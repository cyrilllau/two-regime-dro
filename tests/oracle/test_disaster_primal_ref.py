"""Oracle tests for the fixed-(x, delta, b) disaster primal reference LP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import build_residual_report
from src.contracts.freeze import DEFAULT_FROZEN_CONFIG
from src.contracts.naming import make_line_id
from src.instance.canonical_instance import CanonicalInstance, ScenarioSupport
from src.instance.indexer import build_index_map
from src.instance.network_topology import Line, build_network_topology
from src.instance.schema import (
    AmbiguityParameters,
    CanonicalSets,
    DisasterScenarioTensor,
    EconomicParameters,
    EVParameters,
    LineData,
    NodeMeta,
    NormalScenarioTensor,
)
from src.instance.validators import RuntimeDataValidationError, build_criticality_maps
from src.reference.disaster_primal_ref import (
    build_disaster_primal_reference_model,
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
    solve_disaster_primal_reference,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _build_toy_instance(
    raw: dict[str, object],
    *,
    include_critical_buses: bool = True,
) -> CanonicalInstance:
    buses = tuple(int(bus) for bus in raw["buses"])
    line_pairs = [tuple(pair) for pair in raw["lines"]]
    line_ids = tuple(make_line_id(from_bus, to_bus) for from_bus, to_bus in line_pairs)
    regions = tuple(int(region) for region in raw["regions"])
    disaster_times = tuple(int(ts) for ts in raw["disaster_times"])
    normal_times = (1,)
    scenario_id = int(raw["scenario_id"])

    lines = tuple(
        LineData(
            line_id=make_line_id(from_bus, to_bus),
            from_bus=from_bus,
            to_bus=to_bus,
            resistance_pu=0.0,
            reactance_pu=0.0,
            p_max_kw=float(raw["line_p_max_kw"]),
            q_max_kvar=float(raw["line_p_max_kw"]),
        )
        for from_bus, to_bus in line_pairs
    )
    topology = build_network_topology(
        buses=buses,
        lines=tuple(
            Line(
                line_id=line.line_id,
                from_bus=line.from_bus,
                to_bus=line.to_bus,
            )
            for line in lines
        ),
        root_bus=DEFAULT_FROZEN_CONFIG.root_bus,
    )

    critical_buses = None
    if include_critical_buses:
        critical_buses = tuple(int(bus) for bus in raw["critical_buses"])
    is_critical_by_bus, cls_by_bus = build_criticality_maps(
        buses=buses,
        critical_buses=critical_buses,
        cls_critical=DEFAULT_FROZEN_CONFIG.disaster_objective.cls_critical,
        cls_noncritical=DEFAULT_FROZEN_CONFIG.disaster_objective.cls_noncritical,
    )
    nodes = tuple(
        NodeMeta(
            bus_id=bus,
            is_root=bus == DEFAULT_FROZEN_CONFIG.root_bus,
            candidate_for_evcs=bus in DEFAULT_FROZEN_CONFIG.candidate_buses_for(buses),
            is_critical=None if is_critical_by_bus is None else is_critical_by_bus[bus],
        )
        for bus in buses
    )

    normal_zero_bus = {
        (1, ts, bus): 0.0
        for ts in normal_times
        for bus in buses
    }
    normal_zero_region = {
        (1, ts, region): 0.0
        for ts in normal_times
        for region in regions
    }
    normal_tensors = NormalScenarioTensor(
        support=(1,),
        p_load=dict(normal_zero_bus),
        q_load=dict(normal_zero_bus),
        dev_ch_sl=dict(normal_zero_region),
        dev_ch_fa=dict(normal_zero_region),
    )

    load_by_key = {
        (scenario_id, ts, bus): 0.0
        for ts in disaster_times
        for bus in buses
    }
    for row in raw["loads"]:
        load_by_key[(scenario_id, int(row["ts"]), int(row["bus"]))] = float(row["p_kw"])

    dev_dis_sl = {
        (scenario_id, ts, region): 0.0
        for ts in disaster_times
        for region in regions
    }
    for row in raw["dev_dis_sl"]:
        dev_dis_sl[(scenario_id, int(row["ts"]), int(row["region"]))] = float(row["value"])

    dev_dis_fa = {
        (scenario_id, ts, region): 0.0
        for ts in disaster_times
        for region in regions
    }
    for row in raw["dev_dis_fa"]:
        dev_dis_fa[(scenario_id, int(row["ts"]), int(row["region"]))] = float(row["value"])

    disaster_tensors = DisasterScenarioTensor(
        support=(scenario_id,),
        p_load=load_by_key,
        dev_dis_sl=dev_dis_sl,
        dev_dis_fa=dev_dis_fa,
    )

    return CanonicalInstance(
        frozen_config=DEFAULT_FROZEN_CONFIG,
        sets=CanonicalSets(
            buses=buses,
            line_ids=line_ids,
            regions=regions,
            normal_times=normal_times,
            disaster_times=disaster_times,
            declared_normal_scenarios=(1,),
            declared_disaster_scenarios=(scenario_id,),
            available_normal_scenarios=(1,),
            available_disaster_scenarios=(scenario_id,),
            loaded_normal_scenarios=(1,),
            loaded_disaster_scenarios=(scenario_id,),
        ),
        lines=lines,
        nodes=nodes,
        economics=EconomicParameters(
            cfix=0.0,
            ccons_sl=0.0,
            ccons_fa=0.0,
            ctrans=(0.0,),
            cpur=(0.0,),
            ccong=0.0,
            gamma=0.01,
            theta=20,
            pi_f=0.3,
            alpha_min=0.0,
            cunmet=DEFAULT_FROZEN_CONFIG.cunmet,
            annualize_normal_cost_by_365=True,
            annualize_disaster_cost_by_365=False,
            ctrans_mode="time_vector",
            power_unit="kW",
        ),
        ev=EVParameters(
            p_ev_rated_sl=float(raw["p_ev_rated_sl"]),
            p_ev_rated_fa=float(raw["p_ev_rated_fa"]),
            distance_km=((0.0,) * len(buses),),
            delta_t_hours=1.0,
            nbar_sl=10,
            nbar_fa=10,
        ),
        ambiguity=AmbiguityParameters(
            k_max_outages=len(line_pairs),
            p_bar=tuple(0.1 for _ in line_pairs),
            legacy_w=tuple(1.0 for _ in buses),
        ),
        normal_tensors=normal_tensors,
        disaster_tensors=disaster_tensors,
        index_map=build_index_map(
            buses=buses,
            lines=line_ids,
            regions=regions,
            normal_times=normal_times,
            disaster_times=disaster_times,
            normal_scenarios=(1,),
            disaster_scenarios=(scenario_id,),
        ),
        network_topology=topology,
        scenario_support=ScenarioSupport(
            normal=(1,),
            disaster=(scenario_id,),
            available_normal=(1,),
            available_disaster=(scenario_id,),
            declared_normal=(1,),
            declared_disaster=(scenario_id,),
            csv_support_by_file={},
            manifest_messages=(),
            selection_source="toy_fixture",
        ),
        critical_buses=critical_buses,
        is_critical_by_bus=is_critical_by_bus,
        cls_by_bus=cls_by_bus,
        runtime_directory="tests/fixtures",
        runtime_parameters={},
        metadata={},
    )


def _build_case(
    name: str,
    *,
    include_critical_buses: bool = True,
) -> tuple[CanonicalInstance, object, object, int, dict[str, object]]:
    raw = _load_fixture(name)
    instance = _build_toy_instance(raw, include_critical_buses=include_critical_buses)
    plan_raw = raw["plan"]
    plan = build_fixed_first_stage_plan(
        instance,
        z_by_bus={int(bus): int(value) for bus, value in plan_raw["z_by_bus"].items()},
        n_sl_by_bus={int(bus): int(value) for bus, value in plan_raw["n_sl_by_bus"].items()},
        n_fa_by_bus={int(bus): int(value) for bus, value in plan_raw["n_fa_by_bus"].items()},
    )
    outage = build_fixed_outage_vector(instance, by_line_id=raw["outage_by_line_id"])
    return instance, plan, outage, int(raw["scenario_id"]), raw["expected"]


def test_zero_demand_case_has_zero_objective_and_zero_flows(tmp_path: Path) -> None:
    """Case A: zero demand should yield zero objective and zero recourse actions."""

    instance, plan, outage, scenario_id, expected = _build_case("disaster_primal_zero.yaml")
    reference_model, solution = solve_disaster_primal_reference(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name="disaster_primal_zero",
    )
    dump_path = dump_model_artifact(reference_model, tmp_path / "disaster_primal_zero.lp")
    residual = build_residual_report(reference_model, solution)

    assert solution.objective_value == pytest.approx(float(expected["objective"]))
    assert all(value == pytest.approx(0.0) for value in solution.load_shedding_by_time_bus.values())
    assert all(value == pytest.approx(0.0) for value in solution.line_flow_by_time_line.values())
    assert dump_path.exists()
    assert residual.max_bound_violation <= 1e-9
    assert residual.max_eq27_active_balance_residual <= 1e-9
    assert residual.max_failed_line_flow_violation <= 1e-9


def test_shortage_case_matches_hand_checked_objective() -> None:
    """Case B: limited V2G under a failed line should leave the expected load shed."""

    instance, plan, outage, scenario_id, expected = _build_case("disaster_primal_shortage.yaml")
    reference_model, solution = solve_disaster_primal_reference(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name="disaster_primal_shortage",
    )
    residual = build_residual_report(reference_model, solution)

    assert solution.objective_value == pytest.approx(float(expected["objective"]))
    assert solution.load_shedding_by_time_bus[(1, 2)] == pytest.approx(float(expected["shed_bus_2"]))
    assert solution.discharge_slow_by_time_region_bus[(1, 1, 2)] == pytest.approx(
        float(expected["slow_discharge_bus_2"])
    )
    assert solution.line_flow_by_time_line[(1, str(expected["failed_line_id"]))] == pytest.approx(0.0)
    assert residual.max_eq27_active_balance_residual <= 1e-9


def test_critical_priority_case_preserves_critical_load_first() -> None:
    """Case C: critical-load penalties should prioritize serving the critical bus."""

    instance, plan, outage, scenario_id, expected = _build_case(
        "disaster_primal_critical_priority.yaml"
    )
    reference_model, solution = solve_disaster_primal_reference(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name="disaster_primal_critical_priority",
    )
    residual = build_residual_report(reference_model, solution)

    assert solution.objective_value == pytest.approx(float(expected["objective"]))
    assert solution.load_shedding_by_time_bus[(1, 2)] == pytest.approx(float(expected["shed_bus_2"]))
    assert solution.load_shedding_by_time_bus[(1, 3)] == pytest.approx(float(expected["shed_bus_3"]))
    assert solution.line_flow_by_time_line[(1, "line_02_03")] == pytest.approx(
        float(expected["flow_line_02_03"])
    )
    assert solution.load_shedding_by_time_bus[(1, 2)] < solution.load_shedding_by_time_bus[(1, 3)]
    assert residual.max_bound_violation <= 1e-9


def test_failed_line_case_forces_zero_flow_on_failed_branch() -> None:
    """Case D: Eq. (32) should force exactly zero flow on the failed line."""

    instance, plan, outage, scenario_id, expected = _build_case("disaster_primal_failed_line.yaml")
    reference_model, solution = solve_disaster_primal_reference(
        instance,
        plan=plan,
        outage=outage,
        scenario_id=scenario_id,
        model_name="disaster_primal_failed_line",
    )
    residual = build_residual_report(reference_model, solution)

    failed_line_id = str(expected["failed_line_id"])
    assert solution.objective_value == pytest.approx(float(expected["objective"]))
    assert solution.line_flow_by_time_line[(1, failed_line_id)] == pytest.approx(0.0)
    assert residual.max_failed_line_flow_violation <= 1e-9


def test_missing_critical_buses_fails_before_model_build() -> None:
    """Disaster-objective readiness must fail clearly without explicit critical buses."""

    instance, plan, outage, scenario_id, _ = _build_case(
        "disaster_primal_zero.yaml",
        include_critical_buses=False,
    )

    with pytest.raises(
        RuntimeDataValidationError,
        match="critical_buses is required for disaster-objective construction",
    ):
        build_disaster_primal_reference_model(
            instance,
            plan=plan,
            outage=outage,
            scenario_id=scenario_id,
        )
