"""Calibrate the default 10x10,K=2 paper-scale case with strict gates.

The driver intentionally separates training from reporting.  It trains
candidate first-stage plans under their benchmark definitions, freezes each
plan, and replays all plans under one common exact-primal DRO evaluator.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_paper_final_analysis import (  # noqa: E402
    CRITICAL_BUS_CONFIG,
    _evaluate_fixed_plan_components,
)
from scripts.experiment_pack_utils import (  # noqa: E402
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
    write_plan_csv,
)
from src.audit.experiment_summary import ExperimentRunSummary  # noqa: E402
from src.production.master_problem import solve_master_problem  # noqa: E402
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan  # noqa: E402


DEFAULT_ROOT = Path("results/default_scale_calibration")
DEFAULT_BASE_CONFIG = Path(
    "results/exact_enum_benders_top20_ev055_100budget/logs/"
    "exact_enum_top20_cls200_pi0p3_ev055_100budget_config.json"
)
COMMON_A = tuple(range(1, 11))
COMMON_B = tuple(range(1, 11))
COMMON_K = 2


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload["run_config"] if "run_config" in payload else payload)


def _float_tokens(raw: str) -> list[float]:
    return [float(token.strip()) for token in raw.split(",") if token.strip()]


def _cls_pairs(raw: str) -> list[tuple[float, float]]:
    pairs: list[tuple[float, float]] = []
    for token in raw.split(","):
        if not token.strip():
            continue
        left, right = token.split(":", maxsplit=1)
        pairs.append((float(left), float(right)))
    return pairs


def _candidate_id(
    *,
    ev_scale: float,
    cfix_mult: float,
    ccons_sl_mult: float,
    cls_critical: float,
    cls_noncritical: float,
    pi_f: float,
) -> str:
    def clean(value: float) -> str:
        return f"{value:g}".replace(".", "p")

    return (
        f"ev{clean(ev_scale)}_cfix{clean(cfix_mult)}_"
        f"csl{clean(ccons_sl_mult)}_cls{clean(cls_critical)}x{clean(cls_noncritical)}_"
        f"pi{clean(pi_f)}"
    )


def _candidate_configs(args: argparse.Namespace) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for ev_scale in _float_tokens(args.ev_scales):
        for cfix_mult in _float_tokens(args.cfix_multipliers):
            for ccons_sl_mult in _float_tokens(args.ccons_sl_multipliers):
                for cls_critical, cls_noncritical in _cls_pairs(args.cls_pairs):
                    for pi_f in _float_tokens(args.pi_values):
                        for nbar_sl in [int(value) for value in _float_tokens(args.nbar_sl_values)]:
                            for nbar_fa in [int(value) for value in _float_tokens(args.nbar_fa_values)]:
                                for psl_scale in _float_tokens(args.p_sl_scales):
                                  for ccons_fa_mult in _float_tokens(args.ccons_fa_multipliers):
                                   for ctrans_mult in _float_tokens(args.ctrans_multipliers):
                                    candidate_id = _candidate_id(
                                        ev_scale=ev_scale,
                                        cfix_mult=cfix_mult,
                                        ccons_sl_mult=ccons_sl_mult,
                                        cls_critical=cls_critical,
                                        cls_noncritical=cls_noncritical,
                                        pi_f=pi_f,
                                    )
                                    if nbar_sl != 25 or nbar_fa != 10:
                                        candidate_id = f"{candidate_id}_nbar{nbar_sl}x{nbar_fa}"
                                    if abs(psl_scale - 1.0) > 1e-12:
                                        candidate_id = f"{candidate_id}_psl{str(psl_scale).replace('.', 'p')}"
                                    if abs(ccons_fa_mult - 1.0) > 1e-12:
                                        candidate_id = f"{candidate_id}_cfa{str(ccons_fa_mult).replace('.', 'p')}"
                                    if abs(ctrans_mult - 1.0) > 1e-12:
                                        candidate_id = f"{candidate_id}_ctr{str(ctrans_mult).replace('.', 'p')}"
                                    capacity_profile = str(args.capacity_profile)
                                    if capacity_profile and capacity_profile != "none":
                                        candidate_id = f"{candidate_id}_cap{capacity_profile}"
                                    slow_block_threshold = int(args.slow_block_threshold)
                                    slow_extra_mult = float(args.slow_extra_cost_multiplier)
                                    if slow_block_threshold > 0 and slow_extra_mult > 1.0:
                                        candidate_id = (
                                            f"{candidate_id}_slblk{slow_block_threshold}"
                                            f"x{str(slow_extra_mult).replace('.', 'p')}"
                                        )
                                    cunmet_mult = float(args.cunmet_multiplier)
                                    if abs(cunmet_mult - 1.0) > 1e-12:
                                        candidate_id = (
                                            f"{candidate_id}_cunmet"
                                            f"{str(cunmet_mult).replace('.', 'p')}"
                                        )
                                    candidates.append(
                                        {
                                            "ev_scale": ev_scale,
                                            "cfix_mult": cfix_mult,
                                            "ccons_sl_mult": ccons_sl_mult,
                                            "ccons_fa_mult": ccons_fa_mult,
                                            "ctrans_mult": ctrans_mult,
                                            "cls_critical": cls_critical,
                                            "cls_noncritical": cls_noncritical,
                                            "pi_f": pi_f,
                                            "nbar_sl": nbar_sl,
                                            "nbar_fa": nbar_fa,
                                            "p_sl_scale": psl_scale,
                                            "capacity_profile": capacity_profile,
                                            "slow_block_threshold": slow_block_threshold,
                                            "slow_extra_cost_multiplier": slow_extra_mult,
                                            "cunmet_multiplier": cunmet_mult,
                                            "candidate_id": candidate_id,
                                        }
                                    )
    if args.max_candidates > 0:
        return candidates[: int(args.max_candidates)]
    return candidates


def _set_k(config: dict[str, Any], k_value: int) -> None:
    overrides = copy.deepcopy(config.get("parameter_overrides", {}))
    ambiguity = dict(overrides.get("ambiguity", {}))
    ambiguity["k_max_outages"] = int(k_value)
    overrides["ambiguity"] = ambiguity
    config["parameter_overrides"] = overrides


def _build_run_config(
    base: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    case: str,
) -> dict[str, Any]:
    config = copy.deepcopy(dict(base))
    candidate_id = str(candidate["candidate_id"])
    config["family_name"] = "default_scale_calibration"
    config["parameter_regime"] = candidate_id
    config["runtime_source"] = str(config.get("runtime_source", "data/runtime_12_synth_100"))
    config["selection"] = {
        "scenarios_a": list(COMMON_A),
        "scenarios_b": list(COMMON_B),
    }
    config["ev_penetration_scale"] = float(candidate["ev_scale"])
    config["run_id"] = f"default_{candidate_id}_{case}"
    config["case_name"] = config["run_id"]

    overrides = copy.deepcopy(config.get("parameter_overrides", {}))
    economics = dict(overrides.get("economics", {}))
    economics["pi_f"] = float(candidate["pi_f"])
    economics["cfix"] = float(economics.get("cfix", 153600.0)) * float(candidate["cfix_mult"])
    economics["ccons_sl"] = float(economics.get("ccons_sl", 540.07)) * float(
        candidate["ccons_sl_mult"]
    )
    economics["ccons_fa"] = float(economics.get("ccons_fa", 25000.0)) * float(
        candidate["ccons_fa_mult"]
    )
    if int(candidate.get("slow_block_threshold", 0)) > 0:
        economics["ccons_sl_extra_multiplier"] = float(
            candidate.get("slow_extra_cost_multiplier", 1.0)
        )
    if abs(float(candidate.get("cunmet_multiplier", 1.0)) - 1.0) > 1e-12:
        economics["cunmet"] = float(economics.get("cunmet", 3.0)) * float(
            candidate["cunmet_multiplier"]
        )
    ctrans_source = economics.get("ctrans_scalar", economics.get("ctrans", 0.0435))
    economics["ctrans_scalar"] = float(ctrans_source) * float(candidate["ctrans_mult"])
    overrides["economics"] = economics
    overrides["disaster_objective"] = {
        "cls_critical": float(candidate["cls_critical"]),
        "cls_noncritical": float(candidate["cls_noncritical"]),
    }
    ev = dict(overrides.get("ev", {}))
    ev["nbar_sl"] = int(candidate["nbar_sl"])
    ev["nbar_fa"] = int(candidate["nbar_fa"])
    ev["p_ev_rated_sl"] = float(ev.get("p_ev_rated_sl", 7.0)) * float(candidate["p_sl_scale"])
    if str(candidate.get("capacity_profile", "none")) != "none":
        ev["capacity_profile"] = str(candidate["capacity_profile"])
    if int(candidate.get("slow_block_threshold", 0)) > 0:
        ev["slow_block_threshold"] = int(candidate["slow_block_threshold"])
    overrides["ev"] = ev
    config["parameter_overrides"] = overrides

    if case == "proposed":
        config["mode"] = "integrated_mainline"
        config["solver"] = "benders"
        _set_k(config, COMMON_K)
    elif case == "normal":
        config["mode"] = "normal_only"
        config["solver"] = "direct_master"
        _set_k(config, COMMON_K)
    elif case == "deterministic":
        config["mode"] = "deterministic_mean_value"
        config["solver"] = "benders"
        _set_k(config, 0)
    elif case == "deterministic_k1":
        config["mode"] = "deterministic_mean_value"
        config["solver"] = "benders"
        _set_k(config, 1)
    elif case == "deterministic_k2":
        config["mode"] = "deterministic_mean_value"
        config["solver"] = "benders"
        _set_k(config, 2)
    elif case == "disaster":
        config["mode"] = "disaster_only"
        config["solver"] = "benders"
        _set_k(config, COMMON_K)
    else:
        raise ValueError(f"Unsupported case={case!r}")

    config["benders"] = {
        "epsilon_cert": 100.0,
        "max_iterations": 100,
        "master_time_limit_seconds": 60.0,
        "master_mip_gap": 0.02,
        "allow_master_suboptimal_incumbent": True,
    }
    return config


def _write_config(root: Path, config: Mapping[str, Any]) -> Path:
    path = root / "configs" / f"{config['run_id']}_config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_config": dict(config)}, indent=2), encoding="utf-8")
    return path


def _run_exact_benders(
    *,
    root: Path,
    config: Mapping[str, Any],
    args: argparse.Namespace,
) -> Path:
    run_id = str(config["run_id"])
    run_root = root / "runs" / run_id
    summary_path = run_root / "summary.csv"
    if args.skip_existing and summary_path.exists():
        return run_root

    config_path = _write_config(root, config)
    command = [
        sys.executable,
        "scripts/run_exact_enumeration_benders.py",
        "--config-log",
        str(config_path),
        "--output-root",
        str(run_root),
        "--run-id",
        run_id,
        "--max-iterations",
        str(args.max_iterations),
        "--top-cuts",
        str(args.top_cuts),
        "--epsilon-cert",
        str(args.epsilon_cert),
        "--master-time-limit-seconds",
        str(args.master_time_limit_seconds),
        "--master-mip-gap",
        str(args.master_mip_gap),
        "--allow-master-suboptimal-incumbent",
    ]
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    return run_root


def _run_direct_master(
    *,
    root: Path,
    config: Mapping[str, Any],
    args: argparse.Namespace,
) -> Path:
    run_id = str(config["run_id"])
    run_root = root / "runs" / run_id
    summary_path = run_root / "summary.csv"
    if args.skip_existing and summary_path.exists():
        return run_root

    (run_root / "plans").mkdir(parents=True, exist_ok=True)
    (run_root / "logs").mkdir(parents=True, exist_ok=True)
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    instance = prepare_instance_for_run(
        load_instance_for_run(config, critical_buses=critical_buses),
        config,
    )
    _, solution = solve_master_problem(
        instance,
        normal_scenario_ids=instance.sets.loaded_normal_scenarios,
        time_limit_seconds=float(args.normal_master_time_limit_seconds),
        mip_gap=float(args.master_mip_gap),
        allow_suboptimal_incumbent=False,
        model_name=f"{run_id}_direct_master",
        log_to_console=False,
    )
    plan_rows = [
        {
            "bus": bus,
            "is_open": int(solution.first_stage_solution.z_by_bus[bus]),
            "n_sl": int(solution.first_stage_solution.n_sl_by_bus[bus]),
            "n_fa": int(solution.first_stage_solution.n_fa_by_bus[bus]),
            "is_critical": int(bool(instance.is_critical_by_bus and instance.is_critical_by_bus[bus])),
            "region": "",
        }
        for bus in instance.sets.buses
    ]
    write_plan_csv(run_root / "plans" / f"{run_id}_plan.csv", plan_rows)
    summary = ExperimentRunSummary(
        run_id=run_id,
        family_name=str(config["family_name"]),
        case_name=str(config["case_name"]),
        parameter_regime=str(config["parameter_regime"]),
        validation_level="exact" if solution.model_status == "OPTIMAL" else "failed",
        stop_reason="direct_optimal" if solution.model_status == "OPTIMAL" else solution.model_status,
        solver_status=str(solution.model_status),
        total_objective=float(solution.objective_value or 0.0),
        construction_cost=float(solution.construction_cost_value),
        weighted_normal_term=float(solution.averaged_normal_cost_value),
        unweighted_normal_term=float(solution.unweighted_average_normal_cost_value),
        disaster_master_term=float(solution.disaster_master_cost_value),
        alpha=float(solution.alpha_value),
        lambda_times_FP=float(solution.lambda_fp_value),
        iteration_count=0,
        cut_count=0,
        final_violation_upper_bound=0.0,
        opened_bus_count=sum(solution.first_stage_solution.z_by_bus.values()),
        total_slow_chargers=sum(solution.first_stage_solution.n_sl_by_bus.values()),
        total_fast_chargers=sum(solution.first_stage_solution.n_fa_by_bus.values()),
    )
    _write_rows(summary_path, [summary.to_csv_row()])
    (run_root / "logs" / f"{run_id}_run.json").write_text(
        json.dumps(
            {
                "run_config": dict(config),
                "summary": summary.to_csv_row(),
                "plan_rows": plan_rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return run_root


def _plan_path_for(run_root: Path, run_id: str) -> Path:
    candidates = [
        run_root / "plans" / f"{run_id}_final_plan.csv",
        run_root / "plans" / f"{run_id}_plan.csv",
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"No plan CSV found for {run_id} in {run_root / 'plans'}")


def _load_fixed_plan(instance, path: Path):
    rows = _read_rows(path)
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _eval_config(training_config: Mapping[str, Any]) -> dict[str, Any]:
    config = copy.deepcopy(dict(training_config))
    config["run_id"] = f"{training_config['run_id']}_common_eval"
    config["case_name"] = config["run_id"]
    config["mode"] = "integrated_mainline"
    config["solver"] = "benders"
    config["selection"] = {"scenarios_a": list(COMMON_A), "scenarios_b": list(COMMON_B)}
    _set_k(config, COMMON_K)
    return config


def _evaluate_case(
    *,
    training_config: Mapping[str, Any],
    run_root: Path,
    case: str,
) -> dict[str, Any]:
    run_id = str(training_config["run_id"])
    eval_config = _eval_config(training_config)
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    instance = prepare_instance_for_run(
        load_instance_for_run(eval_config, critical_buses=critical_buses),
        eval_config,
    )
    plan_path = _plan_path_for(run_root, run_id)
    plan = _load_fixed_plan(instance, plan_path)
    components = _evaluate_fixed_plan_components(
        instance,
        plan,
        run_id=f"default_scale_{case}_{run_id}",
        k=COMMON_K,
        disaster_evaluator="exact_primal_dro",
    )
    plan_rows = _read_rows(plan_path)
    open_rows = [row for row in plan_rows if int(float(row["is_open"])) == 1]
    capped_sl_sites = [
        row
        for row in open_rows
        if int(float(row["n_sl"]))
        >= int(instance.ev.nbar_sl_by_bus.get(int(row["bus"]), instance.ev.nbar_sl))
    ]
    summary_rows = _read_rows(run_root / "summary.csv")
    summary = summary_rows[0] if summary_rows else {}
    return {
        "case": case,
        "run_id": run_id,
        "training_mode": training_config.get("mode", ""),
        "training_K": training_config.get("parameter_overrides", {})
        .get("ambiguity", {})
        .get("k_max_outages", ""),
        "training_validation_level": summary.get("validation_level", ""),
        "training_stop_reason": summary.get("stop_reason", ""),
        "training_solver_status": summary.get("solver_status", ""),
        "training_iterations": summary.get("iterations", summary.get("iteration_count", "")),
        "training_max_iterations_budget": summary.get("max_iterations_budget", ""),
        "training_cuts": summary.get("cuts", summary.get("cut_count", "")),
        "training_final_violation": summary.get(
            "final_violation", summary.get("final_violation_upper_bound", "")
        ),
        **{
            key: components[key]
            for key in (
                "F_cons",
                "F_trans",
                "F_unmet",
                "F_sub",
                "Psi_nor",
                "Phi_dis",
                "pi_f",
                "J_common",
                "active_outage_lines",
                "separation_status",
                "separation_reconstruction_gap",
                "normal_scenario_count",
                "disaster_scenario_count",
                "K",
                "disaster_evaluator",
                "evaluated_outage_patterns",
            )
        },
        "sites": sum(plan.z_by_bus.values()),
        "slow_chargers": sum(plan.n_sl_by_bus.values()),
        "fast_chargers": sum(plan.n_fa_by_bus.values()),
        "open_sites_at_sl_cap": len(capped_sl_sites),
        "sl_cap_site_share": len(capped_sl_sites) / max(1, len(open_rows)),
        "plan_path": str(plan_path),
    }


def _safe_ratio(numerator: float, denominator: float) -> float:
    if abs(float(denominator)) <= 1e-12:
        return float("inf") if float(numerator) > 0 else 0.0
    return float(numerator) / float(denominator)


def _quality_row(candidate: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_case = {str(row["case"]): row for row in rows}
    proposed = by_case["proposed"]
    normal = by_case["normal"]
    deterministic = by_case["deterministic"]
    pi_f = float(proposed["pi_f"])
    daily_prop = float(proposed["F_cons"]) + (1.0 - pi_f) * float(proposed["Psi_nor"])
    daily_normal = float(normal["F_cons"]) + (1.0 - pi_f) * float(normal["Psi_nor"])
    delta_daily = daily_prop - daily_normal
    delta_resilience = pi_f * (float(normal["Phi_dis"]) - float(proposed["Phi_dis"]))
    det_reduction = _safe_ratio(
        float(deterministic["Phi_dis"]) - float(proposed["Phi_dis"]),
        float(deterministic["Phi_dis"]),
    )
    prop_unmet_share = _safe_ratio(float(proposed["F_unmet"]), float(proposed["Psi_nor"]))
    prop_phi_share = _safe_ratio(float(proposed["Phi_dis"]), float(proposed["Psi_nor"]))
    normal_phi_share = _safe_ratio(float(normal["Phi_dis"]), float(normal["Psi_nor"]))
    det_phi_share = _safe_ratio(float(deterministic["Phi_dis"]), float(deterministic["Psi_nor"]))
    normal_daily_base = max(1e-9, abs(daily_normal))
    checks = {
        "proposed_certified": str(proposed["training_validation_level"]) in {
            "exact",
            "epsilon_certified",
        },
        "proposed_solver_optimal": str(proposed["training_solver_status"]).upper() == "OPTIMAL",
        "deterministic_certified": str(deterministic["training_validation_level"]) in {
            "exact",
            "epsilon_certified",
        },
        "deterministic_solver_optimal": str(deterministic["training_solver_status"]).upper()
        == "OPTIMAL",
        "normal_exact": str(normal["training_validation_level"]) == "exact",
        "proposed_100iter_budget": int(proposed["training_max_iterations_budget"] or 0) >= 100,
        "deterministic_phi_worse": float(deterministic["Phi_dis"]) > float(proposed["Phi_dis"]),
        "deterministic_reduction_20pct": det_reduction >= 0.20,
        "delta_daily_nonnegative": delta_daily >= 0.0,
        "delta_daily_under_10pct": delta_daily <= 0.10 * normal_daily_base,
        "resilience_over_daily": delta_daily > 0.0
        and _safe_ratio(delta_resilience, delta_daily) >= 1.5,
        "proposed_unmet_under_5pct": prop_unmet_share <= 0.05,
        "station_count_interpretable": 6 <= int(proposed["sites"]) <= 16,
        "sl_cap_share_under_70pct": float(proposed["sl_cap_site_share"]) < 0.70,
        "nonzero_fast_slow_mix": int(proposed["slow_chargers"]) > 0
        and int(proposed["fast_chargers"]) > 0,
        "proposed_phi_material": prop_phi_share >= 0.01,
        "normal_phi_material": normal_phi_share >= 0.10,
        "deterministic_phi_material": det_phi_share >= 0.10,
        "common_eval_exact": all(
            str(row["disaster_evaluator"]) == "exact_primal_dro"
            and int(row["normal_scenario_count"]) == len(COMMON_A)
            and int(row["disaster_scenario_count"]) == len(COMMON_B)
            and int(row["K"]) == COMMON_K
            for row in rows
        ),
    }
    return {
        **{key: candidate[key] for key in (
            "candidate_id",
            "ev_scale",
            "cfix_mult",
            "ccons_sl_mult",
            "ccons_fa_mult",
            "ctrans_mult",
            "cls_critical",
            "cls_noncritical",
            "pi_f",
            "nbar_sl",
            "nbar_fa",
            "p_sl_scale",
            "capacity_profile",
            "slow_block_threshold",
            "slow_extra_cost_multiplier",
            "cunmet_multiplier",
        )},
        "Phi_proposed": proposed["Phi_dis"],
        "Phi_normal": normal["Phi_dis"],
        "Phi_deterministic": deterministic["Phi_dis"],
        "Psi_proposed": proposed["Psi_nor"],
        "Psi_normal": normal["Psi_nor"],
        "Psi_deterministic": deterministic["Psi_nor"],
        "DeltaDaily": delta_daily,
        "DeltaResilience": delta_resilience,
        "DeltaResilience_over_DeltaDaily": _safe_ratio(delta_resilience, delta_daily),
        "deterministic_reduction_pct": 100.0 * det_reduction,
        "proposed_unmet_share_pct": 100.0 * prop_unmet_share,
        "proposed_phi_over_psi_pct": 100.0 * prop_phi_share,
        "normal_phi_over_psi_pct": 100.0 * normal_phi_share,
        "deterministic_phi_over_psi_pct": 100.0 * det_phi_share,
        "proposed_sites": proposed["sites"],
        "proposed_slow": proposed["slow_chargers"],
        "proposed_fast": proposed["fast_chargers"],
        "proposed_sl_cap_site_share_pct": 100.0 * float(proposed["sl_cap_site_share"]),
        **{f"pass_{key}": bool(value) for key, value in checks.items()},
        "passes_all_quality_gates": all(checks.values()),
    }


def _bug_rows(candidate: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    bugs: list[dict[str, Any]] = []
    for row in rows:
        psi_gap = abs(
            float(row["Psi_nor"])
            - float(row["F_trans"])
            - float(row["F_unmet"])
            - float(row["F_sub"])
        )
        j_gap = abs(
            float(row["J_common"])
            - float(row["F_cons"])
            - (1.0 - float(row["pi_f"])) * float(row["Psi_nor"])
            - float(row["pi_f"]) * float(row["Phi_dis"])
        )
        if psi_gap > 1e-5 or j_gap > 1e-5:
            bugs.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "case": row["case"],
                    "bug": "component_identity_failed",
                    "detail": f"psi_gap={psi_gap:.6g}, j_gap={j_gap:.6g}",
                }
            )
        if str(row["case"]) == "deterministic" and int(row["training_K"]) != 0:
            bugs.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "case": row["case"],
                    "bug": "deterministic_main_trained_with_nonzero_K",
                    "detail": f"training_K={row['training_K']}",
                }
            )
        if str(row["separation_status"]) != "EXACT_PRIMAL_DRO":
            bugs.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "case": row["case"],
                    "bug": "common_replay_not_exact_primal_dro",
                    "detail": str(row["separation_status"]),
                }
            )
        if int(row["evaluated_outage_patterns"]) != 529:
            bugs.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "case": row["case"],
                    "bug": "unexpected_outage_pattern_count",
                    "detail": str(row["evaluated_outage_patterns"]),
                }
            )
    return bugs


def _write_bug_log(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("# Default Scale Calibration Bug Log\n\nNo blocking bug detected.\n", encoding="utf-8")
        return
    lines = ["# Default Scale Calibration Bug Log", ""]
    for row in rows:
        lines.append(
            f"- `{row['candidate_id']}` / `{row['case']}`: `{row['bug']}` - {row['detail']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_summary(root: Path, row: Mapping[str, Any]) -> None:
    path = root / "summary.csv"
    rows = _read_rows(path)
    rows = [existing for existing in rows if existing.get("run_id") != row.get("run_id")]
    rows.append({key: row.get(key, "") for key in ExperimentRunSummary.__dataclass_fields__})
    _write_rows(path, rows)


def _execute_case(
    *,
    root: Path,
    config: Mapping[str, Any],
    args: argparse.Namespace,
) -> Path:
    if str(config["solver"]) == "direct_master":
        run_root = _run_direct_master(root=root, config=config, args=args)
        summary_rows = _read_rows(run_root / "summary.csv")
        if summary_rows:
            _append_summary(root, summary_rows[0])
        return run_root
    run_root = _run_exact_benders(root=root, config=config, args=args)
    return run_root


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--base-config-log", default=str(DEFAULT_BASE_CONFIG))
    parser.add_argument("--ev-scales", default="0.55,0.65,0.75,0.85")
    parser.add_argument("--cfix-multipliers", default="0.6,0.8,1.0")
    parser.add_argument("--ccons-sl-multipliers", default="1.0,2.0,4.0")
    parser.add_argument("--ccons-fa-multipliers", default="1.0")
    parser.add_argument("--ctrans-multipliers", default="1.0")
    parser.add_argument("--cls-pairs", default="100:1,150:1,200:1")
    parser.add_argument("--pi-values", default="0.3")
    parser.add_argument("--nbar-sl-values", default="25")
    parser.add_argument("--nbar-fa-values", default="10")
    parser.add_argument("--p-sl-scales", default="1.0")
    parser.add_argument("--capacity-profile", default="none")
    parser.add_argument("--slow-block-threshold", type=int, default=0)
    parser.add_argument("--slow-extra-cost-multiplier", type=float, default=1.0)
    parser.add_argument("--cunmet-multiplier", type=float, default=1.0)
    parser.add_argument("--max-candidates", type=int, default=0)
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--top-cuts", type=int, default=20)
    parser.add_argument("--master-time-limit-seconds", type=float, default=60.0)
    parser.add_argument("--normal-master-time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--master-mip-gap", type=float, default=0.02)
    parser.add_argument("--include-deterministic-k1", action="store_true")
    parser.add_argument("--include-deterministic-k2", action="store_true")
    parser.add_argument("--include-disaster-after-pass", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--stop-on-pass", action="store_true")
    args = parser.parse_args()

    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "diagnostics").mkdir(parents=True, exist_ok=True)
    base_config = _load_json(Path(args.base_config_log))
    candidates = _candidate_configs(args)

    all_component_rows: list[dict[str, Any]] = _read_rows(root / "default_scale_candidate_matrix.csv")
    all_quality_rows: list[dict[str, Any]] = _read_rows(root / "default_scale_quality_gates.csv")
    all_bug_rows: list[dict[str, Any]] = []
    completed_candidates = {row.get("candidate_id") for row in all_quality_rows}
    completed_component_cases = {
        (row.get("candidate_id"), row.get("case")) for row in all_component_rows
    }

    for index, candidate in enumerate(candidates, start=1):
        candidate_id = str(candidate["candidate_id"])
        if args.skip_existing and candidate_id in completed_candidates:
            requested_extra_cases = []
            if args.include_deterministic_k1:
                requested_extra_cases.append("deterministic_k1")
            if args.include_deterministic_k2:
                requested_extra_cases.append("deterministic_k2")
            passed_existing_gate = any(
                row.get("candidate_id") == candidate_id
                and str(row.get("passes_all_quality_gates")) == "True"
                for row in all_quality_rows
            )
            needs_disaster = (
                args.include_disaster_after_pass
                and (candidate_id, "disaster") not in completed_component_cases
                and passed_existing_gate
            )
            needs_extra_case = any(
                (candidate_id, case) not in completed_component_cases
                for case in requested_extra_cases
            )
            if not needs_disaster and not needs_extra_case:
                continue
            if needs_disaster and not needs_extra_case:
                print(
                    f"[default-scale] candidate {index}/{len(candidates)}: "
                    f"{candidate_id} (补跑 disaster-only)",
                    flush=True,
                )
                disaster_config = _build_run_config(base_config, candidate, case="disaster")
                disaster_root = _execute_case(root=root, config=disaster_config, args=args)
                disaster_row = {
                    **{key: candidate[key] for key in (
                        "candidate_id",
                        "ev_scale",
                        "cfix_mult",
                        "ccons_sl_mult",
                        "ccons_fa_mult",
                        "ctrans_mult",
                        "cls_critical",
                        "cls_noncritical",
                        "pi_f",
                        "nbar_sl",
                        "nbar_fa",
                        "p_sl_scale",
                        "capacity_profile",
                        "slow_block_threshold",
                        "slow_extra_cost_multiplier",
                        "cunmet_multiplier",
                    )},
                    **_evaluate_case(
                        training_config=disaster_config,
                        run_root=disaster_root,
                        case="disaster",
                    ),
                }
                all_component_rows = [
                    row
                    for row in all_component_rows
                    if not (
                        row.get("candidate_id") == candidate_id
                        and row.get("case") == "disaster"
                    )
                ]
                all_component_rows.append(disaster_row)
                _write_rows(root / "default_scale_candidate_matrix.csv", all_component_rows)
                if args.stop_on_pass:
                    return
                continue
        print(f"[default-scale] candidate {index}/{len(candidates)}: {candidate_id}", flush=True)

        case_names = ["proposed", "normal", "deterministic"]
        if args.include_deterministic_k1:
            case_names.append("deterministic_k1")
        if args.include_deterministic_k2:
            case_names.append("deterministic_k2")
        configs = {
            case: _build_run_config(base_config, candidate, case=case)
            for case in case_names
        }
        roots = {
            case: _execute_case(root=root, config=configs[case], args=args)
            for case in case_names
        }
        component_rows = [
            {
                **{key: candidate[key] for key in (
                    "candidate_id",
                    "ev_scale",
                    "cfix_mult",
                    "ccons_sl_mult",
                    "ccons_fa_mult",
                    "ctrans_mult",
                    "cls_critical",
                    "cls_noncritical",
                    "pi_f",
                    "nbar_sl",
                    "nbar_fa",
                    "p_sl_scale",
                    "capacity_profile",
                    "slow_block_threshold",
                    "slow_extra_cost_multiplier",
                    "cunmet_multiplier",
                )},
                **_evaluate_case(
                    training_config=configs[case],
                    run_root=roots[case],
                    case=case,
                ),
            }
            for case in case_names
        ]
        quality = _quality_row(candidate, [row for row in component_rows if row["case"] in {"proposed", "normal", "deterministic"}])
        bugs = _bug_rows(candidate, component_rows)
        all_bug_rows.extend(bugs)

        all_component_rows = [
            row for row in all_component_rows if row.get("candidate_id") != candidate_id
        ]
        all_component_rows.extend(component_rows)
        all_quality_rows = [
            row for row in all_quality_rows if row.get("candidate_id") != candidate_id
        ]
        all_quality_rows.append(quality)
        _write_rows(root / "default_scale_candidate_matrix.csv", all_component_rows)
        _write_rows(root / "default_scale_quality_gates.csv", all_quality_rows)
        _write_rows(root / "bug_records.csv", all_bug_rows)
        _write_bug_log(root / "bug_log.md", all_bug_rows)

        if bugs:
            print(f"[default-scale] blocking bug detected for {candidate_id}", flush=True)
            sys.exit(2)

        if bool(quality["passes_all_quality_gates"]):
            print(f"[default-scale] PASS: {candidate_id}", flush=True)
            if args.include_disaster_after_pass:
                disaster_config = _build_run_config(base_config, candidate, case="disaster")
                disaster_root = _execute_case(root=root, config=disaster_config, args=args)
                disaster_row = {
                    **{key: candidate[key] for key in (
                        "candidate_id",
                        "ev_scale",
                        "cfix_mult",
                        "ccons_sl_mult",
                        "ccons_fa_mult",
                        "ctrans_mult",
                        "cls_critical",
                        "cls_noncritical",
                        "pi_f",
                        "nbar_sl",
                        "nbar_fa",
                        "p_sl_scale",
                        "capacity_profile",
                        "slow_block_threshold",
                        "slow_extra_cost_multiplier",
                        "cunmet_multiplier",
                    )},
                    **_evaluate_case(
                        training_config=disaster_config,
                        run_root=disaster_root,
                        case="disaster",
                    ),
                }
                all_component_rows.append(disaster_row)
                _write_rows(root / "default_scale_candidate_matrix.csv", all_component_rows)
            if args.stop_on_pass:
                return

    print("[default-scale] completed candidate sweep; no blocking bug detected.", flush=True)


if __name__ == "__main__":
    main()
