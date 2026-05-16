# Result Section Checklist

## Tables

- Include raw comparable cost/objective components, not only aggregate training
  objective values.
- Include first-stage design quantities that explain the mechanism, e.g.,
  selected assets, capacities, flows, active constraints, or coverage metrics.
- Include certificate status, final violation/gap, iterations, and runtime for
  algorithmic claims.
- Include hardware/software settings for runtime claims.
- Make table captions state the evaluator, support size, seed, and certificate
  tolerance when relevant.

## Figures

- Use maps/layouts when topology or spatial allocation is part of the story.
- Use component bars when the claim is a cost/risk tradeoff.
- Use traces when the claim is convergence or cut effectiveness.
- Use runtime decomposition when claiming scalability.
- Avoid one giant figure per page unless it is genuinely needed for legibility.

## Main-Text Eligibility

A row is main-text eligible only if:

- it uses the accepted data/config regime;
- it is produced by the accepted evaluation protocol;
- it has a reproducible log/config path;
- its certificate label is honest;
- it has no unresolved blocking critic issue.

Rows that fail any item can still be used internally as diagnostics.

## Final Manuscript Audit

- Search the LaTeX for stale regime names, old scenario supports, obsolete
  sensitivity levels, and diagnostic wording.
- Ensure each table and figure is referenced in prose.
- Ensure every claim has a source row in the claim matrix.
- Compile and visually inspect the PDF pages before delivery.
