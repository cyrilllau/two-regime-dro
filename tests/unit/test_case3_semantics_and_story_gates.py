"""Lightweight gates for Case 3 semantics and default-case promotion stories."""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping

import pytest

from scripts.build_paper_final_analysis import REFERENCE_TABLE_III
from scripts.experiment_pack_utils import (
    build_disaster_only_instance,
    prepare_instance_for_run,
)
from scripts.run_default_multiplier_calibration import _base_config, _story_gate
from src.instance.schema import ObjectiveMultipliers
from src.production.master_problem import solve_master_problem
from tests.oracle.test_master_problem_toy_cases import build_round_07_toy_case


def _solve_normal_averaging_fixture_with_multipliers(
    *,
    cons_multiplier: float = 1.0,
    normal_multiplier: float,
    disaster_multiplier: float = 1.0,
):
    instance, cuts, _ = build_round_07_toy_case("master_problem_normal_averaging.yaml")
    instance = replace(
        instance,
        economics=replace(
            instance.economics,
            objective_multipliers=ObjectiveMultipliers(
                cons=cons_multiplier,
                normal=normal_multiplier,
                disaster=disaster_multiplier,
            ),
        ),
    )
    _, solution = solve_master_problem(
        instance,
        cuts=cuts,
        model_name=f"objective_multiplier_normal_{normal_multiplier:g}",
    )
    assert solution.model_status == "OPTIMAL"
    assert solution.objective_value is not None
    return solution


def _assert_default_case_phi_story_gate(table_rows: Mapping[str, Mapping[str, float]]) -> None:
    phi_case1 = float(table_rows["Case 1"]["Phi_dis"])
    phi_case2 = float(table_rows["Case 2"]["Phi_dis"])
    phi_case3 = float(table_rows["Case 3"]["Phi_dis"])

    assert phi_case1 < phi_case2, (
        "Case 1 must improve disaster resilience versus Case 2 normal-only "
        "under the common evaluator."
    )
    assert phi_case3 <= phi_case1, (
        "Case 3 disaster-only must not be promoted when its common-evaluator "
        "disaster score is worse than Case 1; this rejects Phi1<Phi3<Phi2."
    )


def test_objective_multipliers_change_solved_master_objective() -> None:
    """A changed objective multiplier must affect the solved RMP objective value."""

    base = _solve_normal_averaging_fixture_with_multipliers(normal_multiplier=1.0)
    doubled = _solve_normal_averaging_fixture_with_multipliers(normal_multiplier=2.0)

    assert base.averaged_normal_cost_value > 0.0
    assert doubled.averaged_normal_cost_value == pytest.approx(base.averaged_normal_cost_value)
    assert doubled.objective_value == pytest.approx(
        base.objective_value + base.averaged_normal_cost_value
    )


def test_normalized_objective_ratio_matches_legacy_multiplier_ratio() -> None:
    """The normalized default ratio should be equivalent to old (1,50,50)."""

    normalized = _solve_normal_averaging_fixture_with_multipliers(
        cons_multiplier=0.02,
        normal_multiplier=1.0,
        disaster_multiplier=1.0,
    )
    legacy = _solve_normal_averaging_fixture_with_multipliers(
        cons_multiplier=1.0,
        normal_multiplier=50.0,
        disaster_multiplier=50.0,
    )

    assert legacy.construction_cost_value == pytest.approx(
        normalized.construction_cost_value
    )
    assert legacy.averaged_normal_cost_value == pytest.approx(
        normalized.averaged_normal_cost_value
    )
    assert legacy.disaster_master_cost_value == pytest.approx(
        normalized.disaster_master_cost_value
    )
    assert legacy.objective_value == pytest.approx(50.0 * normalized.objective_value)


def test_disaster_only_mode_sets_pi_f_to_one_and_zeroes_normal_training_term() -> None:
    """Case 3 training is construction plus disaster only, not normal objective."""

    base_instance, cuts, _ = build_round_07_toy_case("master_problem_normal_averaging.yaml")
    disaster_instance = prepare_instance_for_run(base_instance, {"mode": "disaster_only"})
    direct_disaster_instance = build_disaster_only_instance(base_instance)

    assert disaster_instance.economics.pi_f == pytest.approx(1.0)
    assert direct_disaster_instance.economics.pi_f == pytest.approx(1.0)
    assert disaster_instance.metadata["benchmark_mode"] == "disaster_only"
    assert disaster_instance.metadata["station_sizing_policy"] == "unrestricted_disaster_capacity"

    _, solution = solve_master_problem(
        disaster_instance,
        cuts=cuts,
        model_name="case3_disaster_only_zero_normal_training_term",
    )

    assert solution.model_status == "OPTIMAL"
    assert solution.unweighted_average_normal_cost_value == pytest.approx(0.0)
    assert solution.averaged_normal_cost_value == pytest.approx(0.0)
    assert solution.objective_value == pytest.approx(
        solution.construction_cost_value + solution.disaster_master_cost_value
    )


