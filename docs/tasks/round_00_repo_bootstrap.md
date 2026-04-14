# Round 00 - Repo Bootstrap

## Objective
Establish the initial repository scaffold for the new EVCS hybrid DRO mainline so future rounds can implement verified math incrementally.

This round is **not** allowed to implement substantive optimization logic. Its job is to create a clean, typed, testable project skeleton that supports:
- a shared canonical instance layer,
- separate `reference` and `production` tracks,
- audit/report outputs,
- multi-round collaboration with strict task boundaries.

## Context files to read first
- `codex_collaboration_plan.md`
- `main_paper.pdf`
- `m1_data_setup.py`

Treat `codex_collaboration_plan.md` as the governing collaboration and architecture document for this round.

## Allowed files to create/update
You may create or update only the following files and directories:

### Project/configuration
- `pyproject.toml`
- `README.md`
- `.gitignore`
- `pytest.ini`

### Docs skeleton
- `docs/spec/00_freeze_contract.md`
- `docs/spec/01_architecture.md`
- `docs/spec/02_equation_registry.md`
- `docs/spec/03_data_contract.md`
- `docs/spec/04_test_strategy.md`
- `docs/spec/05_round_protocol.md`
- `docs/reports/round_00_report.md`

### Source tree skeleton
- `src/__init__.py`
- `src/instance/__init__.py`
- `src/contracts/__init__.py`
- `src/reference/__init__.py`
- `src/production/__init__.py`
- `src/audit/__init__.py`

### Placeholder modules (only lightweight stubs / docstrings / TODO markers)
- `src/instance/schema.py`
- `src/instance/canonical_instance.py`
- `src/instance/validators.py`
- `src/instance/indexer.py`
- `src/instance/network_topology.py`
- `src/contracts/freeze.py`
- `src/contracts/equation_registry.py`
- `src/contracts/naming.py`
- `src/reference/disaster_primal_ref.py`
- `src/reference/lp_canonicalizer.py`
- `src/reference/disaster_dual_auto.py`
- `src/reference/kkt_checks.py`
- `src/reference/outage_enumerator.py`
- `src/reference/dro_outer_lp_oracle.py`
- `src/production/first_stage.py`
- `src/production/normal_block.py`
- `src/production/disaster_dual_paper.py`
- `src/production/separation_milp.py`
- `src/production/cut_factory.py`
- `src/production/master_problem.py`
- `src/production/benders_engine.py`
- `src/audit/model_dump.py`
- `src/audit/residual_report.py`
- `src/audit/cut_audit.py`
- `src/audit/iteration_log.py`

### Tests
- `tests/__init__.py`
- `tests/unit/test_repo_layout.py`
- `tests/integration/test_imports.py`
- `tests/fixtures/README.md`

## Do not modify
- Any raw data files under `data/`
- Any scenario CSV contents
- Any frozen runtime values not explicitly listed in this round
- Any non-listed files

## Required behavior
1. Create a package-oriented repo layout matching the collaboration plan.
2. Set up Python packaging and test configuration.
3. Create spec skeleton files that summarize the intended contents without inventing new mathematics.
4. Create module stubs with descriptive docstrings that clearly state future responsibilities.
5. Ensure imports work for all created Python modules.
6. Add lightweight smoke tests that verify:
   - the source tree is importable,
   - the expected top-level packages exist,
   - the `docs/spec/` files exist.
7. Do **not** implement model logic, data parsing logic, optimization variables, or solver calls in this round.
8. Keep all placeholder code simple, typed where reasonable, and clearly marked as scaffold-only.

## Architecture constraints to respect
1. The repo must preserve a strict distinction between:
   - `src/reference/` for auditable math-validation implementations,
   - `src/production/` for the main algorithm path.
2. The repo must preserve a shared bottom layer:
   - `src/instance/`
   - `src/contracts/`
3. The disaster mainline must **not** infer `critical_buses` from legacy weights.
4. Default runtime fixture semantics are frozen to the small tested instance `{1,2}` at the spec level, but actual fixture loading is not implemented in this round.
5. This round must leave the door open for later primal / auto-dual / hand-coded-dual triangulation.

## Acceptance tests
Run all of the following and record the output in the round report:

```bash
pytest tests/unit/test_repo_layout.py -q
pytest tests/integration/test_imports.py -q
pytest -q
```

## Deliverables
1. The scaffolded repository structure.
2. Passing smoke tests.
3. `docs/reports/round_00_report.md`.

## Report format
The report **must** contain these sections:

```md
# Round 00 Report

## Files changed
- ...

## Scaffold decisions
- ...

## Tests run
- command
- result

## What is intentionally not implemented yet
- ...

## Risks / notes for Round 01
- ...
```

## Definition of done for this round
This round is complete only if:
- the repo layout exists,
- the package imports succeed,
- the smoke tests pass,
- no substantive optimization logic has been added.
