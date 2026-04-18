"""Tiny-case outage enumeration and separation-validation oracles."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Mapping, Sequence

from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import RuntimeDataValidationError
from src.production.disaster_dual_paper import (
    FixedFirstStagePlanLike,
    SamplewisePaperDualDecomposition,
    solve_disaster_dual_paper,
)


@dataclass(frozen=True)
class EnumeratedOutagePattern:
    """Stable outage pattern on a canonical ordered line set."""

    line_ids: tuple[str, ...]
    values: tuple[int, ...]
    by_line_id: dict[str, int] = field(default_factory=dict)
    active_line_ids: tuple[str, ...] = field(default_factory=tuple)
    label: str = ""


@dataclass(frozen=True)
class BudgetSupportResult:
    """Result for `max_{delta in Omega(K)} v^T delta`."""

    objective_value: float
    selected_pattern: EnumeratedOutagePattern
    selected_line_ids: tuple[str, ...]
    score_by_line_id: dict[str, float] = field(default_factory=dict)
    evaluation_path: str = ""


@dataclass(frozen=True)
class SeparationEnumerationResult:
    """Exact outage-enumeration oracle for the fixed-point separation problem."""

    objective_value: float
    best_pattern: EnumeratedOutagePattern
    evaluated_patterns: tuple[EnumeratedOutagePattern, ...]
    objective_by_pattern: dict[str, float] = field(default_factory=dict)
    samplewise_decomposition_by_pattern: dict[str, dict[int, SamplewisePaperDualDecomposition]] = field(
        default_factory=dict
    )
    average_phi_by_pattern: dict[str, dict[str, float]] = field(default_factory=dict)
    samplewise_objective_by_pattern: dict[str, dict[int, float]] = field(default_factory=dict)


def _stable_pattern_label(values: Sequence[int]) -> str:
    return "delta_" + "".join(str(int(value)) for value in values)


def _make_pattern(line_ids: Sequence[str], values: Sequence[int]) -> EnumeratedOutagePattern:
    line_tuple = tuple(str(line_id) for line_id in line_ids)
    value_tuple = tuple(int(value) for value in values)
    by_line_id = {line_id: value_tuple[index] for index, line_id in enumerate(line_tuple)}
    active_line_ids = tuple(
        line_id for line_id, value in zip(line_tuple, value_tuple) if value == 1
    )
    return EnumeratedOutagePattern(
        line_ids=line_tuple,
        values=value_tuple,
        by_line_id=by_line_id,
        active_line_ids=active_line_ids,
        label=_stable_pattern_label(value_tuple),
    )


def _normalize_score_by_line_id(
    line_ids: Sequence[str],
    score_by_line_id: Mapping[str, float],
) -> dict[str, float]:
    normalized = {line_id: 0.0 for line_id in line_ids}
    invalid = sorted(line_id for line_id in score_by_line_id if line_id not in normalized)
    if invalid:
        raise RuntimeDataValidationError(
            f"score_by_line_id contains invalid line ids: {tuple(invalid)}."
        )
    for line_id, value in score_by_line_id.items():
        normalized[line_id] = float(value)
    return normalized


def _normalize_lambda_by_line_id(
    line_ids: Sequence[str],
    lambda_by_line_id: Mapping[str, float] | None,
) -> dict[str, float]:
    normalized = {line_id: 0.0 for line_id in line_ids}
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


def enumerate_outages(
    line_ids: Sequence[str],
    *,
    budget_k: int,
) -> tuple[EnumeratedOutagePattern, ...]:
    """Enumerate `Omega(K)` in stable lexicographic order."""

    line_tuple = tuple(str(line_id) for line_id in line_ids)
    if budget_k < 0:
        raise RuntimeDataValidationError(f"budget_k must be nonnegative, got {budget_k}.")
    if budget_k > len(line_tuple):
        raise RuntimeDataValidationError(
            f"budget_k {budget_k} exceeds the line count {len(line_tuple)}."
        )

    patterns: list[EnumeratedOutagePattern] = []
    for outage_count in range(budget_k + 1):
        for active_indices in combinations(range(len(line_tuple)), outage_count):
            values = [0] * len(line_tuple)
            for index in active_indices:
                values[index] = 1
            patterns.append(_make_pattern(line_tuple, values))
    return tuple(patterns)


def evaluate_outage_pattern(
    pattern: EnumeratedOutagePattern,
    *,
    score_by_line_id: Mapping[str, float],
) -> float:
    """Evaluate `v^T delta` for a stable enumerated outage pattern."""

    normalized_scores = _normalize_score_by_line_id(pattern.line_ids, score_by_line_id)
    return float(
        sum(
            normalized_scores[line_id] * pattern.by_line_id[line_id]
            for line_id in pattern.line_ids
        )
    )


def solve_budget_support_by_enumeration(
    line_ids: Sequence[str],
    *,
    budget_k: int,
    score_by_line_id: Mapping[str, float],
) -> BudgetSupportResult:
    """Exact enumeration oracle for the budget-support function."""

    patterns = enumerate_outages(line_ids, budget_k=budget_k)
    normalized_scores = _normalize_score_by_line_id(line_ids, score_by_line_id)
    best_pattern = patterns[0]
    best_value = evaluate_outage_pattern(best_pattern, score_by_line_id=normalized_scores)
    for pattern in patterns[1:]:
        value = evaluate_outage_pattern(pattern, score_by_line_id=normalized_scores)
        if value > best_value + 1e-12:
            best_pattern = pattern
            best_value = value
    return BudgetSupportResult(
        objective_value=float(best_value),
        selected_pattern=best_pattern,
        selected_line_ids=best_pattern.active_line_ids,
        score_by_line_id=normalized_scores,
        evaluation_path="enumeration",
    )


def solve_budget_support_top_k(
    line_ids: Sequence[str],
    *,
    budget_k: int,
    score_by_line_id: Mapping[str, float],
) -> BudgetSupportResult:
    """Closed-form top-positive equivalent for the budget-support function."""

    line_tuple = tuple(str(line_id) for line_id in line_ids)
    normalized_scores = _normalize_score_by_line_id(line_tuple, score_by_line_id)
    ranked = sorted(
        line_tuple,
        key=lambda line_id: (-normalized_scores[line_id], line_tuple.index(line_id)),
    )
    chosen = [
        line_id
        for line_id in ranked[:budget_k]
        if normalized_scores[line_id] > 1e-12
    ]
    pattern = _make_pattern(
        line_tuple,
        [1 if line_id in chosen else 0 for line_id in line_tuple],
    )
    return BudgetSupportResult(
        objective_value=float(sum(normalized_scores[line_id] for line_id in chosen)),
        selected_pattern=pattern,
        selected_line_ids=tuple(chosen),
        score_by_line_id=normalized_scores,
        evaluation_path="top_k_positive",
    )


def solve_separation_violation_by_enumeration(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlanLike,
    alpha: float,
    lambda_by_line_id: Mapping[str, float] | None,
    budget_k: int,
    scenario_ids: Sequence[int] | None = None,
) -> SeparationEnumerationResult:
    """Exact tiny-case separation oracle by outage enumeration + paper-dual re-solves."""

    line_ids = instance.sets.line_ids
    normalized_lambda = _normalize_lambda_by_line_id(line_ids, lambda_by_line_id)
    selected_scenarios = tuple(
        int(scenario_id)
        for scenario_id in (
            scenario_ids
            if scenario_ids is not None
            else instance.sets.loaded_disaster_scenarios
        )
    )
    if not selected_scenarios:
        raise RuntimeDataValidationError("At least one disaster scenario is required.")

    patterns = enumerate_outages(line_ids, budget_k=budget_k)
    objective_by_pattern: dict[str, float] = {}
    decomposition_by_pattern: dict[str, dict[int, SamplewisePaperDualDecomposition]] = {}
    average_phi_by_pattern: dict[str, dict[str, float]] = {}
    samplewise_objective_by_pattern: dict[str, dict[int, float]] = {}

    best_pattern = patterns[0]
    best_value = float("-inf")

    for pattern in patterns:
        sample_decompositions: dict[int, SamplewisePaperDualDecomposition] = {}
        sample_objectives: dict[int, float] = {}
        for scenario_id in selected_scenarios:
            _, solution = solve_disaster_dual_paper(
                instance,
                plan=plan,
                outage=pattern,
                scenario_id=scenario_id,
                model_name=f"enumeration_paper_dual_b{scenario_id}_{pattern.label}",
            )
            sample_decompositions[scenario_id] = solution.samplewise_decomposition
            sample_objectives[scenario_id] = float(solution.objective_value or 0.0)

        average_value = sum(sample_objectives.values()) / len(selected_scenarios)
        value = average_value - sum(
            normalized_lambda[line_id] * pattern.by_line_id[line_id]
            for line_id in line_ids
        ) - float(alpha)
        objective_by_pattern[pattern.label] = float(value)
        decomposition_by_pattern[pattern.label] = sample_decompositions
        samplewise_objective_by_pattern[pattern.label] = sample_objectives
        average_phi_by_pattern[pattern.label] = {
            line_id: float(
                sum(
                    sample_decompositions[scenario_id].phi_by_line_id[line_id]
                    for scenario_id in selected_scenarios
                )
                / len(selected_scenarios)
            )
            for line_id in line_ids
        }
        if value > best_value + 1e-12:
            best_value = float(value)
            best_pattern = pattern

    return SeparationEnumerationResult(
        objective_value=float(best_value),
        best_pattern=best_pattern,
        evaluated_patterns=patterns,
        objective_by_pattern=objective_by_pattern,
        samplewise_decomposition_by_pattern=decomposition_by_pattern,
        average_phi_by_pattern=average_phi_by_pattern,
        samplewise_objective_by_pattern=samplewise_objective_by_pattern,
    )


def derive_single_line_omega_bounds(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlanLike,
    budget_k: int,
    scenario_ids: Sequence[int] | None = None,
    safety_factor: float = 1.0,
) -> dict[str, tuple[float, float]]:
    """Derive conservative per-line omega bounds from single-line outage re-solves."""

    if safety_factor < 1.0:
        raise RuntimeDataValidationError(
            f"safety_factor must be at least 1.0, got {safety_factor}."
        )

    line_ids = instance.sets.line_ids
    selected_scenarios = tuple(
        int(scenario_id)
        for scenario_id in (
            scenario_ids
            if scenario_ids is not None
            else instance.sets.loaded_disaster_scenarios
        )
    )
    if not selected_scenarios:
        raise RuntimeDataValidationError("At least one disaster scenario is required.")

    bounds: dict[str, tuple[float, float]] = {}
    for line_id in line_ids:
        pattern = _make_pattern(
            line_ids,
            [1 if current_line_id == line_id else 0 for current_line_id in line_ids],
        )
        average_phi = 0.0
        for scenario_id in selected_scenarios:
            _, solution = solve_disaster_dual_paper(
                instance,
                plan=plan,
                outage=pattern,
                scenario_id=scenario_id,
                model_name=f"omega_bound_paper_dual_{line_id}_b{scenario_id}",
            )
            average_phi += solution.samplewise_decomposition.phi_by_line_id[line_id]
        average_phi /= len(selected_scenarios)
        upper = float(max(0.0, average_phi) * max(1, budget_k) * safety_factor)
        bounds[line_id] = (0.0, upper)
    return bounds


def derive_omega_bounds_from_enumeration(
    enumeration_result: SeparationEnumerationResult,
) -> dict[str, tuple[float, float]]:
    """Extract exact linewise omega maxima from an outage-enumeration sweep."""

    line_ids = enumeration_result.best_pattern.line_ids
    bounds: dict[str, tuple[float, float]] = {}
    for line_id in line_ids:
        upper = max(
            average_phi[line_id]
            for average_phi in enumeration_result.average_phi_by_pattern.values()
        )
        bounds[line_id] = (0.0, float(max(0.0, upper)))
    return bounds
