#!/usr/bin/env bash
# bootstrap/hos_repo_sync.sh — fetch + fast-forward the current repo's default
# branch, but only if enough time has passed since the last sync.
#
# Usage:
#   bootstrap/hos_repo_sync.sh              # uses 900s (15 min) default interval
#   bootstrap/hos_repo_sync.sh 300           # custom interval in seconds
#   HOS_REPO_SYNC_STATE_DIR=... bootstrap/hos_repo_sync.sh   # override state dir
#   HOS_REPO_SYNC_PRUNE=1 HOS_TOKEN_APP_ROLE=human bootstrap/hos_repo_sync.sh
#                                            # also prune merged/closed local branches
#   HOS_REPO_SYNC_PRUNE_TIMEOUT_SECS=90      # bound on the prune step (positive integer)
#
# Intended for a human (or a human-proxy interactive session) working against
# an HOS-managed repo whose autonomous worker/overseer cron roles can move
# `origin` with no signal reaching an interactive session otherwise. Run it at
# the start of a turn/session; it no-ops quickly when nothing needs doing.
#
# This is NOT part of the autonomous worker/overseer pipeline (see bin/hos-cron
# for that) — it has no oversight-pipeline role of its own.
#
# State is tracked per-repo (keyed by the repo's absolute path) under
# /tmp/hos-repo-sync by default, so one copy of this script serves every clone
# on the machine and needs no separate cleanup job — it is cleared on reboot
# like the rest of HOS's machine-local /tmp state (see bin/hos-trim-logs).
#
# Only ever fast-forwards, never merges/rebases:
#   - If the default branch is not checked out: updated via a fetch refspec,
#     which git only permits as a fast-forward.
#   - If the default branch is checked out: only via `pull --ff-only`, and
#     only when the working tree is clean. A dirty tree gets fetch-only.
#
# Local-branch prune (#2288 S3, TECHNICAL-DESIGN-2288-S3-repo-sync-prune.md):
# off unless HOS_REPO_SYNC_PRUNE=1; bin/hos-human turns it on for its own
# session-start call (HOS_REPO_SYNC_PRUNE=0 opts out). Human clone only: it also
# requires HOS_TOKEN_APP_ROLE=human, the script's own clone, and a clone that is
# not a registered worker/overseer root (gates P2, P4, P4b). It runs
# `readopt reap-orphans --local-only --no-issue-closed`, so a local branch is
# deleted only when its PR is merged or closed, or its content is already on main
# (pr-merged, pr-closed, landed-ancestor, landed-content). The prune runs after
# the state write and never changes this script's exit status.
# Hardening (#2299): the readopt child runs under `env -u PYTHONPATH -u
# HOS_TOKEN_APP_ROLE python3 -E -s`, so caller-set import paths and user site
# packages cannot load code, and github.py cannot start a slow token re-mint.
# Gate P4b is fail-closed: a worker/overseer registry entry whose value is not an
# existing directory (e.g. a quoted path) skips the prune, naming only the key.
# Each REAPED / REAP-FAILED line for a local branch is validated against an
# anchored pattern and written as a best-effort audit event (repo-sync-branch-reap,
# repo-sync-branch-reap-failed); audit failure never changes output or exit status.

# -e intentionally omitted: the cmd; status=$? capture pattern requires it absent.
set -uo pipefail

interval="${1:-${HOS_REPO_SYNC_INTERVAL:-900}}"
state_dir="${HOS_REPO_SYNC_STATE_DIR:-/tmp/hos-repo-sync}"

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$repo_root" ]; then
  echo "hos-repo-sync: not inside a git repository, skipping" >&2
  exit 0
fi

umask 077
mkdir -p "$state_dir"
# Ownership guard: reject a state directory we don't own (symlink/TOCTOU defence).
# stat -c is Linux; stat -f is macOS — try both, treat empty as unverifiable.
_dir_uid="$(stat -c '%u' "$state_dir" 2>/dev/null \
           || stat -f '%u' "$state_dir" 2>/dev/null \
           || echo "")"
if [ -n "$_dir_uid" ] && [ "$_dir_uid" != "$(id -u)" ]; then
  echo "hos-repo-sync: state directory '$state_dir' owned by UID $_dir_uid (expected $(id -u)) — possible symlink attack, refusing to write" >&2
  exit 1
