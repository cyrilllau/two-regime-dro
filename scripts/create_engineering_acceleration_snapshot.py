"""Create a restore checkpoint before engineering acceleration experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "results/engineering_acceleration/pre_accel_snapshot"
LOCK_TAG = "paper-default-0p0152-1p4-repro-20260503"
TRACKED_ARTIFACTS = (
    "docs/analysis_packs/ieee_experiment_section.tex",
    "docs/analysis_packs/ieee_experiment_section_standalone.pdf",
    "results/paper_final/setup_parameter_table.csv",
    "results/paper_final/objective_components_tableIII.csv",
    "results/paper_final/sensitivity_components_tableIV.csv",
    "results/paper_final/default_topology_evidence.csv",
    "results/paper_final/deterministic_worst_distribution.csv",
    "results/paper_final/logs/default_scale_v2_proposed_run.json",
    "results/paper_final/plans/default_scale_v2_proposed_plan.csv",
)


def _run_git(args: list[str], *, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=check,
        text=True,
        capture_output=True,
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--lock-tag", default=LOCK_TAG)
    args = parser.parse_args()

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    head = _run_git(["rev-parse", "HEAD"])
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    status = _run_git(["status", "--short", "--branch"])
    dirty_patch = _run_git(["diff", "--binary"], check=True)
    paper_dirty_patch = _run_git(
        [
            "diff",
            "--binary",
            "--",
            ".",
            ":(exclude)src/production/benders_engine.py",
            ":(exclude)src/production/master_problem.py",
            ":(exclude)src/production/separation_milp.py",
            ":(exclude)scripts/experiment_pack_utils.py",
            ":(exclude)scripts/analyze_engineering_acceleration_baseline.py",
            ":(exclude)scripts/create_engineering_acceleration_snapshot.py",
            ":(exclude)scripts/run_engineering_acceleration_experiments.py",
            ":(exclude)tests/unit/test_engineering_acceleration_utils.py",
            ":(exclude)results/engineering_acceleration",
        ],
        check=True,
    )
    tag_commit = _run_git(["rev-list", "-n", "1", args.lock_tag], check=False)
    tags_at_head = _run_git(["tag", "--points-at", "HEAD"], check=False).splitlines()

    (output / "git_status.txt").write_text(status + "\n", encoding="utf-8")
    (output / "dirty.patch").write_text(dirty_patch, encoding="utf-8")
    (output / "paper_artifact_dirty.patch").write_text(paper_dirty_patch, encoding="utf-8")

    artifact_hashes = {
        rel_path: {
            "exists": (REPO_ROOT / rel_path).exists(),
            "sha256": _sha256(REPO_ROOT / rel_path),
        }
        for rel_path in TRACKED_ARTIFACTS
    }
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "branch": branch,
        "head": head,
        "lock_tag": args.lock_tag,
        "lock_tag_commit": tag_commit,
        "tags_at_head": tags_at_head,
        "dirty_patch": str(output / "dirty.patch"),
        "paper_artifact_dirty_patch": str(output / "paper_artifact_dirty.patch"),
        "git_status": str(output / "git_status.txt"),
        "artifact_hashes": artifact_hashes,
        "restore_instructions": [
            f"git checkout {args.lock_tag}",
            "or apply the saved dirty.patch onto the recorded HEAD if recovering the current dirty working state",
            "do not promote engineering acceleration outputs into results/paper_final without an explicit audit PASS",
        ],
    }
    _write_json(output / "restore_manifest.json", manifest)
    print(json.dumps({"snapshot": str(output), "head": head, "branch": branch}, sort_keys=True))


if __name__ == "__main__":
    main()
