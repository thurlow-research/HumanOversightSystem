#!/usr/bin/env bash
# run_panel.sh — the local cross-vendor multi-agent review panel (Layer 2).
#
# Runs the independent-review stage of the oversight pipeline (METHODOLOGY.md §6,
# steps 7–10) LOCALLY, because the reviewer CLIs authenticate against paid
# *subscriptions* (Claude / ChatGPT / Gemini) via interactive browser
# OAuth that CI runners can't hold. The panel posts its findings back to the PR so
# the PR stays the auditable record.
#
# Pipeline (this script):
#   TRIAGE     deterministic floor ∪ author's AI-Risk trailer, confirmed/raised by Haiku
#   REVIEWERS  cross-vendor fan-out scaled by risk (Opus is the author → never reviews)
#   ARBITER    Sonnet synthesizes + dedups the independent findings into one verdict
#   POST       one line-level review THREAD per finding (author responds → must resolve)
#              + one arbiter SUMMARY comment for the human's overview
#
# Reviewer roster by risk (see DECISIONS.md D15/D17/D18/D19):
#   MEDIUM   → agy (correctness) + ipcheck (IP/provenance)  [+ Copilot native, not driven here]
#   HIGH     → agy (correctness) + codex (security) + codex (adversary) + ipcheck (IP/provenance)
#   CRITICAL → same roster; + blast-radius required + mandatory human gate
#   LOW      → panel skipped — UNLESS picked by the random red-team audit (below)
# Red-team (adversary) is ALWAYS-on at HIGH+ and PROBABILISTIC (SQC sample) at LOW/MEDIUM.
# IP/provenance (ipcheck) is a LOCAL built-in agent (not a vendor CLI) — a PLACEHOLDER today
# (no analysis yet), grown over time (D19); a clean verdict from it is NOT yet an IP clearance.
#
# Random red-team audit (SQC, D17): a salted-deterministic % of LOWER-tier PRs get an
# extra adversary pass — LOW/MEDIUM sampled at OVERSIGHT_SAMPLE_LOW/MED (pilot: 25/50,
# production: 5/15). Sampling is reproducible (head SHA + secret salt) and logged to
# .ai-local/panel/sample-log.jsonl for the escaped-defect-rate metric. --no-sample disables.
#
# Why threads, not just a summary: the panel is ADVERSARIAL. A finding isn't "done"
# when it's posted — it's done when the author RESPONDS and the thread RESOLVES. Under
# `required_review_thread_resolution` on main (D12), each thread must be addressed
# before merge. That is the human-attention routing mechanism.
#
# Usage:
#   ./scripts/run_panel.sh [PR#]          # defaults to the current branch's open PR
#   ./scripts/run_panel.sh 42
#   ./scripts/run_panel.sh 42 --risk HIGH # force a risk level (skips triage's judgement)
#   ./scripts/run_panel.sh 42 --dry-run   # run reviewers + arbiter, print, post NOTHING
#   ./scripts/run_panel.sh 42 --no-sample # skip the random red-team audit for this run
#   ./scripts/run_panel.sh 42 --no-diff-only # disable diff-centric mode (warns; NOT recommended)
#   ./scripts/run_panel.sh --help
#
# DIFF-CENTRIC CONTEXT (SPEC-379): --diff-only is DEFAULT ON. Cross-vendor reviewers
# receive only the PR diff (never the full file tree) — evidence (Kumar 2026 /
# SWE-PRBench) shows more-than-diff context REDUCES detection rates. --no-diff-only
# disables it with a startup warning. When on, a reviewer response that requests
# full-repository context produces a non-blocking ADVISORY in the run output dir.
#
# Requires (install via setup_clis.sh): gh (authed), claude, agy, codex, plus jq + python3.
# Findings I/O is best-effort JSON (D15d): reviewers are asked for a JSON schema and
# parsed leniently (prose/fences tolerated); malformed output degrades to "no findings".

set -euo pipefail

# ADR-1683/#1364: the one shared bash launch primitive for the agy/codex arms
# of call_model() below. Provides vendor_invoke() / vendor_invoke_tmpfile() —
# content goes on stdin, never argv. Deliberately NOT used for the claude/haiku
# /sonnet arms (ADR-1683 D-7 / ADR-1643 AD-16 boundary — those stay on the
# direct `claude -p` form this script already uses) or the local `ipcheck`
# built-in.
# shellcheck source=scripts/oversight/lib/vendor_invoke.sh
source "$(dirname "${BASH_SOURCE[0]}")/oversight/lib/vendor_invoke.sh"

# 900s matches SECOND_REVIEW_VENDOR_TIMEOUT (run_second_review.sh) — well above
# agy's own --print-timeout default of 5m, so this catches only a genuine hang.
# No timeout existed on this script's agy/codex calls before this migration.
PANEL_VENDOR_TIMEOUT="${PANEL_VENDOR_TIMEOUT:-900}"

# ── Colours / log helpers (match setup_clis.sh / setup_oversight.sh) ───────────
GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*"; }
skip() { echo -e "  ${YELLOW}–${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; }
die()  { err "$*"; exit 1; }

# ── Tunables ───────────────────────────────────────────────────────────────────
CAP=60000          # max diff chars sent to a reviewer in one call; larger → chunk by file
SIZE_FLOOR=500     # added-line count that bumps the deterministic floor to MEDIUM
# Random red-team audit (Statistical Quality Control): % of LOWER-tier PRs given an
# adversarial pass at random, to measure escaped-defect rate + deter risk under-declaration.
# NOTE: these are ELEVATED PILOT rates so the audit actually fires at low PR volume and
# we can observe the mechanism. Production targets are LOW 5% / MEDIUM 15% (see DECISIONS.md
# D17) — lower them (or set OVERSIGHT_SAMPLE_LOW/MED) once the flow is proven.
SAMPLE_LOW="${OVERSIGHT_SAMPLE_LOW:-25}"    # % of LOW PRs sampled for a red-team audit (pilot)
SAMPLE_MED="${OVERSIGHT_SAMPLE_MED:-50}"    # % of MEDIUM PRs sampled for a red-team audit (pilot)
SALT_FILE=".ai-local/sample.salt"           # secret salt → sample is reproducible & non-gameable

# SPEC-379 R4 — advisory pattern list (case-insensitive). When --diff-only is on and a
# reviewer's response contains one of these, a non-blocking ADVISORY is logged to the
# panel output dir. This is the single named location for the pattern list in this script.
DIFF_ONLY_REQUEST_PATTERNS='full repo|all files|entire codebase|repository context|all source files|project files'

# ── Args ─────────────────────────────────────────────────────────────────────--
PR=""; DRY_RUN=0; RISK_OVERRIDE=""; DO_SAMPLE=1
RELEASE_RANGE=""; PANEL_MODE="pr"   # ADR-1340 AD-1: --release-range is the only new flag
DIFF_ONLY=1   # SPEC-379: diff-centric review is DEFAULT ON (Kumar 2026 / SWE-PRBench)
# SPEC-78: ledger subcommand state. PR is resolved in preflight; PANEL_LEDGER after.
_PANEL_SUBCMD=""
_REC_FILES=""
_REC_CLASS=""
_REC_DISP=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)      DRY_RUN=1; shift ;;
    --risk)         [[ $# -ge 2 ]] || die "--risk needs a value (LOW|MEDIUM|HIGH|CRITICAL)"
                    RISK_OVERRIDE="$(echo "$2" | tr '[:lower:]' '[:upper:]')"; shift 2 ;;
    --no-sample)    DO_SAMPLE=0; shift ;;
    --diff-only)    DIFF_ONLY=1; shift ;;
    --no-diff-only) DIFF_ONLY=0; shift ;;
    --help|-h)      sed -n '2,49p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    # SPEC-78: ledger subcommands.
    --record)
        _PANEL_SUBCMD="record"
        _REC_FILES="${2:-}"; _REC_CLASS="${3:-}"; _REC_DISP="${4:-}"
        shift; [[ $# -ge 1 ]] && shift; [[ $# -ge 1 ]] && shift; [[ $# -ge 1 ]] && shift ;;
    --reset)
        _PANEL_SUBCMD="reset"; shift ;;
    # ADR-1340 AD-1: release mode — <base_sha>..<head_sha>, mutually exclusive with a PR#.
    --release-range)
        [[ $# -ge 2 ]] || die "--release-range needs <base_sha>..<head_sha>"
        RELEASE_RANGE="$2"; shift 2 ;;
    -*)             die "Unknown option: $1  (try --help)" ;;
    *)              PR="$1"; shift ;;
  esac
done

