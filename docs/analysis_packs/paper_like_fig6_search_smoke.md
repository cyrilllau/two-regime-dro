# Paper-Like Fig. 6 Search Log

## Objective
- Search exact `normal_only` configurations that move the local `runtime_12` result closer to the paper Fig. 6 Case 1 semantics.
- Record the search process instead of only keeping the final recommendation.

## Target Semantics
- target site count = 7
- target total slow chargers = 74
- target total fast chargers = 13
- target buses = `3, 5, 10, 22, 28, 32, 33`

## Phase 1 Search
| run_id | scale | nbar_sl | ccons_fa | opened | slow | fast | overlap | missing | extra | capped | score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| phase1_scale0p46_nsl25_fa12000 | 0.46 | 25 | 12000.0 | 7 | 167 | 11 | 2 | 5 | 5 | 5 | 309.0 |
| phase1_scale0p5_nsl25_fa12000 | 0.5 | 25 | 12000.0 | 8 | 181 | 12 | 3 | 4 | 5 | 6 | 332.0 |

## Phase 2 Search
| run_id | scale | nbar_sl | ccons_fa | opened | slow | fast | overlap | missing | extra | capped | score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| phase2_scale0p46_nsl25_fa6000 | 0.46 | 25 | 6000.0 | 7 | 167 | 11 | 2 | 5 | 5 | 5 | 309.0 |
| phase2_scale0p46_nsl25_fa12000 | 0.46 | 25 | 12000.0 | 7 | 167 | 11 | 2 | 5 | 5 | 5 | 309.0 |
| phase2_scale0p5_nsl25_fa12000 | 0.5 | 25 | 12000.0 | 8 | 181 | 12 | 3 | 4 | 5 | 6 | 332.0 |
| phase2_scale0p5_nsl25_fa6000 | 0.5 | 25 | 6000.0 | 8 | 181 | 12 | 2 | 5 | 6 | 6 | 372.0 |

## Selected Best-Fit Parameter Set
- run_id = `phase1_scale0p46_nsl25_fa12000`
- `ev_penetration_scale = 0.46`
- `nbar_sl = 25`
- `ccons_fa = 12000.0`
- opened buses / slow / fast = `7 / 167 / 11`
- exact bus overlap count = `2`
- missing target buses = `5,10,22,32,33`
- extra buses = `9,18,19,26,27`
- capped slow station count = `5`
- opened-site list = `3:25/0; 9:25/0; 18:22/0; 19:25/8; 26:20/0; 27:25/0; 28:25/3`

## Why The Changes Make Sense
- Lower `ev_penetration_scale` is the only lever that consistently reduced both site count and total slow chargers in the exact anchor.
- Reducing `nbar_sl` is the lever that prevents a few stations from absorbing all slow capacity and helps keep the site count in the paper-like range.
- `ccons_fa` matters much less than demand scale; in the best candidates it mainly nudges station mix after the demand scale already fixed the overall site count.
- The search confirms that the earlier `25/0` pattern was not a plotting artifact; it was a real optimizer response under larger local demand and higher per-site slow-cap.

## Limitations
- This is still local `runtime_12` calibration, not paper-data reproduction.
- The best-fit result is judged against paper-like geometry/scale, not against the paper's hidden raw tensors.

## Figure
- ``
