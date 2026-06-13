#!/usr/bin/env bash
# capture_session.sh — session turn log, summary, and watermark management.
#
# Three modes:
#
#   --log FILE MSG    Append a turn entry to the session log.
#                     FILE: the file changed in this turn (or "session" for meta-turns)
#                     MSG:  one-line description of what was done
#
#   --summarize       Generate a session summary from the turn log since the last
#                     watermark (or from the beginning if no watermark exists).
#                     Writes prompts/sessions/<session-id>-summary.md.
#                     Requires agy or codex to be authenticated.
#
#   --watermark       Mark the current position in the log as summarized.
#                     Updates prompts/sessions/<session-id>.watermark.
#
#   --status          Show current session log size, last watermark, and summary status.
#
# Session ID is derived from the current git branch name + date.
# All session artifacts live under prompts/sessions/.
#
# The session summary serves two purposes:
#   1. Human comprehension — reviewer can understand what happened without replaying turns
#   2. Expedited rerun — summary is precise enough to serve as a one-shot prompt
#
# Usage:
#   bash scripts/capture_session.sh --log parking/views.py "Added booking gate"
#   bash scripts/capture_session.sh --summarize
#   bash scripts/capture_session.sh --watermark
#   bash scripts/capture_session.sh --status

set -euo pipefail

[[ -f .env ]] && set -o allexport && source .env && set +o allexport 2>/dev/null || true

GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }

# ── Session identity ──────────────────────────────────────────────────────────
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo "detached")
DATE=$(date +%Y-%m-%d)
SESSION_ID="${DATE}-${BRANCH}"

SESSION_DIR="prompts/sessions"
mkdir -p "$SESSION_DIR"

LOG_FILE="${SESSION_DIR}/${SESSION_ID}.log"
WATERMARK_FILE="${SESSION_DIR}/${SESSION_ID}.watermark"
SUMMARY_FILE="${SESSION_DIR}/${SESSION_ID}-summary.md"

MODE=""
LOG_TARGET=""
LOG_MSG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --log)       MODE="log"; LOG_TARGET="$2"; LOG_MSG="$3"; shift 3 ;;
        --summarize) MODE="summarize"; shift ;;
        --watermark) MODE="watermark"; shift ;;
        --status)    MODE="status"; shift ;;
        *) shift ;;
    esac
done

# ── Mode: log ─────────────────────────────────────────────────────────────────
if [[ "$MODE" == "log" ]]; then
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "${TIMESTAMP} | ${LOG_TARGET} | ${LOG_MSG}" >> "$LOG_FILE"
    ok "Logged: ${LOG_TARGET} — ${LOG_MSG}"
    exit 0
fi

# ── Mode: status ──────────────────────────────────────────────────────────────
if [[ "$MODE" == "status" ]]; then
    echo ""
    echo "  Session: ${SESSION_ID}"
    echo "  Log:     ${LOG_FILE}"
    if [[ -f "$LOG_FILE" ]]; then
        LINE_COUNT=$(wc -l < "$LOG_FILE")
        echo "  Turns logged: ${LINE_COUNT}"
    else
        echo "  Turns logged: 0 (no log yet)"
    fi
    if [[ -f "$WATERMARK_FILE" ]]; then
        WATERMARK_LINE=$(cat "$WATERMARK_FILE")
        echo "  Last watermark at line: ${WATERMARK_LINE}"
    else
        echo "  Last watermark: none (will summarize full log)"
    fi
    if [[ -f "$SUMMARY_FILE" ]]; then
        echo "  Summary: ${SUMMARY_FILE} (exists)"
    else
        echo "  Summary: not yet generated"
    fi
    echo ""
    exit 0
fi

# ── Mode: watermark ───────────────────────────────────────────────────────────
if [[ "$MODE" == "watermark" ]]; then
    if [[ ! -f "$LOG_FILE" ]]; then
        warn "No log file found at ${LOG_FILE} — nothing to watermark"
        exit 0
    fi
    LINE_COUNT=$(wc -l < "$LOG_FILE")
    echo "$LINE_COUNT" > "$WATERMARK_FILE"
    ok "Watermark set at line ${LINE_COUNT} of ${LOG_FILE}"
    exit 0
fi

# ── Mode: summarize ───────────────────────────────────────────────────────────
if [[ "$MODE" == "summarize" ]]; then
    if [[ ! -f "$LOG_FILE" ]]; then
        warn "No log file found at ${LOG_FILE}"
        exit 1
    fi

    # Determine range to summarize: from watermark to end
    START_LINE=1
    if [[ -f "$WATERMARK_FILE" ]]; then
        START_LINE=$(( $(cat "$WATERMARK_FILE") + 1 ))
    fi

    TOTAL_LINES=$(wc -l < "$LOG_FILE")
    if [[ $START_LINE -gt $TOTAL_LINES ]]; then
        warn "No new turns since last watermark (watermark at ${START_LINE}, log has ${TOTAL_LINES} lines)"
        exit 0
    fi

    UNSUMMARIZED=$(tail -n "+${START_LINE}" "$LOG_FILE")
    TURN_COUNT=$(echo "$UNSUMMARIZED" | wc -l)

    info "Summarizing ${TURN_COUNT} turns (lines ${START_LINE}–${TOTAL_LINES})..."

    PROMPT="You are summarizing a software development session for two purposes:
1. Human comprehension — the summary should let a reviewer understand what happened without replaying every turn
2. Expedited rerun — the summary should be precise enough to serve as a one-shot prompt that could reproduce the session's outputs

Session: ${SESSION_ID}
Branch: ${BRANCH}

Turn log (each line: timestamp | file | description):
${UNSUMMARIZED}

Write a session summary in this format:

## Session Summary: ${SESSION_ID}

### Intent
[What was the overall goal of this session? 1-2 sentences.]

### Changes made
[Bulleted list: what was changed, file by file, with enough detail to understand each change without reading the code]

### Decisions made
[Any non-obvious choices made during the session — tradeoffs, alternatives considered, rationale]

### Deferred items
[Things that were explicitly left for later or out of scope]

### Rerun prompt
[A precise, self-contained prompt that could reproduce this session's work. Write it as if briefing a fresh agent. Include specific file names, what to change, and any constraints that shaped the decisions.]

Keep the summary factual and specific. Avoid filler. The Rerun prompt section is the most important — it should be detailed enough that an agent could execute the session from scratch."

    if command -v agy &>/dev/null; then
        SUMMARY=$(agy -p "$PROMPT" 2>/dev/null || echo "")
    elif command -v codex &>/dev/null; then
        SUMMARY=$(echo "$PROMPT" | codex --quiet 2>/dev/null || echo "")
    else
        warn "Neither agy nor codex available — cannot generate summary"
        exit 1
    fi

    if [[ -z "$SUMMARY" ]]; then
        warn "Summary generation failed — CLI returned empty output"
        exit 1
    fi

    cat > "$SUMMARY_FILE" << SUMMARYEOF
---
session: ${SESSION_ID}
branch: ${BRANCH}
turns_summarized: ${TURN_COUNT}
log_lines: ${START_LINE}–${TOTAL_LINES}
generated: $(date -u +"%Y-%m-%dT%H:%M:%SZ")
---

${SUMMARY}
SUMMARYEOF

    ok "Summary written: ${SUMMARY_FILE}"
    info "Run --watermark to mark this position in the log"
    exit 0
fi

echo "Usage: $0 --log FILE MSG | --summarize | --watermark | --status"
exit 1
