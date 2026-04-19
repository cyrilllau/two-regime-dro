"""Run the Round 12.5 convergence diagnostic pack."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

from diagnostic_utils import (
    clear_output_directory,
    ensure_directory,
    execute_diagnostic_run,
    load_critical_buses,
    load_diagnostic_manifest,
    rows_to_markdown_table,
    snapshot_round12_baseline,
    summarize_run_logs,
    write_failures_csv,
    write_summary_csv,
)
from make_convergence_diagnostic_figures import generate_figures


def _render_lines(items: Iterable[str]) -> str:
    materialized = [item for item in items if item]
    if not materialized:
        return "- none"
    return "\n".join(f"- {item}" for item in materialized)


def _write_report(
    *,
    report_path: str | Path,
    baseline_dir: str | Path,
    summary_rows,
    failure_rows,
    figure_paths: Sequence[str],
    log_paths: Sequence[str],
) -> Path:
    exact_rows = [row for row in summary_rows if row.diagnosis_label == "exact_zero"]
    epsilon_rows = [row for row in summary_rows if row.diagnosis_label == "epsilon_stop"]
    max_iter_rows = [row for row in summary_rows if row.diagnosis_label == "max_iter_noncert"]

    matrix_rows = [
        {
            "run_id": row.run_id,
            "case_name": row.case_name,
            "parameter_regime": row.parameter_regime,
            "epsilon_cert": row.epsilon_cert,
            "max_iterations": row.max_iterations,
            "A_selected": row.A_selected,
            "B_selected": row.B_selected,
            "K": row.K,
        }
        for row in summary_rows
    ]

    validation_rows = [
        {
            "run_id": row.run_id,
            "validation_level": row.validation_level,
            "diagnosis_label": row.diagnosis_label,
            "stop_reason": row.stop_reason,
            "solver_status": row.solver_status,
            "iteration_count": row.iteration_count,
            "cut_count": row.cut_count,
            "final_violation_upper_bound": row.final_violation_upper_bound,
        }
        for row in summary_rows
    ]

    dominant_runtime_counts = {"master": 0, "separation": 0, "dual": 0}
    for row in summary_rows:
        values = {
            "master": float(row.master_runtime_sec_total),
            "separation": float(row.separation_runtime_sec_total),
            "dual": float(row.dual_resolve_runtime_sec_total),
        }
        dominant_runtime_counts[max(values, key=values.get)] += 1

    safe_smoke_interpretation = [
        "A max-iteration smoke run with a budget of 2 is usually an intentionally bounded packaging run, not proof of an algorithmic bug.",
        "A max-iteration run that still has nontrivial violation after 10 or 20 iterations is stronger evidence that the current cut process is struggling on that benchmark.",
        "An epsilon stop with nonzero violation is not exact convergence; it is a certificate relative to the chosen epsilon.",
    ]
    bottleneck_ranking = sorted(
        dominant_runtime_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    )
    bottleneck_lines = [
        f"{index}. `{name}` dominated {count} run(s)."
        for index, (name, count) in enumerate(bottleneck_ranking, start=1)
    ]

    report = f"""# Convergence Diagnostic Pack

## Scope
- This pack preserves the validated optimization chain and diagnoses convergence behavior only.
- Round 12 outputs were snapshotted before any new diagnostic runs.
- `critical_buses` remained explicit and unchanged.

## Baseline Snapshot
- Saved baseline under `{baseline_dir}`
- Included:
  - `summary.csv`
  - `failures.csv`
  - `round_12_report.md`
  - `paper_style_experiment_pack.md`
  - `figures/*`
  - `plans/*`

## Diagnostic Matrix
{rows_to_markdown_table(matrix_rows, ['run_id', 'case_name', 'parameter_regime', 'epsilon_cert', 'max_iterations', 'A_selected', 'B_selected', 'K'])}

