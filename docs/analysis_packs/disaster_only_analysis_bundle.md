# Disaster-Only Analysis Bundle

## Purpose
This note packages the current evidence behind the question:

> Why does `disaster_only_paper_like` open only one EVCS site, and should that be interpreted as a real modeling conclusion, an artifact of the benchmark definition, or a bounded-solve artifact?

This bundle is designed to be forwarded to a stronger external model for independent review.

## Executive Takeaway
- The current `disaster_only_paper_like` run opens exactly **one** site:
  - `bus 10 -> 25 slow / 10 fast`
- This is **not obviously a bug**.
- Structurally, it is plausible because `disaster_only` removes the daily-service reward that drives wide station deployment in `normal_only` and `integrated`.
- However, the specific one-site result is **not yet strong evidence of the final intended disaster-only policy**, because the current baseline run is only:
  - `validation_level = smoke_only`
  - `stop_reason = max_iterations`
  - `final_violation_upper_bound = 71546.45`
- Longer-budget diagnostics show that the same disaster-only family can continue improving substantially, so the current one-site solution should be read as a **bounded directional result**, not a fully settled conclusion.

## Main Evidence

### 1. Current Paper-Like Comparison
Source files:
- `results/summary.csv`
- `results/plans/disaster_only_paper_like_plan.csv`
- `results/plans/normal_only_paper_like_plan.csv`
- `results/plans/integrated_mainline_paper_like_plan.csv`

| Run | Validation | Stop Reason | Construction | Weighted Normal | Disaster Master | Opened Sites | Slow | Fast |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `integrated_mainline_paper_like` | `epsilon_certified` | `certified_epsilon` | `171730.1363` | `13035357.5922` | `0.0` | `15` | `361` | `24` |
| `normal_only_paper_like` | `exact` | `direct_optimal` | `171760.0644` | `18622035.2641` | `0.0` | `15` | `362` | `24` |
| `disaster_only_paper_like` | `smoke_only` | `max_iterations` | `23113.8248` | `0.0` | `3709.8685` | `1` | `25` | `10` |

### 2. Current Opened-Site Plans
Source files:
- `results/plans/disaster_only_paper_like_plan.csv`
- `results/plans/normal_only_paper_like_plan.csv`
- `results/plans/integrated_mainline_paper_like_plan.csv`

#### `disaster_only_paper_like`
- `(10, 25, 10)`

#### `normal_only_paper_like`
- `(3, 25, 6)`
- `(4, 25, 0)`
- `(5, 25, 3)`
- `(6, 25, 0)`
- `(9, 25, 0)`
- `(18, 25, 0)`
- `(19, 25, 10)`
- `(20, 25, 0)`
- `(25, 24, 1)`
- `(26, 25, 0)`
- `(27, 25, 0)`
- `(28, 25, 4)`
- `(29, 25, 0)`
- `(32, 25, 0)`
- `(33, 13, 0)`

#### `integrated_mainline_paper_like`
- `(3, 25, 6)`
- `(4, 25, 0)`
- `(5, 25, 3)`
- `(6, 25, 0)`
- `(9, 25, 0)`
- `(18, 25, 0)`
- `(19, 25, 10)`
- `(20, 25, 1)`
- `(25, 21, 0)`
- `(26, 25, 0)`
- `(27, 25, 0)`
- `(28, 25, 4)`
- `(29, 25, 0)`
- `(32, 25, 0)`
- `(33, 15, 0)`

### 3. Disaster-Only Longer-Budget Diagnostics
Source file:
- `results/cut_process_diagnostics/summary.csv`

These rows matter because they show the same disaster-only family can keep improving under larger iteration budgets.

