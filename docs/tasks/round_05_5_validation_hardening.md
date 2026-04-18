# Round 05.5 - Separation Validation Hardening

## Objective

Do **not** proceed to first-stage / normal-block work yet.

This round has one bounded objective:

> harden the already-implemented separation layer by adding coefficient-level and edge-case validation, and apply only minimal localized fixes if the new validation reveals a real bug.

Round 05 established tiny-case exactness and runtime-fixture smoke behavior. Round 05.5 exists to reduce the risk of carrying a subtle separation/sign/bounds bug into later production rounds.

## Allowed files to create/update

Primary validation files:
- `tests/unit/test_separation_coeffs.py`
- `tests/oracle/test_budget_support_edge_cases.py`
- `tests/oracle/test_separation_edge_cases.py`
- `tests/integration/test_separation_runtime_bounds.py`
- `docs/reports/round_05_5_report.md`

Primary implementation files (only if required by new tests):
- `src/production/separation_milp.py`
- `src/reference/outage_enumerator.py`
- `src/reference/dro_outer_lp_oracle.py`
- `src/audit/residual_report.py`

Narrow bug-fix permission (only if a new validation test exposes a localized bug):
- `src/production/disaster_dual_paper.py`

If any implementation file is changed:
- keep the change minimal
- explain exactly why it was needed
- show which new Round 05.5 test exposed it
- do not widen scope beyond the localized fix

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/disaster_primal_ref.py`
- `src/reference/lp_canonicalizer.py`
- `src/reference/disaster_dual_auto.py`
- `src/reference/kkt_checks.py`
- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/production/master_problem.py`
- `src/production/cut_factory.py`
- `src/production/benders_engine.py`

Also forbidden in this round:
- no new planning model logic
- no cut generation
- no master problem
- no Benders driver
- no change to runtime selection semantics
- no fallback from `ambig.w` to `critical_buses`

## Required behavior

### A. Coefficient / model-shape validation for separation MILP
Add direct tests that the separation model structure is correct, not just that outcomes match on examples.

At minimum validate:
1. `delta` variables are binary
2. there is exactly one outage-budget row enforcing `1^T delta <= K`
3. for each line, the McCormick linearization for `tau_l = delta_l * omega_l` contributes the expected four inequalities
4. the model contains explicit `omega` and `tau` variables for each line
5. the fixed-`(x, alpha, lambda)` objective uses the expected sign pattern for:
   - `beta`
   - `- gamma^T x`
   - `+ phi^T delta`
   - `- lambda^T delta`
   - `- alpha`

These tests may inspect named constraints, variable types, and objective coefficients directly.

### B. Budget-support edge cases
Add edge-case tests for the support-function oracle.

At minimum include:
1. `K = 0` => optimal support value is `0` and the chosen outage vector is all-zero
2. `K = |L|` => support value equals the sum of positive components of `v`
3. all components of `v` nonpositive => support value is `0`
4. at least one tie case where multiple outage patterns are optimal
   - compare objective value exactly
   - do **not** require a unique outage identity

### C. Separation edge cases
Add edge-case tests for the separation MILP itself.

At minimum include:
1. a `K = 0` separation case
2. a tie-optimum separation case with multiple best outage patterns
3. a case where exact tiny bounds and inflated valid bounds produce the same optimal violation value

### D. Runtime bound validation
The runtime smoke path currently uses externally supplied conservative `omega` bounds.
Add validation that:
1. the solved runtime-smoke `omega` values lie within the supplied bounds
2. the slack-to-bound information is surfaced clearly in diagnostics
3. no exactness claim is made for runtime-smoke bounds beyond what is actually tested

### E. Group/sign propagation hardening
Because Round 04 exposed a sign bug in upper-bound-derived dual groups, add one explicit regression check that isolates sign propagation into the separation objective.

A good minimal target is:
- a tiny case where the objective contribution from outage-dependent `phi` terms is isolated as much as possible
- and one case where `beta/gamma/phi` blockwise reconstruction is checked again under the new validation harness

### F. Contract preservation
The following must remain true:
- `critical_buses` is still required for disaster-objective-ready model construction
- `critical_buses` is never inferred from `ambig.w`
- disaster math remains active-power-only
- Round 02 disaster primal math remains unchanged
- no production logic beyond `separation_milp.py` is widened in this round

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/unit/test_separation_coeffs.py -q`
- `pytest tests/oracle/test_budget_support_edge_cases.py -q`
- `pytest tests/oracle/test_separation_edge_cases.py -q`
- `pytest tests/oracle/test_separation_exactness.py -q`
- `pytest tests/integration/test_separation_runtime_bounds.py -q`
- `pytest tests/integration/test_separation_runtime_fixture.py -q`
- `pytest -q`

## Deliverables

You must return:

1. implementation / validation code in the allowed files
2. required tests
3. `docs/reports/round_05_5_report.md`
4. stable LP dump path(s) for at least one inspected separation model
5. concise validation diagnostics including:
   - coefficient/model-shape check summary
   - edge-case outcomes
   - runtime-bound slack summary
6. if any implementation file was changed:
   - the exact files changed
   - the exact bug
   - which new test exposed it

## Report format

Write `docs/reports/round_05_5_report.md` with at least:

```md
# Round 05.5 Report

## Files changed
- ...

## Validation goals
- ...

## Design decisions
- ...

## Coefficient/model-shape checks
- ...

## Edge-case checks
- ...

## Runtime-bound checks
- ...

## Tests run
- command
- result

## Audit artifacts
- LP dump paths
- runtime-bound slack summary
- any tie-case notes

## Known limitations
- ...

## Open issues for next round
- ...
```

Model validation rounds should also include:
- any numerical tolerance used
- whether any localized bug fix was needed
- whether the new checks changed acceptance confidence for moving to Round 06
