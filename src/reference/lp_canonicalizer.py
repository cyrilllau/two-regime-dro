"""Canonical LP export for the fixed-(x, delta, b) disaster primal reference model."""

from __future__ import annotations

from dataclasses import dataclass, field

from gurobipy import GRB

from src.reference.disaster_primal_ref import (
    DisasterPrimalReferenceModel,
    DisasterPrimalSolution,
)


@dataclass(frozen=True)
class CanonicalVariable:
    """Canonical nonnegative primal variable after sign handling."""

    name: str
    original_var_name: str
    split_role: str
    objective_coefficient: float


@dataclass(frozen=True)
class CanonicalConstraint:
    """Canonical linear constraint row."""

    name: str
    rhs: float
    coefficients: dict[str, float] = field(default_factory=dict)
    original_constraint_name: str = ""
    original_sense: str = ""
    equation_group: str = ""


@dataclass(frozen=True)
class CanonicalizedReferenceLP:
    """Canonicalized disaster primal LP with x >= 0 and rows in = / >= form."""

    objective_sense: str
    variables: tuple[CanonicalVariable, ...]
    equality_constraints: tuple[CanonicalConstraint, ...]
    geq_constraints: tuple[CanonicalConstraint, ...]
    free_variable_map: dict[str, tuple[str, str]] = field(default_factory=dict)
    original_var_to_canonical: dict[str, tuple[tuple[str, float], ...]] = field(default_factory=dict)

    @property
    def variable_names(self) -> tuple[str, ...]:
        return tuple(variable.name for variable in self.variables)

    @property
    def objective_coefficients(self) -> dict[str, float]:
        return {variable.name: variable.objective_coefficient for variable in self.variables}


def _classify_equation_group(name: str) -> str:
    for prefix in ("eq27", "eq28", "eq29", "eq30", "eq31", "eq32"):
        if name.startswith(prefix):
            return prefix
    return "unclassified"


def _supports_nonnegative_form(var) -> bool:
    return abs(float(var.LB)) <= 1e-12 and var.UB >= GRB.INFINITY / 2


def _supports_free_form(var) -> bool:
    return var.LB <= -GRB.INFINITY / 2 and var.UB >= GRB.INFINITY / 2


def _transform_map(reference_model: DisasterPrimalReferenceModel) -> tuple[
    tuple[CanonicalVariable, ...],
    dict[str, tuple[tuple[str, float], ...]],
    dict[str, tuple[str, str]],
]:
    variables = []
    original_var_to_canonical: dict[str, tuple[tuple[str, float], ...]] = {}
    free_variable_map: dict[str, tuple[str, str]] = {}

    reference_model.model.update()
    for var in reference_model.model.getVars():
        if _supports_nonnegative_form(var):
            canonical_name = var.VarName
            variables.append(
                CanonicalVariable(
                    name=canonical_name,
                    original_var_name=var.VarName,
                    split_role="nonnegative",
                    objective_coefficient=float(var.Obj),
                )
            )
            original_var_to_canonical[var.VarName] = ((canonical_name, 1.0),)
            continue

        if _supports_free_form(var):
            pos_name = f"{var.VarName}__pos"
            neg_name = f"{var.VarName}__neg"
            variables.append(
                CanonicalVariable(
                    name=pos_name,
                    original_var_name=var.VarName,
                    split_role="free_pos",
                    objective_coefficient=float(var.Obj),
                )
            )
            variables.append(
                CanonicalVariable(
                    name=neg_name,
                    original_var_name=var.VarName,
                    split_role="free_neg",
                    objective_coefficient=-float(var.Obj),
                )
            )
            original_var_to_canonical[var.VarName] = ((pos_name, 1.0), (neg_name, -1.0))
            free_variable_map[var.VarName] = (pos_name, neg_name)
            continue

        raise ValueError(
            "Round 03 canonicalizer only supports nonnegative and free primal variables; "
            f"encountered unsupported bounds for {var.VarName}: LB={var.LB}, UB={var.UB}."
        )

    return tuple(variables), original_var_to_canonical, free_variable_map


def _normalize_coefficients(coefficients: dict[str, float]) -> dict[str, float]:
    return {
        name: float(value)
        for name, value in coefficients.items()
        if abs(float(value)) > 1e-12
    }


