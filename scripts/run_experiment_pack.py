"""Run the Round 11 experiment pack and write packaging artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from experiment_pack_utils import (
    ensure_directory,
    execute_run,
    load_critical_buses,
    load_manifest,
    rows_to_markdown_table,
    summarize_run_logs,
    write_summary_csv,
)
from make_experiment_figures import generate_figures


def _find_row(summary_rows, *, family_name: str | None = None, run_id_contains: str | None = None):
    for row in summary_rows:
        if family_name is not None and row.family_name != family_name:
            continue
        if run_id_contains is not None and run_id_contains not in row.run_id:
            continue
        return row
    return None


def _plan_signature(run_logs: dict[str, dict[str, object]], run_id: str) -> tuple[tuple[int, int, int, int], ...] | None:
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
                int(row.get("z", 0)),
                int(row.get("n_sl", 0)),
                int(row.get("n_fa", 0)),
            )
        )
    return tuple(signature)


def _same_plan(run_logs: dict[str, dict[str, object]], left_run_id: str, right_run_id: str) -> bool | None:
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


def _write_interpretation_report(
    *,
    report_path: str | Path,
    run_logs: dict[str, dict[str, object]],
    summary_rows,
    figure_paths,
) -> Path:
    certified_integrated = _find_row(
        summary_rows,
        family_name="certified_small_family",
        run_id_contains="integrated_mainline",
    )
    certified_normal = _find_row(
        summary_rows,
        family_name="certified_small_family",
        run_id_contains="normal_only",
    )
    certified_deterministic = _find_row(
        summary_rows,
        family_name="certified_small_family",
        run_id_contains="deterministic_mean_value",
    )
    runtime_integrated = _find_row(
        summary_rows,
        family_name="runtime12_smoke_family",
        run_id_contains="integrated_mainline_runtime12",
    )
    runtime_normal = _find_row(
        summary_rows,
        family_name="runtime12_smoke_family",
        run_id_contains="normal_only_runtime12",
    )
    runtime_deterministic = _find_row(
        summary_rows,
        family_name="runtime12_smoke_family",
        run_id_contains="deterministic_mean_value_runtime12",
    )
    runtime_ev_1_5 = _find_row(
        summary_rows,
        family_name="runtime12_smoke_family",
        run_id_contains="ev_penetration_1_5x",
    )
    runtime_ev_2_0 = _find_row(
        summary_rows,
        family_name="runtime12_smoke_family",
        run_id_contains="ev_penetration_2_0x",
    )

    safe_claims = [
        "The tiny validation chain from earlier rounds remains exact.",
        "Every experiment run is labeled explicitly as `exact`, `epsilon_certified`, or `smoke_only` in `results/summary.csv`.",
        "The default runtime `{1,2}` family remains smoke-oriented unless a specific run actually certified.",
    ]
    provisional_claims = [
        "Integrated vs normal-only differences on default `runtime_12` are provisional because the family is smoke-oriented.",
        "Deterministic mean-value vs integrated differences on default `runtime_12` are provisional for the same reason.",
        "EV-penetration directionality on default `runtime_12` is smoke-only unless a specific run certified.",
    ]

    validation_rows = [
        {
            "run_id": row.run_id,
            "case_name": row.case_name,
            "validation_level": row.validation_level,
            "stop_reason": row.stop_reason,
            "iteration_count": row.iteration_count,
            "cut_count": row.cut_count,
            "final_violation_upper_bound": row.final_violation_upper_bound,
        }
        for row in summary_rows
    ]
    component_rows = [
        {
            "run_id": row.run_id,
            "construction_cost": round(row.construction_cost, 3),
            "unweighted_normal_term": round(row.unweighted_normal_term, 3),
            "disaster_master_term": round(row.disaster_master_term, 3),
            "total_objective": round(row.total_objective, 3),
        }
        for row in summary_rows
    ]

    certified_integrated_vs_normal = ""
    if certified_integrated and certified_normal:
        plan_match = _same_plan(run_logs, certified_integrated.run_id, certified_normal.run_id)
        if plan_match is True:
            plan_sentence = (
                "Both runs produced the same first-stage siting/charger pattern under the reduced `[1] / [1]` support."
            )
        elif plan_match is False:
            plan_sentence = (
                "The integrated and normal-only benchmarks produced different first-stage plans under the reduced `[1] / [1]` support."
            )
        else:
            plan_sentence = "The plan comparison could not be reconstructed from the saved packaging logs."
        certified_integrated_vs_normal = f"""## Integrated Vs Normal-Only
