"""Residual summaries for the disaster and normal-operation reference blocks."""

from __future__ import annotations

from dataclasses import dataclass

from src.production.disaster_dual_paper import (
    DisasterPaperDualModel,
    DisasterPaperDualSolution,
)
from src.production.master_problem import (
    RestrictedMasterProblem,
    RestrictedMasterProblemSolution,
)
from src.production.normal_block import NormalOperationBlock, NormalOperationSolution
from src.reference.disaster_primal_ref import (
    DisasterPrimalReferenceModel,
    DisasterPrimalSolution,
)


@dataclass(frozen=True)
class DisasterPrimalResidualReport:
    """Compact residual summary for the fixed-outage disaster primal LP."""

    max_bound_violation: float
    max_eq27_active_balance_residual: float
    max_failed_line_flow_violation: float
    eq27_active_balance_residuals: dict[str, float]
    eq28_regional_v2g_slacks: dict[str, float]
    eq29_station_capacity_slacks: dict[str, float]
    eq30_linkage_slacks: dict[str, float]
    eq31_load_shedding_upper_slacks: dict[str, float]
    eq32_line_capacity_slacks: dict[str, float]


@dataclass(frozen=True)
class DisasterPaperDualResidualReport:
    """Named feasibility diagnostics for the hand-coded disaster paper dual."""

    max_sign_violation: float
    max_dual_row_violation: float
    decomposition_gap: float
    yls_dual_row_slacks: dict[str, float]
    discharge_slow_dual_row_slacks: dict[str, float]
    discharge_fast_dual_row_slacks: dict[str, float]
    line_flow_dual_row_residuals: dict[str, float]
    nonnegative_dual_sign_violations: dict[str, float]


@dataclass(frozen=True)
class NormalOperationResidualReport:
    """Compact feasibility diagnostics for one fixed normal-operation block."""

    max_charge_balance_residual: float
    max_active_power_balance_residual: float
    max_reactive_power_balance_residual: float
    max_voltage_drop_residual: float
    max_voltage_bound_violation: float
    max_line_limit_violation: float
    eq24_power_base_kw: float
    eq24_power_to_pu_scale: float
    eq24_unit_assumption: str
    charge_balance_residuals: dict[str, float]
    active_power_balance_residuals: dict[str, float]
    reactive_power_balance_residuals: dict[str, float]
    voltage_drop_residuals: dict[str, float]
    voltage_bound_violations: dict[str, float]
    line_limit_violations: dict[str, float]


@dataclass(frozen=True)
class RestrictedMasterProblemResidualReport:
    """Compact diagnostic summary for the fixed-cut restricted master problem."""

    max_cut_support_violation: float
    max_u_link_violation: float
    cut_support_slacks: dict[str, float]
    u_link_slacks: dict[str, float]
    active_cut_ids: tuple[str, ...]
    active_nontrivial_cut_ids: tuple[str, ...]
    first_stage_attached_objective_value: float | None
    first_stage_objective_is_pure_construction: bool
    construction_cost_value: float
    averaged_normal_cost_value: float
    unweighted_average_normal_cost_value: float
    normal_cost_by_scenario: dict[int, float]
    disaster_master_cost_value: float
    alpha_value: float
    lambda_fp_value: float
    objective_reconstruction_gap: float


