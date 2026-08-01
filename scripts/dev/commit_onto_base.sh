#!/usr/bin/env bash
# scripts/dev/commit_onto_base.sh — commit files onto a base ref without a checkout
#
# WHY THIS EXISTS
# Protected surfaces (scripts/framework/protected_surfaces.txt) are mounted
# read-only in the sandboxed Human clone. `git checkout <branch>` fails with
# EROFS partway through when the target tree differs in any protected path,
# leaving the index desynced from the working tree. That makes the ordinary
# "branch → edit → commit" flow unusable for changes to CLAUDE.md,
# .claude/agents/**, contract/**, bootstrap/**, or bin/**.
#
# This script builds the commit with plumbing instead: a temporary index seeded
# from the base ref, blobs hashed straight from files on disk, and a commit
# written with git commit-tree. The working tree is never touched, so no
# read-only path is ever written and the caller's checkout stays clean.
#
# It also exists because hand-rolling this inline produces commands no
# permission rule can match — `GIT_INDEX_FILE=... git ...` does not start with
# `git`, and capturing blob hashes needs command substitution. Both prompt every
# time, and on Worker/Overseer a prompt is a hang. See CLAUDE.md, "Shell usage
# under the sandbox": recurring logic belongs in a committed script, reviewed
# once, invoked statically.
#
# USAGE
#   scripts/dev/commit_onto_base.sh \
#       --base origin/main \
#       --branch docs/my-change \
#       --message-file /tmp/claude/commit-msg.txt \
#       --file <repo-path>=<source-path> [--file ...]
#
#   --base          ref the commit is parented on (default: origin/main)
#   --branch        branch to create/move to the new commit (required)
#   --message-file  file containing the full commit message (required)
#   --file          repo-path=source-path, repeatable (at least one required).
#                   repo-path is the path inside the tree; source-path is the
#                   edited file on disk.
#   --mode          file mode for added blobs (default: 100644)
#   --dry-run       build and report the tree, but do not create the commit
#
# Prints the new commit SHA on stdout. Diagnostics go to stderr.
#
# Deliberately NOT included: pushing, or opening a PR. Those need credentials
# and belong in bootstrap/submit_pr.sh (#1085).

set -euo pipefail

GREEN="\033[32m"; CYAN="\033[36m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*" >&2; }
info() { echo -e "  ${CYAN}→${RESET}  $*" >&2; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $*" >&2; }
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }

BASE="origin/main"
BRANCH=""
MESSAGE_FILE=""
MODE="100644"
DRY_RUN=0
ALLOW_DELETIONS=0
NO_FETCH=0
COMPARE_TO="origin/main"
FILE_SPECS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --base)         BASE="$2"; shift 2 ;;
        --branch)       BRANCH="$2"; shift 2 ;;
        --message-file) MESSAGE_FILE="$2"; shift 2 ;;
        --mode)         MODE="$2"; shift 2 ;;
        --file)         FILE_SPECS+=("$2"); shift 2 ;;
        --dry-run)      DRY_RUN=1; shift ;;
        --allow-deletions) ALLOW_DELETIONS=1; shift ;;
        --no-fetch)     NO_FETCH=1; shift ;;
        --compare-to)   COMPARE_TO="$2"; shift 2 ;;
        -h|--help)      sed -n '2,45p' "$0"; exit 0 ;;
        *)              err "unknown argument: $1" ;;
    esac
done

