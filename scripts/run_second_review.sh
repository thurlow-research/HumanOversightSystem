#!/usr/bin/env bash
# run_second_review.sh — pre-PR cross-vendor second code review.
#
# Runs after internal review chain completes and risk validators score the step.
# Provides independent, cross-vendor perspective BEFORE the PR is opened.
# This is distinct from run_panel.sh (post-PR, posts PR threads that must resolve).
# Second review findings go to .claudetmp/second-review/ for oversight-evaluator.
#
# VENDOR ROLES (DECISIONS.md D4 — no Claude model as independent check):
#
#   agy (Gemini) — CONDITIONAL SCREENING
#     Fires when composite score ≥ OVERSIGHT_AGY_THRESHOLD (default: 0.30 = MEDIUM+).
#     Lens: correctness + spec adherence. Large context window fits whole-diff + spec.
#     Subscription: $20/month baseline → upgrade to $100/month to lower the threshold
#     without changing any logic (set OVERSIGHT_AGY_THRESHOLD lower in .env).
#
#   codex (OpenAI) — RESERVE
#     Fires when composite score ≥ OVERSIGHT_CODEX_THRESHOLD (default: 0.55 = HIGH+).
#     Lens: adversarial security probe against the project's specific threat model.
#     Stays at $20/month — scarcity is intentional; threshold controls frequency.
#     Do NOT upgrade to $100/month; it is a reserve tool, not a high-frequency one.
#
#   FALLBACK: if agy is unavailable and score ≥ CODEX_THRESHOLD, codex takes the
#     correctness lens too. NOTE: fallback runs ONE combined review (correctness +
#     security) instead of two separate targeted reviews. This is documented as an
#     intentional degradation — the alternative would be to require two codex calls
#     (expensive) or fail-closed (blocks the pipeline when agy is briefly unavailable).
#     At HIGH+, if BOTH vendors are unavailable, the script exits with a non-zero
#     status so the pipeline does not silently proceed without cross-vendor review.
#
# INDEPENDENCE: Do NOT pass internal reviewer (code-reviewer agent) findings to
# these reviewers. Independence is the value — decorrelated judgement catches
# different classes of bugs. The oversight-evaluator compares all sets of findings.
#
# ISSUE CREATION: critical/high severity findings create GitHub issues immediately
# (labels: second-review-finding). These feed the historical risk database and are
# visible to future risk assessor runs on the same files.
#
# THRESHOLDS (override via environment or .env):
#   OVERSIGHT_AGY_THRESHOLD=0.30    fire agy when composite score >= this
#   OVERSIGHT_CODEX_THRESHOLD=0.55  fire codex when composite score >= this
#
# DIFF-CENTRIC CONTEXT (SPEC-379): --diff-only is DEFAULT ON. Reviewers receive the
# diff as primary input — never the full file tree. Evidence (Kumar 2026 / SWE-PRBench)
# shows that providing more-than-diff context REDUCES reviewer detection rates. Pass
# --no-diff-only to disable (prints a startup warning). When --diff-only is on and a
# reviewer response asks for full-repository context, an ADVISORY entry is appended to
# the run's output file (non-blocking; does not change verdict or exit code).
#
# Usage:
#   ./scripts/run_second_review.sh --step 3 --score 0.67
#   ./scripts/run_second_review.sh --diff HEAD~1 --score 0.45
#   ./scripts/run_second_review.sh --files a.py b.py --score 0.71
#   ./scripts/run_second_review.sh --step 3 --no-diff-only   # disable diff-centric (warns)
#   --diff-only       (default) reviewers get only the diff; advisory on context requests
#   --no-diff-only    disable diff-centric mode — full context allowed (NOT recommended)
#
# Prerequisites: agy authenticated (`agy` login), codex authenticated (`codex` login)

set -euo pipefail

# ADR-1683 D-1/D-2: the one shared bash launch primitive for agy/codex. Provides
# vendor_invoke() / vendor_invoke_tmpfile(); sources run_with_retry.sh itself for
# with_timeout (ADR-1643 AD-5.3 — do not add a third timeout implementation).
# shellcheck source=scripts/oversight/lib/vendor_invoke.sh
source "$(dirname "${BASH_SOURCE[0]}")/oversight/lib/vendor_invoke.sh"

# Thresholds — trusted baseline first. A trusted caller (config.sh / orchestrator)
# may set these via the real environment; absent that, the built-in defaults apply.
AGY_THRESHOLD="${OVERSIGHT_AGY_THRESHOLD:-0.30}"
CODEX_THRESHOLD="${OVERSIGHT_CODEX_THRESHOLD:-0.55}"

# ADR-1683 D-2: shared vendor-invocation timeout. 900s is deliberately well
# above agy's own --print-timeout default of 5m, so this catches only a genuine
# hang and does not newly truncate legitimate long reviews.
SECOND_REVIEW_VENDOR_TIMEOUT="${SECOND_REVIEW_VENDOR_TIMEOUT:-900}"

# Read threshold overrides from the repo-local .env WITHOUT executing it as shell.
# Only the two specific keys are extracted via grep/cut (strict numeric regex).
# Sourcing a repo-local .env would execute author-controlled shell before review,
# defeating the gate's purpose (HOS#765).
#
# The .env is author-controlled and UNTRUSTED: raising a threshold suppresses
# reviewer firing — an author under review could commit OVERSIGHT_AGY_THRESHOLD=9
# to self-skip the cross-vendor review (verdict: skipped, exit 0 — HOS#985). So a
# .env value may only *lower* (strengthen) a threshold, never raise it: the
# effective value is min(trusted_baseline, clamp(env_value, 0, 1)). Out-of-range
# or non-numeric values are ignored and the trusted baseline is kept.
if [[ -f .env ]]; then
    # Fold a raw .env value into the trusted baseline: clamp to [0,1] and never
    # allow a raise above the baseline. Echoes the effective threshold. awk does
    # the float comparison bash can't, and rejects malformed values (e.g. "0.3.0").
    _clamp_lower() {
        awk -v base="$1" -v v="$2" 'BEGIN{
            if (v ~ /^[0-9]+(\.[0-9]+)?$/) {
                if (v < 0) v = 0; else if (v > 1) v = 1;
                print (v < base ? v : base);
            } else { print base }
        }'
    }
    # `|| true` keeps a no-match (expected when the key is absent) non-fatal under
    # `set -euo pipefail` — without it grep's exit 1 propagates and aborts the gate
    # before any review runs (HOS#961). The `[[ -n "$_val" ]]` guard handles the
    # empty result, leaving the trusted baseline in place.
    _val=$(grep -E '^OVERSIGHT_AGY_THRESHOLD=[0-9.]+$' .env | cut -d= -f2 | head -1 || true)
    [[ -n "$_val" ]] && AGY_THRESHOLD="$(_clamp_lower "$AGY_THRESHOLD" "$_val")"
    _val=$(grep -E '^OVERSIGHT_CODEX_THRESHOLD=[0-9.]+$' .env | cut -d= -f2 | head -1 || true)
    [[ -n "$_val" ]] && CODEX_THRESHOLD="$(_clamp_lower "$CODEX_THRESHOLD" "$_val")"
    unset _val
    unset -f _clamp_lower
