"""Tests for scripts/automation/readopt.py (#2126, D-7 / D-8).

Real temp git repositories (with a bare origin) are used for the git-facing
behaviour; the GitHub PR lookup is injected so no test touches the network.
"""

import base64
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from scripts.automation import readopt
from scripts.framework import select_work_candidates as swc

IDENT = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *IDENT, *args],
        capture_output=True,
        text=True,
        check=check,
    )
    return proc.stdout.strip()


def commit(repo: Path, name: str, text: str, msg: str) -> str:
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q")
    git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    commit(work, "a.txt", "".join(f"{i}\n" for i in range(1, 10)), "init a")
    commit(work, "b.txt", "b\n", "init b")
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "origin", "main")
    git(work, "fetch", "-q", "origin")
    return work


def write_record(repo: Path, branch: str, age_secs: int = 3600) -> Path:
    store = readopt.store_dir(readopt.make_git(repo), repo)
    store.mkdir(parents=True, exist_ok=True)
    rec = store / (branch.replace("%", "%25").replace("/", "%2F") + ".rec")
    rec.write_text(f"schema=1\nbranch={branch}\ncycle_id=c-1\nrole=worker\ncreated_at=x\n")
    old = rec.stat().st_mtime - age_secs
    os.utime(rec, (old, old))
    return rec


def make_branch(repo: Path, name: str, fname: str = "a.txt", text: str = "work\n") -> str:
    git(repo, "checkout", "-q", "-b", name, "main")
    tip = commit(repo, fname, text, f"work on {name}")
    git(repo, "checkout", "-q", "main")
    return tip


def advance_main(repo: Path, fname: str, text: str) -> None:
    git(repo, "checkout", "-q", "main")
    commit(repo, fname, text, f"main touches {fname}")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")


def branches(repo: Path) -> set:
    return set(git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines())


# --- D-7 decision rule ------------------------------------------------------


def test_decide_touched_reviewed_file_is_full():
    path, reason = readopt.decide_review_path(["a.py", "b.py"], ["b.py", "z.py"], [])
    assert path == "full"
    assert "b.py" in reason


def test_decide_added_commit_is_full():
    path, reason = readopt.decide_review_path(["a.py"], ["z.py"], ["abc123"])
    assert path == "full"
    assert "1 new commit" in reason


def test_decide_neither_is_delta():
    assert readopt.decide_review_path(["a.py"], ["z.py"], [], "")[0] == "delta"
    assert readopt.decide_review_path([], [], [])[0] == "delta"


def test_decide_unexplained_change_is_full():
    path, reason = readopt.decide_review_path([], [], [], "merge had conflicts: x.py")
    assert (path, reason) == ("full", "merge had conflicts: x.py")


# --- review-path on a real repo --------------------------------------------


def _merged_scenario(repo: Path, main_file: str) -> "tuple[str, str]":
    original = make_branch(repo, "worker-1-x", "a.txt")
    advance_main(repo, main_file, "new\n")
    git(repo, "checkout", "-q", "worker-1-x")
    git(repo, "merge", "-q", "--no-edit", "origin/main")
    merged = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    return original, merged


def test_review_path_unrelated_merge_is_delta(repo):
    original, merged = _merged_scenario(repo, "b.txt")
    path, _ = readopt.compute_review_path(readopt.make_git(repo), original, merged)
    assert path == "delta"


def test_review_path_merge_touching_reviewed_file_is_full(repo):
    lines = [f"{i}\n" for i in range(1, 10)]
    original = make_branch(repo, "worker-1-x", "a.txt", "".join(["edited\n"] + lines[1:]))
    advance_main(repo, "a.txt", "".join(lines[:-1] + ["main edit\n"]))
    git(repo, "checkout", "-q", "worker-1-x")
    git(repo, "merge", "-q", "--no-edit", "origin/main")
    merged = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    path, reason = readopt.compute_review_path(readopt.make_git(repo), original, merged)
    assert path == "full"
    assert "a.txt" in reason


def _older_main_already_merged(repo: Path) -> str:
    """Branch edits line 1 of a.txt, merges an OLDER main (which added c.txt);
    returns that merge commit as the originally reviewed head."""
    lines = [f"{i}\n" for i in range(1, 10)]
    git(repo, "checkout", "-q", "-b", "worker-1-x", "main")
    commit(repo, "a.txt", "".join(["edited\n"] + lines[1:]), "branch work")
    git(repo, "checkout", "-q", "main")
    advance_main(repo, "c.txt", "from older main\n")
    git(repo, "checkout", "-q", "worker-1-x")
    git(repo, "merge", "-q", "--no-edit", "origin/main")
    original = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    return original


def _merge_main_again(repo: Path) -> str:
    git(repo, "checkout", "-q", "worker-1-x")
    git(repo, "merge", "-q", "--no-edit", "origin/main")
    merged = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    return merged


def test_review_path_older_main_merged_then_unrelated_change_is_delta(repo):
    original = _older_main_already_merged(repo)
    advance_main(repo, "b.txt", "main moved on\n")
    merged = _merge_main_again(repo)
    path, _ = readopt.compute_review_path(readopt.make_git(repo), original, merged)
    assert path == "delta"


def test_review_path_older_main_merged_then_reviewed_file_change_is_full(repo):
    original = _older_main_already_merged(repo)
    lines = [f"{i}\n" for i in range(1, 10)]
    advance_main(repo, "a.txt", "".join(lines[:-1] + ["main edit\n"]))
    merged = _merge_main_again(repo)
    path, reason = readopt.compute_review_path(readopt.make_git(repo), original, merged)
    assert path == "full"
    assert "a.txt" in reason


def test_review_path_file_from_older_main_merge_is_not_reviewed(repo):
    original = _older_main_already_merged(repo)
    advance_main(repo, "c.txt", "from older main\nchanged later\n")
    merged = _merge_main_again(repo)
    path, reason = readopt.compute_review_path(readopt.make_git(repo), original, merged)
    assert path == "delta"
    assert "c.txt" not in reason


def test_review_path_added_commit_is_full(repo):
    original, _ = _merged_scenario(repo, "b.txt")
    git(repo, "checkout", "-q", "worker-1-x")
    commit(repo, "d.txt", "d\n", "extra work")
    merged = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    path, reason = readopt.compute_review_path(readopt.make_git(repo), original, merged)
    assert path == "full"
    # The extra commit's file is now reported as an unexplained tree change
    # (checked before the added-commit rule, which decide_review_path still covers).
    assert "d.txt" in reason


def test_review_path_cli_git_error_exits_2(repo, capsys):
    rc = readopt.main(
        [
            "--repo",
            str(repo),
            "review-path",
            "--original-head",
            "nope",
            "--merged-head",
            "nope2",
        ]
    )
    assert rc == 2


