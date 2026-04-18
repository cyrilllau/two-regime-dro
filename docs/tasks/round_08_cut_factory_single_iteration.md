# Round 08 - Cut Factory + Single-Iteration Flow

## Objective

Implement the production cut-construction layer and a **single-iteration** outer-loop flow that connects:

- the fixed-cut production master,
- the validated separation MILP,
- the validated fixed-sample paper-dual chain,

without implementing the full Benders driver.

This round has one bounded proof obligation:

> a cut generated from validated samplewise paper-dual solutions at the separation worst outage can be converted into the structured master-cut format, inserted into the fixed-cut production master, and on at least one tiny case it must provably cut the old master solution and produce the expected lower-bound behavior.

This round must:
- use the already validated disaster primal / auto dual / paper dual / separation chain from Rounds 02–05.5
- use the hardened first-stage + normal-block + fixed-cut master interfaces from Rounds 06–07.5
- stop at **one** cut-generation-and-addition step
- avoid any full Benders loop, multi-iteration driver, or end-to-end planning solve

## Allowed files to create/update

Primary implementation files:
- `src/production/cut_factory.py`
- `src/audit/cut_audit.py`

Primary test files:
- `tests/oracle/test_cut_factory.py`
- `tests/integration/test_single_iteration_cut_addition.py`
- `tests/integration/test_cut_factory_runtime_fixture.py`

Fixture files for this round:
- `tests/fixtures/cut_factory_*.yaml`

Round report:
- `docs/reports/round_08_report.md`

### Narrow bug-fix permission (only if required by the new Round 08 interface tests)

The following files may be edited **only** if the new Round 08 tests reveal a localized bug that blocks valid cut construction or one-step integration:

- `src/production/master_problem.py`
- `src/production/disaster_dual_paper.py`
- `src/production/separation_milp.py`
- `src/audit/residual_report.py`

