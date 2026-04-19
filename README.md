# Two-Stage Hybrid DRO EVCS Mainline

This repository is a round-gated, paper-faithful implementation of:

`Two-Stage Hybrid DRO-Stochastic Optimization for Resilient EV Charging Station Planning`

The codebase now contains a validated end-to-end mainline up through:

- canonical runtime loading and validation
- fixed-sample disaster primal / auto dual / paper dual checks
- separation MILP
- restricted master problem
- iterative Benders engine
- experiment packaging and interpretation outputs

This README is written as a working guide for the next person who wants to:

- run more experiments
- add benchmark families
- inspect outputs and validation levels
- improve the algorithm without breaking validated mathematics

## Current Status

The repository is usable for:

- tiny exact validation
- epsilon-certified reduced-runtime runs
- smoke-level runtime experiments on `data/runtime_12`
- packaging results into CSV / JSON / figures / interpretation markdown

The repository does **not** currently claim:

- paper-scale optimality
- direct reproduction of the paper's reported numerical tables
- unrestricted benchmark generality across arbitrary data packages

The most important honesty rule is:

- every run must be labeled explicitly as `exact`, `epsilon_certified`, or `smoke_only`

## Core Principles

These are the guardrails that keep the repo coherent:

- `docs/spec/*` are the frozen implementation contract
- `docs/tasks/*` define bounded round scope
- production model layers use only canonical objects from `src/instance/`
- production layers do **not** read raw CSV / JSON directly
- `critical_buses` are explicit runtime inputs
- never infer `critical_buses` from `ambig.w`
- when a pure first-stage contribution is needed, use `construction_cost_value`, not the attached master objective
- first-stage ordering must stay aligned with `instance.sets.buses`
- line ordering must stay aligned with the canonical stable line ordering

## Repository Map

### Contracts and specs

- `docs/spec/`
  - frozen implementation contract
  - architecture, equation registry, data contract, test strategy, round protocol
- `docs/tasks/`
  - per-round bounded task files
- `docs/reports/`
  - per-round completion reports

### Runtime and canonical layer

- `data/runtime_12/`
  - current local runtime package
  - useful for reduced certified runs and smoke experiments
- `src/instance/`
  - canonical loader
  - runtime selection boundary
  - manifest and validation logic
  - topology/indexing helpers

### Math-validation track

- `src/reference/`
  - auditable reference models and exact oracles
  - disaster primal reference LP
  - auto dual
  - independent exact disaster oracle
  - outage enumeration
  - outer-DRO LP oracle
  - tiny brute-force stage-1 oracle

### Production track

- `src/production/`
  - first-stage builder
  - normal-operation block
  - hand-coded paper dual
  - separation MILP
  - fixed-cut restricted master
  - cut factory
  - iterative Benders engine

### Audit and packaging

- `src/audit/`
  - residual summaries
  - cut audit
  - iteration log structures
  - experiment summary rows
- `scripts/`
  - experiment pack execution
  - figure generation
  - packaging helpers
- `configs/`
  - critical-bus configs
  - experiment manifests
- `results/`
  - generated summary CSV
  - plans
  - logs
  - figures
- `docs/analysis_packs/`
  - interpretation / experiment / diagnostic packs intended for human review

### Tests

- `tests/unit/`
  - coefficient and interface checks
- `tests/oracle/`
  - hand-checkable mathematical tests
- `tests/integration/`
  - end-to-end bounded regressions

## End-to-End Pipeline

At a high level, the validated workflow is:

1. Load and validate a canonical instance from `src/instance/`
2. Build first-stage and normal-operation components
3. Solve the fixed-cut master
4. Solve the separation MILP at the current master point
5. Extract a structured cut from the simplex-solved paper-dual chain
6. Add the cut and iterate through the Benders engine
7. Export auditable artifacts
8. Package experiments into CSV / JSON / figures / markdown

The cut representation is structured throughout:

- `beta`
- `gamma_z_by_bus`
- `gamma_n_sl_by_bus`
- `gamma_n_fa_by_bus`
- `phi_by_line_id`

It is intentionally **not** flattened into an opaque vector.

## Validation Levels

All interpretation should flow through these labels.

### `exact`

Use this only when the bounded run is actually exact.

