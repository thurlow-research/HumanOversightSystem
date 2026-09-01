#!/usr/bin/env bash
# bootstrap/hos_repo_sync.sh — fetch + fast-forward the current repo's default
# branch, but only if enough time has passed since the last sync.
#
# Usage:
#   bootstrap/hos_repo_sync.sh              # uses 900s (15 min) default interval
#   bootstrap/hos_repo_sync.sh 300           # custom interval in seconds
#   HOS_REPO_SYNC_STATE_DIR=... bootstrap/hos_repo_sync.sh   # override state dir
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
mv "$_tmpf" "$state_file"
