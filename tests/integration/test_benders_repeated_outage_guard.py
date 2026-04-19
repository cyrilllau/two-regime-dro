"""Repeated-outage diagnostics for the Round 13 Benders engine."""

from __future__ import annotations

from src.instance.canonical_instance import load_canonical_instance
from src.instance.selection import build_runtime_selection
from src.production.benders_engine import run_benders_engine
from scripts.experiment_pack_utils import prepare_instance_for_run


PAPER_LIKE_OVERRIDES = {
    "economics": {
        "cfix": 153600.0,
        "ccons_sl": 540.07,
        "ccons_fa": 25000.0,
        "ctrans_scalar": 0.0435,
        "gamma": 0.01,
        "theta": 20,
        "pi_f": 0.3,
    },
    "ev": {
        "p_ev_rated_sl": 7.0,
        "p_ev_rated_fa": 50.0,
        "nbar_sl": 25,
        "nbar_fa": 10,
    },
}


def test_repeated_outage_flag_is_recorded_on_known_harder_paper_like_case() -> None:
    """The engine should explicitly mark repeated outage patterns on the known non-cert case."""

    selection = build_runtime_selection(
        scenarios_a=[1],
        scenarios_b=[1],
        source="round_13_repeated_outage_guard",
    )
    base_instance = load_canonical_instance(
        "data/runtime_12",
        critical_buses=(2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32),
        selection=selection,
    )
    instance = prepare_instance_for_run(
        base_instance,
        {
            "mode": "integrated_mainline",
            "parameter_overrides": PAPER_LIKE_OVERRIDES,
        },
    )

    result = run_benders_engine(
        instance,
        epsilon_cert=0.0,
        max_iterations=20,
        enable_cut_signature_dedup=True,
        enable_repeated_outage_guard=True,
        model_name_prefix="round_13_repeated_outage_guard",
    )

    assert any(record.repeated_outage_flag for record in result.iterations)
    assert all(record.generated_cut_signature_hash is None or len(record.generated_cut_signature_hash) == 16 for record in result.iterations)
    assert all(record.repeated_cut_signature_flag is False for record in result.iterations)
    assert result.stop_reason in {"max_iterations", "duplicate_cut_signature", "repeated_outage_duplicate_cut"}
