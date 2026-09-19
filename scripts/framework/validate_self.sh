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
#   ./scripts/framework/validate_self.sh                       # one review pass
#   ./scripts/framework/validate_self.sh --changed-only        # only files changed vs HEAD~1
#   ./scripts/framework/validate_self.sh --reset               # new change set: clear ledger+counter
#   ./scripts/framework/validate_self.sh --record FILES CATEGORY DISPOSITION
#   ./scripts/framework/validate_self.sh --allow-keychain-auth # interactive human on keychain auth (see Auth: below)
#
# Auth (AD-16.7): every run requires env-token auth (CLAUDE_CODE_OAUTH_TOKEN
# or ANTHROPIC_API_KEY) by default. This is NOT a flag you pass — it is the
# unconditional default; there is nothing to type to request it. The ONLY
# auth-related CLI option this script accepts is --allow-keychain-auth, to
# opt OUT of the default for an interactive human on keychain auth. This is
# a deliberate breaking change: a maintainer running this by hand must now
# pass that flag. There is no auto-detection of "interactive" — see the
# REQUIRE_ENV_AUTH_FLAG comment below for why. A cron cycle (HOS_CYCLE_ROLE
# set) may never pass --allow-keychain-auth; doing so is refused (exit 2).
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
# never goes stale the way the previous dated generation pin did (#1122, #1362).
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
# Per-invocation budget passed to bootstrap/invoke_agent.sh (#1643 W4 §6.1).
# Same env override + default as validate_scripts.sh's sibling path, so a
# release-wide override (e.g. CI budget tuning) covers both call sites with
# one setting.
AI_REVIEW_TIMEOUT="${AI_REVIEW_TIMEOUT:-300}"
# bootstrap/invoke_agent.sh's --require-env-auth is MANDATORY for every
# non-interactive caller (ADR-1643 Amendment 1 §9.3). AD-16.7 (architect
# ruling, codex CWE-287, cross-vendor second review): the caller's identity
# is NEVER inferred from an environment heuristic. An earlier revision of
# this script gated on HOS_CYCLE_ROLE / CI / terminal-attachment, but every
# one of those signals is controllable by the very process being classified
# — a cron/systemd/CI wrapper can allocate a pty, omit CI, and preserve
# terminal fds, walking straight past the check onto the interactive
# keychain-auth path. No signal an unauthenticated caller can shape may
# decide whether that caller must authenticate.
#
# The mode is EXPLICIT and STRICT BY DEFAULT instead: every caller gets
# --require-env-auth unless it opts out with --allow-keychain-auth (below).
# This is a deliberate breaking change to the interactive human workflow —
# a maintainer running this by hand must now pass --allow-keychain-auth —
# accepted on condition that the remedy is discoverable (see the
# not_authenticated branch further down, which names the flag verbatim).
# Do not reintroduce a detection fallback here.
#
# HOS_CYCLE_ROLE is used for exactly one thing below: a ONE-DIRECTION veto
# that can only make a run STRICTER — refusing --allow-keychain-auth from
# inside a cron cycle — never looser. It never sets this flag itself.
REQUIRE_ENV_AUTH_FLAG="--require-env-auth"

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
        --agents-dir)         AGENTS_DIR="$2"; shift 2 ;;
        --changed-only)       CHANGED_ONLY=true; shift ;;
        --base)               BASE_REF="$2"; shift 2 ;;
        --allow-keychain-auth) REQUIRE_ENV_AUTH_FLAG=""; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

# One-direction veto (AD-16.7): HOS_CYCLE_ROLE may only REFUSE
# --allow-keychain-auth, never route around --require-env-auth on its own.
# A cron cycle asking to skip the env-token check is asking to run this
# framework-validation gate under keychain auth from inside an unattended
# process — exactly the identity confusion AD-16.7 exists to prevent.
if [[ -n "${HOS_CYCLE_ROLE:-}" && -z "$REQUIRE_ENV_AUTH_FLAG" ]]; then
    echo "validate_self: --allow-keychain-auth is not permitted inside a cron cycle (HOS_CYCLE_ROLE=${HOS_CYCLE_ROLE}) — a cron-launched run must authenticate via CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_API_KEY, never keychain auth (AD-16.7)." >&2
    exit 2
