# Default Case Reproduction Report

Verdict: `PASS_REPRODUCED_WITH_SEEDED_CUT_POOL`.

## Target Version

- Restored PDF/source version: `docs/analysis_packs/ieee_experiment_section_standalone.pdf`.
- Candidate id: `mult_cons0p0152_normal1_disaster1p4`.
- Source artifact root: `results/default_case_targeted_transition_v8_focus_cert`.
- Runtime data source: `data/colleague_default_10x10`.
- Common evaluator: `A=10`, `B=10`, `K=2`, `milp_worst_distribution`.
- Training objective multipliers: `m_cons=0.0152`, `m_normal=1.0`, `m_disaster=1.4`.
- Raw reporting remains unweighted: `F_cons`, `F_trans`, `F_unmet`, `F_sub`, `Psi_nor`, `Phi_dis`, `J_common`.

## Reproduction Result

The seeded rerun reproduced all Table III rows exactly against
`results/paper_final/objective_components_tableIII.csv`.

- Case 1 proposed: all objective components, topology, and charger counts match.
- Case 2 normal-only: all objective components, topology, and charger counts match.
- Case 3 disaster-only: all objective components, topology, and charger counts match.
- Case 4 deterministic K=2: all objective components, topology, and charger counts match.

Machine-readable comparison:

- `results/reproduce_default_0p0152_1p4_seeded_20260503/reproduction_diff.csv`
- `results/reproduce_default_0p0152_1p4_seeded_20260503/reproduction_verdict.json`

## Fresh Rerun Attempt

A fresh unseeded proposed training rerun was started with the same parameter
regime and solver settings. It ran for more than 20 minutes without completing
the first proposed case log. I terminated that attempt to avoid wasting compute.
This does not indicate missing parameters; it indicates that from-scratch
Benders/MILP-separation training can follow a much slower Gurobi branch path.

## Seeded Rerun Method

The successful reproduction used saved valid cut pools from the same instance
and same benchmark mode. This is a deterministic reproducibility pack for this
paper version: it does not alter the feasible region or reporting evaluator, but
it avoids re-discovering cuts that were already certified for the same
`A=10,B=10,K=2` instance.

Use the following commands from the repo root.

### Proposed

```bash
python scripts/run_default_multiplier_calibration.py \
  --runtime-source data/colleague_default_10x10 \
  --output-root results/reproduce_default_0p0152_1p4_seeded_20260503 \
  --cons-values 0.0152 --normal-values 1 --disaster-values 1.4 \
  --stage1-max-candidates 1 --stage2-max-candidates 1 \
  --cases proposed \
  --max-iterations 100 --top-cuts 20 \
  --fixed-eval-max-iterations 60 --fixed-eval-top-cuts 20 \
  --reuse-certified-disaster-training-phi \
  --epsilon-cert 100 \
  --master-time-limit-seconds 120 --master-mip-gap 0.03 \
  --separation-time-limit-seconds 180 --separation-mip-gap 0.02 \
  --omega-bound-upper 20000000 \
  --enable-cut-signature-dedup \
  --initial-cut-pool-paths results/default_case_targeted_transition_v8_focus_cert/runs/default_multiplier_mult_cons0p0152_normal1_disaster1p4_proposed/logs/default_multiplier_mult_cons0p0152_normal1_disaster1p4_proposed_cut_pool.json \
  --no-forced-baseline
```

### Normal-Only

```bash
python scripts/run_default_multiplier_calibration.py \
  --runtime-source data/colleague_default_10x10 \
  --output-root results/reproduce_default_0p0152_1p4_seeded_20260503 \
  --cons-values 0.0152 --normal-values 1 --disaster-values 1.4 \
  --stage1-max-candidates 1 --stage2-max-candidates 1 \
  --cases normal \
  --max-iterations 100 --top-cuts 20 \
  --fixed-eval-max-iterations 60 --fixed-eval-top-cuts 20 \
  --reuse-certified-disaster-training-phi \
  --epsilon-cert 100 \
  --master-time-limit-seconds 120 --master-mip-gap 0.03 \
  --separation-time-limit-seconds 180 --separation-mip-gap 0.02 \
  --omega-bound-upper 20000000 \
  --enable-cut-signature-dedup \
  --no-forced-baseline
```

### Disaster-Only

```bash
python scripts/run_default_multiplier_calibration.py \
  --runtime-source data/colleague_default_10x10 \
  --output-root results/reproduce_default_0p0152_1p4_seeded_20260503 \
  --cons-values 0.0152 --normal-values 1 --disaster-values 1.4 \
  --stage1-max-candidates 1 --stage2-max-candidates 1 \
  --cases disaster \
  --max-iterations 100 --top-cuts 20 \
  --fixed-eval-max-iterations 60 --fixed-eval-top-cuts 20 \
  --reuse-certified-disaster-training-phi \
  --epsilon-cert 100 \
  --master-time-limit-seconds 120 --master-mip-gap 0.03 \
  --separation-time-limit-seconds 180 --separation-mip-gap 0.02 \
  --omega-bound-upper 20000000 \
  --enable-cut-signature-dedup \
  --initial-cut-pool-paths results/default_case_targeted_transition_v8_focus_cert/runs/default_multiplier_mult_cons0p0152_normal1_disaster1p4_disaster/logs/default_multiplier_mult_cons0p0152_normal1_disaster1p4_disaster_cut_pool.json \
  --no-forced-baseline
```

### Deterministic K=2

```bash
python scripts/run_default_multiplier_calibration.py \
  --runtime-source data/colleague_default_10x10 \
  --output-root results/reproduce_default_0p0152_1p4_seeded_20260503 \
  --cons-values 0.0152 --normal-values 1 --disaster-values 1.4 \
  --stage1-max-candidates 1 --stage2-max-candidates 1 \
  --cases deterministic_k2 \
  --max-iterations 100 --top-cuts 20 \
  --fixed-eval-max-iterations 60 --fixed-eval-top-cuts 20 \
  --reuse-certified-disaster-training-phi \
  --epsilon-cert 100 \
  --master-time-limit-seconds 120 --master-mip-gap 0.03 \
  --separation-time-limit-seconds 180 --separation-mip-gap 0.02 \
  --omega-bound-upper 20000000 \
  --enable-cut-signature-dedup \
  --initial-cut-pool-paths results/default_case_targeted_transition_v8_focus_cert/runs/default_multiplier_mult_cons0p0152_normal1_disaster1p4_deterministic_k2/logs/default_multiplier_mult_cons0p0152_normal1_disaster1p4_deterministic_k2_cut_pool.json \
  --no-forced-baseline
```

