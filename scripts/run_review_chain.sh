#!/usr/bin/env bash
# run_review_chain.sh — orchestrate the full HOS oversight pipeline in tier-gated order.
#
# Wraps three existing scripts in pipeline order:
#   1. scripts/oversight/run_validators.sh  — deterministic, always runs
#   2. scripts/run_second_review.sh         — agy at MEDIUM+, codex at HIGH+
#   3. scripts/run_panel.sh                 — outer loop (only when --pr is given)
#
# Usage:
#   ./scripts/run_review_chain.sh [--tier LOW|MEDIUM|HIGH|CRITICAL] [--pr <number>]
#                                 [--step <n>] [--since-tag|--since-main]
#                                 [--dry-run] [--help] [-- <files...>]
#
# Changed-file input modes (mutually exclusive), in priority order:
#   1. Explicit paths   bare positional args, or after `--` — passed to validators as-is
#   2. --since-main     auto-detect via `git diff origin/main..HEAD --name-only`
#   3. --since-tag      auto-detect via `git diff <last-tag>..HEAD --name-only`;
#                       falls back to HEAD~1..HEAD (with a warning) when no tag exists
#   Default when no paths and no --since-* flag: --since-tag.
#   --since-tag and --since-main cannot be combined. All changed files are passed
#   unfiltered; the validators handle file-type filtering themselves.
#
# Tier resolution order:
#   1. --tier flag (explicit override)
#   2. .claudetmp/oversight/validators/summary.json  (.tier field)
#   3. Default: MEDIUM
#
# Tier gating:
#   LOW        validators only
#   MEDIUM     validators + agy second review
#   HIGH/CRITICAL  validators + agy + codex second review
#   All tiers  if --pr provided, run_panel.sh runs after second review passes
#
# Idempotency: each step records a session sentinel under .claudetmp/run-review-chain/
# and is skipped if that sentinel already exists. Delete the directory to force a
# full re-run.

set -euo pipefail

# ── Colours / log helpers (match setup_clis.sh) ───────────────────────────────
GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*"; }
skip() { echo -e "  ${YELLOW}–${RESET}  $*"; }
info() { echo -e "  ${CYAN}→${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*"; }
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; }
die()  { err "$*"; exit 1; }

# ── Locate repo root (script lives in scripts/, one level below root) ─────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Sentinel directory for idempotency ────────────────────────────────────────
SESSION_DIR="$REPO_ROOT/.claudetmp/run-review-chain"
SUMMARY_JSON="$REPO_ROOT/.claudetmp/oversight/validators/summary.json"

# ── Arg parsing ───────────────────────────────────────────────────────────────
TIER_ARG=""
PR_NUM=""
STEP_ARG=""
DRY_RUN=0
SINCE_MODE=""   # "" | tag | main — auto-detect mode for changed files (SPEC-360)
EXTRA_VALIDATOR_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier)
      [[ $# -ge 2 ]] || die "--tier requires a value (LOW|MEDIUM|HIGH|CRITICAL)"
      TIER_ARG="$(echo "$2" | tr '[:lower:]' '[:upper:]')"
      shift 2 ;;
    --since-tag)
      [[ -z "$SINCE_MODE" ]] || die "--since-tag and --since-main are mutually exclusive"
      SINCE_MODE="tag"
      shift ;;
    --since-main)
      [[ -z "$SINCE_MODE" ]] || die "--since-tag and --since-main are mutually exclusive"
      SINCE_MODE="main"
      shift ;;
    --pr)
      [[ $# -ge 2 ]] || die "--pr requires a PR number"
      PR_NUM="$2"
      shift 2 ;;
    --step)
      [[ $# -ge 2 ]] || die "--step requires a value"
      STEP_ARG="$2"
      shift 2 ;;
    --dry-run)
      DRY_RUN=1
      shift ;;
    --help|-h)
      sed -n '2,36p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    --)
      shift; EXTRA_VALIDATOR_ARGS+=("$@"); break ;;
    -*)
      die "Unknown option: $1  (try --help)" ;;
    *)
      # Treat bare positional args as files to pass to run_validators.sh
      EXTRA_VALIDATOR_ARGS+=("$1")
      shift ;;
  esac
done

