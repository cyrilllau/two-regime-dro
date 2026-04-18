"""Oracle tests for the budget-support function over outage patterns."""

from __future__ import annotations

from src.reference.outage_enumerator import (
    enumerate_outages,
    solve_budget_support_by_enumeration,
    solve_budget_support_top_k,
)


def test_enumeration_and_top_k_budget_support_agree_on_mixed_sign_scores() -> None:
    """Enumeration and the closed-form top-positive rule should agree."""

    line_ids = ("line_a", "line_b", "line_c")
    score_by_line_id = {
        "line_a": 4.0,
        "line_b": -1.0,
        "line_c": 3.0,
    }
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

    assert enumeration.objective_value == 7.0
    assert top_k.objective_value == 7.0
    assert enumeration.selected_pattern.values == (1, 0, 1)
    assert top_k.selected_pattern.values == (1, 0, 1)


def test_outage_enumerator_lists_budgeted_patterns_in_stable_order() -> None:
    """`Omega(K)` should enumerate in a stable combination order."""

    patterns = enumerate_outages(("l1", "l2", "l3"), budget_k=2)

    assert len(patterns) == 7
    assert [pattern.label for pattern in patterns] == [
        "delta_000",
        "delta_100",
        "delta_010",
        "delta_001",
        "delta_110",
        "delta_101",
        "delta_011",
    ]