fi

# POSIX-portable CRC32 via cksum; negligible collision risk at typical repo counts.
key="$(printf '%s' "$repo_root" | cksum | cut -d' ' -f1)"
state_file="$state_dir/${key}.json"

now="$(date +%s)"
last_sync=0
if [ -f "$state_file" ]; then
  last_sync="$(grep -o '"last_sync_epoch"[[:space:]]*:[[:space:]]*[0-9]*' "$state_file" | grep -o '[0-9]*$')"
  last_sync="${last_sync:-0}"
fi

elapsed=$(( now - last_sync ))
if [ "$elapsed" -lt "$interval" ]; then
  echo "hos-repo-sync: skipped, last synced ${elapsed}s ago (< ${interval}s) — $repo_root"
  exit 0
fi

cd "$repo_root" || exit 1

# Gate the .gitmodules stderr filter: only suppress gitmodules access warnings
# if .gitmodules is not a real tracked file in this repo. Sandboxed dev
# environments can produce spurious "unable to access .gitmodules" warnings
# even when there are no submodules; repos that DO have a tracked .gitmodules
# should see all stderr unfiltered so genuine submodule problems are surfaced.
_filter_gitmodules=false
if ! git ls-files --error-unmatch .gitmodules >/dev/null 2>&1; then
  _filter_gitmodules=true
fi

# Emit captured stderr for one fetch/pull/ff operation. Skips spurious
# .gitmodules noise (when safe to filter). Suppresses blank output entirely.
_pipe_stderr() {
  local out="$1"
  [ -z "$out" ] && return 0
  if $_filter_gitmodules; then
    printf '%s\n' "$out" | grep -v 'unable to access.*\.gitmodules' >&2 || true
  else
    printf '%s\n' "$out" >&2
  fi
}

# Classifies a failure message as structural (a filesystem/permission
# restriction that will never resolve by retrying — e.g. a sandboxed
# read-only working tree) vs benign (network/auth/divergence — retry next
# session). See #1200: the two demand different responses and must not be
# reported identically.
_is_structural_failure() {
  printf '%s' "$1" | grep -qiE 'read-only file system|permission denied|unable to unlink|unable to create'
}

fetch_out="$(git fetch origin 2>&1)"; fetch_status=$?
_pipe_stderr "$fetch_out"
if [ "$fetch_status" -ne 0 ]; then
  echo "hos-repo-sync: git fetch failed — $repo_root" >&2
  if _is_structural_failure "$fetch_out"; then
    echo "hos-repo-sync: STRUCTURAL cause — a filesystem/permission restriction is blocking the fetch and will not resolve by retrying. See #1183/#1185 for the sandbox write-protection this is likely caused by." >&2
  else
    echo "hos-repo-sync: transient cause — likely network/auth; safe to retry next session." >&2
  fi
  exit 1
fi

default_branch="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
if [ -z "$default_branch" ]; then
  git remote set-head origin -a >/dev/null 2>&1
  default_branch="$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
fi
default_branch="${default_branch:-main}"
current_branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"

if ! git rev-parse --verify -q "refs/heads/${default_branch}" >/dev/null; then
  behind=1   # no local ref yet — force the create/fast-forward path below
else
  behind="$(git rev-list --count "${default_branch}..origin/${default_branch}" 2>/dev/null)"
  behind="${behind:-0}"
fi

sync_ok=false
sync_failure_out=""

if [ "$behind" -eq 0 ]; then
  sync_ok=true
  echo "hos-repo-sync: $default_branch up to date — $repo_root"
elif [ "$current_branch" = "$default_branch" ]; then
  if [ -z "$(git status --porcelain)" ]; then
    pull_out="$(git pull --ff-only 2>&1)"; pull_status=$?
    _pipe_stderr "$pull_out"
    if [ "$pull_status" -eq 0 ]; then
      sync_ok=true
      echo "hos-repo-sync: fast-forwarded $default_branch — $repo_root"
    else
      echo "hos-repo-sync: fetch OK, pull --ff-only failed on '$default_branch' (diverged?) — $repo_root" >&2
      sync_failure_out="$pull_out"
    fi
  else
    echo "hos-repo-sync: $default_branch is behind but working tree is dirty, fetch-only — $repo_root"
    sync_failure_out="(fetch-only: working tree dirty)"
  fi
