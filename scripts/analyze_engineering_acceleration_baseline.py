"""Audit current full-Benders scalability logs before acceleration work."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_separation_scalability import _summarize_milp  # noqa: E402


DEFAULT_OUTPUT = REPO_ROOT / "results/engineering_acceleration/baseline_audit"
SCALING_LOG_ROOTS = (
    REPO_ROOT / "results/paper_final/full_benders_scaling_runs/current_default_milp/logs",
    REPO_ROOT / "results/paper_final/full_benders_completion_runs/current_default_milp/logs",
)


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def _float(value: Any, default: float = 0.0) -> float:
    if value in ("", None):
        return default
    return float(value)


def _run_id_from_log(path: Path) -> str:
    suffix = "_run.json"
    name = path.name
    return name[: -len(suffix)] if name.endswith(suffix) else path.stem


def _load_progress_roles() -> dict[str, str]:
    roles: dict[str, str] = {}
    for row in _read_rows(REPO_ROOT / "results/paper_final/full_benders_scaling_progress.csv"):
        if row.get("run_id"):
            roles[row["run_id"]] = row.get("source_run_role", "")
    return roles


def _load_log(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_rows(log_path: Path, summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = _load_log(log_path)
    iterations = (payload.get("iteration_log") or {}).get("iterations") or []
    rows: list[dict[str, Any]] = []
    for item in iterations:
        rows.append(
            {
                "run_id": summary["run_id"],
                "A": summary["A"],
                "B": summary["B"],
                "K": summary["K"],
                "top_cuts": summary["top_cuts"],
                "iteration_id": item.get("iteration_id", ""),
                "pre_cut_master_objective": item.get("pre_cut_master_objective", ""),
                "post_cut_master_objective": item.get("post_cut_master_objective", ""),
                "separation_violation_value": item.get("separation_violation_value", ""),
                "master_solve_seconds": item.get("master_solve_seconds", ""),
                "separation_solve_seconds": item.get("separation_solve_seconds", ""),
                "cut_generation_seconds": item.get("cut_generation_seconds", ""),
                "separation_model_status": item.get("separation_model_status", ""),
                "separation_mip_gap": item.get("separation_mip_gap", ""),
                "separation_obj_bound": item.get("separation_obj_bound", ""),
                "separation_node_count": item.get("separation_node_count", ""),
                "selected_outage_active_lines": ";".join(
                    str(value) for value in (item.get("selected_outage_active_lines") or [])
                ),
                "repeated_outage_flag": item.get("repeated_outage_flag", ""),
                "repeated_cut_signature_flag": item.get("repeated_cut_signature_flag", ""),
                "cut_added": item.get("cut_added", ""),
                "cut_addition_status": item.get("cut_addition_status", ""),
                "total_cut_count_before": item.get("total_cut_count_before", ""),
                "total_cut_count_after": item.get("total_cut_count_after", ""),
                "generated_cut_old_master_violation": item.get(
                    "generated_cut_old_master_violation", ""
                ),
                "post_cut_master_objective_change": item.get(
                    "post_cut_master_objective_change", ""
                ),
                "first_stage_plan_changed": item.get("first_stage_plan_changed", ""),
                "alpha_lambda_only_change": item.get("alpha_lambda_only_change", ""),
                "log_path": str(log_path),
            }
        )
    return rows


def _cut_effectiveness(summary: Mapping[str, Any], trace: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    violations = [_float(row.get("separation_violation_value")) for row in trace]
    increases = sum(
        1 for prev, curr in zip(violations, violations[1:]) if curr > prev + 1.0e-6
    )
    return {
        "run_id": summary["run_id"],
        "A": summary["A"],
        "B": summary["B"],
        "K": summary["K"],
        "top_cuts": summary["top_cuts"],
        "validation_level": summary["validation_level"],
        "stop_reason": summary["stop_reason"],
        "iterations": summary["iterations"],
        "cuts": summary["cuts"],
        "first_violation": violations[0] if violations else "",
        "final_violation": summary["final_violation"],
        "min_violation": min(violations) if violations else "",
        "max_violation": max(violations) if violations else "",
        "violation_increase_count": increases,
        "duplicate_cut_iteration_count": sum(
            1 for row in trace if str(row.get("repeated_cut_signature_flag")).lower() == "true"
        ),
        "repeated_outage_iteration_count": sum(
            1 for row in trace if str(row.get("repeated_outage_flag")).lower() == "true"
        ),
        "plan_changed_iteration_count": sum(
            1 for row in trace if str(row.get("first_stage_plan_changed")).lower() == "true"
        ),
        "alpha_lambda_only_change_count": sum(
            1 for row in trace if str(row.get("alpha_lambda_only_change")).lower() == "true"
        ),
        "mean_master_seconds": (
            sum(_float(row.get("master_solve_seconds")) for row in trace) / len(trace)
            if trace
            else ""
        ),
        "mean_separation_seconds": (
            sum(_float(row.get("separation_solve_seconds")) for row in trace) / len(trace)
            if trace
            else ""
        ),
    }


def _diagnosis(row: Mapping[str, Any]) -> str:
    b_value = int(row["B"])
    k_value = int(row["K"])
    if b_value >= 100 and row["validation_level"] != "epsilon_certified":
        return "B-support separation bottleneck: final separation did not certify before time limit"
    if k_value >= 5 and row["validation_level"] != "epsilon_certified":
        return "K-budget convergence bottleneck: weak cuts/iteration budget, not safe for paper claim"
    if k_value >= 5:
        return "K-budget certified only with high iteration/cut budget"
    return "certified baseline row"


def _write_report(path: Path, summaries: Sequence[Mapping[str, Any]]) -> None:
    certified = [row for row in summaries if row["validation_level"] in {"exact", "epsilon_certified"}]
    diagnostic = [row for row in summaries if row not in certified]
    b100 = [row for row in summaries if int(row["B"]) == 100]
    k_hard = [row for row in summaries if int(row["K"]) >= 5]
    lines = [
        "# Current Scalability Failure Report",
        "",
        "## Verdict",
        "",
        "- Existing rows are useful as diagnostics, but the scalability section is not paper-ready yet.",
        "- `B=100` exposes a separation-MILP time-limit bottleneck.",
        "- `K>=5` exposes finite-iteration/cut effectiveness problems; K=5 certifies only after high-budget completion.",
        "",
        "## Row Counts",
        "",
        f"- Certified rows: `{len(certified)}`",
        f"- Diagnostic rows: `{len(diagnostic)}`",
        "",
        "## Hard Rows",
        "",
    ]
    for row in [*b100, *k_hard]:
        lines.append(
            "- "
            f"`{row['run_id']}`: A={row['A']}, B={row['B']}, K={row['K']}, "
            f"validation={row['validation_level']}, stop={row['stop_reason']}, "
            f"iter={row['iterations']}, cuts={row['cuts']}, runtime={float(row['runtime_seconds']):.1f}s, "
            f"final_violation={float(row['final_violation']):.2f}, "
            f"sep_share={float(row['separation_time_share'] or 0.0):.3f}. "
            f"{row['diagnosis']}"
        )
    lines.extend(
        [
            "",
            "## Required Next Engineering Checks",
            "",
            "- Use same-instance cut-pool seeding and plan warm starts for continuation, not from-scratch high-budget reruns.",
            "- Compare `top_cuts={3,10,20}` on K=5 before running K=7/10.",
            "- Keep B=100 rows diagnostic unless final separation reaches OPTIMAL certification.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output)
    roles = _load_progress_roles()

    summaries: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    cut_rows: list[dict[str, Any]] = []
    for root in SCALING_LOG_ROOTS:
        for log_path in sorted(root.glob("*_run.json")):
            run_id = _run_id_from_log(log_path)
            summary = _summarize_milp(log_path, run_id=run_id)
            summary["source_run_role"] = roles.get(run_id, "")
            summary["diagnosis"] = _diagnosis(summary)
            summaries.append(summary)
            trace = _iter_rows(log_path, summary)
            traces.extend(trace)
            cut_rows.append(_cut_effectiveness(summary, trace))

    summaries = sorted(summaries, key=lambda row: (int(row["K"]), int(row["B"]), row["run_id"]))
    _write_rows(output / "baseline_runtime_decomposition.csv", summaries)
    _write_rows(output / "baseline_iteration_trace.csv", traces)
    _write_rows(output / "baseline_cut_effectiveness.csv", cut_rows)
    _write_report(output / "current_scalability_failure_report.md", summaries)
    print(json.dumps({"output": str(output), "run_count": len(summaries)}, sort_keys=True))


if __name__ == "__main__":
    main()
