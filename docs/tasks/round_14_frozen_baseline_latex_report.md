# Round 14 - Frozen Baseline Archive + LaTeX Review Report

## Objective

Create a **frozen baseline archive** and a **colleague-reviewable LaTeX report** that records the current state of the project **before any future algorithm-improvement work begins**.

This round has one bounded objective:

> consolidate the validated chain, benchmark results, convergence diagnostics, station-topology figures, and caveats into a single auditable baseline package for colleague review, without changing validated optimization mathematics.

This round must:
- preserve the current validated math and solver behavior
- archive the current baseline artifacts in a stable location
- regenerate any missing experiment/plan/figure artifacts needed for a complete baseline report
- produce a LaTeX report (and compile it to PDF if the LaTeX toolchain is available)
- make all non-convergence / non-certification cases explicit
- clearly distinguish:
  - `exact`
  - `epsilon_certified`
  - `smoke_only`
  - `failed`

## Allowed files to create/update

Primary packaging / reporting files:
- `configs/reports/frozen_baseline_review.yaml`
- `scripts/build_frozen_baseline_archive.py`
- `scripts/build_frozen_baseline_figures.py`
- `scripts/build_frozen_baseline_report.py`

Primary report outputs:
- `reports/frozen_baseline_review_report.tex`
- `reports/frozen_baseline_review_report.pdf`   # if LaTeX compile succeeds
- `reports/frozen_baseline_review_report.log`   # LaTeX build log or compile-attempt log
- `reports/frozen_baseline_review_appendix.csv`
- `reports/frozen_baseline_review_metadata.json`

Figure/table outputs:
- `reports/figures/baseline/*.png`
- `reports/tables/*.csv`
- `reports/tables/*.tex`

Archive outputs:
- `artifacts/baselines/frozen_pre_improvement/**/*`

Round report:
- `docs/reports/round_14_report.md`

Optional packaging smoke test files:
- `tests/integration/test_frozen_baseline_report_packaging.py`
- `tests/fixtures/frozen_baseline_report_smoke.yaml`

### Narrow packaging-fix permission (only if required to regenerate missing report inputs)

The following files may be edited **only** if the new Round 14 packaging tests expose a localized packaging bug, import-path issue, or missing-export issue:
- `scripts/experiment_pack_utils.py`
- `scripts/make_experiment_figures.py`
- `scripts/run_experiment_pack.py`
- `scripts/diagnostic_utils.py`
- `scripts/run_convergence_diagnostics.py`
- `scripts/make_convergence_diagnostic_figures.py`
- `src/audit/experiment_summary.py`

