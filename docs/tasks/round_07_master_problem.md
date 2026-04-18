# Round 07 - Restricted Master Problem (RMP) Builder

## Objective

Implement the production restricted master problem builder that combines:

1. the validated first-stage planning block,
2. the validated explicit normal-operation blocks over the selected normal scenarios,
3. the disaster master variables `alpha` and `lambda`,
4. a fixed externally supplied disaster-cut family,

without implementing cut generation, a Benders driver, or any end-to-end planning loop.

This round has one bounded proof obligation:

> the production RMP for Eq. (33), Eq. (37)–(39) must be buildable, auditable, and correct for a fixed cut set, while preserving the existing reference/production boundaries.

---

## Allowed files to create/update

Primary implementation files:
- `src/production/master_problem.py`
- `src/audit/model_dump.py`
- `src/audit/residual_report.py`

Primary test files:
- `tests/unit/test_master_problem_coeffs.py`
- `tests/oracle/test_master_problem_toy_cases.py`
- `tests/integration/test_master_problem_runtime_fixture.py`

Fixture files for this round:
- `tests/fixtures/master_problem_*.yaml`

Round report:
- `docs/reports/round_07_report.md`

### Narrow bug-fix permission (only if required by the new Round 07 tests)

The following files may be edited **only** if a new Round 07 test reveals a localized bug that blocks the RMP proof obligation:

- `src/production/first_stage.py`
- `src/production/normal_block.py`

If any narrow-fix file is changed:
- keep the change minimal
- explain exactly why it was needed
- show which new Round 07 test exposed it
- do not widen scope beyond the localized fix

