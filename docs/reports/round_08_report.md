# Round 08 Report

## Files changed
- `src/production/cut_factory.py`
- `src/audit/cut_audit.py`
- `tests/oracle/test_cut_factory.py`
- `tests/integration/test_single_iteration_cut_addition.py`
- `tests/integration/test_cut_factory_runtime_fixture.py`
- `tests/fixtures/cut_factory_generated_efficacy.yaml`
- `tests/fixtures/cut_factory_multi_cut_carryover.yaml`
- `docs/reports/round_08_report.md`

## Design decisions
- The cut factory generates master cuts only from the validated hand-coded paper-dual chain. It does not read or reuse the separation MILP's internal dual blocks as the final cut family.
- Per-sample paper-dual LPs in the cut-factory path are solved with Gurobi `Method=0` (primal simplex) so the extracted optimal dual solution is simplex/basic-solution compatible with the extreme-point interpretation required by the theorem-level cut family.
- The generated master cut stays structured as `beta`, `gamma_z_by_bus`, `gamma_n_sl_by_bus`, `gamma_n_fa_by_bus`, and `phi_by_line_id`. No flattened coefficient vector is introduced.
- The one-step integration path is intentionally bounded to one explicit `master -> separation -> generate cut -> master` pass. No multi-iteration Benders driver was added.

## Cut factory design
- `generate_structured_cut(...)` solves the hand-coded paper dual once per selected disaster sample at fixed `(x, delta_star, b)`.
- Each sample solve exposes `samplewise_decomposition = beta_b - gamma_b^T x + phi_b^T delta`.
- `_build_aggregated_cut(...)` averages those samplewise decompositions exactly over the loaded disaster sample set to produce one `RestrictedMasterCut`.
- `GeneratedCutAuditRecord` stores:
  - cut id
  - provenance string
  - simplex method used
  - source plan `x`
  - source outage `delta_star`
  - source `alpha` / `lambda` when available
  - source violation value
  - samplewise decompositions and samplewise objectives
  - aggregated structured cut

## Single-iteration integration behavior
- `run_single_iteration_cut_addition(...)` performs exactly one bounded step:
  1. solve the fixed-cut master
  2. read `(x_star, alpha_star, lambda_star)`
  3. derive/use `omega` bounds
  4. solve the fixed-point separation MILP once
  5. if the separation objective is positive, build one generated cut from the separation outage
  6. rebuild the fixed-cut master with the new cut
  7. re-solve once and stop
- Multi-cut carryover was verified on a tiny case with an existing `gamma_site` cut plus one generated real cut:
  - cut ids stayed distinct
  - `s_r` stayed indexed by cut id
  - `u_{r,l}` stayed indexed by `(cut_id, line_id)`
  - both cuts remained enforced after the re-solve
- The master objective boundary remained correct after cut addition:
  - the post-cut master still reconstructs with pure `construction_cost_value`
  - the attached first-stage `objective_value` remains the full attached-model objective and is not reused as the pure first-stage term

## Tests run
- `pytest tests/oracle/test_cut_factory.py -q`
  - `1 passed in 0.05s`
- `pytest tests/integration/test_single_iteration_cut_addition.py -q`
  - `3 passed in 0.07s`
- `pytest tests/integration/test_cut_factory_runtime_fixture.py -q`
  - `1 passed in 4.42s`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
  - `5 passed in 0.07s`
- `pytest tests/oracle/test_separation_exactness.py -q`
  - `5 passed in 0.07s`
- `pytest tests/integration/test_master_problem_runtime_fixture.py -q`
  - `2 passed in 3.29s`
- `pytest -q`
  - `133 passed in 15.12s`

## Audit artifacts
- Stable LP dumps:
  - `/tmp/round_08_tiny_master_before_cut.lp`
  - `/tmp/round_08_tiny_master_after_cut.lp`
  - `/tmp/round_08_runtime_master_before_cut.lp`
  - `/tmp/round_08_runtime_master_after_cut.lp`

- Tiny generated-cut efficacy summary:
  - source outage: `line_01_02 = 1`
  - aggregated cut:
    - `beta = 0.0`
    - `gamma_n_sl_by_bus[2] = 30.0`
    - `phi_by_line_id["line_01_02"] = 100.0`
  - samplewise objective at source: `100.0`
  - old-master cut violation: `100.0`
  - pre-cut master objective: `0.0`
  - post-cut master objective: `10.0`
  - post-cut residuals:
    - `max_cut_support_violation = 0.0`
    - `max_u_link_violation = 0.0`

- Multi-cut carryover summary:
  - existing cut ids before addition: `("gamma_site",)`
  - cut ids after addition: `("gamma_site", "generated_real_cut")`
  - pre-cut master objective: `35.0`
  - post-cut master objective: `42.0`
  - post-cut support slacks:
    - `gamma_site = 0.0`
    - `generated_real_cut = 0.0`
  - post-cut construction cost: `35.0`
  - attached first-stage objective after cut addition: `42.0`

- Runtime generated-cut smoke summary:
  - source outage from separation: `("line_06_07", "line_23_24")`
  - samplewise `beta_b`:
    - scenario `1`: `-765181.3599999999`
    - scenario `2`: `-764043.2799999998`
  - aggregated generated cut:
    - `beta = -764612.3199999998`
    - nonzero `gamma_n_sl_by_bus`: buses `7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 24, 25` each `280.0`
    - nonzero `gamma_n_fa_by_bus`: buses `7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 24, 25` each `2000.0`
    - nonzero `phi_by_line_id`:
      - `line_06_07 = 400000.0`
      - `line_23_24 = 400000.0`
  - pre-cut master objective: `24916711.48002533`
  - separation violation at the old point: `12987.680000000284`
  - generated-cut old-master violation: `12987.680000000168`
  - post-cut master objective: `24916798.832808632`
  - post-cut residuals:
    - `max_cut_support_violation = 0.0`
    - `max_u_link_violation = 0.0`
  - result interpretation: the runtime generated-cut smoke changed the master meaningfully; it was not only an interface smoke

## Known limitations
- The one-step integration path is intentionally not a Benders engine. It performs exactly one explicit cut-addition-and-resolve step and stops.
- `omega` bounds still come from the existing conservative bound path rather than a tighter production bound-management subsystem.
- The cut-audit artifact is a stable Python object used by tests/reporting; this round does not add a separate serialized artifact format.

## Open issues for next round
- Build the actual iterative Benders driver on top of the validated fixed-cut master, separation MILP, and generated-cut factory.
- Decide whether the runtime cut-audit object should also be serialized to a stable JSON/markdown artifact.
- Add convergence bookkeeping and termination logic once multi-iteration behavior is opened.
- Revisit runtime `omega` bound quality if later rounds need tighter separation strength or performance.

- Extreme-point extraction note:
  - passed
  - the cut-factory path explicitly uses Gurobi primal simplex (`Method=0`) for per-sample paper-dual LP solves

- Generated-cut efficacy check:
  - passed
  - on the tiny case, the old master solution violated the generated cut by `100.0` and the re-solved master objective increased from `0.0` to `10.0`

- Runtime generated-cut smoke:
  - passed
  - the runtime path produced a nontrivial real cut and increased the master objective from `24916711.48002533` to `24916798.832808632`

- Narrow bug fix needed:
  - none