If any of these narrow-fix files are changed:
- keep the change minimal
- explain exactly why it was needed
- show which Round 14 packaging test exposed it
- do not widen scope beyond the localized packaging fix

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/*`
- `src/production/*`
- previously validated algorithm logic and model math

Also forbidden in this round:
- no new optimization algorithm
- no redesign of validated model mathematics
- no convergence-acceleration logic
- no new Benders, cut, separation, or dual semantics
- no silent relabeling of `smoke_only` as certified
- no inference of `critical_buses` from `ambig.w`

## Required behavior

### A. Freeze and archive the current baseline
Create a stable archive directory, for example:

- `artifacts/baselines/frozen_pre_improvement/`

Copy or regenerate into that archive at least the following:
- Round reports for the key validated rounds:
  - 02, 03, 04, 05, 05.5, 06, 06.5, 07, 07.5, 08, 09, 10, 11, 12, 12.5, 13
- key result packs:
  - `results/summary.csv`
  - `results/failures.csv`
  - `reports/experiment_interpretation_pack.md`
  - `reports/paper_style_experiment_pack.md`
  - `results/convergence_diagnostics/summary.csv`
  - `results/convergence_diagnostics/failures.csv`
  - `results/cut_process_diagnostics/summary.csv`
  - `results/cut_process_diagnostics/failures.csv`
  - `results/cut_process_diagnostics/cut_diagnostics.csv`
- selected figure outputs from current rounds
- selected iteration logs / LP dumps needed to document the baseline

If a required upstream artifact is missing, regenerate it using the existing validated pipeline and record that in the round report.

### B. Produce a colleague-reviewable LaTeX report
Create:
- `reports/frozen_baseline_review_report.tex`
- attempt to compile to `reports/frozen_baseline_review_report.pdf`
- always write `reports/frozen_baseline_review_report.log`

The report must be **for review**, not for publication, and it must be honest about validation levels and non-converged runs.

The report must include these sections:

1. **Executive Summary**
   - what is already validated exactly
   - what is only epsilon-certified
   - what is only smoke-only
   - what is currently difficult / not yet certified

2. **Current Frozen Contract**
   - source-of-truth hierarchy
   - default runtime fixture semantics
   - explicit `critical_buses`
   - validation-label meaning

3. **Validation Chain Summary**
   - one compact table listing the key rounds and what they validated
   - reference/primal/dual/separation/master/Benders chain

4. **Benchmark Experiment Summary**
   - certified-small family
   - runtime12 directional family
   - paper-like family
   - explicit run-by-run validation labels

5. **IEEE 33-Bus Station Topology Interpretation**
   - topology-style station maps that are easy to compare visually
   - explicit marking of critical buses
   - discussion of:
     - coverage pattern
     - fast-charger hubs
     - direct critical coverage vs nearby support
     - EV-penetration-driven expansion

6. **Objective Decomposition**
   - construction
   - weighted normal term
   - disaster master term
   - total objective
   - do **not** mix weighted and unweighted normal terms ambiguously

7. **Convergence / Non-Certification Diagnostics**
   - summarize Round 12.5 and Round 13
   - show which runs are bounded smoke only
   - show which exact-mode runs remained non-certified under larger budgets
   - show the current diagnosis:
     - repeated outages observed
     - exact duplicate structured cuts not observed
     - likely issue = cut-process effectiveness, not data loading or core math correctness

8. **Safe Claims vs Unsafe Claims**
   - what is safe to say to colleagues now
   - what is not yet safe to claim
   - explicitly state:
     - default `runtime_12` is not paper-Table-II comparable
     - paper-like family is approximation, not paper-number reproduction

9. **Next Improvement Priorities**
   - what the next algorithm-improvement round should target, based on the current diagnosis

### C. Required figures
Produce colleague-friendly figures under `reports/figures/baseline/` at minimum:

1. `validation_status_overview.png`
   - exact / epsilon / smoke / failed by run

2. `objective_components_by_run.png`
   - use **weighted normal term**
   - show construction / weighted normal / disaster master separately
   - avoid ambiguous use of unweighted normal cost in the main stacked chart

3. `benchmark_comparison_safe.png`
   - a safer benchmark comparison that does **not** encourage ranking heterogeneous objective definitions by raw total objective alone
   - use subtitles / legends / captions to explain comparability limits

4. `ieee33_runtime12_directional_maps.png`
   - multi-panel topology maps for:
     - integrated runtime12
     - deterministic runtime12
     - EV 1.5x runtime12
     - EV 2.0x runtime12

5. `ieee33_paper_like_maps_case123.png`
   - paper-like integrated / normal-only / disaster-only maps if plan data can be regenerated
   - if a plan cannot be regenerated, keep the panel but mark it clearly as unavailable and explain why

6. `ieee33_paper_like_maps_case4_56.png`
   - deterministic mean-value paper-like
   - EV 1.5x paper-like
   - EV 2.0x paper-like

7. `iteration_trace_selected.png`
   - selected traces for:
     - one exact tiny/certified run
     - one runtime smoke run
     - one hard non-certified exact-mode run

8. `convergence_diagnostics_overview.png`
   - summarize final violation vs iteration budget for the key Round 12.5 / 13 cases

9. `cut_process_diagnostics_overview.png`
   - show repeated outage counts, repeated signature counts, plan-changing cuts, alpha/lambda-only cuts where available

### D. Required tables / exports
Produce at least:

1. `reports/tables/validation_chain_summary.csv`
2. `reports/tables/validation_chain_summary.tex`

3. `reports/tables/run_inventory.csv`
   - one row per run
   - family
   - case name
   - parameter regime
   - validation level
   - stop reason
   - iteration count
   - cut count
   - final violation upper bound

4. `reports/tables/objective_components.csv`
   - one row per run
   - construction_cost
   - weighted_normal_term
   - unweighted_normal_term
   - disaster_master_term
   - total_objective
   - explicit note that `total_objective` should be compared using weighted-normal conventions only

5. `reports/tables/noncertified_runs.csv`
   - include both bounded smoke runs and harder non-certified exact-mode runs
   - do not hide them

6. `reports/frozen_baseline_review_appendix.csv`
   - consolidated appendix of all runs included in the report

### E. Required interpretation discipline
The report must be explicit about:

- `critical_buses = [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`
- current `runtime_12` parameters are not numerically Table-II comparable
- `smoke_only` means bounded directional run, not certified evidence
- `epsilon_certified` means certified to the specified tolerance, not exact zero
- any max-iteration non-certification must be recorded in the report body and appendix

### F. Required consistency checks
This round must perform a light consistency check on at least three anchor runs by comparing archived/current outputs against a fresh rerun from the validated pipeline:

- one certified-small integrated run
- one runtime12 integrated run
- one hard exact-mode diagnostic run from Round 12.5 or 13

Use tolerances appropriate for LP/MILP floating-point outputs and record:
- whether the rerun matched objective components
- whether the rerun matched validation level / stop reason
- any mismatch explanation

### G. No-raw-read and packaging discipline
- Preserve the current canonical-instance and raw-read boundary.
- Packaging/report scripts may read existing packaged result files, manifests, and archived artifacts.
- Production model layers must still not read raw CSV/JSON directly.

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/integration/test_frozen_baseline_report_packaging.py -q`   # if created
- `pytest tests/integration/test_experiment_pack_smoke.py -q`
- `pytest tests/integration/test_convergence_diagnostic_pack_smoke.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest -q`

If no new packaging smoke test is added, the report must explain why.

## Deliverables

You must return:

1. implementation in the allowed files
2. packaging/regeneration tests
3. `docs/reports/round_14_report.md`
4. `reports/frozen_baseline_review_report.tex`
5. `reports/frozen_baseline_review_report.pdf` if compilation succeeds
6. `reports/frozen_baseline_review_report.log`
7. archive path for the frozen baseline snapshot
8. lists of generated figures and tables
9. concise note describing:
   - which upstream artifacts were reused vs regenerated
   - whether any anchor-rerun consistency mismatch was found
   - whether LaTeX compilation succeeded
   - any narrow packaging fix that was required

## Report format

Write `docs/reports/round_14_report.md` with at least:

```md
# Round 14 Report

## Files changed
- ...

## Design decisions
- ...

## Baseline archive contents
- ...

## Reused vs regenerated artifacts
- ...

## Consistency checks
- ...

## Tests run
- command
- result

## Deliverables produced
- ...

## Known limitations
- ...

## Open issues for next round
- ...
```

This round is packaging/reporting only, but it must still be auditable and conservative.
