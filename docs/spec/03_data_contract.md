# 03 Data Contract

## Purpose

This file defines the canonical internal data contract for the new mainline.

The model layer must only consume canonical objects.  
No production or reference model may read raw CSV/JSON directly.

---

## 1. Authority order for data semantics

The data layer must follow the source-of-truth hierarchy from the freeze contract:

1. `m1_data_setup.py`
   - loader behavior
   - schema shape
   - set construction logic
   - raw data resolution rules

2. `parameters.json`
   - live numeric parameters
   - base set declarations

3. scenario CSV contents
   - actual realized scenario support
   - must be validated against declared support

The data layer must surface mismatches explicitly.

---

## 2. Raw input families

The expected raw inputs are:

### 2.1 Parameter layer
- `parameters.json`

### 2.2 Normal-operation scenario layer
- `normal_load_scenarios.csv`
- `normal_ev_demand_slow.csv`
- `normal_ev_demand_fast.csv`

### 2.3 Disaster-operation scenario layer
- `disaster_load_scenarios.csv`
- `disaster_ev_discharge_slow.csv`
- `disaster_ev_discharge_fast.csv`

### 2.4 External paper-level config layer
- `critical_buses` configuration file or equivalent explicit config object

This last item is required for paper-faithful disaster objective construction.

---

## 3. Canonical objects

The data layer must produce these canonical objects.

## 3.1 `FrozenConfig`

This object stores project-level frozen semantics, such as:
- default runtime fixture support
- `Cunmet`
- `root_bus`
- candidate-bus policy
- disaster objective freeze
- ambiguity semantics

It is not a raw-data object.  
It is the normalized config contract used by the rest of the codebase.

## 3.2 `CanonicalInstance`

This is the central normalized object.

Minimum contents:
- normalized sets
- network topology
- runtime numeric parameters
- ambiguity-set parameters
- distance matrix
- `CLS_n` vector derived from `critical_buses`
- scenario support metadata
- references to canonical scenario tensors

## 3.3 `NormalScenarioTensor`

Minimum normalized contents:
- `P_Load[a, t, n]`
- `Q_Load[a, t, n]`
- `DEV_ch_sl[a, t, o]`
- `DEV_ch_fa[a, t, o]`

## 3.4 `DisasterScenarioTensor`

Minimum normalized contents:
- `P_Load[b, ts, n]`
- `DEV_dis_sl[b, ts, o]`
- `DEV_dis_fa[b, ts, o]`

## 3.5 `NetworkTopology`

Minimum contents:
- line list with stable line ids
- parent/child relationships
- root bus
- downstream adjacency
- radiality validation results

## 3.6 `IndexMap`

Stable integer or label mappings for:
- buses
- lines
- regions
- normal times
- disaster times
- normal scenarios
- disaster scenarios

---

## 4. Runtime fixture semantics

The default mainline fixture is:

```yaml
scenarios_a: [1, 2]
scenarios_b: [1, 2]
```

The data layer must:
- load only this support by default
- reject undeclared support unless expanded mode is explicitly enabled
- report mismatches rather than silently guessing

---

## 5. Required units and shapes

## 5.1 Units
- power: `kW`
- reactive power: `kvar`
- voltage representation in the normal model: squared magnitude
- time step length must be explicit
- costs must be stored in a way consistent with the freeze contract

## 5.2 Shape expectations

### Normal tensors
- `P_Load[a, t, n]` must be defined for all loaded `(a, t, n)` combinations that belong to the canonical normal support
- `Q_Load[a, t, n]` same as above
- `DEV_ch_sl[a, t, o]` defined on loaded `(a, t, o)`
- `DEV_ch_fa[a, t, o]` defined on loaded `(a, t, o)`

### Disaster tensors
- `P_Load[b, ts, n]` defined on loaded `(b, ts, n)`
- `DEV_dis_sl[b, ts, o]` defined on loaded `(b, ts, o)`
- `DEV_dis_fa[b, ts, o]` defined on loaded `(b, ts, o)`

Sparse raw CSVs are allowed, but the canonicalizer must normalize missing entries explicitly according to the loader rules rather than leaving ambiguous holes.

---

## 6. Critical-node contract

`critical_buses` is not optional for the paper-faithful disaster objective.

Minimum accepted form:
```yaml
critical_buses:
  - 5
  - 9
  - 14
```

The canonicalizer must then build:
- `is_critical[n]`
- `CLS_n`

with:
- `CLS_n = CLS_critical` if `n in critical_buses`
- `CLS_n = CLS_noncritical` otherwise

Forbidden behavior:
- infer criticality from `ambig.w`
- infer criticality from load size
- infer criticality from graph position

---

## 7. Validation rules

The data layer must fail before model construction if any of the following holds:

- invalid or missing `critical_buses`
- duplicate bus ids in `critical_buses`
- bus id outside the bus set
- malformed line list
- topology is not a single-root tree
- `p_bar` length != number of lines
- distance matrix shape mismatch
- unsupported scenario indices under default fixture
- missing required normal/disaster tensor support

---

## 8. Canonicalizer behavior

The canonicalizer is allowed to:
- reorder indices into stable internal order
- fill explicit zero entries where loader rules imply absence means zero
- attach human-readable metadata for debugging

It is not allowed to:
- invent new scenario indices
- reinterpret `ambig.w` semantically
- change the default fixture support
- collapse paper-level categories without explicit freeze support

---

## 9. Model boundary

Everything below must receive only canonical objects:
- reference primal
- reference dual
- production dual
- separation MILP
- master problem
- Benders engine

This is a hard boundary.
