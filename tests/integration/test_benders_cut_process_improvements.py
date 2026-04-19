"""Smoke coverage for the Round 13 cut-process diagnostics."""

from __future__ import annotations

import csv
from pathlib import Path
import subprocess
import sys


def test_cut_process_diagnostic_pack_smoke_produces_required_outputs(tmp_path: Path) -> None:
    """The Round 13 script should emit summary, failures, cut diagnostics, logs, figures, and report."""

    output_root = tmp_path / "results"
    report_path = tmp_path / "cut_process_diagnostic_pack.md"
    command = [
        sys.executable,
        "scripts/run_cut_process_diagnostics.py",
        "--matrix",
        "tests/fixtures/cut_process_smoke.yaml",
        "--output-root",
        str(output_root),
        "--report-path",
        str(report_path),
    ]
    subprocess.run(command, check=True, cwd=Path.cwd())

    assert (output_root / "summary.csv").exists()
    assert (output_root / "failures.csv").exists()
    assert (output_root / "cut_diagnostics.csv").exists()
    assert (output_root / "figures" / "cut_process_violation_summary.png").exists()
    assert (output_root / "logs" / "smoke_integrated_eps20000_i2_k2_a1b1__baseline_iteration_log.json").exists()
    assert report_path.exists()

    with (output_root / "summary.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = {row["run_id"]: row for row in csv.DictReader(handle)}
    assert rows["smoke_integrated_eps20000_i2_k2_a1b1__baseline"]["variant"] == "baseline"
    assert rows["smoke_integrated_eps20000_i2_k2_a1b1__improved"]["variant"] == "improved"
    assert rows["smoke_integrated_eps20000_i2_k2_a1b1__improved"]["cut_signature_dedup_enabled"] == "True"
    assert rows["smoke_disaster_only_exact_i2_k2_a1b1__baseline"]["diagnosis_label"] == "max_iter_noncert"

    with (output_root / "cut_diagnostics.csv").open("r", encoding="utf-8", newline="") as handle:
        cut_rows = list(csv.DictReader(handle))
    assert cut_rows
    required_columns = {
        "run_id",
        "cut_id",
        "source_outage_vector",
        "cut_signature_hash",
        "old_master_violation_at_source",
        "first_stage_plan_changed",
        "alpha_lambda_only_change",
        "gamma_n_sl_nonzero_count",
        "phi_nonzero_count",
        "cut_addition_status",
    }
    assert required_columns.issubset(set(cut_rows[0].keys()))
