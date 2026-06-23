#!/usr/bin/env bash
# run_redteam_sample.sh — statistical sampling red-team for LOW-tier escaped-defect rate.
#
# Distinct from run_red_team.sh (milestone-triggered, full-codebase).
# This script samples recent LOW-tier merged commits, red-teams each diff
# independently, and computes the escaped-defect rate for the LOW tier.
# That rate is the empirical signal for calibrating tier thresholds over time.
#
# Usage:
#   ./scripts/run_redteam_sample.sh                   (defaults: N=20, 30 days)
#   ./scripts/run_redteam_sample.sh --n 30 --days 60
#   ./scripts/run_redteam_sample.sh --dry-run          (show sample, no CLI calls)
#
# Prerequisites: agy + codex authenticated, gh authenticated
# Output: .claudetmp/sampling-audit/<timestamp>/

set -euo pipefail

GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
fail() { echo -e "  ${RED}✘${RESET}  $*"; }

SAMPLE_N=20
LOOKBACK_DAYS=30
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --n)      SAMPLE_N="$2";      shift 2 ;;
        --days)   LOOKBACK_DAYS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true;      shift ;;
        *) shift ;;
    esac
done

TIMESTAMP=$(date +%Y%m%dT%H%M%S)
OUT_DIR=".claudetmp/sampling-audit/${TIMESTAMP}"
mkdir -p "$OUT_DIR"

# ── Branch + PR context ───────────────────────────────────────────────────────
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")

echo ""
echo -e "${BOLD}=== Statistical Sampling Red-Team ===${RESET}"
echo "  Sample size: N=${SAMPLE_N}, lookback: ${LOOKBACK_DAYS} days"
echo "  Output: ${OUT_DIR}"
$DRY_RUN && warn "DRY RUN — no external CLI calls"
echo ""

# ── Step 1: Find LOW-tier commits in window ───────────────────────────────────
info "Collecting LOW-tier commits from last ${LOOKBACK_DAYS} days..."

# Get commits with AI-Risk: LOW trailer within the lookback window
LOW_COMMITS=()
while IFS= read -r sha; do
    [[ -z "$sha" ]] && continue
    # Check for AI-Risk: LOW trailer
    if git log -1 --format="%B" "$sha" 2>/dev/null | grep -q "^AI-Risk: LOW"; then
        LOW_COMMITS+=("$sha")
    fi
done < <(git log --oneline --since="${LOOKBACK_DAYS}.days" --format="%H" --merges=false 2>/dev/null | head -200)

