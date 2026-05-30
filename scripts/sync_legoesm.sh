#!/usr/bin/env bash
# Sync the legoESM pinned version to the latest commit on the specified ref.
#
# This script:
# 1. Fetches the latest from the legoESM remote
# 2. Fast-forwards the local legoESM checkout
# 3. Detects a Python with JAX/legoesm (venv-aware)
# 4. Updates legoESM_version.txt to the HEAD of the specified ref (atomic)
# 5. Runs template validation to check compatibility
# 6. With --tag: commits + creates a git tag on successful validation
# 7. With --push: pushes the commit and tag to origin
#
# Usage:
#   bash scripts/sync_legoesm.sh                    # sync to latest main
#   bash scripts/sync_legoesm.sh --tag              # sync + validate + tag on success
#   bash scripts/sync_legoesm.sh --tag --push       # sync + validate + tag + push
#   bash scripts/sync_legoesm.sh feature/ocean-btr   # sync to a specific branch
#   bash scripts/sync_legoesm.sh --check-only        # just validate, don't update

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION_FILE="$ROOT_DIR/legoESM_version.txt"
TEMP_VERSION_FILE="$ROOT_DIR/legoESM_version.txt.tmp"

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

# Detect Python with JAX + legoesm
detect_python() {
    if [ -n "${LEGOESM_PYTHON:-}" ]; then
        echo "$LEGOESM_PYTHON"
        return
    fi

    local venv_python="$LEGOESM_DIR/.venv/bin/python3"
    if [ -x "$venv_python" ]; then
        if "$venv_python" -c "import jax" 2>/dev/null; then
            echo "$venv_python"
            return
        fi
    fi

    if command -v python3 &>/dev/null; then
        echo "python3"
        return
    fi

    echo "python"
}

PYTHON=$(detect_python)
echo "Using Python: $PYTHON"

# Ensure legoesm is importable from the detected Python
ensure_legoesm_importable() {
    if "$PYTHON" -c "import legoesm" 2>/dev/null; then
        return
    fi

    echo "legoesm not importable. Installing in editable mode..."
    "$PYTHON" -m pip install -e "$LEGOESM_DIR" --quiet 2>&1 || {
        echo "WARNING: Could not install legoesm. Validation may fail."
    }
}

# Parse arguments
REF="main"
CHECK_ONLY=0
CREATE_TAG=0
PUSH=0

for arg in "$@"; do
    case "$arg" in
        --tag)
            CREATE_TAG=1
            ;;
        --push)
            PUSH=1
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
if [ "$PUSH" = "1" ]; then
    echo "Push on success: yes"
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

# Check-only mode: just validate, don't update anything
if [ "$CHECK_ONLY" = "1" ]; then
    echo ""
    echo "Check-only mode. Running validation..."
    ensure_legoesm_importable
    "$PYTHON" "$SCRIPT_DIR/validate_templates.py" --legoesm-dir "$LEGOESM_DIR" --verbose
    exit $?
fi

# Already up to date
if [ "$NEW_COMMIT" = "$CURRENT_COMMIT" ]; then
    echo "Already up to date."
    if [ "$CREATE_TAG" = "1" ]; then
        TAG_NAME="legoesm-${SHORT_COMMIT}-$(date +%Y%m%d)"
        if git -C "$ROOT_DIR" tag -l "$TAG_NAME" | grep -q .; then
            echo "Tag $TAG_NAME already exists."
        else
            echo "Creating tag: $TAG_NAME"
            git -C "$ROOT_DIR" tag "$TAG_NAME"
            if [ "$PUSH" = "1" ]; then
                git -C "$ROOT_DIR" push origin "$TAG_NAME" 2>/dev/null || echo "  (Could not push tag to remote)"
            else
                echo "To push the tag to remote:"
                echo "  git push origin $TAG_NAME"
            fi
        fi
    fi
    exit 0
fi

# Fast-forward local legoESM checkout
echo "Fast-forwarding local legoESM checkout..."
(cd "$LEGOESM_DIR" && git checkout "$REF" 2>/dev/null && git merge "origin/$REF" --ff-only 2>/dev/null) || {
    echo "ERROR: Could not fast-forward legoESM. Resolve conflicts manually."
    echo "       Current legoESM branch may have diverged from origin/$REF."
    exit 1
}

# Ensure legoesm is importable after checkout
ensure_legoesm_importable

# Write version to temp file (atomic: only replace real file on validation success)
TODAY=$(date +%Y-%m-%d)
cat > "$TEMP_VERSION_FILE" <<EOF
ref: $REF
commit: $NEW_COMMIT
date: $TODAY
EOF

echo ""
echo "Prepared version update:"
echo "  ref:    $REF"
echo "  commit: $SHORT_COMMIT"
echo "  date:   $TODAY"

# Run validation
echo ""
echo "Running template validation..."
VALIDATION_OK=1
"$PYTHON" "$SCRIPT_DIR/validate_templates.py" --legoesm-dir "$LEGOESM_DIR" --verbose || VALIDATION_OK=0

if [ "$VALIDATION_OK" = "0" ]; then
    rm -f "$TEMP_VERSION_FILE"
    echo ""
    echo "WARNING: Some templates failed validation with the new legoESM version."
    echo "         Version file NOT updated. Working tree is clean."
    echo "         Please review and update the failing templates before committing."
    echo "         Do NOT tag until all templates pass validation."
    exit 1
fi

# Validation passed: atomically replace the version file
mv "$TEMP_VERSION_FILE" "$VERSION_FILE"

echo ""
echo "All templates validated successfully."

if [ "$CREATE_TAG" = "1" ]; then
    TAG_NAME="legoesm-${SHORT_COMMIT}-$(date +%Y%m%d)"

    # Check if already tagged
    if git -C "$ROOT_DIR" tag -l "$TAG_NAME" | grep -q .; then
        echo "Tag $TAG_NAME already exists."
    else
        # Commit the version file update
        git -C "$ROOT_DIR" add "$VERSION_FILE"
        git -C "$ROOT_DIR" commit -m "chore: update legoESM pin to ${SHORT_COMMIT}"

        echo "Creating tag: $TAG_NAME"
        git -C "$ROOT_DIR" tag "$TAG_NAME"
        echo "Tag created: $TAG_NAME"

        if [ "$PUSH" = "1" ]; then
            echo "Pushing commit and tag to origin..."
            git -C "$ROOT_DIR" push origin main 2>/dev/null || echo "  (Could not push commit)"
            git -C "$ROOT_DIR" push origin "$TAG_NAME" 2>/dev/null || echo "  (Could not push tag)"
            echo "Pushed."
        else
            echo ""
            echo "To push the commit and tag to remote:"
            echo "  git push origin main $TAG_NAME"
        fi
    fi
else
    echo ""
    echo "Version file updated but not committed. To commit and tag:"
    echo "  git add legoESM_version.txt"
    echo "  git commit -m \"chore: update legoESM pin to ${SHORT_COMMIT}\""
    echo "  git tag \"legoesm-${SHORT_COMMIT}-\$(date +%Y%m%d)\""
    echo "  git push origin main --tags"
fi
