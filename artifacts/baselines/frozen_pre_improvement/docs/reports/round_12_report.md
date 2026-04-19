# Round 12 Report

## Scope
- Implemented Round 12 only.
- Kept validated model mathematics unchanged.
- Added paper-style experiment packaging on top of the existing validated pipeline.
- Added explicit failure / non-convergence logging to `results/failures.csv`, per-run JSON logs, and the interpretation report.

## Files Updated In Scope
- `configs/experiments/experiment_manifest.yaml`
- `configs/experiments/paper_like_tableII_family.yaml`
- `configs/experiments/runtime12_directional_family.yaml`
- `scripts/experiment_pack_utils.py`
- `scripts/make_experiment_figures.py`
- `scripts/run_experiment_pack.py`
- `src/audit/experiment_summary.py`
- `tests/fixtures/experiment_pack_smoke.yaml`
- `tests/integration/test_experiment_pack_smoke.py`
- `tests/integration/test_experiment_failure_logging.py`
- `docs/reports/round_12_report.md`
- `docs/analysis_packs/paper_style_experiment_pack.md`
- `results/summary.csv`
- `results/failures.csv`
- `results/plans/*.csv`
- `results/figures/*.png`
- `results/logs/*.json`

## Experiment Families
### `paper_like_tableII_family`
- `integrated_mainline_paper_like`
- `normal_only_paper_like`
- `disaster_only_paper_like`
- `deterministic_mean_value_paper_like`
- `ev_penetration_1_5x_paper_like`
- `ev_penetration_2_0x_paper_like`

Implementation note:
- used config-level overrides only
- froze `critical_buses` to `[2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`
- preserved local `runtime_12` tensors and selection-driven loading
- treated the family as a paper-like approximation layer, not a paper-number reproduction

### `runtime12_directional_family`
- `integrated_mainline_runtime12`
- `normal_only_runtime12`
- `deterministic_mean_value_runtime12`
- `ev_penetration_1_5x_runtime12`
- `ev_penetration_2_0x_runtime12`

Implementation note:
- retained the local `{1,2}` directional family
- preserved explicit `smoke_only` labeling for bounded non-certified Benders runs
- recorded all max-iteration runs into `results/failures.csv`

## Validation Labels Observed
- `exact`
  - `normal_only_paper_like`
  - `normal_only_runtime12`
- `epsilon_certified`
  - `integrated_mainline_paper_like`
  - `deterministic_mean_value_paper_like`
  - `ev_penetration_1_5x_paper_like`
  - `ev_penetration_2_0x_paper_like`
- `smoke_only`
  - `disaster_only_paper_like`
  - `integrated_mainline_runtime12`
  - `deterministic_mean_value_runtime12`
  - `ev_penetration_1_5x_runtime12`
  - `ev_penetration_2_0x_runtime12`
- `failed`
  - none in the final Round 12 manifest run

## Failure / Non-Convergence Logging
Recorded explicitly in `results/failures.csv`:
- `disaster_only_paper_like`
- `integrated_mainline_runtime12`
- `deterministic_mean_value_runtime12`
- `ev_penetration_1_5x_runtime12`
- `ev_penetration_2_0x_runtime12`

All five ended with:
- `validation_level = smoke_only`
- `stop_reason = max_iterations`
- `solver_status = OPTIMAL`

This round therefore distinguishes:
- algorithmic failure: `failed`
- bounded non-certified run: `smoke_only`, but still visible in `failures.csv`

## Key Outcomes
### Integrated vs normal-only
- In the current paper-like family, integrated did not show a daily-cost penalty relative to the normal-only benchmark.
- In the runtime-directional family, integrated and normal-only produced the same first-stage plan, but the integrated run remained `smoke_only`.

### Deterministic vs integrated
- In the paper-like family with singleton support `[1] / [1]`, deterministic mean-value collapsed to the same plan and objective as integrated.
- In the runtime-directional family, deterministic changed the first-stage plan relative to integrated, but this remains local-directional `smoke_only` evidence.

### EV penetration
- Paper-like family: monotone buildout and objective growth from base to `1.5x` to `2.0x`.
- Runtime-directional family: monotone buildout and objective growth also appeared, but remained `smoke_only`.

## Generated Artifacts
- Summary CSV: `results/summary.csv`
- Failures CSV: `results/failures.csv`
- Interpretation report: `docs/analysis_packs/paper_style_experiment_pack.md`
- Figures:
  - `results/figures/tableIII_like_components.png`
  - `results/figures/tableIV_like_sensitivity.png`
  - `results/figures/fig6_like_plan_maps.png`
  - `results/figures/fig7_like_plan_map.png`
  - `results/figures/fig8_like_sensitivity_maps.png`
  - `results/figures/validation_level_overview.png`
  - `results/figures/iteration_trace.png`

## Tests
- `pytest tests/integration/test_experiment_pack_smoke.py -q`
- `pytest tests/integration/test_experiment_failure_logging.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest tests/integration/test_readiness_matrix.py -q`
- `pytest -q`

Observed results:
- all required integration tests passed
- full suite passed: `143 passed`

## Narrow Bug Fixes
- No narrow validated-chain fix was required.
- Changes stayed inside the Round 12 packaging/report/config/test scope.
