# Round 11 - Experiment Interpretation Pack

## Objective

Produce a colleague-reviewable experiment pack that helps interpret whether the current validated EVCS hybrid DRO mainline results make sense.

This round has one bounded objective:

> run a small but meaningful benchmark family using the already validated pipeline, export auditable summaries/figures/plans, and write a report that clearly distinguishes exact / epsilon-certified / smoke-only claims.

This round must **not** redesign the validated model mathematics or add new optimization algorithms.

---

## Allowed files to create/update

Configuration / experiment packaging:
- `configs/critical_buses_paper_fig2.yaml`
- `configs/experiments/experiment_manifest.yaml`
- `configs/experiments/*.yaml`

Scripts / helpers for experiment execution and reporting:
- `scripts/run_experiment_pack.py`
- `scripts/make_experiment_figures.py`
- `scripts/experiment_pack_utils.py`

Optional lightweight packaging helpers:
- `src/audit/experiment_summary.py`

Outputs produced by this round:
- `results/summary.csv`
- `results/plans/*.csv`
- `results/figures/*.png`
- `results/logs/*.json`
- `reports/experiment_interpretation_pack.md`

Optional smoke test / fixture for this round:
- `tests/integration/test_experiment_pack_smoke.py`
- `tests/fixtures/experiment_pack_*.yaml`

Round report:
- `docs/reports/round_11_report.md`

### Narrow bug-fix permission

No core model/math bug-fix is authorized by default in this round.

If an experiment-pack smoke test exposes a **localized non-math packaging bug** in one of the following files, you may fix it minimally:
- `src/production/benders_engine.py`
- `src/production/master_problem.py`
- `src/production/cut_factory.py`
- `src/audit/iteration_log.py`

If any such file is changed:
- keep the fix minimal
- explain exactly why it was needed
- show which new Round 11 test or packaging run exposed it
- do not widen scope beyond the localized fix

