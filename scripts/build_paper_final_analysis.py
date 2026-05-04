"""Build paper-final tables, figures, audits, and experiment-section text.

This script is intentionally stricter than the legacy experiment pack: it
replays first-stage plans under a common evaluator and exposes the
Table-III/Table-IV objective decomposition required for paper analysis.
"""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable, Mapping, Sequence

import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import (
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from src.instance.canonical_instance import CanonicalInstance
from src.production.first_stage import (
    build_first_stage_model,
    extract_first_stage_solution,
)
from src.production.normal_block import (
    build_normal_operation_block,
    extract_normal_operation_solution,
)
from src.production.separation_milp import solve_separation_milp
from src.reference.disaster_primal_ref import (
    FixedFirstStagePlan,
    build_fixed_first_stage_plan,
)
from src.reference.disaster_exact_oracle import solve_disaster_exact_oracle
from src.reference.outage_enumerator import derive_single_line_omega_bounds
from src.reference.outage_enumerator import solve_separation_violation_by_enumeration


PAPER_ROOT = Path("results/paper_final")
FIGURES_DIR = PAPER_ROOT / "figures"
DOCS_DIR = Path("docs/analysis_packs")
CRITICAL_BUS_CONFIG = "configs/critical_buses_paper_fig2.yaml"
BASE_MAIN_RUN = "paper_scale_matrix_A10_B10_k2_integrated"
DEFAULT_SELECTION = {
    "scenarios_a": list(range(1, 11)),
    "scenarios_b": list(range(1, 11)),
}
CASE_RUNS = {
    "Case 1": ("Proposed integrated", "paper_scale_matrix_A10_B10_k2_integrated", 1.0),
    "Case 2": ("Normal-only", "paper_scale_matrix_A10_B10_k2_normal", 1.0),
    "Case 3": ("Disaster-only", "disaster_only_paper_like", 1.0),
    "Case 4": ("Deterministic mean-value", "paper_scale_matrix_A10_B10_k2_deterministic", 1.0),
}
SENSITIVITY_RUNS = {
    "Base": ("Proposed integrated", "paper_scale_matrix_A10_B10_k2_integrated", 1.0),
    "EV 1.5x": ("EV penetration 1.5x", "paper_scale_matrix_A10_B10_k2_ev1p5", 1.5),
    "EV 2.0x": ("EV penetration 2.0x", "paper_scale_matrix_A10_B10_k2_ev2p0", 2.0),
}
REFERENCE_TABLE_III = {
    "Case 1": {
        "F_cons": 88408.78,
        "F_trans": 17202.11,
        "F_unmet": 0.0,
        "F_sub": 29951.26,
        "Psi_nor": 47153.37,
        "Phi_dis": 893.91,
    },
    "Case 2": {
        "F_cons": 45550.54,
        "F_trans": 17099.30,
        "F_unmet": 0.0,
        "F_sub": 29951.26,
        "Psi_nor": 47050.56,
        "Phi_dis": 8451.73,
    },
    "Case 3": {
        "F_cons": 103218.92,
        "F_trans": 14152.47,
        "F_unmet": 8514421.07,
        "F_sub": 24940.13,
        "Psi_nor": 8553513.67,
        "Phi_dis": 0.0,
    },
    "Case 4": {
        "F_cons": 86903.68,
        "F_trans": 17115.09,
        "F_unmet": 0.0,
        "F_sub": 29951.26,
        "Psi_nor": 47066.35,
        "Phi_dis": 2230.34,
    },
}
SCREENING_CANDIDATES = [
    {
        "candidate_id": "current_scale",
        "cpur_scale": 1.0,
        "ctrans_scale": 1.0,
        "cls_critical": 50.0,
        "cls_noncritical": 10.0,
        "pi_f": 0.3,
    },
    {
        "candidate_id": "paper_magnitude_uniform_phi",
        "cpur_scale": 0.001655,
        "ctrans_scale": 0.116,
        "cls_critical": 2.55,
        "cls_noncritical": 0.51,
        "pi_f": 0.3,
    },
    {
        "candidate_id": "paper_magnitude_current_phi",
        "cpur_scale": 0.001655,
        "ctrans_scale": 0.116,
        "cls_critical": 50.0,
        "cls_noncritical": 10.0,
        "pi_f": 0.3,
    },
    {
        "candidate_id": "critical_dominant_50_1",
        "cpur_scale": 0.001655,
        "ctrans_scale": 0.116,
        "cls_critical": 50.0,
        "cls_noncritical": 1.0,
        "pi_f": 0.3,
    },
    {
        "candidate_id": "critical_dominant_100_1",
        "cpur_scale": 0.001655,
        "ctrans_scale": 0.116,
        "cls_critical": 100.0,
        "cls_noncritical": 1.0,
        "pi_f": 0.3,
    },
    {
        "candidate_id": "critical_dominant_200_1",
        "cpur_scale": 0.001655,
        "ctrans_scale": 0.116,
        "cls_critical": 200.0,
        "cls_noncritical": 1.0,
        "pi_f": 0.3,
    },
]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def _fmt(value: float | str | None, digits: int = 2) -> str:
    if value in (None, ""):
        return "--"
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return value
    return f"{float(value):,.{digits}f}"


def _pct(numerator: float, denominator: float) -> float:
    if abs(denominator) <= 1e-12:
        return 0.0
    return 100.0 * numerator / denominator


def _latex_escape(text: str) -> str:
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
    }
    escaped = str(text)
    for src, dst in replacements.items():
        escaped = escaped.replace(src, dst)
    return escaped


def _load_log(run_id: str) -> dict[str, Any]:
    return json.loads((PAPER_ROOT / "logs" / f"{run_id}_run.json").read_text(encoding="utf-8"))


def _load_plan(instance: CanonicalInstance, run_id: str) -> FixedFirstStagePlan:
    rows = _read_csv(PAPER_ROOT / "plans" / f"{run_id}_plan.csv")
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _base_eval_config(*, ev_scale: float = 1.0, k: int = 2) -> dict[str, Any]:
    raw = copy.deepcopy(_load_log(BASE_MAIN_RUN)["run_config"])
    raw["run_id"] = f"common_eval_A10_B10_K{k}_ev{ev_scale:g}"
    raw["case_name"] = raw["run_id"]
    raw["mode"] = "integrated_mainline"
    raw["solver"] = "benders"
    raw["selection"] = copy.deepcopy(DEFAULT_SELECTION)
    raw["parameter_regime"] = "paper_common_evaluator"
    raw["family_name"] = "paper_common_evaluator"
    raw["ev_penetration_scale"] = float(ev_scale)
    parameter_overrides = copy.deepcopy(raw.get("parameter_overrides", {}))
    ambiguity = dict(parameter_overrides.get("ambiguity", {}))
    ambiguity["k_max_outages"] = int(k)
    parameter_overrides["ambiguity"] = ambiguity
    raw["parameter_overrides"] = parameter_overrides
    raw["benders"] = {"epsilon_cert": 0.0, "max_iterations": 100}
    return raw


def _load_eval_instance(*, ev_scale: float = 1.0, k: int = 2) -> CanonicalInstance:
    config = _base_eval_config(ev_scale=ev_scale, k=k)
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    base = load_instance_for_run(config, critical_buses=critical_buses)
    return prepare_instance_for_run(base, config)


def _fix_first_stage_plan(
    instance: CanonicalInstance,
    plan: FixedFirstStagePlan,
    *,
    attach_objective: bool,
    model_name: str,
):
    first_stage = build_first_stage_model(
        instance,
        model_name=model_name,
        log_to_console=False,
        attach_objective=attach_objective,
    )
    for bus in instance.sets.buses:
        first_stage.model.addConstr(
            first_stage.z_by_bus[bus] == float(plan.z_by_bus[bus]),
            name=f"fix_z_n{bus}",
        )
        first_stage.model.addConstr(
            first_stage.n_sl_by_bus[bus] == float(plan.n_sl_by_bus[bus]),
            name=f"fix_n_sl_n{bus}",
        )
        first_stage.model.addConstr(
            first_stage.n_fa_by_bus[bus] == float(plan.n_fa_by_bus[bus]),
            name=f"fix_n_fa_n{bus}",
        )
    first_stage.model.update()
    return first_stage


