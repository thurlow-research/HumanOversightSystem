"""The test session never writes the real tmp-root trust registry (#2100 S1, AD-10).

The guard's comparison logic is tested against temp stand-ins for the "real" path,
never the actual registry.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests import conftest as guard
from tests.framework.test_hos_human_launcher import _Launcher
from tests.tmp_hygiene import child_env


def test_the_session_override_is_set_and_is_not_the_real_path():
    override = os.environ[guard.REGISTRY_ENV]
    assert os.path.realpath(override) != os.path.realpath(guard.real_registry_path())


def test_the_real_path_is_computed_without_the_override(monkeypatch, tmp_path):
    monkeypatch.setenv(guard.REGISTRY_ENV, str(tmp_path / "x.json"))
    assert guard.real_registry_path().endswith("/.local/state/hos/tmp-roots.json")
    assert os.environ[guard.REGISTRY_ENV] == str(tmp_path / "x.json")


def test_a_launcher_run_writes_only_the_override(tmp_path):
    """The launcher test that used to leak a test_the_token_file_is_removed0 entry."""
    real = guard.real_registry_path()
    before = guard.registry_fingerprint(real)
    launcher = _Launcher(tmp_path)
    r = launcher.run()
    assert r.returncode == 0, r.stdout + r.stderr
    entries = json.loads(launcher.registry.read_text())["entries"]
    assert [e["path"] for e in entries] == [os.path.realpath(launcher.parent / ".tmp" / "Human")]
    assert guard.registry_changes(before, guard.registry_fingerprint(real)) is None


def test_the_guard_fails_when_the_real_path_changes(tmp_path):
    fake_real = tmp_path / "state" / "tmp-roots.json"
    absent = guard.registry_fingerprint(str(fake_real))
    assert absent == {"present": False}
    fake_real.parent.mkdir()
    fake_real.write_text("{}")
    created = guard.registry_fingerprint(str(fake_real))
    assert guard.registry_changes(absent, created)

    fake_real.write_text('{"version": 1}')
    rewritten = guard.registry_fingerprint(str(fake_real))
    assert guard.registry_changes(created, rewritten)

    os.utime(fake_real, ns=(1, 1))
    touched = guard.registry_fingerprint(str(fake_real))
    assert guard.registry_changes(rewritten, touched)
    assert guard.registry_changes(touched, guard.registry_fingerprint(str(fake_real))) is None


def test_the_guard_never_creates_the_file_or_its_directory(tmp_path):
    missing = tmp_path / "no" / "such" / "dir" / "tmp-roots.json"
    assert guard.registry_fingerprint(str(missing)) == {"present": False}
    assert not (tmp_path / "no").exists()


def test_the_guard_passes_when_the_real_registry_is_unreadable(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    target = locked / "tmp-roots.json"
    target.write_text("{}")
    locked.chmod(0)
    try:
        if os.access(locked, os.X_OK):  # running as root: chmod does not hide it
            pytest.skip("cannot make a path unreadable as this user")
        before = guard.registry_fingerprint(str(target))
        assert before == guard.NOT_OBSERVABLE
        assert guard.registry_changes(before, guard.registry_fingerprint(str(target))) is None
        assert guard.registry_changes({"present": False}, before) is None
    finally:
        locked.chmod(0o700)


def test_a_symlink_is_fingerprinted_without_being_followed(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    fp = guard.registry_fingerprint(str(link))
    assert isinstance(fp, dict) and fp["present"] and fp["sha256"] is None


def test_a_from_scratch_env_through_child_env_sees_the_session_override():
    r = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import os,sys;sys.path.insert(0,sys.argv[1]);import hos_tmp_root;"
            "print(hos_tmp_root.registry_path())",
            str(guard.ROOT / "bootstrap" / "lib"),
        ],
        env=child_env({"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == os.environ[guard.REGISTRY_ENV]
    assert r.stdout.strip() != guard.real_registry_path()
