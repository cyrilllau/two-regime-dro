"""Direct coefficient and model-shape checks for the Round 07 restricted master problem."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.instance.schema import ObjectiveMultipliers
from src.production.master_problem import build_master_problem
from tests.oracle.test_master_problem_toy_cases import build_round_07_toy_case


def test_master_problem_objective_coefficients_match_alpha_lambda_and_normal_averaging() -> None:
    """The RMP objective should preserve the required alpha/lambda and averaged-normal weights."""

    averaging_instance, averaging_cuts, _ = build_round_07_toy_case(
        "master_problem_normal_averaging.yaml"
    )
    averaging_master = build_master_problem(
        averaging_instance,
        cuts=averaging_cuts,
        model_name="round_07_master_coeffs_average",
    )
    normal_weight = (1.0 - averaging_instance.economics.pi_f) / len(
        averaging_instance.sets.loaded_normal_scenarios
    )
    scenario_1_block = averaging_master.normal_blocks_by_scenario[1]

    assert averaging_master.normal_average_weight == pytest.approx(normal_weight)
    assert averaging_master.alpha_var.Obj == pytest.approx(averaging_instance.economics.pi_f)
    assert scenario_1_block.charge_slow_vars[(1, 1, 2)].Obj == pytest.approx(
        normal_weight * 1.0 / averaging_instance.ev.p_ev_rated_sl
    )
    assert scenario_1_block.unmet_slow_vars[(1, 1)].Obj == pytest.approx(
        normal_weight * averaging_instance.economics.cunmet
    )

    phi_instance, phi_cuts, _ = build_round_07_toy_case("master_problem_phi_support.yaml")
    phi_master = build_master_problem(
        phi_instance,
        cuts=phi_cuts,
        model_name="round_07_master_coeffs_phi",
    )
    line_id = phi_instance.sets.line_ids[0]

    assert phi_master.alpha_var.Obj == pytest.approx(phi_instance.economics.pi_f)
    assert phi_master.lambda_by_line_id[line_id].Obj == pytest.approx(
        phi_instance.economics.pi_f * phi_instance.ambiguity.p_bar[0]
    )


def test_master_problem_objective_multipliers_scale_training_coefficients_only() -> None:
    """Objective multipliers should affect only the optimized master objective."""

    instance, cuts, _ = build_round_07_toy_case("master_problem_normal_averaging.yaml")
    instance = replace(
        instance,
        economics=replace(
            instance.economics,
            objective_multipliers=ObjectiveMultipliers(
                cons=2.0,
                normal=3.0,
                disaster=5.0,
            ),
        ),
    )
    master = build_master_problem(
        instance,
        cuts=cuts,
        model_name="round_07_master_coeffs_objective_multipliers",
    )
    normal_weight = (1.0 - instance.economics.pi_f) / len(
        instance.sets.loaded_normal_scenarios
    )
    scenario_1_block = master.normal_blocks_by_scenario[1]
    line_id = instance.sets.line_ids[0]

    assert master.first_stage.z_by_bus[2].Obj == pytest.approx(
        2.0 * instance.economics.cfix
    )
    assert scenario_1_block.unmet_slow_vars[(1, 1)].Obj == pytest.approx(
        3.0 * normal_weight * instance.economics.cunmet
    )
    assert master.alpha_var.Obj == pytest.approx(5.0 * instance.economics.pi_f)
    assert master.lambda_by_line_id[line_id].Obj == pytest.approx(
        5.0 * instance.economics.pi_f * instance.ambiguity.p_bar[0]
    )


def test_disaster_only_master_excludes_normal_recourse_blocks() -> None:
    """Case 3 should not include normal-stage recourse variables or constraints."""

    instance, cuts, _ = build_round_07_toy_case("master_problem_normal_averaging.yaml")
    instance = replace(
        instance,
        economics=replace(instance.economics, pi_f=1.0),
        metadata={**instance.metadata, "benchmark_mode": "disaster_only"},
    )
    master = build_master_problem(
        instance,
        cuts=cuts,
        model_name="round_07_master_disaster_only_no_normal_blocks",
    )

    variable_names = {var.VarName for var in master.model.getVars()}

    assert master.normal_recourse_active is False
    assert master.normal_blocks_by_scenario == {}
    assert master.normal_average_weight == pytest.approx(0.0)
    assert master.averaged_normal_cost_expression == pytest.approx(0.0)
    assert not any(name.startswith("p_sub_") for name in variable_names)
    assert not any(name.startswith("unmet_slow_") for name in variable_names)
    assert not any(name.startswith("unmet_fast_") for name in variable_names)
    assert not any(name.startswith("charge_slow_") for name in variable_names)
    assert not any(name.startswith("charge_fast_") for name in variable_names)


def test_master_problem_cut_rows_match_eq39_sign_patterns() -> None:
    """Cut-support and `u`-link rows should preserve the expected Eq. (39) signs."""

    gamma_instance, gamma_cuts, _ = build_round_07_toy_case(
        "master_problem_gamma_incentive.yaml"
    )
    gamma_master = build_master_problem(
        gamma_instance,
        cuts=gamma_cuts,
        model_name="round_07_master_coeffs_gamma_rows",
    )
    gamma_model = gamma_master.model
    line_id = gamma_instance.sets.line_ids[0]

    support_row = gamma_model.getConstrByName("eq39_cut_support_gamma_site")
    assert support_row is not None
    assert support_row.Sense == ">"
    assert support_row.RHS == pytest.approx(100.0)
    assert gamma_model.getCoeff(support_row, gamma_master.alpha_var) == pytest.approx(1.0)
    assert gamma_model.getCoeff(
        support_row,
        gamma_master.first_stage.z_by_bus[2],
    ) == pytest.approx(100.0)
    assert gamma_model.getCoeff(
        support_row,
        gamma_master.s_by_cut_id["gamma_site"],
    ) == pytest.approx(-1.0)
    assert gamma_model.getCoeff(
        support_row,
        gamma_master.u_by_cut_id_and_line_id[("gamma_site", line_id)],
    ) == pytest.approx(-1.0)

    phi_instance, phi_cuts, _ = build_round_07_toy_case("master_problem_phi_support.yaml")
    phi_master = build_master_problem(
        phi_instance,
        cuts=phi_cuts,
        model_name="round_07_master_coeffs_phi_rows",
    )
    phi_model = phi_master.model
    u_link_row = phi_model.getConstrByName(f"eq39_u_link_phi_support_{line_id}")
    assert u_link_row is not None
    assert u_link_row.Sense == ">"
    assert u_link_row.RHS == pytest.approx(10.0)
    assert phi_model.getCoeff(
        u_link_row,
        phi_master.u_by_cut_id_and_line_id[("phi_support", line_id)],
    ) == pytest.approx(1.0)
    assert phi_model.getCoeff(
        u_link_row,
        phi_master.lambda_by_line_id[line_id],
    ) == pytest.approx(1.0)
    assert phi_model.getCoeff(
        u_link_row,
        phi_master.s_by_cut_id["phi_support"],
    ) == pytest.approx(1.0)
