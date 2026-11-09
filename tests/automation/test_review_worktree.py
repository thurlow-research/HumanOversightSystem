"""Tests for bootstrap/review_worktree.sh (#2287, TD-2287 section 2, tests C1-C10).

Real temp git repositories with a bare origin that carries refs/pull/<N>/head.
Scratch worktrees live under a per-test TMPDIR inside pytest's tmp_path, so
tests/conftest.py's zero-leak check sees nothing left behind.
"""

import os
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "bootstrap" / "review_worktree.sh"
IDENT = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *IDENT, *args], capture_output=True, text=True, check=check
    ).stdout.strip()


class Env:
    def __init__(self, tmp_path):
        self.origin = tmp_path / "origin.git"
        self.work = tmp_path / "work"
        self.scratch = tmp_path / "scratch"
        self.scratch.mkdir()
        subprocess.run(["git", "init", "-q", "--bare", str(self.origin)], check=True)
        self.work.mkdir()
        git(self.work, "init", "-q")
        git(self.work, "symbolic-ref", "HEAD", "refs/heads/main")
        (self.work / "a.txt").write_text("a\n")
        git(self.work, "add", "a.txt")
        git(self.work, "commit", "-q", "-m", "init")
        git(self.work, "remote", "add", "origin", str(self.origin))
        git(self.work, "push", "-q", "origin", "main")
        git(self.work, "fetch", "-q", "origin")
        self.sha = {n: self.pull(n) for n in (7, 8)}

    def pull(self, n):
        git(self.work, "checkout", "-q", "-b", f"src{n}", "main")
        (self.work / f"f{n}.txt").write_text(f"{n}\n")
        git(self.work, "add", f"f{n}.txt")
        git(self.work, "commit", "-q", "-m", f"pr {n}")
        sha = git(self.work, "rev-parse", "HEAD")
        git(self.work, "push", "-q", "origin", f"{sha}:refs/pull/{n}/head")
        git(self.work, "checkout", "-q", "main")
        git(self.work, "branch", "-q", "-D", f"src{n}")
        return sha

    def run(self, *args, cwd=None, tmpdir=None):
        env = {**os.environ, "TMPDIR": str(tmpdir or self.scratch)}
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=str(cwd or self.work),
            env=env,
            capture_output=True,
            text=True,
        )

    def checkout(self, n, **kw):
        return self.run("--pr", str(n), "--expect-sha", self.sha[n], **kw)

    def refs(self):
        return git(self.work, "for-each-ref", "--format=%(refname) %(objectname)")

    def heads(self):
        return git(self.work, "for-each-ref", "refs/heads/")

    def worktrees(self):
        return [
            ln[len("worktree ") :]
            for ln in git(self.work, "worktree", "list", "--porcelain").splitlines()
            if ln.startswith("worktree ")
        ]


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def wt_of(proc):
    return Path(proc.stdout.splitlines()[0].removeprefix("WORKTREE="))


def test_c1_review_creates_no_branch_and_no_ref(env):
    heads, refs = env.heads(), env.refs()
    p = env.checkout(7)
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    assert len(lines) == 2 and lines[1] == f"HEAD={env.sha[7]}"
    wt = wt_of(p)
    assert env.scratch in wt.parents
    assert git(wt, "rev-parse", "HEAD") == env.sha[7]
    assert git(wt, "symbolic-ref", "-q", "HEAD", check=False) == ""  # detached
    assert env.heads() == heads and env.refs() == refs


def test_c2_cleanup_removes_worktree_and_scratch(env):
    heads = env.heads()
    wt = wt_of(env.checkout(7))
    p = env.run("--cleanup", "--pr", "7")
    assert p.returncode == 0
    assert f"REMOVED-WORKTREE pr=7 path={wt}" in p.stdout
    assert not wt.exists() and not wt.parent.exists()
    assert env.worktrees() == [str(env.work)]
    assert env.heads() == heads


def test_c3_wrong_expect_sha_exits_4_and_creates_nothing(env):
    p = env.run("--pr", "7", "--expect-sha", "0" * 40)
    assert p.returncode == 4 and "head-moved" in p.stderr
    assert list(env.scratch.iterdir()) == [] and env.worktrees() == [str(env.work)]


@pytest.mark.parametrize(
    "args",
    [
        ["--pr", "0", "--expect-sha", "a" * 40],
        ["--pr", "-1", "--expect-sha", "a" * 40],
        ["--pr", "7;x", "--expect-sha", "a" * 40],
        ["--pr", "7"],
        ["--pr", "7", "--expect-sha", "abc123"],
        ["--pr", "7", "--expect-sha", "A" * 40],
    ],
)
def test_c4_bad_arguments_exit_2(env, args):
    assert env.run(*args).returncode == 2
    assert list(env.scratch.iterdir()) == []


def test_c5_running_twice_leaves_one_worktree(env):
    first = wt_of(env.checkout(7))
    second = wt_of(env.checkout(7))
    assert not first.exists()
    reviews = [w for w in env.worktrees() if "hos-review-pr7." in w]
    assert reviews == [str(second)]


