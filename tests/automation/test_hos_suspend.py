"""Tests for bin/hos-suspend — the project suspension CLI (#778)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
HOS_SUSPEND = Path(__file__).parent.parent.parent / "bin" / "hos-suspend"


def _run(args, tmp_home, tmp_state=None, extra_env=None):
    env = {
        "HOME": str(tmp_home),
        "PATH": "/usr/bin:/bin",
    }
    if tmp_state:
        env["HOS_STATE_DIR"] = str(tmp_state)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [BASH, str(HOS_SUSPEND)] + args,
        capture_output=True, text=True, check=False, env=env, timeout=10,
    )


@pytest.fixture
def env(tmp_path):
    """Minimal home + state directories with a populated projects.conf."""
    home = tmp_path / "home"
    state = tmp_path / "state"
    conf = home / ".config" / "hos" / "projects.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text(
        f"hos_config_dir={home}/.config/hos\n"
        f"hos_worker_root={tmp_path}/repo\n"
    )
    return home, state


# ────────────────────────────── suspend ──────────────────────────────────────

class TestSuspend:
    def test_creates_marker_file(self, env):
        home, state = env
        r = _run(["--project", "hos"], home, state)
        assert r.returncode == 0, r.stderr
        marker = state / "suspend" / "hos"
        assert marker.exists()
        d = json.loads(marker.read_text())
        assert "suspended_at" in d

    def test_creates_suspend_dir_if_missing(self, env):
        home, state = env
        assert not (state / "suspend").exists()
        r = _run(["--project", "hos"], home, state)
        assert r.returncode == 0, r.stderr
        assert (state / "suspend").is_dir()

    def test_with_until_stores_date(self, env):
        home, state = env
        r = _run(["--project", "hos", "--until", "2099-12-31"], home, state)
        assert r.returncode == 0, r.stderr
        d = json.loads((state / "suspend" / "hos").read_text())
        assert d["until"] == "2099-12-31"

    def test_with_reason_stores_reason(self, env):
        home, state = env
        r = _run(["--project", "hos", "--reason", "DB migration"], home, state)
        assert r.returncode == 0, r.stderr
        d = json.loads((state / "suspend" / "hos").read_text())
        assert d["reason"] == "DB migration"

    def test_no_until_no_reason_minimal_json(self, env):
        home, state = env
        r = _run(["--project", "hos"], home, state)
        assert r.returncode == 0, r.stderr
        d = json.loads((state / "suspend" / "hos").read_text())
        assert "until" not in d
        assert "reason" not in d

    def test_invalid_until_format_exits_nonzero(self, env):
        home, state = env
        r = _run(["--project", "hos", "--until", "tomorrow"], home, state)
        assert r.returncode != 0
        assert "YYYY-MM-DD" in r.stderr

    def test_unknown_project_exits_nonzero(self, env):
        home, state = env
        r = _run(["--project", "nonexistent"], home, state)
        assert r.returncode != 0
        assert "nonexistent" in r.stderr

    def test_missing_project_flag_exits_nonzero(self, env):
        home, state = env
        r = _run([], home, state)
        assert r.returncode != 0


# ────────────────────────────── clear ────────────────────────────────────────

class TestClear:
    def test_removes_existing_marker(self, env):
        home, state = env
        marker = state / "suspend" / "hos"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"suspended_at": "2026-06-23T00:00:00Z"}))
        r = _run(["--project", "hos", "--clear"], home, state)
        assert r.returncode == 0, r.stderr
        assert not marker.exists()
        assert "resumed" in r.stdout

    def test_clear_nonexistent_marker_is_noop(self, env):
        home, state = env
        r = _run(["--project", "hos", "--clear"], home, state)
        assert r.returncode == 0, r.stderr
        assert "not suspended" in r.stdout

    def test_clear_does_not_require_project_in_conf(self, env):
        """--clear should succeed even for a project removed from projects.conf."""
        home, state = env
        marker = state / "suspend" / "ghost-project"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"suspended_at": "2026-06-23T00:00:00Z"}))
        r = _run(["--project", "ghost-project", "--clear"], home, state)
        assert r.returncode == 0, r.stderr
        assert not marker.exists()


# ────────────────────────────── list ─────────────────────────────────────────

class TestList:
    def test_empty_shows_none_suspended(self, env):
        home, state = env
        r = _run(["--list"], home, state)
        assert r.returncode == 0, r.stderr
        assert "no projects suspended" in r.stdout

    def test_shows_suspended_project(self, env):
        home, state = env
        marker = state / "suspend" / "hos"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"suspended_at": "2026-06-23T00:00:00Z"}))
        r = _run(["--list"], home, state)
        assert r.returncode == 0, r.stderr
        assert "hos" in r.stdout
        assert "indefinite" in r.stdout

    def test_shows_expiry_date(self, env):
        home, state = env
        marker = state / "suspend" / "hos"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"suspended_at": "2026-06-23T00:00:00Z", "until": "2099-12-31"}))
        r = _run(["--list"], home, state)
        assert r.returncode == 0, r.stderr
        assert "2099-12-31" in r.stdout

    def test_shows_expired_marker(self, env):
        home, state = env
        marker = state / "suspend" / "hos"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"suspended_at": "2026-01-01T00:00:00Z", "until": "2026-01-02"}))
        r = _run(["--list"], home, state)
        assert r.returncode == 0, r.stderr
        assert "EXPIRED" in r.stdout

    def test_list_does_not_require_project(self, env):
        home, state = env
        r = _run(["--list"], home, state)
        assert r.returncode == 0