fi

OUT_DIR=".claudetmp/second-review"
STEP=""
SCORE=""
TIER=""
DIFF_REF=""
FILES=()
DIFF_ONLY=1   # SPEC-379: diff-centric review is DEFAULT ON (Kumar 2026 / SWE-PRBench)
# SPEC-78: ledger file resolved after STEP is confirmed; see post-parse dispatch below.
LEDGER_FILE=""
_SUBCMD=""
_REC_FILES=""
_REC_CLASS=""
_REC_DISP=""

# SPEC-219: the reviewed commit range, recorded in every report header so the
# oversight-evaluator can verify the second review covered the step's canonical
# base_sha..head_sha. Default to the absent-range sentinel `none` (architect
# binding B2) so the field is NEVER emitted empty, on any path. Resolved to a
# full-SHA pair, `UNCOMMITTED`, or `none` at diff-derivation time (binding B3).
REVIEWED_RANGE="none"

# SPEC-379 R4 — advisory pattern list (case-insensitive). When --diff-only is on and a
# reviewer's response contains one of these, an ADVISORY (non-blocking) is logged.
# This is the single named location for the pattern list in this script.
DIFF_ONLY_REQUEST_PATTERNS='full repo|all files|entire codebase|repository context|all source files|project files'

while [[ $# -gt 0 ]]; do
    case "$1" in
        --score)        SCORE="$2";    shift 2 ;;
        --tier)         TIER="$2";     shift 2 ;;
        --step)         STEP="$2";     shift 2 ;;
        --diff)         DIFF_REF="$2"; shift 2 ;;
        --files)        shift; while [[ $# -gt 0 && "$1" != --* ]]; do FILES+=("$1"); shift; done ;;
        --diff-only)    DIFF_ONLY=1; shift ;;
        --no-diff-only) DIFF_ONLY=0; shift ;;
        # SPEC-78: ledger subcommands. --step must be supplied before these.
        --record)
            _SUBCMD="record"
            _REC_FILES="${2:-}"; _REC_CLASS="${3:-}"; _REC_DISP="${4:-}"
            shift; [[ $# -ge 1 ]] && shift; [[ $# -ge 1 ]] && shift; [[ $# -ge 1 ]] && shift ;;
        --reset)
            _SUBCMD="reset"; shift ;;
        *)              shift ;;
    esac
done

# SPEC-379 R2 — opting out of diff-centric mode emits a startup warning.
if [[ "$DIFF_ONLY" -eq 0 ]]; then
    echo "[WARN] --diff-only disabled: full-file context enabled. Evidence (Kumar 2026 / SWE-PRBench) shows this can reduce reviewer detection rates." >&2
fi

if [[ -z "$STEP" ]]; then
    echo "Error: --step <N> is required (used to name output and match oversight-evaluator lookup)" >&2
    exit 1
fi

# SPEC-78: resolve ledger path now that STEP is confirmed.
LEDGER_FILE="${OUT_DIR}/step${STEP}-ledger.jsonl"

# SPEC-78: post-parse dispatch for --record and --reset subcommands.
# These short-circuit before any reviewer invocation or diff-derivation.
if [[ "$_SUBCMD" == "record" ]]; then
    [[ -z "$_REC_FILES" || -z "$_REC_CLASS" || -z "$_REC_DISP" ]] && {
        echo "Usage: run_second_review.sh --step <N> --record <files> <class> <disposition>" >&2
        echo "  disposition: fixed | filed:#<N> | residual | noise" >&2
        exit 1
    }
    mkdir -p "$OUT_DIR"
    python3 "$(dirname "$0")/oversight/validation_logic.py" record \
        --ledger "$LEDGER_FILE" \
        --files "$_REC_FILES" \
        --class "$_REC_CLASS" \
        --disposition "$_REC_DISP"
    exit $?
fi
if [[ "$_SUBCMD" == "reset" ]]; then
    rm -f "$LEDGER_FILE"
    echo "reset: removed ledger for step ${STEP} (${LEDGER_FILE})"
    exit 0
fi

# Read score from validator summary if not provided
if [[ -z "$SCORE" && -f ".claudetmp/oversight/validators/summary.json" ]]; then
    SCORE=$(python3 -c \
        "import json; d=json.load(open('.claudetmp/oversight/validators/summary.json')); \
         print(d.get('composite_score', 0))" 2>/dev/null || echo "0")
fi

SCORE="${SCORE:-0}"

# Determine which reviewers fire.
# Fire on the validated TIER floor OR the composite score — whichever demands
# more review. The deterministic risk floor raises tier (auth→HIGH, booking/
# payment→CRITICAL) WITHOUT raising the composite score, so a HIGH-by-floor step
# can have a low score; gating on score alone would silently skip the mandatory
# cross-vendor review the tier requires. Tier is the ratchet floor here too.
RUN_AGY=false
RUN_CODEX=false
AGY_AVAILABLE=false
CODEX_AVAILABLE=false

# Reviewer selection (SPEC-331): the threshold comparison and tier-floor rules
# live in scripts/oversight/second_review_logic.py (named, unit-testable). The
# module prints RUN_AGY=true|false and RUN_CODEX=true|false for us to eval. Tier
# normalization and the >= threshold comparison are done inside the module.
SELECT_OUT=$(python3 "$(dirname "$0")/oversight/second_review_logic.py" \
    select-reviewers --score "$SCORE" --tier "$TIER" \
    --agy-threshold "$AGY_THRESHOLD" --codex-threshold "$CODEX_THRESHOLD") || {
    echo "ERROR: reviewer selection helper exited non-zero — cannot determine which reviewers to run." >&2
    echo "       Failing closed: cross-vendor review cannot be skipped silently (#681)." >&2
    exit 1
}
if [[ -z "$SELECT_OUT" ]]; then
    echo "ERROR: reviewer selection helper returned empty output — cannot determine which reviewers to run." >&2
    echo "       Failing closed: cross-vendor review cannot be skipped silently (#681)." >&2
    exit 1
fi
eval "$SELECT_OUT"   # sets RUN_AGY / RUN_CODEX to true|false

if ! $RUN_AGY && ! $RUN_CODEX; then
    echo "run_second_review: score=$SCORE below both thresholds (agy≥$AGY_THRESHOLD, codex≥$CODEX_THRESHOLD) and tier=${TIER:-none} below MEDIUM — skip"
    # Write a sentinel so oversight-evaluator can distinguish "skipped" from "missing"
    mkdir -p ".claudetmp/second-review"
    TS=$(date +%Y%m%dT%H%M%S)
    cat > ".claudetmp/second-review/step${STEP}-${TS}.md" <<EOF
