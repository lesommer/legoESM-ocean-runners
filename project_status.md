# Project Status

This document tracks what's currently implemented and tested in the runners. Consult it before assuming any capability.

## Runner implementation status

Only `ocean_scm` mode has a working native run path (YAML → model object → output). The `3d_ocean_realistic` mode has a working run path for tripolar grids via script delegation to `run_omip_tripole.py`. All other mode/grid combinations have working init but stub or untested run paths. Do not assume that calling `run_experiment run` on a 3D or coupled template will execute a simulation — check the table below.

| Mode | Init (YAML → config.yaml + tag) | Run (config.yaml → model → output) | Notes |
|------|----------------------------------|-------------------------------------|-------|
| `ocean_scm` | Working | **Working** | Constructs `OceanColumnModel`, runs, saves NetCDF. 5 templates tested end-to-end. |
| `3d_ocean` | Working | **Stub** | Prints note to use `run_ocean_test_matrix.py` or legoESM scripts directly. No model object constructed. |
| `3d_ocean_realistic` | Working | **Working for tripolar only** | Script delegation: calls `run_omip_tripole.py` (patches `001` + `002`) which reads NEMO domain_cfg, WOCE ICs, applies CORE2 NYF via integrated forcing with Jerlov SW, SSS restoring, Dai-Trenberth runoff, writes NEMO-compatible grid_T/U/V output. **MPI support** (patch `003` + `004`): when `mpi.enabled: true` in config, dispatches to `run_omip_tripole_mpi.py` with latitude-band decomposition and tripolar-fold-aware halo exchange. **Caveat**: NEMO WOCE/EN4 ICs cause cold-start blowup at ~day 2 due to pressure gradient imbalance; use `--idealized-ic` for initial spinup. Other grid types still stub. |
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
| `global_ocean/` | `omip_tripole` | yes | 5-day run (CPU, idealized ICs, synthetic forcing); NEMO ICs blow up at ~day 2 |

## Definitions

- **Structurally validated** — `validate_templates.py --skip-imports` passes: the YAML has required sections (`experiment`, `grid`, `time`), a valid mode, a valid grid type, and `requires` references match entries in `data_catalog.yaml`. No legoESM code is exercised.
- **Init tested** — `init_experiment()` successfully loads the template, applies overrides, writes `config.yaml`, `experiment.tag`, and `run.sh`.
- **Run tested** — the runner executed the experiment and produced output (NetCDF, diagnostics JSON, etc.).

## Current 3D / coupled workflow

For `3d_ocean_realistic` on tripolar grids, the runner delegates to `run_omip_tripole.py` (delivered as patches `001-omip-tripole-script.patch` + `002-omip-tripole-physics.patch`). Patch 001 added the initial script with CORE2 NYF forcing. Patch 002 extends it with NEMO-identical Phase 0 configuration: reads `domain_cfg.nc` for grid + partial cells, loads WOCE/EN4 ICs, uses `compute_omip2_surface_forcing` for energetically consistent forcing with Jerlov shortwave penetration (water type II), applies SSS restoring from NEMO's `presalt` climatology, adds Dai-Trenberth runoff, and writes yearly NEMO-compatible grid_T/U/V NetCDF output via `NemoOutputWriter`. The integrated forcing approach (not operator-split `apply_omip2_surface_fluxes`) is used for energetic consistency and to enable Jerlov SW penetration. Patch 002 also adds `--idealized-ic` (exponentially stratified, hydrostatically balanced), `--forcing-scale` (amplitude multiplier for cold-start spinup), and `--no-gm-redi` (disable GM/Redi during spinup). **Known issue**: NEMO WOCE/EN4 ICs are not in hydrostatic balance on the legoESM grid and cause NaN blowup at ~day 2 regardless of timestep, forcing amplitude, or GM/Redi setting. Use `--idealized-ic` for initial spinup, then restart with NEMO ICs overlaid once the flow field has adjusted. Tidal mixing, sea ice, and TEOS-10 are deferred to later phases. The template exposes `fold_convention`, `smag_cfl_safety`, `adaptive_implicit_vertadv`, `water_type`, `sss_restoring.enabled`, and `runoff.enabled` as configurable fields.

For all other 3D/coupled modes, experiments are executed by calling legoESM's own Python scripts directly (e.g., `legoESM/scripts/run_omip.py`). The runners still handle init and provenance tagging for these modes — the generated `config.yaml` and `experiment.tag` are valid even though `run_experiment run` does not execute a simulation.

## MPI support for tripolar grids

Patches `003-tripolar-mpi-halo.patch` and `004-omip-tripole-mpi.patch` add multi-CPU MPI support for the `omip_tripole` template. When `mpi.enabled: true` is set in the config (via overrides), the runner dispatches to `run_omip_tripole_mpi.py` which uses latitude-band domain decomposition across MPI ranks. The northernmost rank handles the tripolar fold using `FoldDescriptor.perm_T`-based halo exchange instead of the regular 180° geographic pole-fold.

Patch `005-mpi-boundary-ops.patch` makes the barotropic solver and C-grid operators MPI-aware at partition boundaries: `min_cell_to_vface` and `fold_vface_row` use `pad_ns_zero` (MPI halo exchange) instead of zero-padding at non-fold boundaries; `_depth_average_to_faces` and `_h_total_at_faces` in the barotropic solver follow the same pattern. Also includes a NaN guard in `_apply_implicit_vertical_mixing` that replaces NaN values in K_v/A_v (from KPP/convection at partition boundaries) with background values — a temporary workaround until the physics schemes are made MPI-aware.

**To enable MPI**: set overrides `mpi.enabled=true` and `mpi.ranks=N` in your `run.yaml`:
```yaml
overrides:
  mpi.enabled: true
  mpi.ranks: 4
```

**Environment**: MPI runs require `mpi4py` and `mpi4jax` installed, plus an MPI launcher (`mpirun`/`mpiexec`). The runner automatically sets `OMP_NUM_THREADS=1`, `XLA_FLAGS=--xla_cpu_multi_thread_eigen=false`, and `JAX_PLATFORMS=cpu` when MPI is enabled.

**Validation status**: serial vs 2-rank MPI comparison on 0.5-day run with idealized ICs and synthetic forcing. 2-day MPI run verified stable with KPP + enhanced diffusion convection (NaN guard active).

**Known issues**: KPP vertical mixing and enhanced diffusion convection produce NaN in A_v/K_v at MPI partition boundaries. The NaN guard in patch 005 replaces these with background values, but this means the vertical mixing at boundary rows is not physically correct. A proper fix requires making KPP/convection MPI-aware (using halo data for boundary-adjacent columns).
