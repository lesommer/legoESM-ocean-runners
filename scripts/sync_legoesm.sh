#!/usr/bin/env bash
# Sync the legoESM pinned version to the latest commit on the specified ref.
#
# This script:
# 1. Fetches the latest from the legoESM remote
# 2. Updates legoESM_version.txt to the HEAD of the specified ref
# 3. Runs template validation to check compatibility
# 4. With --tag: creates a git tag on successful validation
#
# Usage:
#   bash scripts/sync_legoesm.sh                    # sync to latest main
#   bash scripts/sync_legoesm.sh --tag              # sync + validate + tag on success
#   bash scripts/sync_legoesm.sh feature/ocean-btr   # sync to a specific branch
#   bash scripts/sync_legoesm.sh --check-only        # just validate, don't update

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION_FILE="$ROOT_DIR/legoESM_version.txt"

# Find legoESM checkout
if [ -n "${LEGOESM_DIR:-}" ]; then
    LEGOESM_DIR="$LEGOESM_DIR"
else
    LEGOESM_DIR="$(dirname "$ROOT_DIR")/legoESM"
fi

if [ ! -d "$LEGOESM_DIR/.git" ]; then
    echo "ERROR: legoESM not found at $LEGOESM_DIR"
    echo "       Set LEGOESM_DIR to point to your legoESM checkout."
    exit 1
fi

# Parse arguments
REF="main"
CHECK_ONLY=0
CREATE_TAG=0

for arg in "$@"; do
    case "$arg" in
        --tag)
            CREATE_TAG=1
            ;;
        --check-only)
            CHECK_ONLY=1
            ;;
        *)
            REF="$arg"
            ;;
    esac
done

echo "legoESM directory: $LEGOESM_DIR"
echo "Target ref: $REF"
if [ "$CREATE_TAG" = "1" ]; then
    echo "Tag on success: yes"
fi

# Fetch latest
echo "Fetching latest from remote..."
(cd "$LEGOESM_DIR" && git fetch origin)

# Get the commit hash for the ref
NEW_COMMIT=$(cd "$LEGOESM_DIR" && git rev-parse "origin/$REF" 2>/dev/null || git rev-parse "$REF")
SHORT_COMMIT=$(echo "$NEW_COMMIT" | cut -c1-12)
echo "Latest commit on $REF: $SHORT_COMMIT"

# Read current version
CURRENT_COMMIT=$(grep '^commit:' "$VERSION_FILE" | cut -d: -f2 | tr -d ' ')
echo "Current pinned commit: $(echo "$CURRENT_COMMIT" | cut -c1-12)"

if [ "$CHECK_ONLY" = "1" ]; then
    echo ""
    echo "Check-only mode. Running validation..."
    python "$SCRIPT_DIR/validate_templates.py" --legoesm-dir "$LEGOESM_DIR" --verbose
    exit $?
fi

if [ "$NEW_COMMIT" = "$CURRENT_COMMIT" ]; then
    echo "Already up to date."
    # Even if up to date, create tag if requested and not already tagged
    if [ "$CREATE_TAG" = "1" ]; then
        TAG_NAME="legoesm-${SHORT_COMMIT}-$(date +%Y%m%d)"
        if git -C "$ROOT_DIR" tag -l "$TAG_NAME" | grep -q .; then
            echo "Tag $TAG_NAME already exists."
        else
            echo "Creating tag: $TAG_NAME"
            git -C "$ROOT_DIR" tag "$TAG_NAME"
            git -C "$ROOT_DIR" push origin "$TAG_NAME" 2>/dev/null || echo "  (Could not push tag to remote)"
        fi
    fi
    exit 0
fi

# Update legoESM checkout to the ref
echo "Checking out $REF..."
(cd "$LEGOESM_DIR" && git checkout "$REF" 2>/dev/null && git merge "origin/$REF" --ff-only 2>/dev/null) || {
    echo "WARNING: Could not fast-forward. Checking out detached HEAD at $SHORT_COMMIT"
    (cd "$LEGOESM_DIR" && git checkout "$NEW_COMMIT")
}

# Update version file
TODAY=$(date +%Y-%m-%d)
cat > "$VERSION_FILE" <<EOF
ref: $REF
commit: $NEW_COMMIT
date: $TODAY
EOF

echo ""
echo "Updated legoESM_version.txt:"
echo "  ref:    $REF"
echo "  commit: $SHORT_COMMIT"
echo "  date:   $TODAY"

# Run validation
echo ""
echo "Running template validation..."
VALIDATION_OK=1
python "$SCRIPT_DIR/validate_templates.py" --legoesm-dir "$LEGOESM_DIR" --verbose || VALIDATION_OK=0

if [ "$VALIDATION_OK" = "0" ]; then
    echo ""
    echo "WARNING: Some templates failed validation with the new legoESM version."
    echo "         Please review and update the failing templates before committing."
    echo "         Do NOT tag until all templates pass validation."
    exit 1
fi

echo ""
echo "All templates validated successfully."

if [ "$CREATE_TAG" = "1" ]; then
    TAG_NAME="legoesm-${SHORT_COMMIT}-$(date +%Y%m%d)"

    # Check if already tagged
    if git -C "$ROOT_DIR" tag -l "$TAG_NAME" | grep -q .; then
        echo "Tag $TAG_NAME already exists."
    else
        # Commit the version file update if there are changes
        if git -C "$ROOT_DIR" diff --quiet "$VERSION_FILE" 2>/dev/null; then
            echo "No changes to commit."
        else
            git -C "$ROOT_DIR" add "$VERSION_FILE"
            git -C "$ROOT_DIR" commit -m "chore: update legoESM pin to ${SHORT_COMMIT}"
        fi

        echo "Creating tag: $TAG_NAME"
        git -C "$ROOT_DIR" tag "$TAG_NAME"
        echo "Tag created: $TAG_NAME"
        echo ""
        echo "To push the tag to remote:"
        echo "  git push origin $TAG_NAME"
    fi
else
    echo ""
    echo "To create a reproducibility tag after committing:"
    echo "  git tag \"legoesm-${SHORT_COMMIT}-$(date +%Y%m%d)\""
    echo "  git push --tags"
fi