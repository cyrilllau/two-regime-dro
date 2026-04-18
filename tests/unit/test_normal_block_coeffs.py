"""Direct coefficient checks for the Round 06 normal-operation block."""

from __future__ import annotations

import pytest

from src.contracts.naming import make_line_id
from src.production.first_stage import build_first_stage_model
from src.production.normal_block import build_normal_operation_block
from tests.oracle.test_first_stage_normal_toy_cases import build_round_06_toy_case


def test_normal_block_objective_coefficients_and_charge_rows_match_eq17_to_eq19() -> None:
    """Eq. (17)-(19) should preserve assignment, unmet, capacity, and siting-linkage signs."""

    instance, scenario_id, _ = build_round_06_toy_case("normal_block_t4_distance_preference.yaml")
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_normal_coeffs_a",
        attach_objective=True,
    )
    normal_block = build_normal_operation_block(
        instance,
        first_stage=first_stage,
        scenario_id=scenario_id,
        attach_objective=True,
    )
    model = normal_block.model

    y_bus2 = normal_block.charge_slow_vars[(1, 1, 2)]
    y_bus3 = normal_block.charge_slow_vars[(1, 1, 3)]
    unmet = normal_block.unmet_slow_vars[(1, 1)]
    assert y_bus2.Obj == pytest.approx(1.0 * 1.0 / instance.ev.p_ev_rated_sl)
    assert y_bus3.Obj == pytest.approx(1.0 * 2.0 / instance.ev.p_ev_rated_sl)
    assert unmet.Obj == pytest.approx(instance.economics.cunmet)

    eq17 = model.getConstrByName("eq17_balance_slow_t1_o1")
    assert eq17 is not None
    assert eq17.Sense == "="
    assert eq17.RHS == pytest.approx(50.0)
    assert model.getCoeff(eq17, normal_block.charge_slow_vars[(1, 1, 1)]) == pytest.approx(1.0)
    assert model.getCoeff(eq17, y_bus2) == pytest.approx(1.0)
    assert model.getCoeff(eq17, y_bus3) == pytest.approx(1.0)
    assert model.getCoeff(eq17, unmet) == pytest.approx(1.0)

    eq18 = model.getConstrByName("eq18_station_capacity_slow_t1_n2")
    assert eq18 is not None
    assert eq18.Sense == "<"
    assert eq18.RHS == pytest.approx(0.0)
    assert model.getCoeff(eq18, y_bus2) == pytest.approx(1.0)
    assert model.getCoeff(eq18, first_stage.n_sl_by_bus[2]) == pytest.approx(
        -instance.ev.p_ev_rated_sl
    )

    eq19 = model.getConstrByName("eq19_link_slow_t1_o1_n2")
    assert eq19 is not None
    assert eq19.Sense == "<"
    assert eq19.RHS == pytest.approx(0.0)
    assert model.getCoeff(eq19, y_bus2) == pytest.approx(1.0)
    assert model.getCoeff(eq19, first_stage.z_by_bus[2]) == pytest.approx(-50.0)


def test_normal_block_power_flow_rows_match_eq20_to_eq25_signs() -> None:
    """Eq. (20)-(25) should preserve balance, line-bound, and voltage-row sign conventions."""

    instance, scenario_id, _ = build_round_06_toy_case("normal_block_t4_distance_preference.yaml")
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_normal_coeffs_b",
        attach_objective=True,
    )
    normal_block = build_normal_operation_block(
        instance,
        first_stage=first_stage,
        scenario_id=scenario_id,
        attach_objective=True,
    )
    model = normal_block.model
    line_12 = make_line_id(1, 2)
    line_23 = make_line_id(2, 3)

    eq20 = model.getConstrByName(f"eq20_active_balance_t1_{line_12}")
    assert eq20 is not None
    assert eq20.Sense == "="
    assert eq20.RHS == pytest.approx(0.0)
    assert model.getCoeff(eq20, normal_block.active_flow_vars[(1, line_12)]) == pytest.approx(1.0)
    assert model.getCoeff(eq20, normal_block.active_flow_vars[(1, line_23)]) == pytest.approx(-1.0)
    assert model.getCoeff(eq20, normal_block.charge_slow_vars[(1, 1, 2)]) == pytest.approx(-1.0)
    assert model.getCoeff(eq20, normal_block.charge_fast_vars[(1, 1, 2)]) == pytest.approx(-1.0)

    eq21 = model.getConstrByName(f"eq21_reactive_balance_t1_{line_12}")
    assert eq21 is not None
    assert eq21.Sense == "="
    assert eq21.RHS == pytest.approx(0.0)
    assert model.getCoeff(eq21, normal_block.reactive_flow_vars[(1, line_12)]) == pytest.approx(
        1.0
    )
    assert model.getCoeff(eq21, normal_block.reactive_flow_vars[(1, line_23)]) == pytest.approx(
        -1.0
    )

    eq22 = model.getConstrByName("eq22_substation_t1")
    assert eq22 is not None
    assert eq22.Sense == "="
    assert eq22.RHS == pytest.approx(0.0)
    assert model.getCoeff(eq22, normal_block.substation_active_vars[1]) == pytest.approx(1.0)
    assert model.getCoeff(eq22, normal_block.active_flow_vars[(1, line_12)]) == pytest.approx(-1.0)
    assert model.getCoeff(eq22, normal_block.charge_slow_vars[(1, 1, 1)]) == pytest.approx(-1.0)
    assert model.getCoeff(eq22, normal_block.charge_fast_vars[(1, 1, 1)]) == pytest.approx(-1.0)

    active_upper = model.getConstrByName(f"eq23_active_upper_t1_{line_12}")
    active_lower = model.getConstrByName(f"eq23_active_lower_t1_{line_12}")
    reactive_upper = model.getConstrByName(f"eq23_reactive_upper_t1_{line_12}")
    reactive_lower = model.getConstrByName(f"eq23_reactive_lower_t1_{line_12}")
    assert active_upper is not None and active_upper.Sense == "<"
    assert active_lower is not None and active_lower.Sense == "<"
    assert reactive_upper is not None and reactive_upper.Sense == "<"
    assert reactive_lower is not None and reactive_lower.Sense == "<"

    eq24 = model.getConstrByName(f"eq24_voltage_drop_t1_{line_23}")
    assert eq24 is not None
    assert eq24.Sense == "="
    assert eq24.RHS == pytest.approx(0.0)
    assert model.getCoeff(eq24, normal_block.voltage_vars[(1, 3)]) == pytest.approx(1.0)
    assert model.getCoeff(eq24, normal_block.voltage_vars[(1, 2)]) == pytest.approx(-1.0)
    assert model.getCoeff(eq24, normal_block.active_flow_vars[(1, line_23)]) == pytest.approx(
        2.0 * 0.001 / 1000.0
    )
    assert model.getCoeff(eq24, normal_block.reactive_flow_vars[(1, line_23)]) == pytest.approx(
        2.0 * 0.002 / 1000.0
    )

    eq25_lower = model.getConstrByName("eq25_voltage_lower_t1_n2")
    eq25_upper = model.getConstrByName("eq25_voltage_upper_t1_n2")
    root_fix = model.getConstrByName("root_voltage_fix_t1")
    assert eq25_lower is not None and eq25_lower.Sense == ">"
    assert eq25_upper is not None and eq25_upper.Sense == "<"
    assert root_fix is not None and root_fix.Sense == "="
