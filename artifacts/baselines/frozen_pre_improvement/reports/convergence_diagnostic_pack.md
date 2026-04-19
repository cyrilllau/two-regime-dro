# Convergence Diagnostic Pack

## Scope
- This pack preserves the validated optimization chain and diagnoses convergence behavior only.
- Round 12 outputs were snapshotted before any new diagnostic runs.
- `critical_buses` remained explicit and unchanged.

## Baseline Snapshot
- Saved baseline under `artifacts/baselines/round_12`
- Included:
  - `summary.csv`
  - `failures.csv`
  - `round_12_report.md`
  - `paper_style_experiment_pack.md`
  - `figures/*`
  - `plans/*`

## Diagnostic Matrix
| run_id | case_name | parameter_regime | epsilon_cert | max_iterations | A_selected | B_selected | K |
| --- | --- | --- | --- | --- | --- | --- | --- |
| normal_only_paper_like_direct_exact | normal_only_paper_like_direct_exact | paper_like_tableII | 0.0 | 0 | [1] | [1] | 2 |
| integrated_paper_like_eps20000_i2_k2_a1b1 | integrated_mainline | paper_like_tableII | 20000.0 | 2 | [1] | [1] | 2 |
| integrated_paper_like_eps10000_i5_k2_a1b1 | integrated_mainline | paper_like_tableII | 10000.0 | 5 | [1] | [1] | 2 |
| integrated_paper_like_exact_i10_k2_a1b1 | integrated_mainline | paper_like_tableII | 0.0 | 10 | [1] | [1] | 2 |
| integrated_paper_like_exact_i20_k2_a1b1 | integrated_mainline | paper_like_tableII | 0.0 | 20 | [1] | [1] | 2 |
| integrated_runtime12_exact_i2_k2_a12b12 | integrated_mainline | runtime12_directional | 0.0 | 2 | [1,2] | [1,2] | 2 |
| integrated_runtime12_exact_i2_k1_a1234b1234 | integrated_mainline | runtime12_directional | 0.0 | 2 | [1,2,3,4] | [1,2,3,4] | 1 |
| integrated_runtime12_exact_i2_k3_a1234b1234 | integrated_mainline | runtime12_directional | 0.0 | 2 | [1,2,3,4] | [1,2,3,4] | 3 |
| deterministic_paper_like_eps20000_i2_k2_a1b1 | deterministic_mean_value | paper_like_tableII | 20000.0 | 2 | [1] | [1] | 2 |
| deterministic_runtime12_exact_i2_k2_a12b12 | deterministic_mean_value | runtime12_directional | 0.0 | 2 | [1] | [1] | 2 |
| disaster_only_paper_like_exact_i5_k1_a1b1 | disaster_only | paper_like_tableII | 0.0 | 5 | [1] | [1] | 1 |
| disaster_only_paper_like_exact_i20_k2_a1b1 | disaster_only | paper_like_tableII | 0.0 | 20 | [1] | [1] | 2 |

## Validation / Diagnosis Summary
| run_id | validation_level | diagnosis_label | stop_reason | solver_status | iteration_count | cut_count | final_violation_upper_bound |
| --- | --- | --- | --- | --- | --- | --- | --- |
| normal_only_paper_like_direct_exact | exact | exact_zero | direct_optimal | OPTIMAL | 0 | 1 | 0.0 |
| integrated_paper_like_eps20000_i2_k2_a1b1 | epsilon_certified | epsilon_stop | certified_epsilon | OPTIMAL | 1 | 1 | 16575.030000000726 |
| integrated_paper_like_eps10000_i5_k2_a1b1 | epsilon_certified | epsilon_stop | certified_epsilon | OPTIMAL | 5 | 5 | 6363.820000000065 |
| integrated_paper_like_exact_i10_k2_a1b1 | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 10 | 10 | 2818.310000000056 |
| integrated_paper_like_exact_i20_k2_a1b1 | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 20 | 20 | 3747.1099999961443 |
| integrated_runtime12_exact_i2_k2_a12b12 | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 2 | 2 | 10529.50500000018 |
| integrated_runtime12_exact_i2_k1_a1234b1234 | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 2 | 2 | 10492.675000000047 |
| integrated_runtime12_exact_i2_k3_a1234b1234 | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 2 | 2 | 15217.614999999438 |
| deterministic_paper_like_eps20000_i2_k2_a1b1 | epsilon_certified | epsilon_stop | certified_epsilon | OPTIMAL | 1 | 1 | 16575.030000000726 |
| deterministic_runtime12_exact_i2_k2_a12b12 | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 2 | 2 | 12987.68000000075 |
| disaster_only_paper_like_exact_i5_k1_a1b1 | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 5 | 5 | 46818.8099999954 |
| disaster_only_paper_like_exact_i20_k2_a1b1 | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 20 | 20 | 35891.95999998739 |

