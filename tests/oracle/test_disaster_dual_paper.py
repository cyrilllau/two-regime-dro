"""Primal-vs-auto-dual-vs-paper-dual oracle tests for the disaster block."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import (
    build_paper_dual_residual_report,
    build_residual_report,
)
from src.production.disaster_dual_paper import solve_disaster_dual_paper
from src.reference.disaster_dual_auto import solve_disaster_dual_auto
from src.reference.disaster_primal_ref import solve_disaster_primal_reference
from src.reference.lp_canonicalizer import canonicalize_reference_lp
from tests.oracle.test_disaster_primal_ref import _build_case


@pytest.mark.parametrize(
    ("fixture_name", "case_label"),
    [
        ("disaster_primal_zero.yaml", "zero"),
        ("disaster_primal_shortage.yaml", "shortage"),
        ("disaster_primal_critical_priority.yaml", "critical"),
        ("disaster_primal_failed_line.yaml", "failed_line"),
        ("disaster_primal_mixed_slow_fast.yaml", "mixed_slow_fast"),
    ],
)
def test_primal_auto_dual_and_paper_dual_agree_on_toy_cases(
    fixture_name: str,
    case_label: str,
    tmp_path: Path,
) -> None:
    """Every toy case should satisfy primal = auto dual = paper dual."""

    instance, plan, outage, scenario_id, _ = _build_case(fixture_name)
    reference_model, primal_solution = solve_disaster_primal_reference(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name=f"primal_{case_label}_round_04",
    )
    canonical_lp = canonicalize_reference_lp(reference_model)
    auto_dual_model, auto_dual_solution = solve_disaster_dual_auto(
        canonical_lp,
        model_name=f"auto_dual_{case_label}_round_04",
    )
    paper_dual_model, paper_dual_solution = solve_disaster_dual_paper(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name=f"paper_dual_{case_label}_round_04",
    )
    primal_residual = build_residual_report(reference_model, primal_solution)
    paper_dual_residual = build_paper_dual_residual_report(
        paper_dual_model,
        paper_dual_solution,
    )

    assert primal_solution.objective_value == pytest.approx(
        auto_dual_solution.objective_value,
        abs=1e-8,
    )
    assert auto_dual_solution.objective_value == pytest.approx(
        paper_dual_solution.objective_value,
        abs=1e-8,
    )
    assert paper_dual_solution.samplewise_decomposition.evaluate(
        plan=plan,
        outage=outage,
    ) == pytest.approx(paper_dual_solution.objective_value, abs=1e-8)
    assert paper_dual_residual.max_sign_violation <= 1e-9
    assert paper_dual_residual.max_dual_row_violation <= 1e-9
    assert paper_dual_residual.decomposition_gap <= 1e-8
    assert "dual_yls_t1_n1" in paper_dual_residual.yls_dual_row_slacks
    assert primal_residual.max_eq27_active_balance_residual <= 1e-9

    if fixture_name == "disaster_primal_zero.yaml":
        dump_path = dump_model_artifact(
            paper_dual_model,
            tmp_path / "paper_dual_zero.lp",
        )
        assert dump_path.exists()
