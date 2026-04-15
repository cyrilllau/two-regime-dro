# Round 02 - Disaster Primal Reference

## Objective
Implement an auditable fixed-`(x, delta, b)` disaster-stage primal LP reference model for the paper's disaster recourse, together with toy-case tests and minimal audit helpers.

This round has exactly one bounded proof obligation:

> For a fixed first-stage plan `x`, a fixed outage vector `delta`, and a fixed selected disaster scenario `b`, the disaster primal LP corresponding to Eq. (26)–(32) is built correctly, solves correctly, and behaves correctly on hand-checkable toy cases.

This round is **not** allowed to implement:
- auto dualization
- hand-coded paper dual
- separation MILP
- cut generation
- master problem logic
- any production-track optimization logic

---

## Allowed files to create/update
- `src/reference/disaster_primal_ref.py`
- `src/audit/model_dump.py`
- `src/audit/residual_report.py`
- `tests/oracle/test_disaster_primal_ref.py`
- `tests/fixtures/disaster_primal_zero.yaml`
- `tests/fixtures/disaster_primal_shortage.yaml`
- `tests/fixtures/disaster_primal_critical_priority.yaml`
- `tests/fixtures/disaster_primal_failed_line.yaml`
- `tests/integration/test_disaster_primal_runtime_fixture.py`
- `docs/reports/round_02_report.md`

If you absolutely need one tiny helper test fixture file beyond the list above, create **at most one** additional file under `tests/fixtures/` and document why in the round report.

---

## Do not modify
- `docs/spec/*`
- `docs/tasks/*`
- `src/instance/*`
- `src/contracts/*`
- `src/reference/lp_canonicalizer.py`
- `src/reference/disaster_dual_auto.py`
- `src/reference/kkt_checks.py`
- `src/reference/outage_enumerator.py`
- `src/reference/dro_outer_lp_oracle.py`
- `src/production/*`
- `data/*`
- `pyproject.toml`
- existing round reports other than `docs/reports/round_02_report.md`

---

## Required behavior

### 1. Implement only the fixed-outage disaster primal reference LP
The implemented model must correspond only to the disaster-stage primal recourse in Eq. (26)–(32), not to any dual, decomposition, or first-stage optimization logic.

It must accept as fixed inputs:
- a `CanonicalInstance`
- a fixed first-stage plan `x`
- a fixed outage vector `delta`
- one selected disaster scenario id `b`

The model is allowed to optimize only the disaster recourse variables.

### 2. Required equation coverage
Implement the disaster reference LP with a clear mapping to the paper equations:
- Eq. (26) disaster objective
- Eq. (27) disaster active-power balance
- Eq. (28) assignment discharging constraints
- Eq. (29) station discharge capacity limits
- Eq. (30) discharge assignment-siting linkage
- Eq. (31) load shedding bounds
- Eq. (32) outage-dependent line capacity

Use explicit equation-aware naming in variable/constraint labels wherever practical.

### 3. Disaster objective semantics must follow the freeze contract
The disaster objective must use `CLS_n` constructed from explicit `critical_buses`.

Rules:
- do **not** infer `critical_buses` from `ambig.w`
- do **not** use `ambig.w` as a substitute for `CLS_n`
- if the caller does not provide disaster-objective-ready critical-bus information, the reference model builder or solve entry point must raise a clear error before model build

This round may use explicit toy-case critical-bus fixtures for validation.
It does **not** need to solve the real runtime package without an explicit critical-bus input.

### 4. Disaster model scope must match the paper, not add extra physics
The disaster reference model must remain a linear active-power-only formulation consistent with the paper.

Required restrictions:
- no disaster reactive-power variables
- no disaster voltage variables
- no AC nonlinearities
- no additional substation-purchase variable

Use the paper-consistent interpretation that disaster-stage supply from the root is represented implicitly through intact branch flows from the root, not through a separate disaster substation decision variable.

### 5. First-stage plan input must be explicit and fixed
Because the first-stage production model does not exist yet, define a small local reference-track representation for fixed `x`, for example a dataclass or equivalent structure containing:
- siting `z[n]`
- slow chargers `n_sl[n]`
- fast chargers `n_fa[n]`

Requirements:
- validate dimensions and bus ids
- validate nonnegativity
- validate that no chargers are installed where `z[n] = 0`
- keep this representation local to this round unless absolutely necessary

### 6. Outage vector input must be explicit and validated
The reference model must accept a fixed outage vector aligned with the canonical line set.

