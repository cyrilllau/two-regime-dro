# Cut Process Diagnostic Pack

## Scope
- This pack diagnoses the Benders cut process only.
- Validated model mathematics were left unchanged.
- The only algorithm-side strengthening in scope is conservative duplicate-cut guarding plus repeated-outage/cut reporting.

## Comparative sweep summary
| comparison_group | baseline_label | baseline_violation | improved_label | improved_violation | helped |
| --- | --- | --- | --- | --- | --- |
| integrated_paper_like_exact_i10_k2_a1b1 | max_iter_noncert | 2818.310000000056 | max_iter_noncert | 2818.310000000056 | False |
| integrated_paper_like_exact_i20_k2_a1b1 | max_iter_noncert | 3747.1099999961443 | max_iter_noncert | 3747.1099999961443 | False |
| integrated_paper_like_exact_i40_k2_a1b1 | exact_zero | 4.656612873077393e-10 | exact_zero | 4.656612873077393e-10 | False |
| disaster_only_paper_like_exact_i5_k1_a1b1 | max_iter_noncert | 46818.8099999954 | max_iter_noncert | 46818.8099999954 | False |
| disaster_only_paper_like_exact_i20_k1_a1b1 | max_iter_noncert | 21273.049999997485 | max_iter_noncert | 21273.049999997485 | False |
| disaster_only_paper_like_exact_i40_k1_a1b1 | exact_zero | 1.280568540096283e-09 | exact_zero | 1.280568540096283e-09 | False |
| disaster_only_paper_like_exact_i5_k2_a1b1 | max_iter_noncert | 71546.45000003651 | max_iter_noncert | 71546.45000003651 | False |
| disaster_only_paper_like_exact_i20_k2_a1b1 | max_iter_noncert | 35891.95999998739 | max_iter_noncert | 35891.95999998739 | False |
| disaster_only_paper_like_exact_i40_k2_a1b1 | max_iter_noncert | 7636.459999999031 | max_iter_noncert | 7636.459999999031 | False |
| integrated_runtime12_exact_i3_k3_a1234b1234 | max_iter_noncert | 12863.407500000903 | max_iter_noncert | 12863.407500000903 | False |

## Repeated-outage findings
- `integrated_paper_like_exact_i20_k2_a1b1__baseline`: repeated_outage_count=`1`
- `integrated_paper_like_exact_i20_k2_a1b1__improved`: repeated_outage_count=`1`
- `integrated_paper_like_exact_i40_k2_a1b1__baseline`: repeated_outage_count=`3`
- `integrated_paper_like_exact_i40_k2_a1b1__improved`: repeated_outage_count=`3`
- `disaster_only_paper_like_exact_i20_k1_a1b1__baseline`: repeated_outage_count=`2`
- `disaster_only_paper_like_exact_i20_k1_a1b1__improved`: repeated_outage_count=`2`
- `disaster_only_paper_like_exact_i40_k1_a1b1__baseline`: repeated_outage_count=`4`
- `disaster_only_paper_like_exact_i40_k1_a1b1__improved`: repeated_outage_count=`4`
- `disaster_only_paper_like_exact_i20_k2_a1b1__baseline`: repeated_outage_count=`1`
- `disaster_only_paper_like_exact_i20_k2_a1b1__improved`: repeated_outage_count=`1`
- `disaster_only_paper_like_exact_i40_k2_a1b1__baseline`: repeated_outage_count=`2`
- `disaster_only_paper_like_exact_i40_k2_a1b1__improved`: repeated_outage_count=`2`

## Repeated-cut findings
- none

