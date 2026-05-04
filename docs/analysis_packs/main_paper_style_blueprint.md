# Main Paper Style Blueprint

This blueprint is distilled from `reference/main_paper.pdf` and is used as the
style lock for the EVCS DRO experiment section.

## Experimental Setup Pattern

- State the IEEE 33-node feeder, critical/non-critical buses, EV regions, charger
  types, planning horizon, and disaster horizon.
- Explain scenario profiles before giving optimization results: normal load,
  normal EV charging demand, disaster EV discharging availability, and line
  outage ambiguity.
- Include a Table-II-style parameter table with units.
- Report solver, implementation language, CPU, and RAM.

## Benchmark Pattern

- Case 1: proposed integrated planning.
- Case 2: normal-operation-only planning.
- Case 3: disaster-resilience-only planning.
- Case 4: deterministic/mean-value planning.
- Use Fig.-6/Fig.-7-style planning maps before discussing component costs.
- Use Table-III-style components: Fcons, Ftrans, Funmet, Fsub, Psi_nor, Phi_dis.

## Analysis Pattern

- Compare first-stage layout and charger mix before objective interpretation.
- Compare proposed vs normal-only as a normal-cost sacrifice for resilience gain.
- Compare proposed vs disaster-only as a resilience-only design that may harm
  daily service quality.
- Compare proposed vs deterministic as a small deterministic economy gain versus
  a worst-distribution resilience loss.
- EV sensitivity must reuse the same component taxonomy and explain capacity
  expansion, unmet demand, transport cost, substation cost, and Phi_dis.

## DRO Extension Required Here

- All cross-case claims must use a common ex-post evaluator.
- Report the scenario support size and K explicitly.
- Separate certified main rows from diagnostic stress rows.
- If deterministic is not worse under the common worst-distribution evaluator,
  the strong DRO robustness claim must be blocked or rewritten.
