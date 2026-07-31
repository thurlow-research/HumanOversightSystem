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

GREEN="\033[32m"; CYAN="\033[36m"; RED="\033[31m"; RESET="\033[0m"
ok()   { echo -e "  ${GREEN}✔${RESET}  $*" >&2; }
info() { echo -e "  ${CYAN}→${RESET}  $*" >&2; }
err()  { echo -e "  ${RED}✘${RESET}  $*" >&2; exit 1; }

BASE="origin/main"
BRANCH=""
MESSAGE_FILE=""
MODE="100644"
DRY_RUN=0
FILE_SPECS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --base)         BASE="$2"; shift 2 ;;
        --branch)       BRANCH="$2"; shift 2 ;;
        --message-file) MESSAGE_FILE="$2"; shift 2 ;;
        --mode)         MODE="$2"; shift 2 ;;
        --file)         FILE_SPECS+=("$2"); shift 2 ;;
        --dry-run)      DRY_RUN=1; shift ;;
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

git rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null \
    || err "base ref does not resolve to a commit: $BASE"

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