def test_review_path_cli_prints_lines(repo, capsys):
    original, merged = _merged_scenario(repo, "b.txt")
    rc = readopt.main(
        [
            "--repo",
            str(repo),
            "review-path",
            "--original-head",
            original,
            "--merged-head",
            merged,
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "REVIEW_PATH=delta" in out
    assert "REASON=" in out


def test_review_path_cli_rejects_option_like_ref(repo):
    rc = readopt.main(
        [
            "--repo",
            str(repo),
            "review-path",
            "--original-head=--output=x",
            "--merged-head",
            "HEAD",
        ]
    )
    assert rc == 2


# --- reap-landed ------------------------------------------------------------


def no_pr(branch, tip):
    return False


def boom(branch, tip):
    raise RuntimeError("api down")


def land_into_main(repo: Path, branch: str) -> None:
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-edit", branch)
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")


def test_reap_landed_by_ancestry(repo):
    make_branch(repo, "worker-5-x")
    rec = write_record(repo, "worker-5-x")
    land_into_main(repo, "worker-5-x")
    reaped = readopt.reap_landed(repo, pr_lookup=no_pr)
    assert reaped == ["worker-5-x"]
    assert "worker-5-x" not in branches(repo)
    assert not rec.exists()


def test_reap_landed_by_merged_pr_matching_sha(repo):
    tip = make_branch(repo, "worker-6-x")
    rec = write_record(repo, "worker-6-x")
    seen = []

    def lookup(branch, sha):
        seen.append((branch, sha))
        return True

    reaped = readopt.reap_landed(repo, pr_lookup=lookup)
    assert reaped == ["worker-6-x"]
    assert seen == [("worker-6-x", tip)]
    assert "worker-6-x" not in branches(repo)
    assert not rec.exists()


def test_reap_keeps_unlanded_branch(repo):
    make_branch(repo, "worker-7-x")
    rec = write_record(repo, "worker-7-x")
    assert readopt.reap_landed(repo, pr_lookup=no_pr) == []
    assert "worker-7-x" in branches(repo)
    assert rec.exists()


def test_reap_keeps_branch_within_grace(repo):
    make_branch(repo, "worker-8-x")
    rec = write_record(repo, "worker-8-x", age_secs=10)
    land_into_main(repo, "worker-8-x")
    assert readopt.reap_landed(repo, pr_lookup=no_pr) == []
    assert "worker-8-x" in branches(repo)
    assert rec.exists()


def test_reap_never_touches_unrecorded_branch(repo):
    make_branch(repo, "worker-9-x")
    land_into_main(repo, "worker-9-x")
    assert readopt.reap_landed(repo, pr_lookup=lambda b, t: True) == []
    assert "worker-9-x" in branches(repo)


def test_reap_pr_lookup_failure_keeps_branch(repo, capsys):
    make_branch(repo, "worker-10-x")
    rec = write_record(repo, "worker-10-x")
    assert readopt.reap_landed(repo, pr_lookup=boom) == []
    assert "worker-10-x" in branches(repo)
    assert rec.exists()
    assert "WARN" in capsys.readouterr().out


def test_reap_skips_checked_out_branch(repo):
    make_branch(repo, "worker-11-x")
    write_record(repo, "worker-11-x")
    land_into_main(repo, "worker-11-x")
    git(repo, "checkout", "-q", "worker-11-x")
    assert readopt.reap_landed(repo, pr_lookup=no_pr) == []
    assert "worker-11-x" in branches(repo)


def test_reap_dry_run_deletes_nothing(repo):
    make_branch(repo, "worker-12-x")
    rec = write_record(repo, "worker-12-x")
    land_into_main(repo, "worker-12-x")
    assert readopt.reap_landed(repo, pr_lookup=no_pr, dry_run=True) == ["worker-12-x"]
    assert "worker-12-x" in branches(repo)
    assert rec.exists()


# --- prune-attempts ---------------------------------------------------------


def make_dated_branch(repo: Path, name: str, date: str) -> None:
    git(repo, "checkout", "-q", "-b", name, "main")
    (repo / "a.txt").write_text(name)
    git(repo, "add", "a.txt")
    env = {**os.environ, "GIT_COMMITTER_DATE": date, "GIT_AUTHOR_DATE": date}
    subprocess.run(
        ["git", "-C", str(repo), *IDENT, "commit", "-q", "-m", name],
        check=True,
        env=env,
        capture_output=True,
    )
    git(repo, "checkout", "-q", "main")


def closed(issue):
    return "closed"


@pytest.fixture
def attempts(repo):
    make_dated_branch(repo, "worker-20-old", "2026-01-01T00:00:00Z")
    make_dated_branch(repo, "worker-20-new", "2026-03-01T00:00:00Z")
    make_dated_branch(repo, "worker-20-mid", "2026-02-01T00:00:00Z")
    make_dated_branch(repo, "worker-201-other", "2026-04-01T00:00:00Z")
    return repo


def test_prune_keeps_newest_and_deletes_duplicates_and_records(attempts):
    rec_old = write_record(attempts, "worker-20-old")
    deleted = readopt.prune_attempts(attempts, 20)
    assert sorted(deleted) == ["worker-20-mid", "worker-20-old"]
    assert branches(attempts) >= {"worker-20-new", "worker-201-other", "main"}
    assert not rec_old.exists()


def test_prune_keep_honored(attempts):
    deleted = readopt.prune_attempts(attempts, 20, keep="worker-20-old")
    assert sorted(deleted) == ["worker-20-mid", "worker-20-new"]
    assert "worker-20-old" in branches(attempts)


def test_prune_keep_unknown_errors(attempts):
    with pytest.raises(readopt.GitError):
        readopt.prune_attempts(attempts, 20, keep="worker-20-ghost")
    assert "worker-20-old" in branches(attempts)


def test_prune_issue_closed_deletes_all_but_not_other_issue(attempts):
    deleted = readopt.prune_attempts(attempts, 20, issue_closed=True, issue_state=closed)
    assert sorted(deleted) == ["worker-20-mid", "worker-20-new", "worker-20-old"]
    assert "worker-201-other" in branches(attempts)


def _no_lookup(needed):
    raise AssertionError("issue_states must not be called when no commit references another issue")


def _ref_attempts(repo, ref_msg="also carries #77 work"):
    """worker-20-* attempts: 'old' references another issue in a commit message."""
    git(repo, "checkout", "-q", "worker-20-old")
    commit(repo, "x.txt", "x\n", ref_msg)
    git(repo, "checkout", "-q", "main")
    return repo


def test_prune_closed_no_refs_makes_no_lookup(attempts):
    deleted = readopt.prune_attempts(
        attempts, 20, issue_closed=True, issue_state=closed, issue_states=_no_lookup
    )
    assert sorted(deleted) == ["worker-20-mid", "worker-20-new", "worker-20-old"]


def test_prune_closed_keeps_attempt_referencing_open_issue(attempts, capsys):
    _ref_attempts(attempts)
    calls = []

    def states(needed):
        calls.append(set(needed))
        return {77: "open"}

    deleted = readopt.prune_attempts(
        attempts, 20, issue_closed=True, issue_state=closed, issue_states=states
    )
    out = capsys.readouterr().out
    assert sorted(deleted) == ["worker-20-mid", "worker-20-new"]
    assert "worker-20-old" in branches(attempts)
    assert "WARN: 'worker-20-old' kept" in out and "#77 (open)" in out
    assert calls == [{77}]


def test_prune_closed_deletes_attempt_whose_other_ref_is_closed(attempts):
    _ref_attempts(attempts)
    deleted = readopt.prune_attempts(
        attempts, 20, issue_closed=True, issue_state=closed, issue_states=lambda n: {77: "closed"}
    )
    assert "worker-20-old" in deleted
    assert "worker-20-old" not in branches(attempts)


def test_prune_closed_lookup_failure_keeps_attempt(attempts, capsys):
    _ref_attempts(attempts)

    def boom(needed):
        raise RuntimeError("api down")

    deleted = readopt.prune_attempts(
        attempts, 20, issue_closed=True, issue_state=closed, issue_states=boom
    )
    out = capsys.readouterr().out
    assert sorted(deleted) == ["worker-20-mid", "worker-20-new"]
    assert "worker-20-old" in branches(attempts)
    assert "WARN: 'worker-20-old' kept" in out and "api down" in out


def test_prune_closed_unknown_other_issue_keeps_attempt(attempts, capsys):
    _ref_attempts(attempts)
    deleted = readopt.prune_attempts(
        attempts, 20, issue_closed=True, issue_state=closed, issue_states=lambda n: {}
    )
    assert "worker-20-old" not in deleted
    assert "worker-20-old" in branches(attempts)
    assert "#77 (unknown)" in capsys.readouterr().out


def test_prune_closed_dry_run_skips_open_ref_attempt(attempts, capsys):
    _ref_attempts(attempts)
    deleted = readopt.prune_attempts(
        attempts,
        20,
        issue_closed=True,
        dry_run=True,
        issue_state=closed,
        issue_states=lambda n: {77: "open"},
    )
    out = capsys.readouterr().out
    assert "WOULD-DELETE branch=worker-20-old" not in out
    assert "WOULD-DELETE branch=worker-20-new" in out
    assert "worker-20-old" not in deleted


def test_prune_closed_git_error_on_ref_scan_keeps_attempts(attempts, capsys):
    run = _failing_git(attempts, fail_prefix=("log", "--format=%B"))
    deleted = readopt.prune_attempts(
        attempts, 20, git=run, issue_closed=True, issue_state=closed, issue_states=_no_lookup
    )
    out = capsys.readouterr().out
    assert deleted == []
    assert "WARN: 'worker-20-old' kept" in out and "git error" in out
    assert {"worker-20-old", "worker-20-mid", "worker-20-new"} <= branches(attempts)


def _ref_commit(repo, branch, msg):
    git(repo, "checkout", "-q", branch)
    commit(repo, f"{branch}.txt", "x\n", msg)
    git(repo, "checkout", "-q", "main")


def test_prune_closed_self_reference_only_makes_no_lookup(attempts):
    _ref_commit(attempts, "worker-20-old", "fix #20 again")
    deleted = readopt.prune_attempts(
        attempts, 20, issue_closed=True, issue_state=closed, issue_states=_no_lookup
    )
    assert "worker-20-old" in deleted


def test_prune_closed_batches_one_lookup_with_union_and_mixes_outcomes(attempts, capsys):
    _ref_commit(attempts, "worker-20-old", "carries #77")
    _ref_commit(attempts, "worker-20-mid", "carries #77 and #88")
    calls = []

    def states(needed):
        calls.append(set(needed))
        return {77: "closed", 88: "open"}

    deleted = readopt.prune_attempts(
        attempts, 20, issue_closed=True, issue_state=closed, issue_states=states
    )
    out = capsys.readouterr().out
    assert calls == [{77, 88}]
    assert sorted(deleted) == ["worker-20-new", "worker-20-old"]
    assert "worker-20-mid" in branches(attempts)
    assert "WARN: 'worker-20-mid' kept" in out and "#88 (open)" in out
    assert "#77 (" not in out


def test_prune_closed_kept_attempt_never_reaches_remote_step(attempts, capsys):
    _ref_commit(attempts, "worker-20-old", "carries #77")
    for n in ("old", "new", "mid"):
        push_branch(attempts, f"worker-20-{n}")
    readopt.prune_attempts(
        attempts,
        20,
        issue_closed=True,
        issue_state=closed,
        issue_states=lambda n: {77: "open"},
        slug=SLUG,
        open_pr=_no_open_pr,
    )
    out = lines_of(capsys)
    assert "DELETED branch=worker-20-new where=remote" in out
    assert not any("worker-20-old" in ln and "where=remote" in ln for ln in out)
    assert "worker-20-old" in set(remote_heads_of(attempts, "refs/heads/worker-20-*"))
    assert "worker-20-old" in branches(attempts)


def test_prune_closed_cli_plumbs_ref_guard(attempts, monkeypatch):
    _ref_commit(attempts, "worker-20-old", "carries #77")
    monkeypatch.setattr(readopt, "github_issue_state", lambda git: closed)
    monkeypatch.setattr(readopt, "_slug_from_origin", lambda git: ("o", "r"))
    monkeypatch.setattr(readopt, "_github_issue_states", lambda slug: lambda n: {77: "open"})
    rc = readopt.main(
        ["--repo", str(attempts), "prune-attempts", "--issue", "20", "--issue-closed"]
    )
    assert rc == 0
    assert "worker-20-old" in branches(attempts)
    assert "worker-20-new" not in branches(attempts)


def test_prune_never_deletes_checked_out_branch(attempts):
    git(attempts, "checkout", "-q", "worker-20-old")
    deleted = readopt.prune_attempts(attempts, 20, issue_closed=True, issue_state=closed)
    assert "worker-20-old" not in deleted
    assert "worker-20-old" in branches(attempts)


def test_prune_dry_run(attempts):
    deleted = readopt.prune_attempts(attempts, 20, dry_run=True)
    assert len(deleted) == 2
    assert "worker-20-old" in branches(attempts)


def test_prune_issue_closed_refused_when_issue_open(attempts):
    with pytest.raises(readopt.GitError, match="refused"):
        readopt.prune_attempts(attempts, 20, issue_closed=True, issue_state=lambda n: "open")
    assert {"worker-20-old", "worker-20-mid", "worker-20-new"} <= branches(attempts)


def test_prune_issue_closed_refused_when_lookup_fails(attempts):
    def fail(n):
        raise RuntimeError("api down")

    with pytest.raises(readopt.GitError, match="cannot verify"):
        readopt.prune_attempts(attempts, 20, issue_closed=True, issue_state=fail)
    assert "worker-20-old" in branches(attempts)


def test_prune_issue_closed_cli_refuses_without_network(attempts, monkeypatch):
    monkeypatch.setattr(readopt, "github_issue_state", lambda git: lambda n: "open")
    rc = readopt.main(
        ["--repo", str(attempts), "prune-attempts", "--issue", "20", "--issue-closed"]
    )
    assert rc == 2
    assert "worker-20-old" in branches(attempts)


def test_prune_warns_when_choosing_without_keep(attempts, capsys):
    readopt.prune_attempts(attempts, 20, dry_run=True)
    out = capsys.readouterr().out
    assert "WARN: no --keep given; keeping 'worker-20-new'" in out
    assert "escalation comment" in out


def test_prune_no_warn_with_keep(attempts, capsys):
    readopt.prune_attempts(attempts, 20, keep="worker-20-new", dry_run=True)
    assert "no --keep given" not in capsys.readouterr().out


# --- lookup cost bound ------------------------------------------------------


def test_reap_lookup_cap_bounds_api_calls(repo, capsys):
    for i in range(5):
        make_branch(repo, f"worker-3{i}-x")
        write_record(repo, f"worker-3{i}-x")
    calls = []

    def lookup(branch, tip):
        calls.append(branch)
        return False

    assert readopt.reap_landed(repo, pr_lookup=lookup, max_lookups=2) == []
    assert len(calls) == 2
    assert "cap (2) reached" in capsys.readouterr().out


def _unlanded_branches(repo, n):
    names = [f"worker-8{i}-x" for i in range(n)]
    for name in names:
        make_branch(repo, name)
        write_record(repo, name)
    return names


def _looked_up(repo, seed, cap):
    calls = []
    readopt.reap_landed(
        repo,
        pr_lookup=lambda b, t: calls.append(b) or False,
        max_lookups=cap,
        seed=seed,
    )
    return calls


def test_reap_lookup_cap_prints_exactly_one_cap_line(repo, capsys):
    _unlanded_branches(repo, 5)
    readopt.reap_landed(repo, pr_lookup=no_pr, max_lookups=2, seed=1)
    out = capsys.readouterr().out
    cap_lines = [ln for ln in out.splitlines() if "PR-lookup cap" in ln]
    assert cap_lines == ["WARN: PR-lookup cap (2) reached — 3 branch(es) deferred to a later cycle"]


def test_reap_lookup_subset_depends_on_seed(repo):
    _unlanded_branches(repo, 8)
    subsets = {frozenset(_looked_up(repo, seed, 2)) for seed in range(12)}
    assert len(subsets) > 1


def test_reap_lookup_same_seed_is_deterministic(repo):
    _unlanded_branches(repo, 8)
    assert _looked_up(repo, 7, 3) == _looked_up(repo, 7, 3)


def test_reap_lookup_coverage_rotates_to_every_candidate(repo):
    names = _unlanded_branches(repo, 8)
    seen = set()
    for seed in range(40):
        seen.update(_looked_up(repo, seed, 2))
    assert seen == set(names)


def test_reap_cheap_checks_run_for_all_records_despite_cap(repo):
    _unlanded_branches(repo, 4)
    make_branch(repo, "worker-89-x")
    write_record(repo, "worker-89-x", age_secs=100000)
    land_into_main(repo, "worker-89-x")
    assert readopt.reap_landed(repo, pr_lookup=no_pr, max_lookups=0, seed=0) == ["worker-89-x"]


def test_reap_ancestry_landed_makes_no_lookup(repo):
    make_branch(repo, "worker-42-x")
    write_record(repo, "worker-42-x")
    land_into_main(repo, "worker-42-x")
    readopt.reap_landed(repo, pr_lookup=boom, max_lookups=0)
    assert "worker-42-x" not in branches(repo)


def test_production_lookup_empty_github_response_keeps_branch(repo, monkeypatch):
    git_run = readopt.make_git(repo)
    git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
    make_branch(repo, "worker-43-x")
    rec = write_record(repo, "worker-43-x")
    monkeypatch.setattr(readopt.github, "list_pulls", lambda *a, **k: [])
    assert readopt.reap_landed(repo, git=git_run) == []
    assert "worker-43-x" in branches(repo)
    assert rec.exists()


def test_production_lookup_github_error_keeps_branch(repo, monkeypatch):
    git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
    make_branch(repo, "worker-44-x")
    write_record(repo, "worker-44-x")

    def err(*a, **k):
        raise readopt.github.GitHubError("boom")

    monkeypatch.setattr(readopt.github, "list_pulls", err)
    assert readopt.reap_landed(repo) == []
    assert "worker-44-x" in branches(repo)


def test_review_path_unexpected_exception_exits_2(repo, monkeypatch):
    def explode(*a, **k):
        raise ValueError("surprise")

    monkeypatch.setattr(readopt, "compute_review_path", explode)
    rc = readopt.main(
        [
            "--repo",
            str(repo),
            "review-path",
            "--original-head",
            "HEAD",
            "--merged-head",
            "HEAD",
        ]
    )
    assert rc == 2


# --- review hardening -------------------------------------------------------


def test_circuit_breaker_stops_lookups_after_two_consecutive_failures(repo, capsys):
    for i in range(4):
        make_branch(repo, f"worker-5{i}-x")
        write_record(repo, f"worker-5{i}-x")
    make_branch(repo, "worker-59-x")
    write_record(repo, "worker-59-x", age_secs=100000)
    land_into_main(repo, "worker-59-x")
    calls = []

    def failing(branch, tip):
        calls.append(branch)
        raise RuntimeError("api down")

    reaped = readopt.reap_landed(repo, pr_lookup=failing)
    out = capsys.readouterr().out
    assert len(calls) == 2
    assert out.count("PR lookups aborted after 2 consecutive failures") == 1
    assert reaped == ["worker-59-x"]  # ancestry reap still works
    assert "lookups=2" in out and "lookup_failures=2" in out


def test_breaker_resets_on_success(repo, capsys):
    for i in range(3):
        make_branch(repo, f"worker-6{i}-x")
        write_record(repo, f"worker-6{i}-x", age_secs=1000 * (i + 1))
    results = iter([RuntimeError("x"), False, RuntimeError("y")])

    def flaky(branch, tip):
        r = next(results)
        if isinstance(r, Exception):
            raise r
        return r

    readopt.reap_landed(repo, pr_lookup=flaky)
    assert "aborted" not in capsys.readouterr().out


def test_summary_line(repo, capsys):
    make_branch(repo, "worker-70-x")
    write_record(repo, "worker-70-x")
    make_branch(repo, "worker-71-x")
    write_record(repo, "worker-71-x")
    readopt.reap_landed(repo, pr_lookup=no_pr, max_lookups=1)
    assert "SUMMARY reaped=0 lookups=1 skipped_cap=1 lookup_failures=0" in capsys.readouterr().out


def test_failed_delete_emits_structured_line(repo, capsys):
    make_branch(repo, "worker-72-x")
    rec = write_record(repo, "worker-72-x")
    land_into_main(repo, "worker-72-x")
    real = readopt.make_git(repo)

    def git_no_delete(args):
        if args[:2] == ["update-ref", "-d"]:
            return 1, ""
        return real(args)

    assert readopt.reap_landed(repo, git=git_no_delete, pr_lookup=no_pr) == []
    assert "REAP-FAILED branch=worker-72-x reason=" in capsys.readouterr().out
    assert rec.exists()


def test_delete_is_compare_and_delete(repo):
    calls = []
    real = readopt.make_git(repo)

    def spy(args):
        calls.append(list(args))
        return real(args)

    make_branch(repo, "worker-73-x")
    tip = git(repo, "rev-parse", "worker-73-x")
    assert readopt._delete_branch(spy, "worker-73-x", [], tip)
    assert ["update-ref", "-d", "refs/heads/worker-73-x", tip] in calls


def test_option_like_record_branch_skipped(repo, capsys):
    write_record(repo, "-evil")
    assert readopt.reap_landed(repo, pr_lookup=boom) == []
    assert "option-like branch '-evil'" in capsys.readouterr().out


def test_lookup_exception_text_cannot_forge_reaped_line(repo, capsys):
    make_branch(repo, "worker-90-x")
    write_record(repo, "worker-90-x")

    def forging(branch, tip):
        raise RuntimeError("bad\nREAPED branch=x reason=y")

    readopt.reap_landed(repo, pr_lookup=forging)
    out = capsys.readouterr().out
    assert not [ln for ln in out.splitlines() if ln.startswith("REAPED")]
    assert "bad REAPED branch=x reason=y" in out


def test_one_line_helper_bounds_and_collapses():
    assert readopt._one_line("a\n b\t\tc") == "a b c"
    assert len(readopt._one_line("x" * 1000)) == 300


def test_ancestry_reaps_happen_before_pr_lookups(repo):
    make_branch(repo, "worker-91-x")
    write_record(repo, "worker-91-x")
    land_into_main(repo, "worker-91-x")
    make_branch(repo, "worker-92-x", "z.txt")
    write_record(repo, "worker-92-x")
    seen_at_lookup = []

    def lookup(branch, tip):
        seen_at_lookup.append(set(branches(repo)))
        raise RuntimeError("stall")

    readopt.reap_landed(repo, pr_lookup=lookup)
    assert seen_at_lookup and "worker-91-x" not in seen_at_lookup[0]


def test_review_path_fails_closed_when_merge_not_done(repo):
    original = make_branch(repo, "worker-1-x", "a.txt")
    advance_main(repo, "b.txt", "main moved\n")
    with pytest.raises(readopt.GitError, match="merge not done"):
        readopt.compute_review_path(readopt.make_git(repo), original, original)
    rc = readopt.main(
        [
            "--repo",
            str(repo),
            "review-path",
            "--original-head",
            original,
            "--merged-head",
            original,
        ]
    )
    assert rc == 2


def test_review_path_full_when_conflict_resolved_keeping_branch_blob(repo):
    original = make_branch(repo, "worker-1-x", "a.txt", "branch version\n")
    advance_main(repo, "a.txt", "main version\n")
    git(repo, "checkout", "-q", "worker-1-x")
    git(repo, "merge", "-q", "--no-edit", "-s", "ours", "origin/main")
    merged = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    assert git(repo, "diff", "--name-only", original, merged) == ""  # blob unchanged
    path, reason = readopt.compute_review_path(readopt.make_git(repo), original, merged)
    assert path == "full"
    assert "a.txt" in reason


def advance_branch_tip(repo: Path, branch: str) -> str:
    tree = git(repo, "rev-parse", f"{branch}^{{tree}}")
    parent = git(repo, "rev-parse", branch)
    new = git(repo, "commit-tree", tree, "-p", parent, "-m", "moved during lookup")
    git(repo, "update-ref", f"refs/heads/{branch}", new)
    return new


def test_reap_refuses_when_branch_advanced_during_lookup(repo, capsys):
    make_branch(repo, "worker-95-x")
    rec = write_record(repo, "worker-95-x")
    moved = []

    def lookup(branch, tip):
        moved.append(advance_branch_tip(repo, branch))
        return True

    assert readopt.reap_landed(repo, pr_lookup=lookup) == []
    assert git(repo, "rev-parse", "worker-95-x") == moved[0]
    assert rec.exists()
    assert "REAP-FAILED branch=worker-95-x" in capsys.readouterr().out


def test_reap_skips_branch_checked_out_in_other_worktree(repo, tmp_path, capsys):
    make_branch(repo, "worker-96-x")
    rec = write_record(repo, "worker-96-x")
    land_into_main(repo, "worker-96-x")
    git(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "worker-96-x")
    assert readopt.reap_landed(repo, pr_lookup=no_pr) == []
    assert "worker-96-x" in branches(repo)
    assert rec.exists()
    assert "checked out in a worktree" in capsys.readouterr().out


def test_prune_compare_and_delete_refuses_moved_branch(attempts, monkeypatch):
    real = readopt._delete_branch
    moved = {}

    def racing(git_runner, branch, recs, sha):
        if branch == "worker-20-old":
            moved["tip"] = advance_branch_tip(attempts, branch)
        return real(git_runner, branch, recs, sha)

    monkeypatch.setattr(readopt, "_delete_branch", racing)
    deleted = readopt.prune_attempts(attempts, 20)
    assert "worker-20-old" not in deleted
    assert git(attempts, "rev-parse", "worker-20-old") == moved["tip"]


def test_review_path_merge_commit_hiding_extra_file_is_full(repo):
    original = make_branch(repo, "worker-1-x", "a.txt")
    advance_main(repo, "b.txt", "main moved\n")
    git(repo, "checkout", "-q", "worker-1-x")
    git(repo, "merge", "-q", "--no-edit", "origin/main")
    (repo / "evil.sh").write_text("echo pwned\n")
    git(repo, "add", "evil.sh")
    git(repo, "commit", "-q", "--amend", "--no-edit")  # still a 2-parent merge
    merged = git(repo, "rev-parse", "HEAD")
    assert len(git(repo, "rev-list", "--parents", "-n1", merged).split()) == 3
    git(repo, "checkout", "-q", "main")
    path, reason = readopt.compute_review_path(readopt.make_git(repo), original, merged)
    assert path == "full"
    assert "independent merge" in reason and "evil.sh" in reason


def test_review_path_conflicted_merge_is_full(repo):
    original = make_branch(repo, "worker-1-x", "a.txt", "branch version\n")
    advance_main(repo, "a.txt", "main version\n")
    git(repo, "checkout", "-q", "worker-1-x")
    git(repo, "merge", "-q", "--no-edit", "-s", "ours", "origin/main")
    merged = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    path, reason = readopt.compute_review_path(readopt.make_git(repo), original, merged)
    assert path == "full"
    assert reason == "merge had conflicts: a.txt"


def test_review_path_newer_base_not_merged_fails_closed(repo):
    original = make_branch(repo, "worker-1-x", "a.txt")
    advance_main(repo, "b.txt", "first\n")
    git(repo, "checkout", "-q", "worker-1-x")
    git(repo, "merge", "-q", "--no-edit", "origin/main")
    merged = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    advance_main(repo, "c.txt", "newer main\n")
    git(repo, "checkout", "-q", "worker-1-x")
    git(repo, "merge", "-q", "--no-edit", "origin/main")
    git(repo, "checkout", "-q", "main")
    # merged_head is the first (older-base) merge, but the newer base is not an
    # ancestor of it: fails closed at the ancestry check.
    with pytest.raises(readopt.GitError):
        readopt.compute_review_path(readopt.make_git(repo), original, merged)


# =============================================================================
# #2286 reap-orphans / remote heads / prune-attempts remote delete
# =============================================================================

SLUG = ("o", "r")
FAR = time.time() + 30 * 86400  # injected "now": every just-made branch is 30 days old
# Copied from bin/hos-cron (_RO_EVENT_RE, the reap-landed audit hook). Slice 2's
# cron wiring extends it to capture where=; the field ORDER is the contract (A8).
RO_EVENT_RE = re.compile(r"^(REAPED|REAP-FAILED) branch=([A-Za-z0-9._/@+-]+) reason=")
OTHER_SHA = "0" * 40


def pr(branch, sha, *, merged=False, state="closed", number=1, base="main"):
    return {
        "number": number,
        "state": state,
        "merged_at": "2026-01-01T00:00:00Z" if merged else None,
        "head": {"ref": branch, "sha": sha, "repo": {"full_name": "o/r"}},
        "base": {"ref": base},
    }


def fake_pulls(prs):
    allp = [pr("unrelated-x", OTHER_SHA, merged=True, number=999), *prs]
    return lambda state: [p for p in allp if state == "all" or p["state"] == state]


def reap(repo, *, prs=(), issues=None, now=FAR, **kw):
    states = dict(issues or {})
    kw.setdefault("pulls", fake_pulls(list(prs)))
    kw.setdefault("issue_states", lambda needed: {n: s for n, s in states.items()})
    return readopt.reap_orphans(repo, slug=SLUG, now=now, **kw)


def lines_of(capsys, prefix=None):
    out = capsys.readouterr().out.splitlines()
    return [ln for ln in out if prefix is None or ln.startswith(prefix)]


def remote_heads_of(repo, pattern="refs/heads/*"):
    out = git(repo, "ls-remote", "origin", pattern)
    return {ln.split("\t")[1][len("refs/heads/") :]: ln.split("\t")[0] for ln in out.splitlines()}


def push_branch(repo, name, ref=None):
    git(repo, "push", "-q", "origin", f"{ref or name}:refs/heads/{name}")


def make_old_branch(repo, name):
    make_dated_branch(repo, name, "2026-01-01T00:00:00Z")
    return git(repo, "rev-parse", name)


def test_t1_never_list_names_current_and_worktree(repo, tmp_path, capsys):
    for name in ("audit-log", "release/x", "audit/y", "wt-b", "cur"):
        git(repo, "branch", name, "main")
    git(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "wt-b")
    git(repo, "checkout", "-q", "cur")
    assert reap(repo) == 0
    assert branches(repo) >= {
        "main",
        "audit-log",
        "release/x",
        "audit/y",
        "wt-b",
        "cur",
    }
    out = "\n".join(lines_of(capsys))
    assert "reaped_local=0" in out and "failed=0" in out


def test_t1_reasons_are_reported_in_dry_run(repo, tmp_path, capsys):
    for name in ("audit-log", "release/x", "wt-b", "cur"):
        git(repo, "branch", name, "main")
    git(repo, "worktree", "add", "-q", str(tmp_path / "wt"), "wt-b")
    git(repo, "checkout", "-q", "cur")
    reap(repo, dry_run=True)
    out = "\n".join(lines_of(capsys))
    for name, reason in (
        ("main", "protected-name"),
        ("audit-log", "protected-name"),
        ("release/x", "protected-name"),
        ("cur", "current-branch"),
        ("wt-b", "worktree"),
    ):
        assert f"KEEP branch={name} reason={reason} where=local" in out


def test_t2_open_pr_head_is_never_touched(repo, capsys):
    tip = make_old_branch(repo, "worker-5-x")
    push_branch(repo, "worker-5-x")
    prs = [
        pr("worker-5-x", tip, merged=True, number=1),
        pr("worker-5-x", tip, state="open", number=2),
    ]
    assert reap(repo, prs=prs) == 0
    out = "\n".join(lines_of(capsys))
    assert "REAPED" not in out
    assert "worker-5-x" in branches(repo)
    assert "worker-5-x" in remote_heads_of(repo)
    reap(repo, prs=prs, dry_run=True)
    out = "\n".join(lines_of(capsys))
    assert f"KEEP branch=worker-5-x reason=open-pr where=local tip={tip}" in out
    assert f"KEEP branch=worker-5-x reason=open-pr where=remote tip={tip}" in out


def test_t3_merged_pr_at_tip_reaps_local_and_remote_and_record(repo, capsys):
    tip = make_old_branch(repo, "worker-5-x")
    push_branch(repo, "worker-5-x")
    rec = write_record(repo, "worker-5-x")
    assert reap(repo, prs=[pr("worker-5-x", tip, merged=True, number=7)]) == 0
    out = lines_of(capsys)
    assert f"REAPED branch=worker-5-x reason=pr-merged where=local pr=#7 tip={tip}" in out
    assert f"REAPED branch=worker-5-x reason=pr-merged where=remote pr=#7 tip={tip}" in out
    assert "worker-5-x" not in branches(repo)
    assert "worker-5-x" not in remote_heads_of(repo)
    assert not rec.exists()


def test_t4_closed_unmerged_pr_at_tip_reaps(repo, capsys):
    tip = make_old_branch(repo, "fix/x")
    push_branch(repo, "fix/x")
    reap(repo, prs=[pr("fix/x", tip, number=3)])
    out = lines_of(capsys)
    assert f"REAPED branch=fix/x reason=pr-closed where=local pr=#3 tip={tip}" in out
    assert "fix/x" not in branches(repo)
    assert "fix/x" in remote_heads_of(repo)  # remote phase is worker-* only


def test_t5_landed_by_ancestry_and_by_content(repo, capsys):
    git(repo, "branch", "worker-7-a", "main")
    make_branch(repo, "worker-7-b", "c.txt", "x\n")
    advance_main(repo, "c.txt", "x\n")
    reap(repo, issues={7: "open"})
    out = "\n".join(lines_of(capsys))
    assert "reason=landed-ancestor where=local" in out and "branch=worker-7-a" in out
    assert re.search(r"REAPED branch=worker-7-b reason=landed-content", out)
    assert not ({"worker-7-a", "worker-7-b"} & branches(repo))


def test_t6_closed_issue_reaps_unlanded_but_legacy_branch_is_kept(repo, capsys):
    make_branch(repo, "worker-30-x", "a.txt", "unlanded\n")
    make_branch(repo, "fix/x", "a.txt", "unlanded legacy\n")
    reap(repo, issues={30: "closed"})
    out = lines_of(capsys)
    assert any(ln.startswith("REAPED branch=worker-30-x reason=issue-closed") for ln in out)
    assert "worker-30-x" not in branches(repo)
    assert "fix/x" in branches(repo)
    reap(repo, issues={30: "closed"}, dry_run=True)
    assert any(
        ln.startswith("KEEP branch=fix/x reason=unlanded-no-pr where=local")
        for ln in lines_of(capsys)
    )


def test_ni1_no_issue_closed_keeps_unlanded_closed_issue_branch(repo, capsys):
    make_branch(repo, "worker-30-x", "a.txt", "unlanded\n")
    reap(repo, issues={30: "closed"}, dry_run=True, issue_closed=False)
    assert any(
        ln.startswith("KEEP branch=worker-30-x reason=issue-closed-unlanded where=local")
        for ln in lines_of(capsys)
    )
    reap(repo, issues={30: "closed"}, issue_closed=False)
    assert "worker-30-x" in branches(repo)
    reap(repo, issues={30: "closed"})
    assert "worker-30-x" not in branches(repo)


def test_ni2_no_issue_closed_still_reaps_landed_content(repo, capsys):
    make_branch(repo, "worker-31-x", "c.txt", "x\n")
    advance_main(repo, "c.txt", "x\n")
    reap(repo, issues={31: "closed"}, issue_closed=False)
    assert any(
        ln.startswith("REAPED branch=worker-31-x reason=landed-content") for ln in lines_of(capsys)
    )
    assert "worker-31-x" not in branches(repo)


def test_ni3_no_issue_closed_keeps_a1_and_pr_merged(repo, capsys):
    tip32 = make_branch(repo, "worker-32-x", "a.txt", "closed pr\n")
    tipy = make_branch(repo, "fix/y", "b.txt", "merged\n")
    reap(
        repo,
        prs=[
            pr("worker-32-x", tip32, number=32),
            pr("fix/y", tipy, merged=True, number=33),
        ],
        issues={32: "open"},
        issue_closed=False,
    )
    out = lines_of(capsys)
    assert any(
        f"REAPED branch=fix/y reason=pr-merged where=local pr=#33 tip={tipy}" in ln for ln in out
    )
    assert "worker-32-x" in branches(repo)
    reap(
        repo,
        prs=[pr("worker-32-x", tip32, number=32)],
        issues={32: "open"},
        issue_closed=False,
        dry_run=True,
    )
    assert any(
        "KEEP branch=worker-32-x reason=closed-pr-open-issue" in ln for ln in lines_of(capsys)
    )


def test_ni4_no_issue_closed_does_not_look_up_commit_refs(repo):
    git(repo, "checkout", "-q", "-b", "worker-33-x", "main")
    commit(repo, "a.txt", "w\n", "work, see #99")
    git(repo, "checkout", "-q", "main")
    seen = []

    def states(needed):
        seen.append(set(needed))
        return {33: "closed"}

    reap(repo, issue_states=states, issue_closed=False, dry_run=True)
    reap(repo, issue_states=states, dry_run=True)
    assert seen == [{33}, {33, 99}]


def test_ni5_cli_plumbs_no_issue_closed(repo, monkeypatch):
    seen = []
    monkeypatch.setattr(readopt, "reap_orphans", lambda r, **kw: seen.append(kw) or 0)
    base = ["--repo", str(repo), "reap-orphans", "--local-only", "--dry-run"]
    assert readopt.main([*base, "--no-issue-closed"]) == 0
    assert readopt.main(base) == 0
    assert [kw["issue_closed"] for kw in seen] == [False, True]


def test_t7_tip_beyond_merged_pr_head_is_kept(repo, capsys):
    git(repo, "checkout", "-q", "-b", "worker-40-x", "main")
    first = commit(repo, "a.txt", "one\n", "first")
    commit(repo, "a.txt", "two\n", "second")
    git(repo, "checkout", "-q", "main")
    reap(repo, prs=[pr("worker-40-x", first, merged=True)], issues={40: "open"})
    assert "worker-40-x" in branches(repo)
    reap(
        repo,
        prs=[pr("worker-40-x", first, merged=True)],
        issues={40: "open"},
        dry_run=True,
    )
    assert any(
        "KEEP branch=worker-40-x reason=unlanded-pr-sha-mismatch" in ln for ln in lines_of(capsys)
    )


def test_t8_conflicting_stale_branch_on_open_issue_is_kept(repo, capsys):
    make_branch(repo, "worker-50-x", "a.txt", "branch edit\n")
    advance_main(repo, "a.txt", "main edit\n")
    reap(repo, issues={50: "open"}, dry_run=True)
    assert any(
        "KEEP branch=worker-50-x reason=unlanded-open-issue" in ln for ln in lines_of(capsys)
    )


def test_t9_grace_young_tip(repo, capsys):
    git(repo, "branch", "worker-8-a", "main")
    reap(repo, issues={8: "open"}, now=time.time(), dry_run=True)
    assert any("KEEP branch=worker-8-a reason=grace" in ln for ln in lines_of(capsys))


def test_t9_grace_fresh_record_on_old_tip(repo, capsys):
    make_old_branch(repo, "worker-8-b")
    now = time.time() + 10 * 86400  # reflog is 10 days old; only the record is fresh
    rec = write_record(repo, "worker-8-b", age_secs=0)
    os.utime(rec, (now - 3600, now - 3600))
    reap(repo, issues={8: "open"}, now=now, dry_run=True)
    assert any("KEEP branch=worker-8-b reason=grace" in ln for ln in lines_of(capsys))


def test_t9_grace_fresh_reflog_on_old_tip(repo, capsys):
    tip = make_old_branch(repo, "worker-8-c")  # commit and reflog both dated January
    git(repo, "branch", "-f", "worker-8-c", "main")  # re-created from the old commit,
    git(repo, "branch", "-f", "worker-8-c", tip)  # as create_branch.sh --from does
    reap(repo, issues={8: "open"}, now=time.time(), dry_run=True)
    out = lines_of(capsys)
    assert any("KEEP branch=worker-8-c reason=grace" in ln for ln in out), "\n".join(out)


def test_t10_dry_run_deletes_nothing_and_reports_every_branch(repo, capsys):
    tip = make_old_branch(repo, "worker-5-x")
    push_branch(repo, "worker-5-x")
    git(repo, "branch", "worker-6-y", "main")
    make_branch(repo, "worker-7-z", "a.txt", "w\n")
    local_before, remote_before = branches(repo), remote_heads_of(repo)
    reap(
        repo,
        prs=[pr("worker-5-x", tip, merged=True)],
        issues={6: "open", 7: "open"},
        dry_run=True,
    )
    out = lines_of(capsys)
    assert branches(repo) == local_before and remote_heads_of(repo) == remote_before
    named = {
        re.search(r"branch=(\S+) .*where=local", ln).group(1) for ln in out if "where=local" in ln
    }
    assert named == local_before
    assert any(
        ln.startswith("WOULD-REAP branch=worker-5-x reason=pr-merged where=remote") for ln in out
    )


@pytest.mark.parametrize("failing", ["pulls", "issue_states", "recheck"])
def test_t11_failed_listing_aborts_with_zero_deletions(repo, capsys, failing):
    git(repo, "branch", "worker-6-y", "main")  # landed, would be reaped
    make_branch(repo, "worker-7-z", "a.txt", "w\n")  # needs issue state
    base = fake_pulls([])

    def pulls(state):
        if failing == "pulls" or (failing == "recheck" and state == "open"):
            raise RuntimeError("api down")
        return base(state)

    def issue_states(needed):
        if failing == "issue_states":
            raise RuntimeError("api down")
        return {6: "open", 7: "open"}

    before = branches(repo)
    assert (
        readopt.reap_orphans(repo, slug=SLUG, now=FAR, pulls=pulls, issue_states=issue_states) == 2
    )
    out = "\n".join(lines_of(capsys))
    assert "listing failed — nothing deleted" in out and "aborted=1" in out
    assert branches(repo) == before


def test_t12_remote_moved_between_listing_and_push(repo, capsys):
    tip = make_old_branch(repo, "worker-60-x")
    push_branch(repo, "worker-60-x")
    git(repo, "checkout", "-q", "-b", "tmp", "worker-60-x")
    moved = commit(repo, "a.txt", "moved\n", "moved on")
    git(repo, "checkout", "-q", "main")
    push_branch(repo, "worker-60-x", "tmp")
    git(repo, "branch", "-D", "tmp")
    prs = [pr("worker-60-x", tip, merged=True)]
    assert reap(repo, prs=prs, remote_heads=lambda pat: [("worker-60-x", tip)]) == 0
    out = lines_of(capsys)
    assert f"REAP-FAILED branch=worker-60-x reason=cas-or-push-failed where=remote tip={tip}" in out
    assert remote_heads_of(repo)["worker-60-x"] == moved
    assert "worker-60-x" not in branches(repo)  # the local side is independent
    assert any(RO_EVENT_RE.match(ln) for ln in out if ln.startswith("REAP"))


def test_t24_real_run_lines_match_cron_event_regex(repo, capsys):
    tip = make_old_branch(repo, "worker-5-x")
    push_branch(repo, "worker-5-x")
    reap(repo, prs=[pr("worker-5-x", tip, merged=True)])
    reaped = [ln for ln in lines_of(capsys) if ln.startswith("REAPED")]
    assert len(reaped) == 2 and all(RO_EVENT_RE.match(ln) for ln in reaped)
    assert all(RO_EVENT_RE.match(ln).group(2) == "worker-5-x" for ln in reaped)
    failed = f"REAP-FAILED branch=worker-5-x reason=delete-failed where=local tip={tip}"
    assert RO_EVENT_RE.match(failed)


class _FakeRemote:
    """Stands in for make_git_remote: records argv/env, scripted per subcommand."""

    def __init__(self, heads=(), push_rc=0, push_out="", ls_rc=0, stderr=""):
        self.calls, self.envs, self.timeouts = [], [], []
        self.heads, self.push_rc, self.push_out = list(heads), push_rc, push_out
        self.ls_rc, self.stderr = ls_rc, stderr

    def factory(self, repo, env_fn):
        def run(args, timeout=60):
            self.envs.append(dict(env_fn()))  # env is built per call (lazy)
            self.timeouts.append(timeout)
            self.calls.append(list(args))
            run.last_stderr = self.stderr
            if args[0] == "ls-remote":
                return self.ls_rc, "\n".join(f"{s}\trefs/heads/{b}" for b, s in self.heads)
            return self.push_rc, self.push_out

        run.last_stderr = ""
        return run


def test_t13_token_never_printed_or_passed_in_argv(repo, monkeypatch, capsys):
    sentinel = "SENTINEL"
    b64 = base64.b64encode(f"x-access-token:{sentinel}".encode()).decode()
    monkeypatch.setenv("GH_TOKEN", sentinel)
    git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
    tip = make_old_branch(repo, "worker-5-x")
    fake = _FakeRemote(heads=[("worker-5-x", tip)], ls_rc=128, stderr=f"fatal: {sentinel} {b64}")
    monkeypatch.setattr(readopt, "make_git_remote", fake.factory)
    reap(repo, prs=[pr("worker-5-x", tip, merged=True)], do_local=False)
    out = capsys.readouterr()
    assert sentinel not in out.out + out.err and b64 not in out.out + out.err
    assert "WARN: remote head listing failed" in out.out
    assert fake.envs and fake.envs[0]["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: basic {b64}"
    assert fake.envs[0]["GIT_CONFIG_KEY_1"] == "credential.helper"
    assert fake.envs[0]["GIT_CONFIG_VALUE_1"] == ""
    assert not any(sentinel in a or b64 in a for c in fake.calls for a in c)
    assert not any(k.startswith("GIT_TRACE") or k == "GIT_CURL_VERBOSE" for k in fake.envs[0])
    assert all("https://github.com/o/r.git" in c for c in fake.calls)


def test_t13_push_failure_text_is_redacted(repo, monkeypatch, capsys):
    sentinel = "SENTINEL"
    monkeypatch.setenv("GH_TOKEN", sentinel)
    git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
    tip = make_old_branch(repo, "worker-5-x")
    fake = _FakeRemote(heads=[("worker-5-x", tip)], push_rc=1, push_out=f"!\t:x\t{sentinel}")
    monkeypatch.setattr(readopt, "make_git_remote", fake.factory)
    reap(repo, prs=[pr("worker-5-x", tip, merged=True)], do_local=False)
    out = capsys.readouterr()
    assert sentinel not in out.out + out.err
    assert "REAP-FAILED branch=worker-5-x reason=cas-or-push-failed where=remote" in out.out


def test_push_timeout_reports_distinct_reason_and_warns(repo, monkeypatch, capsys):
    tip = make_old_branch(repo, "worker-5-x")
    fake = _FakeRemote(heads=[("worker-5-x", tip)], push_rc=124)
    monkeypatch.setattr(readopt, "make_git_remote", fake.factory)
    reap(repo, prs=[pr("worker-5-x", tip, merged=True)], do_local=False)
    out = capsys.readouterr().out
    assert "REAP-FAILED branch=worker-5-x reason=push-timeout where=remote" in out
    assert "cas-or-push-failed" not in out
    assert "next run's ls-remote is the truth" in out


def test_push_delete_chunks_at_50_refs_each_with_own_timeout():
    calls = []

    def run(args, timeout=0):
        calls.append((list(args), timeout))
        deleted = [a for a in args if a.startswith(":refs/heads/")]
        return 0, "".join(f"-\t{d}\t[deleted]\n" for d in deleted)

    items = [(f"b{i}", "1" * 40) for i in range(120)]
    got = readopt._push_delete(run, "u", items)
    assert all(v is True for v in got.values()) and len(got) == 120
    sizes = [sum(a.startswith(":refs/heads/") for a in c) for c, _ in calls]
    assert sizes == [50, 50, 20]
    assert all(t == readopt.PUSH_TIMEOUT_SECS for _, t in calls)


def test_push_delete_timeout_marks_only_its_chunk():
    seq = iter([(0, "-\t:refs/heads/b0\t[deleted]\n"), (124, "")])

    def run(args, timeout=0):
        return next(seq)

    items = [(f"b{i}", "1" * 40) for i in range(51)]
    got = readopt._push_delete(run, "u", items)
    assert got["b0"] is True and got["b1"] is False
    assert got["b50"] == readopt.PUSH_TIMEOUT


def test_push_env_uses_token_current_at_call_time(repo, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "OLDTOKEN")
    git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
    fake = _FakeRemote()
    monkeypatch.setattr(readopt, "make_git_remote", fake.factory)
    _url, run = readopt._remote_ops(readopt.make_git(repo), repo)
    monkeypatch.setenv("GH_TOKEN", "NEWTOKEN")
    run(["push"], 1)
    new_b64 = base64.b64encode(b"x-access-token:NEWTOKEN").decode()
    assert fake.envs[0]["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: basic {new_b64}"


def test_remote_runner_redacts_creation_time_token_after_rotation(repo, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "OLDTOKEN")
    run = readopt.make_git_remote(repo, dict)
    monkeypatch.setenv("GH_TOKEN", "NEWTOKEN")

    class P:
        returncode, stdout, stderr = 1, "", "fatal: OLDTOKEN and NEWTOKEN"

    monkeypatch.setattr(readopt.subprocess, "run", lambda *a, **k: P())
    run(["ls-remote"], 1)
    assert "OLDTOKEN" not in run.last_stderr and "NEWTOKEN" not in run.last_stderr


def test_remote_runner_strips_askpass_and_trace_from_child_env(repo, monkeypatch):
    for k in ("GIT_ASKPASS", "SSH_ASKPASS", "GIT_TRACE", "GIT_CURL_VERBOSE"):
        monkeypatch.setenv(k, "1")
    seen = {}

    class P:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(argv, **kw):
        seen.update(kw["env"])
        return P()

    monkeypatch.setattr(readopt.subprocess, "run", fake_run)
    readopt.make_git_remote(repo, lambda: {"X": "y"})(["version"], 1)
    assert seen["X"] == "y"
    assert not {"GIT_ASKPASS", "SSH_ASKPASS", "GIT_TRACE", "GIT_CURL_VERBOSE"} & set(seen)


def test_summary_reports_remote_skipped_and_recheck(repo, monkeypatch, capsys):
    git(repo, "remote", "set-url", "origin", "ssh://git@github.com/o/r.git")
    reap(repo, dry_run=True)
    last = lines_of(capsys, "SUMMARY")[-1]
    assert "aborted=0 remote_skipped=1 recheck=skipped" in last
    git(repo, "remote", "set-url", "origin", str(repo.parent / "origin.git"))
    reap(repo, remote_heads=lambda pat: [], remote_delete=lambda i: {})
    assert "remote_skipped=0 recheck=none" in lines_of(capsys, "SUMMARY")[-1]


def test_summary_remote_skipped_on_listing_failure(repo, capsys):
    def boom(pat):
        raise RuntimeError("down")

    reap(repo, remote_heads=boom, remote_delete=lambda i: {}, dry_run=True)
    assert "remote_skipped=1" in lines_of(capsys, "SUMMARY")[-1]


def test_summary_recheck_done_when_something_is_reaped(repo, capsys):
    git(repo, "branch", "worker-7-a", "main")
    reap(repo, issues={7: "closed"}, remote_heads=lambda p: [], remote_delete=lambda i: {})
    assert "recheck=done" in lines_of(capsys, "SUMMARY")[-1]


def test_git_error_before_listing_still_prints_summary_exit_2(repo, capsys):
    rc = readopt.reap_orphans(repo, slug=SLUG, now=FAR, base="no-such-ref", dry_run=True)
    cap = capsys.readouterr()
    assert rc == 2
    assert cap.out.splitlines()[-1].startswith("SUMMARY ")
    assert "aborted=1" in cap.out.splitlines()[-1]


def test_redact_covers_literal_and_header_forms(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "tok123")
    header = base64.b64encode(b"x-access-token:tok123").decode()
    assert readopt._redact(f"a tok123 b {header}") == "a *** b ***"
    assert "tok123" not in readopt._one_line(RuntimeError("boom tok123"))


def test_local_origin_gets_no_auth_env(repo, monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "SENTINEL")
    fake = _FakeRemote()
    monkeypatch.setattr(readopt, "make_git_remote", fake.factory)
    reap(repo, dry_run=True)
    assert fake.envs == [{}]


def test_remote_runner_strips_trace_vars_and_times_out(repo, monkeypatch):
    monkeypatch.setenv("GIT_TRACE", "1")
    monkeypatch.setenv("GIT_CURL_VERBOSE", "1")
    run = readopt.make_git_remote(repo, dict)
    rc, _ = run(["version"], 30)
    assert rc == 0 and run.last_stderr == ""


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:o/r.git",
        "ssh://git@github.com/o/r.git",
        "https://gitlab.com/o/r.git",
    ],
)
def test_t23_unsupported_origin_skips_remote_phase(repo, monkeypatch, capsys, url):
    monkeypatch.setenv("GH_TOKEN", "SENTINEL")
    git(repo, "remote", "set-url", "origin", url)

    def boom_factory(*_a, **_k):
        raise AssertionError("remote runner must not be built")

    monkeypatch.setattr(readopt, "make_git_remote", boom_factory)
    assert reap(repo, dry_run=True) == 0
    assert "remote phase skipped — unsupported origin URL scheme" in capsys.readouterr().out


def test_t23_github_url_without_token_skips_remote_phase(repo, monkeypatch, capsys):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    git(repo, "remote", "set-url", "origin", "https://github.com/o/r.git")
    assert reap(repo, dry_run=True) == 0
    assert "GH_TOKEN unset — remote phase skipped" in capsys.readouterr().out


def test_t15_max_deletions_defers_the_rest(repo, capsys):
    for n in ("a", "b", "c"):
        git(repo, "branch", f"worker-7-{n}", "main")
    reap(repo, issues={7: "open"}, max_deletions=1)
    out = lines_of(capsys)
    assert sum(ln.startswith("REAPED") for ln in out) == 1
    assert sum(ln.startswith("DEFERRED") for ln in out) == 2
    assert len({"worker-7-a", "worker-7-b", "worker-7-c"} & branches(repo)) == 2
    assert " aborted=0 " in out[-1] and "deferred=2" in out[-1]


def test_t16_local_only_and_remote_only(repo, capsys):
    tip = make_old_branch(repo, "worker-5-x")
    push_branch(repo, "worker-5-x")
    prs = [pr("worker-5-x", tip, merged=True)]
    reap(repo, prs=prs, do_remote=False)
    assert "worker-5-x" not in branches(repo) and "worker-5-x" in remote_heads_of(repo)
    git(repo, "branch", "worker-5-x", tip)
    reap(repo, prs=prs, do_local=False)
    assert "worker-5-x" in branches(repo) and "worker-5-x" not in remote_heads_of(repo)


def test_t16_both_only_flags_exit_2(repo):
    with pytest.raises(SystemExit) as exc:
        readopt.main(["--repo", str(repo), "reap-orphans", "--local-only", "--remote-only"])
    assert exc.value.code == 2


@pytest.mark.parametrize("flag", ["--grace-days", "--max-deletions"])
def test_cli_rejects_negative_numbers(repo, flag):
    with pytest.raises(SystemExit) as exc:
        readopt.main(["--repo", str(repo), "reap-orphans", flag, "-1"])
    assert exc.value.code == 2


def test_t17_unsafe_names_are_kept_and_never_reach_git(repo, capsys):
    git(repo, "update-ref", "refs/heads/-x", "main")
    git(repo, "update-ref", "refs/heads/a,b", "main")
    real = readopt.make_git(repo)
    calls = []

    def spy(args):
        calls.append(list(args))
        return real(args)

    reap(repo, git=spy, dry_run=True)
    out = "\n".join(lines_of(capsys))
    assert re.search(r"KEEP branch=-x reason=unsafe-name where=local", out)
    assert re.search(r"KEEP branch=a%2Cb reason=unsafe-name where=local", out)
    assert not any("-x" in a or "a,b" in a for c in calls for a in c)


def test_t18_closed_pr_on_open_issue_local_kept_remote_reaped(repo, capsys):
    tip = make_old_branch(repo, "worker-70-x")
    push_branch(repo, "worker-70-x")
    legacy = make_old_branch(repo, "fix/y")
    prs = [pr("worker-70-x", tip, number=4), pr("fix/y", legacy, number=5)]
    reap(repo, prs=prs, issues={70: "open"})
    out = lines_of(capsys)
    assert f"REAPED branch=worker-70-x reason=pr-closed where=remote pr=#4 tip={tip}" in out
    assert f"REAPED branch=fix/y reason=pr-closed where=local pr=#5 tip={legacy}" in out
    assert "worker-70-x" in branches(repo) and "fix/y" not in branches(repo)
    assert "worker-70-x" not in remote_heads_of(repo)
    reap(repo, prs=prs, issues={70: "open"}, dry_run=True)
    assert any(
        "KEEP branch=worker-70-x reason=closed-pr-open-issue where=local" in ln
        for ln in lines_of(capsys)
    )


def test_t19_batched_branch_with_open_issue_ref_is_kept(repo, capsys):
    git(repo, "checkout", "-q", "-b", "worker-80-x", "main")
    commit(repo, "a.txt", "batched\n", "S1 work\n\nPart of #81")
    git(repo, "checkout", "-q", "main")
    for issues in ({80: "closed", 81: "open"}, {80: "closed"}):
        reap(repo, issues=issues, dry_run=True)
        assert any(
            "KEEP branch=worker-80-x reason=issue-closed-batch-open" in ln
            for ln in lines_of(capsys)
        )
    reap(repo, issues={80: "closed", 81: "closed"})
    assert "worker-80-x" not in branches(repo)


def test_t20_unknown_issue_is_kept_and_empty_pr_listing_aborts(repo, capsys):
    make_branch(repo, "worker-90-x", "a.txt", "w\n")
    reap(repo, issues={}, dry_run=True)
    assert any("KEEP branch=worker-90-x reason=issue-unknown" in ln for ln in lines_of(capsys))
    before = branches(repo)
    rc = readopt.reap_orphans(
        repo,
        slug=SLUG,
        now=FAR,
        pulls=lambda state: [],
        issue_states=lambda n: {90: "closed"},
    )
    out = "\n".join(lines_of(capsys))
    assert rc == 2 and "aborted=1" in out and branches(repo) == before


def test_t21_tip_behind_merged_pr_head_is_covered(repo, capsys):
    git(repo, "checkout", "-q", "-b", "worker-91-x", "main")
    tip = commit(repo, "a.txt", "one\n", "one")
    git(repo, "checkout", "-q", "-b", "ahead")
    ahead = commit(repo, "a.txt", "two\n", "two")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "-D", "ahead")  # object stays present locally, as after a fetch
    reap(repo, prs=[pr("worker-91-x", ahead, merged=True, number=6)], issues={91: "open"})
    assert any(
        ln.startswith(f"REAPED branch=worker-91-x reason=pr-merged where=local pr=#6 tip={tip}")
        for ln in lines_of(capsys)
    )


def test_t21_pr_head_object_absent_or_non_main_base_is_not_covered(repo, capsys):
    tip = make_branch(repo, "worker-92-x", "a.txt", "w\n")
    reap(
        repo,
        prs=[pr("worker-92-x", "1" * 40, merged=True)],
        issues={92: "open"},
        dry_run=True,
    )
    assert any(
        "KEEP branch=worker-92-x reason=unlanded-pr-sha-mismatch" in ln for ln in lines_of(capsys)
    )
    reap(
        repo,
        prs=[pr("worker-92-x", tip, merged=True, base="dev")],
        issues={92: "open"},
        dry_run=True,
    )
    out = "\n".join(lines_of(capsys))
    assert "reason=pr-merged" not in out and "worker-92-x reason=unlanded-open-issue" in out


def test_t22_one_batched_push_with_per_ref_results(repo, monkeypatch, capsys):
    tips = {}
    for n in ("a", "b", "c"):
        tips[n] = make_old_branch(repo, f"worker-31-{n}")
        push_branch(repo, f"worker-31-{n}")
    git(repo, "checkout", "-q", "-b", "tmp", "worker-31-b")
    commit(repo, "a.txt", "moved\n", "moved on")
    git(repo, "checkout", "-q", "main")
    push_branch(repo, "worker-31-b", "tmp")  # remote b moved; the injected listing is stale
    real_factory = readopt.make_git_remote
    pushes = []

    def factory(r, env):
        real = real_factory(r, env)

        def run(args, timeout=60):
            if args[0] == "push":
                pushes.append(list(args))
            return real(args, timeout)

        return run

    monkeypatch.setattr(readopt, "make_git_remote", factory)
    prs = [
        pr(f"worker-31-{n}", t, merged=True, number=i) for i, (n, t) in enumerate(tips.items(), 1)
    ]
    stale = lambda pat: [(f"worker-31-{n}", t) for n, t in tips.items()]  # noqa: E731
    reap(repo, prs=prs, remote_heads=stale, do_local=False)
    out = lines_of(capsys)
    assert len(pushes) == 1
    assert all("--atomic" not in a for a in pushes[0]) and "--no-verify" in pushes[0]
    assert sum(ln.startswith("REAPED") for ln in out) == 2
    assert sum(ln.startswith("REAP-FAILED") and "cas-or-push-failed" in ln for ln in out) == 1
    assert set(remote_heads_of(repo, "refs/heads/worker-31-*")) == {"worker-31-b"}


def test_push_parse_requires_per_ref_deleted_line():
    calls = []

    def run(args, timeout=0):
        calls.append(args)
        return (
            1,
            "To x\n-\t:refs/heads/a\t[deleted]\n!\t:refs/heads/b\t[rejected] (stale info)\n",
        )

    got = readopt._push_delete(run, "u", [("a", "1" * 40), ("b", "2" * 40), ("c", "3" * 40)])
    assert got == {"a": True, "b": False, "c": False}
    assert readopt._push_delete(
        lambda a, t=0: (124, "-\t:refs/heads/a\t"), "u", [("a", "1" * 40)]
    ) == {"a": readopt.PUSH_TIMEOUT}


def test_no_candidates_makes_no_github_calls(repo, capsys):
    git(repo, "branch", "wt-keep", "main")
    git(repo, "checkout", "-q", "wt-keep")

    def forbidden(*_a, **_k):
        raise AssertionError("GitHub must not be called")

    rc = readopt.reap_orphans(
        repo,
        slug=SLUG,
        now=time.time(),
        pulls=forbidden,
        issue_states=forbidden,
        dry_run=True,
    )
    out = "\n".join(lines_of(capsys))
    assert rc == 0 and "api_calls=0" in out and "aborted=0" in out


def test_remote_tip_not_local_is_kept(repo, capsys):
    reap(repo, remote_heads=lambda pat: [("worker-5-x", "a" * 40)], dry_run=True)
    assert any(
        "KEEP branch=worker-5-x reason=remote-tip-not-local where=remote" in ln
        for ln in lines_of(capsys)
    )


def test_remote_listing_failure_still_runs_local_phase(repo, capsys):
    git(repo, "branch", "worker-6-y", "main")

    def bad(pat):
        raise GitErrorLike("ls-remote down")

    class GitErrorLike(Exception):
        pass

    rc = reap(repo, issues={6: "open"}, remote_heads=bad)
    out = "\n".join(lines_of(capsys))
    assert rc == 0 and "remote head listing failed" in out and "REAPED branch=worker-6-y" in out


def test_issue_states_default_uses_per_issue_reads_then_list(monkeypatch):
    calls = {"get": [], "list": 0}
    monkeypatch.setattr(
        readopt.github,
        "get_issue",
        lambda o, r, n: (calls["get"].append(n) or ({"state": "closed"} if n != 3 else None)),
    )
    monkeypatch.setattr(
        readopt.github,
        "list_all_issue_states",
        lambda o, r: calls.__setitem__("list", 1) or {9: "open"},
    )
    lookup = readopt._github_issue_states(SLUG)
    assert lookup({1, 3}) == {1: "closed"}  # a 404 is unknown, never closed
    assert lookup(set(range(100, 100 + readopt.PER_ISSUE_READ_LIMIT + 1))) == {9: "open"}
    assert calls["get"] == [1, 3] and calls["list"] == 1


def test_t25_selector_stage_cleared_by_reap(repo):
    git(repo, "checkout", "-q", "-b", "worker-100-x", "main")
    tip = commit(repo, "a.txt", "squashed attempt\n", "attempt")
    git(repo, "checkout", "-q", "main")
    advance_main(repo, "a.txt", "main moved on\n")  # merge-tree now conflicts
    assert swc._started_stages(str(repo), [100]) == {100: swc._STAGE_BRANCH}
    reap(repo, prs=[pr("worker-100-x", tip, merged=True)])
    assert swc._started_stages(str(repo), [100]) == {}


# --- prune-attempts remote head (T14) ---------------------------------------


def _no_open_pr(branch):
    return False


def test_t14_prune_deletes_matching_remote_head(attempts, capsys):
    repo = attempts
    for n in ("old", "new", "mid"):
        push_branch(repo, f"worker-20-{n}")
    readopt.prune_attempts(repo, 20, slug=SLUG, open_pr=_no_open_pr)
    out = lines_of(capsys)
    assert "DELETED branch=worker-20-old where=remote" in out
    assert "DELETED branch=worker-20-old" in out  # back-compat local line
    assert set(remote_heads_of(repo, "refs/heads/worker-20-*")) == {"worker-20-new"}
    assert "worker-20-old" not in branches(repo)


def test_t14_prune_keeps_moved_remote_and_still_deletes_local(attempts, capsys):
    repo = attempts
    push_branch(repo, "worker-20-old")
    git(repo, "checkout", "-q", "-b", "tmp", "worker-20-old")
    moved = commit(repo, "a.txt", "moved\n", "moved")
    git(repo, "checkout", "-q", "main")
    push_branch(repo, "worker-20-old", "tmp")
    git(repo, "branch", "-D", "tmp")
    assert readopt.prune_attempts(repo, 20, slug=SLUG, open_pr=_no_open_pr) == [
        "worker-20-mid",
        "worker-20-old",
    ]
    out = "\n".join(lines_of(capsys))
    assert "remote head moved for 'worker-20-old'" in out
    assert remote_heads_of(repo)["worker-20-old"] == moved
    assert "worker-20-old" not in branches(repo)


def test_t14_prune_open_pr_keeps_remote(attempts, capsys):
    repo = attempts
    push_branch(repo, "worker-20-old")
    readopt.prune_attempts(repo, 20, slug=SLUG, open_pr=lambda b: True)
    assert "has an open PR — remote head kept" in capsys.readouterr().out
    assert "worker-20-old" in remote_heads_of(repo)


def test_t14_prune_dry_run_reads_but_writes_nothing(attempts, capsys):
    repo = attempts
    push_branch(repo, "worker-20-old")
    before = (branches(repo), remote_heads_of(repo))
    readopt.prune_attempts(repo, 20, dry_run=True)
    assert "WOULD-DELETE branch=worker-20-old where=remote" in capsys.readouterr().out
    assert (branches(repo), remote_heads_of(repo)) == before


def test_t14_prune_remote_lookup_failure_never_fails_the_local_delete(attempts, capsys):
    def bad(pat):
        raise RuntimeError("net down")

    got = readopt.prune_attempts(attempts, 20, remote_heads=bad, remote_delete=lambda i: {})
    assert "worker-20-old" in got and "worker-20-old" not in branches(attempts)
    assert "remote head lookup failed" in capsys.readouterr().out


# --- unit-test authority additions (#2286): decision rows not otherwise pinned ---


def _failing_git(repo, *, fail_prefix, rc=128):
    """Real git runner that returns ``rc`` for commands starting with fail_prefix."""
    real = readopt.make_git(repo)

    def run(args):
        if list(args[: len(fail_prefix)]) == list(fail_prefix):
            return rc, ""
        return real(args)

    return run


@pytest.mark.parametrize(
    "fail_prefix",
    [("merge-base", "--is-ancestor"), ("merge-tree", "--write-tree")],
)
def test_git_error_in_landed_probe_keeps_branch(repo, capsys, fail_prefix):
    make_branch(repo, "worker-60-x", "a.txt", "w\n")
    git(repo, "branch", "-f", "worker-61-y", "worker-60-x")
    run = _failing_git(
        repo, fail_prefix=fail_prefix, rc=128 if fail_prefix[0] == "merge-base" else 2
    )
    before = branches(repo)
    assert reap(repo, issues={60: "open", 61: "open"}, git=run) == 0
    assert branches(repo) == before
    reap(repo, issues={60: "open", 61: "open"}, git=run, dry_run=True)
    out = lines_of(capsys, "KEEP")
    assert any("branch=worker-60-x reason=git-error" in ln for ln in out)


def test_git_error_on_closed_issue_commit_scan_keeps_branch(repo, capsys):
    make_branch(repo, "worker-62-x", "a.txt", "w\n")
    advance_main(repo, "a.txt", "main edit\n")  # conflict: not landed
    run = _failing_git(repo, fail_prefix=("log", "--format=%B"))
    assert reap(repo, issues={62: "closed"}, git=run) == 0
    assert "worker-62-x" in branches(repo)
    reap(repo, issues={62: "closed"}, git=run, dry_run=True)
    assert any("branch=worker-62-x reason=git-error" in ln for ln in lines_of(capsys, "KEEP"))


def test_closed_issue_with_all_refs_closed_is_reaped_d2(repo, capsys):
    git(repo, "checkout", "-q", "-b", "worker-63-x", "main")
    commit(repo, "a.txt", "w\n", "work for #63 and #64")
    git(repo, "checkout", "-q", "main")
    advance_main(repo, "a.txt", "main edit\n")
    reap(repo, issues={63: "closed", 64: "closed"}, dry_run=True)
    assert any("WOULD-REAP branch=worker-63-x reason=issue-closed" in ln for ln in lines_of(capsys))
    reap(repo, issues={63: "closed", 64: "open"}, dry_run=True)
    assert any(
        "KEEP branch=worker-63-x reason=issue-closed-batch-open" in ln for ln in lines_of(capsys)
    )


def test_open_pr_appearing_before_delete_phase_blocks_reap(repo, capsys):
    tip = make_old_branch(repo, "worker-65-x")
    push_branch(repo, "worker-65-x")
    merged = pr("worker-65-x", tip, merged=True, number=3)
    late_open = pr("worker-65-x", tip, state="open", number=4)
    calls = []

    def pulls(state):
        calls.append(state)
        if state == "all":
            return [pr("unrelated-x", OTHER_SHA, merged=True, number=999), merged]
        return [late_open]  # the pre-delete re-check sees a new open PR

    assert (
        readopt.reap_orphans(repo, slug=SLUG, now=FAR, pulls=pulls, issue_states=lambda n: {}) == 0
    )
    assert calls == ["all", "open"]
    assert "worker-65-x" in branches(repo) and "worker-65-x" in remote_heads_of(repo)
    out = lines_of(capsys)
    assert not any(ln.startswith("REAPED") for ln in out)
    assert any("reaped_local=0 reaped_remote=0" in ln for ln in out)


def test_young_branch_with_open_pr_is_labelled_open_pr(repo, capsys):
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 19.5 * 86400))
    make_dated_branch(repo, "worker-66-y", soon)  # 0.5 day old at the injected "now"
    make_old_branch(repo, "worker-67-old")  # old enough to force phase B to run
    tip = git(repo, "rev-parse", "worker-66-y")
    prs = [pr("worker-66-y", tip, state="open", number=5)]
    reap(
        repo,
        prs=prs,
        issues={66: "open", 67: "open"},
        now=time.time() + 20 * 86400,
        dry_run=True,
    )
    out = lines_of(capsys, "KEEP")
    assert any("branch=worker-66-y reason=open-pr" in ln for ln in out)
    assert not any("worker-66-y reason=grace" in ln for ln in out)


