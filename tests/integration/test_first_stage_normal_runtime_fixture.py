"""Runtime smoke test for the Round 06 first-stage and normal-operation builders."""

from __future__ import annotations

from pathlib import Path

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import build_normal_operation_residual_report
from src.instance.canonical_instance import load_canonical_instance
from src.production.normal_block import solve_first_stage_with_normal_operation_block


def test_runtime_fixture_first_stage_plus_one_normal_scenario_solves_cleanly() -> None:
    """The selected runtime fixture should build and solve one fixed normal scenario cleanly."""

    instance = load_canonical_instance(
        "data/runtime_12",
        critical_buses=(5, 9),
    )
    scenario_id = instance.sets.loaded_normal_scenarios[0]
    first_stage, first_stage_solution, normal_block, normal_solution = (
        solve_first_stage_with_normal_operation_block(
            instance,
            scenario_id=scenario_id,
            model_name="round_06_runtime_fixture",
        )
    )
    dump_path = dump_model_artifact(
        normal_block,
        Path("/tmp/round_06_runtime_first_stage_normal.lp"),
    )
    residual = build_normal_operation_residual_report(normal_block, normal_solution)

    assert dump_path.exists()
    assert first_stage.ordered_buses == instance.sets.buses
    assert tuple(first_stage.z_by_bus) == instance.sets.buses
    assert first_stage_solution.model_status == "OPTIMAL"
    assert normal_solution.model_status == "OPTIMAL"
    assert residual.max_charge_balance_residual <= 1e-8
    assert residual.max_active_power_balance_residual <= 1e-8
    assert residual.max_reactive_power_balance_residual <= 1e-8
    assert residual.max_voltage_bound_violation <= 1e-8
    assert residual.max_line_limit_violation <= 1e-8
