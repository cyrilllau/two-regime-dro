"""Round 10 tiny cross-check between production and independent exact paths."""

from __future__ import annotations

import pytest

from src.production.benders_engine import run_benders_engine
from src.reference.brute_force_stage1 import (
    build_bounded_candidate,
    solve_bounded_first_stage_bruteforce,
)
from tests.oracle.test_cut_factory import build_round_08_case


def _build_candidates(instance, raw):
    return tuple(
        build_bounded_candidate(
            instance,
            plan_id=str(plan_raw["plan_id"]),
            z_by_bus={int(bus): int(value) for bus, value in plan_raw["z_by_bus"].items()},
            n_sl_by_bus={
                int(bus): int(value) for bus, value in plan_raw["n_sl_by_bus"].items()
            },
            n_fa_by_bus={
                int(bus): int(value) for bus, value in plan_raw["n_fa_by_bus"].items()
            },
        )
        for plan_raw in raw["enumerated_plans"]
    )


def test_independent_primal_disaster_exact_path_matches_current_tiny_production_path() -> None:
    """Tiny end-to-end optimum should agree across production and primal-exact paths."""

    instance, _, _, _, raw = build_round_08_case("disaster_exact_crosscheck_three_bus.yaml")
    expected = raw["expected_crosscheck"]
    candidates = _build_candidates(instance, raw)

    benders_result = run_benders_engine(
        instance,
        epsilon_cert=0.0,
        max_iterations=10,
        model_name_prefix="round_10_crosscheck_benders",
    )
    paper_dual_oracle = solve_bounded_first_stage_bruteforce(
        instance,
        candidates=candidates,
        disaster_value_mode="paper_dual",
    )
    primal_exact_oracle = solve_bounded_first_stage_bruteforce(
        instance,
        candidates=candidates,
        disaster_value_mode="primal_exact",
    )

    assert benders_result.stop_reason == "certified_exact"
    assert benders_result.final_solution.objective_value == pytest.approx(
        float(expected["optimal_objective"])
    )
    assert benders_result.final_solution.objective_value == pytest.approx(
        paper_dual_oracle.best_plan_evaluation.total_objective_value
    )
    assert benders_result.final_solution.objective_value == pytest.approx(
        primal_exact_oracle.best_plan_evaluation.total_objective_value
    )
    assert paper_dual_oracle.best_plan_evaluation.plan_id == expected["best_plan_id"]
    assert primal_exact_oracle.best_plan_evaluation.plan_id == expected["best_plan_id"]
