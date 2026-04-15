"""Manifest views that separate declared support from raw CSV availability."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.instance.raw_package import RawDataPackage
from src.instance.validators import (
    ValidationIssue,
    build_support_mismatch_issue,
    coerce_int_tuple,
    validate_csv_family_support,
)


@dataclass(frozen=True)
class StageSupportManifest:
    """Per-stage support manifest derived from JSON metadata and CSV content."""

    stage_name: str
    declared_support: tuple[int, ...]
    csv_support: tuple[int, ...]
    csv_support_by_file: dict[str, tuple[int, ...]] = field(default_factory=dict)
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def has_mismatch(self) -> bool:
        """Whether declared JSON support disagrees with CSV support."""

        return bool(self.issues)


@dataclass(frozen=True)
class RuntimeSupportManifest:
    """Complete runtime support manifest across both stages."""

    normal: StageSupportManifest
    disaster: StageSupportManifest
    json_declared_support_is_advisory: bool = True

    @property
    def issues(self) -> tuple[ValidationIssue, ...]:
        """Flattened manifest issues across both stages."""

        return self.normal.issues + self.disaster.issues

    def as_dict(self) -> dict[str, object]:
        """Return a JSON/report-friendly representation."""

        return {
            "policy": {
                "json_declared_support_is_advisory": self.json_declared_support_is_advisory,
                "csv_support_binds_runtime_selection": True,
            },
            "normal": {
                "declared_support": self.normal.declared_support,
                "csv_support": self.normal.csv_support,
                "csv_support_by_file": self.normal.csv_support_by_file,
                "issues": tuple(issue.message for issue in self.normal.issues),
            },
            "disaster": {
                "declared_support": self.disaster.declared_support,
                "csv_support": self.disaster.csv_support,
                "csv_support_by_file": self.disaster.csv_support_by_file,
                "issues": tuple(issue.message for issue in self.disaster.issues),
            },
        }


def _build_stage_manifest(
    *,
    stage_name: str,
    declared_support: tuple[int, ...],
    csv_support_by_file: dict[str, tuple[int, ...]],
) -> StageSupportManifest:
    csv_support = validate_csv_family_support(
        family_name=f"{stage_name} CSV family",
        support_by_file=csv_support_by_file,
    )
    mismatch = build_support_mismatch_issue(
        stage_name=f"{stage_name.capitalize()}-stage",
        declared_support=declared_support,
        csv_support=csv_support,
    )
    issues = () if mismatch is None else (mismatch,)
    return StageSupportManifest(
        stage_name=stage_name,
        declared_support=declared_support,
        csv_support=csv_support,
        csv_support_by_file=csv_support_by_file,
        issues=issues,
    )


def inspect_available_support(raw_package: RawDataPackage) -> RuntimeSupportManifest:
    """Inspect raw availability without deciding the runtime selection."""

    sets_raw = raw_package.raw_parameters["sets"]
    declared_normal = coerce_int_tuple(sets_raw["scenarios_a"], field_name="sets.scenarios_a")
    declared_disaster = coerce_int_tuple(sets_raw["scenarios_b"], field_name="sets.scenarios_b")

    normal_manifest = _build_stage_manifest(
        stage_name="normal",
        declared_support=declared_normal,
        csv_support_by_file={
            name: support
            for name, support in raw_package.csv_support_by_file.items()
            if name.startswith("normal_")
        },
    )
    disaster_manifest = _build_stage_manifest(
        stage_name="disaster",
        declared_support=declared_disaster,
        csv_support_by_file={
            name: support
            for name, support in raw_package.csv_support_by_file.items()
            if name.startswith("disaster_")
        },
    )
    return RuntimeSupportManifest(
        normal=normal_manifest,
        disaster=disaster_manifest,
        json_declared_support_is_advisory=True,
    )