# ── Auto-detect changed files (SPEC-360) ──────────────────────────────────────
# Resolves a concrete diff range (never a bare symbolic HEAD) and appends the
# changed file paths to EXTRA_VALIDATOR_ARGS. Validators do their own type
# filtering, so the list is passed unfiltered. Logs the mode used and the count.
autodetect_files() {
  local mode="$1" base head files n
  head="$(git rev-parse --verify --quiet HEAD || true)"
  [[ -n "$head" ]] || die "auto-detect: cannot resolve HEAD — run inside a git repo or pass explicit file paths"

  if [[ "$mode" == "main" ]]; then
    base="$(git rev-parse --verify --quiet origin/main || true)"
    [[ -n "$base" ]] || die "auto-detect: cannot resolve origin/main (no remote?) — use explicit paths or --since-tag"
    info "auto-detect mode: since-main (git diff ${base:0:8}..${head:0:8})"
  else
    # mode == tag (also the default)
    local tag
    tag="$(git describe --tags --abbrev=0 2>/dev/null || true)"
    if [[ -n "$tag" ]]; then
      base="$(git rev-parse --verify --quiet "${tag}^{commit}" || true)"
      [[ -n "$base" ]] || die "auto-detect: tag '$tag' could not be resolved to a commit"
      info "auto-detect mode: since-tag (tag=$tag → ${base:0:8}..HEAD)"
    else
      warn "no git tag reachable from HEAD — falling back to HEAD~1..HEAD"
      base="$(git rev-parse --verify --quiet HEAD~1 || true)"
      [[ -n "$base" ]] || die "auto-detect: cannot resolve HEAD~1 (shallow clone or single commit) — re-run with explicit file paths"
      info "auto-detect mode: since-tag (fallback ${base:0:8}..HEAD)"
    fi
  fi

  files="$(git diff --name-only "$base" "$head")"
  n="$(printf '%s\n' "$files" | grep -c . || true)"
  if [[ "$n" -eq 0 ]]; then
    warn "auto-detect: diff range was empty (0 changed files) — validators will run with no file arguments"
    return 0
  fi
  while IFS= read -r f; do
    [[ -n "$f" ]] && EXTRA_VALIDATOR_ARGS+=("$f")
  done <<< "$files"
  info "auto-detect: $n changed file(s) detected"
}

# Engage auto-detection only when no explicit paths were given. Explicit paths
# always win; a --since-* flag passed alongside explicit paths is ignored.
if [[ ${#EXTRA_VALIDATOR_ARGS[@]} -eq 0 ]]; then
  autodetect_files "${SINCE_MODE:-tag}"
elif [[ -n "$SINCE_MODE" ]]; then
  warn "--since-$SINCE_MODE ignored: explicit file paths were provided"
fi

# ── Resolve tier ──────────────────────────────────────────────────────────────
resolve_tier() {
  if [[ -n "$TIER_ARG" ]]; then
    echo "$TIER_ARG"
    return
  fi
  if [[ -f "$SUMMARY_JSON" ]]; then
    local t
    t=$(python3 -c \
      "import json; d=json.load(open('$SUMMARY_JSON')); print(d.get('tier','').upper())" \
      2>/dev/null || true)
    if [[ -n "$t" ]]; then
      echo "$t"
      return
    fi
  fi
  echo "MEDIUM"   # safe default — triggers agy without requiring codex
}

TIER="$(resolve_tier)"

# Validate tier
case "$TIER" in
  LOW|MEDIUM|HIGH|CRITICAL) ;;
  *) die "Unrecognized tier '$TIER' — must be LOW, MEDIUM, HIGH, or CRITICAL" ;;
esac

# ── Risk ranking helper ────────────────────────────────────────────────────────
rank() {
  case "$1" in LOW) echo 0 ;; MEDIUM) echo 1 ;; HIGH) echo 2 ;; CRITICAL) echo 3 ;; *) echo 0 ;; esac
}

# ── Idempotency helpers ────────────────────────────────────────────────────────
mkdir -p "$SESSION_DIR"

sentinel_exists() { [[ -f "$SESSION_DIR/$1.done" ]]; }
mark_done()       { touch "$SESSION_DIR/$1.done"; }

# ── Header banner ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}AI Oversight — review chain${RESET}  (tier: ${BOLD}${TIER}${RESET}, mode: $( (( DRY_RUN )) && echo "dry-run" || echo "live" ), session: $SESSION_DIR)"
echo ""
if [[ -n "$TIER_ARG" ]]; then
  info "tier source: --tier flag (explicit override)"
elif [[ -f "$SUMMARY_JSON" ]]; then
  info "tier source: $SUMMARY_JSON"
else
  info "tier source: default (no --tier and no summary.json found)"
fi
[[ -n "$PR_NUM" ]] && info "PR: #$PR_NUM (run_panel.sh will run after second review)"
echo ""

# ── Step 1: run_validators.sh — always runs ────────────────────────────────────
echo -e "${BOLD}Step 1/3 — validators (deterministic, always)${RESET}"

if sentinel_exists "validators"; then
  skip "validators already ran this session — skipping (delete $SESSION_DIR to re-run)"
