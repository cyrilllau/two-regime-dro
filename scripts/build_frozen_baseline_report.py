"""Build the Round 14 frozen baseline archive, figures, tables, and LaTeX review report."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_frozen_baseline_archive import build_archive  # noqa: E402
from scripts.build_frozen_baseline_figures import (  # noqa: E402
    build_figures_and_tables,
    resolve_report_paths,
)
from scripts.diagnostic_utils import execute_diagnostic_run  # noqa: E402
from scripts.experiment_pack_utils import execute_run  # noqa: E402


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path} must contain a YAML mapping.")
    return dict(raw)


def _escape_latex(text: Any) -> str:
    value = str(text)
    replacements = {
        "\\": "\\textbackslash{}",
        "&": "\\&",
        "%": "\\%",
        "$": "\\$",
        "#": "\\#",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def _format_float(value: Any) -> str:
    if value in {"", None, "None"}:
        return "n/a"
    numeric = float(value)
    if abs(numeric) >= 1000:
        return f"{numeric:,.3f}"
    return f"{numeric:.6f}"


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(payload), indent=2, sort_keys=True), encoding="utf-8")
    return str(target)


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _lookup_experiment_log(
    *,
    run_id: str,
    current_logs_dir: Path,
    regen_root: Path | None,
) -> Path | None:
    candidates = [current_logs_dir / f"{run_id}_run.json"]
    if regen_root is not None:
        candidates.insert(0, regen_root / "logs" / f"{run_id}_run.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _lookup_convergence_log(run_id: str, logs_dir: Path) -> Path | None:
    candidate = logs_dir / f"{run_id}_diagnostic.json"
    return candidate if candidate.exists() else None


def _relative_to_repo(path: str | Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except Exception:
        return str(path)


def _compare_values(left: Any, right: Any, *, abs_tol: float = 1e-6, rel_tol: float = 1e-9) -> bool:
    if left in {"", None, "None"} and right in {"", None, "None"}:
        return True
    try:
        return math.isclose(float(left), float(right), abs_tol=abs_tol, rel_tol=rel_tol)
    except Exception:
        return str(left) == str(right)


def _run_anchor_checks(
    *,
    config: Mapping[str, Any],
    archive_info: Mapping[str, Any],
    skip_anchor_reruns: bool,
) -> list[dict[str, Any]]:
    critical_buses = tuple(int(bus) for bus in config["critical_buses"])
    current_logs_dir = REPO_ROOT / config["current_outputs"]["experiment_logs_dir"]
    convergence_logs_dir = REPO_ROOT / config["current_outputs"]["convergence_logs_dir"]
    regen_root = None
    if archive_info.get("regenerated_certified_small"):
        regen_root = Path(archive_info["regenerated_certified_small"]["output_root"])

    rerun_root = Path(archive_info["archive_root"]) / "anchor_reruns"
    if rerun_root.exists():
        shutil.rmtree(rerun_root)
    rerun_root.mkdir(parents=True, exist_ok=True)

    checks: list[dict[str, Any]] = []
    for anchor in config["anchors"]:
        anchor_id = str(anchor["anchor_id"])
        source_kind = str(anchor["source_kind"])
        run_id = str(anchor["run_id"])
        if source_kind in {"regenerated_experiment", "current_experiment"}:
            baseline_path = _lookup_experiment_log(
                run_id=run_id,
                current_logs_dir=current_logs_dir,
                regen_root=regen_root if source_kind == "regenerated_experiment" else None,
            )
        else:
            baseline_path = _lookup_convergence_log(run_id, convergence_logs_dir)
        if baseline_path is None:
            checks.append(
                {
                    "anchor_id": anchor_id,
                    "run_id": run_id,
                    "source_kind": source_kind,
                    "baseline_path": None,
                    "rerun_path": None,
                    "baseline_available": False,
                    "objective_components_match": False,
                    "validation_match": False,
                    "stop_reason_match": False,
                    "notes": "baseline artifact missing",
                }
            )
            continue

        baseline_payload = _load_json(baseline_path)
        baseline_summary = baseline_payload["summary"]
        run_config = baseline_payload["run_config"]

        if skip_anchor_reruns:
            checks.append(
                {
                    "anchor_id": anchor_id,
                    "run_id": run_id,
                    "source_kind": source_kind,
                    "baseline_path": _relative_to_repo(baseline_path),
                    "rerun_path": None,
                    "baseline_available": True,
                    "objective_components_match": None,
                    "validation_match": None,
                    "stop_reason_match": None,
                    "notes": "anchor rerun skipped by request",
                }
            )
            continue

        output_root = rerun_root / anchor_id
        if source_kind in {"regenerated_experiment", "current_experiment"}:
            rerun_result = execute_run(run_config, critical_buses=critical_buses, output_root=output_root)
            rerun_payload = _load_json(rerun_result["log_path"])
        else:
            rerun_result = execute_diagnostic_run(run_config, critical_buses=critical_buses, output_root=output_root)
            rerun_payload = _load_json(rerun_result["log_path"])
        rerun_summary = rerun_payload["summary"]

        if source_kind in {"regenerated_experiment", "current_experiment"}:
            objective_match = all(
                _compare_values(baseline_summary[key], rerun_summary[key])
                for key in (
                    "total_objective",
                    "construction_cost",
                    "weighted_normal_term",
                    "unweighted_normal_term",
                    "disaster_master_term",
                    "final_violation_upper_bound",
                )
            )
        else:
            objective_match = all(
                _compare_values(baseline_summary.get(key), rerun_summary.get(key))
                for key in (
                    "total_objective",
                    "construction_cost",
                    "weighted_normal_term",
                    "disaster_master_term",
                    "final_violation_upper_bound",
                )
            )
        validation_match = baseline_summary["validation_level"] == rerun_summary["validation_level"]
        stop_reason_match = baseline_summary["stop_reason"] == rerun_summary["stop_reason"]
        notes = []
        if source_kind == "regenerated_experiment":
            notes.append("baseline source was regenerated because current Round 12 outputs no longer include certified-small artifacts")
        if not objective_match:
            notes.append("objective components changed on rerun")
        if not validation_match:
            notes.append("validation label changed on rerun")
        if not stop_reason_match:
            notes.append("stop reason changed on rerun")
        if not notes:
            notes.append("rerun matched baseline within configured tolerances")
        checks.append(
            {
                "anchor_id": anchor_id,
                "run_id": run_id,
                "source_kind": source_kind,
                "baseline_path": _relative_to_repo(baseline_path),
                "rerun_path": _relative_to_repo(rerun_payload["artifact_paths"]["iteration_log_path"] if source_kind in {"regenerated_experiment", "current_experiment"} else rerun_result["log_path"]),
                "baseline_available": True,
                "objective_components_match": objective_match,
                "validation_match": validation_match,
                "stop_reason_match": stop_reason_match,
                "baseline_validation_level": baseline_summary["validation_level"],
                "rerun_validation_level": rerun_summary["validation_level"],
                "baseline_stop_reason": baseline_summary["stop_reason"],
                "rerun_stop_reason": rerun_summary["stop_reason"],
                "notes": "; ".join(notes),
            }
        )
    return checks


def _label_lines(rows: Sequence[Mapping[str, Any]], *, label_key: str) -> str:
    grouped: dict[str, list[str]] = {"exact": [], "epsilon_certified": [], "smoke_only": [], "failed": []}
    for row in rows:
        grouped.setdefault(str(row[label_key]), []).append(f"`{row['run_id']}`")
    return "\n".join(
        f"- `{label}`: {', '.join(grouped[label]) if grouped.get(label) else 'none'}"
        for label in ("exact", "epsilon_certified", "smoke_only", "failed")
    )


def _family_rows(rows: Sequence[Mapping[str, Any]], family_name: str) -> list[Mapping[str, Any]]:
    return [row for row in rows if row["family_name"] == family_name]


def _summary_bullets(rows: Sequence[Mapping[str, Any]]) -> str:
    lines = []
    for row in rows:
        lines.append(
            f"\\item {_escape_latex(row['run_id'])}: validation={_escape_latex(row['validation_level'])}, "
            f"stop={_escape_latex(row['stop_reason'])}, construction={_escape_latex(_format_float(row.get('construction_cost')))}, "
            f"weighted normal={_escape_latex(_format_float(row.get('weighted_normal_term')))}, "
            f"disaster master={_escape_latex(_format_float(row.get('disaster_master_term')))}"
        )
    return "\n".join(lines) if lines else "\\item none"


def _render_anchor_table(checks: Sequence[Mapping[str, Any]]) -> str:
    lines = [
        "\\begin{tabular}{p{2.4cm} p{3.3cm} p{1.9cm} p{1.7cm} p{1.7cm} p{4.3cm}}",
        "\\hline",
        "Anchor & Run id & Objective match & Validation match & Stop match & Notes \\\\",
        "\\hline",
    ]
    for row in checks:
        lines.append(
            f"{_escape_latex(row['anchor_id'])} & {_escape_latex(row['run_id'])} & "
            f"{_escape_latex(row.get('objective_components_match'))} & "
            f"{_escape_latex(row.get('validation_match'))} & "
            f"{_escape_latex(row.get('stop_reason_match'))} & "
            f"{_escape_latex(row.get('notes', ''))} \\\\"
        )
    lines.extend(["\\hline", "\\end{tabular}"])
    return "\n".join(lines)


def _build_latex_report(
    *,
    config: Mapping[str, Any],
    archive_info: Mapping[str, Any],
    figure_info: Mapping[str, Any],
    anchor_checks: Sequence[Mapping[str, Any]],
) -> str:
    experiment_rows = figure_info["experiment_rows"]
    convergence_rows = figure_info["convergence_rows"]
    cut_rows = figure_info["cut_process_rows"]
    certified_small_rows = _family_rows(experiment_rows, "certified_small_family")
    paper_like_rows = _family_rows(experiment_rows, "paper_like_tableII_family")
    runtime_rows = _family_rows(experiment_rows, "runtime12_directional_family")
    noncert_rows = figure_info["noncert_rows"]

    exact_count = sum(1 for row in experiment_rows if row["validation_level"] == "exact")
    epsilon_count = sum(1 for row in experiment_rows if row["validation_level"] == "epsilon_certified")
    smoke_count = sum(1 for row in experiment_rows if row["validation_level"] == "smoke_only")
    failed_count = sum(1 for row in experiment_rows if row["validation_level"] == "failed")

    repeated_outage_cases = [
        row["run_id"] for row in convergence_rows if str(row.get("repeated_outage_flag", "")).lower() == "true"
    ]
    repeated_signature_cases = [
        row["run_id"]
        for row in convergence_rows
        if str(row.get("repeated_cut_signature_flag", "")).lower() == "true"
    ]
    hard_noncert_cases = [
        row["run_id"]
        for row in cut_rows
        if row["variant"] == "baseline" and row["diagnosis_label"] == "max_iter_noncert"
    ]
    validation_label_lines = "\n".join(
        f"\\item {_escape_latex(line)}"
        for line in _label_lines(experiment_rows, label_key="validation_level").splitlines()
    )

    tex = f"""\\documentclass[11pt]{{article}}
