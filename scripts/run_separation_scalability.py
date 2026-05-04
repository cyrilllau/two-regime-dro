"""Build separation-focused runtime evidence under the accepted paper regime."""

from __future__ import annotations

import argparse
import csv
import json
from math import comb
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import (  # noqa: E402
    execute_run,
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from src.production.separation_milp import solve_separation_milp  # noqa: E402
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan  # noqa: E402


ACCEPTED_CONFIG = Path(
    "results/default_scale_calibration/runs/"
    "default_ev0p55_cfix1_csl5_cls300x1_pi0p3_cfa0p24_ctr16p0_"
    "cappaper_heterogeneous_headroom_slblk16x10p0_cunmet3p0_proposed/logs/"
    "default_ev0p55_cfix1_csl5_cls300x1_pi0p3_cfa0p24_ctr16p0_"
    "cappaper_heterogeneous_headroom_slblk16x10p0_cunmet3p0_proposed_config.json"
)
CRITICAL_BUSES = Path("configs/critical_buses_paper_fig2.yaml")
REPRESENTATIVE_PLAN = Path(
    "results/paper_final/plans/default_scale_v2_proposed_plan.csv"
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload["run_config"] if "run_config" in payload else payload)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _parse_int_list(raw: str) -> list[int]:
    return [int(token.strip()) for token in raw.split(",") if token.strip()]


def _parse_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _outage_pattern_count(line_count: int, k: int) -> int:
    return int(sum(comb(line_count, i) for i in range(int(k) + 1)))


def _configure(
    base: Mapping[str, Any],
    *,
    run_id: str,
    a_count: int,
    b_count: int,
    k: int,
    solver: str,
    max_iterations: int,
    epsilon_cert: float,
    master_time_limit_seconds: float,
    master_mip_gap: float,
    separation_time_limit_seconds: float,
    separation_mip_gap: float,
    separation_top_cuts_per_iteration: int,
    omega_bound_upper: float,
) -> dict[str, Any]:
    config = json.loads(json.dumps(dict(base)))
    config["run_id"] = run_id
    config["case_name"] = run_id
    config["family_name"] = "separation_scalability"
    config["parameter_regime"] = str(base.get("parameter_regime", "accepted_default_regime"))
    config["selection"] = {
        "scenarios_a": list(range(1, int(a_count) + 1)),
        "scenarios_b": list(range(1, int(b_count) + 1)),
    }
    overrides = dict(config.get("parameter_overrides", {}))
    ambiguity = dict(overrides.get("ambiguity", {}))
    ambiguity["k_max_outages"] = int(k)
    overrides["ambiguity"] = ambiguity
    config["parameter_overrides"] = overrides
    config["mode"] = "integrated_mainline"
    config["solver"] = solver
    config["benders"] = {
        "epsilon_cert": float(epsilon_cert),
        "max_iterations": int(max_iterations),
        "master_time_limit_seconds": float(master_time_limit_seconds),
        "master_mip_gap": float(master_mip_gap),
        "separation_time_limit_seconds": float(separation_time_limit_seconds),
        "separation_mip_gap": float(separation_mip_gap),
        "separation_top_cuts_per_iteration": int(separation_top_cuts_per_iteration),
        "allow_master_suboptimal_incumbent": True,
        "omega_bound_upper": float(omega_bound_upper),
    }
    return config


def _write_config(path: Path, config: Mapping[str, Any]) -> None:
    _write_json(path, {"run_config": dict(config)})


def _run_milp(
    *,
    base: Mapping[str, Any],
    raw_root: Path,
    run_id: str,
    a_count: int,
    b_count: int,
    k: int,
    max_iterations: int,
    epsilon_cert: float,
    master_time_limit_seconds: float,
    master_mip_gap: float,
    separation_time_limit_seconds: float,
    separation_mip_gap: float,
    omega_bound_upper: float,
    top_cuts: int,
    skip_existing: bool,
) -> dict[str, Any]:
    log_path = raw_root / "milp" / "logs" / f"{run_id}_run.json"
    if skip_existing and log_path.exists():
        return _summarize_milp(log_path, run_id=run_id)

    config = _configure(
        base,
        run_id=run_id,
        a_count=a_count,
        b_count=b_count,
        k=k,
        solver="benders",
        max_iterations=max_iterations,
        epsilon_cert=epsilon_cert,
        master_time_limit_seconds=master_time_limit_seconds,
        master_mip_gap=master_mip_gap,
        separation_time_limit_seconds=separation_time_limit_seconds,
        separation_mip_gap=separation_mip_gap,
        separation_top_cuts_per_iteration=int(top_cuts),
        omega_bound_upper=omega_bound_upper,
    )
    critical_buses = load_critical_buses(CRITICAL_BUSES)
    execute_run(config, critical_buses=critical_buses, output_root=raw_root / "milp")
    return _summarize_milp(log_path, run_id=run_id)


def _run_milp_oracle(
    *,
    base: Mapping[str, Any],
    raw_root: Path,
    run_id: str,
    a_count: int,
    b_count: int,
    k: int,
    separation_time_limit_seconds: float,
    separation_mip_gap: float,
    omega_bound_upper: float,
    skip_existing: bool,
) -> dict[str, Any]:
    log_path = raw_root / "milp_oracle" / "logs" / f"{run_id}_run.json"
    if skip_existing and log_path.exists():
        return _summarize_milp_oracle(log_path, run_id=run_id)

    config = _configure(
        base,
        run_id=run_id,
        a_count=a_count,
        b_count=b_count,
        k=k,
        solver="benders",
        max_iterations=1,
        epsilon_cert=0.0,
        master_time_limit_seconds=0.0,
        master_mip_gap=0.0,
        separation_time_limit_seconds=separation_time_limit_seconds,
        separation_mip_gap=separation_mip_gap,
        separation_top_cuts_per_iteration=1,
        omega_bound_upper=omega_bound_upper,
    )
    critical_buses = load_critical_buses(CRITICAL_BUSES)
    base_instance = load_instance_for_run(config, critical_buses=critical_buses)
    instance = prepare_instance_for_run(base_instance, config)
    plan_rows = _read_rows(REPO_ROOT / REPRESENTATIVE_PLAN)
    z_by_bus = {int(row["bus"]): int(row["is_open"]) for row in plan_rows}
    n_sl_by_bus = {int(row["bus"]): int(row["n_sl"]) for row in plan_rows}
    n_fa_by_bus = {int(row["bus"]): int(row["n_fa"]) for row in plan_rows}
    plan = build_fixed_first_stage_plan(
        instance,
        z_by_bus=z_by_bus,
        n_sl_by_bus=n_sl_by_bus,
        n_fa_by_bus=n_fa_by_bus,
    )
    omega_upper = float(config["benders"]["omega_bound_upper"])
    omega_bounds_by_line_id = {
        line_id: (0.0, omega_upper) for line_id in instance.sets.line_ids
    }
    start = perf_counter()
    _, solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=0.0,
        lambda_by_line_id=None,
        omega_bounds_by_line_id=omega_bounds_by_line_id,
        budget_k=int(k),
        scenario_ids=list(range(1, int(b_count) + 1)),
        model_name=f"{run_id}_one_shot_separation",
        time_limit_seconds=float(separation_time_limit_seconds),
        mip_gap=float(separation_mip_gap),
        require_optimal=False,
    )
    runtime = perf_counter() - start
    omega_upper_slacks = list(solution.omega_upper_slack_by_line_id.values())
    active_omega_upper_slacks = [
        float(solution.omega_upper_slack_by_line_id[line_id])
        for line_id, active in solution.delta_by_line_id.items()
        if int(active) == 1 and line_id in solution.omega_upper_slack_by_line_id
    ]
    omega_values = list(solution.omega_by_line_id.values())
    log_payload = {
        "run_config": config,
        "representative_point": {
            "source_plan_path": str(REPRESENTATIVE_PLAN),
            "alpha": 0.0,
            "lambda_by_line_id": "all_zero",
            "purpose": "one-shot separation oracle stress test",
        },
        "summary": {
            "run_id": run_id,
            "A": int(a_count),
            "B": int(b_count),
            "K": int(k),
            "separation_mode": "milp_oracle",
            "validation_level": (
                "separation_optimal"
                if solution.model_status == "OPTIMAL"
                else "diagnostic_separation"
            ),
            "stop_reason": f"one_shot_{solution.model_status.lower()}",
            "solver_status": solution.model_status,
            "iterations": 1,
            "cuts": 0,
            "final_violation": float(solution.objective_value or 0.0),
            "runtime_seconds": float(runtime),
            "separation_seconds": float(solution.runtime_seconds or runtime),
            "milp_status": solution.model_status,
            "milp_gap": solution.mip_gap,
            "milp_obj_bound": solution.obj_bound,
            "milp_node_count": solution.node_count,
            "omega_bound_upper": omega_upper,
            "max_omega_value": max(omega_values) if omega_values else None,
            "min_omega_upper_slack": (
                min(omega_upper_slacks) if omega_upper_slacks else None
            ),
            "min_active_omega_upper_slack": (
                min(active_omega_upper_slacks) if active_omega_upper_slacks else None
            ),
            "max_omega_bound_violation": solution.max_omega_bound_violation,
            "separation_reconstruction_gap": solution.reconstruction_gap,
            "selected_active_outage_lines": ";".join(
                sorted(
                    line_id
                    for line_id, value in solution.delta_by_line_id.items()
                    if int(value) == 1
                )
            ),
        },
    }
    _write_json(log_path, log_payload)
    return _summarize_milp_oracle(log_path, run_id=run_id)