## Validation / Diagnosis Summary
{rows_to_markdown_table(validation_rows, ['run_id', 'validation_level', 'diagnosis_label', 'stop_reason', 'solver_status', 'iteration_count', 'cut_count', 'final_violation_upper_bound'])}

## Key Findings
### exact_zero
{_render_lines(f"`{row.run_id}`" for row in exact_rows)}

### epsilon_stop
{_render_lines(f"`{row.run_id}`: final violation `{row.final_violation_upper_bound}` <= epsilon `{row.epsilon_cert}`" for row in epsilon_rows)}

### max_iter_noncert
{_render_lines(f"`{row.run_id}`: final violation `{row.final_violation_upper_bound}` after `{row.iteration_count}` iteration(s)" for row in max_iter_rows)}

## Why The Smoke-Only Runs Are Or Are Not Alarming
{_render_lines(safe_smoke_interpretation)}

## Suspected Bottlenecks
{_render_lines(bottleneck_lines)}

## Failure / Non-Certification Table
{rows_to_markdown_table([row.to_csv_row() for row in failure_rows], ['run_id', 'case_name', 'parameter_regime', 'validation_level', 'diagnosis_label', 'stop_reason', 'solver_status', 'iteration_count', 'cut_count', 'final_violation_upper_bound', 'message']) if failure_rows else '- none'}

## Recommendation For The Next Algorithm Round
- The current diagnostic pack suggests focusing next on cut-process effectiveness rather than data loading or model correctness.
- The strongest candidates are:
  1. analyze repeated outage or near-duplicate cut patterns
  2. improve the effectiveness of generated cuts under larger support / larger `K`
  3. revisit runtime allocation only after confirming whether separation or dual re-solves dominate

## Figures
{_render_lines(f'`{path}`' for path in figure_paths)}

## Iteration Logs Used
{_render_lines(f'`{path}`' for path in log_paths)}
"""

    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default="configs/experiments/convergence_diagnostic_manifest.yaml",
    )
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--report-path", default=None)
    parser.add_argument("--baseline-dir", default=None)
    parser.add_argument("--skip-figures", action="store_true")
    args = parser.parse_args()

    manifest = load_diagnostic_manifest(args.manifest)
    critical_buses = load_critical_buses(manifest["critical_buses_config"])
    output_root = args.output_root or manifest.get(
        "output_root",
        "results/convergence_diagnostics",
    )
    report_path = args.report_path or manifest.get(
        "report_path",
        "docs/analysis_packs/convergence_diagnostic_pack.md",
    )
    baseline_dir = args.baseline_dir or manifest.get(
        "baseline_dir",
        "artifacts/baselines/round_12",
    )

    snapshot_round12_baseline(baseline_dir)
    output_root_path = clear_output_directory(output_root)
    figures_dir = ensure_directory(output_root_path / "figures")

    results = [
        execute_diagnostic_run(run_config, critical_buses=critical_buses, output_root=output_root_path)
        for run_config in manifest["runs"]
    ]
    summaries = [result["summary"] for result in results]
    failures = [result["failure"] for result in results if result["failure"] is not None]
    summary_path = write_summary_csv(output_root_path / "summary.csv", summaries)
    write_failures_csv(output_root_path / "failures.csv", failures)

    if args.skip_figures:
        figure_paths: list[str] = []
    else:
        figure_paths = generate_figures(
            summary_csv_path=summary_path,
            logs_dir=output_root_path / "logs",
            figures_dir=figures_dir,
        )

    run_logs = summarize_run_logs(output_root_path / "logs")
    log_paths = [
        payload["diagnostics"]["iteration_log_path"]
        for payload in run_logs.values()
        if isinstance(payload.get("diagnostics"), dict)
        and payload["diagnostics"].get("iteration_log_path")
    ]
    _write_report(
        report_path=report_path,
        baseline_dir=baseline_dir,
        summary_rows=summaries,
        failure_rows=failures,
        figure_paths=figure_paths,
        log_paths=log_paths,
    )


if __name__ == "__main__":
    main()
