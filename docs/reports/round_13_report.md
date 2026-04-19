# Round 13 Report

## Files changed
- `src/production/benders_engine.py`
- `src/production/cut_factory.py`
- `src/audit/iteration_log.py`
- `src/audit/cut_audit.py`
- `src/audit/experiment_summary.py`
- `scripts/cut_process_utils.py`
- `scripts/run_cut_process_diagnostics.py`
- `scripts/make_cut_process_figures.py`
- `tests/oracle/test_cut_signature_dedup.py`
- `tests/integration/test_benders_cut_process_improvements.py`
- `tests/integration/test_benders_repeated_outage_guard.py`
- `tests/integration/test_benders_two_real_cuts_runtime_like.py`
- `tests/fixtures/cut_process_smoke.yaml`

## Design decisions
- Kept validated math unchanged. No changes were made to the sampled dual, separation MILP, master formulation, or reference models.
- Implemented only two conservative cut-process changes:
  - repeated-outage detection/reporting
  - exact duplicate structured-cut signature detection with an optional dedup guard
- Left both improvements individually switchable through `run_benders_engine(...)` flags:
  - `enable_cut_signature_dedup`
  - `enable_repeated_outage_guard`
- Preserved existing semantics by default. All new behavior is opt-in, so the baseline engine path remains unchanged.
- Exported cut-process diagnostics directly from the engine/iteration log instead of re-solving extra master problems in the Round 13 pack.

## Improvement(s) implemented
- Added per-cut diagnostics to iteration logs and CSV export:
  - cut id
  - iteration id
  - source outage vector
  - repeated outage flag
  - cut signature hash
  - repeated cut-signature flag
  - old-master violation at source
  - post-cut objective change
  - whether the first-stage plan changed
  - whether the cut changed only `alpha/lambda`
  - nonzero counts in `gamma_z`, `gamma_n_sl`, `gamma_n_fa`, `phi`
- Added a stable structured-cut signature hash in `src/production/cut_factory.py`, ignoring `cut_id`.
- Added an optional dedup guard in `src/production/benders_engine.py` that can stop before re-adding an exact duplicate structured cut.
- Added a focused Round 13 diagnostic pack under `results/cut_process_diagnostics/` plus a human report at `reports/cut_process_diagnostic_pack.md`.

## Comparative diagnostic sweep
- Compared baseline vs improved on:
  - `integrated_paper_like_exact`, `A=[1]`, `B=[1]`, `K=2`, iteration budgets `10`, `20`, `40`
  - `disaster_only_paper_like_exact`, `A=[1]`, `B=[1]`, `K=1`, iteration budgets `5`, `20`, `40`
  - `disaster_only_paper_like_exact`, `A=[1]`, `B=[1]`, `K=2`, iteration budgets `5`, `20`, `40`
  - one runtime-directional case with `[1,2,3,4]`, `K=3`, iteration budget `3`
- Baseline vs improved summary:
  - all 10 comparison groups had identical baseline and improved outcomes
  - no compared run showed a lower final violation under the new options
  - the improvement therefore did not strengthen the current hard cases in this bounded Round 13 sweep
- Repeated-outage findings:
  - repeated outage patterns were real and observable in the harder longer-budget cases
  - they appeared in:
    - `integrated_paper_like_exact_i20_k2_a1b1`
    - `integrated_paper_like_exact_i40_k2_a1b1`
    - `disaster_only_paper_like_exact_i20_k1_a1b1`
    - `disaster_only_paper_like_exact_i40_k1_a1b1`
    - `disaster_only_paper_like_exact_i20_k2_a1b1`
    - `disaster_only_paper_like_exact_i40_k2_a1b1`
- Repeated-cut findings:
  - exact duplicate structured-cut signatures were **not** observed in the focused sweep
  - repeated outage did not translate into repeated structured-cut signatures in these runs
  - the dedup guard therefore never activated on the compared production runs