## Lower-bound / cut-count behavior
- `integrated_paper_like_exact_i10_k2_a1b1__baseline`: lower_bound_gain=`1003.0779996309429`, generated_cut_count=`9`, dominant_cause=`other evidenced cause`
- `integrated_paper_like_exact_i10_k2_a1b1__improved`: lower_bound_gain=`1003.0779996309429`, generated_cut_count=`9`, dominant_cause=`other evidenced cause`
- `integrated_paper_like_exact_i20_k2_a1b1__baseline`: lower_bound_gain=`1173.5826972350478`, generated_cut_count=`19`, dominant_cause=`repeated outages`
- `integrated_paper_like_exact_i20_k2_a1b1__improved`: lower_bound_gain=`1173.5826972350478`, generated_cut_count=`19`, dominant_cause=`repeated outages`
- `integrated_paper_like_exact_i40_k2_a1b1__baseline`: lower_bound_gain=`1146.0782674960792`, generated_cut_count=`22`, dominant_cause=`repeated outages`
- `integrated_paper_like_exact_i40_k2_a1b1__improved`: lower_bound_gain=`1146.0782674960792`, generated_cut_count=`22`, dominant_cause=`repeated outages`
- `disaster_only_paper_like_exact_i5_k1_a1b1__baseline`: lower_bound_gain=`29087.07384291861`, generated_cut_count=`4`, dominant_cause=`other evidenced cause`
- `disaster_only_paper_like_exact_i5_k1_a1b1__improved`: lower_bound_gain=`29087.07384291861`, generated_cut_count=`4`, dominant_cause=`other evidenced cause`
- `disaster_only_paper_like_exact_i20_k1_a1b1__baseline`: lower_bound_gain=`48296.08952088406`, generated_cut_count=`19`, dominant_cause=`repeated outages`
- `disaster_only_paper_like_exact_i20_k1_a1b1__improved`: lower_bound_gain=`48296.08952088406`, generated_cut_count=`19`, dominant_cause=`repeated outages`
- `disaster_only_paper_like_exact_i40_k1_a1b1__baseline`: lower_bound_gain=`48593.66117353786`, generated_cut_count=`24`, dominant_cause=`repeated outages`
- `disaster_only_paper_like_exact_i40_k1_a1b1__improved`: lower_bound_gain=`48593.66117353786`, generated_cut_count=`24`, dominant_cause=`repeated outages`
- `disaster_only_paper_like_exact_i5_k2_a1b1__baseline`: lower_bound_gain=`26823.693279902243`, generated_cut_count=`4`, dominant_cause=`other evidenced cause`
- `disaster_only_paper_like_exact_i5_k2_a1b1__improved`: lower_bound_gain=`26823.693279902243`, generated_cut_count=`4`, dominant_cause=`other evidenced cause`
- `disaster_only_paper_like_exact_i20_k2_a1b1__baseline`: lower_bound_gain=`44130.916698912304`, generated_cut_count=`19`, dominant_cause=`repeated outages`
- `disaster_only_paper_like_exact_i20_k2_a1b1__improved`: lower_bound_gain=`44130.916698912304`, generated_cut_count=`19`, dominant_cause=`repeated outages`
- `disaster_only_paper_like_exact_i40_k2_a1b1__baseline`: lower_bound_gain=`55144.17175855965`, generated_cut_count=`39`, dominant_cause=`repeated outages`
- `disaster_only_paper_like_exact_i40_k2_a1b1__improved`: lower_bound_gain=`55144.17175855965`, generated_cut_count=`39`, dominant_cause=`repeated outages`
- `integrated_runtime12_exact_i3_k3_a1234b1234__baseline`: lower_bound_gain=`146.58931542560458`, generated_cut_count=`2`, dominant_cause=`other evidenced cause`
- `integrated_runtime12_exact_i3_k3_a1234b1234__improved`: lower_bound_gain=`146.58931542560458`, generated_cut_count=`2`, dominant_cause=`other evidenced cause`

## Alpha/Lambda-only cut evidence
- `disaster_only_paper_like_exact_i5_k1_a1b1__baseline`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`3`
- `disaster_only_paper_like_exact_i5_k1_a1b1__improved`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`3`
- `disaster_only_paper_like_exact_i20_k1_a1b1__baseline`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`18`
- `disaster_only_paper_like_exact_i20_k1_a1b1__improved`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`18`
- `disaster_only_paper_like_exact_i40_k1_a1b1__baseline`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`23`
- `disaster_only_paper_like_exact_i40_k1_a1b1__improved`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`23`
- `disaster_only_paper_like_exact_i5_k2_a1b1__baseline`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`3`
- `disaster_only_paper_like_exact_i5_k2_a1b1__improved`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`3`
- `disaster_only_paper_like_exact_i20_k2_a1b1__baseline`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`18`
- `disaster_only_paper_like_exact_i20_k2_a1b1__improved`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`18`
- `disaster_only_paper_like_exact_i40_k2_a1b1__baseline`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`38`
- `disaster_only_paper_like_exact_i40_k2_a1b1__improved`: alpha_lambda_only_cut_count=`1`, plan_change_cut_count=`38`

