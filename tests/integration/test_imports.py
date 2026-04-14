"""Import smoke tests for the Round 00 scaffold."""

from __future__ import annotations

import importlib

import pytest


MODULE_NAMES = (
    "src",
    "src.instance",
    "src.instance.schema",
    "src.instance.canonical_instance",
    "src.instance.validators",
    "src.instance.indexer",
    "src.instance.network_topology",
    "src.contracts",
    "src.contracts.freeze",
    "src.contracts.equation_registry",
    "src.contracts.naming",
    "src.reference",
    "src.reference.disaster_primal_ref",
    "src.reference.lp_canonicalizer",
    "src.reference.disaster_dual_auto",
    "src.reference.kkt_checks",
    "src.reference.outage_enumerator",
    "src.reference.dro_outer_lp_oracle",
    "src.production",
    "src.production.first_stage",
    "src.production.normal_block",
    "src.production.disaster_dual_paper",
    "src.production.separation_milp",
    "src.production.cut_factory",
    "src.production.master_problem",
    "src.production.benders_engine",
    "src.audit",
    "src.audit.model_dump",
    "src.audit.residual_report",
    "src.audit.cut_audit",
    "src.audit.iteration_log",
)


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_module_imports(module_name: str) -> None:
    """Every scaffold module should be importable before future rounds add logic."""

    module = importlib.import_module(module_name)
    assert module.__name__ == module_name
