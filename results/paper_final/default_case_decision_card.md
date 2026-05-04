# Autonomous Default Case Decision Card

- Candidate: `mult_cons0p016_normal1_disaster1p4`
- Default scale: IEEE 33-bus, `A=10`, `B=10`, `K=2`.
- Objective multipliers: `m_cons=0.016`, `m_normal=1.0`, `m_dis=1.4`.
- Verdict: `PASS_PAPER_STORY`.
- Proposed certificate: `epsilon_certified`, final violation `94.95991363086542`.
- Disaster-only certificate: `epsilon_certified`, final violation `90.51938974422592`.

## Component Story

- Case 1 Phi: `5,223.70`; Case 2 Phi: `16,844.36`; Case 3 Phi: `4,557.02`; Case 4 Phi: `7,032.12`.
- Case 3 reduces Phi relative to Case 1 by `12.76%` while its `F_unmet/Psi` is `68.36%`.
- Case 1 reduces fair deterministic Case 4 Phi by `25.72%` and installs `172/15` slow/fast chargers versus `171/15`.

## Topology Boundary

- This candidate passes the mechanism-based story rubric but does not satisfy every earlier hard topology preference.
- Direct critical-bus coverage is `7/11` for Case 1 and `2/11` for Case 4.
- Case 1 opens `12` stations versus `11` in Case 4; Case 1 is larger through both siting coverage and charger capacity.
