"""Direct coefficient checks for the Round 06 first-stage builder."""

from __future__ import annotations

import pytest

from src.production.first_stage import build_first_stage_model
from tests.oracle.test_first_stage_normal_toy_cases import build_round_06_toy_case


def test_first_stage_objective_coefficients_follow_eq10_and_root_is_fixed_off() -> None:
    """Eq. (10) should map annualized construction coefficients directly onto the first-stage vars."""

    instance, _, _ = build_round_06_toy_case("first_stage_t2_minimum_three.yaml")
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_first_stage_coeffs",
        attach_objective=True,
    )

    assert first_stage.ordered_buses == instance.sets.buses
    assert tuple(first_stage.z_by_bus) == instance.sets.buses
    assert tuple(first_stage.n_sl_by_bus) == instance.sets.buses
    assert tuple(first_stage.n_fa_by_bus) == instance.sets.buses
    assert first_stage.annualization_factor == pytest.approx(1.0)

    assert first_stage.z_by_bus[1].UB == pytest.approx(0.0)
    assert first_stage.z_by_bus[2].UB == pytest.approx(1.0)
    assert first_stage.z_by_bus[2].Obj == pytest.approx(instance.economics.cfix)
    assert first_stage.n_sl_by_bus[2].Obj == pytest.approx(instance.economics.ccons_sl)
    assert first_stage.n_fa_by_bus[2].Obj == pytest.approx(instance.economics.ccons_fa)


def test_first_stage_constraint_rows_match_eq11_and_eq12_signs() -> None:
    """Eq. (11) and Eq. (12) rows should keep the expected min-charger and upper-bound patterns."""

    instance, _, _ = build_round_06_toy_case("first_stage_t2_minimum_three.yaml")
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_first_stage_row_signs",
        attach_objective=True,
    )
    model = first_stage.model

    min_row = model.getConstrByName("eq11_min_chargers_n2")
    assert min_row is not None
    assert min_row.Sense == ">"
    assert min_row.RHS == pytest.approx(0.0)
    assert model.getCoeff(min_row, first_stage.n_sl_by_bus[2]) == pytest.approx(1.0)
    assert model.getCoeff(min_row, first_stage.n_fa_by_bus[2]) == pytest.approx(1.0)
    assert model.getCoeff(min_row, first_stage.z_by_bus[2]) == pytest.approx(-3.0)

    slow_row = model.getConstrByName("eq12_n_sl_ub_n2")
    assert slow_row is not None
    assert slow_row.Sense == "<"
    assert slow_row.RHS == pytest.approx(0.0)
    assert model.getCoeff(slow_row, first_stage.n_sl_by_bus[2]) == pytest.approx(1.0)
    assert model.getCoeff(slow_row, first_stage.z_by_bus[2]) == pytest.approx(
        -instance.ev.nbar_sl
    )

    fast_row = model.getConstrByName("eq12_n_fa_ub_n2")
    assert fast_row is not None
    assert fast_row.Sense == "<"
    assert fast_row.RHS == pytest.approx(0.0)
    assert model.getCoeff(fast_row, first_stage.n_fa_by_bus[2]) == pytest.approx(1.0)
    assert model.getCoeff(fast_row, first_stage.z_by_bus[2]) == pytest.approx(
        -instance.ev.nbar_fa
    )
