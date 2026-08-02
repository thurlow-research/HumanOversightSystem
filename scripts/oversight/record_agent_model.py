#!/usr/bin/env python3
"""
record_agent_model.py — record the resolved model ID for a subagent invocation
into the audit trail (#1122 Option C, revised acceptance criterion 3).

Why: agent frontmatter now pins a class alias (`model: opus` / `model: sonnet`,
see .claude/agents/*.md) rather than a specific generation ID, so the alias
never drifts as new generations ship. That means the frontmatter no longer
records *which* model actually ran — only the intended tier. The audit trail
is the strictly-better place to capture provenance, because it records what
executed, not what was merely configured to execute (a stale pin was never
evidence of the model that ran, only of an intent that could go stale).

This module is invoked as a Claude Code `SubagentStop` hook (wired in
.claude/settings.json). SubagentStop hooks cannot block anything (exit code 2
just prints stderr — see Claude Code hooks reference), so this script always
exits 0 and never raises past its own entry point: a failure to record
provenance must never fail, hang, or visibly disrupt a build.

Transcript schema caveat: Claude Code's hook JSON input and transcript file
format are not fully documented for the subagent-scoped case (specifically,
whether `transcript_path` is isolated to one subagent or shared with the
session). `extract_resolved_model` is written defensively against that
ambiguity: it takes the LAST assistant-role transcript line whose `agent_id`
(when present on the line) matches the invoking subagent, and falls back to
the last assistant-role line in the file when no line carries a matching (or
any) agent_id. Each such line is expected to carry a `message.model` field,
mirroring the Anthropic Messages API response shape (`response.model`), which
is the one part of this shape actually documented and stable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.oversight.lib.audit_log import write_event  # noqa: E402


def extract_resolved_model(transcript_text: str, agent_id: Optional[str] = None) -> Optional[str]:
    """Return the resolved model ID for the most recent matching assistant turn.

    Pure — no I/O. `transcript_text` is the raw JSONL content (one JSON object
    per line; blank/malformed lines are skipped rather than raising, since a
    transcript tail can be truncated or still being written).

    Preference order: the last assistant-role line whose own `agent_id` field
    equals the given `agent_id`; if no line carries a matching (or any)
    `agent_id` field, the last assistant-role line overall. Returns None if no
    assistant-role line with a model field is found.
    """
    last_any: Optional[str] = None
    last_matching: Optional[str] = None

    for line in transcript_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict) or record.get("type") != "assistant":
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        model = message.get("model")
        if not isinstance(model, str) or not model:
            continue

        last_any = model
        record_agent_id = record.get("agent_id")
        if agent_id is not None and record_agent_id == agent_id:
            last_matching = model

    return last_matching if last_matching is not None else last_any


def record_from_hook_input(hook_input: dict, *, root: str = ".") -> Optional[str]:
    """Read the transcript named in a SubagentStop hook payload and write an
    audit event recording the resolved model. Returns the relpath written, or
    None if nothing could be recorded (missing/unreadable transcript, or no
    model found) — never raises.
    """
    transcript_path = hook_input.get("transcript_path")
    agent_id = hook_input.get("agent_id")
    agent_type = hook_input.get("agent_type")
    if not transcript_path or not agent_type:
        return None

    try:
        transcript_text = Path(transcript_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    model = extract_resolved_model(transcript_text, agent_id)
    if not model:
        return None

    event = {
        "event": "subagent-model-resolved",
        "agent_type": agent_type,
        "agent_id": agent_id,
        "model": model,
    }
    return write_event(event, root=root)


def main(argv: Optional[list] = None) -> int:
    """Hook entry point: read the SubagentStop JSON payload from stdin.

    Always exits 0 — a provenance-recording failure must never surface as a
    hook failure (SubagentStop can't block anyway; exit 2 only prints stderr).
    """
    try:
        raw = sys.stdin.read()
        hook_input = json.loads(raw) if raw.strip() else {}
        record_from_hook_input(hook_input)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
