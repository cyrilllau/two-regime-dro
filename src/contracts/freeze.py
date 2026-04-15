"""Frozen contract helpers for the paper-faithful mainline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class FrozenConfigError(ValueError):
    """Raised when the frozen contract is malformed."""


@dataclass(frozen=True)
class SourceOfTruth:
    """Repository-level source-of-truth paths and semantics."""

    schema_and_loader: str
    runtime_numeric_params: str
    scenario_index_source: str


@dataclass(frozen=True)
class DefaultRuntimeFixture:
    """Default runtime selection preset for the mainline."""

    instance_id: str
    scenarios_a: tuple[int, ...]
    scenarios_b: tuple[int, ...]
    expanded_scenario_packages: str
    on_support_mismatch: str


@dataclass(frozen=True)
class EconomicsFreeze:
    """Frozen economics and unit semantics."""

    cunmet: float
    annualize_normal_cost_by_365: bool
    annualize_disaster_cost_by_365: bool
    ctrans_mode: str
    power_unit: str


@dataclass(frozen=True)
class NetworkFreeze:
    """Frozen network semantics."""

    root_bus: int
    candidate_buses: str
    allow_evcs_at_root: bool
    v_ref_sq: float


@dataclass(frozen=True)
class AmbiguityFreeze:
    """Frozen ambiguity-set semantics."""

    p_bar_equals_fp: bool
    use_ambig_w_in_paper_model: bool
    ambig_w_meaning: str


@dataclass(frozen=True)
class DisasterObjectiveFreeze:
    """Frozen disaster-objective semantics."""

    critical_buses: str
    cls_critical: float
    cls_noncritical: float


@dataclass(frozen=True)
class FrozenConfig:
    """Normalized project-wide frozen contract."""

    source_of_truth: SourceOfTruth
    default_runtime_fixture: DefaultRuntimeFixture
    economics: EconomicsFreeze
    network: NetworkFreeze
    ambiguity: AmbiguityFreeze
    disaster_objective: DisasterObjectiveFreeze

    @property
    def scenarios_a(self) -> tuple[int, ...]:
        """Shortcut for the frozen default normal-scenario support."""

        return self.default_runtime_fixture.scenarios_a

    @property
    def scenarios_b(self) -> tuple[int, ...]:
        """Shortcut for the frozen default disaster-scenario support."""

        return self.default_runtime_fixture.scenarios_b

    @property
    def root_bus(self) -> int:
        """Shortcut for the frozen feeder root."""

        return self.network.root_bus

    @property
    def allow_evcs_at_root(self) -> bool:
        """Shortcut for root siting policy."""

        return self.network.allow_evcs_at_root

    @property
    def cunmet(self) -> float:
        """Shortcut for the frozen unmet-demand penalty."""

        return self.economics.cunmet

    @property
    def critical_buses_required(self) -> bool:
        """Whether disaster-objective critical buses must be explicit."""

        return self.disaster_objective.critical_buses == "REQUIRED_EXTERNAL_INPUT"

    def candidate_buses_for(self, buses: tuple[int, ...]) -> tuple[int, ...]:
        """Resolve the current candidate-bus policy against a bus set."""

        if self.network.candidate_buses != "all_except_root":
            raise FrozenConfigError(
                "Unsupported candidate-bus policy in FrozenConfig: "
                f"{self.network.candidate_buses!r}"
            )
        return tuple(bus for bus in buses if bus != self.root_bus)


def _expect_mapping(raw: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise FrozenConfigError(f"{name} must be a mapping, got {type(raw).__name__}.")
    return raw


def _expect_key(raw: Mapping[str, Any], key: str, *, section: str) -> Any:
    if key not in raw:
        raise FrozenConfigError(f"Missing required field {section}.{key}.")
    return raw[key]


def _expect_bool(raw: Mapping[str, Any], key: str, *, section: str) -> bool:
    value = _expect_key(raw, key, section=section)
    if not isinstance(value, bool):
        raise FrozenConfigError(f"{section}.{key} must be a bool, got {value!r}.")
    return value


def _expect_str(raw: Mapping[str, Any], key: str, *, section: str) -> str:
    value = _expect_key(raw, key, section=section)
    if not isinstance(value, str) or not value:
        raise FrozenConfigError(f"{section}.{key} must be a non-empty string.")
    return value


def _expect_float(raw: Mapping[str, Any], key: str, *, section: str) -> float:
    value = _expect_key(raw, key, section=section)
    if not isinstance(value, (int, float)):
        raise FrozenConfigError(f"{section}.{key} must be numeric, got {value!r}.")
    return float(value)


def _expect_int(raw: Mapping[str, Any], key: str, *, section: str) -> int:
    value = _expect_key(raw, key, section=section)
    if not isinstance(value, int) or isinstance(value, bool):
        raise FrozenConfigError(f"{section}.{key} must be an int, got {value!r}.")
    return value


def _expect_int_tuple(raw: Mapping[str, Any], key: str, *, section: str) -> tuple[int, ...]:
    value = _expect_key(raw, key, section=section)
    if not isinstance(value, list) or not value:
        raise FrozenConfigError(f"{section}.{key} must be a non-empty list of ints.")
    ints: list[int] = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool):
            raise FrozenConfigError(f"{section}.{key} must contain only ints, got {item!r}.")
        ints.append(item)
    return tuple(ints)


def build_frozen_config(raw: Mapping[str, Any]) -> FrozenConfig:
    """Build and validate a ``FrozenConfig`` from a raw mapping."""

    root = _expect_mapping(raw, name="Frozen config")

    source_raw = _expect_mapping(
        _expect_key(root, "source_of_truth", section="Frozen config"),
        name="source_of_truth",
    )
    fixture_raw = _expect_mapping(
        _expect_key(root, "default_runtime_fixture", section="Frozen config"),
        name="default_runtime_fixture",
    )
    econ_raw = _expect_mapping(
        _expect_key(root, "economics", section="Frozen config"),
        name="economics",
    )
    network_raw = _expect_mapping(
        _expect_key(root, "network_freeze", section="Frozen config"),
        name="network_freeze",
    )
    ambiguity_raw = _expect_mapping(
        _expect_key(root, "ambiguity_freeze", section="Frozen config"),
        name="ambiguity_freeze",
    )
    disaster_raw = _expect_mapping(
        _expect_key(root, "disaster_objective_freeze", section="Frozen config"),
        name="disaster_objective_freeze",
    )

    source = SourceOfTruth(
        schema_and_loader=_expect_str(source_raw, "schema_and_loader", section="source_of_truth"),
        runtime_numeric_params=_expect_str(
            source_raw,
            "runtime_numeric_params",
            section="source_of_truth",
        ),
        scenario_index_source=_expect_str(
            source_raw,
            "scenario_index_source",
            section="source_of_truth",
        ),
    )
    fixture = DefaultRuntimeFixture(
        instance_id=_expect_str(fixture_raw, "instance_id", section="default_runtime_fixture"),
        scenarios_a=_expect_int_tuple(fixture_raw, "scenarios_a", section="default_runtime_fixture"),
        scenarios_b=_expect_int_tuple(fixture_raw, "scenarios_b", section="default_runtime_fixture"),
        expanded_scenario_packages=_expect_str(
            fixture_raw,
            "expanded_scenario_packages",
            section="default_runtime_fixture",
        ),
        on_support_mismatch=_expect_str(
            fixture_raw,
            "on_support_mismatch",
            section="default_runtime_fixture",
        ),
    )
    economics = EconomicsFreeze(
        cunmet=_expect_float(econ_raw, "Cunmet", section="economics"),
        annualize_normal_cost_by_365=_expect_bool(
            econ_raw,
            "annualize_normal_cost_by_365",
            section="economics",
        ),
        annualize_disaster_cost_by_365=_expect_bool(
            econ_raw,
            "annualize_disaster_cost_by_365",
            section="economics",
        ),
        ctrans_mode=_expect_str(econ_raw, "Ctrans_mode", section="economics"),
        power_unit=_expect_str(econ_raw, "power_unit", section="economics"),
    )
    network = NetworkFreeze(
        root_bus=_expect_int(network_raw, "root_bus", section="network_freeze"),
        candidate_buses=_expect_str(network_raw, "candidate_buses", section="network_freeze"),
        allow_evcs_at_root=_expect_bool(
            network_raw,
            "allow_evcs_at_root",
            section="network_freeze",
        ),
        v_ref_sq=_expect_float(network_raw, "v_ref_sq", section="network_freeze"),
    )
    ambiguity = AmbiguityFreeze(
        p_bar_equals_fp=_expect_bool(
            ambiguity_raw,
            "p_bar_equals_FP",
            section="ambiguity_freeze",
        ),
        use_ambig_w_in_paper_model=_expect_bool(
            ambiguity_raw,
            "use_ambig_w_in_paper_model",
            section="ambiguity_freeze",
        ),
        ambig_w_meaning=_expect_str(
            ambiguity_raw,
            "ambig_w_meaning",
            section="ambiguity_freeze",
        ),
    )
    disaster = DisasterObjectiveFreeze(
        critical_buses=_expect_str(
            disaster_raw,
            "critical_buses",
            section="disaster_objective_freeze",
        ),
        cls_critical=_expect_float(
            disaster_raw,
            "CLS_critical",
            section="disaster_objective_freeze",
        ),
        cls_noncritical=_expect_float(
            disaster_raw,
            "CLS_noncritical",
            section="disaster_objective_freeze",
        ),
    )

    if disaster.critical_buses != "REQUIRED_EXTERNAL_INPUT":
        raise FrozenConfigError(
            "disaster_objective_freeze.critical_buses must remain "
            "'REQUIRED_EXTERNAL_INPUT' in the frozen contract."
        )
    if network.candidate_buses != "all_except_root":
        raise FrozenConfigError(
            "network_freeze.candidate_buses must be 'all_except_root' for Round 01."
        )

    return FrozenConfig(
        source_of_truth=source,
        default_runtime_fixture=fixture,
        economics=economics,
        network=network,
        ambiguity=ambiguity,
        disaster_objective=disaster,
    )


def load_frozen_config_file(path: str | Path) -> FrozenConfig:
    """Load a JSON-compatible YAML fixture file for FrozenConfig tests."""

    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FrozenConfigError(
            f"{file_path} must contain JSON-compatible YAML for Round 01 fixtures."
        ) from exc
    return build_frozen_config(raw)


DEFAULT_FROZEN_CONFIG = build_frozen_config(
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
            "on_support_mismatch": "record_manifest_mismatch_and_fail_only_if_selection_invalid",
        },
        "economics": {
            "Cunmet": 3.0,
            "annualize_normal_cost_by_365": True,
            "annualize_disaster_cost_by_365": False,
            "Ctrans_mode": "time_vector",
            "power_unit": "kW",
        },
        "network_freeze": {
            "root_bus": 1,
            "candidate_buses": "all_except_root",
            "allow_evcs_at_root": False,
            "v_ref_sq": 1.0,
        },
        "ambiguity_freeze": {
            "p_bar_equals_FP": True,
            "use_ambig_w_in_paper_model": False,
            "ambig_w_meaning": (
                "legacy engineering weight in old repo only, not the paper CLS_n contract"
            ),
        },
        "disaster_objective_freeze": {
            "critical_buses": "REQUIRED_EXTERNAL_INPUT",
            "CLS_critical": 50.0,
            "CLS_noncritical": 10.0,
        },
    }
)
