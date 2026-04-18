"""Regression tests for disaster-objective readiness gating."""

from __future__ import annotations

import pytest

from src.instance.validators import RuntimeDataValidationError
from src.production.disaster_dual_paper import build_disaster_dual_paper_model
from src.reference.disaster_primal_ref import build_disaster_primal_reference_model
from tests.oracle.test_disaster_primal_ref import _build_case


@pytest.mark.parametrize(
    ("builder", "label"),
    [
        (build_disaster_primal_reference_model, "primal"),
        (build_disaster_dual_paper_model, "paper_dual"),
    ],
)
def test_missing_critical_buses_fails_clearly_without_ambig_w_fallback(
    builder,
    label: str,
) -> None:
    """Missing critical buses should fail fast, with no inference from legacy `ambig.w`."""

    instance, plan, outage, scenario_id, _ = _build_case(
        "disaster_primal_shortage.yaml",
        include_critical_buses=False,
    )

    with pytest.raises(RuntimeDataValidationError) as exc_info:
        builder(
            instance,
            plan=plan,
            outage=outage,
            scenario_id=scenario_id,
            model_name=f"missing_critical_{label}",
        )

    message = str(exc_info.value)
    assert "critical_buses is required for disaster-objective construction." in message
    assert "ambig.w is present but explicitly forbidden as a fallback." in message
