"""Fixed-`(x, alpha, lambda)` separation MILP for the disaster DRO term."""

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
from src.production.disaster_dual_paper import (
    FixedFirstStagePlanLike,
    SamplewisePaperDualDecomposition,
)


@dataclass(frozen=True)
class SeparationSampleDualBlock:
    """Grouped paper-dual block for one sampled disaster realization."""

    scenario_id: int
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


@dataclass(frozen=True)
class SeparationSampleDualSolution:
    """Numeric grouped paper-dual block for one sample inside the separation MILP."""

    scenario_id: int
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
    group_activity_counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SeparationMilpModel:
    """Built separation MILP plus grouped variable metadata."""

    instance: CanonicalInstance
    plan: FixedFirstStagePlanLike
    alpha: float
    lambda_by_line_id: dict[str, float]
    budget_k: int
    scenario_ids: tuple[int, ...]
    omega_bounds_by_line_id: dict[str, tuple[float, float]]
    cls_by_bus: dict[int, float]
    model: Model
    delta_vars: dict[str, object] = field(default_factory=dict)
    omega_vars: dict[str, object] = field(default_factory=dict)
    tau_vars: dict[str, object] = field(default_factory=dict)
    sample_blocks: dict[int, SeparationSampleDualBlock] = field(default_factory=dict)


@dataclass(frozen=True)
class SeparationMilpSolution:
    """Structured solved result for the fixed-point separation MILP."""

    objective_value: float | None
    model_status: str
    raw_status_code: int
    delta_by_line_id: dict[str, int]
    omega_by_line_id: dict[str, float]
    tau_by_line_id: dict[str, float]
    omega_lower_slack_by_line_id: dict[str, float]
    omega_upper_slack_by_line_id: dict[str, float]
    max_omega_bound_violation: float
    samplewise_dual_solutions: dict[int, SeparationSampleDualSolution]
    active_groups: dict[str, bool]
    average_base_value: float
    tau_sum: float
    lambda_delta_value: float
    alpha_value: float
    reconstructed_objective: float
    reconstruction_gap: float


def _coerce_nonnegative_int_map(
    raw: Mapping[int, int],
    *,
    label: str,
    keys: Sequence[int],
    binary: bool = False,
) -> dict[int, int]:
    normalized: dict[int, int] = {}
    key_set = set(keys)
    invalid = sorted(key for key in raw if key not in key_set)
    if invalid:
        raise RuntimeDataValidationError(f"{label} contains invalid ids: {tuple(invalid)}.")
    for key in keys:
        if key not in raw:
            raise RuntimeDataValidationError(f"{label} is missing required id {key}.")
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int):
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
) -> tuple[dict[int, int], dict[int, int], dict[int, int]]:
    buses = instance.sets.buses
    z_by_bus = _coerce_nonnegative_int_map(
        plan.z_by_bus,
        label="plan.z_by_bus",
        keys=buses,
        binary=True,
    )
    n_sl_by_bus = _coerce_nonnegative_int_map(
        plan.n_sl_by_bus,
        label="plan.n_sl_by_bus",
        keys=buses,
    )
    n_fa_by_bus = _coerce_nonnegative_int_map(
        plan.n_fa_by_bus,
        label="plan.n_fa_by_bus",
        keys=buses,
    )
    return z_by_bus, n_sl_by_bus, n_fa_by_bus


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


def _resolve_lambda_by_line_id(
    line_ids: Sequence[str],
    lambda_by_line_id: Mapping[str, float] | None,
) -> dict[str, float]:
    normalized = {line_id: 0.0 for line_id in line_ids}
    if lambda_by_line_id is None:
        return normalized
    invalid = sorted(line_id for line_id in lambda_by_line_id if line_id not in normalized)
    if invalid:
        raise RuntimeDataValidationError(
            f"lambda_by_line_id contains invalid line ids: {tuple(invalid)}."
        )
    for line_id, value in lambda_by_line_id.items():
        numeric = float(value)
        if numeric < -1e-12:
            raise RuntimeDataValidationError(
                f"lambda_by_line_id[{line_id!r}] must be nonnegative, got {numeric}."
            )
        normalized[line_id] = max(0.0, numeric)
    return normalized