def build_residual_report(
    reference_model: DisasterPrimalReferenceModel,
    solution: DisasterPrimalSolution,
) -> DisasterPrimalResidualReport:
    """Build the residual summary required by the Round 02 audit contract."""

    instance = reference_model.instance
    plan = reference_model.plan
    scenario_id = reference_model.scenario_id
    outage = reference_model.outage
    buses = instance.sets.buses
    regions = instance.sets.regions
    disaster_times = instance.sets.disaster_times
    topology = instance.network_topology

    max_bound_violation = 0.0
    eq28_slacks: dict[str, float] = {}
    eq29_slacks: dict[str, float] = {}
    eq30_slacks: dict[str, float] = {}
    eq31_slacks: dict[str, float] = {}
    for ts in disaster_times:
        for bus in buses:
            shed = solution.load_shedding_by_time_bus[(ts, bus)]
            load = instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
            max_bound_violation = max(max_bound_violation, max(0.0, -shed), max(0.0, shed - load))
            eq31_slacks[f"eq31_shed_upper_t{ts}_n{bus}"] = float(load - shed)

            slow_total = sum(
                solution.discharge_slow_by_time_region_bus[(ts, region, bus)]
                for region in regions
            )
            fast_total = sum(
                solution.discharge_fast_by_time_region_bus[(ts, region, bus)]
                for region in regions
            )
            max_bound_violation = max(
                max_bound_violation,
                max(0.0, slow_total - plan.n_sl_by_bus[bus] * instance.ev.p_ev_rated_sl),
                max(0.0, fast_total - plan.n_fa_by_bus[bus] * instance.ev.p_ev_rated_fa),
            )
            eq29_slacks[f"eq29_station_slow_capacity_t{ts}_n{bus}"] = float(
                plan.n_sl_by_bus[bus] * instance.ev.p_ev_rated_sl - slow_total
            )
            eq29_slacks[f"eq29_station_fast_capacity_t{ts}_n{bus}"] = float(
                plan.n_fa_by_bus[bus] * instance.ev.p_ev_rated_fa - fast_total
            )

            for region in regions:
                slow = solution.discharge_slow_by_time_region_bus[(ts, region, bus)]
                fast = solution.discharge_fast_by_time_region_bus[(ts, region, bus)]
                available_slow = instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)]
                available_fast = instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]
                max_bound_violation = max(
                    max_bound_violation,
                    max(0.0, -slow),
                    max(0.0, -fast),
                    max(0.0, slow - available_slow * plan.z_by_bus[bus]),
                    max(0.0, fast - available_fast * plan.z_by_bus[bus]),
                )
                eq30_slacks[f"eq30_link_slow_t{ts}_o{region}_n{bus}"] = float(
                    available_slow * plan.z_by_bus[bus] - slow
                )
                eq30_slacks[f"eq30_link_fast_t{ts}_o{region}_n{bus}"] = float(
                    available_fast * plan.z_by_bus[bus] - fast
                )

        for region in regions:
            slow_assigned = sum(
                solution.discharge_slow_by_time_region_bus[(ts, region, bus)]
                for bus in buses
            )
            fast_assigned = sum(
                solution.discharge_fast_by_time_region_bus[(ts, region, bus)]
                for bus in buses
            )
            max_bound_violation = max(
                max_bound_violation,
                max(0.0, slow_assigned - instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)]),
                max(0.0, fast_assigned - instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)]),
            )
            eq28_slacks[f"eq28_discharge_slow_t{ts}_o{region}"] = float(
                instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)] - slow_assigned
            )
            eq28_slacks[f"eq28_discharge_fast_t{ts}_o{region}"] = float(
                instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)] - fast_assigned
            )

    max_eq27_residual = 0.0
    eq27_residuals: dict[str, float] = {}
    for ts in disaster_times:
        for line in instance.lines:
            bus = line.to_bus
            child_line_ids = tuple(
                topology.line_by_child_bus[child]
                for child in topology.children_by_bus.get(bus, ())
            )
            lhs = solution.line_flow_by_time_line[(ts, line.line_id)]
            rhs = sum(solution.line_flow_by_time_line[(ts, child_line_id)] for child_line_id in child_line_ids)
            rhs += instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
            rhs -= solution.load_shedding_by_time_bus[(ts, bus)]
            rhs -= sum(
                solution.discharge_slow_by_time_region_bus[(ts, region, bus)]
                + solution.discharge_fast_by_time_region_bus[(ts, region, bus)]
                for region in regions
            )
            residual = float(lhs - rhs)
            eq27_residuals[f"eq27_active_balance_t{ts}_{line.line_id}"] = residual
            max_eq27_residual = max(max_eq27_residual, abs(residual))

    max_failed_line_flow_violation = 0.0
    eq32_slacks: dict[str, float] = {}
    for ts in disaster_times:
        for line in instance.lines:
            line_id = line.line_id
            failed = outage.by_line_id[line_id]
            available_capacity = line.p_max_kw * (1 - failed)
            flow = solution.line_flow_by_time_line[(ts, line_id)]
            eq32_slacks[f"eq32_line_upper_t{ts}_{line_id}"] = float(available_capacity - flow)
            eq32_slacks[f"eq32_line_lower_t{ts}_{line_id}"] = float(flow + available_capacity)
            if failed == 1:
                max_failed_line_flow_violation = max(
                    max_failed_line_flow_violation,
                    abs(flow),
                )

    return DisasterPrimalResidualReport(
        max_bound_violation=float(max_bound_violation),
        max_eq27_active_balance_residual=float(max_eq27_residual),
        max_failed_line_flow_violation=float(max_failed_line_flow_violation),
        eq27_active_balance_residuals=eq27_residuals,
        eq28_regional_v2g_slacks=eq28_slacks,
        eq29_station_capacity_slacks=eq29_slacks,
        eq30_linkage_slacks=eq30_slacks,
        eq31_load_shedding_upper_slacks=eq31_slacks,
        eq32_line_capacity_slacks=eq32_slacks,
    )


