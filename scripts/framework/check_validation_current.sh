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
#   2. Override-expiry check (fail-closed). A human-authorized override may set an
#      `override_expires:` line (ISO-8601 UTC) on the stamp. If present and now is
#      past it — or the value is malformed/unparseable — FAIL: time-boxed overrides
#      are never permanent. If the line is absent, this check is skipped (normal
#      clean stamp). Any ambiguity is treated as EXPIRED.
#   3. Find all files changed in this branch relative to the merge base with main.
#      Exclude: audit/, research/, .claudetmp/, scripts/framework/validation-stamps/
#   4. For each changed file, get its most recent git commit timestamp.
#   5. If any file was committed MORE RECENTLY than the stamp → FAIL.
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
# Temporary bypass: stamps gitignored (#422) — skip check instead of failing.
# This bypass MUST be removed by STAMP_BYPASS_DISABLED_UNTIL or #552 redesign,
# whichever comes first. After that date CI exits 1 (FAIL) to force resolution.
STAMP_BYPASS_DISABLED_UNTIL="2026-12-31"
_bypass_expiry=$(date -d "$STAMP_BYPASS_DISABLED_UNTIL" +%s 2>/dev/null \
    || python3 -c "import time,calendar; print(calendar.timegm(time.strptime('$STAMP_BYPASS_DISABLED_UNTIL','%Y-%m-%d')))" 2>/dev/null || echo 0)
_now=$(date -u +%s)
if [[ "$_now" -gt "$_bypass_expiry" ]]; then
    echo "════════════════════════════════════════════"
    echo "  FAIL: Stamp bypass EXPIRED on $STAMP_BYPASS_DISABLED_UNTIL."
    echo "  The gitignore bypass for validation stamps must be resolved."
    echo "  Implement #552 (content-hash stamps) or re-authorize with a new date."
    echo "════════════════════════════════════════════"
    exit 1
fi
if [[ ! -f "$STAMP_FILE" ]] || ! git ls-files --error-unmatch "$STAMP_FILE" &>/dev/null 2>&1; then
    echo "  SKIP: Stamp gitignored per #422 — check skipped (bypass expires $STAMP_BYPASS_DISABLED_UNTIL)."
    exit 0
fi

STAMP_COMMIT=$(git log -1 --format="%H" -- "$STAMP_FILE" 2>/dev/null || true)
if [[ -z "$STAMP_COMMIT" ]]; then
    echo "  SKIP: Stamp not committed — skipping (#422)."
    exit 0
fi

STAMP_TIME=$(git log -1 --format="%ct" -- "$STAMP_FILE")
STAMP_DATE=$(git log -1 --format="%ci" -- "$STAMP_FILE")
STAMP_PHASES=$(grep "^phases:" "$STAMP_FILE" 2>/dev/null | sed 's/phases:[[:space:]]*//' || echo "unknown")
STAMP_SKIPPED=$(grep "^skipped:" "$STAMP_FILE" 2>/dev/null | sed 's/skipped:[[:space:]]*//' || echo "")

ok "Stamp found: $STAMP_DATE"
ok "Phases run: $STAMP_PHASES"
[[ -n "$STAMP_SKIPPED" && "$STAMP_SKIPPED" != " " ]] && echo "  WARN: Skipped phases: $STAMP_SKIPPED (skipping requires human approval)"
echo ""

# ── 1b. Override-expiry check (fail-closed) ──────────────────────────────────
# A human-authorized validation override (HOS_ALLOW_UNVALIDATED) is time-boxed:
# the stamp may carry an `override_expires:` line (ISO-8601 UTC). After that
# instant the override has lapsed and CI MUST fail, forcing the team to resolve
# the deferred findings or re-authorize. Fail-closed: an absent line means "no
# override" (skip); a present-but-malformed or unparseable value is treated as
# EXPIRED. This runs early so an expired override fails fast.
OVERRIDE_EXPIRES=$(grep "^override_expires:" "$STAMP_FILE" 2>/dev/null \
    | head -n1 | sed 's/override_expires:[[:space:]]*//' || true)

if [[ -n "$OVERRIDE_EXPIRES" ]]; then
    # Parse expiry to epoch using a portable method (python3 is a prerequisite).
    EXPIRY_EPOCH=$(python3 -c "import sys,calendar,time; print(calendar.timegm(time.strptime(sys.argv[1], '%Y-%m-%dT%H:%M:%SZ')))" "$OVERRIDE_EXPIRES" 2>/dev/null || true)

    if [[ -z "$EXPIRY_EPOCH" ]] || ! [[ "$EXPIRY_EPOCH" =~ ^[0-9]+$ ]]; then
        echo "════════════════════════════════════════════"
        fail "override_expires is malformed: '$OVERRIDE_EXPIRES' — cannot verify expiry; treat as expired"
        echo ""
        echo "  A human-authorized validation override must carry a parseable"
        echo "  ISO-8601 UTC expiry (e.g. 2026-06-22T00:00:00Z). Fix the stamp's"
        echo "  override_expires value, or resolve the deferred findings and commit"
        echo "  a fresh (non-override) stamp."
        echo "════════════════════════════════════════════"
        exit 1
    fi

    NOW=$(date -u +%s)
    NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    if [[ "$NOW" -gt "$EXPIRY_EPOCH" ]]; then
        echo "════════════════════════════════════════════"
        echo "  FAIL: Validation override EXPIRED on $OVERRIDE_EXPIRES (now $NOW_ISO)."
        echo "    A human-authorized validation override is time-boxed and has lapsed."
        echo "    The deferred findings must now be resolved (or re-authorized):"
        echo "      - Resolve the tracked findings, re-run scripts/framework/run_framework_validation.sh"
        echo "        until the gate converges clean, and commit a fresh (non-override) stamp; OR"
        echo "      - A human re-authorizes a new time-boxed override with a new override_expires."
        echo "════════════════════════════════════════════"
        exit 1
    fi

    # Active override — report and continue to the normal per-file currency check.
    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW) / 86400 ))
    ok "Validation override active until $OVERRIDE_EXPIRES ($DAYS_LEFT day(s) remaining)"
    echo ""
fi

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
