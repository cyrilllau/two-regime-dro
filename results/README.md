# Local Experiment Results

`results/` is a local generated-output area. It is ignored by Git except for
this README.

Keep large or reproducible artifacts here, including solver logs, cut pools,
diagnostic runs, generated figures, local archives, and Pro context packs. Move
only small paper-facing assets that are required to compile the manuscript into
`docs/analysis_packs/assets/`.

Current top-level convention:

- `paper_final/`: latest generated paper pack, ignored by Git.
- `engineering_acceleration/`: local algorithm probes and scalability traces.
- `ev_sensitivity_current_default_ev2p0/` and `ev_sensitivity_current_default_ev3p0/`: current sensitivity run outputs.
- `reproduce_default_0p0152_1p4*/`: locked default reproduction outputs.
- `archive/local_legacy_YYYYMMDD/`: historical diagnostics and superseded runs.
