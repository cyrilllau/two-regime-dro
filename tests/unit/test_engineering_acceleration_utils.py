from dataclasses import replace
from pathlib import Path
from typing import Optional

from scripts.analyze_engineering_acceleration_baseline import _diagnosis
from scripts.run_engineering_acceleration_experiments import _selected_config
from scripts.experiment_pack_utils import (
    _load_initial_cuts_from_pools,
    _plan_rows_from_trial_certificate,
    _write_cut_pool,
)
from src.production.benders_engine import (
    _delta_by_line_id_from_active_lines,
    _initial_active_outage_pool,
    _live_iteration_row,
    _merge_active_outage_pool,
    _neighbor_outage_patterns,
    _separation_bound_certifies,
    _separation_incumbent_can_generate_cut,
    _z_hamming_distance,
)
from src.audit.iteration_log import BendersIterationRecord
from src.production.master_problem import build_master_problem
from src.production.master_problem import RestrictedMasterCut, RestrictedMasterOutageColumnCut
from src.production.separation_milp import SeparationMilpSolution
from src.reference.disaster_primal_ref import FixedFirstStagePlan
from tests.oracle.test_disaster_primal_ref import _build_case


def _solution(
    *,
    objective_value: Optional[float],
    obj_bound: Optional[float],
    delta: Optional[dict[str, int]] = None,
) -> SeparationMilpSolution:
    return SeparationMilpSolution(
        objective_value=objective_value,
        model_status="TIME_LIMIT",
        raw_status_code=9,
        obj_bound=obj_bound,
        mip_gap=None,
        node_count=None,
        runtime_seconds=None,
        delta_by_line_id=delta or {"line_1": 1, "line_2": 0},
        omega_by_line_id={},
        tau_by_line_id={},
        omega_lower_slack_by_line_id={},
        omega_upper_slack_by_line_id={},
        max_omega_bound_violation=0.0,
        samplewise_dual_solutions={},
        active_groups={},
        average_base_value=0.0,
        tau_sum=0.0,
        lambda_delta_value=0.0,
        alpha_value=0.0,
        reconstructed_objective=objective_value or 0.0,
        reconstruction_gap=0.0,
    )


def test_engineering_config_keeps_seeded_cuts_and_solver_params(tmp_path: Path) -> None:
    seed_plan = tmp_path / "seed_plan.csv"
    seed_cut_pool = tmp_path / "seed_cut_pool.json"
    seed_plan.write_text("bus,is_open,n_sl,n_fa\n", encoding="utf-8")
    seed_cut_pool.write_text("{}", encoding="utf-8")
    config = _selected_config(
        {
            "run_id": "accepted",
            "parameter_overrides": {"objective_multipliers": {"cons": 0.0152}},
        },
        run_id="eng_continuation_test",
        runtime_source="data/colleague_default_synth_100x100",
        a_count=10,
        b_count=10,
        k=5,
        top_cuts=3,
        max_iterations=200,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.03,
        separation_time_limit_seconds=180.0,
        separation_mip_gap=0.02,
        omega_bound_upper=2.0e7,
        warm_start_plan_paths=[seed_plan],
        initial_cut_pool_paths=[seed_cut_pool],
        master_gurobi_params={"Threads": 4},
        separation_gurobi_params={"MIPFocus": 1, "Heuristics": 0.05},
        acceleration_role="same_support_cut_pool_continuation",
        seed_run_id="standard_seed",
    )
    benders = config["benders"]
    assert benders["warm_start_plan_paths"] == [str(seed_plan)]
    assert benders["initial_cut_pool_paths"] == [str(seed_cut_pool)]
    assert benders["master_gurobi_params"] == {"Threads": 4}
    assert benders["separation_gurobi_params"] == {"MIPFocus": 1, "Heuristics": 0.05}
    assert config["engineering_acceleration"]["math_change"] == "none"


