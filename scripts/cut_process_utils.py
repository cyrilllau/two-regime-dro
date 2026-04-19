"""Utilities for the Round 13 cut-process diagnostic pack."""

from __future__ import annotations

from dataclasses import asdict
import csv
import json
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
    CutProcessDiagnosticCutRow,
    CutProcessDiagnosticFailureSummary,
    CutProcessDiagnosticSummary,
)
from src.production.benders_engine import BendersEngineResult, run_benders_engine  # noqa: E402


EXACT_ZERO_TOLERANCE = 1e-8
PAPER_LIKE_OVERRIDES = {
    "economics": {
        "cfix": 153600.0,
        "ccons_sl": 540.07,
        "ccons_fa": 25000.0,
        "ctrans_scalar": 0.0435,
        "gamma": 0.01,
        "theta": 20,
        "pi_f": 0.3,
    },
    "ev": {
        "p_ev_rated_sl": 7.0,
        "p_ev_rated_fa": 50.0,
        "nbar_sl": 25,
        "nbar_fa": 10,
    },
}


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    raw = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{file_path} must contain a YAML mapping.")
    return dict(raw)


def _clone_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload))


def _baseline_and_improved(base_run: Mapping[str, Any]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for variant, dedup_enabled, outage_guard_enabled in (
        ("baseline", False, False),
        ("improved", True, True),
    ):
        copied = _clone_mapping(base_run)
        copied["variant"] = variant
        copied["run_id"] = f"{base_run['comparison_group']}__{variant}"
        copied.setdefault("benders", {})
        copied["benders"]["enable_cut_signature_dedup"] = dedup_enabled
        copied["benders"]["enable_repeated_outage_guard"] = outage_guard_enabled
        runs.append(copied)
    return runs


def build_default_run_matrix() -> list[dict[str, Any]]:
    """Return the bounded Round 13 diagnostic matrix."""

    runs: list[dict[str, Any]] = []
    for max_iterations in (10, 20, 40):
        runs.extend(
            _baseline_and_improved(
                {
                    "comparison_group": f"integrated_paper_like_exact_i{max_iterations}_k2_a1b1",
                    "case_name": "integrated_paper_like_exact",
                    "parameter_regime": "paper_like_exact",
                    "runtime_source": "data/runtime_12",
                    "selection": {"scenarios_a": [1], "scenarios_b": [1]},
                    "mode": "integrated_mainline",
                    "solver": "benders",
                    "parameter_overrides": PAPER_LIKE_OVERRIDES,
                    "benders": {
                        "epsilon_cert": 0.0,
                        "max_iterations": max_iterations,
                    },
                }
            )
        )
    for budget_k in (1, 2):
        for max_iterations in (5, 20, 40):
            runs.extend(
                _baseline_and_improved(
                    {
                        "comparison_group": f"disaster_only_paper_like_exact_i{max_iterations}_k{budget_k}_a1b1",
                        "case_name": "disaster_only_paper_like_exact",
                        "parameter_regime": "paper_like_exact",
                        "runtime_source": "data/runtime_12",
                        "selection": {"scenarios_a": [1], "scenarios_b": [1]},
                        "mode": "disaster_only",
                        "solver": "benders",
                        "parameter_overrides": {
                            **_clone_mapping(PAPER_LIKE_OVERRIDES),
                            "ambiguity": {"k_max_outages": budget_k},
                        },
                        "benders": {
                            "epsilon_cert": 0.0,
                            "max_iterations": max_iterations,
                        },
                    }
                )
            )
    runs.extend(
        _baseline_and_improved(
            {
                "comparison_group": "integrated_runtime12_exact_i3_k3_a1234b1234",
                "case_name": "integrated_runtime12_exact",
                "parameter_regime": "runtime12_directional_exact",
                "runtime_source": "data/runtime_12",
                "selection": {"scenarios_a": [1, 2, 3, 4], "scenarios_b": [1, 2, 3, 4]},
                "mode": "integrated_mainline",
                "solver": "benders",
                "parameter_overrides": {
                    "ambiguity": {"k_max_outages": 3},
                },
                "benders": {
                    "epsilon_cert": 0.0,
                    "max_iterations": 3,
                    "capture_lp_artifacts": True,
                },
            }
        )
    )
    return runs


def load_cut_process_matrix(path: str | Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        return build_default_run_matrix()
    raw = load_yaml_file(path)
    return [dict(run) for run in raw.get("runs", ())]


def clear_output_directory(output_root: str | Path) -> Path:
    output_root_path = ensure_directory(output_root)
    for file_name in ("summary.csv", "failures.csv", "cut_diagnostics.csv"):
        candidate = output_root_path / file_name
        if candidate.exists():
            candidate.unlink()
    for directory_name in ("figures", "logs", "lp"):
        directory = ensure_directory(output_root_path / directory_name)
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()
    return output_root_path


def write_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return file_path


def _csv_write(path: str | Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> Path:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return file_path


def write_summary_csv(path: str | Path, rows: Sequence[CutProcessDiagnosticSummary]) -> Path:
    return _csv_write(
        path,
        list(CutProcessDiagnosticSummary.__dataclass_fields__.keys()),
        [row.to_csv_row() for row in rows],
    )


def write_failures_csv(path: str | Path, rows: Sequence[CutProcessDiagnosticFailureSummary]) -> Path:
    return _csv_write(
        path,
        list(CutProcessDiagnosticFailureSummary.__dataclass_fields__.keys()),
        [row.to_csv_row() for row in rows],
    )


def write_cut_diagnostics_csv(path: str | Path, rows: Sequence[CutProcessDiagnosticCutRow]) -> Path:
    return _csv_write(
        path,
        list(CutProcessDiagnosticCutRow.__dataclass_fields__.keys()),
        [row.to_csv_row() for row in rows],
    )


def rows_to_markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(column, "")) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, sep, *body])


