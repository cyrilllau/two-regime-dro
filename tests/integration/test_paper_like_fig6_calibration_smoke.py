"""Smoke coverage for the paper-like Fig. 6 calibration pipeline."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_paper_like_fig6_calibration_smoke_produces_core_outputs(tmp_path: Path) -> None:
    output_root = tmp_path / "calibration"
    report_path = tmp_path / "paper_like_fig6_calibration_pack.md"
    command = [
        sys.executable,
        "scripts/run_paper_like_fig6_calibration.py",
        "--config",
        "tests/fixtures/paper_like_fig6_calibration_smoke.yaml",
        "--output-root",
        str(output_root),
        "--report-path",
        str(report_path),
        "--skip-figures",
    ]
    subprocess.run(command, check=True, cwd=Path.cwd())

    assert (output_root / "summary.csv").exists()
    assert (output_root / "failures.csv").exists()
    assert (output_root / "metadata.json").exists()
    assert (output_root / "plans" / "S0_baseline_plan.csv").exists()
    assert (output_root / "plans" / "normal_only_paper_like_tuned_plan.csv").exists()
    assert (output_root / "plans" / "paper_case1_target_semantics_plan.csv").exists()
    assert (output_root / "logs" / "integrated_mainline_paper_like_tuned_run.json").exists()
    assert report_path.exists()
