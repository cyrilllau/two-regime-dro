# Paper-Like Fig. 6 Tuning Journal

## Goal
- Move the local `runtime_12` exact `normal_only` anchor toward the paper Fig. 6 Case 1 semantics.
- Keep the validated optimization math unchanged.
- Record the tuning process instead of keeping only one final parameter recommendation.

## Step 0: Baseline Observation
Baseline exact anchor:
- `normal_only_paper_like`
- `15` opened buses
- `362` slow chargers
- `24` fast chargers

This was much denser than the paper Fig. 6 Case 1 layout and repeatedly produced many `25/0` stations.

Reference:
- `results/plans/normal_only_paper_like_plan.csv`
- `results/summary.csv`

## Step 1: Cost-Only Sweep
I ran the fixed sequence `S0`-`S6` cost-only candidates and recorded them in:
- `results/paper_like_calibration/summary.csv`
- `docs/analysis_packs/paper_like_fig6_calibration_pack.md`

Observed result:
- `S0`-`S6` all stayed at roughly `15` opened buses and `361-362` slow chargers.
- Increasing `cfix`, lowering `ctrans_scalar`, increasing `ccons_sl`, and lowering `ccons_fa` at those magnitudes did **not** materially change the exact `normal_only` layout.

Interpretation:
- The local `runtime_12` demand environment was still dominating the siting outcome.
- The cost-only lever set was too weak to push the exact anchor into the paper-like station-count range.

## Step 2: Demand-Normalization Sweep On Top Of The Refined Cost Mix
I then kept the refined cost mix:
- `cfix = 614400`
- `ccons_sl = 2700.35`
- `ccons_fa = 12000`
- `ctrans_scalar = 0.032625`

and varied only `ev_penetration_scale`.

Recorded in:
- `results/paper_like_calibration_refined/summary.csv`
- `docs/analysis_packs/paper_like_fig6_refined_pack.md`

Exact results:

| run_id | scale | opened buses | slow | fast |
| --- | --- | --- | --- | --- |
| `normal_only_paper_like_refined_scale_055` | `0.55` | `8` | `199` | `13` |
| `normal_only_paper_like_refined_scale_050` | `0.50` | `8` | `181` | `12` |
| `normal_only_paper_like_refined_scale_045` | `0.45` | `7` | `163` | `11` |

Interpretation:
- This was the first lever that actually moved the exact anchor into the paper-like site-count range.
- `0.55` was the first scale entering the `6-8` station window.
- `0.45` was the closest exact anchor to the paper Case 1 station count.

## Step 3: Why The Solution Still Shows Many `25/0` Stations
The remaining question was whether `nbar_sl = 25` itself was the main culprit.

I recorded focused capacity-relief probes in:
- `results/paper_like_calibration_refined/capacity_probe.csv`

Key outcomes:
- Raising `nbar_sl` from `25` to `35` or `40` made the solution **more concentrated**, not more paper-like.
  - Example:
    - `scale = 0.45`, `nbar_sl = 35` -> `5` sites
    - `scale = 0.45`, `nbar_sl = 40` -> `4` sites
- Increasing `nbar_fa` did not materially change the exact `normal_only` plan.
- Lowering `ctrans_scalar` again did not undo the extra concentration once `nbar_sl` was raised.

Interpretation:
- The `25/0` pattern is not mainly caused by the upper bound being too low.
- Under the current local demand and economics, the optimizer still prefers slow-heavy stations.
- If `nbar_sl` is relaxed, the model concentrates even more slow capacity into fewer sites.

This is why the persistent `25/0` pattern should not currently be treated as evidence of a bug by itself.

## Parameter Recommendations
Recorded in:
- `results/paper_like_calibration_refined/recommended_parameter_sets.csv`

### Recommended tuned baseline
Use this when you want a reasonable paper-like calibration without pushing demand scaling too aggressively:

```yaml
economics:
  cfix: 614400.0
  ccons_sl: 2700.35
  ccons_fa: 12000.0
  ctrans_scalar: 0.032625
  gamma: 0.01
  theta: 20
  pi_f: 0.3

ev:
  p_ev_rated_sl: 7.0
  p_ev_rated_fa: 50.0
  nbar_sl: 25
  nbar_fa: 10

ev_penetration_scale: 0.50
```

Why:
- exact anchor stays at `8` sites
- total charger count is substantially reduced relative to the original baseline
- the scaling is less aggressive than `0.45`

### Recommended figure anchor
Use this when matching the paper Fig. 6 station-count impression matters most:

```yaml
economics:
  cfix: 614400.0
  ccons_sl: 2700.35
  ccons_fa: 12000.0
  ctrans_scalar: 0.032625
  gamma: 0.01
  theta: 20
  pi_f: 0.3

ev:
  p_ev_rated_sl: 7.0
  p_ev_rated_fa: 50.0
  nbar_sl: 25
  nbar_fa: 10

ev_penetration_scale: 0.45
```

Why:
- exact anchor lands at `7` sites
- this is the closest exact result so far to the paper Case 1 station count

## What Makes Sense And What Does Not
What now looks justified:
- adjusting demand intensity is the dominant useful calibration lever
- keeping the refined cost mix is better than going back to the original `paper_like` costs
- **not** raising `nbar_sl` first; it pushes the model away from the paper-like siting count

What is still unresolved:
- why the local best-fit exact anchors still prefer several `25/0` slow-heavy stations
- how to obtain more paper-like mixed station types without moving away from the validated local semantics too aggressively

## Next Practical Direction
The next useful calibration step should focus on diagnosis rather than more blind scalar sweeps:
- inspect slow vs fast demand composition in the selected `runtime_12` support
- inspect station-level utilization in the best-fit exact anchors
- then decide whether the remaining gap is mostly a demand-composition issue or a cost-ratio issue