If any of these narrow-fix files are changed:
- keep the change minimal
- explain exactly why it was needed
- show which new Round 08 test exposed it
- do not widen scope beyond the localized fix

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/*`

Do not implement in this round:
- `src/production/benders_engine.py`
- any multi-iteration Benders loop
- any global end-to-end planning solve
- any new raw-data loading path
- any semantic fallback from `ambig.w` to `critical_buses`

## Required behavior

### A. Samplewise cut factory
Implement a production cut-factory path that, for fixed:
- canonical instance
- current first-stage plan `x`
- separation-selected outage `delta_star`
- loaded disaster sample set

does the following:

1. solves the validated fixed-sample hand-coded paper dual **once per loaded disaster sample** at `(x, delta_star, b)`
2. extracts the samplewise decomposition from each solve
3. aggregates those decompositions exactly as in Eq. (36), preserving the structured blocks:
   - `beta`
   - `gamma_z_by_bus`
   - `gamma_n_sl_by_bus`
   - `gamma_n_fa_by_bus`
   - `phi_by_line_id`
4. returns a production `RestrictedMasterCut` (or equivalent structured cut object) without flattening the first-stage blocks
5. exposes enough diagnostics to audit:
   - samplewise decompositions
   - aggregated cut coefficients
   - source outage vector
   - source plan `x`

### B. Extreme-point / solver discipline
Because the theorem-level cut family is defined over extreme optimal dual solutions, this round must use an LP solve mode that is appropriate for extracting an optimal basic/extreme-point solution from the fixed-sample paper duals.

Required behavior:
- use a simplex-based solve mode for the per-sample paper-dual LPs in the cut-factory path
- document the chosen Gurobi method/parameter in the round report
- do not silently rely on a barrier/interior solution if that would lose the extreme-point interpretation

If the existing validated paper-dual builder already guarantees this in the current environment, state that explicitly.

### C. Cut-audit artifact
Add a structured audit artifact for one generated cut.

Minimum contents:
- cut id
- source round / provenance string
- source `x`
- source `alpha`, `lambda` (if available from the one-step flow)
- source `delta_star`
- samplewise `beta_b / gamma_b / phi_b` pieces
- aggregated `beta / gamma / phi`
- at-source violation or equivalent justification for why the cut was added

This may be emitted either as a Python object plus tests, or via a lightweight stable dump helper.

### D. Single-iteration flow (no loop)
Add a **single-step** production flow for tiny/integration testing only:

1. build and solve the fixed-cut master with its current supplied cuts
2. read `(x_star, alpha_star, lambda_star)`
3. solve the fixed-point separation MILP at that point
4. if violation exceeds tolerance, generate one new cut via the cut factory
5. rebuild or extend the fixed-cut master with the new cut
6. re-solve once
7. stop

This is not a Benders engine. It is only a one-iteration integration path.

### E. Required strengthening checks
Add the following checks in this round:

1. **Generated-cut efficacy on a tiny case**
   On at least one tiny case, a generated real cut must do something nontrivial:
   - either increase the fixed-cut master objective,
   - or change the master solution,
   - or make the disaster master term become positive,
   but in all cases:
   - the old master solution must violate the new cut by more than tolerance,
   - the re-solved master must satisfy the new cut within tolerance.

2. **Multi-cut carryover with a generated real cut**
   Add one tiny test in which the master already has an existing cut and then receives a generated real cut.
   Verify:
   - cut ids remain distinct
   - `s_r` and `u_{r,l}` indexing remains per-cut
   - both cuts are enforced after the re-solve

3. **Master objective-boundary regression under cut addition**
   Add a regression showing that after adding a generated cut:
   - the master still reconstructs the objective using pure `construction_cost_value`
   - attached first-stage `objective_value` is not misused as the pure first-stage term

4. **Runtime-fixture generated-cut smoke**
   Add one runtime smoke/integration test that:
   - loads the canonical runtime fixture first
   - activates the existing raw-read guard
   - solves one fixed-cut runtime master
   - runs separation once
   - generates one real cut from the validated paper-dual chain
   - re-solves the fixed-cut runtime master with that new cut
   This is a smoke/integration check only, not an end-to-end optimality claim.

### F. Contract preservation
The following must remain true:
- `critical_buses` is still required for disaster-objective-ready model construction
- `critical_buses` is never inferred from `ambig.w`
- default runtime selection remains selection-driven, not raw-package-equality-driven
- no production logic beyond cut construction and one-step integration enters this round

### G. Solver / audit discipline
- Use `gurobipy` for LP/MILP models in this round.
- Support stable LP dump paths for:
  - at least one master before cut addition
  - at least one master after cut addition
- Keep the implementation auditable and easy to inspect.

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/oracle/test_cut_factory.py -q`
- `pytest tests/integration/test_single_iteration_cut_addition.py -q`
- `pytest tests/integration/test_cut_factory_runtime_fixture.py -q`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
- `pytest tests/oracle/test_separation_exactness.py -q`
- `pytest tests/integration/test_master_problem_runtime_fixture.py -q`
- `pytest -q`

## Deliverables

You must return:

1. implementation in the allowed files
2. required tests
3. `docs/reports/round_08_report.md`
4. stable LP dump path(s) for:
   - master before cut addition
   - master after cut addition
5. concise cut-audit diagnostics including:
   - source outage vector
   - samplewise decomposition summary
   - aggregated `beta / gamma / phi`
   - old-master cut violation
   - new-master post-cut residual summary
6. if any narrow bug-fix files were changed:
   - the exact files changed
   - the exact bug
   - which new Round 08 test exposed it

## Report format

Write `docs/reports/round_08_report.md` with at least:

```md
# Round 08 Report

## Files changed
- ...

## Design decisions
- ...

## Cut factory design
- ...

## Single-iteration integration behavior
- ...

## Tests run
- command
- result

## Audit artifacts
- LP dump paths
- generated cut summary
- pre-cut vs post-cut master summary
- violation / residual summary

## Known limitations
- ...

## Open issues for next round
- ...
```

Model rounds should also include:
- the simplex/extreme-point extraction note for samplewise paper-dual solves
- whether the generated-cut efficacy check passed
- whether the runtime generated-cut smoke changed the master meaningfully or only served as an interface smoke
- whether any narrow bug fix was needed
