"""Utilities for the Round 12 experiment packaging scripts."""

from __future__ import annotations

from dataclasses import asdict, replace
import csv
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.audit.experiment_summary import (
    ExperimentFailureSummary,
    ExperimentRunSummary,
)
from src.instance.canonical_instance import (
    CanonicalInstance,
    ScenarioSupport,
    load_canonical_instance,
)
from src.instance.indexer import build_index_map
from src.instance.schema import (
    CanonicalSets,
    DisasterScenarioTensor,
    NormalScenarioTensor,
    ObjectiveMultipliers,
)
from src.instance.selection import build_runtime_selection, default_runtime_selection
from src.instance.validators import build_criticality_maps
from src.instance.validators import RuntimeDataValidationError
from src.production.benders_engine import BendersEngineResult, run_benders_engine
from src.production.cut_factory import compute_cut_signature_hash
from src.production.master_problem import (
    RestrictedMasterCut,
    RestrictedMasterOutageColumnCut,
    RestrictedMasterProblemSolution,
    solve_master_problem,
)
from src.reference.disaster_primal_ref import FixedFirstStagePlan, build_fixed_first_stage_plan


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML mapping from disk."""

    file_path = Path(path)
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{file_path} must contain a YAML mapping.")
    return dict(raw)


def ensure_directory(path: str | Path) -> Path:
    """Create a directory and return it as a ``Path``."""

    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Load the top-level experiment manifest and expand family includes."""

    manifest = load_yaml_file(manifest_path)
    runs: list[dict[str, Any]] = []
    for family_entry in manifest.get("families", ()):
        include_path = family_entry.get("include")
        if include_path is None:
            raise ValueError("Each family entry must define `include`.")
        family_raw = load_yaml_file(include_path)
        family_name = str(family_raw["family_name"])
        for run in family_raw.get("runs", ()):
            run_copy = dict(run)
            run_copy["family_name"] = family_name
            runs.append(run_copy)
    for run in manifest.get("runs", ()):
        runs.append(dict(run))
    expanded = dict(manifest)
    expanded["runs"] = runs
    return expanded


def load_critical_buses(config_path: str | Path) -> tuple[int, ...]:
    """Load the explicit critical-bus set for this round."""

    raw = load_yaml_file(config_path)
    values = raw.get("critical_buses")
    if not isinstance(values, Sequence):
        raise ValueError(f"{config_path} must define a sequence field `critical_buses`.")
    return tuple(int(value) for value in values)


def resolve_selection(run_config: Mapping[str, Any]):
    """Resolve the canonical selection for one run."""

    if "selection" in run_config:
        selection_raw = run_config["selection"]
        return build_runtime_selection(
            scenarios_a=selection_raw["scenarios_a"],
            scenarios_b=selection_raw["scenarios_b"],
            source=str(run_config.get("run_id", "explicit_selection")),
        )
    preset = run_config.get("selection_preset")
    if preset == "default_small":
        return default_runtime_selection()
    return None


def load_instance_for_run(
    run_config: Mapping[str, Any],
    *,
    critical_buses: Sequence[int],
) -> CanonicalInstance:
    """Load the canonical base instance for one experiment run."""

    return load_canonical_instance(
        run_config["runtime_source"],
        critical_buses=tuple(int(bus) for bus in critical_buses),
        selection=resolve_selection(run_config),
    )


def _average_values(values: Sequence[float]) -> float:
    return float(sum(values) / len(values))


def build_mean_value_instance(instance: CanonicalInstance) -> CanonicalInstance:
    """Collapse the currently loaded supports to one mean-value scenario per stage."""

    mean_normal_id = 1
    mean_disaster_id = 1
    normal_support = instance.sets.loaded_normal_scenarios
    disaster_support = instance.sets.loaded_disaster_scenarios

    normal_tensors = NormalScenarioTensor(
        support=(mean_normal_id,),
        p_load={
            (mean_normal_id, time_id, bus): _average_values(
                [
                    instance.normal_tensors.p_load[(scenario_id, time_id, bus)]
                    for scenario_id in normal_support
                ]
            )
            for time_id in instance.sets.normal_times
            for bus in instance.sets.buses
        },
        q_load={
            (mean_normal_id, time_id, bus): _average_values(
                [
                    instance.normal_tensors.q_load[(scenario_id, time_id, bus)]
                    for scenario_id in normal_support
                ]
            )
            for time_id in instance.sets.normal_times
            for bus in instance.sets.buses
        },
        dev_ch_sl={
            (mean_normal_id, time_id, region): _average_values(
                [
                    instance.normal_tensors.dev_ch_sl[(scenario_id, time_id, region)]
                    for scenario_id in normal_support
                ]
            )
            for time_id in instance.sets.normal_times
            for region in instance.sets.regions
        },
        dev_ch_fa={
            (mean_normal_id, time_id, region): _average_values(
                [
                    instance.normal_tensors.dev_ch_fa[(scenario_id, time_id, region)]
                    for scenario_id in normal_support
                ]
            )
            for time_id in instance.sets.normal_times
            for region in instance.sets.regions
        },
    )
    disaster_tensors = DisasterScenarioTensor(
        support=(mean_disaster_id,),
        p_load={
            (mean_disaster_id, time_id, bus): _average_values(
                [
                    instance.disaster_tensors.p_load[(scenario_id, time_id, bus)]
                    for scenario_id in disaster_support
                ]
            )
            for time_id in instance.sets.disaster_times
            for bus in instance.sets.buses
        },
        dev_dis_sl={
            (mean_disaster_id, time_id, region): _average_values(
                [
                    instance.disaster_tensors.dev_dis_sl[(scenario_id, time_id, region)]
                    for scenario_id in disaster_support
                ]
            )
            for time_id in instance.sets.disaster_times
            for region in instance.sets.regions
        },
        dev_dis_fa={
            (mean_disaster_id, time_id, region): _average_values(
                [
                    instance.disaster_tensors.dev_dis_fa[(scenario_id, time_id, region)]
                    for scenario_id in disaster_support
                ]
            )
            for time_id in instance.sets.disaster_times
            for region in instance.sets.regions
        },
    )
    sets = CanonicalSets(
        buses=instance.sets.buses,
        line_ids=instance.sets.line_ids,
        regions=instance.sets.regions,
        normal_times=instance.sets.normal_times,
        disaster_times=instance.sets.disaster_times,
        declared_normal_scenarios=(mean_normal_id,),
        declared_disaster_scenarios=(mean_disaster_id,),
        available_normal_scenarios=(mean_normal_id,),
        available_disaster_scenarios=(mean_disaster_id,),
        loaded_normal_scenarios=(mean_normal_id,),
        loaded_disaster_scenarios=(mean_disaster_id,),
    )
    index_map = build_index_map(
        buses=instance.sets.buses,
        lines=instance.sets.line_ids,
        regions=instance.sets.regions,
        normal_times=instance.sets.normal_times,
        disaster_times=instance.sets.disaster_times,
        normal_scenarios=(mean_normal_id,),
        disaster_scenarios=(mean_disaster_id,),
    )
    scenario_support = ScenarioSupport(
        normal=(mean_normal_id,),
        disaster=(mean_disaster_id,),
        available_normal=(mean_normal_id,),
        available_disaster=(mean_disaster_id,),
        declared_normal=(mean_normal_id,),
        declared_disaster=(mean_disaster_id,),
        csv_support_by_file=dict(instance.scenario_support.csv_support_by_file),
        manifest_messages=tuple(instance.scenario_support.manifest_messages),
        selection_source=f"{instance.scenario_support.selection_source}|mean_value_benchmark",
    )
    metadata = dict(instance.metadata)
    metadata["benchmark_mode"] = "deterministic_mean_value"
    metadata["mean_value_source_normal_support"] = list(normal_support)
    metadata["mean_value_source_disaster_support"] = list(disaster_support)
    return replace(
        instance,
        sets=sets,
        normal_tensors=normal_tensors,
        disaster_tensors=disaster_tensors,
        index_map=index_map,
        scenario_support=scenario_support,
        metadata=metadata,
    )


