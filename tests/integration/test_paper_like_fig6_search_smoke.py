"""Smoke coverage for the recorded paper-like Fig. 6 exact search."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def test_paper_like_fig6_search_smoke_produces_outputs(tmp_path: Path) -> None:
    manifest_path = tmp_path / "search.yaml"
    manifest_path.write_text(
        """
critical_buses_config: configs/critical_buses_paper_fig2.yaml
output_root: results/paper_like_calibration_search_smoke
report_path: docs/analysis_packs/paper_like_fig6_search_smoke.md
family_name: paper_like_fig6_search_smoke

base_run:
  runtime_source: data/runtime_12
  selection:
    scenarios_a: [1]
    scenarios_b: [1]
  mode: normal_only
  solver: direct_master
  parameter_regime: paper_like_fig6_search_smoke
  parameter_overrides:
    economics:
      cfix: 614400.0
      ccons_sl: 2700.35
      ccons_fa: 12000.0
      ctrans_scalar: 0.032625
      gamma: 0.01
      theta: 20
      pi_f: 0.3
    ev:
      p_ev_rated_sl: 7.0
      p_ev_rated_fa: 50.0
      nbar_sl: 25
      nbar_fa: 10

phase1_grid:
  ev_penetration_scale: [0.46, 0.50]
  nbar_sl: [20, 25]

phase2_grid:
  ccons_fa: [6000.0, 12000.0]

phase1_top_k: 2

target_semantics:
  run_id: paper_case1_target_semantics
  target_opened_bus_count: 7
  target_total_slow_chargers: 74
  target_total_fast_chargers: 13
  target_sites:
    - bus: 3
      n_sl: 22
      n_fa: 1
    - bus: 5
      n_sl: 3
      n_fa: 0
    - bus: 22
      n_sl: 1
      n_fa: 2
    - bus: 10
      n_sl: 0
      n_fa: 3
    - bus: 28
      n_sl: 21
      n_fa: 4
    - bus: 32
      n_sl: 24
      n_fa: 3
    - bus: 33
      n_sl: 3
      n_fa: 0
""",
        encoding="utf-8",
    )

    command = [
        sys.executable,
        "scripts/run_paper_like_fig6_search.py",
        "--config",
        str(manifest_path),
        "--skip-figures",
    ]
    subprocess.run(command, check=True, cwd=Path.cwd())

    output_root = Path("results/paper_like_calibration_search_smoke")
    assert (output_root / "search_results.csv").exists()
    assert (output_root / "metadata.json").exists()
    assert (output_root / "plans" / "paper_case1_target_semantics_plan.csv").exists()
    assert Path("docs/analysis_packs/paper_like_fig6_search_smoke.md").exists()
