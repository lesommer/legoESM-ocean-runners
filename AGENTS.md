# AGENTS.md

This document explains the purpose, philosophy, boundaries, and working conventions of this repository for AI coding agents.

## 1. Purpose

This repository stores **experiment templates, runners, and reproducibility tools** for running ocean (and coupled) simulations with [legoESM](https://github.com/gentine/legoESM). It is not the model itself — legoESM lives in a separate repository and is referenced by a pinned commit in `legoESM_version.txt`.

**Reproducibility is the core guiding principle.** Every experiment must be reconstructable from its provenance records. The full chain `template + overrides → config.yaml → experiment.tag → reproduce.py` must be unbroken. If an experiment cannot be reproduced from what is committed, the system has failed.

The repo serves three goals (in priority order):
1. **Reproducibility** — make experiments reconstructable via tag files that capture every parameter, version, and machine detail
2. Provide version-controlled experiment configurations that stay in phase with the latest legoESM
3. Manage external data dependencies (grids, forcings, bathymetry) declaratively without storing the data itself

## 2. Philosophy

**Reproducibility contract.** The following chain must be unbroken for every experiment:

```
legoESM_version.txt  ←pins model commit→  git tag (legoesm-<hash>-<date>)
                                             ↕ validated by CI
template + overrides  →  config.yaml  →  experiment.tag  →  reproduce.py
```

- `legoESM_version.txt` + git tags are the provenance anchor. Every `experiment.tag` records the `runner_tag` that can reproduce the exact software environment.
- Every tag must be validated (templates pass `lego-validate`) before creation.
- `experiment.tag` is the permanent reproducibility record — never delete or modify it after creation.
- `runner_tag` in `experiment.tag` must resolve to a tag in this repo. If it reads `untagged`, the reproducibility chain is broken.
- Never change `legoESM_version.txt` without creating a corresponding tag.

**Reproducibility verification checklist.** Before considering an experiment complete, verify:
- [ ] `config.yaml` matches `run.yaml` + overrides
- [ ] `experiment.tag` has a valid `runner_tag` (not `untagged`)
- [ ] `experiment.tag` legoESM commit matches `legoESM_version.txt`
- [ ] The tag recorded in `experiment.tag` exists in this repo and points to a validated commit
- [ ] `reproduce.py` can reconstruct the software environment from `experiment.tag`

**Declarative, not imperative.** Experiment templates are YAML files that describe *what* to run, not *how* to run it. The runners translate these declarations into legoESM configuration objects at runtime.

**Separation of concerns.** This repo handles configuration and orchestration only. Three hard boundaries exist:
- **legoESM** (model code) → pinned, never edited here; modifications go through `patches/`
- **Data files** (NetCDF/Zarr) → never stored here; cataloged in `data_catalog.yaml`, fetched by `scripts/fetch_data.py`
- **Experiment Archives** (output) → stored in a separate archive repo; this repo only produces `experiment.tag` files that describe what was run

**Version control as reproducibility contract.** `main` always targets the latest legoESM. Git tags (`legoesm-<hash>-<date>`) mark validated compatibility points — every time `legoESM_version.txt` is updated and templates pass validation, a tag is created. Past experiments are reproduced by checking out the tag recorded in their `experiment.tag` file. Never create branches for different legoESM versions; use tags instead.

**Machine-agnostic templates.** Templates contain no machine-specific paths or scheduler settings. Machine configuration lives in `machines/*.yaml` (git-ignored except `_template.yaml`).

## 3. Repository Map

```
templates/           YAML experiment configurations (the core of this repo)
  1d/                 Single-column / SCM experiments
  2d/                 Barotropic / shallow-water experiments
  3d_idealized/       Idealized 3D basins and process studies
  3d_realistic/       OMIP, AMIP, coupled ESM configurations
  global_ocean/       Global ocean at various resolutions
  ml_aimip/           ML/AIMIP experiment variants

data_catalog.yaml    Single source of truth for external data files
runners/             Python package: experiment init, run, tag generation
scripts/             CLI tools: fetch_data, validate_templates, init_experiment, etc.
machines/            Machine configs (only _template.yaml is committed)
patches/             Pre-merge patches for legoESM
experiments/         Instantiated experiments (git-ignored)
legoESM_version.txt  Pinned legoESM commit hash
```

## 4. Boundaries

### What this repo IS
- Experiment configurations and their reproducibility metadata
- Runners that translate YAML → legoESM config objects
- A data catalog describing where to get external files
- CI workflows that validate templates against the pinned legoESM

### What this repo is NOT
- **Not the model.** legoESM source code is never edited here. If a change to legoESM is needed, create a patch in `patches/` — never edit `../legoESM` directly.
- **Not a data store.** No NetCDF, Zarr, or large binary files are committed. The `data/` directory is git-ignored. Use `scripts/fetch_data.py` to download.
- **Not an archive.** Experiment outputs go to a separate archive repository. This repo only produces `experiment.tag` files that describe what was run.
- **Not a fork of legoESM.** The relationship is `patches/ → apply to ../legoESM`. Patches are removed once merged upstream.

## 5. Working Conventions

### Template Format

Every template YAML must have:
```yaml
experiment:
  name: <string>
  mode: <one of: ocean_scm, barotropic_ocean, 3d_ocean, 3d_ocean_realistic, atmosphere_only, atmosphere_only_aimip, coupled>
  description: <string>

requires:          # list of data_catalog.yaml IDs; empty list for idealized configs
  - <file_id>

grid:
  type: <one of: latlon, cubed_sphere, gaussian, mpas, scm>
  resolution: <int or string like "64x128">
  n_levels: <int>   # or nlev for ocean configs

ocean: ...         # or atmosphere: ... or coupled: ... depending on mode
time:
  duration_days: <int>    # or duration_hours for short tests
```

### Mode → Config Class Mapping

Templates are mode-aware. The runner dispatches based on `experiment.mode`:

| Mode | legoESM Config Class |
|------|---------------------|
| `ocean_scm` | Ocean config (single column) |
| `barotropic_ocean` | Barotropic config |
| `3d_ocean` | `LatLonCGridOceanConfig` / `OceanConfig` / `MPASOceanConfig` / `SpectralOceanConfig` (depends on `grid.type`) |
| `3d_ocean_realistic` | Same as `3d_ocean` but with realistic bathymetry and forcing |
| `atmosphere_only` | `ExperimentConfig` |
| `atmosphere_only_aimip` | `ExperimentConfig` with AIMIP variant |
| `coupled` | `ExperimentConfig` + `CoupledConfig` (selected by `coupled.preset`) |

For field-level details, read the legoESM source code directly (`../legoESM/src/legoesm/driver/config.py` for atmosphere, `../legoESM/src/legoesm/ocean/state.py` for ocean).

### Data Dependencies

Templates declare `requires: [<file_id>, ...]` where each ID references an entry in `data_catalog.yaml`. The catalog contains download URLs, checksums, sizes, access levels, and citations.

- **Idealized experiments** have `requires: []` (all forcings are analytical)
- **Realistic experiments** list the data files they need (bathymetry, WOA18, JRA55, etc.)
- **Access levels**: `public` (direct download), `globus` (requires Globus), `institutional` (requires registration), `derived` (must be built from other data)

### Patches

If an experiment needs a legoESM feature not yet in main:
1. Work in `../legoESM` on a feature branch
2. Create a patch: `cd ../legoESM && git diff main > ../legoESM-ocean-runners/patches/NNN-description.patch`
3. Patches are numbered and applied in order by `scripts/apply_patches.sh`
4. Remove the patch once the feature is merged into legoESM main

### Tag Files

Every initialized experiment produces an `experiment.tag` INI file with:
- `[experiment]` — name, template, mode, creation timestamp
- `[legoESM]` — pinned ref, commit hash, patches applied
- `[model]` — configuration, grid type, resolution, vertical levels
- `[run]` — duration, timestep
- `[data]` — data_root, requires list, resolved file paths
- `[machine]` — hostname, machine config
- `[reproducibility]` — config hash, runner_tag (git tag in THIS repo), legoESM ref, Python/JAX versions

These tag files are intended to be archived alongside experiment output in a separate archive repository.

## 6. What Agents Should Do

### Add a new experiment template
1. Check if an existing template in the same category is close to what's needed
2. **Ask the user for confirmation** before creating a new template
3. Create the YAML in the appropriate `templates/<category>/` directory
4. Include `experiment`, `requires`, `grid`, and `time` sections at minimum
5. Use a valid `mode` (see table above)
6. Reference data catalog IDs in `requires` — never invent new IDs without adding them to `data_catalog.yaml`
7. Run `python scripts/validate_templates.py --skip-imports` to verify
8. Update the test count in `tests/test_templates.py` if needed

### Fix a broken template
1. Run `python scripts/validate_templates.py --skip-imports --verbose` to identify the issue
2. Fix the YAML — common issues: invalid mode, missing required sections, wrong requires IDs
3. If the template broke because of a legoESM API change, update `legoESM_version.txt` and create a patch if needed

### Add a new data file to the catalog
1. Add an entry to `data_catalog.yaml` with all required fields: `description`, `path`, `access`, `format`, `size_mb`
2. For public URLs, add `url` and `sha256` (compute with `python scripts/fetch_data.py verify <id>` after downloading)
3. For restricted data, set `access: institutional` or `access: globus` and add `instructions`
4. For derived data, set `access: derived` and add `build_from` and `build_instructions`

### Update legoESM version
1. Run `bash scripts/sync_legoesm.sh --tag` to update the pin and create a compatibility tag
2. If validation passes: a tag `legoesm-<hash>-<date>` is created automatically
3. If validation fails: fix the templates, then commit and tag manually: `git tag "legoesm-$(grep '^commit:' legoESM_version.txt | cut -d: -f2 | tr -d ' ' | cut -c1-12)-$(date +%Y%m%d)"`

### Reproduce a past experiment
1. Read the `experiment.tag` file: find `runner_tag` in the `[reproducibility]` section
2. Checkout that tag: `git checkout legoesm-c78680b-20260529`
3. Or use the reproduce script: `python scripts/reproduce.py path/to/experiment.tag`
4. The script checks out the matching legoESM commit, applies patches, and verifies data availability

### Use a feature branch locally (temporary, never committed)
1. Create `legoESM_version.txt.override` with the branch name and commit (git-ignored)
2. Create a patch: `cd ../legoESM && git diff main > ../legoESM-ocean-runners/patches/001-my-feature.patch`
3. Apply patches: `bash scripts/apply_patches.sh`
4. When merged upstream: remove the override and patch, run `sync_legoesm.sh --tag`

## 7. What Agents Must NOT Do

- **Never edit `../legoESM/` directly.** If legoESM needs changes, create a patch in `patches/`.
- **Never commit data files** (NetCDF, Zarr, large binaries) to this repository. The `data/` directory is git-ignored for a reason.
- **Never commit machine-specific configs** that contain secrets or absolute paths. Only `_template.yaml` is committed; actual machine files are git-ignored.
- **Never hardcode absolute paths** in templates or runners. Use `$LEGOESM_DATA_DIR`, `$LEGOESM_DIR`, or relative paths.
- **Never modify `data_catalog.yaml` checksums** without verifying them against actual downloaded files.
- **Never remove the `requires` field** from a template. Even idealized templates have `requires: []` — this is intentional and validated by CI.
- **Never bypass validation.** Always run `python scripts/validate_templates.py` after modifying templates.
- **Never create branches for different legoESM versions.** Use tags (`legoesm-<hash>-<date>`) for reproducibility. The `main` branch always tracks the latest legoESM.
- **Never modify `legoESM_version.txt` without tagging.** Every pin update should be accompanied by a `legoesm-<hash>-<date>` tag after validation passes.

## 8. Key File Locations

| What | Where |
|------|-------|
| Experiment templates | `templates/<category>/<name>.yaml` |
| Data catalog | `data_catalog.yaml` |
| Pinned legoESM version | `legoESM_version.txt` |
| Compatibility tags | `git tag -l 'legoesm-*'` |
| Reproduction tool | `scripts/reproduce.py` |
| Version sync + tagging | `scripts/sync_legoesm.sh --tag` |
| Data fetch tool | `scripts/fetch_data.py` |
| Template validator | `scripts/validate_templates.py` |
| Experiment runner | `runners/run_experiment.py` |
| Ocean test matrix | `runners/run_ocean_test_matrix.py` |
| Patches | `patches/*.patch` |
| Machine config template | `machines/_template.yaml` |
| Tests | `tests/test_templates.py` |
| CI workflow | `.github/workflows/ci.yml` |

## 8.5 CI Setup (Private legoESM Access)

CI is split into two tiers:

- **Tier 1** (always runs): YAML structure validation, catalog checks, requires references — no legoESM access needed
- **Tier 2** (requires PAT): Full validation against legoESM, smoke test — only runs when the `LEGOESM_ACCESS_TOKEN` secret is set

Since legoESM is a private repository, you must set up a **fine-grained Personal Access Token** for Tier 2:

1. GitHub → Settings → Developer settings → Fine-grained tokens → New token
2. Give it **Contents: Read** permission on `gentine/legoESM`
3. Add the token as repository secret `LEGOESM_ACCESS_TOKEN` in `lesommer/legoESM-ocean-runners` → Settings → Secrets → Actions

If the secret is missing, Tier 2 is skipped. The scheduled `sync-check` job also needs the token to query the legoESM remote.

## 9. Common Workflows

### "I want to run baroclinic_gyre on my laptop"
```bash
# 1. Check data availability (idealized = no data needed)
python scripts/fetch_data.py check 3d_idealized/baroclinic_gyre

# 2. Initialize the experiment
python scripts/init_experiment.py 3d_idealized/baroclinic_gyre --name my_gyre

# 3. Run it
cd experiments/my_gyre && bash run.sh
```

### "I want to run OMIP on an HPC cluster"
```bash
# 1. Fetch needed data
python scripts/fetch_data.py fetch 3d_realistic/omip_jra55 --data-dir /scratch/data

# 2. Create a machine config
cp machines/_template.yaml machines/perlmutter.yaml
# Edit perlmutter.yaml with SLURM settings and data_root

# 3. Initialize with machine override
python scripts/init_experiment.py 3d_realistic/omip_jra55 --name omip_run --machine perlmutter

# 4. Submit
cd experiments/omip_run && sbatch run.sh
```

### "I need a legoESM feature that isn't in main yet"
```bash
# 1. Work in ../legoESM on a feature branch
cd ../legoESM && git checkout -b feature/my-feature

# 2. Develop and test

# 3. Create a local override (never committed)
echo "ref: feature/my-feature" > legoESM_version.txt.override
echo "commit: $(cd ../legoESM && git rev-parse HEAD)" >> legoESM_version.txt.override

# 4. Create a patch
cd ../legoESM && git diff main > ../legoESM-ocean-runners/patches/001-my-feature.patch

# 5. Apply patches to your legoESM checkout
cd ../legoESM-ocean-runners && bash scripts/apply_patches.sh

# 6. When done, remove override and patch
rm legoESM_version.txt.override patches/001-my-feature.patch
```

### "I need to reproduce a past experiment"
```bash
# Option A: Use the reproduce script (automatic)
python scripts/reproduce.py experiments/my_old_run/experiment.tag
# This checks out the right repo tag, legoESM commit, and applies patches.

# Option B: Manual reproduction
# 1. Read the experiment.tag to find the runner_tag
grep runner_tag experiments/my_old_run/experiment.tag
# runner_tag = legoesm-c78680b-20260529

# 2. Checkout that tag in this repo
git checkout legoesm-c78680b-20260529

# 3. Checkout the corresponding legoESM commit
cd ../legoESM && git checkout c78680b839de

# 4. Apply any patches listed in the tag
cd ../legoESM-ocean-runners && bash scripts/apply_patches.sh

# 5. Fetch data and run
python scripts/fetch_data.py check 3d_idealized/baroclinic_gyre
python scripts/init_experiment.py 3d_idealized/baroclinic_gyre --name reproduced_run
cd experiments/reproduced_run && bash run.sh
```

### "I want to update the pinned legoESM version"
```bash
# Sync to latest main, validate, and tag on success:
bash scripts/sync_legoesm.sh --tag

# If validation fails, fix templates first, then tag manually:
bash scripts/sync_legoesm.sh           # update the pin
python scripts/validate_templates.py   # check what broke
# ... fix templates ...
git commit -am "fix: update templates for new legoESM API"
git tag "legoesm-$(grep '^commit:' legoESM_version.txt | cut -d: -f2 | tr -d ' ' | cut -c1-12)-$(date +%Y%m%d)"
git push --tags
```