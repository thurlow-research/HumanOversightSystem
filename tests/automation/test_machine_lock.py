"""
Tests for machine_lock.sh — atomic lock, holder inspection, hang timeout (R7.5.3–R7.5.6).

These run the bash functions via subprocess (the lock is bash-native; no Python wrapper).
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path
from textwrap import dedent

import pytest

MACHINE_LOCK_SH = (
    Path(__file__).parent.parent.parent
    / "scripts" / "automation" / "lib" / "machine_lock.sh"
)


def _bash_run(script: str, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a bash snippet that sources machine_lock.sh first.
    Sets HOS_LOCK_JITTER_MAX=0 to skip the 0-60s random jitter in acquire_lock.
    """
    full = f"source {MACHINE_LOCK_SH}\n{script}"
    env = {**os.environ, "HOS_LOCK_JITTER_MAX": "0"}
    return subprocess.run(
        ["bash", "-c", full],
        capture_output=True, text=True, timeout=timeout, check=False,
        env=env,
    )


def _bash_script(script: str, timeout: int = 10) -> subprocess.CompletedProcess:
    """Write script to a temp file and run it (for scripts that need a real argv[0])."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".sh", delete=False, prefix="hos_test_"
    ) as f:
        f.write(f"#!/usr/bin/env bash\nsource {MACHINE_LOCK_SH}\n{script}\n")
        script_path = f.name
    env = {**os.environ, "HOS_LOCK_JITTER_MAX": "0"}
    try:
        os.chmod(script_path, 0o755)
        result = subprocess.run(
            ["bash", script_path],
            capture_output=True, text=True, timeout=timeout, check=False,
            env=env,
        )
    finally:
        os.unlink(script_path)
    return result


class TestResolveLockDir:
    def test_resolves_to_tmp_when_writable(self):
        result = _bash_run(
            "resolve_lock_dir && echo \"$_HOS_LOCK_DIR\""
        )
        assert result.returncode == 0
        out = result.stdout.strip()
        # Should prefer /tmp when writable.
        assert "/tmp/hos-worker.lock" in out or ".hos/worker.lock" in out

    def test_primary_is_tmp(self):
        result = _bash_run("echo \"$HOS_LOCK_PRIMARY\"")
        assert "/tmp/hos-worker.lock" in result.stdout


class TestAcquireRelease:
    def test_acquire_succeeds_when_lock_absent(self, tmp_path):
        lock_dir = tmp_path / "test-hos-worker.lock"
        result = _bash_run(dedent(f"""\
            HOS_LOCK_PRIMARY="{lock_dir}"
            HOS_LOCK_FALLBACK="{lock_dir}-fallback"
            acquire_lock
            echo "rc=$?"
            release_lock
        """))
        assert "rc=0" in result.stdout

    def test_lock_dir_created_on_acquire(self, tmp_path):
        lock_dir = tmp_path / "test-hos-worker.lock"
        result = _bash_run(dedent(f"""\
            HOS_LOCK_PRIMARY="{lock_dir}"
            HOS_LOCK_FALLBACK="{lock_dir}-fallback"
            acquire_lock
        """))
        # After acquire, meta file should exist.
        meta = lock_dir / "meta"
        assert meta.exists()
        pid_line = meta.read_text()
        assert "pid=" in pid_line
        assert "marker=hos-orchestrator" in pid_line

    def test_release_removes_lock_dir(self, tmp_path):
        lock_dir = tmp_path / "test-hos-worker.lock"
        _bash_run(dedent(f"""\
            HOS_LOCK_PRIMARY="{lock_dir}"
            HOS_LOCK_FALLBACK="{lock_dir}-fallback"
            acquire_lock
            release_lock
        """))
        assert not lock_dir.exists()

    def test_release_is_idempotent(self, tmp_path):
        lock_dir = tmp_path / "test-hos-worker.lock"
        result = _bash_run(dedent(f"""\
            HOS_LOCK_PRIMARY="{lock_dir}"
            HOS_LOCK_FALLBACK="{lock_dir}-fallback"
            release_lock
            echo "rc=$?"
        """))
        assert "rc=0" in result.stdout


class TestContention:
    def test_contention_with_dead_pid_reclaims_and_succeeds(self, tmp_path):
        """A lock held by a dead PID is treated as stale and reclaimed."""
        lock_dir = tmp_path / "test-hos-worker.lock"
        lock_dir.mkdir()
        meta = lock_dir / "meta"
        meta.write_text("pid=99999999\nstarted=2020-01-01T00:00:00Z\nmarker=hos-orchestrator\n")

        result = _bash_run(dedent(f"""\
            HOS_LOCK_PRIMARY="{lock_dir}"
            HOS_LOCK_FALLBACK="{lock_dir}-fallback"
            HOS_ORCHESTRATOR_LOCK_TIMEOUT_SECS=99999
            acquire_lock
            echo "rc=$?"
        """))
        assert "rc=0" in result.stdout
        assert "stale" in result.stdout.lower() or "stale" in result.stderr.lower()

    def test_contention_with_missing_meta_reclaims(self, tmp_path):
        """A lock dir with no meta file is reclaimed as stale."""
        lock_dir = tmp_path / "test-hos-worker.lock"
        lock_dir.mkdir()
        # No meta file.

        result = _bash_run(dedent(f"""\
            HOS_LOCK_PRIMARY="{lock_dir}"
            HOS_LOCK_FALLBACK="{lock_dir}-fallback"
            HOS_ORCHESTRATOR_LOCK_TIMEOUT_SECS=99999
            acquire_lock
            echo "rc=$?"
        """))
        assert "rc=0" in result.stdout


class TestHolderInspection:
    def test_is_holder_alive_requires_command_match(self, tmp_path):
        """_is_holder_alive returns false when PID is alive but command doesn't match.

        Use PID 1 (launchd/init) — always alive, never has the orchestrator markers.
        We pass the marker strings via a file to avoid embedding them in the bash -c
        argument (which ps -o command= would then match via the script text).
        """
        marker_file = tmp_path / "markers.env"
        marker_file.write_text(
            "TEST_SCRIPT=hos_orchestrator.sh\nTEST_MARKER=hos-orchestrator\n"
        )
        result = _bash_run(dedent(f"""\
            source {marker_file}
            HOS_ORCHESTRATOR_SCRIPT="$TEST_SCRIPT"
            HOS_ORCHESTRATOR_MARKER="$TEST_MARKER"
            # PID 1 (launchd/init) is always alive but never matches our markers.
            if _is_holder_alive 1; then
                echo "alive"
            else
                echo "not-alive"
            fi
        """))
        assert "not-alive" in result.stdout

    def test_hung_lock_reclaims(self, tmp_path):
        """A lock started long ago (simulated by past timestamp) is reclaimed as hung."""
        lock_dir = tmp_path / "test-hos-worker.lock"
        lock_dir.mkdir()
        meta = lock_dir / "meta"
        # Use PID 1 (always alive) so liveness check passes, forcing the hung-timeout path.
        meta.write_text("pid=1\nstarted=2020-01-01T00:00:00Z\nmarker=hos-orchestrator\n")

        result = _bash_run(dedent(f"""\
            HOS_LOCK_PRIMARY="{lock_dir}"
            HOS_LOCK_FALLBACK="{lock_dir}-fallback"
            HOS_ORCHESTRATOR_LOCK_TIMEOUT_SECS=1
            acquire_lock
            echo "rc=$?"
        """))
        assert "hung" in result.stdout.lower() or "hung" in result.stderr.lower()
        assert "rc=0" in result.stdout


class TestSecondsSinceIso:
    """#671: _seconds_since_iso must work on any host (BSD date, GNU date, or python3).

    The original used only macOS `date -j -f`, which fails silently on Linux —
    leaving `elapsed` empty so the hung-lock reclaim never fired. These tests pin
    the cross-platform contract directly, independent of which date(1) is present.
    """

    def test_returns_nonempty_elapsed_for_valid_timestamp(self):
        """A valid ISO-8601 UTC timestamp yields a non-empty, numeric elapsed."""
        result = _bash_run(
            "_seconds_since_iso 2020-01-01T00:00:00Z; echo \"rc=$?\""
        )
        assert "rc=0" in result.stdout
        elapsed = result.stdout.splitlines()[0].strip()
        assert elapsed != "", "elapsed must not be empty (the #671 silent-fail bug)"
        assert int(elapsed) > 0

    def test_recent_timestamp_yields_small_elapsed(self):
        """Elapsed since 'now' should be near zero, never empty."""
        result = _bash_run(dedent("""\
            now="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
            _seconds_since_iso "$now"
            echo "rc=$?"
        """))
        assert "rc=0" in result.stdout
        elapsed = int(result.stdout.splitlines()[0].strip())
        assert 0 <= elapsed < 60

    def test_malformed_timestamp_returns_failure(self):
        """Unparseable input must return non-zero (all parsers fail) — not empty success."""
        result = _bash_run(
            "_seconds_since_iso not-a-timestamp; echo \"rc=$?\""
        )
        assert "rc=1" in result.stdout


class TestTrap:
    def test_trap_releases_lock_on_exit(self, tmp_path):
        """setup_lock_trap ensures the lock is removed on EXIT."""
        lock_dir = tmp_path / "test-hos-worker.lock"
        result = _bash_run(dedent(f"""\
            HOS_LOCK_PRIMARY="{lock_dir}"
            HOS_LOCK_FALLBACK="{lock_dir}-fallback"
            setup_lock_trap
            acquire_lock
            # Subshell exits here; trap fires.
        """))
        assert result.returncode == 0
        assert not lock_dir.exists()


class TestADR3Separation:
    def test_lock_timeout_constant_is_20_minutes(self):
        """ADR-3: machine lock hang timeout must be 20m, not max_task_runtime (4h)."""
        result = _bash_run("echo \"$HOS_ORCHESTRATOR_LOCK_TIMEOUT_SECS\"")
        assert result.returncode == 0
        secs = int(result.stdout.strip())
        assert secs == 1200, (
            f"Expected 1200 (20 min); got {secs}. "
            "ADR-3 requires orchestrator_lock_timeout != max_task_runtime."
        )
