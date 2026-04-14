# Round 01 - Instance Layer and Frozen Config

## Objective
Implement the canonical instance layer for the EVCS hybrid DRO mainline.

This round must build the **shared bottom layer** used by both the `reference` and `production` tracks. The goal is to make raw runtime data safe and deterministic before any optimization model is built.

This round must focus on:
- typed internal schema,
- frozen config contract,
- canonical instance construction,
- topology and indexing helpers,
- fail-fast validation,
- a default small runtime fixture contract for the local tested `{1,2}` instance.

## Context files to read first
- `codex_collaboration_plan.md`
- `main_paper.pdf`
- `m1_data_setup.py`
- `parameters.json`
- `docs/spec/00_freeze_contract.md`
- `docs/spec/01_architecture.md`
- `docs/spec/03_data_contract.md`

## Allowed files to create/update

### Contracts / instance layer
- `src/contracts/freeze.py`
- `src/contracts/naming.py`
- `src/instance/schema.py`
- `src/instance/canonical_instance.py`
- `src/instance/validators.py`
- `src/instance/indexer.py`
- `src/instance/network_topology.py`

### Optional helper modules if needed
- `src/instance/loader_adapter.py`
- `src/instance/runtime_fixture.py`

### Docs
- `docs/spec/00_freeze_contract.md`
- `docs/spec/03_data_contract.md`
- `docs/reports/round_01_report.md`

### Tests / fixtures
- `tests/unit/test_freeze_contract.py`
- `tests/unit/test_network_topology.py`
- `tests/unit/test_indexer.py`
- `tests/unit/test_validators.py`
- `tests/integration/test_instance_loading.py`
- `tests/fixtures/runtime_12/README.md`
- `tests/fixtures/toy_config_valid.yaml`
- `tests/fixtures/toy_config_missing_critical.yaml`

## Do not modify
- Any source files under `src/reference/`
- Any source files under `src/production/`
- Raw scenario CSV contents
- The mathematics of the optimization model
- Any non-listed files

## Required behavior
1. Define a typed `FrozenConfig` contract that captures the currently frozen mainline semantics.
2. Define typed schema objects for the canonical instance layer. At minimum, cover:
   - sets,
   - line data,
   - node metadata,
   - economic parameters,
   - EV parameters,
   - ambiguity parameters,
   - normal scenario tensors,
   - disaster scenario tensors,
   - canonical instance container.
3. Implement an adapter that reads the runtime source-of-truth layers using this precedence:
   - schema/loader behavior from `m1_data_setup.py`
   - runtime numeric params from `parameters.json`
   - actual scenario support from live CSV contents
4. Implement explicit validation for the default runtime fixture contract:
   - default expected runtime support is `scenarios_a = [1,2]`, `scenarios_b = [1,2]`
   - if the loaded CSV support disagrees with the default fixture, raise a clear validation error unless an explicit expanded-mode flag is enabled.
5. Build topology helpers for the IEEE 33-bus radial network:
   - root identification via frozen config,
   - parent/child maps,
   - downstream-line lookup,
   - radiality checks.
6. Implement stable integer/string index maps for buses, lines, regions, normal times, disaster times, scenarios.
7. Implement explicit fail-fast validation rules, including at least:
   - line count vs parameter vector length consistency,
   - scenario tensor completeness,
   - valid bus ids in critical list when provided,
   - no direct fallback from `ambig.w` to paper `critical_buses`.
8. The schema must preserve the fact that `critical_buses` is a required external paper-level input for the disaster objective.
   - It is acceptable for generic instance loading to proceed with `critical_buses=None`.
   - It is **not** acceptable for later disaster-objective construction to proceed without an explicit validation call that raises.
9. Provide clear error messages designed for debugging, not vague assertions.

## Frozen semantics to encode
Use the following as the new-repo contract:

```yaml
source_of_truth:
  schema_and_loader: m1_data_setup.py
  runtime_numeric_params: parameters.json
  scenario_index_source: csv_contents_then_validate_against_json

default_runtime_fixture:
  instance_id: local_tested_small_v1
  scenarios_a: [1, 2]
  scenarios_b: [1, 2]
  expanded_scenario_packages: opt_in_only
  on_support_mismatch: raise_explicit_validation_error

economics:
  Cunmet: 3.0
  annualize_normal_cost_by_365: true
  annualize_disaster_cost_by_365: false
  Ctrans_mode: time_vector
  power_unit: kW

network_freeze:
  root_bus: 1
  candidate_buses: all_except_root
  allow_evcs_at_root: false
  v_ref_sq: 1.0

ambiguity_freeze:
  p_bar_equals_FP: true
  use_ambig_w_in_paper_model: false
  ambig_w_meaning: legacy engineering weight in old repo only, not the paper CLS_n contract

disaster_objective_freeze:
  critical_buses: REQUIRED_EXTERNAL_INPUT
  CLS_critical: 50.0
  CLS_noncritical: 10.0
```

## Specific implementation guidance
1. Prefer dataclasses or similarly transparent typed containers.
2. Keep parsing/adapter code separate from validation logic.
3. Keep topology logic separate from scenario tensor logic.
4. Store both original labels and normalized indices where helpful for debugging.
5. Favor explicit helper functions over clever abstractions.
6. Make all validation errors deterministic and human-readable.
7. Do not implement solver models in this round.

## Acceptance tests
Run all of the following and record outputs in the round report:

```bash
pytest tests/unit/test_freeze_contract.py -q
pytest tests/unit/test_network_topology.py -q
pytest tests/unit/test_indexer.py -q
pytest tests/unit/test_validators.py -q
pytest tests/integration/test_instance_loading.py -q
pytest -q
```

## Required test content
Your tests must explicitly cover:
1. successful construction of a valid toy frozen config,
2. rejection of missing/invalid runtime fields,
3. topology helper correctness on the IEEE 33-bus radial structure,
4. deterministic index ordering,
5. scenario-support mismatch detection for the default `{1,2}` fixture contract,
6. proof that `critical_buses` is not inferred from `ambig.w`.

## Deliverables
1. Working instance-layer implementation.
2. Passing tests.
3. `docs/reports/round_01_report.md`.

## Report format
The report **must** contain these sections:

```md
# Round 01 Report

## Files changed
- ...

## Schema / contract decisions
- ...

## Validation behavior
- ...

## Tests run
- command
- result

## Known limitations
- ...

## Ready interfaces for Round 02
- ...
```

## Definition of done for this round
This round is complete only if:
- canonical instance loading exists,
- topology + index helpers are implemented,
- fail-fast validation exists,
- the default small-fixture contract is enforced,
- `critical_buses` remains an explicit external paper-level input rather than an inferred field.
