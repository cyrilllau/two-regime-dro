"""Runtime-fixture smoke test for the Round 05 separation MILP."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.instance.canonical_instance import load_canonical_instance
from src.production.separation_milp import solve_separation_milp
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan
from src.reference.outage_enumerator import (
    derive_single_line_omega_bounds,
    solve_budget_support_by_enumeration,
    solve_budget_support_top_k,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_separation_milp_smoke_runs_on_runtime_fixture(tmp_path: Path) -> None:
    """The separation MILP should build and solve on the canonical runtime fixture."""

    instance = load_canonical_instance(
        REPO_ROOT / "data/runtime_12",
        critical_buses=(5, 9),
    )
    plan = build_fixed_first_stage_plan(instance)
    lambda_by_line_id = {line_id: 0.0 for line_id in instance.sets.line_ids}
    omega_bounds = derive_single_line_omega_bounds(
        instance,
        plan=plan,
        budget_k=instance.ambiguity.k_max_outages,
        safety_factor=2.0,
    )
    separation_model, solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=0.0,
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=omega_bounds,
        budget_k=instance.ambiguity.k_max_outages,
        model_name="runtime_fixture_separation_round_05",
    )
    dump_path = dump_model_artifact(
        separation_model,
        tmp_path / "runtime_fixture_separation_round_05.lp",
    )

    score_by_line_id = {
        line_id: solution.omega_by_line_id[line_id] - lambda_by_line_id[line_id]
        for line_id in instance.sets.line_ids
    }
    support_enumeration = solve_budget_support_by_enumeration(
        instance.sets.line_ids,
        budget_k=instance.ambiguity.k_max_outages,
        score_by_line_id=score_by_line_id,
    )
    support_top_k = solve_budget_support_top_k(
        instance.sets.line_ids,
        budget_k=instance.ambiguity.k_max_outages,
        score_by_line_id=score_by_line_id,
    )

    assert solution.model_status == "OPTIMAL"
    assert sum(solution.delta_by_line_id.values()) <= instance.ambiguity.k_max_outages
    assert solution.reconstruction_gap <= 1e-6
    assert sum(solution.tau_by_line_id.values()) - solution.lambda_delta_value == pytest.approx(
        support_enumeration.objective_value,
        abs=1e-6,
    )
    assert support_enumeration.objective_value == pytest.approx(
        support_top_k.objective_value,
        abs=1e-6,
    )
    assert dump_path.exists()
