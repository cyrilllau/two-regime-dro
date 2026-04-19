# Round 12.5 Report

## Scope

Round 12.5 was a convergence-diagnostics and scaling-sweep round only. It did not change
validated optimization mathematics, solver objectives, certification semantics, or any
protected files under `docs/spec/*` or `data/*`.

This round implemented:

- baseline snapshotting of the existing Round 12 experiment outputs
- a bounded convergence/scaling diagnostic matrix
- diagnostic CSV / JSON / figure / markdown packaging
- explicit diagnosis labels:
  - `exact_zero`
  - `epsilon_stop`
  - `max_iter_noncert`

No production math files were modified. In particular, no narrow diagnostic-instrumentation
edits were required in:

- `src/production/benders_engine.py`
- `src/production/master_problem.py`
- `src/production/cut_factory.py`
- `src/production/separation_milp.py`

## Files Added Or Updated

Primary config / script files:

- `configs/experiments/convergence_diagnostic_manifest.yaml`
- `configs/experiments/convergence_diagnostic_matrix.yaml`
- `scripts/run_convergence_diagnostics.py`
- `scripts/make_convergence_diagnostic_figures.py`
- `scripts/diagnostic_utils.py`

Primary audit / packaging files:

- `src/audit/experiment_summary.py`

Primary tests / fixtures:

- `tests/integration/test_convergence_diagnostic_pack_smoke.py`
- `tests/integration/test_convergence_diagnostic_labels.py`
- `tests/fixtures/convergence_diagnostic_smoke.yaml`

Artifacts generated:

- `artifacts/baselines/round_12/*`
- `results/convergence_diagnostics/summary.csv`
- `results/convergence_diagnostics/failures.csv`
- `results/convergence_diagnostics/figures/*.png`
- `results/convergence_diagnostics/logs/*.json`
- `docs/analysis_packs/convergence_diagnostic_pack.md`

## Baseline Snapshot

Before running any new diagnostics, the existing Round 12 outputs were copied into:

- `artifacts/baselines/round_12/summary.csv`
- `artifacts/baselines/round_12/failures.csv`
- `artifacts/baselines/round_12/round_12_report.md`
- `artifacts/baselines/round_12/paper_style_experiment_pack.md`
- `artifacts/baselines/round_12/figures/*`
- `artifacts/baselines/round_12/plans/*`

This preserves the pre-diagnostic Round 12 state for later comparison.

## Diagnostic Matrix

The diagnostic matrix varied all required dimensions:

- iteration budget:
  - `2`
  - `5`
  - `10`
  - `20`
- epsilon:
  - `0`
  - `10000`
  - `20000`
- support size:
  - singleton `[1]`
  - bounded pair `[1,2]`
  - larger reviewable subset `[1,2,3,4]`
- outage budget:
  - `K=1`
  - `K=2`
  - `K=3`

Included families:

- `integrated_mainline`
- `deterministic_mean_value`
- `disaster_only`
- one direct `normal_only` baseline

## Diagnosis Summary

### exact_zero

Only one run ended with zero final violation:

- `normal_only_paper_like_direct_exact`

This is a direct master baseline rather than a Benders iteration case, so it serves as an
anchor for the diagnostic labels rather than as evidence about cut-process behavior.

### epsilon_stop

Three runs stopped by design under a positive epsilon certificate:

- `integrated_paper_like_eps20000_i2_k2_a1b1`
- `integrated_paper_like_eps10000_i5_k2_a1b1`
- `deterministic_paper_like_eps20000_i2_k2_a1b1`

Concrete evidence:

- `integrated_paper_like_eps20000_i2_k2_a1b1`
  - `final_violation_upper_bound = 16575.03`
  - `epsilon_cert = 20000`
- `integrated_paper_like_eps10000_i5_k2_a1b1`
  - `final_violation_upper_bound = 6363.82`
  - `epsilon_cert = 10000`

Interpretation:

- these are not exact-zero results
- they are certified relative to the requested tolerance
- they should not be promoted to exact convergence

### max_iter_noncert

All remaining Benders-based diagnostic runs ended as:

- `validation_level = smoke_only`
- `diagnosis_label = max_iter_noncert`
- `stop_reason = max_iterations`

This group includes two different situations:

1. intentionally bounded short-run smoke diagnostics
2. stronger non-certification evidence under enlarged iteration budgets

Short-budget bounded smoke examples:

- `integrated_runtime12_exact_i2_k2_a12b12`
- `integrated_runtime12_exact_i2_k1_a1234b1234`
- `integrated_runtime12_exact_i2_k3_a1234b1234`
- `deterministic_runtime12_exact_i2_k2_a12b12`

These were deliberately capped at two iterations to measure directional behavior under larger
support or altered `K`, not to prove convergence.

Stronger non-certification examples:

- `integrated_paper_like_exact_i10_k2_a1b1`
  - 10 iterations, final violation `2818.31`
- `integrated_paper_like_exact_i20_k2_a1b1`
  - 20 iterations, final violation `3747.11`
- `disaster_only_paper_like_exact_i5_k1_a1b1`
  - 5 iterations, final violation `46818.81`
- `disaster_only_paper_like_exact_i20_k2_a1b1`
  - 20 iterations, final violation `35891.96`