else
  ff_out="$(git fetch origin "${default_branch}:${default_branch}" 2>&1)"; ff_status=$?
  _pipe_stderr "$ff_out"
  if [ "$ff_status" -eq 0 ]; then
    sync_ok=true
    echo "hos-repo-sync: fast-forwarded local $default_branch (checked-out branch '$current_branch' untouched) — $repo_root"
  else
    echo "hos-repo-sync: fetch OK, fast-forward of '$default_branch' failed (diverged?) — $repo_root" >&2
    sync_failure_out="$ff_out"
  fi
fi

# Loud, unmissable staleness report (#1200) — a session must always be able
# to tell it may be working against superseded code, even when the sync
# itself could not fix it. Printed to stderr so it survives being piped
# through anything that filters stdout.
if ! $sync_ok; then
  head_short="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "" >&2
  echo "hos-repo-sync: STALE — HEAD is ${behind} commit(s) behind origin/${default_branch} (current HEAD: ${head_short}). File/line references and analysis in this session may be against superseded code." >&2
  if _is_structural_failure "$sync_failure_out"; then
    echo "hos-repo-sync: STRUCTURAL cause — a filesystem/permission restriction is blocking the sync and will not resolve by retrying. See #1183/#1185 for the sandbox write-protection this is likely caused by." >&2
  else
    echo "hos-repo-sync: transient cause — likely network/auth, a dirty working tree, or a genuinely diverged branch; safe to retry next session." >&2
  fi
fi

# Atomically write the state file (mktemp + mv avoids following a symlink at
# the destination and prevents partial-write races).
_tmpf="$(mktemp "$state_dir/.sync.XXXXXX")"
cat > "$_tmpf" <<JSON
{
  "last_sync_epoch": $now
}
JSON
mv "$_tmpf" "$state_file"; sync_rc=$?

# --- Local-branch prune (#2288 S3). Gate order P1..P6 per the TD; the first
# failing gate decides. Nothing in here may change the exit status.
_prune_skip() { echo "hos-repo-sync: prune skipped — $1"; }