def test_remote_head_missing_commit_object_is_kept_not_deleted(repo, capsys):
    pushed = []
    reap(
        repo,
        remote_heads=lambda pat: [("worker-68-gone", "1" * 40)],
        remote_delete=lambda items: pushed.append(items) or {},
        dry_run=True,
    )
    assert any(
        "branch=worker-68-gone reason=remote-tip-not-local" in ln for ln in lines_of(capsys, "KEEP")
    )
    assert pushed == []


def test_closed_pr_local_on_closed_issue_is_reaped_but_unknown_issue_is_kept(repo, capsys):
    closed = make_old_branch(repo, "worker-71-x")
    unknown = make_old_branch(repo, "worker-72-x")
    prs = [pr("worker-71-x", closed, number=6), pr("worker-72-x", unknown, number=7)]
    # 71 is closed: the closed PR's head carries no open-issue work. 72 is absent
    # from the state map: unknown is treated like open and the branch is protected.
    reap(repo, prs=prs, issues={71: "closed"}, dry_run=True)
    out = lines_of(capsys)
    assert any("WOULD-REAP branch=worker-71-x reason=pr-closed where=local" in ln for ln in out)
    assert any(
        "KEEP branch=worker-72-x reason=closed-pr-open-issue where=local" in ln for ln in out
    )


