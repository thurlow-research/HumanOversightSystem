"""Tests for bootstrap/delete_branch.sh (#2288 item 2).

The real script runs against a stubbed get_app_token.sh / curl and a stub
python3 on PATH that records argv and exits $PY_RC. No network.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.tmp_hygiene import child_env

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
DELETE_BRANCH_SH = REPO_ROOT / "bootstrap" / "delete_branch.sh"

GET_APP_TOKEN_STUB = """#!/usr/bin/env bash
echo "GET_APP_TOKEN_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "${FAIL_TOKEN_MINT:-}" == "1" ]]; then exit 1; fi
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
"""

CURL_STUB = """#!/usr/bin/env bash
echo "CURL_CALLED_WITH:$*" >> "$CAPTURE_FILE"
exit 0
"""

AUDIT_LIB_STUB = """audit_write_event() { echo "AUDIT_EVENT:$1" >> "$CAPTURE_FILE"; }
"""

PYTHON_STUB = """#!/usr/bin/env bash
echo "PYTHON_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ -n "${PY_OUT:-}" ]]; then echo "$PY_OUT"; fi
exit "${PY_RC:-0}"
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Harness:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.bootstrap_dir = tmp_path / "bootstrap"
        self.bootstrap_dir.mkdir()
        self.script = self.bootstrap_dir / "delete_branch.sh"
        shutil.copy(DELETE_BRANCH_SH, self.script)
        self.script.chmod(0o755)
        _write_exec(self.bootstrap_dir / "get_app_token.sh", GET_APP_TOKEN_STUB)
        lib = tmp_path / "scripts" / "oversight" / "lib"
        lib.mkdir(parents=True)
        (lib / "audit_log.sh").write_text(AUDIT_LIB_STUB)
        self.stub_bin = tmp_path / "stub_bin"
        self.stub_bin.mkdir()
        _write_exec(self.stub_bin / "curl", CURL_STUB)
        _write_exec(self.stub_bin / "python3", PYTHON_STUB)
        self.capture_file = tmp_path / "capture.log"
        self.capture_file.write_text("")

    def run(self, args, env_overrides=None):
        env = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture_file),
            "HOME": str(self.tmp / "home"),
        }
        env.update(env_overrides or {})
        return subprocess.run(
            [BASH, str(self.script), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
            env=child_env(env),
        )

    def capture(self) -> str:
        return self.capture_file.read_text()


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


@pytest.mark.parametrize("rc", [0, 2, 3])
def test_db1_runs_delete_head_revokes_and_passes_rc_through(h, rc):
    result = h.run(["--pr", "42", "--app", "worker"], {"PY_RC": str(rc)})
    assert result.returncode == rc, result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app worker" in cap
    assert (
        f"PYTHON_CALLED_WITH:-m scripts.automation.readopt --repo {h.bootstrap_dir}/.. "
        "delete-head --pr 42"
    ) in cap
    assert cap.index("PYTHON_CALLED_WITH") < cap.index("CURL_CALLED_WITH")
    python_line = next(ln for ln in cap.splitlines() if ln.startswith("PYTHON_CALLED_WITH"))
    assert "fake-token" not in python_line


@pytest.mark.parametrize(
    "args",
    [
        ["--pr", "0", "--app", "worker"],
        ["--pr", "abc", "--app", "worker"],
        ["--pr", "007", "--app", "worker"],
        ["--app", "worker"],
        ["--pr", "5"],
        ["--pr", "5", "--app", "bogus"],
        ["--pr", "5", "--app", "worker", "--branch", "x"],
        ["--pr", "5", "--app", "worker", "--keep-branch"],
    ],
)
def test_db2_usage_errors_do_not_mint(h, args):
    result = h.run(args)
    assert result.returncode == 1
    assert h.capture() == ""


def test_db3_failed_mint_exits_2_without_running_python(h):
    result = h.run(["--pr", "42", "--app", "worker"], {"FAIL_TOKEN_MINT": "1"})
    assert result.returncode == 2
    assert "PYTHON_CALLED_WITH" not in h.capture()


@pytest.mark.parametrize(
    "line,rc,expected",
    [
        (
            "DELETED pr=#42 branch=fix/x tip=" + "a" * 40,
            0,
            {"outcome": "DELETED", "branch": "fix/x", "reason": "", "tip": "a" * 40},
        ),
        (
            "KEPT pr=#42 branch=fix/x reason=moved expected=" + "a" * 40 + " tip=" + "b" * 40,
            3,
            {"outcome": "KEPT", "branch": "fix/x", "reason": "moved", "tip": "b" * 40},
        ),
        (
            "ERROR pr=#42 reason=PR #42 not found",
            2,
            {"outcome": "ERROR", "branch": "", "reason": "PR #42 not found", "tip": ""},
        ),
        ("ALREADY-GONE pr=#42 branch=fix/x", 0, {"outcome": "ALREADY-GONE", "branch": "fix/x"}),
    ],
)
def test_db4_audit_event_per_outcome_and_stdout_unchanged(h, line, rc, expected):
    result = h.run(["--pr", "42", "--app", "worker"], {"PY_RC": str(rc), "PY_OUT": line})
    assert result.returncode == rc
    assert result.stdout.splitlines()[-1] == line
    events = [
        json.loads(ln.split(":", 1)[1])
        for ln in h.capture().splitlines()
        if ln.startswith("AUDIT_EVENT:")
    ]
    assert len(events) == 1
    ev = events[0]
    assert ev["event"] == "branch-delete" and ev["pr"] == 42 and ev["actor"] == "worker"
    assert ev["timestamp"].endswith("Z")
    for k, v in expected.items():
        assert ev[k] == v


def test_db5_audit_sink_failure_never_changes_rc(h):
    (h.tmp / "scripts" / "oversight" / "lib" / "audit_log.sh").write_text(
        "audit_write_event() { return 1; }\n"
    )
    result = h.run(["--pr", "42", "--app", "worker"], {"PY_RC": "3", "PY_OUT": "KEPT pr=#42"})
    assert result.returncode == 3
    assert result.stdout.splitlines()[-1] == "KEPT pr=#42"


def test_db6_revoke_curl_has_timeouts(h):
    h.run(["--pr", "42", "--app", "worker"])
    curl = next(ln for ln in h.capture().splitlines() if ln.startswith("CURL_CALLED_WITH"))
    assert "--connect-timeout 10 --max-time 30" in curl


def test_db7_control_characters_in_reason_still_yield_valid_json(h):
    reason = "bad\x1b[0m\there\x7f"
    line = f"ERROR pr=#42 reason={reason}"
    result = h.run(["--pr", "42", "--app", "worker"], {"PY_RC": "2", "PY_OUT": line})
    assert result.returncode == 2
    events = [
        ln.split(":", 1)[1] for ln in h.capture().splitlines() if ln.startswith("AUDIT_EVENT:")
    ]
    assert len(events) == 1
    assert json.loads(events[0])["reason"] == reason
