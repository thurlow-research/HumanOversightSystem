"""Tests for scripts/oversight/record_agent_model.py (#1122 Option C).

Covers the pure transcript-parsing function (extract_resolved_model) and the
hook-payload-to-audit-event path (record_from_hook_input), which is the piece
that lets the audit trail answer "which model actually ran" now that agent
frontmatter pins a class alias rather than a specific generation ID.
"""
import json
from pathlib import Path

from record_agent_model import extract_resolved_model, record_from_hook_input


def _line(model=None, agent_id=None, type_="assistant"):
    record = {"type": type_}
    if model is not None:
        record["message"] = {"role": "assistant", "model": model}
    if agent_id is not None:
        record["agent_id"] = agent_id
    return json.dumps(record)


def test_extract_resolved_model_returns_last_assistant_model_when_no_agent_id_given():
    transcript = "\n".join([
        _line(model="claude-sonnet-5"),
        _line(model="claude-opus-5"),
    ])
    assert extract_resolved_model(transcript) == "claude-opus-5"


def test_extract_resolved_model_prefers_matching_agent_id():
    transcript = "\n".join([
        _line(model="claude-opus-5", agent_id="other-agent"),
        _line(model="claude-sonnet-5", agent_id="target-agent"),
        _line(model="claude-opus-5", agent_id="other-agent"),
    ])
    assert extract_resolved_model(transcript, agent_id="target-agent") == "claude-sonnet-5"


def test_extract_resolved_model_falls_back_when_no_line_carries_agent_id():
    transcript = "\n".join([
        _line(model="claude-sonnet-5"),
    ])
    assert extract_resolved_model(transcript, agent_id="target-agent") == "claude-sonnet-5"


def test_extract_resolved_model_ignores_non_assistant_and_malformed_lines():
    transcript = "\n".join([
        "not json at all",
        _line(model="claude-sonnet-5", type_="user"),
        "",
        _line(model="claude-opus-5"),
    ])
    assert extract_resolved_model(transcript) == "claude-opus-5"


def test_extract_resolved_model_returns_none_when_no_model_found():
    transcript = "\n".join([
        _line(type_="user"),
        "{}",
    ])
    assert extract_resolved_model(transcript) is None


def test_extract_resolved_model_empty_transcript():
    assert extract_resolved_model("") is None


def test_record_from_hook_input_writes_audit_event(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(_line(model="claude-opus-5", agent_id="agent-1") + "\n")

    hook_input = {
        "transcript_path": str(transcript_path),
        "agent_id": "agent-1",
        "agent_type": "pm-agent",
    }

    relpath = record_from_hook_input(hook_input, root=str(tmp_path))
    assert relpath is not None

    written = (tmp_path / "audit" / "log" / relpath).read_text()
    event = json.loads(written)
    assert event["event"] == "subagent-model-resolved"
    assert event["agent_type"] == "pm-agent"
    assert event["agent_id"] == "agent-1"
    assert event["model"] == "claude-opus-5"


def test_record_from_hook_input_returns_none_when_transcript_missing(tmp_path):
    hook_input = {
        "transcript_path": str(tmp_path / "does-not-exist.jsonl"),
        "agent_id": "agent-1",
        "agent_type": "pm-agent",
    }
    assert record_from_hook_input(hook_input, root=str(tmp_path)) is None


def test_record_from_hook_input_returns_none_when_agent_type_missing(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(_line(model="claude-opus-5") + "\n")
    hook_input = {"transcript_path": str(transcript_path)}
    assert record_from_hook_input(hook_input, root=str(tmp_path)) is None


def test_record_from_hook_input_returns_none_when_no_model_in_transcript(tmp_path):
    transcript_path = tmp_path / "transcript.jsonl"
    transcript_path.write_text(_line(type_="user") + "\n")
    hook_input = {
        "transcript_path": str(transcript_path),
        "agent_id": "agent-1",
        "agent_type": "pm-agent",
    }
    assert record_from_hook_input(hook_input, root=str(tmp_path)) is None
