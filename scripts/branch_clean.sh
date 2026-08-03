#!/usr/bin/env bash
# scripts/branch_clean.sh — reset the Human clone to a clean, synced main
#
# WHY THIS EXISTS
# A session can leave the working tree in a state that git pull --ff-only
# won't recover from on its own: tracked-file modifications from a partial
# pull (some paths under the Human sandbox's read-only protected surfaces
# can fail to update mid-pull, e.g. .claude/agents/**, bin/**), untracked
# debris, and/or a stray local branch cut from a stale HEAD while
# recovering. This script is the repair sequence for that state, generalized
# from a one-off recovery run on 2026-08-03.
#
# RUN THIS OUTSIDE THE SANDBOX, IN YOUR OWN SHELL — not via Claude Code.
# It is destructive by design (discards uncommitted changes, deletes
# untracked files, force-deletes a branch) and CLAUDE.md's "Executing
# actions with care" section asks for exactly this kind of operation to be
# confirmed by a human directly rather than run unattended.
#
# USAGE
#   scripts/branch_clean.sh [branch-to-delete ...]
#
#   With no arguments, only resets the working tree and syncs main — no
#   branch is deleted. Any branch names passed as arguments are force-deleted
#   with `git branch -D` (a no-op, reported, if the branch doesn't exist).
#
# Prints each step as it runs, then a verification block:
#   git status --short                       — expect no output
#   git rev-list --count HEAD..origin/main    — expect 0
#   git log --oneline -1

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

echo "==> git checkout main"
git checkout main

echo "==> git checkout -- . (discard uncommitted changes to tracked files)"
git checkout -- .

echo "==> git clean -fd (remove untracked files/dirs)"
git clean -fd

echo "==> git pull --ff-only origin main"
git pull --ff-only origin main

for branch in "$@"; do
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    echo "==> git branch -D $branch"
    git branch -D "$branch"
  else
    echo "==> skip: local branch '$branch' does not exist"
  fi
done

echo
echo "==> Verify"
echo "-- git status --short (expect no output)"
git status --short
echo "-- git rev-list --count HEAD..origin/main (expect 0)"
git rev-list --count HEAD..origin/main
echo "-- git log --oneline -1"
git log --oneline -1