def test_remote_head_with_unreadable_commit_date_is_kept_as_git_error(repo, capsys):
    tip = make_old_branch(repo, "worker-73-x")
    run = _failing_git(repo, fail_prefix=("log", "-1", "--format=%ct"))
    pushed = []
    reap(
        repo,
        do_local=False,
        git=run,
        remote_heads=lambda pat: [("worker-73-x", tip)],
        remote_delete=lambda items: pushed.append(items) or {},
        dry_run=True,
    )
    assert any(
        "branch=worker-73-x reason=git-error where=remote" in ln for ln in lines_of(capsys, "KEEP")
    )
    assert pushed == []


# =============================================================================
# #2287: D4 review-named branches, N2a audit-branch names, N6 audit-record guard
# =============================================================================

# Copied from bin/hos-cron (_RB_EVENT_RE, the overseer reap-orphans audit hook).
# Group indices (A10): 1 kind, 2 branch, 3 reason, 4 where, 6 pr, 7 tip.
RB_EVENT_RE = re.compile(
    r"^(REAPED|REAP-FAILED) branch=([A-Za-z0-9._/@+-]+) reason=([a-z-]+) where=(local|remote)"
    r"( pr=(#[0-9]+|-))? tip=([0-9a-f]{40})$"
)
REVIEW_NAMES = ["pr-7-review", "pr7", "pr7-check", "pr-7-new", "pr7-12"]


