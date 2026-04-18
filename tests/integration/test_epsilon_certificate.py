"""Round 09 epsilon-certificate regression checks."""

from __future__ import annotations

import pytest

from src.production.benders_engine import run_benders_engine
from tests.oracle.test_cut_factory import build_round_08_case


def test_positive_epsilon_stops_no_later_and_reports_gap_bound() -> None:
    """A positive epsilon certificate should stop no later than the exact path."""

    instance, _, _, _, raw = build_round_08_case("benders_two_cut_unique_plan.yaml")
    expected = raw["expected_benders"]
    epsilon_cert = float(expected["epsilon_cert"])

    exact_result = run_benders_engine(
        instance,
        epsilon_cert=0.0,
        max_iterations=10,
        model_name_prefix="round_09_exact_cert",
    )
    epsilon_result = run_benders_engine(
        instance,
        epsilon_cert=epsilon_cert,
        max_iterations=10,
        model_name_prefix="round_09_epsilon_cert",
    )

    assert exact_result.stop_reason == expected["stop_reason_exact"]
    assert epsilon_result.stop_reason == expected["stop_reason_epsilon"]
    assert len(epsilon_result.iterations) <= len(exact_result.iterations)
    assert epsilon_result.certificate.epsilon_cert == pytest.approx(epsilon_cert)
    assert epsilon_result.certificate.final_rmp_value == pytest.approx(
        epsilon_result.final_solution.objective_value
    )
    assert epsilon_result.certificate.final_violation_upper_bound == pytest.approx(epsilon_cert)
    assert epsilon_result.certificate.sampled_problem_gap_bound == pytest.approx(
        float(expected["epsilon_gap_bound"])
    )
    assert epsilon_result.lower_bound_sequence == pytest.approx((10.0,))
    assert epsilon_result.cut_count_sequence == (1,)
    assert len(epsilon_result.generated_cut_results) == 0
    assert epsilon_result.final_solution.first_stage_solution.z_by_bus == {1: 0, 2: 0, 3: 0}
    assert epsilon_result.final_solution.first_stage_solution.n_sl_by_bus == {1: 0, 2: 0, 3: 0}
    assert epsilon_result.final_solution.first_stage_solution.n_fa_by_bus == {1: 0, 2: 0, 3: 0}
