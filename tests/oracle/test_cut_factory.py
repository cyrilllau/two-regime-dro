"""Oracle tests for the Round 08 structured cut factory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
from src.production.cut_factory import PAPER_DUAL_SIMPLEX_METHOD, generate_structured_cut
from src.production.master_problem import RestrictedMasterCut
from src.reference.disaster_primal_ref import (
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def load_round_08_fixture(name: str) -> dict[str, object]:
    """Load a Round 08 JSON fixture stored with a `.yaml` extension."""

    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def build_round_08_case(
    name: str,
) -> tuple[
    CanonicalInstance,
    tuple[RestrictedMasterCut, ...] | None,
    object | None,
    object | None,
    dict[str, object],
]:
    """Build one Round 08 toy canonical instance, optional initial cuts, and source point."""

    raw = load_round_08_fixture(name)
    buses = tuple(int(bus) for bus in raw["buses"])
    line_pairs = tuple((int(pair[0]), int(pair[1])) for pair in raw["lines"])
    line_ids = tuple(make_line_id(from_bus, to_bus) for from_bus, to_bus in line_pairs)
    regions = tuple(int(region) for region in raw["regions"])
    normal_times = tuple(int(time_id) for time_id in raw["normal_times"])
    disaster_times = tuple(int(time_id) for time_id in raw["disaster_times"])
    normal_scenarios = tuple(int(scenario_id) for scenario_id in raw["normal_scenarios"])
    disaster_scenarios = tuple(int(scenario_id) for scenario_id in raw["disaster_scenarios"])
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
    lines = tuple(
        LineData(
            line_id=make_line_id(from_bus, to_bus),
            from_bus=from_bus,
            to_bus=to_bus,
            resistance_pu=float(raw["line_r_pu"][index]),
            reactance_pu=float(raw["line_x_pu"][index]),
            p_max_kw=float(raw["line_p_max_kw"][index]),
            q_max_kvar=float(raw["line_q_max_kvar"][index]),
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
        normal_q_load[key] = float(row.get("q_kvar", 0.0))

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

    disaster_zero_bus = {
        (scenario_id, time_id, bus): 0.0
        for scenario_id in disaster_scenarios
        for time_id in disaster_times
        for bus in buses
    }
    disaster_p_load = dict(disaster_zero_bus)
    for row in raw.get("disaster_loads", ()):
        disaster_p_load[
            (int(row["scenario"]), int(row["t"]), int(row["bus"]))
        ] = float(row["p_kw"])

    disaster_zero_region = {
        (scenario_id, time_id, region): 0.0
        for scenario_id in disaster_scenarios
        for time_id in disaster_times
        for region in regions
    }
    disaster_dev_dis_sl = dict(disaster_zero_region)
    for row in raw.get("disaster_dev_dis_sl", ()):
        disaster_dev_dis_sl[
            (int(row["scenario"]), int(row["t"]), int(row["region"]))
        ] = float(row["value"])
    disaster_dev_dis_fa = dict(disaster_zero_region)
    for row in raw.get("disaster_dev_dis_fa", ()):
        disaster_dev_dis_fa[
            (int(row["scenario"]), int(row["t"]), int(row["region"]))
        ] = float(row["value"])

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
            declared_disaster_scenarios=disaster_scenarios,
            available_normal_scenarios=normal_scenarios,
            available_disaster_scenarios=disaster_scenarios,
            loaded_normal_scenarios=normal_scenarios,
            loaded_disaster_scenarios=disaster_scenarios,
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
        normal_tensors=NormalScenarioTensor(
            support=normal_scenarios,
            p_load=normal_p_load,
            q_load=normal_q_load,
            dev_ch_sl=normal_dev_ch_sl,
            dev_ch_fa=normal_dev_ch_fa,
        ),
        disaster_tensors=DisasterScenarioTensor(
            support=disaster_scenarios,
            p_load=disaster_p_load,
            dev_dis_sl=disaster_dev_dis_sl,
            dev_dis_fa=disaster_dev_dis_fa,
        ),
        index_map=build_index_map(
            buses=buses,
            lines=line_ids,
            regions=regions,
            normal_times=normal_times,
            disaster_times=disaster_times,
            normal_scenarios=normal_scenarios,
            disaster_scenarios=disaster_scenarios,
        ),
        network_topology=topology,
        scenario_support=ScenarioSupport(
            normal=normal_scenarios,
            disaster=disaster_scenarios,
            available_normal=normal_scenarios,
            available_disaster=disaster_scenarios,
            declared_normal=normal_scenarios,
            declared_disaster=disaster_scenarios,
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
                "Vmin": float(raw["vmin"]) if "vmin" in raw else 0.9,
                "Vmax": float(raw["vmax"]) if "vmax" in raw else 1.1,
            }
        },
        metadata={"fixture_name": name},
    )

    initial_cuts_raw = raw.get("initial_cuts", ())
    initial_cuts = tuple(
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
        for cut_row in initial_cuts_raw
    )

    source_plan = None
    if "source_plan" in raw:
        plan_raw = raw["source_plan"]
        source_plan = build_fixed_first_stage_plan(
            instance,
            z_by_bus={int(bus): int(value) for bus, value in plan_raw["z_by_bus"].items()},
            n_sl_by_bus={int(bus): int(value) for bus, value in plan_raw["n_sl_by_bus"].items()},
            n_fa_by_bus={int(bus): int(value) for bus, value in plan_raw["n_fa_by_bus"].items()},
        )

    source_outage = None
    if "source_outage_by_line_id" in raw:
        source_outage = build_fixed_outage_vector(
            instance,
            by_line_id={str(line_id): int(value) for line_id, value in raw["source_outage_by_line_id"].items()},
        )

    return instance, (initial_cuts or None), source_plan, source_outage, raw


def test_cut_factory_aggregates_samplewise_paper_duals_into_structured_cut() -> None:
    """The cut factory should preserve the paper-dual blocks without flattening."""

    instance, _, source_plan, source_outage, raw = build_round_08_case(
        "cut_factory_generated_efficacy.yaml"
    )
    generated = generate_structured_cut(
        instance,
        plan=source_plan,
        outage=source_outage,
        cut_id="tiny_generated_cut",
        provenance="round_08_oracle_test",
    )

    expected = raw["expected_generated_cut"]
    assert generated.simplex_method == PAPER_DUAL_SIMPLEX_METHOD
    assert generated.cut.cut_id == "tiny_generated_cut"
    assert generated.cut.is_trivial() is False
    assert generated.audit.provenance == "round_08_oracle_test"
    assert generated.audit.source_outage.by_line_id == source_outage.by_line_id
    assert generated.audit.source_plan.n_sl_by_bus == source_plan.n_sl_by_bus
    assert generated.cut.beta == pytest.approx(float(expected["beta"]))
    assert generated.cut.gamma_n_sl_by_bus[2] == pytest.approx(
        float(expected["gamma_n_sl_by_bus"]["2"])
    )
    assert generated.cut.phi_by_line_id["line_01_02"] == pytest.approx(
        float(expected["phi_by_line_id"]["line_01_02"])
    )
    assert generated.audit.samplewise_objective_by_scenario[1] == pytest.approx(
        float(expected["samplewise_objective"])
    )
    samplewise = generated.audit.samplewise_decompositions_by_scenario[1]
    assert samplewise.beta_b == pytest.approx(generated.cut.beta)
    assert samplewise.gamma_n_sl_by_bus[2] == pytest.approx(
        generated.cut.gamma_n_sl_by_bus[2]
    )
    assert samplewise.phi_by_line_id["line_01_02"] == pytest.approx(
        generated.cut.phi_by_line_id["line_01_02"]
    )
