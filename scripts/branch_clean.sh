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
#   with `git branch -D`. A branch that does not exist, or that is the one
#   currently checked out, is reported and skipped rather than aborting.
#
#   Untracked files ARE deleted — commit or stash anything worth keeping
#   first. Files ignored via .gitignore are preserved (`clean -fd`, not
#   `-fdx`), so local config such as .env survives.
#
# Prints each step as it runs, then a verification block:
#   git status --short                        — expect no output
#   git rev-list --count HEAD..origin/main    — behind; expect 0
#   git rev-list --count origin/main..HEAD    — ahead;  expect 0
#   git log --oneline -1

set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

# Reset BEFORE switching branches. `git checkout main` refuses to run when
# local modifications would be overwritten by the switch — which is exactly
# the state this script exists to repair, so doing it first makes the script
# abort on its own use case. `reset --hard` is also what clears the INDEX:
# `git checkout -- .` restores the working tree from the index and therefore
# leaves staged changes in place, so the tree would still be dirty at the
# verification step.
echo "==> git reset --hard HEAD (discard staged and unstaged tracked changes)"
git reset --hard HEAD

echo "==> git clean -fd (remove untracked files/dirs)"
git clean -fd

# Safe now: the tree is clean, so the switch has nothing to refuse to overwrite.
echo "==> git checkout main"
git checkout main

echo "==> git pull --ff-only origin main"
git pull --ff-only origin main

current_branch="$(git symbolic-ref --short HEAD)"
for branch in "$@"; do
  if [[ "$branch" == "$current_branch" ]]; then
    # git refuses to delete the checked-out branch; without this guard that
    # refusal aborts the whole script under `set -e`, after the destructive
    # steps have already run.
    echo "==> skip: '$branch' is the checked-out branch — cannot delete"
  elif git show-ref --verify --quiet "refs/heads/$branch"; then
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
# Both directions: behind-only would report 0 for a local main that is AHEAD of
# origin (unpushed commits), which reads as "synced" when it is not.
echo "-- git rev-list --count HEAD..origin/main (behind; expect 0)"
git rev-list --count HEAD..origin/main
echo "-- git rev-list --count origin/main..HEAD (ahead; expect 0)"
git rev-list --count origin/main..HEAD
echo "-- git log --oneline -1"
git log --oneline -1
