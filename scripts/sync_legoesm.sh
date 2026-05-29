#!/usr/bin/env bash
# Sync the legoESM pinned version to the latest commit on the specified ref.
#
# This script:
# 1. Fetches the latest from the legoESM remote
# 2. Updates legoESM_version.txt to the HEAD of the specified ref
# 3. Runs template validation to check compatibility
#
# Usage:
#   bash scripts/sync_legoesm.sh                    # sync to latest main
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

REF="${1:-main}"
CHECK_ONLY=0
if [ "$REF" = "--check-only" ]; then
    CHECK_ONLY=1
    REF="main"
fi

echo "legoESM directory: $LEGOESM_DIR"
echo "Target ref: $REF"

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
python "$SCRIPT_DIR/validate_templates.py" --legoesm-dir "$LEGOESM_DIR" --verbose

if [ $? -ne 0 ]; then
    echo ""
    echo "WARNING: Some templates failed validation with the new legoESM version."
    echo "         Please review and update the failing templates before committing."
fi