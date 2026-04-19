"""Build the Round 14 frozen baseline archive."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import (  # noqa: E402
    ensure_directory,
    execute_run,
    load_critical_buses,
    load_yaml_file as load_pack_yaml_file,
    write_failures_csv,
    write_summary_csv,
)


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path} must contain a YAML mapping.")
    return dict(raw)


def _remove_existing_tree(path: Path) -> None:
    if path.exists():
        if path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_tree(source: Path, destination: Path) -> None:
    _remove_existing_tree(destination)
    shutil.copytree(source, destination)


def _copy_optional_file(
    *,
    source: Path,
    destination: Path,
    missing: list[str],
) -> None:
    if source.exists():
        _copy_file(source, destination)
    else:
        missing.append(str(source))


def _copy_optional_tree(
    *,
    source: Path,
    destination: Path,
    missing: list[str],
) -> None:
    if source.exists():
        _copy_tree(source, destination)
    else:
        missing.append(str(source))


def regenerate_certified_small_family(
    *,
    family_config_path: str | Path,
    critical_buses: tuple[int, ...],
    output_root: str | Path,
) -> dict[str, Any]:
    """Regenerate the missing Round 11 certified-small family under the archive root."""

    family = load_pack_yaml_file(family_config_path)
    output_root_path = ensure_directory(output_root)
    for child in output_root_path.iterdir():
        if child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)
    ensure_directory(output_root_path / "plans")
    ensure_directory(output_root_path / "logs")

    results = []
    for run_config in family["runs"]:
        run_payload = dict(run_config)
        run_payload["family_name"] = str(family["family_name"])
        results.append(
            execute_run(run_payload, critical_buses=critical_buses, output_root=output_root_path)
        )
    summaries = [result["summary"] for result in results]
    failures = [
        result["failure_summary"]
        for result in results
        if result["failure_summary"] is not None
    ]
    summary_path = write_summary_csv(output_root_path / "summary.csv", summaries)
    failures_path = write_failures_csv(output_root_path / "failures.csv", failures)
    return {
        "family_name": family["family_name"],
        "output_root": str(output_root_path),
        "summary_path": str(summary_path),
        "failures_path": str(failures_path),
        "run_ids": [str(run["run_id"]) for run in family["runs"]],
    }


def build_archive(
    *,
    config_path: str | Path = "configs/reports/frozen_baseline_review.yaml",
    archive_root_override: str | Path | None = None,
    regenerate_certified_small: bool = True,
) -> dict[str, Any]:
    """Create the frozen pre-improvement archive and return metadata."""

    config = load_yaml_file(config_path)
    archive_root = Path(archive_root_override or config["archive_root"])
    _remove_existing_tree(archive_root)
    archive_root.mkdir(parents=True, exist_ok=True)

    reused: list[str] = []
    regenerated: list[str] = []
    missing: list[str] = []

    # Round reports.
    for report_path in config["round_reports"]:
        source = REPO_ROOT / report_path
        destination = archive_root / report_path
        _copy_optional_file(source=source, destination=destination, missing=missing)
        if source.exists():
            reused.append(report_path)

    # Current packaged outputs.
    current = config["current_outputs"]
    for relative_path in (
        current["experiment_summary_csv"],
        current["experiment_failures_csv"],
        current["convergence_summary_csv"],
        current["convergence_failures_csv"],
        current["cut_process_summary_csv"],
        current["cut_process_failures_csv"],
        current["cut_process_cut_csv"],
    ):
        source = REPO_ROOT / relative_path
        _copy_optional_file(source=source, destination=archive_root / relative_path, missing=missing)
        if source.exists():
            reused.append(relative_path)

    for relative_dir in (
        current["experiment_figures_dir"],
        current["experiment_logs_dir"],
        current["experiment_plans_dir"],
        current["convergence_figures_dir"],
        current["convergence_logs_dir"],
        current["cut_process_figures_dir"],
        current["cut_process_logs_dir"],
        current["cut_process_lp_dir"],
    ):
        source_dir = REPO_ROOT / relative_dir
        _copy_optional_tree(source=source_dir, destination=archive_root / relative_dir, missing=missing)
        if source_dir.exists():
            reused.append(relative_dir)

    # Current pack docs: preserve both current and legacy-named archive paths.
    for pack_name, source_relative in config["pack_sources"].items():
        source = REPO_ROOT / source_relative
        if source.exists():
            current_destination = archive_root / source_relative
            _copy_file(source, current_destination)
            reused.append(source_relative)
            legacy_name = f"{pack_name}.md"
            if pack_name == "experiment_interpretation":
                legacy_name = "experiment_interpretation_pack.md"
            elif pack_name == "paper_style_experiment":
                legacy_name = "paper_style_experiment_pack.md"
            elif pack_name == "convergence_diagnostic":
                legacy_name = "convergence_diagnostic_pack.md"
            elif pack_name == "cut_process_diagnostic":
                legacy_name = "cut_process_diagnostic_pack.md"
            _copy_file(source, archive_root / "reports" / legacy_name)
        else:
            missing.append(str(source))

    # Explicitly copy selected iteration logs / LP dumps to a compact top-level selection folder too.
    for relative_path in config.get("selected_iteration_logs", []):
        source = REPO_ROOT / relative_path
        if source.exists():
            _copy_file(source, archive_root / "selected_iteration_logs" / Path(relative_path).name)
            reused.append(relative_path)
        else:
            missing.append(str(source))
    for relative_path in config.get("selected_lp_dumps", []):
        source = REPO_ROOT / relative_path
        if source.exists():
            _copy_file(source, archive_root / "selected_lp_dumps" / Path(relative_path).name)
            reused.append(relative_path)
        else:
            missing.append(str(source))

    regen_info: dict[str, Any] | None = None
    if regenerate_certified_small:
        critical_buses = tuple(int(bus) for bus in config["critical_buses"])
        regen_info = regenerate_certified_small_family(
            family_config_path=config["certified_small_family"]["source_config"],
            critical_buses=critical_buses,
            output_root=archive_root / "regenerated" / "certified_small",
        )
        regenerated.append("certified_small_family")
    return {
        "config_path": str(config_path),
        "archive_root": str(archive_root),
        "reused_artifacts": sorted(set(reused)),
        "regenerated_artifacts": regenerated,
        "missing_artifacts": missing,
        "regenerated_certified_small": regen_info,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/reports/frozen_baseline_review.yaml")
    parser.add_argument("--archive-root", default=None)
    parser.add_argument("--skip-certified-small-regeneration", action="store_true")
    parser.add_argument("--metadata-out", default=None)
    args = parser.parse_args()

    archive_info = build_archive(
        config_path=args.config,
        archive_root_override=args.archive_root,
        regenerate_certified_small=not args.skip_certified_small_regeneration,
    )
    if args.metadata_out:
        metadata_path = Path(args.metadata_out)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(archive_info, indent=2, sort_keys=True), encoding="utf-8")
    else:
        print(json.dumps(archive_info, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