def test_deterministic_mean_value_mode_collapses_normal_and_disaster_support_with_k2() -> None:
    """Case 4 must mean-value both A and B, then keep the K=2 outage budget."""

    base_instance, _, _ = build_round_07_toy_case("master_problem_normal_averaging.yaml")
    deterministic_instance = prepare_instance_for_run(
        base_instance,
        {
            "mode": "deterministic_mean_value",
            "parameter_overrides": {"ambiguity": {"k_max_outages": 2}},
        },
    )

    assert deterministic_instance.metadata["benchmark_mode"] == "deterministic_mean_value"
    assert deterministic_instance.metadata["mean_value_source_normal_support"] == [1, 2]
    assert deterministic_instance.metadata["mean_value_source_disaster_support"] == [1]
    assert deterministic_instance.sets.loaded_normal_scenarios == (1,)
    assert deterministic_instance.sets.loaded_disaster_scenarios == (1,)
    assert deterministic_instance.normal_tensors.support == (1,)
    assert deterministic_instance.disaster_tensors.support == (1,)
    assert deterministic_instance.ambiguity.k_max_outages == 2


def test_default_case4_config_uses_full_mean_value_k2_dro() -> None:
    """Default Case 4 should solve the original model on mean A/B with K=2."""

    config = _base_config(
        runtime_source="data/colleague_default_10x10",
        candidate={
            "candidate_id": "synthetic",
            "m_cons": 0.015,
            "m_normal": 1.0,
            "m_disaster": 1.25,
        },
        case="deterministic_k2",
        max_iterations=100,
        top_cuts=20,
        epsilon_cert=100.0,
        master_time_limit_seconds=300.0,
        master_mip_gap=0.01,
        separation_time_limit_seconds=120.0,
        separation_mip_gap=0.01,
        omega_bound_upper=20_000_000.0,
    )

    assert config["mode"] == "deterministic_mean_value"
    assert config["solver"] == "benders"
    assert config["selection"] == {
        "scenarios_a": list(range(1, 11)),
        "scenarios_b": list(range(1, 11)),
    }
    assert config["parameter_overrides"]["objective_multipliers"] == {
        "cons": 0.015,
        "normal": 1.0,
        "disaster": 1.25,
    }


def test_default_case_story_gate_rejects_phi1_less_than_phi3_less_than_phi2() -> None:
    """The paper-promotion gate must catch the current bad Phi ordering pattern."""

    bad_table = {
        "Case 1": {"Phi_dis": 10.0},
        "Case 2": {"Phi_dis": 30.0},
        "Case 3": {"Phi_dis": 20.0},
    }

    with pytest.raises(AssertionError, match="Phi1<Phi3<Phi2"):
        _assert_default_case_phi_story_gate(bad_table)


def test_reference_default_case_phi_story_is_promotion_safe() -> None:
    """The encoded gate documents the required default-case disaster ordering."""

    _assert_default_case_phi_story_gate(REFERENCE_TABLE_III)


def _gate_row(
    *,
    case: str,
    phi: float,
    psi: float,
    sites: int,
    coverage: str,
    open_buses: str,
    unmet: float = 0.0,
    slow: int = 80,
    fast: int = 12,
) -> dict[str, object]:
    return {
        "candidate_id": "synthetic",
        "case": case,
        "training_validation_level": "epsilon_certified",
        "normal_scenario_count": 10,
        "disaster_scenario_count": 10,
        "K": 2,
        "disaster_evaluator": "milp_worst_distribution",
        "F_unmet": unmet,
        "Psi_nor": psi,
        "Phi_dis": phi,
        "sites": sites,
        "critical_bus_coverage": coverage,
        "open_buses": open_buses,
        "slow_chargers": slow,
        "fast_chargers": fast,
        "total_chargers": slow + fast,
    }


