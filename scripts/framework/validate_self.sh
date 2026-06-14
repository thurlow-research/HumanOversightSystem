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
#   ./scripts/framework/validate_self.sh                 # one review pass
#   ./scripts/framework/validate_self.sh --changed-only  # only files changed vs HEAD~1
#   ./scripts/framework/validate_self.sh --reset         # new change set: clear ledger+counter
#   ./scripts/framework/validate_self.sh --record FILES CATEGORY DISPOSITION
#
# Capped-iterate protocol (why a non-deterministic reviewer still terminates):
#   1. --reset at the start of a new change set.
#   2. Run a pass. For each NEW (un-ledgered) blocking finding, either
#        fix-in-place (inner loop — NO issue), or file an issue if it needs a
#        human / another agent; then --record it so it won't re-gate next pass.
#   3. Re-run. The verdict is keyed on NEW findings, so once every finding is
#        either fixed or dispositioned, the pass APPROVES ("zero non-noise",
#        not zero findings — the model never returns the same set twice).
#   4. Hard cap: SELF_REVIEW_MAX_PASSES (default 3). If the cap is hit while NEW
#        blocking findings still appear, the script ESCALATES (exit 3) — a human
#        decides; automation never loops past the cap (the ratchet).
#
# Model is ALWAYS Opus — not overridable by design.
# Exit: 0 converged | 1 NEW blocking findings (re-run) | 2 tooling/CLI error
#       | 3 pass cap hit without converging (escalate to human)
set -euo pipefail

AGENTS_DIR=".claude/agents"
DOCS_DIR="docs"
OUT_DIR=".claudetmp/framework"
# Dedup ledger: fingerprints of findings already dispositioned (fixed / filed /
# noise). A finding matching the ledger is "seen" → noise, and does NOT count
# toward the verdict. This is what lets self-review converge on "zero NEW
# non-noise findings" (not zero findings — it is non-deterministic) and what
# prevents re-filing issues that would poison the risk score.
LEDGER="$OUT_DIR/self-review-ledger.jsonl"
# Self-review is ALWAYS Opus — not overridable. The whole point is to apply the
# strongest available model to flush issues before the external pass; allowing a
# downgrade would defeat that. (Override only the resolved ID if Opus is renamed.)
MODEL="claude-opus-4-8"
CHANGED_ONLY=false
# Base ref for --changed-only. Defaults to HEAD~1 (single commit), but a release
# scopes to the last release tag so a patch/minor reviews ITS diff, not the whole
# corpus (#130). Override with --base <ref>.
BASE_REF="HEAD~1"
# Hard cap on iterate passes. Self-review is non-deterministic and will keep
# surfacing low-value findings forever; the cap forces a stop. If the cap is hit
# while NEW blocking findings are still appearing, the script escalates (exit 3)
# rather than looping — a human decides, never automation (the ratchet).
SELF_REVIEW_MAX_PASSES="${SELF_REVIEW_MAX_PASSES:-3}"
PASS_COUNT_FILE="$OUT_DIR/self-review-pass-count"

PROJECT_NAME="(unnamed project)"
PROJECT_STACK="(unspecified stack)"
DESIGN_PACK_PATH=""
EXTRA_REVIEW_FILES=""
# shellcheck source=/dev/null
[[ -f "scripts/framework/config.sh" ]] && source scripts/framework/config.sh

# --record FILES CATEGORY DISPOSITION — append a disposition to the dedup ledger
# so the finding is treated as "seen" (noise) on subsequent runs. FILES is a
# comma-separated list. DISPOSITION is e.g. "fixed", "filed:#74", or "noise".
if [[ "${1:-}" == "--record" ]]; then
    mkdir -p "$OUT_DIR"
    _files="${2:?--record needs FILES}"; _cat="${3:?--record needs CATEGORY}"; _disp="${4:?--record needs DISPOSITION}"
    _ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    _json_files=$(printf '%s' "$_files" | awk -F, '{for(i=1;i<=NF;i++){printf "%s\"%s\"", (i>1?",":""), $i}}')
    printf '{"files":[%s],"category":"%s","disposition":"%s","ts":"%s"}\n' \
        "$_json_files" "$_cat" "$_disp" "$_ts" >> "$LEDGER"
    echo "Recorded to ledger: [$_files] $_cat → $_disp"
    exit 0