fi

# No `command -v claude` preflight here (#1643 W4 §6.1): CLI resolution is now
# bootstrap/invoke_agent.sh's job. A missing `claude` binary surfaces through
# agent_invoke_cli.py's own P8 check as a `cli_unavailable` document
# (outcome: invocation_failed, verdict: error, exit 0) — the SAME fail-closed
# reviewer-block path that already handles a hang or a bad response, rather
# than a second, divergent early-exit check duplicating that resolution here.

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

# Script-global (not `local` to run_opus below) so the EXIT trap run_opus
# installs can still reference this path when it fires — which is at the end
# of the command-substitution subshell run_opus is called in, just after the
# function itself returns. A `local` is already out of scope by then and the
# trap dies on `set -u` instead of cleaning up. This declaration keeps the
# parent shell's own reference defined under `set -u`; the subshell's
# assignment never propagates back here, so it stays "" in the parent. See
# the SCOPE note at the assignment for the full rationale.
_VSELF_TMP_DIR=""

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
    local result="" tmp_prompt rc=0
    # --input-file is the only input path into bootstrap/invoke_agent.sh
    # (REQ-A3, #1643 W4 §6.1): the prompt moves from a piped stdin argument
    # to a file — same pattern already used for the agy call in
    # validate_agents.sh (tmpfile, #1384) and for the sibling review package
    # in validate_scripts.sh. This also removes the ARG_MAX exposure #1368
    # fixed for the old direct-CLI stdin path: a file has no such ceiling.
    #
    # codex HIGH/MEDIUM (round 4): the prompt now lives in a PRIVATE,
    # mode-700 directory under $OUT_DIR (already created above; gitignored
    # .claudetmp/ working state — contract/OVERSIGHT-CONTRACT.md §1) rather
    # than directly in the shared $TMPDIR — this removes the shared-directory
    # substitution surface rather than mitigating it. The trap is installed
    # IMMEDIATELY after the directory is created, before anything else can
    # fail and skip cleanup.
    #
    # EXIT, not RETURN, and the path is held in the script-global
    # _VSELF_TMP_DIR (declared above run_opus), not a `local`: tested both
    # ways before choosing.
    #
    # SCOPE — read this before relying on the lifetime. run_opus has exactly
    # one call site below, where its output is captured by a command
    # substitution, i.e. a SUBSHELL. (That call site is deliberately not
    # quoted verbatim here: the tests anchor on the first occurrence of that
    # assignment's text, so a copy of it in this comment would silently
    # capture the anchor.) Everything here happens inside that
    # subshell: the trap belongs to it and fires when IT ends, which is when
    # run_opus returns — not at the outer script's exit. The assignment to
    # _VSELF_TMP_DIR likewise never reaches the parent shell, which still
    # holds "" afterwards. So cleanup is prompt, not deferred: by the time
    # the parent resumes, the directory is already gone. Do NOT write code
    # after the substitution that expects $tmp_prompt or $_VSELF_TMP_DIR to
    # still be there — both are gone. (An earlier version of this comment
    # claimed the trap covered "every path out of the whole script" and that
    # the directory lived until script exit; that described a non-subshell
    # call site this script does not have. Corrected per the #1760 review.)
    #
    # Within that subshell the choice still matters, and both alternatives
    # were confirmed by direct test to fail:
    #   - A RETURN trap fires on a *graceful* function return but NOT when a
    #     `set -e` abort inside the function is fatal (the realistic case —
    #     nothing guards the invoke_agent.sh call site above with `|| true`);
    #     it left the directory on disk.
    #   - `local _VSELF_TMP_DIR` goes out of scope the moment the function
    #     returns, so the EXIT trap firing just after hits `set -u`'s
    #     unbound-variable error instead of cleaning up — the directory
    #     leaks. The script-global is load-bearing for this reason, not for
    #     any cross-function lifetime.
    # Global + EXIT survives both: it fires on graceful return, on a set -e
    # abort anywhere inside run_opus, and on a signal delivered while the
    # subshell runs. Proportionate for a local gate (not a privilege
    # boundary), with no broader trap machinery than that one line; the
    # directory is mode 700 for its whole (short) life regardless.
    # run_opus is called exactly once, so one global variable and one EXIT
    # trap registration is sufficient — a second call would need its own
    # cleanup accounting, which this does not attempt.
    _VSELF_TMP_DIR=$(mktemp -d "$OUT_DIR/vself_opus.XXXXXX")
    trap 'rm -rf "$_VSELF_TMP_DIR"' EXIT
    chmod 700 "$_VSELF_TMP_DIR"
    tmp_prompt="$_VSELF_TMP_DIR/prompt.txt"
    printf '%s' "$prompt" > "$tmp_prompt"
    # Pre-use sanity check (codex HIGH, round 4): fail closed on anything
    # other than a regular file this process owns, rather than handing an
    # unexpected path to the subprocess.
    if [[ -f "$tmp_prompt" && -O "$tmp_prompt" ]]; then
        # bootstrap/invoke_agent.sh replaces the raw direct-CLI invocation. Context
        # isolation (fresh session, no dynamic system-prompt sections, no
        # session persistence) is no longer spelled out here — it is baked into
        # agent_invoke_cli.py's own claude invocation for every caller, not
        # something this script asserts. --agent self-reviewer fills the
        # adversarial self-review seat (self-reviewer.md, #1673).
        # REQUIRE_ENV_AUTH_FLAG (set near the top of this file, AD-16.7) is
        # "--require-env-auth" by default (strict) and empty only when the
        # caller explicitly passed --allow-keychain-auth.
        result=$(bash "$ROOT/bootstrap/invoke_agent.sh" \
            --agent self-reviewer \
            --posture review-read-only \
            --input-file "$tmp_prompt" \
            --dimension self-review \
            --lens self-review \
            --timeout "$AI_REVIEW_TIMEOUT" \
            --model "$MODEL" \
            ${REQUIRE_ENV_AUTH_FLAG}) || rc=$?
    else
        echo "  ERROR: prompt temp file failed its pre-use sanity check ($tmp_prompt is not a regular file owned by this process) — aborting Opus self-review rather than proceeding." >&2
        rc=1
    fi
    # invoke_agent.sh exits non-zero ONLY when no document was produced at
    # all (its own interpreter-resolution failure, or a usage error, §3.3);
    # a structured invocation_failed document (cli_unavailable, timeout,
    # not_authenticated, a malformed response, ...) still exits 0 with a
    # "verdict":"error" document already in $result — AD-6's rule
    # (`_verdict_for_outcome`'s outcome=="invocation_failed" forces verdict=
    # "error" unconditionally, `agent_invoke_cli.py:961-969`). That document
    # is a SUPERSET of the block this function used to synthesize by hand
    # (same "verdict":"error" signal, plus outcome/outcome_detail/
    # observability fields the old stub never had), so nothing is
    # synthesized here (#1362's fix generalised): on the hard-failure path
    # below, $result is empty; extract_json_objects finds no parseable
    # block in it, and --strict-empty (used by the finalize step below)
    # already treats "no blocks parsed" as verdict=error.
    #
    # rc != 0 means, by invoke_agent.sh's own contract, that NO document was
    # produced — any bytes present on $result in that case are not a result
    # document (a crash's partial stdout, at most) and must not reach the
    # parser downstream as if they were one (agy LOW, round 3). Clear it
    # explicitly rather than relying on it happening to already be empty.
    if [[ $rc -ne 0 || -z "${result//[[:space:]]/}" ]]; then
        echo "  ERROR: bootstrap/invoke_agent.sh produced no result (rc=$rc) for Opus self-review — recording as a review FAILURE, not a clean pass (#1362)." >&2
        result=""
    fi
    echo "$result"
}