## Key Findings
### exact_zero
- `normal_only_paper_like_direct_exact`

### epsilon_stop
- `integrated_paper_like_eps20000_i2_k2_a1b1`: final violation `16575.030000000726` <= epsilon `20000.0`
- `integrated_paper_like_eps10000_i5_k2_a1b1`: final violation `6363.820000000065` <= epsilon `10000.0`
- `deterministic_paper_like_eps20000_i2_k2_a1b1`: final violation `16575.030000000726` <= epsilon `20000.0`

### max_iter_noncert
- `integrated_paper_like_exact_i10_k2_a1b1`: final violation `2818.310000000056` after `10` iteration(s)
- `integrated_paper_like_exact_i20_k2_a1b1`: final violation `3747.1099999961443` after `20` iteration(s)
- `integrated_runtime12_exact_i2_k2_a12b12`: final violation `10529.50500000018` after `2` iteration(s)
- `integrated_runtime12_exact_i2_k1_a1234b1234`: final violation `10492.675000000047` after `2` iteration(s)
- `integrated_runtime12_exact_i2_k3_a1234b1234`: final violation `15217.614999999438` after `2` iteration(s)
- `deterministic_runtime12_exact_i2_k2_a12b12`: final violation `12987.68000000075` after `2` iteration(s)
- `disaster_only_paper_like_exact_i5_k1_a1b1`: final violation `46818.8099999954` after `5` iteration(s)
- `disaster_only_paper_like_exact_i20_k2_a1b1`: final violation `35891.95999998739` after `20` iteration(s)

## Why The Smoke-Only Runs Are Or Are Not Alarming
- A max-iteration smoke run with a budget of 2 is usually an intentionally bounded packaging run, not proof of an algorithmic bug.
- A max-iteration run that still has nontrivial violation after 10 or 20 iterations is stronger evidence that the current cut process is struggling on that benchmark.
- An epsilon stop with nonzero violation is not exact convergence; it is a certificate relative to the chosen epsilon.

## Suspected Bottlenecks
- 1. `master` dominated 12 run(s).
- 2. `separation` dominated 0 run(s).
- 3. `dual` dominated 0 run(s).

