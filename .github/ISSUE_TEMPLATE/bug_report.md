---
name: Bug report
about: Something does not work as expected
labels: bug
title: ""
assignees: ""
---

## What happened

<!-- A clear and specific description of the problem. -->

## What you expected

<!-- What you expected to happen instead. -->

## Experiment details

- **Template + mode**: <!-- e.g. 3d_idealized/baroclinic_gyre, mode 3d_ocean; list any `-o` overrides -->
- **legoESM pin** (from `legoESM_version.txt`): <!-- ref + commit, e.g. main / 2ddb56f77e19 -->
- **Machine / environment**: <!-- hostname, scheduler, GPU or CPU, Python and JAX versions -->

## Provenance files (required)

Attach **both** files from the experiment directory:

- [ ] `experiment.tag` — records the runner tag, legoESM commit, patches, machine
- [ ] `config.yaml` — the resolved configuration (if you used `run.yaml` overrides, attach it too)

Reports without these two files cannot be reproduced; raw logs are not a
substitute.

## Additional context

<!-- Error output, screenshots, or anything else that helps. -->
