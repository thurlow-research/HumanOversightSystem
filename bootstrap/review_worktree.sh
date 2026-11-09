#!/usr/bin/env bash
# bootstrap/review_worktree.sh — the sanctioned way to get a PR's code locally
# WITHOUT creating a local branch (#2287, TD-2287 section 2).
#
# Why: nothing used to tell the overseer how to look at a PR head, so the model
# improvised pr-N / pr-N-review / pr-N-check branches that were never cleaned up.
# This script fetches refs/pull/<N>/head into FETCH_HEAD only (no local ref of any
# kind), pins it to the head SHA the verdict will be posted against, and checks it
# out as a DETACHED worktree under $TMPDIR. It never touches refs/heads.
#
# Usage (every form is one command with literal arguments):
#   bash bootstrap/review_worktree.sh --pr <N> --expect-sha <sha40> [--repo <path>]
#   bash bootstrap/review_worktree.sh --cleanup --pr <N> [--repo <path>]
#   bash bootstrap/review_worktree.sh --cleanup-all [--older-than-mins <M>] [--repo <path>]
#
# --pr prints exactly two stdout lines:  WORKTREE=<abs path>  and  HEAD=<sha40>
# --cleanup / --cleanup-all print, per review worktree:
#   REMOVED-WORKTREE pr=<N> path=<path>                         (stdout)
#   KEPT-WORKTREE pr=<N> path=<path> reason=head-moved          (stderr)
#
# Exit codes: 0 ok (cleanup modes: always, even when a removal failed — hygiene,
#   never a gate); 2 usage error / not a git repository; 3 fetch failed;
#   4 head-moved (the PR head no longer equals --expect-sha); 5 scratch location
#   refused (inside the repo, or /tmp/claude) or worktree creation failed.
#
# The script always operates on the MAIN worktree of the repository (derived from
# --git-common-dir), so running it from inside a review worktree never nests one.
# Re-running --pr for the same PR first removes the earlier review worktree.
set -uo pipefail

if [[ -t 2 ]]; then RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"; else RED=""; YELLOW=""; RESET=""; fi
err()  { echo -e "${RED}review_worktree: $*${RESET}" >&2; }
warn() { echo -e "${YELLOW}review_worktree: WARN: $*${RESET}" >&2; }

PR="" EXPECT="" REPO="." MODE="checkout" OLDER=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr)             [[ $# -ge 2 ]] || { err "--pr needs a value"; exit 2; }; PR="$2"; shift 2 ;;
    --expect-sha)     [[ $# -ge 2 ]] || { err "--expect-sha needs a value"; exit 2; }; EXPECT="$2"; shift 2 ;;
    --repo)           [[ $# -ge 2 ]] || { err "--repo needs a value"; exit 2; }; REPO="$2"; shift 2 ;;
    --older-than-mins) [[ $# -ge 2 ]] || { err "--older-than-mins needs a value"; exit 2; }; OLDER="$2"; shift 2 ;;
    --cleanup)        MODE="cleanup"; shift ;;
    --cleanup-all)    MODE="cleanup-all"; shift ;;
    -h|--help)        sed -n '2,29p' "$0"; exit 0 ;;
    *)                err "unknown argument: $1"; exit 2 ;;
  esac
done

[[ "$OLDER" =~ ^[0-9]{1,6}$ ]] || { err "--older-than-mins must be a non-negative integer"; exit 2; }
case "$MODE" in
  checkout)
    [[ "$PR" =~ ^[1-9][0-9]{0,6}$ ]] || { err "--pr must match ^[1-9][0-9]{0,6}\$"; exit 2; }
    [[ "$EXPECT" =~ ^[0-9a-f]{40}$ ]] || { err "--expect-sha is required and must be 40 lowercase hex chars"; exit 2; }
    ;;
  cleanup)
    [[ "$PR" =~ ^[1-9][0-9]{0,6}$ ]] || { err "--pr must match ^[1-9][0-9]{0,6}\$"; exit 2; }
    ;;
  cleanup-all)
    [[ -z "$PR" ]] || { err "--cleanup-all takes no --pr"; exit 2; }
    ;;
esac

# A5: always act on the main worktree, whatever worktree --repo / cwd is inside.
COMMON="$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" \
  || { err "not inside a git repository: $REPO"; exit 2; }
MAIN="$(dirname "$COMMON")"

