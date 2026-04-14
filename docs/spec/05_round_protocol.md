# 05 Round Protocol

## Purpose

This file defines how multi-round collaboration with Codex is managed.

The project is intentionally too large for a single undirected prompt.  
Therefore the repo is built round by round, with each round proving exactly one bounded obligation.

---

## 1. Roles

## 1.1 ChatGPT
Responsible for:
- maintaining stable spec files
- defining round scope
- writing task files
- reviewing Codex outputs
- approving, revising, or rejecting a round

## 1.2 User
Responsible for:
- passing round task files to Codex
- returning changed files, test results, and round reports
- supplying explicit external inputs when required
- keeping spec files stable during a round

## 1.3 Codex
Responsible for:
- implementing the current round only
- modifying only the allowed files
- running the required tests
- writing the required round report
- not changing stable spec files unless explicitly instructed

---

## 2. Round philosophy

Each round must satisfy all of the following:

1. one bounded objective
2. an explicit file scope
3. explicit acceptance tests
4. explicit deliverables
5. a written report

A round is not "done" just because code exists.

---

## 3. Required task-file format

Each file under `docs/tasks/` must follow this structure:

```md
# Round XX - Title

## Objective
A single bounded objective.

## Allowed files to create/update
Only these files may be changed.

## Do not modify
Protected files and directories.

## Required behavior
What must be true when the round is complete.

## Acceptance tests
Commands or checks that must pass.

## Deliverables
Code, tests, report, and any required audit artifacts.

## Report format
The exact required structure of the round report.
```

This format exists to constrain Codex's freedom and preserve semantic stability.

---

## 4. Required report-file format

Each file under `docs/reports/` must include at least:

```md
# Round XX Report

## Files changed
- ...

## Design decisions
- ...

## Tests run
- command
- result

## Known limitations
- ...

## Open issues for next round
- ...
```

If a round contains model or solver logic, the report should also include:
- any LP/MPS dump path
- objective comparisons
- residual summary
- unresolved numerical concerns

---

## 5. Round gatekeeping rules

### 5.1 Stable spec files are protected
Codex may not edit:
- `docs/spec/*`
unless the task file explicitly permits it.

### 5.2 One proof obligation per round
Examples of valid rounds:
- build canonical instance layer
- implement disaster primal reference
- build auto dual and strong-duality tests

Examples of invalid rounds:
- build primal, dual, separation, and Benders engine all at once

### 5.3 Production after reference
Production implementations of the following may only proceed after the relevant reference checks exist:
- `disaster_dual_paper`
- `separation_milp`
- `cut_factory`
- `benders_engine`

### 5.4 No silent semantic patching
If Codex encounters a mismatch:
- between JSON and CSV support
- between task instructions and freeze contract
- between missing external config and model requirements

it must surface the issue explicitly rather than guessing.

---

## 6. Recommended round sequence

The recommended early sequence is:

1. Round 00: repo bootstrap
2. Round 01: canonical instance layer
3. Round 02: disaster primal reference
4. Round 03: auto dual + KKT checks
5. Round 04: hand-coded paper dual
6. Round 05: separation MILP + oracle checks
7. Round 06: first-stage + normal block
8. Round 07: master problem
9. Round 08: cut factory + single-iteration flow
10. Round 09: full Benders engine

---

## 7. How the user should hand off a round

Recommended flow:

1. place the stable spec files in the repo
2. place reference materials in `reference/`
3. place the current round task file in `docs/tasks/`
4. send Codex a prompt telling it to:
   - read onboarding/spec files
   - read the current round task file
   - implement this round only
   - run tests
   - write the round report

---

## 8. Review checklist after Codex returns

Before accepting a round, verify:

- did Codex edit only allowed files?
- did it respect the freeze contract?
- did it run the required tests?
- did it write the round report?
- are any unresolved issues clearly stated?
- does the implementation satisfy the round's proof obligation?

If any answer is "no", the round is not accepted.

---

## 9. Hard-stop conditions

A round must be rejected or revised if:
- Codex edits protected spec files
- Codex infers `critical_buses` from `ambig.w`
- Codex silently expands the default `{1,2}` fixture
- Codex skips required tests
- Codex mixes reference and production responsibilities without authorization

---

## 10. Success criterion for the protocol

The protocol is working correctly if:
- each round is small enough to review quickly
- failures are local and diagnosable
- the project accumulates proof, not just code
- reference and production tracks remain aligned
