# Round 05 Report

## Files changed
- `src/reference/outage_enumerator.py`
- `src/reference/dro_outer_lp_oracle.py`
- `src/production/separation_milp.py`
- `tests/oracle/test_budget_support_fn.py`
- `tests/oracle/test_dro_outer_lp.py`
- `tests/oracle/test_separation_exactness.py`
- `tests/integration/test_separation_runtime_fixture.py`
- `tests/fixtures/separation_generic_exactness.yaml`
- `tests/fixtures/separation_phi_only_line_limit.yaml`
- `tests/fixtures/separation_mixed_reconstruction.yaml`
- `tests/fixtures/separation_activation_budget2.yaml`
- `docs/reports/round_05_report.md`

## Design decisions
- Implemented the Round 05 layer as three auditable pieces:
  - exact outage-enumeration support oracles for tiny cases
  - a tiny finite outer-DRO LP oracle over enumerated outage states
  - the fixed-`(x, alpha, lambda)` separation MILP for Eq. (41)
- Kept the Round 02 disaster primal mathematics unchanged.
- Kept the separation layer active-power-only and built it from the Round 04 paper-dual group structure rather than from copied closed-form outage scores.
- Preserved the disaster readiness gate:
  - `critical_buses` is still required for disaster-objective-ready builds
  - `critical_buses` is never inferred from `ambig.w`
- Used explicit `omega_bounds_by_line_id` as an input contract to the separation MILP.
  - tiny exactness tests use bounds derived from independent outage re-solves
  - the runtime smoke test uses conservative single-line bounds with a safety factor
  - this keeps the production separation builder auditable without embedding extra oracle logic inside the MILP builder
- Numerical exactness tolerance used in the tiny comparisons: `1e-8`.
- No narrow bug fix in any permitted Round 02-04 file was required by the new exactness tests.

## Oracle design
- Budget-support oracle
  - `enumerate_outages(...)` enumerates `Omega(K)` in stable canonical line order.
  - `solve_budget_support_by_enumeration(...)` computes the exact support-function value
    `max_{delta in Omega(K)} v^T delta`.
  - `solve_budget_support_top_k(...)` provides the equivalent top-positive-`K` validation path.
- Separation exactness oracle
  - `solve_separation_violation_by_enumeration(...)` re-solves the fixed-sample paper dual for every enumerated outage pattern, averages the sample values, subtracts `lambda^T delta` and `alpha`, and returns the exact best pattern on tiny cases.
  - The oracle also exposes samplewise decompositions and average linewise `phi` coefficients by pattern.
- Outer-DRO LP oracle
  - `solve_dro_outer_lp_oracle(...)` solves the finite LP over enumerated outage probabilities `p`.
  - Constraints enforced:
    - `sum p = 1`
    - `sum p * delta <= FP`
  - Tiny hand-checkable validation case:
    - objective `7.0`
    - worst-case probabilities:
      - `p(delta_10) = 0.5`
      - `p(delta_01) = 0.25`
      - `p(delta_00) = 0.25`

## Separation MILP design
- `build_separation_milp(...)` builds the fixed-point Eq. (41) MILP for fixed:
  - first-stage plan `x`
  - scalar `alpha`
  - linewise ambiguity multipliers `lambda`
  - selected disaster samples
- Each disaster sample contributes a grouped paper-dual block with variables:
  - `eta`, `mu`, `nu`, `sigma`, `rho_upper`, `rho_lower`, plus free Eq. (27) balance duals
- The model enforces:
  - binary outage vector `delta`
  - outage budget `sum delta <= K`
  - samplewise paper-dual feasibility
  - `omega_l = (1 / |B|) sum_b phi_l^b`
  - McCormick linearization for `tau_l = delta_l * omega_l`
- The solved result exposes:
  - violation value
  - `delta_star`
  - `omega` and `tau`
  - samplewise grouped dual solutions
  - samplewise `beta_b / gamma_b / phi_b` decomposition
  - objective reconstruction diagnostics

## Exactness comparisons
- Generic tiny exactness case
  - oracle objective: `20.0`
  - separation MILP objective: `20.0`
  - oracle outage: `{"line_01_02": 1}`
  - MILP outage: `{"line_01_02": 1}`
  - absolute gap: `0.0`
- `phi-only` / line-limit-dominated exactness case
  - oracle objective: `15.0`
  - separation MILP objective: `15.0`
  - oracle outage: `{"line_01_02": 1, "line_02_03": 0}`
  - MILP outage: `{"line_01_02": 1, "line_02_03": 0}`
  - absolute gap: `0.0`
- Mixed slow/fast reconstruction case
  - separation MILP objective: `5.0`
  - chosen outage: `{"line_01_02": 1}`
  - reconstruction gap: `0.0`
  - active groups on the solved sample: `mu`, `nu`, `rho_upper`
- Dual-group activation coverage check
  - required union passed:
    - `eta`
    - `mu`
    - `nu`
    - `sigma`
    - `rho_upper`
    - `rho_lower`
- Required strengthening checks
  - `phi-only` exactness check: passed
  - dual-group activation coverage: passed
  - blockwise decomposition reconstruction: passed

## Tests run
- `pytest tests/oracle/test_budget_support_fn.py -q`
  - Result: `2 passed in 0.03s`
- `pytest tests/oracle/test_dro_outer_lp.py -q`
  - Result: `1 passed in 0.05s`
- `pytest tests/oracle/test_separation_exactness.py -q`
  - Result: `5 passed in 0.08s`
- `pytest tests/integration/test_separation_runtime_fixture.py -q`
  - Result: `1 passed in 1.16s`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
  - Result: `5 passed in 0.09s`
- `pytest -q`
  - Result: `88 passed in 5.35s`

## Audit artifacts
- Separation MILP LP dump path(s)
  - `/tmp/round_05_runtime_fixture_separation.lp`
- Outer-DRO LP oracle dump path(s)
  - `/tmp/round_05_tiny_outer_dro_oracle.lp`
- Runtime-fixture separation smoke summary
  - violation objective: `77520.30999995698`
  - chosen outage vector:
    - `line_01_02 = 1`
    - `line_08_09 = 1`
    - all other lines `= 0`
  - `tau` support objective: `16000000.0`
  - budget-support oracle objective on solved `omega - lambda`: `16000000.0`
  - top-`K` support objective on solved `omega - lambda`: `16000000.0`
  - reconstruction gap: `2.491287887096405e-08`
  - largest solved `omega` values:
    - `line_01_02 = 8000000.0`
    - `line_08_09 = 8000000.0`
- Tiny outer-DRO LP summary
  - objective: `7.0`
  - line marginals:
    - `line_1 = 0.5`
    - `line_2 = 0.25`

## Known limitations
- The current separation MILP depends on caller-supplied `omega` bounds rather than deriving Eq. (40) bounds internally.
- Tiny exactness is established on enumeration-scale fixtures only.
- The runtime fixture test is explicitly a smoke/integration check, not a proof that the current runtime-bound construction is globally tight.
- No cut generation, master problem, or Benders loop logic exists yet.

## Open issues for next round
- Round 06 should use the exposed samplewise `beta_b / gamma_b / phi_b` pieces to build actual separation cuts without re-solving the reference oracle stack unnecessarily.
- If later rounds need stronger runtime exactness guarantees, replace the current conservative `omega`-bound supply path with a paper-faithful bound construction that remains bounded and auditable.
- Once master-variable ordering exists, bind the current blockwise `gamma_b` exposure to that production ordering for cut assembly.
