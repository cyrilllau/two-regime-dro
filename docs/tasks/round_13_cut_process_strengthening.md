# Round 13 - Cut-Process Strengthening Diagnostics and Minimal Algorithm Improvements

## Objective
Diagnose and improve the current Benders cut process without redesigning validated model mathematics.

This round has one bounded objective:

> determine whether the current non-certification cases are primarily caused by weak/redundant cuts and master-side stagnation, then implement only small, auditable cut-process improvements that are justified by diagnostics.

## Background from Round 12.5
Key evidence already observed:
- some `smoke_only` runs were intentionally bounded and are not alarming by themselves
- some runs remain true `max_iter_noncert` cases even after larger iteration budgets
- master-side runtime dominated the diagnostic pack
- repeated outage patterns were observed on some harder cases
- disaster-only appears especially difficult

This round must build on those findings rather than re-running the same pack unchanged.

## Allowed files to create/update
Primary implementation files:
- `src/production/benders_engine.py`
- `src/production/cut_factory.py`
- `src/audit/iteration_log.py`
- `src/audit/cut_audit.py`
- `src/audit/experiment_summary.py`

Primary diagnostic / packaging files:
- `scripts/run_cut_process_diagnostics.py`
- `scripts/make_cut_process_figures.py`
- `scripts/cut_process_utils.py`

Primary test files:
- `tests/integration/test_benders_cut_process_improvements.py`
- `tests/integration/test_benders_repeated_outage_guard.py`
- `tests/integration/test_benders_two_real_cuts_runtime_like.py`
- `tests/oracle/test_cut_signature_dedup.py`

Fixture files for this round:
- `tests/fixtures/cut_process_*.yaml`

Round report:
- `docs/reports/round_13_report.md`

## Narrow bug-fix permission (only if exposed by new Round 13 tests)
The following files may be edited only if a new Round 13 test exposes a localized bug:
- `src/production/master_problem.py`
- `src/production/separation_milp.py`
- `src/production/disaster_dual_paper.py`

If changed:
- keep the fix minimal
- explain exactly which test exposed it
- explain why the bug blocks the cut-process diagnosis/improvement objective
- do not widen scope

## Do not modify
Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/*`

Also forbidden in this round:
- no scenario reduction
- no stabilized / level Benders
- no trust-region or proximal reformulation
- no cut deletion
- no end-to-end paper-scale experiment pack
- no semantic fallback from `ambig.w` to `critical_buses`

## Required behavior

### A. Add cut-process diagnostics
For each generated cut in the Benders engine, record at least:
- cut id
- iteration id
- source outage vector
- repeated outage flag
- cut signature hash
- repeated cut-signature flag
- old-master violation at source point
- post-cut objective change
- whether first-stage plan changed
- whether only `alpha/lambda` changed
- number of nonzero entries in:
  - `gamma_z_by_bus`
  - `gamma_n_sl_by_bus`
  - `gamma_n_fa_by_bus`
  - `phi_by_line_id`

These diagnostics must be exported to iteration logs and a tabular artifact.

### B. Add one or two minimal algorithm improvements only
Implement only improvements justified by the Round 12.5 findings, chosen from:
1. repeated-cut / repeated-outage detection and explicit reporting
2. deduplication guard that prevents re-adding an exactly duplicate structured cut
3. optional multi-cut addition per iteration **only if** it can be done conservatively and transparently using already validated samplewise cut objects
4. master warm-start / state reuse if available through the current implementation path

Requirements:
- any improvement must be small and auditable
- do not redesign the mathematical formulation
- do not change certification semantics
- if multiple options are implemented, keep them individually switchable in config

### C. Comparative diagnostic sweep
Run a focused sweep on the currently problematic patterns identified in Round 12.5, including at minimum:
- `integrated_paper_like_exact` with `A=[1]`, `B=[1]`, `K=2`, iteration budgets `10`, `20`, `40`
- `disaster_only_paper_like_exact` with `A=[1]`, `B=[1]`, `K=1` and `K=2`, iteration budgets `5`, `20`, `40`
- one runtime-directional case with support `[1,2,3,4]` and `K=3`

For each run, compare:
- baseline behavior from the existing engine
- improved behavior with the new cut-process option(s)

### D. Classification and root-cause summary
For each compared run, classify outcome into:
- `exact_zero`
- `epsilon_stop`
- `max_iter_noncert`

And explain the dominant cause among:
- repeated outages / repeated cut signatures
- weak cuts that change only `alpha/lambda`
- master-side growth / slow lower-bound improvement
- other clearly evidenced cause

### E. Contract preservation
The following must remain true:
- `critical_buses` remains explicit external input
- `critical_buses` is never inferred from `ambig.w`
- default runtime selection semantics remain selection-driven
- no raw CSV/JSON reads are added to production model layers
- exact / epsilon / smoke labeling remains honest and unchanged in meaning

## Acceptance tests
At minimum, the following must pass:
- `pytest tests/oracle/test_cut_signature_dedup.py -q`
- `pytest tests/integration/test_benders_repeated_outage_guard.py -q`
- `pytest tests/integration/test_benders_cut_process_improvements.py -q`
- `pytest tests/integration/test_benders_two_real_cuts_runtime_like.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest tests/integration/test_benders_vs_oracle.py -q`
- `pytest -q`

## Deliverables
You must return:
1. implementation in the allowed files
2. required tests
3. `docs/reports/round_13_report.md`
4. `results/cut_process_diagnostics/summary.csv`
5. `results/cut_process_diagnostics/failures.csv`
6. `results/cut_process_diagnostics/cut_diagnostics.csv`
7. `reports/cut_process_diagnostic_pack.md`
8. stable iteration-log artifact path(s)
9. stable master LP dump path(s) for at least one before/after comparison
10. concise comparative summaries showing whether the improvement helped the currently problematic runs

## Report format
Write `docs/reports/round_13_report.md` with at least:

```md
# Round 13 Report

## Files changed
- ...

## Design decisions
- ...

## Improvement(s) implemented
- ...

## Comparative diagnostic sweep
- baseline vs improved summary
- repeated-outage findings
- repeated-cut findings
- lower-bound / cut-count behavior

## Tests run
- command
- result

## Audit artifacts
- iteration logs
- LP dump paths
- cut-diagnostics CSV path

## Known limitations
- ...

## Open issues for next round
- ...
```

The report must state clearly:
- whether exact non-certification cases improved or not
- whether repeated outages / repeated cuts were actually present
- whether the improvement changed first-stage plans or only `alpha/lambda`
- whether the next step should be stronger cuts, multi-cut, stabilization, or master-side engineering
