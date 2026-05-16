"""Build K=16 certificate-closure diagnostics and Pro context pack."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SERIOUS_STEP_TYPES = {"ub_serious_initial", "ub_serious", "violation_serious"}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(path)


def _find_run_logs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(root.glob("runs/*/logs/*_run.json"))


def _artifact_path(payload: Mapping[str, Any], key: str) -> Path | None:
    raw = dict(payload.get("artifact_paths", {})).get(key)
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _last_iteration(payload: Mapping[str, Any]) -> dict[str, Any]:
    artifact = payload.get("iteration_log") or {}
    iterations = list(dict(artifact).get("iterations", ()))
    if not iterations:
        return {}
    return dict(iterations[-1])


def _summarize_run(log_path: Path, *, label: str) -> dict[str, Any]:
    payload = _read_json(log_path)
    summary = dict(payload.get("summary", {}))
    trial_certificate = dict(payload.get("trial_certificate") or {})
    last_iter = _last_iteration(payload)
    trial_path = _artifact_path(payload, "trial_certificate_path")
    cut_pool_path = _artifact_path(payload, "cut_pool_path")
    live_trace_path = _artifact_path(payload, "live_iteration_trace_path")
    return {
        "label": label,
        "run_id": str(payload.get("run_config", {}).get("run_id", log_path.stem)),
        "run_log_path": _relative(log_path),
        "validation_level": payload.get("validation_level", ""),
        "stop_reason": payload.get("stop_reason", ""),
        "solver_status": payload.get("solver_status", ""),
        "iteration_count": summary.get("iteration_count", ""),
        "cut_count": summary.get("cut_count", ""),
        "final_violation_upper_bound": summary.get("final_violation_upper_bound", ""),
        "last_iteration_violation": last_iter.get("separation_violation_value", ""),
        "last_candidate_source": last_iter.get("candidate_source", ""),
        "canonical_lower_bound": trial_certificate.get("canonical_lower_bound", ""),
        "pricing_derived_upper_bound": trial_certificate.get(
            "pricing_derived_upper_bound", ""
        ),
        "best_pricing_derived_upper_bound": trial_certificate.get(
            "best_pricing_derived_upper_bound", ""
        ),
        "pricing_gap_bound": trial_certificate.get("pricing_gap_bound", ""),
        "best_pricing_gap_bound": trial_certificate.get("best_pricing_gap_bound", ""),
        "trial_certificate_path": "" if trial_path is None else _relative(trial_path),
        "trial_plan_path": str(
            dict(payload.get("artifact_paths", {})).get("trial_plan_path") or ""
        ),
        "cut_pool_path": "" if cut_pool_path is None else _relative(cut_pool_path),
        "live_iteration_trace_path": (
            "" if live_trace_path is None else _relative(live_trace_path)
        ),
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _write_active_patterns(path: Path, live_trace_paths: Sequence[Path]) -> int:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for trace_path in live_trace_paths:
        if not trace_path.exists():
            continue
        with trace_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                step_type = str(row.get("certified_serious_step_type", ""))
                pattern = str(row.get("selected_outage_active_lines", "")).strip()
                if step_type not in SERIOUS_STEP_TYPES or not pattern or pattern in seen:
                    continue
                seen.add(pattern)
                rows.append({
                    "source_trace": _relative(trace_path),
                    "iteration_id": row.get("iteration_id", ""),
                    "certified_serious_step_type": step_type,
                    "pattern_key": pattern,
                    "selected_outage_active_lines": pattern,
                })
    _write_csv(path, rows)
    return len(rows)


def _copy_if_exists(src: Path, dst_dir: Path) -> str | None:
    if not src.exists():
        return None
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return _relative(dst)


def _copy_as_if_exists(src: Path, dst_dir: Path, dst_name: str) -> str | None:
    if not src.exists():
        return None
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / dst_name
    if src.resolve() != dst.resolve():
        shutil.copy2(src, dst)
    return _relative(dst)


def _write_pro_prompt(path: Path, *, closure_summary_path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "# K=16 CS-PFPB-CB Certificate Closure Question",
                "",
                "Please answer with extended effort and return a downloadable `.tex` file.",
                "",
                "We have an EVCS two-regime DRO Benders/NCCG implementation.",
                "The current CS-PFPB-CB trial point has full-support pricing violation",
                "below epsilon for K=16, but the point is produced by an auxiliary",
                "level-bundle/serious-step master, not by the canonical restricted",
                "master optimizer.",
                "",
                "The package contains the main paper context, the implemented",
                "CS-PFPB-CB notes, K=16 traces, trial_certificate.json, cut-pool",
                "state details, and the closure summary at:",
                f"`{_relative(closure_summary_path)}`.",
                "",
                "Mathematical question:",
                "",
                "1. Can the canonical restricted-master lower bound together with",
                "   the pricing-derived upper bound at the auxiliary serious-step",
                "   trial point be used as a valid sampled-DRO convergence",
                "   certificate, i.e. certify `UB_pricing - LB_canonical <= epsilon`?",
                "2. If yes, give a theorem, proof, exact certificate fields, and",
                "   local oracle tests. Clearly distinguish the auxiliary objective",
                "   from the canonical lower bound.",
                "3. If no, give the canonical closure algorithm needed after the",
                "   trial point, including what must be solved, what can be warm",
                "   started or seeded, and which fields are paper-facing.",
                "4. In either case, provide TeX-level algorithm notation and the",
                "   validity checks needed before claiming `epsilon_certified`.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _zip_dir(source_dir: Path, zip_path: Path) -> Path:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir.parent))
    return zip_path


def build_artifacts(args: argparse.Namespace) -> dict[str, Any]:
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    run_roots = [
        (label, Path(root))
        for item in args.run_roots
        for label, root in [item.split("=", 1)]
    ]
    rows: list[dict[str, Any]] = []
    for label, root in run_roots:
        for log_path in _find_run_logs(root):
            rows.append(_summarize_run(log_path, label=label))
    closure_summary_path = output_root / "closure_summary.csv"
    _write_csv(closure_summary_path, rows)

    live_trace_paths = [
        REPO_ROOT / str(row["live_iteration_trace_path"])
        for row in rows
        if row.get("live_iteration_trace_path")
    ]
    active_patterns_path = output_root / "last_serious_active_patterns.csv"
    active_pattern_count = _write_active_patterns(active_patterns_path, live_trace_paths)

    pack_dir = output_root / "pro_context_pack"
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)
    included_files: list[str] = []
    for raw_path in args.include_paths:
        copied = _copy_if_exists(Path(raw_path), pack_dir)
        if copied is not None:
            included_files.append(copied)
    for row in rows:
        label_prefix = str(row.get("label", "run")).replace("/", "_")
        for key in ("trial_certificate_path", "run_log_path"):
            raw = row.get(key)
            if raw:
                source = REPO_ROOT / str(raw)
                copied = _copy_as_if_exists(
                    source,
                    pack_dir,
                    f"{label_prefix}_{source.name}",
                )
                if copied is not None:
                    included_files.append(copied)
    copied_summary = _copy_if_exists(closure_summary_path, pack_dir)
    if copied_summary is not None:
        included_files.append(copied_summary)
    copied_patterns = _copy_if_exists(active_patterns_path, pack_dir)
    if copied_patterns is not None:
        included_files.append(copied_patterns)

    prompt_path = pack_dir / "pro_prompt_k16_certificate_closure.md"
    _write_pro_prompt(prompt_path, closure_summary_path=closure_summary_path)
    included_files.append(_relative(prompt_path))

    manifest = {
        "target": "K=16 CS-PFPB-CB certificate closure",
        "closure_summary_path": _relative(closure_summary_path),
        "last_serious_active_patterns_path": _relative(active_patterns_path),
        "active_pattern_count": active_pattern_count,
        "run_roots": [{"label": label, "root": str(root)} for label, root in run_roots],
        "included_files": sorted(set(included_files)),
        "question": "Can pricing-derived UB plus canonical RMP LB certify the sampled DRO gap?",
    }
    manifest_path = output_root / "pro_context_pack_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    shutil.copy2(manifest_path, pack_dir / manifest_path.name)
    decision_path = output_root / "math_layer_next_decision.md"
    decision_path.write_text(
        "\n".join(
            [
                "# Math Layer Next Decision",
                "",
                "Status: engineering certificate artifacts are prepared.",
                "",
                "Next mathematical decision:",
                "ask Pro whether `UB_pricing - LB_canonical` is a valid paper-facing",
                "sampled-DRO certificate for the auxiliary serious-step trial point.",
                "",
                "Adoption rule:",
                "- If Pro approves, implement validation level `epsilon_certified_pricing_ub`.",
                "- If Pro rejects it, implement the canonical closure phase only.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    zip_path = output_root / "k16_certificate_closure_pro_context.zip"
    manifest["pro_context_zip_path"] = _relative(zip_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    shutil.copy2(manifest_path, pack_dir / manifest_path.name)
    _zip_dir(pack_dir, zip_path)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        default="results/engineering_acceleration/certificate_closure_k16",
    )
    parser.add_argument(
        "--run-root",
        dest="run_roots",
        action="append",
        default=[],
        help="Labeled root in the form label=path. Can be repeated.",
    )
    parser.add_argument(
        "--include-path",
        dest="include_paths",
        action="append",
        default=[],
        help="Extra file to copy into the Pro pack. Can be repeated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.run_roots:
        args.run_roots = [
            "cs_trial=results/engineering_acceleration/k16_certificate_closure_20260506",
            "cs_serialized=results/engineering_acceleration/cs_pfpb_cb_serialized_20260506",
            "canonical_closure=results/engineering_acceleration/cs_canonical_closure_serialized_20260506",
        ]
    if not args.include_paths:
        args.include_paths = [
            "reference/main_paper.pdf",
            "results/engineering_acceleration/cs_pfpb_cb_prototype_report_20260506.md",
            "results/engineering_acceleration/k16_cs_pfpb_cb_comparison_20260506.csv",
            "results/engineering_acceleration/figures/k16_cs_pfpb_cb_violation_comparison.png",
            "/Users/shixinliu/Downloads/evcs_dro_nccg_bc_next_step (2).tex",
        ]
    manifest = build_artifacts(args)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
