# Paper-Style Experiment Pack

## Scope
- Round 12 froze `critical_buses` to `[2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`.
- Validation labels are explicit:
  - `exact`
  - `epsilon_certified`
  - `smoke_only`
  - `failed`
- The current `runtime_12` package is **not** numerically paper-Table-II comparable.
- The paper-like family is an approximation layer built through config-level overrides only.

## Validation Label Overview
- `exact`: `normal_only_paper_like`, `normal_only_runtime12`
- `epsilon_certified`: `integrated_mainline_paper_like`, `deterministic_mean_value_paper_like`, `ev_penetration_1_5x_paper_like`, `ev_penetration_2_0x_paper_like`
- `smoke_only`: `disaster_only_paper_like`, `integrated_mainline_runtime12`, `deterministic_mean_value_runtime12`, `ev_penetration_1_5x_runtime12`, `ev_penetration_2_0x_runtime12`
- `failed`: none

## Summary Table
| run_id | case_name | parameter_regime | validation_level | stop_reason | solver_status | iteration_count | cut_count | final_violation_upper_bound |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| integrated_mainline_paper_like | integrated_mainline_paper_like | paper_like_tableII | epsilon_certified | certified_epsilon | OPTIMAL | 1 | 1 | 16575.030000000726 |
| normal_only_paper_like | normal_only_paper_like | paper_like_tableII | exact | direct_optimal | OPTIMAL | 0 | 1 | 0.0 |
| disaster_only_paper_like | disaster_only_paper_like | paper_like_tableII | smoke_only | max_iterations | OPTIMAL | 5 | 5 | 71546.45000003651 |
| deterministic_mean_value_paper_like | deterministic_mean_value_paper_like | paper_like_tableII | epsilon_certified | certified_epsilon | OPTIMAL | 1 | 1 | 16575.030000000726 |
| ev_penetration_1_5x_paper_like | ev_penetration_1_5x_paper_like | paper_like_tableII | epsilon_certified | certified_epsilon | OPTIMAL | 1 | 1 | 3692.670000000391 |
| ev_penetration_2_0x_paper_like | ev_penetration_2_0x_paper_like | paper_like_tableII | epsilon_certified | certified_epsilon | OPTIMAL | 1 | 1 | 2601.750000000233 |
| integrated_mainline_runtime12 | integrated_mainline_runtime12 | runtime12_directional | smoke_only | max_iterations | OPTIMAL | 2 | 2 | 10529.50500000018 |
| normal_only_runtime12 | normal_only_runtime12 | runtime12_directional | exact | direct_optimal | OPTIMAL | 0 | 1 | 0.0 |
| deterministic_mean_value_runtime12 | deterministic_mean_value_runtime12 | runtime12_directional | smoke_only | max_iterations | OPTIMAL | 2 | 2 | 12987.68000000075 |
| ev_penetration_1_5x_runtime12 | ev_penetration_1_5x_runtime12 | runtime12_directional | smoke_only | max_iterations | OPTIMAL | 2 | 2 | 5985.6700000002165 |
| ev_penetration_2_0x_runtime12 | ev_penetration_2_0x_runtime12 | runtime12_directional | smoke_only | max_iterations | OPTIMAL | 2 | 2 | 5985.6700000002165 |

## Objective Components
| run_id | construction_cost | weighted_normal_term | unweighted_normal_term | disaster_master_term | total_objective |
| --- | --- | --- | --- | --- | --- |
| integrated_mainline_paper_like | 171730.13627193242 | 13035357.592206404 | 18621939.41743772 | 0.0 | 13207087.728478337 |
| normal_only_paper_like | 171760.06442104536 | 18622035.264121648 | 18622035.264121648 | 0.0 | 18793795.328542694 |
| disaster_only_paper_like | 23113.82481765002 | 0.0 | 76287766.14798273 | 3709.868462252223 | 26823.693279902243 |
| deterministic_mean_value_paper_like | 171730.13627193242 | 13035357.592206404 | 18621939.41743772 | 0.0 | 13207087.728478337 |
| ev_penetration_1_5x_paper_like | 262853.6935867764 | 17010934.51354102 | 24301335.019344315 | 0.0 | 17273788.20712779 |
| ev_penetration_2_0x_paper_like | 305364.11493179464 | 25867747.20746967 | 36953924.58209953 | 0.0 | 26173111.322401464 |
| integrated_mainline_runtime12 | 4410273.923833655 | 20506437.556191694 | 22784930.61799077 | 87.35278330225373 | 24916798.832808632 |
| normal_only_runtime12 | 4410273.923833655 | 22784930.617990784 | 22784930.617990784 | 0.0 | 27195204.541824397 |
| deterministic_mean_value_runtime12 | 4183374.4336056146 | 20674646.360838365 | 22971829.289820403 | 103.5706534132272 | 24858124.365097396 |
| ev_penetration_1_5x_runtime12 | 6172481.341952035 | 30577949.732886072 | 33975499.70320675 | 122.10888533352457 | 36750553.183723375 |
| ev_penetration_2_0x_runtime12 | 6470032.170454676 | 46930921.15141376 | 52145467.94601529 | 122.10888533352457 | 53401075.4307536 |

