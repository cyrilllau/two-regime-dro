"""Toy-case checks for the Round 06 first-stage and normal-operation builders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
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
from src.instance.validators import build_criticality_maps
from src.production.first_stage import build_first_stage_model
from src.production.normal_block import solve_first_stage_with_normal_operation_block


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def load_round_06_fixture(name: str) -> dict[str, object]:
    """Load a Round 06 JSON fixture stored with a `.yaml` extension."""

    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def build_round_06_toy_case(
    name: str,
) -> tuple[CanonicalInstance, int, dict[str, object]]:
    """Build one Round 06 toy canonical instance from a JSON fixture."""

    raw = load_round_06_fixture(name)
    buses = tuple(int(bus) for bus in raw["buses"])
    line_pairs = tuple((int(pair[0]), int(pair[1])) for pair in raw["lines"])
    line_ids = tuple(make_line_id(from_bus, to_bus) for from_bus, to_bus in line_pairs)
    regions = tuple(int(region) for region in raw["regions"])
    normal_times = tuple(int(time_id) for time_id in raw["normal_times"])
    scenario_id = int(raw["scenario_id"])
    critical_buses = tuple(int(bus) for bus in raw.get("critical_buses", ()))

    topology = build_network_topology(
        buses=buses,
        lines=tuple(
            Line(
                line_id=make_line_id(from_bus, to_bus),
                from_bus=from_bus,
                to_bus=to_bus,
            )
            for from_bus, to_bus in line_pairs
        ),
        root_bus=DEFAULT_FROZEN_CONFIG.root_bus,
    )
    is_critical_by_bus, cls_by_bus = build_criticality_maps(
        buses=buses,
        critical_buses=critical_buses,
        cls_critical=DEFAULT_FROZEN_CONFIG.disaster_objective.cls_critical,
        cls_noncritical=DEFAULT_FROZEN_CONFIG.disaster_objective.cls_noncritical,
    )

    candidate_buses = {int(bus) for bus in raw.get("candidate_buses", ())}
    nodes = tuple(
        NodeMeta(
            bus_id=bus,
            is_root=bus == DEFAULT_FROZEN_CONFIG.root_bus,
            candidate_for_evcs=bus in candidate_buses,
            is_critical=is_critical_by_bus[bus],
        )
        for bus in buses
    )

    line_r = tuple(float(value) for value in raw["line_r_pu"])
    line_x = tuple(float(value) for value in raw["line_x_pu"])
    line_p_max = tuple(float(value) for value in raw["line_p_max_kw"])
    line_q_max = tuple(float(value) for value in raw["line_q_max_kvar"])
    lines = tuple(
        LineData(
            line_id=make_line_id(from_bus, to_bus),
            from_bus=from_bus,
            to_bus=to_bus,
            resistance_pu=line_r[index],
            reactance_pu=line_x[index],
            p_max_kw=line_p_max[index],
            q_max_kvar=line_q_max[index],
        )
        for index, (from_bus, to_bus) in enumerate(line_pairs)
    )

    zero_normal_bus = {
        (scenario_id, time_id, bus): 0.0
        for time_id in normal_times
        for bus in buses
    }
    normal_p_load = dict(zero_normal_bus)
    normal_q_load = dict(zero_normal_bus)
    for row in raw.get("normal_loads", ()):
        key = (scenario_id, int(row["t"]), int(row["bus"]))
        normal_p_load[key] = float(row["p_kw"])
        normal_q_load[key] = float(row["q_kvar"])

    zero_normal_region = {
        (scenario_id, time_id, region): 0.0
        for time_id in normal_times
        for region in regions
    }
    normal_dev_ch_sl = dict(zero_normal_region)
    for row in raw.get("normal_dev_ch_sl", ()):
        normal_dev_ch_sl[(scenario_id, int(row["t"]), int(row["region"]))] = float(
            row["value"]
        )
    normal_dev_ch_fa = dict(zero_normal_region)
    for row in raw.get("normal_dev_ch_fa", ()):
        normal_dev_ch_fa[(scenario_id, int(row["t"]), int(row["region"]))] = float(
            row["value"]
        )

    normal_tensors = NormalScenarioTensor(
        support=(scenario_id,),
        p_load=normal_p_load,
        q_load=normal_q_load,
        dev_ch_sl=normal_dev_ch_sl,
        dev_ch_fa=normal_dev_ch_fa,
    )

    disaster_time = (1,)
    disaster_zero_bus = {
        (1, time_id, bus): 0.0
        for time_id in disaster_time
        for bus in buses
    }
    disaster_zero_region = {
        (1, time_id, region): 0.0
        for time_id in disaster_time
        for region in regions
    }
    disaster_tensors = DisasterScenarioTensor(
        support=(1,),
        p_load=disaster_zero_bus,
        dev_dis_sl=disaster_zero_region,
        dev_dis_fa=disaster_zero_region,
    )

    economics_raw = raw["economics"]
    ev_raw = raw["ev"]
    return (
        CanonicalInstance(
            frozen_config=DEFAULT_FROZEN_CONFIG,
            sets=CanonicalSets(
                buses=buses,
                line_ids=line_ids,
                regions=regions,
                normal_times=normal_times,
                disaster_times=disaster_time,
                declared_normal_scenarios=(scenario_id,),
                declared_disaster_scenarios=(1,),
                available_normal_scenarios=(scenario_id,),
                available_disaster_scenarios=(1,),
                loaded_normal_scenarios=(scenario_id,),
                loaded_disaster_scenarios=(1,),
            ),
            lines=lines,
            nodes=nodes,
            economics=EconomicParameters(
                cfix=float(economics_raw["cfix"]),
                ccons_sl=float(economics_raw["ccons_sl"]),
                ccons_fa=float(economics_raw["ccons_fa"]),
                ctrans=tuple(float(value) for value in economics_raw["ctrans"]),
                cpur=tuple(float(value) for value in economics_raw["cpur"]),
                ccong=float(economics_raw.get("ccong", 0.0)),
                gamma=float(economics_raw["gamma"]),
                theta=int(economics_raw["theta"]),
                pi_f=float(economics_raw.get("pi_f", 0.3)),
                alpha_min=float(economics_raw.get("alpha_min", 0.0)),
                cunmet=float(economics_raw["cunmet"]),
                annualize_normal_cost_by_365=bool(
                    economics_raw.get("annualize_normal_cost_by_365", False)
                ),
                annualize_disaster_cost_by_365=False,
                ctrans_mode="time_vector",
                power_unit="kW",
            ),
            ev=EVParameters(
                p_ev_rated_sl=float(ev_raw["p_ev_rated_sl"]),
                p_ev_rated_fa=float(ev_raw["p_ev_rated_fa"]),
                distance_km=tuple(
                    tuple(float(value) for value in row)
                    for row in raw["distance_km"]
                ),
                delta_t_hours=1.0,
                nbar_sl=int(ev_raw["nbar_sl"]),
                nbar_fa=int(ev_raw["nbar_fa"]),
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
                disaster_times=disaster_time,
                normal_scenarios=(scenario_id,),
                disaster_scenarios=(1,),
            ),
            network_topology=topology,
            scenario_support=ScenarioSupport(
                normal=(scenario_id,),
                disaster=(1,),
                available_normal=(scenario_id,),
                available_disaster=(1,),
                declared_normal=(scenario_id,),
                declared_disaster=(1,),
                csv_support_by_file={},
                manifest_messages=(),
                selection_source="toy_fixture",
            ),
            critical_buses=critical_buses,
            is_critical_by_bus=is_critical_by_bus,
            cls_by_bus=cls_by_bus,
            runtime_directory="tests/fixtures",
            runtime_parameters={
                "net": {
                    "Vmin": float(raw["vmin"]),
                    "Vmax": float(raw["vmax"]),
                }
            },
            metadata={"fixture_name": name},
        ),
        scenario_id,
        raw,
    )


def solve_round_06_toy_case(
    name: str,
):
    """Build and solve one Round 06 toy case."""

    instance, scenario_id, raw = build_round_06_toy_case(name)
    first_stage, first_stage_solution, normal_block, normal_solution = (
        solve_first_stage_with_normal_operation_block(
            instance,
            scenario_id=scenario_id,
            model_name=f"round_06_{name.replace('.yaml', '')}",
        )
    )
    return instance, first_stage, first_stage_solution, normal_block, normal_solution, raw


def test_t1_zero_demand_prefers_no_construction() -> None:
    """T1: zero demand should keep construction, assignment, and purchase at zero."""

    instance, scenario_id, raw = build_round_06_toy_case("first_stage_t1_zero_demand.yaml")
    first_stage_only = build_first_stage_model(
        instance,
        model_name="round_06_first_stage_toy",
        attach_objective=True,
    )
    dump_path = dump_model_artifact(first_stage_only, Path("/tmp/round_06_first_stage_toy.lp"))
    assert dump_path.exists()

    _, first_stage_solution, _, normal_solution = solve_first_stage_with_normal_operation_block(
        instance,
        scenario_id=scenario_id,
        model_name="round_06_t1_zero",
    )
    expected = raw["expected"]

    assert first_stage_solution.z_by_bus == {int(bus): int(value) for bus, value in expected["z_by_bus"].items()}
    assert first_stage_solution.n_sl_by_bus == {
        int(bus): int(value) for bus, value in expected["n_sl_by_bus"].items()
    }
    assert first_stage_solution.n_fa_by_bus == {
        int(bus): int(value) for bus, value in expected["n_fa_by_bus"].items()
    }
    assert normal_solution.normal_objective_value == pytest.approx(float(expected["objective"]))
    assert all(value == pytest.approx(0.0) for value in normal_solution.substation_active_by_time.values())
    assert all(value == pytest.approx(0.0) for value in normal_solution.unmet_slow_by_time_region.values())
    assert all(value == pytest.approx(0.0) for value in normal_solution.unmet_fast_by_time_region.values())


def test_t2_minimum_three_rule_binds_when_one_station_opens() -> None:
    """T2: 20 kW slow demand needs only two slow chargers physically, so Eq. (11) should force three."""

    _, _, first_stage_solution, _, normal_solution, raw = solve_round_06_toy_case(
        "first_stage_t2_minimum_three.yaml"
    )
    expected = raw["expected"]

    assert first_stage_solution.z_by_bus[2] == 1
    assert first_stage_solution.n_sl_by_bus[2] == 3
    assert first_stage_solution.n_fa_by_bus[2] == 0
    assert first_stage_solution.n_sl_by_bus[2] + first_stage_solution.n_fa_by_bus[2] == 3
    assert normal_solution.charge_slow_by_time_region_bus[(1, 1, 2)] == pytest.approx(
        float(expected["slow_served"])
    )
    assert normal_solution.unmet_slow_by_time_region[(1, 1)] == pytest.approx(
        float(expected["slow_unmet"])
    )
    assert normal_solution.objective_value == pytest.approx(float(expected["objective"]))


def test_t3_fast_and_slow_capacities_remain_separated() -> None:
    """T3: one fast charger plus two slow chargers should beat any all-slow build."""

    _, _, first_stage_solution, _, normal_solution, raw = solve_round_06_toy_case(
        "normal_block_t3_fast_slow.yaml"
    )
    expected = raw["expected"]

    assert first_stage_solution.n_sl_by_bus[2] == int(expected["n_sl_by_bus"]["2"])
    assert first_stage_solution.n_fa_by_bus[2] == int(expected["n_fa_by_bus"]["2"])
    assert normal_solution.charge_slow_by_time_region_bus[(1, 1, 2)] == pytest.approx(
        float(expected["slow_served"])
    )
    assert normal_solution.charge_fast_by_time_region_bus[(1, 1, 2)] == pytest.approx(
        float(expected["fast_served"])
    )
    assert normal_solution.unmet_slow_by_time_region[(1, 1)] == pytest.approx(
        float(expected["slow_unmet"])
    )
    assert normal_solution.unmet_fast_by_time_region[(1, 1)] == pytest.approx(
        float(expected["fast_unmet"])
    )
    assert normal_solution.objective_value == pytest.approx(float(expected["objective"]))


def test_t4_nearest_candidate_station_fills_first_under_distance_costs() -> None:
    """T4: bus 2 is closer and can serve 30 kW, so bus 3 should serve only the remaining 20 kW."""

    _, _, first_stage_solution, _, normal_solution, raw = solve_round_06_toy_case(
        "normal_block_t4_distance_preference.yaml"
    )
    expected = raw["expected"]

    assert first_stage_solution.z_by_bus[2] == 1
    assert first_stage_solution.z_by_bus[3] == 1
    assert first_stage_solution.n_sl_by_bus[2] == 3
    assert first_stage_solution.n_sl_by_bus[3] == 3
    assert normal_solution.charge_slow_by_time_region_bus[(1, 1, 2)] == pytest.approx(
        float(expected["slow_served_by_bus"]["2"])
    )
    assert normal_solution.charge_slow_by_time_region_bus[(1, 1, 3)] == pytest.approx(
        float(expected["slow_served_by_bus"]["3"])
    )
    assert normal_solution.unmet_slow_by_time_region[(1, 1)] == pytest.approx(
        float(expected["slow_unmet"])
    )
    assert normal_solution.objective_value == pytest.approx(float(expected["objective"]))


def test_t5_line_limit_forces_unmet_demand_even_with_station_capacity() -> None:
    """T5: the station can host 150 kW slow charging, but the single feeder line caps service at 50 kW."""

    _, _, first_stage_solution, _, normal_solution, raw = solve_round_06_toy_case(
        "normal_block_t5_network_bottleneck.yaml"
    )
    expected = raw["expected"]
    line_id = make_line_id(1, 2)

    assert first_stage_solution.n_sl_by_bus[2] == int(expected["n_sl_by_bus"]["2"])
    assert normal_solution.charge_slow_by_time_region_bus[(1, 1, 2)] == pytest.approx(
        float(expected["slow_served"])
    )
    assert normal_solution.unmet_slow_by_time_region[(1, 1)] == pytest.approx(
        float(expected["slow_unmet"])
    )
    assert normal_solution.active_flow_by_time_line[(1, line_id)] == pytest.approx(
        float(expected["line_flow"])
    )
    assert normal_solution.objective_value == pytest.approx(float(expected["objective"]))
