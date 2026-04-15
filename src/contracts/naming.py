"""Stable naming helpers for canonical instance artifacts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelLabel:
    """Structured label for future equation-tagged artifacts."""

    namespace: str
    name: str


def make_line_id(from_bus: int, to_bus: int) -> str:
    """Create a stable line id from an oriented feeder edge."""

    return f"line_{from_bus:02d}_{to_bus:02d}"


def make_bus_label(bus_id: int) -> str:
    """Create a stable debug label for a bus."""

    return f"bus_{bus_id:02d}"
