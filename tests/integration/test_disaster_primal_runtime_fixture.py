"""Integration test for the disaster primal reference LP on the runtime fixture."""

from __future__ import annotations

from pathlib import Path

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import build_residual_report
from src.instance.canonical_instance import load_canonical_instance
from src.reference.disaster_primal_ref import (
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
    solve_disaster_primal_reference,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_disaster_primal_reference_consumes_runtime_fixture(tmp_path: Path) -> None:
    """The reference LP should solve on the default runtime selection with explicit critical buses."""

    instance = load_canonical_instance(
        REPO_ROOT / "data/runtime_12",
        critical_buses=(5, 9),
    )
    scenario_id = instance.scenario_support.disaster[0]
    failed_line_id = instance.sets.line_ids[0]
    plan = build_fixed_first_stage_plan(instance)
    outage = build_fixed_outage_vector(instance, by_line_id={failed_line_id: 1})

    reference_model, solution = solve_disaster_primal_reference(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name="disaster_primal_runtime_fixture",
    )
    dump_path = dump_model_artifact(reference_model, tmp_path / "runtime_fixture_disaster_primal.lp")
    residual = build_residual_report(reference_model, solution)

    assert instance.scenario_support.disaster == (1, 2)
    assert solution.model_status == "OPTIMAL"
    assert solution.objective_value is not None
    assert solution.objective_value >= 0.0
    for ts in instance.sets.disaster_times:
        assert abs(solution.line_flow_by_time_line[(ts, failed_line_id)]) <= 1e-9
    assert dump_path.exists()
    assert residual.max_failed_line_flow_violation <= 1e-9
