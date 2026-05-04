"""Accelerated default-case retuning driver.

This wrapper keeps the mathematical model unchanged.  It uses continuation
warm starts, same-instance cut-pool seeding, and cut-signature deduplication to
screen deterministic-topology candidates before running full certification.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


PRIMARY_CANDIDATES = (
    (0.016, 1.0, 1.25),
    (0.017, 1.0, 1.25),
    (0.018, 1.0, 1.25),
    (0.019, 1.0, 1.25),
)
SECONDARY_CANDIDATES = (
    (0.018, 1.0, 1.15),
    (0.018, 1.0, 1.20),
    (0.018, 1.0, 1.30),
    (0.019, 1.0, 1.15),
    (0.019, 1.0, 1.20),
    (0.019, 1.0, 1.30),
    (0.020, 1.0, 1.15),
    (0.020, 1.0, 1.20),
    (0.020, 1.0, 1.30),
)
BASELINE_CANDIDATE = (0.015, 1.0, 1.25)


def _token(value: float) -> str:
    return f"{float(value):g}".replace(".", "p")


def _candidate_id(cons: float, normal: float, disaster: float) -> str:
    return f"mult_cons{_token(cons)}_normal{_token(normal)}_disaster{_token(disaster)}"


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


def _write_dry_audit(path: Path, artifact: str) -> None:
    _write_rows(
        path,
        [{
            "artifact": artifact,
            "status": "dry_run",
            "note": "Audit rows are appended during executed candidate runs.",
        }],
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _run_default_calibration(args: list[str]) -> None:
    command = [sys.executable, "scripts/run_default_multiplier_calibration.py", *args]
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def _candidate_run_args(
    *,
    args: argparse.Namespace,
    candidate: Mapping[str, Any],
    cases: str,
    max_iterations: int,
    top_cuts: int,
    fixed_eval_max_iterations: int,
    fixed_eval_top_cuts: int,
    master_time_limit_seconds: float,
    separation_time_limit_seconds: float,
) -> list[str]:
    command_args = [
        "--runtime-source", args.runtime_source,
        "--output-root", args.output_root,
        "--cons-values", str(candidate["m_cons"]),
        "--normal-values", str(candidate["m_normal"]),
        "--disaster-values", str(candidate["m_disaster"]),
        "--stage1-max-candidates", "1",
        "--stage2-max-candidates", "1",
        "--no-forced-baseline",
        "--cases", cases,
        "--max-iterations", str(max_iterations),
        "--top-cuts", str(top_cuts),
        "--fixed-eval-max-iterations", str(fixed_eval_max_iterations),
        "--fixed-eval-top-cuts", str(fixed_eval_top_cuts),
        "--master-time-limit-seconds", str(master_time_limit_seconds),
        "--separation-time-limit-seconds", str(separation_time_limit_seconds),
        "--enable-cut-signature-dedup",
    ]
    if args.skip_existing:
        command_args.append("--skip-existing")
    return command_args


def _candidate_queue() -> list[dict[str, Any]]:
    triples = (BASELINE_CANDIDATE, *PRIMARY_CANDIDATES, *SECONDARY_CANDIDATES)
    return [
        {
            "candidate_id": _candidate_id(cons, normal, disaster),
            "m_cons": cons,
            "m_normal": normal,
            "m_disaster": disaster,
        }
        for cons, normal, disaster in triples
    ]


def _float(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    raw = row.get(key, default)
    if raw in ("", None):
        return default
    return float(raw)


def _int(row: Mapping[str, Any], key: str, default: int = 0) -> int:
    raw = row.get(key, default)
    if raw in ("", None):
        return default
    return int(float(raw))


def _screen_candidates(root: Path, *, max_full_candidates: int) -> list[dict[str, Any]]:
    rows = _read_rows(root / "candidate_matrix.csv")
    by_candidate: dict[str, dict[str, dict[str, str]]] = {}
    for row in rows:
        by_candidate.setdefault(row["candidate_id"], {})[row["case"]] = row
    scored: list[dict[str, Any]] = []
    for candidate in _candidate_queue():
        cases = by_candidate.get(candidate["candidate_id"], {})
        if not {"proposed", "deterministic_k2"} <= set(cases):
            continue
        proposed = cases["proposed"]
        deterministic = cases["deterministic_k2"]
        sites_gap = _int(proposed, "sites") - _int(deterministic, "sites")
        slow_gap = _int(proposed, "slow_chargers") - _int(deterministic, "slow_chargers")
        fast_gap = _int(proposed, "fast_chargers") - _int(deterministic, "fast_chargers")
        total_gap = _int(proposed, "total_chargers") - _int(deterministic, "total_chargers")
        phi_gap_pct = (
            (_float(deterministic, "Phi_dis") - _float(proposed, "Phi_dis"))
            / max(_float(deterministic, "Phi_dis"), 1.0)
            * 100.0
        )
        coverage = int(str(proposed.get("critical_bus_coverage", "0/0")).split("/", 1)[0])
        score = (
            30.0 * max(0, sites_gap)
            + 0.2 * max(0, slow_gap)
            + 3.0 * max(0, fast_gap)
            + 0.1 * max(0, total_gap)
            + 5.0 * coverage
            + max(0.0, phi_gap_pct)
        )
        scored.append({
            **candidate,
            "sites_gap": sites_gap,
            "slow_gap": slow_gap,
            "fast_gap": fast_gap,
            "total_gap": total_gap,
            "phi_gap_pct": phi_gap_pct,
            "critical_direct_case1": coverage,
            "stage_a_score": score,
        })
    selected = sorted(scored, key=lambda row: float(row["stage_a_score"]), reverse=True)
    return selected[:max_full_candidates]


def _write_final_review(root: Path) -> None:
    gates = _read_rows(root / "story_gate_summary.csv")
    passing = [row for row in gates if str(row.get("passes_all", "")).lower() == "true"]
    verdict = "PASS_TARGET" if passing else "FAIL_RECALIBRATE_OR_PRO_MATH_REQUIRED"
    payload = {
        "verdict": verdict,
        "passing_candidates": passing,
        "paper_final_promoted": False,
        "note": (
            "Promotion is intentionally left to the paper-final promotion step; "
            "this driver only selects and verifies candidates."
        ),
    }
    (root / "accelerated_retuning_review.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    if passing:
        selected = passing[0]
        text = (
            "# Accelerated Retuning Review\n\n"
            "Verdict: **PASS_TARGET**\n\n"
            f"Passing candidate: `{selected['candidate_id']}`.\n"
        )
    else:
        text = (
            "# Accelerated Retuning Review\n\n"
            "Verdict: **FAIL_RECALIBRATE_OR_PRO_MATH_REQUIRED**\n\n"
            "No candidate passed both the original default gates and the "
            "deterministic-topology gate.  The next step is Pro-reviewed "
            "algorithmic strengthening rather than paper rewriting.\n"
        )
    (root / "accelerated_retuning_review.md").write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="results/default_case_accelerated_retuning")
    parser.add_argument("--runtime-source", default="data/colleague_default_10x10")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--max-full-candidates", type=int, default=4)
    parser.add_argument("--stage-a-max-iterations", type=int, default=8)
    parser.add_argument("--stage-a-top-cuts", type=int, default=10)
    parser.add_argument("--stage-a-fixed-eval-max-iterations", type=int, default=8)
    parser.add_argument("--stage-a-fixed-eval-top-cuts", type=int, default=10)
    parser.add_argument("--stage-a-separation-time-limit-seconds", type=float, default=60.0)
    args = parser.parse_args()

    root = REPO_ROOT / args.output_root
    root.mkdir(parents=True, exist_ok=True)
    queue = _candidate_queue()
    _write_rows(root / "candidate_queue.csv", queue)
    if args.dry_run:
        _write_dry_audit(root / "warm_start_audit.csv", "warm_start_audit")
        _write_dry_audit(root / "cut_pool_audit.csv", "cut_pool_audit")
        print(f"queued {len(queue)} accelerated candidates")
        return

    for candidate in queue:
        _run_default_calibration(
            _candidate_run_args(
                args=args,
                candidate=candidate,
                cases="proposed,deterministic_k2",
                max_iterations=int(args.stage_a_max_iterations),
                top_cuts=int(args.stage_a_top_cuts),
                fixed_eval_max_iterations=int(args.stage_a_fixed_eval_max_iterations),
                fixed_eval_top_cuts=int(args.stage_a_fixed_eval_top_cuts),
                master_time_limit_seconds=120,
                separation_time_limit_seconds=float(args.stage_a_separation_time_limit_seconds),
            )
        )

    selected = _screen_candidates(root, max_full_candidates=int(args.max_full_candidates))
    _write_rows(root / "stage_b_selected_candidates.csv", selected)
    for candidate in selected:
        _run_default_calibration(
            _candidate_run_args(
                args=args,
                candidate=candidate,
                cases="proposed,normal,disaster,deterministic_k2",
                max_iterations=100,
                top_cuts=20,
                fixed_eval_max_iterations=100,
                fixed_eval_top_cuts=20,
                master_time_limit_seconds=120,
                separation_time_limit_seconds=300,
            )
        )
    _write_final_review(root)


if __name__ == "__main__":
    main()
