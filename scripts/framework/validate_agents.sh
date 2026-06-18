#!/usr/bin/env bash
# validate_agents.sh — AI-powered cross-vendor review of agent definitions and docs.
#
# Runs agy (Gemini) for consistency/completeness and codex (OpenAI) for adversarial
# gap-finding against the agent pipeline framework files. Designed to be run:
#   - When a new agent is added or an existing agent is significantly changed
#   - When escalation paths between agents are modified
#   - When docs/AGENTS.md or docs/OVERSIGHT-RUNBOOK.md is updated
#   - Periodically as a framework health check
#
# This is the AI counterpart to check_agents_static.sh:
#   check_agents_static.sh  → structural/mechanical correctness, no AI, fast
#   validate_agents.sh      → semantic correctness (loops, gaps, contradictions), uses AI
#
# VENDOR ROLES (mirrors run_second_review.sh DECISIONS.md D4):
#   agy (Gemini)  — consistency + completeness lens
#   codex (OpenAI) — adversarial gap-finding lens
#
# Run check_agents_static.sh first; fix any structural issues before running this.
#
# Usage:
#   ./scripts/framework/validate_agents.sh
#   ./scripts/framework/validate_agents.sh --agents-dir .claude/agents
#   ./scripts/framework/validate_agents.sh --changed-only  # only changed vs HEAD~1
#   ./scripts/framework/validate_agents.sh --skip-codex    # agy only (faster)
#   ./scripts/framework/validate_agents.sh --skip-agy      # codex only
#
# Output: .claudetmp/framework/validation-YYYYMMDDTHHMMSS.md
#
# Exit codes:
#   0 — approved by both reviewers (no blocking findings)
#   1 — one or more blocking findings
#   2 — CLI unavailable or usage error

set -euo pipefail

# Resolve the repo root from the script's own location so the validation_logic.py
# delegation works regardless of the caller's cwd (SPEC-334). The ledger paths
# stay cwd-relative (OUT_DIR), preserving the existing --record/--reset contract.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VALIDATION_LOGIC="$ROOT/scripts/oversight/validation_logic.py"

AGENTS_DIR=".claude/agents"
DOCS_DIR="docs"
OUT_DIR=".claudetmp/framework"
CHANGED_ONLY=false
BASE_REF="HEAD~1"   # base for --changed-only; a release passes --base <last tag> (#130)
SKIP_AGY=false
SKIP_CODEX=false

# Dedup ledger (issue #78): external cross-vendor review is non-deterministic and
# re-generates findings every run over the same files — many of them re-phrasings
# of already-fixed findings, documented residual gaps, or filed issues. Without a
# ledger it never converges and is unusable as a gate. The verdict is keyed on
# NEW (un-ledgered) blocking findings, so convergence = "zero NEW non-noise".
# Fingerprint = (sorted files, finding-class) where finding-class is the agy
# `category` or the codex `type`. NOTE (cross-vendor limit): the two vendors use
# different class taxonomies, so the same hole may carry different class strings
# across vendors; dedup is reliable WITHIN a vendor across runs (the main
# convergence win) and best-effort across vendors.
LEDGER="$OUT_DIR/external-review-ledger.jsonl"
# Hard cap on iterate passes; hitting it with NEW findings still present escalates
# (exit 3) rather than looping — the ratchet (a human decides, never automation).
EXTERNAL_REVIEW_MAX_PASSES="${EXTERNAL_REVIEW_MAX_PASSES:-3}"
PASS_COUNT_FILE="$OUT_DIR/external-review-pass-count"

# Load project-specific config if present
PROJECT_NAME="(unnamed project)"
PROJECT_STACK="(stack not configured)"
DESIGN_PACK_PATH=""
EXTRA_REVIEW_FILES=""
[[ -f "scripts/framework/config.sh" ]] && source scripts/framework/config.sh

