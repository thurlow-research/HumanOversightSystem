"""
Tests for bootstrap/hos_repo_sync.sh — periodic fetch + fast-forward helper
for interactive sessions (see the script's own header for rationale: origin
can move via autonomous worker/overseer cron with no signal reaching an
interactive session otherwise).

Strategy
--------
Run the real script via subprocess against real local git repos (a bare
"origin" plus one or more working clones) under tmp_path — git itself is the
only dependency and is always present, so no stubs are needed. The default
branch is deliberately named "trunk" (not "main") in most tests to prove
branch detection reads origin/HEAD rather than assuming a name.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
GIT = shutil.which("git")

SCRIPT = Path(__file__).parent.parent.parent / "bootstrap" / "hos_repo_sync.sh"


def _git(*args, cwd):
    return subprocess.run(
        [GIT, *args], cwd=cwd, capture_output=True, text=True,
        check=True, timeout=30,
    )


def _run_script(repo_dir, state_dir, interval=None):
    env = dict(os.environ)
    env["HOS_REPO_SYNC_STATE_DIR"] = str(state_dir)
    args = [BASH, str(SCRIPT)]
    if interval is not None:
        args.append(str(interval))
    return subprocess.run(
        args, cwd=repo_dir, capture_output=True, text=True,
        timeout=30, env=env, check=False,
    )


class RepoEnv:
    """A bare 'origin' repo plus a working clone and a separate 'pusher'
    clone used to advance the remote independently of the clone under test."""

    def __init__(self, base, default_branch="trunk"):
        base.mkdir(parents=True, exist_ok=True)
        self.tmp = base
        self.default_branch = default_branch
        self.origin = base / "origin.git"
        self.clone = base / "clone"
        self.pusher = base / "pusher"

        _git("init", "--bare", f"--initial-branch={default_branch}",
             str(self.origin), cwd=base)

        seed = base / "seed"
        _git("clone", str(self.origin), str(seed), cwd=base)
        self._configure_identity(seed)
        (seed / "README.md").write_text("seed\n")
        _git("add", "README.md", cwd=seed)
        _git("commit", "-m", "initial", cwd=seed)
        _git("push", "origin", default_branch, cwd=seed)

        _git("clone", str(self.origin), str(self.clone), cwd=base)
        self._configure_identity(self.clone)

        _git("clone", str(self.origin), str(self.pusher), cwd=base)
        self._configure_identity(self.pusher)

    @staticmethod
    def _configure_identity(repo_dir):
        _git("config", "user.email", "test@example.com", cwd=repo_dir)
        _git("config", "user.name", "Test", cwd=repo_dir)

    def advance_remote(self, filename="extra.txt", content="more\n"):
        (self.pusher / filename).write_text(content)
        _git("add", filename, cwd=self.pusher)
        _git("commit", "-m", "advance", cwd=self.pusher)
        _git("push", "origin", self.default_branch, cwd=self.pusher)


@pytest.fixture
def repo(tmp_path):
    if not GIT:
        pytest.skip("git not available")
    return RepoEnv(tmp_path / "repo")


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    return d


class TestSkipInterval:
    def test_skips_when_recently_synced(self, repo, state_dir):
        first = _run_script(repo.clone, state_dir, interval=900)
        assert first.returncode == 0, first.stdout + first.stderr

        second = _run_script(repo.clone, state_dir, interval=900)
        assert "skipped" in (second.stdout + second.stderr)

    def test_runs_when_interval_is_zero(self, repo, state_dir):
        r = _run_script(repo.clone, state_dir, interval=0)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "skipped" not in (r.stdout + r.stderr)

    def test_not_a_git_repo_is_a_noop_not_an_error(self, tmp_path, state_dir):
        plain_dir = tmp_path / "not_a_repo"
        plain_dir.mkdir()
        r = _run_script(plain_dir, state_dir, interval=0)
        assert r.returncode == 0
        assert "not inside a git repository" in (r.stdout + r.stderr)


class TestFastForward:
    def test_fast_forwards_local_ref_when_not_checked_out(self, repo, state_dir):
        _git("checkout", "-b", "feature", cwd=repo.clone)
        repo.advance_remote()

        r = _run_script(repo.clone, state_dir, interval=0)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "fast-forwarded" in (r.stdout + r.stderr)

        local = _git("rev-parse", repo.default_branch, cwd=repo.clone).stdout.strip()
        remote = _git("rev-parse", f"origin/{repo.default_branch}",
                       cwd=repo.clone).stdout.strip()
        assert local == remote

        current = _git("rev-parse", "--abbrev-ref", "HEAD",
                        cwd=repo.clone).stdout.strip()
        assert current == "feature", "must not touch the checked-out branch"

    def test_ff_only_when_default_branch_checked_out_and_clean(self, repo, state_dir):
        repo.advance_remote()

        r = _run_script(repo.clone, state_dir, interval=0)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "fast-forwarded" in (r.stdout + r.stderr)

        local = _git("rev-parse", "HEAD", cwd=repo.clone).stdout.strip()
        remote = _git("rev-parse", f"origin/{repo.default_branch}",
                       cwd=repo.clone).stdout.strip()
        assert local == remote

    def test_skips_fast_forward_when_working_tree_dirty(self, repo, state_dir):
        repo.advance_remote()
        (repo.clone / "README.md").write_text("dirty local edit\n")
        before = _git("rev-parse", "HEAD", cwd=repo.clone).stdout.strip()

        r = _run_script(repo.clone, state_dir, interval=0)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "dirty" in (r.stdout + r.stderr)

        after = _git("rev-parse", "HEAD", cwd=repo.clone).stdout.strip()
        assert after == before, "must never touch a dirty working tree"

    def test_reports_up_to_date_as_a_noop(self, repo, state_dir):
        r = _run_script(repo.clone, state_dir, interval=0)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "up to date" in (r.stdout + r.stderr)


class TestStaleReportingOnSyncFailure:
    """#1200 — a session must always be able to tell it may be working
    against superseded code, and a structural (never-going-to-resolve)
    failure must be reported distinctly from a benign/transient one."""

    def test_diverged_branch_reported_as_stale_and_transient(self, repo, state_dir):
        # Default branch checked out, clean, but locally ahead so
        # pull --ff-only fails and diverged — fills the gap the previous
        # TODO in TestFastForward used to note, and verifies the benign
        # classification (#1200).
        (repo.clone / "local.txt").write_text("local change\n")
        _git("add", "local.txt", cwd=repo.clone)
        _git("commit", "-m", "local diverge", cwd=repo.clone)
        repo.advance_remote()

        r = _run_script(repo.clone, state_dir, interval=0)
        combined = r.stdout + r.stderr
        assert r.returncode == 0, combined
        assert "diverged" in combined
        assert "STALE" in combined
        assert "transient cause" in combined
        assert "STRUCTURAL" not in combined

    def test_dirty_tree_reported_as_stale_and_transient(self, repo, state_dir):
        repo.advance_remote()
        (repo.clone / "README.md").write_text("dirty local edit\n")

        r = _run_script(repo.clone, state_dir, interval=0)
        combined = r.stdout + r.stderr
        assert r.returncode == 0, combined
        assert "STALE" in combined
        assert "transient cause" in combined
        assert "STRUCTURAL" not in combined

    def test_readonly_working_tree_reported_as_stale_and_structural(self, repo, state_dir):
        repo.advance_remote()
        os.chmod(repo.clone, 0o555)
        try:
            r = _run_script(repo.clone, state_dir, interval=0)
        finally:
            os.chmod(repo.clone, 0o755)

        combined = r.stdout + r.stderr
        assert r.returncode == 0, combined
        assert "STALE" in combined
        assert "STRUCTURAL" in combined
        assert "#1183" in combined

    def test_up_to_date_emits_no_stale_warning(self, repo, state_dir):
        r = _run_script(repo.clone, state_dir, interval=0)
        combined = r.stdout + r.stderr
        assert "STALE" not in combined

    def test_successful_fast_forward_emits_no_stale_warning(self, repo, state_dir):
        repo.advance_remote()
        r = _run_script(repo.clone, state_dir, interval=0)
        combined = r.stdout + r.stderr
        assert "STALE" not in combined


class TestFetchFailure:
    def test_fetch_failure_is_reported_and_classified_transient(self, repo, state_dir):
        _git("remote", "set-url", "origin", str(repo.tmp / "does-not-exist.git"), cwd=repo.clone)

        r = _run_script(repo.clone, state_dir, interval=0)
        combined = r.stdout + r.stderr
        assert r.returncode == 1
        assert "git fetch failed" in combined
        assert "transient cause" in combined
        assert "STRUCTURAL" not in combined


class TestPerRepoStateIsolation:
    def test_two_repos_get_independent_state_files(self, tmp_path):
        if not GIT:
            pytest.skip("git not available")
        repo_a = RepoEnv(tmp_path / "a")
        repo_b = RepoEnv(tmp_path / "b")
        shared_state = tmp_path / "shared_state"
        shared_state.mkdir()

        ra = _run_script(repo_a.clone, shared_state, interval=900)
        rb = _run_script(repo_b.clone, shared_state, interval=900)
        assert ra.returncode == 0, ra.stdout + ra.stderr
        assert rb.returncode == 0, rb.stdout + rb.stderr

        state_files = list(shared_state.glob("*.json"))
        assert len(state_files) == 2, "each repo must get its own state file"
