#!/usr/bin/env bash
# validate_scripts.sh — review the framework's SCRIPTS (not just its agents/docs).
#
# The framework's thesis is "review AI-generated code"; its own scripts are
# executable behavior every bit as dangerous as an agent definition (a fail-open
# gate, a predictable mktemp, a non-portable bash idiom). validate_self.sh /
# validate_agents.sh cover .claude/agents + docs + contract; this covers
# bootstrap/, scripts/**/*.sh, scripts/oversight/**/*.py. (#89)
#
# Lens (deliberately DIFFERENT from the governance lens):
#   - Bash correctness: set -euo pipefail interactions, quoting, empty-array under
#     set -u, eval over user paths, swallowed exit codes.
#   - Portability: macOS bash 3.2 vs Linux; BSD vs GNU sed/mktemp/tar/shasum;
#     mapfile / ${var,,} bans.
#   - Fetch-execute security: remote tarball extraction, temp predictability, integrity.
#   - Fail-open / gate integrity: phases that no-op counting as pass; a gate that
#     swallows a non-zero exit.
#   - Python validators/gates: the same, plus the validator output-schema contract.
#
# Runs Opus (self) and optionally agy/codex (3P), with the dedup ledger so it
# converges (zero-NEW), the known-issues injection so it skips tracked findings,
# and --changed-only --base <ref> so a release reviews only its diff.
#
# Usage:
#   ./scripts/framework/validate_scripts.sh                 # all scripts, Opus + 3P
#   ./scripts/framework/validate_scripts.sh --changed-only --base v0.1.1
#   ./scripts/framework/validate_scripts.sh --skip-codex | --skip-agy | --skip-3p
#   ./scripts/framework/validate_scripts.sh --record "a.sh,b.sh" <class> <fixed|filed:#N|noise|residual>
#   ./scripts/framework/validate_scripts.sh --reset
#
# Exit: 0 converged (zero NEW blocking) | 3 ESCALATE (pass cap, human decides) | 2 tooling

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
# Resolve validation_logic.py from the repo root so the delegation works
# regardless of the caller's cwd (SPEC-334); ledger paths stay cwd-relative.
VALIDATION_LOGIC="$ROOT/scripts/oversight/validation_logic.py"
OUT_DIR=".claudetmp/framework"
LEDGER="$OUT_DIR/scripts-review-ledger.jsonl"
PASS_COUNT_FILE="$OUT_DIR/scripts-review-pass-count"
MODEL="claude-opus-4-8"
MAX_PASSES="${SCRIPTS_REVIEW_MAX_PASSES:-3}"
AI_REVIEW_TIMEOUT="${AI_REVIEW_TIMEOUT:-300}"

CHANGED_ONLY=false
BASE_REF="HEAD~1"
SKIP_AGY=false
SKIP_CODEX=false

# ── --record / --reset (shared ledger contract with the other validators) ─────
if [[ "${1:-}" == "--record" ]]; then
    mkdir -p "$OUT_DIR"
    _files="${2:?--record needs FILES}"; _cls="${3:?--record needs CLASS}"; _disp="${4:?--record needs DISPOSITION}"
    # Ledger write delegated to validation_logic.py (SPEC-334 binding 4).
    python3 "$VALIDATION_LOGIC" record \
        --ledger "$LEDGER" --files "$_files" --class "$_cls" --disposition "$_disp" >/dev/null
    echo "Recorded to scripts-review ledger: [$_files] $_cls → $_disp"
    exit 0
fi
if [[ "${1:-}" == "--reset" ]]; then
    rm -f "$LEDGER" "$PASS_COUNT_FILE"; echo "scripts-review ledger + pass counter reset."; exit 0
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --changed-only) CHANGED_ONLY=true; shift ;;
        --base)         BASE_REF="$2"; shift 2 ;;
        --skip-agy)     SKIP_AGY=true; shift ;;
        --skip-codex)   SKIP_CODEX=true; shift ;;
        --skip-3p)      SKIP_AGY=true; SKIP_CODEX=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done

