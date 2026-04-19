# Round 07 Report

## Files changed
- `src/production/master_problem.py`
- `src/audit/residual_report.py`
- `tests/unit/test_master_problem_coeffs.py`
- `tests/oracle/test_master_problem_toy_cases.py`
- `tests/integration/test_master_problem_runtime_fixture.py`
- `tests/fixtures/master_problem_trivial_zero_demand.yaml`
- `tests/fixtures/master_problem_normal_averaging.yaml`
- `tests/fixtures/master_problem_gamma_incentive.yaml`
- `tests/fixtures/master_problem_phi_support.yaml`
- `docs/reports/round_07_report.md`

## Design decisions
- Implemented only the fixed-cut production restricted master problem for Eq. (33), Eq. (37)–(39).
- Reused the validated Round 06 production blocks directly:
  - `build_first_stage_model(...)`
  - `build_normal_operation_block(...)`
- Kept all first-stage bus ordering exactly `instance.sets.buses`.
- Kept all line ordering exactly `instance.sets.line_ids`.
- Introduced a structured production-side cut representation:
  - `beta`
  - `gamma_z_by_bus`
  - `gamma_n_sl_by_bus`
  - `gamma_n_fa_by_bus`
  - `phi_by_line_id`
- Kept the cut family structured and auditable; no flattened opaque first-stage vector was introduced.
- If no cuts are supplied, the builder now inserts one explicit `trivial_cut`.
- Kept the normal expectation explicit across all selected normal scenarios:
  - no pre-aggregated normal-cost constants
  - no raw CSV/JSON reads in the production model layer
- Numerical tolerance used for coefficient/residual checks in this round: `1e-8`, with `1e-7` accepted for the runtime objective reconstruction gap due to floating-point accumulation on the larger LP.
- No narrow bug fix in `src/production/first_stage.py` or `src/production/normal_block.py` was required.

## Equation coverage
- Eq. (33): restricted master objective
  - `F_cons(x)`
  - `((1 - pi_f) / A) * sum_a F_nor^a(x, y^a)`
  - `pi_f * (alpha + lambda^T FP)`
- Eq. (37)–(38): master disaster variables
  - scalar `alpha`
  - linewise `lambda_l >= 0`
- Eq. (39): one fixed cut row plus linewise support-link rows per cut
  - support row: `alpha >= beta - gamma^T x + K s + sum_l u_l`
  - linewise row: `u_l >= phi_l - lambda_l - s`

## RMP structure
- First-stage ordering convention:
  - `z_by_bus`, `n_sl_by_bus`, and `n_fa_by_bus` all follow `instance.sets.buses` exactly.
- Cut representation:
  - each cut is carried as one `RestrictedMasterCut`
  - `gamma` is split by first-stage block:
    - `gamma_z_by_bus`
    - `gamma_n_sl_by_bus`
    - `gamma_n_fa_by_bus`
  - `phi` is carried linewise as `phi_by_line_id`
- Normal-scenario averaging convention:
  - the builder attaches one explicit normal block per selected normal scenario
  - if `A = len(instance.sets.loaded_normal_scenarios)`, each normal block enters with weight `((1 - pi_f) / A)`
  - the weighted normal term is exposed separately from the unweighted average scenario cost in the solved summary
- Alpha/lambda sign conventions:
  - `alpha` enters the objective with coefficient `+pi_f`
  - `lambda_l` enters the objective with coefficient `+pi_f * FP_l`
  - Eq. (39) support rows are implemented as `>=` rows
  - in the support row:
    - coefficient on `alpha` is `+1`
    - coefficients on first-stage variables are `+gamma`
    - coefficient on `s_r` is `-K`
    - coefficient on each `u_{r,l}` is `-1`
  - in the linewise `u`-link row:
    - coefficient on `u_{r,l}` is `+1`
    - coefficient on `lambda_l` is `+1`
    - coefficient on `s_r` is `+1`
    - RHS is `phi_{r,l}`

## Coefficient / model-shape checks
- Added direct unit checks that verify:
  - coefficient on `alpha` is `pi_f`
  - coefficient on each `lambda_l` is `pi_f * FP_l`
  - normal-block charging/unmet coefficients are scaled by `((1 - pi_f) / A)`
- Added direct Eq. (39) row checks that verify:
  - one cut-support row exists per cut
  - one `u`-link row exists per cut-line pair
  - support-row sign pattern on `alpha`, `gamma`, `s`, and `u`
  - `u`-link sign pattern on `u`, `lambda`, and `s`
  - correct linewise `phi` RHS