Requirements:
- validate length / indexing consistency with canonical lines
- validate binary values in `{0,1}`
- use Eq. (32) so that a failed line has zero flow capacity

### 7. Provide a small auditable public API
Implement a minimal public API in `src/reference/disaster_primal_ref.py` that is easy to test and reuse in Round 03.

Expected functions or equivalent:
- a builder for the disaster primal reference model
- a solver convenience function
- a structured solution extractor

The solved result object should make it easy to inspect at least:
- objective value
- load shedding by `(ts, n)`
- discharge assignment by `(ts, o, n)` for slow/fast
- line flows by `(ts, line)`
- model status

### 8. Add minimal audit helpers
Use the allowed audit files to support this round.

Required capabilities:
- LP dump for the disaster primal reference model
- a residual summary that can report at least:
  - max bound violation
  - max equality residual for active-power balance
  - any failed-line flow violation under Eq. (32)

The audit helpers may be small and purpose-built for this round.
They do not need to be a full final audit framework.

### 9. Add toy cases with hand-checkable expectations
Add toy-case tests that verify the disaster primal behaves sensibly.

At minimum, cover the following:

#### Case A: Zero-demand sanity
Expected behavior:
- zero load
- zero V2G needed
- optimal objective is zero
- all load shedding and flows are zero

#### Case B: Simple shortage case
Expected behavior:
- one node has positive load
- available V2G is insufficient
- objective equals shed load times the correct `CLS_n`

#### Case C: Critical-priority case
Expected behavior:
- limited V2G cannot serve all load
- at least one node is critical and one is noncritical
- with `CLS_critical > CLS_noncritical`, the optimal solution preserves critical load before noncritical load whenever network feasibility allows

#### Case D: Failed-line case
Expected behavior:
- a selected line is failed in `delta`
- solved flow on that line is exactly zero up to solver tolerance

### 10. Add one explicit readiness-gating test
Add a test showing that disaster-objective construction fails clearly when `critical_buses` is missing.

This is required because the freeze contract says `critical_buses` remains external input and may not be inferred.

### 11. Add one runtime-fixture integration test
Add one integration test showing that the reference model can consume the existing canonical runtime fixture machinery introduced in Round 01.5.

Requirements:
- load the runtime package through the current canonical instance path
- use default scenario selection `{1,2}`
- provide an explicit test-only `critical_buses` override/config
- build and solve the disaster primal reference model for one selected disaster scenario and one simple outage vector

This test does **not** need a hand-derived objective value.
It only needs to show that the model consumes canonical objects correctly and solves without violating the round contract.

### 12. Keep reference and production responsibilities separate
This round must not touch or implement any of the following:
- auto dualization
- paper dual
- separation
- cut logic
- Benders iteration

If you feel tempted to add those pieces, stop and leave them for later rounds.

---

## Acceptance tests
Run all of the following and report exact outcomes:

1. `pytest tests/oracle/test_disaster_primal_ref.py -q`
2. `pytest tests/integration/test_disaster_primal_runtime_fixture.py -q`
3. `pytest tests/integration/test_instance_loading.py -q`
4. `pytest -q`

In addition, the round is accepted only if all of the following are true:
- the toy cases pass
- missing `critical_buses` raises a clear error
- the runtime-fixture integration test passes without editing raw data under `data/`
- no files outside the allowed scope were modified
- no optimization logic outside the disaster primal reference LP was introduced

---

## Deliverables
- implementation of `src/reference/disaster_primal_ref.py`
- minimal audit helpers in the allowed audit files
- toy-case tests and any allowed fixtures
- one runtime-fixture integration test
- `docs/reports/round_02_report.md`

---

## Report format
Write `docs/reports/round_02_report.md` with at least these sections:

```md
# Round 02 Report

## Files changed
- ...

## Design decisions
- ...

## Equation coverage
- Eq. (26): ...
- Eq. (27): ...
- Eq. (28): ...
- Eq. (29): ...
- Eq. (30): ...
- Eq. (31): ...
- Eq. (32): ...

## Tests run
- command
- result

## Toy-case objective checks
- case name
- expected value / behavior
- observed value / behavior

## Audit artifacts
- LP dump path(s), if generated
- residual summary

## Known limitations
- ...

## Open issues for next round
- ...
```

Be conservative: if something remains uncertain, state it explicitly rather than claiming more than was proven in this round.
