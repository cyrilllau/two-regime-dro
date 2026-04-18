"""Round 09 end-to-end Benders vs brute-force tiny regression."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.production.benders_engine import run_benders_engine
from src.reference.brute_force_stage1 import (
    build_bounded_candidate,
    solve_bounded_first_stage_bruteforce,
)
from tests.oracle.test_cut_factory import build_round_08_case


def _build_bounded_candidates(instance, raw):
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


def test_benders_matches_bounded_bruteforce_on_tiny_case() -> None:
    """The full iterative engine should agree with the tiny brute-force oracle."""

    instance, _, _, _, raw = build_round_08_case("benders_two_cut_unique_plan.yaml")
    expected = raw["expected_benders"]
    candidates = _build_bounded_candidates(instance, raw)

    result = run_benders_engine(
        instance,
        epsilon_cert=0.0,
        max_iterations=10,
        model_name_prefix="round_09_tiny_exact",
        master_before_cut_lp_path=Path("/tmp/round_09_tiny_master_before_cut.lp"),
        master_after_cut_lp_path=Path("/tmp/round_09_tiny_master_after_cut.lp"),
        iteration_log_path=Path("/tmp/round_09_tiny_iteration_log.json"),
    )
    oracle = solve_bounded_first_stage_bruteforce(
        instance,
        candidates=candidates,
    )

    assert result.stop_reason == expected["stop_reason_exact"]
    assert result.master_before_cut_lp_path is not None
    assert result.master_before_cut_lp_path.exists()
    assert result.master_after_cut_lp_path is not None
    assert result.master_after_cut_lp_path.exists()
    assert result.iteration_log_path is not None
    assert result.iteration_log_path.exists()
    assert result.final_solution.objective_value == pytest.approx(float(expected["objective"]))
    assert result.final_solution.objective_value == pytest.approx(
        oracle.best_plan_evaluation.total_objective_value
    )
    assert oracle.best_plan_evaluation.plan_id == expected["best_plan_id"]
    assert result.final_solution.first_stage_solution.z_by_bus == {1: 0, 2: 0, 3: 1}
    assert result.final_solution.first_stage_solution.n_sl_by_bus == {1: 0, 2: 0, 3: 10}
    assert result.final_solution.first_stage_solution.n_fa_by_bus == {1: 0, 2: 0, 3: 0}
    assert result.certificate.final_violation_upper_bound <= 1e-8
    assert result.certificate.sampled_problem_gap_bound == pytest.approx(0.0)


def test_benders_lower_bound_and_cut_bookkeeping_stay_monotone() -> None:
    """The tiny run should accumulate two real cuts with stable indexing."""

    instance, _, _, _, raw = build_round_08_case("benders_two_cut_unique_plan.yaml")
    expected = raw["expected_benders"]

    result = run_benders_engine(
        instance,
        epsilon_cert=0.0,
        max_iterations=10,
        model_name_prefix="round_09_tiny_bookkeeping",
    )

    assert result.lower_bound_sequence == pytest.approx(
        tuple(float(value) for value in expected["lower_bound_sequence"])
    )
    assert result.cut_count_sequence == tuple(
        int(value) for value in expected["cut_count_sequence"]
    )
    assert result.lower_bound_sequence == tuple(sorted(result.lower_bound_sequence))
    assert result.cut_count_sequence == tuple(sorted(result.cut_count_sequence))
    assert len(result.generated_cut_results) == int(expected["generated_cut_count"])
    assert tuple(cut.cut.cut_id for cut in result.generated_cut_results) == (
        expected["first_generated_cut_id"],
        expected["second_generated_cut_id"],
    )
    assert tuple(cut.cut_id for cut in result.final_master.cuts) == (
        "trivial_cut",
        expected["first_generated_cut_id"],
        expected["second_generated_cut_id"],
    )
    assert set(result.final_solution.s_by_cut_id) == {
        "trivial_cut",
        expected["first_generated_cut_id"],
        expected["second_generated_cut_id"],
    }
    assert (
        expected["first_generated_cut_id"],
        "line_01_02",
    ) in result.final_solution.u_by_cut_id_and_line_id
    assert (
        expected["second_generated_cut_id"],
        "line_02_03",
    ) in result.final_solution.u_by_cut_id_and_line_id
    assert result.final_residual.max_cut_support_violation <= 1e-8
    assert result.final_residual.max_u_link_violation <= 1e-8
    assert result.final_solution.first_stage_solution.objective_is_pure_construction is False
    assert result.final_solution.first_stage_solution.objective_value == pytest.approx(
        result.final_solution.objective_value
    )
    assert result.final_solution.construction_cost_value == pytest.approx(70.0)
    assert result.final_solution.first_stage_solution.objective_value != pytest.approx(
        result.final_solution.construction_cost_value
    )
    for index, record in enumerate(result.iterations):
        if record.generated_cut_id is not None:
            assert record.generated_cut_id in record.active_cut_ids_after
            assert record.total_cut_count_after == record.total_cut_count_before + 1
            if index + 1 < len(result.iterations):
                assert record.generated_cut_id in result.iterations[index + 1].active_cut_ids_before
