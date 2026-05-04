"""Full iterative production Benders engine for the sampled mainline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Sequence

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
    compute_cut_signature_hash,
    generate_cut_from_separation_solution,
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
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan
from src.reference.disaster_primal_ref import FixedFirstStagePlan
from src.reference.outage_enumerator import derive_single_line_omega_bounds


CERTIFICATION_TOLERANCE = 1e-8


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


def _make_generated_cut_id(prefix: str, index: int) -> str:
    return f"{prefix}_{index:03d}"


def _active_outage_lines(delta_by_line_id: dict[str, int]) -> tuple[str, ...]:
    return tuple(sorted(line_id for line_id, value in delta_by_line_id.items() if int(value) == 1))


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
    separation_time_limit_seconds: float | None = None,
    separation_mip_gap: float | None = None,
    allow_master_suboptimal_incumbent: bool = False,
    epsilon_cert: float = 0.0,
    max_iterations: int = 25,
    separation_top_cuts_per_iteration: int = 1,
    enable_cut_signature_dedup: bool = False,
    enable_repeated_outage_guard: bool = False,
    generated_cut_prefix: str = "generated_cut",
    model_name_prefix: str = "round_09_benders",
    master_before_cut_lp_path: str | Path | None = None,
    master_after_cut_lp_path: str | Path | None = None,
    iteration_log_path: str | Path | None = None,
    log_to_console: bool = False,
) -> BendersEngineResult:
    """Run the full iterative Benders-like engine."""

    resolved_max_iterations = _resolve_positive_int("max_iterations", max_iterations)
    resolved_top_cuts = _resolve_positive_int(
        "separation_top_cuts_per_iteration",
        separation_top_cuts_per_iteration,
    )
    resolved_epsilon = _resolve_nonnegative_float("epsilon_cert", epsilon_cert)
    current_cuts = list(cuts or [])
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
    current_warm_start_plan = warm_start_plan

    final_master: RestrictedMasterProblem | None = None
    final_solution: RestrictedMasterProblemSolution | None = None
    final_residual: RestrictedMasterProblemResidualReport | None = None
    final_separation_model: SeparationMilpModel | None = None
    final_separation_solution: SeparationMilpSolution | None = None
    stop_reason = "max_iterations"

    for iteration_id in range(resolved_max_iterations):
        master_start = perf_counter()
        master_problem, master_solution = solve_master_problem(
            instance,
            cuts=current_cuts,
            normal_scenario_ids=normal_scenario_ids,
            warm_start_plan=current_warm_start_plan,
            time_limit_seconds=master_time_limit_seconds,
            mip_gap=master_mip_gap,
            allow_suboptimal_incumbent=allow_master_suboptimal_incumbent,
            model_name=f"{model_name_prefix}_master_{iteration_id:03d}",
            log_to_console=log_to_console,
        )
        master_seconds = perf_counter() - master_start
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

        plan = _plan_from_solution(instance, master_solution)
        current_warm_start_plan = plan
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

        separation_start = perf_counter()
        separation_model, separation_solution = solve_separation_milp(
            instance,
            plan=plan,
            alpha=master_solution.alpha_value,
            lambda_by_line_id=master_solution.lambda_by_line_id,
            omega_bounds_by_line_id=resolved_omega_bounds,
            budget_k=int(instance.ambiguity.k_max_outages),
            scenario_ids=disaster_scenario_ids,
            model_name=f"{model_name_prefix}_separation_{iteration_id:03d}",
            time_limit_seconds=separation_time_limit_seconds,
            mip_gap=separation_mip_gap,
            require_optimal=False,
            log_to_console=log_to_console,
        )
        separation_seconds = perf_counter() - separation_start
        if separation_solution.model_status != "OPTIMAL":
            lower_bound_value = float(master_solution.objective_value or 0.0)
            violation_value = max(0.0, float(separation_solution.objective_value or 0.0))
            active_cut_ids_before = tuple(cut.cut_id for cut in master_problem.cuts)
            selected_outage_active_lines = _active_outage_lines(
                separation_solution.delta_by_line_id
            )
            repeated_outage_flag = selected_outage_active_lines in seen_outage_patterns
            seen_outage_patterns.add(selected_outage_active_lines)

            final_master = master_problem
            final_solution = master_solution
            final_residual = master_residual
            final_separation_model = separation_model
            final_separation_solution = separation_solution
            lower_bound_sequence.append(lower_bound_value)
            cut_count_sequence.append(len(master_problem.cuts))
            stop_reason = f"separation_{separation_solution.model_status.lower()}"
            iteration_records.append(
                BendersIterationRecord(
                    iteration_id=iteration_id,
                    pre_cut_master_objective=lower_bound_value,
                    post_cut_master_objective=None,
                    separation_violation_value=violation_value,
                    selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                    selected_outage_active_lines=selected_outage_active_lines,
                    repeated_outage_flag=repeated_outage_flag,
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=len(master_problem.cuts),
                    total_cut_count_after=len(master_problem.cuts),
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
            )
            break

        lower_bound_value = float(master_solution.objective_value or 0.0)
        violation_value = max(0.0, float(separation_solution.objective_value or 0.0))
        active_cut_ids_before = tuple(cut.cut_id for cut in master_problem.cuts)
        selected_outage_active_lines = _active_outage_lines(separation_solution.delta_by_line_id)
        repeated_outage_flag = selected_outage_active_lines in seen_outage_patterns
        seen_outage_patterns.add(selected_outage_active_lines)

        final_master = master_problem
        final_solution = master_solution
        final_residual = master_residual
        final_separation_model = separation_model
        final_separation_solution = separation_solution

        lower_bound_sequence.append(lower_bound_value)
        cut_count_sequence.append(len(master_problem.cuts))

        if violation_value <= resolved_epsilon + CERTIFICATION_TOLERANCE:
            stop_reason = (
                "certified_exact"
                if resolved_epsilon <= CERTIFICATION_TOLERANCE
                else "certified_epsilon"
            )
            iteration_records.append(
                BendersIterationRecord(
                    iteration_id=iteration_id,
                    pre_cut_master_objective=lower_bound_value,
                    post_cut_master_objective=None,
                    separation_violation_value=violation_value,
                    selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                    selected_outage_active_lines=selected_outage_active_lines,
                    repeated_outage_flag=repeated_outage_flag,
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=len(master_problem.cuts),
                    total_cut_count_after=len(master_problem.cuts),
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
            )
            break

        if iteration_id == resolved_max_iterations - 1:
            stop_reason = "max_iterations"
            iteration_records.append(
                BendersIterationRecord(
                    iteration_id=iteration_id,
                    pre_cut_master_objective=lower_bound_value,
                    post_cut_master_objective=None,
                    separation_violation_value=violation_value,
                    selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                    selected_outage_active_lines=selected_outage_active_lines,
                    repeated_outage_flag=repeated_outage_flag,
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=len(master_problem.cuts),
                    total_cut_count_after=len(master_problem.cuts),
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
            )
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

        for batch_index in range(1, resolved_top_cuts):
            extra_start = perf_counter()
            _, extra_solution = solve_separation_milp(
                instance,
                plan=plan,
                alpha=master_solution.alpha_value,
                lambda_by_line_id=master_solution.lambda_by_line_id,
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

        cut_start = perf_counter()
        batch_cut_results: list[GeneratedCutResult] = []
        for batch_index, batch_solution in enumerate(batch_solutions):
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
                lambda_by_line_id=master_solution.lambda_by_line_id,
                log_to_console=log_to_console,
            )
            batch_cut_results.append(batch_cut_result)
        cut_seconds = perf_counter() - cut_start

        current_cuts = list(master_problem.cuts)
        repeated_cut_signature_flag = False
        added_cut_count = 0
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
            cut_addition_status = batch_truncated_status or f"added_batch_{added_cut_count}"

        iteration_records.append(
            BendersIterationRecord(
                iteration_id=iteration_id,
                pre_cut_master_objective=lower_bound_value,
                post_cut_master_objective=None,
                separation_violation_value=violation_value,
                selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                selected_outage_active_lines=selected_outage_active_lines,
                repeated_outage_flag=repeated_outage_flag,
                generated_cut_id=";".join(result.cut.cut_id for result in batch_cut_results),
                generated_cut_signature_hash=";".join(
                    result.cut_signature_hash for result in batch_cut_results
                ),
                repeated_cut_signature_flag=repeated_cut_signature_flag,
                active_cut_ids_before=active_cut_ids_before,
                active_cut_ids_after=tuple(cut.cut_id for cut in current_cuts),
                total_cut_count_before=len(master_problem.cuts),
                total_cut_count_after=len(current_cuts),
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
        )
        if stop_after_duplicate:
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
        final_violation_upper_bound=max(
            0.0,
            float(final_separation_solution.objective_value or 0.0),
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
    )
