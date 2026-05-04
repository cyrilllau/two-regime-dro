"""Compare bounded-MILP disaster evaluator rows against exact outage enumeration."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from typing import Any


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _safe_relative_gap(candidate: float, reference: float) -> float:
    if abs(reference) <= 1e-12:
        return 0.0 if abs(candidate) <= 1e-12 else float("inf")
    return abs(candidate - reference) / abs(reference)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--bounded-csv", default="common_evaluation.csv")
    parser.add_argument(
        "--exact-csv",
        action="append",
        required=True,
        help="Exact enumeration CSV. Pass multiple times to combine subsets.",
    )
    parser.add_argument("--output-csv", default="disaster_evaluator_exactness_audit.csv")
    parser.add_argument("--output-md", default="disaster_evaluator_exactness_audit.md")
    parser.add_argument("--relative-tolerance", type=float, default=0.05)
    args = parser.parse_args()

    root = Path(args.root)
    bounded_rows = {
        row["run_id"]: row for row in _read_rows(root / args.bounded_csv)
    }
    exact_rows: dict[str, dict[str, str]] = {}
    for csv_name in args.exact_csv:
        for row in _read_rows(root / csv_name):
            exact_rows[row["run_id"]] = row

    audit_rows: list[dict[str, Any]] = []
    fail = False
    for run_id in sorted(exact_rows):
        exact = exact_rows[run_id]
        bounded = bounded_rows.get(run_id)
        if bounded is None:
            fail = True
            audit_rows.append(
                {
                    "run_id": run_id,
                    "bounded_phi": "",
                    "exact_phi": exact.get("Phi_dis", ""),
                    "relative_gap": "",
                    "status": "FAIL_MISSING_BOUNDED_ROW",
                    "bounded_active_outage_lines": "",
                    "exact_active_outage_lines": exact.get("active_outage_lines", ""),
                }
            )
            continue
        bounded_phi = float(bounded["Phi_dis"])
        exact_phi = float(exact["Phi_dis"])
        relative_gap = _safe_relative_gap(bounded_phi, exact_phi)
        passed = relative_gap <= float(args.relative_tolerance)
        fail = fail or not passed
        audit_rows.append(
            {
                "run_id": run_id,
                "bounded_phi": bounded_phi,
                "exact_phi": exact_phi,
                "relative_gap": relative_gap,
                "status": "PASS" if passed else "FAIL",
                "bounded_active_outage_lines": bounded.get("active_outage_lines", ""),
                "exact_active_outage_lines": exact.get("active_outage_lines", ""),
            }
        )

    _write_rows(root / args.output_csv, audit_rows)

    lines = ["# Disaster Evaluator Exactness Audit", ""]
    for row in audit_rows:
        gap = row["relative_gap"]
        gap_text = "" if gap == "" else f"{float(gap):.2%}"
        lines.append(
            f"- `{row['run_id']}`: bounded Phi={row['bounded_phi']}, "
            f"exact Phi={row['exact_phi']}, relative gap={gap_text}, "
            f"status={row['status']}."
        )
    lines.extend(
        [
            "",
            f"Overall result: **{'FAIL' if fail else 'PASS'}**",
            "",
            "If this audit fails, Table-III/Table-IV disaster costs must use exact enumeration "
            "or the paper must downgrade any certified DRO robustness claim.",
        ]
    )
    (root / args.output_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(root / args.output_csv)
    print(root / args.output_md)
    if fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
