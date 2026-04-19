"""Smoke coverage for the Round 14 frozen baseline report packaging."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_frozen_baseline_report_packaging_smoke(tmp_path: Path) -> None:
    """The Round 14 builder should emit archive, tables, figures, tex, log, and a round report."""

    archive_root = tmp_path / "archive"
    report_root = tmp_path / "reports"
    command = [
        sys.executable,
        "scripts/build_frozen_baseline_report.py",
        "--config",
        "configs/reports/frozen_baseline_review.yaml",
        "--archive-root",
        str(archive_root),
        "--report-root",
        str(report_root),
        "--skip-latex",
        "--skip-anchor-reruns",
        "--skip-certified-small-regeneration",
    ]
    subprocess.run(command, check=True, cwd=Path.cwd())

    assert (archive_root / "docs" / "reports" / "round_12_report.md").exists()
    assert (archive_root / "reports" / "paper_style_experiment_pack.md").exists()
    assert (report_root / "frozen_baseline_review_report.tex").exists()
    assert (report_root / "frozen_baseline_review_report.log").exists()
    assert (report_root / "round_14_report.md").exists()
    assert (report_root / "frozen_baseline_review_metadata.json").exists()
    assert (report_root / "tables" / "validation_chain_summary.csv").exists()
    assert (report_root / "tables" / "validation_chain_summary.tex").exists()
    assert (report_root / "tables" / "run_inventory.csv").exists()
    assert (report_root / "tables" / "objective_components.csv").exists()
    assert (report_root / "tables" / "noncertified_runs.csv").exists()
    assert (report_root / "frozen_baseline_review_appendix.csv").exists()
    assert (report_root / "figures" / "baseline" / "validation_status_overview.png").exists()
    assert (report_root / "figures" / "baseline" / "objective_components_by_run.png").exists()
    assert (report_root / "figures" / "baseline" / "benchmark_comparison_safe.png").exists()
    assert (report_root / "figures" / "baseline" / "ieee33_runtime12_directional_maps.png").exists()
    assert (report_root / "figures" / "baseline" / "ieee33_paper_like_maps_case123.png").exists()
    assert (report_root / "figures" / "baseline" / "ieee33_paper_like_maps_case4_56.png").exists()
    assert (report_root / "figures" / "baseline" / "iteration_trace_selected.png").exists()
    assert (report_root / "figures" / "baseline" / "convergence_diagnostics_overview.png").exists()
    assert (report_root / "figures" / "baseline" / "cut_process_diagnostics_overview.png").exists()
