"""
Tests for scripts/automation/agent_invoke_cli.py — the deterministic
agent-invocation primitive, W1 slice gate (#1643).

Per docs/v0.7.0/TECHNICAL-DESIGN-1643-invocation-primitive.md §9.1 (T1.1-
T1.49) and docs/v0.7.0/ADR-1643-deterministic-agent-invocation.md §9.1/§9.2
Amendment 1 (T1.9b, T1.13b, T1.15b, T1.15c, T1.24b). The amended AD-4
classifier table (ADR §9.1's A1-A9) governs wherever it differs from the
technical design's original C1-C8 rows — see the module under test's own
`classify()` docstring.

All tests drive `main(argv=[...], repo_root=tmp_path)` in-process. No real
`claude` binary is ever invoked: `run_capped` is replaced with a spy that
returns a synthetic `ProcResult` (or refuses to be called at all, for the
precondition tests asserting no subprocess launches), and
`shutil.which("claude")` is patched to resolve so P8 doesn't short-circuit
first. `classify()` and `run_capped()` are independently exported (TD §3.1
member 4/5) and are also driven directly for the timeout/reaping tests
(T1.47-T1.49), which need real OS process-group behaviour.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import scripts.automation.agent_invoke_cli as cli

AGENT_NAME = "test-agent"
POSTURE_ID = "review-read-only"

# Verbatim copies of the two committed posture files (contract/dimensions/
# postures/review-read-only.{settings,hos}.json) — duplicated here rather
# than read from the live repo tree so these tests stay self-contained and a
# corruption test can mutate a field without touching the real files.
_SETTINGS = {
    "permissions": {
        "defaultMode": "manual",
        "disableBypassPermissionsMode": "disable",
        "additionalDirectories": [],
        "allow": ["Read", "Grep", "Glob", "Bash(git diff *)"],
        "deny": ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Bash(gh *)"],
    }
}
_SIDECAR = {
    "schema": "hos.invocation-posture",
    "schema_version": 1,
    "id": POSTURE_ID,
    "description": "Filesystem read + local read-only shell.",
    "permission_mode": "manual",
    "allowed_tools": ["Read", "Grep", "Glob", "Bash"],
    "disallowed_tools": ["Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task"],
}


def _write_agent(root: Path, name: str, *, declared_name: str | None = None) -> Path:
    p = root / ".claude" / "agents" / f"{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    decl = name if declared_name is None else declared_name
    p.write_text(f"---\nname: {decl}\nmodel: sonnet\ntools:\n  - Read\n---\nDo the review.\n")
    return p


def _write_posture(
    root: Path,
    posture_id: str = POSTURE_ID,
    *,
    settings: dict | None = None,
    sidecar: dict | None = None,
    write_settings: bool = True,
    write_sidecar: bool = True,
    settings_text: str | None = None,
) -> None:
    d = root / "contract" / "dimensions" / "postures"
    d.mkdir(parents=True, exist_ok=True)
    if write_settings:
        text = settings_text if settings_text is not None else json.dumps(settings or _SETTINGS)
        (d / f"{posture_id}.settings.json").write_text(text)
    if write_sidecar:
        (d / f"{posture_id}.hos.json").write_text(json.dumps(sidecar or _SIDECAR))


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    _write_agent(tmp_path, AGENT_NAME)
    _write_posture(tmp_path)
    (tmp_path / "input.txt").write_text("please review this diff")
    return tmp_path


class _Recorder:
    """Reads captured stdout/stderr exactly once (capsys.readouterr() drains
    the buffers) and stashes stderr on `self` so a caller that needs both
    the document AND a stderr assertion (e.g. T1.6's usage-limit line)
    doesn't lose the text to a second, now-empty read. A typed class
    attribute rather than a function attribute so mypy can check
    `.last_err`'s type at every access."""

    def __init__(self) -> None:
        self.last_err: str = ""

    def __call__(self, capsys) -> dict:
        captured = capsys.readouterr()
        self.last_err = captured.err
        lines = [line for line in captured.out.splitlines() if line.strip()]
        assert len(lines) == 1, f"expected exactly one stdout line, got: {captured.out!r}"
        return json.loads(lines[0])


_record = _Recorder()


class _RunCappedSpy:
    """Stands in for run_capped: returns a fixed ProcResult and records
    every call's arguments, so launch-contract assertions (T1.41-T1.46) and
    'no subprocess launched' assertions (T1.25-T1.40) can both use it."""

    def __init__(self, result: cli.ProcResult | None = None):
        self.result = result
        self.calls: list[dict] = []

    def __call__(self, argv, *, stdin_bytes, cwd, timeout_s, grace_s):
        self.calls.append(
            {
                "argv": argv,
                "stdin_bytes": stdin_bytes,
                "cwd": cwd,
                "timeout_s": timeout_s,
                "grace_s": grace_s,
            }
        )
        if self.result is None:
            raise AssertionError("run_capped must not be called on this path")
        return self.result


@pytest.fixture
def claude_available(monkeypatch):
    """P8 must pass (`shutil.which('claude')` resolves) without a real
    `claude` binary on PATH, so run_capped's spy is what actually answers
    the invocation."""
    monkeypatch.setattr(
        cli.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )
    monkeypatch.setattr(cli, "_capture_cli_version", lambda: "2.1.271")


def _clean_envelope(**overrides) -> dict:
    """probe A's shape (ADR-1643 TD §0.2), with `result` a clean approve
    payload. Every field in KNOWN_ENVELOPE_TOP_LEVEL_FIELDS is present so a
    field-completeness bug can't hide behind an accidentally-absent key."""
    base = {
        "duration_api_ms": 2009,
        "stop_reason": "end_turn",
        "session_id": "5063fa1e-0000-0000-0000-000000000000",
        "total_cost_usd": 0.1255,
        "usage": {"input_tokens": 2, "output_tokens": 9},
        "modelUsage": {"claude-sonnet-5": {"costUSD": 0.1}},
        "permission_denials": [],
        "terminal_reason": "completed",
        "fast_mode_state": "off",
        "fast_mode_disabled_reason": "sdk_opt_in_required",
        "subagent_stats": {
            "refused": {"depth_limit": 0, "concurrency_limit": 0, "budget": 0},
        },
        "is_error": False,
        "num_turns": 1,
        "subtype": "success",
        "api_error_status": None,
        "result": json.dumps({"verdict": "approve", "findings": [], "summary": "clean"}),
        "ttft_ms": 1281,
        "type": "result",
        "duration_ms": 1303,
        "uuid": "d7ee8986-0000-0000-0000-000000000000",
        "ttft_stream_ms": 718,
        "time_to_request_ms": 53,
        "first_content_frame_ms": 718,
        "queued_turn_count": 0,
        "result_index": 0,
    }
    base.update(overrides)
    return base


def _proc(
    envelope: dict | None = None, *, rc: int = 0, timed_out: bool = False, raw: str | None = None
):
    text = raw if raw is not None else json.dumps(envelope)
    return cli.ProcResult(
        rc=rc,
        timed_out=timed_out,
        stdout_bytes=text.encode("utf-8"),
        stderr_bytes=b"",
        duration_ms=100,
    )


def _base_argv(root: Path, **extra) -> list[str]:
    argv = [
        "--agent",
        AGENT_NAME,
        "--posture",
        POSTURE_ID,
        "--input-file",
        str(root / "input.txt"),
    ]
    for key, value in extra.items():
        argv += [f"--{key.replace('_', '-')}", str(value)]
    return argv


def _invoke_with_envelope(
    root, monkeypatch, capsys, envelope=None, *, rc=0, timed_out=False, raw=None
):
    proc = _proc(envelope, rc=rc, timed_out=timed_out, raw=raw)
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(proc))
    rc_code = cli.main(_base_argv(root), repo_root=root)
    doc = _record(capsys)
    return rc_code, doc


