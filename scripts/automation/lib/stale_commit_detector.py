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
        # never strip/push when result.open_prs_unverified is set (#1681);
        # otherwise strip commits already in main, then re-check
        if strip_redundant_commits():
            result = check_stale_commits(owner, repo, branch="feat/my-fix-850")
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from scripts.automation.lib.cycle_log import log_event
from scripts.automation.lib.github import GitHubError, _run_gh

logger = logging.getLogger(__name__)


class OpenPrsUnverifiedError(Exception):
    """The open-PR overlap check could not be completed (#1681).

    Deliberately NOT a GitHubError subclass: callers that catch GitHubError to
    degrade gracefully must not accidentally swallow a failed hard gate.
    """


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
    # Reason the open-PR overlap check could not be completed (#1681); None
    # means it ran to completion (or was not requested).
    open_prs_unverified: Optional[str] = None

    @property
    def is_clean(self) -> bool:
        """True only when nothing is redundant AND the check was fully verified."""
        return (
            not self.redundant_in_main
            and not self.redundant_in_prs
            and self.open_prs_unverified is None
        )

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
        capture_output=True,
        text=True,
        check=False,
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
        capture_output=True,
        text=True,
        check=False,
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


_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_MAX_REASON_LEN = 300


def sanitize_reason(text: str, limit: int = _MAX_REASON_LEN) -> str:
    """Make untrusted text safe for a log line / event field / stderr (CWE-117).

    Strips ANSI escape sequences, turns remaining control characters (newlines
    included) into single spaces, collapses whitespace, and truncates to
    ``limit`` characters with an ellipsis marker.
    """
    text = _ANSI_RE.sub("", str(text))
    text = " ".join(_CONTROL_RE.sub(" ", text).split())
    if len(text) > limit:
        text = text[: limit - 1] + "\u2026"
    return text


def _github_error_text(exc: GitHubError) -> str:
    """Message plus status code of a GitHubError, without the tuple repr."""
    message = exc.args[0] if exc.args else str(exc)
    status = getattr(exc, "status_code", None)
    return f"{message} (HTTP {status})" if status is not None else str(message)


