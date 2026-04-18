"""Regression checks for the Round 06 first-stage solution API."""

from __future__ import annotations

import pytest

from src.production.first_stage import build_first_stage_model, extract_first_stage_solution
from src.production.normal_block import (
    build_normal_operation_block,
    extract_normal_operation_solution,
)
from tests.oracle.test_first_stage_normal_toy_cases import build_round_06_toy_case


def test_standalone_first_stage_objective_matches_construction_cost() -> None:
    """A standalone first-stage solve should report the pure construction value as the model objective."""

    instance, _, _ = build_round_06_toy_case("first_stage_t2_minimum_three.yaml")
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_5_first_stage_standalone",
        attach_objective=True,
    )
    first_stage.model.addConstr(first_stage.z_by_bus[2] == 1.0, name="force_site_open_n2")
    first_stage.model.optimize()
    solution = extract_first_stage_solution(first_stage)

    assert solution.model_status == "OPTIMAL"
    assert solution.objective_is_pure_construction is True
    assert solution.objective_value == pytest.approx(solution.construction_cost_value)
    assert solution.construction_cost_value == pytest.approx(35.0)


def test_attached_first_stage_solution_keeps_pure_construction_value_separate() -> None:
    """When attached to the normal block, the first-stage API must still expose pure construction cost."""

    instance, scenario_id, _ = build_round_06_toy_case(
        "normal_block_t4_distance_preference.yaml"
    )
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_5_first_stage_attached",
        attach_objective=True,
    )
    normal_block = build_normal_operation_block(
        instance,
        first_stage=first_stage,
        scenario_id=scenario_id,
        attach_objective=True,
    )
    normal_block.model.optimize()
    first_stage_solution = extract_first_stage_solution(first_stage)
    normal_solution = extract_normal_operation_solution(normal_block)

    assert normal_solution.model_status == "OPTIMAL"
    assert first_stage_solution.objective_is_pure_construction is False
    assert first_stage_solution.construction_cost_value == pytest.approx(6.0)
    assert first_stage_solution.objective_value == pytest.approx(normal_solution.objective_value)
    assert first_stage_solution.objective_value > first_stage_solution.construction_cost_value