def _resolve_omega_bounds(
    line_ids: Sequence[str],
    omega_bounds_by_line_id: Mapping[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    normalized: dict[str, tuple[float, float]] = {}
    invalid = sorted(line_id for line_id in omega_bounds_by_line_id if line_id not in set(line_ids))
    if invalid:
        raise RuntimeDataValidationError(
            f"omega_bounds_by_line_id contains invalid line ids: {tuple(invalid)}."
        )
    for line_id in line_ids:
        if line_id not in omega_bounds_by_line_id:
            raise RuntimeDataValidationError(
                f"omega_bounds_by_line_id is missing line id {line_id}."
            )
        lower, upper = omega_bounds_by_line_id[line_id]
        lower_value = float(lower)
        upper_value = float(upper)
        if lower_value > upper_value + 1e-12:
            raise RuntimeDataValidationError(
                f"omega bounds for {line_id} are invalid: lower {lower_value} > upper {upper_value}."
            )
        normalized[line_id] = (lower_value, upper_value)
    return normalized


def _resolve_scenarios(
    instance: CanonicalInstance,
    scenario_ids: Sequence[int] | None,
) -> tuple[int, ...]:
    selected = tuple(
        int(scenario_id)
        for scenario_id in (
            scenario_ids if scenario_ids is not None else instance.sets.loaded_disaster_scenarios
        )
    )
    if not selected:
        raise RuntimeDataValidationError("At least one disaster scenario is required.")
    loaded = set(instance.sets.loaded_disaster_scenarios)
    invalid = tuple(sorted(scenario_id for scenario_id in selected if scenario_id not in loaded))
    if invalid:
        raise RuntimeDataValidationError(
            f"scenario_ids contains scenarios outside the loaded canonical support: {invalid}."
        )
    return selected


def _sample_zero_outage(line_ids: Sequence[str]) -> dict[str, int]:
    return {line_id: 0 for line_id in line_ids}


def _evaluate_base_value(
    decomposition: SamplewisePaperDualDecomposition,
    *,
    z_by_bus: Mapping[int, int],
    n_sl_by_bus: Mapping[int, int],
    n_fa_by_bus: Mapping[int, int],
) -> float:
    total = float(decomposition.beta_b)
    for bus, coefficient in decomposition.gamma_z_by_bus.items():
        total -= float(coefficient) * float(z_by_bus[bus])
    for bus, coefficient in decomposition.gamma_n_sl_by_bus.items():
        total -= float(coefficient) * float(n_sl_by_bus[bus])
    for bus, coefficient in decomposition.gamma_n_fa_by_bus.items():
        total -= float(coefficient) * float(n_fa_by_bus[bus])
    return float(total)


def _build_samplewise_decomposition_from_solution(
    instance: CanonicalInstance,
    *,
    scenario_id: int,
    sample_solution: SeparationSampleDualSolution,
) -> SamplewisePaperDualDecomposition:
    buses = instance.sets.buses
    regions = instance.sets.regions
    disaster_times = instance.sets.disaster_times

    beta_b = 0.0
    for ts in disaster_times:
        for line in instance.lines:
            beta_b += (
                instance.disaster_tensors.p_load[(scenario_id, ts, line.to_bus)]
                * sample_solution.eq27_lambda_values[(ts, line.line_id)]
            )
        for region in regions:
            beta_b -= (
                instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)]
                * sample_solution.eq28_slow_values[(ts, region)]
            )
            beta_b -= (
                instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]
                * sample_solution.eq28_fast_values[(ts, region)]
            )
        for bus in buses:
            beta_b -= (
                instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
                * sample_solution.eq31_sigma_values[(ts, bus)]
            )
        for line in instance.lines:
            rho_total = (
                sample_solution.eq32_upper_values[(ts, line.line_id)]
                + sample_solution.eq32_lower_values[(ts, line.line_id)]
            )
            beta_b -= line.p_max_kw * rho_total

    gamma_z_by_bus = {bus: 0.0 for bus in buses}
    gamma_n_sl_by_bus = {bus: 0.0 for bus in buses}
    gamma_n_fa_by_bus = {bus: 0.0 for bus in buses}
    for ts in disaster_times:
        for bus in buses:
            gamma_n_sl_by_bus[bus] += (
                instance.ev.p_ev_rated_sl * sample_solution.eq29_slow_values[(ts, bus)]
            )
            gamma_n_fa_by_bus[bus] += (
                instance.ev.p_ev_rated_fa * sample_solution.eq29_fast_values[(ts, bus)]
            )
            for region in regions:
                gamma_z_by_bus[bus] += (
                    instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)]
                    * sample_solution.eq30_slow_values[(ts, region, bus)]
                )
                gamma_z_by_bus[bus] += (
                    instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]
                    * sample_solution.eq30_fast_values[(ts, region, bus)]
                )

    phi_by_line_id = {line_id: 0.0 for line_id in instance.sets.line_ids}
    for line in instance.lines:
        phi_by_line_id[line.line_id] = line.p_max_kw * sum(
            sample_solution.eq32_upper_values[(ts, line.line_id)]
            + sample_solution.eq32_lower_values[(ts, line.line_id)]
            for ts in disaster_times
        )
    return SamplewisePaperDualDecomposition(
        beta_b=float(beta_b),
        gamma_z_by_bus=gamma_z_by_bus,
        gamma_n_sl_by_bus=gamma_n_sl_by_bus,
        gamma_n_fa_by_bus=gamma_n_fa_by_bus,
        phi_by_line_id=phi_by_line_id,
    )


