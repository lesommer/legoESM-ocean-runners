# Project Status

This document tracks what's currently implemented and tested in the runners. Consult it before assuming any capability.

## Runner implementation status

Only `ocean_scm` mode has a working native run path (YAML → model object → output). The `3d_ocean_realistic` mode has a working run path for tripolar grids via script delegation to `run_omip_tripole.py`. All other mode/grid combinations have working init but stub or untested run paths. Do not assume that calling `run_experiment run` on a 3D or coupled template will execute a simulation — check the table below.

| Mode | Init (YAML → config.yaml + tag) | Run (config.yaml → model → output) | Notes |
|------|----------------------------------|-------------------------------------|-------|
| `ocean_scm` | Working | **Working** | Constructs `OceanColumnModel`, runs, saves NetCDF. 5 templates tested end-to-end. |
| `3d_ocean` | Working | **Stub** | Prints note to use `run_ocean_test_matrix.py` or legoESM scripts directly. No model object constructed. |
| `3d_ocean_realistic` | Working | **Working for tripolar only** | Script delegation: calls `run_omip_tripole.py` (patches `001` + `002`) which reads NEMO domain_cfg, WOCE ICs, applies CORE2 NYF via integrated forcing with Jerlov SW, SSS restoring, Dai-Trenberth runoff, writes NEMO-compatible grid_T/U/V output. Other grid types still stub. |
| `barotropic_ocean` | Working | **Not implemented** | Raises `NotImplementedError`. |
| `coupled` | Working | **Partially implemented** | Constructs `CoupledESMDriver` but untested. |

## Template test status

| Category | Template | Init tested | Run tested |
|----------|----------|:-----------:|:----------:|
| `1d/` | `ocean_scm_convective` | yes | **yes** |
| `1d/` | `ocean_scm_ekman` | yes | **yes** |
| `1d/` | `ocean_scm_surface_heating` | yes | **yes** |
| `1d/` | `ocean_scm_kpp_wind` | yes | **yes** |
| `1d/` | `ocean_scm` | yes | **yes** |
| `2d/` | `barotropic_gyre` | structurally validated only | no |
| `2d/` | `stommel_gyre_tracer` | structurally validated only | no |
| `2d/` | `inertia_gravity_wave` | structurally validated only | no |
| `2d/` | `williamson_test2` | structurally validated only | no |
| `3d_idealized/` | `baroclinic_gyre` | structurally validated only | no |
| `3d_idealized/` | `lock_exchange` | structurally validated only | no |
| `3d_idealized/` | `overflow` | structurally validated only | no |
| `3d_idealized/` | `eady_instability` | structurally validated only | no |
| `3d_idealized/` | `phillips_two_layer` | structurally validated only | no |
| `3d_idealized/` | `acc_channel` | structurally validated only | no |
| `3d_idealized/` | `dino` | structurally validated only | no |
| `3d_idealized/` | `geostrophic_adjustment` | structurally validated only | no |
| `3d_idealized/` | `isomip_plus` | structurally validated only | no |
| `coupled/` | `coupled_aquaplanet` | structurally validated only | no |
| `coupled/` | `coupled_slab` | structurally validated only | no |
| `coupled/` | `coupled_full` | structurally validated only | no |
| `global_ocean/` | `omip_jra55` | structurally validated only | no |
| `global_ocean/` | `global_overturning` | structurally validated only | no |
| `global_ocean/` | `neverworld2_lite` | structurally validated only | no |
| `global_ocean/` | `omip_global` | structurally validated only | no |
| `global_ocean/` | `omip_cubed_sphere` | structurally validated only | no |
| `global_ocean/` | `omip_tripole` | yes | smoke tested (CPU, synthetic forcing) |

## Definitions

- **Structurally validated** — `validate_templates.py --skip-imports` passes: the YAML has required sections (`experiment`, `grid`, `time`), a valid mode, a valid grid type, and `requires` references match entries in `data_catalog.yaml`. No legoESM code is exercised.
- **Init tested** — `init_experiment()` successfully loads the template, applies overrides, writes `config.yaml`, `experiment.tag`, and `run.sh`.
- **Run tested** — the runner executed the experiment and produced output (NetCDF, diagnostics JSON, etc.).

## Current 3D / coupled workflow

For `3d_ocean_realistic` on tripolar grids, the runner delegates to `run_omip_tripole.py` (delivered as patches `001-omip-tripole-script.patch` + `002-omip-tripole-physics.patch`). Patch 001 added the initial script with CORE2 NYF forcing. Patch 002 extends it with NEMO-identical Phase 0 configuration: reads `domain_cfg.nc` for grid + partial cells, loads WOCE/EN4 ICs, uses `compute_omip2_surface_forcing` for energetically consistent forcing with Jerlov shortwave penetration (water type II), applies SSS restoring from NEMO's `presalt` climatology, adds Dai-Trenberth runoff, and writes yearly NEMO-compatible grid_T/U/V NetCDF output via `NemoOutputWriter`. The integrated forcing approach (not operator-split `apply_omip2_surface_fluxes`) is used for energetic consistency and to enable Jerlov SW penetration. Tidal mixing, sea ice, and TEOS-10 are deferred to later phases. The template exposes `fold_convention`, `smag_cfl_safety`, `adaptive_implicit_vertadv`, `water_type`, `sss_restoring.enabled`, and `runoff.enabled` as configurable fields.

For all other 3D/coupled modes, experiments are executed by calling legoESM's own Python scripts directly (e.g., `legoESM/scripts/run_omip.py`). The runners still handle init and provenance tagging for these modes — the generated `config.yaml` and `experiment.tag` are valid even though `run_experiment run` does not execute a simulation.