Examples:

- direct fixed master solves used as exact benchmark rows
- tiny end-to-end checks against brute force
- exact disaster oracle checks

### `epsilon_certified`

Use this only when the Benders engine stopped with an explicit epsilon certificate.

Interpretation rule:

- the run is not exact
- but the sampled-problem gap is bounded by the certificate logic

### `smoke_only`

Use this when the run is only testing integration / packaging / directionality.

Interpretation rule:

- do not overclaim
- do not turn it into a paper-comparability statement
- use it for qualitative directionality, not final validation

## Environment

Minimum assumptions:

- Python `>= 3.9`
- `gurobipy`
- `pytest`
- `pyyaml`
- `matplotlib`
- `pandas`

The project metadata lives in [pyproject.toml](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/pyproject.toml). Pytest is configured by [pytest.ini](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/pytest.ini).

The current packaging scripts are designed to run from the repo root:

```bash
python scripts/run_experiment_pack.py
```

## Quick Start

### Run the full test suite

```bash
pytest -q
```

### Run the experiment pack

```bash
python scripts/run_experiment_pack.py
```

Default outputs:

- `results/summary.csv`
- `results/plans/*.csv`
- `results/logs/*.json`
- `results/figures/*.png`
- `docs/analysis_packs/paper_style_experiment_pack.md`

### Run a smoke manifest only

```bash
python scripts/run_experiment_pack.py \
  --manifest tests/fixtures/experiment_pack_smoke.yaml \
  --output-root /tmp/experiment_pack_results \
  --report-path /tmp/experiment_interpretation_pack.md \
  --skip-figures
```

### Regenerate figures from existing outputs

```bash
python scripts/make_experiment_figures.py \
  --summary-csv results/summary.csv \
  --plans-dir results/plans \
  --logs-dir results/logs \
  --figures-dir results/figures
```

## Current Round 11 Experiment Pack

The current experiment pack is defined by:

- [configs/critical_buses_paper_fig2.yaml](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/configs/critical_buses_paper_fig2.yaml)
- [configs/experiments/experiment_manifest.yaml](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/configs/experiments/experiment_manifest.yaml)
- [configs/experiments/certified_small_family.yaml](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/configs/experiments/certified_small_family.yaml)
- [configs/experiments/runtime12_smoke_family.yaml](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/configs/experiments/runtime12_smoke_family.yaml)

### Frozen Round 11 critical buses

For Round 11 packaging, `critical_buses` are fixed to:

`[2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32]`

This is a packaging decision, not a generic runtime rule.

### Benchmark families

#### 1. `certified_small_family`

Uses:

- runtime source: `data/runtime_12`
- explicit selection: `A = [1]`, `B = [1]`

Runs:

- `integrated_mainline_certified_small`
- `normal_only_certified_small`
- `deterministic_mean_value_certified_small`

Interpretation:

- this is the main reduced family for stronger validation
- in current results, integrated and normal-only happen to share the same first-stage plan

#### 2. `runtime12_smoke_family`

Uses:

- runtime source: `data/runtime_12`
- selection preset: `default_small`
- current default selected support: `{1, 2}`

Runs:

- `integrated_mainline_runtime12`
- `normal_only_runtime12`
- `deterministic_mean_value_runtime12`
- `ev_penetration_1_5x_runtime12`
- `ev_penetration_2_0x_runtime12`

Interpretation:

- this family is for bounded runtime-directionality checks
- it is **not** paper-comparable
- smoke results must stay labeled honestly

## Experiment Output Contract

### Summary CSV

[results/summary.csv](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/results/summary.csv) contains one row per run with:

- run identity
- family and regime labels
- validation label and stop reason
- objective decomposition
- iteration / cut counts
- final violation bound
- opened bus count
- total slow and fast chargers

### Plan CSVs

Each run writes `results/plans/<run_id>_plan.csv` with:

- `bus`
- `z`
- `n_sl`
- `n_fa`
- `is_critical`
- `region`

### Per-run JSON logs

Each run writes `results/logs/<run_id>_run.json`.

These logs carry:

- copied run config
- validation label
- stop reason
- selected scenario support
- summary row
- objective components
- per-scenario normal costs
- plan rows
- artifact paths
- lower-bound trace
- cut-count trace
- iteration log payload for Benders runs

