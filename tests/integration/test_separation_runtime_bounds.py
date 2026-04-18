"""Runtime-bound validation for the Round 05 separation smoke path."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.instance.canonical_instance import load_canonical_instance
from src.production.separation_milp import solve_separation_milp
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan
from src.reference.outage_enumerator import derive_single_line_omega_bounds


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_smoke_omega_values_respect_supplied_bounds_and_report_slacks(
    tmp_path: Path,
) -> None:
    """Solved runtime-smoke omega values should stay within the supplied conservative bounds."""

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
        model_name="runtime_fixture_separation_round_05_5_bounds",
    )
    dump_path = dump_model_artifact(
        separation_model,
        tmp_path / "runtime_fixture_separation_round_05_5_bounds.lp",
    )

    for line_id in instance.sets.line_ids:
        lower, upper = omega_bounds[line_id]
        assert solution.omega_by_line_id[line_id] >= lower - 1e-9
        assert solution.omega_by_line_id[line_id] <= upper + 1e-9
        assert solution.omega_lower_slack_by_line_id[line_id] == pytest.approx(
            solution.omega_by_line_id[line_id] - lower,
            abs=1e-9,
        )
        assert solution.omega_upper_slack_by_line_id[line_id] == pytest.approx(
            upper - solution.omega_by_line_id[line_id],
            abs=1e-9,
        )

    assert solution.max_omega_bound_violation <= 1e-9
    assert min(solution.omega_upper_slack_by_line_id.values()) == pytest.approx(0.0, abs=1e-9)
    assert dump_path.exists()
