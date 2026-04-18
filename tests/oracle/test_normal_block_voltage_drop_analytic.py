"""Hand-checkable analytic regression for the Round 06 Eq. (24) voltage-drop row."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import build_normal_operation_residual_report
from src.contracts.naming import make_line_id
from src.production.normal_block import solve_first_stage_with_normal_operation_block
from tests.oracle.test_first_stage_normal_toy_cases import build_round_06_toy_case


def test_two_bus_voltage_drop_matches_hand_calculation() -> None:
    """2-bus analytic case: 100 kW and 50 kvar on a line with R=0.01, X=0.02 gives a 0.004 drop."""

    instance, scenario_id, raw = build_round_06_toy_case(
        "normal_block_voltage_drop_analytic_2bus.yaml"
    )
    first_stage, first_stage_solution, normal_block, normal_solution = (
        solve_first_stage_with_normal_operation_block(
            instance,
            scenario_id=scenario_id,
            model_name="round_06_5_voltage_drop_analytic",
        )
    )
    dump_path = dump_model_artifact(
        normal_block,
        Path("/tmp/round_06_5_voltage_drop_analytic.lp"),
    )
    residual = build_normal_operation_residual_report(normal_block, normal_solution)

    line_id = make_line_id(1, 2)
    analytic = raw["analytic"]
    expected_drop = (
        2.0 * instance.lines[0].resistance_pu * (float(analytic["p_kw"]) / 1000.0)
        + 2.0 * instance.lines[0].reactance_pu * (float(analytic["q_kvar"]) / 1000.0)
    )
    expected_v_to = float(analytic["v_from_sq"]) - expected_drop

    assert dump_path.exists()
    assert first_stage_solution.objective_is_pure_construction is False
    assert first_stage_solution.construction_cost_value == pytest.approx(0.0)
    assert normal_solution.substation_active_by_time[1] == pytest.approx(float(analytic["p_kw"]))
    assert normal_solution.active_flow_by_time_line[(1, line_id)] == pytest.approx(
        float(analytic["p_kw"])
    )
    assert normal_solution.reactive_flow_by_time_line[(1, line_id)] == pytest.approx(
        float(analytic["q_kvar"])
    )
    assert expected_drop == pytest.approx(float(analytic["expected_drop_sq"]))
    assert expected_v_to == pytest.approx(float(analytic["expected_v_to_sq"]))
    assert normal_solution.voltage_by_time_bus[(1, 1)] == pytest.approx(
        float(analytic["v_from_sq"])
    )
    assert normal_solution.voltage_by_time_bus[(1, 2)] == pytest.approx(expected_v_to)
    assert residual.eq24_power_to_pu_scale == pytest.approx(0.001)
    assert residual.max_voltage_drop_residual <= 1e-10
