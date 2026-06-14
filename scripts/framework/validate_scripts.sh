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
    _json_files=$(printf '%s' "$_files" | awk -F, '{for(i=1;i<=NF;i++){printf "%s\"%s\"",(i>1?",":""),$i}}')
    _ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date +"%Y-%m-%dT%H:%M:%SZ")
    printf '{"files":[%s],"class":"%s","disposition":"%s","ts":"%s"}\n' "$_json_files" "$_cls" "$_disp" "$_ts" >> "$LEDGER"
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
    local name="$1" kind="$2" prompt out rc=0
    prompt="${LENS}

${KNOWN}
=== SCRIPTS ===
${PKG}

${JSON_SCHEMA/REVIEWER/$name}"
    out=$(mktemp /tmp/vscripts_${name}_XXXXXX)
    case "$kind" in
        opus)  printf '%s' "$prompt" | run_capped "$AI_REVIEW_TIMEOUT" "$out" claude -p --model "$MODEL" || rc=$? ;;
        agy)   run_capped "$AI_REVIEW_TIMEOUT" "$out" agy --sandbox -p "$prompt" || rc=$? ;;
        codex) printf '%s' "$prompt" | run_capped "$AI_REVIEW_TIMEOUT" "$out" codex --quiet || rc=$? ;;
    esac
    { echo "## ${name} — scripts lens"; echo '```json'; cat "$out" 2>/dev/null; echo '```'; echo ""; } >> "$OUTFILE"
    rm -f "$out"
}

echo "Collecting ${#FILES[@]} script(s) for review (pass ${PASS_NUM}/${MAX_PASSES})..."
echo "Running Opus scripts self-review..."
run_reviewer "opus-self" opus
if ! $SKIP_AGY && command -v agy >/dev/null 2>&1;   then echo "Running agy scripts review...";   run_reviewer "agy" agy;   fi
if ! $SKIP_CODEX && command -v codex >/dev/null 2>&1; then echo "Running codex scripts review..."; run_reviewer "codex" codex; fi

# ── Aggregate verdict (ledger-aware: gate on NEW un-ledgered blocking) ─────────
python3 - "$OUTFILE" "$LEDGER" "$MAX_PASSES" "$PASS_NUM" <<'PYEOF'
import json, re, sys
path, ledger_path, maxp, passn = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
content = open(path).read()
sev = ["critical","blocking","high","warning","none"]
def rank(s):
    s = "blocking" if s in ("critical","high") else s
    return sev.index(s) if s in sev else len(sev)
seen=set()
try:
    for line in open(ledger_path):
        e=json.loads(line); seen.add((tuple(sorted(e.get("files",[]))), e.get("class","")))
except Exception: pass
def fp(f): return (tuple(sorted(f.get("files",[]))), f.get("category",""))
blocking=new=0; highest="none"
for blk in re.findall(r'```json\s*(.*?)```', content, re.DOTALL):
    try: data=json.loads(blk[blk.index('{'):])
    except Exception: continue
    for f in data.get("findings",[]):
        s=str(f.get("severity","warning")).lower()
        if s in ("blocking","critical","high"):
            blocking+=1
            if rank(s)<rank(highest): highest=s
            if fp(f) not in seen: new+=1
verdict = "request_changes" if new>0 else "approve"
content=re.sub(r'^verdict: pending$',f'verdict: {verdict}',content,flags=re.M)
content=re.sub(r'^highest_severity: none$',f'highest_severity: {highest}',content,flags=re.M)
content=re.sub(r'^blocking_count: 0$',f'blocking_count: {blocking}',content,flags=re.M)
content=re.sub(r'^new_blocking_count: 0$',f'new_blocking_count: {new}',content,flags=re.M)
open(path,'w').write(content)
print(f"  verdict={verdict} highest_severity={highest} blocking={blocking} new={new}")
sys.exit(0 if new==0 else (3 if passn>=maxp else 1))
PYEOF
rc=$?

echo ""
echo "Output: $OUTFILE"
if [[ $rc -eq 0 ]]; then
    echo "  PASS — converged (zero NEW blocking script findings)"
elif [[ $rc -eq 3 ]]; then
    echo "  ESCALATE — pass cap ($MAX_PASSES) hit, still NEW blocking. A human decides (fix / file / accept)."
    echo "  Triage, then: $0 --record \"file.sh\" <class> <fixed|filed:#N|residual>; re-run."
else
    echo "  SCRIPT-REVIEW FAIL — NEW blocking findings (pass $PASS_NUM/$MAX_PASSES). Triage + record, re-run."
fi
exit $rc
