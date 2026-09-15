"""
Tests for bootstrap/invoke_agent.sh — the L3 wrapper for the deterministic
agent-invocation primitive (#1643 W1).

docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md §3.9 + §9's slice
gate: "All drive main(argv=[...], repo_root=tmp_path) in-process except the
wrapper tests, which shell out." This file shells out to the real script,
against the real repo checkout (there is no --repo-root flag on this
surface — the L2 module resolves its own repo root from `__file__`, and L3
adds nothing of its own), using `--not-applicable` to avoid any dependency
on a real `claude` binary or network access: no process is launched on that
path (§4.5), so these tests exercise the wrapper's passthrough contract
without needing the vendor CLI installed.

The classifier matrix itself (every AD-4/A1-A9 row) is L2's test obligation,
driven in-process in test_agent_invoke_cli.py. This file only tests what is
specific to the L3 boundary: fixed argv, byte-for-byte passthrough, the
python3-missing operational failure, and that stderr is never suppressed
(#1523).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"
REPO_ROOT = Path(__file__).resolve().parents[2]
INVOKE_AGENT_SH = REPO_ROOT / "bootstrap" / "invoke_agent.sh"
CLI_MODULE = REPO_ROOT / "scripts" / "automation" / "agent_invoke_cli.py"

# A real shipped agent, guaranteed present in this repo, used only via
# --not-applicable so no `claude` process is ever launched.
REAL_AGENT = "code-reviewer"


def _run(args: list[str], *, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(INVOKE_AGENT_SH), *args],
        cwd=str(REPO_ROOT),
        env=env if env is not None else os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_not_applicable_passthrough_exit_0_and_one_json_document():
    result = _run(["--agent", REAL_AGENT, "--not-applicable", "test reason"])
    assert result.returncode == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one stdout line, got: {result.stdout!r}"
    doc = json.loads(lines[0])
    assert doc["applicability"] == "not_applicable"
    assert doc["applicability_reason"] == "test reason"
    assert doc["agent"] == REAL_AGENT
    assert doc["outcome"] == "completed"
    assert doc["verdict"] == "approve"


def test_forbidden_flag_exit_2_no_stdout_document_stderr_names_flag():
    result = _run(["--agent", REAL_AGENT, "--not-applicable", "x", "--settings", "/tmp/x.json"])
    assert result.returncode == 2
    assert result.stdout == ""
    assert "agent_invoke:" in result.stderr
    assert "--settings" in result.stderr


def test_missing_required_flag_exit_2():
    result = _run(["--not-applicable", "x"])  # no --agent
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.strip() != ""


def test_agent_unavailable_is_exit_0_with_a_document_not_a_silent_failure():
    result = _run(["--agent", "no-such-agent-xyz", "--not-applicable", "x"])
    assert result.returncode == 0
    doc = json.loads(result.stdout.splitlines()[0])
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "agent_unavailable"
    assert doc["verdict"] == "error"


def test_python3_missing_is_exit_1_with_stderr_message(tmp_path):
    # A PATH with no python3 on it at all — invoke_agent.sh's own P2 check.
    stub_bin = tmp_path / "stub_bin"
    stub_bin.mkdir()
    env = os.environ.copy()
    env["PATH"] = str(stub_bin)
    result = _run(["--agent", REAL_AGENT, "--not-applicable", "x"], env=env)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "python3" in result.stderr


def test_flags_pass_through_unaltered_dimension_and_binding():
    result = _run(
        [
            "--agent",
            REAL_AGENT,
            "--not-applicable",
            "x",
            "--dimension",
            "security",
            "--binding",
            "core:security/code",
        ]
    )
    assert result.returncode == 0
    doc = json.loads(result.stdout.splitlines()[0])
    assert doc["dimension"] == "security"
    assert doc["binding"] == "core:security/code"
    assert doc["lens"] == "security"


def test_stderr_is_never_suppressed_on_a_usage_error():
    # #1523 — invoke_agent.sh must never redirect or swallow the child's
    # stderr, even on the exit-2 path.
    result = _run(["--agent", "NOT-VALID-NAME", "--not-applicable", "x"])
    assert result.returncode == 2
    assert result.stderr.strip() != ""


@pytest.mark.skipif(shutil.which("python3") is None, reason="direct comparison needs python3")
def test_stdout_is_byte_identical_to_direct_module_invocation():
    wrapper = _run(["--agent", REAL_AGENT, "--not-applicable", "byte-identity check"])
    direct = subprocess.run(
        [
            "python3",
            str(CLI_MODULE),
            "--agent",
            REAL_AGENT,
            "--not-applicable",
            "byte-identity check",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert wrapper.returncode == direct.returncode
    wrapper_doc = json.loads(wrapper.stdout.splitlines()[0])
    direct_doc = json.loads(direct.stdout.splitlines()[0])
    # started_at/ended_at timestamps can legitimately differ by a tick
    # between the two subprocess launches; everything else must match.
    for doc in (wrapper_doc, direct_doc):
        doc["invocation"]["started_at"] = None
        doc["invocation"]["ended_at"] = None
    assert wrapper_doc == direct_doc
