# Round 07.5 Report

## Files changed
- `src/production/master_problem.py`
- `src/audit/residual_report.py`
- `tests/unit/test_master_problem_objective_api.py`
- `tests/oracle/test_master_problem_real_cut_interface.py`
- `tests/oracle/test_master_problem_multi_cut.py`
- `tests/integration/test_master_problem_runtime_fixture.py`
- `tests/fixtures/master_problem_multi_cut_two_line_envelope.yaml`
- `docs/reports/round_07_5_report.md`

## Design decisions
- Kept this round validation/interface-hardening only.
- Preserved the Round 07 fixed-cut master mathematics unchanged.
- Did not add cut generation, a separation driver, a Benders driver, or any end-to-end planning solve.
- Added one explicit production helper on the structured cut type:
  - `RestrictedMasterCut.from_samplewise_decomposition(...)`
  - this converts a validated `SamplewisePaperDualDecomposition` into the structured production master-cut representation without flattening the first-stage blocks
- Extended the master residual summary rather than widening master logic:
  - `active_cut_ids`
  - `active_nontrivial_cut_ids`
  - `first_stage_attached_objective_value`
  - `first_stage_objective_is_pure_construction`
- Numerical tolerance used for interface/reconstruction checks:
  - `1e-8` for toy/interface checks
  - `1e-7` for the runtime master objective reconstruction gap
- No narrow bug fix in `src/production/first_stage.py`, `src/production/normal_block.py`, or `src/production/disaster_dual_paper.py` was required.

## Real-cut interface check
- Used the already validated paper-dual chain directly:
  - source toy case: `disaster_primal_shortage.yaml`
  - path:
    1. solve fixed-sample paper dual
    2. read `samplewise_decomposition`
    3. convert via `RestrictedMasterCut.from_samplewise_decomposition(...)`
    4. feed the resulting structured cut into the production master
- The resulting nontrivial real cut had:
  - `beta = 0.0`
  - `gamma_n_sl_by_bus[2] = 30.0`
  - `phi_by_line_id["line_01_02"] = 100.0`
- The interface test verified:
  - the cut is nontrivial
  - the master support row is named and assembled correctly
  - the support-row RHS equals `beta`
  - the coefficient on `n_sl[2]` equals the real cut’s `gamma_n_sl_by_bus[2]`
  - the linewise `u`-link row RHS equals the real cut’s `phi_by_line_id["line_01_02"]`
  - the `u`, `lambda`, and `s` coefficients in the `u`-link row all have the expected `+1` sign
- Solved real-cut master summary:
  - objective: `0.0`
  - cut-support slack: `0.0`
  - max cut-support violation: `0.0`
  - max `u`-link violation: `0.0`

## Multi-cut validation
- Added one toy case with two simultaneous supplied cuts on a 2-line feeder:
  - `gamma_site`
  - `phi_support`
- The multi-cut indexing test verified:
  - one support row exists per cut
  - one `u`-link row exists per cut-line pair
  - `s_r` is indexed by cut id and not shared
  - `u_{r,l}` is indexed by both cut id and line id and not shared
- The solved multi-cut envelope behaved correctly:
  - objective: `37.0`
  - `z_2 = 1`
  - `n_sl_2 = 3`
  - `alpha = 0.0`
  - `lambda_line_01_02 = 10.0`
  - active cuts: `("gamma_site", "phi_support")`
  - support slacks:
    - `gamma_site = 0.0`
    - `phi_support = 0.0`
- This confirms the fixed-cut master can enforce multiple cuts simultaneously without cut-index or line-index sharing.

## First-stage objective API regression
- Added an explicit master-level regression using `master_problem_normal_averaging.yaml`.
- Verified the attached first-stage object behaves as expected inside the master:
  - `first_stage_solution.objective_is_pure_construction == False`
  - `first_stage_solution.objective_value == master objective`
  - `first_stage_solution.objective_value != construction_cost_value`
- Verified the master residual/objective summary continues to use the pure construction contribution:
  - `first_stage_attached_objective_value = 1.54`
  - `construction_cost_value = 0.04`
  - weighted normal term `= 1.5`
  - disaster master term `= 0.0`
  - reconstructed objective matches the solved master objective within tolerance
- No change to the Round 06.5 first-stage API semantics was needed; this round only hardened downstream use of that API.

## Runtime-fixture smoke extension
- Kept the existing raw-read guard:
  - canonical instance is loaded first
  - then `builtins.open` is patched to fail on any `data/runtime_12/*` read during production build/solve
