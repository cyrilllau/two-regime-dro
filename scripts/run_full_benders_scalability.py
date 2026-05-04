"""Run full-Benders B/K scalability experiments for the accepted default case."""

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

from scripts.experiment_pack_utils import execute_run, load_critical_buses  # noqa: E402
from scripts.run_separation_scalability import _summarize_milp  # noqa: E402


DEFAULT_ACCEPTED_LOG = (
    REPO_ROOT
    / "results/paper_final/logs/"
    "default_multiplier_mult_cons0p015_normal1_disaster1p25_proposed_run.json"
)
CRITICAL_BUSES = REPO_ROOT / "configs/critical_buses_paper_fig2.yaml"


def _parse_ints(raw: str) -> tuple[int, ...]:
    return tuple(int(token.strip()) for token in raw.split(",") if token.strip())


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _read_accepted_config(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = dict(payload["run_config"] if "run_config" in payload else payload)
    if config.get("mode") != "integrated_mainline" or config.get("solver") != "benders":
        raise ValueError(f"{path} is not the accepted proposed Benders run config.")
    return config


def _build_config(
    accepted: Mapping[str, Any],
    *,
    run_id: str,
    runtime_source: str,
    a_count: int,
    b_count: int,
    k: int,
    top_cuts: int,
    max_iterations: int,
    epsilon_cert: float,
    master_time_limit_seconds: float,
    master_mip_gap: float,
    separation_time_limit_seconds: float,
    separation_mip_gap: float,
    omega_bound_upper: float,
) -> dict[str, Any]:
    config = json.loads(json.dumps(dict(accepted)))
    config.update(
        {
            "run_id": run_id,
            "case_name": run_id,
            "family_name": "full_benders_scalability",
            "runtime_source": runtime_source,
            "mode": "integrated_mainline",
            "solver": "benders",
            "parameter_regime": "accepted_default_mult_cons0p015_normal1_disaster1p25",
            "selection": {
                "scenarios_a": list(range(1, int(a_count) + 1)),
                "scenarios_b": list(range(1, int(b_count) + 1)),
            },
        }
    )
    overrides = dict(config.get("parameter_overrides", {}))
    ambiguity = dict(overrides.get("ambiguity", {}))
    ambiguity["k_max_outages"] = int(k)
    overrides["ambiguity"] = ambiguity
    config["parameter_overrides"] = overrides
    config["benders"] = {
        "epsilon_cert": float(epsilon_cert),
        "max_iterations": int(max_iterations),
        "master_time_limit_seconds": float(master_time_limit_seconds),
        "master_mip_gap": float(master_mip_gap),
        "separation_time_limit_seconds": float(separation_time_limit_seconds),
        "separation_mip_gap": float(separation_mip_gap),
        "separation_top_cuts_per_iteration": int(top_cuts),
        "allow_master_suboptimal_incumbent": True,
        "omega_bound_upper": float(omega_bound_upper),
    }
    return config


def _is_certified(row: Mapping[str, Any]) -> bool:
    return str(row.get("validation_level", "")) in {"exact", "epsilon_certified"}


def _run_or_reuse(
    *,
    config: Mapping[str, Any],
    output_root: Path,
    skip_existing: bool,
) -> dict[str, Any]:
    run_id = str(config["run_id"])
    log_path = output_root / "logs" / f"{run_id}_run.json"
    if skip_existing and log_path.exists():
        return _summarize_milp(log_path, run_id=run_id)
    critical_buses = load_critical_buses(CRITICAL_BUSES)
    execute_run(dict(config), critical_buses=critical_buses, output_root=output_root)
    return _summarize_milp(log_path, run_id=run_id)


def _append_progress(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _write_rows(path, rows)


def _paper_status(row: Mapping[str, Any]) -> str:
    return "certified" if _is_certified(row) else "diagnostic_stress"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-log", default=str(DEFAULT_ACCEPTED_LOG))
    parser.add_argument("--runtime-source", default="data/colleague_default_synth_100x100")
    parser.add_argument("--output-root", default="results/paper_final")
    parser.add_argument("--b-values", default="5,10,20,50,100")
    parser.add_argument("--k-values", default="1,2,3,5,7,10")
    parser.add_argument("--completion-k-values", default="7,10")
    parser.add_argument("--a-count", type=int, default=10)
    parser.add_argument("--top-cuts", type=int, default=3)
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--completion-max-iterations", type=int, default=300)
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--master-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--master-mip-gap", type=float, default=0.02)
    parser.add_argument("--separation-time-limit-seconds", type=float, default=300.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.02)
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    accepted = _read_accepted_config(Path(args.accepted_log))
    output_root = Path(args.output_root)
    standard_root = output_root / "full_benders_scaling_runs" / "milp"
    completion_root = output_root / "full_benders_completion_runs" / "milp"
    b_values = _parse_ints(args.b_values)
    k_values = _parse_ints(args.k_values)
    completion_k_values = set(_parse_ints(args.completion_k_values))

    run_configs: list[dict[str, Any]] = []
    for b in b_values:
        run_configs.append(
            _build_config(
                accepted,
                run_id=f"full_benders_A{args.a_count:02d}_B{b:03d}_K02_top{args.top_cuts:03d}",
                runtime_source=args.runtime_source,
                a_count=args.a_count,
                b_count=b,
                k=2,
                top_cuts=args.top_cuts,
                max_iterations=args.max_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
            )
        )
    for k in k_values:
        run_configs.append(
            _build_config(
                accepted,
                run_id=f"full_benders_A{args.a_count:02d}_B010_K{k:02d}_top{args.top_cuts:03d}",
                runtime_source=args.runtime_source,
                a_count=args.a_count,
                b_count=10,
                k=k,
                top_cuts=args.top_cuts,
                max_iterations=args.max_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
            )
        )
    unique_run_configs: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for config in run_configs:
        run_id = str(config["run_id"])
        if run_id in seen_run_ids:
            continue
        seen_run_ids.add(run_id)
        unique_run_configs.append(config)
    matrix_entry_count = len(run_configs)
    run_configs = unique_run_configs

    output_root.mkdir(parents=True, exist_ok=True)
    _write_json(
        output_root / "full_benders_scaling_manifest.json",
        {
            "accepted_log": str(args.accepted_log),
            "runtime_source": args.runtime_source,
            "a_count": int(args.a_count),
            "b_values": list(b_values),
            "k_values": list(k_values),
            "top_cuts": int(args.top_cuts),
            "max_iterations": int(args.max_iterations),
            "completion_k_values": sorted(completion_k_values),
            "completion_max_iterations": int(args.completion_max_iterations),
            "matrix_entry_count": matrix_entry_count,
            "run_ids": [config["run_id"] for config in run_configs],
            "policy": "full Benders convergence runs only; no exact enumeration",
        },
    )
    if args.dry_run:
        print(json.dumps({"run_ids": [config["run_id"] for config in run_configs]}, indent=2))
        return

    rows: list[dict[str, Any]] = []
    for index, config in enumerate(run_configs, start=1):
        print(f"[{index}/{len(run_configs)}] {config['run_id']}", flush=True)
        row = _run_or_reuse(config=config, output_root=standard_root, skip_existing=args.skip_existing)
        row["paper_status"] = _paper_status(row)
        row["source_run_role"] = "standard_100_iteration_scaling"
        rows.append(row)
        _append_progress(output_root / "full_benders_scaling_progress.csv", rows)

        k_value = int(row["K"])
        if (
            k_value in completion_k_values
            and int(row["B"]) == 10
            and not _is_certified(row)
        ):
            completion_config = _build_config(
                accepted,
                run_id=(
                    f"full_benders_completion_A{args.a_count:02d}_B010_"
                    f"K{k_value:02d}_top{args.top_cuts:03d}_max{args.completion_max_iterations}"
                ),
                runtime_source=args.runtime_source,
                a_count=args.a_count,
                b_count=10,
                k=k_value,
                top_cuts=args.top_cuts,
                max_iterations=args.completion_max_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
            )
            print(f"[completion] {completion_config['run_id']}", flush=True)
            completion_row = _run_or_reuse(
                config=completion_config,
                output_root=completion_root,
                skip_existing=args.skip_existing,
            )
            completion_row["paper_status"] = _paper_status(completion_row)
            completion_row["source_run_role"] = "completion_high_budget"
            rows.append(completion_row)
            _append_progress(output_root / "full_benders_scaling_progress.csv", rows)

    print(json.dumps({"completed_rows": len(rows)}, sort_keys=True))


if __name__ == "__main__":
    main()