def test_topology_gate_rejects_sparse_science_pass_candidate() -> None:
    """A numerically valid candidate should fail if the topology is too sparse."""

    gate = _story_gate(
        {"candidate_id": "synthetic", "m_cons": 0.02, "m_normal": 1.0, "m_disaster": 1.0},
        [
            _gate_row(case="proposed", phi=6_700.0, psi=63_000.0, sites=6, coverage="4/11", open_buses="3;8;14;17;28;32"),
            _gate_row(case="normal", phi=16_000.0, psi=62_500.0, sites=5, coverage="1/11", open_buses="3;6;19;30;32"),
            _gate_row(case="disaster", phi=4_700.0, psi=200_000.0, sites=9, coverage="8/11", open_buses="8;11;14;17;20;25;26;29;32", unmet=140_000.0),
            _gate_row(case="deterministic_k2", phi=7_000.0, psi=62_400.0, sites=8, coverage="3/11", open_buses="3;6;8;14;18;25;30;32"),
        ],
    )

    assert gate["science_pass"] is True
    assert gate["topology_pass"] is False
    assert gate["passes_all"] is False
    assert "case1_sites_8_to_12" in gate["failure_reasons"]
    assert "case1_critical_coverage_at_least_5" in gate["failure_reasons"]


def test_topology_gate_accepts_interpretable_default_candidate() -> None:
    """A paper-facing candidate needs both science and topology gates."""

    gate = _story_gate(
        {"candidate_id": "synthetic", "m_cons": 0.01, "m_normal": 1.0, "m_disaster": 1.25},
        [
            _gate_row(case="proposed", phi=6_400.0, psi=63_000.0, sites=9, coverage="6/11", open_buses="3;8;11;14;17;20;23;28;32", slow=110, fast=14),
            _gate_row(case="normal", phi=16_000.0, psi=62_500.0, sites=5, coverage="1/11", open_buses="3;6;19;30;32"),
            _gate_row(case="disaster", phi=4_700.0, psi=200_000.0, sites=9, coverage="8/11", open_buses="8;11;14;17;20;25;26;29;32", unmet=140_000.0),
            _gate_row(case="deterministic_k2", phi=7_000.0, psi=62_400.0, sites=8, coverage="3/11", open_buses="3;6;8;14;18;25;30;32", slow=100, fast=12),
        ],
    )

    assert gate["science_pass"] is True
    assert gate["topology_pass"] is True
    assert gate["deterministic_topology_pass"] is True
    assert gate["passes_all"] is True


def test_deterministic_topology_gate_rejects_case4_larger_than_case1() -> None:
    """The default story requires proposed to build broader capacity than deterministic K2."""

    gate = _story_gate(
        {"candidate_id": "synthetic", "m_cons": 0.015, "m_normal": 1.0, "m_disaster": 1.25},
        [
            _gate_row(case="proposed", phi=5_800.0, psi=63_000.0, sites=9, coverage="6/11", open_buses="3;8;11;14;17;20;23;28;32", slow=150, fast=12),
            _gate_row(case="normal", phi=16_000.0, psi=62_500.0, sites=5, coverage="1/11", open_buses="3;6;19;30;32"),
            _gate_row(case="disaster", phi=4_700.0, psi=200_000.0, sites=9, coverage="8/11", open_buses="8;11;14;17;20;25;26;29;32", unmet=140_000.0),
            _gate_row(case="deterministic_k2", phi=6_000.0, psi=62_400.0, sites=10, coverage="5/11", open_buses="3;6;8;11;14;17;25;28;30;32", slow=160, fast=14),
        ],
    )

    assert gate["science_pass"] is True
    assert gate["topology_pass"] is True
    assert gate["deterministic_topology_pass"] is False
    assert gate["passes_all"] is False
    assert "case1_sites_exceed_det" in gate["failure_reasons"]
    assert "case1_slow_ge_det" in gate["failure_reasons"]
    assert "case1_fast_ge_det" in gate["failure_reasons"]


def test_story_gate_rejects_case4_unmet_not_better_than_case3() -> None:
    """Case 4 should not look like the disaster-only endpoint in normal replay."""

    gate = _story_gate(
        {"candidate_id": "synthetic", "m_cons": 0.0152, "m_normal": 1.0, "m_disaster": 1.4},
        [
            _gate_row(case="proposed", phi=5_300.0, psi=63_000.0, sites=10, coverage="6/11", open_buses="3;8;11;14;17;20;23;28;32", slow=160, fast=15),
            _gate_row(case="normal", phi=16_000.0, psi=62_500.0, sites=5, coverage="1/11", open_buses="3;6;19;30;32"),
            _gate_row(case="disaster", phi=4_500.0, psi=130_000.0, sites=12, coverage="8/11", open_buses="8;11;14;17;20;25;26;29;30;32", unmet=66_000.0),
            _gate_row(case="deterministic_k2", phi=6_600.0, psi=129_000.0, sites=9, coverage="4/11", open_buses="3;6;8;14;18;25;30;32", unmet=66_000.0, slow=100, fast=13),
        ],
    )

    assert gate["science_pass"] is False
    assert gate["passes_all"] is False
    assert "case4_normal_service_better_than_case3" in gate["failure_reasons"]