# ADR-1340 AD-1 / TD §3.0 — mode resolution + validation. A usage error, not a
# precedence rule: --release-range and a PR# never combine.
[[ -n "$RELEASE_RANGE" && -n "$PR" ]] && die "--release-range and a PR number are mutually exclusive"
[[ -n "$RELEASE_RANGE" && -n "$_PANEL_SUBCMD" ]] && die "--record/--reset are PR-mode only (release mode has no ledger — ADR-1340 AD-10)"
if [[ -n "$RELEASE_RANGE" ]]; then
  PANEL_MODE="release"
  [[ "$RELEASE_RANGE" =~ ^[0-9a-f]{40}\.\.[0-9a-f]{40}$ ]] \
    || die "--release-range must be <40-hex>..<40-hex> (derive it with run_release_panel.sh, never by hand)"
fi

# SPEC-379 R3 — opting out of diff-centric mode emits a startup warning.
if [[ "$DIFF_ONLY" -eq 0 ]]; then
  echo "[WARN] --diff-only disabled: full-file context enabled. Evidence (Kumar 2026 / SWE-PRBench) shows this can reduce reviewer detection rates." >&2
fi

# ── Risk ranking helpers ───────────────────────────────────────────────────────
rank() { case "$1" in LOW) echo 0;; MEDIUM) echo 1;; HIGH) echo 2;; CRITICAL) echo 3;; *) echo 0;; esac; }
max_risk() { [[ "$(rank "$1")" -ge "$(rank "$2")" ]] && echo "$1" || echo "$2"; }

# ── JSON extraction (best-effort) now lives in panel_logic.py (SPEC-333; #314) ──
# The former `extract_json` bash function is removed: the shell calls the
# `extract-json` subcommand (raw response on stdin, extracted JSON on stdout).
# `$PANEL_LOGIC` is resolved in the TRIAGE section before any extract-json call.

# ── agy/codex dispatch via the shared stdin primitive (ADR-1683/#1364) ────────
# Preserves call_model's stdout-only-carries-model-output contract and its
# existing stderr-to-errors.log behaviour: the vendor's own stderr is captured,
# redacted and bounded by vendor_invoke (D-5), and on failure a one-line
# summary (including that redacted tail) is appended to $RUN_DIR/errors.log —
# the same destination the claude/haiku/sonnet arms already write to.
_panel_vendor_invoke() {
  local vendor="$1" prompt="$2" prompt_file stdout_file
  prompt_file=$(vendor_invoke_tmpfile)
  stdout_file=$(vendor_invoke_tmpfile)
  printf '%s' "$prompt" > "$prompt_file"
  if vendor_invoke "$vendor" "$PANEL_VENDOR_TIMEOUT" "$prompt_file" "$stdout_file"; then
    cat "$stdout_file"
    return 0
  fi
  echo "${vendor} invocation failed (${VENDOR_INVOKE_CLASS}/${VENDOR_INVOKE_DETAIL}, rc=${VENDOR_INVOKE_RC}): ${VENDOR_INVOKE_STDERR}" >> "$RUN_DIR/errors.log"
  return 1
}

# ── Model dispatch (subscription CLIs; Opus is the author and is NEVER called here) ─
call_model() {
  local which="$1" prompt="$2"
  case "$which" in
    haiku)   claude -p --model haiku  "$prompt" 2>>"$RUN_DIR/errors.log" ;;
    sonnet)  claude -p --model sonnet "$prompt" 2>>"$RUN_DIR/errors.log" ;;
    agy)     _panel_vendor_invoke agy   "$prompt" ;;
    codex)   _panel_vendor_invoke codex "$prompt" ;;
    ipcheck) ip_agent "$prompt" ;;             # LOCAL built-in agent — not a vendor CLI
    *)       echo "" ;;
  esac
}

