# Round 03 Report

## Files changed
- `src/reference/lp_canonicalizer.py`
- `src/reference/disaster_dual_auto.py`
- `src/reference/kkt_checks.py`
- `src/audit/residual_report.py`
- `tests/oracle/test_disaster_primal_ref.py`
- `tests/oracle/test_disaster_primal_dual.py`
- `tests/integration/test_disaster_primal_dual_runtime_fixture.py`
- `tests/fixtures/disaster_primal_mixed_slow_fast.yaml`
- `docs/reports/round_03_report.md`

## Design decisions
- Kept the Round 02 disaster primal LP mathematics unchanged and treated it as the sole primal source of truth.
- Built canonicalization by mechanically reading the already-built Gurobi primal model:
  - objective coefficients from primal variables
  - row coefficients from primal constraints
  - row senses from the actual primal model
- Used a canonical sign convention of:
  - primal objective is minimization
  - canonical primal variables are nonnegative
  - canonical equality rows stay as equality rows
  - all inequality rows are converted to `>=`
- Used plus/minus splitting for free primal line-flow variables so the auto dual can be generated in a standard nonnegative-variable form.
- Built the auto dual only from the canonical LP representation; no hand-coded paper-dual coefficients were introduced.
- Implemented KKT checks directly on the canonical primal/dual pair:
  - primal feasibility
  - dual feasibility
  - strong duality
  - row complementarity
  - variable/reduced-cost complementarity
- Extended the residual audit so Eq. (27)–(32) now expose named residual/slack entries rather than only aggregate maxima.

## Canonicalization conventions
- Variable-sign convention
  - canonical primal form is `min c^T x`
  - canonical variables satisfy `x >= 0`
  - dual feasibility is enforced as `A_eq^T lambda + A_ge^T pi <= c`
- Free-variable handling
  - each free primal line-flow variable `p` is transformed to `p = p_pos - p_neg`
  - `p_pos >= 0`, `p_neg >= 0`
  - objective coefficients transform as `c_p * p = c_p * p_pos - c_p * p_neg`
- Primal-to-dual mapping note
  - primal equality rows receive free dual variables `lambda`
  - primal `>=` rows receive nonnegative dual variables `pi`
  - primal `<=` rows are multiplied by `-1` during canonicalization so they also become canonical `>=` rows before dual generation

## Tests run
- `pytest tests/oracle/test_disaster_primal_ref.py -q`
  - Result: `6 passed in 0.05s`
- `pytest tests/oracle/test_disaster_primal_dual.py -q`
  - Result: `6 passed in 0.06s`
- `pytest tests/integration/test_disaster_primal_runtime_fixture.py -q`
  - Result: `1 passed in 0.09s`
- `pytest tests/integration/test_disaster_primal_dual_runtime_fixture.py -q`
  - Result: `1 passed in 1.95s`
- `pytest -q`
  - Result: `70 passed in 2.31s`

## Objective comparisons
- `zero`
  - primal objective: `0.0`
  - auto-dual objective: `-0.0`
  - absolute gap: `0.0`
- `shortage`
  - primal objective: `70.0`
  - auto-dual objective: `70.0`
  - absolute gap: `0.0`
- `critical_priority`
  - primal objective: `30.0`
  - auto-dual objective: `30.0`
  - absolute gap: `0.0`
- `failed_line`
  - primal objective: `20.0`
  - auto-dual objective: `20.0`
  - absolute gap: `0.0`
- `mixed_slow_fast`
  - primal objective: `10.0`
  - auto-dual objective: `10.0`
  - absolute gap: `0.0`
- `runtime_fixture`
  - primal objective: `76273.74000000002`
  - auto-dual objective: `76273.74`
  - absolute gap: `1.4551915228366852e-11`

## KKT / residual summary
- Strongest residual checks performed
  - primal feasibility from named Eq. (27)–(32) audit entries plus canonical row checks
  - dual feasibility from dual-variable sign checks and canonical dual-constraint slack checks
  - strong duality by primal-vs-dual objective comparison
  - complementarity by:
    - `pi_i * primal_row_slack_i`
    - `x_j * reduced_cost_j`
- Worst observed values
  - runtime-fixture primal feasibility max violation: `0.0`
  - runtime-fixture dual feasibility max violation: `0.0`
  - runtime-fixture strong duality gap: `1.4551915228366852e-11`
  - runtime-fixture max row complementarity: `0.0`
  - runtime-fixture max variable complementarity: `0.0`
  - runtime-fixture max Eq. (27) residual: `0.0`
  - runtime-fixture max failed-line flow violation: `0.0`

## Audit artifacts
- primal LP dump path(s)
  - `/tmp/round_03_runtime_fixture_primal.lp`
- auto-dual LP dump path(s)
  - `/tmp/round_03_runtime_fixture_auto_dual.lp`

## Known limitations
- The canonicalizer currently supports only the variable-bound patterns that appear in the current disaster primal reference LP:
  - nonnegative variables
  - fully free variables
- No hand-coded paper dual was implemented in this round.
- No separation MILP, cut generation, master problem, or Benders logic was implemented in this round.
- The auto dual is tied to the current fixed-`(x, delta, b)` reference LP and is not yet aggregated across sampled disaster scenarios.
- The runtime-fixture audit still uses a test-only `critical_buses` override, as intended by the freeze contract.

## Open issues for next round
- Round 04 should implement the hand-coded paper dual and compare it against this auto dual on the same toy and runtime-fixture cases.
- If future primal models introduce additional bound types, the canonicalizer will need explicit bound shifting or extra-row support.
- The current residual audit exposes named primal equation-group entries; a later round may want similarly named dual-row diagnostics for even faster debugging.
