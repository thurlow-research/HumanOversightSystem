"""Tests for bootstrap/lib/comment_format_check.sh (#1270).

overseer.md's "Executive summary" / §8.2 format contract was stated in prose
only and never checked at either write path — a 35-PR sample found it
present just 37% of the time. This shared library closes that gap for both
bootstrap/post_comment.sh and bootstrap/post_review_thread.sh so they cannot
drift apart the way #1155's @path guard (duplicated, not shared) could have.

Strategy: source the real library into a throwaway bash process (via `bash
-c`) and call its functions directly against a scratch body file. No stubs
for git/gh/curl needed — these functions have no side effects beyond
HOS_CFC_REASON and their return code.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "bootstrap" / "lib" / "comment_format_check.sh"


def _run(function: str, body_file: Path, extra_args: str = "", env_overrides=None):
    script = f"""
set -uo pipefail
source "{LIB}"
warn() {{ echo "WARN:$*" >&2; }}
{function} "{body_file}" {extra_args}
rc=$?
echo "RC=$rc"
echo "REASON=$HOS_CFC_REASON"
"""
    env = {"PATH": "/usr/bin:/bin"}
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [BASH, "-c", script], capture_output=True, text=True, timeout=15, env=env
    )


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "body.md"
    p.write_text(content)
    return p


# --------------------------------------------------------------------------- #
# hos_cfc_check_at_path_literal — the generalised #1155 guard
# --------------------------------------------------------------------------- #


def test_at_path_literal_rejected(tmp_path):
    body = _write(tmp_path, "@/tmp/claude/some_comment.md")
    result = _run("hos_cfc_check_at_path_literal", body)
    assert "RC=1" in result.stdout
    assert "#1155" in result.stdout


def test_normal_content_accepted(tmp_path):
    body = _write(tmp_path, "just a normal comment\nwith text\n")
    result = _run("hos_cfc_check_at_path_literal", body)
    assert "RC=0" in result.stdout


# --------------------------------------------------------------------------- #
# hos_cfc_check_overseer_format — the #1099/#1268 executive-summary contract
# --------------------------------------------------------------------------- #

VALID_BODY = (
    "**Executive summary:** Auto-merged — tier within ceiling, all checks "
    "green. Expected action: **NO ACTION**. Composite 0.0056/LOW. "
    "Not verified this run: `static_analysis` (bandit not installed)."
)


def test_pass_path_accepted(tmp_path):
    body = _write(tmp_path, VALID_BODY)
    result = _run("hos_cfc_check_overseer_format", body)
    assert "RC=0" in result.stdout


def test_missing_summary_rejected(tmp_path):
    body = _write(tmp_path, "no summary heading here at all\n")
    result = _run("hos_cfc_check_overseer_format", body)
    assert "RC=1" in result.stdout
    assert "REASON=missing the leading" in result.stdout


def test_summary_not_leading_rejected(tmp_path):
    body = _write(
        tmp_path,
        "some preamble first\n" + VALID_BODY,
    )
    result = _run("hos_cfc_check_overseer_format", body)
    assert "RC=1" in result.stdout
    assert "must lead the comment" in result.stdout


def test_missing_enum_rejected(tmp_path):
    body = _write(
        tmp_path,
        "**Executive summary:** something happened. Not verified this run: nothing.",
    )
    result = _run("hos_cfc_check_overseer_format", body)
    assert "RC=1" in result.stdout
    assert "missing a bolded expected-action enum value" in result.stdout


def test_multiple_enum_values_rejected(tmp_path):
    body = _write(
        tmp_path,
        "**Executive summary:** foo **APPROVE** bar **OTHER**. "
        "Not verified this run: nothing.",
    )
    result = _run("hos_cfc_check_overseer_format", body)
    assert "RC=1" in result.stdout
    assert "exactly one is required" in result.stdout


def test_missing_not_verified_clause_rejected(tmp_path):
    body = _write(
        tmp_path,
        "**Executive summary:** foo **APPROVE** bar, no clause here.",
    )
    result = _run("hos_cfc_check_overseer_format", body)
    assert "RC=1" in result.stdout
    assert 'missing a "not verified" clause' in result.stdout


def test_not_verified_clause_case_insensitive(tmp_path):
    body = _write(
        tmp_path,
        "**Executive summary:** foo **APPROVE** bar. NOT VERIFIED THIS RUN: nothing.",
    )
    result = _run("hos_cfc_check_overseer_format", body)
    assert "RC=0" in result.stdout


# --------------------------------------------------------------------------- #
# hos_cfc_enforce_overseer_format — the mode-gated orchestration wrapper
# --------------------------------------------------------------------------- #


def test_enforce_wrapper_na_for_worker(tmp_path):
    body = _write(tmp_path, "no summary at all")
    result = _run("hos_cfc_enforce_overseer_format", body, extra_args='"worker" warn')
    assert "RC=0" in result.stdout
    assert "WARN:" not in result.stderr


def test_enforce_wrapper_na_for_human(tmp_path):
    body = _write(tmp_path, "no summary at all")
    result = _run("hos_cfc_enforce_overseer_format", body, extra_args='"human" warn')
    assert "RC=0" in result.stdout


def test_enforce_wrapper_advisory_mode_logs_and_passes(tmp_path):
    body = _write(tmp_path, "no summary at all")
    result = _run("hos_cfc_enforce_overseer_format", body, extra_args='"overseer" warn')
    assert "RC=0" in result.stdout
    assert "WARN:comment format violation (#1270, advisory" in result.stderr
    assert "HOS_COMMENT_FORMAT_MODE=enforce" in result.stderr


def test_enforce_wrapper_enforce_mode_blocks(tmp_path):
    body = _write(tmp_path, "no summary at all")
    result = _run(
        "hos_cfc_enforce_overseer_format",
        body,
        extra_args='"overseer" warn',
        env_overrides={"HOS_COMMENT_FORMAT_MODE": "enforce"},
    )
    assert "RC=1" in result.stdout
    assert "REASON=missing the leading" in result.stdout


def test_enforce_wrapper_passes_valid_body_in_enforce_mode(tmp_path):
    body = _write(tmp_path, VALID_BODY)
    result = _run(
        "hos_cfc_enforce_overseer_format",
        body,
        extra_args='"overseer" warn',
        env_overrides={"HOS_COMMENT_FORMAT_MODE": "enforce"},
    )
    assert "RC=0" in result.stdout
