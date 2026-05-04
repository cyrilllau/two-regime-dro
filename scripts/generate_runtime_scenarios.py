"""Generate reproducible larger scenario supports from the runtime_12 profiles."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import shutil
from pathlib import Path
from typing import Callable, Sequence


NORMAL_FILES = (
    ("normal_load_scenarios.csv", "scenario_a", ("P_kW", "Q_kvar"), "load"),
    ("normal_ev_demand_slow.csv", "scenario_a", ("DEV_ch_sl_kW",), "normal_ev"),
    ("normal_ev_demand_fast.csv", "scenario_a", ("DEV_ch_fa_kW",), "normal_ev"),
)
DISASTER_FILES = (
    ("disaster_load_scenarios.csv", "scenario_b", ("P_kW",), "disaster_load"),
    ("disaster_ev_discharge_slow.csv", "scenario_b", ("DEV_dis_sl_kW",), "disaster_ev"),
    ("disaster_ev_discharge_fast.csv", "scenario_b", ("DEV_dis_fa_kW",), "disaster_ev"),
)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _group_by_scenario(rows: Sequence[dict[str, str]], scenario_col: str) -> dict[int, list[dict[str, str]]]:
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(int(row[scenario_col]), []).append(dict(row))
    return grouped


def _bounded(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _scenario_scale(
    rng: random.Random,
    *,
    target_scenario: int,
    profile_kind: str,
    time_value: int | None,
    region_value: int | None,
) -> float:
    phase = rng.random() * 2.0 * math.pi
    base_sigma = {
        "load": 0.11,
        "normal_ev": 0.18,
        "disaster_load": 0.16,
        "disaster_ev": 0.22,
    }[profile_kind]
    base = rng.lognormvariate(0.0, base_sigma)
    if time_value is not None:
        period = 24.0 if profile_kind in {"load", "normal_ev"} else 4.0
        base *= 1.0 + 0.06 * math.sin(2.0 * math.pi * float(time_value) / period + phase)
    if region_value is not None:
        base *= 1.0 + 0.035 * (float(region_value) - 2.0)
    if profile_kind == "disaster_ev":
        # Available post-disaster V2G support is intentionally more volatile.
        return _bounded(base, 0.45, 1.55)
    if profile_kind == "normal_ev":
        return _bounded(base, 0.60, 1.60)
    return _bounded(base, 0.70, 1.45)


def _expand_file(
    source_path: Path,
    output_path: Path,
    *,
    scenario_col: str,
    value_cols: Sequence[str],
    target_count: int,
    profile_kind: str,
    seed: int,
) -> None:
    fieldnames, rows = _read_csv(source_path)
    grouped = _group_by_scenario(rows, scenario_col)
    source_ids = sorted(grouped)
    expanded: list[dict[str, str]] = []

    for target_scenario in range(1, target_count + 1):
        source_scenario = source_ids[(target_scenario - 1) % len(source_ids)]
        for row_index, source_row in enumerate(grouped[source_scenario]):
            row = dict(source_row)
            row[scenario_col] = str(target_scenario)
            time_value = None
            for time_col in ("t", "ts"):
                if time_col in row:
                    time_value = int(row[time_col])
            region_value = int(row["region"]) if "region" in row else None
            rng = random.Random(seed + 1000003 * target_scenario + 37 * row_index)
            scale = _scenario_scale(
                rng,
                target_scenario=target_scenario,
                profile_kind=profile_kind,
                time_value=time_value,
                region_value=region_value,
            )
            for value_col in value_cols:
                row[value_col] = f"{float(source_row[value_col]) * scale:.6f}"
            expanded.append(row)
    _write_csv(output_path, fieldnames, expanded)


def generate(
    *,
    source_dir: Path,
    output_dir: Path,
    normal_count: int,
    disaster_count: int,
    seed: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    parameters = json.loads((source_dir / "parameters.json").read_text(encoding="utf-8"))
    parameters.setdefault("sets", {})["scenarios_a"] = list(range(1, int(normal_count) + 1))
    parameters.setdefault("sets", {})["scenarios_b"] = list(range(1, int(disaster_count) + 1))
    (output_dir / "parameters.json").write_text(
        json.dumps(parameters, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for file_name, scenario_col, value_cols, profile_kind in NORMAL_FILES:
        _expand_file(
            source_dir / file_name,
            output_dir / file_name,
            scenario_col=scenario_col,
            value_cols=value_cols,
            target_count=normal_count,
            profile_kind=profile_kind,
            seed=seed,
        )
    for file_name, scenario_col, value_cols, profile_kind in DISASTER_FILES:
        _expand_file(
            source_dir / file_name,
            output_dir / file_name,
            scenario_col=scenario_col,
            value_cols=value_cols,
            target_count=disaster_count,
            profile_kind=profile_kind,
            seed=seed + 7919,
        )
    manifest = {
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "normal_count": int(normal_count),
        "disaster_count": int(disaster_count),
        "seed": int(seed),
        "method": (
            "Cyclically reuse source scenarios and apply bounded lognormal, "
            "time-dependent, and region-dependent multiplicative perturbations."
        ),
        "normal_files": [
            {"file": file_name, "scenario_col": scenario_col, "value_cols": list(value_cols)}
            for file_name, scenario_col, value_cols, _ in NORMAL_FILES
        ],
        "disaster_files": [
            {"file": file_name, "scenario_col": scenario_col, "value_cols": list(value_cols)}
            for file_name, scenario_col, value_cols, _ in DISASTER_FILES
        ],
        "declared_support": {
            "scenarios_a": list(range(1, int(normal_count) + 1)),
            "scenarios_b": list(range(1, int(disaster_count) + 1)),
        },
    }
    (output_dir / "scenario_generation_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="data/runtime_12")
    parser.add_argument("--output", default="data/runtime_12_synth_100")
    parser.add_argument("--normal-count", type=int, default=100)
    parser.add_argument("--disaster-count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260426)
    args = parser.parse_args()
    generate(
        source_dir=Path(args.source),
        output_dir=Path(args.output),
        normal_count=args.normal_count,
        disaster_count=args.disaster_count,
        seed=args.seed,
    )
    print(
        f"Generated {args.normal_count} normal and {args.disaster_count} disaster scenarios "
        f"under {args.output}."
    )


if __name__ == "__main__":
    main()
