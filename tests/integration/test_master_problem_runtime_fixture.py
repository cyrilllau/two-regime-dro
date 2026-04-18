"""Runtime smoke test for the Round 07 restricted master problem builder."""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from unittest.mock import patch

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import (
    build_master_problem_residual_report,
    build_normal_operation_residual_report,
)
from src.instance.canonical_instance import load_canonical_instance
from src.production.disaster_dual_paper import solve_disaster_dual_paper
from src.production.master_problem import RestrictedMasterCut, solve_master_problem
from src.reference.disaster_primal_ref import (
    build_fixed_first_stage_plan,
    build_fixed_outage_vector,
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


def test_runtime_fixture_restricted_master_solves_cleanly_without_raw_reads() -> None:
    """The runtime RMP smoke path should solve on all selected normal scenarios without raw reads."""

    instance = load_canonical_instance("data/runtime_12", critical_buses=(5, 9))
    runtime_root = (Path.cwd() / "data" / "runtime_12").resolve()
    guarded_open = _guard_runtime_raw_reads(builtins.open, runtime_root)

    with patch("builtins.open", new=guarded_open):
        master_problem, solution = solve_master_problem(
            instance,
            cuts=None,
            model_name="round_07_runtime_fixture",
        )

    dump_path = dump_model_artifact(master_problem, Path("/tmp/round_07_runtime_master.lp"))
    residual = build_master_problem_residual_report(master_problem, solution)
    normal_reports = {
        scenario_id: build_normal_operation_residual_report(
            master_problem.normal_blocks_by_scenario[scenario_id],
            solution.normal_solutions_by_scenario[scenario_id],
        )
        for scenario_id in master_problem.normal_scenario_ids
    }

    assert dump_path.exists()
    assert solution.model_status == "OPTIMAL"
    assert master_problem.ordered_buses == instance.sets.buses
    assert master_problem.ordered_line_ids == instance.sets.line_ids
    assert tuple(master_problem.first_stage.z_by_bus) == instance.sets.buses
    assert tuple(master_problem.lambda_by_line_id) == instance.sets.line_ids
    assert master_problem.normal_scenario_ids == instance.sets.loaded_normal_scenarios
    assert master_problem.cuts[0].cut_id == "trivial_cut"
    assert solution.alpha_value == 0.0
    assert all(abs(value) <= 1e-8 for value in solution.lambda_by_line_id.values())
    assert residual.max_cut_support_violation <= 1e-8
    assert residual.max_u_link_violation <= 1e-8
    assert residual.objective_reconstruction_gap <= 1e-7
    for normal_report in normal_reports.values():
        assert normal_report.max_charge_balance_residual <= 1e-8
        assert normal_report.max_active_power_balance_residual <= 1e-8
        assert normal_report.max_reactive_power_balance_residual <= 1e-8
        assert normal_report.max_voltage_drop_residual <= 1e-8
        assert normal_report.max_voltage_bound_violation <= 1e-8
        assert normal_report.max_line_limit_violation <= 1e-8


def test_runtime_fixture_restricted_master_accepts_nontrivial_real_cut_under_raw_guard() -> None:
    """The runtime smoke path should also accept a nontrivial supplied real cut."""

    instance = load_canonical_instance("data/runtime_12", critical_buses=(5, 9))
    runtime_root = (Path.cwd() / "data" / "runtime_12").resolve()
    guarded_open = _guard_runtime_raw_reads(builtins.open, runtime_root)

    with patch("builtins.open", new=guarded_open):
        seed_plan = build_fixed_first_stage_plan(
            instance,
            z_by_bus={bus: int(bus in {5, 9}) for bus in instance.sets.buses},
            n_sl_by_bus={bus: (3 if bus in {5, 9} else 0) for bus in instance.sets.buses},
            n_fa_by_bus={bus: 0 for bus in instance.sets.buses},
        )
        nontrivial_outage = build_fixed_outage_vector(
            instance,
            by_line_id={"line_01_02": 1},
        )
        _, paper_solution = solve_disaster_dual_paper(
            instance,
            plan=seed_plan,
            outage=nontrivial_outage,
            scenario_id=instance.sets.loaded_disaster_scenarios[0],
            model_name="round_07_5_runtime_real_cut_source",
        )
        runtime_real_cut = RestrictedMasterCut.from_samplewise_decomposition(
            instance,
            paper_solution.samplewise_decomposition,
            cut_id="runtime_real_cut",
        )
        master_problem, solution = solve_master_problem(
            instance,
            cuts=(runtime_real_cut,),
            model_name="round_07_5_runtime_with_real_cut",
        )

    dump_path = dump_model_artifact(
        master_problem,
        Path("/tmp/round_07_5_runtime_master_with_real_cut.lp"),
    )
    residual = build_master_problem_residual_report(master_problem, solution)

    assert dump_path.exists()
    assert runtime_real_cut.is_trivial() is False
    assert solution.model_status == "OPTIMAL"
    assert residual.max_cut_support_violation <= 1e-8
    assert residual.max_u_link_violation <= 1e-8
    assert residual.objective_reconstruction_gap <= 1e-7
    assert "runtime_real_cut" in residual.cut_support_slacks
    assert "runtime_real_cut:line_01_02" in residual.u_link_slacks
    assert residual.first_stage_objective_is_pure_construction is False
    assert residual.active_nontrivial_cut_ids == ("runtime_real_cut",)
