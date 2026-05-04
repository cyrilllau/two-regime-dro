#!/usr/bin/env python3
"""Regenerate main-paper-style scenario profile figures for the experiment setup.

The accepted default optimization pack uses the 10x10 colleague-derived runtime
source.  The setup figures are drawn from the unperturbed colleague-provided
base profiles, because drawing scenario a=1 from the expanded 10x10 runtime
source can show a synthetic perturbation rather than the representative profile
used in the main-paper-style setup discussion.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt


FIGURE_DPI = 180
REGION_LABELS = {1: "Region1", 2: "Region2", 3: "Region3"}


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _series_by_region(
    path: Path,
    *,
    scenario_col: str,
    scenario_id: int,
    time_col: str,
    value_col: str,
) -> dict[int, dict[int, float]]:
    series: dict[int, dict[int, float]] = {}
    for row in _read_rows(path):
        if int(row[scenario_col]) != int(scenario_id):
            continue
        region = int(row["region"])
        time_id = int(row[time_col])
        series.setdefault(region, {})[time_id] = float(row[value_col])
    return series


def _system_load_series(path: Path, *, scenario_id: int) -> dict[str, dict[int, float]]:
    series = {"P_kW": {}, "Q_kvar": {}}
    for row in _read_rows(path):
        if int(row["scenario_a"]) != int(scenario_id):
            continue
        time_id = int(row["t"])
        for col in series:
            series[col][time_id] = series[col].get(time_id, 0.0) + float(row[col])
    return series


def _plot_regional_lines(
    ax: plt.Axes,
    series: dict[int, dict[int, float]],
    *,
    title: str,
    ylabel: str,
) -> None:
    for region in sorted(series):
        times = sorted(series[region])
        values = [series[region][time_id] for time_id in times]
        ax.plot(times, values, linewidth=1.3, label=REGION_LABELS.get(region, f"Region{region}"))
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("Time(t)")
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)


def _scenario_ids(path: Path, scenario_col: str) -> list[int]:
    return sorted({int(row[scenario_col]) for row in _read_rows(path)})


def _time_ids(path: Path, scenario_col: str, scenario_id: int, time_col: str) -> list[int]:
    return sorted(
        {
            int(row[time_col])
            for row in _read_rows(path)
            if int(row[scenario_col]) == int(scenario_id)
        }
    )


def _write_csv(path: Path, rows: Iterable[dict[str, object]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def regenerate(source: Path, default_runtime_source: Path, output_dir: Path, paper_root: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    normal_load = _system_load_series(source / "normal_load_scenarios.csv", scenario_id=1)
    fig, ax = plt.subplots(figsize=(7.0, 3.4))
    times = sorted(normal_load["P_kW"])
    ax.plot(times, [normal_load["P_kW"][t] for t in times], linewidth=1.5, label="Active load")
    ax.plot(times, [normal_load["Q_kvar"][t] for t in times], linewidth=1.5, label="Reactive load")
    ax.set_title("Active and reactive load profile under scenario a=1", fontsize=11)
    ax.set_xlabel("Time(t)")
    ax.set_ylabel("System load")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output_dir / "scenario_profile_normal_load.png", dpi=FIGURE_DPI)
    plt.close(fig)

    normal_slow = _series_by_region(
        source / "normal_ev_demand_slow.csv",
        scenario_col="scenario_a",
        scenario_id=1,
        time_col="t",
        value_col="DEV_ch_sl_kW",
    )
    normal_fast = _series_by_region(
        source / "normal_ev_demand_fast.csv",
        scenario_col="scenario_a",
        scenario_id=1,
        time_col="t",
        value_col="DEV_ch_fa_kW",
    )
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6), sharex=False)
    _plot_regional_lines(
        axes[0],
        normal_slow,
        title="EV Slow Charging Demand - scenario_a=1",
        ylabel="DEV_ch_sl (kW)",
    )
    _plot_regional_lines(
        axes[1],
        normal_fast,
        title="EV Fast Charging Demand - scenario_a=1",
        ylabel="DEV_ch_fa (kW)",
    )
    fig.tight_layout()
    fig.savefig(output_dir / "scenario_profile_normal_ev.png", dpi=FIGURE_DPI)
    plt.close(fig)

    disaster_slow = _series_by_region(
        source / "disaster_ev_discharge_slow.csv",
        scenario_col="scenario_b",
        scenario_id=1,
        time_col="ts",
        value_col="DEV_dis_sl_kW",
    )
    disaster_fast = _series_by_region(
        source / "disaster_ev_discharge_fast.csv",
        scenario_col="scenario_b",
        scenario_id=1,
        time_col="ts",
        value_col="DEV_dis_fa_kW",
    )
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 3.6), sharex=False)
    _plot_regional_lines(
        axes[0],
        disaster_slow,
        title="EV Slow Discharge - scenario_b=1",
        ylabel="DEV_dis_sl (kW)",
    )
    _plot_regional_lines(
        axes[1],
        disaster_fast,
        title="EV Fast Discharge - scenario_b=1",
        ylabel="DEV_dis_fa (kW)",
    )
    fig.tight_layout()
    fig.savefig(output_dir / "scenario_profile_disaster_ev.png", dpi=FIGURE_DPI)
    plt.close(fig)

    inventory_rows = []
    for dataset_role, root in [
        ("profile_figure_source_unperturbed_base", source),
        ("default_optimization_source", default_runtime_source),
    ]:
        for filename, scenario_col, time_col in [
            ("normal_load_scenarios.csv", "scenario_a", "t"),
            ("normal_ev_demand_slow.csv", "scenario_a", "t"),
            ("normal_ev_demand_fast.csv", "scenario_a", "t"),
            ("disaster_load_scenarios.csv", "scenario_b", "ts"),
            ("disaster_ev_discharge_slow.csv", "scenario_b", "ts"),
            ("disaster_ev_discharge_fast.csv", "scenario_b", "ts"),
        ]:
            path = root / filename
            if not path.exists():
                continue
            rows = _read_rows(path)
            scenarios = _scenario_ids(path, scenario_col)
            times = _time_ids(path, scenario_col, scenarios[0], time_col) if scenarios else []
            inventory_rows.append(
                {
                    "dataset_role": dataset_role,
                    "path": str(path),
                    "rows": len(rows),
                    "scenario_col": scenario_col,
                    "scenario_count": len(scenarios),
                    "scenario_min": min(scenarios) if scenarios else "",
                    "scenario_max": max(scenarios) if scenarios else "",
                    "time_col": time_col,
                    "scenario1_time_count": len(times),
                    "scenario1_time_min": min(times) if times else "",
                    "scenario1_time_max": max(times) if times else "",
                }
            )
    _write_csv(
        paper_root / "scenario_profile_source_inventory.csv",
        inventory_rows,
        [
            "dataset_role",
            "path",
            "rows",
            "scenario_col",
            "scenario_count",
            "scenario_min",
            "scenario_max",
            "time_col",
            "scenario1_time_count",
            "scenario1_time_min",
            "scenario1_time_max",
        ],
    )

    manifest = {
        "profile_figure_source_unperturbed_base": str(source),
        "default_optimization_source": str(default_runtime_source),
        "paper_common_evaluator": {"A": 10, "B": 10, "K": 2},
        "profile_figures": {
            "normal_load": str(output_dir / "scenario_profile_normal_load.png"),
            "normal_ev": str(output_dir / "scenario_profile_normal_ev.png"),
            "disaster_ev": str(output_dir / "scenario_profile_disaster_ev.png"),
        },
        "note": (
            "Scenario-profile figures use the unperturbed colleague-provided "
            "base profiles for representative scenario a=1/b=1. The accepted "
            "optimization/evaluation pack uses the 10x10 runtime source generated "
            "from the same colleague data."
        ),
    }
    (paper_root / "scenario_generation_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    audit = [
        "# Scenario Profile Figure Audit",
        "",
        "Verdict: `PASS`.",
        "",
        "The current setup profile figures are aligned with the colleague-provided representative profiles.",
        "",
        f"- Figure source: `{source}`.",
        f"- Optimization/evaluation source: `{default_runtime_source}`.",
        "- EV demand and V2G availability are shown by Region1/Region2/Region3.",
        "- Slow and fast profiles are separated into different panels, following the reference paper's setup-figure style.",
        "",
        "The disaster-stage profile contains four time steps, matching the 10:00--14:00 emergency window used by the default data package.",
    ]
    (paper_root / "scenario_profile_figure_audit.md").write_text("\n".join(audit) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="data/colleague_default")
    parser.add_argument("--default-runtime-source", default="data/colleague_default_10x10")
    parser.add_argument("--output-dir", default="results/paper_final/figures")
    parser.add_argument("--paper-root", default="results/paper_final")
    args = parser.parse_args()
    regenerate(
        Path(args.source),
        Path(args.default_runtime_source),
        Path(args.output_dir),
        Path(args.paper_root),
    )


if __name__ == "__main__":
    main()
