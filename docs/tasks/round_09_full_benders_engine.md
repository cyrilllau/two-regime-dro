# Round 09 - Full Benders Engine

## Objective

Implement the production multi-iteration Benders-like engine on top of the already validated:
- fixed-cut master problem
- separation MILP
- structured cut factory
- audit/log surfaces

This round has one bounded proof obligation:

> the production engine must execute the paper-faithful iterative loop, maintain correct lower-bound / violation / cut bookkeeping, and agree with a brute-force oracle on tiny cases.

This round must:
- implement the iterative driver corresponding to Algorithm 1
- preserve the existing structured cut interface
- preserve the fixed first-stage and line ordering
- certify stopping either by exact separation or by an epsilon certificate
- remain auditable and regression-testable on tiny cases

This round must not:
- reopen the stable spec
- change raw-data semantics
- redesign validated model mathematics
- silently relax any existing freeze-contract rule

## Allowed files to create/update

Primary implementation files:
- `src/production/benders_engine.py`
- `src/audit/iteration_log.py`
- `src/audit/cut_audit.py`

Primary test / oracle files:
- `src/reference/brute_force_stage1.py`
- `tests/integration/test_benders_vs_oracle.py`
- `tests/integration/test_epsilon_certificate.py`
- `tests/integration/test_benders_runtime_fixture_smoke.py`
- `tests/fixtures/benders_*.yaml`

Round report:
- `docs/reports/round_09_report.md`

### Narrow bug-fix permission (only if required by the new Round 09 tests)

The following files may be edited **only** if the new Round 09 tests expose a localized bug that blocks the bounded proof obligation:
- `src/production/master_problem.py`
- `src/production/cut_factory.py`
- `src/production/separation_milp.py`
- `src/audit/residual_report.py`
- `src/audit/model_dump.py`

If any of these narrow-fix files are changed:
- keep the change minimal
- explain exactly why it was needed
- show which new Round 09 test exposed it
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
- `src/production/disaster_dual_paper.py`
- `src/production/first_stage.py`
- `src/production/normal_block.py`

Do not implement in this round:
- no scenario-reduction workflow
- no cut-selection/deletion policy
- no stabilized / level Benders variant
- no end-to-end paper-case replication workflow
- no semantic fallback from `ambig.w` to `critical_buses`

## Required behavior

### A. Full multi-iteration Benders driver
Implement a production driver that follows the paper-faithful loop:
1. solve fixed-cut master problem
2. read `x_k`, `alpha_k`, `lambda_k`
3. derive / obtain usable `omega` bounds
4. solve separation MILP
5. if certified, stop
6. otherwise generate one structured real cut from the validated paper-dual chain
7. add the cut to the master
8. re-solve and continue

Requirements:
- support more than one iteration
- preserve cut IDs across iterations
- preserve the structured cut representation
- keep first-stage ordering exactly aligned with `instance.sets.buses`
- keep line ordering exactly aligned with canonical stable line ordering
- do not flatten `gamma` or `phi` into opaque vectors

### B. Iteration bookkeeping
Add explicit iteration bookkeeping with at least:
- iteration id
- pre-cut / post-cut master objective (or lower bound sequence)
- separation violation value
- selected outage vector `delta_k`
- generated cut id
- total cut count
- runtime timing split for:
  - master solve
  - separation solve
  - cut generation
- stop reason:
  - `certified_exact`
  - `certified_epsilon`
  - `max_iterations`

Requirements:
- lower-bound sequence must be auditable round-by-round
- cut-count sequence must be auditable round-by-round
- each generated cut must be linked to the iteration that created it

### C. Epsilon-certificate logic
Implement explicit epsilon-certificate support.

Requirements:
- accept `epsilon_cert` as a driver parameter
- if separation returns `violation <= epsilon_cert`, stop and mark the solution certified
- expose a certificate summary showing:
  - final RMP value `z_RMP`
  - final violation upper bound
  - implied sampled-problem gap bound `pi_f * epsilon_cert`
- if `epsilon_cert = 0`, exact certification path must remain available

### D. Brute-force tiny oracle for end-to-end validation
Implement a tiny brute-force oracle path for very small instances.

Requirements:
- enumerate a small bounded first-stage choice set on toy fixtures
- for each enumerated first-stage plan, evaluate the sampled problem exactly on the tiny instance using:
  - explicit normal-side solve
  - exact disaster-side oracle path already available from the validated reference / separation chain
