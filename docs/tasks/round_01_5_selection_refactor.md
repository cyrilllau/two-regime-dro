# Round 01.5 - Decouple Raw Scenario Reservoir from Runtime Selection

## Objective
Refactor the instance layer so that raw data availability and runtime scenario selection are separate concerns.

This round must make the current `data/runtime_12/` package load successfully under the default small tested selection `{1,2}` **without requiring any manual edits to the raw CSV/JSON files**.

At the same time, this round must update the stable spec files so they reflect the correct architecture boundary:
- raw CSV/JSON files define what data is available
- runtime config selects which scenarios are used in this run
- canonical instance only contains the selected subset
- model code never decides how many scenarios to use

This round is still an instance/data-contract round only.
No optimization model, dualization, or solver logic may be implemented.

---

## Allowed files to create/update

### Stable spec files explicitly reopened for this round
- `docs/spec/00_freeze_contract.md`
- `docs/spec/01_architecture.md`
- `docs/spec/03_data_contract.md`
- `docs/spec/04_test_strategy.md`
- `codex_start_here.md`

### Repo plumbing
- `.gitignore`

### Instance / contracts code
- `src/contracts/freeze.py`
- `src/contracts/naming.py`
- `src/instance/schema.py`
- `src/instance/canonical_instance.py`
- `src/instance/validators.py`
- `src/instance/indexer.py`
- `src/instance/network_topology.py`
- `src/instance/loader_adapter.py`
- `src/instance/runtime_fixture.py`
- `src/instance/raw_package.py`   
- `src/instance/manifest.py`
- `src/instance/selection.py`

### Tests and test fixtures
- `tests/unit/test_freeze_contract.py`
- `tests/unit/test_validators.py`
- `tests/unit/test_indexer.py`
- `tests/unit/test_network_topology.py`
- `tests/unit/test_manifest.py`
- `tests/unit/test_selection.py`
- `tests/integration/test_instance_loading.py`
- `tests/fixtures/runtime_12/README.md`
- `tests/fixtures/toy_config_valid.yaml`
- `tests/fixtures/toy_config_missing_critical.yaml`
- `tests/fixtures/selection_default_small.yaml`
- `tests/fixtures/selection_expanded_10.yaml`
- `tests/fixtures/selection_invalid_missing_csv.yaml`
- `tests/fixtures/selection_invalid_missing_json.yaml`

### Round report
- `docs/reports/round_01_5_report.md`

---

## Do not modify
- `docs/spec/02_equation_registry.md`
- `docs/spec/05_round_protocol.md`
- `docs/tasks/*` except creating this round's report path if needed
- anything under `src/reference/`
- anything under `src/production/`
- anything under `src/audit/`
- raw runtime data files under `data/`
- the paper / TeX reference files

---

## Required behavior

### A. Architecture boundary
Implement and expose a three-step instance-loading boundary:

1. `load_raw_data_package(...)`
   - reads raw JSON/CSV inputs
   - does **not** decide which scenarios are used

2. `inspect_available_support(...)`
   - constructs a manifest of raw availability
   - records separately, per stage:
     - declared scenario support from `parameters.json`
     - actual scenario support from CSV contents
   - records explicit mismatch metadata when they disagree
   - does **not** fail merely because raw support is larger than the default small fixture

3. `build_canonical_instance(..., selection=...)`
   - takes an explicit runtime selection
   - materializes only the selected subset into canonical tensors
   - the model-facing object must not carry unselected scenario rows into the tensors

A convenience loader may compose these steps, but the steps themselves must exist as independently testable functions/classes.

---

### B. Spec correction required in this round
Update the spec so the project contract reflects the correct separation:

1. The default `{1,2}` mainline fixture is a **default selection preset**, not a claim that raw CSV files may only contain `{1,2}`.
2. Extra raw scenario support in CSV files is allowed.
3. Runtime scenario usage is controlled by explicit selection config / fixture logic.
4. JSON-vs-CSV support disagreement must still be surfaced explicitly in manifest / validation outputs.
5. Such disagreement is **not** by itself a fatal error when the selected subset is valid and loadable.
6. Fatal errors occur when the selected subset is invalid for the current run, such as:
   - selected scenario absent from CSV support
   - malformed selection config
   - selected tensor entries required by canonicalization cannot be materialized

