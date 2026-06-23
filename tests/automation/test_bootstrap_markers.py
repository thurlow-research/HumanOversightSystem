"""
Tests for bootstrap marker behavior (#806).

bootstrap/hos_bootstrap.sh must write ~/.hos/setup-validation/bootstrap on
successful completion — whether or not optional tools (e.g. scancode) are
missing (DEGRADED state).  The marker must NOT be written when required
prerequisites are missing (ERRORS > 0 → exit 1 before the marker write).

Strategy
--------
Run the real hos_bootstrap.sh with:
  * HOME overridden to a temp dir so markers land outside the real machine.
  * --skip-clis to bypass agent CLI installation.
  * --no-sudo so the script skips privileged apt/dnf calls.
  * A stub PATH that provides expected commands (python3 with correct version,
    gh) so the prerequisite checks pass without network access.
  * For the ERRORS case: a stub python3 that reports an old version so the
    version gate fails.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"

HOS_BOOTSTRAP_SH = (
    Path(__file__).parent.parent.parent / "bootstrap" / "hos_bootstrap.sh"
)


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


class BootstrapEnv:
    """
    Controlled environment for bootstrap marker tests.

    Stubs python3, gh, and other external tools so the script runs to
    completion without network access or real package installs.
    """

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.home = tmp_path / "home"
        self.stub_bin = tmp_path / "stub_bin"
        self.marker_dir = self.home / ".hos" / "setup-validation"

        self.home.mkdir()
        self.stub_bin.mkdir()

        # Stub python3 — reports 3.12 so the version check passes.
        # Must handle all forms the bootstrap uses:
        #   python3 --version                           → "Python 3.12.0"
        #   python3 -c "import sys; print(f'M.m')"     → "3.12"  (version extraction)
        #   python3 -c 'import sys; sys.exit(...)'      → exit 0  (version gate)
        #   python3 -c "import $pkg"                    → exit 0  (importability probe)
        #   python3 -m pip --version                    → "pip 23.0 ..."
        #   python3 -m pip install ...                  → exit 0
        _write_exec(
            self.stub_bin / "python3",
            "#!/usr/bin/env bash\n"
            'if [[ "${1:-}" == "--version" ]]; then echo "Python 3.12.0"; exit 0; fi\n'
            'if [[ "${1:-}" == "-c" ]]; then\n'
            # print(f'{major}.{minor}') — must output version string
            '  if [[ "$*" == *"print"* && "$*" == *"version_info"* ]]; then\n'
            '    echo "3.12"; exit 0\n'
            '  fi\n'
            # sys.exit(0 if version >= (3,10)) — just needs correct exit code
            '  if [[ "$*" == *"version_info"* ]]; then exit 0; fi\n'
            '  exit 0\n'
            'fi\n'
            'if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then\n'
            '  if [[ "${3:-}" == "--version" ]]; then echo "pip 23.0 from /usr 3.12"; exit 0; fi\n'
            '  exit 0\n'
            'fi\n'
            'exit 0\n',
        )

        # Stub gh — version + auth status both succeed.
        _write_exec(
            self.stub_bin / "gh",
            "#!/usr/bin/env bash\n"
            'if [[ "${1:-}" == "--version" ]]; then echo "gh version 2.40.0 (2024-01-01)"; exit 0; fi\n'
            'if [[ "${1:-}" == "auth" ]]; then exit 0; fi\n'
            'exit 0\n',
        )

        # Stub md5sum (used by ensure_venv for the repo hash; not called by bootstrap
        # but present for completeness on systems where the script might probe it).
        _write_exec(
            self.stub_bin / "md5sum",
            "#!/usr/bin/env bash\necho 'aabbccdd  -'\n",
        )

    @property
    def marker(self) -> Path:
        return self.marker_dir / "bootstrap"

    def run(self, extra_args=None, env_overrides=None,
            python_stub=None) -> subprocess.CompletedProcess:
        """
        Run hos_bootstrap.sh with the stubbed environment.

        python_stub: if provided, written as stub_bin/python3 before the run.
        """
        if python_stub is not None:
            _write_exec(self.stub_bin / "python3", python_stub)

        env = {
            "HOME": str(self.home),
            # Stub bin must precede system bins
            "PATH": f"{self.stub_bin}:/usr/bin:/bin",
            # Prevent interactive prompts
            "DEBIAN_FRONTEND": "noninteractive",
        }
        if env_overrides:
            env.update(env_overrides)

        args = [BASH, str(HOS_BOOTSTRAP_SH), "--skip-clis", "--no-sudo"]
        if extra_args:
            args += list(extra_args)
        return subprocess.run(
            args, capture_output=True, text=True, timeout=60,
            check=False, env=env,
        )


@pytest.fixture
def bootstrap(tmp_path):
    return BootstrapEnv(tmp_path)


# ─────────────────── Marker written on successful completion ────────────────
class TestBootstrapMarkerWritten:
    def test_successful_bootstrap_writes_marker(self, bootstrap):
        """A clean bootstrap (no DEGRADED) writes the marker."""
        r = bootstrap.run()
        # The script may exit non-zero if scancode is missing, but should write
        # the marker regardless because it exits after summary, not on ERRORS.
        # We assert the marker independently of exit code.
        assert bootstrap.marker.exists(), (
            f"bootstrap marker must exist after successful run; "
            f"stdout={r.stdout[-500:]!r} stderr={r.stderr[-200:]!r}"
        )

    def test_degraded_bootstrap_also_writes_marker(self, bootstrap):
        """DEGRADED completion (optional tools missing) must still write the marker.

        This is the bug that #806 fixes: previously the marker was only written in
        the non-DEGRADED else branch.
        """
        # scancode is absent from our stub PATH — that sets DEGRADED="ScanCode ..."
        r = bootstrap.run()
        assert "DEGRADED" in (r.stdout + r.stderr) or r.returncode == 0, (
            "expected either DEGRADED warning or clean exit; got neither"
        )
        # Regardless of DEGRADED, the marker must be written
        assert bootstrap.marker.exists(), (
            "bootstrap marker must be written even when running in DEGRADED state"
        )

    def test_dry_run_does_not_write_marker(self, bootstrap):
        """--dry-run must NOT write the marker (the marker write is wrapped in ! $DRY_RUN)."""
        r = bootstrap.run(extra_args=["--dry-run"])
        assert r.returncode == 0, r.stdout + r.stderr
        assert not bootstrap.marker.exists(), (
            "marker must not be written in --dry-run mode"
        )


# ─────────────── Marker NOT written when bootstrap has errors ───────────────
class TestBootstrapMarkerNotWrittenOnError:
    def test_old_python_errors_before_marker(self, bootstrap):
        """ERRORS > 0 (old Python) → exit 1 before the marker is written."""
        old_python = (
            "#!/usr/bin/env bash\n"
            'if [[ "${1:-}" == "--version" ]]; then echo "Python 2.7.18"; exit 0; fi\n'
            # version check: sys.version_info < (3,10) → exit 1
            'if [[ "${1:-}" == "-c" && "$*" == *"version_info"* ]]; then exit 1; fi\n'
            "exit 0\n"
        )
        r = bootstrap.run(python_stub=old_python)
        assert r.returncode == 1, (
            "bootstrap must exit 1 when python3 3.10+ is missing"
        )
        assert not bootstrap.marker.exists(), (
            "marker must NOT be written when bootstrap exits with errors"
        )