def test_c6_cleanup_all_touches_only_review_worktrees(env, tmp_path):
    git(env.work, "worktree", "add", "-q", "-b", "holder", str(tmp_path / "held"))
    git(env.work, "worktree", "add", "-q", "--detach", str(tmp_path / "loose"), "main")
    w7, w8 = wt_of(env.checkout(7)), wt_of(env.checkout(8))
    p = env.run("--cleanup-all")
    assert p.returncode == 0
    assert not w7.exists() and not w8.exists()
    assert (tmp_path / "held").is_dir() and (tmp_path / "loose").is_dir()
    assert {str(tmp_path / "held"), str(tmp_path / "loose"), str(env.work)} == set(env.worktrees())


def test_c7_older_than_mins_skips_fresh(env):
    fresh, old = wt_of(env.checkout(7)), wt_of(env.checkout(8))
    back = time.time() - 7200
    os.utime(old.parent, (back, back))
    p = env.run("--cleanup-all", "--older-than-mins", "60")
    assert p.returncode == 0
    assert fresh.exists() and not old.exists()


def test_c8_commit_guard_keeps_a_worktree_whose_head_moved(env):
    wt = wt_of(env.checkout(7))
    git(wt, "commit", "-q", "--allow-empty", "-m", "oops")
    moved = git(wt, "rev-parse", "HEAD")
    for args in (["--cleanup", "--pr", "7"], ["--cleanup-all"]):
        p = env.run(*args)
        assert p.returncode == 0
        assert f"KEPT-WORKTREE pr=7 path={wt} reason=head-moved" in p.stderr
        assert "REMOVED-WORKTREE" not in p.stdout
        assert wt.exists() and git(wt, "rev-parse", "HEAD") == moved


def test_c8_missing_marker_keeps_worktree(env):
    wt = wt_of(env.checkout(7))
    (wt.parent / "expected-head").unlink()
    p = env.run("--cleanup", "--pr", "7")
    assert "reason=head-moved" in p.stderr and wt.exists()


def test_c9_scratch_inside_repo_is_refused(env):
    heads = env.heads()
    inside = env.work / ".claudetmp" / "x"
    p = env.checkout(7, tmpdir=inside)
    assert p.returncode == 5 and "TMPDIR" in p.stderr
    assert not inside.exists() and env.heads() == heads


def test_c9_scratch_under_tmp_claude_is_refused(env):
    fake = Path("/tmp/claude/hos-test-review-worktree-does-not-exist")
    p = env.checkout(7, tmpdir=fake)
    assert p.returncode == 5
    assert not fake.exists() and env.worktrees() == [str(env.work)]


def test_c10_runs_against_main_worktree_from_inside_a_review_worktree(env):
    w7 = wt_of(env.checkout(7))
    p = env.checkout(8, cwd=w7)
    assert p.returncode == 0, p.stderr
    w8 = wt_of(p)
    assert env.scratch in w8.parents and w7 not in w8.parents
    assert {str(w7), str(w8)} <= set(env.worktrees())


def test_c10_configured_pull_refspec_creates_no_remote_ref(env):
    git(
        env.work,
        "config",
        "--add",
        "remote.origin.fetch",
        "+refs/pull/*/head:refs/remotes/origin/pr/*",
    )
    before = env.refs()
    p = env.checkout(7)
    assert p.returncode == 0, p.stderr
    assert env.refs() == before


def test_c11_fetch_timeout_maps_to_exit_3_with_distinct_reason(env, tmp_path):
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "timeout").write_text("#!/bin/sh\nexit 124\n")
    (fake / "timeout").chmod(0o755)
    p = subprocess.run(
        ["bash", str(SCRIPT), "--pr", "7", "--expect-sha", env.sha[7]],
        cwd=str(env.work),
        env={**os.environ, "TMPDIR": str(env.scratch), "PATH": f"{fake}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert p.returncode == 3
    assert "fetch of refs/pull/7/head timed out" in p.stderr
    assert list(env.scratch.iterdir()) == []


def test_c12_fetch_failure_prints_one_redacted_truncated_line(env):
    token = "ghp_" + "A1b2C3d4" * 4
    git(env.work, "remote", "set-url", "origin", f"/nonexistent/{token}/x/" + "y" * 400)
    p = env.checkout(7)
    assert p.returncode == 3
    assert "fetch of refs/pull/7/head failed: " in p.stderr
    assert token not in p.stderr and "***" in p.stderr
    assert len(p.stderr.strip().splitlines()) == 1
    assert len(p.stderr) < 400


def test_c12_userinfo_url_is_redacted(env):
    url = "https://user:s3cretpw@127.0.0.1:1/x.git"  # pragma: allowlist secret
    git(env.work, "remote", "set-url", "origin", url)
    p = env.checkout(7)
    assert p.returncode == 3
    assert "s3cretpw" not in p.stderr and "user:" not in p.stderr


def test_c13_post_checkout_hook_does_not_run_on_worktree_add(env, tmp_path):
    marker = tmp_path / "hook-ran"
    hook = env.work / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    p = env.checkout(7)
    assert p.returncode == 0, p.stderr
    assert not marker.exists()