echo "Running Opus self-review (${MODEL})..."
OPUS_OUT=$(run_opus)
# Extract outcome/outcome_detail HERE, BEFORE anything is written to
# $OUTFILE — say WHICH failure occurred, not just THAT one did, so
# outcome_detail (the whole point of this migration's observability
# improvement, #1676) doesn't survive only inside a raw JSON blob no human
# reads. python3 is already a hard dependency of this script (the
# $VALIDATION_LOGIC delegation below); jq is not guaranteed present, so this
# reuses that same tooling rather than adding a new one.
#
# Parsed through validation_logic.extract_json_objects — the SAME function
# the finalize step's `process` call uses further down, on the SAME bytes —
# a plain `json.load` here would be a second, independent parser, and a gate
# whose status line and blocking decision can read the same bytes
# differently is worse than one that is merely terse. Requiring EXACTLY one
# matched block is deliberate: extract_json_objects is prose/multi-object
# tolerant (built for agy/codex, which sometimes wrap replies in
# commentary), but invoke_agent.sh's own contract is one bare JSON document
# with nothing else — zero or 2+ blocks means something is unexpectedly
# wrong.
#
# agy HIGH (round 3): a PARSE_ERROR must fail closed by CONSTRUCTION, not by
# hoping the finalizer happens to agree — extract_json_objects has no
# "exactly one block" rule of its own, so a multi-block $OUTFILE could still
# parse to "approve" there even though the status line said FAILED (the
# console and the exit code disagreeing, the exact inverse of the divergence
# this parser-unification was built to close). So on PARSE_ERROR, $OUTFILE
# gets a SYNTHESIZED blocking document in place of the unparseable raw
# output — never the raw $OPUS_OUT — guaranteeing the finalizer, reading
# ONLY that document, blocks too. This is the same fail-closed synthesis
# shape validate_scripts.sh's run_reviewer() already uses for its own
# required-lane failures.
_opus_outcome="__EMPTY__"
_opus_outcome_detail="-"
_opus_verdict="-"
_opus_emit="$OPUS_OUT"
if [[ -n "${OPUS_OUT//[[:space:]]/}" ]]; then
    IFS=$'\t' read -r _opus_outcome _opus_outcome_detail _opus_verdict < <(
        printf '%s' "$OPUS_OUT" | python3 -c '
import importlib.util, sys

try:
    spec = importlib.util.spec_from_file_location("validation_logic", sys.argv[1])
    if spec is None or spec.loader is None:
        raise RuntimeError("no loader for validation_logic.py")
    vl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vl)
    blocks = vl.extract_json_objects(sys.stdin.read())
    if len(blocks) != 1:
        raise ValueError("expected exactly one JSON block, got {}".format(len(blocks)))
    doc = blocks[0]
