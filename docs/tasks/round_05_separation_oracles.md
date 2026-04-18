# Round 05 - Separation MILP + Oracle Exactness

## Objective

Implement the fixed-`(x, alpha, lambda)` separation layer for the disaster DRO term, together with the independent oracle checks needed to validate its exactness on tiny cases.

This round has one bounded proof obligation:

> the linearized separation MILP for Eq. (41) must agree with independent tiny-case oracles, while respecting the existing reference/production boundaries.

This round must:
- use the already validated fixed-sample disaster primal / auto dual / paper dual chain from Rounds 02-04
- keep all disaster math active-power-only
- avoid any master-problem, cut-generation, or Benders-loop implementation

## Allowed files to create/update

Primary implementation files:
- `src/reference/outage_enumerator.py`
- `src/reference/dro_outer_lp_oracle.py`
- `src/production/separation_milp.py`
- `src/audit/model_dump.py`

Primary test files:
- `tests/oracle/test_budget_support_fn.py`
- `tests/oracle/test_dro_outer_lp.py`
- `tests/oracle/test_separation_exactness.py`
- `tests/integration/test_separation_runtime_fixture.py`

Fixture files for this round:
- `tests/fixtures/separation_*.yaml`

Round report:
- `docs/reports/round_05_report.md`

### Narrow bug-fix permission (only if required by the new exactness tests)

The following files may be edited **only** if the new Round 05 tests reveal a localized bug that blocks exactness:
- `src/reference/disaster_primal_ref.py`
- `src/reference/lp_canonicalizer.py`
- `src/reference/disaster_dual_auto.py`
- `src/production/disaster_dual_paper.py`
- `src/audit/residual_report.py`

If any of these narrow-fix files are changed:
- keep the change minimal
- explain exactly why it was needed
- show which new Round 05 test exposed it
- do not widen scope beyond the localized fix

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`

Do not implement in this round:
- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/production/master_problem.py`
- `src/production/cut_factory.py`
- `src/production/benders_engine.py`

Also forbidden in this round:
- no aggregated multi-cut logic
- no full RMP
- no single-iteration Benders driver
- no end-to-end planning solve
- no semantic fallback from `ambig.w` to `critical_buses`

## Required behavior

### A. Budget-support oracle
Implement an oracle for
`max_{delta in Omega(K)} v^T delta`
for tiny cases.

Requirements:
1. support exact outage enumeration on tiny line sets
2. provide at least one exact oracle path by enumeration
3. provide one additional equivalent path suitable for validation, such as:
   - closed-form top-K-positive interpretation, or
   - a tiny LP formulation
4. expose enough output to compare objective value and selected outage set(s)

### B. Outer-DRO tiny LP oracle
Implement a tiny oracle for the ambiguity-set worst-case expectation over enumerated outage states:
- enumerate `Omega(K)`
- accept values `f(delta)` over enumerated outage patterns
- solve the finite LP over outage probabilities `p`
- respect:
  - `sum p = 1`
  - `sum p * delta <= FP`
- return both the optimal value and the worst-case probability mass assignment

This oracle is for validation on tiny cases only.

### C. Fixed-point separation MILP
Implement the linearized separation MILP corresponding to Eq. (41) for fixed:
- first-stage plan `x`
- current master variables `alpha`
- current ambiguity multipliers `lambda`
- sampled disaster set

Requirements:
1. keep the model active-power-only
2. do not introduce master-problem or cut-factory logic
3. use the fixed-sample paper-dual interpretation from Round 04
4. keep `delta` binary and budget-constrained
5. build the McCormick linearization for `tau = delta * omega`
6. expose:
   - optimal violation value
   - optimal outage vector `delta_star`
   - samplewise paper-dual solution blocks
   - enough diagnostics to reconstruct the separation objective from
     `beta_b / gamma_b / phi_b`-style ingredients

### D. Exactness validation against oracles
Add exactness tests on tiny cases that compare:
1. separation MILP objective
2. outage-enumeration oracle objective

At minimum include:
- one generic tiny case
- one `phi-only` / line-limit-dominated case that isolates line-outage contributions
- one case whose dual groups activate beyond a trivial subset

### E. Required regression-strengthening checks
Add the following checks in this round:

1. **dual-group activation check**
   Across the oracle/exactness tests, ensure that the following groups are all exercised somewhere:
   - `eta`
   - `mu`
   - `nu`
   - `sigma`
   - `rho_upper`
   - `rho_lower`

2. **blockwise decomposition reconstruction**
   On at least one tiny case, reconstruct the relevant separation expression from exposed samplewise quantities and show agreement with the solved separation objective up to solver tolerance.

3. **runtime-fixture integration smoke**
   Add one integration test showing that the separation MILP can be built and solved on the canonical runtime fixture with:
   - explicit test-only `critical_buses`
   - fixed test plan `x`
   - fixed test `alpha`
   - fixed test `lambda`

This integration test is a smoke/integration check, not an end-to-end optimality claim.

### F. Contract preservation
The following must remain true:
- `critical_buses` is still required for disaster-objective-ready model construction
- `critical_buses` is never inferred from `ambig.w`
- default runtime selection remains selection-driven, not raw-package-equality-driven
- no production decomposition logic beyond `separation_milp.py` enters this round

### G. Solver / audit discipline
- Use `gurobipy` for LP/MILP models in this round.
- Support stable LP dump paths for:
  - at least one separation MILP
  - at least one oracle LP, if applicable
- Keep the implementation auditable and easy to inspect.

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/oracle/test_budget_support_fn.py -q`
- `pytest tests/oracle/test_dro_outer_lp.py -q`
- `pytest tests/oracle/test_separation_exactness.py -q`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
- `pytest tests/integration/test_separation_runtime_fixture.py -q`
- `pytest -q`

## Deliverables

You must return:

1. implementation in the allowed files
2. required tests
3. `docs/reports/round_05_report.md`
4. stable LP dump path(s) for:
   - separation MILP
   - outer-DRO LP oracle (if dumped)
5. concise separation diagnostics including:
   - worst-case outage vector
   - violation value
   - exactness comparison against the oracle on at least one tiny case
6. if any narrow bug-fix files were changed:
   - the exact files changed
   - the exact bug
   - which new test exposed it

## Report format

Write `docs/reports/round_05_report.md` with at least:

```md
# Round 05 Report

## Files changed
- ...

## Design decisions
- ...

## Oracle design
- ...

## Separation MILP design
- ...

## Exactness comparisons
- ...

## Tests run
- command
- result

## Audit artifacts
- LP dump paths
- worst outage vector(s)
- violation summary
- oracle vs MILP comparison summary

## Known limitations
- ...

## Open issues for next round
- ...
```

Model rounds should also include:
- any numerical tolerance used for exactness comparison
- whether any narrow bug fix was needed
- whether the `phi-only` and dual-group activation checks passed
