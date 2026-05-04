"""Run disaster-economics calibration candidates for paper-ready tradeoff search."""

from __future__ import annotations

import argparse
import copy
import csv
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiment_pack_utils import (
    execute_run,
    load_critical_buses,
    load_yaml_file,
)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _candidate_id(
    cls_critical: float,
    cls_noncritical: float,
    pi_f: float,
    cpur_scale: float,
    ctrans_scale: float,
) -> str:
    cls_text = f"{cls_critical:g}_{cls_noncritical:g}".replace(".", "p")
    pi_text = str(pi_f).replace(".", "p")
    cpur_text = str(cpur_scale).replace(".", "p")
    ctrans_text = str(ctrans_scale).replace(".", "p")
    return f"cls{cls_text}_pi{pi_text}_cpur{cpur_text}_ctrans{ctrans_text}"


def _parse_cls_pairs(raw_pairs: str, raw_scales: str) -> list[tuple[float, float]]:
    if raw_pairs.strip():
        pairs: list[tuple[float, float]] = []
        for token in raw_pairs.split(","):
            if not token.strip():
                continue
            left, right = token.split(":", maxsplit=1)
            pairs.append((float(left), float(right)))
        return pairs
    return [
        (50.0 * float(scale), 10.0 * float(scale))
        for scale in raw_scales.split(",")
        if scale.strip()
    ]


