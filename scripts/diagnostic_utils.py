"""Utilities for the Round 12.5 convergence diagnostic pack."""

from __future__ import annotations

from dataclasses import asdict
import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.experiment_pack_utils import (  # noqa: E402
    ensure_directory,
    load_critical_buses,
    load_instance_for_run,
    prepare_instance_for_run,
)
from src.audit.experiment_summary import (  # noqa: E402
    ConvergenceDiagnosticFailureSummary,
    ConvergenceDiagnosticSummary,
)
from src.production.benders_engine import BendersEngineResult, run_benders_engine  # noqa: E402
from src.production.master_problem import (  # noqa: E402
    RestrictedMasterCut,
    RestrictedMasterProblemSolution,
    solve_master_problem,
)


ROUND_12_BASELINE_SOURCES = {
    "summary.csv": REPO_ROOT / "results" / "summary.csv",
    "failures.csv": REPO_ROOT / "results" / "failures.csv",
    "round_12_report.md": REPO_ROOT / "docs" / "reports" / "round_12_report.md",
    "paper_style_experiment_pack.md": REPO_ROOT / "docs" / "analysis_packs" / "paper_style_experiment_pack.md",
}
ROUND_12_BASELINE_DIRS = {
    "figures": REPO_ROOT / "results" / "figures",
    "plans": REPO_ROOT / "results" / "plans",
}
EXACT_ZERO_TOLERANCE = 1e-8


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """Load a YAML mapping from disk."""

    file_path = Path(path)
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{file_path} must contain a YAML mapping.")
    return dict(raw)


def load_diagnostic_manifest(path: str | Path) -> dict[str, Any]:
    """Load the convergence-diagnostic manifest and expand its matrix include."""

    manifest = load_yaml_file(path)
    runs: list[dict[str, Any]] = []
    matrix_include = manifest.get("matrix_include")
    if matrix_include is not None:
        matrix_payload = load_yaml_file(matrix_include)
        runs.extend(dict(run) for run in matrix_payload.get("runs", ()))
    runs.extend(dict(run) for run in manifest.get("runs", ()))
    expanded = dict(manifest)
    expanded["runs"] = runs
    return expanded


def clear_output_directory(output_root: str | Path) -> Path:
    """Remove stale diagnostic artifacts before writing a fresh pack."""

    output_root_path = ensure_directory(output_root)
    for file_name in ("summary.csv", "failures.csv"):
        candidate = output_root_path / file_name
        if candidate.exists():
            candidate.unlink()
    for directory_name in ("figures", "logs"):
        directory = ensure_directory(output_root_path / directory_name)
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()
    return output_root_path


def snapshot_round12_baseline(destination: str | Path) -> Path:
    """Copy the current Round 12 outputs so they remain recoverable."""

    baseline_dir = ensure_directory(destination)
    for path in baseline_dir.iterdir():
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)

    for relative_name, source_path in ROUND_12_BASELINE_SOURCES.items():
        if not source_path.exists():
            raise FileNotFoundError(f"Missing Round 12 baseline source: {source_path}")
        shutil.copy2(source_path, baseline_dir / relative_name)

    for relative_name, source_dir in ROUND_12_BASELINE_DIRS.items():
        if not source_dir.exists():
            raise FileNotFoundError(f"Missing Round 12 baseline directory: {source_dir}")
        shutil.copytree(source_dir, baseline_dir / relative_name)

    return baseline_dir


def write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write stable JSON."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return file_path


