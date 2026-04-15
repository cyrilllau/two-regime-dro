# Round 01.5 Report

## Files changed
- `.gitignore`
- `codex_start_here.md`
- `docs/spec/00_freeze_contract.md`
- `docs/spec/01_architecture.md`
- `docs/spec/03_data_contract.md`
- `docs/spec/04_test_strategy.md`
- `src/contracts/freeze.py`
- `src/instance/schema.py`
- `src/instance/canonical_instance.py`
- `src/instance/validators.py`
- `src/instance/loader_adapter.py`
- `src/instance/runtime_fixture.py`
- `src/instance/raw_package.py`
- `src/instance/manifest.py`
- `src/instance/selection.py`
- `tests/integration/test_instance_loading.py`
- `tests/unit/test_freeze_contract.py`
- `tests/unit/test_manifest.py`
- `tests/unit/test_selection.py`
- `tests/fixtures/runtime_12/README.md`
- `tests/fixtures/toy_config_valid.yaml`
- `tests/fixtures/toy_config_missing_critical.yaml`
- `tests/fixtures/selection_default_small.yaml`
- `tests/fixtures/selection_expanded_10.yaml`
- `tests/fixtures/selection_invalid_missing_csv.yaml`
- `tests/fixtures/selection_invalid_missing_json.yaml`
- `docs/reports/round_01_5_report.md`

## Spec changes made in this round
- Rewrote the contract so the default `{1,2}` mainline fixture is a default runtime selection preset, not a raw-package equality rule.
- Froze the policy that JSON-declared scenario support in `parameters.json` is advisory manifest metadata.
- Froze the policy that CSV support is the binding raw-availability source for whether a selected scenario exists.
- Added the explicit three-step instance boundary to the architecture/data contract:
  - `load_raw_data_package(...)`
  - `inspect_available_support(...)`
  - `build_canonical_instance(..., selection=...)`
- Updated the test strategy so Phase 0-1 explicitly covers raw-package vs selection separation.

## Design decisions
- Added `RawDataPackage` so JSON/CSV loading no longer decides scenario usage.
- Added `RuntimeSupportManifest` and `StageSupportManifest` so declared support and CSV support are stored separately and compared explicitly.
- Added `RuntimeSelection` plus default and expanded selection helpers.
- Kept `expanded_mode` only as a convenience selector for full-CSV support; default behavior is now selection-first rather than raw-support equality checking.
- Canonical tensors are now built only for the resolved selected subset; unselected raw scenarios never enter the canonical dense tensors.
- Kept `critical_buses` semantics unchanged: generic instance loading may succeed without them, but disaster-objective readiness still fails fast if they are missing.
- Fixed the `.gitignore` rule from `instance/` to `/instance/` so `src/instance/` is visible in normal `git status`.

## Tests run
- `pytest tests/unit/test_freeze_contract.py -q`
  - Result: `3 passed in 0.01s`
- `pytest tests/unit/test_network_topology.py -q`
  - Result: `2 passed in 0.02s`
- `pytest tests/unit/test_indexer.py -q`
  - Result: `2 passed in 0.03s`
- `pytest tests/unit/test_validators.py -q`
  - Result: `3 passed in 0.03s`
- `pytest tests/unit/test_manifest.py -q`
  - Result: `2 passed in 0.07s`
- `pytest tests/unit/test_selection.py -q`
  - Result: `4 passed in 0.07s`
- `pytest tests/integration/test_instance_loading.py -q`
  - Result: `7 passed in 0.21s`
- `pytest -q`
  - Result: `56 passed in 0.31s`

## Runtime-package behavior after refactor
- `data/runtime_12/` now loads successfully under the default runtime selection preset `{1,2}` without any manual edits to raw data.
- The raw package still exposes the full CSV reservoir:
  - normal CSV support = `1..10`
  - disaster CSV support = `1..10`
- The manifest records:
  - normal declared support = `1..10`
  - normal CSV support = `1..10`
  - disaster declared support = `(1, 2)`
  - disaster CSV support = `1..10`
- The disaster-stage JSON/CSV disagreement is surfaced explicitly in manifest metadata and in the canonical instance metadata.
- Canonical tensors under default loading contain only selected scenarios `{1,2}`.
- Requesting a scenario absent from CSV support remains a fatal validation error before canonical tensor build.
- Selecting a scenario that exists in CSV but is absent from JSON declaration is allowed under the Round 01.5 advisory-metadata policy.

## Known limitations
- No optimization model, dualization, or solver logic was implemented in this round.
- JSON/CSV support disagreement is only reported in manifest metadata and instance metadata; there is no separate report exporter yet.
- There is no optional strict mode yet for treating JSON-declared support as binding; that can be added later if the project wants it.
- Generic instance loading still does not synthesize disaster-objective readiness because `critical_buses` remains external input.

## Open issues for next round
- Downstream model rounds should consume the new three-step boundary rather than reading scenario support directly from raw parameters.
- If future rounds need user-facing diagnostics, add a dedicated manifest/report formatter instead of relying on `metadata["support_manifest"]`.
- If larger scenario packages become a normal workflow, consider an explicit runtime selection config file path in the public loader API instead of passing `RuntimeSelection` objects directly.