def build_paper_dual_residual_report(
    paper_dual_model: DisasterPaperDualModel,
    solution: DisasterPaperDualSolution,
) -> DisasterPaperDualResidualReport:
    """Build named sign and dual-row diagnostics for the hand-coded paper dual."""

    instance = paper_dual_model.instance
    topology = instance.network_topology
    buses = instance.sets.buses
    regions = instance.sets.regions
    disaster_times = instance.sets.disaster_times

    sign_violations: dict[str, float] = {}
    max_sign_violation = 0.0

    def record_sign_violation(name: str, value: float) -> None:
        nonlocal max_sign_violation
        violation = max(0.0, -float(value))
        sign_violations[name] = float(violation)
        max_sign_violation = max(max_sign_violation, violation)

    for key, value in solution.eq28_slow_values.items():
        ts, region = key
        record_sign_violation(f"eta_eq28_slow_t{ts}_o{region}", value)
    for key, value in solution.eq28_fast_values.items():
        ts, region = key
        record_sign_violation(f"eta_eq28_fast_t{ts}_o{region}", value)
    for key, value in solution.eq29_slow_values.items():
        ts, bus = key
        record_sign_violation(f"mu_eq29_slow_t{ts}_n{bus}", value)
    for key, value in solution.eq29_fast_values.items():
        ts, bus = key
        record_sign_violation(f"mu_eq29_fast_t{ts}_n{bus}", value)
    for key, value in solution.eq30_slow_values.items():
        ts, region, bus = key
        record_sign_violation(f"nu_eq30_slow_t{ts}_o{region}_n{bus}", value)
    for key, value in solution.eq30_fast_values.items():
        ts, region, bus = key
        record_sign_violation(f"nu_eq30_fast_t{ts}_o{region}_n{bus}", value)
    for key, value in solution.eq31_sigma_values.items():
        ts, bus = key
        record_sign_violation(f"sigma_eq31_t{ts}_n{bus}", value)
    for key, value in solution.eq32_upper_values.items():
        ts, line_id = key
        record_sign_violation(f"rho_eq32_upper_t{ts}_{line_id}", value)
    for key, value in solution.eq32_lower_values.items():
        ts, line_id = key
        record_sign_violation(f"rho_eq32_lower_t{ts}_{line_id}", value)

    yls_dual_row_slacks: dict[str, float] = {}
    discharge_slow_dual_row_slacks: dict[str, float] = {}
    discharge_fast_dual_row_slacks: dict[str, float] = {}
    line_flow_dual_row_residuals: dict[str, float] = {}
    max_dual_row_violation = 0.0

    for ts in disaster_times:
        for bus in buses:
            parent_line_id = topology.line_by_child_bus.get(bus)
            lhs = -solution.eq31_sigma_values[(ts, bus)]
            if parent_line_id is not None:
                lhs += solution.eq27_lambda_values[(ts, parent_line_id)]
            slack = float(paper_dual_model.cls_by_bus[bus] - lhs)
            yls_dual_row_slacks[f"dual_yls_t{ts}_n{bus}"] = slack
            max_dual_row_violation = max(max_dual_row_violation, max(0.0, -slack))

    for ts in disaster_times:
        for region in regions:
            for bus in buses:
                parent_line_id = topology.line_by_child_bus.get(bus)
                slow_lhs = (
                    -solution.eq28_slow_values[(ts, region)]
                    - solution.eq29_slow_values[(ts, bus)]
                    - solution.eq30_slow_values[(ts, region, bus)]
                )
                fast_lhs = (
                    -solution.eq28_fast_values[(ts, region)]
                    - solution.eq29_fast_values[(ts, bus)]
                    - solution.eq30_fast_values[(ts, region, bus)]
                )
                if parent_line_id is not None:
                    slow_lhs += solution.eq27_lambda_values[(ts, parent_line_id)]
                    fast_lhs += solution.eq27_lambda_values[(ts, parent_line_id)]
                slow_slack = float(-slow_lhs)
                fast_slack = float(-fast_lhs)
                discharge_slow_dual_row_slacks[
                    f"dual_ydis_slow_t{ts}_o{region}_n{bus}"
                ] = slow_slack
                discharge_fast_dual_row_slacks[
                    f"dual_ydis_fast_t{ts}_o{region}_n{bus}"
                ] = fast_slack
                max_dual_row_violation = max(
                    max_dual_row_violation,
                    max(0.0, -slow_slack),
                    max(0.0, -fast_slack),
                )

    line_by_id = {line.line_id: line for line in instance.lines}
    for ts in disaster_times:
        for line_id in instance.sets.line_ids:
            parent_line_id = topology.line_by_child_bus.get(line_by_id[line_id].from_bus)
            residual = (
                solution.eq27_lambda_values[(ts, line_id)]
                - solution.eq32_upper_values[(ts, line_id)]
                + solution.eq32_lower_values[(ts, line_id)]
            )
            if parent_line_id is not None:
                residual -= solution.eq27_lambda_values[(ts, parent_line_id)]
            line_flow_dual_row_residuals[f"dual_pdis_t{ts}_{line_id}"] = float(residual)
            max_dual_row_violation = max(max_dual_row_violation, abs(float(residual)))

    decomposition_value = solution.samplewise_decomposition.evaluate(
        plan=paper_dual_model.plan,
        outage=paper_dual_model.outage,
    )
    objective_value = float(solution.objective_value or 0.0)
    return DisasterPaperDualResidualReport(
        max_sign_violation=float(max_sign_violation),
        max_dual_row_violation=float(max_dual_row_violation),
        decomposition_gap=abs(objective_value - decomposition_value),
        yls_dual_row_slacks=yls_dual_row_slacks,
        discharge_slow_dual_row_slacks=discharge_slow_dual_row_slacks,
        discharge_fast_dual_row_slacks=discharge_fast_dual_row_slacks,
        line_flow_dual_row_residuals=line_flow_dual_row_residuals,
        nonnegative_dual_sign_violations=sign_violations,
    )


