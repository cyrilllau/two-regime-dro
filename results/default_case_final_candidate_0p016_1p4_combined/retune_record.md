# Default Retune Record

## Accepted Candidate

- Candidate: `mult_cons0p016_normal1_disaster1p4`
- Data: `data/colleague_default_10x10`
- Common evaluator: `A=10`, `B=10`, `K=2`, MILP worst-distribution replay
- Objective multipliers used for training only: `m_cons=0.016`, `m_normal=1.0`, `m_dis=1.4`
- Verdict: `PASS_PAPER_STORY`

## Why This Candidate Was Accepted

- Case 1 opens 12 stations with 172 slow and 15 fast EVSEs.
- Case 2 opens 5 stations with 113 slow and 15 fast EVSEs and has much worse disaster replay cost.
- Case 3 is the corrected disaster-only endpoint: it has the lowest disaster cost, but its normal replay has high unmet charging demand.
- Case 4 is the fair deterministic mean-value benchmark with `K_train=2`; it opens 11 stations with 171 slow and 15 fast EVSEs.
- Case 1 has more stations than Case 4, no fewer slow/fast chargers, and lower `Phi_dis`.

## Key Numbers

- `Phi_case3 < Phi_case1 < Phi_case2`: `4557.02 < 5223.70 < 16844.36`.
- Case 1 reduces normal-only disaster cost by `68.99%`.
- Case 1 reduces deterministic K=2 disaster cost by `25.72%`.
- Case 3 `F_unmet=137689.83`, while Case 4 `F_unmet=0.00`, so the disaster-only endpoint now clearly sacrifices normal EV service.
- Case 1 keeps `F_unmet=0.00`.

## Rejected Directions

- `m_cons=0.0152, m_dis=1.4` had a strong Case 1/2/4 structure, but the corrected Case 3 run did not produce a usable endpoint under the available budget.
- `m_dis=1.45` gave a strong Case 1/4 topology, but corrected Case 3 became difficult and its light run did not beat Case 1 in `Phi_dis`.
- Raising `m_cons` at fixed `m_dis=1.4` reduced Case 1 charger capacity faster than deterministic capacity and failed the deterministic-topology story.

## Promotion

- Promoted artifacts were written to `results/paper_final/`.
- Updated files include `objective_components_tableIII.csv`, `summary.csv`, `claim_matrix.csv`, `deterministic_worst_distribution.csv`, default plans, default figures, and the standalone experiment-section PDF.
