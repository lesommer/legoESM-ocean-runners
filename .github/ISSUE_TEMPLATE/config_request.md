---
name: Configuration request
about: Propose a new experiment template or a change to an existing one
labels: templates
title: ""
assignees: ""
---

## Proposed template or change

<!-- For a new template: the intended templates/<category>/<name>.yaml and the
overrides it should carry. For a change to an existing template: which fields
change and why. -->

```yaml
# Sketch of the template (required sections at minimum)
experiment:
  name:
  mode:   # one of: ocean_scm, barotropic_ocean, 3d_ocean, 3d_ocean_realistic, coupled
  description:

requires: []
grid:
time:
```

## Scientific case

<!-- What question does this configuration answer? Which process or regime does
it target? Why is it not already covered by an existing template? -->

## Reference configuration in legoESM

<!-- If legoESM already ships a case (e.g. in src/legoesm/ocean/experiments/
or the ocean test matrix), name it — porting an upstream case is preferred over
inventing a new configuration. Otherwise state that there is no upstream
reference and where the configuration comes from (paper, other model). -->

## Data requirements

<!-- New data catalog entries needed? List them with source URL, size, and
license/citation if known. -->
