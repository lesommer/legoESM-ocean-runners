# Pin bump 2026-11-12: 1f6a1df4cf36 → d20bb1cfa25b (1459 commits, post-1.0.0)

Previous large-jump notes: `upgrade-2026-10-22-pin-1f6a1df4cf36.md`,
`upgrade-2026-10-v1.0.0-jump.md`.

## Summary

- **Old pin:** `1f6a1df4cf36b78a6ab4f5602ba5e75795e78dae` (2026-10-22)
- **New pin:** `d20bb1cfa25b8ce7866d7cb8cc6df35e9a221436` (2026-11-12, upstream main HEAD)
- **Delta:** 1459 commits, all post-1.0.0 (`Unreleased` — no release boundary crossed)
- **Tag:** `legoesm-d20bb1cfa25b-20261112`

## What upstream changed that mattered (verified pre-flight via targeted diffs, confirmed at validation)

- **Orchestrator provenance merged upstream** (PR climate-federation/legoESM#2100,
  former patch 006): `build_run_manifest()` now natively reads
  `LEGOESM_RUNNER_TAG` into a NEW `[reproducibility].orchestrator_tag` field
  and appends `LEGOESM_RUNNER_PATCHES` to `.patches` (caller first, duplicates
  and blanks dropped). **Schema difference vs our patch:** upstream KEEPS
  `runner_tag` = the entry script's tag (replay specs and the
  one-run-per-directory check key on it); our patch had overwritten it.
  → patch 006 dropped; `TestOrchestratorProvenance::
  test_env_vars_reach_pinned_legoesm_manifest` rewritten for the upstream
  schema (skip only if the pin predates the field); project_status / README /
  AGENTS references updated.