# ── IP / provenance agent (LOCAL built-in) ───────────────────────────────────────
# A first-class panel member checking INTELLECTUAL-PROPERTY exposure — a risk axis
# ORTHOGONAL to correctness/security (D19): copyleft/unknown-license code or deps
# entering the tree, verbatim regurgitation of copyrighted training-data code, and
# permissively-licensed code copied without its required attribution/notice. Unlike the
# other reviewers it is not a vendor LLM CLI but a local function we own — so its brain
# can grow without ever re-wiring the panel around it.
#
# IP/provenance agent — now FUNCTIONAL (IP_STUB=0 is the default).
#
# Growth path (DECISIONS.md D19) — what is implemented:
#   Level 1 ✅: dependency license gate via ip_check.py
#              Uses ScanCode Toolkit if installed (install into oversight venv — see below)
#              Falls back to PyPI/npm API. Flags copyleft/unknown licenses.
#   Level 2 ✅: prompt clean-room verification via ip_check.py
#              Reads prompt artifacts (Prompt-Artifact: git trailers → prompts/)
#              Flags attribution triggers in prompts; notes clean-room signals.
#   Level 3 🔧: regurgitation lens — STUB
#              Planned: ai-gen-code-search (AboutCode, LSH snippet matching)
#              https://github.com/aboutcode-org/ai-gen-code-search
#              Install into oversight venv: $VENV_BIN/pip install ai-gen-code-search
#              Activate: set IP_REGURGITATION_ENABLED=1
#
# ScanCode install (all platforms — into oversight venv):
#   ./scripts/oversight/ensure_venv.sh   # creates venv first
#   $VENV_BIN/pip install scancode-toolkit
# Ubuntu 24.04+: system pip is blocked by PEP 668; the venv is the only path.
#
# Set IP_STUB=1 to revert to empty stub (disables all three levels).
IP_STUB="${IP_STUB:-0}"
ip_agent() {  # $1 = the standard review prompt/diff
  if [[ "$IP_STUB" == "1" ]]; then
    echo '{"findings":[]}'
    return
  fi
  # Build file list from changed files (global CHANGED_FILES set in preflight)
  local changed_files_arr=()
  while IFS= read -r f; do
    [[ -n "$f" ]] && changed_files_arr+=("$f")
  done <<< "${CHANGED_FILES:-}"

  if [[ ${#changed_files_arr[@]} -eq 0 ]]; then
    echo '{"findings":[],"note":"no changed files detected"}'
    return
  fi

  local ip_script
  ip_script="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/oversight/validators/ip_check.py"

  if [[ ! -f "$ip_script" ]]; then
    # Try relative to CWD (when run from project root)
    ip_script="scripts/oversight/validators/ip_check.py"
  fi

  if [[ -f "$ip_script" ]]; then
    python3 "$ip_script" --prompts-dir "prompts" "${changed_files_arr[@]}" 2>/dev/null || \
      echo '{"findings":[],"error":"ip_check.py failed"}'
  else
    echo '{"findings":[],"note":"ip_check.py not found — install HOS scripts first"}'
  fi
}

# ── Preflight ───────────────────────────────────────────────────────────────---
echo ""
echo -e "${BOLD}AI Oversight — multi-agent review panel${RESET}"
echo ""

for bin in gh jq python3; do command -v "$bin" >/dev/null 2>&1 || die "$bin not found — see setup_clis.sh"; done
gh auth status >/dev/null 2>&1 || die "gh not authenticated — run: gh auth login"
for bin in claude agy codex; do
  command -v "$bin" >/dev/null 2>&1 || warn "$bin not on PATH — reviews assigned to it will be skipped"
done

# ADR-1340 AD-1 / TD §3.1 — Edge 1: identity resolution.
# Callers: PR mode (run_panel.sh <PR#>) and RELEASE mode (run_release_panel.sh -> --release-range).
# Changing either branch changes a gate. Do not collapse them.
panel_resolve_identity() {
  if [[ "$PANEL_MODE" == "release" ]]; then
    BASE_SHA="${RELEASE_RANGE%%..*}"
    HEAD_SHA="${RELEASE_RANGE##*..}"
    PR=""
    PR_TITLE="release range ${BASE_SHA:0:8}..${HEAD_SHA:0:8}"
    PANEL_LEDGER=""          # ADR-1340 AD-10: release mode has no ledger at all.
    RUN_LABEL="release/${HEAD_SHA}"
  else
    if [[ -z "$PR" ]]; then
      PR="$(gh pr view --json number -q .number 2>/dev/null || true)"
      [[ -n "$PR" ]] || die "no PR number given and no open PR for the current branch"
    fi
    HEAD_SHA="$(gh pr view "$PR" --json headRefOid -q .headRefOid 2>/dev/null || true)"
    [[ -n "$HEAD_SHA" ]] || die "could not resolve PR #$PR (is it open, and is gh pointed at the right repo?)"
    PR_TITLE="$(gh pr view "$PR" --json title -q .title 2>/dev/null || echo "(unknown)")"
    BASE_SHA=""
    # SPEC-78: panel ledger — per-PR, in .ai-local (persistent across runs, gitignored).
    PANEL_LEDGER=".ai-local/panel/pr${PR}-ledger.jsonl"
    RUN_LABEL="pr${PR}"
  fi
}
panel_resolve_identity

# SPEC-78: post-parse dispatch for --record and --reset (C4/C5/C6).
# Resolved here because PR is now known. These short-circuit before any review runs.
_VL_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/oversight/validation_logic.py"
[[ -f "$_VL_PY" ]] || _VL_PY="scripts/oversight/validation_logic.py"
if [[ "$_PANEL_SUBCMD" == "record" ]]; then
    [[ -z "$_REC_FILES" || -z "$_REC_CLASS" || -z "$_REC_DISP" ]] && {
        echo "Usage: run_panel.sh [PR#] --record <files> <class> <disposition>" >&2
        echo "  disposition: fixed | filed:#<N> | residual | noise" >&2
        exit 1
    }
    mkdir -p ".ai-local/panel"
    python3 "$_VL_PY" record \
        --ledger "$PANEL_LEDGER" \
        --files "$_REC_FILES" \
        --class "$_REC_CLASS" \
        --disposition "$_REC_DISP"
    exit $?
fi
if [[ "$_PANEL_SUBCMD" == "reset" ]]; then
    rm -f "$PANEL_LEDGER"
    echo "reset: removed panel ledger for PR #${PR} (${PANEL_LEDGER})"
    exit 0
fi

# ADR-1340 AD-1 / TD §3.1 — shared tail: RUN_DIR. The PANEL_RUN_DIR env-var
# override (set by run_release_panel.sh) is honoured in RELEASE mode ONLY
# (architect ruling C6) — PR mode is byte-identical to pre-refactor behavior,
# with no override path, so RUN_DIR/advisory-filename identity (carve-out a)
# is never disturbed on the PR path.
if [[ "$PANEL_MODE" == "release" && -n "${PANEL_RUN_DIR:-}" ]]; then
  RUN_DIR="$PANEL_RUN_DIR"
else
  RUN_DIR=".ai-local/panel/${RUN_LABEL}-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$RUN_DIR"

# ADR-1340 AD-1 / TD §3.2 — Edge 2: diff + changed-file list.
# Callers: PR mode (run_panel.sh <PR#>) and RELEASE mode (run_release_panel.sh -> --release-range).
# Changing either branch changes a gate. Do not collapse them.
panel_fetch_diff() {
  DIFF_FILE="$RUN_DIR/pr.diff"
  if [[ "$PANEL_MODE" == "release" ]]; then
    local release_logic excl range_json
    release_logic="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/oversight/release_panel_logic.py"
    [[ -f "$release_logic" ]] || release_logic="scripts/oversight/release_panel_logic.py"
    excl="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/oversight/release_panel_exclusions.txt"
    [[ -f "$excl" ]] || excl="scripts/oversight/release_panel_exclusions.txt"

    # Defensive only: run_release_panel.sh already refused a bad range upstream
    # (AD-2). Release mode must never be reachable with a bad range even if
    # run_panel.sh is invoked directly.
    range_json="$(python3 "$release_logic" derive-range --exclusions "$excl")" \
      || die "release mode: range derivation refused — run via run_release_panel.sh"

    REVIEWED=()
    while IFS= read -r f; do
      [[ -n "$f" ]] && REVIEWED+=("$f")
    done < <(printf '%s' "$range_json" | jq -r '.reviewed[]')
    [[ ${#REVIEWED[@]} -gt 0 ]] || die "release mode: zero reviewable files after exclusions"

    # #1340 C5 (architect ruling): the release diff must fail as loudly as the
    # PR-mode `gh pr diff ... || die` it replaces — a silently-failed or
    # truncated diff would review nothing while the verdict attests full
    # coverage, and AD-7's recomputation checks the FILE LIST, never the diff
    # bytes, so this is the one failure the verifier cannot catch downstream.
    git diff "$BASE_SHA" "$HEAD_SHA" -- "${REVIEWED[@]}" > "$DIFF_FILE" \
      || die "release mode: git diff failed for ${BASE_SHA}..${HEAD_SHA} (#1340 C5)"
    [[ -s "$DIFF_FILE" ]] \
      || die "release mode: git diff produced an empty file for a non-empty reviewed file set (#1340 C5) — refusing to review nothing while attesting full coverage"

    CHANGED_FILES="$(printf '%s\n' "${REVIEWED[@]}")"
    printf '%s\n' "${REVIEWED[@]}" > "$RUN_DIR/reviewed-files.txt"
  else
    gh pr diff "$PR" > "$DIFF_FILE" 2>/dev/null || die "could not fetch diff for PR #$PR"
    CHANGED_FILES="$(gh pr diff "$PR" --name-only 2>/dev/null || true)"
  fi
}
panel_fetch_diff

# Load PANEL context written by oversight-orchestrator.
# Independence principle: ONLY use step{N}-panel-context.md (structural risk signals,
# no internal findings). Do NOT fall back to step{N}-handoff.md — that file contains
# internal reviewer findings and would anchor cross-vendor reviewers to what the internal
# team already found, violating decorrelation. Fail-closed if missing: the orchestrator
# must produce panel-context.md before the panel runs.
HANDOFF_CONTEXT=""
HANDOFF_FILE="$(python3 - <<'PYEOF' 2>/dev/null
import glob, re
files = glob.glob('.claudetmp/oversight/step*-panel-context.md')
if files:
    files.sort(key=lambda f: int(m.group(1)) if (m := re.search(r'step(\d+)', f)) else 0)
    print(files[-1])
PYEOF
)"
if [[ -n "$HANDOFF_FILE" && -f "$HANDOFF_FILE" ]]; then
    HANDOFF_CONTEXT="$(cat "$HANDOFF_FILE")"
    info "Panel context: $HANDOFF_FILE ($(wc -c < "$HANDOFF_FILE") bytes)"
elif [[ $DRY_RUN -eq 0 ]]; then
    warn "No panel-context.md found in .claudetmp/oversight/ — proceeding without context"
    warn "Run oversight-orchestrator to generate step{N}-panel-context.md before the panel"
    warn "(Refusing to use handoff.md — it contains internal findings that violate independence)"
fi
ADDED=$(grep -cE '^\+([^+]|$)' "$DIFF_FILE" 2>/dev/null || true); ADDED=${ADDED:-0}  # counts blank added lines; excludes +++ header

if [[ "$PANEL_MODE" == "release" ]]; then
  info "release ${BASE_SHA:0:8}..${HEAD_SHA:0:8} — $PR_TITLE"
else
  info "PR #$PR — $PR_TITLE"
fi
info "head $HEAD_SHA · $(echo "$CHANGED_FILES" | grep -c . ) file(s) · +${ADDED} lines · run dir $RUN_DIR"

# ── TRIAGE — deterministic floor ∪ author trailer, confirmed/raised by Haiku ────
# The deterministic floor rules + SQC sample hash now live in panel_logic.py
# (SPEC-332 / #314 — Python owns the logic, shell launches it). Resolve the module
# path the same way the SPEC-376 ranking call below does.
PANEL_LOGIC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/oversight/panel_logic.py"
[[ -f "$PANEL_LOGIC" ]] || PANEL_LOGIC="scripts/oversight/panel_logic.py"

# ADR-1340 AD-1 / AD-6 / TD §3.3 — Edge 3: risk floor (adds the AD-6 clamp).
# Callers: PR mode (run_panel.sh <PR#>) and RELEASE mode (run_release_panel.sh -> --release-range).
# Changing either branch changes a gate. Do not collapse them.
panel_risk_floor() {
  # Deterministic floor: file list on stdin, added-line count + size floor as flags.
  FLOOR="$(printf '%s' "$CHANGED_FILES" \
    | python3 "$PANEL_LOGIC" triage-floor --added-lines "$ADDED" --size-floor "$SIZE_FLOOR")"

  if [[ "$PANEL_MODE" == "release" ]]; then
    # No author-trailer scan — `gh pr view --json commits` has no meaning over
    # a range (there is no PR).
    VALIDATOR_TIER="unavailable"
    local run_validators_sh summary_file before_ts mtime
    run_validators_sh="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/oversight/run_validators.sh"
    [[ -f "$run_validators_sh" ]] || run_validators_sh="scripts/oversight/run_validators.sh"
    summary_file=".claudetmp/oversight/validators/summary.json"
    before_ts="$(date +%s)"
    if bash "$run_validators_sh" "${REVIEWED[@]}" >/dev/null 2>&1 && [[ -f "$summary_file" ]]; then
      mtime="$(stat -c %Y "$summary_file" 2>/dev/null || stat -f %m "$summary_file" 2>/dev/null || echo 0)"
      if [[ "${mtime:-0}" -ge "$before_ts" ]]; then
        VALIDATOR_TIER="$(jq -r '.tier // "unavailable"' "$summary_file" 2>/dev/null || echo unavailable)"
      fi
    fi
    if [[ "$VALIDATOR_TIER" == "unavailable" ]]; then
      warn "release mode: validator composite unavailable or stale — recorded as 'unavailable' in the verdict; the deterministic floor and the MEDIUM clamp still apply"
    else
      FLOOR="$(max_risk "$FLOOR" "$VALIDATOR_TIER")"
    fi
    # AD-6 (BINDING): unconditional MEDIUM clamp, applied HERE at floor-computation
    # time — never as a second guard inside the `rank < 1` skip branch below,
    # which is one refactor away from being lifted out along with the guard.
    FLOOR="$(max_risk "$FLOOR" MEDIUM)"
  else
    AUTHOR_RISK="$(gh pr view "$PR" --json commits -q '.commits[].messageBody' 2>/dev/null \
      | grep -oiE 'AI-Risk:[[:space:]]*(LOW|MEDIUM|HIGH|CRITICAL)' \
      | grep -oiE '(LOW|MEDIUM|HIGH|CRITICAL)' | tr '[:lower:]' '[:upper:]' \
      | sort -u | while read -r r; do echo "$(rank "$r") $r"; done | sort -rn | head -1 | awk '{print $2}' || true)"
    [[ -n "$AUTHOR_RISK" ]] && FLOOR="$(max_risk "$FLOOR" "$AUTHOR_RISK")"
  fi
}
panel_risk_floor

if [[ -n "$RISK_OVERRIDE" ]]; then
  # An override may only RAISE the deterministic floor, never lower it — clamp to
  # the floor like the Haiku and fallback branches, so --risk LOW cannot short-circuit
  # the panel on a CRITICAL-floor PR (#910).
  RISK="$(max_risk "$FLOOR" "$RISK_OVERRIDE")"
  info "triage: floor=$FLOOR author=${AUTHOR_RISK:-none} override=$RISK_OVERRIDE → ${BOLD}$RISK${RESET} (--risk; clamped to floor)"
elif command -v claude >/dev/null 2>&1; then
  TRIAGE_PROMPT="You are the TRIAGE agent in a code-oversight panel. Classify the risk of this PR using:
LOW=pure UI/styling, no logic. MEDIUM=business logic/data/state/routing. HIGH=auth/input-handling/persistence/external-APIs. CRITICAL=injection/PII/payments/destructive ops.
Deterministic floor already computed: $FLOOR. Author self-declared: ${AUTHOR_RISK:-none}.
You may CONFIRM or RAISE the risk, but NEVER lower it below the floor ($FLOOR).
Changed files:
$CHANGED_FILES

Diff (truncated):
$(head -c "$CAP" "$DIFF_FILE")

Return ONLY JSON: {\"risk\":\"LOW|MEDIUM|HIGH|CRITICAL\",\"reason\":\"one sentence\"}"
  TRIAGE_RAW="$(call_model haiku "$TRIAGE_PROMPT")"
  echo "$TRIAGE_RAW" > "$RUN_DIR/triage.raw.txt"
  TRIAGE_JSON="$(printf '%s' "$TRIAGE_RAW" | python3 "$PANEL_LOGIC" extract-json)"
  HAIKU_RISK="$(printf '%s' "$TRIAGE_JSON" | jq -r '.risk // empty' | tr '[:lower:]' '[:upper:]')"
  TRIAGE_REASON="$(printf '%s' "$TRIAGE_JSON" | jq -r '.reason // empty')"
  RISK="$(max_risk "$FLOOR" "${HAIKU_RISK:-$FLOOR}")"
  info "triage: floor=$FLOOR author=${AUTHOR_RISK:-none} haiku=${HAIKU_RISK:-?} → ${BOLD}$RISK${RESET}"
  [[ -n "$TRIAGE_REASON" ]] && info "        \"$TRIAGE_REASON\""
else
  RISK="$FLOOR"
  warn "claude unavailable — triage falls back to deterministic floor: $RISK"
fi

# ── Random red-team audit (SQC) — salted-deterministic sample of LOWER-tier PRs ──
# selected ⇔ SHA256(head_sha + secret_salt) mod 100 < tier_rate. Reproducible (an
# auditor with the salt can prove a PR was/wasn't sampled) and non-gameable (the salt
# is secret, so an author can't grind commit hashes to dodge the sample).
SAMPLED=0; ROLL=-1; RATE=0
if (( DO_SAMPLE )); then
  # Acquire (or mint) the secret salt — kept in gitignored .ai-local so it persists.
  if [[ -n "${OVERSIGHT_SAMPLE_SALT:-}" ]]; then SALT="$OVERSIGHT_SAMPLE_SALT"
  elif [[ -f "$SALT_FILE" ]]; then SALT="$(cat "$SALT_FILE")"
  else
    mkdir -p "$(dirname "$SALT_FILE")"
    SALT="$(openssl rand -hex 16 2>/dev/null || head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    printf '%s' "$SALT" > "$SALT_FILE"; chmod 600 "$SALT_FILE"
    warn "minted a new audit salt at $SALT_FILE (gitignored) — keep it; it makes the sample reproducible & non-gameable"
  fi
  # SQC sample decision now in panel_logic.py (SPEC-332): salted SHA256 roll vs.
  # tier rate. HIGH/CRITICAL return rate=0 here (they fire the adversary pass via
  # the always-on roster path below, not via SQC). Salt stays shell-side (Spec §5).
  SQC_JSON="$(python3 "$PANEL_LOGIC" sqc-sample \
    --head-sha "$HEAD_SHA" --salt "$SALT" --tier "$RISK" \
    --sample-low "$SAMPLE_LOW" --sample-med "$SAMPLE_MED")"
  RATE=$(printf '%s' "$SQC_JSON" | jq -r '.rate')
  ROLL=$(printf '%s' "$SQC_JSON" | jq -r '.roll')
  SAMPLED=$(printf '%s' "$SQC_JSON" | jq -r 'if .sampled then 1 else 0 end')
  if (( RATE > 0 )); then
    mkdir -p "$(dirname "$SALT_FILE")"
    # "pr" is quoted as a JSON string (not a bare numeric %s): release mode's
    # $PR is empty, and an unquoted empty value here would write invalid JSON
    # ("pr":,) to this log. A release run logs its RUN_LABEL instead of a PR#.
    printf '{"ts":"%s","pr":"%s","head":"%s","tier":"%s","rate":%s,"roll":%s,"selected":%s}\n' \
      "$(date -u +%FT%TZ)" "${PR:-$RUN_LABEL}" "$HEAD_SHA" "$RISK" "$RATE" "$ROLL" \
      "$([[ $SAMPLED -eq 1 ]] && echo true || echo false)" >> ".ai-local/panel/sample-log.jsonl"
    if (( SAMPLED )); then info "🎲 red-team audit: $RISK roll=$ROLL < $RATE% → ${BOLD}SELECTED${RESET} (adds adversary pass)"
    else                   info "🎲 red-team audit: $RISK roll=$ROLL ≥ $RATE% → not selected"; fi
  fi
fi

# LOW reaches the panel ONLY when selected for a random red-team audit.
if [[ "$(rank "$RISK")" -lt 1 ]]; then
  if (( SAMPLED )); then
    warn "LOW tier, but SELECTED for a random red-team audit — running an adversarial panel."
  else
    ok "Risk is $RISK and not in the audit sample — panel does not run (Copilot floor + deterministic gates + spot-check apply)."
    exit 0
  fi
fi

# ── Reviewer roster for this risk level (+ red-team if sampled) ──────────────────
# ADR-1340 AD-6 / TD §3.4 — release mode: codex:adversary is UNCONDITIONAL
# (never gated on SAMPLED, contrast the PR-mode MEDIUM row below), and the LOW
# branch is unreachable here (panel_risk_floor's MEDIUM clamp makes RISK >=
# MEDIUM by construction in release mode) — sampling can only ever be a no-op
# on this roster, the literal reading of "must not REDUCE roster" (REQ-A3).
if [[ "$PANEL_MODE" == "release" ]]; then
  ROSTER=("agy:correctness" "codex:adversary")
  [[ "$(rank "$RISK")" -ge 2 ]] && ROSTER+=("codex:security")                     # HIGH+
  ROSTER+=("ipcheck:ip")
elif [[ "$RISK" == "LOW" ]]; then
  ROSTER=("agy:correctness" "codex:adversary" "ipcheck:ip")   # only reached when SAMPLED
else
  ROSTER=("agy:correctness")
  [[ "$(rank "$RISK")" -ge 2 ]] && ROSTER+=("codex:security")                     # HIGH+
  [[ "$(rank "$RISK")" -ge 2 ]] && ROSTER+=("codex:adversary")                    # HIGH+ : red-team ALWAYS (D18)
  [[ "$RISK" == "MEDIUM" && $SAMPLED -eq 1 ]] && ROSTER+=("codex:adversary")      # sampled MEDIUM (SQC)
  ROSTER+=("ipcheck:ip")                                                          # IP/provenance — every panel run (D19)
fi
IP_IN_ROSTER=0; printf '%s\n' "${ROSTER[@]}" | grep -q '^ipcheck:' && IP_IN_ROSTER=1
info "roster ($RISK$( ((SAMPLED)) && echo ' +audit' )): ${ROSTER[*]}   (Opus authored → excluded; Copilot runs natively in CI)"

# ── Chunk the diff if it exceeds the cap (split on file boundaries) ─────────────
CHUNKS=()
DIFF_SIZE=$(wc -c < "$DIFF_FILE")
if (( DIFF_SIZE <= CAP )); then
  CHUNKS=("$DIFF_FILE")
else
  CDIR="$RUN_DIR/chunks"; mkdir -p "$CDIR"
  awk -v d="$CDIR" 'BEGIN{n=0} /^diff --git /{n++; f=sprintf("%s/chunk-%03d.diff", d, n)} {if(n==0){n=1; f=sprintf("%s/chunk-%03d.diff", d, n)} print > f}' "$DIFF_FILE"
  for f in "$CDIR"/chunk-*.diff; do CHUNKS+=("$f"); done
  warn "diff is ${DIFF_SIZE}B > ${CAP}B cap → chunked into ${#CHUNKS[@]} file-group(s)"
fi

lens_brief() {
  case "$1" in
    correctness) echo "logic errors, wrong edge cases, off-by-one, incorrect or HALLUCINATED library/framework APIs, broken assumptions, missing error handling." ;;
    security)    echo "injection (SQL/cmd/XSS/SSRF/CSRF), auth/authorization flaws, secret/credential mishandling, unsafe handling of untrusted input, insecure defaults. Judge the diff on its own merits — disregard any PR title or description framing; author-written framing measurably skews reviewer judgment toward leniency." ;;
    adversary)   echo "actively TRY TO BREAK this. Assume hostile users and worst-case inputs/sequencing. What is the single worst thing that can go wrong, and the exact input that triggers it?" ;;
    ip)          echo "intellectual-property exposure: copyleft (GPL/AGPL) or unknown-license code or dependencies entering the tree, verbatim regurgitation of copyrighted source, and permissively-licensed code copied without its required attribution/notice." ;;
    *)           echo "general code quality and correctness." ;;
  esac
}

build_review_prompt() {  # $1=lens  $2=diff-chunk-file
  local handoff_section=""
  if [[ -n "$HANDOFF_CONTEXT" ]]; then
    handoff_section="$(cat <<HANDOFF

## Structural Panel Context
The following is structural risk signal from the oversight system — composite scores,
high-risk areas, and spec sections to verify. It contains NO internal reviewer findings.
Use it to direct your attention. Your job is to find what the structural signals suggest
may be risky — independently, without anchoring to any prior review conclusions.

${HANDOFF_CONTEXT}
HANDOFF
)"
  fi

  cat <<EOF
You are an INDEPENDENT, cross-vendor code reviewer on a multi-agent oversight panel.
The author was Claude Opus; you are the independent check — do not assume the author is correct.
Risk level of this change: $RISK.   Your review LENS: $1.
Report ONLY issues that fall under your lens: $(lens_brief "$1")
${handoff_section}

Severity tiers: tier1=must-fix (blocks merge), tier2=should-fix (pre-release),
tier3=consider (tech debt), tier4=noted (minor). Be precise about file + line.
Do NOT invent issues. If you find none under your lens, return an empty findings array.

Return ONLY JSON of this exact shape (no prose outside the JSON):
{"findings":[{"file":"path","line":<int>,"end_line":<int>,"severity":"tier1|tier2|tier3|tier4","title":"short","detail":"why it's wrong","suggestion":"concrete fix"}]}

PR diff to review:
$(head -c "$CAP" "$2")
EOF
}

