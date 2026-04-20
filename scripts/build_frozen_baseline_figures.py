"""Build Round 14 frozen-baseline figures and tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import matplotlib.pyplot as plt
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import ensure_directory  # noqa: E402


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

VALIDATION_CHAIN_ROWS = [
    {
        "round": "02",
        "validated_layer": "reference disaster primal",
        "status": "exact toy + runtime fixture",
        "key_result": "Eq. (26)-(32) fixed-(x,delta,b) primal LP validated",
    },
    {
        "round": "03",
        "validated_layer": "canonicalizer + auto dual",
        "status": "exact objective/KKT matching",
        "key_result": "mechanical canonicalization and auto-dual agree with primal",
    },
    {
        "round": "04",
        "validated_layer": "paper dual",
        "status": "exact samplewise decomposition",
        "key_result": "beta/gamma/phi decomposition matches primal/auto-dual",
    },
    {
        "round": "05",
        "validated_layer": "separation oracles",
        "status": "exact tiny validation",
        "key_result": "outage enumeration, budget support, outer-DRO LP, separation exactness",
    },
    {
        "round": "05.5",
        "validated_layer": "separation hardening",
        "status": "coefficient/model-shape validation",
        "key_result": "runtime bounds and edge-case checks added without changing math",
    },
    {
        "round": "06",
        "validated_layer": "first-stage + normal block",
        "status": "toy-case + runtime-smoke validated",
        "key_result": "Eq. (10)-(25) production blocks built and checked",
    },
    {
        "round": "06.5",
        "validated_layer": "unit/interface hardening",
        "status": "analytic Eq. (24) guard",
        "key_result": "voltage-drop scaling and first-stage API protected by tests",
    },
    {
        "round": "07",
        "validated_layer": "fixed-cut master",
        "status": "toy-case + runtime-smoke validated",
        "key_result": "restricted master for Eq. (33), (37)-(39) built",
    },
    {
        "round": "07.5",
        "validated_layer": "master/cut interface",
        "status": "real-cut interface hardened",
        "key_result": "paper-dual decomposition enters master without flattening",
    },
    {
        "round": "08",
        "validated_layer": "single generated cut step",
        "status": "one-step efficacy validated",
        "key_result": "master -> separation -> cut -> master path built",
    },
    {
        "round": "09",
        "validated_layer": "full Benders engine",
        "status": "tiny exact + runtime smoke",
        "key_result": "iterative Benders loop validated against brute force on tiny case",
    },
    {
        "round": "10",
        "validated_layer": "independent disaster exact oracle",
        "status": "tiny cross-check + readiness",
        "key_result": "primal-exact disaster oracle agrees with production tiny path",
    },
    {
        "round": "11",
        "validated_layer": "experiment interpretation pack",
        "status": "packaging only",
        "key_result": "benchmark packaging and explicit validation labels introduced",
    },
    {
        "round": "12",
        "validated_layer": "paper-style experiment pack",
        "status": "packaging only",
        "key_result": "paper-like and runtime-directional families packaged with failures visible",
    },
    {
        "round": "12.5",
        "validated_layer": "convergence diagnostics",
        "status": "diagnostic only",
        "key_result": "exact_zero / epsilon_stop / max_iter_noncert separated",
    },
    {
        "round": "13",
        "validated_layer": "cut-process diagnostics",
        "status": "diagnostic only",
        "key_result": "repeated outages observed; exact duplicate structured cuts not observed",
    },
]


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path} must contain a YAML mapping.")
    return dict(raw)


def resolve_report_paths(
    config: Mapping[str, Any],
    *,
    report_root_override: str | Path | None,
) -> dict[str, str]:
    if report_root_override is None:
        return {
            "figures_dir": str(config["figures_dir"]),
            "tables_dir": str(config["tables_dir"]),
            "appendix_csv_path": str(config["appendix_csv_path"]),
        }
    report_root = Path(report_root_override)
    return {
        "figures_dir": str(report_root / "figures" / "baseline"),
        "tables_dir": str(report_root / "tables"),
        "appendix_csv_path": str(report_root / "frozen_baseline_review_appendix.csv"),
    }


def _read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> str:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        file_path.write_text("", encoding="utf-8")
        return str(file_path)
    fieldnames = list(rows[0].keys())
    with file_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return str(file_path)


def _numeric(row: Mapping[str, Any], key: str) -> float:
    raw = row.get(key, "")
    if raw in {"", None, "None", "nan"}:
        return 0.0
    return float(raw)


def _maybe_int(row: Mapping[str, Any], key: str) -> int:
    raw = row.get(key, "")
    if raw in {"", None, "None"}:
        return 0
    return int(float(raw))


def _ensure_plot_dir(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _validation_color(label: str) -> str:
    return {
        "exact": "tab:green",
        "epsilon_certified": "tab:orange",
        "smoke_only": "tab:blue",
        "failed": "tab:red",
    }.get(label, "tab:gray")


def _escape_latex(text: Any) -> str:
    value = str(text)
    replacements = {
        "\\": "\\textbackslash{}",
        "&": "\\&",
        "%": "\\%",
        "$": "\\$",
        "#": "\\#",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def _write_latex_table(
    *,
    path: str | Path,
    caption: str,
    label: str,
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    headers: Sequence[str] | None = None,
) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    headers = list(headers or columns)
    if list(columns) == ["round", "validated_layer", "status", "key_result"]:
        column_spec = "p{0.8cm} p{3.0cm} p{3.0cm} p{7.0cm}"
    else:
        column_spec = " | ".join(["l"] * len(columns))
    lines = [
        "\\begin{table}[htbp]",
        "\\centering",
        "\\footnotesize",
        "\\setlength{\\tabcolsep}{4pt}",
        "\\renewcommand{\\arraystretch}{1.12}",
        f"\\caption{{{_escape_latex(caption)}}}",
        f"\\label{{{_escape_latex(label)}}}",
        "\\begin{tabular}{" + column_spec + "}",
        "\\hline",
        " & ".join(_escape_latex(header) for header in headers) + " \\\\",
        "\\hline",
    ]
    for row in rows:
        lines.append(
            " & ".join(_escape_latex(row.get(column, "")) for column in columns) + " \\\\"
        )
    lines.extend(["\\hline", "\\end{tabular}", "\\end{table}", ""])
    target.write_text("\n".join(lines), encoding="utf-8")
    return str(target)


def _load_run_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _plot_validation_status(rows: Sequence[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    y = list(range(len(rows)))
    values = []
    for row in rows:
        label = row["validation_level"]
        if label == "exact":
            values.append(3)
        elif label == "epsilon_certified":
            values.append(2)
        elif label == "smoke_only":
            values.append(1)
        else:
            values.append(0)
    ax.barh(y, values, color=[_validation_color(row["validation_level"]) for row in rows])
    ax.set_yticks(y)
    ax.set_yticklabels([row["run_id"] for row in rows], fontsize=8)
    ax.set_xticks([0, 1, 2, 3])
    ax.set_xticklabels(["failed", "smoke_only", "epsilon_certified", "exact"])
    ax.set_title("Validation status overview")
    ax.set_xlabel("Validation category")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _plot_objective_components(rows: Sequence[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 7))
    y = list(range(len(rows)))
    construction = [_numeric(row, "construction_cost") for row in rows]
    normal = [_numeric(row, "weighted_normal_term") for row in rows]
    disaster = [_numeric(row, "disaster_master_term") for row in rows]
    ax.barh(y, construction, label="construction")
    ax.barh(y, normal, left=construction, label="weighted normal")
    ax.barh(
        y,
        disaster,
        left=[construction[index] + normal[index] for index in range(len(rows))],
        label="disaster master",
    )
    ax.set_yticks(y)
    ax.set_yticklabels([row["run_id"] for row in rows], fontsize=8)
    ax.set_xlabel("Objective component value")
    ax.set_title("Objective components by run (weighted normal term only)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _plot_safe_benchmark_comparison(rows: Sequence[dict[str, Any]], path: Path) -> None:
    families = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        family = row["family_name"]
        if family not in grouped:
            grouped[family] = []
            families.append(family)
        grouped[family].append(row)

    fig, axes = plt.subplots(nrows=3, ncols=1, figsize=(13, 11), squeeze=False)
    metrics = [
        ("opened_bus_count", "Opened buses"),
        ("total_slow_chargers", "Total slow chargers"),
        ("total_fast_chargers", "Total fast chargers"),
    ]
    for axis, (metric, title) in zip(axes.flatten(), metrics):
        x_positions: list[float] = []
        heights: list[float] = []
        labels: list[str] = []
        colors: list[str] = []
        cursor = 0.0
        for family in families:
            family_rows = grouped[family]
            for row in family_rows:
                x_positions.append(cursor)
                heights.append(_numeric(row, metric))
                labels.append(row["run_id"])
                colors.append(_validation_color(row["validation_level"]))
                cursor += 1.0
            cursor += 0.7
        axis.bar(x_positions, heights, color=colors)
        axis.set_xticks(x_positions)
        axis.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        axis.set_ylabel(title)
        axis.set_title(title)
    fig.suptitle(
        "Benchmark comparison (safe view: within-family structural counts; do not rank heterogeneous runs by raw total objective)",
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _tree_positions() -> dict[int, tuple[float, float]]:
    children: dict[int, list[int]] = {}
    parent: dict[int, int] = {1: 0}
    for left, right in IEEE33_EDGES:
        children.setdefault(left, []).append(right)
        parent[right] = left
    for key in children:
        children[key].sort()
    y_counter = [0.0]
    positions: dict[int, tuple[float, float]] = {}

    def assign(node: int, depth: int) -> float:
        descendants = children.get(node, [])
        if not descendants:
            y_value = y_counter[0]
            y_counter[0] += 1.0
            positions[node] = (float(depth), y_value)
            return y_value
        child_positions = [assign(child, depth + 1) for child in descendants]
        y_value = sum(child_positions) / len(child_positions)
        positions[node] = (float(depth), y_value)
        return y_value

    assign(1, 0)
    max_y = max(value[1] for value in positions.values())
    return {node: (x, max_y - y) for node, (x, y) in positions.items()}


def _read_plan_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _draw_ieee33_substation(axis) -> None:
    axis.plot([-0.65, -0.1], [0.0, 0.0], color="black", linewidth=1.2, zorder=1)
    axis.plot([-0.75, -0.75], [-0.28, 0.28], color="black", linewidth=1.2, zorder=1)
    axis.plot([-0.9, -0.9], [-0.42, 0.42], color="black", linewidth=1.2, zorder=1)


def _plot_plan_panel(axis, title: str, plan_path: Path | None, critical_buses: Sequence[int]) -> None:
    axis.set_title(title, fontsize=12, pad=8)
    axis.set_aspect("equal")
    axis.axis("off")
    for left, right in IEEE33_EDGES:
        x1, y1 = IEEE33_POSITIONS[left]
        x2, y2 = IEEE33_POSITIONS[right]
        axis.plot([x1, x2], [y1, y2], color="black", linewidth=1.1, zorder=1)
    _draw_ieee33_substation(axis)

    all_buses = sorted(IEEE33_POSITIONS)
    critical_set = set(int(bus) for bus in critical_buses)
    critical_x = [IEEE33_POSITIONS[bus][0] for bus in all_buses if bus in critical_set]
    critical_y = [IEEE33_POSITIONS[bus][1] for bus in all_buses if bus in critical_set]
    noncritical_x = [IEEE33_POSITIONS[bus][0] for bus in all_buses if bus not in critical_set]
    noncritical_y = [IEEE33_POSITIONS[bus][1] for bus in all_buses if bus not in critical_set]

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

    for bus in all_buses:
        x, y = IEEE33_POSITIONS[bus]
        axis.text(x, y + 0.33, str(bus), ha="center", va="bottom", fontsize=9, zorder=4)

    if plan_path is None or not plan_path.exists():
        axis.text(0.5, 0.5, "Plan unavailable", transform=axis.transAxes, ha="center", va="center")
        axis.set_xlim(-1.2, 21.0)
        axis.set_ylim(-4.5, 4.3)
        return

    rows = _read_plan_rows(plan_path)
    installed_rows = [row for row in rows if int(row["is_open"]) == 1]
    evse_label_added = False
    for row in installed_rows:
        bus = int(row["bus"])
        n_sl = int(row["n_sl"])
        n_fa = int(row["n_fa"])
        x, y = IEEE33_POSITIONS[bus]
        dx, dy = IEEE33_BUBBLE_OFFSETS.get(bus, (0.0, 1.0))
        bx, by = x + dx, y + dy
        bubble_size = 430 + 7 * math.sqrt(max(n_sl + 4 * n_fa, 1))
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
            f"{n_sl}/{n_fa}",
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


def _plot_plan_maps(
    *,
    figure_path: Path,
    panels: Sequence[tuple[str, Path | None]],
    critical_buses: Sequence[int],
    ncols: int,
) -> None:
    nrows = math.ceil(len(panels) / ncols)
    if ncols == 1:
        figsize = (17.8, 5.1 * nrows + 0.8)
    else:
        figsize = (16.8, 5.1 * nrows)
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=figsize, squeeze=False)
    for axis in axes.flatten():
        axis.axis("off")
    for axis, (title, plan_path) in zip(axes.flatten(), panels):
        _plot_plan_panel(axis, title, plan_path, critical_buses)
    fig.tight_layout(rect=(0.01, 0.01, 0.995, 0.992), pad=0.9)
    fig.savefig(figure_path, dpi=220, bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)


def _load_iteration_log(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _violation_sequence(payload: dict[str, Any]) -> list[float]:
    violations: list[float] = []
    for record in payload.get("iterations", []):
        value = record.get("separation_violation_value")
        if value is None:
            value = 0.0
        violations.append(float(value))
    if not violations and "certificate" in payload:
        certificate = payload["certificate"]
        if isinstance(certificate, Mapping):
            violations.append(float(certificate.get("final_violation_upper_bound") or 0.0))
    return violations


def _plot_iteration_traces(
    *,
    figure_path: Path,
    traces: Sequence[tuple[str, Path | None]],
) -> None:
    fig, axes = plt.subplots(nrows=len(traces), ncols=1, figsize=(12, 3.6 * len(traces)), squeeze=False)
    for axis, (title, path) in zip(axes.flatten(), traces):
        payload = _load_iteration_log(path)
        axis.set_title(title, fontsize=10)
        if payload is None:
            axis.text(0.5, 0.5, "Iteration log unavailable", ha="center", va="center")
            axis.axis("off")
            continue
        lower_bounds = [float(value) for value in payload.get("lower_bound_sequence", [])]
        violations = _violation_sequence(payload)
        if lower_bounds:
            axis.plot(range(len(lower_bounds)), lower_bounds, marker="o", label="lower bound")
        twin = axis.twinx()
        if violations:
            twin.plot(range(len(violations)), violations, marker="x", color="tab:red", label="violation")
        axis.set_xlabel("Iteration")
        axis.set_ylabel("Lower bound")
        twin.set_ylabel("Violation")
        handles1, labels1 = axis.get_legend_handles_labels()
        handles2, labels2 = twin.get_legend_handles_labels()
        if handles1 or handles2:
            axis.legend(handles1 + handles2, labels1 + labels2, fontsize=8, loc="best")
    fig.tight_layout()
    fig.savefig(figure_path, dpi=180)
    plt.close(fig)


def _plot_convergence_overview(rows: Sequence[dict[str, Any]], path: Path) -> None:
    fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(13, 5), squeeze=False)
    ax1, ax2 = axes[0]
    for row in rows:
        ax1.scatter(
            _numeric(row, "max_iterations"),
            _numeric(row, "final_violation_upper_bound"),
            color=_validation_color(row["validation_level"]),
        )
        ax1.annotate(row["run_id"], (_numeric(row, "max_iterations"), _numeric(row, "final_violation_upper_bound")), fontsize=7)
    ax1.set_xlabel("Iteration budget")
    ax1.set_ylabel("Final violation upper bound")
    ax1.set_title("Convergence diagnostics: violation vs iteration budget")

    diagnosis_counts = {"exact_zero": 0, "epsilon_stop": 0, "max_iter_noncert": 0}
    for row in rows:
        diagnosis_counts[row["diagnosis_label"]] = diagnosis_counts.get(row["diagnosis_label"], 0) + 1
    labels = list(diagnosis_counts.keys())
    values = [diagnosis_counts[label] for label in labels]
    ax2.bar(labels, values, color=["tab:green", "tab:orange", "tab:red"])
    ax2.set_title("Convergence diagnostics: label counts")
    ax2.set_ylabel("Run count")
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _plot_cut_process_overview(rows: Sequence[dict[str, Any]], path: Path) -> None:
    baseline_rows = [row for row in rows if row.get("variant") == "baseline"]
    fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(13, 5), squeeze=False)
    ax1, ax2 = axes[0]
    x = list(range(len(baseline_rows)))
    ax1.bar(
        [value - 0.2 for value in x],
        [_numeric(row, "repeated_outage_count") for row in baseline_rows],
        width=0.4,
        label="repeated outages",
    )
    ax1.bar(
        [value + 0.2 for value in x],
        [_numeric(row, "repeated_cut_signature_count") for row in baseline_rows],
        width=0.4,
        label="repeated signatures",
    )
    ax1.set_xticks(x)
    ax1.set_xticklabels([row["comparison_group"] for row in baseline_rows], rotation=35, ha="right", fontsize=8)
    ax1.set_title("Cut-process repeats")
    ax1.legend(fontsize=8)

    ax2.bar(
        [value - 0.2 for value in x],
        [_numeric(row, "plan_change_cut_count") for row in baseline_rows],
        width=0.4,
        label="plan-changing cuts",
    )
    ax2.bar(
        [value + 0.2 for value in x],
        [_numeric(row, "alpha_lambda_only_cut_count") for row in baseline_rows],
        width=0.4,
        label="alpha/lambda-only cuts",
    )
    ax2.set_xticks(x)
    ax2.set_xticklabels([row["comparison_group"] for row in baseline_rows], rotation=35, ha="right", fontsize=8)
    ax2.set_title("Cut-process effect profile")
    ax2.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def _load_experiment_rows(config: Mapping[str, Any], archive_info: Mapping[str, Any]) -> list[dict[str, Any]]:
    current_rows = [dict(row) for row in _read_csv_rows(REPO_ROOT / config["current_outputs"]["experiment_summary_csv"])]
    for row in current_rows:
        row["source_group"] = "current_experiment"
    regen_info = archive_info.get("regenerated_certified_small")
    if regen_info:
        regen_rows = [dict(row) for row in _read_csv_rows(regen_info["summary_path"])]
        for row in regen_rows:
            row["source_group"] = "regenerated_certified_small"
        current_rows = regen_rows + current_rows
    return current_rows


def _build_run_inventory(
    *,
    experiment_rows: Sequence[dict[str, Any]],
    convergence_rows: Sequence[dict[str, Any]],
    cut_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for row in experiment_rows:
        inventory.append(
            {
                "run_source": row["source_group"],
                "family": row["family_name"],
                "case_name": row["case_name"],
                "parameter_regime": row["parameter_regime"],
                "validation_level": row["validation_level"],
                "stop_reason": row["stop_reason"],
                "iteration_count": row["iteration_count"],
                "cut_count": row["cut_count"],
                "final_violation_upper_bound": row["final_violation_upper_bound"],
            }
        )
    for row in convergence_rows:
        inventory.append(
            {
                "run_source": "convergence_diagnostic",
                "family": "convergence_diagnostic",
                "case_name": row["case_name"],
                "parameter_regime": row["parameter_regime"],
                "validation_level": row["validation_level"],
                "stop_reason": row["stop_reason"],
                "iteration_count": row["iteration_count"],
                "cut_count": row["cut_count"],
                "final_violation_upper_bound": row["final_violation_upper_bound"],
            }
        )
    for row in cut_rows:
        inventory.append(
            {
                "run_source": "cut_process",
                "family": row["comparison_group"],
                "case_name": row["case_name"],
                "parameter_regime": row["parameter_regime"],
                "validation_level": row["validation_level"],
                "stop_reason": row["stop_reason"],
                "iteration_count": row["iteration_count"],
                "cut_count": row["cut_count"],
                "final_violation_upper_bound": row["final_violation_upper_bound"],
            }
        )
    return inventory


def _build_objective_rows(experiment_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in experiment_rows:
        rows.append(
            {
                "run_id": row["run_id"],
                "family_name": row["family_name"],
                "validation_level": row["validation_level"],
                "construction_cost": row["construction_cost"],
                "weighted_normal_term": row["weighted_normal_term"],
                "unweighted_normal_term": row["unweighted_normal_term"],
                "disaster_master_term": row["disaster_master_term"],
                "total_objective": row["total_objective"],
                "note": "Compare total objective only under the weighted-normal convention and with family caveats.",
            }
        )
    return rows


def _build_noncert_rows(
    *,
    experiment_rows: Sequence[dict[str, Any]],
    convergence_rows: Sequence[dict[str, Any]],
    cut_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in experiment_rows:
        if row["validation_level"] in {"smoke_only", "failed"} or row["stop_reason"] == "max_iterations":
            rows.append(
                {
                    "source": row["source_group"],
                    "run_id": row["run_id"],
                    "case_name": row["case_name"],
                    "parameter_regime": row["parameter_regime"],
                    "validation_level": row["validation_level"],
                    "stop_reason": row["stop_reason"],
                    "iteration_count": row["iteration_count"],
                    "cut_count": row["cut_count"],
                    "final_violation_upper_bound": row["final_violation_upper_bound"],
                }
            )
    for row in convergence_rows:
        if row["diagnosis_label"] == "max_iter_noncert":
            rows.append(
                {
                    "source": "convergence_diagnostic",
                    "run_id": row["run_id"],
                    "case_name": row["case_name"],
                    "parameter_regime": row["parameter_regime"],
                    "validation_level": row["validation_level"],
                    "stop_reason": row["stop_reason"],
                    "iteration_count": row["iteration_count"],
                    "cut_count": row["cut_count"],
                    "final_violation_upper_bound": row["final_violation_upper_bound"],
                }
            )
    for row in cut_rows:
        if row["diagnosis_label"] == "max_iter_noncert":
            rows.append(
                {
                    "source": "cut_process",
                    "run_id": row["run_id"],
                    "case_name": row["case_name"],
                    "parameter_regime": row["parameter_regime"],
                    "validation_level": row["validation_level"],
                    "stop_reason": row["stop_reason"],
                    "iteration_count": row["iteration_count"],
                    "cut_count": row["cut_count"],
                    "final_violation_upper_bound": row["final_violation_upper_bound"],
                }
            )
    return rows


def _build_appendix_rows(
    *,
    experiment_rows: Sequence[dict[str, Any]],
    convergence_rows: Sequence[dict[str, Any]],
    cut_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in experiment_rows:
        rows.append(
            {
                "source": row["source_group"],
                "run_id": row["run_id"],
                "family_or_group": row["family_name"],
                "case_name": row["case_name"],
                "parameter_regime": row["parameter_regime"],
                "validation_level": row["validation_level"],
                "stop_reason": row["stop_reason"],
                "iteration_count": row["iteration_count"],
                "cut_count": row["cut_count"],
                "final_violation_upper_bound": row["final_violation_upper_bound"],
                "total_objective": row["total_objective"],
                "construction_cost": row["construction_cost"],
                "weighted_normal_term": row["weighted_normal_term"],
                "disaster_master_term": row["disaster_master_term"],
                "notes": "",
            }
        )
    for row in convergence_rows:
        rows.append(
            {
                "source": "convergence_diagnostic",
                "run_id": row["run_id"],
                "family_or_group": "convergence_diagnostic",
                "case_name": row["case_name"],
                "parameter_regime": row["parameter_regime"],
                "validation_level": row["validation_level"],
                "stop_reason": row["stop_reason"],
                "iteration_count": row["iteration_count"],
                "cut_count": row["cut_count"],
                "final_violation_upper_bound": row["final_violation_upper_bound"],
                "total_objective": row["total_objective"],
                "construction_cost": row["construction_cost"],
                "weighted_normal_term": row["weighted_normal_term"],
                "disaster_master_term": row["disaster_master_term"],
                "notes": row.get("notes", ""),
            }
        )
    for row in cut_rows:
        rows.append(
            {
                "source": "cut_process",
                "run_id": row["run_id"],
                "family_or_group": row["comparison_group"],
                "case_name": row["case_name"],
                "parameter_regime": row["parameter_regime"],
                "validation_level": row["validation_level"],
                "stop_reason": row["stop_reason"],
                "iteration_count": row["iteration_count"],
                "cut_count": row["cut_count"],
                "final_violation_upper_bound": row["final_violation_upper_bound"],
                "total_objective": row["total_objective"],
                "construction_cost": row["construction_cost"],
                "weighted_normal_term": row["weighted_normal_term"],
                "disaster_master_term": row["disaster_master_term"],
                "notes": row.get("notes", ""),
            }
        )
    return rows


def build_figures_and_tables(
    *,
    config_path: str | Path = "configs/reports/frozen_baseline_review.yaml",
    archive_info: Mapping[str, Any] | None = None,
    report_root_override: str | Path | None = None,
) -> dict[str, Any]:
    config = load_yaml_file(config_path)
    archive_info = dict(archive_info or {})
    resolved = resolve_report_paths(config, report_root_override=report_root_override)
    figures_dir = _ensure_plot_dir(REPO_ROOT / resolved["figures_dir"])
    tables_dir = _ensure_plot_dir(REPO_ROOT / resolved["tables_dir"])

    experiment_rows = _load_experiment_rows(config, archive_info)
    convergence_rows = [dict(row) for row in _read_csv_rows(REPO_ROOT / config["current_outputs"]["convergence_summary_csv"])]
    cut_process_rows = [dict(row) for row in _read_csv_rows(REPO_ROOT / config["current_outputs"]["cut_process_summary_csv"])]

    validation_chain_csv = _write_csv(tables_dir / "validation_chain_summary.csv", VALIDATION_CHAIN_ROWS)
    validation_chain_tex = _write_latex_table(
        path=tables_dir / "validation_chain_summary.tex",
        caption="Validation chain summary for the frozen pre-improvement baseline.",
        label="tab:validation-chain-summary",
        rows=VALIDATION_CHAIN_ROWS,
        columns=["round", "validated_layer", "status", "key_result"],
        headers=["Round", "Validated layer", "Status", "Key result"],
    )
    run_inventory_rows = _build_run_inventory(
        experiment_rows=experiment_rows,
        convergence_rows=convergence_rows,
        cut_rows=cut_process_rows,
    )
    objective_rows = _build_objective_rows(experiment_rows)
    noncert_rows = _build_noncert_rows(
        experiment_rows=experiment_rows,
        convergence_rows=convergence_rows,
        cut_rows=cut_process_rows,
    )
    appendix_rows = _build_appendix_rows(
        experiment_rows=experiment_rows,
        convergence_rows=convergence_rows,
        cut_rows=cut_process_rows,
    )

    run_inventory_csv = _write_csv(tables_dir / "run_inventory.csv", run_inventory_rows)
    objective_csv = _write_csv(tables_dir / "objective_components.csv", objective_rows)
    noncert_csv = _write_csv(tables_dir / "noncertified_runs.csv", noncert_rows)
    appendix_csv = _write_csv(REPO_ROOT / resolved["appendix_csv_path"], appendix_rows)

    figure_paths: list[str] = []
    table_paths = [
        validation_chain_csv,
        validation_chain_tex,
        run_inventory_csv,
        objective_csv,
        noncert_csv,
        appendix_csv,
    ]

    validation_status_path = figures_dir / "validation_status_overview.png"
    _plot_validation_status(experiment_rows, validation_status_path)
    figure_paths.append(str(validation_status_path))

    objective_fig_path = figures_dir / "objective_components_by_run.png"
    _plot_objective_components(experiment_rows, objective_fig_path)
    figure_paths.append(str(objective_fig_path))

    safe_benchmark_path = figures_dir / "benchmark_comparison_safe.png"
    _plot_safe_benchmark_comparison(experiment_rows, safe_benchmark_path)
    figure_paths.append(str(safe_benchmark_path))

    plan_lookup: dict[str, Path] = {}
    for path in sorted((REPO_ROOT / config["current_outputs"]["experiment_plans_dir"]).glob("*_plan.csv")):
        plan_lookup[path.stem.replace("_plan", "")] = path
    regen_info = archive_info.get("regenerated_certified_small")
    if regen_info:
        regen_plans_dir = Path(regen_info["output_root"]) / "plans"
        if regen_plans_dir.exists():
            for path in sorted(regen_plans_dir.glob("*_plan.csv")):
                plan_lookup[path.stem.replace("_plan", "")] = path

    critical_buses = tuple(int(bus) for bus in config["critical_buses"])
    runtime_maps_path = figures_dir / "ieee33_runtime12_directional_maps.png"
    _plot_plan_maps(
        figure_path=runtime_maps_path,
        panels=[
            ("Integrated runtime12", plan_lookup.get("integrated_mainline_runtime12")),
            ("Deterministic runtime12", plan_lookup.get("deterministic_mean_value_runtime12")),
            ("EV penetration 1.5x runtime12", plan_lookup.get("ev_penetration_1_5x_runtime12")),
            ("EV penetration 2.0x runtime12", plan_lookup.get("ev_penetration_2_0x_runtime12")),
        ],
        critical_buses=critical_buses,
        ncols=2,
    )
    figure_paths.append(str(runtime_maps_path))

    runtime_maps_path_a = figures_dir / "ieee33_runtime12_directional_maps_a.png"
    _plot_plan_maps(
        figure_path=runtime_maps_path_a,
        panels=[
            ("Integrated runtime12", plan_lookup.get("integrated_mainline_runtime12")),
            ("Deterministic runtime12", plan_lookup.get("deterministic_mean_value_runtime12")),
        ],
        critical_buses=critical_buses,
        ncols=1,
    )
    figure_paths.append(str(runtime_maps_path_a))

    runtime_maps_path_b = figures_dir / "ieee33_runtime12_directional_maps_b.png"
    _plot_plan_maps(
        figure_path=runtime_maps_path_b,
        panels=[
            ("EV penetration 1.5x runtime12", plan_lookup.get("ev_penetration_1_5x_runtime12")),
            ("EV penetration 2.0x runtime12", plan_lookup.get("ev_penetration_2_0x_runtime12")),
        ],
        critical_buses=critical_buses,
        ncols=1,
    )
    figure_paths.append(str(runtime_maps_path_b))

    paper_case123_path = figures_dir / "ieee33_paper_like_maps_case123.png"
    _plot_plan_maps(
        figure_path=paper_case123_path,
        panels=[
            ("(a) Case 1: Proposed model", plan_lookup.get("integrated_mainline_paper_like")),
            ("(b) Case 2: Only normal operation considered", plan_lookup.get("normal_only_paper_like")),
            ("(c) Case 3: Only disaster resilience considered", plan_lookup.get("disaster_only_paper_like")),
        ],
        critical_buses=critical_buses,
        ncols=1,
    )
    figure_paths.append(str(paper_case123_path))

    paper_case456_path = figures_dir / "ieee33_paper_like_maps_case4_56.png"
    _plot_plan_maps(
        figure_path=paper_case456_path,
        panels=[
            ("Case 4: Deterministic mean-value", plan_lookup.get("deterministic_mean_value_paper_like")),
            ("Case 5: EV penetration 1.5x", plan_lookup.get("ev_penetration_1_5x_paper_like")),
            ("Case 6: EV penetration 2.0x", plan_lookup.get("ev_penetration_2_0x_paper_like")),
        ],
        critical_buses=critical_buses,
        ncols=1,
    )
    figure_paths.append(str(paper_case456_path))

    trace_lookup: dict[str, Path] = {}
    for path in sorted((REPO_ROOT / config["current_outputs"]["experiment_logs_dir"]).glob("*_iteration_log.json")):
        trace_lookup[path.stem.replace("_iteration_log", "")] = path
    for path in sorted((REPO_ROOT / config["current_outputs"]["convergence_logs_dir"]).glob("*_iteration_log.json")):
        trace_lookup[path.stem.replace("_iteration_log", "")] = path
    if regen_info:
        regen_logs_dir = Path(regen_info["output_root"]) / "logs"
        if regen_logs_dir.exists():
            for path in sorted(regen_logs_dir.glob("*_iteration_log.json")):
                trace_lookup[path.stem.replace("_iteration_log", "")] = path
    iteration_trace_path = figures_dir / "iteration_trace_selected.png"
    _plot_iteration_traces(
        figure_path=iteration_trace_path,
        traces=[
            ("Certified-small integrated anchor", trace_lookup.get(config["selected_trace_runs"]["certified_or_small"])),
            ("Runtime12 integrated smoke anchor", trace_lookup.get(config["selected_trace_runs"]["runtime_smoke"])),
            ("Hard exact-mode non-certified anchor", trace_lookup.get(config["selected_trace_runs"]["hard_exact_noncert"])),
        ],
    )
    figure_paths.append(str(iteration_trace_path))

    convergence_overview_path = figures_dir / "convergence_diagnostics_overview.png"
    _plot_convergence_overview(convergence_rows, convergence_overview_path)
    figure_paths.append(str(convergence_overview_path))

    cut_process_overview_path = figures_dir / "cut_process_diagnostics_overview.png"
    _plot_cut_process_overview(cut_process_rows, cut_process_overview_path)
    figure_paths.append(str(cut_process_overview_path))

    return {
        "figure_paths": figure_paths,
        "table_paths": table_paths,
        "validation_chain_rows": VALIDATION_CHAIN_ROWS,
        "experiment_rows": experiment_rows,
        "convergence_rows": convergence_rows,
        "cut_process_rows": cut_process_rows,
        "run_inventory_rows": run_inventory_rows,
        "objective_rows": objective_rows,
        "noncert_rows": noncert_rows,
        "appendix_rows": appendix_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/reports/frozen_baseline_review.yaml")
    parser.add_argument("--archive-metadata", default=None)
    args = parser.parse_args()
    archive_info = {}
    if args.archive_metadata:
        archive_info = json.loads(Path(args.archive_metadata).read_text(encoding="utf-8"))
    result = build_figures_and_tables(config_path=args.config, archive_info=archive_info)
    print(json.dumps({"figure_paths": result["figure_paths"], "table_paths": result["table_paths"]}, indent=2))


if __name__ == "__main__":
    main()
