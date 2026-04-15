"""Minimal residual summaries for the disaster primal reference LP."""

from __future__ import annotations

from dataclasses import dataclass

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
    for ts in disaster_times:
        for bus in buses:
            shed = solution.load_shedding_by_time_bus[(ts, bus)]
            load = instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
            max_bound_violation = max(max_bound_violation, max(0.0, -shed), max(0.0, shed - load))

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

    max_eq27_residual = 0.0
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
            max_eq27_residual = max(max_eq27_residual, abs(lhs - rhs))

    max_failed_line_flow_violation = 0.0
    for ts in disaster_times:
        for line_id, failed in outage.by_line_id.items():
            if failed == 1:
                max_failed_line_flow_violation = max(
                    max_failed_line_flow_violation,
                    abs(solution.line_flow_by_time_line[(ts, line_id)]),
                )

    return DisasterPrimalResidualReport(
        max_bound_violation=float(max_bound_violation),
        max_eq27_active_balance_residual=float(max_eq27_residual),
        max_failed_line_flow_violation=float(max_failed_line_flow_violation),
    )
