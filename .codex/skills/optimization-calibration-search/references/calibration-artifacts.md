# Calibration Artifacts

Recommended output structure:

- `candidate_queue.csv`: all planned candidates and stage assignments.
- `stage_a_screen.csv`: cheap topology/objective screening.
- `stage_b_common_replay.csv`: frozen-plan common evaluator rows.
- `stage_c_certification.csv`: fully certified candidate rows.
- `story_gate_summary.csv`: qualitative and quantitative gates.
- `blocked_candidates.csv`: timeout, infeasibility, solver, or semantics blocks.
- `bug_log.md`: suspected model or benchmark bugs with reproduction command.
- `best_candidate_report.md`: why the chosen candidate is paper-facing.
- `decision_card.md`: adopted regime, rejected alternatives, and claim boundary.

Required checks:

- raw component identity checks;
- common evaluator equality across cases;
- benchmark semantics checks;
- no per-case parameter tuning;
- no smoke-only or diagnostic rows promoted to main text.
