"""Tests for deterministic canonical index maps."""

from __future__ import annotations

from src.instance.indexer import build_index_map


def test_index_map_preserves_canonical_order() -> None:
    """Canonical order should translate directly into index positions."""

    index_map = build_index_map(
        buses=(1, 2, 19),
        lines=("line_01_02", "line_02_19"),
        regions=(1, 2),
        normal_times=(1, 2, 3),
        disaster_times=(1, 2),
        normal_scenarios=(1, 2),
        disaster_scenarios=(1, 2),
    )

    assert index_map.bus_to_index == {1: 0, 2: 1, 19: 2}
    assert index_map.line_to_index["line_02_19"] == 1
    assert index_map.normal_time_to_index[3] == 2
    assert index_map.disaster_scenario_to_index[2] == 1


def test_index_map_is_deterministic_across_calls() -> None:
    """Repeated construction with the same canonical labels should be identical."""

    kwargs = dict(
        buses=(1, 2, 3),
        lines=("line_01_02", "line_02_03"),
        regions=(1,),
        normal_times=(1, 2),
        disaster_times=(1,),
        normal_scenarios=(1, 2),
        disaster_scenarios=(1, 2),
    )
    first = build_index_map(**kwargs)
    second = build_index_map(**kwargs)
    assert first == second
