"""Smoke coverage for the Round 12.5 convergence diagnostic pack."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_convergence_diagnostic_pack_smoke_produces_core_outputs(tmp_path: Path) -> None:
    """The diagnostic script should emit baseline snapshot, CSVs, logs, figures, and a report."""

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
    ]
    subprocess.run(command, check=True, cwd=Path.cwd())

    assert (baseline_dir / "summary.csv").exists()
    assert (baseline_dir / "figures").exists()
    assert (baseline_dir / "plans").exists()

    assert (output_root / "summary.csv").exists()
    assert (output_root / "failures.csv").exists()
    assert (output_root / "logs" / "smoke_normal_only_exact_zero_diagnostic.json").exists()
    assert (output_root / "logs" / "smoke_integrated_epsilon_stop_diagnostic.json").exists()
    assert (output_root / "logs" / "smoke_integrated_epsilon_stop_iteration_log.json").exists()
    assert (output_root / "logs" / "smoke_integrated_max_iter_diagnostic.json").exists()
    assert (output_root / "figures" / "validation_category_overview.png").exists()
    assert (output_root / "figures" / "violation_vs_iteration_budget.png").exists()
    assert report_path.exists()
