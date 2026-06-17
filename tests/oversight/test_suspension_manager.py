"""Tests for suspension_manager.py — the unified suspension / auto-removal engine.

Focus: parsing, consecutive-pass counting, auto-removal eligibility, and the
RATCHET invariant (the manager never writes a SUSPENDED line — it only removes).
"""
import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "suspension_manager",
    Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "suspension_manager.py",
)
sm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sm)


SAMPLE = """\
Authorized by: Test Human
Date: 2026-06-13

<!--
SUSPENDED: this-is-a-comment-example
-->

## Currently suspended
SUSPENDED: lint
SUSPENDED: types [pinned]
SUSPENDED: security review-by: 2026-07-01
SUSPENDED: code-review

## Re-enable log
"""


def test_parse_ignores_commented_examples():
    s = sm.parse_suspensions(SAMPLE)
    gates = [x.gate for x in s]
    assert gates == ["lint", "types", "security", "code-review"]
    assert "this-is-a-comment-example" not in gates


def test_parse_flags():
    s = {x.gate: x for x in sm.parse_suspensions(SAMPLE)}
    assert s["types"].pinned is True
    assert s["lint"].pinned is False
    assert s["security"].review_by == "2026-07-01"
    assert s["lint"].review_by is None


def test_consecutive_passes():
    hist = [
        {"gate": "lint", "passed": True},
        {"gate": "lint", "passed": False},
        {"gate": "lint", "passed": True},
        {"gate": "lint", "passed": True},
        {"gate": "security", "passed": True},
    ]
    # trailing run for lint is 2 (the False breaks the older one)
    assert sm.consecutive_passes(hist, "lint") == 2
    assert sm.consecutive_passes(hist, "security") == 1
    assert sm.consecutive_passes(hist, "nonexistent") == 0


def test_security_not_auto_checkable():
    # security has a reviewer counterpart — must NOT be auto-removable.
    assert "security" not in sm.AUTO_CHECKABLE_GATES
    assert "lint" in sm.AUTO_CHECKABLE_GATES


def test_auto_remove_removes_eligible_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "audit").mkdir()
    hist = tmp_path / ".claudetmp" / "oversight"
    hist.mkdir(parents=True)
    (hist / "suspension-history.jsonl").write_text(
        "\n".join(
            json.dumps({"gate": g, "passed": True})
            for g in ["lint", "lint", "lint", "types", "types", "types"]
        )
    )
    monkeypatch.setenv("SUSPENSION_AUTO_REMOVE", "true")
    monkeypatch.setenv("SUSPENSION_AUTO_REMOVE_RUNS", "3")

    susp = sm.parse_suspensions(SAMPLE)
    new_text = sm.cmd_auto_remove(SAMPLE, susp)

    # lint (pure script, 3 passes, unpinned) → removed
    assert "SUSPENDED: lint" not in new_text
    # types is pinned → kept even though it passed 3×
    assert "SUSPENDED: types [pinned]" in new_text
    # security (reviewer counterpart, not auto-checkable) → kept
    assert "SUSPENDED: security" in new_text
    # code-review (reviewer role) → kept
    assert "SUSPENDED: code-review" in new_text
    # re-enable log got a row for lint
    assert "lint" in new_text.split("## Re-enable log", 1)[1]


def test_auto_remove_disabled_keeps_everything(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hist = tmp_path / ".claudetmp" / "oversight"
    hist.mkdir(parents=True)
    (hist / "suspension-history.jsonl").write_text(
        "\n".join(json.dumps({"gate": "lint", "passed": True}) for _ in range(3))
    )
    monkeypatch.setenv("SUSPENSION_AUTO_REMOVE", "false")

    susp = sm.parse_suspensions(SAMPLE)
    new_text = sm.cmd_auto_remove(SAMPLE, susp)
    # auto-remove off → nothing removed (nudge only)
    assert "SUSPENDED: lint" in new_text


def test_emit_audit_writes_gate_suspended_event(tmp_path, monkeypatch):
    """--emit-audit must produce the SAME field set/order as the old bash
    printf: event, gate, authorized_by, timestamp (parity, HOS#337)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "audit").mkdir()
    rc = sm.cmd_emit_audit("lint", "Test Human")
    assert rc == 0
    lines = (tmp_path / "audit" / "oversight-log.jsonl").read_text().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event"] == "gate-suspended"
    assert event["gate"] == "lint"
    assert event["authorized_by"] == "Test Human"
    assert "timestamp" in event
    # PARITY: exactly these four fields, in this order (no step/suspension_file/
    # reason_category — those are deferred to the #337 follow-up).
    assert list(event.keys()) == ["event", "gate", "authorized_by", "timestamp"]


def test_emit_audit_noop_without_audit_dir(tmp_path, monkeypatch):
    """No audit/ directory → no file, no exception (guard preserved)."""
    monkeypatch.chdir(tmp_path)
    rc = sm.cmd_emit_audit("lint", "Test Human")
    assert rc == 0
    assert not (tmp_path / "audit" / "oversight-log.jsonl").exists()


def test_emit_audit_default_authorized_by(tmp_path, monkeypatch):
    """Missing authorized_by defaults to 'unknown' (matches bash :-unknown)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "audit").mkdir()
    sm.cmd_emit_audit("lint", None)
    event = json.loads((tmp_path / "audit" / "oversight-log.jsonl").read_text().strip())
    assert event["authorized_by"] == "unknown"


def test_emit_audit_escapes_authorized_by(tmp_path, monkeypatch):
    """A quote in authorized_by must yield valid JSON that round-trips."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "audit").mkdir()
    sm.cmd_emit_audit("lint", 'Ann "Q" Smith')
    event = json.loads((tmp_path / "audit" / "oversight-log.jsonl").read_text().strip())
    assert event["authorized_by"] == 'Ann "Q" Smith'


def test_ratchet_manager_never_writes_a_suspended_line(tmp_path, monkeypatch):
    """The whole point: auto_remove may only DELETE suspension lines, never add.
    Feeding it a file with one suspension can never yield MORE suspensions."""
    monkeypatch.chdir(tmp_path)
    hist = tmp_path / ".claudetmp" / "oversight"
    hist.mkdir(parents=True)
    (hist / "suspension-history.jsonl").write_text("")  # no passes
    susp = sm.parse_suspensions(SAMPLE)
    before = SAMPLE.count("SUSPENDED:")
    after = sm.cmd_auto_remove(SAMPLE, susp).count("SUSPENDED:")
    assert after <= before  # never increases
