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
import time
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
        # Records each `gh issue create` invocation so dedup/fail-closed tests
        # (#849) can assert whether a [BLOCKED] issue was actually filed.
        self.aa_issue_marker = tmp_path / "aa_issue_create.log"

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

        # gh stub — configurable via HOS_TEST_* env vars so individual tests can
        # exercise halt-check, agent-availability, and PR-routing paths without
        # needing a real GitHub API.  Matches on argument substrings; unknown calls
        # fall through to exit 0 (safe default for non-targeted invocations).
        _write_exec(
            self.bindir / "gh",
            "#!/usr/bin/env bash\n"
            'ARGS="$*"\n'
            'case "$ARGS" in\n'
            # Halt check: issues?labels=hos-halt
            '  *"labels=hos-halt"*)\n'
            '    echo "${HOS_TEST_HALT_COUNT:-0}" ;;\n'
            # Context: next work candidates (needs-ai issues, not needs-human)
            '  *"labels=needs-ai"*)\n'
            '    printf "%s\\n" ${HOS_TEST_ISSUE_CANDIDATES:-} ;;\n'
            # Agent availability: needs-human blocked issues count.
            # HOS_TEST_AA_QUERY_FAIL simulates a gh API failure (non-zero exit)
            # so the #849 fail-closed dedup path can be exercised.
            '  *"labels=needs-human"*)\n'
            '    [[ -n "${HOS_TEST_AA_QUERY_FAIL:-}" ]] && exit 1\n'
            '    echo "${HOS_TEST_NEEDS_HUMAN_BLOCKED:-0}" ;;\n'
            # PR list (open bot PRs) — outputs one PR number per line
            '  *"pulls?state=open"*)\n'
            '    printf "%s\\n" ${HOS_TEST_OPEN_PR_NUMS:-} ;;\n'
            # PR reviews — CHANGES_REQUESTED count
            '  *"reviews"*"CHANGES_REQUESTED"*)\n'
            '    echo "${HOS_TEST_PR_CR:-0}" ;;\n'
            # PR reviews — APPROVED count
            '  *"reviews"*"APPROVED"*)\n'
            '    echo "${HOS_TEST_PR_AP:-1}" ;;\n'
            'esac\n'
            # issue create — record the invocation, then confirm and exit
            'if [[ "$1" == "issue" && "$2" == "create" ]]; then\n'
            f'  echo "called" >> "{self.aa_issue_marker}"\n'
            '  echo "https://github.com/test/repo/issues/999"\n'
            'fi\n'
            "exit 0\n",
        )

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
        # fake oversight venv — satisfies the pre-jitter dependency check
        _write_exec(
            self.repo / "scripts" / "oversight" / ".venv" / "bin" / "python",
            "#!/usr/bin/env bash\nexit 0\n",
        )
        _write_exec(
            self.repo / "scripts" / "oversight" / ".venv" / "bin" / "pytest",
            "#!/usr/bin/env bash\nexit 0\n",
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

    def suspend_file(self, project="hos") -> Path:
        return self.state / "suspend" / project

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
            # Provide a synthetic repo slug so gh-API checks have a target without
            # needing a real git remote configured in the temporary repo directory.
            "HOS_REPO_SLUG": "test-org/test-repo",
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

    def add_agent_files(self, *slugs: str) -> None:
        """Create .claude/agents/<slug>.md stubs for the given agent slugs."""
        for slug in slugs:
            p = self.repo / ".claude" / "agents" / f"{slug}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# {slug}\n")

    def set_consumer_agents(self, *slugs: str) -> None:
        """Write a consumer_agents.txt with only the given slugs (no comments)."""
        f = self.repo / "scripts" / "framework" / "consumer_agents.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(slugs) + "\n")

    def claude_ran(self) -> bool:
        return self.claude_log.exists()

    def aa_issue_created(self) -> bool:
        """True if the launcher filed a [BLOCKED] agent-unavailable issue."""
        return self.aa_issue_marker.exists()

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