Interpretation:

- these are stronger evidence that the current cut process is still struggling on those
  configurations
- the paper-like integrated exact-mode runs improved their lower bounds materially, but still
  did not obtain a zero-violation certificate
- the disaster-only family appears especially difficult under the tested budgets

## Convergence / Scaling Observations

### Paper-like integrated runs

The paper-like integrated family shows all three regimes:

- direct exact baseline
- epsilon-certified early stops
- non-certified exact-mode runs under larger iteration budgets

The most useful contrast is:

- `integrated_paper_like_eps10000_i5_k2_a1b1`
  - certified at violation `6363.82`
- `integrated_paper_like_exact_i10_k2_a1b1`
  - still non-certified at violation `2818.31`
- `integrated_paper_like_exact_i20_k2_a1b1`
  - still non-certified at violation `3747.11`

That pattern supports the main proof obligation of this round:

- some previous `smoke_only` outcomes are explained by intentionally bounded stopping
- some others remain genuine non-certification cases even after a larger iteration budget

### Runtime-directional larger-support runs

The runtime-directional family was intentionally kept reviewable rather than paper-scale.

The larger-support cases:

- `A=[1,2,3,4]`
- `B=[1,2,3,4]`

did finish under the bounded budgets, but remained:

- `smoke_only`
- `max_iter_noncert`

Observed final violations:

- `K=1`: `10492.675`
- `K=2` on `[1,2]`: `10529.505`
- `K=3`: `15217.615`

Interpretation:

- increasing support and/or outage budget did not produce certification within two iterations
- this is not surprising for a bounded diagnostic sweep
- these runs remain directional diagnostics only, not exact or paper-comparable claims

### Disaster-only runs

The disaster-only family is the clearest signal of unresolved convergence difficulty in this
round’s matrix.

Even with larger iteration budgets:

- `disaster_only_paper_like_exact_i5_k1_a1b1`
  - violation `46818.81`
- `disaster_only_paper_like_exact_i20_k2_a1b1`
  - violation `35891.96`

Both runs improved their lower bounds strongly, but still remained far from an exact-zero
certificate. This suggests that cut-process effectiveness, rather than data loading or model
correctness, is the next place to focus.

## Cut-Efficacy Diagnostics

The diagnostic pack exported a per-cut efficacy trace for multi-iteration runs. For each
generated cut it records:

- old-master violation at the source point
- post-cut master objective change
- whether the first-stage plan changed
- whether only `alpha/lambda` changed
- a compact structured cut signature hash

Illustrative cases:

- `integrated_runtime12_exact_i2_k2_a12b12`
  - generated cut changed only `alpha/lambda`
  - first-stage plan did not change
  - old-master violation `12987.68`
  - post-cut objective change `87.35`
- `integrated_paper_like_eps10000_i5_k2_a1b1`
  - generated cuts repeatedly changed the first-stage plan
  - this shows the cut family is still materially reshaping the design, not merely adjusting
    dual-support variables

Repeated-pattern flags were also exported:

- `repeated_outage_flag`
- `repeated_cut_signature_flag`

The repeated outage flag turned on in:

- `integrated_paper_like_exact_i20_k2_a1b1`
- `disaster_only_paper_like_exact_i20_k2_a1b1`

This is consistent with a cut-process difficulty story rather than a data-contract issue.

## Runtime-Bound Diagnostics

For separation runs, the diagnostic JSON logs include:

- `max_omega_bound_violation`
- count of lines tight at lower bound
- count of lines tight at upper bound
- lines with the smallest omega slack

These diagnostics were exported into the per-run JSON logs under:

- `results/convergence_diagnostics/logs/*_diagnostic.json`

No additional instrumentation changes were needed in production solver files to expose them.

## Failure / Non-Certification Recording

All non-certified `max_iterations` runs were recorded explicitly in:

- `results/convergence_diagnostics/failures.csv`
- per-run JSON diagnostic logs
- `docs/analysis_packs/convergence_diagnostic_pack.md`

This round did not hide non-convergence inside summary-only packaging.

## Figures Produced

The required figures were generated:

- `results/convergence_diagnostics/figures/validation_category_overview.png`
- `results/convergence_diagnostics/figures/violation_vs_iteration_budget.png`
- `results/convergence_diagnostics/figures/runtime_breakdown_by_run.png`
- `results/convergence_diagnostics/figures/cut_efficacy_trace.png`
- `results/convergence_diagnostics/figures/outage_repeat_patterns.png`

## Tests

Executed and passing:

- `pytest tests/integration/test_convergence_diagnostic_pack_smoke.py -q`
- `pytest tests/integration/test_convergence_diagnostic_labels.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest tests/integration/test_readiness_matrix.py -q`
- `pytest -q`

## Final Assessment

Round 12.5 met its bounded proof obligation.

It separated three situations cleanly:

1. exact-zero baseline behavior
2. epsilon-certified early stopping by design
3. genuine non-certification under larger budgets or more difficult benchmark regimes

The main conclusion is:

- not all `smoke_only` runs mean the same thing
- some are intentionally bounded diagnostics
- some remain real convergence difficulties for the current cut process

That is the key readiness result this round needed to produce.
