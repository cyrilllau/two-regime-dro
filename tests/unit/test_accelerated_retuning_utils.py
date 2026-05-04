"""Regression tests for accelerated default-retuning plumbing."""

from __future__ import annotations

import json

from scripts.experiment_pack_utils import (
    _load_initial_cuts_from_pools,
    _write_cut_pool,
)
from scripts.run_default_multiplier_calibration import _base_config, _candidate_grid
from scripts.run_default_multiplier_calibration import _initial_cut_pool_paths
from src.production.master_problem import RestrictedMasterCut
from tests.oracle.test_master_problem_toy_cases import build_round_07_toy_case


def _sample_cut() -> RestrictedMasterCut:
    return RestrictedMasterCut(
        cut_id="seed_source_cut",
        beta=1.0,
        gamma_z_by_bus={1: 2.0},
        gamma_n_sl_by_bus={1: 3.0},
        gamma_n_fa_by_bus={1: 4.0},
        phi_by_line_id={"line_01_02": 5.0},
    )


def test_cut_pool_seeding_accepts_same_instance_and_rejects_wrong_mode(tmp_path) -> None:
    """Cut reuse must be limited to the same source, mode, support, K, buses, and lines."""

    instance, _, _ = build_round_07_toy_case("master_problem_normal_averaging.yaml")
    run_config = {
        "runtime_source": "toy_source",
        "mode": "integrated_mainline",
    }
    pool_path = tmp_path / "cut_pool.json"
    _write_cut_pool(
        pool_path,
        instance=instance,
        run_config=run_config,
        cuts=[_sample_cut()],
    )

    loaded, audit_rows = _load_initial_cuts_from_pools(
        instance,
        run_config,
        {"initial_cut_pool_paths": [str(pool_path)]},
    )

    assert len(loaded) == 1
    assert loaded[0].cut_id.startswith("seed1_")
    assert audit_rows[0]["status"] == "accepted"
    assert audit_rows[0]["loaded_cut_count"] == 1

    rejected, rejected_audit = _load_initial_cuts_from_pools(
        instance,
        {"runtime_source": "toy_source", "mode": "deterministic_mean_value"},
        {"initial_cut_pool_paths": [str(pool_path)]},
    )

    assert rejected == []
    assert rejected_audit[0]["status"] == "rejected_metadata_mismatch"


def test_cut_pool_payload_is_metadata_complete(tmp_path) -> None:
    """The persisted cut pool should carry enough metadata for local compatibility audits."""

    instance, _, _ = build_round_07_toy_case("master_problem_normal_averaging.yaml")
    pool_path = tmp_path / "cut_pool.json"
    _write_cut_pool(
        pool_path,
        instance=instance,
        run_config={"runtime_source": "toy_source", "mode": "integrated_mainline"},
        cuts=[_sample_cut()],
    )

    payload = json.loads(pool_path.read_text(encoding="utf-8"))

    assert payload["cut_count"] == 1
    assert payload["metadata"]["runtime_source"] == "toy_source"
    assert payload["metadata"]["mode"] == "integrated_mainline"
    assert payload["metadata"]["K"] == instance.ambiguity.k_max_outages
    assert payload["metadata"]["normal_scenarios"] == list(
        instance.sets.loaded_normal_scenarios
    )
    assert payload["metadata"]["disaster_scenarios"] == list(
        instance.sets.loaded_disaster_scenarios
    )
    assert payload["cuts"][0]["cut_signature_hash"]


def test_default_config_exposes_acceleration_controls() -> None:
    """Retuning configs must pass warm starts, cut pools, dedup, and guard flags to Benders."""

    config = _base_config(
        runtime_source="data/colleague_default_10x10",
        candidate={
            "candidate_id": "synthetic",
            "m_cons": 0.017,
            "m_normal": 1.0,
            "m_disaster": 1.25,
        },
        case="proposed",
        max_iterations=30,
        top_cuts=10,
        epsilon_cert=100.0,
        master_time_limit_seconds=120.0,
        master_mip_gap=0.02,
        separation_time_limit_seconds=180.0,
        separation_mip_gap=0.02,
        omega_bound_upper=20_000_000.0,
        warm_start_plan_paths=["plans/a.csv", "plans/b.csv"],
        initial_cut_pool_paths=["logs/a_cut_pool.json"],
        enable_cut_signature_dedup=True,
        enable_repeated_outage_guard=True,
    )

    assert config["benders"]["warm_start_plan_paths"] == ["plans/a.csv", "plans/b.csv"]
    assert config["benders"]["initial_cut_pool_paths"] == ["logs/a_cut_pool.json"]
    assert config["benders"]["enable_cut_signature_dedup"] is True
    assert config["benders"]["enable_repeated_outage_guard"] is True


def test_candidate_grid_can_disable_forced_rejected_baseline() -> None:
    """Accelerated exact-candidate runs should not silently add extra candidates."""

    class Args:
        cons_values = "0.017"
        normal_values = "1"
        disaster_values = "1.25"
        no_forced_baseline = True
        stage1_max_candidates = 28

    candidates = _candidate_grid(Args())

    assert [row["candidate_id"] for row in candidates] == [
        "mult_cons0p017_normal1_disaster1p25"
    ]


def test_disaster_case_can_use_explicit_cut_pool_path(tmp_path) -> None:
    """Case3 acceleration may seed valid disaster cuts via explicit paths."""

    pool_path = tmp_path / "seed_cut_pool.json"
    pool_path.write_text("{}", encoding="utf-8")

    class Args:
        initial_cut_pool_paths = str(pool_path)
        neighbor_cut_pool_limit = 2

    paths = _initial_cut_pool_paths(
        root=tmp_path,
        candidate={"candidate_id": "synthetic", "m_cons": 0.018, "m_normal": 1.0, "m_disaster": 1.25},
        case="disaster",
        args=Args(),
    )

    assert paths == [str(pool_path)]
