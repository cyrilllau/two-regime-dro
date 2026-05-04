"""12-hour autonomous default-case search with acceleration and checkpoints."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_default_multiplier_calibration import (  # noqa: E402
    _base_config,
    _candidate_id,
    _coverage_count,
    _float,
    _open_bus_set,
    _plan_metrics,
    _read_rows,
    _run_case,
    _story_gate,
    _total_chargers_value,
    _write_rows,
)


DEFAULT_OUTPUT_ROOT = "results/default_case_autonomous_retuning"
RUNTIME_SOURCE = "data/colleague_default_10x10"
HANDPICKED = (
    (0.015, 1.0, 1.25),
    (0.012, 1.0, 1.15),
    (0.016, 1.0, 1.25),
    (0.015, 1.0, 1.30),
    (0.015, 1.0, 1.40),
    (0.015, 1.0, 1.50),
    (0.014, 1.0, 1.25),
    (0.013, 1.0, 1.20),
    (0.013, 1.0, 1.25),
    (0.017, 1.0, 1.25),
)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _append_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    existing = _read_rows(path)
    existing.extend(dict(row) for row in rows)
    _write_rows(path, existing)


def _candidate(cons: float, normal: float, disaster: float) -> dict[str, Any]:
    return {
        "candidate_id": _candidate_id(cons, normal, disaster),
        "m_cons": cons,
        "m_normal": normal,
        "m_disaster": disaster,
    }


def _parse_candidate_id(candidate_id: str) -> dict[str, Any]:
    def parse_token(prefix: str) -> float:
        start = candidate_id.index(prefix) + len(prefix)
        rest = candidate_id[start:]
        token = rest.split("_", 1)[0]
        return float(token.replace("p", "."))

    return _candidate(
        parse_token("mult_cons"),
        parse_token("normal"),
        parse_token("disaster"),
    )


def _case_row_from_run(
    *,
    candidate: Mapping[str, Any],
    case: str,
    run_record: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(run_record["payload"])
    summary = dict(payload.get("summary", {}))
    plan_path = Path(run_record["plan_path"])
    return {
        "candidate_id": candidate["candidate_id"],
        "m_cons": candidate["m_cons"],
        "m_normal": candidate["m_normal"],
        "m_disaster": candidate["m_disaster"],
        "case": case,
        "run_id": run_record["config"]["run_id"],
        "training_mode": run_record["config"]["mode"],
        "training_solver": run_record["config"]["solver"],
        "training_validation_level": payload.get("validation_level", summary.get("validation_level", "")),
        "training_stop_reason": payload.get("stop_reason", summary.get("stop_reason", "")),
        "training_solver_status": payload.get("solver_status", summary.get("solver_status", "")),
        "training_iterations": summary.get("iteration_count", ""),
        "training_cuts": summary.get("cut_count", ""),
        "training_final_violation": summary.get("final_violation_upper_bound", ""),
        "plan_path": str(plan_path),
        **_plan_metrics(plan_path),
    }


def _stage_a_case(args: argparse.Namespace) -> None:
    root = REPO_ROOT / args.output_root
    candidate = _candidate(float(args.m_cons), float(args.m_normal), float(args.m_disaster))
    case_args = argparse.Namespace(
        max_iterations=args.max_iterations,
        top_cuts=args.top_cuts,
        epsilon_cert=args.epsilon_cert,
        master_time_limit_seconds=args.master_time_limit_seconds,
        master_mip_gap=args.master_mip_gap,
        separation_time_limit_seconds=args.separation_time_limit_seconds,
        separation_mip_gap=args.separation_mip_gap,
        omega_bound_upper=args.omega_bound_upper,
        warm_start_plan_paths=args.warm_start_plan_paths,
        initial_cut_pool_paths=args.initial_cut_pool_paths,
        neighbor_warm_start_limit=args.neighbor_warm_start_limit,
        neighbor_cut_pool_limit=args.neighbor_cut_pool_limit,
        enable_cut_signature_dedup=args.enable_cut_signature_dedup,
        enable_repeated_outage_guard=args.enable_repeated_outage_guard,
        skip_existing=args.skip_existing,
    )
    run_record = _run_case(
        root=root,
        runtime_source=args.runtime_source,
        candidate=candidate,
        case=args.case,
        args=case_args,
    )
    row = _case_row_from_run(candidate=candidate, case=args.case, run_record=run_record)
    _write_json(root / "stage_a_cases" / f"{candidate['candidate_id']}_{args.case}.json", row)


def _run_child(
    *,
    root: Path,
    candidate: Mapping[str, Any],
    case: str,
    args: argparse.Namespace,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_autonomous_default_search.py"),
        "--stage-a-case",
        "--output-root", str(root),
        "--runtime-source", args.runtime_source,
        "--case", case,
        "--m-cons", str(candidate["m_cons"]),
        "--m-normal", str(candidate["m_normal"]),
        "--m-disaster", str(candidate["m_disaster"]),
        "--max-iterations", str(args.stage_a_iterations),
        "--top-cuts", str(args.stage_a_top_cuts),
        "--epsilon-cert", str(args.epsilon_cert),
        "--master-time-limit-seconds", str(args.stage_a_master_time_limit),
        "--master-mip-gap", str(args.stage_a_master_mip_gap),
        "--separation-time-limit-seconds", str(args.stage_a_separation_time_limit),
        "--separation-mip-gap", str(args.stage_a_separation_mip_gap),
        "--omega-bound-upper", str(args.omega_bound_upper),
        "--neighbor-warm-start-limit", str(args.neighbor_warm_start_limit),
        "--neighbor-cut-pool-limit", str(args.neighbor_cut_pool_limit),
        "--skip-existing",
        "--enable-cut-signature-dedup",
    ]
    if args.warm_start_plan_paths:
        command.extend(["--warm-start-plan-paths", args.warm_start_plan_paths])
    if args.initial_cut_pool_paths:
        command.extend(["--initial-cut-pool-paths", args.initial_cut_pool_paths])
    if args.enable_repeated_outage_guard:
        command.append("--enable-repeated-outage-guard")
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            timeout=float(args.stage_a_timeout_seconds),
            text=True,
            capture_output=True,
        )
    except subprocess.TimeoutExpired as exc:
        return None, {
            "candidate_id": candidate["candidate_id"],
            "case": case,
            "status": "timeout",
            "elapsed_seconds": round(time.time() - started, 3),
            "reason": f"stage_a_timeout_{args.stage_a_timeout_seconds}s",
            "stdout_tail": (exc.stdout or "")[-1000:],
            "stderr_tail": (exc.stderr or "")[-1000:],
        }
    if completed.returncode != 0:
        return None, {
            "candidate_id": candidate["candidate_id"],
            "case": case,
            "status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-1000:],
            "stderr_tail": completed.stderr[-1000:],
        }
    row_path = root / "stage_a_cases" / f"{candidate['candidate_id']}_{case}.json"
    if not row_path.exists():
        return None, {
            "candidate_id": candidate["candidate_id"],
            "case": case,
            "status": "missing_row",
            "elapsed_seconds": round(time.time() - started, 3),
            "stdout_tail": completed.stdout[-1000:],
            "stderr_tail": completed.stderr[-1000:],
        }
    row = json.loads(row_path.read_text(encoding="utf-8"))
    row["elapsed_seconds"] = round(time.time() - started, 3)
    return row, None


def _run_plan_pool(root: Path) -> list[dict[str, Any]]:
    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "screen_endpoint_plan_pool.py"),
            "--output-root", str(root),
        ],
        cwd=REPO_ROOT,
        check=True,
    )
    return _read_rows(root / "plan_pool_top10.csv")


def _parse_candidate_triples(raw: str) -> list[dict[str, Any]]:
    triples: list[dict[str, Any]] = []
    for item in raw.split(","):
        token = item.strip()
        if not token:
            continue
        parts = token.replace(":", "/").split("/")
        if len(parts) == 2:
            cons, disaster = (float(value) for value in parts)
            normal = 1.0
        elif len(parts) == 3:
            cons, normal, disaster = (float(value) for value in parts)
        else:
            raise ValueError(
                "Candidate triples must be cons/disaster or cons/normal/disaster; "
                f"got {token!r}."
            )
        triples.append(_candidate(cons, normal, disaster))
    return triples


def _candidate_queue(
    root: Path,
    *,
    max_candidates: int,
    candidate_triples: str = "",
) -> list[dict[str, Any]]:
    if candidate_triples.strip():
        ordered = _parse_candidate_triples(candidate_triples)[:max_candidates]
        _write_rows(root / "candidate_queue.csv", ordered)
        return ordered

    candidates: dict[str, dict[str, Any]] = {}
    for triple in HANDPICKED:
        candidate = _candidate(*triple)
        candidates[str(candidate["candidate_id"])] = candidate
    for row in _run_plan_pool(root):
        try:
            candidate = _parse_candidate_id(str(row["candidate_id"]))
        except Exception:
            continue
        candidates[str(candidate["candidate_id"])] = candidate
    ordered = list(candidates.values())[:max_candidates]
    _write_rows(root / "candidate_queue.csv", ordered)
    return ordered


def _stage_a_promising(rows: Sequence[Mapping[str, Any]]) -> bool:
    by_case = {row["case"]: row for row in rows}
    if "proposed" not in by_case:
        return False
    proposed = by_case["proposed"]
    if str(proposed.get("training_validation_level")) not in {"exact", "epsilon_certified", "smoke_only"}:
        return False
    if int(float(proposed.get("sites", 0) or 0)) < 8:
        return False
    if _coverage_count(proposed) < 4:
        return False
    if "deterministic_k2" not in by_case:
        return True
    deterministic = by_case["deterministic_k2"]
    proposed_total = _total_chargers_value(proposed)
    deterministic_total = _total_chargers_value(deterministic)
    proposed_sites = int(float(proposed.get("sites", 0) or 0))
    deterministic_sites = int(float(deterministic.get("sites", 0) or 0))
    proposed_slow = int(float(proposed.get("slow_chargers", 0) or 0))
    deterministic_slow = int(float(deterministic.get("slow_chargers", 0) or 0))
    proposed_fast = int(float(proposed.get("fast_chargers", 0) or 0))
    deterministic_fast = int(float(deterministic.get("fast_chargers", 0) or 0))
    return (
        proposed_sites > deterministic_sites
        and proposed_slow >= deterministic_slow
        and proposed_fast >= deterministic_fast
        and proposed_total > deterministic_total
    )


def _run_full_replay(
    *,
    root: Path,
    candidate: Mapping[str, Any],
    cases: str,
    timeout_seconds: float,
    args: argparse.Namespace,
    max_iterations: int,
    top_cuts: int,
    fixed_eval_max_iterations: int,
    fixed_eval_top_cuts: int,
    skip_existing: bool,
) -> tuple[bool, dict[str, Any] | None]:
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "run_default_multiplier_calibration.py"),
        "--output-root", str(root),
        "--runtime-source", args.runtime_source,
        "--cons-values", str(candidate["m_cons"]),
        "--normal-values", str(candidate["m_normal"]),
        "--disaster-values", str(candidate["m_disaster"]),
        "--cases", cases,
        "--no-forced-baseline",
        "--stage1-max-candidates", "1",
        "--stage2-max-candidates", "1",
        "--max-iterations", str(max_iterations),
        "--top-cuts", str(top_cuts),
        "--fixed-eval-max-iterations", str(fixed_eval_max_iterations),
        "--fixed-eval-top-cuts", str(fixed_eval_top_cuts),
        "--master-time-limit-seconds", str(args.stage_b_master_time_limit),
        "--separation-time-limit-seconds", str(args.stage_b_separation_time_limit),
        "--master-mip-gap", str(args.stage_b_master_mip_gap),
        "--separation-mip-gap", str(args.stage_b_separation_mip_gap),
        "--enable-cut-signature-dedup",
    ]
    if skip_existing:
        command.append("--skip-existing")
    if bool(getattr(args, "reuse_certified_disaster_training_phi", False)):
        command.append("--reuse-certified-disaster-training-phi")
    if args.warm_start_plan_paths:
        command.extend(["--warm-start-plan-paths", args.warm_start_plan_paths])
    if args.initial_cut_pool_paths:
        command.extend(["--initial-cut-pool-paths", args.initial_cut_pool_paths])
    if args.enable_repeated_outage_guard:
        command.append("--enable-repeated-outage-guard")
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            timeout=timeout_seconds,
            text=True,
            capture_output=True,
        )
    except subprocess.TimeoutExpired as exc:
        return False, {
            "candidate_id": candidate["candidate_id"],
            "cases": cases,
            "status": "timeout",
            "elapsed_seconds": round(time.time() - started, 3),
            "stdout_tail": (exc.stdout or "")[-1000:],
            "stderr_tail": (exc.stderr or "")[-1000:],
        }
    if completed.returncode != 0:
        return False, {
            "candidate_id": candidate["candidate_id"],
            "cases": cases,
            "status": "failed",
            "elapsed_seconds": round(time.time() - started, 3),
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-1000:],
            "stderr_tail": completed.stderr[-1000:],
        }
    return True, None


def _rubric_review(candidate: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    gate = _story_gate(candidate, rows)
    by_case = {row["case"]: row for row in rows}
    hard_complete = {"proposed", "normal", "disaster", "deterministic_k2"} <= set(by_case)
    hard_cert = hard_complete and all(
        str(row.get("training_validation_level")) in {"exact", "epsilon_certified"}
        for row in by_case.values()
    )
    if not hard_complete:
        if {"proposed", "deterministic_k2"} <= set(by_case):
            proposed_phi = _float(by_case["proposed"], "Phi_dis")
            deterministic_phi = _float(by_case["deterministic_k2"], "Phi_dis")
            proposed_sites = int(float(by_case["proposed"].get("sites", 0) or 0))
            deterministic_sites = int(float(by_case["deterministic_k2"].get("sites", 0) or 0))
            proposed_total = _total_chargers_value(by_case["proposed"])
            deterministic_total = _total_chargers_value(by_case["deterministic_k2"])
            if proposed_phi >= deterministic_phi:
                verdict = "FAIL_RESULT_STORY"
            elif proposed_sites < deterministic_sites or proposed_total <= deterministic_total:
                verdict = "FAIL_RESULT_STORY"
            else:
                verdict = "NEED_MORE_EVIDENCE"
        else:
            verdict = "NEED_MORE_EVIDENCE"
    elif not hard_cert:
        verdict = "FAIL_BUG_OR_BENCHMARK"
    else:
        proposed = by_case["proposed"]
        normal = by_case["normal"]
        disaster = by_case["disaster"]
        deterministic = by_case["deterministic_k2"]
        proposed_phi = _float(proposed, "Phi_dis")
        normal_phi = _float(normal, "Phi_dis")
        disaster_phi = _float(disaster, "Phi_dis")
        deterministic_phi = _float(deterministic, "Phi_dis")
        case3_sacrifice = _float(disaster, "F_unmet") / max(_float(disaster, "Psi_nor"), 1.0) >= 0.20
        proposed_shift = len(_open_bus_set(proposed) ^ _open_bus_set(normal)) >= 2
        if (
            proposed_phi < deterministic_phi
            and proposed_phi < normal_phi
            and disaster_phi <= 1.05 * proposed_phi
            and case3_sacrifice
            and proposed_shift
            and str(gate.get("passes_all", "")).lower() == "true"
        ):
            verdict = "PASS_PAPER_STORY"
        elif proposed_phi < deterministic_phi and proposed_phi < normal_phi:
            verdict = "PASS_WITH_REWRITE"
        else:
            verdict = "FAIL_RESULT_STORY"
    return {**gate, "rubric_verdict": verdict}


def _refresh_rubric(root: Path) -> list[dict[str, Any]]:
    rows = _read_rows(root / "candidate_matrix.csv")
    candidate_ids = sorted({row.get("candidate_id", "") for row in rows if row.get("candidate_id")})
    reviews: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        try:
            candidate = _parse_candidate_id(candidate_id)
        except Exception:
            continue
        candidate_rows = [row for row in rows if row.get("candidate_id") == candidate_id]
        reviews.append(_rubric_review(candidate, candidate_rows))
    _write_rows(root / "rubric_review.csv", reviews)
    return reviews


def _has_certified_stage_b_pair(root: Path, candidate_id: str) -> bool:
    rows = [
        row for row in _read_rows(root / "candidate_matrix.csv")
        if row.get("candidate_id") == candidate_id
        and row.get("case") in {"proposed", "deterministic_k2"}
    ]
    by_case = {row.get("case"): row for row in rows}
    if {"proposed", "deterministic_k2"} - set(by_case):
        return False
    return all(
        str(row.get("training_validation_level")) in {"exact", "epsilon_certified"}
        for row in by_case.values()
    )


def _has_certified_case(root: Path, candidate_id: str, case: str) -> bool:
    rows = [
        row for row in _read_rows(root / "candidate_matrix.csv")
        if row.get("candidate_id") == candidate_id and row.get("case") == case
    ]
    if not rows:
        return False
    return str(rows[0].get("training_validation_level")) in {"exact", "epsilon_certified"}


def _write_report(root: Path, *, verdict: str, start_time: float) -> None:
    reviews = _read_rows(root / "rubric_review.csv")
    best = sorted(reviews, key=lambda row: float(row.get("story_score") or 0.0), reverse=True)
    lines = [
        "# Autonomous Default Search Report",
        "",
        f"Verdict: **{verdict}**",
        f"Elapsed seconds: `{time.time() - start_time:.1f}`",
        "",
    ]
    if best:
        row = best[0]
        lines.extend([
            "## Best Candidate",
            "",
            f"- Candidate: `{row.get('candidate_id')}`",
            f"- Rubric verdict: `{row.get('rubric_verdict')}`",
            f"- Phi order: Case3 `{row.get('Phi_case3')}`, Case1 `{row.get('Phi_case1')}`, Case2 `{row.get('Phi_case2')}`, Case4 `{row.get('Phi_case4')}`",
            f"- Score: `{row.get('story_score')}`",
            f"- Failure reasons: `{row.get('failure_reasons')}`",
            "",
        ])
    lines.extend([
        "## Records",
        "",
        "- `candidate_queue.csv`",
        "- `stage_a_topology_screen.csv`",
        "- `stage_b_common_replay.csv`",
        "- `stage_c_certification.csv`",
        "- `blocked_candidates.csv`",
        "- `rubric_review.csv`",
        "- `acceleration_decision_log.md`",
    ])
    (root / "best_candidate_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_json(root / "critic_review.json", {"verdict": verdict, "elapsed_seconds": time.time() - start_time, "best": best[0] if best else {}})
    (root / "critic_review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_log(root: Path, text: str) -> None:
    path = root / "acceleration_decision_log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Acceleration Decision Log\n\n"
    path.write_text(existing + f"- {time.strftime('%Y-%m-%d %H:%M:%S')}: {text}\n", encoding="utf-8")


def _is_acceptable_stop(review: Mapping[str, Any], args: argparse.Namespace) -> bool:
    verdict = str(review.get("rubric_verdict", ""))
    if verdict not in {"PASS_PAPER_STORY", "PASS_WITH_REWRITE"}:
        return False
    if bool(getattr(args, "require_paper_ready_topology", False)):
        return str(review.get("paper_ready_topology_pass", "")).lower() == "true"
    return True


def _main_search(args: argparse.Namespace) -> None:
    root = REPO_ROOT / args.output_root
    root.mkdir(parents=True, exist_ok=True)
    start_time = time.time()
    deadline = start_time + float(args.max_wall_clock_hours) * 3600.0
    _append_log(root, "Started autonomous default-case search with story-rubric judging.")
    queue = _candidate_queue(
        root,
        max_candidates=int(args.max_candidates),
        candidate_triples=str(getattr(args, "candidate_triples", "")),
    )
    if args.dry_run:
        _write_report(root, verdict="DRY_RUN_READY", start_time=start_time)
        print(f"dry-run queued {len(queue)} candidates")
        return

    stage_b_candidates: list[dict[str, Any]] = []
    for candidate in queue:
        if time.time() > deadline:
            _write_report(root, verdict="TIME_BUDGET_EXCEEDED", start_time=start_time)
            return
        rows: list[dict[str, Any]] = []
        for case in ("proposed", "deterministic_k2"):
            row, blocked = _run_child(root=root, candidate=candidate, case=case, args=args)
            if blocked:
                _append_rows(root / "blocked_candidates.csv", [blocked])
                _append_log(root, f"Blocked {candidate['candidate_id']} {case}: {blocked['status']}.")
                continue
            if row:
                rows.append(row)
                _append_rows(root / "stage_a_topology_screen.csv", [row])
        if _stage_a_promising(rows):
            stage_b_candidates.append(candidate)
            _append_log(root, f"Stage A shortlisted {candidate['candidate_id']}.")
        if len(stage_b_candidates) >= int(args.max_stage_b_candidates):
            break

    for candidate in stage_b_candidates:
        if time.time() > deadline:
            _write_report(root, verdict="TIME_BUDGET_EXCEEDED", start_time=start_time)
            return
        if _has_certified_stage_b_pair(root, str(candidate["candidate_id"])):
            _append_rows(root / "stage_b_common_replay.csv", [{"candidate_id": candidate["candidate_id"], "status": "reused_certified_pair"}])
        else:
            stage_b_blocked = False
            for case in ("proposed", "deterministic_k2"):
                if _has_certified_case(root, str(candidate["candidate_id"]), case):
                    _append_rows(
                        root / "stage_b_common_replay.csv",
                        [{"candidate_id": candidate["candidate_id"], "case": case, "status": "reused_certified_case"}],
                    )
                    continue
                ok, blocked = _run_full_replay(
                    root=root,
                    candidate=candidate,
                    cases=case,
                    timeout_seconds=float(args.stage_b_timeout_seconds),
                    args=args,
                    max_iterations=int(args.stage_b_iterations),
                    top_cuts=int(args.stage_b_top_cuts),
                    fixed_eval_max_iterations=int(args.stage_b_fixed_eval_iterations),
                    fixed_eval_top_cuts=int(args.stage_b_fixed_eval_top_cuts),
                    skip_existing=True,
                )
                if blocked:
                    _append_rows(root / "blocked_candidates.csv", [blocked])
                    _append_log(
                        root,
                        f"Stage B blocked {candidate['candidate_id']} {case}: {blocked['status']}.",
                    )
                    stage_b_blocked = True
                    break
                _append_rows(
                    root / "stage_b_common_replay.csv",
                    [{"candidate_id": candidate["candidate_id"], "case": case, "status": "completed"}],
                )
            if stage_b_blocked:
                _refresh_rubric(root)
                continue
        reviews = _refresh_rubric(root)
        review = next((row for row in reviews if row.get("candidate_id") == candidate["candidate_id"]), {})
        if str(review.get("rubric_verdict")) in {"PASS_PAPER_STORY", "PASS_WITH_REWRITE", "NEED_MORE_EVIDENCE"}:
            stage_c_blocked = False
            for case in ("proposed", "normal", "disaster", "deterministic_k2"):
                if _has_certified_case(root, str(candidate["candidate_id"]), case):
                    _append_rows(root / "stage_c_certification.csv", [{"candidate_id": candidate["candidate_id"], "case": case, "status": "reused_certified_case"}])
                    continue
                ok, blocked = _run_full_replay(
                    root=root,
                    candidate=candidate,
                    cases=case,
                    timeout_seconds=float(args.stage_c_case_timeout_seconds),
                    args=args,
                    max_iterations=int(args.stage_c_iterations),
                    top_cuts=int(args.stage_c_top_cuts),
                    fixed_eval_max_iterations=int(args.stage_c_fixed_eval_iterations),
                    fixed_eval_top_cuts=int(args.stage_c_fixed_eval_top_cuts),
                    skip_existing=False,
                )
                if blocked:
                    _append_rows(root / "blocked_candidates.csv", [blocked])
                    _append_log(root, f"Stage C blocked {candidate['candidate_id']} {case}: {blocked['status']}.")
                    stage_c_blocked = True
                    break
                _append_rows(root / "stage_c_certification.csv", [{"candidate_id": candidate["candidate_id"], "case": case, "status": "completed"}])
            if stage_c_blocked:
                _refresh_rubric(root)
                continue
            reviews = _refresh_rubric(root)
            review = next((row for row in reviews if row.get("candidate_id") == candidate["candidate_id"]), {})
            if _is_acceptable_stop(review, args):
                _write_json(root / "pass_candidate.json", {"verdict": review.get("rubric_verdict"), "candidate": candidate, "rubric": review, "paper_final_promoted": False})
                _write_report(root, verdict=str(review.get("rubric_verdict")), start_time=start_time)
                print(f"PASS {candidate['candidate_id']} {review.get('rubric_verdict')}")
                return
            if str(review.get("rubric_verdict")) in {"PASS_PAPER_STORY", "PASS_WITH_REWRITE"}:
                _append_log(
                    root,
                    f"Soft pass {candidate['candidate_id']} ({review.get('rubric_verdict')}) "
                    "did not satisfy required paper-ready topology; continuing search.",
                )

    _refresh_rubric(root)
    _write_report(root, verdict="NEED_ALGORITHM_ACCELERATION", start_time=start_time)
    print("NEED_ALGORITHM_ACCELERATION")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--runtime-source", default=RUNTIME_SOURCE)
    parser.add_argument("--max-wall-clock-hours", type=float, default=12.0)
    parser.add_argument("--max-candidates", type=int, default=16)
    parser.add_argument("--max-stage-b-candidates", type=int, default=4)
    parser.add_argument(
        "--candidate-triples",
        default="",
        help=(
            "Optional comma-separated target candidates as cons/disaster or "
            "cons/normal/disaster, e.g. 0.015/1.35,0.016/1/1.45."
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stage-a-case", action="store_true")
    parser.add_argument("--case", default="")
    parser.add_argument("--m-cons", type=float, default=0.015)
    parser.add_argument("--m-normal", type=float, default=1.0)
    parser.add_argument("--m-disaster", type=float, default=1.25)
    parser.add_argument("--stage-a-timeout-seconds", type=float, default=360.0)
    parser.add_argument("--stage-b-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--stage-c-timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--stage-c-case-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--stage-a-iterations", type=int, default=15)
    parser.add_argument("--stage-a-top-cuts", type=int, default=5)
    parser.add_argument("--stage-b-iterations", type=int, default=60)
    parser.add_argument("--stage-b-top-cuts", type=int, default=10)
    parser.add_argument("--stage-b-fixed-eval-iterations", type=int, default=40)
    parser.add_argument("--stage-b-fixed-eval-top-cuts", type=int, default=10)
    parser.add_argument("--stage-c-iterations", type=int, default=100)
    parser.add_argument("--stage-c-top-cuts", type=int, default=20)
    parser.add_argument("--stage-c-fixed-eval-iterations", type=int, default=60)
    parser.add_argument("--stage-c-fixed-eval-top-cuts", type=int, default=20)
    parser.add_argument("--reuse-certified-disaster-training-phi", action="store_true")
    parser.add_argument("--require-paper-ready-topology", action="store_true")
    parser.add_argument("--stage-a-master-time-limit", type=float, default=60.0)
    parser.add_argument("--stage-a-separation-time-limit", type=float, default=90.0)
    parser.add_argument("--stage-a-master-mip-gap", type=float, default=0.05)
    parser.add_argument("--stage-a-separation-mip-gap", type=float, default=0.03)
    parser.add_argument("--stage-b-master-time-limit", type=float, default=120.0)
    parser.add_argument("--stage-b-separation-time-limit", type=float, default=180.0)
    parser.add_argument("--stage-b-master-mip-gap", type=float, default=0.03)
    parser.add_argument("--stage-b-separation-mip-gap", type=float, default=0.02)
    parser.add_argument("--max-iterations", type=int, default=15)
    parser.add_argument("--top-cuts", type=int, default=5)
    parser.add_argument("--master-time-limit-seconds", type=float, default=60.0)
    parser.add_argument("--master-mip-gap", type=float, default=0.05)
    parser.add_argument("--separation-time-limit-seconds", type=float, default=90.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.03)
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument("--neighbor-warm-start-limit", type=int, default=3)
    parser.add_argument("--neighbor-cut-pool-limit", type=int, default=1)
    parser.add_argument("--warm-start-plan-paths", default="")
    parser.add_argument("--initial-cut-pool-paths", default="")
    parser.add_argument("--enable-cut-signature-dedup", action="store_true")
    parser.add_argument("--enable-repeated-outage-guard", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()

    if args.stage_a_case:
        _stage_a_case(args)
    else:
        _main_search(args)


if __name__ == "__main__":
    main()
