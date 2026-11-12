#!/usr/bin/env bash
# Apply patches from patches/ to the legoESM checkout.
#
# Patches are applied in alphabetical order to the legoESM commit pinned in
# legoESM_version.txt. The legoESM checkout is found via LEGOESM_DIR env var
# or defaults to ../legoESM.
#
# Usage:
#   bash scripts/apply_patches.sh                  # apply all
#   bash scripts/apply_patches.sh 001-foo.patch    # apply specific patch
#   bash scripts/apply_patches.sh --reverse        # reverse all patches

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
PATCHES_DIR="$ROOT_DIR/patches"
VERSION_FILE="$ROOT_DIR/legoESM_version.txt"

# Find legoESM checkout
if [ -n "${LEGOESM_DIR:-}" ]; then
    LEGOESM_DIR="$LEGOESM_DIR"
else
    LEGOESM_DIR="$(dirname "$ROOT_DIR")/legoESM"
fi

# `--show-toplevel` equality instead of `[ -d .git ]`: a linked worktree
# has a `.git` FILE, not a directory, and a bare `--git-dir` probe would
# also match any SUBDIRECTORY of some other repo (patch paths are
# repo-rooted, so the dir must be a top level).
if [ "$(git -C "$LEGOESM_DIR" rev-parse --show-toplevel 2>/dev/null)" != "$(cd "$LEGOESM_DIR" 2>/dev/null && pwd -P)" ]; then
    echo "ERROR: legoESM not found at $LEGOESM_DIR"
    echo "       Set LEGOESM_DIR to point to your legoESM checkout."
    exit 1
fi

# Read pinned commit
PINNED_COMMIT=$(grep '^commit:' "$VERSION_FILE" | cut -d: -f2 | tr -d ' ')
echo "Pinned legoESM commit: $PINNED_COMMIT"

# Check current commit
CURRENT_COMMIT=$(cd "$LEGOESM_DIR" && git rev-parse HEAD)
echo "Current legoESM commit: $CURRENT_COMMIT"

if [ "$CURRENT_COMMIT" != "$PINNED_COMMIT" ]; then
    echo "WARNING: Current commit does not match pinned commit."
    echo "         Consider running: scripts/sync_legoesm.sh"
    echo "         Press Ctrl+C to abort, or Enter to continue anyway."
    read -r
fi

# Collect patches
if [ $# -eq 0 ]; then
    PATCHES=$(ls "$PATCHES_DIR"/*.patch 2>/dev/null | sort)
elif [ "$1" = "--reverse" ]; then
    PATCHES=$(ls "$PATCHES_DIR"/*.patch 2>/dev/null | sort -r)
    REVERSE=1
elif [ "$1" = "--check" ]; then
    PATCHES=$(ls "$PATCHES_DIR"/*.patch 2>/dev/null | sort)
    echo "Dry-run: checking the patch chain applies cleanly (in order)..."
    # Patches stack (a later patch's context can be an earlier patch's
    # output — e.g. 010 on 009), so a per-patch --check against the
    # pristine tree false-positives on stacking. Probe the chain on a
    # detached worktree at the checkout's current commit; the real
    # checkout is untouched.
    CHECK_WT=$(mktemp -d "${TMPDIR:-/tmp}/legoesm-patchcheck.XXXXXX")
    if ! git -C "$LEGOESM_DIR" worktree add --detach "$CHECK_WT" HEAD >/dev/null 2>&1; then
        rm -rf "$CHECK_WT"
        echo "ERROR: could not create probe worktree in $LEGOESM_DIR"
        exit 1
    fi
    FAILED=0
    for p in $PATCHES; do
        echo -n "  $(basename "$p"): "
        if git -C "$CHECK_WT" apply "$p" >/dev/null 2>&1; then
            echo "OK"
        else
            echo "FAILED (would conflict)"
            FAILED=1
            break
        fi
    done
    git -C "$LEGOESM_DIR" worktree remove --force "$CHECK_WT" >/dev/null 2>&1
    if [ "$FAILED" = "0" ]; then
        echo "All patches apply cleanly."
    fi
    exit $FAILED
else
    PATCHES="$@"
    REVERSE=0
fi

if [ -z "$PATCHES" ]; then
    echo "No patches found in $PATCHES_DIR"
    exit 0
fi

REVERSE="${REVERSE:-0}"

for patch in $PATCHES; do
    echo -n "Applying $(basename "$patch")... "
    APPLY_ARGS=""
    if [ "$REVERSE" = "1" ]; then
        APPLY_ARGS="--reverse"
    fi
    if (cd "$LEGOESM_DIR" && git apply $APPLY_ARGS "$patch" 2>&1); then
        echo "OK"
    else
        echo "FAILED"
        echo "  Try: git apply --3way $APPLY_ARGS $patch"
        exit 1
    fi
done

echo "Done. All patches applied."