1. Certified-small family:
   - `{certified_integrated.run_id}` is `{certified_integrated.validation_level}` with stop reason `{certified_integrated.stop_reason}`.
   - `{certified_normal.run_id}` is `{certified_normal.validation_level}` via a direct benchmark solve.
   - {plan_sentence}
"""
    elif summary_rows:
        certified_integrated_vs_normal = """## Integrated Vs Normal-Only
- No full certified-small family was supplied in this manifest, so only the generic summary table is available here.
"""

    runtime_integrated_vs_normal = ""
    if runtime_integrated and runtime_normal:
        runtime_plan_match = _same_plan(run_logs, runtime_integrated.run_id, runtime_normal.run_id)
        if runtime_plan_match is True:
            runtime_plan_sentence = (
                "Within this smoke-only family, the integrated and normal-only runs also happened to return the same first-stage plan."
            )
        elif runtime_plan_match is False:
            runtime_plan_sentence = (
                "Within this smoke-only family, the integrated and normal-only runs returned different first-stage plans."
            )
        else:
            runtime_plan_sentence = (
                "The runtime integrated-vs-normal plan comparison could not be reconstructed from the saved packaging logs."
            )
        runtime_integrated_vs_normal = f"""2. Default `runtime_12` family:
   - `{runtime_integrated.run_id}` is `{runtime_integrated.validation_level}`.
   - `{runtime_normal.run_id}` is `{runtime_normal.validation_level}`.
   - The safer colleague-facing takeaway is qualitative only: the integrated run keeps an explicit disaster master term, while the normal-only benchmark removes it by construction.
   - {runtime_plan_sentence}
"""

    deterministic_section_lines: list[str] = []
    if certified_deterministic and certified_integrated:
        deterministic_section_lines.extend(
            [
                "## Deterministic Vs Integrated",
                "1. Certified-small family:",
                f"   - `{certified_deterministic.run_id}` is `{certified_deterministic.validation_level}`.",
                "   - Because the certified-small family already uses singleton scenario supports, the deterministic mean-value benchmark collapses to the same reduced-support data and is not informative by itself.",
            ]
        )
    elif summary_rows:
        deterministic_section_lines.extend(
            [
                "## Deterministic Vs Integrated",
                "- No certified-small deterministic benchmark was supplied in this manifest.",
            ]
        )
    if runtime_deterministic and runtime_integrated:
        runtime_det_match = _same_plan(run_logs, runtime_integrated.run_id, runtime_deterministic.run_id)
        if runtime_det_match is True:
            runtime_det_sentence = (
                "The smoke-only deterministic benchmark landed on the same first-stage plan as the integrated run."
            )
        elif runtime_det_match is False:
            runtime_det_sentence = (
                "The smoke-only deterministic benchmark changed the first-stage plan relative to the integrated run."
            )
        else:
            runtime_det_sentence = (
                "The runtime deterministic-vs-integrated plan comparison could not be reconstructed from the saved packaging logs."
            )
        deterministic_section_lines.extend(
            [
                "2. Default `runtime_12` family:",
                f"   - `{runtime_deterministic.run_id}` is `{runtime_deterministic.validation_level}`.",
                f"   - Compared with `{runtime_integrated.run_id}`, its disaster term is interpreted only provisionally because this family is smoke-oriented.",
                f"   - {runtime_det_sentence}",
            ]
        )

    ev_section = ""
    if runtime_integrated and runtime_ev_1_5 and runtime_ev_2_0:
        ev_section = f"""## EV-Penetration Interpretation
