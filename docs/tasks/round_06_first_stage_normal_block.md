# Round 06 - First-stage builder + normal-operation block

## Objective

Implement the production-track first-stage builder and the production-track normal-operation block builder, with direct coefficient tests, hand-checkable toy cases, and one runtime-fixture smoke/integration test.

This round has one bounded proof obligation:

> Eq. (10)–(25) must be implemented in auditable production-track builders that can be solved independently of the future master problem and Benders loop.

This round must:
- implement the first-stage planning block
- implement the normal-operation explicit recourse block for a fixed sampled normal scenario
- preserve the validated disaster/reference/dual/separation chain from Rounds 02–05.5
- avoid any master-problem, cut-generation, or Benders-loop implementation

## Allowed files to create/update

Primary implementation files:
- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/audit/model_dump.py`
- `src/audit/residual_report.py`

Primary test files:
- `tests/unit/test_first_stage_coeffs.py`
- `tests/unit/test_normal_block_coeffs.py`
- `tests/oracle/test_first_stage_normal_toy_cases.py`
- `tests/integration/test_first_stage_normal_runtime_fixture.py`

Fixture files for this round:
- `tests/fixtures/normal_block_*.yaml`
- `tests/fixtures/first_stage_*.yaml`

Round report:
- `docs/reports/round_06_report.md`

### Narrow bug-fix permission (only if required by the new Round 06 tests)

The following files may be edited **only** if the new Round 06 tests expose a localized bug that blocks correct first-stage/normal-block implementation:
- `src/instance/network_topology.py`
- `src/instance/canonical_instance.py`
- `src/audit/model_dump.py`
- `src/audit/residual_report.py`

If any narrow-fix files are changed:
- keep the change minimal
- explain exactly why it was needed
- show which new Round 06 test exposed it
- do not widen scope beyond the localized fix

## Do not modify

Protected files and directories:
- `docs/spec/*`
- `data/*`
- `src/contracts/*`
- `src/reference/*`
- `src/production/disaster_dual_paper.py`
- `src/production/separation_milp.py`
- `src/production/cut_factory.py`
- `src/production/master_problem.py`
- `src/production/benders_engine.py`

Also forbidden in this round:
- no disaster-dual changes except authorized narrow-fix diagnostics outside protected files
- no master problem
- no cut generation
- no Benders logic
- no end-to-end planning solve over both normal and disaster terms
- no semantic fallback from `ambig.w` to `critical_buses`

## Required behavior

### A. First-stage production builder

Implement the first-stage block for Eq. (10)–(12).

Requirements:
1. create first-stage variables:
   - `z[n]` binary
   - `n_sl[n]` integer/nonnegative
   - `n_fa[n]` integer/nonnegative
2. implement:
   - Eq. (10) annualized construction cost
   - Eq. (11) minimum total-charger requirement
   - Eq. (12) installation bounds
3. respect the freeze contract:
   - root bus is not a candidate in the default mainline
   - candidate buses default to `all_except_root`
4. expose a stable production ordering / view for the first-stage vector blocks:
   - `z_by_bus`
   - `n_sl_by_bus`
   - `n_fa_by_bus`
   This ordering must be deterministic and suitable for later cut/master integration.
5. support LP/MPS dump for at least one first-stage-only toy build

### B. Normal-operation production block

Implement the explicit normal-operation recourse block for one fixed sampled normal scenario `a`.

Requirements:
1. keep the model linear and production-track oriented
2. use only canonical objects from the instance layer
3. implement Eq. (13)–(25):
   - transportation cost
   - unmet charging demand penalty
   - substation purchase cost
   - demand assignment balance
   - station capacity limits
   - assignment-siting linkage
   - active-power LinDistFlow balance
   - reactive-power LinDistFlow balance
   - substation definition
   - line flow limits
   - voltage-drop equation
   - voltage bounds
4. keep the normal block separate from any future master-problem wrapper
5. use the existing network topology orientation rather than rebuilding feeder logic ad hoc
6. keep power units and annualization semantics consistent with the freeze contract

### C. Explicit implementation choices for this round

For this round, use the following interpretation choices consistently and document them in the report:

1. unmet charging demand is aggregated by `(t, region, charger_type)`:
   - `u_sl[t,o]`
   - `u_fa[t,o]`
   rather than node-indexed unmet variables.
   This matches the demand-balance semantics of Eq. (17).

2. EV charging demand enters the normal active-power balance as active power only.
   Do not invent EV reactive demand unless the current canonical contract explicitly provides it.

3. `Ctrans` is time-indexed and must be read as a `t`-vector under the current freeze contract.

### D. Required toy cases

Add hand-checkable tests covering at least the following:

1. **T1 zero-demand sanity**
   - no charging demand
   - objective should prefer no construction
   - no assignment, no unmet, no substation purchase beyond base load

2. **T2 minimum-3-charger activation**
   - choose parameters so opening one station is cheaper than unmet penalty only if the minimum-3 rule activates
   - verify Eq. (11) actually binds

3. **T3 fast/slow separation sanity**
   - fast demand cannot be satisfied by slow charger capacity
   - verify slow/fast capacities remain separated

4. **T4 distance-preference transportation case**
   - two candidate stations with different distances
   - capacity-limited nearest station should fill first

5. **T5 network bottleneck under normal operation**
   - line capacity limits should force unmet demand even when charging capacity exists

Each toy case must include a short hand-checkable expectation in the test comments or report.

### E. Required coefficient/model-shape checks

Add direct coefficient tests for at least:

1. first-stage:
   - Eq. (10) objective coefficients
   - Eq. (11) min-charger activation row
   - Eq. (12) upper-bound linkage to `z`

2. normal block:
   - Eq. (17) charge-balance coefficients/signs
   - Eq. (18) station-capacity coefficients/signs
   - Eq. (19) assignment-siting linkage sign pattern
   - Eq. (20) active-power balance signs
   - Eq. (21) reactive-power balance signs
   - Eq. (22) substation definition sign pattern
   - Eq. (23) line-flow bounds present in both active and reactive parts
   - Eq. (24) voltage-drop row coefficients/signs
   - Eq. (25) voltage-bound rows present

These tests should directly inspect model rows/coefficients where practical rather than only inferring correctness from objective values.

### F. Runtime-fixture smoke / integration test

Add one integration test showing that:
- the production first-stage builder
- plus one fixed normal scenario block built from the canonical runtime fixture

can be built and solved together on the default selection-driven `{1,2}` runtime fixture.

This integration test is a smoke/integration check, not an end-to-end planning claim.

Requirements:
- use the canonical runtime fixture
- do not read raw CSV/JSON directly in the model layer
- dump at least one stable LP path for manual inspection
- provide a compact residual summary for the normal block:
  - charge-balance residual
  - active-power balance residual
  - reactive-power balance residual
  - voltage-bound violation
  - line-limit violation

### G. Contract preservation

The following must remain true:
- no use of `ambig.w` in the normal block
- no change to runtime selection semantics introduced in Round 01.5
- no change to disaster math or separation math
- no production logic beyond `first_stage.py` and `normal_block.py` plus audit helpers enters this round

### H. Solver / audit discipline

- Use `gurobipy` for LP/MILP models in this round.
- Support stable LP dump paths for:
  - at least one first-stage-only model
  - at least one first-stage + normal-block runtime integration model
- Keep implementation auditable and easy to inspect.

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/unit/test_first_stage_coeffs.py -q`
- `pytest tests/unit/test_normal_block_coeffs.py -q`
- `pytest tests/oracle/test_first_stage_normal_toy_cases.py -q`
- `pytest tests/integration/test_first_stage_normal_runtime_fixture.py -q`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
- `pytest tests/oracle/test_separation_exactness.py -q`
- `pytest -q`

## Deliverables

You must return:

1. implementation in the allowed files
2. required tests
3. `docs/reports/round_06_report.md`
4. stable LP dump path(s) for:
   - a first-stage toy model
   - a first-stage + normal-block runtime integration model
5. concise normal-block diagnostics including:
   - chosen first-stage values on at least one toy case
   - one toy-case objective comparison vs hand expectation
   - runtime smoke residual summary
6. if any narrow bug-fix files were changed:
   - exact files changed
   - exact bug
   - which new Round 06 test exposed it

## Report format

Write `docs/reports/round_06_report.md` with at least:

```md
# Round 06 Report

## Files changed
- ...

## Design decisions
- ...

## Equation coverage
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
- residual summaries
- notable first-stage solutions

## Known limitations
- ...

## Open issues for next round
- ...
```

Model rounds should also include:
- the production first-stage ordering convention
- any numerical tolerance used for hand-check comparisons
- whether any narrow bug fix was needed
- whether the T1–T5 toy checks all passed
