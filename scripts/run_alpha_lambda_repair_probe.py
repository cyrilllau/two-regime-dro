"""Fixed-plan alpha/lambda active-support repair probe for hard K rows."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any, Mapping, Sequence

from gurobipy import GRB, Model, quicksum

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import apply_parameter_overrides, load_critical_buses  # noqa: E402
from scripts.run_full_benders_scalability import (  # noqa: E402
    CRITICAL_BUSES,
    DEFAULT_ACCEPTED_LOG,
    _read_accepted_config,
)
from src.instance.canonical_instance import load_canonical_instance  # noqa: E402
from src.instance.selection import build_runtime_selection  # noqa: E402
from src.production.separation_milp import (  # noqa: E402
    extract_separation_milp_solution_pool,
    solve_separation_milp,
)
from src.reference.disaster_primal_ref import (  # noqa: E402
    FixedFirstStagePlan,
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
    solve_disaster_primal_reference,
)
from src.reference.outage_enumerator import derive_single_line_omega_bounds  # noqa: E402


def _parse_params(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    return dict(json.loads(raw))


def _load_plan(instance, path: Path) -> FixedFirstStagePlan:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _pattern_key(pattern: Sequence[str]) -> str:
    return ";".join(sorted(str(line_id) for line_id in pattern))


def _pattern_from_key(key: str) -> tuple[str, ...]:
    if not key:
        return tuple()
    return tuple(token for token in key.split(";") if token)


def _load_trace_patterns(paths: Sequence[Path], *, max_patterns: int) -> list[tuple[str, ...]]:
    patterns: list[tuple[str, ...]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                pattern = _pattern_from_key(
                    str(
                        row.get(
                            "selected_outage_active_lines",
                            row.get("pattern_key", ""),
                        )
                    )
                )
                key = _pattern_key(pattern)
                if not key or key in seen:
                    continue
                seen.add(key)
                patterns.append(pattern)
                if len(patterns) >= int(max_patterns):
                    return patterns
    return patterns


def _evaluate_pattern_value(
    instance,
    *,
    plan: FixedFirstStagePlan,
    pattern: Sequence[str],
    scenario_ids: Sequence[int],
    model_name_prefix: str,
) -> float:
    delta = {line_id: int(line_id in set(pattern)) for line_id in instance.sets.line_ids}
    outage = build_fixed_outage_vector(instance, by_line_id=delta)
    values: list[float] = []
    key = _pattern_key(pattern).replace(";", "_")
    for scenario_id in scenario_ids:
        model, solution = solve_disaster_primal_reference(
            instance,
            plan=plan,
            outage=outage,
            scenario_id=int(scenario_id),
            model_name=f"{model_name_prefix}_{key}_b{int(scenario_id)}",
            log_to_console=False,
        )
        model.model.dispose()
        values.append(float(solution.objective_value or 0.0))
    return float(sum(values) / len(values))


def _solve_alpha_lambda_lp(
    *,
    line_ids: Sequence[str],
    fp_by_line_id: Mapping[str, float],
    alpha_min: float,
    value_by_pattern_key: Mapping[str, float],
    gurobi_params: Mapping[str, Any],
) -> tuple[float, dict[str, float], float]:
    model = Model("alpha_lambda_active_support_repair")
    model.Params.OutputFlag = 0
    for key, value in dict(gurobi_params).items():
        if value not in (None, ""):
            setattr(model.Params, str(key), value)
    alpha = model.addVar(lb=float(alpha_min), name="alpha")
    lambdas = {line_id: model.addVar(lb=0.0, name=f"lambda_{line_id}") for line_id in line_ids}
    for index, (pattern_key, value) in enumerate(value_by_pattern_key.items()):
        active = set(_pattern_from_key(pattern_key))
        model.addConstr(
            alpha + quicksum(lambdas[line_id] for line_id in active) >= float(value),
            name=f"support_pattern_{index:04d}",
        )
    model.setObjective(
        alpha + quicksum(float(fp_by_line_id[line_id]) * lambdas[line_id] for line_id in line_ids),
        sense=GRB.MINIMIZE,
    )
    model.optimize()
    if int(model.Status) != GRB.OPTIMAL:
        raise RuntimeError(f"alpha/lambda LP failed with status {model.Status}.")
    alpha_value = float(alpha.X)
    lambda_values = {line_id: max(0.0, float(var.X)) for line_id, var in lambdas.items()}
    objective_value = float(model.ObjVal)
    model.dispose()
    return alpha_value, lambda_values, objective_value


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
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-log", default=str(DEFAULT_ACCEPTED_LOG))
    parser.add_argument("--runtime-source", default="data/colleague_default_synth_100x100")
    parser.add_argument("--plan-path", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--a-count", type=int, default=10)
    parser.add_argument("--b-count", type=int, default=10)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--max-iterations", type=int, default=80)
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--max-initial-patterns", type=int, default=60)
    parser.add_argument("--trace-path", action="append", default=[])
    parser.add_argument("--separation-time-limit-seconds", type=float, default=180.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.02)
    parser.add_argument("--pool-patterns-per-iteration", type=int, default=1)
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument("--lp-gurobi-params-json", default="")
    parser.add_argument("--separation-gurobi-params-json", default="")
    args = parser.parse_args()

    accepted = _read_accepted_config(Path(args.accepted_log))
    selection = build_runtime_selection(
        scenarios_a=range(1, int(args.a_count) + 1),
        scenarios_b=range(1, int(args.b_count) + 1),
        source="alpha_lambda_repair_probe",
    )
    instance = load_canonical_instance(
        args.runtime_source,
        critical_buses=load_critical_buses(CRITICAL_BUSES),
        selection=selection,
    )
    overrides = dict(accepted.get("parameter_overrides", {}))
    ambiguity = dict(overrides.get("ambiguity", {}))
    ambiguity["k_max_outages"] = int(args.k)
    overrides["ambiguity"] = ambiguity
    instance = apply_parameter_overrides(instance, overrides)
    plan = _load_plan(instance, Path(args.plan_path))
    scenario_ids = tuple(instance.sets.loaded_disaster_scenarios)
    fp_by_line_id = {
        line_id: float(instance.ambiguity.p_bar[index])
        for index, line_id in enumerate(instance.sets.line_ids)
    }
    omega_bounds = {line_id: (0.0, float(args.omega_bound_upper)) for line_id in instance.sets.line_ids}

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    trace_paths = [Path(path) for path in args.trace_path]
    active_patterns = _load_trace_patterns(trace_paths, max_patterns=int(args.max_initial_patterns))
    if not active_patterns:
        active_patterns = [tuple()]

    value_by_pattern_key: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    pattern_rows: list[dict[str, Any]] = []
    stop_reason = "max_iterations"
    sep_params = _parse_params(args.separation_gurobi_params_json)
    lp_params = _parse_params(args.lp_gurobi_params_json)

    for iteration_id in range(int(args.max_iterations)):
        eval_start = perf_counter()
        for pattern in active_patterns:
            key = _pattern_key(pattern)
            if key in value_by_pattern_key:
                continue
            value = _evaluate_pattern_value(
                instance,
                plan=plan,
                pattern=pattern,
                scenario_ids=scenario_ids,
                model_name_prefix=f"repair_iter{iteration_id:03d}",
            )
            value_by_pattern_key[key] = value
            pattern_rows.append(
                {
                    "pattern_key": key,
                    "active_count": len(pattern),
                    "recourse_value": value,
                    "first_seen_iteration": iteration_id,
                }
            )
        eval_seconds = perf_counter() - eval_start

        lp_start = perf_counter()
        alpha, lambda_by_line_id, support_objective = _solve_alpha_lambda_lp(
            line_ids=instance.sets.line_ids,
            fp_by_line_id=fp_by_line_id,
            alpha_min=float(instance.economics.alpha_min),
            value_by_pattern_key=value_by_pattern_key,
            gurobi_params=lp_params,
        )
        lp_seconds = perf_counter() - lp_start

        sep_start = perf_counter()
        separation_model, separation_solution = solve_separation_milp(
            instance,
            plan=plan,
            alpha=alpha,
            lambda_by_line_id=lambda_by_line_id,
            omega_bounds_by_line_id=omega_bounds,
            budget_k=int(args.k),
            scenario_ids=scenario_ids,
            model_name=f"alpha_lambda_repair_separation_{iteration_id:03d}",
            time_limit_seconds=float(args.separation_time_limit_seconds),
            mip_gap=float(args.separation_mip_gap),
            gurobi_params=sep_params,
            require_optimal=False,
            log_to_console=False,
        )
        sep_seconds = perf_counter() - sep_start
        violation = max(0.0, float(separation_solution.objective_value or 0.0))
        selected = tuple(
            sorted(
                line_id
                for line_id, active in separation_solution.delta_by_line_id.items()
                if int(active) == 1
            )
        )
        selected_key = _pattern_key(selected)
        pool_patterns = [selected]
        if (
            separation_solution.model_status == "OPTIMAL"
            and int(args.pool_patterns_per_iteration) > 1
        ):
            for pool_solution in extract_separation_milp_solution_pool(
                separation_model,
                max_solutions=int(args.pool_patterns_per_iteration),
                min_objective=float(args.epsilon_cert),
                unique_outage_patterns=True,
            ):
                pool_pattern = tuple(
                    sorted(
                        line_id
                        for line_id, active in pool_solution.delta_by_line_id.items()
                        if int(active) == 1
                    )
                )
                if pool_pattern not in pool_patterns:
                    pool_patterns.append(pool_pattern)
        new_pool_patterns = [
            pattern for pattern in pool_patterns if _pattern_key(pattern) not in value_by_pattern_key
        ]
        rows.append(
            {
                "iteration": iteration_id,
                "pattern_count": len(value_by_pattern_key),
                "alpha": alpha,
                "lambda_fp": sum(fp_by_line_id[line_id] * lambda_by_line_id[line_id] for line_id in instance.sets.line_ids),
                "support_objective": support_objective,
                "separation_violation": violation,
                "separation_status": separation_solution.model_status,
                "separation_mip_gap": separation_solution.mip_gap,
                "separation_obj_bound": separation_solution.obj_bound,
                "separation_node_count": separation_solution.node_count,
                "selected_pattern_key": selected_key,
                "selected_active_count": len(selected),
                "pool_pattern_count": len(pool_patterns),
                "new_pool_pattern_count": len(new_pool_patterns),
                "eval_seconds": eval_seconds,
                "lp_seconds": lp_seconds,
                "separation_seconds": sep_seconds,
            }
        )
        _write_rows(output_root / "alpha_lambda_repair_trace.csv", rows)
        _write_rows(output_root / "alpha_lambda_repair_patterns.csv", pattern_rows)
        if (
            separation_solution.model_status == "OPTIMAL"
            and violation <= float(args.epsilon_cert)
        ):
            stop_reason = "certified_fixed_plan_alpha_lambda"
            break
        if new_pool_patterns:
            active_patterns = new_pool_patterns
        else:
            # Repeated pattern with positive violation means the separation model and
            # primal pattern evaluator disagree; record and stop instead of looping.
            stop_reason = "repeated_selected_pattern_positive_violation"
            break

    report = {
        "stop_reason": stop_reason,
        "iterations": len(rows),
        "best_violation": min((row["separation_violation"] for row in rows), default=None),
        "last_violation": rows[-1]["separation_violation"] if rows else None,
        "plan_path": str(args.plan_path),
        "runtime_source": str(args.runtime_source),
        "K": int(args.k),
        "note": (
            "Fixed-plan alpha/lambda repair is diagnostic unless paired with a "
            "valid full master lower-bound argument."
        ),
    }
    (output_root / "alpha_lambda_repair_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
