"""Network-topology helpers for the IEEE 33-bus feeder and toy fixtures."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.instance.validators import RuntimeDataValidationError


@dataclass(frozen=True)
class Line:
    """Stable line identifier for an oriented radial feeder edge."""

    line_id: str
    from_bus: int
    to_bus: int
    resistance_pu: float | None = None
    reactance_pu: float | None = None
    p_max_kw: float | None = None
    q_max_kvar: float | None = None


@dataclass(frozen=True)
class NetworkTopology:
    """Canonical radial topology object."""

    root_bus: int = 1
    lines: tuple[Line, ...] = field(default_factory=tuple)
    parent_by_bus: dict[int, int] = field(default_factory=dict)
    children_by_bus: dict[int, tuple[int, ...]] = field(default_factory=dict)
    line_by_child_bus: dict[int, str] = field(default_factory=dict)
    downstream_lines_by_bus: dict[int, tuple[str, ...]] = field(default_factory=dict)
    bus_depth: dict[int, int] = field(default_factory=dict)
    is_radial: bool = True


def build_network_topology(
    *,
    buses: tuple[int, ...],
    lines: tuple[Line, ...],
    root_bus: int,
) -> NetworkTopology:
    """Validate and build a single-root radial topology object."""

    bus_set = set(buses)
    if root_bus not in bus_set:
        raise RuntimeDataValidationError(
            f"Frozen root bus {root_bus} is not present in the bus set."
        )
    if len(set(line.line_id for line in lines)) != len(lines):
        raise RuntimeDataValidationError("Duplicate line_id values are not allowed.")
    if len(lines) != len(buses) - 1:
        raise RuntimeDataValidationError(
            "Topology is not a single-root radial tree: "
            f"expected |L| = |N| - 1 = {len(buses) - 1}, got {len(lines)}."
        )

    parent_by_bus: dict[int, int] = {}
    children_by_bus: dict[int, list[int]] = {bus: [] for bus in buses}
    line_by_child_bus: dict[int, str] = {}

    for line in lines:
        if line.from_bus not in bus_set or line.to_bus not in bus_set:
            raise RuntimeDataValidationError(
                f"Line {line.line_id} references buses outside the bus set."
            )
        if line.to_bus == root_bus:
            raise RuntimeDataValidationError(
                f"Root bus {root_bus} cannot appear as a child node in line {line.line_id}."
            )
        if line.to_bus in parent_by_bus:
            raise RuntimeDataValidationError(
                f"Bus {line.to_bus} has multiple parents: "
                f"{parent_by_bus[line.to_bus]} and {line.from_bus}."
            )
        parent_by_bus[line.to_bus] = line.from_bus
        children_by_bus[line.from_bus].append(line.to_bus)
        line_by_child_bus[line.to_bus] = line.line_id

    if root_bus in parent_by_bus:
        raise RuntimeDataValidationError(
            f"Root bus {root_bus} unexpectedly has a parent assignment."
        )

    visited: set[int] = set()
    bus_depth: dict[int, int] = {root_bus: 0}
    stack = [root_bus]
    while stack:
        bus = stack.pop()
        if bus in visited:
            raise RuntimeDataValidationError(
                f"Topology cycle detected while revisiting bus {bus}."
            )
        visited.add(bus)
        for child in children_by_bus.get(bus, []):
            bus_depth[child] = bus_depth[bus] + 1
            stack.append(child)

    missing = tuple(sorted(bus_set - visited))
    if missing:
        raise RuntimeDataValidationError(
            "Topology is not connected to the frozen root bus; "
            f"unreachable buses: {missing}."
        )

    ordered_children = {bus: tuple(sorted(children)) for bus, children in children_by_bus.items()}

    downstream_cache: dict[int, tuple[str, ...]] = {}

    def collect_downstream_lines(bus: int) -> tuple[str, ...]:
        if bus in downstream_cache:
            return downstream_cache[bus]
        line_ids: list[str] = []
        for child in ordered_children.get(bus, ()):
            line_ids.append(line_by_child_bus[child])
            line_ids.extend(collect_downstream_lines(child))
        downstream_cache[bus] = tuple(line_ids)
        return downstream_cache[bus]

    downstream_lines_by_bus = {bus: collect_downstream_lines(bus) for bus in buses}

    return NetworkTopology(
        root_bus=root_bus,
        lines=lines,
        parent_by_bus=parent_by_bus,
        children_by_bus=ordered_children,
        line_by_child_bus=line_by_child_bus,
        downstream_lines_by_bus=downstream_lines_by_bus,
        bus_depth=bus_depth,
        is_radial=True,
    )


def get_downstream_line_ids(topology: NetworkTopology, bus_id: int) -> tuple[str, ...]:
    """Return stable downstream line ids for a bus subtree."""

    if bus_id not in topology.downstream_lines_by_bus:
        raise RuntimeDataValidationError(f"Bus {bus_id} is not part of the topology.")
    return topology.downstream_lines_by_bus[bus_id]