[[ -n "$BRANCH" ]]                || err "--branch is required"
[[ -n "$MESSAGE_FILE" ]]          || err "--message-file is required"
[[ -f "$MESSAGE_FILE" ]]          || err "message file not found: $MESSAGE_FILE"
[[ -s "$MESSAGE_FILE" ]]          || err "message file is empty: $MESSAGE_FILE"
[[ ${#FILE_SPECS[@]} -gt 0 ]]     || err "at least one --file is required"
[[ "$MODE" =~ ^100(644|755)$ ]]   || err "--mode must be 100644 or 100755, got: $MODE"

# ── Staleness guard (#1162) ───────────────────────────────────────────────────
# A stale base is the failure this guard exists for: if the local remote-tracking
# ref is behind the real remote, the tree seeded from it LACKS whatever landed in
# between, and the resulting commit proposes DELETING that work. The PR looks
# entirely normal. Observed 2026-08-01: a branch built this way would have
# reverted four merged PRs (6,114 deletions), caught only by manual inspection.
#
# So: refresh the remote-tracking ref before reading it. Cheap, and it removes
# the most common way to get a stale base.
if [[ "$BASE" == origin/* ]] && (( ! NO_FETCH )); then
    _remote_branch="${BASE#origin/}"
    info "fetching origin/${_remote_branch} to ensure the base is current (--no-fetch to skip)..."
    # Non-fatal: an offline run should still work off the last known ref, but say so.
    git fetch --quiet origin "$_remote_branch" 2>/dev/null \
        || warn "fetch failed — proceeding with the local ref, which may be STALE"
fi

git rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null \
    || err "base ref does not resolve to a commit: $BASE"

# The actual staleness test: does the upstream target contain commits the base
# does not? If so, the tree seeded from BASE LACKS that work, and committing it
# proposes reverting it.
#
# Note this cannot be detected by diffing BASE against the resulting tree — the
# base IS the stale thing, so that diff looks perfectly clean. It has to be
# compared against the real upstream target.
if ! git rev-parse --verify --quiet "${COMPARE_TO}^{commit}" >/dev/null; then
    # Fail loudly rather than silently skipping the guard — a skipped staleness
    # check is exactly the fail-open this exists to prevent.
    warn "staleness guard SKIPPED: --compare-to ref '${COMPARE_TO}' does not resolve."
    warn "  Pass --compare-to <ref> to enable it (e.g. the branch this will be PR'd against)."
else
    _behind="$(git rev-list --count "${BASE}..${COMPARE_TO}" 2>/dev/null || echo 0)"
    if (( _behind > 0 )) && (( ALLOW_DELETIONS )); then
        warn "base is ${_behind} commit(s) behind ${COMPARE_TO} — proceeding because --allow-deletions was given"
    elif (( _behind > 0 )); then
        err "STALE BASE — '${BASE}' is ${_behind} commit(s) behind ${COMPARE_TO}.

A tree built on this base is missing that work, so the resulting commit would
propose REVERTING it. The PR would look entirely normal. (Observed 2026-08-01:
this exact shape would have reverted four merged PRs — 6,114 deletions.)

Missing commits (newest first):
$(git log --oneline -5 "${BASE}..${COMPARE_TO}" | sed 's/^/    /')$( (( _behind > 5 )) && printf '\n    ... and %d more' "$(( _behind - 5 ))" )

Fix: rebuild against a current base — usually '--base ${COMPARE_TO}'. If a
feature branch was passed as --base, that branch is itself stale and needs the
target merged into it first.

--compare-to <ref> changes the target; --allow-deletions overrides (rarely right)."
    fi
fi

# Fail closed on a branch that already exists at an unrelated commit: moving it
# silently would discard work. Require it to be absent, or an ancestor of BASE.
if git rev-parse --verify --quiet "refs/heads/${BRANCH}" >/dev/null; then
    if ! git merge-base --is-ancestor "$BRANCH" "$BASE" 2>/dev/null; then
        err "branch '$BRANCH' exists and is not an ancestor of $BASE — refusing to move it. Delete it first if that is intended."
    fi
    info "branch '$BRANCH' exists and is an ancestor of $BASE — will fast-forward it"
fi

INDEX_FILE="$(mktemp -t hos-commit-idx.XXXXXX)"
trap 'rm -f "$INDEX_FILE"' EXIT

info "seeding temporary index from ${BASE}..."
GIT_INDEX_FILE="$INDEX_FILE" git read-tree "$BASE"

for spec in "${FILE_SPECS[@]}"; do
    repo_path="${spec%%=*}"
    src_path="${spec#*=}"

    [[ "$spec" == *"="* ]]     || err "--file must be repo-path=source-path, got: $spec"
    [[ -n "$repo_path" ]]      || err "empty repo-path in: $spec"
    [[ -n "$src_path" ]]       || err "empty source-path in: $spec"
    [[ -f "$src_path" ]]       || err "source file not found: $src_path"
    [[ "$repo_path" != /* ]]   || err "repo-path must be relative to the repo root, got: $repo_path"
    [[ "$repo_path" != *".."* ]] || err "repo-path must not contain '..': $repo_path"

    blob="$(git hash-object -w "$src_path")"
    GIT_INDEX_FILE="$INDEX_FILE" git update-index --add --cacheinfo "${MODE},${blob},${repo_path}"
    ok "staged ${repo_path}  (${blob:0:12})"
done

TREE="$(GIT_INDEX_FILE="$INDEX_FILE" git write-tree)"
info "tree: $TREE"

BASE_TREE="$(git rev-parse "${BASE}^{tree}")"
if [[ "$TREE" == "$BASE_TREE" ]]; then
    err "tree is identical to $BASE — the source files match what is already committed. Nothing to do."
fi

echo "" >&2
git diff --stat "$BASE" "$TREE" >&2
echo "" >&2

if (( DRY_RUN )); then
    ok "dry run — tree $TREE built, no commit created"
    echo "$TREE"
    exit 0
fi

COMMIT="$(git commit-tree "$TREE" -p "$BASE" -F "$MESSAGE_FILE")"
git branch -f "$BRANCH" "$COMMIT"

ok "committed ${COMMIT:0:12} onto ${BASE}, branch '${BRANCH}'"
echo "$COMMIT"
