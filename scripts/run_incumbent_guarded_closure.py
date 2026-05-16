"""Run Pro-reviewed incumbent-guarded target-level closure for K-scaling rows.

This script implements the certificate-closure prototype from the Pro note
`evcs_dro_incumbent_guarded_closure.tex`. It never promotes rows to
`paper_final`; it writes engineering diagnostics only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Mapping, Sequence

from gurobipy import GRB, Model, quicksum


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import (  # noqa: E402
    _load_initial_cuts_from_pools,
    _write_cut_pool,
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from scripts.run_full_benders_scalability import CRITICAL_BUSES  # noqa: E402
from src.production.benders_engine import (  # noqa: E402
    _active_outage_lines,
    _outage_column_id,
    _pricing_derived_upper_bound,
)
from src.production.cut_factory import (  # noqa: E402
    compute_cut_signature_hash,
    generate_cut_from_separation_solution,
    generate_structured_cut_from_decompositions,
    generate_structured_cut,
)
from src.production.master_problem import (  # noqa: E402
    RestrictedMasterCut,
    RestrictedMasterOutageColumnCut,
    build_master_problem,
    extract_master_problem_solution,
)
from src.production.first_stage import (  # noqa: E402
    build_first_stage_model,
    extract_first_stage_solution,
)
from src.production.normal_block import (  # noqa: E402
    build_normal_operation_block,
    extract_normal_operation_solution,
)
from src.production.separation_milp import solve_separation_milp  # noqa: E402
from src.reference.disaster_primal_ref import (  # noqa: E402
    FixedFirstStagePlan,
    build_fixed_first_stage_plan,
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
DEFAULT_AUDIT_JSON = (
    REPO_ROOT
    / "results/engineering_acceleration/certificate_closure_k16/"
    "pricing_ub_certificate_audit.json"
)
DEFAULT_PRO_TEX = Path("/Users/shixinliu/Downloads/evcs_dro_incumbent_guarded_closure.tex")


def _safe_gurobi_name(prefix: str, key: object, *, max_length: int = 240) -> str:
    """Return a stable short Gurobi name for persisted cut ids."""

    raw = f"{prefix}_{key}"
    if len(raw) <= max_length:
        return raw
    digest = hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:16]
    prefix_budget = max(8, max_length - len(digest) - 1)
    return f"{prefix[:prefix_budget]}_{digest}"


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: str | Path | None, payload: Mapping[str, Any]) -> None:
    if path in (None, ""):
        return
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")


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


def _parse_int_list(raw: str | Sequence[int]) -> tuple[int, ...]:
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",") if part.strip()]
        return tuple(int(value) for value in values)
    return tuple(int(value) for value in raw)


def _parse_path_list(raw: str | Sequence[str] | None) -> tuple[Path, ...]:
    if raw in (None, ""):
        return ()
    if isinstance(raw, str):
        return tuple(Path(part.strip()) for part in raw.split(",") if part.strip())
    return tuple(Path(str(value)) for value in raw)


def _status_name(status_code: int) -> str:
    names = {
        GRB.OPTIMAL: "OPTIMAL",
        GRB.INFEASIBLE: "INFEASIBLE",
        GRB.INF_OR_UNBD: "INF_OR_UNBD",
        GRB.UNBOUNDED: "UNBOUNDED",
        GRB.TIME_LIMIT: "TIME_LIMIT",
        GRB.CUTOFF: "CUTOFF",
        GRB.INTERRUPTED: "INTERRUPTED",
        GRB.NUMERIC: "NUMERIC",
    }
    return names.get(int(status_code), str(status_code))


def _apply_optional_target_solver_params(model, args: argparse.Namespace) -> None:
    if int(args.target_threads) > 0:
        model.Params.Threads = int(args.target_threads)
    if int(args.target_mip_focus) >= 0:
        model.Params.MIPFocus = int(args.target_mip_focus)
    if int(args.target_presolve) >= 0:
        model.Params.Presolve = int(args.target_presolve)
    if int(args.target_cuts) >= 0:
        model.Params.Cuts = int(args.target_cuts)
    if float(args.target_heuristics) >= 0.0:
        model.Params.Heuristics = float(args.target_heuristics)


def _trial_plan(certificate: Mapping[str, Any]) -> FixedFirstStagePlan:
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


def _plan_from_solution(instance, solution) -> FixedFirstStagePlan:
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus=solution.first_stage_solution.z_by_bus,
        n_sl_by_bus=solution.first_stage_solution.n_sl_by_bus,
        n_fa_by_bus=solution.first_stage_solution.n_fa_by_bus,
    )


def _load_valid_incumbent(
    *,
    run_log: Mapping[str, Any],
    audit_json_path: Path | None,
    epsilon_gap: float,
) -> dict[str, Any]:
    cert_path = _repo_path(dict(run_log.get("artifact_paths", {})).get("trial_certificate_path"))
    if cert_path is None or not cert_path.exists():
        raise RuntimeError("K16 run log does not contain a readable trial certificate.")
    certificate = _read_json(cert_path)
    audit_payload: dict[str, Any] = {}
    if audit_json_path is not None and audit_json_path.exists():
        audit_payload = _read_json(audit_json_path)
    upper_bound = float(
        audit_payload.get(
            "pricing_derived_upper_bound_replay",
            certificate.get("pricing_derived_upper_bound"),
        )
    )
    canonical_lb = float(
        audit_payload.get("canonical_lower_bound", certificate.get("canonical_lower_bound"))
    )
    return {
        "trial_certificate_path": str(cert_path),
        "audit_json_path": "" if audit_json_path is None else str(audit_json_path),
        "pricing_upper_bound": upper_bound,
        "canonical_lower_bound": canonical_lb,
        "initial_gap": max(0.0, upper_bound - canonical_lb),
        "epsilon_gap": float(epsilon_gap),
        "target_tau": upper_bound - float(epsilon_gap),
        "certificate": certificate,
    }


def _load_engineering_state(run_log: Mapping[str, Any]) -> tuple[dict[str, Any], Path]:
    run_config = dict(run_log["run_config"])
    cut_pool_path = _repo_path(dict(run_log.get("artifact_paths", {})).get("cut_pool_path"))
    if cut_pool_path is None or not cut_pool_path.exists():
        raise RuntimeError("K16 run log does not contain a readable cut pool.")
    return run_config, cut_pool_path


def _solve_target_level_master(
    instance,
    *,
    cuts: Sequence[RestrictedMasterCut],
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    tau: float,
    warm_start_plan: FixedFirstStagePlan | None,
    warm_start_alpha: float | None,
    warm_start_lambda_by_line_id: Mapping[str, float] | None,
    time_limit_seconds: float,
    mip_gap: float,
    pool_solutions: int,
    target_search_objective: str,
    model_name: str,
    log_to_console: bool,
):
    master = build_master_problem(
        instance,
        cuts=cuts,
        outage_column_cuts=outage_column_cuts,
        warm_start_plan=warm_start_plan,
        warm_start_alpha=warm_start_alpha,
        warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
        model_name=model_name,
        log_to_console=log_to_console,
    )
    if master.total_objective_expression is None:
        raise RuntimeError("Canonical master did not expose total objective expression.")
    master.model.addConstr(
        master.total_objective_expression <= float(tau),
        name="target_level_objective_upper_bound",
    )
    if target_search_objective == "max_original":
        master.model.setObjective(master.total_objective_expression, sense=GRB.MAXIMIZE)
    elif target_search_objective == "feasibility":
        master.model.setObjective(0.0, sense=GRB.MINIMIZE)
    master.model.Params.TimeLimit = float(time_limit_seconds)
    master.model.Params.MIPGap = float(mip_gap)
    master.model.Params.DualReductions = 0
    if int(pool_solutions) > 1:
        master.model.Params.PoolSearchMode = 2
        master.model.Params.PoolSolutions = int(pool_solutions)
    master.model.optimize()
    solution = extract_master_problem_solution(master)
    return master, solution


def _build_persistent_target_master(
    instance,
    *,
    cuts: Sequence[RestrictedMasterCut],
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    tau: float,
    warm_start_plan: FixedFirstStagePlan | None,
    warm_start_alpha: float | None,
    warm_start_lambda_by_line_id: Mapping[str, float] | None,
    time_limit_seconds: float,
    mip_gap: float,
    pool_solutions: int,
    target_search_objective: str,
    model_name: str,
    log_to_console: bool,
):
    master = build_master_problem(
        instance,
        cuts=cuts,
        outage_column_cuts=outage_column_cuts,
        warm_start_plan=warm_start_plan,
        warm_start_alpha=warm_start_alpha,
        warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
        model_name=model_name,
        log_to_console=log_to_console,
    )
    if master.total_objective_expression is None:
        raise RuntimeError("Canonical master did not expose total objective expression.")
    target_constraint = master.model.addConstr(
        master.total_objective_expression <= float(tau),
        name="target_level_objective_upper_bound",
    )
    if target_search_objective == "max_original":
        master.model.setObjective(master.total_objective_expression, sense=GRB.MAXIMIZE)
    elif target_search_objective == "feasibility":
        master.model.setObjective(0.0, sense=GRB.MINIMIZE)
    master.model.Params.TimeLimit = float(time_limit_seconds)
    master.model.Params.MIPGap = float(mip_gap)
    master.model.Params.DualReductions = 0
    if int(pool_solutions) > 1:
        master.model.Params.PoolSearchMode = 2
        master.model.Params.PoolSolutions = int(pool_solutions)
    master.model.update()
    return master, target_constraint


def _optimize_existing_target_master(master, *, tau: float, target_constraint) -> Any:
    target_constraint.RHS = float(tau)
    master.model.update()
    master.model.optimize()
    return extract_master_problem_solution(master)


def _add_global_cut_to_existing_master(master, cut: RestrictedMasterCut) -> None:
    model = master.model
    ordered_line_ids = master.ordered_line_ids
    ordered_buses = master.ordered_buses
    s_var = model.addVar(lb=0.0, name=_safe_gurobi_name("s_cut", cut.cut_id))
    u_vars = {
        line_id: model.addVar(
            lb=0.0,
            name=_safe_gurobi_name("u_cut", f"{cut.cut_id}_{line_id}"),
        )
        for line_id in ordered_line_ids
    }
    gamma_expr = quicksum(
        cut.gamma_z_by_bus[bus] * master.first_stage.z_by_bus[bus]
        + cut.gamma_n_sl_by_bus[bus] * master.first_stage.n_sl_by_bus[bus]
        + cut.gamma_n_fa_by_bus[bus] * master.first_stage.n_fa_by_bus[bus]
        for bus in ordered_buses
    )
    master.cut_support_constraints[cut.cut_id] = model.addConstr(
        master.alpha_var
        >= float(cut.beta) - gamma_expr + float(master.budget_k) * s_var
        + quicksum(u_vars.values()),
        name=_safe_gurobi_name("eq39_cut_support", cut.cut_id),
    )
    master.s_by_cut_id[cut.cut_id] = s_var
    for line_id in ordered_line_ids:
        master.u_by_cut_id_and_line_id[(cut.cut_id, line_id)] = u_vars[line_id]
        master.u_link_constraints[(cut.cut_id, line_id)] = model.addConstr(
            u_vars[line_id]
            >= float(cut.phi_by_line_id[line_id])
            - master.lambda_by_line_id[line_id]
            - s_var,
            name=_safe_gurobi_name("eq39_u_link", f"{cut.cut_id}_{line_id}"),
        )
    model.update()


def _add_outage_column_cut_to_existing_master(
    master,
    row: RestrictedMasterOutageColumnCut,
) -> None:
    model = master.model
    column_id = str(row.column_id)
    if column_id not in master.theta_by_outage_column_id:
        theta_var = model.addVar(lb=0.0, name=f"theta_outage_{column_id}")
        master.theta_by_outage_column_id[column_id] = theta_var
        master.outage_column_support_constraints[column_id] = model.addConstr(
            master.alpha_var
            + quicksum(master.lambda_by_line_id[line_id] for line_id in row.active_line_ids)
            >= theta_var,
            name=f"nccg_outage_support_{column_id}",
        )
    theta_var = master.theta_by_outage_column_id[column_id]
    cut = row.cut
    gamma_expr = quicksum(
        cut.gamma_z_by_bus[bus] * master.first_stage.z_by_bus[bus]
        + cut.gamma_n_sl_by_bus[bus] * master.first_stage.n_sl_by_bus[bus]
        + cut.gamma_n_fa_by_bus[bus] * master.first_stage.n_fa_by_bus[bus]
        for bus in master.ordered_buses
    )
    phi_delta = sum(float(cut.phi_by_line_id[line_id]) for line_id in row.active_line_ids)
    master.outage_column_cut_constraints[row.row_id] = model.addConstr(
        theta_var >= float(cut.beta) - gamma_expr + float(phi_delta),
        name=_safe_gurobi_name("nccg_rowwise_cut", row.row_id),
    )
    model.update()


def _add_direct_fixed_outage_cut_to_existing_master(
    master,
    *,
    cut: RestrictedMasterCut,
    active_line_ids: Sequence[str],
    row_id: str,
) -> None:
    gamma_expr = quicksum(
        cut.gamma_z_by_bus[bus] * master.first_stage.z_by_bus[bus]
        + cut.gamma_n_sl_by_bus[bus] * master.first_stage.n_sl_by_bus[bus]
        + cut.gamma_n_fa_by_bus[bus] * master.first_stage.n_fa_by_bus[bus]
        for bus in master.ordered_buses
    )
    phi_delta = sum(float(cut.phi_by_line_id[line_id]) for line_id in active_line_ids)
    master.model.addConstr(
        master.alpha_var
        + quicksum(master.lambda_by_line_id[line_id] for line_id in active_line_ids)
        >= float(cut.beta) - gamma_expr + float(phi_delta),
        name=_safe_gurobi_name("direct_fixed_outage_cut", row_id),
    )
    master.model.update()


def _direct_fixed_outage_temp_constr(
    master,
    *,
    cut: RestrictedMasterCut,
    active_line_ids: Sequence[str],
):
    gamma_expr = quicksum(
        cut.gamma_z_by_bus[bus] * master.first_stage.z_by_bus[bus]
        + cut.gamma_n_sl_by_bus[bus] * master.first_stage.n_sl_by_bus[bus]
        + cut.gamma_n_fa_by_bus[bus] * master.first_stage.n_fa_by_bus[bus]
        for bus in master.ordered_buses
    )
    phi_delta = sum(float(cut.phi_by_line_id[line_id]) for line_id in active_line_ids)
    return (
        master.alpha_var
        + quicksum(master.lambda_by_line_id[line_id] for line_id in active_line_ids)
        >= float(cut.beta) - gamma_expr + float(phi_delta)
    )


def _evaluate_linear_expression_from_values(expr: Any, value_getter) -> float:
    """Evaluate a Gurobi linear expression with an explicit variable getter."""

    if expr is None:
        raise RuntimeError("Cannot evaluate a missing objective expression.")
    if isinstance(expr, (int, float)):
        return float(expr)
    if hasattr(expr, "size") and hasattr(expr, "getVar") and hasattr(expr, "getCoeff"):
        value = float(expr.getConstant()) if hasattr(expr, "getConstant") else 0.0
        for index in range(int(expr.size())):
            value += float(expr.getCoeff(index)) * float(value_getter(expr.getVar(index)))
        return float(value)
    return float(value_getter(expr))


def _callback_original_objective_value(model, master) -> float:
    return _evaluate_linear_expression_from_values(
        master.total_objective_expression,
        lambda var: model.cbGetSolution(var),
    )


def _pool_original_objective_value(master) -> float:
    return _evaluate_linear_expression_from_values(
        master.total_objective_expression,
        lambda var: var.Xn,
    )


def _active_line_variants_for_cut(
    cut: RestrictedMasterCut,
    active_line_ids: Sequence[str],
    subset_sizes: Sequence[int],
) -> list[tuple[str, ...]]:
    full_active = tuple(str(line_id) for line_id in active_line_ids)
    variants: list[tuple[str, ...]] = [full_active]
    seen = {full_active}
    ranked_active_lines = tuple(
        line_id
        for line_id, _phi in sorted(
            (
                (line_id, float(cut.phi_by_line_id[line_id]))
                for line_id in full_active
            ),
            key=lambda item: item[1],
            reverse=True,
        )
    )
    for size in sorted({int(value) for value in subset_sizes if int(value) > 0}, reverse=True):
        if size >= len(ranked_active_lines):
            continue
        variant = tuple(sorted(ranked_active_lines[:size]))
        if variant in seen:
            continue
        variants.append(variant)
        seen.add(variant)
    return variants


def _sdbc_var_key(kind: str, identifier: object | None = None) -> str:
    return str(kind) if identifier is None else f"{kind}:{identifier}"


def _sdbc_master_var_by_key(master, key: str):
    if key == "alpha":
        return master.alpha_var
    if key.startswith("lambda:"):
        return master.lambda_by_line_id.get(key.split(":", 1)[1])
    if key.startswith("z:"):
        return master.first_stage.z_by_bus.get(int(key.split(":", 1)[1]))
    if key.startswith("sl:"):
        return master.first_stage.n_sl_by_bus.get(int(key.split(":", 1)[1]))
    if key.startswith("fa:"):
        return master.first_stage.n_fa_by_bus.get(int(key.split(":", 1)[1]))
    return None


def _sdbc_linear_expr(master, coeffs: Mapping[str, float]):
    expr = 0.0
    for key, coeff in coeffs.items():
        if abs(float(coeff)) <= 1e-12:
            continue
        var = _sdbc_master_var_by_key(master, str(key))
        if var is None:
            continue
        expr += float(coeff) * var
    return expr


def _sdbc_row(
    row_id: str,
    coeffs: Mapping[str, float],
    rhs: float,
    *,
    source: str,
) -> dict[str, Any]:
    compact = {
        str(key): float(value)
        for key, value in coeffs.items()
        if abs(float(value)) > 1e-12
    }
    return {
        "row_id": str(row_id),
        "coeffs": compact,
        "rhs": float(rhs),
        "source": str(source),
    }


def _sdbc_add_first_stage_rows(instance, master) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    nbar_sl_by_bus = dict(getattr(instance.ev, "nbar_sl_by_bus", {}) or {})
    nbar_fa_by_bus = dict(getattr(instance.ev, "nbar_fa_by_bus", {}) or {})
    for bus in master.ordered_buses:
        z_key = _sdbc_var_key("z", bus)
        sl_key = _sdbc_var_key("sl", bus)
        fa_key = _sdbc_var_key("fa", bus)
        z_var = master.first_stage.z_by_bus[bus]
        sl_var = master.first_stage.n_sl_by_bus[bus]
        fa_var = master.first_stage.n_fa_by_bus[bus]
        rows.append(_sdbc_row(f"lb_{z_key}", {z_key: 1.0}, float(z_var.LB), source="var_lb"))
        if float(z_var.UB) < GRB.INFINITY / 2:
            rows.append(_sdbc_row(f"ub_{z_key}", {z_key: -1.0}, -float(z_var.UB), source="var_ub"))
        rows.append(_sdbc_row(f"lb_{sl_key}", {sl_key: 1.0}, float(sl_var.LB), source="var_lb"))
        rows.append(_sdbc_row(f"lb_{fa_key}", {fa_key: 1.0}, float(fa_var.LB), source="var_lb"))
        if float(sl_var.UB) < GRB.INFINITY / 2:
            rows.append(_sdbc_row(f"ub_{sl_key}", {sl_key: -1.0}, -float(sl_var.UB), source="var_ub"))
        if float(fa_var.UB) < GRB.INFINITY / 2:
            rows.append(_sdbc_row(f"ub_{fa_key}", {fa_key: -1.0}, -float(fa_var.UB), source="var_ub"))
        nbar_sl = float(nbar_sl_by_bus.get(bus, instance.ev.nbar_sl))
        nbar_fa = float(nbar_fa_by_bus.get(bus, instance.ev.nbar_fa))
        rows.append(
            _sdbc_row(
                f"cap_sl_n{bus}",
                {z_key: nbar_sl, sl_key: -1.0},
                0.0,
                source="first_stage_capacity",
            )
        )
        rows.append(
            _sdbc_row(
                f"cap_fa_n{bus}",
                {z_key: nbar_fa, fa_key: -1.0},
                0.0,
                source="first_stage_capacity",
            )
        )
        rows.append(
            _sdbc_row(
                f"min_chargers_n{bus}",
                {sl_key: 1.0, fa_key: 1.0, z_key: -3.0},
                0.0,
                source="first_stage_min_chargers",
            )
        )
    return rows


def _sdbc_top_k_subset(
    instance,
    cut: RestrictedMasterCut,
    lambda_values: Mapping[str, float],
) -> tuple[str, ...]:
    ranked = sorted(
        (
            (
                str(line_id),
                float(cut.phi_by_line_id[line_id]) - float(lambda_values.get(str(line_id), 0.0)),
            )
            for line_id in instance.sets.line_ids
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    selected = [
        line_id
        for line_id, score in ranked
        if score > 1e-9
    ][: int(instance.ambiguity.k_max_outages)]
    return tuple(sorted(selected))


def _sdbc_direct_row_from_cut(
    instance,
    *,
    cut: RestrictedMasterCut,
    active_line_ids: Sequence[str],
    row_id: str,
    source: str,
) -> dict[str, Any]:
    coeffs: dict[str, float] = {"alpha": 1.0}
    for line_id in active_line_ids:
        coeffs[_sdbc_var_key("lambda", str(line_id))] = (
            coeffs.get(_sdbc_var_key("lambda", str(line_id)), 0.0) + 1.0
        )
    for bus in instance.sets.buses:
        coeffs[_sdbc_var_key("z", bus)] = float(cut.gamma_z_by_bus[bus])
        coeffs[_sdbc_var_key("sl", bus)] = float(cut.gamma_n_sl_by_bus[bus])
        coeffs[_sdbc_var_key("fa", bus)] = float(cut.gamma_n_fa_by_bus[bus])
    rhs = float(cut.beta) + sum(float(cut.phi_by_line_id[line_id]) for line_id in active_line_ids)
    return _sdbc_row(row_id, coeffs, rhs, source=source)


def _sdbc_registry_from_cuts(
    instance,
    master,
    *,
    cuts: Sequence[RestrictedMasterCut],
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    lambda_values: Mapping[str, float],
    max_rows: int,
) -> list[dict[str, Any]]:
    rows = _sdbc_add_first_stage_rows(instance, master)
    seen: set[str] = {
        json.dumps({"coeffs": row["coeffs"], "rhs": round(float(row["rhs"]), 8)}, sort_keys=True)
        for row in rows
    }

    def add(row: dict[str, Any]) -> None:
        key = json.dumps(
            {"coeffs": row["coeffs"], "rhs": round(float(row["rhs"]), 8)},
            sort_keys=True,
        )
        if key in seen:
            return
        seen.add(key)
        rows.append(row)

    for idx, rowwise in enumerate(outage_column_cuts, start=1):
        add(
            _sdbc_direct_row_from_cut(
                instance,
                cut=rowwise.cut,
                active_line_ids=rowwise.active_line_ids,
                row_id=f"rowwise_{idx:05d}_{rowwise.row_id}",
                source="outage_column_direct",
            )
        )
        if len(rows) >= int(max_rows):
            return rows[: int(max_rows)]
    for idx, cut in enumerate(cuts, start=1):
        top_subset = _sdbc_top_k_subset(instance, cut, lambda_values)
        add(
            _sdbc_direct_row_from_cut(
                instance,
                cut=cut,
                active_line_ids=top_subset,
                row_id=f"global_topk_{idx:05d}_{cut.cut_id}",
                source="global_cut_topk_direct",
            )
        )
        if len(rows) >= int(max_rows):
            return rows[: int(max_rows)]
    return rows[: int(max_rows)]


def _sdbc_compact_coeffs_from_expr(expr: Any) -> tuple[dict[str, float], float]:
    coeffs: dict[str, float] = {}
    constant = 0.0
    if isinstance(expr, (int, float)):
        return {}, float(expr)
    if hasattr(expr, "getConstant"):
        constant = float(expr.getConstant())
    if hasattr(expr, "size") and hasattr(expr, "getVar") and hasattr(expr, "getCoeff"):
        for index in range(int(expr.size())):
            var = expr.getVar(index)
            coeff = float(expr.getCoeff(index))
            name = var.VarName
            key: str | None = None
            if name.startswith("z_n"):
                key = _sdbc_var_key("z", int(name.split("_n")[-1]))
            elif name.startswith("n_sl_n"):
                key = _sdbc_var_key("sl", int(name.split("_n")[-1]))
            elif name.startswith("n_fa_n"):
                key = _sdbc_var_key("fa", int(name.split("_n")[-1]))
            elif name == "alpha":
                key = "alpha"
            elif name.startswith("lambda_"):
                key = _sdbc_var_key("lambda", name.split("lambda_", 1)[1])
            if key is not None:
                coeffs[key] = coeffs.get(key, 0.0) + coeff
    return coeffs, constant


def _sdbc_target_cutoff_row(
    instance,
    master,
    *,
    cutoff_rhs: float,
) -> dict[str, Any] | None:
    if master.construction_cost_expression is None or master.disaster_master_expression is None:
        return None
    multipliers = instance.economics.objective_multipliers
    compact_expr = (
        float(multipliers.cons) * master.construction_cost_expression
        + float(multipliers.disaster) * master.disaster_master_expression
    )
    coeffs, constant = _sdbc_compact_coeffs_from_expr(compact_expr)
    if not coeffs:
        return None
    # Full target feasibility implies compact construction+disaster objective <= cutoff_rhs
    # because the normal-operation cost term is nonnegative.  Therefore the
    # negated row below is a valid necessary condition for the target set.
    return _sdbc_row(
        "compact_target_cutoff_construction_disaster",
        {key: -value for key, value in coeffs.items()},
        -float(cutoff_rhs) + float(constant),
        source="compact_target_cutoff",
    )


def _solve_sdbc_cglp(
    *,
    rows: Sequence[Mapping[str, Any]],
    split_key: str,
    split_q: int,
    point_values: Mapping[str, float],
    time_limit_seconds: float,
    violation_tolerance: float,
) -> dict[str, Any]:
    keys: list[str] = sorted(
        {
            str(key)
            for row in rows
            for key in dict(row["coeffs"]).keys()
        }
        | {str(split_key)}
    )
    if not rows or split_key not in keys:
        return {"accepted": False, "reason": "empty_rows_or_missing_split_key"}
    model = Model("sdbc_cglp")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = float(time_limit_seconds)
    rho = {key: model.addVar(lb=-GRB.INFINITY, name=f"rho_{idx}") for idx, key in enumerate(keys)}
    rho0 = model.addVar(lb=-GRB.INFINITY, name="rho0")
    mu0 = {
        idx: model.addVar(lb=0.0, name=f"mu0_{idx}")
        for idx, _row in enumerate(rows)
    }
    mu1 = {
        idx: model.addVar(lb=0.0, name=f"mu1_{idx}")
        for idx, _row in enumerate(rows)
    }
    nu0 = model.addVar(lb=0.0, name="nu0")
    nu1 = model.addVar(lb=0.0, name="nu1")
    for key in keys:
        a0 = quicksum(float(dict(rows[idx]["coeffs"]).get(key, 0.0)) * mu0[idx] for idx in range(len(rows)))
        a1 = quicksum(float(dict(rows[idx]["coeffs"]).get(key, 0.0)) * mu1[idx] for idx in range(len(rows)))
        d_coeff = 1.0 if key == split_key else 0.0
        model.addConstr(rho[key] == a0 - float(d_coeff) * nu0, name=f"rho_left_{key}")
        model.addConstr(rho[key] == a1 + float(d_coeff) * nu1, name=f"rho_right_{key}")
    model.addConstr(
        rho0
        <= quicksum(float(rows[idx]["rhs"]) * mu0[idx] for idx in range(len(rows)))
        - float(split_q) * nu0,
        name="rhs_left",
    )
    model.addConstr(
        rho0
        <= quicksum(float(rows[idx]["rhs"]) * mu1[idx] for idx in range(len(rows)))
        + float(split_q + 1) * nu1,
        name="rhs_right",
    )
    model.addConstr(
        quicksum(mu0.values()) + quicksum(mu1.values()) + nu0 + nu1 == 1.0,
        name="normalization",
    )
    violation_expr = rho0 - quicksum(
        rho[key] * float(point_values.get(key, 0.0))
        for key in keys
    )
    model.setObjective(violation_expr, GRB.MAXIMIZE)
    model.optimize()
    status_name = _status_name(int(model.Status))
    if model.Status != GRB.OPTIMAL:
        return {"accepted": False, "status": status_name, "reason": "cglp_not_optimal"}
    violation = float(model.ObjVal)
    coeffs = {key: float(rho[key].X) for key in keys if abs(float(rho[key].X)) > 1e-9}
    rhs = float(rho0.X)
    lhs_at_point = sum(float(coeffs.get(key, 0.0)) * float(point_values.get(key, 0.0)) for key in coeffs)
    reconstruction = {
        "nu0": float(nu0.X),
        "nu1": float(nu1.X),
        "mu0_sum": sum(float(var.X) for var in mu0.values()),
        "mu1_sum": sum(float(var.X) for var in mu1.values()),
    }
    return {
        "accepted": bool(violation > float(violation_tolerance) and coeffs),
        "status": status_name,
        "violation": violation,
        "rhs": rhs,
        "lhs_at_point": lhs_at_point,
        "coeffs": coeffs,
        "split_key": split_key,
        "split_q": int(split_q),
        "reconstruction": reconstruction,
    }


def _sdbc_relaxation_solution(
    master,
    *,
    side_split_key: str | None = None,
    side: str | None = None,
    split_q: int | None = None,
    time_limit_seconds: float | None = None,
) -> tuple[dict[str, float], float | None, str]:
    master.model.update()
    relaxation = master.model.relax()
    relaxation.Params.OutputFlag = 0
    relaxation.Params.DualReductions = 0
    if time_limit_seconds is not None and float(time_limit_seconds) > 0.0:
        relaxation.Params.TimeLimit = float(time_limit_seconds)
    if side_split_key is not None:
        if side not in {"left", "right"}:
            raise ValueError("side must be 'left' or 'right' when side_split_key is set.")
        original_var = _sdbc_master_var_by_key(master, side_split_key)
        if original_var is None:
            return {}, None, "MISSING_SPLIT_VAR"
        rel_var = relaxation.getVarByName(original_var.VarName)
        if rel_var is None:
            return {}, None, "MISSING_RELAXED_SPLIT_VAR"
        if side == "left":
            relaxation.addConstr(rel_var <= int(split_q), name="sdbc_side_left")
        else:
            relaxation.addConstr(rel_var >= int(split_q) + 1, name="sdbc_side_right")
    relaxation.optimize()
    if relaxation.Status != GRB.OPTIMAL:
        return {}, None, _status_name(int(relaxation.Status))
    by_name = {var.VarName: var.X for var in relaxation.getVars()}
    values: dict[str, float] = {"alpha": float(by_name.get(master.alpha_var.VarName, 0.0))}
    for line_id, var in master.lambda_by_line_id.items():
        values[_sdbc_var_key("lambda", line_id)] = max(0.0, float(by_name.get(var.VarName, 0.0)))
    for bus, var in master.first_stage.z_by_bus.items():
        values[_sdbc_var_key("z", bus)] = float(by_name.get(var.VarName, 0.0))
    for bus, var in master.first_stage.n_sl_by_bus.items():
        values[_sdbc_var_key("sl", bus)] = float(by_name.get(var.VarName, 0.0))
    for bus, var in master.first_stage.n_fa_by_bus.items():
        values[_sdbc_var_key("fa", bus)] = float(by_name.get(var.VarName, 0.0))
    return values, float(relaxation.ObjVal), "OPTIMAL"


def _sdbc_objective_from_values(master, values: Mapping[str, float]) -> float:
    def getter(var) -> float:
        name = var.VarName
        if name.startswith("z_n"):
            return float(values.get(_sdbc_var_key("z", int(name.split("_n")[-1])), 0.0))
        if name.startswith("n_sl_n"):
            return float(values.get(_sdbc_var_key("sl", int(name.split("_n")[-1])), 0.0))
        if name.startswith("n_fa_n"):
            return float(values.get(_sdbc_var_key("fa", int(name.split("_n")[-1])), 0.0))
        if name == "alpha":
            return float(values.get("alpha", 0.0))
        if name.startswith("lambda_"):
            return float(values.get(_sdbc_var_key("lambda", name.split("lambda_", 1)[1]), 0.0))
        return 0.0

    return _evaluate_linear_expression_from_values(master.total_objective_expression, getter)


def _sdbc_price_relaxed_point_rows(
    args: argparse.Namespace,
    *,
    output_root: Path,
    instance,
    master,
    point_values: Mapping[str, float],
    prefix: str,
    max_rounds: int,
    persisted_global_signatures: set[str],
    prepared_initial_cuts: list[RestrictedMasterCut],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    added_global_count = 0
    lambda_values = {
        str(line_id): float(point_values.get(_sdbc_var_key("lambda", line_id), 0.0))
        for line_id in instance.sets.line_ids
    }
    forbidden_patterns: list[tuple[str, ...]] = []
    for pricing_rank in range(1, int(max_rounds) + 1):
        plan = FixedFirstStagePlan(
            z_by_bus={
                bus: max(0.0, min(1.0, float(point_values.get(_sdbc_var_key("z", bus), 0.0))))
                for bus in instance.sets.buses
            },
            n_sl_by_bus={
                bus: max(0.0, float(point_values.get(_sdbc_var_key("sl", bus), 0.0)))
                for bus in instance.sets.buses
            },
            n_fa_by_bus={
                bus: max(0.0, float(point_values.get(_sdbc_var_key("fa", bus), 0.0)))
                for bus in instance.sets.buses
            },
        )
        solution = SimpleNamespace(
            alpha_value=float(point_values.get("alpha", 0.0)),
            lambda_by_line_id=lambda_values,
            original_total_objective_value=_sdbc_objective_from_values(master, point_values),
        )
        _, pricing_solution = _full_support_pricing(
            instance,
            plan=plan,
            solution=solution,
            forbidden_outage_patterns=forbidden_patterns,
            omega_bound_upper=float(args.omega_bound_upper),
            time_limit_seconds=float(args.sdbc_root_pricing_time_limit_seconds),
            mip_gap=float(args.separation_mip_gap),
            model_name=(
                f"{prefix}_k{int(instance.ambiguity.k_max_outages)}_"
                f"pricing_{pricing_rank:03d}"
            ),
            log_to_console=bool(args.log_to_console),
        )
        active_lines = tuple(_active_outage_lines(pricing_solution.delta_by_line_id))
        violation_bound = max(
            0.0,
            float(
                pricing_solution.obj_bound
                if pricing_solution.obj_bound is not None
                else (pricing_solution.objective_value or 0.0)
            ),
        )
        audit_rows.append(
            {
                "stage": prefix,
                "pricing_rank": pricing_rank,
                "pricing_status": pricing_solution.model_status,
                "pricing_violation_bound": violation_bound,
                "active_lines": ";".join(active_lines),
            }
        )
        if pricing_solution.objective_value is None or violation_bound <= float(args.sdbc_pricing_cut_epsilon):
            break
        outage = build_fixed_outage_vector(
            instance,
            by_line_id={
                line_id: int(line_id in active_lines)
                for line_id in instance.sets.line_ids
            },
        )
        cut_result = generate_structured_cut_from_decompositions(
            instance,
            plan=plan,
            outage=outage,
            samplewise_decompositions_by_scenario={
                scenario_id: sample.samplewise_decomposition
                for scenario_id, sample in pricing_solution.samplewise_dual_solutions.items()
            },
            cut_id=f"{prefix}_cut_{pricing_rank:03d}",
            provenance=f"{prefix}_{pricing_rank:03d}",
            source_alpha=solution.alpha_value,
            source_lambda_by_line_id=solution.lambda_by_line_id,
            source_violation_value=pricing_solution.objective_value,
        )
        signature = str(cut_result.cut_signature_hash)
        if signature not in persisted_global_signatures:
            _add_global_cut_to_existing_master(master, cut_result.cut)
            prepared_initial_cuts.append(cut_result.cut)
            persisted_global_signatures.add(signature)
            added_global_count += 1
        rows.append(
            _sdbc_direct_row_from_cut(
                instance,
                cut=cut_result.cut,
                active_line_ids=active_lines,
                row_id=f"{prefix}_active_{pricing_rank:03d}",
                source=f"{prefix}_active",
            )
        )
        top_subset = _sdbc_top_k_subset(instance, cut_result.cut, lambda_values)
        rows.append(
            _sdbc_direct_row_from_cut(
                instance,
                cut=cut_result.cut,
                active_line_ids=top_subset,
                row_id=f"{prefix}_topk_{pricing_rank:03d}",
                source=f"{prefix}_topk",
            )
        )
        forbidden_patterns.append(active_lines)
    return rows, audit_rows, added_global_count


def _run_sdbc_root_closure(
    args: argparse.Namespace,
    *,
    output_root: Path,
    instance,
    master,
    prepared_initial_cuts: list[RestrictedMasterCut],
    prepared_initial_outage_column_cuts: list[RestrictedMasterOutageColumnCut],
    persisted_global_signatures: set[str],
    objective_cutoff_rhs: float | None,
) -> dict[str, Any]:
    audit_rows: list[dict[str, Any]] = []
    root_values, root_lp_obj, root_lp_status = _sdbc_relaxation_solution(master)
    if not root_values:
        summary = {
            "enabled": True,
            "status": "root_lp_not_optimal",
            "root_lp_status": root_lp_status,
            "cut_count": 0,
        }
        _write_json(output_root / "sdbc_root_summary.json", summary)
        return summary

    lambda_values = {
        str(line_id): float(root_values.get(_sdbc_var_key("lambda", line_id), 0.0))
        for line_id in instance.sets.line_ids
    }
    registry_rows = _sdbc_registry_from_cuts(
        instance,
        master,
        cuts=prepared_initial_cuts,
        outage_column_cuts=prepared_initial_outage_column_cuts,
        lambda_values=lambda_values,
        max_rows=int(args.sdbc_max_registry_rows),
    )
    if objective_cutoff_rhs is not None:
        cutoff_row = _sdbc_target_cutoff_row(
            instance,
            master,
            cutoff_rhs=float(objective_cutoff_rhs),
        )
        if cutoff_row is not None:
            registry_rows.insert(0, cutoff_row)
            registry_rows = registry_rows[: int(args.sdbc_max_registry_rows)]
    priced_cut_count = 0
    forbidden_patterns: list[tuple[str, ...]] = []
    for pricing_rank in range(1, int(args.sdbc_root_pricing_rounds) + 1):
        plan = FixedFirstStagePlan(
            z_by_bus={
                bus: max(0.0, min(1.0, float(root_values.get(_sdbc_var_key("z", bus), 0.0))))
                for bus in instance.sets.buses
            },
            n_sl_by_bus={
                bus: max(0.0, float(root_values.get(_sdbc_var_key("sl", bus), 0.0)))
                for bus in instance.sets.buses
            },
            n_fa_by_bus={
                bus: max(0.0, float(root_values.get(_sdbc_var_key("fa", bus), 0.0)))
                for bus in instance.sets.buses
            },
        )
        solution = SimpleNamespace(
            alpha_value=float(root_values.get("alpha", 0.0)),
            lambda_by_line_id=lambda_values,
            original_total_objective_value=_evaluate_linear_expression_from_values(
                master.total_objective_expression,
                lambda var: root_values.get(_sdbc_var_key("z", int(var.VarName.split("_n")[-1])), 0.0)
                if var.VarName.startswith("z_n")
                else root_values.get(_sdbc_var_key("sl", int(var.VarName.split("_n")[-1])), 0.0)
                if var.VarName.startswith("n_sl_n")
                else root_values.get(_sdbc_var_key("fa", int(var.VarName.split("_n")[-1])), 0.0)
                if var.VarName.startswith("n_fa_n")
                else root_values.get("alpha", 0.0)
                if var.VarName == "alpha"
                else root_values.get(_sdbc_var_key("lambda", var.VarName.split("lambda_", 1)[1]), 0.0)
                if var.VarName.startswith("lambda_")
                else 0.0,
            ),
        )
        _, pricing_solution = _full_support_pricing(
            instance,
            plan=plan,
            solution=solution,
            forbidden_outage_patterns=forbidden_patterns,
            omega_bound_upper=float(args.omega_bound_upper),
            time_limit_seconds=float(args.sdbc_root_pricing_time_limit_seconds),
            mip_gap=float(args.separation_mip_gap),
            model_name=f"sdbc_root_k{int(instance.ambiguity.k_max_outages)}_pricing_{pricing_rank:03d}",
            log_to_console=bool(args.log_to_console),
        )
        active_lines = tuple(_active_outage_lines(pricing_solution.delta_by_line_id))
        violation_bound = max(
            0.0,
            float(
                pricing_solution.obj_bound
                if pricing_solution.obj_bound is not None
                else (pricing_solution.objective_value or 0.0)
            ),
        )
        audit_rows.append(
            {
                "stage": "root_pricing",
                "pricing_rank": pricing_rank,
                "pricing_status": pricing_solution.model_status,
                "pricing_violation_bound": violation_bound,
                "active_lines": ";".join(active_lines),
            }
        )
        if pricing_solution.objective_value is None or violation_bound <= float(args.sdbc_pricing_cut_epsilon):
            break
        outage = build_fixed_outage_vector(
            instance,
            by_line_id={
                line_id: int(line_id in active_lines)
                for line_id in instance.sets.line_ids
            },
        )
        cut_result = generate_structured_cut_from_decompositions(
            instance,
            plan=plan,
            outage=outage,
            samplewise_decompositions_by_scenario={
                scenario_id: sample.samplewise_decomposition
                for scenario_id, sample in pricing_solution.samplewise_dual_solutions.items()
            },
            cut_id=f"sdbc_root_pricing_cut_{pricing_rank:03d}",
            provenance=f"sdbc_root_pricing_{pricing_rank:03d}",
            source_alpha=solution.alpha_value,
            source_lambda_by_line_id=solution.lambda_by_line_id,
            source_violation_value=pricing_solution.objective_value,
        )
        signature = str(cut_result.cut_signature_hash)
        if signature not in persisted_global_signatures:
            _add_global_cut_to_existing_master(master, cut_result.cut)
            prepared_initial_cuts.append(cut_result.cut)
            persisted_global_signatures.add(signature)
            priced_cut_count += 1
        registry_rows.append(
            _sdbc_direct_row_from_cut(
                instance,
                cut=cut_result.cut,
                active_line_ids=active_lines,
                row_id=f"sdbc_priced_active_{pricing_rank:03d}",
                source="sdbc_root_priced_active",
            )
        )
        top_subset = _sdbc_top_k_subset(instance, cut_result.cut, lambda_values)
        registry_rows.append(
            _sdbc_direct_row_from_cut(
                instance,
                cut=cut_result.cut,
                active_line_ids=top_subset,
                row_id=f"sdbc_priced_topk_{pricing_rank:03d}",
                source="sdbc_root_priced_topk",
            )
        )
        forbidden_patterns.append(active_lines)
        if len(registry_rows) >= int(args.sdbc_max_registry_rows):
            registry_rows = registry_rows[: int(args.sdbc_max_registry_rows)]
            break

    split_candidates: list[tuple[str, int, float]] = []
    for bus in instance.sets.buses:
        for kind in ("z", "sl", "fa"):
            key = _sdbc_var_key(kind, bus)
            value = float(root_values.get(key, 0.0))
            nearest = round(value)
            frac = abs(value - nearest)
            if frac <= float(args.sdbc_fractionality_tolerance):
                continue
            q = int(value // 1)
            split_candidates.append((key, q, min(value - q, q + 1 - value)))
    split_candidates.sort(key=lambda item: item[2], reverse=True)
    split_candidates = split_candidates[: int(args.sdbc_max_splits)]

    cut_count = 0
    cglp_rows: list[dict[str, Any]] = []
    for split_index, (split_key, split_q, fractionality) in enumerate(split_candidates, start=1):
        split_registry_rows = list(registry_rows)
        side_global_added = 0
        if int(args.sdbc_side_rounds) > 0:
            for side in ("left", "right"):
                side_values, side_obj, side_status = _sdbc_relaxation_solution(
                    master,
                    side_split_key=split_key,
                    side=side,
                    split_q=split_q,
                    time_limit_seconds=float(args.sdbc_side_lp_time_limit_seconds),
                )
                audit_rows.append(
                    {
                        "stage": "sdbc_side_lp",
                        "split_index": split_index,
                        "split_key": split_key,
                        "split_q": split_q,
                        "side": side,
                        "side_status": side_status,
                        "side_obj": side_obj,
                    }
                )
                if not side_values:
                    continue
                side_rows, side_audit_rows, side_added = _sdbc_price_relaxed_point_rows(
                    args,
                    output_root=output_root,
                    instance=instance,
                    master=master,
                    point_values=side_values,
                    prefix=f"sdbc_side_{split_index:03d}_{side}",
                    max_rounds=int(args.sdbc_side_rounds),
                    persisted_global_signatures=persisted_global_signatures,
                    prepared_initial_cuts=prepared_initial_cuts,
                )
                split_registry_rows.extend(side_rows)
                audit_rows.extend(side_audit_rows)
                side_global_added += int(side_added)
        result = _solve_sdbc_cglp(
            rows=split_registry_rows[: int(args.sdbc_max_registry_rows)],
            split_key=split_key,
            split_q=split_q,
            point_values=root_values,
            time_limit_seconds=float(args.sdbc_cglp_time_limit_seconds),
            violation_tolerance=float(args.sdbc_violation_tolerance),
        )
        row = {
            "stage": "sdbc_cglp",
            "split_index": split_index,
            "split_key": split_key,
            "split_q": split_q,
            "fractionality": fractionality,
            "accepted": bool(result.get("accepted", False)),
            "status": result.get("status", ""),
            "reason": result.get("reason", ""),
            "violation": result.get("violation", ""),
            "rhs": result.get("rhs", ""),
            "lhs_at_point": result.get("lhs_at_point", ""),
            "nonzero_coeff_count": len(dict(result.get("coeffs", {}))),
            "side_global_added": side_global_added,
            "split_registry_row_count": len(split_registry_rows[: int(args.sdbc_max_registry_rows)]),
        }
        audit_rows.append(row)
        if not bool(result.get("accepted", False)):
            continue
        cut_id = f"sdbc_split_{split_index:03d}_{split_key.replace(':', '_')}"
        constr_name = _safe_gurobi_name("sdbc_split_cut", cut_id)
        master.model.addConstr(
            _sdbc_linear_expr(master, dict(result["coeffs"])) >= float(result["rhs"]),
            name=constr_name,
        )
        cglp_rows.append(
            {
                "cut_id": cut_id,
                "split_key": split_key,
                "split_q": split_q,
                "rhs": float(result["rhs"]),
                "violation": float(result["violation"]),
                "constraint_name": constr_name,
                "coeffs": json.dumps(dict(result["coeffs"]), sort_keys=True),
                "reconstruction": json.dumps(dict(result.get("reconstruction", {})), sort_keys=True),
            }
        )
        cut_count += 1
        if cut_count >= int(args.sdbc_max_cuts):
            break
    master.model.update()
    after_values, after_lp_obj, after_lp_status = _sdbc_relaxation_solution(master)
    summary = {
        "enabled": True,
        "pro_response_tex": "/Users/shixinliu/Downloads/evcs_dro_k16_lower_bound_split_bpc_next_step.tex",
        "status": "completed",
        "root_lp_obj_before": root_lp_obj,
        "root_lp_obj_after": after_lp_obj,
        "root_lp_status": root_lp_status,
        "root_lp_status_after": after_lp_status,
        "root_lp_lift": (
            None if root_lp_obj is None or after_lp_obj is None else float(after_lp_obj) - float(root_lp_obj)
        ),
        "registry_row_count": len(registry_rows),
        "root_priced_global_cut_count": priced_cut_count,
        "side_pricing_rounds": int(args.sdbc_side_rounds),
        "split_candidate_count": len(split_candidates),
        "cut_count": cut_count,
        "audit_path": str(output_root / "sdbc_root_audit.csv"),
        "cut_path": str(output_root / "sdbc_split_cuts.csv"),
    }
    _write_csv(output_root / "sdbc_root_audit.csv", audit_rows)
    _write_csv(output_root / "sdbc_split_cuts.csv", cglp_rows)
    _write_json(output_root / "sdbc_root_summary.json", summary)
    return summary


def _fullrow_expr_to_coeffs(model, expr: Any) -> dict[str, float]:
    coeffs: dict[str, float] = {}
    if hasattr(expr, "size") and hasattr(expr, "getVar") and hasattr(expr, "getCoeff"):
        for idx in range(int(expr.size())):
            var = expr.getVar(idx)
            coeff = float(expr.getCoeff(idx))
            if abs(coeff) <= 1e-12:
                continue
            coeffs[var.VarName] = coeffs.get(var.VarName, 0.0) + coeff
    return {key: value for key, value in coeffs.items() if abs(value) > 1e-12}


def _fullrow_relaxation_snapshot(
    master,
    *,
    time_limit_seconds: float,
) -> tuple[Any | None, dict[str, float], float | None, str]:
    master.model.update()
    relaxation = master.model.relax()
    relaxation.Params.OutputFlag = 0
    relaxation.Params.DualReductions = 0
    if float(time_limit_seconds) > 0:
        relaxation.Params.TimeLimit = float(time_limit_seconds)
    relaxation.optimize()
    status = _status_name(int(relaxation.Status))
    if relaxation.Status != GRB.OPTIMAL:
        return relaxation, {}, None, status
    values = {var.VarName: float(var.X) for var in relaxation.getVars()}
    return relaxation, values, float(relaxation.ObjVal), status


def _fullrow_converted_constraint_rows(
    relaxation,
    values: Mapping[str, float],
    *,
    max_rows: int,
    tight_tolerance: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[tuple[tuple[float, float, str], dict[str, Any], dict[str, Any]]] = []

    def priority_for(name: str, residual: float) -> tuple[float, float, str]:
        lower = name.lower()
        if "safe_tau" in lower or "objective_cutoff" in lower:
            return (0.0, abs(residual), name)
        if lower.startswith("eq11") or lower.startswith("eq12") or "first_stage" in lower:
            return (1.0, abs(residual), name)
        if "eq39" in lower or "nccg" in lower or "support" in lower or "outage" in lower:
            return (2.0, abs(residual), name)
        if abs(residual) <= float(tight_tolerance):
            return (3.0, abs(residual), name)
        return (10.0, abs(residual), name)

    for constr in relaxation.getConstrs():
        name = constr.ConstrName
        rhs = float(constr.RHS)
        if abs(rhs) >= GRB.INFINITY / 2:
            continue
        expr = relaxation.getRow(constr)
        coeffs = _fullrow_expr_to_coeffs(relaxation, expr)
        if not coeffs:
            continue
        activity = sum(float(coeff) * float(values.get(var_name, 0.0)) for var_name, coeff in coeffs.items())
        sense = str(constr.Sense)
        converted: list[tuple[dict[str, float], float, str, float]] = []
        if sense == ">":
            converted.append((coeffs, rhs, "ge", activity - rhs))
        elif sense == "<":
            converted.append(({key: -value for key, value in coeffs.items()}, -rhs, "le_as_ge", rhs - activity))
        elif sense == "=":
            converted.append((coeffs, rhs, "eq_ge", activity - rhs))
            converted.append(({key: -value for key, value in coeffs.items()}, -rhs, "eq_le_as_ge", rhs - activity))
        for direction_index, (row_coeffs, row_rhs, direction, residual) in enumerate(converted, start=1):
            row = {
                "row_id": f"{name}#{direction_index}",
                "coeffs": row_coeffs,
                "rhs": float(row_rhs),
                "source": "full_model_constraint",
            }
            meta = {
                "row_id": row["row_id"],
                "constraint_name": name,
                "sense": sense,
                "direction": direction,
                "rhs": rhs,
                "converted_rhs": row_rhs,
                "activity": activity,
                "converted_residual": residual,
                "nonzero_count": len(row_coeffs),
                "selected": False,
                "selection_reason": "",
            }
            candidates.append((priority_for(name, residual), row, meta))

    candidates.sort(key=lambda item: item[0])
    max_rows_int = int(max_rows)
    target_rows = [item for item in candidates if item[0][0] == 0.0]
    first_stage_rows = [item for item in candidates if item[0][0] == 1.0]
    support_rows = [item for item in candidates if item[0][0] == 2.0]
    tight_rows = [item for item in candidates if item[0][0] == 3.0]
    other_rows = [item for item in candidates if item[0][0] not in {0.0, 1.0, 2.0, 3.0}]
    selected: list[tuple[tuple[float, float, str], dict[str, Any], dict[str, Any]]] = []

    def take(items, quota: int) -> None:
        remaining = max_rows_int - len(selected)
        if remaining <= 0 or quota <= 0:
            return
        selected.extend(items[: min(int(quota), remaining)])

    take(target_rows, len(target_rows))
    take(first_stage_rows, min(len(first_stage_rows), max(20, max_rows_int // 5)))
    take(support_rows, min(len(support_rows), max(20, max_rows_int // 3)))
    take(tight_rows, max_rows_int - len(selected))
    take(other_rows, max_rows_int - len(selected))
    rows = [row for _priority, row, _meta in selected]
    metadata = []
    selected_ids = {row["row_id"] for row in rows}
    for priority, row, meta in candidates:
        meta = dict(meta)
        meta["priority"] = priority[0]
        meta["priority_residual"] = priority[1]
        if row["row_id"] in selected_ids:
            meta["selected"] = True
            meta["selection_reason"] = "priority_or_tight"
        metadata.append(meta)
    return rows, metadata


def _fullrow_add_bound_rows(
    relaxation,
    rows: list[dict[str, Any]],
    *,
    required_var_names: set[str],
    bound_scope: str = "all_selected",
) -> list[dict[str, Any]]:
    scope = str(bound_scope).strip().lower().replace("-", "_")
    if scope == "none":
        return rows
    involved = set(required_var_names)
    if scope == "all_selected":
        for row in rows:
            involved.update(str(key) for key in dict(row["coeffs"]).keys())
    elif scope == "split_only":
        involved = set(required_var_names)
    else:
        raise ValueError(f"Unsupported full-row SDBC bound scope: {bound_scope}")
    bound_rows: list[dict[str, Any]] = []
    vars_by_name = {var.VarName: var for var in relaxation.getVars()}
    for name in sorted(involved):
        var = vars_by_name.get(name)
        if var is None:
            continue
        if float(var.LB) > -GRB.INFINITY / 2:
            bound_rows.append(
                {
                    "row_id": f"lb#{name}",
                    "coeffs": {name: 1.0},
                    "rhs": float(var.LB),
                    "source": "var_lb",
                }
            )
        if float(var.UB) < GRB.INFINITY / 2:
            bound_rows.append(
                {
                    "row_id": f"ub#{name}",
                    "coeffs": {name: -1.0},
                    "rhs": -float(var.UB),
                    "source": "var_ub",
                }
            )
    return rows + bound_rows


def _fullrow_split_candidates(
    master,
    values: Mapping[str, float],
    *,
    max_single: int,
    include_composite: bool,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for bus, var in master.first_stage.z_by_bus.items():
        value = float(values.get(var.VarName, 0.0))
        frac = abs(value - round(value))
        if frac > 1.0e-5:
            candidates.append(
                {
                    "split_id": f"single_{var.VarName}",
                    "coeffs": {var.VarName: 1.0},
                    "h": int(value // 1),
                    "fractionality": min(value - int(value // 1), int(value // 1) + 1 - value),
                    "family": "single_z",
                }
            )
    for bus, var in master.first_stage.n_sl_by_bus.items():
        value = float(values.get(var.VarName, 0.0))
        frac = abs(value - round(value))
        if frac > 1.0e-5:
            candidates.append(
                {
                    "split_id": f"single_{var.VarName}",
                    "coeffs": {var.VarName: 1.0},
                    "h": int(value // 1),
                    "fractionality": min(value - int(value // 1), int(value // 1) + 1 - value),
                    "family": "single_sl",
                }
            )
    for bus, var in master.first_stage.n_fa_by_bus.items():
        value = float(values.get(var.VarName, 0.0))
        frac = abs(value - round(value))
        if frac > 1.0e-5:
            candidates.append(
                {
                    "split_id": f"single_{var.VarName}",
                    "coeffs": {var.VarName: 1.0},
                    "h": int(value // 1),
                    "fractionality": min(value - int(value // 1), int(value // 1) + 1 - value),
                    "family": "single_fa",
                }
            )
    candidates.sort(key=lambda row: float(row["fractionality"]), reverse=True)
    selected = candidates[: int(max_single)]
    if include_composite:
        z_vars = [var.VarName for var in master.first_stage.z_by_bus.values()]
        sl_vars = [var.VarName for var in master.first_stage.n_sl_by_bus.values()]
        fa_vars = [var.VarName for var in master.first_stage.n_fa_by_bus.values()]
        for family, var_names in (
            ("station_count", z_vars),
            ("slow_count", sl_vars),
            ("fast_count", fa_vars),
        ):
            total = sum(float(values.get(name, 0.0)) for name in var_names)
            frac = abs(total - round(total))
            if frac > 1.0e-5:
                h = int(total // 1)
                selected.append(
                    {
                        "split_id": family,
                        "coeffs": {name: 1.0 for name in var_names},
                        "h": h,
                        "fractionality": min(total - h, h + 1 - total),
                        "family": family,
                    }
                )
    return selected


def _solve_fullrow_cglp(
    *,
    rows: Sequence[Mapping[str, Any]],
    split_coeffs: Mapping[str, float],
    split_h: int,
    point_values: Mapping[str, float],
    time_limit_seconds: float,
    violation_tolerance: float,
) -> dict[str, Any]:
    keys = sorted(
        {
            str(key)
            for row in rows
            for key in dict(row["coeffs"]).keys()
        }
        | {str(key) for key in split_coeffs}
    )
    if not rows:
        return {"accepted": False, "reason": "empty_row_set"}
    model = Model("fullrow_sdbc_cglp")
    model.Params.OutputFlag = 0
    model.Params.TimeLimit = float(time_limit_seconds)
    c = {key: model.addVar(lb=-GRB.INFINITY, name=f"c_{idx}") for idx, key in enumerate(keys)}
    gamma = model.addVar(lb=-GRB.INFINITY, name="gamma")
    u_left = {idx: model.addVar(lb=0.0, name=f"uL_{idx}") for idx, _row in enumerate(rows)}
    u_right = {idx: model.addVar(lb=0.0, name=f"uR_{idx}") for idx, _row in enumerate(rows)}
    mu_left = model.addVar(lb=0.0, name="muL")
    mu_right = model.addVar(lb=0.0, name="muR")
    for key in keys:
        lhs_left = quicksum(
            float(dict(rows[idx]["coeffs"]).get(key, 0.0)) * u_left[idx]
            for idx in range(len(rows))
        )
        lhs_right = quicksum(
            float(dict(rows[idx]["coeffs"]).get(key, 0.0)) * u_right[idx]
            for idx in range(len(rows))
        )
        d_coeff = float(split_coeffs.get(key, 0.0))
        model.addConstr(c[key] == lhs_left - mu_left * d_coeff, name=f"left_c_{len(key)}_{len(model.getConstrs())}")
        model.addConstr(c[key] == lhs_right + mu_right * d_coeff, name=f"right_c_{len(key)}_{len(model.getConstrs())}")
    model.addConstr(
        gamma
        <= quicksum(float(rows[idx]["rhs"]) * u_left[idx] for idx in range(len(rows)))
        - float(split_h) * mu_left,
        name="left_gamma",
    )
    model.addConstr(
        gamma
        <= quicksum(float(rows[idx]["rhs"]) * u_right[idx] for idx in range(len(rows)))
        + float(split_h + 1) * mu_right,
        name="right_gamma",
    )
    model.addConstr(
        quicksum(u_left.values()) + quicksum(u_right.values()) + mu_left + mu_right == 1.0,
        name="normalization",
    )
    violation_expr = gamma - quicksum(
        c[key] * float(point_values.get(key, 0.0))
        for key in keys
    )
    model.setObjective(violation_expr, GRB.MAXIMIZE)
    model.optimize()
    status = _status_name(int(model.Status))
    if model.Status != GRB.OPTIMAL:
        return {"accepted": False, "status": status, "reason": "cglp_not_optimal"}
    violation = float(model.ObjVal)
    coeffs = {key: float(c[key].X) for key in keys if abs(float(c[key].X)) > 1.0e-9}
    lhs_at_point = sum(float(coeffs.get(key, 0.0)) * float(point_values.get(key, 0.0)) for key in coeffs)
    rhs = float(gamma.X)
    return {
        "accepted": bool(violation > float(violation_tolerance) and coeffs),
        "status": status,
        "violation": violation,
        "rhs": rhs,
        "lhs_at_point": lhs_at_point,
        "coeffs": coeffs,
        "mu_left": float(mu_left.X),
        "mu_right": float(mu_right.X),
        "u_left_sum": sum(float(var.X) for var in u_left.values()),
        "u_right_sum": sum(float(var.X) for var in u_right.values()),
    }


def _add_fullrow_cut_to_master(master, cut: Mapping[str, Any], *, cut_name: str) -> None:
    master.model.update()
    vars_by_name = {var.VarName: var for var in master.model.getVars()}
    expr = 0.0
    for name, coeff in dict(cut["coeffs"]).items():
        var = vars_by_name.get(str(name))
        if var is None:
            continue
        expr += float(coeff) * var
    master.model.addConstr(expr >= float(cut["rhs"]), name=_safe_gurobi_name("fullrow_sdbc", cut_name))


def _run_fullrow_sdbc_root_closure(
    args: argparse.Namespace,
    *,
    output_root: Path,
    master,
    target_cutoff_enabled: bool,
) -> dict[str, Any]:
    event_path = output_root / "fullrow_sdbc_events.jsonl"
    started_at = perf_counter()
    _append_jsonl(
        event_path,
        {
            "event": "fullrow_sdbc_start",
            "max_rows": int(args.fullrow_sdbc_max_rows),
            "max_single_splits": int(args.fullrow_sdbc_max_single_splits),
            "max_splits": int(args.fullrow_sdbc_max_splits),
            "max_cuts": int(args.fullrow_sdbc_max_cuts),
            "split_families": str(args.fullrow_sdbc_split_families),
            "bound_scope": str(args.fullrow_sdbc_bound_scope),
            "target_cutoff_enabled": bool(target_cutoff_enabled),
        },
    )
    relaxation, values, root_lp_obj, root_status = _fullrow_relaxation_snapshot(
        master,
        time_limit_seconds=float(args.fullrow_sdbc_lp_time_limit_seconds),
    )
    _append_jsonl(
        event_path,
        {
            "event": "fullrow_sdbc_root_lp_done",
            "elapsed_seconds": perf_counter() - started_at,
            "root_lp_status": root_status,
            "root_lp_obj": root_lp_obj,
        },
    )
    if relaxation is None or not values:
        summary = {
            "enabled": True,
            "status": "root_lp_not_optimal",
            "root_lp_status": root_status,
            "cut_count": 0,
            "event_path": str(event_path),
        }
        _write_json(output_root / "fullrow_sdbc_summary.json", summary)
        return summary
    splits = _fullrow_split_candidates(
        master,
        values,
        max_single=int(args.fullrow_sdbc_max_single_splits),
        include_composite=bool(args.fullrow_sdbc_composite_splits),
    )
    allowed_families = {
        item.strip()
        for item in str(args.fullrow_sdbc_split_families).split(",")
        if item.strip()
    }
    if allowed_families:
        splits = [split for split in splits if str(split.get("family", "")) in allowed_families]
    splits = splits[: int(args.fullrow_sdbc_max_splits)]
    _append_jsonl(
        event_path,
        {
            "event": "fullrow_sdbc_split_selection_done",
            "elapsed_seconds": perf_counter() - started_at,
            "split_count": len(splits),
            "split_ids": [str(split.get("split_id", "")) for split in splits],
            "split_families": [str(split.get("family", "")) for split in splits],
        },
    )
    required_vars = {str(key) for split in splits for key in dict(split["coeffs"]).keys()}
    base_rows, row_metadata = _fullrow_converted_constraint_rows(
        relaxation,
        values,
        max_rows=int(args.fullrow_sdbc_max_rows),
        tight_tolerance=float(args.fullrow_sdbc_tight_tolerance),
    )
    rows = _fullrow_add_bound_rows(
        relaxation,
        base_rows,
        required_var_names=required_vars,
        bound_scope=str(args.fullrow_sdbc_bound_scope),
    )
    _append_jsonl(
        event_path,
        {
            "event": "fullrow_sdbc_rows_ready",
            "elapsed_seconds": perf_counter() - started_at,
            "selected_model_row_count": len(base_rows),
            "row_count_with_bounds": len(rows),
            "bound_scope": str(args.fullrow_sdbc_bound_scope),
            "row_metadata_path": str(output_root / "fullrow_sdbc_row_metadata.csv"),
        },
    )
    cut_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    cut_count = 0
    for split_index, split in enumerate(splits, start=1):
        split_started_at = perf_counter()
        _append_jsonl(
            event_path,
            {
                "event": "fullrow_sdbc_cglp_start",
                "elapsed_seconds": split_started_at - started_at,
                "split_index": split_index,
                "split_id": split["split_id"],
                "family": split["family"],
                "h": split["h"],
                "fractionality": split["fractionality"],
                "row_count": len(rows),
            },
        )
        result = _solve_fullrow_cglp(
            rows=rows,
            split_coeffs=dict(split["coeffs"]),
            split_h=int(split["h"]),
            point_values=values,
            time_limit_seconds=float(args.fullrow_sdbc_cglp_time_limit_seconds),
            violation_tolerance=float(args.fullrow_sdbc_violation_tolerance),
        )
        _append_jsonl(
            event_path,
            {
                "event": "fullrow_sdbc_cglp_done",
                "elapsed_seconds": perf_counter() - started_at,
                "split_runtime_seconds": perf_counter() - split_started_at,
                "split_index": split_index,
                "split_id": split["split_id"],
                "family": split["family"],
                "accepted": bool(result.get("accepted", False)),
                "status": result.get("status", ""),
                "reason": result.get("reason", ""),
                "violation": result.get("violation", ""),
                "nonzero_coeff_count": len(dict(result.get("coeffs", {}))),
            },
        )
        audit_row = {
            "split_index": split_index,
            "split_id": split["split_id"],
            "family": split["family"],
            "h": split["h"],
            "fractionality": split["fractionality"],
            "accepted": bool(result.get("accepted", False)),
            "status": result.get("status", ""),
            "reason": result.get("reason", ""),
            "violation": result.get("violation", ""),
            "rhs": result.get("rhs", ""),
            "lhs_at_point": result.get("lhs_at_point", ""),
            "nonzero_coeff_count": len(dict(result.get("coeffs", {}))),
            "row_count": len(rows),
        }
        audit_rows.append(audit_row)
        if not bool(result.get("accepted", False)):
            continue
        cut_id = f"fullrow_sdbc_{split_index:03d}_{str(split['split_id']).replace(':', '_')}"
        cut_payload = {
            "cut_id": cut_id,
            "scope": "target_only" if target_cutoff_enabled else "canonical_global",
            "rhs": float(result["rhs"]),
            "coeffs": dict(result["coeffs"]),
        }
        _add_fullrow_cut_to_master(master, cut_payload, cut_name=cut_id)
        cut_rows.append(
            {
                "cut_id": cut_id,
                "scope": cut_payload["scope"],
                "split_id": split["split_id"],
                "family": split["family"],
                "h": split["h"],
                "violation": float(result["violation"]),
                "rhs": float(result["rhs"]),
                "lhs_at_point": float(result["lhs_at_point"]),
                "nonzero_coeff_count": len(dict(result["coeffs"])),
                "coeffs": json.dumps(dict(result["coeffs"]), sort_keys=True),
            }
        )
        cut_count += 1
        if cut_count >= int(args.fullrow_sdbc_max_cuts):
            break
    master.model.update()
    _relax_after, _values_after, root_lp_after, after_status = _fullrow_relaxation_snapshot(
        master,
        time_limit_seconds=float(args.fullrow_sdbc_lp_time_limit_seconds),
    )
    _append_jsonl(
        event_path,
        {
            "event": "fullrow_sdbc_root_lp_after_done",
            "elapsed_seconds": perf_counter() - started_at,
            "root_lp_status_after": after_status,
            "root_lp_obj_after": root_lp_after,
            "cut_count": cut_count,
        },
    )
    summary = {
        "enabled": True,
        "pro_response_tex": "/Users/shixinliu/Downloads/evcs_dro_k16_corrected_sdbc_closure.tex",
        "status": "completed",
        "scope": "target_only" if target_cutoff_enabled else "canonical_global",
        "root_lp_status": root_status,
        "root_lp_status_after": after_status,
        "root_lp_obj_before": root_lp_obj,
        "root_lp_obj_after": root_lp_after,
        "root_lp_lift": (
            None if root_lp_obj is None or root_lp_after is None else float(root_lp_after) - float(root_lp_obj)
        ),
        "selected_model_row_count": len(base_rows),
        "row_count_with_bounds": len(rows),
        "bound_scope": str(args.fullrow_sdbc_bound_scope),
        "split_candidate_count": len(splits),
        "cut_count": cut_count,
        "runtime_seconds": perf_counter() - started_at,
        "event_path": str(event_path),
        "audit_path": str(output_root / "fullrow_sdbc_audit.csv"),
        "cut_path": str(output_root / "fullrow_sdbc_cuts.csv"),
        "row_metadata_path": str(output_root / "fullrow_sdbc_row_metadata.csv"),
    }
    _write_csv(output_root / "fullrow_sdbc_audit.csv", audit_rows)
    _write_csv(output_root / "fullrow_sdbc_cuts.csv", cut_rows)
    _write_csv(output_root / "fullrow_sdbc_row_metadata.csv", row_metadata)
    _write_json(output_root / "fullrow_sdbc_summary.json", summary)
    return summary


def _add_lazy_direct_cut_variants(
    *,
    model,
    master,
    cut: RestrictedMasterCut,
    active_line_ids: Sequence[str],
    signature: str,
    seen_lazy_keys: set[tuple[tuple[str, ...], str]],
    subset_sizes: Sequence[int],
    enable_subset_cuts: bool,
) -> dict[str, Any]:
    variants = (
        _active_line_variants_for_cut(cut, active_line_ids, subset_sizes)
        if bool(enable_subset_cuts)
        else [tuple(str(line_id) for line_id in active_line_ids)]
    )
    added = 0
    duplicate = 0
    added_sizes: list[int] = []
    for variant in variants:
        lazy_key = (tuple(variant), signature)
        if lazy_key in seen_lazy_keys:
            duplicate += 1
            continue
        model.cbLazy(
            _direct_fixed_outage_temp_constr(
                master,
                cut=cut,
                active_line_ids=variant,
            )
        )
        seen_lazy_keys.add(lazy_key)
        added += 1
        added_sizes.append(len(variant))
    return {
        "added": added,
        "duplicate": duplicate,
        "variant_count": len(variants),
        "added_sizes": ";".join(str(size) for size in added_sizes),
    }


def _capture_target_incumbents(
    instance,
    master,
    *,
    max_candidates: int,
    min_candidates: int,
    window_seconds: float,
    target_search_objective: str,
) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    seen_plan_signatures: set[tuple[tuple[int, int, int], ...]] = set()
    started = perf_counter()

    def _callback(model, where):
        if where != GRB.Callback.MIPSOL:
            return
        z_by_bus = {
            bus: int(round(float(model.cbGetSolution(var))))
            for bus, var in master.first_stage.z_by_bus.items()
        }
        n_sl_by_bus = {
            bus: int(round(float(model.cbGetSolution(var))))
            for bus, var in master.first_stage.n_sl_by_bus.items()
        }
        n_fa_by_bus = {
            bus: int(round(float(model.cbGetSolution(var))))
            for bus, var in master.first_stage.n_fa_by_bus.items()
        }
        signature = tuple(
            (int(bus), int(z_by_bus[bus]), int(n_sl_by_bus[bus]), int(n_fa_by_bus[bus]))
            for bus in master.ordered_buses
        )
        if signature in seen_plan_signatures:
            return
        seen_plan_signatures.add(signature)
        plan = build_fixed_first_stage_plan(
            instance,
            z_by_bus=z_by_bus,
            n_sl_by_bus=n_sl_by_bus,
            n_fa_by_bus=n_fa_by_bus,
        )
        original_objective = _callback_original_objective_value(model, master)
        captured.append(
            {
                "plan": plan,
                "solution": SimpleNamespace(
                    alpha_value=float(model.cbGetSolution(master.alpha_var)),
                    lambda_by_line_id={
                        str(line_id): max(0.0, float(model.cbGetSolution(var)))
                        for line_id, var in master.lambda_by_line_id.items()
                    },
                    original_total_objective_value=float(original_objective),
                ),
            }
        )
        elapsed = perf_counter() - started
        if len(captured) >= int(max_candidates) or (
            len(captured) >= int(min_candidates) and elapsed >= float(window_seconds)
        ):
            model.terminate()

    master.model.optimize(_callback)
    for capture_index, item in enumerate(captured):
        item["pool_index"] = int(capture_index)
    return sorted(
        captured,
        key=lambda item: float(item["solution"].original_total_objective_value),
        reverse=True,
    )


def _target_pool_candidates(instance, master, *, max_solutions: int) -> list[dict[str, Any]]:
    """Extract target-level pool candidates without treating them as lower bounds."""

    sol_count = min(int(getattr(master.model, "SolCount", 0)), int(max_solutions))
    candidates: list[dict[str, Any]] = []
    for pool_index in range(sol_count):
        master.model.Params.SolutionNumber = int(pool_index)
        plan = build_fixed_first_stage_plan(
            instance,
            z_by_bus={
                bus: int(round(float(var.Xn)))
                for bus, var in master.first_stage.z_by_bus.items()
            },
            n_sl_by_bus={
                bus: int(round(float(var.Xn)))
                for bus, var in master.first_stage.n_sl_by_bus.items()
            },
            n_fa_by_bus={
                bus: int(round(float(var.Xn)))
                for bus, var in master.first_stage.n_fa_by_bus.items()
            },
        )
        candidates.append(
            {
                "pool_index": int(pool_index),
                "plan": plan,
                "solution": SimpleNamespace(
                    alpha_value=float(master.alpha_var.Xn),
                    lambda_by_line_id={
                        str(line_id): max(0.0, float(var.Xn))
                        for line_id, var in master.lambda_by_line_id.items()
                    },
                    original_total_objective_value=_pool_original_objective_value(master),
                ),
            }
        )
    return candidates


def _full_support_pricing(
    instance,
    *,
    plan: FixedFirstStagePlan,
    solution,
    forbidden_outage_patterns: Sequence[Sequence[str]] | None = None,
    omega_bound_upper: float,
    time_limit_seconds: float,
    mip_gap: float,
    model_name: str,
    log_to_console: bool,
):
    omega_bounds = {
        str(line_id): (0.0, float(omega_bound_upper))
        for line_id in instance.sets.line_ids
    }
    return solve_separation_milp(
        instance,
        plan=plan,
        alpha=float(solution.alpha_value),
        lambda_by_line_id=solution.lambda_by_line_id,
        omega_bounds_by_line_id=omega_bounds,
        budget_k=int(instance.ambiguity.k_max_outages),
        scenario_ids=instance.sets.loaded_disaster_scenarios,
        forbidden_outage_patterns=forbidden_outage_patterns,
        model_name=model_name,
        time_limit_seconds=float(time_limit_seconds),
        mip_gap=float(mip_gap),
        require_optimal=False,
        log_to_console=log_to_console,
    )


def _fix_first_stage_for_plan(
    instance,
    plan: FixedFirstStagePlan,
    *,
    attach_objective: bool,
    model_name: str,
):
    first_stage = build_first_stage_model(
        instance,
        model_name=model_name,
        log_to_console=False,
        attach_objective=attach_objective,
    )
    for bus in instance.sets.buses:
        first_stage.model.addConstr(
            first_stage.z_by_bus[bus] == float(plan.z_by_bus[bus]),
            name=f"fix_z_n{bus}",
        )
        first_stage.model.addConstr(
            first_stage.n_sl_by_bus[bus] == float(plan.n_sl_by_bus[bus]),
            name=f"fix_n_sl_n{bus}",
        )
        first_stage.model.addConstr(
            first_stage.n_fa_by_bus[bus] == float(plan.n_fa_by_bus[bus]),
            name=f"fix_n_fa_n{bus}",
        )
    first_stage.model.update()
    return first_stage


def _fixed_plan_normal_replay(instance, plan: FixedFirstStagePlan) -> dict[str, Any]:
    first_stage = _fix_first_stage_for_plan(
        instance,
        plan,
        attach_objective=True,
        model_name="fixed_plan_nogood_construction",
    )
    first_stage.model.optimize()
    first_stage_solution = extract_first_stage_solution(first_stage)
    if first_stage_solution.model_status != "OPTIMAL":
        raise RuntimeError("Fixed-plan construction replay did not solve to OPTIMAL.")

    normal_cost_by_scenario: dict[int, float] = {}
    for scenario_id in instance.sets.loaded_normal_scenarios:
        fixed = _fix_first_stage_for_plan(
            instance,
            plan,
            attach_objective=False,
            model_name=f"fixed_plan_nogood_normal_s{int(scenario_id)}",
        )
        block = build_normal_operation_block(
            instance,
            first_stage=fixed,
            scenario_id=int(scenario_id),
            model_name=f"fixed_plan_nogood_normal_s{int(scenario_id)}",
            log_to_console=False,
            attach_objective=True,
        )
        block.model.optimize()
        solution = extract_normal_operation_solution(block)
        if solution.model_status != "OPTIMAL":
            raise RuntimeError(
                f"Fixed-plan normal replay failed for scenario {scenario_id}."
            )
        normal_cost_by_scenario[int(scenario_id)] = float(solution.normal_objective_value)
    averaged_normal_cost = float(
        (1.0 - float(instance.economics.pi_f))
        / len(instance.sets.loaded_normal_scenarios)
        * sum(normal_cost_by_scenario.values())
    )
    return {
        "construction_cost": float(first_stage_solution.construction_cost_value),
        "averaged_normal_cost": averaged_normal_cost,
        "unweighted_average_normal_cost": float(
            sum(normal_cost_by_scenario.values()) / len(normal_cost_by_scenario)
        ),
        "normal_cost_by_scenario": {
            str(key): float(value) for key, value in sorted(normal_cost_by_scenario.items())
        },
    }


def _solve_fixed_plan_restricted_moment_dual(
    instance,
    *,
    plan: FixedFirstStagePlan,
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    max_columns: int,
) -> dict[str, Any]:
    best_by_pattern: dict[tuple[str, ...], tuple[float, RestrictedMasterOutageColumnCut]] = {}
    for row in outage_column_cuts:
        pattern = tuple(row.active_line_ids)
        value = _rowwise_cut_source_value(row, source_plan=plan)
        incumbent = best_by_pattern.get(pattern)
        if incumbent is None or value > incumbent[0]:
            best_by_pattern[pattern] = (float(value), row)
    ranked = sorted(best_by_pattern.values(), key=lambda item: item[0], reverse=True)
    if int(max_columns) > 0:
        ranked = ranked[: int(max_columns)]
    if not ranked:
        return {
            "status": "NO_COLUMNS",
            "restricted_w_lb": None,
            "column_count": 0,
            "max_column_value": None,
        }

    model = Model("fixed_plan_restricted_moment_dual")
    model.Params.OutputFlag = 0
    alpha = model.addVar(lb=float(instance.economics.alpha_min), name="alpha")
    lambda_by_line_id = {
        line_id: model.addVar(lb=0.0, name=f"lambda_{line_id}")
        for line_id in instance.sets.line_ids
    }
    for index, (value, row) in enumerate(ranked):
        model.addConstr(
            alpha + quicksum(lambda_by_line_id[line_id] for line_id in row.active_line_ids)
            >= float(value),
            name=f"fixed_plan_col_{index:05d}",
        )
    fp_by_line_id = _line_fp_by_id(instance)
    model.setObjective(
        alpha
        + quicksum(
            float(fp_by_line_id[line_id]) * lambda_by_line_id[line_id]
            for line_id in instance.sets.line_ids
        ),
        GRB.MINIMIZE,
    )
    model.optimize()
    status = _status_name(int(model.Status))
    if int(model.Status) != GRB.OPTIMAL:
        return {
            "status": status,
            "restricted_w_lb": None,
            "column_count": len(ranked),
            "max_column_value": float(ranked[0][0]),
        }
    return {
        "status": status,
        "restricted_w_lb": float(model.ObjVal),
        "alpha": float(alpha.X),
        "lambda_by_line_id": {
            str(line_id): max(0.0, float(lambda_by_line_id[line_id].X))
            for line_id in instance.sets.line_ids
        },
        "lambda_fp": float(
            sum(float(fp_by_line_id[line_id]) * float(lambda_by_line_id[line_id].X)
                for line_id in instance.sets.line_ids)
        ),
        "column_count": len(ranked),
        "max_column_value": float(ranked[0][0]),
        "positive_lambda_count": sum(
            1 for line_id in instance.sets.line_ids if float(lambda_by_line_id[line_id].X) > 1e-8
        ),
    }


def _fixed_plan_objective_lb(
    instance,
    *,
    normal_replay: Mapping[str, Any],
    restricted_w_lb: float,
) -> float:
    multipliers = instance.economics.objective_multipliers
    return float(
        float(multipliers.cons) * float(normal_replay["construction_cost"])
        + float(multipliers.normal) * float(normal_replay["averaged_normal_cost"])
        + float(multipliers.disaster)
        * float(instance.economics.pi_f)
        * float(restricted_w_lb)
    )


def _fixed_plan_lb_oracle(
    instance,
    *,
    plan: FixedFirstStagePlan,
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    tau: float,
    max_columns: int,
    pricing_rounds: int = 0,
    pricing_time_limit_seconds: float = 300.0,
    pricing_mip_gap: float = 0.02,
    omega_bound_upper: float = 2.0e7,
    epsilon_price: float = 100.0,
    log_to_console: bool = False,
    trace_path: Path | None = None,
    cut_id_prefix: str = "fixed_plan_lb",
) -> dict[str, Any]:
    normal_replay = _fixed_plan_normal_replay(instance, plan)
    working_rows = list(outage_column_cuts)
    generated_rows: list[RestrictedMasterOutageColumnCut] = []
    seen_local_keys = {
        (tuple(row.active_line_ids), compute_cut_signature_hash(row.cut))
        for row in working_rows
    }
    pricing_events: list[dict[str, Any]] = []
    last_fixed_dual: dict[str, Any] | None = None
    last_objective_lb: float | None = None
    for round_index in range(0, int(pricing_rounds) + 1):
        fixed_dual = _solve_fixed_plan_restricted_moment_dual(
            instance,
            plan=plan,
            outage_column_cuts=working_rows,
            max_columns=max_columns,
        )
        last_fixed_dual = fixed_dual
        if fixed_dual.get("restricted_w_lb") is None:
            return {
                "status": fixed_dual["status"],
                "proved_above_tau": False,
                "tau": float(tau),
                "normal_replay": normal_replay,
                "fixed_dual": fixed_dual,
                "pricing_events": pricing_events,
                "local_generated_column_count": max(0, len(working_rows) - len(outage_column_cuts)),
            }
        objective_lb = _fixed_plan_objective_lb(
            instance,
            normal_replay=normal_replay,
            restricted_w_lb=float(fixed_dual["restricted_w_lb"]),
        )
        last_objective_lb = objective_lb
        if objective_lb > float(tau):
            _append_jsonl(
                trace_path,
                {
                    "event": "proved_above_tau",
                    "pricing_round": round_index,
                    "fixed_plan_objective_lb": objective_lb,
                    "margin_above_tau": float(objective_lb - float(tau)),
                    "restricted_w_lb": float(fixed_dual["restricted_w_lb"]),
                },
            )
            return {
                "status": "PROVED_ABOVE_TAU_BY_FIXED_PLAN_LB",
                "proved_above_tau": True,
                "tau": float(tau),
                "fixed_plan_objective_lb": objective_lb,
                "margin_above_tau": float(objective_lb - float(tau)),
                "normal_replay": normal_replay,
                "fixed_dual": fixed_dual,
                "pricing_events": pricing_events,
                "pricing_rounds_used": round_index,
                "local_generated_column_count": max(0, len(working_rows) - len(outage_column_cuts)),
                "_generated_outage_column_cuts": generated_rows,
            }
        if round_index >= int(pricing_rounds):
            break
        _, separation_solution = _full_support_pricing(
            instance,
            plan=plan,
            solution=SimpleNamespace(
                alpha_value=float(fixed_dual["alpha"]),
                lambda_by_line_id=dict(fixed_dual["lambda_by_line_id"]),
            ),
            forbidden_outage_patterns=None,
            omega_bound_upper=float(omega_bound_upper),
            time_limit_seconds=float(pricing_time_limit_seconds),
            mip_gap=float(pricing_mip_gap),
            model_name=f"fixed_plan_lb_pricing_{round_index + 1:03d}",
            log_to_console=log_to_console,
        )
        violation_value = max(0.0, float(separation_solution.objective_value or 0.0))
        violation_bound = max(
            0.0,
            float(
                separation_solution.obj_bound
                if separation_solution.obj_bound is not None
                else (separation_solution.objective_value or 0.0)
            ),
        )
        active_lines = tuple(_active_outage_lines(separation_solution.delta_by_line_id))
        event: dict[str, Any] = {
            "pricing_round": round_index + 1,
            "restricted_w_lb": float(fixed_dual["restricted_w_lb"]),
            "fixed_plan_objective_lb": objective_lb,
            "pricing_status": separation_solution.model_status,
            "pricing_violation_value": violation_value,
            "pricing_violation_bound": violation_bound,
            "pricing_mip_gap": separation_solution.mip_gap,
            "pricing_node_count": separation_solution.node_count,
            "active_line_count": len(active_lines),
            "active_lines": ";".join(active_lines),
        }
        pricing_events.append(event)
        _append_jsonl(trace_path, event)
        if violation_bound <= float(epsilon_price):
            return {
                "status": "FULLY_PRICED_NOT_ABOVE_TAU",
                "proved_above_tau": False,
                "tau": float(tau),
                "fixed_plan_objective_lb": objective_lb,
                "margin_above_tau": float(objective_lb - float(tau)),
                "normal_replay": normal_replay,
                "fixed_dual": fixed_dual,
                "pricing_events": pricing_events,
                "pricing_rounds_used": round_index + 1,
                "full_support_pricing_bound": violation_bound,
                "local_generated_column_count": max(0, len(working_rows) - len(outage_column_cuts)),
                "_generated_outage_column_cuts": generated_rows,
            }
        if separation_solution.objective_value is None or violation_value <= 0.0:
            event["event"] = "pricing_no_feasible_violated_column"
            break
        cut_result = generate_cut_from_separation_solution(
            instance,
            plan=plan,
            separation_solution=separation_solution,
            scenario_ids=instance.sets.loaded_disaster_scenarios,
            cut_id=f"{cut_id_prefix}_price_{round_index + 1:04d}",
            provenance=f"{cut_id_prefix}_oracle_pricing_{round_index + 1:04d}",
            lambda_by_line_id=dict(fixed_dual["lambda_by_line_id"]),
            log_to_console=log_to_console,
        )
        signature = compute_cut_signature_hash(cut_result.cut)
        key = (active_lines, signature)
        if key in seen_local_keys:
            event["event"] = "duplicate_priced_column"
            break
        generated_row = RestrictedMasterOutageColumnCut(
            row_id=f"{cut_id_prefix}_price_row_{round_index + 1:04d}_{_outage_column_id(active_lines)}",
            column_id=_outage_column_id(active_lines),
            active_line_ids=active_lines,
            cut=cut_result.cut,
        )
        working_rows.append(generated_row)
        generated_rows.append(generated_row)
        seen_local_keys.add(key)
        event["event"] = "added_priced_column"
        event["cut_signature_hash"] = signature
        event["old_master_cut_violation"] = float(cut_result.old_master_cut_violation)
    if last_fixed_dual is None or last_objective_lb is None:
        return {
            "status": "NO_FIXED_PLAN_DUAL_SOLVE",
            "proved_above_tau": False,
            "tau": float(tau),
            "normal_replay": normal_replay,
            "pricing_events": pricing_events,
            "local_generated_column_count": max(0, len(working_rows) - len(outage_column_cuts)),
            "_generated_outage_column_cuts": generated_rows,
        }
    return {
        "status": "RESTRICTED_LB_NOT_ABOVE_TAU",
        "proved_above_tau": False,
        "tau": float(tau),
        "fixed_plan_objective_lb": last_objective_lb,
        "margin_above_tau": float(last_objective_lb - float(tau)),
        "normal_replay": normal_replay,
        "fixed_dual": last_fixed_dual,
        "pricing_events": pricing_events,
        "pricing_rounds_used": int(pricing_rounds),
        "local_generated_column_count": max(0, len(working_rows) - len(outage_column_cuts)),
        "_generated_outage_column_cuts": generated_rows,
    }


def _add_exact_plan_nogood_to_existing_master(
    master,
    *,
    plan: FixedFirstStagePlan,
    nogood_id: str,
) -> None:
    mismatch_vars = []
    for bus in master.ordered_buses:
        z_val = int(plan.z_by_bus[bus])
        z_mismatch = master.model.addVar(vtype=GRB.BINARY, name=f"{nogood_id}_mz_{bus}")
        if z_val == 1:
            master.model.addConstr(
                z_mismatch >= 1.0 - master.first_stage.z_by_bus[bus],
                name=f"{nogood_id}_z_mismatch_one_{bus}",
            )
        else:
            master.model.addConstr(
                z_mismatch >= master.first_stage.z_by_bus[bus],
                name=f"{nogood_id}_z_mismatch_zero_{bus}",
            )
        mismatch_vars.append(z_mismatch)

        for label, var_by_bus, value_by_bus, bound in (
            (
                "sl",
                master.first_stage.n_sl_by_bus,
                plan.n_sl_by_bus,
                int(master.instance.ev.nbar_sl_by_bus.get(bus, master.instance.ev.nbar_sl)),
            ),
            (
                "fa",
                master.first_stage.n_fa_by_bus,
                plan.n_fa_by_bus,
                int(master.instance.ev.nbar_fa_by_bus.get(bus, master.instance.ev.nbar_fa)),
            ),
        ):
            value = int(value_by_bus[bus])
            big_m = max(1, int(bound), value)
            mismatch = master.model.addVar(
                vtype=GRB.BINARY,
                name=f"{nogood_id}_m{label}_{bus}",
            )
            master.model.addConstr(
                var_by_bus[bus] - float(value) <= float(big_m) * mismatch,
                name=f"{nogood_id}_{label}_pos_{bus}",
            )
            master.model.addConstr(
                float(value) - var_by_bus[bus] <= float(big_m) * mismatch,
                name=f"{nogood_id}_{label}_neg_{bus}",
            )
            mismatch_vars.append(mismatch)
    master.model.addConstr(
        quicksum(mismatch_vars) >= 1.0,
        name=f"{nogood_id}_exclude_exact_plan",
    )
    master.model.update()


def _append_valid_cut(
    instance,
    *,
    current_cuts: list[RestrictedMasterCut],
    current_outage_column_cuts: list[RestrictedMasterOutageColumnCut],
    seen_global_signatures: set[str],
    seen_rowwise_keys: set[tuple[tuple[str, ...], str]],
    plan: FixedFirstStagePlan,
    separation_solution,
    lambda_by_line_id: Mapping[str, float],
    cut_index: int,
    keep_global_cuts: bool,
    persistent_master: Any | None = None,
    direct_fixed_outage_rows: bool = False,
    enable_subset_cuts: bool = False,
    subset_cut_sizes: Sequence[int] = (),
    log_to_console: bool,
) -> dict[str, Any]:
    active_lines = _active_outage_lines(separation_solution.delta_by_line_id)
    cut_result = generate_cut_from_separation_solution(
        instance,
        plan=plan,
        separation_solution=separation_solution,
        scenario_ids=instance.sets.loaded_disaster_scenarios,
        cut_id=f"target_level_cut_{cut_index:06d}",
        provenance=f"incumbent_guarded_target_level_{cut_index:06d}",
        lambda_by_line_id=lambda_by_line_id,
        log_to_console=log_to_console,
    )
    signature = str(cut_result.cut_signature_hash)
    added_global = False
    added_rowwise = False
    if keep_global_cuts and signature not in seen_global_signatures:
        current_cuts.append(cut_result.cut)
        seen_global_signatures.add(signature)
        if persistent_master is not None:
            _add_global_cut_to_existing_master(persistent_master, cut_result.cut)
        added_global = True
    added_rowwise_count = 0
    duplicate_rowwise_count = 0
    row_variants = _active_line_variants_for_cut(
        cut_result.cut,
        active_lines,
        subset_cut_sizes,
    ) if bool(enable_subset_cuts) else [tuple(active_lines)]
    row_variant_sizes: list[int] = []
    for variant_index, active_variant in enumerate(row_variants, start=1):
        rowwise_key = (tuple(active_variant), signature)
        if rowwise_key in seen_rowwise_keys:
            duplicate_rowwise_count += 1
            continue
        column_id = _outage_column_id(active_variant)
        row = RestrictedMasterOutageColumnCut(
            row_id=f"target_level_nccg_{cut_index:06d}_{variant_index:03d}_{column_id}",
            column_id=column_id,
            active_line_ids=tuple(active_variant),
            cut=cut_result.cut,
        )
        current_outage_column_cuts.append(row)
        if persistent_master is not None:
            if bool(direct_fixed_outage_rows):
                _add_direct_fixed_outage_cut_to_existing_master(
                    persistent_master,
                    cut=cut_result.cut,
                    active_line_ids=active_variant,
                    row_id=row.row_id,
                )
            else:
                _add_outage_column_cut_to_existing_master(persistent_master, row)
        seen_rowwise_keys.add(rowwise_key)
        added_rowwise_count += 1
        row_variant_sizes.append(len(active_variant))
    return {
        "active_lines": ";".join(active_lines),
        "cut_signature_hash": signature,
        "old_master_cut_violation": cut_result.old_master_cut_violation,
        "added_global": added_global,
        "added_rowwise": added_rowwise_count > 0,
        "added_rowwise_count": added_rowwise_count,
        "duplicate_rowwise_count": duplicate_rowwise_count,
        "row_variant_count": len(row_variants),
        "row_variant_sizes_added": ";".join(str(size) for size in row_variant_sizes),
    }


def _plan_gamma_value(cut: RestrictedMasterCut, plan: FixedFirstStagePlan) -> float:
    return float(
        sum(float(cut.gamma_z_by_bus[bus]) * float(plan.z_by_bus[bus]) for bus in plan.z_by_bus)
        + sum(
            float(cut.gamma_n_sl_by_bus[bus]) * float(plan.n_sl_by_bus[bus])
            for bus in plan.n_sl_by_bus
        )
        + sum(
            float(cut.gamma_n_fa_by_bus[bus]) * float(plan.n_fa_by_bus[bus])
            for bus in plan.n_fa_by_bus
        )
    )


def _rowwise_cut_source_value(
    row_cut: RestrictedMasterOutageColumnCut,
    *,
    source_plan: FixedFirstStagePlan,
    active_line_ids: Sequence[str] | None = None,
) -> float:
    cut = row_cut.cut
    resolved_active = tuple(active_line_ids) if active_line_ids is not None else row_cut.active_line_ids
    phi_delta = sum(float(cut.phi_by_line_id[line_id]) for line_id in resolved_active)
    return float(cut.beta) - _plan_gamma_value(cut, source_plan) + float(phi_delta)


def _line_fp_by_id(instance) -> dict[str, float]:
    p_bar = tuple(float(value) for value in instance.ambiguity.p_bar)
    line_ids = tuple(instance.sets.line_ids)
    if len(p_bar) != len(line_ids):
        raise RuntimeError(
            f"ambiguity p_bar has length {len(p_bar)}, expected {len(line_ids)}."
        )
    return {line_id: p_bar[index] for index, line_id in enumerate(line_ids)}


def _build_distributional_value_cut(
    instance,
    *,
    source_plan: FixedFirstStagePlan,
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    cut_id: str,
    max_columns: int,
    subset_sizes: Sequence[int],
    pricing_rounds: int = 0,
    pricing_time_limit_seconds: float = 300.0,
    pricing_mip_gap: float = 0.02,
    omega_bound_upper: float = 2.0e7,
    log_to_console: bool = False,
    min_positive_mass: float = 1.0e-8,
    recompute_source_duals: bool = False,
    recompute_source_duals_limit: int = 0,
) -> dict[str, Any] | None:
    """Build one Pro-recommended distributional value cut from valid row cuts."""

    best_by_key: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}
    requested_subset_sizes = tuple(sorted({int(size) for size in subset_sizes if int(size) > 0}))
    for row_cut in outage_column_cuts:
        signature = compute_cut_signature_hash(row_cut.cut)
        ranked_active_lines = tuple(
            line_id
            for line_id, _phi in sorted(
                (
                    (line_id, float(row_cut.cut.phi_by_line_id[line_id]))
                    for line_id in row_cut.active_line_ids
                ),
                key=lambda item: item[1],
                reverse=True,
            )
        )
        active_variants: set[tuple[str, ...]] = {tuple(row_cut.active_line_ids)}
        for size in requested_subset_sizes:
            if size <= len(ranked_active_lines):
                active_variants.add(tuple(sorted(ranked_active_lines[:size])))
        for active_line_ids in active_variants:
            key = (tuple(active_line_ids), signature)
            source_value = _rowwise_cut_source_value(
                row_cut,
                source_plan=source_plan,
                active_line_ids=active_line_ids,
            )
            previous = best_by_key.get(key)
            if previous is None or source_value > float(previous["source_value"]):
                best_by_key[key] = {
                    "row_cut": row_cut,
                    "active_line_ids": tuple(active_line_ids),
                    "source_value": float(source_value),
                    "signature": signature,
                }

    candidates = sorted(
        best_by_key.values(),
        key=lambda item: float(item["source_value"]),
        reverse=True,
    )[: int(max_columns)]
    if not candidates:
        return None

    recompute_limit = int(recompute_source_duals_limit)
    if bool(recompute_source_duals) and recompute_limit != 0:
        selected = candidates if recompute_limit < 0 else candidates[:recompute_limit]
        untouched = [] if recompute_limit < 0 else candidates[recompute_limit:]
        recomputed: list[dict[str, Any]] = []
        for idx, item in enumerate(selected, start=1):
            active_line_ids = tuple(str(line_id) for line_id in item["active_line_ids"])
            outage = build_fixed_outage_vector(
                instance,
                by_line_id={line_id: int(line_id in active_line_ids) for line_id in instance.sets.line_ids},
            )
            try:
                cut_result = generate_structured_cut(
                    instance,
                    plan=source_plan,
                    outage=outage,
                    scenario_ids=instance.sets.loaded_disaster_scenarios,
                    cut_id=f"{cut_id}_recomputed_{idx:04d}",
                    provenance="distributional_value_cut_source_recompute",
                    canonicalize_degenerate_dual=True,
                    log_to_console=log_to_console,
                )
            except Exception as exc:
                pricing_events = [
                    {
                        "event": "source_dual_recompute_failed",
                        "candidate_index": idx,
                        "active_line_ids": ";".join(active_line_ids),
                        "error": repr(exc),
                    }
                ]
                return {
                    "cut_id": cut_id,
                    "accepted": False,
                    "status": "SOURCE_DUAL_RECOMPUTE_FAILED",
                    "reason": "source_dual_recompute_failed",
                    "pricing_events": pricing_events,
                }
            recomputed_row = RestrictedMasterOutageColumnCut(
                row_id=f"{cut_id}_recomputed_row_{idx:04d}_{_outage_column_id(active_line_ids)}",
                column_id=_outage_column_id(active_line_ids),
                active_line_ids=active_line_ids,
                cut=cut_result.cut,
            )
            source_value = _rowwise_cut_source_value(
                recomputed_row,
                source_plan=source_plan,
                active_line_ids=active_line_ids,
            )
            recomputed.append(
                {
                    "row_cut": recomputed_row,
                    "active_line_ids": active_line_ids,
                    "source_value": float(source_value),
                    "signature": compute_cut_signature_hash(cut_result.cut),
                    "recomputed_source_dual": True,
                }
            )
        candidates = sorted(
            recomputed + untouched,
            key=lambda item: float(item["source_value"]),
            reverse=True,
        )[: int(max_columns)]

    line_ids = tuple(instance.sets.line_ids)
    fp_by_line_id = _line_fp_by_id(instance)
    pricing_events: list[dict[str, Any]] = []
    for pricing_round in range(1, int(pricing_rounds) + 1):
        alpha_value, lambda_values, dual_status, dual_obj = _solve_value_cut_column_dual(
            instance,
            candidates=candidates,
            fp_by_line_id=fp_by_line_id,
        )
        if dual_status != "OPTIMAL":
            pricing_events.append(
                {
                    "pricing_round": pricing_round,
                    "event": "column_dual_not_optimal",
                    "dual_status": dual_status,
                }
            )
            break
        _, separation_solution = _full_support_pricing(
            instance,
            plan=source_plan,
            solution=SimpleNamespace(
                alpha_value=float(alpha_value),
                lambda_by_line_id=dict(lambda_values),
            ),
            omega_bound_upper=float(omega_bound_upper),
            time_limit_seconds=float(pricing_time_limit_seconds),
            mip_gap=float(pricing_mip_gap),
            model_name=f"value_cut_{cut_id}_pricing_{pricing_round:03d}",
            log_to_console=log_to_console,
        )
        active_lines = _active_outage_lines(separation_solution.delta_by_line_id)
        violation_bound = (
            None
            if separation_solution.obj_bound is None
            else float(separation_solution.obj_bound)
        )
        violation_value = (
            0.0
            if separation_solution.objective_value is None
            else float(separation_solution.objective_value)
        )
        pricing_events.append(
            {
                "pricing_round": pricing_round,
                "dual_status": dual_status,
                "dual_obj": float(dual_obj),
                "pricing_status": separation_solution.model_status,
                "pricing_violation": violation_value,
                "pricing_obj_bound": violation_bound,
                "active_line_count": len(active_lines),
                "active_lines": ";".join(active_lines),
            }
        )
        if violation_bound is not None and violation_bound <= 1.0e-6:
            break
        if separation_solution.objective_value is None:
            break
        cut_result = generate_cut_from_separation_solution(
            instance,
            plan=source_plan,
            separation_solution=separation_solution,
            scenario_ids=instance.sets.loaded_disaster_scenarios,
            cut_id=f"{cut_id}_priced_{pricing_round:03d}",
            provenance=f"value_cut_fixed_plan_pricing_{pricing_round:03d}",
            lambda_by_line_id=lambda_values,
            log_to_console=log_to_console,
        )
        priced_row = RestrictedMasterOutageColumnCut(
            row_id=f"{cut_id}_priced_row_{pricing_round:03d}",
            column_id=_outage_column_id(active_lines),
            active_line_ids=tuple(active_lines),
            cut=cut_result.cut,
        )
        ranked_active_lines = tuple(
            line_id
            for line_id, _phi in sorted(
                (
                    (line_id, float(cut_result.cut.phi_by_line_id[line_id]))
                    for line_id in active_lines
                ),
                key=lambda item: item[1],
                reverse=True,
            )
        )
        active_variants: set[tuple[str, ...]] = {tuple(active_lines)}
        for size in requested_subset_sizes:
            if size <= len(ranked_active_lines):
                active_variants.add(tuple(sorted(ranked_active_lines[:size])))
        added = 0
        for active_variant in active_variants:
            signature = compute_cut_signature_hash(cut_result.cut)
            key = (tuple(active_variant), signature)
            source_value = _rowwise_cut_source_value(
                priced_row,
                source_plan=source_plan,
                active_line_ids=active_variant,
            )
            previous = best_by_key.get(key)
            if previous is None or source_value > float(previous["source_value"]):
                best_by_key[key] = {
                    "row_cut": priced_row,
                    "active_line_ids": tuple(active_variant),
                    "source_value": float(source_value),
                    "signature": signature,
                }
                added += 1
        candidates = sorted(
            best_by_key.values(),
            key=lambda item: float(item["source_value"]),
            reverse=True,
        )[: int(max_columns)]
        pricing_events[-1]["added_candidate_variants"] = added

    model = Model(f"value_cut_distribution_{cut_id}")
    model.Params.OutputFlag = 0
    p_vars = {
        idx: model.addVar(lb=0.0, ub=1.0, name=f"p_{idx:04d}")
        for idx in range(len(candidates))
    }
    p_zero = model.addVar(lb=0.0, ub=1.0, name="p_zero")
    model.addConstr(p_zero + quicksum(p_vars.values()) == 1.0, name="mass")
    for line_id in line_ids:
        model.addConstr(
            quicksum(
                p_vars[idx]
                for idx, item in enumerate(candidates)
                if line_id in item["active_line_ids"]
            )
            <= float(fp_by_line_id[line_id]),
            name=f"moment_{line_id}",
        )
    model.setObjective(
        quicksum(float(item["source_value"]) * p_vars[idx] for idx, item in enumerate(candidates)),
        GRB.MAXIMIZE,
    )
    model.optimize()
    if int(model.Status) != GRB.OPTIMAL:
        return {
            "cut_id": cut_id,
            "status": _status_name(int(model.Status)),
            "accepted": False,
            "reason": "distribution_lp_not_optimal",
        }

    positive_terms: list[tuple[float, RestrictedMasterOutageColumnCut, tuple[str, ...], float]] = []
    for idx, item in enumerate(candidates):
        mass = float(p_vars[idx].X)
        if mass > float(min_positive_mass):
            positive_terms.append(
                (
                    mass,
                    item["row_cut"],
                    tuple(item["active_line_ids"]),
                    float(item["source_value"]),
                )
            )
    if not positive_terms:
        return {
            "cut_id": cut_id,
            "status": "OPTIMAL",
            "accepted": False,
            "reason": "zero_real_column_mass",
            "objective_value": float(model.ObjVal),
            "p_zero": float(p_zero.X),
        }

    beta = 0.0
    gamma_z_by_bus = {bus: 0.0 for bus in instance.sets.buses}
    gamma_n_sl_by_bus = {bus: 0.0 for bus in instance.sets.buses}
    gamma_n_fa_by_bus = {bus: 0.0 for bus in instance.sets.buses}
    distribution_rows: list[dict[str, Any]] = []
    moment_usage = {line_id: 0.0 for line_id in line_ids}
    for mass, row_cut, active_line_ids, source_value in positive_terms:
        cut = row_cut.cut
        phi_delta = sum(float(cut.phi_by_line_id[line_id]) for line_id in active_line_ids)
        beta += float(mass) * (float(cut.beta) + float(phi_delta))
        for bus in instance.sets.buses:
            gamma_z_by_bus[bus] += float(mass) * float(cut.gamma_z_by_bus[bus])
            gamma_n_sl_by_bus[bus] += float(mass) * float(cut.gamma_n_sl_by_bus[bus])
            gamma_n_fa_by_bus[bus] += float(mass) * float(cut.gamma_n_fa_by_bus[bus])
        for line_id in active_line_ids:
            moment_usage[line_id] += float(mass)
        distribution_rows.append(
            {
                "cut_id": cut_id,
                "mass": float(mass),
                "column_id": row_cut.column_id,
                "row_id": row_cut.row_id,
                "active_line_count": len(active_line_ids),
                "source_column_active_line_count": len(row_cut.active_line_ids),
                "source_value": float(source_value),
                "cut_signature": compute_cut_signature_hash(cut),
                "active_line_ids": ";".join(active_line_ids),
            }
        )

    rhs_at_source = float(beta) - (
        sum(gamma_z_by_bus[bus] * float(source_plan.z_by_bus[bus]) for bus in instance.sets.buses)
        + sum(
            gamma_n_sl_by_bus[bus] * float(source_plan.n_sl_by_bus[bus])
            for bus in instance.sets.buses
        )
        + sum(
            gamma_n_fa_by_bus[bus] * float(source_plan.n_fa_by_bus[bus])
            for bus in instance.sets.buses
        )
    )
    moment_slack = {
        line_id: float(fp_by_line_id[line_id]) - float(moment_usage[line_id])
        for line_id in line_ids
    }
    return {
        "cut_id": cut_id,
        "accepted": True,
        "status": "OPTIMAL",
        "beta": float(beta),
        "gamma_z_by_bus": gamma_z_by_bus,
        "gamma_n_sl_by_bus": gamma_n_sl_by_bus,
        "gamma_n_fa_by_bus": gamma_n_fa_by_bus,
        "objective_value": float(model.ObjVal),
        "rhs_at_source": rhs_at_source,
        "source_replay_gap": float(rhs_at_source) - float(model.ObjVal),
        "p_zero": float(p_zero.X),
        "real_column_mass": float(sum(mass for mass, _, _, _ in positive_terms)),
        "positive_column_count": len(positive_terms),
        "candidate_column_count": len(candidates),
        "moment_slack_min": min(moment_slack.values()) if moment_slack else 0.0,
        "moment_slack_max": max(moment_slack.values()) if moment_slack else 0.0,
        "distribution_rows": distribution_rows,
        "pricing_events": pricing_events,
    }


def _add_distributional_value_cut_to_master(master, value_cut: Mapping[str, Any]) -> Any:
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
    lhs = master.alpha_var + quicksum(
        float(master.fp_by_line_id[line_id]) * master.lambda_by_line_id[line_id]
        for line_id in master.ordered_line_ids
    )
    return master.model.addConstr(
        lhs >= float(value_cut["beta"]) - gamma_expr,
        name=f"distributional_value_cut_{cut_id}",
    )


def _complete_mandatory_outage_columns(
    instance,
    *,
    source_plan: FixedFirstStagePlan,
    base_cuts: Sequence[RestrictedMasterCut],
    base_outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    include_zero: bool,
    include_singletons: bool,
    historical_count: int,
    cut_id_prefix: str,
    log_to_console: bool = False,
) -> dict[str, Any]:
    """Generate valid initial cuts for low-order and historical outage columns."""

    existing_global_signatures = {
        compute_cut_signature_hash(cut) for cut in base_cuts
    }
    existing_row_keys = {
        (tuple(row.active_line_ids), compute_cut_signature_hash(row.cut))
        for row in base_outage_column_cuts
    }
    patterns: list[tuple[str, ...]] = []
    if bool(include_zero):
        patterns.append(())
    if bool(include_singletons):
        patterns.extend((str(line_id),) for line_id in instance.sets.line_ids)
    if int(historical_count) > 0:
        best_by_pattern: dict[tuple[str, ...], float] = {}
        for row in base_outage_column_cuts:
            pattern = tuple(str(line_id) for line_id in row.active_line_ids)
            value = _rowwise_cut_source_value(row, source_plan=source_plan)
            if pattern not in best_by_pattern or value > best_by_pattern[pattern]:
                best_by_pattern[pattern] = float(value)
        patterns.extend(
            tuple(pattern)
            for pattern, _value in sorted(
                best_by_pattern.items(),
                key=lambda item: item[1],
                reverse=True,
            )[: int(historical_count)]
        )

    unique_patterns: list[tuple[str, ...]] = []
    seen_patterns: set[tuple[str, ...]] = set()
    for pattern in patterns:
        normalized = tuple(sorted(str(line_id) for line_id in pattern))
        if normalized in seen_patterns:
            continue
        seen_patterns.add(normalized)
        unique_patterns.append(normalized)

    new_cuts: list[RestrictedMasterCut] = []
    new_outage_rows: list[RestrictedMasterOutageColumnCut] = []
    rows: list[dict[str, Any]] = []
    for index, active_line_ids in enumerate(unique_patterns, start=1):
        active_set = set(active_line_ids)
        outage = build_fixed_outage_vector(
            instance,
            by_line_id={
                line_id: int(str(line_id) in active_set)
                for line_id in instance.sets.line_ids
            },
        )
        try:
            generated = generate_structured_cut(
                instance,
                plan=source_plan,
                outage=outage,
                scenario_ids=instance.sets.loaded_disaster_scenarios,
                cut_id=f"{cut_id_prefix}_{index:04d}_{_outage_column_id(active_line_ids)}",
                provenance="single_tree_mandatory_column_completion",
                canonicalize_degenerate_dual=True,
                log_to_console=log_to_console,
            )
        except Exception as exc:
            rows.append(
                {
                    "pattern_index": index,
                    "active_line_count": len(active_line_ids),
                    "active_lines": ";".join(active_line_ids),
                    "status": "error",
                    "error": repr(exc),
                }
            )
            continue
        signature = compute_cut_signature_hash(generated.cut)
        added_global = False
        if signature not in existing_global_signatures:
            new_cuts.append(generated.cut)
            existing_global_signatures.add(signature)
            added_global = True
        row_key = (active_line_ids, signature)
        added_rowwise = False
        if row_key not in existing_row_keys:
            new_outage_rows.append(
                RestrictedMasterOutageColumnCut(
                    row_id=(
                        f"{cut_id_prefix}_row_{index:04d}_"
                        f"{_outage_column_id(active_line_ids)}"
                    ),
                    column_id=_outage_column_id(active_line_ids),
                    active_line_ids=active_line_ids,
                    cut=generated.cut,
                )
            )
            existing_row_keys.add(row_key)
            added_rowwise = True
        rows.append(
            {
                "pattern_index": index,
                "active_line_count": len(active_line_ids),
                "active_lines": ";".join(active_line_ids),
                "status": "ok",
                "cut_signature_hash": signature,
                "added_global": added_global,
                "added_rowwise": added_rowwise,
                "old_master_cut_violation": generated.old_master_cut_violation,
            }
        )
    return {
        "cuts": new_cuts,
        "outage_column_cuts": new_outage_rows,
        "audit_rows": rows,
        "requested_pattern_count": len(unique_patterns),
        "added_global_count": len(new_cuts),
        "added_rowwise_count": len(new_outage_rows),
    }


def _distributional_value_cut_temp_constr(master, value_cut: Mapping[str, Any]):
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
    lhs = master.alpha_var + quicksum(
        float(master.fp_by_line_id[line_id]) * master.lambda_by_line_id[line_id]
        for line_id in master.ordered_line_ids
    )
    return lhs >= float(value_cut["beta"]) - gamma_expr


def _distributional_value_cut_signature(value_cut: Mapping[str, Any]) -> str:
    payload = {
        "beta": round(float(value_cut["beta"]), 8),
        "gamma_z": {
            str(bus): round(float(value), 8)
            for bus, value in dict(value_cut["gamma_z_by_bus"]).items()
            if abs(float(value)) > 1.0e-9
        },
        "gamma_sl": {
            str(bus): round(float(value), 8)
            for bus, value in dict(value_cut["gamma_n_sl_by_bus"]).items()
            if abs(float(value)) > 1.0e-9
        },
        "gamma_fa": {
            str(bus): round(float(value), 8)
            for bus, value in dict(value_cut["gamma_n_fa_by_bus"]).items()
            if abs(float(value)) > 1.0e-9
        },
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _solve_value_cut_column_dual(
    instance,
    *,
    candidates: Sequence[Mapping[str, Any]],
    fp_by_line_id: Mapping[str, float],
) -> tuple[float, dict[str, float], str, float | None]:
    """Solve the restricted fixed-plan ambiguity dual over candidate columns."""

    model = Model("value_cut_column_dual")
    model.Params.OutputFlag = 0
    alpha = model.addVar(lb=float(instance.economics.alpha_min), name="alpha")
    lambda_by_line_id = {
        line_id: model.addVar(lb=0.0, name=f"lambda_{line_id}")
        for line_id in instance.sets.line_ids
    }
    for idx, item in enumerate(candidates):
        active_line_ids = tuple(str(line_id) for line_id in item["active_line_ids"])
        model.addConstr(
            alpha + quicksum(lambda_by_line_id[line_id] for line_id in active_line_ids)
            >= float(item["source_value"]),
            name=f"column_{idx:05d}",
        )
    model.setObjective(
        alpha
        + quicksum(
            float(fp_by_line_id[line_id]) * lambda_by_line_id[line_id]
            for line_id in instance.sets.line_ids
        ),
        GRB.MINIMIZE,
    )
    model.optimize()
    status = _status_name(int(model.Status))
    if int(model.Status) != GRB.OPTIMAL:
        return 0.0, {line_id: 0.0 for line_id in instance.sets.line_ids}, status, None
    return (
        float(alpha.X),
        {
            line_id: max(0.0, float(lambda_by_line_id[line_id].X))
            for line_id in instance.sets.line_ids
        },
        status,
        float(model.ObjVal),
    )


def _canonical_bound(model) -> float | None:
    try:
        return float(model.ObjBound)
    except Exception:
        return None


def _run_value_cut_lb_ascent(
    args: argparse.Namespace,
    *,
    output_root: Path,
    instance,
    incumbent: Mapping[str, Any],
    run_log_path: Path,
    cut_pool_path: Path,
    cut_pool_audit_rows: Sequence[Mapping[str, Any]],
    initial_cuts: Sequence[RestrictedMasterCut],
    initial_outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    warm_start_plan: FixedFirstStagePlan,
    warm_start_alpha: float,
    warm_start_lambda_by_line_id: Mapping[str, float],
) -> dict[str, Any]:
    """Prototype A from Pro: distributional value-cut lower-bound ascent."""

    output_root.mkdir(parents=True, exist_ok=True)
    U = float(incumbent["pricing_upper_bound"])
    tau = float(incumbent["target_tau"])
    value_cuts: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    distribution_rows: list[dict[str, Any]] = []
    current_source_plan = warm_start_plan
    best_lower_bound = float(incumbent["canonical_lower_bound"])
    certified = False
    closure_status = "value_cut_lb_ascent_not_started"

    for rebuild in range(1, int(args.value_cut_rebuilds) + 1):
        for local_idx in range(1, int(args.value_cuts_per_rebuild) + 1):
            cut = _build_distributional_value_cut(
                instance,
                source_plan=current_source_plan,
                outage_column_cuts=initial_outage_column_cuts,
                cut_id=f"value_cut_r{rebuild:03d}_{local_idx:02d}",
                max_columns=int(args.value_cut_max_columns),
                subset_sizes=_parse_int_list(args.value_cut_subset_sizes),
                pricing_rounds=int(args.value_cut_pricing_rounds),
                pricing_time_limit_seconds=float(args.value_cut_pricing_time_limit_seconds),
                pricing_mip_gap=float(args.separation_mip_gap),
                omega_bound_upper=float(args.omega_bound_upper),
                log_to_console=bool(args.log_to_console),
                recompute_source_duals=bool(args.value_cut_recompute_source_duals),
                recompute_source_duals_limit=int(args.value_cut_recompute_source_duals_limit),
            )
            if cut is not None and bool(cut.get("accepted")):
                value_cuts.append(cut)
                distribution_rows.extend(cut.get("distribution_rows", []))
            elif cut is not None:
                rows.append(
                    {
                        "rebuild": rebuild,
                        "event": "value_cut_rejected",
                        "cut_id": cut.get("cut_id", ""),
                        "reason": cut.get("reason", ""),
                        "status": cut.get("status", ""),
                    }
                )

        master = build_master_problem(
            instance,
            cuts=initial_cuts,
            outage_column_cuts=initial_outage_column_cuts,
            warm_start_plan=warm_start_plan,
            warm_start_alpha=warm_start_alpha,
            warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
            model_name=f"value_cut_lb_ascent_k{int(instance.ambiguity.k_max_outages)}_{rebuild:03d}",
            log_to_console=bool(args.log_to_console),
        )
        if master.total_objective_expression is None:
            raise RuntimeError("Canonical master did not expose total objective expression.")
        if bool(args.value_cut_safe_cutoff):
            master.model.addConstr(
                master.total_objective_expression <= float(U),
                name="safe_incumbent_objective_cutoff",
            )
        for value_cut in value_cuts:
            _add_distributional_value_cut_to_master(master, value_cut)
        master.model.Params.TimeLimit = float(args.value_cut_time_limit_seconds)
        master.model.Params.MIPGap = float(args.target_mip_gap)
        master.model.Params.DualReductions = 0
        start = perf_counter()
        master.model.optimize()
        elapsed = perf_counter() - start
        status = _status_name(int(master.model.Status))
        obj_bound = _canonical_bound(master.model)
        obj_val = None
        sol_count = int(getattr(master.model, "SolCount", 0))
        solution = None
        if sol_count > 0:
            obj_val = float(master.model.ObjVal)
            solution = extract_master_problem_solution(master)
            current_source_plan = _plan_from_solution(instance, solution)
            warm_start_plan = current_source_plan
            warm_start_alpha = float(solution.alpha_value)
            warm_start_lambda_by_line_id = dict(solution.lambda_by_line_id)
        if obj_bound is not None:
            best_lower_bound = max(best_lower_bound, float(obj_bound))
        gap_to_incumbent = float(U) - float(best_lower_bound)
        row = {
            "rebuild": rebuild,
            "status": status,
            "runtime_seconds": elapsed,
            "sol_count": sol_count,
            "obj_val": obj_val,
            "obj_bound": obj_bound,
            "best_lower_bound": best_lower_bound,
            "pricing_upper_bound": U,
            "target_tau": tau,
            "gap_to_incumbent": gap_to_incumbent,
            "value_cut_count": len(value_cuts),
            "last_value_cut_objective": value_cuts[-1]["objective_value"] if value_cuts else None,
            "last_value_cut_real_mass": value_cuts[-1]["real_column_mass"] if value_cuts else None,
            "last_value_cut_positive_columns": (
                value_cuts[-1]["positive_column_count"] if value_cuts else None
            ),
        }
        rows.append(row)
        _write_csv(output_root / "value_cut_lb_ascent_trace.csv", rows)
        _write_csv(output_root / "value_cut_distribution_rows.csv", distribution_rows)
        _write_json(
            output_root / "value_cut_pool.json",
            {
                "value_cuts": value_cuts,
                "metadata": {
                    "run_log_path": str(run_log_path),
                    "cut_pool_path": str(cut_pool_path),
                    "pricing_upper_bound": U,
                    "target_tau": tau,
                    "epsilon_gap": float(args.epsilon_gap),
                    "cut_pool_audit_rows": list(cut_pool_audit_rows),
                },
            },
        )
        if gap_to_incumbent <= float(args.epsilon_gap):
            certified = True
            closure_status = "epsilon_gap_certified_by_value_cut_canonical_lb"
            break
        closure_status = "value_cut_lb_ascent_diagnostic"

    summary = {
        "closure_status": closure_status,
        "validation_level": (
            "epsilon_certified_value_cut_canonical_lb"
            if certified
            else "value_cut_lb_ascent_diagnostic"
        ),
        "certified": certified,
        "pricing_upper_bound": U,
        "target_tau": tau,
        "epsilon_gap": float(args.epsilon_gap),
        "initial_canonical_lower_bound": float(incumbent["canonical_lower_bound"]),
        "best_lower_bound": best_lower_bound,
        "gap_to_incumbent": float(U) - float(best_lower_bound),
        "value_cut_count": len(value_cuts),
        "trace_path": str(output_root / "value_cut_lb_ascent_trace.csv"),
        "value_cut_pool_path": str(output_root / "value_cut_pool.json"),
        "pro_tex_path": str(Path("/Users/shixinliu/Downloads/evcs_dro_k16_root_closure_next_step.tex")),
        "certificate_rule": (
            "Paper-facing only if pricing_upper_bound - best canonical ObjBound/ObjVal "
            "<= epsilon_gap. Otherwise diagnostic."
        ),
    }
    _write_json(output_root / "value_cut_lb_ascent_summary.json", summary)
    (output_root / "value_cut_lb_ascent_report.md").write_text(
        "\n".join(
            [
                "# K=16 Distributional Value-Cut LB Ascent",
                "",
                f"- Closure status: `{closure_status}`",
                f"- Initial LB: `{float(incumbent['canonical_lower_bound'])}`",
                f"- Best LB: `{best_lower_bound}`",
                f"- Pricing UB: `{U}`",
                f"- Remaining gap: `{float(U) - float(best_lower_bound)}`",
                f"- Value cuts: `{len(value_cuts)}`",
                "",
                "Certificate rule: this is paper-facing only if the canonical lower-bound gap closes.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def _run_integrated_target_lazy_closure(
    args: argparse.Namespace,
    *,
    output_root: Path,
    instance,
    run_config: Mapping[str, Any],
    incumbent: Mapping[str, Any],
    run_log_path: Path,
    cut_pool_path: Path,
    cut_pool_audit_rows: Sequence[Mapping[str, Any]],
    initial_cuts: Sequence[RestrictedMasterCut],
    initial_outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    warm_start_plan: FixedFirstStagePlan,
    warm_start_alpha: float,
    warm_start_lambda_by_line_id: Mapping[str, float],
) -> dict[str, Any]:
    event_path = output_root / "integrated_target_lazy_events.jsonl"
    event_path.write_text("", encoding="utf-8")
    target_master, _target_constraint = _build_persistent_target_master(
        instance,
        cuts=list(initial_cuts),
        outage_column_cuts=list(initial_outage_column_cuts),
        tau=float(incumbent["target_tau"]),
        warm_start_plan=warm_start_plan,
        warm_start_alpha=warm_start_alpha,
        warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
        time_limit_seconds=float(args.target_time_limit_seconds),
        mip_gap=float(args.target_mip_gap),
        pool_solutions=1,
        target_search_objective=str(args.target_search_objective),
        model_name=f"integrated_target_lazy_k{int(instance.ambiguity.k_max_outages)}",
        log_to_console=bool(args.log_to_console),
    )
    target_master.model.Params.LazyConstraints = 1
    target_master.model.Params.TimeLimit = float(args.integrated_lazy_time_limit_seconds)
    target_master.model.Params.MIPGap = float(args.target_mip_gap)
    _apply_optional_target_solver_params(target_master.model, args)
    seen_lazy_keys: set[tuple[tuple[str, ...], str]] = set()
    persisted_lazy_cuts: list[RestrictedMasterCut] = []
    persisted_lazy_outage_rows: list[RestrictedMasterOutageColumnCut] = []
    persisted_global_signatures: set[str] = {
        compute_cut_signature_hash(cut) for cut in initial_cuts
    }
    persisted_row_keys: set[tuple[tuple[str, ...], str]] = {
        (tuple(row.active_line_ids), compute_cut_signature_hash(row.cut))
        for row in initial_outage_column_cuts
    }
    seen_value_lazy_signatures: set[str] = set()
    value_distribution_rows: list[dict[str, Any]] = []
    callback_state: dict[str, Any] = {
        "callback_count": 0,
        "lazy_count": 0,
        "value_lazy_count": 0,
        "duplicate_lazy_count": 0,
        "duplicate_value_lazy_count": 0,
        "nonoptimal_pricing_count": 0,
        "callback_error": "",
        "best_pricing_upper_bound": float(incumbent["pricing_upper_bound"]),
        "found_full_priced_incumbent": False,
        "terminated_reason": "",
    }

    def _record_event(payload: Mapping[str, Any]) -> None:
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")

    def _persist_lazy_cut_variants(
        *,
        cut: RestrictedMasterCut,
        active_line_ids: Sequence[str],
        signature: str,
        callback_index: int,
        pricing_rank: int,
    ) -> dict[str, int]:
        added_global = 0
        added_rowwise = 0
        if bool(args.keep_global_cuts) and signature not in persisted_global_signatures:
            persisted_lazy_cuts.append(cut)
            persisted_global_signatures.add(signature)
            added_global = 1
        variants = (
            _active_line_variants_for_cut(
                cut,
                active_line_ids,
                _parse_int_list(args.integrated_lazy_subset_cut_sizes),
            )
            if bool(args.integrated_lazy_subset_cuts)
            else [tuple(active_line_ids)]
        )
        for variant_index, variant in enumerate(variants, start=1):
            row_key = (tuple(variant), signature)
            if row_key in persisted_row_keys:
                continue
            row = RestrictedMasterOutageColumnCut(
                row_id=(
                    f"integrated_lazy_persist_{callback_index:06d}_"
                    f"{pricing_rank:03d}_{variant_index:03d}_{_outage_column_id(variant)}"
                ),
                column_id=_outage_column_id(variant),
                active_line_ids=tuple(variant),
                cut=cut,
            )
            persisted_lazy_outage_rows.append(row)
            persisted_row_keys.add(row_key)
            added_rowwise += 1
        return {"persisted_global": added_global, "persisted_rowwise": added_rowwise}

    def _callback(model, where):
        if where != GRB.Callback.MIPSOL:
            return
        callback_state["callback_count"] += 1
        callback_index = int(callback_state["callback_count"])
        if callback_index > int(args.integrated_lazy_max_callbacks):
            callback_state["terminated_reason"] = "max_lazy_callbacks"
            model.terminate()
            return
        try:
            z_by_bus = {
                bus: int(round(float(model.cbGetSolution(var))))
                for bus, var in target_master.first_stage.z_by_bus.items()
            }
            n_sl_by_bus = {
                bus: int(round(float(model.cbGetSolution(var))))
                for bus, var in target_master.first_stage.n_sl_by_bus.items()
            }
            n_fa_by_bus = {
                bus: int(round(float(model.cbGetSolution(var))))
                for bus, var in target_master.first_stage.n_fa_by_bus.items()
            }
            plan = build_fixed_first_stage_plan(
                instance,
                z_by_bus=z_by_bus,
                n_sl_by_bus=n_sl_by_bus,
                n_fa_by_bus=n_fa_by_bus,
            )
            solution = SimpleNamespace(
                alpha_value=float(model.cbGetSolution(target_master.alpha_var)),
                lambda_by_line_id={
                    str(line_id): max(0.0, float(model.cbGetSolution(var)))
                    for line_id, var in target_master.lambda_by_line_id.items()
                },
                original_total_objective_value=_callback_original_objective_value(
                    model,
                    target_master,
                ),
            )
            _, pricing_solution = _full_support_pricing(
                instance,
                plan=plan,
                solution=solution,
                forbidden_outage_patterns=None,
                omega_bound_upper=float(args.omega_bound_upper),
                time_limit_seconds=float(args.separation_time_limit_seconds),
                mip_gap=float(args.separation_mip_gap),
                model_name=(
                    f"integrated_target_lazy_k{int(instance.ambiguity.k_max_outages)}_"
                    f"pricing_{callback_index:05d}"
                ),
                log_to_console=bool(args.log_to_console),
            )
            violation_bound = max(
                0.0,
                float(
                    pricing_solution.obj_bound
                    if pricing_solution.obj_bound is not None
                    else (pricing_solution.objective_value or 0.0)
                ),
            )
            violation_value = max(0.0, float(pricing_solution.objective_value or 0.0))
            upper_bound = _pricing_derived_upper_bound(
                instance,
                original_objective_value=float(solution.original_total_objective_value),
                violation_bound=violation_bound,
            )
            active_lines = tuple(_active_outage_lines(pricing_solution.delta_by_line_id))
            event: dict[str, Any] = {
                "callback_index": callback_index,
                "candidate_objective": float(solution.original_total_objective_value),
                "pricing_status": pricing_solution.model_status,
                "pricing_violation_value": violation_value,
                "pricing_violation_bound": violation_bound,
                "pricing_derived_upper_bound": upper_bound,
                "active_lines": ";".join(active_lines),
            }
            if pricing_solution.model_status != "OPTIMAL":
                callback_state["nonoptimal_pricing_count"] += 1
            if (
                pricing_solution.model_status == "OPTIMAL"
                and upper_bound < float(callback_state["best_pricing_upper_bound"])
                - float(args.min_ub_improvement)
            ):
                callback_state["found_full_priced_incumbent"] = True
                callback_state["best_pricing_upper_bound"] = float(upper_bound)
                callback_state["terminated_reason"] = "improved_pricing_derived_upper_bound"
                event["event"] = "improved_pricing_derived_upper_bound"
                _record_event(event)
                model.terminate()
                return
            if violation_bound <= float(args.epsilon_price):
                callback_state["found_full_priced_incumbent"] = True
                callback_state["terminated_reason"] = "target_feasible_full_priced_incumbent"
                event["event"] = "target_feasible_full_priced_incumbent"
                _record_event(event)
                model.terminate()
                return
            cut_result = generate_cut_from_separation_solution(
                instance,
                plan=plan,
                separation_solution=pricing_solution,
                scenario_ids=instance.sets.loaded_disaster_scenarios,
                cut_id=f"integrated_lazy_cut_{callback_index:06d}",
                provenance=f"integrated_target_lazy_{callback_index:06d}",
                lambda_by_line_id=solution.lambda_by_line_id,
                log_to_console=bool(args.log_to_console),
            )
            signature = str(cut_result.cut_signature_hash)
            callback_outage_rows: list[RestrictedMasterOutageColumnCut] = [
                RestrictedMasterOutageColumnCut(
                    row_id=f"integrated_lazy_value_source_{callback_index:06d}_001",
                    column_id=_outage_column_id(active_lines),
                    active_line_ids=tuple(active_lines),
                    cut=cut_result.cut,
                )
            ]
            lazy_stats = _add_lazy_direct_cut_variants(
                model=model,
                master=target_master,
                cut=cut_result.cut,
                active_line_ids=active_lines,
                signature=signature,
                seen_lazy_keys=seen_lazy_keys,
                subset_sizes=_parse_int_list(args.integrated_lazy_subset_cut_sizes),
                enable_subset_cuts=bool(args.integrated_lazy_subset_cuts),
            )
            callback_state["lazy_count"] += int(lazy_stats["added"])
            callback_state["duplicate_lazy_count"] += int(lazy_stats["duplicate"])
            event["event"] = (
                "added_lazy_direct_outage_cut"
                if int(lazy_stats["added"]) > 0
                else "duplicate_lazy_cut"
            )
            event["cut_signature_hash"] = signature
            event["lazy_variant_count"] = lazy_stats["variant_count"]
            event["lazy_added_count"] = lazy_stats["added"]
            event["lazy_duplicate_count"] = lazy_stats["duplicate"]
            event["lazy_added_sizes"] = lazy_stats["added_sizes"]
            event.update(
                _persist_lazy_cut_variants(
                    cut=cut_result.cut,
                    active_line_ids=active_lines,
                    signature=signature,
                    callback_index=callback_index,
                    pricing_rank=1,
                )
            )
            _record_event(event)
            forbidden_patterns = [active_lines]
            for pricing_rank in range(2, int(args.integrated_lazy_top_cuts) + 1):
                _, extra_pricing = _full_support_pricing(
                    instance,
                    plan=plan,
                    solution=solution,
                    forbidden_outage_patterns=forbidden_patterns,
                    omega_bound_upper=float(args.omega_bound_upper),
                    time_limit_seconds=float(args.separation_time_limit_seconds),
                    mip_gap=float(args.separation_mip_gap),
                    model_name=(
                        f"integrated_target_lazy_k{int(instance.ambiguity.k_max_outages)}_"
                        f"pricing_{callback_index:05d}_rank_{pricing_rank:03d}"
                    ),
                    log_to_console=bool(args.log_to_console),
                )
                extra_violation = max(0.0, float(extra_pricing.objective_value or 0.0))
                extra_bound = max(
                    0.0,
                    float(
                        extra_pricing.obj_bound
                        if extra_pricing.obj_bound is not None
                        else (extra_pricing.objective_value or 0.0)
                    ),
                )
                extra_active_lines = tuple(_active_outage_lines(extra_pricing.delta_by_line_id))
                extra_event: dict[str, Any] = {
                    "callback_index": callback_index,
                    "pricing_rank": pricing_rank,
                    "candidate_objective": float(solution.original_total_objective_value),
                    "pricing_status": extra_pricing.model_status,
                    "pricing_violation_value": extra_violation,
                    "pricing_violation_bound": extra_bound,
                    "active_lines": ";".join(extra_active_lines),
                }
                if extra_pricing.model_status != "OPTIMAL":
                    callback_state["nonoptimal_pricing_count"] += 1
                    extra_event["event"] = "top_m_pricing_nonoptimal"
                    _record_event(extra_event)
                    break
                if extra_bound <= float(args.epsilon_price):
                    extra_event["event"] = "top_m_pricing_below_epsilon"
                    _record_event(extra_event)
                    break
                extra_cut_result = generate_cut_from_separation_solution(
                    instance,
                    plan=plan,
                    separation_solution=extra_pricing,
                    scenario_ids=instance.sets.loaded_disaster_scenarios,
                    cut_id=f"integrated_lazy_cut_{callback_index:06d}_{pricing_rank:03d}",
                    provenance=f"integrated_target_lazy_{callback_index:06d}_{pricing_rank:03d}",
                    lambda_by_line_id=solution.lambda_by_line_id,
                    log_to_console=bool(args.log_to_console),
                )
                extra_signature = str(extra_cut_result.cut_signature_hash)
                callback_outage_rows.append(
                    RestrictedMasterOutageColumnCut(
                        row_id=(
                            f"integrated_lazy_value_source_{callback_index:06d}_"
                            f"{pricing_rank:03d}"
                        ),
                        column_id=_outage_column_id(extra_active_lines),
                        active_line_ids=tuple(extra_active_lines),
                        cut=extra_cut_result.cut,
                    )
                )
                extra_lazy_stats = _add_lazy_direct_cut_variants(
                    model=model,
                    master=target_master,
                    cut=extra_cut_result.cut,
                    active_line_ids=extra_active_lines,
                    signature=extra_signature,
                    seen_lazy_keys=seen_lazy_keys,
                    subset_sizes=_parse_int_list(args.integrated_lazy_subset_cut_sizes),
                    enable_subset_cuts=bool(args.integrated_lazy_subset_cuts),
                )
                callback_state["lazy_count"] += int(extra_lazy_stats["added"])
                callback_state["duplicate_lazy_count"] += int(extra_lazy_stats["duplicate"])
                extra_event["event"] = (
                    "added_lazy_direct_outage_cut"
                    if int(extra_lazy_stats["added"]) > 0
                    else "duplicate_lazy_cut"
                )
                extra_event["cut_signature_hash"] = extra_signature
                extra_event["lazy_variant_count"] = extra_lazy_stats["variant_count"]
                extra_event["lazy_added_count"] = extra_lazy_stats["added"]
                extra_event["lazy_duplicate_count"] = extra_lazy_stats["duplicate"]
                extra_event["lazy_added_sizes"] = extra_lazy_stats["added_sizes"]
                extra_event.update(
                    _persist_lazy_cut_variants(
                        cut=extra_cut_result.cut,
                        active_line_ids=extra_active_lines,
                        signature=extra_signature,
                        callback_index=callback_index,
                        pricing_rank=pricing_rank,
                    )
                )
                _record_event(extra_event)
                forbidden_patterns.append(extra_active_lines)
            if bool(args.integrated_lazy_value_cuts):
                source_rows: list[RestrictedMasterOutageColumnCut] = []
                if bool(args.integrated_lazy_value_cut_use_initial_pool):
                    source_rows.extend(initial_outage_column_cuts)
                source_rows.extend(callback_outage_rows)
                value_cut = _build_distributional_value_cut(
                    instance,
                    source_plan=plan,
                    outage_column_cuts=source_rows,
                    cut_id=f"integrated_lazy_value_cut_{callback_index:06d}",
                    max_columns=int(args.integrated_lazy_value_cut_max_columns),
                    subset_sizes=_parse_int_list(args.integrated_lazy_value_cut_subset_sizes),
                    pricing_rounds=int(args.integrated_lazy_value_cut_pricing_rounds),
                    pricing_time_limit_seconds=float(
                        args.integrated_lazy_value_cut_pricing_time_limit_seconds
                    ),
                    pricing_mip_gap=float(args.separation_mip_gap),
                    omega_bound_upper=float(args.omega_bound_upper),
                    log_to_console=False,
                )
                if value_cut is not None and bool(value_cut.get("accepted")):
                    value_signature = _distributional_value_cut_signature(value_cut)
                    value_event = {
                        "callback_index": callback_index,
                        "event": "added_lazy_distributional_value_cut",
                        "value_cut_signature": value_signature,
                        "value_cut_objective": value_cut.get("objective_value"),
                        "value_cut_rhs_at_source": value_cut.get("rhs_at_source"),
                        "value_cut_real_mass": value_cut.get("real_column_mass"),
                        "value_cut_positive_columns": value_cut.get("positive_column_count"),
                        "value_cut_candidate_columns": value_cut.get("candidate_column_count"),
                    }
                    if value_signature in seen_value_lazy_signatures:
                        callback_state["duplicate_value_lazy_count"] += 1
                        value_event["event"] = "duplicate_lazy_distributional_value_cut"
                        _record_event(value_event)
                    else:
                        model.cbLazy(
                            _distributional_value_cut_temp_constr(
                                target_master,
                                value_cut,
                            )
                        )
                        seen_value_lazy_signatures.add(value_signature)
                        callback_state["value_lazy_count"] += 1
                        value_distribution_rows.extend(value_cut.get("distribution_rows", []))
                        _record_event(value_event)
                elif value_cut is not None:
                    _record_event(
                        {
                            "callback_index": callback_index,
                            "event": "rejected_lazy_distributional_value_cut",
                            "reason": value_cut.get("reason", ""),
                            "status": value_cut.get("status", ""),
                        }
                    )
        except Exception as exc:  # pragma: no cover - exercised only in Gurobi callback.
            callback_state["callback_error"] = repr(exc)
            callback_state["terminated_reason"] = "callback_error"
            _record_event({"callback_index": callback_index, "event": "callback_error", "error": repr(exc)})
            model.terminate()

    started = perf_counter()
    target_master.model.optimize(_callback)
    elapsed = perf_counter() - started
    status_name = _status_name(int(target_master.model.Status))
    certified = status_name == "INFEASIBLE" and not str(callback_state["callback_error"])
    integrated_cut_pool_path = output_root / "integrated_target_lazy_cut_pool.json"
    _write_cut_pool(
        integrated_cut_pool_path,
        instance=instance,
        run_config=run_config,
        cuts=list(initial_cuts) + persisted_lazy_cuts,
        outage_column_cuts=list(initial_outage_column_cuts) + persisted_lazy_outage_rows,
    )
    summary = {
        "closure_status": (
            "epsilon_gap_certified_by_integrated_target_lazy_infeasibility"
            if certified
            else f"integrated_target_lazy_{status_name.lower()}"
        ),
        "paper_facing_eligible": bool(certified),
        "validation_level": (
            "epsilon_gap_certified_by_integrated_target_lazy_infeasibility"
            if certified
            else "integrated_target_lazy_diagnostic"
        ),
        "run_log_path": str(run_log_path),
        "trial_certificate_path": incumbent["trial_certificate_path"],
        "pro_response_tex": str(output_root / DEFAULT_PRO_TEX.name)
        if DEFAULT_PRO_TEX.exists()
        else "",
        "cut_pool_path": str(cut_pool_path),
        "cut_pool_audit": list(cut_pool_audit_rows),
        "initial_global_cut_count": len(initial_cuts),
        "initial_outage_column_cut_count": len(initial_outage_column_cuts),
        "persisted_lazy_global_cut_count": len(persisted_lazy_cuts),
        "persisted_lazy_outage_column_cut_count": len(persisted_lazy_outage_rows),
        "integrated_lazy_cut_pool_path": str(integrated_cut_pool_path),
        "initial_pricing_upper_bound": float(incumbent["pricing_upper_bound"]),
        "best_pricing_upper_bound": float(callback_state["best_pricing_upper_bound"]),
        "canonical_lower_bound_from_trial": float(incumbent["canonical_lower_bound"]),
        "epsilon_gap": float(args.epsilon_gap),
        "target_tau": float(incumbent["target_tau"]),
        "target_status": status_name,
        "target_runtime_seconds": elapsed,
        "target_objval": None
        if not hasattr(target_master.model, "ObjVal")
        else float(getattr(target_master.model, "ObjVal")),
        "target_objbound": None
        if not hasattr(target_master.model, "ObjBound")
        else float(getattr(target_master.model, "ObjBound")),
        "target_mip_gap": None
        if not hasattr(target_master.model, "MIPGap")
        else float(getattr(target_master.model, "MIPGap")),
        "callback_state": callback_state,
        "event_path": str(event_path),
        "math_semantics": {
            "canonical_lower_bound_source": "integrated_target_level_infeasibility_only",
            "auxiliary_objective_used_as_lower_bound": False,
            "restricted_support_certification": "forbidden",
            "target_constraint": "canonical_original_objective <= pricing_UB - epsilon_gap",
            "target_search_objective": str(args.target_search_objective),
            "integrated_target_lazy_closure": True,
            "integrated_lazy_top_cuts": int(args.integrated_lazy_top_cuts),
            "integrated_lazy_subset_cuts": bool(args.integrated_lazy_subset_cuts),
            "integrated_lazy_subset_cut_sizes": str(args.integrated_lazy_subset_cut_sizes),
            "integrated_lazy_value_cuts": bool(args.integrated_lazy_value_cuts),
            "integrated_lazy_value_cut_use_initial_pool": bool(
                args.integrated_lazy_value_cut_use_initial_pool
            ),
            "lazy_constraint_type": (
                "valid direct fixed-outage Benders row over alpha/lambda/first-stage variables; "
                "when subset cuts are enabled, selected sub-outage rows use the same valid lifted "
                "cut coefficients with smaller active-line sets"
            ),
            "value_lazy_constraint_type": (
                "valid distributional value cut over alpha + Fp^T lambda and first-stage variables"
            ),
        },
    }
    _write_json(output_root / "integrated_target_lazy_summary.json", summary)
    _write_json(output_root / "target_level_closure_summary.json", summary)
    _write_csv(output_root / "integrated_target_lazy_value_cut_rows.csv", value_distribution_rows)
    report_lines = [
        "# Integrated Target-Level Lazy Closure",
        "",
        f"- Closure status: `{summary['closure_status']}`",
        f"- Paper-facing eligible: `{bool(certified)}`",
        f"- Target status: `{status_name}`",
        f"- Runtime seconds: `{elapsed}`",
        f"- Callback count: `{callback_state['callback_count']}`",
        f"- Lazy cuts added: `{callback_state['lazy_count']}`",
        f"- Value lazy cuts added: `{callback_state['value_lazy_count']}`",
        f"- Duplicate lazy cuts: `{callback_state['duplicate_lazy_count']}`",
        f"- Initial UB: `{incumbent['pricing_upper_bound']}`",
        f"- Best pricing UB: `{callback_state['best_pricing_upper_bound']}`",
        "",
        "Certificate rule: paper-facing only if the integrated target-level model",
        "proves global infeasibility. Time limits and callback terminations remain",
        "diagnostic.",
    ]
    (output_root / "target_level_closure_report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )
    return summary


def _run_single_tree_canonical_lazy_closure(
    args: argparse.Namespace,
    *,
    output_root: Path,
    instance,
    run_config: Mapping[str, Any],
    incumbent: Mapping[str, Any],
    run_log_path: Path,
    cut_pool_path: Path,
    cut_pool_audit_rows: Sequence[Mapping[str, Any]],
    initial_cuts: Sequence[RestrictedMasterCut],
    initial_outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut],
    warm_start_plan: FixedFirstStagePlan,
    warm_start_alpha: float,
    warm_start_lambda_by_line_id: Mapping[str, float],
) -> dict[str, Any]:
    """Run Pro-recommended single-tree canonical objective closure.

    The model keeps the original minimization objective and uses only a safe
    incumbent cutoff. The reported lower bound is the canonical branch-and-cut
    ObjBound, never an auxiliary or target-feasibility objective.
    """

    event_path = output_root / "single_tree_canonical_events.jsonl"
    event_path.write_text("", encoding="utf-8")
    mandatory_completion: dict[str, Any] = {
        "cuts": [],
        "outage_column_cuts": [],
        "audit_rows": [],
        "requested_pattern_count": 0,
        "added_global_count": 0,
        "added_rowwise_count": 0,
    }
    prepared_initial_cuts = list(initial_cuts)
    prepared_initial_outage_column_cuts = list(initial_outage_column_cuts)
    if bool(args.single_tree_mandatory_columns):
        mandatory_completion = _complete_mandatory_outage_columns(
            instance,
            source_plan=warm_start_plan,
            base_cuts=prepared_initial_cuts,
            base_outage_column_cuts=prepared_initial_outage_column_cuts,
            include_zero=bool(args.single_tree_mandatory_zero_column),
            include_singletons=bool(args.single_tree_mandatory_singletons),
            historical_count=int(args.single_tree_mandatory_historical_count),
            cut_id_prefix="single_tree_mandatory",
            log_to_console=bool(args.log_to_console),
        )
        prepared_initial_cuts.extend(mandatory_completion["cuts"])
        prepared_initial_outage_column_cuts.extend(
            mandatory_completion["outage_column_cuts"]
        )
        _write_csv(
            output_root / "single_tree_mandatory_column_completion.csv",
            mandatory_completion["audit_rows"],
        )
    master = build_master_problem(
        instance,
        cuts=prepared_initial_cuts,
        outage_column_cuts=prepared_initial_outage_column_cuts,
        warm_start_plan=warm_start_plan,
        warm_start_alpha=warm_start_alpha,
        warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
        model_name=f"single_tree_canonical_k{int(instance.ambiguity.k_max_outages)}",
        log_to_console=bool(args.log_to_console),
    )
    if master.total_objective_expression is None:
        raise RuntimeError("Canonical master did not expose total objective expression.")

    initial_ub = float(incumbent["pricing_upper_bound"])
    cutoff_constraint = None
    cutoff_rhs: float | None = None
    cutoff_type = "none"
    if bool(args.single_tree_target_cutoff):
        cutoff_rhs = float(incumbent["target_tau"])
        cutoff_type = "tau"
    elif bool(args.single_tree_incumbent_cutoff):
        cutoff_rhs = initial_ub
        cutoff_type = "ub"
    if cutoff_rhs is not None:
        cutoff_constraint = master.model.addConstr(
            master.total_objective_expression <= float(cutoff_rhs),
            name=f"safe_{cutoff_type}_objective_cutoff",
        )

    root_value_cuts: list[dict[str, Any]] = []
    root_value_rows: list[dict[str, Any]] = []
    if int(args.single_tree_root_value_cuts) > 0:
        for idx in range(1, int(args.single_tree_root_value_cuts) + 1):
            value_cut = _build_distributional_value_cut(
                instance,
                source_plan=warm_start_plan,
                outage_column_cuts=prepared_initial_outage_column_cuts,
                cut_id=f"single_tree_root_value_cut_{idx:03d}",
                max_columns=int(args.single_tree_value_cut_max_columns),
                subset_sizes=_parse_int_list(args.single_tree_value_cut_subset_sizes),
                pricing_rounds=int(args.single_tree_value_cut_pricing_rounds),
                pricing_time_limit_seconds=float(
                    args.single_tree_value_cut_pricing_time_limit_seconds
                ),
                pricing_mip_gap=float(args.separation_mip_gap),
                omega_bound_upper=float(args.omega_bound_upper),
                log_to_console=bool(args.log_to_console),
                recompute_source_duals=bool(args.single_tree_value_cut_recompute_source_duals),
                recompute_source_duals_limit=int(
                    args.single_tree_value_cut_recompute_source_duals_limit
                ),
            )
            if value_cut is not None and bool(value_cut.get("accepted")):
                root_value_cuts.append(value_cut)
                root_value_rows.extend(value_cut.get("distribution_rows", []))
                _add_distributional_value_cut_to_master(master, value_cut)

    master.model.Params.LazyConstraints = 1
    if bool(args.single_tree_mipnode_user_cuts):
        master.model.Params.PreCrush = 1
    master.model.Params.TimeLimit = float(args.single_tree_time_limit_seconds)
    master.model.Params.MIPGap = float(args.target_mip_gap)
    master.model.Params.DualReductions = 0
    _apply_optional_target_solver_params(master.model, args)

    seen_lazy_keys: set[tuple[tuple[str, ...], str]] = set()
    seen_user_cut_keys: set[tuple[tuple[str, ...], str]] = set()
    persisted_lazy_cuts: list[RestrictedMasterCut] = []
    persisted_lazy_outage_rows: list[RestrictedMasterOutageColumnCut] = []
    persisted_global_signatures: set[str] = {
        compute_cut_signature_hash(cut) for cut in prepared_initial_cuts
    }
    persisted_row_keys: set[tuple[tuple[str, ...], str]] = {
        (tuple(row.active_line_ids), compute_cut_signature_hash(row.cut))
        for row in prepared_initial_outage_column_cuts
    }
    callback_state: dict[str, Any] = {
        "callback_count": 0,
        "lazy_count": 0,
        "user_cut_count": 0,
        "duplicate_user_cut_count": 0,
        "mipnode_pricing_count": 0,
        "duplicate_lazy_count": 0,
        "nonoptimal_pricing_count": 0,
        "unresolved_pricing_count": 0,
        "full_priced_incumbent_count": 0,
        "best_pricing_upper_bound": initial_ub,
        "best_full_priced_incumbent_objective": None,
        "callback_error": "",
        "terminated_reason": "",
    }
    sdbc_summary: dict[str, Any] = {"enabled": False}
    if bool(args.sdbc_root_closure):
        sdbc_summary = _run_sdbc_root_closure(
            args,
            output_root=output_root,
            instance=instance,
            master=master,
            prepared_initial_cuts=prepared_initial_cuts,
            prepared_initial_outage_column_cuts=prepared_initial_outage_column_cuts,
            persisted_global_signatures=persisted_global_signatures,
            objective_cutoff_rhs=cutoff_rhs,
        )
    fullrow_sdbc_summary: dict[str, Any] = {"enabled": False}
    if bool(args.fullrow_sdbc_root_closure):
        fullrow_sdbc_summary = _run_fullrow_sdbc_root_closure(
            args,
            output_root=output_root,
            master=master,
            target_cutoff_enabled=bool(args.single_tree_target_cutoff),
        )

    def _record_event(payload: Mapping[str, Any]) -> None:
        with event_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(payload), sort_keys=True) + "\n")

    def _callback(model, where):
        if where == GRB.Callback.MIPNODE and bool(args.single_tree_mipnode_user_cuts):
            if int(callback_state["mipnode_pricing_count"]) >= int(
                args.single_tree_mipnode_max_pricing_calls
            ):
                return
            try:
                node_count = float(model.cbGet(GRB.Callback.MIPNODE_NODCNT))
                if bool(args.single_tree_mipnode_root_only) and node_count > 0.5:
                    return
                node_status = int(model.cbGet(GRB.Callback.MIPNODE_STATUS))
                if node_status != GRB.OPTIMAL:
                    return
                callback_state["mipnode_pricing_count"] += 1
                node_index = int(callback_state["mipnode_pricing_count"])
                plan = SimpleNamespace(
                    z_by_bus={
                        bus: float(model.cbGetNodeRel(var))
                        for bus, var in master.first_stage.z_by_bus.items()
                    },
                    n_sl_by_bus={
                        bus: float(model.cbGetNodeRel(var))
                        for bus, var in master.first_stage.n_sl_by_bus.items()
                    },
                    n_fa_by_bus={
                        bus: float(model.cbGetNodeRel(var))
                        for bus, var in master.first_stage.n_fa_by_bus.items()
                    },
                )
                solution = SimpleNamespace(
                    alpha_value=float(model.cbGetNodeRel(master.alpha_var)),
                    lambda_by_line_id={
                        str(line_id): max(0.0, float(model.cbGetNodeRel(var)))
                        for line_id, var in master.lambda_by_line_id.items()
                    },
                    original_total_objective_value=_evaluate_linear_expression_from_values(
                        master.total_objective_expression,
                        lambda var: model.cbGetNodeRel(var),
                    ),
                )
                _, pricing_solution = _full_support_pricing(
                    instance,
                    plan=plan,
                    solution=solution,
                    forbidden_outage_patterns=None,
                    omega_bound_upper=float(args.omega_bound_upper),
                    time_limit_seconds=float(args.single_tree_mipnode_pricing_time_limit_seconds),
                    mip_gap=float(args.separation_mip_gap),
                    model_name=(
                        f"single_tree_node_k{int(instance.ambiguity.k_max_outages)}_"
                        f"pricing_{node_index:05d}"
                    ),
                    log_to_console=bool(args.log_to_console),
                )
                violation_bound = max(
                    0.0,
                    float(
                        pricing_solution.obj_bound
                        if pricing_solution.obj_bound is not None
                        else (pricing_solution.objective_value or 0.0)
                    ),
                )
                active_lines = tuple(_active_outage_lines(pricing_solution.delta_by_line_id))
                event = {
                    "mipnode_pricing_index": node_index,
                    "node_count": node_count,
                    "event": "mipnode_pricing",
                    "pricing_status": pricing_solution.model_status,
                    "pricing_violation_bound": violation_bound,
                    "pricing_violation_value": max(0.0, float(pricing_solution.objective_value or 0.0)),
                    "active_lines": ";".join(active_lines),
                }
                if pricing_solution.objective_value is None or violation_bound <= float(
                    args.single_tree_mipnode_cut_epsilon
                ):
                    _record_event(event)
                    return
                outage = build_fixed_outage_vector(
                    instance,
                    by_line_id={
                        line_id: int(line_id in active_lines)
                        for line_id in instance.sets.line_ids
                    },
                )
                cut_result = generate_structured_cut_from_decompositions(
                    instance,
                    plan=plan,
                    outage=outage,
                    samplewise_decompositions_by_scenario={
                        scenario_id: sample.samplewise_decomposition
                        for scenario_id, sample in pricing_solution.samplewise_dual_solutions.items()
                    },
                    cut_id=f"single_tree_user_cut_{node_index:06d}",
                    provenance=f"single_tree_mipnode_user_cut_{node_index:06d}",
                    source_alpha=solution.alpha_value,
                    source_lambda_by_line_id=solution.lambda_by_line_id,
                    source_violation_value=pricing_solution.objective_value,
                )
                signature = str(cut_result.cut_signature_hash)
                if signature not in persisted_global_signatures:
                    persisted_lazy_cuts.append(cut_result.cut)
                    persisted_global_signatures.add(signature)
                variants = _active_line_variants_for_cut(
                    cut_result.cut,
                    active_lines,
                    _parse_int_list(args.single_tree_mipnode_subset_cut_sizes),
                )
                added = 0
                duplicate = 0
                for variant in variants:
                    key = (tuple(variant), signature)
                    if key in seen_user_cut_keys:
                        duplicate += 1
                        continue
                    model.cbCut(
                        _direct_fixed_outage_temp_constr(
                            master,
                            cut=cut_result.cut,
                            active_line_ids=variant,
                        )
                    )
                    seen_user_cut_keys.add(key)
                    added += 1
                    if key not in persisted_row_keys:
                        row = RestrictedMasterOutageColumnCut(
                            row_id=(
                                f"single_tree_user_persist_{node_index:06d}_"
                                f"{len(persisted_lazy_outage_rows) + 1:03d}_{_outage_column_id(variant)}"
                            ),
                            column_id=_outage_column_id(variant),
                            active_line_ids=tuple(variant),
                            cut=cut_result.cut,
                        )
                        persisted_lazy_outage_rows.append(row)
                        persisted_row_keys.add(key)
                callback_state["user_cut_count"] += added
                callback_state["duplicate_user_cut_count"] += duplicate
                event.update(
                    {
                        "event": "added_mipnode_user_cut" if added else "duplicate_mipnode_user_cut",
                        "cut_signature_hash": signature,
                        "user_cut_added_count": added,
                        "user_cut_duplicate_count": duplicate,
                        "user_cut_variant_count": len(variants),
                    }
                )
                _record_event(event)
                forbidden_patterns = [active_lines]
                for pricing_rank in range(2, int(args.single_tree_mipnode_top_cuts) + 1):
                    if int(callback_state["mipnode_pricing_count"]) >= int(
                        args.single_tree_mipnode_max_pricing_calls
                    ):
                        break
                    callback_state["mipnode_pricing_count"] += 1
                    extra_node_index = int(callback_state["mipnode_pricing_count"])
                    _, extra_pricing = _full_support_pricing(
                        instance,
                        plan=plan,
                        solution=solution,
                        forbidden_outage_patterns=forbidden_patterns,
                        omega_bound_upper=float(args.omega_bound_upper),
                        time_limit_seconds=float(
                            args.single_tree_mipnode_pricing_time_limit_seconds
                        ),
                        mip_gap=float(args.separation_mip_gap),
                        model_name=(
                            f"single_tree_node_k{int(instance.ambiguity.k_max_outages)}_"
                            f"pricing_{extra_node_index:05d}"
                        ),
                        log_to_console=bool(args.log_to_console),
                    )
                    extra_bound = max(
                        0.0,
                        float(
                            extra_pricing.obj_bound
                            if extra_pricing.obj_bound is not None
                            else (extra_pricing.objective_value or 0.0)
                        ),
                    )
                    extra_active_lines = tuple(
                        _active_outage_lines(extra_pricing.delta_by_line_id)
                    )
                    extra_event = {
                        "mipnode_pricing_index": extra_node_index,
                        "pricing_rank": pricing_rank,
                        "node_count": node_count,
                        "event": "mipnode_pricing",
                        "pricing_status": extra_pricing.model_status,
                        "pricing_violation_bound": extra_bound,
                        "pricing_violation_value": max(
                            0.0, float(extra_pricing.objective_value or 0.0)
                        ),
                        "active_lines": ";".join(extra_active_lines),
                    }
                    if extra_pricing.objective_value is None or extra_bound <= float(
                        args.single_tree_mipnode_cut_epsilon
                    ):
                        _record_event(extra_event)
                        break
                    extra_outage = build_fixed_outage_vector(
                        instance,
                        by_line_id={
                            line_id: int(line_id in extra_active_lines)
                            for line_id in instance.sets.line_ids
                        },
                    )
                    extra_cut_result = generate_structured_cut_from_decompositions(
                        instance,
                        plan=plan,
                        outage=extra_outage,
                        samplewise_decompositions_by_scenario={
                            scenario_id: sample.samplewise_decomposition
                            for scenario_id, sample in extra_pricing.samplewise_dual_solutions.items()
                        },
                        cut_id=(
                            f"single_tree_user_cut_{extra_node_index:06d}_"
                            f"{pricing_rank:03d}"
                        ),
                        provenance=(
                            f"single_tree_mipnode_user_cut_{extra_node_index:06d}_"
                            f"{pricing_rank:03d}"
                        ),
                        source_alpha=solution.alpha_value,
                        source_lambda_by_line_id=solution.lambda_by_line_id,
                        source_violation_value=extra_pricing.objective_value,
                    )
                    extra_signature = str(extra_cut_result.cut_signature_hash)
                    if extra_signature not in persisted_global_signatures:
                        persisted_lazy_cuts.append(extra_cut_result.cut)
                        persisted_global_signatures.add(extra_signature)
                    extra_variants = _active_line_variants_for_cut(
                        extra_cut_result.cut,
                        extra_active_lines,
                        _parse_int_list(args.single_tree_mipnode_subset_cut_sizes),
                    )
                    extra_added = 0
                    extra_duplicate = 0
                    for extra_variant in extra_variants:
                        extra_key = (tuple(extra_variant), extra_signature)
                        if extra_key in seen_user_cut_keys:
                            extra_duplicate += 1
                            continue
                        model.cbCut(
                            _direct_fixed_outage_temp_constr(
                                master,
                                cut=extra_cut_result.cut,
                                active_line_ids=extra_variant,
                            )
                        )
                        seen_user_cut_keys.add(extra_key)
                        extra_added += 1
                        if extra_key not in persisted_row_keys:
                            row = RestrictedMasterOutageColumnCut(
                                row_id=(
                                    f"single_tree_user_persist_{extra_node_index:06d}_"
                                    f"{len(persisted_lazy_outage_rows) + 1:03d}_"
                                    f"{_outage_column_id(extra_variant)}"
                                ),
                                column_id=_outage_column_id(extra_variant),
                                active_line_ids=tuple(extra_variant),
                                cut=extra_cut_result.cut,
                            )
                            persisted_lazy_outage_rows.append(row)
                            persisted_row_keys.add(extra_key)
                    callback_state["user_cut_count"] += extra_added
                    callback_state["duplicate_user_cut_count"] += extra_duplicate
                    extra_event.update(
                        {
                            "event": (
                                "added_mipnode_user_cut"
                                if extra_added
                                else "duplicate_mipnode_user_cut"
                            ),
                            "cut_signature_hash": extra_signature,
                            "user_cut_added_count": extra_added,
                            "user_cut_duplicate_count": extra_duplicate,
                            "user_cut_variant_count": len(extra_variants),
                        }
                    )
                    _record_event(extra_event)
                    forbidden_patterns.append(extra_active_lines)
            except Exception as exc:  # pragma: no cover - callback-only guard.
                callback_state["callback_error"] = repr(exc)
                callback_state["terminated_reason"] = "mipnode_callback_error"
                _record_event({"event": "mipnode_callback_error", "error": repr(exc)})
                model.terminate()
            return
        if where != GRB.Callback.MIPSOL:
            return
        callback_state["callback_count"] += 1
        callback_index = int(callback_state["callback_count"])
        if callback_index > int(args.single_tree_max_callbacks):
            callback_state["terminated_reason"] = "max_callbacks"
            model.terminate()
            return
        try:
            z_by_bus = {
                bus: int(round(float(model.cbGetSolution(var))))
                for bus, var in master.first_stage.z_by_bus.items()
            }
            n_sl_by_bus = {
                bus: int(round(float(model.cbGetSolution(var))))
                for bus, var in master.first_stage.n_sl_by_bus.items()
            }
            n_fa_by_bus = {
                bus: int(round(float(model.cbGetSolution(var))))
                for bus, var in master.first_stage.n_fa_by_bus.items()
            }
            plan = build_fixed_first_stage_plan(
                instance,
                z_by_bus=z_by_bus,
                n_sl_by_bus=n_sl_by_bus,
                n_fa_by_bus=n_fa_by_bus,
            )
            solution = SimpleNamespace(
                alpha_value=float(model.cbGetSolution(master.alpha_var)),
                lambda_by_line_id={
                    str(line_id): max(0.0, float(model.cbGetSolution(var)))
                    for line_id, var in master.lambda_by_line_id.items()
                },
                original_total_objective_value=_callback_original_objective_value(
                    model,
                    master,
                ),
            )
            pricing_solutions = []
            forbidden_patterns: list[tuple[str, ...]] = []
            for pricing_rank in range(1, int(args.single_tree_top_cuts) + 1):
                _, pricing_solution = _full_support_pricing(
                    instance,
                    plan=plan,
                    solution=solution,
                    forbidden_outage_patterns=forbidden_patterns,
                    omega_bound_upper=float(args.omega_bound_upper),
                    time_limit_seconds=float(args.separation_time_limit_seconds),
                    mip_gap=float(args.separation_mip_gap),
                    model_name=(
                        f"single_tree_k{int(instance.ambiguity.k_max_outages)}_"
                        f"pricing_{callback_index:05d}_{pricing_rank:03d}"
                    ),
                    log_to_console=bool(args.log_to_console),
                )
                active_lines = tuple(_active_outage_lines(pricing_solution.delta_by_line_id))
                violation_bound = max(
                    0.0,
                    float(
                        pricing_solution.obj_bound
                        if pricing_solution.obj_bound is not None
                        else (pricing_solution.objective_value or 0.0)
                    ),
                )
                violation_value = max(0.0, float(pricing_solution.objective_value or 0.0))
                event: dict[str, Any] = {
                    "callback_index": callback_index,
                    "pricing_rank": pricing_rank,
                    "candidate_objective": float(solution.original_total_objective_value),
                    "pricing_status": pricing_solution.model_status,
                    "pricing_violation_value": violation_value,
                    "pricing_violation_bound": violation_bound,
                    "active_lines": ";".join(active_lines),
                }
                if pricing_solution.model_status != "OPTIMAL":
                    callback_state["nonoptimal_pricing_count"] += 1
                    if pricing_solution.objective_value is None:
                        callback_state["unresolved_pricing_count"] += 1
                        event["event"] = "pricing_unresolved_no_cut"
                        _record_event(event)
                        break
                upper_bound = _pricing_derived_upper_bound(
                    instance,
                    original_objective_value=float(solution.original_total_objective_value),
                    violation_bound=violation_bound,
                )
                event["pricing_derived_upper_bound"] = upper_bound
                if upper_bound < float(callback_state["best_pricing_upper_bound"]):
                    callback_state["best_pricing_upper_bound"] = float(upper_bound)
                    event["improved_pricing_upper_bound"] = True
                if pricing_solution.model_status == "OPTIMAL" and violation_bound <= float(
                    args.epsilon_price
                ):
                    callback_state["full_priced_incumbent_count"] += 1
                    callback_state["best_full_priced_incumbent_objective"] = (
                        float(solution.original_total_objective_value)
                        if callback_state["best_full_priced_incumbent_objective"] is None
                        else min(
                            float(callback_state["best_full_priced_incumbent_objective"]),
                            float(solution.original_total_objective_value),
                        )
                    )
                    event["event"] = "full_priced_incumbent"
                    _record_event(event)
                    break
                if violation_bound <= float(args.epsilon_price):
                    event["event"] = "pricing_bound_below_epsilon_unresolved_status"
                    _record_event(event)
                    break
                pricing_solutions.append((pricing_rank, pricing_solution, active_lines, event))
                forbidden_patterns.append(active_lines)

            for pricing_rank, pricing_solution, active_lines, event in pricing_solutions:
                cut_result = generate_cut_from_separation_solution(
                    instance,
                    plan=plan,
                    separation_solution=pricing_solution,
                    scenario_ids=instance.sets.loaded_disaster_scenarios,
                    cut_id=f"single_tree_lazy_cut_{callback_index:06d}_{pricing_rank:03d}",
                    provenance=f"single_tree_canonical_lazy_{callback_index:06d}_{pricing_rank:03d}",
                    lambda_by_line_id=solution.lambda_by_line_id,
                    log_to_console=bool(args.log_to_console),
                )
                cut_signature = str(cut_result.cut_signature_hash)
                if cut_signature not in persisted_global_signatures:
                    persisted_lazy_cuts.append(cut_result.cut)
                    persisted_global_signatures.add(cut_signature)
                lazy_stats = _add_lazy_direct_cut_variants(
                    model=model,
                    master=master,
                    cut=cut_result.cut,
                    active_line_ids=active_lines,
                    signature=cut_signature,
                    seen_lazy_keys=seen_lazy_keys,
                    subset_sizes=_parse_int_list(args.single_tree_subset_cut_sizes),
                    enable_subset_cuts=bool(args.single_tree_subset_cuts),
                )
                variants = (
                    _active_line_variants_for_cut(
                        cut_result.cut,
                        active_lines,
                        _parse_int_list(args.single_tree_subset_cut_sizes),
                    )
                    if bool(args.single_tree_subset_cuts)
                    else [tuple(active_lines)]
                )
                for variant_index, variant in enumerate(variants, start=1):
                    row_key = (tuple(variant), cut_signature)
                    if row_key in persisted_row_keys:
                        continue
                    row = RestrictedMasterOutageColumnCut(
                        row_id=(
                            f"single_tree_persist_{callback_index:06d}_"
                            f"{pricing_rank:03d}_{variant_index:03d}_{_outage_column_id(variant)}"
                        ),
                        column_id=_outage_column_id(variant),
                        active_line_ids=tuple(variant),
                        cut=cut_result.cut,
                    )
                    persisted_lazy_outage_rows.append(row)
                    persisted_row_keys.add(row_key)
                callback_state["lazy_count"] += int(lazy_stats["added"])
                callback_state["duplicate_lazy_count"] += int(lazy_stats["duplicate"])
                event["event"] = (
                    "added_single_tree_lazy_cut"
                    if int(lazy_stats["added"]) > 0
                    else "duplicate_single_tree_lazy_cut"
                )
                event["cut_signature_hash"] = cut_signature
                event["lazy_added_count"] = int(lazy_stats["added"])
                event["lazy_duplicate_count"] = int(lazy_stats["duplicate"])
                event["lazy_variant_count"] = int(lazy_stats["variant_count"])
                event["lazy_added_sizes"] = lazy_stats["added_sizes"]
                _record_event(event)
        except Exception as exc:  # pragma: no cover - callback-only guard.
            callback_state["callback_error"] = repr(exc)
            callback_state["terminated_reason"] = "callback_error"
            _record_event(
                {
                    "callback_index": callback_index,
                    "event": "callback_error",
                    "error": repr(exc),
                }
            )
            model.terminate()

    started = perf_counter()
    master.model.optimize(_callback)
    elapsed = perf_counter() - started
    status_name = _status_name(int(master.model.Status))
    obj_bound = _canonical_bound(master.model)
    obj_val = None
    try:
        if int(getattr(master.model, "SolCount", 0)) > 0:
            obj_val = float(master.model.ObjVal)
    except Exception:
        obj_val = None
    best_ub = float(callback_state["best_pricing_upper_bound"])
    prior_lb = float(incumbent["canonical_lower_bound"])
    best_available_lb = prior_lb if obj_bound is None else max(prior_lb, float(obj_bound))
    gap = float(best_ub) - float(best_available_lb)
    target_infeasible_certified = (
        bool(args.single_tree_target_cutoff)
        and status_name == "INFEASIBLE"
        and not str(callback_state["callback_error"])
    )
    bound_gap_certified = bool(gap is not None and gap <= float(args.epsilon_gap))
    certified = bool(target_infeasible_certified or bound_gap_certified)
    single_tree_cut_pool_path = output_root / "single_tree_canonical_cut_pool.json"
    _write_cut_pool(
        single_tree_cut_pool_path,
        instance=instance,
        run_config=run_config,
        cuts=list(prepared_initial_cuts) + persisted_lazy_cuts,
        outage_column_cuts=list(prepared_initial_outage_column_cuts) + persisted_lazy_outage_rows,
    )
    summary = {
        "closure_status": (
            "epsilon_gap_certified_by_single_tree_target_infeasibility"
            if target_infeasible_certified
            else "epsilon_gap_certified_by_single_tree_canonical_bound"
            if bound_gap_certified
            else f"single_tree_canonical_{status_name.lower()}"
        ),
        "paper_facing_eligible": bool(certified),
        "validation_level": (
            "epsilon_certified_single_tree_target_infeasibility"
            if target_infeasible_certified
            else "epsilon_certified_single_tree_canonical_bound"
            if bound_gap_certified
            else "single_tree_canonical_diagnostic"
        ),
        "target_status": status_name,
        "runtime_seconds": elapsed,
        "obj_val": obj_val,
        "obj_bound": obj_bound,
        "prior_canonical_lower_bound": prior_lb,
        "best_available_lower_bound": best_available_lb,
        "initial_pricing_upper_bound": initial_ub,
        "best_pricing_upper_bound": best_ub,
        "gap_to_best_available_lb": gap,
        "epsilon_gap": float(args.epsilon_gap),
        "safe_cutoff_enabled": bool(args.single_tree_incumbent_cutoff),
        "target_cutoff_enabled": bool(args.single_tree_target_cutoff),
        "objective_cutoff_type": cutoff_type,
        "safe_cutoff_enabled": bool(cutoff_constraint is not None),
        "safe_cutoff_rhs": cutoff_rhs,
        "callback_state": callback_state,
        "single_tree_mipnode_top_cuts": int(args.single_tree_mipnode_top_cuts),
        "persisted_lazy_global_cut_count": len(persisted_lazy_cuts),
        "persisted_lazy_outage_column_cut_count": len(persisted_lazy_outage_rows),
        "mandatory_column_completion": {
            "enabled": bool(args.single_tree_mandatory_columns),
            "requested_pattern_count": int(
                mandatory_completion["requested_pattern_count"]
            ),
            "added_global_count": int(mandatory_completion["added_global_count"]),
            "added_rowwise_count": int(mandatory_completion["added_rowwise_count"]),
            "audit_path": str(output_root / "single_tree_mandatory_column_completion.csv"),
        },
        "sdbc_root_closure": sdbc_summary,
        "fullrow_sdbc_root_closure": fullrow_sdbc_summary,
        "single_tree_cut_pool_path": str(single_tree_cut_pool_path),
        "root_value_cut_count": len(root_value_cuts),
        "event_path": str(event_path),
        "run_log_path": str(run_log_path),
        "cut_pool_path": str(cut_pool_path),
        "cut_pool_audit": list(cut_pool_audit_rows),
        "pro_response_tex": str(
            Path("/Users/shixinliu/Downloads/evcs_dro_k16_certificate_bpc_next_step.tex")
        ),
        "certificate_rule": (
            "Paper-facing only if best_pricing_upper_bound - canonical ObjBound "
            "<= epsilon_gap, or if the canonical single-tree target model with "
            "objective <= tau is proven infeasible."
        ),
    }
    _write_json(output_root / "single_tree_canonical_summary.json", summary)
    _write_json(output_root / "target_level_closure_summary.json", summary)
    _write_csv(output_root / "single_tree_root_value_cut_rows.csv", root_value_rows)
    (output_root / "single_tree_canonical_report.md").write_text(
        "\n".join(
            [
                "# K=16 Single-Tree Canonical Lazy Closure",
                "",
                f"- Closure status: `{summary['closure_status']}`",
                f"- Paper-facing eligible: `{bool(certified)}`",
                f"- Runtime seconds: `{elapsed}`",
                f"- Status: `{status_name}`",
                f"- ObjBound: `{obj_bound}`",
                f"- Prior canonical LB: `{prior_lb}`",
                f"- Best available LB: `{best_available_lb}`",
                f"- Best pricing UB: `{best_ub}`",
                f"- Gap to best available LB: `{gap}`",
                f"- Lazy cuts added: `{callback_state['lazy_count']}`",
                f"- Root value cuts: `{len(root_value_cuts)}`",
                f"- Mandatory columns added: `{mandatory_completion['added_rowwise_count']}`",
                f"- SDBC cuts added: `{sdbc_summary.get('cut_count', 0)}`",
                f"- SDBC root LP lift: `{sdbc_summary.get('root_lp_lift', None)}`",
                f"- Full-row SDBC cuts added: `{fullrow_sdbc_summary.get('cut_count', 0)}`",
                f"- Full-row SDBC root LP lift: `{fullrow_sdbc_summary.get('root_lp_lift', None)}`",
                f"- Objective cutoff type: `{cutoff_type}`",
                "",
                "Certificate rule: use original-objective branch-and-cut ObjBound for LB,",
                "or target infeasibility under the original objective cutoff.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def run_closure(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    if DEFAULT_PRO_TEX.exists():
        shutil.copy2(DEFAULT_PRO_TEX, output_root / DEFAULT_PRO_TEX.name)

    run_log_path = Path(args.run_log)
    run_log = _read_json(run_log_path)
    audit_json_path = Path(args.audit_json) if args.audit_json else None
    incumbent = _load_valid_incumbent(
        run_log=run_log,
        audit_json_path=audit_json_path,
        epsilon_gap=float(args.epsilon_gap),
    )
    if args.pricing_upper_bound_override is not None:
        upper_bound_override = float(args.pricing_upper_bound_override)
        incumbent["pricing_upper_bound"] = upper_bound_override
        incumbent["initial_gap"] = max(
            0.0,
            upper_bound_override - float(incumbent["canonical_lower_bound"]),
        )
        incumbent["target_tau"] = upper_bound_override - float(args.epsilon_gap)
    run_config, cut_pool_path = _load_engineering_state(run_log)
    extra_cut_pool_paths = _parse_path_list(args.extra_initial_cut_pool_paths)
    benders_config = {
        "initial_cut_pool_paths": [str(cut_pool_path)]
        + [str(path) for path in extra_cut_pool_paths]
    }
    critical_buses = load_critical_buses(args.critical_buses)
    base_instance = load_instance_for_run(run_config, critical_buses=critical_buses)
    instance = prepare_instance_for_run(base_instance, run_config)
    initial_cuts, initial_outage_column_cuts, cut_pool_audit_rows = (
        _load_initial_cuts_from_pools(instance, run_config, benders_config)
    )
    current_cuts = list(initial_cuts)
    current_outage_column_cuts = list(initial_outage_column_cuts)
    seen_global_signatures = {compute_cut_signature_hash(cut) for cut in current_cuts}
    seen_rowwise_keys = {
        (tuple(row.active_line_ids), compute_cut_signature_hash(row.cut))
        for row in current_outage_column_cuts
    }
    trial_plan = _trial_plan(incumbent["certificate"])
    warm_start_plan = build_fixed_first_stage_plan(
        instance,
        z_by_bus=trial_plan.z_by_bus,
        n_sl_by_bus=trial_plan.n_sl_by_bus,
        n_fa_by_bus=trial_plan.n_fa_by_bus,
    )
    warm_start_alpha = float(incumbent["certificate"]["alpha"])
    warm_start_lambda_by_line_id = {
        str(line_id): float(value)
        for line_id, value in dict(incumbent["certificate"]["lambda_by_line_id"]).items()
    }
    if bool(args.value_cut_lb_ascent):
        return _run_value_cut_lb_ascent(
            args,
            output_root=output_root,
            instance=instance,
            incumbent=incumbent,
            run_log_path=run_log_path,
            cut_pool_path=cut_pool_path,
            cut_pool_audit_rows=cut_pool_audit_rows,
            initial_cuts=initial_cuts,
            initial_outage_column_cuts=initial_outage_column_cuts,
            warm_start_plan=warm_start_plan,
            warm_start_alpha=warm_start_alpha,
            warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
        )
    if bool(args.single_tree_canonical_lazy_closure):
        return _run_single_tree_canonical_lazy_closure(
            args,
            output_root=output_root,
            instance=instance,
            run_config=run_config,
            incumbent=incumbent,
            run_log_path=run_log_path,
            cut_pool_path=cut_pool_path,
            cut_pool_audit_rows=cut_pool_audit_rows,
            initial_cuts=initial_cuts,
            initial_outage_column_cuts=initial_outage_column_cuts,
            warm_start_plan=warm_start_plan,
            warm_start_alpha=warm_start_alpha,
            warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
        )
    if bool(args.integrated_target_lazy_closure):
        return _run_integrated_target_lazy_closure(
            args,
            output_root=output_root,
            instance=instance,
            run_config=run_config,
            incumbent=incumbent,
            run_log_path=run_log_path,
            cut_pool_path=cut_pool_path,
            cut_pool_audit_rows=cut_pool_audit_rows,
            initial_cuts=initial_cuts,
            initial_outage_column_cuts=initial_outage_column_cuts,
            warm_start_plan=warm_start_plan,
            warm_start_alpha=warm_start_alpha,
            warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
        )
    U = float(incumbent["pricing_upper_bound"])
    tau = float(incumbent["target_tau"])
    rows: list[dict[str, Any]] = []
    closure_status = "not_started"
    certified = False
    best_pricing_upper_bound = U
    best_target_solution_objective: float | None = None
    cut_index = 1
    exact_plan_nogood_count = 0
    exact_plan_nogood_proofs: list[dict[str, Any]] = []
    persistent_master = None
    persistent_target_constraint = None
    if bool(args.incumbent_capture_mode):
        args.persistent_target_model = True
        args.target_pool_solutions = 1
    if bool(args.persistent_target_model):
        persistent_master, persistent_target_constraint = _build_persistent_target_master(
            instance,
            cuts=current_cuts,
            outage_column_cuts=current_outage_column_cuts,
            tau=tau,
            warm_start_plan=warm_start_plan,
            warm_start_alpha=warm_start_alpha,
            warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
            time_limit_seconds=float(args.target_time_limit_seconds),
            mip_gap=float(args.target_mip_gap),
            pool_solutions=int(args.target_pool_solutions),
            target_search_objective=str(args.target_search_objective),
            model_name=f"persistent_target_level_k{int(instance.ambiguity.k_max_outages)}",
            log_to_console=bool(args.log_to_console),
        )
        _apply_optional_target_solver_params(persistent_master.model, args)

    closure_cut_pool_path = output_root / "target_level_closure_cut_pool.json"

    def _checkpoint_closure_state() -> None:
        _write_cut_pool(
            closure_cut_pool_path,
            instance=instance,
            run_config=run_config,
            cuts=current_cuts,
            outage_column_cuts=current_outage_column_cuts,
        )

    for iteration in range(1, int(args.max_closure_iterations) + 1):
        master_start = perf_counter()
        captured_candidate = None
        captured_candidates: list[dict[str, Any]] = []
        if bool(args.incumbent_capture_mode):
            if persistent_master is None or persistent_target_constraint is None:
                raise RuntimeError("incumbent_capture_mode requires a persistent target master.")
            persistent_target_constraint.RHS = float(tau)
            persistent_master.model.update()
            captured_candidates = _capture_target_incumbents(
                instance,
                persistent_master,
                max_candidates=int(args.incumbent_capture_candidates),
                min_candidates=int(args.incumbent_capture_min_candidates),
                window_seconds=float(args.incumbent_capture_window_seconds),
                target_search_objective=str(args.target_search_objective),
            )
            captured_candidate = captured_candidates[0] if captured_candidates else None
            master = persistent_master
            if captured_candidate is None:
                solution = extract_master_problem_solution(master)
            else:
                solution = captured_candidate["solution"]
        elif persistent_master is not None and persistent_target_constraint is not None:
            master = persistent_master
            solution = _optimize_existing_target_master(
                master,
                tau=tau,
                target_constraint=persistent_target_constraint,
            )
        else:
            master, solution = _solve_target_level_master(
                instance,
                cuts=current_cuts,
                outage_column_cuts=current_outage_column_cuts,
                tau=tau,
                warm_start_plan=warm_start_plan,
                warm_start_alpha=warm_start_alpha,
                warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
                time_limit_seconds=float(args.target_time_limit_seconds),
                mip_gap=float(args.target_mip_gap),
                pool_solutions=int(args.target_pool_solutions),
                target_search_objective=str(args.target_search_objective),
                model_name=f"target_level_k{int(instance.ambiguity.k_max_outages)}_{iteration:03d}",
                log_to_console=bool(args.log_to_console),
            )
        master_seconds = perf_counter() - master_start
        status = (
            "INCUMBENT_CAPTURED"
            if captured_candidate is not None
            else _status_name(solution.raw_status_code)
        )
        row: dict[str, Any] = {
            "iteration": iteration,
            "U": U,
            "epsilon_gap": float(args.epsilon_gap),
            "tau": tau,
            "target_status": status,
            "target_sol_count": int(getattr(master.model, "SolCount", 0)),
            "captured_candidate_count": len(captured_candidates),
            "target_objval": solution.original_total_objective_value,
            "target_objbound": (
                None
                if not hasattr(master.model, "ObjBound")
                else float(getattr(master.model, "ObjBound"))
            ),
            "target_mip_gap": (
                None
                if not hasattr(master.model, "MIPGap")
                else float(getattr(master.model, "MIPGap"))
            ),
            "target_master_seconds": master_seconds,
            "global_cut_count": len(current_cuts),
            "outage_column_cut_count": len(current_outage_column_cuts),
        }
        if status == "INFEASIBLE":
            closure_status = "epsilon_gap_certified_by_target_infeasibility"
            certified = True
            row["closure_event"] = closure_status
            rows.append(row)
            _write_csv(output_root / "target_level_closure_trace.csv", rows)
            _checkpoint_closure_state()
            break
        if captured_candidate is None and solution.objective_value is None:
            closure_status = f"target_level_{status.lower()}_without_feasible_point"
            row["closure_event"] = closure_status
            rows.append(row)
            _write_csv(output_root / "target_level_closure_trace.csv", rows)
            _checkpoint_closure_state()
            break

        best_target_solution_objective = (
            float(solution.original_total_objective_value)
            if best_target_solution_objective is None
            else (
                max(best_target_solution_objective, float(solution.original_total_objective_value))
                if str(args.target_search_objective) == "max_original"
                else min(best_target_solution_objective, float(solution.original_total_objective_value))
            )
        )
        pool_candidates = (
            captured_candidates
            if bool(args.incumbent_capture_mode)
            else _target_pool_candidates(
                instance,
                master,
                max_solutions=int(args.target_pool_solutions),
            )
        )
        plan = (
            captured_candidate["plan"]
            if captured_candidate is not None
            else _plan_from_solution(instance, solution)
        )
        _, pricing_solution = _full_support_pricing(
            instance,
            plan=plan,
            solution=solution,
            forbidden_outage_patterns=None,
            omega_bound_upper=float(args.omega_bound_upper),
            time_limit_seconds=float(args.separation_time_limit_seconds),
            mip_gap=float(args.separation_mip_gap),
            model_name=f"target_level_k{int(instance.ambiguity.k_max_outages)}_pricing_{iteration:03d}",
            log_to_console=bool(args.log_to_console),
        )
        pricing_violation_value = max(0.0, float(pricing_solution.objective_value or 0.0))
        pricing_violation_bound = max(
            0.0,
            float(
                pricing_solution.obj_bound
                if pricing_solution.obj_bound is not None
                else (pricing_solution.objective_value or 0.0)
            ),
        )
        U_new = _pricing_derived_upper_bound(
            instance,
            original_objective_value=float(solution.original_total_objective_value or 0.0),
            violation_bound=pricing_violation_bound,
        )
        row.update(
            {
                "pricing_status": pricing_solution.model_status,
                "pricing_objval": pricing_solution.objective_value,
                "pricing_objbound": pricing_solution.obj_bound,
                "pricing_mip_gap": pricing_solution.mip_gap,
                "pricing_node_count": pricing_solution.node_count,
                "pricing_violation_value": pricing_violation_value,
                "pricing_violation_bound": pricing_violation_bound,
                "pricing_derived_upper_bound": U_new,
                "selected_active_lines": ";".join(
                    _active_outage_lines(pricing_solution.delta_by_line_id)
                ),
            }
        )
        if (
            pricing_solution.model_status == "OPTIMAL"
            and U_new < U - float(args.min_ub_improvement)
        ):
            U = float(U_new)
            tau = U - float(args.epsilon_gap)
            best_pricing_upper_bound = min(best_pricing_upper_bound, U)
            warm_start_plan = plan
            warm_start_alpha = float(solution.alpha_value)
            warm_start_lambda_by_line_id = dict(solution.lambda_by_line_id)
            row["closure_event"] = "updated_pricing_derived_upper_bound"
            rows.append(row)
            _write_csv(output_root / "target_level_closure_trace.csv", rows)
            _checkpoint_closure_state()
            continue
        if pricing_violation_bound <= float(args.epsilon_price):
            closure_status = "target_feasible_full_priced_incumbent_no_gap_closure"
            row["closure_event"] = closure_status
            rows.append(row)
            _write_csv(output_root / "target_level_closure_trace.csv", rows)
            _checkpoint_closure_state()
            break

        pricing_solutions = [pricing_solution]
        forbidden_patterns = [_active_outage_lines(pricing_solution.delta_by_line_id)]
        for rank in range(2, int(args.target_top_cuts) + 1):
            _, extra_pricing = _full_support_pricing(
                instance,
                plan=plan,
                solution=solution,
                forbidden_outage_patterns=forbidden_patterns,
                omega_bound_upper=float(args.omega_bound_upper),
                time_limit_seconds=float(args.separation_time_limit_seconds),
                mip_gap=float(args.separation_mip_gap),
                model_name=(
                    f"target_level_k{int(instance.ambiguity.k_max_outages)}_"
                    f"pricing_{iteration:03d}_rank_{rank:03d}"
                ),
                log_to_console=bool(args.log_to_console),
            )
            if extra_pricing.model_status != "OPTIMAL":
                row["top_m_truncated_status"] = extra_pricing.model_status
                break
            extra_violation = max(0.0, float(extra_pricing.objective_value or 0.0))
            if extra_violation <= float(args.epsilon_price):
                break
            pricing_solutions.append(extra_pricing)
            forbidden_patterns.append(_active_outage_lines(extra_pricing.delta_by_line_id))

        cut_infos: list[dict[str, Any]] = []
        added_global_count = 0
        added_rowwise_count = 0
        for pricing_rank, selected_pricing_solution in enumerate(pricing_solutions, start=1):
            cut_info = _append_valid_cut(
                instance,
                current_cuts=current_cuts,
                current_outage_column_cuts=current_outage_column_cuts,
                seen_global_signatures=seen_global_signatures,
                seen_rowwise_keys=seen_rowwise_keys,
                plan=plan,
                separation_solution=selected_pricing_solution,
                lambda_by_line_id=solution.lambda_by_line_id,
                cut_index=cut_index,
                keep_global_cuts=bool(args.keep_global_cuts),
                persistent_master=persistent_master,
                direct_fixed_outage_rows=bool(args.direct_fixed_outage_rows),
                enable_subset_cuts=bool(args.target_subset_cuts),
                subset_cut_sizes=_parse_int_list(args.target_subset_cut_sizes),
                log_to_console=bool(args.log_to_console),
            )
            cut_index += 1
            cut_info["pricing_rank"] = pricing_rank
            cut_infos.append(cut_info)
            added_global_count += int(bool(cut_info["added_global"]))
            added_rowwise_count += int(cut_info.get("added_rowwise_count", int(bool(cut_info["added_rowwise"]))))
        first_cut_info = cut_infos[0] if cut_infos else {}
        row.update(first_cut_info)
        row["top_m_pricing_count"] = len(pricing_solutions)
        row["added_global_count"] = added_global_count
        row["added_rowwise_count"] = added_rowwise_count
        row["all_active_lines"] = " | ".join(str(info.get("active_lines", "")) for info in cut_infos)
        row["target_pool_candidate_count"] = len(pool_candidates)
        pool_added_global_count = 0
        pool_added_rowwise_count = 0
        pool_priced_candidate_count = 0
        for candidate in pool_candidates[1:]:
            _, pool_pricing = _full_support_pricing(
                instance,
                plan=candidate["plan"],
                solution=candidate["solution"],
                forbidden_outage_patterns=None,
                omega_bound_upper=float(args.omega_bound_upper),
                time_limit_seconds=float(args.separation_time_limit_seconds),
                mip_gap=float(args.separation_mip_gap),
                model_name=(
                    f"target_level_k{int(instance.ambiguity.k_max_outages)}_"
                    f"pricing_{iteration:03d}_pool_{int(candidate['pool_index']):03d}"
                ),
                log_to_console=bool(args.log_to_console),
            )
            pool_priced_candidate_count += 1
            pool_violation = max(0.0, float(pool_pricing.objective_value or 0.0))
            if pool_pricing.model_status != "OPTIMAL" or pool_violation <= float(args.epsilon_price):
                continue
            pool_cut_info = _append_valid_cut(
                instance,
                current_cuts=current_cuts,
                current_outage_column_cuts=current_outage_column_cuts,
                seen_global_signatures=seen_global_signatures,
                seen_rowwise_keys=seen_rowwise_keys,
                plan=candidate["plan"],
                separation_solution=pool_pricing,
                lambda_by_line_id=candidate["solution"].lambda_by_line_id,
                cut_index=cut_index,
                keep_global_cuts=bool(args.keep_global_cuts),
                persistent_master=persistent_master,
                direct_fixed_outage_rows=bool(args.direct_fixed_outage_rows),
                enable_subset_cuts=bool(args.target_subset_cuts),
                subset_cut_sizes=_parse_int_list(args.target_subset_cut_sizes),
                log_to_console=bool(args.log_to_console),
            )
            cut_index += 1
            pool_added_global_count += int(bool(pool_cut_info["added_global"]))
            pool_added_rowwise_count += int(
                pool_cut_info.get("added_rowwise_count", int(bool(pool_cut_info["added_rowwise"])))
            )
        row["pool_priced_candidate_count"] = pool_priced_candidate_count
        row["pool_added_global_count"] = pool_added_global_count
        row["pool_added_rowwise_count"] = pool_added_rowwise_count
        row["added_global_count"] = added_global_count + pool_added_global_count
        row["added_rowwise_count"] = added_rowwise_count + pool_added_rowwise_count
        nogood_added = False
        promoted_oracle_row_count = 0
        if bool(args.exact_plan_nogoods):
            oracle_start = perf_counter()
            try:
                proof = _fixed_plan_lb_oracle(
                    instance,
                    plan=plan,
                    outage_column_cuts=current_outage_column_cuts,
                    tau=float(tau),
                    max_columns=int(args.exact_plan_lb_max_columns),
                    pricing_rounds=int(args.exact_plan_lb_pricing_rounds),
                    pricing_time_limit_seconds=float(
                        args.exact_plan_lb_pricing_time_limit_seconds
                    ),
                    pricing_mip_gap=(
                        float(args.separation_mip_gap)
                        if float(args.exact_plan_lb_pricing_mip_gap) < 0.0
                        else float(args.exact_plan_lb_pricing_mip_gap)
                    ),
                    omega_bound_upper=float(args.omega_bound_upper),
                    epsilon_price=float(args.epsilon_price),
                    log_to_console=bool(args.log_to_console),
                    trace_path=(
                        output_root
                        / f"fixed_plan_lb_oracle_iter_{int(iteration):03d}.jsonl"
                    ),
                    cut_id_prefix=f"fixed_plan_lb_iter_{int(iteration):03d}",
                )
                generated_oracle_rows = list(proof.pop("_generated_outage_column_cuts", []))
                duplicate_oracle_row_count = 0
                for oracle_row in generated_oracle_rows:
                    oracle_key = (
                        tuple(oracle_row.active_line_ids),
                        compute_cut_signature_hash(oracle_row.cut),
                    )
                    if oracle_key in seen_rowwise_keys:
                        duplicate_oracle_row_count += 1
                        continue
                    current_outage_column_cuts.append(oracle_row)
                    seen_rowwise_keys.add(oracle_key)
                    if persistent_master is not None:
                        if bool(args.direct_fixed_outage_rows):
                            _add_direct_fixed_outage_cut_to_existing_master(
                                persistent_master,
                                cut=oracle_row.cut,
                                active_line_ids=oracle_row.active_line_ids,
                                row_id=oracle_row.row_id,
                            )
                        else:
                            _add_outage_column_cut_to_existing_master(
                                persistent_master,
                                oracle_row,
                            )
                    promoted_oracle_row_count += 1
                proof["iteration"] = iteration
                proof["oracle_seconds"] = perf_counter() - oracle_start
                proof["promoted_oracle_row_count"] = promoted_oracle_row_count
                proof["duplicate_oracle_row_count"] = duplicate_oracle_row_count
                proof["plan"] = {
                    "z_by_bus": {str(bus): int(value) for bus, value in plan.z_by_bus.items()},
                    "n_sl_by_bus": {
                        str(bus): int(value) for bus, value in plan.n_sl_by_bus.items()
                    },
                    "n_fa_by_bus": {
                        str(bus): int(value) for bus, value in plan.n_fa_by_bus.items()
                    },
                }
                exact_plan_nogood_proofs.append(proof)
                row["exact_plan_lb_status"] = proof.get("status")
                row["exact_plan_lb"] = proof.get("fixed_plan_objective_lb")
                row["exact_plan_lb_margin_above_tau"] = proof.get("margin_above_tau")
                row["exact_plan_lb_column_count"] = dict(proof.get("fixed_dual", {})).get(
                    "column_count"
                )
                row["exact_plan_lb_oracle_seconds"] = proof["oracle_seconds"]
                row["exact_plan_lb_pricing_rounds_used"] = proof.get(
                    "pricing_rounds_used"
                )
                row["exact_plan_lb_local_generated_column_count"] = proof.get(
                    "local_generated_column_count"
                )
                row["exact_plan_lb_promoted_oracle_row_count"] = promoted_oracle_row_count
                row["exact_plan_lb_duplicate_oracle_row_count"] = duplicate_oracle_row_count
                pricing_events = list(proof.get("pricing_events", []))
                if pricing_events:
                    last_pricing_event = dict(pricing_events[-1])
                    row["exact_plan_lb_last_pricing_status"] = last_pricing_event.get(
                        "pricing_status"
                    )
                    row["exact_plan_lb_last_pricing_violation_bound"] = (
                        last_pricing_event.get("pricing_violation_bound")
                    )
                    row["exact_plan_lb_last_pricing_active_lines"] = (
                        last_pricing_event.get("active_lines")
                    )
                if bool(proof.get("proved_above_tau")):
                    if persistent_master is None:
                        row["exact_plan_nogood_event"] = (
                            "proved_but_not_added_without_persistent_master"
                        )
                    else:
                        exact_plan_nogood_count += 1
                        nogood_id = f"exact_plan_ng_{exact_plan_nogood_count:05d}"
                        _add_exact_plan_nogood_to_existing_master(
                            persistent_master,
                            plan=plan,
                            nogood_id=nogood_id,
                        )
                        row["exact_plan_nogood_event"] = "added_exact_plan_nogood"
                        row["exact_plan_nogood_id"] = nogood_id
                        nogood_added = True
                else:
                    row["exact_plan_nogood_event"] = "not_proved"
            except Exception as exc:
                row["exact_plan_nogood_event"] = "oracle_error"
                row["exact_plan_nogood_error"] = repr(exc)
        row["closure_event"] = (
            "added_valid_cut"
            if (
                row["added_global_count"] > 0
                or row["added_rowwise_count"] > 0
                or promoted_oracle_row_count > 0
            )
            else "added_exact_plan_nogood"
            if nogood_added
            else "duplicate_cut_no_progress"
        )
        rows.append(row)
        _write_csv(output_root / "target_level_closure_trace.csv", rows)
        _write_json(output_root / "exact_plan_nogood_proofs.json", {"proofs": exact_plan_nogood_proofs})
        _checkpoint_closure_state()
        if (
            row["added_global_count"] == 0
            and row["added_rowwise_count"] == 0
            and promoted_oracle_row_count == 0
            and not nogood_added
        ):
            closure_status = "duplicate_cut_no_progress"
            break

    else:
        closure_status = "max_closure_iterations"

    summary = {
        "closure_status": closure_status,
        "paper_facing_eligible": bool(certified),
        "validation_level": (
            "epsilon_gap_certified_by_target_infeasibility"
            if certified
            else "target_level_closure_diagnostic"
        ),
        "run_log_path": str(run_log_path),
        "trial_certificate_path": incumbent["trial_certificate_path"],
        "pro_response_tex": str(output_root / DEFAULT_PRO_TEX.name)
        if DEFAULT_PRO_TEX.exists()
        else "",
        "cut_pool_path": str(cut_pool_path),
        "cut_pool_audit": cut_pool_audit_rows,
        "initial_global_cut_count": len(initial_cuts),
        "initial_outage_column_cut_count": len(initial_outage_column_cuts),
        "final_global_cut_count": len(current_cuts),
        "final_outage_column_cut_count": len(current_outage_column_cuts),
        "exact_plan_nogood_count": exact_plan_nogood_count,
        "exact_plan_nogood_proof_path": str(output_root / "exact_plan_nogood_proofs.json"),
        "initial_pricing_upper_bound": float(incumbent["pricing_upper_bound"]),
        "best_pricing_upper_bound": float(best_pricing_upper_bound),
        "canonical_lower_bound_from_trial": float(incumbent["canonical_lower_bound"]),
        "epsilon_gap": float(args.epsilon_gap),
        "initial_gap": float(incumbent["initial_gap"]),
        "target_tau": float(tau),
        "best_target_solution_objective": best_target_solution_objective,
        "trace_path": str(output_root / "target_level_closure_trace.csv"),
        "closure_cut_pool_path": str(closure_cut_pool_path),
        "math_semantics": {
            "canonical_lower_bound_source": "target_level_infeasibility_only",
            "auxiliary_objective_used_as_lower_bound": False,
            "restricted_support_certification": "forbidden",
            "target_constraint": "canonical_original_objective <= pricing_UB - epsilon_gap",
            "target_search_objective": str(args.target_search_objective),
            "persistent_target_model": bool(args.persistent_target_model),
            "incumbent_capture_mode": bool(args.incumbent_capture_mode),
            "incumbent_capture_candidates": int(args.incumbent_capture_candidates),
            "incumbent_capture_min_candidates": int(args.incumbent_capture_min_candidates),
            "incumbent_capture_window_seconds": float(args.incumbent_capture_window_seconds),
            "direct_fixed_outage_rows": bool(args.direct_fixed_outage_rows),
            "target_subset_cuts": bool(args.target_subset_cuts),
            "target_subset_cut_sizes": str(args.target_subset_cut_sizes),
            "exact_plan_nogoods": bool(args.exact_plan_nogoods),
            "exact_plan_lb_max_columns": int(args.exact_plan_lb_max_columns),
            "exact_plan_lb_pricing_rounds": int(args.exact_plan_lb_pricing_rounds),
            "exact_plan_lb_pricing_time_limit_seconds": float(
                args.exact_plan_lb_pricing_time_limit_seconds
            ),
            "exact_plan_lb_pricing_mip_gap": (
                float(args.separation_mip_gap)
                if float(args.exact_plan_lb_pricing_mip_gap) < 0.0
                else float(args.exact_plan_lb_pricing_mip_gap)
            ),
        },
    }
    _write_json(output_root / "target_level_closure_summary.json", summary)
    report_lines = [
        "# Incumbent-Guarded Target-Level Closure",
        "",
        f"- Closure status: `{closure_status}`",
        f"- Paper-facing eligible: `{bool(certified)}`",
        f"- Initial UB: `{incumbent['pricing_upper_bound']}`",
        f"- Trial canonical LB: `{incumbent['canonical_lower_bound']}`",
        f"- Initial gap: `{incumbent['initial_gap']}`",
        f"- Epsilon gap target: `{float(args.epsilon_gap)}`",
        f"- Initial tau: `{incumbent['target_tau']}`",
        f"- Final tau: `{tau}`",
        f"- Initial cuts: `{len(initial_cuts)}` global, `{len(initial_outage_column_cuts)}` row-wise",
        f"- Final cuts: `{len(current_cuts)}` global, `{len(current_outage_column_cuts)}` row-wise",
        f"- Exact-plan no-goods: `{exact_plan_nogood_count}`",
        "",
        "Certificate rule: this row is paper-facing only if target-level canonical",
        "infeasibility is proven globally. Time limits, feasible target points, and",
        "duplicate-cut stops remain diagnostic.",
    ]
    (output_root / "target_level_closure_report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-log", default=str(DEFAULT_K16_RUN_LOG))
    parser.add_argument("--audit-json", default=str(DEFAULT_AUDIT_JSON))
    parser.add_argument("--extra-initial-cut-pool-paths", default="")
    parser.add_argument("--pricing-upper-bound-override", type=float, default=None)
    parser.add_argument(
        "--output-root",
        default="results/engineering_acceleration/incumbent_guarded_closure_k16",
    )
    parser.add_argument("--critical-buses", default=str(CRITICAL_BUSES))
    parser.add_argument("--epsilon-gap", type=float, default=100.0)
    parser.add_argument("--epsilon-price", type=float, default=100.0)
    parser.add_argument("--max-closure-iterations", type=int, default=10)
    parser.add_argument("--target-time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--target-mip-gap", type=float, default=0.0)
    parser.add_argument("--target-threads", type=int, default=0)
    parser.add_argument("--target-mip-focus", type=int, default=-1)
    parser.add_argument("--target-presolve", type=int, default=-1)
    parser.add_argument("--target-cuts", type=int, default=-1)
    parser.add_argument("--target-heuristics", type=float, default=-1.0)
    parser.add_argument("--separation-time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.02)
    parser.add_argument("--target-top-cuts", type=int, default=1)
    parser.add_argument("--target-subset-cuts", action="store_true")
    parser.add_argument("--target-subset-cut-sizes", default="1,2,4,8,16")
    parser.add_argument("--target-pool-solutions", type=int, default=1)
    parser.add_argument(
        "--target-search-objective",
        choices=("min_original", "max_original", "feasibility"),
        default="min_original",
    )
    parser.add_argument("--persistent-target-model", action="store_true")
    parser.add_argument("--exact-plan-nogoods", action="store_true")
    parser.add_argument("--exact-plan-lb-max-columns", type=int, default=400)
    parser.add_argument("--exact-plan-lb-pricing-rounds", type=int, default=0)
    parser.add_argument("--exact-plan-lb-pricing-time-limit-seconds", type=float, default=180.0)
    parser.add_argument(
        "--exact-plan-lb-pricing-mip-gap",
        type=float,
        default=-1.0,
        help="Use separation MIP gap when negative.",
    )
    parser.add_argument("--incumbent-capture-mode", action="store_true")
    parser.add_argument("--incumbent-capture-candidates", type=int, default=1)
    parser.add_argument("--incumbent-capture-min-candidates", type=int, default=1)
    parser.add_argument("--incumbent-capture-window-seconds", type=float, default=0.0)
    parser.add_argument("--integrated-target-lazy-closure", action="store_true")
    parser.add_argument("--integrated-lazy-time-limit-seconds", type=float, default=1800.0)
    parser.add_argument("--integrated-lazy-max-callbacks", type=int, default=200)
    parser.add_argument("--integrated-lazy-top-cuts", type=int, default=1)
    parser.add_argument("--integrated-lazy-subset-cuts", action="store_true")
    parser.add_argument("--integrated-lazy-subset-cut-sizes", default="1,2,4,8,16")
    parser.add_argument("--integrated-lazy-value-cuts", action="store_true")
    parser.add_argument("--integrated-lazy-value-cut-max-columns", type=int, default=600)
    parser.add_argument("--integrated-lazy-value-cut-subset-sizes", default="1,2,4,8,16")
    parser.add_argument("--integrated-lazy-value-cut-pricing-rounds", type=int, default=0)
    parser.add_argument(
        "--integrated-lazy-value-cut-pricing-time-limit-seconds",
        type=float,
        default=120.0,
    )
    parser.add_argument("--integrated-lazy-value-cut-use-initial-pool", action="store_true", default=True)
    parser.add_argument(
        "--no-integrated-lazy-value-cut-use-initial-pool",
        dest="integrated_lazy_value_cut_use_initial_pool",
        action="store_false",
    )
    parser.add_argument("--single-tree-canonical-lazy-closure", action="store_true")
    parser.add_argument("--single-tree-time-limit-seconds", type=float, default=1800.0)
    parser.add_argument("--single-tree-max-callbacks", type=int, default=300)
    parser.add_argument("--single-tree-top-cuts", type=int, default=1)
    parser.add_argument("--single-tree-subset-cuts", action="store_true")
    parser.add_argument("--single-tree-subset-cut-sizes", default="1,2,4,8,16")
    parser.add_argument("--single-tree-mipnode-user-cuts", action="store_true")
    parser.add_argument("--single-tree-mipnode-root-only", action="store_true", default=True)
    parser.add_argument(
        "--no-single-tree-mipnode-root-only",
        dest="single_tree_mipnode_root_only",
        action="store_false",
    )
    parser.add_argument("--single-tree-mipnode-max-pricing-calls", type=int, default=5)
    parser.add_argument("--single-tree-mipnode-top-cuts", type=int, default=1)
    parser.add_argument("--single-tree-mipnode-pricing-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--single-tree-mipnode-cut-epsilon", type=float, default=100.0)
    parser.add_argument("--single-tree-mipnode-subset-cut-sizes", default="4,8,16")
    parser.add_argument("--single-tree-incumbent-cutoff", action="store_true", default=True)
    parser.add_argument(
        "--no-single-tree-incumbent-cutoff",
        dest="single_tree_incumbent_cutoff",
        action="store_false",
    )
    parser.add_argument("--single-tree-target-cutoff", action="store_true")
    parser.add_argument("--single-tree-root-value-cuts", type=int, default=0)
    parser.add_argument("--single-tree-mandatory-columns", action="store_true")
    parser.add_argument("--single-tree-mandatory-zero-column", action="store_true", default=True)
    parser.add_argument(
        "--no-single-tree-mandatory-zero-column",
        dest="single_tree_mandatory_zero_column",
        action="store_false",
    )
    parser.add_argument("--single-tree-mandatory-singletons", action="store_true", default=True)
    parser.add_argument(
        "--no-single-tree-mandatory-singletons",
        dest="single_tree_mandatory_singletons",
        action="store_false",
    )
    parser.add_argument("--single-tree-mandatory-historical-count", type=int, default=0)
    parser.add_argument("--single-tree-value-cut-max-columns", type=int, default=600)
    parser.add_argument("--single-tree-value-cut-subset-sizes", default="1,2,4,8,16")
    parser.add_argument("--single-tree-value-cut-pricing-rounds", type=int, default=0)
    parser.add_argument(
        "--single-tree-value-cut-pricing-time-limit-seconds",
        type=float,
        default=300.0,
    )
    parser.add_argument("--single-tree-value-cut-recompute-source-duals", action="store_true")
    parser.add_argument("--single-tree-value-cut-recompute-source-duals-limit", type=int, default=0)
    parser.add_argument(
        "--sdbc-root-closure",
        action="store_true",
        help=(
            "Run Pro-reviewed split-disjunctive Benders closure at the canonical "
            "single-tree root before the branch-and-cut solve. Diagnostic unless "
            "canonical ObjBound/target infeasibility closes the certificate."
        ),
    )
    parser.add_argument("--sdbc-max-registry-rows", type=int, default=250)
    parser.add_argument("--sdbc-root-pricing-rounds", type=int, default=2)
    parser.add_argument("--sdbc-root-pricing-time-limit-seconds", type=float, default=180.0)
    parser.add_argument("--sdbc-pricing-cut-epsilon", type=float, default=100.0)
    parser.add_argument("--sdbc-side-rounds", type=int, default=0)
    parser.add_argument("--sdbc-side-lp-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--sdbc-max-splits", type=int, default=10)
    parser.add_argument("--sdbc-max-cuts", type=int, default=10)
    parser.add_argument("--sdbc-cglp-time-limit-seconds", type=float, default=20.0)
    parser.add_argument("--sdbc-violation-tolerance", type=float, default=1.0e-5)
    parser.add_argument("--sdbc-fractionality-tolerance", type=float, default=1.0e-4)
    parser.add_argument("--fullrow-sdbc-root-closure", action="store_true")
    parser.add_argument("--fullrow-sdbc-lp-time-limit-seconds", type=float, default=180.0)
    parser.add_argument("--fullrow-sdbc-max-rows", type=int, default=1200)
    parser.add_argument("--fullrow-sdbc-tight-tolerance", type=float, default=1.0e-5)
    parser.add_argument("--fullrow-sdbc-max-single-splits", type=int, default=10)
    parser.add_argument("--fullrow-sdbc-composite-splits", action="store_true")
    parser.add_argument(
        "--fullrow-sdbc-split-families",
        default="",
        help=(
            "Optional comma-separated split-family filter for full-row SDBC, "
            "e.g. single_z,station_count. Empty means all generated families."
        ),
    )
    parser.add_argument("--fullrow-sdbc-max-splits", type=int, default=12)
    parser.add_argument("--fullrow-sdbc-max-cuts", type=int, default=12)
    parser.add_argument("--fullrow-sdbc-cglp-time-limit-seconds", type=float, default=60.0)
    parser.add_argument("--fullrow-sdbc-violation-tolerance", type=float, default=1.0e-5)
    parser.add_argument(
        "--fullrow-sdbc-bound-scope",
        choices=("all_selected", "split_only", "none"),
        default="all_selected",
        help=(
            "Variable-bound rows included in full-row SDBC CGLP. "
            "`all_selected` is strongest and slowest; `split_only` is a safe "
            "subset using only split-variable bounds; `none` is diagnostic."
        ),
    )
    parser.add_argument("--value-cut-lb-ascent", action="store_true")
    parser.add_argument("--value-cut-rebuilds", type=int, default=5)
    parser.add_argument("--value-cuts-per-rebuild", type=int, default=1)
    parser.add_argument("--value-cut-max-columns", type=int, default=600)
    parser.add_argument("--value-cut-subset-sizes", default="1,2,4,8,16")
    parser.add_argument("--value-cut-pricing-rounds", type=int, default=0)
    parser.add_argument("--value-cut-pricing-time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--value-cut-time-limit-seconds", type=float, default=600.0)
    parser.add_argument("--value-cut-safe-cutoff", action="store_true", default=True)
    parser.add_argument(
        "--value-cut-recompute-source-duals",
        action="store_true",
        help=(
            "Recompute fixed-outage paper-dual cuts at the current source plan before "
            "building distributional value cuts. This is stronger but more expensive."
        ),
    )
    parser.add_argument(
        "--value-cut-recompute-source-duals-limit",
        type=int,
        default=0,
        help=(
            "Number of candidate columns whose source-plan duals are recomputed. "
            "Use -1 for all selected candidates; 0 disables recomputation."
        ),
    )
    parser.add_argument(
        "--no-value-cut-safe-cutoff",
        dest="value_cut_safe_cutoff",
        action="store_false",
    )
    parser.add_argument("--direct-fixed-outage-rows", action="store_true")
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument("--min-ub-improvement", type=float, default=1.0e-6)
    parser.add_argument("--keep-global-cuts", action="store_true", default=True)
    parser.add_argument("--no-keep-global-cuts", dest="keep_global_cuts", action="store_false")
    parser.add_argument("--log-to-console", action="store_true")
    args = parser.parse_args()
    summary = run_closure(args)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