- **IGW retarget (#2114):** upstream retargeted `ocean/inertia_gravity_wave`
  to the verified f-plane CHANNEL case (`setup: inertia_gravity_wave_channel`,
  grid `latlon_channel`, maturity run_tested; new recipe_map tag
  `inertia_gravity_wave_channel: default_wright_implicit_cn_v1`) and moved the
  global case our 2d template describes to the NEW stem
  `ocean/inertia_gravity_wave_global` (maturity init_only — no wave-speed gate
  constructible on the sphere). → `UPSTREAM_COUNTERPARTS["2d/inertia_gravity_wave"]`
  repointed to the global stem (the counterpart follows the case, not the
  stem); `ocean/inertia_gravity_wave_global` registered in
  `_UPSTREAM_TEMPLATE_MODES` (registry parity is exact-set-tested); channel
  onboarding stayed **backlog** per the pre-staged dispositions.
- **Recipe catalog:** new `default_wright_implicit_cn_v1` (the channel lane's
  recipe); `lateral_viscosity_mask_levels` added across the latlon recipes;
  NEMO-like + tripole-match recipes gained `lateral_side_bc: nemo_shlat`,
  `lateral_shlat: 2.0` (ORCA1 rn_shlat fidelity). No recipe RENAMES — the
  runners' `ocean.recipe` declarations all still resolve.
- **ePBL vertical mixing** added upstream (`VerticalMixingConfig(scheme="epbl")`,
  OMIP driver flags): no new runners lane surfaced (dispositions untouched).
- **`config/templates/ocean/` maturity bumps** (structurally_validated →
  run_tested for the graduated stems) — informational only, the consistency
  gate reports maturity and never blocks on it.
- **Heavy churn in `scripts/run/run_omip_core2.py`** (+229/−82; `run_omip.py`
  +395) — patch 004's context moved. `run_dino.py`, `ocean_test_matrix/setup.py`,
  `ocean_long_runs/run_omip2.py`, `test_ocean_long_run_drivers_forcing.py`
  UNCHANGED between pins.

## Patch chain (003–010 minus 006; names stable — no renumbering)

Pre-graduation `experiment.tag`s record `patch_sha256_<stem>` by name;
renumbering would orphan them.

| Patch | Disposition |
|---|---|
| `003-omip-core2-mpi.patch` | Kept; applies unchanged (new-file wrapper; upstream has no `run_omip_core2_mpi.py`) |
| `004-runoff-file-override.patch` | **Regenerated** against the new `run_omip_core2.py` (same feature: `--runoff-file` + `domain_cfg_file` plumb-through; `_load_nemo_cell_area_m2` now takes a path natively) |
| `005-bt-slow-depth-eval-decision90.patch` | Kept; applies unchanged |
| `006-manifest-runner-tag.patch` | **Dropped** — merged upstream as PR #2100 (see schema note above) |
| `007-dino-tke-n2-stage-flag.patch` | Kept; applies unchanged (`run_dino.py` untouched upstream) |
| `008-omip2-latlon-bottom-drag.patch` | Kept; applies unchanged |
| `009-omip2-freshwater.patch` | Kept; applies unchanged |
| `010-omip2-auto-resume.patch` | Kept; applies unchanged — but only IN CHAIN ORDER (its context includes 009's `run_omip2.py` edits) |

**Probe-tooling fix (reproducibility-affecting):** patches 009→010 are the
first STACKED pair (010's context is 009's output). Both
`sync_legoesm.sh`'s pin-bump probe and `apply_patches.sh --check` checked each
patch independently against a pristine tree — a false-positive on stacking.
Both now apply the chain IN ORDER to a throwaway detached worktree
(`git apply`, real, sequential). First bump where the probe actually exercises
the chain semantics.

**Lane-gate fix:** the reproducible surface is pin + patches — a patch-CREATED
ocean driver script (003) is a lane we consciously run.
`enumerate_ocean_surface()` now unions `_patch_surface_scripts()` (script
paths in `patches/*.patch` diff headers) into the script surface, so the
disposition for `script:scripts/run/run_omip_core2_mpi.py` is REQUIRED at
pin-bump time (clean checkout) and never goes stale. The patches dir is
derived from the dispositions file's repo root (same repo), so planted test
fixtures are isolated from the real chain; a planted patch-file test pins the
behavior (`TestLaneCoverageGate::test_patch_created_script_needs_disposition`).

## Dispositions added / updated (docs/ocean_lane_dispositions.yaml)

- `recipe:default_wright_implicit_cn_v1` — backlog (the channel lane's recipe)
- `experiment_recipe:inertia_gravity_wave_channel` — backlog (mirrors the matrix lane)
- `template:ocean/inertia_gravity_wave_global` — declined (no gate on the sphere; the runners 2d counterpart tracks it via the drift gate)
- `template:ocean/inertia_gravity_wave` — declined → **backlog** (the verified channel lane; graduation candidate)

## Environment / tooling notes

- **venv re-sync:** `uv sync --extra dev` was a no-op (lockfile unchanged at
  the new pin; jax/pytest versions already in place).
- The dirty-checkout caveat is unchanged: `sync_legoesm.sh` fast-forwards a
  CLEAN tree — reset the patched checkout first
  (`git checkout -- . && git clean -fd`), re-apply with `apply_patches.sh`
  after the bump.
- Upstream git-ref collision workaround (narrowed fetch refspec) still in
  place; fetch was clean.

## Verification (all green before tag)

- `sync_legoesm.sh` (staged): 23/23 templates full-import valid at the new
  pin; chain probe 7/7 in order → atomic pin write.
- `sync_legoesm.sh --check-only`: 23/23 (full imports, recipe + consistency +
  lane gates — 168 lanes, 126 dispositions, all covered).
- `apply_patches.sh --check`: 7/7 in chain order.
- `python3 -m pytest tests/test_templates.py`: 255 passed, 3 skipped.
  `../legoESM/.venv/bin/python -m pytest tests/test_templates.py`: 258
  passed (includes the env→manifest e2e against the pinned legoESM — the
  upstream `orchestrator_tag` channel verified end-to-end).
- `render_readme_status.py --check`: up to date.
