#!/usr/bin/env bash
# run_tests_inner_loop.sh — Run the inner-loop test suite (required for PR approval).
#
# Skips tests marked @pytest.mark.slow or @pytest.mark.integration.
# These are the tests that must pass before opening or merging a PR.
# Expected runtime: < 60s.
#
# Usage:
#   ./scripts/framework/run_tests_inner_loop.sh                # run inner-loop tests
#   ./scripts/framework/run_tests_inner_loop.sh --failure-log   # + keep a full log on failure (#1903)
#   ./scripts/framework/run_tests_inner_loop.sh --help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"

# #1903: opt-in --failure-log. May appear anywhere in the args (not just $1);
# strip it here so the rest pass through to pytest unchanged.
FAILURE_LOG=0
_args=()
for _a in "$@"; do
  if [[ "$_a" == "--failure-log" ]]; then
    FAILURE_LOG=1
  else
    _args+=("$_a")
  fi
done
set -- ${_args[@]+"${_args[@]}"}

case "${1:-}" in
  --help|-h)
    echo "Usage: $0 [--failure-log] [pytest-args...]"
    echo ""
    echo "Runs the inner-loop test suite — all tests except @pytest.mark.slow"
    echo "and @pytest.mark.integration. Required to pass before PR approval."
    echo ""
    echo "  --failure-log   On a nonzero exit, keep a full stdout+stderr log in"
    echo "                  /tmp and print its path as INNER_LOOP_LOG=<path> on"
    echo "                  stdout. No log is created on a passing run. (#1903)"
    echo ""
    echo "Before the suite, bootstrap/tmp_reaper.py frees stale test temp (pytest"
    echo "run dirs and leaked tmp* entries older than 24 h); it never aborts the run."
    echo ""
    echo "For the full release suite: ./scripts/framework/run_tests_release.sh"
    exit 0
    ;;
esac