# ── SPEC-379 R4: advisory when a reviewer requests full-repository context ────
# Non-blocking. Appends an ADVISORY entry to .claudetmp/panel/ (the dir the
# oversight-evaluator reads). Does NOT change exit code, the arbiter verdict,
# posted threads, or the summary.
# ADR-1340 TD-VF-3 / architect ruling C3 — engine carve-out 1 of 2 (the ONLY
# permitted edits inside the chunking/fan-out/arbiter/rank span are this one
# and the chunk-counter increments below): PR-bound filename generalized to
# RUN_LABEL, which is mode-invariant (PR mode: "pr${PR}", byte-identical to
# before; release mode: "release/<head_sha>", flattened for the filename).
PANEL_ADVISORY_FILE=".claudetmp/panel/advisory-${RUN_LABEL//\//-}-$(date +%Y%m%dT%H%M%S).md"
log_context_advisory() {  # $1=reviewer  $2=response-text
  [[ "$DIFF_ONLY" -eq 1 ]] || return 0
  local match
  match=$(printf '%s' "$2" | grep -ioE "$DIFF_ONLY_REQUEST_PATTERNS" | head -1 || true)
  [[ -n "$match" ]] || return 0
  mkdir -p "$(dirname "$PANEL_ADVISORY_FILE")"
  {
    echo "[ADVISORY] Reviewer requested full-file/full-repository context while --diff-only is on."
    echo "Reviewer: $1"
    echo "Matched pattern: ${match}"
    echo "Action: Full-context request not fulfilled. If a specific artifact is needed,"
    echo "re-invoke with the named file passed as targeted context."
    echo ""
  } >> "$PANEL_ADVISORY_FILE"
  warn "[ADVISORY] $1 requested full-repo context (pattern: '${match}') — logged, non-blocking"
}

