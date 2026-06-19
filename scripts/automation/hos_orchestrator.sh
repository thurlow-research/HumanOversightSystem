#!/usr/bin/env bash
# hos_orchestrator.sh — HOS unattended worker orchestrator.
#
# The cron target. Runs the short-lived probe→claim→dispatch(spawn) cycle.
# Holds the machine lock ONLY across this cycle, then exits. Per-task workers
# (hos_worker.sh) run detached and independently (ADR-3).
#
# Usage:
#   hos_orchestrator.sh hos-orchestrator --class worker   # worker cron (0,30 * * * *)
#   hos_orchestrator.sh hos-orchestrator --class overseer # overseer cron (15,45 * * * *)
#
# The literal argv element "hos-orchestrator" is REQUIRED — it appears in
# ps -o command= output for the O18 liveness check in machine_lock.sh.
# The --class flag tells the orchestrator which credential context to use.
#
# Gate order (§11, R13.4, R8.4, ADR-3):
#   0. git pull --ff-only    (#300 — keep checkout current)
#   1. Activation check      (activation.py — first gate, zero activity if OFF)
#   2. hos-halt check        (file check — present → exit immediately)
#   3. Machine lock acquire  (machine_lock.sh)
#   4. Config resolve        (config_resolver.py)
#   5. Probe                 (probe.py)
#   6. Claim + dispatch      (claim.py → SPAWN hos_worker.sh, not run-to-completion)
#   7. Release lock + exit

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIB_DIR="$SCRIPT_DIR/lib"

GREEN="\033[32m"; YELLOW="\033[33m"; CYAN="\033[36m"
RED="\033[31m"; BOLD="\033[1m"; RESET="\033[0m"
_log() { printf '[hos-orchestrator] %s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"; }
_warn() { printf "${YELLOW}[hos-orchestrator] %s %s${RESET}\n" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }
_err()  { printf "${RED}[hos-orchestrator] %s %s${RESET}\n" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*" >&2; }

# ── Args ──────────────────────────────────────────────────────────────────────
AGENT_CLASS=""
_MARKER_SEEN=false

for arg in "$@"; do
  case "$arg" in
    hos-orchestrator) _MARKER_SEEN=true ;;
    --class) : ;;
    worker|overseer)
      [ -z "$AGENT_CLASS" ] && AGENT_CLASS="$arg" ;;
  esac
done

# Handle "--class worker" style (two-token flag)
for i in "${!@}"; do
  if [ "${!i}" = "--class" ]; then
    next=$((i+1))
    AGENT_CLASS="${!next:-}"
    break
  fi
done 2>/dev/null || true

# Simpler arg parsing that works in bash 3.2
AGENT_CLASS=""
i=1
while [ $i -le $# ]; do
  arg="${!i}"
  case "$arg" in
    --class)
      i=$((i+1))
      AGENT_CLASS="${!i:-}"
      ;;
    worker|overseer)
      [ -z "$AGENT_CLASS" ] && AGENT_CLASS="$arg"
      ;;
  esac
  i=$((i+1))
done

if [ -z "$AGENT_CLASS" ]; then
  _err "--class worker|overseer is required"
  exit 1
fi

_log "starting class=$AGENT_CLASS"

# ── GitHub App auth (#590) ────────────────────────────────────────────────────
# Must run before any GitHub API call. Exports GH_TOKEN (installation token)
# and HOS_BOT_LOGIN (e.g. hos-worker-hos[bot]) into this shell.
BOOTSTRAP_SCRIPT="$REPO_ROOT/bootstrap/get_app_token.sh"
if [[ ! -f "$BOOTSTRAP_SCRIPT" ]]; then
  _err "bootstrap/get_app_token.sh not found at $BOOTSTRAP_SCRIPT — run hos_bootstrap.sh first"
  exit 1
fi
# shellcheck source=../../bootstrap/get_app_token.sh
source <("$BOOTSTRAP_SCRIPT" --app "$AGENT_CLASS") \
  || { _err "Failed to obtain GitHub App token for --class $AGENT_CLASS"; exit 1; }

EXPECTED_LOGIN="hos-${AGENT_CLASS}-hos[bot]"
if [[ "$HOS_BOT_LOGIN" != "$EXPECTED_LOGIN" ]]; then
  _err "Identity guard failed: HOS_BOT_LOGIN='$HOS_BOT_LOGIN' (expected '$EXPECTED_LOGIN')"
  exit 1
fi
_log "authenticated as $HOS_BOT_LOGIN"

# ── Python helper ─────────────────────────────────────────────────────────────
PYTHON="${HOS_PYTHON:-python3}"
_py() {
  PYTHONPATH="$REPO_ROOT" "$PYTHON" -c "$@"
}

