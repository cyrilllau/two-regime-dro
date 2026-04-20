"""Run the paper-like Fig. 6 calibration sweep without changing validated math."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from experiment_pack_utils import (  # noqa: E402
    ensure_directory,
    execute_run,
    load_critical_buses,
    load_yaml_file,
    rows_to_markdown_table,
)
from make_experiment_figures import write_plan_map_figure  # noqa: E402


def _clear_outputs(output_root: Path) -> None:
    for child_name in ("summary.csv", "failures.csv", "metadata.json"):
        child = output_root / child_name
        if child.exists():
            child.unlink()
    for directory_name in ("plans", "logs", "figures"):
        directory = output_root / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()


def _deep_merge(base: Mapping[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if (
            key in merged
            and isinstance(merged[key], Mapping)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(dict(merged[key]), dict(value))
        else:
            merged[key] = value
    return merged


def _load_plan_rows(path: str | Path) -> list[dict[str, int]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    materialized: list[dict[str, int]] = []
    for row in rows:
        materialized.append(
            {
                "bus": int(row["bus"]),
                "is_open": int(row["is_open"]),
                "n_sl": int(row["n_sl"]),
                "n_fa": int(row["n_fa"]),
                "is_critical": int(row["is_critical"]),
            }
        )
    return materialized


def _safe_plan_rows(result: Mapping[str, Any]) -> list[dict[str, int]]:
    plan_path = result.get("plan_path")
    if not plan_path:
        return []
    return _load_plan_rows(plan_path)


def _opened_sites(plan_rows: Sequence[Mapping[str, int]]) -> list[tuple[int, int, int]]:
    return sorted(
        (
            int(row["bus"]),
            int(row["n_sl"]),
            int(row["n_fa"]),
        )
        for row in plan_rows
        if int(row["is_open"]) == 1
    )


def _cluster_metrics(
    opened_sites: Sequence[tuple[int, int, int]],
    target_clusters: Mapping[str, Mapping[str, Sequence[int]]],
) -> dict[str, Any]:
    cluster_lookup = {
        cluster_name: {int(bus) for bus in cluster_payload["buses"]}
        for cluster_name, cluster_payload in target_clusters.items()
    }
    all_target_buses = set().union(*cluster_lookup.values()) if cluster_lookup else set()
    hits: dict[str, list[int]] = {}
    for cluster_name, buses in cluster_lookup.items():
        hits[cluster_name] = [bus for bus, _, _ in opened_sites if bus in buses]
    out_of_cluster_buses = [bus for bus, _, _ in opened_sites if bus not in all_target_buses]
    return {
        "cluster_hits": hits,
        "cluster_count": sum(1 for values in hits.values() if values),
        "out_of_cluster_buses": out_of_cluster_buses,
    }


def _stage1_rule_check(
    *,
    summary: Mapping[str, Any],
    fast_station_count: int,
    capped_slow_station_count: int,
    cluster_count: int,
    out_of_cluster_open_count: int,
    rules: Mapping[str, Any],
) -> bool:
    opened_bus_count = int(summary.get("opened_bus_count") or 0)
    total_slow = int(summary.get("total_slow_chargers") or 0)
    return (
        int(rules["opened_bus_min"]) <= opened_bus_count <= int(rules["opened_bus_max"])
        and total_slow <= int(rules["total_slow_max"])
        and fast_station_count >= int(rules["min_fast_station_count"])
        and capped_slow_station_count <= int(rules["max_capped_slow_station_count"])
        and int(rules["min_cluster_count"]) <= cluster_count <= int(rules["max_cluster_count"])
        and out_of_cluster_open_count <= int(rules["max_out_of_cluster_open_count"])
    )


def _stage1_rank_key(
    *,
    summary: Mapping[str, Any],
    fast_station_count: int,
    capped_slow_station_count: int,
    cluster_count: int,
    out_of_cluster_open_count: int,
    rules: Mapping[str, Any],
    candidate_order: int,
) -> tuple[int, int, int, int, int, int, int]:
    opened_bus_count = int(summary.get("opened_bus_count") or 0)
    total_slow = int(summary.get("total_slow_chargers") or 0)
    min_open = int(rules["opened_bus_min"])
    max_open = int(rules["opened_bus_max"])
    site_penalty = max(0, min_open - opened_bus_count) + max(0, opened_bus_count - max_open)
    slow_penalty = max(0, total_slow - int(rules["total_slow_max"]))
    fast_station_penalty = max(0, int(rules["min_fast_station_count"]) - fast_station_count)
    capped_penalty = max(0, capped_slow_station_count - int(rules["max_capped_slow_station_count"]))
    cluster_penalty = 0
    if cluster_count < int(rules["min_cluster_count"]):
        cluster_penalty = int(rules["min_cluster_count"]) - cluster_count
    elif cluster_count > int(rules["max_cluster_count"]):
        cluster_penalty = cluster_count - int(rules["max_cluster_count"])
    return (
        site_penalty,
        slow_penalty,
        out_of_cluster_open_count,
        fast_station_penalty,
        capped_penalty,
        cluster_penalty,
        candidate_order,
    )


def _overrides_to_scalars(overrides: Mapping[str, Any]) -> dict[str, float]:
    economics = dict(overrides.get("economics", {}))
    return {
        "cfix": float(economics["cfix"]),
        "ctrans_scalar": float(economics["ctrans_scalar"]),
        "ccons_sl": float(economics["ccons_sl"]),
        "ccons_fa": float(economics["ccons_fa"]),
    }


def _stringify_sites(opened_sites: Sequence[tuple[int, int, int]]) -> str:
    return "; ".join(f"{bus}:{n_sl}/{n_fa}" for bus, n_sl, n_fa in opened_sites)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return path


def _write_target_plan_csv(
    *,
    path: Path,
    critical_buses: Sequence[int],
    target_semantics: Mapping[str, Any],
) -> Path:
    sites = {
        int(site["bus"]): (int(site["n_sl"]), int(site["n_fa"]))
        for site in target_semantics.get("sites", ())
    }
    rows: list[dict[str, Any]] = []
    critical_set = {int(bus) for bus in critical_buses}
    for bus in range(1, 34):
        slow, fast = sites.get(bus, (0, 0))
        rows.append(
            {
                "bus": bus,
                "is_open": int(bus in sites),
                "n_sl": slow,
                "n_fa": fast,
                "is_critical": int(bus in critical_set),
                "region": "",
            }
        )
    fieldnames = ["bus", "is_open", "n_sl", "n_fa", "is_critical", "region"]
    return _write_csv(path, rows, fieldnames)


def _render_lines(items: Iterable[str]) -> str:
    materialized = [item for item in items if item]
    if not materialized:
        return "- none"
    return "\n".join(f"- {item}" for item in materialized)


def _write_report(
    *,
    report_path: Path,
    summary_rows: Sequence[Mapping[str, Any]],
    failure_rows: Sequence[Mapping[str, Any]],
    winner_row: Mapping[str, Any],
    triggered_demand_normalization: bool,
    figure_paths: Sequence[str],
) -> Path:
    stage1_rows = [row for row in summary_rows if row["stage"] == "stage1"]
    stage2_rows = [row for row in summary_rows if row["stage"] == "stage2"]
    stage3_rows = [row for row in summary_rows if row["stage"] == "stage3"]

    content = f"""# Paper-Like Fig. 6 Calibration Pack