# Remove the review worktrees selected by $1 (a PR number, or "" for all), honouring
# --older-than-mins. $2 is the file descriptor REMOVED-WORKTREE lines go to.
cleanup_worktrees() {
  local only="$1" out_fd="$2" path="" head="" detached=0 line
  local -a paths=() heads=() dets=()
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      "worktree "*) [[ -n "$path" ]] && { paths+=("$path"); heads+=("$head"); dets+=("$detached"); }
                    path="${line#worktree }"; head=""; detached=0 ;;
      "HEAD "*)     head="${line#HEAD }" ;;
      detached)     detached=1 ;;
    esac
  done < <(git -C "$MAIN" worktree list --porcelain 2>/dev/null)
  [[ -n "$path" ]] && { paths+=("$path"); heads+=("$head"); dets+=("$detached"); }

  local i digits scratch expected
  for i in "${!paths[@]}"; do
    path="${paths[$i]}"
    [[ "$path" == "$MAIN" ]] && continue
    [[ "${dets[$i]}" == 1 ]] || continue
    [[ "$path" =~ ^(.*)/(hos-review-pr([0-9]+)\.[A-Za-z0-9]{6,})/wt$ ]] || continue
    scratch="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
    digits="${BASH_REMATCH[3]}"
    [[ -z "$only" || "$digits" == "$only" ]] || continue
    # A directory the reaper already deleted is cleared by the prune below.
    [[ -d "$path" ]] || continue
    if (( OLDER > 0 )) && [[ -n "$(find "$scratch" -maxdepth 0 -mmin "-$OLDER" 2>/dev/null)" ]]; then
      continue
    fi
    # A3: a moved HEAD means a commit was made here; removal would orphan it.
    expected="$(cat "$scratch/expected-head" 2>/dev/null || true)"
    if [[ -z "$expected" || "$expected" != "${heads[$i]}" ]]; then
      echo "KEPT-WORKTREE pr=$digits path=$path reason=head-moved" >&2
      continue
    fi
    if git -C "$MAIN" worktree remove --force "$path" >/dev/null 2>&1; then
      rm -rf -- "$scratch"
      echo "REMOVED-WORKTREE pr=$digits path=$path" >&"$out_fd"
    else
      warn "could not remove worktree $path"
    fi
  done
  git -C "$MAIN" worktree prune >/dev/null 2>&1 || true
}

case "$MODE" in
  cleanup)     cleanup_worktrees "$PR" 1; exit 0 ;;
  cleanup-all) cleanup_worktrees "" 1; exit 0 ;;
esac

# A6: refuse a scratch root inside the repo (validators and git status would scan it)
# or under /tmp/claude (small command artifacts only).
ROOT="$(realpath -m -- "${TMPDIR:-/tmp}")"
if [[ "$ROOT" == "$MAIN" || "$ROOT" == "$MAIN"/* || "$ROOT" == /tmp/claude || "$ROOT" == /tmp/claude/* ]]; then
  err "refusing scratch root '$ROOT' (inside the repository or /tmp/claude); set TMPDIR to a directory outside the repository"
  exit 5
fi

# Idempotent: at most one review worktree per PR (cleanup chatter goes to stderr so
# stdout stays exactly the two result lines).
cleanup_worktrees "$PR" 2

# Bounded and hardened (#2287 review): a hung network must not stall the cycle; no
# credential prompt, no LFS smudge, objects fsck'd. Unbounded only if neither timeout
# nor gtimeout exists (as bin/hos-cron does).
BOUND=()
if command -v timeout >/dev/null 2>&1; then BOUND=(timeout --kill-after=5 120)
elif command -v gtimeout >/dev/null 2>&1; then BOUND=(gtimeout --kill-after=5 120); fi
FETCH_ERR="$(GIT_TERMINAL_PROMPT=0 GIT_LFS_SKIP_SMUDGE=1 ${BOUND[@]+"${BOUND[@]}"} \
  git -C "$MAIN" -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 -c transfer.fsckObjects=true \
  fetch --no-tags --no-recurse-submodules --refmap= --quiet origin "refs/pull/$PR/head" 2>&1 >/dev/null)"
FETCH_RC=$?
if (( FETCH_RC != 0 )); then
  if (( FETCH_RC == 124 || FETCH_RC == 137 )); then
    err "fetch of refs/pull/$PR/head timed out"
  else
    # One redacted, truncated line of git's own reason (never a credential).
    REASON="$(printf '%s\n' "$FETCH_ERR" | sed -E 's#://[^/@[:space:]]*@#://***@#g; s#gh[pousr]_[A-Za-z0-9_]+#***#g' \
      | LC_ALL=C tr -d '\000-\010\013-\037\177' | grep -v '^$' | head -n 1 | cut -c1-200)"
    err "fetch of refs/pull/$PR/head failed${REASON:+: $REASON}"
  fi
  exit 3
fi
FETCHED="$(git -C "$MAIN" rev-parse --verify --quiet 'FETCH_HEAD^{commit}' 2>/dev/null || true)"
if [[ "$FETCHED" != "$EXPECT" ]]; then
  err "head-moved: PR #$PR head is ${FETCHED:-unknown}, expected $EXPECT; re-read head_sha and start again"
  exit 4
fi

SCRATCH="$(mktemp -d "$ROOT/hos-review-pr$PR.XXXXXX" 2>/dev/null)" \
  || { err "could not create a scratch directory under $ROOT"; exit 5; }
if ! echo "$EXPECT" > "$SCRATCH/expected-head" \
   || ! GIT_LFS_SKIP_SMUDGE=1 git -C "$MAIN" -c core.hooksPath=/dev/null worktree add --detach --quiet "$SCRATCH/wt" "$EXPECT" >/dev/null 2>&1; then
  rm -rf -- "$SCRATCH"
  git -C "$MAIN" worktree prune >/dev/null 2>&1 || true
  err "could not create the review worktree for PR #$PR"
  exit 5
fi
echo "WORKTREE=$SCRATCH/wt"
echo "HEAD=$EXPECT"