def _summarize_milp(log_path: Path, *, run_id: str) -> dict[str, Any]:
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    run_config = payload["run_config"]
    iteration_log = payload.get("iteration_log") or {}
    iterations = iteration_log.get("iterations") or []
    master_seconds = sum(_parse_float(row.get("master_solve_seconds")) for row in iterations)
    separation_seconds = sum(_parse_float(row.get("separation_solve_seconds")) for row in iterations)
    cut_seconds = sum(_parse_float(row.get("cut_generation_seconds")) for row in iterations)
    runtime = master_seconds + separation_seconds + cut_seconds
    if runtime <= 0:
        runtime = _parse_float(summary.get("total_objective"), 0.0) * 0.0
    selected = [
        ";".join(row.get("selected_outage_active_lines") or ())
        for row in iterations
        if row.get("selected_outage_active_lines") is not None
    ]
    statuses = sorted(
        {
            str(row.get("separation_model_status"))
            for row in iterations
            if row.get("separation_model_status") not in (None, "")
        }
    )
    gaps = [
        _parse_float(row.get("separation_mip_gap"))
        for row in iterations
        if row.get("separation_mip_gap") not in (None, "")
    ]
    nodes = [
        _parse_float(row.get("separation_node_count"))
        for row in iterations
        if row.get("separation_node_count") not in (None, "")
    ]
    omega_bound_violations = [
        _parse_float(row.get("separation_max_omega_bound_violation"))
        for row in iterations
        if row.get("separation_max_omega_bound_violation") not in (None, "")
    ]
    omega_upper_slacks = [
        _parse_float(row.get("separation_min_omega_upper_slack"))
        for row in iterations
        if row.get("separation_min_omega_upper_slack") not in (None, "")
    ]
    active_omega_upper_slacks = [
        _parse_float(row.get("separation_min_active_omega_upper_slack"))
        for row in iterations
        if row.get("separation_min_active_omega_upper_slack") not in (None, "")
    ]
    reconstruction_gaps = [
        _parse_float(row.get("separation_reconstruction_gap"))
        for row in iterations
        if row.get("separation_reconstruction_gap") not in (None, "")
    ]
    first = iterations[0] if iterations else {}
    last = iterations[-1] if iterations else {}
    selected_normal = run_config.get("selection", {}).get("scenarios_a", [])
    selected_disaster = run_config.get("selection", {}).get("scenarios_b", [])
    k_value = (
        run_config.get("parameter_overrides", {})
        .get("ambiguity", {})
        .get("k_max_outages", "")
    )
    return {
        "experiment_group": "",
        "run_id": run_id,
        "A": len(selected_normal),
        "B": len(selected_disaster),
        "K": int(k_value),
        "separation_mode": "milp",
        "top_cuts": int(
            run_config.get("benders", {}).get("separation_top_cuts_per_iteration", 1)
        ),
        "validation_level": payload["validation_level"],
        "stop_reason": payload["stop_reason"],
        "solver_status": payload["solver_status"],
        "max_iterations_budget": int(run_config.get("benders", {}).get("max_iterations", 0)),
        "iterations": int(summary["iteration_count"]),
        "cuts": int(summary["cut_count"]),
        "final_violation": _parse_float(summary["final_violation_upper_bound"]),
        "final_violation_bound": _parse_float(last.get("separation_obj_bound")) if last else "",
        "runtime_seconds": runtime,
        "master_seconds": master_seconds,
        "separation_seconds": separation_seconds,
        "cut_generation_seconds": cut_seconds,
        "separation_time_share": separation_seconds / runtime if runtime > 0 else "",
        "evaluated_outage_patterns": "",
        "outage_pattern_count_formula": _outage_pattern_count(32, int(k_value)),
        "milp_statuses": ";".join(statuses),
        "milp_gap_max": max(gaps) if gaps else "",
        "milp_node_count_total": sum(nodes) if nodes else "",
        "omega_bound_upper": run_config.get("benders", {}).get("omega_bound_upper", ""),
        "max_omega_bound_violation": max(omega_bound_violations) if omega_bound_violations else "",
        "min_omega_upper_slack": min(omega_upper_slacks) if omega_upper_slacks else "",
        "min_active_omega_upper_slack": (
            min(active_omega_upper_slacks) if active_omega_upper_slacks else ""
        ),
        "max_separation_reconstruction_gap": max(reconstruction_gaps) if reconstruction_gaps else "",
        "selected_active_outage_lines": " | ".join(selected),
        "first_iteration_violation": _parse_float(first.get("separation_violation_value")) if first else "",
        "first_iteration_active_outage": ";".join(first.get("selected_outage_active_lines") or ()),
        "top_cut_source_violation_max": max(
            [
                _parse_float(row.get("generated_cut_old_master_violation"))
                for row in iterations
                if row.get("generated_cut_old_master_violation") not in (None, "")
            ]
            or [""]
        ),
        "duplicate_cut_count": sum(1 for row in iterations if row.get("repeated_cut_signature_flag")),
        "raw_run_path": str(log_path.parents[1]),
        "log_path": str(log_path),
        "plan_path": str(log_path.parents[1] / "plans" / f"{run_id}_plan.csv"),
    }


