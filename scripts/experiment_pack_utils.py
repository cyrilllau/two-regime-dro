"""Utilities for the Round 11 experiment packaging scripts."""

from __future__ import annotations

from dataclasses import asdict, replace
import csv
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.audit.experiment_summary import ExperimentRunSummary
from src.instance.canonical_instance import (
    CanonicalInstance,
    ScenarioSupport,
    load_canonical_instance,
)
from src.instance.indexer import build_index_map
from src.instance.schema import (
    CanonicalSets,
    DisasterScenarioTensor,
    EconomicParameters,
    NormalScenarioTensor,
)
from src.instance.selection import build_runtime_selection, default_runtime_selection
from src.production.benders_engine import BendersEngineResult, run_benders_engine
from src.production.master_problem import RestrictedMasterProblemSolution, solve_master_problem


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML mapping from disk."""

    file_path = Path(path)
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{file_path} must contain a YAML mapping.")
    return dict(raw)


def write_yaml_file(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write a stable YAML file."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        yaml.safe_dump(dict(payload), sort_keys=False),
        encoding="utf-8",
    )
    return file_path


def ensure_directory(path: str | Path) -> Path:
    """Create a directory and return it as a Path."""

    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def load_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Load the top-level experiment manifest and expand family includes."""

    manifest = load_yaml_file(manifest_path)
    runs: list[dict[str, Any]] = []
    for family_entry in manifest.get("families", ()):
        include_path = family_entry.get("include")
        if include_path is None:
            raise ValueError("Each family entry must define `include`.")
        family_raw = load_yaml_file(include_path)
        family_name = str(family_raw["family_name"])
        for run in family_raw.get("runs", ()):
            run_copy = dict(run)
            run_copy["family_name"] = family_name
            runs.append(run_copy)
    for run in manifest.get("runs", ()):
        runs.append(dict(run))
    expanded = dict(manifest)
    expanded["runs"] = runs
    return expanded


def load_critical_buses(config_path: str | Path) -> tuple[int, ...]:
    """Load the explicit critical-bus set for this round."""

    raw = load_yaml_file(config_path)
    values = raw.get("critical_buses")
    if not isinstance(values, Sequence):
        raise ValueError(f"{config_path} must define a sequence field `critical_buses`.")
    return tuple(int(value) for value in values)


def resolve_selection(run_config: Mapping[str, Any]):
    """Resolve the canonical selection for one run."""

    if "selection" in run_config:
        selection_raw = run_config["selection"]
        return build_runtime_selection(
            scenarios_a=selection_raw["scenarios_a"],
            scenarios_b=selection_raw["scenarios_b"],
            source=str(run_config.get("run_id", "explicit_selection")),
        )
    preset = run_config.get("selection_preset")
    if preset == "default_small":
        return default_runtime_selection()
    return None


def load_instance_for_run(
    run_config: Mapping[str, Any],
    *,
    critical_buses: Sequence[int],
) -> CanonicalInstance:
    """Load the canonical base instance for one experiment run."""

    return load_canonical_instance(
        run_config["runtime_source"],
        critical_buses=tuple(int(bus) for bus in critical_buses),
        selection=resolve_selection(run_config),
    )


def _average_values(values: Sequence[float]) -> float:
    return float(sum(values) / len(values))


