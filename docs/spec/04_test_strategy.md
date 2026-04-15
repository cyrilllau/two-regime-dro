# 04 Test Strategy

## Purpose

This file defines the project-wide testing strategy.

The goal is not just "the solver runs."  
The goal is:

- the data contract is enforced
- the disaster primal is correct
- the dualization is correct
- the separation reformulation is correct
- the production Benders mainline agrees with independent oracles on tiny cases

---

## 1. Core philosophy

The project uses layered validation.

A result is trusted only after it passes all relevant lower layers:

1. data contract validation
2. coefficient and model-shape validation
3. reference primal validation
4. primal/dual equivalence validation
5. oracle validation for outage/DRO pieces
6. end-to-end algorithm validation

This matters especially because the disaster block is dualized and then further embedded into a cut-generation algorithm.

---

## 2. Test layers

## 2.1 Data contract tests

Purpose:
- make sure the canonical instance is well-formed before any optimization is attempted

Typical checks:
- raw support manifest
- runtime selection validity
- selected-scenario tensor support
- tensor shape completeness
- radial topology
- line count and `p_bar` length consistency
- `critical_buses` validity
- default selection-preset enforcement

Expected location:
- `tests/unit/test_data_contract.py`
- `tests/unit/test_topology.py`

---

## 2.2 Coefficient assembly tests

Purpose:
- verify that the right variables and signs appear in the right equations

Typical checks:
- first-stage bounds and minimum charger constraints
- normal charge balance and station capacity coefficients
- disaster active-power balance signs
- outage line-capacity dependence on `delta`
- McCormick linearization structure

Expected location:
- `tests/unit/test_first_stage_coeffs.py`
- `tests/unit/test_normal_block_coeffs.py`
- `tests/unit/test_disaster_block_coeffs.py`
- `tests/unit/test_separation_coeffs.py`

---

## 2.3 Reference LP tests

Purpose:
- validate the fixed-outage disaster primal itself

Typical checks:
- feasibility on toy cases
- objective agreement with hand calculations
- load shedding and V2G dispatch sanity

Expected location:
- `tests/oracle/test_disaster_primal_ref.py`

---

## 2.4 Duality tests

Purpose:
- validate the dualization chain

Required comparisons:
1. `disaster_primal_ref` vs `disaster_dual_auto`
2. `disaster_dual_auto` vs `disaster_dual_paper`

Required checks:
- primal feasibility
- dual feasibility
- strong duality
- complementary slackness or equivalent residual check

Expected location:
- `tests/oracle/test_disaster_primal_dual.py`
- `tests/oracle/test_disaster_dual_paper.py`

---

## 2.5 Oracle tests for outage/DRO pieces

Purpose:
- validate the outer combinatorial/DRO reformulations independently of the production engine

Required checks:
- budgeted support function oracle
- outage enumeration oracle
- outer DRO LP oracle
- exactness of separation MILP on tiny cases

Expected location:
- `tests/oracle/test_budget_support_fn.py`
- `tests/oracle/test_dro_outer_lp.py`
- `tests/oracle/test_separation_exactness.py`

---

## 2.6 End-to-end algorithm tests

Purpose:
- validate the complete Benders-like mainline against brute-force oracles on very small instances

Required checks:
- same optimal objective as brute-force oracle
- same first-stage solution where identifiable
- valid epsilon-certificate logic
- monotone cut accumulation behavior

Expected location:
- `tests/integration/test_benders_vs_oracle.py`
- `tests/integration/test_epsilon_certificate.py`

---

## 3. Required toy cases

These toy cases are part of the strategy, even before the full mainline exists.

## T1 Zero-demand sanity
Purpose:
- no demand, no disaster support, no construction should be optimal

## T2 Minimum-3-charger activation
Purpose:
- verify Eq. (11) activates correctly and interacts correctly with unmet penalties

## T3 Fast/slow separation sanity
Purpose:
- verify fast demand cannot be served incorrectly by slow capacity

## T4 Distance-preference transportation case
Purpose:
- verify transportation assignment logic

## T5 Network bottleneck under normal operation
Purpose:
- verify line limits can force unmet demand

## T6 Disaster critical-load protection case
Purpose:
- verify disaster objective prefers preserving critical load when `CLS_critical > CLS_noncritical`

## T7 Budget support function hand-check
Purpose:
- verify `max_{delta in Omega(K)} v^T delta` reformulation

## T8 Outer-DRO tiny LP hand-check
Purpose:
- verify ambiguity-set outer maximization

## T9 Benders vs brute-force tiny end-to-end
Purpose:
- validate the whole algorithm on a tiny instance

---

## 4. Test progression by phase

### Phase 0-1
Focus:
- repo sanity
- data contract
- topology checks
- raw-package vs selection boundary

### Phase 2
Focus:
- disaster primal toy tests

### Phase 3
Focus:
- primal vs auto dual
- KKT checks

### Phase 4
Focus:
- auto dual vs hand-coded paper dual

### Phase 5
Focus:
- support-function oracle
- separation exactness

### Phase 6-9
Focus:
- normal block correctness
- RMP correctness
- full Benders vs oracle

---

## 5. Audit artifacts required during testing

When a model-level test fails, the code should make it easy to emit:
- LP/MPS dumps
- primal residual report
- dual residual report
- violated cut details
- outage vector used in the failing test

This is a project requirement, not an optional debug convenience.

---

## 6. Pass criteria

The project should not be considered mainline-complete unless all of the following hold:

1. data-contract tests pass
2. disaster primal toy tests pass
3. primal/auto-dual/paper-dual triangle passes
4. separation exactness tests pass on tiny instances
5. normal block tests pass
6. end-to-end Benders/oracle tests pass on tiny instances
7. default `{1,2}` fixture runs through the mainline without semantic contract violations
8. raw packages with larger CSV support can still load under the default `{1,2}` selection when the selected scenarios exist
