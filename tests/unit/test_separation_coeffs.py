"""Coefficient and model-shape checks for the Round 05 separation MILP."""

from __future__ import annotations

import pytest
from gurobipy import GRB

from src.production.separation_milp import build_separation_milp
from tests.oracle.test_disaster_primal_ref import _build_case


def _build_inspection_model():
    instance, plan, _, scenario_id, _ = _build_case("disaster_primal_mixed_slow_fast.yaml")
    line_ids = instance.sets.line_ids
    lambda_by_line_id = {line_id: 0.0 for line_id in line_ids}
    lambda_by_line_id[line_ids[0]] = 7.5
    separation_model = build_separation_milp(
        instance,
        plan=plan,
        alpha=4.0,
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id={line_id: (0.0, 250.0) for line_id in line_ids},
        budget_k=1,
        scenario_ids=(scenario_id,),
        model_name="round_05_5_coeff_inspection",
    )
    return instance, plan, scenario_id, separation_model, lambda_by_line_id


def test_separation_model_has_expected_variable_types_and_mccormick_shape() -> None:
    """The built MILP should expose the expected binary/budget/McCormick structure."""

    instance, _, _, separation_model, _ = _build_inspection_model()
    model = separation_model.model

    assert set(separation_model.delta_vars) == set(instance.sets.line_ids)
    assert set(separation_model.omega_vars) == set(instance.sets.line_ids)
    assert set(separation_model.tau_vars) == set(instance.sets.line_ids)

    for line_id in instance.sets.line_ids:
        assert separation_model.delta_vars[line_id].VType == GRB.BINARY
        assert separation_model.omega_vars[line_id].VType == GRB.CONTINUOUS
        assert separation_model.tau_vars[line_id].VType == GRB.CONTINUOUS

    budget_rows = [
        constr for constr in model.getConstrs() if constr.ConstrName == "outage_budget"
    ]
    assert len(budget_rows) == 1
    assert budget_rows[0].Sense == "<"
    assert budget_rows[0].RHS == pytest.approx(1.0)

    for line_id in instance.sets.line_ids:
        expected_rows = {
            f"tau_lower_prod_{line_id}": ">",
            f"tau_upper_prod_{line_id}": "<",
            f"tau_mccormick_lb_{line_id}": ">",
            f"tau_mccormick_ub_{line_id}": "<",
        }
        for row_name, expected_sense in expected_rows.items():
            constr = model.getConstrByName(row_name)
            assert constr is not None
            assert constr.Sense == expected_sense

    tau_rows = [
        constr
        for constr in model.getConstrs()
        if constr.ConstrName.startswith("tau_")
    ]
    assert len(tau_rows) == 4 * len(instance.sets.line_ids)


def test_separation_objective_and_omega_definition_coefficients_have_expected_signs() -> None:
    """Objective coefficients and omega-definition rows should preserve the paper sign pattern."""

    instance, plan, scenario_id, separation_model, lambda_by_line_id = _build_inspection_model()
    model = separation_model.model
    sample_block = separation_model.sample_blocks[scenario_id]
    ts = instance.sets.disaster_times[0]
    sample_count = len(separation_model.scenario_ids)

    line_with_load = next(
        line
        for line in instance.lines
        if instance.disaster_tensors.p_load[(scenario_id, ts, line.to_bus)] > 0.0
    )
    line_id = line_with_load.line_id
    bus = line_with_load.to_bus

    region = next(
        region
        for region in instance.sets.regions
        if instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)] > 0.0
    )
    bus_with_fast = next(bus_id for bus_id, count in plan.n_fa_by_bus.items() if count > 0)
    bus_with_site = next(bus_id for bus_id, value in plan.z_by_bus.items() if value == 1)

    lam_var = sample_block.eq27_lambda_vars[(ts, line_id)]
    mu_var = sample_block.eq29_fast_vars[(ts, bus_with_fast)]
    nu_var = sample_block.eq30_fast_vars[(ts, region, bus_with_site)]
    sigma_var = sample_block.eq31_sigma_vars[(ts, bus)]
    rho_var = sample_block.eq32_upper_vars[(ts, line_id)]
    delta_var = separation_model.delta_vars[line_id]
    omega_var = separation_model.omega_vars[line_id]
    tau_var = separation_model.tau_vars[line_id]

    assert lam_var.Obj == pytest.approx(
        instance.disaster_tensors.p_load[(scenario_id, ts, bus)] / sample_count
    )
    assert mu_var.Obj == pytest.approx(
        -instance.ev.p_ev_rated_fa * plan.n_fa_by_bus[bus_with_fast] / sample_count
    )
    assert nu_var.Obj == pytest.approx(
        -instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]
        * plan.z_by_bus[bus_with_site]
        / sample_count
    )
    assert sigma_var.Obj == pytest.approx(
        -instance.disaster_tensors.p_load[(scenario_id, ts, bus)] / sample_count
    )
    assert rho_var.Obj == pytest.approx(-line_with_load.p_max_kw / sample_count)

    assert delta_var.Obj == pytest.approx(-lambda_by_line_id[line_id])
    assert tau_var.Obj == pytest.approx(1.0)
    assert omega_var.Obj == pytest.approx(0.0)
    assert model.ObjCon == pytest.approx(-4.0)

    omega_row = model.getConstrByName(f"omega_definition_{line_id}")
    assert omega_row is not None
    assert omega_row.Sense == "="
    assert model.getCoeff(omega_row, omega_var) == pytest.approx(1.0)
    assert model.getCoeff(omega_row, sample_block.eq32_upper_vars[(ts, line_id)]) == pytest.approx(
        -line_with_load.p_max_kw / sample_count
    )
    assert model.getCoeff(omega_row, sample_block.eq32_lower_vars[(ts, line_id)]) == pytest.approx(
        -line_with_load.p_max_kw / sample_count
    )
