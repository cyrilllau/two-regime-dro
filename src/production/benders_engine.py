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


def _copy_iteration_record(
    record: BendersIterationRecord,
    *,
    post_cut_master_objective: float | None,
) -> BendersIterationRecord:
    return BendersIterationRecord(
        iteration_id=record.iteration_id,
        pre_cut_master_objective=record.pre_cut_master_objective,
        post_cut_master_objective=post_cut_master_objective,
        separation_violation_value=record.separation_violation_value,
        selected_outage_by_line_id=dict(record.selected_outage_by_line_id),
        generated_cut_id=record.generated_cut_id,
        active_cut_ids_before=tuple(record.active_cut_ids_before),
        active_cut_ids_after=tuple(record.active_cut_ids_after),
        total_cut_count_before=record.total_cut_count_before,
        total_cut_count_after=record.total_cut_count_after,
        generated_cut_old_master_violation=record.generated_cut_old_master_violation,
        construction_cost_value=record.construction_cost_value,
        first_stage_attached_objective_value=record.first_stage_attached_objective_value,
        first_stage_objective_is_pure_construction=record.first_stage_objective_is_pure_construction,
        master_solve_seconds=record.master_solve_seconds,
        separation_solve_seconds=record.separation_solve_seconds,
        cut_generation_seconds=record.cut_generation_seconds,
        stop_reason=record.stop_reason,
    )


def run_benders_engine(
    instance: CanonicalInstance,
    *,
    cuts: Sequence[RestrictedMasterCut] | None = None,
    normal_scenario_ids: Sequence[int] | None = None,
    disaster_scenario_ids: Sequence[int] | None = None,
    omega_bounds_by_line_id: dict[str, tuple[float, float]] | None = None,
    omega_bound_safety_factor: float = 2.0,
    epsilon_cert: float = 0.0,
    max_iterations: int = 25,
    generated_cut_prefix: str = "generated_cut",
    model_name_prefix: str = "round_09_benders",
    master_before_cut_lp_path: str | Path | None = None,
    master_after_cut_lp_path: str | Path | None = None,
    iteration_log_path: str | Path | None = None,
    log_to_console: bool = False,
) -> BendersEngineResult:
    """Run the full iterative Benders-like engine."""

    resolved_max_iterations = _resolve_positive_int("max_iterations", max_iterations)
    resolved_epsilon = _resolve_nonnegative_float("epsilon_cert", epsilon_cert)
    current_cuts = list(cuts or [])
    generated_cut_results: list[GeneratedCutResult] = []
    iteration_records: list[BendersIterationRecord] = []
    lower_bound_sequence: list[float] = []
    cut_count_sequence: list[int] = []
    pending_post_cut_record_index: int | None = None
    baseline_cut_count: int | None = None
    dumped_before_path: Path | None = None
    dumped_after_path: Path | None = None

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
            model_name=f"{model_name_prefix}_master_{iteration_id:03d}",
            log_to_console=log_to_console,
        )
        master_seconds = perf_counter() - master_start
        master_residual = build_master_problem_residual_report(master_problem, master_solution)

        if baseline_cut_count is None:
            baseline_cut_count = len(master_problem.cuts)
        if pending_post_cut_record_index is not None:
            iteration_records[pending_post_cut_record_index] = _copy_iteration_record(
                iteration_records[pending_post_cut_record_index],
                post_cut_master_objective=float(master_solution.objective_value or 0.0),
            )
            pending_post_cut_record_index = None
        if dumped_before_path is None and master_before_cut_lp_path is not None:
            dumped_before_path = dump_model_artifact(master_problem, master_before_cut_lp_path)
        if (
            dumped_after_path is None
            and master_after_cut_lp_path is not None
            and len(master_problem.cuts) > baseline_cut_count
        ):
            dumped_after_path = dump_model_artifact(master_problem, master_after_cut_lp_path)

        plan = _plan_from_solution(instance, master_solution)
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
            log_to_console=log_to_console,
        )
        separation_seconds = perf_counter() - separation_start

        lower_bound_value = float(master_solution.objective_value or 0.0)
        violation_value = max(0.0, float(separation_solution.objective_value or 0.0))
        active_cut_ids_before = tuple(cut.cut_id for cut in master_problem.cuts)

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
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=len(master_problem.cuts),
                    total_cut_count_after=len(master_problem.cuts),
                    generated_cut_old_master_violation=None,
                    construction_cost_value=float(master_solution.construction_cost_value),
                    first_stage_attached_objective_value=master_solution.first_stage_solution.objective_value,
                    first_stage_objective_is_pure_construction=bool(
                        master_solution.first_stage_solution.objective_is_pure_construction
                    ),
                    master_solve_seconds=float(master_seconds),
                    separation_solve_seconds=float(separation_seconds),
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
                    generated_cut_id=None,
                    active_cut_ids_before=active_cut_ids_before,
                    active_cut_ids_after=active_cut_ids_before,
                    total_cut_count_before=len(master_problem.cuts),
                    total_cut_count_after=len(master_problem.cuts),
                    generated_cut_old_master_violation=None,
                    construction_cost_value=float(master_solution.construction_cost_value),
                    first_stage_attached_objective_value=master_solution.first_stage_solution.objective_value,
                    first_stage_objective_is_pure_construction=bool(
                        master_solution.first_stage_solution.objective_is_pure_construction
                    ),
                    master_solve_seconds=float(master_seconds),
                    separation_solve_seconds=float(separation_seconds),
                    cut_generation_seconds=0.0,
                    stop_reason=stop_reason,
                )
            )
            break

        cut_start = perf_counter()
        generated_cut_result = generate_cut_from_separation_solution(
            instance,
            plan=plan,
            separation_solution=separation_solution,
            scenario_ids=disaster_scenario_ids,
            cut_id=_make_generated_cut_id(
                generated_cut_prefix,
                len(generated_cut_results) + 1,
            ),
            provenance=f"{model_name_prefix}_iteration_{iteration_id:03d}",
            lambda_by_line_id=master_solution.lambda_by_line_id,
            log_to_console=log_to_console,
        )
        cut_seconds = perf_counter() - cut_start
        generated_cut_results.append(generated_cut_result)
        current_cuts = list(master_problem.cuts) + [generated_cut_result.cut]

        iteration_records.append(
            BendersIterationRecord(
                iteration_id=iteration_id,
                pre_cut_master_objective=lower_bound_value,
                post_cut_master_objective=None,
                separation_violation_value=violation_value,
                selected_outage_by_line_id=dict(separation_solution.delta_by_line_id),
                generated_cut_id=generated_cut_result.cut.cut_id,
                active_cut_ids_before=active_cut_ids_before,
                active_cut_ids_after=tuple(cut.cut_id for cut in current_cuts),
                total_cut_count_before=len(master_problem.cuts),
                total_cut_count_after=len(current_cuts),
                generated_cut_old_master_violation=generated_cut_result.old_master_cut_violation,
                construction_cost_value=float(master_solution.construction_cost_value),
                first_stage_attached_objective_value=master_solution.first_stage_solution.objective_value,
                first_stage_objective_is_pure_construction=bool(
                    master_solution.first_stage_solution.objective_is_pure_construction
                ),
                master_solve_seconds=float(master_seconds),
                separation_solve_seconds=float(separation_seconds),
                cut_generation_seconds=float(cut_seconds),
                stop_reason=None,
            )
        )
        pending_post_cut_record_index = len(iteration_records) - 1

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
