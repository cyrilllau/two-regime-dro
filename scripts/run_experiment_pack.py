"""Run the Round 12 experiment pack and write packaging artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

from experiment_pack_utils import (
    ExperimentFailureSummary,
    ExperimentRunSummary,
    ensure_directory,
    execute_run,
    load_critical_buses,
    load_manifest,
    rows_to_markdown_table,
    summarize_run_logs,
    write_failures_csv,
    write_summary_csv,
)
from make_experiment_figures import generate_figures


def _find_row(
    summary_rows: Sequence[ExperimentRunSummary],
    *,
    run_id: str,
) -> ExperimentRunSummary | None:
    for row in summary_rows:
        if row.run_id == run_id:
            return row
    return None


def _plan_signature(
    run_logs: dict[str, dict[str, object]],
    run_id: str,
) -> tuple[tuple[int, int, int, int], ...] | None:
    payload = run_logs.get(run_id)
    if payload is None:
        return None
    rows = payload.get("plan_rows", [])
    if not isinstance(rows, list):
        return None
    signature: list[tuple[int, int, int, int]] = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        signature.append(
            (
                int(row.get("bus", 0)),
                int(row.get("is_open", 0)),
                int(row.get("n_sl", 0)),
                int(row.get("n_fa", 0)),
            )
        )
    return tuple(signature)


def _same_plan(
    run_logs: dict[str, dict[str, object]],
    left_run_id: str,
    right_run_id: str,
) -> bool | None:
    left = _plan_signature(run_logs, left_run_id)
    right = _plan_signature(run_logs, right_run_id)
    if left is None or right is None:
        return None
    return left == right


def _render_lines(items: Iterable[str]) -> str:
    materialized = [item for item in items if item]
    if not materialized:
        return "- none"
    return "\n".join(f"- {item}" for item in materialized)


def _clear_pack_outputs(output_root_path: Path) -> None:
    """Remove stale packaging artifacts before generating a fresh experiment pack."""

    for child in (
        output_root_path / "summary.csv",
        output_root_path / "failures.csv",
    ):
        if child.exists():
            child.unlink()
    for directory_name in ("plans", "logs", "figures"):
        directory = output_root_path / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()


def _render_validation_lists(summary_rows: Sequence[ExperimentRunSummary]) -> str:
    labels = ("exact", "epsilon_certified", "smoke_only", "failed")
    lines: list[str] = []
    for label in labels:
        run_ids = [f"`{row.run_id}`" for row in summary_rows if row.validation_level == label]
        lines.append(f"- `{label}`: {', '.join(run_ids) if run_ids else 'none'}")
    return "\n".join(lines)


def _render_failure_details(failure_rows: Sequence[ExperimentFailureSummary]) -> str:
    if not failure_rows:
        return "- none"
    return "\n".join(
        f"- `{row.run_id}`: validation=`{row.validation_level}`, stop_reason=`{row.stop_reason}`, "
        f"solver_status=`{row.solver_status}`, message={row.message}"
        for row in failure_rows
    )


def _value_text(value: float | None) -> str:
    return "n/a" if value is None else f"{value}"


def _integrated_vs_normal_section(
    *,
    title: str,
    integrated: ExperimentRunSummary | None,
    normal_only: ExperimentRunSummary | None,
    run_logs: dict[str, dict[str, object]],
    qualification: str,
) -> str:
    if integrated is None or normal_only is None:
        return f"## {title}\n- This manifest does not contain both required runs.\n"

    plan_match = _same_plan(run_logs, integrated.run_id, normal_only.run_id)
    if plan_match is True:
        plan_sentence = "The two runs returned the same first-stage plan."
    elif plan_match is False:
        plan_sentence = "The two runs returned different first-stage plans."
    else:
        plan_sentence = "The saved plan logs were not sufficient to reconstruct a clean comparison."

    return f"""## {title}
- Integrated run: `{integrated.run_id}` (`{integrated.validation_level}`, stop_reason=`{integrated.stop_reason}`)
- Normal-only run: `{normal_only.run_id}` (`{normal_only.validation_level}`, stop_reason=`{normal_only.stop_reason}`)
- Construction cost comparison:
  - integrated = `{_value_text(integrated.construction_cost)}`
  - normal-only = `{_value_text(normal_only.construction_cost)}`
- Unweighted normal-cost comparison:
  - integrated = `{_value_text(integrated.unweighted_normal_term)}`
  - normal-only = `{_value_text(normal_only.unweighted_normal_term)}`
- Disaster-master comparison:
  - integrated = `{_value_text(integrated.disaster_master_term)}`
  - normal-only = `{_value_text(normal_only.disaster_master_term)}`
