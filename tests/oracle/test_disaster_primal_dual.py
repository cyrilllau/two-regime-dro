"""Primal-vs-auto-dual oracle tests for the disaster reference LP."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import build_residual_report
from src.reference.disaster_dual_auto import solve_disaster_dual_auto
from src.reference.disaster_primal_ref import solve_disaster_primal_reference
from src.reference.kkt_checks import run_kkt_checks
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
def test_primal_and_auto_dual_objectives_match_on_toy_cases(
    fixture_name: str,
    case_label: str,
    tmp_path: Path,
) -> None:
    """Every toy case should satisfy strong duality for the auto-derived dual."""

    instance, plan, outage, scenario_id, _ = _build_case(fixture_name)
    reference_model, primal_solution = solve_disaster_primal_reference(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name=f"primal_{case_label}",
    )
    canonical_lp = canonicalize_reference_lp(reference_model)
    auto_dual_model, dual_solution = solve_disaster_dual_auto(
        canonical_lp,
        model_name=f"dual_{case_label}",
    )
    residual = build_residual_report(reference_model, primal_solution)
    kkt_report = run_kkt_checks(
        reference_model,
        primal_solution,
        auto_dual_model,
        dual_solution,
        residual,
        canonical_lp=canonical_lp,
    )

    assert primal_solution.objective_value == pytest.approx(dual_solution.objective_value, abs=1e-8)
    assert kkt_report.primal_feasibility_max_violation <= 1e-9
    assert kkt_report.dual_feasibility_max_violation <= 1e-9
    assert kkt_report.strong_duality_gap <= 1e-8
    assert kkt_report.max_row_complementarity <= 1e-8
    assert kkt_report.max_variable_complementarity <= 1e-8

    if fixture_name == "disaster_primal_zero.yaml":
        dump_path = dump_model_artifact(auto_dual_model, tmp_path / "dual_zero.lp")
        assert dump_path.exists()


def test_canonicalizer_reports_free_line_flow_splitting() -> None:
    """Free line-flow variables should be split explicitly in the canonical LP."""

    instance, plan, outage, scenario_id, _ = _build_case("disaster_primal_failed_line.yaml")
    reference_model, _ = solve_disaster_primal_reference(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name="primal_for_free_split",
    )
    canonical_lp = canonicalize_reference_lp(reference_model)

    assert "pdis_eq27_eq32_t1_line_01_02" in canonical_lp.free_variable_map
    pos_name, neg_name = canonical_lp.free_variable_map["pdis_eq27_eq32_t1_line_01_02"]
    assert pos_name.endswith("__pos")
    assert neg_name.endswith("__neg")
