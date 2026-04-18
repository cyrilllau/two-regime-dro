"""Primal/dual feasibility and KKT-style checks for the disaster reference LP."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.audit.residual_report import DisasterPrimalResidualReport
from src.reference.disaster_dual_auto import (
    DisasterAutoDualModel,
    DisasterAutoDualSolution,
)
from src.reference.disaster_primal_ref import (
    DisasterPrimalReferenceModel,
    DisasterPrimalSolution,
)
from src.reference.lp_canonicalizer import (
    CanonicalizedReferenceLP,
    canonicalize_reference_lp,
    evaluate_canonical_constraint,
    extract_canonical_primal_solution,
)


@dataclass(frozen=True)
class KKTCheckReport:
    """Compact KKT-style validation report for primal vs auto dual."""

    primal_feasibility_max_violation: float
    dual_feasibility_max_violation: float
    strong_duality_gap: float
    max_row_complementarity: float
    max_variable_complementarity: float
    geq_constraint_slacks: dict[str, float] = field(default_factory=dict)
    dual_constraint_slacks: dict[str, float] = field(default_factory=dict)
    row_complementarity_products: dict[str, float] = field(default_factory=dict)
    variable_complementarity_products: dict[str, float] = field(default_factory=dict)


def run_kkt_checks(
    reference_model: DisasterPrimalReferenceModel,
    primal_solution: DisasterPrimalSolution,
    auto_dual_model: DisasterAutoDualModel,
    dual_solution: DisasterAutoDualSolution,
    primal_residual_report: DisasterPrimalResidualReport,
    *,
    canonical_lp: CanonicalizedReferenceLP | None = None,
) -> KKTCheckReport:
    """Run primal/dual feasibility, strong duality, and complementarity checks."""

    canonical = canonical_lp or canonicalize_reference_lp(reference_model)
    canonical_primal = extract_canonical_primal_solution(reference_model, primal_solution, canonical)

    geq_constraint_slacks: dict[str, float] = {}
    primal_feasibility_max = max(
        float(primal_residual_report.max_bound_violation),
        float(primal_residual_report.max_eq27_active_balance_residual),
        float(primal_residual_report.max_failed_line_flow_violation),
    )
    for constraint in canonical.geq_constraints:
        lhs = evaluate_canonical_constraint(constraint, canonical_primal)
        slack = float(lhs - constraint.rhs)
        geq_constraint_slacks[constraint.name] = slack
        primal_feasibility_max = max(primal_feasibility_max, max(0.0, -slack))

    for constraint in canonical.equality_constraints:
        lhs = evaluate_canonical_constraint(constraint, canonical_primal)
        primal_feasibility_max = max(primal_feasibility_max, abs(lhs - constraint.rhs))

    dual_feasibility_max = 0.0
    for value in dual_solution.geq_dual_values.values():
        dual_feasibility_max = max(dual_feasibility_max, max(0.0, -float(value)))
    for slack in dual_solution.dual_constraint_slacks_by_primal_var.values():
        dual_feasibility_max = max(dual_feasibility_max, max(0.0, -float(slack)))

    row_complementarity_products = {
        constraint.name: float(dual_solution.geq_dual_values[constraint.name] * geq_constraint_slacks[constraint.name])
        for constraint in canonical.geq_constraints
    }
    variable_complementarity_products = {
        variable.name: float(canonical_primal[variable.name] * dual_solution.dual_constraint_slacks_by_primal_var[variable.name])
        for variable in canonical.variables
    }

    primal_objective = float(primal_solution.objective_value or 0.0)
    dual_objective = float(dual_solution.objective_value or 0.0)
    return KKTCheckReport(
        primal_feasibility_max_violation=float(primal_feasibility_max),
        dual_feasibility_max_violation=float(dual_feasibility_max),
        strong_duality_gap=abs(primal_objective - dual_objective),
        max_row_complementarity=max(abs(value) for value in row_complementarity_products.values()) if row_complementarity_products else 0.0,
        max_variable_complementarity=max(abs(value) for value in variable_complementarity_products.values()) if variable_complementarity_products else 0.0,
        geq_constraint_slacks=geq_constraint_slacks,
        dual_constraint_slacks=dict(dual_solution.dual_constraint_slacks_by_primal_var),
        row_complementarity_products=row_complementarity_products,
        variable_complementarity_products=variable_complementarity_products,
    )