## Failure / Non-Convergence Table
| run_id | case_name | parameter_regime | validation_level | stop_reason | solver_status | iteration_count | cut_count | final_violation_upper_bound | message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| disaster_only_paper_like | disaster_only_paper_like | paper_like_tableII | smoke_only | max_iterations | OPTIMAL | 5 | 5 | 71546.45000003651 | Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL. |
| integrated_mainline_runtime12 | integrated_mainline_runtime12 | runtime12_directional | smoke_only | max_iterations | OPTIMAL | 2 | 2 | 10529.50500000018 | Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL. |
| deterministic_mean_value_runtime12 | deterministic_mean_value_runtime12 | runtime12_directional | smoke_only | max_iterations | OPTIMAL | 2 | 2 | 12987.68000000075 | Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL. |
| ev_penetration_1_5x_runtime12 | ev_penetration_1_5x_runtime12 | runtime12_directional | smoke_only | max_iterations | OPTIMAL | 2 | 2 | 5985.6700000002165 | Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL. |
| ev_penetration_2_0x_runtime12 | ev_penetration_2_0x_runtime12 | runtime12_directional | smoke_only | max_iterations | OPTIMAL | 2 | 2 | 5985.6700000002165 | Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL. |

## What Happened For Failed Or Non-Converged Runs
- `disaster_only_paper_like`: validation=`smoke_only`, stop_reason=`max_iterations`, solver_status=`OPTIMAL`, message=Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL.
- `integrated_mainline_runtime12`: validation=`smoke_only`, stop_reason=`max_iterations`, solver_status=`OPTIMAL`, message=Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL.
- `deterministic_mean_value_runtime12`: validation=`smoke_only`, stop_reason=`max_iterations`, solver_status=`OPTIMAL`, message=Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL.
- `ev_penetration_1_5x_runtime12`: validation=`smoke_only`, stop_reason=`max_iterations`, solver_status=`OPTIMAL`, message=Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL.
- `ev_penetration_2_0x_runtime12`: validation=`smoke_only`, stop_reason=`max_iterations`, solver_status=`OPTIMAL`, message=Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL.

## Direct Answers To The Round-12 Interpretation Questions
1. Does integrated planning trade a small increase in daily cost for a large resilience gain?
   - In the current paper-like family, no clear daily-cost penalty appears. The integrated run is epsilon-certified, returns a slightly lower normal-cost term, and does not expose a positive disaster master term under the reduced `[1] / [1]` support.
2. Does deterministic mean-value underestimate disaster risk?
   - The certified paper-like small-support benchmark does not show an underestimation gap: deterministic mean-value collapses to the same plan and objective. The stronger underestimation question is therefore unresolved here.
3. How does EV penetration affect buildout and cost?
   - The paper-like family shows monotone buildout and cost growth from base to 1.5x to 2.0x EV penetration. That direction is robust in the produced artifacts, but still belongs to a local approximation layer.

## Integrated Vs Normal-Only (Paper-Like Family)
- Integrated run: `integrated_mainline_paper_like` (`epsilon_certified`, stop_reason=`certified_epsilon`)
- Normal-only run: `normal_only_paper_like` (`exact`, stop_reason=`direct_optimal`)
- Construction cost comparison:
  - integrated = `171730.13627193242`
  - normal-only = `171760.06442104536`
- Unweighted normal-cost comparison:
  - integrated = `18621939.41743772`
  - normal-only = `18622035.264121648`
- Disaster-master comparison:
  - integrated = `0.0`
  - normal-only = `0.0`
- Plan comparison: The two runs returned different first-stage plans.
- Interpretation boundary: Use this as a paper-like directional comparison only. The local runtime data and current approximation layer are not paper-number reproduction.


## Disaster-Only Paper-Like Run
- `disaster_only_paper_like`: `smoke_only`
- Interpretation boundary:
  - this benchmark removes weighted normal cost by construction
  - raw totals should not be ranked directly against integrated/normal-only unless that caveat is stated

## Deterministic Vs Integrated (Paper-Like Family)
- Integrated run: `integrated_mainline_paper_like` (`epsilon_certified`)
- Deterministic run: `deterministic_mean_value_paper_like` (`epsilon_certified`)
- Weighted normal term:
  - integrated = `13035357.592206404`
  - deterministic = `13035357.592206404`
- Disaster master term:
  - integrated = `0.0`
  - deterministic = `0.0`
