# Paper-Like Fig. 6 Refined Exact Sweep

## Scope
- This is a second-layer exact `normal_only` sweep.
- It uses the promising combined lever set:
  - `cfix = 614400`
  - `ccons_sl = 2700.35`
  - `ccons_fa = 12000`
  - `ctrans_scalar = 0.032625`
- Only `ev_penetration_scale` is varied here.
- This remains local `runtime_12` calibration, not paper-number reproduction.

## Refined Exact Candidates
| run_id | ev_penetration_scale | opened_bus_count | total_slow_chargers | total_fast_chargers | fast_station_count | capped_slow_station_count | opened_bus_list |
| --- | --- | --- | --- | --- | --- | --- | --- |
| normal_only_paper_like_refined_scale_055 | 0.55 | 8 | 199 | 13 | 3 | 7 | 3:25/0; 4:24/0; 9:25/0; 18:25/1; 19:25/9; 27:25/0; 28:25/3; 32:25/0 |
| normal_only_paper_like_refined_scale_050 | 0.5 | 8 | 181 | 12 | 3 | 6 | 3:25/0; 4:17/0; 9:25/1; 18:25/0; 19:25/8; 27:25/0; 28:25/3; 32:14/0 |
| normal_only_paper_like_refined_scale_045 | 0.45 | 7 | 163 | 11 | 3 | 5 | 3:25/1; 4:17/0; 9:25/0; 18:21/0; 19:25/7; 27:25/0; 28:25/3 |

## Best-Fit Candidate
- Selected best-fit candidate: `normal_only_paper_like_refined_scale_045`
- Reason: it is the closest exact `normal_only` match to the paper Fig. 6 Case 1 siting count/layout target.
- Opened buses / slow / fast: `7 / 163 / 11`
- Opened-site list: `3:25/1; 4:17/0; 9:25/0; 18:21/0; 19:25/7; 27:25/0; 28:25/3`

## Interpretation
- `0.55` is the first scale that enters the paper-like `6-8` station range.
- `0.50` keeps `8` stations while reducing total slow chargers further.
- `0.45` reaches `7` stations, which is the closest exact anchor to the paper Case 1 station count.
- None of these runs fully resolve the remaining `25/0` saturation pattern, so the next structural lever would have to address station-level capacity usage rather than only overall demand intensity.

## Capacity-Relief Sanity Probes
- I also checked whether the remaining `25/0` saturation was mainly caused by `nbar_sl = 25`.
- Result: increasing `nbar_sl` made the solution *more* concentrated rather than more paper-like.
  - `nbar_sl = 35`, `scale = 0.45` -> `5` sites, still dominated by slow-heavy stations.
  - `nbar_sl = 40`, `scale = 0.45` -> `4` sites, even more concentrated.
- Changing `nbar_fa` from `10` to `15` or `20` did not change the exact `normal_only` plan in the focused probes.
- Lowering `ctrans_scalar` again also did not undo that concentration once `nbar_sl` was raised.
- Probe table: `results/paper_like_calibration_refined/capacity_probe.csv`

## Practical Takeaway
- The most effective lever so far is still demand normalization on top of the refined cost mix.
- The best exact anchor for paper-like station count is currently:
  - `normal_only_paper_like_refined_scale_045`
- The next useful calibration round should not start by raising `nbar_sl`; that moves the solution away from the paper-like siting count.

## Figure
- `results/paper_like_calibration_refined/figures/refined_exact_comparison.png`