# P4b: is $1 (physical path) a registered worker/overseer root in projects.conf?
# Returns 0 if so, 2 if any such entry has a non-empty value that is not an
# existing directory (fail closed; the key is left in _registry_bad_key), else 1.
# Values are read literally, as bin/hos-cron does: no quote stripping.
_registry_bad_key=""
_is_registered_cron_root() {
  local conf="${HOME:-}/.config/hos/projects.conf" line key val phys matched=1
  [ -f "$conf" ] && [ -r "$conf" ] || return 1
  while IFS= read -r line || [ -n "$line" ]; do
    if [[ "$line" =~ ^([A-Za-z0-9_]+_(worker|overseer)_root)=(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      val="${BASH_REMATCH[3]}"
      val="${val%"${val##*[![:space:]]}"}"  # trailing CR / whitespace
      val="${val%/}"
      [ -n "$val" ] || continue
      if [ ! -d "$val" ]; then
        _registry_bad_key="$key"
        continue
      fi
      phys="$(cd "$val" 2>/dev/null && pwd -P)" && val="$phys"
      [ "$val" = "$1" ] && matched=0
    fi
  done < "$conf"
  [ -n "$_registry_bad_key" ] && return 2
  return "$matched"
}

# Best-effort audit event for one validated local REAPED/REAP-FAILED line, guarded
# like bootstrap/delete_branch.sh _audit_branch_delete. Always returns 0. Inputs
# are already restricted by the caller's anchored regex, so no JSON escaping needed.
_prune_audit() {
  local event="$1" branch="$2" reason="$3" where="$4" pr="$5" tip="$6"
  local audit_lib="$script_root/scripts/oversight/lib/audit_log.sh" json
  [ -f "$audit_lib" ] || return 0
  # shellcheck disable=SC1090
  source "$audit_lib" 2>/dev/null || return 0
  command -v audit_write_event >/dev/null 2>&1 || return 0
  json="$(printf '{"event":"%s","actor":"human","branch":"%s","reason":"%s","where":"%s","pr":"%s","tip":"%s","timestamp":"%s"}' \
    "$event" "$branch" "$reason" "$where" "$pr" "$tip" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
  audit_write_event "$json" "$script_root" >/dev/null 2>&1 </dev/null || true
  return 0
}

_prune_local_branches() {
  [ "${HOS_REPO_SYNC_PRUNE:-}" = "1" ] || return 0
  if [ "${HOS_TOKEN_APP_ROLE:-}" != "human" ]; then
    _prune_skip "not the human role"; return 0
  fi
  local script_root root_phys reg_rc
  script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd -P)"
  if [ -z "$script_root" ] || [ ! -f "$script_root/scripts/automation/readopt.py" ]; then
    _prune_skip "scripts/automation/readopt.py not present"; return 0
  fi
  root_phys="$(cd "$repo_root" 2>/dev/null && pwd -P)"
  if [ "$root_phys" != "$script_root" ]; then
    _prune_skip "not this script's own clone"; return 0
  fi
  _is_registered_cron_root "$root_phys"; reg_rc=$?
  if [ "$reg_rc" -eq 2 ]; then
    _prune_skip "registry entry ${_registry_bad_key} does not resolve to a directory"; return 0
  fi
  if [ "$reg_rc" -eq 0 ]; then
    _prune_skip "clone is a registered worker/overseer root"; return 0
  fi
  if [ "$default_branch" != "main" ] || ! git rev-parse --verify -q refs/remotes/origin/main >/dev/null; then
    _prune_skip "default branch is not main"; return 0
  fi
  local tbin
  tbin="$(command -v timeout || command -v gtimeout || true)"
  if [ -z "$tbin" ]; then
    _prune_skip "no timeout(1) available"; return 0
  fi
  local secs="${HOS_REPO_SYNC_PRUNE_TIMEOUT_SECS:-}"
  if ! [[ "$secs" =~ ^[0-9]+$ ]] || [ "$secs" -le 0 ]; then
    secs=90
  fi
  local rc note="" line reaped=0 ev_re kind
  # Anchored (log-forging guard); same shape as bin/hos-cron's _RB_EVENT_RE.
  ev_re='^(REAPED|REAP-FAILED) branch=([A-Za-z0-9._/@+-]+) reason=([a-z-]+) where=(local|remote)( pr=(#[0-9]+|-))? tip=([0-9a-f]{40})$'
  # env -u / python -E -s: ignore caller-set PYTHONPATH and user site-packages, and
  # drop HOS_TOKEN_APP_ROLE so github.py cannot start a slow token re-mint. Not -P:
  # it drops the cwd that makes `-m scripts.*` importable.
  "$tbin" --kill-after=10 "$secs" env -u PYTHONPATH -u HOS_TOKEN_APP_ROLE \
      python3 -E -s -u -m scripts.automation.readopt \
      --repo "$root_phys" reap-orphans --local-only --grace-days 1 --max-deletions 25 \
      --no-issue-closed </dev/null 2>&1 \
    | {
        while IFS= read -r line || [ -n "$line" ]; do
          printf '%s\n' "hos-repo-sync: prune: $line"
          case "$line" in REAPED\ *) reaped=1 ;; esac
          if [[ "$line" =~ $ev_re ]] && [ "${BASH_REMATCH[4]}" = "local" ]; then
            kind="repo-sync-branch-reap"
            [ "${BASH_REMATCH[1]}" = "REAPED" ] || kind="repo-sync-branch-reap-failed"
            _prune_audit "$kind" "${BASH_REMATCH[2]}" "${BASH_REMATCH[3]}" "${BASH_REMATCH[4]}" \
              "${BASH_REMATCH[6]:--}" "${BASH_REMATCH[7]}"
          fi
        done
        if [ "$reaped" -eq 1 ]; then
          echo "hos-repo-sync: prune: recover a deleted branch with: git branch <name> <tip>  (or git fetch origin pull/<N>/head:<name>)"
        fi
      }
  rc="${PIPESTATUS[0]}"
  if [ "$rc" -ne 0 ]; then
    if [ "$rc" -eq 124 ] || [ "$rc" -eq 137 ]; then note=" (timeout)"; fi
    echo "hos-repo-sync: prune: WARN: readopt reap-orphans exited ${rc}${note} — branches were deleted only where a REAPED line appears above; sync result unaffected" >&2
  fi
  return 0
}

_prune_local_branches
exit "$sync_rc"
