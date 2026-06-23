"""
Tests for scripts/oversight/ensure_venv.sh — smoke-test-gated venv management.

Strategy
--------
ensure_venv.sh is a pure-bash script whose key behaviors are:

  1. Smoke test (import radon, bandit, flake8) runs on every invocation.
  2. Marker is only written AFTER a successful smoke test.
  3. A failing smoke test triggers a venv rebuild; if the rebuild also fails
     the script exits non-zero and leaves the marker absent.

We test these behaviors by:
  * Copying ensure_venv.sh to a temp directory (so VENV = tmp/oversight/.venv).
  * Injecting a stub python3 onto PATH that:
      - handles `python3 -m venv <path>`: creates a minimal fake venv with
        a stub python3 inside (stale-check shebang correct, pip exits 0).
      - handles `python3 -c "..."` (smoke test): exits via HOS_TEST_SMOKE_EXIT
        (default 0) or consumes a one-shot fail-file (HOS_TEST_SMOKE_FAIL_ONCE).
      - handles everything else (pip invocations, --version): exits 0.
  * Overriding HOME so marker writes land in a temp directory.
  * Asserting on exit code and marker-file presence.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"

ENSURE_VENV_SH = (
    Path(__file__).parent.parent.parent / "scripts" / "oversight" / "ensure_venv.sh"
)


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


class EnsureVenvEnv:
    """
    Test harness for ensure_venv.sh.

    Injects a stub python3 that controls venv creation and smoke-test outcomes
    without performing real pip installs.  HOME is redirected to a temp dir so
    marker writes don't touch the real machine.
    """

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        # Script dir simulates scripts/oversight/ — VENV = script_dir/.venv
        self.script_dir = tmp_path / "oversight"
        self.stub_bin = tmp_path / "stub_bin"
        self.venv = self.script_dir / ".venv"
        self.marker_dir = self.home / ".hos" / "setup-validation"

        self.home.mkdir()
        self.script_dir.mkdir()
        self.stub_bin.mkdir()

        # Copy the real ensure_venv.sh — it will compute VENV relative to itself.
        self.script = self.script_dir / "ensure_venv.sh"
        shutil.copy2(ENSURE_VENV_SH, self.script)
        self.script.chmod(0o755)

        # Empty requirements.txt (no real packages to install during tests)
        (self.script_dir / "requirements.txt").write_text("")

        # Stub python3:
        #   python3 -m venv <path>          → create minimal fake venv (copies stub)
        #   python3 -c "import ..."         → smoke test (controlled by env vars)
        #   python3 --version               → "Python 3.10.0"
        #   python3 /path/to/pip [...]      → exits 0  (pip-via-shebang invocations)
        _write_exec(
            self.stub_bin / "python3",
            "#!/usr/bin/env bash\n"
            # Use realpath so copies inherit the same path resolution
            'SELF="$(realpath "$0" 2>/dev/null || readlink -f "$0" 2>/dev/null || echo "$0")"\n'
            # python3 -m venv <path>: create minimal fake venv
            'if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then\n'
            '  P="${3}"\n'
            '  mkdir -p "$P/bin"\n'
            '  cp "$SELF" "$P/bin/python3"\n'
            '  chmod 755 "$P/bin/python3"\n'
            # pip shebang must match VENV path for ensure_venv.sh stale check
            '  printf "#!%s/bin/python3\\n# stub pip\\n" "$P" > "$P/bin/pip"\n'
            '  chmod 755 "$P/bin/pip"\n'
            '  exit 0\n'
            'fi\n'
            # python3 --version
            'if [[ "${1:-}" == "--version" ]]; then\n'
            '  echo "Python 3.10.0"\n'
            '  exit 0\n'
            'fi\n'
            # python3 -c "import ..." smoke test
            'if [[ "${1:-}" == "-c" ]]; then\n'
            # HOS_TEST_SMOKE_FAIL_ONCE: if set and the named file exists, consume it
            # and fail (next call succeeds — simulates broken-then-rebuilt scenario).
            '  ONCE="${HOS_TEST_SMOKE_FAIL_ONCE:-}"\n'
            '  if [[ -n "$ONCE" && -f "$ONCE" ]]; then\n'
            '    rm -f "$ONCE"\n'
            '    exit 1\n'
            '  fi\n'
            '  exit "${HOS_TEST_SMOKE_EXIT:-0}"\n'
            'fi\n'
            # Fallback: pip-via-shebang invocations (python3 /path/to/pip install ...)
            'exit 0\n',
        )

    def create_fake_venv(self) -> None:
        """Pre-create a minimal fake venv (so ensure_venv.sh skips the creation step)."""
        self.venv.mkdir(parents=True)
        (self.venv / "bin").mkdir()
        # python3: copy the stub so smoke tests go through it
        venv_python = self.venv / "bin" / "python3"
        shutil.copy2(self.stub_bin / "python3", venv_python)
        venv_python.chmod(0o755)
        # pip: shebang first line must start with VENV path (stale check uses head -1)
        pip = self.venv / "bin" / "pip"
        pip.write_text(f"#!{self.venv}/bin/python3\n# stub pip\n")
        pip.chmod(0o755)

    def marker_exists(self) -> bool:
        """True if any oversight-venv-* marker was written under our temp HOME."""
        if not self.marker_dir.exists():
            return False
        return bool(list(self.marker_dir.glob("oversight-venv-*")))

    def run(self, env_overrides=None, quiet=True) -> subprocess.CompletedProcess:
        env = {
            "HOME": str(self.home),
            # Stub python3 precedes system bins so venv creation uses our stub
            "PATH": f"{self.stub_bin}:/usr/bin:/bin",
        }
        if env_overrides:
            env.update(env_overrides)
        args = [BASH, str(self.script)]
        if quiet:
            args.append("--quiet")
        return subprocess.run(
            args, capture_output=True, text=True, timeout=30, check=False, env=env,
        )


@pytest.fixture
def venv_env(tmp_path):
    return EnsureVenvEnv(tmp_path)


# ─────────────────────── Healthy venv — marker written ─────────────────────
class TestHealthyVenv:
    def test_healthy_venv_exits_zero(self, venv_env):
        """Smoke test passes → script exits 0."""
        venv_env.create_fake_venv()
        r = venv_env.run()
        assert r.returncode == 0, r.stderr

    def test_healthy_venv_writes_marker(self, venv_env):
        """Smoke test passes → marker is written."""
        venv_env.create_fake_venv()
        venv_env.run()
        assert venv_env.marker_exists(), "marker must be written after a successful smoke test"

    def test_no_venv_created_and_smoke_passes_writes_marker(self, venv_env):
        """No pre-existing venv: create_venv runs, smoke passes, marker written."""
        # No call to create_fake_venv() — script must create the venv itself
        r = venv_env.run()
        assert r.returncode == 0, r.stderr
        assert venv_env.marker_exists()

    def test_quiet_flag_suppresses_stdout(self, venv_env):
        """--quiet suppresses informational output; errors still go to stderr."""
        venv_env.create_fake_venv()
        r = venv_env.run(quiet=True)
        assert r.returncode == 0, r.stderr
        # Quiet mode: no "→ creating" or "✔ ready" on stdout
        assert "creating" not in r.stdout
        assert "installing" not in r.stdout


# ─────────────── Broken venv → auto-repaired, marker written ───────────────
class TestBrokenVenvAutoRepair:
    def test_broken_venv_triggers_rebuild(self, venv_env):
        """Smoke test fails → venv is rebuilt → smoke test passes → exit 0."""
        venv_env.create_fake_venv()
        # First smoke test fails; after rebuild the flag is gone and it succeeds
        flag = venv_env.tmp / "smoke_fail_once"
        flag.touch()
        r = venv_env.run(env_overrides={"HOS_TEST_SMOKE_FAIL_ONCE": str(flag)})
        assert r.returncode == 0, f"expected successful rebuild; stderr={r.stderr}"

    def test_broken_venv_marker_written_after_rebuild(self, venv_env):
        """After auto-repair, marker is written."""
        venv_env.create_fake_venv()
        flag = venv_env.tmp / "smoke_fail_once"
        flag.touch()
        venv_env.run(env_overrides={"HOS_TEST_SMOKE_FAIL_ONCE": str(flag)})
        assert venv_env.marker_exists(), "marker must be written after successful rebuild"

    def test_broken_venv_no_marker_before_repair(self, venv_env):
        """If smoke always fails, marker must NOT be written."""
        venv_env.create_fake_venv()
        r = venv_env.run(env_overrides={"HOS_TEST_SMOKE_EXIT": "1"})
        assert r.returncode != 0
        assert not venv_env.marker_exists(), (
            "marker must not be written when smoke test fails even after rebuild"
        )


# ─────────────── Rebuild also fails — exit non-zero, no marker ─────────────
class TestRebuildFails:
    def test_rebuild_also_fails_exits_nonzero(self, venv_env):
        """All smoke tests fail → exit non-zero."""
        r = venv_env.run(env_overrides={"HOS_TEST_SMOKE_EXIT": "1"})
        assert r.returncode != 0, "must exit non-zero when rebuild also fails"

    def test_rebuild_also_fails_no_marker(self, venv_env):
        """All smoke tests fail → marker NOT written."""
        venv_env.run(env_overrides={"HOS_TEST_SMOKE_EXIT": "1"})
        assert not venv_env.marker_exists(), (
            "marker must not be written when venv cannot be repaired"
        )
