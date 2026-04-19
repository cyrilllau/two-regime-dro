"""Failure/non-convergence logging coverage for the Round 12 experiment pack."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys

import yaml


def test_experiment_pack_logs_max_iteration_runs_to_failures_csv(tmp_path: Path) -> None:
    """A non-certified smoke run should remain visible in failures.csv, run JSON, and report."""

    output_root = tmp_path / "results"
    report_path = tmp_path / "paper_style_experiment_pack.md"
    manifest_path = tmp_path / "failure_logging_manifest.yaml"
    manifest = {
        "critical_buses_config": "configs/critical_buses_paper_fig2.yaml",
        "output_root": "results",
        "report_path": "docs/analysis_packs/paper_style_experiment_pack.md",
        "runs": [
            {
                "run_id": "runtime12_failure_logging_smoke",
                "family_name": "failure_logging_family",
                "case_name": "runtime12_failure_logging_smoke",
                "runtime_source": "data/runtime_12",
                "selection_preset": "default_small",
                "mode": "integrated_mainline",
                "solver": "benders",
                "parameter_regime": "runtime12_directional",
                "benders": {
                    "epsilon_cert": 0.0,
                    "max_iterations": 1,
                },
            }
        ],
    }
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    command = [
        sys.executable,
        "scripts/run_experiment_pack.py",
        "--manifest",
        str(manifest_path),
        "--output-root",
        str(output_root),
        "--report-path",
        str(report_path),
        "--skip-figures",
    ]
    subprocess.run(command, check=True, cwd=Path.cwd())

    failures_path = output_root / "failures.csv"
    assert failures_path.exists()
    with failures_path.open("r", encoding="utf-8", newline="") as handle:
        failure_rows = list(csv.DictReader(handle))
    assert len(failure_rows) == 1
    assert failure_rows[0]["run_id"] == "runtime12_failure_logging_smoke"
    assert failure_rows[0]["validation_level"] == "smoke_only"
    assert failure_rows[0]["stop_reason"] == "max_iterations"

    run_log_path = output_root / "logs" / "runtime12_failure_logging_smoke_run.json"
    payload = json.loads(run_log_path.read_text(encoding="utf-8"))
    assert payload["validation_level"] == "smoke_only"
    assert payload["stop_reason"] == "max_iterations"
    assert payload["failure_record"]["run_id"] == "runtime12_failure_logging_smoke"

    report_text = report_path.read_text(encoding="utf-8")
    assert "runtime12_failure_logging_smoke" in report_text
    assert "max_iterations" in report_text
