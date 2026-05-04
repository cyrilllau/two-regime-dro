"""Promote the MILP-separation default case into paper-facing artifacts.

This is deliberately narrow.  It replaces the old exact-enumeration proposed
plan with the fixed-dual MILP-separation Benders plan, then replays all default
plans under the same MILP worst-distribution evaluator.
"""

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
from src.production.cut_factory import generate_cut_from_separation_solution  # noqa: E402
from src.production.master_problem import (  # noqa: E402
    RestrictedMasterCut,
    build_master_problem,
    extract_master_problem_solution,
)
from src.production.separation_milp import solve_separation_milp  # noqa: E402
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan  # noqa: E402


PAPER_ROOT = REPO_ROOT / "results" / "paper_final"
MILP_RUN_ID = "full_benders_A10_B010_K02_top020"
MILP_RUN_ROOT = PAPER_ROOT / "full_benders_scaling_runs" / "milp"
MILP_RUN_JSON = MILP_RUN_ROOT / "logs" / f"{MILP_RUN_ID}_run.json"
MILP_ITERATION_JSON = MILP_RUN_ROOT / "logs" / f"{MILP_RUN_ID}_iteration_log.json"
MILP_PLAN = MILP_RUN_ROOT / "plans" / f"{MILP_RUN_ID}_plan.csv"
DET_K2_MILP_RUN_ID = "milp_default_deterministic_k2_top020"
DET_K2_MILP_ROOT = PAPER_ROOT / "milp_default_benchmark_runs"
DET_K2_MILP_RUN_JSON = DET_K2_MILP_ROOT / "logs" / f"{DET_K2_MILP_RUN_ID}_run.json"
DET_K2_MILP_ITERATION_JSON = (
    DET_K2_MILP_ROOT / "logs" / f"{DET_K2_MILP_RUN_ID}_iteration_log.json"
)
DET_K2_MILP_PLAN = DET_K2_MILP_ROOT / "plans" / f"{DET_K2_MILP_RUN_ID}_plan.csv"

CASE_SPECS = [
    ("Case 1", "Proposed integrated", "proposed", "default_scale_v2_proposed"),
    ("Case 2", "Normal-only", "normal", "default_scale_v2_normal"),
    ("Case 3", "Disaster-only", "disaster", "default_scale_v2_disaster"),
    (
        "Case 4",
        "Deterministic mean-value, K_train=2",
        "deterministic_k2",
        "default_scale_v2_deterministic_k2",
    ),
    (
        "Diagnostic",
        "Naive deterministic mean-value, K_train=0",
        "deterministic",
        "default_scale_v2_deterministic",
    ),
]

IEEE33_EDGES = [
    (1, 2), (2, 3), (2, 19), (3, 4), (3, 23), (4, 5), (5, 6), (6, 7),
    (6, 26), (7, 8), (8, 9), (9, 10), (10, 11), (11, 12), (12, 13),
    (13, 14), (14, 15), (15, 16), (16, 17), (17, 18), (19, 20),
    (20, 21), (21, 22), (23, 24), (24, 25), (26, 27), (27, 28),
    (28, 29), (29, 30), (30, 31), (31, 32), (32, 33),
]
CRITICAL_BUSES = {2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32}


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


def _float(value: Any, default: float = 0.0) -> float:
    if value in ("", None):
        return default
    return float(value)


def _load_plan(instance, plan_path: Path):
    rows = _read_rows(plan_path)
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _summary_for(run_id: str) -> dict[str, str]:
    path = PAPER_ROOT / "logs" / f"{run_id}_summary.csv"
    if not path.exists():
        return {}
    rows = _read_rows(path)
    return rows[0] if rows else {}