def test_engineering_config_can_enable_pro_approved_fast_incumbent_cuts(
    tmp_path: Path,
) -> None:
    config = _selected_config(
        {"run_id": "accepted"},
        run_id="eng_fast_incumbent_test",
        runtime_source="data/colleague_default_synth_100x100",
        a_count=10,
        b_count=10,
        k=7,
        top_cuts=1,
        max_iterations=30,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.03,
        separation_time_limit_seconds=20.0,
        separation_mip_gap=0.02,
        omega_bound_upper=2.0e7,
        warm_start_plan_paths=[],
        initial_cut_pool_paths=[],
        master_gurobi_params={},
        separation_gurobi_params={},
        acceleration_role="fast_incumbent_cut_prototype",
        allow_nonoptimal_separation_cuts=True,
        nonoptimal_separation_cut_tolerance=100.0,
        math_change="pro_approved_fast_incumbent_cuts",
    )
    assert config["benders"]["allow_nonoptimal_separation_cuts"] is True
    assert config["benders"]["nonoptimal_separation_cut_tolerance"] == 100.0
    assert (
        config["engineering_acceleration"]["math_change"]
        == "pro_approved_fast_incumbent_cuts"
    )


def test_engineering_config_can_enable_pro_approved_stabilization(
    tmp_path: Path,
) -> None:
    seed_plan = tmp_path / "seed_plan.csv"
    seed_plan.write_text("bus,is_open,n_sl,n_fa\n", encoding="utf-8")
    config = _selected_config(
        {"run_id": "accepted"},
        run_id="eng_stabilized_test",
        runtime_source="data/colleague_default_synth_100x100",
        a_count=10,
        b_count=10,
        k=7,
        top_cuts=1,
        max_iterations=20,
        separation_pool_cuts=6,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.03,
        separation_time_limit_seconds=180.0,
        separation_mip_gap=0.02,
        omega_bound_upper=2.0e7,
        warm_start_plan_paths=[seed_plan],
        initial_cut_pool_paths=[],
        master_gurobi_params={},
        separation_gurobi_params={},
        acceleration_role="stabilized_local_branch_z_probe",
        stabilization_mode="local_branch_z",
        stabilization_z_radius=2,
        math_change="pro_approved_stabilized_trial_points",
    )
    benders = config["benders"]
    assert benders["stabilization_mode"] == "local_branch_z"
    assert benders["stabilization_z_radius"] == 2
    assert (
        config["engineering_acceleration"]["math_change"]
        == "pro_approved_stabilized_trial_points"
    )


def test_engineering_config_can_enable_pro_approved_active_set_cuts(
    tmp_path: Path,
) -> None:
    config = _selected_config(
        {"run_id": "accepted"},
        run_id="eng_active_set_test",
        runtime_source="data/colleague_default_synth_100x100",
        a_count=10,
        b_count=10,
        k=7,
        top_cuts=1,
        max_iterations=20,
        separation_pool_cuts=6,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.03,
        separation_time_limit_seconds=180.0,
        separation_mip_gap=0.02,
        omega_bound_upper=2.0e7,
        warm_start_plan_paths=[],
        initial_cut_pool_paths=[],
        master_gurobi_params={},
        separation_gurobi_params={},
        acceleration_role="active_set_fullB_validated_probe",
        stabilization_mode="local_branch_z_n",
        stabilization_z_radius=2,
        stabilization_charger_sl_radius=20,
        stabilization_charger_fa_radius=6,
        stabilization_center_update_policy="best_violation",
        enable_active_set_cuts=True,
        active_delta_max=50,
        active_neighbor_radius=1,
        active_max_candidates_per_iteration=5,
        active_cuts_per_iteration=3,
        active_select_top_violations=True,
        active_min_hamming_distance=2,
        enable_exact_outage_rows=True,
        exact_rows_per_iteration=2,
        exact_row_max=30,
        math_change="pro_approved_active_set_fullB_validated_cuts",
    )
    benders = config["benders"]
    assert benders["enable_active_set_cuts"] is True
    assert benders["active_delta_max"] == 50
    assert benders["active_max_candidates_per_iteration"] == 5
    assert benders["active_cuts_per_iteration"] == 3
    assert benders["active_select_top_violations"] is True
    assert benders["active_min_hamming_distance"] == 2
    assert benders["enable_exact_outage_rows"] is True
    assert benders["exact_rows_per_iteration"] == 2
    assert benders["exact_row_max"] == 30
    assert benders["separation_pool_cuts_per_iteration"] == 6
    assert benders["stabilization_mode"] == "local_branch_z_n"
    assert benders["stabilization_center_update_policy"] == "best_violation"


