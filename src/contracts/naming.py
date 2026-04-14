"""Naming placeholders for equation-aware labels and audit artifacts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelLabel:
    """Structured label placeholder for future equation-tagged artifacts."""

    namespace: str
    name: str