## Toy-case checks
- Trivial-cut zero-demand sanity:
  - no normal demand
  - no construction
  - `alpha = 0`
  - `lambda = 0`
  - total objective `0.0`
- Normal-expectation averaging sanity:
  - two selected normal scenarios with normal costs `2.0` and `4.0`
  - unweighted scenario average `3.0`
  - weighted master normal term `1.5`
  - first-stage construction cost `0.04`
  - total objective `1.54`
- Gamma-driven siting incentive cut:
  - synthetic cut `alpha >= 100 - 100 z_2 + s + u`
  - opening the site forces the usual three-charger minimum
  - optimal solution: `z_2 = 1`, `n_sl_2 = 3`, `n_fa_2 = 0`
  - `alpha = 0`
  - total objective `35.0`
- Phi/lambda support sanity:
  - one-line cut with `phi = 10`, `K = 1`, `FP = 0.2`
  - optimal solution: `lambda_line_01_02 = 10`, `alpha = 0`
  - total objective `2.0`

## Runtime smoke summary
- Runtime fixture:
  - canonical instance loaded from `data/runtime_12`
  - selected normal scenarios: `(1, 2)`
  - cut family: trivial cut only
- Solved RMP objective summary:
  - total objective: `24916711.48002533`
  - construction cost: `4410273.923833655`
  - weighted normal term: `20506437.556191698`
  - unweighted average normal cost: `22784930.617990773`
  - scenario normal costs:
    - scenario `1`: `22889668.17424082`
    - scenario `2`: `22680193.061740726`
  - disaster master term: `0.0`
  - `alpha = 0.0`
  - `lambda^T FP = 0.0`
  - objective reconstruction gap: `2.2351741790771484e-08`
- Runtime cut residual summary:
  - max cut-support violation: `0.0`
  - max `u`-link violation: `0.0`
- Runtime first-stage summary:
  - opened buses:
    - `{3, 4, 5, 6, 9, 17, 18, 19, 20, 22, 23, 25, 26, 27, 28, 29, 32, 33}`
  - positive slow-install buses:
    - all opened buses at `20` slow chargers each
  - positive fast-install buses:
    - bus `3`: `2`
    - bus `5`: `4`
    - bus `19`: `10`
    - bus `20`: `5`
    - bus `22`: `1`
    - bus `28`: `2`
- Runtime normal-block residuals:
  - all selected normal blocks remained feasible under the reused Round 06 checks
  - for each selected scenario:
    - max charge-balance residual <= `1e-8`
    - max active-power residual <= `1e-8`
    - max reactive-power residual <= `1e-8`
    - max voltage-drop residual <= `1e-8`
    - max voltage-bound violation <= `1e-8`
    - max line-limit violation <= `1e-8`
- Raw-read guard:
  - the runtime integration test patches `builtins.open`
  - any attempted `data/runtime_12/*` file read during production build/solve would fail
  - the RMP build/solve passed under that guard

## Tests run
- `pytest tests/unit/test_master_problem_coeffs.py -q`
  - Result: `2 passed in 0.06s`
- `pytest tests/oracle/test_master_problem_toy_cases.py -q`
  - Result: `4 passed in 0.06s`
- `pytest tests/integration/test_master_problem_runtime_fixture.py -q`
  - Result: `1 passed in 1.65s`
- `pytest tests/unit/test_first_stage_coeffs.py -q`
  - Result: `2 passed in 0.04s`
- `pytest tests/unit/test_normal_block_coeffs.py -q`
  - Result: `2 passed in 0.04s`
- `pytest tests/integration/test_first_stage_normal_runtime_fixture.py -q`
  - Result: `1 passed in 0.49s`
- `pytest tests/oracle/test_separation_exactness.py -q`
  - Result: `5 passed in 0.10s`
- `pytest -q`
  - Result: `123 passed in 9.34s`

## Audit artifacts
- Stable LP dump paths:
  - toy RMP: `/tmp/round_07_toy_master.lp`
  - runtime RMP: `/tmp/round_07_runtime_master.lp`

## Known limitations
- This round builds only the fixed-cut restricted master problem; it does not generate cuts or run Benders iterations.
- The cut family is externally supplied; there is still no production cut-construction path.
- The runtime smoke uses the trivial cut only, so it validates master assembly and averaging discipline rather than disaster-bound tightness.

## Open issues for next round
- Round 08 can now attach a cut-generation driver or Benders loop without changing the stable first-stage or line ordering exposed here.
- When real cuts are produced, keep using the structured `beta/gamma/phi` representation rather than flattening the first-stage vector.
- Preserve the new raw-read guard and the objective/coefficient checks; they now protect the RMP boundary and averaging contract directly.
