"""Tiny finite-LP oracle for the outer DRO moment problem."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from gurobipy import GRB, Model, quicksum

from src.instance.validators import RuntimeDataValidationError
from src.reference.outage_enumerator import EnumeratedOutagePattern, enumerate_outages


@dataclass(frozen=True)
class DroOuterLPOracleModel:
    """Built finite outer-DRO LP oracle."""

    line_ids: tuple[str, ...]
    outage_patterns: tuple[EnumeratedOutagePattern, ...]
    value_by_pattern: dict[str, float]
    fp_by_line_id: dict[str, float]
    model: Model
    probability_vars: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DroOuterLPOracleSolution:
    """Structured solved result for the outer-DRO LP oracle."""

    objective_value: float | None
    model_status: str
    raw_status_code: int
    probability_by_pattern: dict[str, float]
    linewise_marginals: dict[str, float]


def _normalize_fp_by_line_id(
    line_ids: Sequence[str],
    fp_by_line_id: Mapping[str, float],
) -> dict[str, float]:
    normalized = {line_id: 0.0 for line_id in line_ids}
    invalid = sorted(line_id for line_id in fp_by_line_id if line_id not in normalized)
    if invalid:
        raise RuntimeDataValidationError(
            f"fp_by_line_id contains invalid line ids: {tuple(invalid)}."
        )
    for line_id, value in fp_by_line_id.items():
        numeric = float(value)
        if numeric < -1e-12:
            raise RuntimeDataValidationError(
                f"fp_by_line_id[{line_id!r}] must be nonnegative, got {numeric}."
            )
        normalized[line_id] = numeric
    return normalized


def _normalize_value_by_pattern(
    patterns: Sequence[EnumeratedOutagePattern],
    value_by_pattern: Mapping[str | tuple[int, ...], float],
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    valid_labels = {pattern.label for pattern in patterns}
    valid_values = {pattern.values for pattern in patterns}
    for key, value in value_by_pattern.items():
        if isinstance(key, tuple):
            if key not in valid_values:
                raise RuntimeDataValidationError(
                    f"value_by_pattern contains invalid outage tuple key: {key}."
                )
            label = next(pattern.label for pattern in patterns if pattern.values == key)
        else:
            label = str(key)
            if label not in valid_labels:
                raise RuntimeDataValidationError(
                    f"value_by_pattern contains invalid outage label: {label!r}."
                )
        normalized[label] = float(value)

    missing = sorted(label for label in valid_labels if label not in normalized)
    if missing:
        raise RuntimeDataValidationError(
            f"value_by_pattern is missing outage values for: {tuple(missing)}."
        )
    return normalized


def build_dro_outer_lp_oracle(
    *,
    line_ids: Sequence[str],
    fp_by_line_id: Mapping[str, float],
    value_by_pattern: Mapping[str | tuple[int, ...], float],
    outage_patterns: Sequence[EnumeratedOutagePattern] | None = None,
    budget_k: int | None = None,
    model_name: str = "dro_outer_lp_oracle",
    log_to_console: bool = False,
) -> DroOuterLPOracleModel:
    """Build the finite LP oracle for `sup_Q E_Q[f(delta)]` over enumerated outages."""

    line_tuple = tuple(str(line_id) for line_id in line_ids)
    if outage_patterns is None:
        if budget_k is None:
            raise RuntimeDataValidationError(
                "Either outage_patterns or budget_k must be provided to build the outer-DRO LP oracle."
            )
        patterns = enumerate_outages(line_tuple, budget_k=budget_k)
    else:
        patterns = tuple(outage_patterns)

    normalized_fp = _normalize_fp_by_line_id(line_tuple, fp_by_line_id)
    normalized_values = _normalize_value_by_pattern(patterns, value_by_pattern)

    model = Model(model_name)
    model.Params.OutputFlag = 1 if log_to_console else 0

    probability_vars = {
        pattern.label: model.addVar(lb=0.0, name=f"p_{pattern.label}")
        for pattern in patterns
    }

    model.setObjective(
        quicksum(
            normalized_values[pattern.label] * probability_vars[pattern.label]
            for pattern in patterns
        ),
        sense=GRB.MAXIMIZE,
    )
    model.addConstr(
        quicksum(probability_vars[pattern.label] for pattern in patterns) == 1.0,
        name="probability_mass",
    )
    for line_id in line_tuple:
        model.addConstr(
            quicksum(
                pattern.by_line_id[line_id] * probability_vars[pattern.label]
                for pattern in patterns
            )
            <= normalized_fp[line_id],
            name=f"fp_{line_id}",
        )

    model.update()
    return DroOuterLPOracleModel(
        line_ids=line_tuple,
        outage_patterns=patterns,
        value_by_pattern=normalized_values,
        fp_by_line_id=normalized_fp,
        model=model,
        probability_vars=probability_vars,
    )


def extract_dro_outer_lp_oracle_solution(
    oracle_model: DroOuterLPOracleModel,
) -> DroOuterLPOracleSolution:
    """Extract a structured solution from an optimized outer-DRO LP oracle model."""

    model = oracle_model.model
    status_code = int(model.Status)
    status_name = str(model.Status)
    if status_code == GRB.OPTIMAL:
        status_name = "OPTIMAL"
    elif status_code == GRB.INFEASIBLE:
        status_name = "INFEASIBLE"
    elif status_code == GRB.UNBOUNDED:
        status_name = "UNBOUNDED"

    objective_value = float(model.ObjVal) if status_code == GRB.OPTIMAL else None
    probability_by_pattern = {
        label: float(var.X)
        for label, var in oracle_model.probability_vars.items()
    }
    linewise_marginals = {
        line_id: float(
            sum(
                pattern.by_line_id[line_id] * probability_by_pattern[pattern.label]
                for pattern in oracle_model.outage_patterns
            )
        )
        for line_id in oracle_model.line_ids
    }
    return DroOuterLPOracleSolution(
        objective_value=objective_value,
        model_status=status_name,
        raw_status_code=status_code,
        probability_by_pattern=probability_by_pattern,
        linewise_marginals=linewise_marginals,
    )


def solve_dro_outer_lp_oracle(
    *,
    line_ids: Sequence[str],
    fp_by_line_id: Mapping[str, float],
    value_by_pattern: Mapping[str | tuple[int, ...], float],
    outage_patterns: Sequence[EnumeratedOutagePattern] | None = None,
    budget_k: int | None = None,
    model_name: str = "dro_outer_lp_oracle",
    log_to_console: bool = False,
) -> tuple[DroOuterLPOracleModel, DroOuterLPOracleSolution]:
    """Build, solve, and extract the tiny outer-DRO LP oracle."""

    oracle_model = build_dro_outer_lp_oracle(
        line_ids=line_ids,
        fp_by_line_id=fp_by_line_id,
        value_by_pattern=value_by_pattern,
        outage_patterns=outage_patterns,
        budget_k=budget_k,
        model_name=model_name,
        log_to_console=log_to_console,
    )
    oracle_model.model.optimize()
    solution = extract_dro_outer_lp_oracle_solution(oracle_model)
    if solution.model_status != "OPTIMAL":
        raise ValueError(
            f"Outer-DRO LP oracle did not reach OPTIMAL status: "
            f"{solution.model_status} (code {solution.raw_status_code})."
        )
    return oracle_model, solution
