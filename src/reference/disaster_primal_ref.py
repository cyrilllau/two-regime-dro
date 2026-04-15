"""Auditable fixed-(x, delta, b) disaster-stage primal reference LP."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from gurobipy import GRB, Model, quicksum

from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import (
    RuntimeDataValidationError,
    build_criticality_maps,
    require_explicit_critical_buses,
)


@dataclass(frozen=True)
class FixedFirstStagePlan:
    """Fixed first-stage plan used by the disaster reference LP."""

    z_by_bus: dict[int, int]
    n_sl_by_bus: dict[int, int]
    n_fa_by_bus: dict[int, int]


@dataclass(frozen=True)
class FixedOutageVector:
    """Fixed outage realization aligned with canonical line ordering."""

    values: tuple[int, ...]
    by_line_id: dict[str, int]


@dataclass(frozen=True)
class DisasterPrimalReferenceModel:
    """Built disaster primal model plus aligned metadata for auditing."""

    instance: CanonicalInstance
    scenario_id: int
    plan: FixedFirstStagePlan
    outage: FixedOutageVector
    cls_by_bus: dict[int, float]
    model: Model
    load_shedding_vars: dict[tuple[int, int], object] = field(default_factory=dict)
    discharge_slow_vars: dict[tuple[int, int, int], object] = field(default_factory=dict)
    discharge_fast_vars: dict[tuple[int, int, int], object] = field(default_factory=dict)
    line_flow_vars: dict[tuple[int, str], object] = field(default_factory=dict)


@dataclass(frozen=True)
class DisasterPrimalSolution:
    """Structured solved result for the disaster primal reference LP."""

    objective_value: float | None
    model_status: str
    raw_status_code: int
    load_shedding_by_time_bus: dict[tuple[int, int], float]
    discharge_slow_by_time_region_bus: dict[tuple[int, int, int], float]
    discharge_fast_by_time_region_bus: dict[tuple[int, int, int], float]
    line_flow_by_time_line: dict[tuple[int, str], float]


def _as_nonnegative_int_map(
    raw: Mapping[int, int] | None,
    *,
    label: str,
    keys: tuple[int, ...],
) -> dict[int, int]:
    normalized = {key: 0 for key in keys}
    if raw is None:
        return normalized

    allowed = set(keys)
    invalid = sorted(key for key in raw if key not in allowed)
    if invalid:
        raise RuntimeDataValidationError(f"{label} contains invalid bus ids: {tuple(invalid)}.")

    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise RuntimeDataValidationError(
                f"{label}[{key}] must be an int, got {value!r}."
            )
        if value < 0:
            raise RuntimeDataValidationError(
                f"{label}[{key}] must be nonnegative, got {value}."
            )
        normalized[int(key)] = int(value)
    return normalized


def build_fixed_first_stage_plan(
    instance: CanonicalInstance,
    *,
    z_by_bus: Mapping[int, int] | None = None,
    n_sl_by_bus: Mapping[int, int] | None = None,
    n_fa_by_bus: Mapping[int, int] | None = None,
) -> FixedFirstStagePlan:
    """Normalize and validate a fixed first-stage plan."""

    buses = instance.sets.buses
    z_map = _as_nonnegative_int_map(z_by_bus, label="z_by_bus", keys=buses)
    n_sl_map = _as_nonnegative_int_map(n_sl_by_bus, label="n_sl_by_bus", keys=buses)
    n_fa_map = _as_nonnegative_int_map(n_fa_by_bus, label="n_fa_by_bus", keys=buses)
    candidate_by_bus = {node.bus_id: node.candidate_for_evcs for node in instance.nodes}

    for bus in buses:
        z_value = z_map[bus]
        if z_value not in (0, 1):
            raise RuntimeDataValidationError(
                f"z_by_bus[{bus}] must be binary in {{0,1}}, got {z_value}."
            )
        if not candidate_by_bus[bus] and (z_value > 0 or n_sl_map[bus] > 0 or n_fa_map[bus] > 0):
            raise RuntimeDataValidationError(
                f"Bus {bus} is not an EVCS candidate under the frozen contract."
            )
        if z_value == 0 and (n_sl_map[bus] > 0 or n_fa_map[bus] > 0):
            raise RuntimeDataValidationError(
                f"Bus {bus} has chargers installed even though z[{bus}] = 0."
            )

    return FixedFirstStagePlan(
        z_by_bus=z_map,
        n_sl_by_bus=n_sl_map,
        n_fa_by_bus=n_fa_map,
    )


def build_fixed_outage_vector(
    instance: CanonicalInstance,
    *,
    by_line_id: Mapping[str, int] | None = None,
) -> FixedOutageVector:
    """Normalize and validate a fixed outage vector."""

    line_ids = instance.sets.line_ids
    normalized = {line_id: 0 for line_id in line_ids}
    if by_line_id is not None:
        invalid = sorted(line_id for line_id in by_line_id if line_id not in normalized)
        if invalid:
            raise RuntimeDataValidationError(
                f"Outage vector contains invalid line ids: {tuple(invalid)}."
            )
        for line_id, value in by_line_id.items():
            if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1):
                raise RuntimeDataValidationError(
                    f"Outage state for {line_id} must be binary in {{0,1}}, got {value!r}."
                )
            normalized[line_id] = int(value)

    return FixedOutageVector(
        values=tuple(normalized[line_id] for line_id in line_ids),
        by_line_id=normalized,
    )


def _resolve_cls_by_bus(instance: CanonicalInstance) -> dict[int, float]:
    require_explicit_critical_buses(
        buses=instance.sets.buses,
        critical_buses=instance.critical_buses,
        legacy_w=instance.ambiguity.legacy_w,
    )
    if instance.cls_by_bus is not None:
        return dict(instance.cls_by_bus)

    _, cls_by_bus = build_criticality_maps(
        buses=instance.sets.buses,
        critical_buses=instance.critical_buses,
        cls_critical=instance.frozen_config.disaster_objective.cls_critical,
        cls_noncritical=instance.frozen_config.disaster_objective.cls_noncritical,
    )
    if cls_by_bus is None:
        raise RuntimeDataValidationError(
            "critical_buses is required for disaster-objective construction."
        )
    return cls_by_bus


def _validate_selected_disaster_scenario(
    instance: CanonicalInstance,
    scenario_id: int,
) -> None:
    if scenario_id not in set(instance.sets.loaded_disaster_scenarios):
        raise RuntimeDataValidationError(
            f"Disaster scenario {scenario_id} is not part of the loaded canonical selection "
            f"{instance.sets.loaded_disaster_scenarios}."
        )


def build_disaster_primal_reference_model(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlan,
    outage: FixedOutageVector,
    scenario_id: int,
    model_name: str = "disaster_primal_reference",
    log_to_console: bool = False,
) -> DisasterPrimalReferenceModel:
    """Build the fixed-(x, delta, b) disaster-stage primal LP for Eq. (26)-(32)."""

    _validate_selected_disaster_scenario(instance, scenario_id)
    cls_by_bus = _resolve_cls_by_bus(instance)
    if len(outage.values) != len(instance.sets.line_ids):
        raise RuntimeDataValidationError(
            "Outage vector length does not match the canonical line set."
        )

    buses = instance.sets.buses
    regions = instance.sets.regions
    disaster_times = instance.sets.disaster_times
    line_ids = instance.sets.line_ids
    topology = instance.network_topology
    line_by_id = {line.line_id: line for line in instance.lines}

    model = Model(model_name)
    model.Params.OutputFlag = 1 if log_to_console else 0

    load_shedding_vars = {
        (ts, bus): model.addVar(
            lb=0.0,
            name=f"yls_eq31_t{ts}_n{bus}",
        )
        for ts in disaster_times
        for bus in buses
    }
    discharge_slow_vars = {
        (ts, region, bus): model.addVar(
            lb=0.0,
            name=f"ydis_sl_eq28_eq30_t{ts}_o{region}_n{bus}",
        )
        for ts in disaster_times
        for region in regions
        for bus in buses
    }
    discharge_fast_vars = {
        (ts, region, bus): model.addVar(
            lb=0.0,
            name=f"ydis_fa_eq28_eq30_t{ts}_o{region}_n{bus}",
        )
        for ts in disaster_times
        for region in regions
        for bus in buses
    }
    line_flow_vars = {
        (ts, line_id): model.addVar(
            lb=-GRB.INFINITY,
            name=f"pdis_eq27_eq32_t{ts}_{line_id}",
        )
        for ts in disaster_times
        for line_id in line_ids
    }

    model.setObjective(
        quicksum(
            cls_by_bus[bus] * load_shedding_vars[(ts, bus)]
            for ts in disaster_times
            for bus in buses
        ),
        sense=GRB.MINIMIZE,
    )

    for ts in disaster_times:
        for line in instance.lines:
            bus = line.to_bus
            child_line_ids = tuple(
                topology.line_by_child_bus[child]
                for child in topology.children_by_bus.get(bus, ())
            )
            discharge_total = quicksum(
                discharge_slow_vars[(ts, region, bus)] + discharge_fast_vars[(ts, region, bus)]
                for region in regions
            )
            model.addConstr(
                line_flow_vars[(ts, line.line_id)]
                == quicksum(line_flow_vars[(ts, child_line_id)] for child_line_id in child_line_ids)
                + instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
                - load_shedding_vars[(ts, bus)]
                - discharge_total,
                name=f"eq27_active_balance_t{ts}_{line.line_id}",
            )

    for ts in disaster_times:
        for region in regions:
            model.addConstr(
                quicksum(discharge_slow_vars[(ts, region, bus)] for bus in buses)
                <= instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)],
                name=f"eq28_discharge_slow_t{ts}_o{region}",
            )
            model.addConstr(
                quicksum(discharge_fast_vars[(ts, region, bus)] for bus in buses)
                <= instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)],
                name=f"eq28_discharge_fast_t{ts}_o{region}",
            )

    for ts in disaster_times:
        for bus in buses:
            model.addConstr(
                quicksum(discharge_slow_vars[(ts, region, bus)] for region in regions)
                <= plan.n_sl_by_bus[bus] * instance.ev.p_ev_rated_sl,
                name=f"eq29_station_slow_capacity_t{ts}_n{bus}",
            )
            model.addConstr(
                quicksum(discharge_fast_vars[(ts, region, bus)] for region in regions)
                <= plan.n_fa_by_bus[bus] * instance.ev.p_ev_rated_fa,
                name=f"eq29_station_fast_capacity_t{ts}_n{bus}",
            )

    for ts in disaster_times:
        for region in regions:
            available_slow = instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)]
            available_fast = instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]
            for bus in buses:
                model.addConstr(
                    discharge_slow_vars[(ts, region, bus)]
                    <= available_slow * plan.z_by_bus[bus],
                    name=f"eq30_link_slow_t{ts}_o{region}_n{bus}",
                )
                model.addConstr(
                    discharge_fast_vars[(ts, region, bus)]
                    <= available_fast * plan.z_by_bus[bus],
                    name=f"eq30_link_fast_t{ts}_o{region}_n{bus}",
                )

    for ts in disaster_times:
        for bus in buses:
            load = instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
            model.addConstr(
                load_shedding_vars[(ts, bus)] <= load,
                name=f"eq31_shed_upper_t{ts}_n{bus}",
            )

    for ts in disaster_times:
        for line_id in line_ids:
            available_capacity = line_by_id[line_id].p_max_kw * (1 - outage.by_line_id[line_id])
            model.addConstr(
                line_flow_vars[(ts, line_id)] <= available_capacity,
                name=f"eq32_line_upper_t{ts}_{line_id}",
            )
            model.addConstr(
                line_flow_vars[(ts, line_id)] >= -available_capacity,
                name=f"eq32_line_lower_t{ts}_{line_id}",
            )

    model.update()
    return DisasterPrimalReferenceModel(
        instance=instance,
        scenario_id=scenario_id,
        plan=plan,
        outage=outage,
        cls_by_bus=cls_by_bus,
        model=model,
        load_shedding_vars=load_shedding_vars,
        discharge_slow_vars=discharge_slow_vars,
        discharge_fast_vars=discharge_fast_vars,
        line_flow_vars=line_flow_vars,
    )


def extract_disaster_primal_solution(
    reference_model: DisasterPrimalReferenceModel,
) -> DisasterPrimalSolution:
    """Extract a structured solution from an optimized Gurobi model."""

    model = reference_model.model
    status_code = int(model.Status)
    status_name = str(model.Status)
    if status_code == GRB.OPTIMAL:
        status_name = "OPTIMAL"
    elif status_code == GRB.INFEASIBLE:
        status_name = "INFEASIBLE"
    elif status_code == GRB.UNBOUNDED:
        status_name = "UNBOUNDED"

    objective_value = float(model.ObjVal) if status_code == GRB.OPTIMAL else None
    return DisasterPrimalSolution(
        objective_value=objective_value,
        model_status=status_name,
        raw_status_code=status_code,
        load_shedding_by_time_bus={
            key: float(var.X)
            for key, var in reference_model.load_shedding_vars.items()
        },
        discharge_slow_by_time_region_bus={
            key: float(var.X)
            for key, var in reference_model.discharge_slow_vars.items()
        },
        discharge_fast_by_time_region_bus={
            key: float(var.X)
            for key, var in reference_model.discharge_fast_vars.items()
        },
        line_flow_by_time_line={
            key: float(var.X)
            for key, var in reference_model.line_flow_vars.items()
        },
    )


def solve_disaster_primal_reference(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlan,
    outage: FixedOutageVector,
    scenario_id: int,
    model_name: str = "disaster_primal_reference",
    log_to_console: bool = False,
) -> tuple[DisasterPrimalReferenceModel, DisasterPrimalSolution]:
    """Build, solve, and extract the fixed-(x, delta, b) disaster primal LP."""

    reference_model = build_disaster_primal_reference_model(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name=model_name,
        log_to_console=log_to_console,
    )
    reference_model.model.optimize()
    solution = extract_disaster_primal_solution(reference_model)
    if solution.model_status != "OPTIMAL":
        raise RuntimeDataValidationError(
            f"Disaster primal reference solve did not reach OPTIMAL status: "
            f"{solution.model_status} (code {solution.raw_status_code})."
        )
    return reference_model, solution
