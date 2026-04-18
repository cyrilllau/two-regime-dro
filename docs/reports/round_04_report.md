# Round 04 Report

## Files changed
- `src/production/disaster_dual_paper.py`
- `src/audit/residual_report.py`
- `tests/oracle/test_lp_canonicalizer_signs.py`
- `tests/oracle/test_disaster_readiness_gate.py`
- `tests/oracle/test_disaster_dual_paper.py`
- `tests/integration/test_disaster_dual_paper_runtime_fixture.py`
- `docs/reports/round_04_report.md`

## Design decisions
- Implemented the fixed-sample hand-coded paper dual directly from the Round 02 primal equation groups rather than from the Round 03 canonicalized LP rows.
- Kept the Round 02 disaster primal mathematics unchanged.
- Used grouped dual variables with explicit economic meaning:
  - `lam_eq27` for Eq. (27) active-balance equalities
  - `eta_eq28_{slow,fast}` for Eq. (28) regional V2G availability upper bounds
  - `mu_eq29_{slow,fast}` for Eq. (29) station discharge upper bounds
  - `nu_eq30_{slow,fast}` for Eq. (30) siting-linkage upper bounds
  - `sigma_eq31` for Eq. (31) load-shedding upper bounds
  - `rho_eq32_{upper,lower}` for Eq. (32) two-sided line limits
- Kept `lam_eq27` free and all other paper-dual groups nonnegative.
- Added named hand-coded dual diagnostics in `src/audit/residual_report.py` instead of widening the reference-track KKT checker.
- The only narrow bug fix needed in this round was in the paper-dual objective sign convention:
  - upper-bound primal rows contribute negative RHS terms in the dual objective after canonical `>=` interpretation
  - the dual constraints were already correct
- No reference-file bug fix was required by the new regression tests.

## Paper-dual mapping
- Dual variable groups
  - Eq. (27): `lam_eq27_t{ts}_{line}` free
  - Eq. (28): `eta_eq28_slow_t{ts}_o{region} >= 0`, `eta_eq28_fast_t{ts}_o{region} >= 0`
  - Eq. (29): `mu_eq29_slow_t{ts}_n{bus} >= 0`, `mu_eq29_fast_t{ts}_n{bus} >= 0`
  - Eq. (30): `nu_eq30_slow_t{ts}_o{region}_n{bus} >= 0`, `nu_eq30_fast_t{ts}_o{region}_n{bus} >= 0`
  - Eq. (31): `sigma_eq31_t{ts}_n{bus} >= 0`
  - Eq. (32): `rho_eq32_upper_t{ts}_{line} >= 0`, `rho_eq32_lower_t{ts}_{line} >= 0`
- Primal equation groups they correspond to
  - Eq. (27) rows dualize the active-power-balance equalities
  - Eq. (28) rows dualize regional slow/fast discharging availability
  - Eq. (29) rows dualize station slow/fast capacity
  - Eq. (30) rows dualize assignment-siting linkage
  - Eq. (31) rows dualize load-shedding upper bounds
  - Eq. (32) rows dualize upper and lower line-capacity limits separately
- Sign restrictions
  - `lam_eq27` is unrestricted because it dualizes equality rows
  - all upper-bound-derived groups are nonnegative because they dualize canonical `>=` rows obtained from primal upper bounds
- Samplewise `beta_b / gamma_b / phi_b` decomposition note
  - `dual_value = beta_b - gamma_b^T x + phi_b^T delta`
  - `beta_b` collects sample-load terms from Eq. (27) and Eq. (31), sample V2G availability terms from Eq. (28), and the outage-independent base line-capacity terms from Eq. (32)
  - `gamma_b` is exposed in three first-stage blocks:
    - `gamma_z_by_bus`
    - `gamma_n_sl_by_bus`
    - `gamma_n_fa_by_bus`
  - `phi_b` is exposed linewise through `phi_by_line_id`
  - the current runtime-fixture hand-coded dual returned:
    - `beta_b = -1923726.2599999967`
    - failed-line coefficient `phi_b[line_01_02] = 2000000.0`

## Tests run
- `pytest tests/oracle/test_lp_canonicalizer_signs.py -q`
  - Result: `1 passed in 0.03s`
- `pytest tests/oracle/test_disaster_readiness_gate.py -q`
  - Result: `2 passed in 0.03s`