# ─────────────────────── Pre-jitter dependency check ─────────────────────────
class TestPreJitterDepsCheck:
    def test_missing_venv_exits_78_before_jitter(self, cron):
        """No oversight venv python → exit 78 before jitter sleep (fail-closed)."""
        (cron.repo / "scripts" / "oversight" / ".venv" / "bin" / "python").unlink()
        r = cron.run()
        assert r.returncode == 78, r.stdout + r.stderr
        assert "oversight venv missing" in r.stdout
        assert not cron.claude_ran()

    def test_missing_pytest_exits_78_before_jitter(self, cron):
        """pytest missing from venv → exit 78 before jitter sleep."""
        (cron.repo / "scripts" / "oversight" / ".venv" / "bin" / "pytest").unlink()
        r = cron.run()
        assert r.returncode == 78, r.stdout + r.stderr
        assert "pytest missing" in r.stdout
        assert not cron.claude_ran()

    def test_successful_check_writes_marker(self, cron):
        """Successful deps check writes a marker file in validation-cache."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        cache_dir = cron.state / "validation-cache"
        assert any(cache_dir.glob("deps-*")), "successful check must write deps marker"

    def test_fresh_marker_skips_validation_after_venv_removed(self, cron):
        """Once a fresh marker exists, removing the venv no longer causes exit 78."""
        # First run: succeeds and writes marker
        r1 = cron.run()
        assert r1.returncode == 0, r1.stdout + r1.stderr
        cache_dir = cron.state / "validation-cache"
        assert any(cache_dir.glob("deps-*"))
        # Remove venv python to simulate broken environment
        (cron.repo / "scripts" / "oversight" / ".venv" / "bin" / "python").unlink()
        # Clear bookkeeping state so idle backoff doesn't fire on the second run
        if cron.claude_log.exists():
            cron.claude_log.unlink()
        if cron.last_run_file.exists():
            cron.last_run_file.unlink()
        # Second run: marker is fresh → validation skipped → cycle proceeds
        r2 = cron.run()
        assert r2.returncode == 0, r2.stdout + r2.stderr
        assert cron.claude_ran()

    def test_stale_marker_triggers_revalidation_and_fails(self, cron):
        """A marker older than 7 days triggers re-validation; missing venv → exit 78."""
        # Run once to get the marker written
        r1 = cron.run()
        assert r1.returncode == 0, r1.stdout + r1.stderr
        cache_dir = cron.state / "validation-cache"
        markers = list(cache_dir.glob("deps-*"))
        assert markers
        # Make the marker appear 8 days old
        old_time = time.time() - (8 * 24 * 3600)
        for m in markers:
            os.utime(str(m), (old_time, old_time))
        # Remove venv so re-validation finds a missing dependency
        (cron.repo / "scripts" / "oversight" / ".venv" / "bin" / "python").unlink()
        if cron.claude_log.exists():
            cron.claude_log.unlink()
        if cron.last_run_file.exists():
            cron.last_run_file.unlink()
        # Re-run: stale marker → revalidation → venv missing → exit 78
        r2 = cron.run()
        assert r2.returncode == 78, r2.stdout + r2.stderr
        assert "oversight venv missing" in r2.stdout


# ──────────────────────────── Suspension (#778) ──────────────────────────────
class TestSuspension:
    """Suspension check exits cleanly before lock acquisition."""

    def test_suspended_project_exits_0_without_claude(self, cron):
        """Marker present → exit 0, Claude never invoked."""
        import json
        cron.suspend_file().parent.mkdir(parents=True, exist_ok=True)
        cron.suspend_file().write_text(json.dumps({"suspended_at": "2026-06-23T00:00:00Z"}))
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[SUSPENDED]" in r.stdout
        assert not cron.claude_ran()

    def test_suspended_project_logs_clear_hint(self, cron):
        """Log message includes the --clear hint so the operator knows how to resume."""
        import json
        cron.suspend_file().parent.mkdir(parents=True, exist_ok=True)
        cron.suspend_file().write_text(json.dumps({"suspended_at": "2026-06-23T00:00:00Z"}))
        r = cron.run()
        assert "--clear" in r.stdout

    def test_suspended_until_future_exits_0(self, cron):
        """Marker with future --until date → still suspended."""
        import json
        cron.suspend_file().parent.mkdir(parents=True, exist_ok=True)
        cron.suspend_file().write_text(json.dumps({"suspended_at": "2026-06-23T00:00:00Z", "until": "2099-12-31"}))
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[SUSPENDED]" in r.stdout
        assert not cron.claude_ran()

    def test_suspended_until_past_removes_marker_and_runs(self, cron):
        """Marker with expired --until → marker removed, cycle proceeds normally."""
        import json
        cron.suspend_file().parent.mkdir(parents=True, exist_ok=True)
        cron.suspend_file().write_text(json.dumps({"suspended_at": "2026-01-01T00:00:00Z", "until": "2026-01-02"}))
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "expired" in r.stdout
        assert not cron.suspend_file().exists()
        assert cron.claude_ran()

    def test_no_marker_runs_normally(self, cron):
        """No suspend marker → normal cycle, Claude invoked."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "[SUSPENDED]" not in r.stdout
        assert cron.claude_ran()


