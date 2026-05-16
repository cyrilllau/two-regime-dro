"""Hand-coded paper dual for the fixed-(x, delta, b) disaster recourse LP."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

from gurobipy import GRB, Model, quicksum

from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import (
    RuntimeDataValidationError,
    build_criticality_maps,
    require_explicit_critical_buses,
)


class FixedFirstStagePlanLike(Protocol):
    """Minimal fixed-plan interface required by the paper dual."""

    z_by_bus: Mapping[int, int]
    n_sl_by_bus: Mapping[int, int]
    n_fa_by_bus: Mapping[int, int]


class FixedOutageVectorLike(Protocol):
    """Minimal fixed-outage interface required by the paper dual."""

    values: Sequence[int]
    by_line_id: Mapping[str, int]


@dataclass(frozen=True)
class SamplewisePaperDualDecomposition:
    """Samplewise `beta_b / gamma_b / phi_b` decomposition for a fixed disaster sample."""

    beta_b: float
    gamma_z_by_bus: dict[int, float] = field(default_factory=dict)
    gamma_n_sl_by_bus: dict[int, float] = field(default_factory=dict)
    gamma_n_fa_by_bus: dict[int, float] = field(default_factory=dict)
    phi_by_line_id: dict[str, float] = field(default_factory=dict)

    def gamma_by_component(self) -> dict[str, float]:
        """Return a flattened `gamma_b` mapping keyed by first-stage component names."""

        flattened: dict[str, float] = {}
        for bus, value in self.gamma_z_by_bus.items():
            flattened[f"z[{bus}]"] = float(value)
        for bus, value in self.gamma_n_sl_by_bus.items():
            flattened[f"n_sl[{bus}]"] = float(value)
        for bus, value in self.gamma_n_fa_by_bus.items():
            flattened[f"n_fa[{bus}]"] = float(value)
        return flattened

    def evaluate(
        self,
        *,
        plan: FixedFirstStagePlanLike,
        outage: FixedOutageVectorLike,
    ) -> float:
        """Evaluate `beta_b - gamma_b^T x + phi_b^T delta` for fixed inputs."""

        total = float(self.beta_b)
        for bus, coefficient in self.gamma_z_by_bus.items():
            total -= float(coefficient) * float(plan.z_by_bus[bus])
        for bus, coefficient in self.gamma_n_sl_by_bus.items():
            total -= float(coefficient) * float(plan.n_sl_by_bus[bus])
        for bus, coefficient in self.gamma_n_fa_by_bus.items():
            total -= float(coefficient) * float(plan.n_fa_by_bus[bus])
        for line_id, coefficient in self.phi_by_line_id.items():
            total += float(coefficient) * float(outage.by_line_id[line_id])
        return float(total)


@dataclass(frozen=True)
class DisasterPaperDualModel:
    """Built hand-coded paper dual plus grouped metadata."""

    instance: CanonicalInstance
    scenario_id: int
    plan: FixedFirstStagePlanLike
    outage: FixedOutageVectorLike
    cls_by_bus: dict[int, float]
    model: Model
    eq27_lambda_vars: dict[tuple[int, str], object] = field(default_factory=dict)
    eq28_slow_vars: dict[tuple[int, int], object] = field(default_factory=dict)
    eq28_fast_vars: dict[tuple[int, int], object] = field(default_factory=dict)
    eq29_slow_vars: dict[tuple[int, int], object] = field(default_factory=dict)
    eq29_fast_vars: dict[tuple[int, int], object] = field(default_factory=dict)
    eq30_slow_vars: dict[tuple[int, int, int], object] = field(default_factory=dict)
    eq30_fast_vars: dict[tuple[int, int, int], object] = field(default_factory=dict)
    eq31_sigma_vars: dict[tuple[int, int], object] = field(default_factory=dict)
    eq32_upper_vars: dict[tuple[int, str], object] = field(default_factory=dict)
    eq32_lower_vars: dict[tuple[int, str], object] = field(default_factory=dict)
    load_shedding_dual_constraints: dict[tuple[int, int], object] = field(default_factory=dict)
    discharge_slow_dual_constraints: dict[tuple[int, int, int], object] = field(default_factory=dict)
    discharge_fast_dual_constraints: dict[tuple[int, int, int], object] = field(default_factory=dict)
    line_flow_dual_constraints: dict[tuple[int, str], object] = field(default_factory=dict)


@dataclass(frozen=True)
class DisasterPaperDualSolution:
    """Structured solved result for the hand-coded paper dual."""

    objective_value: float | None
    model_status: str
    raw_status_code: int
    eq27_lambda_values: dict[tuple[int, str], float]
    eq28_slow_values: dict[tuple[int, int], float]
    eq28_fast_values: dict[tuple[int, int], float]
    eq29_slow_values: dict[tuple[int, int], float]
    eq29_fast_values: dict[tuple[int, int], float]
    eq30_slow_values: dict[tuple[int, int, int], float]
    eq30_fast_values: dict[tuple[int, int, int], float]
    eq31_sigma_values: dict[tuple[int, int], float]
    eq32_upper_values: dict[tuple[int, str], float]
    eq32_lower_values: dict[tuple[int, str], float]
    samplewise_decomposition: SamplewisePaperDualDecomposition


def _coerce_nonnegative_int_map(
    raw: Mapping[int, int],
    *,
    label: str,
    keys: Sequence[int],
    binary: bool = False,
    allow_fractional: bool = False,
) -> dict[int, int]:
    normalized: dict[int, int | float] = {}
    key_set = set(keys)
    invalid = sorted(key for key in raw if key not in key_set)
    if invalid:
        raise RuntimeDataValidationError(f"{label} contains invalid ids: {tuple(invalid)}.")

    for key in keys:
        if key not in raw:
            raise RuntimeDataValidationError(f"{label} is missing required id {key}.")
        value = raw[key]
        if isinstance(value, bool):
            raise RuntimeDataValidationError(f"{label}[{key}] must be numeric, got {value!r}.")
        if allow_fractional:
            if not isinstance(value, (int, float)):
                raise RuntimeDataValidationError(
                    f"{label}[{key}] must be numeric, got {value!r}."
                )
            numeric = float(value)
            if numeric < -1e-8:
                raise RuntimeDataValidationError(
                    f"{label}[{key}] must be nonnegative, got {value}."
                )
            if binary and numeric > 1.0 + 1e-8:
                raise RuntimeDataValidationError(
                    f"{label}[{key}] must be <= 1 for fractional binary relaxation, "
                    f"got {value}."
                )
            normalized[int(key)] = max(0.0, min(1.0, numeric) if binary else numeric)
            continue
        if not isinstance(value, int):
            raise RuntimeDataValidationError(f"{label}[{key}] must be an int, got {value!r}.")
        if value < 0:
            raise RuntimeDataValidationError(f"{label}[{key}] must be nonnegative, got {value}.")
        if binary and value not in (0, 1):
            raise RuntimeDataValidationError(
                f"{label}[{key}] must be binary in {{0,1}}, got {value}."
            )
        normalized[int(key)] = int(value)
    return normalized


def _resolve_plan_maps(
    instance: CanonicalInstance,
    plan: FixedFirstStagePlanLike,
    *,
    allow_fractional: bool = False,
) -> tuple[dict[int, int | float], dict[int, int | float], dict[int, int | float]]:
    buses = instance.sets.buses
    z_by_bus = _coerce_nonnegative_int_map(
        plan.z_by_bus,
        label="plan.z_by_bus",
        keys=buses,
        binary=True,
        allow_fractional=allow_fractional,
    )
    n_sl_by_bus = _coerce_nonnegative_int_map(
        plan.n_sl_by_bus,
        label="plan.n_sl_by_bus",
        keys=buses,
        allow_fractional=allow_fractional,
    )
    n_fa_by_bus = _coerce_nonnegative_int_map(
        plan.n_fa_by_bus,
        label="plan.n_fa_by_bus",
        keys=buses,
        allow_fractional=allow_fractional,
    )
    return z_by_bus, n_sl_by_bus, n_fa_by_bus


def _resolve_outage_map(
    instance: CanonicalInstance,
    outage: FixedOutageVectorLike,
) -> dict[str, int]:
    line_ids = instance.sets.line_ids
    if len(outage.values) != len(line_ids):
        raise RuntimeDataValidationError(
            "Outage vector length does not match the canonical line set."
        )
    line_set = set(line_ids)
    invalid = sorted(line_id for line_id in outage.by_line_id if line_id not in line_set)
    if invalid:
        raise RuntimeDataValidationError(
            f"outage.by_line_id contains invalid line ids: {tuple(invalid)}."
        )

    resolved: dict[str, int] = {}
    for line_id in line_ids:
        if line_id not in outage.by_line_id:
            raise RuntimeDataValidationError(
                f"outage.by_line_id is missing required line id {line_id}."
            )
        value = outage.by_line_id[line_id]
        if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1):
            raise RuntimeDataValidationError(
                f"outage.by_line_id[{line_id!r}] must be binary in {{0,1}}, got {value!r}."
            )
        resolved[line_id] = int(value)
    return resolved


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


def _parent_line_for_bus(instance: CanonicalInstance, bus: int) -> str | None:
    return instance.network_topology.line_by_child_bus.get(bus)


def _zero_decomposition(instance: CanonicalInstance) -> SamplewisePaperDualDecomposition:
    return SamplewisePaperDualDecomposition(
        beta_b=0.0,
        gamma_z_by_bus={bus: 0.0 for bus in instance.sets.buses},
        gamma_n_sl_by_bus={bus: 0.0 for bus in instance.sets.buses},
        gamma_n_fa_by_bus={bus: 0.0 for bus in instance.sets.buses},
        phi_by_line_id={line_id: 0.0 for line_id in instance.sets.line_ids},
    )


def build_samplewise_paper_dual_decomposition(
    paper_dual_model: DisasterPaperDualModel,
    solution: DisasterPaperDualSolution,
) -> SamplewisePaperDualDecomposition:
    """Recover the samplewise `beta_b / gamma_b / phi_b` terms from a solved paper dual."""

    instance = paper_dual_model.instance
    scenario_id = paper_dual_model.scenario_id
    buses = instance.sets.buses
    regions = instance.sets.regions
    disaster_times = instance.sets.disaster_times

    beta_b = 0.0
    for ts in disaster_times:
        for line in instance.lines:
            beta_b += (
                instance.disaster_tensors.p_load[(scenario_id, ts, line.to_bus)]
                * solution.eq27_lambda_values[(ts, line.line_id)]
            )
        for region in regions:
            beta_b -= (
                instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)]
                * solution.eq28_slow_values[(ts, region)]
            )
            beta_b -= (
                instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]
                * solution.eq28_fast_values[(ts, region)]
            )
        for bus in buses:
            beta_b -= (
                instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
                * solution.eq31_sigma_values[(ts, bus)]
            )
        for line in instance.lines:
            rho_total = (
                solution.eq32_upper_values[(ts, line.line_id)]
                + solution.eq32_lower_values[(ts, line.line_id)]
            )
            beta_b -= line.p_max_kw * rho_total

    gamma_z_by_bus = {bus: 0.0 for bus in buses}
    gamma_n_sl_by_bus = {bus: 0.0 for bus in buses}
    gamma_n_fa_by_bus = {bus: 0.0 for bus in buses}
    for ts in disaster_times:
        for bus in buses:
            gamma_n_sl_by_bus[bus] += (
                instance.ev.p_ev_rated_sl * solution.eq29_slow_values[(ts, bus)]
            )
            gamma_n_fa_by_bus[bus] += (
                instance.ev.p_ev_rated_fa * solution.eq29_fast_values[(ts, bus)]
            )
            for region in regions:
                gamma_z_by_bus[bus] += (
                    instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)]
                    * solution.eq30_slow_values[(ts, region, bus)]
                )
                gamma_z_by_bus[bus] += (
                    instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]
                    * solution.eq30_fast_values[(ts, region, bus)]
                )

    phi_by_line_id = {line_id: 0.0 for line_id in instance.sets.line_ids}
    for line in instance.lines:
        phi_by_line_id[line.line_id] = line.p_max_kw * sum(
            solution.eq32_upper_values[(ts, line.line_id)]
            + solution.eq32_lower_values[(ts, line.line_id)]
            for ts in disaster_times
        )

    return SamplewisePaperDualDecomposition(
        beta_b=float(beta_b),
        gamma_z_by_bus=gamma_z_by_bus,
        gamma_n_sl_by_bus=gamma_n_sl_by_bus,
        gamma_n_fa_by_bus=gamma_n_fa_by_bus,
        phi_by_line_id=phi_by_line_id,
    )


def build_disaster_dual_paper_model(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlanLike,
    outage: FixedOutageVectorLike,
    scenario_id: int,
    model_name: str = "disaster_dual_paper",
    log_to_console: bool = False,
    allow_fractional_plan: bool = False,
) -> DisasterPaperDualModel:
    """Build the hand-coded paper dual for a fixed `(x, delta, b)` disaster sample."""

    _validate_selected_disaster_scenario(instance, scenario_id)
    cls_by_bus = _resolve_cls_by_bus(instance)
    z_by_bus, n_sl_by_bus, n_fa_by_bus = _resolve_plan_maps(
        instance,
        plan,
        allow_fractional=allow_fractional_plan,
    )
    outage_by_line_id = _resolve_outage_map(instance, outage)

    buses = instance.sets.buses
    regions = instance.sets.regions
    disaster_times = instance.sets.disaster_times
    line_ids = instance.sets.line_ids
    line_by_id = {line.line_id: line for line in instance.lines}

    model = Model(model_name)
    model.Params.OutputFlag = 1 if log_to_console else 0

    eq27_lambda_vars = {
        (ts, line_id): model.addVar(
            lb=-GRB.INFINITY,
            name=f"lam_eq27_t{ts}_{line_id}",
        )
        for ts in disaster_times
        for line_id in line_ids
    }
    eq28_slow_vars = {
        (ts, region): model.addVar(
            lb=0.0,
            name=f"eta_eq28_slow_t{ts}_o{region}",
        )
        for ts in disaster_times
        for region in regions
    }
    eq28_fast_vars = {
        (ts, region): model.addVar(
            lb=0.0,
            name=f"eta_eq28_fast_t{ts}_o{region}",
        )
        for ts in disaster_times
        for region in regions
    }
    eq29_slow_vars = {
        (ts, bus): model.addVar(
            lb=0.0,
            name=f"mu_eq29_slow_t{ts}_n{bus}",
        )
        for ts in disaster_times
        for bus in buses
    }
    eq29_fast_vars = {
        (ts, bus): model.addVar(
            lb=0.0,
            name=f"mu_eq29_fast_t{ts}_n{bus}",
        )
        for ts in disaster_times
        for bus in buses
    }
    eq30_slow_vars = {
        (ts, region, bus): model.addVar(
            lb=0.0,
            name=f"nu_eq30_slow_t{ts}_o{region}_n{bus}",
        )
        for ts in disaster_times
        for region in regions
        for bus in buses
    }
    eq30_fast_vars = {
        (ts, region, bus): model.addVar(
            lb=0.0,
            name=f"nu_eq30_fast_t{ts}_o{region}_n{bus}",
        )
        for ts in disaster_times
        for region in regions
        for bus in buses
    }
    eq31_sigma_vars = {
        (ts, bus): model.addVar(
            lb=0.0,
            name=f"sigma_eq31_t{ts}_n{bus}",
        )
        for ts in disaster_times
        for bus in buses
    }
    eq32_upper_vars = {
        (ts, line_id): model.addVar(
            lb=0.0,
            name=f"rho_eq32_upper_t{ts}_{line_id}",
        )
        for ts in disaster_times
        for line_id in line_ids
    }
    eq32_lower_vars = {
        (ts, line_id): model.addVar(
            lb=0.0,
            name=f"rho_eq32_lower_t{ts}_{line_id}",
        )
        for ts in disaster_times
        for line_id in line_ids
    }

    model.setObjective(
        quicksum(
            instance.disaster_tensors.p_load[(scenario_id, ts, line.to_bus)]
            * eq27_lambda_vars[(ts, line.line_id)]
            for ts in disaster_times
            for line in instance.lines
        )
        - quicksum(
            instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)]
            * eq28_slow_vars[(ts, region)]
            for ts in disaster_times
            for region in regions
        )
        - quicksum(
            instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]
            * eq28_fast_vars[(ts, region)]
            for ts in disaster_times
            for region in regions
        )
        - quicksum(
            instance.ev.p_ev_rated_sl * n_sl_by_bus[bus] * eq29_slow_vars[(ts, bus)]
            for ts in disaster_times
            for bus in buses
        )
        - quicksum(
            instance.ev.p_ev_rated_fa * n_fa_by_bus[bus] * eq29_fast_vars[(ts, bus)]
            for ts in disaster_times
            for bus in buses
        )
        - quicksum(
            instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)]
            * z_by_bus[bus]
            * eq30_slow_vars[(ts, region, bus)]
            for ts in disaster_times
            for region in regions
            for bus in buses
        )
        - quicksum(
            instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]
            * z_by_bus[bus]
            * eq30_fast_vars[(ts, region, bus)]
            for ts in disaster_times
            for region in regions
            for bus in buses
        )
        - quicksum(
            instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
            * eq31_sigma_vars[(ts, bus)]
            for ts in disaster_times
            for bus in buses
        )
        - quicksum(
            line_by_id[line_id].p_max_kw
            * (1 - outage_by_line_id[line_id])
            * (eq32_upper_vars[(ts, line_id)] + eq32_lower_vars[(ts, line_id)])
            for ts in disaster_times
            for line_id in line_ids
        ),
        sense=GRB.MAXIMIZE,
    )

    load_shedding_dual_constraints = {}
    for ts in disaster_times:
        for bus in buses:
            parent_line_id = _parent_line_for_bus(instance, bus)
            lhs = -eq31_sigma_vars[(ts, bus)]
            if parent_line_id is not None:
                lhs += eq27_lambda_vars[(ts, parent_line_id)]
            load_shedding_dual_constraints[(ts, bus)] = model.addConstr(
                lhs <= cls_by_bus[bus],
                name=f"dual_yls_t{ts}_n{bus}",
            )

    discharge_slow_dual_constraints = {}
    discharge_fast_dual_constraints = {}
    for ts in disaster_times:
        for region in regions:
            for bus in buses:
                parent_line_id = _parent_line_for_bus(instance, bus)
                slow_lhs = (
                    -eq28_slow_vars[(ts, region)]
                    - eq29_slow_vars[(ts, bus)]
                    - eq30_slow_vars[(ts, region, bus)]
                )
                fast_lhs = (
                    -eq28_fast_vars[(ts, region)]
                    - eq29_fast_vars[(ts, bus)]
                    - eq30_fast_vars[(ts, region, bus)]
                )
                if parent_line_id is not None:
                    slow_lhs += eq27_lambda_vars[(ts, parent_line_id)]
                    fast_lhs += eq27_lambda_vars[(ts, parent_line_id)]
                discharge_slow_dual_constraints[(ts, region, bus)] = model.addConstr(
                    slow_lhs <= 0.0,
                    name=f"dual_ydis_slow_t{ts}_o{region}_n{bus}",
                )
                discharge_fast_dual_constraints[(ts, region, bus)] = model.addConstr(
                    fast_lhs <= 0.0,
                    name=f"dual_ydis_fast_t{ts}_o{region}_n{bus}",
                )

    line_flow_dual_constraints = {}
    for ts in disaster_times:
        for line_id in line_ids:
            parent_line_id = instance.network_topology.line_by_child_bus.get(
                line_by_id[line_id].from_bus
            )
            lhs = (
                eq27_lambda_vars[(ts, line_id)]
                - eq32_upper_vars[(ts, line_id)]
                + eq32_lower_vars[(ts, line_id)]
            )
            if parent_line_id is not None:
                lhs -= eq27_lambda_vars[(ts, parent_line_id)]
            line_flow_dual_constraints[(ts, line_id)] = model.addConstr(
                lhs == 0.0,
                name=f"dual_pdis_t{ts}_{line_id}",
            )

    model.update()
    return DisasterPaperDualModel(
        instance=instance,
        scenario_id=scenario_id,
        plan=plan,
        outage=outage,
        cls_by_bus=cls_by_bus,
        model=model,
        eq27_lambda_vars=eq27_lambda_vars,
        eq28_slow_vars=eq28_slow_vars,
        eq28_fast_vars=eq28_fast_vars,
        eq29_slow_vars=eq29_slow_vars,
        eq29_fast_vars=eq29_fast_vars,
        eq30_slow_vars=eq30_slow_vars,
        eq30_fast_vars=eq30_fast_vars,
        eq31_sigma_vars=eq31_sigma_vars,
        eq32_upper_vars=eq32_upper_vars,
        eq32_lower_vars=eq32_lower_vars,
        load_shedding_dual_constraints=load_shedding_dual_constraints,
        discharge_slow_dual_constraints=discharge_slow_dual_constraints,
        discharge_fast_dual_constraints=discharge_fast_dual_constraints,
        line_flow_dual_constraints=line_flow_dual_constraints,
    )


def extract_disaster_dual_paper_solution(
    paper_dual_model: DisasterPaperDualModel,
) -> DisasterPaperDualSolution:
    """Extract a structured solution from an optimized hand-coded paper dual."""

    model = paper_dual_model.model
    status_code = int(model.Status)
    status_name = str(model.Status)
    if status_code == GRB.OPTIMAL:
        status_name = "OPTIMAL"
    elif status_code == GRB.INFEASIBLE:
        status_name = "INFEASIBLE"
    elif status_code == GRB.UNBOUNDED:
        status_name = "UNBOUNDED"

    objective_value = float(model.ObjVal) if status_code == GRB.OPTIMAL else None
    provisional = DisasterPaperDualSolution(
        objective_value=objective_value,
        model_status=status_name,
        raw_status_code=status_code,
        eq27_lambda_values={
            key: float(var.X) for key, var in paper_dual_model.eq27_lambda_vars.items()
        },
        eq28_slow_values={
            key: float(var.X) for key, var in paper_dual_model.eq28_slow_vars.items()
        },
        eq28_fast_values={
            key: float(var.X) for key, var in paper_dual_model.eq28_fast_vars.items()
        },
        eq29_slow_values={
            key: float(var.X) for key, var in paper_dual_model.eq29_slow_vars.items()
        },
        eq29_fast_values={
            key: float(var.X) for key, var in paper_dual_model.eq29_fast_vars.items()
        },
        eq30_slow_values={
            key: float(var.X) for key, var in paper_dual_model.eq30_slow_vars.items()
        },
        eq30_fast_values={
            key: float(var.X) for key, var in paper_dual_model.eq30_fast_vars.items()
        },
        eq31_sigma_values={
            key: float(var.X) for key, var in paper_dual_model.eq31_sigma_vars.items()
        },
        eq32_upper_values={
            key: float(var.X) for key, var in paper_dual_model.eq32_upper_vars.items()
        },
        eq32_lower_values={
            key: float(var.X) for key, var in paper_dual_model.eq32_lower_vars.items()
        },
        samplewise_decomposition=_zero_decomposition(paper_dual_model.instance),
    )

    if status_code != GRB.OPTIMAL:
        return provisional

    decomposition = build_samplewise_paper_dual_decomposition(paper_dual_model, provisional)
    return DisasterPaperDualSolution(
        objective_value=objective_value,
        model_status=status_name,
        raw_status_code=status_code,
        eq27_lambda_values=provisional.eq27_lambda_values,
        eq28_slow_values=provisional.eq28_slow_values,
        eq28_fast_values=provisional.eq28_fast_values,
        eq29_slow_values=provisional.eq29_slow_values,
        eq29_fast_values=provisional.eq29_fast_values,
        eq30_slow_values=provisional.eq30_slow_values,
        eq30_fast_values=provisional.eq30_fast_values,
        eq31_sigma_values=provisional.eq31_sigma_values,
        eq32_upper_values=provisional.eq32_upper_values,
        eq32_lower_values=provisional.eq32_lower_values,
        samplewise_decomposition=decomposition,
    )


def solve_disaster_dual_paper(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlanLike,
    outage: FixedOutageVectorLike,
    scenario_id: int,
    model_name: str = "disaster_dual_paper",
    log_to_console: bool = False,
) -> tuple[DisasterPaperDualModel, DisasterPaperDualSolution]:
    """Build, solve, and extract the fixed-sample hand-coded paper dual."""

    paper_dual_model = build_disaster_dual_paper_model(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name=model_name,
        log_to_console=log_to_console,
    )
    paper_dual_model.model.optimize()
    solution = extract_disaster_dual_paper_solution(paper_dual_model)
    if solution.model_status != "OPTIMAL":
        raise ValueError(
            f"Paper dual solve did not reach OPTIMAL status: "
            f"{solution.model_status} (code {solution.raw_status_code})."
        )
    return paper_dual_model, solution
