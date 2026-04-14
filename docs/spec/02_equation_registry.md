# 02 Equation Registry

## Purpose

This file maps paper equations to code responsibilities.  
The point is not to restate the whole paper, but to ensure that:

- every important mathematical block has a home in the codebase
- debugging can refer to equation groups directly
- task files can name equations unambiguously

Equation numbers below refer to the paper numbering in `main_paper.pdf`.

---

## 1. Top-level objective

### Eq. (9) Overall two-stage objective
Code owner:
- `src/production/master_problem.py`
- `src/production/benders_engine.py`

Meaning:
- first-stage construction cost
- normal-operation expected recourse
- disaster-stage worst-case DRO recourse

Notes:
- the normal and disaster parts must remain separate in code
- disaster recourse enters the master through the dualized outer term

---

## 2. First-stage planning

### Eq. (10) Annualized construction cost
Code owner:
- `src/production/first_stage.py`

Key quantities:
- `z_n`
- `n_sl_n`
- `n_fa_n`
- annualization factor

### Eq. (11) Minimum charger requirement
Code owner:
- `src/production/first_stage.py`

### Eq. (12) Installation bounds
Code owner:
- `src/production/first_stage.py`

---

## 3. Normal-operation recourse

### Eq. (13) Normal recourse objective decomposition
Code owner:
- `src/production/normal_block.py`

### Eq. (14) Transportation cost
Code owner:
- `src/production/normal_block.py`

### Eq. (15) Unmet charging demand penalty
Code owner:
- `src/production/normal_block.py`

### Eq. (16) Substation purchase cost
Code owner:
- `src/production/normal_block.py`

### Eq. (17) Demand assignment balance
Code owner:
- `src/production/normal_block.py`

### Eq. (18) Station capacity limits
Code owner:
- `src/production/normal_block.py`

### Eq. (19) Assignment-siting linkage
Code owner:
- `src/production/normal_block.py`

### Eq. (20) Active-power LinDistFlow balance
Code owner:
- `src/production/normal_block.py`

### Eq. (21) Reactive-power LinDistFlow balance
Code owner:
- `src/production/normal_block.py`

### Eq. (22) Substation power definition
Code owner:
- `src/production/normal_block.py`

### Eq. (23) Line flow limits
Code owner:
- `src/production/normal_block.py`

### Eq. (24) Voltage drop equation
Code owner:
- `src/production/normal_block.py`

### Eq. (25) Voltage bounds
Code owner:
- `src/production/normal_block.py`

---

## 4. Disaster-stage primal recourse

### Eq. (26) Disaster objective
Code owner:
- `src/reference/disaster_primal_ref.py`
- `src/production/disaster_dual_paper.py` (indirectly through dual coefficients)

Important freeze:
- `CLS_n` must be constructed from external `critical_buses`
- no fallback to `ambig.w`

### Eq. (27) Disaster active-power balance
Code owner:
- `src/reference/disaster_primal_ref.py`

### Eq. (28) Assignment discharging constraints
Code owner:
- `src/reference/disaster_primal_ref.py`

### Eq. (29) Station discharge capacity limits
Code owner:
- `src/reference/disaster_primal_ref.py`

### Eq. (30) Discharge assignment-siting linkage
Code owner:
- `src/reference/disaster_primal_ref.py`

### Eq. (31) Load shedding bounds
Code owner:
- `src/reference/disaster_primal_ref.py`

### Eq. (32) Outage-dependent line capacity
Code owner:
- `src/reference/disaster_primal_ref.py`

---

## 5. Sample-average approximation and compact disaster reformulation

### Eq. (33) SAA sampled problem
Code owner:
- `src/production/master_problem.py`
- `src/production/benders_engine.py`

### Eq. (34) Dual feasible region
Code owner:
- `src/reference/disaster_dual_auto.py`
- `src/production/disaster_dual_paper.py`

### Eq. (35) Dual representation of disaster recourse
Code owner:
- `src/reference/disaster_dual_auto.py`
- `src/production/disaster_dual_paper.py`

### Eq. (36) Aggregated cut coefficients
Code owner:
- `src/production/cut_factory.py`

Named quantities:
- `beta`
- `gamma`
- `phi`

---

## 6. Outer DRO reformulation

### Eq. (37) Moment dualization
Code owner:
- `src/reference/dro_outer_lp_oracle.py`
- `src/production/master_problem.py`

### Eq. (38) Semi-infinite formulation
Code owner:
- `src/production/master_problem.py`

---

## 7. Restricted master problem and separation

### Eq. (39) Restricted master problem
Code owner:
- `src/production/master_problem.py`

### Eq. (40) Bounds on `omega`
Code owner:
- `src/reference/outage_enumerator.py` (oracle checks)
- `src/production/separation_milp.py` (production usage)

### Eq. (41) Linearized separation MILP
Code owner:
- `src/production/separation_milp.py`

Key linearization objects:
- `delta`
- `omega`
- `tau`
- McCormick envelope constraints

---

## 8. Algorithm-level registry

### Algorithm 1 Cut generation procedure
Code owner:
- `src/production/benders_engine.py`

Expected iteration steps:
1. solve RMP
2. solve separation MILP
3. certify or continue
4. re-solve samplewise dual LPs at worst outage
5. build new cut
6. add cut to RMP
7. log iteration

---

## 9. Appendix proof hooks for validation

These are not production modules by themselves, but they motivate required tests.

### Proposition 1 Moment dualization
Validation hook:
- `tests/oracle/test_dro_outer_lp.py`

### Lemma 1 Budgeted support function
Validation hook:
- `tests/oracle/test_budget_support_fn.py`

### Proposition 2 Exact linearized separation
Validation hook:
- `tests/oracle/test_separation_exactness.py`

### Proposition 3 Finite exact reformulation
Validation hook:
- conceptual reference for cut-family finiteness
- used to justify termination logic

### Theorem 1 Finite termination under exact separation
Validation hook:
- `tests/integration/test_benders_vs_oracle.py`

### Theorem 2 epsilon-optimal termination
Validation hook:
- `tests/integration/test_epsilon_certificate.py`

---

## 10. Naming convention

Recommended internal names:

- `eq09_total_objective`
- `eq10_construction_cost`
- `eq11_min_charger_requirement`
- `eq12_installation_bounds`
- `eq17_charge_balance`
- `eq20_active_power_balance_normal`
- `eq27_active_power_balance_disaster`
- `eq32_outage_capacity`
- `eq35_disaster_dual_value`
- `eq39_rmp`
- `eq41_separation_milp`

Use these names in:
- constraint labels
- model dumps
- residual reports
- cut-audit logs
