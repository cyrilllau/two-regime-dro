"""Run large-scale scenario/K-scaling experiment pack for paper_final artifacts."""

from __future__ import annotations

import argparse
import copy
import csv
import sys
import shutil
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.audit.experiment_summary import (
    ExperimentFailureSummary,
    ExperimentRunSummary,
)
from experiment_pack_utils import (
    execute_run,
    load_critical_buses,
    load_yaml_file,
)


def _read_existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _copy_baseline_outputs(
    source_root: Path,
    target_root: Path,
    *,
    include_summary: bool = True,
) -> None:
    source_summary = source_root / "summary.csv"
    source_failures = source_root / "failures.csv"
    if include_summary and source_summary.exists():
        shutil.copy2(source_summary, target_root / "summary.csv")
    if source_failures.exists():
        shutil.copy2(source_failures, target_root / "failures.csv")

    for name in ("plans", "logs"):
        src_dir = source_root / name
        dst_dir = target_root / name
        if not src_dir.exists():
            continue
        for src_path in sorted(src_dir.iterdir()):
            if src_path.is_file():
                shutil.copy2(src_path, dst_dir / src_path.name)


def _build_benders_run(
    base: dict[str, Any],
    *,
    run_id: str,
    scenarios_a: Sequence[int],
    scenarios_b: Sequence[int],
    k: int,
    max_iterations: int,
    epsilon_cert: float,
    ev_penetration_scale: float = 1.0,
    family_name: str = "paper_scale_matrix",
) -> dict[str, Any]:
    parameter_overrides = copy.deepcopy(base.get("parameter_overrides", {}))
    ambiguity_overrides = dict(parameter_overrides.get("ambiguity", {}))
    ambiguity_overrides["k_max_outages"] = int(k)
    parameter_overrides["ambiguity"] = ambiguity_overrides

    run: dict[str, Any] = {
        "run_id": run_id,
        "family_name": family_name,
        "case_name": run_id,
        "runtime_source": base["runtime_source"],
        "selection": {"scenarios_a": list(scenarios_a), "scenarios_b": list(scenarios_b)},
        "mode": base["mode"],
        "solver": base["solver"],
        "parameter_regime": family_name,
        "parameter_overrides": parameter_overrides,
        "benders": {
            "epsilon_cert": float(epsilon_cert),
            "max_iterations": int(max_iterations),
        },
    }
    if float(ev_penetration_scale) != 1.0:
        run["ev_penetration_scale"] = float(ev_penetration_scale)
    return run