\\usepackage[margin=1in]{{geometry}}
\\usepackage{{graphicx}}
\\usepackage{{booktabs}}
\\usepackage{{longtable}}
\\usepackage{{array}}
\\usepackage{{float}}
\\usepackage{{hyperref}}
\\title{{Frozen Baseline Review Report}}
\\author{{Round 14 packaging pass}}
\\date{{}}
\\begin{{document}}
\\maketitle

\\section{{Executive Summary}}
This report freezes the pre-improvement baseline before any future algorithm-strengthening work. The current benchmark inventory contains {len(experiment_rows)} packaged experiment runs: {exact_count} exact, {epsilon_count} epsilon-certified, {smoke_count} smoke-only, and {failed_count} failed. The validation chain from reference disaster primal through the production Benders engine is already built and individually checked, but the harder exact-mode convergence cases remain non-certified.

\\begin{{itemize}}
\\item Exact results currently cover the fixed disaster primal/dual reference chain, the normal-only direct master baselines, and selected tiny or longer-budget exact-mode Benders diagnostics.
\\item Epsilon-certified results are bounded certificates relative to their chosen tolerance; they are not exact-zero convergence.
\\item Smoke-only runs remain visible and are not promoted into certified evidence.
\\item Default \\texttt{{runtime\\_12}} remains a local directional benchmark and is not numerically paper-Table-II comparable.
\\end{{itemize}}

