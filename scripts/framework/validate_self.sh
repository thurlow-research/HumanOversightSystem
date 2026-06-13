#!/usr/bin/env bash
# validate_self.sh — Opus self-review of the framework.
#
# Part of the framework-validation suite: it reviews AGENT/DOC/CONTRACT files,
# the same as validate_agents.sh — never customer application code. It ships to
# consumer projects so a team that MODIFIES the framework (agent definitions,
# pipeline docs) can self-review those changes. It does not run when evaluating
# a customer's app.
#
# Purpose: flush issues cheaply (within the Claude subscription) BEFORE spending
# the metered external agy/codex budget.
#
# Position in the framework review chain:
#   static check  →  SELF REVIEW (Opus, this script)  →  agy  →  codex  →  docs/compliance
#
# This is NOT cross-vendor review — it is Claude reviewing Claude's own work, so
# it provides no vendor decorrelation. Its value is catching obvious problems
# before the external pass, not replacing it. The prompt below pushes hard for
# adversarial self-criticism precisely because the same model family wrote much
# of what is under review (sycophancy / shared-blind-spot risk).
#
# Usage:
#   ./scripts/framework/validate_self.sh
#   ./scripts/framework/validate_self.sh --changed-only
#
# Model is ALWAYS Opus — not overridable by design.
# Exit: 0 clean | 1 blocking findings | 2 tooling/CLI error
set -euo pipefail

AGENTS_DIR=".claude/agents"
DOCS_DIR="docs"
OUT_DIR=".claudetmp/framework"
# Self-review is ALWAYS Opus — not overridable. The whole point is to apply the
# strongest available model to flush issues before the external pass; allowing a
# downgrade would defeat that. (Override only the resolved ID if Opus is renamed.)
MODEL="claude-opus-4-8"
CHANGED_ONLY=false

PROJECT_NAME="(unnamed project)"
PROJECT_STACK="(unspecified stack)"
DESIGN_PACK_PATH=""
EXTRA_REVIEW_FILES=""
# shellcheck source=/dev/null
[[ -f "scripts/framework/config.sh" ]] && source scripts/framework/config.sh

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agents-dir)   AGENTS_DIR="$2"; shift 2 ;;
        --changed-only) CHANGED_ONLY=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

if ! command -v claude >/dev/null 2>&1; then
    echo "validate_self: claude CLI not found — cannot run Opus self-review." >&2
    exit 2
fi

mkdir -p "$OUT_DIR"
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
OUTFILE="$OUT_DIR/self-validation-${TIMESTAMP}.md"