def build_disaster_mean_value_instance(instance: CanonicalInstance) -> CanonicalInstance:
    """Collapse only the disaster support to a mean-value scenario.

    This benchmark keeps the full normal-operation support so that the
    deterministic comparison isolates disaster uncertainty instead of becoming a
    weak normal-service strawman when the normal scenarios are highly variable.
    """

    mean_disaster_id = 1
    normal_support = instance.sets.loaded_normal_scenarios
    disaster_support = instance.sets.loaded_disaster_scenarios

    disaster_tensors = DisasterScenarioTensor(
        support=(mean_disaster_id,),
        p_load={
            (mean_disaster_id, time_id, bus): _average_values(
                [
                    instance.disaster_tensors.p_load[(scenario_id, time_id, bus)]
                    for scenario_id in disaster_support
                ]
            )
            for time_id in instance.sets.disaster_times
            for bus in instance.sets.buses
        },
        dev_dis_sl={
            (mean_disaster_id, time_id, region): _average_values(
                [
                    instance.disaster_tensors.dev_dis_sl[(scenario_id, time_id, region)]
                    for scenario_id in disaster_support
                ]
            )
            for time_id in instance.sets.disaster_times
            for region in instance.sets.regions
        },
        dev_dis_fa={
            (mean_disaster_id, time_id, region): _average_values(
                [
                    instance.disaster_tensors.dev_dis_fa[(scenario_id, time_id, region)]
                    for scenario_id in disaster_support
                ]
            )
            for time_id in instance.sets.disaster_times
            for region in instance.sets.regions
        },
    )
    sets = CanonicalSets(
        buses=instance.sets.buses,
        line_ids=instance.sets.line_ids,
        regions=instance.sets.regions,
        normal_times=instance.sets.normal_times,
        disaster_times=instance.sets.disaster_times,
        declared_normal_scenarios=normal_support,
        declared_disaster_scenarios=(mean_disaster_id,),
        available_normal_scenarios=normal_support,
        available_disaster_scenarios=(mean_disaster_id,),
        loaded_normal_scenarios=normal_support,
        loaded_disaster_scenarios=(mean_disaster_id,),
    )
    index_map = build_index_map(
        buses=instance.sets.buses,
        lines=instance.sets.line_ids,
        regions=instance.sets.regions,
        normal_times=instance.sets.normal_times,
        disaster_times=instance.sets.disaster_times,
        normal_scenarios=normal_support,
        disaster_scenarios=(mean_disaster_id,),
    )
    scenario_support = ScenarioSupport(
        normal=normal_support,
        disaster=(mean_disaster_id,),
        available_normal=normal_support,
        available_disaster=(mean_disaster_id,),
        declared_normal=normal_support,
        declared_disaster=(mean_disaster_id,),
        csv_support_by_file=dict(instance.scenario_support.csv_support_by_file),
        manifest_messages=tuple(instance.scenario_support.manifest_messages),
        selection_source=f"{instance.scenario_support.selection_source}|disaster_mean_value_benchmark",
    )
    metadata = dict(instance.metadata)
    metadata["benchmark_mode"] = "deterministic_disaster_mean_value"
    metadata["mean_value_source_disaster_support"] = list(disaster_support)
    return replace(
        instance,
        sets=sets,
        disaster_tensors=disaster_tensors,
        index_map=index_map,
        scenario_support=scenario_support,
        metadata=metadata,
    )


def build_ev_penetration_instance(instance: CanonicalInstance, *, scale: float) -> CanonicalInstance:
    """Scale EV charging/discharging tensors by an explicit penetration factor."""

    scaled_normal = replace(
        instance.normal_tensors,
        dev_ch_sl={
            key: float(scale * value) for key, value in instance.normal_tensors.dev_ch_sl.items()
        },
        dev_ch_fa={
            key: float(scale * value) for key, value in instance.normal_tensors.dev_ch_fa.items()
        },
    )
    scaled_disaster = replace(
        instance.disaster_tensors,
        dev_dis_sl={
            key: float(scale * value)
            for key, value in instance.disaster_tensors.dev_dis_sl.items()
        },
        dev_dis_fa={
            key: float(scale * value)
            for key, value in instance.disaster_tensors.dev_dis_fa.items()
        },
    )
    metadata = dict(instance.metadata)
    metadata["ev_penetration_scale"] = float(scale)
    return replace(
        instance,
        normal_tensors=scaled_normal,
        disaster_tensors=scaled_disaster,
        metadata=metadata,
    )


def build_normal_only_instance(instance: CanonicalInstance) -> CanonicalInstance:
    """Disable the disaster objective term for the normal-only benchmark."""

    economics = replace(instance.economics, pi_f=0.0)
    metadata = dict(instance.metadata)
    metadata["benchmark_mode"] = "normal_only"
    return replace(instance, economics=economics, metadata=metadata)


def build_disaster_only_instance(instance: CanonicalInstance) -> CanonicalInstance:
    """Disable the weighted normal term while preserving the disaster objective."""

    economics = replace(instance.economics, pi_f=1.0)
    metadata = dict(instance.metadata)
    metadata["benchmark_mode"] = "disaster_only"
    metadata["station_sizing_policy"] = "unrestricted_disaster_capacity"
    return replace(instance, economics=economics, metadata=metadata)


def _resolve_tuple_override(
    raw_value: Any,
    *,
    expected_length: int,
    label: str,
) -> tuple[float, ...]:
    if isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes)):
        values = tuple(float(value) for value in raw_value)
        if len(values) != expected_length:
            raise ValueError(
                f"{label} must have length {expected_length}, got {len(values)}."
            )
        return values
    scalar = float(raw_value)
    return tuple(scalar for _ in range(expected_length))


def _resolve_capacity_map(
    raw_value: Any,
    *,
    buses: Sequence[int],
    label: str,
) -> dict[int, int]:
    if raw_value is None:
        return {}
    if not isinstance(raw_value, Mapping):
        raise RuntimeDataValidationError(f"{label} must be a mapping from bus id to integer cap.")

    bus_set = set(int(bus) for bus in buses)
    resolved: dict[int, int] = {}
    for raw_bus, raw_cap in raw_value.items():
        try:
            bus = int(raw_bus)
        except (TypeError, ValueError) as exc:
            raise RuntimeDataValidationError(
                f"{label} has a non-integer bus key: {raw_bus!r}."
            ) from exc
        if bus not in bus_set:
            raise RuntimeDataValidationError(
                f"{label} references bus {bus}, which is not in the instance bus set."
            )
        if isinstance(raw_cap, bool):
            raise RuntimeDataValidationError(f"{label}[{bus}] must be a nonnegative integer.")
        try:
            cap = int(raw_cap)
        except (TypeError, ValueError) as exc:
            raise RuntimeDataValidationError(
                f"{label}[{bus}] must be a nonnegative integer, got {raw_cap!r}."
            ) from exc
        if float(raw_cap) != float(cap) or cap < 0:
            raise RuntimeDataValidationError(
                f"{label}[{bus}] must be a nonnegative integer, got {raw_cap!r}."
            )
        resolved[bus] = cap
    return resolved


def build_station_capacity_profile(
    instance: CanonicalInstance,
    *,
    profile_name: str,
) -> tuple[dict[int, int], dict[int, int]]:
    """Build a deterministic paper-facing capacity profile from input metadata."""

    if profile_name not in {"paper_heterogeneous", "paper_heterogeneous_headroom"}:
        raise RuntimeDataValidationError(f"Unsupported EVCS capacity profile: {profile_name!r}.")

    candidate_by_bus = {node.bus_id: bool(node.candidate_for_evcs) for node in instance.nodes}
    critical = set(instance.critical_buses or ())
    topology = instance.network_topology
    critical_neighbors: set[int] = set()
    for bus in critical:
        parent = topology.parent_by_bus.get(bus)
        if parent is not None:
            critical_neighbors.add(parent)
        critical_neighbors.update(topology.children_by_bus.get(bus, ()))

    min_distance_by_bus: dict[int, float] = {}
    for index, bus in enumerate(instance.sets.buses):
        min_distance_by_bus[bus] = min(float(row[index]) for row in instance.ev.distance_km)

    slow_caps: dict[int, int] = {}
    fast_caps: dict[int, int] = {}
    for bus in instance.sets.buses:
        if not candidate_by_bus.get(bus, False):
            slow_caps[bus] = 0
            fast_caps[bus] = 0
            continue

        degree = len(topology.children_by_bus.get(bus, ())) + (1 if bus in topology.parent_by_bus else 0)
        distance = min_distance_by_bus[bus]
        score = 0
        if bus in critical:
            score += 3
        elif bus in critical_neighbors:
            score += 2
        if distance <= 2.5:
            score += 2
        elif distance <= 4.0:
            score += 1
        if degree >= 3:
            score += 1
        if topology.bus_depth.get(bus, 999) <= 3:
            score += 1

        if profile_name == "paper_heterogeneous_headroom":
            large_cap = (40, 10)
            medium_cap = (25, 6)
            small_cap = (12, 3)
        else:
            large_cap = (25, 10)
            medium_cap = (16, 6)
            small_cap = (8, 3)

        if score >= 5:
            slow_caps[bus], fast_caps[bus] = large_cap
        elif score >= 3:
            slow_caps[bus], fast_caps[bus] = medium_cap
        else:
            slow_caps[bus], fast_caps[bus] = small_cap

    return slow_caps, fast_caps


