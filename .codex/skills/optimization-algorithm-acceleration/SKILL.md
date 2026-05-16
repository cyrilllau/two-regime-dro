---
name: optimization-algorithm-acceleration
description: Use when an optimization algorithm, decomposition method, Benders loop, column generation, separation oracle, or MIP workflow fails to converge or scale; guides engineering-first acceleration, bottleneck diagnosis, Pro-reviewed mathematical changes, certificate preservation, and paper-facing scalability reporting.
metadata:
  short-description: Diagnose and accelerate optimization algorithms safely
---

# Optimization Algorithm Acceleration

Use this skill when runtime, convergence, separation, cut quality, or
certificate closure becomes the bottleneck. It is designed for decomposition
algorithms where a fast-looking heuristic must not be confused with a valid
certificate.

## Acceleration Order

1. **Snapshot first.** Create a restore point: branch, commit, config, logs,
   paper artifacts, and dirty patch. Never let acceleration experiments pollute
   the accepted paper pack.
2. **Measure before changing.** Build runtime decomposition and iteration
   traces: master time, separation time, cut generation, active-set overhead,
   violation/gap, cuts, nodes, statuses, and incumbent objective.
3. **Exhaust low-risk engineering.** Try resume/continuation, warm starts,
   solver parameter exposure, cut deduplication, metadata-guarded cut-pool
   reuse, checkpointing, and top-M policy ablation.
4. **Classify the bottleneck.** Decide whether the blocker is master MIP,
   separation MIP, weak cuts, duplicate cuts, bound closure, memory/state size,
   or certificate semantics.
5. **Ask Pro before math changes.** Stabilization, Pareto/Magnanti-Wong cuts,
   trust regions, scenario screening, active-set certification, omega-bound
   tightening, and cut deletion require mathematical review.
6. **Implement behind flags.** Keep each acceleration switchable and write all
   probes under local engineering results until validated.
7. **Preserve certificate semantics.** Auxiliary or heuristic points can
   generate valid cuts, but final claims must use a canonical full-support
   certificate or a proved upper/lower-bound gap certificate.
8. **Report apples-to-apples when possible.** If different certificate routes
   are used, table them explicitly and avoid pretending they are identical.

## Engineering Experiments

Before math changes, produce:

- baseline runtime decomposition;
- live iteration trace;
- continuation/resume comparison;
- solver parameter grid summary;
- top-M or cut-policy ablation;
- hard-row report with final violation/gap and failure mode.

## Mathematical Changes

Any medium/high-risk change must come with:

- theorem or proof sketch of cut validity / bound validity;
- local oracle test;
- same-plan replay consistency check;
- lower-bound monotonicity or explicit statement when auxiliary objectives are
  not lower bounds;
- certificate preservation test;
- paper wording that distinguishes diagnostic progress from certified proof.

Use `references/certificate-boundaries.md` and
`references/pro-math-context-pack.md`.
