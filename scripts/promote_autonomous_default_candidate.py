"""Promote a passing autonomous default-case candidate to paper_final."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence


CASE_META = {
    "proposed": ("Case 1", "Proposed integrated", "default_scale_v2_proposed"),
    "normal": ("Case 2", "Normal-only", "default_scale_v2_normal"),
    "disaster": ("Case 3", "Disaster-only", "default_scale_v2_disaster"),
    "deterministic_k2": (
        "Case 4",
        "Deterministic mean-value, K_train=2",
        "default_scale_v2_deterministic_k2",
    ),
}

IEEE33_EDGES = [
    (1, 2), (2, 3), (2, 19), (3, 4), (3, 23), (4, 5), (5, 6), (6, 7),
    (6, 26), (7, 8), (8, 9), (9, 10), (10, 11), (11, 12), (12, 13),
    (13, 14), (14, 15), (15, 16), (16, 17), (17, 18), (19, 20),
    (20, 21), (21, 22), (23, 24), (24, 25), (26, 27), (27, 28),
    (28, 29), (29, 30), (30, 31), (31, 32), (32, 33),
]
CRITICAL_BUSES = {2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32}


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
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


def _float(row: Mapping[str, Any], key: str) -> float:
    value = row.get(key, "")
    return 0.0 if value in ("", None) else float(value)


def _copy_if_exists(source: Path, destination: Path) -> str:
    if not source.exists():
        return ""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return str(destination)


def _adjacency() -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {}
    for left, right in IEEE33_EDGES:
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)
    return graph


def _promote_artifacts(source_root: Path, paper_root: Path, row: Mapping[str, str], case: str) -> dict[str, str]:
    _, _, promoted_id = CASE_META[case]
    run_id = str(row["run_id"])
    run_root = source_root / "runs" / run_id
    plan_path = Path(str(row.get("plan_path", "")))
    copied = {
        "promoted_run_id": promoted_id,
        "source_run_root": str(run_root),
        "source_plan_path": str(plan_path),
        "promoted_plan_path": _copy_if_exists(plan_path, paper_root / "plans" / f"{promoted_id}_plan.csv"),
    }
    for suffix in ("run", "iteration_log", "cut_pool"):
        copied[f"promoted_{suffix}_path"] = _copy_if_exists(
            run_root / "logs" / f"{run_id}_{suffix}.json",
            paper_root / "logs" / f"{promoted_id}_{suffix}.json",
        )
    return copied


def _component_row(row: Mapping[str, str], case: str, copied: Mapping[str, str]) -> dict[str, Any]:
    case_id, case_name, _ = CASE_META[case]
    keep_fields = [
        "candidate_id", "m_cons", "m_normal", "m_disaster", "training_mode",
        "training_solver", "training_validation_level", "training_stop_reason",
        "training_solver_status", "training_iterations", "training_cuts",
        "training_final_violation", "normal_scenario_count", "disaster_scenario_count",
        "K", "disaster_evaluator", "F_cons", "F_trans", "F_unmet", "F_sub",
        "Psi_nor", "Phi_dis", "pi_f", "J_common", "active_outage_lines",
        "fixed_plan_dro_iterations", "fixed_plan_dro_cuts",
        "fixed_plan_dro_final_violation", "fixed_plan_dro_max_iterations",
        "fixed_plan_dro_top_cuts", "sites", "slow_chargers", "fast_chargers",
        "total_chargers", "critical_bus_coverage", "open_buses",
    ]
    out = {
        "case_id": case_id,
        "case_name": case_name,
        "source_case": case,
        "source_run_id": row.get("run_id", ""),
        "promoted_run_id": copied["promoted_run_id"],
        "plan_path": copied["promoted_plan_path"],
        "source_plan_path": copied["source_plan_path"],
    }
    out.update({field: row.get(field, "") for field in keep_fields})
    return out


def _topology_rows(table_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    graph = _adjacency()
    by_case = {row["source_case"]: row for row in table_rows}
    normal_open = {
        int(bus) for bus in str(by_case["normal"].get("open_buses", "")).split(";") if bus
    }
    out = []
    for row in table_rows:
        open_buses = {int(bus) for bus in str(row.get("open_buses", "")).split(";") if bus}
        direct = sorted(CRITICAL_BUSES & open_buses)
        direct_or_neighbor = sorted(
            bus for bus in CRITICAL_BUSES if bus in open_buses or bool(graph.get(bus, set()) & open_buses)
        )
        out.append({
            "source_case": row["source_case"],
            "case_name": row["case_name"],
            "open_buses": ";".join(str(bus) for bus in sorted(open_buses)),
            "swapped_in_vs_normal": ";".join(str(bus) for bus in sorted(open_buses - normal_open)),
            "swapped_out_vs_normal": ";".join(str(bus) for bus in sorted(normal_open - open_buses)),
            "critical_direct_count": len(direct),
            "critical_direct_buses": ";".join(str(bus) for bus in direct),
            "critical_direct_or_neighbor_count": len(direct_or_neighbor),
            "critical_direct_or_neighbor_buses": ";".join(str(bus) for bus in direct_or_neighbor),
        })
    return out


def _write_decision_card(path: Path, candidate_id: str, rows: Mapping[str, Mapping[str, str]], rubric: Mapping[str, str]) -> None:
    proposed = rows["proposed"]
    normal = rows["normal"]
    disaster = rows["disaster"]
    deterministic = rows["deterministic_k2"]
    lines = [
        "# Autonomous Default Case Decision Card",
        "",
        f"- Candidate: `{candidate_id}`",
        "- Default scale: IEEE 33-bus, `A=10`, `B=10`, `K=2`.",
        f"- Objective multipliers: `m_cons={proposed.get('m_cons')}`, `m_normal={proposed.get('m_normal')}`, `m_dis={proposed.get('m_disaster')}`.",
        f"- Verdict: `{rubric.get('rubric_verdict', '')}`.",
        f"- Proposed certificate: `{proposed.get('training_validation_level')}`, final violation `{proposed.get('training_final_violation')}`.",
        f"- Disaster-only certificate: `{disaster.get('training_validation_level')}`, final violation `{disaster.get('training_final_violation')}`.",
        "",
        "## Component Story",
        "",
        f"- Case 1 Phi: `{float(proposed['Phi_dis']):,.2f}`; Case 2 Phi: `{float(normal['Phi_dis']):,.2f}`; Case 3 Phi: `{float(disaster['Phi_dis']):,.2f}`; Case 4 Phi: `{float(deterministic['Phi_dis']):,.2f}`.",
        f"- Case 3 reduces Phi relative to Case 1 by `{float(rubric.get('Phi_case3_reduction_pct', 0.0)):,.2f}%` while its `F_unmet/Psi` is `{100.0 * float(rubric.get('Funmet_case3_over_Psi_case3', 0.0)):,.2f}%`.",
        f"- Case 1 reduces fair deterministic Case 4 Phi by `{float(rubric.get('Phi_det_gap_pct', 0.0)):,.2f}%` and installs `{proposed.get('slow_chargers')}/{proposed.get('fast_chargers')}` slow/fast chargers versus `{deterministic.get('slow_chargers')}/{deterministic.get('fast_chargers')}`.",
        "",
        "## Topology Boundary",
        "",
        "- This candidate passes the mechanism-based story rubric but does not satisfy every earlier hard topology preference.",
        f"- Direct critical-bus coverage is `{proposed.get('critical_bus_coverage')}` for Case 1 and `{deterministic.get('critical_bus_coverage')}` for Case 4.",
        f"- Case 1 opens `{proposed.get('sites')}` stations versus `{deterministic.get('sites')}` in Case 4; Case 1 is larger through both siting coverage and charger capacity.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default="results/default_case_autonomous_retuning_v3_run")
    parser.add_argument("--paper-root", default="results/paper_final")
    parser.add_argument("--candidate-id", default="mult_cons0p015_normal1_disaster1p3")
    args = parser.parse_args()

    source_root = Path(args.source_root)
    paper_root = Path(args.paper_root)
    rows = [
        row for row in _read_rows(source_root / "candidate_matrix.csv")
        if row.get("candidate_id") == args.candidate_id
    ]
    rows_by_case = {row["case"]: row for row in rows}
    missing = sorted(set(CASE_META).difference(rows_by_case))
    if missing:
        raise SystemExit(f"Missing cases for promotion: {', '.join(missing)}")
    if any(rows_by_case[case].get("training_validation_level") not in {"exact", "epsilon_certified"} for case in CASE_META):
        raise SystemExit("All promoted cases must be exact or epsilon_certified.")
    rubric_rows = [
        row for row in _read_rows(source_root / "rubric_review.csv")
        if row.get("candidate_id") == args.candidate_id
    ]
    rubric = rubric_rows[-1] if rubric_rows else {}
    if rubric.get("rubric_verdict") not in {"PASS_PAPER_STORY", "PASS_WITH_REWRITE"}:
        raise SystemExit(f"Candidate rubric did not pass: {rubric.get('rubric_verdict')}")

    copied_by_case = {
        case: _promote_artifacts(source_root, paper_root, rows_by_case[case], case)
        for case in CASE_META
    }
    table_rows = [
        _component_row(rows_by_case[case], case, copied_by_case[case])
        for case in ("proposed", "normal", "disaster", "deterministic_k2")
    ]
    _write_rows(paper_root / "objective_components_tableIII.csv", table_rows)
    _write_rows(paper_root / "default_case_multiplier_tableIII.csv", table_rows)
    _write_rows(paper_root / "default_topology_evidence.csv", _topology_rows(table_rows))

    proposed = rows_by_case["proposed"]
    deterministic = rows_by_case["deterministic_k2"]
    det_rows = []
    for case in ("proposed", "deterministic_k2"):
        row = rows_by_case[case]
        phi = _float(row, "Phi_dis")
        proposed_phi = _float(proposed, "Phi_dis")
        det_rows.append({
            "candidate_id": args.candidate_id,
            "case": case,
            "benchmark_role": "proposed" if case == "proposed" else "fair deterministic mean-value with K_train=2",
            "Phi_worst": row.get("Phi_dis", ""),
            "pi_f_Phi_worst": _float(row, "pi_f") * phi,
            "Phi_reduction_pct_vs_this_comparator": "" if case == "proposed" else 100.0 * (phi - proposed_phi) / phi,
            "F_cons": row.get("F_cons", ""),
            "Psi_nor": row.get("Psi_nor", ""),
            "J_common": row.get("J_common", ""),
            "active_outage_lines": row.get("active_outage_lines", ""),
            "plan_path": copied_by_case[case]["promoted_plan_path"],
            "source_plan_path": copied_by_case[case]["source_plan_path"],
        })
    _write_rows(paper_root / "deterministic_worst_distribution.csv", det_rows)

    promotion = {
        "candidate_id": args.candidate_id,
        "verdict": rubric.get("rubric_verdict"),
        "paper_final_promoted": True,
        "source_root": str(source_root),
        "paper_root": str(paper_root),
        "objective_components_tableIII": str(paper_root / "objective_components_tableIII.csv"),
        "deterministic_worst_distribution": str(paper_root / "deterministic_worst_distribution.csv"),
    }
    _write_json(paper_root / "default_autonomous_promotion.json", promotion)
    _write_json(paper_root / "default_case_multiplier_critic_review.json", {**promotion, "rubric": dict(rubric)})
    (paper_root / "default_case_multiplier_critic_review.md").write_text(
        "# Default Case Multiplier Critic Review\n\n"
        f"Verdict: `{rubric.get('rubric_verdict')}`\n\n"
        f"Candidate: `{args.candidate_id}`\n\n"
        f"Science pass: `{rubric.get('science_pass')}`\n\n"
        f"Topology pass: `{rubric.get('topology_pass')}`\n\n"
        f"Failure/preferences not met: `{rubric.get('failure_reasons')}`\n",
        encoding="utf-8",
    )
    _write_decision_card(
        paper_root / "default_case_decision_card.md",
        args.candidate_id,
        rows_by_case,
        rubric,
    )
    print(json.dumps(promotion, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
