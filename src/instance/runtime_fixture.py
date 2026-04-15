"""Helpers for the default Round 01 runtime fixture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from src.contracts.freeze import DEFAULT_FROZEN_CONFIG, FrozenConfig
from src.instance.canonical_instance import CanonicalInstance, load_canonical_instance
from src.instance.selection import RuntimeSelection, default_runtime_selection


DEFAULT_RUNTIME_12_DIR = Path("data/runtime_12")


@dataclass(frozen=True)
class RuntimeFixtureRequest:
    """Request object for loading the default runtime fixture."""

    runtime_dir: Path = DEFAULT_RUNTIME_12_DIR
    frozen_config: FrozenConfig = DEFAULT_FROZEN_CONFIG
    expanded_mode: bool = False
    selection: RuntimeSelection | None = None
    critical_buses: tuple[int, ...] | None = None


def load_default_runtime_fixture(
    *,
    expanded_mode: bool = False,
    selection: RuntimeSelection | None = None,
    critical_buses: Sequence[int] | None = None,
) -> CanonicalInstance:
    """Load the default Round 01.5 runtime fixture using selection semantics."""

    resolved_selection = selection
    if resolved_selection is None and not expanded_mode:
        resolved_selection = default_runtime_selection(DEFAULT_FROZEN_CONFIG)

    return load_canonical_instance(
        runtime_dir=DEFAULT_RUNTIME_12_DIR,
        frozen_config=DEFAULT_FROZEN_CONFIG,
        critical_buses=critical_buses,
        selection=resolved_selection,
        expanded_mode=expanded_mode,
    )
