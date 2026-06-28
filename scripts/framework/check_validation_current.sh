#!/usr/bin/env bash
# check_validation_current.sh — verify that agent content has a valid validation stamp.
#
# Uses content-hash-based stamps (#552): computes a SHA-256 hash of all
# .claude/agents/*.md file contents, then checks that a matching stamp file
# (scripts/framework/validation-stamps/phase1-<HASH>.stamp) exists and has been
# committed to git. Identical agent content → identical hash → stamp is still
# valid after rebase (solves the #422 merge-conflict cascade).
#
# The stamp is written by check_agents_static.sh (via run_framework_validation.sh).
# Non-agent-file changes (e.g. Python validator scripts) do not require a new
# stamp because the agent structure did not change — this is a known design
# tradeoff documented in #552.
#
# Override-expiry (fail-closed): a stamp may carry override_expires: (ISO-8601 UTC)
# for human-authorized time-boxed overrides. CI fails after that instant.
#
# Exit codes:
#   0 — stamp exists and is current for the agent content
#   1 — stamp missing or expired override
#   2 — usage or git error

set -euo pipefail

STAMP_DIR="scripts/framework/validation-stamps"

echo "=== Validation stamp check ==="
echo ""

# ── Compute agent content hash ────────────────────────────────────────────────
if [[ ! -d ".claude/agents" ]]; then
    echo "  FAIL: .claude/agents directory not found — cannot compute content hash"
    exit 2
fi

AGENT_FILES=$(find .claude/agents -name "*.md" | sort)
if [[ -z "$AGENT_FILES" ]]; then
    echo "  FAIL: no agent files found in .claude/agents/"
    exit 2
fi

CONTENT_HASH=$(echo "$AGENT_FILES" | xargs sha256sum | sha256sum | cut -d' ' -f1)
STAMP_FILE="$STAMP_DIR/phase1-${CONTENT_HASH}.stamp"

echo "  Agent content hash: $CONTENT_HASH"

# ── Check stamp is committed ──────────────────────────────────────────────────
if ! git ls-files --error-unmatch "$STAMP_FILE" &>/dev/null 2>&1; then
    echo ""
    echo "════════════════════════════════════════════"
    echo "  FAIL: no committed stamp for current agent content"
    echo "  Expected: $STAMP_FILE"
    echo ""
    echo "  To fix:"
    echo "    bash scripts/framework/run_framework_validation.sh"
    echo "    git add $STAMP_FILE"
    echo "    git commit --amend   # or a new commit"
    echo "════════════════════════════════════════════"
    exit 1
fi

echo "  OK:   stamp committed: $STAMP_FILE"

# ── Read stamp fields for display ────────────────────────────────────────────
STAMP_PHASES=$(grep "^phase:" "$STAMP_FILE" 2>/dev/null | head -1 | sed 's/phase:[[:space:]]*//' || echo "unknown")
STAMP_VALIDATED=$(grep "^validated_at:" "$STAMP_FILE" 2>/dev/null | head -1 | sed 's/validated_at:[[:space:]]*//' || echo "unknown")
STAMP_SKIPPED=$(grep "^skipped:" "$STAMP_FILE" 2>/dev/null | head -1 | sed 's/skipped:[[:space:]]*//' || echo "")

echo "  OK:   phase: $STAMP_PHASES (validated $STAMP_VALIDATED)"
[[ -n "$STAMP_SKIPPED" && "$STAMP_SKIPPED" != " " ]] && \
    echo "  WARN: skipped phases: $STAMP_SKIPPED (skipping requires human approval)"
echo ""

# ── Override-expiry check (fail-closed) ──────────────────────────────────────
# A human-authorized validation override may set override_expires: (ISO-8601 UTC).
# After that instant CI MUST fail. Fail-closed: malformed value treated as expired.
OVERRIDE_EXPIRES=$(grep "^override_expires:" "$STAMP_FILE" 2>/dev/null \
    | head -n1 | sed 's/override_expires:[[:space:]]*//' || true)

if [[ -n "$OVERRIDE_EXPIRES" ]]; then
    EXPIRY_EPOCH=$(python3 -c \
        "import sys,calendar,time; print(calendar.timegm(time.strptime(sys.argv[1], '%Y-%m-%dT%H:%M:%SZ')))" \
        "$OVERRIDE_EXPIRES" 2>/dev/null || true)

    if [[ -z "$EXPIRY_EPOCH" ]] || ! [[ "$EXPIRY_EPOCH" =~ ^[0-9]+$ ]]; then
        echo "════════════════════════════════════════════"
        echo "  FAIL: override_expires is malformed: '$OVERRIDE_EXPIRES' — treating as expired"
        echo "  Fix the stamp's override_expires or re-run validation to get a clean stamp."
        echo "════════════════════════════════════════════"
        exit 1
    fi

    NOW=$(date -u +%s)
    NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    if [[ "$NOW" -gt "$EXPIRY_EPOCH" ]]; then
        echo "════════════════════════════════════════════"
        echo "  FAIL: Validation override EXPIRED on $OVERRIDE_EXPIRES (now $NOW_ISO)."
        echo "    Re-run scripts/framework/run_framework_validation.sh and commit a fresh stamp, or"
        echo "    obtain human re-authorization with a new override_expires."
        echo "════════════════════════════════════════════"
        exit 1
    fi

    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW) / 86400 ))
    echo "  OK:   validation override active until $OVERRIDE_EXPIRES ($DAYS_LEFT day(s) remaining)"
    echo ""
fi

echo "════════════════════════════════════════════"
echo "  PASS — validation stamp is current"
echo "  Agent hash: $CONTENT_HASH"
echo "════════════════════════════════════════════"
exit 0