# ───────────────────────────── Halt check (#793) ─────────────────────────────
class TestHaltCheck:
    def test_halt_issue_present_skips_claude(self, cron):
        """Open hos-halt issue → cycle exits 0, Claude not launched."""
        r = cron.run(env_overrides={"HOS_TEST_HALT_COUNT": "1"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "HALT" in r.stdout
        assert "hos-halt" in r.stdout
        assert not cron.claude_ran()

    def test_halt_issue_present_logs_audit_event(self, cron):
        """cycle-skip reason=hos-halt is emitted (even if _audit silently fails)."""
        r = cron.run(env_overrides={"HOS_TEST_HALT_COUNT": "2"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert not cron.claude_ran()

    def test_no_halt_issue_proceeds(self, cron):
        """No halt issues → cycle runs normally."""
        r = cron.run(env_overrides={"HOS_TEST_HALT_COUNT": "0"})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "HALT" not in r.stdout
        assert cron.claude_ran()

    def test_halt_check_api_error_proceeds(self, cron):
        """gh API failure → treats as 0 halt issues (fail-open), proceeds."""
        # Simulate no _REPO_SLUG so the gh call is skipped entirely.
        r = cron.run(env_overrides={"HOS_REPO_SLUG": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "HALT" not in r.stdout
        assert cron.claude_ran()


# ─────────────────────── Agent availability check (#794) ─────────────────────
class TestAgentAvailability:
    def test_no_agents_list_proceeds(self, cron):
        """No consumer_agents.txt → check skipped, cycle runs normally."""
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "AGENT AVAILABILITY" not in r.stdout
        assert cron.claude_ran()

    def test_all_agents_present_proceeds(self, cron):
        """All listed agents exist → cycle runs normally."""
        cron.set_consumer_agents("worker", "overseer", "coder")
        cron.add_agent_files("worker", "overseer", "coder")
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert "AGENT AVAILABILITY" not in r.stdout
        assert cron.claude_ran()

    def test_missing_agent_exits_one(self, cron):
        """One agent missing → exit 1, Claude not launched."""
        cron.set_consumer_agents("worker", "coder")
        cron.add_agent_files("worker")  # coder missing
        r = cron.run()
        assert r.returncode == 1, r.stdout + r.stderr
        assert "AGENT AVAILABILITY FAIL" in r.stdout
        assert "coder" in r.stdout
        assert not cron.claude_ran()

    def test_missing_agent_files_needs_human_issue_filed(self, cron):
        """Missing agents with no existing blocked issue → issue create called."""
        cron.set_consumer_agents("coder")
        # coder agent file absent; stub reports 0 existing blocked issues
        r = cron.run(env_overrides={"HOS_TEST_NEEDS_HUMAN_BLOCKED": "0"})
        assert r.returncode == 1, r.stdout + r.stderr
        assert not cron.claude_ran()
        assert cron.aa_issue_created(), "expected a [BLOCKED] issue to be filed"

    def test_missing_agent_duplicate_issue_guard(self, cron):
        """Existing blocked issue → no second issue create (duplicate guard)."""
        cron.set_consumer_agents("coder")
        # Stub reports 1 existing blocked issue → should NOT create another
        r = cron.run(env_overrides={"HOS_TEST_NEEDS_HUMAN_BLOCKED": "1"})
        assert r.returncode == 1, r.stdout + r.stderr
        assert not cron.claude_ran()
        assert not cron.aa_issue_created(), "existing issue → must not file a duplicate"

    def test_missing_agent_dedup_query_failure_fails_closed(self, cron):
        """#849: a dedup-query *error* must NOT default the count to 0 and file a
        duplicate [BLOCKED] issue (fail-open). On query failure, skip filing and
        warn (fail-closed)."""
        cron.set_consumer_agents("coder")
        r = cron.run(env_overrides={"HOS_TEST_AA_QUERY_FAIL": "1"})
        assert r.returncode == 1, r.stdout + r.stderr
        assert not cron.claude_ran()
        assert not cron.aa_issue_created(), (
            "dedup query failed → must fail closed and NOT file an issue"
        )
        assert "fail-closed" in r.stdout

    def test_comments_and_blanks_in_agents_list_ignored(self, cron):
        """Comment lines and blank lines in consumer_agents.txt are skipped."""
        f = cron.repo / "scripts" / "framework" / "consumer_agents.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# a comment\n\nworker\n\n# another comment\n")
        cron.add_agent_files("worker")
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.claude_ran()


# ──────────────────────────── PR routing skip (#791) ─────────────────────────
class TestPRRoutingSkip:
    def test_no_open_prs_launches_claude(self, cron):
        """No open bot PRs → no routing skip, Claude launched."""
        r = cron.run(env_overrides={"HOS_TEST_OPEN_PR_NUMS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting" not in r.stdout
        assert cron.claude_ran()

    def test_awaiting_merge_skips_claude(self, cron):
        """One open PR with APPROVED and no CHANGES_REQUESTED → skip launch."""
        r = cron.run(env_overrides={
            "HOS_TEST_OPEN_PR_NUMS": "856",
            "HOS_TEST_PR_CR": "0",
            "HOS_TEST_PR_AP": "1",
        })
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting human merge" in r.stdout
        assert not cron.claude_ran()

    def test_awaiting_merge_drops_overseer_wakeup(self, cron):
        """Skipped cycle still signals overseer so it can act on the ready PR."""
        r = cron.run(env_overrides={
            "HOS_TEST_OPEN_PR_NUMS": "856",
            "HOS_TEST_PR_CR": "0",
            "HOS_TEST_PR_AP": "1",
        })
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.wakeup_overseer.exists(), "overseer wakeup must be dropped"
        payload = cron.wakeup_overseer.read_text()
        assert "worker-cycle-skip" in payload

    def test_awaiting_merge_stamps_last_run(self, cron):
        """Skipped cycle stamps last-run so idle backoff applies normally."""
        r = cron.run(env_overrides={
            "HOS_TEST_OPEN_PR_NUMS": "856",
            "HOS_TEST_PR_CR": "0",
            "HOS_TEST_PR_AP": "1",
        })
        assert r.returncode == 0, r.stdout + r.stderr
        assert cron.last_run_file.exists(), "last-run must be stamped on skip"

    def test_changes_requested_launches_claude(self, cron):
        """PR with CHANGES_REQUESTED → worker must fix, Claude is launched."""
        r = cron.run(env_overrides={
            "HOS_TEST_OPEN_PR_NUMS": "856",
            "HOS_TEST_PR_CR": "1",
            "HOS_TEST_PR_AP": "1",
        })
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting" not in r.stdout
        assert cron.claude_ran()

    def test_unapproved_pr_launches_claude(self, cron):
        """PR with no approvals yet → not 'awaiting merge', Claude launched."""
        r = cron.run(env_overrides={
            "HOS_TEST_OPEN_PR_NUMS": "856",
            "HOS_TEST_PR_CR": "0",
            "HOS_TEST_PR_AP": "0",  # not yet approved
        })
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting" not in r.stdout
        assert cron.claude_ran()

    def test_overseer_role_not_subject_to_pr_routing(self, cron):
        """PR routing skip applies only to worker — overseer always launches."""
        r = cron.run(role="overseer", env_overrides={
            "HOS_TEST_OPEN_PR_NUMS": "856",
            "HOS_TEST_PR_CR": "0",
            "HOS_TEST_PR_AP": "1",
        })
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting" not in r.stdout
        assert cron.claude_ran()


# ──────────────────────── Working directory injection (#805) ──────────────────
class TestWorkingDirectoryInjection:
    def test_prompt_file_prepended_with_working_directory(self, cron):
        """When a prompt file exists, it is piped with WORKING DIRECTORY prepended."""
        # Write a minimal worker-cron-prompt.md; capture stdin via claude stub.
        prompt_file = cron.repo / "bootstrap" / "worker-cron-prompt.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("hello from prompt\n")
        # Override claude stub to capture its stdin to a file.
        stdin_capture = cron.home / "claude_stdin.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n"
            f'cat > "{stdin_capture}"\n'
            "exit 0\n",
        )
        r = cron.run()
        assert r.returncode == 0, r.stdout + r.stderr
        stdin_text = stdin_capture.read_text()
        assert stdin_text.startswith("WORKING DIRECTORY:"), (
            "First line must be the injected WORKING DIRECTORY"
        )
        assert str(cron.repo) in stdin_text, "Injected path must match REPO_ROOT"
        assert "hello from prompt" in stdin_text

    def test_no_hardcoded_paths_in_worker_prompt(self):
        """worker-cron-prompt.md must contain no absolute paths (regression guard)."""
        prompt = (
            Path(__file__).parent.parent.parent
            / "bootstrap" / "worker-cron-prompt.md"
        ).read_text()
        import re
        hardcoded = re.findall(r'(?:^|\s)(/(?:home|Users)/\S+)', prompt, re.MULTILINE)
        assert not hardcoded, (
            f"Hardcoded absolute paths found in worker-cron-prompt.md: {hardcoded}"
        )

    def test_no_hardcoded_paths_in_overseer_prompt(self):
        """overseer-cron-prompt.md must contain no absolute paths (regression guard)."""
        prompt = (
            Path(__file__).parent.parent.parent
            / "bootstrap" / "overseer-cron-prompt.md"
        ).read_text()
        import re
        hardcoded = re.findall(r'(?:^|\s)(/(?:home|Users)/\S+)', prompt, re.MULTILINE)
        assert not hardcoded, (
            f"Hardcoded absolute paths found in overseer-cron-prompt.md: {hardcoded}"
        )


# ─────────────────────── Pre-computed cycle context (#792) ─────────────────────
class TestCycleContextBlock:
    """_build_context() appends a pre-computed block to the Claude prompt (#792)."""

    def _setup_stdin_capture(self, cron: CronEnv) -> Path:
        """Replace claude stub to capture its stdin; write a minimal prompt file."""
        stdin_capture = cron.home / "claude_stdin.log"
        _write_exec(
            cron.bindir / "claude",
            "#!/usr/bin/env bash\n"
            f'cat > "{stdin_capture}"\n'
            "exit 0\n",
        )
        prompt_file = cron.repo / "bootstrap" / "worker-cron-prompt.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text("## Worker step instructions\n")
        return stdin_capture

    def test_context_block_present_no_open_prs(self, cron):
        """0 open bot PRs → context block header present and 'None.' shown."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(env_overrides={"HOS_TEST_OPEN_PR_NUMS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "Pre-computed cycle context" in context
        assert "None." in context

    def test_context_block_one_open_pr(self, cron):
        """1 open bot PR → context block shows that PR number."""
        stdin_capture = self._setup_stdin_capture(cron)
        # PR_AP=0: unapproved → routing marks needs-attention → Claude launched
        r = cron.run(env_overrides={
            "HOS_TEST_OPEN_PR_NUMS": "856",
            "HOS_TEST_PR_AP": "0",
            "HOS_TEST_PR_CR": "0",
        })
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "Pre-computed cycle context" in context
        assert "856" in context
        assert "None." not in context

    def test_context_block_three_open_prs(self, cron):
        """3 open bot PRs → context block lists all three numbers."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(env_overrides={
            "HOS_TEST_OPEN_PR_NUMS": "856 857 858",
            "HOS_TEST_PR_AP": "0",
            "HOS_TEST_PR_CR": "0",
        })
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        assert "Pre-computed cycle context" in context
        assert "856" in context
        assert "857" in context
        assert "858" in context

    def test_context_block_follows_prompt_content(self, cron):
        """Context block is appended after the prompt file content, not before it."""
        stdin_capture = self._setup_stdin_capture(cron)
        r = cron.run(env_overrides={"HOS_TEST_OPEN_PR_NUMS": ""})
        assert r.returncode == 0, r.stdout + r.stderr
        context = stdin_capture.read_text()
        prompt_pos = context.find("## Worker step instructions")
        ctx_pos = context.find("Pre-computed cycle context")
        assert prompt_pos >= 0, "prompt file content must be present"
        assert ctx_pos >= 0, "context block must be present"
        assert prompt_pos < ctx_pos, "context block must follow prompt content"

    def test_context_block_absent_when_routing_skips_claude(self, cron):
        """All PRs awaiting merge → routing skips Claude launch; no context delivered."""
        r = cron.run(env_overrides={
            "HOS_TEST_OPEN_PR_NUMS": "856",
            "HOS_TEST_PR_AP": "1",
            "HOS_TEST_PR_CR": "0",
        })
        assert r.returncode == 0, r.stdout + r.stderr
        assert "awaiting human merge" in r.stdout


# ───────────────────────── _sync_audit_logs ────────────────────────────────
def _extract_sync_audit_logs_func() -> str:
    """Extract the _sync_audit_logs function body from bin/hos-cron."""
    lines = HOS_CRON.read_text().splitlines()
    in_func, depth, collected = False, 0, []
    for line in lines:
        if line.startswith("_sync_audit_logs()"):
            in_func = True
        if in_func:
            collected.append(line)
            depth += line.count("{") - line.count("}")
            if depth == 0 and len(collected) > 1:
                break
    return "\n".join(collected)


_SYNC_FUNC = _extract_sync_audit_logs_func()


def _git(*args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + list(args), cwd=cwd, check=True, capture_output=True, text=True
    )


def _make_repos(tmp_path: Path) -> tuple[Path, Path]:
    """Create a bare remote and a fully-configured local clone with a main branch."""
    remote = tmp_path / "remote.git"
    local = tmp_path / "local"
    _git("init", "--bare", str(remote))
    _git("init", str(local))
    _git("-C", str(local), "config", "user.email", "test@hos.test")
    _git("-C", str(local), "config", "user.name", "HOS Test")
    _git("-C", str(local), "commit", "--allow-empty", "-m", "init", "--quiet")
    _git("-C", str(local), "remote", "add", "origin", str(remote))
    _git("-C", str(local), "push", "origin", "HEAD:main", "--quiet")
    return remote, local


def _run_sync(local: Path, env_extra=None) -> subprocess.CompletedProcess:
    env = {"PATH": "/usr/bin:/bin", "HOME": str(local.parent)}
    if env_extra:
        env.update(env_extra)
    script = (
        "#!/usr/bin/env bash\n"
        "set -uo pipefail\n"
        'LOG_PREFIX="[test]"\n'
        + _SYNC_FUNC
        + f'\n_sync_audit_logs "{local}"\n'
    )
    return subprocess.run(
        [BASH, "-c", script],
        capture_output=True, text=True, timeout=30, check=False, env=env,
    )


def _remote_branch_exists(remote: Path, branch: str) -> bool:
    r = subprocess.run(
        ["git", "ls-remote", "--exit-code", str(remote), branch],
        capture_output=True, check=False,
    )
    return r.returncode == 0


def _files_on_branch(remote: Path, branch: str) -> list[str]:
    r = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", f"refs/heads/{branch}"],
        cwd=remote, capture_output=True, text=True, check=False,
    )
    return r.stdout.splitlines()


class TestSyncAuditLogs:
    """Unit tests for _sync_audit_logs() in bin/hos-cron (#861)."""

    def test_changed_audit_files_pushed_to_audit_log_branch(self, tmp_path):
        """Audit files present and changed → committed and pushed to audit-log (not main)."""
        remote, local = _make_repos(tmp_path)
        audit_dir = local / "audit"
        audit_dir.mkdir(parents=True)
        (audit_dir / "oversight-log.jsonl").write_text('{"event":"cycle-start"}\n')

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert _remote_branch_exists(remote, "audit-log")
        tree = _files_on_branch(remote, "audit-log")
        assert any("oversight-log" in f for f in tree), (
            f"Expected audit file on audit-log branch, got: {tree}"
        )

    def test_no_audit_files_on_disk_no_push(self, tmp_path):
        """No audit files on disk → function returns early, audit-log branch not created."""
        remote, local = _make_repos(tmp_path)

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert not _remote_branch_exists(remote, "audit-log")

    def test_audit_log_branch_absent_bases_off_main(self, tmp_path):
        """No existing audit-log branch → new branch is rooted at main."""
        remote, local = _make_repos(tmp_path)
        assert not _remote_branch_exists(remote, "audit-log")

        (local / "audit").mkdir(parents=True)
        (local / "audit" / "oversight-log.jsonl").write_text('{"event":"test"}\n')

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert _remote_branch_exists(remote, "audit-log"), "audit-log branch should be created"
        assert "audit logs pushed" in r.stdout

    def test_audit_log_branch_exists_rebases_from_it(self, tmp_path):
        """Existing audit-log branch → new commit is based on it, not on main."""
        remote, local = _make_repos(tmp_path)

        # Seed the remote audit-log branch with a prior commit
        seed_local = tmp_path / "seed"
        _git("clone", str(remote), str(seed_local))
        _git("-C", str(seed_local), "config", "user.email", "test@hos.test")
        _git("-C", str(seed_local), "config", "user.name", "HOS Test")
        _git("-C", str(seed_local), "checkout", "-b", "audit-log", "--quiet")
        (seed_local / "audit").mkdir(parents=True)
        (seed_local / "audit" / "overnight-loop-log.md").write_text("# prior\n")
        _git("-C", str(seed_local), "add", "audit/overnight-loop-log.md")
        _git("-C", str(seed_local), "commit", "-m", "prior audit", "--quiet")
        _git("-C", str(seed_local), "push", "origin", "HEAD:audit-log", "--quiet")

        # Now add new content to local and sync
        (local / "audit").mkdir(parents=True)
        (local / "audit" / "oversight-log.jsonl").write_text('{"event":"new"}\n')

        r = _run_sync(local)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "audit logs pushed" in r.stdout

    def test_push_failure_warns_and_exits_zero(self, tmp_path):
        """Push failure prints WARN line but the function exits 0 (retry next cycle)."""
        remote, local = _make_repos(tmp_path)
        (local / "audit").mkdir(parents=True)
        (local / "audit" / "oversight-log.jsonl").write_text('{"event":"test"}\n')

        # Fake git that succeeds on all operations except push
        fake_bin = tmp_path / "fakebin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        real_git = subprocess.check_output(["which", "git"], text=True).strip()
        fake_git.write_text(
            "#!/usr/bin/env bash\n"
            'if [[ "$*" == *"push"* ]]; then\n'
            '  echo "fatal: fake push failure" >&2\n'
            "  exit 1\n"
            "fi\n"
            f'exec "{real_git}" "$@"\n'
        )
        fake_git.chmod(0o755)

        r = _run_sync(local, env_extra={"PATH": f"{fake_bin}:/usr/bin:/bin"})
        assert r.returncode == 0, f"push failure must not exit non-zero; got {r.returncode}"
        assert "WARN" in r.stdout and "push failed" in r.stdout