def _validate_candidate_capacity_feasibility(
    instance: CanonicalInstance,
    *,
    slow_caps: Mapping[int, int],
    fast_caps: Mapping[int, int],
    default_slow_cap: int,
    default_fast_cap: int,
) -> None:
    for node in instance.nodes:
        if not node.candidate_for_evcs:
            continue
        slow_cap = int(slow_caps.get(node.bus_id, default_slow_cap))
        fast_cap = int(fast_caps.get(node.bus_id, default_fast_cap))
        if slow_cap + fast_cap < 3:
            raise RuntimeDataValidationError(
                "EVCS capacity profile makes candidate bus "
                f"{node.bus_id} infeasible for the three-charger minimum."
            )


def apply_parameter_overrides(
    instance: CanonicalInstance,
    overrides: Mapping[str, Any] | None,
) -> CanonicalInstance:
    """Apply packaging-scope parameter overrides without touching raw data files."""

    if not overrides:
        return instance

    economics = instance.economics
    ev = instance.ev
    ambiguity = instance.ambiguity
    metadata = dict(instance.metadata)

    economics_overrides = overrides.get("economics", {})
    objective_multiplier_overrides = overrides.get("objective_multipliers", {})
    if objective_multiplier_overrides and not isinstance(objective_multiplier_overrides, Mapping):
        raise RuntimeDataValidationError("objective_multipliers override must be a mapping.")
    if economics_overrides:
        economics_kwargs = {
            "cfix": float(economics_overrides.get("cfix", economics.cfix)),
            "ccons_sl": float(economics_overrides.get("ccons_sl", economics.ccons_sl)),
            "ccons_fa": float(economics_overrides.get("ccons_fa", economics.ccons_fa)),
            "cpur": _resolve_tuple_override(
                economics_overrides.get("cpur", economics.cpur),
                expected_length=len(economics.cpur),
                label="economics.cpur",
            ),
            "ccong": float(economics_overrides.get("ccong", economics.ccong)),
            "gamma": float(economics_overrides.get("gamma", economics.gamma)),
            "theta": int(economics_overrides.get("theta", economics.theta)),
            "pi_f": float(economics_overrides.get("pi_f", economics.pi_f)),
            "alpha_min": float(economics_overrides.get("alpha_min", economics.alpha_min)),
            "cunmet": float(economics_overrides.get("cunmet", economics.cunmet)),
            "annualize_normal_cost_by_365": bool(
                economics_overrides.get(
                    "annualize_normal_cost_by_365",
                    economics.annualize_normal_cost_by_365,
                )
            ),
            "annualize_disaster_cost_by_365": bool(
                economics_overrides.get(
                    "annualize_disaster_cost_by_365",
                    economics.annualize_disaster_cost_by_365,
                )
            ),
            "ctrans_mode": str(
                economics_overrides.get("ctrans_mode", economics.ctrans_mode)
            ),
            "power_unit": str(economics_overrides.get("power_unit", economics.power_unit)),
            "ccons_sl_extra_multiplier": float(
                economics_overrides.get(
                    "ccons_sl_extra_multiplier",
                    economics.ccons_sl_extra_multiplier,
                )
            ),
        }
        if economics_kwargs["ccons_sl_extra_multiplier"] < 1.0:
            raise RuntimeDataValidationError(
                "economics.ccons_sl_extra_multiplier must be at least 1.0."
            )
        ctrans_source = economics_overrides.get(
            "ctrans_scalar",
            economics_overrides.get("ctrans", economics.ctrans),
        )
        economics_kwargs["ctrans"] = _resolve_tuple_override(
            ctrans_source,
            expected_length=len(economics.ctrans),
            label="economics.ctrans",
        )
        economics = replace(economics, **economics_kwargs)
    if objective_multiplier_overrides:
        economics = replace(
            economics,
            objective_multipliers=ObjectiveMultipliers(
                cons=float(
                    objective_multiplier_overrides.get(
                        "cons", economics.objective_multipliers.cons
                    )
                ),
                normal=float(
                    objective_multiplier_overrides.get(
                        "normal", economics.objective_multipliers.normal
                    )
                ),
                disaster=float(
                    objective_multiplier_overrides.get(
                        "disaster", economics.objective_multipliers.disaster
                    )
                ),
            ),
        )

    ev_overrides = overrides.get("ev", {})
    if ev_overrides:
        nbar_sl = int(ev_overrides.get("nbar_sl", ev.nbar_sl))
        nbar_fa = int(ev_overrides.get("nbar_fa", ev.nbar_fa))
        slow_block_threshold = int(
            ev_overrides.get("slow_block_threshold", ev.slow_block_threshold)
        )
        if slow_block_threshold < 0:
            raise RuntimeDataValidationError("ev.slow_block_threshold must be nonnegative.")
        nbar_sl_by_bus = dict(ev.nbar_sl_by_bus)
        nbar_fa_by_bus = dict(ev.nbar_fa_by_bus)
        capacity_profile = ev_overrides.get("capacity_profile")
        if capacity_profile:
            nbar_sl_by_bus, nbar_fa_by_bus = build_station_capacity_profile(
                instance,
                profile_name=str(capacity_profile),
            )
        if "nbar_sl_by_bus" in ev_overrides:
            nbar_sl_by_bus = _resolve_capacity_map(
                ev_overrides["nbar_sl_by_bus"],
                buses=instance.sets.buses,
                label="ev.nbar_sl_by_bus",
            )
        if "nbar_fa_by_bus" in ev_overrides:
            nbar_fa_by_bus = _resolve_capacity_map(
                ev_overrides["nbar_fa_by_bus"],
                buses=instance.sets.buses,
                label="ev.nbar_fa_by_bus",
            )
        _validate_candidate_capacity_feasibility(
            instance,
            slow_caps=nbar_sl_by_bus,
            fast_caps=nbar_fa_by_bus,
            default_slow_cap=nbar_sl,
            default_fast_cap=nbar_fa,
        )
        ev = replace(
            ev,
            p_ev_rated_sl=float(ev_overrides.get("p_ev_rated_sl", ev.p_ev_rated_sl)),
            p_ev_rated_fa=float(ev_overrides.get("p_ev_rated_fa", ev.p_ev_rated_fa)),
            delta_t_hours=float(ev_overrides.get("delta_t_hours", ev.delta_t_hours)),
            nbar_sl=nbar_sl,
            nbar_fa=nbar_fa,
            nbar_sl_by_bus=nbar_sl_by_bus,
            nbar_fa_by_bus=nbar_fa_by_bus,
            slow_block_threshold=slow_block_threshold,
        )

    ambiguity_overrides = overrides.get("ambiguity", {})
    if ambiguity_overrides:
        p_bar_source = ambiguity_overrides.get("p_bar", ambiguity.p_bar)
        ambiguity = replace(
            ambiguity,
            k_max_outages=int(ambiguity_overrides.get("k_max_outages", ambiguity.k_max_outages)),
            p_bar=_resolve_tuple_override(
                p_bar_source,
                expected_length=len(ambiguity.p_bar),
                label="ambiguity.p_bar",
            ),
        )

    cls_by_bus = instance.cls_by_bus
    is_critical_by_bus = instance.is_critical_by_bus
    disaster_overrides = overrides.get("disaster_objective", {})
    if disaster_overrides:
        cls_critical = float(
            disaster_overrides.get(
                "cls_critical",
                instance.frozen_config.disaster_objective.cls_critical,
            )
        )
        cls_noncritical = float(
            disaster_overrides.get(
                "cls_noncritical",
                instance.frozen_config.disaster_objective.cls_noncritical,
            )
        )
        is_critical_by_bus, cls_by_bus = build_criticality_maps(
            buses=instance.sets.buses,
            critical_buses=instance.critical_buses,
            cls_critical=cls_critical,
            cls_noncritical=cls_noncritical,
        )

    metadata["parameter_overrides"] = json.loads(json.dumps(overrides))
    return replace(
        instance,
        economics=economics,
        ev=ev,
        ambiguity=ambiguity,
        cls_by_bus=cls_by_bus,
        is_critical_by_bus=is_critical_by_bus,
        metadata=metadata,
    )