def test_engineering_config_can_enable_target_face_bundle_cuts() -> None:
    config = _selected_config(
        {"run_id": "accepted"},
        run_id="eng_target_face_test",
        runtime_source="data/colleague_default_synth_100x100",
        a_count=10,
        b_count=10,
        k=10,
        top_cuts=1,
        max_iterations=20,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.03,
        separation_time_limit_seconds=180.0,
        separation_mip_gap=0.02,
        omega_bound_upper=2.0e7,
        warm_start_plan_paths=[],
        initial_cut_pool_paths=[],
        master_gurobi_params={},
        separation_gurobi_params={},
        acceleration_role="active_set_fullB_validated_probe",
        enable_active_set_cuts=True,
        active_delta_max=120,
        active_max_candidates_per_iteration=20,
        active_cuts_per_iteration=2,
        active_select_top_violations=True,
        enable_target_face_bundle_cuts=True,
        target_face_candidate_limit=30,
        target_face_cuts_per_iteration=6,
        target_face_add_violation_fraction=0.01,
        target_face_tolerance_rel=1e-6,
        math_change="pro_approved_targeted_dual_face_bundle_cuts",
    )
    benders = config["benders"]
    assert benders["enable_target_face_bundle_cuts"] is True
    assert benders["target_face_candidate_limit"] == 30
    assert benders["target_face_cuts_per_iteration"] == 6
    assert benders["target_face_add_violation_fraction"] == 0.01
    assert benders["target_face_tolerance_rel"] == 1e-6
    assert (
        config["engineering_acceleration"]["math_change"]
        == "pro_approved_targeted_dual_face_bundle_cuts"
    )


def test_engineering_config_can_enable_lambda_face_prox_trial() -> None:
    config = _selected_config(
        {"run_id": "accepted"},
        run_id="eng_lambda_face_test",
        runtime_source="data/colleague_default_synth_100x100",
        a_count=10,
        b_count=10,
        k=10,
        top_cuts=1,
        max_iterations=20,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.03,
        separation_time_limit_seconds=180.0,
        separation_mip_gap=0.02,
        omega_bound_upper=2.0e7,
        warm_start_plan_paths=[],
        initial_cut_pool_paths=[],
        master_gurobi_params={},
        separation_gurobi_params={},
        acceleration_role="active_set_fullB_validated_probe",
        enable_active_set_cuts=True,
        enable_target_face_bundle_cuts=True,
        enable_lambda_face_prox_trial=True,
        lambda_face_level_slack_abs=750.0,
        lambda_face_level_slack_fraction=0.08,
        lambda_face_rho_alpha=0.03,
        math_change="pro_approved_lambda_face_prox_trial",
    )
    benders = config["benders"]
    assert benders["enable_lambda_face_prox_trial"] is True
    assert benders["lambda_face_level_slack_abs"] == 750.0
    assert benders["lambda_face_level_slack_fraction"] == 0.08
    assert benders["lambda_face_rho_alpha"] == 0.03
    assert (
        config["engineering_acceleration"]["math_change"]
        == "pro_approved_lambda_face_prox_trial"
    )


def test_engineering_config_can_disable_alpha_lambda_warm_start() -> None:
    config = _selected_config(
        {"run_id": "accepted"},
        run_id="eng_no_alpha_lambda_warmstart",
        runtime_source="data/colleague_default_synth_100x100",
        a_count=10,
        b_count=10,
        k=10,
        top_cuts=1,
        max_iterations=20,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.03,
        separation_time_limit_seconds=180.0,
        separation_mip_gap=0.02,
        omega_bound_upper=2.0e7,
        warm_start_plan_paths=[],
        initial_cut_pool_paths=[],
        master_gurobi_params={},
        separation_gurobi_params={},
        acceleration_role="active_set_fullB_validated_probe",
        enable_alpha_lambda_warm_start=False,
    )
    assert config["benders"]["enable_alpha_lambda_warm_start"] is False