except Exception:
    print("__PARSE_ERROR__\t__PARSE_ERROR__\t__PARSE_ERROR__")
else:
    print("{}\t{}\t{}".format(
        doc.get("outcome") or "-", doc.get("outcome_detail") or "-", doc.get("verdict") or "-"
    ))
' "$VALIDATION_LOGIC" 2>/dev/null
    ) || { _opus_outcome="__PARSE_ERROR__"; _opus_outcome_detail="__PARSE_ERROR__"; _opus_verdict="__PARSE_ERROR__"; }
fi
# agy HIGH (round 3): a PARSE_ERROR must fail closed by CONSTRUCTION, not by
# hoping the finalizer happens to agree — extract_json_objects has no
# "exactly one block" rule of its own, so a multi-block $OUTFILE could still
# parse to "approve" there even though the status line said FAILED (the
# console and the exit code disagreeing, the exact inverse of the divergence
# this parser-unification was built to close). So on PARSE_ERROR — and on
# any outcome value that is neither "completed" nor "invocation_failed"
# (the primitive's own closed 2-value type; unreachable today, but a status
# line that fails open on a future third value would be the same bug again)
# — $OUTFILE gets a SYNTHESIZED blocking document in place of the raw
# output, never the raw $OPUS_OUT itself, guaranteeing the finalizer,
# reading ONLY that document, blocks too. This is the same fail-closed
# synthesis shape validate_scripts.sh's run_reviewer() already uses for its
# own required-lane failures.
if [[ "$_opus_outcome" == "__PARSE_ERROR__" ]]; then
    # agy MEDIUM (round 4): the synthesized document's own "fix" field used
    # to tell the operator to "inspect the raw output captured in this
    # file" — but $OUTFILE gets THIS synthesized document in place of the
    # raw output, so that raw output is exactly what is no longer there. An
    # operator debugging an unparseable response needs the bytes that
    # failed to parse, so they are preserved in a SEPARATE file (never fed
    # back into $OUTFILE — that would reintroduce the round-3 fail-open),
    # and the message names its real path.
    _opus_raw_dump="$OUT_DIR/self-review-unparseable-${TIMESTAMP}.txt"
    printf '%s' "$OPUS_OUT" > "$_opus_raw_dump"
    _opus_emit='{"reviewer":"opus-self","lens":"self-review","findings":[{"severity":"blocking","category":"fail-open","files":["<reviewer:opus-self>"],"description":"bootstrap/invoke_agent.sh produced output that could not be parsed as exactly one JSON document (a required precondition for the Opus self-review lane).","fix":"Re-run validate_self.sh; the unparseable output was preserved at '"$_opus_raw_dump"' for inspection."}],"verdict":"request_changes","summary":"Opus self-review output was unparseable — fail-closed (agy HIGH, round 3)."}'
