"""Tests for bootstrap/post_comment.sh (#1155).

Runs the real script against stubbed git/gh/curl/get_app_token.sh on PATH so
the argument-parsing, --body-file-only, @path-literal guard, and
mint/comment/revoke flow are exercised without touching the network or a
real GitHub App.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
POST_COMMENT_SH = REPO_ROOT / "bootstrap" / "post_comment.sh"

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
if [[ "$1" == "issue" && "$2" == "comment" ]]; then
    if [[ "${GH_FAIL:-}" == "1" ]]; then exit 1; fi
    echo "https://github.com/test-owner/test-repo/issues/999#issuecomment-1"
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
        self.script = self.bootstrap_dir / "post_comment.sh"
        shutil.copy(POST_COMMENT_SH, self.script)
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
        self.body_file.write_text("comment body\nwith a newline\n")

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


def test_missing_number(h):
    result = h.run(["--body-file", str(h.body_file), "--app", "worker"])
    assert result.returncode != 0
    assert "--number" in result.stderr


def test_missing_body_file_flag(h):
    result = h.run(["--number", "42", "--app", "worker"])
    assert result.returncode != 0
    assert "--body-file" in result.stderr


def test_body_file_does_not_exist(h):
    result = h.run(["--number", "42", "--body-file", str(h.tmp / "missing.md"), "--app", "worker"])
    assert result.returncode != 0
    assert "not found" in result.stderr


def test_missing_app(h):
    result = h.run(["--number", "42", "--body-file", str(h.body_file)])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_invalid_app_value(h):
    result = h.run(["--number", "42", "--body-file", str(h.body_file), "--app", "bogus"])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_rejects_inline_body(h):
    result = h.run(["--number", "42", "--body", "inline text", "--app", "worker"])
    assert result.returncode != 0
    assert "--body-file" in result.stderr


def test_non_numeric_number_rejected(h):
    result = h.run(["--number", "not-a-number", "--body-file", str(h.body_file), "--app", "worker"])
    assert result.returncode != 0
    assert "--number" in result.stderr


def test_negative_number_rejected(h):
    result = h.run(["--number", "-5", "--body-file", str(h.body_file), "--app", "worker"])
    assert result.returncode != 0
    assert "--number" in result.stderr


# --------------------------------------------------------------------------- #
# #1155 regression guard: @path-literal body content
# --------------------------------------------------------------------------- #


def test_rejects_at_path_literal_body_content(h):
    h.body_file.write_text("@/tmp/claude/pr1154_comment.md")
    result = h.run(["--number", "1154", "--body-file", str(h.body_file), "--app", "overseer"])
    assert result.returncode != 0
    assert "#1155" in result.stderr
    cap = h.capture()
    assert "GH_CALLED_WITH" not in cap


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_happy_path_posts_comment_and_revokes_token(h):
    result = h.run([
        "--number", "1154", "--body-file", str(h.body_file), "--app", "overseer",
    ])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://github.com/test-owner/test-repo/issues/999#issuecomment-1"

    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app overseer" in cap
    assert "GH_CALLED_WITH:issue comment 1154 --repo test-owner/test-repo --body-file" in cap
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap


def test_token_mint_failure_aborts_before_gh(h):
    result = h.run(
        ["--number", "1154", "--body-file", str(h.body_file), "--app", "worker"],
        env_overrides={"FAIL_TOKEN_MINT": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "GH_CALLED_WITH" not in cap


def test_gh_failure_still_revokes_token(h):
    result = h.run(
        ["--number", "1154", "--body-file", str(h.body_file), "--app", "worker"],
        env_overrides={"GH_FAIL": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap
