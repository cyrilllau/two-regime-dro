---
name: optimization-paper-results
description: Use when turning optimization experiment outputs into paper-facing tables, figures, claims, and IEEE-style experiment-section prose, especially when distinguishing raw comparable metrics from training objectives, separating diagnostics from main-text evidence, and ensuring every paper claim traces to logs, configs, figures, and certificates.
metadata:
  short-description: Convert optimization results into paper-ready evidence
---

# Optimization Paper Results

Use this skill after an optimization experiment has produced candidate results,
or when writing/reviewing a paper subsection from experiment artifacts. Pair it
with `optimization-calibration-search` when the result story is not yet good
enough, and with `optimization-algorithm-acceleration` when convergence or
runtime is the blocker.

## Core Workflow

1. **Lock the paper claim.** State exactly what the table/figure is supposed to
   prove, which benchmark is used, and what would falsify the claim.
2. **Separate training from reporting.** Optimization objectives, penalty
   multipliers, relaxations, and auxiliary certificates may guide training, but
   paper tables must use raw comparable metrics under a common evaluator.
3. **Build component-complete tables.** Report objective components, first-stage
   design variables, feasibility/certificate status, and runtime if relevant.
4. **Use a common ex-post evaluator.** Freeze each plan and replay all methods
   under the same scenarios, ambiguity set, seeds, units, solver tolerance, and
   hardware before making cross-method claims.
5. **Write mechanism, not inventory.** Each result paragraph should identify
   what changed, quantify the component changes, explain the physical or
   algorithmic reason, and state the supported claim boundary.
6. **Keep diagnostics out of the main story.** Diagnostic rows, failed regimes,
   stress tests, and caveats belong in decision cards or appendices unless they
   are required to avoid a misleading paper claim.
7. **Audit traceability.** Every number in the manuscript must trace to a
   manifest, config, summary row, raw log, figure source, and certificate.

## Paper-Ready Gates

Reject the result as paper-facing if any of these hold:

- compared methods use different reporting evaluators or units;
- training objectives are compared directly as performance metrics;
- a component table omits a material term such as investment, operating cost,
  unmet demand, risk/resilience, or runtime/certificate fields;
- the benchmark definition is ambiguous or weaker than what the claim implies;
- figures show only aggregate trends when the mechanism depends on topology,
  allocation, active constraints, or scenario/outage support;
- certified and diagnostic rows are mixed in prose;
- the section reads like a run log rather than an academic case study.

## Writing Pattern

For each paragraph:

1. Name the comparison.
2. Report the few numbers that matter.
3. Explain the mechanism behind the change.
4. Connect the mechanism to the model or algorithm contribution.
5. State the claim boundary if the evidence is certified only for part of the
   stress range.

Use `references/result-section-checklist.md` for a detailed paper-facing audit
and `references/claim-language.md` for safe wording.