| Run | K | Max Iters | Validation | Stop Reason | Total Objective | Construction | Disaster Master | Final Violation |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| `disaster_only_paper_like_exact_i5_k1_a1b1__baseline` | `1` | `5` | `smoke_only` | `max_iterations` | `29087.0738` | `23113.8248` | `5973.2490` | `46818.8100` |
| `disaster_only_paper_like_exact_i20_k1_a1b1__baseline` | `1` | `20` | `smoke_only` | `max_iterations` | `48296.0895` | `24061.5237` | `24234.5658` | `21273.0500` |
| `disaster_only_paper_like_exact_i40_k1_a1b1__baseline` | `1` | `40` | `exact` | `certified_exact` | `48593.6612` | `25446.9066` | `23146.7546` | `1.28e-09` |
| `disaster_only_paper_like_exact_i20_k2_a1b1__baseline` | `2` | `20` | `smoke_only` | `max_iterations` | `44130.9167` | `26832.2894` | `17298.6273` | `35891.9600` |
| `disaster_only_paper_like_exact_i40_k2_a1b1__baseline` | `2` | `40` | `smoke_only` | `max_iterations` | `55144.1718` | `26832.2894` | `28311.8823` | `7636.4600` |

## Why the One-Site Outcome Is Structurally Plausible

### A. `disaster_only` removes the daily-service benefit
In the paper-like family:
- `normal_only` and `integrated` are rewarded for serving ongoing charging demand.
- `disaster_only` has:
  - `weighted_normal_term = 0.0`
  - no day-to-day coverage reward

So under `disaster_only`, opening a second site is not justified by normal-operation service quality. The model must recover the extra station cost using only disaster-side value.

### B. The current one-site solution is a full-capacity hub
The current plan is not “one tiny station.” It is:
- `bus 10 -> 25 slow / 10 fast`

That means the model is not saying “do almost nothing.” It is saying:
- first choose one location that appears most valuable for resilience
- then saturate that location’s available EVSE capacity

### C. The fixed-cost hurdle for a second site is real
Source files:
- `configs/experiments/paper_like_tableII_family.yaml`
- `src/production/first_stage.py`

The benchmark uses:
- `cfix = 153600`
- `ccons_sl = 540.07`
- `ccons_fa = 25000`
- `gamma = 0.01`
- `theta = 20`
- `nbar_sl = 25`
- `nbar_fa = 10`

Using the existing annualization logic, the approximate annualized first-stage unit costs are:
- station fixed cost: `~8511.79`
- one slow charger: `~29.93`
- one fast charger: `~1385.38`

So a second site must clear a nontrivial fixed-cost threshold before it is worthwhile in `disaster_only`.

### D. `bus 10` is not an arbitrary fringe point
In the IEEE-33 layout used here, `bus 10` sits on the main feeder spine in a relatively central location. For a disaster-only objective that is trying to hedge resilience value with minimal first-stage spend, a centered hub is economically plausible.

## Why the Current One-Site Result Should Not Be Overclaimed

### A. The headline baseline run is only `smoke_only`
The current `disaster_only_paper_like` row has:
- `validation_level = smoke_only`
- `stop_reason = max_iterations`
- `final_violation_upper_bound = 71546.45`

So this is a bounded run, not a certified final answer.

### B. Longer-budget diagnostics keep moving
The longer-budget exact-mode diagnostics show:
- at `K = 1`, objective climbs from about `29087` to about `48594`
- at `K = 2`, objective is still moving materially even by iteration budget `40`

That means:
- the disaster-only landscape is not “done” at the 5-iteration budget used in the Round 12 baseline pack
- any spatial conclusion drawn from the one-site baseline should be explicitly qualified

### C. The benchmark itself is local and paper-like, not paper-identical
This repo is using:
- local `runtime_12` data
- plus paper-like scalar overrides

It is **not** using the paper authors’ original full input instance. So even if the optimization were exact, the disaster-only policy would still be a local paper-like result, not a paper-number reproduction.

## Strong vs Weak Conclusions

### Stronger conclusions
- It is economically plausible that `disaster_only` is much sparser than `normal_only` and `integrated`.
- It is plausible that a disaster-only benchmark would favor a hub-like stationing pattern rather than broad spatial coverage.
- The current one-site solution is not by itself evidence of a code bug.

### Weaker conclusions
- It is **not yet strong evidence** that the final intended disaster-only policy under this family should truly be one site.
- It is **not yet strong evidence** that `bus 10` is the uniquely correct resilience hub.
- It is **not yet strong evidence** that the paper-like disaster case should look this sparse under a fully converged and paper-comparable setup.

