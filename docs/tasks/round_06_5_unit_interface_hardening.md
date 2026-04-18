# Round 06.5 - Normal-block unit semantics + first-stage interface hardening

## Objective

Harden the Round 06 production first-stage / normal-block layer so that:

1. the Eq. (24) voltage-drop scaling is validated by direct analytic and coefficient-level tests,
2. the current runtime-data unit assumption (`R/X` in per-unit, powers in `kW/kvar`, implicit `S_base = 1 MVA`) is made explicit through regression checks,
3. the first-stage objective API is guarded so downstream rounds do not accidentally confuse the pure construction-cost value with a larger attached-model objective.

This round has one bounded proof obligation:

> the current Round 06 implementation must be made unit-auditable and interface-safe before later master/cut integration proceeds.

This round is validation/interface hardening only. It must not introduce new planning logic.

## Allowed files to create/update

Primary implementation files:
- `src/production/normal_block.py`
- `src/production/first_stage.py`
- `src/audit/residual_report.py`

Primary test files:
- `tests/unit/test_normal_block_unit_semantics.py`
- `tests/unit/test_first_stage_objective_api.py`
- `tests/oracle/test_normal_block_voltage_drop_analytic.py`
- `tests/integration/test_normal_block_runtime_unit_guard.py`

Fixture files for this round:
- `tests/fixtures/normal_block_voltage_drop_*.yaml`
- `tests/fixtures/normal_block_unit_guard_*.yaml`

Round report:
- `docs/reports/round_06_5_report.md`

### Narrow bug-fix permission (only if required by the new hardening tests)

The following files may be edited **only** if the new Round 06.5 tests reveal a localized bug:
- `tests/unit/test_normal_block_coeffs.py`
- `tests/integration/test_first_stage_normal_runtime_fixture.py`

If any of these narrow-fix files are changed:
- keep the change minimal
- explain exactly why it was needed
- show which new Round 06.5 test exposed it
- do not widen scope beyond the localized fix

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/*`
- `src/production/disaster_dual_paper.py`
- `src/production/separation_milp.py`
- `src/production/master_problem.py`
- `src/production/cut_factory.py`
- `src/production/benders_engine.py`

Also forbidden in this round:
- no new first-stage planning semantics
- no new normal-block physics beyond clarifying existing unit handling
- no disaster logic changes
- no master problem logic
- no Benders logic
- no semantic fallback from `ambig.w` to `critical_buses`
- no raw CSV/JSON reads in the production model layer

## Required behavior

### A. Analytic Eq. (24) voltage-drop regression
Add a hand-checkable tiny analytic test for Eq. (24):

- use a 2-bus / 1-line or similarly minimal radial case,
- choose explicit `R`, `X`, `P`, `Q`, and voltage values,
- verify the implemented row enforces
  `v_to - v_from + 2 R p + 2 X q = 0`
  under the **actual production unit conversion path**,
- make the expectation readable enough to audit by hand.

This must directly validate the current `1/1000`-style scaling assumption rather than only checking solver feasibility.

### B. Runtime-data unit-semantics guard
Add regression checks that make the current runtime-data unit assumption explicit:

- feeder `Rline/Xline` used in Eq. (24) are per-unit feeder coefficients,
- canonical active/reactive powers are supplied in `kW/kvar`,
- the current production Eq. (24) therefore uses an implicit `S_base = 1 MVA` conversion,
- the runtime fixture remains feasible and numerically consistent under this assumption.

This round does **not** reopen the stable spec. Instead, it must create tests/diagnostics that make the current assumption explicit and prevent accidental silent changes.

### C. First-stage objective API guard
Add regression checks so downstream rounds cannot accidentally misuse the first-stage solution object.

At minimum verify:
- when the first-stage block is solved by itself, `objective_value == construction_cost_value`,
- when the first-stage block is attached to a larger model, downstream code must rely on `construction_cost_value` when it needs the pure first-stage value,
- if the current API is ambiguous, tighten it conservatively within the allowed files and document the change.

### D. Direct coefficient / sign checks for the unit-sensitive rows
Add direct tests that inspect the Eq. (24) row coefficients/signs after model build, including the production scaling path.

At minimum check:
- coefficient on `v_to` is `+1`,
- coefficient on `v_from` is `-1`,
- coefficients on `p` and `q` include the expected `2R` and `2X` factors **with the implemented unit conversion**,
- the row sense is equality.

### E. Runtime smoke hardening
Add one integration test that builds the existing runtime first-stage + normal block and explicitly reports/validates:
- maximum Eq. (24) residual,
- the unit-conversion assumption in use,
- that no raw data files are read from the production model layer,
- that current runtime feasibility depends on the same tested conversion rule.

This remains a smoke/integration check, not an end-to-end optimality claim.

### F. Contract preservation
The following must remain true:
- `critical_buses` is still never inferred from `ambig.w`,
- no change to runtime-selection semantics from Round 01.5,
- no change to disaster/reference/dual/separation logic,
- no widening of production scope beyond the existing first-stage / normal-block layer.

### G. Solver / audit discipline
- Use `gurobipy` for model builds in this round.
- Support stable LP dump paths for:
  - at least one analytic/tiny normal-block LP,
  - at least one runtime first-stage + normal-block LP.
- Keep the implementation auditable and easy to inspect.

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/unit/test_normal_block_unit_semantics.py -q`
- `pytest tests/unit/test_first_stage_objective_api.py -q`
- `pytest tests/oracle/test_normal_block_voltage_drop_analytic.py -q`
- `pytest tests/integration/test_normal_block_runtime_unit_guard.py -q`
- `pytest tests/unit/test_normal_block_coeffs.py -q`
- `pytest tests/integration/test_first_stage_normal_runtime_fixture.py -q`
- `pytest -q`

## Deliverables

You must return:

1. implementation in the allowed files
2. required tests
3. `docs/reports/round_06_5_report.md`
4. stable LP dump path(s) for:
   - analytic tiny normal-block LP
   - runtime first-stage + normal-block LP
5. concise diagnostics including:
   - the explicit Eq. (24) unit/scaling assumption in force
   - the hand-checkable voltage-drop example and expected equality value
   - whether any narrow bug fix was required

## Report format

Write `docs/reports/round_06_5_report.md` with at least:

```md
# Round 06.5 Report

## Files changed
- ...

## Validation goals
- ...

## Design decisions
- ...

## Eq. (24) unit / scaling checks
- ...

## First-stage objective API checks
- ...

## Tests run
- command
- result

## Audit artifacts
- LP dump paths
- residual / scaling summary

## Known limitations
- ...

## Open issues for next round
- ...
```

Model-validation rounds should also include:
- numerical tolerance used for the analytic / residual checks
- whether any narrow bug fix was needed
- the exact runtime unit assumption being protected
