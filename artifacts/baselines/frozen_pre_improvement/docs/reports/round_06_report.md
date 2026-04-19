# Round 06 Report

## Files changed
- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/audit/residual_report.py`
- `tests/unit/test_first_stage_coeffs.py`
- `tests/unit/test_normal_block_coeffs.py`
- `tests/oracle/test_first_stage_normal_toy_cases.py`
- `tests/integration/test_first_stage_normal_runtime_fixture.py`
- `tests/fixtures/first_stage_t1_zero_demand.yaml`
- `tests/fixtures/first_stage_t2_minimum_three.yaml`
- `tests/fixtures/normal_block_t3_fast_slow.yaml`
- `tests/fixtures/normal_block_t4_distance_preference.yaml`
- `tests/fixtures/normal_block_t5_network_bottleneck.yaml`
- `docs/reports/round_06_report.md`

## Design decisions
- Implemented the production first-stage block directly on the canonical bus ordering `instance.sets.buses`.
- Exposed deterministic production views through:
  - `z_by_bus`
  - `n_sl_by_bus`
  - `n_fa_by_bus`
- Implemented unmet charging demand with aggregated variables by `(t, region, charger_type)`:
  - `u_sl[t,o]`
  - `u_fa[t,o]`
- Treated EV charging as active-power-only in the normal active-balance equations.
- Read `Ctrans[t]` and `Cpur[t]` strictly from canonical time vectors.
- Used `annualize_normal_cost_by_365` exactly as carried by the canonical economic contract.
- Numerical tolerance for hand-check and residual assertions in this round: `1e-8`.
- No use of `ambig.w` appears in the first-stage or normal block.

## Equation coverage
- Eq. (10): annualized construction cost in `build_first_stage_model`
- Eq. (11): minimum total-charger activation row
- Eq. (12): slow/fast installation upper bounds linked to `z`
- Eq. (13): normal-stage objective decomposition
- Eq. (14): transportation cost term
- Eq. (15): unmet-demand penalty term
- Eq. (16): substation purchase-cost term
- Eq. (17): aggregated demand-assignment balances
- Eq. (18): station-capacity limits by charger type
- Eq. (19): assignment-siting linkage rows
- Eq. (20): active-power radial balance
- Eq. (21): reactive-power radial balance
- Eq. (22): active substation definition
- Eq. (23): active/reactive line upper and lower bounds
- Eq. (24): voltage-drop equations
- Eq. (25): voltage lower/upper bounds
- Additional implementation anchor:
  - `root_voltage_fix_t` enforces the frozen root squared-voltage reference

## Coefficient/model-shape checks
- First-stage unit checks directly inspect:
  - Eq. (10) objective coefficients on `z`, `n_sl`, `n_fa`
  - root-bus `z` upper bound fixed to `0`
  - Eq. (11) row coefficients `(+1, +1, -3)`
  - Eq. (12) slow/fast upper-bound coefficients `(+1, -Nbar)`
- Normal-block unit checks directly inspect:
  - Eq. (17) assignment and unmet coefficients/signs
  - Eq. (18) capacity-row coefficient on `n_sl`
  - Eq. (19) linkage coefficient on `z`
  - Eq. (20) active-balance sign pattern on current line, child line, and local charging
  - Eq. (21) reactive-balance sign pattern
  - Eq. (22) substation-definition sign pattern
  - Eq. (23) presence of all active/reactive upper/lower rows
  - Eq. (24) voltage-drop row coefficients/signs
  - Eq. (25) voltage-bound row presence and senses

## Toy-case objective checks
- T1 zero-demand sanity:
  - result: no construction, no assignment, no unmet, no substation purchase
  - objective: `0.0`
- T2 minimum-3-charger activation:
  - hand expectation: 20 kW slow demand would physically fit in two 10 kW slow chargers, so Eq. (11) must force a third charger once the site opens
  - result: `z_2 = 1`, `n_sl_2 = 3`, `n_fa_2 = 0`
  - objective: `35.0`
- T3 fast/slow separation sanity:
  - result: `n_sl_2 = 2`, `n_fa_2 = 1`
  - served slow/fast: `10.0 / 50.0`
  - objective: `6.0`
- T4 distance-preference transportation case:
  - hand expectation: bus 2 is nearer and capped at 30 kW slow, so it should fill first and bus 3 should cover the remaining 20 kW
  - result: bus 2 served `30.0`, bus 3 served `20.0`
  - first stage: `z_2 = z_3 = 1`, `n_sl_2 = n_sl_3 = 3`
  - objective: `13.0`
- T5 network bottleneck case:
  - hand expectation: site capacity is 150 kW slow, but the feeder line caps deliverable service at 50 kW
  - result: served `50.0`, unmet `100.0`
  - objective: `1003.0`
- T1-T5 all passed.

## Tests run
- `pytest tests/unit/test_first_stage_coeffs.py -q`
  - Result: `2 passed in 0.04s`
- `pytest tests/unit/test_normal_block_coeffs.py -q`
  - Result: `2 passed in 0.04s`
- `pytest tests/oracle/test_first_stage_normal_toy_cases.py -q`
  - Result: `5 passed in 0.05s`
- `pytest tests/integration/test_first_stage_normal_runtime_fixture.py -q`
  - Result: `1 passed in 0.48s`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
  - Result: `5 passed in 0.08s`
- `pytest tests/oracle/test_separation_exactness.py -q`
  - Result: `5 passed in 0.08s`
- `pytest -q`
  - Result: `110 passed in 6.68s`

## Audit artifacts
- Stable LP dump paths:
  - first-stage toy build: `/tmp/round_06_first_stage_toy.lp`
  - runtime first-stage + normal block: `/tmp/round_06_runtime_first_stage_normal.lp`
- Runtime smoke residual summary:
  - total objective: `27296770.304400675`
  - construction cost: `4421143.360491286`
  - normal-block cost: `22875626.94390937`
  - max charge-balance residual: `2.8421709430404007e-13`
  - max active-power residual: `3.3591618375794496e-10`
  - max reactive-power residual: `1.9895196601282805e-13`
  - max voltage-bound violation: `0.0`
  - max line-limit violation: `0.0`
- Notable first-stage solutions:
  - T2:
    - `z = {2: 1}`
    - `n_sl = {2: 3}`
    - `n_fa = {}`
  - Runtime smoke:
    - opened buses: `{3, 4, 5, 6, 9, 17, 18, 19, 20, 22, 23, 25, 26, 27, 28, 29, 32, 33}`
    - positive slow-install buses: all opened buses at `20` slow chargers each
    - positive fast-install buses:
      - bus `3`: `1`
      - bus `5`: `3`
      - bus `19`: `10`
      - bus `20`: `6`
      - bus `22`: `3`
      - bus `28`: `3`

## Known limitations
- This round solves only one fixed sampled normal scenario at a time; it does not build the later master-level normal expectation.
- The normal block does not include any disaster, cut, master, or Benders logic.
- The runtime voltage-drop coefficients required an explicit `kW/kvar -> MW/Mvar` conversion inside Eq. (24) because the canonical contract provides powers in `kW/kvar` while `R/X` arrives as per-unit feeder data without an explicit base-power field.
- `FirstStageSolution.objective_value` reflects the active model objective of the attached model; downstream master/cut rounds should rely on `construction_cost_value` when they need the pure first-stage block value.

## Open issues for next round
- Round 07 can now integrate the Round 06 production blocks into the later master/cut flow without rebuilding feeder or ordering logic.
- If a later round formalizes an explicit power-base field in the canonical contract, replace the Eq. (24) literal `1/1000` conversion with that metadata.
- When master/Benders integration arrives, keep using the stable bus ordering from `instance.sets.buses` so first-stage vectors remain aligned with future cut coefficients.
- Preserve the new runtime smoke test and coefficient tests; they now guard the unit-sensitive Eq. (24) behavior that the toy cases alone would not have caught.
