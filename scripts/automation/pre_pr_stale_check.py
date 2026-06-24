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
  5. Checks that audit-only files (audit/oversight-log.jsonl,
     audit/overnight-loop-log.md) are NOT committed to a non-main branch (#880).
     These files are gitignored and must only reach main via the audit-log sync
     workflow, never via a feature PR.

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

# Files that must NEVER appear in feature/fix branch commits (#880).
# These are gitignored append-only operational files synced to main via GitHub
# Actions (introduced in #861). Committing them to a feature branch shifts PR
# HEAD past the validator artifact commit and breaks the overseer's §3b check.
_AUDIT_ONLY_FILES: frozenset[str] = frozenset({
    "audit/oversight-log.jsonl",
    "audit/overnight-loop-log.md",
})


def _run(args: list[str]) -> str:
    """Run a subprocess and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def check_audit_log_not_committed(branch: str, base: str = "main") -> list[str]:
    """Return violation messages if audit-only files are committed on this branch.

    Audit-only files (audit/oversight-log.jsonl, audit/overnight-loop-log.md)
    are gitignored and must never be committed to a feature/fix branch (#880).
    They reach main exclusively via the audit-log GitHub Actions sync workflow.

    When on `main` itself, this check is skipped (returns []).

    The check compares against `origin/{base}` (not local `{base}`) so a stale
    local branch doesn't produce false positives when `origin/main` has advanced
    past the local `main` ref. Falls back to `{base}` if `origin/{base}` is
    not available (e.g., no remote configured).

    Returns a list of human-readable violation strings; empty means clean.
    """
    if branch in (base, "main"):
        return []

    # Prefer origin/{base} so local-main staleness doesn't cause false positives.
    base_ref = f"origin/{base}"
    try:
        _run(["git", "rev-parse", "--verify", base_ref])
    except RuntimeError:
        base_ref = base  # fallback: no remote available

    try:
        changed = _run(["git", "diff", "--name-only", f"{base_ref}...{branch}"])
    except RuntimeError:
        return []

    changed_files = set(changed.splitlines()) if changed else set()
    violations = sorted(_AUDIT_ONLY_FILES & changed_files)
    return [
        f"audit-only file committed to feature branch: {f!r} — "
        "must not be committed to non-main branches (#880); "
        "remove from last commit with: git reset HEAD~1 -- " + f
        for f in violations
    ]


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
    # Audit-log guard (#880): fail before stale check if audit-only files
    # have been committed to this branch — they invalidate the overseer's §3b
    # head_sha check and must never appear in a feature PR.
    audit_violations = check_audit_log_not_committed(branch, base)
    if audit_violations:
        for v in audit_violations:
            print(f"✘ pre-pr-stale-check: {v}", file=sys.stderr)
        print(
            "\n✘ pre-pr-stale-check: audit-only files committed to feature branch.\n"
            "  These files are gitignored and must only reach main via the\n"
            "  audit-log GitHub Actions sync (introduced in #861).\n"
            "  Drop the audit commit before opening a PR.",
            file=sys.stderr,
        )
        return 1

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
        f"\n✘ pre-pr-stale-check: stale commits remain after rebase on {branch!r}:",
        file=sys.stderr,
    )
    for sha in result2.redundant_in_main:
        print(f"    still-in-{base}: {sha[:12]}", file=sys.stderr)
    for pr_num, shas in result2.redundant_in_prs.items():
        for sha in shas:
            print(f"    still-in-PR #{pr_num}: {sha[:12]}", file=sys.stderr)
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
