"""Runtime adapter that composes raw loading, manifest inspection, and selection."""

from __future__ import annotations

from itertools import product
from pathlib import Path
from typing import Any, Sequence

from src.contracts.freeze import DEFAULT_FROZEN_CONFIG, FrozenConfig
from src.contracts.naming import make_line_id
from src.instance.canonical_instance import CanonicalInstance, ScenarioSupport
from src.instance.indexer import build_index_map
from src.instance.manifest import RuntimeSupportManifest, inspect_available_support
from src.instance.network_topology import Line, build_network_topology
from src.instance.raw_package import RawDataPackage, load_raw_data_package
from src.instance.schema import (
    AmbiguityParameters,
    CanonicalSets,
    DisasterScenarioTensor,
    EconomicParameters,
    EVParameters,
    LineData,
    NodeMeta,
    NormalScenarioTensor,
    ObjectiveMultipliers,
)
from src.instance.selection import RuntimeSelection, resolve_runtime_selection
from src.instance.validators import (
    RuntimeDataValidationError,
    assert_valid_canonical_instance,
    build_criticality_maps,
    coerce_int_tuple,
    validate_distance_matrix_shape,
    validate_line_parameter_lengths,
    validate_tensor_cardinality,
)


def _parse_int(row: dict[str, str], key: str, *, path: Path, line_no: int) -> int:
    try:
        return int(row[key])
    except (KeyError, ValueError) as exc:
        raise RuntimeDataValidationError(
            f"{path}:{line_no} has invalid integer field {key!r}: {row.get(key)!r}."
        ) from exc


def _parse_float(row: dict[str, str], key: str, *, path: Path, line_no: int) -> float:
    try:
        return float(row[key])
    except (KeyError, ValueError) as exc:
        raise RuntimeDataValidationError(
            f"{path}:{line_no} has invalid numeric field {key!r}: {row.get(key)!r}."
        ) from exc


def _insert_unique(
    target: dict[tuple[int, int, int], float],
    *,
    key: tuple[int, int, int],
    value: float,
    path: Path,
    line_no: int,
    tensor_name: str,
) -> None:
    if key in target:
        raise RuntimeDataValidationError(
            f"{path}:{line_no} duplicates canonical key {key} in {tensor_name}."
        )
    target[key] = value


def _normalize_dense_tensor(
    *,
    support: tuple[int, ...],
    times: tuple[int, ...],
    entities: tuple[int, ...],
    sparse: dict[tuple[int, int, int], float],
) -> dict[tuple[int, int, int], float]:
    return {
        (scenario, time_index, entity): float(sparse.get((scenario, time_index, entity), 0.0))
        for scenario, time_index, entity in product(support, times, entities)
    }


def _build_lines(parameters: dict[str, Any]) -> tuple[LineData, ...]:
    sets_raw = parameters["sets"]
    net_raw = parameters["net"]
    ambig_raw = parameters["ambig"]
    line_pairs = [tuple(pair) for pair in sets_raw["lines"]]

    validate_line_parameter_lengths(
        line_count=len(line_pairs),
        rline=net_raw["Rline"],
        xline=net_raw["Xline"],
        pmax=net_raw["Pmax"],
        qmax=net_raw["Qmax"],
        p_bar=ambig_raw["p_bar"],
    )

    lines: list[LineData] = []
    for (from_bus, to_bus), resistance, reactance, p_max, q_max in zip(
        line_pairs,
        net_raw["Rline"],
        net_raw["Xline"],
        net_raw["Pmax"],
        net_raw["Qmax"],
    ):
        lines.append(
            LineData(
                line_id=make_line_id(from_bus, to_bus),
                from_bus=from_bus,
                to_bus=to_bus,
                resistance_pu=float(resistance),
                reactance_pu=float(reactance),
                p_max_kw=float(p_max),
                q_max_kvar=float(q_max),
            )
        )
    return tuple(lines)


