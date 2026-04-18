"""Single-iteration integration checks for the Round 08 cut-addition path."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.production.cut_factory import run_single_iteration_cut_addition
from tests.oracle.test_cut_factory import build_round_08_case


def test_generated_cut_efficacy_on_tiny_case() -> None:
    """One real generated cut should violate the old point and tighten the tiny master."""

    instance, initial_cuts, _, _, raw = build_round_08_case(
        "cut_factory_generated_efficacy.yaml"
    )
    result = run_single_iteration_cut_addition(
        instance,
        cuts=initial_cuts,
        model_name_prefix="round_08_tiny_efficacy",
        cut_id="tiny_generated_cut",
    )
    before_dump = dump_model_artifact(
        result.pre_master,
        Path("/tmp/round_08_tiny_master_before_cut.lp"),
    )
    after_dump = dump_model_artifact(
        result.post_master,
        Path("/tmp/round_08_tiny_master_after_cut.lp"),
    )

    expected = raw["expected_single_iteration"]
    assert before_dump.exists()
    assert after_dump.exists()
    assert result.generated_cut_result is not None
    assert result.pre_solution.objective_value == pytest.approx(
        float(expected["pre_objective"])
    )
    assert result.post_solution.objective_value == pytest.approx(
        float(expected["post_objective"])
    )
    assert result.generated_cut_result.old_master_cut_violation is not None
    assert result.generated_cut_result.old_master_cut_violation > 1e-6
    assert result.generated_cut_result.cut.is_trivial() is False
    assert result.post_solution.objective_value > result.pre_solution.objective_value + 1e-8
    assert result.post_residual.max_cut_support_violation <= 1e-8
    assert result.post_residual.max_u_link_violation <= 1e-8
    assert result.post_residual.cut_support_slacks["tiny_generated_cut"] == pytest.approx(0.0)


def test_multi_cut_carryover_keeps_per_cut_indexing_after_generated_addition() -> None:
    """Existing cuts and the generated cut should coexist with distinct indexed auxiliaries."""

    instance, initial_cuts, _, _, raw = build_round_08_case(
        "cut_factory_multi_cut_carryover.yaml"
    )
    result = run_single_iteration_cut_addition(
        instance,
        cuts=initial_cuts,
        model_name_prefix="round_08_multi_cut",
        cut_id="generated_real_cut",
    )

    expected = raw["expected_single_iteration"]
    assert result.generated_cut_result is not None
    assert result.pre_master.cuts[0].cut_id == "gamma_site"
    assert tuple(cut.cut_id for cut in result.post_master.cuts) == (
        "gamma_site",
        "generated_real_cut",
    )
    assert result.pre_solution.objective_value == pytest.approx(float(expected["pre_objective"]))
    assert result.post_solution.objective_value == pytest.approx(
        float(expected["post_objective"])
    )
    assert set(result.post_solution.s_by_cut_id) == {"gamma_site", "generated_real_cut"}
    assert ("gamma_site", "line_01_02") in result.post_solution.u_by_cut_id_and_line_id
    assert ("generated_real_cut", "line_01_02") in result.post_solution.u_by_cut_id_and_line_id
    assert result.post_residual.max_cut_support_violation <= 1e-8
    assert result.post_residual.max_u_link_violation <= 1e-8
    assert result.post_residual.cut_support_slacks["gamma_site"] == pytest.approx(0.0)
    assert result.post_residual.cut_support_slacks["generated_real_cut"] == pytest.approx(0.0)


def test_master_objective_boundary_regression_holds_after_cut_addition() -> None:
    """The post-cut master should still reconstruct with pure construction cost only."""

    instance, initial_cuts, _, _, _ = build_round_08_case(
        "cut_factory_multi_cut_carryover.yaml"
    )
    result = run_single_iteration_cut_addition(
        instance,
        cuts=initial_cuts,
        model_name_prefix="round_08_objective_boundary",
        cut_id="generated_real_cut",
    )

    assert result.generated_cut_result is not None
    assert result.post_solution.first_stage_solution.objective_is_pure_construction is False
    assert result.post_solution.first_stage_solution.objective_value == pytest.approx(
        result.post_solution.objective_value
    )
    assert result.post_solution.first_stage_solution.objective_value != pytest.approx(
        result.post_solution.construction_cost_value
    )
    assert result.post_residual.construction_cost_value == pytest.approx(
        result.post_solution.construction_cost_value
    )
    assert result.post_solution.objective_reconstruction_gap <= 1e-8