def ref_snapshot(repo):
    return git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads")


def review_copies(repo, names, sha):
    for n in names:
        git(repo, "branch", n, sha)


def make_record_branch(repo, name, relpath="audit/log/2026/06/rec.json", text="{}\n"):
    git(repo, "checkout", "-q", "-b", name, "main")
    (repo / relpath).parent.mkdir(parents=True, exist_ok=True)
    tip = commit(repo, relpath, text, f"record on {name}")
    git(repo, "checkout", "-q", "main")
    return tip


def test_r1_review_copies_of_merged_pr_are_reaped(repo, capsys):
    tip = make_old_branch(repo, "src")
    review_copies(repo, REVIEW_NAMES, tip)
    assert reap(repo, prs=[pr("worker-x", tip, merged=True, number=7)]) == 0
    out = lines_of(capsys)
    for n in REVIEW_NAMES:
        assert f"REAPED branch={n} reason=review-pr-done where=local pr=#7 tip={tip}" in out
    assert not (set(REVIEW_NAMES) & branches(repo))


def test_r2_closed_unmerged_and_non_main_base_review_copies_are_reaped(repo, capsys):
    tip = make_old_branch(repo, "src")
    review_copies(repo, ["pr-7-review"], tip)
    reap(repo, prs=[pr("worker-x", tip, number=7)])
    assert (
        "REAPED branch=pr-7-review reason=review-pr-done where=local pr=#7 " + f"tip={tip}"
        in lines_of(capsys)
    )
    review_copies(repo, ["pr7"], tip)
    reap(repo, prs=[pr("worker-x", tip, merged=True, number=7, base="release-x")])
    assert "REAPED branch=pr7 reason=review-pr-done where=local pr=#7 " + f"tip={tip}" in lines_of(
        capsys
    )


def test_r3_open_pr_review_copy_is_stale_after_grace_only(repo, capsys):
    tip = make_old_branch(repo, "src")
    review_copies(repo, ["pr-7-review"], tip)
    prs = [pr("worker-x", tip, state="open", number=7)]
    reap(repo, prs=prs, now=time.time() + 60, dry_run=True)
    assert any("KEEP branch=pr-7-review reason=grace" in ln for ln in lines_of(capsys))
    assert "pr-7-review" in branches(repo)
    reap(repo, prs=prs)
    assert f"REAPED branch=pr-7-review reason=review-stale where=local pr=#7 tip={tip}" in lines_of(
        capsys
    )
    assert "pr-7-review" not in branches(repo)