def _build_economics(parameters: dict[str, Any], frozen_config: FrozenConfig) -> EconomicParameters:
    econ_raw = parameters["econ"]
    objective_multipliers_raw = parameters.get("objective_multipliers", {})
    if not isinstance(objective_multipliers_raw, dict):
        raise RuntimeDataValidationError("objective_multipliers must be an object when provided.")
    try:
        objective_multipliers = ObjectiveMultipliers(
            cons=float(objective_multipliers_raw.get("cons", 1.0)),
            normal=float(objective_multipliers_raw.get("normal", 1.0)),
            disaster=float(objective_multipliers_raw.get("disaster", 1.0)),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeDataValidationError(str(exc)) from exc
    return EconomicParameters(
        cfix=float(econ_raw["Cfix"]),
        ccons_sl=float(econ_raw["Ccons_sl"]),
        ccons_fa=float(econ_raw["Ccons_fa"]),
        ctrans=tuple(float(value) for value in econ_raw["Ctrans"]),
        cpur=tuple(float(value) for value in econ_raw["Cpur"]),
        ccong=float(econ_raw["Ccong"]),
        gamma=float(econ_raw["gamma"]),
        theta=int(econ_raw["theta"]),
        pi_f=float(econ_raw["pi_f"]),
        alpha_min=float(econ_raw.get("alpha_min", 0.0)),
        cunmet=frozen_config.economics.cunmet,
        annualize_normal_cost_by_365=frozen_config.economics.annualize_normal_cost_by_365,
        annualize_disaster_cost_by_365=frozen_config.economics.annualize_disaster_cost_by_365,
        ctrans_mode=frozen_config.economics.ctrans_mode,
        power_unit=frozen_config.economics.power_unit,
        objective_multipliers=objective_multipliers,
    )


def _build_ev(parameters: dict[str, Any]) -> EVParameters:
    ev_raw = parameters["ev"]
    sets_raw = parameters["sets"]
    buses = coerce_int_tuple(sets_raw["buses"], field_name="sets.buses")
    regions = coerce_int_tuple(sets_raw["regions"], field_name="sets.regions")
    distance = tuple(tuple(float(value) for value in row) for row in ev_raw["D"])
    validate_distance_matrix_shape(distance, region_count=len(regions), bus_count=len(buses))
    return EVParameters(
        p_ev_rated_sl=float(ev_raw["P_EV_rated_sl"]),
        p_ev_rated_fa=float(ev_raw["P_EV_rated_fa"]),
        distance_km=distance,
        delta_t_hours=float(ev_raw["delta_t"]),
        nbar_sl=int(ev_raw["Nbar_sl"]),
        nbar_fa=int(ev_raw["Nbar_fa"]),
    )


def _build_ambiguity(parameters: dict[str, Any]) -> AmbiguityParameters:
    ambig_raw = parameters["ambig"]
    return AmbiguityParameters(
        k_max_outages=int(ambig_raw["K"]),
        p_bar=tuple(float(value) for value in ambig_raw["p_bar"]),
        legacy_w=tuple(float(value) for value in ambig_raw["w"]),
    )


def _build_normal_tensors(
    *,
    raw_package: RawDataPackage,
    buses: tuple[int, ...],
    regions: tuple[int, ...],
    normal_times: tuple[int, ...],
    selected_support: tuple[int, ...],
) -> NormalScenarioTensor:
    csv_paths = raw_package.schema.csv_paths()
    selected = set(selected_support)
    rows_load = raw_package.csv_rows_by_file["normal_load"]
    rows_slow = raw_package.csv_rows_by_file["normal_slow"]
    rows_fast = raw_package.csv_rows_by_file["normal_fast"]

    p_load_sparse: dict[tuple[int, int, int], float] = {}
    q_load_sparse: dict[tuple[int, int, int], float] = {}
    for line_no, row in enumerate(rows_load, start=2):
        scenario = _parse_int(row, "scenario_a", path=csv_paths["normal_load"], line_no=line_no)
        if scenario not in selected:
            continue
        time_index = _parse_int(row, "t", path=csv_paths["normal_load"], line_no=line_no)
        bus = _parse_int(row, "bus", path=csv_paths["normal_load"], line_no=line_no)
        if time_index not in normal_times:
            raise RuntimeDataValidationError(
                f"{csv_paths['normal_load']}:{line_no} references unknown normal time {time_index}."
            )
        if bus not in buses:
            raise RuntimeDataValidationError(
                f"{csv_paths['normal_load']}:{line_no} references unknown bus {bus}."
            )
        _insert_unique(
            p_load_sparse,
            key=(scenario, time_index, bus),
            value=_parse_float(row, "P_kW", path=csv_paths["normal_load"], line_no=line_no),
            path=csv_paths["normal_load"],
            line_no=line_no,
            tensor_name="normal P_Load",
        )
        _insert_unique(
            q_load_sparse,
            key=(scenario, time_index, bus),
            value=_parse_float(row, "Q_kvar", path=csv_paths["normal_load"], line_no=line_no),
            path=csv_paths["normal_load"],
            line_no=line_no,
            tensor_name="normal Q_Load",
        )

    dev_ch_sl_sparse: dict[tuple[int, int, int], float] = {}
    for line_no, row in enumerate(rows_slow, start=2):
        scenario = _parse_int(row, "scenario_a", path=csv_paths["normal_slow"], line_no=line_no)
        if scenario not in selected:
            continue
        time_index = _parse_int(row, "t", path=csv_paths["normal_slow"], line_no=line_no)
        region = _parse_int(row, "region", path=csv_paths["normal_slow"], line_no=line_no)
        if time_index not in normal_times:
            raise RuntimeDataValidationError(
                f"{csv_paths['normal_slow']}:{line_no} references unknown normal time {time_index}."
            )
        if region not in regions:
            raise RuntimeDataValidationError(
                f"{csv_paths['normal_slow']}:{line_no} references unknown region {region}."
            )
        _insert_unique(
            dev_ch_sl_sparse,
            key=(scenario, time_index, region),
            value=_parse_float(
                row,
                "DEV_ch_sl_kW",
                path=csv_paths["normal_slow"],
                line_no=line_no,
            ),
            path=csv_paths["normal_slow"],
            line_no=line_no,
            tensor_name="normal DEV_ch_sl",
        )

    dev_ch_fa_sparse: dict[tuple[int, int, int], float] = {}
    for line_no, row in enumerate(rows_fast, start=2):
        scenario = _parse_int(row, "scenario_a", path=csv_paths["normal_fast"], line_no=line_no)
        if scenario not in selected:
            continue
        time_index = _parse_int(row, "t", path=csv_paths["normal_fast"], line_no=line_no)
        region = _parse_int(row, "region", path=csv_paths["normal_fast"], line_no=line_no)
        if time_index not in normal_times:
            raise RuntimeDataValidationError(
                f"{csv_paths['normal_fast']}:{line_no} references unknown normal time {time_index}."
            )
        if region not in regions:
            raise RuntimeDataValidationError(
                f"{csv_paths['normal_fast']}:{line_no} references unknown region {region}."
            )
        _insert_unique(
            dev_ch_fa_sparse,
            key=(scenario, time_index, region),
            value=_parse_float(
                row,
                "DEV_ch_fa_kW",
                path=csv_paths["normal_fast"],
                line_no=line_no,
            ),
            path=csv_paths["normal_fast"],
            line_no=line_no,
            tensor_name="normal DEV_ch_fa",
        )

    p_load = _normalize_dense_tensor(
        support=selected_support,
        times=normal_times,
        entities=buses,
        sparse=p_load_sparse,
    )
    q_load = _normalize_dense_tensor(
        support=selected_support,
        times=normal_times,
        entities=buses,
        sparse=q_load_sparse,
    )
    dev_ch_sl = _normalize_dense_tensor(
        support=selected_support,
        times=normal_times,
        entities=regions,
        sparse=dev_ch_sl_sparse,
    )
    dev_ch_fa = _normalize_dense_tensor(
        support=selected_support,
        times=normal_times,
        entities=regions,
        sparse=dev_ch_fa_sparse,
    )

    expected_bus_entries = len(selected_support) * len(normal_times) * len(buses)
    expected_region_entries = len(selected_support) * len(normal_times) * len(regions)
    validate_tensor_cardinality(
        tensor_name="normal P_Load",
        actual_count=len(p_load),
        expected_count=expected_bus_entries,
    )
    validate_tensor_cardinality(
        tensor_name="normal Q_Load",
        actual_count=len(q_load),
        expected_count=expected_bus_entries,
    )
    validate_tensor_cardinality(
        tensor_name="normal DEV_ch_sl",
        actual_count=len(dev_ch_sl),
        expected_count=expected_region_entries,
    )
    validate_tensor_cardinality(
        tensor_name="normal DEV_ch_fa",
        actual_count=len(dev_ch_fa),
        expected_count=expected_region_entries,
    )
    return NormalScenarioTensor(
        support=selected_support,
        p_load=p_load,
        q_load=q_load,
        dev_ch_sl=dev_ch_sl,
        dev_ch_fa=dev_ch_fa,
    )


def _build_disaster_tensors(
    *,
    raw_package: RawDataPackage,
    buses: tuple[int, ...],
    regions: tuple[int, ...],
    disaster_times: tuple[int, ...],
    selected_support: tuple[int, ...],
) -> DisasterScenarioTensor:
    csv_paths = raw_package.schema.csv_paths()
    selected = set(selected_support)
    rows_load = raw_package.csv_rows_by_file["disaster_load"]
    rows_slow = raw_package.csv_rows_by_file["disaster_slow"]
    rows_fast = raw_package.csv_rows_by_file["disaster_fast"]

    p_load_sparse: dict[tuple[int, int, int], float] = {}
    for line_no, row in enumerate(rows_load, start=2):
        scenario = _parse_int(row, "scenario_b", path=csv_paths["disaster_load"], line_no=line_no)
        if scenario not in selected:
            continue
        time_index = _parse_int(row, "ts", path=csv_paths["disaster_load"], line_no=line_no)
        bus = _parse_int(row, "bus", path=csv_paths["disaster_load"], line_no=line_no)
        if time_index not in disaster_times:
            raise RuntimeDataValidationError(
                f"{csv_paths['disaster_load']}:{line_no} references unknown disaster time {time_index}."
            )
        if bus not in buses:
            raise RuntimeDataValidationError(
                f"{csv_paths['disaster_load']}:{line_no} references unknown bus {bus}."
            )
        _insert_unique(
            p_load_sparse,
            key=(scenario, time_index, bus),
            value=_parse_float(row, "P_kW", path=csv_paths["disaster_load"], line_no=line_no),
            path=csv_paths["disaster_load"],
            line_no=line_no,
            tensor_name="disaster P_Load",
        )

    dev_dis_sl_sparse: dict[tuple[int, int, int], float] = {}
    for line_no, row in enumerate(rows_slow, start=2):
        scenario = _parse_int(row, "scenario_b", path=csv_paths["disaster_slow"], line_no=line_no)
        if scenario not in selected:
            continue
        time_index = _parse_int(row, "ts", path=csv_paths["disaster_slow"], line_no=line_no)
        region = _parse_int(row, "region", path=csv_paths["disaster_slow"], line_no=line_no)
        if time_index not in disaster_times:
            raise RuntimeDataValidationError(
                f"{csv_paths['disaster_slow']}:{line_no} references unknown disaster time {time_index}."
            )
        if region not in regions:
            raise RuntimeDataValidationError(
                f"{csv_paths['disaster_slow']}:{line_no} references unknown region {region}."
            )
        _insert_unique(
            dev_dis_sl_sparse,
            key=(scenario, time_index, region),
            value=_parse_float(
                row,
                "DEV_dis_sl_kW",
                path=csv_paths["disaster_slow"],
                line_no=line_no,
            ),
            path=csv_paths["disaster_slow"],
            line_no=line_no,
            tensor_name="disaster DEV_dis_sl",
        )

    dev_dis_fa_sparse: dict[tuple[int, int, int], float] = {}
    for line_no, row in enumerate(rows_fast, start=2):
        scenario = _parse_int(row, "scenario_b", path=csv_paths["disaster_fast"], line_no=line_no)
        if scenario not in selected:
            continue
        time_index = _parse_int(row, "ts", path=csv_paths["disaster_fast"], line_no=line_no)
        region = _parse_int(row, "region", path=csv_paths["disaster_fast"], line_no=line_no)
        if time_index not in disaster_times:
            raise RuntimeDataValidationError(
                f"{csv_paths['disaster_fast']}:{line_no} references unknown disaster time {time_index}."
            )
        if region not in regions:
            raise RuntimeDataValidationError(
                f"{csv_paths['disaster_fast']}:{line_no} references unknown region {region}."
            )
        _insert_unique(
            dev_dis_fa_sparse,
            key=(scenario, time_index, region),
            value=_parse_float(
                row,
                "DEV_dis_fa_kW",
                path=csv_paths["disaster_fast"],
                line_no=line_no,
            ),
            path=csv_paths["disaster_fast"],
            line_no=line_no,
            tensor_name="disaster DEV_dis_fa",
        )

    p_load = _normalize_dense_tensor(
        support=selected_support,
        times=disaster_times,
        entities=buses,
        sparse=p_load_sparse,
    )
    dev_dis_sl = _normalize_dense_tensor(
        support=selected_support,
        times=disaster_times,
        entities=regions,
        sparse=dev_dis_sl_sparse,
    )
    dev_dis_fa = _normalize_dense_tensor(
        support=selected_support,
        times=disaster_times,
        entities=regions,
        sparse=dev_dis_fa_sparse,
    )

    expected_bus_entries = len(selected_support) * len(disaster_times) * len(buses)
    expected_region_entries = len(selected_support) * len(disaster_times) * len(regions)
    validate_tensor_cardinality(
        tensor_name="disaster P_Load",
        actual_count=len(p_load),
        expected_count=expected_bus_entries,
    )
    validate_tensor_cardinality(
        tensor_name="disaster DEV_dis_sl",
        actual_count=len(dev_dis_sl),
        expected_count=expected_region_entries,
    )
    validate_tensor_cardinality(
        tensor_name="disaster DEV_dis_fa",
        actual_count=len(dev_dis_fa),
        expected_count=expected_region_entries,
    )
    return DisasterScenarioTensor(
        support=selected_support,
        p_load=p_load,
        dev_dis_sl=dev_dis_sl,
        dev_dis_fa=dev_dis_fa,
    )


def build_canonical_instance(
    *,
    raw_package: RawDataPackage,
    support_manifest: RuntimeSupportManifest,
    frozen_config: FrozenConfig = DEFAULT_FROZEN_CONFIG,
    critical_buses: Sequence[int] | None = None,
    selection: RuntimeSelection | None = None,
    expanded_mode: bool = False,
) -> CanonicalInstance:
    """Materialize a canonical instance for the selected scenario subset only."""

    resolved_selection = resolve_runtime_selection(
        manifest=support_manifest,
        frozen_config=frozen_config,
        selection=selection,
        expanded_mode=expanded_mode,
    )
    parameters = raw_package.raw_parameters
    sets_raw = parameters["sets"]
    buses = coerce_int_tuple(sets_raw["buses"], field_name="sets.buses")
    regions = coerce_int_tuple(sets_raw["regions"], field_name="sets.regions")
    normal_times = coerce_int_tuple(sets_raw["t_nor"], field_name="sets.t_nor")
    disaster_times = coerce_int_tuple(sets_raw["t_s"], field_name="sets.t_s")

    lines = _build_lines(parameters)
    line_ids = tuple(line.line_id for line in lines)
    is_critical_by_bus, cls_by_bus = build_criticality_maps(
        buses=buses,
        critical_buses=critical_buses,
        cls_critical=frozen_config.disaster_objective.cls_critical,
        cls_noncritical=frozen_config.disaster_objective.cls_noncritical,
    )
    nodes = tuple(
        NodeMeta(
            bus_id=bus,
            is_root=bus == frozen_config.root_bus,
            candidate_for_evcs=bus in frozen_config.candidate_buses_for(buses),
            is_critical=None if is_critical_by_bus is None else is_critical_by_bus[bus],
        )
        for bus in buses
    )
    normal_tensors = _build_normal_tensors(
        raw_package=raw_package,
        buses=buses,
        regions=regions,
        normal_times=normal_times,
        selected_support=resolved_selection.scenarios_a,
    )
    disaster_tensors = _build_disaster_tensors(
        raw_package=raw_package,
        buses=buses,
        regions=regions,
        disaster_times=disaster_times,
        selected_support=resolved_selection.scenarios_b,
    )
    topology = build_network_topology(
        buses=buses,
        root_bus=frozen_config.root_bus,
        lines=tuple(
            Line(
                line_id=line.line_id,
                from_bus=line.from_bus,
                to_bus=line.to_bus,
            )
            for line in lines
        ),
    )
    sets = CanonicalSets(
        buses=buses,
        line_ids=line_ids,
        regions=regions,
        normal_times=normal_times,
        disaster_times=disaster_times,
        declared_normal_scenarios=support_manifest.normal.declared_support,
        declared_disaster_scenarios=support_manifest.disaster.declared_support,
        available_normal_scenarios=support_manifest.normal.csv_support,
        available_disaster_scenarios=support_manifest.disaster.csv_support,
        loaded_normal_scenarios=resolved_selection.scenarios_a,
        loaded_disaster_scenarios=resolved_selection.scenarios_b,
    )
    scenario_support = ScenarioSupport(
        normal=resolved_selection.scenarios_a,
        disaster=resolved_selection.scenarios_b,
        available_normal=support_manifest.normal.csv_support,
        available_disaster=support_manifest.disaster.csv_support,
        declared_normal=support_manifest.normal.declared_support,
        declared_disaster=support_manifest.disaster.declared_support,
        csv_support_by_file=dict(raw_package.csv_support_by_file),
        manifest_messages=tuple(issue.message for issue in support_manifest.issues),
        selection_source=resolved_selection.source,
    )
    instance = CanonicalInstance(
        frozen_config=frozen_config,
        sets=sets,
        lines=lines,
        nodes=nodes,
        economics=_build_economics(parameters, frozen_config),
        ev=_build_ev(parameters),
        ambiguity=_build_ambiguity(parameters),
        normal_tensors=normal_tensors,
        disaster_tensors=disaster_tensors,
        index_map=build_index_map(
            buses=buses,
            lines=line_ids,
            regions=regions,
            normal_times=normal_times,
            disaster_times=disaster_times,
            normal_scenarios=resolved_selection.scenarios_a,
            disaster_scenarios=resolved_selection.scenarios_b,
        ),
        network_topology=topology,
        scenario_support=scenario_support,
        critical_buses=None if critical_buses is None else tuple(int(bus) for bus in critical_buses),
        is_critical_by_bus=is_critical_by_bus,
        cls_by_bus=cls_by_bus,
        runtime_directory=str(raw_package.schema.runtime_path),
        runtime_parameters=parameters,
        metadata={
            "support_manifest": support_manifest.as_dict(),
            "runtime_selection": {
                "scenarios_a": resolved_selection.scenarios_a,
                "scenarios_b": resolved_selection.scenarios_b,
                "source": resolved_selection.source,
            },
        },
    )
    assert_valid_canonical_instance(instance)
    return instance


def load_runtime_instance(
    runtime_dir: str | Path = "data/runtime_12",
    *,
    frozen_config: FrozenConfig = DEFAULT_FROZEN_CONFIG,
    critical_buses: Sequence[int] | None = None,
    selection: RuntimeSelection | None = None,
    expanded_mode: bool = False,
) -> CanonicalInstance:
    """Convenience loader that composes raw package, manifest, and selection."""

    raw_package = load_raw_data_package(runtime_dir)
    support_manifest = inspect_available_support(raw_package)
    return build_canonical_instance(
        raw_package=raw_package,
        support_manifest=support_manifest,
        frozen_config=frozen_config,
        critical_buses=critical_buses,
        selection=selection,
        expanded_mode=expanded_mode,
    )
