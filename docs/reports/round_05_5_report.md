# Round 05.5 Report

## Files changed
- `src/production/separation_milp.py`
- `tests/unit/test_separation_coeffs.py`
- `tests/oracle/test_budget_support_edge_cases.py`
- `tests/oracle/test_separation_edge_cases.py`
- `tests/integration/test_separation_runtime_bounds.py`
- `docs/reports/round_05_5_report.md`

## Validation goals
- Add direct coefficient/model-shape checks for the existing separation MILP.
- Add budget-support and separation edge cases that were not covered in Round 05.
- Harden the runtime-smoke path with explicit omega-bound validation and slack diagnostics.
- Preserve the Round 02-05 math and production-scope boundaries.

## Design decisions
- Kept this round validation-only: no new planning logic, no cut generation, no master problem, and no Benders logic.
- Kept the Round 02 disaster primal mathematics unchanged.
- Kept the separation MILP formulation unchanged; the only implementation extension was to expose solved `omega` lower/upper slack diagnostics directly in `SeparationMilpSolution`.
- Used existing toy fixtures and helpers rather than adding new fixture files, to stay within the narrow Round 05.5 scope.
- Numerical tolerance used for exactness-style checks in this round: `1e-8`.
- No localized math bug fix was required.

## Coefficient/model-shape checks
- Added direct unit checks that:
  - every `delta_l` variable is binary
  - there is exactly one outage-budget row named `outage_budget`
  - each line has explicit `omega_l` and `tau_l` variables
  - each line has exactly four McCormick constraints:
    - `tau_lower_prod_l`
    - `tau_upper_prod_l`
    - `tau_mccormick_lb_l`
    - `tau_mccormick_ub_l`
- Added direct objective-coefficient checks for the fixed-`(x, alpha, lambda)` sign pattern:
  - Eq. (27) `lambda` rows contribute positive `beta` coefficients
  - Eq. (29) `mu` terms contribute negative `gamma^T x` coefficients
  - Eq. (30) `nu` terms contribute negative `gamma^T x` coefficients
  - Eq. (31) `sigma` terms contribute negative `beta` coefficients
  - Eq. (32) `rho` terms contribute negative base coefficients
  - `tau_l` objective coefficient is `+1`
  - `delta_l` objective coefficient is `-lambda_l`
  - objective constant is `-alpha`
- Added direct omega-definition row checks showing the expected sign propagation:
  - coefficient of `omega_l` is `+1`
  - coefficients of samplewise `rho_upper` / `rho_lower` terms for the same line are `-Pmax/B`

## Edge-case checks
- Budget-support edge cases added:
  - `K = 0` returns value `0` with the all-zero outage vector
  - `K = |L|` returns the sum of positive score components
  - all-nonpositive score vectors return value `0`
  - tie case validated by objective value without requiring a unique outage identity
- Separation edge cases added:
  - `K = 0` separation case matches zero-outage enumeration exactly
  - tie-optimum separation case accepts any best outage pattern while matching the best value
  - exact tiny bounds vs inflated valid bounds produce the same optimal violation value on a tiny case
- Sign/block regression checks added under the new harness:
  - `phi`-dominant regression re-checks that the outage-dependent part is `tau - lambda^T delta`
  - mixed slow/fast case re-checks `beta/gamma/phi` blockwise reconstruction

## Runtime-bound checks
- Added runtime integration validation that:
  - solved `omega_l` values stay inside the supplied conservative bounds
  - bound slacks are exposed directly as:
    - `omega_lower_slack_by_line_id`
    - `omega_upper_slack_by_line_id`
    - `max_omega_bound_violation`
- Runtime validation result:
  - max omega bound violation: `0.0`
  - outage chosen in the inspected runtime solve:
    - `line_01_02 = 1`
    - `line_08_09 = 1`
  - lines exactly at the supplied upper bound:
    - `line_01_02`
    - `line_08_09`
  - tightest upper-bound slacks:
    - `line_01_02 = 0.0`
    - `line_08_09 = 0.0`
    - `line_02_19 = 1600000.0`
    - `line_03_23 = 1600000.0`
    - `line_06_26 = 1600000.0`
- No exactness claim is made here beyond the tested facts:
  - the supplied runtime-smoke bounds are valid for the solved point
  - the solution respects them
  - this round does not prove those bounds are globally tight

## Tests run
- `pytest tests/unit/test_separation_coeffs.py -q`
  - Result: `2 passed in 0.08s`
- `pytest tests/oracle/test_budget_support_edge_cases.py -q`
  - Result: `4 passed in 0.04s`
- `pytest tests/oracle/test_separation_edge_cases.py -q`
  - Result: `5 passed in 0.11s`
- `pytest tests/oracle/test_separation_exactness.py -q`
  - Result: `5 passed in 0.07s`
- `pytest tests/integration/test_separation_runtime_bounds.py -q`
  - Result: `1 passed in 1.14s`
- `pytest tests/integration/test_separation_runtime_fixture.py -q`
  - Result: `1 passed in 1.15s`
- `pytest -q`
  - Result: `100 passed in 6.62s`

## Audit artifacts
- Stable separation LP dump path(s)
  - `/tmp/round_05_5_runtime_fixture_separation.lp`
- Runtime-bound slack summary
  - objective value: `77520.30999995698`
  - max omega bound violation: `0.0`
  - reconstruction gap: `2.491287887096405e-08`
  - `delta_star`:
    - `line_01_02 = 1`
    - `line_08_09 = 1`
  - omega upper-bound active lines:
    - `line_01_02`
    - `line_08_09`
- Tie-case notes
  - the `failed_line` tie-optimum separation case has multiple best outage patterns
  - the hardening check validates objective agreement and membership in the best-pattern set, not a unique selected identity

## Known limitations
- This round validates the existing separation layer more deeply, but it still does not derive Eq. (40) runtime bounds internally.
- Runtime-bound checks are validity checks, not a proof that the supplied runtime-smoke bounds are exact.
- The new diagnostics focus on `omega` bounds; they do not add a broader production diagnostic/reporting framework.

## Open issues for next round
- Round 06 can proceed with higher confidence on the separation surface, but later rounds should still preserve the new coefficient and edge-case tests when integrating cuts.
- If a future round introduces internally computed runtime `omega` bounds, add the same slack diagnostics and direct coefficient tests to that new bound-construction path.
- Once cut generation exists, reuse the current `beta/gamma/phi` and runtime-bound diagnostics to audit cut assembly rather than creating a separate inconsistent reporting path.
