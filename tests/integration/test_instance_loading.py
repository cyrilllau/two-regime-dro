"""Integration tests for raw-package loading, selection, and canonicalization."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scripts.experiment_pack_utils import prepare_instance_for_run
from src.instance.canonical_instance import load_canonical_instance
from src.instance.manifest import inspect_available_support
from src.instance.raw_package import load_raw_data_package
from src.instance.runtime_fixture import load_default_runtime_fixture
from src.instance.selection import build_runtime_selection, load_runtime_selection_file
from src.instance.validators import RuntimeDataValidationError, require_explicit_critical_buses


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, int | float]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_valid_runtime_fixture(runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True, exist_ok=True)

    parameters = {
        "sets": {
            "buses": [1, 2, 3],
            "lines": [[1, 2], [2, 3]],
            "regions": [1],
            "t_nor": [1, 2],
            "t_s": [1],
            "scenarios_a": [1, 2],
            "scenarios_b": [1, 2],
        },
        "econ": {
            "Cfix": 1.0,
            "Ccons_sl": 2.0,
            "Ccons_fa": 3.0,
            "Ctrans": [1.0, 1.0],
            "Cpur": [0.2, 0.3],
            "Ccong": 0.0,
            "gamma": 0.01,
            "theta": 20,
            "pi_f": 0.3,
            "alpha_min": 0.0,
        },
        "net": {
            "Rline": [0.1, 0.2],
            "Xline": [0.01, 0.02],
            "Pmax": [10.0, 10.0],
            "Qmax": [10.0, 10.0],
            "Vmin": 0.95,
            "Vmax": 1.05,
        },
        "ev": {
            "P_EV_rated_sl": 7.0,
            "P_EV_rated_fa": 50.0,
            "D": [[1.0, 2.0, 3.0]],
            "delta_t": 1.0,
            "Nbar_sl": 5,
            "Nbar_fa": 2,
        },
        "ambig": {
            "K": 1,
            "p_bar": [0.1, 0.2],
            "w": [50000.0, 1.0, 20000.0],
        },
    }
    (runtime_dir / "parameters.json").write_text(json.dumps(parameters), encoding="utf-8")

    _write_csv(
        runtime_dir / "normal_load_scenarios.csv",
        ["scenario_a", "t", "bus", "P_kW", "Q_kvar"],
        [
            {"scenario_a": 1, "t": 1, "bus": 2, "P_kW": 4.0, "Q_kvar": 1.0},
            {"scenario_a": 1, "t": 2, "bus": 2, "P_kW": 5.0, "Q_kvar": 1.5},
            {"scenario_a": 2, "t": 1, "bus": 2, "P_kW": 6.0, "Q_kvar": 2.0},
            {"scenario_a": 2, "t": 2, "bus": 2, "P_kW": 7.0, "Q_kvar": 2.5},
        ],
    )
    _write_csv(
        runtime_dir / "normal_ev_demand_slow.csv",
        ["scenario_a", "t", "region", "DEV_ch_sl_kW"],
        [
            {"scenario_a": 1, "t": 1, "region": 1, "DEV_ch_sl_kW": 10.0},
            {"scenario_a": 1, "t": 2, "region": 1, "DEV_ch_sl_kW": 11.0},
            {"scenario_a": 2, "t": 1, "region": 1, "DEV_ch_sl_kW": 12.0},
            {"scenario_a": 2, "t": 2, "region": 1, "DEV_ch_sl_kW": 13.0},
        ],
    )
    _write_csv(
        runtime_dir / "normal_ev_demand_fast.csv",
        ["scenario_a", "t", "region", "DEV_ch_fa_kW"],
        [
            {"scenario_a": 1, "t": 1, "region": 1, "DEV_ch_fa_kW": 3.0},
            {"scenario_a": 1, "t": 2, "region": 1, "DEV_ch_fa_kW": 3.5},
            {"scenario_a": 2, "t": 1, "region": 1, "DEV_ch_fa_kW": 4.0},
            {"scenario_a": 2, "t": 2, "region": 1, "DEV_ch_fa_kW": 4.5},
        ],
    )
    _write_csv(
        runtime_dir / "disaster_load_scenarios.csv",
        ["scenario_b", "ts", "bus", "P_kW"],
        [
            {"scenario_b": 1, "ts": 1, "bus": 2, "P_kW": 2.0},
            {"scenario_b": 2, "ts": 1, "bus": 2, "P_kW": 3.0},
        ],
    )
    _write_csv(
        runtime_dir / "disaster_ev_discharge_slow.csv",
        ["scenario_b", "ts", "region", "DEV_dis_sl_kW"],
        [
            {"scenario_b": 1, "ts": 1, "region": 1, "DEV_dis_sl_kW": 8.0},
            {"scenario_b": 2, "ts": 1, "region": 1, "DEV_dis_sl_kW": 9.0},
        ],
    )
    _write_csv(
        runtime_dir / "disaster_ev_discharge_fast.csv",
        ["scenario_b", "ts", "region", "DEV_dis_fa_kW"],
        [
            {"scenario_b": 1, "ts": 1, "region": 1, "DEV_dis_fa_kW": 4.0},
            {"scenario_b": 2, "ts": 1, "region": 1, "DEV_dis_fa_kW": 5.0},
        ],
    )


def test_runtime_12_loads_under_default_selection_and_reports_manifest_mismatch() -> None:
    """The live runtime_12 package should load under the default {1,2} selection."""

    instance = load_canonical_instance(REPO_ROOT / "data/runtime_12")

    assert instance.scenario_support.normal == (1, 2)
    assert instance.scenario_support.disaster == (1, 2)
    assert instance.scenario_support.available_normal == tuple(range(1, 11))
    assert instance.scenario_support.available_disaster == tuple(range(1, 11))
    assert instance.scenario_support.declared_normal == tuple(range(1, 11))
    assert instance.scenario_support.declared_disaster == (1, 2)
    assert any(
        "Disaster-stage support declared in parameters.json is (1, 2)" in message
        for message in instance.scenario_support.manifest_messages
    )
    assert instance.metadata["support_manifest"]["policy"]["json_declared_support_is_advisory"] is True


def test_extra_raw_support_does_not_leak_into_canonical_tensors() -> None:
    """Only the selected subset should appear in model-facing canonical tensors."""

    instance = load_canonical_instance(REPO_ROOT / "data/runtime_12")

    assert {key[0] for key in instance.normal_tensors.p_load} == {1, 2}
    assert {key[0] for key in instance.disaster_tensors.p_load} == {1, 2}
    assert (3, 1, 1) not in instance.normal_tensors.p_load
    assert (3, 1, 1) not in instance.disaster_tensors.p_load


def test_missing_csv_selection_is_rejected_before_canonical_build() -> None:
    """Selection errors should be fatal before model-facing tensors are built."""

    selection = load_runtime_selection_file(FIXTURE_DIR / "selection_invalid_missing_csv.yaml")

    with pytest.raises(RuntimeDataValidationError, match="absent from CSV support"):
        load_canonical_instance(REPO_ROOT / "data/runtime_12", selection=selection)


def test_load_default_runtime_fixture_uses_selection_preset() -> None:
    """The default fixture should load via selection semantics rather than raw equality tests."""

    instance = load_default_runtime_fixture()

    assert instance.scenario_support.normal == (1, 2)
    assert instance.scenario_support.disaster == (1, 2)
    assert instance.scenario_support.selection_source == "default_small_preset"


def test_valid_synthetic_runtime_loads_and_fills_sparse_zeros(tmp_path: Path) -> None:
    """A valid small runtime fixture should canonicalize into dense tensors."""

    runtime_dir = tmp_path / "runtime_small"
    _write_valid_runtime_fixture(runtime_dir)

    instance = load_canonical_instance(runtime_dir)

    assert instance.scenario_support.normal == (1, 2)
    assert instance.scenario_support.disaster == (1, 2)
    assert instance.network_topology.children_by_bus[2] == (3,)
    assert instance.normal_tensors.p_load[(1, 1, 1)] == 0.0
    assert instance.normal_tensors.p_load[(1, 1, 3)] == 0.0
    assert instance.normal_tensors.p_load[(2, 2, 2)] == 7.0
    assert instance.disaster_tensors.p_load[(2, 1, 1)] == 0.0
    assert instance.critical_buses is None
    assert instance.is_critical_by_bus is None
    assert instance.cls_by_bus is None


def test_parameter_overrides_accept_bus_specific_evcs_capacity(tmp_path: Path) -> None:
    """Packaging overrides should allow per-bus station capacity maps."""

    runtime_dir = tmp_path / "runtime_small"
    _write_valid_runtime_fixture(runtime_dir)
    base = load_canonical_instance(runtime_dir)

    instance = prepare_instance_for_run(
        base,
        {
            "parameter_overrides": {
                "ev": {
                    "nbar_sl_by_bus": {"2": 4, "3": 8},
                    "nbar_fa_by_bus": {"2": 2, "3": 3},
                }
            }
        },
    )

    assert instance.ev.nbar_sl == 5
    assert instance.ev.nbar_fa == 2
    assert instance.ev.nbar_sl_by_bus == {2: 4, 3: 8}
    assert instance.ev.nbar_fa_by_bus == {2: 2, 3: 3}


def test_parameter_overrides_reject_candidate_capacity_below_minimum(tmp_path: Path) -> None:
    """A candidate bus cannot have less total capacity than the min-charger rule."""

    runtime_dir = tmp_path / "runtime_small"
    _write_valid_runtime_fixture(runtime_dir)
    base = load_canonical_instance(runtime_dir)

    with pytest.raises(RuntimeDataValidationError, match="three-charger minimum"):
        prepare_instance_for_run(
            base,
            {
                "parameter_overrides": {
                    "ev": {
                        "nbar_sl_by_bus": {"2": 1},
                        "nbar_fa_by_bus": {"2": 1},
                    }
                }
            },
        )


def test_parameter_overrides_accept_slow_block_cost_controls(tmp_path: Path) -> None:
    """Packaging overrides should carry optional slow-block cost settings."""

    runtime_dir = tmp_path / "runtime_small"
    _write_valid_runtime_fixture(runtime_dir)
    base = load_canonical_instance(runtime_dir)

    instance = prepare_instance_for_run(
        base,
        {
            "parameter_overrides": {
                "economics": {"ccons_sl_extra_multiplier": 2.5},
                "ev": {"slow_block_threshold": 4},
            }
        },
    )

    assert instance.economics.ccons_sl_extra_multiplier == pytest.approx(2.5)
    assert instance.ev.slow_block_threshold == 4


def test_runtime_objective_multipliers_default_to_one(tmp_path: Path) -> None:
    """Missing objective multipliers should preserve the historical objective."""

    runtime_dir = tmp_path / "runtime_small"
    _write_valid_runtime_fixture(runtime_dir)

    instance = load_canonical_instance(runtime_dir)

    assert instance.economics.objective_multipliers.cons == pytest.approx(1.0)
    assert instance.economics.objective_multipliers.normal == pytest.approx(1.0)
    assert instance.economics.objective_multipliers.disaster == pytest.approx(1.0)


def test_runtime_objective_multipliers_load_and_validate(tmp_path: Path) -> None:
    """Runtime objective multipliers must be finite positive values."""

    runtime_dir = tmp_path / "runtime_small"
    _write_valid_runtime_fixture(runtime_dir)
    parameter_path = runtime_dir / "parameters.json"
    parameters = json.loads(parameter_path.read_text(encoding="utf-8"))
    parameters["objective_multipliers"] = {
        "cons": 2.0,
        "normal": 3.0,
        "disaster": 5.0,
    }
    parameter_path.write_text(json.dumps(parameters), encoding="utf-8")

    instance = load_canonical_instance(runtime_dir)

    assert instance.economics.objective_multipliers.cons == pytest.approx(2.0)
    assert instance.economics.objective_multipliers.normal == pytest.approx(3.0)
    assert instance.economics.objective_multipliers.disaster == pytest.approx(5.0)

    parameters["objective_multipliers"]["normal"] = 0.0
    parameter_path.write_text(json.dumps(parameters), encoding="utf-8")
    with pytest.raises(
        RuntimeDataValidationError,
        match=r"objective_multipliers\.normal must be finite and positive",
    ):
        load_canonical_instance(runtime_dir)


def test_raw_package_manifest_and_default_selection_compose_cleanly() -> None:
    """The three-step boundary should compose without collapsing raw support to selection."""

    raw_package = load_raw_data_package(REPO_ROOT / "data/runtime_12")
    manifest = inspect_available_support(raw_package)
    instance = load_canonical_instance(
        REPO_ROOT / "data/runtime_12",
        selection=build_runtime_selection(scenarios_a=(1, 2), scenarios_b=(1, 2)),
    )

    assert manifest.normal.csv_support == tuple(range(1, 11))
    assert manifest.disaster.csv_support == tuple(range(1, 11))
    assert instance.scenario_support.normal == (1, 2)
    assert instance.scenario_support.disaster == (1, 2)


def test_critical_buses_are_not_inferred_from_ambig_w(tmp_path: Path) -> None:
    """Legacy ambiguity weights must not synthesize paper critical buses."""

    runtime_dir = tmp_path / "runtime_small"
    _write_valid_runtime_fixture(runtime_dir)
    instance = load_canonical_instance(runtime_dir)

    with pytest.raises(
        RuntimeDataValidationError,
        match="ambig.w is present but explicitly forbidden as a fallback",
    ):
        require_explicit_critical_buses(
            buses=instance.sets.buses,
            critical_buses=instance.critical_buses,
            legacy_w=instance.ambiguity.legacy_w,
        )
