# Project Status

This document tracks what's currently implemented and tested in the runners. Consult it before assuming any capability.

## Runner implementation status

Only `ocean_scm` mode has a working native run path (YAML → model object → output). The `3d_ocean_realistic` mode has a working run path for tripolar grids via script delegation to `run_omip_core2.py`. All other mode/grid combinations have working init but stub or untested run paths. Do not assume that calling `run_experiment run` on a 3D or coupled template will execute a simulation — check the table below.

| Mode | Init (YAML → config.yaml + tag) | Run (config.yaml → model → output) | Notes |
|------|----------------------------------|-------------------------------------|-------|
| `ocean_scm` | Working | **Working** | Constructs `OceanColumnModel`, runs, saves NetCDF. 5 templates tested end-to-end. |
| `3d_ocean` | Working | **Stub** | Prints note to use `run_ocean_test_matrix.py` or legoESM scripts directly. No model object constructed. |
| `3d_ocean_realistic` | Working | **Working for tripolar only** | Script delegation: calls `scripts/run/run_omip_core2.py` (upstream + patch `002` extensions) which reads eORCA1 mesh mask, loads WOCE ICs, applies CORE2 NYF forcing, supports `--scan-block` for `lax.scan`, `--convection enhanced_diffusion`, `--partial-cell`, `--synthetic-forcing`, `--forcing-scale`, `--days`. **MPI support** (patch `003`): when `mpi.enabled: true`, dispatches to `scripts/run/run_omip_core2_mpi.py` with latitude-band decomposition. Other grid types still stub. **2026-10-07 (pin `c986cb989`)**: patch 002 regenerated against the rewritten upstream script (same three flags); IC/SSS delegation flags remapped to the new upstream CLI (`--nemo-monthly-init`, `--sss-restore` + `--sss-restore-file` + `--sss-restore-tau-days`) — templates/patches validate and the suite passes, but the delegation path is **not yet re-run-tested** at this pin. |
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
| `global_ocean/` | `omip_tripole` | yes | 5-day run tested at pin `69287951` (2026-06, synthetic forcing); delegation remapped for pin `c986cb989` — re-run pending |

## Definitions

- **Structurally validated** — `validate_templates.py --skip-imports` passes: the YAML has required sections (`experiment`, `grid`, `time`), a valid mode, a valid grid type, and `requires` references match entries in `data_catalog.yaml`. No legoESM code is exercised.
- **Init tested** — `init_experiment()` successfully loads the template, applies overrides, writes `config.yaml`, `experiment.tag`, and `run.sh`.
- **Run tested** — the runner executed the experiment and produced output (NetCDF, diagnostics JSON, etc.).

## Current 3D / coupled workflow

For `3d_ocean_realistic` on tripolar grids, the runner delegates to `scripts/run/run_omip_core2.py` (upstream in legoESM, extended by patch `002-omip-core2-extensions.patch`). The upstream script provides `build_tripole()` for eORCA1 mesh mask reading, `load_core2_nyf()` for CORE-II Normal Year Forcing, `--scan-block` for `lax.scan` stepping, `--convection enhanced_diffusion`, and `--partial-cell` for partial bottom cells. Patch 002 (regenerated against the rewritten upstream script at pin `c986cb989`) adds: `--synthetic-forcing` (explicit opt-in smoke tests without real Zarr data), `--forcing-scale` (amplitude multiplier), `--days` (short experiments). Since the upstream CLI changed at this pin, the delegation maps WOCE ICs to `--nemo-monthly-init <temp> <salt>` and SSS restoring to `--sss-restore --sss-restore-file <clim> --sss-restore-tau-days <tau>`.

For all other 3D/coupled modes, experiments are executed by calling legoESM's own Python scripts directly (e.g., `legoESM/scripts/run/run_omip.py`). The runners still handle init and provenance tagging for these modes — the generated `config.yaml` and `experiment.tag` are valid even though `run_experiment run` does not execute a simulation.

## MPI support for tripolar grids

Patch `003-omip-core2-mpi.patch` adds the MPI runner `scripts/run/run_omip_core2_mpi.py`. When `mpi.enabled: true` is set in the config (via overrides), the runner dispatches to this script which uses latitude-band domain decomposition across MPI ranks.

The upstream legoESM (PRs #357 and #358) now includes the MPI-correct boundary operators:
- `_fold_is_local(grid)` checks `fold.fold_j >= 0` instead of `fold.is_active`, ensuring consistent MPI call counts across all ranks
- `slice_cgrid_geometry_to_band` uses `fold_j=-1` sentinel on non-northernmost ranks (keeps `is_active=True` for consistency)
- `_interp_to_v_points` uses "pad-first-then-average" pattern for correct v-face interpolation at partition boundaries
- All meridional operators (`pad_ns_scalar`, `pad_ns_vector_v`, `gradient_y_cgrid`, `curl_vertex_cgrid`, etc.) use `pad_ns_zero` first, then override the fold row only on the fold-local rank

These fixes eliminated the `MPI_ERR_TRUNCATE` bug (np>=2) and the NaN blowup at partition boundaries (np>=4) that were present before PRs #357/#358.

**To enable MPI**: set overrides `mpi.enabled=true` and `mpi.ranks=N` in your `run.yaml`:
```yaml
overrides:
  mpi.enabled: true
  mpi.ranks: 4
```

**Environment**: MPI runs require `mpi4py` and `mpi4jax` installed, plus an MPI launcher (`mpirun`/`mpiexec`). The runner automatically sets `OMP_NUM_THREADS=1`, `XLA_FLAGS=--xla_cpu_multi_thread_eigen=false`, and `JAX_PLATFORMS=cpu` when MPI is enabled. legoESM must be installed via `uv sync` or `pip install -e .` in the legoESM checkout.

**Known issues**: `--scan-block` is not yet supported in MPI mode.

## Installation (federation refactor)

legoESM uses a uv workspace federation layout (`packages/core/`, `packages/ocean/`, etc.). Import paths are unchanged (`legoesm.ocean.dynamics.*` still works via PEP-420 namespace), but the source files are no longer under `src/legoesm/`. The runners no longer set `PYTHONPATH=$LEGOESM_DIR/src` — instead, legoESM must be installed:

```bash
cd ../legoESM && uv sync
# or: pip install -e ".[dev]"
```