def _copy_milp_artifacts() -> dict[str, Any]:
    if not MILP_RUN_JSON.exists() or not MILP_PLAN.exists():
        raise FileNotFoundError(
            f"Missing MILP default run artifacts under {MILP_RUN_ROOT}."
        )
    target_plan = PAPER_ROOT / "plans" / "default_scale_v2_proposed_plan.csv"
    exact_reference = (
        PAPER_ROOT / "plans" / "default_scale_v2_proposed_exact_reference_plan.csv"
    )
    if target_plan.exists() and not exact_reference.exists():
        shutil.copy2(target_plan, exact_reference)
    shutil.copy2(MILP_PLAN, target_plan)
    shutil.copy2(MILP_RUN_JSON, PAPER_ROOT / "logs" / "default_scale_v2_proposed_milp_run.json")
    if MILP_ITERATION_JSON.exists():
        shutil.copy2(
            MILP_ITERATION_JSON,
            PAPER_ROOT / "logs" / "default_scale_v2_proposed_milp_iteration_log.json",
        )
    payloads = {"proposed": json.loads(MILP_RUN_JSON.read_text(encoding="utf-8"))}

    if DET_K2_MILP_RUN_JSON.exists() and DET_K2_MILP_PLAN.exists():
        det_target_plan = PAPER_ROOT / "plans" / "default_scale_v2_deterministic_k2_plan.csv"
        det_exact_reference = (
            PAPER_ROOT
            / "plans"
            / "default_scale_v2_deterministic_k2_exact_reference_plan.csv"
        )
        if det_target_plan.exists() and not det_exact_reference.exists():
            shutil.copy2(det_target_plan, det_exact_reference)
        shutil.copy2(DET_K2_MILP_PLAN, det_target_plan)
        shutil.copy2(
            DET_K2_MILP_RUN_JSON,
            PAPER_ROOT / "logs" / "default_scale_v2_deterministic_k2_milp_run.json",
        )
        if DET_K2_MILP_ITERATION_JSON.exists():
            shutil.copy2(
                DET_K2_MILP_ITERATION_JSON,
                PAPER_ROOT / "logs" / "default_scale_v2_deterministic_k2_milp_iteration_log.json",
            )
        payloads["deterministic_k2"] = json.loads(
            DET_K2_MILP_RUN_JSON.read_text(encoding="utf-8")
        )
    return payloads


