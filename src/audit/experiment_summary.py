"""Structured summaries for the Round 11 experiment pack."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ExperimentRunSummary:
    """One auditable experiment-pack summary row."""

    run_id: str
    family_name: str
    case_name: str
    parameter_regime: str
    validation_level: str
    stop_reason: str
    total_objective: float
    construction_cost: float
    weighted_normal_term: float
    unweighted_normal_term: float
    disaster_master_term: float
    alpha: float
    lambda_times_FP: float
    iteration_count: int
    cut_count: int
    final_violation_upper_bound: float
    opened_bus_count: int
    total_slow_chargers: int
    total_fast_chargers: int

    def to_csv_row(self) -> dict[str, Any]:
        """Return a CSV-ready row dictionary."""

        return asdict(self)