## Failure / Non-Certification Table
| run_id | case_name | parameter_regime | validation_level | diagnosis_label | stop_reason | solver_status | iteration_count | cut_count | final_violation_upper_bound | message |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| integrated_paper_like_exact_i10_k2_a1b1 | integrated_mainline | paper_like_tableII | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 10 | 10 | 2818.310000000056 | true non-certification under enlarged iteration budget; lower-bound gain=1003.078; violation drop=13756.720; dominant runtime component: master-side; smoke_only result should not be promoted beyond directional diagnosis |
| integrated_paper_like_exact_i20_k2_a1b1 | integrated_mainline | paper_like_tableII | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 20 | 20 | 3747.1099999961443 | true non-certification under enlarged iteration budget; lower-bound gain=1173.583; violation drop=12827.920; dominant runtime component: master-side; repeated outage pattern observed; smoke_only result should not be promoted beyond directional diagnosis |
| integrated_runtime12_exact_i2_k2_a12b12 | integrated_mainline | runtime12_directional | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 2 | 2 | 10529.50500000018 | intentionally bounded smoke run with low iteration budget; lower-bound gain=87.353; violation drop=2458.175; dominant runtime component: master-side; smoke_only result should not be promoted beyond directional diagnosis |
| integrated_runtime12_exact_i2_k1_a1234b1234 | integrated_mainline | runtime12_directional | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 2 | 2 | 10492.675000000047 | intentionally bounded smoke run with low iteration budget; lower-bound gain=1324.209; violation drop=1724.215; dominant runtime component: master-side; smoke_only result should not be promoted beyond directional diagnosis |
| integrated_runtime12_exact_i2_k3_a1234b1234 | integrated_mainline | runtime12_directional | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 2 | 2 | 15217.614999999438 | intentionally bounded smoke run with low iteration budget; lower-bound gain=1031.514; violation drop=7690.955; dominant runtime component: master-side; smoke_only result should not be promoted beyond directional diagnosis |
| deterministic_runtime12_exact_i2_k2_a12b12 | deterministic_mean_value | runtime12_directional | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 2 | 2 | 12987.68000000075 | intentionally bounded smoke run with low iteration budget; lower-bound gain=-23.046; violation drop=3789.950; dominant runtime component: master-side; smoke_only result should not be promoted beyond directional diagnosis |
| disaster_only_paper_like_exact_i5_k1_a1b1 | disaster_only | paper_like_tableII | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 5 | 5 | 46818.8099999954 | true non-certification under enlarged iteration budget; lower-bound gain=29087.074; violation drop=104728.770; dominant runtime component: master-side; smoke_only result should not be promoted beyond directional diagnosis |
| disaster_only_paper_like_exact_i20_k2_a1b1 | disaster_only | paper_like_tableII | smoke_only | max_iter_noncert | max_iterations | OPTIMAL | 20 | 20 | 35891.95999998739 | true non-certification under enlarged iteration budget; lower-bound gain=44130.917; violation drop=115655.620; dominant runtime component: master-side; repeated outage pattern observed; smoke_only result should not be promoted beyond directional diagnosis |

## Recommendation For The Next Algorithm Round
- The current diagnostic pack suggests focusing next on cut-process effectiveness rather than data loading or model correctness.
- The strongest candidates are:
  1. analyze repeated outage or near-duplicate cut patterns
  2. improve the effectiveness of generated cuts under larger support / larger `K`
  3. revisit runtime allocation only after confirming whether separation or dual re-solves dominate

## Figures
- `results/convergence_diagnostics/figures/validation_category_overview.png`
- `results/convergence_diagnostics/figures/violation_vs_iteration_budget.png`
- `results/convergence_diagnostics/figures/runtime_breakdown_by_run.png`
- `results/convergence_diagnostics/figures/cut_efficacy_trace.png`
- `results/convergence_diagnostics/figures/outage_repeat_patterns.png`

## Iteration Logs Used
- `results/convergence_diagnostics/logs/deterministic_paper_like_eps20000_i2_k2_a1b1_iteration_log.json`
- `results/convergence_diagnostics/logs/deterministic_runtime12_exact_i2_k2_a12b12_iteration_log.json`
- `results/convergence_diagnostics/logs/disaster_only_paper_like_exact_i20_k2_a1b1_iteration_log.json`
- `results/convergence_diagnostics/logs/disaster_only_paper_like_exact_i5_k1_a1b1_iteration_log.json`
- `results/convergence_diagnostics/logs/integrated_paper_like_eps10000_i5_k2_a1b1_iteration_log.json`
- `results/convergence_diagnostics/logs/integrated_paper_like_eps20000_i2_k2_a1b1_iteration_log.json`
- `results/convergence_diagnostics/logs/integrated_paper_like_exact_i10_k2_a1b1_iteration_log.json`
- `results/convergence_diagnostics/logs/integrated_paper_like_exact_i20_k2_a1b1_iteration_log.json`
- `results/convergence_diagnostics/logs/integrated_runtime12_exact_i2_k1_a1234b1234_iteration_log.json`
- `results/convergence_diagnostics/logs/integrated_runtime12_exact_i2_k2_a12b12_iteration_log.json`
- `results/convergence_diagnostics/logs/integrated_runtime12_exact_i2_k3_a1234b1234_iteration_log.json`
