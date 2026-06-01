# legoESM-ocean-runners

Experiment templates, runners, and reproducibility tools for ocean simulations with [legoESM](https://github.com/gentine/legoESM).

## Why use this repo?

Running legoESM directly means editing `scripts/run_omip.py` (3687 lines) by hand — no versioned configurations, no provenance trail, no way to reproduce past runs.

This repo gives you:

- **Named templates** — version-controlled YAML files instead of ad-hoc script edits
- **Reproducibility tags** — every run produces an `experiment.tag` capturing the exact software environment (legoESM commit, patches, Python/JAX versions)
- **One-command reproduction** — `reproduce.py` reconstructs any past experiment from its tag file

For managing personal experiment directories across machines, see [my-legoESM-ocean-experiments](https://github.com/lesommer/my-legoESM-ocean-experiments).

See [project_status.md](project_status.md) for what's currently implemented and tested.

## Run an experiment

### Idealized (no data needed)

```bash
# 1. Check data availability (idealized experiments need no data)
python scripts/fetch_data.py check 3d_idealized/baroclinic_gyre

# 2. Initialize (--output-dir is required)
python scripts/init_experiment.py 3d_idealized/baroclinic_gyre \
    --name my_gyre --output-dir ./my_gyre

# 3. Run
cd my_gyre && bash run.sh
```

### Global ocean / OMIP (requires data)

```bash
# 1. Fetch required data
python scripts/fetch_data.py fetch global_ocean/omip_tripole

# 2. Initialize
python scripts/init_experiment.py global_ocean/omip_tripole \
    --name orca1_phase0 --output-dir ./orca1_phase0

# 3. Run (or submit run.sh to your scheduler)
cd orca1_phase0 && bash run.sh
```

## Modify an experiment

Templates are the starting point. Override any parameter with dot-notation `-o` flags:

```bash
# Higher resolution and stronger lateral viscosity
python scripts/init_experiment.py 3d_idealized/baroclinic_gyre \
    --name gyre_hires --output-dir ./gyre_hires \
    -o grid.resolution=128x256 \
    -o ocean.A_h=1e6 \
    -o time.duration_days=730

# Change vertical mixing scheme
python scripts/init_experiment.py global_ocean/omip_jra55 \
    --name omip_kpp --output-dir ./omip_kpp \
    -o physics.vertical_mixing.scheme=kpp
```

## Reproduce an experiment

Every run produces an `experiment.tag` (INI format) recording the full software environment:

```ini
[legoESM]
ref = main
commit = 6056a0d0402968d952089209098c5990ed7d53fa

[reproducibility]
runner_tag = legoesm-6056a0d04029-20260530
python_version = 3.11.14
jax_version = 0.4.38
```

To reproduce:

```bash
python scripts/reproduce.py path/to/experiment.tag
```

This checks out the runner tag → checks out the legoESM commit → applies patches → verifies data.

## Available templates

| Category | Templates | Run status |
|----------|-----------|------------|
| `1d/` | `ocean_scm_convective`, `ocean_scm_ekman`, `ocean_scm_surface_heating`, `ocean_scm_kpp_wind`, `ocean_scm` | **Run-tested** |
| `global_ocean/` | `omip_tripole` | **5-day run completed** (CPU, idealized ICs, synthetic forcing; NEMO ICs cause cold-start blowup — use `--idealized-ic` for spinup; patch 001 + 002: NEMO-identical eORCA1 tripolar OMIP with domain_cfg grid, integrated forcing, Jerlov SW, SSS restoring, Dai-Trenberth runoff, NEMO-compatible output) |
| `global_ocean/` | `omip_jra55`, `omip_global`, `omip_cubed_sphere`, `global_overturning`, `neverworld2_lite` | Init-only |
| `2d/`, `3d_idealized/`, `coupled/` | See `templates/` | Init-only or structurally validated |

See [project_status.md](project_status.md) for the full status of every template.

## CLI tools

| Command | Description |
|---------|-------------|
| `python scripts/init_experiment.py` | Create experiment directory from template |
| `python scripts/validate_templates.py` | Validate templates against legoESM |
| `python scripts/generate_tag.py` | Generate reproducibility tag file |
| `python scripts/fetch_data.py` | Download/verify external data files |
| `python scripts/reproduce.py` | Reproduce experiment from its tag file |
| `bash scripts/sync_legoesm.sh --tag` | Update pinned legoESM version and tag |
| `bash scripts/apply_patches.sh` | Apply patches to legoESM checkout |

## Further reading

See [AGENTS.md](AGENTS.md) for full conventions, CI setup, data catalog schema, patch workflow, and version strategy.
