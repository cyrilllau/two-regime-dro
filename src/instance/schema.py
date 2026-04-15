"""Typed schema objects for the canonical instance layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RawInputSchema:
    """Location and header contract for runtime input files."""

    runtime_dir: str = "data/runtime_12"
    parameter_file: str = "parameters.json"
    normal_load_file: str = "normal_load_scenarios.csv"
    normal_slow_demand_file: str = "normal_ev_demand_slow.csv"
    normal_fast_demand_file: str = "normal_ev_demand_fast.csv"
    disaster_load_file: str = "disaster_load_scenarios.csv"
    disaster_slow_discharge_file: str = "disaster_ev_discharge_slow.csv"
    disaster_fast_discharge_file: str = "disaster_ev_discharge_fast.csv"
    legacy_loader_reference: str = "reference/legacy/m1_data_setup.py"
    critical_buses_source: str = "external_config_required"

    @classmethod
    def for_runtime_dir(cls, runtime_dir: str | Path) -> "RawInputSchema":
        """Create a schema bound to a specific runtime directory."""

        return cls(runtime_dir=str(Path(runtime_dir)))

    @property
    def runtime_path(self) -> Path:
        """Return the bound runtime directory as a ``Path``."""

        return Path(self.runtime_dir)

    @property
    def parameter_path(self) -> Path:
        """Return the runtime parameter JSON path."""

        return self.runtime_path / self.parameter_file

    def csv_paths(self) -> dict[str, Path]:
        """Return the runtime CSV file paths keyed by logical tensor name."""

        return {
            "normal_load": self.runtime_path / self.normal_load_file,
            "normal_slow": self.runtime_path / self.normal_slow_demand_file,
            "normal_fast": self.runtime_path / self.normal_fast_demand_file,
            "disaster_load": self.runtime_path / self.disaster_load_file,
            "disaster_slow": self.runtime_path / self.disaster_slow_discharge_file,
            "disaster_fast": self.runtime_path / self.disaster_fast_discharge_file,
        }


@dataclass(frozen=True)
class CanonicalSets:
    """Normalized set layer shared by reference and production code."""

    buses: tuple[int, ...]
    line_ids: tuple[str, ...]
    regions: tuple[int, ...]
    normal_times: tuple[int, ...]
    disaster_times: tuple[int, ...]
    declared_normal_scenarios: tuple[int, ...]
    declared_disaster_scenarios: tuple[int, ...]
    available_normal_scenarios: tuple[int, ...]
    available_disaster_scenarios: tuple[int, ...]
    loaded_normal_scenarios: tuple[int, ...]
    loaded_disaster_scenarios: tuple[int, ...]


@dataclass(frozen=True)
class LineData:
    """Canonical line record."""

    line_id: str
    from_bus: int
    to_bus: int
    resistance_pu: float
    reactance_pu: float
    p_max_kw: float
    q_max_kvar: float


@dataclass(frozen=True)
class NodeMeta:
    """Canonical node metadata derived from the frozen contract."""

    bus_id: int
    is_root: bool
    candidate_for_evcs: bool
    is_critical: bool | None = None


@dataclass(frozen=True)
class EconomicParameters:
    """Runtime economic parameters plus frozen cost semantics."""

    cfix: float
    ccons_sl: float
    ccons_fa: float
    ctrans: tuple[float, ...]
    cpur: tuple[float, ...]
    ccong: float
    gamma: float
    theta: int
    pi_f: float
    alpha_min: float
    cunmet: float
    annualize_normal_cost_by_365: bool
    annualize_disaster_cost_by_365: bool
    ctrans_mode: str
    power_unit: str


@dataclass(frozen=True)
class EVParameters:
    """Runtime EV and region-distance parameters."""

    p_ev_rated_sl: float
    p_ev_rated_fa: float
    distance_km: tuple[tuple[float, ...], ...]
    delta_t_hours: float
    nbar_sl: int
    nbar_fa: int


@dataclass(frozen=True)
class AmbiguityParameters:
    """Runtime ambiguity-set parameters with legacy-weight preservation."""

    k_max_outages: int
    p_bar: tuple[float, ...]
    legacy_w: tuple[float, ...]


@dataclass(frozen=True)
class NormalScenarioTensor:
    """Canonical dense normal-stage tensors."""

    support: tuple[int, ...]
    p_load: dict[tuple[int, int, int], float] = field(default_factory=dict)
    q_load: dict[tuple[int, int, int], float] = field(default_factory=dict)
    dev_ch_sl: dict[tuple[int, int, int], float] = field(default_factory=dict)
    dev_ch_fa: dict[tuple[int, int, int], float] = field(default_factory=dict)


@dataclass(frozen=True)
class DisasterScenarioTensor:
    """Canonical dense disaster-stage tensors."""

    support: tuple[int, ...]
    p_load: dict[tuple[int, int, int], float] = field(default_factory=dict)
    dev_dis_sl: dict[tuple[int, int, int], float] = field(default_factory=dict)
    dev_dis_fa: dict[tuple[int, int, int], float] = field(default_factory=dict)


@dataclass(frozen=True)
class RawRuntimeBundle:
    """Typed raw runtime material prior to canonicalization."""

    raw_parameters: dict[str, Any]
    csv_rows_by_file: dict[str, tuple[dict[str, str], ...]]
    csv_support_by_file: dict[str, tuple[int, ...]]
