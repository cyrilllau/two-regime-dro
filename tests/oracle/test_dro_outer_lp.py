"""Oracle tests for the tiny finite outer-DRO LP."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.reference.dro_outer_lp_oracle import solve_dro_outer_lp_oracle
from src.reference.outage_enumerator import enumerate_outages


def test_outer_dro_lp_oracle_matches_hand_computed_two_line_case(tmp_path: Path) -> None:
    """A tiny two-line case should match the hand-derived worst-case distribution."""

    patterns = enumerate_outages(("line_1", "line_2"), budget_k=1)
    oracle_model, solution = solve_dro_outer_lp_oracle(
        line_ids=("line_1", "line_2"),
        fp_by_line_id={"line_1": 0.5, "line_2": 0.25},
        value_by_pattern={
            "delta_00": 0.0,
            "delta_10": 10.0,
            "delta_01": 8.0,
        },
        outage_patterns=patterns,
        model_name="tiny_outer_dro_oracle",
    )
    dump_path = dump_model_artifact(oracle_model, tmp_path / "tiny_outer_dro_oracle.lp")

    assert solution.objective_value == pytest.approx(7.0, abs=1e-9)
    assert solution.probability_by_pattern["delta_10"] == pytest.approx(0.5, abs=1e-9)
    assert solution.probability_by_pattern["delta_01"] == pytest.approx(0.25, abs=1e-9)
    assert solution.probability_by_pattern["delta_00"] == pytest.approx(0.25, abs=1e-9)
    assert solution.linewise_marginals == pytest.approx(
        {"line_1": 0.5, "line_2": 0.25},
        abs=1e-9,
    )
    assert dump_path.exists()
