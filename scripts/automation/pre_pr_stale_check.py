#!/usr/bin/env python3
"""pre_pr_stale_check.py — CLI wrapper for the pre-PR stale-commit guard (#850).

Run this before `git push && gh pr create` to detect commits that are already
present in main or in another open PR.

Behaviour:
  1. Runs check_stale_commits() against the current branch.
  2. If clean: prints a confirmation and exits 0.
  3. If only redundant-in-main commits are found: calls strip_redundant_commits()
     to rebase them away, then re-checks.  Exits 0 if now clean, 1 if the rebase
     failed or commits remain.
  4. If commits overlap an open PR: prints a warning and exits 1.  These cannot
     be auto-resolved — the caller must cherry-pick unique commits onto a fresh
     branch (or wait for the conflicting PR to merge).

Usage:
  cd "$REPO_ROOT"
  python scripts/automation/pre_pr_stale_check.py [--owner ORG] [--repo NAME] \\
                                                    [--branch BRANCH] [--base BASE]

  --owner / --repo default to values parsed from `git remote get-url origin`.
  --branch defaults to the current branch (git rev-parse --abbrev-ref HEAD).
  --base defaults to "main".

Exit codes:
  0 — branch is clean (or was made clean by auto-rebase)
  1 — stale commits remain; do NOT push or open a PR
  2 — usage / configuration error
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

from scripts.automation.lib.stale_commit_detector import (
    check_stale_commits,
    strip_redundant_commits,
)


def _run(args: list[str]) -> str:
    """Run a subprocess and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def parse_remote_url(url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a git remote URL.

    Handles HTTPS and SSH forms:
      https://github.com/owner/repo.git
      https://github.com/owner/repo
      git@github.com:owner/repo.git
    """
    m = re.search(r"github\.com[/:]([^/]+)/([^/.]+?)(?:\.git)?$", url)
    if m:
        return m.group(1), m.group(2)
    raise ValueError(f"Cannot parse GitHub owner/repo from remote URL: {url!r}")


def resolve_owner_repo(owner: str | None, repo: str | None) -> tuple[str, str]:
    if owner and repo:
        return owner, repo
    try:
        url = _run(["git", "remote", "get-url", "origin"])
    except RuntimeError as exc:
        print(
            f"pre-pr-stale-check: cannot resolve owner/repo from git remote: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        return parse_remote_url(url)
    except ValueError as exc:
        print(f"pre-pr-stale-check: {exc}", file=sys.stderr)
        sys.exit(2)


def resolve_branch(branch: str | None) -> str:
    if branch:
        return branch
    try:
        return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    except RuntimeError as exc:
        print(
            f"pre-pr-stale-check: cannot determine current branch: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)


def run_check(owner: str, repo: str, branch: str, base: str) -> int:
    """Perform the stale-commit check and auto-strip if possible.

    Returns 0 on clean, 1 if stale commits cannot be resolved.
    """
    result = check_stale_commits(owner, repo, branch=branch, base=base)

    if result.is_clean:
        print(f"✔ pre-pr-stale-check: branch {branch!r} is clean — no stale commits.")
        return 0

    if result.redundant_in_main:
        print(
            f"⚠ pre-pr-stale-check: {len(result.redundant_in_main)} commit(s) on "
            f"{branch!r} already present in {base}:"
        )
        for sha in result.redundant_in_main:
            print(f"    {sha[:12]}")

    if result.redundant_in_prs:
        for pr_num, shas in result.redundant_in_prs.items():
            print(
                f"⚠ pre-pr-stale-check: {len(shas)} commit(s) also appear in open "
                f"PR #{pr_num}:",
                file=sys.stderr,
            )
            for sha in shas:
                print(f"    {sha[:12]}", file=sys.stderr)
        print(
            "\n✘ pre-pr-stale-check: commits overlap an open PR — cannot auto-resolve.\n"
            "  Cherry-pick unique commits onto a fresh branch from main, or wait\n"
            "  for the conflicting PR to merge first.",
            file=sys.stderr,
        )
        return 1

    # Only redundant-in-main: attempt auto-strip via rebase
    print(f"  Attempting auto-rebase onto {base} to drop stale commits…")
    if not strip_redundant_commits(base=base):
        print(
            f"\n✘ pre-pr-stale-check: rebase onto {base} failed.\n"
            "  Run `git rebase --abort` then rebase manually before opening a PR.",
            file=sys.stderr,
        )
        return 1

    result2 = check_stale_commits(owner, repo, branch=branch, base=base)
    if result2.is_clean:
        print(
            f"✔ pre-pr-stale-check: rebase succeeded — branch {branch!r} is now clean."
        )
        return 0

    print(
        f"\n✘ pre-pr-stale-check: stale commits remain after rebase on {branch!r}.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-PR stale-commit guard")
    ap.add_argument("--owner", help="GitHub org/user (default: parsed from git remote)")
    ap.add_argument("--repo", help="GitHub repo name (default: parsed from git remote)")
    ap.add_argument("--branch", help="Branch to check (default: current branch)")
    ap.add_argument("--base", default="main", help="Base branch (default: main)")
    args = ap.parse_args()

    owner, repo = resolve_owner_repo(args.owner, args.repo)
    branch = resolve_branch(args.branch)
    return run_check(owner, repo, branch=branch, base=args.base)


if __name__ == "__main__":
    sys.exit(main())
