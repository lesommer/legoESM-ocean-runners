## Summary

<!-- What does this PR change, and why? Reference the issue number if there is one. -->

## Checklist

- [ ] `python scripts/validate_templates.py --skip-imports` passes
- [ ] `python -m pytest tests/` passes
- [ ] `python scripts/render_readme_status.py --check` passes
- [ ] `project_status.md` updated for any capability or template change
      (new template → row in the "Template test status" table with Status
      `structural`; then `python scripts/render_readme_status.py`), committed
      together with the change
- [ ] No data files, notebook outputs, secrets, or real machine configs
      (scheduler accounts, usernames) are committed
- [ ] I understand that `legoesm-*` tags are created by the maintainer after
      merge (`bash scripts/sync_legoesm.sh --tag-only`) — the red
      reproducibility-tag check on this PR is expected until then, and I will
      not create tags myself

<!-- If this PR touches templates/, runners/, scripts/, patches/,
legoESM_version.txt, or data_catalog.yaml, the reproducibility-tag check will
be red until the maintainer tags after merge. That is by design. -->