## Failure / non-certification rows
| comparison_group | variant | run_id | diagnosis_label | stop_reason | final_violation_upper_bound | dominant_cause | message |
| --- | --- | --- | --- | --- | --- | --- | --- |
| integrated_paper_like_exact_i10_k2_a1b1 | baseline | integrated_paper_like_exact_i10_k2_a1b1__baseline | max_iter_noncert | max_iterations | 2818.310000000056 | other evidenced cause | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; plan-changing cuts=9/9; alpha/lambda-only cuts=0/9; lower-bound gain=1003.078 |
| integrated_paper_like_exact_i10_k2_a1b1 | improved | integrated_paper_like_exact_i10_k2_a1b1__improved | max_iter_noncert | max_iterations | 2818.310000000056 | other evidenced cause | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; plan-changing cuts=9/9; alpha/lambda-only cuts=0/9; lower-bound gain=1003.078 |
| integrated_paper_like_exact_i20_k2_a1b1 | baseline | integrated_paper_like_exact_i20_k2_a1b1__baseline | max_iter_noncert | max_iterations | 3747.1099999961443 | repeated outages | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; repeated outages=1; plan-changing cuts=19/19; alpha/lambda-only cuts=0/19; lower-bound gain=1173.583 |
| integrated_paper_like_exact_i20_k2_a1b1 | improved | integrated_paper_like_exact_i20_k2_a1b1__improved | max_iter_noncert | max_iterations | 3747.1099999961443 | repeated outages | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; repeated outages=1; plan-changing cuts=19/19; alpha/lambda-only cuts=0/19; lower-bound gain=1173.583 |
| disaster_only_paper_like_exact_i5_k1_a1b1 | baseline | disaster_only_paper_like_exact_i5_k1_a1b1__baseline | max_iter_noncert | max_iterations | 46818.8099999954 | other evidenced cause | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; plan-changing cuts=3/4; alpha/lambda-only cuts=1/4; lower-bound gain=29087.074 |
| disaster_only_paper_like_exact_i5_k1_a1b1 | improved | disaster_only_paper_like_exact_i5_k1_a1b1__improved | max_iter_noncert | max_iterations | 46818.8099999954 | other evidenced cause | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; plan-changing cuts=3/4; alpha/lambda-only cuts=1/4; lower-bound gain=29087.074 |
| disaster_only_paper_like_exact_i20_k1_a1b1 | baseline | disaster_only_paper_like_exact_i20_k1_a1b1__baseline | max_iter_noncert | max_iterations | 21273.049999997485 | repeated outages | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; repeated outages=2; plan-changing cuts=18/19; alpha/lambda-only cuts=1/19; lower-bound gain=48296.090 |
| disaster_only_paper_like_exact_i20_k1_a1b1 | improved | disaster_only_paper_like_exact_i20_k1_a1b1__improved | max_iter_noncert | max_iterations | 21273.049999997485 | repeated outages | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; repeated outages=2; plan-changing cuts=18/19; alpha/lambda-only cuts=1/19; lower-bound gain=48296.090 |
| disaster_only_paper_like_exact_i5_k2_a1b1 | baseline | disaster_only_paper_like_exact_i5_k2_a1b1__baseline | max_iter_noncert | max_iterations | 71546.45000003651 | other evidenced cause | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; plan-changing cuts=3/4; alpha/lambda-only cuts=1/4; lower-bound gain=26823.693 |
| disaster_only_paper_like_exact_i5_k2_a1b1 | improved | disaster_only_paper_like_exact_i5_k2_a1b1__improved | max_iter_noncert | max_iterations | 71546.45000003651 | other evidenced cause | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; plan-changing cuts=3/4; alpha/lambda-only cuts=1/4; lower-bound gain=26823.693 |
| disaster_only_paper_like_exact_i20_k2_a1b1 | baseline | disaster_only_paper_like_exact_i20_k2_a1b1__baseline | max_iter_noncert | max_iterations | 35891.95999998739 | repeated outages | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; repeated outages=1; plan-changing cuts=18/19; alpha/lambda-only cuts=1/19; lower-bound gain=44130.917 |
| disaster_only_paper_like_exact_i20_k2_a1b1 | improved | disaster_only_paper_like_exact_i20_k2_a1b1__improved | max_iter_noncert | max_iterations | 35891.95999998739 | repeated outages | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; repeated outages=1; plan-changing cuts=18/19; alpha/lambda-only cuts=1/19; lower-bound gain=44130.917 |
| disaster_only_paper_like_exact_i40_k2_a1b1 | baseline | disaster_only_paper_like_exact_i40_k2_a1b1__baseline | max_iter_noncert | max_iterations | 7636.459999999031 | repeated outages | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; repeated outages=2; plan-changing cuts=38/39; alpha/lambda-only cuts=1/39; lower-bound gain=55144.172 |
| disaster_only_paper_like_exact_i40_k2_a1b1 | improved | disaster_only_paper_like_exact_i40_k2_a1b1__improved | max_iter_noncert | max_iterations | 7636.459999999031 | repeated outages | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; repeated outages=2; plan-changing cuts=38/39; alpha/lambda-only cuts=1/39; lower-bound gain=55144.172 |
| integrated_runtime12_exact_i3_k3_a1234b1234 | baseline | integrated_runtime12_exact_i3_k3_a1234b1234__baseline | max_iter_noncert | max_iterations | 12863.407500000903 | other evidenced cause | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; plan-changing cuts=2/2; alpha/lambda-only cuts=0/2; lower-bound gain=146.589 |
| integrated_runtime12_exact_i3_k3_a1234b1234 | improved | integrated_runtime12_exact_i3_k3_a1234b1234__improved | max_iter_noncert | max_iterations | 12863.407500000903 | other evidenced cause | stop_reason=max_iterations; diagnosis=max_iter_noncert; non-certified run remains smoke_only; plan-changing cuts=2/2; alpha/lambda-only cuts=0/2; lower-bound gain=146.589 |