def _evaluate_fixed_plan_components(
    instance: CanonicalInstance,
    plan: FixedFirstStagePlan,
    *,
    run_id: str,
    k: int = 2,
    disaster_evaluator: str = "milp",
) -> dict[str, Any]:
    first_stage = _fix_first_stage_plan(
        instance,
        plan,
        attach_objective=True,
        model_name=f"{run_id}_construction_eval",
    )
    first_stage.model.optimize()
    first_stage_solution = extract_first_stage_solution(first_stage)
    if first_stage_solution.model_status != "OPTIMAL":
        raise RuntimeError(f"{run_id}: construction evaluation did not solve.")

    transport_by_scenario: dict[int, float] = {}
    unmet_by_scenario: dict[int, float] = {}
    substation_by_scenario: dict[int, float] = {}
    normal_by_scenario: dict[int, float] = {}
    for scenario_id in instance.sets.loaded_normal_scenarios:
        fixed = _fix_first_stage_plan(
            instance,
            plan,
            attach_objective=False,
            model_name=f"{run_id}_normal_eval_s{scenario_id}",
        )
        block = build_normal_operation_block(
            instance,
            first_stage=fixed,
            scenario_id=int(scenario_id),
            model_name=f"{run_id}_normal_eval_s{scenario_id}",
            log_to_console=False,
            attach_objective=True,
        )
        block.model.optimize()
        solution = extract_normal_operation_solution(block)
        if solution.model_status != "OPTIMAL":
            raise RuntimeError(f"{run_id}: normal scenario {scenario_id} did not solve.")
        transport_by_scenario[int(scenario_id)] = float(solution.transport_cost_value)
        unmet_by_scenario[int(scenario_id)] = float(solution.unmet_cost_value)
        substation_by_scenario[int(scenario_id)] = float(solution.substation_cost_value)
        normal_by_scenario[int(scenario_id)] = float(solution.normal_objective_value)

    evaluator_name = disaster_evaluator.strip().lower()
    if evaluator_name == "milp":
        # Use a fixed, audited wide bound for the compact MILP separator.
        # Per-plan bounds derived from single-line probes can be too tight for
        # multi-line outage products and then understate the separation value.
        omega_bounds = {
            line_id: (0.0, 2.0e7)
            for line_id in instance.sets.line_ids
        }
        _, sep = solve_separation_milp(
            instance,
            plan=plan,
            alpha=0.0,
            lambda_by_line_id=None,
            omega_bounds_by_line_id=omega_bounds,
            budget_k=int(k),
            scenario_ids=instance.sets.loaded_disaster_scenarios,
            model_name=f"{run_id}_phi_common_eval",
            log_to_console=False,
        )
        phi = max(0.0, float(sep.objective_value or 0.0))
        active_outage_lines = ";".join(
            line for line, value in sep.delta_by_line_id.items() if int(value) == 1
        )
        separation_status = sep.model_status
        separation_reconstruction_gap = float(sep.reconstruction_gap)
        evaluated_outage_patterns = ""
    elif evaluator_name == "enumeration":
        enum = solve_separation_violation_by_enumeration(
            instance,
            plan=plan,
            alpha=0.0,
            lambda_by_line_id=None,
            budget_k=int(k),
            scenario_ids=instance.sets.loaded_disaster_scenarios,
        )
        phi = max(0.0, float(enum.objective_value))
        active_outage_lines = ";".join(enum.best_pattern.active_line_ids)
        separation_status = "ENUMERATION_EXACT"
        separation_reconstruction_gap = 0.0
        evaluated_outage_patterns = len(enum.evaluated_patterns)
    elif evaluator_name == "exact_primal_dro":
        _, exact = solve_disaster_exact_oracle(
            instance,
            plan=plan,
            scenario_ids=instance.sets.loaded_disaster_scenarios,
            model_name_prefix=f"{run_id}_exact_primal_dro",
        )
        phi = max(0.0, float(exact.outer_dro_value))
        active_outage_lines = ";".join(exact.active_worst_case_patterns)
        separation_status = "EXACT_PRIMAL_DRO"
        separation_reconstruction_gap = 0.0
        evaluated_outage_patterns = len(exact.outage_patterns)
    else:
        raise ValueError(f"Unsupported disaster_evaluator={disaster_evaluator!r}.")
    pi_f = float(instance.economics.pi_f)
    f_trans = statistics.fmean(transport_by_scenario.values())
    f_unmet = statistics.fmean(unmet_by_scenario.values())
    f_sub = statistics.fmean(substation_by_scenario.values())
    psi = float(f_trans + f_unmet + f_sub)
    f_cons = float(first_stage_solution.construction_cost_value)
    return {
        "F_cons": f_cons,
        "F_trans": float(f_trans),
        "F_unmet": float(f_unmet),
        "F_sub": float(f_sub),
        "Psi_nor": psi,
        "Phi_dis": phi,
        "pi_f": pi_f,
        "J_common": float(f_cons + (1.0 - pi_f) * psi + pi_f * phi),
        "active_outage_lines": active_outage_lines,
        "separation_status": separation_status,
        "separation_reconstruction_gap": separation_reconstruction_gap,
        "disaster_evaluator": evaluator_name,
        "evaluated_outage_patterns": evaluated_outage_patterns,
        "normal_scenario_count": len(instance.sets.loaded_normal_scenarios),
        "disaster_scenario_count": len(instance.sets.loaded_disaster_scenarios),
        "K": int(k),
        "transport_by_scenario": transport_by_scenario,
        "unmet_by_scenario": unmet_by_scenario,
        "substation_by_scenario": substation_by_scenario,
        "normal_by_scenario": normal_by_scenario,
    }


def _plan_metrics(run_id: str) -> dict[str, Any]:
    rows = _read_csv(PAPER_ROOT / "plans" / f"{run_id}_plan.csv")
    opened = [row for row in rows if int(float(row["is_open"])) == 1]
    covered_critical = sum(
        1 for row in rows if int(float(row["is_open"])) == 1 and int(float(row["is_critical"])) == 1
    )
    critical_total = sum(1 for row in rows if int(float(row["is_critical"])) == 1)
    return {
        "sites": len(opened),
        "slow_chargers": sum(int(float(row["n_sl"])) for row in rows),
        "fast_chargers": sum(int(float(row["n_fa"])) for row in rows),
        "total_chargers": sum(int(float(row["n_sl"])) + int(float(row["n_fa"])) for row in rows),
        "critical_bus_coverage": f"{covered_critical}/{critical_total}",
    }


def _summary_lookup() -> dict[str, dict[str, str]]:
    return {row["run_id"]: row for row in _read_csv(PAPER_ROOT / "summary.csv")}


def _build_component_rows(
    run_specs: Mapping[str, tuple[str, str, float]],
    *,
    table_kind: str,
) -> list[dict[str, Any]]:
    summary = _summary_lookup()
    rows: list[dict[str, Any]] = []
    instance_cache: dict[tuple[float, int], CanonicalInstance] = {}
    for case_id, (case_name, run_id, ev_scale) in run_specs.items():
        key = (float(ev_scale), 2)
        if key not in instance_cache:
            instance_cache[key] = _load_eval_instance(ev_scale=ev_scale, k=2)
        instance = instance_cache[key]
        plan = _load_plan(instance, run_id)
        components = _evaluate_fixed_plan_components(
            instance,
            plan,
            run_id=f"{table_kind}_{case_id.replace(' ', '_').lower()}",
            k=2,
        )
        metrics = _plan_metrics(run_id)
        training = summary.get(run_id, {})
        row = {
            "case_id": case_id,
            "case_name": case_name,
            "run_id": run_id,
            "training_validation_level": training.get("validation_level", ""),
            "training_stop_reason": training.get("stop_reason", ""),
            "training_iterations": training.get("iteration_count", ""),
            "training_cut_count": training.get("cut_count", ""),
            "training_final_violation": training.get("final_violation_upper_bound", ""),
            "common_eval_A": components["normal_scenario_count"],
            "common_eval_B": components["disaster_scenario_count"],
            "common_eval_K": components["K"],
            **{key: components[key] for key in (
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
            )},
            **metrics,
        }
        rows.append(row)
    return rows


def _write_component_tables() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fields = [
        "case_id",
        "case_name",
        "run_id",
        "training_validation_level",
        "training_stop_reason",
        "training_iterations",
        "training_cut_count",
        "training_final_violation",
        "common_eval_A",
        "common_eval_B",
        "common_eval_K",
        "F_cons",
        "F_trans",
        "F_unmet",
        "F_sub",
        "Psi_nor",
        "Phi_dis",
        "pi_f",
        "J_common",
        "sites",
        "slow_chargers",
        "fast_chargers",
        "total_chargers",
        "critical_bus_coverage",
        "active_outage_lines",
        "separation_status",
        "separation_reconstruction_gap",
    ]
    table_iii = _build_component_rows(CASE_RUNS, table_kind="tableIII")
    table_iv = _build_component_rows(SENSITIVITY_RUNS, table_kind="tableIV")
    _write_csv(PAPER_ROOT / "objective_components_tableIII.csv", table_iii, fields)
    _write_csv(PAPER_ROOT / "sensitivity_components_tableIV.csv", table_iv, fields)
    return table_iii, table_iv


def _safe_ratio(numerator: float, denominator: float) -> float:
    if abs(float(denominator)) <= 1e-12:
        return 0.0
    return float(numerator) / float(denominator)