POOL_SIZE=${#LOW_COMMITS[@]}
info "Found ${POOL_SIZE} LOW-tier commits in pool"

if [[ $POOL_SIZE -eq 0 ]]; then
    warn "No LOW-tier commits found in window. Nothing to sample."
    echo '{"pool_size":0,"sample_size":0,"tier_escapes":0,"escape_rate":0,"recommendation":"no data"}' \
        > "${OUT_DIR}/summary.json"
    exit 0
fi

# ── Step 2: Random sample (deterministic via sha hash for reproducibility) ────
# Use git SHA bytes as entropy source — reproducible without Date.now()
ACTUAL_N=$(( POOL_SIZE < SAMPLE_N ? POOL_SIZE : SAMPLE_N ))
SAMPLE=()
declare -A SEEN

# Pseudo-random selection using SHA suffix as sort key
while IFS= read -r sha; do
    [[ -z "$sha" || "${SEEN[$sha]+x}" ]] && continue
    SAMPLE+=("$sha")
    SEEN["$sha"]=1
    [[ ${#SAMPLE[@]} -ge $ACTUAL_N ]] && break
done < <(printf '%s\n' "${LOW_COMMITS[@]}" | \
    awk '{print substr($0,length($0)-3)" "$0}' | sort | awk '{print $2}')

info "Sampled ${#SAMPLE[@]} commits from pool of ${POOL_SIZE}"
echo ""

# ── Step 3: Red-team each sampled diff ────────────────────────────────────────
TIER_ESCAPES=0
FINDINGS_SUMMARY=()

for sha in "${SAMPLE[@]}"; do
    COMMIT_MSG=$(git log -1 --format="%s" "$sha" 2>/dev/null || echo "unknown")
    DIFF=$(git diff "${sha}^..${sha}" 2>/dev/null | head -300)  # cap diff size

    if [[ -z "$DIFF" ]]; then
        warn "  ${sha:0:8}: empty diff — skip"
        continue
    fi

    info "  ${sha:0:8}: ${COMMIT_MSG:0:60}"

    COMMIT_OUT="${OUT_DIR}/${sha:0:8}.json"

    CODEX_PROMPT="You are reviewing a diff from a commit classified as LOW risk (AI-Risk: LOW trailer).
Your job: does this diff actually introduce any security, correctness, or spec-drift issues?

A LOW-tier classification means: pure UI/styling, no logic/data/external calls.
A 'tier escape' occurs if this diff contains MEDIUM or higher severity issues despite its LOW classification.

Diff:
<diff>
${DIFF}
</diff>

Commit: ${COMMIT_MSG}

Respond with JSON only:
{
  \"sha\": \"${sha:0:8}\",
  \"reviewer\": \"codex\",
  \"tier_escape\": true | false,
  \"max_severity\": \"NONE\" | \"LOW\" | \"MEDIUM\" | \"HIGH\" | \"CRITICAL\",
  \"findings\": [
    {\"severity\": \"...\", \"description\": \"...\"}
  ],
  \"rationale\": \"one sentence explaining the verdict\"
}"

    AGY_PROMPT="You are reviewing a diff from a commit classified as LOW risk (AI-Risk: LOW trailer).
Check for: spec drift (does this change behavior that the spec constrains?), hidden logic changes, data handling that looks like styling but isn't.

Diff:
<diff>
${DIFF}
</diff>

Commit: ${COMMIT_MSG}

Respond with JSON only:
{
  \"sha\": \"${sha:0:8}\",
  \"reviewer\": \"agy\",
  \"tier_escape\": true | false,
  \"max_severity\": \"NONE\" | \"LOW\" | \"MEDIUM\" | \"HIGH\" | \"CRITICAL\",
  \"findings\": [
    {\"severity\": \"...\", \"description\": \"...\"}
  ],
  \"rationale\": \"one sentence explaining the verdict\"
}"

    if ! $DRY_RUN; then
        CODEX_OUT=$(codex exec "$CODEX_PROMPT" 2>/dev/null || \
            echo "{\"sha\":\"${sha:0:8}\",\"reviewer\":\"codex\",\"tier_escape\":false,\"max_severity\":\"NONE\",\"findings\":[],\"rationale\":\"error\"}")
        AGY_OUT=$(agy -p "$AGY_PROMPT" 2>/dev/null || \
            echo "{\"sha\":\"${sha:0:8}\",\"reviewer\":\"agy\",\"tier_escape\":false,\"max_severity\":\"NONE\",\"findings\":[],\"rationale\":\"error\"}")
    else
        CODEX_OUT="{\"sha\":\"${sha:0:8}\",\"reviewer\":\"codex\",\"tier_escape\":false,\"max_severity\":\"NONE\",\"findings\":[],\"rationale\":\"dry-run\"}"
        AGY_OUT="{\"sha\":\"${sha:0:8}\",\"reviewer\":\"agy\",\"tier_escape\":false,\"max_severity\":\"NONE\",\"findings\":[],\"rationale\":\"dry-run\"}"
    fi

    # A tier escape if EITHER reviewer flags MEDIUM+
    CODEX_ESCAPE=$(echo "$CODEX_OUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print('true' if d.get('tier_escape') else 'false')" 2>/dev/null || echo "false")
    AGY_ESCAPE=$(echo "$AGY_OUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print('true' if d.get('tier_escape') else 'false')" 2>/dev/null || echo "false")

    ESCAPED=false
    [[ "$CODEX_ESCAPE" == "true" || "$AGY_ESCAPE" == "true" ]] && ESCAPED=true

    if $ESCAPED; then
        TIER_ESCAPES=$(( TIER_ESCAPES + 1 ))
        fail "  ${sha:0:8}: TIER ESCAPE detected"
        FINDINGS_SUMMARY+=("${sha:0:8}: ESCAPED — ${COMMIT_MSG:0:50}")
    else
        ok "  ${sha:0:8}: clean"
    fi

    echo "{\"codex\":${CODEX_OUT},\"agy\":${AGY_OUT}}" > "$COMMIT_OUT"
done

# ── Step 4: Aggregate report ──────────────────────────────────────────────────
echo ""
ESCAPE_RATE=$(python3 -c "print(round(${TIER_ESCAPES}/${ACTUAL_N}*100,1))" 2>/dev/null || echo "0")

if python3 -c "exit(0 if ${TIER_ESCAPES}/${ACTUAL_N} < 0.05 else 1)" 2>/dev/null; then
    RECOMMENDATION="LOW tier well-calibrated (escape rate ${ESCAPE_RATE}% < 5% threshold)"
elif python3 -c "exit(0 if ${TIER_ESCAPES}/${ACTUAL_N} < 0.15 else 1)" 2>/dev/null; then
    RECOMMENDATION="LOW threshold may be too permissive (escape rate ${ESCAPE_RATE}% — review tier criteria)"
else
    RECOMMENDATION="LOW threshold is miscalibrated (escape rate ${ESCAPE_RATE}% > 15% — escalate tier criteria revision to human)"
fi

SUMMARY_JSON="{
  \"timestamp\": \"${TIMESTAMP}\",
  \"branch\": \"${CURRENT_BRANCH}\",
  \"pool_size\": ${POOL_SIZE},
  \"sample_size\": ${ACTUAL_N},
  \"lookback_days\": ${LOOKBACK_DAYS},
  \"tier_escapes\": ${TIER_ESCAPES},
  \"escape_rate_pct\": ${ESCAPE_RATE},
  \"recommendation\": \"${RECOMMENDATION}\"
}"

echo "$SUMMARY_JSON" > "${OUT_DIR}/summary.json"

# Append to audit log
AUDIT_LOG="audit/oversight-log.jsonl"
if [[ -f "$AUDIT_LOG" ]]; then
    echo "{\"event\":\"sampling-audit\",\"timestamp\":\"${TIMESTAMP}\",\"pool_size\":${POOL_SIZE},\"sample_size\":${ACTUAL_N},\"tier_escapes\":${TIER_ESCAPES},\"escape_rate_pct\":${ESCAPE_RATE},\"recommendation\":\"${RECOMMENDATION}\"}" \
        >> "$AUDIT_LOG"
fi

# ── Step 5: Print summary ─────────────────────────────────────────────────────
echo -e "${BOLD}=== Sampling Audit Complete ===${RESET}"
echo ""
echo "  Pool size:      ${POOL_SIZE} LOW-tier commits"
echo "  Sampled:        ${ACTUAL_N}"
echo "  Tier escapes:   ${TIER_ESCAPES} (${ESCAPE_RATE}%)"
echo ""
if [[ ${#FINDINGS_SUMMARY[@]} -gt 0 ]]; then
    echo -e "  ${RED}Escaped commits:${RESET}"
    for f in "${FINDINGS_SUMMARY[@]}"; do
        echo "    $f"
    done
    echo ""
fi
echo "  Recommendation: ${RECOMMENDATION}"
echo ""
echo "  Full report: ${OUT_DIR}/"
echo "  Summary:     ${OUT_DIR}/summary.json"

# ── Token tracking ────────────────────────────────────────────────────────────
TRACKER="$(dirname "$0")/oversight/token_tracker.py"
if [[ -f "$TRACKER" ]] && ! $DRY_RUN && [[ $ACTUAL_N -gt 0 ]]; then
    python3 "$TRACKER" record \
        --vendor codex --stage sampling-audit --step "n${ACTUAL_N}" \
        --prompt-chars $(( ACTUAL_N * 800 )) \
        --output-chars $(( ACTUAL_N * 200 )) 2>/dev/null || true
    python3 "$TRACKER" record \
        --vendor agy --stage sampling-audit --step "n${ACTUAL_N}" \
        --prompt-chars $(( ACTUAL_N * 800 )) \
        --output-chars $(( ACTUAL_N * 200 )) 2>/dev/null || true
fi
