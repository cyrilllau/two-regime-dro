"""Round 13 cut-signature hashing and dedup helpers."""

from __future__ import annotations

from src.production.cut_factory import (
    compute_cut_nonzero_counts,
    compute_cut_signature_hash,
    generate_structured_cut,
)
from src.production.master_problem import RestrictedMasterCut
from src.reference.disaster_primal_ref import build_fixed_first_stage_plan, build_fixed_outage_vector
from tests.oracle.test_cut_factory import build_round_08_case


def test_cut_signature_hash_ignores_cut_id_for_exact_duplicate_coefficients() -> None:
    """Two structurally identical cuts should hash identically even if cut_id differs."""

    cut_a = RestrictedMasterCut(
        cut_id="cut_a",
        beta=1.0,
        gamma_z_by_bus={1: 0.0, 2: 3.0},
        gamma_n_sl_by_bus={1: 0.0, 2: 4.0},
        gamma_n_fa_by_bus={1: 0.0, 2: 0.0},
        phi_by_line_id={"line_01_02": 5.0},
    )
    cut_b = RestrictedMasterCut(
        cut_id="cut_b",
        beta=1.0,
        gamma_z_by_bus={1: 0.0, 2: 3.0},
        gamma_n_sl_by_bus={1: 0.0, 2: 4.0},
        gamma_n_fa_by_bus={1: 0.0, 2: 0.0},
        phi_by_line_id={"line_01_02": 5.0},
    )

    assert compute_cut_signature_hash(cut_a) == compute_cut_signature_hash(cut_b)
    assert compute_cut_nonzero_counts(cut_a) == {
        "gamma_z_nonzero_count": 1,
        "gamma_n_sl_nonzero_count": 1,
        "gamma_n_fa_nonzero_count": 0,
        "phi_nonzero_count": 1,
    }


def test_generated_cut_signature_is_stable_for_same_plan_and_outage() -> None:
    """The same validated paper-dual source point should produce the same cut signature."""

    instance, _, _, _, _ = build_round_08_case("benders_two_cut_unique_plan.yaml")
    plan = build_fixed_first_stage_plan(
        instance,
        z_by_bus={3: 1},
        n_sl_by_bus={3: 10},
        n_fa_by_bus={},
    )
    outage = build_fixed_outage_vector(instance, by_line_id={"line_01_02": 1})

    generated_a = generate_structured_cut(
        instance,
        plan=plan,
        outage=outage,
        cut_id="generated_a",
    )
    generated_b = generate_structured_cut(
        instance,
        plan=plan,
        outage=outage,
        cut_id="generated_b",
    )

    assert generated_a.cut_signature_hash == generated_b.cut_signature_hash
    assert generated_a.audit.cut_signature_hash == generated_b.audit.cut_signature_hash
    assert generated_a.gamma_n_sl_nonzero_count == generated_b.gamma_n_sl_nonzero_count