def build_normal_operation_residual_report(
    normal_block: NormalOperationBlock,
    solution: NormalOperationSolution,
) -> NormalOperationResidualReport:
    """Build named residual summaries for Eq. (17)-(25) in the normal block."""

    instance = normal_block.instance
    scenario_id = normal_block.scenario_id
    topology = instance.network_topology
    buses = instance.sets.buses
    regions = instance.sets.regions
    normal_times = instance.sets.normal_times
    root_bus = instance.frozen_config.root_bus
    line_by_id = {line.line_id: line for line in instance.lines}

    net_raw = instance.runtime_parameters.get("net", {})
    vmin = float(net_raw["Vmin"])
    vmax = float(net_raw["Vmax"])
    vmin_sq = float(vmin**2)
    vmax_sq = float(vmax**2)

    charge_balance_residuals: dict[str, float] = {}
    max_charge_balance_residual = 0.0
    for time_id in normal_times:
        for region in regions:
            slow_residual = (
                sum(
                    solution.charge_slow_by_time_region_bus[(time_id, region, bus)]
                    for bus in buses
                )
                + solution.unmet_slow_by_time_region[(time_id, region)]
                - instance.normal_tensors.dev_ch_sl[(scenario_id, time_id, region)]
            )
            fast_residual = (
                sum(
                    solution.charge_fast_by_time_region_bus[(time_id, region, bus)]
                    for bus in buses
                )
                + solution.unmet_fast_by_time_region[(time_id, region)]
                - instance.normal_tensors.dev_ch_fa[(scenario_id, time_id, region)]
            )
            charge_balance_residuals[f"eq17_balance_slow_t{time_id}_o{region}"] = float(
                slow_residual
            )
            charge_balance_residuals[f"eq17_balance_fast_t{time_id}_o{region}"] = float(
                fast_residual
            )
            max_charge_balance_residual = max(
                max_charge_balance_residual,
                abs(float(slow_residual)),
                abs(float(fast_residual)),
            )

    active_power_balance_residuals: dict[str, float] = {}
    reactive_power_balance_residuals: dict[str, float] = {}
    max_active_power_balance_residual = 0.0
    max_reactive_power_balance_residual = 0.0
    voltage_drop_residuals: dict[str, float] = {}
    max_voltage_drop_residual = 0.0
    for time_id in normal_times:
        root_child_line_ids = tuple(
            topology.line_by_child_bus[child_bus]
            for child_bus in topology.children_by_bus.get(root_bus, ())
        )
        root_charge = sum(
            solution.charge_slow_by_time_region_bus[(time_id, region, root_bus)]
            + solution.charge_fast_by_time_region_bus[(time_id, region, root_bus)]
            for region in regions
        )
        substation_residual = (
            solution.substation_active_by_time[time_id]
            - sum(
                solution.active_flow_by_time_line[(time_id, line_id)]
                for line_id in root_child_line_ids
            )
            - root_charge
            - instance.normal_tensors.p_load[(scenario_id, time_id, root_bus)]
        )
        active_power_balance_residuals[f"eq22_substation_t{time_id}"] = float(
            substation_residual
        )
        max_active_power_balance_residual = max(
            max_active_power_balance_residual,
            abs(float(substation_residual)),
        )

        for line in instance.lines:
            line_id = line.line_id
            bus = line.to_bus
            child_line_ids = tuple(
                topology.line_by_child_bus[child_bus]
                for child_bus in topology.children_by_bus.get(bus, ())
            )
            charge_at_bus = sum(
                solution.charge_slow_by_time_region_bus[(time_id, region, bus)]
                + solution.charge_fast_by_time_region_bus[(time_id, region, bus)]
                for region in regions
            )
            active_residual = (
                solution.active_flow_by_time_line[(time_id, line_id)]
                - sum(
                    solution.active_flow_by_time_line[(time_id, child_line_id)]
                    for child_line_id in child_line_ids
                )
                - charge_at_bus
                - instance.normal_tensors.p_load[(scenario_id, time_id, bus)]
            )
            reactive_residual = (
                solution.reactive_flow_by_time_line[(time_id, line_id)]
                - sum(
                    solution.reactive_flow_by_time_line[(time_id, child_line_id)]
                    for child_line_id in child_line_ids
                )
                - instance.normal_tensors.q_load[(scenario_id, time_id, bus)]
            )
            active_power_balance_residuals[
                f"eq20_active_balance_t{time_id}_{line_id}"
            ] = float(active_residual)
            reactive_power_balance_residuals[
                f"eq21_reactive_balance_t{time_id}_{line_id}"
            ] = float(reactive_residual)
            voltage_drop_residual = (
                solution.voltage_by_time_bus[(time_id, line.to_bus)]
                - solution.voltage_by_time_bus[(time_id, line.from_bus)]
                + 2.0
                * line.resistance_pu
                * normal_block.eq24_power_to_pu_scale
                * solution.active_flow_by_time_line[(time_id, line_id)]
                + 2.0
                * line.reactance_pu
                * normal_block.eq24_power_to_pu_scale
                * solution.reactive_flow_by_time_line[(time_id, line_id)]
            )
            max_active_power_balance_residual = max(
                max_active_power_balance_residual,
                abs(float(active_residual)),
            )
            max_reactive_power_balance_residual = max(
                max_reactive_power_balance_residual,
                abs(float(reactive_residual)),
            )
            voltage_drop_residuals[
                f"eq24_voltage_drop_t{time_id}_{line_id}"
            ] = float(voltage_drop_residual)
            max_voltage_drop_residual = max(
                max_voltage_drop_residual,
                abs(float(voltage_drop_residual)),
            )

    voltage_bound_violations: dict[str, float] = {}
    max_voltage_bound_violation = 0.0
    for time_id in normal_times:
        for bus in buses:
            value = solution.voltage_by_time_bus[(time_id, bus)]
            violation = max(0.0, vmin_sq - value, value - vmax_sq)
            voltage_bound_violations[f"eq25_voltage_t{time_id}_n{bus}"] = float(violation)
            max_voltage_bound_violation = max(max_voltage_bound_violation, violation)
            root_fix_residual = 0.0
            if bus == root_bus:
                root_fix_residual = abs(value - instance.frozen_config.network.v_ref_sq)
                voltage_bound_violations[f"root_voltage_fix_t{time_id}"] = float(
                    root_fix_residual
                )
                max_voltage_bound_violation = max(
                    max_voltage_bound_violation,
                    root_fix_residual,
                )

    line_limit_violations: dict[str, float] = {}
    max_line_limit_violation = 0.0
    for time_id in normal_times:
        for line_id in instance.sets.line_ids:
            line = line_by_id[line_id]
            active_violation = max(
                0.0,
                abs(solution.active_flow_by_time_line[(time_id, line_id)]) - line.p_max_kw,
            )
            reactive_violation = max(
                0.0,
                abs(solution.reactive_flow_by_time_line[(time_id, line_id)]) - line.q_max_kvar,
            )
            line_limit_violations[f"eq23_active_t{time_id}_{line_id}"] = float(
                active_violation
            )
            line_limit_violations[f"eq23_reactive_t{time_id}_{line_id}"] = float(
                reactive_violation
            )
            max_line_limit_violation = max(
                max_line_limit_violation,
                active_violation,
                reactive_violation,
            )

    return NormalOperationResidualReport(
        max_charge_balance_residual=float(max_charge_balance_residual),
        max_active_power_balance_residual=float(max_active_power_balance_residual),
        max_reactive_power_balance_residual=float(max_reactive_power_balance_residual),
        max_voltage_drop_residual=float(max_voltage_drop_residual),
        max_voltage_bound_violation=float(max_voltage_bound_violation),
        max_line_limit_violation=float(max_line_limit_violation),
        eq24_power_base_kw=float(normal_block.eq24_power_base_kw),
        eq24_power_to_pu_scale=float(normal_block.eq24_power_to_pu_scale),
        eq24_unit_assumption=str(normal_block.eq24_unit_assumption),
        charge_balance_residuals=charge_balance_residuals,
        active_power_balance_residuals=active_power_balance_residuals,
        reactive_power_balance_residuals=reactive_power_balance_residuals,
        voltage_drop_residuals=voltage_drop_residuals,
        voltage_bound_violations=voltage_bound_violations,
        line_limit_violations=line_limit_violations,
    )


