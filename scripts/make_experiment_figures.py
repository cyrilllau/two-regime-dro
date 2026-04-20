"""Figure generation for the Round 12 experiment pack."""

from __future__ import annotations

import csv
import json
import math
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


IEEE33_EDGES = [
    (1, 2), (2, 3), (2, 19), (3, 4), (3, 23), (4, 5), (5, 6), (6, 7), (6, 26),
    (7, 8), (8, 9), (9, 10), (10, 11), (11, 12), (12, 13), (13, 14), (14, 15),
    (15, 16), (16, 17), (17, 18), (19, 20), (20, 21), (21, 22), (23, 24),
    (24, 25), (26, 27), (27, 28), (28, 29), (29, 30), (30, 31), (31, 32), (32, 33),
]

IEEE33_POSITIONS = {
    1: (0.0, 0.0),
    2: (1.2, 0.0),
    3: (2.4, 0.0),
    4: (3.6, 0.0),
    5: (4.8, 0.0),
    6: (6.0, 0.0),
    7: (7.2, 0.0),
    8: (8.4, 0.0),
    9: (9.6, 0.0),
    10: (10.8, 0.0),
    11: (12.0, 0.0),
    12: (13.2, 0.0),
    13: (14.4, 0.0),
    14: (15.6, 0.0),
    15: (16.8, 0.0),
    16: (18.0, 0.0),
    17: (19.2, 0.0),
    18: (20.4, 0.0),
    19: (1.2, -1.6),
    20: (1.2, -3.2),
    21: (2.4, -3.2),
    22: (3.6, -3.2),
    23: (2.4, 1.6),
    24: (2.4, 3.2),
    25: (3.6, 3.2),
    26: (6.0, 1.6),
    27: (7.2, 1.6),
    28: (8.4, 1.6),
    29: (9.6, 1.6),
    30: (10.8, 1.6),
    31: (12.0, 1.6),
    32: (13.2, 1.6),
    33: (14.4, 1.6),
}

IEEE33_BUBBLE_OFFSETS = {
    1: (-0.55, 0.9),
    2: (-0.65, 0.95),
    3: (0.0, -1.05),
    4: (0.0, 0.95),
    5: (0.0, -1.05),
    6: (0.0, -1.05),
    7: (0.0, -1.05),
    8: (0.0, -1.05),
    9: (0.0, -1.05),
    10: (0.0, -1.05),
    11: (0.0, -1.05),
    12: (0.0, -1.05),
    13: (0.0, -1.05),
    14: (0.0, 0.95),
    15: (0.0, -1.05),
    16: (0.0, -1.05),
    17: (0.0, -1.05),
    18: (0.0, -1.05),
    19: (-0.8, 0.0),
    20: (0.0, -1.0),
    21: (0.0, -1.0),
    22: (0.0, -1.0),
    23: (-0.85, 0.0),
    24: (0.0, 1.0),
    25: (0.0, 1.0),
    26: (0.0, 1.0),
    27: (0.0, 1.0),
    28: (0.0, 1.0),
    29: (0.0, 1.0),
    30: (0.0, 1.0),
    31: (0.0, 1.0),
    32: (0.0, 1.0),
    33: (0.0, 1.0),
}

PAPER_STYLE_PANEL_TITLES = {
    "integrated_mainline_paper_like": "(a) Case 1: Proposed model",
    "normal_only_paper_like": "(b) Case 2: Only normal operation considered",
    "disaster_only_paper_like": "(c) Case 3: Only disaster resilience considered",
    "deterministic_mean_value_paper_like": "Deterministic mean-value benchmark",
    "ev_penetration_1_5x_paper_like": "EV penetration 1.5x",
    "ev_penetration_2_0x_paper_like": "EV penetration 2.0x",
    "S0_baseline": "Calibration baseline",
    "normal_only_paper_like_tuned": "Tuned normal-only winner",
    "normal_only_paper_like_tuned_D1_scale_0_85": "Demand scale 0.85",
    "normal_only_paper_like_tuned_D2_scale_0_70": "Demand scale 0.70",
    "paper_case1_target_semantics": "Paper Fig. 6 target semantics",
}


def _draw_ieee33_substation(axis) -> None:
    axis.plot([-0.65, -0.1], [0.0, 0.0], color="black", linewidth=1.2, zorder=1)
    axis.plot([-0.75, -0.75], [-0.28, 0.28], color="black", linewidth=1.2, zorder=1)
    axis.plot([-0.9, -0.9], [-0.42, 0.42], color="black", linewidth=1.2, zorder=1)


