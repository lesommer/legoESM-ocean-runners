# Project Status

This document tracks what's currently implemented and tested in the runners. Consult it before assuming any capability.

## Runner implementation status

Only `ocean_scm` mode has a working native run path (YAML → model object → output). The `3d_ocean_realistic` mode has a working run path for tripolar grids via script delegation to `run_omip_core2.py`. All other mode/grid combinations have working init but stub or untested run paths. Do not assume that calling `run_experiment run` on a 3D or coupled template will execute a simulation — check the table below.

| Mode | Init (YAML → config.yaml + tag) | Run (config.yaml → model → output) | Notes |
|------|----------------------------------|-------------------------------------|-------|
| `ocean_scm` | Working | **Working** | Constructs `OceanColumnModel`, runs, saves NetCDF. 5 templates tested end-to-end. |
| `3d_ocean` | Working | **Working for `dino`, `baroclinic_gyre`, `lock_exchange`, `overflow`, `acc_channel` (lat-lon)** | Two delegation lanes: `dino` → `runners/run_experiment.py::_run_dino` calls `scripts/run/run_dino.py` (upstream + patch `006`: `--n-devices` SPMD, `--restart-from`, `--seed`, `--timing-jsonl`; upstream PR climate-federation/legoESM#1926 pending); the other Tier-A cases → `_run_matrix_case` calls `scripts/matrix/run_ocean_test_matrix.py --only <case> --grid <grid>` (the upstream matrix runner owns the scientifically-validated case config; the runner forwards duration/dt/levels/resolution overrides). **Run-tested 2026-10-10** (`dino_e2e`, Mac CPU): full R1 grid (198×50, 36 lev, dt 2700), 8 steps finite, 154 SYPD, timing JSONL + snapshots written, `experiment.tag` records patch 006. **Tier-A run-tested 2026-10-10** (Mac CPU, all upstream gates PASS): baroclinic_gyre (latlon_regional 64x128, 1 d, 2/2 incl. the _cos variant), lock_exchange (latlon 64x64, 0.5 d, RPE 2.9e-9), overflow (latlon 64x64, 0.5 d, PE drift 2.2e-8), acc_channel (latlon_channel 64x128, 0.5 d). All other `3d_ocean` cases: stub (init + provenance only). |
| `3d_ocean_realistic` | Working | **Working for tripolar only** | Script delegation: calls `scripts/run/run_omip_core2.py` (upstream + patch `002` extensions) which reads eORCA1 mesh mask, loads WOCE ICs, applies CORE2 NYF forcing, supports `--scan-block` for `lax.scan`, `--convection enhanced_diffusion`, `--partial-cell`, `--synthetic-forcing`, `--forcing-scale`, `--days`. **MPI support** (patch `003`): when `mpi.enabled: true`, dispatches to `scripts/run/run_omip_core2_mpi.py` with latitude-band decomposition. Other grid types still stub. **2026-10-07 (pin `c986cb989`)**: patch 002 regenerated against the rewritten upstream script (same three flags); IC/SSS delegation flags remapped to the new upstream CLI (`--nemo-monthly-init`, `--sss-restore` + `--sss-restore-file` + `--sss-restore-tau-days`). **Delegation fixed + verified 2026-10-07**: upstream `build_tripole` now asserts `--mesh` resolves to the canonical repo-relative `data/grids/<file>` path, so the runner executes the delegated script with `cwd=<legoesm>` and passes the repo-rooted mesh (`<legoesm>/data/grids/<mesh_file>` — the mesh MUST exist there; a symlink into `data_root` is fine), and `--output` is absolutized against the experiment dir (relative output would relocate under the changed cwd). Mesh-resolution verified end-to-end (grid build + synthetic 5-day startup). **Run-tested 2026-10-07** (`macbook_2026-10-07_tripole-repin-5day`): 720 steps, no NaN, 2.85 s/step on M-series CPU (vs 3.9 s/step at the June pin) — delegation verified at this pin. **GPU-verified 2026-10-07** (`bigfoot_2026-10-08_tripole-gpu-smoke`, V100): exit 0, 1.17 steps/s (3.3× CPU), every diagnostic identical to the CPU run at print precision. **Caveats**: (1) at this pin `--sss-restore` implies loading NEMO siconc from an upstream-hardcoded path (`_SICONC_NC`) — unavailable off upstream's machine; disable via `physics.sss_restoring.enabled: false` until the Phase-3 env-override patch lands (the laptop's `orca1_data_repository/input_fields/` holds runoff/chl/domain_cfg locally — same repo upstream hardcodes). (2) **Delegation mapping completed 2026-10-07 (full 229-flag audit)**: `--tripole-vmix` ← `physics.vertical_mixing.scheme`, `--bottom-drag-{scheme,r,cd0,cdmax,z0,ke0}` ← `physics.bottom_drag` (template 'linear' → legacy), `--no-gm-redi` ← `physics.lateral_mixing.enabled: false` (upstream tripole ships GM/Redi **ON** κ=600 by default — the 2026-10-07 smokes therefore ran with GM active despite their `enabled: false` override; corrected by this mapping), `--runoff` ← `forcing.runoff.enabled` (the `_RUNOFF_NC` hardcode is fixed by patch `004-runoff-file-override.patch`; supply `--runoff-file` (and `--nemo-domain-cfg`) via the template/method in the `omip_faithful_card` section below — no longer blocked off upstream's machine). No upstream `--water-type` flag exists; Jerlov II is the upstream default and matches the template. Remaining unmapped upstream flags are grid-specific (`--cube-*`, `--fesom-*`, `--mpas-*`), and unenumerated physics/numerics families — card runs use the verbatim `run.extra_args` passthrough (see the card section). |
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
| `3d_idealized/` | `baroclinic_gyre` | yes | **yes** (2026-10-10, Mac CPU via matrix delegation: latlon_regional 64x128, 1 d, upstream drift gates 2/2 PASS incl. `baroclinic_gyre_cos`) |
| `3d_idealized/` | `lock_exchange` | yes | **yes** (2026-10-10, Mac CPU via matrix delegation: latlon 64x64, 0.5 d, RPE 2.9e-9 PASS) |
| `3d_idealized/` | `overflow` | yes | **yes** (2026-10-10, Mac CPU via matrix delegation: latlon 64x64, 0.5 d, PE drift 2.2e-8 PASS) |
| `3d_idealized/` | `eady_instability` | structurally validated only | no |
| `3d_idealized/` | `phillips_two_layer` | structurally validated only | no |
| `3d_idealized/` | `acc_channel` | yes | **yes** (2026-10-10, Mac CPU via matrix delegation: latlon_channel 64x128, 0.5 d, PASS) |
| `3d_idealized/` | `dino` | yes | **yes** (2026-10-10, `dino_e2e` Mac CPU: 198×50 R1, 8 steps, 154 SYPD; delegation via `run_dino.py` + patch 006; template rewritten to paper-faithful R1 defaults) |
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
| `global_ocean/` | `omip_faithful_card` | structurally validated only | no |
| `global_ocean/` | `omip_core2_thin` | yes | The FAST thin-card CORE-II tripole lane (legoESM job `8089905`, 2026-08-18: pure-defaults `run_omip_core2.py --years 4 --dt 600`, 20 lev, rest-state IC, ~9.5 SYPD on one RTX 8000). Mac CPU 0.5-day startup smoke at pin `c986cb989` (2026-10-09, synthetic forcing fallback): grid (332,362), rest-state, pure-defaults physics (A_h=1e5 mesh-derived, GM/Redi upstream-ON), 72 steps finite at 1.90 steps/s. Real `_MOD` forcing resolves on machines with the staged cache (jean-zay). `initial_conditions.type: rest` = no IC flags (documented lane; `ic.type` values woce/woa map to flags, anything else is left alone) |

## Definitions

- **Structurally validated** — `validate_templates.py --skip-imports` passes: the YAML has required sections (`experiment`, `grid`, `time`), a valid mode, a valid grid type, and `requires` references match entries in `data_catalog.yaml`. No legoESM code is exercised.
- **Init tested** — `init_experiment()` successfully loads the template, applies overrides, writes `config.yaml`, `experiment.tag`, and `run.sh`.
- **Run tested** — the runner executed the experiment and produced output (NetCDF, diagnostics JSON, etc.).

## Current 3D / coupled workflow

For `3d_ocean`, the runner has two delegation lanes:

- **`dino`** (lat-lon): `_run_dino` in `runners/run_experiment.py` delegates to `scripts/run/run_dino.py`. The upstream script is the standalone DINO production driver — it builds the paper-faithful R1 `DINOConfig` itself (Kamm et al. 2025 defaults: KPP + Visbeck GM/Redi + EVD convection, Wright EOS, zstar 36 lev, dt 2700), so the runner forwards only legitimate overrides (resolution `grid.n_lon`, duration, snapshot cadence, scheme flags, recipe cards via `run.extra_args`) plus the patch-006 lanes: `run.n_devices` (lat-band SPMD; `n_lat % N == 0` — the R1 grid's 198 rows divide by 1 and 2 only), `run.restart_from` (snapshot NPZ; clock restarts at 0), `run.seed` (ensemble IC; 0 = canonical), `run.timing_jsonl`. Restart is verified bit-exact on CPU; SPMD parity within the re-association floor. Patch 006 is scheduled for removal once upstream PR climate-federation/legoESM#1926 merges and the pin is bumped.
- **Tier-A idealized cases** (`baroclinic_gyre`, `lock_exchange`, `overflow`, `acc_channel`; lat-lon grids): `_run_matrix_case` delegates to `scripts/matrix/run_ocean_test_matrix.py --only <case> --grid <grid>`. The upstream matrix runner owns the scientifically-validated configuration (grid geometry, ICs, physics, stability-verified dt/duration pairs — see legoESM `docs/dev-notes/ocean_experiments_reference.md`); the runner forwards only duration/dt/levels/resolution overrides. Template physics fields are the documented intent; the upstream baseline is what runs. NB: upstream `--only` is a substring match — `baroclinic_gyre` also runs the `baroclinic_gyre_cos` variant (extra runtime, both gated).

For `3d_ocean_realistic` on tripolar grids, the runner delegates to `scripts/run/run_omip_core2.py` (upstream in legoESM, extended by patch `002-omip-core2-extensions.patch`). The upstream script provides `build_tripole()` for eORCA1 mesh mask reading, `load_core2_nyf()` for CORE-II Normal Year Forcing, `--scan-block` for `lax.scan` stepping, `--convection enhanced_diffusion`, and `--partial-cell` for partial bottom cells. Patch 002 (regenerated against the rewritten upstream script at pin `c986cb989`) adds: `--synthetic-forcing` (explicit opt-in smoke tests without real Zarr data), `--forcing-scale` (amplitude multiplier), `--days` (short experiments). Since the upstream CLI changed at this pin, the delegation maps WOCE ICs to `--nemo-monthly-init <temp> <salt>` and SSS restoring to `--sss-restore --sss-restore-file <clim> --sss-restore-tau-days <tau>`.

For all other 3D/coupled modes, experiments are executed by calling legoESM's own Python scripts directly (e.g., `legoESM/scripts/run/run_omip.py`). The runners still handle init and provenance tagging for these modes — the generated `config.yaml` and `experiment.tag` are valid even though `run_experiment run` does not execute a simulation.

## The NEMO-faithful card (template `global_ocean/omip_faithful_card`)

Added 2026-10-08. The template encodes the *standard NEMO-faithful 1° card* declared in legoESM `scripts/cluster/omip_nemo/run_standard_faithful_1deg.sbatch` (validated `nemolev_trp_long180` configuration, see legoESM `docs/dev-notes/OMIP_faithful.md`): TKE (NEMO Dirichlet surface BC, `nn_mxl=3`, prognostic, veros_sqrte κ convention), prognostic sea ice (free-drift, `--ice-init` SI3 NC), MLE, iwm, dm2dc, ISF 'spe' melt + Dai-Trenberth runoff (`--runoff-depth-nemo-ini`, river-mouth gate), SSS restoring (τ=45.5 d, ±4 mm/d cap, NEMO ice gate), RGB-chl SW, geothermal, bbl-adv, smc03 PGF, smag sched, momentum-RK3.

Delegation additions at this pin:
- **Verbatim passthrough**: `run.extra_args` (list) from the template is appended after all mapped args with only the `{data_root}` token substituted — machine-portable, recorded verbatim in `config.yaml` + `experiment.tag`.
- **`time.duration_overshoot_days`** (default 0.0): adds the standard card's +0.05 d overshoot to `--years`/`--days` (the driver skips the cadence snapshot at the exact final step, so the advertised day-N snapshot only lands as a normal cadence write).
- **`output.snapshot_every_days` / `output.diag_every_days`** mapped to the upstream cadence flags.
- **Patch `004-runoff-file-override.patch`** adds upstream `--runoff-file` (fixes the `_RUNOFF_NC` /burg hardcode; the `--isf`/`--runoff` double-count check follows the effective source). Remaining card path needs are satisfied by explicit flags: `--nemo-vertical-file`/`--nemo-domain-cfg` (domain_cfg.nc), `--chl-file` (RGB chl; card default `_CHL_NC` — override staged), `--siconc-file` (RUN_REF icemod, staged), `--iwm-forcing-file`, `--isf-forcing-file`, `--ice-init`, `--woa-t/--woa-s`, `--runoff-file`.

Data staging note (card): the corrected CORE-II `_MOD` zarr is NOT under `data_root` — it resolves via `core2_nyf_cache_dir()` = `$LEGOESM_CACHE_DIR` (or `~/.cache/legoesm/ocean_fidelity/`) sibling `core2_nyf_mod/nyf.zarr`; set `LEGOESM_CACHE_DIR` for the data_root staging on the target machine.

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