def build_mean_value_instance(instance: CanonicalInstance) -> CanonicalInstance:
    """Collapse the currently loaded supports to one mean-value scenario per stage."""

    mean_normal_id = 1
    mean_disaster_id = 1
    normal_support = instance.sets.loaded_normal_scenarios
    disaster_support = instance.sets.loaded_disaster_scenarios

    normal_tensors = NormalScenarioTensor(
        support=(mean_normal_id,),
        p_load={
            (mean_normal_id, time_id, bus): _average_values(
                [
                    instance.normal_tensors.p_load[(scenario_id, time_id, bus)]
                    for scenario_id in normal_support
                ]
            )
            for time_id in instance.sets.normal_times
            for bus in instance.sets.buses
        },
        q_load={
            (mean_normal_id, time_id, bus): _average_values(
                [
                    instance.normal_tensors.q_load[(scenario_id, time_id, bus)]
                    for scenario_id in normal_support
                ]
            )
            for time_id in instance.sets.normal_times
            for bus in instance.sets.buses
        },
        dev_ch_sl={
            (mean_normal_id, time_id, region): _average_values(
                [
                    instance.normal_tensors.dev_ch_sl[(scenario_id, time_id, region)]
                    for scenario_id in normal_support
                ]
            )
            for time_id in instance.sets.normal_times
            for region in instance.sets.regions
        },
        dev_ch_fa={
            (mean_normal_id, time_id, region): _average_values(
                [
                    instance.normal_tensors.dev_ch_fa[(scenario_id, time_id, region)]
                    for scenario_id in normal_support
                ]
            )
            for time_id in instance.sets.normal_times
            for region in instance.sets.regions
        },
    )
    disaster_tensors = DisasterScenarioTensor(
        support=(mean_disaster_id,),
        p_load={
            (mean_disaster_id, time_id, bus): _average_values(
                [
                    instance.disaster_tensors.p_load[(scenario_id, time_id, bus)]
                    for scenario_id in disaster_support
                ]
            )
            for time_id in instance.sets.disaster_times
            for bus in instance.sets.buses
        },
        dev_dis_sl={
            (mean_disaster_id, time_id, region): _average_values(
                [
                    instance.disaster_tensors.dev_dis_sl[(scenario_id, time_id, region)]
                    for scenario_id in disaster_support
                ]
            )
            for time_id in instance.sets.disaster_times
            for region in instance.sets.regions
        },
        dev_dis_fa={
            (mean_disaster_id, time_id, region): _average_values(
                [
                    instance.disaster_tensors.dev_dis_fa[(scenario_id, time_id, region)]
                    for scenario_id in disaster_support
                ]
            )
            for time_id in instance.sets.disaster_times
            for region in instance.sets.regions
        },
    )
    sets = CanonicalSets(
        buses=instance.sets.buses,
        line_ids=instance.sets.line_ids,
        regions=instance.sets.regions,
        normal_times=instance.sets.normal_times,
        disaster_times=instance.sets.disaster_times,
        declared_normal_scenarios=(mean_normal_id,),
        declared_disaster_scenarios=(mean_disaster_id,),
        available_normal_scenarios=(mean_normal_id,),
        available_disaster_scenarios=(mean_disaster_id,),
        loaded_normal_scenarios=(mean_normal_id,),
        loaded_disaster_scenarios=(mean_disaster_id,),
    )
    index_map = build_index_map(
        buses=instance.sets.buses,
        lines=instance.sets.line_ids,
        regions=instance.sets.regions,
        normal_times=instance.sets.normal_times,
        disaster_times=instance.sets.disaster_times,
        normal_scenarios=(mean_normal_id,),
        disaster_scenarios=(mean_disaster_id,),
    )
    scenario_support = ScenarioSupport(
        normal=(mean_normal_id,),
        disaster=(mean_disaster_id,),
        available_normal=(mean_normal_id,),
        available_disaster=(mean_disaster_id,),
        declared_normal=(mean_normal_id,),
        declared_disaster=(mean_disaster_id,),
        csv_support_by_file=dict(instance.scenario_support.csv_support_by_file),
        manifest_messages=tuple(instance.scenario_support.manifest_messages),
        selection_source=f"{instance.scenario_support.selection_source}|mean_value_benchmark",
    )
    metadata = dict(instance.metadata)
    metadata["benchmark_mode"] = "deterministic_mean_value"
    metadata["mean_value_source_normal_support"] = list(normal_support)
    metadata["mean_value_source_disaster_support"] = list(disaster_support)
    return replace(
        instance,
        sets=sets,
        normal_tensors=normal_tensors,
        disaster_tensors=disaster_tensors,
        index_map=index_map,
        scenario_support=scenario_support,
        metadata=metadata,
    )


def build_ev_penetration_instance(instance: CanonicalInstance, *, scale: float) -> CanonicalInstance:
    """Scale EV charging/discharging tensors by an explicit penetration factor."""

    scaled_normal = replace(
        instance.normal_tensors,
        dev_ch_sl={
            key: float(scale * value) for key, value in instance.normal_tensors.dev_ch_sl.items()
        },
        dev_ch_fa={
            key: float(scale * value) for key, value in instance.normal_tensors.dev_ch_fa.items()
        },
    )
    scaled_disaster = replace(
        instance.disaster_tensors,
        dev_dis_sl={
            key: float(scale * value)
            for key, value in instance.disaster_tensors.dev_dis_sl.items()
        },
        dev_dis_fa={
            key: float(scale * value)
            for key, value in instance.disaster_tensors.dev_dis_fa.items()
        },
    )
    metadata = dict(instance.metadata)
    metadata["ev_penetration_scale"] = float(scale)
    return replace(
        instance,
        normal_tensors=scaled_normal,
        disaster_tensors=scaled_disaster,
        metadata=metadata,
    )


def build_normal_only_instance(instance: CanonicalInstance) -> CanonicalInstance:
    """Disable the disaster objective term for the normal-only benchmark."""

    economics = replace(instance.economics, pi_f=0.0)
    metadata = dict(instance.metadata)
    metadata["benchmark_mode"] = "normal_only"
    return replace(instance, economics=economics, metadata=metadata)