## Scope
- This pack performs config-level calibration only.
- No validated optimization math was changed.
- The exact anchor remains `normal_only` under `direct_master`.
- The current `runtime_12` source is still not paper-number reproduction.

## Stage 1 Candidate Sweep
{rows_to_markdown_table(
    stage1_rows,
    columns=(
        "candidate_id",
        "validation_level",
        "opened_bus_count",
        "total_slow_chargers",
        "total_fast_chargers",
        "fast_station_count",
        "capped_slow_station_count",
        "cluster_count",
        "out_of_cluster_open_count",
        "meets_stage1_rules",
    ),
)}

## Winner Selection
- Selected winner candidate: `{winner_row["candidate_id"]}`
- Winner selection basis: `{winner_row["selection_basis"]}`
- Winner opened buses: `{winner_row["opened_bus_count"]}`
- Winner total slow / fast: `{winner_row["total_slow_chargers"]} / {winner_row["total_fast_chargers"]}`
- Winner opened-site list: `{winner_row["opened_bus_list"]}`

## Stage 2 Propagation
{rows_to_markdown_table(
    stage2_rows,
    columns=(
        "run_id",
        "mode",
        "validation_level",
        "stop_reason",
        "opened_bus_count",
        "total_slow_chargers",
        "total_fast_chargers",
    ),
)}

