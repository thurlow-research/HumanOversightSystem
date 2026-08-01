"""Tests for bootstrap/submit_pr.sh (#1085).

Runs the real script against stubbed git/gh/curl/get_app_token.sh on PATH so
the argument-parsing, --confirmed human-proxy gate, and
mint/push/create/revoke flow are exercised without touching the network or a
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
SUBMIT_PR_SH = REPO_ROOT / "bootstrap" / "submit_pr.sh"

GET_APP_TOKEN_STUB = """#!/usr/bin/env bash
echo "GET_APP_TOKEN_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "${FAIL_TOKEN_MINT:-}" == "1" ]]; then exit 1; fi
printf "export GH_TOKEN='fake-token-%s'\\n" "$2"
printf "export HOS_BOT_LOGIN='fake-bot[bot]'\\n"
"""

# rev-parse --abbrev-ref HEAD -> "current-branch"; remote get-url origin -> repo URL;
# fetch -> honors GIT_FETCH_FAIL; rev-list --count -> GIT_BEHIND_COUNT (default 0);
# merge -> honors GIT_MERGE_FAIL (merge --abort always succeeds);
# push <url> <refspec> -> captured, honors GIT_PUSH_FAIL.
GIT_STUB = """#!/usr/bin/env bash
echo "GIT_CALLED_WITH:$*" >> "$CAPTURE_FILE"
i=0
if [[ "$1" == "-C" ]]; then i=2; fi
sub="${@:$((i+1)):1}"
case "$sub" in
  remote) echo "https://github.com/test-owner/test-repo.git" ;;
  rev-parse) echo "current-branch" ;;
  fetch) if [[ "${GIT_FETCH_FAIL:-}" == "1" ]]; then exit 1; fi ;;
  rev-list) echo "${GIT_BEHIND_COUNT:-0}" ;;
  merge)
    if [[ "$*" == *"--abort"* ]]; then exit 0; fi
    if [[ "${GIT_MERGE_FAIL:-}" == "1" ]]; then exit 1; fi
    ;;
  push) if [[ "${GIT_PUSH_FAIL:-}" == "1" ]]; then exit 1; fi ;;
esac
exit 0
"""

GH_STUB = """#!/usr/bin/env bash
echo "GH_CALLED_WITH:$*" >> "$CAPTURE_FILE"
if [[ "$1" == "pr" && "$2" == "create" ]]; then
    if [[ "${GH_FAIL:-}" == "1" ]]; then exit 1; fi
    echo "https://github.com/test-owner/test-repo/pull/999"
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
        self.script = self.bootstrap_dir / "submit_pr.sh"
        shutil.copy(SUBMIT_PR_SH, self.script)
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
        self.body_file.write_text("pr body\nwith a newline\n")

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


BASE_ARGS = ["--title", "t", "--base", "main"]


# --------------------------------------------------------------------------- #
# Argument validation
# --------------------------------------------------------------------------- #


def test_missing_title(h):
    result = h.run(["--body-file", str(h.body_file), "--base", "main", "--app", "worker"])
    assert result.returncode != 0
    assert "--title" in result.stderr


def test_missing_body_file_flag(h):
    result = h.run(["--title", "t", "--base", "main", "--app", "worker"])
    assert result.returncode != 0
    assert "--body-file" in result.stderr


def test_body_file_does_not_exist(h):
    result = h.run(["--title", "t", "--body-file", str(h.tmp / "missing.md"), "--base", "main", "--app", "worker"])
    assert result.returncode != 0
    assert "not found" in result.stderr