# Second Review — Step ${STEP}
Timestamp: ${TS}
verdict: skipped
reviewed_range: none
reason: composite score=${SCORE} below both thresholds (agy≥${AGY_THRESHOLD}, codex≥${CODEX_THRESHOLD}) and tier=${TIER:-none} below MEDIUM
agy_threshold: ${AGY_THRESHOLD}
codex_threshold: ${CODEX_THRESHOLD}
validated_tier: ${TIER:-none}
EOF
    exit 0
fi

# Check availability
command -v agy &>/dev/null  && AGY_AVAILABLE=true  || true
command -v codex &>/dev/null && CODEX_AVAILABLE=true || true

# Fallback: if agy unavailable and codex threshold reached, codex handles both lenses
if $RUN_AGY && ! $AGY_AVAILABLE && $CODEX_AVAILABLE && $RUN_CODEX; then
    echo "run_second_review: agy unavailable — codex will cover correctness lens too (degraded: one combined review)"
fi

# Fail-closed checks by risk band:
#   MEDIUM (score ≥ 0.30): agy is required. If agy unavailable and codex can't cover
#     (score < codex threshold), fail — an unreviewed MEDIUM step cannot proceed silently.
#   HIGH+ (score ≥ CODEX_THRESHOLD): agy required + codex required. Codex FALLBACK is
#     allowed when agy is unavailable (one combined review instead of two targeted ones).
#     Fail only if BOTH vendors are unavailable. This is documented in contract §7.
if $RUN_AGY && ! $AGY_AVAILABLE && ! $RUN_CODEX; then
    echo "ERROR: score=${SCORE} is MEDIUM+ (agy required) but agy is unavailable and" >&2
    echo "       score is below codex threshold (${CODEX_THRESHOLD}) — no fallback reviewer." >&2
    echo "Options:" >&2
    echo "  1. Authenticate agy: ./scripts/setup_clis.sh auth" >&2
    echo "  2. Human override: create .claudetmp/oversight/human-tier-override.md" >&2
    exit 1
fi

python3 -c "
s=float('${SCORE:-0}'); threshold=float('${CODEX_THRESHOLD}')
exit(0 if s < threshold else 1)
" 2>/dev/null || {
    if ! $AGY_AVAILABLE && ! $CODEX_AVAILABLE; then
        echo "ERROR: score=${SCORE} is HIGH+ (≥${CODEX_THRESHOLD}) but neither agy nor codex is available." >&2
        echo "Options:" >&2
        echo "  1. Authenticate a reviewer: ./scripts/setup_clis.sh auth" >&2
        echo "  2. Human override: create .claudetmp/oversight/human-tier-override.md" >&2
        exit 1
    fi
}

mkdir -p "$OUT_DIR"
TIMESTAMP=$(date +%Y%m%dT%H%M%S)
OUTFILE="$OUT_DIR/step${STEP}-${TIMESTAMP}.md"

# --- Build diff content + capture reviewed range (SPEC-219) ---
# REVIEWED_RANGE is resolved in the SAME if/elif/else that derives DIFF_CONTENT so
# the recorded range and the diff source can never diverge (binding B3), and the
# UNCOMMITTED/none sentinels are mutually exclusive by construction (binding B4):
# only one branch runs. All SHAs are full 40-char (git rev-parse / get_step_range).
if [[ -n "$DIFF_REF" && "$DIFF_REF" == *..* ]]; then
    # Path: --diff <A>..<B> (range form). BASE=rev-parse A, HEAD=rev-parse B.
    DIFF_CONTENT=$(git diff "$DIFF_REF" 2>/dev/null || echo "")
    _RANGE_A="${DIFF_REF%%..*}"
    _RANGE_B="${DIFF_REF##*..}"
    _BASE_SHA=$(git rev-parse "$_RANGE_A" 2>/dev/null || echo "")
    _HEAD_SHA=$(git rev-parse "$_RANGE_B" 2>/dev/null || echo "")
    [[ -n "$_BASE_SHA" && -n "$_HEAD_SHA" ]] && REVIEWED_RANGE="${_BASE_SHA}..${_HEAD_SHA}"
elif [[ -n "$DIFF_REF" ]]; then
    # Path 1: --diff <ref> (single ref). git diff <ref> compares <ref> to the tree.
    # BASE=rev-parse <ref>, HEAD=rev-parse HEAD — NEW calls at derivation time (B3).
    DIFF_CONTENT=$(git diff "$DIFF_REF" 2>/dev/null || echo "")
    _BASE_SHA=$(git rev-parse "$DIFF_REF" 2>/dev/null || echo "")
    _HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
    [[ -n "$_BASE_SHA" && -n "$_HEAD_SHA" ]] && REVIEWED_RANGE="${_BASE_SHA}..${_HEAD_SHA}"
