"""Runtime smoke checks for the Round 08 generated-cut path."""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.audit.model_dump import dump_model_artifact
from src.instance.canonical_instance import load_canonical_instance
from src.production.cut_factory import (
    CUT_FROM_SEPARATION_DUAL_METHOD,
    run_single_iteration_cut_addition,
)


def _guard_runtime_raw_reads(real_open, runtime_root: Path):
    """Reject any attempted raw runtime-data reads during production build/solve."""

    def wrapped(file, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)):
            path = Path(file).resolve()
            if path == runtime_root or runtime_root in path.parents:
                raise AssertionError(
                    f"Production model layer attempted to read raw runtime data path: {path}"
                )
        return real_open(file, *args, **kwargs)

    return wrapped


def test_runtime_fixture_supports_one_generated_cut_addition_under_raw_guard() -> None:
    """The runtime fixture should support one cut-generation-and-resolve step."""

    instance = load_canonical_instance("data/runtime_12", critical_buses=(5, 9))
    runtime_root = (Path.cwd() / "data" / "runtime_12").resolve()
    guarded_open = _guard_runtime_raw_reads(builtins.open, runtime_root)

    with patch("builtins.open", new=guarded_open):
        result = run_single_iteration_cut_addition(
            instance,
            cuts=None,
            model_name_prefix="round_08_runtime",
            cut_id="runtime_generated_cut",
        )

    before_dump = dump_model_artifact(
        result.pre_master,
        Path("/tmp/round_08_runtime_master_before_cut.lp"),
    )
    after_dump = dump_model_artifact(
        result.post_master,
        Path("/tmp/round_08_runtime_master_after_cut.lp"),
    )
    audit = result.generated_cut_result.audit
    averaged_cut = result.generated_cut_result.cut
    scenario_count = len(result.generated_cut_result.scenario_ids)

    assert before_dump.exists()
    assert after_dump.exists()
    assert result.generated_cut_result is not None
    assert result.generated_cut_result.simplex_method == CUT_FROM_SEPARATION_DUAL_METHOD
    assert result.generated_cut_result.cut.is_trivial() is False
    assert result.generated_cut_result.old_master_cut_violation is not None
    assert result.generated_cut_result.old_master_cut_violation > 1e-6
    assert result.generated_cut_result.old_master_cut_violation == pytest.approx(
        result.separation_solution.objective_value,
        abs=1e-6,
    )
    assert result.post_solution.objective_value >= result.pre_solution.objective_value - 1e-8
    assert result.post_residual.max_cut_support_violation <= 1e-8
    assert result.post_residual.max_u_link_violation <= 1e-8
    assert audit.source_outage.by_line_id == result.separation_solution.delta_by_line_id
    assert audit.source_alpha == pytest.approx(result.pre_solution.alpha_value)
    assert audit.source_lambda_by_line_id == result.pre_solution.lambda_by_line_id
    assert "runtime_generated_cut" in result.post_residual.cut_support_slacks

    assert averaged_cut.beta == pytest.approx(
        sum(
            audit.samplewise_decompositions_by_scenario[scenario_id].beta_b
            for scenario_id in result.generated_cut_result.scenario_ids
        )
        / scenario_count
    )
    for bus in instance.sets.buses:
        assert averaged_cut.gamma_z_by_bus[bus] == pytest.approx(
            sum(
                audit.samplewise_decompositions_by_scenario[scenario_id].gamma_z_by_bus[bus]
                for scenario_id in result.generated_cut_result.scenario_ids
            )
            / scenario_count
        )
        assert averaged_cut.gamma_n_sl_by_bus[bus] == pytest.approx(
            sum(
                audit.samplewise_decompositions_by_scenario[scenario_id].gamma_n_sl_by_bus[bus]
                for scenario_id in result.generated_cut_result.scenario_ids
            )
            / scenario_count
        )
        assert averaged_cut.gamma_n_fa_by_bus[bus] == pytest.approx(
            sum(
                audit.samplewise_decompositions_by_scenario[scenario_id].gamma_n_fa_by_bus[bus]
                for scenario_id in result.generated_cut_result.scenario_ids
            )
            / scenario_count
        )
    for line_id in instance.sets.line_ids:
        assert averaged_cut.phi_by_line_id[line_id] == pytest.approx(
            sum(
                audit.samplewise_decompositions_by_scenario[scenario_id].phi_by_line_id[line_id]
                for scenario_id in result.generated_cut_result.scenario_ids
            )
            / scenario_count
        )
