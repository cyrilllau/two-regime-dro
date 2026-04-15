"""Unit tests for runtime selection presets and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.instance.manifest import inspect_available_support
from src.instance.raw_package import load_raw_data_package
from src.instance.selection import (
    default_runtime_selection,
    load_runtime_selection_file,
    resolve_runtime_selection,
)
from src.instance.validators import RuntimeDataValidationError


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _runtime_12_manifest():
    raw_package = load_raw_data_package(REPO_ROOT / "data/runtime_12")
    return inspect_available_support(raw_package)


def test_default_small_selection_fixture_loads() -> None:
    """The default small preset fixture should parse deterministically."""

    selection = load_runtime_selection_file(FIXTURE_DIR / "selection_default_small.yaml")

    assert selection.scenarios_a == (1, 2)
    assert selection.scenarios_b == (1, 2)


def test_default_runtime_selection_matches_frozen_preset() -> None:
    """The helper preset should still point to the frozen {1,2} selection."""

    selection = default_runtime_selection()

    assert selection.scenarios_a == (1, 2)
    assert selection.scenarios_b == (1, 2)
    assert selection.source == "default_small_preset"


def test_selection_missing_from_csv_is_rejected() -> None:
    """Runtime selection must be bounded by CSV availability, not by wishful config."""

    manifest = _runtime_12_manifest()
    selection = load_runtime_selection_file(FIXTURE_DIR / "selection_invalid_missing_csv.yaml")

    with pytest.raises(RuntimeDataValidationError, match="absent from CSV support"):
        resolve_runtime_selection(manifest=manifest, selection=selection)


def test_selection_missing_from_json_is_allowed_under_advisory_policy() -> None:
    """JSON support remains advisory metadata when the chosen scenario exists in CSV."""

    manifest = _runtime_12_manifest()
    selection = load_runtime_selection_file(FIXTURE_DIR / "selection_invalid_missing_json.yaml")
    resolved = resolve_runtime_selection(manifest=manifest, selection=selection)

    assert resolved.scenarios_a == (1, 2, 3)
    assert resolved.scenarios_b == (3,)
    assert 3 not in manifest.disaster.declared_support
