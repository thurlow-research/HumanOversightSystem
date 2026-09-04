#!/usr/bin/env bash
# bootstrap/validate_setup.sh — HOS preflight check
#
# Run BEFORE invoking Claude. Zero token cost. Fail-fast if setup is broken.
# Exit 0 = setup OK, proceed. Exit 1 = setup broken, block Claude invocation.
#
# Usage:
#   bash bootstrap/validate_setup.sh                  # check from cwd
#   bash bootstrap/validate_setup.sh --quiet          # suppress OK output (cron use)
#   bash bootstrap/validate_setup.sh --repo /path     # explicit repo root
#   bash bootstrap/validate_setup.sh --role human     # also run the opt-in
#                                                      # sandbox-policy currency
#                                                      # check (#1221, AD-6).
#                                                      # Omitting --role skips
#                                                      # it entirely — this flag
#                                                      # is a declaration by the
#                                                      # caller, never inferred.

set -euo pipefail

QUIET=false
REPO_ROOT=""
SANDBOX_ROLE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quiet)  QUIET=true; shift ;;
    --repo)   REPO_ROOT="$2"; shift 2 ;;
    --role)   SANDBOX_ROLE="$2"; shift 2 ;;
    *)        echo "Usage: $0 [--quiet] [--repo PATH] [--role ROLE]" >&2; exit 1 ;;
  esac
done

[[ -z "$REPO_ROOT" ]] && REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo ".")"

fail() { echo "SETUP FAIL: $*" >&2; exit 1; }
ok()   { "$QUIET" || echo "  ✔  $*"; }

# sandbox_config_check ROLE REPO_ROOT — the opt-in #1221 currency check (AD-6).
# Returns 0 when the policy is current. Never calls exit or fail() itself —
# it only classifies the outcome; the caller decides whether to block
# (2026-08-16 E-2 ruling: divergent/unknown warn, missing hard-blocks for
# sandboxed roles). Every command that can fail sits inside a conditional so
# `set -euo pipefail` cannot abort this function.
#
# Return codes: 0 current | 1 divergent or check-could-not-run (warn, UNKNOWN
# for the latter) | 2 policy missing entirely (this clone was never enrolled).
sandbox_config_check() {
  local role="$1" repo="$2"
  local gen="$repo/scripts/framework/gen_sandbox_config.py"

  if [[ ! -f "$gen" ]]; then
    echo "  WARN: sandbox config CHECK FAILED (generator missing: $gen)." >&2
    echo "        The check did not run — policy status is UNKNOWN. This does NOT mean the policy is fine." >&2
    return 1
  fi

  # Declare-then-assign, deliberately: `local out="$(cmd)"` would make $? the
  # exit status of `local` itself, silently discarding the generator's real
  # exit code (this is the single most likely bug in this component).
  local out rc
  out="$(python3 "$gen" --role "$role" --clone-dir "$repo" --check 2>&1)" && rc=0 || rc=$?

  case "$rc" in
    0)
      ok "Sandbox policy current (contract/sandbox-policy.template.json)"
      return 0
      ;;
    1)
      echo "  WARN: SANDBOX POLICY DIVERGENT" >&2
      echo "$out" >&2
      echo "  session continues — this is a warning, not a block." >&2
      return 1
      ;;
    6)
      echo "  note: this clone's sandbox policy was never generated — it is hand-maintained" >&2
      echo "        (no .claude/hos-sandbox.values). Enroll with:" >&2
      echo "        scripts/framework/gen_sandbox_config.py --role $role --clone-dir $repo --handoff-dir <path> --claude-project-state <path>" >&2
      return 2
      ;;
    *)
      echo "  WARN: sandbox config CHECK FAILED (exit $rc) — the check did not run." >&2
      echo "        Policy status is UNKNOWN. This does NOT mean the policy is fine." >&2
      echo "$out" >&2
      return 1
      ;;
  esac
}

echo "=== HOS preflight check ($(date -u '+%Y-%m-%dT%H:%M:%SZ')) ==="

