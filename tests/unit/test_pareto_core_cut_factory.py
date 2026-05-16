"""Safety checks for fixed-support Pareto/MW cut tie-breaking."""

from __future__ import annotations

import pytest

from src.production.cut_factory import (
    CoreFirstStagePoint,
    build_default_pareto_core_point,
    generate_target_face_bundle_cuts,
    generate_structured_cut,
    normalize_core_first_stage_point,
)
from src.reference.disaster_primal_ref import build_fixed_outage_vector
from tests.oracle.test_disaster_primal_ref import _build_case


def test_default_pareto_core_point_is_aligned_and_nonnegative() -> None:
    instance, _, _, _, _ = _build_case("disaster_primal_mixed_slow_fast.yaml")

    core = build_default_pareto_core_point(instance)

    assert set(core.z_by_bus) == set(instance.sets.buses)
    assert set(core.n_sl_by_bus) == set(instance.sets.buses)
    assert set(core.n_fa_by_bus) == set(instance.sets.buses)
    assert all(value >= 0.0 for value in core.z_by_bus.values())
    assert all(value >= 0.0 for value in core.n_sl_by_bus.values())
    assert all(value >= 0.0 for value in core.n_fa_by_bus.values())


def test_pareto_core_cut_generation_preserves_source_cut_validity() -> None:
    instance, plan, outage, scenario_id, _ = _build_case(
        "disaster_primal_mixed_slow_fast.yaml"
    )
    core = build_default_pareto_core_point(instance)

    cut_result = generate_structured_cut(
        instance,
        plan=plan,
        outage=outage,
        scenario_ids=(scenario_id,),
        cut_id="pareto_core_test_cut",
        source_alpha=-1.0e6,
        source_lambda_by_line_id={line_id: 0.0 for line_id in instance.sets.line_ids},
        pareto_core_point=core,
    )

    assert cut_result.cut.cut_id == "pareto_core_test_cut"
    assert cut_result.old_master_cut_violation is not None
    assert cut_result.old_master_cut_violation >= -1e-5
    assert cut_result.support_value_at_source is not None


def test_invalid_pareto_core_point_rejected() -> None:
    instance, _, _, _, _ = _build_case("disaster_primal_mixed_slow_fast.yaml")

    with pytest.raises(Exception, match="nonnegative"):
        normalize_core_first_stage_point(
            instance,
            CoreFirstStagePoint(
                z_by_bus={bus: -1.0 for bus in instance.sets.buses},
                n_sl_by_bus={bus: 0.0 for bus in instance.sets.buses},
                n_fa_by_bus={bus: 0.0 for bus in instance.sets.buses},
            ),
        )


def test_target_face_bundle_cut_preserves_source_face_validity() -> None:
    instance, plan, outage, scenario_id, _ = _build_case(
        "disaster_primal_mixed_slow_fast.yaml"
    )
    line_ids = list(instance.sets.line_ids)
    if len(line_ids) < 2:
        pytest.skip("target-face test needs at least two lines")
    target = {line_id: 0 for line_id in line_ids}
    target[line_ids[0]] = 1
    if target == outage.by_line_id and len(line_ids) > 1:
        target[line_ids[0]] = 0
        target[line_ids[1]] = 1
    target_outage = build_fixed_outage_vector(instance, by_line_id=target)

    cuts = generate_target_face_bundle_cuts(
        instance,
        plan=plan,
        source_outage=outage,
        target_outages=(target_outage,),
        scenario_ids=(scenario_id,),
        cut_id_prefix="target_face_test",
        source_alpha=-1.0e6,
        source_lambda_by_line_id={line_id: 0.0 for line_id in instance.sets.line_ids},
        face_tolerance_rel=1e-6,
        max_cuts=1,
        min_cut_violation=0.0,
    )

    assert len(cuts) == 1
    cut_result = cuts[0]
    assert cut_result.old_master_cut_violation is not None
    assert cut_result.old_master_cut_violation >= -1e-5
    assert cut_result.cut.cut_id.startswith("target_face_test")
