"""Unit tests for raw-support manifest inspection."""

from __future__ import annotations

from pathlib import Path

from src.instance.manifest import inspect_available_support
from src.instance.raw_package import load_raw_data_package


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runtime_12_manifest_records_disaster_json_csv_mismatch() -> None:
    """Disaster-stage JSON/CSV disagreements should be reported, not hidden."""

    raw_package = load_raw_data_package(REPO_ROOT / "data/runtime_12")
    manifest = inspect_available_support(raw_package)

    assert manifest.json_declared_support_is_advisory is True
    assert manifest.normal.declared_support == tuple(range(1, 11))
    assert manifest.normal.csv_support == tuple(range(1, 11))
    assert manifest.normal.has_mismatch is False
    assert manifest.disaster.declared_support == (1, 2)
    assert manifest.disaster.csv_support == tuple(range(1, 11))
    assert manifest.disaster.has_mismatch is True
    assert (
        "Disaster-stage support declared in parameters.json is (1, 2), but live CSV support is "
        "(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)."
    ) == manifest.disaster.issues[0].message


def test_manifest_preserves_file_level_csv_support() -> None:
    """Manifest metadata should keep the per-file raw availability evidence."""

    raw_package = load_raw_data_package(REPO_ROOT / "data/runtime_12")
    manifest = inspect_available_support(raw_package)

    assert manifest.normal.csv_support_by_file["normal_load"] == tuple(range(1, 11))
    assert manifest.disaster.csv_support_by_file["disaster_fast"] == tuple(range(1, 11))