command -v claude >/dev/null 2>&1 || { echo "ERROR: claude CLI required for the Opus script self-review (--skip not supported; this is the deterministic lane)" >&2; exit 2; }

# ── Portable hard timeout (agy/codex can hang) — same pattern as validate_agents ──
_TIMEOUT_BIN=""
if command -v timeout &>/dev/null; then _TIMEOUT_BIN="timeout"
elif command -v gtimeout &>/dev/null; then _TIMEOUT_BIN="gtimeout"; fi
run_capped() {
    local secs="$1" out="$2"; shift 2
    if [[ -n "$_TIMEOUT_BIN" ]]; then "$_TIMEOUT_BIN" "$secs" "$@" > "$out" 2>/dev/null; return $?; fi
    "$@" > "$out" 2>/dev/null &
    local pid=$! waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if (( waited >= secs )); then kill -TERM "$pid" 2>/dev/null; sleep 2; kill -KILL "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 124; fi
        sleep 3; waited=$(( waited + 3 ))
    done
    wait "$pid"; return $?
}

# ── Collect scripts (changed-only via --base, or all) ─────────────────────────
collect_scripts() {
    local files=()
    if $CHANGED_ONLY; then
        while IFS= read -r f; do
            [[ -f "$f" ]] || continue
            case "$f" in bootstrap/*.sh|scripts/*.sh|scripts/*/*.sh|scripts/oversight/*.py|scripts/oversight/*/*.py) files+=("$f") ;; esac
        done < <(git diff --name-only "$BASE_REF" 2>/dev/null || true)
    fi
    if [[ ${#files[@]} -eq 0 ]]; then
        CHANGED_ONLY=false
        while IFS= read -r f; do files+=("$f"); done < <(
            find bootstrap scripts -type f \( -name '*.sh' -o -name '*.py' \) \
                -not -path '*/.venv/*' -not -path '*/__pycache__/*' 2>/dev/null | sort)
    fi
    [[ ${#files[@]} -gt 0 ]] && printf '%s\n' "${files[@]}"
}

FILES=()
while IFS= read -r f; do [[ -n "$f" ]] && FILES+=("$f"); done < <(collect_scripts)
if [[ ${#FILES[@]} -eq 0 ]]; then echo "validate_scripts: no scripts to review"; exit 0; fi

mkdir -p "$OUT_DIR"
TS=$(date +%Y%m%dT%H%M%S 2>/dev/null || echo now)
OUTFILE="$OUT_DIR/scripts-validation-${TS}.md"
PASS_NUM=$(( $(cat "$PASS_COUNT_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$PASS_NUM" > "$PASS_COUNT_FILE"

# Known-issues context: skip already-tracked findings (#134 pattern).
KNOWN_ISSUES=""
if [[ "${HOS_FEED_KNOWN_ISSUES:-1}" == "1" ]] && command -v gh >/dev/null 2>&1; then
    KNOWN_ISSUES=$(gh issue list --state open --limit 100 --json number,title -q '.[] | "- #\(.number): \(.title)"' 2>/dev/null || true)
fi
[[ -z "$KNOWN_ISSUES" ]] && KNOWN_ISSUES="(none available)"

# Build the review package.
PKG=""
for f in "${FILES[@]}"; do PKG+=$'\n\n===== '"$f"$' =====\n'"$(cat "$f")"; done

LENS="You are reviewing the SCRIPTS of an AI agent pipeline framework (the Human Oversight System) — installers, gates, validators, review/release orchestration. These scripts ARE the framework's executable behavior; a bug here is as dangerous as a bug in an agent definition. Find real, high-confidence defects. Lens:
1. BASH CORRECTNESS — set -euo pipefail interactions, quoting, empty-array expansion under set -u (bash 3.2), eval over user/remote paths, swallowed exit codes (cmd || true that hides a real failure).
2. PORTABILITY — macOS bash 3.2 vs Linux; BSD vs GNU sed/mktemp/tar/shasum/stat; banned bash-4 idioms (mapfile, \${var,,}); mktemp suffix predictability.
3. FETCH-EXECUTE SECURITY — remote tarball extraction, predictable temp paths (stale/planted-file extraction), missing integrity checks, sudo scope.
4. FAIL-OPEN / GATE INTEGRITY — a phase that no-ops but counts as PASS; a gate that swallows a non-zero exit; a 'validated release' that isn't actually validated.
5. PYTHON VALIDATORS/GATES — the same, plus the validator output-schema contract (does it emit the score/weight/error fields the aggregator expects?).
Be specific: name the exact file and quote the offending line. Prefer a few real blocking findings over many speculative ones. If clean, say so."

KNOWN="=== KNOWN, ALREADY-TRACKED ISSUES — do NOT re-report these ===
The findings below are already filed and tracked. Only report findings NOT covered by one of these.
${KNOWN_ISSUES}
"

JSON_SCHEMA='Return JSON only — no prose outside the JSON block:
{"reviewer":"REVIEWER","lens":"scripts","findings":[{"severity":"blocking|warning","category":"bash|portability|fetch-exec|fail-open|schema","files":["f.sh"],"description":"what is wrong and where (quote it)","fix":"specific change"}],"verdict":"approve|request_changes","summary":"honest one paragraph"}'

{
  printf "# Framework Scripts Validation\nTimestamp: %s\nPass: %s/%s  Scope: %s\nverdict: pending\nhighest_severity: none\nblocking_count: 0\nnew_blocking_count: 0\n\n" \
    "$TS" "$PASS_NUM" "$MAX_PASSES" "$([[ $CHANGED_ONLY == true ]] && echo "changed since $BASE_REF" || echo "all scripts")"
} > "$OUTFILE"

run_reviewer() {  # name, cli-kind
    local name="$1" kind="$2" prompt out rc=0 body reason
    prompt="${LENS}

${KNOWN}
=== SCRIPTS ===
${PKG}

${JSON_SCHEMA/REVIEWER/$name}"
    out=$(mktemp /tmp/vscripts_${name}_XXXXXX)
    case "$kind" in
        opus)  printf '%s' "$prompt" | run_capped "$AI_REVIEW_TIMEOUT" "$out" claude -p --model "$MODEL" || rc=$? ;;
        agy)   run_capped "$AI_REVIEW_TIMEOUT" "$out" agy --sandbox -p "$prompt" || rc=$? ;;
        codex) printf '%s' "$prompt" | run_capped "$AI_REVIEW_TIMEOUT" "$out" codex exec || rc=$? ;;
    esac
    body=$(cat "$out" 2>/dev/null)
    rm -f "$out"

    # Fail-closed on a reviewer that hung, errored, or produced empty/whitespace
    # output (#669). run_capped's rc was previously discarded, so a timeout (124)
    # or nonzero exit left an empty $out that parsed to zero findings → approve →
    # exit 0 (silent fail-open). Now: the REQUIRED Opus lane (the deterministic
    # gate) synthesizes a BLOCKING finding so a hung/erroring reviewer cannot
    # converge to PASS — even if an optional 3P lane is clean. agy/codex are
    # optional 3P: a failure there is recorded as a non-blocking error (matching
    # validate_agents.sh's hang-guard) and the review continues.
    if [[ $rc -ne 0 || -z "${body//[[:space:]]/}" ]]; then
        reason=$([[ $rc -eq 124 ]] && echo "timed out after ${AI_REVIEW_TIMEOUT}s" || echo "failed (rc=$rc) or produced empty output")
        if [[ "$kind" == "opus" ]]; then
            echo "  ERROR: required ${name} reviewer ${reason} — recording as BLOCKING (fail-closed, #669)" >&2
            body='{"reviewer":"'"$name"'","lens":"scripts","findings":[{"severity":"blocking","category":"fail-open","files":["<reviewer:'"$name"'>"],"description":"Required Opus scripts reviewer '"$reason"'; treated as a blocking finding so a hung/erroring deterministic reviewer cannot silently converge to PASS (#669).","fix":"Re-run validate_scripts.sh; if the failure recurs, investigate the reviewer hang/timeout before trusting the gate."}],"verdict":"request_changes","summary":"Required reviewer '"$reason"' — fail-closed (#669)."}'
        else
            echo "  WARN: ${name} reviewer ${reason} — recorded as error, continuing" >&2
            body='{"reviewer":"'"$name"'","lens":"scripts","findings":[],"verdict":"error","summary":"'"$name"' '"$reason"' (hang guard)."}'
        fi
    fi
    { echo "## ${name} — scripts lens"; echo '```json'; echo "$body"; echo '```'; echo ""; } >> "$OUTFILE"
}

echo "Collecting ${#FILES[@]} script(s) for review (pass ${PASS_NUM}/${MAX_PASSES})..."
echo "Running Opus scripts self-review..."
run_reviewer "opus-self" opus
if ! $SKIP_AGY && command -v agy >/dev/null 2>&1;   then echo "Running agy scripts review...";   run_reviewer "agy" agy;   fi
if ! $SKIP_CODEX && command -v codex >/dev/null 2>&1; then echo "Running codex scripts review..."; run_reviewer "codex" codex; fi

# ── Aggregate verdict (ledger-aware: gate on NEW un-ledgered blocking) ─────────
# Dedup fingerprinting + verdict aggregation delegated to validation_logic.py
# (SPEC-334). --strict-empty (#669): an empty/malformed parse → verdict=error, NOT
# approve. The old "no --strict-empty / empty→approve" scripts compat was a
# fail-open bug — a reviewer that hung or errored produced zero findings and exit 0.
# The canonical 7-rank severity ordering applies — critical/high are no longer
# collapsed to blocking, so highest_severity reports the true rank (AC-1). The
# pass-cap exit-code decision stays in this shell (binding 3) — the module never
# emits verdict exit codes.
python3 "$VALIDATION_LOGIC" process \
    --file "$OUTFILE" --ledger "$LEDGER" --strict-empty

VERDICT=$(grep '^verdict:' "$OUTFILE" | head -1 | awk '{print $2}')
NEW=$(grep '^new_blocking_count:' "$OUTFILE" | head -1 | awk '{print $2}')
# Converge ONLY on an explicit approve (zero NEW blocking AND the reviewers
# actually produced parseable output). Reading new_blocking_count alone was the
# fail-open: an empty parse leaves it 0 even though verdict=error (#669). Any
# non-approve verdict — request_changes (NEW blocking) or error (empty/malformed) —
# is non-converged and fails closed.
if   [[ "$VERDICT" == "approve" ]];       then rc=0   # converged — zero NEW blocking, real output
elif [[ "$PASS_NUM" -ge "$MAX_PASSES" ]]; then rc=3   # pass cap hit, still non-converged → escalate
else                                           rc=1   # non-converged, under cap → fail/retry
fi

echo ""
echo "Output: $OUTFILE"
if [[ $rc -eq 0 ]]; then
    echo "  PASS — converged (zero NEW blocking script findings)"
elif [[ $rc -eq 3 ]]; then
    echo "  ESCALATE — pass cap ($MAX_PASSES) hit, still non-converged (verdict=${VERDICT:-?}). A human decides (fix / file / accept)."
    echo "  Triage, then: $0 --record \"file.sh\" <class> <fixed|filed:#N|residual>; re-run."
elif [[ "$VERDICT" == "error" ]]; then
    echo "  SCRIPT-REVIEW FAIL — reviewer output empty/malformed (verdict=error, pass $PASS_NUM/$MAX_PASSES)."
    echo "  A required reviewer likely hung or errored; the gate fails closed (#669). Re-run; investigate if it recurs."
else
    echo "  SCRIPT-REVIEW FAIL — NEW blocking findings (pass $PASS_NUM/$MAX_PASSES). Triage + record, re-run."
fi
exit $rc
