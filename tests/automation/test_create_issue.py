"""Tests for bootstrap/create_issue.sh (#1085).

Runs the real script against stubbed git/gh/curl/get_app_token.sh on PATH so
the argument-parsing, --body-file-only, and mint/create/revoke flow are
exercised without touching the network or a real GitHub App.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
CREATE_ISSUE_SH = REPO_ROOT / "bootstrap" / "create_issue.sh"

GET_APP_TOKEN_STUB = """#!/usr/bin/env bash
echo "GET_APP_TOKEN_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "${FAIL_TOKEN_MINT:-}" == "1" ]]; then exit 1; fi
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
printf "export HOS_BOT_LOGIN='fake-bot[bot]'\\n"
"""

GIT_STUB = """#!/usr/bin/env bash
echo "GIT_CALLED_WITH:$*" >> "$CAPTURE_FILE"
i=0
if [[ "$1" == "-C" ]]; then i=2; fi
sub="${@:$((i+1)):1}"
case "$sub" in
  remote) echo "https://github.com/test-owner/test-repo.git" ;;
esac
exit 0
"""

GH_STUB = """#!/usr/bin/env bash
echo "GH_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "$1" == "issue" && "$2" == "create" ]]; then
    if [[ "${GH_FAIL:-}" == "1" ]]; then exit 1; fi
    echo "https://github.com/test-owner/test-repo/issues/999"
    exit 0
fi
exit 1
"""

CURL_STUB = """#!/usr/bin/env bash
echo "CURL_CALLED_WITH:$*" >> "$CAPTURE_FILE"
exit 0
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class Harness:
    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        self.bootstrap_dir = tmp_path / "bootstrap"
        self.bootstrap_dir.mkdir()
        self.script = self.bootstrap_dir / "create_issue.sh"
        shutil.copy(CREATE_ISSUE_SH, self.script)
        self.script.chmod(0o755)
        _write_exec(self.bootstrap_dir / "get_app_token.sh", GET_APP_TOKEN_STUB)

        self.stub_bin = tmp_path / "stub_bin"
        self.stub_bin.mkdir()
        _write_exec(self.stub_bin / "git", GIT_STUB)
        _write_exec(self.stub_bin / "gh", GH_STUB)
        _write_exec(self.stub_bin / "curl", CURL_STUB)

        self.capture_file = tmp_path / "capture.log"
        self.capture_file.write_text("")

        self.body_file = tmp_path / "body.md"
        self.body_file.write_text("issue body\nwith a newline\n")

    def run(self, args, env_overrides=None):
        env = {
            "PATH": f"{self.stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CAPTURE_FILE": str(self.capture_file),
            "HOME": str(self.tmp / "home"),
        }
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [BASH, str(self.script), *args],
            capture_output=True, text=True, timeout=30, check=False, env=env,
        )

    def capture(self) -> str:
        return self.capture_file.read_text()


@pytest.fixture
def h(tmp_path):
    return Harness(tmp_path)


# --------------------------------------------------------------------------- #
# Argument validation
# --------------------------------------------------------------------------- #


def test_missing_title(h):
    result = h.run(["--body-file", str(h.body_file), "--app", "worker"])
    assert result.returncode != 0
    assert "--title" in result.stderr


def test_missing_body_file_flag(h):
    result = h.run(["--title", "t", "--app", "worker"])
    assert result.returncode != 0
    assert "--body-file" in result.stderr


def test_body_file_does_not_exist(h):
    result = h.run(["--title", "t", "--body-file", str(h.tmp / "missing.md"), "--app", "worker"])
    assert result.returncode != 0
    assert "not found" in result.stderr


def test_missing_app(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file)])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_invalid_app_value(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--app", "bogus"])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_rejects_inline_body(h):
    result = h.run(["--title", "t", "--body", "inline text", "--app", "worker"])
    assert result.returncode != 0
    assert "--body-file" in result.stderr


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_happy_path_creates_issue_and_revokes_token(h):
    result = h.run([
        "--title", "Test issue", "--body-file", str(h.body_file),
        "--label", "priority:high,needs-ai", "--app", "worker",
    ])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://github.com/test-owner/test-repo/issues/999"

    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app worker" in cap
    assert "--repo test-owner/test-repo" in cap
    assert "--title Test issue" in cap
    assert "--label priority:high,needs-ai" in cap
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap


def test_label_omitted_when_not_passed(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--app", "overseer"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    gh_line = [ln for ln in cap.splitlines() if ln.startswith("GH_CALLED_WITH")][0]
    assert "--label" not in gh_line


def test_token_mint_failure_aborts_before_gh(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--app", "worker"],
        env_overrides={"FAIL_TOKEN_MINT": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "GH_CALLED_WITH" not in cap


def test_gh_failure_still_revokes_token(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--app", "worker"],
        env_overrides={"GH_FAIL": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap
