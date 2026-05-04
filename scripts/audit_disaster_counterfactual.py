"""Evaluate disaster-stage counterfactual plans for a selected outage pattern."""

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
from src.reference.disaster_primal_ref import (  # noqa: E402
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
    solve_disaster_primal_reference,
)


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


def _load_plan_maps(path: Path) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    rows = _read_rows(path)
    return (
        {int(row["bus"]): int(float(row["is_open"])) for row in rows},
        {int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        {int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _apply_variant(
    z_by_bus: dict[int, int],
    n_sl_by_bus: dict[int, int],
    n_fa_by_bus: dict[int, int],
    *,
    buses: list[int],
    slow: int,
    fast: int,
) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    z = dict(z_by_bus)
    n_sl = dict(n_sl_by_bus)
    n_fa = dict(n_fa_by_bus)
    for bus in buses:
        z[bus] = 1
        n_sl[bus] = max(int(n_sl.get(bus, 0)), int(slow))
        n_fa[bus] = max(int(n_fa.get(bus, 0)), int(fast))
    return z, n_sl, n_fa


def _evaluate(instance, outage, *, label: str, z_by_bus, n_sl_by_bus, n_fa_by_bus) -> dict[str, Any]:
    plan = build_fixed_first_stage_plan(
        instance,
        z_by_bus=z_by_bus,
        n_sl_by_bus=n_sl_by_bus,
        n_fa_by_bus=n_fa_by_bus,
    )
    objectives: list[float] = []
    shedding: list[float] = []
    discharge: list[float] = []
    for scenario_id in instance.sets.loaded_disaster_scenarios:
        _, solution = solve_disaster_primal_reference(
            instance,
            plan=plan,
            outage=outage,
            scenario_id=int(scenario_id),
            model_name=f"counterfactual_{label}_b{scenario_id}",
        )
        objectives.append(float(solution.objective_value or 0.0))
        shedding.append(float(sum(solution.load_shedding_by_time_bus.values())))
        discharge.append(
            float(sum(solution.discharge_slow_by_time_region_bus.values()))
            + float(sum(solution.discharge_fast_by_time_region_bus.values()))
        )
    return {
        "case": label,
        "avg_phi_primal": sum(objectives) / len(objectives),
        "min_phi_primal": min(objectives),
        "max_phi_primal": max(objectives),
        "avg_load_shed": sum(shedding) / len(shedding),
        "avg_ev_discharge": sum(discharge) / len(discharge),
        "sites": sum(z_by_bus.values()),
        "slow_chargers": sum(n_sl_by_bus.values()),
        "fast_chargers": sum(n_fa_by_bus.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--config-run-id", required=True)
    parser.add_argument("--base-run-id", required=True)
    parser.add_argument("--active-lines", required=True)
    parser.add_argument("--output-csv", default="disaster_counterfactual.csv")
    parser.add_argument("--output-md", default="disaster_counterfactual.md")
    args = parser.parse_args()

    root = Path(args.root)
    config = json.loads((root / "logs" / f"{args.config_run_id}_run.json").read_text())[
        "run_config"
    ]
    instance = prepare_instance_for_run(
        load_instance_for_run(config, critical_buses=load_critical_buses(CRITICAL_BUS_CONFIG)),
        config,
    )
    outage = build_fixed_outage_vector(
        instance,
        by_line_id={line_id.strip(): 1 for line_id in args.active_lines.split(",") if line_id.strip()},
    )
    z, n_sl, n_fa = _load_plan_maps(root / "plans" / f"{args.base_run_id}_plan.csv")
    variants = [
        ("base", z, n_sl, n_fa),
        ("critical_11_14_17_5fast", *_apply_variant(z, n_sl, n_fa, buses=[11, 14, 17], slow=0, fast=5)),
        ("critical_11_14_17_25slow", *_apply_variant(z, n_sl, n_fa, buses=[11, 14, 17], slow=25, fast=0)),
        ("critical_11_14_17_max", *_apply_variant(z, n_sl, n_fa, buses=[11, 14, 17], slow=25, fast=10)),
        ("subtree_10_17_max", *_apply_variant(z, n_sl, n_fa, buses=list(range(10, 18)), slow=25, fast=10)),
    ]
    rows = [
        _evaluate(instance, outage, label=label, z_by_bus=vz, n_sl_by_bus=vsl, n_fa_by_bus=vfa)
        for label, vz, vsl, vfa in variants
    ]
    _write_rows(root / args.output_csv, rows)

    lines = ["# Disaster Counterfactual Audit", ""]
    for row in rows:
        lines.append(
            f"- `{row['case']}`: Phi={float(row['avg_phi_primal']):.6g}, "
            f"avg load shed={float(row['avg_load_shed']):.6g}, "
            f"avg EV discharge={float(row['avg_ev_discharge']):.6g}."
        )
    lines.extend(
        [
            "",
            "This audit distinguishes model physics from separation failure: if a counterfactual "
            "plan improves Phi while the optimized plan does not, the planning model is connected "
            "to the disaster objective but the separation/master algorithm failed to find the tradeoff.",
        ]
    )
    (root / args.output_md).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(root / args.output_csv)
    print(root / args.output_md)


if __name__ == "__main__":
    main()
