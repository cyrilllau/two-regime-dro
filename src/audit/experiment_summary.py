"""Structured summaries for the Round 12 experiment pack."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


def _csv_ready(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert optional values into stable CSV-ready scalars."""

    return {key: ("" if value is None else value) for key, value in payload.items()}


@dataclass(frozen=True)
class ExperimentRunSummary:
    """One auditable experiment-pack summary row."""

    run_id: str
    family_name: str
    case_name: str
    parameter_regime: str
    validation_level: str
    stop_reason: str
    solver_status: str
    total_objective: float | None
    construction_cost: float | None
    weighted_normal_term: float | None
    unweighted_normal_term: float | None
    disaster_master_term: float | None
    alpha: float | None
    lambda_times_FP: float | None
    iteration_count: int
    cut_count: int
    final_violation_upper_bound: float | None
    opened_bus_count: int | None
    total_slow_chargers: int | None
    total_fast_chargers: int | None

    def to_csv_row(self) -> dict[str, Any]:
        """Return a CSV-ready row dictionary."""

        return _csv_ready(asdict(self))


@dataclass(frozen=True)
class ExperimentFailureSummary:
    """Explicit failure/non-convergence row for auditable packaging."""

    run_id: str
    case_name: str
    parameter_regime: str
    validation_level: str
    stop_reason: str
    solver_status: str
    iteration_count: int
    cut_count: int
    final_violation_upper_bound: float | None
    message: str

    def to_csv_row(self) -> dict[str, Any]:
        """Return a CSV-ready failure row dictionary."""

        return _csv_ready(asdict(self))


@dataclass(frozen=True)
class ConvergenceDiagnosticSummary:
    """One auditable convergence-diagnostic summary row."""

    run_id: str
    case_name: str
    parameter_regime: str
    validation_level: str
    diagnosis_label: str
    stop_reason: str
    solver_status: str
    epsilon_cert: float
    max_iterations: int
    A_selected: str
    B_selected: str
    K: int
    iteration_count: int
    cut_count: int
    final_violation_upper_bound: float | None
    sampled_problem_gap_bound: float | None
    total_objective: float | None
    construction_cost: float | None
    weighted_normal_term: float | None
    disaster_master_term: float | None
    final_alpha: float | None
    final_lambda_times_FP: float | None
    total_runtime_sec: float
    master_runtime_sec_total: float
    separation_runtime_sec_total: float
    dual_resolve_runtime_sec_total: float
    generated_cut_count: int
    selected_outage_trace: str
    lower_bound_sequence: str
    violation_sequence: str
    cut_efficacy_sequence: str
    repeated_outage_flag: bool
    repeated_cut_signature_flag: bool
    notes: str

    def to_csv_row(self) -> dict[str, Any]:
        """Return a CSV-ready row dictionary."""

        return _csv_ready(asdict(self))


@dataclass(frozen=True)
class ConvergenceDiagnosticFailureSummary:
    """Explicit failure/non-convergence row for convergence diagnostics."""

    run_id: str
    case_name: str
    parameter_regime: str
    validation_level: str
    diagnosis_label: str
    stop_reason: str
    solver_status: str
    epsilon_cert: float
    max_iterations: int
    A_selected: str
    B_selected: str
    K: int
    iteration_count: int
    cut_count: int
    final_violation_upper_bound: float | None
    sampled_problem_gap_bound: float | None
    total_runtime_sec: float
    message: str

    def to_csv_row(self) -> dict[str, Any]:
        """Return a CSV-ready row dictionary."""

        return _csv_ready(asdict(self))


@dataclass(frozen=True)
class CutProcessDiagnosticSummary:
    """One auditable Round 13 cut-process summary row."""

    comparison_group: str
    variant: str
    run_id: str
    case_name: str
    parameter_regime: str
    validation_level: str
    diagnosis_label: str
    stop_reason: str
    solver_status: str
    epsilon_cert: float
    max_iterations: int
    A_selected: str
    B_selected: str
    K: int
    cut_signature_dedup_enabled: bool
    repeated_outage_guard_enabled: bool
    iteration_count: int
    cut_count: int
    generated_cut_count: int
    final_violation_upper_bound: float | None
    sampled_problem_gap_bound: float | None
    total_objective: float | None
    construction_cost: float | None
    weighted_normal_term: float | None
    disaster_master_term: float | None
    total_runtime_sec: float
    master_runtime_sec_total: float
    separation_runtime_sec_total: float
    dual_resolve_runtime_sec_total: float
    repeated_outage_count: int
    repeated_cut_signature_count: int
    alpha_lambda_only_cut_count: int
    plan_change_cut_count: int
    lower_bound_gain: float | None
    dominant_cause: str
    notes: str
    iteration_log_path: str | None
    master_before_cut_lp_path: str | None
    master_after_cut_lp_path: str | None

    def to_csv_row(self) -> dict[str, Any]:
        return _csv_ready(asdict(self))


@dataclass(frozen=True)
class CutProcessDiagnosticFailureSummary:
    """Explicit failure/non-certification row for Round 13 diagnostics."""

    comparison_group: str
    variant: str
    run_id: str
    case_name: str
    parameter_regime: str
    validation_level: str
    diagnosis_label: str
    stop_reason: str
    solver_status: str
    epsilon_cert: float
    max_iterations: int
    A_selected: str
    B_selected: str
    K: int
    iteration_count: int
    cut_count: int
    generated_cut_count: int
    final_violation_upper_bound: float | None
    sampled_problem_gap_bound: float | None
    total_runtime_sec: float
    dominant_cause: str
    message: str

    def to_csv_row(self) -> dict[str, Any]:
        return _csv_ready(asdict(self))


@dataclass(frozen=True)
class CutProcessDiagnosticCutRow:
    """Per-generated-cut diagnostic row for Round 13."""

    comparison_group: str
    variant: str
    run_id: str
    case_name: str
    parameter_regime: str
    iteration_id: int
    cut_id: str
    source_outage_vector: str
    source_outage_active_lines: str
    repeated_outage_flag: bool
    cut_signature_hash: str
    repeated_cut_signature_flag: bool
    old_master_violation_at_source: float | None
    post_cut_objective_change: float | None
    first_stage_plan_changed: bool | None
    alpha_lambda_only_change: bool | None
    gamma_z_nonzero_count: int | None
    gamma_n_sl_nonzero_count: int | None
    gamma_n_fa_nonzero_count: int | None
    phi_nonzero_count: int | None
    cut_added: bool
    cut_addition_status: str | None

    def to_csv_row(self) -> dict[str, Any]:
        return _csv_ready(asdict(self))
