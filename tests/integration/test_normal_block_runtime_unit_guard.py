"""Runtime unit-guard checks for the Round 06 normal-operation block."""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from unittest.mock import patch

from gurobipy import GRB

from src.audit.model_dump import dump_model_artifact
from src.audit.residual_report import build_normal_operation_residual_report
from src.instance.canonical_instance import load_canonical_instance
from src.production.first_stage import build_first_stage_model
from src.production.normal_block import (
    build_normal_operation_block,
    extract_normal_operation_solution,
)


def _guard_runtime_raw_reads(real_open, runtime_root: Path):
    """Reject any attempted raw `data/runtime_12` file reads during model build/solve."""

    def wrapped(file, *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)):
            path = Path(file).resolve()
            if path == runtime_root or runtime_root in path.parents:
                raise AssertionError(
                    f"Production model layer attempted to read raw runtime data path: {path}"
                )
        return real_open(file, *args, **kwargs)

    return wrapped


def test_runtime_normal_block_unit_guard_is_explicit_and_required_for_feasibility() -> None:
    """The runtime smoke path should use the explicit Eq. (24) conversion and become infeasible without it."""

    instance = load_canonical_instance("data/runtime_12", critical_buses=(5, 9))
    scenario_id = instance.sets.loaded_normal_scenarios[0]
    runtime_root = (Path.cwd() / "data" / "runtime_12").resolve()
    guarded_open = _guard_runtime_raw_reads(builtins.open, runtime_root)

    with patch("builtins.open", new=guarded_open):
        first_stage = build_first_stage_model(
            instance,
            model_name="round_06_5_runtime_unit_guard",
            attach_objective=True,
        )
        normal_block = build_normal_operation_block(
            instance,
            first_stage=first_stage,
            scenario_id=scenario_id,
            attach_objective=True,
        )
        normal_block.model.optimize()

    normal_solution = extract_normal_operation_solution(normal_block)
    residual = build_normal_operation_residual_report(normal_block, normal_solution)
    dump_path = dump_model_artifact(
        normal_block,
        Path("/tmp/round_06_5_runtime_first_stage_normal.lp"),
    )

    assert dump_path.exists()
    assert normal_solution.model_status == "OPTIMAL"
    assert normal_block.eq24_power_base_kw == 1000.0
    assert normal_block.eq24_power_to_pu_scale == 0.001
    assert "1 MVA" in normal_block.eq24_unit_assumption
    assert residual.max_voltage_drop_residual <= 1e-8
    assert residual.max_voltage_bound_violation <= 1e-8
    assert residual.max_line_limit_violation <= 1e-8

    incorrect_first_stage = build_first_stage_model(
        instance,
        model_name="round_06_5_runtime_unit_guard_incorrect_scale",
        attach_objective=True,
    )
    incorrect_block = build_normal_operation_block(
        instance,
        first_stage=incorrect_first_stage,
        scenario_id=scenario_id,
        attach_objective=True,
    )
    line_by_id = {line.line_id: line for line in instance.lines}
    for (time_id, line_id), constr in incorrect_block.voltage_drop_constraints.items():
        line = line_by_id[line_id]
        incorrect_block.model.chgCoeff(
            constr,
            incorrect_block.active_flow_vars[(time_id, line_id)],
            2.0 * line.resistance_pu,
        )
        incorrect_block.model.chgCoeff(
            constr,
            incorrect_block.reactive_flow_vars[(time_id, line_id)],
            2.0 * line.reactance_pu,
        )
    incorrect_block.model.update()
    incorrect_block.model.optimize()

    assert incorrect_block.model.Status == GRB.INFEASIBLE