def build_master_problem_residual_report(
    master_problem: RestrictedMasterProblem,
    solution: RestrictedMasterProblemSolution,
) -> RestrictedMasterProblemResidualReport:
    """Build cut-feasibility and objective-decomposition diagnostics for the RMP."""

    cut_support_slacks: dict[str, float] = {}
    u_link_slacks: dict[str, float] = {}
    max_cut_support_violation = 0.0
    max_u_link_violation = 0.0
    active_cut_ids: list[str] = []
    active_nontrivial_cut_ids: list[str] = []

    first_stage_solution = solution.first_stage_solution
    for cut in master_problem.cuts:
        gamma_value = 0.0
        for bus in master_problem.ordered_buses:
            gamma_value += (
                cut.gamma_z_by_bus[bus] * first_stage_solution.z_by_bus[bus]
                + cut.gamma_n_sl_by_bus[bus] * first_stage_solution.n_sl_by_bus[bus]
                + cut.gamma_n_fa_by_bus[bus] * first_stage_solution.n_fa_by_bus[bus]
            )
        support_slack = (
            solution.alpha_value
            - float(cut.beta)
            + gamma_value
            - float(master_problem.budget_k) * solution.s_by_cut_id[cut.cut_id]
            - sum(
                solution.u_by_cut_id_and_line_id[(cut.cut_id, line_id)]
                for line_id in master_problem.ordered_line_ids
            )
        )
        cut_support_slacks[cut.cut_id] = float(support_slack)
        max_cut_support_violation = max(max_cut_support_violation, max(0.0, -support_slack))
        if abs(float(support_slack)) <= 1e-8:
            active_cut_ids.append(cut.cut_id)
            if not cut.is_trivial():
                active_nontrivial_cut_ids.append(cut.cut_id)

        for line_id in master_problem.ordered_line_ids:
            link_slack = (
                solution.u_by_cut_id_and_line_id[(cut.cut_id, line_id)]
                + solution.lambda_by_line_id[line_id]
                + solution.s_by_cut_id[cut.cut_id]
                - float(cut.phi_by_line_id[line_id])
            )
            u_link_slacks[f"{cut.cut_id}:{line_id}"] = float(link_slack)
            max_u_link_violation = max(max_u_link_violation, max(0.0, -link_slack))

    return RestrictedMasterProblemResidualReport(
        max_cut_support_violation=float(max_cut_support_violation),
        max_u_link_violation=float(max_u_link_violation),
        cut_support_slacks=cut_support_slacks,
        u_link_slacks=u_link_slacks,
        active_cut_ids=tuple(active_cut_ids),
        active_nontrivial_cut_ids=tuple(active_nontrivial_cut_ids),
        first_stage_attached_objective_value=(
            None
            if first_stage_solution.objective_value is None
            else float(first_stage_solution.objective_value)
        ),
        first_stage_objective_is_pure_construction=bool(
            first_stage_solution.objective_is_pure_construction
        ),
        construction_cost_value=float(solution.construction_cost_value),
        averaged_normal_cost_value=float(solution.averaged_normal_cost_value),
        unweighted_average_normal_cost_value=float(solution.unweighted_average_normal_cost_value),
        normal_cost_by_scenario={
            int(scenario_id): float(value)
            for scenario_id, value in solution.normal_cost_by_scenario.items()
        },
        disaster_master_cost_value=float(solution.disaster_master_cost_value),
        alpha_value=float(solution.alpha_value),
        lambda_fp_value=float(solution.lambda_fp_value),
        objective_reconstruction_gap=float(solution.objective_reconstruction_gap),
    )