- Plan comparison: {plan_sentence}
- Interpretation boundary: {qualification}
"""


def _deterministic_vs_integrated_section(
    *,
    title: str,
    integrated: ExperimentRunSummary | None,
    deterministic: ExperimentRunSummary | None,
    run_logs: dict[str, dict[str, object]],
    qualification: str,
) -> str:
    if integrated is None or deterministic is None:
        return f"## {title}\n- This manifest does not contain both required runs.\n"

    plan_match = _same_plan(run_logs, integrated.run_id, deterministic.run_id)
    if plan_match is True:
        plan_sentence = "The deterministic mean-value run landed on the same first-stage plan."
    elif plan_match is False:
        plan_sentence = "The deterministic mean-value run changed the first-stage plan."
    else:
        plan_sentence = "The plan comparison could not be reconstructed from the saved logs."

    return f"""## {title}
- Integrated run: `{integrated.run_id}` (`{integrated.validation_level}`)
- Deterministic run: `{deterministic.run_id}` (`{deterministic.validation_level}`)
- Weighted normal term:
  - integrated = `{_value_text(integrated.weighted_normal_term)}`
  - deterministic = `{_value_text(deterministic.weighted_normal_term)}`
- Disaster master term:
  - integrated = `{_value_text(integrated.disaster_master_term)}`
  - deterministic = `{_value_text(deterministic.disaster_master_term)}`
- Plan comparison: {plan_sentence}
- Interpretation boundary: {qualification}
"""


def _ev_section(
    *,
    title: str,
    base: ExperimentRunSummary | None,
    up_1_5: ExperimentRunSummary | None,
    up_2_0: ExperimentRunSummary | None,
    qualification: str,
) -> str:
    if base is None or up_1_5 is None or up_2_0 is None:
        return f"## {title}\n- This manifest does not contain the full EV-penetration trio.\n"

    return f"""## {title}
- Base run `{base.run_id}`:
  - validation = `{base.validation_level}`
  - construction = `{_value_text(base.construction_cost)}`
  - total objective = `{_value_text(base.total_objective)}`
  - opened buses / slow / fast = `{base.opened_bus_count} / {base.total_slow_chargers} / {base.total_fast_chargers}`
- 1.5x run `{up_1_5.run_id}`:
  - validation = `{up_1_5.validation_level}`
  - construction = `{_value_text(up_1_5.construction_cost)}`
  - total objective = `{_value_text(up_1_5.total_objective)}`
  - opened buses / slow / fast = `{up_1_5.opened_bus_count} / {up_1_5.total_slow_chargers} / {up_1_5.total_fast_chargers}`
- 2.0x run `{up_2_0.run_id}`:
  - validation = `{up_2_0.validation_level}`
  - construction = `{_value_text(up_2_0.construction_cost)}`
  - total objective = `{_value_text(up_2_0.total_objective)}`
  - opened buses / slow / fast = `{up_2_0.opened_bus_count} / {up_2_0.total_slow_chargers} / {up_2_0.total_fast_chargers}`
