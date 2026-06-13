#!/usr/bin/env bash
# check_validation_current.sh — verify that all framework validation phases were
# run after the most recent change to any tracked (non-excluded) file.
#
# Used by the PR pipeline (GitHub Actions) to enforce that no AI-model calls
# are needed in CI — just a check that the developer ran validation locally
# before pushing.
#
# Logic:
#   1. Read the git commit timestamp of scripts/framework/validation-stamps/all-phases.stamp.
#      If the stamp does not exist or has never been committed, FAIL.
#   2. Find all files changed in this branch relative to the merge base with main.
#      Exclude: audit/, research/, .claudetmp/, scripts/framework/validation-stamps/
#   3. For each changed file, get its most recent git commit timestamp.
#   4. If any file was committed MORE RECENTLY than the stamp → FAIL.
#      (Same commit timestamp is allowed — stamp and changes can be committed together.)
#
# Exit codes:
#   0 — stamp is current; all changed files predate the stamp
#   1 — stamp is stale or missing; re-run validation before pushing
#   2 — usage or git error

set -euo pipefail

STAMP_FILE="scripts/framework/validation-stamps/all-phases.stamp"

# ── Excluded path prefixes ────────────────────────────────────────────────────
# Changes to these paths do not require re-validation.
EXCLUDE_PATTERNS=(
    "^audit/"
    "^research/"
    "^\.claudetmp/"
    "^scripts/framework/validation-stamps/"
)

# ── Helpers ───────────────────────────────────────────────────────────────────
fail() { echo "  FAIL: $1"; }
ok()   { echo "  OK:   $1"; }

is_excluded() {
    local file="$1"
    for pattern in "${EXCLUDE_PATTERNS[@]}"; do
        if echo "$file" | grep -qE "$pattern"; then
            return 0
        fi
    done
    return 1
}

echo "=== Validation stamp check ==="
echo ""

# ── 1. Check stamp exists and is committed ────────────────────────────────────
if [[ ! -f "$STAMP_FILE" ]]; then
    fail "Stamp file not found: $STAMP_FILE"
    echo ""
    echo "  Run scripts/framework/run_framework_validation.sh and commit the stamp"
    echo "  before pushing. The stamp proves all validation phases were run."
    exit 1
fi

STAMP_COMMIT=$(git log -1 --format="%H" -- "$STAMP_FILE" 2>/dev/null || true)
if [[ -z "$STAMP_COMMIT" ]]; then
    fail "Stamp file exists but has not been committed: $STAMP_FILE"
    echo ""
    echo "  git add $STAMP_FILE && git commit"
    exit 1
fi

STAMP_TIME=$(git log -1 --format="%ct" -- "$STAMP_FILE")
STAMP_DATE=$(git log -1 --format="%ci" -- "$STAMP_FILE")
STAMP_PHASES=$(grep "^phases:" "$STAMP_FILE" 2>/dev/null | sed 's/phases:[[:space:]]*//' || echo "unknown")
STAMP_SKIPPED=$(grep "^skipped:" "$STAMP_FILE" 2>/dev/null | sed 's/skipped:[[:space:]]*//' || echo "")

ok "Stamp found: $STAMP_DATE"
ok "Phases run: $STAMP_PHASES"
[[ -n "$STAMP_SKIPPED" && "$STAMP_SKIPPED" != " " ]] && echo "  WARN: Skipped phases: $STAMP_SKIPPED (skipping requires human approval)"
echo ""

# ── 2. Find changed files in this PR ─────────────────────────────────────────
# In CI (GitHub Actions), GITHUB_BASE_REF is the target branch.
# Locally, fall back to comparing against origin/main.
BASE_REF="${GITHUB_BASE_REF:-main}"
MERGE_BASE=$(git merge-base HEAD "origin/${BASE_REF}" 2>/dev/null \
    || git merge-base HEAD "${BASE_REF}" 2>/dev/null \
    || echo "")

if [[ -z "$MERGE_BASE" ]]; then
    echo "  WARN: Could not determine merge base — comparing against HEAD~1"
    CHANGED_FILES=$(git diff --name-only HEAD~1 2>/dev/null || true)
else
    CHANGED_FILES=$(git diff --name-only "$MERGE_BASE"...HEAD 2>/dev/null || true)
fi

if [[ -z "$CHANGED_FILES" ]]; then
    ok "No changed files detected — nothing to check"
    echo ""
    echo "════════════════════════════════════════════"
    echo "  PASS — validation stamp is current"
    echo "════════════════════════════════════════════"
    exit 0
fi

# ── 3. Check each changed file against the stamp timestamp ───────────────────
STALE_FILES=()

while IFS= read -r file; do
    [[ -z "$file" ]] && continue

    # Skip excluded paths
    if is_excluded "$file"; then
        ok "EXCLUDED: $file"
        continue
    fi

    # Get the most recent commit time for this file
    FILE_TIME=$(git log -1 --format="%ct" -- "$file" 2>/dev/null || echo "")
    FILE_DATE=$(git log -1 --format="%ci" -- "$file" 2>/dev/null || echo "uncommitted")

    if [[ -z "$FILE_TIME" ]]; then
        # File is untracked or not in git history — skip
        ok "UNTRACKED (skip): $file"
        continue
    fi

    if [[ "$FILE_TIME" -gt "$STAMP_TIME" ]]; then
        fail "$file was committed after last validation (file: $FILE_DATE > stamp: $STAMP_DATE)"
        STALE_FILES+=("$file")
    else
        ok "$file — predates stamp"
    fi
done <<< "$CHANGED_FILES"

echo ""

# ── 4. Report ─────────────────────────────────────────────────────────────────
if [[ ${#STALE_FILES[@]} -gt 0 ]]; then
    echo "════════════════════════════════════════════"
    echo "  FAIL — ${#STALE_FILES[@]} file(s) changed after last validation"
    echo ""
    echo "  Files committed after stamp ($STAMP_DATE):"
    for f in "${STALE_FILES[@]}"; do
        echo "    $f"
    done
    echo ""
    echo "  To fix:"
    echo "    bash scripts/framework/run_framework_validation.sh"
    echo "    git add scripts/framework/validation-stamps/all-phases.stamp"
    echo "    git commit --amend   # or a new commit"
    echo "════════════════════════════════════════════"
    exit 1
fi

echo "════════════════════════════════════════════"
echo "  PASS — stamp is current ($STAMP_DATE)"
echo "  Phases validated: $STAMP_PHASES"
echo "════════════════════════════════════════════"
exit 0