def prepare_instance_for_run(
    base_instance: CanonicalInstance,
    run_config: Mapping[str, Any],
) -> CanonicalInstance:
    """Apply benchmark-only transformations in packaging scope."""

    instance = base_instance
    if float(run_config.get("ev_penetration_scale", 1.0)) != 1.0:
        instance = build_ev_penetration_instance(
            instance,
            scale=float(run_config["ev_penetration_scale"]),
        )
    if run_config.get("mode") == "deterministic_mean_value":
        instance = build_mean_value_instance(instance)
    if run_config.get("mode") == "normal_only":
        instance = build_normal_only_instance(instance)
    return instance


def _validation_level_from_result(*, solver: str, stop_reason: str) -> str:
    if solver == "direct_master":
        return "exact"
    if stop_reason == "certified_exact":
        return "exact"
    if stop_reason == "certified_epsilon":
        return "epsilon_certified"
    return "smoke_only"


def _plan_rows(
    instance: CanonicalInstance,
    solution: RestrictedMasterProblemSolution,
) -> list[dict[str, Any]]:
    return [
        {
            "bus": bus,
            "z": int(solution.first_stage_solution.z_by_bus[bus]),
            "n_sl": int(solution.first_stage_solution.n_sl_by_bus[bus]),
            "n_fa": int(solution.first_stage_solution.n_fa_by_bus[bus]),
            "is_critical": int(bool(instance.is_critical_by_bus and instance.is_critical_by_bus[bus])),
            "region": "",
        }
        for bus in instance.sets.buses
    ]