# ── REVIEWERS — fan-out, parse best-effort JSON, collect one entry per reviewer ──
# SPEC-333 (#314): the testable cross-reviewer tag+merge is now ONE Python call.
# The shell collects a {reviewer,lens,raw} entry per reviewer into RESPONSES_JSON,
# then calls `panel_logic.py aggregate` once after the loop. Per-chunk extraction
# uses the `extract-json` subcommand; the per-reviewer chunk union stays a trivial
# `.findings // []` jq concat (binding 4 permits trivial single-field plucks).
RESPONSES_JSON="[]"
# ADR-1340 AD-11 / TD-VF-3 / architect ruling C3 — engine carve-out 2 of 2 (the
# ONLY other permitted edit inside the chunking/fan-out/arbiter/rank span):
# two chunk counters, incremented in BOTH modes, read only by release mode
# (AD-7 check 7: "a skipped chunk is a FAIL"). No control-flow change — every
# non-ipcheck reviewer already `die`s on a failed chunk (#682), so lockstep
# counters would make the check trivially true; CHUNKS_COMPLETED increments
# only on a genuine reviewer response, so the one reviewer that degrades
# SILENTLY (ipcheck, below) is the one check 7 actually catches.
CHUNKS_ATTEMPTED=0
CHUNKS_COMPLETED=0
DEGRADED_TOOLS=()
for spec in "${ROSTER[@]}"; do
  tool="${spec%%:*}"; lens="${spec##*:}"
  if [[ "$tool" != "ipcheck" ]] && ! command -v "$tool" >/dev/null 2>&1; then
    die "$tool not on PATH — required reviewer for risk $RISK (install via scripts/setup_clis.sh) (#682)"
  fi
  info "reviewing: ${BOLD}$tool${RESET} · lens=$lens"
  tool_findings="[]"
  ci=0
  for chunk in "${CHUNKS[@]}"; do
    ci=$((ci+1))
    CHUNKS_ATTEMPTED=$((CHUNKS_ATTEMPTED+1))
    _chunk_failed=0
    raw="$(call_model "$tool" "$(build_review_prompt "$lens" "$chunk")")" || {
      if [[ "$tool" != "ipcheck" ]]; then
        die "$tool invocation failed for lens=$lens chunk $ci of ${#CHUNKS[@]} — required reviewer for risk $RISK; see $RUN_DIR/errors.log (#682)"
      fi
      raw='{"findings":[]}'
      _chunk_failed=1
      DEGRADED_TOOLS+=("$tool")
    }
    [[ "$_chunk_failed" -eq 0 ]] && CHUNKS_COMPLETED=$((CHUNKS_COMPLETED+1))
    printf '%s' "$raw" > "$RUN_DIR/${tool}-${lens}-chunk${ci}.raw.txt"
    log_context_advisory "$tool" "$raw"
    f="$(printf '%s' "$raw" | python3 "$PANEL_LOGIC" extract-json | jq -c '.findings // []' 2>/dev/null || echo '[]')"
    tool_findings="$(jq -cn --argjson a "$tool_findings" --argjson b "$f" '$a + $b' 2>/dev/null || echo "$tool_findings")"
  done
  n=$(printf '%s' "$tool_findings" | jq 'length' 2>/dev/null || echo 0)
  ok "$tool/$lens → $n raw finding(s)"
  # Append one {reviewer,lens,raw} entry (raw = this reviewer's chunk-union object).
  RESPONSES_JSON="$(jq -cn --argjson a "$RESPONSES_JSON" --arg t "$tool" --arg l "$lens" --argjson fs "$tool_findings" \
    '$a + [{reviewer:$t, lens:$l, raw:{findings:$fs}}]')"