fi

# --reset — clear the ledger and pass counter when starting review of a NEW
# change set, so prior dispositions don't mask genuinely new findings.
if [[ "${1:-}" == "--reset" ]]; then
    rm -f "$LEDGER" "$PASS_COUNT_FILE"
    echo "Self-review ledger and pass counter reset."
    exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agents-dir)   AGENTS_DIR="$2"; shift 2 ;;
        --changed-only) CHANGED_ONLY=true; shift ;;
        --base)         BASE_REF="$2"; shift 2 ;;
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

# Count this pass. Reset with --reset when starting a new change set.
PASS_NUM=$(( $(cat "$PASS_COUNT_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$PASS_NUM" > "$PASS_COUNT_FILE"
echo "Self-review pass ${PASS_NUM} of ${SELF_REVIEW_MAX_PASSES} (cap)." >&2

collect_files() {
    local files=() content=""
    if $CHANGED_ONLY; then
        while IFS= read -r f; do [[ -f "$f" ]] && files+=("$f"); done \
            < <(git diff --name-only "$BASE_REF" -- "$AGENTS_DIR" "$DOCS_DIR" 2>/dev/null || true)
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

# Known-issues context: feed the reviewer the open GitHub issues so it SKIPS
# already-tracked findings instead of re-surfacing them every run. This is the
# root-cause fix for convergence churn (the reviewer never reports what's already
# filed), complementing the post-hoc dedup ledger. (#133-adjacent)
KNOWN_ISSUES=""
if [[ "${HOS_FEED_KNOWN_ISSUES:-1}" == "1" ]] && command -v gh >/dev/null 2>&1; then
    KNOWN_ISSUES=$(gh issue list --state open --limit 100 \
        --json number,title -q '.[] | "- #\(.number): \(.title)"' 2>/dev/null || true)
fi
[[ -z "$KNOWN_ISSUES" ]] && KNOWN_ISSUES="(none available)"

{
    printf "# Framework Self-Validation (Opus)\n"
    printf "Timestamp: %s\n" "$TIMESTAMP"
    printf "Model: %s\n" "$MODEL"
    printf "verdict: pending\n"
    printf "highest_severity: none\n"
    printf "blocking_count: 0\n"
    printf "new_blocking_count: 0\n\n"
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

=== KNOWN, ALREADY-TRACKED ISSUES — do NOT re-report these ===
The findings below are ALREADY filed as GitHub issues and are being tracked. Do
NOT report a finding that is already covered by one of these — re-surfacing a
known, filed issue is noise. Only report findings NOT represented below. (E.g.
the human-gate forgeability / shared-git-identity weakness, and the
mechanical-vs-prose 'structural' gap, are tracked — do not re-report them.)
${KNOWN_ISSUES}

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

# ── Finalize verdict (ledger-aware: verdict keyed on NEW findings) ───────────
python3 - "$OUTFILE" "$LEDGER" <<'PYEOF'
import json, re, sys
path, ledger_path = sys.argv[1], sys.argv[2]
content = open(path).read()
order = ["critical", "blocking", "high", "warning", "medium", "low", "none"]


def _brace_objects(text):
    """String-aware extraction of every balanced {...} that parses as JSON.

    Brace counting must ignore braces inside JSON strings — finding
    descriptions routinely contain literals like "step{N}-...". Naive
    counting would mis-balance and drop the whole object.
    """
    out, n, i = [], len(text), 0
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc = 0, False, False
        j = i
        while j < n:
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        out.append(json.loads(text[i:j + 1]))
                    except Exception:
                        pass
                    break
            j += 1
        i = j + 1
    return out


def extract_objects(text):
    """Findings objects, tolerant of prose the model emits inside/around the
    ```json fence (the strict `​```json{...}​``` regex misses those)."""
    objs = []
    for m in re.finditer(r"```json(.*?)```", text, re.DOTALL):
        objs.extend(o for o in _brace_objects(m.group(1)) if "findings" in o or "verdict" in o)
    if not objs:  # no fenced object parsed — scan the whole document
        objs.extend(o for o in _brace_objects(text) if "findings" in o or "verdict" in o)
    return objs


blocks = extract_objects(content)

# Load dedup ledger: fingerprint = (sorted files, category).
seen = set()
try:
    for line in open(ledger_path):
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        seen.add((tuple(sorted(e.get("files", []))), e.get("category", "")))
except FileNotFoundError:
    pass


def fingerprint(f):
    return (tuple(sorted(f.get("files", []))), f.get("category", ""))


highest = "none"
blocking_count = new_blocking = 0
for d in blocks:
    for f in d.get("findings", []):
        sev = str(f.get("severity", "low")).lower()
        if sev in order and order.index(sev) < order.index(highest):
            highest = sev
        if sev in ("critical", "blocking", "high"):
            blocking_count += 1
            if fingerprint(f) not in seen:
                new_blocking += 1

# Verdict is keyed on NEW (un-ledgered) blocking findings: convergence means
# "zero non-noise", not zero findings. Seen findings are already dispositioned.
if not blocks:
    verdict = "error"
elif new_blocking > 0:
    verdict = "request_changes"
else:
    verdict = "approve"
content = re.sub(r'^verdict: pending$', f'verdict: {verdict}', content, flags=re.M)
content = re.sub(r'^highest_severity: none$', f'highest_severity: {highest}', content, flags=re.M)
content = re.sub(r'^blocking_count: 0$', f'blocking_count: {blocking_count}', content, flags=re.M)
content = re.sub(r'^new_blocking_count: 0$', f'new_blocking_count: {new_blocking}', content, flags=re.M)
open(path, 'w').write(content)
print(f"  verdict={verdict} highest_severity={highest} blocking={blocking_count} new={new_blocking}")
PYEOF

VERDICT=$(grep '^verdict:' "$OUTFILE" | head -1 | awk '{print $2}')
BLOCKING=$(grep '^new_blocking_count:' "$OUTFILE" | head -1 | awk '{print $2}')
echo ""
echo "Output: $OUTFILE"
if [[ "$VERDICT" == "approve" ]]; then
    echo "════════════════════════════════════════════"
    echo "  PASS — converged (zero NEW blocking findings)"
    echo "════════════════════════════════════════════"
    echo "  Findings already in the ledger are dispositioned;"
    echo "  only un-ledgered blocking findings gate the verdict."
    rm -f "$PASS_COUNT_FILE"   # converged — reset for the next change set
    exit 0
elif [[ "$PASS_NUM" -ge "$SELF_REVIEW_MAX_PASSES" ]]; then
    echo "════════════════════════════════════════════"
    echo "  ESCALATE — pass cap (${SELF_REVIEW_MAX_PASSES}) hit, still ${BLOCKING:-?} NEW blocking"
    echo "════════════════════════════════════════════"
    echo "  Self-review did not converge within the cap. Do NOT keep"
    echo "  looping — a human decides whether to fix, accept, or file."
    echo "  Review: $OUTFILE"
    exit 3
else
    echo "════════════════════════════════════════════"
    echo "  SELF-REVIEW FAIL — verdict=${VERDICT} new_blocking=${BLOCKING:-?} (pass ${PASS_NUM}/${SELF_REVIEW_MAX_PASSES})"
    echo "════════════════════════════════════════════"
    echo "  Triage the NEW findings in: $OUTFILE"
    echo "  For each: fix-in-place (inner loop, no issue), or file an"
    echo "  issue if it needs a human / another agent, then record it:"
    echo "    $0 --record \"file1.md,file2.md\" <category> <fixed|filed:#NN|noise>"
    echo "  Re-run. Stop when zero NEW findings, or at the pass cap"
    echo "  (\$SELF_REVIEW_MAX_PASSES=${SELF_REVIEW_MAX_PASSES}) — then escalate to a human."
    echo "  Don't spend external agy/codex budget until converged."
    exit 1
fi
