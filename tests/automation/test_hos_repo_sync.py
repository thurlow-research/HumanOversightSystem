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

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tests.tmp_hygiene import child_env

BASH = shutil.which("bash") or "/bin/bash"
GIT = shutil.which("git")

SCRIPT = Path(__file__).parent.parent.parent / "bootstrap" / "hos_repo_sync.sh"


def _git(*args, cwd):
    return subprocess.run(
        [GIT, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )


def _run_script(repo_dir, state_dir, interval=None):
    env = dict(os.environ)
    env["HOS_REPO_SYNC_STATE_DIR"] = str(state_dir)
    # The developer's shell must never switch the prune on for the existing tests.
    env.pop("HOS_REPO_SYNC_PRUNE", None)
    env.pop("HOS_TOKEN_APP_ROLE", None)
    args = [BASH, str(SCRIPT)]
    if interval is not None:
        args.append(str(interval))
    return subprocess.run(
        args,
        cwd=repo_dir,
        capture_output=True,
        text=True,
        timeout=30,
        env=child_env(env),
        check=False,
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

        _git("init", "--bare", f"--initial-branch={default_branch}", str(self.origin), cwd=base)

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
        remote = _git("rev-parse", f"origin/{repo.default_branch}", cwd=repo.clone).stdout.strip()
        assert local == remote

        current = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo.clone).stdout.strip()
        assert current == "feature", "must not touch the checked-out branch"

    def test_ff_only_when_default_branch_checked_out_and_clean(self, repo, state_dir):
        repo.advance_remote()

        r = _run_script(repo.clone, state_dir, interval=0)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "fast-forwarded" in (r.stdout + r.stderr)

        local = _git("rev-parse", "HEAD", cwd=repo.clone).stdout.strip()
        remote = _git("rev-parse", f"origin/{repo.default_branch}", cwd=repo.clone).stdout.strip()
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


# ---------------------------------------------------------------------------
# #2288 S3 — local-branch prune (TECHNICAL-DESIGN-2288-S3-repo-sync-prune.md)
#
# The script is copied into <clone>/bootstrap/ (gate P4: it prunes only the
# clone it ships in) and readopt is a stdlib-only STUB: no network, no gh.
# ---------------------------------------------------------------------------

STUB_READOPT = """\
import json, os, sys, time
with open(os.environ["PRUNE_CAPTURE"], "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(),
                         "has_pythonpath": "PYTHONPATH" in os.environ,
                         "has_role": "HOS_TOKEN_APP_ROLE" in os.environ}) + "\\n")
for line in os.environ.get("PRUNE_STUB_OUT", "").splitlines():
    print(line, flush=True)
time.sleep(float(os.environ.get("PRUNE_STUB_SLEEP", "0")))
sys.exit(int(os.environ.get("PRUNE_STUB_RC", "0")))
"""

HAVE_TIMEOUT = bool(shutil.which("timeout") or shutil.which("gtimeout"))


def _install_script(clone):
    dest = clone / "bootstrap"
    dest.mkdir(exist_ok=True)
    shutil.copy(SCRIPT, dest / "hos_repo_sync.sh")
    return dest / "hos_repo_sync.sh"


def _install_stub(clone):
    auto = clone / "scripts" / "automation"
    auto.mkdir(parents=True, exist_ok=True)
    (clone / "scripts" / "__init__.py").write_text("")
    (auto / "__init__.py").write_text("")
    (auto / "readopt.py").write_text(STUB_READOPT)


def _prune_env(tmp, **extra):
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    env = {
        "HOS_REPO_SYNC_PRUNE": "1",
        "HOS_TOKEN_APP_ROLE": "human",
        "HOME": str(home),
        "PRUNE_CAPTURE": str(tmp / "capture.jsonl"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    env.update(extra)
    return {k: v for k, v in env.items() if v is not None}


def _run_prune(clone, state_dir, env_extra, interval=0, script=None, path=None):
    env = dict(os.environ)
    env.pop("HOS_REPO_SYNC_PRUNE", None)
    env.pop("HOS_TOKEN_APP_ROLE", None)
    env.pop("HOS_REPO_SYNC_PRUNE_TIMEOUT_SECS", None)
    env["HOS_REPO_SYNC_STATE_DIR"] = str(state_dir)
    env.update(env_extra)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(
        [BASH, str(script or (clone / "bootstrap" / "hos_repo_sync.sh")), str(interval)],
        cwd=clone,
        capture_output=True,
        text=True,
        timeout=60,
        env=child_env(env),
        check=False,
    )


def _calls(tmp):
    cap = tmp / "capture.jsonl"
    if not cap.exists():
        return []
    return [json.loads(ln) for ln in cap.read_text().splitlines() if ln]


@pytest.fixture
def prune_repo(tmp_path):
    if not GIT:
        pytest.skip("git not available")
    if not HAVE_TIMEOUT:
        pytest.skip("neither timeout nor gtimeout available")
    env = RepoEnv(tmp_path / "repo", default_branch="main")
    _install_script(env.clone)
    _install_stub(env.clone)
    return env


class TestPrune:
    def test_s1_invokes_reaper_with_fixed_argv(self, prune_repo, state_dir):
        r = _run_prune(prune_repo.clone, state_dir, _prune_env(prune_repo.tmp))
        assert r.returncode == 0, r.stdout + r.stderr
        calls = _calls(prune_repo.tmp)
        assert len(calls) == 1
        clone_real = str(prune_repo.clone.resolve())
        assert calls[0]["argv"] == [
            "--repo", clone_real, "reap-orphans", "--local-only", "--grace-days", "1",
            "--max-deletions", "25", "--no-issue-closed",
        ]  # fmt: skip
        assert calls[0]["cwd"] == clone_real
        assert "recover a deleted branch" not in r.stdout  # no REAPED line, no hint

    def test_s2_interval_skip_still_prunes(self, prune_repo, state_dir):
        env = _prune_env(prune_repo.tmp)
        assert _run_prune(prune_repo.clone, state_dir, env, interval=900).returncode == 0
        second = _run_prune(prune_repo.clone, state_dir, env, interval=900)
        assert second.returncode == 0, second.stdout + second.stderr
        assert "skipped, last synced" in second.stdout
        assert len(_calls(prune_repo.tmp)) == 2

    def test_s2b_interval_skip_gate_skip_is_never_silent(self, prune_repo, state_dir):
        env = _prune_env(prune_repo.tmp, HOS_TOKEN_APP_ROLE="worker")
        assert _run_prune(prune_repo.clone, state_dir, env, interval=900).returncode == 0
        second = _run_prune(prune_repo.clone, state_dir, env, interval=900)
        assert second.returncode == 0
        assert "skipped, last synced" in second.stdout
        assert "prune skipped — not the human role" in second.stdout

    def test_s2c_interval_skip_prune_off_is_silent(self, prune_repo, state_dir):
        env = _prune_env(prune_repo.tmp, HOS_REPO_SYNC_PRUNE=None)
        assert _run_prune(prune_repo.clone, state_dir, env, interval=900).returncode == 0
        second = _run_prune(prune_repo.clone, state_dir, env, interval=900)
        assert second.returncode == 0
        assert "skipped, last synced" in second.stdout
        assert "hos-repo-sync: prune" not in second.stdout + second.stderr
        assert _calls(prune_repo.tmp) == []

    def test_s3_fetch_failure_does_not_prune(self, prune_repo, state_dir):
        _git("remote", "set-url", "origin", str(prune_repo.tmp / "nope.git"), cwd=prune_repo.clone)
        r = _run_prune(prune_repo.clone, state_dir, _prune_env(prune_repo.tmp))
        assert r.returncode == 1
        assert "prune skipped — fetch failed" in r.stdout
        assert _calls(prune_repo.tmp) == []

    def test_s3b_fetch_failure_prune_off_is_silent(self, prune_repo, state_dir):
        _git("remote", "set-url", "origin", str(prune_repo.tmp / "nope.git"), cwd=prune_repo.clone)
        r = _run_prune(
            prune_repo.clone, state_dir, _prune_env(prune_repo.tmp, HOS_REPO_SYNC_PRUNE=None)
        )
        assert r.returncode == 1
        assert "hos-repo-sync: prune" not in r.stdout + r.stderr
        assert _calls(prune_repo.tmp) == []

    @pytest.mark.parametrize("flag", [None, "0"])
    def test_s4_off_unless_exactly_one(self, prune_repo, state_dir, flag):
        r = _run_prune(
            prune_repo.clone, state_dir, _prune_env(prune_repo.tmp, HOS_REPO_SYNC_PRUNE=flag)
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "prune" not in r.stdout + r.stderr
        assert _calls(prune_repo.tmp) == []

    @pytest.mark.parametrize("role", ["worker", None])
    def test_s5_requires_human_role(self, prune_repo, state_dir, role):
        r = _run_prune(
            prune_repo.clone, state_dir, _prune_env(prune_repo.tmp, HOS_TOKEN_APP_ROLE=role)
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert "prune skipped — not the human role" in r.stdout
        assert _calls(prune_repo.tmp) == []

    def test_s6_module_absent_skips_once(self, prune_repo, state_dir):
        shutil.rmtree(prune_repo.clone / "scripts")
        r = _run_prune(prune_repo.clone, state_dir, _prune_env(prune_repo.tmp))
        assert r.returncode == 0, r.stdout + r.stderr
        msg = "prune skipped — scripts/automation/readopt.py not present"
        assert r.stdout.count(msg) == 1

    def test_s7_only_prunes_the_scripts_own_clone(self, prune_repo, state_dir):
        # The REAL repo script run with cwd = a different clone: gate P4 must stop it
        # before the real readopt (which always prints SUMMARY) could run.
        r = _run_prune(prune_repo.clone, state_dir, _prune_env(prune_repo.tmp), script=SCRIPT)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "prune skipped — not this script's own clone" in r.stdout
        assert _calls(prune_repo.tmp) == []
        assert "SUMMARY " not in r.stdout + r.stderr

    def test_s8_default_branch_must_be_main(self, tmp_path, state_dir):
        if not GIT:
            pytest.skip("git not available")
        if not HAVE_TIMEOUT:
            pytest.skip("neither timeout nor gtimeout available")
        env = RepoEnv(tmp_path / "repo", default_branch="trunk")
        _install_script(env.clone)
        _install_stub(env.clone)
        r = _run_prune(env.clone, state_dir, _prune_env(env.tmp))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "prune skipped — default branch is not main" in r.stdout
        assert _calls(env.tmp) == []

    @pytest.mark.parametrize("rc", [1, 2, 3])
    def test_s9_reaper_rc_never_changes_sync_exit(self, prune_repo, state_dir, rc):
        r = _run_prune(
            prune_repo.clone, state_dir, _prune_env(prune_repo.tmp, PRUNE_STUB_RC=str(rc))
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"WARN: readopt reap-orphans exited {rc}" in r.stderr
        assert "sync result unaffected" in r.stderr
        assert "(timeout)" not in r.stderr

    def test_s9b_rc_137_is_classified_as_timeout(self, prune_repo, state_dir):
        r = _run_prune(prune_repo.clone, state_dir, _prune_env(prune_repo.tmp, PRUNE_STUB_RC="137"))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "exited 137 (timeout)" in r.stderr

    @pytest.mark.parametrize(
        "secs, expected",
        [(None, "90"), ("abc", "90"), ("0", "90"), ("-5", "90"), ("7", "7")],
    )
    def test_s10b_timeout_seconds_validation(self, prune_repo, state_dir, tmp_path, secs, expected):
        real = shutil.which("timeout") or shutil.which("gtimeout")
        shims = tmp_path / "shims"
        shims.mkdir()
        log = tmp_path / "timeout-argv.log"
        shim = shims / "timeout"
        shim.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexec "{real}" "$@"\n')
        shim.chmod(0o755)
        env = _prune_env(prune_repo.tmp, HOS_REPO_SYNC_PRUNE_TIMEOUT_SECS=secs)
        r = _run_prune(
            prune_repo.clone, state_dir, env, path=f"{shims}{os.pathsep}{os.environ['PATH']}"
        )
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"--kill-after=10 {expected} " in log.read_text()

    def test_s10_timeout_is_bounded_and_keeps_early_output(self, prune_repo, state_dir):
        env = _prune_env(
            prune_repo.tmp,
            PRUNE_STUB_SLEEP="10",
            PRUNE_STUB_OUT="early line",
            HOS_REPO_SYNC_PRUNE_TIMEOUT_SECS="1",
        )
        start = time.monotonic()
        r = _run_prune(prune_repo.clone, state_dir, env)
        assert time.monotonic() - start < 15
        assert r.returncode == 0, r.stdout + r.stderr
        assert "hos-repo-sync: prune: early line" in r.stdout
        assert "(timeout)" in r.stderr

    def test_s11_reaper_output_passes_through_verbatim_in_order(self, prune_repo, state_dir):
        reaped = f"REAPED branch=human/x reason=pr-merged where=local pr=#5 tip={'a' * 40}"
        summary = "SUMMARY reaped_local=1 failed=0"
        r = _run_prune(
            prune_repo.clone,
            state_dir,
            _prune_env(prune_repo.tmp, PRUNE_STUB_OUT=f"{reaped}\n{summary}"),
        )
        lines = r.stdout.splitlines()
        a = lines.index(f"hos-repo-sync: prune: {reaped}")
        assert lines[a + 1] == f"hos-repo-sync: prune: {summary}"
        assert lines[a + 2].startswith(
            "hos-repo-sync: prune: recover a deleted branch with: git branch <name> <tip>"
        )
        assert sum("recover a deleted branch" in ln for ln in lines) == 1

    def test_s12_dirty_behind_tree_still_prunes(self, prune_repo, state_dir):
        prune_repo.advance_remote()
        (prune_repo.clone / "README.md").write_text("dirty\n")
        r = _run_prune(prune_repo.clone, state_dir, _prune_env(prune_repo.tmp))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "STALE" in r.stderr
        assert len(_calls(prune_repo.tmp)) == 1

    def test_s13_no_timeout_binary_skips(self, prune_repo, state_dir, tmp_path):
        bindir = tmp_path / "minbin"
        bindir.mkdir()
        tools = (
            "git python3 sed cksum cut grep mktemp stat id date dirname cat mv mkdir rm "
            "uname sh awk"
        ).split()
        for tool in tools:
            found = shutil.which(tool)
            if found is None:
                pytest.skip(f"cannot build a minimal PATH: {tool} missing")
            (bindir / tool).symlink_to(found)
        r = _run_prune(prune_repo.clone, state_dir, _prune_env(prune_repo.tmp), path=str(bindir))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "prune skipped — no timeout(1) available" in r.stdout
        assert _calls(prune_repo.tmp) == []

    @pytest.mark.parametrize(
        "line_fmt, expect_skip",
        [
            ("x_worker_root={clone}/", True),
            ("x_overseer_root={clone}", True),
            ("x_human_root={clone}", False),
            ("x_worker_root_extra={clone}", False),
            ("x_worker_root=", False),
            ("x_worker_root={clone}\r", True),
            ("x_worker_root={clone}/  ", True),
            ("x_worker_root={other}", False),
        ],
    )
    def test_s14_registered_cron_root_is_never_pruned(
        self, prune_repo, state_dir, line_fmt, expect_skip
    ):
        env = _prune_env(prune_repo.tmp)
        (prune_repo.tmp / "elsewhere").mkdir()  # a dangling root now fails closed (#2299)
        conf = Path(env["HOME"]) / ".config" / "hos" / "projects.conf"
        conf.parent.mkdir(parents=True)
        conf.write_text(
            line_fmt.format(clone=prune_repo.clone, other=prune_repo.tmp / "elsewhere") + "\n"
        )
        r = _run_prune(prune_repo.clone, state_dir, env)
        assert r.returncode == 0, r.stdout + r.stderr
        if expect_skip:
            assert "prune skipped — clone is a registered worker/overseer root" in r.stdout
            assert _calls(prune_repo.tmp) == []
        else:
            assert len(_calls(prune_repo.tmp)) == 1

    def test_h1_child_env_scrubbed_and_python_isolated(self, prune_repo, state_dir, tmp_path):
        real = shutil.which("python3")
        shims = tmp_path / "pyshims"
        shims.mkdir()
        log = tmp_path / "python-argv.log"
        shim = shims / "python3"
        shim.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\nexec "{real}" "$@"\n')
        shim.chmod(0o755)
        env = _prune_env(prune_repo.tmp, PYTHONPATH=str(tmp_path / "evil"))
        r = _run_prune(
            prune_repo.clone, state_dir, env, path=f"{shims}{os.pathsep}{os.environ['PATH']}"
        )
        assert r.returncode == 0, r.stdout + r.stderr
        calls = _calls(prune_repo.tmp)
        assert len(calls) == 1
        assert calls[0]["has_pythonpath"] is False
        assert calls[0]["has_role"] is False
        assert "-E -s -u -m scripts.automation.readopt" in log.read_text()

    def _write_conf(self, env, text):
        conf = Path(env["HOME"]) / ".config" / "hos" / "projects.conf"
        conf.parent.mkdir(parents=True)
        conf.write_text(text)

    def test_h2_quoted_registry_value_fails_closed_naming_key(self, prune_repo, state_dir):
        env = _prune_env(prune_repo.tmp)
        self._write_conf(env, f'x_worker_root="{prune_repo.clone}"\n')
        r = _run_prune(prune_repo.clone, state_dir, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (
            "prune skipped — registry entry x_worker_root does not resolve to a directory"
            in r.stdout
        )
        assert str(prune_repo.clone) not in r.stdout.split("prune skipped")[1]
        assert _calls(prune_repo.tmp) == []

    def test_h3_nonexistent_registry_dir_fails_closed(self, prune_repo, state_dir):
        env = _prune_env(prune_repo.tmp)
        self._write_conf(env, f"y_overseer_root={prune_repo.tmp / 'gone'}\n")
        r = _run_prune(prune_repo.clone, state_dir, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "registry entry y_overseer_root does not resolve to a directory" in r.stdout
        assert _calls(prune_repo.tmp) == []

    def test_h4_existing_nonmatching_root_still_prunes(self, prune_repo, state_dir):
        other = prune_repo.tmp / "elsewhere"
        other.mkdir()
        env = _prune_env(prune_repo.tmp)
        self._write_conf(env, f"x_worker_root={other}\n")
        r = _run_prune(prune_repo.clone, state_dir, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert len(_calls(prune_repo.tmp)) == 1

    def test_h5_matching_root_then_dangling_entry_still_fails_closed(self, prune_repo, state_dir):
        env = _prune_env(prune_repo.tmp)
        self._write_conf(
            env,
            f"x_worker_root={prune_repo.clone}\ny_overseer_root={prune_repo.tmp / 'gone'}\n",
        )
        r = _run_prune(prune_repo.clone, state_dir, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "registry entry y_overseer_root does not resolve to a directory" in r.stdout
        assert _calls(prune_repo.tmp) == []

    def test_h6_dangling_entry_then_existing_nonmatching_root_fails_closed(
        self, prune_repo, state_dir
    ):
        other = prune_repo.tmp / "elsewhere"
        other.mkdir()
        env = _prune_env(prune_repo.tmp)
        self._write_conf(
            env,
            f"y_overseer_root={prune_repo.tmp / 'gone'}\nx_worker_root={other}\n",
        )
        r = _run_prune(prune_repo.clone, state_dir, env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "registry entry y_overseer_root does not resolve to a directory" in r.stdout
        assert _calls(prune_repo.tmp) == []


def _install_audit_lib(clone):
    lib = clone / "scripts" / "oversight" / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    src = SCRIPT.parent.parent / "scripts" / "oversight" / "lib"
    shutil.copy(src / "audit_log.sh", lib / "audit_log.sh")
    shutil.copy(src / "audit_log.py", lib / "audit_log.py")


def _audit_events(clone):
    return [json.loads(f.read_text()) for f in sorted((clone / "audit" / "log").rglob("*.json"))]


class TestPruneAudit:
    TIP = "b" * 40

    def _run(self, prune_repo, state_dir, out):
        return _run_prune(
            prune_repo.clone, state_dir, _prune_env(prune_repo.tmp, PRUNE_STUB_OUT=out)
        )

    def test_a1_reaped_local_writes_one_event(self, prune_repo, state_dir):
        _install_audit_lib(prune_repo.clone)
        line = f"REAPED branch=human/x-1 reason=pr-merged where=local pr=#5 tip={self.TIP}"
        r = self._run(prune_repo, state_dir, line)
        assert r.returncode == 0, r.stdout + r.stderr
        events = _audit_events(prune_repo.clone)
        assert len(events) == 1
        ev = events[0]
        assert ev["event"] == "repo-sync-branch-reap"
        assert ev["actor"] == "human"
        assert (ev["branch"], ev["reason"], ev["where"], ev["pr"], ev["tip"]) == (
            "human/x-1", "pr-merged", "local", "#5", self.TIP,
        )  # fmt: skip

    def test_a2_reap_failed_writes_failed_event(self, prune_repo, state_dir):
        _install_audit_lib(prune_repo.clone)
        line = f"REAP-FAILED branch=human/y reason=landed-ancestor where=local tip={self.TIP}"
        r = self._run(prune_repo, state_dir, line)
        assert r.returncode == 0, r.stdout + r.stderr
        events = _audit_events(prune_repo.clone)
        assert [e["event"] for e in events] == ["repo-sync-branch-reap-failed"]
        assert events[0]["pr"] == "-"

    @pytest.mark.parametrize(
        "line",
        [
            f"REAPED branch=human/x reason=pr-merged where=local pr=#5 tip={'b' * 40} junk",
            f"REAPED branch=human/x reason=pr-merged where=remote pr=#5 tip={'b' * 40}",
            f"  REAPED branch=human/x reason=pr-merged where=local tip={'b' * 40}",
            f"REAPED branch=x;rm reason=pr-merged where=local tip={'b' * 40}",
        ],
    )
    def test_a3_forged_or_remote_line_writes_no_event(self, prune_repo, state_dir, line):
        _install_audit_lib(prune_repo.clone)
        r = self._run(prune_repo, state_dir, line)
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"hos-repo-sync: prune: {line}" in r.stdout
        assert _audit_events(prune_repo.clone) == []

    def test_a4_missing_audit_lib_does_not_change_output_or_exit(self, prune_repo, state_dir):
        line = f"REAPED branch=human/x reason=pr-merged where=local pr=#5 tip={self.TIP}"
        r = self._run(prune_repo, state_dir, line)
        assert r.returncode == 0, r.stdout + r.stderr
        lines = r.stdout.splitlines()
        a = lines.index(f"hos-repo-sync: prune: {line}")
        assert lines[a + 1].startswith("hos-repo-sync: prune: recover a deleted branch")
        assert not (prune_repo.clone / "audit").exists()