def test_engineering_config_can_enable_cluster_face_bundle_cuts() -> None:
    config = _selected_config(
        {"run_id": "accepted"},
        run_id="eng_cluster_face_test",
        runtime_source="data/colleague_default_synth_100x100",
        a_count=10,
        b_count=10,
        k=10,
        top_cuts=1,
        max_iterations=20,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.03,
        separation_time_limit_seconds=180.0,
        separation_mip_gap=0.02,
        omega_bound_upper=2.0e7,
        warm_start_plan_paths=[],
        initial_cut_pool_paths=[],
        master_gurobi_params={},
        separation_gurobi_params={},
        acceleration_role="active_set_fullB_validated_probe",
        enable_active_set_cuts=True,
        enable_cluster_face_bundle_cuts=True,
        cluster_face_candidate_limit=24,
        cluster_face_cuts_per_iteration=2,
        cluster_face_add_violation_fraction=0.02,
        cluster_face_tolerance_rel=1e-5,
        math_change="pro_approved_cluster_minimax_dual_face_bundle_cuts",
    )
    benders = config["benders"]
    assert benders["enable_cluster_face_bundle_cuts"] is True
    assert benders["cluster_face_candidate_limit"] == 24
    assert benders["cluster_face_cuts_per_iteration"] == 2
    assert benders["cluster_face_add_violation_fraction"] == 0.02
    assert benders["cluster_face_tolerance_rel"] == 1e-5
    assert (
        config["engineering_acceleration"]["math_change"]
        == "pro_approved_cluster_minimax_dual_face_bundle_cuts"
    )


def test_local_branch_z_trust_region_is_auxiliary_and_explicit() -> None:
    instance, plan, _, _, _ = _build_case("disaster_primal_mixed_slow_fast.yaml")
    instance = replace(instance, metadata={"benchmark_mode": "disaster_only"})
    master = build_master_problem(
        instance,
        trust_region_center_plan=plan,
        trust_region_z_radius=2,
    )

    assert master.trust_region_z_radius == 2
    assert "local_branch_z" in master.trust_region_constraints
    assert "trust_region_local_branch_z" in {
        constr.ConstrName for constr in master.trust_region_constraints.values()
    }

    canonical = build_master_problem(instance)
    assert canonical.trust_region_constraints == {}
    assert canonical.trust_region_z_radius is None


def test_z_hamming_distance_and_live_row_keep_auxiliary_fields() -> None:
    instance, plan, _, _, _ = _build_case("disaster_primal_mixed_slow_fast.yaml")
    first_bus = instance.sets.buses[0]
    shifted = FixedFirstStagePlan(
        z_by_bus={
            bus: (1 - value if bus == first_bus else value)
            for bus, value in plan.z_by_bus.items()
        },
        n_sl_by_bus=plan.n_sl_by_bus,
        n_fa_by_bus=plan.n_fa_by_bus,
    )
    assert _z_hamming_distance(plan, shifted) == 1

    row = _live_iteration_row(
        BendersIterationRecord(
            iteration_id=0,
            pre_cut_master_objective=10.0,
            post_cut_master_objective=None,
            separation_violation_value=20.0,
            candidate_source="stabilized_local_branch_z",
            canonical_master_objective=10.0,
            auxiliary_master_objective=12.0,
            unpenalized_candidate_objective=12.0,
            trust_region_z_radius=2,
            trust_region_z_distance=1,
            active_delta_pool_size=50,
            active_candidate_count=5,
            active_validated_cut_count=3,
            active_best_validated_violation=2500.0,
            active_set_generation_seconds=1.25,
        )
    )
    assert row["candidate_source"] == "stabilized_local_branch_z"
    assert row["canonical_master_objective"] == 10.0
    assert row["auxiliary_master_objective"] == 12.0
    assert row["active_delta_pool_size"] == 50
    assert row["active_validated_cut_count"] == 3
    assert row["active_best_validated_violation"] == 2500.0


def test_active_outage_pool_helpers_are_budget_safe() -> None:
    instance, _, _, _, _ = _build_case("disaster_primal_mixed_slow_fast.yaml")
    pool = _initial_active_outage_pool(instance, max_size=4)
    assert pool[0] == tuple()
    assert all(len(pattern) <= 1 for pattern in pool)

    line_ids = tuple(instance.sets.line_ids)
    base = tuple(line_ids[:1])
    neighbors = _neighbor_outage_patterns(
        base,
        line_ids=line_ids,
        budget_k=2,
        radius=1,
    )
    assert base in neighbors
    assert all(len(pattern) <= 2 for pattern in neighbors)
    assert tuple() in neighbors
    if len(line_ids) > 1:
        assert tuple(sorted((line_ids[0], line_ids[1]))) in neighbors

    delta = _delta_by_line_id_from_active_lines(line_ids, base)
    assert sum(delta.values()) == 1
    merged = _merge_active_outage_pool(
        existing=[tuple()],
        additions=[base, tuple()],
        max_size=2,
        fp_by_line_id={line_id: float(index) for index, line_id in enumerate(line_ids)},
    )
    assert merged[0] == base
    assert len(merged) == 2


