"""Raw runtime package loading without scenario-selection decisions."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.instance.schema import RawInputSchema
from src.instance.validators import RuntimeDataValidationError


@dataclass(frozen=True)
class RawDataPackage:
    """Raw runtime material loaded directly from JSON/CSV files."""

    schema: RawInputSchema
    raw_parameters: dict[str, Any]
    csv_rows_by_file: dict[str, tuple[dict[str, str], ...]]
    csv_support_by_file: dict[str, tuple[int, ...]]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeDataValidationError(f"Missing runtime parameter file: {path}.") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeDataValidationError(f"Invalid JSON in runtime parameter file: {path}.") from exc


def _read_csv_rows(path: Path) -> tuple[dict[str, str], ...]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return tuple(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise RuntimeDataValidationError(f"Missing runtime CSV file: {path}.") from exc


def _discover_support(
    rows: tuple[dict[str, str], ...],
    *,
    scenario_field: str,
    path: Path,
) -> tuple[int, ...]:
    support: set[int] = set()
    for line_no, row in enumerate(rows, start=2):
        try:
            support.add(int(row[scenario_field]))
        except (KeyError, ValueError) as exc:
            raise RuntimeDataValidationError(
                f"{path}:{line_no} has invalid scenario field {scenario_field!r}: "
                f"{row.get(scenario_field)!r}."
            ) from exc
    return tuple(sorted(support))


def load_raw_data_package(
    runtime_dir: str | Path = "data/runtime_12",
    *,
    schema: RawInputSchema | None = None,
) -> RawDataPackage:
    """Load a runtime JSON/CSV package without applying selection semantics."""

    runtime_schema = schema or RawInputSchema.for_runtime_dir(runtime_dir)
    csv_paths = runtime_schema.csv_paths()
    csv_rows_by_file = {
        name: _read_csv_rows(path)
        for name, path in csv_paths.items()
    }
    csv_support_by_file = {
        "normal_load": _discover_support(
            csv_rows_by_file["normal_load"],
            scenario_field="scenario_a",
            path=csv_paths["normal_load"],
        ),
        "normal_slow": _discover_support(
            csv_rows_by_file["normal_slow"],
            scenario_field="scenario_a",
            path=csv_paths["normal_slow"],
        ),
        "normal_fast": _discover_support(
            csv_rows_by_file["normal_fast"],
            scenario_field="scenario_a",
            path=csv_paths["normal_fast"],
        ),
        "disaster_load": _discover_support(
            csv_rows_by_file["disaster_load"],
            scenario_field="scenario_b",
            path=csv_paths["disaster_load"],
        ),
        "disaster_slow": _discover_support(
            csv_rows_by_file["disaster_slow"],
            scenario_field="scenario_b",
            path=csv_paths["disaster_slow"],
        ),
        "disaster_fast": _discover_support(
            csv_rows_by_file["disaster_fast"],
            scenario_field="scenario_b",
            path=csv_paths["disaster_fast"],
        ),
    }
    return RawDataPackage(
        schema=runtime_schema,
        raw_parameters=_read_json(runtime_schema.parameter_path),
        csv_rows_by_file=csv_rows_by_file,
        csv_support_by_file=csv_support_by_file,
    )