# ── Step 0: git pull --ff-only (#300) ─────────────────────────────────────────
_log "step 0: git pull --ff-only"
if ! git -C "$REPO_ROOT" pull --ff-only --quiet 2>&1; then
  _warn "git pull --ff-only failed (local modifications or diverged branch) — proceeding with current checkout"
  # Non-fatal: the loop continues on the current checkout. This is intentional:
  # a stale checkout is better than silently aborting the whole probe cycle.
  # Operators should investigate if this warning is persistent.
fi

# ── Step 1: activation check ──────────────────────────────────────────────────
_log "step 1: activation check"
ACTIVE=$(_py "
import sys
sys.path.insert(0, '$REPO_ROOT')
from scripts.automation.lib.activation import check_activation
print('1' if check_activation('$REPO_ROOT') else '0')
" 2>/dev/null) || ACTIVE="0"

if [ "$ACTIVE" != "1" ]; then
  _log "inactive — exiting (no probe, no API calls)"
  exit 0
fi

# ── Step 2: hos-halt check ────────────────────────────────────────────────────
_log "step 2: hos-halt check"
HALT_PATH=""
for candidate in "$REPO_ROOT/PROJECT/hos-halt" "$REPO_ROOT/.hos-halt"; do
  if [ -f "$candidate" ] && [ -s "$candidate" ]; then
    HALT_PATH="$candidate"
    break
  fi
done

if [ -n "$HALT_PATH" ]; then
  _log "hos-halt file present at $HALT_PATH — exiting immediately"
  exit 0
fi

# ── Step 3: machine lock ──────────────────────────────────────────────────────
_log "step 3: machine lock"
# shellcheck source=./lib/machine_lock.sh
source "$LIB_DIR/machine_lock.sh"
setup_lock_trap
acquire_lock || exit 0  # Legitimate contention — wait for next window

# ── Step 4: config resolve + enabled check ────────────────────────────────────
_log "step 4: config resolve"
CONFIG_JSON=$(_py "
import sys, json
sys.path.insert(0, '$REPO_ROOT')
from scripts.automation.lib.config_resolver import resolve
from dataclasses import asdict
cfg = resolve('$REPO_ROOT')
# Emit the fields we need in the shell
print(json.dumps({
  'enabled': cfg.enabled,
  'mode': cfg.mode,
  'customer': cfg.customer,
  'cadence_floor': cfg.cadence.floor,
  'cadence_ceiling': cfg.cadence.ceiling,
  'per_task_tokens': cfg.thresholds.per_task_tokens,
  'window_budget': cfg.thresholds.window_budget_tokens,
  'triage_floor': cfg.thresholds.triage_confidence_floor,
  'per_issue_failures': cfg.breakers.per_issue_failures,
  'max_task_runtime': cfg.breakers.max_task_runtime,
}))
" 2>/dev/null) || {
  _err "config resolver failed — exiting"
  release_lock
  exit 1
}

ENABLED=$(printf '%s' "$CONFIG_JSON" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d['enabled'])" 2>/dev/null || echo "False")
if [ "$ENABLED" != "True" ]; then
  _log "enabled=false in governance config — exiting"
  release_lock
  exit 0
fi

CUSTOMER=$(printf '%s' "$CONFIG_JSON" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d['customer'])" 2>/dev/null || echo "")
MODE=$(printf '%s' "$CONFIG_JSON" | "$PYTHON" -c "import sys,json; d=json.load(sys.stdin); print(d['mode'])" 2>/dev/null || echo "propose-only")

_log "config: customer=$CUSTOMER mode=$MODE"

# ── Step 5: probe ─────────────────────────────────────────────────────────────
_log "step 5: probe (class=$AGENT_CLASS)"

# Determine what to probe based on class:
#   worker   → probe for new inbound work (hos-coordination issues)
#   overseer → probe for reviewable PRs (open hos/auto/* branches)
if [ "$AGENT_CLASS" = "overseer" ]; then
  _log "overseer probe: looking for open hos/auto/* PRs to review"
  CANDIDATES_JSON=$(_py "
import sys, json
sys.path.insert(0, '$REPO_ROOT')
from scripts.automation.lib.github import _run_gh
import os
# Get OWNER/REPO from git remote
import subprocess
remote = subprocess.run(['git', '-C', '$REPO_ROOT', 'remote', 'get-url', 'origin'],
                       capture_output=True, text=True).stdout.strip()
# Normalize: strip scheme+host, strip .git
import re
m = re.match(r'(?:https://github\.com/|git@github\.com:)([^/]+)/(.+?)(?:\.git)?\$', remote, re.I)
if not m:
    print(json.dumps([]))
    sys.exit(0)
owner, repo = m.group(1).lower(), m.group(2).lower()
# List open PRs with hos/auto/ head branches
prs = _run_gh([f'/repos/{owner}/{repo}/pulls?state=open&per_page=50']) or []
candidates = [
    {'owner': owner, 'repo': repo, 'pr_number': pr['number'],
     'head': pr['head']['ref'], 'cid': pr['head']['ref'].replace('hos/auto/', '')}
    for pr in prs
    if isinstance(pr, dict) and pr.get('head', {}).get('ref', '').startswith('hos/auto/')
]
print(json.dumps(candidates))
" 2>/dev/null) || CANDIDATES_JSON="[]"

  CANDIDATE_COUNT=$(printf '%s' "$CANDIDATES_JSON" | "$PYTHON" -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  _log "overseer found $CANDIDATE_COUNT reviewable PR(s)"

  if [ "$CANDIDATE_COUNT" = "0" ]; then
    release_lock
    exit 0
  fi

  # Spawn one overseer worker per PR
  printf '%s' "$CANDIDATES_JSON" | "$PYTHON" - <<'PYEOF'
import sys, json, subprocess, os
candidates = json.load(sys.stdin)
script = os.path.join(os.environ.get('SCRIPT_DIR', '.'), 'hos_worker.sh')
for c in candidates:
    cmd = [
        'nohup', 'bash', script, 'hos-orchestrator',
        '--class', 'overseer',
        '--cid', c['cid'],
        '--owner', c['owner'],
        '--repo', c['repo'],
        '--pr', str(c['pr_number']),
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    print(f"[hos-orchestrator] spawned overseer worker for PR #{c['pr_number']} cid={c['cid']}")
PYEOF

else
  # Worker probe — look for new inbound work
  CANDIDATES_JSON=$(_py "
import sys, json, subprocess, re
sys.path.insert(0, '$REPO_ROOT')
from scripts.automation.lib.probe import probe_repo
from scripts.automation.lib.activation import derive_repo_id
import subprocess
remote = subprocess.run(['git', '-C', '$REPO_ROOT', 'remote', 'get-url', 'origin'],
                       capture_output=True, text=True).stdout.strip()
m = re.match(r'(?:https://github\.com/|git@github\.com:)([^/]+)/(.+?)(?:\.git)?\$', remote, re.I)
if not m:
    print(json.dumps([]))
    sys.exit(0)
owner, repo_name = m.group(1).lower(), m.group(2).lower()
repo_id = derive_repo_id('$REPO_ROOT')
# Load allowlist from config
import json as _json
cfg_raw = '''$CONFIG_JSON'''
cfg = _json.loads(cfg_raw) if cfg_raw.strip() else {}
allowlist = cfg.get('requester_allowlist', [])
candidates = probe_repo(
    owner=owner, repo=repo_name, repo_id=repo_id,
    requester_allowlist=allowlist,
    customer='$CUSTOMER', repo_root='$REPO_ROOT'
)
print(json.dumps([
    {'owner': c.owner, 'repo': c.repo,
     'issue_number': c.issue_number, 'issue_url': c.issue_url,
     'labels': c.labels}
    for c in candidates
]))
" 2>/dev/null) || CANDIDATES_JSON="[]"

  CANDIDATE_COUNT=$(printf '%s' "$CANDIDATES_JSON" | "$PYTHON" -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
  _log "worker probe found $CANDIDATE_COUNT candidate(s)"

  if [ "$CANDIDATE_COUNT" = "0" ]; then
    release_lock
    exit 0
  fi

  # Spawn one worker per candidate
  SCRIPT_DIR_EXPORT="$SCRIPT_DIR"
  printf '%s' "$CANDIDATES_JSON" | SCRIPT_DIR="$SCRIPT_DIR_EXPORT" "$PYTHON" - <<PYEOF
import sys, json, subprocess, os
candidates = json.load(sys.stdin)
script = os.path.join(os.environ.get('SCRIPT_DIR', '.'), 'hos_worker.sh')
for c in candidates:
    cmd = [
        'nohup', 'bash', script, 'hos-orchestrator',
        '--class', 'worker',
        '--owner', c['owner'],
        '--repo', c['repo'],
        '--issue', str(c['issue_number']),
    ]
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    print(f"[hos-orchestrator] spawned worker for issue #{c['issue_number']}")
PYEOF
fi

# ── Step 7: release lock + exit ───────────────────────────────────────────────
# Trap handles release_lock on EXIT
_log "dispatched — releasing lock and exiting"
