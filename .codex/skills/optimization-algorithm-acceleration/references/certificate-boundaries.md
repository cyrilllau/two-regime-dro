# Certificate Boundaries

## Ordinary Epsilon Certificate

Use when the canonical master solution is separated over the full support and
the final violation is below tolerance:

`max_s { Q_s(x) - H_s(rho) } <= epsilon`.

Report final violation, iteration count, cuts, master/separation status, and
runtime decomposition.

## Pricing-UB / Canonical-LB Certificate

Use only if a theorem or Pro-reviewed proof establishes that:

- the lower bound is from the canonical restricted master, not an auxiliary
  stabilized objective;
- the upper bound is a valid full-support pricing-derived upper bound for the
  same problem;
- `UB - LB <= epsilon` under the accepted objective scale;
- all support, data hash, K, and cut metadata match.

Label this separately in tables, e.g., `pricing_ub_gap_certified`.

## Not A Certificate

- heuristic incumbent with low observed violation on a restricted support;
- active-set separation without full-support audit;
- stabilized/local-branch objective value;
- non-optimal separation MIP gap reported as if exact;
- cut pool inherited from a different support, data source, or benchmark mode.
