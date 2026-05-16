"""Prototype hybrid value-master BPC cuts for K=16 certificate closure.

This script implements the first, low-scope prototype from the Pro note
`evcs_dro_k16_value_master_bpc_next_step.tex`.

It does not promote anything to `paper_final`.  It reads a persisted K=16
row-wise NCCG cut pool, aggregates dual-feasible fixed-outage affine rows into
distributional value cuts, and solves a canonical value-master relaxation using
those cuts as `eta >= a - g*x` lower supports.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from gurobipy import GRB, Model, quicksum


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
from src.production.cut_factory import compute_cut_signature_hash  # noqa: E402
from src.production.cut_factory import generate_structured_cut  # noqa: E402
from src.production.master_problem import (  # noqa: E402
    RestrictedMasterCut,
    RestrictedMasterOutageColumnCut,
    RestrictedMasterProblemSolution,
    build_master_problem,
    extract_master_problem_solution,
)
from src.reference.disaster_primal_ref import (  # noqa: E402
    FixedFirstStagePlan,
    build_fixed_outage_vector,
)


DEFAULT_K16_RUN_LOG = (
    REPO_ROOT
    / "results/engineering_acceleration/k16_certificate_closure_120_20260506/runs/"
    "eng_active_set_localbranchzn_A10_B010_K16_top001_max120_pool100_cand20_cuts03_"
    "levelbundle_s5000p0_f0p05_rl1p0_bestviolation_nccg_global_complete05_oldest_"
    "pfpb01_r00_cb10_tol0p0_cs_k0p35_ev0p15_n03/logs/"
    "eng_active_set_localbranchzn_A10_B010_K16_top001_max120_pool100_cand20_cuts03_"
    "levelbundle_s5000p0_f0p05_rl1p0_bestviolation_nccg_global_complete05_oldest_"
    "pfpb01_r00_cb10_tol0p0_cs_k0p35_ev0p15_n03_run.json"
)
DEFAULT_OUTPUT_DIR = REPO_ROOT / "results/engineering_acceleration/k16_value_master_bpc_proto1"
PRIOR_K16_LB = 48369.96694884317
BEST_K16_UB = 50256.86816363342
EPS_GAP_TARGET = 100.0


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


def _repo_path(raw: str | Path | None) -> Path | None:
    if raw in (None, ""):
        return None
    path = Path(str(raw))
    return path if path.is_absolute() else REPO_ROOT / path


def _trial_plan_from_certificate(certificate: Mapping[str, Any]) -> FixedFirstStagePlan:
    first_stage = dict(certificate.get("first_stage_plan", {}))
    return FixedFirstStagePlan(
        z_by_bus={
            int(bus): int(value)
            for bus, value in dict(first_stage.get("z_by_bus", {})).items()
        },
        n_sl_by_bus={
            int(bus): int(value)
            for bus, value in dict(first_stage.get("n_sl_by_bus", {})).items()
        },
        n_fa_by_bus={
            int(bus): int(value)
            for bus, value in dict(first_stage.get("n_fa_by_bus", {})).items()
        },
    )


def _plan_from_master_solution(solution: RestrictedMasterProblemSolution) -> FixedFirstStagePlan:
    first_stage = solution.first_stage_solution
    return FixedFirstStagePlan(
        z_by_bus={int(bus): int(value) for bus, value in first_stage.z_by_bus.items()},
        n_sl_by_bus={
            int(bus): int(value) for bus, value in first_stage.n_sl_by_bus.items()
        },
        n_fa_by_bus={
            int(bus): int(value) for bus, value in first_stage.n_fa_by_bus.items()
        },
    )


def _plan_from_relaxed_model(master, relaxed_model) -> FixedFirstStagePlan:
    """Extract a fractional first-stage point from a relaxed master model."""

    by_name = {var.VarName: var for var in relaxed_model.getVars()}

    def value(name: str) -> float:
        var = by_name.get(name)
        if var is None:
            raise RuntimeError(f"Relaxed model is missing expected variable {name!r}.")
        return float(var.X)

    return FixedFirstStagePlan(
        z_by_bus={int(bus): value(master.first_stage.z_by_bus[bus].VarName) for bus in master.ordered_buses},
        n_sl_by_bus={
            int(bus): value(master.first_stage.n_sl_by_bus[bus].VarName)
            for bus in master.ordered_buses
        },
        n_fa_by_bus={
            int(bus): value(master.first_stage.n_fa_by_bus[bus].VarName)
            for bus in master.ordered_buses
        },
    )


def _cut_gamma_value(cut: RestrictedMasterCut, plan: FixedFirstStagePlan) -> float:
    return sum(
        float(cut.gamma_z_by_bus.get(bus, 0.0)) * float(plan.z_by_bus.get(bus, 0.0))
        + float(cut.gamma_n_sl_by_bus.get(bus, 0.0))
        * float(plan.n_sl_by_bus.get(bus, 0.0))
        + float(cut.gamma_n_fa_by_bus.get(bus, 0.0))
        * float(plan.n_fa_by_bus.get(bus, 0.0))
        for bus in plan.z_by_bus
    )


def _phi_delta(cut: RestrictedMasterCut, active_line_ids: Sequence[str]) -> float:
    return sum(float(cut.phi_by_line_id.get(line_id, 0.0)) for line_id in active_line_ids)


def _row_value_at_plan(row: RestrictedMasterOutageColumnCut, plan: FixedFirstStagePlan) -> float:
    cut = row.cut
    return float(cut.beta) - _cut_gamma_value(cut, plan) + _phi_delta(
        cut,
        row.active_line_ids,
    )


def _best_rows_by_column(
    rows: Sequence[RestrictedMasterOutageColumnCut],
    *,
    plan: FixedFirstStagePlan,
    max_columns: int,
) -> list[tuple[RestrictedMasterOutageColumnCut, float]]:
    best_by_pattern: dict[tuple[str, ...], tuple[RestrictedMasterOutageColumnCut, float]] = {}
    for row in rows:
        pattern = tuple(row.active_line_ids)
        value = _row_value_at_plan(row, plan)
        incumbent = best_by_pattern.get(pattern)
        if incumbent is None or value > incumbent[1]:
            best_by_pattern[pattern] = (row, value)
    ranked = sorted(best_by_pattern.values(), key=lambda item: item[1], reverse=True)
    if max_columns > 0:
        return ranked[:max_columns]
    return ranked


def _build_zero_outage_row(
    instance,
    *,
    plan: FixedFirstStagePlan,
    allow_fractional_plan: bool = False,
    log_to_console: bool,
) -> RestrictedMasterOutageColumnCut:
    outage = build_fixed_outage_vector(
        instance,
        by_line_id={},
    )
    result = generate_structured_cut(
        instance,
        plan=plan,
        outage=outage,
        scenario_ids=instance.sets.loaded_disaster_scenarios,
        cut_id="value_seed_zero_outage_cut",
        provenance="value_master_bpc_zero_outage_seed",
        canonicalize_degenerate_dual=True,
        allow_fractional_plan=allow_fractional_plan,
        log_to_console=log_to_console,
    )
    return RestrictedMasterOutageColumnCut(
        row_id="value_seed_zero_outage_row",
        column_id="delta_zero_outage",
        active_line_ids=tuple(),
        cut=result.cut,
    )


def _generate_fresh_rows_for_patterns(
    instance,
    *,
    plan: FixedFirstStagePlan,
    pattern_rows: Sequence[RestrictedMasterOutageColumnCut],
    loop_index: int,
    allow_fractional_plan: bool,
    log_to_console: bool,
) -> list[tuple[RestrictedMasterOutageColumnCut, float]]:
    """Generate source-tight fixed-outage dual rows for selected outage patterns."""

    fresh_rows: list[tuple[RestrictedMasterOutageColumnCut, float]] = []
    seen_patterns: set[tuple[str, ...]] = set()
    for pattern_index, source_row in enumerate(pattern_rows, start=1):
        pattern = tuple(source_row.active_line_ids)
        if pattern in seen_patterns:
            continue
        seen_patterns.add(pattern)
        outage = build_fixed_outage_vector(
            instance,
            by_line_id={line_id: 1 for line_id in pattern},
        )
        cut_id = f"value_loop{loop_index:03d}_pattern{pattern_index:03d}_cut"
        result = generate_structured_cut(
            instance,
            plan=plan,
            outage=outage,
            scenario_ids=instance.sets.loaded_disaster_scenarios,
            cut_id=cut_id,
            provenance="value_master_bpc_loop_fresh_fixed_outage",
            canonicalize_degenerate_dual=True,
            allow_fractional_plan=allow_fractional_plan,
            log_to_console=log_to_console,
        )
        row = RestrictedMasterOutageColumnCut(
            row_id=f"value_loop{loop_index:03d}_pattern{pattern_index:03d}_row",
            column_id=source_row.column_id,
            active_line_ids=pattern,
            cut=result.cut,
        )
        fresh_rows.append((row, _row_value_at_plan(row, plan)))
    zero_row = _build_zero_outage_row(
        instance,
        plan=plan,
        allow_fractional_plan=allow_fractional_plan,
        log_to_console=log_to_console,
    )
    fresh_rows.append((zero_row, _row_value_at_plan(zero_row, plan)))
    return fresh_rows


def _solve_distribution_lp(
    *,
    line_ids: Sequence[str],
    fp_by_line_id: Mapping[str, float],
    candidates: Sequence[tuple[RestrictedMasterOutageColumnCut, float]],
    max_support: int,
    log_to_console: bool,
) -> tuple[list[tuple[float, RestrictedMasterOutageColumnCut, float]], dict[str, Any]]:
    """Solve restricted adversarial distribution LP over candidate outage columns."""

    model = Model("restricted_adversarial_distribution_lp")
    model.Params.OutputFlag = 1 if log_to_console else 0
    p_vars = {
        index: model.addVar(lb=0.0, name=f"p_{index:04d}")
        for index, _ in enumerate(candidates)
    }
    model.addConstr(
        quicksum(p_vars.values()) == 1.0,
        name="probability_sum",
    )
    for line_id in line_ids:
        model.addConstr(
            quicksum(
                p_vars[index]
                for index, (row, _) in enumerate(candidates)
                if line_id in set(row.active_line_ids)
            )
            <= float(fp_by_line_id[line_id]),
            name=f"moment_{line_id}",
        )
    model.setObjective(
        quicksum(p_vars[index] * float(value) for index, (_, value) in enumerate(candidates)),
        sense=GRB.MAXIMIZE,
    )
    model.optimize()
    if model.Status != GRB.OPTIMAL:
        raise RuntimeError(f"restricted distribution LP did not solve optimally: {model.Status}")
    positive = [
        (float(p_vars[index].X), row, float(value))
        for index, (row, value) in enumerate(candidates)
        if float(p_vars[index].X) > 1.0e-9
    ]
    positive.sort(key=lambda item: item[0], reverse=True)
    if max_support > 0 and len(positive) > max_support:
        # This should not normally be needed because the LP BFS is sparse.  If Gurobi returns
        # a dense convex combination, keep the largest terms only for a diagnostic cut and
        # renormalize conservatively by resolving is future work.
        positive = positive[:max_support]
    moment_usage = {
        line_id: sum(weight for weight, row, _ in positive if line_id in set(row.active_line_ids))
        for line_id in line_ids
    }
    info = {
        "status": "OPTIMAL",
        "objective": float(model.ObjVal),
        "p_zero": sum(
            float(p_vars[index].X)
            for index, (row, _) in enumerate(candidates)
            if len(row.active_line_ids) == 0
        ),
        "candidate_count": len(candidates),
        "positive_support_count": len(positive),
        "max_moment_violation": max(
            [moment_usage[line_id] - float(fp_by_line_id[line_id]) for line_id in line_ids]
            or [0.0]
        ),
    }
    return positive, info


def _aggregate_value_cut(
    *,
    line_ids: Sequence[str],
    buses: Sequence[int],
    positive_distribution: Sequence[tuple[float, RestrictedMasterOutageColumnCut, float]],
    cut_id: str,
) -> tuple[RestrictedMasterCut, list[dict[str, Any]], dict[str, Any]]:
    beta = 0.0
    gamma_z_by_bus = {int(bus): 0.0 for bus in buses}
    gamma_n_sl_by_bus = {int(bus): 0.0 for bus in buses}
    gamma_n_fa_by_bus = {int(bus): 0.0 for bus in buses}
    rows: list[dict[str, Any]] = []
    weighted_source_value = 0.0
    for support_index, (weight, row, value_at_source) in enumerate(
        positive_distribution,
        start=1,
    ):
        cut = row.cut
        phi_delta = _phi_delta(cut, row.active_line_ids)
        beta += float(weight) * (float(cut.beta) + phi_delta)
        weighted_source_value += float(weight) * float(value_at_source)
        for bus in buses:
            gamma_z_by_bus[int(bus)] += float(weight) * float(cut.gamma_z_by_bus.get(bus, 0.0))
            gamma_n_sl_by_bus[int(bus)] += float(weight) * float(
                cut.gamma_n_sl_by_bus.get(bus, 0.0)
            )
            gamma_n_fa_by_bus[int(bus)] += float(weight) * float(
                cut.gamma_n_fa_by_bus.get(bus, 0.0)
            )
        rows.append({
            "support_index": support_index,
            "weight": float(weight),
            "column_id": row.column_id,
            "row_id": row.row_id,
            "active_line_ids": ";".join(row.active_line_ids),
            "source_affine_value": float(value_at_source),
            "phi_delta": float(phi_delta),
            "row_cut_signature": compute_cut_signature_hash(cut),
        })

    value_cut = RestrictedMasterCut(
        cut_id=cut_id,
        beta=float(beta),
        gamma_z_by_bus=gamma_z_by_bus,
        gamma_n_sl_by_bus=gamma_n_sl_by_bus,
        gamma_n_fa_by_bus=gamma_n_fa_by_bus,
        phi_by_line_id={str(line_id): 0.0 for line_id in line_ids},
    )
    info = {
        "cut_id": cut_id,
        "support_count": len(rows),
        "beta": float(beta),
        "weighted_source_value": float(weighted_source_value),
        "signature": compute_cut_signature_hash(value_cut),
    }
    return value_cut, rows, info


def _solve_value_master(
    instance,
    *,
    value_cuts: Sequence[RestrictedMasterCut],
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    warm_start_plan: FixedFirstStagePlan | None,
    time_limit_seconds: float,
    mip_gap: float,
    log_to_console: bool,
):
    master = build_master_problem(
        instance,
        cuts=value_cuts,
        outage_column_cuts=outage_column_cuts,
        warm_start_plan=warm_start_plan,
        model_name="k16_value_master_proto1",
        log_to_console=log_to_console,
    )
    master.model.Params.TimeLimit = float(time_limit_seconds)
    master.model.Params.MIPGap = float(mip_gap)
    master.model.Params.Threads = 8
    master.model.Params.MIPFocus = 1
    master.model.optimize()
    solution = extract_master_problem_solution(master)
    obj_bound = getattr(master.model, "ObjBound", None)
    obj_val = getattr(master.model, "ObjVal", None) if int(master.model.SolCount) > 0 else None
    return master, solution, {
        "status_code": int(master.model.Status),
        "status": solution.model_status,
        "sol_count": int(master.model.SolCount),
        "obj_bound": None if obj_bound is None else float(obj_bound),
        "obj_val": None if obj_val is None else float(obj_val),
        "mip_gap": None if getattr(master.model, "MIPGap", None) is None else float(master.model.MIPGap),
        "runtime_seconds": float(master.model.Runtime),
        "value_cut_count": len(value_cuts),
        "outage_column_cut_count": len(outage_column_cuts),
    }


def _solve_relaxed_value_master_plan(
    instance,
    *,
    value_cuts: Sequence[RestrictedMasterCut],
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    time_limit_seconds: float,
    log_to_console: bool,
) -> tuple[FixedFirstStagePlan, dict[str, Any]]:
    master = build_master_problem(
        instance,
        cuts=value_cuts,
        outage_column_cuts=outage_column_cuts,
        model_name="k16_value_master_root_lp_proto",
        log_to_console=log_to_console,
    )
    relaxed = master.model.relax()
    relaxed.Params.OutputFlag = 1 if log_to_console else 0
    relaxed.Params.TimeLimit = float(time_limit_seconds)
    relaxed.optimize()
    if int(relaxed.Status) not in (GRB.OPTIMAL, GRB.TIME_LIMIT) or int(relaxed.SolCount) <= 0:
        raise RuntimeError(f"Root LP relaxation did not return a usable solution: {relaxed.Status}")
    return _plan_from_relaxed_model(master, relaxed), {
        "status_code": int(relaxed.Status),
        "status": "OPTIMAL" if int(relaxed.Status) == GRB.OPTIMAL else "TIME_LIMIT",
        "obj_bound": None if not hasattr(relaxed, "ObjBound") else float(relaxed.ObjBound),
        "obj_val": None if int(relaxed.SolCount) <= 0 else float(relaxed.ObjVal),
        "runtime_seconds": float(relaxed.Runtime),
        "sol_count": int(relaxed.SolCount),
    }


def _build_value_cut_from_candidates(
    instance,
    *,
    plan: FixedFirstStagePlan,
    candidate_rows: Sequence[tuple[RestrictedMasterOutageColumnCut, float]],
    cut_id: str,
    max_support: int,
    log_to_console: bool,
) -> tuple[RestrictedMasterCut, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    positive_distribution, distribution_info = _solve_distribution_lp(
        line_ids=instance.sets.line_ids,
        fp_by_line_id={
            line_id: float(value)
            for line_id, value in zip(instance.sets.line_ids, instance.ambiguity.p_bar)
        },
        candidates=candidate_rows,
        max_support=int(max_support),
        log_to_console=bool(log_to_console),
    )
    value_cut, support_rows, value_cut_info = _aggregate_value_cut(
        line_ids=instance.sets.line_ids,
        buses=instance.sets.buses,
        positive_distribution=positive_distribution,
        cut_id=cut_id,
    )
    return value_cut, support_rows, value_cut_info, distribution_info


def run(args: argparse.Namespace) -> dict[str, Any]:
    run_log = _read_json(args.run_log)
    run_config = dict(run_log["run_config"])
    base_instance = load_instance_for_run(
        run_config,
        critical_buses=load_critical_buses(CRITICAL_BUSES),
    )
    instance = prepare_instance_for_run(base_instance, run_config)
    cut_pool_path = _repo_path(dict(run_log.get("artifact_paths", {})).get("cut_pool_path"))
    if cut_pool_path is None or not cut_pool_path.exists():
        raise RuntimeError("K16 run log does not contain a readable cut pool path.")
    cert_path = _repo_path(dict(run_log.get("artifact_paths", {})).get("trial_certificate_path"))
    if cert_path is None or not cert_path.exists():
        raise RuntimeError("K16 run log does not contain a readable trial certificate path.")
    trial_certificate = _read_json(cert_path)
    trial_plan = _trial_plan_from_certificate(trial_certificate)

    loaded_global_cuts, outage_rows, audit_rows = _load_initial_cuts_from_pools(
        instance,
        run_config,
        {"initial_cut_pool_path": str(cut_pool_path)},
    )
    if not outage_rows:
        raise RuntimeError("No compatible outage-column cuts were loaded from the cut pool.")
    global_cuts: list[RestrictedMasterCut] = (
        [] if bool(args.no_global_cuts) else list(loaded_global_cuts)
    )

    ranked_rows = _best_rows_by_column(
        outage_rows,
        plan=trial_plan,
        max_columns=int(args.max_columns),
    )
    if bool(args.include_zero_outage_dual):
        zero_row = _build_zero_outage_row(
            instance,
            plan=trial_plan,
            log_to_console=bool(args.log_to_console),
        )
        ranked_rows.append((zero_row, _row_value_at_plan(zero_row, trial_plan)))
    value_cuts: list[RestrictedMasterCut] = list(global_cuts)
    value_cut_signature_set = {compute_cut_signature_hash(cut) for cut in value_cuts}
    support_rows_all: list[dict[str, Any]] = []
    loop_rows: list[dict[str, Any]] = []

    value_cut, support_rows, value_cut_info, distribution_info = _build_value_cut_from_candidates(
        instance,
        plan=trial_plan,
        candidate_rows=ranked_rows,
        cut_id="value_cut_seed_trial_001",
        max_support=int(args.max_support),
        log_to_console=bool(args.log_to_console),
    )
    value_cuts.append(value_cut)
    value_cut_signature_set.add(compute_cut_signature_hash(value_cut))
    for row in support_rows:
        support_rows_all.append({"value_cut_id": value_cut.cut_id, **row})

    master, _, master_info = _solve_value_master(
        instance,
        value_cuts=value_cuts,
        outage_column_cuts=outage_rows if bool(args.include_outage_column_cuts) else [],
        warm_start_plan=trial_plan,
        time_limit_seconds=float(args.time_limit_seconds),
        mip_gap=float(args.mip_gap),
        log_to_console=bool(args.log_to_console),
    )
    loop_rows.append({
        "loop": 0,
        "cut_id": value_cut.cut_id,
        "fresh_fixed_outage_rows": 0,
        "candidate_columns": len(ranked_rows),
        "positive_support_count": distribution_info["positive_support_count"],
        "distribution_objective": distribution_info["objective"],
        "p_zero": distribution_info.get("p_zero", ""),
        "value_cut_weighted_source_value": value_cut_info["weighted_source_value"],
        "value_cut_beta": value_cut_info["beta"],
        "master_status": master_info["status"],
        "master_obj_bound": master_info["obj_bound"],
        "master_obj_val": master_info["obj_val"],
        "master_mip_gap": master_info["mip_gap"],
        "master_runtime_seconds": master_info["runtime_seconds"],
        "bound_improvement_vs_prior": (
            None if master_info.get("obj_bound") is None else float(master_info["obj_bound"]) - PRIOR_K16_LB
        ),
        "remaining_gap_if_lb_used": (
            None if master_info.get("obj_bound") is None else BEST_K16_UB - float(master_info["obj_bound"])
        ),
    })

    current_solution = extract_master_problem_solution(master)
    current_plan = _plan_from_master_solution(current_solution)
    for loop_index in range(1, int(args.value_cut_loop_iterations) + 1):
        if bool(args.root_lp_value_cut_loop):
            current_plan, root_lp_info = _solve_relaxed_value_master_plan(
                instance,
                value_cuts=value_cuts,
                outage_column_cuts=outage_rows if bool(args.include_outage_column_cuts) else [],
                time_limit_seconds=float(args.root_lp_time_limit_seconds),
                log_to_console=bool(args.log_to_console),
            )
        else:
            root_lp_info = {}
        source_ranked_rows = _best_rows_by_column(
            outage_rows,
            plan=current_plan,
            max_columns=int(args.fresh_patterns_per_loop),
        )
        fresh_candidates = _generate_fresh_rows_for_patterns(
            instance,
            plan=current_plan,
            pattern_rows=[row for row, _ in source_ranked_rows],
            loop_index=loop_index,
            allow_fractional_plan=bool(args.root_lp_value_cut_loop),
            log_to_console=bool(args.log_to_console),
        )
        loop_cut, loop_support_rows, loop_cut_info, loop_distribution_info = (
            _build_value_cut_from_candidates(
                instance,
                plan=current_plan,
                candidate_rows=fresh_candidates,
                cut_id=f"value_cut_loop_{loop_index:03d}",
                max_support=int(args.max_support),
                log_to_console=bool(args.log_to_console),
            )
        )
        if compute_cut_signature_hash(loop_cut) in value_cut_signature_set:
            loop_rows.append({
                "loop": loop_index,
                "loop_source": "root_lp" if bool(args.root_lp_value_cut_loop) else "integer_master",
                "cut_id": loop_cut.cut_id,
                "fresh_fixed_outage_rows": len(fresh_candidates),
                "candidate_columns": len(fresh_candidates),
                "positive_support_count": loop_distribution_info["positive_support_count"],
                "distribution_objective": loop_distribution_info["objective"],
                "p_zero": loop_distribution_info.get("p_zero", ""),
                "value_cut_weighted_source_value": loop_cut_info["weighted_source_value"],
                "value_cut_beta": loop_cut_info["beta"],
                "master_status": "SKIPPED_DUPLICATE_VALUE_CUT",
                "root_lp_obj_val": root_lp_info.get("obj_val", ""),
            })
            break
        value_cuts.append(loop_cut)
        value_cut_signature_set.add(compute_cut_signature_hash(loop_cut))
        for row in loop_support_rows:
            support_rows_all.append({"value_cut_id": loop_cut.cut_id, **row})
        if bool(args.include_fresh_rows_in_master):
            outage_rows = [*outage_rows, *(row for row, _ in fresh_candidates if row.active_line_ids)]
        master, _, master_info = _solve_value_master(
            instance,
            value_cuts=value_cuts,
            outage_column_cuts=outage_rows if bool(args.include_outage_column_cuts) else [],
            warm_start_plan=current_plan,
            time_limit_seconds=float(args.time_limit_seconds),
            mip_gap=float(args.mip_gap),
            log_to_console=bool(args.log_to_console),
        )
        current_solution = extract_master_problem_solution(master)
        current_plan = _plan_from_master_solution(current_solution)
        lb_loop = master_info.get("obj_bound")
        loop_rows.append({
            "loop": loop_index,
            "loop_source": "root_lp" if bool(args.root_lp_value_cut_loop) else "integer_master",
            "cut_id": loop_cut.cut_id,
            "fresh_fixed_outage_rows": len(fresh_candidates),
            "candidate_columns": len(fresh_candidates),
            "positive_support_count": loop_distribution_info["positive_support_count"],
            "distribution_objective": loop_distribution_info["objective"],
            "p_zero": loop_distribution_info.get("p_zero", ""),
            "value_cut_weighted_source_value": loop_cut_info["weighted_source_value"],
            "value_cut_beta": loop_cut_info["beta"],
            "master_status": master_info["status"],
            "master_obj_bound": master_info["obj_bound"],
            "master_obj_val": master_info["obj_val"],
            "master_mip_gap": master_info["mip_gap"],
            "master_runtime_seconds": master_info["runtime_seconds"],
            "root_lp_status": root_lp_info.get("status", ""),
            "root_lp_obj_val": root_lp_info.get("obj_val", ""),
            "root_lp_runtime_seconds": root_lp_info.get("runtime_seconds", ""),
            "bound_improvement_vs_prior": (
                None if lb_loop is None else float(lb_loop) - PRIOR_K16_LB
            ),
            "remaining_gap_if_lb_used": (
                None if lb_loop is None else BEST_K16_UB - float(lb_loop)
            ),
        })

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "value_cut_support.csv", support_rows_all)
    _write_csv(output_dir / "value_cut_loop_trace.csv", loop_rows)
    _write_csv(output_dir / "cut_pool_audit.csv", audit_rows)
    _write_json(
        output_dir / "value_cut.json",
        {
            "loaded_global_cut_count": len(global_cuts),
            "distributional_value_cuts": [
                {
                    "cut_id": cut.cut_id,
                    "beta": cut.beta,
                    "signature": compute_cut_signature_hash(cut),
                    "gamma_z_by_bus": {str(k): v for k, v in cut.gamma_z_by_bus.items()},
                    "gamma_n_sl_by_bus": {
                        str(k): v for k, v in cut.gamma_n_sl_by_bus.items()
                    },
                    "gamma_n_fa_by_bus": {
                        str(k): v for k, v in cut.gamma_n_fa_by_bus.items()
                    },
                    "phi_by_line_id": {str(k): v for k, v in cut.phi_by_line_id.items()},
                }
                for cut in value_cuts[len(global_cuts):]
            ],
        },
    )
    lb = master_info.get("obj_bound")
    summary = {
        "source_run_log": str(Path(args.run_log)),
        "source_cut_pool": str(cut_pool_path),
        "source_trial_certificate": str(cert_path),
        "loaded_outage_column_cuts": len(outage_rows),
        "loaded_global_cuts": len(loaded_global_cuts),
        "included_global_cuts": not bool(args.no_global_cuts),
        "candidate_columns": len(ranked_rows),
        "distribution_lp": distribution_info,
        "value_cut": value_cut_info,
        "value_cut_loop_iterations_requested": int(args.value_cut_loop_iterations),
        "root_lp_value_cut_loop": bool(args.root_lp_value_cut_loop),
        "value_cut_loop_iterations_completed": max(
            (int(row["loop"]) for row in loop_rows if str(row.get("master_status", "")).startswith("OPTIMAL")),
            default=0,
        ),
        "value_cut_loop_trace_path": str(output_dir / "value_cut_loop_trace.csv"),
        "seeded_distributional_value_cut_count": len(value_cuts) - len(global_cuts),
        "value_cut_count_including_global": len(value_cuts),
        "final_loop": loop_rows[-1] if loop_rows else {},
        "master": master_info,
        "included_outage_column_cuts": bool(args.include_outage_column_cuts),
        "prior_k16_lb": PRIOR_K16_LB,
        "best_k16_ub": BEST_K16_UB,
        "epsilon_gap_target": EPS_GAP_TARGET,
        "bound_improvement_vs_prior": (
            None if lb is None else float(lb) - PRIOR_K16_LB
        ),
        "remaining_gap_if_lb_used": (
            None if lb is None else BEST_K16_UB - float(lb)
        ),
        "paper_facing_eligible": False,
        "validation_level": "value_master_proto1_diagnostic",
    }
    _write_json(output_dir / "value_master_summary.json", summary)
    _write_csv(
        output_dir / "value_master_summary.csv",
        [{
            "loaded_outage_column_cuts": len(outage_rows),
            "loaded_global_cuts": len(loaded_global_cuts),
            "included_global_cuts": not bool(args.no_global_cuts),
            "candidate_columns": len(ranked_rows),
            "positive_support_count": distribution_info["positive_support_count"],
            "distribution_objective": distribution_info["objective"],
            "value_cut_weighted_source_value": value_cut_info["weighted_source_value"],
            "seeded_distributional_value_cut_count": len(value_cuts) - len(global_cuts),
            "value_cut_count_including_global": len(value_cuts),
            "master_status": master_info["status"],
            "master_obj_bound": master_info["obj_bound"],
            "master_obj_val": master_info["obj_val"],
            "master_mip_gap": master_info["mip_gap"],
            "master_runtime_seconds": master_info["runtime_seconds"],
            "prior_k16_lb": PRIOR_K16_LB,
            "best_k16_ub": BEST_K16_UB,
            "bound_improvement_vs_prior": summary["bound_improvement_vs_prior"],
            "remaining_gap_if_lb_used": summary["remaining_gap_if_lb_used"],
        }],
    )
    try:
        master.model.write(str(output_dir / "value_master_proto1.lp"))
    except Exception:
        pass
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-log", default=str(DEFAULT_K16_RUN_LOG))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-columns", type=int, default=600)
    parser.add_argument("--max-support", type=int, default=0)
    parser.add_argument("--time-limit-seconds", type=float, default=600.0)
    parser.add_argument("--mip-gap", type=float, default=0.03)
    parser.add_argument("--include-outage-column-cuts", action="store_true")
    parser.add_argument("--include-fresh-rows-in-master", action="store_true")
    parser.add_argument("--no-global-cuts", action="store_true")
    parser.add_argument("--value-cut-loop-iterations", type=int, default=0)
    parser.add_argument("--fresh-patterns-per-loop", type=int, default=12)
    parser.add_argument("--root-lp-value-cut-loop", action="store_true")
    parser.add_argument("--root-lp-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--no-zero-outage-dual", dest="include_zero_outage_dual", action="store_false")
    parser.set_defaults(include_zero_outage_dual=True)
    parser.add_argument("--log-to-console", action="store_true")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    summary = run(args)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
