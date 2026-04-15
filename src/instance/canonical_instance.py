"""Canonical instance container and public loader entry points."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from src.contracts.freeze import DEFAULT_FROZEN_CONFIG, FrozenConfig
from src.instance.indexer import IndexMap
from src.instance.network_topology import NetworkTopology
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

if TYPE_CHECKING:
    from src.instance.selection import RuntimeSelection


@dataclass(frozen=True)
class ScenarioSupport:
    """Declared, available, and selected scenario-support metadata."""

    normal: tuple[int, ...] = field(default_factory=tuple)
    disaster: tuple[int, ...] = field(default_factory=tuple)
    available_normal: tuple[int, ...] = field(default_factory=tuple)
    available_disaster: tuple[int, ...] = field(default_factory=tuple)
    declared_normal: tuple[int, ...] = field(default_factory=tuple)
    declared_disaster: tuple[int, ...] = field(default_factory=tuple)
    csv_support_by_file: dict[str, tuple[int, ...]] = field(default_factory=dict)
    manifest_messages: tuple[str, ...] = field(default_factory=tuple)
    selection_source: str = ""


@dataclass(frozen=True)
class CanonicalInstance:
    """Canonical runtime instance shared by reference and production tracks."""

    frozen_config: FrozenConfig
    sets: CanonicalSets
    lines: tuple[LineData, ...]
    nodes: tuple[NodeMeta, ...]
    economics: EconomicParameters
    ev: EVParameters
    ambiguity: AmbiguityParameters
    normal_tensors: NormalScenarioTensor
    disaster_tensors: DisasterScenarioTensor
    index_map: IndexMap
    network_topology: NetworkTopology
    scenario_support: ScenarioSupport
    critical_buses: tuple[int, ...] | None = None
    is_critical_by_bus: dict[int, bool] | None = None
    cls_by_bus: dict[int, float] | None = None
    runtime_directory: str = ""
    runtime_parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


def load_canonical_instance(
    runtime_dir: str | Path = "data/runtime_12",
    *,
    frozen_config: FrozenConfig = DEFAULT_FROZEN_CONFIG,
    critical_buses: Sequence[int] | None = None,
    selection: "RuntimeSelection | None" = None,
    expanded_mode: bool = False,
) -> CanonicalInstance:
    """Load and canonicalize a runtime instance."""

    from src.instance.loader_adapter import load_runtime_instance

    return load_runtime_instance(
        runtime_dir=runtime_dir,
        frozen_config=frozen_config,
        critical_buses=critical_buses,
        selection=selection,
        expanded_mode=expanded_mode,
    )
