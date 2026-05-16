# Story Rubric

## Endpoint Structure

Good optimization experiment stories usually have interpretable endpoints:

- The integrated/proposed method balances competing objectives.
- The single-objective baseline performs well on its own objective but poorly
  on the missing objective.
- The robustness/risk endpoint improves risk but pays a visible efficiency or
  service-quality cost.
- The deterministic/mean-value benchmark looks reasonable on average but is
  weaker under the common worst-case or stress evaluator.

## Solution Quality

Flag a candidate for review when:

- most decisions hit upper or lower bounds without a physical reason;
- the proposed method is nearly identical to a benchmark while the text claims
  novelty;
- the robust method is sparser or less capable than a deterministic benchmark
  while claiming better robustness, unless this has a clear mechanism;
- unmet demand, violation, or slack terms dominate the story unexpectedly;
- topology/capacity allocation cannot be explained from data or model logic.

## Thresholds

Fixed thresholds are warnings, not substitutes for judgment. A candidate that
misses a nominal percentage by a small margin may still be paper-ready if the
mechanism is clear, the benchmark is fair, and the prose does not overclaim.
Conversely, a candidate can pass numeric thresholds and still fail if topology
or component decomposition is not credible.
