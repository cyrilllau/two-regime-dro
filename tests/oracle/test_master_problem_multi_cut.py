"""Multi-cut envelope and indexing checks for the Round 07.5 restricted master problem."""

from __future__ import annotations

import pytest

from src.audit.residual_report import build_master_problem_residual_report
from src.production.master_problem import build_master_problem, solve_master_problem
from tests.oracle.test_master_problem_toy_cases import build_round_07_toy_case


def test_multi_cut_master_keeps_cut_and_line_indices_separate() -> None:
    """Each cut should receive its own support row, `s_r`, and linewise `u_{r,l}` family."""

    instance, cuts, _ = build_round_07_toy_case(
        "master_problem_multi_cut_two_line_envelope.yaml"
    )
    master_problem = build_master_problem(
        instance,
        cuts=cuts,
        model_name="round_07_5_multi_cut_indexing",
    )

    assert tuple(cut.cut_id for cut in master_problem.cuts) == ("gamma_site", "phi_support")
    assert set(master_problem.s_by_cut_id) == {"gamma_site", "phi_support"}
    assert master_problem.s_by_cut_id["gamma_site"] is not master_problem.s_by_cut_id["phi_support"]

    for cut_id in ("gamma_site", "phi_support"):
        assert cut_id in master_problem.cut_support_constraints
        for line_id in instance.sets.line_ids:
            assert (cut_id, line_id) in master_problem.u_by_cut_id_and_line_id
            assert (cut_id, line_id) in master_problem.u_link_constraints

    assert master_problem.u_by_cut_id_and_line_id[("gamma_site", "line_01_02")] is not (
        master_problem.u_by_cut_id_and_line_id[("phi_support", "line_01_02")]
    )
    assert master_problem.u_by_cut_id_and_line_id[("phi_support", "line_01_02")] is not (
        master_problem.u_by_cut_id_and_line_id[("phi_support", "line_02_03")]
    )


def test_multi_cut_master_envelope_handles_two_cuts_simultaneously() -> None:
    """The solved RMP should enforce the multi-cut envelope without index sharing."""

    instance, cuts, raw = build_round_07_toy_case(
        "master_problem_multi_cut_two_line_envelope.yaml"
    )
    master_problem, solution = solve_master_problem(
        instance,
        cuts=cuts,
        model_name="round_07_5_multi_cut_envelope",
    )
    residual = build_master_problem_residual_report(master_problem, solution)
    expected = raw["expected"]

    assert solution.model_status == "OPTIMAL"
    assert solution.objective_value == pytest.approx(float(expected["objective"]))
    assert solution.first_stage_solution.z_by_bus[2] == int(expected["z2"])
    assert solution.first_stage_solution.n_sl_by_bus[2] == int(expected["n_sl2"])
    assert solution.alpha_value == pytest.approx(float(expected["alpha"]))
    assert solution.lambda_by_line_id["line_01_02"] == pytest.approx(
        float(expected["lambda_line_01_02"])
    )
    assert residual.cut_support_slacks["gamma_site"] == pytest.approx(0.0)
    assert residual.cut_support_slacks["phi_support"] == pytest.approx(0.0)
    assert residual.active_cut_ids == ("gamma_site", "phi_support")
    assert residual.active_nontrivial_cut_ids == ("gamma_site", "phi_support")
    assert residual.max_cut_support_violation <= 1e-8
    assert residual.max_u_link_violation <= 1e-8