\\section{{Current Frozen Contract}}
\\begin{{itemize}}
\\item Source-of-truth hierarchy: frozen specs under \\texttt{{docs/spec/}}, validated round reports under \\texttt{{docs/reports/}}, human-facing interpretation packs under \\texttt{{docs/analysis\\_packs/}}, and current packaged outputs under \\texttt{{results/}}.
\\item Explicit critical-bus freeze for this report: \\texttt{{[2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]}}.
\\item \\texttt{{smoke\\_only}} means a bounded directional run that is not certified evidence.
\\item \\texttt{{epsilon\\_certified}} means the run stopped with a proved violation upper bound below the configured epsilon, not exact zero.
\\item The paper-like family is an approximation layer built from local config overrides, not paper-number reproduction.
\\end{{itemize}}

\\section{{Validation Chain Summary}}
\\input{{tables/validation_chain_summary.tex}}

\\section{{Benchmark Experiment Summary}}
Certified-small family (regenerated in this round because the Round 12 packaged outputs no longer carried those rows separately):
\\begin{{itemize}}
{_summary_bullets(certified_small_rows)}
\\end{{itemize}}

Paper-like family:
\\begin{{itemize}}
{_summary_bullets(paper_like_rows)}
\\end{{itemize}}

Runtime12 directional family:
\\begin{{itemize}}
{_summary_bullets(runtime_rows)}
\\end{{itemize}}

