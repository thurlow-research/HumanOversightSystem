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
        ["git", "-C", str(repo), *IDENT, *args], capture_output=True, text=True, check=check
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
        ["--repo", str(repo), "review-path", "--original-head", "nope", "--merged-head", "nope2"]
    )
    assert rc == 2


def test_review_path_cli_prints_lines(repo, capsys):
    original, merged = _merged_scenario(repo, "b.txt")
    rc = readopt.main(
        ["--repo", str(repo), "review-path", "--original-head", original, "--merged-head", merged]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "REVIEW_PATH=delta" in out
    assert "REASON=" in out


def test_review_path_cli_rejects_option_like_ref(repo):
    rc = readopt.main(
        ["--repo", str(repo), "review-path", "--original-head=--output=x", "--merged-head", "HEAD"]
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
    monkeypatch.setattr(readopt, "github_issue_state", lambda git: (lambda n: "open"))
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
        repo, pr_lookup=lambda b, t: calls.append(b) or False, max_lookups=cap, seed=seed
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
        ["--repo", str(repo), "review-path", "--original-head", "HEAD", "--merged-head", "HEAD"]
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
        ["--repo", str(repo), "review-path", "--original-head", original, "--merged-head", original]
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
    assert branches(repo) >= {"main", "audit-log", "release/x", "audit/y", "wt-b", "cur"}
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


def test_t7_tip_beyond_merged_pr_head_is_kept(repo, capsys):
    git(repo, "checkout", "-q", "-b", "worker-40-x", "main")
    first = commit(repo, "a.txt", "one\n", "first")
    commit(repo, "a.txt", "two\n", "second")
    git(repo, "checkout", "-q", "main")
    reap(repo, prs=[pr("worker-40-x", first, merged=True)], issues={40: "open"})
    assert "worker-40-x" in branches(repo)
    reap(repo, prs=[pr("worker-40-x", first, merged=True)], issues={40: "open"}, dry_run=True)
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
        repo, prs=[pr("worker-5-x", tip, merged=True)], issues={6: "open", 7: "open"}, dry_run=True
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
        self.calls, self.envs = [], []
        self.heads, self.push_rc, self.push_out = list(heads), push_rc, push_out
        self.ls_rc, self.stderr = ls_rc, stderr

    def factory(self, repo, extra_env):
        self.envs.append(dict(extra_env))

        def run(args, timeout=60):
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
    run = readopt.make_git_remote(repo, {})
    rc, _ = run(["version"], 30)
    assert rc == 0 and run.last_stderr == ""


@pytest.mark.parametrize(
    "url", ["git@github.com:o/r.git", "ssh://git@github.com/o/r.git", "https://gitlab.com/o/r.git"]
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
    assert out[-1].endswith("aborted=0") and "deferred=2" in out[-1]


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
        repo, slug=SLUG, now=FAR, pulls=lambda state: [], issue_states=lambda n: {90: "closed"}
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
    reap(repo, prs=[pr("worker-92-x", "1" * 40, merged=True)], issues={92: "open"}, dry_run=True)
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
        return 1, "To x\n-\t:refs/heads/a\t[deleted]\n!\t:refs/heads/b\t[rejected] (stale info)\n"

    got = readopt._push_delete(run, "u", [("a", "1" * 40), ("b", "2" * 40), ("c", "3" * 40)])
    assert got == {"a": True, "b": False, "c": False}
    assert readopt._push_delete(
        lambda a, t=0: (124, "-\t:refs/heads/a\t"), "u", [("a", "1" * 40)]
    ) == {"a": False}


def test_no_candidates_makes_no_github_calls(repo, capsys):
    git(repo, "branch", "wt-keep", "main")
    git(repo, "checkout", "-q", "wt-keep")

    def forbidden(*_a, **_k):
        raise AssertionError("GitHub must not be called")

    rc = readopt.reap_orphans(
        repo, slug=SLUG, now=time.time(), pulls=forbidden, issue_states=forbidden, dry_run=True
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
        lambda o, r, n: calls["get"].append(n) or ({"state": "closed"} if n != 3 else None),
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
