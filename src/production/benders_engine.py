"""Full iterative production Benders engine for the sampled mainline."""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

from gurobipy import GRB, Model, quicksum

from src.audit.iteration_log import (
    BendersCertificateSummary,
    BendersIterationLogArtifact,
    BendersIterationRecord,
    build_iteration_log_artifact,
    write_iteration_log_artifact,
)
from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import (
    RestrictedMasterProblemResidualReport,
    build_master_problem_residual_report,
)
from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import RuntimeDataValidationError
from src.production.cut_factory import (
    GeneratedCutResult,
    build_default_pareto_core_point,
    compute_cut_signature_hash,
    generate_cluster_face_bundle_cuts,
    generate_cut_from_separation_solution,
    generate_structured_cut,
    generate_target_face_bundle_cuts,
)
from src.production.master_problem import (
    RestrictedMasterCut,
    RestrictedMasterOutageColumnCut,
    RestrictedMasterProblem,
    RestrictedMasterProblemSolution,
    solve_master_problem,
)
from src.production.separation_milp import (
    SeparationMilpModel,
    SeparationMilpSolution,
    extract_separation_milp_solution_pool,
    solve_separation_milp,
)
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan
from src.reference.disaster_primal_ref import build_fixed_outage_vector
from src.reference.disaster_primal_ref import FixedFirstStagePlan
from src.reference.outage_enumerator import derive_single_line_omega_bounds


CERTIFICATION_TOLERANCE = 1e-8


@dataclass(frozen=True)
class BendersTrialCertificate:
    """Diagnostic certificate for an auxiliary trial point.

    The trial point can have full-support pricing violation below epsilon while
    the canonical restricted-master optimizer has not closed yet. This artifact
    deliberately separates the auxiliary trial objective from the canonical
    lower bound so downstream code cannot mislabel a trial-feasible point as a
    canonical Benders certificate.
    """

    iteration_id: int
    stop_reason: str
    candidate_source: str
    epsilon_cert: float
    canonical_lower_bound: float
    canonical_master_objective: float | None
    canonical_model_status: str
    canonical_rmp_objval: float | None
    canonical_rmp_objbound: float | None
    canonical_rmp_mipgap: float | None
    canonical_lower_bound_source: str
    auxiliary_master_objective: float | None
    auxiliary_used_for_lower_bound: bool
    A_total: int
    B_total: int
    K: int
    m_cons: float
    m_normal: float
    m_dis: float
    unpenalized_candidate_objective: float
    pricing_violation_bound: float
    pricing_violation_value: float
    pricing_support: str
    pricing_bound_is_valid_upper_bound: bool
    separation_objval: float | None
    pricing_derived_upper_bound: float
    pricing_ub_addition: float
    pricing_ub_formula: str
    best_pricing_derived_upper_bound: float | None
    pricing_gap_bound: float
    best_pricing_gap_bound: float | None
    certificate_type: str
    paper_facing_eligible: bool
    validation_level: str
    normal_recourse_replayed: bool
    plan_hash: str
    alpha_lambda_hash: str
    support_hash: str
    alpha: float
    lambda_by_line_id: dict[str, float]
    first_stage_plan: dict[str, dict[str, int]]
    selected_outage_active_lines: tuple[str, ...]
    selected_outage_by_line_id: dict[str, int]
    separation_model_status: str
    separation_mip_gap: float | None
    separation_obj_bound: float | None
    separation_reconstruction_gap: float
    separation_node_count: int | None
    level_bundle_objective_upper_bound: float | None
    trust_region_z_distance: int | None


@dataclass(frozen=True)
class BendersEngineResult:
    """Structured result of one full iterative Benders run."""

    stop_reason: str
    epsilon_cert: float
    iterations: tuple[BendersIterationRecord, ...]
    lower_bound_sequence: tuple[float, ...]
    cut_count_sequence: tuple[int, ...]
    generated_cut_results: tuple[GeneratedCutResult, ...]
    final_master: RestrictedMasterProblem
    final_solution: RestrictedMasterProblemSolution
    final_residual: RestrictedMasterProblemResidualReport
    final_separation_model: SeparationMilpModel
    final_separation_solution: SeparationMilpSolution
    certificate: BendersCertificateSummary
    iteration_log_artifact: BendersIterationLogArtifact
    master_before_cut_lp_path: Path | None = None
    master_after_cut_lp_path: Path | None = None
    iteration_log_path: Path | None = None
    trial_certificate: BendersTrialCertificate | None = None


def _resolve_positive_int(name: str, value: int) -> int:
    resolved = int(value)
    if resolved <= 0:
        raise RuntimeDataValidationError(f"{name} must be positive, got {value!r}.")
    return resolved


def _resolve_nonnegative_float(name: str, value: float) -> float:
    resolved = float(value)
    if resolved < 0.0:
        raise RuntimeDataValidationError(f"{name} must be nonnegative, got {value!r}.")
    return resolved


def _plan_from_solution(
    instance: CanonicalInstance,
    solution: RestrictedMasterProblemSolution,
):
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus=solution.first_stage_solution.z_by_bus,
        n_sl_by_bus=solution.first_stage_solution.n_sl_by_bus,
        n_fa_by_bus=solution.first_stage_solution.n_fa_by_bus,
    )


def _first_stage_plan_payload(plan: FixedFirstStagePlan) -> dict[str, dict[str, int]]:
    """Return a stable JSON payload for a fixed first-stage plan."""

    return {
        "z_by_bus": {str(bus): int(value) for bus, value in sorted(plan.z_by_bus.items())},
        "n_sl_by_bus": {
            str(bus): int(value) for bus, value in sorted(plan.n_sl_by_bus.items())
        },
        "n_fa_by_bus": {
            str(bus): int(value) for bus, value in sorted(plan.n_fa_by_bus.items())
        },
    }


