"""Run a component-complete default pack on the colleague-provided data."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_paper_final_analysis import _evaluate_fixed_plan_components  # noqa: E402
from scripts.experiment_pack_utils import (  # noqa: E402
    execute_run,
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan  # noqa: E402


CRITICAL_BUSES_CONFIG = Path("configs/critical_buses_paper_fig2.yaml")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


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


def _read_plan(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_plan(instance, path: Path):
    rows = _read_plan(path)
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _plan_metrics(plan_path: Path) -> dict[str, Any]:
    rows = _read_plan(plan_path)
    open_rows = [row for row in rows if int(float(row["is_open"])) == 1]
    critical_total = sum(1 for row in rows if int(float(row.get("is_critical", 0))) == 1)
    critical_open = sum(
        1
        for row in open_rows
        if int(float(row.get("is_critical", 0))) == 1
    )
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


def _base_config(
    *,
    runtime_source: str,
    scenarios_a: Sequence[int],
    scenarios_b: Sequence[int],
    k: int,
    max_iterations: int,
    epsilon_cert: float,
    top_cuts: int,
    master_time_limit_seconds: float,
    master_mip_gap: float,
    separation_time_limit_seconds: float,
    separation_mip_gap: float,
    omega_bound_upper: float,
) -> dict[str, Any]:
    return {
        "family_name": "colleague_default_rerun",
        "runtime_source": runtime_source,
        "selection": {
            "scenarios_a": list(scenarios_a),
            "scenarios_b": list(scenarios_b),
        },
        "parameter_regime": "colleague_default_parameters",
        "parameter_overrides": {
            "ambiguity": {"k_max_outages": int(k)},
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
        },
    }


def _case_configs(base: Mapping[str, Any], *, case_filter: set[str] | None = None) -> list[dict[str, Any]]:
    specs = [
        ("Case 1", "colleague_default_proposed", "Proposed integrated", "integrated_mainline", "benders", None),
        ("Case 2", "colleague_default_normal", "Normal-only", "normal_only", "direct_master", None),
        ("Case 3", "colleague_default_disaster", "Disaster-only", "disaster_only", "benders", None),
        (
            "Case 4",
            "colleague_default_deterministic_k2",
            "Deterministic mean-value, K_train=2",
            "deterministic_mean_value",
            "benders",
            2,
        ),
        (
            "Diagnostic",
            "colleague_default_deterministic_k0",
            "Naive deterministic mean-value, K_train=0",
            "deterministic_mean_value",
            "benders",
            0,
        ),
    ]
    configs: list[dict[str, Any]] = []
    for case_id, run_id, case_name, mode, solver, k_override in specs:
        case_key = case_id.lower().replace(" ", "")
        if case_filter is not None and case_key not in case_filter and run_id not in case_filter:
            continue
        config = json.loads(json.dumps(dict(base)))
        config.update(
            {
                "case_id": case_id,
                "run_id": run_id,
                "case_name": case_name,
                "mode": mode,
                "solver": solver,
            }
        )
        if k_override is not None:
            overrides = dict(config.get("parameter_overrides", {}))
            ambiguity = dict(overrides.get("ambiguity", {}))
            ambiguity["k_max_outages"] = int(k_override)
            overrides["ambiguity"] = ambiguity
            config["parameter_overrides"] = overrides
        configs.append(config)
    return configs


def _summarize_training(log_path: Path) -> dict[str, Any]:
    payload = _read_json(log_path)
    summary = payload.get("summary", {})
    return {
        "training_validation_level": payload.get("validation_level", ""),
        "training_stop_reason": payload.get("stop_reason", ""),
        "training_solver_status": payload.get("solver_status", ""),
        "training_iterations": summary.get("iteration_count", ""),
        "training_cuts": summary.get("cut_count", ""),
        "training_final_violation": summary.get("final_violation_upper_bound", ""),
        "training_objective": summary.get("total_objective", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-source", default="data/colleague_default")
    parser.add_argument("--output-root", default="results/colleague_default_rerun")
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--top-cuts", type=int, default=20)
    parser.add_argument("--master-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--master-mip-gap", type=float, default=0.02)
    parser.add_argument("--separation-time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.02)
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument(
        "--cases",
        default="case1,case2,case3,case4,diagnostic",
        help=(
            "Comma-separated case ids to run. Supported ids: case1, case2, "
            "case3, case4, diagnostic, or explicit run ids."
        ),
    )
    args = parser.parse_args()

    output_root = Path(args.output_root)
    params = _read_json(REPO_ROOT / args.runtime_source / "parameters.json")
    scenarios_a = tuple(int(value) for value in params["sets"]["scenarios_a"])
    scenarios_b = tuple(int(value) for value in params["sets"]["scenarios_b"])
    base = _base_config(
        runtime_source=args.runtime_source,
        scenarios_a=scenarios_a,
        scenarios_b=scenarios_b,
        k=args.k,
        max_iterations=args.max_iterations,
        epsilon_cert=args.epsilon_cert,
        top_cuts=args.top_cuts,
        master_time_limit_seconds=args.master_time_limit_seconds,
        master_mip_gap=args.master_mip_gap,
        separation_time_limit_seconds=args.separation_time_limit_seconds,
        separation_mip_gap=args.separation_mip_gap,
        omega_bound_upper=args.omega_bound_upper,
    )
    _write_json(output_root / "manifest.json", {"base_run_config": base})

    critical_buses = load_critical_buses(CRITICAL_BUSES_CONFIG)
    case_filter = {token.strip().lower() for token in args.cases.split(",") if token.strip()}
    summaries = []
    configs = _case_configs(base, case_filter=case_filter)
    for config in configs:
        result = execute_run(config, critical_buses=critical_buses, output_root=output_root)
        summaries.append(result["summary"].to_csv_row())
    _write_rows(output_root / "summary.csv", summaries)

    eval_config = json.loads(json.dumps(base))
    eval_config.update(
        {
            "run_id": "colleague_default_common_eval",
            "case_name": "colleague_default_common_eval",
            "mode": "integrated_mainline",
            "solver": "benders",
        }
    )
    eval_instance = prepare_instance_for_run(
        load_instance_for_run(eval_config, critical_buses=critical_buses),
        eval_config,
    )

    component_rows: list[dict[str, Any]] = []
    for config in configs:
        run_id = str(config["run_id"])
        plan_path = output_root / "plans" / f"{run_id}_plan.csv"
        log_path = output_root / "logs" / f"{run_id}_run.json"
        plan = _load_plan(eval_instance, plan_path)
        components = _evaluate_fixed_plan_components(
            eval_instance,
            plan,
            run_id=f"{run_id}_common_eval",
            k=int(args.k),
            disaster_evaluator="milp",
        )
        component_rows.append(
            {
                "case_id": config["case_id"],
                "case_name": config["case_name"],
                "run_id": run_id,
                "source_plan_path": str(plan_path),
                "normal_scenario_count": components["normal_scenario_count"],
                "disaster_scenario_count": components["disaster_scenario_count"],
                "K_eval": components["K"],
                "disaster_evaluator": components["disaster_evaluator"],
                "F_cons": components["F_cons"],
                "F_trans": components["F_trans"],
                "F_unmet": components["F_unmet"],
                "F_sub": components["F_sub"],
                "Psi_nor": components["Psi_nor"],
                "Phi_dis": components["Phi_dis"],
                "pi_f": components["pi_f"],
                "J_common": components["J_common"],
                "active_outage_lines": components["active_outage_lines"],
                "separation_status": components["separation_status"],
                "separation_reconstruction_gap": components["separation_reconstruction_gap"],
                "evaluated_outage_patterns": components["evaluated_outage_patterns"],
                **_plan_metrics(plan_path),
                **_summarize_training(log_path),
            }
        )
    _write_rows(output_root / "objective_components_tableIII.csv", component_rows)

    proposed = next(
        (row for row in component_rows if row["run_id"] == "colleague_default_proposed"),
        None,
    )
    normal = next(
        (row for row in component_rows if row["run_id"] == "colleague_default_normal"),
        None,
    )
    disaster = next(
        (row for row in component_rows if row["run_id"] == "colleague_default_disaster"),
        None,
    )
    det_k1 = next(
        (row for row in component_rows if row["run_id"] == "colleague_default_deterministic_k1"),
        None,
    )
    pi_f = float(proposed["pi_f"]) if proposed is not None else 0.0
    if proposed is not None and normal is not None:
        daily_proposed = float(proposed["F_cons"]) + (1.0 - pi_f) * float(proposed["Psi_nor"])
        daily_normal = float(normal["F_cons"]) + (1.0 - pi_f) * float(normal["Psi_nor"])
        delta_daily = daily_proposed - daily_normal
        delta_resilience = pi_f * (float(normal["Phi_dis"]) - float(proposed["Phi_dis"]))
    else:
        delta_daily = None
        delta_resilience = None
    det_reduction = None
    if proposed is not None and det_k1 is not None and float(det_k1["Phi_dis"]):
        det_reduction = (
            (float(det_k1["Phi_dis"]) - float(proposed["Phi_dis"])) / float(det_k1["Phi_dis"])
        )
    audit = {
        "target": "colleague_default_rerun",
        "runtime_source": args.runtime_source,
        "A": len(scenarios_a),
        "B": len(scenarios_b),
        "K_eval": int(args.k),
        "component_complete": True,
        "proposed_validation_level": None if proposed is None else proposed["training_validation_level"],
        "normal_validation_level": None if normal is None else normal["training_validation_level"],
        "disaster_validation_level": None if disaster is None else disaster["training_validation_level"],
        "deterministic_k1_validation_level": None if det_k1 is None else det_k1["training_validation_level"],
        "delta_daily_vs_normal": delta_daily,
        "delta_resilience_vs_normal": delta_resilience,
        "delta_resilience_over_delta_daily": (
            delta_resilience / delta_daily
            if delta_daily not in (None, 0) and delta_resilience is not None
            else None
        ),
        "deterministic_k1_phi_reduction": det_reduction,
        "proposed_phi_over_psi": (
            float(proposed["Phi_dis"]) / float(proposed["Psi_nor"])
            if float(proposed["Psi_nor"])
            else None
        ),
        "proposed_unmet_over_psi": (
            float(proposed["F_unmet"]) / float(proposed["Psi_nor"])
            if float(proposed["Psi_nor"])
            else None
        ),
        "verdict": "DIAGNOSTIC_COMPLETE",
    }
    _write_json(output_root / "colleague_default_audit.json", audit)
    report = [
        "# Colleague Default Rerun",
        "",
        f"- Runtime source: `{args.runtime_source}`",
        f"- Support: `A={len(scenarios_a)}`, `B={len(scenarios_b)}`, `K_eval={args.k}`",
        f"- Proposed validation: `{audit['proposed_validation_level']}`; final violation `{'' if proposed is None else proposed['training_final_violation']}`",
        f"- Normal-only validation: `{audit['normal_validation_level']}`",
        f"- Disaster-only validation: `{audit['disaster_validation_level']}`",
        "",
        "## Key Metrics",
        "",
        f"- DeltaDaily vs normal-only: `{delta_daily}`",
        f"- DeltaResilience vs normal-only: `{delta_resilience}`",
        f"- DeltaResilience/DeltaDaily: `{audit['delta_resilience_over_delta_daily']}`",
        f"- Proposed Phi reduction vs deterministic K1: `{'' if det_reduction is None else f'{100.0 * det_reduction:.2f}%'}`",
        f"- Proposed Phi/Psi: `{audit['proposed_phi_over_psi']}`",
        f"- Proposed unmet/Psi: `{audit['proposed_unmet_over_psi']}`",
        "",
        "## Artifacts",
        "",
        "- `summary.csv`",
        "- `objective_components_tableIII.csv`",
        "- `colleague_default_audit.json`",
        "- `logs/*_run.json`",
        "- `plans/*_plan.csv`",
    ]
    (output_root / "colleague_default_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
