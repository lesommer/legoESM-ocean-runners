# BENCH experiments through the runners

[BENCH](https://doi.org/10.5194/gmd-15-1567-2022) is NEMO's performance
benchmark (Irrmann, Masson, Maisonnave, Guibert & Raffin 2022, Sect. 2.2;
NEMO `tests/BENCH`): a flat-bottom all-ocean global box with analytic zero
forcing and a **unique value at every grid point** (the `z2d` ramp — an
MPI/halo/sharding bug detector), run with full production complexity so the
benchmarked step cost is the production cost. Results are **physically
meaningless by design**; validation is stability-only.

This guide covers the `global_ocean/bench` template: what runs, what maps
where, and the preset / tripole / timing lanes.

## What the runner does

`run_experiment run` on a `bench` config delegates to legoESM's standalone
timing harness `scripts/run/run_bench.py` (`_run_bench` in
`runners/run_experiment.py`; upstream PR climate-federation/legoESM#1934).
The harness **builds the `BenchConfig` itself** — production-like
`legoesm_nemo_like_v1` dycore recipe (vector-invariant momentum, RK3,
explicit-substep barotropic, ppm_fct tracers, veros_gsw EOS, SMC03 PGF) +
TKE vertical mixing + enhanced-diffusion convection, uniform z* with 74 wet
levels (dz ≈ 67.6 m), zero forcing, no bottom drag. The runner therefore
forwards only legitimate overrides; it does not re-interpret BENCH physics.

Benchmarks **count steps, not days**: `time.duration_days` is nominal and
is NOT forwarded; the run is governed by `run.steps` (NEMO `nn_itend`
default 1000, of which the first `run.warmup_steps` are excluded from the
steady-state mean as JIT-plateau warmup).

Template → CLI mapping:

| Template field | `run_bench.py` flag | Notes |
|---|---|---|
| `grid.type` | `--grid` | `latlon` (Mercator, truncated at 80°) or `tripole` (synthetic north fold, no mesh file) |
| `run.preset` | `--preset` | `orca1_like` (default), `orca025_like`, `orca12_like` — sizing + measured-stable dt travel together |
| `run.steps` | `--steps` | default 1000 (NEMO `nn_itend`) |
| `run.warmup_steps` | `--warmup-steps` | default 5 |
| `time.dt_seconds` | `--dt` | forwarded **only when ≠ the template nominal** (orca1_like 1200 s) — see below |
| `grid.nlev` | `--nlev` | default 74 (NEMO `nn_ksize=75` → 74 wet levels); forwarded only if changed |
| `ocean.H_max` | `--H-max` | default 5000 m; forwarded only if changed |
| `ocean.lat_max_deg` | `--lat-max` | default 80°; forwarded only if changed |
| `run.n_lat` | `--n-lat` | tripole only; defaults upstream to the preset's NEMO-exact j-count |
| `run.timing_jsonl` | `--timing-jsonl` | path resolved against the experiment directory |
| `run.float32` | `--no-x64` | fp32 benchmarking (default is fp64) |
| `run.extra_args` | verbatim passthrough | `{data_root}` substituted; upstream flags recorded verbatim in `config.yaml` + `experiment.tag` |

**dt vs preset (the baroclinic_gyre lesson).** The dt values are
measured first-stable-guess boundaries halved for margin (stability probes
committed upstream, 2026-10-10): a full-sphere equirectangular latlon row
is barotropic-CFL-unstable at the pole, and the Mercator truncation at 80°
is what makes the presets stable at all. `time.dt_seconds` is forwarded
only when it differs from the template's nominal default, so
`-o run.preset=orca025_like` re-sizes dt with the grid (300 s) instead of
silently inheriting 1200 s — which exceeds the orca025_like stability
boundary. The pre-registered stability gates catch a too-large dt by
design (the run FAILS, exit 1); never relax a gate to make a run pass.

## Preset ladder (overrides, not new templates)

| Preset | n_lon × n_lat (latlon) | n_lat (tripole) | levels | dt (s) |
|---|---|---|---|---|
| `orca1_like` (default) | 360 × 278 | 331 | 74 | 1200 |
| `orca025_like` | 1440 × 1116 | 1206 | 74 | 300 |
| `orca12_like` | 4320 × 3350 | 3146 | 74 | 120 (extrapolated — re-measure before long runs) |

```bash
# 0.25° analog via overrides (no new template):
bin/run-experiment init runs/<name> -o run.preset=orca025_like
```

## Tripole fold lane

`grid.type: tripole` (or `-o grid.type=tripole`) runs the **synthetic
tripole** — an active north fold with no mesh file — the same fold machinery
the production tripolar OMIP lane uses. NEMO's orca1_like preset uses an
F-fold; the synthetic tripole is a T-fold for every preset (a documented
upstream divergence, like the temperate IC backgrounds and the spherical
instead of flat 100-km beta-plane domain).

## Timing

```yaml
run:
  timing_jsonl: timing_bench.jsonl    # relative to experiment dir
```

The run appends one JSON line (`run_dino`-compatible contract): `compile_ms`,
`steady_mean_ms`/`steady_std_ms` over the post-warmup steps, `sypd`
(years simulated per day at the preset dt), `mcells_s`, plus full
provenance (`preset`, `grid_type`, `fold_active`, sizes, `dt`, `steps`,
`n_devices`/`n_processes`, `precision`, `recipe`,
`gates_pass`, `max_speed_final`, `max_eta_final`, `step_times_ms`). No
snapshots are written — no I/O perturbs the measurement.

The exit code carries the pre-registered stability gates: all final fields
finite, max pointwise speed < 1 m/s, max |eta| < 1 m. `gates_pass: false`
or a nonzero exit means the preset dt (or recipe) is wrong for that size —
the fix belongs upstream in `BENCH_PRESETS`, not in the gates.

## Weak scaling — not wired (follow-up)

NEMO BENCH's weak-scaling mode (negative `nn_jsize`) is an explicit
follow-up: it needs SPMD sharding, which `run_bench.py` does not expose
(the upstream `--weak-lat-rows` flag was removed in the adversarial review
rather than ship something misleading). Run strong-scaling presets across
ranks/devices for now; a genuine weak-scaling lane belongs in this repo
once upstream wires SPMD sizing.

## Provenance

`experiment.tag` records the pinned legoESM commit (bench is upstream since
PR #1934 — no patch required), the applied patches, and the runner tag.
`reproduce.py` rebuilds the environment from it. The `36x72` CI-sized
matrix lane stays upstream (`scripts/matrix/run_ocean_test_matrix.py --only
bench --grid latlon`); the runners lane is the preset-driven timing harness.

## References

- Irrmann, G., Masson, S., Maisonnave, É., Guibert, D., & Raffin, E. (2022).
  *Improving ocean modeling software NEMO 4.0 benchmarking and communication
  efficiency.* GMD, 15, 1567–1582. doi:10.5194/gmd-15-1567-2022
- legoESM: `packages/ocean/legoesm/ocean/experiments/bench.py`
  (`BenchConfig` + `BENCH_PRESETS` — the authoritative sizing/dt table),
  `scripts/run/run_bench.py`, `docs/ocean/experiments/bench_plan.md`
  (provenance, divergences, measured dt boundaries).