def _build_direct_run(
    base: dict[str, Any],
    *,
    run_id: str,
    scenarios_a: Sequence[int],
    scenarios_b: Sequence[int],
    k: int,
    family_name: str = "paper_scale_matrix",
) -> dict[str, Any]:
    parameter_overrides = copy.deepcopy(base.get("parameter_overrides", {}))
    ambiguity_overrides = dict(parameter_overrides.get("ambiguity", {}))
    ambiguity_overrides["k_max_outages"] = int(k)
    parameter_overrides["ambiguity"] = ambiguity_overrides

    return {
        "run_id": run_id,
        "family_name": family_name,
        "case_name": run_id,
        "runtime_source": base["runtime_source"],
        "selection": {"scenarios_a": list(scenarios_a), "scenarios_b": list(scenarios_b)},
        "mode": base["mode"],
        "solver": base["solver"],
        "parameter_regime": family_name,
        "parameter_overrides": parameter_overrides,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="results/paper_final")
    parser.add_argument("--manifest", default="configs/experiments/paper_like_tableII_family.yaml")
    parser.add_argument("--baseline-root", default="results")
    parser.add_argument(
        "--runtime-source",
        default=None,
        help="Optional runtime data directory overriding the manifest runtime_source.",
    )
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--epsilon-cert", type=float, default=0.0)
    parser.add_argument("--skip-baseline-copy", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument(
        "--skip-ev-stress",
        action="store_true",
        help="Skip EV penetration stress runs for large scenario-scaling sweeps.",
    )
    parser.add_argument(
        "--scenario-pairs",
        default="1x1,3x2,5x2,10x10",
        help="Comma-separated scenario pairs in format axb, e.g. 3x2",
    )
    parser.add_argument(
        "--k-values",
        default="1,2,3,5,7,10",
        help="Comma-separated K values for fixed 10x10 support runs",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    scenario_pairs = [
        tuple(int(part) for part in pair.split("x", maxsplit=1))
        for pair in args.scenario_pairs.split(",")
        if pair.strip()
    ]
    k_values = [int(token) for token in args.k_values.split(",") if token.strip()]

    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "plans").mkdir(exist_ok=True)
    (output_root / "logs").mkdir(exist_ok=True)
    (output_root / "figures").mkdir(exist_ok=True)

    if output_root.exists():
        # keep this file-level idempotent: we intentionally keep prior non-target artifacts
        # and only append missing run_ids below.
        pass

    if not args.skip_baseline_copy:
        _copy_baseline_outputs(Path(args.baseline_root), output_root)

    existing_summary = {row["run_id"] for row in _read_existing_rows(output_root / "summary.csv")}
    # Keep runtime summary and failures append-only for resumable long runs.
    summary_rows = _read_existing_rows(output_root / "summary.csv")
    failure_rows = _read_existing_rows(output_root / "failures.csv")

    family = load_yaml_file(args.manifest)
    base_runs = {row["run_id"]: row for row in family["runs"]}
    integrated_base = base_runs["integrated_mainline_paper_like"]
    normal_base = base_runs["normal_only_paper_like"]
    deterministic_base = base_runs["deterministic_mean_value_paper_like"]
    if args.runtime_source is not None:
        for base_run in (integrated_base, normal_base, deterministic_base):
            base_run["runtime_source"] = str(args.runtime_source)

    critical_buses = load_critical_buses("configs/critical_buses_paper_fig2.yaml")

    runs: list[dict[str, Any]] = []
    family_name = "paper_scale_matrix"

    for a, b in scenario_pairs:
        scenarios_a = list(range(1, int(a) + 1))
        scenarios_b = list(range(1, int(b) + 1))
        pair_id = f"A{int(a):02d}_B{int(b):02d}"

        runs.append(
            _build_benders_run(
                integrated_base,
                run_id=f"{family_name}_{pair_id}_k2_integrated",
                scenarios_a=scenarios_a,
                scenarios_b=scenarios_b,
                k=2,
                max_iterations=args.max_iterations,
                epsilon_cert=args.epsilon_cert,
                family_name=family_name,
            ),
        )
        runs.append(
            _build_direct_run(
                normal_base,
                run_id=f"{family_name}_{pair_id}_k2_normal",
                scenarios_a=scenarios_a,
                scenarios_b=scenarios_b,
                k=2,
                family_name=family_name,
            ),
        )
        runs.append(
            _build_benders_run(
                deterministic_base,
                run_id=f"{family_name}_{pair_id}_k2_deterministic",
                scenarios_a=scenarios_a,
                scenarios_b=scenarios_b,
                k=2,
                max_iterations=args.max_iterations,
                epsilon_cert=args.epsilon_cert,
                family_name=family_name,
            ),
        )

    # EV penetration stress on top of the largest support.
    if not args.skip_ev_stress:
        full_a_b = max((a for a, _ in scenario_pairs), default=10)
        full_b = max((b for _, b in scenario_pairs), default=10)
        run_pair = f"A{full_a_b:02d}_B{full_b:02d}"
        for ev_scale in (1.5, 2.0):
            runs.append(
                _build_benders_run(
                    integrated_base,
                    run_id=f"{family_name}_{run_pair}_k2_ev{str(ev_scale).replace('.', 'p')}",
                    scenarios_a=list(range(1, full_a_b + 1)),
                    scenarios_b=list(range(1, full_b + 1)),
                    k=2,
                    max_iterations=args.max_iterations,
                    epsilon_cert=args.epsilon_cert,
                    ev_penetration_scale=ev_scale,
                    family_name=family_name,
                ),
            )

    # K-scaling at full 10x10 support.
    full_a_b = 10
    scenarios_a = list(range(1, full_a_b + 1))
    scenarios_b = list(range(1, full_a_b + 1))
    for k in k_values:
        runs.append(
            _build_benders_run(
                integrated_base,
                run_id=f"{family_name}_A10x10_K{k:02d}_integrated",
                scenarios_a=scenarios_a,
                scenarios_b=scenarios_b,
                k=k,
                max_iterations=args.max_iterations,
                epsilon_cert=args.epsilon_cert,
                family_name=family_name,
            ),
        )
        runs.append(
            _build_benders_run(
                deterministic_base,
                run_id=f"{family_name}_A10x10_K{k:02d}_deterministic",
                scenarios_a=scenarios_a,
                scenarios_b=scenarios_b,
                k=k,
                max_iterations=args.max_iterations,
                epsilon_cert=args.epsilon_cert,
                family_name=family_name,
            ),
        )
        runs.append(
            _build_direct_run(
                normal_base,
                run_id=f"{family_name}_A10x10_K{k:02d}_normal",
                scenarios_a=scenarios_a,
                scenarios_b=scenarios_b,
                k=k,
                family_name=family_name,
            ),
        )

    # Keep run count bounded; duplicate ids may happen with repeated inputs.
    dedup_runs: list[dict[str, Any]] = []
    seen = set()
    for run in runs:
        if run["run_id"] in seen:
            continue
        seen.add(run["run_id"])
        dedup_runs.append(run)

    for idx, run_config in enumerate(dedup_runs, start=1):
        if args.verbose:
            print(f"[{idx}/{len(dedup_runs)}] run={run_config['run_id']}")
        if args.skip_existing and run_config["run_id"] in existing_summary:
            if args.verbose:
                print(f"  -> skipped (already in summary)")
            continue
        result = execute_run(run_config, critical_buses=critical_buses, output_root=output_root)
        summary = result["summary"]
        failure = result["failure_summary"]
        # persist immediately to avoid long-run interruption loss.
        summary_dict = summary.to_csv_row()
        if summary_dict.get("run_id") not in existing_summary:
            summary_rows.append(summary_dict)
            existing_summary.add(summary_dict.get("run_id"))
            with (output_root / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(ExperimentRunSummary.__dataclass_fields__.keys()))
                writer.writeheader()
                for row in summary_rows:
                    writer.writerow(row)
        if failure is not None:
            failure_dict = failure.to_csv_row()
            exists_fail = {row["run_id"] for row in failure_rows}
            if failure_dict.get("run_id") not in exists_fail:
                failure_rows.append(failure_dict)
                with (output_root / "failures.csv").open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=list(ExperimentFailureSummary.__dataclass_fields__.keys()),
                    )
                    writer.writeheader()
                    for row in failure_rows:
                        writer.writerow(row)
        if args.verbose:
            print(
                f"  -> {summary.validation_level} | stop={summary.stop_reason} | iter={summary.iteration_count} "
                f"| cuts={summary.cut_count} | obj={summary.total_objective}"
            )

    print(f"summary rows now: {len(summary_rows)}")
    print(f"failure rows now: {len(failure_rows)}")


if __name__ == "__main__":
    main()