elif [[ "$_opus_outcome" != "__EMPTY__" && "$_opus_outcome" != "completed" && "$_opus_outcome" != "invocation_failed" ]]; then
    _opus_emit='{"reviewer":"opus-self","lens":"self-review","findings":[{"severity":"blocking","category":"fail-open","files":["<reviewer:opus-self>"],"description":"bootstrap/invoke_agent.sh returned an outcome value this script does not recognise (neither completed nor invocation_failed).","fix":"Investigate — the primitive is expected to emit only those two outcome values."}],"verdict":"request_changes","summary":"Unrecognised outcome — fail-closed."}'
fi
{
    echo "## opus-self — Adversarial Self-Review"
    echo '```json'
    echo "$_opus_emit"
    echo '```'
    echo ""
} >> "$OUTFILE"
# "done" means the reviewer actually completed a review AND found nothing
# blocking — nothing else does. Two agy findings, round 3:
#   MEDIUM (:398) — the previous `else → done` fallthrough treated ANY
#     outcome other than the three named failure buckets as success,
#     including a missing/unexpected value the extractor renders "-".
#     Inverted: `done` requires outcome=="completed" explicitly; every other
#     outcome, named or not, is reported as a failure naming the value.
#   Found during the requested sweep of this same seam, not originally
#     reported: outcome=="completed" only means the INVOCATION succeeded —
#     the self-reviewer AGENT can still legitimately return
#     verdict:"request_changes" with real blocking findings (the normal,
#     expected shape when it finds something), and the previous version
#     printed "done" for that too, misleading the console even though the
#     finalizer below was already correctly blocking. `done` now also
#     requires the document's own verdict to be "approve".
if [[ "$_opus_outcome" == "__EMPTY__" ]]; then
    echo "  FAILED — no result produced (see ERROR above)"
elif [[ "$_opus_outcome" == "__PARSE_ERROR__" ]]; then
    # agy LOW (round 4): the two occurrences below used a single-quoted
    # `\$OUTFILE`/`\$_opus_raw_dump`-style escape inside a double-quoted
    # string, which prints the LITERAL text "$OUTFILE" rather than
    # expanding it — the operator never saw the real path. Unescaped here
    # (and throughout this if/elif chain) so the actual paths print.
    echo "  FAILED — bootstrap/invoke_agent.sh output could not be parsed as exactly one JSON document — recorded as a blocking finding in $OUTFILE; the unparseable bytes are preserved at $_opus_raw_dump"
elif [[ "$_opus_outcome" == "invocation_failed" ]]; then
    echo "  FAILED — outcome=invocation_failed outcome_detail=${_opus_outcome_detail}"
    # Discoverability (AD-16.7): strict-by-default auth is a deliberate
    # breaking change for an interactive human on keychain auth — the
    # remedy must be named verbatim right where the failure surfaces, not
    # left to be inferred from outcome_detail alone.
    if [[ "$_opus_outcome_detail" == "not_authenticated" ]]; then
        echo "  If you are running this interactively with keychain auth (no CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_API_KEY set), re-run with --allow-keychain-auth." >&2
    fi
elif [[ "$_opus_outcome" == "completed" ]]; then
    if [[ "$_opus_verdict" == "approve" ]]; then
        echo "  done"
    else
        echo "  FAILED — review completed with verdict=${_opus_verdict} (blocking findings present — see $OUTFILE)"
    fi
else
    echo "  FAILED — unrecognised outcome '${_opus_outcome}' — recorded as a blocking finding (see $OUTFILE)"
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