# #2054: pick the temp dir for this run, first match wins, and export it as
# TMPDIR so pytest-of-<user>, tempfile and mktemp land on disk, not on /tmp:
#   1. HOS_TMP_DIR, when a launcher chose one: a 0700 dir owned by the user, not
#      a symlink, not inside this clone (else WARN and fall through)
#   2. the "local" role dir from bootstrap/lib/hos_tmp_root.py (--create)
#   3. the inherited non-empty TMPDIR, unless it is inside this clone (WARN)
#   4. unset, i.e. /tmp (WARN)
# Blindly inheriting TMPDIR is not allowed: in a sandboxed ad-hoc session it is
# Claude Code's /tmp/claude, which would put pytest back on the RAM-backed tmpfs.
_select_tmpdir() {
  local _tool="$REPO_ROOT/bootstrap/lib/hos_tmp_root.py" _dir="" _why=""
  if [[ -n "${HOS_TMP_DIR:-}" ]]; then
    if _why="$(python3 -I "$_tool" check-dir --repo "$REPO_ROOT" --dir "$HOS_TMP_DIR" 2>&1)"; then
      export TMPDIR="$HOS_TMP_DIR"
      return 0
    fi
    echo -e "  ${RED}!${RESET}  WARN: ignoring HOS_TMP_DIR (${_why##*$'\n'}) — falling back" >&2
  fi
  if _dir="$(python3 -I "$_tool" resolve --repo "$REPO_ROOT" --role local --create 2>/dev/null)"; then
    if [[ -d "$_dir" && -w "$_dir" ]]; then
      export TMPDIR="$_dir"
      return 0
    fi
    _why="the resolved dir is not writable"
  else
    # Failure path only: stdout is the dir (never mixed with stderr), so re-run for the reason.
    # Last line only: a crashed resolver prints a traceback.
    _why="$(python3 -I "$_tool" resolve --repo "$REPO_ROOT" --role local --create 2>&1 >/dev/null | tail -n 1 || true)"
    _why="${_why#hos_tmp_root: }"
  fi
  if [[ -n "${TMPDIR:-}" ]]; then
    # Independent of the resolver (which may be what failed): physical paths, so a
    # symlink into the clone is caught too.
    local _tmp_real _repo_real
    _tmp_real="$(cd "$TMPDIR" 2>/dev/null && pwd -P || true)"
    _repo_real="$(cd "$REPO_ROOT" && pwd -P)"
    if [[ "$_tmp_real" != "$_repo_real" && "$_tmp_real" != "$_repo_real"/* ]]; then
      echo -e "  ${RED}!${RESET}  WARN: HOS local tmp dir unavailable (${_why:-unknown}) — keeping inherited TMPDIR=$TMPDIR" >&2
      return 0
    fi
    echo -e "  ${RED}!${RESET}  WARN: HOS local tmp dir unavailable (${_why:-unknown}) and the inherited TMPDIR is inside this clone — using /tmp" >&2
  else
    echo -e "  ${RED}!${RESET}  WARN: HOS local tmp dir unavailable (${_why:-unknown}) and TMPDIR unset — using /tmp" >&2
  fi
  unset TMPDIR
}
_select_tmpdir

echo -e "${BOLD}HOS Inner-Loop Tests${RESET} (PR-required tier)"
echo -e "  ${CYAN}→${RESET}  Skipping: @slow, @integration"
echo -e "  ${CYAN}→${RESET}  Repo: $REPO_ROOT"
echo ""

# Activate the oversight venv (where pytest lives)
VENV="$REPO_ROOT/scripts/oversight/.venv"
if [ -f "$VENV/bin/python" ]; then
  PYTHON="$VENV/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
else
  echo -e "  ${RED}✘${RESET}  python not found — run: ./bootstrap/hos_bootstrap.sh"
  exit 1
fi

cd "$REPO_ROOT"

# #1903: LOG_FILE stays empty unless --failure-log was passed AND mktemp
# succeeded. Everything below degrades to the plain (unlogged) path whenever
# LOG_FILE is empty, so a logging failure never fails the run. Flat in /tmp
# (not $TMPDIR, no subdirectory) — the host /tmp sweep only deletes files.
LOG_FILE=""
if [[ "$FAILURE_LOG" -eq 1 ]]; then
  _ts="$(date -u +%Y%m%dT%H%M%SZ)"
  _sha="$(git rev-parse --short HEAD 2>/dev/null || echo nohead)"
  if ! LOG_FILE="$(mktemp "/tmp/hos-inner-loop-${_ts}-${_sha}-XXXXXX" 2>/dev/null)"; then
    LOG_FILE=""
    echo -e "  ${RED}✘${RESET}  --failure-log: mktemp failed — continuing without a failure log" >&2
  fi
fi

_run_suite() {
  # #2054 (TD 8.1): free stale test debris (classes P and T only) before the suite
  # runs. --no-scratch is explicit: a test run never deletes agent scratch trees.
  # Best-effort: a failure here never changes this script's exit code.
  if [[ -f "$REPO_ROOT/bootstrap/tmp_reaper.py" ]]; then
    "$PYTHON" -I "$REPO_ROOT/bootstrap/tmp_reaper.py" --summary-only --no-scratch --max-seconds 20 \
      --root "${TMPDIR:-/tmp}" --root /tmp \
      || echo -e "  ${RED}✘${RESET}  tmp_reaper failed (rc=$?) — continuing" >&2
  fi
  echo -e "  ${CYAN}→${RESET}  Regenerating derived artifacts (SCRIPTS-INDEX.md, CODEOWNERS)..."
  "$SCRIPT_DIR/regen_all.sh" || return $?
  echo ""
  "$PYTHON" -m pytest -m "not slow and not integration" "$@"
}

if [[ -n "$LOG_FILE" ]]; then
  # Tee everything (regen_all.sh + pytest, both stdout and stderr) to the log
  # while still showing it on the console exactly as today. set +e/-e around
  # the pipeline: pipefail alone would trip this script's own set -e before
  # PIPESTATUS can be read; _run_suite already returns the right code itself
  # via its explicit `|| return $?` on the regen_all.sh step.
  set +e
  _run_suite "$@" 2>&1 | tee "$LOG_FILE"
  # PIPESTATUS is clobbered by the very next simple command (even a bare
  # assignment), so both elements must be captured in one shot.
  _ps=("${PIPESTATUS[@]}")
  _exit="${_ps[0]}"
  _tee_exit="${_ps[1]}"
  set -e
  if [[ "$_exit" -eq 0 ]]; then
    rm -f "$LOG_FILE"
  elif [[ "$_tee_exit" -ne 0 || ! -s "$LOG_FILE" ]]; then
    # tee itself failed (e.g. disk full) — what's on disk is empty/truncated,
    # not a usable log. Never claim one exists; the suite's own exit code is
    # still the one that matters and is preserved below either way.
    echo -e "  ${RED}✘${RESET}  --failure-log: tee failed — no log kept" >&2
    rm -f "$LOG_FILE"
  else
    echo -e "  ${RED}✘${RESET}  Failure log kept: $LOG_FILE" >&2
    echo "INNER_LOOP_LOG=$LOG_FILE"
  fi
  exit "$_exit"
fi

_run_suite "$@"