def _build_group_activity_counts(
    sample_solution: SeparationSampleDualSolution,
) -> dict[str, int]:
    return {
        "eta": int(
            sum(abs(value) > 1e-8 for value in sample_solution.eq28_slow_values.values())
            + sum(abs(value) > 1e-8 for value in sample_solution.eq28_fast_values.values())
        ),
        "mu": int(
            sum(abs(value) > 1e-8 for value in sample_solution.eq29_slow_values.values())
            + sum(abs(value) > 1e-8 for value in sample_solution.eq29_fast_values.values())
        ),
        "nu": int(
            sum(abs(value) > 1e-8 for value in sample_solution.eq30_slow_values.values())
            + sum(abs(value) > 1e-8 for value in sample_solution.eq30_fast_values.values())
        ),
        "sigma": int(sum(abs(value) > 1e-8 for value in sample_solution.eq31_sigma_values.values())),
        "rho_upper": int(
            sum(abs(value) > 1e-8 for value in sample_solution.eq32_upper_values.values())
        ),
        "rho_lower": int(
            sum(abs(value) > 1e-8 for value in sample_solution.eq32_lower_values.values())
        ),
    }


def _add_sample_dual_block(
    model: Model,
    *,
    instance: CanonicalInstance,
    scenario_id: int,
    z_by_bus: Mapping[int, int],
    n_sl_by_bus: Mapping[int, int],
    n_fa_by_bus: Mapping[int, int],
    cls_by_bus: Mapping[int, float],
) -> tuple[SeparationSampleDualBlock, object, dict[str, object]]:
    buses = instance.sets.buses
    regions = instance.sets.regions
    disaster_times = instance.sets.disaster_times
    line_ids = instance.sets.line_ids
    line_by_id = {line.line_id: line for line in instance.lines}

    eq27_lambda_vars = {
        (ts, line_id): model.addVar(
            lb=-GRB.INFINITY,
            name=f"sep_b{scenario_id}_lam_eq27_t{ts}_{line_id}",
        )
        for ts in disaster_times
        for line_id in line_ids
    }
    eq28_slow_vars = {
        (ts, region): model.addVar(
            lb=0.0,
            name=f"sep_b{scenario_id}_eta_eq28_slow_t{ts}_o{region}",
        )
        for ts in disaster_times
        for region in regions
    }
    eq28_fast_vars = {
        (ts, region): model.addVar(
            lb=0.0,
            name=f"sep_b{scenario_id}_eta_eq28_fast_t{ts}_o{region}",
        )
        for ts in disaster_times
        for region in regions
    }
    eq29_slow_vars = {
        (ts, bus): model.addVar(
            lb=0.0,
            name=f"sep_b{scenario_id}_mu_eq29_slow_t{ts}_n{bus}",
        )
        for ts in disaster_times
        for bus in buses
    }
    eq29_fast_vars = {
        (ts, bus): model.addVar(
            lb=0.0,
            name=f"sep_b{scenario_id}_mu_eq29_fast_t{ts}_n{bus}",
        )
        for ts in disaster_times
        for bus in buses
    }
    eq30_slow_vars = {
        (ts, region, bus): model.addVar(
            lb=0.0,
            name=f"sep_b{scenario_id}_nu_eq30_slow_t{ts}_o{region}_n{bus}",
        )
        for ts in disaster_times
        for region in regions
        for bus in buses
    }
    eq30_fast_vars = {
        (ts, region, bus): model.addVar(
            lb=0.0,
            name=f"sep_b{scenario_id}_nu_eq30_fast_t{ts}_o{region}_n{bus}",
        )
        for ts in disaster_times
        for region in regions
        for bus in buses
    }
    eq31_sigma_vars = {
        (ts, bus): model.addVar(
            lb=0.0,
            name=f"sep_b{scenario_id}_sigma_eq31_t{ts}_n{bus}",
        )
        for ts in disaster_times
        for bus in buses
    }
    eq32_upper_vars = {
        (ts, line_id): model.addVar(
            lb=0.0,
            name=f"sep_b{scenario_id}_rho_eq32_upper_t{ts}_{line_id}",
        )
        for ts in disaster_times
        for line_id in line_ids
    }
    eq32_lower_vars = {
        (ts, line_id): model.addVar(
            lb=0.0,
            name=f"sep_b{scenario_id}_rho_eq32_lower_t{ts}_{line_id}",
        )
        for ts in disaster_times
        for line_id in line_ids
    }

    base_expression = (
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
            * (eq32_upper_vars[(ts, line_id)] + eq32_lower_vars[(ts, line_id)])
            for ts in disaster_times
            for line_id in line_ids
        )
    )
    phi_expression_by_line_id = {
        line_id: quicksum(
            line_by_id[line_id].p_max_kw
            * (eq32_upper_vars[(ts, line_id)] + eq32_lower_vars[(ts, line_id)])
            for ts in disaster_times
        )
        for line_id in line_ids
    }

    topology = instance.network_topology
    for ts in disaster_times:
        for bus in buses:
            parent_line_id = topology.line_by_child_bus.get(bus)
            lhs = -eq31_sigma_vars[(ts, bus)]
            if parent_line_id is not None:
                lhs += eq27_lambda_vars[(ts, parent_line_id)]
            model.addConstr(
                lhs <= cls_by_bus[bus],
                name=f"sep_b{scenario_id}_dual_yls_t{ts}_n{bus}",
            )

    for ts in disaster_times:
        for region in regions:
            for bus in buses:
                parent_line_id = topology.line_by_child_bus.get(bus)
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
                model.addConstr(
                    slow_lhs <= 0.0,
                    name=f"sep_b{scenario_id}_dual_ydis_slow_t{ts}_o{region}_n{bus}",
                )
                model.addConstr(
                    fast_lhs <= 0.0,
                    name=f"sep_b{scenario_id}_dual_ydis_fast_t{ts}_o{region}_n{bus}",
                )

    for ts in disaster_times:
        for line_id in line_ids:
            parent_line_id = topology.line_by_child_bus.get(line_by_id[line_id].from_bus)
            lhs = (
                eq27_lambda_vars[(ts, line_id)]
                - eq32_upper_vars[(ts, line_id)]
                + eq32_lower_vars[(ts, line_id)]
            )
            if parent_line_id is not None:
                lhs -= eq27_lambda_vars[(ts, parent_line_id)]
            model.addConstr(
                lhs == 0.0,
                name=f"sep_b{scenario_id}_dual_pdis_t{ts}_{line_id}",
            )

    return (
        SeparationSampleDualBlock(
            scenario_id=scenario_id,
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
        ),
        base_expression,
        phi_expression_by_line_id,
    )


