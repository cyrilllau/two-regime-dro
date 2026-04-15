"""Tests for the Round 01 frozen contract helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.contracts.freeze import FrozenConfigError, build_frozen_config, load_frozen_config_file


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_valid_toy_frozen_config_loads() -> None:
    """A JSON-compatible YAML fixture should build a typed FrozenConfig."""

    config = load_frozen_config_file(FIXTURE_DIR / "toy_config_valid.yaml")
    assert config.scenarios_a == (1, 2)
    assert config.scenarios_b == (1, 2)
    assert config.root_bus == 1
    assert config.critical_buses_required is True


def test_missing_critical_marker_is_rejected() -> None:
    """The frozen contract must keep the external critical-bus marker explicit."""

    with pytest.raises(FrozenConfigError, match="critical_buses"):
        load_frozen_config_file(FIXTURE_DIR / "toy_config_missing_critical.yaml")


def test_invalid_root_bus_type_is_rejected() -> None:
    """Malformed runtime fields should fail with a deterministic message."""

    with pytest.raises(FrozenConfigError, match="network_freeze.root_bus"):
        build_frozen_config(
            {
                "source_of_truth": {
                    "schema_and_loader": "reference/legacy/m1_data_setup.py",
                    "runtime_numeric_params": "data/runtime_12/parameters.json",
                    "scenario_index_source": "selection_config_bounded_by_csv_manifest",
                },
                "default_runtime_fixture": {
                    "instance_id": "local_tested_small_v1",
                    "scenarios_a": [1, 2],
                    "scenarios_b": [1, 2],
                    "expanded_scenario_packages": "opt_in_only",
                    "on_support_mismatch": (
                        "record_manifest_mismatch_and_fail_only_if_selection_invalid"
                    ),
                },
                "economics": {
                    "Cunmet": 3.0,
                    "annualize_normal_cost_by_365": True,
                    "annualize_disaster_cost_by_365": False,
                    "Ctrans_mode": "time_vector",
                    "power_unit": "kW",
                },
                "network_freeze": {
                    "root_bus": "1",
                    "candidate_buses": "all_except_root",
                    "allow_evcs_at_root": False,
                    "v_ref_sq": 1.0,
                },
                "ambiguity_freeze": {
                    "p_bar_equals_FP": True,
                    "use_ambig_w_in_paper_model": False,
                    "ambig_w_meaning": "legacy only",
                },
                "disaster_objective_freeze": {
                    "critical_buses": "REQUIRED_EXTERNAL_INPUT",
                    "CLS_critical": 50.0,
                    "CLS_noncritical": 10.0,
                },
            }
        )
