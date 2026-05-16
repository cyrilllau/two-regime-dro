---
name: optimization-calibration-search
description: Use when tuning an optimization model's experiment regime or objective-term multipliers to obtain interpretable, paper-facing results without changing the underlying physical parameters or hiding failed candidates; especially useful for default-case selection, benchmark story formation, topology/solution quality gates, and automated calibration loops.
metadata:
  short-description: Tune optimization experiments toward publishable stories
---

# Optimization Calibration Search

Use this skill when the model can run but the result story is weak: benchmark
ordering is wrong, the solution is extreme, a sensitivity trend is not
interpretable, or a paper default case needs retuning.

## Core Workflow

1. **Lock what cannot change.** Separate physical/data parameters from tunable
   experiment weights. Do not silently change units, datasets, scenario
   supports, or benchmark semantics to rescue a story.
2. **Define a story rubric before searching.** Express the expected mechanism
   qualitatively and quantitatively: endpoint behavior, compromise behavior,
   benchmark fairness, topology/solution quality, and certification.
3. **Search with stages.** Start with cheap screens, then common replay, then
   full certification only for short-listed candidates.
4. **Use a single global regime.** Do not tune each benchmark independently.
   One candidate regime must be used for all compared cases.
5. **Rank, do not stop at the first pass.** Choose the candidate that best
   supports the paper mechanism, not the first row that crosses a threshold.
6. **Record failures.** Failed regimes go to diagnostics with reason codes; do
   not delete or hide them, but do not let them pollute paper-facing tables.
7. **Promote only after audit.** A candidate can enter the manuscript only
   after identity checks, common evaluator checks, benchmark semantics checks,
   certificate checks, and critic review.

## Search Controls

- Use objective-term multipliers only when the user or paper design requires
  raw physical parameters to stay fixed.
- Use parameter ranges that are explainable, preferably normalized around a
  baseline.
- For costly MIP/Benders runs, use warm starts, cut reuse with metadata guards,
  timeout pruning, and staged certification.
- If all reasonable candidates fail the same story condition, switch to bug or
  model-semantics investigation instead of widening the search indefinitely.

## Story Rubric

For each candidate, judge:

- Does the proposed method form an interpretable compromise between endpoints?
- Is the normal-only or deterministic baseline visibly weaker on the risk metric
  under the same evaluator?
- Is the risk-only endpoint best or near-best on risk while sacrificing normal
  service or investment efficiency?
- Are first-stage decisions non-extreme and explainable?
- Are sensitivity trends monotone or at least mechanistically defensible?
- Is the certification strong enough for main-text claims?

Use `references/calibration-artifacts.md` for output files and
`references/story-rubric.md` for reviewer-facing criteria.
