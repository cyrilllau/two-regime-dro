"""Project freeze-contract placeholders aligned to the stable spec documents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FrozenConfig:
    """Normalized project-wide freeze settings.

    This placeholder mirrors the current stable contract at a high level without
    implementing config loading or validation.
    """

    instance_id: str = "local_tested_small_v1"
    scenarios_a: tuple[int, ...] = (1, 2)
    scenarios_b: tuple[int, ...] = (1, 2)
    root_bus: int = 1
    allow_evcs_at_root: bool = False
    cunmet: float = 3.0
    critical_buses_required: bool = True


DEFAULT_FROZEN_CONFIG = FrozenConfig()