def canonicalize_reference_lp(
    reference_model: DisasterPrimalReferenceModel,
) -> CanonicalizedReferenceLP:
    """Canonicalize the current disaster primal LP into explicit = / >= / x>=0 form."""

    model = reference_model.model
    model.update()
    variables, original_var_to_canonical, free_variable_map = _transform_map(reference_model)
    equality_constraints: list[CanonicalConstraint] = []
    geq_constraints: list[CanonicalConstraint] = []

    for constraint in model.getConstrs():
        row = model.getRow(constraint)
        coefficients: dict[str, float] = {}
        for index in range(row.size()):
            var = row.getVar(index)
            coefficient = float(row.getCoeff(index))
            for canonical_name, sign in original_var_to_canonical[var.VarName]:
                coefficients[canonical_name] = coefficients.get(canonical_name, 0.0) + coefficient * sign

        coefficients = _normalize_coefficients(coefficients)
        rhs = float(constraint.RHS)
        name = str(constraint.ConstrName)
        sense = str(constraint.Sense)
        equation_group = _classify_equation_group(name)

        if sense == "=":
            equality_constraints.append(
                CanonicalConstraint(
                    name=name,
                    rhs=rhs,
                    coefficients=coefficients,
                    original_constraint_name=name,
                    original_sense=sense,
                    equation_group=equation_group,
                )
            )
            continue

        if sense == ">":
            geq_constraints.append(
                CanonicalConstraint(
                    name=name,
                    rhs=rhs,
                    coefficients=coefficients,
                    original_constraint_name=name,
                    original_sense=sense,
                    equation_group=equation_group,
                )
            )
            continue

        if sense == "<":
            geq_constraints.append(
                CanonicalConstraint(
                    name=f"{name}__canonical_ge",
                    rhs=-rhs,
                    coefficients={key: -value for key, value in coefficients.items()},
                    original_constraint_name=name,
                    original_sense=sense,
                    equation_group=equation_group,
                )
            )
            continue

        raise ValueError(f"Unsupported primal constraint sense {sense!r} for {name}.")

    return CanonicalizedReferenceLP(
        objective_sense="min",
        variables=variables,
        equality_constraints=tuple(equality_constraints),
        geq_constraints=tuple(geq_constraints),
        free_variable_map=free_variable_map,
        original_var_to_canonical=original_var_to_canonical,
    )


def extract_canonical_primal_solution(
    reference_model: DisasterPrimalReferenceModel,
    primal_solution: DisasterPrimalSolution,
    canonical_lp: CanonicalizedReferenceLP,
) -> dict[str, float]:
    """Map a solved primal point into the canonical nonnegative variable space."""

    original_values: dict[str, float] = {}
    for key, var in reference_model.load_shedding_vars.items():
        original_values[var.VarName] = primal_solution.load_shedding_by_time_bus[key]
    for key, var in reference_model.discharge_slow_vars.items():
        original_values[var.VarName] = primal_solution.discharge_slow_by_time_region_bus[key]
    for key, var in reference_model.discharge_fast_vars.items():
        original_values[var.VarName] = primal_solution.discharge_fast_by_time_region_bus[key]
    for key, var in reference_model.line_flow_vars.items():
        original_values[var.VarName] = primal_solution.line_flow_by_time_line[key]

    canonical_values: dict[str, float] = {}
    for variable in canonical_lp.variables:
        original_value = float(original_values[variable.original_var_name])
        if variable.split_role == "nonnegative":
            canonical_values[variable.name] = original_value
        elif variable.split_role == "free_pos":
            canonical_values[variable.name] = max(original_value, 0.0)
        elif variable.split_role == "free_neg":
            canonical_values[variable.name] = max(-original_value, 0.0)
        else:
            raise ValueError(f"Unsupported split role {variable.split_role!r}.")
    return canonical_values


def evaluate_canonical_constraint(
    constraint: CanonicalConstraint,
    canonical_values: dict[str, float],
) -> float:
    """Evaluate the left-hand side of a canonical row."""

    return sum(
        coefficient * canonical_values.get(variable_name, 0.0)
        for variable_name, coefficient in constraint.coefficients.items()
    )