# --record FILES CLASS DISPOSITION — append a disposition to the dedup ledger so
# the finding is treated as "seen" on subsequent runs. Convergence = every finding
# DISPOSITIONED (not every finding fixed); a dispositioned finding is deduped and
# never re-gates. Triage rubric (#133):
#   fix       — clear, safe, low-churn fix AND the finding is non-trivial
#   filed:#NN — real design/foundational issue → tracked as an issue, no churn now
#   residual  — minor in practice AND fix-churn-risk > finding-severity → accept + move on
#   noise     — false positive / non-reproducing
# GUARDRAIL: `residual` ACCEPTS a real-but-not-worth-fixing finding — a human (or an
# explicit confidence/severity threshold) decides residual-vs-fix. The AI must NOT
# silently downgrade a real finding to `residual` to unblock itself (the anti-gaming
# line: the agent cannot mark its own homework done). CLASS = agy category / codex type.
if [[ "${1:-}" == "--record" ]]; then
    mkdir -p "$OUT_DIR"
    _files="${2:?--record needs FILES}"; _cls="${3:?--record needs CLASS}"; _disp="${4:?--record needs DISPOSITION}"
    # Ledger write delegated to validation_logic.py (SPEC-334 binding 4).
    python3 "$VALIDATION_LOGIC" record \
        --ledger "$LEDGER" --files "$_files" --class "$_cls" --disposition "$_disp" >/dev/null
    echo "Recorded to external-review ledger: [$_files] $_cls → $_disp"
    exit 0
fi

# --reset — clear ledger + pass counter when starting review of a NEW change set.
if [[ "${1:-}" == "--reset" ]]; then
    rm -f "$LEDGER" "$PASS_COUNT_FILE"
    echo "External-review ledger and pass counter reset."
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agents-dir)   AGENTS_DIR="$2"; shift 2 ;;
        --docs-dir)     DOCS_DIR="$2";   shift 2 ;;
        --changed-only) CHANGED_ONLY=true; shift ;;
        --base)         BASE_REF="$2"; shift 2 ;;
        --skip-codex)   SKIP_CODEX=true;  shift ;;
        --skip-agy)     SKIP_AGY=true;    shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# ── Check CLI availability ───────────────────────────────────────────────────
AGY_AVAILABLE=false
CODEX_AVAILABLE=false
command -v agy   &>/dev/null && AGY_AVAILABLE=true  || true
command -v codex &>/dev/null && CODEX_AVAILABLE=true || true

if ! $SKIP_AGY && ! $AGY_AVAILABLE; then
    echo "WARN: agy not found — agy review will be skipped"
fi
if ! $SKIP_CODEX && ! $CODEX_AVAILABLE; then
    echo "WARN: codex not found — codex review will be skipped"
fi

if (! $AGY_AVAILABLE || $SKIP_AGY) && (! $CODEX_AVAILABLE || $SKIP_CODEX); then
    echo "ERROR: neither agy nor codex available/enabled — cannot run AI review" >&2
    echo "  Run check_agents_static.sh for the static-only check." >&2
    exit 2
fi

# ── External-reviewer timeout (agy/codex can hang; the gate must NOT) ──────────
# A hung agy/codex once stalled the entire release gate indefinitely — there was
# no cap on the external CLI call. Wrap every reviewer invocation in a hard
# timeout. macOS ships no `timeout` by default, so prefer timeout/gtimeout when
# present and otherwise fall back to a portable background-poll-and-kill.
# Override per-call budget with AI_REVIEW_TIMEOUT (seconds).
AI_REVIEW_TIMEOUT="${AI_REVIEW_TIMEOUT:-300}"
_TIMEOUT_BIN=""
if command -v timeout &>/dev/null; then _TIMEOUT_BIN="timeout"
elif command -v gtimeout &>/dev/null; then _TIMEOUT_BIN="gtimeout"; fi

# run_capped <secs> <outfile> <cmd...> → 0 ok | 124 timeout | other = cmd's rc.
# stdout of the command is written to <outfile> (stderr discarded, as before).
run_capped() {
    local secs="$1" out="$2"; shift 2
    if [[ -n "$_TIMEOUT_BIN" ]]; then
        "$_TIMEOUT_BIN" "$secs" "$@" > "$out" 2>/dev/null
        return $?
    fi
    # Portable fallback: background the call, poll, escalate TERM→KILL at the cap.
    "$@" > "$out" 2>/dev/null &
    local pid=$! waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if (( waited >= secs )); then
            kill -TERM "$pid" 2>/dev/null
            sleep 2
            kill -KILL "$pid" 2>/dev/null
            wait "$pid" 2>/dev/null
            return 124
        fi
        sleep 3
        waited=$(( waited + 3 ))
    done
    wait "$pid"
    return $?
}

mkdir -p "$OUT_DIR"
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
OUTFILE="$OUT_DIR/validation-${TIMESTAMP}.md"

