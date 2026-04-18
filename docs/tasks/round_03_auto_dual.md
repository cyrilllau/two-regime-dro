# Round 03 - Auto Dual + KKT Checks for Disaster Reference LP

## Objective
Implement a mechanically derived auto dual for the fixed-`(x, delta, b)` disaster-stage reference LP, together with primal/dual/KKT validation on hand-checkable toy cases and one canonical runtime-fixture case.

This round has one bounded proof obligation:

> prove that the current disaster primal reference LP can be canonicalized consistently, dualized mechanically, and validated through strong duality and KKT-style checks.

This round also strengthens the audit path by extending the residual report to expose named slack / residual information for the disaster-stage constraints needed for dual debugging.

## Allowed files to create/update
- `src/reference/disaster_primal_ref.py`
- `src/reference/lp_canonicalizer.py`
- `src/reference/disaster_dual_auto.py`
- `src/reference/kkt_checks.py`
- `src/audit/residual_report.py`
- `tests/oracle/test_disaster_primal_ref.py`
- `tests/oracle/test_disaster_primal_dual.py`
- `tests/integration/test_disaster_primal_dual_runtime_fixture.py`
- `tests/fixtures/disaster_primal_mixed_slow_fast.yaml`
- `docs/reports/round_03_report.md`

## Do not modify
- `docs/spec/*`
- `docs/tasks/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/production/*`
- `src/audit/model_dump.py`
- `tests/integration/test_instance_loading.py`
- `tests/integration/test_disaster_primal_runtime_fixture.py`
- any previous round report except by reading it

## Required behavior
1. **Keep the primal math unchanged.**
   - The disaster primal reference LP from Round 02 remains the mathematical source.
   - Do not change the Eq. (26)–(32) semantics.
   - Keep the model active-power-only.

2. **Build a mechanical canonicalization layer for the current disaster primal reference LP.**
   - Canonicalize the fixed-`(x, delta, b)` LP into an explicit matrix/vector representation suitable for auto dual generation.
   - Use a documented sign convention.
   - If free primal variables are present (for example line-flow variables that can be positive or negative), handle them through a standard, explicit transformation such as plus/minus splitting.
   - The transformation must preserve primal objective value and feasibility semantics.

3. **Build the auto dual mechanically from the canonicalized primal.**
   - `src/reference/disaster_dual_auto.py` must derive the dual from the canonical LP representation rather than hard-coding paper dual coefficients by hand.
   - This round is only for the mechanically derived reference dual, not the hand-coded paper dual.

4. **Add KKT / duality checks.**
   - Provide checks for:
     - primal feasibility
     - dual feasibility
     - strong duality (objective equality within tolerance)
     - complementary-slackness-style residuals or an equivalent reduced-cost/slack residual check
   - These checks must operate on the primal/auto-dual pair for fixed `x, delta, b`.

5. **Strengthen the disaster residual audit.**
   - Extend `src/audit/residual_report.py` so the report exposes named residual/slack information for:
     - Eq. (27) active-power balance
     - Eq. (28) regional V2G availability limits
     - Eq. (29) station discharge capacity limits
     - Eq. (30) discharge assignment–siting linkage
     - Eq. (31) load shedding bounds
     - Eq. (32) failed-line / outage-dependent capacity
   - The report may summarize maxima, but the labels must make it possible to tell which equation group is being audited.

6. **Toy-case coverage.**
   Use the Round 02 toy cases and add one mixed slow/fast case.
   At minimum, primal-vs-auto-dual validation must cover:
   - zero-demand sanity
   - simple shortage
   - critical-priority case
   - failed-line zero-flow case
   - mixed slow/fast discharge case

7. **Runtime-fixture integration.**
   - Add one integration test showing that the auto dual can be built and solved on the Round 01.5 canonical runtime fixture using an explicit test-only `critical_buses` override.
   - This integration test is not required to have a hand-derived objective value, but it must verify primal and auto-dual objective agreement within tolerance and produce audit-friendly residual/KKT summaries.

8. **Readiness gating stays intact.**
   - `critical_buses` must still never be inferred from `ambig.w`.
   - Missing disaster-objective-ready `critical_buses` must still fail clearly before model build / solve.

9. **No production or decomposition logic in this round.**
   - Do not implement hand-coded paper dual.
   - Do not implement separation MILP.
   - Do not implement cut generation.
   - Do not implement master problem or Benders logic.

10. **Audit artifacts.**
    - Make it easy to dump both primal and auto-dual LPs for at least one manual audit run.
    - The round report must include at least one stable primal LP dump path and one stable dual LP dump path, or explicitly state the stable paths used during manual verification.

## Acceptance tests
Run at least the following and report the outcomes:

1. `pytest tests/oracle/test_disaster_primal_ref.py -q`
2. `pytest tests/oracle/test_disaster_primal_dual.py -q`
3. `pytest tests/integration/test_disaster_primal_runtime_fixture.py -q`
4. `pytest tests/integration/test_disaster_primal_dual_runtime_fixture.py -q`
5. `pytest -q`

The new tests must verify all of the following:
- primal objective equals auto-dual objective within a tight numerical tolerance on every toy case
- the mixed slow/fast toy case passes
- missing `critical_buses` still fails clearly
- the residual report exposes named audit entries for Eq. (27)–(32)
- the runtime-fixture integration test passes with an explicit test-only `critical_buses` override

## Deliverables
- implementation of the auto-dual reference path
- tests
- `docs/reports/round_03_report.md`
- primal/dual LP dump path(s) used in manual audit
- primal/dual objective comparison summary
- KKT / residual summary

## Report format
The report must include at least the following sections:

```md
# Round 03 Report

## Files changed
- ...

## Design decisions
- ...

## Canonicalization conventions
- variable-sign convention
- free-variable handling
- primal-to-dual mapping note

## Tests run
- command
- result

## Objective comparisons
- toy case name
- primal objective
- auto-dual objective
- absolute gap

## KKT / residual summary
- strongest residual checks performed
- worst observed values

## Audit artifacts
- primal LP dump path(s)
- auto-dual LP dump path(s)

## Known limitations
- ...

## Open issues for next round
- ...
```
