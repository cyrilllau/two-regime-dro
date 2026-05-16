"""Run a diagnostic node-closed hybrid value BPC root-closure probe.

This implements the first phase of the Pro note
`evcs_dro_k16_node_closed_hybrid_bpc_next_step.tex`.

It is an engineering diagnostic only. It never writes to `results/paper_final`
and it never labels rows as paper-facing certified unless the existing
canonical certificate rule is actually met by a valid full-support closure.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from gurobipy import GRB, quicksum


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import (  # noqa: E402
    _load_initial_cuts_from_pools,
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from scripts.run_full_benders_scalability import CRITICAL_BUSES  # noqa: E402
from scripts.run_incumbent_guarded_closure import (  # noqa: E402
    DEFAULT_K16_RUN_LOG,
    _active_outage_lines,
    _add_distributional_value_cut_to_master,
    _build_distributional_value_cut,
    _full_support_pricing,
    _line_fp_by_id,
    _outage_column_id,
    _parse_int_list,
    _repo_path,
    _status_name,
    _trial_plan,
)
from src.production.cut_factory import (  # noqa: E402
    compute_cut_signature_hash,
    generate_structured_cut,
)
from src.production.master_problem import (  # noqa: E402
    RestrictedMasterCut,
    RestrictedMasterOutageColumnCut,
    build_master_problem,
)
from src.reference.disaster_primal_ref import (  # noqa: E402
    FixedFirstStagePlan,
    build_fixed_outage_vector,
)


DEFAULT_OUTPUT_ROOT = (
    REPO_ROOT / "results/engineering_acceleration/k16_node_closed_hybrid_bpc_probe_20260509"
)


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with file_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _append_jsonl(path: str | Path, payload: Mapping[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")


def _parse_fixings(raw: str) -> dict[int, float]:
    fixings: dict[int, float] = {}
    if not str(raw).strip():
        return fixings
    for item in str(raw).split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise ValueError(f"Invalid fixing {item!r}; expected BUS=VALUE.")
        left, right = item.split("=", 1)
        fixings[int(left.strip())] = float(right.strip())
    return fixings


def _apply_node_fixings(master, *, z_fix: Mapping[int, float], sl_fix: Mapping[int, float], fa_fix: Mapping[int, float]) -> None:
    for bus, value in z_fix.items():
        master.model.addConstr(
            master.first_stage.z_by_bus[int(bus)] == float(value),
            name=f"node_fix_z_{int(bus)}",
        )
    for bus, value in sl_fix.items():
        master.model.addConstr(
            master.first_stage.n_sl_by_bus[int(bus)] == float(value),
            name=f"node_fix_n_sl_{int(bus)}",
        )
    for bus, value in fa_fix.items():
        master.model.addConstr(
            master.first_stage.n_fa_by_bus[int(bus)] == float(value),
            name=f"node_fix_n_fa_{int(bus)}",
        )


def _enable_explicit_eta_value_master(master):
    """Use an explicit disaster-value epigraph eta for diagnostic MAMVC probes.

    The production master minimizes pi_f * (alpha + FP lambda) directly.  For the
    Pro-recommended MAMVC diagnostic, we introduce eta >= alpha + FP lambda and
    minimize pi_f * eta so distributional value cuts can target eta without
    forcing alpha/lambda themselves.  This is an optional diagnostic reformulation
    and is not enabled by default.
    """

    eta_var = master.model.addVar(lb=0.0, name="eta_disaster_value")
    alpha_lambda_expr = master.alpha_var + quicksum(
        float(master.fp_by_line_id[line_id]) * master.lambda_by_line_id[line_id]
        for line_id in master.ordered_line_ids
    )
    master.model.addConstr(
        eta_var >= alpha_lambda_expr,
        name="eta_alpha_lambda_epigraph",
    )
    multipliers = master.instance.economics.objective_multipliers
    disaster_expression = float(master.instance.economics.pi_f) * eta_var
    total_expression = (
        float(multipliers.cons) * master.construction_cost_expression
        + float(multipliers.normal) * master.averaged_normal_cost_expression
        + float(multipliers.disaster) * disaster_expression
    )
    master.model.setObjective(total_expression, GRB.MINIMIZE)
    return eta_var


def _add_distributional_value_cut_to_eta_master(master, value_cut: Mapping[str, Any], eta_var) -> Any:
    cut_id = str(value_cut["cut_id"])
    gamma_z = {int(bus): float(value) for bus, value in dict(value_cut["gamma_z_by_bus"]).items()}
    gamma_sl = {
        int(bus): float(value)
        for bus, value in dict(value_cut["gamma_n_sl_by_bus"]).items()
    }
    gamma_fa = {
        int(bus): float(value)
        for bus, value in dict(value_cut["gamma_n_fa_by_bus"]).items()
    }
    gamma_expr = quicksum(
        gamma_z[bus] * master.first_stage.z_by_bus[bus]
        + gamma_sl[bus] * master.first_stage.n_sl_by_bus[bus]
        + gamma_fa[bus] * master.first_stage.n_fa_by_bus[bus]
        for bus in master.ordered_buses
    )
    return master.model.addConstr(
        eta_var >= float(value_cut["beta"]) - gamma_expr,
        name=f"mamvc_eta_value_cut_{cut_id}",
    )


def _load_instance_and_pool(args: argparse.Namespace):
    run_log = _read_json(args.run_log)
    run_config = dict(run_log["run_config"])
    base_instance = load_instance_for_run(
        run_config,
        critical_buses=load_critical_buses(CRITICAL_BUSES),
    )
    instance = prepare_instance_for_run(base_instance, run_config)
    cut_pool_path = _repo_path(dict(run_log.get("artifact_paths", {})).get("cut_pool_path"))
    if cut_pool_path is None or not cut_pool_path.exists():
        raise RuntimeError("K16 run log does not contain a readable cut-pool path.")
    cert_path = _repo_path(dict(run_log.get("artifact_paths", {})).get("trial_certificate_path"))
    if cert_path is None or not cert_path.exists():
        raise RuntimeError("K16 run log does not contain a readable trial-certificate path.")
    trial_certificate = _read_json(cert_path)
    trial_plan = _trial_plan(trial_certificate)

    initial_pool_paths = [str(cut_pool_path)]
    for raw in str(args.extra_initial_cut_pool_paths).split(","):
        if raw.strip():
            initial_pool_paths.append(raw.strip())
    loaded_cuts: list[RestrictedMasterCut] = []
    loaded_rows: list[RestrictedMasterOutageColumnCut] = []
    audit_rows: list[dict[str, Any]] = []
    for pool_index, pool_path in enumerate(initial_pool_paths, start=1):
        cuts, rows, audit = _load_initial_cuts_from_pools(
            instance,
            run_config,
            {"initial_cut_pool_path": pool_path},
        )
        loaded_cuts.extend(cuts)
        loaded_rows.extend(rows)
        for row in audit:
            audit_rows.append({"pool_index": pool_index, **row})
    return run_log, run_config, instance, trial_plan, loaded_cuts, loaded_rows, audit_rows


def _relaxed_root_solution(master, *, time_limit_seconds: float, log_to_console: bool) -> dict[str, Any]:
    relaxed = master.model.relax()
    relaxed.Params.OutputFlag = 1 if log_to_console else 0
    relaxed.Params.TimeLimit = float(time_limit_seconds)
    relaxed.optimize()
    status = _status_name(int(relaxed.Status))
    if int(relaxed.SolCount) <= 0:
        return {
            "status": status,
            "sol_count": int(relaxed.SolCount),
            "objective": None,
            "obj_bound": None,
            "runtime_seconds": float(relaxed.Runtime),
            "plan": None,
            "alpha": None,
            "lambda_by_line_id": {},
        }
    by_name = {var.VarName: var for var in relaxed.getVars()}

    def value(name: str) -> float:
        var = by_name.get(name)
        if var is None:
            raise RuntimeError(f"Relaxed root model missing variable {name!r}.")
        return float(var.X)

    plan = FixedFirstStagePlan(
        z_by_bus={
            int(bus): value(master.first_stage.z_by_bus[bus].VarName)
            for bus in master.ordered_buses
        },
        n_sl_by_bus={
            int(bus): value(master.first_stage.n_sl_by_bus[bus].VarName)
            for bus in master.ordered_buses
        },
        n_fa_by_bus={
            int(bus): value(master.first_stage.n_fa_by_bus[bus].VarName)
            for bus in master.ordered_buses
        },
    )
    return {
        "status": status,
        "sol_count": int(relaxed.SolCount),
        "objective": float(relaxed.ObjVal),
        "obj_bound": None if not hasattr(relaxed, "ObjBound") else float(relaxed.ObjBound),
        "runtime_seconds": float(relaxed.Runtime),
        "plan": plan,
        "alpha": value(master.alpha_var.VarName),
        "eta": (
            value("eta_disaster_value")
            if "eta_disaster_value" in by_name
            else None
        ),
        "lambda_by_line_id": {
            str(line_id): max(0.0, value(var.VarName))
            for line_id, var in master.lambda_by_line_id.items()
        },
    }


def _add_priced_cut(
    instance,
    *,
    source_plan: FixedFirstStagePlan,
    alpha_value: float,
    lambda_by_line_id: Mapping[str, float],
    separation_solution,
    cut_index: int,
) -> tuple[RestrictedMasterCut, RestrictedMasterOutageColumnCut, str, tuple[str, ...]]:
    active_lines = tuple(_active_outage_lines(separation_solution.delta_by_line_id))
    outage = build_fixed_outage_vector(
        instance,
        by_line_id=separation_solution.delta_by_line_id,
    )
    generated = generate_structured_cut(
        instance,
        plan=source_plan,
        outage=outage,
        scenario_ids=instance.sets.loaded_disaster_scenarios,
        cut_id=f"node_closed_hybrid_cut_{cut_index:06d}",
        provenance=f"node_closed_hybrid_root_{cut_index:06d}",
        source_alpha=float(alpha_value),
        source_lambda_by_line_id=lambda_by_line_id,
        source_violation_value=separation_solution.objective_value,
        canonicalize_degenerate_dual=True,
        allow_fractional_plan=True,
        log_to_console=False,
    )
    signature = compute_cut_signature_hash(generated.cut)
    row = RestrictedMasterOutageColumnCut(
        row_id=f"node_closed_hybrid_row_{cut_index:06d}_{_outage_column_id(active_lines)}",
        column_id=_outage_column_id(active_lines),
        active_line_ids=active_lines,
        cut=generated.cut,
    )
    return generated.cut, row, signature, active_lines


def run(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    event_path = output_root / "node_closed_hybrid_events.jsonl"
    run_log, run_config, instance, trial_plan, loaded_cuts, loaded_rows, audit_rows = (
        _load_instance_and_pool(args)
    )
    current_cuts: list[RestrictedMasterCut] = list(loaded_cuts)
    current_rows: list[RestrictedMasterOutageColumnCut] = list(loaded_rows)
    value_cuts: list[dict[str, Any]] = []
    global_signatures = {compute_cut_signature_hash(cut) for cut in current_cuts}
    row_keys = {
        (tuple(row.active_line_ids), compute_cut_signature_hash(row.cut))
        for row in current_rows
    }
    value_signatures: set[str] = set()
    trace_rows: list[dict[str, Any]] = []
    value_distribution_rows: list[dict[str, Any]] = []
    z_fix = _parse_fixings(args.fix_z)
    sl_fix = _parse_fixings(args.fix_sl)
    fa_fix = _parse_fixings(args.fix_fa)
    pricing_upper_bound = float(args.pricing_upper_bound)
    epsilon_gap = float(args.epsilon_gap)
    target_tau = pricing_upper_bound - epsilon_gap
    best_root_lp = None
    closure_status = "not_started"

    _write_csv(output_root / "cut_pool_audit.csv", audit_rows)

    for iteration in range(1, int(args.max_root_closure_rounds) + 1):
        master = build_master_problem(
            instance,
            cuts=current_cuts,
            outage_column_cuts=current_rows,
            warm_start_plan=trial_plan,
            model_name=f"node_closed_hybrid_root_{iteration:03d}",
            log_to_console=bool(args.log_to_console),
        )
        _apply_node_fixings(master, z_fix=z_fix, sl_fix=sl_fix, fa_fix=fa_fix)
        eta_var = (
            _enable_explicit_eta_value_master(master)
            if bool(args.explicit_eta_value_master)
            else None
        )
        for value_cut in value_cuts:
            if eta_var is None:
                _add_distributional_value_cut_to_master(master, value_cut)
            else:
                _add_distributional_value_cut_to_eta_master(master, value_cut, eta_var)
        master.model.update()
        root = _relaxed_root_solution(
            master,
            time_limit_seconds=float(args.root_lp_time_limit_seconds),
            log_to_console=bool(args.log_to_console),
        )
        if root["objective"] is None or root["plan"] is None:
            closure_status = "root_lp_unusable"
            trace_rows.append(
                {
                    "iteration": iteration,
                    "event": "root_lp_unusable",
                    "root_status": root["status"],
                    "root_runtime_seconds": root["runtime_seconds"],
                }
            )
            break
        best_root_lp = (
            float(root["objective"])
            if best_root_lp is None
            else max(float(best_root_lp), float(root["objective"]))
        )
        pricing_solutions = []
        forbidden_patterns: list[tuple[str, ...]] = []
        for pricing_rank in range(1, int(args.pricing_captures_per_round) + 1):
            _, pricing_solution = _full_support_pricing(
                instance,
                plan=root["plan"],
                solution=SimpleNamespace(
                    alpha_value=float(root["alpha"]),
                    lambda_by_line_id=dict(root["lambda_by_line_id"]),
                ),
                forbidden_outage_patterns=forbidden_patterns,
                omega_bound_upper=float(args.omega_bound_upper),
                time_limit_seconds=float(args.pricing_time_limit_seconds),
                mip_gap=float(args.pricing_mip_gap),
                model_name=f"node_closed_hybrid_root_pricing_{iteration:03d}_{pricing_rank:02d}",
                log_to_console=bool(args.log_to_console),
            )
            pricing_solutions.append(pricing_solution)
            if pricing_solution.objective_value is None:
                break
            active_lines_rank = tuple(_active_outage_lines(pricing_solution.delta_by_line_id))
            if active_lines_rank in forbidden_patterns:
                break
            forbidden_patterns.append(active_lines_rank)
        primary_pricing = pricing_solutions[0] if pricing_solutions else None
        violation_value = (
            None
            if primary_pricing is None or primary_pricing.objective_value is None
            else float(primary_pricing.objective_value)
        )
        violation_bound = (
            None
            if primary_pricing is None or primary_pricing.obj_bound is None
            else float(primary_pricing.obj_bound)
        )
        active_lines = (
            tuple()
            if primary_pricing is None
            else tuple(_active_outage_lines(primary_pricing.delta_by_line_id))
        )
        captured_violation_bounds = [
            None if sol.obj_bound is None else float(sol.obj_bound)
            for sol in pricing_solutions
        ]
        captured_active_patterns = [
            ";".join(_active_outage_lines(sol.delta_by_line_id))
            for sol in pricing_solutions
        ]
        row = {
            "iteration": iteration,
            "root_status": root["status"],
            "root_objective": root["objective"],
            "root_eta_value": "" if root.get("eta") is None else root.get("eta"),
            "best_root_lp": best_root_lp,
            "target_tau": target_tau,
            "target_gap_from_root": target_tau - float(best_root_lp),
            "root_runtime_seconds": root["runtime_seconds"],
            "pricing_status": "" if primary_pricing is None else primary_pricing.model_status,
            "pricing_violation_value": violation_value,
            "pricing_violation_bound": violation_bound,
            "pricing_mip_gap": "" if primary_pricing is None else primary_pricing.mip_gap,
            "pricing_runtime_seconds": sum(float(sol.runtime_seconds or 0.0) for sol in pricing_solutions),
            "pricing_node_count": sum(float(sol.node_count or 0.0) for sol in pricing_solutions),
            "pricing_capture_count": len(pricing_solutions),
            "pricing_captured_violation_bounds": ";".join(
                "" if value is None else str(value) for value in captured_violation_bounds
            ),
            "pricing_captured_active_patterns": " | ".join(captured_active_patterns),
            "active_line_count": len(active_lines),
            "active_lines": ";".join(active_lines),
            "global_cut_count_before": len(current_cuts),
            "rowwise_cut_count_before": len(current_rows),
            "value_cut_count_before": len(value_cuts),
        }
        if violation_bound is not None and violation_bound <= float(args.node_pricing_tolerance):
            closure_status = "root_pricing_closed"
            row["event"] = "root_pricing_closed"
            trace_rows.append(row)
            _append_jsonl(event_path, row)
            break
        if primary_pricing is None or primary_pricing.objective_value is None:
            closure_status = "pricing_no_solution"
            row["event"] = "pricing_no_solution"
            trace_rows.append(row)
            _append_jsonl(event_path, row)
            break

        added_global_count = 0
        added_rowwise_count = 0
        for rank, priced_solution in enumerate(pricing_solutions, start=1):
            if priced_solution.objective_value is None:
                continue
            cut, outage_row, signature, _active_lines = _add_priced_cut(
                instance,
                source_plan=root["plan"],
                alpha_value=float(root["alpha"]),
                lambda_by_line_id=dict(root["lambda_by_line_id"]),
                separation_solution=priced_solution,
                cut_index=iteration * 100 + rank,
            )
            if signature not in global_signatures:
                current_cuts.append(cut)
                global_signatures.add(signature)
                added_global_count += 1
            row_key = (tuple(outage_row.active_line_ids), signature)
            if row_key not in row_keys:
                current_rows.append(outage_row)
                row_keys.add(row_key)
                added_rowwise_count += 1

        value_cut = None
        if bool(args.add_value_cuts):
            value_cut = _build_distributional_value_cut(
                instance,
                source_plan=root["plan"],
                outage_column_cuts=current_rows,
                cut_id=f"node_closed_hybrid_value_{iteration:06d}",
                max_columns=int(args.value_cut_max_columns),
                subset_sizes=_parse_int_list(args.value_cut_subset_sizes),
                pricing_rounds=int(args.value_cut_pricing_rounds),
                pricing_time_limit_seconds=float(args.pricing_time_limit_seconds),
                pricing_mip_gap=float(args.pricing_mip_gap),
                omega_bound_upper=float(args.omega_bound_upper),
                log_to_console=bool(args.log_to_console),
                recompute_source_duals=False,
            )
        added_value_cut = False
        if value_cut is not None and bool(value_cut.get("accepted")):
            signature_value = str(value_cut.get("signature") or "")
            if not signature_value:
                payload = {
                    "beta": value_cut.get("beta"),
                    "gamma_z_by_bus": value_cut.get("gamma_z_by_bus"),
                    "gamma_n_sl_by_bus": value_cut.get("gamma_n_sl_by_bus"),
                    "gamma_n_fa_by_bus": value_cut.get("gamma_n_fa_by_bus"),
                }
                signature_value = json.dumps(payload, sort_keys=True)
            if signature_value not in value_signatures:
                value_cuts.append(value_cut)
                value_signatures.add(signature_value)
                added_value_cut = True
                for dist_row in value_cut.get("distribution_rows", []):
                    value_distribution_rows.append({"iteration": iteration, **dist_row})

        row.update(
            {
                "event": "added_pricing_rows",
                "added_global": added_global_count > 0,
                "added_global_count": added_global_count,
                "added_rowwise": added_rowwise_count > 0,
                "added_rowwise_count": added_rowwise_count,
                "added_value_cut": added_value_cut,
                "value_cut_objective": (
                    "" if value_cut is None else value_cut.get("objective_value", "")
                ),
                "value_cut_real_mass": (
                    "" if value_cut is None else value_cut.get("real_column_mass", "")
                ),
                "value_cut_positive_columns": (
                    "" if value_cut is None else value_cut.get("positive_column_count", "")
                ),
                "global_cut_count_after": len(current_cuts),
                "rowwise_cut_count_after": len(current_rows),
                "value_cut_count_after": len(value_cuts),
            }
        )
        trace_rows.append(row)
        _append_jsonl(event_path, row)
        _write_csv(output_root / "node_closed_root_trace.csv", trace_rows)
        _write_csv(output_root / "value_cut_distribution_rows.csv", value_distribution_rows)
        if not (added_global_count or added_rowwise_count or added_value_cut):
            closure_status = "duplicate_no_progress"
            break
        closure_status = "root_closure_budget_exhausted"

    _write_csv(output_root / "node_closed_root_trace.csv", trace_rows)
    _write_csv(output_root / "value_cut_distribution_rows.csv", value_distribution_rows)
    summary = {
        "validation_level": "node_closed_hybrid_root_diagnostic",
        "paper_facing_eligible": False,
        "closure_status": closure_status,
        "pro_response_tex": "/Users/shixinliu/Downloads/evcs_dro_k16_node_closed_hybrid_bpc_next_step.tex",
        "source_run_log": str(Path(args.run_log)),
        "pricing_upper_bound": pricing_upper_bound,
        "epsilon_gap": epsilon_gap,
        "target_tau": target_tau,
        "best_root_lp": best_root_lp,
        "target_gap_from_root": None if best_root_lp is None else target_tau - float(best_root_lp),
        "root_rounds_completed": len(trace_rows),
        "global_cut_count": len(current_cuts),
        "rowwise_cut_count": len(current_rows),
        "value_cut_count": len(value_cuts),
        "explicit_eta_value_master": bool(args.explicit_eta_value_master),
        "node_fix_z": {str(k): v for k, v in z_fix.items()},
        "node_fix_sl": {str(k): v for k, v in sl_fix.items()},
        "node_fix_fa": {str(k): v for k, v in fa_fix.items()},
        "trace_path": str(output_root / "node_closed_root_trace.csv"),
        "event_path": str(event_path),
        "certificate_rule": (
            "Diagnostic only. Paper-facing certification still requires UB - canonical/custom-tree "
            "LB <= epsilon_gap or full target-tree infeasibility with full-support pricing."
        ),
    }
    _write_json(output_root / "node_closed_hybrid_summary.json", summary)
    _write_json(
        output_root / "node_closed_value_cut_pool.json",
        {
            "value_cuts": value_cuts,
            "metadata": {
                "source_run_log": str(Path(args.run_log)),
                "pricing_upper_bound": pricing_upper_bound,
                "epsilon_gap": epsilon_gap,
                "target_tau": target_tau,
                "line_fp_by_id": _line_fp_by_id(instance),
            },
        },
    )
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-log", default=str(DEFAULT_K16_RUN_LOG))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--extra-initial-cut-pool-paths", default="")
    parser.add_argument("--pricing-upper-bound", type=float, default=49981.0288376632)
    parser.add_argument("--epsilon-gap", type=float, default=100.0)
    parser.add_argument("--max-root-closure-rounds", type=int, default=20)
    parser.add_argument("--root-lp-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--node-pricing-tolerance", type=float, default=500.0)
    parser.add_argument("--pricing-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--pricing-mip-gap", type=float, default=0.02)
    parser.add_argument("--pricing-captures-per-round", type=int, default=1)
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument("--fix-z", default="", help="Comma-separated node fixings, e.g. 30=1.")
    parser.add_argument("--fix-sl", default="", help="Comma-separated slow-EVSE node fixings.")
    parser.add_argument("--fix-fa", default="", help="Comma-separated fast-EVSE node fixings.")
    parser.add_argument("--add-value-cuts", action="store_true")
    parser.add_argument(
        "--explicit-eta-value-master",
        action="store_true",
        help=(
            "Diagnostic-only MAMVC mode: minimize pi_f*eta with eta >= alpha+FP lambda "
            "and put distributional value cuts on eta."
        ),
    )
    parser.add_argument("--value-cut-max-columns", type=int, default=600)
    parser.add_argument("--value-cut-subset-sizes", default="1,2,4,8,16")
    parser.add_argument("--value-cut-pricing-rounds", type=int, default=0)
    parser.add_argument("--log-to-console", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
