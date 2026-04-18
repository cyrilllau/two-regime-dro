# Round 10 Report

## Files changed
- `src/reference/disaster_exact_oracle.py`
- `src/reference/brute_force_stage1.py`
- `tests/oracle/test_disaster_exact_oracle.py`
- `tests/integration/test_disaster_exact_crosscheck.py`
- `tests/integration/test_benders_runtime_certification.py`
- `tests/integration/test_readiness_matrix.py`
- `tests/fixtures/disaster_exact_crosscheck_three_bus.yaml`
- `tests/fixtures/benders_runtime_certified_small.yaml`

## Design decisions
- Added a new independent disaster exact oracle that evaluates disaster recourse from the primal reference LP plus outage enumeration plus the outer-DRO LP oracle. It does not depend on the production paper-dual chain for the value being compared.
- Kept the existing Round 09 brute-force API stable by leaving `paper_dual` as the default disaster evaluation mode and adding an explicit `primal_exact` mode for Round 10 cross-checks.
- Chose a runtime-like certified-small path that still uses canonical instance loading on `data/runtime_12`, but with an explicit selection `{A=1, B=1}` and a fixed epsilon certificate threshold. This keeps the run production-like while remaining certifiable.

## Independent disaster exact oracle
- Path:
  - enumerate outages in `Omega(K)`
  - solve `disaster_primal_ref` for each fixed `(x, delta, b)`
  - average primal values samplewise into `value_by_pattern`
  - solve the outer-DRO LP oracle on those enumerated pattern values
- Exposed outputs:
  - exact weighted disaster objective
  - unweighted outer-DRO value
  - worst-case outage distribution by enumerated state
  - linewise outage marginals
  - samplewise primal values by outage pattern

## Tiny cross-check results
- Fixture: `tests/fixtures/disaster_exact_crosscheck_three_bus.yaml`
- The independent primal-based disaster oracle gives:
  - `value_by_pattern = {delta_00: 0.0, delta_10: 0.0, delta_01: 500.0}`
  - outer-DRO value `250.0`
  - weighted disaster term `225.0`
- The full exact Benders run, bounded brute-force with paper-dual disaster evaluation, and bounded brute-force with primal-exact disaster evaluation all agree on the same final optimal value:
  - optimal objective `71.0`
  - best plan `bus3_10`

## Certified runtime-like run
- Runtime source: `data/runtime_12`
- Canonical explicit selection:
  - normal scenarios `[1]`
  - disaster scenarios `[1]`
- Certification mode: `certified_epsilon`
- Epsilon used: `10200.0`
- Observed results:
  - iteration count `2`
  - lower-bound trace `(25010444.305336308, 25010527.830859635)`
  - cut-count trace `(1, 2)`
  - generated real cuts `1`
  - final violation upper bound `10180.110000000335`
  - sampled-problem gap bound `1020.0`
- Raw-read guard remained active during production build/solve.

## Readiness matrix
- Tiny independent disaster exact: exact
- Tiny end-to-end Benders vs brute-force: exact
- Tiny epsilon certificate: epsilon-certified
- Default runtime `{1,2}`: smoke-only
- Runtime-like certified-small `{A=1, B=1}` on `runtime_12`: certified-epsilon

## Tests run
- `pytest tests/oracle/test_disaster_exact_oracle.py -q`
- `pytest tests/integration/test_disaster_exact_crosscheck.py -q`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
- `pytest tests/integration/test_readiness_matrix.py -q`
- `pytest tests/integration/test_benders_vs_oracle.py -q`
- `pytest tests/integration/test_epsilon_certificate.py -q`
- `pytest tests/integration/test_benders_runtime_fixture_smoke.py -q`
- `pytest -q`

## Test outcomes
- `pytest tests/oracle/test_disaster_exact_oracle.py -q` -> `1 passed in 0.06s`
- `pytest tests/integration/test_disaster_exact_crosscheck.py -q` -> `1 passed in 0.11s`
- `pytest tests/integration/test_benders_runtime_certification.py -q` -> `1 passed in 1.90s`
- `pytest tests/integration/test_readiness_matrix.py -q` -> `1 passed in 0.01s`
- `pytest tests/integration/test_benders_vs_oracle.py -q` -> `2 passed in 0.10s`
- `pytest tests/integration/test_epsilon_certificate.py -q` -> `1 passed in 0.08s`
- `pytest tests/integration/test_benders_runtime_fixture_smoke.py -q` -> `1 passed in 5.52s`
- `pytest -q` -> `141 passed in 22.79s`

## Audit artifacts
- Certified runtime-like master before cut:
  - `/tmp/round_10_runtime_certified_master_before_cut.lp`
- Certified runtime-like master after cut:
  - `/tmp/round_10_runtime_certified_master_after_cut.lp`
- Certified runtime-like iteration log:
  - `/tmp/round_10_runtime_certified_iteration_log.json`

## Known limitations
- The certified runtime-like run is epsilon-certified, not exact.
- The default runtime `{1,2}` fixture remains a smoke path only.
- No paper-scale optimality claim is made in this round.

## Open issues for next round
- Decide whether a stronger certified runtime-like family should be formalized beyond the current `{A=1, B=1}` readiness path.
- If paper-scale validation is needed later, it should be added as a new bounded round rather than inferred from the current smoke/certified-small evidence.