def _json_compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _selected_support_text(instance) -> tuple[str, str]:
    return (
        _json_compact(list(instance.sets.loaded_normal_scenarios)),
        _json_compact(list(instance.sets.loaded_disaster_scenarios)),
    )


def _validation_level_from_result(result: BendersEngineResult) -> str:
    if result.stop_reason == "certified_exact":
        return "exact"
    if result.stop_reason == "certified_epsilon":
        return "epsilon_certified"
    if str(result.final_solution.model_status).upper() == "OPTIMAL":
        return "smoke_only"
    return "failed"


def _diagnosis_label(validation_level: str, final_violation_upper_bound: float | None) -> str:
    violation = 0.0 if final_violation_upper_bound is None else float(final_violation_upper_bound)
    if abs(violation) <= EXACT_ZERO_TOLERANCE:
        return "exact_zero"
    if validation_level == "epsilon_certified":
        return "epsilon_stop"
    return "max_iter_noncert"


def _dominant_cause(
    *,
    repeated_outage_count: int,
    repeated_cut_signature_count: int,
    alpha_lambda_only_cut_count: int,
    plan_change_cut_count: int,
    generated_cut_count: int,
    lower_bound_gain: float,
) -> str:
    if repeated_cut_signature_count > 0:
        return "repeated cut signatures"
    if repeated_outage_count > 0:
        return "repeated outages"
    if generated_cut_count > 0 and alpha_lambda_only_cut_count >= max(1, generated_cut_count // 2):
        return "weak cuts that change only alpha/lambda"
    if generated_cut_count > 0 and plan_change_cut_count <= max(1, generated_cut_count // 4):
        return "weak cuts that change only alpha/lambda"
    if lower_bound_gain <= 1e-6:
        return "master-side growth / slow lower-bound improvement"
    return "other evidenced cause"


def _build_notes(
    *,
    validation_level: str,
    diagnosis_label: str,
    stop_reason: str,
    repeated_outage_count: int,
    repeated_cut_signature_count: int,
    alpha_lambda_only_cut_count: int,
    plan_change_cut_count: int,
    generated_cut_count: int,
    lower_bound_gain: float,
) -> str:
    notes: list[str] = [f"stop_reason={stop_reason}", f"diagnosis={diagnosis_label}"]
    if validation_level == "smoke_only":
        notes.append("non-certified run remains smoke_only")
    if repeated_outage_count > 0:
        notes.append(f"repeated outages={repeated_outage_count}")
    if repeated_cut_signature_count > 0:
        notes.append(f"repeated cut signatures={repeated_cut_signature_count}")
    if generated_cut_count > 0:
        notes.append(f"plan-changing cuts={plan_change_cut_count}/{generated_cut_count}")
        notes.append(f"alpha/lambda-only cuts={alpha_lambda_only_cut_count}/{generated_cut_count}")
    notes.append(f"lower-bound gain={lower_bound_gain:.3f}")
    return "; ".join(notes)


def _cut_rows_from_result(
    *,
    run_config: Mapping[str, Any],
    result: BendersEngineResult,
) -> list[CutProcessDiagnosticCutRow]:
    rows: list[CutProcessDiagnosticCutRow] = []
    for record in result.iterations:
        if record.generated_cut_id is None:
            continue
        rows.append(
            CutProcessDiagnosticCutRow(
                comparison_group=str(run_config["comparison_group"]),
                variant=str(run_config["variant"]),
                run_id=str(run_config["run_id"]),
                case_name=str(run_config["case_name"]),
                parameter_regime=str(run_config["parameter_regime"]),
                iteration_id=int(record.iteration_id),
                cut_id=str(record.generated_cut_id),
                source_outage_vector=_json_compact(record.selected_outage_by_line_id),
                source_outage_active_lines=_json_compact(list(record.selected_outage_active_lines)),
                repeated_outage_flag=bool(record.repeated_outage_flag),
                cut_signature_hash=str(record.generated_cut_signature_hash or ""),
                repeated_cut_signature_flag=bool(record.repeated_cut_signature_flag),
                old_master_violation_at_source=record.generated_cut_old_master_violation,
                post_cut_objective_change=record.post_cut_master_objective_change,
                first_stage_plan_changed=record.first_stage_plan_changed,
                alpha_lambda_only_change=record.alpha_lambda_only_change,
                gamma_z_nonzero_count=record.gamma_z_nonzero_count,
                gamma_n_sl_nonzero_count=record.gamma_n_sl_nonzero_count,
                gamma_n_fa_nonzero_count=record.gamma_n_fa_nonzero_count,
                phi_nonzero_count=record.phi_nonzero_count,
                cut_added=bool(record.cut_added),
                cut_addition_status=record.cut_addition_status,
            )
        )
    return rows


def execute_cut_process_run(
    run_config: Mapping[str, Any],
    *,
    critical_buses: Sequence[int],
    output_root: str | Path,
) -> dict[str, Any]:
    output_root_path = ensure_directory(output_root)
    logs_dir = ensure_directory(output_root_path / "logs")
    lp_dir = ensure_directory(output_root_path / "lp")
    run_id = str(run_config["run_id"])
    start = perf_counter()
    summary: CutProcessDiagnosticSummary | None = None
    failure: CutProcessDiagnosticFailureSummary | None = None
    cut_rows: list[CutProcessDiagnosticCutRow] = []
    payload: dict[str, Any] = {}
    exception_payload: dict[str, Any] | None = None

    try:
        base_instance = load_instance_for_run(run_config, critical_buses=critical_buses)
        instance = prepare_instance_for_run(base_instance, run_config)
        benders_cfg = dict(run_config.get("benders", {}))
        capture_lp = bool(benders_cfg.get("capture_lp_artifacts", False))
        before_lp_path = (
            lp_dir / f"{run_id}_master_before.lp" if capture_lp else None
        )
        after_lp_path = (
            lp_dir / f"{run_id}_master_after.lp" if capture_lp else None
        )
        result = run_benders_engine(
            instance,
            epsilon_cert=float(benders_cfg.get("epsilon_cert", 0.0)),
            max_iterations=int(benders_cfg.get("max_iterations", 25)),
            enable_cut_signature_dedup=bool(
                benders_cfg.get("enable_cut_signature_dedup", False)
            ),
            enable_repeated_outage_guard=bool(
                benders_cfg.get("enable_repeated_outage_guard", False)
            ),
            model_name_prefix=f"{run_id}_cut_process",
            master_before_cut_lp_path=before_lp_path,
            master_after_cut_lp_path=after_lp_path,
            iteration_log_path=logs_dir / f"{run_id}_iteration_log.json",
        )
        elapsed = perf_counter() - start
        validation_level = _validation_level_from_result(result)
        diagnosis_label = _diagnosis_label(
            validation_level,
            result.certificate.final_violation_upper_bound,
        )
        repeated_outage_count = sum(1 for record in result.iterations if record.repeated_outage_flag)
        repeated_cut_signature_count = sum(
            1 for record in result.iterations if record.repeated_cut_signature_flag
        )
        alpha_lambda_only_cut_count = sum(
            1 for record in result.iterations if record.alpha_lambda_only_change is True
        )
        plan_change_cut_count = sum(
            1 for record in result.iterations if record.first_stage_plan_changed is True
        )
        lower_bound_gain = (
            float(result.lower_bound_sequence[-1] - result.lower_bound_sequence[0])
            if result.lower_bound_sequence
            else 0.0
        )
        dominant_cause = _dominant_cause(
            repeated_outage_count=repeated_outage_count,
            repeated_cut_signature_count=repeated_cut_signature_count,
            alpha_lambda_only_cut_count=alpha_lambda_only_cut_count,
            plan_change_cut_count=plan_change_cut_count,
            generated_cut_count=len(result.generated_cut_results),
            lower_bound_gain=lower_bound_gain,
        )
        A_selected, B_selected = _selected_support_text(instance)
        master_runtime = float(sum(record.master_solve_seconds for record in result.iterations))
        separation_runtime = float(
            sum(record.separation_solve_seconds for record in result.iterations)
        )
        dual_runtime = float(sum(record.cut_generation_seconds for record in result.iterations))
        summary = CutProcessDiagnosticSummary(
            comparison_group=str(run_config["comparison_group"]),
            variant=str(run_config["variant"]),
            run_id=run_id,
            case_name=str(run_config["case_name"]),
            parameter_regime=str(run_config["parameter_regime"]),
            validation_level=validation_level,
            diagnosis_label=diagnosis_label,
            stop_reason=str(result.stop_reason),
            solver_status=str(result.final_solution.model_status),
            epsilon_cert=float(result.epsilon_cert),
            max_iterations=int(benders_cfg.get("max_iterations", len(result.iterations))),
            A_selected=A_selected,
            B_selected=B_selected,
            K=int(instance.ambiguity.k_max_outages),
            cut_signature_dedup_enabled=bool(
                benders_cfg.get("enable_cut_signature_dedup", False)
            ),
            repeated_outage_guard_enabled=bool(
                benders_cfg.get("enable_repeated_outage_guard", False)
            ),
            iteration_count=len(result.iterations),
            cut_count=len(result.final_master.cuts),
            generated_cut_count=len(result.generated_cut_results),
            final_violation_upper_bound=float(result.certificate.final_violation_upper_bound),
            sampled_problem_gap_bound=float(result.certificate.sampled_problem_gap_bound),
            total_objective=float(result.final_solution.objective_value or 0.0),
            construction_cost=float(result.final_solution.construction_cost_value),
            weighted_normal_term=float(result.final_solution.averaged_normal_cost_value),
            disaster_master_term=float(result.final_solution.disaster_master_cost_value),
            total_runtime_sec=float(elapsed),
            master_runtime_sec_total=master_runtime,
            separation_runtime_sec_total=separation_runtime,
            dual_resolve_runtime_sec_total=dual_runtime,
            repeated_outage_count=repeated_outage_count,
            repeated_cut_signature_count=repeated_cut_signature_count,
            alpha_lambda_only_cut_count=alpha_lambda_only_cut_count,
            plan_change_cut_count=plan_change_cut_count,
            lower_bound_gain=lower_bound_gain,
            dominant_cause=dominant_cause,
            notes=_build_notes(
                validation_level=validation_level,
                diagnosis_label=diagnosis_label,
                stop_reason=result.stop_reason,
                repeated_outage_count=repeated_outage_count,
                repeated_cut_signature_count=repeated_cut_signature_count,
                alpha_lambda_only_cut_count=alpha_lambda_only_cut_count,
                plan_change_cut_count=plan_change_cut_count,
                generated_cut_count=len(result.generated_cut_results),
                lower_bound_gain=lower_bound_gain,
            ),
            iteration_log_path=None if result.iteration_log_path is None else str(result.iteration_log_path),
            master_before_cut_lp_path=None if result.master_before_cut_lp_path is None else str(result.master_before_cut_lp_path),
            master_after_cut_lp_path=None if result.master_after_cut_lp_path is None else str(result.master_after_cut_lp_path),
        )
        if validation_level in {"smoke_only", "failed"}:
            failure = CutProcessDiagnosticFailureSummary(
                comparison_group=summary.comparison_group,
                variant=summary.variant,
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
                generated_cut_count=summary.generated_cut_count,
                final_violation_upper_bound=summary.final_violation_upper_bound,
                sampled_problem_gap_bound=summary.sampled_problem_gap_bound,
                total_runtime_sec=summary.total_runtime_sec,
                dominant_cause=summary.dominant_cause,
                message=summary.notes,
            )
        cut_rows = _cut_rows_from_result(run_config=run_config, result=result)
        payload = {
            "summary": summary.to_csv_row(),
            "cut_rows": [row.to_csv_row() for row in cut_rows],
            "iteration_log_path": summary.iteration_log_path,
            "master_before_cut_lp_path": summary.master_before_cut_lp_path,
            "master_after_cut_lp_path": summary.master_after_cut_lp_path,
            "lower_bound_sequence": list(result.lower_bound_sequence),
            "cut_count_sequence": list(result.cut_count_sequence),
            "iteration_artifact": asdict(result.iteration_log_artifact),
        }
    except Exception as exc:  # pragma: no cover - integration path
        elapsed = perf_counter() - start
        selection = run_config.get("selection", {})
        summary = CutProcessDiagnosticSummary(
            comparison_group=str(run_config["comparison_group"]),
            variant=str(run_config["variant"]),
            run_id=run_id,
            case_name=str(run_config["case_name"]),
            parameter_regime=str(run_config["parameter_regime"]),
            validation_level="failed",
            diagnosis_label="max_iter_noncert",
            stop_reason="exception",
            solver_status="EXCEPTION",
            epsilon_cert=float(run_config.get("benders", {}).get("epsilon_cert", 0.0)),
            max_iterations=int(run_config.get("benders", {}).get("max_iterations", 0)),
            A_selected=_json_compact(list(selection.get("scenarios_a", []))),
            B_selected=_json_compact(list(selection.get("scenarios_b", []))),
            K=int(
                run_config.get("parameter_overrides", {})
                .get("ambiguity", {})
                .get("k_max_outages", 0)
            ),
            cut_signature_dedup_enabled=bool(
                run_config.get("benders", {}).get("enable_cut_signature_dedup", False)
            ),
            repeated_outage_guard_enabled=bool(
                run_config.get("benders", {}).get("enable_repeated_outage_guard", False)
            ),
            iteration_count=0,
            cut_count=0,
            generated_cut_count=0,
            final_violation_upper_bound=None,
            sampled_problem_gap_bound=None,
            total_objective=None,
            construction_cost=None,
            weighted_normal_term=None,
            disaster_master_term=None,
            total_runtime_sec=float(elapsed),
            master_runtime_sec_total=0.0,
            separation_runtime_sec_total=0.0,
            dual_resolve_runtime_sec_total=0.0,
            repeated_outage_count=0,
            repeated_cut_signature_count=0,
            alpha_lambda_only_cut_count=0,
            plan_change_cut_count=0,
            lower_bound_gain=None,
            dominant_cause="other evidenced cause",
            notes=f"{exc.__class__.__name__}: {exc}",
            iteration_log_path=None,
            master_before_cut_lp_path=None,
            master_after_cut_lp_path=None,
        )
        failure = CutProcessDiagnosticFailureSummary(
            comparison_group=summary.comparison_group,
            variant=summary.variant,
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
            generated_cut_count=0,
            final_violation_upper_bound=None,
            sampled_problem_gap_bound=None,
            total_runtime_sec=float(elapsed),
            dominant_cause=summary.dominant_cause,
            message=summary.notes,
        )
        exception_payload = {"type": exc.__class__.__name__, "message": str(exc)}

    log_path = write_json(
        logs_dir / f"{run_id}_diagnostic.json",
        {
            "run_config": dict(run_config),
            "summary": None if summary is None else summary.to_csv_row(),
            "failure_record": None if failure is None else failure.to_csv_row(),
            "cut_rows": [row.to_csv_row() for row in cut_rows],
            "exception": exception_payload,
            "diagnostics": payload,
        },
    )
    return {
        "summary": summary,
        "failure": failure,
        "cut_rows": cut_rows,
        "log_path": str(log_path),
        "iteration_log_path": None if summary is None else summary.iteration_log_path,
        "master_before_cut_lp_path": None if summary is None else summary.master_before_cut_lp_path,
        "master_after_cut_lp_path": None if summary is None else summary.master_after_cut_lp_path,
    }
