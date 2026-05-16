---
name: pro-math-consultation
description: Use when a research or optimization task requires ChatGPT Pro extended-effort mathematical review, especially for theorem-level validation, algorithm changes, certificate definitions, proof sketches, or reviewer-facing wording; emphasizes persistent chat context, context packs, downloadable TeX responses, and conversion of Pro advice into local tests.
metadata:
  short-description: Work with Pro on math and algorithm decisions
---

# Pro Math Consultation

Use this skill when the next step depends on mathematical judgment rather than
ordinary coding. Pro is an external critic and derivation assistant, not an
authority whose answer can bypass local verification.

## Consultation Rules

1. **Reuse context.** For the same paper target or algorithm line, continue the
   same Pro chat so context accumulates. Start a new chat only when the target
   is unrelated, the old chat is inaccessible, or the user asks for a new one.
2. **Send a context pack.** Include the model/paper reference, current formulas,
   logs/traces, known failures, implemented prototypes, and the exact question.
3. **Ask for extended effort.** Explicitly ask Pro to be rigorous and critical.
4. **Request a downloadable TeX file.** For math sections, ask for theorem
   statements, proof sketches, algorithm box, and local audit tests in `.tex`.
5. **Do not upload unnecessary private data.** Send only minimal artifacts and
   summaries unless the user approves broader upload.
6. **Record the consultation.** Save prompt, uploaded file list, Pro conclusion,
   adopted/rejected items, and converted local tests.
7. **Verify locally.** Turn every Pro recommendation into code tests, oracle
   checks, audit gates, reruns, or claim wording changes.

## Ask Pro For

- Is this cut valid for all feasible first-stage points?
- Does this bound define a real certificate or only a heuristic diagnostic?
- What assumptions are needed for a theorem-level claim?
- Which local oracle tests would falsify this derivation?
- What paper wording is accurate and not overclaimed?

Use `references/pro-prompt-template.md` for a reusable prompt skeleton.