### Figures

The current figure script writes:

- `objective_components.png`
- `benchmark_comparison.png`
- `iteration_trace.png`
- `plan_map.png`

### Interpretation pack

[docs/analysis_packs/experiment_interpretation_pack.md](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/docs/analysis_packs/experiment_interpretation_pack.md) is the colleague-facing summary.

It is supposed to be:

- readable
- validation-aware
- honest about smoke-only evidence
- explicit about non-comparability to the paper's numeric tables

## How To Add More Experiments

The safest way to expand experiments is to stay inside the packaging layer.

### Step 1: decide the benchmark family

Ask:

- Is this intended to be exact, epsilon-certified, or smoke-only?
- Is the goal integrated vs normal-only, deterministic vs integrated, or parameter scaling?
- Is the selected runtime support small enough to support a stronger claim?

If the answer is unclear, default the interpretation to `smoke_only`.

### Step 2: add or extend a family config

Create or update a file under `configs/experiments/`.

A run entry currently supports:

- `run_id`
- `case_name`
- `runtime_source`
- `family_name` if used inline
- either `selection` or `selection_preset`
- `mode`
- `solver`
- `parameter_regime`
- `expected_validation_level`
- optional `benders`
- optional `ev_penetration_scale`

Example shape:

```yaml
family_name: my_new_family
runs:
  - run_id: integrated_new_case
    case_name: integrated_new_case
    runtime_source: data/runtime_12
    selection:
      scenarios_a: [1]
      scenarios_b: [1]
    mode: integrated_mainline
    solver: benders
    parameter_regime: base
    expected_validation_level: epsilon_certified
    benders:
      epsilon_cert: 10000.0
      max_iterations: 5
```

### Step 3: include the family in the manifest

Add it to [configs/experiments/experiment_manifest.yaml](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/configs/experiments/experiment_manifest.yaml).

### Step 4: run the pack

```bash
python scripts/run_experiment_pack.py
```

### Step 5: check honesty before publishing results

Look at:

- `results/summary.csv`
- `results/logs/*.json`
- `docs/analysis_packs/paper_style_experiment_pack.md`

Make sure:

- validation labels match actual stop reasons
- interpretation text does not exceed the evidence
- any runtime-smoke family is still called smoke-only

## Supported Packaging Modes

These are benchmark-layer transformations already supported in [scripts/experiment_pack_utils.py](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/scripts/experiment_pack_utils.py).

### `integrated_mainline`

- uses the loaded canonical instance directly
- includes the disaster term through the normal validated production path

### `normal_only`

- packaging transform only
- sets `pi_f = 0.0`
- keeps the rest of the model structure intact

### `deterministic_mean_value`

- packaging transform only
- collapses loaded scenario supports to one mean normal scenario and one mean disaster scenario
- intended for deterministic benchmark comparisons

### `ev_penetration_scale`

- packaging transform only
- scales:
  - `normal_tensors.dev_ch_sl`
  - `normal_tensors.dev_ch_fa`
  - `disaster_tensors.dev_dis_sl`
  - `disaster_tensors.dev_dis_fa`

Use this for directionality experiments, not paper reproduction claims.

## How To Improve The Algorithm Safely

If you want to change the optimization algorithm rather than just package more experiments, treat that as a new validated round.

### Safe rule of thumb

Do not start by editing everything.

Pick one boundary:

- tighter separation bounds
- cut management
- stabilization
- warm starts
- parallel per-sample dual solves
- stronger certified-small families

Then add:

- one bounded task
- one independent oracle or regression
- one honest interpretation boundary

### Files by responsibility

If you are changing algorithmic behavior, these are the main places:

- first stage: [src/production/first_stage.py](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/src/production/first_stage.py)
- normal block: [src/production/normal_block.py](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/src/production/normal_block.py)
- paper dual: [src/production/disaster_dual_paper.py](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/src/production/disaster_dual_paper.py)
- separation: [src/production/separation_milp.py](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/src/production/separation_milp.py)
- master: [src/production/master_problem.py](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/src/production/master_problem.py)
- cut factory: [src/production/cut_factory.py](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/src/production/cut_factory.py)
- Benders loop: [src/production/benders_engine.py](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/src/production/benders_engine.py)

