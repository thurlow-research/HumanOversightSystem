#!/usr/bin/env python3
"""readopt.py — mechanics for re-adopting stalled local worker branches (#2126).

The worker lands a stalled, already-reviewed local branch (``worker-<N>-*``)
by re-adopting it onto current main via ``bootstrap/create_branch.sh --from``.
The human ruled (D-7 / D-8) how that is reviewed and cleaned up; this module
holds the deterministic parts so the worker does not re-derive them.

Subcommands
-----------
review-path    D-7: after merging origin/main into the adopted branch, is the
               re-review ``full`` or ``delta``?
reap-landed    D-8: delete local branches (that have an ownership record) whose
               work has landed on origin/main, plus their records.
prune-attempts D-8: delete duplicate / superseded / closed-issue attempts for
               one issue, keeping the newest (or an explicitly named) branch,
               and the remote head of each deleted attempt (#2286).
reap-orphans   #2286: delete orphaned local branches (recorded or not) and
               remote ``worker-*`` heads by PR, issue and content state, after
               a grace period. Never touches open-PR heads or unlanded work on
               open issues.

Usage
-----
  python3 -m scripts.automation.readopt review-path \\
      --original-head <ref> --merged-head <ref> [--base origin/main]
  python3 -m scripts.automation.readopt reap-landed [--dry-run] [--grace-secs 300]
  python3 -m scripts.automation.readopt prune-attempts --issue <N> \\
      [--keep <branch>] [--issue-closed] [--dry-run]
  python3 -m scripts.automation.readopt reap-orphans [--dry-run] [--grace-days 7] \\
      [--local-only | --remote-only] [--max-deletions N]

Exit codes
----------
  0 — success (``reap-landed`` exits 0 even when it skipped branches; skips
      are printed as WARN lines)
  2 — git / usage error. For ``review-path`` a caller MUST treat exit 2 as
      ``full`` (fail closed: never skip review on uncertainty). For
      ``reap-orphans`` a failed listing also exits 2, having deleted nothing.

Safety
------
Only branches that have an ownership record are ever considered by
``reap-landed``; unrecorded leftover branches are never touched there (that is
``reap-orphans``' job, human-authorized by #2286). The checked-out branch is
never deleted. A branch is never deleted on uncertainty (git or GitHub failure
-> skip). The GitHub token reaches git only through the subprocess environment,
never argv, a URL, or printed text.
"""
from __future__ import annotations

import argparse
import base64
import os
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence
from urllib.parse import quote

from scripts.automation.lib import github
from scripts.automation.pre_pr_stale_check import parse_remote_url

# Same grace window as bin/hos-cron's zero-commit reaper (#1498): a record
# younger than this may belong to a concurrently-running cycle's new branch.
DEFAULT_GRACE_SECS = 300

# (args after "git") -> (returncode, stdout)
GitRunner = Callable[[Sequence[str]], "tuple[int, str]"]
# (branch, local_tip_sha) -> True iff a merged PR from that branch has head.sha == tip.
# Raises on lookup failure (caller then skips the branch).
PrMergedLookup = Callable[[str, str], bool]
# issue number -> GitHub issue state ("open" / "closed"). Raises on failure.
IssueStateLookup = Callable[[int], str]

# Cap on PR lookups per reap-landed run. Neither branch.<n>.merge nor a
# refs/remotes/origin/<branch> ref is a reliable "has a PR" signal:
# bootstrap/submit_pr.sh pushes to a token URL with no -u, so no upstream is
# set, and the remote-tracking ref is pruned once the PR's head branch is
# deleted on merge -- exactly when a squash-merged branch needs the lookup.
# So API cost is bounded by a cap instead; which candidates get the lookups
# is randomised each run so coverage rotates (see reap_landed).
DEFAULT_MAX_LOOKUPS = 20
# Circuit breaker: stop PR lookups for the run after this many consecutive failures.
MAX_CONSECUTIVE_LOOKUP_FAILURES = 2


def _one_line(exc: object) -> str:
    """Collapse exception text to one bounded line so it cannot forge a
    REAPED/REAP-FAILED line in the output the cron hook parses (CWE-117). Also
    redacts the GitHub token (CWE-532), so no printed text can carry it."""
    return " ".join(_redact(exc).split())[:300]


class GitError(RuntimeError):
    pass


def make_git(repo: Path) -> GitRunner:
    def run(args: Sequence[str]) -> "tuple[int, str]":
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()

    return run


def _git_ok(git: GitRunner, *args: str) -> str:
    rc, out = git(args)
    if rc != 0:
        raise GitError(f"git {' '.join(args)} failed (rc={rc})")
    return out


# ---------------------------------------------------------------------------
# D-7 review path
# ---------------------------------------------------------------------------


def decide_review_path(
    reviewed_files: Sequence[str],
    merge_touched_files: Sequence[str],
    added_commits: Sequence[str],
    unexplained_change: str = "",
) -> "tuple[str, str]":
    """D-7: ``full`` iff the merge touched a reviewed file, new commits were
    added beyond the originally reviewed head, or the merged tree is not what
    an independent merge would produce (``unexplained_change`` is a non-empty
    description of that, e.g. a conflict resolution or extra edits); otherwise
    ``delta``."""
    if unexplained_change:
        return "full", unexplained_change
    overlap = sorted(set(reviewed_files) & set(merge_touched_files))
    if overlap:
        return "full", f"merge from base touched reviewed file(s): {', '.join(overlap)}"
    if added_commits:
        return "full", f"{len(added_commits)} new commit(s) added beyond the reviewed head"
    return "delta", "merge touched no reviewed file and added no new commits"


def _lines(out: str) -> "list[str]":
    return [ln for ln in out.splitlines() if ln]


