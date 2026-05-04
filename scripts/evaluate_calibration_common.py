"""Replay calibrated first-stage plans under one common paper evaluator."""

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
from scripts.build_paper_final_analysis import (  # noqa: E402
    CRITICAL_BUS_CONFIG,
    _evaluate_fixed_plan_components,
)
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan  # noqa: E402


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


def _case_key(run_id: str) -> str:
    for suffix in (
        "deterministic_disaster_mean",
        "integrated",
        "normal",
        "deterministic",
        "disaster",
    ):
        if run_id.endswith(f"_{suffix}"):
            return suffix
    return run_id.rsplit("_", maxsplit=1)[-1]


def _load_plan(plan_path: Path, instance) -> Any:
    rows = _read_rows(plan_path)
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _load_common_config(root: Path, preferred_run_id: str | None) -> dict[str, Any]:
    summary_rows = _read_rows(root / "summary.csv")
    candidates = []
    if preferred_run_id:
        candidates.append(preferred_run_id)
    candidates.extend(row["run_id"] for row in summary_rows if row["run_id"].endswith("_integrated"))
    candidates.extend(row["run_id"] for row in summary_rows)
    for run_id in candidates:
        path = root / "logs" / f"{run_id}_run.json"
        if not path.exists():
            path = root / "logs" / f"{run_id}_config.json"
        if path.exists():
            config = json.loads(path.read_text(encoding="utf-8"))["run_config"]
            config = dict(config)
            config["mode"] = "integrated_mainline"
            config["solver"] = "benders"
            return config
    raise FileNotFoundError(f"No run log found under {root / 'logs'}")