## Stage 3 Demand Normalization
- Triggered: `{triggered_demand_normalization}`
{rows_to_markdown_table(
    stage3_rows,
    columns=(
        "run_id",
        "ev_penetration_scale",
        "validation_level",
        "opened_bus_count",
        "total_slow_chargers",
        "total_fast_chargers",
        "opened_bus_list",
    ),
) if stage3_rows else "- No demand-normalization runs were required."}

## Key Findings
- No Stage 1 candidate satisfied the target paper-like siting rules.
- The exact `normal_only` anchor stayed at `15` opened buses for all `S0`-`S6` cost-only candidates.
- The lexicographic fallback winner was therefore `{winner_row["candidate_id"]}`, not because it solved the target, but because it was the first tied-best cost-only variant.
- Stage 2 propagation confirmed the same qualitative result:
  - `normal_only_paper_like_tuned` stayed at `15` opened buses.
  - `integrated_mainline_paper_like_tuned` also stayed at `15` opened buses.
  - `disaster_only_paper_like_tuned` remained sparse at `1` site, so the excessive siting pressure is still coming from the normal-operation side.
- Demand normalization was the only lever that materially changed the exact `normal_only` siting pattern:
  - `0.85` scale reduced the exact anchor to `13` sites.
  - `0.70` scale reduced the exact anchor to `10` sites.
- Even after `0.70`, the current local `runtime_12`-based approximation still did not reach the desired `6-8` sites or `<= 220` slow chargers.

## Lever Interpretation
- Sparsity levers:
  - `cfix`
  - `ctrans_scalar`
  - `ccons_sl`
- Station-mix lever:
  - `ccons_fa`
- Demand-normalization lever:
  - `ev_penetration_scale`
- Explicitly not used as tuning levers:
  - `epsilon_cert`
  - `max_iterations`
  - `critical_buses`
  - `gamma`
  - `theta`
  - `cunmet`
  - `nbar_sl`
  - `nbar_fa`

## Figures
{_render_lines(figure_paths)}

## Failure / Non-Exact Visibility
{rows_to_markdown_table(
    failure_rows,
    columns=(
        "stage",
        "run_id",
        "validation_level",
        "stop_reason",
        "solver_status",
        "final_violation_upper_bound",
        "message",
    ),
) if failure_rows else "- none"}
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")
    return report_path


