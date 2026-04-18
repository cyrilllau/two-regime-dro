"""Edge-case validation for the budget-support outage oracle."""

from __future__ import annotations

import pytest

from src.reference.outage_enumerator import (
    solve_budget_support_by_enumeration,
    solve_budget_support_top_k,
)


def test_budget_support_k_zero_forces_all_zero_outage() -> None:
    """When `K = 0`, the support value should be zero with the all-zero outage pattern."""

    line_ids = ("l1", "l2", "l3")
    score_by_line_id = {"l1": 4.0, "l2": 1.0, "l3": -3.0}

    enumeration = solve_budget_support_by_enumeration(
        line_ids,
        budget_k=0,
        score_by_line_id=score_by_line_id,
    )
    top_k = solve_budget_support_top_k(
        line_ids,
        budget_k=0,
        score_by_line_id=score_by_line_id,
    )

    assert enumeration.objective_value == pytest.approx(0.0)
    assert top_k.objective_value == pytest.approx(0.0)
    assert enumeration.selected_pattern.values == (0, 0, 0)
    assert top_k.selected_pattern.values == (0, 0, 0)


def test_budget_support_full_budget_equals_sum_of_positive_scores() -> None:
    """When `K = |L|`, the support value should equal the sum of positive components."""

    line_ids = ("l1", "l2", "l3", "l4")
    score_by_line_id = {"l1": 4.0, "l2": -1.0, "l3": 3.0, "l4": 0.0}

    enumeration = solve_budget_support_by_enumeration(
        line_ids,
        budget_k=len(line_ids),
        score_by_line_id=score_by_line_id,
    )
    top_k = solve_budget_support_top_k(
        line_ids,
        budget_k=len(line_ids),
        score_by_line_id=score_by_line_id,
    )

    assert enumeration.objective_value == pytest.approx(7.0)
    assert top_k.objective_value == pytest.approx(7.0)


def test_budget_support_nonpositive_scores_choose_zero_vector() -> None:
    """If every component is nonpositive, the best outage should still be all-zero."""

    line_ids = ("l1", "l2", "l3")
    score_by_line_id = {"l1": -2.0, "l2": -1.0, "l3": 0.0}

    enumeration = solve_budget_support_by_enumeration(
        line_ids,
        budget_k=2,
        score_by_line_id=score_by_line_id,
    )
    top_k = solve_budget_support_top_k(
        line_ids,
        budget_k=2,
        score_by_line_id=score_by_line_id,
    )

    assert enumeration.objective_value == pytest.approx(0.0)
    assert top_k.objective_value == pytest.approx(0.0)
    assert enumeration.selected_pattern.values == (0, 0, 0)
    assert top_k.selected_pattern.values == (0, 0, 0)


def test_budget_support_tie_case_checks_value_without_requiring_unique_identity() -> None:
    """Tie cases should match in objective value even when multiple outages are optimal."""

    line_ids = ("l1", "l2", "l3")
    score_by_line_id = {"l1": 5.0, "l2": 5.0, "l3": -1.0}
    optimal_patterns = {(1, 0, 0), (0, 1, 0)}

    enumeration = solve_budget_support_by_enumeration(
        line_ids,
        budget_k=1,
        score_by_line_id=score_by_line_id,
    )
    top_k = solve_budget_support_top_k(
        line_ids,
        budget_k=1,
        score_by_line_id=score_by_line_id,
    )

    assert enumeration.objective_value == pytest.approx(5.0)
    assert top_k.objective_value == pytest.approx(5.0)
    assert enumeration.selected_pattern.values in optimal_patterns
    assert top_k.selected_pattern.values in optimal_patterns
