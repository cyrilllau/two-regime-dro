# Two-Stage Hybrid DRO EVCS Mainline

This repository hosts a round-gated, paper-faithful implementation scaffold for:

`Two-Stage Hybrid DRO-Stochastic Optimization for Resilient EV Charging Station Planning`

The current state is `Round 00` bootstrap only. The repository now provides:

- a package-oriented `src/` scaffold,
- separate `reference` and `production` tracks,
- placeholder `audit` modules,
- pytest smoke tests for layout and imports,
- frozen specification documents under `docs/spec/`.

What is intentionally absent in this round:

- canonical data loading,
- optimization model construction,
- solver integration,
- disaster dualization and Benders logic,
- any inference of `critical_buses` from legacy data.

## Layout

- `docs/spec/`: stable implementation contract and round protocol
- `docs/tasks/`: bounded round task files
- `docs/reports/`: round completion reports
- `src/instance/`: future canonical instance and validation layer
- `src/contracts/`: future freeze-contract and equation-registry access layer
- `src/reference/`: future auditable math-validation track
- `src/production/`: future production algorithm track
- `src/audit/`: future audit artifact helpers
- `tests/`: smoke tests now, model and oracle tests in later rounds

## Development

Run the smoke tests from the repository root:

```bash
pytest tests/unit/test_repo_layout.py -q
pytest tests/integration/test_imports.py -q
pytest -q
```