- Preserved the original trivial-cut smoke path.
- Added a second runtime smoke path with a nontrivial supplied real cut:
  - built a valid fixed first-stage seed plan with buses `5` and `9` opened and `3` slow chargers at each
  - used outage `line_01_02 = 1`
  - solved the validated paper dual on the canonical runtime instance
  - converted the resulting `samplewise_decomposition` into `runtime_real_cut`
  - solved the runtime fixed-cut master with that supplied cut under the raw-read guard
- Runtime supplied-cut summary:
  - total objective: `24916711.48002532`
  - construction cost: `4410273.923833655`
  - weighted normal term: `20506437.556191687`
  - disaster master term: `0.0`
  - `alpha = 0.0`
  - `lambda^T FP = 0.0`
  - objective reconstruction gap: `2.2351741790771484e-08`
  - max cut-support violation: `0.0`
  - max `u`-link violation: `0.0`
  - active nontrivial cuts: `("runtime_real_cut",)`
  - `runtime_real_cut` support slack: `0.0`
  - `runtime_real_cut:line_01_02` `u`-link slack: `667726.259999997`
  - `first_stage_objective_is_pure_construction = False`
  - `first_stage_attached_objective_value = 24916711.48002532`
- The supplied nontrivial cut path passed under the same raw-read guard without touching raw CSV/JSON files.

## Tests run
- `pytest tests/unit/test_master_problem_coeffs.py -q`
  - Result: `2 passed in 0.05s`
- `pytest tests/unit/test_master_problem_objective_api.py -q`
  - Result: `1 passed in 0.05s`
- `pytest tests/oracle/test_master_problem_toy_cases.py -q`
  - Result: `4 passed in 0.06s`
- `pytest tests/oracle/test_master_problem_real_cut_interface.py -q`
  - Result: `1 passed in 0.05s`
- `pytest tests/oracle/test_master_problem_multi_cut.py -q`
  - Result: `2 passed in 0.06s`
- `pytest tests/integration/test_master_problem_runtime_fixture.py -q`
  - Result: `2 passed in 3.25s`
- `pytest -q`
  - Result: `128 passed in 10.97s`

## Audit artifacts
- Stable LP dump paths
  - toy real-cut master: `/tmp/round_07_5_real_cut_master.lp`
  - runtime master with supplied real cut: `/tmp/round_07_5_runtime_master_with_real_cut.lp`
- Objective decomposition summary
  - real-cut toy master:
    - objective `0.0`
    - cut-support slack `0.0`
  - multi-cut master:
    - objective `37.0`
    - active cuts `("gamma_site", "phi_support")`
  - runtime supplied-cut master:
    - construction `4410273.923833655`
    - weighted normal `20506437.556191687`
    - disaster master `0.0`
    - total objective `24916711.48002532`
- Cut-support / `u`-link summary
  - real-cut toy:
    - max cut-support violation `0.0`
    - max `u`-link violation `0.0`
  - multi-cut toy:
    - `gamma_site` support slack `0.0`
    - `phi_support` support slack `0.0`
  - runtime supplied-cut:
    - active nontrivial cut ids `("runtime_real_cut",)`
    - support slack `0.0`
    - largest reported `u`-link slack on `line_01_02`: `667726.259999997`

## Known limitations
- The real-cut interface test proves the master consumes structured cuts from the validated disaster-dual chain, but it still does not build those cuts inside production code automatically.
- The runtime supplied-cut smoke remains a smoke/integration check, not an end-to-end planning optimality claim.
- The runtime supplied-cut path used one explicit hand-picked seed plan and outage to produce a nontrivial real cut; this is intentional interface validation, not cut-generation logic.

## Open issues for next round
- Round 08 can now build cut-construction logic against a hardened interface:
  - real structured cuts already pass into the master cleanly
  - multi-cut indexing is now regression-protected
  - the pure-construction-vs-attached-objective boundary is now protected at the master layer
- When cut generation is added, preserve the current structured `beta/gamma/phi` interface and the new active-cut diagnostics rather than introducing a second incompatible cut format.
- Keep the runtime raw-read guard in place for any future production layer that wraps the fixed-cut master.

## Narrow bug fix status
- No narrow bug fix in the Round 07.5 permission list was required.
- The only adjustment during implementation was choosing a nontrivial runtime seed plan/outage pair for the new supplied-cut smoke test; no production math change was needed.