def write_summary_csv(
    path: str | Path,
    summaries: Sequence[ConvergenceDiagnosticSummary],
) -> Path:
    """Write the convergence-diagnostic summary CSV."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ConvergenceDiagnosticSummary.__dataclass_fields__.keys())
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            writer.writerow(summary.to_csv_row())
    return file_path


def write_failures_csv(
    path: str | Path,
    failures: Sequence[ConvergenceDiagnosticFailureSummary],
) -> Path:
    """Write the convergence-diagnostic failures CSV."""

    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ConvergenceDiagnosticFailureSummary.__dataclass_fields__.keys())
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for failure in failures:
            writer.writerow(failure.to_csv_row())
    return file_path


def summarize_run_logs(logs_dir: str | Path) -> dict[str, dict[str, Any]]:
    """Load all per-run JSON diagnostic logs keyed by run id."""

    logs: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(logs_dir).glob("*_diagnostic.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        logs[str(payload["run_config"]["run_id"])] = payload
    return logs


def rows_to_markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    """Render a compact markdown table."""

    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(column, "")) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, sep, *body])


def _json_compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _diagnosis_label(
    *,
    validation_level: str,
    final_violation_upper_bound: float | None,
) -> str:
    violation = 0.0 if final_violation_upper_bound is None else float(final_violation_upper_bound)
    if abs(violation) <= EXACT_ZERO_TOLERANCE:
        return "exact_zero"
    if validation_level == "epsilon_certified":
        return "epsilon_stop"
    return "max_iter_noncert"


def _plan_signature(solution: RestrictedMasterProblemSolution) -> tuple[tuple[int, int, int], ...]:
    first_stage = solution.first_stage_solution
    return tuple(
        (
            int(bus),
            int(first_stage.n_sl_by_bus[bus]),
            int(first_stage.n_fa_by_bus[bus]),
        )
        for bus, opened in sorted(first_stage.z_by_bus.items())
        if int(opened) == 1
    )


def _lambda_signature(solution: RestrictedMasterProblemSolution) -> tuple[tuple[str, float], ...]:
    return tuple(
        (str(line_id), round(float(value), 6))
        for line_id, value in sorted(solution.lambda_by_line_id.items())
        if abs(float(value)) > 1e-9
    )


def _cut_signature(cut: RestrictedMasterCut) -> str:
    payload = {
        "beta": round(float(cut.beta), 6),
        "gamma_z_by_bus": {
            str(bus): round(float(value), 6)
            for bus, value in sorted(cut.gamma_z_by_bus.items())
            if abs(float(value)) > 1e-9
        },
        "gamma_n_sl_by_bus": {
            str(bus): round(float(value), 6)
            for bus, value in sorted(cut.gamma_n_sl_by_bus.items())
            if abs(float(value)) > 1e-9
        },
        "gamma_n_fa_by_bus": {
            str(bus): round(float(value), 6)
            for bus, value in sorted(cut.gamma_n_fa_by_bus.items())
            if abs(float(value)) > 1e-9
        },
        "phi_by_line_id": {
            str(line_id): round(float(value), 6)
            for line_id, value in sorted(cut.phi_by_line_id.items())
            if abs(float(value)) > 1e-9
        },
    }
    return hashlib.sha256(_json_compact(payload).encode("utf-8")).hexdigest()[:16]


def _active_lines(outage_by_line_id: Mapping[str, int]) -> tuple[str, ...]:
    return tuple(
        sorted(line_id for line_id, value in outage_by_line_id.items() if int(value) == 1)
    )


def _smallest_omega_slack_lines(
    solution,
    *,
    top_k: int = 5,
) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for line_id in solution.omega_by_line_id:
        lower_slack = float(solution.omega_lower_slack_by_line_id[line_id])
        upper_slack = float(solution.omega_upper_slack_by_line_id[line_id])
        rows.append(
            {
                "line_id": line_id,
                "lower_slack": lower_slack,
                "upper_slack": upper_slack,
                "min_slack": min(lower_slack, upper_slack),
            }
        )
    return sorted(rows, key=lambda row: row["min_slack"])[:top_k]


def _runtime_breakdown(result: BendersEngineResult) -> tuple[float, float, float]:
    master_runtime = float(sum(record.master_solve_seconds for record in result.iterations))
    separation_runtime = float(sum(record.separation_solve_seconds for record in result.iterations))
    dual_runtime = float(sum(record.cut_generation_seconds for record in result.iterations))
    return master_runtime, separation_runtime, dual_runtime


def _selected_outage_trace(result: BendersEngineResult) -> list[list[str]]:
    return [list(_active_lines(record.selected_outage_by_line_id)) for record in result.iterations]


def _repeated_outage_flag(selected_outage_trace: Sequence[Sequence[str]]) -> bool:
    normalized = [tuple(trace) for trace in selected_outage_trace]
    return len(set(normalized)) != len(normalized)


def _cut_diagnostics(
    *,
    instance,
    result: BendersEngineResult,
) -> tuple[list[dict[str, Any]], bool]:
    diagnostics: list[dict[str, Any]] = []
    repeated_cut_signature_flag = False
    seen_signatures: set[str] = set()
    cumulative_cuts: list[RestrictedMasterCut] = []

    generated_results_by_id = {
        generated.cut.cut_id: generated for generated in result.generated_cut_results
    }
    for record in result.iterations:
        if record.generated_cut_id is None:
            continue
        generated = generated_results_by_id[record.generated_cut_id]
        cut_signature = _cut_signature(generated.cut)
        if cut_signature in seen_signatures:
            repeated_cut_signature_flag = True
        seen_signatures.add(cut_signature)

        _, pre_solution = solve_master_problem(
            instance,
            cuts=tuple(cumulative_cuts),
            model_name=f"diag_pre_{record.generated_cut_id}",
        )
        _, post_solution = solve_master_problem(
            instance,
            cuts=tuple(cumulative_cuts + [generated.cut]),
            model_name=f"diag_post_{record.generated_cut_id}",
        )
        pre_plan_signature = _plan_signature(pre_solution)
        post_plan_signature = _plan_signature(post_solution)
        pre_lambda_signature = _lambda_signature(pre_solution)
        post_lambda_signature = _lambda_signature(post_solution)
        plan_changed = pre_plan_signature != post_plan_signature
        alpha_lambda_changed = (
            abs(float(pre_solution.alpha_value) - float(post_solution.alpha_value)) > 1e-9
            or pre_lambda_signature != post_lambda_signature
        )
        diagnostics.append(
            {
                "iteration_id": int(record.iteration_id),
                "cut_id": generated.cut.cut_id,
                "cut_signature": cut_signature,
                "old_master_violation": None
                if generated.old_master_cut_violation is None
                else float(generated.old_master_cut_violation),
                "post_cut_master_objective_change": None
                if record.post_cut_master_objective is None
                else float(record.post_cut_master_objective - record.pre_cut_master_objective),
                "plan_changed": plan_changed,
                "alpha_lambda_only": (not plan_changed) and alpha_lambda_changed,
                "pre_plan_signature": list(pre_plan_signature),
                "post_plan_signature": list(post_plan_signature),
            }
        )
        cumulative_cuts.append(generated.cut)

    return diagnostics, repeated_cut_signature_flag


def _build_notes(
    *,
    diagnosis_label: str,
    validation_level: str,
    stop_reason: str,
    epsilon_cert: float,
    max_iterations: int,
    lower_bound_sequence: Sequence[float],
    violation_sequence: Sequence[float],
    repeated_outage_flag: bool,
    repeated_cut_signature_flag: bool,
    runtime_breakdown: tuple[float, float, float],
) -> str:
    notes: list[str] = []
    if diagnosis_label == "exact_zero":
        notes.append("final violation reached zero within tolerance")
    elif diagnosis_label == "epsilon_stop":
        notes.append(
            f"epsilon stop by design: final violation stayed nonzero but below epsilon_cert={epsilon_cert}"
        )
    else:
        if stop_reason == "max_iterations" and max_iterations <= 2:
            notes.append("intentionally bounded smoke run with low iteration budget")
        elif stop_reason == "max_iterations":
            notes.append("true non-certification under enlarged iteration budget")
        else:
            notes.append(f"non-certified stop_reason={stop_reason}")

    if len(lower_bound_sequence) >= 2:
        lb_gain = float(lower_bound_sequence[-1] - lower_bound_sequence[0])
        notes.append(f"lower-bound gain={lb_gain:.3f}")
    if len(violation_sequence) >= 2:
        violation_drop = float(violation_sequence[0] - violation_sequence[-1])
        notes.append(f"violation drop={violation_drop:.3f}")
        if abs(violation_drop) < 1e-6:
            notes.append("lower-bound / violation stagnation is visible")

    master_runtime, separation_runtime, dual_runtime = runtime_breakdown
    dominant = max(
        (
            ("master-side", master_runtime),
            ("separation-side", separation_runtime),
            ("dual-resolve-side", dual_runtime),
        ),
        key=lambda item: item[1],
    )[0]
    notes.append(f"dominant runtime component: {dominant}")
    if repeated_outage_flag:
        notes.append("repeated outage pattern observed")
    if repeated_cut_signature_flag:
        notes.append("repeated cut signature observed")
    if validation_level == "smoke_only":
        notes.append("smoke_only result should not be promoted beyond directional diagnosis")
    return "; ".join(notes)


def _selected_support_text(instance) -> tuple[str, str]:
    return (
        _json_compact(list(instance.sets.loaded_normal_scenarios)),
        _json_compact(list(instance.sets.loaded_disaster_scenarios)),
    )


def _diagnostic_summary_from_direct(
    *,
    run_config: Mapping[str, Any],
    instance,
    solution: RestrictedMasterProblemSolution,
    total_runtime_sec: float,
) -> tuple[ConvergenceDiagnosticSummary, ConvergenceDiagnosticFailureSummary | None, dict[str, Any]]:
    A_selected, B_selected = _selected_support_text(instance)
    final_violation = 0.0
    validation_level = "exact" if solution.model_status == "OPTIMAL" else "failed"
    diagnosis_label = _diagnosis_label(
        validation_level=validation_level,
        final_violation_upper_bound=final_violation,
    )
    notes = "direct master baseline; no Benders separation or cut generation"
    summary = ConvergenceDiagnosticSummary(
        run_id=str(run_config["run_id"]),
        case_name=str(run_config["case_name"]),
        parameter_regime=str(run_config["parameter_regime"]),
        validation_level=validation_level,
        diagnosis_label=diagnosis_label,
        stop_reason="direct_optimal" if solution.model_status == "OPTIMAL" else solution.model_status,
        solver_status=str(solution.model_status),
        epsilon_cert=0.0,
        max_iterations=0,
        A_selected=A_selected,
        B_selected=B_selected,
        K=int(instance.ambiguity.k_max_outages),
        iteration_count=0,
        cut_count=1,
        final_violation_upper_bound=final_violation,
        sampled_problem_gap_bound=0.0,
        total_objective=float(solution.objective_value or 0.0),
        construction_cost=float(solution.construction_cost_value),
        weighted_normal_term=float(solution.averaged_normal_cost_value),
        disaster_master_term=float(solution.disaster_master_cost_value),
        final_alpha=float(solution.alpha_value),
        final_lambda_times_FP=float(solution.lambda_fp_value),
        total_runtime_sec=float(total_runtime_sec),
        master_runtime_sec_total=float(total_runtime_sec),
        separation_runtime_sec_total=0.0,
        dual_resolve_runtime_sec_total=0.0,
        generated_cut_count=0,
        selected_outage_trace="[]",
        lower_bound_sequence="[]",
        violation_sequence="[]",
        cut_efficacy_sequence="[]",
        repeated_outage_flag=False,
        repeated_cut_signature_flag=False,
        notes=notes,
    )
    payload = {
        "type": "direct_master",
        "summary": summary.to_csv_row(),
    }
    failure = None
    if validation_level == "failed":
        failure = ConvergenceDiagnosticFailureSummary(
            run_id=summary.run_id,
            case_name=summary.case_name,
            parameter_regime=summary.parameter_regime,
            validation_level=summary.validation_level,
            diagnosis_label=summary.diagnosis_label,
            stop_reason=summary.stop_reason,
            solver_status=summary.solver_status,
            epsilon_cert=0.0,
            max_iterations=0,
            A_selected=A_selected,
            B_selected=B_selected,
            K=int(instance.ambiguity.k_max_outages),
            iteration_count=0,
            cut_count=1,
            final_violation_upper_bound=0.0,
            sampled_problem_gap_bound=0.0,
            total_runtime_sec=float(total_runtime_sec),
            message="Direct master did not reach OPTIMAL status.",
        )
    return summary, failure, payload


def _diagnostic_summary_from_benders(
    *,
    run_config: Mapping[str, Any],
    instance,
    result: BendersEngineResult,
    total_runtime_sec: float,
) -> tuple[ConvergenceDiagnosticSummary, ConvergenceDiagnosticFailureSummary | None, dict[str, Any]]:
    iteration_log_path = None if result.iteration_log_path is None else str(result.iteration_log_path)
    A_selected, B_selected = _selected_support_text(instance)
    master_runtime, separation_runtime, dual_runtime = _runtime_breakdown(result)
    selected_outage_trace = _selected_outage_trace(result)
    repeated_outage_flag = _repeated_outage_flag(selected_outage_trace)
    cut_efficacy_rows, repeated_cut_signature_flag = _cut_diagnostics(
        instance=instance,
        result=result,
    )
    violation_sequence = [
        float(record.separation_violation_value) for record in result.iterations
    ]
    diagnosis_label = _diagnosis_label(
        validation_level=(
            "exact"
            if result.stop_reason == "certified_exact"
            else "epsilon_certified"
            if result.stop_reason == "certified_epsilon"
            else "smoke_only"
        ),
        final_violation_upper_bound=result.certificate.final_violation_upper_bound,
    )
    validation_level = (
        "exact"
        if result.stop_reason == "certified_exact"
        else "epsilon_certified"
        if result.stop_reason == "certified_epsilon"
        else "smoke_only"
        if result.final_solution.model_status == "OPTIMAL"
        else "failed"
    )
    notes = _build_notes(
        diagnosis_label=diagnosis_label,
        validation_level=validation_level,
        stop_reason=result.stop_reason,
        epsilon_cert=float(result.epsilon_cert),
        max_iterations=int(run_config.get("benders", {}).get("max_iterations", len(result.iterations))),
        lower_bound_sequence=result.lower_bound_sequence,
        violation_sequence=violation_sequence,
        repeated_outage_flag=repeated_outage_flag,
        repeated_cut_signature_flag=repeated_cut_signature_flag,
        runtime_breakdown=(master_runtime, separation_runtime, dual_runtime),
    )
    summary = ConvergenceDiagnosticSummary(
        run_id=str(run_config["run_id"]),
        case_name=str(run_config["case_name"]),
        parameter_regime=str(run_config["parameter_regime"]),
        validation_level=validation_level,
        diagnosis_label=diagnosis_label,
        stop_reason=str(result.stop_reason),
        solver_status=str(result.final_solution.model_status),
        epsilon_cert=float(result.epsilon_cert),
        max_iterations=int(run_config.get("benders", {}).get("max_iterations", len(result.iterations))),
        A_selected=A_selected,
        B_selected=B_selected,
        K=int(instance.ambiguity.k_max_outages),
        iteration_count=len(result.iterations),
        cut_count=len(result.final_master.cuts),
        final_violation_upper_bound=float(result.certificate.final_violation_upper_bound),
        sampled_problem_gap_bound=float(result.certificate.sampled_problem_gap_bound),
        total_objective=float(result.final_solution.objective_value or 0.0),
        construction_cost=float(result.final_solution.construction_cost_value),
        weighted_normal_term=float(result.final_solution.averaged_normal_cost_value),
        disaster_master_term=float(result.final_solution.disaster_master_cost_value),
        final_alpha=float(result.final_solution.alpha_value),
        final_lambda_times_FP=float(result.final_solution.lambda_fp_value),
        total_runtime_sec=float(total_runtime_sec),
        master_runtime_sec_total=master_runtime,
        separation_runtime_sec_total=separation_runtime,
        dual_resolve_runtime_sec_total=dual_runtime,
        generated_cut_count=len(result.generated_cut_results),
        selected_outage_trace=_json_compact(selected_outage_trace),
        lower_bound_sequence=_json_compact(list(result.lower_bound_sequence)),
        violation_sequence=_json_compact(violation_sequence),
        cut_efficacy_sequence=_json_compact(cut_efficacy_rows),
        repeated_outage_flag=repeated_outage_flag,
        repeated_cut_signature_flag=repeated_cut_signature_flag,
        notes=notes,
    )
    final_separation = result.final_separation_solution
    omega_diag = {
        "max_omega_bound_violation": float(final_separation.max_omega_bound_violation),
        "tight_lower_count": int(
            sum(1 for value in final_separation.omega_lower_slack_by_line_id.values() if abs(float(value)) <= 1e-8)
        ),
        "tight_upper_count": int(
            sum(1 for value in final_separation.omega_upper_slack_by_line_id.values() if abs(float(value)) <= 1e-8)
        ),
        "smallest_slack_lines": _smallest_omega_slack_lines(final_separation),
    }
    payload = {
        "type": "benders",
        "summary": summary.to_csv_row(),
        "iteration_log_path": iteration_log_path,
        "lower_bound_sequence": list(result.lower_bound_sequence),
        "cut_count_sequence": list(result.cut_count_sequence),
        "violation_sequence": violation_sequence,
        "selected_outage_trace": selected_outage_trace,
        "cut_efficacy_sequence": cut_efficacy_rows,
        "omega_diagnostics": omega_diag,
        "generated_cut_ids": [generated.cut.cut_id for generated in result.generated_cut_results],
        "generated_cut_signatures": {
            generated.cut.cut_id: _cut_signature(generated.cut)
            for generated in result.generated_cut_results
        },
        "iteration_artifact": asdict(result.iteration_log_artifact),
    }

    failure = None
    if validation_level in {"smoke_only", "failed"}:
        failure = ConvergenceDiagnosticFailureSummary(
            run_id=summary.run_id,
            case_name=summary.case_name,
            parameter_regime=summary.parameter_regime,
            validation_level=summary.validation_level,
            diagnosis_label=summary.diagnosis_label,
            stop_reason=summary.stop_reason,
            solver_status=summary.solver_status,
            epsilon_cert=summary.epsilon_cert,
            max_iterations=summary.max_iterations,
            A_selected=summary.A_selected,
            B_selected=summary.B_selected,
            K=summary.K,
            iteration_count=summary.iteration_count,
            cut_count=summary.cut_count,
            final_violation_upper_bound=summary.final_violation_upper_bound,
            sampled_problem_gap_bound=summary.sampled_problem_gap_bound,
            total_runtime_sec=summary.total_runtime_sec,
            message=notes,
        )
    return summary, failure, payload


def execute_diagnostic_run(
    run_config: Mapping[str, Any],
    *,
    critical_buses: Sequence[int],
    output_root: str | Path,
) -> dict[str, Any]:
    """Execute one convergence-diagnostic run and return auditable artifacts."""

    output_root_path = ensure_directory(output_root)
    logs_dir = ensure_directory(output_root_path / "logs")

    run_id = str(run_config["run_id"])
    solver = str(run_config["solver"])
    start = perf_counter()
    summary: ConvergenceDiagnosticSummary | None = None
    failure: ConvergenceDiagnosticFailureSummary | None = None
    payload: dict[str, Any] = {}
    exception_payload: dict[str, Any] | None = None

    try:
        base_instance = load_instance_for_run(run_config, critical_buses=critical_buses)
        instance = prepare_instance_for_run(base_instance, run_config)
        if solver == "direct_master":
            _, solution = solve_master_problem(
                instance,
                model_name=f"{run_id}_diagnostic_direct",
            )
            summary, failure, payload = _diagnostic_summary_from_direct(
                run_config=run_config,
                instance=instance,
                solution=solution,
                total_runtime_sec=perf_counter() - start,
            )
        elif solver == "benders":
            benders_cfg = dict(run_config.get("benders", {}))
            result = run_benders_engine(
                instance,
                epsilon_cert=float(benders_cfg.get("epsilon_cert", 0.0)),
                max_iterations=int(benders_cfg.get("max_iterations", 25)),
                model_name_prefix=f"{run_id}_diagnostic",
                iteration_log_path=logs_dir / f"{run_id}_iteration_log.json",
            )
            summary, failure, payload = _diagnostic_summary_from_benders(
                run_config=run_config,
                instance=instance,
                result=result,
                total_runtime_sec=perf_counter() - start,
            )
        else:
            raise ValueError(f"Unsupported solver {solver!r}.")
    except Exception as exc:  # pragma: no cover - exercised by integration path
        elapsed = perf_counter() - start
        selection = run_config.get("selection", {})
        A_selected = _json_compact(list(selection.get("scenarios_a", [])))
        B_selected = _json_compact(list(selection.get("scenarios_b", [])))
        max_iterations = int(run_config.get("benders", {}).get("max_iterations", 0))
        epsilon_cert = float(run_config.get("benders", {}).get("epsilon_cert", 0.0))
        summary = ConvergenceDiagnosticSummary(
            run_id=str(run_config["run_id"]),
            case_name=str(run_config["case_name"]),
            parameter_regime=str(run_config["parameter_regime"]),
            validation_level="failed",
            diagnosis_label="max_iter_noncert",
            stop_reason="exception",
            solver_status="EXCEPTION",
            epsilon_cert=epsilon_cert,
            max_iterations=max_iterations,
            A_selected=A_selected,
            B_selected=B_selected,
            K=int(run_config.get("parameter_overrides", {}).get("ambiguity", {}).get("k_max_outages", 0)),
            iteration_count=0,
            cut_count=0,
            final_violation_upper_bound=None,
            sampled_problem_gap_bound=None,
            total_objective=None,
            construction_cost=None,
            weighted_normal_term=None,
            disaster_master_term=None,
            final_alpha=None,
            final_lambda_times_FP=None,
            total_runtime_sec=float(elapsed),
            master_runtime_sec_total=0.0,
            separation_runtime_sec_total=0.0,
            dual_resolve_runtime_sec_total=0.0,
            generated_cut_count=0,
            selected_outage_trace="[]",
            lower_bound_sequence="[]",
            violation_sequence="[]",
            cut_efficacy_sequence="[]",
            repeated_outage_flag=False,
            repeated_cut_signature_flag=False,
            notes=f"{exc.__class__.__name__}: {exc}",
        )
        failure = ConvergenceDiagnosticFailureSummary(
            run_id=summary.run_id,
            case_name=summary.case_name,
            parameter_regime=summary.parameter_regime,
            validation_level=summary.validation_level,
            diagnosis_label=summary.diagnosis_label,
            stop_reason=summary.stop_reason,
            solver_status=summary.solver_status,
            epsilon_cert=summary.epsilon_cert,
            max_iterations=summary.max_iterations,
            A_selected=summary.A_selected,
            B_selected=summary.B_selected,
            K=summary.K,
            iteration_count=0,
            cut_count=0,
            final_violation_upper_bound=None,
            sampled_problem_gap_bound=None,
            total_runtime_sec=float(elapsed),
            message=f"{exc.__class__.__name__}: {exc}",
        )
        exception_payload = {"type": exc.__class__.__name__, "message": str(exc)}

    log_payload = {
        "run_config": dict(run_config),
        "summary": summary.to_csv_row() if summary is not None else None,
        "failure_record": None if failure is None else failure.to_csv_row(),
        "exception": exception_payload,
        "diagnostics": payload,
    }
    log_path = write_json(logs_dir / f"{run_id}_diagnostic.json", log_payload)
    return {
        "summary": summary,
        "failure": failure,
        "log_path": str(log_path),
        "iteration_log_path": payload.get("iteration_log_path"),
    }
