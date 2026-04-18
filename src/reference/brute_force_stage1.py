"""Tiny brute-force stage-1 oracle for end-to-end Benders validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import RuntimeDataValidationError
from src.reference.disaster_exact_oracle import solve_disaster_exact_oracle
from src.production.disaster_dual_paper import solve_disaster_dual_paper
from src.production.first_stage import (
    build_first_stage_model,
    extract_first_stage_solution,
)
from src.production.normal_block import (
    build_normal_operation_block,
    extract_normal_operation_solution,
)
from src.reference.disaster_primal_ref import (
    FixedFirstStagePlan,
    build_fixed_first_stage_plan,
)
from src.reference.dro_outer_lp_oracle import solve_dro_outer_lp_oracle
from src.reference.outage_enumerator import enumerate_outages


@dataclass(frozen=True)
class BoundedFirstStagePlanCandidate:
    """One explicit plan inside the bounded tiny brute-force plan set."""

    plan_id: str
    plan: FixedFirstStagePlan


@dataclass(frozen=True)
class BruteForcePlanEvaluation:
    """Exact sampled-problem evaluation for one bounded fixed first-stage plan."""

    plan_id: str
    plan: FixedFirstStagePlan
    construction_cost_value: float
    averaged_normal_cost_value: float
    disaster_dro_cost_value: float
    total_objective_value: float
    normal_cost_by_scenario: dict[int, float] = field(default_factory=dict)
    value_by_outage_pattern: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class BruteForceStage1OracleResult:
    """Best bounded first-stage plan under exact tiny normal + disaster evaluation."""

    best_plan_evaluation: BruteForcePlanEvaluation
    evaluations: tuple[BruteForcePlanEvaluation, ...]


def _fix_first_stage_plan(
    instance: CanonicalInstance,
    plan: FixedFirstStagePlan,
    *,
    attach_objective: bool,
    model_name: str,
    log_to_console: bool,
):
    first_stage = build_first_stage_model(
        instance,
        model_name=model_name,
        log_to_console=log_to_console,
        attach_objective=attach_objective,
    )
    for bus in instance.sets.buses:
        first_stage.model.addConstr(
            first_stage.z_by_bus[bus] == float(plan.z_by_bus[bus]),
            name=f"fix_z_n{bus}",
        )
        first_stage.model.addConstr(
            first_stage.n_sl_by_bus[bus] == float(plan.n_sl_by_bus[bus]),
            name=f"fix_n_sl_n{bus}",
        )
        first_stage.model.addConstr(
            first_stage.n_fa_by_bus[bus] == float(plan.n_fa_by_bus[bus]),
            name=f"fix_n_fa_n{bus}",
        )
    first_stage.model.update()
    return first_stage


def _evaluate_construction_cost(
    instance: CanonicalInstance,
    plan: FixedFirstStagePlan,
    *,
    log_to_console: bool = False,
) -> float:
    first_stage = _fix_first_stage_plan(
        instance,
        plan,
        attach_objective=True,
        model_name="bruteforce_first_stage_cost",
        log_to_console=log_to_console,
    )
    first_stage.model.optimize()
    solution = extract_first_stage_solution(first_stage)
    if solution.model_status != "OPTIMAL":
        raise ValueError(
            "Brute-force first-stage cost solve did not reach OPTIMAL status: "
            f"{solution.model_status} (code {solution.raw_status_code})."
        )
    return float(solution.construction_cost_value)


def _evaluate_normal_costs(
    instance: CanonicalInstance,
    plan: FixedFirstStagePlan,
    *,
    normal_scenario_ids: Sequence[int] | None = None,
    log_to_console: bool = False,
) -> tuple[float, dict[int, float]]:
    scenario_ids = tuple(
        int(scenario_id)
        for scenario_id in (
            normal_scenario_ids
            if normal_scenario_ids is not None
            else instance.sets.loaded_normal_scenarios
        )
    )
    normal_cost_by_scenario: dict[int, float] = {}
    for scenario_id in scenario_ids:
        first_stage = _fix_first_stage_plan(
            instance,
            plan,
            attach_objective=False,
            model_name=f"bruteforce_normal_s{scenario_id}",
            log_to_console=log_to_console,
        )
        normal_block = build_normal_operation_block(
            instance,
            first_stage=first_stage,
            scenario_id=scenario_id,
            model_name=f"bruteforce_normal_s{scenario_id}",
            log_to_console=log_to_console,
            attach_objective=True,
        )
        normal_block.model.optimize()
        normal_solution = extract_normal_operation_solution(normal_block)
        if normal_solution.model_status != "OPTIMAL":
            raise ValueError(
                "Brute-force normal solve did not reach OPTIMAL status: "
                f"{normal_solution.model_status} (code {normal_solution.raw_status_code})."
            )
        normal_cost_by_scenario[scenario_id] = float(normal_solution.normal_objective_value)

    averaged_normal_cost_value = float(
        ((1.0 - instance.economics.pi_f) / len(scenario_ids))
        * sum(normal_cost_by_scenario.values())
    )
    return averaged_normal_cost_value, normal_cost_by_scenario


def _evaluate_disaster_dro_cost(
    instance: CanonicalInstance,
    plan: FixedFirstStagePlan,
    *,
    disaster_scenario_ids: Sequence[int] | None = None,
    disaster_value_mode: str = "paper_dual",
    log_to_console: bool = False,
) -> tuple[float, dict[str, float]]:
    if disaster_value_mode == "primal_exact":
        _, exact_result = solve_disaster_exact_oracle(
            instance,
            plan=plan,
            scenario_ids=disaster_scenario_ids,
            model_name_prefix="bruteforce_primal_exact",
            log_to_console=log_to_console,
        )
        return float(exact_result.weighted_objective_value), dict(exact_result.value_by_pattern)
    if disaster_value_mode != "paper_dual":
        raise RuntimeDataValidationError(
            "disaster_value_mode must be either 'paper_dual' or 'primal_exact', "
            f"got {disaster_value_mode!r}."
        )

    scenario_ids = tuple(
        int(scenario_id)
        for scenario_id in (
            disaster_scenario_ids
            if disaster_scenario_ids is not None
            else instance.sets.loaded_disaster_scenarios
        )
    )
    outage_patterns = enumerate_outages(
        instance.sets.line_ids,
        budget_k=int(instance.ambiguity.k_max_outages),
    )
    value_by_pattern: dict[str, float] = {}
    for pattern in outage_patterns:
        sample_values = []
        for scenario_id in scenario_ids:
            _, paper_dual_solution = solve_disaster_dual_paper(
                instance,
                plan=plan,
                outage=pattern,
                scenario_id=scenario_id,
                model_name=f"bruteforce_paper_dual_{pattern.label}_b{scenario_id}",
                log_to_console=log_to_console,
            )
            sample_values.append(float(paper_dual_solution.objective_value or 0.0))
        value_by_pattern[pattern.label] = float(sum(sample_values) / len(sample_values))

    fp_by_line_id = {
        line_id: float(instance.ambiguity.p_bar[index])
        for index, line_id in enumerate(instance.sets.line_ids)
    }
    _, dro_solution = solve_dro_outer_lp_oracle(
        line_ids=instance.sets.line_ids,
        fp_by_line_id=fp_by_line_id,
        value_by_pattern=value_by_pattern,
        outage_patterns=outage_patterns,
        model_name="bruteforce_outer_dro",
        log_to_console=log_to_console,
    )
    if dro_solution.model_status != "OPTIMAL":
        raise ValueError(
            "Brute-force outer-DRO LP did not reach OPTIMAL status: "
            f"{dro_solution.model_status} (code {dro_solution.raw_status_code})."
        )
    return float(instance.economics.pi_f * float(dro_solution.objective_value or 0.0)), value_by_pattern


def evaluate_bounded_first_stage_plan(
    instance: CanonicalInstance,
    candidate: BoundedFirstStagePlanCandidate,
    *,
    normal_scenario_ids: Sequence[int] | None = None,
    disaster_scenario_ids: Sequence[int] | None = None,
    disaster_value_mode: str = "paper_dual",
    log_to_console: bool = False,
) -> BruteForcePlanEvaluation:
    """Evaluate one bounded plan exactly on the tiny sampled problem."""

    construction_cost_value = _evaluate_construction_cost(
        instance,
        candidate.plan,
        log_to_console=log_to_console,
    )
    averaged_normal_cost_value, normal_cost_by_scenario = _evaluate_normal_costs(
        instance,
        candidate.plan,
        normal_scenario_ids=normal_scenario_ids,
        log_to_console=log_to_console,
    )
    disaster_dro_cost_value, value_by_pattern = _evaluate_disaster_dro_cost(
        instance,
        candidate.plan,
        disaster_scenario_ids=disaster_scenario_ids,
        disaster_value_mode=disaster_value_mode,
        log_to_console=log_to_console,
    )
    total_objective_value = float(
        construction_cost_value + averaged_normal_cost_value + disaster_dro_cost_value
    )
    return BruteForcePlanEvaluation(
        plan_id=candidate.plan_id,
        plan=candidate.plan,
        construction_cost_value=construction_cost_value,
        averaged_normal_cost_value=averaged_normal_cost_value,
        disaster_dro_cost_value=disaster_dro_cost_value,
        total_objective_value=total_objective_value,
        normal_cost_by_scenario=normal_cost_by_scenario,
        value_by_outage_pattern=value_by_pattern,
    )


def solve_bounded_first_stage_bruteforce(
    instance: CanonicalInstance,
    *,
    candidates: Sequence[BoundedFirstStagePlanCandidate],
    normal_scenario_ids: Sequence[int] | None = None,
    disaster_scenario_ids: Sequence[int] | None = None,
    disaster_value_mode: str = "paper_dual",
    log_to_console: bool = False,
) -> BruteForceStage1OracleResult:
    """Evaluate all bounded plans exactly and return the best one."""

    if not candidates:
        raise RuntimeDataValidationError(
            "At least one bounded first-stage candidate is required."
        )
    evaluations = tuple(
        evaluate_bounded_first_stage_plan(
            instance,
            candidate,
            normal_scenario_ids=normal_scenario_ids,
            disaster_scenario_ids=disaster_scenario_ids,
            disaster_value_mode=disaster_value_mode,
            log_to_console=log_to_console,
        )
        for candidate in candidates
    )
    best = min(
        evaluations,
        key=lambda evaluation: (evaluation.total_objective_value, evaluation.plan_id),
    )
    return BruteForceStage1OracleResult(
        best_plan_evaluation=best,
        evaluations=evaluations,
    )


def build_bounded_candidate(
    instance: CanonicalInstance,
    *,
    plan_id: str,
    z_by_bus: dict[int, int] | None = None,
    n_sl_by_bus: dict[int, int] | None = None,
    n_fa_by_bus: dict[int, int] | None = None,
) -> BoundedFirstStagePlanCandidate:
    """Build one validated bounded candidate from raw bus maps."""

    return BoundedFirstStagePlanCandidate(
        plan_id=str(plan_id),
        plan=build_fixed_first_stage_plan(
            instance,
            z_by_bus=z_by_bus,
            n_sl_by_bus=n_sl_by_bus,
            n_fa_by_bus=n_fa_by_bus,
        ),
    )
