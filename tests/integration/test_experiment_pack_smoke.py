"""Smoke coverage for the Round 11 experiment pack scripts."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_experiment_pack_smoke_produces_core_outputs(tmp_path: Path) -> None:
    """The packaging script should emit summary, plans, logs, and a report on a tiny subset."""

    output_root = tmp_path / "results"
    report_path = tmp_path / "experiment_interpretation_pack.md"
    command = [
        sys.executable,
        "scripts/run_experiment_pack.py",
        "--manifest",
        "tests/fixtures/experiment_pack_smoke.yaml",
        "--output-root",
        str(output_root),
        "--report-path",
        str(report_path),
        "--skip-figures",
    ]
    subprocess.run(command, check=True, cwd=Path.cwd())

    assert (output_root / "summary.csv").exists()
    assert (output_root / "plans" / "integrated_mainline_certified_small_smoke_plan.csv").exists()
    assert (output_root / "plans" / "normal_only_certified_small_smoke_plan.csv").exists()
    assert (output_root / "logs" / "integrated_mainline_certified_small_smoke_run.json").exists()
    assert (output_root / "logs" / "integrated_mainline_certified_small_smoke_iteration_log.json").exists()
    assert (output_root / "logs" / "normal_only_certified_small_smoke_run.json").exists()
    assert report_path.exists()