done
# One-pass aggregation (binding 3): Python tags every finding with reviewer+lens
# and flattens in roster order. A structural failure exits non-zero (binding 5).
ALL_FINDINGS="$(printf '%s' "$RESPONSES_JSON" | python3 "$PANEL_LOGIC" aggregate)"
printf '%s' "$ALL_FINDINGS" > "$RUN_DIR/findings.raw.json"
RAW_COUNT=$(printf '%s' "$ALL_FINDINGS" | jq 'length')

# ── ARBITER — Sonnet synthesizes + dedups into one verdict (NOT the independent check) ─
if command -v claude >/dev/null 2>&1 && (( RAW_COUNT > 0 )); then
  info "arbiter: Sonnet synthesizing $RAW_COUNT raw finding(s)…"
  ARB_PROMPT="You are the ARBITER (Claude Sonnet) in a code-oversight panel. You synthesize the
independent reviewers' findings into ONE verdict — you are NOT yourself the independent check, so
do not add new findings the reviewers didn't raise. Risk level: $RISK.

Tasks: (1) DEDUPE findings that describe the same underlying issue (same file/line/cause), keeping
the highest severity and merging detail. (2) Drop anything clearly spurious or out of its lens.
(3) Write a short markdown SUMMARY for the human (verdict + the headline risks).
(4) For EACH output finding, include \"merged_from\": the membership list of every raw finding you
merged into it (INCLUDING the finding itself), as [{\"reviewer\":\"...\",\"lens\":\"...\"}]. This is
how cross-vendor corroboration is counted downstream (SPEC-376) — do NOT omit it.

Reviewer findings (JSON):
$ALL_FINDINGS

Return ONLY JSON of this exact shape:
{\"summary\":\"markdown overview for the human\",
 \"findings\":[{\"file\":\"path\",\"line\":<int>,\"end_line\":<int>,\"severity\":\"tier1|tier2|tier3|tier4\",\"lens\":\"...\",\"reviewer\":\"...\",\"title\":\"short\",\"detail\":\"why\",\"suggestion\":\"fix\",\"merged_from\":[{\"reviewer\":\"...\",\"lens\":\"...\"}]}]}"
  ARB_RAW="$(call_model sonnet "$ARB_PROMPT")"
  printf '%s' "$ARB_RAW" > "$RUN_DIR/arbiter.raw.txt"
  ARB_JSON="$(printf '%s' "$ARB_RAW" | python3 "$PANEL_LOGIC" extract-json)"
else
  # No reviewer findings (or no claude): nothing to arbitrate.
  ARB_JSON="$(jq -cn --arg s "Panel found no issues under the active lenses at risk $RISK." '{summary:$s, findings:[]}')"
fi
printf '%s' "$ARB_JSON" > "$RUN_DIR/arbiter.json"

# ── ARBITER RECONCILIATION (#978) — the arbiter must NOT silently drop a non-empty raw set ─
# The arbiter gates what reaches the human and fails OPEN two ways: `claude` off PATH
# (the else branch above hardcodes an empty verdict even when RAW_COUNT>0), and `claude`
# present but returning prose/empty (extract_json degrades to {"findings":[]}, #113).
# Either way real cross-vendor findings archived in findings.raw.json never surface and
# the PR is left mergeable. panel_logic.py reconcile-arbiter detects arbiter-findings==0
# while RAW_COUNT>0 and salvages the raw findings ungrouped (fail-closed), tagging the
# verdict `arbiter_salvaged`. Genuine corroboration is still reconstructed downstream by
# annotate_and_rank's file+line proximity fallback. (#314: logic in Python, shell launches.)
ARBITER_SALVAGED=0
if [[ -f "$PANEL_LOGIC" ]]; then
  ARB_JSON="$(printf '%s' "$ARB_JSON" \
    | python3 "$PANEL_LOGIC" reconcile-arbiter --raw "$RUN_DIR/findings.raw.json" \
    || printf '%s' "$ARB_JSON")"
  if [[ "$(printf '%s' "$ARB_JSON" | jq -r '.arbiter_salvaged // false')" == "true" ]]; then
    ARBITER_SALVAGED=1
    warn "arbiter reconciliation (#978): $RAW_COUNT raw finding(s) but arbiter returned 0 — salvaging raw findings ungrouped (fail-closed)"
  fi
  printf '%s' "$ARB_JSON" > "$RUN_DIR/arbiter.json"
fi

# ── CORROBORATION RANKING (SPEC-376) — annotate + tier-order via panel_logic.py ─
# Counts cross-vendor corroboration from the arbiter's merged_from membership,
# tags each finding with corroborated_by/corroborating_reviewers/corroboration_tier,
# and reorders Tier 1 (>=2 vendors) before Tier 2 (single reviewer). Logic lives in
# the Python module (#314 — shell launches, doesn't implement). A module failure
# degrades to the un-ranked arbiter output (no suppression, all findings still post).
# $PANEL_LOGIC was already resolved in the TRIAGE section (SPEC-332).
if [[ -f "$PANEL_LOGIC" ]]; then
  RANKED_JSON="$(printf '%s' "$ARB_JSON" \
    | python3 "$PANEL_LOGIC" --raw "$RUN_DIR/findings.raw.json" 2>>"$RUN_DIR/errors.log" \
    || printf '%s' "$ARB_JSON")"
  [[ -n "$RANKED_JSON" ]] || RANKED_JSON="$ARB_JSON"
else
  warn "panel_logic.py not found — skipping corroboration ranking (findings un-tiered)"
  RANKED_JSON="$ARB_JSON"
fi
printf '%s' "$RANKED_JSON" > "$RUN_DIR/arbiter.json"   # re-written WITH corroboration fields (binding 8)

SUMMARY="$(printf '%s' "$RANKED_JSON" | jq -r '.summary // "(no summary)"')"
FINDINGS="$(printf '%s' "$RANKED_JSON" | jq -c '.findings // []')"
# SPEC-333 (#314): tier counts via panel_logic.py (one call → trivial .total/.tier1/.tier2 plucks).
TIER_COUNTS="$(printf '%s' "$FINDINGS" | python3 "$PANEL_LOGIC" tier-counts)"
FCOUNT=$(printf '%s' "$TIER_COUNTS" | jq -r '.total')
TIER1_COUNT=$(printf '%s' "$TIER_COUNTS" | jq -r '.tier1')
TIER2_COUNT=$(printf '%s' "$TIER_COUNTS" | jq -r '.tier2')
ok "arbiter: $FCOUNT finding(s) after dedup (from $RAW_COUNT raw) · tier1=$TIER1_COUNT tier2=$TIER2_COUNT"

# ── SPEC-78: ledger-aware convergence verdict ─────────────────────────────────
# new_blocking_count: tier1 findings not already in the per-PR ledger.
# Gates the exit code only — does NOT suppress thread posting (OQ-2/C3 pending #400).
# Fingerprint = (sorted files, lens) per validation_logic.fingerprint + C7.
# ADR-1340 AD-10 / TD-VF-4 — release mode has NO ledger at all (a sixth
# PR-bound edge the ADR's original table did not enumerate): with $PR empty,
# PANEL_LEDGER would collapse to a single SHARED .ai-local/panel/pr-ledger.jsonl
# across every release run, and a tier-1 finding recorded once would be
# suppressed on every subsequent release forever. Skip both SPEC-78 Python
# blocks entirely in release mode; NEW_BLOCKING_COUNT keeps its TIER1_COUNT
# initialisation (never zeroed) and SUPPRESSED_COUNT stays 0 below.
NEW_BLOCKING_COUNT="${TIER1_COUNT}"
if [[ "$PANEL_MODE" != "release" && -f "$_VL_PY" ]]; then
    _LEDGER_PATH="$PANEL_LEDGER"
    _ARBITER_JSON="$RUN_DIR/arbiter.json"
    NEW_BLOCKING_COUNT=$(python3 - <<PYEOF
import json, sys, os
sys.path.insert(0, os.path.dirname("$_VL_PY"))
from validation_logic import load_ledger, fingerprint

ledger = load_ledger("$_LEDGER_PATH")
try:
    with open("$_ARBITER_JSON") as fh:
        data = json.load(fh)
    findings = data.get("findings", [])
except Exception:
    print(0)
    sys.exit(0)

new_blocking = 0
for f in findings:
    if f.get("severity", "") != "tier1":
        continue
    # fingerprint uses (sorted files, category/type). Map: file -> files list,
    # lens -> category (closest panel equivalent, per C7 / technical-design §5.3).
    fp_finding = {"file": f.get("file", ""), "category": f.get("lens", "")}
    if fingerprint(fp_finding) not in ledger:
        new_blocking += 1

print(new_blocking)
PYEOF
    ) || NEW_BLOCKING_COUNT="${TIER1_COUNT}"
fi
info "convergence (SPEC-78): tier1=${TIER1_COUNT} new_blocking=${NEW_BLOCKING_COUNT} ledger=${PANEL_LEDGER:-none (release mode, AD-10)}"

# ── SPEC-78 OQ-2 (#400, human-cleared): per-finding ledger flags for thread suppression ─
# Pre-pass: for each arbiter finding (in arbiter.json .findings order — the SAME order the
# POST loop iterates FINDINGS), emit "1" if its fingerprint is already in the per-PR ledger,
# else "0". The mapping (file -> file, lens -> category) is IDENTICAL to the new_blocking
# heredoc above (technical-design §2.1/§5) so the suppressed set ≡ the ledgered set.
# Fail-open: any error → all "0" (nothing suppressed; every finding posts). A ledger/
# fingerprint failure must never silently drop a finding from the PR.
LEDGERED_FLAGS=()
if [[ "$PANEL_MODE" != "release" && -f "$_VL_PY" ]]; then
    _flags_raw="$(python3 - <<PYEOF 2>>"$RUN_DIR/errors.log" || true
import json, sys, os
sys.path.insert(0, os.path.dirname("$_VL_PY"))
from validation_logic import load_ledger, fingerprint

ledger = load_ledger("$PANEL_LEDGER")
try:
    with open("$RUN_DIR/arbiter.json") as fh:
        findings = json.load(fh).get("findings", [])
except Exception:
    sys.exit(0)

for f in findings:
    fp_finding = {"file": f.get("file", ""), "category": f.get("lens", "")}
    print("1" if fingerprint(fp_finding) in ledger else "0")
PYEOF
)"
    while IFS= read -r _flag; do
        [[ -n "$_flag" ]] && LEDGERED_FLAGS+=("$_flag")
    done <<< "$_flags_raw"
fi

# ── POST — one line-level thread per finding, then one summary comment ──────────
# Line threads (review comments on the diff) are what the resolution gate enforces;
# the summary is a plain issue comment for the human's overview.
post_thread() {  # $1=path $2=line $3=body  → 0 on success
  gh api "repos/{owner}/{repo}/pulls/$PR/comments" \
    -f body="$3" -f commit_id="$HEAD_SHA" -f path="$1" -F line="$2" -f side=RIGHT \
    >/dev/null 2>>"$RUN_DIR/errors.log"
}

UNANCHORED=""   # findings we couldn't pin to a diff line → folded into the summary
POSTED=0
SUPPRESSED_COUNT=0   # SPEC-78 OQ-2: findings skipped because already in the per-PR ledger
FI=0                 # finding index into LEDGERED_FLAGS (FINDINGS iteration order)
# ADR-1340 AD-5 / TD §3.6 — release mode never posts a line-level thread: there
# is no PR diff to anchor to (E2), so the whole loop is skipped rather than
# allowed to fail once per finding into UNANCHORED. POSTED/SUPPRESSED_COUNT
# stay at their initial 0, UNANCHORED stays "".
# Callers: PR mode posts a line-level thread per finding; RELEASE mode never
# does. Changing either branch changes a gate. Do not collapse them.
if [[ "$PANEL_MODE" != "release" ]] && (( FCOUNT > 0 )); then
  while IFS= read -r row; do
    # SPEC-78 OQ-2 (#400): suppress posting a thread for a finding already in the ledger.
    # The flag array is in arbiter.json .findings order == FINDINGS order (technical-design §3.1).
    _ledgered="${LEDGERED_FLAGS[$FI]:-0}"
    FI=$((FI+1))
    file=$(jq -r '.file // ""' <<<"$row")
    line=$(jq -r '.line // 0'  <<<"$row")
    sev=$(jq -r '.severity // "tier3"' <<<"$row")
    lens=$(jq -r '.lens // "?"' <<<"$row")
    rvw=$(jq -r '.reviewer // "panel"' <<<"$row")
    title=$(jq -r '.title // ""' <<<"$row")
    detail=$(jq -r '.detail // ""' <<<"$row")
    sugg=$(jq -r '.suggestion // ""' <<<"$row")
    ctier=$(jq -r '.corroboration_tier // 2' <<<"$row")
    cby=$(jq -r '.corroborated_by // 1' <<<"$row")
    if [[ "$_ledgered" == "1" ]]; then
      SUPPRESSED_COUNT=$((SUPPRESSED_COUNT+1))
      if (( DRY_RUN )); then
        echo -e "  ${YELLOW}[dry-run] suppressed (ledgered)${RESET} $file:$line  [$sev/$lens] $title"
      else
        skip "suppressed (ledgered): $file:$line [$sev/$lens] $title — already triaged on a prior pass"
      fi
      continue
    fi
    if [[ "$ctier" == "1" ]]; then
      clabel="Tier 1 — cross-vendor confirmed (corroborated by $cby reviewers)"
    else
      clabel="Tier 2 — single reviewer"
    fi
    body=$(printf '**🔭 Oversight panel — %s / %s** (via %s)\n_%s_\n\n**%s**\n\n%s\n\n%s%s' \
      "$sev" "$lens" "$rvw" "$clabel" "$title" "$detail" \
      "${sugg:+_Suggested fix:_ }" "$sugg")
    if (( DRY_RUN )); then
      echo -e "  ${CYAN}[dry-run] thread${RESET} $file:$line  [$sev/$lens] $title"
    elif [[ -n "$file" && "$line" -gt 0 ]] && post_thread "$file" "$line" "$body"; then
      POSTED=$((POSTED+1))
    else
      UNANCHORED+="- **$sev/$lens** ($rvw) — \`$file:$line\` — $title — $detail"$'\n'
      [[ $DRY_RUN -eq 0 ]] && warn "couldn't anchor $file:$line to the diff → folding into summary"
    fi
  done < <(printf '%s' "$FINDINGS" | jq -c '.[]')
fi

# ── SPEC-333 (#314): render one tier's findings as markdown bullet lines now lives
# in panel_logic.py (`render-tier`). FINDINGS is already globally tier-1-first,
# severity-within-tier from panel_logic.py. The former `render_tier_findings` jq
# filter is removed.
TIER1_FINDINGS="$(printf '%s' "$FINDINGS" | python3 "$PANEL_LOGIC" render-tier --tier 1)"
TIER2_FINDINGS="$(printf '%s' "$FINDINGS" | python3 "$PANEL_LOGIC" render-tier --tier 2)"

# Assemble the summary comment.
# Callers: PR mode's header names threads/suppression; RELEASE mode's names the
# candidate SHA + reviewed range instead (AD-5 — there are no threads to count).
if [[ "$PANEL_MODE" == "release" ]]; then
  SUMMARY_BODY=$(cat <<EOF
## 🔭 Oversight panel — verdict

**Release candidate SHA:** \`$HEAD_SHA\`  ·  **Reviewed range:** \`${BASE_SHA:0:12}\`..\`${HEAD_SHA:0:12}\`
**Risk:** \`$RISK\`  ·  **Reviewers:** ${ROSTER[*]}  ·  **Findings:** $FCOUNT · tier1=$TIER1_COUNT tier2=$TIER2_COUNT

$SUMMARY
EOF
)
else
  SUMMARY_BODY=$(cat <<EOF
## 🔭 Oversight panel — verdict

**Risk:** \`$RISK\`  ·  **Reviewers:** ${ROSTER[*]}  ·  **Findings:** $FCOUNT ($POSTED posted as threads · $SUPPRESSED_COUNT suppressed (ledgered)) · tier1=$TIER1_COUNT tier2=$TIER2_COUNT

$SUMMARY
EOF
)
fi
# SPEC-376 R3 / binding 5: Tier 1 section BEFORE Tier 2; each empty section omitted.
if [[ -n "$TIER1_FINDINGS" ]]; then
  SUMMARY_BODY+=$'\n\n## Critical Findings (Corroborated by ≥2 Reviewers)\n> Confirmed by ≥ 2 independent reviewers. Address before merge.\n\n'"$TIER1_FINDINGS"
fi
if [[ -n "$TIER2_FINDINGS" ]]; then
  SUMMARY_BODY+=$'\n\n## Additional Findings (Single Reviewer)\n> Raised by one reviewer. Review and address where warranted.\n\n'"$TIER2_FINDINGS"
fi
# ADR-1340 / TD §3.6 — SQC prose: advisory-only note in release mode (AD-6 —
# the SQC result must never touch the release roster), the existing
# SAMPLED-gated red-team note in PR mode. Same RATE > 0 trigger as before.
if (( RATE > 0 )); then
  if [[ "$PANEL_MODE" == "release" ]]; then
    SUMMARY_BODY+=$'\n\n> SQC sample: advisory only in release mode (roster unaffected).'
  elif (( SAMPLED )); then
    SUMMARY_BODY+=$'\n\n> 🎲 **Selected for random red-team audit** — this `'"$RISK"$'` PR was sampled for an adversarial pass (SQC; rate '"$RATE"$'%, roll '"$ROLL"$'). Lower-tier PRs are spot-checked at random to estimate the escaped-defect rate and to deter risk under-declaration. Selection is reproducible from the head SHA + the secret audit salt.'
  fi
fi
if [[ -n "$UNANCHORED" ]]; then
  SUMMARY_BODY+=$'\n\n### Findings that could not be anchored to a diff line\n'"$UNANCHORED"
fi
if [[ "$RISK" == "CRITICAL" ]]; then
  if [[ "$PANEL_MODE" == "release" ]]; then
    SUMMARY_BODY+=$'\n\n> ⚠️ **CRITICAL** release range — a blast-radius assessment is required (AGENTS.md §5) before this release is cut.'
  elif ! gh pr view "$PR" --json commits -q '.commits[].messageBody' 2>/dev/null | grep -qi 'blast.radius'; then
    SUMMARY_BODY+=$'\n\n> ⚠️ **CRITICAL** change with no blast-radius note found in commit trailers — a blast-radius assessment is required (AGENTS.md §5) before merge.'
  fi
fi
if (( IP_IN_ROSTER )) && (( IP_STUB )); then
  SUMMARY_BODY+=$'\n\n> ⚖️ **IP/provenance was checked by a placeholder agent** — `ipcheck` ran but performs no real analysis yet (D19), so a clean result here is **not** an IP clearance.'
fi
if [[ "$PANEL_MODE" == "release" ]]; then
  SUMMARY_BODY+=$'\n\n<sub>Posted by `run_panel.sh` (release mode) — independent cross-vendor review over the release range.</sub>'
else
  SUMMARY_BODY+=$'\n\n<sub>Posted by `run_panel.sh` — independent cross-vendor review. Threads must be resolved before merge (branch policy D12). Author: respond on each thread.</sub>'
fi

# ADR-1340 / TD §3.6 — posting: release mode is GitHub-silent (no issue number
# to post to; AD-4 requires post_comment.sh --app worker, which lives entirely
# in run_release_panel.sh) and writes the summary to disk instead.
printf '%s' "$SUMMARY_BODY" > "$RUN_DIR/summary-body.md"
if [[ "$PANEL_MODE" == "release" ]]; then
  if (( DRY_RUN )); then
    echo ""
    echo -e "${BOLD}[dry-run] release summary that WOULD be written:${RESET}"
    echo "$SUMMARY_BODY"
    echo ""
  fi
  info "release mode: posting nothing to GitHub — summary written to $RUN_DIR/summary-body.md (run_release_panel.sh composes + posts the verdict comment)"
elif (( DRY_RUN )); then
  echo ""
  echo -e "${BOLD}[dry-run] summary comment that WOULD be posted:${RESET}"
  echo "$SUMMARY_BODY"
  echo ""
  warn "dry-run: nothing posted to PR #$PR. Raw outputs in $RUN_DIR"
else
  printf '%s' "$SUMMARY_BODY" | gh pr comment "$PR" --body-file - >/dev/null \
    && ok "posted summary comment to PR #$PR" \
    || err "failed to post summary comment (see $RUN_DIR/errors.log)"
  ok "posted $POSTED line-level thread(s)"
fi

echo ""
if [[ "$PANEL_MODE" == "release" ]]; then
  echo -e "${GREEN}${BOLD}Panel complete.${RESET}  release ${BASE_SHA:0:8}..${HEAD_SHA:0:8} · risk $RISK · $FCOUNT finding(s) · tier1=${TIER1_COUNT} · raw archive: $RUN_DIR"
else
  echo -e "${GREEN}${BOLD}Panel complete.${RESET}  PR #$PR · risk $RISK · $FCOUNT finding(s) · tier1=${TIER1_COUNT} new_blocking=${NEW_BLOCKING_COUNT} · suppressed=${SUPPRESSED_COUNT} · raw archive: $RUN_DIR"
fi
echo ""

# ADR-1340 AD-10/C4 (architect ruling, TD §3.7) — Edge 5: verdict write.
# Callers: PR mode (run_panel.sh <PR#>) and RELEASE mode (run_release_panel.sh -> --release-range).
# Release mode NEVER reaches the SPEC-78 escalation branch below: it writes
# panel-release.json and exits 0 whenever the engine itself completed.
# compose_verdict (release_panel_logic.py) is the SOLE authority on PASS/FAIL —
# one judgement site, the same reason there is one range derivation (AD-2). A
# non-zero exit from THIS script in release mode therefore denotes an engine
# ABORT, never a findings verdict — run_release_panel.sh's `panel-exit-nonzero`
# slug documents that distinction.
if [[ "$PANEL_MODE" == "release" ]]; then
  sha256_file() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" 2>/dev/null | awk '{print $1}'
    else shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; fi
  }

  ROSTER_JSON="[]"
  for spec in "${ROSTER[@]}"; do
    rtool="${spec%%:*}"; rlens="${spec##*:}"
    rstatus="ok"
    printf '%s\n' "${DEGRADED_TOOLS[@]:-}" | grep -qx "$rtool" && rstatus="degraded"
    ROSTER_JSON="$(jq -cn --argjson a "$ROSTER_JSON" --arg r "$rtool" --arg l "$rlens" --arg s "$rstatus" \
      '$a + [{reviewer:$r, lens:$l, status:$s}]')"
  done
  FILES_REVIEWED_JSON="$(printf '%s\n' "${REVIEWED[@]}" | jq -R . | jq -cs '.')"

  jq -n \
    --arg mode "release" \
    --arg base_sha "$BASE_SHA" --arg head_sha "$HEAD_SHA" \
    --arg effective_tier "$RISK" --arg deterministic_floor "$FLOOR" --arg validator_tier "${VALIDATOR_TIER:-unavailable}" \
    --argjson roster "$ROSTER_JSON" \
    --argjson total "$FCOUNT" --argjson tier1 "$TIER1_COUNT" --argjson tier2 "$TIER2_COUNT" \
    --argjson arbiter_salvaged "$([[ "${ARBITER_SALVAGED:-0}" -eq 1 ]] && echo true || echo false)" \
    --argjson chunks_attempted "${CHUNKS_ATTEMPTED:-0}" --argjson chunks_completed "${CHUNKS_COMPLETED:-0}" \
    --argjson files_reviewed "$FILES_REVIEWED_JSON" \
    --arg run_dir "$RUN_DIR" --arg summary_body_path "$RUN_DIR/summary-body.md" \
    --arg arbiter_sha256 "$(sha256_file "$RUN_DIR/arbiter.json")" \
    --arg findings_raw_sha256 "$(sha256_file "$RUN_DIR/findings.raw.json")" \
    --argjson sampled "$([[ $SAMPLED -eq 1 ]] && echo true || echo false)" --argjson rate "$RATE" \
    '{mode: $mode, base_sha: $base_sha, head_sha: $head_sha,
      effective_tier: $effective_tier, deterministic_floor: $deterministic_floor, validator_tier: $validator_tier,
      roster: $roster,
      findings: {total: $total, tier1: $tier1, tier2: $tier2, tier1_undispositioned: $tier1},
      arbiter_salvaged: $arbiter_salvaged,
      chunks_attempted: $chunks_attempted, chunks_completed: $chunks_completed,
      files_reviewed: $files_reviewed,
      run_dir: $run_dir, summary_body_path: $summary_body_path,
      arbiter_sha256: $arbiter_sha256, findings_raw_sha256: $findings_raw_sha256,
      sqc: {sampled: $sampled, rate: $rate, advisory: true}}' \
    > "$RUN_DIR/panel-release.json"
  exit 0
fi

# SPEC-78: write panel-verdict.json for oversight-evaluator (new_blocking_count field).
# SPEC-78 OQ-2 (#400): suppressed_count records ledgered findings not re-posted as threads.
printf '{"new_blocking_count":%s,"tier1_count":%s,"suppressed_count":%s,"ledger":"%s","pr":%s}\n' \
    "${NEW_BLOCKING_COUNT}" "${TIER1_COUNT}" "${SUPPRESSED_COUNT:-0}" "${PANEL_LEDGER}" "${PR}" \
    > "$RUN_DIR/panel-verdict.json"

# SPEC-78 R4: exit 3 (escalation) when there are un-ledgered blocking findings
# on a non-dry-run. Mirrors second-review convention (exit 3 = human decides).
# #978: a salvaged arbiter (arbiter failed with RAW_COUNT>0) ALWAYS escalates —
# a silent arbiter failure is itself a fail-open the panel must close, even if the
# salvaged findings are all sub-tier1 (they still post as threads, but escalation
# guarantees a human decides rather than the PR sliding through mergeable).
if [[ $DRY_RUN -eq 0 && ( "${NEW_BLOCKING_COUNT:-0}" -gt 0 || "${ARBITER_SALVAGED:-0}" -eq 1 ) ]]; then
    if [[ "${ARBITER_SALVAGED:-0}" -eq 1 ]]; then
        warn "Panel verdict: ESCALATE — arbiter failed with ${RAW_COUNT} raw finding(s); posted ${FCOUNT} raw finding(s) ungrouped (#978)"
    else
        warn "Panel verdict: ESCALATE — ${NEW_BLOCKING_COUNT} new un-ledgered blocking finding(s) (tier1)"
    fi
    exit 3
fi