def prepare_instance_for_run(
    base_instance: CanonicalInstance,
    run_config: Mapping[str, Any],
) -> CanonicalInstance:
    """Apply benchmark-only transformations in packaging scope."""

    instance = apply_parameter_overrides(base_instance, run_config.get("parameter_overrides"))
    if float(run_config.get("ev_penetration_scale", 1.0)) != 1.0:
        instance = build_ev_penetration_instance(
            instance,
            scale=float(run_config["ev_penetration_scale"]),
        )
    if run_config.get("mode") == "deterministic_mean_value":
        instance = build_mean_value_instance(instance)
    if run_config.get("mode") == "deterministic_disaster_mean_value":
        instance = build_disaster_mean_value_instance(instance)
    if run_config.get("mode") == "normal_only":
        instance = build_normal_only_instance(instance)
    if run_config.get("mode") == "disaster_only":
        instance = build_disaster_only_instance(instance)
    return instance


def _validation_level_from_result(
    *,
    solver: str,
    stop_reason: str,
    solver_status: str,
) -> str:
    normalized_status = str(solver_status).upper()
    if solver == "direct_master" and normalized_status == "OPTIMAL":
        return "exact"
    if normalized_status == "OPTIMAL" and stop_reason == "certified_exact":
        return "exact"
    if normalized_status == "OPTIMAL" and stop_reason == "certified_epsilon":
        return "epsilon_certified"
    if normalized_status == "OPTIMAL" and stop_reason == "certified_epsilon_bound":
        return "epsilon_certified"
    if solver == "benders" and normalized_status == "OPTIMAL":
        return "smoke_only"
    return "failed"


def _record_failure(
    *,
    validation_level: str,
    stop_reason: str,
) -> bool:
    return validation_level in {"failed", "smoke_only"} or stop_reason == "max_iterations"


def _failure_message(
    *,
    validation_level: str,
    stop_reason: str,
    solver_status: str,
    exception: Exception | None = None,
) -> str:
    if exception is not None:
        return f"{exception.__class__.__name__}: {exception}"
    if validation_level == "smoke_only":
        return (
            "Run completed a bounded smoke-only solve but did not certify; "
            f"stop_reason={stop_reason}, solver_status={solver_status}."
        )
    return f"Run ended with stop_reason={stop_reason}, solver_status={solver_status}."


def _plan_rows(
    instance: CanonicalInstance,
    solution: RestrictedMasterProblemSolution,
) -> list[dict[str, Any]]:
    return [
        {
            "bus": bus,
            "is_open": int(solution.first_stage_solution.z_by_bus[bus]),
            "n_sl": int(solution.first_stage_solution.n_sl_by_bus[bus]),
            "n_fa": int(solution.first_stage_solution.n_fa_by_bus[bus]),
            "is_critical": int(
                bool(instance.is_critical_by_bus and instance.is_critical_by_bus[bus])
            ),
            "region": "",
        }
        for bus in instance.sets.buses
    ]


def _plan_rows_from_trial_certificate(
    instance: CanonicalInstance,
    trial_certificate_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Build plan CSV rows from a trial-certificate first-stage payload."""

    first_stage_plan = dict(trial_certificate_payload.get("first_stage_plan", {}))
    z_by_bus = dict(first_stage_plan.get("z_by_bus", {}))
    n_sl_by_bus = dict(first_stage_plan.get("n_sl_by_bus", {}))
    n_fa_by_bus = dict(first_stage_plan.get("n_fa_by_bus", {}))
    return [
        {
            "bus": bus,
            "is_open": int(z_by_bus.get(str(bus), z_by_bus.get(bus, 0))),
            "n_sl": int(n_sl_by_bus.get(str(bus), n_sl_by_bus.get(bus, 0))),
            "n_fa": int(n_fa_by_bus.get(str(bus), n_fa_by_bus.get(bus, 0))),
            "is_critical": int(
                bool(instance.is_critical_by_bus and instance.is_critical_by_bus[bus])
            ),
            "region": "",
        }
        for bus in instance.sets.buses
    ]


def write_plan_csv(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    """Write one plan-detail CSV."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["bus", "is_open", "n_sl", "n_fa", "is_critical", "region"]
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return file_path


def write_summary_csv(path: str | Path, summaries: Sequence[ExperimentRunSummary]) -> Path:
    """Write the experiment summary CSV."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ExperimentRunSummary.__dataclass_fields__.keys())
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            writer.writerow(summary.to_csv_row())
    return file_path


def write_failures_csv(
    path: str | Path,
    failures: Sequence[ExperimentFailureSummary],
) -> Path:
    """Write the explicit failure/non-convergence CSV."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ExperimentFailureSummary.__dataclass_fields__.keys())
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for failure in failures:
            writer.writerow(failure.to_csv_row())
    return file_path


def write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write stable JSON."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return file_path


def _load_fixed_plan_from_csv(
    instance: CanonicalInstance,
    path: str | Path,
) -> FixedFirstStagePlan:
    rows: list[dict[str, str]] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(row["bus"]): int(float(row["is_open"])) for row in rows},
        n_sl_by_bus={int(row["bus"]): int(float(row["n_sl"])) for row in rows},
        n_fa_by_bus={int(row["bus"]): int(float(row["n_fa"])) for row in rows},
    )


def _resolve_warm_start_plan(
    instance: CanonicalInstance,
    benders_config: Mapping[str, Any],
) -> FixedFirstStagePlan | None:
    raw_paths: list[str] = []
    if benders_config.get("warm_start_plan_path"):
        raw_paths.append(str(benders_config["warm_start_plan_path"]))
    if isinstance(benders_config.get("warm_start_plan_paths"), Sequence):
        raw_paths.extend(str(path) for path in benders_config["warm_start_plan_paths"])
    for raw_path in raw_paths:
        path = Path(raw_path)
        if path.exists():
            return _load_fixed_plan_from_csv(instance, path)
    return None


def _cut_to_payload(cut: RestrictedMasterCut) -> dict[str, Any]:
    return {
        "cut_id": str(cut.cut_id),
        "beta": float(cut.beta),
        "gamma_z_by_bus": {str(bus): float(value) for bus, value in cut.gamma_z_by_bus.items()},
        "gamma_n_sl_by_bus": {
            str(bus): float(value) for bus, value in cut.gamma_n_sl_by_bus.items()
        },
        "gamma_n_fa_by_bus": {
            str(bus): float(value) for bus, value in cut.gamma_n_fa_by_bus.items()
        },
        "phi_by_line_id": {
            str(line_id): float(value) for line_id, value in cut.phi_by_line_id.items()
        },
        "cut_signature_hash": compute_cut_signature_hash(cut),
    }


def _cut_from_payload(
    payload: Mapping[str, Any],
    *,
    cut_id_prefix: str = "",
) -> RestrictedMasterCut:
    raw_cut_id = str(payload["cut_id"])
    return RestrictedMasterCut(
        cut_id=f"{cut_id_prefix}{raw_cut_id}",
        beta=float(payload["beta"]),
        gamma_z_by_bus={
            int(bus): float(value)
            for bus, value in dict(payload.get("gamma_z_by_bus", {})).items()
        },
        gamma_n_sl_by_bus={
            int(bus): float(value)
            for bus, value in dict(payload.get("gamma_n_sl_by_bus", {})).items()
        },
        gamma_n_fa_by_bus={
            int(bus): float(value)
            for bus, value in dict(payload.get("gamma_n_fa_by_bus", {})).items()
        },
        phi_by_line_id={
            str(line_id): float(value)
            for line_id, value in dict(payload.get("phi_by_line_id", {})).items()
        },
    )


