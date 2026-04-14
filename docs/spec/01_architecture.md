# 01 Architecture

## Purpose

This file defines the high-level structure of the new mainline repo.  
The goal is not minimal code size; the goal is a structure that is easy to:
- debug
- audit
- verify mathematically
- grow over multiple Codex rounds without semantic drift

The core design choice is:

> shared foundation + dual tracks  
> reference track for proof and audit, production track for the main algorithm

---

## 1. Design principles

### 1.1 Not organized around the old repo

The old repo is not the architectural template.

The new repo is organized around:
- the paper's mathematical decomposition
- validation and audit needs
- clean separation between data normalization and model construction
- clean separation between reference and production implementations

### 1.2 Shared foundation

Both tracks must share:
- the same canonical instance
- the same index system
- the same network topology object
- the same freeze config
- the same equation registry

This ensures that any disagreement is a math/model disagreement, not a data-meaning disagreement.

### 1.3 Reference before production

The production implementation may only be trusted after the corresponding reference implementation and validation chain exist.

This is especially strict for:
- disaster dualization
- separation MILP
- cut extraction
- Benders engine

---

## 2. Top-level layout

Recommended layout:

```text
repo/
  reference/
    main_paper.pdf
    tex/

  docs/
    spec/
    tasks/
    reports/

  src/
    instance/
    contracts/
    reference/
    production/
    audit/

  tests/
    unit/
    integration/
    oracle/
    fixtures/

  codex_start_here.md
```

---

## 3. Module responsibilities

## 3.1 `src/instance/`

This layer is the only place that may touch raw JSON/CSV loader semantics.

Responsibilities:
- read raw data
- apply source-of-truth hierarchy
- build canonical internal objects
- validate shape and topology
- construct stable index maps

Non-responsibilities:
- no optimization
- no dualization
- no implicit paper-level inference

Key expected modules:
- `schema.py`
- `canonical_instance.py`
- `validators.py`
- `indexer.py`
- `network_topology.py`

---

## 3.2 `src/contracts/`

This layer stores project-wide contracts.

Responsibilities:
- freeze contract access
- equation registry
- naming conventions
- validation policy

Key expected modules:
- `freeze.py`
- `equation_registry.py`
- `naming.py`

---

## 3.3 `src/reference/`

This is the audit track.  
It may be slower, but it must be transparent and mathematically checkable.

Core purpose:
- prove that the disaster recourse and its dualization are implemented correctly

Key expected modules:
- `disaster_primal_ref.py`
- `lp_canonicalizer.py`
- `disaster_dual_auto.py`
- `kkt_checks.py`
- `outage_enumerator.py`
- `dro_outer_lp_oracle.py`

---

## 3.4 `src/production/`

This is the main algorithm track.

Core purpose:
- implement the paper-faithful operational mainline
- solve the actual planning problem using the decomposition structure

Key expected modules:
- `first_stage.py`
- `normal_block.py`
- `disaster_dual_paper.py`
- `separation_milp.py`
- `cut_factory.py`
- `master_problem.py`
- `benders_engine.py`

---

## 3.5 `src/audit/`

This layer produces evidence.

Core purpose:
- make debugging and post-mortem diagnosis easy
- preserve proof artifacts for each important model block

Key expected modules:
- `model_dump.py`
- `residual_report.py`
- `cut_audit.py`
- `iteration_log.py`

---

## 4. Separation of concerns

### 4.1 Data does not define math

`src/instance/` is allowed to define:
- what objects exist
- how indices are normalized
- which raw file populates which tensor

It is not allowed to define:
- the disaster objective semantics
- critical-node meaning
- how dual variables are interpreted

### 4.2 Reference does not optimize for speed

The reference track exists to validate:
- primal feasibility
- dual feasibility
- strong duality
- exact separation on tiny cases

### 4.3 Production does not rewrite the reference story

The production track should mirror the paper's tractable formulation, but it must be checked against the reference track.

---

## 5. Import discipline

The intended dependency direction is:

```text
src/instance  --> shared canonical objects
src/contracts --> shared contracts

src/reference --> depends on instance + contracts
src/production --> depends on instance + contracts
src/audit --> may depend on both reference and production

tests --> may depend on all of the above
```

Forbidden patterns:
- `src/instance` importing `src/production`
- `src/reference` mutating production models
- `src/production` reading raw CSV/JSON directly

---

## 6. Paper decomposition reflected in code

The architecture must preserve the paper structure:

1. first-stage siting/sizing
2. normal-operation explicit recourse
3. disaster-stage recourse
4. dualization of disaster-stage recourse
5. outer DRO reformulation
6. RMP + separation + cut generation

That is why disaster primal, auto-dual, paper-dual, and separation are separate modules rather than a single black-box optimizer.

---

## 7. Repository onboarding flow

The recommended first-read order for Codex is:

1. `codex_start_here.md`
2. `docs/spec/00_freeze_contract.md`
3. `docs/spec/01_architecture.md`
4. `docs/spec/02_equation_registry.md`
5. `docs/spec/03_data_contract.md`
6. `docs/spec/04_test_strategy.md`
7. `docs/spec/05_round_protocol.md`
8. `reference/main_paper.pdf`
9. selected TeX sections
10. current round task file

This makes the paper the math reference and the spec files the implementation contract.
