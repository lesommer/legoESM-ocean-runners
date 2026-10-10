# DINO experiments through the runners

[DINO](https://doi.org/10.5194/gmd-18-8091-2025) (DIabatic Neverworld Ocean;
Kamm, Deshayes & Madec 2025) is a pole-to-pole idealized Atlantic-sector basin
with a re-entrant ACC channel (45–65°S) — the standard testbed for subgrid
parameterizations (ACC, MOC, MHT, σ₂ stratification benchmarks).

This guide covers the `3d_idealized/dino` template: what runs, what maps
where, and the resolution / multi-GPU / restart / ensemble lanes.

## What the runner does

`run_experiment run` on a `dino` config delegates to legoESM's standalone
production driver `scripts/run/run_dino.py` (`_run_dino` in
`runners/run_experiment.py`). The upstream script **builds the
paper-faithful R1 `DINOConfig` itself** — KPP + Visbeck GM/Redi (triads) +
enhanced-diffusion convection, Wright EOS, zstar 36 levels, dt = 2700 s,
implicit-CN barotropic, analytic bathymetry/forcing. The runner therefore
forwards only legitimate overrides; it does not re-interpret DINO physics.

Template → CLI mapping:

| Template field | `run_dino.py` flag | Notes |
|---|---|---|
| `grid.n_lon` | `--n-lon` | 50 → 198-row Mercator = paper 1° R1 |
| `time.duration_days` | `--days` (+`--allow-multiyear` > 365) | upstream caps at 1 yr locally |
| `time.dt_seconds` | `--dt` | default 2700 forwarded only if changed |
| `output.snapshot_every_days` | `--snapshot-every-days` | |
| `ocean.vmix` | `--vmix` | kpp (paper), tke, constant, richardson, catke |
| `ocean.eos` | `--eos` | wright (default), nemo_seos (paper oracle) |
| `ocean.gm_kappa_scheme` | `--gm-kappa-scheme` | visbeck (default), treguier (NEMO nn_aei_ijk_t=21) |
| `ocean.bottom_drag_scheme` | `--bottom-drag-scheme` | legacy (default), nemo_quadratic, nemo_loglayer |
| `ocean.recipe` | `--recipe` | L1/L2 model-recipe cards (see upstream `--help`) |
| `grid.nemo_faithful` | `--nemo-faithful-grid` | NEMO's exact 52×199 mesh (oracle lane) |
| `physics.disabled` | `--physics-off` | dycore only |
| `forcing.disabled` | `--no-forcing` | no wind/restoring |
| `run.extra_args` | verbatim passthrough | `{data_root}` substituted; upstream flags recorded verbatim in `config.yaml` + `experiment.tag` |

## Resolution ladder (overrides, not new templates)

| Label | Override | n_lat | dt (s) |
|---|---|---|---|
| R1 (default) | — | 198 | 2700 |
| R2 | `-o grid.n_lon=100 -o time.dt_seconds=1350` | 396 | 1350 |
| R4 | `-o grid.n_lon=200 -o time.dt_seconds=675` | 794 | 675 |
| R8 | `-o grid.n_lon=400 -o time.dt_seconds=338` | 1590 | 338 |

## Multi-GPU (upstream PR climate-federation/legoESM#1926, merged)

```yaml
run:
  n_devices: 2        # lat-band SPMD (make_sharded_ocean_step)
```

Constraints:

- Lat-lon only; `n_lat % n_devices == 0` — the R1 grid's 198 rows divide by
  1 and 2 only; R2 (396) divides by 4. No exact DINO Mercator row count
  divides by 8; wider device counts belong on the synthetic-grid SPMD
  benches (`legoESM/scripts/bench/bench_ocean_latlon_spmd_scaling.py`).
- Global build runs on the host CPU when `n_devices > 1` — set
  `JAX_PLATFORMS=cuda,cpu` in the machine env so the CPU backend exists.
- Snapshots/diagnostics gather the global state (the sharded `v_lower`
  carrier never reaches disk).
- One process per GPU (SLURM/srun): append `--multicontroller
  --coordinator host:port` via `run.extra_args` (rank 0 is the sole writer).

Verified on CPU (2 virtual devices): SPMD parity vs the single-device run
within the floating-point re-association floor (eta 1.6e-5, T 1.9e-6 at 2
steps — under the `tests/parallel/test_latlon_ocean_spmd_step.py` gate).

## Restart

```yaml
run:
  restart_from: results/dino/snapshots/snapshot_00010.npz
```

Path is resolved against the experiment directory. The snapshot's
prognostic fields (eta/T/S/u/v) become the IC; **the clock restarts at 0**
(the snapshot's time metadata is recorded, not replayed). Same grid settings
required (`--n-lon` etc. must match the run that wrote the snapshot).

Verified **bit-exact**: a 2-step + 2-step restart equals the continuous
4-step run with max diff 0.0 on every field (fp64 CPU smoke).

## Ensemble / perturbed ICs

```yaml
run:
  seed: 7
```

`seed: 0` (default) is the canonical rest-state IC — byte-identical to the
unseeded run. `seed > 0` adds masked Gaussian noise (u/v σ = 0.02 m/s,
eta σ = 0.005 m; velocity noise projected through the face masks).

## Timing

```yaml
run:
  timing_jsonl: timing.jsonl    # relative to experiment dir
```

The run appends one JSON line: compile step, 5-step warmup, steady-state
mean/σ, SYPD, Mcells/s + full provenance (grid, dt, recipe, precision,
devices, forcing/physics state). Reference (Mac CPU, R1, fp64):
~154 SYPD on an 8-step smoke; the AISSAI JAX hackathon (Jean-Zay, H100)
measured the full ladder — see the campaign's committed JSONLs for
GPU-class numbers.

## Provenance

`experiment.tag` records the pinned legoESM commit, the applied patches
(the multi-GPU/restart/seed/timing lanes are upstream since PR #1926 —
pins at or after the merge carry no patch for them), and the runner tag.
`reproduce.py` rebuilds the environment from it.

## References

- Kamm, D., Deshayes, J., & Madec, G. (2025). *DINO: a diabatic model of
  pole-to-pole ocean dynamics to assess subgrid parameterizations across
  horizontal scales.* GMD, 18, 8091–8107. doi:10.5194/gmd-18-8091-2025
- legoESM: `packages/ocean/legoesm/ocean/experiments/dino.py`
  (`DINOConfig` — the authoritative defaults + NEMO-fidelity switches),
  `docs/ocean/experiments/dino_replication_plan.md`.
- AISSAI JAX Hackathon campaign (performance + validation):
  the `run_dino_spmd.py` additions ported here were validated on Jean-Zay
  H100 (strong/weak scaling, restart exactness, physical consistency).
