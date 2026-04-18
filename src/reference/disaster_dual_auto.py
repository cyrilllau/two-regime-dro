"""Mechanically derived auto dual for the canonicalized disaster primal LP."""

from __future__ import annotations

from dataclasses import dataclass, field

from gurobipy import GRB, Model, quicksum

from src.reference.lp_canonicalizer import CanonicalizedReferenceLP


@dataclass(frozen=True)
class DisasterAutoDualModel:
    """Built auto dual plus alignment metadata."""

    canonical_lp: CanonicalizedReferenceLP
    model: Model
    equality_dual_vars: dict[str, object] = field(default_factory=dict)
    geq_dual_vars: dict[str, object] = field(default_factory=dict)
    dual_constraint_by_primal_var: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DisasterAutoDualSolution:
    """Structured solved result for the mechanically derived auto dual."""

    objective_value: float | None
    model_status: str
    raw_status_code: int
    equality_dual_values: dict[str, float]
    geq_dual_values: dict[str, float]
    dual_constraint_slacks_by_primal_var: dict[str, float]


def build_disaster_dual_auto(
    canonical_lp: CanonicalizedReferenceLP,
    *,
    model_name: str = "disaster_dual_auto",
    log_to_console: bool = False,
) -> DisasterAutoDualModel:
    """Build the auto dual mechanically from the canonical LP."""

    model = Model(model_name)
    model.Params.OutputFlag = 1 if log_to_console else 0

    equality_dual_vars = {
        constraint.name: model.addVar(lb=-GRB.INFINITY, name=f"lambda_{constraint.name}")
        for constraint in canonical_lp.equality_constraints
    }
    geq_dual_vars = {
        constraint.name: model.addVar(lb=0.0, name=f"pi_{constraint.name}")
        for constraint in canonical_lp.geq_constraints
    }

    model.setObjective(
        quicksum(
            constraint.rhs * equality_dual_vars[constraint.name]
            for constraint in canonical_lp.equality_constraints
        )
        + quicksum(
            constraint.rhs * geq_dual_vars[constraint.name]
            for constraint in canonical_lp.geq_constraints
        ),
        sense=GRB.MAXIMIZE,
    )

    dual_constraint_by_primal_var = {}
    objective_coefficients = canonical_lp.objective_coefficients
    for variable_name in canonical_lp.variable_names:
        lhs = quicksum(
            constraint.coefficients.get(variable_name, 0.0) * equality_dual_vars[constraint.name]
            for constraint in canonical_lp.equality_constraints
            if variable_name in constraint.coefficients
        ) + quicksum(
            constraint.coefficients.get(variable_name, 0.0) * geq_dual_vars[constraint.name]
            for constraint in canonical_lp.geq_constraints
            if variable_name in constraint.coefficients
        )
        dual_constraint_by_primal_var[variable_name] = model.addConstr(
            lhs <= objective_coefficients[variable_name],
            name=f"dual_feas_{variable_name}",
        )

    model.update()
    return DisasterAutoDualModel(
        canonical_lp=canonical_lp,
        model=model,
        equality_dual_vars=equality_dual_vars,
        geq_dual_vars=geq_dual_vars,
        dual_constraint_by_primal_var=dual_constraint_by_primal_var,
    )


def extract_disaster_dual_auto_solution(
    auto_dual_model: DisasterAutoDualModel,
) -> DisasterAutoDualSolution:
    """Extract a structured solution from an optimized auto dual model."""

    model = auto_dual_model.model
    status_code = int(model.Status)
    status_name = str(model.Status)
    if status_code == GRB.OPTIMAL:
        status_name = "OPTIMAL"
    elif status_code == GRB.INFEASIBLE:
        status_name = "INFEASIBLE"
    elif status_code == GRB.UNBOUNDED:
        status_name = "UNBOUNDED"

    objective_value = float(model.ObjVal) if status_code == GRB.OPTIMAL else None
    dual_constraint_slacks = {}
    objective_coefficients = auto_dual_model.canonical_lp.objective_coefficients
    for variable_name in auto_dual_model.canonical_lp.variable_names:
        lhs = 0.0
        for constraint in auto_dual_model.canonical_lp.equality_constraints:
            lhs += (
                constraint.coefficients.get(variable_name, 0.0)
                * auto_dual_model.equality_dual_vars[constraint.name].X
            )
        for constraint in auto_dual_model.canonical_lp.geq_constraints:
            lhs += (
                constraint.coefficients.get(variable_name, 0.0)
                * auto_dual_model.geq_dual_vars[constraint.name].X
            )
        dual_constraint_slacks[variable_name] = float(objective_coefficients[variable_name] - lhs)

    return DisasterAutoDualSolution(
        objective_value=objective_value,
        model_status=status_name,
        raw_status_code=status_code,
        equality_dual_values={
            name: float(var.X) for name, var in auto_dual_model.equality_dual_vars.items()
        },
        geq_dual_values={
            name: float(var.X) for name, var in auto_dual_model.geq_dual_vars.items()
        },
        dual_constraint_slacks_by_primal_var=dual_constraint_slacks,
    )


def solve_disaster_dual_auto(
    canonical_lp: CanonicalizedReferenceLP,
    *,
    model_name: str = "disaster_dual_auto",
    log_to_console: bool = False,
) -> tuple[DisasterAutoDualModel, DisasterAutoDualSolution]:
    """Build, solve, and extract the mechanically derived auto dual."""

    auto_dual_model = build_disaster_dual_auto(
        canonical_lp,
        model_name=model_name,
        log_to_console=log_to_console,
    )
    auto_dual_model.model.optimize()
    solution = extract_disaster_dual_auto_solution(auto_dual_model)
    if solution.model_status != "OPTIMAL":
        raise ValueError(
            f"Auto dual solve did not reach OPTIMAL status: "
            f"{solution.model_status} (code {solution.raw_status_code})."
        )
    return auto_dual_model, solution
