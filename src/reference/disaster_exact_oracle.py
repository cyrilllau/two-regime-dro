"""Independent tiny disaster exact oracle using primal recourse evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import RuntimeDataValidationError
from src.reference.disaster_primal_ref import (
    FixedFirstStagePlan,
    build_fixed_outage_vector,
    solve_disaster_primal_reference,
)
from src.reference.dro_outer_lp_oracle import (
    DroOuterLPOracleModel,
    solve_dro_outer_lp_oracle,
)
from src.reference.outage_enumerator import EnumeratedOutagePattern, enumerate_outages


@dataclass(frozen=True)
class DisasterExactOracleResult:
    """Exact tiny disaster-DRO evaluation independent of the paper-dual chain."""

    weighted_objective_value: float
    outer_dro_value: float
    scenario_ids: tuple[int, ...]
    outage_patterns: tuple[EnumeratedOutagePattern, ...]
    value_by_pattern: dict[str, float] = field(default_factory=dict)
    samplewise_primal_objective_by_pattern: dict[str, dict[int, float]] = field(
        default_factory=dict
    )
    worst_case_probability_by_pattern: dict[str, float] = field(default_factory=dict)
    linewise_marginals: dict[str, float] = field(default_factory=dict)
    active_worst_case_patterns: tuple[str, ...] = field(default_factory=tuple)


def _resolve_disaster_scenario_ids(
    instance: CanonicalInstance,
    scenario_ids: Sequence[int] | None,
) -> tuple[int, ...]:
    selected = tuple(
        int(scenario_id)
        for scenario_id in (
            scenario_ids
            if scenario_ids is not None
            else instance.sets.loaded_disaster_scenarios
        )
    )
    if not selected:
        raise RuntimeDataValidationError("At least one disaster scenario is required.")
    if len(set(selected)) != len(selected):
        raise RuntimeDataValidationError(
            f"scenario_ids contains duplicate disaster scenarios: {selected}."
        )
    loaded = set(instance.sets.loaded_disaster_scenarios)
    invalid = tuple(sorted(scenario_id for scenario_id in selected if scenario_id not in loaded))
    if invalid:
        raise RuntimeDataValidationError(
            "scenario_ids contains scenarios outside the loaded canonical selection: "
            f"{invalid}."
        )
    return selected


def solve_disaster_exact_oracle(
    instance: CanonicalInstance,
    *,
    plan: FixedFirstStagePlan,
    scenario_ids: Sequence[int] | None = None,
    model_name_prefix: str = "disaster_exact_oracle",
    log_to_console: bool = False,
) -> tuple[DroOuterLPOracleModel, DisasterExactOracleResult]:
    """Evaluate the exact tiny disaster DRO term via primal recourse and outage enumeration."""

    selected_scenarios = _resolve_disaster_scenario_ids(instance, scenario_ids)
    outage_patterns = enumerate_outages(
        instance.sets.line_ids,
        budget_k=int(instance.ambiguity.k_max_outages),
    )

    samplewise_primal_objective_by_pattern: dict[str, dict[int, float]] = {}
    value_by_pattern: dict[str, float] = {}
    for pattern in outage_patterns:
        outage = build_fixed_outage_vector(instance, by_line_id=pattern.by_line_id)
        samplewise_values: dict[int, float] = {}
        for scenario_id in selected_scenarios:
            _, solution = solve_disaster_primal_reference(
                instance,
                plan=plan,
                outage=outage,
                scenario_id=scenario_id,
                model_name=f"{model_name_prefix}_{pattern.label}_b{scenario_id}",
                log_to_console=log_to_console,
            )
            samplewise_values[scenario_id] = float(solution.objective_value or 0.0)
        samplewise_primal_objective_by_pattern[pattern.label] = samplewise_values
        value_by_pattern[pattern.label] = float(
            sum(samplewise_values.values()) / len(selected_scenarios)
        )

    fp_by_line_id = {
        line_id: float(instance.ambiguity.p_bar[index])
        for index, line_id in enumerate(instance.sets.line_ids)
    }
    oracle_model, outer_solution = solve_dro_outer_lp_oracle(
        line_ids=instance.sets.line_ids,
        fp_by_line_id=fp_by_line_id,
        value_by_pattern=value_by_pattern,
        outage_patterns=outage_patterns,
        model_name=f"{model_name_prefix}_outer_dro",
        log_to_console=log_to_console,
    )

    return oracle_model, DisasterExactOracleResult(
        weighted_objective_value=float(
            instance.economics.pi_f * float(outer_solution.objective_value or 0.0)
        ),
        outer_dro_value=float(outer_solution.objective_value or 0.0),
        scenario_ids=selected_scenarios,
        outage_patterns=outage_patterns,
        value_by_pattern=value_by_pattern,
        samplewise_primal_objective_by_pattern=samplewise_primal_objective_by_pattern,
        worst_case_probability_by_pattern=dict(outer_solution.probability_by_pattern),
        linewise_marginals=dict(outer_solution.linewise_marginals),
        active_worst_case_patterns=tuple(
            sorted(
                label
                for label, probability in outer_solution.probability_by_pattern.items()
                if probability > 1e-8
            )
        ),
    )
