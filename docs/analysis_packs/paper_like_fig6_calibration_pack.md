# Paper-Like Fig. 6 Calibration Pack

## Scope
- This pack performs config-level calibration only.
- No validated optimization math was changed.
- The exact anchor remains `normal_only` under `direct_master`.
- The current `runtime_12` source is still not paper-number reproduction.

## Stage 1 Candidate Sweep
| candidate_id | validation_level | opened_bus_count | total_slow_chargers | total_fast_chargers | fast_station_count | capped_slow_station_count | cluster_count | out_of_cluster_open_count | meets_stage1_rules |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S0_baseline | exact | 15 | 362 | 24 | 5 | 13 | 4 | 3 | False |
| S1_site_cost_up | exact | 15 | 361 | 24 | 5 | 13 | 4 | 3 | False |
| S2_site_cost_up_transport_down | exact | 15 | 361 | 24 | 5 | 13 | 4 | 3 | False |
| S3_site_cost_up_transport_half | exact | 15 | 361 | 24 | 5 | 13 | 4 | 3 | False |
| S4_sparse_slow_cost_up | exact | 15 | 361 | 24 | 5 | 13 | 4 | 3 | False |
| S5_sparse_slow_cost_up_more | exact | 15 | 361 | 24 | 5 | 13 | 4 | 3 | False |
| S6_mixed_station_bias | exact | 15 | 361 | 24 | 5 | 13 | 4 | 3 | False |

## Winner Selection
- Selected winner candidate: `S1_site_cost_up`
- Winner selection basis: `lexicographic_best_fallback`
- Winner opened buses: `15`
- Winner total slow / fast: `361 / 24`
- Winner opened-site list: `3:25/6; 4:25/0; 5:25/3; 6:25/0; 9:25/0; 18:25/0; 19:25/10; 20:25/1; 25:21/0; 26:25/0; 27:25/0; 28:25/4; 29:25/0; 32:25/0; 33:15/0`

## Stage 2 Propagation
| run_id | mode | validation_level | stop_reason | opened_bus_count | total_slow_chargers | total_fast_chargers |
| --- | --- | --- | --- | --- | --- | --- |
| integrated_mainline_paper_like_tuned | integrated_mainline | epsilon_certified | certified_epsilon | 15 | 361 | 24 |
| normal_only_paper_like_tuned | normal_only | exact | direct_optimal | 15 | 361 | 24 |
| disaster_only_paper_like_tuned | disaster_only | smoke_only | max_iterations | 1 | 25 | 10 |
| deterministic_mean_value_paper_like_tuned | deterministic_mean_value | epsilon_certified | certified_epsilon | 15 | 361 | 24 |

## Stage 3 Demand Normalization
- Triggered: `True`
| run_id | ev_penetration_scale | validation_level | opened_bus_count | total_slow_chargers | total_fast_chargers | opened_bus_list |
| --- | --- | --- | --- | --- | --- | --- |
| normal_only_paper_like_tuned_D1_scale_0_85 | 0.85 | exact | 13 | 308 | 20 | 3:25/4; 4:25/0; 5:25/1; 9:25/0; 17:12/0; 18:25/0; 19:25/10; 20:25/0; 26:25/0; 27:25/0; 28:25/5; 32:25/0; 33:21/0 |
| normal_only_paper_like_tuned_D2_scale_0_70 | 0.7 | exact | 10 | 250 | 17 | 3:25/2; 4:25/0; 5:25/0; 9:25/0; 18:25/0; 19:25/10; 26:25/0; 27:25/0; 28:25/5; 32:25/0 |

## Key Findings
- No Stage 1 candidate satisfied the target paper-like siting rules.
- The exact `normal_only` anchor stayed at `15` opened buses for all `S0`-`S6` cost-only candidates.
- The lexicographic fallback winner was therefore `S1_site_cost_up`, not because it solved the target, but because it was the first tied-best cost-only variant.
- Stage 2 propagation confirmed the same qualitative result:
  - `normal_only_paper_like_tuned` stayed at `15` opened buses.
  - `integrated_mainline_paper_like_tuned` also stayed at `15` opened buses.
  - `disaster_only_paper_like_tuned` remained sparse at `1` site, so the excessive siting pressure is still coming from the normal-operation side.
- Demand normalization was the only lever that materially changed the exact `normal_only` siting pattern:
  - `0.85` scale reduced the exact anchor to `13` sites.
  - `0.70` scale reduced the exact anchor to `10` sites.
- Even after `0.70`, the current local `runtime_12`-based approximation still did not reach the desired `6-8` sites or `<= 220` slow chargers.

## Lever Interpretation
- Sparsity levers:
  - `cfix`
  - `ctrans_scalar`
  - `ccons_sl`
- Station-mix lever:
  - `ccons_fa`
- Demand-normalization lever:
  - `ev_penetration_scale`
- Explicitly not used as tuning levers:
  - `epsilon_cert`
  - `max_iterations`
  - `critical_buses`
  - `gamma`
  - `theta`
  - `cunmet`
  - `nbar_sl`
  - `nbar_fa`

## Figures
- results/paper_like_calibration/figures/stage1_candidate_metrics.png
- results/paper_like_calibration/figures/baseline_tuned_target_plan_maps.png
- results/paper_like_calibration/figures/demand_normalization_progression.png

## Failure / Non-Exact Visibility
| stage | run_id | validation_level | stop_reason | solver_status | final_violation_upper_bound | message |
| --- | --- | --- | --- | --- | --- | --- |
| stage2 | disaster_only_paper_like_tuned | smoke_only | max_iterations | OPTIMAL | 68546.42000001483 | Run completed a bounded smoke-only solve but did not certify; stop_reason=max_iterations, solver_status=OPTIMAL. |