---

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/*`

Do not implement in this round:
- `src/production/cut_factory.py`
- `src/production/benders_engine.py`

Also forbidden in this round:
- no cut generation
- no separation iteration driver
- no single-iteration Benders driver
- no disaster dual re-solve flow
- no end-to-end planning solve
- no semantic fallback from `ambig.w` to `critical_buses`
- no raw CSV/JSON reads in the production model layer

---

## Required behavior

### A. Fixed-cut RMP builder
Implement a production RMP builder that includes:

- first-stage variables and constraints from Eq. (10)–(12)
- explicit normal-operation recourse blocks for all selected normal scenarios
- disaster master variables:
  - scalar `alpha`
  - linewise `lambda_l >= 0`
- a fixed externally supplied cut set `R`

The RMP objective must be:

`F_cons(x) + ((1 - pi_f) / A) * sum_a F_nor^a(x, y^a) + pi_f * (alpha + lambda^T FP)`

where:
- `A` is the number of selected normal scenarios loaded into the canonical instance for this run
- normal blocks are explicitly attached, not replaced by precomputed numbers
- the disaster part uses the cut approximation only

### B. Cut-family representation
Introduce a stable production-side cut representation for a single disaster cut with at least:

- `beta`
- `gamma_z_by_bus`
- `gamma_n_sl_by_bus`
- `gamma_n_fa_by_bus`
- `phi_by_line_id`

The production RMP must consume this representation directly.
Do **not** flatten the first-stage vector into an opaque array in this round.

If no cut list is supplied, the RMP builder must still be able to build using the trivial cut.

### C. Eq. (39) cut realization
For each cut `r`, build the RMP auxiliary variables and rows corresponding to Eq. (39):

- one `s_r >= 0`
- one `u_{r,l} >= 0` for each line `l`

and constraints of the form implied by Eq. (39):

- `alpha >= beta_r - gamma_r^T x + K s_r + sum_l u_{r,l}`
- `u_{r,l} >= phi_{r,l} - lambda_l - s_r`

The implementation must expose enough structure to audit:
- `alpha`
- `lambda_by_line_id`
- `s_by_cut_id`
- `u_by_cut_id_and_line_id`

### D. Stable ordering / interface discipline
The RMP must preserve and expose stable production ordering:

- first-stage bus ordering exactly `instance.sets.buses`
- line ordering exactly the canonical stable line ordering from the topology/index layer

The RMP must expose or document the first-stage block ordering in a way that is compatible with later `gamma`-based cut usage.

### E. Normal-block integration discipline
The RMP must integrate the existing validated normal block without changing its math:

- use only canonical objects from the instance layer
- do not read raw CSV/JSON directly
- keep unmet-demand indexing aggregated by `(t, region, charger_type)`
- keep EV charging active-power-only unless the canonical contract later expands it
- keep the normal-operation model linear

### F. Required coefficient / model-shape checks
Add direct checks that verify at least:

1. objective coefficients:
   - coefficient on `alpha` is `pi_f`
   - coefficient on each `lambda_l` is `pi_f * FP_l`
   - normal-scenario objective contributions are scaled by `((1 - pi_f) / A)`

2. one cut-support row exists per cut:
   - correct sign pattern on `alpha`
   - correct sign pattern on the relevant `z / n_sl / n_fa` variables through `gamma`
   - correct sign pattern on `s_r`
   - correct sign pattern on `u_{r,l}`

3. one `u`-link row exists per cut-line pair:
   - correct sign pattern on `u_{r,l}`, `lambda_l`, and `s_r`
   - correct linewise `phi` contribution

### G. Required toy cases
At minimum include these hand-checkable RMP toy cases:

1. **trivial-cut zero-demand sanity**
   - no normal demand
   - trivial cut only
   - expect no construction, `alpha = 0`, `lambda = 0`, total objective `0`

2. **normal-expectation averaging sanity**
   - two selected normal scenarios with hand-checkable different normal costs
   - trivial cut only
   - verify the RMP objective uses the average normal cost with weight `((1 - pi_f) / A)`

3. **gamma-driven siting incentive cut**
   - one synthetic disaster cut where opening a site reduces the disaster lower bound
   - verify the RMP can prefer opening the site when the disaster benefit exceeds construction cost

4. **phi/lambda support sanity**
   - one-line cut with hand-checkable `phi > 0`, `K = 1`
   - verify the RMP chooses `lambda` / `alpha` consistently with the budget-support interpretation

The toy cases may use tiny synthetic instances/fixtures.

### H. Runtime-fixture integration smoke
Add one runtime-fixture integration test that:

- loads the canonical runtime fixture under the existing selection-driven boundary
- builds the RMP on all currently selected normal scenarios
- uses at least the trivial cut
- solves the RMP
- emits a residual/objective summary
- verifies no raw data file reads occur during production model build/solve
  after the canonical instance has already been loaded

This is a smoke/integration test, not an end-to-end planning optimality claim.

### I. Contract preservation
The following must remain true:
- no inference from `ambig.w`
- no raw-data access in the production model layer
- default runtime selection remains selection-driven, not raw-package-equality-driven
- disaster/reference/dual/separation validation chain remains untouched in this round

### J. Solver / audit discipline
- Use `gurobipy` for LP/MILP models in this round.
- Support stable LP dump paths for:
  - at least one toy RMP
  - at least one runtime-fixture RMP
- Keep the implementation auditable and easy to inspect.

---

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/unit/test_master_problem_coeffs.py -q`
- `pytest tests/oracle/test_master_problem_toy_cases.py -q`
- `pytest tests/integration/test_master_problem_runtime_fixture.py -q`
- `pytest tests/unit/test_first_stage_coeffs.py -q`
- `pytest tests/unit/test_normal_block_coeffs.py -q`
- `pytest tests/integration/test_first_stage_normal_runtime_fixture.py -q`
- `pytest tests/oracle/test_separation_exactness.py -q`
- `pytest -q`

---

## Deliverables

You must return:

1. implementation in the allowed files
2. required tests
3. `docs/reports/round_07_report.md`
4. stable LP dump path(s) for:
   - at least one toy RMP
   - at least one runtime-fixture RMP
5. concise RMP diagnostics including:
   - selected first-stage solution summary
   - `alpha`
   - `lambda`
   - cut residual summary
   - objective decomposition summary
6. if any narrow bug-fix files were changed:
   - the exact files changed
   - the exact bug
   - which new Round 07 test exposed it

---

## Report format

Write `docs/reports/round_07_report.md` with at least:

```md
# Round 07 Report

## Files changed
- ...

## Design decisions
- ...

## RMP design
- ...

## Coefficient/model-shape checks
- ...

## Toy-case objective checks
- ...

## Tests run
- command
- result

## Audit artifacts
- LP dump paths
- first-stage summary
- alpha/lambda summary
- cut residual summary
- objective decomposition summary

## Known limitations
- ...

## Open issues for next round
- ...
```

Model rounds should also include:
- any numerical tolerance used for hand-check / residual checks
- whether any narrow bug fix was needed
- whether the averaging-sanity and phi/lambda-sanity checks passed