def _load_config_from_log(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    config = dict(payload["run_config"] if "run_config" in payload else payload)
    config["mode"] = "integrated_mainline"
    config["solver"] = "benders"
    return config


def _load_run_config(root: Path, run_id: str) -> dict[str, Any]:
    path = root / "logs" / f"{run_id}_run.json"
    if not path.exists():
        path = root / "logs" / f"{run_id}_config.json"
    config = json.loads(path.read_text(encoding="utf-8"))["run_config"]
    config = dict(config)
    config["mode"] = "integrated_mainline"
    config["solver"] = "benders"
    return config


def _common_config_by_regime(root: Path, summary_rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    integrated_by_regime = {
        row["parameter_regime"]: row["run_id"]
        for row in summary_rows
        if row["run_id"].endswith("_integrated")
    }
    configs: dict[str, dict[str, Any]] = {}
    for row in summary_rows:
        regime = row.get("parameter_regime", "")
        run_id = integrated_by_regime.get(regime, row["run_id"])
        if regime not in configs:
            configs[regime] = _load_run_config(root, run_id)
    return configs


def _safe_ratio(numerator: float, denominator: float) -> float:
    if abs(denominator) <= 1e-12:
        return float("inf") if numerator > 0 else 0.0
    return float(numerator / denominator)


def _build_gates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []
    regimes = sorted({str(row.get("parameter_regime", "")) for row in rows})
    for regime in regimes:
        group_rows = [row for row in rows if str(row.get("parameter_regime", "")) == regime]
        by_case = {str(row["case_key"]): row for row in group_rows}
        proposed = by_case.get("integrated")
        normal = by_case.get("normal")
        deterministic = by_case.get("deterministic")
        if proposed is None:
            continue
        gates.append(
            {
                "parameter_regime": regime,
                "gate": "material_phi_prop",
                "value": _safe_ratio(float(proposed["Phi_dis"]), float(proposed["Psi_nor"])) * 100.0,
                "threshold": 1.0,
                "pass": _safe_ratio(float(proposed["Phi_dis"]), float(proposed["Psi_nor"])) * 100.0
                >= 1.0,
            }
        )
        if deterministic is not None:
            det_reduction = _safe_ratio(
                float(deterministic["Phi_dis"]) - float(proposed["Phi_dis"]),
                float(deterministic["Phi_dis"]),
            ) * 100.0
            gates.append(
                {
                    "parameter_regime": regime,
                    "gate": "deterministic_phi_reduction_pct",
                    "value": det_reduction,
                    "threshold": 20.0,
                    "pass": det_reduction >= 20.0,
                }
            )
        if normal is not None:
            pi_f = float(proposed["pi_f"])
            delta_daily = (
                float(proposed["F_cons"])
                + (1.0 - pi_f) * float(proposed["Psi_nor"])
                - float(normal["F_cons"])
                - (1.0 - pi_f) * float(normal["Psi_nor"])
            )
            delta_resilience = pi_f * (float(normal["Phi_dis"]) - float(proposed["Phi_dis"]))
            gates.extend(
                [
                    {
                        "parameter_regime": regime,
                        "gate": "delta_daily_prop_minus_normal",
                        "value": delta_daily,
                        "threshold": ">0",
                        "pass": delta_daily > 0.0,
                    },
                    {
                        "parameter_regime": regime,
                        "gate": "delta_resilience_prop_vs_normal",
                        "value": delta_resilience,
                        "threshold": ">0",
                        "pass": delta_resilience > 0.0,
                    },
                    {
                        "parameter_regime": regime,
                        "gate": "delta_resilience_over_delta_daily",
                        "value": _safe_ratio(delta_resilience, delta_daily),
                        "threshold": 1.5,
                        "pass": delta_daily > 0.0
                        and _safe_ratio(delta_resilience, delta_daily) >= 1.5,
                    },
                ]
            )
    return gates


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--preferred-run-id", default=None)
    parser.add_argument("--common-config-log", default=None)
    parser.add_argument("--common-k-override", type=int, default=None)
    parser.add_argument(
        "--run-ids",
        default=None,
        help="Optional comma-separated subset of run ids to evaluate.",
    )
    parser.add_argument(
        "--disaster-evaluator",
        choices=("milp", "enumeration", "exact_primal_dro"),
        default="milp",
        help="Use the bounded separation MILP or exact outage enumeration for Phi.",
    )
    parser.add_argument("--output-name", default="common_evaluation.csv")
    parser.add_argument("--gates-name", default="common_evaluation_gates.csv")
    parser.add_argument("--per-scenario-name", default="common_evaluation_normal_scenarios.csv")
    args = parser.parse_args()

    root = Path(args.input_root)
    summary_rows = _read_rows(root / "summary.csv")
    requested_run_ids = None
    if args.run_ids:
        requested_run_ids = {token.strip() for token in args.run_ids.split(",") if token.strip()}
        summary_rows = [row for row in summary_rows if row["run_id"] in requested_run_ids]
        missing = sorted(requested_run_ids - {row["run_id"] for row in summary_rows})
        if missing:
            raise FileNotFoundError(f"Requested run ids are missing from summary.csv: {missing}")
    fallback_common_config = (
        _load_config_from_log(Path(args.common_config_log))
        if args.common_config_log
        else _load_common_config(root, args.preferred_run_id)
    )
    configs_by_regime = (
        {
            str(row.get("parameter_regime", "")): dict(fallback_common_config)
            for row in summary_rows
        }
        if args.common_config_log
        else _common_config_by_regime(root, summary_rows)
    )
    if args.common_k_override is not None:
        for config in [fallback_common_config, *configs_by_regime.values()]:
            overrides = dict(config.get("parameter_overrides", {}))
            ambiguity = dict(overrides.get("ambiguity", {}))
            ambiguity["k_max_outages"] = int(args.common_k_override)
            overrides["ambiguity"] = ambiguity
            config["parameter_overrides"] = overrides
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    instance_cache = {}
    rows: list[dict[str, Any]] = []
    per_scenario_rows: list[dict[str, Any]] = []
    for summary in summary_rows:
        run_id = summary["run_id"]
        regime = summary.get("parameter_regime", "")
        common_config = configs_by_regime.get(regime, fallback_common_config)
        if regime not in instance_cache:
            instance_cache[regime] = prepare_instance_for_run(
                load_instance_for_run(common_config, critical_buses=critical_buses),
                common_config,
            )
        instance = instance_cache[regime]
        plan_path = root / "plans" / f"{run_id}_plan.csv"
        if not plan_path.exists():
            plan_path = root / "plans" / f"{run_id}_final_plan.csv"
        if not plan_path.exists():
            continue
        plan = _load_plan(plan_path, instance)
        components = _evaluate_fixed_plan_components(
            instance,
            plan,
            run_id=f"common_eval_{run_id}",
            k=int(common_config.get("parameter_overrides", {}).get("ambiguity", {}).get("k_max_outages", 2)),
            disaster_evaluator=args.disaster_evaluator,
        )
        for scenario_id in sorted(components["normal_by_scenario"]):
            per_scenario_rows.append(
                {
                    "run_id": run_id,
                    "case_key": _case_key(run_id),
                    "parameter_regime": regime,
                    "scenario_id": scenario_id,
                    "F_trans": components["transport_by_scenario"][scenario_id],
                    "F_unmet": components["unmet_by_scenario"][scenario_id],
                    "F_sub": components["substation_by_scenario"][scenario_id],
                    "Psi_nor": components["normal_by_scenario"][scenario_id],
                }
            )
        rows.append(
            {
                "run_id": run_id,
                "case_key": _case_key(run_id),
                "parameter_regime": regime,
                "training_validation_level": summary.get("validation_level", ""),
                "training_stop_reason": summary.get("stop_reason", ""),
                "training_iterations": summary.get("iteration_count", ""),
                "training_cut_count": summary.get("cut_count", ""),
                "training_final_violation": summary.get("final_violation_upper_bound", ""),
                **{
                    key: components[key]
                    for key in (
                        "F_cons",
                        "F_trans",
                        "F_unmet",
                        "F_sub",
                        "Psi_nor",
                        "Phi_dis",
                        "pi_f",
                        "J_common",
                        "active_outage_lines",
                        "separation_status",
                        "separation_reconstruction_gap",
                        "normal_scenario_count",
                        "disaster_scenario_count",
                        "K",
                        "disaster_evaluator",
                        "evaluated_outage_patterns",
                    )
                },
                "sites": sum(plan.z_by_bus.values()),
                "slow_chargers": sum(plan.n_sl_by_bus.values()),
                "fast_chargers": sum(plan.n_fa_by_bus.values()),
            }
        )
    _write_rows(root / args.output_name, rows)
    _write_rows(root / args.gates_name, _build_gates(rows))
    _write_rows(root / args.per_scenario_name, per_scenario_rows)
    print(f"wrote {root / args.output_name}")
    print(f"wrote {root / args.gates_name}")


if __name__ == "__main__":
    main()
