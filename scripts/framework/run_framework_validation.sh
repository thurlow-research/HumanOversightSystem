#!/usr/bin/env bash
# run_framework_validation.sh — run the full framework validation suite.
#
# Run before committing any change to agent files, pipeline docs, or
# the framework scripts themselves.
#
# Sequence:
#   1.  Static check (check_agents_static.sh) — fast, no AI, blocks on findings
#   1.5 Self-review  (validate_self.sh)        — Claude/Opus pre-flush before
#       spending external budget; skipped if absent or via --skip-self
#   2.  AI review    (validate_agents.sh)      — agy + codex, blocks on findings
#
# Usage:
#   ./scripts/framework/run_framework_validation.sh
#   ./scripts/framework/run_framework_validation.sh --static-only   # skip AI review
#   ./scripts/framework/run_framework_validation.sh --changed-only  # only changed files vs HEAD~1
#   ./scripts/framework/run_framework_validation.sh --skip-codex    # agy only
#   ./scripts/framework/run_framework_validation.sh --skip-agy      # codex only
#
# Exit codes:
#   0 — all checks pass
#   1 — findings that block commit
#   2 — tooling error

set -euo pipefail

STATIC_ONLY=false
SKIP_DOCS=false
SKIP_COMPLIANCE=false
SKIP_SELF=false
CHANGED_ONLY=""
BASE_ARG=""
SKIP_CODEX=""
SKIP_AGY=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --static-only)      STATIC_ONLY=true;             shift ;;
        --skip-docs)        SKIP_DOCS=true;               shift ;;
        --skip-compliance)  SKIP_COMPLIANCE=true;         shift ;;
        --skip-self)        SKIP_SELF=true;               shift ;;
        --changed-only)     CHANGED_ONLY="--changed-only"; shift ;;
        --base)             BASE_ARG="--base $2";          shift 2 ;;
        --skip-codex)       SKIP_CODEX="--skip-codex";    shift ;;
        --skip-agy)         SKIP_AGY="--skip-agy";        shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "══════════════════════════════════════════════════"
echo "  Framework Validation Suite"
echo "══════════════════════════════════════════════════"
echo ""

# ── Phase 1: Static check ────────────────────────────────────────────────────
echo "Phase 1 — Static consistency check"
echo ""
if ! bash "$SCRIPT_DIR/check_agents_static.sh"; then
    echo ""
    echo "  Static check FAILED. Fix findings above before running AI review."
    exit 1
fi
echo ""

if $STATIC_ONLY; then
    echo "  --static-only: skipping AI review"
    STAMP_DIR="$SCRIPT_DIR/validation-stamps"
    mkdir -p "$STAMP_DIR"
    printf "validated: %s\nphases: 1-static\nskipped: 2-agents 3-docs 4-spec-compliance\nresult: pass\n" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STAMP_DIR/all-phases.stamp"
    echo ""
    echo "  PASS — static checks clean"
    echo "  Stamp written: $STAMP_DIR/all-phases.stamp"
    echo "  Note: AI phases skipped — stamp records skipped phases."
    exit 0
fi

# ── Phase 1.5: Opus self-review (cheap pre-flush before external budget) ─────
# Runs Claude/Opus over the framework files to catch obvious problems before
# spending the metered external agy/codex budget. Skipped gracefully if the
# script is absent or claude CLI is unavailable. --skip-self to bypass.
if ! $SKIP_SELF && [[ -f "$SCRIPT_DIR/validate_self.sh" ]]; then
    echo "Phase 1.5 — Opus self-review (pre-external)"
    echo ""
    self_rc=0
    bash "$SCRIPT_DIR/validate_self.sh" $CHANGED_ONLY $BASE_ARG || self_rc=$?
    if [[ "$self_rc" -eq 3 ]]; then
        echo ""
        echo "  Self-review hit the pass cap without converging — a HUMAN must"
        echo "  decide (fix / accept / file) before the external pass. Not auto-retried."
        exit 3
    elif [[ "$self_rc" -ne 0 ]]; then
        echo ""
        echo "  Opus self-review found NEW blocking issues — triage them (fix-in-place"
        echo "  or file an issue), record dispositions, and re-run until converged."
        echo "  (Use --skip-self to bypass, e.g. when claude CLI is unavailable.)"
        exit 1
    fi
    echo ""
fi

# ── Phase 1.6: Scripts review (the gate now covers what it ships) ────────────
# validate_self/validate_agents cover agents+docs+contract; this covers the
# framework's SCRIPTS (installers, gates, validators, cut_release) with a script
# lens (bash correctness, portability, fetch-execute security, fail-open). Same
# convergence machinery (ledger, known-issues, --base). --skip-self bypasses it
# too (it needs the claude CLI). (#89)
if ! $SKIP_SELF && [[ -f "$SCRIPT_DIR/validate_scripts.sh" ]]; then
    echo "Phase 1.6 — Scripts review (bash/portability/fail-open lens)"
    echo ""
    scripts_rc=0
    bash "$SCRIPT_DIR/validate_scripts.sh" $CHANGED_ONLY $BASE_ARG $SKIP_CODEX $SKIP_AGY || scripts_rc=$?
    if [[ "$scripts_rc" -eq 3 ]]; then
        echo ""
        echo "  Scripts review hit the pass cap without converging — a HUMAN decides"
        echo "  (fix / accept / file). Not auto-retried."
        exit 3
    elif [[ "$scripts_rc" -ne 0 ]]; then
        echo ""
        echo "  Scripts review found NEW blocking issues — triage (fix/file), record"
        echo "  via validate_scripts.sh --record, and re-run until converged."
        exit 1
    fi
    echo ""
