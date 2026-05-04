# Objective Multiplier Calibration Audit

- Runtime source: `data/colleague_default_10x10`
- Fixed Table-I parameters are read from the runtime data; the driver only sets `parameter_overrides.objective_multipliers`.
- Training objective uses `m_cons F_cons + m_normal (1-pi_f) Psi + m_disaster pi_f Phi`.
- Default topology-aware search uses normalized objective weights with `m_normal=1`. The `(0.015,1,1.25)` candidate is treated as the Case1/2/3 endpoint-structure anchor because it has a strong disaster-only endpoint, but it still needs deterministic-topology improvement before final promotion.
- Common replay rows report raw `F_cons`, `Psi_nor`, and `Phi_dis`.
- Passing the target requires both science gates and topology gates.
- Candidate triples queued: `1`.
