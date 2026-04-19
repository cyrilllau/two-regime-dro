"""Figure generation for the Round 13 cut-process diagnostic pack."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt


def _read_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _numeric(row: dict[str, str], key: str) -> float:
    raw = row.get(key, "")
    if raw in {"", "None", None}:
        return 0.0
    return float(raw)


def _bool(row: dict[str, str], key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"true", "1", "yes"}


def generate_figures(
    *,
    summary_csv_path: str | Path,
    cut_diagnostics_csv_path: str | Path,
    figures_dir: str | Path,
) -> list[str]:
    """Generate the Round 13 cut-process figures."""

    summary_rows = _read_rows(summary_csv_path)
    cut_rows = _read_rows(cut_diagnostics_csv_path)
    output_dir = Path(figures_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    created: list[str] = []

    if not summary_rows:
        return created

    run_labels = [row["run_id"] for row in summary_rows]
    x = list(range(len(summary_rows)))

    fig, ax = plt.subplots(figsize=(13, 5))
    viol = [_numeric(row, "final_violation_upper_bound") for row in summary_rows]
    colors = [
        "tab:green"
        if row["diagnosis_label"] == "exact_zero"
        else "tab:orange"
        if row["diagnosis_label"] == "epsilon_stop"
        else "tab:red"
        for row in summary_rows
    ]
    ax.bar(x, viol, color=colors)
    ax.set_xticks(x)
    ax.set_xticklabels(run_labels, rotation=35, ha="right")
    ax.set_ylabel("Final violation upper bound")
    ax.set_title("Round 13 final violation by run")
    fig.tight_layout()
    path = output_dir / "cut_process_violation_summary.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    fig, ax = plt.subplots(figsize=(13, 5))
    plan_change = [_numeric(row, "plan_change_cut_count") for row in summary_rows]
    alpha_only = [_numeric(row, "alpha_lambda_only_cut_count") for row in summary_rows]
    ax.bar(x, plan_change, label="plan-changing cuts")
    ax.bar(x, alpha_only, bottom=plan_change, label="alpha/lambda-only cuts")
    ax.set_xticks(x)
    ax.set_xticklabels(run_labels, rotation=35, ha="right")
    ax.set_ylabel("Generated cut count")
    ax.set_title("Plan-changing vs alpha/lambda-only cuts")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = output_dir / "cut_process_effect_breakdown.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    grouped: dict[str, dict[str, float]] = {}
    for row in summary_rows:
        group = row["comparison_group"]
        grouped.setdefault(group, {})
        grouped[group][row["variant"]] = _numeric(row, "final_violation_upper_bound")

    groups = list(grouped.keys())
    baseline_values = [grouped[group].get("baseline", 0.0) for group in groups]
    improved_values = [grouped[group].get("improved", 0.0) for group in groups]
    fig, ax = plt.subplots(figsize=(13, 5))
    width = 0.38
    ax.bar([value - width / 2 for value in range(len(groups))], baseline_values, width=width, label="baseline")
    ax.bar([value + width / 2 for value in range(len(groups))], improved_values, width=width, label="improved")
    ax.set_xticks(list(range(len(groups))))
    ax.set_xticklabels(groups, rotation=35, ha="right")
    ax.set_ylabel("Final violation upper bound")
    ax.set_title("Baseline vs improved violation")
    ax.legend(fontsize=8)
    fig.tight_layout()
    path = output_dir / "cut_process_baseline_vs_improved.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))

    if cut_rows:
        fig, ax = plt.subplots(figsize=(13, 5))
        repeat_outage = [1 if _bool(row, "repeated_outage_flag") else 0 for row in cut_rows]
        repeat_signature = [1 if _bool(row, "repeated_cut_signature_flag") else 0 for row in cut_rows]
        cut_labels = [f"{row['run_id']}:{row['cut_id']}" for row in cut_rows]
        width = 0.38
        ax.bar([value - width / 2 for value in range(len(cut_rows))], repeat_outage, width=width, label="repeated outage")
        ax.bar([value + width / 2 for value in range(len(cut_rows))], repeat_signature, width=width, label="repeated signature")
        ax.set_xticks(list(range(len(cut_rows))))
        ax.set_xticklabels(cut_labels, rotation=45, ha="right")
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["no", "yes"])
        ax.set_title("Repeated outage / signature flags by generated cut")
        ax.legend(fontsize=8)
        fig.tight_layout()
        path = output_dir / "cut_process_repeat_flags.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        created.append(str(path))

    return created


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--cut-diagnostics-csv", required=True)
    parser.add_argument("--figures-dir", required=True)
    args = parser.parse_args()
    generate_figures(
        summary_csv_path=args.summary_csv,
        cut_diagnostics_csv_path=args.cut_diagnostics_csv,
        figures_dir=args.figures_dir,
    )