def _unexplained_change(git: GitRunner, original_head: str, merged_head: str, base: str) -> str:
    """ "" if merged_head's tree equals a clean independent merge of
    original_head and base; otherwise a description. GitError on git failure.
    ``git merge-tree --write-tree`` exits 0 when clean and 1 on conflicts."""
    rc, out = git(["merge-tree", "--write-tree", "--name-only", original_head, base])
    lines = out.splitlines()
    if rc == 1:
        conflicted = []
        for line in lines[1:]:
            if not line:
                break
            conflicted.append(line)
        return f"merge had conflicts: {', '.join(sorted(set(conflicted))) or '(unknown)'}"
    if rc != 0 or not lines:
        raise GitError(f"git merge-tree failed (rc={rc})")
    expected_tree = lines[0]
    merged_tree = _git_ok(git, "rev-parse", f"{merged_head}^{{tree}}")
    if expected_tree == merged_tree:
        return ""
    files = _lines(_git_ok(git, "diff", "--name-only", expected_tree, merged_tree))
    return "merged tree differs from an independent merge of the reviewed head and base: " + (
        ", ".join(files) or "(no file list)"
    )


def compute_review_path(
    git: GitRunner, original_head: str, merged_head: str, base: str = "origin/main"
) -> "tuple[str, str]":
    """Derive the three D-7 inputs from git and apply decide_review_path.

    Fails closed (GitError) unless both original_head and base are ancestors of
    merged_head, i.e. the merge from base has actually happened.

    fork           = merge-base(original_head, base).
    reviewed set   = files changed in original_head since the fork.
    merge-touched  = (files changed on base since the fork) UNION (``git diff
                     --name-only original_head merged_head``). The first part is
                     what main changed that this merge had to absorb, so a
                     conflict resolved keeping the branch's side (``--ours``) on
                     a reviewed file still counts as touched; the second part
                     catches anything else that differs after the merge. A file
                     that only an OLDER main merge already inside original_head
                     brought in is not in the reviewed set, and the fork
                     (their merge-base) moves past that merge, so it stays out.
    added commits  = non-merge commits in original_head..merged_head that are
                     not reachable from base (i.e. authored on the branch, not
                     merely merged in from main).
    unexplained   = the merge is recomputed independently with ``git merge-tree
                     --write-tree`` (original_head + base). Conflicts (a
                     resolution is newly authored content) or a merged_head
                     tree that differs from the independent merge's tree (extra
                     edits hidden in a merge commit) force ``full``. If
                     merged_head merged an OLDER base than the ``base`` given
                     here, the trees differ and the result is ``full`` --
                     conservative by design.
    Raises GitError on any git failure.
    """
    for ancestor in (original_head, base):
        rc, _ = git(["merge-base", "--is-ancestor", ancestor, merged_head])
        if rc != 0:
            raise GitError(f"{ancestor!r} is not an ancestor of {merged_head!r}: merge not done")
    fork = _git_ok(git, "merge-base", original_head, base)
    reviewed = _lines(_git_ok(git, "diff", "--name-only", fork, original_head))
    touched = _lines(_git_ok(git, "diff", "--name-only", fork, base)) + _lines(
        _git_ok(git, "diff", "--name-only", original_head, merged_head)
    )
    added = _lines(
        _git_ok(git, "rev-list", "--no-merges", f"{original_head}..{merged_head}", "--not", base)
    )
    unexplained = _unexplained_change(git, original_head, merged_head, base)
    return decide_review_path(reviewed, touched, added, unexplained)


# ---------------------------------------------------------------------------
# Ownership records (read-only parsing; the writer is bootstrap/lib/branch_ownership.sh)
# ---------------------------------------------------------------------------


