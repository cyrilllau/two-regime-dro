# Full Benders Scaling Diagnostic Report

Target: accepted default regime, proposed integrated model, objective multipliers `(m_cons,m_normal,m_dis)=(0.015,1,1.25)`, MILP separation, top-M cuts = 3.

## Solving Setup
- Solver: Benders decomposition with a MIP master and MILP separation oracle.
- Separation mode: MILP for all rows; no small-K exact enumeration is used.
- Standard row budget: `max_iterations=100`, `epsilon_cert=100`, `top_cuts=3`, master time limit 120s, separation time limit 300s, MIPGap 0.02.
- Completion row: K=7 was rerun with `max_iterations=300` after the 100-iteration row failed certification.
- K=10 was interrupted before producing a completed row and is excluded from the evidence table.

## Completed Runs
| run | B | K | validation | iters | cuts | final violation | runtime s | separation s |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| full_benders_A10_B005_K02_top003 | 5 | 2 | epsilon_certified | 31 | 91 | 92.88 | 263.5 | 91.7 |
| full_benders_A10_B010_K01_top003 | 10 | 1 | epsilon_certified | 14 | 38 | 67.37 | 101.2 | 60.5 |
| full_benders_A10_B010_K02_top003 | 10 | 2 | epsilon_certified | 49 | 145 | 33.14 | 669.9 | 348.7 |
| full_benders_A10_B010_K03_top003 | 10 | 3 | smoke_only | 100 | 298 | 811.56 | 1992.5 | 975.8 |
| full_benders_A10_B010_K05_top003 | 10 | 5 | smoke_only | 100 | 298 | 36744.81 | 2757.4 | 1465.2 |
| full_benders_A10_B010_K07_top003 | 10 | 7 | smoke_only | 100 | 298 | 67772.68 | 3155.8 | 1567.3 |
| full_benders_A10_B020_K02_top003 | 20 | 2 | epsilon_certified | 75 | 222 | 68.72 | 2250.1 | 1592.5 |
| full_benders_A10_B050_K02_top003 | 50 | 2 | epsilon_certified | 47 | 137 | 74.07 | 4928.2 | 4472.3 |
| full_benders_A10_B100_K02_top003 | 100 | 2 | epsilon_certified | 40 | 116 | 68.27 | 12156.3 | 11686.2 |
| full_benders_completion_A10_B010_K07_top003_max300 | 10 | 7 | smoke_only | 300 | 898 | 18833.51 | 11467.5 | 4958.2 |

## Main Observations
- B-scaling with K=2 certified through B=100. Runtime grows mainly through separation time; B=100 spent roughly 96% of total runtime in separation.
- K-scaling is the hard dimension. K=1 and K=2 certified, while K=3/5/7 hit the 100-iteration limit.
- K=7 completion to 300 iterations reduced violation from 67772.68 to 18833.51 but still did not certify. Cuts are useful, but the current cut family/batching is too weak for large K under this accepted multiplier regime.
- The accepted objective multipliers make disaster performance material in the training objective; this increases the value/diversity of violated outage cuts and makes the master harder to certify than the faster colleague/default-scale parameter regime.

## Generated Artifacts
- `results/paper_final/full_benders_scaling_diagnostics/run_summary.csv`
- `results/paper_final/full_benders_scaling_diagnostics/iteration_trace.csv`
- `results/paper_final/full_benders_scaling_diagnostics/iteration_key_points.csv`
- `results/paper_final/full_benders_scaling_diagnostics/cut_effectiveness_summary.csv`
- `results/paper_final/full_benders_scaling_diagnostics/k_violation_trace.png`
- `results/paper_final/full_benders_scaling_diagnostics/b_violation_trace.png`
- `results/paper_final/full_benders_scaling_diagnostics/k_runtime_decomposition.png`
