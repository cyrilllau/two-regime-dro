"""Production first-stage EVCS siting and sizing block for Eq. (10)-(12)."""

from __future__ import annotations

from dataclasses import dataclass, field

from gurobipy import GRB, Model, quicksum

from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import RuntimeDataValidationError


@dataclass(frozen=True)
class FirstStageBlock:
    """Built production first-stage block with stable bus ordering."""

    instance: CanonicalInstance
    model: Model
    ordered_buses: tuple[int, ...]
    z_by_bus: dict[int, object] = field(default_factory=dict)
    n_sl_by_bus: dict[int, object] = field(default_factory=dict)
    n_fa_by_bus: dict[int, object] = field(default_factory=dict)
    n_sl_extra_by_bus: dict[int, object] = field(default_factory=dict)
    annualization_factor: float = 0.0
    construction_cost_expression: object | None = None
    min_charger_constraints: dict[int, object] = field(default_factory=dict)
    slow_bound_constraints: dict[int, object] = field(default_factory=dict)
    fast_bound_constraints: dict[int, object] = field(default_factory=dict)
    minimum_slow_policy_constraints: dict[int, object] = field(default_factory=dict)
    no_fast_policy_constraints: dict[int, object] = field(default_factory=dict)
    slow_extra_lower_constraints: dict[int, object] = field(default_factory=dict)
    slow_extra_upper_constraints: dict[int, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FirstStageSolution:
    """Structured solution for the production first-stage block.

    `objective_value` is the optimized objective of the attached model.
    Downstream code that needs the pure first-stage cost must read
    `construction_cost_value`, and can use `objective_is_pure_construction`
    as a guard.
    """

    objective_value: float | None
    objective_is_pure_construction: bool
    model_status: str
    raw_status_code: int
    z_by_bus: dict[int, int]
    n_sl_by_bus: dict[int, int]
    n_fa_by_bus: dict[int, int]
    n_sl_extra_by_bus: dict[int, int]
    construction_cost_value: float


def _objective_is_pure_construction(first_stage_block: FirstStageBlock) -> bool:
    """Return whether the attached model objective contains only first-stage terms."""

    model = first_stage_block.model
    model.update()
    first_stage_var_names = {
        *(var.VarName for var in first_stage_block.z_by_bus.values()),
        *(var.VarName for var in first_stage_block.n_sl_by_bus.values()),
        *(var.VarName for var in first_stage_block.n_fa_by_bus.values()),
        *(var.VarName for var in first_stage_block.n_sl_extra_by_bus.values()),
    }
    if abs(float(model.ObjCon)) > 1e-12:
        return False
    for var in model.getVars():
        if var.VarName not in first_stage_var_names and abs(float(var.Obj)) > 1e-12:
            return False
    return True


def _build_candidate_map(instance: CanonicalInstance) -> dict[int, bool]:
    candidate_by_bus = {node.bus_id: bool(node.candidate_for_evcs) for node in instance.nodes}
    missing = tuple(bus for bus in instance.sets.buses if bus not in candidate_by_bus)
    if missing:
        raise RuntimeDataValidationError(
            f"Node metadata is missing candidate flags for buses: {missing}."
        )
    return candidate_by_bus


def _annualization_factor(instance: CanonicalInstance) -> float:
    gamma = float(instance.economics.gamma)
    theta = int(instance.economics.theta)
    if theta <= 0:
        raise RuntimeDataValidationError(
            f"economics.theta must be positive, got {theta}."
        )
    if abs(gamma) <= 1e-12:
        return float(1.0 / theta)
    numerator = gamma * (1.0 + gamma) ** theta
    denominator = (1.0 + gamma) ** theta - 1.0
    if abs(denominator) <= 1e-12:
        raise RuntimeDataValidationError(
            "Annualization factor denominator is numerically zero."
        )
    return float(numerator / denominator)


def _slow_capacity_bound(instance: CanonicalInstance, bus: int) -> int:
    return int(instance.ev.nbar_sl_by_bus.get(bus, instance.ev.nbar_sl))


def _fast_capacity_bound(instance: CanonicalInstance, bus: int) -> int:
    return int(instance.ev.nbar_fa_by_bus.get(bus, instance.ev.nbar_fa))


def _slow_block_threshold(instance: CanonicalInstance) -> int:
    return int(getattr(instance.ev, "slow_block_threshold", 0))


def _slow_extra_cost_increment(instance: CanonicalInstance) -> float:
    return float(instance.economics.ccons_sl) * (
        float(instance.economics.ccons_sl_extra_multiplier) - 1.0
    )


def _slow_block_cost_enabled(instance: CanonicalInstance) -> bool:
    return _slow_block_threshold(instance) > 0 and _slow_extra_cost_increment(instance) > 1e-12


def _minimum_slow_only_policy_active(instance: CanonicalInstance) -> bool:
    return str(instance.metadata.get("station_sizing_policy", "")) == "minimum_slow_only"


def build_first_stage_model(
    instance: CanonicalInstance,
    *,
    model: Model | None = None,
    model_name: str = "first_stage",
    log_to_console: bool = False,
    attach_objective: bool = True,
) -> FirstStageBlock:
    """Build the production first-stage block for Eq. (10)-(12)."""

    ordered_buses = instance.sets.buses
    candidate_by_bus = _build_candidate_map(instance)
    annualization_factor = _annualization_factor(instance)

    working_model = model or Model(model_name)
    working_model.Params.OutputFlag = 1 if log_to_console else 0

    z_by_bus = {
        bus: working_model.addVar(
            vtype=GRB.BINARY,
            lb=0.0,
            ub=1.0 if candidate_by_bus[bus] else 0.0,
            name=f"z_n{bus}",
        )
        for bus in ordered_buses
    }
    n_sl_by_bus = {
        bus: working_model.addVar(
            vtype=GRB.INTEGER,
            lb=0.0,
            name=f"n_sl_n{bus}",
        )
        for bus in ordered_buses
    }
    n_fa_by_bus = {
        bus: working_model.addVar(
            vtype=GRB.INTEGER,
            lb=0.0,
            name=f"n_fa_n{bus}",
        )
        for bus in ordered_buses
    }

    min_charger_constraints: dict[int, object] = {}
    slow_bound_constraints: dict[int, object] = {}
    fast_bound_constraints: dict[int, object] = {}
    minimum_slow_policy_constraints: dict[int, object] = {}
    no_fast_policy_constraints: dict[int, object] = {}
    slow_extra_lower_constraints: dict[int, object] = {}
    slow_extra_upper_constraints: dict[int, object] = {}
    minimum_slow_only_policy = _minimum_slow_only_policy_active(instance)
    for bus in ordered_buses:
        min_charger_constraints[bus] = working_model.addConstr(
            n_sl_by_bus[bus] + n_fa_by_bus[bus] - 3.0 * z_by_bus[bus] >= 0.0,
            name=f"eq11_min_chargers_n{bus}",
        )
        slow_bound_constraints[bus] = working_model.addConstr(
            n_sl_by_bus[bus] - _slow_capacity_bound(instance, bus) * z_by_bus[bus] <= 0.0,
            name=f"eq12_n_sl_ub_n{bus}",
        )
        fast_bound_constraints[bus] = working_model.addConstr(
            n_fa_by_bus[bus] - _fast_capacity_bound(instance, bus) * z_by_bus[bus] <= 0.0,
            name=f"eq12_n_fa_ub_n{bus}",
        )
        if minimum_slow_only_policy:
            minimum_slow_policy_constraints[bus] = working_model.addConstr(
                n_sl_by_bus[bus] - 3.0 * z_by_bus[bus] == 0.0,
                name=f"case3_minimum_slow_only_n{bus}",
            )
            no_fast_policy_constraints[bus] = working_model.addConstr(
                n_fa_by_bus[bus] == 0.0,
                name=f"case3_no_fast_n{bus}",
            )

    n_sl_extra_by_bus: dict[int, object] = {}
    if _slow_block_cost_enabled(instance):
        threshold = _slow_block_threshold(instance)
        for bus in ordered_buses:
            extra_var = working_model.addVar(
                vtype=GRB.INTEGER,
                lb=0.0,
                name=f"n_sl_extra_n{bus}",
            )
            n_sl_extra_by_bus[bus] = extra_var
            slow_extra_lower_constraints[bus] = working_model.addConstr(
                extra_var - n_sl_by_bus[bus] + threshold * z_by_bus[bus] >= 0.0,
                name=f"slow_block_extra_lb_n{bus}",
            )
            slow_extra_upper_constraints[bus] = working_model.addConstr(
                extra_var - max(0, _slow_capacity_bound(instance, bus) - threshold) * z_by_bus[bus]
                <= 0.0,
                name=f"slow_block_extra_ub_n{bus}",
            )

    construction_cost_expression = annualization_factor * quicksum(
        instance.economics.cfix * z_by_bus[bus]
        + instance.economics.ccons_sl * n_sl_by_bus[bus]
        + instance.economics.ccons_fa * n_fa_by_bus[bus]
        + _slow_extra_cost_increment(instance) * n_sl_extra_by_bus.get(bus, 0.0)
        for bus in ordered_buses
    )
    if attach_objective:
        working_model.setObjective(
            working_model.getObjective() + construction_cost_expression,
            sense=GRB.MINIMIZE,
        )

    working_model.update()
    return FirstStageBlock(
        instance=instance,
        model=working_model,
        ordered_buses=ordered_buses,
        z_by_bus=z_by_bus,
        n_sl_by_bus=n_sl_by_bus,
        n_fa_by_bus=n_fa_by_bus,
        n_sl_extra_by_bus=n_sl_extra_by_bus,
        annualization_factor=annualization_factor,
        construction_cost_expression=construction_cost_expression,
        min_charger_constraints=min_charger_constraints,
        slow_bound_constraints=slow_bound_constraints,
        fast_bound_constraints=fast_bound_constraints,
        minimum_slow_policy_constraints=minimum_slow_policy_constraints,
        no_fast_policy_constraints=no_fast_policy_constraints,
        slow_extra_lower_constraints=slow_extra_lower_constraints,
        slow_extra_upper_constraints=slow_extra_upper_constraints,
    )


def extract_first_stage_solution(first_stage_block: FirstStageBlock) -> FirstStageSolution:
    """Extract a structured first-stage solution from an optimized attached model."""

    model = first_stage_block.model
    status_code = int(model.Status)
    status_name = str(model.Status)
    objective_is_pure_construction = _objective_is_pure_construction(first_stage_block)
    if status_code == GRB.OPTIMAL:
        status_name = "OPTIMAL"
    elif status_code == GRB.TIME_LIMIT:
        status_name = "TIME_LIMIT"
    elif status_code == GRB.INFEASIBLE:
        status_name = "INFEASIBLE"
    elif status_code == GRB.UNBOUNDED:
        status_name = "UNBOUNDED"

    has_solution = bool(status_code == GRB.OPTIMAL or int(getattr(model, "SolCount", 0)) > 0)
    if not has_solution:
        return FirstStageSolution(
            objective_value=None,
            objective_is_pure_construction=objective_is_pure_construction,
            model_status=status_name,
            raw_status_code=status_code,
            z_by_bus={bus: 0 for bus in first_stage_block.ordered_buses},
            n_sl_by_bus={bus: 0 for bus in first_stage_block.ordered_buses},
            n_fa_by_bus={bus: 0 for bus in first_stage_block.ordered_buses},
            n_sl_extra_by_bus={bus: 0 for bus in first_stage_block.ordered_buses},
            construction_cost_value=0.0,
        )

    z_by_bus = {
        bus: int(round(float(var.X)))
        for bus, var in first_stage_block.z_by_bus.items()
    }
    n_sl_by_bus = {
        bus: int(round(float(var.X)))
        for bus, var in first_stage_block.n_sl_by_bus.items()
    }
    n_fa_by_bus = {
        bus: int(round(float(var.X)))
        for bus, var in first_stage_block.n_fa_by_bus.items()
    }
    n_sl_extra_by_bus = {
        bus: int(round(float(var.X)))
        for bus, var in first_stage_block.n_sl_extra_by_bus.items()
    }
    construction_cost_value = float(sum(
        first_stage_block.annualization_factor
        * (
            first_stage_block.instance.economics.cfix * z_by_bus[bus]
            + first_stage_block.instance.economics.ccons_sl * n_sl_by_bus[bus]
            + first_stage_block.instance.economics.ccons_fa * n_fa_by_bus[bus]
            + _slow_extra_cost_increment(first_stage_block.instance)
            * n_sl_extra_by_bus.get(bus, 0)
        )
        for bus in first_stage_block.ordered_buses
    ))
    return FirstStageSolution(
        objective_value=float(model.ObjVal),
        objective_is_pure_construction=objective_is_pure_construction,
        model_status=status_name,
        raw_status_code=status_code,
        z_by_bus=z_by_bus,
        n_sl_by_bus=n_sl_by_bus,
        n_fa_by_bus=n_fa_by_bus,
        n_sl_extra_by_bus=n_sl_extra_by_bus,
        construction_cost_value=construction_cost_value,
    )


def solve_first_stage_model(
    instance: CanonicalInstance,
    *,
    model_name: str = "first_stage",
    log_to_console: bool = False,
) -> tuple[FirstStageBlock, FirstStageSolution]:
    """Build, solve, and extract the standalone production first-stage block."""

    first_stage_block = build_first_stage_model(
        instance,
        model_name=model_name,
        log_to_console=log_to_console,
        attach_objective=True,
    )
    first_stage_block.model.optimize()
    solution = extract_first_stage_solution(first_stage_block)
    if solution.model_status != "OPTIMAL":
        raise ValueError(
            f"First-stage model did not reach OPTIMAL status: "
            f"{solution.model_status} (code {solution.raw_status_code})."
        )
    return first_stage_block, solution
