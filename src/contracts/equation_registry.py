"""Equation-registry placeholders for linking paper equations to code modules."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EquationReference:
    """Metadata handle for an equation block named in the paper/spec."""

    equation_id: str
    owner_modules: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


def load_equation_registry() -> tuple[EquationReference, ...]:
    """Placeholder entry point reserved for a later registry round."""

    raise NotImplementedError(
        "Round 00 scaffold only: equation-registry materialization is not implemented yet."
    )