def build_separation_milp(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlanLike,
    alpha: float,
    lambda_by_line_id: Mapping[str, float] | None,
    omega_bounds_by_line_id: Mapping[str, tuple[float, float]],
    budget_k: int | None = None,
    scenario_ids: Sequence[int] | None = None,
    model_name: str = "separation_milp",
    log_to_console: bool = False,
) -> SeparationMilpModel:
    """Build the fixed-`(x, alpha, lambda)` separation MILP for Eq. (41)."""

    line_ids = instance.sets.line_ids
    effective_budget = int(instance.ambiguity.k_max_outages if budget_k is None else budget_k)
    if effective_budget < 0:
        raise RuntimeDataValidationError(
            f"budget_k must be nonnegative, got {effective_budget}."
        )
    if effective_budget > len(line_ids):
        raise RuntimeDataValidationError(
            f"budget_k {effective_budget} exceeds the line count {len(line_ids)}."
        )

    z_by_bus, n_sl_by_bus, n_fa_by_bus = _resolve_plan_maps(instance, plan)
    cls_by_bus = _resolve_cls_by_bus(instance)
    normalized_lambda = _resolve_lambda_by_line_id(line_ids, lambda_by_line_id)
    normalized_omega_bounds = _resolve_omega_bounds(line_ids, omega_bounds_by_line_id)
    selected_scenarios = _resolve_scenarios(instance, scenario_ids)

    model = Model(model_name)
    model.Params.OutputFlag = 1 if log_to_console else 0

    delta_vars = {
        line_id: model.addVar(vtype=GRB.BINARY, name=f"delta_{line_id}")
        for line_id in line_ids
    }
    omega_vars = {
        line_id: model.addVar(
            lb=normalized_omega_bounds[line_id][0],
            ub=normalized_omega_bounds[line_id][1],
            name=f"omega_{line_id}",
        )
        for line_id in line_ids
    }
    tau_vars = {}
    for line_id in line_ids:
        lower, upper = normalized_omega_bounds[line_id]
        tau_vars[line_id] = model.addVar(
            lb=min(0.0, lower),
            ub=max(0.0, upper),
            name=f"tau_{line_id}",
        )

    sample_blocks: dict[int, SeparationSampleDualBlock] = {}
    sample_base_expressions = []
    phi_expr_by_sample: dict[int, dict[str, object]] = {}
    for scenario_id in selected_scenarios:
        block, base_expression, phi_by_line_id = _add_sample_dual_block(
            model,
            instance=instance,
            scenario_id=scenario_id,
            z_by_bus=z_by_bus,
            n_sl_by_bus=n_sl_by_bus,
            n_fa_by_bus=n_fa_by_bus,
            cls_by_bus=cls_by_bus,
        )
        sample_blocks[scenario_id] = block
        sample_base_expressions.append(base_expression)
        phi_expr_by_sample[scenario_id] = phi_by_line_id

    sample_count = len(selected_scenarios)
    model.addConstr(
        quicksum(delta_vars[line_id] for line_id in line_ids) <= effective_budget,
        name="outage_budget",
    )
    for line_id in line_ids:
        model.addConstr(
            omega_vars[line_id]
            == quicksum(phi_expr_by_sample[scenario_id][line_id] for scenario_id in selected_scenarios)
            / sample_count,
            name=f"omega_definition_{line_id}",
        )
        lower, upper = normalized_omega_bounds[line_id]
        model.addConstr(
            tau_vars[line_id] >= lower * delta_vars[line_id],
            name=f"tau_lower_prod_{line_id}",
        )
        model.addConstr(
            tau_vars[line_id] <= upper * delta_vars[line_id],
            name=f"tau_upper_prod_{line_id}",
        )
        model.addConstr(
            tau_vars[line_id] >= omega_vars[line_id] - upper * (1 - delta_vars[line_id]),
            name=f"tau_mccormick_lb_{line_id}",
        )
        model.addConstr(
            tau_vars[line_id] <= omega_vars[line_id] - lower * (1 - delta_vars[line_id]),
            name=f"tau_mccormick_ub_{line_id}",
        )

    model.setObjective(
        quicksum(sample_base_expressions) / sample_count
        + quicksum(tau_vars[line_id] for line_id in line_ids)
        - quicksum(normalized_lambda[line_id] * delta_vars[line_id] for line_id in line_ids)
        - float(alpha),
        sense=GRB.MAXIMIZE,
    )
    model.update()
    return SeparationMilpModel(
        instance=instance,
        plan=plan,
        alpha=float(alpha),
        lambda_by_line_id=normalized_lambda,
        budget_k=effective_budget,
        scenario_ids=selected_scenarios,
        omega_bounds_by_line_id=normalized_omega_bounds,
        cls_by_bus=cls_by_bus,
        model=model,
        delta_vars=delta_vars,
        omega_vars=omega_vars,
        tau_vars=tau_vars,
        sample_blocks=sample_blocks,
    )


