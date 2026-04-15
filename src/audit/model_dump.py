"""Minimal LP dump helpers for the disaster primal reference round."""

from __future__ import annotations

from pathlib import Path


def dump_model_artifact(model_or_wrapper: object, path: str | Path) -> Path:
    """Write a Gurobi model artifact to disk and return the written path."""

    model = getattr(model_or_wrapper, "model", model_or_wrapper)
    if not hasattr(model, "write"):
        raise TypeError("dump_model_artifact expects a Gurobi model or wrapper with .model.")

    artifact_path = Path(path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    model.update()
    model.write(str(artifact_path))
    return artifact_path
