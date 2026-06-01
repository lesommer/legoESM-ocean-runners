# Project Status

This document tracks what's currently implemented and tested in the runners. Consult it before assuming any capability.

## Runner implementation status

Only `ocean_scm` mode has a working native run path (YAML → model object → output). The `3d_ocean_realistic` mode has a working run path for tripolar grids via script delegation to `run_omip_core2.py`. All other mode/grid combinations have working init but stub or untested run paths. Do not assume that calling `run_experiment run` on a 3D or coupled template will execute a simulation — check the table below.

| Mode | Init (YAML → config.yaml + tag) | Run (config.yaml → model → output) | Notes |
|------|----------------------------------|-------------------------------------|-------|
| `ocean_scm` | Working | **Working** | Constructs `OceanColumnModel`, runs, saves NetCDF. 5 templates tested end-to-end. |
| `3d_ocean` | Working | **Stub** | Prints note to use `run_ocean_test_matrix.py` or legoESM scripts directly. No model object constructed. |
| `3d_ocean_realistic` | Working | **Working for tripolar only** | Script delegation: calls `run_omip_core2.py` (upstream + patch `002` extensions) which reads eORCA1 mesh mask, loads WOCE/EN4 ICs, applies CORE2 NYF forcing, supports `--scan-block` for `lax.scan`, `--convection enhanced_diffusion`, `--partial-cell`, `--synthetic-forcing`, `--forcing-scale`, `--days`, `--ic-type {rest,woa,woce}`, `--sss-target`. **MPI support** (patches `003` + `004`): when `mpi.enabled: true`, dispatches to `run_omip_core2_mpi.py` with latitude-band decomposition and MPI-aware boundary operators. Other grid types still stub. |
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
| `global_ocean/` | `omip_tripole` | yes | 5-day run (CPU, rest ICs, synthetic forcing); WOCE ICs under testing |

## Definitions

- **Structurally validated** — `validate_templates.py --skip-imports` passes: the YAML has required sections (`experiment`, `grid`, `time`), a valid mode, a valid grid type, and `requires` references match entries in `data_catalog.yaml`. No legoESM code is exercised.
- **Init tested** — `init_experiment()` successfully loads the template, applies overrides, writes `config.yaml`, `experiment.tag`, and `run.sh`.
- **Run tested** — the runner executed the experiment and produced output (NetCDF, diagnostics JSON, etc.).

## Current 3D / coupled workflow

For `3d_ocean_realistic` on tripolar grids, the runner delegates to `run_omip_core2.py` (upstream in legoESM, extended by patch `002-omip-core2-extensions.patch`). The upstream script provides `build_tripole()` for eORCA1 mesh mask reading, `load_core2_nyf()` for CORE-II Normal Year Forcing, `--scan-block` for `lax.scan` stepping, `--convection enhanced_diffusion`, and `--partial-cell` for partial bottom cells. Patch 002 adds: `--synthetic-forcing` (smoke tests without real Zarr data), `--forcing-scale` (amplitude multiplier), `--days` (short experiments), `--ic-type {rest,woa,woce}` (initial conditions selection), and `--sss-target` (salinity restoring from climatology). The template now uses `--mesh` (eORCA1.2 mesh mask) instead of `--domain-cfg`, and defaults to `--ic-type woce` with WOCE/EN4 v4.2 initial conditions.

For all other 3D/coupled modes, experiments are executed by calling legoESM's own Python scripts directly (e.g., `legoESM/scripts/run_omip.py`). The runners still handle init and provenance tagging for these modes — the generated `config.yaml` and `experiment.tag` are valid even though `run_experiment run` does not execute a simulation.

## MPI support for tripolar grids

Patches `003-mpi-boundary-ops.patch` and `004-omip-core2-mpi.patch` add multi-CPU MPI support for the `omip_tripole` template. When `mpi.enabled: true` is set in the config (via overrides), the runner dispatches to `run_omip_core2_mpi.py` which uses latitude-band domain decomposition across MPI ranks.

**Patch 003** makes the C-grid boundary operators and barotropic solver MPI-aware at partition boundaries:
- Adds `_fold_is_local(fold)` helper that checks `fold.fold_j >= 0` instead of `fold.is_active` (which is True on all ranks for consistent MPI call counts)
- Updates `pad_ns_scalar`, `pad_ns_vector_u/v`, `pad_ns_vector_pair`, `min_cell_to_vface`, `fold_vface_row` in `latlon_cgrid_operators.py` to use `pad_ns_zero` (MPI halo exchange) first, then override the north row with fold data only on the fold-local rank
- Updates `_depth_average_to_faces` and `_h_total_at_faces` in `barotropic_implicit_latlon_cgrid.py` with the same pattern
- Adds NaN guard in `_apply_implicit_vertical_mixing` that replaces NaN in K_v/A_v with background values

**Patch 004** adds `scripts/run_omip_core2_mpi.py` which imports `build_tripole` and forcing functions from the patched `run_omip_core2.py`, uses `initialize_distributed_latlon` for MPI setup, `scatter_state_latlon_cgrid_ocean`/`gather_state_latlon_cgrid_ocean` for state distribution, and `slice_cgrid_geometry_to_band`/`slice_zcoord_to_band` for per-rank grid slicing.

**To enable MPI**: set overrides `mpi.enabled=true` and `mpi.ranks=N` in your `run.yaml`:
```yaml
overrides:
  mpi.enabled: true
  mpi.ranks: 4
```

**Environment**: MPI runs require `mpi4py` and `mpi4jax` installed, plus an MPI launcher (`mpirun`/`mpiexec`). The runner automatically sets `OMP_NUM_THREADS=1`, `XLA_FLAGS=--xla_cpu_multi_thread_eigen=false`, and `JAX_PLATFORMS=cpu` when MPI is enabled.

**Known issues**: KPP vertical mixing and enhanced diffusion convection produce NaN in A_v/K_v at MPI partition boundaries. The NaN guard in patch 003 replaces these with background values, but this means the vertical mixing at boundary rows is not physically correct. A proper fix requires making KPP/convection MPI-aware (using halo data for boundary-adjacent columns). `--scan-block` is not yet supported in MPI mode.