def extract_separation_milp_solution(
    separation_model: SeparationMilpModel,
) -> SeparationMilpSolution:
    """Extract a structured solution from an optimized separation MILP."""

    model = separation_model.model
    status_code = int(model.Status)
    status_name = str(model.Status)
    if status_code == GRB.OPTIMAL:
        status_name = "OPTIMAL"
    elif status_code == GRB.INFEASIBLE:
        status_name = "INFEASIBLE"
    elif status_code == GRB.UNBOUNDED:
        status_name = "UNBOUNDED"

    objective_value = float(model.ObjVal) if status_code == GRB.OPTIMAL else None
    if status_code != GRB.OPTIMAL:
        return SeparationMilpSolution(
            objective_value=objective_value,
            model_status=status_name,
            raw_status_code=status_code,
            delta_by_line_id={line_id: 0 for line_id in separation_model.instance.sets.line_ids},
            omega_by_line_id={line_id: 0.0 for line_id in separation_model.instance.sets.line_ids},
            tau_by_line_id={line_id: 0.0 for line_id in separation_model.instance.sets.line_ids},
            omega_lower_slack_by_line_id={
                line_id: 0.0 for line_id in separation_model.instance.sets.line_ids
            },
            omega_upper_slack_by_line_id={
                line_id: 0.0 for line_id in separation_model.instance.sets.line_ids
            },
            max_omega_bound_violation=0.0,
            samplewise_dual_solutions={},
            active_groups={},
            average_base_value=0.0,
            tau_sum=0.0,
            lambda_delta_value=0.0,
            alpha_value=float(separation_model.alpha),
            reconstructed_objective=0.0,
            reconstruction_gap=0.0,
        )

    delta_by_line_id = {
        line_id: int(round(float(var.X)))
        for line_id, var in separation_model.delta_vars.items()
    }
    omega_by_line_id = {
        line_id: float(var.X)
        for line_id, var in separation_model.omega_vars.items()
    }
    tau_by_line_id = {
        line_id: float(var.X)
        for line_id, var in separation_model.tau_vars.items()
    }
    omega_lower_slack_by_line_id = {
        line_id: float(
            omega_by_line_id[line_id] - separation_model.omega_bounds_by_line_id[line_id][0]
        )
        for line_id in separation_model.instance.sets.line_ids
    }
    omega_upper_slack_by_line_id = {
        line_id: float(
            separation_model.omega_bounds_by_line_id[line_id][1] - omega_by_line_id[line_id]
        )
        for line_id in separation_model.instance.sets.line_ids
    }
    max_omega_bound_violation = float(
        max(
            [0.0]
            + [
                max(0.0, -omega_lower_slack_by_line_id[line_id])
                for line_id in separation_model.instance.sets.line_ids
            ]
            + [
                max(0.0, -omega_upper_slack_by_line_id[line_id])
                for line_id in separation_model.instance.sets.line_ids
            ]
        )
    )

    samplewise_dual_solutions: dict[int, SeparationSampleDualSolution] = {}
    for scenario_id, block in separation_model.sample_blocks.items():
        provisional = SeparationSampleDualSolution(
            scenario_id=scenario_id,
            eq27_lambda_values={key: float(var.X) for key, var in block.eq27_lambda_vars.items()},
            eq28_slow_values={key: float(var.X) for key, var in block.eq28_slow_vars.items()},
            eq28_fast_values={key: float(var.X) for key, var in block.eq28_fast_vars.items()},
            eq29_slow_values={key: float(var.X) for key, var in block.eq29_slow_vars.items()},
            eq29_fast_values={key: float(var.X) for key, var in block.eq29_fast_vars.items()},
            eq30_slow_values={key: float(var.X) for key, var in block.eq30_slow_vars.items()},
            eq30_fast_values={key: float(var.X) for key, var in block.eq30_fast_vars.items()},
            eq31_sigma_values={key: float(var.X) for key, var in block.eq31_sigma_vars.items()},
            eq32_upper_values={key: float(var.X) for key, var in block.eq32_upper_vars.items()},
            eq32_lower_values={key: float(var.X) for key, var in block.eq32_lower_vars.items()},
            samplewise_decomposition=SamplewisePaperDualDecomposition(beta_b=0.0),
            group_activity_counts={},
        )
        decomposition = _build_samplewise_decomposition_from_solution(
            separation_model.instance,
            scenario_id=scenario_id,
            sample_solution=provisional,
        )
        completed = SeparationSampleDualSolution(
            scenario_id=scenario_id,
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
            group_activity_counts={},
        )
        activity_counts = _build_group_activity_counts(completed)
        samplewise_dual_solutions[scenario_id] = SeparationSampleDualSolution(
            scenario_id=scenario_id,
            eq27_lambda_values=completed.eq27_lambda_values,
            eq28_slow_values=completed.eq28_slow_values,
            eq28_fast_values=completed.eq28_fast_values,
            eq29_slow_values=completed.eq29_slow_values,
            eq29_fast_values=completed.eq29_fast_values,
            eq30_slow_values=completed.eq30_slow_values,
            eq30_fast_values=completed.eq30_fast_values,
            eq31_sigma_values=completed.eq31_sigma_values,
            eq32_upper_values=completed.eq32_upper_values,
            eq32_lower_values=completed.eq32_lower_values,
            samplewise_decomposition=completed.samplewise_decomposition,
            group_activity_counts=activity_counts,
        )

    z_by_bus, n_sl_by_bus, n_fa_by_bus = _resolve_plan_maps(
        separation_model.instance,
        separation_model.plan,
    )
    average_base_value = float(
        sum(
            _evaluate_base_value(
                sample_solution.samplewise_decomposition,
                z_by_bus=z_by_bus,
                n_sl_by_bus=n_sl_by_bus,
                n_fa_by_bus=n_fa_by_bus,
            )
            for sample_solution in samplewise_dual_solutions.values()
        )
        / len(samplewise_dual_solutions)
    )
    tau_sum = float(sum(tau_by_line_id.values()))
    lambda_delta_value = float(
        sum(
            separation_model.lambda_by_line_id[line_id] * delta_by_line_id[line_id]
            for line_id in separation_model.instance.sets.line_ids
        )
    )
    reconstructed_objective = float(
        average_base_value + tau_sum - lambda_delta_value - separation_model.alpha
    )
    active_groups = {
        group_name: any(
            sample_solution.group_activity_counts.get(group_name, 0) > 0
            for sample_solution in samplewise_dual_solutions.values()
        )
        for group_name in ("eta", "mu", "nu", "sigma", "rho_upper", "rho_lower")
    }

    return SeparationMilpSolution(
        objective_value=objective_value,
        model_status=status_name,
        raw_status_code=status_code,
        delta_by_line_id=delta_by_line_id,
        omega_by_line_id=omega_by_line_id,
        tau_by_line_id=tau_by_line_id,
        omega_lower_slack_by_line_id=omega_lower_slack_by_line_id,
        omega_upper_slack_by_line_id=omega_upper_slack_by_line_id,
        max_omega_bound_violation=max_omega_bound_violation,
        samplewise_dual_solutions=samplewise_dual_solutions,
        active_groups=active_groups,
        average_base_value=average_base_value,
        tau_sum=tau_sum,
        lambda_delta_value=lambda_delta_value,
        alpha_value=float(separation_model.alpha),
        reconstructed_objective=reconstructed_objective,
        reconstruction_gap=abs(float(objective_value or 0.0) - reconstructed_objective),
    )


def solve_separation_milp(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlanLike,
    alpha: float,
    lambda_by_line_id: Mapping[str, float] | None,
    omega_bounds_by_line_id: Mapping[str, tuple[float, float]],
    budget_k: int | None = None,
    scenario_ids: Sequence[int] | None = None,
    model_name: str = "separation_milp",
    log_to_console: bool = False,
) -> tuple[SeparationMilpModel, SeparationMilpSolution]:
    """Build, solve, and extract the fixed-point separation MILP."""

    separation_model = build_separation_milp(
        instance,
        plan=plan,
        alpha=alpha,
        lambda_by_line_id=lambda_by_line_id,
        omega_bounds_by_line_id=omega_bounds_by_line_id,
        budget_k=budget_k,
        scenario_ids=scenario_ids,
        model_name=model_name,
        log_to_console=log_to_console,
    )
    separation_model.model.optimize()
    solution = extract_separation_milp_solution(separation_model)
    if solution.model_status != "OPTIMAL":
        raise ValueError(
            f"Separation MILP did not reach OPTIMAL status: "
            f"{solution.model_status} (code {solution.raw_status_code})."
        )
    return separation_model, solution