- Plan comparison: The deterministic mean-value run landed on the same first-stage plan.
- Interpretation boundary: Treat this as a directional deterministic-vs-integrated comparison only. The key question is whether deterministic mean-value planning understates disaster risk in the current local benchmark pack.


## EV-Penetration Interpretation (Paper-Like Family)
- Base run `integrated_mainline_paper_like`:
  - validation = `epsilon_certified`
  - construction = `171730.13627193242`
  - total objective = `13207087.728478337`
  - opened buses / slow / fast = `15 / 361 / 24`
- 1.5x run `ev_penetration_1_5x_paper_like`:
  - validation = `epsilon_certified`
  - construction = `262853.6935867764`
  - total objective = `17273788.20712779`
  - opened buses / slow / fast = `23 / 575 / 36`
- 2.0x run `ev_penetration_2_0x_paper_like`:
  - validation = `epsilon_certified`
  - construction = `305364.11493179464`
  - total objective = `26173111.322401464`
  - opened buses / slow / fast = `26 / 633 / 47`
- Interpretation boundary: These are paper-like directionality runs only. They are not a claim of reproducing the paper sensitivity table numerically.


## Integrated Vs Normal-Only (Runtime-Directional Family)
- Integrated run: `integrated_mainline_runtime12` (`smoke_only`, stop_reason=`max_iterations`)
- Normal-only run: `normal_only_runtime12` (`exact`, stop_reason=`direct_optimal`)
- Construction cost comparison:
  - integrated = `4410273.923833655`
  - normal-only = `4410273.923833655`
- Unweighted normal-cost comparison:
  - integrated = `22784930.61799077`
  - normal-only = `22784930.617990784`
- Disaster-master comparison:
  - integrated = `87.35278330225373`
  - normal-only = `0.0`
- Plan comparison: The two runs returned the same first-stage plan.
- Interpretation boundary: This family must be read as local-runtime directionality only. If a run is smoke_only, it stays smoke_only.


## Deterministic Vs Integrated (Runtime-Directional Family)
- Integrated run: `integrated_mainline_runtime12` (`smoke_only`)
- Deterministic run: `deterministic_mean_value_runtime12` (`smoke_only`)
- Weighted normal term:
  - integrated = `20506437.556191694`
  - deterministic = `20674646.360838365`
- Disaster master term:
  - integrated = `87.35278330225373`
  - deterministic = `103.5706534132272`
- Plan comparison: The deterministic mean-value run changed the first-stage plan.
- Interpretation boundary: The runtime-directional family is not paper-comparable. Any deterministic-vs-integrated conclusion here is local-directional only.


## EV-Penetration Interpretation (Runtime-Directional Family)
- Base run `integrated_mainline_runtime12`:
  - validation = `smoke_only`
  - construction = `4410273.923833655`
  - total objective = `24916798.832808632`
  - opened buses / slow / fast = `18 / 360 / 24`
- 1.5x run `ev_penetration_1_5x_runtime12`:
  - validation = `smoke_only`
  - construction = `6172481.341952035`
  - total objective = `36750553.183723375`
  - opened buses / slow / fast = `25 / 500 / 42`
- 2.0x run `ev_penetration_2_0x_runtime12`:
  - validation = `smoke_only`
  - construction = `6470032.170454676`
  - total objective = `53401075.4307536`
  - opened buses / slow / fast = `26 / 520 / 53`
- Interpretation boundary: These runs are for local directionality only, especially when validation remains smoke_only.


## Safe Colleague-Facing Claims
- Validation labels are explicit at the run level and are carried into the summary CSV, failures CSV, and per-run JSON logs.
- The paper-like family is an approximation layer on top of the local runtime data, not a claim of exact Table-II number reproduction.
- The runtime12 directional family is useful for qualitative directionality only unless a run is explicitly exact or epsilon-certified.

## Unsafe Or Overstated Claims
- Do not present current runtime_12 totals as paper-number reproduction.
- Do not rank heterogeneous benchmark definitions by raw total objective unless the report explicitly says the objectives are directly comparable.
- Do not treat smoke-only runs as certified evidence.

## Paper-Like Vs Local-Runtime Directionality
- The `paper_like_tableII_family` is closer in economic semantics to the paper experiment section, but it is still built on the local `runtime_12` data package.
- The `runtime12_directional_family` is purely a local-directional benchmark family.
- Neither family should be described as paper-scale validation unless the produced artifacts explicitly certify that claim.

## Figure Outputs
- `results/figures/tableIII_like_components.png`
- `results/figures/tableIV_like_sensitivity.png`
- `results/figures/fig6_like_plan_maps.png`
- `results/figures/fig7_like_plan_map.png`
- `results/figures/fig8_like_sensitivity_maps.png`
- `results/figures/validation_level_overview.png`
- `results/figures/iteration_trace.png`