- `pytest tests/oracle/test_disaster_dual_paper.py -q`
  - Result: `5 passed in 0.07s`
- `pytest tests/oracle/test_disaster_primal_dual.py -q`
  - Result: `6 passed in 0.07s`
- `pytest tests/integration/test_disaster_dual_paper_runtime_fixture.py -q`
  - Result: `1 passed in 2.08s`
- `pytest -q`
  - Result: `79 passed in 4.03s`

## Objective comparisons
- Toy cases: primal vs auto dual vs paper dual
  - `zero`: `0.0` vs `-0.0` vs `-0.0`, absolute primal-paper gap `0.0`
  - `shortage`: `70.0` vs `70.0` vs `70.0`, absolute primal-paper gap `0.0`
  - `critical_priority`: `30.0` vs `30.0` vs `30.0`, absolute primal-paper gap `0.0`
  - `failed_line`: `20.0` vs `20.0` vs `20.0`, absolute primal-paper gap `0.0`
  - `mixed_slow_fast`: `10.0` vs `10.0` vs `10.0`, absolute primal-paper gap `0.0`
- Runtime fixture: primal vs auto dual vs paper dual
  - primal objective: `76273.74000000002`
  - auto-dual objective: `76273.74`
  - paper-dual objective: `76273.74`
  - absolute primal-auto gap: `1.4551915228366852e-11`
  - absolute auto-paper gap: `0.0`
  - decomposition reconstruction gap: `3.245077095925808e-09`

## Regression fixes
- Canonicalization sign-regression result
  - Added a minimal regression LP that checks:
    - equality rows stay as equality rows
    - original `<=` rows are negated into canonical `>=` rows
    - free-variable plus/minus splitting preserves row signs
  - Result: passed without requiring a reference-track code fix
- Missing-critical-buses regression result
  - Added an explicit regression test showing both the primal builder and the paper-dual builder fail clearly when `critical_buses` is missing
  - Result: passed, with the message explicitly stating that `ambig.w` is forbidden as a fallback
- Narrow bug fixes applied
  - Fixed the paper-dual objective sign convention for upper-bound-derived dual groups (`eta`, `mu`, `nu`, `sigma`, `rho`)
  - No changes were required in `src/reference/disaster_primal_ref.py`, `src/reference/lp_canonicalizer.py`, `src/reference/disaster_dual_auto.py`, or `src/reference/kkt_checks.py`

## Audit artifacts
- Primal LP dump path(s)
  - `/tmp/round_04_runtime_fixture_primal.lp`
- Auto-dual LP dump path(s)
  - `/tmp/round_04_runtime_fixture_auto_dual.lp`
- Paper-dual LP dump path(s)
  - `/tmp/round_04_runtime_fixture_paper_dual.lp`
- Dual-row / residual summary
  - runtime-fixture paper-dual max sign violation: `0.0`
  - runtime-fixture paper-dual max dual-row violation: `0.0`
  - runtime-fixture decomposition gap: `3.245077095925808e-09`
  - runtime-fixture primal Eq. (27) max residual: `0.0`
  - runtime-fixture failed-line flow max violation: `0.0`
  - named line-flow dual rows checked explicitly:
    - `dual_pdis_t1_line_01_02 = 0.0`
    - `dual_pdis_t1_line_02_03 = 0.0`
    - `dual_pdis_t1_line_02_19 = 0.0`

## Known limitations
- The hand-coded paper dual is still the fixed-sample, fixed-`(x, delta, b)` reference/prototype version only.
- No aggregated multi-sample disaster dual, separation MILP, cut generation, master problem, or Benders logic was implemented in this round.
- `gamma_b` is exposed by first-stage block (`z`, `n_sl`, `n_fa`) rather than through a shared master-problem vector object because the production first-stage block does not exist yet.
- The decomposition reconstruction gap on the runtime fixture is small LP solve noise rather than an exact symbolic identity check.

## Open issues for next round
- Round 05 should use the new samplewise `beta_b / gamma_b / phi_b` exposure when building and validating the separation problem.
- If later rounds need richer debugging, add a shared dual-diagnostic formatter rather than duplicating report assembly in tests.
- Once the production first-stage block exists, bind the current blockwise `gamma_b` exposure to the production `x` ordering used by cut generation.
