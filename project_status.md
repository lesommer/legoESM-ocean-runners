# Project Status

*Last verified: 2026-10-23 — legoESM pin 1f6a1df4cf36, runner tag legoesm-1f6a1df4cf36-20261023c (see legoESM_version.txt)*

This document tracks what's currently implemented and tested in the runners. Consult it before assuming any capability.

## Runner implementation status

Init (template → `config.yaml` + `experiment.tag` + `run.sh`) works for every mode. `run_experiment run` executes a simulation only on these lanes; everything else is init-only:

- `ocean_scm` — native run path (YAML → model → NetCDF); all 5 templates run-tested.
- `3d_ocean` — `dino` (delegation to legoESM `run_dino.py`), `bench` (delegation to legoESM `run_bench.py`) plus 11 matrix-lane idealized cases (delegation to the upstream ocean test matrix); all other cases init-only.
- `barotropic_ocean` — `barotropic_double_gyre` (runners-owned) and `barotropic_wave` (graduated 2026-10-22, canonical `ocean/barotropic_wave`) via the same matrix delegation; other barotropic templates init-only.
- `3d_ocean_realistic` — tripolar grids only (eORCA1 OMIP via `run_omip_core2.py`); other grid types init-only.
- `coupled` — init-only.

Quick answer to "will `run_experiment run` execute my template?": find the template's row in the Template test status table below — `run-tested` or `smoke-tested` means yes (on the recorded lane); `structural` or `init-only` means no (init and provenance still work). The mode table gives the mechanism per mode.

| Mode | Init (YAML → config.yaml + tag) | Run (config.yaml → model → output) | Notes |
|------|----------------------------------|-------------------------------------|-------|
| `ocean_scm` | Working | **Working** | Native run path; see the `ocean_scm` subsection below. |
| `3d_ocean` | Working | **Working: `dino`, `bench` + matrix-lane cases (11 runners-owned or graduated)** | Three delegation lanes; see the `3d_ocean` subsection below. Other cases: init-only. |
| `barotropic_ocean` | Working | **Working: `barotropic_double_gyre` (runners-owned), `barotropic_wave` (graduated)** | Matrix delegation like the 3D lanes; see the `barotropic_ocean` subsection below. Other templates: init-only. |
| `3d_ocean_realistic` | Working | **Working: tripolar grids** | Script delegation to `run_omip_core2.py`; see the `3d_ocean_realistic` subsection below. Other grid types: init-only. |
| `coupled` | Working | **Implemented, untested** | Constructs `CoupledESMDriver`; no end-to-end run recorded. See the `coupled` subsection below. |

### Recipe identity validation (ocean.recipe)

Added 2026-10-21 (recipe × setup integration with the pinned legoESM): templates declare their scheme identity via `ocean.recipe`. Matrix-lane templates MUST name the pinned `recipe_map` tag of their `ocean.case` (declared identity — the upstream matrix case owns the recipe; the field is not forwarded); the dino lane takes optional DINO recipe cards (`ocean.recipe` → `run_dino.py --recipe`, e.g. `nemo_dino_kamm_mlf`); the tripole OMIP lane is pinned to `omip_nemo_match_tripole_v1` (`omip_faithful_card` declares nothing — it overrides dycore fields via `run.extra_args`, and recipe names are fidelity claims). `scripts/validate_templates.py::validate_recipe` resolves every declaration against the pinned legoESM catalogs (`EXPERIMENT_RECIPES`, `DINO_RECIPES`; import-gated, so the semantic checks run where legoESM is installed — CI Tier-2 — and degrade under `--skip-imports`), and `generate_tag` records the declaration in `experiment.tag` `[model]`. An upstream recipe rename/re-tagging therefore breaks validation at pin-bump time instead of silently drifting (the `nemo_v1` → `legoesm_nemo_like_v1` lesson, 2026-09-02). Cases with no upstream tag (`barotropic_gyre`, `barotropic_double_gyre`, `rest_state_stratified_no_land`) must not declare a recipe. Mechanism tests: `tests/test_templates.py::TestRecipeValidation` (planted violations + a real-parity test against the pinned catalogs).

### Manifest stamping (run-time layer identity)

