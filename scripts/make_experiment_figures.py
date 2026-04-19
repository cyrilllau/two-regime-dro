"""Figure generation for the Round 12 experiment pack."""

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


def _plan_csv_lookup(plans_dir: str | Path) -> dict[str, Path]:
    lookup: dict[str, Path] = {}
    for path in sorted(Path(plans_dir).glob("*_plan.csv")):
        lookup[path.stem.replace("_plan", "")] = path
    return lookup


def _read_plan_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _numeric(row: dict[str, str], key: str) -> float:
    raw = row.get(key, "")
    if raw in {"", "nan", "None", None}:
        return 0.0
    return float(raw)


def _validation_color(label: str) -> str:
    mapping = {
        "exact": "tab:green",
        "epsilon_certified": "tab:orange",
        "smoke_only": "tab:blue",
        "failed": "tab:red",
    }
    return mapping.get(label, "tab:gray")


def _find_row(rows: Sequence[dict[str, str]], run_id: str) -> dict[str, str] | None:
    for row in rows:
        if row.get("run_id") == run_id:
            return row
    return None


def _write_placeholder(path: Path, *, title: str, lines: Sequence[str]) -> None:
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.axis("off")
    ax.set_title(title)
    ax.text(0.02, 0.75, "\n".join(lines), va="top")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_component_bars(
    *,
    rows: Sequence[dict[str, str]],
    title: str,
    path: Path,
) -> None:
    if not rows:
        _write_placeholder(path, title=title, lines=["No matching runs available."])
        return
    run_ids = [row["run_id"] for row in rows]
    construction = [_numeric(row, "construction_cost") for row in rows]
    normal = [_numeric(row, "weighted_normal_term") for row in rows]
    disaster = [_numeric(row, "disaster_master_term") for row in rows]
    x = list(range(len(rows)))

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(x, construction, label="construction")
    ax.bar(x, normal, bottom=construction, label="weighted normal")
    ax.bar(
        x,
        disaster,
        bottom=[construction[i] + normal[i] for i in range(len(rows))],
        label="disaster master",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(run_ids, rotation=25, ha="right")
    ax.set_ylabel("Objective component value")
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_validation_overview(
    *,
    rows: Sequence[dict[str, str]],
    path: Path,
) -> None:
    if not rows:
        _write_placeholder(path, title="Validation level overview", lines=["No runs available."])
        return
    run_ids = [row["run_id"] for row in rows]
    x = list(range(len(rows)))
    heights = []
    for row in rows:
        label = row["validation_level"]
        if label == "exact":
            heights.append(3)
        elif label == "epsilon_certified":
            heights.append(2)
        elif label == "smoke_only":
            heights.append(1)
        else:
            heights.append(0)

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(
        x,
        heights,
        color=[_validation_color(row["validation_level"]) for row in rows],
    )
    ax.set_yticks([0, 1, 2, 3])
    ax.set_yticklabels(["failed", "smoke_only", "epsilon_certified", "exact"])
    ax.set_xticks(x)
    ax.set_xticklabels(run_ids, rotation=35, ha="right")
    ax.set_title("Validation level overview")
    ax.set_ylabel("Validation category")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_iteration_trace(
    *,
    iteration_logs: dict[str, dict[str, object]],
    path: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(12, 5))
    plotted = False
    for run_id, payload in iteration_logs.items():
        lower_bounds = payload.get("lower_bound_sequence", [])
        stop_reason = str(payload.get("stop_reason", "unknown"))
        if not lower_bounds:
            continue
        ax.plot(
            range(len(lower_bounds)),
            lower_bounds,
            marker="o",
            label=f"{run_id} [{stop_reason}]",
        )
        plotted = True
    ax.set_xlabel("Iteration")
    ax.set_ylabel("RMP objective / lower bound")
    ax.set_title("Benders iteration trace (legend shows stop reason)")
    if plotted:
        ax.legend(fontsize=8)
    else:
        ax.text(0.5, 0.5, "No Benders iteration traces available", ha="center", va="center")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_plan_maps(
    *,
    run_ids: Sequence[str],
    plan_lookup: dict[str, Path],
    title: str,
    path: Path,
    ncols: int,
) -> None:
    selected = [run_id for run_id in run_ids if run_id in plan_lookup]
    if not selected:
        _write_placeholder(path, title=title, lines=["No plan CSVs available for this figure."])
        return

    nrows = (len(selected) + ncols - 1) // ncols
    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(6 * ncols, 3.5 * nrows),
        squeeze=False,
    )
    for axis in axes.flatten():
        axis.axis("off")

    for axis, run_id in zip(axes.flatten(), selected):
        axis.axis("on")
        plan_rows = _read_plan_rows(plan_lookup[run_id])
        buses = [int(row["bus"]) for row in plan_rows]
        totals_by_bus = [int(row["n_sl"]) + int(row["n_fa"]) for row in plan_rows]
        critical_buses = [
            buses[index]
            for index, row in enumerate(plan_rows)
            if int(row["is_critical"]) == 1
        ]
        critical_markers = [
            totals_by_bus[index]
            for index, row in enumerate(plan_rows)
            if int(row["is_critical"]) == 1
        ]
        open_buses = [
            buses[index]
            for index, row in enumerate(plan_rows)
            if int(row["is_open"]) == 1
        ]
        open_markers = [
            totals_by_bus[index]
            for index, row in enumerate(plan_rows)
            if int(row["is_open"]) == 1
        ]
        axis.bar(buses, totals_by_bus, color="tab:blue")
        if critical_buses:
            axis.scatter(critical_buses, critical_markers, color="tab:red", marker="x", label="critical")
        if open_buses:
            axis.scatter(open_buses, open_markers, color="black", marker="o", facecolors="none", label="open")
        axis.set_title(run_id)
        axis.set_xlabel("Bus")
        axis.set_ylabel("Installed chargers")
        if critical_buses or open_buses:
            axis.legend(fontsize=8)

    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


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
    plan_lookup = _plan_csv_lookup(plans_dir)
    output_dir = Path(figures_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    table_iii_rows = [
        row
        for run_id in (
            "integrated_mainline_paper_like",
            "normal_only_paper_like",
            "disaster_only_paper_like",
            "deterministic_mean_value_paper_like",
        )
        if (row := _find_row(summary_rows, run_id)) is not None
    ]
    path = output_dir / "tableIII_like_components.png"
    _plot_component_bars(rows=table_iii_rows, title="Case-1-like to Case-4-like components", path=path)
    created.append(str(path))

    table_iv_rows = [
        row
        for run_id in (
            "integrated_mainline_paper_like",
            "ev_penetration_1_5x_paper_like",
            "ev_penetration_2_0x_paper_like",
        )
        if (row := _find_row(summary_rows, run_id)) is not None
    ]
    path = output_dir / "tableIV_like_sensitivity.png"
    _plot_component_bars(rows=table_iv_rows, title="Base vs EV-penetration sensitivity", path=path)
    created.append(str(path))

    path = output_dir / "fig6_like_plan_maps.png"
    _plot_plan_maps(
        run_ids=(
            "integrated_mainline_paper_like",
            "normal_only_paper_like",
            "disaster_only_paper_like",
        ),
        plan_lookup=plan_lookup,
        title="Integrated / normal-only / disaster-only paper-like plans",
        path=path,
        ncols=1,
    )
    created.append(str(path))

    path = output_dir / "fig7_like_plan_map.png"
    _plot_plan_maps(
        run_ids=("deterministic_mean_value_paper_like",),
        plan_lookup=plan_lookup,
        title="Deterministic mean-value paper-like plan",
        path=path,
        ncols=1,
    )
    created.append(str(path))

    path = output_dir / "fig8_like_sensitivity_maps.png"
    _plot_plan_maps(
        run_ids=(
            "ev_penetration_1_5x_paper_like",
            "ev_penetration_2_0x_paper_like",
        ),
        plan_lookup=plan_lookup,
        title="EV-penetration paper-like plans",
        path=path,
        ncols=1,
    )
    created.append(str(path))

    path = output_dir / "validation_level_overview.png"
    _plot_validation_overview(rows=summary_rows, path=path)
    created.append(str(path))

    path = output_dir / "iteration_trace.png"
    _plot_iteration_trace(iteration_logs=iteration_logs, path=path)
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