---

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/*`

Do not implement in this round:
- no new optimization formulations
- no new decomposition method
- no stabilization / level method
- no cut deletion / selection policy
- no scenario reduction
- no paper-scale workflow claims
- no semantic fallback from `ambig.w` to `critical_buses`

---

## Required behavior

### A. Freeze explicit critical buses from the paper figure

Create an explicit config file:
- `configs/critical_buses_paper_fig2.yaml`

Use the Fig. 2 paper figure interpretation:
- `critical_buses = [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`

Important:
- treat this as an explicit round-level external config input
- do not infer anything from `ambig.w`
- do not silently change this set

### B. Run an interpretation-oriented benchmark family

At minimum, produce two experiment families:

#### Family 1: `certified_small_family`
Use:
- canonical runtime source: `data/runtime_12`
- explicit selection:
  - `scenarios_a = [1]`
  - `scenarios_b = [1]`
- explicit `critical_buses` from the config above
- use current validated Benders pipeline when needed

Required cases inside this family:
1. `integrated_mainline_certified_small`
2. `normal_only_certified_small`
3. `deterministic_mean_value_certified_small`

Interpretation purpose:
- compare integrated vs normal-only on a certifiable small production-like run
- compare integrated vs deterministic mean-value on the same reduced support

#### Family 2: `runtime12_smoke_family`
Use:
- canonical runtime source: `data/runtime_12`
- default selected runtime support `{1,2}`
- explicit `critical_buses` from the config above

Required cases inside this family:
1. `integrated_mainline_runtime12`
2. `normal_only_runtime12`
3. `deterministic_mean_value_runtime12`
4. `ev_penetration_1_5x_runtime12`
5. `ev_penetration_2_0x_runtime12`

Optional:
- `disaster_only_runtime12`

Interpretation purpose:
- observe qualitative behavior / directionality on the current runtime fixture
- do **not** overclaim certification for this family unless it is actually certified by the engine

### C. Validation-level labeling must be explicit

Every run must be labeled as one of:
- `exact`
- `epsilon_certified`
- `smoke_only`

Rules:
- do not label default runtime `{1,2}` as certified unless the engine actually stops with certification
- make the current evidence boundary explicit
- distinguish:
  - tiny exact evidence
  - certified-small evidence
  - runtime smoke evidence

### D. Required outputs

#### 1. Experiment manifest
Create:
- `configs/experiments/experiment_manifest.yaml`

Must record for each run:
- run id
- case name
- family name
- runtime source
- selected scenarios A/B
- critical_buses source
- parameter regime
- whether Benders / direct solve / benchmark simplification is used
- expected validation level

#### 2. Results summary table
Create:
- `results/summary.csv`

Must include at least these columns:
- `run_id`
- `family_name`
- `case_name`
- `parameter_regime`
- `validation_level`
- `stop_reason`
- `total_objective`
- `construction_cost`
- `weighted_normal_term`
- `disaster_master_term`
- `alpha`
- `lambda_times_FP`
- `iteration_count`
- `cut_count`
- `final_violation_upper_bound`
- `opened_bus_count`
- `total_slow_chargers`
- `total_fast_chargers`

#### 3. Plan detail files
Create one CSV per run:
- `results/plans/<run_id>_plan.csv`

Minimum columns:
- `bus`
- `z`
- `n_sl`
- `n_fa`
- `is_critical`
- `region` (if available)

#### 4. Figures
Create at least:
- `results/figures/objective_components.png`
- `results/figures/benchmark_comparison.png`
- `results/figures/iteration_trace.png`
- `results/figures/plan_map.png`

Figure requirements:
- keep them simple and auditable
- no custom color semantics unless already standard in the existing codebase
- if a run has no iterations (e.g. benchmark/direct case), handle this explicitly in the figure or omit it with a clear note in the report

#### 5. Interpretation report
Create:
- `reports/experiment_interpretation_pack.md`

This report must answer, explicitly:
1. Does `integrated_mainline` trade a modest daily-cost increase for a resilience benefit?
2. Does `deterministic_mean_value` underestimate disaster risk relative to the integrated model?
3. How do EV penetration increases affect construction, normal-operation, and disaster terms?
4. Which claims are exact, epsilon-certified, or smoke-only?
5. Which conclusions are safe for colleague review, and which are only provisional?
6. How do the current runtime parameters differ from the paper Table II regime, and what does that imply for interpretation?

### E. Paper-reference honesty checks

The interpretation report must explicitly state:
- current `runtime_12` parameters are not numerically identical to the paper Table II regime
- therefore absolute cost magnitudes are not directly paper-comparable unless a paper-like config is added explicitly
- the colleague-facing interpretation should focus on:
  - directionality
  - trade-offs
  - validation level
  rather than claiming direct paper-number reproduction

### F. Runtime discipline

- use the existing validated pipeline
- no raw CSV/JSON reads in production model layers
- preserve raw-read guard behavior where existing tests already rely on it
- keep structured cut representation intact
- preserve first-stage objective-boundary discipline:
  - use `construction_cost_value` when a pure first-stage contribution is needed
  - do not reuse attached `objective_value` as a pure-construction quantity

---

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/integration/test_experiment_pack_smoke.py -q` (if you add it)
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest tests/integration/test_readiness_matrix.py -q`
- `pytest tests/integration/test_benders_vs_oracle.py -q`
- `pytest -q`

In addition, you must run the experiment pack itself and verify that the required output files are actually created.

---

## Deliverables

You must return:

1. implementation in the allowed files
2. any smoke test(s) added for this round
3. `docs/reports/round_11_report.md`
4. `configs/experiments/experiment_manifest.yaml`
5. `results/summary.csv`
6. `results/plans/*.csv`
7. `results/figures/*.png`
8. `reports/experiment_interpretation_pack.md`
9. concise run summary including:
   - which runs are exact / epsilon-certified / smoke-only
   - the biggest integrated vs normal-only difference observed
   - the deterministic vs integrated comparison
   - EV penetration trend summary
10. if any narrow-fix file was changed:
   - the exact file(s)
   - the exact bug
   - which new Round 11 test or run exposed it

---

## Report format

Write `docs/reports/round_11_report.md` with at least:

```md
# Round 11 Report

## Files changed
- ...

## Design decisions
- ...

## Experiment families run
- ...

## Outputs produced
- ...

## Tests run
- command
- result

## Known limitations
- ...

## Open issues / next recommendations
- ...
```

The round report should also include:
- output file locations
- any runtime/certification failures encountered and how they were labeled
- whether a paper-like parameter pack was produced or intentionally deferred
