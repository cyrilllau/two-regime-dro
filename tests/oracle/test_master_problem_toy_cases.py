"""Toy-case checks for the Round 07 restricted master problem builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import build_master_problem_residual_report
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
from src.production.master_problem import (
    RestrictedMasterCut,
    solve_master_problem,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def load_round_07_fixture(name: str) -> dict[str, object]:
    """Load a Round 07 JSON fixture stored with a `.yaml` extension."""

    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def build_round_07_toy_case(
    name: str,
) -> tuple[CanonicalInstance, tuple[RestrictedMasterCut, ...] | None, dict[str, object]]:
    """Build one Round 07 toy canonical instance and its fixed cut family."""

    raw = load_round_07_fixture(name)
    buses = tuple(int(bus) for bus in raw["buses"])
    line_pairs = tuple((int(pair[0]), int(pair[1])) for pair in raw["lines"])
    line_ids = tuple(make_line_id(from_bus, to_bus) for from_bus, to_bus in line_pairs)
    regions = tuple(int(region) for region in raw["regions"])
    normal_times = tuple(int(time_id) for time_id in raw["normal_times"])
    normal_scenarios = tuple(int(scenario_id) for scenario_id in raw["normal_scenarios"])
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
        for scenario_id in normal_scenarios
        for time_id in normal_times
        for bus in buses
    }
    normal_p_load = dict(zero_normal_bus)
    normal_q_load = dict(zero_normal_bus)
    for row in raw.get("normal_loads", ()):
        key = (int(row["scenario"]), int(row["t"]), int(row["bus"]))
        normal_p_load[key] = float(row["p_kw"])
        normal_q_load[key] = float(row["q_kvar"])

    zero_normal_region = {
        (scenario_id, time_id, region): 0.0
        for scenario_id in normal_scenarios
        for time_id in normal_times
        for region in regions
    }
    normal_dev_ch_sl = dict(zero_normal_region)
    for row in raw.get("normal_dev_ch_sl", ()):
        normal_dev_ch_sl[
            (int(row["scenario"]), int(row["t"]), int(row["region"]))
        ] = float(row["value"])
    normal_dev_ch_fa = dict(zero_normal_region)
    for row in raw.get("normal_dev_ch_fa", ()):
        normal_dev_ch_fa[
            (int(row["scenario"]), int(row["t"]), int(row["region"]))
        ] = float(row["value"])

    normal_tensors = NormalScenarioTensor(
        support=normal_scenarios,
        p_load=normal_p_load,
        q_load=normal_q_load,
        dev_ch_sl=normal_dev_ch_sl,
        dev_ch_fa=normal_dev_ch_fa,
    )

    disaster_times = (1,)
    disaster_zero_bus = {
        (1, time_id, bus): 0.0
        for time_id in disaster_times
        for bus in buses
    }
    disaster_zero_region = {
        (1, time_id, region): 0.0
        for time_id in disaster_times
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
    ambig_raw = raw["ambig"]
    instance = CanonicalInstance(
        frozen_config=DEFAULT_FROZEN_CONFIG,
        sets=CanonicalSets(
            buses=buses,
            line_ids=line_ids,
            regions=regions,
            normal_times=normal_times,
            disaster_times=disaster_times,
            declared_normal_scenarios=normal_scenarios,
            declared_disaster_scenarios=(1,),
            available_normal_scenarios=normal_scenarios,
            available_disaster_scenarios=(1,),
            loaded_normal_scenarios=normal_scenarios,
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
            pi_f=float(economics_raw["pi_f"]),
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
            k_max_outages=int(ambig_raw["k_max_outages"]),
            p_bar=tuple(float(value) for value in ambig_raw["p_bar"]),
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
            normal_scenarios=normal_scenarios,
            disaster_scenarios=(1,),
        ),
        network_topology=topology,
        scenario_support=ScenarioSupport(
            normal=normal_scenarios,
            disaster=(1,),
            available_normal=normal_scenarios,
            available_disaster=(1,),
            declared_normal=normal_scenarios,
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
    )

    cut_rows = raw.get("cuts", ())
    cuts = tuple(
        RestrictedMasterCut(
            cut_id=str(cut_row["cut_id"]),
            beta=float(cut_row["beta"]),
            gamma_z_by_bus={
                int(bus): float(value)
                for bus, value in cut_row.get("gamma_z_by_bus", {}).items()
            },
            gamma_n_sl_by_bus={
                int(bus): float(value)
                for bus, value in cut_row.get("gamma_n_sl_by_bus", {}).items()
            },
            gamma_n_fa_by_bus={
                int(bus): float(value)
                for bus, value in cut_row.get("gamma_n_fa_by_bus", {}).items()
            },
            phi_by_line_id={
                str(line_id): float(value)
                for line_id, value in cut_row.get("phi_by_line_id", {}).items()
            },
        )
        for cut_row in cut_rows
    )
    return instance, (cuts or None), raw


def solve_round_07_toy_case(
    name: str,
):
    """Build and solve one Round 07 toy restricted master problem."""

    instance, cuts, raw = build_round_07_toy_case(name)
    master_problem, solution = solve_master_problem(
        instance,
        cuts=cuts,
        model_name=f"round_07_{name.replace('.yaml', '')}",
    )
    residual = build_master_problem_residual_report(master_problem, solution)
    return instance, master_problem, solution, residual, raw


def test_trivial_cut_zero_demand_sanity() -> None:
    """No normal demand plus the trivial cut should yield the zero plan and zero objective."""

    instance, master_problem, solution, residual, raw = solve_round_07_toy_case(
        "master_problem_trivial_zero_demand.yaml"
    )
    dump_path = dump_model_artifact(master_problem, Path("/tmp/round_07_toy_master.lp"))

    assert dump_path.exists()
    assert master_problem.cuts[0].cut_id == "trivial_cut"
    assert solution.model_status == "OPTIMAL"
    assert solution.objective_value == pytest.approx(float(raw["expected"]["objective"]))
    assert solution.alpha_value == pytest.approx(0.0)
    assert all(value == pytest.approx(0.0) for value in solution.lambda_by_line_id.values())
    assert all(value == 0 for value in solution.first_stage_solution.z_by_bus.values())
    assert all(value == 0 for value in solution.first_stage_solution.n_sl_by_bus.values())
    assert all(value == 0 for value in solution.first_stage_solution.n_fa_by_bus.values())
    assert residual.max_cut_support_violation <= 1e-8
    assert residual.max_u_link_violation <= 1e-8
    assert residual.objective_reconstruction_gap <= 1e-8
    assert master_problem.ordered_buses == instance.sets.buses
    assert master_problem.ordered_line_ids == instance.sets.line_ids


def test_normal_expectation_averaging_sanity() -> None:
    """Two normal scenarios should enter the master objective through the required average."""

    _, _, solution, residual, raw = solve_round_07_toy_case(
        "master_problem_normal_averaging.yaml"
    )

    expected = raw["expected"]
    assert solution.model_status == "OPTIMAL"
    assert solution.objective_value == pytest.approx(float(expected["objective"]))
    assert solution.first_stage_solution.z_by_bus[2] == int(expected["z2"])
    assert solution.first_stage_solution.n_sl_by_bus[2] == int(expected["n_sl2"])
    assert solution.normal_cost_by_scenario[1] == pytest.approx(
        float(expected["scenario_1_normal_cost"])
    )
    assert solution.normal_cost_by_scenario[2] == pytest.approx(
        float(expected["scenario_2_normal_cost"])
    )
    assert solution.unweighted_average_normal_cost_value == pytest.approx(
        float(expected["unweighted_average_normal_cost"])
    )
    assert solution.averaged_normal_cost_value == pytest.approx(
        float(expected["weighted_normal_term"])
    )
    assert solution.alpha_value == pytest.approx(0.0)
    assert all(value == pytest.approx(0.0) for value in solution.lambda_by_line_id.values())
    assert residual.max_cut_support_violation <= 1e-8
    assert residual.max_u_link_violation <= 1e-8


def test_gamma_driven_siting_incentive_cut_can_outweigh_construction() -> None:
    """A positive `gamma_z` cut should be able to induce site opening in the RMP."""

    _, _, solution, residual, raw = solve_round_07_toy_case(
        "master_problem_gamma_incentive.yaml"
    )

    expected = raw["expected"]
    assert solution.model_status == "OPTIMAL"
    assert solution.objective_value == pytest.approx(float(expected["objective"]))
    assert solution.first_stage_solution.z_by_bus[2] == int(expected["z2"])
    assert solution.first_stage_solution.n_sl_by_bus[2] == int(expected["n_sl2"])
    assert solution.first_stage_solution.n_fa_by_bus[2] == int(expected["n_fa2"])
    assert solution.alpha_value == pytest.approx(float(expected["alpha"]))
    assert residual.cut_support_slacks["gamma_site"] == pytest.approx(0.0)
    assert residual.max_cut_support_violation <= 1e-8
    assert residual.max_u_link_violation <= 1e-8


def test_phi_lambda_support_sanity_matches_one_line_budget_interpretation() -> None:
    """A one-line cut with positive `phi` should choose `lambda` consistently with Eq. (39)."""

    _, _, solution, residual, raw = solve_round_07_toy_case(
        "master_problem_phi_support.yaml"
    )

    line_id = str(raw["expected"]["line_id"])
    assert solution.model_status == "OPTIMAL"
    assert solution.objective_value == pytest.approx(float(raw["expected"]["objective"]))
    assert solution.alpha_value == pytest.approx(float(raw["expected"]["alpha"]))
    assert solution.lambda_by_line_id[line_id] == pytest.approx(
        float(raw["expected"]["lambda_value"])
    )
    assert solution.s_by_cut_id["phi_support"] == pytest.approx(0.0)
    assert solution.u_by_cut_id_and_line_id[("phi_support", line_id)] == pytest.approx(0.0)
    assert residual.cut_support_slacks["phi_support"] == pytest.approx(0.0)
    assert residual.u_link_slacks[f"phi_support:{line_id}"] == pytest.approx(0.0)
    assert residual.max_cut_support_violation <= 1e-8
    assert residual.max_u_link_violation <= 1e-8