## Cut diagnostics sample
| run_id | cut_id | repeated_outage_flag | repeated_cut_signature_flag | old_master_violation_at_source | post_cut_objective_change | first_stage_plan_changed | alpha_lambda_only_change | cut_addition_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| integrated_paper_like_exact_i10_k2_a1b1__baseline | generated_cut_001 | False | False | 16575.030000000144 | 271.7509497497231 | True | False | added |
| integrated_paper_like_exact_i10_k2_a1b1__baseline | generated_cut_002 | False | False | 13818.64000000013 | 51.8442450594157 | True | False | added |
| integrated_paper_like_exact_i10_k2_a1b1__baseline | generated_cut_003 | False | False | 15098.5 | 166.0360380988568 | True | False | added |
| integrated_paper_like_exact_i10_k2_a1b1__baseline | generated_cut_004 | False | False | 19454.900000000023 | 178.09203523769975 | True | False | added |
| integrated_paper_like_exact_i10_k2_a1b1__baseline | generated_cut_005 | False | False | 6363.820000000065 | 194.28060147725046 | True | False | added |
| integrated_paper_like_exact_i10_k2_a1b1__baseline | generated_cut_006 | False | False | 7545.65000000014 | 20.449003817513585 | True | False | added |
| integrated_paper_like_exact_i10_k2_a1b1__baseline | generated_cut_007 | False | False | 6363.799999998882 | 13.964125517755747 | True | False | added |
| integrated_paper_like_exact_i10_k2_a1b1__baseline | generated_cut_008 | False | False | 5810.820000000182 | 9.891990043222904 | True | False | added |
| integrated_paper_like_exact_i10_k2_a1b1__baseline | generated_cut_009 | False | False | 5076.080000000191 | 96.76901062950492 | True | False | added |
| integrated_paper_like_exact_i10_k2_a1b1__improved | generated_cut_001 | False | False | 16575.030000000144 | 271.7509497497231 | True | False | added |

## Figures
- `results/cut_process_diagnostics/figures/cut_process_violation_summary.png`
- `results/cut_process_diagnostics/figures/cut_process_effect_breakdown.png`
- `results/cut_process_diagnostics/figures/cut_process_baseline_vs_improved.png`
- `results/cut_process_diagnostics/figures/cut_process_repeat_flags.png`

## Iteration logs
- `results/cut_process_diagnostics/logs/integrated_paper_like_exact_i10_k2_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/integrated_paper_like_exact_i10_k2_a1b1__improved_iteration_log.json`
- `results/cut_process_diagnostics/logs/integrated_paper_like_exact_i20_k2_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/integrated_paper_like_exact_i20_k2_a1b1__improved_iteration_log.json`
- `results/cut_process_diagnostics/logs/integrated_paper_like_exact_i40_k2_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/integrated_paper_like_exact_i40_k2_a1b1__improved_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i5_k1_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i5_k1_a1b1__improved_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i20_k1_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i20_k1_a1b1__improved_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i40_k1_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i40_k1_a1b1__improved_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i5_k2_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i5_k2_a1b1__improved_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i20_k2_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i20_k2_a1b1__improved_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i40_k2_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i40_k2_a1b1__improved_iteration_log.json`
- `results/cut_process_diagnostics/logs/integrated_runtime12_exact_i3_k3_a1234b1234__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/integrated_runtime12_exact_i3_k3_a1234b1234__improved_iteration_log.json`

## Master LP dumps
- `results/cut_process_diagnostics/lp/integrated_runtime12_exact_i3_k3_a1234b1234__baseline_master_before.lp`
- `results/cut_process_diagnostics/lp/integrated_runtime12_exact_i3_k3_a1234b1234__baseline_master_after.lp`
- `results/cut_process_diagnostics/lp/integrated_runtime12_exact_i3_k3_a1234b1234__improved_master_before.lp`
- `results/cut_process_diagnostics/lp/integrated_runtime12_exact_i3_k3_a1234b1234__improved_master_after.lp`
