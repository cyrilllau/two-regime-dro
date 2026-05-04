"""Promote a strict-gate default-scale candidate into paper-facing artifacts."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
from typing import Any, Mapping, Sequence


DEFAULT_CANDIDATE_ID = (
    "ev0p55_cfix1_csl5_cls200x1_pi0p3_cfa0p48_ctr16p0_"
    "cappaper_heterogeneous_headroom_slblk16x10p0_cunmet3p0"
)

CASE_META = {
    "proposed": ("Case 1", "Proposed integrated"),
    "normal": ("Case 2", "Normal-only"),
    "disaster": ("Case 3", "Disaster-only"),
    "deterministic_k2": ("Case 4", "Deterministic mean-value, K_train=2"),
    "deterministic": ("Diagnostic", "Naive deterministic mean-value, K_train=0"),
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _float(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key, "")
    return 0.0 if value in ("", None) else float(value)


def _copy_if_exists(source: Path, destination: Path) -> str:
    if not source.exists():
        return ""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _run_root(source_root: Path, row: Mapping[str, Any]) -> Path:
    return source_root / "runs" / str(row["run_id"])


def _promote_plan_and_logs(
    *,
    source_root: Path,
    paper_root: Path,
    row: Mapping[str, Any],
    case: str,
) -> dict[str, str]:
    run_root = _run_root(source_root, row)
    run_id = str(row["run_id"])
    promoted_id = f"default_scale_v2_{case}"
    plan_path = Path(str(row.get("plan_path", "")))
    if not plan_path.exists():
        plan_candidates = [
            run_root / "plans" / f"{run_id}_final_plan.csv",
            run_root / "plans" / f"{run_id}_plan.csv",
        ]
        plan_path = next((path for path in plan_candidates if path.exists()), Path())

    return {
        "promoted_run_id": promoted_id,
        "promoted_plan_path": _copy_if_exists(
            plan_path,
            paper_root / "plans" / f"{promoted_id}_plan.csv",
        ),
        "promoted_summary_path": _copy_if_exists(
            run_root / "summary.csv",
            paper_root / "logs" / f"{promoted_id}_summary.csv",
        ),
        "promoted_iteration_trace_path": _copy_if_exists(
            run_root / "iteration_trace.csv",
            paper_root / "logs" / f"{promoted_id}_iteration_trace.csv",
        ),
        "promoted_master_trace_path": _copy_if_exists(
            run_root / "master_trace.csv",
            paper_root / "logs" / f"{promoted_id}_master_trace.csv",
        ),
        "source_run_root": str(run_root),
        "source_plan_path": str(plan_path) if plan_path else "",
    }


def _component_row(
    row: Mapping[str, Any],
    *,
    case: str,
    copied: Mapping[str, str],
) -> dict[str, Any]:
    case_id, case_name = CASE_META[case]
    fields = (
        "training_validation_level",
        "training_stop_reason",
        "training_iterations",
        "training_cuts",
        "training_final_violation",
        "training_max_iterations_budget",
        "normal_scenario_count",
        "disaster_scenario_count",
        "K",
        "disaster_evaluator",
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
        "active_outage_lines",
        "separation_status",
        "separation_reconstruction_gap",
        "evaluated_outage_patterns",
    )
    promoted = {
        "case_id": case_id,
        "case_name": case_name,
        "source_case": case,
        "candidate_id": row["candidate_id"],
        "source_run_id": row["run_id"],
        "promoted_run_id": copied["promoted_run_id"],
        "plan_path": copied["promoted_plan_path"],
        "source_plan_path": copied["source_plan_path"],
    }
    promoted.update({field: row.get(field, "") for field in fields})
    return promoted


def _write_decision_card(
    path: Path,
    *,
    candidate_id: str,
    quality: Mapping[str, Any],
    rows_by_case: Mapping[str, Mapping[str, Any]],
) -> None:
    proposed = rows_by_case["proposed"]
    normal = rows_by_case["normal"]
    deterministic = rows_by_case.get("deterministic", {})
    deterministic_k2 = rows_by_case.get("deterministic_k2", {})
    delta_daily = _float(quality, "DeltaDaily")
    delta_resilience = _float(quality, "DeltaResilience")
    lines = [
        "# Default-Scale Candidate Decision Card",
        "",
        f"- Candidate: `{candidate_id}`",
        "- Scale: IEEE 33-bus, `A=10`, `B=10`, `K_eval=2`, evaluator `exact_primal_dro`.",
        f"- Gate result: `{quality.get('passes_all_quality_gates')}`.",
        f"- Proposed certificate: `{proposed.get('training_validation_level')}`, final violation `{proposed.get('training_final_violation')}`.",
        f"- Fair deterministic certificate: `{deterministic_k2.get('training_validation_level')}`, training `K={deterministic_k2.get('training_K')}`.",
        "",
        "## Paper-Style Interpretation",
        "",
        (
            f"Proposed increases the daily/capital reporting metric over normal-only by "
            f"{delta_daily:,.2f}, while reducing the weighted disaster penalty by "
            f"{delta_resilience:,.2f}. The resilience/daily-cost ratio is "
            f"{_float(quality, 'DeltaResilience_over_DeltaDaily'):,.2f}."
        ),
        (
            f"Under the common worst-distribution evaluator, fair deterministic-K2 `Phi` is "
            f"{_float(deterministic_k2, 'Phi_dis'):,.2f} and proposed `Phi` is "
            f"{_float(proposed, 'Phi_dis'):,.2f}, a "
            f"{100.0 * (_float(deterministic_k2, 'Phi_dis') - _float(proposed, 'Phi_dis')) / _float(deterministic_k2, 'Phi_dis'):,.2f}% reduction."
        ),
        (
            f"The proposed plan opens {proposed.get('sites')} stations with "
            f"{proposed.get('slow_chargers')} slow and {proposed.get('fast_chargers')} fast chargers; "
            f"slow-cap saturation share is {_float(quality, 'proposed_sl_cap_site_share_pct'):,.2f}%."
        ),
        "",
        "## Claim Boundary",
        "",
        "- This card certifies the default-scale calibration only.",
        "- EV sensitivity, disaster-only certification, large-scenario scalability, and the final paper section still require their own gates before the full paper pack can be called paper-ready.",
    ]
    if "disaster" in rows_by_case:
        disaster = rows_by_case["disaster"]
        lines.extend(
            [
                "",
                "## Disaster-Only Benchmark",
                "",
                (
                    f"Disaster-only common-eval `Psi` is {_float(disaster, 'Psi_nor'):,.2f} "
                    f"and `Phi` is {_float(disaster, 'Phi_dis'):,.2f}; training certificate is "
                    f"`{disaster.get('training_validation_level')}`."
                ),
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-id", default=DEFAULT_CANDIDATE_ID)
    parser.add_argument("--source-root", default="results/default_scale_calibration")
    parser.add_argument("--paper-root", default="results/paper_final")
    parser.add_argument("--allow-missing-disaster", action="store_true")
    args = parser.parse_args()

    source_root = Path(args.source_root)
    paper_root = Path(args.paper_root)
    rows = [
        row
        for row in _read_csv(source_root / "default_scale_candidate_matrix.csv")
        if row.get("candidate_id") == args.candidate_id
    ]
    quality_rows = [
        row
        for row in _read_csv(source_root / "default_scale_quality_gates.csv")
        if row.get("candidate_id") == args.candidate_id
    ]
    if not quality_rows:
        raise SystemExit(f"No quality row found for {args.candidate_id}")
    quality = quality_rows[-1]
    if str(quality.get("passes_all_quality_gates")) != "True":
        raise SystemExit(f"Candidate did not pass strict gates: {args.candidate_id}")

    rows_by_case = {row["case"]: row for row in rows}
    required_cases = {"proposed", "normal", "deterministic", "deterministic_k2"}
    if not args.allow_missing_disaster:
        required_cases.add("disaster")
    missing = sorted(required_cases.difference(rows_by_case))
    if missing:
        raise SystemExit(f"Missing required cases for promotion: {', '.join(missing)}")

    copied_by_case = {
        case: _promote_plan_and_logs(
            source_root=source_root,
            paper_root=paper_root,
            row=rows_by_case[case],
            case=case,
        )
        for case in sorted(rows_by_case)
        if case in CASE_META
    }
    table_rows = [
        _component_row(rows_by_case[case], case=case, copied=copied_by_case[case])
        for case in ("proposed", "normal", "disaster", "deterministic_k2", "deterministic")
        if case in rows_by_case
    ]
    table_fields = [
        "case_id",
        "case_name",
        "source_case",
        "candidate_id",
        "source_run_id",
        "promoted_run_id",
        "training_validation_level",
        "training_stop_reason",
        "training_iterations",
        "training_cuts",
        "training_final_violation",
        "training_max_iterations_budget",
        "normal_scenario_count",
        "disaster_scenario_count",
        "K",
        "disaster_evaluator",
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
        "active_outage_lines",
        "separation_status",
        "separation_reconstruction_gap",
        "evaluated_outage_patterns",
        "plan_path",
        "source_plan_path",
    ]
    _write_csv(paper_root / "objective_components_tableIII.csv", table_rows, table_fields)

    proposed = rows_by_case["proposed"]
    deterministic = rows_by_case["deterministic"]
    deterministic_k2 = rows_by_case["deterministic_k2"]
    det_phi = _float(deterministic, "Phi_dis")
    det_k2_phi = _float(deterministic_k2, "Phi_dis")
    proposed_phi = _float(proposed, "Phi_dis")
    det_reduction = 100.0 * (det_phi - proposed_phi) / det_phi if det_phi else 0.0
    det_k2_reduction = (
        100.0 * (det_k2_phi - proposed_phi) / det_k2_phi if det_k2_phi else 0.0
    )
    det_rows = []
    for case in ("proposed", "deterministic_k2", "deterministic"):
        row = rows_by_case[case]
        comparator_phi = _float(row, "Phi_dis")
        reduction_vs_row = (
            100.0 * (comparator_phi - proposed_phi) / comparator_phi
            if case != "proposed" and comparator_phi
            else ""
        )
        det_rows.append(
            {
                "candidate_id": args.candidate_id,
                "case": case,
                "benchmark_role": (
                    "proposed"
                    if case == "proposed"
                    else "fair deterministic mean-value with K_train=2"
                    if case == "deterministic_k2"
                    else "naive deterministic diagnostic with K_train=0"
                ),
                "training_K": row.get("training_K", ""),
                "Phi_worst": row.get("Phi_dis", ""),
                "pi_f_Phi_worst": _float(row, "pi_f") * _float(row, "Phi_dis"),
                "F_cons": row.get("F_cons", ""),
                "Psi_nor": row.get("Psi_nor", ""),
                "J_common": row.get("J_common", ""),
                "active_outage_lines": row.get("active_outage_lines", ""),
                "worst_distribution_reduction_pct_vs_naive_deterministic": (
                    det_reduction if case == "proposed" else 0.0
                ),
                "Phi_reduction_pct_vs_this_comparator": reduction_vs_row,
                "plan_path": copied_by_case[case]["promoted_plan_path"],
                "source_plan_path": copied_by_case[case]["source_plan_path"],
            }
        )
    _write_csv(
        paper_root / "deterministic_worst_distribution.csv",
        det_rows,
        [
            "candidate_id",
            "case",
            "benchmark_role",
            "training_K",
            "Phi_worst",
            "pi_f_Phi_worst",
            "F_cons",
            "Psi_nor",
            "J_common",
            "active_outage_lines",
            "worst_distribution_reduction_pct_vs_naive_deterministic",
            "Phi_reduction_pct_vs_this_comparator",
            "plan_path",
            "source_plan_path",
        ],
    )

    trace_rows = [
        {
            "claim_id": "default_gate_pass",
            "claim": "Default-scale proposed integrated case passes strict calibration gates.",
            "artifact": str(source_root / "default_scale_quality_gates.csv"),
            "row_filter": f"candidate_id={args.candidate_id}",
        },
        {
            "claim_id": "component_tableIII",
            "claim": "Main benchmark table uses component-complete common-evaluator metrics.",
            "artifact": str(paper_root / "objective_components_tableIII.csv"),
            "row_filter": f"candidate_id={args.candidate_id}",
        },
        {
            "claim_id": "deterministic_worst_distribution",
            "claim": "Proposed DRO is more robust than the fair deterministic-K2 mean-value comparator in Phi, while naive deterministic K0 is reported as a diagnostic.",
            "artifact": str(paper_root / "deterministic_worst_distribution.csv"),
            "row_filter": "case in {proposed, deterministic_k2, deterministic}",
        },
    ]
    _write_csv(paper_root / "claim_to_artifact_trace.csv", trace_rows, ["claim_id", "claim", "artifact", "row_filter"])

    audit = {
        "candidate_id": args.candidate_id,
        "default_scale_gate": "PASS",
        "component_complete": True,
        "common_evaluator": "exact_primal_dro",
        "A": 10,
        "B": 10,
        "K_eval": 2,
        "naive_deterministic_reduction_pct": det_reduction,
        "fair_deterministic_k2_reduction_pct": det_k2_reduction,
        "paper_ready_full_pack": False,
        "remaining_gates": [
            "EV sensitivity must be regenerated under the accepted regime.",
            "Large-scenario and K-scaling artifacts must be regenerated under the accepted regime.",
            "IEEE experiment section must be rewritten from the promoted artifacts.",
            "Full paper_readiness_audit and critic_review must be rerun after the final pack is rebuilt.",
        ],
    }
    _write_json(paper_root / "default_scale_audit.json", audit)
    _write_decision_card(
        paper_root / "default_scale_decision_card.md",
        candidate_id=args.candidate_id,
        quality=quality,
        rows_by_case=rows_by_case,
    )
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
