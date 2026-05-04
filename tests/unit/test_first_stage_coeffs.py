"""Direct coefficient checks for the Round 06 first-stage builder."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.production.first_stage import build_first_stage_model, extract_first_stage_solution
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


def test_first_stage_uses_bus_specific_capacity_bounds_when_provided() -> None:
    """Eq. (12) should prefer explicit bus caps over the global EVSE bounds."""

    instance, _, _ = build_round_06_toy_case("first_stage_t2_minimum_three.yaml")
    instance = replace(
        instance,
        ev=replace(
            instance.ev,
            nbar_sl_by_bus={2: 4},
            nbar_fa_by_bus={2: 2},
        ),
    )
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_first_stage_bus_specific_bounds",
        attach_objective=True,
    )
    model = first_stage.model

    slow_row = model.getConstrByName("eq12_n_sl_ub_n2")
    assert slow_row is not None
    assert model.getCoeff(slow_row, first_stage.n_sl_by_bus[2]) == pytest.approx(1.0)
    assert model.getCoeff(slow_row, first_stage.z_by_bus[2]) == pytest.approx(-4.0)

    fast_row = model.getConstrByName("eq12_n_fa_ub_n2")
    assert fast_row is not None
    assert model.getCoeff(fast_row, first_stage.n_fa_by_bus[2]) == pytest.approx(1.0)
    assert model.getCoeff(fast_row, first_stage.z_by_bus[2]) == pytest.approx(-2.0)


def test_first_stage_minimum_slow_only_policy_fixes_case3_station_size() -> None:
    """Case 3 can force opened EVCSs to the paper-style minimum slow-only size."""

    instance, _, _ = build_round_06_toy_case("first_stage_t2_minimum_three.yaml")
    instance = replace(
        instance,
        metadata={**instance.metadata, "station_sizing_policy": "minimum_slow_only"},
    )
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_first_stage_minimum_slow_only_policy",
        attach_objective=True,
    )
    model = first_stage.model

    slow_row = model.getConstrByName("case3_minimum_slow_only_n2")
    assert slow_row is not None
    assert slow_row.Sense == "="
    assert model.getCoeff(slow_row, first_stage.n_sl_by_bus[2]) == pytest.approx(1.0)
    assert model.getCoeff(slow_row, first_stage.z_by_bus[2]) == pytest.approx(-3.0)

    fast_row = model.getConstrByName("case3_no_fast_n2")
    assert fast_row is not None
    assert fast_row.Sense == "="
    assert model.getCoeff(fast_row, first_stage.n_fa_by_bus[2]) == pytest.approx(1.0)

    model.addConstr(first_stage.z_by_bus[2] == 1.0, name="force_case3_site_open_n2")
    model.optimize()
    solution = extract_first_stage_solution(first_stage)

    assert solution.model_status == "OPTIMAL"
    assert solution.n_sl_by_bus[2] == 3
    assert solution.n_fa_by_bus[2] == 0


def test_first_stage_adds_slow_block_extra_cost_when_enabled() -> None:
    """Slow EVSEs above the configured block should carry the extra marginal cost."""

    instance, _, _ = build_round_06_toy_case("first_stage_t2_minimum_three.yaml")
    instance = replace(
        instance,
        economics=replace(instance.economics, ccons_sl_extra_multiplier=3.0),
        ev=replace(instance.ev, slow_block_threshold=2),
    )
    first_stage = build_first_stage_model(
        instance,
        model_name="round_06_first_stage_slow_block_cost",
        attach_objective=True,
    )
    model = first_stage.model

    assert first_stage.n_sl_extra_by_bus[2].Obj == pytest.approx(20.0)
    lower_row = model.getConstrByName("slow_block_extra_lb_n2")
    assert lower_row is not None
    assert model.getCoeff(lower_row, first_stage.n_sl_extra_by_bus[2]) == pytest.approx(1.0)
    assert model.getCoeff(lower_row, first_stage.n_sl_by_bus[2]) == pytest.approx(-1.0)
    assert model.getCoeff(lower_row, first_stage.z_by_bus[2]) == pytest.approx(2.0)

    model.addConstr(first_stage.z_by_bus[2] == 1.0, name="force_site_open_n2")
    model.optimize()
    solution = extract_first_stage_solution(first_stage)

    assert solution.model_status == "OPTIMAL"
    assert solution.n_sl_by_bus[2] == 3
    assert solution.n_sl_extra_by_bus[2] == 1
    assert solution.construction_cost_value == pytest.approx(55.0)