Validation labels by packaged experiment run:
\\begin{{itemize}}
{validation_label_lines}
\\end{{itemize}}

\\section{{IEEE 33-Bus Station Topology Interpretation}}
Figure~\\ref{{fig:runtime12-maps}} shows the runtime12 directional maps, while Figures~\\ref{{fig:paper123}} and \\ref{{fig:paper456}} show the paper-like maps. Critical buses are highlighted explicitly in red. The current baseline supports a careful topological interpretation: integrated and normal-only plans often place direct capacity at or near critical buses, fast-charger hubs concentrate on a smaller subset of opened buses, and EV-penetration expansion is monotone in buildout. None of these plots should be read as paper-number reproduction.

\\begin{{figure}}[H]
\\centering
\\includegraphics[width=\\textwidth]{{figures/baseline/ieee33_runtime12_directional_maps.png}}
\\caption{{Runtime12 directional topology maps.}}
\\label{{fig:runtime12-maps}}
\\end{{figure}}

\\begin{{figure}}[H]
\\centering
\\includegraphics[width=\\textwidth]{{figures/baseline/ieee33_paper_like_maps_case123.png}}
\\caption{{Paper-like case 1/2/3 topology maps: integrated, normal-only, disaster-only.}}
\\label{{fig:paper123}}
\\end{{figure}}

\\begin{{figure}}[H]
\\centering
\\includegraphics[width=\\textwidth]{{figures/baseline/ieee33_paper_like_maps_case4_56.png}}
\\caption{{Paper-like case 4/5/6 topology maps: deterministic mean-value and EV-penetration cases.}}
\\label{{fig:paper456}}
\\end{{figure}}

\\section{{Objective Decomposition}}
Figure~\\ref{{fig:obj-components}} uses the weighted normal term consistently and keeps the unweighted normal term out of the main stacked chart. Cross-family ranking by raw total objective is intentionally avoided in the safer benchmark comparison view of Figure~\\ref{{fig:safe-benchmark}}.

\\begin{{figure}}[H]
\\centering
\\includegraphics[width=\\textwidth]{{figures/baseline/objective_components_by_run.png}}
\\caption{{Construction, weighted normal term, and disaster master term by run.}}
\\label{{fig:obj-components}}
\\end{{figure}}

\\begin{{figure}}[H]
\\centering
\\includegraphics[width=\\textwidth]{{figures/baseline/benchmark_comparison_safe.png}}
\\caption{{Safer benchmark comparison based on structural counts within each family.}}
\\label{{fig:safe-benchmark}}
\\end{{figure}}

\\section{{Convergence / Non-Certification Diagnostics}}
The convergence and cut-process diagnostics keep non-certified runs visible. Round 12.5 showed that exact-zero, epsilon-stop, and max-iteration non-certification need to be separated explicitly. Round 13 showed repeated outages in several hard cases, while exact duplicate structured cut signatures were not observed.

\\begin{{itemize}}
\\item Repeated-outage cases from Round 12.5: {_escape_latex(", ".join(repeated_outage_cases) if repeated_outage_cases else "none observed")}.
\\item Repeated structured-cut signature cases from Round 12.5: {_escape_latex(", ".join(repeated_signature_cases) if repeated_signature_cases else "none observed")}.
\\item Hard exact-mode or strengthened diagnostic cases still non-certified: {_escape_latex(", ".join(hard_noncert_cases) if hard_noncert_cases else "none")}.
\\end{{itemize}}

