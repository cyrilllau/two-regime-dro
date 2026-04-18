"""Independent disaster exact-oracle checks for Round 10."""

from __future__ import annotations

from src.reference.disaster_exact_oracle import solve_disaster_exact_oracle
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan
from tests.oracle.test_cut_factory import build_round_08_case


def test_independent_disaster_exact_oracle_matches_expected_pattern_values() -> None:
    """The primal-based disaster oracle should expose exact tiny pattern values."""

    instance, _, _, _, raw = build_round_08_case("disaster_exact_crosscheck_three_bus.yaml")
    plan_raw = raw["oracle_plan"]
    expected = raw["expected_disaster_exact"]
    plan = build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(bus): int(value) for bus, value in plan_raw["z_by_bus"].items()},
        n_sl_by_bus={int(bus): int(value) for bus, value in plan_raw["n_sl_by_bus"].items()},
        n_fa_by_bus={int(bus): int(value) for bus, value in plan_raw["n_fa_by_bus"].items()},
    )

    _, result = solve_disaster_exact_oracle(
        instance,
        plan=plan,
        model_name_prefix="round_10_disaster_exact",
    )

    assert result.value_by_pattern == {
        label: float(value) for label, value in expected["value_by_pattern"].items()
    }
    assert result.outer_dro_value == float(expected["outer_dro_value"])
    assert result.weighted_objective_value == float(expected["weighted_objective_value"])
    for label, probability in expected["required_probability_by_pattern"].items():
        assert result.worst_case_probability_by_pattern[label] == float(probability)
    for line_id, marginal in expected["required_linewise_marginals"].items():
        assert result.linewise_marginals[line_id] == float(marginal)
    assert result.samplewise_primal_objective_by_pattern["delta_01"][1] == 500.0
    assert "delta_01" in result.active_worst_case_patterns