def _stable_json_hash(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    """Return a stable short hash for certificate identity checks."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _build_trial_certificate(
    *,
    instance: CanonicalInstance,
    iteration_id: int,
    stop_reason: str,
    candidate_source: str,
    canonical_master_problem: RestrictedMasterProblem,
    canonical_solution: RestrictedMasterProblemSolution,
    plan: FixedFirstStagePlan,
    separation_alpha_value: float,
    separation_lambda_by_line_id: Mapping[str, float],
    separation_solution: SeparationMilpSolution,
    auxiliary_objective: float | None,
    candidate_unpenalized_objective: float | None,
    pricing_violation_upper_bound: float,
    pricing_upper_bound: float,
    best_pricing_derived_upper_bound: float | None,
    level_bundle_bound_used: float | None,
    trust_region_z_distance: int | None,
    epsilon_cert: float,
) -> BendersTrialCertificate:
    """Build the explicit auxiliary-trial diagnostic certificate."""

    canonical_lower_bound = _valid_restricted_master_lower_bound(
        canonical_master_problem,
        canonical_solution,
    )
    canonical_obj_bound_raw = getattr(canonical_master_problem.model, "ObjBound", None)
    canonical_mip_gap_raw = getattr(canonical_master_problem.model, "MIPGap", None)
    canonical_lower_bound_source = (
        "ObjVal" if str(canonical_solution.model_status) == "OPTIMAL" else "ObjBound"
    )
    plan_payload = _first_stage_plan_payload(plan)
    alpha_lambda_payload = {
        "alpha": float(separation_alpha_value),
        "lambda_by_line_id": {
            str(line_id): float(value)
            for line_id, value in sorted(separation_lambda_by_line_id.items())
        },
    }
    support_payload = {
        "normal_scenarios": [int(value) for value in instance.sets.loaded_normal_scenarios],
        "disaster_scenarios": [
            int(value) for value in instance.sets.loaded_disaster_scenarios
        ],
        "K": int(instance.ambiguity.k_max_outages),
        "line_ids": [str(value) for value in instance.sets.line_ids],
        "buses": [int(value) for value in instance.sets.buses],
    }
    pricing_ub_addition = float(
        instance.economics.objective_multipliers.disaster
    ) * float(instance.economics.pi_f) * max(0.0, float(pricing_violation_upper_bound))
    current_gap_bound = max(
        0.0,
        float(pricing_upper_bound) - float(canonical_lower_bound),
    )
    pricing_bound_is_valid_upper_bound = (
        separation_solution.model_status == "OPTIMAL"
        or separation_solution.obj_bound is not None
    )
    if (
        pricing_bound_is_valid_upper_bound
        and max(0.0, float(pricing_violation_upper_bound))
        <= float(epsilon_cert) + CERTIFICATION_TOLERANCE
        and current_gap_bound <= float(epsilon_cert) + CERTIFICATION_TOLERANCE
    ):
        certificate_type = "pricing_ub_gap_certified"
        validation_level = "pricing_ub_gap_certified"
        paper_facing_eligible = True
    elif (
        pricing_bound_is_valid_upper_bound
        and max(0.0, float(pricing_violation_upper_bound))
        <= float(epsilon_cert) + CERTIFICATION_TOLERANCE
    ):
        certificate_type = "trial_full_support_feasible_gap_open"
        validation_level = "trial_full_support_feasible_gap_open"
        paper_facing_eligible = False
    else:
        certificate_type = "diagnostic_only"
        validation_level = "smoke_only"
        paper_facing_eligible = False
    effective_best_upper_bound = (
        float(pricing_upper_bound)
        if best_pricing_derived_upper_bound is None
        else min(float(best_pricing_derived_upper_bound), float(pricing_upper_bound))
    )
    return BendersTrialCertificate(
        iteration_id=int(iteration_id),
        stop_reason=str(stop_reason),
        candidate_source=str(candidate_source),
        epsilon_cert=float(epsilon_cert),
        canonical_lower_bound=float(canonical_lower_bound),
        canonical_master_objective=(
            None
            if canonical_solution.objective_value is None
            else float(canonical_solution.objective_value)
        ),
        canonical_model_status=str(canonical_solution.model_status),
        canonical_rmp_objval=(
            None
            if canonical_solution.objective_value is None
            else float(canonical_solution.objective_value)
        ),
        canonical_rmp_objbound=(
            None if canonical_obj_bound_raw is None else float(canonical_obj_bound_raw)
        ),
        canonical_rmp_mipgap=(
            None if canonical_mip_gap_raw is None else float(canonical_mip_gap_raw)
        ),
        canonical_lower_bound_source=canonical_lower_bound_source,
        auxiliary_master_objective=(
            None if auxiliary_objective is None else float(auxiliary_objective)
        ),
        auxiliary_used_for_lower_bound=False,
        A_total=len(instance.sets.loaded_normal_scenarios),
        B_total=len(instance.sets.loaded_disaster_scenarios),
        K=int(instance.ambiguity.k_max_outages),
        m_cons=float(instance.economics.objective_multipliers.cons),
        m_normal=float(instance.economics.objective_multipliers.normal),
        m_dis=float(instance.economics.objective_multipliers.disaster),
        unpenalized_candidate_objective=float(candidate_unpenalized_objective or 0.0),
        pricing_violation_bound=float(pricing_violation_upper_bound),
        pricing_violation_value=max(0.0, float(separation_solution.objective_value or 0.0)),
        pricing_support="full_B_full_Omega",
        pricing_bound_is_valid_upper_bound=pricing_bound_is_valid_upper_bound,
        separation_objval=(
            None
            if separation_solution.objective_value is None
            else float(separation_solution.objective_value)
        ),
        pricing_derived_upper_bound=float(pricing_upper_bound),
        pricing_ub_addition=pricing_ub_addition,
        pricing_ub_formula=(
            "unpenalized_candidate_objective + "
            "m_dis*pi_f*max(0, pricing_violation_bound)"
        ),
        best_pricing_derived_upper_bound=(
            None
            if best_pricing_derived_upper_bound is None
            else float(best_pricing_derived_upper_bound)
        ),
        pricing_gap_bound=current_gap_bound,
        best_pricing_gap_bound=max(
            0.0,
            float(effective_best_upper_bound) - float(canonical_lower_bound),
        ),
        certificate_type=certificate_type,
        paper_facing_eligible=paper_facing_eligible,
        validation_level=validation_level,
        normal_recourse_replayed=False,
        plan_hash=_stable_json_hash(plan_payload),
        alpha_lambda_hash=_stable_json_hash(alpha_lambda_payload),
        support_hash=_stable_json_hash(support_payload),
        alpha=float(separation_alpha_value),
        lambda_by_line_id={
            str(line_id): float(value)
            for line_id, value in sorted(separation_lambda_by_line_id.items())
        },
        first_stage_plan=plan_payload,
        selected_outage_active_lines=_active_outage_lines(separation_solution.delta_by_line_id),
        selected_outage_by_line_id={
            str(line_id): int(value)
            for line_id, value in sorted(separation_solution.delta_by_line_id.items())
        },
        separation_model_status=str(separation_solution.model_status),
        separation_mip_gap=(
            None if separation_solution.mip_gap is None else float(separation_solution.mip_gap)
        ),
        separation_obj_bound=(
            None
            if separation_solution.obj_bound is None
            else float(separation_solution.obj_bound)
        ),
        separation_reconstruction_gap=float(separation_solution.reconstruction_gap),
        separation_node_count=separation_solution.node_count,
        level_bundle_objective_upper_bound=(
            None if level_bundle_bound_used is None else float(level_bundle_bound_used)
        ),
        trust_region_z_distance=trust_region_z_distance,
    )


def _make_generated_cut_id(prefix: str, index: int) -> str:
    return f"{prefix}_{index:03d}"


def _active_outage_lines(delta_by_line_id: dict[str, int]) -> tuple[str, ...]:
    return tuple(sorted(line_id for line_id, value in delta_by_line_id.items() if int(value) == 1))


def _delta_by_line_id_from_active_lines(
    line_ids: Sequence[str],
    active_lines: Sequence[str],
) -> dict[str, int]:
    active = {str(line_id) for line_id in active_lines}
    invalid = sorted(line_id for line_id in active if line_id not in set(line_ids))
    if invalid:
        raise RuntimeDataValidationError(
            f"active outage pattern contains invalid line ids: {tuple(invalid)}."
        )
    return {str(line_id): int(str(line_id) in active) for line_id in line_ids}


def _normalize_active_outage_pattern(
    line_ids: Sequence[str],
    active_lines: Sequence[str],
    *,
    budget_k: int,
) -> tuple[str, ...]:
    delta = _delta_by_line_id_from_active_lines(line_ids, active_lines)
    pattern = _active_outage_lines(delta)
    if len(pattern) > int(budget_k):
        raise RuntimeDataValidationError(
            f"active outage pattern has {len(pattern)} lines but K={budget_k}."
        )
    return pattern


def _resolve_fp_by_line_id(instance: CanonicalInstance) -> dict[str, float]:
    line_ids = tuple(str(line_id) for line_id in instance.sets.line_ids)
    p_bar = tuple(float(value) for value in instance.ambiguity.p_bar)
    if len(p_bar) != len(line_ids):
        raise RuntimeDataValidationError(
            f"ambig.p_bar has length {len(p_bar)}, expected {len(line_ids)}."
        )
    return {line_id: p_bar[index] for index, line_id in enumerate(line_ids)}


def _rank_outage_patterns(
    patterns: Sequence[Sequence[str]],
    *,
    fp_by_line_id: Mapping[str, float],
) -> list[tuple[str, ...]]:
    normalized: set[tuple[str, ...]] = {
        tuple(sorted(str(line_id) for line_id in pattern)) for pattern in patterns
    }
    return sorted(
        normalized,
        key=lambda pattern: (
            -sum(float(fp_by_line_id.get(line_id, 0.0)) for line_id in pattern),
            len(pattern),
            pattern,
        ),
    )


def _initial_active_outage_pool(
    instance: CanonicalInstance,
    *,
    max_size: int,
) -> list[tuple[str, ...]]:
    line_ids = tuple(str(line_id) for line_id in instance.sets.line_ids)
    fp_by_line_id = _resolve_fp_by_line_id(instance)
    singletons = [(line_id,) for line_id in line_ids]
    ranked_singletons = _rank_outage_patterns(singletons, fp_by_line_id=fp_by_line_id)
    patterns = [tuple()] + ranked_singletons
    return patterns[: max(0, int(max_size))]


def _neighbor_outage_patterns(
    active_lines: Sequence[str],
    *,
    line_ids: Sequence[str],
    budget_k: int,
    radius: int,
) -> list[tuple[str, ...]]:
    """Return deterministic one-neighborhood patterns around one outage set."""

    base = set(str(line_id) for line_id in active_lines)
    all_lines = tuple(str(line_id) for line_id in line_ids)
    if len(base) > int(budget_k):
        raise RuntimeDataValidationError(
            f"active outage pattern has {len(base)} lines but K={budget_k}."
        )
    patterns: set[tuple[str, ...]] = {tuple(sorted(base))}
    if int(radius) <= 0:
        return sorted(patterns)

    inactive = [line_id for line_id in all_lines if line_id not in base]
    for remove_line in tuple(base):
        reduced = set(base)
        reduced.remove(remove_line)
        patterns.add(tuple(sorted(reduced)))
    if len(base) < int(budget_k):
        for add_line in inactive:
            expanded = set(base)
            expanded.add(add_line)
            patterns.add(tuple(sorted(expanded)))
    for remove_line in tuple(base):
        for add_line in inactive:
            swapped = set(base)
            swapped.remove(remove_line)
            swapped.add(add_line)
            if len(swapped) <= int(budget_k):
                patterns.add(tuple(sorted(swapped)))
    return sorted(patterns)


def _merge_active_outage_pool(
    existing: Sequence[Sequence[str]],
    additions: Sequence[Sequence[str]],
    *,
    max_size: int,
    fp_by_line_id: Mapping[str, float],
) -> list[tuple[str, ...]]:
    """Merge new patterns first, then preserve useful old patterns under a cap."""

    unique: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for pattern in list(additions) + list(existing):
        normalized = tuple(sorted(str(line_id) for line_id in pattern))
        if normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    # Keep recent additions first, but rank overflow candidates by line probability.
    if len(unique) <= int(max_size):
        return unique
    head = unique[: min(len(additions), int(max_size))]
    tail = _rank_outage_patterns(
        [pattern for pattern in unique if pattern not in set(head)],
        fp_by_line_id=fp_by_line_id,
    )
    return (head + tail)[: int(max_size)]


def _append_exact_outage_patterns(
    existing: Sequence[Sequence[str]],
    additions: Sequence[Sequence[str]],
    *,
    max_size: int,
    per_iteration: int,
) -> list[tuple[str, ...]]:
    """Append canonical fixed-outage rows for the next master solve."""

    resolved_max = max(0, int(max_size))
    resolved_per_iteration = max(0, int(per_iteration))
    unique: list[tuple[str, ...]] = [
        tuple(sorted(str(line_id) for line_id in pattern))
        for pattern in existing
    ]
    seen = set(unique)
    if len(unique) >= resolved_max or resolved_per_iteration == 0:
        return unique[:resolved_max]
    added = 0
    for pattern in additions:
        normalized = tuple(sorted(str(line_id) for line_id in pattern))
        if not normalized or normalized in seen:
            continue
        unique.append(normalized)
        seen.add(normalized)
        added += 1
        if len(unique) >= resolved_max or added >= resolved_per_iteration:
            break
    return unique


def _outage_column_id(active_line_ids: Sequence[str]) -> str:
    """Return a stable compact id for an NCCG active outage column."""

    normalized = tuple(str(line_id) for line_id in active_line_ids)
    if not normalized:
        return "delta_none"
    digest = hashlib.sha1("|".join(normalized).encode("utf-8")).hexdigest()[:12]
    return f"delta_{len(normalized)}_{digest}"


def _rowwise_cut_value_at_pattern(
    cut: RestrictedMasterCut,
    *,
    plan: FixedFirstStagePlan,
    active_line_ids: Sequence[str],
) -> float:
    """Evaluate beta - gamma*x + phi*delta for one row at one outage column."""

    value = float(cut.beta)
    for bus in plan.z_by_bus:
        value -= float(cut.gamma_z_by_bus.get(bus, 0.0)) * float(plan.z_by_bus[bus])
        value -= float(cut.gamma_n_sl_by_bus.get(bus, 0.0)) * float(plan.n_sl_by_bus[bus])
        value -= float(cut.gamma_n_fa_by_bus.get(bus, 0.0)) * float(plan.n_fa_by_bus[bus])
    for line_id in active_line_ids:
        value += float(cut.phi_by_line_id.get(str(line_id), 0.0))
    return float(value)


def _plan_signature(
    solution: RestrictedMasterProblemSolution,
) -> tuple[tuple[int, int, int, int], ...]:
    first_stage = solution.first_stage_solution
    return tuple(
        (
            int(bus),
            int(first_stage.z_by_bus[bus]),
            int(first_stage.n_sl_by_bus[bus]),
            int(first_stage.n_fa_by_bus[bus]),
        )
        for bus in sorted(first_stage.z_by_bus)
    )


def _alpha_lambda_signature(
    solution: RestrictedMasterProblemSolution,
) -> tuple[float, tuple[tuple[str, float], ...]]:
    return (
        round(float(solution.alpha_value), 8),
        tuple(
            (str(line_id), round(float(value), 8))
            for line_id, value in sorted(solution.lambda_by_line_id.items())
            if abs(float(value)) > 1e-9
        ),
    )


def _copy_iteration_record(
    record: BendersIterationRecord,
    *,
    post_cut_master_objective: float | None,
    first_stage_plan_changed: bool | None,
    alpha_lambda_only_change: bool | None,
) -> BendersIterationRecord:
    return BendersIterationRecord(
        iteration_id=record.iteration_id,
        pre_cut_master_objective=record.pre_cut_master_objective,
        post_cut_master_objective=post_cut_master_objective,
        separation_violation_value=record.separation_violation_value,
        candidate_source=record.candidate_source,
        canonical_master_objective=record.canonical_master_objective,
        auxiliary_master_objective=record.auxiliary_master_objective,
        unpenalized_candidate_objective=record.unpenalized_candidate_objective,
        valid_lb_used=record.valid_lb_used,
        auxiliary_used_for_lb=record.auxiliary_used_for_lb,
        level_bundle_objective_upper_bound=record.level_bundle_objective_upper_bound,
        level_bundle_center_policy=record.level_bundle_center_policy,
        trust_region_z_radius=record.trust_region_z_radius,
        trust_region_z_distance=record.trust_region_z_distance,
        active_delta_pool_size=record.active_delta_pool_size,
        active_candidate_count=record.active_candidate_count,
        active_validated_cut_count=record.active_validated_cut_count,
        active_best_validated_violation=record.active_best_validated_violation,
        active_set_generation_seconds=record.active_set_generation_seconds,
        full_support_separation_called=record.full_support_separation_called,
        pricing_capture_count=record.pricing_capture_count,
        pricing_capture_best_violation=record.pricing_capture_best_violation,
        pricing_capture_seconds=record.pricing_capture_seconds,
        persistent_pricing_pool_size=record.persistent_pricing_pool_size,
        broadcast_candidate_count=record.broadcast_candidate_count,
        broadcast_added_count=record.broadcast_added_count,
        pricing_violation_bound=record.pricing_violation_bound,
        pricing_derived_upper_bound=record.pricing_derived_upper_bound,
        best_pricing_derived_upper_bound=record.best_pricing_derived_upper_bound,
        certified_serious_step_type=record.certified_serious_step_type,
        certified_serious_null_count=record.certified_serious_null_count,
        valid_gap_bound=record.valid_gap_bound,
        selected_outage_by_line_id=dict(record.selected_outage_by_line_id),
        selected_outage_active_lines=tuple(record.selected_outage_active_lines),
        repeated_outage_flag=bool(record.repeated_outage_flag),
        generated_cut_id=record.generated_cut_id,
        generated_cut_signature_hash=record.generated_cut_signature_hash,
        repeated_cut_signature_flag=bool(record.repeated_cut_signature_flag),
        active_cut_ids_before=tuple(record.active_cut_ids_before),
        active_cut_ids_after=tuple(record.active_cut_ids_after),
        total_cut_count_before=record.total_cut_count_before,
        total_cut_count_after=record.total_cut_count_after,
        generated_cut_old_master_violation=record.generated_cut_old_master_violation,
        post_cut_master_objective_change=(
            None
            if post_cut_master_objective is None
            else float(post_cut_master_objective - record.pre_cut_master_objective)
        ),
        first_stage_plan_changed=first_stage_plan_changed,
        alpha_lambda_only_change=alpha_lambda_only_change,
        cut_added=bool(record.cut_added),
        cut_addition_status=record.cut_addition_status,
        gamma_z_nonzero_count=record.gamma_z_nonzero_count,
        gamma_n_sl_nonzero_count=record.gamma_n_sl_nonzero_count,
        gamma_n_fa_nonzero_count=record.gamma_n_fa_nonzero_count,
        phi_nonzero_count=record.phi_nonzero_count,
        construction_cost_value=record.construction_cost_value,
        first_stage_attached_objective_value=record.first_stage_attached_objective_value,
        first_stage_objective_is_pure_construction=record.first_stage_objective_is_pure_construction,
        master_solve_seconds=record.master_solve_seconds,
        separation_solve_seconds=record.separation_solve_seconds,
        separation_model_status=record.separation_model_status,
        separation_mip_gap=record.separation_mip_gap,
        separation_obj_bound=record.separation_obj_bound,
        separation_node_count=record.separation_node_count,
        separation_max_omega_bound_violation=record.separation_max_omega_bound_violation,
        separation_min_omega_upper_slack=record.separation_min_omega_upper_slack,
        separation_min_active_omega_upper_slack=(
            record.separation_min_active_omega_upper_slack
        ),
        separation_reconstruction_gap=record.separation_reconstruction_gap,
        cut_generation_seconds=record.cut_generation_seconds,
        stop_reason=record.stop_reason,
    )


def _min_omega_upper_slack(solution: SeparationMilpSolution) -> float | None:
    if not solution.omega_upper_slack_by_line_id:
        return None
    return float(min(solution.omega_upper_slack_by_line_id.values()))


def _min_active_omega_upper_slack(solution: SeparationMilpSolution) -> float | None:
    active_slacks = [
        float(solution.omega_upper_slack_by_line_id[line_id])
        for line_id, active in solution.delta_by_line_id.items()
        if int(active) == 1 and line_id in solution.omega_upper_slack_by_line_id
    ]
    return float(min(active_slacks)) if active_slacks else None


def _max_omega_bound_violation(
    solutions: Sequence[SeparationMilpSolution],
) -> float | None:
    if not solutions:
        return None
    return float(max(solution.max_omega_bound_violation for solution in solutions))


def _min_batch_omega_upper_slack(
    solutions: Sequence[SeparationMilpSolution],
) -> float | None:
    slacks: list[float] = []
    for solution in solutions:
        slack = _min_omega_upper_slack(solution)
        if slack is not None:
            slacks.append(float(slack))
    return float(min(slacks)) if slacks else None


def _min_batch_active_omega_upper_slack(
    solutions: Sequence[SeparationMilpSolution],
) -> float | None:
    slacks: list[float] = []
    for solution in solutions:
        slack = _min_active_omega_upper_slack(solution)
        if slack is not None:
            slacks.append(float(slack))
    return float(min(slacks)) if slacks else None


def _max_reconstruction_gap(
    solutions: Sequence[SeparationMilpSolution],
) -> float | None:
    if not solutions:
        return None
    return float(max(solution.reconstruction_gap for solution in solutions))


LIVE_ITERATION_FIELDS = (
    "iteration_id",
    "pre_cut_master_objective",
    "post_cut_master_objective",
    "separation_violation_value",
    "candidate_source",
    "canonical_master_objective",
    "auxiliary_master_objective",
    "unpenalized_candidate_objective",
    "valid_lb_used",
    "auxiliary_used_for_lb",
    "level_bundle_objective_upper_bound",
    "level_bundle_center_policy",
    "trust_region_z_radius",
    "trust_region_z_distance",
    "active_delta_pool_size",
    "active_candidate_count",
    "active_validated_cut_count",
    "active_best_validated_violation",
    "active_set_generation_seconds",
    "full_support_separation_called",
    "pricing_capture_count",
    "pricing_capture_best_violation",
    "pricing_capture_seconds",
    "persistent_pricing_pool_size",
    "broadcast_candidate_count",
    "broadcast_added_count",
    "pricing_violation_bound",
    "pricing_derived_upper_bound",
    "best_pricing_derived_upper_bound",
    "certified_serious_step_type",
    "certified_serious_null_count",
    "valid_gap_bound",
    "selected_outage_active_lines",
    "repeated_outage_flag",
    "generated_cut_id",
    "generated_cut_signature_hash",
    "repeated_cut_signature_flag",
    "total_cut_count_before",
    "total_cut_count_after",
    "generated_cut_old_master_violation",
    "first_stage_plan_changed",
    "alpha_lambda_only_change",
    "cut_added",
    "cut_addition_status",
    "master_solve_seconds",
    "separation_solve_seconds",
    "cut_generation_seconds",
    "separation_model_status",
    "separation_mip_gap",
    "separation_obj_bound",
    "separation_node_count",
    "stop_reason",
)


def _live_iteration_row(record: BendersIterationRecord) -> dict[str, Any]:
    return {
        "iteration_id": record.iteration_id,
        "pre_cut_master_objective": record.pre_cut_master_objective,
        "post_cut_master_objective": record.post_cut_master_objective,
        "separation_violation_value": record.separation_violation_value,
        "candidate_source": record.candidate_source,
        "canonical_master_objective": record.canonical_master_objective,
        "auxiliary_master_objective": record.auxiliary_master_objective,
        "unpenalized_candidate_objective": record.unpenalized_candidate_objective,
        "valid_lb_used": record.valid_lb_used,
        "auxiliary_used_for_lb": record.auxiliary_used_for_lb,
        "level_bundle_objective_upper_bound": record.level_bundle_objective_upper_bound,
        "level_bundle_center_policy": record.level_bundle_center_policy,
        "trust_region_z_radius": record.trust_region_z_radius,
        "trust_region_z_distance": record.trust_region_z_distance,
        "active_delta_pool_size": record.active_delta_pool_size,
        "active_candidate_count": record.active_candidate_count,
        "active_validated_cut_count": record.active_validated_cut_count,
        "active_best_validated_violation": record.active_best_validated_violation,
        "active_set_generation_seconds": record.active_set_generation_seconds,
        "full_support_separation_called": record.full_support_separation_called,
        "pricing_capture_count": record.pricing_capture_count,
        "pricing_capture_best_violation": record.pricing_capture_best_violation,
        "pricing_capture_seconds": record.pricing_capture_seconds,
        "persistent_pricing_pool_size": record.persistent_pricing_pool_size,
        "broadcast_candidate_count": record.broadcast_candidate_count,
        "broadcast_added_count": record.broadcast_added_count,
        "pricing_violation_bound": record.pricing_violation_bound,
        "pricing_derived_upper_bound": record.pricing_derived_upper_bound,
        "best_pricing_derived_upper_bound": record.best_pricing_derived_upper_bound,
        "certified_serious_step_type": record.certified_serious_step_type,
        "certified_serious_null_count": record.certified_serious_null_count,
        "valid_gap_bound": record.valid_gap_bound,
        "selected_outage_active_lines": ";".join(record.selected_outage_active_lines),
        "repeated_outage_flag": record.repeated_outage_flag,
        "generated_cut_id": record.generated_cut_id,
        "generated_cut_signature_hash": record.generated_cut_signature_hash,
        "repeated_cut_signature_flag": record.repeated_cut_signature_flag,
        "total_cut_count_before": record.total_cut_count_before,
        "total_cut_count_after": record.total_cut_count_after,
        "generated_cut_old_master_violation": record.generated_cut_old_master_violation,
        "first_stage_plan_changed": record.first_stage_plan_changed,
        "alpha_lambda_only_change": record.alpha_lambda_only_change,
        "cut_added": record.cut_added,
        "cut_addition_status": record.cut_addition_status,
        "master_solve_seconds": record.master_solve_seconds,
        "separation_solve_seconds": record.separation_solve_seconds,
        "cut_generation_seconds": record.cut_generation_seconds,
        "separation_model_status": record.separation_model_status,
        "separation_mip_gap": record.separation_mip_gap,
        "separation_obj_bound": record.separation_obj_bound,
        "separation_node_count": record.separation_node_count,
        "stop_reason": record.stop_reason,
    }


def _write_live_iteration(
    record: BendersIterationRecord,
    *,
    csv_path: Path | None,
    jsonl_path: Path | None,
) -> None:
    row = _live_iteration_row(record)
    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not csv_path.exists()
        with csv_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(LIVE_ITERATION_FIELDS))
            if write_header:
                writer.writeheader()
            writer.writerow({key: row.get(key, "") for key in LIVE_ITERATION_FIELDS})
            handle.flush()
    if jsonl_path is not None:
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()


def _adaptive_stall_detected(
    violations: Sequence[float],
    *,
    window_iterations: int,
    min_relative_improvement: float,
) -> bool:
    if window_iterations <= 0 or len(violations) < window_iterations:
        return False
    window = [max(0.0, float(value)) for value in violations[-window_iterations:]]
    start = window[0]
    best_later = min(window[1:] or window)
    if start <= CERTIFICATION_TOLERANCE:
        return False
    relative_improvement = (start - best_later) / max(abs(start), 1.0)
    return relative_improvement < float(min_relative_improvement)


def _separation_bound_certifies(
    solution: SeparationMilpSolution,
    *,
    epsilon: float,
) -> bool:
    """Return whether a maximization separation bound proves no violation."""

    if solution.obj_bound is None:
        return False
    return max(0.0, float(solution.obj_bound)) <= float(epsilon) + CERTIFICATION_TOLERANCE


def _separation_incumbent_can_generate_cut(
    solution: SeparationMilpSolution,
    *,
    cut_tolerance: float,
) -> bool:
    """Return whether a non-optimal separation incumbent is safe to use as a cut source."""

    if solution.objective_value is None:
        return False
    if max(0.0, float(solution.objective_value)) <= float(cut_tolerance) + CERTIFICATION_TOLERANCE:
        return False
    return all(int(value) in (0, 1) for value in solution.delta_by_line_id.values())


def _valid_restricted_master_lower_bound(
    master_problem: RestrictedMasterProblem,
    solution: RestrictedMasterProblemSolution,
) -> float:
    """Return the valid canonical restricted-master lower bound.

    When Gurobi stops with a feasible incumbent but nonzero MIP gap, ObjVal is
    not a valid minimization lower bound. ObjBound is. If the model reached
    OPTIMAL, ObjVal and ObjBound should agree up to solver tolerance.
    """

    if str(solution.model_status) == "OPTIMAL":
        return float(
            solution.original_total_objective_value
            if solution.original_total_objective_value is not None
            else (solution.objective_value or 0.0)
        )
    obj_bound = getattr(master_problem.model, "ObjBound", None)
    if obj_bound is not None:
        return float(obj_bound)
    return float(
        solution.original_total_objective_value
        if solution.original_total_objective_value is not None
        else (solution.objective_value or 0.0)
    )


def _pricing_violation_bound(solution: SeparationMilpSolution) -> float:
    """Return the valid full-support pricing violation upper bound."""

    if solution.obj_bound is not None:
        return max(0.0, float(solution.obj_bound))
    return max(0.0, float(solution.objective_value or 0.0))


def _pricing_derived_upper_bound(
    instance: CanonicalInstance,
    *,
    original_objective_value: float,
    violation_bound: float,
) -> float:
    """Return a valid weighted objective upper bound from full-support pricing."""

    return float(original_objective_value) + float(
        instance.economics.objective_multipliers.disaster
    ) * float(instance.economics.pi_f) * max(0.0, float(violation_bound))


def _z_hamming_distance(
    left: FixedFirstStagePlan,
    right: FixedFirstStagePlan,
) -> int:
    return int(
        sum(
            1
            for bus, value in left.z_by_bus.items()
            if int(value) != int(right.z_by_bus[bus])
        )
    )


@dataclass(frozen=True)
class LambdaFaceTrialPoint:
    """Auxiliary fixed-x alpha/lambda trial point used only for separation."""

    alpha: float
    lambda_by_line_id: dict[str, float]
    objective_value: float
    status: str
    runtime_seconds: float


def _solve_lambda_face_prox_trial(
    instance: CanonicalInstance,
    *,
    cuts: Sequence[RestrictedMasterCut],
    plan: FixedFirstStagePlan,
    canonical_alpha: float,
    canonical_lambda_by_line_id: Mapping[str, float],
    center_alpha: float,
    center_lambda_by_line_id: Mapping[str, float],
    best_violation: float | None,
    level_slack_abs: float,
    level_slack_fraction: float,
    rho_alpha: float,
    gurobi_params: Mapping[str, Any] | None,
    log_to_console: bool,
) -> LambdaFaceTrialPoint | None:
    """Solve Pro-recommended fixed-x alpha/lambda face-prox LP.

    The solution is an auxiliary trial point for full-support separation only.
    It is not a restricted-master lower bound and it does not add prox/level
    constraints to the canonical master.
    """

    if not cuts:
        return None
    line_ids = tuple(instance.sets.line_ids)
    fp_by_line_id = _resolve_fp_by_line_id(instance)
    level_slack = max(
        float(level_slack_abs),
        float(level_slack_fraction) * max(0.0, float(best_violation or 0.0)),
    )
    canonical_disaster_value = float(canonical_alpha) + sum(
        fp_by_line_id[line_id] * float(canonical_lambda_by_line_id.get(line_id, 0.0))
        for line_id in line_ids
    )

    model = Model("lambda_face_prox_trial")
    model.Params.OutputFlag = 1 if log_to_console else 0
    for key, value in dict(gurobi_params or {}).items():
        if hasattr(model.Params, str(key)):
            setattr(model.Params, str(key), value)
    alpha = model.addVar(lb=float(instance.economics.alpha_min), name="trial_alpha")
    lambda_by_line_id = {
        line_id: model.addVar(lb=0.0, name=f"trial_lambda_{line_id}")
        for line_id in line_ids
    }
    p_alpha_pos = model.addVar(lb=0.0, name="trial_p_alpha_pos")
    p_alpha_neg = model.addVar(lb=0.0, name="trial_p_alpha_neg")
    p_lambda_pos = {
        line_id: model.addVar(lb=0.0, name=f"trial_p_lambda_pos_{line_id}")
        for line_id in line_ids
    }
    p_lambda_neg = {
        line_id: model.addVar(lb=0.0, name=f"trial_p_lambda_neg_{line_id}")
        for line_id in line_ids
    }
    model.addConstr(
        alpha - float(center_alpha) == p_alpha_pos - p_alpha_neg,
        name="trial_alpha_abs_balance",
    )
    for line_id in line_ids:
        model.addConstr(
            lambda_by_line_id[line_id] - float(center_lambda_by_line_id.get(line_id, 0.0))
            == p_lambda_pos[line_id] - p_lambda_neg[line_id],
            name=f"trial_lambda_abs_balance_{line_id}",
        )

    for cut in cuts:
        if cut.is_trivial():
            continue
        base = float(cut.beta)
        for bus in instance.sets.buses:
            base -= float(cut.gamma_z_by_bus[bus]) * float(plan.z_by_bus[bus])
            base -= float(cut.gamma_n_sl_by_bus[bus]) * float(plan.n_sl_by_bus[bus])
            base -= float(cut.gamma_n_fa_by_bus[bus]) * float(plan.n_fa_by_bus[bus])
        s_var = model.addVar(lb=0.0, name=f"trial_s_{cut.cut_id}")
        u_by_line_id = {
            line_id: model.addVar(lb=0.0, name=f"trial_u_{cut.cut_id}_{line_id}")
            for line_id in line_ids
        }
        for line_id in line_ids:
            model.addConstr(
                u_by_line_id[line_id]
                >= float(cut.phi_by_line_id[line_id])
                - lambda_by_line_id[line_id]
                - s_var,
                name=f"trial_support_{cut.cut_id}_{line_id}",
            )
        model.addConstr(
            alpha
            >= base
            + int(instance.ambiguity.k_max_outages) * s_var
            + quicksum(u_by_line_id.values()),
            name=f"trial_cut_{cut.cut_id}",
        )

    model.addConstr(
        alpha
        + quicksum(fp_by_line_id[line_id] * lambda_by_line_id[line_id] for line_id in line_ids)
        <= canonical_disaster_value + level_slack,
        name="trial_level_face",
    )
    alpha_scale = 1.0 + abs(float(center_alpha))
    lambda_scale_by_line_id = {
        line_id: 1.0 + abs(float(center_lambda_by_line_id.get(line_id, 0.0)))
        for line_id in line_ids
    }
    model.setObjective(
        float(rho_alpha) * (p_alpha_pos + p_alpha_neg) / alpha_scale
        + quicksum(
            (p_lambda_pos[line_id] + p_lambda_neg[line_id])
            / lambda_scale_by_line_id[line_id]
            for line_id in line_ids
        ),
        sense=GRB.MINIMIZE,
    )
    start = perf_counter()
    model.optimize()
    runtime = perf_counter() - start
    if model.Status != GRB.OPTIMAL:
        return None
    return LambdaFaceTrialPoint(
        alpha=max(float(instance.economics.alpha_min), float(alpha.X)),
        lambda_by_line_id={
            line_id: max(0.0, float(var.X))
            for line_id, var in lambda_by_line_id.items()
        },
        objective_value=float(model.ObjVal),
        status="OPTIMAL",
        runtime_seconds=float(runtime),
    )


def run_benders_engine(
    instance: CanonicalInstance,
    *,
    cuts: Sequence[RestrictedMasterCut] | None = None,
    normal_scenario_ids: Sequence[int] | None = None,
    disaster_scenario_ids: Sequence[int] | None = None,
    omega_bounds_by_line_id: dict[str, tuple[float, float]] | None = None,
    omega_bound_safety_factor: float = 2.0,
    warm_start_plan: FixedFirstStagePlan | None = None,
    master_time_limit_seconds: float | None = None,
    master_mip_gap: float | None = None,
    master_gurobi_params: Mapping[str, Any] | None = None,
    separation_time_limit_seconds: float | None = None,
    separation_mip_gap: float | None = None,
    separation_gurobi_params: Mapping[str, Any] | None = None,
    allow_master_suboptimal_incumbent: bool = False,
    epsilon_cert: float = 0.0,
    max_iterations: int = 25,
    separation_top_cuts_per_iteration: int = 1,
    separation_pool_cuts_per_iteration: int = 0,
    adaptive_top_cuts_switch_violation: float | None = None,
    adaptive_top_cuts_after_switch: int = 1,
    allow_nonoptimal_separation_cuts: bool = False,
    nonoptimal_separation_cut_tolerance: float | None = None,
    enable_pareto_core_cuts: bool = False,
    stabilization_mode: str | None = None,
    stabilization_center_plan: FixedFirstStagePlan | None = None,
    stabilization_z_radius: int | None = None,
    stabilization_charger_sl_radius: int | None = None,
    stabilization_charger_fa_radius: int | None = None,
    stabilization_center_update_policy: str = "fixed",
    enable_level_bundle_trial: bool = False,
    level_bundle_objective_slack_abs: float = 5000.0,
    level_bundle_objective_slack_fraction: float = 0.05,
    level_bundle_rho_n: float = 0.2,
    level_bundle_rho_alpha: float = 0.05,
    level_bundle_rho_lambda: float = 1.0,
    enable_active_set_cuts: bool = False,
    active_delta_max: int = 50,
    active_neighbor_radius: int = 1,
    active_max_candidates_per_iteration: int = 5,
    active_cuts_per_iteration: int = 3,
    active_select_top_violations: bool = False,
    active_min_hamming_distance: int = 0,
    initial_active_outage_patterns: Sequence[Sequence[str]] | None = None,
    initial_outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut] | None = None,
    enable_exact_outage_rows: bool = False,
    exact_rows_per_iteration: int = 0,
    exact_row_max: int = 30,
    exact_rows_include_active: bool = True,
    enable_nccg_outage_columns: bool = False,
    nccg_keep_global_cuts: bool = False,
    nccg_complete_active_columns: bool = False,
    nccg_completion_tolerance: float = 100.0,
    nccg_completion_max_cuts_per_iteration: int = 5,
    nccg_completion_order: str = "oldest",
    enable_persistent_pricing_pool: bool = False,
    pricing_capture_passes: int = 0,
    pricing_capture_diversity_radius: int = 4,
    cross_column_broadcast: bool = False,
    broadcast_top_columns: int = 30,
    broadcast_violation_tolerance: float = 100.0,
    enable_certified_serious_step: bool = False,
    serious_level_kappa: float = 0.35,
    serious_eta_ub: float = 0.01,
    serious_tau_ub: float = 10.0,
    serious_eta_violation: float = 0.15,
    serious_chi: float = 0.05,
    serious_null_limit: int = 3,
    enable_target_face_bundle_cuts: bool = False,
    target_face_candidate_limit: int = 30,
    target_face_cuts_per_iteration: int = 6,
    target_face_neighbor_radius: int = 1,
    target_face_add_violation_fraction: float = 0.01,
    target_face_tolerance_rel: float = 1e-6,
    enable_cluster_face_bundle_cuts: bool = False,
    cluster_face_candidate_limit: int = 30,
    cluster_face_cuts_per_iteration: int = 2,
    cluster_face_add_violation_fraction: float = 0.01,
    cluster_face_tolerance_rel: float = 1e-6,
    enable_lambda_face_prox_trial: bool = False,
    lambda_face_level_slack_abs: float = 500.0,
    lambda_face_level_slack_fraction: float = 0.05,
    lambda_face_rho_alpha: float = 0.05,
    enable_alpha_lambda_warm_start: bool = True,
    enable_cut_signature_dedup: bool = False,
    enable_repeated_outage_guard: bool = False,
    generated_cut_prefix: str = "generated_cut",
    model_name_prefix: str = "round_09_benders",
    master_before_cut_lp_path: str | Path | None = None,
    master_after_cut_lp_path: str | Path | None = None,
    iteration_log_path: str | Path | None = None,
    live_iteration_trace_path: str | Path | None = None,
    live_iteration_jsonl_path: str | Path | None = None,
    adaptive_stall_window_iterations: int = 0,
    adaptive_stall_min_relative_improvement: float = 0.0,
    log_to_console: bool = False,
) -> BendersEngineResult:
    """Run the full iterative Benders-like engine."""

    resolved_max_iterations = _resolve_positive_int("max_iterations", max_iterations)
    resolved_top_cuts = _resolve_positive_int(
        "separation_top_cuts_per_iteration",
        separation_top_cuts_per_iteration,
    )
    resolved_pool_cuts = int(separation_pool_cuts_per_iteration)
    if resolved_pool_cuts < 0:
        raise RuntimeDataValidationError(
            "separation_pool_cuts_per_iteration must be nonnegative, "
            f"got {separation_pool_cuts_per_iteration!r}."
        )
    resolved_adaptive_top_cuts_after_switch = _resolve_positive_int(
        "adaptive_top_cuts_after_switch",
        adaptive_top_cuts_after_switch,
    )
    resolved_active_delta_max = _resolve_positive_int(
        "active_delta_max",
        active_delta_max,
    )
    resolved_active_neighbor_radius = int(active_neighbor_radius)
    if resolved_active_neighbor_radius < 0:
        raise RuntimeDataValidationError(
            f"active_neighbor_radius must be nonnegative, got {active_neighbor_radius!r}."
        )
    resolved_active_max_candidates = _resolve_positive_int(
        "active_max_candidates_per_iteration",
        active_max_candidates_per_iteration,
    )
    resolved_active_cuts_per_iteration = _resolve_positive_int(
        "active_cuts_per_iteration",
        active_cuts_per_iteration,
    )
    resolved_active_min_hamming_distance = int(active_min_hamming_distance)
    if resolved_active_min_hamming_distance < 0:
        raise RuntimeDataValidationError(
            "active_min_hamming_distance must be nonnegative, "
            f"got {active_min_hamming_distance!r}."
        )
    resolved_exact_rows_per_iteration = int(exact_rows_per_iteration)
    if resolved_exact_rows_per_iteration < 0:
        raise RuntimeDataValidationError(
            "exact_rows_per_iteration must be nonnegative, "
            f"got {exact_rows_per_iteration!r}."
        )
    resolved_exact_row_max = int(exact_row_max)
    if resolved_exact_row_max < 0:
        raise RuntimeDataValidationError(
            f"exact_row_max must be nonnegative, got {exact_row_max!r}."
        )
    resolved_target_face_candidate_limit = int(target_face_candidate_limit)
    if resolved_target_face_candidate_limit < 0:
        raise RuntimeDataValidationError(
            "target_face_candidate_limit must be nonnegative, "
            f"got {target_face_candidate_limit!r}."
        )
    resolved_target_face_cuts_per_iteration = int(target_face_cuts_per_iteration)
    if resolved_target_face_cuts_per_iteration < 0:
        raise RuntimeDataValidationError(
            "target_face_cuts_per_iteration must be nonnegative, "
            f"got {target_face_cuts_per_iteration!r}."
        )
    resolved_target_face_neighbor_radius = int(target_face_neighbor_radius)
    if resolved_target_face_neighbor_radius < 0:
        raise RuntimeDataValidationError(
            "target_face_neighbor_radius must be nonnegative, "
            f"got {target_face_neighbor_radius!r}."
        )
    resolved_target_face_add_violation_fraction = float(
        target_face_add_violation_fraction
    )
    if resolved_target_face_add_violation_fraction < 0.0:
        raise RuntimeDataValidationError(
            "target_face_add_violation_fraction must be nonnegative, "
            f"got {target_face_add_violation_fraction!r}."
        )
    resolved_target_face_tolerance_rel = float(target_face_tolerance_rel)
    if resolved_target_face_tolerance_rel < 0.0:
        raise RuntimeDataValidationError(
            "target_face_tolerance_rel must be nonnegative, "
            f"got {target_face_tolerance_rel!r}."
        )
    resolved_cluster_face_candidate_limit = int(cluster_face_candidate_limit)
    if resolved_cluster_face_candidate_limit < 0:
        raise RuntimeDataValidationError(
            "cluster_face_candidate_limit must be nonnegative, "
            f"got {cluster_face_candidate_limit!r}."
        )
    resolved_cluster_face_cuts_per_iteration = int(cluster_face_cuts_per_iteration)
    if resolved_cluster_face_cuts_per_iteration < 0:
        raise RuntimeDataValidationError(
            "cluster_face_cuts_per_iteration must be nonnegative, "
            f"got {cluster_face_cuts_per_iteration!r}."
        )
    resolved_cluster_face_add_violation_fraction = float(
        cluster_face_add_violation_fraction
    )
    if resolved_cluster_face_add_violation_fraction < 0.0:
        raise RuntimeDataValidationError(
            "cluster_face_add_violation_fraction must be nonnegative, "
            f"got {cluster_face_add_violation_fraction!r}."
        )
    resolved_cluster_face_tolerance_rel = float(cluster_face_tolerance_rel)
    if resolved_cluster_face_tolerance_rel < 0.0:
        raise RuntimeDataValidationError(
            "cluster_face_tolerance_rel must be nonnegative, "
            f"got {cluster_face_tolerance_rel!r}."
        )
    resolved_lambda_face_level_slack_abs = _resolve_nonnegative_float(
        "lambda_face_level_slack_abs",
        lambda_face_level_slack_abs,
    )
    resolved_lambda_face_level_slack_fraction = _resolve_nonnegative_float(
        "lambda_face_level_slack_fraction",
        lambda_face_level_slack_fraction,
    )
    resolved_lambda_face_rho_alpha = _resolve_nonnegative_float(
        "lambda_face_rho_alpha",
        lambda_face_rho_alpha,
    )
    resolved_nccg_completion_tolerance = _resolve_nonnegative_float(
        "nccg_completion_tolerance",
        nccg_completion_tolerance,
    )
    resolved_level_bundle_slack_abs = _resolve_nonnegative_float(
        "level_bundle_objective_slack_abs",
        level_bundle_objective_slack_abs,
    )
    resolved_level_bundle_slack_fraction = _resolve_nonnegative_float(
        "level_bundle_objective_slack_fraction",
        level_bundle_objective_slack_fraction,
    )
    resolved_level_bundle_rho_n = _resolve_nonnegative_float(
        "level_bundle_rho_n",
        level_bundle_rho_n,
    )
    resolved_level_bundle_rho_alpha = _resolve_nonnegative_float(
        "level_bundle_rho_alpha",
        level_bundle_rho_alpha,
    )
    resolved_level_bundle_rho_lambda = _resolve_nonnegative_float(
        "level_bundle_rho_lambda",
        level_bundle_rho_lambda,
    )
    resolved_nccg_completion_max_cuts = int(nccg_completion_max_cuts_per_iteration)
    if resolved_nccg_completion_max_cuts < 0:
        raise RuntimeDataValidationError(
            "nccg_completion_max_cuts_per_iteration must be nonnegative, "
            f"got {nccg_completion_max_cuts_per_iteration!r}."
        )
    resolved_nccg_completion_order = str(nccg_completion_order or "oldest")
    if resolved_nccg_completion_order not in {"oldest", "newest", "source_violation"}:
        raise RuntimeDataValidationError(
            "nccg_completion_order must be one of oldest, newest, source_violation; got "
            f"{nccg_completion_order!r}."
        )
    resolved_pricing_capture_passes = int(pricing_capture_passes)
    if resolved_pricing_capture_passes < 0:
        raise RuntimeDataValidationError(
            f"pricing_capture_passes must be nonnegative, got {pricing_capture_passes!r}."
        )
    resolved_pricing_capture_diversity_radius = int(pricing_capture_diversity_radius)
    if resolved_pricing_capture_diversity_radius < 0:
        raise RuntimeDataValidationError(
            "pricing_capture_diversity_radius must be nonnegative, "
            f"got {pricing_capture_diversity_radius!r}."
        )
    resolved_broadcast_top_columns = int(broadcast_top_columns)
    if resolved_broadcast_top_columns < 0:
        raise RuntimeDataValidationError(
            f"broadcast_top_columns must be nonnegative, got {broadcast_top_columns!r}."
        )
    resolved_broadcast_violation_tolerance = _resolve_nonnegative_float(
        "broadcast_violation_tolerance",
        broadcast_violation_tolerance,
    )
    resolved_serious_level_kappa = _resolve_nonnegative_float(
        "serious_level_kappa",
        serious_level_kappa,
    )
    resolved_serious_eta_ub = _resolve_nonnegative_float("serious_eta_ub", serious_eta_ub)
    resolved_serious_tau_ub = _resolve_nonnegative_float("serious_tau_ub", serious_tau_ub)
    resolved_serious_eta_violation = _resolve_nonnegative_float(
        "serious_eta_violation",
        serious_eta_violation,
    )
    if resolved_serious_eta_violation >= 1.0:
        raise RuntimeDataValidationError(
            f"serious_eta_violation must be < 1, got {serious_eta_violation!r}."
        )
    resolved_serious_chi = _resolve_nonnegative_float("serious_chi", serious_chi)
    resolved_serious_null_limit = int(serious_null_limit)
    if resolved_serious_null_limit < 0:
        raise RuntimeDataValidationError(
            f"serious_null_limit must be nonnegative, got {serious_null_limit!r}."
        )
    resolved_epsilon = _resolve_nonnegative_float("epsilon_cert", epsilon_cert)
    resolved_nonoptimal_cut_tolerance = _resolve_nonnegative_float(
        "nonoptimal_separation_cut_tolerance",
        resolved_epsilon
        if nonoptimal_separation_cut_tolerance is None
        else float(nonoptimal_separation_cut_tolerance),
    )
    current_cuts = list(cuts or [])
    current_outage_column_cuts: list[RestrictedMasterOutageColumnCut] = list(
        initial_outage_column_cuts or []
    )
    pareto_core_point = (
        build_default_pareto_core_point(instance)
        if bool(enable_pareto_core_cuts)
        else None
    )
    generated_cut_results: list[GeneratedCutResult] = []
    iteration_records: list[BendersIterationRecord] = []
    lower_bound_sequence: list[float] = []
    cut_count_sequence: list[int] = []
    pending_post_cut_record_index: int | None = None
    pending_pre_cut_solution: RestrictedMasterProblemSolution | None = None
    baseline_cut_count: int | None = None
    dumped_before_path: Path | None = None
    dumped_after_path: Path | None = None
    seen_outage_patterns: set[tuple[str, ...]] = set()
    seen_cut_signatures: set[str] = set()
    seen_cut_signatures.update(compute_cut_signature_hash(cut) for cut in current_cuts)
    seen_rowwise_cut_keys: set[tuple[tuple[str, ...], str]] = {
        (
            tuple(str(line_id) for line_id in row.active_line_ids),
            str(compute_cut_signature_hash(row.cut)),
        )
        for row in current_outage_column_cuts
    }
    outage_column_source_violation_by_id: dict[str, float] = {}
    current_warm_start_plan = warm_start_plan
    current_warm_start_alpha: float | None = None
    current_warm_start_lambda_by_line_id: dict[str, float] | None = None
    lambda_face_center_alpha: float | None = None
    lambda_face_center_lambda_by_line_id: dict[str, float] | None = None
    best_lambda_face_trial_violation: float | None = None
    current_stabilization_center_plan = stabilization_center_plan or warm_start_plan
    current_stabilization_center_alpha: float | None = None
    current_stabilization_center_lambda_by_line_id: dict[str, float] | None = None
    best_pricing_derived_upper_bound: float | None = None
    current_center_pricing_violation_bound: float | None = None
    certified_serious_null_count = 0
    resolved_stabilization_mode = (
        None if stabilization_mode in (None, "", "none") else str(stabilization_mode)
    )
    if resolved_stabilization_mode not in (None, "local_branch_z", "local_branch_z_n"):
        raise RuntimeDataValidationError(
            "stabilization_mode must be one of none, local_branch_z, local_branch_z_n."
        )
    if bool(enable_nccg_outage_columns) and (
        bool(enable_target_face_bundle_cuts) or bool(enable_cluster_face_bundle_cuts)
    ):
        raise RuntimeDataValidationError(
            "enable_nccg_outage_columns is currently incompatible with target/cluster "
            "face bundle cuts because those prototype cuts do not yet carry a unique "
            "active outage-column id."
        )
    if (bool(enable_persistent_pricing_pool) or bool(cross_column_broadcast)) and not bool(
        enable_nccg_outage_columns
    ):
        raise RuntimeDataValidationError(
            "persistent pricing capture and cross-column broadcast require "
            "enable_nccg_outage_columns=True."
        )
    resolved_center_update_policy = str(stabilization_center_update_policy or "fixed")
    if resolved_center_update_policy not in ("fixed", "last_trial", "best_violation"):
        raise RuntimeDataValidationError(
            "stabilization_center_update_policy must be one of fixed, last_trial, "
            f"best_violation; got {stabilization_center_update_policy!r}."
        )
    best_stabilization_violation: float | None = None
    fp_by_line_id = _resolve_fp_by_line_id(instance)
    active_outage_pool: list[tuple[str, ...]] = (
        _initial_active_outage_pool(instance, max_size=resolved_active_delta_max)
        if bool(enable_active_set_cuts)
        else []
    )
    if bool(enable_active_set_cuts) and initial_active_outage_patterns:
        seeded_patterns = [
            _normalize_active_outage_pattern(
                instance.sets.line_ids,
                pattern,
                budget_k=int(instance.ambiguity.k_max_outages),
            )
            for pattern in initial_active_outage_patterns
        ]
        active_outage_pool = _merge_active_outage_pool(
            active_outage_pool,
            seeded_patterns,
            max_size=resolved_active_delta_max,
            fp_by_line_id=fp_by_line_id,
        )
    exact_outage_patterns: list[tuple[str, ...]] = []
    live_csv_path = (
        Path(live_iteration_trace_path) if live_iteration_trace_path is not None else None
    )
    live_jsonl_path = (
        Path(live_iteration_jsonl_path) if live_iteration_jsonl_path is not None else None
    )
    if live_csv_path is not None and live_csv_path.exists():
        live_csv_path.unlink()
    if live_jsonl_path is not None and live_jsonl_path.exists():
        live_jsonl_path.unlink()

    final_master: RestrictedMasterProblem | None = None
    final_solution: RestrictedMasterProblemSolution | None = None
    final_residual: RestrictedMasterProblemResidualReport | None = None
    final_separation_model: SeparationMilpModel | None = None
    final_separation_solution: SeparationMilpSolution | None = None
    trial_certificate: BendersTrialCertificate | None = None
    stop_reason = "max_iterations"

    for iteration_id in range(resolved_max_iterations):
        master_start = perf_counter()
        canonical_master_problem, canonical_solution = solve_master_problem(
            instance,
            cuts=current_cuts,
            normal_scenario_ids=normal_scenario_ids,
            disaster_scenario_ids=disaster_scenario_ids,
            exact_outage_rows=exact_outage_patterns,
            outage_column_cuts=current_outage_column_cuts,
            warm_start_plan=current_warm_start_plan,
            warm_start_alpha=(
                current_warm_start_alpha if bool(enable_alpha_lambda_warm_start) else None
            ),
            warm_start_lambda_by_line_id=(
                current_warm_start_lambda_by_line_id
                if bool(enable_alpha_lambda_warm_start)
                else None
            ),
            time_limit_seconds=master_time_limit_seconds,
            mip_gap=master_mip_gap,
            gurobi_params=master_gurobi_params,
            allow_suboptimal_incumbent=allow_master_suboptimal_incumbent,
            model_name=f"{model_name_prefix}_master_{iteration_id:03d}",
            log_to_console=log_to_console,
        )
        canonical_master_seconds = perf_counter() - master_start
        master_problem = canonical_master_problem
        master_solution = canonical_solution
        master_seconds = canonical_master_seconds
        master_residual = build_master_problem_residual_report(master_problem, master_solution)

        if baseline_cut_count is None:
            baseline_cut_count = len(master_problem.cuts)
        if pending_post_cut_record_index is not None:
            if pending_pre_cut_solution is None:
                raise RuntimeDataValidationError("Missing pending pre-cut solution state.")
            pre_plan_signature = _plan_signature(pending_pre_cut_solution)
            post_plan_signature = _plan_signature(master_solution)
            first_stage_plan_changed = pre_plan_signature != post_plan_signature
            alpha_lambda_changed = (
                _alpha_lambda_signature(pending_pre_cut_solution)
                != _alpha_lambda_signature(master_solution)
            )
            iteration_records[pending_post_cut_record_index] = _copy_iteration_record(
                iteration_records[pending_post_cut_record_index],
                post_cut_master_objective=float(master_solution.objective_value or 0.0),
                first_stage_plan_changed=first_stage_plan_changed,
                alpha_lambda_only_change=(not first_stage_plan_changed) and alpha_lambda_changed,
            )
            pending_post_cut_record_index = None
            pending_pre_cut_solution = None
        if dumped_before_path is None and master_before_cut_lp_path is not None:
            dumped_before_path = dump_model_artifact(master_problem, master_before_cut_lp_path)
        if (
            dumped_after_path is None
            and master_after_cut_lp_path is not None
            and len(master_problem.cuts) > baseline_cut_count
        ):
            dumped_after_path = dump_model_artifact(master_problem, master_after_cut_lp_path)

        canonical_plan = _plan_from_solution(instance, canonical_solution)
        candidate_source = "canonical"
        auxiliary_objective: float | None = None
        candidate_unpenalized_objective = (
            canonical_solution.original_total_objective_value
            if canonical_solution.original_total_objective_value is not None
            else canonical_solution.objective_value
        )
        level_bundle_bound_used: float | None = None
        trust_region_z_distance: int | None = None
        if resolved_stabilization_mode is not None or bool(enable_level_bundle_trial):
            if current_stabilization_center_plan is None:
                current_stabilization_center_plan = canonical_plan
            if current_stabilization_center_alpha is None:
                current_stabilization_center_alpha = float(canonical_solution.alpha_value)
            if current_stabilization_center_lambda_by_line_id is None:
                current_stabilization_center_lambda_by_line_id = dict(
                    canonical_solution.lambda_by_line_id
                )
            canonical_original_objective = float(
                canonical_solution.original_total_objective_value
                if canonical_solution.original_total_objective_value is not None
                else (canonical_solution.objective_value or 0.0)
            )
            canonical_valid_lower_bound = _valid_restricted_master_lower_bound(
                canonical_master_problem,
                canonical_solution,
            )
            level_slack = None
            if bool(enable_level_bundle_trial):
                if (
                    bool(enable_certified_serious_step)
                    and best_pricing_derived_upper_bound is not None
                ):
                    valid_gap = max(
                        0.0,
                        float(best_pricing_derived_upper_bound)
                        - float(canonical_valid_lower_bound),
                    )
                    level_slack = max(
                        float(resolved_level_bundle_slack_abs),
                        float(resolved_serious_level_kappa) * valid_gap,
                    )
                else:
                    progress_scale = max(
                        0.0,
                        float(best_stabilization_violation or 0.0),
                        float(best_lambda_face_trial_violation or 0.0),
                    )
                    level_slack = max(
                        float(resolved_level_bundle_slack_abs),
                        float(resolved_level_bundle_slack_fraction) * progress_scale,
                    )
                level_bundle_bound_used = canonical_original_objective + float(level_slack)
            aux_start = perf_counter()
            try:
                auxiliary_master_problem, auxiliary_solution = solve_master_problem(
                    instance,
                    cuts=current_cuts,
                    normal_scenario_ids=normal_scenario_ids,
                    disaster_scenario_ids=disaster_scenario_ids,
                    exact_outage_rows=exact_outage_patterns,
                    outage_column_cuts=current_outage_column_cuts,
                    warm_start_plan=current_warm_start_plan,
                    warm_start_alpha=(
                        current_warm_start_alpha
                        if bool(enable_alpha_lambda_warm_start)
                        else None
                    ),
                    warm_start_lambda_by_line_id=(
                        current_warm_start_lambda_by_line_id
                        if bool(enable_alpha_lambda_warm_start)
                        else None
                    ),
                    trust_region_center_plan=(
                        current_stabilization_center_plan
                        if resolved_stabilization_mode is not None
                        else None
                    ),
                    trust_region_z_radius=(
                        int(stabilization_z_radius)
                        if resolved_stabilization_mode is not None
                        and stabilization_z_radius is not None
                        else (2 if resolved_stabilization_mode is not None else None)
                    ),
                    trust_region_charger_sl_radius=(
                        int(stabilization_charger_sl_radius)
                        if resolved_stabilization_mode == "local_branch_z_n"
                        else None
                    ),
                    trust_region_charger_fa_radius=(
                        int(stabilization_charger_fa_radius)
                        if resolved_stabilization_mode == "local_branch_z_n"
                        else None
                    ),
                    level_bundle_center_plan=(
                        current_stabilization_center_plan
                        if bool(enable_level_bundle_trial)
                        else None
                    ),
                    level_bundle_center_alpha=(
                        current_stabilization_center_alpha
                        if bool(enable_level_bundle_trial)
                        else None
                    ),
                    level_bundle_center_lambda_by_line_id=(
                        current_stabilization_center_lambda_by_line_id
                        if bool(enable_level_bundle_trial)
                        else None
                    ),
                    level_bundle_objective_upper_bound=level_bundle_bound_used,
                    level_bundle_rho_n=resolved_level_bundle_rho_n,
                    level_bundle_rho_alpha=resolved_level_bundle_rho_alpha,
                    level_bundle_rho_lambda=resolved_level_bundle_rho_lambda,
                    time_limit_seconds=master_time_limit_seconds,
                    mip_gap=master_mip_gap,
                    gurobi_params=master_gurobi_params,
                    allow_suboptimal_incumbent=allow_master_suboptimal_incumbent,
                    model_name=f"{model_name_prefix}_aux_master_{iteration_id:03d}",
                    log_to_console=log_to_console,
                )
            except Exception:
                auxiliary_master_problem = None
                auxiliary_solution = None
            aux_seconds = perf_counter() - aux_start
            if auxiliary_solution is not None and auxiliary_master_problem is not None:
                master_problem = auxiliary_master_problem
                master_solution = auxiliary_solution
                master_seconds = float(canonical_master_seconds + aux_seconds)
                master_residual = build_master_problem_residual_report(
                    master_problem,
                    master_solution,
                )
                if resolved_stabilization_mode is not None and bool(enable_level_bundle_trial):
                    candidate_source = f"stabilized_{resolved_stabilization_mode}_level_bundle_aux"
                elif bool(enable_level_bundle_trial):
                    candidate_source = "level_bundle_aux"
                else:
                    candidate_source = f"stabilized_{resolved_stabilization_mode}"
                auxiliary_objective = auxiliary_solution.objective_value
                candidate_unpenalized_objective = (
                    auxiliary_solution.original_total_objective_value
                    if auxiliary_solution.original_total_objective_value is not None
                    else auxiliary_solution.objective_value
                )
            elif bool(enable_level_bundle_trial) or resolved_stabilization_mode is not None:
                candidate_source = "canonical_aux_fallback"

        plan = _plan_from_solution(instance, master_solution)
        if current_stabilization_center_plan is not None:
            trust_region_z_distance = _z_hamming_distance(
                plan,
                current_stabilization_center_plan,
            )
        current_warm_start_plan = plan
        current_warm_start_alpha = float(master_solution.alpha_value)
        current_warm_start_lambda_by_line_id = dict(master_solution.lambda_by_line_id)
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

        separation_alpha_value = float(master_solution.alpha_value)
        separation_lambda_by_line_id = dict(master_solution.lambda_by_line_id)
        if bool(enable_lambda_face_prox_trial):
            center_alpha = (
                separation_alpha_value
                if lambda_face_center_alpha is None
                else float(lambda_face_center_alpha)
            )
            center_lambda_by_line_id = (
                separation_lambda_by_line_id
                if lambda_face_center_lambda_by_line_id is None
                else dict(lambda_face_center_lambda_by_line_id)
            )
            lambda_face_trial = _solve_lambda_face_prox_trial(
                instance,
                cuts=current_cuts,
                plan=plan,
                canonical_alpha=separation_alpha_value,
                canonical_lambda_by_line_id=separation_lambda_by_line_id,
                center_alpha=center_alpha,
                center_lambda_by_line_id=center_lambda_by_line_id,
                best_violation=best_lambda_face_trial_violation,
                level_slack_abs=resolved_lambda_face_level_slack_abs,
                level_slack_fraction=resolved_lambda_face_level_slack_fraction,
                rho_alpha=resolved_lambda_face_rho_alpha,
                gurobi_params=master_gurobi_params,
                log_to_console=log_to_console,
            )
            if lambda_face_trial is None:
                lambda_face_trial = _solve_lambda_face_prox_trial(
                    instance,
                    cuts=current_cuts,
                    plan=plan,
                    canonical_alpha=separation_alpha_value,
                    canonical_lambda_by_line_id=separation_lambda_by_line_id,
                    center_alpha=center_alpha,
                    center_lambda_by_line_id=center_lambda_by_line_id,
                    best_violation=best_lambda_face_trial_violation,
                    level_slack_abs=3.0 * resolved_lambda_face_level_slack_abs,
                    level_slack_fraction=3.0 * resolved_lambda_face_level_slack_fraction,
                    rho_alpha=resolved_lambda_face_rho_alpha,
                    gurobi_params=master_gurobi_params,
                    log_to_console=log_to_console,
                )
            if lambda_face_trial is not None:
                separation_alpha_value = float(lambda_face_trial.alpha)
                separation_lambda_by_line_id = dict(lambda_face_trial.lambda_by_line_id)
                candidate_source = f"{candidate_source}_lambda_face_prox"
                if lambda_face_center_alpha is None:
                    lambda_face_center_alpha = float(lambda_face_trial.alpha)
                    lambda_face_center_lambda_by_line_id = dict(
                        lambda_face_trial.lambda_by_line_id
                    )

        separation_start = perf_counter()
        separation_model, separation_solution = solve_separation_milp(
            instance,
            plan=plan,
            alpha=separation_alpha_value,
            lambda_by_line_id=separation_lambda_by_line_id,
            omega_bounds_by_line_id=resolved_omega_bounds,
            budget_k=int(instance.ambiguity.k_max_outages),
            scenario_ids=disaster_scenario_ids,
            model_name=f"{model_name_prefix}_separation_{iteration_id:03d}",
            time_limit_seconds=separation_time_limit_seconds,
            mip_gap=separation_mip_gap,
            gurobi_params=separation_gurobi_params,
            require_optimal=False,
            log_to_console=log_to_console,
        )
        separation_seconds = perf_counter() - separation_start
        separation_status_is_optimal = separation_solution.model_status == "OPTIMAL"
        separation_bound_certifies = _separation_bound_certifies(
            separation_solution,
            epsilon=resolved_epsilon,
        )
        use_nonoptimal_incumbent_cut = (
            (not separation_status_is_optimal)
            and bool(allow_nonoptimal_separation_cuts)
            and _separation_incumbent_can_generate_cut(
                separation_solution,
                cut_tolerance=resolved_nonoptimal_cut_tolerance,
            )
        )

        pricing_violation_upper_bound = _pricing_violation_bound(separation_solution)
        pricing_upper_bound = _pricing_derived_upper_bound(
            instance,
            original_objective_value=float(candidate_unpenalized_objective or 0.0),
            violation_bound=pricing_violation_upper_bound,
        )
        previous_best_upper_bound = best_pricing_derived_upper_bound
        certified_serious_step_type: str | None = None
        valid_gap_bound = (
            None
            if best_pricing_derived_upper_bound is None
            else max(
                0.0,
                float(best_pricing_derived_upper_bound)
                - _valid_restricted_master_lower_bound(
                    canonical_master_problem,
                    canonical_solution,
                ),
            )
        )
        if bool(enable_certified_serious_step):
            valid_lb_for_serious = _valid_restricted_master_lower_bound(
                canonical_master_problem,
                canonical_solution,
            )
            if previous_best_upper_bound is None:
                certified_serious_step_type = "ub_serious_initial"
            else:
                required_ub_drop = max(
                    float(resolved_serious_tau_ub),
                    float(resolved_serious_eta_ub)
                    * max(0.0, float(previous_best_upper_bound) - valid_lb_for_serious),
                )
                if pricing_upper_bound <= float(previous_best_upper_bound) - required_ub_drop:
                    certified_serious_step_type = "ub_serious"
                elif current_center_pricing_violation_bound is not None:
                    violation_target = (
                        (1.0 - float(resolved_serious_eta_violation))
                        * float(current_center_pricing_violation_bound)
                    )
                    allowed_ub = float(previous_best_upper_bound) + float(
                        resolved_serious_chi
                    ) * max(0.0, float(previous_best_upper_bound) - valid_lb_for_serious)
                    if (
                        pricing_violation_upper_bound <= violation_target
                        and pricing_upper_bound <= allowed_ub
                    ):
                        certified_serious_step_type = "violation_serious"
            if certified_serious_step_type is None:
                certified_serious_null_count += 1
                certified_serious_step_type = "null_step"
            else:
                if certified_serious_step_type.startswith("ub_serious"):
                    best_pricing_derived_upper_bound = (
                        pricing_upper_bound
                        if best_pricing_derived_upper_bound is None
                        else min(
                            float(best_pricing_derived_upper_bound),
                            float(pricing_upper_bound),
                        )
                    )
                current_center_pricing_violation_bound = float(pricing_violation_upper_bound)
                certified_serious_null_count = 0
            valid_gap_bound = (
                None
                if best_pricing_derived_upper_bound is None
                else max(
                    0.0,
                    float(best_pricing_derived_upper_bound)
                    - float(valid_lb_for_serious),
                )
            )

        if (not separation_status_is_optimal) and separation_bound_certifies:
            lower_bound_value = _valid_restricted_master_lower_bound(
                canonical_master_problem,
                canonical_solution,
            )
            violation_value = max(0.0, float(separation_solution.obj_bound or 0.0))
            active_cut_ids_before = (
                tuple(cut.cut_id for cut in master_problem.cuts)
                + tuple(row.row_id for row in master_problem.outage_column_cuts)
            )
            selected_outage_active_lines = _active_outage_lines(
                separation_solution.delta_by_line_id
            )
            repeated_outage_flag = selected_outage_active_lines in seen_outage_patterns
            seen_outage_patterns.add(selected_outage_active_lines)

            final_master = canonical_master_problem
            final_solution = canonical_solution
            final_residual = build_master_problem_residual_report(
                canonical_master_problem,
                canonical_solution,
            )
            final_separation_model = separation_model
            final_separation_solution = separation_solution
            lower_bound_sequence.append(lower_bound_value)
            cut_count_sequence.append(
                len(master_problem.cuts) + len(master_problem.outage_column_cuts)
            )
            stop_reason = (
                "certified_epsilon_bound"
                if candidate_source == "canonical"
                else "trial_point_separation_bound_below_epsilon_needs_canonical_certificate"
            )
            if candidate_source != "canonical":
                trial_certificate = _build_trial_certificate(
                    instance=instance,
                    iteration_id=iteration_id,
                    stop_reason=stop_reason,
                    candidate_source=candidate_source,
                    canonical_master_problem=canonical_master_problem,
                    canonical_solution=canonical_solution,
                    plan=plan,
                    separation_alpha_value=separation_alpha_value,
                    separation_lambda_by_line_id=separation_lambda_by_line_id,
                    separation_solution=separation_solution,
                    auxiliary_objective=auxiliary_objective,
                    candidate_unpenalized_objective=candidate_unpenalized_objective,
                    pricing_violation_upper_bound=pricing_violation_upper_bound,
                    pricing_upper_bound=pricing_upper_bound,
                    best_pricing_derived_upper_bound=best_pricing_derived_upper_bound,
                    level_bundle_bound_used=level_bundle_bound_used,
                    trust_region_z_distance=trust_region_z_distance,
                    epsilon_cert=resolved_epsilon,
                )
            record = BendersIterationRecord(
                    iteration_id=iteration_id,
                    pre_cut_master_objective=lower_bound_value,
                    post_cut_master_objective=None,
                    separation_violation_value=violation_value,
                    candidate_source=candidate_source,
                    canonical_master_objective=canonical_solution.objective_value,
                    auxiliary_master_objective=auxiliary_objective,
                    unpenalized_candidate_objective=candidate_unpenalized_objective,
                    trust_region_z_radius=(
                        int(stabilization_z_radius)
                        if stabilization_z_radius is not None
                        else (2 if resolved_stabilization_mode is not None else None)
                    ),
                    trust_region_z_distance=trust_region_z_distance,
                    selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                    selected_outage_active_lines=selected_outage_active_lines,
                    repeated_outage_flag=repeated_outage_flag,
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    total_cut_count_after=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    generated_cut_old_master_violation=None,
                    cut_added=False,
                    cut_addition_status=(
                        "certified_from_separation_bound"
                        if candidate_source == "canonical"
                        else stop_reason
                    ),
                    construction_cost_value=float(master_solution.construction_cost_value),
                    first_stage_attached_objective_value=(
                        master_solution.first_stage_solution.objective_value
                    ),
                    first_stage_objective_is_pure_construction=bool(
                        master_solution.first_stage_solution.objective_is_pure_construction
                    ),
                    master_solve_seconds=float(master_seconds),
                    separation_solve_seconds=float(separation_seconds),
                    separation_model_status=separation_solution.model_status,
                    separation_mip_gap=separation_solution.mip_gap,
                    separation_obj_bound=separation_solution.obj_bound,
                    separation_node_count=separation_solution.node_count,
                    separation_max_omega_bound_violation=(
                        separation_solution.max_omega_bound_violation
                    ),
                    separation_min_omega_upper_slack=_min_omega_upper_slack(
                        separation_solution
                    ),
                    separation_min_active_omega_upper_slack=(
                        _min_active_omega_upper_slack(separation_solution)
                    ),
                    separation_reconstruction_gap=separation_solution.reconstruction_gap,
                    cut_generation_seconds=0.0,
                    stop_reason=stop_reason,
            )
            record = replace(
                record,
                valid_lb_used=lower_bound_value,
                auxiliary_used_for_lb=False,
                level_bundle_objective_upper_bound=level_bundle_bound_used,
                level_bundle_center_policy=(
                    resolved_center_update_policy if bool(enable_level_bundle_trial) else None
                ),
            )
            iteration_records.append(record)
            _write_live_iteration(record, csv_path=live_csv_path, jsonl_path=live_jsonl_path)
            break

        if (not separation_status_is_optimal) and not use_nonoptimal_incumbent_cut:
            lower_bound_value = _valid_restricted_master_lower_bound(
                canonical_master_problem,
                canonical_solution,
            )
            violation_value = max(0.0, float(separation_solution.objective_value or 0.0))
            active_cut_ids_before = (
                tuple(cut.cut_id for cut in master_problem.cuts)
                + tuple(row.row_id for row in master_problem.outage_column_cuts)
            )
            selected_outage_active_lines = _active_outage_lines(
                separation_solution.delta_by_line_id
            )
            repeated_outage_flag = selected_outage_active_lines in seen_outage_patterns
            seen_outage_patterns.add(selected_outage_active_lines)

            final_master = canonical_master_problem
            final_solution = canonical_solution
            final_residual = build_master_problem_residual_report(
                canonical_master_problem,
                canonical_solution,
            )
            final_separation_model = separation_model
            final_separation_solution = separation_solution
            lower_bound_sequence.append(lower_bound_value)
            cut_count_sequence.append(
                len(master_problem.cuts) + len(master_problem.outage_column_cuts)
            )
            stop_reason = f"separation_{separation_solution.model_status.lower()}"
            record = BendersIterationRecord(
                    iteration_id=iteration_id,
                    pre_cut_master_objective=lower_bound_value,
                    post_cut_master_objective=None,
                    separation_violation_value=violation_value,
                    candidate_source=candidate_source,
                    canonical_master_objective=canonical_solution.objective_value,
                    auxiliary_master_objective=auxiliary_objective,
                    unpenalized_candidate_objective=candidate_unpenalized_objective,
                    trust_region_z_radius=(
                        int(stabilization_z_radius)
                        if stabilization_z_radius is not None
                        else (2 if resolved_stabilization_mode is not None else None)
                    ),
                    trust_region_z_distance=trust_region_z_distance,
                    selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                    selected_outage_active_lines=selected_outage_active_lines,
                    repeated_outage_flag=repeated_outage_flag,
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    total_cut_count_after=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    generated_cut_old_master_violation=None,
                    cut_added=False,
                    cut_addition_status=stop_reason,
                    construction_cost_value=float(master_solution.construction_cost_value),
                    first_stage_attached_objective_value=(
                        master_solution.first_stage_solution.objective_value
                    ),
                    first_stage_objective_is_pure_construction=bool(
                        master_solution.first_stage_solution.objective_is_pure_construction
                    ),
                    master_solve_seconds=float(master_seconds),
                    separation_solve_seconds=float(separation_seconds),
                    separation_model_status=separation_solution.model_status,
                    separation_mip_gap=separation_solution.mip_gap,
                    separation_obj_bound=separation_solution.obj_bound,
                    separation_node_count=separation_solution.node_count,
                    separation_max_omega_bound_violation=(
                        separation_solution.max_omega_bound_violation
                    ),
                    separation_min_omega_upper_slack=_min_omega_upper_slack(
                        separation_solution
                    ),
                    separation_min_active_omega_upper_slack=(
                        _min_active_omega_upper_slack(separation_solution)
                    ),
                    separation_reconstruction_gap=separation_solution.reconstruction_gap,
                    cut_generation_seconds=0.0,
                    stop_reason=stop_reason,
            )
            record = replace(
                record,
                valid_lb_used=lower_bound_value,
                auxiliary_used_for_lb=False,
                level_bundle_objective_upper_bound=level_bundle_bound_used,
                level_bundle_center_policy=(
                    resolved_center_update_policy if bool(enable_level_bundle_trial) else None
                ),
            )
            iteration_records.append(record)
            _write_live_iteration(record, csv_path=live_csv_path, jsonl_path=live_jsonl_path)
            break

        lower_bound_value = _valid_restricted_master_lower_bound(
            canonical_master_problem,
            canonical_solution,
        )
        violation_value = max(0.0, float(separation_solution.objective_value or 0.0))
        active_cut_ids_before = (
            tuple(cut.cut_id for cut in master_problem.cuts)
            + tuple(row.row_id for row in master_problem.outage_column_cuts)
        )
        selected_outage_active_lines = _active_outage_lines(separation_solution.delta_by_line_id)
        repeated_outage_flag = selected_outage_active_lines in seen_outage_patterns
        seen_outage_patterns.add(selected_outage_active_lines)

        final_master = canonical_master_problem
        final_solution = canonical_solution
        final_residual = build_master_problem_residual_report(
            canonical_master_problem,
            canonical_solution,
        )
        final_separation_model = separation_model
        final_separation_solution = separation_solution

        lower_bound_sequence.append(lower_bound_value)
        cut_count_sequence.append(
            len(master_problem.cuts) + len(master_problem.outage_column_cuts)
        )

        if (
            candidate_source != "canonical"
            and separation_status_is_optimal
            and violation_value <= resolved_epsilon + CERTIFICATION_TOLERANCE
        ):
            stop_reason = "trial_point_full_support_below_epsilon_needs_canonical_certificate"
            trial_certificate = _build_trial_certificate(
                instance=instance,
                iteration_id=iteration_id,
                stop_reason=stop_reason,
                candidate_source=candidate_source,
                canonical_master_problem=canonical_master_problem,
                canonical_solution=canonical_solution,
                plan=plan,
                separation_alpha_value=separation_alpha_value,
                separation_lambda_by_line_id=separation_lambda_by_line_id,
                separation_solution=separation_solution,
                auxiliary_objective=auxiliary_objective,
                candidate_unpenalized_objective=candidate_unpenalized_objective,
                pricing_violation_upper_bound=pricing_violation_upper_bound,
                pricing_upper_bound=pricing_upper_bound,
                best_pricing_derived_upper_bound=best_pricing_derived_upper_bound,
                level_bundle_bound_used=level_bundle_bound_used,
                trust_region_z_distance=trust_region_z_distance,
                epsilon_cert=resolved_epsilon,
            )
            record = BendersIterationRecord(
                    iteration_id=iteration_id,
                    pre_cut_master_objective=lower_bound_value,
                    post_cut_master_objective=None,
                    separation_violation_value=violation_value,
                    candidate_source=candidate_source,
                    canonical_master_objective=canonical_solution.objective_value,
                    auxiliary_master_objective=auxiliary_objective,
                    unpenalized_candidate_objective=candidate_unpenalized_objective,
                    trust_region_z_radius=(
                        int(stabilization_z_radius)
                        if stabilization_z_radius is not None
                        else (2 if resolved_stabilization_mode is not None else None)
                    ),
                    trust_region_z_distance=trust_region_z_distance,
                    selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                    selected_outage_active_lines=selected_outage_active_lines,
                    repeated_outage_flag=repeated_outage_flag,
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    total_cut_count_after=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    generated_cut_old_master_violation=None,
                    cut_added=False,
                    cut_addition_status=stop_reason,
                    construction_cost_value=float(master_solution.construction_cost_value),
                    first_stage_attached_objective_value=master_solution.first_stage_solution.objective_value,
                    first_stage_objective_is_pure_construction=bool(
                        master_solution.first_stage_solution.objective_is_pure_construction
                    ),
                    master_solve_seconds=float(master_seconds),
                    separation_solve_seconds=float(separation_seconds),
                    separation_model_status=separation_solution.model_status,
                    separation_mip_gap=separation_solution.mip_gap,
                    separation_obj_bound=separation_solution.obj_bound,
                    separation_node_count=separation_solution.node_count,
                    separation_max_omega_bound_violation=(
                        separation_solution.max_omega_bound_violation
                    ),
                    separation_min_omega_upper_slack=_min_omega_upper_slack(
                        separation_solution
                    ),
                    separation_min_active_omega_upper_slack=(
                        _min_active_omega_upper_slack(separation_solution)
                    ),
                    separation_reconstruction_gap=separation_solution.reconstruction_gap,
                    cut_generation_seconds=0.0,
                    stop_reason=stop_reason,
            )
            record = replace(
                record,
                valid_lb_used=lower_bound_value,
                auxiliary_used_for_lb=False,
                level_bundle_objective_upper_bound=level_bundle_bound_used,
                level_bundle_center_policy=(
                    resolved_center_update_policy if bool(enable_level_bundle_trial) else None
                ),
            )
            iteration_records.append(record)
            _write_live_iteration(record, csv_path=live_csv_path, jsonl_path=live_jsonl_path)
            break

        if separation_status_is_optimal and violation_value <= resolved_epsilon + CERTIFICATION_TOLERANCE:
            stop_reason = (
                "certified_exact"
                if resolved_epsilon <= CERTIFICATION_TOLERANCE
                else "certified_epsilon"
            )
            record = BendersIterationRecord(
                    iteration_id=iteration_id,
                    pre_cut_master_objective=lower_bound_value,
                    post_cut_master_objective=None,
                    separation_violation_value=violation_value,
                    candidate_source=candidate_source,
                    canonical_master_objective=canonical_solution.objective_value,
                    auxiliary_master_objective=auxiliary_objective,
                    unpenalized_candidate_objective=candidate_unpenalized_objective,
                    trust_region_z_radius=(
                        int(stabilization_z_radius)
                        if stabilization_z_radius is not None
                        else (2 if resolved_stabilization_mode is not None else None)
                    ),
                    trust_region_z_distance=trust_region_z_distance,
                    selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                    selected_outage_active_lines=selected_outage_active_lines,
                    repeated_outage_flag=repeated_outage_flag,
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    total_cut_count_after=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    generated_cut_old_master_violation=None,
                    cut_added=False,
                    cut_addition_status="certified_stop",
                    construction_cost_value=float(master_solution.construction_cost_value),
                    first_stage_attached_objective_value=master_solution.first_stage_solution.objective_value,
                    first_stage_objective_is_pure_construction=bool(
                        master_solution.first_stage_solution.objective_is_pure_construction
                    ),
                    master_solve_seconds=float(master_seconds),
                    separation_solve_seconds=float(separation_seconds),
                    separation_model_status=separation_solution.model_status,
                    separation_mip_gap=separation_solution.mip_gap,
                    separation_obj_bound=separation_solution.obj_bound,
                    separation_node_count=separation_solution.node_count,
                    separation_max_omega_bound_violation=(
                        separation_solution.max_omega_bound_violation
                    ),
                    separation_min_omega_upper_slack=_min_omega_upper_slack(
                        separation_solution
                    ),
                    separation_min_active_omega_upper_slack=(
                        _min_active_omega_upper_slack(separation_solution)
                    ),
                    separation_reconstruction_gap=separation_solution.reconstruction_gap,
                    cut_generation_seconds=0.0,
                    stop_reason=stop_reason,
            )
            record = replace(
                record,
                valid_lb_used=lower_bound_value,
                auxiliary_used_for_lb=False,
                level_bundle_objective_upper_bound=level_bundle_bound_used,
                level_bundle_center_policy=(
                    resolved_center_update_policy if bool(enable_level_bundle_trial) else None
                ),
            )
            iteration_records.append(record)
            _write_live_iteration(record, csv_path=live_csv_path, jsonl_path=live_jsonl_path)
            break

        if iteration_id == resolved_max_iterations - 1:
            stop_reason = "max_iterations"
            record = BendersIterationRecord(
                    iteration_id=iteration_id,
                    pre_cut_master_objective=lower_bound_value,
                    post_cut_master_objective=None,
                    separation_violation_value=violation_value,
                    candidate_source=candidate_source,
                    canonical_master_objective=canonical_solution.objective_value,
                    auxiliary_master_objective=auxiliary_objective,
                    unpenalized_candidate_objective=candidate_unpenalized_objective,
                    trust_region_z_radius=(
                        int(stabilization_z_radius)
                        if stabilization_z_radius is not None
                        else (2 if resolved_stabilization_mode is not None else None)
                    ),
                    trust_region_z_distance=trust_region_z_distance,
                    selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                    selected_outage_active_lines=selected_outage_active_lines,
                    repeated_outage_flag=repeated_outage_flag,
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    total_cut_count_after=(
                        len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                    ),
                    generated_cut_old_master_violation=None,
                    cut_added=False,
                    cut_addition_status="max_iterations_stop",
                    construction_cost_value=float(master_solution.construction_cost_value),
                    first_stage_attached_objective_value=master_solution.first_stage_solution.objective_value,
                    first_stage_objective_is_pure_construction=bool(
                        master_solution.first_stage_solution.objective_is_pure_construction
                    ),
                    master_solve_seconds=float(master_seconds),
                    separation_solve_seconds=float(separation_seconds),
                    separation_model_status=separation_solution.model_status,
                    separation_mip_gap=separation_solution.mip_gap,
                    separation_obj_bound=separation_solution.obj_bound,
                    separation_node_count=separation_solution.node_count,
                    separation_max_omega_bound_violation=(
                        separation_solution.max_omega_bound_violation
                    ),
                    separation_min_omega_upper_slack=_min_omega_upper_slack(
                        separation_solution
                    ),
                    separation_min_active_omega_upper_slack=(
                        _min_active_omega_upper_slack(separation_solution)
                    ),
                    separation_reconstruction_gap=separation_solution.reconstruction_gap,
                    cut_generation_seconds=0.0,
                    stop_reason=stop_reason,
            )
            record = replace(
                record,
                valid_lb_used=lower_bound_value,
                auxiliary_used_for_lb=False,
                level_bundle_objective_upper_bound=level_bundle_bound_used,
                level_bundle_center_policy=(
                    resolved_center_update_policy if bool(enable_level_bundle_trial) else None
                ),
            )
            iteration_records.append(record)
            _write_live_iteration(record, csv_path=live_csv_path, jsonl_path=live_jsonl_path)
            break

        batch_solutions: list[SeparationMilpSolution] = [separation_solution]
        forbidden_patterns: list[tuple[str, ...]] = [selected_outage_active_lines]
        batch_statuses = [separation_solution.model_status]
        batch_gaps = [
            float(separation_solution.mip_gap)
            for _ in (0,)
            if separation_solution.mip_gap is not None
        ]
        batch_bounds = [
            float(separation_solution.obj_bound)
            for _ in (0,)
            if separation_solution.obj_bound is not None
        ]
        batch_nodes = [
            float(separation_solution.node_count)
            for _ in (0,)
            if separation_solution.node_count is not None
        ]
        batch_truncated_status: str | None = None
        if separation_status_is_optimal and resolved_pool_cuts > 1:
            pool_solutions = extract_separation_milp_solution_pool(
                separation_model,
                max_solutions=resolved_pool_cuts,
                min_objective=resolved_epsilon + CERTIFICATION_TOLERANCE,
                unique_outage_patterns=True,
            )
            for pool_solution in pool_solutions:
                pool_active_lines = _active_outage_lines(pool_solution.delta_by_line_id)
                if pool_active_lines in set(forbidden_patterns):
                    continue
                forbidden_patterns.append(pool_active_lines)
                seen_outage_patterns.add(pool_active_lines)
                batch_solutions.append(pool_solution)
                batch_statuses.append("OPTIMAL_POOL")

        effective_top_cuts = 1 if use_nonoptimal_incumbent_cut else resolved_top_cuts
        if adaptive_top_cuts_switch_violation is not None:
            switch_violation = _resolve_nonnegative_float(
                "adaptive_top_cuts_switch_violation",
                float(adaptive_top_cuts_switch_violation),
            )
            if violation_value <= switch_violation:
                effective_top_cuts = min(
                    resolved_top_cuts,
                    resolved_adaptive_top_cuts_after_switch,
                )

        for batch_index in range(1, effective_top_cuts):
            extra_start = perf_counter()
            _, extra_solution = solve_separation_milp(
                instance,
                plan=plan,
                alpha=separation_alpha_value,
                lambda_by_line_id=separation_lambda_by_line_id,
                omega_bounds_by_line_id=resolved_omega_bounds,
                budget_k=int(instance.ambiguity.k_max_outages),
                scenario_ids=disaster_scenario_ids,
                forbidden_outage_patterns=forbidden_patterns,
                model_name=(
                    f"{model_name_prefix}_separation_{iteration_id:03d}_"
                    f"rank_{batch_index + 1:03d}"
                ),
                time_limit_seconds=separation_time_limit_seconds,
                mip_gap=separation_mip_gap,
                gurobi_params=separation_gurobi_params,
                require_optimal=False,
                log_to_console=log_to_console,
            )
            separation_seconds += perf_counter() - extra_start
            batch_statuses.append(extra_solution.model_status)
            if extra_solution.mip_gap is not None:
                batch_gaps.append(float(extra_solution.mip_gap))
            if extra_solution.obj_bound is not None:
                batch_bounds.append(float(extra_solution.obj_bound))
            if extra_solution.node_count is not None:
                batch_nodes.append(float(extra_solution.node_count))
            if extra_solution.model_status != "OPTIMAL":
                batch_truncated_status = f"top_m_truncated_{extra_solution.model_status}"
                break
            extra_violation = max(0.0, float(extra_solution.objective_value or 0.0))
            if extra_violation <= resolved_epsilon + CERTIFICATION_TOLERANCE:
                break
            extra_active_lines = _active_outage_lines(extra_solution.delta_by_line_id)
            forbidden_patterns.append(extra_active_lines)
            seen_outage_patterns.add(extra_active_lines)
            batch_solutions.append(extra_solution)

        pricing_capture_seconds = 0.0
        pricing_capture_count = 0
        pricing_capture_best_violation: float | None = None
        effective_pricing_capture_passes = resolved_pricing_capture_passes
        if (
            bool(enable_certified_serious_step)
            and resolved_serious_null_limit > 0
            and certified_serious_null_count >= resolved_serious_null_limit
        ):
            effective_pricing_capture_passes += 2
        if (
            bool(enable_persistent_pricing_pool)
            and separation_status_is_optimal
            and effective_pricing_capture_passes > 0
        ):
            capture_hamming_balls: list[tuple[tuple[str, ...], int]] = []
            if resolved_pricing_capture_diversity_radius > 0:
                capture_hamming_balls.extend(
                    (tuple(pattern), resolved_pricing_capture_diversity_radius)
                    for pattern in forbidden_patterns
                )
            for capture_index in range(effective_pricing_capture_passes):
                capture_start = perf_counter()
                _, capture_solution = solve_separation_milp(
                    instance,
                    plan=plan,
                    alpha=separation_alpha_value,
                    lambda_by_line_id=separation_lambda_by_line_id,
                    omega_bounds_by_line_id=resolved_omega_bounds,
                    budget_k=int(instance.ambiguity.k_max_outages),
                    scenario_ids=disaster_scenario_ids,
                    forbidden_outage_patterns=forbidden_patterns,
                    forbidden_outage_hamming_balls=capture_hamming_balls,
                    model_name=(
                        f"{model_name_prefix}_separation_{iteration_id:03d}_"
                        f"capture_{capture_index + 1:03d}"
                    ),
                    time_limit_seconds=separation_time_limit_seconds,
                    mip_gap=separation_mip_gap,
                    gurobi_params=separation_gurobi_params,
                    require_optimal=False,
                    log_to_console=log_to_console,
                )
                elapsed = perf_counter() - capture_start
                pricing_capture_seconds += elapsed
                separation_seconds += elapsed
                batch_statuses.append(f"CAPTURE_{capture_solution.model_status}")
                if capture_solution.mip_gap is not None:
                    batch_gaps.append(float(capture_solution.mip_gap))
                if capture_solution.obj_bound is not None:
                    batch_bounds.append(float(capture_solution.obj_bound))
                if capture_solution.node_count is not None:
                    batch_nodes.append(float(capture_solution.node_count))
                if capture_solution.model_status != "OPTIMAL":
                    batch_truncated_status = (
                        f"pricing_capture_truncated_{capture_solution.model_status}"
                    )
                    break
                capture_violation = max(
                    0.0,
                    float(capture_solution.objective_value or 0.0),
                )
                pricing_capture_best_violation = (
                    capture_violation
                    if pricing_capture_best_violation is None
                    else max(pricing_capture_best_violation, capture_violation)
                )
                if capture_violation <= resolved_epsilon + CERTIFICATION_TOLERANCE:
                    break
                capture_active_lines = _active_outage_lines(
                    capture_solution.delta_by_line_id
                )
                forbidden_patterns.append(capture_active_lines)
                if resolved_pricing_capture_diversity_radius > 0:
                    capture_hamming_balls.append(
                        (
                            capture_active_lines,
                            resolved_pricing_capture_diversity_radius,
                        )
                    )
                seen_outage_patterns.add(capture_active_lines)
                batch_solutions.append(capture_solution)
                pricing_capture_count += 1

        cut_start = perf_counter()
        batch_cut_results: list[GeneratedCutResult] = []
        batch_cut_result_patterns: list[tuple[str, ...]] = []
        for batch_index, batch_solution in enumerate(batch_solutions):
            batch_pattern = _active_outage_lines(batch_solution.delta_by_line_id)
            batch_cut_result = generate_cut_from_separation_solution(
                instance,
                plan=plan,
                separation_solution=batch_solution,
                scenario_ids=disaster_scenario_ids,
                cut_id=_make_generated_cut_id(
                    generated_cut_prefix,
                    len(generated_cut_results) + len(batch_cut_results) + 1,
                ),
                provenance=(
                    f"{model_name_prefix}_iteration_{iteration_id:03d}_"
                    f"rank_{batch_index + 1:03d}"
                ),
                lambda_by_line_id=separation_lambda_by_line_id,
                pareto_core_point=pareto_core_point,
                log_to_console=log_to_console,
            )
            batch_cut_results.append(batch_cut_result)
            batch_cut_result_patterns.append(batch_pattern)

        broadcast_candidate_count = 0
        broadcast_added_count = 0
        if (
            bool(cross_column_broadcast)
            and bool(enable_nccg_outage_columns)
            and resolved_broadcast_top_columns > 0
            and batch_cut_results
            and master_problem.outage_column_cuts
        ):
            existing_columns: dict[str, tuple[str, ...]] = {}
            for rowwise_cut in master_problem.outage_column_cuts:
                existing_columns.setdefault(
                    rowwise_cut.column_id,
                    rowwise_cut.active_line_ids,
                )
            planned_rowwise_keys: set[tuple[tuple[str, ...], str]] = set()
            broadcast_cut_results: list[GeneratedCutResult] = []
            broadcast_patterns: list[tuple[str, ...]] = []
            for source_result, source_pattern in zip(
                tuple(batch_cut_results),
                tuple(batch_cut_result_patterns),
            ):
                ranked_broadcasts: list[tuple[float, tuple[str, ...]]] = []
                ranked_score_fallbacks: list[tuple[float, float, tuple[str, ...]]] = []
                for column_id, active_pattern in existing_columns.items():
                    normalized_pattern = tuple(str(line_id) for line_id in active_pattern)
                    if normalized_pattern == tuple(source_pattern):
                        continue
                    rowwise_key = (
                        normalized_pattern,
                        str(source_result.cut_signature_hash),
                    )
                    if (
                        rowwise_key in seen_rowwise_cut_keys
                        or rowwise_key in planned_rowwise_keys
                    ):
                        continue
                    theta_value = float(
                        master_solution.theta_by_outage_column_id.get(column_id, 0.0)
                    )
                    predicted_violation = (
                        _rowwise_cut_value_at_pattern(
                            source_result.cut,
                            plan=plan,
                            active_line_ids=normalized_pattern,
                        )
                        - theta_value
                    )
                    if (
                        predicted_violation
                        >= resolved_broadcast_violation_tolerance
                        + CERTIFICATION_TOLERANCE
                    ):
                        ranked_broadcasts.append(
                            (float(predicted_violation), normalized_pattern)
                        )
                    else:
                        ranked_score_fallbacks.append(
                            (
                                float(
                                    outage_column_source_violation_by_id.get(
                                        column_id,
                                        0.0,
                                    )
                                ),
                                float(predicted_violation),
                                normalized_pattern,
                            )
                        )
                broadcast_candidate_count += len(ranked_broadcasts)
                selected_broadcast_patterns: list[tuple[str, ...]] = []
                for _, broadcast_pattern in sorted(
                    ranked_broadcasts,
                    key=lambda item: item[0],
                    reverse=True,
                ):
                    if len(selected_broadcast_patterns) >= resolved_broadcast_top_columns:
                        break
                    selected_broadcast_patterns.append(broadcast_pattern)
                for _, _, broadcast_pattern in sorted(
                    ranked_score_fallbacks,
                    key=lambda item: (item[0], item[1]),
                    reverse=True,
                ):
                    if len(selected_broadcast_patterns) >= resolved_broadcast_top_columns:
                        break
                    selected_broadcast_patterns.append(broadcast_pattern)
                for broadcast_pattern in selected_broadcast_patterns:
                    rowwise_key = (
                        broadcast_pattern,
                        str(source_result.cut_signature_hash),
                    )
                    planned_rowwise_keys.add(rowwise_key)
                    broadcast_cut_results.append(source_result)
                    broadcast_patterns.append(broadcast_pattern)
            if broadcast_cut_results:
                batch_cut_results.extend(broadcast_cut_results)
                batch_cut_result_patterns.extend(broadcast_patterns)
                broadcast_added_count = len(broadcast_cut_results)

        active_set_start = perf_counter()
        active_cut_results: list[GeneratedCutResult] = []
        selected_active_patterns: list[tuple[str, ...]] = []
        active_candidate_cut_results: list[
            tuple[tuple[str, ...], GeneratedCutResult]
        ] = []
        active_candidate_count = 0
        active_best_validated_violation: float | None = None
        full_support_patterns = {
            _active_outage_lines(solution.delta_by_line_id)
            for solution in batch_solutions
        }
        if bool(enable_active_set_cuts):
            additions: list[tuple[str, ...]] = []
            for pattern in full_support_patterns:
                additions.append(pattern)
                additions.extend(
                    _neighbor_outage_patterns(
                        pattern,
                        line_ids=instance.sets.line_ids,
                        budget_k=int(instance.ambiguity.k_max_outages),
                        radius=resolved_active_neighbor_radius,
                    )
                )
            active_outage_pool = _merge_active_outage_pool(
                active_outage_pool,
                additions,
                max_size=resolved_active_delta_max,
                fp_by_line_id=fp_by_line_id,
            )
            active_cut_index = 0
            for active_pattern in active_outage_pool:
                if active_pattern in full_support_patterns:
                    continue
                if active_candidate_count >= resolved_active_max_candidates:
                    break
                active_candidate_count += 1
                active_delta = _delta_by_line_id_from_active_lines(
                    instance.sets.line_ids,
                    active_pattern,
                )
                active_outage = build_fixed_outage_vector(instance, by_line_id=active_delta)
                active_cut_result = generate_structured_cut(
                    instance,
                    plan=plan,
                    outage=active_outage,
                    scenario_ids=disaster_scenario_ids,
                    cut_id=_make_generated_cut_id(
                        f"{generated_cut_prefix}_active_i{iteration_id:03d}",
                        active_cut_index + 1,
                    ),
                    provenance=(
                        f"{model_name_prefix}_iteration_{iteration_id:03d}_"
                        f"active_{active_cut_index + 1:03d}"
                    ),
                    source_alpha=separation_alpha_value,
                    source_lambda_by_line_id=separation_lambda_by_line_id,
                    pareto_core_point=pareto_core_point,
                    log_to_console=log_to_console,
                )
                active_cut_index += 1
                active_violation = float(active_cut_result.old_master_cut_violation or 0.0)
                active_best_validated_violation = (
                    active_violation
                    if active_best_validated_violation is None
                    else max(active_best_validated_violation, active_violation)
                )
                if active_violation <= resolved_epsilon + CERTIFICATION_TOLERANCE:
                    continue
                if bool(active_select_top_violations):
                    active_candidate_cut_results.append((active_pattern, active_cut_result))
                    continue
                active_cut_results.append(active_cut_result)
                selected_active_patterns.append(active_pattern)
                if len(active_cut_results) >= resolved_active_cuts_per_iteration:
                    break
            if bool(active_select_top_violations) and active_candidate_cut_results:
                ranked_candidates = sorted(
                    active_candidate_cut_results,
                    key=lambda item: float(item[1].old_master_cut_violation or 0.0),
                    reverse=True,
                )
                selected_candidates: list[tuple[tuple[str, ...], GeneratedCutResult]] = []
                deferred_candidates: list[tuple[tuple[str, ...], GeneratedCutResult]] = []
                for candidate_pattern, candidate_result in ranked_candidates:
                    if (
                        resolved_active_min_hamming_distance <= 0
                        or all(
                            len(set(candidate_pattern).symmetric_difference(selected_pattern))
                            >= resolved_active_min_hamming_distance
                            for selected_pattern, _ in selected_candidates
                        )
                    ):
                        selected_candidates.append((candidate_pattern, candidate_result))
                    else:
                        deferred_candidates.append((candidate_pattern, candidate_result))
                    if len(selected_candidates) >= resolved_active_cuts_per_iteration:
                        break
                if len(selected_candidates) < resolved_active_cuts_per_iteration:
                    seen_patterns = {pattern for pattern, _ in selected_candidates}
                    for candidate_pattern, candidate_result in deferred_candidates:
                        if candidate_pattern in seen_patterns:
                            continue
                        selected_candidates.append((candidate_pattern, candidate_result))
                        seen_patterns.add(candidate_pattern)
                        if len(selected_candidates) >= resolved_active_cuts_per_iteration:
                            break
                active_cut_results = [result for _, result in selected_candidates]
                selected_active_patterns = [pattern for pattern, _ in selected_candidates]
        active_set_seconds = perf_counter() - active_set_start
        batch_cut_results.extend(active_cut_results)
        batch_cut_result_patterns.extend(selected_active_patterns)
        if (
            bool(enable_nccg_outage_columns)
            and bool(nccg_complete_active_columns)
            and resolved_nccg_completion_max_cuts > 0
            and master_problem.outage_column_cuts
        ):
            existing_columns: dict[str, tuple[str, ...]] = {}
            for rowwise_cut in master_problem.outage_column_cuts:
                existing_columns.setdefault(
                    rowwise_cut.column_id,
                    rowwise_cut.active_line_ids,
                )
            completion_added = 0
            completion_items = list(existing_columns.items())
            if resolved_nccg_completion_order == "newest":
                completion_items = list(reversed(completion_items))
            elif resolved_nccg_completion_order == "source_violation":
                completion_items = sorted(
                    completion_items,
                    key=lambda item: float(
                        outage_column_source_violation_by_id.get(item[0], 0.0)
                    ),
                    reverse=True,
                )
            for column_id, active_pattern in completion_items:
                if completion_added >= resolved_nccg_completion_max_cuts:
                    break
                theta_value = float(
                    master_solution.theta_by_outage_column_id.get(column_id, 0.0)
                )
                completion_delta = _delta_by_line_id_from_active_lines(
                    instance.sets.line_ids,
                    active_pattern,
                )
                completion_outage = build_fixed_outage_vector(
                    instance,
                    by_line_id=completion_delta,
                )
                completion_cut_result = generate_structured_cut(
                    instance,
                    plan=plan,
                    outage=completion_outage,
                    scenario_ids=disaster_scenario_ids,
                    cut_id=_make_generated_cut_id(
                        f"{generated_cut_prefix}_nccgcomp_i{iteration_id:03d}",
                        completion_added + 1,
                    ),
                    provenance=(
                        f"{model_name_prefix}_iteration_{iteration_id:03d}_"
                        f"nccg_completion_{completion_added + 1:03d}"
                    ),
                    source_alpha=separation_alpha_value,
                    source_lambda_by_line_id=separation_lambda_by_line_id,
                    pareto_core_point=pareto_core_point,
                    log_to_console=log_to_console,
                )
                sample_values = tuple(
                    float(value)
                    for value in completion_cut_result.audit.samplewise_objective_by_scenario.values()
                )
                fixed_column_value = (
                    sum(sample_values) / len(sample_values) if sample_values else 0.0
                )
                if (
                    fixed_column_value - theta_value
                    <= resolved_nccg_completion_tolerance + CERTIFICATION_TOLERANCE
                ):
                    continue
                batch_cut_results.append(completion_cut_result)
                batch_cut_result_patterns.append(tuple(active_pattern))
                completion_added += 1
        if (
            bool(enable_target_face_bundle_cuts)
            and resolved_target_face_cuts_per_iteration > 0
            and batch_solutions
        ):
            target_candidates: list[tuple[str, ...]] = []
            for pattern in selected_active_patterns:
                if pattern not in target_candidates:
                    target_candidates.append(pattern)
            for pattern in active_outage_pool:
                if pattern not in target_candidates:
                    target_candidates.append(pattern)
                if len(target_candidates) >= resolved_target_face_candidate_limit:
                    break
            if not target_candidates:
                for pattern in full_support_patterns:
                    for neighbor in _neighbor_outage_patterns(
                        pattern,
                        line_ids=instance.sets.line_ids,
                        budget_k=int(instance.ambiguity.k_max_outages),
                        radius=resolved_target_face_neighbor_radius,
                    ):
                        if neighbor not in target_candidates:
                            target_candidates.append(neighbor)
                        if len(target_candidates) >= resolved_target_face_candidate_limit:
                            break
                    if len(target_candidates) >= resolved_target_face_candidate_limit:
                        break
            remaining_target_face_cuts = resolved_target_face_cuts_per_iteration
            target_face_min_violation = max(
                resolved_epsilon,
                resolved_target_face_add_violation_fraction
                * max(0.0, float(separation_solution.objective_value or 0.0)),
            )
            for source_index, source_solution in enumerate(batch_solutions, start=1):
                if remaining_target_face_cuts <= 0:
                    break
                source_pattern = _active_outage_lines(source_solution.delta_by_line_id)
                source_outage = build_fixed_outage_vector(
                    instance,
                    by_line_id=source_solution.delta_by_line_id,
                )
                target_outages = [
                    build_fixed_outage_vector(
                        instance,
                        by_line_id=_delta_by_line_id_from_active_lines(
                            instance.sets.line_ids,
                            pattern,
                        ),
                    )
                    for pattern in target_candidates
                    if pattern != source_pattern
                ][:resolved_target_face_candidate_limit]
                target_face_results = generate_target_face_bundle_cuts(
                    instance,
                    plan=plan,
                    source_outage=source_outage,
                    target_outages=target_outages,
                    scenario_ids=disaster_scenario_ids,
                    cut_id_prefix=_make_generated_cut_id(
                        f"{generated_cut_prefix}_targetface_i{iteration_id:03d}",
                        source_index,
                    ),
                    provenance=(
                        f"{model_name_prefix}_iteration_{iteration_id:03d}_"
                        f"target_face_source_{source_index:03d}"
                    ),
                    source_alpha=separation_alpha_value,
                    source_lambda_by_line_id=separation_lambda_by_line_id,
                    source_violation_value=source_solution.objective_value,
                    face_tolerance_rel=resolved_target_face_tolerance_rel,
                    max_cuts=remaining_target_face_cuts,
                    min_cut_violation=target_face_min_violation,
                    log_to_console=log_to_console,
                )
                batch_cut_results.extend(target_face_results)
                remaining_target_face_cuts -= len(target_face_results)
        if (
            bool(enable_cluster_face_bundle_cuts)
            and resolved_cluster_face_cuts_per_iteration > 0
            and batch_solutions
        ):
            cluster_candidates: list[tuple[str, ...]] = []
            for pattern in selected_active_patterns:
                if pattern not in cluster_candidates:
                    cluster_candidates.append(pattern)
            for pattern in active_outage_pool:
                if pattern not in cluster_candidates:
                    cluster_candidates.append(pattern)
                if len(cluster_candidates) >= resolved_cluster_face_candidate_limit:
                    break
            remaining_cluster_face_cuts = resolved_cluster_face_cuts_per_iteration
            cluster_face_min_violation = max(
                resolved_epsilon,
                resolved_cluster_face_add_violation_fraction
                * max(0.0, float(separation_solution.objective_value or 0.0)),
            )
            for source_index, source_solution in enumerate(batch_solutions, start=1):
                if remaining_cluster_face_cuts <= 0:
                    break
                source_pattern = _active_outage_lines(source_solution.delta_by_line_id)
                source_outage = build_fixed_outage_vector(
                    instance,
                    by_line_id=source_solution.delta_by_line_id,
                )
                target_outages = [
                    build_fixed_outage_vector(
                        instance,
                        by_line_id=_delta_by_line_id_from_active_lines(
                            instance.sets.line_ids,
                            pattern,
                        ),
                    )
                    for pattern in cluster_candidates
                    if pattern != source_pattern
                ][:resolved_cluster_face_candidate_limit]
                cluster_face_results = generate_cluster_face_bundle_cuts(
                    instance,
                    plan=plan,
                    source_outage=source_outage,
                    target_outages=target_outages,
                    scenario_ids=disaster_scenario_ids,
                    cut_id_prefix=_make_generated_cut_id(
                        f"{generated_cut_prefix}_clusterface_i{iteration_id:03d}",
                        source_index,
                    ),
                    provenance=(
                        f"{model_name_prefix}_iteration_{iteration_id:03d}_"
                        f"cluster_face_source_{source_index:03d}"
                    ),
                    source_alpha=separation_alpha_value,
                    source_lambda_by_line_id=separation_lambda_by_line_id,
                    source_violation_value=source_solution.objective_value,
                    face_tolerance_rel=resolved_cluster_face_tolerance_rel,
                    min_cut_violation=cluster_face_min_violation,
                    log_to_console=log_to_console,
                )
                batch_cut_results.extend(cluster_face_results)
                remaining_cluster_face_cuts -= len(cluster_face_results)
        if bool(enable_exact_outage_rows) and resolved_exact_row_max > 0:
            exact_candidates: list[tuple[str, ...]] = [
                _active_outage_lines(solution.delta_by_line_id)
                for solution in batch_solutions
            ]
            if bool(exact_rows_include_active):
                exact_candidates.extend(selected_active_patterns)
            exact_outage_patterns = _append_exact_outage_patterns(
                exact_outage_patterns,
                exact_candidates,
                max_size=resolved_exact_row_max,
                per_iteration=resolved_exact_rows_per_iteration,
            )
        cut_seconds = perf_counter() - cut_start

        current_cuts = list(master_problem.cuts)
        current_outage_column_cuts = list(master_problem.outage_column_cuts)
        repeated_cut_signature_flag = False
        added_cut_count = 0
        if bool(enable_nccg_outage_columns):
            if len(batch_cut_result_patterns) != len(batch_cut_results):
                raise RuntimeDataValidationError(
                    "NCCG row-wise mode requires one active outage pattern per generated cut."
                )
            for batch_cut_result, batch_pattern in zip(
                batch_cut_results,
                batch_cut_result_patterns,
            ):
                generated_cut_results.append(batch_cut_result)
                normalized_pattern = tuple(str(line_id) for line_id in batch_pattern)
                rowwise_key = (
                    normalized_pattern,
                    str(batch_cut_result.cut_signature_hash),
                )
                is_repeated = rowwise_key in seen_rowwise_cut_keys
                repeated_cut_signature_flag = repeated_cut_signature_flag or is_repeated
                if enable_cut_signature_dedup and is_repeated:
                    continue
                column_id = _outage_column_id(normalized_pattern)
                outage_column_source_violation_by_id[column_id] = max(
                    float(outage_column_source_violation_by_id.get(column_id, 0.0)),
                    float(batch_cut_result.old_master_cut_violation or 0.0),
                )
                row_id = (
                    f"nccg_{len(current_outage_column_cuts) + 1:06d}_"
                    f"{column_id}"
                )
                current_outage_column_cuts.append(
                    RestrictedMasterOutageColumnCut(
                        row_id=row_id,
                        column_id=column_id,
                        active_line_ids=normalized_pattern,
                        cut=batch_cut_result.cut,
                    )
                )
                if bool(nccg_keep_global_cuts):
                    if str(batch_cut_result.cut_signature_hash) not in seen_cut_signatures:
                        current_cuts.append(batch_cut_result.cut)
                        seen_cut_signatures.add(batch_cut_result.cut_signature_hash)
                seen_rowwise_cut_keys.add(rowwise_key)
                added_cut_count += 1
        else:
            for batch_cut_result in batch_cut_results:
                generated_cut_results.append(batch_cut_result)
                is_repeated = batch_cut_result.cut_signature_hash in seen_cut_signatures
                repeated_cut_signature_flag = repeated_cut_signature_flag or is_repeated
                if enable_cut_signature_dedup and is_repeated:
                    continue
                current_cuts.append(batch_cut_result.cut)
                added_cut_count += 1
                seen_cut_signatures.add(batch_cut_result.cut_signature_hash)

        cut_added = added_cut_count > 0
        stop_after_duplicate = False
        if not cut_added:
            cut_addition_status = (
                "repeated_outage_duplicate_cut"
                if enable_repeated_outage_guard and repeated_outage_flag
                else "duplicate_cut_signature"
            )
            stop_after_duplicate = True
            stop_reason = cut_addition_status
        else:
            if use_nonoptimal_incumbent_cut:
                cut_addition_status = (
                    batch_truncated_status
                    or f"added_nonoptimal_incumbent_batch_{added_cut_count}"
                )
            else:
                cut_addition_status = batch_truncated_status or f"added_batch_{added_cut_count}"

        record = BendersIterationRecord(
                iteration_id=iteration_id,
                pre_cut_master_objective=lower_bound_value,
                post_cut_master_objective=None,
                separation_violation_value=violation_value,
                candidate_source=candidate_source,
                canonical_master_objective=canonical_solution.objective_value,
                auxiliary_master_objective=auxiliary_objective,
                unpenalized_candidate_objective=candidate_unpenalized_objective,
                trust_region_z_radius=(
                    int(stabilization_z_radius)
                    if stabilization_z_radius is not None
                    else (2 if resolved_stabilization_mode is not None else None)
                ),
                trust_region_z_distance=trust_region_z_distance,
                active_delta_pool_size=(
                    len(active_outage_pool) if bool(enable_active_set_cuts) else None
                ),
                active_candidate_count=(
                    active_candidate_count if bool(enable_active_set_cuts) else None
                ),
                active_validated_cut_count=(
                    len(active_cut_results) if bool(enable_active_set_cuts) else None
                ),
                active_best_validated_violation=active_best_validated_violation,
                active_set_generation_seconds=float(active_set_seconds),
                full_support_separation_called=True,
                pricing_capture_count=int(pricing_capture_count),
                pricing_capture_best_violation=pricing_capture_best_violation,
                pricing_capture_seconds=float(pricing_capture_seconds),
                persistent_pricing_pool_size=(
                    len(
                        {
                            row.column_id
                            for row in current_outage_column_cuts
                        }
                    )
                    if bool(enable_nccg_outage_columns)
                    else None
                ),
                broadcast_candidate_count=int(broadcast_candidate_count),
                broadcast_added_count=int(broadcast_added_count),
                pricing_violation_bound=float(pricing_violation_upper_bound),
                pricing_derived_upper_bound=float(pricing_upper_bound),
                best_pricing_derived_upper_bound=(
                    None
                    if best_pricing_derived_upper_bound is None
                    else float(best_pricing_derived_upper_bound)
                ),
                certified_serious_step_type=certified_serious_step_type,
                certified_serious_null_count=int(certified_serious_null_count),
                valid_gap_bound=valid_gap_bound,
                selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                selected_outage_active_lines=selected_outage_active_lines,
                repeated_outage_flag=repeated_outage_flag,
                generated_cut_id=";".join(result.cut.cut_id for result in batch_cut_results),
                generated_cut_signature_hash=";".join(
                    result.cut_signature_hash for result in batch_cut_results
                ),
                repeated_cut_signature_flag=repeated_cut_signature_flag,
                active_cut_ids_before=active_cut_ids_before,
                active_cut_ids_after=(
                    tuple(cut.cut_id for cut in current_cuts)
                    + tuple(row.row_id for row in current_outage_column_cuts)
                ),
                total_cut_count_before=(
                    len(master_problem.cuts) + len(master_problem.outage_column_cuts)
                ),
                total_cut_count_after=len(current_cuts) + len(current_outage_column_cuts),
                generated_cut_old_master_violation=max(
                    result.old_master_cut_violation or 0.0
                    for result in batch_cut_results
                ),
                cut_added=cut_added,
                cut_addition_status=cut_addition_status,
                gamma_z_nonzero_count=sum(
                    result.gamma_z_nonzero_count for result in batch_cut_results
                ),
                gamma_n_sl_nonzero_count=sum(
                    result.gamma_n_sl_nonzero_count for result in batch_cut_results
                ),
                gamma_n_fa_nonzero_count=sum(
                    result.gamma_n_fa_nonzero_count for result in batch_cut_results
                ),
                phi_nonzero_count=sum(result.phi_nonzero_count for result in batch_cut_results),
                construction_cost_value=float(master_solution.construction_cost_value),
                first_stage_attached_objective_value=master_solution.first_stage_solution.objective_value,
                first_stage_objective_is_pure_construction=bool(
                    master_solution.first_stage_solution.objective_is_pure_construction
                ),
                master_solve_seconds=float(master_seconds),
                separation_solve_seconds=float(separation_seconds),
                separation_model_status=";".join(batch_statuses),
                separation_mip_gap=max(batch_gaps) if batch_gaps else None,
                separation_obj_bound=max(batch_bounds) if batch_bounds else None,
                separation_node_count=sum(batch_nodes) if batch_nodes else None,
                separation_max_omega_bound_violation=_max_omega_bound_violation(
                    batch_solutions
                ),
                separation_min_omega_upper_slack=_min_batch_omega_upper_slack(
                    batch_solutions
                ),
                separation_min_active_omega_upper_slack=(
                    _min_batch_active_omega_upper_slack(batch_solutions)
                ),
                separation_reconstruction_gap=_max_reconstruction_gap(batch_solutions),
                cut_generation_seconds=float(cut_seconds),
                stop_reason=stop_reason if stop_after_duplicate else None,
        )
        record = replace(
            record,
            valid_lb_used=lower_bound_value,
            auxiliary_used_for_lb=False,
            level_bundle_objective_upper_bound=level_bundle_bound_used,
            level_bundle_center_policy=(
                resolved_center_update_policy if bool(enable_level_bundle_trial) else None
            ),
        )
        iteration_records.append(record)
        _write_live_iteration(record, csv_path=live_csv_path, jsonl_path=live_jsonl_path)
        if (
            bool(enable_lambda_face_prox_trial)
            and "lambda_face_prox" in candidate_source
            and (
                best_lambda_face_trial_violation is None
                or violation_value < best_lambda_face_trial_violation
            )
        ):
            best_lambda_face_trial_violation = float(violation_value)
            lambda_face_center_alpha = float(separation_alpha_value)
            lambda_face_center_lambda_by_line_id = dict(separation_lambda_by_line_id)
        if (
            (resolved_stabilization_mode is not None or bool(enable_level_bundle_trial))
            and resolved_center_update_policy != "fixed"
        ):
            if bool(enable_certified_serious_step):
                serious_update = certified_serious_step_type in {
                    "ub_serious_initial",
                    "ub_serious",
                    "violation_serious",
                }
                if serious_update:
                    current_stabilization_center_plan = plan
                    current_stabilization_center_alpha = float(separation_alpha_value)
                    current_stabilization_center_lambda_by_line_id = dict(
                        separation_lambda_by_line_id
                    )
                    if (
                        best_stabilization_violation is None
                        or violation_value < best_stabilization_violation
                    ):
                        best_stabilization_violation = violation_value
            elif resolved_center_update_policy == "last_trial":
                current_stabilization_center_plan = plan
                current_stabilization_center_alpha = float(separation_alpha_value)
                current_stabilization_center_lambda_by_line_id = dict(
                    separation_lambda_by_line_id
                )
            elif (
                best_stabilization_violation is None
                or violation_value < best_stabilization_violation
            ):
                current_stabilization_center_plan = plan
                current_stabilization_center_alpha = float(separation_alpha_value)
                current_stabilization_center_lambda_by_line_id = dict(
                    separation_lambda_by_line_id
                )
                best_stabilization_violation = violation_value
        if stop_after_duplicate:
            break
        if _adaptive_stall_detected(
            [
                float(item.separation_violation_value)
                for item in iteration_records
                if item.separation_violation_value is not None
            ],
            window_iterations=int(adaptive_stall_window_iterations),
            min_relative_improvement=float(adaptive_stall_min_relative_improvement),
        ):
            stop_reason = (
                f"adaptive_stall_window_{int(adaptive_stall_window_iterations)}"
            )
            iteration_records[-1] = replace(
                iteration_records[-1],
                cut_addition_status=stop_reason,
                stop_reason=stop_reason,
            )
            _write_live_iteration(
                iteration_records[-1],
                csv_path=live_csv_path,
                jsonl_path=live_jsonl_path,
            )
            break
        pending_post_cut_record_index = len(iteration_records) - 1
        pending_pre_cut_solution = master_solution

    if final_master is None or final_solution is None or final_residual is None:
        raise RuntimeDataValidationError("Benders engine produced no master solve.")
    if final_separation_model is None or final_separation_solution is None:
        raise RuntimeDataValidationError("Benders engine produced no separation solve.")

    certificate = BendersCertificateSummary(
        epsilon_cert=float(resolved_epsilon),
        final_rmp_value=float(final_solution.objective_value or 0.0),
        final_violation_upper_bound=(
            max(0.0, float(final_separation_solution.obj_bound or 0.0))
            if stop_reason == "certified_epsilon_bound"
            else max(0.0, float(final_separation_solution.objective_value or 0.0))
        ),
        sampled_problem_gap_bound=float(instance.economics.pi_f * resolved_epsilon),
    )
    iteration_log_artifact = build_iteration_log_artifact(
        stop_reason=stop_reason,
        lower_bound_sequence=tuple(lower_bound_sequence),
        cut_count_sequence=tuple(cut_count_sequence),
        generated_cut_count=len(generated_cut_results),
        epsilon_cert=resolved_epsilon,
        certificate=certificate,
        iterations=tuple(iteration_records),
    )
    written_iteration_log_path = (
        write_iteration_log_artifact(iteration_log_artifact, iteration_log_path)
        if iteration_log_path is not None
        else None
    )

    return BendersEngineResult(
        stop_reason=stop_reason,
        epsilon_cert=resolved_epsilon,
        iterations=tuple(iteration_records),
        lower_bound_sequence=tuple(lower_bound_sequence),
        cut_count_sequence=tuple(cut_count_sequence),
        generated_cut_results=tuple(generated_cut_results),
        final_master=final_master,
        final_solution=final_solution,
        final_residual=final_residual,
        final_separation_model=final_separation_model,
        final_separation_solution=final_separation_solution,
        certificate=certificate,
        iteration_log_artifact=iteration_log_artifact,
        master_before_cut_lp_path=dumped_before_path,
        master_after_cut_lp_path=dumped_after_path,
        iteration_log_path=written_iteration_log_path,
        trial_certificate=trial_certificate,
    )
