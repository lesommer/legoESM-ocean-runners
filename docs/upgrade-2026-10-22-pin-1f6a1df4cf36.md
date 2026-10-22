# Pin bump 2026-10-22: 294495454a29 → 1f6a1df4cf36 (1252 commits, post-1.0.0)

Issue #8 Phase 3A close-out. Previous large-jump note: `upgrade-2026-10-v1.0.0-jump.md`.

## Summary

- **Old pin:** `294495454a2935acfce4360807a3a48ee3dfe0ef` (2026-10-11)
- **New pin:** `1f6a1df4cf36b78a6ab4f5602ba5e75795e78dae` (2026-10-22, upstream main HEAD)
- **Delta:** 1252 commits, all post-1.0.0 (`Unreleased` — no release boundary crossed)
- **Tag:** `legoesm-1f6a1df4cf36-20261022` (runners `324fb47`)
- Runners commit sequence: `b02d0d5` (patch surgery) + `324fb47` (pin).

## What upstream changed that mattered (verified pre-flight via GitHub API, confirmed at validation)

- **PR #2101 merged** (OMIP core2 short-run flags — contributed from our lane): `scripts/run/run_omip_core2.py` absorbed `--days` / `--synthetic-forcing` / `--forcing-scale`. → patch 002 dropped.
- **libm lazy-load landed upstream** (2026-10-19, with tests) for `transcendentals.py` + `ocean/forcing/nemo_fld_read.py`. → patch 001 dropped (superseded).
- **`config/templates/ocean/`: only `bench.yaml` changed** — maturity `experimental` → `structurally_validated`. Informational for the consistency gate (maturity is reported, never blocking).
- **Unchanged since the old pin:** `packages/ocean/.../recipe_map.py` (recipe gate quiet), `scripts/matrix/run_ocean_test_matrix.py` (matrix lanes + the IGW global-case defect unchanged), `scripts/run/run_bench.py` (bench lane stable).
- **Changed:** `scripts/run/run_dino.py` (2 commits) — dino lane re-verified green via the runners suite.
- **New upstream template categories** beyond `ocean/`: `2d/` (williamson SW), `3d_idealized/` (held_suarez, hydrostatic_gray), `global_ocean/` (omip_latlon, omip_latlon_kpp), `atmosphere/`, `sea_ice/`. **No stem overlaps** with runners-owned templates; the consistency gate's auto-discovery scans only `config/templates/ocean/`, so nothing fires. Registry parity holds (16 upstream ocean templates == 16 registered modes).
- **Pre-existing upstream test failures at the new pin** (not ours, present on clean main): `tests/unit/test_run_manifest.py::test_resolved_config_roundtrips_to_experiment_config`, `::test_write_then_read_roundtrips`, `::test_manifest_for_a_shipped_config` — `ExperimentConfig` equality assertions. Upstream issue candidate.

## Patch chain (003–006, names stable — no renumbering)

Pre-graduation `experiment.tag`s record `patch_sha256_<stem>` by name; renumbering would orphan them.

| Patch | Disposition |
|---|---|
| `001-libm-lazy-load.patch` | **Dropped** — superseded upstream |
| `002-omip-core2-extensions.patch` | **Dropped** — merged as #2101; `omip_tripole.yaml` `requires_patches` updated (003 stays) |
| `003-omip-core2-mpi.patch` | Kept; applies unchanged (new-file wrapper) |
| `004-runoff-file-override.patch` | Kept; applies unchanged |
| `005-bt-slow-depth-eval-decision90.patch` | Kept; applies unchanged |
| `006-manifest-runner-tag.patch` | **Regenerated** — only the CHANGELOG hunk moved (upstream's `Unreleased/Added` now carries the #2101 entry; both entries now listed); `restart.py` + test hunks re-apply unchanged. Stays until PR #2100 merges. |

## Environment / tooling notes

- **legoESM remote was the stale rename** `leap-stc/legoESM` → reset to canonical `https://github.com/climate-federation/legoESM.git` (CI already pointed at the canonical name).
- **venv re-sync:** `uv sync --extra dev` (workspace packages 1.0.0 → 1.0.1; a bare `uv sync` drops pytest/ruff — the `dev` extra is required for the runners-suite protocol that runs `../legoESM/.venv/bin/python -m pytest tests/test_templates.py`). jax 0.10.0, pytest 9.0.3.
- **Upstream git-ref collision:** upstream has branches `Jisu` (capital) and `jisu/land-p-model`; on case-insensitive macOS filesystems (APFS default) the fetched tracking refs collide, and with git 2.17 fetch fails outright ("cannot lock ref ... 'refs/remotes/origin/jisu' exists"). Workaround: narrowed the clone's fetch refspec to `+refs/heads/main:refs/remotes/origin/main` (this clone only consumes the pin target). Upstream hygiene candidate.
- The dirty-checkout caveat is unchanged: `sync_legoesm.sh` fast-forwards a CLEAN tree — clean/reset the patched checkout first (`git checkout -- . && git clean -fd`; patch content lives in `patches/`), then re-apply with `apply_patches.sh` after the bump.

## Verification (all green before tag)

- `sync_legoesm.sh` (staged, no tag): 23/23 templates full-import valid at the new pin; patch probe 4/4 clean → atomic pin write.
- `sync_legoesm.sh --check-only`: 23/23 (full imports, recipe + consistency gates).
- `python3 -m pytest tests/test_templates.py`: 228 passed, 3 skipped. `../legoESM/.venv/bin/python -m pytest tests/test_templates.py`: 231 passed (includes the env→manifest e2e against the pinned+patched legoESM).
- `render_readme_status.py --check`: up to date.
- `apply_patches.sh`: 003–006 applied cleanly to `1f6a1df4cf36` (local dirty-by-design state restored).
