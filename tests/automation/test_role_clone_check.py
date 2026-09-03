"""Tests for bootstrap/lib/role_clone_check.sh (#1409).

bin/hos-worker and bin/hos-overseer each fix a role by which script you
invoke and derive REPO_ROOT from their own location on disk, with no
cross-check against the registry. `_hos_check_role_clone` closes that gap:
it fails loudly when the clone is registered as the *other* role's root for
some project, and is a no-op (fail-open) when the clone isn't registered at
all — the same convention bin/hos-human already uses for its own registry
lookup (#1407).

Strategy: source the real library into a throwaway bash process (via `bash
-c`) against a fake HOME + projects.conf, and call the function directly.
No stubs for git/claude/get_app_token.sh needed since the function under
test has no side effects beyond stdout/stderr and its return code.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB = _REPO_ROOT / "bootstrap" / "lib" / "role_clone_check.sh"
_HOS_WORKER = _REPO_ROOT / "bin" / "hos-worker"
_HOS_OVERSEER = _REPO_ROOT / "bin" / "hos-overseer"


def _run_check(home: Path, role: str, repo_root: Path) -> subprocess.CompletedProcess:
    script = f'source "{_LIB}"\n' f'_hos_check_role_clone "{role}" "{repo_root}"\n'
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    return subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def registry(tmp_path: Path):
    home = tmp_path / "home"
    (home / ".config" / "hos").mkdir(parents=True)
    worker_clone = tmp_path / "WorkerClone"
    overseer_clone = tmp_path / "OverseerClone"
    worker_clone.mkdir()
    overseer_clone.mkdir()
    (home / ".config" / "hos" / "projects.conf").write_text(
        f"demo_worker_root={worker_clone}\n" f"demo_overseer_root={overseer_clone}\n"
    )
    return {
        "home": home,
        "worker_clone": worker_clone,
        "overseer_clone": overseer_clone,
    }


def test_worker_in_worker_clone_passes(registry):
    result = _run_check(registry["home"], "worker", registry["worker_clone"])
    assert result.returncode == 0
    assert result.stderr == ""


def test_overseer_in_overseer_clone_passes(registry):
    result = _run_check(registry["home"], "overseer", registry["overseer_clone"])
    assert result.returncode == 0
    assert result.stderr == ""


def test_worker_in_overseer_clone_fails_loudly(registry):
    """The concrete #1409 scenario: hos-worker typed in the Overseer clone."""
    result = _run_check(registry["home"], "worker", registry["overseer_clone"])
    assert result.returncode == 1
    assert "role/clone mismatch" in result.stderr
    assert "demo_overseer_root" in result.stderr
    assert "hos-overseer" in result.stderr


def test_overseer_in_worker_clone_fails_loudly(registry):
    result = _run_check(registry["home"], "overseer", registry["worker_clone"])
    assert result.returncode == 1
    assert "role/clone mismatch" in result.stderr
    assert "demo_worker_root" in result.stderr
    assert "hos-worker" in result.stderr


def test_unregistered_clone_fails_open(registry, tmp_path):
    """A first-install clone predates registration — must not block (#1407 convention)."""
    unregistered = tmp_path / "Unregistered"
    unregistered.mkdir()
    result = _run_check(registry["home"], "worker", unregistered)
    assert result.returncode == 0
    assert result.stderr == ""


def test_missing_projects_conf_fails_open(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    result = _run_check(home, "worker", tmp_path / "SomeClone")
    assert result.returncode == 0
    assert result.stderr == ""


def test_trailing_slash_normalized(registry):
    """A registry entry or REPO_ROOT with a trailing slash still matches."""
    (registry["home"] / ".config" / "hos" / "projects.conf").write_text(
        f"demo_worker_root={registry['worker_clone']}/\n"
        f"demo_overseer_root={registry['overseer_clone']}\n"
    )
    result = _run_check(registry["home"], "worker", registry["overseer_clone"])
    assert result.returncode == 1
    assert "role/clone mismatch" in result.stderr


# --------------------------------------------------------------------------- #
# Static guards: the real launchers actually call the check before auth
# --------------------------------------------------------------------------- #


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.skipif(not _HOS_WORKER.exists(), reason="bin/hos-worker not present")
def test_hos_worker_sources_role_clone_check():
    src = _src(_HOS_WORKER)
    assert "role_clone_check.sh" in src
    assert "_hos_check_role_clone worker" in src


@pytest.mark.skipif(not _HOS_WORKER.exists(), reason="bin/hos-worker not present")
def test_hos_worker_checks_role_before_auth():
    src = _src(_HOS_WORKER)
    check_pos = src.index("_hos_check_role_clone worker")
    auth_pos = src.index("get_app_token.sh")
    assert check_pos < auth_pos, "role/clone check must run before any token is minted"


@pytest.mark.skipif(not _HOS_OVERSEER.exists(), reason="bin/hos-overseer not present")
def test_hos_overseer_sources_role_clone_check():
    src = _src(_HOS_OVERSEER)
    assert "role_clone_check.sh" in src
    assert "_hos_check_role_clone overseer" in src


@pytest.mark.skipif(not _HOS_OVERSEER.exists(), reason="bin/hos-overseer not present")
def test_hos_overseer_checks_role_before_auth():
    src = _src(_HOS_OVERSEER)
    check_pos = src.index("_hos_check_role_clone overseer")
    auth_pos = src.index("get_app_token.sh")
    assert check_pos < auth_pos, "role/clone check must run before any token is minted"
