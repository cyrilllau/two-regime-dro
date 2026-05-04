"""Create scalability visualizations from paper_scale_matrix experiment summaries."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import matplotlib.pyplot as plt


RunData = dict[str, str]


SCENARIO_PATTERN = re.compile(
    r"paper_scale_matrix_A(?P<a>\d+)_B(?P<b>\d+)_k(?P<k>\d+)_(?P<mode>integrated|normal|deterministic)"
)
EV_PATTERN = re.compile(
    r"paper_scale_matrix_A(?P<a>\d+)_B(?P<b>\d+)_k(?P<k>\d+)_ev(?P<ev>.+)"
)
K_PATTERN = re.compile(r"paper_scale_matrix_A10x10_K(?P<k>\d+)_(?P<mode>integrated|deterministic|normal)")


def _read_rows(path: Path) -> list[RunData]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _to_float(value: str | None) -> float:
    if value is None:
        return float("nan")
    try:
        return float(value)
    except ValueError:
        return float("nan")


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _ensure_numeric(x: float) -> float:
    if x != x:
        return 0.0
    return x


def _extract_metadata(row: RunData) -> dict[str, str | int | float | None]:
    run_id = row["run_id"]
    mode: str | None = None
    a: int | None = None
    b: int | None = None
    k: int | None = None
    scenario_cells = None
    k_category = None
    ev_scale = None

    m = SCENARIO_PATTERN.match(run_id)
    if m:
        a = _to_int(m.group("a"))
        b = _to_int(m.group("b"))
        k = _to_int(m.group("k"))
        mode = m.group("mode")
        k_category = "scenario_grid"
    else:
        m = EV_PATTERN.match(run_id)
        if m:
            a = _to_int(m.group("a"))
            b = _to_int(m.group("b"))
            k = _to_int(m.group("k"))
            mode = f"ev_{m.group('ev')}"
            ev_scale = m.group("ev")
            k_category = "ev_sensitivity"
        else:
            m = K_PATTERN.match(run_id)
            if m:
                k = _to_int(m.group("k"))
                mode = m.group("mode")
                a = 10
                b = 10
                k_category = "k_scaling"
            else:
                mode = "other"
                k_category = "other"

    return {
        "run_id": run_id,
        "mode": mode,
        "A": a,
        "B": b,
        "k": k,
        "k_category": k_category,
        "ev_scale": ev_scale,
    }


def _prepare_rows(rows: list[RunData]) -> list[RunData]:
    prepared: list[RunData] = []
    for row in rows:
        meta = _extract_metadata(row)
        if meta["k_category"] == "other":
            continue
        merged = dict(row)
        for key, value in meta.items():
            if value is None:
                merged[key] = "" if key == "k_category" else ""
            else:
                merged[key] = value
        prepared.append(merged)
    return prepared


def _plot_scenario_scaling(rows: list[RunData], out_dir: Path) -> None:
    scenario_rows = [
        r for r in rows if r.get("k_category") == "scenario_grid"
    ]
    if not scenario_rows:
        return

    # sort by support size (A*B) then run type
    scenario_rows.sort(
        key=lambda row: (
            int(row.get("A") or 0) * int(row.get("B") or 0),
            row.get("mode"),
        )
    )

    x = [int(row["A"]) + int(row["B"]) for row in scenario_rows]
    labels = [
        f"{row['A']}x{row['B']} {row['mode']} (k={row['k']})"
        for row in scenario_rows
    ]

    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    ax_obj, ax_iter, ax_cuts, ax_vio = axes.flatten()

    values = [
        _to_float(row.get("total_objective")) for row in scenario_rows
    ]
    ax_obj.plot(range(len(scenario_rows)), values, marker="o", linestyle="-")
    for idx, row in enumerate(scenario_rows):
        ax_obj.text(
            idx,
            _ensure_numeric(values[idx]),
            row["mode"][:3],
            fontsize=8,
            ha="center",
            va="bottom",
            rotation=45,
        )
    ax_obj.set_title("Scenario scaling: objective")
    ax_obj.set_xlabel("A+B support size")
    ax_obj.set_ylabel("Total objective")
    ax_obj.set_xticks(range(len(labels)))
    ax_obj.set_xticklabels(labels, rotation=35, ha="right")

    normal_term = [_to_float(row.get("unweighted_normal_term")) for row in scenario_rows]
    disaster_term = [_to_float(row.get("disaster_master_term")) for row in scenario_rows]
    ax_iter.plot(range(len(scenario_rows)), normal_term, marker="o", label="unweighted normal")
    ax_iter.plot(range(len(scenario_rows)), disaster_term, marker="o", label="disaster")
    ax_iter.set_title("Scenario scaling: objective components")
    ax_iter.set_xlabel("A+B support size")
    ax_iter.set_ylabel("Component value")
    ax_iter.legend(fontsize=8)
    ax_iter.set_xticks(range(len(labels)))
    ax_iter.set_xticklabels(labels, rotation=35, ha="right")

    iter_vals = [_to_float(row.get("iteration_count")) for row in scenario_rows]
    ax_cuts.plot(range(len(scenario_rows)), iter_vals, marker="o", label="iteration")
    cut_vals = [_to_float(row.get("cut_count")) for row in scenario_rows]
    ax_cuts.plot(range(len(scenario_rows)), cut_vals, marker="o", label="cuts")
    ax_cuts.set_title("Scenario scaling: convergence effort")
    ax_cuts.set_xlabel("A+B support size")
    ax_cuts.set_ylabel("Count")
    ax_cuts.legend(fontsize=8)
    ax_cuts.set_xticks(range(len(labels)))
    ax_cuts.set_xticklabels(labels, rotation=35, ha="right")

    vio_vals = [_to_float(row.get("final_violation_upper_bound")) for row in scenario_rows]
    ax_vio.plot(range(len(scenario_rows)), vio_vals, marker="o")
    ax_vio.set_title("Scenario scaling: final violation")
    ax_vio.set_xlabel("A+B support size")
    ax_vio.set_ylabel("final_violation_upper_bound")
    ax_vio.set_xticks(range(len(labels)))
    ax_vio.set_xticklabels(labels, rotation=35, ha="right")

    fig.tight_layout()
    path = out_dir / "paper_scale_matrix_scenario_scaling.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _plot_k_scaling(rows: list[RunData], out_dir: Path) -> None:
    k_rows = [r for r in rows if r.get("k_category") == "k_scaling"]
    if not k_rows:
        return
    k_rows.sort(key=lambda row: (int(row["k"] or 0), str(row["mode"])))

    labels = [f"K={row['k']} {row['mode']}" for row in k_rows]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    ax_obj, ax_iter, ax_cuts, ax_vio = axes.flatten()

    obj = [_to_float(row.get("total_objective")) for row in k_rows]
    ax_obj.plot(range(len(k_rows)), obj, marker="o")
    ax_obj.set_title("K scaling: total objective")
    ax_obj.set_ylabel("Total objective")
    ax_obj.set_xlabel("Run")
    ax_obj.set_xticks(range(len(labels)))
    ax_obj.set_xticklabels(labels, rotation=40, ha="right")

    iter_counts = [_to_float(row.get("iteration_count")) for row in k_rows]
    cuts = [_to_float(row.get("cut_count")) for row in k_rows]
    ax_iter.plot(range(len(k_rows)), iter_counts, marker="o", label="iterations")
    ax_iter.plot(range(len(k_rows)), cuts, marker="o", label="cuts")
    ax_iter.set_title("K scaling: iterations and cuts")
    ax_iter.set_xlabel("Run")
    ax_iter.set_ylabel("Count")
    ax_iter.legend(fontsize=8)
    ax_iter.set_xticks(range(len(labels)))
    ax_iter.set_xticklabels(labels, rotation=40, ha="right")

    disaster = [_to_float(row.get("disaster_master_term")) for row in k_rows]
    normal = [_to_float(row.get("unweighted_normal_term")) for row in k_rows]
    ax_cuts.plot(range(len(k_rows)), normal, marker="o", label="unweighted normal")
    ax_cuts.plot(range(len(k_rows)), disaster, marker="o", label="disaster")
    ax_cuts.set_title("K scaling: objective components")
    ax_cuts.set_xlabel("Run")
    ax_cuts.set_ylabel("Component value")
    ax_cuts.legend(fontsize=8)
    ax_cuts.set_xticks(range(len(labels)))
    ax_cuts.set_xticklabels(labels, rotation=40, ha="right")

    vio = [_to_float(row.get("final_violation_upper_bound")) for row in k_rows]
    ax_vio.plot(range(len(k_rows)), vio, marker="o")
    ax_vio.set_title("K scaling: final violation")
    ax_vio.set_xlabel("Run")
    ax_vio.set_ylabel("final_violation_upper_bound")
    ax_vio.set_xticks(range(len(labels)))
    ax_vio.set_xticklabels(labels, rotation=40, ha="right")

    fig.tight_layout()
    path = out_dir / "paper_scale_matrix_k_scaling.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _write_aggregates(rows: list[RunData], out_dir: Path) -> None:
    scenario_rows = [r for r in rows if r.get("k_category") == "scenario_grid"]
    k_rows = [r for r in rows if r.get("k_category") == "k_scaling"]

    out_path = out_dir / "scalability_summary_from_scale_matrix.csv"
    rows_out = [
        [
            "run_id",
            "scenario_category",
            "A",
            "B",
            "k",
            "mode",
            "total_objective",
            "construction_cost",
            "unweighted_normal_term",
            "disaster_master_term",
            "iteration_count",
            "cut_count",
            "final_violation_upper_bound",
        ]
    ]

    for r in scenario_rows + k_rows:
        rows_out.append([
            r["run_id"],
            r.get("k_category", ""),
            str(r.get("A", "")),
            str(r.get("B", "")),
            str(r.get("k", "")),
            str(r.get("mode", "")),
            r.get("total_objective", ""),
            r.get("construction_cost", ""),
            r.get("unweighted_normal_term", ""),
            r.get("disaster_master_term", ""),
            r.get("iteration_count", ""),
            r.get("cut_count", ""),
            r.get("final_violation_upper_bound", ""),
        ])

    with (out_dir / out_path.name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows_out)

    # simple trend metrics for quick checks
    summary_path = out_dir / "scalability_trend_checks.txt"
    with summary_path.open("w", encoding="utf-8") as handle:
        handle.write("Scenario scaling trend (total objective):\n")
        for mode in ("integrated", "normal", "deterministic"):
            subset = [r for r in scenario_rows if str(r.get("mode")) == mode]
            if len(subset) >= 2:
                first = _to_float(subset[0].get("total_objective"))
                last = _to_float(subset[-1].get("total_objective"))
                delta = last - first if first == first else float("nan")
                handle.write(f"  {mode}: first={first:.4g}, last={last:.4g}, delta={delta:.4g}\n")
        handle.write("K scaling trend (integrated):\n")
        subset = [r for r in k_rows if str(r.get("mode")) == "integrated"]
        if len(subset) >= 2:
            for i in range(1, len(subset)):
                prev = _to_float(subset[i - 1].get("total_objective"))
                cur = _to_float(subset[i].get("total_objective"))
                handle.write(
                    f"  K{subset[i-1]['k']}->K{subset[i]['k']}: "
                    f"{prev:.4g} -> {cur:.4g}, "
                    f"change={cur-prev:.4g}\n"
                )


def generate_plots(summary_csv: Path, figures_dir: Path) -> list[str]:
    rows = _prepare_rows(_read_rows(summary_csv))
    figures_dir.mkdir(parents=True, exist_ok=True)
    _plot_scenario_scaling(rows, figures_dir)
    _plot_k_scaling(rows, figures_dir)
    _write_aggregates(rows, figures_dir)
    return [
        str(figures_dir / "paper_scale_matrix_scenario_scaling.png"),
        str(figures_dir / "paper_scale_matrix_k_scaling.png"),
        str(figures_dir / "scalability_summary_from_scale_matrix.csv"),
        str(figures_dir / "scalability_trend_checks.txt"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary-csv", required=True)
    parser.add_argument("--figures-dir", required=True)
    args = parser.parse_args()

    generated = generate_plots(
        summary_csv=Path(args.summary_csv),
        figures_dir=Path(args.figures_dir),
    )
    for item in generated:
        print(item)


if __name__ == "__main__":
    main()
