# legoESM-ocean-runners

Experiment templates, runners, and reproducibility tools for ocean simulations with [legoESM](https://github.com/gentine/legoESM).

## Repository Structure

```
legoESM-ocean-runners/
├── templates/                    # Experiment templates (YAML, version-controlled)
│   ├── 1d/                       #   Single-column / SCM experiments
│   ├── 2d/                       #   Barotropic / shallow-water experiments
│   ├── 3d_idealized/             #   Idealized 3D ocean & atmosphere tests
│   ├── 3d_realistic/             #   Realistic configurations (OMIP, AMIP, coupled)
│   ├── global_ocean/             #   Global ocean experiments
│   └── ml_aimip/                 #   ML/AIMIP configurations
├── runners/                      # Python runners (shared execution logic)
│   ├── run_experiment.py         #   Generic experiment runner (init/run/tag)
│   ├── run_ocean_test_matrix.py  #   Cross-product ocean test suite
│   └── run_coupled.py            #   Coupled ESM runner
├── scripts/                      # CLI utilities
│   ├── init_experiment.py        #   Create experiment directory from template
│   ├── generate_tag.py           #   Generate reproducibility tag files
│   ├── validate_templates.py     #   Validate templates against legoESM
│   ├── apply_patches.sh          #   Apply patches to legoESM checkout
│   └── sync_legoesm.sh           #   Update pinned legoESM version
├── experiments/                  # Instantiated experiments (git-ignored)
├── machines/                     # Machine-specific configs (secrets git-ignored)
├── patches/                      # Pre-merge patches for legoESM
├── .github/workflows/ci.yml      # CI: validate templates against latest legoESM
├── legoESM_version.txt           # Pinned legoESM commit
└── pyproject.toml                # Project metadata and dependencies
```

## Quick Start

### Prerequisites

- Python 3.10+
- JAX installed (`pip install jax jaxlib`)
- legoESM checked out at `../legoESM` (or set `$LEGOESM_DIR`)

### Initialize an Experiment

```bash
# From a template (e.g., baroclinic gyre)
python scripts/init_experiment.py 3d_idealized/baroclinic_gyre --name my_gyre

# With overrides
python scripts/init_experiment.py 3d_idealized/baroclinic_gyre \
    --name gyre_high_res \
    -o grid.resolution=128x256 \
    -o ocean.A_h=1e6 \
    -o time.duration_days=730

# Then run
cd experiments/my_gyre
bash run.sh
```

### Run the Ocean Test Matrix

```bash
# Quick smoke tests for all 2D and 3D idealized experiments
python -m runners.run_ocean_test_matrix --categories 2d 3d_idealized --quick

# Specific grid types only
python -m runners.run_ocean_test_matrix --grid-types latlon --dry-run
```

### Validate Templates

```bash
# Validate all templates (structure only, no legoESM needed)
python scripts/validate_templates.py --skip-imports --verbose

# Full validation with legoESM import checks
python scripts/validate_templates.py --legoesm-dir /path/to/legoESM
```

## Template System

### Template Format

Templates are YAML files that describe experiments in a mode-aware way. Each template specifies:

| Section | Purpose |
|---------|---------|
| `experiment` | Name, mode (e.g., `3d_ocean`), description |
| `grid` | Grid type, resolution, vertical levels |
| `ocean` / `atmosphere` | Physics and numerics configuration |
| `domain` | Basin geometry, boundaries, bathymetry |
| `physics` | Vertical mixing, surface forcing, bottom drag |
| `initial_conditions` | IC parameters |
| `time` | Duration, timestep |
| `output` | Diagnostics and checkpoint intervals |

### Experiment Modes

| Mode | Description | Config Target |
|------|-------------|---------------|
| `ocean_scm` | Single-column ocean | `OceanConfig` (1D) |
| `barotropic_ocean` | 2D barotropic tests | Barotropic config |
| `3d_ocean` | Idealized 3D ocean | `LatLonCGridOceanConfig` / `OceanConfig` |
| `3d_ocean_realistic` | Realistic 3D ocean (OMIP) | `LatLonCGridOceanConfig` |
| `atmosphere_only` | Atmosphere-only (Held-Suarez, AMIP) | `ExperimentConfig` |
| `atmosphere_only_aimip` | AIMIP ML physics | `ExperimentConfig` |
| `coupled` | Coupled ESM | `ExperimentConfig` + `CoupledConfig` |

### Available Templates

**1D:**
- `1d/ocean_scm` — Single-column rest state with KPP

**2D:**
- `2d/barotropic_gyre` — Wind-driven barotropic gyre
- `2d/stommel_gyre_tracer` — Stommel gyre with tracer
- `2d/inertia_gravity_wave` — Inertia-gravity wave test
- `2d/williamson_test2` — Williamson shallow water test case 2

**3D Idealized:**
- `3d_idealized/baroclinic_gyre` — Wind-driven baroclinic instability
- `3d_idealized/lock_exchange` — Density-driven lock exchange
- `3d_idealized/overflow` — Dense water overflow down slope
- `3d_idealized/eady_instability` — Eady baroclinic instability
- `3d_idealized/phillips_two_layer` — Two-layer QG instability
- `3d_idealized/acc_channel` — ACC with topographic ridge
- `3d_idealized/dino` — DINO diabatic ocean basin
- `3d_idealized/isomip_plus` — Ice shelf-ocean interaction
- `3d_idealized/geostrophic_adjustment` — Geostrophic adjustment
- `3d_idealized/held_suarez` — Held-Suarez atmosphere
- `3d_idealized/rce_mip` — Radiative-convective equilibrium

**3D Realistic:**
- `3d_realistic/omip_jra55` — OMIP forced by JRA55-do
- `3d_realistic/amip` — AMIP atmosphere-only
- `3d_realistic/coupled_aquaplanet` — Coupled aquaplanet
- `3d_realistic/coupled_slab` — Coupled slab ocean
- `3d_realistic/coupled_full` — Fully coupled ESM

**Global Ocean:**
- `global_ocean/global_overturning` — Global overturning circulation
- `global_ocean/neverworld2_lite` — Neverworld2 benchmark
- `global_ocean/omip_global` — Production-resolution OMIP
- `global_ocean/omip_cubed_sphere` — OMIP on cubed-sphere

**ML/AIMIP:**
- `ml_aimip/aimip_classical` — Classical physics AIMIP
- `ml_aimip/aimip_column_nn` — Per-column MLP physics
- `ml_aimip/aimip_sfno` — SFNO global emulator

## Reproducibility Tags

Every initialized experiment produces an `experiment.tag` file in INI format:

```ini
[experiment]
name = baroclinic_gyre
template = 3d_idealized/baroclinic_gyre
mode = 3d_ocean
created = 2026-05-29T14:30:00+00:00

[legoESM]
ref = main
commit = c78680b839de
patches = 

[model]
configuration = 3d_ocean
grid_type = latlon
resolution = 64x128
nlev = 50

[run]
duration_days = 365
dt_seconds = 1800

[machine]
hostname = my-workstation
machine_config = default

[reproducibility]
config_hash = sha256:abcdef1234567890
legoesm_ref = main
python_version = 3.12.3
jax_version = 0.4.35
```

These tag files are intended to be archived alongside experiment output in a separate archive repository.

## Version Strategy

This repository always targets the **latest legoESM main branch**. Past compatibility states are preserved via **git tags**, enabling exact reproduction of any experiment ever run.

### How it works

| Concept | Mechanism |
|---------|-----------|
| **Current version** | `legoESM_version.txt` pins the exact legoESM commit that `main` templates are validated against |
| **Past versions** | Git tags (`legoesm-<hash>-<date>`) capture the repo state each time the pin is updated |
| **Reproducibility** | Every `experiment.tag` file records `runner_tag`, tying an experiment to a specific repo tag |
| **Feature branches** | Local `.override` files + patches for temporary legoESM branches (never committed) |

### Updating the pinned version

```bash
# Sync to latest legoESM main, validate, and create a tag on success:
bash scripts/sync_legoesm.sh --tag

# Sync to a specific legoESM branch (local override, no tag):
bash scripts/sync_legoesm.sh feature/ocean-btr
```

When `--tag` is used, `sync_legoesm.sh` will:
1. Update `legoESM_version.txt` to the new commit
2. Run `validate_templates.py` against the new version
3. If validation passes: commit, create tag `legoesm-<hash>-<date>`, push
4. If validation fails: report failures, hold for manual fixes

### Viewing and using tags

```bash
# List all compatibility tags
git tag -l 'legoesm-*'

# Find tags from a specific date range
git tag -l 'legoesm-*202605*'

# Checkout a past compatibility state
git checkout legoesm-c78680b-20260529
```

### Reproducing a past experiment

Every experiment produces an `experiment.tag` file that records the exact repo tag:

```ini
[reproducibility]
runner_tag = legoesm-c78680b-20260529    # ← repo tag
legoesm_ref = main
```

To reproduce:

```bash
# Automatic: reads experiment.tag and reproduces the environment
python scripts/reproduce.py experiments/my_gyre/experiment.tag

# Manual: checkout the tag and corresponding legoESM version
git checkout legoesm-c78680b-20260529
cd ../legoESM && git checkout c78680b839de
cd ../legoESM-ocean-runners && bash scripts/apply_patches.sh
```

### Using a feature branch locally

For development with a legoESM feature branch (never committed to the repo):

```bash
# 1. Create a local override (git-ignored)
echo "ref: feature/ocean-partial-cells" > legoESM_version.txt.override
echo "commit: $(cd ../legoESM && git rev-parse HEAD)" >> legoESM_version.txt.override

# 2. Create a patch for your feature
cd ../legoESM && git diff main > ../legoESM-ocean-runners/patches/001-my-feature.patch
bash scripts/apply_patches.sh

# 3. When the feature is merged upstream, clean up:
rm legoESM_version.txt.override patches/001-my-feature.patch
bash scripts/sync_legoesm.sh --tag
```

## Patches

Patches in `patches/` are applied on top of the pinned legoESM version. They allow running experiments with features not yet merged into legoESM main.

```bash
# Create a patch
cd ../legoESM && git diff main > ../legoESM-ocean-runners/patches/001-my-feature.patch

# Apply patches
bash scripts/apply_patches.sh

# Check patches apply cleanly
bash scripts/apply_patches.sh --check

# Reverse patches
bash scripts/apply_patches.sh --reverse
```

Remove patches once they are merged upstream.

## Machine Configurations

`machines/` contains per-cluster YAML configs for paths, scheduler settings, and device selection. Copy `_template.yaml` and customize for your machine:

```yaml
scheduler: slurm
scheduler_partition: gpu
scheduler_account: project123
devices: gpu
n_devices: 4
precision: mixed
data_dir: /scratch/project123/legoesm-data
output_root: /scratch/project123/output
env_setup:
  - "module load python/3.12"
  - "conda activate legoesm"
```

Machine files containing secrets should be added to `.gitignore`.

## Data Management

### Overview

Experiment templates that require external data files (NetCDF grids, forcings, bathymetry) declare their dependencies in a `requires` field. The `data_catalog.yaml` file is the single source of truth for all downloadable data.

### Catalog Structure

Each entry in `data_catalog.yaml` specifies:

| Field | Description |
|-------|-------------|
| `description` | Human-readable description |
| `path` | Relative path under `DATA_ROOT` |
| `url` | Direct download URL (if public) |
| `access` | `public`, `globus`, `institutional`, or `derived` |
| `sha256` | Checksum (or `pending` until computed) |
| `size_mb` | Approximate file size |
| `format` | `NetCDF4`, `Zarr`, etc. |
| `variables` | Key NetCDF variable names |
| `citation` | Academic citation |

### Template Requires

Each template YAML includes a `requires` list referencing catalog IDs:

```yaml
# templates/3d_realistic/omip_jra55.yaml
experiment:
  name: omip_jra55
  mode: 3d_ocean_realistic

requires:
  - etopo1_1deg
  - woa18_annual_t
  - woa18_annual_s
  - jra55_do_ryf
  - eorca1_mesh
```

Idealized experiments have `requires: []` since they use analytical forcings.

### Fetching Data

```bash
# List data required by a template
python scripts/fetch_data.py list 3d_realistic/omip_jra55 -v

# Check what's missing locally
python scripts/fetch_data.py check 3d_realistic/omip_jra55

# Download all required data
python scripts/fetch_data.py fetch 3d_realistic/omip_jra55

# Download a specific file
python scripts/fetch_data.py fetch-file etopo1_1deg

# Verify a downloaded file
python scripts/fetch_data.py verify etopo1_1deg

# List all catalog entries
python scripts/fetch_data.py list-all
```

### Data Root

The `DATA_ROOT` directory is resolved in order:

1. `--data-dir` CLI argument
2. `LEGOESM_DATA_DIR` environment variable
3. `./data` (relative to the repo)

Machine configs can set `data_root` to point to shared storage on HPC systems.

### Data That Requires Manual Setup

Some datasets cannot be auto-downloaded:

| ID | Access | Instructions |
|----|--------|-------------|
| `jra55_iaf_raw` | Globus | Use `scripts/download_jra55_iaf.py` |
| `jra55_do_ryf` | Derived | Run `scripts/prepare_omip_forcing.py` after downloading raw JRA55 |
| `era5_monthly` | Institutional | Register at CDS, download via CDS API |
| `cmip6_aerosol` | Institutional | Download from ESGF |
| `gebco_2023` | Institutional | Download from GEBCO website |

The `fetch_data.py` tool will print manual instructions for these entries.

## CI

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs on every push/PR and weekly:

1. Validates all template YAML structure
2. Checks that templates parse correctly against the pinned legoESM
3. Runs a smoke test with one template
4. On weekly schedule, checks if legoESM has been updated

## License

MIT License. See [LICENSE](LICENSE) for details.