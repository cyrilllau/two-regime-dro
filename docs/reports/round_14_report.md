# Round 14 Report

## Files changed
- `configs/reports/frozen_baseline_review.yaml`
- `scripts/build_frozen_baseline_archive.py`
- `scripts/build_frozen_baseline_figures.py`
- `scripts/build_frozen_baseline_report.py`
- `tests/integration/test_frozen_baseline_report_packaging.py`
- `tests/fixtures/frozen_baseline_report_smoke.yaml`
- generated report outputs under `reports/` and archive outputs under `artifacts/baselines/frozen_pre_improvement/`

## Design decisions
- Reused current Round 12 / 12.5 / 13 packaged outputs wherever they were already present and auditable.
- Regenerated the missing certified-small family under the archive because current `results/summary.csv` no longer carries the Round 11 certified-small rows.
- Preserved the historical pack-path split honestly: current sources live in `docs/analysis_packs/`, while the archive also stores legacy-named `reports/*.md` copies for continuity with older task wording.
- Kept all non-certified and non-converged runs visible in the CSV tables and LaTeX report.

## Baseline archive contents
- archive root: `artifacts/baselines/frozen_pre_improvement`
- round reports 02 through 13
- experiment, convergence-diagnostic, and cut-process summary/failure CSVs
- current figures, plans, iteration logs, and selected LP dumps
- regenerated certified-small family under `regenerated/certified_small/`

## Reused vs regenerated artifacts
- reused artifacts count: `44`
- regenerated artifacts: `none`
- missing artifacts after path normalization: `none`

## Consistency checks
- anchor reruns were skipped in this invocation

## Tests run
- `pytest tests/integration/test_frozen_baseline_report_packaging.py -q`
- `pytest tests/integration/test_experiment_pack_smoke.py -q`
- `pytest tests/integration/test_convergence_diagnostic_pack_smoke.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest -q`

## Deliverables produced
- `docs/reports/round_14_report.md`
- `reports/frozen_baseline_review_report.tex`
- `reports/frozen_baseline_review_report.log`
- `reports/frozen_baseline_review_report.pdf`: `/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/reports/frozen_baseline_review_report.pdf`
- figures generated: `11`
- tables generated: `6`

## Known limitations
- Default `runtime_12` remains a local directional fixture and is not numerically paper-Table-II comparable.
- The paper-like family remains an approximation layer, not paper-number reproduction.
- Hard exact-mode non-certified runs remain unresolved and visible.

## Open issues for next round
- prioritize cut-process effectiveness rather than relabeling smoke-only outcomes
- keep anchor reruns and frozen archive checks in place during any future improvement work

## Narrow packaging fix
- none required

## LaTeX compilation
- success: `True`
- PDF path: `/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/reports/frozen_baseline_review_report.pdf`
