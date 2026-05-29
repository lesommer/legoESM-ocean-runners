# Patches for legoESM

This directory stores git patches that extend or modify the pinned version of
legoESM before those changes are merged upstream.

## Naming convention

Patches are numbered and descriptive:

    001-<short-description>.patch
    002-<short-description>.patch

## Creating a patch

From inside the legoESM checkout:

    cd ../legoESM
    git diff main > ../legoESM-ocean-runners/patches/001-my-feature.patch

## Applying patches

    ./scripts/apply_patches.sh

This applies all patches in order to the legoESM checkout referenced by
`legoESM_version.txt`.

## Cleanup

Once a patch is merged into legoESM main, remove the patch file here and
update `legoESM_version.txt` to the new pinned commit.