#!/usr/bin/env bash
# ensure_venv.sh — Create the oversight pip venv if it does not exist.
#
# Source this from other oversight scripts to export VENV, VENV_BIN, and
# OVERSIGHT_PYTHON without activating the venv globally (no PATH pollution).
#
#   source "$(dirname "${BASH_SOURCE[0]}")/ensure_venv.sh"        # from scripts/oversight/
#   source "$GATES_DIR/../ensure_venv.sh"                          # from scripts/oversight/gates/
#
# Or run standalone to create / verify the venv:
#   ./scripts/oversight/ensure_venv.sh
#
# The venv lives at scripts/oversight/.venv and is git-ignored (.venv/).
# On first use it is created from scripts/oversight/requirements.txt.
# Ubuntu 24.04+ (PEP 668 / EXTERNALLY-MANAGED): system and --user pip are
# blocked; this venv is the intended install path.
#
# Flags (effective only when run as a subprocess — not when sourced):
#   --quiet   Suppress informational stdout; errors still go to stderr.

_ENSURE_VENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$_ENSURE_VENV_DIR/.venv"
VENV_BIN="$VENV/bin"
OVERSIGHT_PYTHON="$VENV_BIN/python3"

# --quiet suppresses informational stdout; only meaningful when run as a subprocess.
_ENSURE_VENV_QUIET=false
[[ "${1:-}" == "--quiet" ]] && _ENSURE_VENV_QUIET=true

GREEN="\033[32m"; CYAN="\033[36m"; RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"

_evenv_info() { $_ENSURE_VENV_QUIET || echo -e "  ${CYAN}→${RESET}  $*"; }
_evenv_ok()   { $_ENSURE_VENV_QUIET || echo -e "  ${GREEN}✔${RESET}  $*"; }
_evenv_err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }

# Detect a stale venv: shebangs embed the absolute venv path at creation time.
# After a repo move the shebang points to the old location and tools break with
# "bad interpreter: No such file or directory".  If the pip shebang doesn't
# start with the current VENV path, the venv was built elsewhere — delete it so
# the creation block below rebuilds it in the right place.
_check_venv_stale() {
  local pip="$VENV/bin/pip"
  [[ -f "$pip" ]] || return 0  # doesn't exist yet, not stale
  local shebang
  shebang=$(head -1 "$pip" 2>/dev/null)
  if [[ "$shebang" != "#!${VENV}/"* ]]; then
    return 1  # stale
  fi
  return 0
}

# Free space (in KB) below which pip is likely to fail with ENOSPC while
# building the venv (radon/bandit/flake8 + their deps). A full disk otherwise
# surfaces as a generic "venv unavailable" with no hint about the real cause
# (#954: a full /tmp made pip ENOSPC, which read as a missing-venv FATAL).
_EVENV_MIN_FREE_KB=512000  # ~500 MB

# Report free space at the venv's filesystem, e.g. "412 MB free". Best-effort:
# returns nothing if df is unavailable or reports oddly.
_evenv_free_space() {
  df -Pk "$_ENSURE_VENV_DIR" 2>/dev/null \
    | awk 'NR==2 && $4 ~ /^[0-9]+$/ {printf "%d MB free", int($4/1024)}'
}

# Warn (do NOT block) when disk is low, so a subsequent pip failure is read as
# ENOSPC rather than a mystery. The pip exit-code checks below are the actual
# arbiter — this is purely an explicit early heads-up.
_check_disk_space() {
  local avail
  avail=$(df -Pk "$_ENSURE_VENV_DIR" 2>/dev/null | awk 'NR==2 {print $4}')
  [[ "$avail" =~ ^[0-9]+$ ]] || return 0  # can't tell — don't warn
  if (( avail < _EVENV_MIN_FREE_KB )); then
    warn "low disk: only $((avail/1024)) MB free at $_ENSURE_VENV_DIR (need ~$((_EVENV_MIN_FREE_KB/1024)) MB) — pip may fail with ENOSPC"
  fi
}

_create_venv() {
  _check_disk_space
  _evenv_info "creating oversight venv at $VENV"
  if ! python3 -m venv "$VENV"; then
    _evenv_err "python3 -m venv failed — is python3 (>= 3.8) installed? ($(_evenv_free_space))"
    return 1
  fi
  _evenv_info "installing oversight dependencies (this runs once) ..."
  # Check pip's exit code — a failed install (e.g. ENOSPC on a full disk) must
  # NOT be reported as "ready" and silently leave a broken venv behind (#954).
  if ! "$VENV_BIN/pip" install --quiet --upgrade pip; then
    _evenv_err "pip self-upgrade failed — disk full or network down? ($(_evenv_free_space))"
    return 1
  fi
  if ! "$VENV_BIN/pip" install --quiet -r "$_ENSURE_VENV_DIR/requirements.txt"; then
    _evenv_err "pip install of oversight requirements failed — disk full or network down? ($(_evenv_free_space))"
    return 1
  fi
  _evenv_ok "oversight venv ready"
}

# Smoke test: fast (~50ms) check that key packages are importable.
# Runs on every invocation so a broken venv (e.g. after a Python upgrade or
# path change) is caught and repaired without human intervention.
_smoke_test_venv() {
  "$OVERSIGHT_PYTHON" -c "import radon, bandit, flake8" 2>/dev/null
}

if ! _check_venv_stale; then
  warn "Venv shebang is stale (repo may have moved) — rebuilding venv"
  rm -rf "$VENV"
fi

if [[ ! -x "$OVERSIGHT_PYTHON" ]]; then
  if ! _create_venv; then exit 1; fi
fi

# Smoke test on every invocation — detects broken packages and auto-repairs.
if ! _smoke_test_venv; then
  warn "Oversight venv smoke test failed (key packages not importable) — rebuilding"
  rm -rf "$VENV"
  if ! _create_venv; then
    _evenv_err "Venv rebuild failed — oversight venv unavailable"
    exit 1
  fi
  if ! _smoke_test_venv; then
    _evenv_err "Venv smoke test failed after rebuild — key packages still not importable"
    exit 1
  fi
  _evenv_ok "oversight venv rebuilt and verified"
fi

export VENV VENV_BIN OVERSIGHT_PYTHON

# Drop marker file only after a successful smoke test — the marker is a cache
# hint, not a trust anchor.  A broken venv leaves the marker absent until the
# smoke test passes again.
REPO_ROOT="$(cd "$_ENSURE_VENV_DIR/../.." && pwd)"
REPO_HASH=$(echo -n "$REPO_ROOT" | md5sum 2>/dev/null | cut -d' ' -f1)
mkdir -p ~/.hos/setup-validation 2>/dev/null || true
touch ~/.hos/setup-validation/oversight-venv-${REPO_HASH} 2>/dev/null || true

# When executed directly (not sourced): print venv status and exit.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "Oversight venv : $VENV"
  echo "Python         : $("$OVERSIGHT_PYTHON" --version 2>&1)"
  echo ""
  "$VENV_BIN/pip" list --format=columns 2>/dev/null
fi
