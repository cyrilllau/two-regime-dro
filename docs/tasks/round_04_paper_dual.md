# Round 04 - Hand-coded paper dual

## Objective
Implement the **hand-coded paper dual** for the fixed-`(x, delta, b)` disaster recourse block, and validate it against the existing **auto dual** and **reference primal**.

This round has one bounded proof obligation:

> For the same fixed disaster sample `b`, fixed first-stage plan `x`, and fixed outage vector `delta`, the hand-coded paper dual must match the Round 02 disaster primal reference LP and the Round 03 mechanically derived auto dual.

This round also absorbs two narrow follow-up fixes requested after Round 03 review:
1. add a **minimal canonicalization sign-regression test**;
2. add an explicit **missing-`critical_buses` regression test** for the disaster-objective readiness gate.

## Allowed files to create/update
Primary implementation:
- `src/production/disaster_dual_paper.py`
- `src/audit/residual_report.py`

Reference-track support fixes **only if required by the new tests**:
- `src/reference/lp_canonicalizer.py`
- `src/reference/disaster_dual_auto.py`
- `src/reference/kkt_checks.py`
- `src/reference/disaster_primal_ref.py`

Tests:
- `tests/oracle/test_disaster_dual_paper.py`
- `tests/oracle/test_lp_canonicalizer_signs.py`
- `tests/oracle/test_disaster_readiness_gate.py`
- `tests/integration/test_disaster_dual_paper_runtime_fixture.py`

Optional test touch-ups **only if required for shared helpers/assertions**:
- `tests/oracle/test_disaster_primal_dual.py`
- `tests/oracle/test_disaster_primal_ref.py`

Report:
- `docs/reports/round_04_report.md`

## Do not modify
Protected areas:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/production/separation_milp.py`
- `src/production/cut_factory.py`
- `src/production/master_problem.py`
- `src/production/benders_engine.py`

Forbidden scope expansions:
- no separation MILP
- no cut generation
- no master problem
- no Benders logic
- no aggregated multi-sample disaster dual
- no changes to the Round 02 disaster primal mathematics, except a **narrow readiness-gate fix** if required by the new regression test

## Required behavior

### 1. Implement the hand-coded paper dual
Create `src/production/disaster_dual_paper.py` for a fixed `(x, delta, b)` disaster sample.

It must:
- represent the **paper dual**, not the auto dual;
- be built from the disaster primal mathematics of Eq. (26)–(32) and the compact dual interpretation of Eq. (34)–(35);
- remain **active-power-only** and paper-consistent;
- not read raw CSV/JSON directly;
- consume only canonical objects plus explicit fixed inputs.

### 2. Preserve the reference-track truth chain
The Round 02 disaster primal remains the sole primal source of truth.
The Round 03 auto dual remains the mechanical audit dual.
The new paper dual must be checked against both.

Required equality checks for fixed `(x, delta, b)`:
- `objective(primal_ref) == objective(auto_dual)`
- `objective(auto_dual) == objective(paper_dual)`
- therefore `objective(primal_ref) == objective(paper_dual)`

Use a numerical tolerance appropriate for LP solve noise, but report the actual observed gaps.

### 3. Document the hand-coded dual structure explicitly
The hand-coded paper dual must expose or clearly document:
- dual variable groups;
- which primal equation groups they correspond to;
- sign restrictions for each dual group;
- how the dual objective decomposes into samplewise pieces corresponding to
  - `beta_b`
  - `gamma_b`
  - `phi_b`
  so later rounds can build cut coefficients cleanly.

At minimum, provide a structured object or helper that can return a samplewise decomposition satisfying:
- `dual_value = beta_b - gamma_b^T x + phi_b^T delta`
for the solved fixed-sample paper dual.

### 4. Add named dual-row diagnostics
Extend audit support so debugging can inspect named dual-row / dual-feasibility diagnostics for the hand-coded paper dual.
This does **not** need to be a full production logging system.
It does need to make Round-04 failures diagnosable.

### 5. Add the two requested regression fixes
#### 5a. Minimal canonicalization sign-regression test
Add a very small test that directly checks the canonicalization sign convention on a tiny LP row example.
The goal is to catch future sign drift in:
- equality handling;
- `<=` to canonical `>=` conversion;
- free-variable plus/minus splitting interaction.

If this test reveals a narrow defect in `lp_canonicalizer.py` or `disaster_dual_auto.py`, fix it in this round.

#### 5b. Missing-`critical_buses` regression test
Add an explicit regression test showing that the disaster-objective readiness gate still fails clearly when `critical_buses` is missing.
This test must also confirm that no fallback or inference from `ambig.w` occurs.

If this test reveals a narrow clarity/guard bug in `disaster_primal_ref.py`, fix it in this round **without changing the underlying disaster primal math**.

### 6. Add toy and runtime-fixture comparisons
Required comparisons:
- the existing toy cases;
- the existing mixed slow/fast toy case;
- one runtime-fixture integration test using the canonical runtime fixture plus an explicit test-only `critical_buses` override.

The runtime integration test must compare:
- primal objective
- auto-dual objective
- paper-dual objective

### 7. LP dump discipline
Provide stable LP dump paths for manual audit of the runtime fixture:
- one primal LP dump path
- one auto-dual LP dump path
- one paper-dual LP dump path

### 8. Keep the implementation auditable
The code should remain simple and inspectable.
Do not hide core coefficient logic inside opaque helper chains unless clearly documented.

## Acceptance tests
At minimum, run and report:

- `pytest tests/oracle/test_lp_canonicalizer_signs.py -q`
- `pytest tests/oracle/test_disaster_readiness_gate.py -q`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
- `pytest tests/oracle/test_disaster_primal_dual.py -q`
- `pytest tests/integration/test_disaster_dual_paper_runtime_fixture.py -q`
- `pytest -q`

Expected acceptance properties:
- all tests pass;
- no forbidden scope expansion occurs;
- paper-dual objectives match primal/auto-dual objectives on all required cases;
- the missing-`critical_buses` regression test passes;
- the sign-regression test passes.

## Deliverables
- implementation files within the allowed scope
- tests
- `docs/reports/round_04_report.md`
- stable LP dump paths for manual audit
- a concise note describing:
  - hand-coded dual variable groups
  - sign conventions
  - samplewise `beta_b / gamma_b / phi_b` decomposition
  - any narrow bug fixes made to support the new regression tests

## Report format
Write `docs/reports/round_04_report.md` with at least the following sections:

```md
# Round 04 Report

## Files changed
- ...

## Design decisions
- ...

## Paper-dual mapping
- dual variable groups
- primal equation groups they correspond to
- sign restrictions
- samplewise beta/gamma/phi decomposition note

## Tests run
- command
- result

## Objective comparisons
- toy cases: primal vs auto dual vs paper dual
- runtime fixture: primal vs auto dual vs paper dual
- absolute gaps

## Regression fixes
- canonicalization sign-regression result
- missing-critical-buses regression result
- any narrow bug fixes applied

## Audit artifacts
- primal LP dump path(s)
- auto-dual LP dump path(s)
- paper-dual LP dump path(s)
- dual-row / residual summary

## Known limitations
- ...

## Open issues for next round
- ...
```
