# Attention points: upgrading ocean-runners + experiments to latest legoESM

*Prepared 2026-10-07, before the upgrade. This note lives in the runners
repo (`docs/`) because the upgrade is executed here and should be versioned
with the tag it produces. Facts below were measured against
`~/git/lego-world/legoESM` (pin `69287951b423` → `origin/main` `c986cb989`).
The general procedure lives in the `lego-world-sync-runners` opencode skill;
this note records the measured specifics of THIS jump.*

## 0. Scale and shape of the jump (measured)

- **12,457 commits** between the pinned commit (`69287951b423`, 2026-06-06,
  PR #375 era) and `origin/main` (`c986cb989`, 2026-10-07, PR #1907 era). This is not a
  routine pin bump — it crosses the upstream **v1.0.0 release** (2026-10-01).
- **The repo moved org**: origin is now `https://github.com/leap-stc/legoESM/`
  (was `github.com/gentine/legoESM`; PRs merge from the `climate-federation`
  org). Update the clone remotes on every machine (macbook, ige-calcul1) and
  every doc reference (workspace-conventions, how-to, runners AGENTS.md).
  Old URLs likely redirect, but do not rely on that.
- **`src/legoesm/*` is gone at origin/main**: the src→packages migration is
  complete. Layout is now `packages/<pkg>/legoesm/...` with packages:
  `core`, `ocean`, `coupler`, `atmosphere`, `land`, `ice`, `ml`, `tools`.
  Notably `legoesm.driver.*` moved to `packages/coupler/legoesm/driver/`
  (`config.py`, `coupled_config.py`, `model_driver.py`); `legoesm.ocean.scm`
  is at `packages/ocean/legoesm/ocean/scm.py`; parallel modules at
  `packages/core/legoesm/parallel/`. The `packages/` refactor already
  existed at the pin — what changed since is that the `src/` tree was
  emptied. Any code path referencing `$LEGOESM_DIR/src` or importing from
  the source tree directly breaks.
- **`scripts/run/run_omip_core2.py`: 1,236 → 11,095 lines** (249 commits,
  +10,173/−314). Upstream did **not** adopt the patch-002 flags
  (`--synthetic-forcing`, `--forcing-scale`, `--days` — only a comment about
  a synthetic fallback exists). `scripts/run/run_omip_core2_mpi.py` (created
  by our patch 003) still does not exist upstream, but new upstream runners
  appeared in `scripts/run/` (`run_omip.py`, `run_omip_cross_grid.sh`,
  several `*.sbatch`) — an upstream MPI path may now supersede patch 003.

## 1. Procedure (unchanged in shape, bigger in blast radius)

```bash
cd legoESM-ocean-runners
bash scripts/sync_legoesm.sh --tag --push
```

or, via opencode, the `lego-world-sync-runners` skill. Reminders:

- The pin write is atomic and validated; tag naming
  `legoesm-<hash12>-<YYYYMMDD>` with letter suffixes on collision.
- **Template validation does NOT cover patches** — run
  `scripts/apply_patches.sh --check` before tagging; a dead patch tags green
  and breaks every dependent run at init time.
- **`--tag-only` validates structure only (`--skip-imports`)** — after any
  fix, gate with `sync_legoesm.sh --check-only` (full imports) before
  tagging; and it never commits the pin file — commit it yourself, then
  `--tag-only`, then `git push origin main --tags`.
- **Every reproducibility-affecting change needs a `legoesm-*` tag** — CI
  fails pushes to `main` without one. Runner-only changes use
  `sync_legoesm.sh --tag-only` (after `--check-only`).
- `legoESM_version.txt.override` (git-ignored) exists for feature-branch
  testing — do not let one leak into a commit.

## 2. Expect these to break (checked against origin/main)

1. **Patches 002/003 are dead against current main.** Plan to regenerate
   both, or drop them:
   - patch 002 (modifies `run_omip_core2.py`): first read the new file's
     argparse — equivalent flags may exist under other names; re-derive
     what is genuinely missing.
   - patch 003 (adds `run_omip_core2_mpi.py`): check whether the new
     upstream OMIP/MPI scripts supersede it; if not, port it (it imports
     `legoesm.parallel.distributed` / `legoesm.parallel.latlon_mpi`, both
     still present in `packages/core/legoesm/parallel/`).
   - Prefer **upstreaming** recurring patches over maintaining them.
2. **Import surface**: `scripts/validate_templates.py` imports
   `legoesm.driver.config`, `legoesm.driver.model_driver`,
   `legoesm.ocean.state`, `legoesm.ocean.physics`. Verify all resolve
   after `uv sync` in the new packages layout (driver → coupler package).
3. **Ocean SCM API**: `runners/run_ocean_scm.py` builds
   `OceanColumnModel.create(...)` from `legoesm.ocean.scm` with physics
   config classes. The ocean package churned heavily since the pin
   (NEMO-faithful TKE, etc.) — expect signature/config drift; the 1d
   template runs are the fastest probe.
4. **No more source-tree imports**: `resolve_legoesm_path()` and machine
   `env_setup` must not reference `$LEGOESM_DIR/src`; legoESM must be
   *installed* (`cd ../legoESM && uv sync`).
5. **Template-facing config schema**: grid types, modes, and config fields
   may have changed upstream; `lego-validate` is the gate — expect template
   edits, not just pin bumps.
6. Read the upstream **v1.0.0 CHANGELOG deprecations** before starting
   (e.g. removed schemes, renamed flags, new required config keys).

## 3. Chain integrity and per-machine rollout

- `runner_tag = untagged` in any `experiment.tag` = broken reproducibility
  chain; re-tag and `bin/run-experiment record` after re-init.
- After the pin bump, **every machine's environment must be re-synced**:
  - macbook: `legoESM/.venv` → `uv sync` / `pip install -e ".[dev]"`.
  - ige-calcul1: `/tmp/legoesm-venv` is **ephemeral** (wiped on reboot);
    re-run `bash ~/lego-world/setup_gpu_venv.sh` after the upgrade and
    after each reboot; verify `jax[cuda12]` still matches the new pin.
- Smoke ladder (cheapest first): 1d SCM templates → 2D/3D idealized →
  `omip_tripole` 5-day synthetic-forcing run → re-run the mpi-scaling
  series (`--scan-block` remains unsupported in MPI mode). Only then
  resume production plans (orca1-nemo-comparison Phase 0 on calcul1).
- Use the `lego-world-experiments` opencode skill's **sync** operation to roll out:
  local push → per-machine pull → legoESM checkout of the new pin →
  `scripts/apply_patches.sh --check` → remote `bin/check-workspace` green.

## 4. Repo hygiene to fold into the same pass

- `project_status.md`: remove stale rows (`2d/williamson_test2`,
  `held_suarez`, `rce_mip`, `amip` — deleted upstream/in-repo but still
  listed), refresh per-template test statuses after re-validation, record
  the new pin + tag.
- Fix the two known code quirks while touching the runners:
  - generated `run.sh` checks data with an undefined `$CONFIG_TEMPLATE`
    and a relative `scripts/` path (fragile under `set -euo pipefail`);
  - `scripts/reproduce.py --run` calls `init_experiment.py` without the
    now-required `--output-dir`.
- `data_catalog.yaml`: every `sha256` is `pending` — register real hashes
  (`fetch_data.py verify <id>`) while you are in there.
- Experiments repo side:
  - machine YAML ↔ how-to sync rule applies to any `env_setup` change;
  - AGENTS.md §8 agent duty "Do NOT run `bin/run-experiment init`" needs
    updating for ssh-relayed execution (the `lego-world-experiments` skill's relay
    policy);
  - fix series status drift (e.g. `reports/2026-06-01-mpi-scaling/
    series.yaml` still `planned` while its member runs are completed/failed);
  - record the upgrade itself as a note in `notes.md` of the smoke run.

## 5. Suggested order

1. Skim the v1.0.0 CHANGELOG deprecations; update clone remotes to
   `leap-stc/legoESM`.
2. `sync_legoesm.sh` (no tag) in a scratch state → fix imports/validation →
   regenerate (or drop) patches 002/003 → fix templates →
   `sync_legoesm.sh --check-only` (full-import validation) →
   `scripts/apply_patches.sh --check` → commit the pin
   (`git add legoESM_version.txt && git commit -m "chore: update legoESM pin
   to <hash>"`) → `sync_legoesm.sh --tag-only` → `git push origin main --tags`.
3. One laptop smoke end-to-end (declare → init → run → record) to confirm
   the chain is green before any machine sees the new pin.
4. Roll out via the `lego-world-experiments` skill to ige-calcul1 (venv re-sync +
   `check-workspace` + smoke).
5. **Onboard jean-zay / dahu / bigfoot AFTER the version sync lands** — new
   machines then start at the new pin and never need a second re-sync.