def store_dir(git: GitRunner, repo: Path) -> Path:
    common = Path(_git_ok(git, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = repo / common
    return common / "hos" / "branch-ownership"


def read_records(store: Path) -> "list[tuple[str, Path]]":
    """Return (branch, record_path) for each parseable record. The record is
    read for its ``branch=`` line only — never sourced or eval'd."""
    found: "list[tuple[str, Path]]" = []
    if not store.is_dir():
        return found
    for rec in sorted(store.glob("*.rec")):
        try:
            for line in rec.read_text().splitlines():
                if line.startswith("branch="):
                    branch = line[len("branch=") :]
                    if branch:
                        found.append((branch, rec))
                    break
        except OSError:
            continue
    return found


def _current_branch(git: GitRunner) -> str:
    rc, out = git(["symbolic-ref", "--quiet", "--short", "HEAD"])
    return out if rc == 0 else ""


def _branch_exists(git: GitRunner, branch: str) -> bool:
    rc, _ = git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
    return rc == 0


def _checked_out_in_worktree(git: GitRunner, branch: str) -> bool:
    """True if any worktree (including this one) has refs/heads/<branch> checked
    out. Fails safe: a listing error counts as checked out."""
    rc, out = git(["worktree", "list", "--porcelain"])
    if rc != 0:
        return True
    return f"branch refs/heads/{branch}" in out.splitlines()


def _delete_branch(git: GitRunner, branch: str, records: "list[Path]", expected_sha: str) -> bool:
    """Compare-and-delete (CWE-367): remove the ref only if it still points at
    the SHA that was verified, and never a branch checked out in any worktree.
    The ownership record is removed only after a successful delete."""
    if _checked_out_in_worktree(git, branch):
        print(f"WARN: '{branch}' is checked out in a worktree — not deleting")
        return False
    rc, _ = git(["update-ref", "-d", f"refs/heads/{branch}", expected_sha])
    if rc != 0:
        return False
    for rec in records:
        try:
            rec.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"WARN: branch '{branch}' deleted but record {rec} not removed: {_one_line(exc)}")
    return True


# ---------------------------------------------------------------------------
# D-8 reap-landed
# ---------------------------------------------------------------------------


def github_pr_lookup(git: GitRunner) -> PrMergedLookup:
    """Production PR lookup: a merged PR whose head ref is the branch and whose
    head.sha equals the local tip. Slug is parsed from the origin remote."""
    cache: "dict[str, tuple[str, str]]" = {}

    def lookup(branch: str, tip: str) -> bool:
        if "slug" not in cache:
            cache["slug"] = parse_remote_url(_git_ok(git, "remote", "get-url", "origin"))
        owner, repo = cache["slug"]
        for pr in github.list_pulls(owner, repo, head=f"{owner}:{branch}", state="closed"):
            if pr.get("merged_at") and (pr.get("head") or {}).get("sha") == tip:
                return True
        return False

    return lookup


def github_issue_state(git: GitRunner) -> IssueStateLookup:
    """Production issue-state lookup (server-side truth for --issue-closed)."""

    def lookup(issue: int) -> str:
        owner, repo = parse_remote_url(_git_ok(git, "remote", "get-url", "origin"))
        data = github.get_issue(owner, repo, issue)
        if not isinstance(data, dict) or not data.get("state"):
            raise GitError(f"could not read state of issue #{issue}")
        return str(data["state"])

    return lookup


def reap_landed(
    repo: Path,
    *,
    git: Optional[GitRunner] = None,
    pr_lookup: Optional[PrMergedLookup] = None,
    grace_secs: int = DEFAULT_GRACE_SECS,
    dry_run: bool = False,
    now: Optional[float] = None,
    base: str = "origin/main",
    max_lookups: int = DEFAULT_MAX_LOOKUPS,
    seed: Optional[int] = None,
) -> "list[str]":
    """Delete landed, recorded, local branches. Returns the reaped branch names
    (would-be names when dry_run). Prints a ``REAPED``/``WOULD-REAP``/``WARN`` line
    per decision that matters."""
    git = git or make_git(repo)
    pr_lookup = pr_lookup or github_pr_lookup(git)
    now = time.time() if now is None else now
    reaped: "list[str]" = []

    try:
        store = store_dir(git, repo)
    except GitError as exc:
        print(f"WARN: cannot resolve ownership store: {_one_line(exc)}")
        return reaped
    current = _current_branch(git)

    by_branch: "dict[str, list[Path]]" = {}
    for branch, rec in read_records(store):
        by_branch.setdefault(branch, []).append(rec)

    # Phase 1: cheap local checks for EVERY record (grace window, checked-out
    # branch, ancestry). Ancestry-landed branches need no API call. Only
    # branches that could have been squash-merged become PR-lookup candidates.
    local_reaps: "list[tuple[str, list[Path], str, str]]" = []
    candidates: "list[tuple[str, list[Path], str]]" = []  # (branch, recs, tip)
    for branch, recs in sorted(by_branch.items()):
        if branch.startswith("-"):
            print(f"WARN: record names option-like branch '{branch}' — skipping")
            continue
        if branch == current or not _branch_exists(git, branch):
            continue
        try:
            age = now - max(r.stat().st_mtime for r in recs)
        except OSError:
            continue
        if age < grace_secs:
            continue
        rc, tip = git(["rev-parse", f"refs/heads/{branch}"])
        if rc != 0 or not tip:
            print(f"WARN: cannot resolve tip of '{branch}' — skipping")
            continue
        rc, _ = git(["merge-base", "--is-ancestor", tip, base])
        if rc == 0:
            local_reaps.append((branch, recs, f"tip is an ancestor of {base}", tip))
        elif rc == 1:
            candidates.append((branch, recs, tip))
        else:
            print(f"WARN: cannot compare '{branch}' with {base} (rc={rc}) — skipping")

    def reap_all(items: "list[tuple[str, list[Path], str, str]]") -> None:
        for branch, recs, reason, tip in items:
            if dry_run:
                print(f"WOULD-REAP branch={branch} reason={reason}")
                reaped.append(branch)
            elif _delete_branch(git, branch, recs, tip):
                print(f"REAPED branch={branch} reason={reason}")
                reaped.append(branch)
            else:
                print(f"REAP-FAILED branch={branch} reason=delete-failed (record left in place)")

    # Local (ancestry) reaps happen BEFORE any PR lookup so a lookup stall or
    # timeout kill cannot defer them.
    reap_all(local_reaps)

    # Phase 2: PR lookups, capped. Candidates are SHUFFLED rather than ordered:
    # escalated local-only branches never land, so any fixed order (newest or
    # oldest first) re-queries the same unlandable head of the list every
    # cycle and starves the rest. A random sample gives every candidate an
    # equal chance each cycle with no persisted state -- a round-robin cursor
    # would need a file under the ownership store that concurrent cycles could
    # race on and that goes stale when records are added or removed.
    random.Random(seed).shuffle(candidates)
    lookup_reaps: "list[tuple[str, list[Path], str, str]]" = []
    lookups = 0
    failures = 0  # consecutive PR-lookup exceptions
    total_failures = 0
    skipped_cap = 0
    for index, (branch, recs, tip) in enumerate(candidates):
        if lookups >= max_lookups:
            skipped_cap = len(candidates) - index
            print(
                f"WARN: PR-lookup cap ({max_lookups}) reached — {skipped_cap} "
                "branch(es) deferred to a later cycle"
            )
            break
        lookups += 1
        try:
            merged = pr_lookup(branch, tip)
            failures = 0
        except Exception as exc:  # never delete on uncertainty
            print(f"WARN: PR lookup failed for '{branch}' — skipping: {_one_line(exc)}")
            failures += 1
            total_failures += 1
            if failures >= MAX_CONSECUTIVE_LOOKUP_FAILURES:
                print(
                    f"WARN: PR lookups aborted after {failures} consecutive failures"
                    " — skipping remaining lookups"
                )
                break
            continue
        if merged:
            lookup_reaps.append((branch, recs, "merged PR head.sha matches local tip", tip))

    reap_all(lookup_reaps)
    print(
        f"SUMMARY reaped={len(reaped)} lookups={lookups} skipped_cap={skipped_cap}"
        f" lookup_failures={total_failures}"
    )
    return reaped


# ---------------------------------------------------------------------------
# D-8 prune-attempts
# ---------------------------------------------------------------------------


def prune_attempts(
    repo: Path,
    issue: int,
    *,
    git: Optional[GitRunner] = None,
    keep: Optional[str] = None,
    issue_closed: bool = False,
    dry_run: bool = False,
    issue_state: Optional[IssueStateLookup] = None,
    remote_heads: Optional[RemoteHeads] = None,
    remote_delete: Optional[RemoteDelete] = None,
    slug: "Optional[tuple[str, str]]" = None,
    open_pr: Optional[Callable[[str], bool]] = None,
) -> "list[str]":
    """Delete local ``worker-<issue>-*`` attempts. Closed issue: delete all,
    but only after the issue's state is verified ``closed`` server-side (an
    open issue or a failed lookup raises GitError and deletes nothing).
    Otherwise keep ``keep`` (must exist) or the newest tip, delete the rest.
    The checked-out branch is never deleted. Raises GitError on git failure or
    an unknown ``keep``.

    After each successful local delete of attempt B at tip T, B's remote head is
    deleted too (#2286) iff it is still at T and has no open PR; any remote
    problem is a WARN that never fails or undoes the local delete."""
    git = git or make_git(repo)
    if issue_closed:
        try:
            state = (issue_state or github_issue_state(git))(issue)
        except Exception as exc:  # never delete on uncertainty
            raise GitError(f"cannot verify issue #{issue} is closed: {_one_line(exc)}") from exc
        if state != "closed":
            raise GitError(f"--issue-closed refused: issue #{issue} state is {state!r}")
    out = _git_ok(
        git,
        "for-each-ref",
        "--format=%(refname:short)|%(objectname)|%(committerdate:unix)",
        f"refs/heads/worker-{issue}-*",
    )
    attempts: "list[tuple[int, str]]" = []
    tips: "dict[str, str]" = {}
    for line in _lines(out):
        name, sha, stamp = line.rsplit("|", 2)
        attempts.append((int(stamp or 0), name))
        tips[name] = sha
    names = [n for _, n in attempts]

    if issue_closed:
        doomed = names
    else:
        if keep is not None:
            if keep not in names:
                raise GitError(f"--keep branch '{keep}' is not a local worker-{issue}-* branch")
            survivor = keep
        elif attempts:
            survivor = max(attempts)[1]  # newest tip; name breaks ties
            if len(attempts) > 1:
                print(
                    f"WARN: no --keep given; keeping '{survivor}' (newest tip). Prefer the "
                    f"head named in the escalation comment, via --keep, if there is one."
                )
        else:
            survivor = ""
        doomed = [n for n in names if n != survivor]

    current = _current_branch(git)
    store = store_dir(git, repo)
    records = read_records(store)
    deleted: "list[str]" = []
    remote = _PruneRemote(git, repo, issue, remote_heads, remote_delete, slug, open_pr)
    for branch in sorted(doomed):
        if branch == current:
            print(f"WARN: '{branch}' is checked out — not deleting")
            continue
        recs = [rec for b, rec in records if b == branch]
        if dry_run:
            print(f"WOULD-DELETE branch={branch}")
            deleted.append(branch)
            remote.step(branch, tips[branch], dry_run=True)
        elif _delete_branch(git, branch, recs, tips[branch]):
            print(f"DELETED branch={branch}")
            deleted.append(branch)
            remote.step(branch, tips[branch], dry_run=False)
        else:
            print(f"WARN: could not delete '{branch}'")
    return deleted


class _PruneRemote:
    """Lazy remote-head cleanup for ``prune_attempts`` (one ls-remote per run,
    made on first use). Every failure is a WARN; nothing here can raise."""

    def __init__(self, git, repo, issue, remote_heads, remote_delete, slug, open_pr):
        self.git, self.repo, self.issue = git, repo, issue
        self.heads_fn, self.delete_fn = remote_heads, remote_delete
        self.slug, self.open_pr = slug, open_pr
        self.heads: "Optional[dict[str, str]]" = None
        self.dead = False

    def _load(self) -> None:
        try:
            if self.heads_fn is None or self.delete_fn is None:
                ops = _remote_ops(self.git, self.repo)
                if ops is None:
                    self.dead = True
                    return
                url, run = ops
                self.heads_fn = self.heads_fn or (lambda pat: _ls_remote(run, url, pat))
                self.delete_fn = self.delete_fn or (lambda items: _push_delete(run, url, items))
            self.heads = dict(self.heads_fn(f"refs/heads/worker-{self.issue}-*"))
        except Exception as exc:
            print(f"WARN: remote head lookup failed — remote heads kept: {_one_line(exc)}")
            self.dead = True

    def _has_open_pr(self, branch: str) -> bool:
        if self.open_pr is not None:
            return self.open_pr(branch)
        owner, repo = self.slug or _slug_from_origin(self.git)
        return bool(github.list_pulls(owner, repo, head=f"{owner}:{branch}", state="open"))

    def step(self, branch: str, tip: str, *, dry_run: bool) -> None:
        if self.dead:
            return
        if self.heads is None:
            self._load()
            if self.dead or self.heads is None:
                return
        sha = self.heads.get(branch)
        if sha is None:
            return
        if sha != tip:
            print(f"WARN: remote head moved for '{branch}' — remote head kept")
            return
        if dry_run:
            print(f"WOULD-DELETE branch={branch} where=remote")
            return
        try:
            if self._has_open_pr(branch):
                print(f"WARN: remote head '{branch}' has an open PR — remote head kept")
                return
            ok = bool(self.delete_fn([(branch, sha)]).get(branch)) if self.delete_fn else False
        except Exception as exc:
            print(f"WARN: remote delete of '{branch}' failed — remote head kept: {_one_line(exc)}")
            return
        if ok:
            print(f"DELETED branch={branch} where=remote")
        else:
            print(f"WARN: remote delete of '{branch}' was rejected — remote head kept")


# ---------------------------------------------------------------------------
# #2286 remote helpers (ls-remote / batched compare-and-swap delete)
# ---------------------------------------------------------------------------

# (args after "git", timeout seconds) -> (returncode, stdout). Same shape as
# GitRunner plus a per-call timeout; a timeout is reported as rc 124.
RemoteRunner = Callable[..., "tuple[int, str]"]
# pattern -> [(branch, sha)] for matching remote heads. Raises on failure.
RemoteHeads = Callable[[str], "list[tuple[str, str]]"]
# [(branch, sha)] -> {branch: deleted?}. Never raises for a per-ref failure.
RemoteDelete = Callable[["list[tuple[str, str]]"], "dict[str, bool]"]

LS_REMOTE_TIMEOUT_SECS = 60
PUSH_TIMEOUT_SECS = 120
_RC_TIMEOUT = 124
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _redact(text: object) -> str:
    """Replace the GH_TOKEN literal and its basic-auth header form with ``***``
    so no token can reach a log line or exception text (CWE-532)."""
    out = str(text)
    token = os.environ.get("GH_TOKEN", "")
    if token:
        header = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        for secret in (header, token):
            out = out.replace(secret, "***")
    return out


def _remote_env(token: str) -> "dict[str, str]":
    """Auth for a github.com remote through the git subprocess ENVIRONMENT only
    -- never argv or the URL. The empty credential.helper resets the helper
    list so an expired token cannot fall back to another identity's helper."""
    header = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {header}",
        "GIT_CONFIG_KEY_1": "credential.helper",
        "GIT_CONFIG_VALUE_1": "",
        "GIT_TERMINAL_PROMPT": "0",
    }


