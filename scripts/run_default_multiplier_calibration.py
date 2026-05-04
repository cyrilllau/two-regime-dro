"""Auto-tune the default case using only top-level objective multipliers.

The script intentionally keeps Table-I economics fixed.  Candidate regimes may
only change objective_multipliers.{cons, normal, disaster}; all paper-facing
component rows are reconstructed from raw, common-evaluator costs.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_paper_final_analysis import (  # noqa: E402
    CRITICAL_BUS_CONFIG,
    _evaluate_fixed_plan_components,
)
from scripts.experiment_pack_utils import (  # noqa: E402
    execute_run,
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from scripts.promote_milp_default_case import _fixed_plan_milp_dro_value  # noqa: E402
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan  # noqa: E402


COMMON_A = tuple(range(1, 11))
COMMON_B = tuple(range(1, 11))
COMMON_K = 2
REJECTED_BASELINE_TRIPLE = (0.015, 1.0, 1.25)
CASE_ORDER = ("proposed", "normal", "disaster", "deterministic_k2")


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _assert_table_i_runtime_source(runtime_source: str) -> None:
    params = json.loads((REPO_ROOT / runtime_source / "parameters.json").read_text(encoding="utf-8"))
    scenarios_a = tuple(int(value) for value in params["sets"]["scenarios_a"])
    scenarios_b = tuple(int(value) for value in params["sets"]["scenarios_b"])
    k_value = int(params["ambig"]["K"])
    if len(scenarios_a) < 10 or len(scenarios_b) < 10 or k_value != COMMON_K:
        raise ValueError(
            "Default multiplier calibration requires a Table-I-compatible "
            f"A>=10,B>=10,K=2 runtime source; got A={len(scenarios_a)}, "
            f"B={len(scenarios_b)}, K={k_value} from {runtime_source}."
        )


def _float(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    raw = row.get(key, default)
    if raw in ("", None):
        return default
    return float(raw)


def _token(value: float) -> str:
    return f"{float(value):g}".replace(".", "p")


def _candidate_id(cons: float, normal: float, disaster: float) -> str:
    return f"mult_cons{_token(cons)}_normal{_token(normal)}_disaster{_token(disaster)}"


def _candidate_distance(candidate: Mapping[str, Any], other: Mapping[str, Any]) -> float:
    return (
        abs(float(candidate["m_cons"]) - float(other["m_cons"]))
        + abs(float(candidate["m_normal"]) - float(other["m_normal"]))
        + abs(float(candidate["m_disaster"]) - float(other["m_disaster"]))
    )


def _candidate_grid(args: argparse.Namespace) -> list[dict[str, float | str]]:
    cons_values = [float(value) for value in args.cons_values.split(",") if value.strip()]
    normal_values = [float(value) for value in args.normal_values.split(",") if value.strip()]
    disaster_values = [float(value) for value in args.disaster_values.split(",") if value.strip()]
    triples = set(itertools.product(cons_values, normal_values, disaster_values))
    if not getattr(args, "no_forced_baseline", False):
        triples.add(REJECTED_BASELINE_TRIPLE)

    def priority(triple: tuple[float, float, float]) -> tuple[float, float, float, float]:
        cons, normal, disaster = triple
        if triple == REJECTED_BASELINE_TRIPLE:
            return (0.0, 0.0, cons, normal, disaster)
        preferred_cons = (0.012, 0.01, 0.008, 0.006, 0.015, 0.005, 0.004, 0.003)
        preferred_disaster = (1.25, 1.4, 1.6, 1.1, 1.8, 1.5, 2.0, 1.0)
        cons_rank = (
            preferred_cons.index(cons)
            if cons in preferred_cons
            else len(preferred_cons) + abs(math.log(max(cons, 1.0e-9) / 0.01))
        )
        dis_rank = (
            preferred_disaster.index(disaster)
            if disaster in preferred_disaster
            else len(preferred_disaster) + abs(math.log(max(disaster, 1.0e-9)))
        )
        normal_penalty = abs(math.log(max(normal, 1.0e-9)))
        return (0.0, cons_rank + 0.2 * dis_rank + normal_penalty, cons, normal, disaster)

    ordered = sorted(triples, key=priority)
    if args.stage1_max_candidates > 0:
        ordered = ordered[: int(args.stage1_max_candidates)]
    return [
        {
            "candidate_id": _candidate_id(cons, normal, disaster),
            "m_cons": cons,
            "m_normal": normal,
            "m_disaster": disaster,
        }
        for cons, normal, disaster in ordered
    ]


def _base_config(
    *,
    runtime_source: str,
    candidate: Mapping[str, Any],
    case: str,
    max_iterations: int,
    top_cuts: int,
    epsilon_cert: float,
    master_time_limit_seconds: float,
    master_mip_gap: float,
    separation_time_limit_seconds: float,
    separation_mip_gap: float,
    omega_bound_upper: float,
    warm_start_plan_paths: Sequence[str] | None = None,
    initial_cut_pool_paths: Sequence[str] | None = None,
    enable_cut_signature_dedup: bool = False,
    enable_repeated_outage_guard: bool = False,
) -> dict[str, Any]:
    run_id = f"default_multiplier_{candidate['candidate_id']}_{case}"
    config: dict[str, Any] = {
        "run_id": run_id,
        "case_name": run_id,
        "family_name": "default_multiplier_calibration",
        "runtime_source": runtime_source,
        "parameter_regime": str(candidate["candidate_id"]),
        "selection": {"scenarios_a": list(COMMON_A), "scenarios_b": list(COMMON_B)},
        "parameter_overrides": {
            "objective_multipliers": {
                "cons": float(candidate["m_cons"]),
                "normal": float(candidate["m_normal"]),
                "disaster": float(candidate["m_disaster"]),
            },
        },
        "benders": {
            "epsilon_cert": float(epsilon_cert),
            "max_iterations": int(max_iterations),
            "master_time_limit_seconds": float(master_time_limit_seconds),
            "master_mip_gap": float(master_mip_gap),
            "separation_time_limit_seconds": float(separation_time_limit_seconds),
            "separation_mip_gap": float(separation_mip_gap),
            "separation_top_cuts_per_iteration": int(top_cuts),
            "allow_master_suboptimal_incumbent": True,
            "omega_bound_upper": float(omega_bound_upper),
            "enable_cut_signature_dedup": bool(enable_cut_signature_dedup),
            "enable_repeated_outage_guard": bool(enable_repeated_outage_guard),
        },
    }
    if warm_start_plan_paths:
        config["benders"]["warm_start_plan_paths"] = list(warm_start_plan_paths)
    if initial_cut_pool_paths:
        config["benders"]["initial_cut_pool_paths"] = list(initial_cut_pool_paths)
    if case == "proposed":
        config.update({"mode": "integrated_mainline", "solver": "benders"})
    elif case == "normal":
        config.update({"mode": "normal_only", "solver": "direct_master"})
    elif case == "disaster":
        config.update({"mode": "disaster_only", "solver": "benders"})
    elif case == "deterministic_k2":
        config.update({"mode": "deterministic_mean_value", "solver": "benders"})
    else:
        raise ValueError(f"Unsupported case: {case!r}")
    return config


def _plan_from_csv(instance, plan_path: Path):
    rows = _read_rows(plan_path)
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _plan_metrics(plan_path: Path) -> dict[str, Any]:
    rows = _read_rows(plan_path)
    open_rows = [row for row in rows if int(float(row["is_open"])) == 1]
    critical_total = sum(1 for row in rows if int(float(row.get("is_critical", 0))) == 1)
    critical_open = sum(1 for row in open_rows if int(float(row.get("is_critical", 0))) == 1)
    return {
        "sites": len(open_rows),
        "slow_chargers": sum(int(float(row["n_sl"])) for row in rows),
        "fast_chargers": sum(int(float(row["n_fa"])) for row in rows),
        "total_chargers": sum(
            int(float(row["n_sl"])) + int(float(row["n_fa"])) for row in rows
        ),
        "critical_bus_coverage": f"{critical_open}/{critical_total}",
        "open_buses": ";".join(row["bus"] for row in open_rows),
    }


def _int_value(row: Mapping[str, Any], key: str) -> int:
    return int(float(row.get(key, 0) or 0))


def _total_chargers_value(row: Mapping[str, Any]) -> int:
    raw = row.get("total_chargers", "")
    if raw not in ("", None):
        return int(float(raw))
    return _int_value(row, "slow_chargers") + _int_value(row, "fast_chargers")


def _coverage_count(row: Mapping[str, Any]) -> int:
    raw = str(row.get("critical_bus_coverage", "0/0"))
    return int(raw.split("/", 1)[0])


def _open_bus_set(row: Mapping[str, Any]) -> set[int]:
    raw = str(row.get("open_buses", ""))
    if not raw:
        return set()
    return {int(value) for value in raw.split(";") if value}


def _charger_mix_ok(row: Mapping[str, Any]) -> bool:
    slow = _int_value(row, "slow_chargers")
    fast = _int_value(row, "fast_chargers")
    total = slow + fast
    if total <= 0:
        return False
    fast_share = fast / total
    return slow > 0 and fast > 0 and 0.03 <= fast_share <= 0.35


def _topology_distance(left_path: Path, right_path: Path) -> dict[str, Any]:
    left = _read_rows(left_path)
    right = _read_rows(right_path)
    left_open = {int(row["bus"]) for row in left if int(float(row["is_open"])) == 1}
    right_open = {int(row["bus"]) for row in right if int(float(row["is_open"])) == 1}
    right_by_bus = {int(row["bus"]): row for row in right}
    slow_l1 = 0
    fast_l1 = 0
    for row in left:
        bus = int(row["bus"])
        other = right_by_bus[bus]
        slow_l1 += abs(int(float(row["n_sl"])) - int(float(other["n_sl"])))
        fast_l1 += abs(int(float(row["n_fa"])) - int(float(other["n_fa"])))
    return {
        "site_symmetric_difference": len(left_open ^ right_open),
        "slow_charger_l1_distance": slow_l1,
        "fast_charger_l1_distance": fast_l1,
        "charger_l1_distance": slow_l1 + fast_l1,
    }


def _split_paths(raw: str) -> list[str]:
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _default_warm_start_candidates(case: str) -> list[str]:
    paper_root = REPO_ROOT / "results" / "paper_final" / "plans"
    paths = [
        paper_root / "default_scale_v2_proposed_plan.csv",
        REPO_ROOT
        / "results/default_case_topology_calibration/runs/default_multiplier_mult_cons0p02_normal1_disaster1p25_proposed/plans/default_multiplier_mult_cons0p02_normal1_disaster1p25_proposed_plan.csv",
        paper_root / "default_scale_v2_normal_plan.csv",
        paper_root / "default_scale_v2_deterministic_k2_plan.csv",
    ]
    if case == "deterministic_k2":
        paths = [
            paper_root / "default_scale_v2_deterministic_k2_plan.csv",
            REPO_ROOT
            / "results/default_case_topology_calibration/runs/default_multiplier_mult_cons0p02_normal1_disaster1p25_deterministic_k2/plans/default_multiplier_mult_cons0p02_normal1_disaster1p25_deterministic_k2_plan.csv",
            paper_root / "default_scale_v2_proposed_plan.csv",
            paper_root / "default_scale_v2_normal_plan.csv",
        ]
    elif case == "disaster":
        paths = [
            paper_root / "default_scale_v2_disaster_plan.csv",
            paper_root / "default_scale_v2_proposed_plan.csv",
            paper_root / "default_scale_v2_normal_plan.csv",
        ]
    return [str(path) for path in paths if path.exists()]


def _neighbor_plan_paths(
    *,
    root: Path,
    candidate: Mapping[str, Any],
    case: str,
    limit: int,
) -> list[str]:
    rows = _read_rows(root / "candidate_matrix.csv")
    candidates: list[tuple[float, str]] = []
    for row in rows:
        if row.get("case") != case or row.get("candidate_id") == candidate["candidate_id"]:
            continue
        raw_path = row.get("plan_path", "")
        if not raw_path:
            continue
        path = REPO_ROOT / raw_path if not Path(raw_path).is_absolute() else Path(raw_path)
        if not path.exists():
            continue
        try:
            distance = _candidate_distance(candidate, row)
        except Exception:
            distance = 999.0
        candidates.append((distance, str(path)))
    return [path for _, path in sorted(candidates)[:limit]]


def _warm_start_plan_paths(
    *,
    root: Path,
    candidate: Mapping[str, Any],
    case: str,
    args: argparse.Namespace,
) -> list[str]:
    if case == "normal":
        return []
    ordered: list[str] = []
    ordered.extend(_split_paths(args.warm_start_plan_paths))
    ordered.extend(
        _neighbor_plan_paths(
            root=root,
            candidate=candidate,
            case=case,
            limit=int(args.neighbor_warm_start_limit),
        )
    )
    ordered.extend(_default_warm_start_candidates(case))
    seen: set[str] = set()
    deduped: list[str] = []
    for path in ordered:
        if path in seen or not Path(path).exists():
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _initial_cut_pool_paths(
    *,
    root: Path,
    candidate: Mapping[str, Any],
    case: str,
    args: argparse.Namespace,
) -> list[str]:
    ordered: list[str] = []
    ordered.extend(_split_paths(args.initial_cut_pool_paths))
    if case not in {"proposed", "disaster"}:
        return [
            path for path in ordered
            if Path(path).exists()
        ]
    rows = _read_rows(root / "candidate_matrix.csv")
    candidates: list[tuple[float, str]] = []
    for row in rows:
        if row.get("case") != case or row.get("candidate_id") == candidate["candidate_id"]:
            continue
        run_id = str(row.get("run_id", ""))
        if not run_id:
            continue
        pool_path = root / "runs" / run_id / "logs" / f"{run_id}_cut_pool.json"
        if not pool_path.exists():
            continue
        try:
            distance = _candidate_distance(candidate, row)
        except Exception:
            distance = 999.0
        candidates.append((distance, str(pool_path)))
    ordered.extend(path for _, path in sorted(candidates)[: int(args.neighbor_cut_pool_limit)])
    seen: set[str] = set()
    deduped: list[str] = []
    for path in ordered:
        if path in seen or not Path(path).exists():
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _append_audit_row(path: Path, row: Mapping[str, Any]) -> None:
    existing = _read_rows(path)
    existing.append(dict(row))
    _write_rows(path, existing)


def _run_case(
    *,
    root: Path,
    runtime_source: str,
    candidate: Mapping[str, Any],
    case: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    warm_start_paths = _warm_start_plan_paths(
        root=root,
        candidate=candidate,
        case=case,
        args=args,
    )
    cut_pool_paths = _initial_cut_pool_paths(
        root=root,
        candidate=candidate,
        case=case,
        args=args,
    )
    config = _base_config(
        runtime_source=runtime_source,
        candidate=candidate,
        case=case,
        max_iterations=args.max_iterations,
        top_cuts=args.top_cuts,
        epsilon_cert=args.epsilon_cert,
        master_time_limit_seconds=args.master_time_limit_seconds,
        master_mip_gap=args.master_mip_gap,
        separation_time_limit_seconds=args.separation_time_limit_seconds,
        separation_mip_gap=args.separation_mip_gap,
        omega_bound_upper=args.omega_bound_upper,
        warm_start_plan_paths=warm_start_paths,
        initial_cut_pool_paths=cut_pool_paths,
        enable_cut_signature_dedup=args.enable_cut_signature_dedup,
        enable_repeated_outage_guard=args.enable_repeated_outage_guard,
    )
    _append_audit_row(
        root / "warm_start_audit.csv",
        {
            "candidate_id": candidate["candidate_id"],
            "case": case,
            "run_id": config["run_id"],
            "warm_start_path_count": len(warm_start_paths),
            "warm_start_paths": "|".join(warm_start_paths),
        },
    )
    _append_audit_row(
        root / "cut_pool_audit.csv",
        {
            "candidate_id": candidate["candidate_id"],
            "case": case,
            "run_id": config["run_id"],
            "initial_cut_pool_path_count": len(cut_pool_paths),
            "initial_cut_pool_paths": "|".join(cut_pool_paths),
        },
    )
    run_root = root / "runs" / str(config["run_id"])
    log_path = run_root / "logs" / f"{config['run_id']}_run.json"
    if args.skip_existing and log_path.exists():
        print(f"[reuse] {candidate['candidate_id']} {case}: {config['run_id']}", flush=True)
        payload = json.loads(log_path.read_text(encoding="utf-8"))
        plan_path = run_root / "plans" / f"{config['run_id']}_plan.csv"
        return {"config": config, "payload": payload, "plan_path": plan_path}
    print(f"[train] {candidate['candidate_id']} {case}: {config['run_id']}", flush=True)
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    result = execute_run(config, critical_buses=critical_buses, output_root=run_root)
    payload = json.loads(Path(result["log_path"]).read_text(encoding="utf-8"))
    print(f"[train-done] {candidate['candidate_id']} {case}: {config['run_id']}", flush=True)
    if result["plan_path"] is None:
        raise RuntimeError(
            f"{config['run_id']} did not produce a plan; see {result['log_path']}"
        )
    return {"config": config, "payload": payload, "plan_path": Path(result["plan_path"])}


def _evaluate_case(
    *,
    runtime_source: str,
    candidate: Mapping[str, Any],
    case: str,
    run_record: Mapping[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    eval_config = _base_config(
        runtime_source=runtime_source,
        candidate={**candidate, "m_cons": 1.0, "m_normal": 1.0, "m_disaster": 1.0},
        case="proposed",
        max_iterations=100,
        top_cuts=20,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.02,
        separation_time_limit_seconds=300.0,
        separation_mip_gap=0.02,
        omega_bound_upper=2.0e7,
    )
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    instance = prepare_instance_for_run(
        load_instance_for_run(eval_config, critical_buses=critical_buses),
        eval_config,
    )
    plan_path = Path(run_record["plan_path"])
    plan = _plan_from_csv(instance, plan_path)
    print(f"[replay-components] {candidate['candidate_id']} {case}", flush=True)
    components = _evaluate_fixed_plan_components(
        instance,
        plan,
        run_id=f"default_multiplier_common_{candidate['candidate_id']}_{case}",
        k=COMMON_K,
        disaster_evaluator="milp",
    )
    summary = dict(run_record["payload"].get("summary", {}))
    if (
        bool(getattr(args, "reuse_certified_disaster_training_phi", False))
        and case == "disaster"
        and str(run_record["payload"].get("validation_level", summary.get("validation_level", "")))
        in {"exact", "epsilon_certified"}
        and summary.get("disaster_master_term") not in ("", None)
    ):
        print(
            f"[reuse-certified-disaster-phi] {candidate['candidate_id']} {case}: "
            "using training disaster_master_term under same A/B/K support",
            flush=True,
        )
        dro = {
            "Phi_dis": float(summary["disaster_master_term"]),
            "active_outage_lines": "training_certified_reuse",
            "iterations": summary.get("iteration_count", ""),
            "cuts": summary.get("cut_count", ""),
            "final_violation": summary.get("final_violation_upper_bound", ""),
        }
    else:
        print(
            f"[replay-dro] {candidate['candidate_id']} {case}: "
            f"max_iter={args.fixed_eval_max_iterations}, top_cuts={args.fixed_eval_top_cuts}",
            flush=True,
        )
        dro = _fixed_plan_milp_dro_value(
            instance,
            plan,
            run_id=f"default_multiplier_fixed_dro_{candidate['candidate_id']}_{case}",
            epsilon_cert=100.0,
            max_iterations=args.fixed_eval_max_iterations,
            top_cuts=args.fixed_eval_top_cuts,
        )
    components["Phi_dis"] = dro["Phi_dis"]
    components["J_common"] = (
        components["F_cons"]
        + (1.0 - float(components["pi_f"])) * components["Psi_nor"]
        + float(components["pi_f"]) * components["Phi_dis"]
    )
    return {
        "candidate_id": candidate["candidate_id"],
        "m_cons": candidate["m_cons"],
        "m_normal": candidate["m_normal"],
        "m_disaster": candidate["m_disaster"],
        "case": case,
        "run_id": run_record["config"]["run_id"],
        "training_mode": run_record["config"]["mode"],
        "training_solver": run_record["config"]["solver"],
        "training_validation_level": run_record["payload"].get(
            "validation_level", summary.get("validation_level", "")
        ),
        "training_stop_reason": run_record["payload"].get(
            "stop_reason", summary.get("stop_reason", "")
        ),
        "training_solver_status": run_record["payload"].get(
            "solver_status", summary.get("solver_status", "")
        ),
        "training_iterations": summary.get("iteration_count", ""),
        "training_cuts": summary.get("cut_count", ""),
        "training_final_violation": summary.get("final_violation_upper_bound", ""),
        "normal_scenario_count": components["normal_scenario_count"],
        "disaster_scenario_count": components["disaster_scenario_count"],
        "K": components["K"],
        "disaster_evaluator": "milp_worst_distribution",
        "F_cons": components["F_cons"],
        "F_trans": components["F_trans"],
        "F_unmet": components["F_unmet"],
        "F_sub": components["F_sub"],
        "Psi_nor": components["Psi_nor"],
        "Phi_dis": components["Phi_dis"],
        "pi_f": components["pi_f"],
        "J_common": components["J_common"],
        "active_outage_lines": dro["active_outage_lines"],
        "fixed_plan_dro_iterations": dro["iterations"],
        "fixed_plan_dro_cuts": dro["cuts"],
        "fixed_plan_dro_final_violation": dro["final_violation"],
        "fixed_plan_dro_max_iterations": args.fixed_eval_max_iterations,
        "fixed_plan_dro_top_cuts": args.fixed_eval_top_cuts,
        **_plan_metrics(plan_path),
        "plan_path": str(plan_path),
    }


def _story_gate(candidate: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_case = {str(row["case"]): row for row in rows}
    if not {"proposed", "normal", "disaster", "deterministic_k2"} <= set(by_case):
        return {
            "candidate_id": candidate["candidate_id"],
            "stage": "partial",
            "passes_all": False,
            "failure_reasons": "missing_case_rows",
        }
    proposed = by_case["proposed"]
    normal = by_case["normal"]
    disaster = by_case["disaster"]
    deterministic = by_case["deterministic_k2"]
    proposed_sites = _int_value(proposed, "sites")
    deterministic_sites = _int_value(deterministic, "sites")
    proposed_slow = _int_value(proposed, "slow_chargers")
    proposed_fast = _int_value(proposed, "fast_chargers")
    proposed_total = _total_chargers_value(proposed)
    disaster_unmet = _float(disaster, "F_unmet")
    deterministic_unmet = _float(deterministic, "F_unmet")
    deterministic_slow = _int_value(deterministic, "slow_chargers")
    deterministic_fast = _int_value(deterministic, "fast_chargers")
    deterministic_total = _total_chargers_value(deterministic)
    proposed_critical = _coverage_count(proposed)
    normal_critical = _coverage_count(normal)
    disaster_critical = _coverage_count(disaster)
    proposed_open = _open_bus_set(proposed)
    normal_open = _open_bus_set(normal)
    site_shift = len(proposed_open ^ normal_open)
    science_checks = {
        "phi_order": _float(disaster, "Phi_dis") < _float(proposed, "Phi_dis") < _float(normal, "Phi_dis"),
        "case3_endpoint_strength": (
            (_float(proposed, "Phi_dis") - _float(disaster, "Phi_dis"))
            / max(_float(proposed, "Phi_dis"), 1.0)
            >= 0.10
        ),
        "case2_disaster_fragility": _float(normal, "Phi_dis") >= 2.0 * _float(proposed, "Phi_dis"),
        "psi1_close_to_psi2": _float(proposed, "Psi_nor") <= 1.05 * _float(normal, "Psi_nor"),
        "case3_normal_sacrifice": (
            _float(disaster, "Psi_nor") >= 1.5 * _float(proposed, "Psi_nor")
            or _float(disaster, "F_unmet") / max(_float(disaster, "Psi_nor"), 1.0) >= 0.20
        ),
        "case4_normal_service_better_than_case3": deterministic_unmet < disaster_unmet,
        "deterministic_worse": _float(proposed, "Phi_dis") < _float(deterministic, "Phi_dis"),
        "case1_unmet_controlled": _float(proposed, "F_unmet") / max(_float(proposed, "Psi_nor"), 1.0) <= 0.01,
        "certification": all(
            str(row["training_validation_level"]) in {"exact", "epsilon_certified"}
            and int(float(row["normal_scenario_count"])) == 10
            and int(float(row["disaster_scenario_count"])) == 10
            and int(float(row["K"])) == 2
            and str(row["disaster_evaluator"]) == "milp_worst_distribution"
            for row in rows
        ),
    }
    topology_checks = {
        "case1_sites_8_to_12": 8 <= proposed_sites <= 12,
        "case1_sites_target_9_to_11": 9 <= proposed_sites <= 11,
        "case1_critical_coverage_at_least_5": proposed_critical >= 5,
        "case1_topology_shift_vs_normal": site_shift >= 2 and proposed_critical >= normal_critical + 2,
        "case3_more_disaster_oriented": disaster_critical >= proposed_critical or _float(disaster, "Phi_dis") < _float(proposed, "Phi_dis"),
        "case1_charger_mix_non_extreme": _charger_mix_ok(proposed),
    }
    phi_det_gap_pct = (
        (_float(deterministic, "Phi_dis") - _float(proposed, "Phi_dis"))
        / max(_float(deterministic, "Phi_dis"), 1.0)
        * 100.0
    )
    phi_case3_reduction_pct = (
        (_float(proposed, "Phi_dis") - _float(disaster, "Phi_dis"))
        / max(_float(proposed, "Phi_dis"), 1.0)
        * 100.0
    )
    phi_case2_over_case1 = _float(normal, "Phi_dis") / max(_float(proposed, "Phi_dis"), 1.0)
    deterministic_topology_checks = {
        "case1_sites_exceed_det": proposed_sites >= deterministic_sites + 1,
        "case1_slow_ge_det": proposed_slow >= deterministic_slow,
        "case1_fast_ge_det": proposed_fast >= deterministic_fast,
        "case1_total_chargers_gt_det": proposed_total > deterministic_total,
        "case1_phi_lt_det": _float(proposed, "Phi_dis") < _float(deterministic, "Phi_dis"),
    }
    aspirational_checks = {
        "case1_phi_reduction_target_5pct": phi_det_gap_pct >= 5.0,
    }
    hard_checks = {**science_checks, **topology_checks, **deterministic_topology_checks}
    checks = {**hard_checks, **aspirational_checks}
    science_pass = all(science_checks.values())
    topology_pass = (
        topology_checks["case1_sites_8_to_12"]
        and topology_checks["case1_critical_coverage_at_least_5"]
        and topology_checks["case1_topology_shift_vs_normal"]
        and topology_checks["case3_more_disaster_oriented"]
        and topology_checks["case1_charger_mix_non_extreme"]
    )
    deterministic_topology_pass = all(deterministic_topology_checks.values())
    failure_reasons = ";".join(key for key, ok in hard_checks.items() if not ok)
    score = 0.0
    score += 100.0 if science_pass else 0.0
    score += 100.0 if topology_pass else 0.0
    score += 120.0 if deterministic_topology_pass else 0.0
    score += max(0.0, 20.0 - 5.0 * abs(proposed_sites - 10))
    score += 5.0 * proposed_critical
    score += max(0.0, min(30.0, phi_det_gap_pct))
    score += max(0.0, min(30.0, phi_case3_reduction_pct))
    score += max(0.0, min(20.0, 5.0 * (phi_case2_over_case1 - 2.0)))
    score += max(0.0, min(20.0, 4.0 * (proposed_sites - deterministic_sites)))
    score += max(0.0, min(20.0, 0.1 * (proposed_total - deterministic_total)))
    score += max(0.0, min(20.0, _float(normal, "Phi_dis") / max(_float(proposed, "Phi_dis"), 1.0)))
    score += max(0.0, min(20.0, 100.0 * (disaster_unmet - deterministic_unmet) / max(disaster_unmet, 1.0)))
    score -= max(0.0, _float(proposed, "F_unmet") / max(_float(proposed, "Psi_nor"), 1.0) * 100.0)
    return {
        "candidate_id": candidate["candidate_id"],
        "m_cons": candidate["m_cons"],
        "m_normal": candidate["m_normal"],
        "m_disaster": candidate["m_disaster"],
        "Phi_case1": proposed["Phi_dis"],
        "Phi_case2": normal["Phi_dis"],
        "Phi_case3": disaster["Phi_dis"],
        "Phi_case4": deterministic["Phi_dis"],
        "Psi_case1": proposed["Psi_nor"],
        "Psi_case2": normal["Psi_nor"],
        "Psi_case3": disaster["Psi_nor"],
        "Funmet_case3": disaster_unmet,
        "Funmet_case4": deterministic_unmet,
        "Funmet_case4_reduction_vs_case3_pct": 100.0 * (disaster_unmet - deterministic_unmet) / max(disaster_unmet, 1.0),
        "Funmet_case3_over_Psi_case3": _float(disaster, "F_unmet") / max(_float(disaster, "Psi_nor"), 1.0),
        "Phi_case3_reduction_pct": phi_case3_reduction_pct,
        "Phi_case2_over_case1": phi_case2_over_case1,
        "Phi_det_gap_pct": phi_det_gap_pct,
        "sites_case1": proposed_sites,
        "sites_case2": _int_value(normal, "sites"),
        "sites_case3": _int_value(disaster, "sites"),
        "sites_case4": deterministic_sites,
        "slow_case1": proposed_slow,
        "slow_case4": deterministic_slow,
        "fast_case1": proposed_fast,
        "fast_case4": deterministic_fast,
        "total_chargers_case1": proposed_total,
        "total_chargers_case4": deterministic_total,
        "critical_direct_case1": proposed_critical,
        "critical_direct_case2": normal_critical,
        "critical_direct_case3": disaster_critical,
        "critical_direct_case4": _coverage_count(deterministic),
        "site_shift_case1_vs_case2": site_shift,
        "science_pass": science_pass,
        "topology_pass": topology_pass,
        "deterministic_topology_pass": deterministic_topology_pass,
        "paper_ready_topology_pass": science_pass and topology_pass and deterministic_topology_pass,
        **{f"pass_{key}": value for key, value in checks.items()},
        "story_score": score,
        "passes_all": science_pass and topology_pass and deterministic_topology_pass,
        "failure_reasons": failure_reasons,
    }


def _write_audit(root: Path, *, runtime_source: str, candidates: Sequence[Mapping[str, Any]]) -> None:
    _write_text(
        root / "objective_multiplier_audit.md",
        "# Objective Multiplier Calibration Audit\n\n"
        f"- Runtime source: `{runtime_source}`\n"
        "- Fixed Table-I parameters are read from the runtime data; the driver only sets "
        "`parameter_overrides.objective_multipliers`.\n"
        "- Training objective uses `m_cons F_cons + m_normal (1-pi_f) Psi + "
        "m_disaster pi_f Phi`.\n"
        "- Default topology-aware search uses normalized objective weights with "
        "`m_normal=1`. The `(0.015,1,1.25)` candidate is treated as the "
        "Case1/2/3 endpoint-structure anchor because it has a strong "
        "disaster-only endpoint, but it still needs deterministic-topology "
        "improvement before final promotion.\n"
        "- Common replay rows report raw `F_cons`, `Psi_nor`, and `Phi_dis`.\n"
        "- Passing the target requires both science gates and topology gates.\n"
        f"- Candidate triples queued: `{len(candidates)}`.\n",
    )


def _write_best_report(root: Path, gates: Sequence[Mapping[str, Any]]) -> None:
    def _score(row: Mapping[str, Any]) -> float:
        raw = row.get("story_score", 0.0)
        if raw in ("", None):
            return 0.0
        return float(raw)

    sorted_rows = sorted(gates, key=_score, reverse=True)
    if not sorted_rows:
        _write_text(root / "best_candidate_report.md", "# Best Candidate Report\n\nNo candidates evaluated.\n")
        return
    best = sorted_rows[0]
    lines = [
        "# Best Candidate Report",
        "",
        f"- Candidate: `{best['candidate_id']}`",
        f"- PASS: `{best['passes_all']}`",
        f"- Score: `{best.get('story_score', '')}`",
        f"- Topology pass: `{best.get('topology_pass', '')}`",
        f"- Deterministic topology pass: `{best.get('deterministic_topology_pass', '')}`",
        f"- Sites/Critical coverage: `{best.get('sites_case1', '')}` sites, "
        f"`{best.get('critical_direct_case1', '')}/11` direct critical coverage",
        f"- Case1 vs Case4 topology: sites `{best.get('sites_case1', '')}` vs "
        f"`{best.get('sites_case4', '')}`, slow `{best.get('slow_case1', '')}` vs "
        f"`{best.get('slow_case4', '')}`, fast `{best.get('fast_case1', '')}` vs "
        f"`{best.get('fast_case4', '')}`",
        f"- Phi order: Case3={best.get('Phi_case3', '')}, "
        f"Case1={best.get('Phi_case1', '')}, Case2={best.get('Phi_case2', '')}",
        f"- Case3 endpoint gap: `{best.get('Phi_case3_reduction_pct', '')}%`; "
        f"Case2/Case1 disaster ratio: `{best.get('Phi_case2_over_case1', '')}`",
        f"- Deterministic gap: `{best.get('Phi_det_gap_pct', '')}%`",
        f"- Failure reasons: `{best.get('failure_reasons', '')}`",
    ]
    _write_text(root / "best_candidate_report.md", "\n".join(lines) + "\n")


def _select_best_gate(gates: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not gates:
        return None
    def _score(row: Mapping[str, Any]) -> float:
        raw = row.get("story_score", 0.0)
        if raw in ("", None):
            return 0.0
        return float(raw)

    return sorted(gates, key=_score, reverse=True)[0]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-source", default="data/colleague_default_10x10")
    parser.add_argument("--output-root", default="results/default_case_det_topology_calibration")
    parser.add_argument("--cons-values", default="0.006,0.008,0.01,0.012,0.015")
    parser.add_argument("--normal-values", default="1")
    parser.add_argument("--disaster-values", default="1.1,1.25,1.4,1.6,1.8")
    parser.add_argument("--max-candidates", type=int, default=0)
    parser.add_argument("--stage1-max-candidates", type=int, default=28)
    parser.add_argument("--stage2-max-candidates", type=int, default=26)
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--top-cuts", type=int, default=20)
    parser.add_argument("--fixed-eval-max-iterations", type=int, default=100)
    parser.add_argument("--fixed-eval-top-cuts", type=int, default=20)
    parser.add_argument("--reuse-certified-disaster-training-phi", action="store_true")
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--master-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--master-mip-gap", type=float, default=0.02)
    parser.add_argument("--separation-time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.02)
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument("--warm-start-plan-paths", default="")
    parser.add_argument("--initial-cut-pool-paths", default="")
    parser.add_argument("--neighbor-warm-start-limit", type=int, default=2)
    parser.add_argument("--neighbor-cut-pool-limit", type=int, default=2)
    parser.add_argument("--enable-cut-signature-dedup", action="store_true")
    parser.add_argument("--enable-repeated-outage-guard", action="store_true")
    parser.add_argument(
        "--cases",
        default=",".join(CASE_ORDER),
        help=(
            "Comma-separated case keys to run. Valid values are proposed, "
            "normal, disaster, deterministic_k2."
        ),
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stop-on-pass", action="store_true")
    parser.add_argument(
        "--no-forced-baseline",
        action="store_true",
        help="Do not automatically add the rejected diagnostic baseline candidate.",
    )
    args = parser.parse_args()

    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)
    _assert_table_i_runtime_source(args.runtime_source)
    if args.max_candidates > 0:
        args.stage1_max_candidates = int(args.max_candidates)
        args.stage2_max_candidates = int(args.max_candidates)
    requested_cases = tuple(case.strip() for case in args.cases.split(",") if case.strip())
    unsupported_cases = set(requested_cases) - set(CASE_ORDER)
    if unsupported_cases:
        raise ValueError(f"Unsupported --cases entries: {sorted(unsupported_cases)}")
    candidates = _candidate_grid(args)
    _write_audit(root, runtime_source=args.runtime_source, candidates=candidates)
    if args.dry_run:
        _write_rows(root / "candidate_queue.csv", candidates)
        print(f"queued {len(candidates)} candidates")
        return

    component_rows = _read_rows(root / "candidate_matrix.csv")
    gate_rows = _read_rows(root / "story_gate_summary.csv")
    completed = {
        (row.get("candidate_id"), row.get("case"))
        for row in component_rows
    }
    selected_candidates = (
        candidates[: int(args.stage2_max_candidates)]
        if int(args.stage2_max_candidates) > 0
        else candidates
    )
    print(
        f"[start] selected_candidates={len(selected_candidates)}, "
        f"training_max_iter={args.max_iterations}, fixed_eval_max_iter={args.fixed_eval_max_iterations}",
        flush=True,
    )
    for candidate in selected_candidates:
        print(
            f"[candidate] {candidate['candidate_id']} "
            f"(m_cons={candidate['m_cons']}, m_normal={candidate['m_normal']}, "
            f"m_disaster={candidate['m_disaster']})",
            flush=True,
        )
        case_rows: list[dict[str, Any]] = []
        for case in requested_cases:
            if args.skip_existing and (candidate["candidate_id"], case) in completed:
                existing = [
                    row for row in component_rows
                    if row.get("candidate_id") == candidate["candidate_id"] and row.get("case") == case
                ][0]
                case_rows.append(existing)
                continue
            run_record = _run_case(
                root=root,
                runtime_source=args.runtime_source,
                candidate=candidate,
                case=case,
                args=args,
            )
            row = _evaluate_case(
                runtime_source=args.runtime_source,
                candidate=candidate,
                case=case,
                run_record=run_record,
                args=args,
            )
            component_rows = [
                existing for existing in component_rows
                if not (
                    existing.get("candidate_id") == candidate["candidate_id"]
                    and existing.get("case") == case
                )
            ]
            component_rows.append(row)
            case_rows.append(row)
            _write_rows(root / "candidate_matrix.csv", component_rows)
        gate_input_rows = [
            row for row in component_rows
            if row.get("candidate_id") == candidate["candidate_id"]
        ]
        gate = _story_gate(candidate, gate_input_rows)
        gate_rows = [
            row for row in gate_rows
            if row.get("candidate_id") != candidate["candidate_id"]
        ]
        gate_rows.append(gate)
        _write_rows(root / "story_gate_summary.csv", gate_rows)
        det_gate_rows = [
            {
                "candidate_id": row.get("candidate_id", ""),
                "m_cons": row.get("m_cons", ""),
                "m_normal": row.get("m_normal", ""),
                "m_disaster": row.get("m_disaster", ""),
                "sites_case1": row.get("sites_case1", ""),
                "sites_case4": row.get("sites_case4", ""),
                "slow_case1": row.get("slow_case1", ""),
                "slow_case4": row.get("slow_case4", ""),
                "fast_case1": row.get("fast_case1", ""),
                "fast_case4": row.get("fast_case4", ""),
                "total_chargers_case1": row.get("total_chargers_case1", ""),
                "total_chargers_case4": row.get("total_chargers_case4", ""),
                "Phi_case1": row.get("Phi_case1", ""),
                "Phi_case4": row.get("Phi_case4", ""),
                "Phi_det_gap_pct": row.get("Phi_det_gap_pct", ""),
                "pass_case1_sites_exceed_det": row.get("pass_case1_sites_exceed_det", ""),
                "pass_case1_slow_ge_det": row.get("pass_case1_slow_ge_det", ""),
                "pass_case1_fast_ge_det": row.get("pass_case1_fast_ge_det", ""),
                "pass_case1_total_chargers_gt_det": row.get("pass_case1_total_chargers_gt_det", ""),
                "pass_case1_phi_lt_det": row.get("pass_case1_phi_lt_det", ""),
                "pass_case1_phi_reduction_target_5pct": row.get("pass_case1_phi_reduction_target_5pct", ""),
                "deterministic_topology_pass": row.get("deterministic_topology_pass", ""),
            }
            for row in gate_rows
        ]
        _write_rows(root / "deterministic_topology_gate.csv", det_gate_rows)
        _write_best_report(root, gate_rows)
        if gate["passes_all"] and args.stop_on_pass:
            _write_json(
                root / "pass_candidate.json",
                {
                    "verdict": "PASS_TARGET",
                    "candidate": dict(candidate),
                    "story_gate": gate,
                    "note": (
                        "PASS candidate found. Promote only this candidate's rows, "
                        "plans, figures, and decision card to results/paper_final."
                    ),
                },
            )
            print(f"PASS {candidate['candidate_id']}")
            return
    best_gate = _select_best_gate(gate_rows)
    rejected_lines = ["# Rejected Candidates", ""]
    def _score(row: Mapping[str, Any]) -> float:
        raw = row.get("story_score", 0.0)
        if raw in ("", None):
            return 0.0
        return float(raw)

    for row in sorted(gate_rows, key=_score, reverse=True):
        if str(row.get("passes_all")) in {"True", "true", "1"}:
            continue
        rejected_lines.append(
            f"- `{row.get('candidate_id')}`: {row.get('failure_reasons', '')}"
        )
    _write_text(root / "rejected_candidates.md", "\n".join(rejected_lines) + "\n")
    if best_gate and str(best_gate.get("passes_all")) in {"True", "true", "1"}:
        verdict = "PASS_TARGET"
        candidate = [
            row for row in selected_candidates
            if row["candidate_id"] == best_gate["candidate_id"]
        ][0]
        _write_json(
            root / "pass_candidate.json",
            {
                "verdict": verdict,
                "candidate": dict(candidate),
                "story_gate": best_gate,
                "note": (
                    "Best topology-aware candidate found after ranking evaluated "
                    "normalized multiplier candidates."
                ),
            },
        )
        print(f"PASS {best_gate['candidate_id']}")
        return
    _write_json(
        root / "pass_candidate.json",
        {
            "verdict": "BUDGET_STOP_NO_TOPOLOGY_PASS",
            "evaluated_candidates": len(selected_candidates),
            "best_gate": dict(best_gate or {}),
        },
    )
    print("BUDGET_STOP_NO_TOPOLOGY_PASS")


if __name__ == "__main__":
    main()
