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
               one issue, keeping the newest (or an explicitly named) branch.

Usage
-----
  python3 -m scripts.automation.readopt review-path \\
      --original-head <ref> --merged-head <ref> [--base origin/main]
  python3 -m scripts.automation.readopt reap-landed [--dry-run] [--grace-secs 300]
  python3 -m scripts.automation.readopt prune-attempts --issue <N> \\
      [--keep <branch>] [--issue-closed] [--dry-run]

Exit codes
----------
  0 — success (``reap-landed`` exits 0 even when it skipped branches; skips
      are printed as WARN lines)
  2 — git / usage error. For ``review-path`` a caller MUST treat exit 2 as
      ``full`` (fail closed: never skip review on uncertainty).

Safety
------
Only branches that have an ownership record are ever considered by
``reap-landed``; unrecorded leftover branches need a separate, human-authorized
cleanup and are never touched here. The checked-out branch is never deleted.
A branch is never deleted on uncertainty (git or GitHub failure -> skip).
"""
from __future__ import annotations

import argparse
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional, Sequence

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
    REAPED/REAP-FAILED line in the output the cron hook parses (CWE-117)."""
    return " ".join(str(exc).split())[:300]


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
) -> "list[str]":
    """Delete local ``worker-<issue>-*`` attempts. Closed issue: delete all,
    but only after the issue's state is verified ``closed`` server-side (an
    open issue or a failed lookup raises GitError and deletes nothing).
    Otherwise keep ``keep`` (must exist) or the newest tip, delete the rest.
    The checked-out branch is never deleted. Raises GitError on git failure or
    an unknown ``keep``."""
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
    for branch in sorted(doomed):
        if branch == current:
            print(f"WARN: '{branch}' is checked out — not deleting")
            continue
        recs = [rec for b, rec in records if b == branch]
        if dry_run:
            print(f"WOULD-DELETE branch={branch}")
            deleted.append(branch)
        elif _delete_branch(git, branch, recs, tips[branch]):
            print(f"DELETED branch={branch}")
            deleted.append(branch)
        else:
            print(f"WARN: could not delete '{branch}'")
    return deleted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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
