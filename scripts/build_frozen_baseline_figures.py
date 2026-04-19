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
    lines = [
        "\\begin{table}[htbp]",
        "\\centering",
        "\\small",
        f"\\caption{{{_escape_latex(caption)}}}",
        f"\\label{{{_escape_latex(label)}}}",
        "\\begin{tabular}{" + " | ".join(["l"] * len(columns)) + "}",
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


def _plot_plan_panel(axis, title: str, plan_path: Path | None, critical_buses: Sequence[int]) -> None:
    positions = _tree_positions()
    axis.set_title(title, fontsize=10)
    axis.axis("off")
    for left, right in IEEE33_EDGES:
        x1, y1 = positions[left]
        x2, y2 = positions[right]
        axis.plot([x1, x2], [y1, y2], color="0.75", linewidth=1.2, zorder=1)

    all_x = [positions[bus][0] for bus in sorted(positions)]
    all_y = [positions[bus][1] for bus in sorted(positions)]
    axis.scatter(all_x, all_y, s=26, color="0.88", edgecolors="0.55", zorder=2)

    critical_x = [positions[bus][0] for bus in critical_buses]
    critical_y = [positions[bus][1] for bus in critical_buses]
    axis.scatter(
        critical_x,
        critical_y,
        s=110,
        facecolors="none",
        edgecolors="tab:red",
        linewidths=1.5,
        zorder=3,
    )

    if plan_path is None or not plan_path.exists():
        axis.text(0.5, 0.5, "Plan unavailable", transform=axis.transAxes, ha="center", va="center")
        return

    rows = _read_plan_rows(plan_path)
    slow_x: list[float] = []
    slow_y: list[float] = []
    slow_size: list[float] = []
    fast_x: list[float] = []
    fast_y: list[float] = []
    fast_size: list[float] = []
    labels: list[tuple[float, float, str]] = []

    for row in rows:
        bus = int(row["bus"])
        is_open = int(row["is_open"])
        n_sl = int(row["n_sl"])
        n_fa = int(row["n_fa"])
        x, y = positions[bus]
        if n_sl > 0:
            slow_x.append(x)
            slow_y.append(y)
            slow_size.append(16.0 + 4.0 * math.sqrt(max(n_sl, 1)))
        if n_fa > 0:
            fast_x.append(x)
            fast_y.append(y)
            fast_size.append(24.0 + 12.0 * math.sqrt(max(n_fa, 1)))
        if is_open:
            labels.append((x, y, f"{bus}\nS{n_sl}/F{n_fa}"))

    if slow_x:
        axis.scatter(slow_x, slow_y, s=slow_size, color="tab:blue", alpha=0.85, zorder=4, label="slow")
    if fast_x:
        axis.scatter(
            fast_x,
            fast_y,
            s=fast_size,
            color="tab:orange",
            marker="s",
            alpha=0.75,
            zorder=5,
            label="fast",
        )
    for x, y, label in labels:
        axis.text(x + 0.10, y + 0.10, label, fontsize=7, zorder=6)
    if slow_x or fast_x:
        axis.legend(fontsize=7, loc="lower right")


def _plot_plan_maps(
    *,
    figure_path: Path,
    panels: Sequence[tuple[str, Path | None]],
    critical_buses: Sequence[int],
    ncols: int,
) -> None:
    nrows = math.ceil(len(panels) / ncols)
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(6.2 * ncols, 4.3 * nrows), squeeze=False)
    for axis in axes.flatten():
        axis.axis("off")
    for axis, (title, plan_path) in zip(axes.flatten(), panels):
        _plot_plan_panel(axis, title, plan_path, critical_buses)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=180)
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
            ("integrated runtime12", plan_lookup.get("integrated_mainline_runtime12")),
            ("deterministic runtime12", plan_lookup.get("deterministic_mean_value_runtime12")),
            ("EV 1.5x runtime12", plan_lookup.get("ev_penetration_1_5x_runtime12")),
            ("EV 2.0x runtime12", plan_lookup.get("ev_penetration_2_0x_runtime12")),
        ],
        critical_buses=critical_buses,
        ncols=2,
    )
    figure_paths.append(str(runtime_maps_path))

    paper_case123_path = figures_dir / "ieee33_paper_like_maps_case123.png"
    _plot_plan_maps(
        figure_path=paper_case123_path,
        panels=[
            ("integrated paper-like", plan_lookup.get("integrated_mainline_paper_like")),
            ("normal-only paper-like", plan_lookup.get("normal_only_paper_like")),
            ("disaster-only paper-like", plan_lookup.get("disaster_only_paper_like")),
        ],
        critical_buses=critical_buses,
        ncols=3,
    )
    figure_paths.append(str(paper_case123_path))

    paper_case456_path = figures_dir / "ieee33_paper_like_maps_case4_56.png"
    _plot_plan_maps(
        figure_path=paper_case456_path,
        panels=[
            ("deterministic paper-like", plan_lookup.get("deterministic_mean_value_paper_like")),
            ("EV 1.5x paper-like", plan_lookup.get("ev_penetration_1_5x_paper_like")),
            ("EV 2.0x paper-like", plan_lookup.get("ev_penetration_2_0x_paper_like")),
        ],
        critical_buses=critical_buses,
        ncols=3,
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
