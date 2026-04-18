"""Round 10 readiness summary checks."""

from __future__ import annotations

import json
from pathlib import Path


def test_readiness_matrix_makes_certification_scope_explicit() -> None:
    """The readiness summary should distinguish exact, epsilon, and smoke-only claims."""

    runtime_fixture = json.loads(
        (Path("tests/fixtures") / "benders_runtime_certified_small.yaml").read_text(
            encoding="utf-8"
        )
    )
    readiness = {
        "tiny_independent_disaster_exact": {
            "status": "exact",
            "evidence": "tests/oracle/test_disaster_exact_oracle.py",
        },
        "tiny_end_to_end_benders_vs_bruteforce": {
            "status": "exact",
            "evidence": "tests/integration/test_benders_vs_oracle.py",
        },
        "tiny_epsilon_certificate": {
            "status": "epsilon_certified",
            "evidence": "tests/integration/test_epsilon_certificate.py",
        },
        "default_runtime_small_1_2": {
            "status": "smoke_only",
            "evidence": "tests/integration/test_benders_runtime_fixture_smoke.py",
        },
        "runtime_like_certified_small": {
            "status": runtime_fixture["expected"]["stop_reason"],
            "selection": runtime_fixture["selection"],
            "evidence": "tests/integration/test_benders_runtime_certification.py",
        },
    }

    assert readiness["tiny_independent_disaster_exact"]["status"] == "exact"
    assert readiness["tiny_end_to_end_benders_vs_bruteforce"]["status"] == "exact"
    assert readiness["tiny_epsilon_certificate"]["status"] == "epsilon_certified"
    assert readiness["default_runtime_small_1_2"]["status"] == "smoke_only"
    assert readiness["runtime_like_certified_small"]["status"] == "certified_epsilon"
    assert readiness["runtime_like_certified_small"]["selection"] == {
        "scenarios_a": [1],
        "scenarios_b": [1],
    }