def make_git_remote(repo: Path, extra_env: "dict[str, str]") -> RemoteRunner:
    """Runner for git calls that talk to the remote. The child environment has
    every trace variable removed (they could log the auth header). ``stderr`` of
    the last call is kept redacted on ``run.last_stderr`` for diagnostics."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_TRACE") and k != "GIT_CURL_VERBOSE"
    }
    env.update(extra_env)

    def run(args: Sequence[str], timeout: float = LS_REMOTE_TIMEOUT_SECS) -> "tuple[int, str]":
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                check=False,
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            run.last_stderr = "timed out"  # type: ignore[attr-defined]
            return _RC_TIMEOUT, ""
        run.last_stderr = _one_line(proc.stderr)  # type: ignore[attr-defined]
        return proc.returncode, proc.stdout

    run.last_stderr = ""  # type: ignore[attr-defined]
    return run


def _origin_kind(url: str) -> Optional[str]:
    """``github`` (https://github.com/...), ``local`` (absolute path or file://),
    else None. ssh/other-host forms are refused: they would push with whatever
    ambient key the host has, possibly a human's identity."""
    if url.startswith("https://github.com/"):
        return "github"
    if url.startswith("file://") or (os.path.isabs(url) and not url.startswith("-")):
        return "local"
    return None


def _remote_ops(git: GitRunner, repo: Path) -> "Optional[tuple[str, RemoteRunner]]":
    """(origin url, authenticated runner), or None (after a WARN) when the remote
    phase must be skipped."""
    rc, url = git(["remote", "get-url", "origin"])
    if rc != 0 or not url:
        print("WARN: remote phase skipped — no origin remote")
        return None
    kind = _origin_kind(url)
    if kind is None:
        print("WARN: remote phase skipped — unsupported origin URL scheme")
        return None
    env: "dict[str, str]" = {}
    if kind == "github":
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            print("WARN: GH_TOKEN unset — remote phase skipped")
            return None
        env = _remote_env(token)
    return url, make_git_remote(repo, env)


def _ls_remote(run: RemoteRunner, url: str, pattern: str) -> "list[tuple[str, str]]":
    rc, out = run(["ls-remote", "--refs", url, pattern], LS_REMOTE_TIMEOUT_SECS)
    if rc != 0:
        detail = _one_line(getattr(run, "last_stderr", ""))
        raise GitError(f"git ls-remote failed (rc={rc}) {detail}".strip())
    heads: "list[tuple[str, str]]" = []
    for line in out.splitlines():
        sha, _, ref = line.partition("\t")
        if _SHA_RE.fullmatch(sha) and ref.startswith("refs/heads/"):
            heads.append((ref[len("refs/heads/") :], sha))
    return heads


def _push_delete(run: RemoteRunner, url: str, items: "list[tuple[str, str]]") -> "dict[str, bool]":
    """ONE non-atomic push deleting every (branch, sha), each ref guarded by its
    own ``--force-with-lease=<ref>:<sha>`` (a server-side compare-and-swap). The
    porcelain output is parsed per ref: only a ``-`` (deleted) line for
    ``:refs/heads/<branch>`` counts; a non-zero rc never overrides it and a zero
    rc never stands in for a missing line."""
    result = {b: False for b, _ in items}
    if not items:
        return result
    args = ["push", "--porcelain", "--no-verify"]
    args += [f"--force-with-lease=refs/heads/{b}:{sha}" for b, sha in items]
    args += [url]
    args += [f":refs/heads/{b}" for b, _ in items]
    rc, out = run(args, PUSH_TIMEOUT_SECS)
    if rc == _RC_TIMEOUT:
        return result
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] == "-" and parts[1].startswith(":refs/heads/"):
            name = parts[1][len(":refs/heads/") :]
            if name in result:
                result[name] = True
    return result


