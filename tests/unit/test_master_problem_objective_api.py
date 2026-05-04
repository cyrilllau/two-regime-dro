"""Objective-API regressions for the Round 07.5 restricted master problem."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.audit.residual_report import build_master_problem_residual_report
from src.instance.schema import ObjectiveMultipliers
from src.production.master_problem import solve_master_problem
from tests.oracle.test_master_problem_toy_cases import build_round_07_toy_case


def test_master_problem_uses_pure_construction_value_in_objective_decomposition() -> None:
    """The master summary must use pure construction cost, not the attached first-stage objective."""

    instance, cuts, _ = build_round_07_toy_case("master_problem_normal_averaging.yaml")
    master_problem, solution = solve_master_problem(
        instance,
        cuts=cuts,
        model_name="round_07_5_master_objective_api",
    )
    residual = build_master_problem_residual_report(master_problem, solution)

    assert solution.model_status == "OPTIMAL"
    assert solution.first_stage_solution.objective_is_pure_construction is False
    assert solution.first_stage_solution.objective_value == pytest.approx(solution.objective_value)
    assert (
        solution.first_stage_solution.objective_value
        > solution.first_stage_solution.construction_cost_value
    )

    assert residual.first_stage_objective_is_pure_construction is False
    assert residual.first_stage_attached_objective_value == pytest.approx(solution.objective_value)
    assert residual.construction_cost_value == pytest.approx(
        solution.first_stage_solution.construction_cost_value
    )
    assert residual.construction_cost_value == pytest.approx(0.04)
    assert (
        residual.construction_cost_value
        + residual.averaged_normal_cost_value
        + residual.disaster_master_cost_value
    ) == pytest.approx(solution.objective_value)
    assert residual.objective_reconstruction_gap <= 1e-8


def test_objective_multipliers_leave_reported_master_components_raw() -> None:
    """Component fields should stay raw while the optimized objective is scaled."""

    instance, cuts, _ = build_round_07_toy_case("master_problem_normal_averaging.yaml")
    instance = replace(
        instance,
        economics=replace(
            instance.economics,
            objective_multipliers=ObjectiveMultipliers(
                cons=2.0,
                normal=3.0,
                disaster=5.0,
            ),
        ),
    )
    _, solution = solve_master_problem(
        instance,
        cuts=cuts,
        model_name="round_07_5_master_objective_multipliers",
    )

    raw_sum = (
        solution.construction_cost_value
        + solution.averaged_normal_cost_value
        + solution.disaster_master_cost_value
    )
    scaled_sum = (
        2.0 * solution.construction_cost_value
        + 3.0 * solution.averaged_normal_cost_value
        + 5.0 * solution.disaster_master_cost_value
    )

    assert solution.model_status == "OPTIMAL"
    assert solution.objective_value == pytest.approx(scaled_sum)
    assert solution.objective_value != pytest.approx(raw_sum)
    assert solution.objective_reconstruction_gap <= 1e-8
