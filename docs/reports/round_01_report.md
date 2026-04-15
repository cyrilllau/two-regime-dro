# Round 01 Report

## Files changed
- `src/contracts/freeze.py`
- `src/contracts/naming.py`
- `src/instance/schema.py`
- `src/instance/canonical_instance.py`
- `src/instance/validators.py`
- `src/instance/indexer.py`
- `src/instance/network_topology.py`
- `src/instance/loader_adapter.py`
- `src/instance/runtime_fixture.py`
- `tests/unit/test_freeze_contract.py`
- `tests/unit/test_network_topology.py`
- `tests/unit/test_indexer.py`
- `tests/unit/test_validators.py`
- `tests/integration/test_instance_loading.py`
- `tests/fixtures/runtime_12/README.md`
- `tests/fixtures/toy_config_valid.yaml`
- `tests/fixtures/toy_config_missing_critical.yaml`
- `docs/reports/round_01_report.md`

## Schema / contract decisions
- Implemented a nested typed `FrozenConfig` contract instead of keeping freeze values as loose constants.
- Kept `critical_buses` as an explicit external paper-level input marker in the frozen contract; generic instance loading may leave it unset.
- Separated typed schema objects into sets, line data, node metadata, economic parameters, EV parameters, ambiguity parameters, and scenario tensor containers.
- Used `reference/legacy/m1_data_setup.py` only as the schema/loader-behavior reference:
  - IEEE 33-bus line ordering and topology shape
  - CSV column conventions
  - sparse-load behavior where omitted load entries mean zero after canonicalization
- Did not inherit legacy generator defaults such as `A_SCEN = 10` or `B_SCEN = 10` as live runtime truth.
- Added explicit loader entry points:
  - `src.instance.canonical_instance.load_canonical_instance`
  - `src.instance.runtime_fixture.load_default_runtime_fixture`

## Validation behavior
- Topology validation now fails before model build if the feeder is not a single-root radial tree.
- Linewise vector validation now checks `Rline`, `Xline`, `Pmax`, `Qmax`, and `ambig.p_bar` against the canonical line count.
- Distance-matrix validation checks the runtime `D` matrix shape against `(regions, buses)`.
- CSV-family support is validated per stage, then compared against:
  - declared support in `parameters.json`
  - the frozen default fixture `{1,2}` unless `expanded_mode=True`
- Sparse CSV tensors are normalized into dense canonical tensors by filling omitted entries with explicit zeros.
- `critical_buses` is never inferred from `ambig.w`.
- Disaster-objective readiness requires an explicit validation call and raises a clear error if `critical_buses` is missing.

Explicit runtime-data mismatches found in `data/runtime_12/`:
- Normal-stage:
  - `parameters.json` declares scenarios `1..10`
  - live normal CSV support is `1..10`
  - frozen default fixture requires `{1,2}`
  - result: default-mode loading raises a frozen-fixture mismatch
- Disaster-stage:
  - `parameters.json` declares scenarios `(1, 2)`
  - live disaster CSV support is `1..10`
  - frozen default fixture requires `{1,2}`
  - result: loading raises both a JSON/CSV support mismatch and a frozen-fixture mismatch
- Consequence:
  - `data/runtime_12/` does not load successfully under the default Round 01 contract
  - even with `expanded_mode=True`, the disaster-stage JSON/CSV support mismatch remains an explicit validation error

## Tests run
- `pytest tests/unit/test_freeze_contract.py -q`
- Result: `3 passed in 0.01s`
- `pytest tests/unit/test_network_topology.py -q`
- Result: `2 passed in 0.03s`
- `pytest tests/unit/test_indexer.py -q`
- Result: `2 passed in 0.02s`
- `pytest tests/unit/test_validators.py -q`
- Result: `3 passed in 0.02s`
- `pytest tests/integration/test_instance_loading.py -q`
- Result: `3 passed in 0.05s`
- `pytest -q`
- Result: `46 passed in 0.08s`

## Known limitations
- No optimization model objects were implemented in this round.
- The canonical instance layer does not attempt to repair live runtime-data support mismatches; it raises instead.
- `critical_buses` support is intentionally incomplete for disaster-objective use until an explicit external input is passed.
- The existing repository `.gitignore` ignores directories named `instance/`, so `src/instance/` changes may not appear in plain `git status` output.

## Ready interfaces for Round 02
- `load_canonical_instance(...)` provides a typed canonical instance boundary for the reference disaster-primal round.
- `NetworkTopology` now exposes:
  - `parent_by_bus`
  - `children_by_bus`
  - `downstream_lines_by_bus`
  - `bus_depth`
- `IndexMap` provides deterministic label-to-index mappings for buses, lines, regions, times, and scenarios.
- `require_explicit_critical_buses(...)` is ready to gate any later disaster-objective construction.
- The synthetic valid-runtime integration test provides a minimal working instance pattern for future reference-model tests.