def test_r4_mismatch_unknown_and_non_review_names(repo, capsys):
    git(repo, "checkout", "-q", "-b", "src", "main")
    first = commit(repo, "a.txt", "one\n", "first")
    second = commit(repo, "a.txt", "two\n", "second")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "pr-7-review", second)
    git(repo, "branch", "pr-9-review", first)
    git(repo, "branch", "pr-7-foo", first)
    reap(repo, prs=[pr("worker-x", first, merged=True, number=7)], dry_run=True)
    out = "\n".join(lines_of(capsys))
    assert "KEEP branch=pr-7-review reason=review-pr-sha-mismatch" in out
    assert "KEEP branch=pr-9-review reason=review-pr-unknown" in out
    assert "KEEP branch=pr-7-foo reason=unlanded-no-pr" in out


R5_NAMES = ["audit/x", "chore/audit-overseer-cycle-x", "chore/overseer-audit-x"]


@pytest.mark.parametrize("mode", ["real", "capped", "dry"])
@pytest.mark.parametrize("scenario", ["ancestor", "content", "merged-pr", "closed-pr", "aged"])
def test_r5_audit_patterns_are_never_touched(repo, capsys, scenario, mode):
    prs = []
    for i, name in enumerate(R5_NAMES):
        if scenario == "ancestor":
            git(repo, "branch", name, "main")
        elif scenario == "content":
            make_branch(repo, name, "c.txt", "x\n")
        else:
            tip = make_branch(repo, name, "a.txt", f"edit {i}\n")
            if scenario in ("merged-pr", "closed-pr"):
                prs.append(pr(name, tip, merged=scenario == "merged-pr", number=10 + i))
    if scenario == "content":
        advance_main(repo, "c.txt", "x\n")
    before = ref_snapshot(repo)
    kw = {"dry_run": True} if mode == "dry" else {}
    if mode == "capped":
        kw["max_deletions"] = 1
    assert reap(repo, prs=prs, **kw) == 0
    out = "\n".join(lines_of(capsys))
    assert ref_snapshot(repo) == before
    for name in R5_NAMES:
        reason = "protected-name" if name.startswith("audit/") else "audit-branch"
        if mode == "dry":
            assert f"KEEP branch={name} reason={reason} where=local" in out
        assert f"WOULD-REAP branch={name} " not in out and f"REAPED branch={name} " not in out


def test_r6_audit_content_guard(repo, capsys):
    t_fix_x = make_record_branch(repo, "fix/x")
    t_fix_y = make_record_branch(repo, "fix/y", "audit/oversight-log.jsonl", '{"a":1}\n')
    make_record_branch(repo, "worker-5-x")
    t_rev = make_record_branch(repo, "pr-7-review", "audit/log/2026/06/rev.json")
    t_ok = make_record_branch(repo, "fix/z", "audit/log/2026/06/ok.json")
    prs = [
        pr("fix/x", t_fix_x, number=3),
        pr("fix/y", t_fix_y, number=4),
        pr("worker-r", t_rev, number=7),
        pr("fix/z", t_ok, merged=True, number=6),
    ]
    reap(repo, prs=prs, issues={5: "closed"}, dry_run=True)
    out = "\n".join(lines_of(capsys))
    for n in ("fix/x", "fix/y", "worker-5-x", "pr-7-review"):
        assert f"KEEP branch={n} reason=audit-content where=local" in out
    assert re.search(r"WOULD-REAP branch=fix/z reason=pr-merged where=local pr=#6", out)
    reap(repo, prs=prs, issues={5: "closed"})
    assert branches(repo) >= {"fix/x", "fix/y", "worker-5-x", "pr-7-review"}
    assert "fix/z" not in branches(repo)


def test_r6_guard_git_error_keeps(repo, capsys):
    tip = make_old_branch(repo, "pr-7-review")
    real = readopt.make_git(repo)

    def failing(args):
        return (
            (128, "") if args[:1] == ["merge-base"] and "--is-ancestor" not in args else real(args)
        )

    reap(repo, prs=[pr("worker-x", tip, number=7)], git=failing, dry_run=True)
    assert any("KEEP branch=pr-7-review reason=git-error" in ln for ln in lines_of(capsys))


def test_r7_dry_run_reports_review_candidates(repo, capsys):
    tip = make_old_branch(repo, "src")
    review_copies(repo, ["pr-7-review"], tip)
    before = ref_snapshot(repo)
    reap(repo, prs=[pr("worker-x", tip, merged=True, number=7)], dry_run=True)
    assert (
        f"WOULD-REAP branch=pr-7-review reason=review-pr-done where=local pr=#7 tip={tip}"
        in lines_of(capsys)
    )
    assert ref_snapshot(repo) == before


def test_r8_pulls_failure_aborts_with_zero_deletions(repo, capsys):
    tip = make_old_branch(repo, "src")
    review_copies(repo, ["pr-7-review"], tip)
    before = ref_snapshot(repo)

    def boom(state):
        raise RuntimeError("api down")

    assert (
        readopt.reap_orphans(repo, slug=SLUG, now=FAR, pulls=boom, issue_states=lambda n: {}) == 2
    )
    assert "aborted=1" in "\n".join(lines_of(capsys))
    assert ref_snapshot(repo) == before


def test_r10_event_regex_and_group_indices(repo, capsys):
    tip = make_old_branch(repo, "src")
    review_copies(repo, ["pr-7-review"], tip)
    reap(repo, prs=[pr("worker-x", tip, merged=True, number=7)])
    line = next(ln for ln in lines_of(capsys) if ln.startswith("REAPED branch=pr-7-review"))
    m = RB_EVENT_RE.match(line)
    assert m and (m[1], m[2], m[3], m[4], m[6], m[7]) == (
        "REAPED",
        "pr-7-review",
        "review-pr-done",
        "local",
        "#7",
        tip,
    )
    failed = RB_EVENT_RE.match(
        f"REAP-FAILED branch=pr-7-review reason=delete-failed where=local tip={tip}"
    )
    assert failed and failed[6] is None and failed[7] == tip and failed[3] == "delete-failed"


def test_r11_real_pr_head_named_like_a_review_copy_is_not_d4(repo, capsys):
    git(repo, "checkout", "-q", "-b", "src", "main")
    p456 = commit(repo, "a.txt", "one\n", "first")
    beyond = commit(repo, "a.txt", "two\n", "second")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "pr-123-review", beyond)
    git(repo, "branch", "pr-7", p456)
    prs = [
        pr("pr-123-review", p456, number=456),
        pr("worker-y", beyond, merged=True, number=123),
        pr("pr-7", p456, state="open", number=9),
    ]
    reap(repo, prs=prs, dry_run=True)
    out = "\n".join(lines_of(capsys))
    assert "KEEP branch=pr-123-review reason=unlanded-pr-sha-mismatch" in out
    assert "review-pr-done" not in out
    assert "KEEP branch=pr-7 reason=open-pr" in out


def test_r6_diff_failure_in_guard_keeps_as_git_error(repo, capsys):
    tip = make_record_branch(repo, "fix/x")
    real = readopt.make_git(repo)

    def failing(args):
        return (128, "") if args[:1] == ["diff"] and "--name-only" in args else real(args)

    reap(repo, prs=[pr("fix/x", tip, number=3)], git=failing, dry_run=True)
    out = "\n".join(lines_of(capsys))
    assert "KEEP branch=fix/x reason=git-error where=local" in out
    assert "WOULD-REAP branch=fix/x" not in out


def test_r6_guard_does_not_block_landed_ancestor_with_records(repo, capsys):
    # N6 (design 4.2) is not applied to D3: records that are on main are safe to reap.
    make_record_branch(repo, "fix/landed")
    git(repo, "merge", "-q", "--ff-only", "fix/landed")
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    reap(repo, prs=[], dry_run=True)
    out = "\n".join(lines_of(capsys))
    assert "WOULD-REAP branch=fix/landed reason=landed-" in out
    assert "reason=audit-content" not in out


@pytest.mark.parametrize(
    "name",
    ["worker-1517-audit-sync-x", "chore/audit-sync", "chore/overseer-x", "fix/overseer-audit"],
)
def test_n2a_matches_exact_prefixes_not_the_substring_audit(repo, capsys, name):
    tip = make_branch(repo, name, "a.txt", "edit\n")
    reap(repo, prs=[pr(name, tip, number=21)], issues={1517: "closed"}, dry_run=True)
    out = "\n".join(lines_of(capsys))
    assert f"WOULD-REAP branch={name} reason=pr-closed" in out
    assert "reason=audit-branch" not in out


def test_n2a_audit_branch_kept_even_when_current_or_checked_out(repo, capsys):
    git(repo, "checkout", "-q", "-b", "chore/overseer-audit-9", "main")
    reap(repo, prs=[], dry_run=True)
    out = "\n".join(lines_of(capsys))
    assert "KEEP branch=chore/overseer-audit-9 reason=audit-branch where=local" in out


# =============================================================================
# #2288 S1: reap-orphans --remote-scope all (remote janitor for non-worker heads)
# =============================================================================


def remote_only_branch(repo, name):
    """An old branch pushed to origin whose local copy is dropped: a remote-only head."""
    tip = make_old_branch(repo, name)
    push_branch(repo, name)
    git(repo, "branch", "-D", name)
    return tip


def recording_heads(repo, seen):
    def heads(pattern):
        seen.append(pattern)
        return list(remote_heads_of(repo, pattern).items())

    return heads


def reap_all(repo, **kw):
    kw.setdefault("do_local", False)
    return reap(repo, remote_scope="all", **kw)


def test_s1_closed_unmerged_pr_non_worker_remote_head_is_reaped(repo, capsys):
    tip = remote_only_branch(repo, "fix/foo")
    assert reap_all(repo, prs=[pr("fix/foo", tip, number=3)]) == 0
    assert f"REAPED branch=fix/foo reason=pr-closed where=remote pr=#3 tip={tip}" in lines_of(
        capsys
    )
    assert "fix/foo" not in remote_heads_of(repo)


def test_s2_merged_pr_non_worker_remote_head_is_reaped(repo, capsys):
    tip = remote_only_branch(repo, "feat/bar")
    reap_all(repo, prs=[pr("feat/bar", tip, merged=True, number=4)])
    assert f"REAPED branch=feat/bar reason=pr-merged where=remote pr=#4 tip={tip}" in lines_of(
        capsys
    )
    assert "feat/bar" not in remote_heads_of(repo)


def test_s3_protected_remote_names_are_kept(repo, capsys):
    names = ("audit-log", "release/0.5.x", "audit/x")
    for name in names:
        git(repo, "push", "-q", "origin", f"main:refs/heads/{name}")
    reap_all(repo, dry_run=True)
    out = lines_of(capsys)
    for name in ("main", *names):
        assert any(
            ln.startswith(f"KEEP branch={name} reason=protected-name where=remote") for ln in out
        )
    assert {"main", *names} <= set(remote_heads_of(repo))
    assert "REAPED" not in "\n".join(out)


def test_s4_unlanded_no_pr_remote_head_is_kept(repo, capsys):
    remote_only_branch(repo, "docs/wip")
    reap_all(repo, dry_run=True)
    assert any(
        ln.startswith("KEEP branch=docs/wip reason=unlanded-no-pr where=remote")
        for ln in lines_of(capsys)
    )
    assert "docs/wip" in remote_heads_of(repo)


def test_s5_landed_remote_heads_are_reaped_by_ancestor_and_content(repo, capsys):
    git(repo, "push", "-q", "origin", "main~1:refs/heads/docs/done-anc")
    make_branch(repo, "docs/done-content", "c.txt", "x\n")
    push_branch(repo, "docs/done-content")
    git(repo, "branch", "-D", "docs/done-content")
    advance_main(repo, "c.txt", "x\n")
    reap_all(repo)
    out = "\n".join(lines_of(capsys))
    assert "REAPED branch=docs/done-anc reason=landed-ancestor where=remote" in out
    assert "REAPED branch=docs/done-content reason=landed-content where=remote" in out
    assert not ({"docs/done-anc", "docs/done-content"} & set(remote_heads_of(repo)))


def test_s6_default_scope_ignores_non_worker_remote_heads(repo, capsys):
    fix_tip = remote_only_branch(repo, "fix/foo")
    w_tip = remote_only_branch(repo, "worker-5-x")
    seen = []
    prs = [pr("fix/foo", fix_tip, number=3), pr("worker-5-x", w_tip, merged=True, number=7)]
    reap(repo, prs=prs, do_local=False, remote_heads=recording_heads(repo, seen))
    out = lines_of(capsys)
    assert seen == ["refs/heads/worker-*"]
    assert f"REAPED branch=worker-5-x reason=pr-merged where=remote pr=#7 tip={w_tip}" in out
    assert not any("fix/foo" in ln for ln in out)
    assert "fix/foo" in remote_heads_of(repo) and "worker-5-x" not in remote_heads_of(repo)


def test_s7_dry_run_all_scope_reports_and_deletes_nothing(repo, capsys):
    closed_tip = remote_only_branch(repo, "fix/foo")
    merged_tip = remote_only_branch(repo, "feat/bar")
    remote_only_branch(repo, "docs/wip")
    git(repo, "push", "-q", "origin", "main~1:refs/heads/docs/done")
    before = git(repo, "ls-remote", "origin")

    def forbidden(items):
        raise AssertionError("remote_delete must not be called in a dry run")

    prs = [pr("fix/foo", closed_tip, number=3), pr("feat/bar", merged_tip, merged=True, number=4)]
    assert reap_all(repo, prs=prs, dry_run=True, remote_delete=forbidden) == 0
    out = lines_of(capsys)
    assert any(ln.startswith("WOULD-REAP branch=fix/foo reason=pr-closed") for ln in out)
    assert any(ln.startswith("WOULD-REAP branch=feat/bar reason=pr-merged") for ln in out)
    assert any(ln.startswith("WOULD-REAP branch=docs/done reason=landed-ancestor") for ln in out)
    assert any(ln.startswith("KEEP branch=docs/wip reason=unlanded-no-pr") for ln in out)
    assert not any(ln.startswith(("REAPED", "REAP-FAILED")) for ln in out)
    assert git(repo, "ls-remote", "origin") == before


def test_s8_open_pr_wins_for_non_worker_remote_heads(repo, capsys):
    tip = remote_only_branch(repo, "fix/open")
    git(repo, "push", "-q", "origin", "main~1:refs/heads/fix/open-landed")
    anc = git(repo, "rev-parse", "main~1")
    prs = [
        pr("fix/open", tip, number=1),
        pr("fix/open", tip, state="open", number=2),
        pr("fix/open-landed", anc, merged=True, number=3),
        pr("fix/open-landed", anc, state="open", number=4),
    ]
    reap_all(repo, prs=prs, dry_run=True)
    out = lines_of(capsys)
    assert f"KEEP branch=fix/open reason=open-pr where=remote tip={tip}" in out
    assert f"KEEP branch=fix/open-landed reason=open-pr where=remote tip={anc}" in out
    assert {"fix/open", "fix/open-landed"} <= set(remote_heads_of(repo))


def test_s9_pre_delete_recheck_open_pr_keeps_non_worker_head(repo, capsys):
    tip = remote_only_branch(repo, "fix/x")
    closed_pr = pr("fix/x", tip, number=1)
    opened = pr("fix/x", tip, state="open", number=2)
    pulls = lambda state: [pr("unrelated-x", OTHER_SHA, merged=True, number=999)] + (  # noqa: E731
        [opened] if state == "open" else [closed_pr]
    )
    reap_all(repo, pulls=pulls)
    out = lines_of(capsys)
    assert not any(ln.startswith("REAP") for ln in out)
    assert "kept=2" in out[-1] and "recheck=done" in out[-1]
    assert "fix/x" in remote_heads_of(repo)


def test_s10_non_worker_heads_never_read_issue_states(repo, capsys):
    tip = remote_only_branch(repo, "fix/foo")
    remote_only_branch(repo, "fix/worker-12-x")
    git(repo, "push", "-q", "origin", "main~1:refs/heads/docs/done")
    reads = []

    def counting(needed):
        reads.append(set(needed))
        return {}

    prs = [pr("fix/foo", tip, number=3)]
    reap_all(repo, prs=prs, issue_states=counting, dry_run=True)
    out = "\n".join(lines_of(capsys))
    assert "WOULD-REAP branch=fix/foo" in out and "WOULD-REAP branch=docs/done" in out
    assert "KEEP branch=fix/worker-12-x reason=unlanded-no-pr" in out
    reap_all(repo, prs=prs, issue_states=counting)
    assert "fix/foo" not in remote_heads_of(repo) and "docs/done" not in remote_heads_of(repo)
    assert reads == []


def test_s11_all_scope_lists_every_head_pattern(repo, capsys):
    remote_only_branch(repo, "a/b/c")
    seen = []
    reap_all(repo, remote_heads=recording_heads(repo, seen), dry_run=True)
    assert seen == ["refs/heads/*"]
    assert any(
        ln.startswith("KEEP branch=a/b/c reason=unlanded-no-pr where=remote")
        for ln in lines_of(capsys)
    )


