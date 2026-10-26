"""Tests for scripts/automation/readopt.py (#2126, D-7 / D-8).

Real temp git repositories (with a bare origin) are used for the git-facing
behaviour; the GitHub PR lookup is injected so no test touches the network.
"""

import os
import subprocess
from pathlib import Path

import pytest

from scripts.automation import readopt

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