def _slug_from_origin(git: GitRunner) -> "tuple[str, str]":
    try:
        return parse_remote_url(_git_ok(git, "remote", "get-url", "origin"))
    except ValueError as exc:
        raise GitError(f"cannot resolve GitHub owner/repo: {_one_line(exc)}") from exc


# ---------------------------------------------------------------------------
# #2286 reap-orphans
# ---------------------------------------------------------------------------

DEFAULT_GRACE_DAYS = 7
PER_ISSUE_READ_LIMIT = 20  # at or below this many issue numbers, read them one by one

_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9._/@+-]+")
_WORKER_RE = re.compile(r"worker-(\d+)-")
_ISSUE_REF_RE = re.compile(r"#(\d+)")

# (state) -> PR objects. Raises on failure (the run then deletes nothing).
PullsLookup = Callable[[str], "list[dict]"]
# issue numbers needed -> {number: "open"|"closed"}; absent number == unknown.
IssueStatesLookup = Callable[["set[int]"], "dict[int, str]"]


@dataclass
class _Ref:
    name: str
    where: str  # "local" | "remote"
    tip: str


@dataclass
class _Decision:
    ref: _Ref
    reap: bool
    reason: str
    pr: str = "-"


class _Abort(Exception):
    """A listing failed: print WARN + SUMMARY aborted=1 and delete nothing."""


