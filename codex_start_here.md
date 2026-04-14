# START HERE for Codex

This repository implements a paper-faithful mainline for:

**Two-Stage Hybrid DRO-Stochastic Optimization for Resilient EV Charging Station Planning**.

## Your role

You are not redesigning the math. You are implementing the new mainline under a strict spec.

## Read in this order

1. `docs/spec/00_freeze_contract.md`
2. `docs/spec/01_architecture.md`
3. `docs/spec/02_equation_registry.md`
4. `docs/spec/03_data_contract.md`
5. `docs/spec/04_test_strategy.md`
6. `docs/spec/05_round_protocol.md`
7. `reference/main_paper.pdf`
8. `reference/tex/Section-IV-Solution.tex`
9. `reference/tex/Section-Appendix.tex`
10. `docs/tasks/<current_round>.md`

## Source-of-truth hierarchy

- `m1_data_setup.py` is the source of loader behavior, schema shape, set-construction logic, and data-resolution rules.
- `parameters.json` is the source of live runtime numeric parameters.
- live scenario CSV contents are the source of actual scenario support, with explicit validation against JSON.
- If runtime declarations and CSV support disagree, raise the mismatch explicitly rather than guessing.

## Mainline freeze

- default runtime fixture: scenarios `{1,2}`
- `Cunmet = 3.0`
- `root_bus = 1`
- `candidate_buses = all_except_root`
- `allow_evcs_at_root = false`
- `v_ref_sq = 1.0`
- `p_bar_equals_FP = true`
- `use_ambig_w_in_paper_model = false`
- `critical_buses = REQUIRED_EXTERNAL_INPUT`
- `CLS_critical = 50.0`
- `CLS_noncritical = 10.0`

## Hard prohibitions

- Do not infer `critical_buses` from `ambig.w`.
- Do not use `ambig.w` as a paper `CLS_n` substitute.
- Do not silently expand the default runtime fixture.
- Do not modify `docs/spec/*` unless the current round explicitly allows it.
- Do not implement production disaster dual / separation / Benders before the reference validation rounds require them.

## Implementation philosophy

- shared bottom layer
- reference track for math verification
- production track for the main algorithm
- audit outputs for LP dumps, residuals, cut lineage, and iteration logs

## Deliverable discipline

For each round:

- only modify allowed files
- run required tests
- write the round report
- state conservative design decisions explicitly

