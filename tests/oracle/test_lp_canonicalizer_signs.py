"""Minimal sign-regression tests for the Round 03 canonicalizer."""

from __future__ import annotations

from types import SimpleNamespace

from gurobipy import GRB, Model

from src.reference.lp_canonicalizer import canonicalize_reference_lp


def test_canonicalizer_preserves_equalities_and_negates_le_rows_with_free_splitting() -> None:
    """Equality rows, `<=` rows, and free-variable splitting should keep their signs stable."""

    model = Model("canonicalizer_sign_regression")
    model.Params.OutputFlag = 0

    flow = model.addVar(lb=-GRB.INFINITY, name="pdis_test", obj=0.0)
    shed = model.addVar(lb=0.0, name="yls_test", obj=2.0)

    model.addConstr(flow + shed == 3.0, name="eq27_balance_like")
    model.addConstr(flow - shed <= 4.0, name="eq32_upper_like")
    model.update()

    canonical_lp = canonicalize_reference_lp(SimpleNamespace(model=model))

    assert canonical_lp.free_variable_map["pdis_test"] == (
        "pdis_test__pos",
        "pdis_test__neg",
    )

    equality_by_name = {
        constraint.name: constraint for constraint in canonical_lp.equality_constraints
    }
    geq_by_name = {constraint.name: constraint for constraint in canonical_lp.geq_constraints}

    eq_row = equality_by_name["eq27_balance_like"]
    assert eq_row.rhs == 3.0
    assert eq_row.coefficients == {
        "pdis_test__pos": 1.0,
        "pdis_test__neg": -1.0,
        "yls_test": 1.0,
    }

    ge_row = geq_by_name["eq32_upper_like__canonical_ge"]
    assert ge_row.rhs == -4.0
    assert ge_row.coefficients == {
        "pdis_test__pos": -1.0,
        "pdis_test__neg": 1.0,
        "yls_test": 1.0,
    }