def _printable_name(name: str) -> str:
    return name if _SAFE_NAME_RE.fullmatch(name) else quote(name, safe="")


def _fmt(kind: str, d: _Decision, *, reason: Optional[str] = None, with_pr: bool = False) -> str:
    line = f"{kind} branch={_printable_name(d.ref.name)} reason={reason or d.reason}"
    line += f" where={d.ref.where}"
    if with_pr:
        line += f" pr={d.pr}"
    return f"{line} tip={d.ref.tip}"


def _github_pulls(slug: "tuple[str, str]") -> PullsLookup:
    return lambda state: github.list_all_pulls(slug[0], slug[1], state=state)


def _github_issue_states(slug: "tuple[str, str]") -> IssueStatesLookup:
    owner, repo = slug

    def lookup(needed: "set[int]") -> "dict[int, str]":
        if len(needed) > PER_ISSUE_READ_LIMIT:
            return github.list_all_issue_states(owner, repo)
        out: "dict[int, str]" = {}
        for number in sorted(needed):
            data = github.get_issue(owner, repo, number)
            if isinstance(data, dict) and data.get("state") in ("open", "closed"):
                out[number] = str(data["state"])
        return out

    return lookup


def _index_pulls(pulls: "list[dict]", slug: "tuple[str, str]") -> "dict[str, list[dict]]":
    """Same-repo PRs by head.ref; fork PRs never match a local/remote branch."""
    full = f"{slug[0]}/{slug[1]}".lower()
    index: "dict[str, list[dict]]" = {}
    for pr in pulls:
        head = pr.get("head") or {}
        head_repo = head.get("repo") or {}
        ref = head.get("ref")
        if isinstance(ref, str) and str(head_repo.get("full_name", "")).lower() == full:
            index.setdefault(ref, []).append(pr)
    return index


def _covers(git: GitRunner, pr: dict, tip: str) -> bool:
    """The PR head holds every commit of ``tip``: equal, or tip is an ancestor of
    the (locally present) PR head. A tip with commits beyond the PR never matches."""
    sha = (pr.get("head") or {}).get("sha")
    if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
        return False
    if sha == tip:
        return True
    rc, _ = git(["cat-file", "-e", f"{sha}^{{commit}}"])
    if rc != 0:
        return False
    rc, _ = git(["merge-base", "--is-ancestor", tip, sha])
    return rc == 0


def _commit_issue_refs(git: GitRunner, base: str, tip: str) -> "Optional[set[int]]":
    """Every ``#<n>`` in the messages of ``base..tip`` (a batched branch carries
    more than its name's issue). None on git failure."""
    rc, out = git(["log", "--format=%B", f"{base}..{tip}"])
    if rc != 0:
        return None
    return {int(n) for n in _ISSUE_REF_RE.findall(out)}