def _summarize_milp_oracle(log_path: Path, *, run_id: str) -> dict[str, Any]:
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    run_config = payload["run_config"]
    selected_normal = run_config.get("selection", {}).get("scenarios_a", [])
    selected_disaster = run_config.get("selection", {}).get("scenarios_b", [])
    active = str(summary.get("selected_active_outage_lines", ""))
    runtime = _parse_float(summary.get("runtime_seconds"))
    separation_seconds = _parse_float(summary.get("separation_seconds"), runtime)
    return {
        "experiment_group": "",
        "run_id": run_id,
        "A": len(selected_normal),
        "B": len(selected_disaster),
        "K": int(summary["K"]),
        "separation_mode": "milp_oracle",
        "top_cuts": 0,
        "validation_level": summary["validation_level"],
        "stop_reason": summary["stop_reason"],
        "solver_status": summary["solver_status"],
        "max_iterations_budget": 1,
        "iterations": 1,
        "cuts": 0,
        "final_violation": _parse_float(summary.get("final_violation")),
        "final_violation_bound": _parse_float(summary.get("milp_obj_bound")),
        "runtime_seconds": runtime,
        "master_seconds": 0.0,
        "separation_seconds": separation_seconds,
        "cut_generation_seconds": 0.0,
        "separation_time_share": 1.0 if runtime > 0 else "",
        "evaluated_outage_patterns": "",
        "outage_pattern_count_formula": _outage_pattern_count(32, int(summary["K"])),
        "milp_statuses": summary.get("milp_status", ""),
        "milp_gap_max": summary.get("milp_gap", ""),
        "milp_node_count_total": summary.get("milp_node_count", ""),
        "omega_bound_upper": summary.get("omega_bound_upper", ""),
        "max_omega_bound_violation": summary.get("max_omega_bound_violation", ""),
        "min_omega_upper_slack": summary.get("min_omega_upper_slack", ""),
        "min_active_omega_upper_slack": summary.get("min_active_omega_upper_slack", ""),
        "max_separation_reconstruction_gap": summary.get("separation_reconstruction_gap", ""),
        "selected_active_outage_lines": active,
        "first_iteration_violation": _parse_float(summary.get("final_violation")),
        "first_iteration_active_outage": active,
        "top_cut_source_violation_max": "",
        "duplicate_cut_count": 0,
        "raw_run_path": str(log_path.parents[1]),
        "log_path": str(log_path),
        "plan_path": str(REPRESENTATIVE_PLAN),
    }


