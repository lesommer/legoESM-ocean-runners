# Contributing to legoESM-ocean-runners

This document covers what belongs in this repository, how to propose
changes, and what CI will ask of you.

## What belongs here

| Change | Where it goes |
|--------|---------------|
| New or updated experiment templates | here, `templates/` |
| Runner or script improvements | here, `runners/`, `scripts/` |
| Data catalog entries (URLs, checksums, citations) | here, `data_catalog.yaml` |
| Documentation of templates and runners | here (`README.md`, `project_status.md`, `docs/`) |
| Model features (physics, config classes, grids) | upstream: [climate-federation/legoESM](https://github.com/climate-federation/legoESM) |
| Bugs in the model itself | upstream legoESM issue tracker |

Patches (`patches/`) are temporary by design: a patch lets templates use a
legoESM feature before it is merged upstream, and it is removed from this
repository once the feature lands in legoESM main. Do not treat `patches/`
as a long-term fork, and never edit legoESM source code from this repo.

## Development setup

```bash
git clone https://github.com/<your-fork>/legoESM-ocean-runners.git
cd legoESM-ocean-runners
python -m venv .venv && source .venv/bin/activate   # Python >= 3.11
pip install -e ".[dev]"
```

(With [uv](https://docs.astral.sh/uv/): `uv pip install -e ".[dev]"`.)

Template structure validation and the test suite do not require a legoESM
checkout. Full validation against the pinned model
(`python scripts/validate_templates.py` without `--skip-imports`) checks
out the commit recorded in `legoESM_version.txt`; CI does this
automatically for every PR and push.

## Before opening a PR

Every PR must pass:

```bash
python scripts/validate_templates.py --skip-imports
python -m pytest tests/
python scripts/render_readme_status.py --check
```

Additional requirements depending on the change:

- **New template**: add a row to the "Template test status" table in
  `project_status.md` with Status `structural`, then run
  `python scripts/render_readme_status.py` (template parity is
  CI-enforced).
- **Runner capability change**: update the affected `project_status.md`
  tables and re-run the renderer; commit the docs change together with the
  capability change.
- **New data catalog entry**: include `description`, `path`, `access`,
  `format`, `size_mb`; verify checksums against a real download with
  `python scripts/fetch_data.py verify <id>` before committing them.

Never commit: data files (NetCDF/Zarr), real machine configs (scheduler
accounts, usernames, absolute paths), notebook outputs, or secrets.

## The reproducibility-tag gate

Changes to `templates/`, `runners/`, `scripts/`, `patches/`,
`legoESM_version.txt`, or `data_catalog.yaml` affect reproducibility and
require a `legoesm-*` git tag on `main`. CI enforces this: the
reproducibility-tag check fails if such files changed since the last tag.

For external contributors this means: **a PR touching those paths shows a
red reproducibility-tag check until it is merged and tagged — that is by
design, not a bug in your PR.** Tags are created by the maintainer after
merge, via `bash scripts/sync_legoesm.sh --tag-only`, after validating the
templates. Do not create `legoesm-*` tags yourself; external contributors
cannot tag in any case.

## Bug reports

Use the bug report issue template and attach the two provenance files from
the experiment directory: `experiment.tag` and `config.yaml`. Together they
record the template, overrides, pinned legoESM commit, applied patches,
and machine config needed to reproduce the run. Raw logs are not enough.
If the problem is in the model rather than the runners, report it in the
upstream legoESM issue tracker instead.

## Good first issues

New idealized templates ported from legoESM's ocean test matrix (e.g.
`munk_gyre`, `held_larichev`, ISOMIP+ onboarding), documentation
improvements, and new data catalog entries are good entry points. Look for
the `good first issue` label.