def test_missing_base(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--app", "worker"])
    assert result.returncode != 0
    assert "--base" in result.stderr


def test_missing_app(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--base", "main"])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_invalid_app_value(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "bogus"])
    assert result.returncode != 0
    assert "--app" in result.stderr


def test_rejects_inline_body(h):
    result = h.run(["--title", "t", "--body", "inline text", "--base", "main", "--app", "worker"])
    assert result.returncode != 0
    assert "--body-file" in result.stderr


# --------------------------------------------------------------------------- #
# Human-proxy authorization gate
# --------------------------------------------------------------------------- #


def test_app_human_without_confirmed_fails(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "human"])
    assert result.returncode != 0
    assert "--confirmed" in result.stderr
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap


def test_app_human_with_confirmed_proceeds(h):
    result = h.run([
        "--title", "t", "--body-file", str(h.body_file), "--base", "main",
        "--app", "human", "--confirmed",
    ])
    assert result.returncode == 0, result.stderr
    assert "GET_APP_TOKEN_CALLED_WITH:--app human" in h.capture()


def test_app_worker_does_not_require_confirmed(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"])
    assert result.returncode == 0, result.stderr


def test_app_overseer_does_not_require_confirmed(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "overseer"])
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


def test_head_defaults_to_current_branch(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    push_line = [ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and "refs/heads/" in ln][0]
    assert "HEAD:refs/heads/current-branch" in push_line


def test_explicit_head_used_over_current_branch(h):
    result = h.run([
        "--title", "t", "--body-file", str(h.body_file), "--base", "main",
        "--head", "explicit-branch", "--app", "worker",
    ])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    push_line = [ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and "refs/heads/" in ln][0]
    assert "HEAD:refs/heads/explicit-branch" in push_line


def test_happy_path_pushes_creates_pr_and_revokes_token(h):
    result = h.run([
        "--title", "My PR", "--body-file", str(h.body_file), "--base", "main",
        "--head", "feature-x", "--app", "worker",
    ])
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "https://github.com/test-owner/test-repo/pull/999"

    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH:--app worker" in cap
    push_line = [ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and "refs/heads/" in ln][0]
    assert "x-access-token:fake-token-worker@github.com/test-owner/test-repo.git" in push_line
    assert "HEAD:refs/heads/feature-x" in push_line
    gh_line = [ln for ln in cap.splitlines() if ln.startswith("GH_CALLED_WITH")][0]
    assert "--repo test-owner/test-repo" in gh_line
    assert "--base main" in gh_line
    assert "--head feature-x" in gh_line
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap


def test_token_mint_failure_aborts_before_push(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"FAIL_TOKEN_MINT": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "push" not in cap


def test_push_failure_aborts_before_pr_create_but_revokes(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_PUSH_FAIL": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "GH_CALLED_WITH" not in cap
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap


def test_gh_pr_create_failure_still_revokes_token(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GH_FAIL": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "CURL_CALLED_WITH:-sf -X DELETE" in cap


# --------------------------------------------------------------------------- #
# Merge-from-base guard (#1162)
# --------------------------------------------------------------------------- #


def test_fetches_base_before_pushing(h):
    result = h.run(["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"])
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    fetch_line = [ln for ln in cap.splitlines() if ln.startswith("GIT_CALLED_WITH") and " fetch " in ln][0]
    assert "fetch origin main" in fetch_line


def test_up_to_date_base_does_not_merge(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_BEHIND_COUNT": "0"},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    assert "merge" not in cap


def test_behind_base_merges_before_push(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_BEHIND_COUNT": "3"},
    )
    assert result.returncode == 0, result.stderr
    cap = h.capture()
    calls = cap.splitlines()
    merge_line = [ln for ln in calls if ln.startswith("GIT_CALLED_WITH") and " merge " in ln][0]
    assert "origin/main" in merge_line
    push_idx = [i for i, ln in enumerate(calls) if "refs/heads/" in ln][0]
    merge_idx = calls.index(merge_line)
    assert merge_idx < push_idx, "merge must happen before push"


def test_merge_conflict_aborts_and_does_not_push(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_BEHIND_COUNT": "3", "GIT_MERGE_FAIL": "1"},
    )
    assert result.returncode != 0
    assert "conflict" in result.stderr.lower()
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
    assert not any("refs/heads/" in ln for ln in cap.splitlines())
    assert any("--abort" in ln for ln in cap.splitlines())


def test_fetch_failure_aborts_before_token_mint(h):
    result = h.run(
        ["--title", "t", "--body-file", str(h.body_file), "--base", "main", "--app", "worker"],
        env_overrides={"GIT_FETCH_FAIL": "1"},
    )
    assert result.returncode != 0
    cap = h.capture()
    assert "GET_APP_TOKEN_CALLED_WITH" not in cap