# --------------------------------------------------------------------------- #
# T1.1-T1.24 — the AD-4 classifier table (amended, ADR-1643 §9.1)
# --------------------------------------------------------------------------- #


def test_T1_1_timeout(repo_root, monkeypatch, capsys, claude_available):
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, timed_out=True, raw="anything")
    assert rc == 0
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "timeout"
    assert doc["verdict"] == "error"


def test_T1_2_empty_stdout(repo_root, monkeypatch, capsys, claude_available):
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, raw="")
    assert doc["outcome_detail"] == "unparseable"


def test_T1_3_two_json_objects(repo_root, monkeypatch, capsys, claude_available):
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, raw="{}{}")
    assert doc["outcome_detail"] == "unparseable"


def test_T1_4_prose_prefixed_not_tolerated(repo_root, monkeypatch, capsys, claude_available):
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, raw='notes\n{"a":1}')
    assert doc["outcome_detail"] == "unparseable"


def test_T1_5_vf1_probe_r_verbatim_is_the_most_important_test(
    repo_root, monkeypatch, capsys, claude_available
):
    envelope = _clean_envelope(
        is_error=True,
        subtype="success",
        terminal_reason="api_error",
        api_error_status=404,
        result="There's an issue with the selected model (no-such-model-xyz).",
    )
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope, rc=1)
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "api_error"
    assert doc["verdict"] == "error"


