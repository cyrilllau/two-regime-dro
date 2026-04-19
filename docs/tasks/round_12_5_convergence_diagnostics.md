# Round 12.5 - Convergence diagnostics and scaling sweep

## Objective

Diagnose why some benchmark runs stop as `smoke_only` / `max_iterations` instead of reaching
`certified_exact` or `certified_epsilon`, without changing validated model mathematics.

This round has one bounded proof obligation:

> separate "did not converge because the run was intentionally bounded or epsilon-certified"
> from "did not converge because the algorithm/cut process is actually struggling",
> and produce auditable evidence about where the difficulty comes from.

This round must:
- preserve the current validated optimization chain
- snapshot the current Round 12 experiment outputs before running new diagnostics
- run a bounded but informative convergence / scaling matrix
- generate a diagnosis pack that helps explain:
  - which runs are intentionally bounded
  - which runs are epsilon stops by design
  - which runs exhibit true non-certification under a larger iteration budget
  - whether the bottleneck appears cut-side, separation-side, or master-side

## Allowed files to create/update

Primary config / script files:
- `configs/experiments/convergence_diagnostic_manifest.yaml`
- `configs/experiments/convergence_diagnostic_matrix.yaml`
- `scripts/run_convergence_diagnostics.py`
- `scripts/make_convergence_diagnostic_figures.py`
- `scripts/diagnostic_utils.py`

Primary audit / packaging files:
- `src/audit/experiment_summary.py`
- `src/audit/iteration_log.py`

Primary integration / packaging tests:
- `tests/integration/test_convergence_diagnostic_pack_smoke.py`
- `tests/integration/test_convergence_diagnostic_labels.py`
- `tests/fixtures/convergence_diagnostic_smoke.yaml`

Artifact outputs for this round:
- `artifacts/baselines/round_12/*`
- `results/convergence_diagnostics/summary.csv`
- `results/convergence_diagnostics/failures.csv`
- `results/convergence_diagnostics/figures/*.png`
- `results/convergence_diagnostics/logs/*.json`
- `docs/analysis_packs/convergence_diagnostic_pack.md`
- `docs/reports/round_12_5_report.md`

### Narrow diagnostic-instrumentation fix permission (only if required)

The following files may be edited **only** if the new diagnostic tests or scripts reveal that
critical convergence information is not exposed yet. Any such change must be logging-only and must
not alter model math, solver objectives, constraints, or certification semantics.

- `src/production/benders_engine.py`
- `src/production/master_problem.py`
- `src/production/cut_factory.py`
- `src/production/separation_milp.py`