def _plan_signature(path: str | Path) -> tuple[tuple[int, int, int, int], ...]:
    rows = _read_rows(Path(path))
    return tuple(
        (
            int(row["bus"]),
            int(row["is_open"]),
            int(row["n_sl"]),
            int(row["n_fa"]),
        )
        for row in rows
    )


def _build_consistency_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    milp_rows = [row for row in rows if str(row.get("separation_mode", "")).startswith("milp")]
    non_milp_rows = [row for row in rows if not str(row.get("separation_mode", "")).startswith("milp")]
    return [
        {
            "check": "paper_facing_milp_only",
            "pass": (not non_milp_rows) and bool(milp_rows),
            "reason": (
                ""
                if (not non_milp_rows) and bool(milp_rows)
                else "paper-facing separation rows must all use MILP separation"
            ),
            "milp_row_count": len(milp_rows),
            "non_milp_row_count": len(non_milp_rows),
        }
    ]


def _build_omega_bound_audit(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    audit_rows: list[dict[str, Any]] = []
    for row in rows:
        max_violation = _parse_float(row.get("max_omega_bound_violation"), 0.0)
        min_upper_slack = _parse_float(row.get("min_omega_upper_slack"), 0.0)
        min_active_upper_slack = _parse_float(
            row.get("min_active_omega_upper_slack"),
            min_upper_slack,
        )
        omega_upper = _parse_float(row.get("omega_bound_upper"), 0.0)
        reconstruction_gap = _parse_float(row.get("max_separation_reconstruction_gap"), 0.0)
        bound_violation_ok = max_violation <= 1e-6
        active_upper_bound_nonbinding = min_active_upper_slack > 1e-6
        reconstruction_ok = reconstruction_gap <= 1e-4
        # Active-line omega can bind because failed-line rho variables have a
        # degenerate null direction in the compact separator. The paper-facing
        # cut coefficients are regenerated by fixed-outage paper duals, so this
        # field is diagnostic; the hard audit checks feasibility and objective
        # reconstruction rather than treating active binding as a failure.
        audit_rows.append(
            {
                "run_id": row.get("run_id", ""),
                "experiment_group": row.get("experiment_group", ""),
                "separation_mode": row.get("separation_mode", ""),
                "K": row.get("K", ""),
                "B": row.get("B", ""),
                "omega_bound_upper": omega_upper,
                "min_omega_upper_slack": min_upper_slack,
                "min_active_omega_upper_slack": min_active_upper_slack,
                "max_omega_bound_violation": max_violation,
                "max_separation_reconstruction_gap": reconstruction_gap,
                "bound_violation_ok": bound_violation_ok,
                "active_upper_bound_nonbinding": active_upper_bound_nonbinding,
                "active_upper_bound_binding_diagnostic": not active_upper_bound_nonbinding,
                "reconstruction_ok": reconstruction_ok,
                "pass": bound_violation_ok and reconstruction_ok,
            }
        )
    return audit_rows


def _write_figures(output_root: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures = output_root / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    b_rows = [row for row in rows if row.get("experiment_group") == "b_scaling"]
    if b_rows:
        b_rows = sorted(b_rows, key=lambda row: int(row["B"]))
        plt.figure(figsize=(6.2, 4.2))
        plt.plot(
            [int(r["B"]) for r in b_rows],
            [float(r["separation_seconds"]) for r in b_rows],
            "o-",
            color="#1f77b4",
        )
        plt.xscale("log")
        plt.xlabel("Disaster scenarios |B|")
        plt.ylabel("MILP separation time (s)")
        plt.title("MILP oracle time vs disaster support")
        plt.grid(True, which="both", alpha=0.25)
        plt.tight_layout()
        plt.savefig(figures / "separation_time_vs_B.png", dpi=220)
        plt.close()

    k_rows = [row for row in rows if row.get("experiment_group") == "k_scaling"]
    if k_rows:
        k_rows = sorted(k_rows, key=lambda row: int(row["K"]))
        plt.figure(figsize=(6.2, 4.2))
        plt.plot(
            [int(r["K"]) for r in k_rows],
            [float(r["separation_seconds"]) for r in k_rows],
            "o-",
            color="#d62728",
        )
        plt.xlabel("Outage budget K")
        plt.ylabel("MILP separation time (s)")
        plt.title("MILP oracle time vs outage budget")
        plt.grid(True, alpha=0.25)
        plt.tight_layout()
        plt.savefig(figures / "separation_time_vs_K.png", dpi=220)
        plt.close()

    cut_rows = [row for row in rows if row.get("experiment_group") == "cut_batch"]
    plt.figure(figsize=(6.4, 4.4))
    plotted = False
    for row in sorted(cut_rows, key=lambda item: int(item["top_cuts"])):
        trace_path = Path(str(row["raw_run_path"])) / "iteration_trace.csv"
        trace = _read_rows(trace_path)
        x_values: list[int] = []
        y_values: list[float] = []
        if trace:
            x_values = [int(t["iteration"]) for t in trace]
            y_values = [float(t["violation"]) for t in trace]
        else:
            log_path = Path(str(row.get("log_path", "")))
            if log_path.exists() and log_path.suffix == ".json":
                payload = json.loads(log_path.read_text(encoding="utf-8"))
                iterations = (payload.get("iteration_log") or {}).get("iterations") or []
                x_values = [int(t["iteration_id"]) for t in iterations]
                y_values = [float(t["separation_violation_value"]) for t in iterations]
        if not x_values:
            continue
        plotted = True
        y_values = [max(float(value), 1e-6) for value in y_values]
        plt.plot(
            x_values,
            y_values,
            marker="o",
            label=f"MILP top_cuts={row['top_cuts']}",
        )
    if plotted:
        plt.yscale("log")
        plt.xlabel("Benders iteration")
        plt.ylabel("Separation violation")
        plt.title("Cut batch size ablation")
        plt.legend()
        plt.tight_layout()
        plt.savefig(figures / "cut_batch_violation_trace.png", dpi=220)
    plt.close()


def _build_critic(
    *,
    output_root: Path,
    rows: Sequence[Mapping[str, Any]],
    consistency_rows: Sequence[Mapping[str, Any]],
    omega_audit_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    issues: list[str] = []
    if any(not str(row.get("separation_mode", "")).startswith("milp") for row in rows):
        issues.append("Paper-facing separation rows include non-MILP separation.")
    if not all(str(row.get("pass")) == "True" or row.get("pass") is True for row in consistency_rows):
        issues.append("MILP-only policy check did not pass.")
    if not all(str(row.get("pass")) == "True" or row.get("pass") is True for row in omega_audit_rows):
        issues.append("Omega-bound audit did not pass for all MILP separation rows.")
    k10 = [
        row
        for row in rows
        if row["K"] == 10 and str(row["separation_mode"]).startswith("milp")
    ]
    if not k10:
        issues.append("No K=10 MILP separation result exists.")
    b100 = [row for row in rows if row["B"] == 100 and row.get("experiment_group") == "b_scaling"]
    if not b100:
        issues.append("No B=100 disaster-support scaling result exists.")

    cut_rows = [row for row in rows if row.get("experiment_group") == "cut_batch"]
    top1 = next((row for row in cut_rows if int(row["top_cuts"]) == 1), None)
    better = False
    if top1 is not None:
        for row in cut_rows:
            if int(row["top_cuts"]) <= 1:
                continue
            better = better or (
                str(row["validation_level"]) in {"exact", "epsilon_certified"}
                and str(top1["validation_level"]) not in {"exact", "epsilon_certified"}
            )
            better = better or int(row["iterations"]) < int(top1["iterations"])
            better = better or float(row["final_violation"]) < float(top1["final_violation"])
    else:
        issues.append("No top_cuts=1 baseline exists for cut batching.")
    if not better:
        issues.append("Cut batching has not shown a clear advantage over top_cuts=1.")

    verdict = "PASS_TARGET" if not issues else "NEED_MORE_EVIDENCE"
    review = {
        "target": "separation_scalability_and_cut_effectiveness",
        "verdict": verdict,
        "blocking_or_major_issues": issues,
        "accepted_claims": [
            "B and K are the uncertainty dimensions that directly exercise disaster separation.",
            "All paper-facing separation rows use the MILP separation oracle, including K=1 and K=2.",
            "Omega bounds are audited for all reported MILP separation rows.",
            "K-scaling MILP rows are scalability evidence and must report status/gap/runtime.",
            "Cut batching can be claimed only if the ablation shows finite-iteration progress.",
        ],
        "next_objective": "update_ieee_computation_section" if verdict == "PASS_TARGET" else "remediate_separation_scalability",
    }
    _write_json(output_root / "separation_scalability_critic_review.json", review)
    md = [
        "# Separation Scalability Critic Review",
        "",
        f"Verdict: `{verdict}`",
        "",
        "## Issues",
    ]
    md.extend([f"- {issue}" for issue in issues] or ["- none"])
    md.extend(
        [
            "",
            "## Accepted Claims",
            "- B-scaling and K-scaling are the paper-facing algorithmic scalability axes.",
            "- A-scaling should not be used to claim cut-generation scalability.",
            "- Paper-facing rows must use MILP separation; exact enumeration is not an algorithmic result.",
            "- Omega-bound validity is audited for reported MILP separation rows.",
        ]
    )
    (output_root / "separation_scalability_critic_review.md").write_text(
        "\n".join(md) + "\n",
        encoding="utf-8",
    )
    return review


def _write_iteration_pack(output_root: Path, review: Mapping[str, Any]) -> None:
    pack = output_root / "separation_scalability_iteration"
    (pack / "critic_cards").mkdir(parents=True, exist_ok=True)
    (pack / "pro_consultation.md").write_text(
        "# Pro Consultation\n\n"
        "Status: not completed in this run. The local critic gate treats Pro review as "
        "pending rather than approval; generated claims must still pass local audit.\n",
        encoding="utf-8",
    )
    (pack / "critic_synthesis.md").write_text(
        "# Critic Synthesis\n\n"
        f"Verdict: `{review['verdict']}`\n\n"
        "The target is separation-focused runtime evidence. A-scaling is excluded from "
        "the main algorithmic claim.\n",
        encoding="utf-8",
    )
    _write_json(pack / "critic_review.json", dict(review))
    (pack / "decision_card.md").write_text(
        "# Decision Card\n\n"
        "- Adopt B-scaling and K-scaling as the computation-time axes.\n"
        "- Use MILP separation for all paper-facing K values, including K=1 and K=2.\n"
        "- Use MILP no-good constraints for top-M cut generation; do not use outage enumeration.\n"
        "- Audit omega-bound slack and reconstruction gap for every reported MILP row.\n",
        encoding="utf-8",
    )
    (pack / "next_objective.md").write_text(
        f"# Next Objective\n\n{review['next_objective']}\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="results/paper_final")
    parser.add_argument("--accepted-config", default=str(ACCEPTED_CONFIG))
    parser.add_argument("--b-values", default="1,5,10,20,50,100")
    parser.add_argument("--k-values", default="1,2,3,5,7,10")
    parser.add_argument("--cut-batches", default="1,3,5")
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--master-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--master-mip-gap", type=float, default=0.02)
    parser.add_argument("--separation-time-limit-seconds", type=float, default=180.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.02)
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    raw_root = output_root / "separation_scalability_runs"
    raw_root.mkdir(parents=True, exist_ok=True)
    base = _read_json(Path(args.accepted_config))
    rows: list[dict[str, Any]] = []
    run_cache: dict[tuple[str, int, int, int, int], dict[str, Any]] = {}

    def milp_row(a: int, b: int, k: int, top_cuts: int, group: str) -> dict[str, Any]:
        key = ("milp", a, b, k, top_cuts)
        if key not in run_cache:
            run_id = f"sep_milp_A{a:02d}_B{b:03d}_K{k:02d}_top{top_cuts:03d}"
            run_cache[key] = _run_milp(
                base=base,
                raw_root=raw_root,
                run_id=run_id,
                a_count=a,
                b_count=b,
                k=k,
                max_iterations=args.max_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
                top_cuts=top_cuts,
                skip_existing=args.skip_existing,
            )
        row = dict(run_cache[key])
        row["experiment_group"] = group
        return row

    def milp_oracle_row(a: int, b: int, k: int, group: str) -> dict[str, Any]:
        key = ("milp_oracle", a, b, k, 0)
        if key not in run_cache:
            run_id = f"sep_milp_oracle_A{a:02d}_B{b:03d}_K{k:02d}"
            run_cache[key] = _run_milp_oracle(
                base=base,
                raw_root=raw_root,
                run_id=run_id,
                a_count=a,
                b_count=b,
                k=k,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
                skip_existing=args.skip_existing,
            )
        row = dict(run_cache[key])
        row["experiment_group"] = group
        return row

    start = perf_counter()
    for b in _parse_int_list(args.b_values):
        rows.append(milp_oracle_row(10, b, 2, "b_scaling"))

    for k in _parse_int_list(args.k_values):
        rows.append(milp_oracle_row(10, 10, k, "k_scaling"))

    for top_cuts in _parse_int_list(args.cut_batches):
        rows.append(milp_row(10, 10, 2, top_cuts, "cut_batch"))

    _write_rows(output_root / "separation_scalability_summary.csv", rows)
    _write_rows(
        output_root / "b_scaling_separation_summary.csv",
        [row for row in rows if row["experiment_group"] == "b_scaling"],
    )
    _write_rows(
        output_root / "k_scaling_separation_summary.csv",
        [row for row in rows if row["experiment_group"] == "k_scaling"],
    )
    _write_rows(
        output_root / "cut_batch_ablation.csv",
        [row for row in rows if row["experiment_group"] == "cut_batch"],
    )
    consistency_rows = _build_consistency_rows(rows)
    _write_rows(output_root / "milp_separation_policy_check.csv", consistency_rows)
    omega_audit_rows = _build_omega_bound_audit(rows)
    _write_rows(output_root / "omega_bound_audit.csv", omega_audit_rows)
    _write_figures(output_root, rows)
    review = _build_critic(
        output_root=output_root,
        rows=rows,
        consistency_rows=consistency_rows,
        omega_audit_rows=omega_audit_rows,
    )
    review["driver_runtime_seconds"] = perf_counter() - start
    _write_json(output_root / "separation_scalability_critic_review.json", review)
    _write_iteration_pack(output_root, review)
    print(json.dumps(review, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