def test_T1_6_usage_limit_detail_and_stderr_line(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(terminal_reason="usage_limit")
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome_detail"] == "usage_limit"
    assert "usage limit reached" in _record.last_err


def test_T1_7_refusal(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(terminal_reason="refusal")
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome_detail"] == "refusal"


def test_T1_8_max_turns(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(terminal_reason="max_turns")
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome_detail"] == "max_turns"


def test_T1_9_unknown_bad_terminal_reason_fails_closed_by_default(
    repo_root, monkeypatch, capsys, claude_available
):
    envelope = _clean_envelope(terminal_reason="some_future_reason_nobody_wrote")
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "terminal_reason:some_future_reason_nobody_wrote"


def test_T1_9b_terminal_reason_missing(repo_root, monkeypatch, capsys, claude_available):
    """ADR-1643 §9.2(b) — terminal_reason must be PRESENT."""
    envelope = _clean_envelope()
    del envelope["terminal_reason"]
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "terminal_reason_missing"
    assert doc["verdict"] == "error"


def test_T1_10_api_error_with_not_logged_in_is_not_authenticated(
    repo_root, monkeypatch, capsys, claude_available
):
    envelope = _clean_envelope(
        terminal_reason="api_error", result="Not logged in · Please run /login"
    )
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome_detail"] == "not_authenticated"


def test_T1_11_permission_denials_probe_k_shape(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(
        permission_denials=[
            {
                "tool_name": "Bash",
                "tool_use_id": "toolu_01",
                "tool_input": {"command": "touch canary.txt"},
            }
        ],
        is_error=False,
        terminal_reason="completed",
    )
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "permission_denied"


def test_T1_12_refused_all_zero_probe_a_shape_is_completed(
    repo_root, monkeypatch, capsys, claude_available
):
    envelope = _clean_envelope(
        subagent_stats={"refused": {"depth_limit": 0, "concurrency_limit": 0, "budget": 0}}
    )
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "completed"


def test_T1_13_refused_nonzero(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(
        subagent_stats={"refused": {"depth_limit": 0, "concurrency_limit": 2, "budget": 0}}
    )
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "refused"


def test_T1_13b_refused_quantifies_over_values_not_a_known_key_set(
    repo_root, monkeypatch, capsys, claude_available
):
    """ADR-1643 §9.1 rule 1 — a key-allowlisted implementation passes this
    envelope and fails this test."""
    envelope = _clean_envelope(
        subagent_stats={"refused": {"depth_limit": 0, "some_future_limit": 7}}
    )
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "refused"


def test_T1_14_refused_scalar_zero(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(subagent_stats={"refused": 0})
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "completed"


def test_T1_15_refused_string_is_shape_violation(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(subagent_stats={"refused": "some string"})
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome_detail"] == "envelope_shape_violation"


def test_T1_15b_refused_null_is_not_zero(repo_root, monkeypatch, capsys, claude_available):
    """ADR-1643 §9.1 rule 3 — the NaN-to-null wire shape of a brand new
    refusal reason is never read as zero."""
    envelope = _clean_envelope(subagent_stats={"refused": {"depth_limit": 0, "budget": None}})
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "envelope_shape_violation"


def test_T1_15c_refused_boolean_is_not_an_int(repo_root, monkeypatch, capsys, claude_available):
    """ADR-1643 §9.1 rule 2 — the Python boolean-is-an-int trap."""
    envelope = _clean_envelope(subagent_stats={"refused": {"budget": False}})
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "envelope_shape_violation"


def test_T1_16_subagent_stats_absent_is_harmless(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope()
    del envelope["subagent_stats"]
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "completed"


def test_T1_17_nonzero_exit_code_is_crash(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope()
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope, rc=2)
    assert doc["outcome_detail"] == "crash"


def test_T1_18_payload_verdict_not_in_domain(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(result=json.dumps({"verdict": "maybe", "findings": []}))
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome_detail"] == "schema_violation"


def test_T1_19_finding_with_no_files_and_no_file(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(
        result=json.dumps(
            {
                "verdict": "request_changes",
                "findings": [{"severity": "high", "category": "x", "description": "d", "fix": "f"}],
            }
        )
    )
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome_detail"] == "schema_violation"


def test_T1_20_payload_asserting_applicability_is_schema_violation(
    repo_root, monkeypatch, capsys, claude_available
):
    envelope = _clean_envelope(
        result=json.dumps({"verdict": "approve", "findings": [], "applicability": "not_applicable"})
    )
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome_detail"] == "schema_violation"


def test_T1_21_single_json_fence_is_stripped(repo_root, monkeypatch, capsys, claude_available):
    inner = json.dumps({"verdict": "approve", "findings": []})
    envelope = _clean_envelope(result=f"```json\n{inner}\n```")
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "completed"


def _payload_envelope(result_obj: dict) -> dict:
    return _clean_envelope(result=json.dumps(result_obj))


def test_extract_payload_files_only_populates_file_from_first_element():
    """Risk-assessor inspection item #2 — positive-path coverage for the
    files<->file merge; T1.19 only tested the negative (neither present)
    case."""
    envelope = _payload_envelope(
        {
            "verdict": "request_changes",
            "findings": [
                {
                    "severity": "high",
                    "category": "x",
                    "files": ["a.py", "b.py"],
                    "description": "d",
                    "fix": "f",
                }
            ],
        }
    )
    payload = cli._extract_payload(envelope)
    assert payload is not None
    finding = payload["findings"][0]
    assert finding["files"] == ["a.py", "b.py"]
    assert finding["file"] == "a.py"


def test_extract_payload_file_only_populates_files_list():
    envelope = _payload_envelope(
        {
            "verdict": "request_changes",
            "findings": [
                {"severity": "high", "category": "x", "file": "only.py", "description": "d"}
            ],
        }
    )
    payload = cli._extract_payload(envelope)
    assert payload is not None
    finding = payload["findings"][0]
    assert finding["file"] == "only.py"
    assert finding["files"] == ["only.py"]


def test_extract_payload_type_without_category_mirrors_both_ways():
    envelope = _payload_envelope(
        {
            "verdict": "request_changes",
            "findings": [{"severity": "high", "type": "input-validation", "file": "a.py"}],
        }
    )
    payload = cli._extract_payload(envelope)
    assert payload is not None
    finding = payload["findings"][0]
    assert finding["type"] == "input-validation"
    assert finding["category"] == "input-validation"


def test_extract_payload_category_without_type_mirrors_both_ways():
    envelope = _payload_envelope(
        {
            "verdict": "request_changes",
            "findings": [{"severity": "high", "category": "input-validation", "file": "a.py"}],
        }
    )
    payload = cli._extract_payload(envelope)
    assert payload is not None
    finding = payload["findings"][0]
    assert finding["category"] == "input-validation"
    assert finding["type"] == "input-validation"


def test_extract_payload_defaults_line_to_none_and_attacks_to_empty():
    envelope = _payload_envelope(
        {
            "verdict": "approve",
            "findings": [{"severity": "low", "category": "x", "file": "a.py"}],
        }
    )
    payload = cli._extract_payload(envelope)
    assert payload is not None
    assert payload["findings"][0]["line"] is None
    assert payload["attacks"] == []


def test_T1_22_double_nested_fence_is_schema_violation(
    repo_root, monkeypatch, capsys, claude_available
):
    inner = json.dumps({"verdict": "approve", "findings": []})
    envelope = _clean_envelope(result=f"```json\n```json\n{inner}\n```\n```")
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome_detail"] == "schema_violation"


def test_T1_23_subtype_is_never_read(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope(subtype="failure")
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "completed"


def test_T1_24_unknown_top_level_field_recorded_not_blocking(
    repo_root, monkeypatch, capsys, claude_available
):
    envelope = _clean_envelope(brand_new_telemetry=1)
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "completed"
    assert "brand_new_telemetry" in doc["invocation"]["envelope_unknown_fields"]


def test_T1_24b_unknown_field_never_masks_a_real_failure(
    repo_root, monkeypatch, capsys, claude_available
):
    envelope = _clean_envelope(
        brand_new_telemetry=1,
        permission_denials=[{"tool_name": "Bash"}],
    )
    rc, doc = _invoke_with_envelope(repo_root, monkeypatch, capsys, envelope)
    assert doc["outcome"] == "invocation_failed"
    assert doc["outcome_detail"] == "permission_denied"
    assert "brand_new_telemetry" in doc["invocation"]["envelope_unknown_fields"]


# --------------------------------------------------------------------------- #
# T1.25-T1.40 — preconditions and posture
# --------------------------------------------------------------------------- #


def test_T1_25_agent_file_absent(repo_root, monkeypatch, capsys, claude_available):
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    cli.main(
        [
            "--agent",
            "no-such-agent",
            "--posture",
            POSTURE_ID,
            "--input-file",
            str(repo_root / "input.txt"),
        ],
        repo_root=repo_root,
    )
    doc = _record(capsys)
    assert doc["outcome_detail"] == "agent_unavailable"


def test_T1_26_agent_file_empty(repo_root, monkeypatch, capsys, claude_available):
    (repo_root / ".claude" / "agents" / "empty-agent.md").write_text("")
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    cli.main(_base_argv(repo_root, agent="empty-agent"), repo_root=repo_root)
    doc = _record(capsys)
    assert doc["outcome_detail"] == "agent_unavailable"


def test_T1_27_agent_frontmatter_name_mismatch(repo_root, monkeypatch, capsys, claude_available):
    _write_agent(repo_root, "mismatched", declared_name="something-else")
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    cli.main(_base_argv(repo_root, agent="mismatched"), repo_root=repo_root)
    doc = _record(capsys)
    assert doc["outcome_detail"] == "agent_unavailable"


def test_T1_28_general_purpose_builtin_cannot_be_reached(
    repo_root, monkeypatch, capsys, claude_available
):
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    cli.main(_base_argv(repo_root, agent="general-purpose"), repo_root=repo_root)
    doc = _record(capsys)
    assert doc["outcome_detail"] == "agent_unavailable"


def test_T1_29_agents_flag_forbidden(repo_root, capsys):
    argv = _base_argv(repo_root) + ["--agents", "{}"]
    rc = cli.main(argv, repo_root=repo_root)
    assert rc == 2
    err = capsys.readouterr().err
    assert "--agents" in err


def test_T1_30_permission_mode_forbidden(repo_root, capsys):
    argv = _base_argv(repo_root) + ["--permission-mode", "bypassPermissions"]
    rc = cli.main(argv, repo_root=repo_root)
    assert rc == 2
    assert "--permission-mode" in capsys.readouterr().err


def test_T1_31_output_format_forbidden(repo_root, capsys):
    argv = _base_argv(repo_root) + ["--output-format", "text"]
    rc = cli.main(argv, repo_root=repo_root)
    assert rc == 2
    assert "--output-format" in capsys.readouterr().err


def test_T1_32_settings_forbidden(repo_root, capsys):
    argv = _base_argv(repo_root) + ["--settings", "x"]
    rc = cli.main(argv, repo_root=repo_root)
    assert rc == 2
    assert "--settings" in capsys.readouterr().err


def test_T1_33_posture_settings_malformed_json_no_subprocess(
    repo_root, monkeypatch, capsys, claude_available
):
    _write_posture(repo_root, settings_text="{not json")
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    cli.main(_base_argv(repo_root), repo_root=repo_root)
    doc = _record(capsys)
    assert doc["outcome_detail"] == "posture_invalid"


def test_T1_34_posture_sidecar_missing_bypass_key(repo_root, monkeypatch, capsys, claude_available):
    settings = json.loads(json.dumps(_SETTINGS))
    del settings["permissions"]["disableBypassPermissionsMode"]
    _write_posture(repo_root, settings=settings)
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    cli.main(_base_argv(repo_root), repo_root=repo_root)
    doc = _record(capsys)
    assert doc["outcome_detail"] == "posture_invalid"


def test_T1_35_allowed_disallowed_overlap(repo_root, monkeypatch, capsys, claude_available):
    sidecar = json.loads(json.dumps(_SIDECAR))
    sidecar["allowed_tools"] = ["Read", "Write"]
    _write_posture(repo_root, sidecar=sidecar)
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    cli.main(_base_argv(repo_root), repo_root=repo_root)
    doc = _record(capsys)
    assert doc["outcome_detail"] == "posture_invalid"


def test_T1_36_disallowed_tool_absent_from_deny(repo_root, monkeypatch, capsys, claude_available):
    sidecar = json.loads(json.dumps(_SIDECAR))
    sidecar["disallowed_tools"] = ["Write", "SomethingNotInDeny"]
    _write_posture(repo_root, sidecar=sidecar)
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    cli.main(_base_argv(repo_root), repo_root=repo_root)
    doc = _record(capsys)
    assert doc["outcome_detail"] == "posture_invalid"


def test_T1_37_unknown_posture_name_is_usage_error(repo_root, capsys):
    argv = _base_argv(repo_root, posture="no-such-posture")
    # rebuild argv manually since _base_argv would replace --posture value
    argv = [
        "--agent",
        AGENT_NAME,
        "--posture",
        "no-such-posture",
        "--input-file",
        str(repo_root / "input.txt"),
    ]
    rc = cli.main(argv, repo_root=repo_root)
    assert rc == 2


def test_output_file_is_byte_identical_to_stdout(repo_root, monkeypatch, capsys, tmp_path):
    """TD-D2: `--output-file` is a copy of stdout, never a second
    rendering. `print(text)` would append its own trailing newline
    independently of a `write_text(text)` call with none — this test fails
    if that asymmetry regresses."""
    envelope = _clean_envelope()
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(_proc(envelope)))
    monkeypatch.setattr(
        cli.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )
    monkeypatch.setattr(cli, "_capture_cli_version", lambda: "2.1.271")
    out_path = tmp_path / "result.json"
    argv = _base_argv(repo_root, **{"output-file": str(out_path)})
    rc = cli.main(argv, repo_root=repo_root)
    captured_stdout = capsys.readouterr().out.encode("utf-8")
    assert rc == 0
    assert out_path.read_bytes() == captured_stdout


def test_output_file_smoke_written_and_valid_json(repo_root, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    out_path = tmp_path / "not_applicable.json"
    argv = ["--agent", AGENT_NAME, "--not-applicable", "x", "--output-file", str(out_path)]
    rc = cli.main(argv, repo_root=repo_root)
    capsys.readouterr()
    assert rc == 0
    assert out_path.is_file()
    doc = json.loads(out_path.read_bytes())
    assert doc["applicability"] == "not_applicable"


def test_compound_agent_unavailable_takes_priority_over_missing_posture(
    repo_root, monkeypatch, capsys
):
    """Ordering ruling (risk-assessor inspection item #3 / code-reviewer
    suggestion): TD §3.4 places P3/P4 (agent resolution) before P5/P6
    (posture, input-file). This module now checks --posture/--input-file
    "required unless --not-applicable" AFTER P3/P4, not before — so a
    caller who gets both --agent and --posture wrong learns about the
    agent problem via a document (§3.3: "a silence is never a result"),
    not a bare exit-2 usage error that never mentions --posture at all."""
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    rc = cli.main(["--agent", "no-such-agent-xyz"], repo_root=repo_root)
    assert rc == 0
    doc = _record(capsys)
    assert doc["outcome_detail"] == "agent_unavailable"


def test_T1_38_timeout_zero_is_usage_error(repo_root, capsys):
    argv = _base_argv(repo_root) + ["--timeout", "0"]
    rc = cli.main(argv, repo_root=repo_root)
    assert rc == 2


def test_T1_39_timeout_five_is_usage_error(repo_root, capsys):
    argv = _base_argv(repo_root) + ["--timeout", "5"]
    rc = cli.main(argv, repo_root=repo_root)
    assert rc == 2


def test_T1_39b_timeout_3600_is_usage_error(repo_root, capsys):
    argv = _base_argv(repo_root) + ["--timeout", "3600"]
    rc = cli.main(argv, repo_root=repo_root)
    assert rc == 2


def test_T1_40_require_env_auth_with_no_token_no_subprocess(
    repo_root, monkeypatch, capsys, claude_available
):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    argv = _base_argv(repo_root) + ["--require-env-auth"]
    cli.main(argv, repo_root=repo_root)
    doc = _record(capsys)
    assert doc["outcome_detail"] == "not_authenticated"


# --------------------------------------------------------------------------- #
# T1.41-T1.46 — launch contract
# --------------------------------------------------------------------------- #


def test_T1_41_46_launch_argv_and_stdin_contract(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope()
    spy = _RunCappedSpy(_proc(envelope))
    monkeypatch.setattr(cli, "run_capped", spy)
    cli.main(_base_argv(repo_root), repo_root=repo_root)
    _record(capsys)

    assert len(spy.calls) == 1
    call = spy.calls[0]
    argv = call["argv"]
    assert "--print" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--agent") + 1] == AGENT_NAME
    settings_path = Path(argv[argv.index("--settings") + 1])
    assert settings_path.is_absolute()
    assert settings_path.name == f"{POSTURE_ID}.settings.json"
    assert argv[argv.index("--permission-mode") + 1] == "manual"
    assert "--permission-prompts" in argv
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert "--allowed-tools" in argv
    assert "--disallowed-tools" in argv
    assert "--model" not in argv  # not passed by the caller -> absent (AD-3)

    assert call["cwd"] == repo_root
    assert call["stdin_bytes"] == b"please review this diff"
    # The prompt must appear nowhere in argv.
    joined = " ".join(argv)
    assert "please review this diff" not in joined


def test_cli_version_reaches_the_emitted_document(repo_root, monkeypatch, capsys, claude_available):
    """ADR-1643 §9.2(c) makes `invocation.cli_version` mandatory (diagnostic
    only, never a decision input). Every other test monkeypatches
    `_capture_cli_version` via the `claude_available` fixture but none
    actually read the field back out of the emitted document — this closes
    that gap (ops-reviewer)."""
    envelope = _clean_envelope()
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(_proc(envelope)))
    rc = cli.main(_base_argv(repo_root), repo_root=repo_root)
    doc = _record(capsys)
    assert rc == 0
    assert doc["invocation"]["cli_version"] == "2.1.271"


def test_T1_model_present_when_passed(repo_root, monkeypatch, capsys, claude_available):
    envelope = _clean_envelope()
    spy = _RunCappedSpy(_proc(envelope))
    monkeypatch.setattr(cli, "run_capped", spy)
    argv = _base_argv(repo_root) + ["--model", "opus"]
    cli.main(argv, repo_root=repo_root)
    _record(capsys)
    call_argv = spy.calls[0]["argv"]
    assert call_argv[call_argv.index("--model") + 1] == "opus"


def test_T1_44_start_new_session_true(monkeypatch, tmp_path):
    """T1.44 — with a Popen spy, assert start_new_session=True."""
    captured_kwargs = {}
    real_popen = subprocess.Popen

    def _spy_popen(argv, **kwargs):
        captured_kwargs.update(kwargs)
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(cli.subprocess, "Popen", _spy_popen)
    cli.run_capped(
        [sys.executable, "-c", "pass"],
        stdin_bytes=b"",
        cwd=tmp_path,
        timeout_s=5,
        grace_s=1,
    )
    assert captured_kwargs.get("start_new_session") is True


def test_T1_45_stdin_written_and_closed(tmp_path):
    """T1.45 — input bytes reach the child on stdin and stdin is then
    closed (a child that reads stdin to EOF must complete, not hang)."""
    script = tmp_path / "echo_stdin.py"
    script.write_text("import sys; sys.stdout.write(sys.stdin.read())\n")
    result = cli.run_capped(
        [sys.executable, str(script)],
        stdin_bytes=b"hello-stdin",
        cwd=tmp_path,
        timeout_s=5,
        grace_s=1,
    )
    assert result.timed_out is False
    assert result.stdout_bytes == b"hello-stdin"


def test_T1_46_stdout_and_stderr_are_separate_pipes(tmp_path):
    """T1.46 — stdout and stderr must never be merged into one stream."""
    script = tmp_path / "split_streams.py"
    script.write_text(
        "import sys\n" "sys.stdout.write('ON-STDOUT')\n" "sys.stderr.write('ON-STDERR')\n"
    )
    result = cli.run_capped(
        [sys.executable, str(script)],
        stdin_bytes=b"",
        cwd=tmp_path,
        timeout_s=5,
        grace_s=1,
    )
    assert result.stdout_bytes == b"ON-STDOUT"
    assert result.stderr_bytes == b"ON-STDERR"


# --------------------------------------------------------------------------- #
# T1.47-T1.49 — timeout and reaping (real process-group behaviour)
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_T1_47_sigterm_ignored_then_sigkilled_via_process_group(tmp_path):
    script = tmp_path / "ignore_sigterm.py"
    script.write_text(
        "import signal, time, sys\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "time.sleep(30)\n"
    )
    result = cli.run_capped(
        [sys.executable, str(script)],
        stdin_bytes=b"",
        cwd=tmp_path,
        timeout_s=1,
        grace_s=1,
    )
    assert result.timed_out is True
    # Killed via SIGKILL after the grace period, negative returncode
    # convention for signal termination.
    assert result.rc is not None and result.rc < 0


@pytest.mark.slow
def test_T1_48_grandchild_does_not_survive_the_cap(tmp_path):
    marker = tmp_path / "grandchild.pid"
    script = tmp_path / "spawn_grandchild.py"
    script.write_text(
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', "
        f"'import time; time.sleep(30)'])\n"
        f"open({str(marker)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(30)\n"
    )
    cli.run_capped(
        [sys.executable, str(script)],
        stdin_bytes=b"",
        cwd=tmp_path,
        timeout_s=1,
        grace_s=1,
    )
    time.sleep(0.5)
    grandchild_pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(grandchild_pid, 0)


def test_T1_49_stdout_partial_truncated_to_4kib(tmp_path):
    script = tmp_path / "partial_output.py"
    script.write_text(
        "import sys, time\n"
        "sys.stdout.write('x' * 20000)\n"
        "sys.stdout.flush()\n"
        "time.sleep(30)\n"
    )
    result = cli.run_capped(
        [sys.executable, str(script)],
        stdin_bytes=b"",
        cwd=tmp_path,
        timeout_s=1,
        grace_s=1,
    )
    assert result.timed_out is True
    assert result.stdout_partial is not None
    assert len(result.stdout_partial) <= 4096
    assert result.stdout_bytes == b""


# --------------------------------------------------------------------------- #
# Additional boundary checks (module-structure and cross-cutting rules)
# --------------------------------------------------------------------------- #


def test_no_module_level_side_effects_on_import():
    """Importing the module performs no I/O beyond the sys.path bootstrap —
    re-importing it must not raise or touch the filesystem."""
    import importlib

    importlib.reload(cli)


def test_load_ledger_never_imported():
    source = Path(cli.__file__).read_text()
    assert "load_ledger" not in source


def test_shipped_gh_read_posture_keeps_the_bash_deny_that_blocks_a_live_exploit():
    """CRITICAL regression guard (security-reviewer, live exploit against the
    shipped 2.1.272 CLI). A prior revision of this posture removed
    'Bash(bash *)' from the deny list to "activate" the
    'Bash(bash bootstrap/query_issues.sh *)' allow (which sits behind it and
    is otherwise inert — deny is checked before allow with no specificity
    exception, verified against the shipped binary's own permission-decision
    code). That "activation" was empirically exploitable: with the deny
    entry absent, a command like
    `bash bootstrap/query_issues.sh ...; bash -c "id > /tmp/pwned"`
    (or the same payload via $(...) substitution) ran with zero permission
    denials — the CLI's own safe-command auto-approval does not catch a
    nested `bash -c` the way it catches e.g. `$(curl ...)`. Restoring
    'Bash(bash *)' to deny closed it (verified: DENIED, permission_denials
    populated, no file written). Delivering bash-based gh-read safely is an
    open architectural decision (escalated to architect as #1678: "a
    prefix-matched Bash allowlist grants arbitrary code execution via
    argument injection; postures are either exploitable or inert") —
    nothing in this slice may remove this deny entry again to work around
    the allow's inertness. This test reads the
    REAL shipped posture file, not the test fixture copy above."""
    real_settings_path = (
        Path(__file__).resolve().parents[2]
        / "contract"
        / "dimensions"
        / "postures"
        / "review-read-only-gh-read.settings.json"
    )
    settings = json.loads(real_settings_path.read_text())
    deny = settings["permissions"]["deny"]
    assert "Bash(bash *)" in deny, (
        "'Bash(bash *)' was removed from review-read-only-gh-read's deny list — "
        "this is the CRITICAL command-substitution bypass security-reviewer found "
        "against the live 2.1.272 CLI. Do not remove it to make the "
        "'Bash(bash bootstrap/query_issues.sh *)' allow 'work'; that allow is "
        "deliberately inert pending an architect decision."
    )


def test_severities_and_verdicts_match_validation_logic():
    """`SEVERITIES`/`VERDICTS` are deliberately literal copies in the module
    under test (classify()/`_extract_payload()` must stay I/O-free — see the
    module's own comment at their definition), which makes a hand-sync
    obligation a narration unless something actually checks it. This test is
    that check: `scripts/oversight/` is on sys.path via tests/conftest.py, so
    `validation_logic` imports directly here (this is a test file, not the
    module under test, so it is not bound by the no-I/O-at-import rule)."""
    import validation_logic

    assert cli.SEVERITIES == validation_logic.SEVERITIES
    assert cli.VERDICTS == {"approve", "request_changes", validation_logic.ERROR_VERDICT}
    # Not just spelled the same by coincidence: each value must be one
    # validation_logic's own ratchet (_VERDICT_RANK) actually recognises.
    for verdict in cli.VERDICTS:
        assert verdict in validation_logic._VERDICT_RANK, (
            f"{verdict!r} is in agent_invoke_cli.VERDICTS but validation_logic "
            "does not recognise it as a ranked verdict"
        )


def test_not_applicable_launches_nothing(repo_root, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_capped", _RunCappedSpy(None))
    rc = cli.main(
        ["--agent", AGENT_NAME, "--not-applicable", "no matching files"], repo_root=repo_root
    )
    doc = _record(capsys)
    assert rc == 0
    assert doc["applicability"] == "not_applicable"
    assert doc["applicability_reason"] == "no matching files"
    assert doc["verdict"] == "approve"
    assert doc["invocation"]["exit_code"] is None


def test_not_applicable_with_input_file_is_usage_error(repo_root, capsys):
    argv = [
        "--agent",
        AGENT_NAME,
        "--not-applicable",
        "x",
        "--input-file",
        str(repo_root / "input.txt"),
    ]
    rc = cli.main(argv, repo_root=repo_root)
    assert rc == 2
