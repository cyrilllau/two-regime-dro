"""Exactness tests for the Round 05 separation MILP and its oracles."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.production.disaster_dual_paper import solve_disaster_dual_paper
from src.production.separation_milp import solve_separation_milp
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan
from src.reference.outage_enumerator import (
    derive_single_line_omega_bounds,
    enumerate_outages,
    solve_budget_support_by_enumeration,
    solve_separation_violation_by_enumeration,
)
from tests.oracle.test_disaster_primal_ref import _build_case


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _load_separation_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _build_separation_case(
    name: str,
) -> tuple[object, object, tuple[int, ...], dict[str, object]]:
    raw = _load_separation_fixture(name)
    instance, base_plan, _, scenario_id, _ = _build_case(str(raw["source_fixture"]))
    plan = base_plan
    if "plan_override" in raw:
        override = raw["plan_override"]
        plan = build_fixed_first_stage_plan(
            instance,
            z_by_bus={int(bus): int(value) for bus, value in override["z_by_bus"].items()},
            n_sl_by_bus={
                int(bus): int(value) for bus, value in override["n_sl_by_bus"].items()
            },
            n_fa_by_bus={
                int(bus): int(value) for bus, value in override["n_fa_by_bus"].items()
            },
        )
    return instance, plan, (scenario_id,), raw


@pytest.mark.parametrize(
    "fixture_name",
    [
        "separation_generic_exactness.yaml",
        "separation_mixed_reconstruction.yaml",
    ],
)
def test_separation_milp_matches_enumeration_oracle_on_tiny_cases(
    fixture_name: str,
) -> None:
    """The Round 05 separation MILP should match the exact outage-enumeration oracle."""

    instance, plan, scenario_ids, raw = _build_separation_case(fixture_name)
    alpha = float(raw["alpha"])
    lambda_by_line_id = {str(key): float(value) for key, value in raw["lambda_by_line_id"].items()}
    budget_k = int(raw["budget_k"])

    oracle = solve_separation_violation_by_enumeration(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
    )
    omega_bounds = derive_single_line_omega_bounds(
        instance,
        plan=plan,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
    )
    _, solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=omega_bounds,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
        model_name=f"separation_exactness_{fixture_name}",
    )

    assert solution.objective_value == pytest.approx(oracle.objective_value, abs=1e-8)
    assert tuple(solution.delta_by_line_id[line_id] for line_id in instance.sets.line_ids) == (
        oracle.best_pattern.values
    )
    assert solution.reconstruction_gap <= 1e-8


def test_phi_only_line_limit_case_reduces_to_phi_minus_lambda_choice() -> None:
    """The line-limit-dominated case should select outages from `phi - lambda` scores."""

    instance, plan, scenario_ids, raw = _build_separation_case(
        "separation_phi_only_line_limit.yaml"
    )
    alpha = float(raw["alpha"])
    lambda_by_line_id = {str(key): float(value) for key, value in raw["lambda_by_line_id"].items()}
    budget_k = int(raw["budget_k"])

    oracle = solve_separation_violation_by_enumeration(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
    )
    omega_bounds = derive_single_line_omega_bounds(
        instance,
        plan=plan,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
    )
    _, solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=omega_bounds,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
        model_name="separation_phi_only_case",
    )

    active_pattern_labels = [
        pattern.label
        for pattern in oracle.evaluated_patterns
        if sum(pattern.values) == 1
    ]
    active_base_values = []
    for label in active_pattern_labels:
        pattern = next(pattern for pattern in oracle.evaluated_patterns if pattern.label == label)
        sample_objective = oracle.samplewise_objective_by_pattern[label][scenario_ids[0]]
        phi_term = sum(
            oracle.average_phi_by_pattern[label][line_id] * pattern.by_line_id[line_id]
            for line_id in instance.sets.line_ids
        )
        active_base_values.append(sample_objective - phi_term)

    support_scores = {
        line_id: oracle.average_phi_by_pattern[
            next(
                pattern.label
                for pattern in oracle.evaluated_patterns
                if pattern.active_line_ids == (line_id,)
            )
        ][line_id]
        - lambda_by_line_id.get(line_id, 0.0)
        for line_id in instance.sets.line_ids
    }
    support_oracle = solve_budget_support_by_enumeration(
        instance.sets.line_ids,
        budget_k=budget_k,
        score_by_line_id=support_scores,
    )

    assert max(active_base_values) - min(active_base_values) <= 1e-8
    assert solution.objective_value == pytest.approx(oracle.objective_value, abs=1e-8)
    assert solution.objective_value == pytest.approx(
        active_base_values[0] + support_oracle.objective_value - alpha,
        abs=1e-8,
    )
    assert solution.delta_by_line_id == support_oracle.selected_pattern.by_line_id


def test_blockwise_decomposition_reconstruction_matches_mixed_case_objective() -> None:
    """At least one tiny case should reconstruct the separation objective blockwise."""

    instance, plan, scenario_ids, raw = _build_separation_case(
        "separation_mixed_reconstruction.yaml"
    )
    alpha = float(raw["alpha"])
    budget_k = int(raw["budget_k"])
    omega_bounds = derive_single_line_omega_bounds(
        instance,
        plan=plan,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
    )
    _, solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id={},
        omega_bounds_by_line_id=omega_bounds,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
        model_name="separation_mixed_reconstruction",
    )

    sample_solution = next(iter(solution.samplewise_dual_solutions.values()))
    manual_objective = (
        sample_solution.samplewise_decomposition.evaluate(
            plan=plan,
            outage=next(
                pattern
                for pattern in enumerate_outages(instance.sets.line_ids, budget_k=budget_k)
                if pattern.by_line_id == solution.delta_by_line_id
            ),
        )
        - alpha
    )

    assert solution.reconstruction_gap <= 1e-8
    assert manual_objective == pytest.approx(solution.objective_value, abs=1e-8)
    assert solution.active_groups["nu"] is True


def test_dual_group_activation_coverage_across_tiny_cases() -> None:
    """The tiny-case suite should exercise every requested paper-dual group."""

    active_groups: set[str] = set()

    for fixture_name in (
        "separation_generic_exactness.yaml",
        "separation_mixed_reconstruction.yaml",
    ):
        instance, plan, scenario_ids, raw = _build_separation_case(fixture_name)
        omega_bounds = derive_single_line_omega_bounds(
            instance,
            plan=plan,
            budget_k=int(raw["budget_k"]),
            scenario_ids=scenario_ids,
        )
        _, solution = solve_separation_milp(
            instance,
            plan=plan,
            alpha=float(raw["alpha"]),
            lambda_by_line_id={str(key): float(value) for key, value in raw["lambda_by_line_id"].items()},
            omega_bounds_by_line_id=omega_bounds,
            budget_k=int(raw["budget_k"]),
            scenario_ids=scenario_ids,
            model_name=f"separation_activation_{fixture_name}",
        )
        active_groups.update(
            group_name for group_name, is_active in solution.active_groups.items() if is_active
        )

    instance, plan, scenario_ids, raw = _build_separation_case("separation_activation_budget2.yaml")
    for pattern in enumerate_outages(instance.sets.line_ids, budget_k=int(raw["budget_k"])):
        _, paper_solution = solve_disaster_dual_paper(
            instance,
            plan=plan,
            outage=pattern,
            scenario_id=scenario_ids[0],
            model_name=f"activation_scan_{pattern.label}",
        )
        if any(abs(value) > 1e-8 for value in paper_solution.eq28_slow_values.values()) or any(
            abs(value) > 1e-8 for value in paper_solution.eq28_fast_values.values()
        ):
            active_groups.add("eta")
        if any(abs(value) > 1e-8 for value in paper_solution.eq29_slow_values.values()) or any(
            abs(value) > 1e-8 for value in paper_solution.eq29_fast_values.values()
        ):
            active_groups.add("mu")
        if any(abs(value) > 1e-8 for value in paper_solution.eq30_slow_values.values()) or any(
            abs(value) > 1e-8 for value in paper_solution.eq30_fast_values.values()
        ):
            active_groups.add("nu")
        if any(abs(value) > 1e-8 for value in paper_solution.eq31_sigma_values.values()):
            active_groups.add("sigma")
        if any(abs(value) > 1e-8 for value in paper_solution.eq32_upper_values.values()):
            active_groups.add("rho_upper")
        if any(abs(value) > 1e-8 for value in paper_solution.eq32_lower_values.values()):
            active_groups.add("rho_lower")

    assert active_groups >= {"eta", "mu", "nu", "sigma", "rho_upper", "rho_lower"}
