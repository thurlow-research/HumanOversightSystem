"""
Tests for bin/hos-cron — the parameterized HOS cron launcher.

`bin/hos-cron` was hardened reactively all through the v0.4.1 cron bring-up
(arg validation, registry resolution, thin-env, overlap lock, idle backoff,
auth bootstrap #728, identity guard, deterministic git credentials #738) with
every fix verified by hand and none captured as a test (#743). This suite
codifies those manual checks so the launcher can't silently regress.

Strategy
--------
The launcher is one top-to-bottom `set -euo pipefail` pipeline, so each behavior
is reached by *running the real script* and arranging where it exits. The
`cron_env` fixture builds a throwaway HOME + repo with a full set of stubs that
make the happy path succeed end-to-end:

  * a `claude` stub on the pinned PATH (HOME/.local/bin) that records its argv[0]
    and environment instead of spawning the real CLI — the pinned-PATH/absolute
    resolution is itself under test, so claude is NEVER really invoked;
  * a `gh` stub so the #738 git-credential helper resolves;
  * `bootstrap/validate_setup.sh`, `bootstrap/get_app_token.sh` and
    `scripts/framework/run_tests_inner_loop.sh` stubs in a fake repo root;
  * `projects.conf` + `claude-auth.env` (#728) under the fake HOME.

Individual tests then perturb exactly one input to drive a single branch.
`HOS_CRON_JITTER_MAX=0` disables the startup jitter so nothing waits 0–60s
(mirrors machine_lock.sh's `HOS_LOCK_JITTER_MAX`).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"

HOS_CRON = Path(__file__).parent.parent.parent / "bin" / "hos-cron"

EXPECTED_BOT = "hos-worker-hos[bot]"


def _write_exec(path: Path, body: str) -> None:
    """Write an executable stub script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


