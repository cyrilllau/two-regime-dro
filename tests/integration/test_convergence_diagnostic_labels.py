"""Labeling checks for the Round 12.5 convergence diagnostic pack."""

from __future__ import annotations

import csv
from pathlib import Path
import subprocess
import sys


def test_convergence_diagnostic_labels_cover_exact_epsilon_and_max_iter(tmp_path: Path) -> None:
    """The smoke fixture should produce the three required diagnosis categories."""

    output_root = tmp_path / "results"
    baseline_dir = tmp_path / "baseline"
    report_path = tmp_path / "convergence_diagnostic_pack.md"
    command = [
        sys.executable,
        "scripts/run_convergence_diagnostics.py",
        "--manifest",
        "tests/fixtures/convergence_diagnostic_smoke.yaml",
        "--output-root",
        str(output_root),
        "--baseline-dir",
        str(baseline_dir),
        "--report-path",
        str(report_path),
        "--skip-figures",
    ]
    subprocess.run(command, check=True, cwd=Path.cwd())

    with (output_root / "summary.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = {row["run_id"]: row for row in csv.DictReader(handle)}

    assert rows["smoke_normal_only_exact_zero"]["diagnosis_label"] == "exact_zero"
    assert rows["smoke_normal_only_exact_zero"]["validation_level"] == "exact"

    assert rows["smoke_integrated_epsilon_stop"]["diagnosis_label"] == "epsilon_stop"
    assert rows["smoke_integrated_epsilon_stop"]["validation_level"] == "epsilon_certified"

    assert rows["smoke_integrated_max_iter"]["diagnosis_label"] == "max_iter_noncert"
    assert rows["smoke_integrated_max_iter"]["validation_level"] == "smoke_only"

    with (output_root / "failures.csv").open("r", encoding="utf-8", newline="") as handle:
        failure_rows = list(csv.DictReader(handle))
    failure_ids = {row["run_id"] for row in failure_rows}
    assert "smoke_integrated_max_iter" in failure_ids
    assert "smoke_integrated_epsilon_stop" not in failure_ids
