"""Plot full-Benders separation violation traces for K scaling."""

from __future__ import annotations

import csv
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_ROOT = REPO_ROOT / "results" / "paper_final"
LOG_DIR = PAPER_ROOT / "full_benders_scaling_runs" / "milp" / "logs"
COMPLETION_LOG_DIR = PAPER_ROOT / "full_benders_completion_runs" / "milp" / "logs"
FIGURES_DIR = PAPER_ROOT / "figures"
TRACE_CSV = PAPER_ROOT / "full_benders_k_violation_trace.csv"
K_VALUES = (1, 2, 3, 5, 7, 10)
COMPLETION_OVERRIDES = {
    7: "full_benders_completion_A10_B010_K07_top003_max300",
    10: "full_benders_completion_A10_B010_K10_top003_max300",
}
EPSILON = 100.0


def _load_trace(k: int) -> list[dict[str, float | int | str]]:
    if k in COMPLETION_OVERRIDES:
        path = COMPLETION_LOG_DIR / f"{COMPLETION_OVERRIDES[k]}_run.json"
        source_run_role = "completion_high_budget"
    else:
        path = LOG_DIR / f"full_benders_A10_B010_K{k:02d}_top003_run.json"
        source_run_role = "standard_100_iteration_scaling"
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    validation_level = str(payload["validation_level"])
    rows: list[dict[str, float | int | str]] = []
    for item in payload["iteration_log"]["iterations"]:
        rows.append(
            {
                "K": k,
                "iteration": int(item["iteration_id"]) + 1,
                "violation": float(item["separation_violation_value"]),
                "violation_bound": float(item.get("separation_obj_bound") or 0.0),
                "validation_level": validation_level,
                "final_violation": float(summary["final_violation_upper_bound"]),
                "runtime_seconds": float(summary.get("runtime_seconds") or 0.0),
                "iterations_total": int(summary["iteration_count"]),
                "cuts_total": int(summary["cut_count"]),
                "source_run_role": source_run_role,
            }
        )
    return rows


def _write_trace(rows: list[dict[str, float | int | str]]) -> None:
    TRACE_CSV.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "K",
        "iteration",
        "violation",
        "violation_bound",
        "validation_level",
        "final_violation",
        "runtime_seconds",
        "iterations_total",
        "cuts_total",
        "source_run_role",
    ]
    with TRACE_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _plot(rows: list[dict[str, float | int | str]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    colors = {
        1: "#4c78a8",
        2: "#f58518",
        3: "#54a24b",
        5: "#b279a2",
        7: "#e45756",
        10: "#72b7b2",
    }
    grouped = {
        k: [row for row in rows if int(row["K"]) == k]
        for k in K_VALUES
    }

    plt.figure(figsize=(7.6, 4.8))
    for k, trace in grouped.items():
        if not trace:
            continue
        marker = "s" if trace[-1]["validation_level"] == "smoke_only" else "o"
        plt.plot(
            [int(row["iteration"]) for row in trace],
            [max(float(row["violation"]), 1e-6) for row in trace],
            label=f"K={k}",
            color=colors[k],
            linewidth=1.8,
            marker=marker,
            markevery=max(1, len(trace) // 8),
            markersize=4.5,
        )
    plt.axhline(EPSILON, color="#333333", linestyle="--", linewidth=1.1, label=r"$\epsilon=100$")
    plt.yscale("log")
    plt.xlabel("Benders iteration")
    plt.ylabel("Separation violation")
    plt.title("Full Benders K-scaling violation traces")
    plt.grid(True, which="both", alpha=0.22)
    plt.legend(ncol=3, frameon=False)
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "full_benders_k_violation_trace.png", dpi=240)
    plt.close()

    plt.figure(figsize=(7.2, 4.6))
    for k in (7, 10):
        trace = grouped[k]
        plt.plot(
            [int(row["iteration"]) for row in trace],
            [max(float(row["violation"]), 1e-6) for row in trace],
            label=f"K={k} violation",
            color=colors[k],
            linewidth=2.0,
        )
        plt.plot(
            [int(row["iteration"]) for row in trace],
            [max(float(row["violation_bound"]), 1e-6) for row in trace],
            label=f"K={k} bound",
            color=colors[k],
            linewidth=1.5,
            linestyle="--",
        )
    plt.axhline(EPSILON, color="#333333", linestyle=":", linewidth=1.2, label=r"$\epsilon=100$")
    plt.yscale("log")
    plt.xlabel("Benders iteration")
    plt.ylabel("Residual")
    plt.title("High-K stress residuals")
    plt.grid(True, which="both", alpha=0.22)
    plt.legend(ncol=2, frameon=False)
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / "full_benders_high_k_violation_bound_trace.png", dpi=240)
    plt.close()


def main() -> None:
    rows: list[dict[str, float | int | str]] = []
    for k in K_VALUES:
        rows.extend(_load_trace(k))
    _write_trace(rows)
    _plot(rows)
    print(
        {
            "trace_csv": str(TRACE_CSV),
            "all_k_figure": str(FIGURES_DIR / "full_benders_k_violation_trace.png"),
            "high_k_figure": str(FIGURES_DIR / "full_benders_high_k_violation_bound_trace.png"),
        }
    )


if __name__ == "__main__":
    main()
