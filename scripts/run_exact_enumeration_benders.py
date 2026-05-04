"""Run a diagnostic Benders loop with exact outage-enumeration separation."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from time import perf_counter
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import (  # noqa: E402
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
    write_plan_csv,
)
from scripts.build_paper_final_analysis import CRITICAL_BUS_CONFIG  # noqa: E402
from src.production.cut_factory import generate_structured_cut_from_decompositions  # noqa: E402
from src.production.master_problem import RestrictedMasterCut, solve_master_problem  # noqa: E402
from src.reference.disaster_primal_ref import (  # noqa: E402
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
)
from src.reference.outage_enumerator import solve_separation_violation_by_enumeration  # noqa: E402


def _plan_from_solution(instance, solution):
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus=solution.first_stage_solution.z_by_bus,
        n_sl_by_bus=solution.first_stage_solution.n_sl_by_bus,
        n_fa_by_bus=solution.first_stage_solution.n_fa_by_bus,
    )


def _plan_rows(instance, solution) -> list[dict[str, Any]]:
    return [
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


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _load_config(config_log: Path) -> dict[str, Any]:
    payload = json.loads(config_log.read_text(encoding="utf-8"))
    return dict(payload["run_config"] if "run_config" in payload else payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-log", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--run-id", default="exact_enum_benders")
    parser.add_argument("--mode-override", default=None)
    parser.add_argument("--k-override", type=int, default=None)
    parser.add_argument("--ev-scale-override", type=float, default=None)
    parser.add_argument("--nbar-sl-override", type=int, default=None)
    parser.add_argument("--nbar-fa-override", type=int, default=None)
    parser.add_argument("--max-iterations", type=int, default=10)
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--master-time-limit-seconds", type=float, default=None)
    parser.add_argument("--master-mip-gap", type=float, default=None)
    parser.add_argument("--allow-master-suboptimal-incumbent", action="store_true")
    parser.add_argument("--top-cuts", type=int, default=1)
    args = parser.parse_args()

    output_root = Path(args.output_root)
    logs_dir = output_root / "logs"
    plans_dir = output_root / "plans"
    logs_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)

    config = _load_config(Path(args.config_log))
    config["run_id"] = str(args.run_id)
    config["case_name"] = str(args.run_id)
    if args.mode_override:
        config["mode"] = str(args.mode_override)
    if args.ev_scale_override is not None:
        config["ev_penetration_scale"] = float(args.ev_scale_override)
    if args.k_override is not None:
        overrides = dict(config.get("parameter_overrides", {}))
        ambiguity = dict(overrides.get("ambiguity", {}))
        ambiguity["k_max_outages"] = int(args.k_override)
        overrides["ambiguity"] = ambiguity
        config["parameter_overrides"] = overrides
    if args.nbar_sl_override is not None or args.nbar_fa_override is not None:
        overrides = dict(config.get("parameter_overrides", {}))
        ev = dict(overrides.get("ev", {}))
        if args.nbar_sl_override is not None:
            ev["nbar_sl"] = int(args.nbar_sl_override)
        if args.nbar_fa_override is not None:
            ev["nbar_fa"] = int(args.nbar_fa_override)
        overrides["ev"] = ev
        config["parameter_overrides"] = overrides
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    instance = prepare_instance_for_run(
        load_instance_for_run(config, critical_buses=critical_buses),
        config,
    )

    cuts: list[RestrictedMasterCut] = []
    iteration_rows: list[dict[str, Any]] = []
    master_rows: list[dict[str, Any]] = []
    generated_cut_rows: list[dict[str, Any]] = []
    final_solution = None
    final_stop_reason = "max_iterations"
    total_start = perf_counter()

    for iteration_id in range(int(args.max_iterations)):
        master_start = perf_counter()
        master, solution = solve_master_problem(
            instance,
            cuts=cuts,
            normal_scenario_ids=instance.sets.loaded_normal_scenarios,
            time_limit_seconds=args.master_time_limit_seconds,
            mip_gap=args.master_mip_gap,
            allow_suboptimal_incumbent=bool(args.allow_master_suboptimal_incumbent),
            model_name=f"{args.run_id}_master_{iteration_id:03d}",
            log_to_console=False,
        )
        master_seconds = perf_counter() - master_start
        final_solution = solution
        plan = _plan_from_solution(instance, solution)
        master_rows.append(
            {
                "iteration": iteration_id,
                "master_objective": float(solution.objective_value or 0.0),
                "master_status": solution.model_status,
                "master_seconds": master_seconds,
                "cut_count_before": len(cuts),
                "sites": sum(solution.first_stage_solution.z_by_bus.values()),
                "slow_chargers": sum(solution.first_stage_solution.n_sl_by_bus.values()),
                "fast_chargers": sum(solution.first_stage_solution.n_fa_by_bus.values()),
            }
        )
        _write_csv(output_root / "master_trace.csv", master_rows)
        print(
            f"[{args.run_id}] iter={iteration_id} master_status={solution.model_status} "
            f"master_seconds={master_seconds:.2f} cuts={len(cuts)}",
            flush=True,
        )

        separation_start = perf_counter()
        oracle = solve_separation_violation_by_enumeration(
            instance,
            plan=plan,
            alpha=float(solution.alpha_value),
            lambda_by_line_id=solution.lambda_by_line_id,
            budget_k=int(instance.ambiguity.k_max_outages),
            scenario_ids=instance.sets.loaded_disaster_scenarios,
        )
        separation_seconds = perf_counter() - separation_start
        print(
            f"[{args.run_id}] iter={iteration_id} exact_sep_seconds={separation_seconds:.2f} "
            f"violation={max(0.0, float(oracle.objective_value)):.6g}",
            flush=True,
        )
        violation = max(0.0, float(oracle.objective_value))
        active_lines = tuple(oracle.best_pattern.active_line_ids)

        row = {
            "iteration": iteration_id,
            "master_objective": float(solution.objective_value or 0.0),
            "construction_cost": float(solution.construction_cost_value),
            "normal_term": float(solution.averaged_normal_cost_value),
            "alpha": float(solution.alpha_value),
            "lambda_times_fp": float(solution.lambda_fp_value),
            "violation": violation,
            "active_outage_lines": ";".join(active_lines),
            "cut_count_before": len(cuts),
            "master_seconds": master_seconds,
            "exact_enumeration_seconds": separation_seconds,
            "evaluated_outage_patterns": len(oracle.evaluated_patterns),
            "sites": sum(solution.first_stage_solution.z_by_bus.values()),
            "slow_chargers": sum(solution.first_stage_solution.n_sl_by_bus.values()),
            "fast_chargers": sum(solution.first_stage_solution.n_fa_by_bus.values()),
        }
        iteration_rows.append(row)
        _write_csv(output_root / "iteration_trace.csv", iteration_rows)
        write_plan_csv(plans_dir / f"{args.run_id}_iter{iteration_id:03d}_plan.csv", _plan_rows(instance, solution))

        if violation <= float(args.epsilon_cert):
            final_stop_reason = "certified_epsilon" if float(args.epsilon_cert) > 0.0 else "certified_exact"
            break

        if iteration_id == int(args.max_iterations) - 1:
            final_stop_reason = "max_iterations"
            break

        ranked_patterns = sorted(
            oracle.evaluated_patterns,
            key=lambda pattern: (
                -float(oracle.objective_by_pattern[pattern.label]),
                pattern.active_line_ids,
            ),
        )
        added_this_round = 0
        seen_signatures = {row["cut_signature_hash"] for row in generated_cut_rows}
        for pattern in ranked_patterns:
            pattern_violation = max(0.0, float(oracle.objective_by_pattern[pattern.label]))
            if pattern_violation <= float(args.epsilon_cert):
                continue
            outage = build_fixed_outage_vector(instance, by_line_id=pattern.by_line_id)
            cut_result = generate_structured_cut_from_decompositions(
                instance,
                plan=plan,
                outage=outage,
                samplewise_decompositions_by_scenario=oracle.samplewise_decomposition_by_pattern[
                    pattern.label
                ],
                cut_id=f"{args.run_id}_cut_{len(cuts) + 1:03d}",
                provenance=f"{args.run_id}_exact_enum_iter_{iteration_id:03d}",
                source_alpha=float(solution.alpha_value),
                source_lambda_by_line_id=solution.lambda_by_line_id,
                source_violation_value=pattern_violation,
            )
            if cut_result.cut_signature_hash in seen_signatures:
                continue
            cuts.append(cut_result.cut)
            seen_signatures.add(cut_result.cut_signature_hash)
            added_this_round += 1
            generated_cut_rows.append(
                {
                    "cut_id": cut_result.cut.cut_id,
                    "iteration": iteration_id,
                    "rank": added_this_round,
                    "old_master_cut_violation": cut_result.old_master_cut_violation,
                    "source_violation_value": pattern_violation,
                    "active_outage_lines": ";".join(pattern.active_line_ids),
                    "gamma_z_nonzero_count": cut_result.gamma_z_nonzero_count,
                    "gamma_n_sl_nonzero_count": cut_result.gamma_n_sl_nonzero_count,
                    "gamma_n_fa_nonzero_count": cut_result.gamma_n_fa_nonzero_count,
                    "phi_nonzero_count": cut_result.phi_nonzero_count,
                    "cut_signature_hash": cut_result.cut_signature_hash,
                }
            )
            if added_this_round >= max(1, int(args.top_cuts)):
                break
        if added_this_round == 0:
            final_stop_reason = "no_new_cuts"
            break
        _write_csv(output_root / "generated_cuts.csv", generated_cut_rows)

    if final_solution is None:
        raise RuntimeError("Exact-enumeration Benders produced no master solution.")
    write_plan_csv(plans_dir / f"{args.run_id}_final_plan.csv", _plan_rows(instance, final_solution))
    summary = {
        "run_id": args.run_id,
        "family_name": "exact_enumeration_benders",
        "case_name": args.run_id,
        "parameter_regime": str(config.get("parameter_regime", "")),
        "mode": str(config.get("mode", "")),
        "validation_level": (
            "epsilon_certified"
            if final_stop_reason == "certified_epsilon"
            else "exact"
            if final_stop_reason == "certified_exact"
            else "smoke_only"
        ),
        "stop_reason": final_stop_reason,
        "solver_status": str(final_solution.model_status),
        "max_iterations_budget": int(args.max_iterations),
        "epsilon_cert": float(args.epsilon_cert),
        "top_cuts": int(args.top_cuts),
        "normal_scenario_count": len(instance.sets.loaded_normal_scenarios),
        "disaster_scenario_count": len(instance.sets.loaded_disaster_scenarios),
        "K": int(instance.ambiguity.k_max_outages),
        "iterations": len(iteration_rows),
        "cuts": len(cuts),
        "final_violation": iteration_rows[-1]["violation"],
        "final_objective": float(final_solution.objective_value or 0.0),
        "final_sites": sum(final_solution.first_stage_solution.z_by_bus.values()),
        "final_slow_chargers": sum(final_solution.first_stage_solution.n_sl_by_bus.values()),
        "final_fast_chargers": sum(final_solution.first_stage_solution.n_fa_by_bus.values()),
        "runtime_seconds": perf_counter() - total_start,
    }
    _write_csv(output_root / "summary.csv", [summary])
    (logs_dir / f"{args.run_id}_config.json").write_text(
        json.dumps({"run_config": config, "summary": summary}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