def _outage_column_cut_to_payload(row: RestrictedMasterOutageColumnCut) -> dict[str, Any]:
    return {
        "row_id": str(row.row_id),
        "column_id": str(row.column_id),
        "active_line_ids": [str(line_id) for line_id in row.active_line_ids],
        "cut": _cut_to_payload(row.cut),
    }


def _outage_column_cut_from_payload(
    payload: Mapping[str, Any],
    *,
    row_id_prefix: str = "",
) -> RestrictedMasterOutageColumnCut:
    return RestrictedMasterOutageColumnCut(
        row_id=f"{row_id_prefix}{payload['row_id']}",
        column_id=str(payload["column_id"]),
        active_line_ids=tuple(str(line_id) for line_id in payload["active_line_ids"]),
        cut=_cut_from_payload(payload["cut"], cut_id_prefix=row_id_prefix),
    )


def _cut_pool_metadata(
    instance: CanonicalInstance,
    run_config: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "runtime_source": str(run_config.get("runtime_source", "")),
        "mode": str(run_config.get("mode", "")),
        "benchmark_mode": str(instance.metadata.get("benchmark_mode", "")),
        "normal_scenarios": [int(value) for value in instance.sets.loaded_normal_scenarios],
        "disaster_scenarios": [int(value) for value in instance.sets.loaded_disaster_scenarios],
        "K": int(instance.ambiguity.k_max_outages),
        "buses": [int(value) for value in instance.sets.buses],
        "line_ids": [str(value) for value in instance.sets.line_ids],
    }


def _cut_pool_matches(
    *,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
) -> bool:
    return all(observed.get(key) == expected.get(key) for key in expected)


