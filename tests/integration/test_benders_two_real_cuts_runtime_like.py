"""Runtime-like two-real-cut regression for Round 13."""

from __future__ import annotations

from pathlib import Path

from src.instance.canonical_instance import load_canonical_instance
from src.instance.selection import build_runtime_selection
from src.production.benders_engine import run_benders_engine
from scripts.experiment_pack_utils import prepare_instance_for_run


def test_runtime_like_case_generates_two_real_cuts_with_artifacts(tmp_path: Path) -> None:
    """The larger-support runtime-directional case should generate at least two real cuts."""

    selection = build_runtime_selection(
        scenarios_a=[1, 2, 3, 4],
        scenarios_b=[1, 2, 3, 4],
        source="round_13_runtime_like_two_cuts",
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
            "parameter_overrides": {"ambiguity": {"k_max_outages": 3}},
        },
    )

    before_path = tmp_path / "runtime_like_before.lp"
    after_path = tmp_path / "runtime_like_after.lp"
    log_path = tmp_path / "runtime_like_iteration_log.json"
    result = run_benders_engine(
        instance,
        epsilon_cert=0.0,
        max_iterations=3,
        enable_cut_signature_dedup=True,
        enable_repeated_outage_guard=True,
        model_name_prefix="round_13_runtime_like_two_cuts",
        master_before_cut_lp_path=before_path,
        master_after_cut_lp_path=after_path,
        iteration_log_path=log_path,
    )

    assert len(result.generated_cut_results) >= 2
    assert result.generated_cut_results[0].cut.is_trivial() is False
    assert result.generated_cut_results[1].cut.is_trivial() is False
    assert result.iteration_log_path == log_path
    assert before_path.exists()
    assert log_path.exists()
    if result.master_after_cut_lp_path is not None:
        assert after_path.exists()
