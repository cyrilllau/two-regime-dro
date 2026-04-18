# Round 10 - Final validation & readiness hardening

## Objective

Strengthen final confidence that the current mainline can produce correct experimental results by adding:
1. an **independent** tiny disaster exact cross-check that does **not** rely on the production paper-dual path for disaster evaluation, and
2. a **certified runtime-like convergence test** that reaches `certified_exact` or `certified_epsilon` on a canonical, selection-driven fixture small enough to certify.

This round has one bounded proof obligation:

> the current mainline should be backed by one more layer of independent tiny exact validation and one more layer of runtime-like certification evidence, without changing the validated optimization mathematics.

This round is **validation/readiness hardening only**.

---

## Allowed files to create/update

Primary implementation files:
- `src/reference/disaster_exact_oracle.py`
- `src/reference/brute_force_stage1.py`

Primary test files:
- `tests/oracle/test_disaster_exact_oracle.py`
- `tests/integration/test_disaster_exact_crosscheck.py`
- `tests/integration/test_benders_runtime_certification.py`
- `tests/integration/test_readiness_matrix.py`

Fixture files for this round:
- `tests/fixtures/benders_runtime_certified_small.yaml`
- `tests/fixtures/disaster_exact_crosscheck_*.yaml`

Round report:
- `docs/reports/round_10_report.md`

### Narrow bug-fix permission (only if required by the new Round 10 tests)

The following files may be edited **only** if a new Round 10 validation test exposes a localized bug that blocks the bounded objective:
- `src/production/benders_engine.py`
- `src/audit/iteration_log.py`
- `src/production/cut_factory.py`
- `src/production/master_problem.py`
- `src/production/separation_milp.py`

If any of these narrow-fix files are changed:
- keep the change minimal
- explain exactly why it was needed
- name the new Round 10 test that exposed it
- do not widen scope beyond the localized fix

---

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/reference/disaster_primal_ref.py`
- `src/reference/disaster_dual_auto.py`
- `src/production/disaster_dual_paper.py`

Also forbidden in this round:
- no new algorithmic acceleration features
- no new stabilization / level variant
- no cut deletion / selection policy
- no scenario reduction
- no paper-scale workflow claims
- no semantic fallback from `ambig.w` to `critical_buses`

---

## Required behavior

### A. Independent tiny disaster exact oracle
Add an **independent** disaster exact evaluator for tiny cases.

Requirements:
1. It must evaluate the disaster DRO term for a fixed first-stage plan by using:
   - outage enumeration over `Omega(K)`
   - `disaster_primal_ref` recourse evaluation for each fixed `(x, delta, b)` pair
   - outer-DRO LP oracle over enumerated outage patterns
2. It must **not** rely on the production paper-dual chain to compute the disaster value being compared.
3. It must expose:
   - exact disaster objective value
   - worst-case outage distribution over the enumerated outage states
   - enough intermediate output for audit on tiny cases

### B. Tiny cross-check against current production path
Add a cross-check showing that on at least one tiny end-to-end fixture:
- the current production Benders/tiny-oracle path and
- the new primal-based disaster exact oracle path

agree on the final optimal value.

This cross-check may reuse the existing tiny bounded-candidate fixture family, but the disaster piece must now have an independent primal-based exact path available for comparison.

### C. Certified runtime-like convergence test
Add one **runtime-like but certifiable** Benders regression that:
- uses canonical instance loading / selection-driven semantics
- remains under the raw-read guard
- is small enough to terminate with either:
  - `certified_exact`, or
  - `certified_epsilon`

Requirements:
1. it must not use the default runtime fixture if that fixture is still only suitable for bounded smoke
2. it must still look like a realistic production run:
   - canonical instance
   - first-stage + normal blocks
   - master + separation + cut factory + iterative driver
3. it must expose:
   - stop reason
   - iteration count
   - lower-bound trace
   - cut-count trace
   - final violation upper bound

### D. Readiness matrix
Add one test/report-level readiness summary that makes the current claims explicit.

At minimum distinguish:
- tiny exact certification
- epsilon certification
- runtime smoke only
- default runtime `{1,2}` smoke status
- runtime-like certified-small status

This summary may be implemented as a structured dict, JSON artifact, or markdown block produced by the tests/report, but it must be explicit enough that later readers can see **what is certified and what is only smoke-tested**.

### E. Contract preservation
The following must remain true:
- `critical_buses` is still required for disaster-objective-ready construction
- `critical_buses` is never inferred from `ambig.w`
- runtime selection remains selection-driven
- no raw CSV/JSON reads are added in model/solver layers
- the production first-stage objective boundary discipline remains:
  - use `construction_cost_value` when a pure first-stage contribution is needed

### F. Audit discipline
- Keep stable artifact paths for:
  - at least one certified runtime-like master LP before/after cut addition
  - at least one iteration-log JSON file
- Keep the implementation auditable and easy to inspect.

---

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/oracle/test_disaster_exact_oracle.py -q`
- `pytest tests/integration/test_disaster_exact_crosscheck.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest tests/integration/test_readiness_matrix.py -q`
- `pytest tests/integration/test_benders_vs_oracle.py -q`
- `pytest tests/integration/test_epsilon_certificate.py -q`
- `pytest tests/integration/test_benders_runtime_fixture_smoke.py -q`
- `pytest -q`

---

## Deliverables

You must return:

1. implementation in the allowed files
2. required tests
3. `docs/reports/round_10_report.md`
4. stable artifact path(s) for:
   - at least one certified runtime-like master LP before/after cut addition
   - at least one certified runtime-like iteration log JSON
5. a concise readiness summary containing:
   - what is now independently exact on tiny cases
   - what is epsilon-certified
   - what remains smoke-only
6. if any narrow bug-fix files were changed:
   - the exact files changed
   - the exact bug
   - which new Round 10 test exposed it

---

## Report format

Write `docs/reports/round_10_report.md` with at least:

```md
# Round 10 Report

## Files changed
- ...

## Design decisions
- ...

## Independent disaster exact oracle
- ...

## Tiny cross-check results
- ...

## Certified runtime-like run
- ...

## Readiness matrix
- ...

## Tests run
- command
- result

## Audit artifacts
- LP dump paths
- iteration-log paths
- certification summary

## Known limitations
- ...

## Open issues for next round
- ...
```

Model/solver rounds should also include:
- any numerical tolerances used
- whether any narrow bug fix was needed
- whether the certified runtime-like run is `exact` or `epsilon`
- an explicit statement of whether the default runtime `{1,2}` fixture is still smoke-only
