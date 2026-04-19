# Round 12 - Paper-style Experiment Family + Honest Failure Logging

## Objective
Run a paper-style experiment family and generate colleague-reviewable result artifacts, while preserving all validated model mathematics and recording every algorithmic issue explicitly.

This round has one bounded objective:

> produce a benchmark pack analogous to the paper's Case 1-6 comparisons, with explicit validation labels, complete run logs, and honest failure recording.

## Allowed files to create/update
Primary experiment/config/report files:
- `configs/critical_buses_paper_fig2.yaml`
- `configs/experiments/paper_like_tableII_family.yaml`
- `configs/experiments/runtime12_directional_family.yaml`
- `configs/experiments/experiment_manifest.yaml`
- `scripts/run_experiment_pack.py`
- `scripts/make_experiment_figures.py`
- `scripts/experiment_pack_utils.py`
- `src/audit/experiment_summary.py`
- `tests/integration/test_experiment_pack_smoke.py`
- `tests/integration/test_experiment_failure_logging.py`
- `tests/fixtures/experiment_pack_smoke.yaml`
- `docs/reports/round_12_report.md`
- `docs/analysis_packs/paper_style_experiment_pack.md`
- `results/summary.csv`
- `results/failures.csv`
- `results/plans/*.csv`
- `results/figures/*.png`
- `results/logs/*.json`

### Narrow bug-fix permission (only if required by the new experiment-pack tests)
The following validated-chain files may be edited only if the new Round 12 tests expose a localized packaging/runtime bug that blocks experiment execution:
- `src/production/benders_engine.py`
- `src/production/master_problem.py`
- `src/production/cut_factory.py`
- `src/audit/iteration_log.py`

If any of these narrow-fix files are changed:
- keep the change minimal
- explain exactly why it was needed
- show which Round 12 test or run exposed it
- do not widen scope beyond the localized fix