def test_s12_scope_usage_errors(repo):
    git(repo, "branch", "keep-me", "main")
    before = branches(repo)
    base = ["--repo", str(repo), "reap-orphans"]
    for argv in (
        [*base, "--local-only", "--remote-scope", "all"],
        [*base, "--remote-scope", "bogus"],
    ):
        with pytest.raises(SystemExit) as exc:
            readopt.main(argv)
        assert exc.value.code == 2
    with pytest.raises(ValueError):
        readopt.reap_orphans(repo, slug=SLUG, now=FAR, remote_scope="x")
    assert branches(repo) == before


def test_s13_all_scope_leaves_worker_head_decisions_unchanged(repo, capsys):
    remote_only_branch(repo, "worker-40-x")
    remote_only_branch(repo, "worker-41-x")
    issues = {40: "closed", 41: "open"}
    worker_lines = {}
    for scope in ("worker", "all"):
        reap(repo, issues=issues, do_local=False, remote_scope=scope, dry_run=True)
        worker_lines[scope] = [ln for ln in lines_of(capsys) if "branch=worker-" in ln]
    assert worker_lines["worker"] == worker_lines["all"]
    joined = "\n".join(worker_lines["all"])
    assert "WOULD-REAP branch=worker-40-x reason=issue-closed where=remote" in joined
    assert "KEEP branch=worker-41-x reason=unlanded-open-issue where=remote" in joined
    reap_all(repo, issues=issues)
    assert any(
        ln.startswith("REAPED branch=worker-40-x reason=issue-closed where=remote")
        for ln in lines_of(capsys)
    )
    assert "worker-40-x" not in remote_heads_of(repo) and "worker-41-x" in remote_heads_of(repo)


def test_s14_unsafe_remote_names_never_reach_git_or_delete(repo, capsys):
    main_tip = git(repo, "rev-parse", "main")
    real = readopt.make_git(repo)
    calls = []

    def spy(args):
        calls.append(list(args))
        return real(args)

    deleted = []
    reap_all(
        repo,
        git=spy,
        remote_heads=lambda pat: [("-x", main_tip), ("é", main_tip)],
        remote_delete=lambda items: deleted.append(items) or {},
        dry_run=True,
    )
    out = "\n".join(lines_of(capsys))
    assert f"KEEP branch=-x reason=unsafe-name where=remote tip={main_tip}" in out
    assert f"KEEP branch=%C3%A9 reason=unsafe-name where=remote tip={main_tip}" in out
    assert "é" not in out
    assert not any(a == "-x" or "é" in a for c in calls for a in c)
    assert deleted == []


def test_s14b_unsafe_remote_names_never_deleted_in_a_real_run(repo, capsys):
    main_tip = git(repo, "rev-parse", "main")
    real = readopt.make_git(repo)
    calls = []

    def spy(args):
        calls.append(list(args))
        return real(args)

    deleted = []
    assert (
        reap_all(
            repo,
            git=spy,
            remote_heads=lambda pat: [("-x", main_tip), ("é", main_tip)],
            remote_delete=lambda items: deleted.append(list(items)) or {},
        )
        == 0
    )
    out = "\n".join(lines_of(capsys))
    assert "kept=2 failed=0" in out and "reaped_remote=0" in out
    assert not any(ln.startswith(("REAPED", "REAP-FAILED")) for ln in out.splitlines())
    assert not any(a == "-x" or "é" in a for c in calls for a in c)
    assert deleted == []


def test_s15_zero_unique_commit_non_worker_head_reaped_as_landed_ancestor(repo, capsys):
    git(repo, "push", "-q", "origin", "main:refs/heads/fix/same-as-main")
    tip = git(repo, "rev-parse", "main")
    reap_all(repo)
    assert f"REAPED branch=fix/same-as-main reason=landed-ancestor where=remote pr=- tip={tip}" in (
        lines_of(capsys)
    )
    assert "fix/same-as-main" not in remote_heads_of(repo)


def test_s15b_zero_unique_commit_non_worker_head_within_grace_is_kept(repo, capsys):
    git(repo, "push", "-q", "origin", "main:refs/heads/fix/same-as-main")
    tip = git(repo, "rev-parse", "main")
    committed = int(git(repo, "log", "-1", "--format=%ct", tip))
    reap_all(repo, now=committed + 3600, dry_run=True)
    assert any(
        ln.startswith("KEEP branch=fix/same-as-main reason=grace where=remote")
        for ln in lines_of(capsys)
    )
    assert "fix/same-as-main" in remote_heads_of(repo)


def test_s16_worker_scope_filters_non_worker_names_even_if_listing_returns_them(repo, capsys):
    tip = git(repo, "rev-parse", "main~1")
    git(repo, "push", "-q", "origin", "main~1:refs/heads/fix/foo")
    reap(
        repo,
        do_local=False,
        dry_run=True,
        remote_heads=lambda pat: [("fix/foo", tip), ("worker-9-x", tip)],
    )
    out = lines_of(capsys)
    assert not any("fix/foo" in ln for ln in out)
    assert any("branch=worker-9-x" in ln for ln in out)


def test_s17_cli_remote_scope_default_and_explicit_plumbing(repo, monkeypatch):
    seen = []
    monkeypatch.setattr(readopt, "reap_orphans", lambda r, **kw: seen.append(kw) or 0)
    base = ["--repo", str(repo), "reap-orphans"]
    assert readopt.main(base) == 0
    assert readopt.main([*base, "--remote-scope", "all"]) == 0
    assert readopt.main([*base, "--remote-scope", "worker"]) == 0
    assert readopt.main([*base, "--local-only"]) == 0
    assert [kw["remote_scope"] for kw in seen] == ["worker", "all", "worker", "worker"]


# ---------------------------------------------------------------------------
# #2288 delete-head
# ---------------------------------------------------------------------------

DH_SLUG = ("acme", "proj")


def push_head(repo: Path, ref: str, rev: str = "main~1") -> str:
    git(repo, "push", "-q", "origin", f"{rev}:refs/heads/{ref}")
    return git(repo, "rev-parse", rev)


def origin_refs(repo: Path) -> str:
    return git(repo, "ls-remote", "--heads", "origin")


def make_pr(ref, sha, *, state="closed", merged=False, head_repo="acme/proj", default="main"):
    return {
        "state": state,
        "merged_at": "2026-01-01T00:00:00Z" if merged else None,
        "base": {"repo": {"full_name": "Acme/Proj", "default_branch": default}},
        "head": {
            "ref": ref,
            "sha": sha,
            "repo": None if head_repo is None else {"full_name": head_repo},
        },
    }


def dh(repo, pr, **kw):
    kw.setdefault("open_pulls_for", lambda b: [])
    kw.setdefault("open_pulls_based_on", lambda b: [])
    return readopt.delete_head(
        repo, 7, git=readopt.make_git(repo), get_pull=lambda n: pr, slug=DH_SLUG, **kw
    )


def test_dh1_closed_pr_head_deleted_on_origin(repo, capsys):
    tip = push_head(repo, "fix/x")
    assert dh(repo, make_pr("fix/x", tip)) == 0
    assert capsys.readouterr().out.splitlines()[-1] == f"DELETED pr=#7 branch=fix/x tip={tip}"
    assert "refs/heads/fix/x" not in origin_refs(repo)


def test_dh2_second_run_already_gone(repo, capsys):
    tip = push_head(repo, "fix/x")
    assert dh(repo, make_pr("fix/x", tip)) == 0
    assert dh(repo, make_pr("fix/x", tip)) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "ALREADY-GONE pr=#7 branch=fix/x"


def test_dh3_never_pushed_no_delete_attempted(repo, capsys):
    tip = git(repo, "rev-parse", "main")
    calls = []
    assert dh(repo, make_pr("fix/x", tip), remote_delete=lambda i: calls.append(i) or {}) == 0
    assert calls == []
    assert "ALREADY-GONE" in capsys.readouterr().out


@pytest.mark.parametrize(
    "ref", ["main", "audit-log", "release/0.5.x", "audit/overseer-cycle-x", "trunk"]
)
def test_dh4_protected_names_kept(repo, capsys, ref):
    tip = push_head(repo, ref) if ref != "main" else git(repo, "rev-parse", "main")
    boom = lambda *a: pytest.fail("remote must not be touched")  # noqa: E731
    pr = make_pr(ref, tip, default="trunk" if ref == "trunk" else "main")
    assert dh(repo, pr, remote_heads=boom, remote_delete=boom) == 3
    assert f"KEPT pr=#7 branch={ref} reason=protected-name" in capsys.readouterr().out
    assert ref == "main" or f"refs/heads/{ref}" in origin_refs(repo)


def test_dh5_open_pr_kept(repo, capsys):
    tip = push_head(repo, "fix/x")
    assert dh(repo, make_pr("fix/x", tip, state="open")) == 3
    assert "reason=pr-open" in capsys.readouterr().out
    assert "refs/heads/fix/x" in origin_refs(repo)


def test_dh6_other_open_pr_on_same_head_kept(repo, capsys):
    tip = push_head(repo, "fix/x")
    other = [{"head": {"repo": {"full_name": "ACME/proj"}}}]
    assert dh(repo, make_pr("fix/x", tip), open_pulls_for=lambda b: other) == 3
    assert "reason=open-pr" in capsys.readouterr().out
    assert "refs/heads/fix/x" in origin_refs(repo)


def test_dh7_moved_tip_kept(repo, capsys):
    old = push_head(repo, "fix/x", "main~1")
    git(repo, "push", "-q", "origin", "main:refs/heads/fix/x")
    assert dh(repo, make_pr("fix/x", old)) == 3
    now = git(repo, "rev-parse", "main")
    last = capsys.readouterr().out.splitlines()[-1]
    assert last == f"KEPT pr=#7 branch=fix/x reason=moved expected={old} tip={now}"
    assert "refs/heads/fix/x" in origin_refs(repo)


def test_dh7b_base_of_open_pr_kept(repo, capsys):
    tip = push_head(repo, "fix/x")
    asked = []

    def based(b):
        asked.append(b)
        return [{"number": 9}]

    assert dh(repo, make_pr("fix/x", tip), open_pulls_based_on=based) == 3
    assert asked == ["fix/x"]
    assert "KEPT pr=#7 branch=fix/x reason=base-of-open-pr" in capsys.readouterr().out
    assert "refs/heads/fix/x" in origin_refs(repo)


def test_dh7c_base_lookup_failure_fails_closed(repo, capsys):
    tip = push_head(repo, "fix/x")

    def boom(b):
        raise readopt.github.GitHubError("api down")

    assert dh(repo, make_pr("fix/x", tip), open_pulls_based_on=boom) == 2
    assert "ERROR pr=#7" in capsys.readouterr().out
    assert "refs/heads/fix/x" in origin_refs(repo)


@pytest.mark.parametrize("head_repo", [None, "other/proj"])
def test_dh8_fork_kept(repo, capsys, head_repo):
    tip = push_head(repo, "fix/x")
    assert dh(repo, make_pr("fix/x", tip, head_repo=head_repo)) == 3
    assert "reason=fork" in capsys.readouterr().out
    assert "refs/heads/fix/x" in origin_refs(repo)


def test_dh8b_unsafe_name_printed_encoded(repo, capsys):
    tip = git(repo, "rev-parse", "main")
    assert dh(repo, make_pr("fix/x\x1b[31m", tip)) == 3
    out = capsys.readouterr().out
    assert "\x1b" not in out and "reason=unsafe-name" in out


def test_dh9_missing_pr_and_github_error_fail_closed(repo, capsys):
    tip = push_head(repo, "fix/x")
    assert dh(repo, None) == 2
    assert "ERROR pr=#7 reason=PR #7 not found" in capsys.readouterr().out

    def boom(n):
        raise readopt.github.GitHubError("api down")

    rc = readopt.delete_head(
        repo,
        7,
        git=readopt.make_git(repo),
        get_pull=boom,
        slug=DH_SLUG,
        open_pulls_for=lambda b: [],
    )
    assert rc == 2
    assert capsys.readouterr().out.splitlines()[-1].startswith("ERROR pr=#7")
    assert "refs/heads/fix/x" in origin_refs(repo)
    assert tip


def test_dh9b_foreign_repo_pr_is_error(repo, capsys):
    tip = push_head(repo, "fix/x")
    pr = make_pr("fix/x", tip)
    pr["base"]["repo"]["full_name"] = "other/proj"
    assert dh(repo, pr) == 2
    assert "not in this repository" in capsys.readouterr().out


def test_dh9c_unreadable_sha_is_error(repo, capsys):
    push_head(repo, "fix/x")
    assert dh(repo, make_pr("fix/x", "nothex")) == 2
    assert "SHA unreadable" in capsys.readouterr().out


def test_dh10_open_pr_lookup_failure_fails_closed(repo, capsys):
    tip = push_head(repo, "fix/x")

    def boom(b):
        raise readopt.github.GitHubError("api down")

    assert dh(repo, make_pr("fix/x", tip), open_pulls_for=boom) == 2
    assert "refs/heads/fix/x" in origin_refs(repo)


def test_dh11_push_timeout_is_error(repo, capsys):
    tip = push_head(repo, "fix/x")
    rc = dh(repo, make_pr("fix/x", tip), remote_delete=lambda i: {"fix/x": readopt.PUSH_TIMEOUT})
    assert rc == 2
    assert "outcome unknown" in capsys.readouterr().out


def test_dh12_rejected_push_then_gone_is_already_gone(repo, capsys):
    tip = push_head(repo, "fix/x")

    def lose_race(items):
        git(repo, "push", "-q", "origin", ":refs/heads/fix/x")
        return {"fix/x": False}

    assert dh(repo, make_pr("fix/x", tip), remote_delete=lose_race) == 0
    assert "ALREADY-GONE" in capsys.readouterr().out


def test_dh12b_rejected_push_still_present_is_error(repo, capsys):
    tip = push_head(repo, "fix/x")
    assert dh(repo, make_pr("fix/x", tip), remote_delete=lambda i: {"fix/x": False}) == 2
    assert "push rejected" in capsys.readouterr().out
    assert "refs/heads/fix/x" in origin_refs(repo)


def test_dh13_tail_match_noise_ignored(repo, capsys):
    tip = push_head(repo, "fix/x")
    push_head(repo, "x/refs/heads/fix/x")
    assert dh(repo, make_pr("fix/x", tip)) == 0
    refs = origin_refs(repo)
    assert "refs/heads/x/refs/heads/fix/x" in refs
    assert not any(ln.endswith("\trefs/heads/fix/x") for ln in refs.splitlines())


def test_dh14_is_protected_branch():
    for name in ("main", "audit-log", "release/0.5.x", "audit/overseer-cycle-x"):
        assert readopt.is_protected_branch(name)
    for name in ("mainline", "release", "audit-logs", "fix/release/x"):
        assert not readopt.is_protected_branch(name)


@pytest.mark.parametrize("bad", ["0", "-1", "abc"])
def test_dh15_cli_rejects_bad_pr(repo, bad):
    with pytest.raises(SystemExit) as exc:
        readopt.main(["--repo", str(repo), "delete-head", "--pr", bad])
    assert exc.value.code == 2


def test_dh16_merged_pr_head_deleted(repo, capsys):
    tip = push_head(repo, "fix/x")
    assert dh(repo, make_pr("fix/x", tip, merged=True)) == 0
    assert "DELETED" in capsys.readouterr().out
    assert "refs/heads/fix/x" not in origin_refs(repo)


def test_dh17_cli_plumbs_pr_number(repo, monkeypatch):
    seen = []
    monkeypatch.setattr(readopt, "delete_head", lambda r, n, **kw: seen.append(n) or 3)
    assert readopt.main(["--repo", str(repo), "delete-head", "--pr", "12"]) == 3
    assert seen == [12]


def test_dh18_remote_phase_unavailable_is_error_and_deletes_nothing(repo, monkeypatch, capsys):
    tip = push_head(repo, "fix/x")
    monkeypatch.setattr(readopt, "_remote_ops", lambda git, r: None)
    assert dh(repo, make_pr("fix/x", tip)) == 2
    assert "reason=remote phase unavailable" in capsys.readouterr().out
    assert "refs/heads/fix/x" in origin_refs(repo)


def test_dh19_open_pr_from_other_repo_does_not_block_delete(repo, capsys):
    tip = push_head(repo, "fix/x")
    other = [{"head": {"repo": {"full_name": "stranger/proj"}}}]
    assert dh(repo, make_pr("fix/x", tip), open_pulls_for=lambda b: other) == 0
    assert "DELETED" in capsys.readouterr().out
    assert "refs/heads/fix/x" not in origin_refs(repo)


# =============================================================================
# #2293 archive-before-delete (refs/archive/reap/*) and --list-archives
# =============================================================================


def archive_name(branch: str, tip: str) -> str:
    return f"refs/archive/reap/{branch}@{tip[:12]}"


def d2_branch(repo, name="worker-30-x"):
    return make_branch(repo, name, "a.txt", "unlanded\n")