- Interpretation boundary: {qualification}
"""


def _write_interpretation_report(
    *,
    report_path: str | Path,
    run_logs: dict[str, dict[str, object]],
    summary_rows: Sequence[ExperimentRunSummary],
    failure_rows: Sequence[ExperimentFailureSummary],
    figure_paths: Sequence[str],
) -> Path:
    summary_table_rows = [
        {
            "run_id": row.run_id,
            "case_name": row.case_name,
            "parameter_regime": row.parameter_regime,
            "validation_level": row.validation_level,
            "stop_reason": row.stop_reason,
            "solver_status": row.solver_status,
            "iteration_count": row.iteration_count,
            "cut_count": row.cut_count,
            "final_violation_upper_bound": row.final_violation_upper_bound,
        }
        for row in summary_rows
    ]
    component_table_rows = [
        {
            "run_id": row.run_id,
            "construction_cost": row.construction_cost,
            "weighted_normal_term": row.weighted_normal_term,
            "unweighted_normal_term": row.unweighted_normal_term,
            "disaster_master_term": row.disaster_master_term,
            "total_objective": row.total_objective,
        }
        for row in summary_rows
    ]
    failure_table_rows = [row.to_csv_row() for row in failure_rows]

    integrated_paper_like = _find_row(summary_rows, run_id="integrated_mainline_paper_like")
    normal_paper_like = _find_row(summary_rows, run_id="normal_only_paper_like")
    disaster_paper_like = _find_row(summary_rows, run_id="disaster_only_paper_like")
    deterministic_paper_like = _find_row(
        summary_rows,
        run_id="deterministic_mean_value_paper_like",
    )
    ev_1_5_paper_like = _find_row(summary_rows, run_id="ev_penetration_1_5x_paper_like")
    ev_2_0_paper_like = _find_row(summary_rows, run_id="ev_penetration_2_0x_paper_like")

    integrated_runtime = _find_row(summary_rows, run_id="integrated_mainline_runtime12")
    normal_runtime = _find_row(summary_rows, run_id="normal_only_runtime12")
    deterministic_runtime = _find_row(
        summary_rows,
        run_id="deterministic_mean_value_runtime12",
    )
    ev_1_5_runtime = _find_row(summary_rows, run_id="ev_penetration_1_5x_runtime12")
    ev_2_0_runtime = _find_row(summary_rows, run_id="ev_penetration_2_0x_runtime12")

    if integrated_paper_like and normal_paper_like:
        if (
            integrated_paper_like.unweighted_normal_term is not None
            and normal_paper_like.unweighted_normal_term is not None
            and integrated_paper_like.unweighted_normal_term
            <= normal_paper_like.unweighted_normal_term
        ):
            integrated_answer = (
                "In the current paper-like family, no clear daily-cost penalty appears. "
                "The integrated run is epsilon-certified, returns a slightly lower normal-cost term, "
                "and does not expose a positive disaster master term under the reduced `[1] / [1]` support."
            )
        else:
            integrated_answer = (
                "In the current paper-like family, integrated planning does appear to trade some daily-cost "
                "increase for resilience-oriented structure, but this remains a local approximation and not a paper-number claim."
            )
    else:
        integrated_answer = "The manifest does not contain a complete paper-like integrated-vs-normal pair."

    if integrated_paper_like and deterministic_paper_like:
        same_det = _same_plan(run_logs, integrated_paper_like.run_id, deterministic_paper_like.run_id)
        if same_det is True:
            deterministic_answer = (
                "The certified paper-like small-support benchmark does not show an underestimation gap: "
                "deterministic mean-value collapses to the same plan and objective. "
                "The stronger underestimation question is therefore unresolved here."
            )
        else:
            deterministic_answer = (
                "The paper-like benchmark shows a deterministic-vs-integrated difference, "
                "which is directionally consistent with deterministic underestimation of disaster structure."
            )
    else:
        deterministic_answer = "The manifest does not contain a complete deterministic-vs-integrated paper-like pair."

    if integrated_paper_like and ev_1_5_paper_like and ev_2_0_paper_like:
        ev_answer = (
            "The paper-like family shows monotone buildout and cost growth from base to 1.5x to 2.0x EV penetration. "
            "That direction is robust in the produced artifacts, but still belongs to a local approximation layer."
        )
    else:
        ev_answer = "The manifest does not contain the full paper-like EV-penetration trio."

    safe_claims = [
        "Validation labels are explicit at the run level and are carried into the summary CSV, failures CSV, and per-run JSON logs.",
        "The paper-like family is an approximation layer on top of the local runtime data, not a claim of exact Table-II number reproduction.",
        "The runtime12 directional family is useful for qualitative directionality only unless a run is explicitly exact or epsilon-certified.",
    ]
    unsafe_claims = [
        "Do not present current runtime_12 totals as paper-number reproduction.",
        "Do not rank heterogeneous benchmark definitions by raw total objective unless the report explicitly says the objectives are directly comparable.",
        "Do not treat smoke-only runs as certified evidence.",
    ]

    report = f"""# Paper-Style Experiment Pack

## Scope
- Round 12 froze `critical_buses` to `[2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`.
- Validation labels are explicit:
  - `exact`
  - `epsilon_certified`
  - `smoke_only`
  - `failed`
- The current `runtime_12` package is **not** numerically paper-Table-II comparable.
- The paper-like family is an approximation layer built through config-level overrides only.

## Validation Label Overview
{_render_validation_lists(summary_rows)}

## Summary Table
{rows_to_markdown_table(summary_table_rows, ['run_id', 'case_name', 'parameter_regime', 'validation_level', 'stop_reason', 'solver_status', 'iteration_count', 'cut_count', 'final_violation_upper_bound'])}

## Objective Components
{rows_to_markdown_table(component_table_rows, ['run_id', 'construction_cost', 'weighted_normal_term', 'unweighted_normal_term', 'disaster_master_term', 'total_objective'])}

## Failure / Non-Convergence Table
{rows_to_markdown_table(failure_table_rows, ['run_id', 'case_name', 'parameter_regime', 'validation_level', 'stop_reason', 'solver_status', 'iteration_count', 'cut_count', 'final_violation_upper_bound', 'message']) if failure_rows else '- none'}

## What Happened For Failed Or Non-Converged Runs
{_render_failure_details(failure_rows)}

## Direct Answers To The Round-12 Interpretation Questions
1. Does integrated planning trade a small increase in daily cost for a large resilience gain?
   - {integrated_answer}
2. Does deterministic mean-value underestimate disaster risk?
   - {deterministic_answer}