If any of these files are changed:
- keep the change minimal
- explain exactly what logging/diagnostic field was missing
- prove that no optimization math or stopping logic changed

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/*`
- any validated toy-oracle math tests from earlier rounds unless this task explicitly requires a new diagnostic test

Also forbidden in this round:
- no new optimization algorithm
- no redesign of validated model mathematics
- no cut strengthening / multi-cut redesign
- no stabilization / level method
- no scenario reduction algorithm
- no paper-scale optimality claim
- no semantic fallback from `ambig.w` to `critical_buses`

## Required behavior

### A. Save the current version’s experiment outputs
Before running any new diagnostics, snapshot the existing Round 12 outputs into:

- `artifacts/baselines/round_12/summary.csv`
- `artifacts/baselines/round_12/failures.csv`
- `artifacts/baselines/round_12/round_12_report.md`
- `artifacts/baselines/round_12/paper_style_experiment_pack.md`
- `artifacts/baselines/round_12/figures/*`
- `artifacts/baselines/round_12/plans/*`

The Round 12 baseline must remain recoverable after this round.

### B. Disambiguate three different situations
For every diagnostic run, classify it into one of these diagnosis categories:

1. `exact_zero`
   - final violation upper bound is zero (within tolerance)
2. `epsilon_stop`
   - certified by `epsilon_cert > 0`, but final violation is nonzero
3. `max_iter_noncert`
   - stopped by `max_iterations` without certification

The current round must make these categories explicit in the diagnostic summary.

### C. Run a bounded convergence/scaling matrix
Run a diagnostic matrix that varies at least the following dimensions:

1. **iteration budget**
   - e.g. `{2, 5, 10, 20}` (or a similar bounded ascending sequence)
2. **epsilon certificate**
   - include exact mode `epsilon_cert = 0`
   - include at least two positive epsilon values
3. **scenario support size**
   - at least one singleton support
   - at least one `{1,2}` support
   - at least one larger subset drawn from the available CSV reservoir
4. **outage budget K**
   - include current local default `K = 2`
   - include at least one smaller value
   - include at least one larger value

The diagnostic matrix must include at minimum these benchmark families:
- `integrated_mainline`
- `deterministic_mean_value`
- `disaster_only`

You may include `normal_only` as a direct-solve baseline, but the emphasis of this round is on
Benders-based runs.

### D. Explain *why* a run stops the way it does
For each run, collect and export enough diagnostics to support one or more of these interpretations:

- intentionally bounded smoke run
- epsilon-certified early stop by design
- true non-certification under enlarged iteration budget
- lower-bound stagnation
- weak cut efficacy
- repeated or near-repeated outage/cut pattern
- separation dominates runtime
- master dominates runtime
- samplewise dual re-solves dominate runtime

At minimum the diagnostic summary must include:
- `run_id`
- `case_name`
- `parameter_regime`
- `validation_level`
- `diagnosis_label`
- `stop_reason`
- `solver_status`
- `epsilon_cert`
- `max_iterations`
- `A_selected`
- `B_selected`
- `K`
- `iteration_count`
- `cut_count`
- `final_violation_upper_bound`
- `sampled_problem_gap_bound`
- `total_objective`
- `construction_cost`
- `weighted_normal_term`
- `disaster_master_term`
- `final_alpha`
- `final_lambda_times_FP`
- `total_runtime_sec`
- `master_runtime_sec_total`
- `separation_runtime_sec_total`
- `dual_resolve_runtime_sec_total`
- `generated_cut_count`
- `selected_outage_trace`
- `lower_bound_sequence`
- `violation_sequence`
- `cut_efficacy_sequence`
- `repeated_outage_flag`
- `repeated_cut_signature_flag`
- `notes`

### E. Cut-efficacy diagnostics
For every generated cut in every multi-iteration run, record:
- old-master violation of the generated cut at the source point
- post-cut master objective change
- whether the cut changed the first-stage plan
- whether the cut changed only `alpha/lambda`
- a compact cut signature/hash so repeated or near-duplicate cuts can be spotted

### F. Runtime-bound diagnostics
For runs that solve separation MILPs, include:
- max omega bound violation
- count of lines tight at lower bound
- count of lines tight at upper bound
- top few lines by smallest omega slack

### G. Non-convergence must be recorded, not hidden
Any run that ends with:
- `max_iterations`
- `INFEASIBLE`
- `UNBOUNDED`
- numerical status / abnormal termination
must appear in:
- `results/convergence_diagnostics/failures.csv`
- per-run JSON log
- final markdown diagnosis pack

### H. Runtime-like scaling tests
Include at least one runtime-like family that increases scenario support beyond the current singleton or `{1,2}`
bounded cases, while remaining small enough to finish in a reviewable amount of time.
For example, use subsets like:
- `A=[1,2,3,4]`
- `B=[1,2,3,4]` if supported

If the local repo support prevents a larger `B`, surface that explicitly rather than guessing.

### I. Preserve contract discipline
The following must remain true:
- `critical_buses` remains explicit and never inferred from `ambig.w`
- no raw CSV/JSON reads are introduced into production model layers
- no validated model math is redefined
- no paper-scale claim is made unless the run actually certifies that scope

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/integration/test_convergence_diagnostic_pack_smoke.py -q`
- `pytest tests/integration/test_convergence_diagnostic_labels.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest tests/integration/test_readiness_matrix.py -q`
- `pytest -q`

## Deliverables

You must return:

1. implementation in the allowed files
2. required tests
3. `docs/reports/round_12_5_report.md`
4. the saved baseline snapshot under `artifacts/baselines/round_12/`
5. `results/convergence_diagnostics/summary.csv`
6. `results/convergence_diagnostics/failures.csv`
7. `docs/analysis_packs/convergence_diagnostic_pack.md`
8. generated figures, at minimum:
   - `validation_category_overview.png`
   - `violation_vs_iteration_budget.png`
   - `runtime_breakdown_by_run.png`
   - `cut_efficacy_trace.png`
   - `outage_repeat_patterns.png`
9. stable iteration-log artifact paths used by the analysis
10. if any narrow diagnostic-instrumentation files were changed:
   - exact files changed
   - exact field added
   - which test or diagnostic need exposed it

## Report format

Write `docs/reports/round_12_5_report.md` with at least:

```md
# Round 12.5 Report

## Files changed
- ...

## Design decisions
- ...

## Baseline snapshot
- what was copied and where

## Diagnostic matrix
- cases run
- supports used
- K values used
- epsilon / max-iteration settings used

## Key findings
- which runs were exact_zero
- which runs were epsilon_stop
- which runs were max_iter_noncert
- likely reasons

## Tests run
- command
- result

## Audit artifacts
- iteration log paths
- figure paths
- summary/failures CSV paths

## Known limitations
- ...

## Open issues for next round
- ...
```

Model/solver diagnosis rounds should also include:
- a concise explanation of why currently observed `smoke_only` runs are or are not alarming
- a ranking of suspected bottlenecks
- a recommendation for the next algorithm-improvement round
