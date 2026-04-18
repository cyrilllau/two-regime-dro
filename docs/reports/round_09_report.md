# Round 09 Report

## Files changed
- `src/production/benders_engine.py`
- `src/audit/iteration_log.py`
- `src/reference/brute_force_stage1.py`
- `tests/integration/test_benders_vs_oracle.py`
- `tests/integration/test_epsilon_certificate.py`
- `tests/integration/test_benders_runtime_fixture_smoke.py`
- `tests/fixtures/benders_two_cut_unique_plan.yaml`

## Design decisions
- Implemented a bounded full-iteration production Benders driver that reuses the validated fixed-cut master, separation MILP, and paper-dual cut factory without reopening any model math.
- Kept cut state structured throughout the loop: every generated cut remains a `RestrictedMasterCut` with blockwise `beta`, `gamma_*`, and `phi` maps.
- Added explicit iteration-log dataclasses and a stable JSON artifact so lower-bound traces, cut counts, selected outages, generated cut IDs, timing splits, and stop reasons are auditable after the run.
- Implemented a tiny brute-force stage-1 oracle that evaluates bounded candidate plans exactly by combining:
  - pure first-stage construction cost from the production first-stage block
  - explicit normal-scenario solves from the production normal block
  - exact disaster DRO evaluation from outage enumeration plus paper-dual sample solves plus the outer-DRO LP oracle

## Benders iteration flow
- Solve the fixed-cut master.
- Read the first-stage plan, `alpha`, and `lambda`.
- Derive usable `omega` bounds from the validated single-line oracle if none are supplied.
- Solve the separation MILP at the current master point.
- If the separation violation is at most `epsilon_cert`, stop with an exact or epsilon certificate.
- Otherwise generate one structured real cut from the simplex-solved paper-dual chain at the selected outage.
- Append the cut, re-solve the master, record the updated lower bound, and continue until certification or `max_iterations`.

## Brute-force oracle comparison
- The tiny regression fixture `benders_two_cut_unique_plan.yaml` enumerates six bounded first-stage plans.
- The brute-force oracle evaluates each plan exactly and returns the best total objective plus one optimal plan.
- The production Benders engine matches the brute-force optimum on this fixture and identifies the same unique best plan (`bus3_10`).

## Epsilon-certificate logic
- The driver accepts `epsilon_cert`.
- It stops with:
  - `certified_exact` when `violation <= 0`
  - `certified_epsilon` when `0 < violation <= epsilon_cert`
- The exposed certificate summary contains:
  - final `z_RMP`
  - final violation upper bound
  - sampled-problem gap bound `pi_f * epsilon_cert`
- The epsilon regression uses the same tiny case with `epsilon_cert = 500.0`, which certifies after the first master/separation pair and reports a gap bound of `450.0`.

## Lower-bound and cut-count bookkeeping
- `lower_bound_sequence` records the solved pre-cut master objective at each iteration.
- `cut_count_sequence` records the active master cut count at each solved master.
- Each `BendersIterationRecord` links the generated cut ID, selected outage, cut counts before/after, and timing split.
- The two-cut tiny regression confirms:
  - nondecreasing lower bounds
  - nondecreasing cut counts
  - no loss of previously added cuts in later masters
  - stable per-cut `s_r` and per-cut-per-line `u_{r,l}` indexing after multiple cut additions

## Required hardening checks
- Benders vs brute-force tiny end-to-end: added and passing.
- Monotone cut accumulation / lower-bound trace: added and passing on the two-cut tiny case.
- Two generated real cuts in one run: added and passing on the same tiny case.
- Epsilon-certificate regression: added and passing.
- Runtime-fixture Benders smoke under the raw-read guard: added and passing.

## Test commands
- `pytest tests/integration/test_benders_vs_oracle.py -q`
- `pytest tests/integration/test_epsilon_certificate.py -q`
- `pytest tests/integration/test_benders_runtime_fixture_smoke.py -q`
- `pytest tests/oracle/test_cut_factory.py -q`
- `pytest tests/oracle/test_separation_exactness.py -q`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
- `pytest tests/integration/test_single_iteration_cut_addition.py -q`
- `pytest -q`

## Test outcomes
- `pytest tests/integration/test_benders_vs_oracle.py -q` -> `2 passed in 0.12s`
- `pytest tests/integration/test_epsilon_certificate.py -q` -> `1 passed in 0.07s`
- `pytest tests/integration/test_benders_runtime_fixture_smoke.py -q` -> `1 passed in 5.48s`
- `pytest tests/oracle/test_cut_factory.py -q` -> `1 passed in 0.05s`
- `pytest tests/oracle/test_separation_exactness.py -q` -> `5 passed in 0.07s`
- `pytest tests/oracle/test_disaster_dual_paper.py -q` -> `5 passed in 0.07s`
- `pytest tests/integration/test_single_iteration_cut_addition.py -q` -> `3 passed in 0.07s`
- `pytest -q` -> `137 passed in 20.60s`

## Stable audit artifacts
- Tiny master before any generated cut: `/tmp/round_09_tiny_master_before_cut.lp`
- Tiny master after at least one generated cut: `/tmp/round_09_tiny_master_after_cut.lp`
- Runtime master before any generated cut: `/tmp/round_09_runtime_master_before_cut.lp`
- Runtime master after at least one generated cut: `/tmp/round_09_runtime_master_after_cut.lp`
- Tiny iteration log: `/tmp/round_09_tiny_iteration_log.json`
- Runtime iteration log: `/tmp/round_09_runtime_iteration_log.json`

## Observed diagnostics from the tiny exact regression
- Final stop reason: `certified_exact`
- Iteration count: `3`
- Lower-bound trace: `(9.999999999999998, 70.0, 71.0)`
- Cut-count trace: `(1, 2, 3)`
- Generated real cuts added: `2`
- Final exact objective: `71.0`
- Final first-stage plan: open bus `3` with `10` slow chargers
- Generated cut IDs: `generated_cut_001`, `generated_cut_002`

## Observed runtime smoke diagnostics
- Stop reason: `max_iterations`
- Iteration count: `2`
- Lower-bound trace: `(24916711.48002533, 24916798.832808632)`
- Cut-count trace: `(1, 2)`
- Generated real cuts added: `1`
- Final master objective: `24916798.832808632`
- Final violation upper bound: `10529.50500000018`
- Final `lambda^T FP`: `873.5278330225372`
- Objective reconstruction gap: `2.2351741790771484e-08`

## Narrow bug fixes
- None required in the Round 09 narrow-fix permission files.
- One localized implementation repair inside an allowed Round 09 primary file was required before test execution:
  - `src/reference/brute_force_stage1.py` now imports `RuntimeDataValidationError`, which the bounded-candidate guard already referenced.

## Open notes
- The runtime smoke is intentionally bounded. It validates multi-iteration integration, audit artifacts, raw-read isolation, and generated-cut carryover, but does not claim paper-scale optimality.
