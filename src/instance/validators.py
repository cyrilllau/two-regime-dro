"""Explicit fail-fast validation helpers for the canonical instance layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:
    from src.instance.canonical_instance import CanonicalInstance


class ValidationError(ValueError):
    """Base class for instance-layer validation failures."""


class ConfigurationValidationError(ValidationError):
    """Raised for malformed frozen/runtime configuration."""


class RuntimeDataValidationError(ValidationError):
    """Raised for runtime JSON/CSV/topology contract violations."""


@dataclass(frozen=True)
class ValidationIssue:
    """Structured validation finding."""

    code: str
    message: str


def coerce_int_tuple(
    raw: Any,
    *,
    field_name: str,
    allow_empty: bool = False,
) -> tuple[int, ...]:
    """Normalize a runtime field into a stable int tuple."""

    if not isinstance(raw, list):
        raise RuntimeDataValidationError(f"{field_name} must be a list of ints.")
    if not raw and not allow_empty:
        raise RuntimeDataValidationError(f"{field_name} must be a non-empty list of ints.")

    values: list[int] = []
    for item in raw:
        if not isinstance(item, int) or isinstance(item, bool):
            raise RuntimeDataValidationError(
                f"{field_name} must contain only ints, got {item!r}."
            )
        values.append(int(item))
    return tuple(values)


def validate_line_parameter_lengths(
    *,
    line_count: int,
    rline: Sequence[float],
    xline: Sequence[float],
    pmax: Sequence[float],
    qmax: Sequence[float],
    p_bar: Sequence[float],
) -> None:
    """Validate linewise vector lengths against the topology size."""

    checks = {
        "net.Rline": len(rline),
        "net.Xline": len(xline),
        "net.Pmax": len(pmax),
        "net.Qmax": len(qmax),
        "ambig.p_bar": len(p_bar),
    }
    mismatches = [
        f"{name} has length {actual}, expected {line_count}"
        for name, actual in checks.items()
        if actual != line_count
    ]
    if mismatches:
        raise RuntimeDataValidationError("Line-parameter length mismatch: " + "; ".join(mismatches))


def validate_distance_matrix_shape(
    distance_matrix: Sequence[Sequence[float]],
    *,
    region_count: int,
    bus_count: int,
) -> None:
    """Validate the distance-matrix shape from runtime parameters."""

    if len(distance_matrix) != region_count:
        raise RuntimeDataValidationError(
            f"Distance matrix row count mismatch: expected {region_count}, got {len(distance_matrix)}."
        )
    bad_rows = [
        index + 1
        for index, row in enumerate(distance_matrix)
        if len(row) != bus_count
    ]
    if bad_rows:
        raise RuntimeDataValidationError(
            "Distance matrix column mismatch for region rows "
            f"{tuple(bad_rows)}: expected {bus_count} entries per row."
        )


def validate_csv_family_support(
    *,
    family_name: str,
    support_by_file: Mapping[str, tuple[int, ...]],
) -> tuple[int, ...]:
    """Validate that all CSV files in a tensor family expose the same support."""

    unique_supports = {support for support in support_by_file.values()}
    if not unique_supports:
        raise RuntimeDataValidationError(f"{family_name} support discovery produced no CSV files.")
    if len(unique_supports) != 1:
        details = ", ".join(f"{name}={support}" for name, support in support_by_file.items())
        raise RuntimeDataValidationError(
            f"{family_name} CSV files disagree on scenario support: {details}."
        )
    support = next(iter(unique_supports))
    if not support:
        raise RuntimeDataValidationError(f"{family_name} CSV support is empty.")
    return support


def build_support_mismatch_issue(
    *,
    stage_name: str,
    declared_support: tuple[int, ...],
    csv_support: tuple[int, ...],
) -> ValidationIssue | None:
    """Build a non-fatal manifest issue when JSON and CSV support disagree."""

    if declared_support == csv_support:
        return None
    return ValidationIssue(
        code=f"{stage_name.lower().replace('-', '_').replace(' ', '_')}_support_mismatch",
        message=(
            f"{stage_name} support declared in parameters.json is {declared_support}, "
            f"but live CSV support is {csv_support}."
        ),
    )


def validate_runtime_selection(
    *,
    stage_name: str,
    requested_selection: Sequence[int],
    csv_support: tuple[int, ...],
) -> tuple[int, ...]:
    """Validate that a runtime selection is explicit and satisfied by CSV support."""

    normalized = tuple(int(value) for value in requested_selection)
    if not normalized:
        raise RuntimeDataValidationError(
            f"{stage_name} runtime selection is empty."
        )
    if len(set(normalized)) != len(normalized):
        raise RuntimeDataValidationError(
            f"{stage_name} runtime selection contains duplicate scenario ids: {normalized}."
        )

    available = set(csv_support)
    missing = tuple(sorted(scenario for scenario in normalized if scenario not in available))
    if missing:
        raise RuntimeDataValidationError(
            f"{stage_name} runtime selection {normalized} requests scenarios absent from CSV "
            f"support {csv_support}: {missing}."
        )
    return normalized


def validate_critical_buses(
    *,
    buses: Sequence[int],
    critical_buses: Sequence[int] | None,
    allow_missing: bool,
) -> tuple[int, ...] | None:
    """Validate explicit critical-bus input when it is provided."""

    if critical_buses is None:
        if allow_missing:
            return None
        raise RuntimeDataValidationError(
            "critical_buses is required for disaster-objective construction."
        )

    bus_set = set(buses)
    critical_tuple = tuple(int(bus) for bus in critical_buses)
    if len(set(critical_tuple)) != len(critical_tuple):
        raise RuntimeDataValidationError("critical_buses contains duplicate bus ids.")
    invalid = tuple(bus for bus in critical_tuple if bus not in bus_set)
    if invalid:
        raise RuntimeDataValidationError(
            f"critical_buses contains invalid bus ids outside the bus set: {invalid}."
        )
    return critical_tuple


def build_criticality_maps(
    *,
    buses: Sequence[int],
    critical_buses: Sequence[int] | None,
    cls_critical: float,
    cls_noncritical: float,
) -> tuple[dict[int, bool] | None, dict[int, float] | None]:
    """Build paper-level criticality maps only from explicit critical-bus input."""

    validated = validate_critical_buses(
        buses=buses,
        critical_buses=critical_buses,
        allow_missing=True,
    )
    if validated is None:
        return None, None
    critical_set = set(validated)
    is_critical = {bus: bus in critical_set for bus in buses}
    cls_by_bus = {
        bus: (cls_critical if bus in critical_set else cls_noncritical)
        for bus in buses
    }
    return is_critical, cls_by_bus


def require_explicit_critical_buses(
    *,
    buses: Sequence[int],
    critical_buses: Sequence[int] | None,
    legacy_w: Sequence[float] | None = None,
) -> tuple[int, ...]:
    """Require explicit critical buses before disaster-objective construction."""

    if critical_buses is None:
        detail = (
            " ambig.w is present but explicitly forbidden as a fallback."
            if legacy_w is not None
            else ""
        )
        raise RuntimeDataValidationError(
            "critical_buses is required for disaster-objective construction." + detail
        )

    validated = validate_critical_buses(
        buses=buses,
        critical_buses=critical_buses,
        allow_missing=False,
    )
    return validated


def validate_tensor_cardinality(
    *,
    tensor_name: str,
    actual_count: int,
    expected_count: int,
) -> None:
    """Validate a canonical dense tensor size."""

    if actual_count != expected_count:
        raise RuntimeDataValidationError(
            f"{tensor_name} has {actual_count} canonical entries, expected {expected_count}."
        )


def validate_canonical_instance(instance: "CanonicalInstance") -> tuple[ValidationIssue, ...]:
    """Collect non-disaster-objective canonical instance issues."""

    issues: list[ValidationIssue] = []
    if not instance.network_topology.is_radial:
        issues.append(
            ValidationIssue(
                code="topology_not_radial",
                message="NetworkTopology.is_radial is false.",
            )
        )
    if len(instance.index_map.buses) != len(instance.sets.buses):
        issues.append(
            ValidationIssue(
                code="bus_index_mismatch",
                message="IndexMap bus ordering does not match CanonicalSets.",
            )
        )
    return tuple(issues)


def assert_valid_canonical_instance(instance: "CanonicalInstance") -> None:
    """Raise on canonical instance issues collected by ``validate_canonical_instance``."""

    issues = validate_canonical_instance(instance)
    if issues:
        raise RuntimeDataValidationError("; ".join(issue.message for issue in issues))
