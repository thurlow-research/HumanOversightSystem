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

# Resolve the repo root from the script's own location so the validation_logic.py
# delegation works regardless of the caller's cwd (SPEC-334, mirrors
# validate_agents.sh / validate_scripts.sh). The ledger path stays cwd-relative
# (OUT_DIR), preserving the existing --record/--reset contract and this script's
# own ephemeral (not persisted) ledger — see DECISIONS.md's "ledger asymmetry".
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VALIDATION_LOGIC="$ROOT/scripts/oversight/validation_logic.py"

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
# downgrade would defeat that. A class alias (not a pinned generation ID) so this
# never goes stale the way the previous "claude-opus-4-8" pin did (#1122, #1362).
MODEL="opus"
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
EXTRA_REVIEW_FILES=""
# shellcheck source=/dev/null
[[ -f "scripts/framework/config.sh" ]] && source scripts/framework/config.sh

# --record FILES CATEGORY DISPOSITION — append a disposition to the dedup ledger
# so the finding is treated as "seen" (noise) on subsequent runs. FILES is a
# comma-separated list. DISPOSITION is e.g. "fixed", "filed:#74", or "noise".
if [[ "${1:-}" == "--record" ]]; then
    mkdir -p "$OUT_DIR"
    _files="${2:?--record needs FILES}"; _cat="${3:?--record needs CATEGORY}"; _disp="${4:?--record needs DISPOSITION}"
    # Ledger write delegated to validation_logic.py (SPEC-334 binding 4), same as
    # validate_agents.sh / validate_scripts.sh — one fingerprint/ledger schema
    # ("class" key) shared across all three, instead of this script's own
    # divergent "category" key that compute_verdict's ledger reader never read.
    python3 "$VALIDATION_LOGIC" record \
        --ledger "$LEDGER" --files "$_files" --class "$_cat" --disposition "$_disp" >/dev/null
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
    local result rc=0
    # Pass the prompt via stdin, not as a CLI argument (#1368): at release scale
    # (--changed-only spanning a full minor release) the review package can
    # exceed the OS ARG_MAX ceiling shared by argv and the environment, causing
    # execve to fail (E2BIG, rc=126) before claude ever runs. Piping removes
    # that ceiling entirely — matches the pattern already used for the same
    # invocation in validate_scripts.sh.
    result=$(printf '%s' "$prompt" | claude -p --model "$MODEL" \
        --exclude-dynamic-system-prompt-sections \
        --no-session-persistence 2>/dev/null) || rc=$?
    # Fail-closed on an invocation that errored or produced empty/whitespace-only
    # output (same class of bug as #669/#670 in the sibling scripts): a broken
    # `claude` call must not read as "reviewed, found nothing". The synthesized
    # block below carries "verdict":"error" so the finalize step (which now
    # inspects each block's own verdict field, not just its findings count) fails
    # the gate rather than silently approving it (#1362).
    if [[ $rc -ne 0 || -z "${result//[[:space:]]/}" ]]; then
        echo "  ERROR: Opus self-review invocation failed (rc=$rc) or produced empty output — recording as a review FAILURE, not a clean pass (#1362)." >&2
        result='{"reviewer":"opus-self","error":"claude invocation failed","findings":[],"verdict":"error","summary":"claude failed"}'
    fi
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
# "done" means the reviewer actually produced a review, not merely that the call
# returned — a failed invocation was already reported by run_opus above (#1362).
if printf '%s' "$OPUS_OUT" | grep -q '"error"[[:space:]]*:[[:space:]]*"claude invocation failed"'; then
    echo "  FAILED — see error above"
else
    echo "  done"
fi
echo ""

# ── Finalize verdict (ledger-aware: verdict keyed on NEW findings) ───────────
# Dedup fingerprinting + verdict aggregation delegated to validation_logic.py
# (SPEC-334), same module validate_agents.sh / validate_scripts.sh use, instead
# of this script's own hand-rolled heredoc. That heredoc only ever asked "did I
# get any findings?" — it never inspected a reviewer block's own `verdict`
# field, so run_opus's error stub ({"findings":[],"verdict":"error",...}) parsed
# as zero findings and fell through to "approve" (#1362). validation_logic.py's
# compute_verdict already treats a block-level verdict=="error" as a NEW
# blocking signal (the #670 fix) — reusing it here closes the same class of gap
# validate_self.sh was the one holdout for. --strict-empty: an empty parse (no
# blocks at all) also yields verdict=error, matching this script's prior
# behavior for that case.
python3 "$VALIDATION_LOGIC" process \
    --file "$OUTFILE" --ledger "$LEDGER" --strict-empty

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