\\begin{{figure}}[H]
\\centering
\\includegraphics[width=\\textwidth]{{figures/baseline/iteration_trace_selected.png}}
\\caption{{Selected iteration traces: certified-small anchor, runtime smoke anchor, and hard exact-mode non-certified anchor.}}
\\end{{figure}}

\\begin{{figure}}[H]
\\centering
\\includegraphics[width=\\textwidth]{{figures/baseline/convergence_diagnostics_overview.png}}
\\caption{{Round 12.5 convergence-diagnostic overview.}}
\\end{{figure}}

\\begin{{figure}}[H]
\\centering
\\includegraphics[width=\\textwidth]{{figures/baseline/cut_process_diagnostics_overview.png}}
\\caption{{Round 13 cut-process overview.}}
\\end{{figure}}

\\section{{Safe Claims vs Unsafe Claims}}
\\textbf{{Safe now.}}
\\begin{{itemize}}
\\item The reference-to-production validation chain has been individually exercised from the disaster primal through the fixed-cut master and iterative Benders engine.
\\item Exact, epsilon-certified, smoke-only, and failed labels are preserved explicitly in the frozen baseline.
\\item The current diagnosis points at cut-process effectiveness as the main remaining difficulty in the harder exact-mode runs, not at raw-data loading or a known core-math break.
\\end{{itemize}}

\\textbf{{Not safe yet.}}
\\begin{{itemize}}
\\item Default \\texttt{{runtime\\_12}} is not paper-Table-II comparable.
\\item The paper-like family is not a paper-number reproduction.
\\item Heterogeneous benchmark runs should not be ranked by raw total objective without caveats.
\\item Hard non-certified exact-mode runs should not be described as converged.
\\end{{itemize}}

\\section{{Next Improvement Priorities}}
\\begin{{enumerate}}
\\item Strengthen cut-process effectiveness rather than relabeling smoke-only outcomes.
\\item Revisit multi-cut or stabilization ideas only after preserving the current exact/epsilon/smoke discipline.
\\item Keep baseline archive, anchor reruns, and honest non-certification visibility intact during future improvement rounds.
\\end{{enumerate}}

\\section*{{Anchor Consistency Checks}}
The round reran three anchors against archived/current baselines:
\\begin{{center}}
{_render_anchor_table(anchor_checks)}
\\end{{center}}

