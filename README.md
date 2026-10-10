# legoESM-ocean-runners

Experiment templates, runners, and reproducibility tools for ocean simulations with [legoESM](https://github.com/climate-federation/legoESM).

## Why this repo exists

legoESM is a model repository. It ships the model itself, run scripts such as
`scripts/run/run_omip_core2.py` (a large command-line surface, plus a
`--config` YAML lane and a `legoesm run` entry point), versioned example
configurations under `config/`, a per-run `run_manifest.json` (resolved
configuration, config hash, final state digest), and `legoesm reproduce
--check` to re-run a manifest and bit-check the result.

That is enough to execute a single run on a single machine. A typical user,
however, wants to run *experiments*: a series of configured runs, across
several machines, revisited over months. Between the model and that workflow
there is a gap:

- **Named configurations.** The upstream `--config` lane is deliberately
  narrow: it applies only `ocean.*` fields, only on lat-lon C-grid lanes,
  and grid, mesh and most run controls remain command-line flags. There is
  no way to say "the baroclinic gyre experiment, at 128x256, for 2 years"
  once and then vary one parameter at a time.

- **Reproducibility across environments.** The manifest describes one run,
  but it cannot reconstruct an environment that involved features not yet
  merged into legoESM, and it carries no notion of *which* configuration
  template a run came from.

- **Data.** Realistic runs need grids, bathymetry, forcing and initial
  conditions. Upstream accepts a path to already-staged data; where the
  files come from, how they are verified, and how they are shared between
  machines is not upstream's concern.

- **Machines.** Clusters differ in schedulers, accounts, storage paths and
  GPU setup. Nothing upstream adapts a configuration to where it runs.

This repo fills that gap. It provides:

- **Templates** — 26 version-controlled YAML configurations across five
  modes (`ocean_scm`, `barotropic_ocean`, `3d_ocean`, `3d_ocean_realistic`,
  `coupled`), dispatched to the matching legoESM configuration classes, with
  dot-notation parameter overrides at init (`-o grid.resolution=128x256`).

- **A reproducibility chain anchored in git tags** — `legoESM_version.txt`
  pins the model commit, validated `legoesm-<hash>-<date>` tags mark
  compatibility points, and every run produces an `experiment.tag` whose
  `runner_tag` lets `scripts/reproduce.py` reconstruct the full environment:
  runner tag, legoESM commit, patches, data check. Upstream's manifest
  verifies a rerun's digest; this chain reconstructs the run.

- **A patch workflow** — `patches/` holds pre-merge changes that let
  templates use features before they land in legoESM main; patches are
  numbered, applied in order, and removed once merged upstream.

- **A data catalog** — `data_catalog.yaml` is the single source of truth for
  external files (URLs, checksums, sizes, access levels), and
  `scripts/fetch_data.py` checks, fetches and verifies them per machine.

- **Machine adaptation** — templates are machine-agnostic; machine
  configuration (scheduler, accounts, paths, environment) is passed at init
  via `--machine` and the generated `run.sh` matches the machine's scheduler
  (`slurm`, `oar`, pbs, lsf) or runs directly. SLURM machines get `#SBATCH`
  directives (submit with `sbatch run.sh`); OAR machines (GRICAD/CIMENT:
  bigfoot, dahu, kraken) get `#OAR` directives (submit with
  `oarsub -S ./run.sh` — the path form is required).

- **Validation** — `scripts/validate_templates.py` checks templates against
  the pinned legoESM, and CI blocks pushes to `main` when
  reproducibility-affecting files change without a tag.

### Position in the three-repo layout

```
legoESM (model, consumed read-only at a pinned commit)
   ^
   |  pinned commit (legoESM_version.txt)
this repo (templates, runners, patches, data catalog)
   ^
   |  template + overrides
my-legoESM-ocean-experiments (personal ledger: run declarations, machine
configs, notes, analysis) — see link below
```

Use this repo to declare and execute reproducible experiment
configurations; use
[my-legoESM-ocean-experiments](https://github.com/lesommer/my-legoESM-ocean-experiments)
to record what you ran, where, and what came of it.

### Current capability status

Init and provenance tagging work for all modes. The run path is implemented
for:

- `ocean_scm` (native run path)
- `3d_ocean` for **DINO** (delegation to legoESM's `run_dino.py`, upstream
  since PR climate-federation/legoESM#1926: multi-GPU SPMD, restart,
  ensemble seed and timing)
- `3d_ocean` and `barotropic_ocean` for the **matrix-lane idealized
  cases** (delegation to the upstream ocean test matrix; the upstream
  runner owns the scientifically-validated case config and gates)
- `3d_ocean_realistic` on tripole grids (delegation to the upstream OMIP
  script with patches 002/003)

Which templates are run-tested (and their receipts) is maintained in
[project_status.md](project_status.md) — the single source of truth — and
summarized below. Consult it before assuming a template can be executed
through the runners.

<!-- BEGIN status-summary: generated by scripts/render_readme_status.py; DO NOT EDIT -->

Template status by category (per-template
receipts and history live in
[project_status.md](project_status.md)):

- `1d/` — 5 templates: 5 run-tested
- `2d/` — 5 templates: 2 run-tested, 3 structural
- `3d_idealized/` — 10 templates: 9 run-tested, 1 structural
- `coupled/` — 3 templates: 3 structural
- `global_ocean/` — 8 templates: 2 run-tested, 2 smoke-tested, 4 structural

<!-- END status-summary -->

To regenerate the block after editing project_status.md:
`python scripts/render_readme_status.py` (CI verifies it is current).

## Run an experiment

### DINO (idealized, no data needed)

```bash
# 1. Initialize (paper-faithful R1 by default; see docs/dino.md for the
#    resolution ladder, multi-GPU, restart and ensemble lanes)
python scripts/init_experiment.py 3d_idealized/dino \
    --name my_dino --output-dir ./my_dino

# 2. Run
cd my_dino && bash run.sh
```

### Idealized (no data needed)

```bash
# 1. Check data availability (idealized experiments need no data)
python scripts/fetch_data.py check 3d_idealized/baroclinic_gyre

# 2. Initialize (--output-dir is required)
python scripts/init_experiment.py 3d_idealized/baroclinic_gyre \
    --name my_gyre --output-dir ./my_gyre

# 3. Run (upstream ocean test matrix executes the validated case config)
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
commit = 2ddb56f77e197a53c8411fec62a9540884bc42c9

[reproducibility]
runner_tag = legoesm-2ddb56f77e19-20261010
python_version = 3.12.12
jax_version = 0.10.0
```

To reproduce:

```bash
python scripts/reproduce.py path/to/experiment.tag
```

This checks out the runner tag → checks out the legoESM commit → applies patches → verifies data.

## Available templates

Per-template status and receipts are maintained in
[project_status.md](project_status.md) (single source of truth); the
category summary above is generated from it by
`python scripts/render_readme_status.py`. Browsable template YAMLs live
under [`templates/`](templates/).

## License

This repository is MIT-licensed (see [LICENSE](LICENSE)), **except** the
files under `patches/`: they are modifications to
[legoESM](https://github.com/climate-federation/legoESM), which is licensed
under **PolyForm Noncommercial 1.0.0**. As derivatives of legoESM, the
patches follow legoESM's terms — if you apply them to a legoESM checkout
(or run an experiment whose `experiment.tag` lists patches), that combined
work is subject to the PolyForm Noncommercial license. The rest of this
repo (templates, runners, scripts, docs) is MIT.

External data files referenced by `data_catalog.yaml` keep their own
upstream licenses and citations (recorded per-entry in the catalog).

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
