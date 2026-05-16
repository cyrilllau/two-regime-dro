"""Audit an auxiliary-trial pricing-UB certificate.

This script implements the Pro-reviewed certificate semantics:
an auxiliary serious-step point may provide a valid sampled-DRO upper bound,
but it is paper-facing gap-certified only if the pricing-derived UB and
canonical RMP LB close the requested objective gap.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import (  # noqa: E402
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from scripts.run_full_benders_scalability import CRITICAL_BUSES  # noqa: E402
from src.production.first_stage import (  # noqa: E402
    build_first_stage_model,
    extract_first_stage_solution,
)
from src.production.normal_block import (  # noqa: E402
    build_normal_operation_block,
    extract_normal_operation_solution,
)
from src.production.separation_milp import solve_separation_milp  # noqa: E402
from src.reference.disaster_primal_ref import (  # noqa: E402
    FixedFirstStagePlan,
    build_fixed_first_stage_plan,
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _stable_hash(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _trial_plan(certificate: Mapping[str, Any]) -> FixedFirstStagePlan:
    first_stage = dict(certificate.get("first_stage_plan", {}))
    return FixedFirstStagePlan(
        z_by_bus={
            int(bus): int(value)
            for bus, value in dict(first_stage.get("z_by_bus", {})).items()
        },
        n_sl_by_bus={
            int(bus): int(value)
            for bus, value in dict(first_stage.get("n_sl_by_bus", {})).items()
        },
        n_fa_by_bus={
            int(bus): int(value)
            for bus, value in dict(first_stage.get("n_fa_by_bus", {})).items()
        },
    )


def _fix_first_stage(
    instance,
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


def _replay_normal_objective(instance, plan: FixedFirstStagePlan) -> dict[str, Any]:
    first_stage = _fix_first_stage(
        instance,
        plan,
        attach_objective=True,
        model_name="pricing_ub_audit_construction",
    )
    first_stage.model.optimize()
    first_stage_solution = extract_first_stage_solution(first_stage)
    if first_stage_solution.model_status != "OPTIMAL":
        raise RuntimeError("Fixed construction replay did not solve.")

    normal_cost_by_scenario: dict[int, float] = {}
    for scenario_id in instance.sets.loaded_normal_scenarios:
        fixed = _fix_first_stage(
            instance,
            plan,
            attach_objective=False,
            model_name=f"pricing_ub_audit_normal_s{scenario_id}",
        )
        block = build_normal_operation_block(
            instance,
            first_stage=fixed,
            scenario_id=int(scenario_id),
            model_name=f"pricing_ub_audit_normal_s{scenario_id}",
            log_to_console=False,
            attach_objective=True,
        )
        block.model.optimize()
        solution = extract_normal_operation_solution(block)
        if solution.model_status != "OPTIMAL":
            raise RuntimeError(f"Fixed normal replay failed for scenario {scenario_id}.")
        normal_cost_by_scenario[int(scenario_id)] = float(solution.normal_objective_value)
    averaged_normal = float(
        (1.0 - float(instance.economics.pi_f))
        / len(instance.sets.loaded_normal_scenarios)
        * sum(normal_cost_by_scenario.values())
    )
    return {
        "construction_cost": float(first_stage_solution.construction_cost_value),
        "averaged_normal_cost": averaged_normal,
        "unweighted_average_normal_cost": float(
            sum(normal_cost_by_scenario.values()) / len(normal_cost_by_scenario)
        ),
        "normal_cost_by_scenario": {
            str(key): float(value) for key, value in sorted(normal_cost_by_scenario.items())
        },
    }


def _lambda_fp(instance, lambda_by_line_id: Mapping[str, float]) -> float:
    p_bar = [float(value) for value in instance.ambiguity.p_bar]
    line_ids = [str(value) for value in instance.sets.line_ids]
    return float(
        sum(float(lambda_by_line_id[str(line_id)]) * p_bar[index] for index, line_id in enumerate(line_ids))
    )


def _replay_full_pricing(
    instance,
    plan: FixedFirstStagePlan,
    certificate: Mapping[str, Any],
    *,
    omega_upper: float,
    time_limit_seconds: float,
    mip_gap: float,
) -> dict[str, Any]:
    omega_bounds = {str(line_id): (0.0, float(omega_upper)) for line_id in instance.sets.line_ids}
    _, solution = solve_separation_milp(
        instance,
        plan=plan,
        alpha=float(certificate["alpha"]),
        lambda_by_line_id={
            str(line_id): float(value)
            for line_id, value in dict(certificate["lambda_by_line_id"]).items()
        },
        omega_bounds_by_line_id=omega_bounds,
        budget_k=int(instance.ambiguity.k_max_outages),
        scenario_ids=instance.sets.loaded_disaster_scenarios,
        model_name="pricing_ub_audit_full_support_separation",
        time_limit_seconds=float(time_limit_seconds),
        mip_gap=float(mip_gap),
        require_optimal=False,
        log_to_console=False,
    )
    return {
        "pricing_support": "full_B_full_Omega",
        "separation_model_status": str(solution.model_status),
        "separation_objval": (
            None if solution.objective_value is None else float(solution.objective_value)
        ),
        "separation_objbound": (
            None if solution.obj_bound is None else float(solution.obj_bound)
        ),
        "separation_mip_gap": None if solution.mip_gap is None else float(solution.mip_gap),
        "separation_node_count": solution.node_count,
        "pricing_violation_value": max(0.0, float(solution.objective_value or 0.0)),
        "pricing_violation_bound": max(
            0.0,
            float(
                solution.obj_bound
                if solution.obj_bound is not None
                else (solution.objective_value or 0.0)
            ),
        ),
        "separation_reconstruction_gap": float(solution.reconstruction_gap),
        "selected_outage_by_line_id": {
            str(line_id): int(value)
            for line_id, value in sorted(solution.delta_by_line_id.items())
        },
    }


def _test(name: str, passed: bool, *, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": str(detail)}


def audit_certificate(args: argparse.Namespace) -> dict[str, Any]:
    run_log_path = Path(args.run_log)
    run_log = _read_json(run_log_path)
    cert_path_raw = args.trial_certificate or run_log.get("artifact_paths", {}).get(
        "trial_certificate_path"
    )
    if not cert_path_raw:
        raise RuntimeError("No trial certificate path provided or present in run log.")
    cert_path = Path(cert_path_raw)
    certificate = _read_json(cert_path)
    critical_buses = load_critical_buses(args.critical_buses)
    run_config = dict(run_log["run_config"])
    base_instance = load_instance_for_run(run_config, critical_buses=critical_buses)
    instance = prepare_instance_for_run(base_instance, run_config)
    plan = _trial_plan(certificate)
    # Normalize the trial plan through the canonical builder to catch missing buses.
    plan = build_fixed_first_stage_plan(
        instance,
        z_by_bus=plan.z_by_bus,
        n_sl_by_bus=plan.n_sl_by_bus,
        n_fa_by_bus=plan.n_fa_by_bus,
    )

    normal_replay = _replay_normal_objective(instance, plan)
    pricing_replay = _replay_full_pricing(
        instance,
        plan,
        certificate,
        omega_upper=float(args.omega_bound_upper),
        time_limit_seconds=float(args.separation_time_limit_seconds),
        mip_gap=float(args.separation_mip_gap),
    )
    objective_multipliers = instance.economics.objective_multipliers
    lambda_fp_value = _lambda_fp(instance, certificate["lambda_by_line_id"])
    disaster_surrogate = float(instance.economics.pi_f) * (
        float(certificate["alpha"]) + float(lambda_fp_value)
    )
    replay_unpenalized = float(
        objective_multipliers.cons * normal_replay["construction_cost"]
        + objective_multipliers.normal * normal_replay["averaged_normal_cost"]
        + objective_multipliers.disaster * disaster_surrogate
    )
    pricing_ub_addition = float(objective_multipliers.disaster) * float(
        instance.economics.pi_f
    ) * max(0.0, float(pricing_replay["pricing_violation_bound"]))
    pricing_ub = float(replay_unpenalized + pricing_ub_addition)
    canonical_lb = float(certificate["canonical_lower_bound"])
    pricing_gap = max(0.0, pricing_ub - canonical_lb)
    epsilon_cert = float(certificate.get("epsilon_cert", run_config["benders"].get("epsilon_cert", 0.0)))
    epsilon_gap = float(args.epsilon_gap if args.epsilon_gap is not None else epsilon_cert)
    plan_payload = certificate.get("first_stage_plan", {})
    alpha_lambda_payload = {
        "alpha": float(certificate["alpha"]),
        "lambda_by_line_id": {
            str(line_id): float(value)
            for line_id, value in sorted(dict(certificate["lambda_by_line_id"]).items())
        },
    }

    tests = [
        _test(
            "auxiliary_not_used_for_lower_bound",
            not bool(certificate.get("auxiliary_used_for_lower_bound", True)),
        ),
        _test(
            "canonical_lb_source_safe",
            str(certificate.get("canonical_model_status")) == "OPTIMAL"
            and abs(
                float(certificate.get("canonical_lower_bound", 0.0))
                - float(certificate.get("canonical_master_objective", certificate.get("canonical_rmp_objval", 0.0)))
            )
            <= float(args.objective_tolerance),
            detail="OPTIMAL canonical solve uses ObjVal; non-optimal runs must use ObjBound.",
        ),
        _test(
            "plan_hash_matches_if_present",
            not certificate.get("plan_hash")
            or str(certificate["plan_hash"]) == _stable_hash(plan_payload),
        ),
        _test(
            "alpha_lambda_hash_matches_if_present",
            not certificate.get("alpha_lambda_hash")
            or str(certificate["alpha_lambda_hash"]) == _stable_hash(alpha_lambda_payload),
        ),
        _test(
            "normal_recourse_replayed",
            replay_unpenalized <= float(certificate["unpenalized_candidate_objective"])
            + float(args.objective_tolerance),
            detail=(
                f"replay_unpenalized={replay_unpenalized}, "
                f"stored={certificate['unpenalized_candidate_objective']}"
            ),
        ),
        _test(
            "full_support_pricing_replayed",
            pricing_replay["pricing_support"] == "full_B_full_Omega"
            and str(pricing_replay["separation_model_status"]) == "OPTIMAL",
        ),
        _test(
            "pricing_bound_certifies_trial_feasibility",
            float(pricing_replay["pricing_violation_bound"])
            <= epsilon_cert + float(args.objective_tolerance),
            detail=f"bound={pricing_replay['pricing_violation_bound']}, epsilon_cert={epsilon_cert}",
        ),
        _test(
            "pricing_ub_formula_matches_stored_or_is_tighter",
            pricing_ub
            <= float(certificate["pricing_derived_upper_bound"])
            + float(args.objective_tolerance),
            detail=(
                f"replay_ub={pricing_ub}, stored_ub={certificate['pricing_derived_upper_bound']}"
            ),
        ),
    ]
    oracle_pass = all(row["passed"] for row in tests)
    if oracle_pass and pricing_gap <= epsilon_gap + float(args.objective_tolerance):
        certificate_type = "pricing_ub_gap_certified"
        validation_level = "pricing_ub_gap_certified"
        paper_facing_eligible = True
    elif (
        oracle_pass
        and float(pricing_replay["pricing_violation_bound"])
        <= epsilon_cert + float(args.objective_tolerance)
    ):
        certificate_type = "trial_full_support_feasible_gap_open"
        validation_level = "trial_full_support_feasible_gap_open"
        paper_facing_eligible = False
    else:
        certificate_type = "smoke_only"
        validation_level = "smoke_only"
        paper_facing_eligible = False

    if validation_level == "pricing_ub_gap_certified":
        pro_decision = (
            "Adopt Pro theorem: pricing UB + canonical LB is valid, and this "
            "run is epsilon-gap certified because UB_pricing - LB_canonical "
            "is within the requested tolerance."
        )
        unsafe_claims_rejected = [
            "trial violation alone implies canonical RMP is closed",
            "auxiliary objective is a lower bound",
        ]
    elif validation_level == "trial_full_support_feasible_gap_open":
        pro_decision = (
            "Adopt Pro theorem: pricing UB + canonical LB is valid, but this "
            "run is only trial-feasible because UB_pricing - LB_canonical "
            "does not close the requested epsilon gap."
        )
        unsafe_claims_rejected = [
            "trial violation alone implies canonical RMP is closed",
            "auxiliary objective is a lower bound",
            "trial feasibility implies epsilon-gap certification",
        ]
    else:
        pro_decision = (
            "Adopt Pro theorem: pricing UB + canonical LB is the required "
            "certificate path, but this run did not pass the oracle tests."
        )
        unsafe_claims_rejected = [
            "trial violation alone implies canonical RMP is closed",
            "auxiliary objective is a lower bound",
            "failed oracle tests can support a paper-facing certificate",
        ]

    payload = {
        "run_log_path": str(run_log_path),
        "trial_certificate_path": str(cert_path),
        "pro_response_tex_path": str(args.pro_response_tex),
        "certificate_type": certificate_type,
        "validation_level": validation_level,
        "paper_facing_eligible": paper_facing_eligible,
        "epsilon_cert": epsilon_cert,
        "epsilon_gap": epsilon_gap,
        "canonical_lower_bound": canonical_lb,
        "replay_unpenalized_candidate_objective": replay_unpenalized,
        "stored_unpenalized_candidate_objective": float(
            certificate["unpenalized_candidate_objective"]
        ),
        "pricing_ub_addition": pricing_ub_addition,
        "pricing_derived_upper_bound_replay": pricing_ub,
        "pricing_derived_upper_bound_stored": float(
            certificate["pricing_derived_upper_bound"]
        ),
        "pricing_gap_bound_replay": pricing_gap,
        "pricing_gap_bound_stored": float(certificate["pricing_gap_bound"]),
        "objective_multipliers": {
            "cons": float(objective_multipliers.cons),
            "normal": float(objective_multipliers.normal),
            "disaster": float(objective_multipliers.disaster),
        },
        "pi_f": float(instance.economics.pi_f),
        "support": {
            "A_total": len(instance.sets.loaded_normal_scenarios),
            "B_total": len(instance.sets.loaded_disaster_scenarios),
            "K": int(instance.ambiguity.k_max_outages),
            "normal_scenarios": [int(value) for value in instance.sets.loaded_normal_scenarios],
            "disaster_scenarios": [
                int(value) for value in instance.sets.loaded_disaster_scenarios
            ],
        },
        "normal_replay": normal_replay,
        "pricing_replay": pricing_replay,
        "oracle_tests": tests,
        "pro_adoption": {
            "accepted": True,
            "decision": pro_decision,
            "unsafe_claims_rejected": unsafe_claims_rejected,
        },
    }
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    audit_json = output_root / "pricing_ub_certificate_audit.json"
    _write_json(audit_json, payload)
    audit_md = output_root / "pricing_ub_certificate_audit.md"
    audit_md.write_text(_render_markdown(payload), encoding="utf-8")
    return payload


def _render_markdown(payload: Mapping[str, Any]) -> str:
    tests = payload["oracle_tests"]
    lines = [
        "# Pricing-UB Certificate Audit",
        "",
        f"- Certificate type: `{payload['certificate_type']}`",
        f"- Validation level: `{payload['validation_level']}`",
        f"- Paper-facing eligible: `{payload['paper_facing_eligible']}`",
        f"- Canonical LB: `{payload['canonical_lower_bound']}`",
        f"- Replay pricing UB: `{payload['pricing_derived_upper_bound_replay']}`",
        f"- Replay UB-LB gap: `{payload['pricing_gap_bound_replay']}`",
        f"- Epsilon gap: `{payload['epsilon_gap']}`",
        "",
        "## Oracle Tests",
        "",
        "| Test | Pass | Detail |",
        "|---|---:|---|",
    ]
    for row in tests:
        lines.append(
            f"| `{row['name']}` | `{row['passed']}` | {str(row.get('detail', '')).replace('|', '/')} |"
        )
    lines.extend([
        "",
        "## Pro Adoption",
        "",
        str(payload["pro_adoption"]["decision"]),
        "",
        "Rejected unsafe claims:",
    ])
    for claim in payload["pro_adoption"]["unsafe_claims_rejected"]:
        lines.append(f"- {claim}")
    if payload["validation_level"] == "pricing_ub_gap_certified":
        lines.extend([
            "",
            "Conclusion: this run is paper-facing eligible under the",
            "pricing-UB/canonical-LB gap certificate.",
        ])
    elif payload["validation_level"] == "trial_full_support_feasible_gap_open":
        lines.extend([
            "",
            "Conclusion: this run is trial-feasible but not yet an epsilon-gap",
            "certificate.",
        ])
    else:
        lines.extend([
            "",
            "Conclusion: this run remains diagnostic only.",
        ])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-log",
        default=(
            "results/engineering_acceleration/k16_certificate_closure_120_20260506/runs/"
            "eng_active_set_localbranchzn_A10_B010_K16_top001_max120_pool100_cand20_cuts03_"
            "levelbundle_s5000p0_f0p05_rl1p0_bestviolation_nccg_global_complete05_oldest_"
            "pfpb01_r00_cb10_tol0p0_cs_k0p35_ev0p15_n03/logs/"
            "eng_active_set_localbranchzn_A10_B010_K16_top001_max120_pool100_cand20_cuts03_"
            "levelbundle_s5000p0_f0p05_rl1p0_bestviolation_nccg_global_complete05_oldest_"
            "pfpb01_r00_cb10_tol0p0_cs_k0p35_ev0p15_n03_run.json"
        ),
    )
    parser.add_argument("--trial-certificate", default="")
    parser.add_argument(
        "--pro-response-tex",
        default="/Users/shixinliu/Downloads/evcs_dro_k16_certificate_closure.tex",
    )
    parser.add_argument(
        "--output-root",
        default="results/engineering_acceleration/certificate_closure_k16",
    )
    parser.add_argument("--critical-buses", default=str(CRITICAL_BUSES))
    parser.add_argument("--epsilon-gap", type=float, default=None)
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument("--separation-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.03)
    parser.add_argument("--objective-tolerance", type=float, default=1.0e-4)
    return parser.parse_args()


def main() -> None:
    payload = audit_certificate(parse_args())
    print(json.dumps({
        "certificate_type": payload["certificate_type"],
        "validation_level": payload["validation_level"],
        "pricing_gap_bound_replay": payload["pricing_gap_bound_replay"],
        "paper_facing_eligible": payload["paper_facing_eligible"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