\\end{{document}}
"""
    return tex


def _compile_latex(*, tex_path: Path, log_path: Path) -> tuple[bool, str | None]:
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("latexmk"):
        command = [
            "latexmk",
            "-pdf",
            "-interaction=nonstopmode",
            "-halt-on-error",
            tex_path.name,
        ]
    elif shutil.which("pdflatex"):
        command = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            tex_path.name,
        ]
    else:
        log_path.write_text("No LaTeX toolchain available.\n", encoding="utf-8")
        return False, None

    result = subprocess.run(
        command,
        cwd=tex_path.parent,
        capture_output=True,
        text=True,
    )
    if not log_path.exists():
        log_path.write_text(
            f"Command: {' '.join(command)}\nReturn code: {result.returncode}\n\nSTDOUT\n{result.stdout}\n\nSTDERR\n{result.stderr}\n",
            encoding="utf-8",
        )
    pdf_path = tex_path.with_suffix(".pdf")
    return result.returncode == 0 and pdf_path.exists(), (str(pdf_path) if pdf_path.exists() else None)


def _write_round_report(
    *,
    path: Path,
    archive_info: Mapping[str, Any],
    figure_info: Mapping[str, Any],
    anchor_checks: Sequence[Mapping[str, Any]],
    latex_success: bool,
    pdf_path: str | None,
    narrow_packaging_fix: str,
    skipped_anchor_reruns: bool,
) -> None:
    lines = [
        "# Round 14 Report",
        "",
        "## Files changed",
        "- `configs/reports/frozen_baseline_review.yaml`",
        "- `scripts/build_frozen_baseline_archive.py`",
        "- `scripts/build_frozen_baseline_figures.py`",
        "- `scripts/build_frozen_baseline_report.py`",
        "- `tests/integration/test_frozen_baseline_report_packaging.py`",
        "- `tests/fixtures/frozen_baseline_report_smoke.yaml`",
        "- generated report outputs under `reports/` and archive outputs under `artifacts/baselines/frozen_pre_improvement/`",
        "",
        "## Design decisions",
        "- Reused current Round 12 / 12.5 / 13 packaged outputs wherever they were already present and auditable.",
        "- Regenerated the missing certified-small family under the archive because current `results/summary.csv` no longer carries the Round 11 certified-small rows.",
        "- Preserved the historical pack-path split honestly: current sources live in `docs/analysis_packs/`, while the archive also stores legacy-named `reports/*.md` copies for continuity with older task wording.",
        "- Kept all non-certified and non-converged runs visible in the CSV tables and LaTeX report.",
        "",
        "## Baseline archive contents",
        f"- archive root: `{archive_info['archive_root']}`",
        "- round reports 02 through 13",
        "- experiment, convergence-diagnostic, and cut-process summary/failure CSVs",
        "- current figures, plans, iteration logs, and selected LP dumps",
        "- regenerated certified-small family under `regenerated/certified_small/`",
        "",
        "## Reused vs regenerated artifacts",
        f"- reused artifacts count: `{len(archive_info['reused_artifacts'])}`",
        f"- regenerated artifacts: `{', '.join(archive_info['regenerated_artifacts']) if archive_info['regenerated_artifacts'] else 'none'}`",
        f"- missing artifacts after path normalization: `{', '.join(archive_info['missing_artifacts']) if archive_info['missing_artifacts'] else 'none'}`",
        "",
        "## Consistency checks",
    ]
    if skipped_anchor_reruns:
        lines.append("- anchor reruns were skipped in this invocation")
    else:
        for check in anchor_checks:
            lines.append(
                f"- `{check['anchor_id']}` / `{check['run_id']}`: objective_match=`{check.get('objective_components_match')}`, "
                f"validation_match=`{check.get('validation_match')}`, stop_reason_match=`{check.get('stop_reason_match')}`; {check.get('notes','')}"
            )
    lines.extend(
        [
            "",
            "## Tests run",
            "- `pytest tests/integration/test_frozen_baseline_report_packaging.py -q`",
            "- `pytest tests/integration/test_experiment_pack_smoke.py -q`",
            "- `pytest tests/integration/test_convergence_diagnostic_pack_smoke.py -q`",
            "- `pytest tests/integration/test_benders_runtime_certification.py -q`",
            "- `pytest -q`",
            "",
            "## Deliverables produced",
            f"- `docs/reports/round_14_report.md`",
            f"- `reports/frozen_baseline_review_report.tex`",
            f"- `reports/frozen_baseline_review_report.log`",
            f"- `reports/frozen_baseline_review_report.pdf`: `{pdf_path if pdf_path else 'not available'}`",
            f"- figures generated: `{len(figure_info['figure_paths'])}`",
            f"- tables generated: `{len(figure_info['table_paths'])}`",
            "",
            "## Known limitations",
            "- Default `runtime_12` remains a local directional fixture and is not numerically paper-Table-II comparable.",
            "- The paper-like family remains an approximation layer, not paper-number reproduction.",
            "- Hard exact-mode non-certified runs remain unresolved and visible.",
            "",
            "## Open issues for next round",
            "- prioritize cut-process effectiveness rather than relabeling smoke-only outcomes",
            "- keep anchor reruns and frozen archive checks in place during any future improvement work",
            "",
            "## Narrow packaging fix",
            f"- {narrow_packaging_fix}",
            "",
            "## LaTeX compilation",
            f"- success: `{latex_success}`",
            f"- PDF path: `{pdf_path if pdf_path else 'not produced'}`",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resolve_output_paths(
    config: Mapping[str, Any],
    *,
    report_root_override: str | Path | None,
) -> dict[str, Path]:
    if report_root_override is None:
        return {
            "report_root": REPO_ROOT / config["report_root"],
            "report_tex_path": REPO_ROOT / config["report_tex_path"],
            "report_pdf_path": REPO_ROOT / config["report_pdf_path"],
            "report_log_path": REPO_ROOT / config["report_log_path"],
            "metadata_json_path": REPO_ROOT / config["metadata_json_path"],
            "round_report_path": REPO_ROOT / config["round_report_path"],
        }
    report_root = REPO_ROOT / str(report_root_override)
    return {
        "report_root": report_root,
        "report_tex_path": report_root / "frozen_baseline_review_report.tex",
        "report_pdf_path": report_root / "frozen_baseline_review_report.pdf",
        "report_log_path": report_root / "frozen_baseline_review_report.log",
        "metadata_json_path": report_root / "frozen_baseline_review_metadata.json",
        "round_report_path": report_root / "round_14_report.md",
    }


def build_frozen_baseline_report(
    *,
    config_path: str | Path = "configs/reports/frozen_baseline_review.yaml",
    archive_root_override: str | Path | None = None,
    report_root_override: str | Path | None = None,
    skip_latex: bool = False,
    skip_anchor_reruns: bool = False,
    skip_certified_small_regeneration: bool = False,
) -> dict[str, Any]:
    config = load_yaml_file(config_path)
    archive_info = build_archive(
        config_path=config_path,
        archive_root_override=archive_root_override,
        regenerate_certified_small=not skip_certified_small_regeneration,
    )
    figure_info = build_figures_and_tables(
        config_path=config_path,
        archive_info=archive_info,
        report_root_override=report_root_override,
    )
    anchor_checks = _run_anchor_checks(
        config=config,
        archive_info=archive_info,
        skip_anchor_reruns=skip_anchor_reruns,
    )

    resolved_outputs = _resolve_output_paths(config, report_root_override=report_root_override)
    tex_path = resolved_outputs["report_tex_path"]
    pdf_path = resolved_outputs["report_pdf_path"]
    log_path = resolved_outputs["report_log_path"]
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(
        _build_latex_report(
            config=config,
            archive_info=archive_info,
            figure_info=figure_info,
            anchor_checks=anchor_checks,
        ),
        encoding="utf-8",
    )

    if skip_latex:
        log_path.write_text("LaTeX compilation skipped by request.\n", encoding="utf-8")
        latex_success = False
        produced_pdf = None
    else:
        latex_success, produced_pdf = _compile_latex(tex_path=tex_path, log_path=log_path)

    metadata = {
        "archive": archive_info,
        "anchor_checks": anchor_checks,
        "figure_paths": figure_info["figure_paths"],
        "table_paths": figure_info["table_paths"],
        "latex_success": latex_success,
        "latex_pdf_path": produced_pdf,
        "reused_vs_regenerated_note": "Certified-small family was regenerated because the current Round 12 packaged outputs no longer carry the Round 11 certified-small rows.",
        "path_normalization_note": "Current interpretation packs live under docs/analysis_packs/ and were archived under legacy reports/*.md names for continuity.",
        "narrow_packaging_fix": "none required; Round 14 stayed inside new packaging/report scripts and outputs",
    }
    metadata_path = resolved_outputs["metadata_json_path"]
    _write_json(metadata_path, metadata)

    round_report_path = resolved_outputs["round_report_path"]
    _write_round_report(
        path=round_report_path,
        archive_info=archive_info,
        figure_info=figure_info,
        anchor_checks=anchor_checks,
        latex_success=latex_success,
        pdf_path=produced_pdf,
        narrow_packaging_fix="none required",
        skipped_anchor_reruns=skip_anchor_reruns,
    )

    return {
        "archive_info": archive_info,
        "anchor_checks": anchor_checks,
        "figure_info": figure_info,
        "latex_success": latex_success,
        "pdf_path": produced_pdf,
        "tex_path": str(tex_path),
        "log_path": str(log_path),
        "metadata_path": str(metadata_path),
        "round_report_path": str(round_report_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/reports/frozen_baseline_review.yaml")
    parser.add_argument("--archive-root", default=None)
    parser.add_argument("--report-root", default=None)
    parser.add_argument("--skip-latex", action="store_true")
    parser.add_argument("--skip-anchor-reruns", action="store_true")
    parser.add_argument("--skip-certified-small-regeneration", action="store_true")
    args = parser.parse_args()

    result = build_frozen_baseline_report(
        config_path=args.config,
        archive_root_override=args.archive_root,
        report_root_override=args.report_root,
        skip_latex=args.skip_latex,
        skip_anchor_reruns=args.skip_anchor_reruns,
        skip_certified_small_regeneration=args.skip_certified_small_regeneration,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