## Do not modify
Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/*`
- no redesign of validated math
- no new optimization algorithm
- no paper-scale optimality claim unless actually certified

## Required behavior

### A. Freeze critical buses from the paper figure
Use only:
- `critical_buses = [2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`

Load them from:
- `configs/critical_buses_paper_fig2.yaml`

Do not infer critical buses from `ambig.w`.

### B. Run two clearly separated experiment families

#### 1. `paper_like_tableII_family`
Create a paper-like parameter regime that approximates the paper Table II semantics without altering `data/*`.
Use config-level overrides only.

Required benchmark cases:
- `integrated_mainline_paper_like`
- `normal_only_paper_like`
- `disaster_only_paper_like`
- `deterministic_mean_value_paper_like`
- `ev_penetration_1_5x_paper_like`
- `ev_penetration_2_0x_paper_like`

#### 2. `runtime12_directional_family`
Retain the current local runtime family for directionality only.

Required benchmark cases:
- `integrated_mainline_runtime12`
- `normal_only_runtime12`
- `deterministic_mean_value_runtime12`
- `ev_penetration_1_5x_runtime12`
- `ev_penetration_2_0x_runtime12`

### C. Validation labels must remain explicit
Every run must carry one of:
- `exact`
- `epsilon_certified`
- `smoke_only`
- `failed`

Do not silently promote a smoke run into a stronger category.

### D. Failure / non-convergence logging is mandatory
If any run:
- hits `max_iterations`
- is infeasible
- is unbounded
- throws a validation/config/runtime exception
- has numeric instability
- produces any solver status other than the intended certified/solved status

then it must be recorded explicitly in:
- `results/failures.csv`
- the run's JSON log
- `docs/analysis_packs/paper_style_experiment_pack.md`

Required failure columns in `results/failures.csv`:
- `run_id`
- `case_name`
- `parameter_regime`
- `validation_level`
- `stop_reason`
- `solver_status`
- `iteration_count`
- `cut_count`
- `final_violation_upper_bound`
- `message`

### E. Required exported summaries
`results/summary.csv` must include at least:
- `run_id`
- `case_name`
- `parameter_regime`
- `validation_level`
- `stop_reason`
- `solver_status`
- `total_objective`
- `construction_cost`
- `weighted_normal_term`
- `unweighted_normal_term`
- `disaster_master_term`
- `alpha`
- `lambda_times_FP`
- `iteration_count`
- `cut_count`
- `final_violation_upper_bound`
- `opened_bus_count`
- `total_slow_chargers`
- `total_fast_chargers`

### F. Required plan exports
For every successful run, export:
- `results/plans/<run_id>_plan.csv`

with at least:
- `bus`
- `is_open`
- `n_sl`
- `n_fa`
- `is_critical`

### G. Required figures
Produce figures analogous to the paper's experiment section:

1. `results/figures/tableIII_like_components.png`
   - compare Case-1-like through Case-4-like objective components
   - use component bars, not only raw total objective

2. `results/figures/tableIV_like_sensitivity.png`
   - compare base vs 1.5x vs 2.0x EV penetration

3. `results/figures/fig6_like_plan_maps.png`
   - side-by-side siting/sizing plots for:
     - integrated_mainline_paper_like
     - normal_only_paper_like
     - disaster_only_paper_like

4. `results/figures/fig7_like_plan_map.png`
   - deterministic_mean_value_paper_like plan map

5. `results/figures/fig8_like_sensitivity_maps.png`
   - side-by-side plan maps for:
     - ev_penetration_1_5x_paper_like
     - ev_penetration_2_0x_paper_like

6. `results/figures/validation_level_overview.png`
   - exact / epsilon / smoke / failed labeling by run

7. `results/figures/iteration_trace.png`
   - only for runs that actually used the Benders engine
   - if a run failed or stopped early, that fact must be visible in the legend/title/caption metadata

### H. Interpretation report requirements
Write:
- `docs/analysis_packs/paper_style_experiment_pack.md`

It must answer explicitly:
1. Does integrated planning trade a small increase in daily cost for a large resilience gain?
2. Does deterministic mean-value underestimate disaster risk?
3. How does EV penetration affect buildout and cost?
4. Which runs are exact / epsilon-certified / smoke-only / failed?
5. Which claims are safe for colleague review, and which are not?
6. Which results are paper-like directionally, and which are only local-runtime directionality?
7. If any run failed or did not converge, what exactly happened?

### I. Honesty requirements
The report must explicitly state:
- current `runtime_12` is not numerically paper-Table-II comparable
- paper-like config is an approximation layer, not a claim of perfect paper reproduction
- raw total objective should not be used to rank heterogeneous benchmark definitions unless the report says the objectives are directly comparable
- any failed/non-converged runs are part of the final report, not hidden

## Acceptance tests
At minimum, the following must pass:
- `pytest tests/integration/test_experiment_pack_smoke.py -q`
- `pytest tests/integration/test_experiment_failure_logging.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest tests/integration/test_readiness_matrix.py -q`
- `pytest -q`

## Deliverables
You must return:
1. implementation in the allowed files
2. required tests
3. `docs/reports/round_12_report.md`
4. `configs/experiments/experiment_manifest.yaml`
5. `results/summary.csv`
6. `results/failures.csv`
7. list of generated plan CSVs
8. list of generated figures
9. `docs/analysis_packs/paper_style_experiment_pack.md`
10. concise per-run logging note including:
   - stop reason
   - validation level
   - iteration count
   - cut count
   - whether the run is safe for colleague-facing interpretation

## Report format
Write `docs/reports/round_12_report.md` with at least:

```md
# Round 12 Report

## Files changed
- ...

## Design decisions
- ...

## Benchmark families run
- ...

## Validation labels produced
- ...

## Failure logging behavior
- ...

## Tests run
- command
- result

## Produced artifacts
- summary
- failures
- plans
- figures
- interpretation report

## Known limitations
- ...

## Open issues for next round
- ...
```
