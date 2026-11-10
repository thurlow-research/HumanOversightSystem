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
               remote ``worker-*`` heads (``--remote-scope all``: every remote
               head, #2288) by PR, issue and content state, after
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
      [--local-only | --remote-only] [--max-deletions N] \\
      [--remote-scope worker|all] [--no-issue-closed]
  python3 -m scripts.automation.readopt reap-orphans --list-archives [--archive-age-days 90]
  python3 -m scripts.automation.readopt delete-head --pr <N>

Exit codes
----------
  0 — success (``reap-landed`` exits 0 even when it skipped branches; skips
      are printed as WARN lines)
  2 — git / usage error. For ``review-path`` a caller MUST treat exit 2 as
      ``full`` (fail closed: never skip review on uncertainty). For
      ``reap-orphans`` a failed listing also exits 2, having deleted nothing.
      ``delete-head``: 0 = head is gone (DELETED or ALREADY-GONE), 2 = error or
      uncertainty (nothing deleted, or outcome unknown after a push timeout),
      3 = refused by a safety rule (KEPT; a valid outcome, not a failure).

Safety
------
``reap-orphans`` is archive-before-delete (#2293): a reap whose tip is neither on base nor
inside a PR head (ARCHIVE_REASONS; today rule D2 ``issue-closed``) first writes the
recovery ref ``refs/archive/reap/<branch>@<tip12>`` (local, create-only; for a remote head
it is also pushed to origin) and deletes only if that succeeded; otherwise it prints
``KEEP ... reason=archive-failed`` and deletes nothing. A successful write is reported on
its own line, ``ARCHIVED branch=<b> where=<local|remote> ref=<ref> tip=<sha>``, printed
before the delete; REAPED/REAP-FAILED lines are unchanged (bin/hos-cron audits them with an
end-anchored regex). WOULD-REAP lines in a dry run carry ``archive=<ref>``. The ref lives
outside ``refs/heads``
so no branch selector sees it. ``--list-archives`` lists them with age and NEVER prunes;
pruning archives is a separate human-authorized step. RESTORE:
``git fetch origin refs/archive/reap/<name>@<tip12>:refs/archive/reap/<name>@<tip12>``
(if only on origin), then ``git branch <name> refs/archive/reap/<name>@<tip12>``.
Remote heads of closed or merged PRs are deleted without an archive: their commits remain
reachable from ``refs/pull/N/head``.

Only branches that have an ownership record are ever considered by
``reap-landed``; unrecorded leftover branches are never touched there (that is
``reap-orphans``' job, human-authorized by #2286). The checked-out branch is
never deleted. ``reap-orphans`` (#2287) also deletes review copies of PR heads
(``pr-7``, ``pr7-check``, ... rule D4) only when that PR's current head contains every
commit of the tip, and NEVER deletes ``audit/*``, ``chore/audit-overseer-cycle-*`` or
``chore/overseer-audit-*`` branches, nor any unlanded branch whose diff against its
merge-base touches ``audit/log``, ``audit/oversight-log.jsonl`` or
``audit/overnight-loop-log.md`` (they may hold records that exist nowhere else).
``reap-orphans --dry-run`` skips the pre-delete open-PR re-check, so a
WOULD-REAP can become ``KEEP open-pr`` in the real run (SUMMARY ``recheck=skipped``
vs ``done``/``none``); SUMMARY also carries ``remote_skipped=1`` when the remote phase
could not run. The remote-head grace uses the tip COMMIT date (not the push time,
which git does not expose): a recently pushed old commit is judged old. Accepted
and documented (TD §10 post-review note). A branch is never deleted on uncertainty (git or GitHub failure
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
    base: str = "origin/main",
    issue_states: Optional[IssueStatesLookup] = None,
) -> "list[str]":
    """Delete local ``worker-<issue>-*`` attempts. Closed issue: delete all,
    but only after the issue's state is verified ``closed`` server-side (an
    open issue or a failed lookup raises GitError and deletes nothing).
    A batched attempt may also carry unlanded work for another issue (#2291):
    an attempt is kept, with a WARN, when any other ``#ref`` in its
    ``base..tip`` commit messages is not verified ``closed`` (open, unknown,
    lookup failure, or a git error reading the refs).
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
        doomed = _closed_issue_deletable(git, names, tips, issue, base, issue_states, slug)
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


def _closed_issue_deletable(git, names, tips, issue, base, issue_states, slug) -> "list[str]":
    """The attempts of a closed ``issue`` that are safe to delete (#2291): those
    whose commits reference no issue other than ``issue`` that is not closed."""
    others: "dict[str, set[int]]" = {}
    safe: "list[str]" = []
    for name in names:
        refs = _commit_issue_refs(git, base, tips[name])
        if refs is None:
            print(f"WARN: '{name}' kept — cannot read its commit refs (git error)")
            continue
        extra = refs - {issue}
        if extra:
            others[name] = extra
        else:
            safe.append(name)
    if not others:
        return safe
    needed = set().union(*others.values())
    try:
        states = (issue_states or _github_issue_states(slug or _slug_from_origin(git)))(needed)
    except Exception as exc:  # never delete on uncertainty
        for name in others:
            print(
                f"WARN: '{name}' kept — cannot verify its other referenced issues: {_one_line(exc)}"
            )
        return safe
    for name, extra in others.items():
        bad = [
            f"#{n} ({states.get(n, 'unknown')})" for n in sorted(extra) if states.get(n) != "closed"
        ]
        if bad:
            print(
                f"WARN: '{name}' kept — its commits reference issue(s) not closed: {', '.join(bad)}"
            )
        else:
            safe.append(name)
    return safe


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
            got = self.delete_fn([(branch, sha)]).get(branch) if self.delete_fn else False
        except Exception as exc:
            print(f"WARN: remote delete of '{branch}' failed — remote head kept: {_one_line(exc)}")
            return
        if got is True:
            print(f"DELETED branch={branch} where=remote")
        elif got == PUSH_TIMEOUT:
            print(
                f"WARN: remote delete of '{branch}' timed out — outcome unknown,"
                " remote head kept; the next run's ls-remote is the truth"
            )
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
# [(branch, sha)] -> {branch: True | False | PUSH_TIMEOUT}. Never raises for a per-ref failure.
RemoteDelete = Callable[["list[tuple[str, str]]"], "dict[str, object]"]

LS_REMOTE_TIMEOUT_SECS = 60
PUSH_TIMEOUT_SECS = 120
_RC_TIMEOUT = 124
_SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


def _redact(text: object, *extra_tokens: str) -> str:
    """Replace the current GH_TOKEN (and any ``extra_tokens``, e.g. the one a
    runner was created with) and its basic-auth header form with ``***`` so no
    token can reach a log line or exception text (CWE-532)."""
    out = str(text)
    for token in (os.environ.get("GH_TOKEN", ""), *extra_tokens):
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


def make_git_remote(repo: Path, env_fn: "Callable[[], dict[str, str]]") -> RemoteRunner:
    """Runner for git calls that talk to the remote. ``env_fn`` is called on
    EVERY git call so auth is built from the token current at that moment (a
    token rotated mid-run is picked up). The child environment has every trace
    variable and any askpass helper removed (they could log or leak the auth
    header, or prompt as another identity). ``stderr`` of the last call is kept
    redacted on ``run.last_stderr`` for diagnostics."""
    created_token = os.environ.get("GH_TOKEN", "")

    def run(args: Sequence[str], timeout: float = LS_REMOTE_TIMEOUT_SECS) -> "tuple[int, str]":
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GIT_TRACE")
            and k not in ("GIT_CURL_VERBOSE", "GIT_ASKPASS", "SSH_ASKPASS")
        }
        env.update(env_fn())
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
        run.last_stderr = " ".join(_redact(proc.stderr, created_token).split())[:300]  # type: ignore[attr-defined]
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
    if kind == "github":
        token = os.environ.get("GH_TOKEN", "")
        if not token:
            print("WARN: GH_TOKEN unset — remote phase skipped")
            return None
        # Re-read at call time; fall back to the creation-time token only if
        # the variable was cleared mid-run.
        return url, make_git_remote(repo, lambda: _remote_env(os.environ.get("GH_TOKEN") or token))
    return url, make_git_remote(repo, dict)


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


PUSH_TIMEOUT = "timeout"  # per-ref outcome when its push chunk timed out (result unknown)
PUSH_CHUNK = 50  # refs per push: bounds argv size and the blast radius of one timeout


def _push_delete(
    run: RemoteRunner, url: str, items: "list[tuple[str, str]]"
) -> "dict[str, object]":
    """Non-atomic pushes (at most ``PUSH_CHUNK`` refs each, each with its own
    timeout) deleting every (branch, sha), each ref guarded by its own
    ``--force-with-lease=<ref>:<sha>`` (a server-side compare-and-swap). The
    porcelain output is parsed per ref: only a ``-`` (deleted) line for
    ``:refs/heads/<branch>`` counts (``True``); a non-zero rc never overrides it
    and a zero rc never stands in for a missing line. A chunk that timed out
    reports ``PUSH_TIMEOUT`` for its refs (the delete may or may not have landed;
    the next run's ls-remote is the truth); everything else unproven is ``False``."""
    result: "dict[str, object]" = {b: False for b, _ in items}
    for start in range(0, len(items), PUSH_CHUNK):
        chunk = items[start : start + PUSH_CHUNK]
        args = ["push", "--porcelain", "--no-verify"]
        args += [f"--force-with-lease=refs/heads/{b}:{sha}" for b, sha in chunk]
        args += [url]
        args += [f":refs/heads/{b}" for b, _ in chunk]
        rc, out = run(args, PUSH_TIMEOUT_SECS)
        if rc == _RC_TIMEOUT:
            for b, _ in chunk:
                result[b] = PUSH_TIMEOUT
            continue
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] == "-" and parts[1].startswith(":refs/heads/"):
                name = parts[1][len(":refs/heads/") :]
                if name in result:
                    result[name] = True
    return result


# Reap reasons that delete a tip which is neither on base nor contained in a PR head
# (refs/pull/N/head), i.e. the only copy of the work. Decided by reason so a future
# unlanded-deleting rule must be added here explicitly (#2293).
ARCHIVE_REASONS = frozenset({"issue-closed"})
ARCHIVE_PREFIX = "refs/archive/reap/"

# [(branch, sha)] -> {branch: True | False | PUSH_TIMEOUT}. Never raises for a per-ref failure.
RemoteArchive = Callable[["list[tuple[str, str]]"], "dict[str, object]"]


def _archive_ref(branch: str, tip: str) -> str:
    return f"{ARCHIVE_PREFIX}{branch}@{tip[:12]}"


def _write_local_archive(git: GitRunner, branch: str, tip: str) -> bool:
    """Create the archive ref create-only (``update-ref <ref> <tip> ""``). An existing
    ref at the same tip is success (idempotent re-run); anything else, including a
    read-back mismatch, is failure."""
    ref = _archive_ref(branch, tip)
    rc, _ = git(["check-ref-format", ref])
    if rc != 0:
        return False
    rc, _ = git(["update-ref", ref, tip, ""])
    if rc != 0:
        rc, out = git(["rev-parse", "--verify", "-q", ref])
        return rc == 0 and out == tip
    rc, out = git(["rev-parse", "--verify", "-q", ref])
    return rc == 0 and out == tip


def _push_archive(
    run: RemoteRunner, url: str, items: "list[tuple[str, str]]"
) -> "dict[str, object]":
    """Push ``<tip>:refs/archive/reap/<branch>@<tip12>`` for every (branch, tip), without
    force (an existing ref at another sha is rejected). Only a porcelain ``*`` (new) or
    ``=`` (already identical) line for the ref counts as True; a timed-out chunk reports
    ``PUSH_TIMEOUT``; everything else is False. Auth goes through ``run``'s environment."""
    result: "dict[str, object]" = {b: False for b, _ in items}
    dest = {_archive_ref(b, sha): b for b, sha in items}
    for start in range(0, len(items), PUSH_CHUNK):
        chunk = items[start : start + PUSH_CHUNK]
        args = ["push", "--porcelain", "--no-verify", url]
        args += [f"{sha}:{_archive_ref(b, sha)}" for b, sha in chunk]
        rc, out = run(args, PUSH_TIMEOUT_SECS)
        if rc == _RC_TIMEOUT:
            for b, _ in chunk:
                result[b] = PUSH_TIMEOUT
            continue
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] in ("*", "="):
                name = dest.get(parts[1].partition(":")[2])
                if name is not None and any(b == name for b, _ in chunk):
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

# The never-touch list, shared by reap-orphans (rule N2) and delete-head.
PROTECTED_BRANCH_NAMES = ("main", "audit-log")
PROTECTED_BRANCH_PREFIXES = ("release/", "audit/")


def is_protected_branch(name: str) -> bool:
    return name in PROTECTED_BRANCH_NAMES or name.startswith(PROTECTED_BRANCH_PREFIXES)


_WORKER_RE = re.compile(r"worker-(\d+)-")
_ISSUE_REF_RE = re.compile(r"#(\d+)")
# #2287 D4: names of local copies of a PR head (pr-7, pr7-check, pr-7-review...).
# Group 1 is the PR number; the leading number wins (pr1830-809 -> #1830).
REVIEW_RE = re.compile(r"pr-?([1-9][0-9]{0,6})(?:-(?:review|check|new|[0-9]+))?")
# #2287 N2a: overseer audit-record branches (exact prefixes, never the substring "audit").
_AUDIT_BRANCH_PREFIXES = ("chore/audit-overseer-cycle-", "chore/overseer-audit-")
# #2287 N6: paths whose changes are audit records that may exist nowhere else.
_AUDIT_RECORD_PATHS = ("audit/log", "audit/oversight-log.jsonl", "audit/overnight-loop-log.md")

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


def _fmt(
    kind: str,
    d: _Decision,
    *,
    reason: Optional[str] = None,
    with_pr: bool = False,
    archive: Optional[str] = None,
) -> str:
    line = f"{kind} branch={_printable_name(d.ref.name)} reason={reason or d.reason}"
    line += f" where={d.ref.where}"
    if with_pr:
        line += f" pr={d.pr}"
    line += f" tip={d.ref.tip}"
    if archive:
        line += f" archive={archive}"
    return line


def _archived_line(d: _Decision) -> str:
    """Printed after a successful archive write, before the delete. REAPED/REAP-FAILED
    lines must stay byte-identical to the pre-#2293 shape: bin/hos-cron audits them with an
    end-anchored regex, so the archive is reported on its own line instead."""
    ref = _archive_ref(d.ref.name, d.ref.tip)
    return (
        f"ARCHIVED branch={_printable_name(d.ref.name)} where={d.ref.where}"
        f" ref={_printable_name(ref)} tip={d.ref.tip}"
    )


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


def _audit_guard(git: GitRunner, base: str, tip: str) -> Optional[str]:
    """#2287 N6: KEEP reason when ``tip`` adds or changes audit records relative to
    its merge-base with ``base`` ("audit-content"; "git-error" on any git failure),
    else None. Applied before every unlanded deletion (D1', D2, D4)."""
    rc, mb = git(["merge-base", base, tip])
    if rc != 0 or not mb.strip():
        return "git-error"
    rc, out = git(["diff", "--name-only", mb.strip(), tip, "--", *_AUDIT_RECORD_PATHS])
    if rc != 0:
        return "git-error"
    return "audit-content" if out.strip() else None


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
    remote_archive: Optional[RemoteArchive] = None,
    now: Optional[float] = None,
    slug: "Optional[tuple[str, str]]" = None,
    grace_days: int = DEFAULT_GRACE_DAYS,
    dry_run: bool = False,
    do_local: bool = True,
    do_remote: bool = True,
    max_deletions: int = 0,
    base: str = "origin/main",
    remote_scope: str = "worker",
    issue_closed: bool = True,
) -> int:
    """#2286: delete orphaned local branches and remote ``worker-*`` heads
    (``remote_scope="all"``: every remote head, #2288) by PR, issue and content
    state. Every decision is built before anything is deleted;
    any failed listing aborts the whole run with zero deletions (exit 2). Returns
    the process exit code. See TECHNICAL-DESIGN-2286 for the decision table.

    ``--dry-run`` skips the pre-delete open-PR re-check (SUMMARY ``recheck=skipped``),
    so a WOULD-REAP can still become KEEP open-pr in the real run.

    ``issue_closed=False`` (CLI ``--no-issue-closed``, #2288 S3) suppresses rule D2 only:
    a closed-issue branch that has not landed is KEPT as ``issue-closed-unlanded``.

    Archive-before-delete (#2293): a decision whose reason is in ``ARCHIVE_REASONS``
    writes ``refs/archive/reap/<branch>@<tip12>`` first (``remote_archive`` pushes it to
    origin for remote heads) and is KEPT as ``archive-failed`` when that fails."""
    if remote_scope not in ("worker", "all"):
        raise ValueError(f"remote_scope must be 'worker' or 'all', got {remote_scope!r}")
    git = git or make_git(repo)
    now = time.time() if now is None else now
    calls_before = github.gh_call_count()
    grace_secs = grace_days * 86400
    decisions: "list[_Decision]" = []
    counts = {
        "reaped_local": 0,
        "reaped_remote": 0,
        "kept": 0,
        "failed": 0,
        "deferred": 0,
        "archived": 0,
    }
    remote_skipped = 0  # 1 when the remote phase could not run (WARN printed)
    recheck = "skipped" if dry_run else "none"  # "done" once the open-PR re-check ran

    def summary(aborted: int) -> None:
        # New fields are APPENDED: consumers match the leading fields by name.
        print(
            f"SUMMARY reaped_local={counts['reaped_local']} reaped_remote={counts['reaped_remote']}"
            f" kept={counts['kept']} failed={counts['failed']} deferred={counts['deferred']}"
            f" api_calls={github.gh_call_count() - calls_before} aborted={aborted}"
            f" remote_skipped={remote_skipped} recheck={recheck} archived={counts['archived']}"
        )

    try:
        store = store_dir(git, repo)
        current = _current_branch(git)
        base_tree = _git_ok(git, "rev-parse", f"{base}^{{tree}}")
    except GitError as exc:
        print(f"readopt: {_one_line(exc)}", file=sys.stderr)
        summary(1)
        return 2
    recs_by_branch: "dict[str, list[Path]]" = {}
    for branch, rec in read_records(store):
        recs_by_branch.setdefault(branch, []).append(rec)

    def keep(ref: _Ref, reason: str) -> None:
        decisions.append(_Decision(ref, False, reason))

    # ---- remote head listing (one authoritative read; failure skips only the remote phase)
    remote_refs: "list[_Ref]" = []
    if do_remote:
        if remote_heads is None or remote_delete is None:
            ops = _remote_ops(git, repo)
            if ops is not None:
                url, run = ops
                remote_heads = remote_heads or (lambda pat: _ls_remote(run, url, pat))
                remote_delete = remote_delete or (lambda items: _push_delete(run, url, items))
                remote_archive = remote_archive or (lambda items: _push_archive(run, url, items))
            else:
                remote_heads = None
                remote_skipped = 1
        if remote_heads is not None:
            try:
                pattern = "refs/heads/*" if remote_scope == "all" else "refs/heads/worker-*"
                for name, sha in sorted(remote_heads(pattern)):
                    if remote_scope == "all" or name.startswith("worker-"):
                        remote_refs.append(_Ref(name, "remote", sha))
            except Exception as exc:  # the local phase still runs
                remote_skipped = 1
                print(f"WARN: remote head listing failed — remote phase skipped: {_one_line(exc)}")

    local_refs: "list[_Ref]" = []
    local_committed: "dict[str, int]" = {}
    if do_local:
        try:
            out = _git_ok(
                git,
                "for-each-ref",
                "--format=%(refname)%09%(objectname)%09%(committerdate:unix)",
                "refs/heads/",
            )
        except GitError as exc:
            print(f"WARN: listing failed — nothing deleted: {_one_line(exc)}")
            summary(1)
            return 2
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
        if is_protected_branch(name):
            keep(ref, "protected-name")
            continue
        if name.startswith(_AUDIT_BRANCH_PREFIXES):  # N2a (#2287): holds unsynced records
            keep(ref, "audit-branch")
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
            by_number = {p.get("number"): p for p in all_pulls if p.get("number") is not None}
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
                    "by_number": by_number,
                    "prs": prs,
                    "covering": covering,
                    "issue": int(m.group(1)) if m else None,
                    "refs": None,
                }
                if plan["issue"] is not None:
                    needed.add(plan["issue"])
                    if issue_closed:
                        plan["refs"] = _commit_issue_refs(git, base, ref.tip)
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
                    decisions.append(
                        _decide_rest(git, ref, found, states, base, base_tree, issue_closed)
                    )

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
            recheck = "done"
    except (_Abort, GitError) as exc:
        print(f"WARN: listing failed — nothing deleted: {_one_line(exc)}")
        summary(1)
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
                would = _archive_ref(d.ref.name, d.ref.tip) if d.reason in ARCHIVE_REASONS else None
                print(_fmt("WOULD-REAP", d, with_pr=True, archive=would))
                counts["reaped_" + d.ref.where] += 1
            else:
                print(_fmt("KEEP", d))
        summary(0)
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
        needs_archive = d.reason in ARCHIVE_REASONS
        if d.ref.where == "remote":
            # Budget is reserved at selection, before the batched archive push: a remote
            # archive failure still uses its slot, so a later remote ref in the same run
            # may be DEFERRED although nothing was deleted for the failed one. Only ever
            # keeps more; the cap is never exceeded.
            attempted += 1
            remote_batch.append(d)
            continue
        if needs_archive:
            # An archive-failed decision is never attempted as a delete, so it does not
            # consume the --max-deletions budget.
            if _write_local_archive(git, d.ref.name, d.ref.tip):
                print(_archived_line(d))
                counts["archived"] += 1
            else:
                print(_fmt("KEEP", d, reason="archive-failed"))
                counts["kept"] += 1
                continue
        attempted += 1
        if _delete_branch(git, d.ref.name, recs_by_branch.get(d.ref.name, []), d.ref.tip):
            print(_fmt("REAPED", d, with_pr=True))
            counts["reaped_local"] += 1
        else:
            print(_fmt("REAP-FAILED", d, reason="delete-failed"))
            counts["failed"] += 1
    archives: "dict[str, str]" = {}
    to_archive = [d for d in remote_batch if d.reason in ARCHIVE_REASONS]
    if to_archive:
        try:
            if remote_archive is None:
                raise GitError("no remote archive runner")
            archived = remote_archive([(d.ref.name, d.ref.tip) for d in to_archive])
        except Exception as exc:
            print(f"WARN: remote archive failed: {_one_line(exc)}")
            archived = {}
        for d in to_archive:
            if archived.get(d.ref.name) is True:
                archives[d.ref.name] = _archive_ref(d.ref.name, d.ref.tip)
                print(_archived_line(d))
                counts["archived"] += 1
                # Best effort only: the remote copy is what gates the delete.
                if not _write_local_archive(git, d.ref.name, d.ref.tip):
                    print(f"WARN: local archive ref not written for {_printable_name(d.ref.name)}")
            else:
                print(_fmt("KEEP", d, reason="archive-failed"))
                counts["kept"] += 1
        remote_batch = [
            d for d in remote_batch if d.reason not in ARCHIVE_REASONS or d.ref.name in archives
        ]
    if remote_batch and remote_delete is not None:
        try:
            outcome = remote_delete([(d.ref.name, d.ref.tip) for d in remote_batch])
        except Exception as exc:
            print(f"WARN: remote delete failed: {_one_line(exc)}")
            outcome = {}
        if PUSH_TIMEOUT in outcome.values():
            print(
                "WARN: remote push timed out — outcome unknown for the timed-out refs;"
                " the next run's ls-remote is the truth"
            )
        for d in remote_batch:
            got = outcome.get(d.ref.name)
            if got is True:
                print(_fmt("REAPED", d, with_pr=True))
                counts["reaped_remote"] += 1
            else:
                why = "push-timeout" if got == PUSH_TIMEOUT else "cas-or-push-failed"
                print(_fmt("REAP-FAILED", d, reason=why))
                counts["failed"] += 1
    summary(0)
    return 0


def _decide_rest(
    git: GitRunner,
    ref: _Ref,
    plan: dict,
    states: "dict[int, str]",
    base: str,
    base_tree: str,
    issue_closed: bool = True,
) -> _Decision:
    """Rules D1' through the KEEP table for one non-open-PR, non-D1 ref."""
    issue: Optional[int] = plan["issue"]
    state = states.get(issue) if issue is not None else None
    covering: "list[dict]" = plan["covering"]
    closed_cover = [p for p in covering if not p.get("merged_at") and p.get("state") == "closed"]
    protected_by_issue = False
    # N6 (#2287, A12): an unlanded deletion is withheld when the branch carries audit
    # records. The branch then falls through to D3 (landed content is safe to reap) and
    # ends at the KEEP reason held here.
    audit_hold: Optional[str] = None
    if closed_cover:
        if ref.where == "local" and issue is not None and state != "closed":
            protected_by_issue = True  # A1: never delete open-issue work on a closed PR
        else:
            audit_hold = _audit_guard(git, base, ref.tip)
            if audit_hold is None:
                return _Decision(ref, True, "pr-closed", f"#{closed_cover[0].get('number')}")

    d2_blocked = d2_git_error = False
    if issue_closed and issue is not None and state == "closed":
        refs = plan["refs"]
        if refs is None:
            d2_git_error = True
        elif all(states.get(n) == "closed" for n in refs):
            audit_hold = audit_hold or _audit_guard(git, base, ref.tip)
            if audit_hold is None:
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

    # D4 (#2287): a local copy of a PR head that is no PR's own head.ref. Reaped only
    # when that PR's current head contains every commit of the tip (A1: not for a
    # real PR head, whose name merely looks like a review copy).
    review = REVIEW_RE.fullmatch(ref.name)
    if review and not plan["prs"]:
        number = int(review.group(1))
        target = plan["by_number"].get(number)
        if target is None:
            return _Decision(ref, False, "review-pr-unknown")
        if not _covers(git, target, ref.tip):
            return _Decision(ref, False, "review-pr-sha-mismatch")
        guard = audit_hold or _audit_guard(git, base, ref.tip)
        if guard is not None:
            return _Decision(ref, False, guard)
        if target.get("state") == "closed":
            return _Decision(ref, True, "review-pr-done", f"#{number}")
        if target.get("state") == "open":
            return _Decision(ref, True, "review-stale", f"#{number}")
        return _Decision(ref, False, "review-pr-unknown")

    if audit_hold is not None:
        return _Decision(ref, False, audit_hold)
    if protected_by_issue:
        reason = "closed-pr-open-issue"
    elif plan["prs"] and not covering:
        reason = "unlanded-pr-sha-mismatch"
    elif d2_git_error:
        reason = "git-error"
    elif d2_blocked:
        reason = "issue-closed-batch-open"
    elif issue is not None and state == "closed":
        reason = "issue-closed-unlanded"  # only reachable when D2 was suppressed
    elif issue is not None and state is None:
        reason = "issue-unknown"
    elif issue is not None and state == "open":
        reason = "unlanded-open-issue"
    else:
        reason = "unlanded-no-pr"
    return _Decision(ref, False, reason)


# ---------------------------------------------------------------------------
# #2288 delete-head (delete the remote head of one closed PR)
# ---------------------------------------------------------------------------


def _full_name(repo_obj: object) -> str:
    name = repo_obj.get("full_name") if isinstance(repo_obj, dict) else None
    return name.lower() if isinstance(name, str) else ""


def delete_head(
    repo: Path,
    pr_number: int,
    *,
    git: GitRunner,
    get_pull: "Optional[Callable[[int], Optional[dict]]]" = None,
    open_pulls_for: "Optional[Callable[[str], list]]" = None,
    open_pulls_based_on: "Optional[Callable[[str], list]]" = None,
    remote_heads: Optional[RemoteHeads] = None,
    remote_delete: Optional[RemoteDelete] = None,
    slug: "Optional[tuple[str, str]]" = None,
) -> int:
    """Delete the remote head of closed PR ``pr_number``. Prints exactly one
    result line last on stdout and returns 0 (gone), 2 (error) or 3 (KEPT).
    Fails closed: every exception becomes ERROR with nothing deleted."""

    def result(code: int, line: str) -> int:
        print(line)
        return code

    def error(reason: str) -> int:
        return result(2, f"ERROR pr=#{pr_number} reason={reason}")

    branch_shown = "-"

    def kept(reason: str) -> int:
        return result(3, f"KEPT pr=#{pr_number} branch={branch_shown} reason={reason}")

    try:
        owner, name = slug or _slug_from_origin(git)
        pr = (get_pull or (lambda n: github.get_pull(owner, name, n)))(pr_number)
        if not isinstance(pr, dict):
            return error(f"PR #{pr_number} not found")
        raw_base = pr.get("base")
        base: dict = raw_base if isinstance(raw_base, dict) else {}
        raw_head = pr.get("head")
        head: dict = raw_head if isinstance(raw_head, dict) else {}
        raw_base_repo = base.get("repo")
        base_repo: dict = raw_base_repo if isinstance(raw_base_repo, dict) else {}
        if _full_name(base_repo) != f"{owner}/{name}".lower():
            return error("PR is not in this repository")
        ref = head.get("ref")
        if isinstance(ref, str):
            branch_shown = _printable_name(ref)
        if pr.get("state") != "closed":
            return kept("pr-open")
        if _full_name(head.get("repo")) != f"{owner}/{name}".lower():
            return kept("fork")
        if not isinstance(ref, str) or not _SAFE_NAME_RE.fullmatch(ref) or ref.startswith("-"):
            return kept("unsafe-name")
        if is_protected_branch(ref) or ref == base_repo.get("default_branch"):
            return kept("protected-name")
        sha = head.get("sha")
        if not isinstance(sha, str) or not _SHA_RE.fullmatch(sha):
            return error("PR head SHA unreadable")

        if remote_heads is None or remote_delete is None:
            ops = _remote_ops(git, repo)
            if ops is None:
                return error("remote phase unavailable")
            url, run = ops
            remote_heads = remote_heads or (lambda pat: _ls_remote(run, url, pat))
            remote_delete = remote_delete or (lambda items: _push_delete(run, url, items))

        def tips() -> "dict[str, str]":
            return {b: s for b, s in remote_heads(f"refs/heads/{ref}") if b == ref}

        listed = tips()
        if ref not in listed:
            return result(0, f"ALREADY-GONE pr=#{pr_number} branch={branch_shown}")
        if listed[ref] != sha:
            return result(
                3,
                f"KEPT pr=#{pr_number} branch={branch_shown} reason=moved"
                f" expected={sha} tip={listed[ref]}",
            )
        others = (
            open_pulls_for
            or (lambda b: github.list_pulls(owner, name, head=f"{owner}:{b}", state="open"))
        )(ref)
        for other in others:
            other_head = other.get("head") if isinstance(other, dict) else None
            if _full_name(other_head.get("repo") if isinstance(other_head, dict) else None) == (
                f"{owner}/{name}".lower()
            ):
                return kept("open-pr")
        # Deleting a branch auto-closes any open PR that uses it as its base.
        stacked = (
            open_pulls_based_on or (lambda b: github.list_pulls(owner, name, state="open", base=b))
        )(ref)
        if stacked:
            return kept("base-of-open-pr")
        got = remote_delete([(ref, sha)]).get(ref)
        if got is True:
            return result(0, f"DELETED pr=#{pr_number} branch={branch_shown} tip={sha}")
        if got == PUSH_TIMEOUT:
            return error("outcome unknown (push timed out)")
        if ref not in tips():
            return result(0, f"ALREADY-GONE pr=#{pr_number} branch={branch_shown}")
        return error("push rejected (CAS lost or branch protection)")
    except Exception as exc:
        return error(_one_line(_redact(exc)))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


DEFAULT_ARCHIVE_AGE_DAYS = 90


def list_archives(
    repo: Path,
    *,
    git: Optional[GitRunner] = None,
    now: Optional[float] = None,
    age_days: int = DEFAULT_ARCHIVE_AGE_DAYS,
) -> int:
    """#2293: list local ``refs/archive/reap/*``. Read-only: no deletion, no GitHub or
    network call. Git records no ref creation time, so the age is the tip COMMIT's age
    (the same accepted limitation as the remote-head grace)."""
    git = git or make_git(repo)
    now = time.time() if now is None else now
    rc, out = git(
        [
            "for-each-ref",
            "--format=%(refname)%09%(objectname)%09%(committerdate:unix)",
            ARCHIVE_PREFIX,
        ]
    )
    if rc != 0:
        print("readopt: listing archives failed", file=sys.stderr)
        return 2
    total = older = 0
    for line in _lines(out):
        ref, sha, stamp = line.split("\t")
        age = max(0, int((now - int(stamp)) // 86400)) if stamp.isdigit() else -1
        flag = ""
        if age > age_days:
            flag = f" older-than={age_days}d"
            older += 1
        total += 1
        print(f"ARCHIVE ref={_printable_name(ref)} tip={sha} age_days={age}{flag}")
    print(f"ARCHIVES total={total} older={older} threshold_days={age_days}")
    return 0


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


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

    ro.add_argument(
        "--list-archives",
        action="store_true",
        help="#2293: list refs/archive/reap/* with age and exit; deletes nothing. Pruning"
        " archives is a separate human-authorized step",
    )
    ro.add_argument("--archive-age-days", type=_positive_int, default=DEFAULT_ARCHIVE_AGE_DAYS)
    ro.add_argument(
        "--no-issue-closed",
        action="store_true",
        help="do not evaluate rule D2 (issue-closed); unlanded closed-issue branches are kept",
    )
    ro.add_argument(
        "--remote-scope",
        choices=("worker", "all"),
        default=None,
        help="remote heads to consider: worker-* (default) or every head (#2288); the"
        " never-touch list stays fixed (main, audit-log, release/*, audit/*)",
    )

    dh = sub.add_parser("delete-head", help="#2288: delete the remote head of one closed PR")
    dh.add_argument("--pr", type=_positive_int, required=True)

    args = ap.parse_args(argv)
    if args.cmd == "reap-orphans" and args.local_only and args.remote_scope is not None:
        ap.error("--remote-scope cannot be combined with --local-only")
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
        if args.cmd == "delete-head":
            return delete_head(repo, args.pr, git=git)
        if args.cmd == "reap-orphans" and args.list_archives:
            return list_archives(repo, git=git, age_days=args.archive_age_days)
        if args.cmd == "reap-orphans":
            return reap_orphans(
                repo,
                git=git,
                grace_days=args.grace_days,
                dry_run=args.dry_run,
                do_local=not args.remote_only,
                do_remote=not args.local_only,
                max_deletions=args.max_deletions,
                remote_scope=args.remote_scope or "worker",
                issue_closed=not args.no_issue_closed,
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
