"""Unit-semantics checks for the Round 06 normal-operation block."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.contracts.naming import make_line_id
from src.instance.canonical_instance import load_canonical_instance
from src.production.first_stage import build_first_stage_model
from src.production.normal_block import (
    EQ24_POWER_BASE_KW,
    EQ24_POWER_TO_PU_SCALE,
    build_normal_operation_block,
)
from tests.oracle.test_first_stage_normal_toy_cases import build_round_06_toy_case


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _load_unit_guard_fixture() -> dict[str, object]:
    return json.loads(
        (FIXTURE_DIR / "normal_block_unit_guard_runtime_assumption.yaml").read_text(
            encoding="utf-8"
        )
    )


def test_eq24_scaling_assumption_is_explicit_on_built_block() -> None:
    """The production block should expose the implicit 1 MVA Eq. (24) conversion explicitly."""

    expected = _load_unit_guard_fixture()
    instance, scenario_id, _ = build_round_06_toy_case(
        "normal_block_voltage_drop_analytic_2bus.yaml"
    )
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_5_unit_semantics_toy",
        attach_objective=True,
    )
    normal_block = build_normal_operation_block(
        instance,
        first_stage=first_stage,
        scenario_id=scenario_id,
        attach_objective=True,
    )

    assert EQ24_POWER_BASE_KW == pytest.approx(float(expected["eq24_power_base_kw"]))
    assert EQ24_POWER_TO_PU_SCALE == pytest.approx(
        float(expected["eq24_power_to_pu_scale"])
    )
    assert normal_block.eq24_power_base_kw == pytest.approx(
        float(expected["eq24_power_base_kw"])
    )
    assert normal_block.eq24_power_to_pu_scale == pytest.approx(
        float(expected["eq24_power_to_pu_scale"])
    )
    assert str(expected["unit_assumption_substring"]) in normal_block.eq24_unit_assumption


def test_runtime_eq24_coefficients_match_per_unit_times_kw_to_mw_conversion() -> None:
    """Runtime Eq. (24) rows should carry the explicit `1/1000` conversion on power variables."""

    instance = load_canonical_instance("data/runtime_12", critical_buses=(5, 9))
    scenario_id = instance.sets.loaded_normal_scenarios[0]
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_5_unit_semantics_runtime",
        attach_objective=True,
    )
    normal_block = build_normal_operation_block(
        instance,
        first_stage=first_stage,
        scenario_id=scenario_id,
        attach_objective=True,
    )
    model = normal_block.model
    line = instance.lines[0]
    line_id = line.line_id

    assert instance.economics.power_unit == "kW"
    eq24 = model.getConstrByName(f"eq24_voltage_drop_t1_{line_id}")
    assert eq24 is not None
    assert eq24.Sense == "="
    assert model.getCoeff(eq24, normal_block.voltage_vars[(1, line.to_bus)]) == pytest.approx(1.0)
    assert model.getCoeff(eq24, normal_block.voltage_vars[(1, line.from_bus)]) == pytest.approx(
        -1.0
    )
    assert model.getCoeff(eq24, normal_block.active_flow_vars[(1, line_id)]) == pytest.approx(
        2.0 * line.resistance_pu / 1000.0
    )
    assert model.getCoeff(eq24, normal_block.reactive_flow_vars[(1, line_id)]) == pytest.approx(
        2.0 * line.reactance_pu / 1000.0
    )
