"""Run low-risk engineering acceleration experiments outside paper_final."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import execute_run, load_critical_buses  # noqa: E402
from scripts.run_full_benders_scalability import (  # noqa: E402
    CRITICAL_BUSES,
    CURRENT_DEFAULT_REGIME,
    DEFAULT_ACCEPTED_LOG,
    _read_accepted_config,
)
from scripts.run_separation_scalability import _summarize_milp  # noqa: E402


DEFAULT_OUTPUT = REPO_ROOT / "results/engineering_acceleration"
DEFAULT_RUNTIME_SOURCE = "data/colleague_default_synth_100x100"
PAPER_SCALING_ROOT = REPO_ROOT / "results/paper_final/full_benders_scaling_runs/current_default_milp"
PAPER_DEFAULT_PLAN = REPO_ROOT / "results/paper_final/plans/default_scale_v2_proposed_plan.csv"


def _parse_ints(raw: str) -> tuple[int, ...]:
    return tuple(int(token.strip()) for token in raw.split(",") if token.strip())


def _parse_list(raw: str) -> tuple[str, ...]:
    return tuple(token.strip() for token in raw.split(",") if token.strip())


def _parse_params(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    return dict(json.loads(raw))


def _token(value: Any) -> str:
    return str(value).replace(".", "p").replace("-", "m")


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


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")


def _selected_config(
    accepted: Mapping[str, Any],
    *,
    run_id: str,
    runtime_source: str,
    a_count: int,
    b_count: int,
    k: int,
    top_cuts: int,
    max_iterations: int,
    separation_pool_cuts: int = 0,
    epsilon_cert: float,
    master_time_limit_seconds: float,
    master_mip_gap: float,
    separation_time_limit_seconds: float,
    separation_mip_gap: float,
    omega_bound_upper: float,
    warm_start_plan_paths: Sequence[Path],
    initial_cut_pool_paths: Sequence[Path],
    initial_active_outage_pattern_paths: Sequence[Path] = (),
    master_gurobi_params: Mapping[str, Any],
    separation_gurobi_params: Mapping[str, Any],
    acceleration_role: str,
    seed_run_id: str = "",
    enable_live_iteration_trace: bool = True,
    adaptive_top_cuts_switch_violation: float | None = None,
    adaptive_top_cuts_after_switch: int = 1,
    adaptive_stall_window_iterations: int = 0,
    adaptive_stall_min_relative_improvement: float = 0.0,
    allow_nonoptimal_separation_cuts: bool = False,
    nonoptimal_separation_cut_tolerance: float | None = None,
    enable_pareto_core_cuts: bool = False,
    stabilization_mode: str | None = None,
    stabilization_z_radius: int | None = None,
    stabilization_charger_sl_radius: int | None = None,
    stabilization_charger_fa_radius: int | None = None,
    stabilization_center_update_policy: str = "fixed",
    enable_level_bundle_trial: bool = False,
    level_bundle_objective_slack_abs: float = 5000.0,
    level_bundle_objective_slack_fraction: float = 0.05,
    level_bundle_rho_n: float = 0.2,
    level_bundle_rho_alpha: float = 0.05,
    level_bundle_rho_lambda: float = 1.0,
    enable_active_set_cuts: bool = False,
    active_delta_max: int = 50,
    active_neighbor_radius: int = 1,
    active_max_candidates_per_iteration: int = 5,
    active_cuts_per_iteration: int = 3,
    active_select_top_violations: bool = False,
    active_min_hamming_distance: int = 0,
    enable_exact_outage_rows: bool = False,
    exact_rows_per_iteration: int = 0,
    exact_row_max: int = 30,
    exact_rows_include_active: bool = True,
    enable_nccg_outage_columns: bool = False,
    nccg_keep_global_cuts: bool = False,
    nccg_complete_active_columns: bool = False,
    nccg_completion_tolerance: float = 100.0,
    nccg_completion_max_cuts_per_iteration: int = 5,
    nccg_completion_order: str = "oldest",
    enable_persistent_pricing_pool: bool = False,
    pricing_capture_passes: int = 0,
    pricing_capture_diversity_radius: int = 4,
    cross_column_broadcast: bool = False,
    broadcast_top_columns: int = 30,
    broadcast_violation_tolerance: float = 100.0,
    enable_certified_serious_step: bool = False,
    serious_level_kappa: float = 0.35,
    serious_eta_ub: float = 0.01,
    serious_tau_ub: float = 10.0,
    serious_eta_violation: float = 0.15,
    serious_chi: float = 0.05,
    serious_null_limit: int = 3,
    enable_target_face_bundle_cuts: bool = False,
    target_face_candidate_limit: int = 30,
    target_face_cuts_per_iteration: int = 6,
    target_face_neighbor_radius: int = 1,
    target_face_add_violation_fraction: float = 0.01,
    target_face_tolerance_rel: float = 1e-6,
    enable_cluster_face_bundle_cuts: bool = False,
    cluster_face_candidate_limit: int = 30,
    cluster_face_cuts_per_iteration: int = 2,
    cluster_face_add_violation_fraction: float = 0.01,
    cluster_face_tolerance_rel: float = 1e-6,
    enable_lambda_face_prox_trial: bool = False,
    lambda_face_level_slack_abs: float = 500.0,
    lambda_face_level_slack_fraction: float = 0.05,
    lambda_face_rho_alpha: float = 0.05,
    enable_alpha_lambda_warm_start: bool = True,
    math_change: str = "none",
) -> dict[str, Any]:
    config = json.loads(json.dumps(dict(accepted)))
    config.update(
        {
            "run_id": run_id,
            "case_name": run_id,
            "family_name": "engineering_acceleration",
            "runtime_source": runtime_source,
            "mode": "integrated_mainline",
            "solver": "benders",
            "parameter_regime": CURRENT_DEFAULT_REGIME,
            "selection": {
                "scenarios_a": list(range(1, int(a_count) + 1)),
                "scenarios_b": list(range(1, int(b_count) + 1)),
            },
            "engineering_acceleration": {
                "role": acceleration_role,
                "seed_run_id": seed_run_id,
                "paper_final_safe": True,
                "math_change": str(math_change),
            },
        }
    )
    overrides = dict(config.get("parameter_overrides", {}))
    ambiguity = dict(overrides.get("ambiguity", {}))
    ambiguity["k_max_outages"] = int(k)
    overrides["ambiguity"] = ambiguity
    config["parameter_overrides"] = overrides
    config["benders"] = {
        "epsilon_cert": float(epsilon_cert),
        "max_iterations": int(max_iterations),
        "master_time_limit_seconds": float(master_time_limit_seconds),
        "master_mip_gap": float(master_mip_gap),
        "separation_time_limit_seconds": float(separation_time_limit_seconds),
        "separation_mip_gap": float(separation_mip_gap),
        "separation_top_cuts_per_iteration": int(top_cuts),
        "separation_pool_cuts_per_iteration": int(separation_pool_cuts),
        "allow_master_suboptimal_incumbent": True,
        "enable_cut_signature_dedup": True,
        "enable_repeated_outage_guard": False,
        "omega_bound_upper": float(omega_bound_upper),
        "warm_start_plan_paths": [str(path) for path in warm_start_plan_paths if path.exists()],
        "initial_cut_pool_paths": [str(path) for path in initial_cut_pool_paths if path.exists()],
        "initial_active_outage_pattern_paths": [
            str(path) for path in initial_active_outage_pattern_paths if path.exists()
        ],
        "master_gurobi_params": dict(master_gurobi_params),
        "separation_gurobi_params": dict(separation_gurobi_params),
        "enable_live_iteration_trace": bool(enable_live_iteration_trace),
        "adaptive_top_cuts_switch_violation": adaptive_top_cuts_switch_violation,
        "adaptive_top_cuts_after_switch": int(adaptive_top_cuts_after_switch),
        "adaptive_stall_window_iterations": int(adaptive_stall_window_iterations),
        "adaptive_stall_min_relative_improvement": float(
            adaptive_stall_min_relative_improvement
        ),
        "allow_nonoptimal_separation_cuts": bool(allow_nonoptimal_separation_cuts),
        "nonoptimal_separation_cut_tolerance": nonoptimal_separation_cut_tolerance,
        "enable_pareto_core_cuts": bool(enable_pareto_core_cuts),
        "enable_level_bundle_trial": bool(enable_level_bundle_trial),
        "level_bundle_objective_slack_abs": float(level_bundle_objective_slack_abs),
        "level_bundle_objective_slack_fraction": float(
            level_bundle_objective_slack_fraction
        ),
        "level_bundle_rho_n": float(level_bundle_rho_n),
        "level_bundle_rho_alpha": float(level_bundle_rho_alpha),
        "level_bundle_rho_lambda": float(level_bundle_rho_lambda),
        "enable_active_set_cuts": bool(enable_active_set_cuts),
        "active_delta_max": int(active_delta_max),
        "active_neighbor_radius": int(active_neighbor_radius),
        "active_max_candidates_per_iteration": int(active_max_candidates_per_iteration),
        "active_cuts_per_iteration": int(active_cuts_per_iteration),
        "active_select_top_violations": bool(active_select_top_violations),
        "active_min_hamming_distance": int(active_min_hamming_distance),
        "enable_exact_outage_rows": bool(enable_exact_outage_rows),
        "exact_rows_per_iteration": int(exact_rows_per_iteration),
        "exact_row_max": int(exact_row_max),
        "exact_rows_include_active": bool(exact_rows_include_active),
        "enable_nccg_outage_columns": bool(enable_nccg_outage_columns),
        "nccg_keep_global_cuts": bool(nccg_keep_global_cuts),
        "nccg_complete_active_columns": bool(nccg_complete_active_columns),
        "nccg_completion_tolerance": float(nccg_completion_tolerance),
        "nccg_completion_max_cuts_per_iteration": int(
            nccg_completion_max_cuts_per_iteration
        ),
        "nccg_completion_order": str(nccg_completion_order or "oldest"),
        "enable_persistent_pricing_pool": bool(enable_persistent_pricing_pool),
        "pricing_capture_passes": int(pricing_capture_passes),
        "pricing_capture_diversity_radius": int(pricing_capture_diversity_radius),
        "cross_column_broadcast": bool(cross_column_broadcast),
        "broadcast_top_columns": int(broadcast_top_columns),
        "broadcast_violation_tolerance": float(broadcast_violation_tolerance),
        "enable_certified_serious_step": bool(enable_certified_serious_step),
        "serious_level_kappa": float(serious_level_kappa),
        "serious_eta_ub": float(serious_eta_ub),
        "serious_tau_ub": float(serious_tau_ub),
        "serious_eta_violation": float(serious_eta_violation),
        "serious_chi": float(serious_chi),
        "serious_null_limit": int(serious_null_limit),
        "enable_target_face_bundle_cuts": bool(enable_target_face_bundle_cuts),
        "target_face_candidate_limit": int(target_face_candidate_limit),
        "target_face_cuts_per_iteration": int(target_face_cuts_per_iteration),
        "target_face_neighbor_radius": int(target_face_neighbor_radius),
        "target_face_add_violation_fraction": float(target_face_add_violation_fraction),
        "target_face_tolerance_rel": float(target_face_tolerance_rel),
        "enable_cluster_face_bundle_cuts": bool(enable_cluster_face_bundle_cuts),
        "cluster_face_candidate_limit": int(cluster_face_candidate_limit),
        "cluster_face_cuts_per_iteration": int(cluster_face_cuts_per_iteration),
        "cluster_face_add_violation_fraction": float(cluster_face_add_violation_fraction),
        "cluster_face_tolerance_rel": float(cluster_face_tolerance_rel),
        "enable_lambda_face_prox_trial": bool(enable_lambda_face_prox_trial),
        "lambda_face_level_slack_abs": float(lambda_face_level_slack_abs),
        "lambda_face_level_slack_fraction": float(lambda_face_level_slack_fraction),
        "lambda_face_rho_alpha": float(lambda_face_rho_alpha),
        "enable_alpha_lambda_warm_start": bool(enable_alpha_lambda_warm_start),
    }
    if stabilization_mode not in (None, "", "none"):
        config["benders"]["stabilization_mode"] = str(stabilization_mode)
    if stabilization_z_radius is not None:
        config["benders"]["stabilization_z_radius"] = int(stabilization_z_radius)
    if stabilization_charger_sl_radius is not None:
        config["benders"]["stabilization_charger_sl_radius"] = int(
            stabilization_charger_sl_radius
        )
    if stabilization_charger_fa_radius is not None:
        config["benders"]["stabilization_charger_fa_radius"] = int(
            stabilization_charger_fa_radius
        )
    config["benders"]["stabilization_center_update_policy"] = str(
        stabilization_center_update_policy or "fixed"
    )
    return config


def _seed_paths(seed_run_id: str) -> tuple[Path, Path]:
    return (
        PAPER_SCALING_ROOT / "plans" / f"{seed_run_id}_plan.csv",
        PAPER_SCALING_ROOT / "logs" / f"{seed_run_id}_cut_pool.json",
    )


def _planned_continuation_configs(
    accepted: Mapping[str, Any],
    *,
    runtime_source: str,
    k_values: Sequence[int],
    include_b100: bool,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for k in k_values:
        seed_run_id = f"full_benders_A10_B010_K{k:02d}_top003"
        seed_plan, seed_cut_pool = _seed_paths(seed_run_id)
        if not seed_cut_pool.exists():
            continue
        run_id = (
            f"eng_continuation_A10_B010_K{k:02d}_top{args.top_cuts:03d}_"
            f"seed_existing_add{args.continuation_iterations:03d}"
        )
        configs.append(
            _selected_config(
                accepted,
                run_id=run_id,
                runtime_source=runtime_source,
                a_count=10,
                b_count=10,
                k=k,
                top_cuts=args.top_cuts,
                max_iterations=args.continuation_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
                warm_start_plan_paths=[seed_plan, PAPER_DEFAULT_PLAN],
                initial_cut_pool_paths=[seed_cut_pool],
                master_gurobi_params=args.master_gurobi_params,
                separation_gurobi_params=args.separation_gurobi_params,
                acceleration_role="same_support_cut_pool_continuation",
                seed_run_id=seed_run_id,
                enable_live_iteration_trace=args.enable_live_trace,
                adaptive_stall_window_iterations=args.adaptive_stall_window_iterations,
                adaptive_stall_min_relative_improvement=(
                    args.adaptive_stall_min_relative_improvement
                ),
            )
        )
    if include_b100:
        seed_run_id = "full_benders_A10_B100_K02_top003"
        seed_plan, seed_cut_pool = _seed_paths(seed_run_id)
        if seed_cut_pool.exists():
            configs.append(
                _selected_config(
                    accepted,
                    run_id=(
                        f"eng_continuation_A10_B100_K02_top{args.b100_top_cuts:03d}_"
                        f"seed_existing_add{args.b100_continuation_iterations:03d}_"
                        f"sep{int(args.b100_separation_time_limit_seconds):03d}"
                    ),
                    runtime_source=runtime_source,
                    a_count=10,
                    b_count=100,
                    k=2,
                    top_cuts=args.b100_top_cuts,
                    max_iterations=args.b100_continuation_iterations,
                    epsilon_cert=args.epsilon_cert,
                    master_time_limit_seconds=args.master_time_limit_seconds,
                    master_mip_gap=args.master_mip_gap,
                    separation_time_limit_seconds=args.b100_separation_time_limit_seconds,
                    separation_mip_gap=args.separation_mip_gap,
                    omega_bound_upper=args.omega_bound_upper,
                    warm_start_plan_paths=[seed_plan, PAPER_DEFAULT_PLAN],
                    initial_cut_pool_paths=[seed_cut_pool],
                    master_gurobi_params=args.master_gurobi_params,
                    separation_gurobi_params=args.separation_gurobi_params,
                    acceleration_role="b100_same_support_cut_pool_continuation",
                    seed_run_id=seed_run_id,
                    enable_live_iteration_trace=args.enable_live_trace,
                    adaptive_stall_window_iterations=args.adaptive_stall_window_iterations,
                    adaptive_stall_min_relative_improvement=(
                        args.adaptive_stall_min_relative_improvement
                    ),
                )
            )
    return configs


def _planned_topm_configs(
    accepted: Mapping[str, Any],
    *,
    runtime_source: str,
    top_values: Sequence[int],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    seed_run_id = "full_benders_A10_B010_K05_top003"
    seed_plan, seed_cut_pool = _seed_paths(seed_run_id)
    return [
        _selected_config(
            accepted,
            run_id=(
                f"eng_topm_policy_A10_B010_K05_top{top:03d}_"
                f"seed_existing_add{args.ablation_iterations:03d}"
            ),
            runtime_source=runtime_source,
            a_count=10,
            b_count=10,
            k=5,
            top_cuts=top,
            max_iterations=args.ablation_iterations,
            epsilon_cert=args.epsilon_cert,
            master_time_limit_seconds=args.master_time_limit_seconds,
            master_mip_gap=args.master_mip_gap,
            separation_time_limit_seconds=args.separation_time_limit_seconds,
            separation_mip_gap=args.separation_mip_gap,
            omega_bound_upper=args.omega_bound_upper,
            warm_start_plan_paths=[seed_plan, PAPER_DEFAULT_PLAN],
            initial_cut_pool_paths=[seed_cut_pool],
            master_gurobi_params=args.master_gurobi_params,
            separation_gurobi_params=args.separation_gurobi_params,
            acceleration_role="top_m_policy_seeded",
            seed_run_id=seed_run_id,
            enable_live_iteration_trace=args.enable_live_trace,
            adaptive_stall_window_iterations=args.adaptive_stall_window_iterations,
            adaptive_stall_min_relative_improvement=(
                args.adaptive_stall_min_relative_improvement
            ),
        )
        for top in top_values
    ]


def _planned_adaptive_topm_configs(
    accepted: Mapping[str, Any],
    *,
    runtime_source: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    seed_run_id = "full_benders_A10_B010_K05_top003"
    seed_plan, seed_cut_pool = _seed_paths(seed_run_id)
    return [
        _selected_config(
            accepted,
            run_id=(
                "eng_adaptive_topm_A10_B010_K05_top003_to001_"
                f"thr{_token(args.adaptive_topm_switch_violation)}_"
                f"seed_existing_add{args.adaptive_topm_iterations:03d}"
            ),
            runtime_source=runtime_source,
            a_count=10,
            b_count=10,
            k=5,
            top_cuts=3,
            max_iterations=args.adaptive_topm_iterations,
            epsilon_cert=args.epsilon_cert,
            master_time_limit_seconds=args.master_time_limit_seconds,
            master_mip_gap=args.master_mip_gap,
            separation_time_limit_seconds=args.separation_time_limit_seconds,
            separation_mip_gap=args.separation_mip_gap,
            omega_bound_upper=args.omega_bound_upper,
            warm_start_plan_paths=[seed_plan, PAPER_DEFAULT_PLAN],
            initial_cut_pool_paths=[seed_cut_pool],
            master_gurobi_params=args.master_gurobi_params,
            separation_gurobi_params=args.separation_gurobi_params,
            acceleration_role="adaptive_top_m_policy_seeded",
            seed_run_id=seed_run_id,
            enable_live_iteration_trace=args.enable_live_trace,
            adaptive_top_cuts_switch_violation=float(args.adaptive_topm_switch_violation),
            adaptive_top_cuts_after_switch=1,
            adaptive_stall_window_iterations=args.adaptive_stall_window_iterations,
            adaptive_stall_min_relative_improvement=(
                args.adaptive_stall_min_relative_improvement
            ),
        )
    ]


def _planned_hard_k_probe_configs(
    accepted: Mapping[str, Any],
    *,
    runtime_source: str,
    k_values: Sequence[int],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    for k in k_values:
        seed_run_id = f"fresh_default_plan_A10_B010_K{k:02d}"
        run_id = (
            f"eng_fresh_hard_k_probe_A10_B010_K{k:02d}_"
            f"top{args.hard_k_top_cuts:03d}_max{args.hard_k_iterations:03d}"
        )
        configs.append(
            _selected_config(
                accepted,
                run_id=run_id,
                runtime_source=runtime_source,
                a_count=10,
                b_count=10,
                k=k,
                top_cuts=args.hard_k_top_cuts,
                max_iterations=args.hard_k_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
                warm_start_plan_paths=[PAPER_DEFAULT_PLAN],
                initial_cut_pool_paths=[],
                master_gurobi_params=args.master_gurobi_params,
                separation_gurobi_params=args.separation_gurobi_params,
                acceleration_role="fresh_hard_k_probe",
                seed_run_id=seed_run_id,
                enable_live_iteration_trace=args.enable_live_trace,
                adaptive_stall_window_iterations=args.adaptive_stall_window_iterations,
                adaptive_stall_min_relative_improvement=(
                    args.adaptive_stall_min_relative_improvement
                ),
            )
        )
    return configs


def _planned_fast_incumbent_configs(
    accepted: Mapping[str, Any],
    *,
    args: argparse.Namespace,
    k_values: Sequence[int],
    include_b100: bool,
) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    plan_path, cut_pool_path = _seed_paths("full_benders_A10_B010_K05_top003")
    for k in k_values:
        run_id = (
            f"eng_fast_incumbent_A10_B010_K{k:02d}_"
            f"top001_max{args.fast_incumbent_iterations:03d}_"
            f"sep{int(args.fast_incumbent_separation_time_limit_seconds):03d}"
        )
        configs.append(
            _selected_config(
                accepted,
                run_id=run_id,
                runtime_source=args.runtime_source,
                a_count=10,
                b_count=10,
                k=int(k),
                top_cuts=1,
                max_iterations=args.fast_incumbent_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.fast_incumbent_separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
                warm_start_plan_paths=[plan_path],
                initial_cut_pool_paths=[cut_pool_path],
                master_gurobi_params=args.master_gurobi_params,
                separation_gurobi_params=args.separation_gurobi_params,
                acceleration_role="fast_incumbent_cut_prototype",
                seed_run_id="full_benders_A10_B010_K05_top003",
                enable_live_iteration_trace=args.enable_live_trace,
                adaptive_stall_window_iterations=args.adaptive_stall_window_iterations,
                adaptive_stall_min_relative_improvement=(
                    args.adaptive_stall_min_relative_improvement
                ),
                allow_nonoptimal_separation_cuts=True,
                nonoptimal_separation_cut_tolerance=args.fast_incumbent_cut_tolerance,
                math_change="pro_approved_fast_incumbent_cuts",
            )
        )
    if include_b100:
        b100_plan, b100_cut_pool = _seed_paths("full_benders_A10_B100_K02_top003")
        run_id = (
            f"eng_fast_incumbent_A10_B100_K02_top001_"
            f"max{args.fast_incumbent_b100_iterations:03d}_"
            f"sep{int(args.fast_incumbent_b100_separation_time_limit_seconds):03d}"
        )
        configs.append(
            _selected_config(
                accepted,
                run_id=run_id,
                runtime_source=args.runtime_source,
                a_count=10,
                b_count=100,
                k=2,
                top_cuts=1,
                max_iterations=args.fast_incumbent_b100_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=(
                    args.fast_incumbent_b100_separation_time_limit_seconds
                ),
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
                warm_start_plan_paths=[b100_plan],
                initial_cut_pool_paths=[b100_cut_pool],
                master_gurobi_params=args.master_gurobi_params,
                separation_gurobi_params=args.separation_gurobi_params,
                acceleration_role="fast_incumbent_b100_cut_prototype",
                seed_run_id="full_benders_A10_B100_K02_top003",
                enable_live_iteration_trace=args.enable_live_trace,
                adaptive_stall_window_iterations=args.adaptive_stall_window_iterations,
                adaptive_stall_min_relative_improvement=(
                    args.adaptive_stall_min_relative_improvement
                ),
                allow_nonoptimal_separation_cuts=True,
                nonoptimal_separation_cut_tolerance=args.fast_incumbent_cut_tolerance,
                math_change="pro_approved_fast_incumbent_cuts",
            )
        )
    return configs


def _planned_pareto_core_configs(
    accepted: Mapping[str, Any],
    *,
    args: argparse.Namespace,
    k_values: Sequence[int],
) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    plan_path, cut_pool_path = _seed_paths("full_benders_A10_B010_K05_top003")
    for k in k_values:
        run_id = (
            f"eng_pareto_core_A10_B010_K{k:02d}_top001_"
            f"max{args.pareto_core_iterations:03d}"
        )
        configs.append(
            _selected_config(
                accepted,
                run_id=run_id,
                runtime_source=args.runtime_source,
                a_count=10,
                b_count=10,
                k=int(k),
                top_cuts=1,
                max_iterations=args.pareto_core_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
                warm_start_plan_paths=[plan_path],
                initial_cut_pool_paths=[cut_pool_path],
                master_gurobi_params=args.master_gurobi_params,
                separation_gurobi_params=args.separation_gurobi_params,
                acceleration_role="pareto_core_cut_prototype",
                seed_run_id="full_benders_A10_B010_K05_top003",
                enable_live_iteration_trace=args.enable_live_trace,
                adaptive_stall_window_iterations=args.adaptive_stall_window_iterations,
                adaptive_stall_min_relative_improvement=(
                    args.adaptive_stall_min_relative_improvement
                ),
                enable_pareto_core_cuts=True,
                math_change="pro_approved_fixed_support_pareto_core_cuts",
            )
        )
    return configs


def _planned_stabilization_configs(
    accepted: Mapping[str, Any],
    *,
    args: argparse.Namespace,
    k_values: Sequence[int],
) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    k5_plan, k5_cut_pool = _seed_paths("full_benders_A10_B010_K05_top003")
    cli_warm_start_plan_paths = [
        Path(path) for path in _parse_list(args.warm_start_plan_paths)
    ]
    cli_initial_cut_pool_paths = [
        Path(path) for path in _parse_list(args.initial_cut_pool_paths)
    ]
    for k in k_values:
        max_iterations = (
            int(args.stabilization_k5_iterations)
            if int(k) == 5
            else int(args.stabilization_hard_k_iterations)
        )
        warm_starts = [k5_plan] if k5_plan.exists() else []
        initial_cuts = [k5_cut_pool] if int(k) == 5 and k5_cut_pool.exists() else []
        mode_token = str(args.stabilization_mode).replace("_", "")
        run_id = (
            f"eng_stabilized_{mode_token}_A10_B010_K{int(k):02d}_"
            f"top{int(args.stabilization_top_cuts):03d}_"
            f"max{max_iterations:03d}_r{int(args.stabilization_z_radius):02d}"
        )
        if args.stabilization_mode == "local_branch_z_n":
            run_id += (
                f"_sl{int(args.stabilization_sl_radius):02d}"
                f"_fa{int(args.stabilization_fa_radius):02d}"
            )
        configs.append(
            _selected_config(
                accepted,
                run_id=run_id,
                runtime_source=args.runtime_source,
                a_count=10,
                b_count=10,
                k=int(k),
                top_cuts=int(args.stabilization_top_cuts),
                max_iterations=max_iterations,
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
                warm_start_plan_paths=warm_starts,
                initial_cut_pool_paths=initial_cuts,
                master_gurobi_params=args.master_gurobi_params,
                separation_gurobi_params=args.separation_gurobi_params,
                acceleration_role=f"stabilized_{args.stabilization_mode}_probe",
                seed_run_id="full_benders_A10_B010_K05_top003",
                enable_live_iteration_trace=args.enable_live_trace,
                adaptive_stall_window_iterations=0,
                adaptive_stall_min_relative_improvement=0.0,
                stabilization_mode=args.stabilization_mode,
                stabilization_z_radius=int(args.stabilization_z_radius),
                stabilization_charger_sl_radius=(
                    int(args.stabilization_sl_radius)
                    if args.stabilization_mode == "local_branch_z_n"
                    else None
                ),
                stabilization_charger_fa_radius=(
                    int(args.stabilization_fa_radius)
                    if args.stabilization_mode == "local_branch_z_n"
                    else None
                ),
                math_change="pro_approved_stabilized_trial_points",
            )
        )
    return configs


def _planned_active_set_configs(
    accepted: Mapping[str, Any],
    *,
    args: argparse.Namespace,
    k_values: Sequence[int],
) -> list[dict[str, Any]]:
    configs: list[dict[str, Any]] = []
    k5_plan, k5_cut_pool = _seed_paths("full_benders_A10_B010_K05_top003")
    cli_warm_start_plan_paths = [
        Path(path) for path in _parse_list(args.warm_start_plan_paths)
    ]
    cli_initial_cut_pool_paths = [
        Path(path) for path in _parse_list(args.initial_cut_pool_paths)
    ]
    for k in k_values:
        mode_token = str(args.active_set_stabilization_mode).replace("_", "")
        run_id = (
            f"eng_active_set_{mode_token}_A10_B010_K{int(k):02d}_"
            f"top{int(args.active_set_top_cuts):03d}_"
            f"max{int(args.active_set_iterations):03d}_"
            f"pool{int(args.active_delta_max):03d}_"
            f"cand{int(args.active_max_candidates):02d}_"
            f"cuts{int(args.active_cuts_per_iteration):02d}"
        )
        if bool(args.active_set_enable_exact_outage_rows):
            run_id = (
                f"{run_id}_exactr{int(args.exact_rows_per_iteration):02d}"
                f"_emax{int(args.exact_row_max):03d}"
            )
        if bool(args.active_set_enable_target_face_bundle_cuts):
            run_id = (
                f"{run_id}_tface{int(args.target_face_cuts_per_iteration):02d}"
                f"_tcand{int(args.target_face_candidate_limit):02d}"
            )
        if bool(args.active_set_enable_cluster_face_bundle_cuts):
            run_id = (
                f"{run_id}_cface{int(args.cluster_face_cuts_per_iteration):02d}"
                f"_ccand{int(args.cluster_face_candidate_limit):02d}"
            )
        if bool(args.active_set_enable_lambda_face_prox_trial):
            run_id = f"{run_id}_lface"
        if bool(args.active_set_enable_level_bundle_trial):
            slack_token = _token(args.level_bundle_objective_slack_abs)
            frac_token = _token(args.level_bundle_objective_slack_fraction)
            lambda_token = _token(args.level_bundle_rho_lambda)
            run_id = (
                f"{run_id}_levelbundle_s{slack_token}_f{frac_token}"
                f"_rl{lambda_token}"
            )
        if str(args.active_set_stabilization_center_update_policy) != "fixed":
            policy_token = str(args.active_set_stabilization_center_update_policy).replace(
                "_",
                "",
            )
            run_id = f"{run_id}_{policy_token}"
        if bool(args.active_set_enable_nccg_outage_columns):
            run_id = f"{run_id}_nccg"
            if bool(args.nccg_keep_global_cuts):
                run_id = f"{run_id}_global"
            if bool(args.nccg_complete_active_columns):
                run_id = (
                    f"{run_id}_complete{int(args.nccg_completion_max_cuts):02d}"
                    f"_{args.nccg_completion_order}"
                )
            if bool(args.enable_persistent_pricing_pool):
                run_id = (
                    f"{run_id}_pfpb{int(args.pricing_capture_passes):02d}"
                    f"_r{int(args.pricing_capture_diversity_radius):02d}"
                )
            if bool(args.cross_column_broadcast):
                run_id = (
                    f"{run_id}_cb{int(args.broadcast_top_columns):02d}"
                    f"_tol{_token(args.broadcast_violation_tolerance)}"
                )
            if bool(args.enable_certified_serious_step):
                run_id = (
                    f"{run_id}_cs_k{_token(args.serious_level_kappa)}"
                    f"_ev{_token(args.serious_eta_violation)}"
                    f"_n{int(args.serious_null_limit):02d}"
                )
        configs.append(
            _selected_config(
                accepted,
                run_id=run_id,
                runtime_source=args.runtime_source,
                a_count=10,
                b_count=10,
                k=int(k),
                top_cuts=int(args.active_set_top_cuts),
                max_iterations=int(args.active_set_iterations),
                separation_pool_cuts=int(args.active_set_separation_pool_cuts),
                epsilon_cert=args.epsilon_cert,
                master_time_limit_seconds=args.master_time_limit_seconds,
                master_mip_gap=args.master_mip_gap,
                separation_time_limit_seconds=args.separation_time_limit_seconds,
                separation_mip_gap=args.separation_mip_gap,
                omega_bound_upper=args.omega_bound_upper,
                warm_start_plan_paths=(
                    cli_warm_start_plan_paths
                    if cli_warm_start_plan_paths
                    else ([k5_plan] if k5_plan.exists() else [])
                ),
                initial_cut_pool_paths=(
                    cli_initial_cut_pool_paths
                    if cli_initial_cut_pool_paths
                    else ([k5_cut_pool] if int(k) == 5 and k5_cut_pool.exists() else [])
                ),
                initial_active_outage_pattern_paths=[
                    Path(path)
                    for path in _parse_list(args.initial_active_outage_pattern_paths)
                ],
                master_gurobi_params=args.master_gurobi_params,
                separation_gurobi_params=args.separation_gurobi_params,
                acceleration_role="active_set_fullB_validated_probe",
                seed_run_id="full_benders_A10_B010_K05_top003",
                enable_live_iteration_trace=args.enable_live_trace,
                adaptive_stall_window_iterations=0,
                adaptive_stall_min_relative_improvement=0.0,
                stabilization_mode=args.active_set_stabilization_mode,
                stabilization_z_radius=int(args.active_set_stabilization_z_radius),
                stabilization_charger_sl_radius=(
                    int(args.active_set_stabilization_sl_radius)
                    if args.active_set_stabilization_mode == "local_branch_z_n"
                    else None
                ),
                stabilization_charger_fa_radius=(
                    int(args.active_set_stabilization_fa_radius)
                    if args.active_set_stabilization_mode == "local_branch_z_n"
                    else None
                ),
                stabilization_center_update_policy=(
                    args.active_set_stabilization_center_update_policy
                ),
                enable_level_bundle_trial=bool(args.active_set_enable_level_bundle_trial),
                level_bundle_objective_slack_abs=float(
                    args.level_bundle_objective_slack_abs
                ),
                level_bundle_objective_slack_fraction=float(
                    args.level_bundle_objective_slack_fraction
                ),
                level_bundle_rho_n=float(args.level_bundle_rho_n),
                level_bundle_rho_alpha=float(args.level_bundle_rho_alpha),
                level_bundle_rho_lambda=float(args.level_bundle_rho_lambda),
                enable_active_set_cuts=True,
                active_delta_max=int(args.active_delta_max),
                active_neighbor_radius=int(args.active_neighbor_radius),
                active_max_candidates_per_iteration=int(args.active_max_candidates),
                active_cuts_per_iteration=int(args.active_cuts_per_iteration),
                active_select_top_violations=bool(args.active_select_top_violations),
                active_min_hamming_distance=int(args.active_min_hamming_distance),
                enable_exact_outage_rows=bool(args.active_set_enable_exact_outage_rows),
                exact_rows_per_iteration=int(args.exact_rows_per_iteration),
                exact_row_max=int(args.exact_row_max),
                exact_rows_include_active=not bool(args.exact_rows_exclude_active),
                enable_nccg_outage_columns=bool(
                    args.active_set_enable_nccg_outage_columns
                ),
                nccg_keep_global_cuts=bool(args.nccg_keep_global_cuts),
                nccg_complete_active_columns=bool(args.nccg_complete_active_columns),
                nccg_completion_tolerance=float(args.nccg_completion_tolerance),
                nccg_completion_max_cuts_per_iteration=int(
                    args.nccg_completion_max_cuts
                ),
                nccg_completion_order=str(args.nccg_completion_order),
                enable_persistent_pricing_pool=bool(args.enable_persistent_pricing_pool),
                pricing_capture_passes=int(args.pricing_capture_passes),
                pricing_capture_diversity_radius=int(
                    args.pricing_capture_diversity_radius
                ),
                cross_column_broadcast=bool(args.cross_column_broadcast),
                broadcast_top_columns=int(args.broadcast_top_columns),
                broadcast_violation_tolerance=float(args.broadcast_violation_tolerance),
                enable_certified_serious_step=bool(args.enable_certified_serious_step),
                serious_level_kappa=float(args.serious_level_kappa),
                serious_eta_ub=float(args.serious_eta_ub),
                serious_tau_ub=float(args.serious_tau_ub),
                serious_eta_violation=float(args.serious_eta_violation),
                serious_chi=float(args.serious_chi),
                serious_null_limit=int(args.serious_null_limit),
                enable_target_face_bundle_cuts=bool(
                    args.active_set_enable_target_face_bundle_cuts
                ),
                target_face_candidate_limit=int(args.target_face_candidate_limit),
                target_face_cuts_per_iteration=int(args.target_face_cuts_per_iteration),
                target_face_neighbor_radius=int(args.target_face_neighbor_radius),
                target_face_add_violation_fraction=float(
                    args.target_face_add_violation_fraction
                ),
                target_face_tolerance_rel=float(args.target_face_tolerance_rel),
                enable_cluster_face_bundle_cuts=bool(
                    args.active_set_enable_cluster_face_bundle_cuts
                ),
                cluster_face_candidate_limit=int(args.cluster_face_candidate_limit),
                cluster_face_cuts_per_iteration=int(args.cluster_face_cuts_per_iteration),
                cluster_face_add_violation_fraction=float(
                    args.cluster_face_add_violation_fraction
                ),
                cluster_face_tolerance_rel=float(args.cluster_face_tolerance_rel),
                enable_lambda_face_prox_trial=bool(
                    args.active_set_enable_lambda_face_prox_trial
                ),
                lambda_face_level_slack_abs=float(args.lambda_face_level_slack_abs),
                lambda_face_level_slack_fraction=float(
                    args.lambda_face_level_slack_fraction
                ),
                lambda_face_rho_alpha=float(args.lambda_face_rho_alpha),
                enable_alpha_lambda_warm_start=not bool(
                    args.disable_alpha_lambda_warm_start
                ),
                math_change=(
                    "pro_approved_certified_serious_step_pfpb_cb"
                    if bool(args.enable_certified_serious_step)
                    else
                    "pro_approved_persistent_full_pricing_bundle_capture_cross_broadcast"
                    if bool(args.enable_persistent_pricing_pool)
                    or bool(args.cross_column_broadcast)
                    else
                    "pro_approved_level_bundle_nccg_bc"
                    if bool(args.active_set_enable_level_bundle_trial)
                    else
                    "pro_approved_lambda_face_prox_trial"
                    if bool(args.active_set_enable_lambda_face_prox_trial)
                    else
                    "pro_approved_nccg_bc_active_outage_columns_with_completion"
                    if bool(args.nccg_complete_active_columns)
                    else
                    "pro_approved_nccg_bc_active_outage_columns"
                    if bool(args.active_set_enable_nccg_outage_columns)
                    else
                    "pro_approved_cluster_minimax_dual_face_bundle_cuts"
                    if bool(args.active_set_enable_cluster_face_bundle_cuts)
                    else
                    "pro_approved_hybrid_exact_outage_rows"
                    if bool(args.active_set_enable_exact_outage_rows)
                    else "pro_approved_targeted_dual_face_bundle_cuts"
                    if bool(args.active_set_enable_target_face_bundle_cuts)
                    else "pro_approved_active_set_fullB_validated_cuts"
                ),
            )
        )
    return configs


def _planned_solver_grid_configs(
    accepted: Mapping[str, Any],
    *,
    runtime_source: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    seed_run_id = "full_benders_A10_B010_K05_top003"
    seed_plan, seed_cut_pool = _seed_paths(seed_run_id)
    separation_grid = list(
        itertools.product(
            _parse_ints(args.solver_threads_values),
            _parse_ints(args.solver_mipfocus_values),
            _parse_ints(args.solver_presolve_values),
            _parse_ints(args.solver_cuts_values),
            [float(value) for value in args.solver_heuristics_values.split(",") if value],
        )
    )
    configs: list[dict[str, Any]] = []
    for threads, mip_focus, presolve, cuts, heuristics in separation_grid:
        sep_params = {
            "Threads": int(threads),
            "MIPFocus": int(mip_focus),
            "Presolve": int(presolve),
            "Cuts": int(cuts),
            "Heuristics": float(heuristics),
        }
        for master_threads in _parse_ints(args.master_threads_values):
            master_params = {
                "Threads": int(master_threads),
                "MIPFocus": 1,
                "Presolve": 2,
            }
            run_id = (
                "eng_solvergrid_A10_B010_K05_"
                f"mt{master_threads}_st{threads}_mf{mip_focus}_pr{presolve}_"
                f"cuts{cuts}_heu{_token(heuristics)}_top{args.solver_grid_top_cuts:03d}_"
                f"max{args.solver_grid_iterations:03d}"
            )
            configs.append(
                _selected_config(
                    accepted,
                    run_id=run_id,
                    runtime_source=runtime_source,
                    a_count=10,
                    b_count=10,
                    k=5,
                    top_cuts=args.solver_grid_top_cuts,
                    max_iterations=args.solver_grid_iterations,
                    epsilon_cert=args.epsilon_cert,
                    master_time_limit_seconds=args.master_time_limit_seconds,
                    master_mip_gap=args.master_mip_gap,
                    separation_time_limit_seconds=args.separation_time_limit_seconds,
                    separation_mip_gap=args.separation_mip_gap,
                    omega_bound_upper=args.omega_bound_upper,
                    warm_start_plan_paths=[seed_plan, PAPER_DEFAULT_PLAN],
                    initial_cut_pool_paths=[seed_cut_pool],
                    master_gurobi_params=master_params,
                    separation_gurobi_params=sep_params,
                    acceleration_role="solver_parameter_grid",
                    seed_run_id=seed_run_id,
                    enable_live_iteration_trace=args.enable_live_trace,
                    adaptive_stall_window_iterations=0,
                    adaptive_stall_min_relative_improvement=0.0,
                )
            )
    if args.max_solver_grid_runs > 0:
        configs = configs[: args.max_solver_grid_runs]
    return configs


def _plan_row(config: Mapping[str, Any]) -> dict[str, Any]:
    benders = config.get("benders", {})
    return {
        "run_id": config["run_id"],
        "role": config.get("engineering_acceleration", {}).get("role", ""),
        "seed_run_id": config.get("engineering_acceleration", {}).get("seed_run_id", ""),
        "A": len(config.get("selection", {}).get("scenarios_a", [])),
        "B": len(config.get("selection", {}).get("scenarios_b", [])),
        "K": config.get("parameter_overrides", {}).get("ambiguity", {}).get("k_max_outages", ""),
        "top_cuts": benders.get("separation_top_cuts_per_iteration", ""),
        "separation_pool_cuts_per_iteration": benders.get(
            "separation_pool_cuts_per_iteration", ""
        ),
        "max_iterations": benders.get("max_iterations", ""),
        "warm_start_plan_count": len(benders.get("warm_start_plan_paths", [])),
        "initial_cut_pool_count": len(benders.get("initial_cut_pool_paths", [])),
        "initial_active_outage_pattern_path_count": len(
            benders.get("initial_active_outage_pattern_paths", [])
        ),
        "master_gurobi_params": json.dumps(benders.get("master_gurobi_params", {}), sort_keys=True),
        "separation_gurobi_params": json.dumps(
            benders.get("separation_gurobi_params", {}), sort_keys=True
        ),
        "adaptive_stall_window_iterations": benders.get("adaptive_stall_window_iterations", ""),
        "adaptive_stall_min_relative_improvement": benders.get(
            "adaptive_stall_min_relative_improvement", ""
        ),
        "adaptive_top_cuts_switch_violation": benders.get(
            "adaptive_top_cuts_switch_violation", ""
        ),
        "adaptive_top_cuts_after_switch": benders.get(
            "adaptive_top_cuts_after_switch", ""
        ),
        "allow_nonoptimal_separation_cuts": benders.get(
            "allow_nonoptimal_separation_cuts", ""
        ),
        "nonoptimal_separation_cut_tolerance": benders.get(
            "nonoptimal_separation_cut_tolerance", ""
        ),
        "enable_pareto_core_cuts": benders.get("enable_pareto_core_cuts", ""),
        "stabilization_mode": benders.get("stabilization_mode", ""),
        "stabilization_z_radius": benders.get("stabilization_z_radius", ""),
        "stabilization_charger_sl_radius": benders.get(
            "stabilization_charger_sl_radius", ""
        ),
        "stabilization_charger_fa_radius": benders.get(
            "stabilization_charger_fa_radius", ""
        ),
        "stabilization_center_update_policy": benders.get(
            "stabilization_center_update_policy", ""
        ),
        "enable_level_bundle_trial": benders.get("enable_level_bundle_trial", ""),
        "level_bundle_objective_slack_abs": benders.get(
            "level_bundle_objective_slack_abs", ""
        ),
        "level_bundle_objective_slack_fraction": benders.get(
            "level_bundle_objective_slack_fraction", ""
        ),
        "level_bundle_rho_n": benders.get("level_bundle_rho_n", ""),
        "level_bundle_rho_alpha": benders.get("level_bundle_rho_alpha", ""),
        "level_bundle_rho_lambda": benders.get("level_bundle_rho_lambda", ""),
        "enable_active_set_cuts": benders.get("enable_active_set_cuts", ""),
        "active_delta_max": benders.get("active_delta_max", ""),
        "active_neighbor_radius": benders.get("active_neighbor_radius", ""),
        "active_max_candidates_per_iteration": benders.get(
            "active_max_candidates_per_iteration", ""
        ),
        "active_cuts_per_iteration": benders.get("active_cuts_per_iteration", ""),
        "active_select_top_violations": benders.get("active_select_top_violations", ""),
        "active_min_hamming_distance": benders.get("active_min_hamming_distance", ""),
        "enable_exact_outage_rows": benders.get("enable_exact_outage_rows", ""),
        "exact_rows_per_iteration": benders.get("exact_rows_per_iteration", ""),
        "exact_row_max": benders.get("exact_row_max", ""),
        "exact_rows_include_active": benders.get("exact_rows_include_active", ""),
        "enable_nccg_outage_columns": benders.get("enable_nccg_outage_columns", ""),
        "nccg_keep_global_cuts": benders.get("nccg_keep_global_cuts", ""),
        "nccg_complete_active_columns": benders.get("nccg_complete_active_columns", ""),
        "nccg_completion_tolerance": benders.get("nccg_completion_tolerance", ""),
        "nccg_completion_max_cuts_per_iteration": benders.get(
            "nccg_completion_max_cuts_per_iteration", ""
        ),
        "nccg_completion_order": benders.get("nccg_completion_order", ""),
        "enable_persistent_pricing_pool": benders.get(
            "enable_persistent_pricing_pool", ""
        ),
        "pricing_capture_passes": benders.get("pricing_capture_passes", ""),
        "pricing_capture_diversity_radius": benders.get(
            "pricing_capture_diversity_radius", ""
        ),
        "cross_column_broadcast": benders.get("cross_column_broadcast", ""),
        "broadcast_top_columns": benders.get("broadcast_top_columns", ""),
        "broadcast_violation_tolerance": benders.get(
            "broadcast_violation_tolerance", ""
        ),
        "enable_certified_serious_step": benders.get(
            "enable_certified_serious_step", ""
        ),
        "serious_level_kappa": benders.get("serious_level_kappa", ""),
        "serious_eta_ub": benders.get("serious_eta_ub", ""),
        "serious_tau_ub": benders.get("serious_tau_ub", ""),
        "serious_eta_violation": benders.get("serious_eta_violation", ""),
        "serious_chi": benders.get("serious_chi", ""),
        "serious_null_limit": benders.get("serious_null_limit", ""),
        "enable_target_face_bundle_cuts": benders.get(
            "enable_target_face_bundle_cuts", ""
        ),
        "target_face_candidate_limit": benders.get("target_face_candidate_limit", ""),
        "target_face_cuts_per_iteration": benders.get(
            "target_face_cuts_per_iteration", ""
        ),
        "target_face_add_violation_fraction": benders.get(
            "target_face_add_violation_fraction", ""
        ),
        "target_face_tolerance_rel": benders.get("target_face_tolerance_rel", ""),
        "enable_cluster_face_bundle_cuts": benders.get(
            "enable_cluster_face_bundle_cuts", ""
        ),
        "cluster_face_candidate_limit": benders.get(
            "cluster_face_candidate_limit", ""
        ),
        "cluster_face_cuts_per_iteration": benders.get(
            "cluster_face_cuts_per_iteration", ""
        ),
        "cluster_face_add_violation_fraction": benders.get(
            "cluster_face_add_violation_fraction", ""
        ),
        "cluster_face_tolerance_rel": benders.get("cluster_face_tolerance_rel", ""),
        "enable_lambda_face_prox_trial": benders.get(
            "enable_lambda_face_prox_trial", ""
        ),
        "lambda_face_level_slack_abs": benders.get(
            "lambda_face_level_slack_abs", ""
        ),
        "lambda_face_level_slack_fraction": benders.get(
            "lambda_face_level_slack_fraction", ""
        ),
        "lambda_face_rho_alpha": benders.get("lambda_face_rho_alpha", ""),
        "enable_alpha_lambda_warm_start": benders.get(
            "enable_alpha_lambda_warm_start", ""
        ),
        "math_change": config.get("engineering_acceleration", {}).get("math_change", ""),
    }


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _dedupe_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_run_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        run_id = str(row.get("run_id", ""))
        if run_id:
            by_run_id[run_id] = dict(row)
    return list(by_run_id.values())


def _refresh_aggregate_artifacts(output_root: Path) -> None:
    rows: list[dict[str, Any]] = []
    for log_path in sorted((output_root / "runs").glob("*/logs/*_run.json")):
        run_id = log_path.name[: -len("_run.json")]
        try:
            row = _summarize_milp(log_path, run_id=run_id)
        except Exception:
            continue
        payload = json.loads(log_path.read_text(encoding="utf-8"))
        row["acceleration_role"] = (
            payload.get("run_config", {}).get("engineering_acceleration", {}).get("role", "")
        )
        row["seed_run_id"] = (
            payload.get("run_config", {}).get("engineering_acceleration", {}).get("seed_run_id", "")
        )
        row["math_change"] = (
            payload.get("run_config", {}).get("engineering_acceleration", {}).get("math_change", "")
        )
        row["allow_nonoptimal_separation_cuts"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "allow_nonoptimal_separation_cuts", ""
            )
        )
        row["nonoptimal_separation_cut_tolerance"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "nonoptimal_separation_cut_tolerance", ""
            )
        )
        row["enable_pareto_core_cuts"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_pareto_core_cuts", ""
            )
        )
        row["stabilization_mode"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "stabilization_mode", ""
            )
        )
        row["stabilization_z_radius"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "stabilization_z_radius", ""
            )
        )
        row["stabilization_center_update_policy"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "stabilization_center_update_policy", ""
            )
        )
        row["enable_level_bundle_trial"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_level_bundle_trial", ""
            )
        )
        row["level_bundle_objective_slack_abs"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "level_bundle_objective_slack_abs", ""
            )
        )
        row["level_bundle_objective_slack_fraction"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "level_bundle_objective_slack_fraction", ""
            )
        )
        row["level_bundle_rho_n"] = (
            payload.get("run_config", {}).get("benders", {}).get("level_bundle_rho_n", "")
        )
        row["level_bundle_rho_alpha"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "level_bundle_rho_alpha", ""
            )
        )
        row["level_bundle_rho_lambda"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "level_bundle_rho_lambda", ""
            )
        )
        row["enable_active_set_cuts"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_active_set_cuts", ""
            )
        )
        row["initial_active_outage_pattern_path_count"] = len(
            payload.get("run_config", {})
            .get("benders", {})
            .get("initial_active_outage_pattern_paths", [])
        )
        row["active_delta_max"] = (
            payload.get("run_config", {}).get("benders", {}).get("active_delta_max", "")
        )
        row["active_max_candidates_per_iteration"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "active_max_candidates_per_iteration", ""
            )
        )
        row["active_cuts_per_iteration"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "active_cuts_per_iteration", ""
            )
        )
        row["active_select_top_violations"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "active_select_top_violations", ""
            )
        )
        row["active_min_hamming_distance"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "active_min_hamming_distance", ""
            )
        )
        row["enable_exact_outage_rows"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_exact_outage_rows", ""
            )
        )
        row["exact_rows_per_iteration"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "exact_rows_per_iteration", ""
            )
        )
        row["exact_row_max"] = (
            payload.get("run_config", {}).get("benders", {}).get("exact_row_max", "")
        )
        row["exact_rows_include_active"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "exact_rows_include_active", ""
            )
        )
        row["enable_nccg_outage_columns"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_nccg_outage_columns", ""
            )
        )
        row["nccg_keep_global_cuts"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "nccg_keep_global_cuts", ""
            )
        )
        row["nccg_complete_active_columns"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "nccg_complete_active_columns", ""
            )
        )
        row["nccg_completion_tolerance"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "nccg_completion_tolerance", ""
            )
        )
        row["nccg_completion_max_cuts_per_iteration"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "nccg_completion_max_cuts_per_iteration", ""
            )
        )
        row["nccg_completion_order"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "nccg_completion_order", ""
            )
        )
        row["enable_persistent_pricing_pool"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_persistent_pricing_pool", ""
            )
        )
        row["pricing_capture_passes"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "pricing_capture_passes", ""
            )
        )
        row["pricing_capture_diversity_radius"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "pricing_capture_diversity_radius", ""
            )
        )
        row["cross_column_broadcast"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "cross_column_broadcast", ""
            )
        )
        row["broadcast_top_columns"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "broadcast_top_columns", ""
            )
        )
        row["broadcast_violation_tolerance"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "broadcast_violation_tolerance", ""
            )
        )
        row["enable_certified_serious_step"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_certified_serious_step", ""
            )
        )
        row["serious_level_kappa"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "serious_level_kappa", ""
            )
        )
        row["serious_eta_ub"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "serious_eta_ub", ""
            )
        )
        row["serious_tau_ub"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "serious_tau_ub", ""
            )
        )
        row["serious_eta_violation"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "serious_eta_violation", ""
            )
        )
        row["serious_chi"] = (
            payload.get("run_config", {}).get("benders", {}).get("serious_chi", "")
        )
        row["serious_null_limit"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "serious_null_limit", ""
            )
        )
        row["enable_target_face_bundle_cuts"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_target_face_bundle_cuts", ""
            )
        )
        row["target_face_candidate_limit"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "target_face_candidate_limit", ""
            )
        )
        row["target_face_cuts_per_iteration"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "target_face_cuts_per_iteration", ""
            )
        )
        row["target_face_add_violation_fraction"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "target_face_add_violation_fraction", ""
            )
        )
        row["target_face_tolerance_rel"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "target_face_tolerance_rel", ""
            )
        )
        row["enable_cluster_face_bundle_cuts"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_cluster_face_bundle_cuts", ""
            )
        )
        row["cluster_face_candidate_limit"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "cluster_face_candidate_limit", ""
            )
        )
        row["cluster_face_cuts_per_iteration"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "cluster_face_cuts_per_iteration", ""
            )
        )
        row["cluster_face_add_violation_fraction"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "cluster_face_add_violation_fraction", ""
            )
        )
        row["cluster_face_tolerance_rel"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "cluster_face_tolerance_rel", ""
            )
        )
        row["enable_lambda_face_prox_trial"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_lambda_face_prox_trial", ""
            )
        )
        row["lambda_face_level_slack_abs"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "lambda_face_level_slack_abs", ""
            )
        )
        row["lambda_face_level_slack_fraction"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "lambda_face_level_slack_fraction", ""
            )
        )
        row["lambda_face_rho_alpha"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "lambda_face_rho_alpha", ""
            )
        )
        row["enable_alpha_lambda_warm_start"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "enable_alpha_lambda_warm_start", ""
            )
        )
        row["separation_pool_cuts_per_iteration"] = (
            payload.get("run_config", {}).get("benders", {}).get(
                "separation_pool_cuts_per_iteration", ""
            )
        )
        row["master_gurobi_params"] = json.dumps(
            payload.get("run_config", {}).get("benders", {}).get("master_gurobi_params", {}),
            sort_keys=True,
        )
        row["separation_gurobi_params"] = json.dumps(
            payload.get("run_config", {}).get("benders", {}).get("separation_gurobi_params", {}),
            sort_keys=True,
        )
        rows.append(row)
    rows = _dedupe_rows(rows)
    _write_rows(output_root / "acceleration_run_summary.csv", rows)
    _write_rows(
        output_root / "continuation_summary.csv",
        [row for row in rows if "continuation" in str(row.get("acceleration_role", ""))],
    )
    _write_rows(
        output_root / "solver_param_grid_summary.csv",
        [row for row in rows if row.get("acceleration_role") == "solver_parameter_grid"],
    )
    _write_rows(
        output_root / "topm_policy_summary.csv",
        [row for row in rows if "top_m" in str(row.get("acceleration_role", ""))],
    )
    _write_rows(
        output_root / "b100_engineering_summary.csv",
        [row for row in rows if int(row.get("B", 0) or 0) == 100],
    )
    _write_rows(
        output_root / "hard_k_probe_summary.csv",
        [row for row in rows if row.get("acceleration_role") == "fresh_hard_k_probe"],
    )
    _write_rows(
        output_root / "fast_incumbent_cut_summary.csv",
        [
            row
            for row in rows
            if str(row.get("acceleration_role", "")).startswith("fast_incumbent")
        ],
    )
    _write_rows(
        output_root / "pareto_core_cut_summary.csv",
        [
            row
            for row in rows
            if str(row.get("acceleration_role", "")).startswith("pareto_core")
        ],
    )
    _write_rows(
        output_root / "active_set_cut_summary.csv",
        [
            row
            for row in rows
            if str(row.get("acceleration_role", "")).startswith("active_set")
        ],
    )
    _refresh_live_trace(output_root)
    _write_engineering_reports(output_root, rows)


def _refresh_live_trace(output_root: Path) -> None:
    csv_rows: list[dict[str, Any]] = []
    jsonl_lines: list[str] = []
    for live_path in sorted((output_root / "runs").glob("*/logs/*_live_iteration_trace.csv")):
        run_id = live_path.name[: -len("_live_iteration_trace.csv")]
        for row in _read_rows(live_path):
            row = dict(row)
            row["run_id"] = run_id
            csv_rows.append(row)
    for live_path in sorted((output_root / "runs").glob("*/logs/*_live_iteration_trace.jsonl")):
        run_id = live_path.name[: -len("_live_iteration_trace.jsonl")]
        for line in live_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            payload["run_id"] = run_id
            jsonl_lines.append(json.dumps(payload, sort_keys=True))
    _write_rows(output_root / "engineering_acceleration_live_trace.csv", csv_rows)
    (output_root / "engineering_acceleration_live_trace.jsonl").write_text(
        "\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""),
        encoding="utf-8",
    )


def _write_engineering_reports(output_root: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    role_counts: dict[str, int] = {}
    for row in rows:
        role = str(row.get("acceleration_role", "unknown") or "unknown")
        role_counts[role] = role_counts.get(role, 0) + 1
    certified = [row for row in rows if row.get("validation_level") in {"exact", "epsilon_certified"}]
    best_k5 = sorted(
        [row for row in rows if int(row.get("K", 0) or 0) == 5],
        key=lambda row: float(row.get("final_violation", "inf") or "inf"),
    )
    lines = [
        "# Engineering Exhaustion Report",
        "",
        f"- Total engineering rows completed: `{len(rows)}`",
        f"- Certified rows: `{len(certified)}`",
        f"- Role counts: `{json.dumps(role_counts, sort_keys=True)}`",
    ]
    if best_k5:
        row = best_k5[0]
        lines.append(
            "- Best K=5 violation so far: "
            f"`{row.get('final_violation')}` from `{row.get('run_id')}` "
            f"after `{row.get('iterations')}` iterations and `{row.get('runtime_seconds')}` seconds."
        )
    topm_values = {
        int(row.get("top_cuts", 0) or 0)
        for row in rows
        if row.get("acceleration_role") == "top_m_policy_seeded"
    }
    hard_k_values = {
        int(row.get("K", 0) or 0)
        for row in rows
        if row.get("acceleration_role") == "fresh_hard_k_probe"
    }
    checks = {
        "heartbeat_trace_written": (output_root / "engineering_acceleration_live_trace.csv").exists(),
        "k5_seeded_top1_50plus": any(
            row.get("acceleration_role") == "same_support_cut_pool_continuation"
            and int(row.get("K", 0) or 0) == 5
            and int(row.get("top_cuts", 0) or 0) == 1
            and int(row.get("iterations", 0) or 0) >= 50
            for row in rows
        ),
        "k5_seeded_top1_100plus": any(
            row.get("acceleration_role") == "same_support_cut_pool_continuation"
            and int(row.get("K", 0) or 0) == 5
            and int(row.get("top_cuts", 0) or 0) == 1
            and int(row.get("iterations", 0) or 0) >= 100
            for row in rows
        ),
        "k5_seeded_top1_200plus": any(
            row.get("acceleration_role") == "same_support_cut_pool_continuation"
            and int(row.get("K", 0) or 0) == 5
            and int(row.get("top_cuts", 0) or 0) == 1
            and (
                int(row.get("iterations", 0) or 0) >= 200
                or int(row.get("max_iterations_budget", 0) or 0) >= 200
                or "add200" in str(row.get("run_id", ""))
            )
            for row in rows
        ),
        "k5_seeded_top3_20plus": any(
            row.get("acceleration_role") == "same_support_cut_pool_continuation"
            and int(row.get("K", 0) or 0) == 5
            and int(row.get("top_cuts", 0) or 0) == 3
            and int(row.get("iterations", 0) or 0) >= 20
            for row in rows
        ),
        "k5_seeded_top3_50plus": any(
            row.get("acceleration_role") == "same_support_cut_pool_continuation"
            and int(row.get("K", 0) or 0) == 5
            and int(row.get("top_cuts", 0) or 0) == 3
            and int(row.get("iterations", 0) or 0) >= 50
            for row in rows
        ),
        "fixed_topm_1_2_3": {1, 2, 3}.issubset(topm_values),
        "adaptive_topm_probe": role_counts.get("adaptive_top_m_policy_seeded", 0) > 0,
        "solver_grid_probe": role_counts.get("solver_parameter_grid", 0) >= 12,
        "b100_top1_probe": any(
            int(row.get("B", 0) or 0) == 100 and int(row.get("top_cuts", 0) or 0) == 1
            for row in rows
        ),
        "b100_top1_sep600_probe": any(
            int(row.get("B", 0) or 0) == 100
            and int(row.get("top_cuts", 0) or 0) == 1
            and "sep600" in str(row.get("run_id", ""))
            for row in rows
        ),
        "b100_top3_probe": any(
            int(row.get("B", 0) or 0) == 100 and int(row.get("top_cuts", 0) or 0) == 3
            for row in rows
        ),
        "hard_k_7_10_probe": {7, 10}.issubset(hard_k_values),
    }
    missing = [name for name, passed in checks.items() if not passed]
    lines.append(f"- Engineering coverage checks: `{json.dumps(checks, sort_keys=True)}`")
    if missing:
        lines.append(f"- Engineering matrix incomplete; missing checks: `{', '.join(missing)}`.")
        verdict = "ENGINEERING_IN_PROGRESS"
    else:
        k5_certified = any(
            row.get("acceleration_role") == "same_support_cut_pool_continuation"
            and int(row.get("K", 0) or 0) == 5
            and row.get("validation_level") in {"exact", "epsilon_certified"}
            for row in rows
        )
        hard_k_bad = any(
            row.get("acceleration_role") == "fresh_hard_k_probe"
            and int(row.get("K", 0) or 0) in {7, 10}
            and float(row.get("final_violation", "inf") or "inf") > 10000.0
            for row in rows
        )
        b100_slow = any(
            int(row.get("B", 0) or 0) == 100
            and float(row.get("separation_seconds", 0.0) or 0.0) > 200.0
            for row in rows
        )
        solver_grid_no_cert = role_counts.get("solver_parameter_grid", 0) > 0 and not any(
            row.get("acceleration_role") == "solver_parameter_grid"
            and row.get("validation_level") in {"exact", "epsilon_certified"}
            for row in rows
        )
        lines.append(
            "- Failure checks after engineering: "
            f"`{json.dumps({'k5_certified': k5_certified, 'hard_k_bad': hard_k_bad, 'b100_slow': b100_slow, 'solver_grid_no_cert': solver_grid_no_cert}, sort_keys=True)}`"
        )
        if hard_k_bad or b100_slow or solver_grid_no_cert:
            verdict = "ENGINEERING_EXHAUSTED_PRO_MATH_REQUIRED"
        else:
            verdict = "ENGINEERING_EXHAUSTED_NO_MATH_TRIGGER"
    lines.append(f"- Verdict: `{verdict}`")
    (output_root / "engineering_exhaustion_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    trigger_lines = [
        "# Math Layer Trigger Decision",
        "",
        f"Decision: `{verdict}`",
        "",
        "Do not implement Pareto cuts, stabilization, scenario screening, omega tightening, "
        "or cut aging/removal until a Pro extended-effort prompt has been sent and its "
        "answer has been converted into local validity/certificate tests.",
    ]
    if verdict == "ENGINEERING_EXHAUSTED_PRO_MATH_REQUIRED":
        trigger_lines.extend(
            [
                "",
                "Required Pro question: Given the current Benders master/separation traces, "
                "which mathematically valid strengthening should be attempted first: "
                "Pareto/Magnanti-Wong cuts, stabilized master/trust region, scenario screening "
                "with full-support final separation, omega-bound tightening, or cut management?",
                "",
                "Minimum evidence to send: K=5 certified top1 continuation trace, K=7/K=10 "
                "20-iteration traces, B=100 separation timing, solver-grid summary, and the "
                "current cut formula.",
            ]
        )
    (output_root / "math_layer_trigger_decision.md").write_text(
        "\n".join(trigger_lines) + "\n", encoding="utf-8"
    )


def _run_config(config: Mapping[str, Any], *, output_root: Path, skip_existing: bool) -> dict[str, Any]:
    run_id = str(config["run_id"])
    run_root = output_root / "runs" / run_id
    log_path = run_root / "logs" / f"{run_id}_run.json"
    if skip_existing and log_path.exists():
        return _summarize_milp(log_path, run_id=run_id)
    critical_buses = load_critical_buses(CRITICAL_BUSES)
    execute_run(dict(config), critical_buses=critical_buses, output_root=run_root)
    return _summarize_milp(log_path, run_id=run_id)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--accepted-log", default=str(DEFAULT_ACCEPTED_LOG))
    parser.add_argument("--runtime-source", default=DEFAULT_RUNTIME_SOURCE)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--run-continuation", action="store_true")
    parser.add_argument("--run-topm-ablation", action="store_true")
    parser.add_argument("--run-adaptive-topm", action="store_true")
    parser.add_argument("--run-solver-grid", action="store_true")
    parser.add_argument("--run-hard-k-probes", action="store_true")
    parser.add_argument("--run-fast-incumbent", action="store_true")
    parser.add_argument("--run-pareto-core", action="store_true")
    parser.add_argument("--run-stabilization", action="store_true")
    parser.add_argument("--run-active-set", action="store_true")
    parser.add_argument("--continuation-k-values", default="5")
    parser.add_argument("--include-b100-continuation", action="store_true")
    parser.add_argument("--top-values", default="1,2,3")
    parser.add_argument("--top-cuts", type=int, default=3)
    parser.add_argument("--hard-k-values", default="7,10")
    parser.add_argument("--hard-k-iterations", type=int, default=5)
    parser.add_argument("--hard-k-top-cuts", type=int, default=1)
    parser.add_argument("--fast-incumbent-k-values", default="5,7,10")
    parser.add_argument("--fast-incumbent-iterations", type=int, default=30)
    parser.add_argument("--fast-incumbent-separation-time-limit-seconds", type=float, default=20.0)
    parser.add_argument("--fast-incumbent-cut-tolerance", type=float, default=100.0)
    parser.add_argument("--include-b100-fast-incumbent", action="store_true")
    parser.add_argument("--fast-incumbent-b100-iterations", type=int, default=5)
    parser.add_argument("--fast-incumbent-b100-separation-time-limit-seconds", type=float, default=60.0)
    parser.add_argument("--pareto-core-k-values", default="5,7")
    parser.add_argument("--pareto-core-iterations", type=int, default=10)
    parser.add_argument("--stabilization-k-values", default="5,7")
    parser.add_argument("--stabilization-k5-iterations", type=int, default=30)
    parser.add_argument("--stabilization-hard-k-iterations", type=int, default=20)
    parser.add_argument("--stabilization-top-cuts", type=int, default=1)
    parser.add_argument("--stabilization-mode", default="local_branch_z")
    parser.add_argument("--stabilization-z-radius", type=int, default=2)
    parser.add_argument("--stabilization-sl-radius", type=int, default=20)
    parser.add_argument("--stabilization-fa-radius", type=int, default=6)
    parser.add_argument("--active-set-k-values", default="7,10")
    parser.add_argument("--active-set-iterations", type=int, default=20)
    parser.add_argument("--active-set-top-cuts", type=int, default=1)
    parser.add_argument("--active-set-separation-pool-cuts", type=int, default=0)
    parser.add_argument("--active-delta-max", type=int, default=50)
    parser.add_argument("--active-neighbor-radius", type=int, default=1)
    parser.add_argument("--active-max-candidates", type=int, default=5)
    parser.add_argument("--active-cuts-per-iteration", type=int, default=3)
    parser.add_argument("--active-select-top-violations", action="store_true")
    parser.add_argument("--active-min-hamming-distance", type=int, default=0)
    parser.add_argument("--active-set-enable-exact-outage-rows", action="store_true")
    parser.add_argument("--exact-rows-per-iteration", type=int, default=0)
    parser.add_argument("--exact-row-max", type=int, default=30)
    parser.add_argument("--exact-rows-exclude-active", action="store_true")
    parser.add_argument("--active-set-enable-nccg-outage-columns", action="store_true")
    parser.add_argument("--nccg-keep-global-cuts", action="store_true")
    parser.add_argument("--nccg-complete-active-columns", action="store_true")
    parser.add_argument("--nccg-completion-tolerance", type=float, default=100.0)
    parser.add_argument("--nccg-completion-max-cuts", type=int, default=5)
    parser.add_argument(
        "--nccg-completion-order",
        default="oldest",
        choices=("oldest", "newest", "source_violation"),
    )
    parser.add_argument("--enable-persistent-pricing-pool", action="store_true")
    parser.add_argument("--pricing-capture-passes", type=int, default=0)
    parser.add_argument("--pricing-capture-diversity-radius", type=int, default=4)
    parser.add_argument("--cross-column-broadcast", action="store_true")
    parser.add_argument("--broadcast-top-columns", type=int, default=30)
    parser.add_argument("--broadcast-violation-tolerance", type=float, default=100.0)
    parser.add_argument("--enable-certified-serious-step", action="store_true")
    parser.add_argument("--serious-level-kappa", type=float, default=0.35)
    parser.add_argument("--serious-eta-ub", type=float, default=0.01)
    parser.add_argument("--serious-tau-ub", type=float, default=10.0)
    parser.add_argument("--serious-eta-violation", type=float, default=0.15)
    parser.add_argument("--serious-chi", type=float, default=0.05)
    parser.add_argument("--serious-null-limit", type=int, default=3)
    parser.add_argument("--active-set-enable-target-face-bundle-cuts", action="store_true")
    parser.add_argument("--warm-start-plan-paths", default="")
    parser.add_argument("--initial-cut-pool-paths", default="")
    parser.add_argument("--initial-active-outage-pattern-paths", default="")
    parser.add_argument("--target-face-candidate-limit", type=int, default=30)
    parser.add_argument("--target-face-cuts-per-iteration", type=int, default=6)
    parser.add_argument("--target-face-neighbor-radius", type=int, default=1)
    parser.add_argument("--target-face-add-violation-fraction", type=float, default=0.01)
    parser.add_argument("--target-face-tolerance-rel", type=float, default=1e-6)
    parser.add_argument("--active-set-enable-cluster-face-bundle-cuts", action="store_true")
    parser.add_argument("--cluster-face-candidate-limit", type=int, default=30)
    parser.add_argument("--cluster-face-cuts-per-iteration", type=int, default=2)
    parser.add_argument("--cluster-face-add-violation-fraction", type=float, default=0.01)
    parser.add_argument("--cluster-face-tolerance-rel", type=float, default=1e-6)
    parser.add_argument("--active-set-enable-lambda-face-prox-trial", action="store_true")
    parser.add_argument("--lambda-face-level-slack-abs", type=float, default=500.0)
    parser.add_argument("--lambda-face-level-slack-fraction", type=float, default=0.05)
    parser.add_argument("--lambda-face-rho-alpha", type=float, default=0.05)
    parser.add_argument("--active-set-enable-level-bundle-trial", action="store_true")
    parser.add_argument("--level-bundle-objective-slack-abs", type=float, default=5000.0)
    parser.add_argument("--level-bundle-objective-slack-fraction", type=float, default=0.05)
    parser.add_argument("--level-bundle-rho-n", type=float, default=0.2)
    parser.add_argument("--level-bundle-rho-alpha", type=float, default=0.05)
    parser.add_argument("--level-bundle-rho-lambda", type=float, default=1.0)
    parser.add_argument("--disable-alpha-lambda-warm-start", action="store_true")
    parser.add_argument("--active-set-stabilization-mode", default="local_branch_z_n")
    parser.add_argument("--active-set-stabilization-z-radius", type=int, default=2)
    parser.add_argument("--active-set-stabilization-sl-radius", type=int, default=20)
    parser.add_argument("--active-set-stabilization-fa-radius", type=int, default=6)
    parser.add_argument(
        "--active-set-stabilization-center-update-policy",
        default="fixed",
        choices=("fixed", "last_trial", "best_violation"),
    )
    parser.add_argument("--continuation-iterations", type=int, default=200)
    parser.add_argument("--b100-continuation-iterations", type=int, default=80)
    parser.add_argument("--b100-top-cuts", type=int, default=1)
    parser.add_argument("--ablation-iterations", type=int, default=40)
    parser.add_argument("--adaptive-topm-iterations", type=int, default=40)
    parser.add_argument("--adaptive-topm-switch-violation", type=float, default=5000.0)
    parser.add_argument("--epsilon-cert", type=float, default=100.0)
    parser.add_argument("--master-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--master-mip-gap", type=float, default=0.03)
    parser.add_argument("--separation-time-limit-seconds", type=float, default=180.0)
    parser.add_argument("--b100-separation-time-limit-seconds", type=float, default=600.0)
    parser.add_argument("--separation-mip-gap", type=float, default=0.02)
    parser.add_argument("--omega-bound-upper", type=float, default=2.0e7)
    parser.add_argument("--master-gurobi-params-json", default="")
    parser.add_argument("--separation-gurobi-params-json", default="")
    parser.add_argument("--disable-live-trace", action="store_true")
    parser.add_argument("--adaptive-stall-window-iterations", type=int, default=20)
    parser.add_argument("--adaptive-stall-min-relative-improvement", type=float, default=0.10)
    parser.add_argument("--solver-grid-iterations", type=int, default=10)
    parser.add_argument("--solver-grid-top-cuts", type=int, default=1)
    parser.add_argument("--solver-threads-values", default="4,8")
    parser.add_argument("--solver-mipfocus-values", default="1,2")
    parser.add_argument("--solver-presolve-values", default="1,2")
    parser.add_argument("--solver-cuts-values", default="1,2")
    parser.add_argument("--solver-heuristics-values", default="0.01,0.05")
    parser.add_argument("--master-threads-values", default="4,8")
    parser.add_argument("--max-solver-grid-runs", type=int, default=0)
    parser.add_argument("--skip-existing", action="store_true")
    args = parser.parse_args()
    args.master_gurobi_params = _parse_params(args.master_gurobi_params_json)
    args.separation_gurobi_params = _parse_params(args.separation_gurobi_params_json)
    args.enable_live_trace = not args.disable_live_trace

    accepted = _read_accepted_config(Path(args.accepted_log))
    output_root = Path(args.output_root)
    configs: list[dict[str, Any]] = []
    if args.run_continuation or not (
        args.run_continuation
        or args.run_topm_ablation
        or args.run_adaptive_topm
        or args.run_solver_grid
        or args.run_hard_k_probes
        or args.run_fast_incumbent
        or args.run_pareto_core
        or args.run_stabilization
        or args.run_active_set
    ):
        configs.extend(
            _planned_continuation_configs(
                accepted,
                runtime_source=args.runtime_source,
                k_values=_parse_ints(args.continuation_k_values),
                include_b100=args.include_b100_continuation,
                args=args,
            )
        )
    if args.run_topm_ablation:
        configs.extend(
            _planned_topm_configs(
                accepted,
                runtime_source=args.runtime_source,
                top_values=_parse_ints(args.top_values),
                args=args,
            )
        )
    if args.run_adaptive_topm:
        configs.extend(
            _planned_adaptive_topm_configs(
                accepted,
                runtime_source=args.runtime_source,
                args=args,
            )
        )
    if args.run_solver_grid:
        configs.extend(
            _planned_solver_grid_configs(
                accepted,
                runtime_source=args.runtime_source,
                args=args,
            )
        )
    if args.run_hard_k_probes:
        configs.extend(
            _planned_hard_k_probe_configs(
                accepted,
                runtime_source=args.runtime_source,
                k_values=_parse_ints(args.hard_k_values),
                args=args,
            )
        )
    if args.run_fast_incumbent:
        configs.extend(
            _planned_fast_incumbent_configs(
                accepted,
                args=args,
                k_values=_parse_ints(args.fast_incumbent_k_values),
                include_b100=args.include_b100_fast_incumbent,
            )
        )
    if args.run_pareto_core:
        configs.extend(
            _planned_pareto_core_configs(
                accepted,
                args=args,
                k_values=_parse_ints(args.pareto_core_k_values),
            )
        )
    if args.run_stabilization:
        configs.extend(
            _planned_stabilization_configs(
                accepted,
                args=args,
                k_values=_parse_ints(args.stabilization_k_values),
            )
        )
    if args.run_active_set:
        configs.extend(
            _planned_active_set_configs(
                accepted,
                args=args,
                k_values=_parse_ints(args.active_set_k_values),
            )
        )

    _write_json(
        output_root / "acceleration_manifest.json",
        {
            "accepted_log": str(args.accepted_log),
            "runtime_source": args.runtime_source,
            "parameter_regime": CURRENT_DEFAULT_REGIME,
            "output_policy": "engineering-only; do not promote into paper_final without audit PASS",
            "planned_run_count": len(configs),
        },
    )
    _write_rows(output_root / "planned_acceleration_runs.csv", [_plan_row(config) for config in configs])
    if args.dry_run:
        print(json.dumps({"planned_run_count": len(configs)}, sort_keys=True))
        return

    rows: list[dict[str, Any]] = _read_rows(output_root / "acceleration_run_summary.csv")
    for index, config in enumerate(configs, start=1):
        print(f"[{index}/{len(configs)}] {config['run_id']}", flush=True)
        row = _run_config(config, output_root=output_root, skip_existing=args.skip_existing)
        row["acceleration_role"] = config.get("engineering_acceleration", {}).get("role", "")
        row["seed_run_id"] = config.get("engineering_acceleration", {}).get("seed_run_id", "")
        rows.append(row)
        _write_rows(output_root / "acceleration_run_summary.csv", _dedupe_rows(rows))
        _refresh_aggregate_artifacts(output_root)
    _refresh_aggregate_artifacts(output_root)
    print(json.dumps({"completed_run_count": len(configs)}, sort_keys=True))


if __name__ == "__main__":
    main()