# Count this pass (reset with --reset for a new change set).
PASS_NUM=$(( $(cat "$PASS_COUNT_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$PASS_NUM" > "$PASS_COUNT_FILE"

echo "=== Agent pipeline validation: ${TIMESTAMP} (pass ${PASS_NUM}/${EXTERNAL_REVIEW_MAX_PASSES}) ==="
echo "  Agents dir:  $AGENTS_DIR"
echo "  Docs dir:    $DOCS_DIR"
echo "  Output:      $OUTFILE"
echo ""

# ── Collect files ────────────────────────────────────────────────────────────
collect_files() {
    local content=""
    local files=()

    if $CHANGED_ONLY; then
        while IFS= read -r f; do
            [[ -f "$f" ]] && files+=("$f")
        done < <(git diff --name-only "$BASE_REF" -- "$AGENTS_DIR" "$DOCS_DIR" 2>/dev/null || true)
        if [[ ${#files[@]} -eq 0 ]]; then
            echo "WARN: --changed-only specified but no changed agent/doc files vs $BASE_REF — using all files" >&2
            CHANGED_ONLY=false
        fi
    fi

    if ! $CHANGED_ONLY; then
        while IFS= read -r -d '' f; do files+=("$f"); done \
            < <(find "$AGENTS_DIR" -name '*.md' -print0)
        [[ -f "$DOCS_DIR/AGENTS.md" ]]            && files+=("$DOCS_DIR/AGENTS.md")
        [[ -f "$DOCS_DIR/OVERSIGHT-RUNBOOK.md" ]] && files+=("$DOCS_DIR/OVERSIGHT-RUNBOOK.md")
        # Include design pack / extra files declared in config.sh
        [[ -n "$DESIGN_PACK_PATH" && -f "$DESIGN_PACK_PATH" ]] && files+=("$DESIGN_PACK_PATH")
        for ef in $EXTRA_REVIEW_FILES; do
            [[ -f "$ef" ]] && files+=("$ef")
        done
    fi

    echo "Collecting ${#files[@]} files..." >&2
    for f in "${files[@]}"; do
        content+="=== FILE: $f ===
$(cat "$f")

"
    done
    echo "$content"
}

REVIEW_PACKAGE=$(collect_files)

# Known-issues context: feed the cross-vendor reviewers the open GitHub issues so
# they SKIP already-tracked findings instead of re-surfacing them (root-cause fix
# for convergence churn; complements the dedup ledger).
KNOWN_ISSUES=""
if [[ "${HOS_FEED_KNOWN_ISSUES:-1}" == "1" ]] && command -v gh >/dev/null 2>&1; then
    KNOWN_ISSUES=$(gh issue list --state open --limit 100 \
        --json number,title -q '.[] | "- #\(.number): \(.title)"' 2>/dev/null || true)
fi
[[ -z "$KNOWN_ISSUES" ]] && KNOWN_ISSUES="(none available)"
KNOWN_ISSUES_BLOCK="=== KNOWN, ALREADY-TRACKED ISSUES — do NOT re-report these ===
The findings below are already filed as GitHub issues and tracked. Do NOT report a
finding already covered by one of these; only surface issues NOT represented below.
${KNOWN_ISSUES}
"

# ── agy: consistency and completeness ───────────────────────────────────────
run_agy() {
    local prompt
    prompt="You are reviewing AI agent definition files and documentation for a multi-agent software development pipeline. Project: ${PROJECT_NAME} (${PROJECT_STACK}). Your lens is CONSISTENCY and COMPLETENESS.

Check for:
1. ESCALATION LOOPS — any agent A that escalates to B which escalates back to A (directly or transitively)
2. DEAD ENDS — agent escalates to a role with no defined handler
3. CROSS-FILE MISMATCHES — when agent A says it sends X to agent B, does B's definition describe receiving and handling X?
4. FILE PATH INCONSISTENCY — any doc path referenced differently across files (e.g. docs/design/UX-DESIGN-READINESS.md vs design/UX-DESIGN-READINESS.md)
5. PIPELINE ORDERING PROBLEMS — does each agent's listed inputs exist as outputs from the preceding agent?
6. INVOCATION GAPS — scenarios where a design decision or gap could arise but no agent is instructed to handle it
7. TERMINOLOGY DRIFT — same concept named differently in different files

For each finding, name the exact files and lines affected. Be specific enough that a developer can fix the problem without additional investigation.

${KNOWN_ISSUES_BLOCK}
=== AGENT FILES AND DOCS ===
${REVIEW_PACKAGE}

Return JSON only — no prose outside the JSON block:
{
  \"reviewer\": \"agy\",
  \"lens\": \"consistency-completeness\",
  \"findings\": [
    {
      \"severity\": \"blocking|warning\",
      \"category\": \"loop|dead-end|mismatch|path|ordering|gap|terminology\",
      \"files\": [\"file1.md\", \"file2.md\"],
      \"description\": \"precise description — what is wrong and where\",
      \"fix\": \"specific change needed\"
    }
  ],
  \"verdict\": \"approve|request_changes\",
  \"summary\": \"one paragraph overall assessment\"
}"

    local tmpfile outfile
    tmpfile=$(mktemp /tmp/validate_agents_agy_XXXXXX)
    outfile=$(mktemp /tmp/validate_agents_agy_out_XXXXXX)
    echo "$prompt" > "$tmpfile"
    local result rc=0
    run_capped "$AI_REVIEW_TIMEOUT" "$outfile" agy -p "$(cat "$tmpfile")" || rc=$?
    if [[ $rc -eq 0 ]]; then
        result=$(cat "$outfile")
    elif [[ $rc -eq 124 ]]; then
        echo "  WARN: agy timed out after ${AI_REVIEW_TIMEOUT}s — recorded as error, continuing" >&2
        result='{"reviewer":"agy","error":"agy timed out after '"$AI_REVIEW_TIMEOUT"'s","findings":[],"verdict":"error","summary":"agy exceeded the '"$AI_REVIEW_TIMEOUT"'s timeout (hang guard)"}'
    else
        result='{"reviewer":"agy","error":"agy invocation failed","findings":[],"verdict":"error","summary":"agy failed"}'
    fi
    rm -f "$tmpfile" "$outfile"
    echo "$result"
}

# ── codex: adversarial gap-finding ──────────────────────────────────────────
run_codex() {
    local prompt
    prompt="You are adversarially reviewing AI agent pipeline documentation for a project called ${PROJECT_NAME}. Your job is to find every gap, contradiction, and failure mode. Break this design.

Attack vectors to probe:
1. SCOPE CREEP — can any agent's 'additive'/'clarifying' classification be exploited to make structural changes without human approval? Are change-type boundaries tight enough?
2. SINGLE POINTS OF FAILURE — if any startup-phase agent misses something in its initial audit, what is the recovery path? Is it clearly defined?
3. HUMAN GATE BYPASS — are there decisions that should require human approval but are routed to an agent instead?
4. RESPONSIBILITY VACUUM — find scenarios where a gap or conflict arises but no agent is clearly responsible for resolving it
5. CONTRADICTIONS — find any case where two agent files give conflicting instructions for the exact same scenario
6. UNDERSPECIFIED HANDOFFS — 'notify X' or 'inform Y' with no defined input protocol for the receiver
7. MISSING LOOP EXITS — any agent iteration loop that could run indefinitely with no defined exit condition

For each attack, describe the specific scenario that causes failure, not just the category.

${KNOWN_ISSUES_BLOCK}
=== FILES TO ATTACK ===
${REVIEW_PACKAGE}

Return JSON only:
{
  \"reviewer\": \"codex\",
  \"lens\": \"adversarial-gaps\",
  \"attacks\": [
    {
      \"severity\": \"critical|high|medium\",
      \"type\": \"scope-creep|single-point-failure|human-gate-bypass|vacuum|contradiction|underspecified|no-exit\",
      \"files\": [\"file1.md\"],
      \"scenario\": \"specific scenario where this fails\",
      \"impact\": \"what goes wrong\",
      \"fix\": \"specific change to close the gap\"
    }
  ],
  \"verdict\": \"approve|request_changes\",
  \"summary\": \"one paragraph overall assessment\"
}"

    local tmpfile outfile
    tmpfile=$(mktemp /tmp/validate_agents_codex_XXXXXX)
    outfile=$(mktemp /tmp/validate_agents_codex_out_XXXXXX)
    echo "$prompt" > "$tmpfile"
    local result rc=0
    # codex reads the prompt on stdin; run_capped runs codex with stdin redirected.
    run_capped "$AI_REVIEW_TIMEOUT" "$outfile" sh -c 'exec codex exec < "$1"' _ "$tmpfile" || rc=$?
    if [[ $rc -eq 0 ]]; then
        result=$(cat "$outfile")
    elif [[ $rc -eq 124 ]]; then
        echo "  WARN: codex timed out after ${AI_REVIEW_TIMEOUT}s — recorded as error, continuing" >&2
        result='{"reviewer":"codex","error":"codex timed out after '"$AI_REVIEW_TIMEOUT"'s","attacks":[],"verdict":"error","summary":"codex exceeded the '"$AI_REVIEW_TIMEOUT"'s timeout (hang guard)"}'
    else
        result='{"reviewer":"codex","error":"codex invocation failed","attacks":[],"verdict":"error","summary":"codex failed"}'
    fi
    rm -f "$tmpfile" "$outfile"
    echo "$result"
}

# ── Execute reviewers and write output ──────────────────────────────────────
{
    printf "# Agent Pipeline Validation\n"
    printf "Timestamp: %s\n" "$TIMESTAMP"
    printf "verdict: pending\n"
    printf "highest_severity: none\n"
    printf "blocking_count: 0\n"
    printf "new_blocking_count: 0\n\n"
} > "$OUTFILE"

AGY_OUT=""
CODEX_OUT=""

if ! $SKIP_AGY && $AGY_AVAILABLE; then
    echo "Running agy (consistency + completeness)..."
    AGY_OUT=$(run_agy)
    {
        echo "## agy — Consistency + Completeness"
        echo '```json'
        echo "$AGY_OUT"
        echo '```'
        echo ""
    } >> "$OUTFILE"
    echo "  done"
else
    echo "## agy — SKIPPED" >> "$OUTFILE"
fi

if ! $SKIP_CODEX && $CODEX_AVAILABLE; then
    echo "Running codex (adversarial gap-finding)..."
    CODEX_OUT=$(run_codex)
    {
        echo "## codex — Adversarial Gap Analysis"
        echo '```json'
        echo "$CODEX_OUT"
        echo '```'
        echo ""
    } >> "$OUTFILE"
    echo "  done"
else
    echo "## codex — SKIPPED" >> "$OUTFILE"
fi

echo ""

# ── Finalize verdict header (ledger-aware: verdict keyed on NEW findings) ────
# Dedup fingerprinting + verdict aggregation delegated to validation_logic.py
# (SPEC-334). --strict-empty: an empty parse yields verdict=error here (agents
# behavior, binding 7). The pass-cap / exit-code decision stays in this shell
# below (binding 3) — the module never emits verdict exit codes.
python3 "$VALIDATION_LOGIC" process \
    --file "$OUTFILE" --ledger "$LEDGER" --strict-empty

# ── Print summary ────────────────────────────────────────────────────────────
echo ""
echo "Output: $OUTFILE"
echo ""

VERDICT=$(grep '^verdict:' "$OUTFILE" | head -1 | awk '{print $2}')
BLOCKING=$(grep '^blocking_count:' "$OUTFILE" | head -1 | awk '{print $2}')
NEW_BLOCKING=$(grep '^new_blocking_count:' "$OUTFILE" | head -1 | awk '{print $2}')

if [[ "$VERDICT" == "approve" ]]; then
    echo "════════════════════════════════════════════"
    echo "  PASS — converged (zero NEW blocking findings; ${BLOCKING:-0} total, all ledgered)"
    echo "════════════════════════════════════════════"
    rm -f "$PASS_COUNT_FILE"   # converged — reset for the next change set
    STAMP_DIR="scripts/framework/validation-stamps"
    mkdir -p "$STAMP_DIR"
    printf "validated: %s\nphase: 2-agents\nresult: pass\n" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$STAMP_DIR/phase2.stamp"
    exit 0
elif [[ "$PASS_NUM" -ge "$EXTERNAL_REVIEW_MAX_PASSES" ]]; then
    echo "════════════════════════════════════════════"
    echo "  ESCALATE — pass cap (${EXTERNAL_REVIEW_MAX_PASSES}) hit, still ${NEW_BLOCKING:-?} NEW blocking"
    echo "════════════════════════════════════════════"
    echo "  External review did not converge within the cap. Do NOT keep looping —"
    echo "  a human decides whether to fix, accept, or file. Review: $OUTFILE"
    exit 3
else
    echo "════════════════════════════════════════════"
    echo "  FAIL — verdict=${VERDICT} new_blocking=${NEW_BLOCKING:-?} (total ${BLOCKING:-?}, pass ${PASS_NUM}/${EXTERNAL_REVIEW_MAX_PASSES})"
    echo "════════════════════════════════════════════"
    echo "  Triage the NEW findings in: $OUTFILE"
    echo "  For each: fix-in-place (mechanical), or file an issue (structural), then record it:"
    echo "    $0 --record \"file1.md,file2.md\" <category|type> <fixed|filed:#NN|residual|noise>"
    echo "  Re-run. Stop when zero NEW findings, or at the pass cap (then escalate)."
    exit 1
fi