def _build_run(
    base: dict[str, Any],
    *,
    candidate: str,
    mode_name: str,
    runtime_source: str,
    scenarios_a: list[int],
    scenarios_b: list[int],
    cls_critical: float,
    cls_noncritical: float,
    pi_f: float,
    cpur_values: list[float] | None,
    ctrans_scalar: float | None,
    k: int,
    ev_penetration_scale: float | None,
    max_iterations: int,
    epsilon_cert: float,
    warm_start_plan_paths: list[str],
    master_time_limit_seconds: float | None,
    master_mip_gap: float | None,
    allow_master_suboptimal_incumbent: bool,
) -> dict[str, Any]:
    run = copy.deepcopy(base)
    run["run_id"] = f"tradeoff_{candidate}_{mode_name}"
    run["case_name"] = run["run_id"]
    run["family_name"] = "tradeoff_calibration"
    run["parameter_regime"] = candidate
    run["runtime_source"] = runtime_source
    run["selection"] = {"scenarios_a": scenarios_a, "scenarios_b": scenarios_b}
    if ev_penetration_scale is not None:
        run["ev_penetration_scale"] = float(ev_penetration_scale)
    overrides = copy.deepcopy(run.get("parameter_overrides", {}))
    economics = dict(overrides.get("economics", {}))
    economics["pi_f"] = float(pi_f)
    if cpur_values is not None:
        economics["cpur"] = [float(value) for value in cpur_values]
    if ctrans_scalar is not None:
        economics["ctrans_scalar"] = float(ctrans_scalar)
    overrides["economics"] = economics
    ambiguity = dict(overrides.get("ambiguity", {}))
    ambiguity["k_max_outages"] = int(k)
    overrides["ambiguity"] = ambiguity
    overrides["disaster_objective"] = {
        "cls_critical": float(cls_critical),
        "cls_noncritical": float(cls_noncritical),
    }
    run["parameter_overrides"] = overrides
    if run["solver"] == "benders":
        run["benders"] = {
            "epsilon_cert": float(epsilon_cert),
            "max_iterations": int(max_iterations),
            "warm_start_plan_paths": list(warm_start_plan_paths),
            "allow_master_suboptimal_incumbent": bool(allow_master_suboptimal_incumbent),
        }
        if master_time_limit_seconds is not None:
            run["benders"]["master_time_limit_seconds"] = float(master_time_limit_seconds)
        if master_mip_gap is not None:
            run["benders"]["master_mip_gap"] = float(master_mip_gap)
    return run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="results/tradeoff_calibration")
    parser.add_argument("--manifest", default="configs/experiments/paper_like_tableII_family.yaml")
    parser.add_argument("--runtime-source", default="data/runtime_12_synth_100")
    parser.add_argument("--scenario-count-a", type=int, default=10)
    parser.add_argument("--scenario-count-b", type=int, default=10)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--ev-penetration-scale", type=float, default=None)
    parser.add_argument("--cls-scales", default="10,20,50")
    parser.add_argument("--cls-pairs", default="")
    parser.add_argument("--pi-values", default="0.3,0.5")
    parser.add_argument("--cpur-scales", default="1.0")
    parser.add_argument("--ctrans-scales", default="1.0")
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--epsilon-cert", type=float, default=20000.0)
    parser.add_argument("--warm-start-root", default="results/paper_final/plans")
    parser.add_argument("--master-time-limit-seconds", type=float, default=None)
    parser.add_argument("--master-mip-gap", type=float, default=None)
    parser.add_argument("--allow-master-suboptimal-incumbent", action="store_true")
    parser.add_argument(
        "--modes",
        default="integrated,normal,deterministic",
        help="Comma-separated subset of integrated, normal, deterministic.",
    )
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    output_root = Path(args.output_root)
    (output_root / "plans").mkdir(parents=True, exist_ok=True)
    (output_root / "logs").mkdir(parents=True, exist_ok=True)
    summary_path = output_root / "summary.csv"
    failure_path = output_root / "failures.csv"
    summary_rows = _read_rows(summary_path)
    failure_rows = _read_rows(failure_path)
    existing = {row["run_id"] for row in summary_rows}

    family = load_yaml_file(args.manifest)
    bases = {row["run_id"]: row for row in family["runs"]}
    base_by_mode = {
        "integrated": bases["integrated_mainline_paper_like"],
        "normal": bases["normal_only_paper_like"],
        "deterministic": bases["deterministic_mean_value_paper_like"],
        "deterministic_disaster_mean": {
            **bases["deterministic_mean_value_paper_like"],
            "mode": "deterministic_disaster_mean_value",
        },
    }
    selected_modes = tuple(token.strip() for token in args.modes.split(",") if token.strip())
    invalid_modes = tuple(mode for mode in selected_modes if mode not in base_by_mode)
    if invalid_modes:
        raise ValueError(f"Unsupported --modes values: {invalid_modes}")
    scenarios_a = list(range(1, args.scenario_count_a + 1))
    scenarios_b = list(range(1, args.scenario_count_b + 1))
    critical_buses = load_critical_buses("configs/critical_buses_paper_fig2.yaml")
    runtime_parameters = json.loads((Path(args.runtime_source) / "parameters.json").read_text(encoding="utf-8"))
    base_cpur = [float(value) for value in runtime_parameters["econ"]["Cpur"]]
    warm_root = Path(args.warm_start_root)
    warm_start_plan_paths = [
        str(path)
        for path in (
            warm_root / "paper_scale_matrix_A10_B10_k2_integrated_plan.csv",
            warm_root / "paper_scale_matrix_A10_B10_k2_normal_plan.csv",
            warm_root / "paper_scale_matrix_A10_B10_k2_deterministic_plan.csv",
        )
        if path.exists()
    ]

    runs: list[dict[str, Any]] = []
    for cls_critical, cls_noncritical in _parse_cls_pairs(args.cls_pairs, args.cls_scales):
        for pi_f in [float(token) for token in args.pi_values.split(",") if token.strip()]:
            for cpur_scale in [float(token) for token in args.cpur_scales.split(",") if token.strip()]:
                for ctrans_scale in [float(token) for token in args.ctrans_scales.split(",") if token.strip()]:
                    candidate = _candidate_id(
                        cls_critical,
                        cls_noncritical,
                        pi_f,
                        cpur_scale,
                        ctrans_scale,
                    )
                    cpur_values = [value * float(cpur_scale) for value in base_cpur]
                    base_ctrans = float(base_by_mode["integrated"]["parameter_overrides"]["economics"].get("ctrans_scalar", 0.0435))
                    ctrans_scalar = base_ctrans * float(ctrans_scale)
                    for mode_name in selected_modes:
                        base = base_by_mode[mode_name]
                        runs.append(
                            _build_run(
                                base,
                                candidate=candidate,
                                mode_name=mode_name,
                                runtime_source=args.runtime_source,
                                scenarios_a=scenarios_a,
                                scenarios_b=scenarios_b,
                                cls_critical=cls_critical,
                                cls_noncritical=cls_noncritical,
                                pi_f=pi_f,
                                cpur_values=cpur_values,
                                ctrans_scalar=ctrans_scalar,
                                k=args.k,
                                ev_penetration_scale=args.ev_penetration_scale,
                                max_iterations=args.max_iterations,
                                epsilon_cert=args.epsilon_cert,
                                warm_start_plan_paths=warm_start_plan_paths,
                                master_time_limit_seconds=args.master_time_limit_seconds,
                                master_mip_gap=args.master_mip_gap,
                                allow_master_suboptimal_incumbent=args.allow_master_suboptimal_incumbent,
                            )
                        )

    for index, run in enumerate(runs, start=1):
        if args.skip_existing and run["run_id"] in existing:
            if args.verbose:
                print(f"[{index}/{len(runs)}] skip existing {run['run_id']}")
            continue
        if args.verbose:
            print(f"[{index}/{len(runs)}] run={run['run_id']}")
        result = execute_run(run, critical_buses=critical_buses, output_root=output_root)
        summary_rows.append(result["summary"].to_csv_row())
        existing.add(run["run_id"])
        if result["failure_summary"] is not None:
            failure_rows.append(result["failure_summary"].to_csv_row())
        _write_rows(summary_path, summary_rows)
        if failure_rows:
            _write_rows(failure_path, failure_rows)
        if args.verbose:
            row = result["summary"].to_csv_row()
            print(
                f"  -> {row['validation_level']} | stop={row['stop_reason']} | "
                f"iter={row['iteration_count']} | cuts={row['cut_count']} | obj={row['total_objective']}"
            )


if __name__ == "__main__":
    main()
