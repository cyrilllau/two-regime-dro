"""Promote MILP-separation EV sensitivity runs into paper-facing artifacts."""

from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_ev_sensitivity_artifacts import (  # noqa: E402
    _plot_component_bars,
    _plot_trends,
    _topology,
)
from scripts.build_paper_final_analysis import (  # noqa: E402
    CRITICAL_BUS_CONFIG,
    _evaluate_fixed_plan_components,
)
from scripts.experiment_pack_utils import (  # noqa: E402
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from scripts.make_experiment_figures import write_plan_map_figure  # noqa: E402
from scripts.promote_milp_default_case import _fixed_plan_milp_dro_value  # noqa: E402
from scripts.run_separation_scalability import ACCEPTED_CONFIG, _read_json  # noqa: E402
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan  # noqa: E402


PAPER_ROOT = REPO_ROOT / "results" / "paper_final"
RUN_ROOT = PAPER_ROOT / "ev_sensitivity_milp_runs" / "milp"
PACK_ROOT = PAPER_ROOT / "ev_sensitivity_iteration"
FIGURES_DIR = PAPER_ROOT / "figures"

CASES = [
    {
        "case_id": "Base",
        "case_name": "Base EV demand",
        "ev_multiplier": 1.0,
        "ev_scale": 0.55,
        "promoted_id": "ev_sensitivity_base",
        "plan_source": PAPER_ROOT / "plans" / "default_scale_v2_proposed_plan.csv",
        "run_json": PAPER_ROOT
        / "full_benders_scaling_runs"
        / "milp"
        / "logs"
        / "full_benders_A10_B010_K02_top020_run.json",
        "source_run_id": "full_benders_A10_B010_K02_top020",
    },
    {
        "case_id": "EV 1.5x",
        "case_name": "EV penetration 1.5x",
        "ev_multiplier": 1.5,
        "ev_scale": 0.825,
        "promoted_id": "ev_sensitivity_1p5",
        "plan_source": RUN_ROOT
        / "plans"
        / "ev_sensitivity_ev1p5_milp_A10_B010_K02_top020_plan.csv",
        "run_json": RUN_ROOT
        / "logs"
        / "ev_sensitivity_ev1p5_milp_A10_B010_K02_top020_run.json",
        "source_run_id": "ev_sensitivity_ev1p5_milp_A10_B010_K02_top020",
    },
    {
        "case_id": "EV 2.0x",
        "case_name": "EV penetration 2.0x",
        "ev_multiplier": 2.0,
        "ev_scale": 1.10,
        "promoted_id": "ev_sensitivity_2p0",
        "plan_source": RUN_ROOT
        / "plans"
        / "ev_sensitivity_ev2p0_milp_A10_B010_K02_top020_plan.csv",
        "run_json": RUN_ROOT
        / "logs"
        / "ev_sensitivity_ev2p0_milp_A10_B010_K02_top020_run.json",
        "source_run_id": "ev_sensitivity_ev2p0_milp_A10_B010_K02_top020",
    },
]


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
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


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _float(row: Mapping[str, Any], key: str) -> float:
    raw = row.get(key, "")
    return 0.0 if raw in ("", None) else float(raw)


def _load_plan(instance, path: Path):
    rows = _read_rows(path)
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _instance_for_scale(ev_scale: float):
    config = _read_json(ACCEPTED_CONFIG)
    config["ev_penetration_scale"] = float(ev_scale)
    config["mode"] = "integrated_mainline"
    config["solver"] = "benders"
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    return prepare_instance_for_run(
        load_instance_for_run(config, critical_buses=critical_buses),
        config,
    )


def _copy_plan(case: Mapping[str, Any]) -> Path:
    source = Path(case["plan_source"])
    destination = PAPER_ROOT / "plans" / f"{case['promoted_id']}_plan.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def _training_fields(case: Mapping[str, Any]) -> dict[str, Any]:
    payload = json.loads(Path(case["run_json"]).read_text(encoding="utf-8"))
    summary = dict(payload["summary"])
    config = dict(payload["run_config"])
    runtime_summary = _runtime_fields(str(case["source_run_id"]))
    return {
        "source_run_id": case["source_run_id"],
        "training_algorithm": "milp_fixed_dual_benders",
        "training_validation_level": payload.get("validation_level", summary.get("validation_level", "")),
        "training_stop_reason": payload.get("stop_reason", summary.get("stop_reason", "")),
        "training_iterations": summary.get("iteration_count", ""),
        "training_cuts": summary.get("cut_count", ""),
        "training_final_violation": summary.get("final_violation_upper_bound", ""),
        "training_max_iterations_budget": config.get("benders", {}).get("max_iterations", ""),
        "training_top_cuts": config.get("benders", {}).get("separation_top_cuts_per_iteration", ""),
        **runtime_summary,
    }


def _runtime_fields(run_id: str) -> dict[str, Any]:
    for path in (
        PAPER_ROOT / "ev_sensitivity_milp_training_summary.csv",
        PAPER_ROOT / "cut_batch_ablation.csv",
        PAPER_ROOT / "full_benders_scaling_summary.csv",
    ):
        if not path.exists():
            continue
        for row in _read_rows(path):
            if row.get("run_id") != run_id:
                continue
            return {
                "training_runtime_seconds": row.get("runtime_seconds", ""),
                "training_master_seconds": row.get("master_seconds", ""),
                "training_separation_seconds": row.get("separation_seconds", ""),
                "training_cut_generation_seconds": row.get("cut_generation_seconds", ""),
                "training_separation_time_share": row.get("separation_time_share", ""),
            }
    return {
        "training_runtime_seconds": "",
        "training_master_seconds": "",
        "training_separation_seconds": "",
        "training_cut_generation_seconds": "",
        "training_separation_time_share": "",
    }


def _plan_metrics(plan_path: Path) -> dict[str, Any]:
    rows = _read_rows(plan_path)
    return {
        "sites": sum(int(float(row["is_open"])) for row in rows),
        "slow_chargers": sum(int(float(row["n_sl"])) for row in rows),
        "fast_chargers": sum(int(float(row["n_fa"])) for row in rows),
        "total_chargers": sum(
            int(float(row["n_sl"])) + int(float(row["n_fa"])) for row in rows
        ),
    }


def _component_row(case: Mapping[str, Any]) -> dict[str, Any]:
    plan_path = _copy_plan(case)
    instance = _instance_for_scale(float(case["ev_scale"]))
    plan = _load_plan(instance, plan_path)
    components = _evaluate_fixed_plan_components(
        instance,
        plan,
        run_id=f"milp_ev_sensitivity_{case['case_id'].replace(' ', '_').lower()}",
        k=2,
        disaster_evaluator="milp",
    )
    dro = _fixed_plan_milp_dro_value(
        instance,
        plan,
        run_id=f"milp_ev_sensitivity_{case['case_id'].replace(' ', '_').lower()}",
    )
    components["Phi_dis"] = dro["Phi_dis"]
    components["J_common"] = (
        components["F_cons"]
        + (1.0 - float(components["pi_f"])) * components["Psi_nor"]
        + float(components["pi_f"]) * components["Phi_dis"]
    )
    topo = _topology(str(plan_path))
    metrics = _plan_metrics(plan_path)
    row = {
        "case_id": case["case_id"],
        "case_name": case["case_name"],
        "ev_multiplier": case["ev_multiplier"],
        "ev_scale": case["ev_scale"],
        "promoted_run_id": case["promoted_id"],
        **_training_fields(case),
        "normal_scenario_count": components["normal_scenario_count"],
        "disaster_scenario_count": components["disaster_scenario_count"],
        "K": components["K"],
        "disaster_evaluator": "milp_fixed_plan_dro",
        "F_cons": components["F_cons"],
        "F_trans": components["F_trans"],
        "F_unmet": components["F_unmet"],
        "F_sub": components["F_sub"],
        "Psi_nor": components["Psi_nor"],
        "Phi_dis": components["Phi_dis"],
        "pi_f": components["pi_f"],
        "J_common": components["J_common"],
        **metrics,
        "F_unmet_over_Psi": components["F_unmet"] / max(components["Psi_nor"], 1e-9),
        "Phi_over_Psi": components["Phi_dis"] / max(components["Psi_nor"], 1e-9),
        "open_buses": topo["open_buses"],
        "critical_direct_count": topo["critical_direct_count"],
        "critical_direct_pct": topo["critical_direct_pct"],
        "critical_one_hop_count": topo["critical_one_hop_count"],
        "critical_one_hop_pct": topo["critical_one_hop_pct"],
        "fast_on_critical": topo["fast_on_critical"],
        "slow_on_critical": topo["slow_on_critical"],
        "fixed_plan_dro_iterations": dro["iterations"],
        "fixed_plan_dro_cuts": dro["cuts"],
        "fixed_plan_dro_final_violation": dro["final_violation"],
        "fixed_plan_dro_final_violation_bound": dro["final_violation_bound"],
        "fixed_plan_dro_alpha": dro["alpha"],
        "fixed_plan_dro_lambda_times_FP": dro["lambda_times_FP"],
        "fixed_plan_active_outage_trace": dro["active_outage_trace"],
        "plan_path": str(plan_path),
        "source_plan_path": str(case["plan_source"]),
    }
    return row


def _quality(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sites = [int(float(row["sites"])) for row in rows]
    chargers = [int(float(row["total_chargers"])) for row in rows]
    unmet = [float(row["F_unmet_over_Psi"]) for row in rows]
    phi = [float(row["Phi_dis"]) for row in rows]
    identities = []
    for row in rows:
        psi_gap = abs(
            _float(row, "Psi_nor")
            - _float(row, "F_trans")
            - _float(row, "F_unmet")
            - _float(row, "F_sub")
        )
        j_gap = abs(
            _float(row, "J_common")
            - _float(row, "F_cons")
            - (1.0 - _float(row, "pi_f")) * _float(row, "Psi_nor")
            - _float(row, "pi_f") * _float(row, "Phi_dis")
        )
        identities.append(psi_gap <= 1e-5 and j_gap <= 1e-5)
    issues = []
    if sites != sorted(sites):
        issues.append("Open site count is not monotone with EV multiplier.")
    if chargers != sorted(chargers):
        issues.append("Total EVSE count is not monotone with EV multiplier.")
    if max(unmet) > 0.05:
        issues.append("F_unmet/Psi exceeds 5%.")
    if not all(identities):
        issues.append("Component identity check failed.")
    if not all(str(row["training_validation_level"]) == "epsilon_certified" for row in rows):
        issues.append("At least one EV sensitivity run is not epsilon certified.")
    return {
        "target": "milp_ev_sensitivity",
        "verdict": "PASS_TARGET" if not issues else "NEED_REVIEW",
        "blocking_or_major_issues": issues,
        "site_counts": sites,
        "charger_counts": chargers,
        "phi_values": phi,
        "max_unmet_share": max(unmet),
        "component_identities_pass": all(identities),
        "common_evaluator": "milp_fixed_plan_dro",
    }


def _write_reports(rows: Sequence[Mapping[str, Any]], quality: Mapping[str, Any]) -> None:
    base, ev15, ev20 = rows
    text = (
        "# MILP EV Sensitivity Review\n\n"
        f"Verdict: `{quality['verdict']}`\n\n"
        f"- Open sites: `{quality['site_counts']}`.\n"
        f"- Total EVSE: `{quality['charger_counts']}`.\n"
        f"- Phi values: `{[round(v, 2) for v in quality['phi_values']]}`.\n"
        f"- Max unmet share: `{100.0 * quality['max_unmet_share']:.2f}%`.\n\n"
        "The MILP fixed-plan DRO evaluator is used for every row, so Table IV is now "
        "consistent with the promoted default case.\n"
    )
    _write_text(PACK_ROOT / "critic_synthesis.md", text)
    _write_text(PAPER_ROOT / "ev_sensitivity_critic_review.md", text)
    review = {
        "target": "milp_ev_sensitivity",
        "verdict": quality["verdict"],
        "quality": dict(quality),
        "artifacts": {
            "table_iv": str(PAPER_ROOT / "sensitivity_components_tableIV.csv"),
            "figure_maps": str(FIGURES_DIR / "fig8_like_sensitivity_maps.png"),
            "figure_components": str(FIGURES_DIR / "tableIV_like_sensitivity.png"),
            "figure_trends": str(FIGURES_DIR / "ev_sensitivity_trends.png"),
        },
        "next_objective": "rerun_large_scale_full_benders_or_update_scalability_claim",
    }
    _write_json(PAPER_ROOT / "ev_sensitivity_critic_review.json", review)
    _write_json(PACK_ROOT / "critic_review.json", review)


def main() -> None:
    rows = [_component_row(case) for case in CASES]
    _write_rows(PAPER_ROOT / "sensitivity_components_tableIV.csv", rows)
    _write_rows(PACK_ROOT / "tables" / "sensitivity_components_tableIV.csv", rows)
    write_plan_map_figure(
        run_ids=("ev_sensitivity_base", "ev_sensitivity_1p5", "ev_sensitivity_2p0"),
        plans_dir=PAPER_ROOT / "plans",
        title="EV penetration sensitivity under MILP fixed-dual regime",
        path=FIGURES_DIR / "fig8_like_sensitivity_maps.png",
        ncols=1,
    )
    _plot_component_bars(rows)
    _plot_trends(rows)
    quality = _quality(rows)
    _write_json(PAPER_ROOT / "ev_sensitivity_quality_gates.json", quality)
    _write_json(PACK_ROOT / "ev_sensitivity_quality_gates.json", quality)
    _write_reports(rows, quality)
    print(json.dumps(quality, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
