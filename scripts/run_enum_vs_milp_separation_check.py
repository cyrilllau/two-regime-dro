"""Compare full-support K=2 outage enumeration against MILP separation.

This is an engineering diagnostic, not a paper-facing Benders algorithm.  It
checks whether the MILP separator and a full-support outage enumeration produce
the same separation value for a fixed master point.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from time import perf_counter
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_paper_final_analysis import CRITICAL_BUS_CONFIG  # noqa: E402
from scripts.experiment_pack_utils import (  # noqa: E402
    _cut_from_payload,
    _load_fixed_plan_from_csv,
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from src.production.master_problem import (  # noqa: E402
    RestrictedMasterCut,
    build_master_problem,
    extract_master_problem_solution,
    solve_master_problem,
)
from src.production.separation_milp import solve_separation_milp  # noqa: E402
from src.reference.disaster_primal_ref import (  # noqa: E402
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
)
from src.reference.outage_enumerator import (  # noqa: E402
    EnumeratedOutagePattern,
    enumerate_outages,
)
from src.production.disaster_dual_paper import solve_disaster_dual_paper  # noqa: E402


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


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _resolve_path(raw: str | None, *, base: Path = REPO_ROOT) -> Path | None:
    if raw in (None, ""):
        return None
    path = Path(str(raw))
    return path if path.is_absolute() else base / path


def _load_cuts(path: Path) -> list[RestrictedMasterCut]:
    payload = _read_json(path)
    return [_cut_from_payload(cut_payload) for cut_payload in payload.get("cuts", ())]


def _solve_master_point(
    *,
    run_config: Mapping[str, Any],
    cut_pool_path: Path,
    master_time_limit_seconds: float,
    master_mip_gap: float,
    allow_suboptimal_incumbent: bool,
    run_id: str,
) -> tuple[Any, Any, list[RestrictedMasterCut]]:
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    instance = prepare_instance_for_run(
        load_instance_for_run(run_config, critical_buses=critical_buses),
        run_config,
    )
    cuts = _load_cuts(cut_pool_path)
    _, solution = solve_master_problem(
        instance,
        cuts=cuts,
        normal_scenario_ids=instance.sets.loaded_normal_scenarios,
        time_limit_seconds=master_time_limit_seconds,
        mip_gap=master_mip_gap,
        allow_suboptimal_incumbent=allow_suboptimal_incumbent,
        model_name=f"{run_id}_master_reconstruct",
        log_to_console=False,
    )
    plan = build_fixed_first_stage_plan(
        instance,
        z_by_bus=solution.first_stage_solution.z_by_bus,
        n_sl_by_bus=solution.first_stage_solution.n_sl_by_bus,
        n_fa_by_bus=solution.first_stage_solution.n_fa_by_bus,
    )
    return instance, (solution, plan), cuts


def _solve_fixed_plan_master_point(
    *,
    run_config: Mapping[str, Any],
    cut_pool_path: Path,
    fixed_plan_path: Path,
    master_time_limit_seconds: float,
    master_mip_gap: float,
    run_id: str,
) -> tuple[Any, Any, list[RestrictedMasterCut]]:
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    instance = prepare_instance_for_run(
        load_instance_for_run(run_config, critical_buses=critical_buses),
        run_config,
    )
    cuts = _load_cuts(cut_pool_path)
    fixed_plan = _load_fixed_plan_from_csv(instance, fixed_plan_path)
    master = build_master_problem(
        instance,
        cuts=cuts,
        normal_scenario_ids=instance.sets.loaded_normal_scenarios,
        warm_start_plan=fixed_plan,
        model_name=f"{run_id}_fixed_plan_master_reconstruct",
        log_to_console=False,
    )
    for bus in instance.sets.buses:
        master.model.addConstr(
            master.first_stage.z_by_bus[bus] == int(fixed_plan.z_by_bus[bus]),
            name=f"fix_z_{bus}",
        )
        master.model.addConstr(
            master.first_stage.n_sl_by_bus[bus] == int(fixed_plan.n_sl_by_bus[bus]),
            name=f"fix_n_sl_{bus}",
        )
        master.model.addConstr(
            master.first_stage.n_fa_by_bus[bus] == int(fixed_plan.n_fa_by_bus[bus]),
            name=f"fix_n_fa_{bus}",
        )
    master.model.Params.TimeLimit = float(master_time_limit_seconds)
    master.model.Params.MIPGap = float(master_mip_gap)
    master.model.optimize()
    solution = extract_master_problem_solution(master)
    if solution.model_status != "OPTIMAL":
        raise ValueError(
            "Fixed-plan master reconstruction did not reach OPTIMAL status: "
            f"{solution.model_status}."
        )
    return instance, (solution, fixed_plan), cuts


def _run_milp_separator(
    *,
    instance,
    plan,
    alpha: float,
    lambda_by_line_id: Mapping[str, float],
    omega_bound_upper: float,
    time_limit_seconds: float,
    mip_gap: float,
    gurobi_params: Mapping[str, Any],
    run_id: str,
) -> tuple[dict[str, Any], Any]:
    omega_bounds = {line_id: (0.0, float(omega_bound_upper)) for line_id in instance.sets.line_ids}
    start = perf_counter()
    _, solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=float(alpha),
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=omega_bounds,
        budget_k=int(instance.ambiguity.k_max_outages),
        scenario_ids=instance.sets.loaded_disaster_scenarios,
        model_name=f"{run_id}_milp_separator",
        time_limit_seconds=time_limit_seconds,
        mip_gap=mip_gap,
        gurobi_params=gurobi_params,
        require_optimal=False,
        log_to_console=False,
    )
    elapsed = perf_counter() - start
    return (
        {
            "milp_status": solution.model_status,
            "milp_objval": solution.objective_value,
            "milp_objbound": solution.obj_bound,
            "milp_gap": solution.mip_gap,
            "milp_nodes": solution.node_count,
            "milp_time": elapsed,
            "milp_solver_runtime": solution.runtime_seconds,
            "milp_active_outage_lines": ";".join(
                line_id
                for line_id in instance.sets.line_ids
                if int(solution.delta_by_line_id.get(line_id, 0)) == 1
            ),
            "milp_reconstruction_gap": solution.reconstruction_gap,
            "milp_max_omega_bound_violation": solution.max_omega_bound_violation,
        },
        solution,
    )


def _pattern_value(
    *,
    instance,
    plan,
    pattern: EnumeratedOutagePattern,
    scenario_ids: Sequence[int],
    alpha: float,
    lambda_by_line_id: Mapping[str, float],
    run_id: str,
) -> tuple[float, float]:
    outage = build_fixed_outage_vector(instance, by_line_id=pattern.by_line_id)
    total = 0.0
    for scenario_id in scenario_ids:
        model, solution = solve_disaster_dual_paper(
            instance,
            plan=plan,
            outage=outage,
            scenario_id=int(scenario_id),
            model_name=f"{run_id}_enum_b{int(scenario_id):03d}_{pattern.label}",
            log_to_console=False,
        )
        total += float(solution.objective_value or 0.0)
        try:
            model.model.dispose()
        except Exception:
            pass
    average_value = total / len(scenario_ids)
    penalty = sum(float(lambda_by_line_id[line_id]) * pattern.by_line_id[line_id] for line_id in instance.sets.line_ids)
    return float(average_value - penalty - float(alpha)), float(average_value)


def _run_exact_enumeration(
    *,
    instance,
    plan,
    alpha: float,
    lambda_by_line_id: Mapping[str, float],
    run_id: str,
    live_path: Path,
    max_patterns: int | None,
    progress_every: int,
) -> dict[str, Any]:
    scenario_ids = tuple(int(value) for value in instance.sets.loaded_disaster_scenarios)
    patterns = enumerate_outages(
        instance.sets.line_ids,
        budget_k=int(instance.ambiguity.k_max_outages),
    )
    if max_patterns is not None:
        patterns = patterns[: int(max_patterns)]
    best_value = float("-inf")
    best_average = float("nan")
    best_pattern = patterns[0]
    rows: list[dict[str, Any]] = []
    start = perf_counter()
    for index, pattern in enumerate(patterns, start=1):
        value, average_value = _pattern_value(
            instance=instance,
            plan=plan,
            pattern=pattern,
            scenario_ids=scenario_ids,
            alpha=alpha,
            lambda_by_line_id=lambda_by_line_id,
            run_id=run_id,
        )
        if value > best_value:
            best_value = float(value)
            best_average = float(average_value)
            best_pattern = pattern
        if index == 1 or index == len(patterns) or index % max(1, progress_every) == 0:
            rows.append(
                {
                    "evaluated_patterns": index,
                    "total_patterns": len(patterns),
                    "elapsed_seconds": perf_counter() - start,
                    "current_pattern": pattern.label,
                    "current_active_outage_lines": ";".join(pattern.active_line_ids),
                    "current_violation": value,
                    "best_violation": best_value,
                    "best_active_outage_lines": ";".join(best_pattern.active_line_ids),
                }
            )
            _write_rows(live_path, rows)
    return {
        "enum_status": "complete",
        "enum_violation": best_value,
        "enum_average_disaster_value": best_average,
        "enum_time": perf_counter() - start,
        "enum_evaluated_patterns": len(patterns),
        "enum_total_patterns": len(enumerate_outages(instance.sets.line_ids, budget_k=int(instance.ambiguity.k_max_outages))),
        "enum_active_outage_lines": ";".join(best_pattern.active_line_ids),
        "enum_partial": int(max_patterns is not None),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-run-log", required=True)
    parser.add_argument("--cut-pool-path", default="")
    parser.add_argument("--fixed-plan-path", default="")
    parser.add_argument("--output-root", default="results/engineering_acceleration/enum_vs_milp")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--omega-bound-upper", type=float, default=20_000_000.0)
    parser.add_argument("--master-time-limit-seconds", type=float, default=180.0)
    parser.add_argument("--master-mip-gap", type=float, default=0.03)
    parser.add_argument("--allow-master-suboptimal-incumbent", action="store_true")
    parser.add_argument("--separation-time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.02)
    parser.add_argument("--separation-gurobi-params", default="")
    parser.add_argument("--skip-milp", action="store_true")
    parser.add_argument("--max-patterns", type=int, default=None)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()

    source_log_path = _resolve_path(args.source_run_log)
    if source_log_path is None or not source_log_path.exists():
        raise FileNotFoundError(args.source_run_log)
    source_payload = _read_json(source_log_path)
    run_config = dict(source_payload["run_config"])
    run_id = args.run_id or f"{run_config.get('run_id', source_log_path.stem)}_enum_vs_milp"
    output_root = _resolve_path(args.output_root)
    assert output_root is not None
    run_root = output_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    cut_pool_path = _resolve_path(args.cut_pool_path)
    if cut_pool_path is None:
        cut_pool_path = _resolve_path(source_payload.get("artifact_paths", {}).get("cut_pool_path"))
    if cut_pool_path is None or not cut_pool_path.exists():
        raise FileNotFoundError(f"Cut pool not found for {source_log_path}.")

    fixed_plan_path = _resolve_path(args.fixed_plan_path)
    if fixed_plan_path is not None:
        instance, (master_solution, plan), cuts = _solve_fixed_plan_master_point(
            run_config=run_config,
            cut_pool_path=cut_pool_path,
            fixed_plan_path=fixed_plan_path,
            master_time_limit_seconds=float(args.master_time_limit_seconds),
            master_mip_gap=float(args.master_mip_gap),
            run_id=run_id,
        )
        master_point_mode = "fixed_plan_alpha_lambda_reconstruction"
    else:
        instance, (master_solution, plan), cuts = _solve_master_point(
            run_config=run_config,
            cut_pool_path=cut_pool_path,
            master_time_limit_seconds=float(args.master_time_limit_seconds),
            master_mip_gap=float(args.master_mip_gap),
            allow_suboptimal_incumbent=bool(args.allow_master_suboptimal_incumbent),
            run_id=run_id,
        )
        master_point_mode = "free_master_reconstruction"

    sep_params = dict(json.loads(args.separation_gurobi_params)) if args.separation_gurobi_params else {}
    if args.skip_milp:
        milp_row = {
            "milp_status": "SKIPPED",
            "milp_objval": None,
            "milp_objbound": None,
            "milp_gap": None,
            "milp_nodes": None,
            "milp_time": 0.0,
            "milp_solver_runtime": None,
            "milp_active_outage_lines": "",
            "milp_reconstruction_gap": None,
            "milp_max_omega_bound_violation": None,
        }
    else:
        milp_row, _ = _run_milp_separator(
            instance=instance,
            plan=plan,
            alpha=float(master_solution.alpha_value),
            lambda_by_line_id=master_solution.lambda_by_line_id,
            omega_bound_upper=float(args.omega_bound_upper),
            time_limit_seconds=float(args.separation_time_limit_seconds),
            mip_gap=float(args.separation_mip_gap),
            gurobi_params=sep_params,
            run_id=run_id,
        )
    enum_row = _run_exact_enumeration(
        instance=instance,
        plan=plan,
        alpha=float(master_solution.alpha_value),
        lambda_by_line_id=master_solution.lambda_by_line_id,
        run_id=run_id,
        live_path=run_root / "enum_live_trace.csv",
        max_patterns=args.max_patterns,
        progress_every=int(args.progress_every),
    )
    milp_obj = milp_row.get("milp_objval")
    enum_value = enum_row.get("enum_violation")
    abs_difference = (
        abs(float(milp_obj) - float(enum_value))
        if milp_obj is not None and enum_value is not None
        else ""
    )
    row = {
        "run_id": run_id,
        "source_run_id": run_config.get("run_id", ""),
        "runtime_source": run_config.get("runtime_source", ""),
        "A": len(instance.sets.loaded_normal_scenarios),
        "B": len(instance.sets.loaded_disaster_scenarios),
        "K": int(instance.ambiguity.k_max_outages),
        "cut_count": len(cuts),
        "master_point_mode": master_point_mode,
        "fixed_plan_path": str(fixed_plan_path or ""),
        "master_status": master_solution.model_status,
        "master_objective": master_solution.objective_value,
        "alpha": master_solution.alpha_value,
        "lambda_times_FP": master_solution.lambda_fp_value,
        "epsilon_cert": float(args.epsilon_cert),
        **milp_row,
        **enum_row,
        "abs_difference": abs_difference,
        "certifiable_by_enum": int(float(enum_row["enum_violation"]) <= float(args.epsilon_cert) and not enum_row["enum_partial"]),
        "certifiable_by_milp_bound": int(
            milp_row.get("milp_objbound") is not None
            and float(milp_row["milp_objbound"]) <= float(args.epsilon_cert)
        ),
        "diagnostic_only": 1,
    }
    _write_rows(run_root / "enum_vs_milp.csv", [row])
    _write_json(
        run_root / "enum_vs_milp_manifest.json",
        {
            "source_run_log": str(source_log_path),
            "cut_pool_path": str(cut_pool_path),
            "fixed_plan_path": str(fixed_plan_path or ""),
            "master_point_mode": master_point_mode,
            "run_config": run_config,
            "diagnostic_only": True,
            "paper_claim_allowed": False,
            "reason": "Full-support enumeration/MILP separator consistency check.",
        },
    )
    _write_rows(output_root / "enum_vs_milp_summary.csv", [row])
    print(json.dumps(row, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