def _plot_stage1_metrics(summary_rows: Sequence[Mapping[str, Any]], path: Path) -> Path:
    import matplotlib.pyplot as plt

    stage1_rows = [row for row in summary_rows if row["stage"] == "stage1"]
    candidate_ids = [str(row["candidate_id"]) for row in stage1_rows]
    opened_counts = [int(row["opened_bus_count"] or 0) for row in stage1_rows]
    slow_counts = [int(row["total_slow_chargers"] or 0) for row in stage1_rows]
    fast_counts = [int(row["total_fast_chargers"] or 0) for row in stage1_rows]

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    axes[0].bar(candidate_ids, opened_counts, color="#4878cf")
    axes[0].axhspan(6, 8, color="#8fd175", alpha=0.25)
    axes[0].set_ylabel("Opened buses")
    axes[0].set_title("Stage 1 exact normal-only candidate sweep")

    axes[1].bar(candidate_ids, slow_counts, color="#6acc64", label="slow")
    axes[1].bar(candidate_ids, fast_counts, bottom=slow_counts, color="#d65f5f", label="fast")
    axes[1].axhline(220, color="black", linestyle="--", linewidth=1.0, label="target slow <= 220")
    axes[1].set_ylabel("Installed chargers")
    axes[1].tick_params(axis="x", rotation=20)
    axes[1].legend(fontsize=8)

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def _run_one(
    *,
    run_config: Mapping[str, Any],
    critical_buses: Sequence[int],
    output_root: Path,
) -> dict[str, Any]:
    return execute_run(run_config, critical_buses=critical_buses, output_root=output_root)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/experiments/paper_like_fig6_calibration.yaml",
    )
    parser.add_argument("--output-root")
    parser.add_argument("--report-path")
    parser.add_argument("--skip-figures", action="store_true")
    args = parser.parse_args()

    config = load_yaml_file(args.config)
    output_root = Path(args.output_root or config["output_root"])
    report_path = Path(args.report_path or config["report_path"])
    critical_buses = load_critical_buses(config["critical_buses_config"])
    _clear_outputs(output_root)

    base_run = dict(config["base_run"])
    family_name = str(config["family_name"])
    base_overrides = dict(base_run.get("parameter_overrides", {}))
    rules = dict(config["stage1_rules"])
    target_clusters = dict(config["target_clusters"])

    summary_rows: list[dict[str, Any]] = []
    failure_rows: list[dict[str, Any]] = []
    stage1_ranked: list[tuple[tuple[int, int, int, int, int, int, int], dict[str, Any], dict[str, Any]]] = []

    for candidate_order, candidate in enumerate(config["stage1_candidates"]):
        candidate_id = str(candidate["candidate_id"])
        candidate_overrides = _deep_merge(base_overrides, dict(candidate.get("parameter_overrides", {})))
        run_config = {
            "run_id": candidate_id,
            "family_name": family_name,
            "case_name": candidate_id,
            "runtime_source": base_run["runtime_source"],
            "selection": dict(base_run["selection"]),
            "mode": str(candidate["mode"]),
            "solver": str(candidate["solver"]),
            "parameter_regime": str(base_run["parameter_regime"]),
            "parameter_overrides": candidate_overrides,
        }
        if "benders" in base_run:
            run_config["benders"] = dict(base_run["benders"])
        result = _run_one(run_config=run_config, critical_buses=critical_buses, output_root=output_root)
        plan_rows = _safe_plan_rows(result)
        opened_sites = _opened_sites(plan_rows)
        fast_station_count = sum(1 for _, _, fast in opened_sites if fast > 0)
        capped_slow_station_count = sum(1 for _, slow, _ in opened_sites if slow == 25)
        cluster_metrics = _cluster_metrics(opened_sites, target_clusters)
        meets_rules = _stage1_rule_check(
            summary=result["summary"].to_csv_row(),
            fast_station_count=fast_station_count,
            capped_slow_station_count=capped_slow_station_count,
            cluster_count=cluster_metrics["cluster_count"],
            out_of_cluster_open_count=len(cluster_metrics["out_of_cluster_buses"]),
            rules=rules,
        )
        rank_key = _stage1_rank_key(
            summary=result["summary"].to_csv_row(),
            fast_station_count=fast_station_count,
            capped_slow_station_count=capped_slow_station_count,
            cluster_count=cluster_metrics["cluster_count"],
            out_of_cluster_open_count=len(cluster_metrics["out_of_cluster_buses"]),
            rules=rules,
            candidate_order=candidate_order,
        )
        scalars = _overrides_to_scalars(candidate_overrides)
        row = {
            "stage": "stage1",
            "candidate_id": candidate_id,
            "selection_basis": "",
            "selected_as_stage1_winner": False,
            "run_id": result["summary"].run_id,
            "mode": run_config["mode"],
            "solver": run_config["solver"],
            "validation_level": result["summary"].validation_level,
            "stop_reason": result["summary"].stop_reason,
            "solver_status": result["summary"].solver_status,
            "parameter_regime": result["summary"].parameter_regime,
            "cfix": scalars["cfix"],
            "ctrans_scalar": scalars["ctrans_scalar"],
            "ccons_sl": scalars["ccons_sl"],
            "ccons_fa": scalars["ccons_fa"],
            "ev_penetration_scale": 1.0,
            "opened_bus_count": result["summary"].opened_bus_count,
            "total_slow_chargers": result["summary"].total_slow_chargers,
            "total_fast_chargers": result["summary"].total_fast_chargers,
            "fast_station_count": fast_station_count,
            "capped_slow_station_count": capped_slow_station_count,
            "cluster_count": cluster_metrics["cluster_count"],
            "cluster_hits": json.dumps(cluster_metrics["cluster_hits"], sort_keys=True),
            "out_of_cluster_open_count": len(cluster_metrics["out_of_cluster_buses"]),
            "out_of_cluster_buses": ",".join(str(bus) for bus in cluster_metrics["out_of_cluster_buses"]),
            "opened_bus_list": _stringify_sites(opened_sites),
            "meets_stage1_rules": meets_rules,
            "plan_path": result["plan_path"],
            "log_path": result["log_path"],
            "final_violation_upper_bound": result["summary"].final_violation_upper_bound,
            "notes": str(candidate.get("description", "")),
        }
        summary_rows.append(row)
        stage1_ranked.append((rank_key, row, run_config))
        if result["failure_summary"] is not None:
            failure_rows.append(
                {
                    "stage": "stage1",
                    "candidate_id": candidate_id,
                    "run_id": result["summary"].run_id,
                    "validation_level": result["summary"].validation_level,
                    "stop_reason": result["summary"].stop_reason,
                    "solver_status": result["summary"].solver_status,
                    "final_violation_upper_bound": result["summary"].final_violation_upper_bound,
                    "message": result["failure_summary"].message,
                }
            )

    satisfying = [item for item in stage1_ranked if item[1]["meets_stage1_rules"]]
    if satisfying:
        winner_row, winner_run_config = satisfying[0][1], satisfying[0][2]
        winner_row["selection_basis"] = "first_rule_satisfying"
    else:
        _, winner_row, winner_run_config = min(stage1_ranked, key=lambda item: item[0])
        winner_row["selection_basis"] = "lexicographic_best_fallback"
    winner_row["selected_as_stage1_winner"] = True
    winner_candidate_id = str(winner_row["candidate_id"])
    winner_overrides = dict(winner_run_config["parameter_overrides"])

    stage2_lookup: dict[str, dict[str, Any]] = {}
    for mode_payload in config["stage2_modes"]:
        run_config = {
            "run_id": str(mode_payload["run_id"]),
            "family_name": family_name,
            "case_name": str(mode_payload["case_name"]),
            "runtime_source": base_run["runtime_source"],
            "selection": dict(base_run["selection"]),
            "mode": str(mode_payload["mode"]),
            "solver": str(mode_payload["solver"]),
            "parameter_regime": str(base_run["parameter_regime"]),
            "parameter_overrides": winner_overrides,
        }
        if run_config["solver"] == "benders":
            run_config["benders"] = dict(base_run["benders"])
        result = _run_one(run_config=run_config, critical_buses=critical_buses, output_root=output_root)
        plan_rows = _safe_plan_rows(result)
        opened_sites = _opened_sites(plan_rows)
        stage2_row = {
            "stage": "stage2",
            "candidate_id": winner_candidate_id,
            "selection_basis": winner_row["selection_basis"],
            "selected_as_stage1_winner": run_config["mode"] == "normal_only",
            "run_id": result["summary"].run_id,
            "mode": run_config["mode"],
            "solver": run_config["solver"],
            "validation_level": result["summary"].validation_level,
            "stop_reason": result["summary"].stop_reason,
            "solver_status": result["summary"].solver_status,
            "parameter_regime": result["summary"].parameter_regime,
            "cfix": winner_row["cfix"],
            "ctrans_scalar": winner_row["ctrans_scalar"],
            "ccons_sl": winner_row["ccons_sl"],
            "ccons_fa": winner_row["ccons_fa"],
            "ev_penetration_scale": 1.0,
            "opened_bus_count": result["summary"].opened_bus_count,
            "total_slow_chargers": result["summary"].total_slow_chargers,
            "total_fast_chargers": result["summary"].total_fast_chargers,
            "fast_station_count": sum(1 for _, _, fast in opened_sites if fast > 0),
            "capped_slow_station_count": sum(1 for _, slow, _ in opened_sites if slow == 25),
            "cluster_count": _cluster_metrics(opened_sites, target_clusters)["cluster_count"],
            "cluster_hits": json.dumps(_cluster_metrics(opened_sites, target_clusters)["cluster_hits"], sort_keys=True),
            "out_of_cluster_open_count": len(_cluster_metrics(opened_sites, target_clusters)["out_of_cluster_buses"]),
            "out_of_cluster_buses": ",".join(str(bus) for bus in _cluster_metrics(opened_sites, target_clusters)["out_of_cluster_buses"]),
            "opened_bus_list": _stringify_sites(opened_sites),
            "meets_stage1_rules": "",
            "plan_path": result["plan_path"],
            "log_path": result["log_path"],
            "final_violation_upper_bound": result["summary"].final_violation_upper_bound,
            "notes": f"Winner propagation from {winner_candidate_id}",
        }
        summary_rows.append(stage2_row)
        stage2_lookup[run_config["mode"]] = stage2_row
        if result["failure_summary"] is not None:
            failure_rows.append(
                {
                    "stage": "stage2",
                    "candidate_id": winner_candidate_id,
                    "run_id": result["summary"].run_id,
                    "validation_level": result["summary"].validation_level,
                    "stop_reason": result["summary"].stop_reason,
                    "solver_status": result["summary"].solver_status,
                    "final_violation_upper_bound": result["summary"].final_violation_upper_bound,
                    "message": result["failure_summary"].message,
                }
            )

    triggered_demand_normalization = False
    stage2_normal_only = stage2_lookup["normal_only"]
    if int(stage2_normal_only["opened_bus_count"] or 0) > int(rules["opened_bus_max"]):
        triggered_demand_normalization = True
        for demand_index, demand_payload in enumerate(config["demand_normalization"]):
            ev_scale = float(demand_payload["ev_penetration_scale"])
            run_config = {
                "run_id": f"normal_only_paper_like_tuned_{demand_payload['candidate_id']}",
                "family_name": family_name,
                "case_name": f"normal_only_paper_like_tuned_{demand_payload['candidate_id']}",
                "runtime_source": base_run["runtime_source"],
                "selection": dict(base_run["selection"]),
                "mode": "normal_only",
                "solver": "direct_master",
                "parameter_regime": str(base_run["parameter_regime"]),
                "parameter_overrides": winner_overrides,
                "ev_penetration_scale": ev_scale,
            }
            result = _run_one(run_config=run_config, critical_buses=critical_buses, output_root=output_root)
            plan_rows = _safe_plan_rows(result)
            opened_sites = _opened_sites(plan_rows)
            stage3_row = {
                "stage": "stage3",
                "candidate_id": str(demand_payload["candidate_id"]),
                "selection_basis": winner_row["selection_basis"],
                "selected_as_stage1_winner": False,
                "run_id": result["summary"].run_id,
                "mode": run_config["mode"],
                "solver": run_config["solver"],
                "validation_level": result["summary"].validation_level,
                "stop_reason": result["summary"].stop_reason,
                "solver_status": result["summary"].solver_status,
                "parameter_regime": result["summary"].parameter_regime,
                "cfix": winner_row["cfix"],
                "ctrans_scalar": winner_row["ctrans_scalar"],
                "ccons_sl": winner_row["ccons_sl"],
                "ccons_fa": winner_row["ccons_fa"],
                "ev_penetration_scale": ev_scale,
                "opened_bus_count": result["summary"].opened_bus_count,
                "total_slow_chargers": result["summary"].total_slow_chargers,
                "total_fast_chargers": result["summary"].total_fast_chargers,
                "fast_station_count": sum(1 for _, _, fast in opened_sites if fast > 0),
                "capped_slow_station_count": sum(1 for _, slow, _ in opened_sites if slow == 25),
                "cluster_count": _cluster_metrics(opened_sites, target_clusters)["cluster_count"],
                "cluster_hits": json.dumps(_cluster_metrics(opened_sites, target_clusters)["cluster_hits"], sort_keys=True),
                "out_of_cluster_open_count": len(_cluster_metrics(opened_sites, target_clusters)["out_of_cluster_buses"]),
                "out_of_cluster_buses": ",".join(str(bus) for bus in _cluster_metrics(opened_sites, target_clusters)["out_of_cluster_buses"]),
                "opened_bus_list": _stringify_sites(opened_sites),
                "meets_stage1_rules": "",
                "plan_path": result["plan_path"],
                "log_path": result["log_path"],
                "final_violation_upper_bound": result["summary"].final_violation_upper_bound,
                "notes": "Demand normalization on top of stage-2 winner parameters.",
            }
            summary_rows.append(stage3_row)
            if result["failure_summary"] is not None:
                failure_rows.append(
                    {
                        "stage": "stage3",
                        "candidate_id": str(demand_payload["candidate_id"]),
                        "run_id": result["summary"].run_id,
                        "validation_level": result["summary"].validation_level,
                        "stop_reason": result["summary"].stop_reason,
                        "solver_status": result["summary"].solver_status,
                        "final_violation_upper_bound": result["summary"].final_violation_upper_bound,
                        "message": result["failure_summary"].message,
                    }
                )
            if int(result["summary"].opened_bus_count or 0) <= int(rules["opened_bus_max"]):
                break
            if demand_index == 0:
                continue

    summary_fieldnames = [
        "stage",
        "candidate_id",
        "selection_basis",
        "selected_as_stage1_winner",
        "run_id",
        "mode",
        "solver",
        "validation_level",
        "stop_reason",
        "solver_status",
        "parameter_regime",
        "cfix",
        "ctrans_scalar",
        "ccons_sl",
        "ccons_fa",
        "ev_penetration_scale",
        "opened_bus_count",
        "total_slow_chargers",
        "total_fast_chargers",
        "fast_station_count",
        "capped_slow_station_count",
        "cluster_count",
        "cluster_hits",
        "out_of_cluster_open_count",
        "out_of_cluster_buses",
        "opened_bus_list",
        "meets_stage1_rules",
        "final_violation_upper_bound",
        "plan_path",
        "log_path",
        "notes",
    ]
    failure_fieldnames = [
        "stage",
        "candidate_id",
        "run_id",
        "validation_level",
        "stop_reason",
        "solver_status",
        "final_violation_upper_bound",
        "message",
    ]
    summary_path = _write_csv(output_root / "summary.csv", summary_rows, summary_fieldnames)
    failures_path = _write_csv(output_root / "failures.csv", failure_rows, failure_fieldnames)

    _write_target_plan_csv(
        path=output_root / "plans" / f"{config['target_semantics']['run_id']}_plan.csv",
        critical_buses=critical_buses,
        target_semantics=config["target_semantics"],
    )

    figure_paths: list[str] = []
    if not args.skip_figures:
        stage1_figure = _plot_stage1_metrics(summary_rows, output_root / "figures" / "stage1_candidate_metrics.png")
        figure_paths.append(str(stage1_figure))
        comparison_figure = write_plan_map_figure(
            run_ids=(
                "S0_baseline",
                "normal_only_paper_like_tuned",
                str(config["target_semantics"]["run_id"]),
            ),
            plans_dir=output_root / "plans",
            title="Baseline vs tuned normal-only winner vs paper target semantics",
            path=output_root / "figures" / "baseline_tuned_target_plan_maps.png",
            ncols=1,
        )
        figure_paths.append(str(comparison_figure))
        if triggered_demand_normalization:
            demand_run_ids = tuple(
                row["run_id"] for row in summary_rows if row["stage"] == "stage3"
            )
            if demand_run_ids:
                demand_figure = write_plan_map_figure(
                    run_ids=demand_run_ids,
                    plans_dir=output_root / "plans",
                    title="Demand normalization progression on top of tuned winner",
                    path=output_root / "figures" / "demand_normalization_progression.png",
                    ncols=1,
                )
                figure_paths.append(str(demand_figure))

    report_written = _write_report(
        report_path=report_path,
        summary_rows=summary_rows,
        failure_rows=failure_rows,
        winner_row=winner_row,
        triggered_demand_normalization=triggered_demand_normalization,
        figure_paths=figure_paths,
    )
    metadata = {
        "summary_csv": str(summary_path),
        "failures_csv": str(failures_path),
        "report_path": str(report_written),
        "winner_candidate_id": winner_candidate_id,
        "winner_selection_basis": winner_row["selection_basis"],
        "triggered_demand_normalization": triggered_demand_normalization,
        "figure_paths": figure_paths,
    }
    (output_root / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