def _write_cut_pool(
    path: Path,
    *,
    instance: CanonicalInstance,
    run_config: Mapping[str, Any],
    cuts: Sequence[RestrictedMasterCut],
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut] = (),
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nontrivial_cuts = [cut for cut in cuts if not cut.is_trivial()]
    nontrivial_outage_column_cuts = [
        row for row in outage_column_cuts if not row.cut.is_trivial()
    ]
    payload = {
        "metadata": _cut_pool_metadata(instance, run_config),
        "cut_count": len(nontrivial_cuts),
        "cuts": [_cut_to_payload(cut) for cut in nontrivial_cuts],
        "outage_column_cut_count": len(nontrivial_outage_column_cuts),
        "outage_column_cuts": [
            _outage_column_cut_to_payload(row) for row in nontrivial_outage_column_cuts
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _resolve_cut_pool_paths(benders_config: Mapping[str, Any]) -> list[Path]:
    raw_paths: list[str] = []
    if benders_config.get("initial_cut_pool_path"):
        raw_paths.append(str(benders_config["initial_cut_pool_path"]))
    if isinstance(benders_config.get("initial_cut_pool_paths"), Sequence):
        raw_paths.extend(str(path) for path in benders_config["initial_cut_pool_paths"])
    return [Path(path) for path in raw_paths]


def _read_active_outage_patterns(paths: Sequence[str | Path]) -> list[tuple[str, ...]]:
    patterns: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                raw_pattern = (
                    row.get("pattern_key")
                    or row.get("selected_outage_active_lines")
                    or row.get("active_lines")
                    or ""
                )
                if not raw_pattern:
                    continue
                pattern = tuple(
                    sorted(
                        line_id.strip()
                        for line_id in str(raw_pattern).split(";")
                        if line_id.strip()
                    )
                )
                if not pattern or pattern in seen:
                    continue
                seen.add(pattern)
                patterns.append(pattern)
    return patterns


def _load_initial_cuts_from_pools(
    instance: CanonicalInstance,
    run_config: Mapping[str, Any],
    benders_config: Mapping[str, Any],
) -> tuple[
    list[RestrictedMasterCut],
    list[RestrictedMasterOutageColumnCut],
    list[dict[str, Any]],
]:
    expected_metadata = _cut_pool_metadata(instance, run_config)
    loaded_cuts: list[RestrictedMasterCut] = []
    loaded_outage_column_cuts: list[RestrictedMasterOutageColumnCut] = []
    audit_rows: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    seen_rowwise_keys: set[tuple[tuple[str, ...], str]] = set()
    for pool_index, path in enumerate(_resolve_cut_pool_paths(benders_config), start=1):
        if not path.exists():
            audit_rows.append({
                "path": str(path),
                "status": "rejected_missing",
                "loaded_cut_count": 0,
                "loaded_outage_column_cut_count": 0,
                "duplicate_cut_count": 0,
                "duplicate_outage_column_cut_count": 0,
                "observed_cut_count": 0,
                "observed_outage_column_cut_count": 0,
                "metadata_match": False,
                "reason": "path_not_found",
            })
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed_metadata = dict(payload.get("metadata", {}))
        metadata_match = _cut_pool_matches(expected=expected_metadata, observed=observed_metadata)
        if not _cut_pool_matches(expected=expected_metadata, observed=observed_metadata):
            audit_rows.append({
                "path": str(path),
                "status": "rejected_metadata_mismatch",
                "loaded_cut_count": 0,
                "loaded_outage_column_cut_count": 0,
                "duplicate_cut_count": 0,
                "duplicate_outage_column_cut_count": 0,
                "observed_cut_count": int(payload.get("cut_count", 0) or 0),
                "observed_outage_column_cut_count": int(
                    payload.get("outage_column_cut_count", 0) or 0
                ),
                "metadata_match": metadata_match,
                "reason": "runtime_source/mode/support/K/buses/lines mismatch",
            })
            continue
        pool_loaded = 0
        pool_loaded_rowwise = 0
        pool_duplicate = 0
        pool_duplicate_rowwise = 0
        for cut_payload in payload.get("cuts", ()):
            cut = _cut_from_payload(cut_payload, cut_id_prefix=f"seed{pool_index}_")
            signature = compute_cut_signature_hash(cut)
            if signature in seen_signatures:
                pool_duplicate += 1
                continue
            seen_signatures.add(signature)
            loaded_cuts.append(cut)
            pool_loaded += 1
        for row_payload in payload.get("outage_column_cuts", ()):
            row = _outage_column_cut_from_payload(
                row_payload,
                row_id_prefix=f"seed{pool_index}_",
            )
            rowwise_key = (
                tuple(str(line_id) for line_id in row.active_line_ids),
                str(compute_cut_signature_hash(row.cut)),
            )
            if rowwise_key in seen_rowwise_keys:
                pool_duplicate_rowwise += 1
                continue
            seen_rowwise_keys.add(rowwise_key)
            loaded_outage_column_cuts.append(row)
            pool_loaded_rowwise += 1
        audit_rows.append({
            "path": str(path),
            "status": "accepted",
            "loaded_cut_count": pool_loaded,
            "loaded_outage_column_cut_count": pool_loaded_rowwise,
            "duplicate_cut_count": pool_duplicate,
            "duplicate_outage_column_cut_count": pool_duplicate_rowwise,
            "observed_cut_count": int(payload.get("cut_count", 0) or 0),
            "observed_outage_column_cut_count": int(
                payload.get("outage_column_cut_count", 0) or 0
            ),
            "metadata_match": metadata_match,
            "reason": "",
        })
    return loaded_cuts, loaded_outage_column_cuts, audit_rows


def build_summary_row(
    *,
    run_config: Mapping[str, Any],
    validation_level: str,
    stop_reason: str,
    solver_status: str,
    solution: RestrictedMasterProblemSolution | None,
    iteration_count: int,
    cut_count: int,
    final_violation_upper_bound: float | None,
) -> ExperimentRunSummary:
    """Build the stable summary row for one run."""

    if solution is None:
        return ExperimentRunSummary(
            run_id=str(run_config["run_id"]),
            family_name=str(run_config["family_name"]),
            case_name=str(run_config["case_name"]),
            parameter_regime=str(run_config["parameter_regime"]),
            validation_level=validation_level,
            stop_reason=str(stop_reason),
            solver_status=str(solver_status),
            total_objective=None,
            construction_cost=None,
            weighted_normal_term=None,
            unweighted_normal_term=None,
            disaster_master_term=None,
            alpha=None,
            lambda_times_FP=None,
            iteration_count=int(iteration_count),
            cut_count=int(cut_count),
            final_violation_upper_bound=final_violation_upper_bound,
            opened_bus_count=None,
            total_slow_chargers=None,
            total_fast_chargers=None,
        )

    first_stage = solution.first_stage_solution
    opened_bus_count = int(sum(first_stage.z_by_bus.values()))
    total_slow = int(sum(first_stage.n_sl_by_bus.values()))
    total_fast = int(sum(first_stage.n_fa_by_bus.values()))
    return ExperimentRunSummary(
        run_id=str(run_config["run_id"]),
        family_name=str(run_config["family_name"]),
        case_name=str(run_config["case_name"]),
        parameter_regime=str(run_config["parameter_regime"]),
        validation_level=validation_level,
        stop_reason=str(stop_reason),
        solver_status=str(solver_status),
        total_objective=float(solution.objective_value or 0.0),
        construction_cost=float(solution.construction_cost_value),
        weighted_normal_term=float(solution.averaged_normal_cost_value),
        unweighted_normal_term=float(solution.unweighted_average_normal_cost_value),
        disaster_master_term=float(solution.disaster_master_cost_value),
        alpha=float(solution.alpha_value),
        lambda_times_FP=float(solution.lambda_fp_value),
        iteration_count=int(iteration_count),
        cut_count=int(cut_count),
        final_violation_upper_bound=(
            None if final_violation_upper_bound is None else float(final_violation_upper_bound)
        ),
        opened_bus_count=opened_bus_count,
        total_slow_chargers=total_slow,
        total_fast_chargers=total_fast,
    )


def build_failure_row(
    *,
    run_config: Mapping[str, Any],
    validation_level: str,
    stop_reason: str,
    solver_status: str,
    iteration_count: int,
    cut_count: int,
    final_violation_upper_bound: float | None,
    message: str,
) -> ExperimentFailureSummary:
    """Build the stable failure/non-convergence row."""

    return ExperimentFailureSummary(
        run_id=str(run_config["run_id"]),
        case_name=str(run_config["case_name"]),
        parameter_regime=str(run_config["parameter_regime"]),
        validation_level=str(validation_level),
        stop_reason=str(stop_reason),
        solver_status=str(solver_status),
        iteration_count=int(iteration_count),
        cut_count=int(cut_count),
        final_violation_upper_bound=(
            None if final_violation_upper_bound is None else float(final_violation_upper_bound)
        ),
        message=str(message),
    )


def _selected_scenarios_fallback(run_config: Mapping[str, Any], key: str) -> list[int]:
    selection = run_config.get("selection")
    if isinstance(selection, Mapping):
        raw = selection.get(key, ())
        if isinstance(raw, Sequence):
            return [int(value) for value in raw]
    if run_config.get("selection_preset") == "default_small":
        if key == "scenarios_a":
            return [1, 2]
        return [1, 2]
    return []


def execute_run(
    run_config: Mapping[str, Any],
    *,
    critical_buses: Sequence[int],
    output_root: str | Path,
) -> dict[str, Any]:
    """Execute one experiment run and return full packaging metadata."""

    output_root_path = ensure_directory(output_root)
    plans_dir = ensure_directory(output_root_path / "plans")
    logs_dir = ensure_directory(output_root_path / "logs")

    run_id = str(run_config["run_id"])
    solver = str(run_config["solver"])

    artifact_paths: dict[str, str | None] = {
        "master_before_cut_lp_path": None,
        "master_after_cut_lp_path": None,
        "iteration_log_path": None,
        "live_iteration_trace_path": None,
        "live_iteration_jsonl_path": None,
        "cut_pool_path": None,
        "cut_pool_audit_path": None,
        "trial_certificate_path": None,
        "trial_plan_path": None,
    }

    instance: CanonicalInstance | None = None
    solution: RestrictedMasterProblemSolution | None = None
    plan_rows: list[dict[str, Any]] = []
    plan_path: Path | None = None
    lower_bound_sequence: list[float] = []
    cut_count_sequence: list[int] = []
    iteration_payload: dict[str, Any] | None = None
    normal_cost_by_scenario: dict[str, float] = {}
    objective_components: dict[str, Any] = {}
    iteration_count = 0
    cut_count = 0
    final_violation_upper_bound: float | None = None
    stop_reason = "not_started"
    solver_status = "NOT_STARTED"
    validation_level = "failed"
    message = ""
    exception_payload: dict[str, Any] | None = None
    cut_pool_audit_rows: list[dict[str, Any]] = []
    trial_certificate_payload: dict[str, Any] | None = None

    try:
        base_instance = load_instance_for_run(run_config, critical_buses=critical_buses)
        instance = prepare_instance_for_run(base_instance, run_config)

        if solver == "direct_master":
            _, solution = solve_master_problem(
                instance,
                model_name=f"{run_id}_direct_master",
            )
            solver_status = str(solution.model_status)
            stop_reason = "direct_optimal" if solver_status == "OPTIMAL" else solver_status
            iteration_count = 0
            cut_count = 1
            final_violation_upper_bound = 0.0
        elif solver == "benders":
            benders_config = dict(run_config.get("benders", {}))
            capture_artifacts = bool(benders_config.get("capture_artifacts", False))
            if capture_artifacts:
                artifact_paths["master_before_cut_lp_path"] = str(
                    Path("/tmp") / f"{run_id}_master_before_cut.lp"
                )
                artifact_paths["master_after_cut_lp_path"] = str(
                    Path("/tmp") / f"{run_id}_master_after_cut.lp"
                )
            artifact_paths["iteration_log_path"] = str(logs_dir / f"{run_id}_iteration_log.json")
            if bool(benders_config.get("enable_live_iteration_trace", False)):
                artifact_paths["live_iteration_trace_path"] = str(
                    logs_dir / f"{run_id}_live_iteration_trace.csv"
                )
                artifact_paths["live_iteration_jsonl_path"] = str(
                    logs_dir / f"{run_id}_live_iteration_trace.jsonl"
                )
            warm_start_plan = _resolve_warm_start_plan(instance, benders_config)
            (
                initial_cuts,
                initial_outage_column_cuts,
                cut_pool_audit_rows,
            ) = _load_initial_cuts_from_pools(
                instance,
                run_config,
                benders_config,
            )
            if cut_pool_audit_rows:
                artifact_paths["cut_pool_audit_path"] = str(
                    logs_dir / f"{run_id}_cut_pool_audit.csv"
                )
                with Path(artifact_paths["cut_pool_audit_path"]).open(
                    "w", encoding="utf-8", newline=""
                ) as handle:
                    fieldnames = [
                        "path",
                        "status",
                        "loaded_cut_count",
                        "loaded_outage_column_cut_count",
                        "duplicate_cut_count",
                        "duplicate_outage_column_cut_count",
                        "observed_cut_count",
                        "observed_outage_column_cut_count",
                        "metadata_match",
                        "reason",
                    ]
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in cut_pool_audit_rows:
                        writer.writerow({key: row.get(key, "") for key in fieldnames})
            omega_bounds_by_line_id = None
            if benders_config.get("omega_bound_upper") not in (None, ""):
                omega_upper = float(benders_config["omega_bound_upper"])
                omega_bounds_by_line_id = {
                    line_id: (0.0, omega_upper)
                    for line_id in instance.sets.line_ids
                }
            benders_result: BendersEngineResult = run_benders_engine(
                instance,
                cuts=initial_cuts or None,
                omega_bounds_by_line_id=omega_bounds_by_line_id,
                omega_bound_safety_factor=float(
                    benders_config.get("omega_bound_safety_factor", 2.0)
                ),
                warm_start_plan=warm_start_plan,
                master_time_limit_seconds=(
                    None
                    if benders_config.get("master_time_limit_seconds") in (None, "")
                    else float(benders_config["master_time_limit_seconds"])
                ),
                master_mip_gap=(
                    None
                    if benders_config.get("master_mip_gap") in (None, "")
                    else float(benders_config["master_mip_gap"])
                ),
                master_gurobi_params=dict(benders_config.get("master_gurobi_params", {})),
                separation_time_limit_seconds=(
                    None
                    if benders_config.get("separation_time_limit_seconds") in (None, "")
                    else float(benders_config["separation_time_limit_seconds"])
                ),
                separation_mip_gap=(
                    None
                    if benders_config.get("separation_mip_gap") in (None, "")
                    else float(benders_config["separation_mip_gap"])
                ),
                separation_gurobi_params=dict(
                    benders_config.get("separation_gurobi_params", {})
                ),
                allow_master_suboptimal_incumbent=bool(
                    benders_config.get("allow_master_suboptimal_incumbent", False)
                ),
                epsilon_cert=float(benders_config.get("epsilon_cert", 0.0)),
                max_iterations=int(benders_config.get("max_iterations", 25)),
                separation_top_cuts_per_iteration=int(
                    benders_config.get("separation_top_cuts_per_iteration", 1)
                ),
                separation_pool_cuts_per_iteration=int(
                    benders_config.get("separation_pool_cuts_per_iteration", 0)
                ),
                adaptive_top_cuts_switch_violation=(
                    None
                    if benders_config.get("adaptive_top_cuts_switch_violation") in {None, ""}
                    else float(benders_config.get("adaptive_top_cuts_switch_violation"))
                ),
                adaptive_top_cuts_after_switch=int(
                    benders_config.get("adaptive_top_cuts_after_switch", 1)
                ),
                allow_nonoptimal_separation_cuts=bool(
                    benders_config.get("allow_nonoptimal_separation_cuts", False)
                ),
                nonoptimal_separation_cut_tolerance=(
                    None
                    if benders_config.get("nonoptimal_separation_cut_tolerance") in {None, ""}
                    else float(benders_config.get("nonoptimal_separation_cut_tolerance"))
                ),
                enable_pareto_core_cuts=bool(
                    benders_config.get("enable_pareto_core_cuts", False)
                ),
                stabilization_mode=(
                    None
                    if benders_config.get("stabilization_mode") in {None, "", "none"}
                    else str(benders_config.get("stabilization_mode"))
                ),
                stabilization_z_radius=(
                    None
                    if benders_config.get("stabilization_z_radius") in {None, ""}
                    else int(benders_config.get("stabilization_z_radius"))
                ),
                stabilization_charger_sl_radius=(
                    None
                    if benders_config.get("stabilization_charger_sl_radius") in {None, ""}
                    else int(benders_config.get("stabilization_charger_sl_radius"))
                ),
                stabilization_charger_fa_radius=(
                    None
                    if benders_config.get("stabilization_charger_fa_radius") in {None, ""}
                    else int(benders_config.get("stabilization_charger_fa_radius"))
                ),
                stabilization_center_update_policy=str(
                    benders_config.get("stabilization_center_update_policy", "fixed")
                    or "fixed"
                ),
                enable_level_bundle_trial=bool(
                    benders_config.get("enable_level_bundle_trial", False)
                ),
                level_bundle_objective_slack_abs=float(
                    benders_config.get("level_bundle_objective_slack_abs", 5000.0)
                ),
                level_bundle_objective_slack_fraction=float(
                    benders_config.get("level_bundle_objective_slack_fraction", 0.05)
                ),
                level_bundle_rho_n=float(
                    benders_config.get("level_bundle_rho_n", 0.2)
                ),
                level_bundle_rho_alpha=float(
                    benders_config.get("level_bundle_rho_alpha", 0.05)
                ),
                level_bundle_rho_lambda=float(
                    benders_config.get("level_bundle_rho_lambda", 1.0)
                ),
                enable_active_set_cuts=bool(
                    benders_config.get("enable_active_set_cuts", False)
                ),
                active_delta_max=int(benders_config.get("active_delta_max", 50)),
                active_neighbor_radius=int(
                    benders_config.get("active_neighbor_radius", 1)
                ),
                active_max_candidates_per_iteration=int(
                    benders_config.get("active_max_candidates_per_iteration", 5)
                ),
                active_cuts_per_iteration=int(
                    benders_config.get("active_cuts_per_iteration", 3)
                ),
                active_select_top_violations=bool(
                    benders_config.get("active_select_top_violations", False)
                ),
                active_min_hamming_distance=int(
                    benders_config.get("active_min_hamming_distance", 0)
                ),
                initial_active_outage_patterns=_read_active_outage_patterns(
                    (
                        [benders_config["initial_active_outage_pattern_paths"]]
                        if isinstance(
                            benders_config.get("initial_active_outage_pattern_paths"),
                            str,
                        )
                        else benders_config.get("initial_active_outage_pattern_paths", [])
                    )
                ),
                initial_outage_column_cuts=initial_outage_column_cuts,
                enable_exact_outage_rows=bool(
                    benders_config.get("enable_exact_outage_rows", False)
                ),
                exact_rows_per_iteration=int(
                    benders_config.get("exact_rows_per_iteration", 0)
                ),
                exact_row_max=int(benders_config.get("exact_row_max", 30)),
                exact_rows_include_active=bool(
                    benders_config.get("exact_rows_include_active", True)
                ),
                enable_nccg_outage_columns=bool(
                    benders_config.get("enable_nccg_outage_columns", False)
                ),
                nccg_keep_global_cuts=bool(
                    benders_config.get("nccg_keep_global_cuts", False)
                ),
                nccg_complete_active_columns=bool(
                    benders_config.get("nccg_complete_active_columns", False)
                ),
                nccg_completion_tolerance=float(
                    benders_config.get("nccg_completion_tolerance", 100.0)
                ),
                nccg_completion_max_cuts_per_iteration=int(
                    benders_config.get("nccg_completion_max_cuts_per_iteration", 5)
                ),
                nccg_completion_order=str(
                    benders_config.get("nccg_completion_order", "oldest") or "oldest"
                ),
                enable_persistent_pricing_pool=bool(
                    benders_config.get("enable_persistent_pricing_pool", False)
                ),
                pricing_capture_passes=int(
                    benders_config.get("pricing_capture_passes", 0)
                ),
                pricing_capture_diversity_radius=int(
                    benders_config.get("pricing_capture_diversity_radius", 4)
                ),
                cross_column_broadcast=bool(
                    benders_config.get("cross_column_broadcast", False)
                ),
                broadcast_top_columns=int(
                    benders_config.get("broadcast_top_columns", 30)
                ),
                broadcast_violation_tolerance=float(
                    benders_config.get("broadcast_violation_tolerance", 100.0)
                ),
                enable_certified_serious_step=bool(
                    benders_config.get("enable_certified_serious_step", False)
                ),
                serious_level_kappa=float(
                    benders_config.get("serious_level_kappa", 0.35)
                ),
                serious_eta_ub=float(benders_config.get("serious_eta_ub", 0.01)),
                serious_tau_ub=float(benders_config.get("serious_tau_ub", 10.0)),
                serious_eta_violation=float(
                    benders_config.get("serious_eta_violation", 0.15)
                ),
                serious_chi=float(benders_config.get("serious_chi", 0.05)),
                serious_null_limit=int(benders_config.get("serious_null_limit", 3)),
                enable_target_face_bundle_cuts=bool(
                    benders_config.get("enable_target_face_bundle_cuts", False)
                ),
                target_face_candidate_limit=int(
                    benders_config.get("target_face_candidate_limit", 30)
                ),
                target_face_cuts_per_iteration=int(
                    benders_config.get("target_face_cuts_per_iteration", 6)
                ),
                target_face_neighbor_radius=int(
                    benders_config.get("target_face_neighbor_radius", 1)
                ),
                target_face_add_violation_fraction=float(
                    benders_config.get("target_face_add_violation_fraction", 0.01)
                ),
                target_face_tolerance_rel=float(
                    benders_config.get("target_face_tolerance_rel", 1e-6)
                ),
                enable_cluster_face_bundle_cuts=bool(
                    benders_config.get("enable_cluster_face_bundle_cuts", False)
                ),
                cluster_face_candidate_limit=int(
                    benders_config.get("cluster_face_candidate_limit", 30)
                ),
                cluster_face_cuts_per_iteration=int(
                    benders_config.get("cluster_face_cuts_per_iteration", 2)
                ),
                cluster_face_add_violation_fraction=float(
                    benders_config.get("cluster_face_add_violation_fraction", 0.01)
                ),
                cluster_face_tolerance_rel=float(
                    benders_config.get("cluster_face_tolerance_rel", 1e-6)
                ),
                enable_lambda_face_prox_trial=bool(
                    benders_config.get("enable_lambda_face_prox_trial", False)
                ),
                lambda_face_level_slack_abs=float(
                    benders_config.get("lambda_face_level_slack_abs", 500.0)
                ),
                lambda_face_level_slack_fraction=float(
                    benders_config.get("lambda_face_level_slack_fraction", 0.05)
                ),
                lambda_face_rho_alpha=float(
                    benders_config.get("lambda_face_rho_alpha", 0.05)
                ),
                enable_alpha_lambda_warm_start=bool(
                    benders_config.get("enable_alpha_lambda_warm_start", True)
                ),
                enable_cut_signature_dedup=bool(
                    benders_config.get("enable_cut_signature_dedup", False)
                ),
                enable_repeated_outage_guard=bool(
                    benders_config.get("enable_repeated_outage_guard", False)
                ),
                model_name_prefix=run_id,
                master_before_cut_lp_path=artifact_paths["master_before_cut_lp_path"],
                master_after_cut_lp_path=artifact_paths["master_after_cut_lp_path"],
                iteration_log_path=artifact_paths["iteration_log_path"],
                live_iteration_trace_path=artifact_paths["live_iteration_trace_path"],
                live_iteration_jsonl_path=artifact_paths["live_iteration_jsonl_path"],
                adaptive_stall_window_iterations=int(
                    benders_config.get("adaptive_stall_window_iterations", 0)
                ),
                adaptive_stall_min_relative_improvement=float(
                    benders_config.get("adaptive_stall_min_relative_improvement", 0.0)
                ),
            )
            artifact_paths["cut_pool_path"] = str(logs_dir / f"{run_id}_cut_pool.json")
            _write_cut_pool(
                Path(artifact_paths["cut_pool_path"]),
                instance=instance,
                run_config=run_config,
                cuts=[result.cut for result in benders_result.generated_cut_results],
                outage_column_cuts=benders_result.final_master.outage_column_cuts,
            )
            if benders_result.trial_certificate is not None:
                trial_certificate_payload = asdict(benders_result.trial_certificate)
                artifact_paths["trial_certificate_path"] = str(
                    logs_dir / f"{run_id}_trial_certificate.json"
                )
                write_json(
                    artifact_paths["trial_certificate_path"],
                    trial_certificate_payload,
                )
                trial_plan_rows = _plan_rows_from_trial_certificate(
                    instance,
                    trial_certificate_payload,
                )
                artifact_paths["trial_plan_path"] = str(
                    plans_dir / f"{run_id}_trial_plan.csv"
                )
                write_plan_csv(artifact_paths["trial_plan_path"], trial_plan_rows)
            solution = benders_result.final_solution
            stop_reason = str(benders_result.stop_reason)
            solver_status = str(solution.model_status)
            iteration_count = len(benders_result.iterations)
            cut_count = len(benders_result.final_master.cuts)
            final_violation_upper_bound = float(
                benders_result.certificate.final_violation_upper_bound
            )
            lower_bound_sequence = list(benders_result.lower_bound_sequence)
            cut_count_sequence = list(benders_result.cut_count_sequence)
            iteration_payload = asdict(benders_result.iteration_log_artifact)
        else:
            raise ValueError(f"Unsupported solver {solver!r}.")

        validation_level = _validation_level_from_result(
            solver=solver,
            stop_reason=stop_reason,
            solver_status=solver_status,
        )
        if _record_failure(validation_level=validation_level, stop_reason=stop_reason):
            message = _failure_message(
                validation_level=validation_level,
                stop_reason=stop_reason,
                solver_status=solver_status,
            )

        if solution is not None:
            plan_rows = _plan_rows(instance, solution)
            plan_path = write_plan_csv(plans_dir / f"{run_id}_plan.csv", plan_rows)
            normal_cost_by_scenario = {
                str(key): float(value) for key, value in solution.normal_cost_by_scenario.items()
            }
            objective_components = {
                "construction_cost": float(solution.construction_cost_value),
                "weighted_normal_term": float(solution.averaged_normal_cost_value),
                "unweighted_normal_term": float(solution.unweighted_average_normal_cost_value),
                "disaster_master_term": float(solution.disaster_master_cost_value),
                "alpha": float(solution.alpha_value),
                "lambda_times_FP": float(solution.lambda_fp_value),
                "objective_reconstruction_gap": float(solution.objective_reconstruction_gap),
            }
    except Exception as exc:  # pragma: no cover - exercised by integration path
        stop_reason = "exception"
        solver_status = "EXCEPTION"
        validation_level = "failed"
        message = _failure_message(
            validation_level=validation_level,
            stop_reason=stop_reason,
            solver_status=solver_status,
            exception=exc,
        )
        exception_payload = {
            "type": exc.__class__.__name__,
            "message": str(exc),
        }

    summary = build_summary_row(
        run_config=run_config,
        validation_level=validation_level,
        stop_reason=stop_reason,
        solver_status=solver_status,
        solution=solution,
        iteration_count=iteration_count,
        cut_count=cut_count,
        final_violation_upper_bound=final_violation_upper_bound,
    )

    failure_summary: ExperimentFailureSummary | None = None
    if _record_failure(validation_level=validation_level, stop_reason=stop_reason):
        failure_summary = build_failure_row(
            run_config=run_config,
            validation_level=validation_level,
            stop_reason=stop_reason,
            solver_status=solver_status,
            iteration_count=iteration_count,
            cut_count=cut_count,
            final_violation_upper_bound=final_violation_upper_bound,
            message=message,
        )

    selected_normal_scenarios = (
        list(instance.sets.loaded_normal_scenarios)
        if instance is not None
        else _selected_scenarios_fallback(run_config, "scenarios_a")
    )
    selected_disaster_scenarios = (
        list(instance.sets.loaded_disaster_scenarios)
        if instance is not None
        else _selected_scenarios_fallback(run_config, "scenarios_b")
    )

    log_payload = {
        "run_config": dict(run_config),
        "validation_level": summary.validation_level,
        "stop_reason": stop_reason,
        "solver_status": solver_status,
        "message": message,
        "selected_normal_scenarios": selected_normal_scenarios,
        "selected_disaster_scenarios": selected_disaster_scenarios,
        "summary": summary.to_csv_row(),
        "failure_record": None if failure_summary is None else failure_summary.to_csv_row(),
        "objective_components": objective_components,
        "plan_rows": plan_rows,
        "normal_cost_by_scenario": normal_cost_by_scenario,
        "artifact_paths": artifact_paths,
        "lower_bound_sequence": lower_bound_sequence,
        "cut_count_sequence": cut_count_sequence,
        "iteration_log": iteration_payload,
        "trial_certificate": trial_certificate_payload,
        "cut_pool_audit": cut_pool_audit_rows,
        "metadata": {} if instance is None else dict(instance.metadata),
        "exception": exception_payload,
    }
    log_path = write_json(logs_dir / f"{run_id}_run.json", log_payload)

    return {
        "summary": summary,
        "failure_summary": failure_summary,
        "plan_path": None if plan_path is None else str(plan_path),
        "log_path": str(log_path),
        "artifact_paths": artifact_paths,
        "validation_level": summary.validation_level,
        "stop_reason": stop_reason,
        "solver_status": solver_status,
        "message": message,
        "lower_bound_sequence": lower_bound_sequence,
        "cut_count_sequence": cut_count_sequence,
    }


def rows_to_markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    """Render a compact markdown table."""

    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(column, "")) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, sep, *body])


def summarize_run_logs(logs_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Load all per-run JSON logs keyed by run id."""

    directory = Path(logs_dir)
    logs: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*_run.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        logs[str(payload["run_config"]["run_id"])] = payload
    return logs