Added 2026-10-21 (issue #8, Phase 2A): the runners layer stamps itself into legoESM's per-run `run_manifest.json` — the run-time superset of `experiment.tag`, now actually carrying the runners identity. The generated `run.sh` computes and exports, at **run time**, `LEGOESM_RUNNER_TAG` (`<legoesm-* tag | untagged@sha> template=<name>`) and `LEGOESM_RUNNER_PATCHES` (comma list of `patches/*.patch`); `build_run_manifest()` — via patch `006-manifest-runner-tag.patch` (upstream PR climate-federation/legoESM#2100; remove when merged) — records them under `[reproducibility]`. Division of truth: `experiment.tag` is the init-time snapshot, the manifest the run-time truth (if the repo moved between init and launch, the manifest reports what actually ran). Companion `experiment.tag` additions: per-patch content digests (`patch_sha256_<stem> = sha256:<16hex>` — a re-edited same-named patch is detectable), the raw override list (`[reproducibility] overrides`, JSON — the missing link for `reproduce.py --run`), and `runner_tag` now falls back to `untagged@<sha>` in the untagged window (`reproduce.py` checks out the sha). Mechanism tests: `tests/test_templates.py::TestOrchestratorProvenance` (bash-execution probe of the generated snippet, planted-failure coverage, and an env→manifest end-to-end check against the pinned legoESM). Numbering note: an earlier, unrelated `006` patch (dino SPMD) was dropped at the 2026-10-10 pin bump after upstream merge — the number was reused.

### Provenance verification gates (issue #8, Phase 2B)

Added 2026-10-21: three gates close the drift paths found in the 2A audit. (1) `reproduce.py --verify` audits a tag against the current checkout with no side effects: recomputes `config_hash` from template + recorded overrides, checks every recorded `patch_sha256_*` against the current `patches/` (missing file and content drift are distinct failures); `--run` now re-applies the recorded overrides (previously dropped silently — a reproduced run fell back to template defaults). Tests: `TestReproduceVerify` (planted drift in hash/overrides/patch content; CLI end-to-end exit codes; `--run --dry-run` shows the `-o` flags). (2) `sync_legoesm.sh` full flow re-verifies the patch chain against the NEW pin (clean detached probe worktree between template validation and the atomic pin write) — a patch that stopped applying fails the bump instead of drifting; `apply_patches.sh` accepts git worktrees as `LEGOESM_DIR` (`--show-toplevel` check — a worktree has a `.git` file, not a directory). (3) CI Tier-2 now APPLIES the patch chain before validation and runs the full test suite (previously the patch step was `--check`-only, pointed at the wrong `LEGOESM_DIR`, and swallowed by `|| true` — advisory AND broken); Tier-2 therefore validates the deployment state (pin + patches), and the env→manifest e2e test runs there instead of skipping.

### Ocean lane screening gate (issue #10)

Added 2026-10-23: the Phase-3B gates watch runners *templates* — nothing detected a new upstream *lane* (matrix case, recipe-catalog entry, ocean driver script, non-`ocean/` upstream template). `scripts/validate_templates.py::check_ocean_lane_coverage()` enumerates the pinned legoESM ocean surface import-free (AST parse of the matrix `RUNNERS` dispatch + `TestCase` appends with their grid sets, file-path-loaded `recipes.py`/`recipe_map.py` catalogs, an AST import scan of `scripts/run/**.py`, and a glob of `config/templates/**` in ALL categories) and fails validation on any lane without a disposition in `docs/ocean_lane_dispositions.yaml`, on any stale entry, on any matrix grid-set drift, and on schema violations (unknown status; `declined` without reason). Blocking where validation already runs with the checkout present: pin bumps (`sync_legoesm.sh` validates before the atomic pin write) + CI Tier-2; skipped under `--skip-imports` (CI Tier-1). The weekly sync-check enumerates upstream **main** in warn-only mode (`--lanes-warn`) and posts `::warning::` annotations for lanes that will need a disposition at the next pin bump. Disposition statuses: `onboarded | graduated | upstream_only | delegation | declined(reason) | backlog`; onboarding a lane flips its `matrix:`/`experiment_recipe:`/`template:` entries in the same commit as the wiring + receipt. Enumeration is fail-closed: an idiom the AST evaluator cannot parse fails the gate (never a silently smaller surface).

### ocean_scm (native run path)

Constructs `OceanColumnModel` from the resolved config, runs the simulation, and saves NetCDF output. All 5 templates are run-tested end-to-end.

### 3d_ocean (dino and matrix lanes)

Three delegation lanes; per-template receipts live in the Template test status table below.

- **`dino`** (lat-lon): `_run_dino` in `runners/run_experiment.py` delegates to legoESM `scripts/run/run_dino.py`, the standalone DINO production driver. It builds the paper-faithful R1 `DINOConfig` itself (Kamm et al. 2025 defaults: KPP + Visbeck GM/Redi + EVD convection, Wright EOS, zstar 36 lev, dt 2700), so the runner forwards only legitimate overrides: resolution (`grid.n_lon`), duration, snapshot cadence, scheme flags (forwarded only when ≠ template default, so `ocean.recipe` cards stand), recipe cards via `ocean.recipe`, plus the run-control lanes `run.n_devices` (lat-band SPMD; requires `n_lat % N == 0` — the R1 grid's 198 rows divide by 1 and 2 only), `run.restart_from` (snapshot NPZ; clock restarts at 0), `run.seed` (ensemble IC; 0 = canonical), and `run.timing_jsonl`. Multi-GPU, restart, seed and timing are upstream since PR climate-federation/legoESM#1926 (merged); patch 006 was dropped at the 2026-10-10 pin bump. Restart is verified bit-exact on CPU; SPMD parity within the re-association floor.
- **Matrix-lane idealized cases** (runners-owned: `neverworld2_lite`, `rest_state_stratified_no_land`, `isomip_plus` (wired 2026-10-23, issue #10 Tier 1); graduated, same dispatch: `baroclinic_gyre`, `lock_exchange`, `overflow`, `acc_channel`, `geostrophic_adjustment`, `phillips_two_layer`, `global_overturning`, `eady_instability`): `_run_matrix_case` delegates to legoESM `scripts/matrix/run_ocean_test_matrix.py --only <case> --grid <grid>`. The upstream matrix runner owns the scientifically-validated configuration (grid geometry, ICs, physics, stability-verified dt/duration pairs — see legoESM `docs/dev-notes/ocean_experiments_reference.md`); the runner forwards only duration/dt/levels/resolution overrides. Template physics fields are the documented intent; the upstream baseline is what runs. NB: upstream `--only` is a substring match — `baroclinic_gyre` also runs the `baroclinic_gyre_cos` variant and `barotropic_double_gyre` also runs `_sin2` (extra runtime, both gated). `eady_instability` dispatches lat-lon templates onto the upstream `latlon_channel` lane (both eady lanes are channel-only; upstream excludes `mpas_channel` for eady_instability — it blows up). `neverworld2_lite` uses the upstream 180x360 lane resolution (not the 36x72 matrix default).

- **`bench`** (lat-lon + synthetic tripole): `_run_bench` in `runners/run_experiment.py` delegates to legoESM `scripts/run/run_bench.py` (PR climate-federation/legoESM#1934), the standalone NEMO-BENCH timing harness (Irrmann et al. 2022 port; production-like `legoesm_nemo_like_v1` recipe + TKE, zero forcing, per-point unique ICs — results physically meaningless by design). The harness builds the `BenchConfig` itself, so the runner forwards only `run.preset` (`orca1_like` | `orca025_like` | `orca12_like` — sizing and the measured-stable dt travel together), `run.steps` (NEMO `nn_itend`; benchmarks count steps, not days — `time.duration_days` is nominal and NOT forwarded), `run.warmup_steps`, and `run.timing_jsonl` (run_dino-compatible record, absolutized to the experiment dir). `time.dt_seconds` forwards as `--dt` only when ≠ the template's nominal default (orca1_like 1200 s), so a preset override re-sizes dt with the grid instead of inheriting 1200 s above the orca025_like boundary (the baroclinic_gyre dt lesson; tests: `TestBenchLane`). `grid.type: tripole` selects the synthetic north-fold lane (`--n-lat` defaults to the preset's NEMO-exact j-count; `run.n_lat` overrides). No snapshots are written (no I/O perturbs the measurement); the exit code carries the pre-registered stability gates (finite fields, max speed < 1 m/s, max |eta| < 1 m). The 36x72 CI matrix lane stays upstream (`run_ocean_test_matrix.py --only bench`).

All other `3d_ocean` cases: init + provenance only.

**Graduated templates** (issue #8, Phases 3B-2/3B-3/3B-4): templates whose upstream counterpart in the pinned legoESM template library (`config/templates/ocean/<stem>.yaml`) is the single source of truth are RESOLVED from there — canonical name `ocean/<stem>`, translated to the runners dialect by `runners/run_experiment.py::_adapt_upstream_template` (recipe emitted from the pinned `EXPERIMENT_RECIPES`; no time/output; duration/dt/resolution/nlev forwardable as overrides). Graduated 2026-10-22: `baroclinic_gyre` (pilot), plus the run-tested matrix lanes `acc_channel`, `eady_instability`, `geostrophic_adjustment`, `lock_exchange`, `overflow`, `phillips_two_layer`, `global_overturning`, `barotropic_wave` (batch; post-graduation lane-default receipts in ledger `macbook_2026-10-22_bg-batch8-graduation`), and `stommel_gyre_tracer` (3B-4: wired into `_MATRIX_CASES` first — lane verified at pin `1f6a1df4cf36` — then graduated; receipt in ledger `macbook_2026-10-22_bg-stommel-graduation`). Legacy aliases (`3d_idealized/<name>`, `global_ocean/global_overturning`, `2d/barotropic_wave`, `2d/stommel_gyre_tracer`) keep old names and pre-graduation tags resolving. Run-receipts for graduated templates live in the experiment ledger / upstream's own status docs, not in the table below. **Upstream-only cases** (usable via `ocean/<name>`, no runners YAML ever existed — init + provenance here; receipts are upstream's business): `eady_uniform`, `held_larichev`, `munk_gyre`, `global_barotropic_wind` (the last one routes `barotropic_ocean`; the others are 3d stubs in this repo until upstream-lane receipts justify onboarding). `scripts/validate_templates.py` gates the remaining runners-owned templates against their upstream counterparts (Phase 3B-1: `bench` — terminal state, see below; `inertia_gravity_wave` — blocked on the known upstream gate defect).

### barotropic_ocean (matrix lanes)

Added 2026-10-10: the `_run_ocean` dispatch accepts `barotropic_ocean` mode for matrix-lane cases and routes them through `_run_matrix_case` like the 3D lanes — the upstream ocean test matrix executes them with the same 3D machinery. `barotropic_wave` and `stommel_gyre_tracer` are graduated matrix lanes (see above). Other barotropic templates (`barotropic_gyre`, `inertia_gravity_wave`): init + provenance only.

### 3d_ocean_realistic (tripolar OMIP)

Script delegation: the runner calls legoESM `scripts/run/run_omip_core2.py` (upstream, extended by patch `002-omip-core2-extensions.patch`), which provides `build_tripole()` (eORCA1 mesh mask reading), `load_core2_nyf()` (CORE-II Normal Year Forcing), WOCE IC loading, and the flags `--scan-block` (lax.scan stepping), `--convection enhanced_diffusion`, `--partial-cell`, `--synthetic-forcing` (explicit opt-in smoke tests without real Zarr data), `--forcing-scale` (amplitude multiplier), and `--days` (short experiments). Other grid types are init-only.

**CLI remap at pin `c986cb989` (2026-10-07)**: the upstream script was rewritten; patch 002 was regenerated against it (same three flags), and the delegation now maps WOCE ICs to `--nemo-monthly-init <temp> <salt>` and SSS restoring to `--sss-restore --sss-restore-file <clim> --sss-restore-tau-days <tau>`.

**cwd and mesh resolution (fixed 2026-10-07)**: upstream `build_tripole` asserts `--mesh` resolves to the canonical repo-relative `data/grids/<file>` path, so the runner executes the delegated script with `cwd=<legoesm>` and passes the repo-rooted mesh (`<legoesm>/data/grids/<mesh_file>` — the mesh MUST exist there; a symlink into `data_root` is fine). `--output` is absolutized against the experiment dir (a relative output path would relocate under the changed cwd). Verified end-to-end (grid build + synthetic 5-day startup); receipts in the `omip_tripole` row of the Template test status table.

**MPI (patch `003-omip-core2-mpi.patch`)**: when `mpi.enabled: true`, the runner dispatches to `scripts/run/run_omip_core2_mpi.py` with latitude-band domain decomposition (details in the MPI section below).

**Delegation mapping (full 229-flag audit, 2026-10-07)**:
- `--tripole-vmix` ← `physics.vertical_mixing.scheme`
- `--bottom-drag-{scheme,r,cd0,cdmax,z0,ke0}` ← `physics.bottom_drag` (template `linear` → legacy)
- `--no-gm-redi` ← `physics.lateral_mixing.enabled: false`. Caveat: the upstream tripole recipe ships GM/Redi ON (κ=600) by default — the 2026-10-07 smokes ran with GM active despite their `enabled: false` override; this mapping corrected it.
- `--runoff` ← `forcing.runoff.enabled`; the `_RUNOFF_NC` hardcode is fixed by patch `004-runoff-file-override.patch` — supply `--runoff-file` (and `--nemo-domain-cfg`) via the template method in the NEMO-faithful card section; no longer blocked on upstream's machine.
- No upstream `--water-type` flag exists; Jerlov II is the upstream default and matches the template.
- Remaining unmapped upstream flags are grid-specific (`--cube-*`, `--fesom-*`, `--mpas-*`) and unenumerated physics/numerics families; card runs use the verbatim `run.extra_args` passthrough (see the card section).

**Caveat — siconc hardcode**: at this pin `--sss-restore` implies loading NEMO siconc from an upstream-hardcoded path (`_SICONC_NC`) that does not exist off upstream's machine; disable via `physics.sss_restoring.enabled: false` until an env-override patch lands. (The sibling hardcoded inputs — runoff, chl, domain_cfg — live in the same upstream repo directory and resolve only where staged.)

### coupled

`_run_coupled` constructs `CoupledESMDriver` from the `coupled.preset`, but no end-to-end run has been recorded. All three coupled templates are `structural`.

### Init-only lanes

Modes, grids, and cases without a run path are executed by calling legoESM's own Python scripts directly (e.g., `legoESM/scripts/run/run_omip.py`). The runners still handle init and provenance tagging for these — the generated `config.yaml` and `experiment.tag` are valid even though `run_experiment run` does not execute a simulation.

## Template test status

Single source of truth for per-template status. `Status` uses a controlled
vocabulary (`run-tested` | `smoke-tested` | `init-only` | `structural`);
receipts (dates, machines, gate values) live ONLY here — never in the mode
table above or in the README (the README block is generated by
`scripts/render_readme_status.py`). This table is cross-referenced against
`templates/` by CI: every template file must have exactly one row, and
vice versa.

| Category | Template | Status | Receipt |
|----------|----------|--------|---------|
| `1d/` | `ocean_scm_convective` | run-tested | Native SCM run path; NetCDF output verified |
| `1d/` | `ocean_scm_ekman` | run-tested | Native SCM run path; NetCDF output verified |
| `1d/` | `ocean_scm_surface_heating` | run-tested | Native SCM run path; NetCDF output verified |
| `1d/` | `ocean_scm_kpp_wind` | run-tested | Native SCM run path; NetCDF output verified |
| `1d/` | `ocean_scm` | run-tested | Native SCM run path; NetCDF output verified |
| `2d/` | `barotropic_double_gyre` | run-tested | 2026-10-10, Mac CPU via matrix delegation: latlon_regional 24x48, 2 d, upstream gates 2/2 PASS incl. the `_sin2` substring variant — max speed 0.0647 / 0.0301 m/s |
| `2d/` | `barotropic_gyre` | structural | — |
| `2d/` | `inertia_gravity_wave` | structural | — (known upstream gate defect; excluded from onboarding) |
| `3d_idealized/` | `rest_state_stratified_no_land` | run-tested | 2026-10-10, Mac CPU via matrix delegation: latlon 36x72, 0.1 d, upstream gates PASS — eta drift 0.00, T drift 5.09e-16, S drift 1.42e-15; new template |
| `3d_idealized/` | `dino` | run-tested | 2026-10-10, Mac CPU end-to-end test: 198×50 R1, 8 steps, 154 SYPD; delegation via `run_dino.py`; template rewritten to paper-faithful R1 defaults; multi-GPU/restart/seed/timing upstream since PR #1926. 2026-10-11, ige-calcul1 A40 1-yr lane (R2/R4 + `nemo_dino_kamm_mlf` card): found and fixed recipe-clobber — template-default scheme flags were forwarded unconditionally and silently overrode the card; scheme flags now forwarded only when ≠ template default (tests: `TestDinoSchemeForwarding`) |
| `3d_idealized/` | `isomip_plus` | run-tested | 2026-10-23, Mac CPU via matrix delegation: latlon_regional 32x16, 10 lev, dt 300, **full lane-design 365 d**, upstream gates 1/1 PASS — mdot=1.489 m/yr cavity-mean basal melt (issue #10 Tier 1; lane dt is DEFAULT_DT 300, not the issue's 5.0 = quick_days; receipt `macbook_2026-10-23_isomip-plus-wiring`) |
| `coupled/` | `coupled_aquaplanet` | structural | — |
| `coupled/` | `coupled_slab` | structural | — |
| `coupled/` | `coupled_full` | structural | — |
| `global_ocean/` | `omip_jra55` | structural | — |
| `global_ocean/` | `neverworld2_lite` | run-tested | 2026-10-10, bigfoot V100 via matrix delegation, native OAR submission (`oarsub -S ./run.sh`): latlon 180x360, 50 lev, dt 300, 5 d, upstream gates 1/1 PASS — \|u\|max=0.643 m/s, "eddy-permitting"; ledger run `bigfoot_2026-10-10_nw2-wave1`; template aligned to lane design 180x360 / dt 300 / 365 d |
| `global_ocean/` | `bench` | smoke-tested | 2026-10-11, Mac CPU end-to-end via `_run_bench` delegation at pin `294495454a` (both lanes): latlon 72×54×74 dt 1200, 20 steps (5 warmup) — gates PASS (max_speed 0.0579 m/s, max_eta 0.351 m), 61.7 ms/step steady, 53.2 SYPD; tripole 32×72×74 (fold active) — gates PASS (0.0753 m/s, 0.387 m), 87.4 SYPD; `timing_bench.jsonl` written both lanes; preset downsized via `grid.resolution=72x56` / `run.n_lat=32` |
| `global_ocean/` | `omip_global` | structural | — |
| `global_ocean/` | `omip_cubed_sphere` | structural | — |
| `global_ocean/` | `omip_tripole` | smoke-tested | 2026-10-07 `macbook_2026-10-07_tripole-repin-5day`: 720 steps, no NaN, 2.85 s/step (M-series CPU, synthetic forcing; delegation verified at pin `c986cb989`). 2026-10-08 `bigfoot_2026-10-08_tripole-gpu-smoke` (V100): exit 0, 1.17 steps/s ≈ 3.3× CPU, diagnostics identical to the CPU run at print precision |
| `global_ocean/` | `omip_faithful_card` | structural | Init works anywhere; execution requires staged data on the target machine (eORCA1 mesh mask, WOCE ICs, CORE2 forcing — see the NEMO-faithful card section); card flags pass through via `run.extra_args`. No end-to-end run recorded yet |
| `global_ocean/` | `omip_core2_thin` | smoke-tested | Upstream receipt 2026-08-18 (one RTX 8000): pure-defaults `run_omip_core2.py --years 4 --dt 600`, ~9.5 SYPD (replication campaign documented in ledger `jeanzay_2026-10-09_orca1-thin-year4`). Mac CPU 0.5-day startup smoke 2026-10-09 at pin `c986cb989` (synthetic forcing fallback): grid (332,362), 72 steps finite, 1.90 steps/s. Real `_MOD` forcing resolves on machines with the staged cache (jean-zay). `initial_conditions.type: rest` = no IC flags (documented lane) |

## Definitions

The `Status` column of the table above uses a controlled vocabulary
(enforced by `scripts/render_readme_status.py` and CI):

- **structural** (a.k.a. structurally validated) — `validate_templates.py --skip-imports` passes: the YAML has required sections (`experiment`, `grid`, `time`), a valid mode, a valid grid type, and `requires` references match entries in `data_catalog.yaml`. No legoESM code is exercised (the `ocean.recipe` semantic checks are import-gated and run only with legoESM installed — CI Tier-2 / plain `validate_templates.py`).
- **init-only** — `init_experiment()` successfully loads the template, applies overrides, writes `config.yaml`, `experiment.tag`, and `run.sh`; no end-to-end execution recorded.
- **smoke-tested** — the runner executed a short/startup run (e.g. 0.5-day startup, synthetic forcing) and produced finite output; not a full-duration or fully-forced run.
- **run-tested** — the runner executed the experiment through the delegated/production run path and produced output with upstream gates PASS (NetCDF, diagnostics JSON, etc.).

(`init-only` implies init testing succeeded; `smoke-tested` and
`run-tested` imply it transitively — that is why the separate
"Init tested" column is gone.)

## The NEMO-faithful card (template `global_ocean/omip_faithful_card`)

Added 2026-10-08. The template encodes the *standard NEMO-faithful 1° card* declared in legoESM `scripts/cluster/omip_nemo/run_standard_faithful_1deg.sbatch` (validated `nemolev_trp_long180` configuration, see legoESM `docs/dev-notes/OMIP_faithful.md`): TKE (NEMO Dirichlet surface BC, `nn_mxl=3`, prognostic, veros_sqrte κ convention), prognostic sea ice (free-drift, `--ice-init` SI3 NC), MLE, iwm, dm2dc, ISF 'spe' melt + Dai-Trenberth runoff (`--runoff-depth-nemo-ini`, river-mouth gate), SSS restoring (τ=45.5 d, ±4 mm/d cap, NEMO ice gate), RGB-chl SW, geothermal, bbl-adv, smc03 PGF, smag sched, momentum-RK3.

Delegation additions at this pin:
- **Verbatim passthrough**: `run.extra_args` (list) from the template is appended after all mapped args with only the `{data_root}` token substituted — machine-portable, recorded verbatim in `config.yaml` + `experiment.tag`.
- **`time.duration_overshoot_days`** (default 0.0): adds the standard card's +0.05 d overshoot to `--years`/`--days` (the driver skips the cadence snapshot at the exact final step, so the advertised day-N snapshot only lands as a normal cadence write).
- **`output.snapshot_every_days` / `output.diag_every_days`** mapped to the upstream cadence flags.
- **Patch `004-runoff-file-override.patch`** adds upstream `--runoff-file` (fixes the `_RUNOFF_NC` hardcode; the `--isf`/`--runoff` double-count check follows the effective source). Remaining card path needs are satisfied by explicit flags: `--nemo-vertical-file`/`--nemo-domain-cfg` (domain_cfg.nc), `--chl-file` (RGB chl; card default `_CHL_NC` — override staged), `--siconc-file` (RUN_REF icemod, staged), `--iwm-forcing-file`, `--isf-forcing-file`, `--ice-init`, `--woa-t/--woa-s`, `--runoff-file`.

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

## Scheduler support in generated run.sh (SLURM, OAR)

`_generate_run_script` in `runners/run_experiment.py` emits scheduler directives based on the `scheduler` field of the machine config (experiments repo `machines/*.yaml`):

- **`slurm`** → `#SBATCH` header (job name, partition, account, nodes, tasks, cpus-per-task, walltime, mem, gres, constraint, qos, output/error). Submit with `sbatch run.sh` (jean-zay path, run-tested since 2026-10-08).
- **`oar`** (added 2026-10-10, GRICAD/CIMENT clusters: bigfoot, dahu, kraken/OAR v3) → `#OAR` header: `-n <experiment-name>`, `--project` ← `oar_project`, `-l <oar_resources>,walltime=<scheduler_walltime>` (walltime skipped if `oar_resources` already carries one), `-p "<oar_properties>"`, `-t <oar_types...>`, optional `-O`/`-E` from `scheduler_output`/`scheduler_error`. Submit with `oarsub -S ./run.sh` (path form required — a bare `run.sh` fails PATH lookup); `run.sh` is generated executable (`chmod 0o755` — OAR `-S` execs the script directly, and a non-executable run.sh fails with "Permission denied"; ledger `bigfoot_2026-10-10_nw2-wave1`). Job logs land as `OAR.<name>.<jobid>.stdout/.stderr` in the submission directory, monitor with `oarstat -u`. This replaces the previous manual `oarsub` wrapper around `bin/run-experiment` (scheduler: null). Unit-tested in `tests/test_templates.py::TestRunScriptGeneration`; bigfoot end-to-end verification tracked in issue #4.
- **`null`** → no directives; `run.sh` runs directly (`bash run.sh`) or via a hand-written scheduler wrapper.

Directives always precede the first shell command (`set -euo pipefail` comes after the block) — SLURM stops parsing the header at the first command (jean-zay lesson, 2026-10-08).

## Installation (federation refactor)

legoESM uses a uv workspace federation layout (`packages/core/`, `packages/ocean/`, etc.). Import paths are unchanged (`legoesm.ocean.dynamics.*` still works via PEP-420 namespace), but the source files are no longer under `src/legoesm/`. The runners no longer set `PYTHONPATH=$LEGOESM_DIR/src` — instead, legoESM must be installed:

```bash
cd ../legoESM && uv sync
# or: pip install -e ".[dev]"
```
