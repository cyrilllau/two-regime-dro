"""Run a focused refined exact calibration sweep for paper-like Fig. 6 matching."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiment_pack_utils import (  # noqa: E402
    execute_run,
    load_critical_buses,
    load_manifest,
    write_failures_csv,
    write_summary_csv,
)
from make_experiment_figures import write_plan_map_figure  # noqa: E402


def _load_plan_rows(path: str | Path) -> list[dict[str, int]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {
            "bus": int(row["bus"]),
            "is_open": int(row["is_open"]),
            "n_sl": int(row["n_sl"]),
            "n_fa": int(row["n_fa"]),
            "is_critical": int(row["is_critical"]),
        }
        for row in rows
    ]


def _write_target_plan_csv(
    *,
    path: Path,
    critical_buses: Sequence[int],
) -> Path:
    target_sites = {
        3: (22, 1),
        5: (3, 0),
        22: (1, 2),
        10: (0, 3),
        28: (21, 4),
        32: (24, 3),
        33: (3, 0),
    }
    rows: list[dict[str, Any]] = []
    critical_set = {int(bus) for bus in critical_buses}
    for bus in range(1, 34):
        slow, fast = target_sites.get(bus, (0, 0))
        rows.append(
            {
                "bus": bus,
                "is_open": int(bus in target_sites),
                "n_sl": slow,
                "n_fa": fast,
                "is_critical": int(bus in critical_set),
                "region": "",
            }
        )
    fieldnames = ["bus", "is_open", "n_sl", "n_fa", "is_critical", "region"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def _opened_sites(plan_rows: Sequence[Mapping[str, int]]) -> list[tuple[int, int, int]]:
    return sorted(
        (
            int(row["bus"]),
            int(row["n_sl"]),
            int(row["n_fa"]),
        )
        for row in plan_rows
        if int(row["is_open"]) == 1
    )


def _rank_row(row: Mapping[str, Any]) -> tuple[int, int, int, int]:
    opened = int(row["opened_bus_count"] or 0)
    total_slow = int(row["total_slow_chargers"] or 0)
    total_fast = int(row["total_fast_chargers"] or 0)
    fast_sites = int(row["fast_station_count"] or 0)
    site_penalty = abs(opened - 7)
    slow_penalty = abs(total_slow - 180)
    fast_penalty = abs(total_fast - 13)
    mix_penalty = abs(fast_sites - 3)
    return (site_penalty, slow_penalty, fast_penalty, mix_penalty)


def _write_report(
    *,
    report_path: Path,
    rows: Sequence[dict[str, Any]],
    best_row: Mapping[str, Any],
    figure_path: str,
) -> Path:
    table_lines = [
        "| run_id | ev_penetration_scale | opened_bus_count | total_slow_chargers | total_fast_chargers | fast_station_count | capped_slow_station_count | opened_bus_list |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        table_lines.append(
            f"| {row['run_id']} | {row['ev_penetration_scale']} | {row['opened_bus_count']} | "
            f"{row['total_slow_chargers']} | {row['total_fast_chargers']} | {row['fast_station_count']} | "
            f"{row['capped_slow_station_count']} | {row['opened_bus_list']} |"
        )
    content = f"""# Paper-Like Fig. 6 Refined Exact Sweep

## Scope
- This is a second-layer exact `normal_only` sweep.
- It uses the promising combined lever set:
  - `cfix = 614400`
  - `ccons_sl = 2700.35`
  - `ccons_fa = 12000`
  - `ctrans_scalar = 0.032625`
- Only `ev_penetration_scale` is varied here.
- This remains local `runtime_12` calibration, not paper-number reproduction.

## Refined Exact Candidates
{chr(10).join(table_lines)}

## Best-Fit Candidate
- Selected best-fit candidate: `{best_row['run_id']}`
- Reason: it is the closest exact `normal_only` match to the paper Fig. 6 Case 1 siting count/layout target.
- Opened buses / slow / fast: `{best_row['opened_bus_count']} / {best_row['total_slow_chargers']} / {best_row['total_fast_chargers']}`
- Opened-site list: `{best_row['opened_bus_list']}`

## Interpretation
- `0.55` is the first scale that enters the paper-like `6-8` station range.
- `0.50` keeps `8` stations while reducing total slow chargers further.
- `0.45` reaches `7` stations, which is the closest exact anchor to the paper Case 1 station count.
- None of these runs fully resolve the remaining `25/0` saturation pattern, so the next structural lever would have to address station-level capacity usage rather than only overall demand intensity.

## Figure
- `{figure_path}`
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default="configs/experiments/paper_like_fig6_refined.yaml")
    parser.add_argument("--output-root", default="results/paper_like_calibration_refined")
    parser.add_argument("--report-path", default="docs/analysis_packs/paper_like_fig6_refined_pack.md")
    parser.add_argument("--skip-figures", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    critical_buses = load_critical_buses(manifest["critical_buses_config"])

    summary_rows = []
    failure_rows = []
    report_rows: list[dict[str, Any]] = []
    for run in manifest["runs"]:
        result = execute_run(run, critical_buses=critical_buses, output_root=output_root)
        summary_rows.append(result["summary"])
        if result["failure_summary"] is not None:
            failure_rows.append(result["failure_summary"])
        plan_rows = _load_plan_rows(result["plan_path"])
        opened_sites = _opened_sites(plan_rows)
        report_rows.append(
            {
                "run_id": result["summary"].run_id,
                "ev_penetration_scale": float(run["ev_penetration_scale"]),
                "opened_bus_count": result["summary"].opened_bus_count,
                "total_slow_chargers": result["summary"].total_slow_chargers,
                "total_fast_chargers": result["summary"].total_fast_chargers,
                "fast_station_count": sum(1 for _, _, fast in opened_sites if fast > 0),
                "capped_slow_station_count": sum(1 for _, slow, _ in opened_sites if slow == 25),
                "opened_bus_list": "; ".join(
                    f"{bus}:{slow}/{fast}" for bus, slow, fast in opened_sites
                ),
            }
        )

    summary_path = write_summary_csv(output_root / "summary.csv", summary_rows)
    failures_path = write_failures_csv(output_root / "failures.csv", failure_rows)
    _write_target_plan_csv(
        path=output_root / "plans" / "paper_case1_target_semantics_plan.csv",
        critical_buses=critical_buses,
    )
    best_row = min(report_rows, key=_rank_row)
    figure_path = ""
    if not args.skip_figures:
        figure_output = output_root / "figures" / "refined_exact_comparison.png"
        write_plan_map_figure(
            run_ids=(
                "normal_only_paper_like_refined_scale_055",
                "normal_only_paper_like_refined_scale_050",
                "normal_only_paper_like_refined_scale_045",
                "paper_case1_target_semantics",
            ),
            plans_dir=output_root / "plans",
            title="Refined exact candidates vs paper target semantics",
            path=figure_output,
            ncols=1,
        )
        figure_path = str(figure_output)
    report_written = _write_report(
        report_path=Path(args.report_path),
        rows=report_rows,
        best_row=best_row,
        figure_path=figure_path,
    )
    metadata = {
        "summary_csv": str(summary_path),
        "failures_csv": str(failures_path),
        "report_path": str(report_written),
        "best_fit_run_id": best_row["run_id"],
        "best_fit_ev_penetration_scale": best_row["ev_penetration_scale"],
        "figure_path": figure_path,
    }
    (output_root / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
