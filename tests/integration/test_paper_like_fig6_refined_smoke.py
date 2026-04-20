"""Smoke coverage for the refined paper-like exact calibration sweep."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_paper_like_fig6_refined_smoke_produces_outputs(tmp_path: Path) -> None:
    output_root = tmp_path / "refined"
    report_path = tmp_path / "paper_like_fig6_refined_pack.md"
    command = [
        sys.executable,
        "scripts/run_paper_like_fig6_refined.py",
        "--manifest",
        "configs/experiments/paper_like_fig6_refined.yaml",
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
    assert (output_root / "plans" / "normal_only_paper_like_refined_scale_055_plan.csv").exists()
    assert (output_root / "plans" / "normal_only_paper_like_refined_scale_045_plan.csv").exists()
    assert (output_root / "plans" / "paper_case1_target_semantics_plan.csv").exists()
    assert report_path.exists()
