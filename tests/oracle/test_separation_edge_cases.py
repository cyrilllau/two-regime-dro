"""Edge-case and regression-hardening checks for the separation MILP."""

from __future__ import annotations

import pytest

from src.production.separation_milp import solve_separation_milp
from src.reference.outage_enumerator import (
    derive_omega_bounds_from_enumeration,
    derive_single_line_omega_bounds,
    enumerate_outages,
    solve_budget_support_by_enumeration,
    solve_separation_violation_by_enumeration,
)
from tests.oracle.test_disaster_primal_ref import _build_case
from tests.oracle.test_separation_exactness import _build_separation_case


def test_separation_k_zero_matches_zero_outage_enumeration() -> None:
    """When `K = 0`, the separation MILP should force the all-zero outage pattern."""

    instance, plan, scenario_ids, raw = _build_separation_case("separation_generic_exactness.yaml")
    alpha = float(raw["alpha"])
    lambda_by_line_id = {str(key): float(value) for key, value in raw["lambda_by_line_id"].items()}

    oracle = solve_separation_violation_by_enumeration(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        budget_k=0,
        scenario_ids=scenario_ids,
    )
    omega_bounds = derive_single_line_omega_bounds(
        instance,
        plan=plan,
        budget_k=0,
        scenario_ids=scenario_ids,
    )
    _, solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=omega_bounds,
        budget_k=0,
        scenario_ids=scenario_ids,
        model_name="round_05_5_k_zero_separation",
    )

    assert solution.objective_value == pytest.approx(oracle.objective_value, abs=1e-8)
    assert all(value == 0 for value in solution.delta_by_line_id.values())
    assert oracle.best_pattern.values == tuple(0 for _ in instance.sets.line_ids)


def test_separation_tie_optimum_accepts_any_best_outage_pattern() -> None:
    """Tie-optimum cases should match the best value without requiring a unique outage identity."""

    instance, plan, _, scenario_id, _ = _build_case("disaster_primal_failed_line.yaml")
    scenario_ids = (scenario_id,)
    alpha = 5.0
    lambda_by_line_id = {line_id: 0.0 for line_id in instance.sets.line_ids}
    budget_k = 1

    oracle = solve_separation_violation_by_enumeration(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
    )
    optimal_patterns = [
        pattern.by_line_id
        for pattern in oracle.evaluated_patterns
        if oracle.objective_by_pattern[pattern.label]
        >= oracle.objective_value - 1e-8
    ]
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
        model_name="round_05_5_tie_optimum_separation",
    )

    assert len(optimal_patterns) > 1
    assert solution.objective_value == pytest.approx(oracle.objective_value, abs=1e-8)
    assert solution.delta_by_line_id in optimal_patterns


def test_exact_and_inflated_valid_bounds_preserve_optimal_violation_value() -> None:
    """Inflating valid omega bounds should not change the exact tiny-case optimum."""

    instance, plan, scenario_ids, raw = _build_separation_case("separation_generic_exactness.yaml")
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
    exact_bounds = derive_omega_bounds_from_enumeration(oracle)
    inflated_bounds = {
        line_id: (lower, max(upper * 3.0, upper + 1.0))
        for line_id, (lower, upper) in exact_bounds.items()
    }

    _, exact_solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=exact_bounds,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
        model_name="round_05_5_exact_bounds",
    )
    _, inflated_solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=inflated_bounds,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
        model_name="round_05_5_inflated_bounds",
    )

    assert exact_solution.objective_value == pytest.approx(oracle.objective_value, abs=1e-8)
    assert inflated_solution.objective_value == pytest.approx(oracle.objective_value, abs=1e-8)
    assert inflated_solution.objective_value == pytest.approx(
        exact_solution.objective_value,
        abs=1e-8,
    )
    assert inflated_solution.delta_by_line_id == exact_solution.delta_by_line_id


def test_phi_sign_regression_preserves_tau_minus_lambda_interpretation() -> None:
    """The outage-dependent part should still reduce to `tau - lambda^T delta` on a phi-only case."""

    instance, plan, scenario_ids, raw = _build_separation_case(
        "separation_phi_only_line_limit.yaml"
    )
    alpha = float(raw["alpha"])
    lambda_by_line_id = {str(key): float(value) for key, value in raw["lambda_by_line_id"].items()}
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
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=omega_bounds,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
        model_name="round_05_5_phi_sign_regression",
    )

    support = solve_budget_support_by_enumeration(
        instance.sets.line_ids,
        budget_k=budget_k,
        score_by_line_id={
            line_id: solution.omega_by_line_id[line_id] - lambda_by_line_id.get(line_id, 0.0)
            for line_id in instance.sets.line_ids
        },
    )

    assert solution.delta_by_line_id == support.selected_pattern.by_line_id
    assert solution.tau_sum - solution.lambda_delta_value == pytest.approx(
        support.objective_value,
        abs=1e-8,
    )
    assert solution.reconstructed_objective == pytest.approx(
        solution.average_base_value + support.objective_value - alpha,
        abs=1e-8,
    )


def test_edge_harness_rechecks_blockwise_reconstruction_on_mixed_case() -> None:
    """The new validation harness should still re-check `beta/gamma/phi` reconstruction."""

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
        model_name="round_05_5_blockwise_recheck",
    )

    pattern = next(
        pattern
        for pattern in enumerate_outages(instance.sets.line_ids, budget_k=budget_k)
        if pattern.by_line_id == solution.delta_by_line_id
    )
    sample_solution = next(iter(solution.samplewise_dual_solutions.values()))
    manual_objective = sample_solution.samplewise_decomposition.evaluate(
        plan=plan,
        outage=pattern,
    ) - alpha

    assert solution.reconstruction_gap <= 1e-8
    assert manual_objective == pytest.approx(solution.objective_value, abs=1e-8)
