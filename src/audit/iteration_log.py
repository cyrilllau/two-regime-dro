"""Structured iteration-level evidence for the production Benders engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BendersIterationRecord:
    """One auditable Benders iteration record."""

    iteration_id: int
    pre_cut_master_objective: float
    post_cut_master_objective: float | None
    separation_violation_value: float
    candidate_source: str = "canonical"
    canonical_master_objective: float | None = None
    auxiliary_master_objective: float | None = None
    unpenalized_candidate_objective: float | None = None
    valid_lb_used: float | None = None
    auxiliary_used_for_lb: bool = False
    level_bundle_objective_upper_bound: float | None = None
    level_bundle_center_policy: str | None = None
    trust_region_z_radius: int | None = None
    trust_region_z_distance: int | None = None
    active_delta_pool_size: int | None = None
    active_candidate_count: int | None = None
    active_validated_cut_count: int | None = None
    active_best_validated_violation: float | None = None
    active_set_generation_seconds: float = 0.0
    full_support_separation_called: bool = True
    pricing_capture_count: int = 0
    pricing_capture_best_violation: float | None = None
    pricing_capture_seconds: float = 0.0
    persistent_pricing_pool_size: int | None = None
    broadcast_candidate_count: int = 0
    broadcast_added_count: int = 0
    pricing_violation_bound: float | None = None
    pricing_derived_upper_bound: float | None = None
    best_pricing_derived_upper_bound: float | None = None
    certified_serious_step_type: str | None = None
    certified_serious_null_count: int = 0
    valid_gap_bound: float | None = None
    selected_outage_by_line_id: dict[str, int] = field(default_factory=dict)
    selected_outage_active_lines: tuple[str, ...] = field(default_factory=tuple)
    repeated_outage_flag: bool = False
    generated_cut_id: str | None = None
    generated_cut_signature_hash: str | None = None
    repeated_cut_signature_flag: bool = False
    active_cut_ids_before: tuple[str, ...] = field(default_factory=tuple)
    active_cut_ids_after: tuple[str, ...] = field(default_factory=tuple)
    total_cut_count_before: int = 0
    total_cut_count_after: int = 0
    generated_cut_old_master_violation: float | None = None
    post_cut_master_objective_change: float | None = None
    first_stage_plan_changed: bool | None = None
    alpha_lambda_only_change: bool | None = None
    cut_added: bool = False
    cut_addition_status: str | None = None
    gamma_z_nonzero_count: int | None = None
    gamma_n_sl_nonzero_count: int | None = None
    gamma_n_fa_nonzero_count: int | None = None
    phi_nonzero_count: int | None = None
    construction_cost_value: float = 0.0
    first_stage_attached_objective_value: float | None = None
    first_stage_objective_is_pure_construction: bool = False
    master_solve_seconds: float = 0.0
    separation_solve_seconds: float = 0.0
    separation_model_status: str | None = None
    separation_mip_gap: float | None = None
    separation_obj_bound: float | None = None
    separation_node_count: float | None = None
    separation_max_omega_bound_violation: float | None = None
    separation_min_omega_upper_slack: float | None = None
    separation_min_active_omega_upper_slack: float | None = None
    separation_reconstruction_gap: float | None = None
    cut_generation_seconds: float = 0.0
    stop_reason: str | None = None


@dataclass(frozen=True)
class BendersCertificateSummary:
    """Explicit exact/epsilon certificate summary."""

    epsilon_cert: float
    final_rmp_value: float
    final_violation_upper_bound: float
    sampled_problem_gap_bound: float


@dataclass(frozen=True)
class BendersIterationLogArtifact:
    """Stable serialized artifact for one Benders run."""

    stop_reason: str
    iteration_count: int
    lower_bound_sequence: tuple[float, ...]
    cut_count_sequence: tuple[int, ...]
    generated_cut_count: int
    epsilon_cert: float
    certificate: BendersCertificateSummary
    iterations: tuple[BendersIterationRecord, ...]


def build_iteration_log_artifact(
    *,
    stop_reason: str,
    lower_bound_sequence: tuple[float, ...],
    cut_count_sequence: tuple[int, ...],
    generated_cut_count: int,
    epsilon_cert: float,
    certificate: BendersCertificateSummary,
    iterations: tuple[BendersIterationRecord, ...],
) -> BendersIterationLogArtifact:
    """Build the stable iteration-log artifact for one Benders run."""

    return BendersIterationLogArtifact(
        stop_reason=str(stop_reason),
        iteration_count=len(iterations),
        lower_bound_sequence=tuple(float(value) for value in lower_bound_sequence),
        cut_count_sequence=tuple(int(value) for value in cut_count_sequence),
        generated_cut_count=int(generated_cut_count),
        epsilon_cert=float(epsilon_cert),
        certificate=certificate,
        iterations=iterations,
    )


def write_iteration_log_artifact(
    artifact: BendersIterationLogArtifact,
    path: str | Path,
) -> Path:
    """Write one Benders iteration log artifact as stable JSON."""

    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(asdict(artifact), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return artifact_path


def iteration_log_to_dict(artifact: BendersIterationLogArtifact) -> dict[str, Any]:
    """Return the JSON-ready dictionary form of an iteration-log artifact."""

    return asdict(artifact)
