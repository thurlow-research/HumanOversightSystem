"""
Pre-PR stale-commit guard (#850).

Detects commits on a branch that are already present in main or in an open
PR before the worker pushes and opens a PR.  This prevents the stacked-branch
problem where a worker branches off an in-progress fix, both get PRs, the fix
merges first, and the worker's PR is left with duplicate commits and conflicts.

Usage (call before `git push && gh pr create`):
    from scripts.automation.lib.stale_commit_detector import check_stale_commits

    result = check_stale_commits(owner, repo, branch="feat/my-fix-850")
    if not result.is_clean:
        # strip commits already in main, then re-check
        if strip_redundant_commits():
            result = check_stale_commits(owner, repo, branch="feat/my-fix-850")
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from scripts.automation.lib.cycle_log import log_event
from scripts.automation.lib.github import GitHubError, _run_gh

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class StaleCommitResult:
    """Result of a pre-PR stale-commit check."""
    branch: str
    base: str
    all_commits: list[str]
    redundant_in_main: list[str]
    redundant_in_prs: dict[str, list[str]]  # {str(pr_number): [sha, ...]}

    @property
    def is_clean(self) -> bool:
        return not self.redundant_in_main and not self.redundant_in_prs

    @property
    def all_redundant(self) -> list[str]:
        seen: set[str] = set()
        result = []
        for sha in self.redundant_in_main:
            if sha not in seen:
                seen.add(sha)
                result.append(sha)
        for shas in self.redundant_in_prs.values():
            for sha in shas:
                if sha not in seen:
                    seen.add(sha)
                    result.append(sha)
        return result


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run_git(args: list[str], input: Optional[str] = None) -> str:
    """Run a git command and return stdout. Raises RuntimeError on failure."""
    result = subprocess.run(
        ["git"] + args,
        input=input,
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def get_branch_commits(base: str = "main", head: str = "HEAD") -> list[str]:
    """
    Return SHAs of commits reachable from head but not from base, oldest first.

    These are the commits that would appear in a PR from head targeting base.
    Returns an empty list when head is already up-to-date with base.
    """
    output = _run_git(["log", "--format=%H", "--reverse", f"{base}..{head}"])
    return output.splitlines() if output else []


def find_redundant_in_main(base: str = "main", head: str = "HEAD") -> list[str]:
    """
    Return SHAs of commits on head whose patch-id is already applied in base.

    `git cherry base head` marks each commit:
      `-`  already applied (same patch-id as something in base) — redundant
      `+`  not yet in base — unique

    Only commits marked `-` are returned.  An empty list means the branch
    has no commits already absorbed by base.
    """
    result = subprocess.run(
        ["git", "cherry", base, head],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git cherry {base} {head} failed (rc={result.returncode}): "
            f"{result.stderr.strip()} — cannot determine which commits are already in {base}"
        )

    redundant = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("- "):
            redundant.append(line[2:].strip())
    return redundant


def find_redundant_in_open_prs(
    owner: str,
    repo: str,
    branch_commit_shas: list[str],
    current_branch: Optional[str] = None,
    bot_login: str = "hos-worker-hos[bot]",
) -> dict[str, list[str]]:
    """
    Find commits in branch_commit_shas whose SHA appears in another open PR.

    SHA equality is the right test for the stacked-branch case: when a worker
    builds a branch on top of an in-flight fix, the fix's commits appear in
    both branches with the *same SHA*.  This catches that case without needing
    any local fetch of the remote branches.

    Returns a dict mapping str(pr_number) to the subset of branch_commit_shas
    whose SHAs appear in that PR's commits.  Skips the bot's own PRs and any
    PR whose head branch matches current_branch.  API errors are logged and
    silently skipped — this check is best-effort.
    """
    if not branch_commit_shas:
        return {}

    our_sha_set = set(branch_commit_shas)
    redundant_by_pr: dict[str, list[str]] = {}

    try:
        open_prs = _run_gh([f"/repos/{owner}/{repo}/pulls?state=open&per_page=100"])
    except GitHubError as exc:
        logger.warning("Could not list open PRs for stale-commit check: %s", exc)
        return {}

    if not open_prs:
        return {}

    if not isinstance(open_prs, list):
        logger.warning(
            "Unexpected type from PR listing API: %s — skipping open-PR stale check",
            type(open_prs).__name__,
        )
        return {}

    for pr in open_prs:
        pr_number = pr.get("number")
        if pr_number is None:
            continue
        if pr.get("user", {}).get("login", "") == bot_login:
            continue
        if current_branch and pr.get("head", {}).get("ref", "") == current_branch:
            continue

        try:
            pr_commits = _run_gh(
                [f"/repos/{owner}/{repo}/pulls/{pr_number}/commits?per_page=100"]
            ) or []
        except GitHubError as exc:
            logger.warning("Could not fetch commits for PR #%s: %s", pr_number, exc)
            continue

        if not isinstance(pr_commits, list):
            logger.warning(
                "Unexpected commits response for PR #%s: got %s — skipping",
                pr_number,
                type(pr_commits).__name__,
            )
            continue

        overlap = [
            c.get("sha", "")
            for c in pr_commits
            if c.get("sha", "") in our_sha_set
        ]
        if overlap:
            redundant_by_pr[str(pr_number)] = overlap

    return redundant_by_pr


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def check_stale_commits(
    owner: str,
    repo: str,
    branch: str,
    base: str = "main",
    head: str = "HEAD",
    bot_login: str = "hos-worker-hos[bot]",
    check_open_prs: bool = True,
) -> StaleCommitResult:
    """
    Pre-PR guard: detect commits that are already present in base or open PRs.

    Call this before `git push && gh pr create`.  If the result is not clean,
    call strip_redundant_commits() to rebase away the redundant commits, then
    re-check before pushing.

    Audit log event `pre-pr-stale-commits` is emitted when redundant commits
    are found, so every detection is traceable in audit/oversight-log.jsonl.
    """
    all_commits = get_branch_commits(base=base, head=head)
    redundant_in_main = find_redundant_in_main(base=base, head=head)

    redundant_in_prs: dict[str, list[str]] = {}
    if check_open_prs and all_commits:
        redundant_in_prs = find_redundant_in_open_prs(
            owner, repo, all_commits,
            current_branch=branch,
            bot_login=bot_login,
        )

    result = StaleCommitResult(
        branch=branch,
        base=base,
        all_commits=all_commits,
        redundant_in_main=redundant_in_main,
        redundant_in_prs=redundant_in_prs,
    )

    if not result.is_clean:
        logger.warning(
            "Stale commits detected on %s before PR open: "
            "redundant_in_main=%s redundant_in_prs=%s",
            branch,
            redundant_in_main,
            {k: v for k, v in redundant_in_prs.items()},
        )
        log_event(
            "pre-pr-stale-commits",
            branch=branch,
            base=base,
            redundant_in_main=redundant_in_main,
            redundant_in_prs={k: v for k, v in redundant_in_prs.items()},
        )

    return result


def strip_redundant_commits(base: str = "main") -> bool:
    """
    Drop commits already present in base by rebasing HEAD onto base.

    Git rebase uses patch-id matching to skip commits whose diffs are already
    applied upstream, so commits marked redundant by find_redundant_in_main()
    will be silently dropped.  Safe to call when there are no redundant commits;
    the rebase simply fast-forwards.

    Returns True on success, False if the rebase fails (e.g. conflicts — the
    caller should abort with `git rebase --abort` and escalate to a human).
    """
    try:
        _run_git(["rebase", base])
        logger.info("Rebased onto %s: redundant commits stripped", base)
        return True
    except RuntimeError as exc:
        logger.error("Rebase onto %s failed — run `git rebase --abort`: %s", base, exc)
        return False
