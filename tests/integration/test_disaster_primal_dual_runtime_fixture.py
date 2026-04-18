"""Integration test for primal-vs-auto-dual agreement on the runtime fixture."""

from __future__ import annotations

from pathlib import Path

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import build_residual_report
from src.instance.canonical_instance import load_canonical_instance
from src.reference.disaster_dual_auto import solve_disaster_dual_auto
from src.reference.disaster_primal_ref import (
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
    solve_disaster_primal_reference,
)
from src.reference.kkt_checks import run_kkt_checks
from src.reference.lp_canonicalizer import canonicalize_reference_lp


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_disaster_primal_and_auto_dual_agree_on_runtime_fixture(tmp_path: Path) -> None:
    """Primal and auto dual should agree on the canonical runtime fixture with explicit critical buses."""

    instance = load_canonical_instance(
        REPO_ROOT / "data/runtime_12",
        critical_buses=(5, 9),
    )
    scenario_id = instance.scenario_support.disaster[0]
    failed_line_id = instance.sets.line_ids[0]
    plan = build_fixed_first_stage_plan(instance)
    outage = build_fixed_outage_vector(instance, by_line_id={failed_line_id: 1})

    reference_model, primal_solution = solve_disaster_primal_reference(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name="runtime_fixture_primal_round_03",
    )
    canonical_lp = canonicalize_reference_lp(reference_model)
    auto_dual_model, dual_solution = solve_disaster_dual_auto(
        canonical_lp,
        model_name="runtime_fixture_auto_dual_round_03",
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

    primal_dump = dump_model_artifact(reference_model, tmp_path / "runtime_fixture_primal.lp")
    dual_dump = dump_model_artifact(auto_dual_model, tmp_path / "runtime_fixture_auto_dual.lp")

    assert abs(primal_solution.objective_value - dual_solution.objective_value) <= 1e-8
    assert kkt_report.strong_duality_gap <= 1e-8
    assert kkt_report.primal_feasibility_max_violation <= 1e-9
    assert kkt_report.dual_feasibility_max_violation <= 1e-9
    assert "eq27_active_balance_t1_line_01_02" in residual.eq27_active_balance_residuals
    assert primal_dump.exists()
    assert dual_dump.exists()
