# Round 06.5 Report

## Files changed
- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/audit/residual_report.py`
- `tests/unit/test_normal_block_unit_semantics.py`
- `tests/unit/test_first_stage_objective_api.py`
- `tests/oracle/test_normal_block_voltage_drop_analytic.py`
- `tests/integration/test_normal_block_runtime_unit_guard.py`
- `tests/fixtures/normal_block_voltage_drop_analytic_2bus.yaml`
- `tests/fixtures/normal_block_unit_guard_runtime_assumption.yaml`
- `docs/reports/round_06_5_report.md`

## Validation goals
- Add direct validation that Eq. (24) uses the intended production scaling path.
- Make the current runtime unit assumption explicit and protected by regression checks.
- Guard the first-stage solution API so later rounds do not confuse the attached model objective with the pure construction-cost value.
- Preserve the Round 06 math and keep this round validation-only.

## Design decisions
- Kept the Round 06 first-stage and normal-block mathematics unchanged.
- Exposed the Eq. (24) unit assumption explicitly in `NormalOperationBlock`:
  - `eq24_power_base_kw = 1000.0`
  - `eq24_power_to_pu_scale = 0.001`
  - `eq24_unit_assumption = "R/X in per-unit, powers in kW/kvar, implicit S_base = 1 MVA"`
- Extended the normal residual report with:
  - `max_voltage_drop_residual`
  - `voltage_drop_residuals`
  - the explicit Eq. (24) scale/base metadata
- Added a first-stage API guard:
  - `FirstStageSolution.objective_is_pure_construction`
  - `objective_value` remains the attached-model objective
  - `construction_cost_value` remains the pure first-stage quantity to use downstream
- Numerical tolerance used for analytic and residual checks in this round: `1e-8`.
- No production layer file reads were added; the model layer still consumes only canonical objects.

## Eq. (24) unit / scaling checks
- Protected assumption:
  - feeder `Rline/Xline` are per-unit feeder coefficients
  - canonical active/reactive powers are in `kW/kvar`
  - Eq. (24) therefore uses an implicit `S_base = 1 MVA`
  - implemented conversion factor: `1 / 1000`
- Direct coefficient checks now verify:
  - coefficient on `v_to` is `+1`
  - coefficient on `v_from` is `-1`
  - coefficient on `p` is `2 R / 1000`
  - coefficient on `q` is `2 X / 1000`
  - row sense is equality
- Runtime guard confirms the current runtime fixture is feasible under this assumption and becomes infeasible if the scaling is removed.

## Hand-checkable analytic example
- Tiny case:
  - 2 buses, 1 line
  - `R = 0.01`, `X = 0.02`
  - `p = 100 kW`, `q = 50 kvar`
  - `v_from = 1.0`
- Hand calculation under the production conversion:
  - `p = 0.1 MW`
  - `q = 0.05 Mvar`
  - voltage drop `= 2 * 0.01 * 0.1 + 2 * 0.02 * 0.05 = 0.004`
  - expected `v_to = 1.0 - 0.004 = 0.996`
- Solver result on the analytic toy LP:
  - `p = 100.0`
  - `q = 50.0`
  - `v_from = 1.0`
  - `v_to = 0.996`
  - max Eq. (24) residual `= 3.469446951953614e-18`

## First-stage objective API checks
- Standalone first-stage solve:
  - forced-open regression confirms `objective_value == construction_cost_value`
  - `objective_is_pure_construction == True`
  - forced-open toy objective `= 35.0`
- Attached first-stage + normal-block solve:
  - `objective_value` matches the attached model objective
  - `construction_cost_value` remains the pure first-stage value
  - `objective_is_pure_construction == False`
  - attached toy case (`T4`) had:
    - `construction_cost_value = 6.0`
    - attached objective `= 13.0`

## Runtime unit guard
- Runtime smoke summary under the protected assumption:
  - total objective `= 27296770.304400675`
  - construction cost `= 4421143.360491286`
  - `objective_is_pure_construction = False`
  - max Eq. (24) residual `= 2.203098814490545e-16`
  - max voltage-bound violation `= 0.0`
  - max line-limit violation `= 0.0`
- No-raw-read guard:
  - the integration test loads the canonical instance first
  - then patches `builtins.open` to fail on any `data/runtime_12/*` read during production model build/solve
  - the production first-stage + normal-block build/solve passes under that guard
- Wrong-scale regression:
  - replacing `2R/1000`, `2X/1000` with `2R`, `2X` on the runtime model makes the model infeasible
  - observed Gurobi status: `3` (`INFEASIBLE`)

## Tests run
- `pytest tests/unit/test_normal_block_unit_semantics.py -q`
  - Result: `2 passed in 0.28s`
- `pytest tests/unit/test_first_stage_objective_api.py -q`
  - Result: `2 passed in 0.05s`
- `pytest tests/oracle/test_normal_block_voltage_drop_analytic.py -q`
  - Result: `1 passed in 0.07s`
- `pytest tests/integration/test_normal_block_runtime_unit_guard.py -q`
  - Result: `1 passed in 0.69s`
- `pytest tests/unit/test_normal_block_coeffs.py -q`
  - Result: `2 passed in 0.06s`
- `pytest tests/integration/test_first_stage_normal_runtime_fixture.py -q`
  - Result: `1 passed in 0.56s`
- `pytest -q`
  - Result: `116 passed in 7.77s`

## Audit artifacts
- Stable LP dump paths:
  - analytic tiny normal-block LP: `/tmp/round_06_5_voltage_drop_analytic.lp`
  - runtime first-stage + normal-block LP: `/tmp/round_06_5_runtime_first_stage_normal.lp`
- Scaling summary:
  - `eq24_power_base_kw = 1000.0`
  - `eq24_power_to_pu_scale = 0.001`
  - assumption in force:
    - `Eq. (24) uses feeder R/X in per-unit and power variables in kW/kvar, so the production row applies an implicit S_base = 1 MVA conversion.`

## Known limitations
- This round does not prove that `S_base = 1 MVA` is the only admissible future interpretation; it hardens the current implementation choice until the stable spec is explicitly reopened.
- The first-stage API guard is descriptive and regression-protected; it does not prevent callers from reading `objective_value`, it makes the distinction explicit and test-backed.
- No broader normal-model refactor was attempted in this round.

## Open issues for next round
- If a future round introduces an explicit network base-power field into the stable contract, replace the hard-coded `1000.0` Eq. (24) base with that canonical metadata.
- Later master/cut rounds should rely on `construction_cost_value` plus `objective_is_pure_construction`, not on `objective_value` alone, whenever a pure first-stage value is needed.
- Preserve the wrong-scale runtime infeasibility regression; it now guards the most unit-sensitive part of the Round 06 model layer.
- Keep the no-raw-read integration guard in place whenever the normal block is wrapped by later production layers.

## Narrow bug fix status
- No narrow bug fix in the Round 06.5 permission list was required.
- The only failing item during implementation was a new test harness assumption, which was corrected inside the new Round 06.5 test file without widening scope.
