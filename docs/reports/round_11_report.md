# Round 11 Report

## Files changed
- `configs/critical_buses_paper_fig2.yaml`
- `configs/experiments/experiment_manifest.yaml`
- `configs/experiments/certified_small_family.yaml`
- `configs/experiments/runtime12_smoke_family.yaml`
- `scripts/experiment_pack_utils.py`
- `scripts/make_experiment_figures.py`
- `scripts/run_experiment_pack.py`
- `src/audit/experiment_summary.py`
- `tests/integration/test_experiment_pack_smoke.py`
- `tests/fixtures/experiment_pack_smoke.yaml`

## Design decisions
- Kept the validated optimization pipeline unchanged and treated Round 11 as packaging only: the new code loads canonical instances, runs the existing master/Benders stack, and exports auditable outputs.
- Froze `critical_buses` for the whole pack to the paper Fig. 2 set:
  - `[2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`
- Made validation labeling explicit per run:
  - `exact`
  - `epsilon_certified`
  - `smoke_only`
- Kept the first-stage objective boundary explicit in the exported summaries by recording pure construction cost from `construction_cost_value`, not the attached first-stage objective.

## Benchmark families run
- `certified_small_family` on `data/runtime_12` with explicit singleton selection `{A=1, B=1}`
  - `integrated_mainline_certified_small`
  - `normal_only_certified_small`
  - `deterministic_mean_value_certified_small`
- `runtime12_smoke_family` on `data/runtime_12` with the default selected support `{A={1,2}, B={1,2}}`
  - `integrated_mainline_runtime12`
  - `normal_only_runtime12`
  - `deterministic_mean_value_runtime12`
  - `ev_penetration_1_5x_runtime12`
  - `ev_penetration_2_0x_runtime12`

## Validation labeling outcomes
- Exact:
  - `normal_only_certified_small`
  - `normal_only_runtime12`
- Epsilon-certified:
  - `integrated_mainline_certified_small`
  - `deterministic_mean_value_certified_small`
- Smoke-only:
  - `integrated_mainline_runtime12`
  - `deterministic_mean_value_runtime12`
  - `ev_penetration_1_5x_runtime12`
  - `ev_penetration_2_0x_runtime12`

## Interpretation summary
- Integrated vs normal-only, certified-small family:
  - the integrated and normal-only runs produced the same first-stage plan under the singleton `{1}/{1}` support
  - the family therefore does not show a plan-level separation by itself under the current reduced runtime fixture
- Integrated vs normal-only, default `runtime_12` family:
  - the runtime family is still smoke-only on the integrated side
  - the integrated and normal-only runs also happened to return the same first-stage plan in this bounded smoke pack
  - this is still only a smoke-level observation, not a paper-comparable conclusion
- Deterministic vs integrated:
  - in the certified-small family the deterministic benchmark collapses onto the same singleton support and matches the integrated plan
  - in the default `runtime_12` smoke family the deterministic benchmark changes the first-stage plan relative to the integrated run
- EV penetration:
  - 1.5x and 2.0x scaling increased both buildout and cost relative to the base runtime smoke case
  - opened buses / slow / fast changed from `18 / 360 / 24` at base to `25 / 500 / 42` at 1.5x and `26 / 520 / 53` at 2.0x
  - these runs remain smoke-only and should be read only for directionality
- Paper comparability:
  - the current local `runtime_12` data are not numerically paper-Table-II comparable
  - the correct use of this pack is inspection of directionality and validation status, not reproduction of the paper’s reported magnitudes

## Produced artifacts
- Manifest:
  - `configs/experiments/experiment_manifest.yaml`
- Summary CSV:
  - `results/summary.csv`
- Plan CSVs:
  - `results/plans/integrated_mainline_certified_small_plan.csv`
  - `results/plans/normal_only_certified_small_plan.csv`
  - `results/plans/deterministic_mean_value_certified_small_plan.csv`
  - `results/plans/integrated_mainline_runtime12_plan.csv`
  - `results/plans/normal_only_runtime12_plan.csv`
  - `results/plans/deterministic_mean_value_runtime12_plan.csv`
  - `results/plans/ev_penetration_1_5x_runtime12_plan.csv`
  - `results/plans/ev_penetration_2_0x_runtime12_plan.csv`
- Figures:
  - `results/figures/objective_components.png`
  - `results/figures/benchmark_comparison.png`
  - `results/figures/iteration_trace.png`
  - `results/figures/plan_map.png`
- Interpretation pack:
  - `reports/experiment_interpretation_pack.md`

## Tests run
- `pytest tests/integration/test_experiment_pack_smoke.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest tests/integration/test_readiness_matrix.py -q`
- `pytest -q`

## Test outcomes
- `pytest tests/integration/test_experiment_pack_smoke.py -q` -> `1 passed in 3.15s`
- `pytest tests/integration/test_benders_runtime_certification.py -q` -> `1 passed in 2.03s`
- `pytest tests/integration/test_readiness_matrix.py -q` -> `1 passed in 0.00s`
- `pytest -q` -> `142 passed in 25.87s`

## Narrow bug fixes
- No narrow fix was required in the allowed validated-chain files:
  - `src/production/benders_engine.py`
  - `src/production/master_problem.py`
  - `src/production/cut_factory.py`
  - `src/audit/iteration_log.py`
- Two packaging-scope fixes were required in the newly added Round 11 scripts:
  - `scripts/experiment_pack_utils.py` now bootstraps repo-root imports so `python scripts/run_experiment_pack.py` works outside pytest
  - `scripts/run_experiment_pack.py` now renders the interpretation report against arbitrary manifests instead of assuming the full production manifest is always used

## Open notes
- The experiment pack is ready for colleague-facing inspection as long as each run’s validation label is carried with it.
- The default `runtime_12` family remains a smoke family, not a final validation family.
- No paper-scale optimality or paper-number reproduction claim is made in this round.