fi

# ── Phase 2: Agent semantic review ──────────────────────────────────────────
echo "Phase 2 — Agent semantic review (agy + codex)"
echo ""

AI_ARGS=""
[[ -n "$CHANGED_ONLY" ]] && AI_ARGS="$AI_ARGS $CHANGED_ONLY"
[[ -n "$BASE_ARG" ]] && AI_ARGS="$AI_ARGS $BASE_ARG"
[[ -n "$SKIP_CODEX"   ]] && AI_ARGS="$AI_ARGS $SKIP_CODEX"
[[ -n "$SKIP_AGY"     ]] && AI_ARGS="$AI_ARGS $SKIP_AGY"

agents_rc=0
bash "$SCRIPT_DIR/validate_agents.sh" $AI_ARGS || agents_rc=$?
if [[ "$agents_rc" -eq 3 ]]; then
    echo ""
    echo "  External review hit the pass cap without converging — a HUMAN must"
    echo "  decide (fix / accept / file) on the remaining NEW findings. Not auto-retried."
    exit 3
elif [[ "$agents_rc" -ne 0 ]]; then
    echo ""
    echo "  Agent semantic review found NEW blocking findings. Triage each (fix-in-place"
    echo "  mechanical, or file an issue structural), record dispositions with"
    echo "  validate_agents.sh --record, and re-run until converged (zero NEW)."
    echo "  Invoke framework-validator agent to triage and fix before committing."
    exit 1
fi

echo ""

# ── Phase 3: Documentation coverage review ──────────────────────────────────
if $SKIP_DOCS; then
    echo "Phase 3 — Documentation coverage review (skipped via --skip-docs)"
else
    echo "Phase 3 — Documentation coverage review (agy + codex)"
    echo ""

    DOC_ARGS=""
    [[ -n "$SKIP_CODEX" ]] && DOC_ARGS="$DOC_ARGS $SKIP_CODEX"

    if ! bash "$SCRIPT_DIR/validate_docs.sh" $DOC_ARGS; then
        echo ""
        echo "  Documentation coverage review found issues."
        echo "  Invoke doc-validator agent to review and fix before committing."
        exit 1
    fi
fi

# ── Phase 4: Spec compliance ─────────────────────────────────────────────────
if $SKIP_COMPLIANCE; then
    echo "Phase 4 — Spec compliance check (skipped via --skip-compliance)"
else
    echo "Phase 4 — Spec compliance check (governance requirements + decisions)"
    echo ""

    COMP_ARGS=""
    [[ -n "$SKIP_CODEX" ]] && COMP_ARGS="$COMP_ARGS $SKIP_CODEX"

    if ! bash "$SCRIPT_DIR/validate_spec_compliance.sh" $COMP_ARGS; then
        echo ""
        echo "  Spec compliance failures found."
        echo "  Invoke spec-compliance-validator agent to triage and fix."
        exit 1
    fi
fi

echo ""
echo "══════════════════════════════════════════════════"
echo "  All framework checks passed — clear to commit."
echo "══════════════════════════════════════════════════"

# Write the combined stamp — only written when ALL non-skipped phases pass.
# This is the file the PR pipeline checks.
STAMP_DIR="$SCRIPT_DIR/validation-stamps"
mkdir -p "$STAMP_DIR"
PHASES_RUN="1-static"
$STATIC_ONLY || PHASES_RUN="$PHASES_RUN 2-agents"
( ! $STATIC_ONLY && ! $SKIP_DOCS )       && PHASES_RUN="$PHASES_RUN 3-docs"
( ! $STATIC_ONLY && ! $SKIP_COMPLIANCE ) && PHASES_RUN="$PHASES_RUN 4-spec-compliance"
printf "validated: %s\nphases: %s\nskipped: %s\nresult: pass\n" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$PHASES_RUN" \
    "$(
        skipped=""
        $STATIC_ONLY     && skipped="${skipped}2-agents 3-docs 4-spec-compliance"
        $SKIP_DOCS       && skipped="${skipped}3-docs "
        $SKIP_COMPLIANCE && skipped="${skipped}4-spec-compliance "
        echo "${skipped% }"
    )" \
    > "$STAMP_DIR/all-phases.stamp"
echo "  Stamp written: $STAMP_DIR/all-phases.stamp"
echo "  Commit the stamp file along with your changes before pushing."
exit 0
