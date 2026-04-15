"""Tests for explicit instance-layer validation rules."""

from __future__ import annotations

import pytest

from src.instance.validators import (
    RuntimeDataValidationError,
    build_criticality_maps,
    require_explicit_critical_buses,
    validate_line_parameter_lengths,
)


def test_line_parameter_length_mismatch_is_rejected() -> None:
    """Linewise vectors must match the canonical line count."""

    with pytest.raises(RuntimeDataValidationError, match="ambig.p_bar has length 1, expected 2"):
        validate_line_parameter_lengths(
            line_count=2,
            rline=(0.1, 0.2),
            xline=(0.01, 0.02),
            pmax=(10.0, 10.0),
            qmax=(10.0, 10.0),
            p_bar=(0.1,),
        )


def test_explicit_criticality_maps_use_only_passed_buses() -> None:
    """Criticality must come from explicit input, not from legacy weights."""

    is_critical, cls_by_bus = build_criticality_maps(
        buses=(1, 2, 3),
        critical_buses=(2,),
        cls_critical=50.0,
        cls_noncritical=10.0,
    )
    assert is_critical == {1: False, 2: True, 3: False}
    assert cls_by_bus == {1: 10.0, 2: 50.0, 3: 10.0}


def test_missing_critical_buses_do_not_fall_back_to_ambig_w() -> None:
    """Disaster-objective readiness must reject missing critical buses explicitly."""

    with pytest.raises(
        RuntimeDataValidationError,
        match="ambig.w is present but explicitly forbidden as a fallback",
    ):
        require_explicit_critical_buses(
            buses=(1, 2, 3),
            critical_buses=None,
            legacy_w=(1.0, 50000.0, 20000.0),
        )
