"""Runtime scenario-selection presets and validation helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from src.contracts.freeze import DEFAULT_FROZEN_CONFIG, FrozenConfig
from src.instance.manifest import RuntimeSupportManifest
from src.instance.validators import RuntimeDataValidationError, validate_runtime_selection


@dataclass(frozen=True)
class RuntimeSelection:
    """Explicit runtime scenario selection for the canonical instance."""

    scenarios_a: tuple[int, ...]
    scenarios_b: tuple[int, ...]
    source: str = "explicit"


def _normalize_selection(values: Sequence[int], *, field_name: str) -> tuple[int, ...]:
    normalized = tuple(int(value) for value in values)
    if not normalized:
        raise RuntimeDataValidationError(f"{field_name} must be a non-empty list of scenario ids.")
    if len(set(normalized)) != len(normalized):
        raise RuntimeDataValidationError(
            f"{field_name} contains duplicate scenario ids: {normalized}."
        )
    return tuple(sorted(normalized))


def build_runtime_selection(
    *,
    scenarios_a: Sequence[int],
    scenarios_b: Sequence[int],
    source: str = "explicit",
) -> RuntimeSelection:
    """Build a normalized runtime selection."""

    return RuntimeSelection(
        scenarios_a=_normalize_selection(scenarios_a, field_name="scenarios_a"),
        scenarios_b=_normalize_selection(scenarios_b, field_name="scenarios_b"),
        source=source,
    )


def default_runtime_selection(
    frozen_config: FrozenConfig = DEFAULT_FROZEN_CONFIG,
) -> RuntimeSelection:
    """Return the frozen default small selection preset."""

    return RuntimeSelection(
        scenarios_a=frozen_config.scenarios_a,
        scenarios_b=frozen_config.scenarios_b,
        source="default_small_preset",
    )


def expanded_runtime_selection(manifest: RuntimeSupportManifest) -> RuntimeSelection:
    """Select the full raw CSV reservoir for both stages."""

    return RuntimeSelection(
        scenarios_a=manifest.normal.csv_support,
        scenarios_b=manifest.disaster.csv_support,
        source="expanded_csv_reservoir",
    )


def load_runtime_selection_file(path: str | Path) -> RuntimeSelection:
    """Load a JSON-compatible YAML selection fixture."""

    file_path = Path(path)
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeDataValidationError(
            f"{file_path} must contain JSON-compatible YAML for selection fixtures."
        ) from exc
    if not isinstance(raw, Mapping):
        raise RuntimeDataValidationError(f"{file_path} must parse to a mapping.")
    if "scenarios_a" not in raw or "scenarios_b" not in raw:
        raise RuntimeDataValidationError(
            f"{file_path} must define both scenarios_a and scenarios_b."
        )
    return build_runtime_selection(
        scenarios_a=raw["scenarios_a"],
        scenarios_b=raw["scenarios_b"],
        source=str(file_path),
    )


def resolve_runtime_selection(
    *,
    manifest: RuntimeSupportManifest,
    frozen_config: FrozenConfig = DEFAULT_FROZEN_CONFIG,
    selection: RuntimeSelection | None = None,
    expanded_mode: bool = False,
) -> RuntimeSelection:
    """Resolve and validate the selection used for this run."""

    resolved = selection
    if resolved is None:
        resolved = expanded_runtime_selection(manifest) if expanded_mode else default_runtime_selection(
            frozen_config
        )

    normal = validate_runtime_selection(
        stage_name="Normal-stage",
        requested_selection=resolved.scenarios_a,
        csv_support=manifest.normal.csv_support,
    )
    disaster = validate_runtime_selection(
        stage_name="Disaster-stage",
        requested_selection=resolved.scenarios_b,
        csv_support=manifest.disaster.csv_support,
    )
    return RuntimeSelection(
        scenarios_a=normal,
        scenarios_b=disaster,
        source=resolved.source,
    )