def _write_unit_scale_audit(table_iii: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    current = next(row for row in table_iii if row["case_id"] == "Case 1")
    reference = REFERENCE_TABLE_III["Case 1"]
    rows: list[dict[str, Any]] = []
    for field in ("F_cons", "F_trans", "F_unmet", "F_sub", "Psi_nor", "Phi_dis"):
        current_value = float(current[field])
        reference_value = float(reference[field])
        rows.append(
            {
                "component": field,
                "current_case1": current_value,
                "reference_case1": reference_value,
                "current_over_reference": _safe_ratio(current_value, reference_value),
                "reference_over_current": _safe_ratio(reference_value, current_value),
            }
        )

    recommended = {
        "cpur_scale_to_reference_F_sub": _safe_ratio(reference["F_sub"], float(current["F_sub"])),
        "ctrans_scale_to_reference_F_trans": _safe_ratio(reference["F_trans"], float(current["F_trans"])),
        "uniform_cls_scale_to_reference_Phi": _safe_ratio(reference["Phi_dis"], float(current["Phi_dis"])),
        "diagnosis": (
            "F_sub is the dominant scale mismatch; the current normal-operation electricity "
            "purchase term is roughly hundreds of times larger than the reference Table III "
            "case-study magnitude."
        ),
    }
    for row in rows:
        row.update(recommended)
    _write_csv(
        PAPER_ROOT / "unit_scale_audit.csv",
        rows,
        [
            "component",
            "current_case1",
            "reference_case1",
            "current_over_reference",
            "reference_over_current",
            "cpur_scale_to_reference_F_sub",
            "ctrans_scale_to_reference_F_trans",
            "uniform_cls_scale_to_reference_Phi",
            "diagnosis",
        ],
    )
    md = [
        "# Unit And Cost-Scale Audit",
        "",
        "Result: **ACTION REQUIRED**",
        "",
        "The current component pipeline is internally consistent, but the component magnitudes do not match the paper-style case-study scale.",
        "",
        "## Recommended First Calibration",
        f"- Scale `Cpur` by `{recommended['cpur_scale_to_reference_F_sub']:.6g}` to align Case 1 `F_sub` with the reference Table III magnitude.",
        f"- Scale `Ctrans` by `{recommended['ctrans_scale_to_reference_F_trans']:.6g}` to align Case 1 `F_trans` with the reference Table III magnitude.",
        f"- A uniform `CLS` scale of `{recommended['uniform_cls_scale_to_reference_Phi']:.6g}` aligns Case 1 `Phi_dis`, but it does not by itself fix the deterministic robustness ordering.",
        "",
        "## Blocking Interpretation",
        "- The old `F_sub` value is too large for a meaningful normal/resilience tradeoff.",
        "- The next optimization must use a calibrated scale and still pass the deterministic worst-distribution gate.",
    ]
    (PAPER_ROOT / "unit_scale_audit.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return recommended


def _screening_eval_config(candidate: Mapping[str, Any]) -> dict[str, Any]:
    raw = _base_eval_config(ev_scale=1.0, k=2)
    raw["run_id"] = f"screening_{candidate['candidate_id']}"
    raw["case_name"] = raw["run_id"]
    raw["parameter_regime"] = str(candidate["candidate_id"])
    overrides = copy.deepcopy(raw.get("parameter_overrides", {}))
    economics = dict(overrides.get("economics", {}))
    runtime_parameters = json.loads(Path("data/runtime_12/parameters.json").read_text(encoding="utf-8"))
    economics["cpur"] = [
        float(value) * float(candidate["cpur_scale"])
        for value in runtime_parameters["econ"]["Cpur"]
    ]
    base_ctrans = float(economics.get("ctrans_scalar", 0.0435))
    economics["ctrans_scalar"] = base_ctrans * float(candidate["ctrans_scale"])
    economics["pi_f"] = float(candidate["pi_f"])
    overrides["economics"] = economics
    overrides["disaster_objective"] = {
        "cls_critical": float(candidate["cls_critical"]),
        "cls_noncritical": float(candidate["cls_noncritical"]),
    }
    raw["parameter_overrides"] = overrides
    return raw


def _screen_candidate(
    candidate: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    critical_buses = load_critical_buses(CRITICAL_BUS_CONFIG)
    config = _screening_eval_config(candidate)
    instance = prepare_instance_for_run(
        load_instance_for_run(config, critical_buses=critical_buses),
        config,
    )
    case_specs = {
        "proposed": ("Proposed integrated", "paper_scale_matrix_A10_B10_k2_integrated"),
        "normal_only": ("Normal-only", "paper_scale_matrix_A10_B10_k2_normal"),
        "deterministic": ("Deterministic mean-value", "paper_scale_matrix_A10_B10_k2_deterministic"),
    }
    rows: list[dict[str, Any]] = []
    component_by_case: dict[str, dict[str, Any]] = {}
    for case_key, (case_name, run_id) in case_specs.items():
        plan = _load_plan(instance, run_id)
        components = _evaluate_fixed_plan_components(
            instance,
            plan,
            run_id=f"screening_{candidate['candidate_id']}_{case_key}",
            k=2,
        )
        row = {
            "candidate_id": candidate["candidate_id"],
            "case_key": case_key,
            "case_name": case_name,
            "source_run_id": run_id,
            "cpur_scale": candidate["cpur_scale"],
            "ctrans_scale": candidate["ctrans_scale"],
            "cls_critical": candidate["cls_critical"],
            "cls_noncritical": candidate["cls_noncritical"],
            **{key: components[key] for key in (
                "F_cons",
                "F_trans",
                "F_unmet",
                "F_sub",
                "Psi_nor",
                "Phi_dis",
                "pi_f",
                "J_common",
                "active_outage_lines",
            )},
        }
        component_by_case[case_key] = row
        rows.append(row)

    proposed = component_by_case["proposed"]
    normal = component_by_case["normal_only"]
    deterministic = component_by_case["deterministic"]
    pi_f = float(proposed["pi_f"])
    det_reduction_pct = _pct(
        float(deterministic["Phi_dis"]) - float(proposed["Phi_dis"]),
        float(deterministic["Phi_dis"]),
    )
    delta_daily = (
        float(proposed["F_cons"]) + (1.0 - pi_f) * float(proposed["Psi_nor"])
        - float(normal["F_cons"]) - (1.0 - pi_f) * float(normal["Psi_nor"])
    )
    delta_resilience = pi_f * (float(normal["Phi_dis"]) - float(proposed["Phi_dis"]))
    summary = {
        "candidate_id": candidate["candidate_id"],
        "cpur_scale": candidate["cpur_scale"],
        "ctrans_scale": candidate["ctrans_scale"],
        "cls_critical": candidate["cls_critical"],
        "cls_noncritical": candidate["cls_noncritical"],
        "pi_f": pi_f,
        "proposed_phi_over_psi_percent": _pct(float(proposed["Phi_dis"]), float(proposed["Psi_nor"])),
        "normal_phi_over_psi_percent": _pct(float(normal["Phi_dis"]), float(normal["Psi_nor"])),
        "deterministic_phi_over_psi_percent": _pct(float(deterministic["Phi_dis"]), float(deterministic["Psi_nor"])),
        "deterministic_reduction_pct_det_minus_prop": det_reduction_pct,
        "delta_daily_prop_minus_normal": delta_daily,
        "delta_resilience_prop_vs_normal": delta_resilience,
        "delta_resilience_over_delta_daily": _safe_ratio(delta_resilience, delta_daily),
        "passes_material_phi_gate": _pct(float(proposed["Phi_dis"]), float(proposed["Psi_nor"])) >= 1.0,
        "passes_deterministic_gate": det_reduction_pct >= 20.0,
        "passes_tradeoff_gate": delta_daily > 0.0 and _safe_ratio(delta_resilience, delta_daily) >= 1.5,
    }
    summary["passes_all_screening_gates"] = bool(
        summary["passes_material_phi_gate"]
        and summary["passes_deterministic_gate"]
        and summary["passes_tradeoff_gate"]
    )
    return rows, summary


def _write_plan_pool_screening() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    plan_rows: list[dict[str, Any]] = []
    screening_rows: list[dict[str, Any]] = []
    for candidate in SCREENING_CANDIDATES:
        try:
            candidate_plan_rows, summary = _screen_candidate(candidate)
        except Exception as exc:
            summary = {
                "candidate_id": candidate["candidate_id"],
                "cpur_scale": candidate["cpur_scale"],
                "ctrans_scale": candidate["ctrans_scale"],
                "cls_critical": candidate["cls_critical"],
                "cls_noncritical": candidate["cls_noncritical"],
                "pi_f": candidate["pi_f"],
                "proposed_phi_over_psi_percent": "",
                "normal_phi_over_psi_percent": "",
                "deterministic_phi_over_psi_percent": "",
                "deterministic_reduction_pct_det_minus_prop": "",
                "delta_daily_prop_minus_normal": "",
                "delta_resilience_prop_vs_normal": "",
                "delta_resilience_over_delta_daily": "",
                "passes_material_phi_gate": False,
                "passes_deterministic_gate": False,
                "passes_tradeoff_gate": False,
                "passes_all_screening_gates": False,
                "error": f"{exc.__class__.__name__}: {exc}",
            }
            candidate_plan_rows = []
        plan_rows.extend(candidate_plan_rows)
        screening_rows.append(summary)

    _write_csv(
        PAPER_ROOT / "plan_pool_cross_evaluation.csv",
        plan_rows,
        [
            "candidate_id",
            "case_key",
            "case_name",
            "source_run_id",
            "cpur_scale",
            "ctrans_scale",
            "cls_critical",
            "cls_noncritical",
            "F_cons",
            "F_trans",
            "F_unmet",
            "F_sub",
            "Psi_nor",
            "Phi_dis",
            "pi_f",
            "J_common",
            "active_outage_lines",
        ],
    )
    _write_csv(
        PAPER_ROOT / "calibration_screening_matrix.csv",
        screening_rows,
        [
            "candidate_id",
            "cpur_scale",
            "ctrans_scale",
            "cls_critical",
            "cls_noncritical",
            "pi_f",
            "proposed_phi_over_psi_percent",
            "normal_phi_over_psi_percent",
            "deterministic_phi_over_psi_percent",
            "deterministic_reduction_pct_det_minus_prop",
            "delta_daily_prop_minus_normal",
            "delta_resilience_prop_vs_normal",
            "delta_resilience_over_delta_daily",
            "passes_material_phi_gate",
            "passes_deterministic_gate",
            "passes_tradeoff_gate",
            "passes_all_screening_gates",
            "error",
        ],
    )
    pass_rows = [row for row in screening_rows if row.get("passes_all_screening_gates")]
    md = [
        "# Calibration Screening Matrix",
        "",
        f"Evaluated {len(screening_rows)} cost-scale candidates against the current plan pool.",
        "",
        "## Result",
        "**PASS candidate found**" if pass_rows else "**No current plan-pool candidate passes all paper gates.**",
        "",
        "## Interpretation",
        "- This screening is deliberately cheaper than full integrated Benders: it freezes existing plans and replays them under calibrated common evaluators.",
        "- A candidate that passes here still needs a certified optimization run before it can enter the paper.",
        "- If no candidate passes, the next step is not writing; it is model/calibration remediation or a downgraded claim.",
    ]
    (PAPER_ROOT / "calibration_screening_matrix.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return plan_rows, screening_rows


def _read_grouped_totals(path: Path, scenario_col: str, value_cols: Sequence[str]) -> dict[int, dict[str, float]]:
    totals: dict[int, dict[str, float]] = {}
    for row in _read_csv(path):
        scenario = int(row[scenario_col])
        bucket = totals.setdefault(scenario, {key: 0.0 for key in value_cols})
        for key in value_cols:
            bucket[key] += float(row[key])
    return totals


def _write_setup_and_scenario_artifacts() -> None:
    max_a, max_b = _max_scenario_support_from_summary()
    parameter_rows = [
        {"symbol": "Cfix", "description": "Fixed infrastructure cost", "value": "153600", "unit": "$"},
        {"symbol": "Ccons_sl", "description": "Installation cost per slow EVSE", "value": "540.07", "unit": "$/EVSE"},
        {"symbol": "Ccons_fa", "description": "Installation cost per fast EVSE", "value": "25000", "unit": "$/EVSE"},
        {"symbol": "Ctrans", "description": "Transportation cost scalar", "value": "0.0435", "unit": "$/km"},
        {"symbol": "Cunmet", "description": "Unmet charging-demand penalty", "value": "3", "unit": "$/kWh"},
        {"symbol": "CLS_cri/noncri", "description": "Critical/non-critical load-shedding penalty", "value": "50/10", "unit": "$/kWh"},
        {"symbol": "gamma", "description": "Discount rate", "value": "0.01", "unit": "-"},
        {"symbol": "theta", "description": "Payback period", "value": "20", "unit": "year"},
        {"symbol": "pi_f", "description": "Disaster-regime weight", "value": "0.3", "unit": "-"},
        {"symbol": "P_EV_sl/fa", "description": "Rated charging power of slow/fast EVSE", "value": "7/50", "unit": "kW"},
        {"symbol": "Nmax_sl/fa", "description": "Maximum slow/fast EVSE per EVCS", "value": "25/10", "unit": "-"},
        {"symbol": "K", "description": "Default outage budget", "value": "2", "unit": "lines"},
        {"symbol": "|A|, |B|", "description": "Default common evaluator support", "value": "10, 10", "unit": "scenarios"},
        {"symbol": "|A|, |B|", "description": "Largest generated scalability support", "value": f"{max_a}, {max_b}", "unit": "scenarios"},
    ]
    _write_csv(
        PAPER_ROOT / "setup_parameter_table.csv",
        parameter_rows,
        ["symbol", "description", "value", "unit"],
    )

    manifest = {
        "base_runtime_source": "data/runtime_12",
        "synthetic_runtime_source": "data/runtime_12_synth_100",
        "base_available_normal_scenarios": list(range(1, 11)),
        "base_available_disaster_scenarios": list(range(1, 11)),
        "synthetic_available_normal_scenarios": list(range(1, 101)),
        "synthetic_available_disaster_scenarios": list(range(1, 101)),
        "paper_common_evaluator": {"A": 10, "B": 10, "K": 2},
        "largest_solved_support_in_summary": {"A": max_a, "B": max_b},
        "requested_large_support_status": "generated_and_tested" if max_a > 10 or max_b > 10 else "base_10x10_only",
        "synthetic_generation": {
            "script": "scripts/generate_runtime_scenarios.py",
            "seed": 20260426,
            "method": (
                "bootstrap base runtime_12 profiles by scenario id and apply bounded "
                "multiplicative time/region perturbations to load, charging demand, "
                "disaster load, and V2G availability"
            ),
        },
        "scenario_generation_interpretation": {
            "A": "normal operating load and EV charging-demand profiles",
            "B": "disaster operating-condition and available V2G discharge profiles",
            "K": "line-outage budget in the ambiguity set",
        },
    }
    _write_json(PAPER_ROOT / "scenario_generation_manifest.json", manifest)

    normal_load = _read_grouped_totals(
        Path("data/runtime_12/normal_load_scenarios.csv"),
        "scenario_a",
        ("P_kW", "Q_kvar"),
    )
    disaster_load = _read_grouped_totals(
        Path("data/runtime_12/disaster_load_scenarios.csv"),
        "scenario_b",
        ("P_kW",),
    )
    normal_slow = _read_grouped_totals(
        Path("data/runtime_12/normal_ev_demand_slow.csv"),
        "scenario_a",
        ("DEV_ch_sl_kW",),
    )
    normal_fast = _read_grouped_totals(
        Path("data/runtime_12/normal_ev_demand_fast.csv"),
        "scenario_a",
        ("DEV_ch_fa_kW",),
    )
    disaster_slow = _read_grouped_totals(
        Path("data/runtime_12/disaster_ev_discharge_slow.csv"),
        "scenario_b",
        ("DEV_dis_sl_kW",),
    )
    disaster_fast = _read_grouped_totals(
        Path("data/runtime_12/disaster_ev_discharge_fast.csv"),
        "scenario_b",
        ("DEV_dis_fa_kW",),
    )

    rows: list[dict[str, Any]] = []
    for scenario in range(1, 11):
        rows.append(
            {
                "scenario_id": scenario,
                "normal_load_P_kW_sum": normal_load[scenario]["P_kW"],
                "normal_load_Q_kvar_sum": normal_load[scenario]["Q_kvar"],
                "normal_EV_slow_kW_sum": normal_slow[scenario]["DEV_ch_sl_kW"],
                "normal_EV_fast_kW_sum": normal_fast[scenario]["DEV_ch_fa_kW"],
                "disaster_load_P_kW_sum": disaster_load[scenario]["P_kW"],
                "disaster_EV_slow_kW_sum": disaster_slow[scenario]["DEV_dis_sl_kW"],
                "disaster_EV_fast_kW_sum": disaster_fast[scenario]["DEV_dis_fa_kW"],
            }
        )
    _write_csv(
        PAPER_ROOT / "scenario_profile_summary.csv",
        rows,
        [
            "scenario_id",
            "normal_load_P_kW_sum",
            "normal_load_Q_kvar_sum",
            "normal_EV_slow_kW_sum",
            "normal_EV_fast_kW_sum",
            "disaster_load_P_kW_sum",
            "disaster_EV_slow_kW_sum",
            "disaster_EV_fast_kW_sum",
        ],
    )
    _plot_scenario_profiles()


def _series_by_time(path: Path, scenario_col: str, scenario: int, time_col: str, value_cols: Sequence[str]) -> dict[str, dict[int, float]]:
    output = {value: {} for value in value_cols}
    for row in _read_csv(path):
        if int(row[scenario_col]) != int(scenario):
            continue
        time_id = int(row[time_col])
        for value_col in value_cols:
            output[value_col][time_id] = output[value_col].get(time_id, 0.0) + float(row[value_col])
    return output


def _plot_scenario_profiles() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    normal_load = _series_by_time(
        Path("data/runtime_12/normal_load_scenarios.csv"),
        "scenario_a",
        1,
        "t",
        ("P_kW", "Q_kvar"),
    )
    normal_ev_slow = _series_by_time(
        Path("data/runtime_12/normal_ev_demand_slow.csv"),
        "scenario_a",
        1,
        "t",
        ("DEV_ch_sl_kW",),
    )
    normal_ev_fast = _series_by_time(
        Path("data/runtime_12/normal_ev_demand_fast.csv"),
        "scenario_a",
        1,
        "t",
        ("DEV_ch_fa_kW",),
    )
    disaster_ev_slow = _series_by_time(
        Path("data/runtime_12/disaster_ev_discharge_slow.csv"),
        "scenario_b",
        1,
        "ts",
        ("DEV_dis_sl_kW",),
    )
    disaster_ev_fast = _series_by_time(
        Path("data/runtime_12/disaster_ev_discharge_fast.csv"),
        "scenario_b",
        1,
        "ts",
        ("DEV_dis_fa_kW",),
    )

    fig, ax = plt.subplots(figsize=(8, 4))
    times = sorted(normal_load["P_kW"])
    ax.plot(times, [normal_load["P_kW"][t] for t in times], marker="o", label="Active load")
    ax.plot(times, [normal_load["Q_kvar"][t] for t in times], marker="s", label="Reactive load")
    ax.set_xlabel("Hour")
    ax.set_ylabel("System load")
    ax.set_title("Normal load profile, scenario a=1")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "scenario_profile_normal_load.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    times = sorted(normal_ev_slow["DEV_ch_sl_kW"])
    ax.plot(times, [normal_ev_slow["DEV_ch_sl_kW"][t] for t in times], marker="o", label="Slow charging demand")
    ax.plot(times, [normal_ev_fast["DEV_ch_fa_kW"][t] for t in times], marker="s", label="Fast charging demand")
    ax.set_xlabel("Hour")
    ax.set_ylabel("EV charging demand (kW)")
    ax.set_title("Normal EV charging profile, scenario a=1")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "scenario_profile_normal_ev.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    times = sorted(disaster_ev_slow["DEV_dis_sl_kW"])
    ax.plot(times, [disaster_ev_slow["DEV_dis_sl_kW"][t] for t in times], marker="o", label="Slow V2G availability")
    ax.plot(times, [disaster_ev_fast["DEV_dis_fa_kW"][t] for t in times], marker="s", label="Fast V2G availability")
    ax.set_xlabel("Disaster time step")
    ax.set_ylabel("Available EV discharge (kW)")
    ax.set_title("Disaster EV discharge profile, scenario b=1")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "scenario_profile_disaster_ev.png", dpi=180)
    plt.close(fig)


def _max_scenario_support_from_summary() -> tuple[int, int]:
    max_a = 10
    max_b = 10
    summary = PAPER_ROOT / "summary.csv"
    if not summary.exists():
        return max_a, max_b
    for row in _read_csv(summary):
        category, a_count, b_count, _ = _scenario_k_from_run_id(row.get("run_id", ""))
        if category == "scenario" and a_count is not None and b_count is not None:
            max_a = max(max_a, int(a_count))
            max_b = max(max_b, int(b_count))
    return max_a, max_b


def _plot_component_figures(table_iii: Sequence[Mapping[str, Any]], table_iv: Sequence[Mapping[str, Any]]) -> None:
    def plot(rows: Sequence[Mapping[str, Any]], path: Path, title: str) -> None:
        labels = [str(row["case_id"]) for row in rows]
        x = list(range(len(rows)))
        fig, ax = plt.subplots(figsize=(9, 4.8))
        bottom = [0.0] * len(rows)
        for field, label in [
            ("F_cons", "Construction"),
            ("F_trans", "Transport"),
            ("F_unmet", "Unmet"),
            ("F_sub", "Substation"),
            ("Phi_dis", "Disaster"),
        ]:
            values = [float(row[field]) for row in rows]
            ax.bar(x, values, bottom=bottom, label=label)
            bottom = [bottom[i] + values[i] for i in x]
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=0)
        ax.set_ylabel("Common-evaluator cost")
        ax.set_title(title)
        ax.legend(fontsize=8, ncols=3)
        fig.tight_layout()
        fig.savefig(path, dpi=180)
        plt.close(fig)

    plot(
        table_iii,
        FIGURES_DIR / "objective_component_decomposition_common_eval.png",
        "Default cases under common evaluator",
    )
    plot(
        table_iv,
        FIGURES_DIR / "ev_sensitivity_component_decomposition_common_eval.png",
        "EV penetration sensitivity under common evaluator",
    )

    proposed = next(row for row in table_iii if row["case_id"] == "Case 1")
    deterministic = next(row for row in table_iii if row["case_id"] == "Case 4")
    fig, ax = plt.subplots(figsize=(6.3, 4.0))
    labels = ["Proposed", "Deterministic"]
    values = [float(proposed["Phi_dis"]), float(deterministic["Phi_dis"])]
    ax.bar(labels, values, color=["#4c78a8", "#f58518"])
    ax.set_ylabel(r"$\Phi^{dis}$ under common evaluator")
    ax.set_title("Worst-distribution disaster comparison")
    for i, value in enumerate(values):
        ax.text(i, value, _fmt(value, 1), ha="center", va="bottom", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "deterministic_worst_distribution_common_eval.png", dpi=180)
    plt.close(fig)


def _iteration_runtime(run_id: str) -> float:
    path = PAPER_ROOT / "logs" / f"{run_id}_iteration_log.json"
    if not path.exists():
        return 0.0
    payload = json.loads(path.read_text(encoding="utf-8"))
    total = 0.0
    for row in payload.get("iterations", []):
        total += float(row.get("master_solve_seconds") or 0.0)
        total += float(row.get("separation_solve_seconds") or 0.0)
        total += float(row.get("cut_generation_seconds") or 0.0)
    return total


def _scenario_k_from_run_id(run_id: str) -> tuple[str, int | None, int | None, int | None]:
    import re

    m = re.match(r"paper_scale_matrix_A(\d+)_B(\d+)_k(\d+)_(integrated|normal|deterministic)", run_id)
    if m:
        return "scenario", int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.match(r"paper_scale_matrix_A10x10_K(\d+)_(integrated|normal|deterministic)", run_id)
    if m:
        return "k_scaling", 10, 10, int(m.group(1))
    return "other", None, None, None


def _write_scalability_tables() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _read_csv(PAPER_ROOT / "summary.csv")
    scenario_rows: list[dict[str, Any]] = []
    k_rows: list[dict[str, Any]] = []
    for row in rows:
        category, a_count, b_count, k_value = _scenario_k_from_run_id(row["run_id"])
        if category == "other":
            continue
        out = {
            "run_id": row["run_id"],
            "mode": row["run_id"].split("_")[-1],
            "A": a_count,
            "B": b_count,
            "K": k_value,
            "validation_level": row["validation_level"],
            "stop_reason": row["stop_reason"],
            "max_iteration_budget": _load_log(row["run_id"])["run_config"].get("benders", {}).get("max_iterations", ""),
            "iterations_used": row["iteration_count"],
            "cuts": row["cut_count"],
            "final_violation": row["final_violation_upper_bound"],
            "runtime_seconds_iteration_log": _iteration_runtime(row["run_id"]),
            "total_objective": row["total_objective"],
            "F_cons": row["construction_cost"],
            "Psi_nor_aggregate": row["unweighted_normal_term"],
            "Phi_master": row["disaster_master_term"],
        }
        if category == "scenario":
            scenario_rows.append(out)
        else:
            k_rows.append(out)

    fields = [
        "run_id",
        "mode",
        "A",
        "B",
        "K",
        "validation_level",
        "stop_reason",
        "max_iteration_budget",
        "iterations_used",
        "cuts",
        "final_violation",
        "runtime_seconds_iteration_log",
        "total_objective",
        "F_cons",
        "Psi_nor_aggregate",
        "Phi_master",
    ]
    scenario_rows.sort(key=lambda r: (int(r["A"]), int(r["B"]), str(r["mode"])))
    k_rows.sort(key=lambda r: (int(r["K"]), str(r["mode"])))
    _write_csv(PAPER_ROOT / "scalability_extended_summary.csv", scenario_rows, fields)
    _write_csv(PAPER_ROOT / "k_scaling_summary.csv", k_rows, fields)
    return scenario_rows, k_rows


def _write_deterministic_comparison(table_iii: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    proposed = next(row for row in table_iii if row["case_id"] == "Case 1")
    deterministic = next(row for row in table_iii if row["case_id"] == "Case 4")
    reduction_abs = float(deterministic["Phi_dis"]) - float(proposed["Phi_dis"])
    reduction_pct = _pct(reduction_abs, float(deterministic["Phi_dis"]))
    rows = [
        {
            "metric": "Phi_worst",
            "proposed": proposed["Phi_dis"],
            "deterministic": deterministic["Phi_dis"],
            "proposed_minus_deterministic": float(proposed["Phi_dis"]) - float(deterministic["Phi_dis"]),
            "reduction_abs_det_minus_prop": reduction_abs,
            "reduction_pct_det_minus_prop": reduction_pct,
            "common_eval_A": proposed["common_eval_A"],
            "common_eval_B": proposed["common_eval_B"],
            "common_eval_K": proposed["common_eval_K"],
            "proposed_active_outage_lines": proposed["active_outage_lines"],
            "deterministic_active_outage_lines": deterministic["active_outage_lines"],
            "claim_supported": "yes" if reduction_pct >= 20.0 else "no",
        },
        {
            "metric": "pi_f_Phi_worst",
            "proposed": float(proposed["pi_f"]) * float(proposed["Phi_dis"]),
            "deterministic": float(deterministic["pi_f"]) * float(deterministic["Phi_dis"]),
            "proposed_minus_deterministic": float(proposed["pi_f"]) * (float(proposed["Phi_dis"]) - float(deterministic["Phi_dis"])),
            "reduction_abs_det_minus_prop": float(proposed["pi_f"]) * reduction_abs,
            "reduction_pct_det_minus_prop": reduction_pct,
            "common_eval_A": proposed["common_eval_A"],
            "common_eval_B": proposed["common_eval_B"],
            "common_eval_K": proposed["common_eval_K"],
            "proposed_active_outage_lines": proposed["active_outage_lines"],
            "deterministic_active_outage_lines": deterministic["active_outage_lines"],
            "claim_supported": "yes" if reduction_pct >= 20.0 else "no",
        },
    ]
    _write_csv(
        PAPER_ROOT / "deterministic_worst_distribution.csv",
        rows,
        [
            "metric",
            "proposed",
            "deterministic",
            "proposed_minus_deterministic",
            "reduction_abs_det_minus_prop",
            "reduction_pct_det_minus_prop",
            "common_eval_A",
            "common_eval_B",
            "common_eval_K",
            "proposed_active_outage_lines",
            "deterministic_active_outage_lines",
            "claim_supported",
        ],
    )
    _write_json(
        PAPER_ROOT / "worst_distribution_support.json",
        {
            "proposed_active_outage_lines": proposed["active_outage_lines"].split(";") if proposed["active_outage_lines"] else [],
            "deterministic_active_outage_lines": deterministic["active_outage_lines"].split(";") if deterministic["active_outage_lines"] else [],
            "note": "The current separation evaluator records the active worst outage pattern, not full ambiguity-set probabilities.",
        },
    )
    return rows


def _write_claim_trace() -> None:
    max_a, max_b = _max_scenario_support_from_summary()
    rows = [
        {
            "claim": "Default cases are compared on a common A=10, B=10, K=2 evaluator.",
            "artifact": "results/paper_final/objective_components_tableIII.csv",
            "status": "available",
        },
        {
            "claim": "Normal-operation analysis decomposes Psi into Ftrans, Funmet, and Fsub.",
            "artifact": "results/paper_final/objective_components_tableIII.csv",
            "status": "available",
        },
        {
            "claim": "Deterministic robustness advantage is assessed under the same worst-distribution evaluator.",
            "artifact": "results/paper_final/deterministic_worst_distribution.csv",
            "status": "available_but_current_result_does_not_support_strong_claim",
        },
        {
            "claim": "EV penetration sensitivity uses the same component taxonomy.",
            "artifact": "results/paper_final/sensitivity_components_tableIV.csv",
            "status": "available",
        },
        {
            "claim": "Scenario/K scalability uses 100-iteration budgets.",
            "artifact": "results/paper_final/scalability_extended_summary.csv; results/paper_final/k_scaling_summary.csv",
            "status": "available_for_checked_in_10x10_support",
        },
        {
            "claim": "Scenario supports larger than 10x10 are solved.",
            "artifact": "results/paper_final/scenario_generation_manifest.json",
            "status": (
                f"available_synthetic_stress_up_to_{max_a}x{max_b}"
                if max_a > 10 or max_b > 10
                else "blocked_runtime_csv_has_only_10_scenarios_per_stage"
            ),
        },
        {
            "claim": "A calibrated cost regime satisfies the paper-ready tradeoff gates.",
            "artifact": "results/paper_final/unit_scale_audit.md; results/paper_final/calibration_screening_matrix.csv",
            "status": "screened_but_not_yet_certified",
        },
        {
            "claim": "The current plan pool can support the deterministic robustness gate after cost-scale calibration.",
            "artifact": "results/paper_final/plan_pool_cross_evaluation.csv",
            "status": "requires_calibration_screening_pass_and_certified_rerun",
        },
        {
            "claim": "Tight-epsilon calibrated Benders currently produces reliable first-stage disaster cuts.",
            "artifact": "results/paper_final/cut_pathology_report.md",
            "status": "blocked_by_zero_first_stage_cut_sensitivity",
        },
    ]
    _write_csv(PAPER_ROOT / "claim_to_artifact_trace.csv", rows, ["claim", "artifact", "status"])


def _write_audit_and_critic(
    table_iii: Sequence[Mapping[str, Any]],
    table_iv: Sequence[Mapping[str, Any]],
    deterministic_rows: Sequence[Mapping[str, Any]],
    scenario_rows: Sequence[Mapping[str, Any]],
    k_rows: Sequence[Mapping[str, Any]],
) -> None:
    proposed = next(row for row in table_iii if row["case_id"] == "Case 1")
    normal = next(row for row in table_iii if row["case_id"] == "Case 2")
    deterministic = next(row for row in table_iii if row["case_id"] == "Case 4")
    phi_ratio = _pct(float(proposed["Phi_dis"]), float(proposed["Psi_nor"]))
    det_reduction = float(deterministic_rows[0]["reduction_pct_det_minus_prop"])
    max_a = max(int(row["A"]) for row in scenario_rows) if scenario_rows else 0
    max_b = max(int(row["B"]) for row in scenario_rows) if scenario_rows else 0
    max_k = max(int(row["K"]) for row in k_rows) if k_rows else 0
    screening_path = PAPER_ROOT / "calibration_screening_matrix.csv"
    screening_rows = _read_csv(screening_path) if screening_path.exists() else []
    screening_pass = any(str(row.get("passes_all_screening_gates", "")).lower() == "true" for row in screening_rows)

    checks = {
        "component_complete": all(
            all(field in row for field in ("F_trans", "F_unmet", "F_sub", "Psi_nor", "Phi_dis"))
            for row in [*table_iii, *table_iv]
        ),
        "common_evaluator_A10_B10_K2": all(
            int(row["common_eval_A"]) == 10 and int(row["common_eval_B"]) == 10 and int(row["common_eval_K"]) == 2
            for row in table_iii
        ),
        "deterministic_strong_claim_supported": det_reduction >= 20.0,
        "disaster_term_material_for_proposed": phi_ratio >= 1.0,
        "scenario_scaling_reaches_requested_large_support": max_a >= 20 and max_b >= 20,
        "k_scaling_reaches_10": max_k >= 10,
        "main_runs_use_100_iteration_budget": all(
            int(row.get("max_iteration_budget") or 0) >= 100
            for row in scenario_rows
            if row["mode"] in {"integrated", "deterministic"}
        ),
        "proposed_not_identical_to_normal_in_capacity": (
            int(proposed["slow_chargers"]) != int(normal["slow_chargers"])
            or int(proposed["fast_chargers"]) != int(normal["fast_chargers"])
        ),
        "proposed_not_identical_to_deterministic_in_capacity": (
            int(proposed["slow_chargers"]) != int(deterministic["slow_chargers"])
            or int(proposed["fast_chargers"]) != int(deterministic["fast_chargers"])
        ),
        "calibration_screening_has_candidate": screening_pass,
    }
    pass_all = all(checks.values())
    audit = {
        "paper_readiness_audit": "PASS" if pass_all else "FAIL",
        "checks": checks,
        "key_metrics": {
            "proposed_phi_over_psi_percent": phi_ratio,
            "deterministic_phi_reduction_percent_det_minus_prop": det_reduction,
            "max_scenario_support_solved": {"A": max_a, "B": max_b},
            "max_K_solved": max_k,
            "calibration_screening_pass_candidates": sum(
                1
                for row in screening_rows
                if str(row.get("passes_all_screening_gates", "")).lower() == "true"
            ),
        },
    }
    _write_json(PAPER_ROOT / "paper_readiness_audit.json", audit)

    failures = [name for name, value in checks.items() if not value]
    audit_md = [
        "# Paper Readiness Audit",
        "",
        f"Result: **{audit['paper_readiness_audit']}**",
        "",
        "## Blocking checks",
        *[f"- {name}: {'PASS' if value else 'FAIL'}" for name, value in checks.items()],
        "",
        "## Interpretation",
        (
            "- The current artifacts are now component-complete and comparable under a common evaluator, "
            "but they still do not support a strong final paper claim."
        ),
        (
            f"- Proposed Phi/Psi = {phi_ratio:.3f}%, deterministic reduction (deterministic minus proposed) = "
            f"{det_reduction:.2f}%."
        ),
        f"- Largest checked scenario support is {max_a}x{max_b}; largest K is {max_k}.",
        f"- Plan-pool calibration pass candidates: {audit['key_metrics']['calibration_screening_pass_candidates']}.",
    ]
    (PAPER_ROOT / "paper_readiness_audit.md").write_text("\n".join(audit_md) + "\n", encoding="utf-8")

    critic_status = "PASS" if not failures else "FAIL"
    required_remediation = [
        "Use the plan-pool screening matrix to identify a scale regime that passes materiality, tradeoff, and deterministic robustness before launching another full integrated run.",
        "Strengthen or warm-start the master MIP under calibrated cost scales; the current cost-scale calibration candidates did not produce summary rows within a practical diagnostic window.",
        "Calibrate the disaster penalty/ambiguity regime so Phi_dis is economically material without producing extreme plans.",
        "Re-run proposed and deterministic under the calibrated common evaluator and require at least 20% deterministic worst-distribution reduction before making the strong DRO claim.",
    ]
    if not checks["scenario_scaling_reaches_requested_large_support"]:
        required_remediation.insert(
            0,
            "Generate and validate larger scenario support before claiming 20x20, 50x20, or 50x50 scalability.",
        )
    critic = {
        "critic_review": critic_status,
        "blocking_failures": failures,
        "diagnosis": [
            "The rewritten section follows the main-paper case-study structure and no longer compares incomparable aggregate objectives.",
            "The current numeric evidence still fails the strong DRO robustness story if deterministic is not worse under the common worst-distribution evaluator.",
            (
                f"Scenario scaling currently reaches {max_a}x{max_b}; rows beyond the base 10x10 support "
                "come from the documented synthetic scenario generator."
            ),
            "Calibration attempts that made the disaster term economically material exposed a master-solve bottleneck before producing a certified candidate.",
            "The plan-pool calibration screen is now explicit; a passing screen candidate is required before expensive certified reruns are promoted.",
        ],
        "required_remediation": required_remediation,
    }
    _write_json(PAPER_ROOT / "critic_review.json", critic)
    critic_md = [
        "# Critic Review",
        "",
        f"Result: **{critic_status}**",
        "",
        "## Blocking failures",
        *(f"- {failure}" for failure in failures),
        "",
        "## Diagnosis",
        *(f"- {item}" for item in critic["diagnosis"]),
        "",
        "## Required remediation",
        *(f"- {item}" for item in critic["required_remediation"]),
    ]
    (PAPER_ROOT / "critic_review.md").write_text("\n".join(critic_md) + "\n", encoding="utf-8")


def _tex_table_component(rows: Sequence[Mapping[str, Any]], *, include_case4: bool = True) -> str:
    selected = list(rows) if include_case4 else [row for row in rows if row["case_id"] != "Case 4"]
    cols = "l" + "r" * len(selected)
    headers = " & ".join([r"Obj. (\$)"] + [_latex_escape(str(row["case_id"])) for row in selected])
    body_rows = []
    labels = [
        (r"$F^{\mathrm{cons}}$", "F_cons"),
        (r"$F^{\mathrm{trans}}$", "F_trans"),
        (r"$F^{\mathrm{unmet}}$", "F_unmet"),
        (r"$F^{\mathrm{sub}}$", "F_sub"),
        (r"$\Psi^{\mathrm{nor}}$", "Psi_nor"),
        (r"$\Phi^{\mathrm{dis}}$", "Phi_dis"),
        (r"$J_{\mathrm{eval}}$", "J_common"),
    ]
    for label, field in labels:
        body_rows.append(label + " & " + " & ".join(_fmt(float(row[field]), 2) for row in selected) + r" \\")
    body_rows.append("Sites & " + " & ".join(str(row["sites"]) for row in selected) + r" \\")
    body_rows.append("Slow/Fast EVSE & " + " & ".join(f"{row['slow_chargers']}/{row['fast_chargers']}" for row in selected) + r" \\")
    body_rows.append("Critical coverage & " + " & ".join(str(row["critical_bus_coverage"]) for row in selected) + r" \\")
    return "\n".join(
        [
            rf"\begin{{tabular}}{{{cols}}}",
            r"\toprule",
            headers + r" \\",
            r"\midrule",
            *body_rows,
            r"\bottomrule",
            r"\end{tabular}",
        ]
    )


def _tex_scalability_table(rows: Sequence[Mapping[str, Any]], limit: int = 20) -> str:
    selected = list(rows)[:limit]
    lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"Run & $|A|$ & $|B|$ & $K$ & Iter. & Viol. \\",
        r"\midrule",
    ]
    for row in selected:
        lines.append(
            f"{_latex_escape(str(row['mode']))} & {row['A']} & {row['B']} & {row['K']} & "
            f"{row['iterations_used']} & {_fmt(row['final_violation'], 1)} " + r"\\"
        )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines)


def _write_main_paper_blueprint() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    text = """# Main Paper Style Blueprint

This blueprint is distilled from `reference/main_paper.pdf` and is used as the
style lock for the EVCS DRO experiment section.

## Experimental Setup Pattern

- State the IEEE 33-node feeder, critical/non-critical buses, EV regions, charger
  types, planning horizon, and disaster horizon.
- Explain scenario profiles before giving optimization results: normal load,
  normal EV charging demand, disaster EV discharging availability, and line
  outage ambiguity.
- Include a Table-II-style parameter table with units.
- Report solver, implementation language, CPU, and RAM.

## Benchmark Pattern

- Case 1: proposed integrated planning.
- Case 2: normal-operation-only planning.
- Case 3: disaster-resilience-only planning.
- Case 4: deterministic/mean-value planning.
- Use Fig.-6/Fig.-7-style planning maps before discussing component costs.
- Use Table-III-style components: Fcons, Ftrans, Funmet, Fsub, Psi_nor, Phi_dis.

## Analysis Pattern

- Compare first-stage layout and charger mix before objective interpretation.
- Compare proposed vs normal-only as a normal-cost sacrifice for resilience gain.
- Compare proposed vs disaster-only as a resilience-only design that may harm
  daily service quality.
- Compare proposed vs deterministic as a small deterministic economy gain versus
  a worst-distribution resilience loss.
- EV sensitivity must reuse the same component taxonomy and explain capacity
  expansion, unmet demand, transport cost, substation cost, and Phi_dis.

## DRO Extension Required Here

- All cross-case claims must use a common ex-post evaluator.
- Report the scenario support size and K explicitly.
- Separate certified main rows from diagnostic stress rows.
- If deterministic is not worse under the common worst-distribution evaluator,
  the strong DRO robustness claim must be blocked or rewritten.
"""
    (DOCS_DIR / "main_paper_style_blueprint.md").write_text(text, encoding="utf-8")


def _write_ieee_section(
    table_iii: Sequence[Mapping[str, Any]],
    table_iv: Sequence[Mapping[str, Any]],
    deterministic_rows: Sequence[Mapping[str, Any]],
    scenario_rows: Sequence[Mapping[str, Any]],
    k_rows: Sequence[Mapping[str, Any]],
) -> None:
    proposed = next(row for row in table_iii if row["case_id"] == "Case 1")
    normal = next(row for row in table_iii if row["case_id"] == "Case 2")
    disaster = next(row for row in table_iii if row["case_id"] == "Case 3")
    deterministic = next(row for row in table_iii if row["case_id"] == "Case 4")
    ev15 = next(row for row in table_iv if row["case_id"] == "EV 1.5x")
    ev20 = next(row for row in table_iv if row["case_id"] == "EV 2.0x")

    delta_psi = float(proposed["Psi_nor"]) - float(normal["Psi_nor"])
    delta_phi = float(normal["Phi_dis"]) - float(proposed["Phi_dis"])
    det_phi_delta = float(deterministic["Phi_dis"]) - float(proposed["Phi_dis"])
    det_phi_pct = _pct(det_phi_delta, float(deterministic["Phi_dis"]))
    ev15_charger_growth = int(ev15["total_chargers"]) - int(proposed["total_chargers"])
    ev20_charger_growth = int(ev20["total_chargers"]) - int(proposed["total_chargers"])
    max_a = max(int(row["A"]) for row in scenario_rows) if scenario_rows else 0
    max_b = max(int(row["B"]) for row in scenario_rows) if scenario_rows else 0
    max_k = max(int(row["K"]) for row in k_rows) if k_rows else 0

    section = rf"""\section{{Case Studies}}
\subsection{{Experimental Setup}}
The numerical study is conducted on the IEEE 33-node radial distribution
system. The feeder is divided into critical and non-critical buses according to
the same critical-load map used in the model input, and candidate EV charging
stations may install slow and fast EVSEs subject to the per-site upper bounds in
Table~\ref{{tab:setup_parameters}}. The normal-operation stage represents
daily charging service over the 24-hour horizon, whereas the disaster stage
represents the 10:00--14:00 emergency operating window in which available EV
discharging capability can support critical loads. The common evaluator used
for the main comparison contains $|A|=10$ normal scenarios, $|B|=10$ disaster
operating scenarios, and outage budget $K=2$.

\begin{{table}}[t]
\centering
\caption{{Main model parameters used in the paper-final artifact pack.}}
\label{{tab:setup_parameters}}
\input{{docs/analysis_packs/setup_parameter_table_input.tex}}
\end{{table}}

\subsection{{Scenario Generation and Uncertainty Support}}
The normal scenarios $a\in A$ describe load and EV charging-demand profiles,
while the disaster scenarios $b\in B$ describe post-disaster load and available
V2G discharging profiles. The line outage uncertainty is not represented by a
single sampled scenario. Instead, it is controlled by the ambiguity set and the
budget $K$, which selects the active outage pattern in the separation problem.
Figs.~\ref{{fig:scenario_profiles}}(a)--(c) show the same role as the load,
charging, and discharging profile figures in the reference paper: they make the
operating profiles visible before optimization results are interpreted.

\begin{{figure*}}[t]
\centering
\includegraphics[width=0.32\textwidth]{{results/paper_final/figures/scenario_profile_normal_load.png}}
\includegraphics[width=0.32\textwidth]{{results/paper_final/figures/scenario_profile_normal_ev.png}}
\includegraphics[width=0.32\textwidth]{{results/paper_final/figures/scenario_profile_disaster_ev.png}}
\caption{{Representative scenario profiles: normal load, normal EV charging
demand, and disaster-stage EV discharging availability.}}
\label{{fig:scenario_profiles}}
\end{{figure*}}

The base runtime data contain ten normal and ten disaster scenarios. To test
larger support sizes, an additional synthetic support was generated from the
base profiles using a fixed seed and bounded multiplicative perturbations across
scenario, time, and region. The resulting stress-test data contain 100 normal
and 100 disaster scenarios. Therefore, the component comparison below remains on
the audited $10\times 10$ common evaluator, while the scalability subsection
separately reports large-support stress rows up to ${max_a}\times {max_b}$.

\subsection{{Benchmark Definitions}}
Four planning cases are evaluated. Case~1 is the proposed integrated model,
which optimizes investment, normal-operation recourse, and disaster-stage DRO
recourse jointly. Case~2 removes the disaster term and represents a
normal-operation-only planning benchmark. Case~3 uses the disaster-oriented
planning result as a diagnostic resilience-only benchmark and is replayed under
the same normal-operation evaluator to reveal its daily-service consequence.
Case~4 replaces the sampled second-stage support by a mean-value representation
when planning, and the resulting plan is replayed under the same common
worst-distribution evaluator as Case~1. This replay rule is essential: the
comparisons below do not compare each case under its own training objective.

\subsection{{Default Component Comparison}}
Fig.~\ref{{fig:default_maps}} gives the first-stage plans for the integrated,
normal-only, and disaster-only designs, while Table~\ref{{tab:default_components}}
reports the common-evaluator objective components. Under the current
artifact pack, Case~1 and Case~2 have nearly identical station counts and charger
composition: Case~1 installs {proposed['sites']} sites with
{proposed['slow_chargers']}/{proposed['fast_chargers']} slow/fast EVSEs, while
Case~2 installs {normal['sites']} sites with {normal['slow_chargers']}/{normal['fast_chargers']}
slow/fast EVSEs. This means the present parameter regime does not yet produce a
strong layout-level tradeoff between daily economy and resilience.

\begin{{figure*}}[t]
\centering
\includegraphics[width=0.9\textwidth]{{results/paper_final/figures/fig6_like_plan_maps.png}}
\caption{{Planning maps for the proposed integrated, normal-only, and
disaster-only cases.}}
\label{{fig:default_maps}}
\end{{figure*}}

\begin{{table*}}[t]
\centering
\caption{{Objective components under the common $|A|=10$, $|B|=10$, $K=2$
evaluator.}}
\label{{tab:default_components}}
{_tex_table_component(table_iii)}
\end{{table*}}

The component table also changes the interpretation of the result. Case~1
increases $\Psi^{{\rm nor}}$ relative to Case~2 by {_fmt(delta_psi, 2)}, while
the replayed disaster score changes by {_fmt(delta_phi, 2)} in favor of Case~1
when positive. A paper-ready tradeoff would require a modest increase in
normal-operation cost to purchase a material decrease in $\Phi^{{\rm dis}}$.
The current numbers are not yet strong enough for that claim: $\Phi^{{\rm dis}}$
is small relative to $\Psi^{{\rm nor}}$, and the normal-only and integrated
plans remain too similar. Case~3 gives a useful diagnostic contrast: its common
normal-operation replay produces $\Psi^{{\rm nor}}={_fmt(float(disaster['Psi_nor']), 2)}$,
which is much worse than Case~1 because the resilience-only plan is not designed
to serve daily charging demand economically.

\subsection{{Deterministic Worst-Distribution Comparison}}
The deterministic benchmark is the central DRO comparison. Table~\ref{{tab:det_worst}}
freezes the Case~1 and Case~4 plans and evaluates both under the same
$|A|=10$, $|B|=10$, $K=2$ separation evaluator. Case~4 saves construction cost
relative to Case~1 ({_fmt(float(proposed['F_cons']) - float(deterministic['F_cons']), 2)})
and also changes the charger plan from {proposed['slow_chargers']}/{proposed['fast_chargers']}
to {deterministic['slow_chargers']}/{deterministic['fast_chargers']}. However,
the current worst-distribution replay gives a deterministic-minus-proposed
$\Phi^{{\rm dis}}$ difference of {_fmt(det_phi_delta, 2)} ({det_phi_pct:.2f}\%).
Since this is below the required 20\% robustness margin, the strong statement
that the DRO plan dominates the deterministic plan under the worst distribution
is not supported by the present artifact pack.

\begin{{figure}}[t]
\centering
\includegraphics[width=0.48\textwidth]{{results/paper_final/figures/fig7_like_plan_map.png}}
\caption{{Deterministic mean-value planning map.}}
\label{{fig:det_map}}
\end{{figure}}

\begin{{table}}[t]
\centering
\caption{{Proposed and deterministic plans under the common worst-distribution
evaluator.}}
\label{{tab:det_worst}}
\begin{{tabular}}{{lrr}}
\toprule
Metric & Proposed & Deterministic \\
\midrule
$\Phi^{{\rm dis}}$ & {_fmt(float(proposed['Phi_dis']), 2)} & {_fmt(float(deterministic['Phi_dis']), 2)} \\
$\pi_f\Phi^{{\rm dis}}$ & {_fmt(float(proposed['pi_f']) * float(proposed['Phi_dis']), 2)} & {_fmt(float(deterministic['pi_f']) * float(deterministic['Phi_dis']), 2)} \\
Active outage lines & \multicolumn{{2}}{{c}}{{see CSV support file}} \\
\bottomrule
\end{{tabular}}
\end{{table}}

\subsection{{EV Penetration Sensitivity}}
Cases~5 and 6 scale the EV charging and discharging profiles to 1.5 and 2.0
times the base level. Table~\ref{{tab:ev_components}} and Fig.~\ref{{fig:ev_maps}}
show that the model expands capacity monotonically: total installed EVSEs
increase by {ev15_charger_growth} at 1.5$\times$ penetration and by
{ev20_charger_growth} at 2.0$\times$ penetration. The increase is mainly visible
in $F^{{\rm cons}}$, $F^{{\rm trans}}$, and $F^{{\rm sub}}$, which is physically
consistent with higher charging demand and larger served energy. The common
replay also keeps $F^{{\rm unmet}}$ small in the base and high-penetration cases,
so the capacity expansion is serving demand rather than hiding shortage through
unmet-demand penalties.

\begin{{figure*}}[t]
\centering
\includegraphics[width=0.86\textwidth]{{results/paper_final/figures/fig8_like_sensitivity_maps.png}}
\caption{{Planning maps under EV penetration sensitivity.}}
\label{{fig:ev_maps}}
\end{{figure*}}

\begin{{table*}}[t]
\centering
\caption{{EV penetration sensitivity under the same component taxonomy.}}
\label{{tab:ev_components}}
{_tex_table_component(table_iv)}
\end{{table*}}

\subsection{{Scalability and Convergence}}
The scalability study uses a 100-iteration budget for Benders/DRO runs. Scenario
scaling is tested on both the base support and the synthetic extension, reaching
$|A|={max_a}$ and $|B|={max_b}$ in the generated stress pack; $K$ scaling reaches
10 on the $10\times 10$ support. Table~\ref{{tab:scenario_scaling}} summarizes
the scenario-support runs, and Fig.~\ref{{fig:scale_plots}} visualizes the
scenario and $K$ trends. Most certified rows terminate before exhausting the
100-iteration budget because the final separation violation is below the
configured epsilon-certificate threshold. These rows support bounded convergence
claims for the tested supports, while the generated large-scenario rows should
be described as reproducible stress tests rather than field-measured historical
scenarios.

\begin{{table}}[t]
\centering
\caption{{Scenario scaling summary from the checked-in runtime support.}}
\label{{tab:scenario_scaling}}
{_tex_scalability_table([row for row in scenario_rows if row['mode'] in ('integrated', 'deterministic')])}
\end{{table}}

\begin{{figure*}}[t]
\centering
\includegraphics[width=0.48\textwidth]{{results/paper_final/figures/paper_scale_matrix_scenario_scaling.png}}
\includegraphics[width=0.48\textwidth]{{results/paper_final/figures/paper_scale_matrix_k_scaling.png}}
\caption{{Scenario-support and outage-budget scaling diagnostics.}}
\label{{fig:scale_plots}}
\end{{figure*}}

The $K$-scaling rows reach $K={max_k}$ on the $10\times 10$ support. As $K$
increases, the number of generated cuts and the number of Benders iterations
increase for the deterministic runs more clearly than for the proposed runs,
which is consistent with a larger outage ambiguity set requiring additional
supporting cuts. However, because $\Phi^{{\rm dis}}$ is still too small relative
to $\Psi^{{\rm nor}}$, these rows should be interpreted as algorithmic
diagnostics rather than final economic evidence.

\subsection{{Limitations and Claim Boundary}}
This experiment-section revision fixes the main reporting problem: the tables
now expose $F^{{\rm trans}}$, $F^{{\rm unmet}}$, $F^{{\rm sub}}$, $\Psi^{{\rm nor}}$,
and $\Phi^{{\rm dis}}$ under a common evaluator. It also makes the deterministic
comparison explicit and adds generated large-support scalability evidence.
Nevertheless, the current artifacts are not yet final paper-ready evidence. The
deterministic worst-distribution comparison does not deliver the required 20\%
robustness advantage, and the disaster term remains too small relative to
normal-operation cost to support the strongest tradeoff story. The unit audit
and plan-pool screening artifacts identify this as a scale-and-optimization
problem rather than a writing problem: the recommended $C^{{\rm pur}}$ and
$C^{{\rm trans}}$ rescalings can restore paper-style component magnitudes, but a
certified integrated optimization must still demonstrate that the proposed plan
beats the deterministic plan under the same worst-distribution evaluator. The
next experimental iteration must therefore use the calibrated scale, warm-start
the master problem from the existing plan pool, and re-run the common evaluator
before this section can be promoted from a rigorous diagnostic write-up to the
final IEEE case study.
"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "ieee_experiment_section.tex").write_text(section, encoding="utf-8")

    setup_input = "\n".join(
        [
            r"\resizebox{\columnwidth}{!}{%",
            r"\begin{tabular}{lll}",
            r"\toprule",
            r"Symbol & Description & Value \\",
            r"\midrule",
            *[
                f"{_latex_escape(row['symbol'])} & {_latex_escape(row['description'])} & "
                f"{_latex_escape(row['value'])} {_latex_escape(row['unit'])} \\\\"
                for row in _read_csv(PAPER_ROOT / "setup_parameter_table.csv")
            ],
            r"\bottomrule",
            r"\end{tabular}",
            r"}",
        ]
    )
    (DOCS_DIR / "setup_parameter_table_input.tex").write_text(setup_input, encoding="utf-8")

    standalone = "\n".join(
        [
            r"\documentclass[conference]{IEEEtran}",
            r"\usepackage{graphicx}",
            r"\usepackage{booktabs}",
            r"\usepackage{amsmath}",
            r"\begin{document}",
            r"\input{docs/analysis_packs/ieee_experiment_section.tex}",
            r"\end{document}",
        ]
    )
    (DOCS_DIR / "ieee_experiment_section_standalone.tex").write_text(
        standalone,
        encoding="utf-8",
    )


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    _write_main_paper_blueprint()
    _write_setup_and_scenario_artifacts()
    table_iii, table_iv = _write_component_tables()
    _write_unit_scale_audit(table_iii)
    _write_plan_pool_screening()
    _plot_component_figures(table_iii, table_iv)
    scenario_rows, k_rows = _write_scalability_tables()
    deterministic_rows = _write_deterministic_comparison(table_iii)
    _write_claim_trace()
    _write_audit_and_critic(table_iii, table_iv, deterministic_rows, scenario_rows, k_rows)
    _write_ieee_section(table_iii, table_iv, deterministic_rows, scenario_rows, k_rows)
    print("Generated paper-final analysis artifacts under results/paper_final and docs/analysis_packs.")


if __name__ == "__main__":
    main()
