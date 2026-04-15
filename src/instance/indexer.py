"""Deterministic index helpers for canonical instance objects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IndexMap:
    """Stable label collections plus position lookups for canonical sets."""

    buses: tuple[int, ...] = field(default_factory=tuple)
    lines: tuple[str, ...] = field(default_factory=tuple)
    regions: tuple[int, ...] = field(default_factory=tuple)
    normal_times: tuple[int, ...] = field(default_factory=tuple)
    disaster_times: tuple[int, ...] = field(default_factory=tuple)
    normal_scenarios: tuple[int, ...] = field(default_factory=tuple)
    disaster_scenarios: tuple[int, ...] = field(default_factory=tuple)
    bus_to_index: dict[int, int] = field(default_factory=dict)
    line_to_index: dict[str, int] = field(default_factory=dict)
    region_to_index: dict[int, int] = field(default_factory=dict)
    normal_time_to_index: dict[int, int] = field(default_factory=dict)
    disaster_time_to_index: dict[int, int] = field(default_factory=dict)
    normal_scenario_to_index: dict[int, int] = field(default_factory=dict)
    disaster_scenario_to_index: dict[int, int] = field(default_factory=dict)


def _build_lookup(labels: tuple[int | str, ...]) -> dict[int | str, int]:
    return {label: position for position, label in enumerate(labels)}


def build_index_map(
    *,
    buses: tuple[int, ...],
    lines: tuple[str, ...],
    regions: tuple[int, ...],
    normal_times: tuple[int, ...],
    disaster_times: tuple[int, ...],
    normal_scenarios: tuple[int, ...],
    disaster_scenarios: tuple[int, ...],
) -> IndexMap:
    """Build deterministic index maps while preserving canonical order."""

    return IndexMap(
        buses=buses,
        lines=lines,
        regions=regions,
        normal_times=normal_times,
        disaster_times=disaster_times,
        normal_scenarios=normal_scenarios,
        disaster_scenarios=disaster_scenarios,
        bus_to_index=_build_lookup(buses),
        line_to_index=_build_lookup(lines),
        region_to_index=_build_lookup(regions),
        normal_time_to_index=_build_lookup(normal_times),
        disaster_time_to_index=_build_lookup(disaster_times),
        normal_scenario_to_index=_build_lookup(normal_scenarios),
        disaster_scenario_to_index=_build_lookup(disaster_scenarios),
    )
