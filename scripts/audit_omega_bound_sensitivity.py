"""Audit whether the separation evaluator is stable to omega big-M bounds."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import (  # noqa: E402
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from scripts.build_paper_final_analysis import CRITICAL_BUS_CONFIG  # noqa: E402
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan  # noqa: E402
from src.reference.outage_enumerator import derive_single_line_omega_bounds  # noqa: E402
from src.production.separation_milp import solve_separation_milp  # noqa: E402


def _read_rows(path: Path) -> list[dict[str, str]]:
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


def _load_plan(path: Path, instance):
    rows = _read_rows(path)
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--run-ids", required=True, help="Comma-separated run ids with plans.")
    parser.add_argument("--config-run-id", required=True)
    parser.add_argument("--safety-factors", default="1,2,5,10,50,100")
    parser.add_argument("--output-csv", default="omega_bound_sensitivity.csv")
    parser.add_argument("--output-md", default="omega_bound_sensitivity.md")
    parser.add_argument("--relative-tolerance", type=float, default=0.05)
    args = parser.parse_args()

    root = Path(args.input_root)
    config = json.loads((root / "logs" / f"{args.config_run_id}_run.json").read_text())[
        "run_config"
    ]
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    instance = prepare_instance_for_run(
        load_instance_for_run(config, critical_buses=critical_buses),
        config,
    )
    safety_factors = [float(token) for token in args.safety_factors.split(",") if token.strip()]
    rows: list[dict[str, Any]] = []
    for run_id in [token.strip() for token in args.run_ids.split(",") if token.strip()]:
        plan = _load_plan(root / "plans" / f"{run_id}_plan.csv", instance)
        for safety_factor in safety_factors:
            bounds = derive_single_line_omega_bounds(
                instance,
                plan=plan,
                budget_k=int(instance.ambiguity.k_max_outages),
                scenario_ids=instance.sets.loaded_disaster_scenarios,
                safety_factor=float(safety_factor),
            )
            _, solution = solve_separation_milp(
                instance,
                plan=plan,
                alpha=0.0,
                lambda_by_line_id=None,
                omega_bounds_by_line_id=bounds,
                budget_k=int(instance.ambiguity.k_max_outages),
                scenario_ids=instance.sets.loaded_disaster_scenarios,
                model_name=f"omega_sensitivity_{run_id}_{safety_factor:g}",
            )
            rows.append(
                {
                    "run_id": run_id,
                    "safety_factor": safety_factor,
                    "Phi_dis": float(solution.objective_value or 0.0),
                    "active_outage_lines": ";".join(
                        line_id
                        for line_id, value in solution.delta_by_line_id.items()
                        if int(value) == 1
                    ),
                    "reconstruction_gap": float(solution.reconstruction_gap),
                }
            )
    _write_rows(root / args.output_csv, rows)

    md = ["# Omega-Bound Sensitivity Audit", ""]
    fail = False
    for run_id in sorted({str(row["run_id"]) for row in rows}):
        vals = [float(row["Phi_dis"]) for row in rows if row["run_id"] == run_id]
        min_val = min(vals)
        max_val = max(vals)
        rel_span = 0.0 if abs(max_val) <= 1e-12 else (max_val - min_val) / max_val
        passed = rel_span <= float(args.relative_tolerance)
        fail = fail or not passed
        md.append(
            f"- `{run_id}`: min Phi={min_val:.6g}, max Phi={max_val:.6g}, "
            f"relative span={rel_span:.2%}, stability={'PASS' if passed else 'FAIL'}."
        )
    md.extend(
        [
            "",
            f"Overall result: **{'FAIL' if fail else 'PASS'}**",
            "",
            "If this audit fails, Benders certificates are bound-dependent and cannot support paper-main claims.",
        ]
    )
    (root / args.output_md).write_text("\n".join(md) + "\n", encoding="utf-8")
    print(root / args.output_csv)
    print(root / args.output_md)
    if fail:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
