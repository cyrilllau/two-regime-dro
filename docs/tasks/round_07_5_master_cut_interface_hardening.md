# Round 07.5 - Master/Cut Interface Hardening

## Objective

Harden the fixed-cut restricted master problem before any cut-construction or single-iteration Benders work.

This round has one bounded proof obligation:

> the production master problem must be proven to consume structured real `beta/gamma/phi` cuts correctly, enforce multiple cuts simultaneously, and preserve the first-stage objective API boundary established in Round 06.5.

This round must:
- stay validation/interface-hardening only
- preserve the existing fixed-cut RMP mathematics from Round 07
- avoid any cut-generation, separation-driver, or Benders-loop implementation
- add the specific regression checks needed before Round 08

## Allowed files to create/update

Primary implementation files:
- `src/production/master_problem.py`
- `src/audit/residual_report.py`

Primary test files:
- `tests/oracle/test_master_problem_real_cut_interface.py`
- `tests/oracle/test_master_problem_multi_cut.py`
- `tests/unit/test_master_problem_objective_api.py`
- `tests/integration/test_master_problem_runtime_fixture.py`

Fixture files for this round:
- `tests/fixtures/master_problem_real_cut_*.yaml`
- `tests/fixtures/master_problem_multi_cut_*.yaml`

Round report:
- `docs/reports/round_07_5_report.md`

### Narrow bug-fix permission (only if required by the new interface tests)

The following files may be edited **only** if the new Round 07.5 tests reveal a localized bug that blocks the required interface validation:
- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/production/disaster_dual_paper.py`

If any of these narrow-fix files are changed:
- keep the change minimal
- explain exactly why it was needed
- show which new Round 07.5 test exposed it
- do not widen scope beyond the localized fix

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/*`
- `src/production/separation_milp.py`
- `src/production/cut_factory.py`
- `src/production/benders_engine.py`

Also forbidden in this round:
- no cut generation
- no separation solve driver
- no single-iteration Benders flow
- no end-to-end planning solve
- no semantic fallback from `ambig.w` to `critical_buses`
- no flattening of the structured cut representation into an opaque first-stage vector

## Required behavior

### A. Real-cut interface validation
Add at least one test that feeds the master problem with a **nontrivial real cut** obtained from the already validated disaster-dual chain, rather than a purely synthetic hand-written toy cut.

Requirements:
1. the cut must enter the master through the structured production-side representation:
   - `beta`
   - `gamma_z_by_bus`
   - `gamma_n_sl_by_bus`
   - `gamma_n_fa_by_bus`
   - `phi_by_line_id`
2. the test must validate that the master builder consumes these fields without reindexing drift
3. the test must show that the resulting cut-support row and linewise `u`-link rows are assembled with the expected signs and RHS values
4. the test may obtain the real cut by either:
   - solving a tiny fixed-sample paper dual and extracting the exposed decomposition, or
   - loading a fixture that was explicitly generated from such an extracted decomposition
5. do **not** implement cut factory logic in this round

### B. Multi-cut envelope validation
Add tests showing that the fixed-cut RMP correctly handles more than one cut simultaneously.

Requirements:
1. build at least one toy case with two distinct cuts present at once
2. validate that:
   - one support row exists per cut
   - one linewise `u`-link row exists per cut-line pair
   - `s_r` is indexed by cut id and not shared across cuts
   - `u_{r,l}` is indexed by both cut id and line id and not shared across cuts
3. validate the master envelope behavior on the toy case:
   - either both cuts matter simultaneously, or
   - one cut is inactive but still present and correctly indexed
4. do not rely only on row counts; include at least one value/solution-level check

### C. First-stage objective API regression at the master layer
Add a regression showing that the master problem uses the pure first-stage construction quantity consistently.

Requirements:
1. explicitly test a case where:
   - the attached first-stage object has `objective_is_pure_construction = False`
   - `objective_value` differs from `construction_cost_value`
2. validate that the master objective decomposition/reporting still uses the pure construction contribution correctly
3. keep the distinction explicit in the solved master summary/reporting
4. do not change the Round 06.5 semantics of the first-stage API; only harden and verify downstream use

### D. Runtime-fixture smoke extension
Extend the existing runtime-fixture integration test so it covers the hardened master/cut boundary.

Requirements:
1. keep the raw-read guard in place
2. include at least one nontrivial supplied cut in addition to the trivial-cut path, or add a dedicated second runtime-fixture test that does so
3. continue to treat this as a smoke/integration check, not an end-to-end optimality claim
4. report:
   - objective decomposition
   - cut-support slack / violation
   - `u`-link slack / violation
   - whether any supplied nontrivial cut is active at the solution

### E. Contract preservation
The following must remain true:
- `critical_buses` is still required for any disaster-objective-ready path
- `critical_buses` is never inferred from `ambig.w`
- the master still consumes only canonical objects
- default runtime selection remains selection-driven
- the fixed-cut master remains separate from cut generation and Benders control flow

### F. Solver / audit discipline
- Use `gurobipy` for LP/MILP models in this round.
- Support stable LP dump paths for:
  - at least one toy master with nontrivial supplied cuts
  - at least one runtime-fixture master instance
- Keep the implementation auditable and easy to inspect.

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/unit/test_master_problem_coeffs.py -q`
- `pytest tests/unit/test_master_problem_objective_api.py -q`
- `pytest tests/oracle/test_master_problem_toy_cases.py -q`
- `pytest tests/oracle/test_master_problem_real_cut_interface.py -q`
- `pytest tests/oracle/test_master_problem_multi_cut.py -q`
- `pytest tests/integration/test_master_problem_runtime_fixture.py -q`
- `pytest -q`

## Deliverables

You must return:

1. implementation in the allowed files
2. required tests
3. `docs/reports/round_07_5_report.md`
4. stable LP dump path(s) for:
   - at least one toy fixed-cut master with nontrivial supplied cuts
   - the runtime-fixture master
5. concise master/cut diagnostics including:
   - one real-cut interface summary
   - one multi-cut summary
   - one explicit objective decomposition showing pure construction vs attached objective separation
6. if any narrow bug-fix files were changed:
   - the exact files changed
   - the exact bug
   - which new test exposed it

## Report format

Write `docs/reports/round_07_5_report.md` with at least:

```md
# Round 07.5 Report

## Files changed
- ...

## Design decisions
- ...

## Real-cut interface check
- ...

## Multi-cut validation
- ...

## First-stage objective API regression
- ...

## Runtime-fixture smoke extension
- ...

## Tests run
- command
- result

## Audit artifacts
- LP dump paths
- objective decomposition summary
- cut-support / u-link summary

## Known limitations
- ...

## Open issues for next round
- ...
```

Model rounds should also include:
- any numerical tolerance used for objective/reconstruction checks
- whether any narrow bug fix was needed
- whether the real-cut and multi-cut checks passed