def test_a1_local_d2_writes_archive_ref_and_reaped_line_carries_it(repo, capsys):
    tip = d2_branch(repo)
    reap(repo, issues={30: "closed"})
    out = lines_of(capsys)
    ref = archive_name("worker-30-x", tip)
    assert "worker-30-x" not in branches(repo)
    assert git(repo, "rev-parse", ref) == tip
    assert any(
        ln.startswith("REAPED branch=worker-30-x reason=issue-closed")
        and ln.endswith(f" tip={tip}")
        for ln in out
    )
    assert not any(ln.startswith(("REAPED", "REAP-FAILED")) and "archive=" in ln for ln in out)
    archived = f"ARCHIVED branch=worker-30-x where=local ref={ref} tip={tip}"
    assert archived in out
    assert out.index(archived) < next(i for i, ln in enumerate(out) if ln.startswith("REAPED"))
    assert out[-1].endswith("archived=1")


def test_a2_archive_at_different_sha_blocks_deletion(repo, capsys):
    tip = d2_branch(repo)
    git(repo, "update-ref", archive_name("worker-30-x", tip), "main")
    reap(repo, issues={30: "closed"})
    out = lines_of(capsys)
    assert "worker-30-x" in branches(repo)
    assert any("KEEP branch=worker-30-x reason=archive-failed" in ln for ln in out)
    # kept=2: the checked-out main plus the archive-failed branch
    assert "kept=2" in out[-1] and "failed=0" in out[-1] and "archived=0" in out[-1]
    assert git(repo, "rev-parse", archive_name("worker-30-x", tip)) != tip


def test_a2b_update_ref_failure_blocks_deletion(repo, capsys):
    tip = d2_branch(repo)
    flaky = _failing_git(repo, fail_prefix=("update-ref", archive_name("worker-30-x", tip)))
    reap(repo, issues={30: "closed"}, git=flaky)
    out = lines_of(capsys)
    assert "worker-30-x" in branches(repo)
    assert any("reason=archive-failed" in ln for ln in out)
    assert "kept=2" in out[-1]
    assert not git(repo, "for-each-ref", "refs/archive/")


def test_a2c_read_back_mismatch_blocks_deletion(repo, capsys):
    d2_branch(repo)
    real = readopt.make_git(repo)

    def run(args):
        if list(args[:3]) == ["rev-parse", "--verify", "-q"]:
            return 0, "1" * 40
        return real(args)

    reap(repo, issues={30: "closed"}, git=run)
    out = lines_of(capsys)
    assert "worker-30-x" in branches(repo)
    assert any("reason=archive-failed" in ln for ln in out)
    assert "kept=2" in out[-1] and "archived=0" in out[-1]


def test_a3_existing_archive_at_same_tip_is_idempotent(repo, capsys):
    tip = d2_branch(repo)
    git(repo, "update-ref", archive_name("worker-30-x", tip), tip)
    reap(repo, issues={30: "closed"})
    out = lines_of(capsys)
    assert "worker-30-x" not in branches(repo)
    assert any(ln.startswith("ARCHIVED branch=worker-30-x") for ln in out)
    assert any(ln.startswith("REAPED branch=worker-30-x") for ln in out)
    assert git(repo, "rev-parse", archive_name("worker-30-x", tip)) == tip


def test_a4_remote_d2_archives_before_delete_and_gates_the_batch(repo, capsys):
    tips = {}
    for n in ("a", "b", "c"):
        name = f"worker-30-{n}"
        tips[name] = make_branch(repo, name, "a.txt", f"unlanded {n}\n")
        push_branch(repo, name)
        git(repo, "branch", "-D", name)
    order = []

    def rarchive(items):
        order.append(("archive", list(items)))
        return {
            "worker-30-a": True,
            "worker-30-b": False,
            "worker-30-c": readopt.PUSH_TIMEOUT,
        }

    def rdelete(items):
        order.append(("delete", list(items)))
        return {b: True for b, _ in items}

    reap(
        repo,
        issues={30: "closed"},
        do_local=False,
        remote_heads=recording_heads(repo, []),
        remote_delete=rdelete,
        remote_archive=rarchive,
    )
    out = lines_of(capsys)
    assert [k for k, _ in order] == ["archive", "delete"]
    assert order[0][1] == sorted((n, t) for n, t in tips.items())
    assert order[1][1] == [("worker-30-a", tips["worker-30-a"])]
    ref_a = archive_name("worker-30-a", tips["worker-30-a"])
    assert any(ln.startswith("REAPED branch=worker-30-a") for ln in out)
    assert f"ARCHIVED branch=worker-30-a where=remote ref={ref_a} tip={tips['worker-30-a']}" in out
    for n in ("b", "c"):
        want = f"KEEP branch=worker-30-{n} reason=archive-failed where=remote"
        assert any(want in ln for ln in out)
    assert not any("REAPED branch=worker-30-b" in ln for ln in out)
    assert "reaped_remote=1" in out[-1] and "kept=2" in out[-1] and "archived=1" in out[-1]
    # best-effort local copy exists too
    assert git(repo, "rev-parse", ref_a) == tips["worker-30-a"]


def test_a4b_remote_d2_without_archive_runner_fails_closed(repo, capsys):
    tip = make_branch(repo, "worker-30-x", "a.txt", "unlanded\n")
    push_branch(repo, "worker-30-x")
    git(repo, "branch", "-D", "worker-30-x")
    deleted = []
    reap(
        repo,
        issues={30: "closed"},
        do_local=False,
        remote_heads=recording_heads(repo, []),
        remote_delete=lambda items: deleted.extend(items) or {},
    )
    assert not deleted
    assert any("KEEP branch=worker-30-x reason=archive-failed" in ln for ln in lines_of(capsys))
    assert tip


def test_a5_non_archive_reasons_write_no_archive_ref(repo, capsys):
    tip = make_branch(repo, "worker-7-m", "a.txt", "merged work\n")
    git(repo, "branch", "worker-7-anc", "main")
    tip2 = make_branch(repo, "worker-8-c", "a.txt", "closed pr work\n")
    reap(
        repo,
        prs=[pr("worker-7-m", tip, merged=True, number=2), pr("worker-8-c", tip2, number=3)],
        issues={7: "open", 8: "closed"},
    )
    out = lines_of(capsys)
    reasons = {"pr-merged", "landed-ancestor", "pr-closed"}
    assert {re.search(r"reason=(\S+)", ln).group(1) for ln in out if ln.startswith("REAPED")} == (
        reasons
    )
    assert not any("archive=" in ln for ln in out)
    assert not git(repo, "for-each-ref", "refs/archive/")
    assert out[-1].endswith("archived=0")


def test_a6_selectors_ignore_archive_refs(repo, capsys):
    tip = d2_branch(repo)
    reap(repo, issues={30: "closed"})
    capsys.readouterr()
    assert git(repo, "rev-parse", archive_name("worker-30-x", tip)) == tip
    assert not git(repo, "for-each-ref", "refs/heads/worker-30-*")
    reap(repo, issues={30: "closed"})
    out = lines_of(capsys)
    assert not any("worker-30-x" in ln for ln in out)
    assert swc._started_stages(str(repo), [30]) == {}
    readopt.prune_attempts(repo, 30, issue_closed=True, issue_state=lambda n: "closed")
    assert git(repo, "rev-parse", archive_name("worker-30-x", tip)) == tip


def test_a7_restore_recreates_branch_at_old_tip(repo):
    tip = d2_branch(repo)
    reap(repo, issues={30: "closed"})
    assert "worker-30-x" not in branches(repo)
    git(repo, "branch", "worker-30-x", archive_name("worker-30-x", tip))
    assert git(repo, "rev-parse", "worker-30-x") == tip


def test_a8_dry_run_prints_archive_and_writes_nothing(repo, capsys):
    tip = d2_branch(repo)
    reap(repo, issues={30: "closed"}, dry_run=True)
    out = lines_of(capsys)
    assert any(
        ln.startswith("WOULD-REAP branch=worker-30-x reason=issue-closed")
        and ln.endswith(f"archive={archive_name('worker-30-x', tip)}")
        for ln in out
    )
    assert not git(repo, "for-each-ref", "refs/archive/")
    assert "worker-30-x" in branches(repo)


def test_a9_archive_failure_does_not_consume_deletion_budget(repo, capsys):
    t1 = make_branch(repo, "worker-30-a", "a.txt", "one\n")
    make_branch(repo, "worker-30-b", "b.txt", "two\n")
    git(repo, "update-ref", archive_name("worker-30-a", t1), "main")  # blocks only -a
    reap(repo, issues={30: "closed"}, max_deletions=1)
    out = lines_of(capsys)
    assert any("KEEP branch=worker-30-a reason=archive-failed" in ln for ln in out)
    assert any(ln.startswith("REAPED branch=worker-30-b") for ln in out)
    assert not any(ln.startswith("DEFERRED") for ln in out)


def test_a10_push_archive_parses_porcelain_and_timeout():
    items = [("worker-1-a", "a" * 40), ("worker-1-b", "b" * 40)]
    ref_a = archive_name(*items[0])
    seen = []

    def run(args, timeout):
        seen.append(list(args))
        return 0, f"To x\n*\t{'a' * 40}:{ref_a}\t[new reference]\n!\tb:c\t[rejected]\nDone\n"

    got = readopt._push_archive(run, "u", items)
    assert got == {"worker-1-a": True, "worker-1-b": False}
    assert "--force" not in " ".join(seen[0]) and f"{'a' * 40}:{ref_a}" in seen[0]
    assert readopt._push_archive(lambda a, t: (readopt._RC_TIMEOUT, ""), "u", items) == {
        "worker-1-a": readopt.PUSH_TIMEOUT,
        "worker-1-b": readopt.PUSH_TIMEOUT,
    }


def test_a11_list_archives_lists_flags_old_and_deletes_nothing(repo, capsys):
    old = make_old_branch(repo, "worker-40-old")  # commit dated 2026-01-01
    git(repo, "checkout", "-q", "main")
    new = make_branch(repo, "worker-41-new", "b.txt", "n\n")
    git(repo, "update-ref", archive_name("worker-40-old", old), old)
    git(repo, "update-ref", archive_name("worker-41-new", new), new)
    before = ref_snapshot(repo)
    calls = readopt.github.gh_call_count()
    far = int(time.time()) + 30 * 86400
    assert readopt.list_archives(repo, now=far, age_days=45) == 0
    out = lines_of(capsys)
    assert readopt.github.gh_call_count() == calls
    assert ref_snapshot(repo) == before
    old_ln = next(ln for ln in out if "worker-40-old" in ln)
    new_ln = next(ln for ln in out if "worker-41-new" in ln)
    prefix = f"ARCHIVE ref={archive_name('worker-40-old', old)} tip={old} age_days="
    assert old_ln.startswith(prefix)
    assert old_ln.endswith("older-than=45d")
    assert "older-than" not in new_ln
    assert out[-1] == "ARCHIVES total=2 older=1 threshold_days=45"


def test_a12_cli_list_archives_never_reaps(repo, capsys):
    tip = d2_branch(repo)
    git(repo, "update-ref", archive_name("worker-30-x", tip), tip)
    assert readopt.main(["--repo", str(repo), "reap-orphans", "--list-archives"]) == 0
    out = lines_of(capsys)
    assert out[-1] == "ARCHIVES total=1 older=0 threshold_days=90"
    assert "worker-30-x" in branches(repo)


def test_a13_check_ref_format_failure_blocks_deletion(repo, capsys):
    d2_branch(repo)
    reap(
        repo,
        issues={30: "closed"},
        git=_failing_git(repo, fail_prefix=("check-ref-format",), rc=1),
    )
    out = lines_of(capsys)
    assert "worker-30-x" in branches(repo)
    assert any("KEEP branch=worker-30-x reason=archive-failed" in ln for ln in out)
    assert not any(ln.startswith("REAPED") for ln in out)
    assert not git(repo, "for-each-ref", "refs/archive/")


def test_a14_remote_archive_raising_keeps_ref_and_skips_delete(repo, capsys):
    make_branch(repo, "worker-30-x", "a.txt", "unlanded\n")
    push_branch(repo, "worker-30-x")
    git(repo, "branch", "-D", "worker-30-x")
    deleted = []

    def boom(items):
        raise RuntimeError("network down")

    reap(
        repo,
        issues={30: "closed"},
        do_local=False,
        remote_heads=recording_heads(repo, []),
        remote_delete=lambda items: deleted.extend(items) or {},
        remote_archive=boom,
    )
    out = lines_of(capsys)
    assert not deleted
    assert any(ln.startswith("WARN: remote archive failed") for ln in out)
    assert any("KEEP branch=worker-30-x reason=archive-failed where=remote" in ln for ln in out)
    assert "worker-30-x" in remote_heads_of(repo)


def test_a15_remote_archive_failure_still_uses_budget_so_later_ref_is_deferred(repo, capsys):
    for n in ("a", "b"):
        make_branch(repo, f"worker-30-{n}", "a.txt", f"unlanded {n}\n")
        push_branch(repo, f"worker-30-{n}")
        git(repo, "branch", "-D", f"worker-30-{n}")
    reap(
        repo,
        issues={30: "closed"},
        do_local=False,
        max_deletions=1,
        remote_heads=recording_heads(repo, []),
        remote_delete=lambda items: {b: True for b, _ in items},
        remote_archive=lambda items: {b: False for b, _ in items},
    )
    out = lines_of(capsys)
    assert any("KEEP branch=worker-30-a reason=archive-failed" in ln for ln in out)
    assert any(ln.startswith("DEFERRED branch=worker-30-b") for ln in out)


def test_a16_reaped_lines_match_hos_cron_event_regex(repo, capsys):
    """bin/hos-cron audits REAPED lines with an END-ANCHORED regex; an archived reap must
    still match it (#2293 regression). The literal is read from the file, not copied."""
    text = (Path(__file__).resolve().parents[2] / "bin" / "hos-cron").read_text()
    found = re.findall(r"^\s*_RB_EVENT_RE='([^']+)'$", text, re.MULTILINE)
    assert len(found) == 1
    event_re = re.compile(found[0])
    tip = d2_branch(repo)
    reap(repo, issues={30: "closed"})
    reaped = lines_of(capsys, "REAPED")
    assert len(reaped) == 1
    m = event_re.match(reaped[0])
    assert m and m.group(2) == "worker-30-x" and m.group(7) == tip


def _real_push_runner(repo: Path):
    def run(args, timeout):
        proc = subprocess.run(
            ["git", "-C", str(repo), *IDENT, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout

    return run


def test_a17_push_archive_real_bare_repo_creates_ref_at_tip_and_is_idempotent(repo, tmp_path):
    tip = make_branch(repo, "worker-50-a", "a.txt", "unlanded\n")
    origin = str(tmp_path / "origin.git")
    run = _real_push_runner(repo)
    items = [("worker-50-a", tip)]
    ref = readopt._archive_ref("worker-50-a", tip)
    assert readopt._push_archive(run, origin, items) == {"worker-50-a": True}
    assert git(tmp_path / "origin.git", "rev-parse", ref) == tip
    # Second push: porcelain "=" (up to date) still counts as archived.
    assert readopt._push_archive(run, origin, items) == {"worker-50-a": True}


def test_a18_push_archive_real_bare_repo_failure_is_false_and_never_forces(repo, tmp_path):
    tip = make_branch(repo, "worker-50-b", "a.txt", "unlanded\n")
    run = _real_push_runner(repo)
    bad = str(tmp_path / "does-not-exist.git")
    assert readopt._push_archive(run, bad, [("worker-50-b", tip)]) == {"worker-50-b": False}
    # A ref already at a different sha is rejected, not overwritten.
    origin = tmp_path / "origin.git"
    ref = readopt._archive_ref("worker-50-b", tip)
    # Divergent (not an ancestor of tip) so a non-forced push is a rejected non-ff.
    other = make_branch(repo, "worker-50-other", "b.txt", "divergent\n")
    git(repo, "push", "-q", "origin", "worker-50-other")
    git(origin, "update-ref", ref, other)
    assert readopt._push_archive(run, str(origin), [("worker-50-b", tip)]) == {"worker-50-b": False}
    assert git(origin, "rev-parse", ref) == other


def test_a19_push_archive_chunks_over_push_chunk(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(readopt, "PUSH_CHUNK", 2)
    tips = []
    for i in range(3):
        name = f"worker-6{i}-c"
        tips.append((name, make_branch(repo, name, "a.txt", f"w{i}\n")))
    calls = []
    inner = _real_push_runner(repo)

    def run(args, timeout):
        calls.append(args)
        return inner(args, timeout)

    got = readopt._push_archive(run, str(tmp_path / "origin.git"), tips)
    assert got == {n: True for n, _ in tips}
    assert len(calls) == 2


def test_a20_list_archives_rc2_when_for_each_ref_fails(repo, capsys):
    def bad(args):
        return 1, ""

    assert readopt.list_archives(repo, git=bad) == 2
    assert "listing archives failed" in capsys.readouterr().err
