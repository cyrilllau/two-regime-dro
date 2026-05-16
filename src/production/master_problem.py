"""Production restricted master problem for fixed disaster cuts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from gurobipy import GRB, Model, quicksum

from src.instance.canonical_instance import CanonicalInstance
from src.instance.validators import (
    RuntimeDataValidationError,
    build_criticality_maps,
    require_explicit_critical_buses,
)
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
from src.reference.disaster_primal_ref import FixedFirstStagePlan


def _safe_gurobi_name(prefix: str, key: object, *, max_length: int = 240) -> str:
    """Return a stable Gurobi-safe name for long persisted cut identifiers."""

    raw = f"{prefix}_{key}"
    if len(raw) <= max_length:
        return raw
    digest = hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:16]
    prefix_budget = max(8, max_length - len(digest) - 1)
    return f"{prefix[:prefix_budget]}_{digest}"


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
class RestrictedMasterExactOutageRow:
    """One exact fixed-outage disaster recourse row in the hybrid master."""

    row_id: str
    active_line_ids: tuple[str, ...]


@dataclass(frozen=True)
class RestrictedMasterOutageColumnCut:
    """One NCCG row-wise recourse cut attached to a fixed outage column."""

    row_id: str
    column_id: str
    active_line_ids: tuple[str, ...]
    cut: RestrictedMasterCut


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
    disaster_scenario_ids: tuple[int, ...]
    cuts: tuple[RestrictedMasterCut, ...]
    exact_outage_rows: tuple[RestrictedMasterExactOutageRow, ...]
    outage_column_cuts: tuple[RestrictedMasterOutageColumnCut, ...]
    budget_k: int
    fp_by_line_id: dict[str, float]
    normal_average_weight: float
    normal_recourse_active: bool
    alpha_var: object
    lambda_by_line_id: dict[str, object] = field(default_factory=dict)
    s_by_cut_id: dict[str, object] = field(default_factory=dict)
    u_by_cut_id_and_line_id: dict[tuple[str, str], object] = field(default_factory=dict)
    eta_by_exact_row_id: dict[str, object] = field(default_factory=dict)
    theta_by_outage_column_id: dict[str, object] = field(default_factory=dict)
    cut_support_constraints: dict[str, object] = field(default_factory=dict)
    u_link_constraints: dict[tuple[str, str], object] = field(default_factory=dict)
    exact_row_epigraph_constraints: dict[str, object] = field(default_factory=dict)
    exact_row_support_constraints: dict[str, object] = field(default_factory=dict)
    outage_column_support_constraints: dict[str, object] = field(default_factory=dict)
    outage_column_cut_constraints: dict[str, object] = field(default_factory=dict)
    construction_cost_expression: object | None = None
    averaged_normal_cost_expression: object | None = None
    disaster_master_expression: object | None = None
    total_objective_expression: object | None = None
    objective_mode: str = "original"
    auxiliary_objective_expression: object | None = None
    auxiliary_level_constraint: object | None = None
    trust_region_center_plan: FixedFirstStagePlan | None = None
    trust_region_z_radius: int | None = None
    trust_region_charger_sl_radius: int | None = None
    trust_region_charger_fa_radius: int | None = None
    trust_region_constraints: dict[str, object] = field(default_factory=dict)


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
    original_total_objective_value: float | None = None
    theta_by_outage_column_id: dict[str, float] = field(default_factory=dict)


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


def _resolve_disaster_scenario_ids(
    instance: CanonicalInstance,
    disaster_scenario_ids: Sequence[int] | None,
) -> tuple[int, ...]:
    selected = tuple(
        int(scenario_id)
        for scenario_id in (
            disaster_scenario_ids
            if disaster_scenario_ids is not None
            else instance.sets.loaded_disaster_scenarios
        )
    )
    if not selected:
        raise RuntimeDataValidationError("At least one selected disaster scenario is required.")
    if len(set(selected)) != len(selected):
        raise RuntimeDataValidationError(
            f"disaster_scenario_ids contains duplicates: {selected}."
        )
    loaded = set(instance.sets.loaded_disaster_scenarios)
    invalid = tuple(sorted(scenario_id for scenario_id in selected if scenario_id not in loaded))
    if invalid:
        raise RuntimeDataValidationError(
            "disaster_scenario_ids contains scenarios outside the loaded canonical selection: "
            f"{invalid}."
        )
    return selected


def _resolve_cls_by_bus(instance: CanonicalInstance) -> dict[int, float]:
    require_explicit_critical_buses(
        buses=instance.sets.buses,
        critical_buses=instance.critical_buses,
        legacy_w=instance.ambiguity.legacy_w,
    )
    if instance.cls_by_bus is not None:
        return dict(instance.cls_by_bus)
    _, cls_by_bus = build_criticality_maps(
        buses=instance.sets.buses,
        critical_buses=instance.critical_buses,
        cls_critical=instance.frozen_config.disaster_objective.cls_critical,
        cls_noncritical=instance.frozen_config.disaster_objective.cls_noncritical,
    )
    if cls_by_bus is None:
        raise RuntimeDataValidationError(
            "critical_buses is required for disaster exact-row construction."
        )
    return cls_by_bus


def _resolve_exact_outage_rows(
    instance: CanonicalInstance,
    rows: Sequence[Sequence[str] | RestrictedMasterExactOutageRow] | None,
    *,
    budget_k: int,
) -> tuple[RestrictedMasterExactOutageRow, ...]:
    if not rows:
        return tuple()
    line_ids = tuple(str(line_id) for line_id in instance.sets.line_ids)
    line_set = set(line_ids)
    resolved: list[RestrictedMasterExactOutageRow] = []
    seen_patterns: set[tuple[str, ...]] = set()
    for index, raw in enumerate(rows, start=1):
        if isinstance(raw, RestrictedMasterExactOutageRow):
            active = tuple(str(line_id) for line_id in raw.active_line_ids)
            row_id = str(raw.row_id)
        else:
            active = tuple(str(line_id) for line_id in raw)
            row_id = f"exact_delta_{index:03d}"
        unique_active = set(active)
        invalid = tuple(sorted(line_id for line_id in unique_active if line_id not in line_set))
        if invalid:
            raise RuntimeDataValidationError(
                f"exact outage row {row_id!r} contains invalid line ids: {invalid}."
            )
        normalized = tuple(sorted(unique_active, key=line_ids.index))
        if len(normalized) > int(budget_k):
            raise RuntimeDataValidationError(
                f"exact outage row {row_id!r} has {len(normalized)} outages, K={budget_k}."
            )
        if normalized in seen_patterns:
            continue
        seen_patterns.add(normalized)
        resolved.append(
            RestrictedMasterExactOutageRow(row_id=row_id, active_line_ids=normalized)
        )
    return tuple(resolved)


def _resolve_outage_column_cuts(
    instance: CanonicalInstance,
    rows: Sequence[RestrictedMasterOutageColumnCut] | None,
    *,
    budget_k: int,
) -> tuple[RestrictedMasterOutageColumnCut, ...]:
    """Validate NCCG row-wise cuts and canonicalize their outage columns."""

    if not rows:
        return tuple()
    line_ids = tuple(str(line_id) for line_id in instance.sets.line_ids)
    line_set = set(line_ids)
    resolved: list[RestrictedMasterOutageColumnCut] = []
    seen_row_ids: set[str] = set()
    column_patterns: dict[str, tuple[str, ...]] = {}
    for index, row in enumerate(rows, start=1):
        row_id = str(row.row_id).strip()
        column_id = str(row.column_id).strip()
        if row_id == "":
            raise RuntimeDataValidationError(
                f"outage column cut #{index} has an empty row_id."
            )
        if column_id == "":
            raise RuntimeDataValidationError(
                f"outage column cut {row_id!r} has an empty column_id."
            )
        if row_id in seen_row_ids:
            raise RuntimeDataValidationError(
                f"Duplicate outage column cut row_id is not allowed: {row_id!r}."
            )
        seen_row_ids.add(row_id)

        active = tuple(str(line_id) for line_id in row.active_line_ids)
        invalid = tuple(sorted(line_id for line_id in set(active) if line_id not in line_set))
        if invalid:
            raise RuntimeDataValidationError(
                f"outage column cut {row_id!r} contains invalid line ids: {invalid}."
            )
        normalized_active = tuple(sorted(set(active), key=line_ids.index))
        if len(normalized_active) > int(budget_k):
            raise RuntimeDataValidationError(
                f"outage column cut {row_id!r} has {len(normalized_active)} outages, "
                f"K={budget_k}."
            )
        existing = column_patterns.get(column_id)
        if existing is not None and existing != normalized_active:
            raise RuntimeDataValidationError(
                f"outage column {column_id!r} is attached to incompatible patterns: "
                f"{existing} and {normalized_active}."
            )
        column_patterns[column_id] = normalized_active
        resolved.append(
            RestrictedMasterOutageColumnCut(
                row_id=row_id,
                column_id=column_id,
                active_line_ids=normalized_active,
                cut=_normalize_cut(instance, row.cut),
            )
        )
    return tuple(resolved)


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


def _normal_recourse_is_active(instance: CanonicalInstance) -> bool:
    """Return whether the training master should include normal-operation blocks."""

    return str(instance.metadata.get("benchmark_mode", "")).strip() != "disaster_only"


def _resolve_nonnegative_int_or_none(name: str, value: int | None) -> int | None:
    if value is None:
        return None
    resolved = int(value)
    if resolved < 0:
        raise RuntimeDataValidationError(f"{name} must be nonnegative, got {value!r}.")
    return resolved


def _resolve_nonnegative_float_or_none(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    resolved = float(value)
    if resolved < 0.0:
        raise RuntimeDataValidationError(f"{name} must be nonnegative, got {value!r}.")
    return resolved


def build_master_problem(
    instance: CanonicalInstance,
    *,
    cuts: Sequence[RestrictedMasterCut] | None = None,
    normal_scenario_ids: Sequence[int] | None = None,
    disaster_scenario_ids: Sequence[int] | None = None,
    exact_outage_rows: Sequence[Sequence[str] | RestrictedMasterExactOutageRow] | None = None,
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut] | None = None,
    warm_start_plan: FixedFirstStagePlan | None = None,
    warm_start_alpha: float | None = None,
    warm_start_lambda_by_line_id: Mapping[str, float] | None = None,
    trust_region_center_plan: FixedFirstStagePlan | None = None,
    trust_region_z_radius: int | None = None,
    trust_region_charger_sl_radius: int | None = None,
    trust_region_charger_fa_radius: int | None = None,
    level_bundle_center_plan: FixedFirstStagePlan | None = None,
    level_bundle_center_alpha: float | None = None,
    level_bundle_center_lambda_by_line_id: Mapping[str, float] | None = None,
    level_bundle_objective_upper_bound: float | None = None,
    level_bundle_rho_n: float = 0.2,
    level_bundle_rho_alpha: float = 0.05,
    level_bundle_rho_lambda: float = 1.0,
    model_name: str = "restricted_master_problem",
    log_to_console: bool = False,
) -> RestrictedMasterProblem:
    """Build the fixed-cut restricted master problem for Eq. (33), (37)-(39)."""

    ordered_buses = instance.sets.buses
    ordered_line_ids = instance.sets.line_ids
    selected_normal_scenarios = _resolve_normal_scenario_ids(instance, normal_scenario_ids)
    normal_recourse_active = _normal_recourse_is_active(instance)
    budget_k = _resolve_budget_k(instance)
    selected_disaster_scenarios = _resolve_disaster_scenario_ids(
        instance,
        disaster_scenario_ids,
    )
    normalized_cuts = _resolve_cuts(instance, cuts)
    normalized_exact_rows = _resolve_exact_outage_rows(
        instance,
        exact_outage_rows,
        budget_k=budget_k,
    )
    normalized_outage_column_cuts = _resolve_outage_column_cuts(
        instance,
        outage_column_cuts,
        budget_k=budget_k,
    )
    fp_by_line_id = _resolve_fp_by_line_id(instance)
    resolved_z_radius = _resolve_nonnegative_int_or_none(
        "trust_region_z_radius",
        trust_region_z_radius,
    )
    resolved_sl_radius = _resolve_nonnegative_int_or_none(
        "trust_region_charger_sl_radius",
        trust_region_charger_sl_radius,
    )
    resolved_fa_radius = _resolve_nonnegative_int_or_none(
        "trust_region_charger_fa_radius",
        trust_region_charger_fa_radius,
    )
    if trust_region_center_plan is None and (
        resolved_z_radius is not None
        or resolved_sl_radius is not None
        or resolved_fa_radius is not None
    ):
        raise RuntimeDataValidationError(
            "A trust_region_center_plan is required when trust-region radii are set."
        )
    resolved_level_bound = _resolve_nonnegative_float_or_none(
        "level_bundle_objective_upper_bound",
        level_bundle_objective_upper_bound,
    )
    if resolved_level_bound is not None and level_bundle_center_plan is None:
        raise RuntimeDataValidationError(
            "A level_bundle_center_plan is required when a level-bundle objective "
            "upper bound is set."
        )
    if level_bundle_center_plan is not None:
        if level_bundle_center_alpha is None:
            raise RuntimeDataValidationError(
                "level_bundle_center_alpha is required for a level-bundle auxiliary master."
            )
        if level_bundle_center_lambda_by_line_id is None:
            raise RuntimeDataValidationError(
                "level_bundle_center_lambda_by_line_id is required for a level-bundle "
                "auxiliary master."
            )
        invalid = sorted(
            str(line_id)
            for line_id in level_bundle_center_lambda_by_line_id
            if str(line_id) not in set(ordered_line_ids)
        )
        if invalid:
            raise RuntimeDataValidationError(
                "level_bundle_center_lambda_by_line_id contains invalid line ids: "
                f"{tuple(invalid)}."
            )

    first_stage = build_first_stage_model(
        instance,
        model_name=model_name,
        log_to_console=log_to_console,
        attach_objective=False,
    )
    model = first_stage.model
    if warm_start_plan is not None:
        for bus in ordered_buses:
            first_stage.z_by_bus[bus].Start = float(warm_start_plan.z_by_bus[bus])
            first_stage.n_sl_by_bus[bus].Start = float(warm_start_plan.n_sl_by_bus[bus])
            first_stage.n_fa_by_bus[bus].Start = float(warm_start_plan.n_fa_by_bus[bus])

    trust_region_constraints: dict[str, object] = {}
    if trust_region_center_plan is not None and resolved_z_radius is not None:
        z_distance_expr = quicksum(
            (
                1 - first_stage.z_by_bus[bus]
                if int(trust_region_center_plan.z_by_bus[bus]) == 1
                else first_stage.z_by_bus[bus]
            )
            for bus in ordered_buses
        )
        trust_region_constraints["local_branch_z"] = model.addConstr(
            z_distance_expr <= int(resolved_z_radius),
            name="trust_region_local_branch_z",
        )
    if trust_region_center_plan is not None and resolved_sl_radius is not None:
        sl_distance_vars = []
        for bus in ordered_buses:
            distance_var = model.addVar(lb=0.0, name=f"trust_region_abs_sl_{bus}")
            sl_distance_vars.append(distance_var)
            center_value = int(trust_region_center_plan.n_sl_by_bus[bus])
            model.addConstr(
                distance_var >= first_stage.n_sl_by_bus[bus] - center_value,
                name=f"trust_region_abs_sl_pos_{bus}",
            )
            model.addConstr(
                distance_var >= center_value - first_stage.n_sl_by_bus[bus],
                name=f"trust_region_abs_sl_neg_{bus}",
            )
        trust_region_constraints["local_branch_sl"] = model.addConstr(
            quicksum(sl_distance_vars) <= int(resolved_sl_radius),
            name="trust_region_local_branch_sl",
        )
    if trust_region_center_plan is not None and resolved_fa_radius is not None:
        fa_distance_vars = []
        for bus in ordered_buses:
            distance_var = model.addVar(lb=0.0, name=f"trust_region_abs_fa_{bus}")
            fa_distance_vars.append(distance_var)
            center_value = int(trust_region_center_plan.n_fa_by_bus[bus])
            model.addConstr(
                distance_var >= first_stage.n_fa_by_bus[bus] - center_value,
                name=f"trust_region_abs_fa_pos_{bus}",
            )
            model.addConstr(
                distance_var >= center_value - first_stage.n_fa_by_bus[bus],
                name=f"trust_region_abs_fa_neg_{bus}",
            )
        trust_region_constraints["local_branch_fa"] = model.addConstr(
            quicksum(fa_distance_vars) <= int(resolved_fa_radius),
            name="trust_region_local_branch_fa",
        )

    normal_blocks_by_scenario: dict[int, NormalOperationBlock] = {}
    if normal_recourse_active:
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
    if warm_start_alpha is not None:
        alpha_var.Start = max(float(instance.economics.alpha_min), float(warm_start_alpha))
    if warm_start_lambda_by_line_id is not None:
        invalid = sorted(
            str(line_id)
            for line_id in warm_start_lambda_by_line_id
            if str(line_id) not in set(ordered_line_ids)
        )
        if invalid:
            raise RuntimeDataValidationError(
                "warm_start_lambda_by_line_id contains invalid line ids: "
                f"{tuple(invalid)}."
            )
        for line_id, var in lambda_by_line_id.items():
            if line_id in warm_start_lambda_by_line_id:
                var.Start = max(0.0, float(warm_start_lambda_by_line_id[line_id]))

    s_by_cut_id: dict[str, object] = {}
    u_by_cut_id_and_line_id: dict[tuple[str, str], object] = {}
    eta_by_exact_row_id: dict[str, object] = {}
    theta_by_outage_column_id: dict[str, object] = {}
    cut_support_constraints: dict[str, object] = {}
    u_link_constraints: dict[tuple[str, str], object] = {}
    exact_row_epigraph_constraints: dict[str, object] = {}
    exact_row_support_constraints: dict[str, object] = {}
    outage_column_support_constraints: dict[str, object] = {}
    outage_column_cut_constraints: dict[str, object] = {}

    for cut in normalized_cuts:
        s_var = model.addVar(lb=0.0, name=_safe_gurobi_name("s_cut", cut.cut_id))
        s_by_cut_id[cut.cut_id] = s_var

        u_expr = quicksum(
            (
                u_by_cut_id_and_line_id.setdefault(
                    (cut.cut_id, line_id),
                    model.addVar(
                        lb=0.0,
                        name=_safe_gurobi_name("u_cut", f"{cut.cut_id}_{line_id}"),
                    ),
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
            name=_safe_gurobi_name("eq39_cut_support", cut.cut_id),
        )

        for line_id in ordered_line_ids:
            u_var = u_by_cut_id_and_line_id[(cut.cut_id, line_id)]
            u_link_constraints[(cut.cut_id, line_id)] = model.addConstr(
                u_var >= float(cut.phi_by_line_id[line_id]) - lambda_by_line_id[line_id] - s_var,
                name=_safe_gurobi_name("eq39_u_link", f"{cut.cut_id}_{line_id}"),
            )

    outage_column_patterns: dict[str, tuple[str, ...]] = {}
    for rowwise_cut in normalized_outage_column_cuts:
        outage_column_patterns.setdefault(
            rowwise_cut.column_id,
            rowwise_cut.active_line_ids,
        )
    for column_id, active_line_ids in outage_column_patterns.items():
        theta_var = model.addVar(lb=0.0, name=f"theta_outage_{column_id}")
        theta_by_outage_column_id[column_id] = theta_var
        outage_column_support_constraints[column_id] = model.addConstr(
            alpha_var + quicksum(lambda_by_line_id[line_id] for line_id in active_line_ids)
            >= theta_var,
            name=f"nccg_outage_support_{column_id}",
        )
    for rowwise_cut in normalized_outage_column_cuts:
        cut = rowwise_cut.cut
        theta_var = theta_by_outage_column_id[rowwise_cut.column_id]
        gamma_expr = quicksum(
            cut.gamma_z_by_bus[bus] * first_stage.z_by_bus[bus]
            + cut.gamma_n_sl_by_bus[bus] * first_stage.n_sl_by_bus[bus]
            + cut.gamma_n_fa_by_bus[bus] * first_stage.n_fa_by_bus[bus]
            for bus in ordered_buses
        )
        phi_delta = sum(
            float(cut.phi_by_line_id[line_id]) for line_id in rowwise_cut.active_line_ids
        )
        outage_column_cut_constraints[rowwise_cut.row_id] = model.addConstr(
            theta_var >= float(cut.beta) - gamma_expr + float(phi_delta),
            name=_safe_gurobi_name("nccg_rowwise_cut", rowwise_cut.row_id),
        )

    if normalized_exact_rows:
        cls_by_bus = _resolve_cls_by_bus(instance)
        topology = instance.network_topology
        line_by_id = {line.line_id: line for line in instance.lines}
        for exact_row in normalized_exact_rows:
            active_lines = set(exact_row.active_line_ids)
            eta_var = model.addVar(lb=0.0, name=f"eta_exact_{exact_row.row_id}")
            eta_by_exact_row_id[exact_row.row_id] = eta_var
            scenario_cost_expressions = []
            for scenario_id in selected_disaster_scenarios:
                load_shedding_vars = {
                    (ts, bus): model.addVar(
                        lb=0.0,
                        name=(
                            f"exact_{exact_row.row_id}_b{scenario_id}_"
                            f"yls_t{ts}_n{bus}"
                        ),
                    )
                    for ts in instance.sets.disaster_times
                    for bus in ordered_buses
                }
                discharge_slow_vars = {
                    (ts, region, bus): model.addVar(
                        lb=0.0,
                        name=(
                            f"exact_{exact_row.row_id}_b{scenario_id}_"
                            f"ydis_sl_t{ts}_o{region}_n{bus}"
                        ),
                    )
                    for ts in instance.sets.disaster_times
                    for region in instance.sets.regions
                    for bus in ordered_buses
                }
                discharge_fast_vars = {
                    (ts, region, bus): model.addVar(
                        lb=0.0,
                        name=(
                            f"exact_{exact_row.row_id}_b{scenario_id}_"
                            f"ydis_fa_t{ts}_o{region}_n{bus}"
                        ),
                    )
                    for ts in instance.sets.disaster_times
                    for region in instance.sets.regions
                    for bus in ordered_buses
                }
                line_flow_vars = {
                    (ts, line_id): model.addVar(
                        lb=-GRB.INFINITY,
                        name=(
                            f"exact_{exact_row.row_id}_b{scenario_id}_"
                            f"pdis_t{ts}_{line_id}"
                        ),
                    )
                    for ts in instance.sets.disaster_times
                    for line_id in ordered_line_ids
                }
                scenario_cost_expressions.append(
                    quicksum(
                        cls_by_bus[bus] * load_shedding_vars[(ts, bus)]
                        for ts in instance.sets.disaster_times
                        for bus in ordered_buses
                    )
                )
                for ts in instance.sets.disaster_times:
                    for line in instance.lines:
                        bus = line.to_bus
                        child_line_ids = tuple(
                            topology.line_by_child_bus[child]
                            for child in topology.children_by_bus.get(bus, ())
                        )
                        discharge_total = quicksum(
                            discharge_slow_vars[(ts, region, bus)]
                            + discharge_fast_vars[(ts, region, bus)]
                            for region in instance.sets.regions
                        )
                        model.addConstr(
                            line_flow_vars[(ts, line.line_id)]
                            == quicksum(
                                line_flow_vars[(ts, child_line_id)]
                                for child_line_id in child_line_ids
                            )
                            + instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
                            - load_shedding_vars[(ts, bus)]
                            - discharge_total,
                            name=(
                                f"exact_{exact_row.row_id}_b{scenario_id}_"
                                f"balance_t{ts}_{line.line_id}"
                            ),
                        )
                    for region in instance.sets.regions:
                        model.addConstr(
                            quicksum(
                                discharge_slow_vars[(ts, region, bus)]
                                for bus in ordered_buses
                            )
                            <= instance.disaster_tensors.dev_dis_sl[(scenario_id, ts, region)],
                            name=(
                                f"exact_{exact_row.row_id}_b{scenario_id}_"
                                f"slow_region_t{ts}_o{region}"
                            ),
                        )
                        model.addConstr(
                            quicksum(
                                discharge_fast_vars[(ts, region, bus)]
                                for bus in ordered_buses
                            )
                            <= instance.disaster_tensors.dev_dis_fa[(scenario_id, ts, region)],
                            name=(
                                f"exact_{exact_row.row_id}_b{scenario_id}_"
                                f"fast_region_t{ts}_o{region}"
                            ),
                        )
                    for bus in ordered_buses:
                        model.addConstr(
                            quicksum(
                                discharge_slow_vars[(ts, region, bus)]
                                for region in instance.sets.regions
                            )
                            <= first_stage.n_sl_by_bus[bus] * instance.ev.p_ev_rated_sl,
                            name=(
                                f"exact_{exact_row.row_id}_b{scenario_id}_"
                                f"slow_cap_t{ts}_n{bus}"
                            ),
                        )
                        model.addConstr(
                            quicksum(
                                discharge_fast_vars[(ts, region, bus)]
                                for region in instance.sets.regions
                            )
                            <= first_stage.n_fa_by_bus[bus] * instance.ev.p_ev_rated_fa,
                            name=(
                                f"exact_{exact_row.row_id}_b{scenario_id}_"
                                f"fast_cap_t{ts}_n{bus}"
                            ),
                        )
                        load = instance.disaster_tensors.p_load[(scenario_id, ts, bus)]
                        model.addConstr(
                            load_shedding_vars[(ts, bus)] <= load,
                            name=(
                                f"exact_{exact_row.row_id}_b{scenario_id}_"
                                f"shed_upper_t{ts}_n{bus}"
                            ),
                        )
                    for region in instance.sets.regions:
                        available_slow = instance.disaster_tensors.dev_dis_sl[
                            (scenario_id, ts, region)
                        ]
                        available_fast = instance.disaster_tensors.dev_dis_fa[
                            (scenario_id, ts, region)
                        ]
                        for bus in ordered_buses:
                            model.addConstr(
                                discharge_slow_vars[(ts, region, bus)]
                                <= available_slow * first_stage.z_by_bus[bus],
                                name=(
                                    f"exact_{exact_row.row_id}_b{scenario_id}_"
                                    f"slow_link_t{ts}_o{region}_n{bus}"
                                ),
                            )
                            model.addConstr(
                                discharge_fast_vars[(ts, region, bus)]
                                <= available_fast * first_stage.z_by_bus[bus],
                                name=(
                                    f"exact_{exact_row.row_id}_b{scenario_id}_"
                                    f"fast_link_t{ts}_o{region}_n{bus}"
                                ),
                            )
                    for line_id in ordered_line_ids:
                        available_capacity = line_by_id[line_id].p_max_kw * (
                            1 - int(line_id in active_lines)
                        )
                        model.addConstr(
                            line_flow_vars[(ts, line_id)] <= available_capacity,
                            name=(
                                f"exact_{exact_row.row_id}_b{scenario_id}_"
                                f"line_upper_t{ts}_{line_id}"
                            ),
                        )
                        model.addConstr(
                            line_flow_vars[(ts, line_id)] >= -available_capacity,
                            name=(
                                f"exact_{exact_row.row_id}_b{scenario_id}_"
                                f"line_lower_t{ts}_{line_id}"
                            ),
                        )
            exact_row_epigraph_constraints[exact_row.row_id] = model.addConstr(
                eta_var
                >= quicksum(scenario_cost_expressions) / len(selected_disaster_scenarios),
                name=f"exact_{exact_row.row_id}_eta_average",
            )
            exact_row_support_constraints[exact_row.row_id] = model.addConstr(
                alpha_var
                + quicksum(lambda_by_line_id[line_id] for line_id in exact_row.active_line_ids)
                >= eta_var,
                name=f"exact_{exact_row.row_id}_alpha_lambda_support",
            )

    normal_average_weight = (
        float((1.0 - instance.economics.pi_f) / len(selected_normal_scenarios))
        if normal_recourse_active
        else 0.0
    )
    construction_cost_expression = first_stage.construction_cost_expression
    averaged_normal_cost_expression = (
        normal_average_weight
        * quicksum(
            normal_blocks_by_scenario[scenario_id].total_normal_cost_expression
            for scenario_id in selected_normal_scenarios
        )
        if normal_recourse_active
        else 0.0
    )
    disaster_master_expression = float(instance.economics.pi_f) * (
        alpha_var
        + quicksum(
            fp_by_line_id[line_id] * lambda_by_line_id[line_id]
            for line_id in ordered_line_ids
        )
    )
    objective_multipliers = instance.economics.objective_multipliers
    total_objective_expression = (
        objective_multipliers.cons * construction_cost_expression
        + objective_multipliers.normal * averaged_normal_cost_expression
        + objective_multipliers.disaster * disaster_master_expression
    )
    objective_mode = "original"
    auxiliary_objective_expression = None
    auxiliary_level_constraint = None
    if level_bundle_center_plan is not None:
        if resolved_level_bound is not None:
            auxiliary_level_constraint = model.addConstr(
                total_objective_expression <= float(resolved_level_bound),
                name="level_bundle_original_objective_level",
            )
        distance_terms = []
        for bus in ordered_buses:
            if int(level_bundle_center_plan.z_by_bus[bus]) == 1:
                distance_terms.append(1 - first_stage.z_by_bus[bus])
            else:
                distance_terms.append(first_stage.z_by_bus[bus])

            sl_abs = model.addVar(lb=0.0, name=f"level_bundle_abs_sl_{bus}")
            fa_abs = model.addVar(lb=0.0, name=f"level_bundle_abs_fa_{bus}")
            center_sl = int(level_bundle_center_plan.n_sl_by_bus[bus])
            center_fa = int(level_bundle_center_plan.n_fa_by_bus[bus])
            model.addConstr(
                sl_abs >= first_stage.n_sl_by_bus[bus] - center_sl,
                name=f"level_bundle_abs_sl_pos_{bus}",
            )
            model.addConstr(
                sl_abs >= center_sl - first_stage.n_sl_by_bus[bus],
                name=f"level_bundle_abs_sl_neg_{bus}",
            )
            model.addConstr(
                fa_abs >= first_stage.n_fa_by_bus[bus] - center_fa,
                name=f"level_bundle_abs_fa_pos_{bus}",
            )
            model.addConstr(
                fa_abs >= center_fa - first_stage.n_fa_by_bus[bus],
                name=f"level_bundle_abs_fa_neg_{bus}",
            )
            sl_scale = max(
                1.0,
                float(instance.ev.nbar_sl_by_bus.get(bus, instance.ev.nbar_sl)),
            )
            fa_scale = max(
                1.0,
                float(instance.ev.nbar_fa_by_bus.get(bus, instance.ev.nbar_fa)),
            )
            distance_terms.append(float(level_bundle_rho_n) * sl_abs / sl_scale)
            distance_terms.append(float(level_bundle_rho_n) * fa_abs / fa_scale)

        alpha_pos = model.addVar(lb=0.0, name="level_bundle_abs_alpha_pos")
        alpha_neg = model.addVar(lb=0.0, name="level_bundle_abs_alpha_neg")
        model.addConstr(
            alpha_var - float(level_bundle_center_alpha) == alpha_pos - alpha_neg,
            name="level_bundle_abs_alpha_balance",
        )
        alpha_scale = 1.0 + abs(float(level_bundle_center_alpha))
        distance_terms.append(
            float(level_bundle_rho_alpha) * (alpha_pos + alpha_neg) / alpha_scale
        )
        for line_id in ordered_line_ids:
            lambda_pos = model.addVar(lb=0.0, name=f"level_bundle_abs_lambda_pos_{line_id}")
            lambda_neg = model.addVar(lb=0.0, name=f"level_bundle_abs_lambda_neg_{line_id}")
            center_value = float(level_bundle_center_lambda_by_line_id.get(line_id, 0.0))
            model.addConstr(
                lambda_by_line_id[line_id] - center_value == lambda_pos - lambda_neg,
                name=f"level_bundle_abs_lambda_balance_{line_id}",
            )
            lambda_scale = 1.0 + abs(center_value)
            distance_terms.append(
                float(level_bundle_rho_lambda) * (lambda_pos + lambda_neg) / lambda_scale
            )
        auxiliary_objective_expression = quicksum(distance_terms)
        objective_mode = "level_bundle_auxiliary"
        model.setObjective(auxiliary_objective_expression, sense=GRB.MINIMIZE)
    else:
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
        disaster_scenario_ids=selected_disaster_scenarios,
        cuts=normalized_cuts,
        exact_outage_rows=normalized_exact_rows,
        outage_column_cuts=normalized_outage_column_cuts,
        budget_k=budget_k,
        fp_by_line_id=fp_by_line_id,
        normal_average_weight=normal_average_weight,
        normal_recourse_active=normal_recourse_active,
        alpha_var=alpha_var,
        lambda_by_line_id=lambda_by_line_id,
        s_by_cut_id=s_by_cut_id,
        u_by_cut_id_and_line_id=u_by_cut_id_and_line_id,
        eta_by_exact_row_id=eta_by_exact_row_id,
        theta_by_outage_column_id=theta_by_outage_column_id,
        cut_support_constraints=cut_support_constraints,
        u_link_constraints=u_link_constraints,
        exact_row_epigraph_constraints=exact_row_epigraph_constraints,
        exact_row_support_constraints=exact_row_support_constraints,
        outage_column_support_constraints=outage_column_support_constraints,
        outage_column_cut_constraints=outage_column_cut_constraints,
        construction_cost_expression=construction_cost_expression,
        averaged_normal_cost_expression=averaged_normal_cost_expression,
        disaster_master_expression=disaster_master_expression,
        total_objective_expression=total_objective_expression,
        objective_mode=objective_mode,
        auxiliary_objective_expression=auxiliary_objective_expression,
        auxiliary_level_constraint=auxiliary_level_constraint,
        trust_region_center_plan=trust_region_center_plan,
        trust_region_z_radius=resolved_z_radius,
        trust_region_charger_sl_radius=resolved_sl_radius,
        trust_region_charger_fa_radius=resolved_fa_radius,
        trust_region_constraints=trust_region_constraints,
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
    elif status_code == GRB.TIME_LIMIT:
        status_name = "TIME_LIMIT"
    elif status_code == GRB.INFEASIBLE:
        status_name = "INFEASIBLE"
    elif status_code == GRB.UNBOUNDED:
        status_name = "UNBOUNDED"

    first_stage_solution = extract_first_stage_solution(master_problem.first_stage)
    normal_solutions_by_scenario = {
        scenario_id: extract_normal_operation_solution(normal_block)
        for scenario_id, normal_block in master_problem.normal_blocks_by_scenario.items()
    }
    has_solution = bool(status_code == GRB.OPTIMAL or int(getattr(model, "SolCount", 0)) > 0)
    if not has_solution:
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
            theta_by_outage_column_id={
                column_id: 0.0
                for column_id in master_problem.theta_by_outage_column_id
            },
            construction_cost_value=first_stage_solution.construction_cost_value,
            averaged_normal_cost_value=0.0,
            unweighted_average_normal_cost_value=0.0,
            normal_cost_by_scenario={},
            disaster_master_cost_value=0.0,
            lambda_fp_value=0.0,
            objective_reconstruction_gap=0.0,
            original_total_objective_value=None,
        )

    def nonnegative_solution_value(value: float, *, label: str, atol: float = 1.0e-5) -> float:
        numeric = float(value)
        if numeric < -atol:
            raise RuntimeDataValidationError(f"{label} must be nonnegative, got {numeric}.")
        return max(0.0, numeric)

    alpha_value = float(master_problem.alpha_var.X)
    lambda_values = {
        line_id: nonnegative_solution_value(var.X, label=f"lambda_by_line_id[{line_id!r}]")
        for line_id, var in master_problem.lambda_by_line_id.items()
    }
    s_values = {
        cut_id: nonnegative_solution_value(var.X, label=f"s_by_cut_id[{cut_id!r}]")
        for cut_id, var in master_problem.s_by_cut_id.items()
    }
    u_values = {
        key: nonnegative_solution_value(
            var.X,
            label=f"u_by_cut_id_and_line_id[{key!r}]",
        )
        for key, var in master_problem.u_by_cut_id_and_line_id.items()
    }
    theta_values = {
        column_id: nonnegative_solution_value(
            var.X,
            label=f"theta_by_outage_column_id[{column_id!r}]",
        )
        for column_id, var in master_problem.theta_by_outage_column_id.items()
    }
    normal_cost_by_scenario = {
        scenario_id: float(solution.normal_objective_value)
        for scenario_id, solution in normal_solutions_by_scenario.items()
    }
    construction_cost_value = float(first_stage_solution.construction_cost_value)
    unweighted_average_normal_cost_value = (
        float(sum(normal_cost_by_scenario.values()) / len(normal_cost_by_scenario))
        if normal_cost_by_scenario
        else 0.0
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
    objective_multipliers = master_problem.instance.economics.objective_multipliers
    reconstructed_objective = float(
        objective_multipliers.cons * construction_cost_value
        + objective_multipliers.normal * averaged_normal_cost_value
        + objective_multipliers.disaster * disaster_master_cost_value
    )
    objective_value = float(model.ObjVal)
    original_total_objective_value = (
        objective_value
        if master_problem.objective_mode == "original"
        else reconstructed_objective
    )

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
        theta_by_outage_column_id=theta_values,
        construction_cost_value=construction_cost_value,
        averaged_normal_cost_value=averaged_normal_cost_value,
        unweighted_average_normal_cost_value=unweighted_average_normal_cost_value,
        normal_cost_by_scenario=normal_cost_by_scenario,
        disaster_master_cost_value=disaster_master_cost_value,
        lambda_fp_value=lambda_fp_value,
        objective_reconstruction_gap=abs(
            float(original_total_objective_value) - reconstructed_objective
        ),
        original_total_objective_value=float(original_total_objective_value),
    )


def solve_master_problem(
    instance: CanonicalInstance,
    *,
    cuts: Sequence[RestrictedMasterCut] | None = None,
    normal_scenario_ids: Sequence[int] | None = None,
    disaster_scenario_ids: Sequence[int] | None = None,
    exact_outage_rows: Sequence[Sequence[str] | RestrictedMasterExactOutageRow] | None = None,
    outage_column_cuts: Sequence[RestrictedMasterOutageColumnCut] | None = None,
    warm_start_plan: FixedFirstStagePlan | None = None,
    warm_start_alpha: float | None = None,
    warm_start_lambda_by_line_id: Mapping[str, float] | None = None,
    trust_region_center_plan: FixedFirstStagePlan | None = None,
    trust_region_z_radius: int | None = None,
    trust_region_charger_sl_radius: int | None = None,
    trust_region_charger_fa_radius: int | None = None,
    level_bundle_center_plan: FixedFirstStagePlan | None = None,
    level_bundle_center_alpha: float | None = None,
    level_bundle_center_lambda_by_line_id: Mapping[str, float] | None = None,
    level_bundle_objective_upper_bound: float | None = None,
    level_bundle_rho_n: float = 0.2,
    level_bundle_rho_alpha: float = 0.05,
    level_bundle_rho_lambda: float = 1.0,
    time_limit_seconds: float | None = None,
    mip_gap: float | None = None,
    gurobi_params: Mapping[str, Any] | None = None,
    allow_suboptimal_incumbent: bool = False,
    model_name: str = "restricted_master_problem",
    log_to_console: bool = False,
) -> tuple[RestrictedMasterProblem, RestrictedMasterProblemSolution]:
    """Build, solve, and extract the fixed-cut restricted master problem."""

    master_problem = build_master_problem(
        instance,
        cuts=cuts,
        normal_scenario_ids=normal_scenario_ids,
        disaster_scenario_ids=disaster_scenario_ids,
        exact_outage_rows=exact_outage_rows,
        outage_column_cuts=outage_column_cuts,
        warm_start_plan=warm_start_plan,
        warm_start_alpha=warm_start_alpha,
        warm_start_lambda_by_line_id=warm_start_lambda_by_line_id,
        trust_region_center_plan=trust_region_center_plan,
        trust_region_z_radius=trust_region_z_radius,
        trust_region_charger_sl_radius=trust_region_charger_sl_radius,
        trust_region_charger_fa_radius=trust_region_charger_fa_radius,
        level_bundle_center_plan=level_bundle_center_plan,
        level_bundle_center_alpha=level_bundle_center_alpha,
        level_bundle_center_lambda_by_line_id=level_bundle_center_lambda_by_line_id,
        level_bundle_objective_upper_bound=level_bundle_objective_upper_bound,
        level_bundle_rho_n=level_bundle_rho_n,
        level_bundle_rho_alpha=level_bundle_rho_alpha,
        level_bundle_rho_lambda=level_bundle_rho_lambda,
        model_name=model_name,
        log_to_console=log_to_console,
    )
    if time_limit_seconds is not None:
        master_problem.model.Params.TimeLimit = float(time_limit_seconds)
    if mip_gap is not None:
        master_problem.model.Params.MIPGap = float(mip_gap)
    for key, value in dict(gurobi_params or {}).items():
        if value not in (None, ""):
            setattr(master_problem.model.Params, str(key), value)
    master_problem.model.optimize()
    solution = extract_master_problem_solution(master_problem)
    if solution.model_status != "OPTIMAL" and not (
        allow_suboptimal_incumbent and solution.objective_value is not None
    ):
        raise ValueError(
            "Restricted master problem did not reach OPTIMAL status: "
            f"{solution.model_status} (code {solution.raw_status_code})."
        )
    return master_problem, solution
