"""Real-cut interface checks for the Round 07.5 restricted master problem."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import build_master_problem_residual_report
from src.production.disaster_dual_paper import solve_disaster_dual_paper
from src.production.master_problem import (
    RestrictedMasterCut,
    build_master_problem,
    extract_master_problem_solution,
)
from tests.oracle.test_disaster_primal_ref import _build_case


def test_master_problem_consumes_real_cut_from_validated_paper_dual_without_index_drift() -> None:
    """A nontrivial real cut from the validated disaster-dual chain should map directly into the RMP."""

    base_instance, plan, outage, scenario_id, _ = _build_case("disaster_primal_shortage.yaml")
    instance = replace(
        base_instance,
        runtime_parameters={"net": {"Vmin": 0.9, "Vmax": 1.1}},
        metadata={"fixture_name": "round_07_5_real_cut_shortage"},
    )
    _, paper_solution = solve_disaster_dual_paper(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name="round_07_5_real_cut_source",
    )
    cut = RestrictedMasterCut.from_samplewise_decomposition(
        instance,
        paper_solution.samplewise_decomposition,
        cut_id="real_cut_shortage",
    )

    assert cut.is_trivial() is False
    assert cut.gamma_n_sl_by_bus[2] == pytest.approx(30.0)
    assert cut.phi_by_line_id["line_01_02"] == pytest.approx(100.0)

    master_problem = build_master_problem(
        instance,
        cuts=(cut,),
        model_name="round_07_5_real_cut_master",
    )
    dump_path = dump_model_artifact(
        master_problem,
        Path("/tmp/round_07_5_real_cut_master.lp"),
    )
    model = master_problem.model
    support_row = model.getConstrByName("eq39_cut_support_real_cut_shortage")
    u_link_row = model.getConstrByName("eq39_u_link_real_cut_shortage_line_01_02")

    assert dump_path.exists()
    assert support_row is not None
    assert support_row.Sense == ">"
    assert support_row.RHS == pytest.approx(cut.beta)
    assert model.getCoeff(support_row, master_problem.alpha_var) == pytest.approx(1.0)
    assert model.getCoeff(
        support_row,
        master_problem.first_stage.n_sl_by_bus[2],
    ) == pytest.approx(cut.gamma_n_sl_by_bus[2])
    assert model.getCoeff(
        support_row,
        master_problem.s_by_cut_id["real_cut_shortage"],
    ) == pytest.approx(-float(master_problem.budget_k))
    assert model.getCoeff(
        support_row,
        master_problem.u_by_cut_id_and_line_id[("real_cut_shortage", "line_01_02")],
    ) == pytest.approx(-1.0)

    assert u_link_row is not None
    assert u_link_row.Sense == ">"
    assert u_link_row.RHS == pytest.approx(cut.phi_by_line_id["line_01_02"])
    assert model.getCoeff(
        u_link_row,
        master_problem.u_by_cut_id_and_line_id[("real_cut_shortage", "line_01_02")],
    ) == pytest.approx(1.0)
    assert model.getCoeff(
        u_link_row,
        master_problem.lambda_by_line_id["line_01_02"],
    ) == pytest.approx(1.0)
    assert model.getCoeff(
        u_link_row,
        master_problem.s_by_cut_id["real_cut_shortage"],
    ) == pytest.approx(1.0)

    master_problem.model.optimize()
    solution = extract_master_problem_solution(master_problem)
    residual = build_master_problem_residual_report(master_problem, solution)

    assert solution.model_status == "OPTIMAL"
    assert residual.max_cut_support_violation <= 1e-8
    assert residual.max_u_link_violation <= 1e-8
    assert "real_cut_shortage" in residual.cut_support_slacks