else
  VALIDATORS_SCRIPT="$SCRIPT_DIR/oversight/run_validators.sh"
  [[ -f "$VALIDATORS_SCRIPT" ]] || die "run_validators.sh not found at $VALIDATORS_SCRIPT"

  VALIDATOR_CMD=("$VALIDATORS_SCRIPT")
  [[ -n "$STEP_ARG" ]] && VALIDATOR_CMD+=("--step" "$STEP_ARG")
  [[ ${#EXTRA_VALIDATOR_ARGS[@]} -gt 0 ]] && VALIDATOR_CMD+=("${EXTRA_VALIDATOR_ARGS[@]}")

  if (( DRY_RUN )); then
    info "[dry-run] would run: ${VALIDATOR_CMD[*]}"
    mark_done "validators"
    ok "validators (dry-run)"
  else
    info "running: ${VALIDATOR_CMD[*]}"
    if "${VALIDATOR_CMD[@]}"; then
      mark_done "validators"
      ok "validators passed"
    else
      die "validators failed — review .claudetmp/oversight/validators/ for details"
    fi
  fi
fi
echo ""

# ── Step 2: run_second_review.sh — tier-gated ─────────────────────────────────
echo -e "${BOLD}Step 2/3 — second review (tier-gated)${RESET}"

RUN_AGY=0
RUN_CODEX=0
[[ "$(rank "$TIER")" -ge 1 ]] && RUN_AGY=1    # MEDIUM+
[[ "$(rank "$TIER")" -ge 2 ]] && RUN_CODEX=1  # HIGH+

if [[ $RUN_AGY -eq 0 ]]; then
  skip "second review: tier=$TIER is below MEDIUM — skipping (validators-only gate)"
elif sentinel_exists "second-review"; then
  skip "second review already ran this session — skipping"
else
  SECOND_REVIEW_SCRIPT="$SCRIPT_DIR/run_second_review.sh"
  [[ -f "$SECOND_REVIEW_SCRIPT" ]] || die "run_second_review.sh not found at $SECOND_REVIEW_SCRIPT"

  # run_second_review.sh artifact names embed the step number; require it at MEDIUM+
  # to prevent multiple runs colliding on the same "step0-<ts>.md" filename.
  # (For LOW tier, second review is skipped entirely, so the step is never used.)
  if [[ -z "$STEP_ARG" ]]; then
    die "ERROR: --step <N> is required for MEDIUM+ tier (second review artifact naming)"
  fi
  EFFECTIVE_STEP="$STEP_ARG"

  SR_CMD=("$SECOND_REVIEW_SCRIPT" "--step" "$EFFECTIVE_STEP" "--tier" "$TIER")

  # Warn if required CLIs are absent — run_second_review.sh is fail-closed itself,
  # but warn here so the operator knows before the script errors out.
  if (( RUN_AGY )) && ! command -v agy >/dev/null 2>&1; then
    warn "agy is not installed or not on PATH — second review may fail (see bootstrap/setup_clis.sh)"
  fi
  if (( RUN_CODEX )) && ! command -v codex >/dev/null 2>&1; then
    warn "codex is not installed or not on PATH — HIGH/CRITICAL second review may degrade (see bootstrap/setup_clis.sh)"
  fi

  if (( DRY_RUN )); then
    info "[dry-run] would run: ${SR_CMD[*]}"
    info "[dry-run] reviewers for tier=$TIER: $( (( RUN_AGY )) && echo "agy" ) $( (( RUN_CODEX )) && echo "codex" )"
    mark_done "second-review"
    ok "second review (dry-run)"
  else
    info "running: ${SR_CMD[*]}"
    info "reviewers: $( (( RUN_AGY )) && echo "agy(correctness)" ) $( (( RUN_CODEX )) && echo "codex(security)" )"
    if "${SR_CMD[@]}"; then
      mark_done "second-review"
      ok "second review passed"
    else
      die "second review failed — check .claudetmp/second-review/ and re-run after resolving findings"
    fi
  fi
fi
echo ""

# ── Step 3: run_panel.sh — only when --pr is provided ─────────────────────────
echo -e "${BOLD}Step 3/3 — panel (post-PR, --pr required)${RESET}"

if [[ -z "$PR_NUM" ]]; then
  skip "panel: --pr not provided — skipping outer loop (run with --pr <number> after opening the PR)"
elif sentinel_exists "panel-pr${PR_NUM}"; then
  skip "panel already ran for PR #$PR_NUM this session — skipping"
else
  PANEL_SCRIPT="$SCRIPT_DIR/run_panel.sh"
  [[ -f "$PANEL_SCRIPT" ]] || die "run_panel.sh not found at $PANEL_SCRIPT"

  PANEL_CMD=("$PANEL_SCRIPT" "$PR_NUM")
  (( DRY_RUN )) && PANEL_CMD+=("--dry-run")

  if ! command -v gh >/dev/null 2>&1; then
    warn "gh is not installed or not on PATH — panel will fail (see bootstrap/setup_clis.sh)"
  fi

  if (( DRY_RUN )); then
    info "[dry-run] would run: ${PANEL_CMD[*]}"
    mark_done "panel-pr${PR_NUM}"
    ok "panel (dry-run)"
  else
    info "running panel for PR #$PR_NUM: ${PANEL_CMD[*]}"
    if "${PANEL_CMD[@]}"; then
      mark_done "panel-pr${PR_NUM}"
      ok "panel complete for PR #$PR_NUM"
    else
      die "panel failed for PR #$PR_NUM — check run_panel.sh output above"
    fi
  fi
fi
echo ""

# ── Summary ───────────────────────────────────────────────────────────────────
echo -e "${GREEN}${BOLD}Review chain complete.${RESET}  tier=${TIER}$( [[ -n "$PR_NUM" ]] && echo " pr=#$PR_NUM" )"
echo "  Session sentinels: $SESSION_DIR"
echo ""