- Base default runtime: `{runtime_integrated.run_id}`
  - construction = `{runtime_integrated.construction_cost}`
  - unweighted normal term = `{runtime_integrated.unweighted_normal_term}`
  - disaster term = `{runtime_integrated.disaster_master_term}`
  - opened buses / slow / fast = `{runtime_integrated.opened_bus_count} / {runtime_integrated.total_slow_chargers} / {runtime_integrated.total_fast_chargers}`
- 1.5x EV penetration:
  - construction = `{runtime_ev_1_5.construction_cost}`
  - unweighted normal term = `{runtime_ev_1_5.unweighted_normal_term}`
  - disaster term = `{runtime_ev_1_5.disaster_master_term}`
  - opened buses / slow / fast = `{runtime_ev_1_5.opened_bus_count} / {runtime_ev_1_5.total_slow_chargers} / {runtime_ev_1_5.total_fast_chargers}`
- 2.0x EV penetration:
  - construction = `{runtime_ev_2_0.construction_cost}`
  - unweighted normal term = `{runtime_ev_2_0.unweighted_normal_term}`
  - disaster term = `{runtime_ev_2_0.disaster_master_term}`
  - opened buses / slow / fast = `{runtime_ev_2_0.opened_bus_count} / {runtime_ev_2_0.total_slow_chargers} / {runtime_ev_2_0.total_fast_chargers}`
- Interpretation:
  - use these runs for directionality only unless their validation label is not `smoke_only`
  - higher EV penetration should be read as a packaging-layer scaling of EV charging and V2G-related tensors, not as a paper-Table-II reproduction
"""
    elif summary_rows:
        ev_section = """## EV-Penetration Interpretation
- No EV-penetration benchmark family was supplied in this manifest.
"""

    report = f"""# Experiment Interpretation Pack

## Scope
- `critical_buses` were fixed explicitly from the paper Fig. 2 set:
  `[2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`
- Validation labels are explicit:
  - `exact`
  - `epsilon_certified`
  - `smoke_only`
- No paper-scale optimality claim is made in this pack.

## Validation Overview
{rows_to_markdown_table(validation_rows, ['run_id', 'case_name', 'validation_level', 'stop_reason', 'iteration_count', 'cut_count', 'final_violation_upper_bound'])}

## Objective Decomposition Overview
{rows_to_markdown_table(component_rows, ['run_id', 'construction_cost', 'unweighted_normal_term', 'disaster_master_term', 'total_objective'])}

{certified_integrated_vs_normal}{runtime_integrated_vs_normal}

{chr(10).join(deterministic_section_lines)}

{ev_section}

## What Is Safe For Colleague Review
{_render_lines(safe_claims)}

## What Is Provisional
{_render_lines(provisional_claims)}

## Paper-Comparability Honesty Check
- The current `runtime_12` pack is not numerically identical to the paper Table II regime.
- This pack uses the local runtime parameters already frozen in the repo, including 24 normal periods, 4 disaster periods, and the current local capital/operating coefficients.
- Therefore absolute magnitudes are not directly paper-comparable.
- The correct colleague-facing use of this pack is:
  - directionality
  - trade-off inspection
  - validation-level awareness
  - not direct paper-number reproduction

## Figure Outputs
{_render_lines(f'`{path}`' for path in figure_paths)}

## Artifact Notes
- Per-run logs record the exact validation label and stop reason used in this pack.
- Benders iteration artifacts are saved only for the runs that actually used the Benders engine.
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
        "reports/experiment_interpretation_pack.md",
    )

    output_root_path = ensure_directory(output_root)
    ensure_directory(output_root_path / "plans")
    ensure_directory(output_root_path / "logs")
    figures_dir = ensure_directory(output_root_path / "figures")

    results = [
        execute_run(run_config, critical_buses=critical_buses, output_root=output_root_path)
        for run_config in manifest["runs"]
    ]
    summaries = [result["summary"] for result in results]
    summary_path = write_summary_csv(output_root_path / "summary.csv", summaries)

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
        figure_paths=figure_paths,
    )


if __name__ == "__main__":
    main()
