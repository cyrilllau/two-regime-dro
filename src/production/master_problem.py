"""Production restricted master problem for fixed disaster cuts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from gurobipy import GRB, Model, quicksum

from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import RuntimeDataValidationError
from src.production.disaster_dual_paper import SamplewisePaperDualDecomposition
from src.production.first_stage import (
    FirstStageBlock,
    FirstStageSolution,
    build_first_stage_model,
    extract_first_stage_solution,
)
from src.production.normal_block import (
    NormalOperationBlock,
    NormalOperationSolution,
    build_normal_operation_block,
    extract_normal_operation_solution,
)


@dataclass(frozen=True)
class RestrictedMasterCut:
    """Structured production representation of one fixed disaster cut."""

    cut_id: str
    beta: float
    gamma_z_by_bus: dict[int, float] = field(default_factory=dict)
    gamma_n_sl_by_bus: dict[int, float] = field(default_factory=dict)
    gamma_n_fa_by_bus: dict[int, float] = field(default_factory=dict)
    phi_by_line_id: dict[str, float] = field(default_factory=dict)

    def is_trivial(self, *, atol: float = 1e-12) -> bool:
        """Return whether the cut is numerically the zero cut."""

        if abs(float(self.beta)) > atol:
            return False
        coefficient_groups = (
            self.gamma_z_by_bus,
            self.gamma_n_sl_by_bus,
            self.gamma_n_fa_by_bus,
            self.phi_by_line_id,
        )
        return all(
            abs(float(value)) <= atol
            for mapping in coefficient_groups
            for value in mapping.values()
        )

    @classmethod
    def from_samplewise_decomposition(
        cls,
        instance: CanonicalInstance,
        decomposition: SamplewisePaperDualDecomposition,
        *,
        cut_id: str,
    ) -> "RestrictedMasterCut":
        """Build a production master cut from a validated paper-dual decomposition."""

        return _normalize_cut(
            instance,
            cls(
                cut_id=cut_id,
                beta=float(decomposition.beta_b),
                gamma_z_by_bus=dict(decomposition.gamma_z_by_bus),
                gamma_n_sl_by_bus=dict(decomposition.gamma_n_sl_by_bus),
                gamma_n_fa_by_bus=dict(decomposition.gamma_n_fa_by_bus),
                phi_by_line_id=dict(decomposition.phi_by_line_id),
            ),
        )


@dataclass(frozen=True)
class RestrictedMasterProblem:
    """Built fixed-cut restricted master problem with auditable structure."""

    instance: CanonicalInstance
    model: Model
    first_stage: FirstStageBlock
    normal_blocks_by_scenario: dict[int, NormalOperationBlock]
    ordered_buses: tuple[int, ...]
    ordered_line_ids: tuple[str, ...]
    normal_scenario_ids: tuple[int, ...]
    cuts: tuple[RestrictedMasterCut, ...]
    budget_k: int
    fp_by_line_id: dict[str, float]
    normal_average_weight: float
    alpha_var: object
    lambda_by_line_id: dict[str, object] = field(default_factory=dict)
    s_by_cut_id: dict[str, object] = field(default_factory=dict)
    u_by_cut_id_and_line_id: dict[tuple[str, str], object] = field(default_factory=dict)
    cut_support_constraints: dict[str, object] = field(default_factory=dict)
    u_link_constraints: dict[tuple[str, str], object] = field(default_factory=dict)
    construction_cost_expression: object | None = None
    averaged_normal_cost_expression: object | None = None
    disaster_master_expression: object | None = None
    total_objective_expression: object | None = None


@dataclass(frozen=True)
class RestrictedMasterProblemSolution:
    """Structured solved result for the fixed-cut restricted master problem."""

    objective_value: float | None
    model_status: str
    raw_status_code: int
    first_stage_solution: FirstStageSolution
    normal_solutions_by_scenario: dict[int, NormalOperationSolution]
    alpha_value: float
    lambda_by_line_id: dict[str, float]
    s_by_cut_id: dict[str, float]
    u_by_cut_id_and_line_id: dict[tuple[str, str], float]
    construction_cost_value: float
    averaged_normal_cost_value: float
    unweighted_average_normal_cost_value: float
    normal_cost_by_scenario: dict[int, float]
    disaster_master_cost_value: float
    lambda_fp_value: float
    objective_reconstruction_gap: float


def _normalize_numeric_map(
    raw: Mapping[object, object] | None,
    *,
    keys: Sequence[object],
    label: str,
) -> dict[object, float]:
    normalized = {key: 0.0 for key in keys}
    if raw is None:
        return normalized
    invalid = sorted(key for key in raw if key not in normalized)
    if invalid:
        raise RuntimeDataValidationError(f"{label} contains invalid keys: {tuple(invalid)}.")
    for key, value in raw.items():
        normalized[key] = float(value)
    return normalized


def _normalize_bus_map(
    raw: Mapping[int, float] | None,
    *,
    buses: Sequence[int],
    label: str,
) -> dict[int, float]:
    return {
        int(key): float(value)
        for key, value in _normalize_numeric_map(raw, keys=buses, label=label).items()
    }


def _normalize_line_map(
    raw: Mapping[str, float] | None,
    *,
    line_ids: Sequence[str],
    label: str,
) -> dict[str, float]:
    return {
        str(key): float(value)
        for key, value in _normalize_numeric_map(raw, keys=line_ids, label=label).items()
    }


def _build_trivial_cut(instance: CanonicalInstance) -> RestrictedMasterCut:
    """Return the zero cut used when no explicit cut family is supplied."""

    return RestrictedMasterCut(
        cut_id="trivial_cut",
        beta=0.0,
        gamma_z_by_bus={bus: 0.0 for bus in instance.sets.buses},
        gamma_n_sl_by_bus={bus: 0.0 for bus in instance.sets.buses},
        gamma_n_fa_by_bus={bus: 0.0 for bus in instance.sets.buses},
        phi_by_line_id={line_id: 0.0 for line_id in instance.sets.line_ids},
    )


def _normalize_cut(
    instance: CanonicalInstance,
    cut: RestrictedMasterCut,
) -> RestrictedMasterCut:
    cut_id = str(cut.cut_id).strip()
    if cut_id == "":
        raise RuntimeDataValidationError("Each disaster cut must have a nonempty cut_id.")
    return RestrictedMasterCut(
        cut_id=cut_id,
        beta=float(cut.beta),
        gamma_z_by_bus=_normalize_bus_map(
            cut.gamma_z_by_bus,
            buses=instance.sets.buses,
            label=f"cuts[{cut_id}].gamma_z_by_bus",
        ),
        gamma_n_sl_by_bus=_normalize_bus_map(
            cut.gamma_n_sl_by_bus,
            buses=instance.sets.buses,
            label=f"cuts[{cut_id}].gamma_n_sl_by_bus",
        ),
        gamma_n_fa_by_bus=_normalize_bus_map(
            cut.gamma_n_fa_by_bus,
            buses=instance.sets.buses,
            label=f"cuts[{cut_id}].gamma_n_fa_by_bus",
        ),
        phi_by_line_id=_normalize_line_map(
            cut.phi_by_line_id,
            line_ids=instance.sets.line_ids,
            label=f"cuts[{cut_id}].phi_by_line_id",
        ),
    )


def _resolve_cuts(
    instance: CanonicalInstance,
    cuts: Sequence[RestrictedMasterCut] | None,
) -> tuple[RestrictedMasterCut, ...]:
    if not cuts:
        return (_build_trivial_cut(instance),)

    normalized = tuple(_normalize_cut(instance, cut) for cut in cuts)
    cut_ids = tuple(cut.cut_id for cut in normalized)
    if len(set(cut_ids)) != len(cut_ids):
        raise RuntimeDataValidationError(f"Duplicate cut ids are not allowed: {cut_ids}.")
    return normalized


def _resolve_normal_scenario_ids(
    instance: CanonicalInstance,
    normal_scenario_ids: Sequence[int] | None,
) -> tuple[int, ...]:
    selected = tuple(
        int(scenario_id)
        for scenario_id in (
            normal_scenario_ids
            if normal_scenario_ids is not None
            else instance.sets.loaded_normal_scenarios
        )
    )
    if not selected:
        raise RuntimeDataValidationError("At least one selected normal scenario is required.")
    if len(set(selected)) != len(selected):
        raise RuntimeDataValidationError(
            f"normal_scenario_ids contains duplicates: {selected}."
        )
    loaded = set(instance.sets.loaded_normal_scenarios)
    invalid = tuple(sorted(scenario_id for scenario_id in selected if scenario_id not in loaded))
    if invalid:
        raise RuntimeDataValidationError(
            "normal_scenario_ids contains scenarios outside the loaded canonical selection: "
            f"{invalid}."
        )
    return selected


def _resolve_budget_k(instance: CanonicalInstance) -> int:
    budget_k = int(instance.ambiguity.k_max_outages)
    if budget_k < 0:
        raise RuntimeDataValidationError(
            f"ambig.K must be nonnegative, got {instance.ambiguity.k_max_outages!r}."
        )
    return budget_k


def _resolve_fp_by_line_id(instance: CanonicalInstance) -> dict[str, float]:
    line_ids = instance.sets.line_ids
    p_bar = tuple(float(value) for value in instance.ambiguity.p_bar)
    if len(p_bar) != len(line_ids):
        raise RuntimeDataValidationError(
            f"ambig.p_bar has length {len(p_bar)}, expected {len(line_ids)}."
        )
    return {line_id: p_bar[index] for index, line_id in enumerate(line_ids)}


def build_master_problem(
    instance: CanonicalInstance,
    *,
    cuts: Sequence[RestrictedMasterCut] | None = None,
    normal_scenario_ids: Sequence[int] | None = None,
    model_name: str = "restricted_master_problem",
    log_to_console: bool = False,
) -> RestrictedMasterProblem:
    """Build the fixed-cut restricted master problem for Eq. (33), (37)-(39)."""

    ordered_buses = instance.sets.buses
    ordered_line_ids = instance.sets.line_ids
    selected_normal_scenarios = _resolve_normal_scenario_ids(instance, normal_scenario_ids)
    budget_k = _resolve_budget_k(instance)
    normalized_cuts = _resolve_cuts(instance, cuts)
    fp_by_line_id = _resolve_fp_by_line_id(instance)

    first_stage = build_first_stage_model(
        instance,
        model_name=model_name,
        log_to_console=log_to_console,
        attach_objective=False,
    )
    model = first_stage.model

    normal_blocks_by_scenario: dict[int, NormalOperationBlock] = {}
    for scenario_id in selected_normal_scenarios:
        normal_blocks_by_scenario[scenario_id] = build_normal_operation_block(
            instance,
            first_stage=first_stage,
            scenario_id=scenario_id,
            model=model,
            model_name=model_name,
            log_to_console=log_to_console,
            attach_objective=False,
        )

    alpha_var = model.addVar(
        lb=float(instance.economics.alpha_min),
        name="alpha",
    )
    lambda_by_line_id = {
        line_id: model.addVar(lb=0.0, name=f"lambda_{line_id}")
        for line_id in ordered_line_ids
    }

    s_by_cut_id: dict[str, object] = {}
    u_by_cut_id_and_line_id: dict[tuple[str, str], object] = {}
    cut_support_constraints: dict[str, object] = {}
    u_link_constraints: dict[tuple[str, str], object] = {}

    for cut in normalized_cuts:
        s_var = model.addVar(lb=0.0, name=f"s_cut_{cut.cut_id}")
        s_by_cut_id[cut.cut_id] = s_var

        u_expr = quicksum(
            (
                u_by_cut_id_and_line_id.setdefault(
                    (cut.cut_id, line_id),
                    model.addVar(lb=0.0, name=f"u_cut_{cut.cut_id}_{line_id}"),
                )
            )
            for line_id in ordered_line_ids
        )
        gamma_expr = quicksum(
            cut.gamma_z_by_bus[bus] * first_stage.z_by_bus[bus]
            + cut.gamma_n_sl_by_bus[bus] * first_stage.n_sl_by_bus[bus]
            + cut.gamma_n_fa_by_bus[bus] * first_stage.n_fa_by_bus[bus]
            for bus in ordered_buses
        )
        cut_support_constraints[cut.cut_id] = model.addConstr(
            alpha_var >= float(cut.beta) - gamma_expr + float(budget_k) * s_var + u_expr,
            name=f"eq39_cut_support_{cut.cut_id}",
        )

        for line_id in ordered_line_ids:
            u_var = u_by_cut_id_and_line_id[(cut.cut_id, line_id)]
            u_link_constraints[(cut.cut_id, line_id)] = model.addConstr(
                u_var >= float(cut.phi_by_line_id[line_id]) - lambda_by_line_id[line_id] - s_var,
                name=f"eq39_u_link_{cut.cut_id}_{line_id}",
            )

    normal_average_weight = float((1.0 - instance.economics.pi_f) / len(selected_normal_scenarios))
    construction_cost_expression = first_stage.construction_cost_expression
    averaged_normal_cost_expression = normal_average_weight * quicksum(
        normal_blocks_by_scenario[scenario_id].total_normal_cost_expression
        for scenario_id in selected_normal_scenarios
    )
    disaster_master_expression = float(instance.economics.pi_f) * (
        alpha_var
        + quicksum(
            fp_by_line_id[line_id] * lambda_by_line_id[line_id]
            for line_id in ordered_line_ids
        )
    )
    total_objective_expression = (
        construction_cost_expression
        + averaged_normal_cost_expression
        + disaster_master_expression
    )
    model.setObjective(total_objective_expression, sense=GRB.MINIMIZE)
    model.update()

    return RestrictedMasterProblem(
        instance=instance,
        model=model,
        first_stage=first_stage,
        normal_blocks_by_scenario=normal_blocks_by_scenario,
        ordered_buses=ordered_buses,
        ordered_line_ids=ordered_line_ids,
        normal_scenario_ids=selected_normal_scenarios,
        cuts=normalized_cuts,
        budget_k=budget_k,
        fp_by_line_id=fp_by_line_id,
        normal_average_weight=normal_average_weight,
        alpha_var=alpha_var,
        lambda_by_line_id=lambda_by_line_id,
        s_by_cut_id=s_by_cut_id,
        u_by_cut_id_and_line_id=u_by_cut_id_and_line_id,
        cut_support_constraints=cut_support_constraints,
        u_link_constraints=u_link_constraints,
        construction_cost_expression=construction_cost_expression,
        averaged_normal_cost_expression=averaged_normal_cost_expression,
        disaster_master_expression=disaster_master_expression,
        total_objective_expression=total_objective_expression,
    )


def extract_master_problem_solution(
    master_problem: RestrictedMasterProblem,
) -> RestrictedMasterProblemSolution:
    """Extract a structured solution from an optimized restricted master problem."""

    model = master_problem.model
    status_code = int(model.Status)
    status_name = str(model.Status)
    if status_code == GRB.OPTIMAL:
        status_name = "OPTIMAL"
    elif status_code == GRB.INFEASIBLE:
        status_name = "INFEASIBLE"
    elif status_code == GRB.UNBOUNDED:
        status_name = "UNBOUNDED"

    first_stage_solution = extract_first_stage_solution(master_problem.first_stage)
    normal_solutions_by_scenario = {
        scenario_id: extract_normal_operation_solution(normal_block)
        for scenario_id, normal_block in master_problem.normal_blocks_by_scenario.items()
    }
    if status_code != GRB.OPTIMAL:
        return RestrictedMasterProblemSolution(
            objective_value=None,
            model_status=status_name,
            raw_status_code=status_code,
            first_stage_solution=first_stage_solution,
            normal_solutions_by_scenario=normal_solutions_by_scenario,
            alpha_value=0.0,
            lambda_by_line_id={line_id: 0.0 for line_id in master_problem.ordered_line_ids},
            s_by_cut_id={cut.cut_id: 0.0 for cut in master_problem.cuts},
            u_by_cut_id_and_line_id={
                (cut.cut_id, line_id): 0.0
                for cut in master_problem.cuts
                for line_id in master_problem.ordered_line_ids
            },
            construction_cost_value=first_stage_solution.construction_cost_value,
            averaged_normal_cost_value=0.0,
            unweighted_average_normal_cost_value=0.0,
            normal_cost_by_scenario={
                scenario_id: 0.0 for scenario_id in master_problem.normal_scenario_ids
            },
            disaster_master_cost_value=0.0,
            lambda_fp_value=0.0,
            objective_reconstruction_gap=0.0,
        )

    alpha_value = float(master_problem.alpha_var.X)
    lambda_values = {
        line_id: float(var.X) for line_id, var in master_problem.lambda_by_line_id.items()
    }
    s_values = {
        cut_id: float(var.X) for cut_id, var in master_problem.s_by_cut_id.items()
    }
    u_values = {
        key: float(var.X) for key, var in master_problem.u_by_cut_id_and_line_id.items()
    }
    normal_cost_by_scenario = {
        scenario_id: float(solution.normal_objective_value)
        for scenario_id, solution in normal_solutions_by_scenario.items()
    }
    construction_cost_value = float(first_stage_solution.construction_cost_value)
    unweighted_average_normal_cost_value = float(
        sum(normal_cost_by_scenario.values()) / len(master_problem.normal_scenario_ids)
    )
    averaged_normal_cost_value = float(
        master_problem.normal_average_weight * sum(normal_cost_by_scenario.values())
    )
    lambda_fp_value = float(
        sum(
            master_problem.fp_by_line_id[line_id] * lambda_values[line_id]
            for line_id in master_problem.ordered_line_ids
        )
    )
    disaster_master_cost_value = float(
        master_problem.instance.economics.pi_f * (alpha_value + lambda_fp_value)
    )
    reconstructed_objective = float(
        construction_cost_value + averaged_normal_cost_value + disaster_master_cost_value
    )
    objective_value = float(model.ObjVal)

    return RestrictedMasterProblemSolution(
        objective_value=objective_value,
        model_status=status_name,
        raw_status_code=status_code,
        first_stage_solution=first_stage_solution,
        normal_solutions_by_scenario=normal_solutions_by_scenario,
        alpha_value=alpha_value,
        lambda_by_line_id=lambda_values,
        s_by_cut_id=s_values,
        u_by_cut_id_and_line_id=u_values,
        construction_cost_value=construction_cost_value,
        averaged_normal_cost_value=averaged_normal_cost_value,
        unweighted_average_normal_cost_value=unweighted_average_normal_cost_value,
        normal_cost_by_scenario=normal_cost_by_scenario,
        disaster_master_cost_value=disaster_master_cost_value,
        lambda_fp_value=lambda_fp_value,
        objective_reconstruction_gap=abs(objective_value - reconstructed_objective),
    )


def solve_master_problem(
    instance: CanonicalInstance,
    *,
    cuts: Sequence[RestrictedMasterCut] | None = None,
    normal_scenario_ids: Sequence[int] | None = None,
    model_name: str = "restricted_master_problem",
    log_to_console: bool = False,
) -> tuple[RestrictedMasterProblem, RestrictedMasterProblemSolution]:
    """Build, solve, and extract the fixed-cut restricted master problem."""

    master_problem = build_master_problem(
        instance,
        cuts=cuts,
        normal_scenario_ids=normal_scenario_ids,
        model_name=model_name,
        log_to_console=log_to_console,
    )
    master_problem.model.optimize()
    solution = extract_master_problem_solution(master_problem)
    if solution.model_status != "OPTIMAL":
        raise ValueError(
            "Restricted master problem did not reach OPTIMAL status: "
            f"{solution.model_status} (code {solution.raw_status_code})."
        )
    return master_problem, solution