collect_files() {
    local files=() content=""
    if $CHANGED_ONLY; then
        while IFS= read -r f; do [[ -f "$f" ]] && files+=("$f"); done \
            < <(git diff --name-only HEAD~1 -- "$AGENTS_DIR" "$DOCS_DIR" 2>/dev/null || true)
        [[ ${#files[@]} -eq 0 ]] && CHANGED_ONLY=false
    fi
    if ! $CHANGED_ONLY; then
        while IFS= read -r -d '' f; do files+=("$f"); done \
            < <(find "$AGENTS_DIR" -name '*.md' -print0)
        [[ -f "$DOCS_DIR/AGENTS.md" ]]            && files+=("$DOCS_DIR/AGENTS.md")
        [[ -f "$DOCS_DIR/OVERSIGHT-RUNBOOK.md" ]] && files+=("$DOCS_DIR/OVERSIGHT-RUNBOOK.md")
        [[ -f "contract/OVERSIGHT-CONTRACT.md" ]] && files+=("contract/OVERSIGHT-CONTRACT.md")
        for ef in $EXTRA_REVIEW_FILES; do [[ -f "$ef" ]] && files+=("$ef"); done
    fi
    echo "Collecting ${#files[@]} files for Opus self-review..." >&2
    for f in "${files[@]}"; do
        content+="=== FILE: $f ===
$(cat "$f")

"
    done
    echo "$content"
}

REVIEW_PACKAGE=$(collect_files)

{
    printf "# Framework Self-Validation (Opus)\n"
    printf "Timestamp: %s\n" "$TIMESTAMP"
    printf "Model: %s\n" "$MODEL"
    printf "verdict: pending\n"
    printf "highest_severity: none\n"
    printf "blocking_count: 0\n\n"
} > "$OUTFILE"

run_opus() {
    local prompt
    prompt="You are performing an ADVERSARIAL SELF-REVIEW of an AI agent pipeline framework (the Human Oversight System). You are the same model family that authored much of this — so your single biggest risk is SYCOPHANCY and SHARED BLIND SPOTS. Do not be agreeable. Assume an external reviewer (Gemini, then GPT) will see this next; find everything you would be embarrassed for them to catch first.

Project: ${PROJECT_NAME} (${PROJECT_STACK}).

Review the agent definitions, docs, and contract below for:
1. CONTRADICTIONS — two files (or two parts of one file) that disagree.
2. GOVERNANCE HOLES — any path where an automated action could reduce oversight without a human (RATCHET VIOLATIONS), a human gate that an agent could forge, or a required check that can be silently skipped.
3. UNENFORCEABLE RULES — instructions that assert a behavior with no mechanism to verify it happened.
4. LOOPS / DEAD ENDS / MISSING EXITS — escalation cycles, escalation to undefined handlers, iteration without a round limit.
5. SELF-CLASSIFICATION GAMING — places where an agent classifies its own work (clarifying/additive/structural, risk tier) in a way it could game to reduce scrutiny.
6. STALE / OVER-CLAIMED STATUS — docs marked done (✅) for things that are not actually built or validated.
7. SCOPE / OWNERSHIP CONFUSION — two agents that could both (or neither) own a decision.

Be specific: name exact files and quote the offending text. Prefer a few real, high-confidence findings over many speculative ones. If genuinely clean, say so plainly — do not invent findings to seem thorough.

=== FRAMEWORK FILES ===
${REVIEW_PACKAGE}

Return JSON only — no prose outside the JSON block:
{
  \"reviewer\": \"opus-self\",
  \"lens\": \"adversarial-self-review\",
  \"findings\": [
    {\"severity\": \"blocking|warning\", \"category\": \"contradiction|governance-hole|unenforceable|loop|gaming|stale-status|ownership\", \"files\": [\"f.md\"], \"description\": \"what is wrong and where (quote it)\", \"fix\": \"specific change\"}
  ],
  \"verdict\": \"approve|request_changes\",
  \"summary\": \"one paragraph — be honest, not reassuring\"
}"
    # CONTEXT ISOLATION (reduce self-review bias):
    #   -p                                    fresh session — does NOT inherit the
    #                                         caller's interactive conversation.
    #   --exclude-dynamic-system-prompt-sections
    #                                         drop cwd/env/memory-paths/git status so
    #                                         the reviewer is not primed by project
    #                                         memory or our own framing.
    #   --no-session-persistence              leave no session state behind.
    # The review package is fully self-contained (all files inline in the prompt),
    # so the reviewer needs no project context at all.
    local tmpfile result
    tmpfile=$(mktemp /tmp/validate_self_XXXXXX)
    printf '%s' "$prompt" > "$tmpfile"
    result=$(claude -p "$(cat "$tmpfile")" --model "$MODEL" \
        --exclude-dynamic-system-prompt-sections \
        --no-session-persistence 2>/dev/null) || \
        result='{"reviewer":"opus-self","error":"claude invocation failed","findings":[],"verdict":"error","summary":"claude failed"}'
    rm -f "$tmpfile"
    # Strip any markdown fencing the CLI may add around the JSON.
    echo "$result" | sed -e 's/^```json$//' -e 's/^```$//'
}

echo "Running Opus self-review (${MODEL})..."
OPUS_OUT=$(run_opus)
{
    echo "## opus-self — Adversarial Self-Review"
    echo '```json'
    echo "$OPUS_OUT"
    echo '```'
    echo ""
} >> "$OUTFILE"
echo "  done"
echo ""

# ── Finalize verdict ─────────────────────────────────────────────────────────
python3 - "$OUTFILE" <<'PYEOF'
import json, re, sys
path = sys.argv[1]
content = open(path).read()
blocks = re.findall(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
order = ["critical", "blocking", "high", "warning", "medium", "low", "none"]
highest, request_changes, blocking_count = "none", False, 0
for b in blocks:
    try:
        d = json.loads(b)
    except Exception:
        continue
    if d.get("verdict") in ("request_changes", "error"):
        request_changes = True
    for f in d.get("findings", []):
        sev = str(f.get("severity", "low")).lower()
        if sev in order and order.index(sev) < order.index(highest):
            highest = sev
        if sev in ("critical", "blocking", "high"):
            blocking_count += 1
verdict = "request_changes" if request_changes else "approve"
if not blocks:
    verdict = "error"
content = re.sub(r'^verdict: pending$', f'verdict: {verdict}', content, flags=re.M)
content = re.sub(r'^highest_severity: none$', f'highest_severity: {highest}', content, flags=re.M)
content = re.sub(r'^blocking_count: 0$', f'blocking_count: {blocking_count}', content, flags=re.M)
open(path, 'w').write(content)
print(f"  verdict={verdict} highest_severity={highest} blocking={blocking_count}")
PYEOF

VERDICT=$(grep '^verdict:' "$OUTFILE" | head -1 | awk '{print $2}')
BLOCKING=$(grep '^blocking_count:' "$OUTFILE" | head -1 | awk '{print $2}')
echo ""
echo "Output: $OUTFILE"
if [[ "$VERDICT" == "approve" ]]; then
    echo "════════════════════════════════════════════"
    echo "  PASS — Opus self-review clean"
    echo "════════════════════════════════════════════"
    exit 0
else
    echo "════════════════════════════════════════════"
    echo "  SELF-REVIEW FAIL — verdict=${VERDICT} blocking=${BLOCKING:-?}"
    echo "  Fix these before spending external agy/codex budget."
    echo "  Review: $OUTFILE"
    echo "════════════════════════════════════════════"
    exit 1
fi
