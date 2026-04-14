"""Repository layout smoke tests for Round 00."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_PACKAGE_DIRS = (
    "src",
    "src/instance",
    "src/contracts",
    "src/reference",
    "src/production",
    "src/audit",
    "tests",
    "tests/unit",
    "tests/integration",
    "tests/fixtures",
)

EXPECTED_MODULE_FILES = (
    "src/__init__.py",
    "src/instance/schema.py",
    "src/instance/canonical_instance.py",
    "src/instance/validators.py",
    "src/instance/indexer.py",
    "src/instance/network_topology.py",
    "src/contracts/freeze.py",
    "src/contracts/equation_registry.py",
    "src/contracts/naming.py",
    "src/reference/disaster_primal_ref.py",
    "src/reference/lp_canonicalizer.py",
    "src/reference/disaster_dual_auto.py",
    "src/reference/kkt_checks.py",
    "src/reference/outage_enumerator.py",
    "src/reference/dro_outer_lp_oracle.py",
    "src/production/first_stage.py",
    "src/production/normal_block.py",
    "src/production/disaster_dual_paper.py",
    "src/production/separation_milp.py",
    "src/production/cut_factory.py",
    "src/production/master_problem.py",
    "src/production/benders_engine.py",
    "src/audit/model_dump.py",
    "src/audit/residual_report.py",
    "src/audit/cut_audit.py",
    "src/audit/iteration_log.py",
)

EXPECTED_SPEC_FILES = (
    "docs/spec/00_freeze_contract.md",
    "docs/spec/01_architecture.md",
    "docs/spec/02_equation_registry.md",
    "docs/spec/03_data_contract.md",
    "docs/spec/04_test_strategy.md",
    "docs/spec/05_round_protocol.md",
)


def test_expected_directories_exist() -> None:
    """The bootstrap round should create the planned package/test tree."""

    missing = [path for path in EXPECTED_PACKAGE_DIRS if not (REPO_ROOT / path).is_dir()]
    assert not missing, f"Missing expected directories: {missing}"


def test_expected_files_exist() -> None:
    """Bootstrap should supply stub modules plus the frozen spec files."""

    expected_files = EXPECTED_MODULE_FILES + EXPECTED_SPEC_FILES
    missing = [path for path in expected_files if not (REPO_ROOT / path).is_file()]
    assert not missing, f"Missing expected files: {missing}"
