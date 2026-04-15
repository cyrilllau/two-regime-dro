"""Tests for radial topology helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.contracts.naming import make_line_id
from src.instance.network_topology import Line, build_network_topology, get_downstream_line_ids
from src.instance.validators import RuntimeDataValidationError


REPO_ROOT = Path(__file__).resolve().parents[2]


def _runtime_12_topology_input() -> tuple[tuple[int, ...], tuple[Line, ...]]:
    raw = json.loads((REPO_ROOT / "data/runtime_12/parameters.json").read_text(encoding="utf-8"))
    buses = tuple(raw["sets"]["buses"])
    lines = tuple(
        Line(
            line_id=make_line_id(from_bus, to_bus),
            from_bus=from_bus,
            to_bus=to_bus,
        )
        for from_bus, to_bus in raw["sets"]["lines"]
    )
    return buses, lines


def test_ieee33_topology_helpers_are_correct() -> None:
    """The IEEE 33-bus feeder should canonicalize into a single-root radial tree."""

    buses, lines = _runtime_12_topology_input()
    topology = build_network_topology(buses=buses, lines=lines, root_bus=1)

    assert topology.root_bus == 1
    assert topology.parent_by_bus[19] == 2
    assert topology.children_by_bus[6] == (7, 26)
    assert topology.bus_depth[33] > topology.bus_depth[32]
    assert len(get_downstream_line_ids(topology, 6)) == 20
    assert "line_06_26" in get_downstream_line_ids(topology, 6)


def test_non_radial_topology_is_rejected() -> None:
    """Multiple parents must fail before any model layer is built."""

    with pytest.raises(RuntimeDataValidationError, match="multiple parents"):
        build_network_topology(
            buses=(1, 2, 3),
            lines=(
                Line(line_id="line_01_02", from_bus=1, to_bus=2),
                Line(line_id="line_03_02", from_bus=3, to_bus=2),
            ),
            root_bus=1,
        )