def reap_orphans(
    repo: Path,
    *,
    git: Optional[GitRunner] = None,
    pulls: Optional[PullsLookup] = None,
    issue_states: Optional[IssueStatesLookup] = None,
    remote_heads: Optional[RemoteHeads] = None,
    remote_delete: Optional[RemoteDelete] = None,
    now: Optional[float] = None,
    slug: "Optional[tuple[str, str]]" = None,
    grace_days: int = DEFAULT_GRACE_DAYS,
    dry_run: bool = False,
    do_local: bool = True,
    do_remote: bool = True,
    max_deletions: int = 0,
    base: str = "origin/main",
) -> int:
    """#2286: delete orphaned local branches and remote ``worker-*`` heads by PR,
    issue and content state. Every decision is built before anything is deleted;
    any failed listing aborts the whole run with zero deletions (exit 2). Returns
    the process exit code. See TECHNICAL-DESIGN-2286 for the decision table."""
    git = git or make_git(repo)
    now = time.time() if now is None else now
    calls_before = github.gh_call_count()
    grace_secs = grace_days * 86400
    decisions: "list[_Decision]" = []

    store = store_dir(git, repo)
    current = _current_branch(git)
    recs_by_branch: "dict[str, list[Path]]" = {}
    for branch, rec in read_records(store):
        recs_by_branch.setdefault(branch, []).append(rec)
    base_tree = _git_ok(git, "rev-parse", f"{base}^{{tree}}")

    def keep(ref: _Ref, reason: str) -> None:
        decisions.append(_Decision(ref, False, reason))

    def summary(aborted: int, counts: "dict[str, int]") -> None:
        print(
            f"SUMMARY reaped_local={counts['reaped_local']} reaped_remote={counts['reaped_remote']}"
            f" kept={counts['kept']} failed={counts['failed']} deferred={counts['deferred']}"
            f" api_calls={github.gh_call_count() - calls_before} aborted={aborted}"
        )

    counts = {"reaped_local": 0, "reaped_remote": 0, "kept": 0, "failed": 0, "deferred": 0}

    # ---- remote head listing (one authoritative read; failure skips only the remote phase)
    remote_refs: "list[_Ref]" = []
    if do_remote:
        if remote_heads is None or remote_delete is None:
            ops = _remote_ops(git, repo)
            if ops is not None:
                url, run = ops
                remote_heads = remote_heads or (lambda pat: _ls_remote(run, url, pat))
                remote_delete = remote_delete or (lambda items: _push_delete(run, url, items))
            else:
                remote_heads = None
        if remote_heads is not None:
            try:
                for name, sha in sorted(remote_heads("refs/heads/worker-*")):
                    if name.startswith("worker-"):
                        remote_refs.append(_Ref(name, "remote", sha))
            except Exception as exc:  # the local phase still runs
                print(f"WARN: remote head listing failed — remote phase skipped: {_one_line(exc)}")

    local_refs: "list[_Ref]" = []
    local_committed: "dict[str, int]" = {}
    if do_local:
        out = _git_ok(
            git,
            "for-each-ref",
            "--format=%(refname)%09%(objectname)%09%(committerdate:unix)",
            "refs/heads/",
        )
        for line in _lines(out):
            refname, sha, stamp = line.split("\t")
            name = refname[len("refs/heads/") :]
            local_refs.append(_Ref(name, "local", sha))
            local_committed[name] = int(stamp) if stamp.isdigit() else -1

    # ---- phase A: purely local rules N1-N4 and G1 (no GitHub)
    pending: "list[_Ref]" = []
    young: "list[_Ref]" = []  # grace-KEEP; relabelled open-pr if a listing shows one
    for ref in sorted(local_refs, key=lambda r: r.name) + sorted(remote_refs, key=lambda r: r.name):
        name = ref.name
        if not _SAFE_NAME_RE.fullmatch(name) or name.startswith("-"):
            keep(ref, "unsafe-name")
            continue
        if name in ("main", "audit-log") or name.startswith(("release/", "audit/")):
            keep(ref, "protected-name")
            continue
        if ref.where == "local":
            if name == current:
                keep(ref, "current-branch")
                continue
            if _checked_out_in_worktree(git, name):
                keep(ref, "worktree")
                continue
            stamps = [local_committed.get(name, -1)]
            # %gd with --date=unix renders "<branch>@{<epoch>}" (there is no
            # reflog-timestamp placeholder; %ct would be the commit's date).
            rc, out = git(["log", "-g", "-1", "--date=unix", "--format=%gd", f"refs/heads/{name}"])
            reflog_at = re.search(r"@\{(\d+)\}$", out) if rc == 0 else None
            if reflog_at:
                stamps.append(int(reflog_at.group(1)))
            for rec in recs_by_branch.get(name, []):
                try:
                    stamps.append(int(rec.stat().st_mtime))
                except OSError:
                    pass
        else:
            rc, _ = git(["cat-file", "-e", f"{ref.tip}^{{commit}}"])
            if rc != 0:
                keep(ref, "remote-tip-not-local")
                continue
            rc, out = git(["log", "-1", "--format=%ct", ref.tip])
            stamps = [int(out)] if rc == 0 and out.isdigit() else [-1]
        newest = max(stamps)
        if newest < 0:
            keep(ref, "git-error")
            continue
        if now - newest < grace_secs:
            keep(ref, "grace")
            young.append(ref)
            continue
        pending.append(ref)

    # ---- phase B: decisions that need GitHub (skipped entirely when none remain)
    open_heads: "set[str]" = set()
    owner_repo = slug
    try:
        if pending:
            owner_repo = slug or _slug_from_origin(git)
            pulls = pulls or _github_pulls(owner_repo)
            issue_states = issue_states or _github_issue_states(owner_repo)
            try:
                all_pulls = pulls("all")
            except Exception as exc:
                raise _Abort(exc) from exc
            if not all_pulls:
                raise _Abort("empty pull-request listing")
            index = _index_pulls(all_pulls, owner_repo)
            open_heads = {
                name for name, prs in index.items() if any(p.get("state") == "open" for p in prs)
            }
            young_ids = {id(r) for r in young}
            for d in decisions:
                if id(d.ref) in young_ids and d.ref.name in open_heads:
                    d.reason = "open-pr"  # N5 outranks G1 in the table; both are KEEP

            # pass 1: N5, D1, and the issue numbers D1'/D2 will need
            plans: "dict[int, dict]" = {}
            needed: "set[int]" = set()
            for ref in pending:
                prs = index.get(ref.name, [])
                if ref.name in open_heads:
                    keep(ref, "open-pr")
                    continue
                covering = [p for p in prs if _covers(git, p, ref.tip)]
                merged = [
                    p
                    for p in covering
                    if p.get("merged_at") and (p.get("base") or {}).get("ref") == "main"
                ]
                if merged:
                    decisions.append(
                        _Decision(ref, True, "pr-merged", f"#{merged[0].get('number')}")
                    )
                    continue
                m = _WORKER_RE.match(ref.name)
                plan: dict = {
                    "prs": prs,
                    "covering": covering,
                    "issue": int(m.group(1)) if m else None,
                    "refs": None,
                }
                if plan["issue"] is not None:
                    plan["refs"] = _commit_issue_refs(git, base, ref.tip)
                    needed.add(plan["issue"])
                    needed |= plan["refs"] or set()
                plans[id(ref)] = plan

            states: "dict[int, str]" = {}
            if needed:
                try:
                    states = issue_states(needed)
                except Exception as exc:
                    raise _Abort(exc) from exc

            # pass 2: D1', D2, D3, then the KEEP reasons
            for ref in pending:
                found = plans.get(id(ref))
                if found is not None:
                    decisions.append(_decide_rest(git, ref, found, states, base, base_tree))

        # ---- open-PR re-check right before the deletion phase
        if not dry_run and any(d.reap for d in decisions):
            try:
                fresh = pulls("open") if pulls else []
            except Exception as exc:
                raise _Abort(exc) from exc
            fresh_heads = set(_index_pulls(fresh, owner_repo))  # type: ignore[arg-type]
            for d in decisions:
                if d.reap and d.ref.name in fresh_heads:
                    d.reap, d.reason, d.pr = False, "open-pr", "-"
    except _Abort as exc:
        print(f"WARN: listing failed — nothing deleted: {_one_line(exc)}")
        summary(1, counts)
        return 2

    # ---- phase C: report / delete. Local before remote.
    ordered = [d for d in decisions if d.ref.where == "local"] + [
        d for d in decisions if d.ref.where == "remote"
    ]
    counts["kept"] = sum(1 for d in ordered if not d.reap)
    budget = max_deletions if max_deletions > 0 else None

    if dry_run:
        for d in ordered:
            if d.reap:
                print(_fmt("WOULD-REAP", d, with_pr=True))
                counts["reaped_" + d.ref.where] += 1
            else:
                print(_fmt("KEEP", d))
        summary(0, counts)
        return 0

    attempted = 0
    remote_batch: "list[_Decision]" = []
    for d in ordered:
        if not d.reap:
            continue
        if budget is not None and attempted >= budget:
            print(_fmt("DEFERRED", d))
            counts["deferred"] += 1
            continue
        attempted += 1
        if d.ref.where == "remote":
            remote_batch.append(d)
            continue
        if _delete_branch(git, d.ref.name, recs_by_branch.get(d.ref.name, []), d.ref.tip):
            print(_fmt("REAPED", d, with_pr=True))
            counts["reaped_local"] += 1
        else:
            print(_fmt("REAP-FAILED", d, reason="delete-failed"))
            counts["failed"] += 1
    if remote_batch and remote_delete is not None:
        try:
            outcome = remote_delete([(d.ref.name, d.ref.tip) for d in remote_batch])
        except Exception as exc:
            print(f"WARN: remote delete failed: {_one_line(exc)}")
            outcome = {}
        for d in remote_batch:
            if outcome.get(d.ref.name):
                print(_fmt("REAPED", d, with_pr=True))
                counts["reaped_remote"] += 1
            else:
                print(_fmt("REAP-FAILED", d, reason="cas-or-push-failed"))
                counts["failed"] += 1
    summary(0, counts)
    return 0


