"""Figure generation for the Round 11 experiment pack."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt


def _read_summary_rows(summary_csv_path: str | Path) -> list[dict[str, str]]:
    with Path(summary_csv_path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_iteration_logs(logs_dir: str | Path) -> dict[str, dict[str, object]]:
    payloads: dict[str, dict[str, object]] = {}
    for path in sorted(Path(logs_dir).glob("*_iteration_log.json")):
        payloads[path.stem.replace("_iteration_log", "")] = json.loads(
            path.read_text(encoding="utf-8")
        )
    return payloads


def _plan_csv_paths(plans_dir: str | Path) -> list[Path]:
    return sorted(Path(plans_dir).glob("*_plan.csv"))


def _read_plan_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _numeric(row: dict[str, str], key: str) -> float:
    return float(row[key])


def generate_figures(
    *,
    summary_csv_path: str | Path,
    plans_dir: str | Path,
    logs_dir: str | Path,
    figures_dir: str | Path,
) -> list[str]:
    """Generate the required auditable PNG figures."""

    summary_rows = _read_summary_rows(summary_csv_path)
    iteration_logs = _load_iteration_logs(logs_dir)
    plan_paths = _plan_csv_paths(plans_dir)
    output_dir = Path(figures_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    run_ids = [row["run_id"] for row in summary_rows]
    x = range(len(run_ids))

    # objective_components.png
    fig, ax = plt.subplots(figsize=(12, 5))
    construction = [_numeric(row, "construction_cost") for row in summary_rows]
    normal = [_numeric(row, "weighted_normal_term") for row in summary_rows]
    disaster = [_numeric(row, "disaster_master_term") for row in summary_rows]
    ax.bar(x, construction, label="construction")
    ax.bar(x, normal, bottom=construction, label="weighted normal")
    ax.bar(
        x,
        disaster,
        bottom=[construction[i] + normal[i] for i in range(len(run_ids))],
        label="disaster master",
    )
    ax.set_xticks(list(x))
    ax.set_xticklabels(run_ids, rotation=45, ha="right")
    ax.set_ylabel("Objective component value")
    ax.set_title("Objective components by run")
    ax.legend()
    fig.tight_layout()
    path = output_dir / "objective_components.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    # benchmark_comparison.png
    fig, ax = plt.subplots(figsize=(12, 5))
    totals = [_numeric(row, "total_objective") for row in summary_rows]
    colors = [
        "tab:green"
        if row["validation_level"] == "exact"
        else "tab:orange"
        if row["validation_level"] == "epsilon_certified"
        else "tab:blue"
        for row in summary_rows
    ]
    ax.bar(list(x), totals, color=colors)
    ax.set_xticks(list(x))
    ax.set_xticklabels(run_ids, rotation=45, ha="right")
    ax.set_ylabel("Total objective")
    ax.set_title("Benchmark comparison by run")
    fig.tight_layout()
    path = output_dir / "benchmark_comparison.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    # iteration_trace.png
    fig, ax = plt.subplots(figsize=(12, 5))
    plotted = False
    for run_id, payload in iteration_logs.items():
        lower_bounds = payload.get("lower_bound_sequence", [])
        if not lower_bounds:
            continue
        ax.plot(range(len(lower_bounds)), lower_bounds, marker="o", label=run_id)
        plotted = True
    ax.set_xlabel("Iteration")
    ax.set_ylabel("RMP objective / lower bound")
    ax.set_title("Iteration trace")
    if plotted:
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "No iteration traces available", ha="center", va="center")
    fig.tight_layout()
    path = output_dir / "iteration_trace.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    # plan_map.png
    selected_plan_paths = plan_paths[: min(4, len(plan_paths))]
    fig, axes = plt.subplots(
        nrows=max(1, len(selected_plan_paths)),
        ncols=1,
        figsize=(12, 3 * max(1, len(selected_plan_paths))),
        squeeze=False,
    )
    for axis, plan_path in zip(axes.flatten(), selected_plan_paths):
        plan_rows = _read_plan_rows(plan_path)
        buses = [int(row["bus"]) for row in plan_rows]
        totals_by_bus = [int(row["n_sl"]) + int(row["n_fa"]) for row in plan_rows]
        critical_markers = [
            totals_by_bus[index]
            for index, row in enumerate(plan_rows)
            if int(row["is_critical"]) == 1
        ]
        critical_buses = [
            buses[index]
            for index, row in enumerate(plan_rows)
            if int(row["is_critical"]) == 1
        ]
        axis.bar(buses, totals_by_bus, color="tab:blue")
        if critical_buses:
            axis.scatter(
                critical_buses,
                critical_markers,
                color="tab:red",
                marker="x",
                label="critical bus",
            )
            axis.legend(loc="upper right", fontsize=8)
        axis.set_title(plan_path.stem.replace("_plan", ""))
        axis.set_xlabel("Bus")
        axis.set_ylabel("Installed chargers")
    fig.tight_layout()
    path = output_dir / "plan_map.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    return created


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--plans-dir", required=True)
    parser.add_argument("--logs-dir", required=True)
    parser.add_argument("--figures-dir", required=True)
    args = parser.parse_args()
    generate_figures(
        summary_csv_path=args.summary_csv,
        plans_dir=args.plans_dir,
        logs_dir=args.logs_dir,
        figures_dir=args.figures_dir,
    )
