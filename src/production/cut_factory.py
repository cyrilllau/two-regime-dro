"""Production cut construction plus one explicit cut-addition step."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping, Sequence

from gurobipy import GRB, quicksum

from src.audit.cut_audit import GeneratedCutAuditRecord, build_cut_audit_record
from src.audit.residual_report import (
    RestrictedMasterProblemResidualReport,
    build_master_problem_residual_report,
)
from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import RuntimeDataValidationError
from src.production.disaster_dual_paper import (
    SamplewisePaperDualDecomposition,
    build_disaster_dual_paper_model,
    extract_disaster_dual_paper_solution,
)
from src.production.master_problem import (
    RestrictedMasterCut,
    RestrictedMasterProblem,
    RestrictedMasterProblemSolution,
    solve_master_problem,
)
from src.production.separation_milp import (
    SeparationMilpModel,
    SeparationMilpSolution,
    solve_separation_milp,
)
from src.reference.disaster_primal_ref import (
    FixedFirstStagePlan,
    FixedOutageVector,
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
)
from src.reference.outage_enumerator import (
    derive_single_line_omega_bounds,
    solve_budget_support_top_k,
)


PAPER_DUAL_SIMPLEX_METHOD = 0
CUT_FROM_SEPARATION_DUAL_METHOD = -1
CUT_SIGNATURE_TOLERANCE = 1e-9
DUAL_OBJECTIVE_TIEBREAK_TOLERANCE = 1e-6


@dataclass(frozen=True)
class GeneratedCutResult:
    """Structured generated cut plus its source diagnostics."""

    cut: RestrictedMasterCut
    audit: GeneratedCutAuditRecord
    scenario_ids: tuple[int, ...]
    simplex_method: int
    support_value_at_source: float | None
    old_master_cut_violation: float | None
    cut_signature_hash: str
    gamma_z_nonzero_count: int
    gamma_n_sl_nonzero_count: int
    gamma_n_fa_nonzero_count: int
    phi_nonzero_count: int


@dataclass(frozen=True)
class SingleIterationCutAdditionResult:
    """One explicit master -> separation -> cut -> master integration step."""

    pre_master: RestrictedMasterProblem
    pre_solution: RestrictedMasterProblemSolution
    pre_residual: RestrictedMasterProblemResidualReport
    separation_model: SeparationMilpModel
    separation_solution: SeparationMilpSolution
    generated_cut_result: GeneratedCutResult | None
    post_master: RestrictedMasterProblem | None
    post_solution: RestrictedMasterProblemSolution | None
    post_residual: RestrictedMasterProblemResidualReport | None


def _resolve_disaster_scenario_ids(
    instance: CanonicalInstance,
    scenario_ids: Sequence[int] | None,
) -> tuple[int, ...]:
    selected = tuple(
        int(scenario_id)
        for scenario_id in (
            scenario_ids
            if scenario_ids is not None
            else instance.sets.loaded_disaster_scenarios
        )
    )
    if not selected:
        raise RuntimeDataValidationError("At least one disaster scenario is required.")
    if len(set(selected)) != len(selected):
        raise RuntimeDataValidationError(f"scenario_ids contains duplicates: {selected}.")
    loaded = set(instance.sets.loaded_disaster_scenarios)
    invalid = tuple(sorted(scenario_id for scenario_id in selected if scenario_id not in loaded))
    if invalid:
        raise RuntimeDataValidationError(
            "scenario_ids contains scenarios outside the loaded canonical selection: "
            f"{invalid}."
        )
    return selected


def _stable_signature_payload(
    cut: RestrictedMasterCut,
    *,
    atol: float = CUT_SIGNATURE_TOLERANCE,
) -> dict[str, object]:
    return {
        "beta": round(float(cut.beta), 6),
        "gamma_z_by_bus": {
            str(bus): round(float(value), 6)
            for bus, value in sorted(cut.gamma_z_by_bus.items())
            if abs(float(value)) > atol
        },
        "gamma_n_sl_by_bus": {
            str(bus): round(float(value), 6)
            for bus, value in sorted(cut.gamma_n_sl_by_bus.items())
            if abs(float(value)) > atol
        },
        "gamma_n_fa_by_bus": {
            str(bus): round(float(value), 6)
            for bus, value in sorted(cut.gamma_n_fa_by_bus.items())
            if abs(float(value)) > atol
        },
        "phi_by_line_id": {
            str(line_id): round(float(value), 6)
            for line_id, value in sorted(cut.phi_by_line_id.items())
            if abs(float(value)) > atol
        },
    }


def compute_cut_signature_hash(
    cut: RestrictedMasterCut,
    *,
    atol: float = CUT_SIGNATURE_TOLERANCE,
) -> str:
    """Return a stable signature hash for one structured cut, ignoring `cut_id`."""

    payload = _stable_signature_payload(cut, atol=atol)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def compute_cut_nonzero_counts(
    cut: RestrictedMasterCut,
    *,
    atol: float = CUT_SIGNATURE_TOLERANCE,
) -> dict[str, int]:
    """Return the nonzero coefficient counts for the structured cut blocks."""

    return {
        "gamma_z_nonzero_count": sum(
            1 for value in cut.gamma_z_by_bus.values() if abs(float(value)) > atol
        ),
        "gamma_n_sl_nonzero_count": sum(
            1 for value in cut.gamma_n_sl_by_bus.values() if abs(float(value)) > atol
        ),
        "gamma_n_fa_nonzero_count": sum(
            1 for value in cut.gamma_n_fa_by_bus.values() if abs(float(value)) > atol
        ),
        "phi_nonzero_count": sum(
            1 for value in cut.phi_by_line_id.values() if abs(float(value)) > atol
        ),
    }


def _normalize_lambda_by_line_id(
    instance: CanonicalInstance,
    lambda_by_line_id: Mapping[str, float] | None,
) -> dict[str, float]:
    normalized = {line_id: 0.0 for line_id in instance.sets.line_ids}
    if lambda_by_line_id is None:
        return normalized
    invalid = sorted(line_id for line_id in lambda_by_line_id if line_id not in normalized)
    if invalid:
        raise RuntimeDataValidationError(
            f"lambda_by_line_id contains invalid line ids: {tuple(invalid)}."
        )
    for line_id, value in lambda_by_line_id.items():
        numeric = float(value)
        if numeric < -1e-12:
            raise RuntimeDataValidationError(
                f"lambda_by_line_id[{line_id!r}] must be nonnegative, got {numeric}."
            )
        normalized[line_id] = max(0.0, numeric)
    return normalized


def _plan_from_first_stage_solution(
    instance: CanonicalInstance,
    solution: RestrictedMasterProblemSolution,
) -> FixedFirstStagePlan:
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus=solution.first_stage_solution.z_by_bus,
        n_sl_by_bus=solution.first_stage_solution.n_sl_by_bus,
        n_fa_by_bus=solution.first_stage_solution.n_fa_by_bus,
    )


def _build_aggregated_cut(
    instance: CanonicalInstance,
    *,
    cut_id: str,
    samplewise_decompositions_by_scenario: Mapping[int, SamplewisePaperDualDecomposition],
) -> RestrictedMasterCut:
    scenario_ids = tuple(sorted(int(scenario_id) for scenario_id in samplewise_decompositions_by_scenario))
    if not scenario_ids:
        raise RuntimeDataValidationError(
            "samplewise_decompositions_by_scenario must contain at least one scenario."
        )
    weight = 1.0 / len(scenario_ids)
    return RestrictedMasterCut(
        cut_id=str(cut_id),
        beta=float(
            sum(
                samplewise_decompositions_by_scenario[scenario_id].beta_b
                for scenario_id in scenario_ids
            )
            * weight
        ),
        gamma_z_by_bus={
            bus: float(
                sum(
                    samplewise_decompositions_by_scenario[scenario_id].gamma_z_by_bus[bus]
                    for scenario_id in scenario_ids
                )
                * weight
            )
            for bus in instance.sets.buses
        },
        gamma_n_sl_by_bus={
            bus: float(
                sum(
                    samplewise_decompositions_by_scenario[scenario_id].gamma_n_sl_by_bus[bus]
                    for scenario_id in scenario_ids
                )
                * weight
            )
            for bus in instance.sets.buses
        },
        gamma_n_fa_by_bus={
            bus: float(
                sum(
                    samplewise_decompositions_by_scenario[scenario_id].gamma_n_fa_by_bus[bus]
                    for scenario_id in scenario_ids
                )
                * weight
            )
            for bus in instance.sets.buses
        },
        phi_by_line_id={
            line_id: float(
                sum(
                    samplewise_decompositions_by_scenario[scenario_id].phi_by_line_id[line_id]
                    for scenario_id in scenario_ids
                )
                * weight
            )
            for line_id in instance.sets.line_ids
        },
    )


def evaluate_generated_cut_violation(
    instance: CanonicalInstance,
    *,
    cut: RestrictedMasterCut,
    plan: FixedFirstStagePlan,
    alpha: float,
    lambda_by_line_id: Mapping[str, float] | None,
) -> tuple[float, float, float]:
    """Evaluate the aggregated cut base term, support term, and violation."""

    normalized_lambda = _normalize_lambda_by_line_id(instance, lambda_by_line_id)
    base_value = float(cut.beta)
    for bus in instance.sets.buses:
        base_value -= float(cut.gamma_z_by_bus[bus]) * float(plan.z_by_bus[bus])
        base_value -= float(cut.gamma_n_sl_by_bus[bus]) * float(plan.n_sl_by_bus[bus])
        base_value -= float(cut.gamma_n_fa_by_bus[bus]) * float(plan.n_fa_by_bus[bus])
    support = solve_budget_support_top_k(
        instance.sets.line_ids,
        budget_k=int(instance.ambiguity.k_max_outages),
        score_by_line_id={
            line_id: float(cut.phi_by_line_id[line_id]) - normalized_lambda[line_id]
            for line_id in instance.sets.line_ids
        },
    )
    lower_bound = float(base_value + support.objective_value)
    return base_value, float(support.objective_value), float(lower_bound - float(alpha))


def _canonicalize_paper_dual_solution(
    paper_dual_model,
    *,
    optimal_objective_value: float,
) -> None:
    """Pick a stable minimum-rho representative among optimal fixed-outage duals."""

    original_objective = paper_dual_model.model.getObjective()
    paper_dual_model.model.addConstr(
        original_objective
        >= float(optimal_objective_value) - DUAL_OBJECTIVE_TIEBREAK_TOLERANCE,
        name="canonical_dual_objective_floor",
    )
    rho_total = quicksum(
        var
        for block in (
            paper_dual_model.eq32_upper_vars,
            paper_dual_model.eq32_lower_vars,
        )
        for var in block.values()
    )
    paper_dual_model.model.setObjective(rho_total, sense=GRB.MINIMIZE)
    paper_dual_model.model.Params.Method = PAPER_DUAL_SIMPLEX_METHOD
    paper_dual_model.model.optimize()
    if paper_dual_model.model.Status != GRB.OPTIMAL:
        raise ValueError(
            "Paper dual canonical tie-break did not reach OPTIMAL status: "
            f"{paper_dual_model.model.Status}."
        )


def generate_structured_cut(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlan,
    outage: FixedOutageVector,
    scenario_ids: Sequence[int] | None = None,
    cut_id: str = "generated_cut",
    provenance: str = "round_08_cut_factory",
    source_alpha: float | None = None,
    source_lambda_by_line_id: Mapping[str, float] | None = None,
    source_violation_value: float | None = None,
    canonicalize_degenerate_dual: bool = False,
    log_to_console: bool = False,
) -> GeneratedCutResult:
    """Generate one structured master cut from simplex-solved paper-dual samples."""

    selected_scenarios = _resolve_disaster_scenario_ids(instance, scenario_ids)
    samplewise_decompositions_by_scenario: dict[int, SamplewisePaperDualDecomposition] = {}
    samplewise_objective_by_scenario: dict[int, float] = {}

    for scenario_id in selected_scenarios:
        paper_dual_model = build_disaster_dual_paper_model(
            instance,
            plan=plan,
            outage=outage,
            scenario_id=scenario_id,
            model_name=f"{cut_id}_paper_dual_b{scenario_id}",
            log_to_console=log_to_console,
        )
        paper_dual_model.model.Params.Method = PAPER_DUAL_SIMPLEX_METHOD
        paper_dual_model.model.optimize()
        if paper_dual_model.model.Status != GRB.OPTIMAL:
            raise ValueError(
                "Paper dual solve did not reach OPTIMAL status during cut generation: "
                f"{paper_dual_model.model.Status}."
            )
        optimal_objective_value = float(paper_dual_model.model.ObjVal)
        if canonicalize_degenerate_dual:
            _canonicalize_paper_dual_solution(
                paper_dual_model,
                optimal_objective_value=optimal_objective_value,
            )
        paper_dual_solution = extract_disaster_dual_paper_solution(paper_dual_model)
        samplewise_decompositions_by_scenario[scenario_id] = (
            paper_dual_solution.samplewise_decomposition
        )
        samplewise_objective_by_scenario[scenario_id] = float(
            paper_dual_solution.samplewise_decomposition.evaluate(
                plan=plan,
                outage=outage,
            )
        )

    cut = _build_aggregated_cut(
        instance,
        cut_id=cut_id,
        samplewise_decompositions_by_scenario=samplewise_decompositions_by_scenario,
    )
    cut_signature_hash = compute_cut_signature_hash(cut)
    nonzero_counts = compute_cut_nonzero_counts(cut)
    support_value_at_source = None
    old_master_cut_violation = None
    if source_alpha is not None:
        _, support_value, violation = evaluate_generated_cut_violation(
            instance,
            cut=cut,
            plan=plan,
            alpha=float(source_alpha),
            lambda_by_line_id=source_lambda_by_line_id,
        )
        support_value_at_source = float(support_value)
        old_master_cut_violation = float(violation)

    audit = build_cut_audit_record(
        cut_id=cut.cut_id,
        provenance=provenance,
        simplex_method=PAPER_DUAL_SIMPLEX_METHOD,
        source_plan=plan,
        source_outage=outage,
        source_alpha=source_alpha,
        source_lambda_by_line_id=source_lambda_by_line_id,
        source_violation_value=(
            source_violation_value
            if source_violation_value is not None
            else old_master_cut_violation
        ),
        cut_signature_hash=cut_signature_hash,
        gamma_z_nonzero_count=nonzero_counts["gamma_z_nonzero_count"],
        gamma_n_sl_nonzero_count=nonzero_counts["gamma_n_sl_nonzero_count"],
        gamma_n_fa_nonzero_count=nonzero_counts["gamma_n_fa_nonzero_count"],
        phi_nonzero_count=nonzero_counts["phi_nonzero_count"],
        samplewise_decompositions_by_scenario=samplewise_decompositions_by_scenario,
        samplewise_objective_by_scenario=samplewise_objective_by_scenario,
        aggregated_cut=cut,
    )
    return GeneratedCutResult(
        cut=cut,
        audit=audit,
        scenario_ids=selected_scenarios,
        simplex_method=PAPER_DUAL_SIMPLEX_METHOD,
        support_value_at_source=support_value_at_source,
        old_master_cut_violation=old_master_cut_violation,
        cut_signature_hash=cut_signature_hash,
        gamma_z_nonzero_count=nonzero_counts["gamma_z_nonzero_count"],
        gamma_n_sl_nonzero_count=nonzero_counts["gamma_n_sl_nonzero_count"],
        gamma_n_fa_nonzero_count=nonzero_counts["gamma_n_fa_nonzero_count"],
        phi_nonzero_count=nonzero_counts["phi_nonzero_count"],
    )


def generate_structured_cut_from_decompositions(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlan,
    outage: FixedOutageVector,
    samplewise_decompositions_by_scenario: Mapping[int, SamplewisePaperDualDecomposition],
    cut_id: str = "generated_cut",
    provenance: str = "round_08_cut_factory",
    source_alpha: float | None = None,
    source_lambda_by_line_id: Mapping[str, float] | None = None,
    source_violation_value: float | None = None,
    simplex_method: int = CUT_FROM_SEPARATION_DUAL_METHOD,
) -> GeneratedCutResult:
    """Build one structured cut from already-solved paper-dual decompositions."""

    selected_scenarios = _resolve_disaster_scenario_ids(
        instance,
        tuple(sorted(int(scenario_id) for scenario_id in samplewise_decompositions_by_scenario)),
    )
    normalized_decompositions = {
        int(scenario_id): samplewise_decompositions_by_scenario[int(scenario_id)]
        for scenario_id in selected_scenarios
    }
    samplewise_objective_by_scenario = {
        scenario_id: float(
            normalized_decompositions[scenario_id].evaluate(
                plan=plan,
                outage=outage,
            )
        )
        for scenario_id in selected_scenarios
    }
    cut = _build_aggregated_cut(
        instance,
        cut_id=cut_id,
        samplewise_decompositions_by_scenario=normalized_decompositions,
    )
    cut_signature_hash = compute_cut_signature_hash(cut)
    nonzero_counts = compute_cut_nonzero_counts(cut)
    support_value_at_source = None
    old_master_cut_violation = None
    if source_alpha is not None:
        _, support_value, violation = evaluate_generated_cut_violation(
            instance,
            cut=cut,
            plan=plan,
            alpha=float(source_alpha),
            lambda_by_line_id=source_lambda_by_line_id,
        )
        support_value_at_source = float(support_value)
        old_master_cut_violation = float(violation)

    audit = build_cut_audit_record(
        cut_id=cut.cut_id,
        provenance=provenance,
        simplex_method=simplex_method,
        source_plan=plan,
        source_outage=outage,
        source_alpha=source_alpha,
        source_lambda_by_line_id=source_lambda_by_line_id,
        source_violation_value=(
            source_violation_value
            if source_violation_value is not None
            else old_master_cut_violation
        ),
        cut_signature_hash=cut_signature_hash,
        gamma_z_nonzero_count=nonzero_counts["gamma_z_nonzero_count"],
        gamma_n_sl_nonzero_count=nonzero_counts["gamma_n_sl_nonzero_count"],
        gamma_n_fa_nonzero_count=nonzero_counts["gamma_n_fa_nonzero_count"],
        phi_nonzero_count=nonzero_counts["phi_nonzero_count"],
        samplewise_decompositions_by_scenario=normalized_decompositions,
        samplewise_objective_by_scenario=samplewise_objective_by_scenario,
        aggregated_cut=cut,
    )
    return GeneratedCutResult(
        cut=cut,
        audit=audit,
        scenario_ids=selected_scenarios,
        simplex_method=simplex_method,
        support_value_at_source=support_value_at_source,
        old_master_cut_violation=old_master_cut_violation,
        cut_signature_hash=cut_signature_hash,
        gamma_z_nonzero_count=nonzero_counts["gamma_z_nonzero_count"],
        gamma_n_sl_nonzero_count=nonzero_counts["gamma_n_sl_nonzero_count"],
        gamma_n_fa_nonzero_count=nonzero_counts["gamma_n_fa_nonzero_count"],
        phi_nonzero_count=nonzero_counts["phi_nonzero_count"],
    )


def generate_cut_from_separation_solution(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlan,
    separation_solution: SeparationMilpSolution,
    scenario_ids: Sequence[int] | None = None,
    cut_id: str = "generated_cut",
    provenance: str = "round_08_single_iteration",
    lambda_by_line_id: Mapping[str, float] | None = None,
    log_to_console: bool = False,
) -> GeneratedCutResult:
    """Generate a stable cut for the separation-selected outage pattern."""

    outage = build_fixed_outage_vector(
        instance,
        by_line_id=separation_solution.delta_by_line_id,
    )
    return generate_structured_cut(
        instance,
        plan=plan,
        outage=outage,
        scenario_ids=scenario_ids,
        cut_id=cut_id,
        provenance=provenance,
        source_alpha=separation_solution.alpha_value,
        source_lambda_by_line_id=lambda_by_line_id,
        source_violation_value=separation_solution.objective_value,
        canonicalize_degenerate_dual=True,
        log_to_console=log_to_console,
    )


def run_single_iteration_cut_addition(
    instance: CanonicalInstance,
    *,
    cuts: Sequence[RestrictedMasterCut] | None = None,
    normal_scenario_ids: Sequence[int] | None = None,
    disaster_scenario_ids: Sequence[int] | None = None,
    omega_bounds_by_line_id: Mapping[str, tuple[float, float]] | None = None,
    omega_bound_safety_factor: float = 2.0,
    cut_id: str = "generated_cut_001",
    provenance: str = "round_08_single_iteration",
    violation_tolerance: float = 1e-6,
    model_name_prefix: str = "round_08_single_iteration",
    log_to_console: bool = False,
) -> SingleIterationCutAdditionResult:
    """Run exactly one master -> separation -> cut -> master step."""

    pre_master, pre_solution = solve_master_problem(
        instance,
        cuts=cuts,
        normal_scenario_ids=normal_scenario_ids,
        model_name=f"{model_name_prefix}_master_pre",
        log_to_console=log_to_console,
    )
    pre_residual = build_master_problem_residual_report(pre_master, pre_solution)
    plan = _plan_from_first_stage_solution(instance, pre_solution)
    lambda_by_line_id = pre_solution.lambda_by_line_id
    resolved_omega_bounds = (
        {
            str(line_id): (float(bounds[0]), float(bounds[1]))
            for line_id, bounds in omega_bounds_by_line_id.items()
        }
        if omega_bounds_by_line_id is not None
        else derive_single_line_omega_bounds(
            instance,
            plan=plan,
            budget_k=int(instance.ambiguity.k_max_outages),
            scenario_ids=disaster_scenario_ids,
            safety_factor=float(omega_bound_safety_factor),
        )
    )
    separation_model, separation_solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=pre_solution.alpha_value,
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=resolved_omega_bounds,
        budget_k=int(instance.ambiguity.k_max_outages),
        scenario_ids=disaster_scenario_ids,
        model_name=f"{model_name_prefix}_separation",
        log_to_console=log_to_console,
    )

    if float(separation_solution.objective_value or 0.0) <= float(violation_tolerance):
        return SingleIterationCutAdditionResult(
            pre_master=pre_master,
            pre_solution=pre_solution,
            pre_residual=pre_residual,
            separation_model=separation_model,
            separation_solution=separation_solution,
            generated_cut_result=None,
            post_master=None,
            post_solution=None,
            post_residual=None,
        )

    generated_cut_result = generate_cut_from_separation_solution(
        instance,
        plan=plan,
        separation_solution=separation_solution,
        scenario_ids=disaster_scenario_ids,
        cut_id=cut_id,
        provenance=provenance,
        lambda_by_line_id=lambda_by_line_id,
        log_to_console=log_to_console,
    )
    post_cuts = tuple(pre_master.cuts) + (generated_cut_result.cut,)
    post_master, post_solution = solve_master_problem(
        instance,
        cuts=post_cuts,
        normal_scenario_ids=normal_scenario_ids,
        model_name=f"{model_name_prefix}_master_post",
        log_to_console=log_to_console,
    )
    post_residual = build_master_problem_residual_report(post_master, post_solution)
    return SingleIterationCutAdditionResult(
        pre_master=pre_master,
        pre_solution=pre_solution,
        pre_residual=pre_residual,
        separation_model=separation_model,
        separation_solution=separation_solution,
        generated_cut_result=generated_cut_result,
        post_master=post_master,
        post_solution=post_solution,
        post_residual=post_residual,
    )
