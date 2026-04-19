"""Run the Round 13 cut-process strengthening diagnostic pack."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

from cut_process_utils import (
    clear_output_directory,
    ensure_directory,
    execute_cut_process_run,
    load_critical_buses,
    load_cut_process_matrix,
    rows_to_markdown_table,
    write_cut_diagnostics_csv,
    write_failures_csv,
    write_summary_csv,
)
from make_cut_process_figures import generate_figures


def _render_lines(items: Iterable[str]) -> str:
    materialized = [item for item in items if item]
    if not materialized:
        return "- none"
    return "\n".join(f"- {item}" for item in materialized)


def _write_report(
    *,
    report_path: str | Path,
    summary_rows,
    failure_rows,
    cut_rows,
    figure_paths: Sequence[str],
    iteration_log_paths: Sequence[str],
    master_lp_paths: Sequence[str],
) -> Path:
    grouped: dict[str, dict[str, object]] = {}
    for row in summary_rows:
        grouped.setdefault(row.comparison_group, {})[row.variant] = row

    comparison_rows = []
    for comparison_group, variants in grouped.items():
        baseline = variants.get("baseline")
        improved = variants.get("improved")
        comparison_rows.append(
            {
                "comparison_group": comparison_group,
                "baseline_label": "" if baseline is None else baseline.diagnosis_label,
                "baseline_violation": "" if baseline is None else baseline.final_violation_upper_bound,
                "improved_label": "" if improved is None else improved.diagnosis_label,
                "improved_violation": "" if improved is None else improved.final_violation_upper_bound,
                "helped": (
                    ""
                    if baseline is None or improved is None
                    else float(improved.final_violation_upper_bound or 0.0)
                    < float(baseline.final_violation_upper_bound or 0.0)
                ),
            }
        )

    repeated_outage_rows = [
        row
        for row in summary_rows
        if int(row.repeated_outage_count) > 0
    ]
    repeated_signature_rows = [
        row
        for row in summary_rows
        if int(row.repeated_cut_signature_count) > 0
    ]
    alpha_lambda_rows = [
        row
        for row in summary_rows
        if int(row.alpha_lambda_only_cut_count) > 0
    ]

    report = f"""# Cut Process Diagnostic Pack

## Scope
- This pack diagnoses the Benders cut process only.
- Validated model mathematics were left unchanged.
- The only algorithm-side strengthening in scope is conservative duplicate-cut guarding plus repeated-outage/cut reporting.

## Comparative sweep summary
{rows_to_markdown_table(comparison_rows, ['comparison_group', 'baseline_label', 'baseline_violation', 'improved_label', 'improved_violation', 'helped'])}

## Repeated-outage findings
{_render_lines(f"`{row.run_id}`: repeated_outage_count=`{row.repeated_outage_count}`" for row in repeated_outage_rows)}

## Repeated-cut findings
{_render_lines(f"`{row.run_id}`: repeated_cut_signature_count=`{row.repeated_cut_signature_count}`" for row in repeated_signature_rows)}

## Lower-bound / cut-count behavior
{_render_lines(f"`{row.run_id}`: lower_bound_gain=`{row.lower_bound_gain}`, generated_cut_count=`{row.generated_cut_count}`, dominant_cause=`{row.dominant_cause}`" for row in summary_rows)}

## Alpha/Lambda-only cut evidence
{_render_lines(f"`{row.run_id}`: alpha_lambda_only_cut_count=`{row.alpha_lambda_only_cut_count}`, plan_change_cut_count=`{row.plan_change_cut_count}`" for row in alpha_lambda_rows)}

## Failure / non-certification rows
{rows_to_markdown_table([row.to_csv_row() for row in failure_rows], ['comparison_group', 'variant', 'run_id', 'diagnosis_label', 'stop_reason', 'final_violation_upper_bound', 'dominant_cause', 'message']) if failure_rows else '- none'}

## Cut diagnostics sample
{rows_to_markdown_table([row.to_csv_row() for row in cut_rows[:10]], ['run_id', 'cut_id', 'repeated_outage_flag', 'repeated_cut_signature_flag', 'old_master_violation_at_source', 'post_cut_objective_change', 'first_stage_plan_changed', 'alpha_lambda_only_change', 'cut_addition_status']) if cut_rows else '- none'}

## Figures
{_render_lines(f'`{path}`' for path in figure_paths)}

## Iteration logs
{_render_lines(f'`{path}`' for path in iteration_log_paths)}

## Master LP dumps
{_render_lines(f'`{path}`' for path in master_lp_paths)}
"""

    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", default=None)
    parser.add_argument("--output-root", default="results/cut_process_diagnostics")
    parser.add_argument("--report-path", default="reports/cut_process_diagnostic_pack.md")
    parser.add_argument(
        "--critical-buses-config",
        default="configs/critical_buses_paper_fig2.yaml",
    )
    parser.add_argument("--skip-figures", action="store_true")
    args = parser.parse_args()

    runs = load_cut_process_matrix(args.matrix)
    critical_buses = load_critical_buses(args.critical_buses_config)
    output_root = clear_output_directory(args.output_root)
    figures_dir = ensure_directory(output_root / "figures")

    results = [
        execute_cut_process_run(run_config, critical_buses=critical_buses, output_root=output_root)
        for run_config in runs
    ]
    summary_rows = [result["summary"] for result in results]
    failure_rows = [result["failure"] for result in results if result["failure"] is not None]
    cut_rows = [row for result in results for row in result["cut_rows"]]

    summary_csv = write_summary_csv(output_root / "summary.csv", summary_rows)
    write_failures_csv(output_root / "failures.csv", failure_rows)
    cut_csv = write_cut_diagnostics_csv(output_root / "cut_diagnostics.csv", cut_rows)

    figure_paths = (
        []
        if args.skip_figures
        else generate_figures(
            summary_csv_path=summary_csv,
            cut_diagnostics_csv_path=cut_csv,
            figures_dir=figures_dir,
        )
    )
    iteration_log_paths = [
        result["iteration_log_path"]
        for result in results
        if result["iteration_log_path"]
    ]
    master_lp_paths = [
        path
        for result in results
        for path in (result["master_before_cut_lp_path"], result["master_after_cut_lp_path"])
        if path
    ]
    _write_report(
        report_path=args.report_path,
        summary_rows=summary_rows,
        failure_rows=failure_rows,
        cut_rows=cut_rows,
        figure_paths=figure_paths,
        iteration_log_paths=iteration_log_paths,
        master_lp_paths=master_lp_paths,
    )


if __name__ == "__main__":
    main()