def _decide_rest(
    git: GitRunner, ref: _Ref, plan: dict, states: "dict[int, str]", base: str, base_tree: str
) -> _Decision:
    """Rules D1' through the KEEP table for one non-open-PR, non-D1 ref."""
    issue: Optional[int] = plan["issue"]
    state = states.get(issue) if issue is not None else None
    covering: "list[dict]" = plan["covering"]
    closed_cover = [p for p in covering if not p.get("merged_at") and p.get("state") == "closed"]
    protected_by_issue = False
    if closed_cover:
        if ref.where == "local" and issue is not None and state != "closed":
            protected_by_issue = True  # A1: never delete open-issue work on a closed PR
        else:
            return _Decision(ref, True, "pr-closed", f"#{closed_cover[0].get('number')}")

    d2_blocked = d2_git_error = False
    if issue is not None and state == "closed":
        refs = plan["refs"]
        if refs is None:
            d2_git_error = True
        elif all(states.get(n) == "closed" for n in refs):
            return _Decision(ref, True, "issue-closed")
        else:
            d2_blocked = True

    rc, _ = git(["merge-base", "--is-ancestor", ref.tip, base])
    if rc == 0:
        return _Decision(ref, True, "landed-ancestor")
    if rc != 1:
        return _Decision(ref, False, "git-error")
    rc, out = git(["merge-tree", "--write-tree", base, ref.tip])
    if rc == 0 and out.splitlines()[:1] == [base_tree]:
        return _Decision(ref, True, "landed-content")
    if rc not in (0, 1):
        return _Decision(ref, False, "git-error")

    if protected_by_issue:
        reason = "closed-pr-open-issue"
    elif plan["prs"] and not covering:
        reason = "unlanded-pr-sha-mismatch"
    elif d2_git_error:
        reason = "git-error"
    elif d2_blocked:
        reason = "issue-closed-batch-open"
    elif issue is not None and state is None:
        reason = "issue-unknown"
    elif issue is not None and state == "open":
        reason = "unlanded-open-issue"
    else:
        reason = "unlanded-no-pr"
    return _Decision(ref, False, reason)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _non_negative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if number < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return number


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Re-adoption mechanics for stalled worker branches (#2126)"
    )
    ap.add_argument("--repo", default=".", help="repository root (default: cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("review-path", help="D-7: full vs delta re-review")
    rp.add_argument("--original-head", required=True)
    rp.add_argument("--merged-head", required=True)
    rp.add_argument("--base", default="origin/main")

    rl = sub.add_parser("reap-landed", help="D-8: delete landed recorded branches")
    rl.add_argument("--dry-run", action="store_true")
    rl.add_argument("--grace-secs", type=int, default=DEFAULT_GRACE_SECS)
    rl.add_argument("--max-lookups", type=int, default=DEFAULT_MAX_LOOKUPS)

    pa = sub.add_parser("prune-attempts", help="D-8: delete duplicate attempts for an issue")
    pa.add_argument("--issue", type=int, required=True)
    pa.add_argument("--keep")
    pa.add_argument("--issue-closed", action="store_true")
    pa.add_argument("--dry-run", action="store_true")

    ro = sub.add_parser("reap-orphans", help="#2286: delete orphaned local branches + remote heads")
    ro.add_argument("--dry-run", action="store_true")
    ro.add_argument("--grace-days", type=_non_negative_int, default=DEFAULT_GRACE_DAYS)
    ro.add_argument("--max-deletions", type=_non_negative_int, default=0)
    only = ro.add_mutually_exclusive_group()
    only.add_argument("--local-only", action="store_true")
    only.add_argument("--remote-only", action="store_true")

    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    git = make_git(repo)

    try:
        if args.cmd == "review-path":
            for ref in (args.original_head, args.merged_head, args.base):
                if not re.fullmatch(r"[A-Za-z0-9._/@^~+-]+", ref) or ref.startswith("-"):
                    print(f"readopt: invalid ref {ref!r}", file=sys.stderr)
                    return 2
            path, reason = compute_review_path(git, args.original_head, args.merged_head, args.base)
            print(f"REVIEW_PATH={path}")
            print(f"REASON={reason}")
            return 0
        if args.cmd == "reap-landed":
            reap_landed(
                repo,
                git=git,
                grace_secs=args.grace_secs,
                dry_run=args.dry_run,
                max_lookups=args.max_lookups,
            )
            return 0
        if args.cmd == "reap-orphans":
            return reap_orphans(
                repo,
                git=git,
                grace_days=args.grace_days,
                dry_run=args.dry_run,
                do_local=not args.remote_only,
                do_remote=not args.local_only,
                max_deletions=args.max_deletions,
            )
        prune_attempts(
            repo,
            args.issue,
            git=git,
            keep=args.keep,
            issue_closed=args.issue_closed,
            dry_run=args.dry_run,
        )
        return 0
    except GitError as exc:
        print(f"readopt: {_one_line(exc)}", file=sys.stderr)
        return 2
    except Exception as exc:  # review-path must fail closed (caller treats rc!=0 as full)
        if args.cmd != "review-path":
            raise
        print(f"readopt: unexpected error: {_one_line(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
