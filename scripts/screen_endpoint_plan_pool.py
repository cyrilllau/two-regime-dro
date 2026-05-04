"""Fast frozen-plan screening for default endpoint-structure retuning.

This is a screening tool, not paper evidence.  It reuses certified plans already
generated for the same data/support and scores them under candidate objective
term multipliers.  Candidate triples that cannot look good even within this
plan pool should not be sent to expensive Benders solves first.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_default_multiplier_calibration import _candidate_id, _story_gate  # noqa: E402


CASE_ORDER = ("proposed", "normal", "disaster", "deterministic_k2")
DEFAULT_SOURCES = (
    "results/default_case_topology_calibration/candidate_matrix.csv",
    "results/default_case_det_topology_calibration/candidate_matrix.csv",
    "results/default_case_accelerated_retuning/candidate_matrix.csv",
    "results/paper_final/objective_components_tableIII.csv",
)


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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


def _float(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    raw = row.get(key, default)
    if raw in ("", None):
        return default
    return float(raw)


def _int(row: Mapping[str, Any], key: str, default: int = 0) -> int:
    raw = row.get(key, default)
    if raw in ("", None):
        return default
    return int(float(raw))


def _normalize_row(row: Mapping[str, Any], *, source_path: str) -> dict[str, Any]:
    case = str(row.get("case") or row.get("source_case") or "")
    candidate_id = str(row.get("candidate_id") or row.get("accepted_candidate_id") or "")
    return {
        **dict(row),
        "case": case,
        "candidate_id": candidate_id,
        "source_artifact": source_path,
        "training_validation_level": str(row.get("training_validation_level", "")),
        "normal_scenario_count": row.get("normal_scenario_count", "10"),
        "disaster_scenario_count": row.get("disaster_scenario_count", "10"),
        "K": row.get("K", "2"),
        "disaster_evaluator": row.get("disaster_evaluator", "milp_worst_distribution"),
    }


def _load_plan_pool(paths: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw_path in paths:
        path = REPO_ROOT / raw_path if not Path(raw_path).is_absolute() else Path(raw_path)
        for row in _read_rows(path):
            normalized = _normalize_row(row, source_path=str(path))
            case = normalized["case"]
            if case not in CASE_ORDER:
                continue
            if normalized["training_validation_level"] not in {"exact", "epsilon_certified"}:
                continue
            if _int(normalized, "normal_scenario_count") != 10:
                continue
            if _int(normalized, "disaster_scenario_count") != 10:
                continue
            if _int(normalized, "K") != 2:
                continue
            key = (case, str(normalized.get("plan_path", "")), normalized["candidate_id"])
            if key in seen:
                continue
            seen.add(key)
            rows.append(normalized)
    return rows


def _training_objective(row: Mapping[str, Any], *, m_cons: float, m_normal: float, m_dis: float) -> float:
    pi_f = _float(row, "pi_f", 0.3)
    return (
        m_cons * _float(row, "F_cons")
        + m_normal * (1.0 - pi_f) * _float(row, "Psi_nor")
        + m_dis * pi_f * _float(row, "Phi_dis")
    )


def _candidate_rows(
    pool: Sequence[Mapping[str, Any]],
    *,
    m_cons: float,
    m_normal: float,
    m_dis: float,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for case in CASE_ORDER:
        case_pool = [row for row in pool if row["case"] == case]
        if not case_pool:
            continue
        best = min(
            case_pool,
            key=lambda row: _training_objective(row, m_cons=m_cons, m_normal=m_normal, m_dis=m_dis),
        )
        selected.append({
            **dict(best),
            "candidate_id": _candidate_id(m_cons, m_normal, m_dis),
            "m_cons": m_cons,
            "m_normal": m_normal,
            "m_disaster": m_dis,
            "plan_pool_source_candidate": best.get("candidate_id", ""),
            "plan_pool_training_objective": _training_objective(
                best, m_cons=m_cons, m_normal=m_normal, m_dis=m_dis
            ),
        })
    return selected


def _parse_values(raw: str) -> list[float]:
    return [float(value.strip()) for value in raw.split(",") if value.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default="results/default_case_endpoint_structure_retuning")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES))
    parser.add_argument("--cons-values", default="0.011,0.012,0.013,0.014,0.015,0.016,0.017,0.018")
    parser.add_argument("--normal-values", default="1")
    parser.add_argument("--disaster-values", default="1.15,1.20,1.25,1.30,1.35,1.40,1.45,1.50")
    args = parser.parse_args()

    root = REPO_ROOT / args.output_root
    sources = [part.strip() for part in args.sources.split(",") if part.strip()]
    pool = _load_plan_pool(sources)
    _write_rows(root / "plan_pool_rows.csv", pool)

    gate_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []
    for m_cons, m_normal, m_dis in itertools.product(
        _parse_values(args.cons_values),
        _parse_values(args.normal_values),
        _parse_values(args.disaster_values),
    ):
        candidate = {
            "candidate_id": _candidate_id(m_cons, m_normal, m_dis),
            "m_cons": m_cons,
            "m_normal": m_normal,
            "m_disaster": m_dis,
        }
        selected = _candidate_rows(pool, m_cons=m_cons, m_normal=m_normal, m_dis=m_dis)
        for row in selected:
            selection_rows.append({
                "screen_candidate_id": candidate["candidate_id"],
                "screen_m_cons": m_cons,
                "screen_m_normal": m_normal,
                "screen_m_disaster": m_dis,
                "case": row["case"],
                "plan_pool_source_candidate": row.get("plan_pool_source_candidate", ""),
                "source_artifact": row.get("source_artifact", ""),
                "plan_pool_training_objective": row.get("plan_pool_training_objective", ""),
                "Phi_dis": row.get("Phi_dis", ""),
                "Psi_nor": row.get("Psi_nor", ""),
                "sites": row.get("sites", ""),
                "slow_chargers": row.get("slow_chargers", ""),
                "fast_chargers": row.get("fast_chargers", ""),
                "critical_bus_coverage": row.get("critical_bus_coverage", ""),
            })
        gate = _story_gate(candidate, selected)
        gate_rows.append({**gate, "screening_method": "certified_plan_pool"})

    _write_rows(root / "plan_pool_selection.csv", selection_rows)
    _write_rows(root / "plan_pool_gate_summary.csv", gate_rows)
    passing = [row for row in gate_rows if bool(row.get("passes_all"))]
    best = sorted(
        gate_rows,
        key=lambda row: float(row.get("story_score") or 0.0),
        reverse=True,
    )[:10]
    _write_rows(root / "plan_pool_top10.csv", best)
    print(f"pool_rows={len(pool)} candidates={len(gate_rows)} passing={len(passing)}")
    if passing:
        print("best_pass=", passing[0]["candidate_id"])


if __name__ == "__main__":
    main()
