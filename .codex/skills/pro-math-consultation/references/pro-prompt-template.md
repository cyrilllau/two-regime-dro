# Pro Prompt Template

```text
Please use extended effort and return the answer as a downloadable LaTeX file.

Context:
- Paper/model:
- Current formulation:
- Current algorithm:
- Evidence and failures:
- Implemented prototypes:
- Exact decision I need:

Tasks:
1. State whether the proposed mathematical change is valid.
2. Give theorem/proposition statements and proof sketches.
3. Distinguish model changes, solver-only changes, and engineering changes.
4. State certificate conditions and what is only diagnostic.
5. Provide local oracle tests and audit gates.
6. Provide safe paper wording and contribution text.

Please be adversarial. If the idea is invalid, say exactly what condition is
missing and what should be implemented instead.
```

After receiving the response:

- save the `.tex` file or copied block;
- summarize adopted/rejected items;
- implement only changes with local tests;
- keep Pro wording out of the paper until verified by artifacts.
