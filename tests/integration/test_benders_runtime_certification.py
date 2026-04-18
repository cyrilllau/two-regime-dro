"""Certified runtime-like Benders regression for Round 10."""

from __future__ import annotations

import builtins
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.instance.canonical_instance import load_canonical_instance
from src.instance.selection import build_runtime_selection
from src.production.benders_engine import run_benders_engine


def _guard_runtime_raw_reads(real_open, runtime_root: Path):
    """Reject any attempted raw runtime-data reads during production build/solve."""

    def wrapped(file, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)):
            path = Path(file).resolve()
            if path == runtime_root or runtime_root in path.parents:
                raise AssertionError(
                    f"Production model layer attempted to read raw runtime data path: {path}"
                )
        return real_open(file, *args, **kwargs)

    return wrapped


def _load_runtime_certified_fixture() -> dict[str, object]:
    return json.loads(
        (Path("tests/fixtures") / "benders_runtime_certified_small.yaml").read_text(
            encoding="utf-8"
        )
    )


def test_runtime_like_small_selection_reaches_certified_epsilon_under_raw_guard() -> None:
    """A small explicit runtime selection should certify under the production Benders engine."""

    raw = _load_runtime_certified_fixture()
    selection = build_runtime_selection(
        scenarios_a=raw["selection"]["scenarios_a"],
        scenarios_b=raw["selection"]["scenarios_b"],
        source="round_10_runtime_certified_small",
    )
    instance = load_canonical_instance(
        raw["runtime_dir"],
        critical_buses=tuple(int(bus) for bus in raw["critical_buses"]),
        selection=selection,
    )
    runtime_root = (Path.cwd() / raw["runtime_dir"]).resolve()
    guarded_open = _guard_runtime_raw_reads(builtins.open, runtime_root)
    before_path = Path("/tmp/round_10_runtime_certified_master_before_cut.lp")
    after_path = Path("/tmp/round_10_runtime_certified_master_after_cut.lp")
    log_path = Path("/tmp/round_10_runtime_certified_iteration_log.json")

    with patch("builtins.open", new=guarded_open):
        result = run_benders_engine(
            instance,
            epsilon_cert=float(raw["epsilon_cert"]),
            max_iterations=int(raw["max_iterations"]),
            model_name_prefix="round_10_runtime_certified",
            master_before_cut_lp_path=before_path,
            master_after_cut_lp_path=after_path,
            iteration_log_path=log_path,
        )

    expected = raw["expected"]
    assert result.stop_reason == expected["stop_reason"]
    assert len(result.iterations) == int(expected["iteration_count"])
    assert len(result.generated_cut_results) == int(expected["generated_cut_count"])
    assert result.lower_bound_sequence == pytest.approx(
        tuple(float(value) for value in expected["lower_bound_sequence"])
    )
    assert result.cut_count_sequence == tuple(int(value) for value in expected["cut_count_sequence"])
    assert result.certificate.final_violation_upper_bound == pytest.approx(
        float(expected["final_violation_upper_bound"])
    )
    assert result.certificate.sampled_problem_gap_bound == pytest.approx(
        float(expected["sampled_problem_gap_bound"])
    )
    assert result.certificate.final_violation_upper_bound <= float(raw["epsilon_cert"])
    assert result.master_before_cut_lp_path == before_path
    assert result.master_after_cut_lp_path == after_path
    assert result.iteration_log_path == log_path
    assert before_path.exists()
    assert after_path.exists()
    assert log_path.exists()
    assert result.final_solution.first_stage_solution.objective_is_pure_construction is False
    assert result.final_solution.first_stage_solution.objective_value != pytest.approx(
        result.final_solution.construction_cost_value
    )
    assert result.final_residual.max_cut_support_violation <= 1e-8
    assert result.final_residual.max_u_link_violation <= 1e-8