def write_plan_csv(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    """Write one plan-detail CSV."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["bus", "z", "n_sl", "n_fa", "is_critical", "region"]
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    return file_path


def write_summary_csv(path: str | Path, summaries: Sequence[ExperimentRunSummary]) -> Path:
    """Write the experiment summary CSV."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ExperimentRunSummary.__dataclass_fields__.keys())
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            writer.writerow(summary.to_csv_row())
    return file_path


def write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write stable JSON."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return file_path


def build_summary_row(
    *,
    run_config: Mapping[str, Any],
    validation_level: str,
    stop_reason: str,
    solution: RestrictedMasterProblemSolution,
    iteration_count: int,
    cut_count: int,
    final_violation_upper_bound: float,
) -> ExperimentRunSummary:
    """Build the stable summary row for one run."""

    first_stage = solution.first_stage_solution
    opened_bus_count = int(sum(first_stage.z_by_bus.values()))
    total_slow = int(sum(first_stage.n_sl_by_bus.values()))
    total_fast = int(sum(first_stage.n_fa_by_bus.values()))
    return ExperimentRunSummary(
        run_id=str(run_config["run_id"]),
        family_name=str(run_config["family_name"]),
        case_name=str(run_config["case_name"]),
        parameter_regime=str(run_config["parameter_regime"]),
        validation_level=validation_level,
        stop_reason=str(stop_reason),
        total_objective=float(solution.objective_value or 0.0),
        construction_cost=float(solution.construction_cost_value),
        weighted_normal_term=float(solution.averaged_normal_cost_value),
        unweighted_normal_term=float(solution.unweighted_average_normal_cost_value),
        disaster_master_term=float(solution.disaster_master_cost_value),
        alpha=float(solution.alpha_value),
        lambda_times_FP=float(solution.lambda_fp_value),
        iteration_count=int(iteration_count),
        cut_count=int(cut_count),
        final_violation_upper_bound=float(final_violation_upper_bound),
        opened_bus_count=opened_bus_count,
        total_slow_chargers=total_slow,
        total_fast_chargers=total_fast,
    )


def execute_run(
    run_config: Mapping[str, Any],
    *,
    critical_buses: Sequence[int],
    output_root: str | Path,
) -> dict[str, Any]:
    """Execute one experiment run and return full packaging metadata."""

    output_root_path = ensure_directory(output_root)
    plans_dir = ensure_directory(output_root_path / "plans")
    logs_dir = ensure_directory(output_root_path / "logs")

    base_instance = load_instance_for_run(run_config, critical_buses=critical_buses)
    instance = prepare_instance_for_run(base_instance, run_config)
    run_id = str(run_config["run_id"])
    solver = str(run_config["solver"])

    artifact_paths: dict[str, str | None] = {
        "master_before_cut_lp_path": None,
        "master_after_cut_lp_path": None,
        "iteration_log_path": None,
    }

    if solver == "direct_master":
        _, solution = solve_master_problem(
            instance,
            model_name=f"{run_id}_direct_master",
        )
        stop_reason = "direct_optimal" if solution.model_status == "OPTIMAL" else solution.model_status
        iteration_count = 0
        cut_count = 1
        final_violation_upper_bound = 0.0
        lower_bound_sequence: list[float] = []
        cut_count_sequence: list[int] = []
        validation_level = _validation_level_from_result(solver=solver, stop_reason=stop_reason)
        summary = build_summary_row(
            run_config=run_config,
            validation_level=validation_level,
            stop_reason=stop_reason,
            solution=solution,
            iteration_count=iteration_count,
            cut_count=cut_count,
            final_violation_upper_bound=final_violation_upper_bound,
        )
        iteration_payload: dict[str, Any] | None = None
    elif solver == "benders":
        benders_config = dict(run_config.get("benders", {}))
        capture_artifacts = bool(benders_config.get("capture_artifacts", False))
        if capture_artifacts:
            artifact_paths["master_before_cut_lp_path"] = str(
                Path("/tmp") / f"{run_id}_master_before_cut.lp"
            )
            artifact_paths["master_after_cut_lp_path"] = str(
                Path("/tmp") / f"{run_id}_master_after_cut.lp"
            )
        artifact_paths["iteration_log_path"] = str(logs_dir / f"{run_id}_iteration_log.json")
        benders_result: BendersEngineResult = run_benders_engine(
            instance,
            epsilon_cert=float(benders_config.get("epsilon_cert", 0.0)),
            max_iterations=int(benders_config.get("max_iterations", 25)),
            model_name_prefix=run_id,
            master_before_cut_lp_path=artifact_paths["master_before_cut_lp_path"],
            master_after_cut_lp_path=artifact_paths["master_after_cut_lp_path"],
            iteration_log_path=artifact_paths["iteration_log_path"],
        )
        solution = benders_result.final_solution
        stop_reason = str(benders_result.stop_reason)
        iteration_count = len(benders_result.iterations)
        cut_count = len(benders_result.final_master.cuts)
        final_violation_upper_bound = float(
            benders_result.certificate.final_violation_upper_bound
        )
        lower_bound_sequence = list(benders_result.lower_bound_sequence)
        cut_count_sequence = list(benders_result.cut_count_sequence)
        validation_level = _validation_level_from_result(solver=solver, stop_reason=stop_reason)
        summary = build_summary_row(
            run_config=run_config,
            validation_level=validation_level,
            stop_reason=stop_reason,
            solution=solution,
            iteration_count=iteration_count,
            cut_count=cut_count,
            final_violation_upper_bound=final_violation_upper_bound,
        )
        iteration_payload = asdict(benders_result.iteration_log_artifact)
    else:
        raise ValueError(f"Unsupported solver {solver!r}.")

    plan_rows = _plan_rows(instance, solution)
    plan_path = write_plan_csv(plans_dir / f"{run_id}_plan.csv", plan_rows)
    log_payload = {
        "run_config": dict(run_config),
        "validation_level": summary.validation_level,
        "stop_reason": stop_reason,
        "selected_normal_scenarios": list(instance.sets.loaded_normal_scenarios),
        "selected_disaster_scenarios": list(instance.sets.loaded_disaster_scenarios),
        "summary": summary.to_csv_row(),
        "objective_components": {
            "construction_cost": float(solution.construction_cost_value),
            "weighted_normal_term": float(solution.averaged_normal_cost_value),
            "unweighted_normal_term": float(solution.unweighted_average_normal_cost_value),
            "disaster_master_term": float(solution.disaster_master_cost_value),
            "alpha": float(solution.alpha_value),
            "lambda_times_FP": float(solution.lambda_fp_value),
            "objective_reconstruction_gap": float(solution.objective_reconstruction_gap),
        },
        "plan_rows": plan_rows,
        "normal_cost_by_scenario": {
            str(key): float(value) for key, value in solution.normal_cost_by_scenario.items()
        },
        "artifact_paths": artifact_paths,
        "lower_bound_sequence": lower_bound_sequence,
        "cut_count_sequence": cut_count_sequence,
        "iteration_log": iteration_payload,
        "metadata": dict(instance.metadata),
    }
    log_path = write_json(logs_dir / f"{run_id}_run.json", log_payload)

    return {
        "summary": summary,
        "plan_path": str(plan_path),
        "log_path": str(log_path),
        "artifact_paths": artifact_paths,
        "validation_level": summary.validation_level,
        "stop_reason": stop_reason,
        "lower_bound_sequence": lower_bound_sequence,
        "cut_count_sequence": cut_count_sequence,
    }


def rows_to_markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    """Render a compact markdown table."""

    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(column, "")) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, sep, *body])


def summarize_run_logs(logs_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Load all per-run JSON logs keyed by run id."""

    directory = Path(logs_dir)
    logs: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*_run.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        logs[str(payload["run_config"]["run_id"])] = payload
    return logs