### Non-negotiable constraints for algorithm work

- do not flatten structured cuts
- do not break stable bus / line ordering
- do not redesign validated equations casually
- do not route model layers back to raw runtime files
- do not mix attached master objective with pure construction cost
- do not infer `critical_buses` from `ambig.w`

### Recommended workflow for algorithm changes

1. Start from the smallest auditable scope possible
2. Add a tiny hand-checkable regression first
3. Add one integration test second
4. Preserve or extend artifact dumping
5. Only then try a runtime smoke case
6. Label the result honestly

## Suggested Next Experiments

These are natural next steps that fit the current codebase.

### Stronger runtime-like certification

- build additional `{A=1, B=1}` or other explicitly selected certified-small families
- vary `epsilon_cert`
- compare stability of first-stage plans across certificates

### Deterministic vs integrated ablations

- use more than one selected scenario where still computationally manageable
- compare when deterministic mean-value changes siting or charger mix
- track when the disaster term actually moves the first-stage solution

### EV penetration sweeps

- run more than `1.5x` and `2.0x`
- record monotonicity in:
  - opened buses
  - total slow chargers
  - total fast chargers
  - objective components

### Critical-bus sensitivity

- create alternative explicit `critical_buses` configs
- compare plan sensitivity and disaster master term
- keep the config explicit and auditable

## Suggested Next Algorithm Improvements

These are plausible future research directions, but they should be introduced with new validation, not patched in ad hoc.

### Better Benders efficiency

- warm starts for the fixed-cut master
- tighter default `omega` bounds
- selective cut addition
- cut dominance / redundancy checks

### Better certification behavior

- stronger runtime-like certified families
- more systematic epsilon schedules
- explicit trace summaries comparing exact vs epsilon-certified stopping

### Better experiment ergonomics

- richer manifest schema validation
- more figure families
- better summary aggregation across multiple experiment packs

### Better interpretation support

- delta-of-plan tables
- cut growth summaries
- comparative plots for construction / normal / disaster components

None of these should be merged without:

- bounded tests
- auditable outputs
- explicit statement of what is exact vs epsilon vs smoke

## Common Pitfalls

### 1. Overclaiming smoke runs

This is the biggest mistake to avoid.

If a run is `smoke_only`, say so everywhere.

### 2. Treating `runtime_12` as paper-comparable

Do not do that.

The current local runtime package is useful for:

- directionality
- bounded validation
- workflow testing

It is not a direct paper-table reproduction regime.

### 3. Using the wrong first-stage objective field

If you need the pure first-stage contribution, use:

- `construction_cost_value`

Do not substitute:

- attached master `objective_value`

### 4. Sneaking raw reads into model layers

All model construction should be driven by canonical objects.

If you need new runtime semantics:

- change the instance layer or packaging layer
- do not let production solvers reopen raw files

### 5. Breaking stable ordering

Many interfaces depend on:

- bus ordering = `instance.sets.buses`
- line ordering = canonical stable line ordering

Do not reorder these silently.

## Reproducibility Checklist

Before handing results to someone else, verify:

- `pytest -q` passes
- the manifest used is saved
- the critical-bus config used is saved
- `results/summary.csv` exists
- per-run logs exist
- figures exist if promised
- the interpretation pack matches the actual validation labels
- any smoke-only family is called smoke-only in prose

## Where To Start Reading

If you are new to the repo, read in this order:

1. [codex_start_here.md](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/codex_start_here.md)
2. `docs/spec/*`
3. recent `docs/reports/*`
4. [configs/experiments/experiment_manifest.yaml](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/configs/experiments/experiment_manifest.yaml)
5. [scripts/run_experiment_pack.py](/Users/shixinliu/Desktop/Research/GitHub_Research/two-regime-dro/two-regime-dro/scripts/run_experiment_pack.py)
6. the specific production component you plan to change

## Bottom Line

This repository is in a good state for:

- bounded but real experiment packaging
- careful benchmark comparisons
- algorithmic improvements under strict validation discipline

The two most important habits for future work are:

1. keep the evidence level honest
2. change one algorithmic boundary at a time
