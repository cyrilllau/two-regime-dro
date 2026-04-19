"""Structured audit artifacts for generated master cuts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from src.production.disaster_dual_paper import SamplewisePaperDualDecomposition
from src.production.master_problem import RestrictedMasterCut
from src.reference.disaster_primal_ref import FixedFirstStagePlan, FixedOutageVector


@dataclass(frozen=True)
class GeneratedCutAuditRecord:
    """Stable audit record for one generated structured master cut."""

    cut_id: str
    provenance: str
    simplex_method: int
    source_plan: FixedFirstStagePlan
    source_outage: FixedOutageVector
    source_alpha: float | None
    source_lambda_by_line_id: dict[str, float] = field(default_factory=dict)
    source_violation_value: float | None = None
    cut_signature_hash: str = ""
    gamma_z_nonzero_count: int = 0
    gamma_n_sl_nonzero_count: int = 0
    gamma_n_fa_nonzero_count: int = 0
    phi_nonzero_count: int = 0
    samplewise_decompositions_by_scenario: dict[int, SamplewisePaperDualDecomposition] = field(
        default_factory=dict
    )
    samplewise_objective_by_scenario: dict[int, float] = field(default_factory=dict)
    aggregated_cut: RestrictedMasterCut | None = None


def build_cut_audit_record(
    *,
    cut_id: str,
    provenance: str,
    simplex_method: int,
    source_plan: FixedFirstStagePlan,
    source_outage: FixedOutageVector,
    source_alpha: float | None,
    source_lambda_by_line_id: Mapping[str, float] | None,
    source_violation_value: float | None,
    cut_signature_hash: str,
    gamma_z_nonzero_count: int,
    gamma_n_sl_nonzero_count: int,
    gamma_n_fa_nonzero_count: int,
    phi_nonzero_count: int,
    samplewise_decompositions_by_scenario: Mapping[int, SamplewisePaperDualDecomposition],
    samplewise_objective_by_scenario: Mapping[int, float],
    aggregated_cut: RestrictedMasterCut,
) -> GeneratedCutAuditRecord:
    """Build the stable audit artifact required for one generated cut."""

    return GeneratedCutAuditRecord(
        cut_id=str(cut_id),
        provenance=str(provenance),
        simplex_method=int(simplex_method),
        source_plan=source_plan,
        source_outage=source_outage,
        source_alpha=None if source_alpha is None else float(source_alpha),
        source_lambda_by_line_id={
            str(line_id): float(value)
            for line_id, value in (source_lambda_by_line_id or {}).items()
        },
        source_violation_value=(
            None if source_violation_value is None else float(source_violation_value)
        ),
        cut_signature_hash=str(cut_signature_hash),
        gamma_z_nonzero_count=int(gamma_z_nonzero_count),
        gamma_n_sl_nonzero_count=int(gamma_n_sl_nonzero_count),
        gamma_n_fa_nonzero_count=int(gamma_n_fa_nonzero_count),
        phi_nonzero_count=int(phi_nonzero_count),
        samplewise_decompositions_by_scenario={
            int(scenario_id): decomposition
            for scenario_id, decomposition in samplewise_decompositions_by_scenario.items()
        },
        samplewise_objective_by_scenario={
            int(scenario_id): float(value)
            for scenario_id, value in samplewise_objective_by_scenario.items()
        },
        aggregated_cut=aggregated_cut,
    )