def _unverified(reason: str) -> OpenPrsUnverifiedError:
    reason = sanitize_reason(reason)
    logger.warning("Open-PR stale-commit check unverifiable: %s", reason)
    return OpenPrsUnverifiedError(reason)


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
    whose SHAs appear in that PR's commits.  Skips only the PR whose head branch
    matches current_branch — the branch under check, whose own already-pushed
    commits are not "stale" against itself.  Both the open-PR listing and each
    PR's commit list are fully paginated so a large PR backlog (or a PR with
    >100 commits) is never silently truncated.

    Fail-closed (#1681): this check backs a hard gate, so "could not check" must
    never read as "no overlap".  OpenPrsUnverifiedError is raised at the FIRST
    failure — a GitHubError (incl. RateLimitError) on any listing, a None
    response (_run_gh returns None on HTTP 404 or an empty body; only a real
    ``[]`` means "no more items"), a non-list response, a PR entry that is not a
    dict or lacks ``number``, or a commit entry that is not a dict or lacks
    ``sha``.  Other exception types propagate unchanged.

    bot_login is retained for backward compatibility but no longer suppresses
    detection (#987): in autonomous mode *every* open PR is bot-authored, so the
    old bot-login skip made this guard a no-op against the worker's own stacked
    branches — exactly the scenario #850 built it for.  The current_branch guard
    already excludes the branch under check, so the bot-login skip was redundant
    at best and blinding at worst.
    """
    if not branch_commit_shas:
        return {}

    our_sha_set = set(branch_commit_shas)
    redundant_by_pr: dict[str, list[str]] = {}

    def _fetch_page(path: str, what: str) -> list:
        """Fetch one page; raise OpenPrsUnverifiedError on anything but a list."""
        try:
            batch = _run_gh([path])
        except GitHubError as exc:
            raise _unverified(f"could not fetch {what}: {_github_error_text(exc)}") from exc
        if batch is None:
            raise _unverified(f"{what}: empty or 404 response (wrong repo, or token lacks access?)")
        if not isinstance(batch, list):
            raise _unverified(f"{what}: unexpected response type {type(batch).__name__}")
        return batch

    # Paginate the open-PR listing — an unpaged fetch silently drops PRs past
    # the first 100, letting stale commits slip through in a busy repo (#987).
    open_prs: list = []
    page = 1
    while True:
        batch = _fetch_page(
            f"/repos/{owner}/{repo}/pulls?state=open&per_page=100&page={page}",
            f"open-PR listing page {page}",
        )
        if not batch:
            break
        open_prs.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    for pr in open_prs:
        if not isinstance(pr, dict) or pr.get("number") is None:
            raise _unverified("open-PR listing contained a malformed PR entry")
        pr_number = pr["number"]
        if not isinstance(pr_number, int) or isinstance(pr_number, bool):
            raise _unverified("open-PR listing contained a PR with a non-integer number")
        head = pr.get("head")
        head_ref = head.get("ref", "") if isinstance(head, dict) else ""
        if current_branch and head_ref == current_branch:
            continue

        # Paginate this PR's commits — a PR can carry more than 100 commits.
        pr_commits: list = []
        commit_page = 1
        while True:
            commit_batch = _fetch_page(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/commits"
                f"?per_page=100&page={commit_page}",
                f"commits of PR #{pr_number} page {commit_page}",
            )
            if not commit_batch:
                break
            pr_commits.extend(commit_batch)
            if len(commit_batch) < 100:
                break
            commit_page += 1

        overlap = []
        for c in pr_commits:
            sha = c.get("sha") if isinstance(c, dict) else None
            if not sha:
                raise _unverified(f"commits of PR #{pr_number} contained a malformed commit entry")
            if sha in our_sha_set:
                overlap.append(sha)
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

    Fail-closed (#1681): if the open-PR overlap check cannot be completed (API
    error, 404/empty body, malformed response), the result carries the reason in
    `open_prs_unverified`, `is_clean` is False, and a
    `pre-pr-stale-check-unverified` event is emitted.  Callers must not treat an
    unverified result as clean.  When check_open_prs is False, or the branch has
    no commits ahead of base, there is nothing to verify and the check is not
    marked unverified.
    """
    all_commits = get_branch_commits(base=base, head=head)
    redundant_in_main = find_redundant_in_main(base=base, head=head)

    redundant_in_prs: dict[str, list[str]] = {}
    unverified: Optional[str] = None
    if check_open_prs and all_commits:
        try:
            redundant_in_prs = find_redundant_in_open_prs(
                owner,
                repo,
                all_commits,
                current_branch=branch,
                bot_login=bot_login,
            )
        except OpenPrsUnverifiedError as exc:
            unverified = sanitize_reason(str(exc))
            logger.warning("Open-PR overlap on %s could not be verified: %s", branch, unverified)
            log_event(
                "pre-pr-stale-check-unverified",
                branch=branch,
                base=base,
                reason=unverified,
            )

    result = StaleCommitResult(
        branch=branch,
        base=base,
        all_commits=all_commits,
        redundant_in_main=redundant_in_main,
        redundant_in_prs=redundant_in_prs,
        open_prs_unverified=unverified,
    )

    # Real redundancies keep their existing event; a merely-unverified result
    # has already emitted its own event above.
    if result.redundant_in_main or result.redundant_in_prs:
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


# ---------------------------------------------------------------------------
# Base freshness (#1162)
# ---------------------------------------------------------------------------


@dataclass
class BaseFreshnessResult:
    """Whether a base ref is current with respect to the branch it targets.

    Distinct from StaleCommitResult, which asks whether a branch carries
    commits already present upstream (redundant work). This asks the opposite
    question: does upstream carry commits the *base* is missing?
    """

    base: str
    target: str
    missing_commits: list[str]  # oneline summaries, newest first
    behind_count: int
    target_resolved: bool  # False → the check could not run

    @property
    def is_fresh(self) -> bool:
        return self.behind_count == 0

    @property
    def could_not_check(self) -> bool:
        return not self.target_resolved


def _ref_exists(ref: str) -> bool:
    try:
        _run_git(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"])
        return True
    except RuntimeError:
        return False


def check_base_freshness(
    base: str,
    target: str = "origin/main",
    sample: int = 5,
) -> BaseFreshnessResult:
    """
    Report whether `target` contains commits that `base` does not.

    Building a commit on a base the target has moved past produces a change
    that proposes REVERTING the intervening work, because the tree seeded from
    that base simply lacks it — and the resulting PR looks entirely normal.
    Observed 2026-08-01: this shape would have reverted four merged PRs
    (6,114 deletions), caught only by manually reading a diff stat.

    Note this cannot be detected by diffing the base against the resulting
    tree: the base *is* the stale thing, so that diff is clean by construction.
    It has to be compared against the real upstream target — which is what this
    function does.

    `sample` bounds how many missing-commit summaries are returned; the full
    count is always exact.

    An unresolvable `target` returns target_resolved=False rather than raising
    or silently passing — callers must treat that as "could not check", never
    as "fresh". A silently-skipped staleness check is the fail-open this
    function exists to prevent.
    """
    if not _ref_exists(target):
        return BaseFreshnessResult(
            base=base,
            target=target,
            missing_commits=[],
            behind_count=0,
            target_resolved=False,
        )

    count_out = _run_git(["rev-list", "--count", f"{base}..{target}"])
    behind = int(count_out or "0")

    missing: list[str] = []
    if behind:
        log_out = _run_git(["log", "--oneline", f"-{sample}", f"{base}..{target}"])
        missing = log_out.splitlines() if log_out else []

    return BaseFreshnessResult(
        base=base,
        target=target,
        missing_commits=missing,
        behind_count=behind,
        target_resolved=True,
    )