def _training_fields(
    case_key: str,
    promoted_id: str,
    milp_payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if case_key in {"proposed", "deterministic_k2"} and case_key in milp_payloads:
        payload = milp_payloads[case_key]
        summary = dict(payload["summary"])
        config = dict(payload["run_config"])
        return {
            "training_algorithm": "milp_fixed_dual_benders",
            "training_validation_level": payload.get("validation_level", summary.get("validation_level", "")),
            "training_stop_reason": payload.get("stop_reason", summary.get("stop_reason", "")),
            "training_iterations": summary.get("iteration_count", ""),
            "training_cuts": summary.get("cut_count", ""),
            "training_final_violation": summary.get("final_violation_upper_bound", ""),
            "training_max_iterations_budget": config.get("benders", {}).get("max_iterations", ""),
            "training_top_cuts": config.get("benders", {}).get("separation_top_cuts_per_iteration", ""),
            "training_runtime_seconds": "",
            "source_run_id": MILP_RUN_ID if case_key == "proposed" else DET_K2_MILP_RUN_ID,
        }
    summary = _summary_for(promoted_id)
    return {
        "training_algorithm": summary.get("family_name", "promoted_existing"),
        "training_validation_level": summary.get("validation_level", ""),
        "training_stop_reason": summary.get("stop_reason", ""),
        "training_iterations": summary.get("iterations", summary.get("iteration_count", "")),
        "training_cuts": summary.get("cuts", summary.get("cut_count", "")),
        "training_final_violation": summary.get("final_violation", summary.get("final_violation_upper_bound", "")),
        "training_max_iterations_budget": summary.get("max_iterations_budget", ""),
        "training_top_cuts": summary.get("top_cuts", ""),
        "training_runtime_seconds": summary.get("runtime_seconds", ""),
        "source_run_id": summary.get("run_id", promoted_id),
    }


def _plan_metrics(plan_path: Path) -> dict[str, Any]:
    rows = _read_rows(plan_path)
    open_rows = [row for row in rows if int(float(row["is_open"])) == 1]
    critical_total = sum(1 for row in rows if int(float(row["is_critical"])) == 1)
    direct_critical = sum(
        1
        for row in open_rows
        if int(float(row.get("is_critical", 0))) == 1
    )
    return {
        "sites": len(open_rows),
        "slow_chargers": sum(int(float(row["n_sl"])) for row in rows),
        "fast_chargers": sum(int(float(row["n_fa"])) for row in rows),
        "critical_bus_coverage": f"{direct_critical}/{critical_total}",
    }


def _fixed_plan_milp_dro_value(
    instance,
    plan,
    *,
    run_id: str,
    epsilon_cert: float = 100.0,
    max_iterations: int = 100,
    top_cuts: int = 20,
) -> dict[str, Any]:
    cuts: list[RestrictedMasterCut] = []
    omega_bounds = {line_id: (0.0, 2.0e7) for line_id in instance.sets.line_ids}
    last_solution = None
    last_violation = float("inf")
    last_bound = float("inf")
    active_trace: list[str] = []
    cut_counter = 0
    for iteration in range(int(max_iterations)):
        master = build_master_problem(
            instance,
            cuts=cuts,
            model_name=f"{run_id}_fixed_plan_master_{iteration:03d}",
            log_to_console=False,
        )
        for bus in instance.sets.buses:
            master.model.addConstr(master.first_stage.z_by_bus[bus] == plan.z_by_bus[bus])
            master.model.addConstr(master.first_stage.n_sl_by_bus[bus] == plan.n_sl_by_bus[bus])
            master.model.addConstr(master.first_stage.n_fa_by_bus[bus] == plan.n_fa_by_bus[bus])
        master.model.optimize()
        solution = extract_master_problem_solution(master)
        last_solution = solution
        forbidden: list[tuple[str, ...]] = []
        batch = []
        for rank in range(int(top_cuts)):
            _, sep = solve_separation_milp(
                instance,
                plan=plan,
                alpha=solution.alpha_value,
                lambda_by_line_id=solution.lambda_by_line_id,
                omega_bounds_by_line_id=omega_bounds,
                budget_k=2,
                scenario_ids=instance.sets.loaded_disaster_scenarios,
                forbidden_outage_patterns=forbidden,
                model_name=f"{run_id}_fixed_plan_sep_{iteration:03d}_{rank:03d}",
                time_limit_seconds=300.0,
                mip_gap=0.02,
                require_optimal=False,
                log_to_console=False,
            )
            active = tuple(
                line_id for line_id, value in sep.delta_by_line_id.items() if int(value) == 1
            )
            if rank == 0:
                last_violation = float(sep.objective_value or 0.0)
                last_bound = float(sep.obj_bound if sep.obj_bound is not None else last_violation)
                active_trace.append(";".join(active))
            if float(sep.objective_value or 0.0) <= float(epsilon_cert):
                break
            batch.append(sep)
            forbidden.append(active)
        if last_violation <= float(epsilon_cert):
            break
        for sep in batch:
            cut_counter += 1
            generated = generate_cut_from_separation_solution(
                instance,
                plan=plan,
                separation_solution=sep,
                scenario_ids=instance.sets.loaded_disaster_scenarios,
                cut_id=f"{run_id}_fixed_cut_{cut_counter:04d}",
                provenance="fixed_plan_milp_dro_eval",
                lambda_by_line_id=solution.lambda_by_line_id,
                log_to_console=False,
            )
            cuts.append(generated.cut)

    if last_solution is None:
        raise RuntimeError(f"{run_id}: fixed-plan DRO evaluator did not run.")
    pi_f = float(instance.economics.pi_f)
    phi_dis = float(last_solution.disaster_master_cost_value) / pi_f if pi_f else 0.0
    return {
        "Phi_dis": phi_dis,
        "alpha": last_solution.alpha_value,
        "lambda_times_FP": last_solution.lambda_fp_value,
        "final_violation": last_violation,
        "final_violation_bound": last_bound,
        "iterations": iteration + 1,
        "cuts": len(cuts),
        "active_outage_lines": active_trace[-1] if active_trace else "",
        "active_outage_trace": " | ".join(active_trace),
    }


def _adjacency() -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {}
    for left, right in IEEE33_EDGES:
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    return graph


def _topology_rows(table_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    graph = _adjacency()
    rows: list[dict[str, Any]] = []
    normal_plan_path = next(row["plan_path"] for row in table_rows if row["source_case"] == "normal")
    normal_open = {
        int(row["bus"])
        for row in _read_rows(REPO_ROOT / str(normal_plan_path))
        if int(float(row["is_open"])) == 1
    }
    for table_row in table_rows:
        plan_path = REPO_ROOT / str(table_row["plan_path"])
        plan_rows = _read_rows(plan_path)
        open_buses = {
            int(row["bus"]) for row in plan_rows if int(float(row["is_open"])) == 1
        }
        direct = sorted(CRITICAL_BUSES & open_buses)
        neighbor = sorted(
            bus for bus in CRITICAL_BUSES if bus in open_buses or bool(graph[bus] & open_buses)
        )
        rows.append(
            {
                "source_case": table_row["source_case"],
                "case_name": table_row["case_name"],
                "open_buses": ";".join(str(bus) for bus in sorted(open_buses)),
                "swapped_in_vs_normal": ";".join(str(bus) for bus in sorted(open_buses - normal_open)),
                "swapped_out_vs_normal": ";".join(str(bus) for bus in sorted(normal_open - open_buses)),
                "critical_direct_count": len(direct),
                "critical_direct_buses": ";".join(str(bus) for bus in direct),
                "critical_direct_or_neighbor_count": len(neighbor),
                "critical_direct_or_neighbor_buses": ";".join(str(bus) for bus in neighbor),
            }
        )
    return rows


def main() -> None:
    milp_payloads = _copy_milp_artifacts()
    config = dict(milp_payloads["proposed"]["run_config"])
    config["mode"] = "integrated_mainline"
    config["solver"] = "benders"
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    instance = prepare_instance_for_run(
        load_instance_for_run(config, critical_buses=critical_buses),
        config,
    )

    table_rows: list[dict[str, Any]] = []
    for case_id, case_name, case_key, promoted_id in CASE_SPECS:
        plan_path = PAPER_ROOT / "plans" / f"{promoted_id}_plan.csv"
        plan = _load_plan(instance, plan_path)
        components = _evaluate_fixed_plan_components(
            instance,
            plan,
            run_id=f"milp_default_{case_key}",
            k=2,
            disaster_evaluator="milp",
        )
        dro_eval = _fixed_plan_milp_dro_value(
            instance,
            plan,
            run_id=f"milp_default_{case_key}",
        )
        components["Phi_dis"] = dro_eval["Phi_dis"]
        components["J_common"] = (
            components["F_cons"]
            + (1.0 - float(components["pi_f"])) * components["Psi_nor"]
            + float(components["pi_f"]) * components["Phi_dis"]
        )
        components["active_outage_lines"] = dro_eval["active_outage_lines"]
        training = _training_fields(case_key, promoted_id, milp_payloads)
        row = {
            "case_id": case_id,
            "case_name": case_name,
            "source_case": case_key,
            "promoted_run_id": promoted_id,
            **training,
            "normal_scenario_count": components["normal_scenario_count"],
            "disaster_scenario_count": components["disaster_scenario_count"],
            "K": components["K"],
            "disaster_evaluator": "milp_worst_distribution",
            "F_cons": components["F_cons"],
            "F_trans": components["F_trans"],
            "F_unmet": components["F_unmet"],
            "F_sub": components["F_sub"],
            "Psi_nor": components["Psi_nor"],
            "Phi_dis": components["Phi_dis"],
            "pi_f": components["pi_f"],
            "J_common": components["J_common"],
            **_plan_metrics(plan_path),
            "active_outage_lines": components["active_outage_lines"],
            "separation_status": components["separation_status"],
            "separation_reconstruction_gap": components["separation_reconstruction_gap"],
            "fixed_plan_dro_iterations": dro_eval["iterations"],
            "fixed_plan_dro_cuts": dro_eval["cuts"],
            "fixed_plan_dro_final_violation": dro_eval["final_violation"],
            "fixed_plan_dro_final_violation_bound": dro_eval["final_violation_bound"],
            "fixed_plan_dro_alpha": dro_eval["alpha"],
            "fixed_plan_dro_lambda_times_FP": dro_eval["lambda_times_FP"],
            "fixed_plan_active_outage_trace": dro_eval["active_outage_trace"],
            "evaluated_outage_patterns": "",
            "plan_path": str(plan_path.relative_to(REPO_ROOT)),
        }
        table_rows.append(row)

    _write_rows(PAPER_ROOT / "objective_components_tableIII.csv", table_rows)
    _write_rows(PAPER_ROOT / "default_topology_evidence.csv", _topology_rows(table_rows))

    proposed = next(row for row in table_rows if row["source_case"] == "proposed")
    deterministic_k2 = next(row for row in table_rows if row["source_case"] == "deterministic_k2")
    deterministic = next(row for row in table_rows if row["source_case"] == "deterministic")
    det_rows: list[dict[str, Any]] = []
    for row in (proposed, deterministic_k2, deterministic):
        phi = _float(row["Phi_dis"])
        reduction = (
            ""
            if row["source_case"] == "proposed"
            else 100.0 * (phi - _float(proposed["Phi_dis"])) / phi
            if phi
            else ""
        )
        det_rows.append(
            {
                "case": row["source_case"],
                "benchmark_role": (
                    "proposed"
                    if row["source_case"] == "proposed"
                    else "fair deterministic mean-value with K_train=2"
                    if row["source_case"] == "deterministic_k2"
                    else "naive deterministic diagnostic with K_train=0"
                ),
                "training_algorithm": row["training_algorithm"],
                "Phi_worst": row["Phi_dis"],
                "pi_f_Phi_worst": _float(row["pi_f"]) * phi,
                "F_cons": row["F_cons"],
                "Psi_nor": row["Psi_nor"],
                "J_common": row["J_common"],
                "Phi_reduction_pct_vs_this_comparator": reduction,
                "active_outage_lines": row["active_outage_lines"],
                "plan_path": row["plan_path"],
            }
        )
    _write_rows(PAPER_ROOT / "deterministic_worst_distribution.csv", det_rows)

    pi_f = _float(proposed["pi_f"])
    normal = next(row for row in table_rows if row["source_case"] == "normal")
    delta_daily = (
        _float(proposed["F_cons"]) + (1.0 - pi_f) * _float(proposed["Psi_nor"])
        - _float(normal["F_cons"]) - (1.0 - pi_f) * _float(normal["Psi_nor"])
    )
    delta_resilience = pi_f * (_float(normal["Phi_dis"]) - _float(proposed["Phi_dis"]))
    det_k2_reduction = 100.0 * (
        _float(deterministic_k2["Phi_dis"]) - _float(proposed["Phi_dis"])
    ) / _float(deterministic_k2["Phi_dis"])
    verdict = (
        "PASS_MILP_DEFAULT_PROMOTION"
        if det_k2_reduction > 0.0 and delta_resilience > 0.0
        else "NEED_RECALIBRATION_OR_BUG_REVIEW"
    )
    audit = {
        "verdict": verdict,
        "proposed_training_algorithm": "milp_fixed_dual_benders",
        "common_evaluator": "milp_worst_distribution",
        "proposed_validation_level": proposed["training_validation_level"],
        "proposed_final_violation": proposed["training_final_violation"],
        "proposed_sites": proposed["sites"],
        "proposed_slow_chargers": proposed["slow_chargers"],
        "proposed_fast_chargers": proposed["fast_chargers"],
        "proposed_phi": proposed["Phi_dis"],
        "normal_phi": normal["Phi_dis"],
        "deterministic_k2_phi": deterministic_k2["Phi_dis"],
        "deterministic_k2_phi_reduction_pct": det_k2_reduction,
        "delta_daily_vs_normal": delta_daily,
        "delta_resilience_vs_normal": delta_resilience,
        "delta_resilience_over_delta_daily": (
            delta_resilience / delta_daily if abs(delta_daily) > 1e-12 else ""
        ),
        "paper_claim_boundary": (
            "Use the MILP fixed-dual Benders plan as the proposed default. "
            "The deterministic comparison is a resilience claim under the same MILP "
            "worst-distribution replay, not a universal total-cost dominance claim."
        ),
    }
    _write_json(PAPER_ROOT / "milp_default_case_audit.json", audit)
    (PAPER_ROOT / "milp_default_case_audit.md").write_text(
        "# MILP Default Case Audit\n\n"
        f"Verdict: `{audit['verdict']}`\n\n"
        f"- Proposed Phi: `{float(proposed['Phi_dis']):,.2f}`\n"
        f"- Fair deterministic-K2 Phi: `{float(deterministic_k2['Phi_dis']):,.2f}`\n"
        f"- Phi reduction: `{det_k2_reduction:,.2f}%`\n"
        f"- DeltaDaily vs normal: `{delta_daily:,.2f}`\n"
        f"- DeltaResilience vs normal: `{delta_resilience:,.2f}`\n"
        f"- Proposed topology: {proposed['sites']} sites, "
        f"{proposed['slow_chargers']} slow, {proposed['fast_chargers']} fast chargers.\n",
        encoding="utf-8",
    )

    write_plan_map_figure(
        run_ids=(
            "default_scale_v2_proposed",
            "default_scale_v2_normal",
            "default_scale_v2_disaster",
        ),
        plans_dir=PAPER_ROOT / "plans",
        title="Default MILP-separation plans",
        path=PAPER_ROOT / "figures" / "default_maps_milp.png",
        ncols=1,
    )
    write_plan_map_figure(
        run_ids=("default_scale_v2_deterministic_k2",),
        plans_dir=PAPER_ROOT / "plans",
        title="Fair deterministic mean-value plan",
        path=PAPER_ROOT / "figures" / "deterministic_k2_map_milp.png",
        ncols=1,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