## Most Likely Explanations, Ranked
1. **Benchmark definition effect**
   - `disaster_only` removes normal-operation reward, so sparse siting is expected.
2. **Bounded Benders effect**
   - the current baseline run uses `max_iterations = 5`, and longer-budget diagnostics show continued improvement.
3. **Local-instance effect**
   - this is built on `runtime_12`, not the paper’s full original instance.
4. **Possible hidden modeling issue**
   - currently not the leading explanation; no clear evidence yet points to a bug.

## What an External Reviewer Should Check First
1. Whether the single-site hub is a structural consequence of the disaster-only objective.
2. Whether the low-budget `max_iterations = 5` run is producing an artificially sparse early-stage plan.
3. Whether the network geometry and outage support make `bus 10` a natural resilience hub.
4. Whether the disaster-only benchmark is missing some service-quality mechanism that the paper implicitly preserved.
5. Whether the paper-like benchmark should be compared to the paper’s disaster case at all, given the local `runtime_12` base.

## Files to Forward

### Minimal set
- `configs/experiments/paper_like_tableII_family.yaml`
- `results/summary.csv`
- `results/plans/disaster_only_paper_like_plan.csv`
- `results/plans/normal_only_paper_like_plan.csv`
- `results/plans/integrated_mainline_paper_like_plan.csv`
- `docs/analysis_packs/paper_style_experiment_pack.md`
- `results/figures/fig6_like_plan_maps.png`
- `docs/reports/round_12_report.md`

### Stronger set
- `results/cut_process_diagnostics/summary.csv`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i40_k1_a1b1__baseline_iteration_log.json`
- `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i20_k2_a1b1__baseline_iteration_log.json`
- `docs/reports/round_13_report.md`
- `results/paper_like_calibration_refined/capacity_probe.csv`

## Suggested Prompt for External Review
```md
Please analyze why `disaster_only_paper_like` currently opens only one EVCS site, and whether that is a structural consequence of the benchmark or a likely artifact of the current bounded Benders solve.

Context:
- This repo uses local `runtime_12` data plus a paper-like parameter override layer. It is not a full reproduction of the paper’s original instance.
- The current `disaster_only_paper_like` run is:
  - `validation_level = smoke_only`
  - `stop_reason = max_iterations`
  - `final_violation_upper_bound = 71546.45`
- The resulting plan opens only one site:
  - `bus 10 -> 25 slow / 10 fast`
- Its objective breakdown is:
  - `construction_cost = 23113.82`
  - `weighted_normal_term = 0.0`
  - `disaster_master_term = 3709.87`

Important comparison runs:
- `normal_only_paper_like` is exact and opens 15 sites.
- `integrated_mainline_paper_like` is epsilon-certified and also opens 15 sites.
- In longer-budget disaster-only exact diagnostics, the same benchmark continues improving substantially:
  - `K=1, i5`: smoke_only, objective ~29087
  - `K=1, i20`: smoke_only, objective ~48296
  - `K=1, i40`: exact, objective ~48594
  - `K=2, i40`: still non-certified, objective ~55144

What I want you to assess:
1. Is the one-site disaster-only solution structurally plausible under this objective?
2. How much of it is likely due to the benchmark definition itself versus the bounded `max_iterations=5` solve?
3. Is `bus 10` as a single hub consistent with the network geometry / outage logic?
4. Does the evidence suggest a bug, or does it look economically consistent?
5. If we want a more paper-like disaster-resilience case, what should be investigated first:
   - local demand structure
   - outage support structure
   - benchmark definition
   - Benders iteration budget / cut process
   - something else

Please be explicit about which conclusions are strong and which are weak because of `smoke_only` status.
```

## Recommended Interpretation Discipline
- Do **not** describe the current one-site result as a validated final disaster-only optimum.
- It is fair to describe it as:
  - a bounded paper-like local result
  - directionally sparse
  - economically plausible
  - not yet strong enough to settle the final disaster-only siting pattern