elif [[ ${#FILES[@]} -gt 0 ]]; then
    # Path 3 (scoped): --files ... → HEAD-vs-worktree for named files. A dirty
    # worktree means the review sees uncommitted state → UNCOMMITTED (BC-219-3).
    DIFF_CONTENT=$(git diff HEAD -- "${FILES[@]}" 2>/dev/null || cat "${FILES[@]}" 2>/dev/null || echo "")
    if ! git diff --quiet HEAD -- "${FILES[@]}" 2>/dev/null; then
        REVIEWED_RANGE="UNCOMMITTED"
    else
        _HEAD_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
        [[ -n "$_HEAD_SHA" ]] && REVIEWED_RANGE="${_HEAD_SHA}..${_HEAD_SHA}"
    fi
else
    # --step N path: canonical step range via the shared helper (SPEC-220 / binding
    # B1). Used when no --diff/--files narrows the diff — the run relies on the
    # step's canonical range. The helper owns range derivation; we own the
    # merge-base fallback for a leading-empty base and the empty→none sentinel.
    if [[ -f "$(dirname "$0")/oversight/lib/step_range.sh" ]]; then
        # shellcheck source=scripts/oversight/lib/step_range.sh
        . "$(dirname "$0")/oversight/lib/step_range.sh"
        _STEP_RANGE=$(get_step_range "$STEP" 2>/dev/null || echo "")
    else
        _STEP_RANGE=""
    fi
    if [[ -z "$_STEP_RANGE" ]]; then
        # Step N has no event in the log → no range. Do NOT invoke a reviewer; emit
        # the no-content sentinel with reviewed_range: none (binding B2, AC-12).
        echo "run_second_review: step ${STEP} has no range in audit log — writing skipped (none) sentinel"
        mkdir -p "$OUT_DIR"
        TS=$(date +%Y%m%dT%H%M%S)
        cat > "$OUT_DIR/step${STEP}-${TS}.md" <<EOF
# Second Review — Step ${STEP}
Timestamp: ${TS}
verdict: skipped
highest_severity: none
unresolved_findings: 0
reviewed_range: none
reason: no commit range for step ${STEP} in audit log
EOF
        exit 0
    fi
    _BASE_SHA="${_STEP_RANGE%%..*}"
    _HEAD_SHA="${_STEP_RANGE##*..}"
    if [[ -z "$_BASE_SHA" ]]; then
        # Leading-empty base (step 1, or step N-1 has no event). Merge-base fallback
        # — byte-identical to the SPEC-220 evaluator so both resolve BASE the same
        # way (binding B1).
        _BASE_SHA=$(git merge-base HEAD "$(git rev-parse HEAD~1 2>/dev/null || echo HEAD)")
    fi
    REVIEWED_RANGE="${_BASE_SHA}..${_HEAD_SHA}"
    DIFF_CONTENT=$(git diff "${_BASE_SHA}..${_HEAD_SHA}" 2>/dev/null || echo "")
fi

if [[ -z "$DIFF_CONTENT" ]]; then
    echo "run_second_review: no diff content — writing skipped sentinel"
    mkdir -p "$OUT_DIR"
    TS=$(date +%Y%m%dT%H%M%S)
    cat > "$OUT_DIR/step${STEP}-${TS}.md" <<EOF
# Second Review — Step ${STEP}
Timestamp: ${TS}
verdict: skipped
highest_severity: none
unresolved_findings: 0
reviewed_range: none
reason: no diff content detected
EOF
    exit 0
fi

SPEC_CONTEXT=""
# Load project identity from config.sh (#685 — was hardcoded to CondoParkShare)
PROJECT_NAME="" PROJECT_STACK="" SPEC_FILE=""
[[ -f "scripts/framework/config.sh" ]] && source scripts/framework/config.sh
# Consumer projects may define SPEC_FILE in their config.sh
SPEC_CONTEXT=""
if [[ -n "${SPEC_FILE:-}" && -f "$SPEC_FILE" ]]; then
    SPEC_CONTEXT=$(cat "$SPEC_FILE")
fi

# ADR-1683 D-3: the prompt embeds a derived DIGEST of the validator summary, not
# the raw document. The full document's `evidence`/`findings`/`checklist_items`
# arrays are exactly the internal-reviewer "anchoring" content this script's own
# header says must NOT be passed to these reviewers — the digest keeps only the
# risk-context scalars (composite score, per-dimension scores/weights) that bear
# on a correctness+spec-adherence lens. Degradation is never silent on ANY path:
# second_review_logic.py prints a stderr line naming the tier and byte count
# when it drops to tier 2/3, and one naming the cause when it omits the digest
# entirely (summary.json unreadable, or parsed but not a JSON object). The
# latter exits 0 by design — a degraded digest must not kill the review — so
# that stderr line is the only operator signal that context was lost.
VALIDATOR_DIGEST=""
if [[ -f ".claudetmp/oversight/validators/summary.json" ]]; then
    VALIDATOR_DIGEST=$(python3 "$(dirname "$0")/oversight/second_review_logic.py" \
        digest-validators --file ".claudetmp/oversight/validators/summary.json")
fi

echo "=== Second review: step=${STEP} score=${SCORE} ==="
echo "  agy threshold:   $AGY_THRESHOLD  → $(  $RUN_AGY   && echo "FIRE"   || echo "skip")"
echo "  codex threshold: $CODEX_THRESHOLD → $($RUN_CODEX && echo "FIRE" || echo "skip")"
echo "Output: $OUTFILE"
echo ""

# Machine-readable header written first; evaluator reads these top-level fields.
# Individual reviewer JSON blocks follow inside fenced sections.
# verdict and highest_severity are updated at the end of the script.
{
    printf "# Second Review — Step %s\n" "$STEP"
    printf "Score: %s | Timestamp: %s\n" "$SCORE" "$TIMESTAMP"
    printf "verdict: pending\n"
    printf "reviewed_range: %s\n" "$REVIEWED_RANGE"
    printf "highest_severity: none\n"
    printf "unresolved_findings: 0\n"
    printf "blocking_count: 0\n"
    printf "new_blocking_count: 0\n"
    printf "agy_threshold: %s | codex_threshold: %s\n\n" "$AGY_THRESHOLD" "$CODEX_THRESHOLD"
} > "$OUTFILE"

# ── Helper: create GitHub issue for high/critical findings ──────────────────
create_finding_issues() {
    local reviewer="$1"
    local findings_json="$2"

    python3 - "$reviewer" "$findings_json" "$STEP" <<'PYEOF'
import json, subprocess, sys

reviewer = sys.argv[1]
step = sys.argv[3]

try:
    data = json.loads(sys.argv[2])
    findings = data.get("findings", [])
except Exception:
    sys.exit(0)

for f in findings:
    sev = f.get("severity", "low").lower()
    if sev not in ("critical", "high"):
        continue

    title = f"Second review [{reviewer}]: {f.get('finding','?')[:80]}"
    cwe = f.get("cwe", "")
    body_parts = [
        f"**Reviewer:** {reviewer}",
        f"**Step:** {step}",
        f"**Severity:** {sev}",
    ]
    if cwe:
        body_parts.append(f"**CWE:** {cwe}")
    body_parts += [
        f"**File:** {f.get('file','?')}:{f.get('line','?')}",
        f"**Finding:** {f.get('finding','')}",
        f"**Why:** {f.get('why', f.get('attack_scenario',''))}",
        f"**Suggestion:** {f.get('suggestion','')}",
        "",
        "*Created by run_second_review.sh — feeds historical risk assessor.*",
    ]

    cmd = [
        "gh", "issue", "create",
        "--title", title,
        "--body", "\n".join(body_parts),
        "--label", "second-review-finding",
    ]
    if sev == "critical":
        cmd += ["--label", "security-finding"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            print(f"  Issue created: {result.stdout.strip()}")
    except Exception as e:
        print(f"  Issue creation failed: {e}", file=sys.stderr)
PYEOF
}

# ── JSON salvage (HOS#113, #1737) ────────────────────────────────────────────
# Agentic review CLIs (agy especially) sometimes wrap the requested JSON in
# markdown fences or prose, narrate instead of emitting JSON at all, or (agy's
# `--output-format json`) wrap it in a STATUS ENVELOPE whose review is a JSON
# STRING nested in a `response` field (#1737 — the envelope's top-level keys
# are conversation_id/status/response/usage and never `verdict`/`findings`/
# `attacks`, so the original key-test scan below never matched it and this
# function fell through to treating the whole envelope as unparseable prose,
# which the aggregator then silently defaulted to `verdict: approve`).
#
# The logic now lives in scripts/oversight/second_review_logic.py
# (`salvage_review_json` / `_unwrap_envelope`), importable and unit-testable
# per #314 policy. This function is a thin shell wrapper: write the raw
# response to a tmpfile (vendor_invoke_tmpfile — cleaned up on every exit
# path per D-6, no per-call rm needed) and call the `salvage` CLI subcommand.
# Contract unchanged: prints the salvaged review JSON on stdout and exits 0,
# or prints nothing and exits 1 when there is no review JSON to salvage.
#
# Optional 2nd arg (`metadata_file`, #1718): when given, the envelope's own
# metadata — principally `usage.input_tokens` — is written there as JSON.
# #1718 established that agy can silently truncate an oversized prompt and
# still report `status: SUCCESS`; `usage.input_tokens` (what the model
# actually RECEIVED) is the only signal that catches that, and it is NOT
# recoverable from the salvaged review returned on stdout (the review is the
# unwrapped `response` body; the envelope's `usage` sits alongside it, one
# level up, and is discarded by the unwrap unless captured separately here).
# A char-based estimate of what was SENT cannot substitute for it — see
# salvage_with_metadata's docstring.
salvage_review_json() {
    local raw="$1" metadata_file="${2:-}" tmp
    tmp=$(vendor_invoke_tmpfile)
    printf '%s' "$raw" > "$tmp"
    if [[ -n "$metadata_file" ]]; then
        python3 "$(dirname "$0")/oversight/second_review_logic.py" salvage \
            --file "$tmp" --metadata-file "$metadata_file"
    else
        python3 "$(dirname "$0")/oversight/second_review_logic.py" salvage --file "$tmp"
    fi
}

# ── SPEC-379 R4: advisory when a reviewer requests full-repository context ────
# Non-blocking. Appends an ADVISORY block to $OUTFILE (the .claudetmp/second-review/
# file the oversight-evaluator reads). Does NOT change verdict, severity, or exit code.
log_context_advisory() {
    local reviewer="$1" response="$2"
    [[ "$DIFF_ONLY" -eq 1 ]] || return 0
    local match
    match=$(printf '%s' "$response" | grep -ioE "$DIFF_ONLY_REQUEST_PATTERNS" | head -1 || true)
    [[ -n "$match" ]] || return 0
    {
        echo "## [ADVISORY] Full-context request — diff-centric mode (SPEC-379)"
        echo '```'
        echo "[ADVISORY] Reviewer requested full-file/full-repository context while --diff-only is on."
        echo "Reviewer: ${reviewer}"
        echo "Matched pattern: ${match}"
        echo "Action: Full-context request not fulfilled. If a specific artifact is needed,"
        echo "re-invoke with the named file passed as targeted context."
        echo '```'
        echo ""
    } >> "$OUTFILE"
    echo "  [ADVISORY] ${reviewer} requested full-repo context (pattern: '${match}') — logged, non-blocking"
}

# ── ADR-1683 D-4: harness vs vendor invocation-failure record ───────────────
# Emits the required shape once vendor_invoke() has classified a failed call
# (VENDOR_INVOKE_CLASS/DETAIL/RC/BYTES/STDERR, set by the last vendor_invoke
# call). `failure_class` is the one-word operational answer ADR-1643 AD-6's
# outcome/outcome_detail vocabulary does not carry: who fixes this — the
# harness (this repo's invocation code) or the vendor (auth/quota/outage).
# Delegates JSON construction to python3 so stderr_tail (arbitrary vendor
# text) is correctly escaped — hand-composing this string in bash is exactly
# the class of defect this ADR exists to remove (#1683).
second_review_failure_json() {
    local reviewer="$1" record_lens="$2"
    local rc="${VENDOR_INVOKE_RC:-}"
    [[ -z "$rc" ]] && rc=0
    VI_REVIEWER="$reviewer" VI_LENS="$record_lens" VI_CLASS="$VENDOR_INVOKE_CLASS" \
    VI_DETAIL="$VENDOR_INVOKE_DETAIL" VI_RC="$rc" VI_BYTES="${VENDOR_INVOKE_BYTES:-0}" \
    VI_STDERR="$VENDOR_INVOKE_STDERR" python3 -c '
import json, os

reviewer = os.environ["VI_REVIEWER"]
failure_class = os.environ["VI_CLASS"]
detail = os.environ["VI_DETAIL"]
rc = int(os.environ["VI_RC"])

if failure_class == "harness":
    error = f"{reviewer} could not be invoked ({detail}) — no independent judgment was produced"
    summary = "Harness defect: fix the invocation, do not simply re-run."
else:
    error = f"{reviewer} ran and failed ({detail}, rc={rc}) — no independent judgment was produced"
    summary = "Vendor-side failure: resolve the vendor condition and re-run."

print(json.dumps({
    "reviewer": reviewer,
    "lens": os.environ["VI_LENS"],
    "verdict": "error",
    "findings": [],
    "outcome": "invocation_failed",
    "outcome_detail": detail,
    "failure_class": failure_class,
    "exit_code": rc,
    "prompt_bytes": int(os.environ["VI_BYTES"]),
    "stderr_tail": os.environ["VI_STDERR"],
    "error": error,
    "summary": summary,
}))
'
}

# ── agy: correctness + spec adherence ───────────────────────────────────────
run_agy_review() {
    local lens="$1"
    local extra_instructions="$2"
    # #1718: optional path to receive the envelope's actual usage (input/output
    # token counts) — the token-usage-report section below reads this instead
    # of trying to recover it from the returned review text, which no longer
    # carries the envelope wrapper after #1737's fix.
    local metadata_file="${3:-}"

    local prompt="You are an independent code reviewer. Your lens is CORRECTNESS and SPEC ADHERENCE.

IMPORTANT — this is a READ-ONLY review. Base your review ONLY on the diff and context provided below. Do NOT run shell commands, execute tests, or create/modify any files. Output your review directly; do not narrate tool use.

## Application context
${PROJECT_NAME:-this project} — ${PROJECT_STACK:-see config.sh for stack details}.

## Your task
${extra_instructions}

Review this diff for:
1. Logic errors, off-by-one errors, incorrect conditions, missing edge cases
2. Spec adherence gaps — requirements that appear unimplemented or wrong
3. Stack-specific risks: race conditions, N+1 queries, cross-tenant data leaks (see PROJECT_STACK in config.sh)
4. Missing error handling required by the spec

Do NOT comment on style, formatting, or repeat obvious design decisions.

Every finding MUST carry a \`category\` — exactly one of the five values in the
schema below, matching the numbered concern it came from (1 → logic-error,
2 → spec-adherence, 3 → stack-risk, 4 → error-handling, anything else → other).
Use the literal token, lowercase, no other wording: it is a dedup key that must
be byte-identical when the same finding is raised again on a later review pass.

## Risk context (static analysis scores — NOT internal reviewer findings)
\`\`\`json
${VALIDATOR_DIGEST}
\`\`\`

## Product spec
<spec>
${SPEC_CONTEXT}
</spec>

## Diff
\`\`\`diff
${DIFF_CONTENT}
\`\`\`

Return JSON only:
{
  \"reviewer\": \"agy\",
  \"lens\": \"${lens}\",
  \"findings\": [
    {
      \"severity\": \"critical|high|medium|low\",
      \"category\": \"logic-error|spec-adherence|stack-risk|error-handling|other\",
      \"file\": \"path/to/file.py\",
      \"line\": 0,
      \"finding\": \"one sentence: what is wrong\",
      \"why\": \"one sentence: why this is a problem\",
      \"suggestion\": \"specific change\"
    }
  ],
  \"verdict\": \"approve|request_changes\",
  \"summary\": \"one paragraph\"
}"

    # --sandbox: terminal restrictions so the review cannot mutate the working
    # tree. agy is an AGENTIC CLI — without this it has run pytest and created
    # files mid-review (HOS#113). A review step must never write to the tree.
    #
    # --output-format json: agy gained a JSON-output mode after HOS#113 was
    # filed (verified against the installed CLI, 2026-07-31, #1133). The salvage
    # + single-retry fallback below is kept regardless — the flag's payload
    # shape under real failure conditions (timeout, partial output, agy still
    # narrating despite the flag) hasn't been exercised yet, so this is
    # belt-and-braces, not a replacement for defensive parsing.
    #
    # STDIN, NOT ARGV (ADR-1683 / #1683): the prompt is written to a tmpfile and
    # read on stdin through vendor_invoke — never passed as a single argv
    # element. Linux's per-argument MAX_ARG_STRLEN (131,072 B) silently E2BIGs
    # execve on a large prompt otherwise, and `-p` is dropped: on the installed
    # build (agy 1.2.3) `-p` requires a value it is never given, which is itself
    # an arg-parse failure — see scripts/oversight/lib/vendor_invoke.sh's header
    # for the empirical verification and the harness/vendor failure taxonomy
    # (D-4) used below.
    local prompt_file stdout_file raw clean
    prompt_file=$(vendor_invoke_tmpfile)
    stdout_file=$(vendor_invoke_tmpfile)
    printf '%s' "$prompt" > "$prompt_file"

    if vendor_invoke agy "$SECOND_REVIEW_VENDOR_TIMEOUT" "$prompt_file" "$stdout_file" \
        --sandbox --output-format json; then
        raw=$(cat "$stdout_file")
    else
        raw=""
    fi
    clean=$(salvage_review_json "$raw" "$metadata_file") || clean=""

    # Retry ONLY when agy was actually invoked and responded with something
    # that didn't parse as JSON (prose) — a genuine invocation failure
    # (raw empty; classified via VENDOR_INVOKE_CLASS/DETAIL below) will not be
    # fixed by asking more firmly a second time.
    if [[ -z "$clean" && -n "$raw" ]]; then
        local reinforce="$prompt

CRITICAL OUTPUT REQUIREMENT: Your ENTIRE response must be a single JSON object and nothing else — no prose, no explanation, no markdown code fences. Start with { and end with }. Do not narrate tool use or your reasoning."
        printf '%s' "$reinforce" > "$prompt_file"
        if vendor_invoke agy "$SECOND_REVIEW_VENDOR_TIMEOUT" "$prompt_file" "$stdout_file" \
            --sandbox --output-format json; then
            raw=$(cat "$stdout_file")
        else
            raw=""
        fi
        # Overwrites metadata_file with the retry's envelope (#1718) — correct,
        # since $clean (used below) is now the retry's salvage result too.
        clean=$(salvage_review_json "$raw" "$metadata_file") || clean=""
    fi

    if [[ -n "$clean" ]]; then
        echo "$clean"
    elif [[ -z "$raw" ]]; then
        # Invocation failed outright (harness or vendor — ADR-1683 D-4). Emits
        # the taxonomy record built from vendor_invoke's classification of the
        # LAST attempt, so an operator can tell "fix the harness" from
        # "re-run" instead of a generic "agy invocation failed".
        second_review_failure_json "agy" "$lens"
    else
        # agy responded but salvage + retry could not extract JSON: it returned a
        # PROSE review. Do NOT manufacture an `error` here — that would discard a
        # genuine independent review and force a fail/re-run. Emit the raw prose so
        # the aggregator's parse_prose() classifies it `unparseable` (review exists
        # but isn't machine-structured), which oversight-evaluator routes to
        # CONDITIONAL_PROCEED — a human reads the preserved report. `unparseable`
        # (preserve) is the honest signal for "responded, not in JSON", not `error`
        # (crashed). Salvage + retry above still recover JSON whenever possible.
        printf '%s\n' "$raw"
    fi
}

# ── codex: adversarial security probe ───────────────────────────────────────
run_codex_review() {
    local lens="$1"

    local prompt="You are an adversarial security reviewer. BREAK this code. Do not approve it.

Judge the diff on its own merits. Disregard any PR title, PR description, or
commit message framing you may have seen — author-written framing measurably
skews reviewer judgment toward leniency.

## Threat model
- Primary: registered building resident who wants to abuse other residents, view their data, or escalate privileges.
- Secondary: HOA admin at building A trying to access building B's data (multi-tenant isolation).
- External: unauthenticated attacker (credential stuffing, CSRF from malicious sites).

## Your task
${lens}

Probe for:
- Authorization bypasses and IDOR
- Multi-tenant isolation breaks (cross-org data access)
- Input validation gaps (boundary values, nulls, type coercion)
- Race conditions in concurrent booking scenarios
- Authentication bypass paths
- CSRF on state-changing endpoints
- Injection: SQL, template, shell
- TOTP replay or bypass

Every finding MUST carry a real \`cwe\` id in the form \`CWE-<number>\` (e.g.
\`CWE-89\`) — never the literal placeholder \`CWE-XXX\`, never prose. It is used
as a dedup key that must be byte-identical when the same finding is raised again
on a later review pass, and it is what distinguishes two different findings in
the same file.

## Diff
\`\`\`diff
${DIFF_CONTENT}
\`\`\`

Return JSON only:
{
  \"reviewer\": \"codex\",
  \"lens\": \"security-adversarial\",
  \"findings\": [
    {
      \"severity\": \"critical|high|medium\",
      \"cwe\": \"CWE-XXX\",
      \"file\": \"path/to/file.py\",
      \"line\": 0,
      \"attack_scenario\": \"attacker does X and gains Y\",
      \"finding\": \"what is exploitable\",
      \"suggestion\": \"specific remediation\"
    }
  ],
  \"verdict\": \"approve|request_changes\",
  \"summary\": \"one paragraph\"
}"

    # codex reads the prompt on stdin and the subcommand is `codex exec` (HOS#199).
    # The old `codex --quiet` was an invalid invocation that ALWAYS failed; the
    # `2>/dev/null` then masked it as an empty `verdict:error`, so this path looked
    # like it ran a review and found nothing when codex was never actually invoked.
    #
    # This path was already stdin-safe before ADR-1683 — migrated onto the
    # shared vendor_invoke helper anyway (D-2/D-3 of that ADR): leaving two
    # invocation idioms in one file is how the agy path above drifted into
    # passing its prompt via argv in the first place, and the old local
    # `mktemp`/`rm -f` here leaked its tmpfile on the failure path (#1683 scope
    # item 1) — the helper's own per-process tmp dir + EXIT/INT/TERM trap (D-6)
    # covers every exit path, not just the success one.
    local prompt_file stdout_file result clean
    prompt_file=$(vendor_invoke_tmpfile)
    stdout_file=$(vendor_invoke_tmpfile)
    printf '%s' "$prompt" > "$prompt_file"

    if vendor_invoke codex "$SECOND_REVIEW_VENDOR_TIMEOUT" "$prompt_file" "$stdout_file"; then
        result=$(cat "$stdout_file")
    else
        # Invocation failed outright (harness or vendor — ADR-1683 D-4).
        second_review_failure_json "codex" "security-adversarial"
        return
    fi
    # Salvage the JSON in case codex wrapped it in prose/fences (HOS#113).
    clean=$(salvage_review_json "$result") || clean=""
    if [[ -n "$clean" ]]; then
        echo "$clean"
    else
        # codex responded but salvage failed → prose. Emit the raw prose so the
        # aggregator's parse_prose() classifies it `unparseable` (preserved for a
        # human), not `error`. Same reconciliation as the agy path above.
        printf '%s\n' "$result"
    fi
}

# ── Execute reviewers ────────────────────────────────────────────────────────
if $RUN_AGY && $AGY_AVAILABLE; then
    echo "Running agy (correctness + spec adherence)..."
    # #1718: created BEFORE the call (not inside run_agy_review, which runs in
    # a command-substitution subshell — a variable it set would not survive
    # back into this scope, but a file it writes to a path decided out here
    # does). Read below in the token-usage-report section.
    AGY_USAGE_METADATA_FILE=$(vendor_invoke_tmpfile)
    AGY_OUT=$(run_agy_review "correctness+spec" "" "$AGY_USAGE_METADATA_FILE")
    {
        echo "## agy — Correctness + Spec Adherence"
        echo '```json'
        echo "$AGY_OUT"
        echo '```'
        echo ""
    } >> "$OUTFILE"
    create_finding_issues "agy" "$AGY_OUT"
    log_context_advisory "agy" "$AGY_OUT"
    echo "  done"

elif $RUN_AGY && ! $AGY_AVAILABLE && $RUN_CODEX && $CODEX_AVAILABLE; then
    # Fallback: codex handles correctness lens since agy is unavailable
    echo "Running codex (FALLBACK correctness — agy unavailable)..."
    FALLBACK_OUT=$(run_codex_review \
        "agy is unavailable. Cover BOTH correctness + spec adherence AND adversarial security.")
    {
        echo "## codex — Correctness + Security (fallback: agy unavailable)"
        echo '```json'
        echo "$FALLBACK_OUT"
        echo '```'
        echo ""
    } >> "$OUTFILE"
    create_finding_issues "codex-fallback" "$FALLBACK_OUT"
    log_context_advisory "codex-fallback" "$FALLBACK_OUT"
    echo "  done (fallback)"
else
    [[ ! $AGY_AVAILABLE ]] && echo "  SKIP agy: not available"
    echo "## agy — SKIPPED" >> "$OUTFILE"
fi

if $RUN_CODEX && $CODEX_AVAILABLE && ! ( $RUN_AGY && ! $AGY_AVAILABLE ); then
    # Run codex security probe (not already run as fallback above)
    echo "Running codex (adversarial security probe — reserve)..."
    CODEX_OUT=$(run_codex_review "Adversarial security probe only.")
    {
        echo "## codex — Adversarial Security Probe (reserve)"
        echo '```json'
        echo "$CODEX_OUT"
        echo '```'
        echo ""
    } >> "$OUTFILE"
    create_finding_issues "codex" "$CODEX_OUT"
    log_context_advisory "codex" "$CODEX_OUT"
    echo "  done"
elif $RUN_CODEX && ! $CODEX_AVAILABLE; then
    echo "  SKIP codex: not available"
    echo "## codex — SKIPPED" >> "$OUTFILE"
fi

echo ""

# ── Finalize machine-readable verdict header ─────────────────────────────────
# Step 1 (SPEC-331): second_review_logic.py rewrites verdict, highest_severity,
# and unresolved_findings from the prose/JSON classifier. The module reads
# $OUTFILE and rewrites it in place.
python3 "$(dirname "$0")/oversight/second_review_logic.py" aggregate --file "$OUTFILE"

# Step 2 (SPEC-78 C1): validation_logic.py process rewrites new_blocking_count
# (and re-keys verdict) against the step-scoped convergence ledger. This is the
# only place that reads the ledger — imported from validation_logic.py, never
# reimplemented here (C1). A missing ledger is treated as empty (zero seen
# fingerprints), so first-run behavior is unchanged.
#
# --strict-empty (#1737): every real invocation of this script writes at least
# one "## agy"/"## codex" section (populated, or "SKIPPED") — there is no
# legitimate case where this script's own $OUTFILE has reviewer sections that
# validation_logic.py's independent extraction should find nothing in.
# Without this flag, zero extractable blocks default to `approve` regardless
# of WHY nothing was extracted — including a reviewer section whose body
# failed to parse into anything findings/attacks/verdict-shaped. That is "we
# could not read what the reviewer said", which must never present as a clean
# pass. With the flag it defaults to `error` instead, which the fail-closed
# guard below already acts on. This does not change the all-SKIPPED case
# (score below both reviewer thresholds): `second_review_logic.py aggregate`
# already writes `error` there (empty reviewer list, binding 4), which
# outranks and is preserved over whatever this step recomputes, strict or
# not — see the ratchet below.
#
# This was the LAST production caller of validation_logic.py process not
# passing --strict-empty: scripts/framework/validate_agents.sh,
# validate_scripts.sh (since #669), and validate_self.sh (since #1362) all
# already pass it. With this diff, every caller in this repo does — the unset
# (`approve`-on-empty-parse) default in validation_logic.py binding 7 has zero
# remaining production callers relying on it.
python3 "$(dirname "$0")/oversight/validation_logic.py" process \
    --file "$OUTFILE" --ledger "$LEDGER_FILE" --strict-empty

echo "Second review complete: $OUTFILE"
echo "Oversight-evaluator reads this before determining PROCEED/CONDITIONAL/ESCALATE."

# ── Token usage report ───────────────────────────────────────────────────────
TRACKER="$(dirname "$0")/oversight/token_tracker.py"
if [[ -f "$TRACKER" ]]; then
    # Record agy usage — estimate prompt size from source content (prompt is function-local in run_agy_review)
    if $RUN_AGY && [[ -n "${AGY_OUT:-}" ]]; then
        # ADR-1683 D-3: the prompt embeds the digest, not the raw summary — use
        # its length here too, or this estimate silently drifts stale again.
        PROMPT_CHARS=$(( ${#DIFF_CONTENT} + ${#SPEC_CONTEXT} + ${#VALIDATOR_DIGEST} + 800 ))
        OUT_CHARS=${#AGY_OUT}
        # #1718/#1737: actual token counts come from the envelope metadata file
        # salvage_review_json wrote (AGY_USAGE_METADATA_FILE), NOT from parsing
        # AGY_OUT — AGY_OUT is now the salvaged REVIEW (the unwrapped `response`
        # body), which never carried `usage` even in the pre-#1737 envelope
        # (that field lives on the envelope, one level up). Re-parsing AGY_OUT
        # here would silently degrade every agy call to the char-based estimate
        # below, which is derived from what was SENT, not what the model
        # RECEIVED — exactly the distinction #1718's truncation defence needs.
        # A missing/unwritten metadata file (prose fallback, invocation
        # failure) yields {} and 0/0 here, falling through to the same
        # char-estimate behavior those paths always had.
        ACTUAL_IN=$(python3 -c \
            "import json,sys
try:
    with open(sys.argv[1], encoding='utf-8') as fh:
        d = json.load(fh)
except Exception:
    d = {}
usage = d.get('usage') or {}
print(usage.get('input_tokens', usage.get('prompt_tokens', 0)))" \
            "${AGY_USAGE_METADATA_FILE:-/dev/null}" 2>/dev/null || echo "0")
        ACTUAL_OUT=$(python3 -c \
            "import json,sys
try:
    with open(sys.argv[1], encoding='utf-8') as fh:
        d = json.load(fh)
except Exception:
    d = {}
usage = d.get('usage') or {}
print(usage.get('output_tokens', usage.get('completion_tokens', 0)))" \
            "${AGY_USAGE_METADATA_FILE:-/dev/null}" 2>/dev/null || echo "0")
        python3 "$TRACKER" record --vendor agy --stage second-review \
            --step "${STEP:-?}" --prompt-chars "$PROMPT_CHARS" --output-chars "$OUT_CHARS" \
            --actual-prompt-tokens "$ACTUAL_IN" --actual-output-tokens "$ACTUAL_OUT" 2>/dev/null || true
    fi

    # Record codex usage — tag fallback mode separately for telemetry fidelity
    # Fallback (agy unavailable) uses stage "second-review-fallback" so reports
    # distinguish a targeted security probe from a combined correctness+security pass.
    if [[ -n "${FALLBACK_OUT:-}" ]]; then
        _CODEX_ACTUAL="$FALLBACK_OUT"
        _CODEX_STAGE="second-review-fallback"
    elif [[ -n "${CODEX_OUT:-}" ]]; then
        _CODEX_ACTUAL="$CODEX_OUT"
        _CODEX_STAGE="second-review"
    else
        _CODEX_ACTUAL=""
        _CODEX_STAGE="second-review"
    fi
    if $RUN_CODEX && [[ -n "$_CODEX_ACTUAL" ]]; then
        CODEX_PROMPT_CHARS=$(( ${#DIFF_CONTENT} + 600 ))
        CODEX_OUT_CHARS=${#_CODEX_ACTUAL}
        python3 "$TRACKER" record --vendor codex --stage "$_CODEX_STAGE" \
            --step "${STEP:-?}" --prompt-chars "$CODEX_PROMPT_CHARS" --output-chars "$CODEX_OUT_CHARS" \
            2>/dev/null || true
    fi

    echo ""
    python3 "$TRACKER" report 2>/dev/null || true
fi

# ── Fail closed on a runtime reviewer error ──────────────────────────────────
# A fired-and-required reviewer that errored at runtime makes the aggregate
# verdict `error`. Exit non-zero so the pipeline does not proceed on a review
# that never produced an independent judgment — symmetric with the
# vendor-unavailable-at-pre-check guard. The evaluator independently treats a
# MEDIUM+ `verdict: error` file as COMPLIANCE FAIL, but failing here too means a
# transient agy/codex crash blocks the pipeline at the source rather than
# relying solely on the downstream reader.
FINAL_VERDICT=$(grep -m1 '^verdict:' "$OUTFILE" | awk '{print $2}')
if [[ "$FINAL_VERDICT" == "error" ]]; then
    echo "run_second_review: FAIL-CLOSED — a required reviewer errored at runtime (verdict=error)." >&2
    echo "  The mandatory cross-vendor review did not produce an independent judgment. Re-run." >&2
    exit 1
fi
# ── Fail closed on a blocking review verdict (#986) ──────────────────────────
# `validation_logic.py process` sets verdict=request_changes iff new_blocking_count
# > 0 — i.e. the cross-vendor review surfaced blocking findings NOT already
# dispositioned in this step's convergence ledger (dedup-silenced findings never
# reach this verdict). That module deliberately exits 0 for EVERY verdict ("the
# shell decides pass/fail"), so this guard is the sole place the pre-PR chain
# learns of a blocking second-review verdict. Before #986 the script fell through
# to exit 0 here, so run_review_chain.sh gated purely on that exit code, printed
# "second review passed", and proceeded to the panel — a blocking cross-vendor
# verdict survived only in $OUTFILE, which nothing downstream reads. Exit
# non-zero (a code distinct from the reviewer-error exit 1) so the chain halts
# and the operator/evaluator dispositions the findings before a PR is opened.
if [[ "$FINAL_VERDICT" == "request_changes" ]]; then
    NEW_BLOCKING=$(grep -m1 '^new_blocking_count:' "$OUTFILE" | awk '{print $2}')
    echo "run_second_review: FAIL-CLOSED — verdict=request_changes (${NEW_BLOCKING:-?} new blocking finding(s))." >&2
    echo "  The cross-vendor second review surfaced blocking findings not yet dispositioned in the ledger." >&2
    echo "  Read the review, resolve or disposition each finding, then re-run:" >&2
    echo "    $OUTFILE" >&2
    exit 2
fi
if [[ "$FINAL_VERDICT" == "unparseable" ]]; then
    # The reviewer produced a real review we could not auto-structure (agy returned
    # a markdown report, not JSON — HOS#113). This is NOT a crash: the content is
    # in $OUTFILE. Do not silently fail-closed-as-error, and do not silently pass —
    # surface it for a human to read and disposition.
    echo "run_second_review: ⚠ UNPARSEABLE — a reviewer returned prose, not structured JSON." >&2
    echo "  The independent review DID run and its content is preserved in:" >&2
    echo "    $OUTFILE" >&2
    echo "  A human must read it and decide. (This is distinct from verdict=error/crash.)" >&2
    # Exit 0: the review exists and is recorded. The oversight-evaluator routes an
    # 'unparseable' second-review to human review (CONDITIONAL/ESCALATE), not a
    # silent PASS and not a COMPLIANCE FAIL.
fi