def test_nonoptimal_separation_status_semantics() -> None:
    assert _separation_incumbent_can_generate_cut(
        _solution(objective_value=250.0, obj_bound=1000.0),
        cut_tolerance=100.0,
    )
    assert not _separation_incumbent_can_generate_cut(
        _solution(objective_value=72.0, obj_bound=500.0),
        cut_tolerance=100.0,
    )
    assert _separation_bound_certifies(
        _solution(objective_value=72.0, obj_bound=99.0),
        epsilon=100.0,
    )
    assert not _separation_bound_certifies(
        _solution(objective_value=72.0, obj_bound=500.0),
        epsilon=100.0,
    )


def test_baseline_diagnosis_separates_b_and_k_bottlenecks() -> None:
    assert "B-support separation" in _diagnosis(
        {"B": 100, "K": 2, "validation_level": "smoke_only"}
    )
    assert "K-budget convergence" in _diagnosis(
        {"B": 10, "K": 5, "validation_level": "smoke_only"}
    )
    assert "high iteration" in _diagnosis(
        {"B": 10, "K": 5, "validation_level": "epsilon_certified"}
    )


def test_trial_certificate_plan_payload_writes_plan_rows() -> None:
    instance, _, _, _, _ = _build_case("disaster_primal_mixed_slow_fast.yaml")
    trial_payload = {
        "first_stage_plan": {
            "z_by_bus": {str(bus): int(index == 0) for index, bus in enumerate(instance.sets.buses)},
            "n_sl_by_bus": {str(bus): int(3 if index == 0 else 0) for index, bus in enumerate(instance.sets.buses)},
            "n_fa_by_bus": {str(bus): int(1 if index == 0 else 0) for index, bus in enumerate(instance.sets.buses)},
        }
    }

    rows = _plan_rows_from_trial_certificate(instance, trial_payload)

    assert rows[0]["is_open"] == 1
    assert rows[0]["n_sl"] == 3
    assert rows[0]["n_fa"] == 1
    assert all(row["is_open"] == 0 for row in rows[1:])


def test_cut_pool_roundtrip_restores_rowwise_outage_columns(tmp_path: Path) -> None:
    instance, _, _, _, _ = _build_case("disaster_primal_mixed_slow_fast.yaml")
    instance = replace(instance, metadata={"benchmark_mode": "integrated"})
    run_config = {
        "runtime_source": "toy_source",
        "mode": "integrated_mainline",
        "benders": {},
    }
    cut = RestrictedMasterCut(
        cut_id="cut_a",
        beta=1.25,
        gamma_z_by_bus={int(instance.sets.buses[0]): 2.0},
        gamma_n_sl_by_bus={},
        gamma_n_fa_by_bus={},
        phi_by_line_id={str(instance.sets.line_ids[0]): 3.0},
    )
    rowwise = RestrictedMasterOutageColumnCut(
        row_id="row_a",
        column_id="delta_a",
        active_line_ids=(str(instance.sets.line_ids[0]),),
        cut=cut,
    )
    pool_path = tmp_path / "cut_pool.json"
    _write_cut_pool(
        pool_path,
        instance=instance,
        run_config=run_config,
        cuts=[cut],
        outage_column_cuts=[rowwise],
    )
    benders_config = {"initial_cut_pool_paths": [str(pool_path)]}

    loaded_cuts, loaded_rowwise, audit = _load_initial_cuts_from_pools(
        instance,
        run_config,
        benders_config,
    )

    assert len(loaded_cuts) == 1
    assert len(loaded_rowwise) == 1
    assert audit[0]["status"] == "accepted"
    assert audit[0]["loaded_outage_column_cut_count"] == 1
    assert audit[0]["observed_outage_column_cut_count"] == 1
    assert audit[0]["metadata_match"] is True
