#!/usr/bin/env bash
# scripts/oversight/smoke_test.sh — one-shot health check for every dependency
# a HOS session relies on: agent CLIs, oversight venv scanners, the
# IP/provenance scanner, and the validator orchestrator.
#
# Read-only: does not write to .claudetmp/ or otherwise mutate pipeline
# state. run_validators.sh itself is checked for presence/syntax only, never
# invoked — invoking it would write .claudetmp/oversight/validators/, which
# Human's sandbox correctly blocks (Human is a read-only observer of
# Worker/Overseer's live pipeline state by design, not a bug to work around).
#
# Runnable from Human, Worker, or Overseer repos — resolves the venv relative
# to this script's own location, not a hardcoded repo name.
#
# Usage:
#   bash scripts/oversight/smoke_test.sh
#
# Exit 0 = every required dependency passed.
# Exit 1 = at least one required dependency is missing or broken.
# agy, codex, and scancode are optional (warn, don't fail) — same tier as
# bootstrap/hos_bootstrap.sh treats them.

set -uo pipefail  # no -e: run every check and report a full summary, not just the first failure

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"; CYAN="\033[36m"; RESET="\033[0m"
FAIL_COUNT=0
WARN_COUNT=0

ok()     { echo -e "  ${GREEN}✔${RESET}  $*"; }
bad()    { echo -e "  ${RED}✘${RESET}  $*"; FAIL_COUNT=$((FAIL_COUNT + 1)); }
soft()   { echo -e "  ${YELLOW}⚠${RESET}  $*"; WARN_COUNT=$((WARN_COUNT + 1)); }
header() { echo; echo -e "${CYAN}── $* ──${RESET}"; }

# check <label> <required:true|false> <cmd...>
# Runs `cmd --version`-shaped commands. Never parses/displays the version
# string itself — output banners vary too much across tools to do that
# reliably (isort and pysemgrep both print a banner/notice line before the
# version; bandit and black print a Python version instead of their own on
# the last line) — exit code is the only trustworthy pass/fail signal.
check() {
  local label="$1" required="$2"; shift 2
  local out
  if out="$("$@" 2>&1)"; then
    ok "$label"
  elif [[ "$required" == "true" ]]; then
    bad "$label — failed: $(echo "$out" | head -1)"
  else
    soft "$label — not available (optional): $(echo "$out" | head -1)"
  fi
}

header "Agent CLIs"
check "claude"  true  claude --version
check "gh"      true  gh --version
check "node"    true  node --version
check "npm"     true  npm --version
check "python3" true  python3 --version
check "agy"     false agy --version
check "codex"   false codex --version

header "Oversight venv scanners"
# shellcheck source=scripts/oversight/ensure_venv.sh
if source "$SCRIPT_DIR/ensure_venv.sh" --quiet; then
  for tool in bandit radon pysemgrep pip-audit detect-secrets mypy black flake8 isort pytest mutmut; do
    check "$tool" true "$VENV_BIN/$tool" --version
  done
else
  bad "oversight venv unavailable — cannot check scanners"
fi

header "IP / provenance scanner"
check "scancode" false scancode --version
if [[ -x "${VENV_BIN:-}/python3" ]]; then
  IP_OUT="$("$VENV_BIN/python3" "$SCRIPT_DIR/validators/ip_check.py" --help 2>/dev/null)"
  if echo "$IP_OUT" | "$VENV_BIN/python3" -c "import json,sys; json.load(sys.stdin)" >/dev/null 2>&1; then
    ok "ip_check.py runs and emits valid JSON"
  else
    bad "ip_check.py did not emit valid JSON: $(echo "$IP_OUT" | head -1)"
  fi
else
  bad "ip_check.py — oversight venv unavailable, cannot check"
fi
# ai-gen-code-search (Level 3 regurgitation) is a stub gated behind
# IP_REGURGITATION_ENABLED — absence is expected, not checked here.

header "Orchestrator"
if [[ -x "$SCRIPT_DIR/run_validators.sh" ]] && bash -n "$SCRIPT_DIR/run_validators.sh"; then
  ok "run_validators.sh present, executable, syntax OK (not invoked — invoking it writes .claudetmp/)"
else
  bad "run_validators.sh missing, not executable, or has a syntax error"
fi

echo
if (( FAIL_COUNT > 0 )); then
  echo "SMOKE TEST FAILED: $FAIL_COUNT required check(s) failed, $WARN_COUNT optional warning(s)"
  exit 1
fi
echo "SMOKE TEST PASSED: all required checks OK, $WARN_COUNT optional warning(s)"
exit 0