def _plot_paper_style_panel(axis, run_id: str, plan_lookup: dict[str, Path]) -> None:
    plan_rows = _read_plan_rows(plan_lookup[run_id])
    critical_buses = {
        int(row["bus"])
        for row in plan_rows
        if int(row["is_critical"]) == 1
    }
    installed_rows = [
        row for row in plan_rows if int(row["is_open"]) == 1
    ]

    axis.set_aspect("equal")
    axis.axis("off")
    axis.set_title(PAPER_STYLE_PANEL_TITLES.get(run_id, run_id), fontsize=13, pad=10)

    for left, right in IEEE33_EDGES:
        x1, y1 = IEEE33_POSITIONS[left]
        x2, y2 = IEEE33_POSITIONS[right]
        axis.plot([x1, x2], [y1, y2], color="black", linewidth=1.1, zorder=1)
    _draw_ieee33_substation(axis)

    buses = sorted(IEEE33_POSITIONS)
    critical_x = [IEEE33_POSITIONS[bus][0] for bus in buses if bus in critical_buses]
    critical_y = [IEEE33_POSITIONS[bus][1] for bus in buses if bus in critical_buses]
    noncritical_x = [IEEE33_POSITIONS[bus][0] for bus in buses if bus not in critical_buses]
    noncritical_y = [IEEE33_POSITIONS[bus][1] for bus in buses if bus not in critical_buses]

    if critical_x:
        axis.scatter(
            critical_x,
            critical_y,
            s=54,
            facecolors="#c83c23",
            edgecolors="black",
            linewidths=0.8,
            zorder=3,
            label="Critical load",
        )
    if noncritical_x:
        axis.scatter(
            noncritical_x,
            noncritical_y,
            s=54,
            facecolors="white",
            edgecolors="black",
            linewidths=0.8,
            zorder=2,
            label="Non-critical load",
        )

    for bus in buses:
        x, y = IEEE33_POSITIONS[bus]
        axis.text(
            x,
            y + 0.33,
            str(bus),
            ha="center",
            va="bottom",
            fontsize=9,
            zorder=4,
        )

    evse_label_added = False
    for row in installed_rows:
        bus = int(row["bus"])
        slow = int(row["n_sl"])
        fast = int(row["n_fa"])
        x, y = IEEE33_POSITIONS[bus]
        dx, dy = IEEE33_BUBBLE_OFFSETS.get(bus, (0.0, 1.0))
        bx, by = x + dx, y + dy
        bubble_size = 430 + 7 * math.sqrt(max(slow + 4 * fast, 1))
        axis.plot(
            [x, bx],
            [y, by],
            color="#3f5523",
            linewidth=1.45,
            alpha=0.98,
            zorder=4,
        )
        axis.scatter(
            [x],
            [y],
            s=26,
            facecolors="none",
            edgecolors="#3f5523",
            linewidths=1.0,
            zorder=4.5,
        )
        axis.scatter(
            [bx],
            [by],
            s=bubble_size,
            facecolors="#7caf3e",
            edgecolors="#3a5d1c",
            linewidths=1.0,
            alpha=0.92,
            zorder=5,
            label="EVCS(No. slow EVSE,\nNo. fast EVSE)" if not evse_label_added else None,
        )
        evse_label_added = True
        axis.text(
            bx,
            by,
            f"{slow}/{fast}",
            ha="center",
            va="center",
            fontsize=9,
            fontweight="bold",
            color="#1f2f0f",
            zorder=6,
        )

    axis.set_xlim(-1.2, 23.7)
    axis.set_ylim(-4.8, 4.6)
    axis.legend(
        loc="lower right",
        fontsize=8.3,
        frameon=True,
        fancybox=False,
        framealpha=1.0,
        borderpad=0.55,
        handletextpad=0.5,
        labelspacing=0.35,
    )


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
    if ncols == 1:
        figsize = (17.4, 5.0 * nrows + 0.8)
    else:
        figsize = (16.6, 5.1 * nrows)
    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=figsize,
        squeeze=False,
    )
    for axis in axes.flatten():
        axis.axis("off")

    for axis, run_id in zip(axes.flatten(), selected):
        _plot_paper_style_panel(axis, run_id, plan_lookup)

    fig.suptitle(title, fontsize=15, y=0.992)
    fig.tight_layout(rect=(0.01, 0.01, 0.995, 0.982), pad=0.9)
    fig.savefig(path, dpi=220, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def write_plan_map_figure(
    *,
    run_ids: Sequence[str],
    plans_dir: str | Path,
    title: str,
    path: str | Path,
    ncols: int = 1,
) -> Path:
    """Public helper that reuses the paper-style IEEE-33 plan-map rendering."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _plot_plan_maps(
        run_ids=run_ids,
        plan_lookup=_plan_csv_lookup(plans_dir),
        title=title,
        path=output_path,
        ncols=ncols,
    )
    return output_path


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
