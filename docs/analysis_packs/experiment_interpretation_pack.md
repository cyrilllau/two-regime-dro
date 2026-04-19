# Experiment Interpretation Pack

## Scope
- `critical_buses` were fixed explicitly from the paper Fig. 2 set:
  `[2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`
- Validation labels are explicit:
  - `exact`
  - `epsilon_certified`
  - `smoke_only`
- No paper-scale optimality claim is made in this pack.

## Validation Overview
| run_id | case_name | validation_level | stop_reason | iteration_count | cut_count | final_violation_upper_bound |
| --- | --- | --- | --- | --- | --- | --- |
| integrated_mainline_certified_small | integrated_mainline_certified_small | epsilon_certified | certified_epsilon | 4 | 4 | 6167.220000000321 |
| normal_only_certified_small | normal_only_certified_small | exact | direct_optimal | 0 | 1 | 0.0 |
| deterministic_mean_value_certified_small | deterministic_mean_value_certified_small | epsilon_certified | certified_epsilon | 4 | 4 | 6167.220000000321 |
| integrated_mainline_runtime12 | integrated_mainline_runtime12 | smoke_only | max_iterations | 2 | 2 | 10529.50500000018 |
| normal_only_runtime12 | normal_only_runtime12 | exact | direct_optimal | 0 | 1 | 0.0 |
| deterministic_mean_value_runtime12 | deterministic_mean_value_runtime12 | smoke_only | max_iterations | 2 | 2 | 12987.68000000075 |
| ev_penetration_1_5x_runtime12 | ev_penetration_1_5x_runtime12 | smoke_only | max_iterations | 2 | 2 | 5985.6700000002165 |
| ev_penetration_2_0x_runtime12 | ev_penetration_2_0x_runtime12 | smoke_only | max_iterations | 2 | 2 | 5985.6700000002165 |

## Objective Decomposition Overview
| run_id | construction_cost | unweighted_normal_term | disaster_master_term | total_objective |
| --- | --- | --- | --- | --- |
| integrated_mainline_certified_small | 4421143.36 | 22875626.944 | 167.617 | 25009375.227 |
| normal_only_certified_small | 4421143.36 | 22875626.944 | 0.0 | 27296770.304 |
| deterministic_mean_value_certified_small | 4421143.36 | 22875626.944 | 167.617 | 25009375.227 |
| integrated_mainline_runtime12 | 4410273.924 | 22784930.618 | 87.353 | 24916798.833 |
| normal_only_runtime12 | 4410273.924 | 22784930.618 | 0.0 | 27195204.542 |
| deterministic_mean_value_runtime12 | 4183374.434 | 22971829.29 | 103.571 | 24858124.365 |
| ev_penetration_1_5x_runtime12 | 6172481.342 | 33975499.703 | 122.109 | 36750553.184 |
| ev_penetration_2_0x_runtime12 | 6470032.17 | 52145467.946 | 122.109 | 53401075.431 |

## Integrated Vs Normal-Only
1. Certified-small family:
   - `integrated_mainline_certified_small` is `epsilon_certified` with stop reason `certified_epsilon`.
   - `normal_only_certified_small` is `exact` via a direct benchmark solve.
   - Both runs produced the same first-stage siting/charger pattern under the reduced `[1] / [1]` support.
2. Default `runtime_12` family:
   - `integrated_mainline_runtime12` is `smoke_only`.
   - `normal_only_runtime12` is `exact`.
   - The safer colleague-facing takeaway is qualitative only: the integrated run keeps an explicit disaster master term, while the normal-only benchmark removes it by construction.
   - Within this smoke-only family, the integrated and normal-only runs also happened to return the same first-stage plan.


## Deterministic Vs Integrated
1. Certified-small family:
   - `deterministic_mean_value_certified_small` is `epsilon_certified`.
   - Because the certified-small family already uses singleton scenario supports, the deterministic mean-value benchmark collapses to the same reduced-support data and is not informative by itself.
2. Default `runtime_12` family:
   - `deterministic_mean_value_runtime12` is `smoke_only`.
   - Compared with `integrated_mainline_runtime12`, its disaster term is interpreted only provisionally because this family is smoke-oriented.
   - The smoke-only deterministic benchmark changed the first-stage plan relative to the integrated run.

## EV-Penetration Interpretation
- Base default runtime: `integrated_mainline_runtime12`
  - construction = `4410273.923833655`
  - unweighted normal term = `22784930.61799077`
  - disaster term = `87.35278330225373`
  - opened buses / slow / fast = `18 / 360 / 24`
- 1.5x EV penetration:
  - construction = `6172481.341952035`
  - unweighted normal term = `33975499.70320675`
  - disaster term = `122.10888533352457`
  - opened buses / slow / fast = `25 / 500 / 42`
- 2.0x EV penetration:
  - construction = `6470032.170454676`
  - unweighted normal term = `52145467.94601529`
  - disaster term = `122.10888533352457`
  - opened buses / slow / fast = `26 / 520 / 53`
- Interpretation:
  - use these runs for directionality only unless their validation label is not `smoke_only`
  - higher EV penetration should be read as a packaging-layer scaling of EV charging and V2G-related tensors, not as a paper-Table-II reproduction


## What Is Safe For Colleague Review
- The tiny validation chain from earlier rounds remains exact.
- Every experiment run is labeled explicitly as `exact`, `epsilon_certified`, or `smoke_only` in `results/summary.csv`.
- The default runtime `{1,2}` family remains smoke-oriented unless a specific run actually certified.

## What Is Provisional
- Integrated vs normal-only differences on default `runtime_12` are provisional because the family is smoke-oriented.
- Deterministic mean-value vs integrated differences on default `runtime_12` are provisional for the same reason.
- EV-penetration directionality on default `runtime_12` is smoke-only unless a specific run certified.

## Paper-Comparability Honesty Check
- The current `runtime_12` pack is not numerically identical to the paper Table II regime.
- This pack uses the local runtime parameters already frozen in the repo, including 24 normal periods, 4 disaster periods, and the current local capital/operating coefficients.
- Therefore absolute magnitudes are not directly paper-comparable.
- The correct colleague-facing use of this pack is:
  - directionality
  - trade-off inspection
  - validation-level awareness
  - not direct paper-number reproduction

## Figure Outputs
- `results/figures/objective_components.png`
- `results/figures/benchmark_comparison.png`
- `results/figures/iteration_trace.png`
- `results/figures/plan_map.png`

## Artifact Notes
- Per-run logs record the exact validation label and stop reason used in this pack.
- Benders iteration artifacts are saved only for the runs that actually used the Benders engine.