- Lower-bound / cut-count behavior:
  - `integrated_paper_like_exact_i10_k2_a1b1`: LB gain `1003.078`, still `max_iter_noncert`
  - `integrated_paper_like_exact_i20_k2_a1b1`: LB gain `1173.583`, repeated outages present, still `max_iter_noncert`
  - `integrated_paper_like_exact_i40_k2_a1b1`: reached `exact_zero`
  - `disaster_only_paper_like_exact_i40_k1_a1b1`: reached `exact_zero`
  - `disaster_only_paper_like_exact_i40_k2_a1b1`: still `max_iter_noncert` with final violation `7636.46`
  - `integrated_runtime12_exact_i3_k3_a1234b1234`: LB gain `146.589`, still `max_iter_noncert`
- First-stage vs `alpha/lambda` effect:
  - integrated hard cases produced plan-changing cuts almost exclusively
  - disaster-only cases consistently had one early cut that changed only `alpha/lambda`, but most later cuts still changed the plan
  - the hard non-certification cases are therefore not well explained by “duplicate cuts only affecting `alpha/lambda`”

## Tests run
- `pytest tests/oracle/test_cut_signature_dedup.py -q`
  - `2 passed in 0.06s`
- `pytest tests/integration/test_benders_repeated_outage_guard.py -q`
  - `1 passed in 47.51s`
- `pytest tests/integration/test_benders_cut_process_improvements.py -q`
  - `1 passed in 8.15s`
- `pytest tests/integration/test_benders_two_real_cuts_runtime_like.py -q`
  - `1 passed in 21.28s`
- `pytest tests/integration/test_benders_runtime_certification.py -q`
  - `1 passed in 1.95s`
- `pytest tests/integration/test_benders_vs_oracle.py -q`
  - `2 passed in 0.10s`
- `pytest -q`
  - `150 passed in 124.87s (0:02:04)`

## Audit artifacts
- Summary CSV:
  - `results/cut_process_diagnostics/summary.csv`
- Failures CSV:
  - `results/cut_process_diagnostics/failures.csv`
- Cut diagnostics CSV:
  - `results/cut_process_diagnostics/cut_diagnostics.csv`
- Human diagnostic pack:
  - `reports/cut_process_diagnostic_pack.md`
- Stable iteration logs:
  - `results/cut_process_diagnostics/logs/integrated_paper_like_exact_i20_k2_a1b1__baseline_iteration_log.json`
  - `results/cut_process_diagnostics/logs/integrated_paper_like_exact_i20_k2_a1b1__improved_iteration_log.json`
  - `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i40_k2_a1b1__baseline_iteration_log.json`
  - `results/cut_process_diagnostics/logs/disaster_only_paper_like_exact_i40_k2_a1b1__improved_iteration_log.json`
  - `results/cut_process_diagnostics/logs/integrated_runtime12_exact_i3_k3_a1234b1234__baseline_iteration_log.json`
  - `results/cut_process_diagnostics/logs/integrated_runtime12_exact_i3_k3_a1234b1234__improved_iteration_log.json`
- Stable master LP dumps:
  - `results/cut_process_diagnostics/lp/integrated_runtime12_exact_i3_k3_a1234b1234__baseline_master_before.lp`
  - `results/cut_process_diagnostics/lp/integrated_runtime12_exact_i3_k3_a1234b1234__baseline_master_after.lp`
  - `results/cut_process_diagnostics/lp/integrated_runtime12_exact_i3_k3_a1234b1234__improved_master_before.lp`
  - `results/cut_process_diagnostics/lp/integrated_runtime12_exact_i3_k3_a1234b1234__improved_master_after.lp`

## Known limitations
- The implemented Round 13 improvements are intentionally conservative. They diagnose and prevent exact duplicate cut re-addition, but they do not strengthen cuts mathematically.
- Because no exact duplicate structured cuts were observed in the focused sweep, the dedup guard did not improve the problematic production runs.
- Repeated outages were present, but those repeated outages still produced distinct structured cuts under the current plan trajectory.
- The runtime-directional case remains `max_iter_noncert`; this round does not make any paper-scale convergence claim.

## Open issues for next round
- The main issue now appears to be cut strength / progress quality rather than exact duplicate structured cuts.
- The next step should likely be one of:
  - stronger cuts
  - conservative multi-cut addition
  - stabilization
  - master-side engineering only after cut quality is revisited
- Based on Round 13 evidence, pure duplicate-cut guarding alone is not enough to materially improve the current hard non-certification cases.
