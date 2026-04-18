"""Production normal-operation block for one fixed sampled normal scenario."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from gurobipy import GRB, Model, quicksum

from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import RuntimeDataValidationError
from src.production.first_stage import (
    FirstStageBlock,
    FirstStageSolution,
    build_first_stage_model,
    extract_first_stage_solution,
)


EQ24_POWER_BASE_KW = 1000.0
EQ24_POWER_TO_PU_SCALE = 1.0 / EQ24_POWER_BASE_KW
EQ24_UNIT_ASSUMPTION = (
    "Eq. (24) uses feeder R/X in per-unit and power variables in kW/kvar, "
    "so the production row applies an implicit S_base = 1 MVA conversion."
)


@dataclass(frozen=True)
class NormalOperationBlock:
    """Built production normal-operation block for one fixed normal scenario."""

    instance: CanonicalInstance
    first_stage: FirstStageBlock
    scenario_id: int
    model: Model
    transport_cost_expression: object | None = None
    unmet_cost_expression: object | None = None
    substation_cost_expression: object | None = None
    total_normal_cost_expression: object | None = None
    eq24_power_base_kw: float = EQ24_POWER_BASE_KW
    eq24_power_to_pu_scale: float = EQ24_POWER_TO_PU_SCALE
    eq24_unit_assumption: str = EQ24_UNIT_ASSUMPTION
    charge_slow_vars: dict[tuple[int, int, int], object] = field(default_factory=dict)
    charge_fast_vars: dict[tuple[int, int, int], object] = field(default_factory=dict)
    unmet_slow_vars: dict[tuple[int, int], object] = field(default_factory=dict)
    unmet_fast_vars: dict[tuple[int, int], object] = field(default_factory=dict)
    active_flow_vars: dict[tuple[int, str], object] = field(default_factory=dict)
    reactive_flow_vars: dict[tuple[int, str], object] = field(default_factory=dict)
    substation_active_vars: dict[int, object] = field(default_factory=dict)
    voltage_vars: dict[tuple[int, int], object] = field(default_factory=dict)
    charge_balance_slow_constraints: dict[tuple[int, int], object] = field(default_factory=dict)
    charge_balance_fast_constraints: dict[tuple[int, int], object] = field(default_factory=dict)
    station_capacity_slow_constraints: dict[tuple[int, int], object] = field(default_factory=dict)
    station_capacity_fast_constraints: dict[tuple[int, int], object] = field(default_factory=dict)
    linkage_slow_constraints: dict[tuple[int, int, int], object] = field(default_factory=dict)
    linkage_fast_constraints: dict[tuple[int, int, int], object] = field(default_factory=dict)
    active_balance_constraints: dict[tuple[int, str], object] = field(default_factory=dict)
    reactive_balance_constraints: dict[tuple[int, str], object] = field(default_factory=dict)
    substation_definition_constraints: dict[int, object] = field(default_factory=dict)
    active_upper_constraints: dict[tuple[int, str], object] = field(default_factory=dict)
    active_lower_constraints: dict[tuple[int, str], object] = field(default_factory=dict)
    reactive_upper_constraints: dict[tuple[int, str], object] = field(default_factory=dict)
    reactive_lower_constraints: dict[tuple[int, str], object] = field(default_factory=dict)
    voltage_drop_constraints: dict[tuple[int, str], object] = field(default_factory=dict)
    voltage_lower_constraints: dict[tuple[int, int], object] = field(default_factory=dict)
    voltage_upper_constraints: dict[tuple[int, int], object] = field(default_factory=dict)
    root_voltage_fix_constraints: dict[int, object] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalOperationSolution:
    """Structured solution for the production normal-operation block."""

    objective_value: float | None
    normal_objective_value: float
    model_status: str
    raw_status_code: int
    transport_cost_value: float
    unmet_cost_value: float
    substation_cost_value: float
    charge_slow_by_time_region_bus: dict[tuple[int, int, int], float]
    charge_fast_by_time_region_bus: dict[tuple[int, int, int], float]
    unmet_slow_by_time_region: dict[tuple[int, int], float]
    unmet_fast_by_time_region: dict[tuple[int, int], float]
    active_flow_by_time_line: dict[tuple[int, str], float]
    reactive_flow_by_time_line: dict[tuple[int, str], float]
    substation_active_by_time: dict[int, float]
    voltage_by_time_bus: dict[tuple[int, int], float]


def _scenario_is_loaded(instance: CanonicalInstance, scenario_id: int) -> None:
    if scenario_id not in set(instance.sets.loaded_normal_scenarios):
        raise RuntimeDataValidationError(
            f"Normal scenario {scenario_id} is not part of the loaded canonical selection "
            f"{instance.sets.loaded_normal_scenarios}."
        )


def _get_time_vector_value(
    values: tuple[float, ...],
    *,
    time_id: int,
    positions: Mapping[int, int],
    label: str,
) -> float:
    if len(values) != len(positions):
        raise RuntimeDataValidationError(
            f"{label} length mismatch: expected {len(positions)}, got {len(values)}."
        )
    return float(values[positions[time_id]])


def _get_voltage_limits(instance: CanonicalInstance) -> tuple[float, float]:
    net_raw = instance.runtime_parameters.get("net")
    if not isinstance(net_raw, Mapping):
        raise RuntimeDataValidationError(
            "Canonical runtime parameters are missing the `net` section required for voltage bounds."
        )
    try:
        vmin = float(net_raw["Vmin"])
        vmax = float(net_raw["Vmax"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeDataValidationError(
            "Canonical runtime parameters are missing valid `net.Vmin` / `net.Vmax` values."
        ) from exc
    return float(vmin**2), float(vmax**2)


def build_normal_operation_block(
    instance: CanonicalInstance,
    *,
    first_stage: FirstStageBlock,
    scenario_id: int,
    model: Model | None = None,
    model_name: str = "normal_operation",
    log_to_console: bool = False,
    attach_objective: bool = True,
) -> NormalOperationBlock:
    """Build the production normal-operation block for Eq. (13)-(25)."""

    _scenario_is_loaded(instance, scenario_id)
    working_model = model or first_stage.model
    if working_model is not first_stage.model:
        raise RuntimeDataValidationError(
            "The normal-operation block must be attached to the first-stage model instance."
        )
    working_model.Params.OutputFlag = 1 if log_to_console else 0
    if working_model.ModelName == "":
        working_model.ModelName = model_name

    buses = instance.sets.buses
    regions = instance.sets.regions
    normal_times = instance.sets.normal_times
    line_ids = instance.sets.line_ids
    topology = instance.network_topology
    root_bus = instance.frozen_config.root_bus
    line_by_id = {line.line_id: line for line in instance.lines}
    vmin_sq, vmax_sq = _get_voltage_limits(instance)
    power_to_voltage_drop_scale = EQ24_POWER_TO_PU_SCALE

    charge_slow_vars = {
        (time_id, region, bus): working_model.addVar(
            lb=0.0,
            name=f"ych_sl_t{time_id}_o{region}_n{bus}",
        )
        for time_id in normal_times
        for region in regions
        for bus in buses
    }
    charge_fast_vars = {
        (time_id, region, bus): working_model.addVar(
            lb=0.0,
            name=f"ych_fa_t{time_id}_o{region}_n{bus}",
        )
        for time_id in normal_times
        for region in regions
        for bus in buses
    }
    unmet_slow_vars = {
        (time_id, region): working_model.addVar(
            lb=0.0,
            name=f"u_sl_t{time_id}_o{region}",
        )
        for time_id in normal_times
        for region in regions
    }
    unmet_fast_vars = {
        (time_id, region): working_model.addVar(
            lb=0.0,
            name=f"u_fa_t{time_id}_o{region}",
        )
        for time_id in normal_times
        for region in regions
    }
    active_flow_vars = {
        (time_id, line_id): working_model.addVar(
            lb=-GRB.INFINITY,
            name=f"p_t{time_id}_{line_id}",
        )
        for time_id in normal_times
        for line_id in line_ids
    }
    reactive_flow_vars = {
        (time_id, line_id): working_model.addVar(
            lb=-GRB.INFINITY,
            name=f"q_t{time_id}_{line_id}",
        )
        for time_id in normal_times
        for line_id in line_ids
    }
    substation_active_vars = {
        time_id: working_model.addVar(
            lb=0.0,
            name=f"psub_t{time_id}",
        )
        for time_id in normal_times
    }
    voltage_vars = {
        (time_id, bus): working_model.addVar(
            lb=-GRB.INFINITY,
            name=f"v_t{time_id}_n{bus}",
        )
        for time_id in normal_times
        for bus in buses
    }

    transport_scale = 365.0 if instance.economics.annualize_normal_cost_by_365 else 1.0
    transport_cost_expression = transport_scale * quicksum(
        _get_time_vector_value(
            instance.economics.ctrans,
            time_id=time_id,
            positions=instance.index_map.normal_time_to_index,
            label="economics.ctrans",
        )
        * instance.ev.distance_km[instance.index_map.region_to_index[region]][
            instance.index_map.bus_to_index[bus]
        ]
        * (
            charge_slow_vars[(time_id, region, bus)] / instance.ev.p_ev_rated_sl
            + charge_fast_vars[(time_id, region, bus)] / instance.ev.p_ev_rated_fa
        )
        for time_id in normal_times
        for region in regions
        for bus in buses
    )
    unmet_cost_expression = transport_scale * instance.economics.cunmet * quicksum(
        unmet_slow_vars[(time_id, region)] + unmet_fast_vars[(time_id, region)]
        for time_id in normal_times
        for region in regions
    )
    substation_cost_expression = transport_scale * quicksum(
        _get_time_vector_value(
            instance.economics.cpur,
            time_id=time_id,
            positions=instance.index_map.normal_time_to_index,
            label="economics.cpur",
        )
        * substation_active_vars[time_id]
        for time_id in normal_times
    )
    total_normal_cost_expression = (
        transport_cost_expression + unmet_cost_expression + substation_cost_expression
    )
    if attach_objective:
        working_model.setObjective(
            working_model.getObjective() + total_normal_cost_expression,
            sense=GRB.MINIMIZE,
        )

    charge_balance_slow_constraints: dict[tuple[int, int], object] = {}
    charge_balance_fast_constraints: dict[tuple[int, int], object] = {}
    station_capacity_slow_constraints: dict[tuple[int, int], object] = {}
    station_capacity_fast_constraints: dict[tuple[int, int], object] = {}
    linkage_slow_constraints: dict[tuple[int, int, int], object] = {}
    linkage_fast_constraints: dict[tuple[int, int, int], object] = {}
    active_balance_constraints: dict[tuple[int, str], object] = {}
    reactive_balance_constraints: dict[tuple[int, str], object] = {}
    substation_definition_constraints: dict[int, object] = {}
    active_upper_constraints: dict[tuple[int, str], object] = {}
    active_lower_constraints: dict[tuple[int, str], object] = {}
    reactive_upper_constraints: dict[tuple[int, str], object] = {}
    reactive_lower_constraints: dict[tuple[int, str], object] = {}
    voltage_drop_constraints: dict[tuple[int, str], object] = {}
    voltage_lower_constraints: dict[tuple[int, int], object] = {}
    voltage_upper_constraints: dict[tuple[int, int], object] = {}
    root_voltage_fix_constraints: dict[int, object] = {}

    for time_id in normal_times:
        root_charge_expression = quicksum(
            charge_slow_vars[(time_id, region, root_bus)] + charge_fast_vars[(time_id, region, root_bus)]
            for region in regions
        )
        root_child_line_ids = tuple(
            topology.line_by_child_bus[child_bus]
            for child_bus in topology.children_by_bus.get(root_bus, ())
        )
        substation_definition_constraints[time_id] = working_model.addConstr(
            substation_active_vars[time_id]
            - quicksum(active_flow_vars[(time_id, line_id)] for line_id in root_child_line_ids)
            - root_charge_expression
            == instance.normal_tensors.p_load[(scenario_id, time_id, root_bus)],
            name=f"eq22_substation_t{time_id}",
        )
        root_voltage_fix_constraints[time_id] = working_model.addConstr(
            voltage_vars[(time_id, root_bus)] == instance.frozen_config.network.v_ref_sq,
            name=f"root_voltage_fix_t{time_id}",
        )

        for region in regions:
            charge_balance_slow_constraints[(time_id, region)] = working_model.addConstr(
                quicksum(charge_slow_vars[(time_id, region, bus)] for bus in buses)
                + unmet_slow_vars[(time_id, region)]
                == instance.normal_tensors.dev_ch_sl[(scenario_id, time_id, region)],
                name=f"eq17_balance_slow_t{time_id}_o{region}",
            )
            charge_balance_fast_constraints[(time_id, region)] = working_model.addConstr(
                quicksum(charge_fast_vars[(time_id, region, bus)] for bus in buses)
                + unmet_fast_vars[(time_id, region)]
                == instance.normal_tensors.dev_ch_fa[(scenario_id, time_id, region)],
                name=f"eq17_balance_fast_t{time_id}_o{region}",
            )

        for bus in buses:
            station_capacity_slow_constraints[(time_id, bus)] = working_model.addConstr(
                quicksum(charge_slow_vars[(time_id, region, bus)] for region in regions)
                - instance.ev.p_ev_rated_sl * first_stage.n_sl_by_bus[bus]
                <= 0.0,
                name=f"eq18_station_capacity_slow_t{time_id}_n{bus}",
            )
            station_capacity_fast_constraints[(time_id, bus)] = working_model.addConstr(
                quicksum(charge_fast_vars[(time_id, region, bus)] for region in regions)
                - instance.ev.p_ev_rated_fa * first_stage.n_fa_by_bus[bus]
                <= 0.0,
                name=f"eq18_station_capacity_fast_t{time_id}_n{bus}",
            )
            for region in regions:
                linkage_slow_constraints[(time_id, region, bus)] = working_model.addConstr(
                    charge_slow_vars[(time_id, region, bus)]
                    - instance.normal_tensors.dev_ch_sl[(scenario_id, time_id, region)]
                    * first_stage.z_by_bus[bus]
                    <= 0.0,
                    name=f"eq19_link_slow_t{time_id}_o{region}_n{bus}",
                )
                linkage_fast_constraints[(time_id, region, bus)] = working_model.addConstr(
                    charge_fast_vars[(time_id, region, bus)]
                    - instance.normal_tensors.dev_ch_fa[(scenario_id, time_id, region)]
                    * first_stage.z_by_bus[bus]
                    <= 0.0,
                    name=f"eq19_link_fast_t{time_id}_o{region}_n{bus}",
                )
            voltage_lower_constraints[(time_id, bus)] = working_model.addConstr(
                voltage_vars[(time_id, bus)] >= vmin_sq,
                name=f"eq25_voltage_lower_t{time_id}_n{bus}",
            )
            voltage_upper_constraints[(time_id, bus)] = working_model.addConstr(
                voltage_vars[(time_id, bus)] <= vmax_sq,
                name=f"eq25_voltage_upper_t{time_id}_n{bus}",
            )

        for line in instance.lines:
            line_id = line.line_id
            bus = line.to_bus
            child_line_ids = tuple(
                topology.line_by_child_bus[child_bus]
                for child_bus in topology.children_by_bus.get(bus, ())
            )
            charge_expression = quicksum(
                charge_slow_vars[(time_id, region, bus)] + charge_fast_vars[(time_id, region, bus)]
                for region in regions
            )
            active_balance_constraints[(time_id, line_id)] = working_model.addConstr(
                active_flow_vars[(time_id, line_id)]
                - quicksum(active_flow_vars[(time_id, child_line_id)] for child_line_id in child_line_ids)
                - charge_expression
                == instance.normal_tensors.p_load[(scenario_id, time_id, bus)],
                name=f"eq20_active_balance_t{time_id}_{line_id}",
            )
            reactive_balance_constraints[(time_id, line_id)] = working_model.addConstr(
                reactive_flow_vars[(time_id, line_id)]
                - quicksum(reactive_flow_vars[(time_id, child_line_id)] for child_line_id in child_line_ids)
                == instance.normal_tensors.q_load[(scenario_id, time_id, bus)],
                name=f"eq21_reactive_balance_t{time_id}_{line_id}",
            )
            active_upper_constraints[(time_id, line_id)] = working_model.addConstr(
                active_flow_vars[(time_id, line_id)] <= line.p_max_kw,
                name=f"eq23_active_upper_t{time_id}_{line_id}",
            )
            active_lower_constraints[(time_id, line_id)] = working_model.addConstr(
                -active_flow_vars[(time_id, line_id)] <= line.p_max_kw,
                name=f"eq23_active_lower_t{time_id}_{line_id}",
            )
            reactive_upper_constraints[(time_id, line_id)] = working_model.addConstr(
                reactive_flow_vars[(time_id, line_id)] <= line.q_max_kvar,
                name=f"eq23_reactive_upper_t{time_id}_{line_id}",
            )
            reactive_lower_constraints[(time_id, line_id)] = working_model.addConstr(
                -reactive_flow_vars[(time_id, line_id)] <= line.q_max_kvar,
                name=f"eq23_reactive_lower_t{time_id}_{line_id}",
            )
            voltage_drop_constraints[(time_id, line_id)] = working_model.addConstr(
                voltage_vars[(time_id, line.to_bus)]
                - voltage_vars[(time_id, line.from_bus)]
                + 2.0
                * line.resistance_pu
                * power_to_voltage_drop_scale
                * active_flow_vars[(time_id, line_id)]
                + 2.0
                * line.reactance_pu
                * power_to_voltage_drop_scale
                * reactive_flow_vars[(time_id, line_id)]
                == 0.0,
                name=f"eq24_voltage_drop_t{time_id}_{line_id}",
            )

    working_model.update()
    return NormalOperationBlock(
        instance=instance,
        first_stage=first_stage,
        scenario_id=scenario_id,
        model=working_model,
        transport_cost_expression=transport_cost_expression,
        unmet_cost_expression=unmet_cost_expression,
        substation_cost_expression=substation_cost_expression,
        total_normal_cost_expression=total_normal_cost_expression,
        eq24_power_base_kw=EQ24_POWER_BASE_KW,
        eq24_power_to_pu_scale=power_to_voltage_drop_scale,
        eq24_unit_assumption=EQ24_UNIT_ASSUMPTION,
        charge_slow_vars=charge_slow_vars,
        charge_fast_vars=charge_fast_vars,
        unmet_slow_vars=unmet_slow_vars,
        unmet_fast_vars=unmet_fast_vars,
        active_flow_vars=active_flow_vars,
        reactive_flow_vars=reactive_flow_vars,
        substation_active_vars=substation_active_vars,
        voltage_vars=voltage_vars,
        charge_balance_slow_constraints=charge_balance_slow_constraints,
        charge_balance_fast_constraints=charge_balance_fast_constraints,
        station_capacity_slow_constraints=station_capacity_slow_constraints,
        station_capacity_fast_constraints=station_capacity_fast_constraints,
        linkage_slow_constraints=linkage_slow_constraints,
        linkage_fast_constraints=linkage_fast_constraints,
        active_balance_constraints=active_balance_constraints,
        reactive_balance_constraints=reactive_balance_constraints,
        substation_definition_constraints=substation_definition_constraints,
        active_upper_constraints=active_upper_constraints,
        active_lower_constraints=active_lower_constraints,
        reactive_upper_constraints=reactive_upper_constraints,
        reactive_lower_constraints=reactive_lower_constraints,
        voltage_drop_constraints=voltage_drop_constraints,
        voltage_lower_constraints=voltage_lower_constraints,
        voltage_upper_constraints=voltage_upper_constraints,
        root_voltage_fix_constraints=root_voltage_fix_constraints,
    )


def extract_normal_operation_solution(normal_block: NormalOperationBlock) -> NormalOperationSolution:
    """Extract a structured normal-operation solution from an optimized model."""

    model = normal_block.model
    status_code = int(model.Status)
    status_name = str(model.Status)
    if status_code == GRB.OPTIMAL:
        status_name = "OPTIMAL"
    elif status_code == GRB.INFEASIBLE:
        status_name = "INFEASIBLE"
    elif status_code == GRB.UNBOUNDED:
        status_name = "UNBOUNDED"

    if status_code != GRB.OPTIMAL:
        return NormalOperationSolution(
            objective_value=None,
            normal_objective_value=0.0,
            model_status=status_name,
            raw_status_code=status_code,
            transport_cost_value=0.0,
            unmet_cost_value=0.0,
            substation_cost_value=0.0,
            charge_slow_by_time_region_bus={key: 0.0 for key in normal_block.charge_slow_vars},
            charge_fast_by_time_region_bus={key: 0.0 for key in normal_block.charge_fast_vars},
            unmet_slow_by_time_region={key: 0.0 for key in normal_block.unmet_slow_vars},
            unmet_fast_by_time_region={key: 0.0 for key in normal_block.unmet_fast_vars},
            active_flow_by_time_line={key: 0.0 for key in normal_block.active_flow_vars},
            reactive_flow_by_time_line={key: 0.0 for key in normal_block.reactive_flow_vars},
            substation_active_by_time={key: 0.0 for key in normal_block.substation_active_vars},
            voltage_by_time_bus={key: 0.0 for key in normal_block.voltage_vars},
        )

    transport_cost_value = float(normal_block.transport_cost_expression.getValue())
    unmet_cost_value = float(normal_block.unmet_cost_expression.getValue())
    substation_cost_value = float(normal_block.substation_cost_expression.getValue())
    return NormalOperationSolution(
        objective_value=float(model.ObjVal),
        normal_objective_value=float(
            transport_cost_value + unmet_cost_value + substation_cost_value
        ),
        model_status=status_name,
        raw_status_code=status_code,
        transport_cost_value=transport_cost_value,
        unmet_cost_value=unmet_cost_value,
        substation_cost_value=substation_cost_value,
        charge_slow_by_time_region_bus={
            key: float(var.X) for key, var in normal_block.charge_slow_vars.items()
        },
        charge_fast_by_time_region_bus={
            key: float(var.X) for key, var in normal_block.charge_fast_vars.items()
        },
        unmet_slow_by_time_region={
            key: float(var.X) for key, var in normal_block.unmet_slow_vars.items()
        },
        unmet_fast_by_time_region={
            key: float(var.X) for key, var in normal_block.unmet_fast_vars.items()
        },
        active_flow_by_time_line={
            key: float(var.X) for key, var in normal_block.active_flow_vars.items()
        },
        reactive_flow_by_time_line={
            key: float(var.X) for key, var in normal_block.reactive_flow_vars.items()
        },
        substation_active_by_time={
            key: float(var.X) for key, var in normal_block.substation_active_vars.items()
        },
        voltage_by_time_bus={
            key: float(var.X) for key, var in normal_block.voltage_vars.items()
        },
    )


def solve_first_stage_with_normal_operation_block(
    instance: CanonicalInstance,
    *,
    scenario_id: int,
    model_name: str = "first_stage_with_normal_operation",
    log_to_console: bool = False,
) -> tuple[FirstStageBlock, FirstStageSolution, NormalOperationBlock, NormalOperationSolution]:
    """Build, solve, and extract a first-stage + one-scenario normal-operation model."""

    first_stage = build_first_stage_model(
        instance,
        model_name=model_name,
        log_to_console=log_to_console,
        attach_objective=True,
    )
    normal_block = build_normal_operation_block(
        instance,
        first_stage=first_stage,
        scenario_id=scenario_id,
        model_name=model_name,
        log_to_console=log_to_console,
        attach_objective=True,
    )
    normal_block.model.optimize()
    first_stage_solution = extract_first_stage_solution(first_stage)
    normal_solution = extract_normal_operation_solution(normal_block)
    if normal_solution.model_status != "OPTIMAL":
        raise ValueError(
            f"First-stage + normal-operation model did not reach OPTIMAL status: "
            f"{normal_solution.model_status} (code {normal_solution.raw_status_code})."
        )
    return first_stage, first_stage_solution, normal_block, normal_solution
