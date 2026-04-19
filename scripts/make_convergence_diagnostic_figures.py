"""Figure generation for the Round 12.5 convergence diagnostic pack."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt


def _read_summary_rows(summary_csv_path: str | Path) -> list[dict[str, str]]:
    with Path(summary_csv_path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_logs(logs_dir: str | Path) -> dict[str, dict[str, object]]:
    payloads: dict[str, dict[str, object]] = {}
    for path in sorted(Path(logs_dir).glob("*_diagnostic.json")):
        payloads[path.stem.replace("_diagnostic", "")] = json.loads(path.read_text(encoding="utf-8"))
    return payloads


def _numeric(row: dict[str, str], key: str) -> float:
    raw = row.get(key, "")
    if raw in {"", "None", "nan", None}:
        return 0.0
    return float(raw)


def _bool(row: dict[str, str], key: str) -> bool:
    raw = str(row.get(key, "")).strip().lower()
    return raw in {"true", "1", "yes"}


def _label_color(label: str) -> str:
    return {
        "exact_zero": "tab:green",
        "epsilon_stop": "tab:orange",
        "max_iter_noncert": "tab:red",
    }.get(label, "tab:gray")


def _write_placeholder(path: Path, *, title: str, lines: list[str]) -> None:
    fig, ax = plt.subplots(figsize=(10, 3))
    ax.axis("off")
    ax.set_title(title)
    ax.text(0.02, 0.8, "\n".join(lines), va="top")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def generate_figures(
    *,
    summary_csv_path: str | Path,
    logs_dir: str | Path,
    figures_dir: str | Path,
) -> list[str]:
    """Generate the required convergence diagnostic PNG figures."""

    summary_rows = _read_summary_rows(summary_csv_path)
    logs = _load_logs(logs_dir)
    output_dir = Path(figures_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    if not summary_rows:
        for file_name, title in (
            ("validation_category_overview.png", "Validation categories"),
            ("violation_vs_iteration_budget.png", "Violation vs iteration budget"),
            ("runtime_breakdown_by_run.png", "Runtime breakdown"),
            ("cut_efficacy_trace.png", "Cut efficacy trace"),
            ("outage_repeat_patterns.png", "Outage repeat patterns"),
        ):
            path = output_dir / file_name
            _write_placeholder(path, title=title, lines=["No diagnostic runs available."])
            created.append(str(path))
        return created

    run_ids = [row["run_id"] for row in summary_rows]
    x = list(range(len(summary_rows)))

    # validation_category_overview.png
    fig, ax = plt.subplots(figsize=(12, 5))
    heights = []
    for row in summary_rows:
        label = row["diagnosis_label"]
        if label == "exact_zero":
            heights.append(3)
        elif label == "epsilon_stop":
            heights.append(2)
        else:
            heights.append(1)
    ax.bar(x, heights, color=[_label_color(row["diagnosis_label"]) for row in summary_rows])
    ax.set_yticks([1, 2, 3])
    ax.set_yticklabels(["max_iter_noncert", "epsilon_stop", "exact_zero"])
    ax.set_xticks(x)
    ax.set_xticklabels(run_ids, rotation=35, ha="right")
    ax.set_title("Diagnostic validation categories")
    fig.tight_layout()
    path = output_dir / "validation_category_overview.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    # violation_vs_iteration_budget.png
    fig, ax = plt.subplots(figsize=(12, 5))
    for row in summary_rows:
        ax.scatter(
            _numeric(row, "max_iterations"),
            _numeric(row, "final_violation_upper_bound"),
            color=_label_color(row["diagnosis_label"]),
        )
        ax.annotate(row["run_id"], (_numeric(row, "max_iterations"), _numeric(row, "final_violation_upper_bound")), fontsize=7)
    ax.set_xlabel("Max iteration budget")
    ax.set_ylabel("Final violation upper bound")
    ax.set_title("Violation vs iteration budget")
    fig.tight_layout()
    path = output_dir / "violation_vs_iteration_budget.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    # runtime_breakdown_by_run.png
    fig, ax = plt.subplots(figsize=(12, 5))
    master = [_numeric(row, "master_runtime_sec_total") for row in summary_rows]
    separation = [_numeric(row, "separation_runtime_sec_total") for row in summary_rows]
    dual = [_numeric(row, "dual_resolve_runtime_sec_total") for row in summary_rows]
    ax.bar(x, master, label="master")
    ax.bar(x, separation, bottom=master, label="separation")
    ax.bar(
        x,
        dual,
        bottom=[master[i] + separation[i] for i in range(len(summary_rows))],
        label="dual / cut generation",
    )
    ax.set_xticks(x)
    ax.set_xticklabels(run_ids, rotation=35, ha="right")
    ax.set_ylabel("Runtime (sec)")
    ax.set_title("Runtime breakdown by run")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = output_dir / "runtime_breakdown_by_run.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    # cut_efficacy_trace.png
    fig, axes = plt.subplots(nrows=2, ncols=1, figsize=(12, 7), squeeze=False)
    top_ax = axes[0][0]
    bottom_ax = axes[1][0]
    plotted = False
    for run_id, payload in logs.items():
        diagnostic_payload = payload.get("diagnostics", {})
        sequence = diagnostic_payload.get("cut_efficacy_sequence", [])
        if not isinstance(sequence, list) or not sequence:
            continue
        x_values = list(range(1, len(sequence) + 1))
        old_violations = [float(item.get("old_master_violation") or 0.0) for item in sequence]
        objective_deltas = [float(item.get("post_cut_master_objective_change") or 0.0) for item in sequence]
        top_ax.plot(x_values, old_violations, marker="o", label=run_id)
        bottom_ax.plot(x_values, objective_deltas, marker="o", label=run_id)
        plotted = True
    top_ax.set_title("Old-master cut violation by generated cut")
    top_ax.set_ylabel("Violation")
    bottom_ax.set_title("Post-cut master objective change")
    bottom_ax.set_xlabel("Generated cut index")
    bottom_ax.set_ylabel("Objective delta")
    if plotted:
        top_ax.legend(fontsize=8)
        bottom_ax.legend(fontsize=8)
    else:
        top_ax.text(0.5, 0.5, "No generated-cut traces available", ha="center", va="center")
        bottom_ax.text(0.5, 0.5, "No generated-cut traces available", ha="center", va="center")
    fig.tight_layout()
    path = output_dir / "cut_efficacy_trace.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    # outage_repeat_patterns.png
    fig, ax = plt.subplots(figsize=(12, 5))
    outage_flags = [1 if _bool(row, "repeated_outage_flag") else 0 for row in summary_rows]
    cut_flags = [1 if _bool(row, "repeated_cut_signature_flag") else 0 for row in summary_rows]
    width = 0.38
    ax.bar([value - width / 2 for value in x], outage_flags, width=width, label="repeated outage")
    ax.bar([value + width / 2 for value in x], cut_flags, width=width, label="repeated cut signature")
    ax.set_xticks(x)
    ax.set_xticklabels(run_ids, rotation=35, ha="right")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["no", "yes"])
    ax.set_title("Outage / cut repeat patterns")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = output_dir / "outage_repeat_patterns.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    return created


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--logs-dir", required=True)
    parser.add_argument("--figures-dir", required=True)
    args = parser.parse_args()
    generate_figures(
        summary_csv_path=args.summary_csv,
        logs_dir=args.logs_dir,
        figures_dir=args.figures_dir,
    )