class CronEnv:
    """A fully stubbed environment for invoking bin/hos-cron deterministically."""

    def __init__(self, tmp_path: Path):
        self.home = tmp_path / "home"
        self.repo = tmp_path / "repo"
        self.state = tmp_path / "state"
        self.bindir = self.home / ".local" / "bin"
        self.claude_log = tmp_path / "claude_invocation.log"
        self.token_capture = tmp_path / "lock_pid_seen.log"
        self.ppid_capture = tmp_path / "ppid_seen.log"

        # ── claude stub: records how it was invoked, never spawns the real CLI ──
        # $0 proves thin-env resolved it by absolute path off the pinned PATH;
        # the recorded env proves ANTHROPIC_API_KEY was unset and the OAuth token
        # is present. Exit code is overridable to exercise the non-zero path.
        _write_exec(
            self.bindir / "claude",
            "#!/usr/bin/env bash\n"
            'cat > /dev/null 2>&1 || true   # drain stdin (prompt pipe)\n'
            "{\n"
            '  echo "argv0=$0"\n'
            '  echo "api_key=${ANTHROPIC_API_KEY:-UNSET}"\n'
            '  echo "auth_token=${ANTHROPIC_AUTH_TOKEN:-UNSET}"\n'
            '  echo "oauth=${CLAUDE_CODE_OAUTH_TOKEN:-UNSET}"\n'
            '  echo "path=$PATH"\n'
            f'}} > "{self.claude_log}"\n'
            'exit "${HOS_TEST_CLAUDE_EXIT:-0}"\n',
        )

        # gh stub — only needs to be found by `command -v gh` (#738 helper string
        # is never actually invoked without a real push).
        _write_exec(self.bindir / "gh", "#!/usr/bin/env bash\nexit 0\n")

        # ── fake repo with the launcher's downstream dependencies stubbed ──
        _write_exec(
            self.repo / "bootstrap" / "validate_setup.sh",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        # get_app_token's stdout is SOURCED by the launcher — emit the identity
        # exports the identity guard checks. It runs as a direct child of the
        # launcher, so $PPID == the launcher's $$ == the lock pid it just wrote;
        # recording both lets a test prove "pid written" without racing the trap.
        _write_exec(
            self.repo / "bootstrap" / "get_app_token.sh",
            "#!/usr/bin/env bash\n"
            f'cat "$HOS_STATE_DIR/locks/hos-cron-worker-hos.lock/pid" > "{self.token_capture}" 2>/dev/null || true\n'
            f'echo "$PPID" > "{self.ppid_capture}"\n'
            # `-` (not `:-`) so a test can deliver an explicitly-empty value to
            # exercise the fail-closed unset/empty guard.
            "echo \"export HOS_BOT_LOGIN='${HOS_TEST_BOT_LOGIN-" + EXPECTED_BOT + "}'\"\n"
            "echo \"export HOS_EXPECTED_BOT_LOGIN='${HOS_TEST_EXPECTED_BOT-" + EXPECTED_BOT + "}'\"\n"
            'echo "export GH_TOKEN=fake-token"\n',
        )
        _write_exec(
            self.repo / "scripts" / "framework" / "run_tests_inner_loop.sh",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        # ensure_venv.sh stub: exit 0 by default (healthy venv); override with
        # HOS_TEST_ENSURE_VENV_EXIT to simulate a broken venv.
        _write_exec(
            self.repo / "scripts" / "oversight" / "ensure_venv.sh",
            "#!/usr/bin/env bash\n"
            'exit "${HOS_TEST_ENSURE_VENV_EXIT:-0}"\n',
        )

        # ── HOME config: project registry + claude OAuth (#728) ──
        conf = self.home / ".config" / "hos" / "projects.conf"
        conf.parent.mkdir(parents=True, exist_ok=True)
        conf.write_text(
            f"hos_config_dir={self.home}/.config/hos\n"
            f"hos_worker_root={self.repo}\n"
            f"hos_overseer_root={self.repo}\n"
        )
        self.auth_env = self.home / ".config" / "hos" / "claude-auth.env"
        self.auth_env.write_text("CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-TESTTOKEN\n")
        self.auth_env.chmod(0o600)

    @property
    def lock_dir(self) -> Path:
        return self.state / "locks" / "hos-cron-worker-hos.lock"

    @property
    def last_run_file(self) -> Path:
        return self.state / "last-run" / "worker-hos"

    @property
    def wakeup_worker(self) -> Path:
        return self.state / "wakeup" / "worker"

    @property
    def wakeup_overseer(self) -> Path:
        return self.state / "wakeup" / "overseer"

    def run(self, *args, env_overrides=None, role="worker", project="hos",
            timeout=30) -> subprocess.CompletedProcess:
        """Invoke the real bin/hos-cron with the stubbed world."""
        env = {
            "HOME": str(self.home),
            # Minimal incoming PATH — the launcher pins its own on top. The claude
            # stub lives in $HOME/.local/bin, which the launcher prepends first.
            "PATH": "/usr/bin:/bin",
            "HOS_STATE_DIR": str(self.state),
            "HOS_CRON_JITTER_MAX": "0",      # deterministic: no 0–60s sleep
            "HOS_CRON_MAX_SECONDS": "0",     # don't wrap claude stub in `timeout`
            "HOS_IDLE_INTERVAL": "1800",
            "HOS_TEST_CLAUDE_LOG": str(self.claude_log),
        }
        if env_overrides:
            env.update(env_overrides)
        argv = [BASH, str(HOS_CRON)]
        if args:
            argv += list(args)
        else:
            argv += ["--role", role, "--project", project]
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            check=False, env=env,
        )

    def claude_ran(self) -> bool:
        return self.claude_log.exists()

    def claude_record(self) -> str:
        return self.claude_log.read_text() if self.claude_log.exists() else ""


@pytest.fixture
def cron(tmp_path):
    return CronEnv(tmp_path)


# ───────────────────────────── Arg validation ──────────────────────────────
class TestArgValidation:
    def test_missing_role_and_project_errors(self, cron):
        r = cron.run("--role", "")  # both end up empty
        assert r.returncode == 1
        assert "required" in (r.stdout + r.stderr)

    def test_no_args_errors(self, cron):
        # Pass an explicit empty role so argv isn't auto-filled by run().
        r = cron.run("--project", "hos")  # role missing
        assert r.returncode == 1
        assert "required" in (r.stdout + r.stderr)

    def test_invalid_role_rejected(self, cron):
        r = cron.run("--role", "wizard", "--project", "hos")
        assert r.returncode == 1
        assert "must be worker or overseer" in (r.stdout + r.stderr)

    def test_unknown_flag_shows_usage(self, cron):
        r = cron.run("--frobnicate", "x")
        assert r.returncode == 1
        assert "Usage:" in (r.stdout + r.stderr)


# ──────────────────────────── Registry resolution ──────────────────────────
class TestRegistryResolution:
    def test_unknown_project_errors(self, cron):
        r = cron.run("--role", "worker", "--project", "ghost")
        assert r.returncode == 1
        assert "no ghost_config_dir" in (r.stdout + r.stderr)

    def test_missing_role_root_errors(self, cron):
        # config_dir present but worker_root absent → distinct error.
        conf = cron.home / ".config" / "hos" / "projects.conf"
        conf.write_text(f"hos_config_dir={cron.home}/.config/hos\n")
        r = cron.run()
        assert r.returncode == 1
        assert "no hos_worker_root" in (r.stdout + r.stderr)

    def test_resolved_project_proceeds_past_registry(self, cron):
        # A fully resolvable project runs the whole happy path (claude stub fires).
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no hos_config_dir" not in r.stdout
        assert cron.claude_ran()


# ────────────────────────────── Overlap lock ───────────────────────────────
class TestOverlapLock:
    def test_live_holder_makes_second_invocation_exit_zero(self, cron):
        # Pre-seed the lock with a *live* pid (this test process) → held.
        cron.lock_dir.mkdir(parents=True)
        (cron.lock_dir / "pid").write_text(f"{os.getpid()}\n")
        r = cron.run()
        assert r.returncode == 0
        assert "holds the lock" in r.stdout
        assert not cron.claude_ran(), "must not run work while another holder is live"

    def test_stale_dead_pid_lock_is_reclaimed(self, cron):
        cron.lock_dir.mkdir(parents=True)
        (cron.lock_dir / "pid").write_text("99999999\n")  # never-alive pid
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "reclaiming stale lock" in r.stdout
        assert cron.claude_ran(), "after reclaim the cycle should proceed"

    def test_pid_written_is_the_launcher_pid(self, cron):
        # Seed a stale lock, then confirm the launcher overwrote the pid file with
        # its own pid. get_app_token (a direct child) snapshots both the pid file
        # and its own $PPID mid-run, before the EXIT trap removes the lock dir.
        cron.lock_dir.mkdir(parents=True)
        (cron.lock_dir / "pid").write_text("99999999\n")
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        seen_lock_pid = cron.token_capture.read_text().strip()
        launcher_pid = cron.ppid_capture.read_text().strip()
        assert seen_lock_pid.isdigit()
        assert seen_lock_pid != "99999999", "stale pid should have been overwritten"
        assert seen_lock_pid == launcher_pid, "lock pid must be the launcher's own pid"


# ──────────────────────────── Wakeup / idle backoff ────────────────────────
class TestWakeupBackoff:
    def test_wakeup_file_is_consumed_and_cycle_runs(self, cron):
        cron.wakeup_worker.parent.mkdir(parents=True, exist_ok=True)
        cron.wakeup_worker.write_text('{"reason":"overseer-signal"}')
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "wakeup signal received" in r.stdout
        assert "reason=overseer-signal" in r.stdout
        assert not cron.wakeup_worker.exists(), "wakeup file must be consumed"
        assert cron.claude_ran()

    def test_recent_last_run_triggers_idle_backoff(self, cron):
        # last-run = now, no wakeup → within IDLE_INTERVAL → skip with exit 0.
        cron.last_run_file.parent.mkdir(parents=True, exist_ok=True)
        now = int(subprocess.run(["date", "+%s"], capture_output=True, text=True).stdout)
        cron.last_run_file.write_text(str(now))
        r = cron.run()
        assert r.returncode == 0
        assert "idle backoff" in r.stdout
        assert not cron.claude_ran(), "backoff must skip the cycle entirely"

    def test_stale_last_run_polls_and_runs(self, cron):
        cron.last_run_file.parent.mkdir(parents=True, exist_ok=True)
        now = int(subprocess.run(["date", "+%s"], capture_output=True, text=True).stdout)
        cron.last_run_file.write_text(str(now - 100_000))  # far past the threshold
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "idle poll" in r.stdout
        assert cron.claude_ran()


# ───────────────────────────── Auth bootstrap (#728) ───────────────────────
class TestClaudeAuthBootstrap:
    def test_missing_claude_auth_env_is_ex_config(self, cron):
        cron.auth_env.unlink()
        r = cron.run()
        assert r.returncode == 78, "missing claude-auth.env must exit EX_CONFIG (78)"
        assert "missing" in r.stdout
        assert not cron.claude_ran()

    def test_empty_oauth_token_is_ex_config(self, cron):
        cron.auth_env.write_text("CLAUDE_CODE_OAUTH_TOKEN=\n")
        r = cron.run()
        assert r.returncode == 78
        assert "CLAUDE_CODE_OAUTH_TOKEN not set" in r.stdout
        assert not cron.claude_ran()

    def test_api_key_unset_before_claude_invoke(self, cron):
        # A shadowing ANTHROPIC_API_KEY in the environment must be cleared so the
        # OAuth subscription token wins (#728).
        r = cron.run(env_overrides={"ANTHROPIC_API_KEY": "sk-shadow-should-be-cleared"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.claude_ran()
        assert "api_key=UNSET" in cron.claude_record()
        assert "auth_token=UNSET" in cron.claude_record()
        assert "oauth=sk-ant-oat01-TESTTOKEN" in cron.claude_record()


# ───────────────────────────── Identity guard ──────────────────────────────
class TestIdentityGuard:
    def test_login_mismatch_exits_one(self, cron):
        r = cron.run(env_overrides={"HOS_TEST_BOT_LOGIN": "imposter[bot]"})
        assert r.returncode == 1
        assert "IDENTITY GUARD FAILED" in r.stdout
        assert not cron.claude_ran()

    def test_expected_login_unset_exits_one(self, cron):
        # get_app_token emits an empty HOS_EXPECTED_BOT_LOGIN → guard fails closed.
        r = cron.run(env_overrides={"HOS_TEST_EXPECTED_BOT": ""})
        assert r.returncode == 1
        assert "IDENTITY GUARD FAILED" in r.stdout
        assert not cron.claude_ran()

    def test_matching_login_proceeds(self, cron):
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"Authenticated as {EXPECTED_BOT}" in r.stdout
        assert cron.claude_ran()


# ───────────────────────────── Thin-env hardening ──────────────────────────
class TestThinEnv:
    def test_claude_resolved_by_absolute_path_from_minimal_path(self, cron):
        # Incoming PATH is just /usr/bin:/bin (no claude). The launcher pins its
        # own PATH and resolves the stub in $HOME/.local/bin by absolute path.
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        argv0 = next(
            (l for l in cron.claude_record().splitlines() if l.startswith("argv0=")),
            "",
        )
        assert argv0 == f"argv0={cron.bindir}/claude", (
            "claude must be invoked by its absolute pinned-PATH location"
        )

    def test_pinned_path_includes_standard_bins(self, cron):
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        path_line = next(
            (l for l in cron.claude_record().splitlines() if l.startswith("path=")),
            "",
        )
        # The launcher prepends the pinned dirs regardless of the sparse inbound PATH.
        assert f"{cron.bindir}" in path_line
        assert "/usr/bin" in path_line


# ──────────── last-run written only on exit 0 + wakeup hand-off ─────────────
class TestPostCycleBookkeeping:
    def test_last_run_written_on_success(self, cron):
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.last_run_file.exists(), "successful cycle must stamp last-run"
        assert cron.last_run_file.read_text().strip().isdigit()

    def test_last_run_not_written_when_claude_fails(self, cron):
        r = cron.run(env_overrides={"HOS_TEST_CLAUDE_EXIT": "7"})
        # The launcher itself still exits 0 (it logs the claude failure); the
        # contract is that last-run is NOT stamped, so the next fire retries.
        assert "claude exited 7" in r.stdout
        assert not cron.last_run_file.exists(), (
            "last-run must NOT be written when the claude session fails (#711)"
        )

    def test_wakeup_dropped_to_overseer(self, cron):
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.wakeup_overseer.exists(), "worker must signal the overseer"
        payload = cron.wakeup_overseer.read_text()
        assert "worker-cycle-complete" in payload
        assert '"project":"hos"' in payload


# ──────────────────────────── _validate_env ─────────────────────────────────
class TestValidateEnv:
    def test_bootstrap_marker_absent_warns(self, cron):
        """Missing bootstrap marker → warning in output."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "bootstrap marker missing" in r.stdout

    def test_bootstrap_marker_present_no_warn(self, cron):
        """Bootstrap marker present → no bootstrap warning."""
        marker_dir = cron.home / ".hos" / "setup-validation"
        marker_dir.mkdir(parents=True)
        (marker_dir / "bootstrap").touch()
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "bootstrap marker missing" not in r.stdout

    def test_broken_venv_warns(self, cron):
        """ensure_venv.sh exits non-zero → cron logs oversight-venv warning."""
        r = cron.run(env_overrides={"HOS_TEST_ENSURE_VENV_EXIT": "1"})
        assert r.returncode == 0, r.stdout + r.stderr  # fail-open: cron still runs
        assert "oversight-venv broken or missing" in r.stdout

    def test_healthy_venv_no_warn(self, cron):
        """ensure_venv.sh exits 0 → no oversight-venv warning."""
        marker_dir = cron.home / ".hos" / "setup-validation"
        marker_dir.mkdir(parents=True)
        (marker_dir / "bootstrap").touch()
        r = cron.run()  # default HOS_TEST_ENSURE_VENV_EXIT=0
        assert r.returncode == 0, r.stdout + r.stderr
        assert "oversight-venv" not in r.stdout
        assert "✓ environment validated" in r.stdout