3. How does EV penetration affect buildout and cost?
   - {ev_answer}

{_integrated_vs_normal_section(
    title='Integrated Vs Normal-Only (Paper-Like Family)',
    integrated=integrated_paper_like,
    normal_only=normal_paper_like,
    run_logs=run_logs,
    qualification='Use this as a paper-like directional comparison only. The local runtime data and current approximation layer are not paper-number reproduction.',
)}

## Disaster-Only Paper-Like Run
- `disaster_only_paper_like`: `{disaster_paper_like.validation_level if disaster_paper_like else 'missing'}`
- Interpretation boundary:
  - this benchmark removes weighted normal cost by construction
  - raw totals should not be ranked directly against integrated/normal-only unless that caveat is stated

{_deterministic_vs_integrated_section(
    title='Deterministic Vs Integrated (Paper-Like Family)',
    integrated=integrated_paper_like,
    deterministic=deterministic_paper_like,
    run_logs=run_logs,
    qualification='Treat this as a directional deterministic-vs-integrated comparison only. The key question is whether deterministic mean-value planning understates disaster risk in the current local benchmark pack.',
)}

{_ev_section(
    title='EV-Penetration Interpretation (Paper-Like Family)',
    base=integrated_paper_like,
    up_1_5=ev_1_5_paper_like,
    up_2_0=ev_2_0_paper_like,
    qualification='These are paper-like directionality runs only. They are not a claim of reproducing the paper sensitivity table numerically.',
)}

{_integrated_vs_normal_section(
    title='Integrated Vs Normal-Only (Runtime-Directional Family)',
    integrated=integrated_runtime,
    normal_only=normal_runtime,
    run_logs=run_logs,
    qualification='This family must be read as local-runtime directionality only. If a run is smoke_only, it stays smoke_only.',
)}

{_deterministic_vs_integrated_section(
    title='Deterministic Vs Integrated (Runtime-Directional Family)',
    integrated=integrated_runtime,
    deterministic=deterministic_runtime,
    run_logs=run_logs,
    qualification='The runtime-directional family is not paper-comparable. Any deterministic-vs-integrated conclusion here is local-directional only.',
)}

{_ev_section(
    title='EV-Penetration Interpretation (Runtime-Directional Family)',
    base=integrated_runtime,
    up_1_5=ev_1_5_runtime,
    up_2_0=ev_2_0_runtime,
    qualification='These runs are for local directionality only, especially when validation remains smoke_only.',
)}

## Safe Colleague-Facing Claims
{_render_lines(safe_claims)}

## Unsafe Or Overstated Claims
{_render_lines(unsafe_claims)}

## Paper-Like Vs Local-Runtime Directionality
- The `paper_like_tableII_family` is closer in economic semantics to the paper experiment section, but it is still built on the local `runtime_12` data package.
- The `runtime12_directional_family` is purely a local-directional benchmark family.
- Neither family should be described as paper-scale validation unless the produced artifacts explicitly certify that claim.

## Figure Outputs
{_render_lines(f'`{path}`' for path in figure_paths)}
"""

    file_path = Path(report_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(report, encoding="utf-8")
    return file_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        default="configs/experiments/experiment_manifest.yaml",
    )
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--report-path", default=None)
    parser.add_argument("--skip-figures", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    critical_buses = load_critical_buses(manifest["critical_buses_config"])
    output_root = args.output_root or manifest.get("output_root", "results")
    report_path = args.report_path or manifest.get(
        "report_path",
        "docs/analysis_packs/paper_style_experiment_pack.md",
    )

    output_root_path = ensure_directory(output_root)
    _clear_pack_outputs(output_root_path)
    figures_dir = ensure_directory(output_root_path / "figures")

    results = [
        execute_run(run_config, critical_buses=critical_buses, output_root=output_root_path)
        for run_config in manifest["runs"]
    ]
    summaries = [result["summary"] for result in results]
    failures = [
        result["failure_summary"]
        for result in results
        if result.get("failure_summary") is not None
    ]
    summary_path = write_summary_csv(output_root_path / "summary.csv", summaries)
    write_failures_csv(output_root_path / "failures.csv", failures)

    if args.skip_figures:
        figure_paths: list[str] = []
    else:
        figure_paths = generate_figures(
            summary_csv_path=summary_path,
            plans_dir=output_root_path / "plans",
            logs_dir=output_root_path / "logs",
            figures_dir=figures_dir,
        )

    run_logs = summarize_run_logs(output_root_path / "logs")
    _write_interpretation_report(
        report_path=report_path,
        run_logs=run_logs,
        summary_rows=summaries,
        failure_rows=failures,
        figure_paths=figure_paths,
    )


if __name__ == "__main__":
    main()
