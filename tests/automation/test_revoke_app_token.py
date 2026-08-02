"""Tests for bootstrap/revoke_app_token.sh (#1191).

Runs the real script against a stubbed curl on PATH so the no-token,
idempotent-revoke, and error paths are exercised without touching the
network or a real GitHub App token.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
REVOKE_SH = REPO_ROOT / "bootstrap" / "revoke_app_token.sh"

CURL_STUB = """#!/usr/bin/env bash
echo "CURL_CALLED_WITH:$*" >> "$CAPTURE_FILE"
printf '%s' "${REVOKE_HTTP_CODE:-204}"
exit "${REVOKE_CURL_EXIT:-0}"
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Harness:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.stub_bin = tmp_path / "stub_bin"
        self.stub_bin.mkdir()
        _write_exec(self.stub_bin / "curl", CURL_STUB)

        self.capture_file = tmp_path / "capture.log"
        self.capture_file.write_text("")

    def run(self, env_overrides=None):
        env = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture_file),
            "HOME": str(self.tmp / "home"),
        }
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [BASH, str(REVOKE_SH)],
            capture_output=True, text=True, timeout=30, check=False, env=env,
        )

    def capture(self) -> str:
        return self.capture_file.read_text()


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


# --------------------------------------------------------------------------- #
# Call site / allowlistability
# --------------------------------------------------------------------------- #


def test_is_executable():
    assert os.access(REVOKE_SH, os.X_OK)


def test_call_site_has_no_expansion_or_substitution():
    text = REVOKE_SH.read_text()
    usage_line = next(ln for ln in text.splitlines() if "bash bootstrap/revoke_app_token.sh" in ln)
    assert "$" not in usage_line
    assert "`" not in usage_line


# --------------------------------------------------------------------------- #
# No-token-present path
# --------------------------------------------------------------------------- #


def test_no_token_present_exits_zero_without_calling_curl(h):
    result = h.run(env_overrides={"GH_TOKEN": ""})
    assert result.returncode == 0, result.stderr
    assert h.capture() == ""


def test_gh_token_unset_exits_zero(h):
    # GH_TOKEN not present in env at all (not just empty).
    result = h.run()
    assert result.returncode == 0, result.stderr
    assert h.capture() == ""


# --------------------------------------------------------------------------- #
# Successful revoke
# --------------------------------------------------------------------------- #


def test_successful_revoke_exits_zero_and_calls_delete(h):
    result = h.run(env_overrides={"GH_TOKEN": "fake-token-abc123", "REVOKE_HTTP_CODE": "204"})
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "-X DELETE" in cap
    assert "Authorization: token fake-token-abc123" in cap
    assert "https://api.github.com/installation/token" in cap


def test_token_value_never_reaches_stdout(h):
    result = h.run(env_overrides={"GH_TOKEN": "super-secret-token", "REVOKE_HTTP_CODE": "204"})
    assert "super-secret-token" not in result.stdout


# --------------------------------------------------------------------------- #
# Idempotent path — revoking twice in a row
# --------------------------------------------------------------------------- #


def test_revoking_twice_in_a_row_exits_zero_both_times(h):
    first = h.run(env_overrides={"GH_TOKEN": "fake-token-abc123", "REVOKE_HTTP_CODE": "204"})
    assert first.returncode == 0, first.stderr

    # Second call: GitHub would now report the token as already invalid.
    second = h.run(env_overrides={"GH_TOKEN": "fake-token-abc123", "REVOKE_HTTP_CODE": "401"})
    assert second.returncode == 0, second.stderr


def test_already_revoked_404_exits_zero(h):
    result = h.run(env_overrides={"GH_TOKEN": "fake-token-abc123", "REVOKE_HTTP_CODE": "404"})
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Error paths — never a hard failure
# --------------------------------------------------------------------------- #


def test_curl_network_failure_exits_zero(h):
    result = h.run(env_overrides={
        "GH_TOKEN": "fake-token-abc123",
        "REVOKE_CURL_EXIT": "1",
    })
    assert result.returncode == 0, result.stderr


def test_unexpected_http_code_exits_zero(h):
    result = h.run(env_overrides={"GH_TOKEN": "fake-token-abc123", "REVOKE_HTTP_CODE": "500"})
    assert result.returncode == 0, result.stderr
