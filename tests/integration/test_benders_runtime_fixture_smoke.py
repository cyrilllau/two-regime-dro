"""Runtime smoke checks for the Round 09 full Benders engine."""

from __future__ import annotations

import builtins
import json
import os
from pathlib import Path
from unittest.mock import patch

from src.instance.canonical_instance import load_canonical_instance
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


def test_runtime_fixture_supports_multi_iteration_benders_under_raw_guard() -> None:
    """The runtime fixture should support at least one generated-cut Benders iteration."""

    instance = load_canonical_instance("data/runtime_12", critical_buses=(5, 9))
    runtime_root = (Path.cwd() / "data" / "runtime_12").resolve()
    guarded_open = _guard_runtime_raw_reads(builtins.open, runtime_root)
    before_path = Path("/tmp/round_09_runtime_master_before_cut.lp")
    after_path = Path("/tmp/round_09_runtime_master_after_cut.lp")
    log_path = Path("/tmp/round_09_runtime_iteration_log.json")

    with patch("builtins.open", new=guarded_open):
        result = run_benders_engine(
            instance,
            epsilon_cert=0.0,
            max_iterations=2,
            model_name_prefix="round_09_runtime",
            master_before_cut_lp_path=before_path,
            master_after_cut_lp_path=after_path,
            iteration_log_path=log_path,
        )

    assert result.master_before_cut_lp_path == before_path
    assert result.master_after_cut_lp_path == after_path
    assert result.iteration_log_path == log_path
    assert before_path.exists()
    assert after_path.exists()
    assert log_path.exists()
    assert len(result.generated_cut_results) >= 1
    assert len(result.iterations) >= 1
    assert result.iteration_log_artifact.generated_cut_count >= 1
    assert result.stop_reason in {"certified_exact", "certified_epsilon", "max_iterations"}
    assert tuple(result.lower_bound_sequence) == tuple(sorted(result.lower_bound_sequence))
    assert tuple(result.cut_count_sequence) == tuple(sorted(result.cut_count_sequence))
    assert result.final_solution.first_stage_solution.objective_is_pure_construction is False
    assert result.final_solution.first_stage_solution.objective_value != result.final_solution.construction_cost_value
    assert result.final_residual.max_cut_support_violation <= 1e-8
    assert result.final_residual.max_u_link_violation <= 1e-8

    artifact = json.loads(log_path.read_text(encoding="utf-8"))
    assert artifact["generated_cut_count"] >= 1
    assert artifact["iteration_count"] == len(result.iterations)
    assert artifact["stop_reason"] == result.stop_reason