- return at least:
  - optimal objective
  - one optimal first-stage plan
- this oracle may be slow, but it must be transparent and only intended for tiny cases

### E. Required integration tests
Add the following required tests.

1. **Benders vs brute-force tiny end-to-end**
   - use at least one tiny case where the full sampled problem is small enough for brute-force comparison
   - require:
     - same optimal objective within tolerance
     - same first-stage plan where identifiable
     - final stop reason is certified

2. **Monotone cut accumulation / lower-bound trace**
   - on at least one tiny case with more than one generated cut, require:
     - lower bound is nondecreasing across iterations
     - cut count is nondecreasing
     - each added cut remains present in later iterations

3. **Two generated real cuts in one run**
   - require at least one tiny case where the engine adds at least two generated real cuts in sequence
   - verify:
     - cut IDs remain distinct
     - `s_r` and `u_{r,l}` remain indexed by cut id after multiple additions
     - no indexing drift appears in the post-cut master

4. **Epsilon-certificate regression**
   - on a tiny case, run once with `epsilon_cert = 0` and once with a positive epsilon
   - verify:
     - the positive-epsilon run stops no later than the exact run
     - the reported certificate gap bound equals `pi_f * epsilon_cert`
     - the returned result explicitly records the stop reason and certificate fields

5. **Runtime-fixture Benders smoke**
   - add one canonical-runtime smoke run under the raw-read guard
   - this is only a smoke/integration check, not a claim of paper-case optimality
   - it must:
     - complete at least one generated-cut iteration
     - produce an iteration log
     - preserve raw-read isolation in the production layer

### F. Objective-boundary discipline
The engine must preserve the existing first-stage API discipline.

Requirements:
- when reconstructing total objective terms, use pure `construction_cost_value` for the first-stage contribution
- do not reuse the attached `objective_value` as the pure construction term
- retain the existing `objective_is_pure_construction` semantics
- add at least one regression confirming this remains true after multiple iterations

### G. Contract preservation
The following must remain true:
- `critical_buses` is still required for disaster-objective-ready construction
- `critical_buses` is never inferred from `ambig.w`
- default runtime selection remains selection-driven, not raw-package-equality-driven
- the production model layer still consumes only canonical objects
- no raw CSV/JSON reads are introduced in production model build/solve

### H. Solver / audit discipline
- Use `gurobipy` for LP/MILP models in this round.
- Keep the existing simplex-compatible cut-factory path.
- Support stable dump / audit paths for:
  - at least one iteration-0 master LP
  - at least one post-cut master LP
  - at least one iteration log artifact
- Keep the implementation auditable and easy to inspect.

## Acceptance tests

At minimum, the following must pass:

- `pytest tests/integration/test_benders_vs_oracle.py -q`
- `pytest tests/integration/test_epsilon_certificate.py -q`
- `pytest tests/integration/test_benders_runtime_fixture_smoke.py -q`
- `pytest tests/oracle/test_cut_factory.py -q`
- `pytest tests/oracle/test_separation_exactness.py -q`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
- `pytest tests/integration/test_single_iteration_cut_addition.py -q`
- `pytest -q`

## Deliverables

You must return:

1. implementation in the allowed files
2. required tests
3. `docs/reports/round_09_report.md`
4. stable LP dump path(s) for:
   - at least one master before any generated cut
   - at least one master after at least one generated cut
5. stable iteration-log artifact path(s)
6. concise Benders diagnostics including:
   - final stop reason
   - iteration count
   - final lower bound sequence
   - final cut count sequence
   - whether at least two generated real cuts were added in any tiny regression
7. if any narrow bug-fix files were changed:
   - the exact files changed
   - the exact bug
   - which new Round 09 test exposed it

## Report format

Write `docs/reports/round_09_report.md` with at least:

```md
# Round 09 Report

## Files changed
- ...

## Design decisions
- ...

## Benders engine design
- ...

## Iteration bookkeeping
- ...

## Benders vs brute-force comparisons
- ...

## Epsilon-certificate checks
- ...

## Tests run
- command
- result

## Audit artifacts
- LP dump paths
- iteration-log paths
- lower-bound / violation summaries

## Known limitations
- ...

## Open issues for next round
- ...
```

Model rounds should also include:
- numerical tolerances used for objective and certificate comparisons
- whether at least one tiny run added two generated real cuts
- whether any runtime smoke run completed more than one iteration
- whether any narrow bug fix was needed