For this round, freeze the policy explicitly as follows:
- JSON-declared scenario support in `parameters.json` is **advisory manifest metadata**, not the controller of runtime scenario selection
- runtime scenario selection is controlled by config / fixture logic
- CSV support is the binding raw-availability source for whether a selected scenario exists
- JSON/CSV support disagreement must be surfaced explicitly in manifest metadata and reports
- JSON/CSV disagreement is **not** by itself a fatal load error when the requested selected subset is available from CSV and can be canonicalized
- it is acceptable to add an optional strict mode later, but the default behavior in this round must be the non-strict policy above

Because the project goal is config-driven scenario selection, the required outcome is:
- raw reservoir availability is allowed to exceed the default small selection
- current `data/runtime_12/` loads successfully under the default selected subset `{1,2}`
- manifest metadata still reports the disaster-stage JSON/CSV disagreement

---

### C. Default runtime selection behavior
The default runtime fixture for the mainline remains:

```yaml
scenarios_a: [1, 2]
scenarios_b: [1, 2]
```

But the semantics must become:
- by default, select `{1,2}` from the raw reservoir
- do not require the raw reservoir itself to contain only `{1,2}`
- do not silently expand the selected subset to all available CSV scenarios

`load_default_runtime_fixture(...)` must use the default selection preset and must succeed on the current `data/runtime_12/` package without editing those raw files.

---

### D. Validation semantics
Implement explicit distinction between:
- raw support availability
- declared support metadata
- requested runtime selection
- canonical selected support

Validation must distinguish:
1. **Manifest mismatch**
   - JSON support and CSV support differ
   - must be surfaced explicitly in metadata/reporting
   - not necessarily fatal

2. **Selection error**
   - requested selection cannot be satisfied under the chosen policy
   - must be fatal before canonical instance build

3. **Canonicalization error**
   - selected rows exist conceptually but required tensor entries cannot be materialized
   - must be fatal

Keep all existing topology, shape, `p_bar` length, `critical_buses`, and no-`ambig.w` inference rules intact.

---

### E. `critical_buses` contract remains unchanged
Do not weaken this rule:
- `critical_buses` remains a required external paper-level input for disaster-objective readiness
- do not infer it from `ambig.w`
- generic instance loading may still succeed without it, but any explicit disaster-objective readiness gate must fail fast if it is missing

---

### F. `.gitignore` hygiene
Fix the existing `.gitignore` problem so `src/instance/` files are visible in ordinary `git status` and future rounds are not obscured.

---

## Acceptance tests
All of the following must pass.

### Existing coverage must still pass
- `pytest tests/unit/test_freeze_contract.py -q`
- `pytest tests/unit/test_network_topology.py -q`
- `pytest tests/unit/test_indexer.py -q`
- `pytest tests/unit/test_validators.py -q`
- `pytest tests/integration/test_instance_loading.py -q`

### New unit tests required
- `pytest tests/unit/test_manifest.py -q`
- `pytest tests/unit/test_selection.py -q`

### Full suite
- `pytest -q`

### Required behavioral checks
Your tests must prove all of the following:

1. A raw package with CSV support `1..10` can be loaded under a runtime selection `{1,2}`.
2. Extra raw support does not force the canonical instance to include unselected scenarios.
3. The current `data/runtime_12/` package loads successfully under the default small selection `{1,2}`.
4. The current `data/runtime_12/` package surfaces the disaster-stage JSON/CSV support disagreement as explicit manifest metadata.
5. Requesting a scenario that is absent from CSV support raises a clear validation error.
6. `critical_buses` is still never inferred from `ambig.w`.
7. `load_default_runtime_fixture(...)` uses selection semantics, not raw-package truncation or raw-package equality tests.

---

## Deliverables
- updated stable spec files reflecting the revised boundary
- refactored instance-layer code
- tests covering manifest vs selection behavior
- `.gitignore` fix
- `docs/reports/round_01_5_report.md`

---

## Report format
Write `docs/reports/round_01_5_report.md` with exactly these sections:

```md
# Round 01.5 Report

## Files changed
- ...

## Spec changes made in this round
- what semantic contract changed
- why the change was required
- confirm that JSON declared support is advisory metadata, not the runtime selection controller

## Design decisions
- raw package object
- manifest object
- selection object
- canonicalization flow

## Tests run
- command
- result

## Runtime-package behavior after refactor
- whether `data/runtime_12/` now loads under default selection
- what manifest mismatches are reported
- whether any mismatches remain fatal and why

## Known limitations
- ...

## Open issues for next round
- ...
```