# ── 1. Required specialist agents ─────────────────────────────────────────────
# Read from the canonical list (scripts/framework/consumer_agents.txt) rather
# than hardcoding a hand-picked subset here — a third copy of the list drifts
# silently when a new agent is added there but not mirrored here (#1410; see
# HOS#225, which already fixed this drift for the installer's copy-loop and
# .hos-manifest enumerator).
AGENTS_LIST="$REPO_ROOT/scripts/framework/consumer_agents.txt"
[[ -f "$AGENTS_LIST" ]] || fail "scripts/framework/consumer_agents.txt missing — is this a proper HOS clone?"

REQUIRED_AGENTS=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%%#*}"
  line="$(echo "$line" | xargs)"
  [[ -n "$line" ]] && REQUIRED_AGENTS+=("$line")
done < "$AGENTS_LIST"
(( ${#REQUIRED_AGENTS[@]} > 0 )) || fail "no agents parsed from $AGENTS_LIST"

AGENTS_DIR="$REPO_ROOT/.claude/agents"
[[ -d "$AGENTS_DIR" ]] || fail ".claude/agents/ directory missing — run hos_install.sh"

for agent in "${REQUIRED_AGENTS[@]}"; do
  [[ -f "$AGENTS_DIR/${agent}.md" ]] \
    || fail ".claude/agents/${agent}.md missing — run hos_install.sh"
done
ok "All required agents present (${#REQUIRED_AGENTS[@]} checked)"

# ── 2. Bootstrap scripts ───────────────────────────────────────────────────────
[[ -f "$REPO_ROOT/bootstrap/get_app_token.sh" ]] \
  || fail "bootstrap/get_app_token.sh missing"
[[ -x "$REPO_ROOT/bootstrap/get_app_token.sh" ]] \
  || fail "bootstrap/get_app_token.sh not executable"
ok "bootstrap/get_app_token.sh present and executable"

# ── 3. Config / credentials ───────────────────────────────────────────────────
# Check in priority order: project-level → global
PROJECT_CONFIG="$(cd "$REPO_ROOT/.." 2>/dev/null && pwd)/.config/hos/apps.env"
GLOBAL_CONFIG="${HOS_CONFIG_DIR:-$HOME/.config/hos}/apps.env"

if [[ -f "$PROJECT_CONFIG" ]]; then
  ok "Config: project-level $PROJECT_CONFIG"
elif [[ -f "$GLOBAL_CONFIG" ]]; then
  ok "Config: global $GLOBAL_CONFIG"
else
  fail "apps.env not found at project-level or global — run hos_bootstrap.sh"
fi

# ── 4. Git repo sanity ────────────────────────────────────────────────────────
# Verify a git remote exists. If HOS_EXPECTED_REMOTE is set, also verify the
# remote matches — useful for HOS self-development but intentionally optional
# so consumer projects with their own remotes pass without false warnings.
REMOTE=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || echo "")
if [[ -z "$REMOTE" ]]; then
  fail "No git remote configured — is this a proper clone?"
elif [[ -n "${HOS_EXPECTED_REMOTE:-}" ]] && ! echo "$REMOTE" | grep -qF -- "$HOS_EXPECTED_REMOTE"; then
  echo "  WARN: remote is $REMOTE (expected $HOS_EXPECTED_REMOTE)" >&2
  ok "Git remote: $REMOTE (no match against HOS_EXPECTED_REMOTE)"
else
  ok "Git remote: $REMOTE"
fi

# ── 5. Sandbox policy currency (opt-in: --role) ────────────────────────────
# 2026-08-16 E-2 ruling: a divergent or inconclusive check still only warns,
# but a MISSING policy (rc 2 — never enrolled, or the live file is gone) now
# hard-blocks for sandboxed roles. Only `human` is sandboxed today; worker and
# overseer run under bypassPermissions and don't pass --role, so they never
# reach this branch.
if [[ -n "$SANDBOX_ROLE" ]]; then
  sandbox_rc=0
  sandbox_config_check "$SANDBOX_ROLE" "$REPO_ROOT" || sandbox_rc=$?
  if [[ "$sandbox_rc" -eq 2 && "$SANDBOX_ROLE" == "human" ]]; then
    fail "Sandbox policy missing for role '$SANDBOX_ROLE' — enroll before continuing (see message above)."
  elif [[ "$sandbox_rc" -ne 0 ]]; then
    echo "  WARN: sandbox policy check reported a problem (see above) — session continues." >&2
  fi
fi

echo "=== Preflight PASSED ==="
exit 0
