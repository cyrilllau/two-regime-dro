# 00 Freeze Contract

## Purpose

This file is the implementation contract for the new paper-faithful mainline.  
Its job is to freeze the project-level semantics that Codex must **not** invent,
override, or infer from legacy engineering shortcuts.

This file has higher authority than any round task file on questions of:
- source-of-truth hierarchy
- runtime fixture defaults
- ambiguity-set semantics
- paper-level disaster objective semantics
- prohibited inferences

## Scope boundary

The new repo is **not** organized around the old codebase.  
The old codebase is useful only as:
1. a data/loader/schema reference, and
2. a source of debugging lessons from the `{1,2}` local tested instance.

The old codebase is **not** the semantic authority for the new mainline disaster objective.

---

## 1. Source-of-truth hierarchy

Use three layers, with strict precedence:

1. `m1_data_setup.py`
   - source of loader behavior
   - source of schema shape
   - source of set-construction logic
   - source of data-resolution rules
   - **not** the source of the live runtime numeric instance

2. `parameters.json`
   - source of live runtime numeric parameters
   - source of base set declarations
   - scenario-support declarations are advisory metadata for manifest/reporting

3. live scenario CSV contents
   - source of raw scenario index availability
   - must be compared explicitly against `parameters.json`
   - if JSON and CSV disagree, the mismatch must be surfaced explicitly in manifest/reporting

4. runtime selection config / fixture logic
   - source of which scenarios are used in this run
   - must be bounded by CSV availability
   - does not change raw package contents

Interpretation:
- `m1_data_setup.py` = schema/loader truth
- `parameters.json` = runtime numeric-parameter truth
- CSV contents = raw scenario reservoir truth
- runtime selection = chosen subset for canonicalization

---

## 2. Mainline default runtime selection preset

The first mainline implementation is frozen to the locally tested small instance.

```yaml
default_runtime_fixture:
  instance_id: "local_tested_small_v1"
  scenarios_a: [1, 2]
  scenarios_b: [1, 2]
  expanded_scenario_packages: "opt_in_only"
  on_support_mismatch: "raise_explicit_validation_error"
```

Important:
- The default mainline must select the `{1,2}` tested subset.
- The raw CSV reservoir is allowed to contain more support than `{1,2}`.
- Larger scenario packages are allowed later, but only via explicit opt-in.
- Codex must never silently upgrade the default selection preset to a larger scenario package.
- JSON/CSV support disagreement is not by itself a fatal load error when the selected subset is available from CSV.

---

## 3. Frozen economics and cost-time semantics

```yaml
economics:
  Cunmet: 3.0
  annualize_normal_cost_by_365: true
  annualize_disaster_cost_by_365: false
  Ctrans_mode: "time_vector"
  power_unit: "kW"
```

Semantics:
- `Cunmet = 3.0` is an explicit mainline freeze input.
- It must not be guessed from unrelated legacy fields.
- Normal-operation costs are annualized by 365.
- Disaster-stage recourse is weighted by disaster probability and is **not** separately annualized by 365.
- `Ctrans` is interpreted as a time-indexed vector in the current mainline contract.

---

## 4. Frozen network semantics

```yaml
network_freeze:
  root_bus: 1
  candidate_buses: "all_except_root"
  allow_evcs_at_root: false
  v_ref_sq: 1.0
```

Rules:
- `root_bus` is fixed at 1.
- Candidate siting buses default to all buses except the root.
- EVCS installation at the root is prohibited in the default mainline.
- The squared reference voltage is fixed at 1.0 unless a future explicit freeze changes it.

---

## 5. Frozen ambiguity-set semantics

```yaml
ambiguity_freeze:
  p_bar_equals_FP: true
  use_ambig_w_in_paper_model: false
  ambig_w_meaning: "legacy engineering weight in old repo only, not the paper CLS_n contract"
```

Interpretation:
- `ambig.p_bar` is the paper-level linewise marginal outage upper-bound vector `FP`.
- `ambig.w` is legacy only.
- `ambig.w` must not enter the new paper-faithful disaster objective.

---

## 6. Frozen disaster objective semantics

```yaml
disaster_objective_freeze:
  critical_buses: REQUIRED_EXTERNAL_INPUT
  CLS_critical: 50.0
  CLS_noncritical: 10.0
```

This is the only remaining required paper-level external input:
- `critical_buses` must come from the user/config layer.
- There is no authorized default derived from the old repo.
- There is no fallback to `ambig.w`.

---

## 7. Prohibited inferences

The following are forbidden:

```yaml
prohibited_inference:
  infer_critical_buses_from_ambig_w: false
  fallback_to_ambig_w_when_critical_buses_missing: false
  synthesize_paper_CLS_from_old_repo_weights: false
  auto_expand_default_fixture_from_csv_support: false
```

Codex must not:
- infer `critical_buses` from `ambig.w`
- use `ambig.w` as a substitute for paper `CLS_n`
- silently broaden the default `{1,2}` selection preset
- treat JSON-declared support as the controller of runtime selection
- patch semantic mismatches by guessing

---

## 8. Fail-fast requirements

The implementation must raise a configuration or validation error before model build if any of the following occurs:

- missing `critical_buses`
- a `critical_buses` entry is not a valid bus id
- malformed runtime selection
- selected scenario absent from CSV availability
- topology is not a single-root radial tree
- `p_bar` length does not match line count
- missing required scenario tensors for the selected support

---

## 9. Relationship to the paper reference

This freeze contract is intended to preserve a paper-faithful mainline for:
- first-stage EVCS siting/sizing
- normal-operation explicit recourse
- disaster-stage dualized DRO recourse
- Benders-like cut generation

Where the old repo and the paper disagree semantically, the new repo follows:
1. this freeze contract,
2. the paper math,
3. explicit configuration,
not legacy engineering shortcuts.
