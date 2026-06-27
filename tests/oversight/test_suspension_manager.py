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


def _read_audit_events(root) -> list[dict]:
    """Reconstruct the chronological event list from the per-entry records.

    emit_audit writes one write-once file per event under <root>/audit/log/
    (SPEC-888 #888 P2); the canonical read-shim concatenates them back in order.
    """
    return [json.loads(b) for b in sm._AUDIT_LOG.read_stream(str(root))]


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
    """--emit-audit produces the full OVERSIGHT-CONTRACT §6a field set (#397).

    PARITY fields (HOS#337): event, gate, authorized_by, timestamp.
    Added by HOS#397: step, suspension_file, reason_category.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "audit").mkdir()
    rc = sm.cmd_emit_audit("lint", "Test Human", step="step-3")
    assert rc == 0
    events = _read_audit_events(tmp_path)
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "gate-suspended"
    assert event["gate"] == "lint"
    assert event["authorized_by"] == "Test Human"
    assert event["step"] == "step-3"
    assert "suspension_file" in event
    assert event["reason_category"] == "unspecified"  # no suspension file in tmp_path
    assert "timestamp" in event
    # Full field set per OVERSIGHT-CONTRACT §6a (parity + #397 additions). The
    # on-disk record is canonically key-sorted (SPEC-888), so compare as a set.
    assert set(event.keys()) == {
        "event", "gate", "authorized_by", "step",
        "suspension_file", "reason_category", "timestamp",
    }


def test_emit_audit_noop_without_audit_dir(tmp_path, monkeypatch):
    """No audit/ directory → no record, no exception (guard preserved)."""
    monkeypatch.chdir(tmp_path)
    rc = sm.cmd_emit_audit("lint", "Test Human")
    assert rc == 0
    assert not (tmp_path / "audit").exists()
    assert _read_audit_events(tmp_path) == []


def test_emit_audit_default_authorized_by(tmp_path, monkeypatch):
    """Missing authorized_by defaults to 'unknown' (matches bash :-unknown)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "audit").mkdir()
    sm.cmd_emit_audit("lint", None)
    event = _read_audit_events(tmp_path)[0]
    assert event["authorized_by"] == "unknown"


def test_emit_audit_escapes_authorized_by(tmp_path, monkeypatch):
    """A quote in authorized_by must yield valid JSON that round-trips."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "audit").mkdir()
    sm.cmd_emit_audit("lint", 'Ann "Q" Smith')
    event = _read_audit_events(tmp_path)[0]
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


# ─────────────────────────────────────────────────────────────────────────────
# SPEC-83 — per-step scope + grandfathered_until
# ─────────────────────────────────────────────────────────────────────────────

PER_STEP_BLOCK = """\
Authorized by: Test Human
Date: 2026-06-17

security-suspension-acknowledged: yes
per_step_scope: true
steps:
  - step-3
  - step-4

## Currently suspended
SUSPENDED: security
"""

PER_STEP_INLINE = """\
security-suspension-acknowledged: yes
per_step_scope: true
steps: [step-3, step-4]
"""

BLANKET = """\
security-suspension-acknowledged: yes
## Currently suspended
SUSPENDED: security
"""

MALFORMED = """\
security-suspension-acknowledged: yes
per_step_scope: true
## Currently suspended
SUSPENDED: security
"""

COMMENTED_FIELDS = """\
# per_step_scope: true
# steps:
#   - step-9
<!--
per_step_scope: true
steps:
  - step-99
-->
## Currently suspended
SUSPENDED: security
"""


def test_parse_per_step_scope_block_list():
    per, steps = sm.parse_per_step_scope(PER_STEP_BLOCK)
    assert per is True
    assert steps == ["step-3", "step-4"]


def test_parse_per_step_scope_inline_list():
    per, steps = sm.parse_per_step_scope(PER_STEP_INLINE)
    assert per is True
    assert steps == ["step-3", "step-4"]


def test_parse_per_step_scope_absent_defaults_false():
    per, steps = sm.parse_per_step_scope(BLANKET)
    assert per is False
    assert steps == []


def test_parse_per_step_scope_ignores_commented_and_html():
    per, steps = sm.parse_per_step_scope(COMMENTED_FIELDS)
    assert per is False
    assert steps == []


def test_validate_per_step_scope_covers_listed_step():
    v = sm.validate_per_step_scope(PER_STEP_BLOCK, "step-3")
    assert v["per_step_scope"] is True
    assert v["malformed"] is False
    assert v["covers_step"] is True


def test_validate_per_step_scope_does_not_cover_unlisted_step():
    # AC7 — scope covering step-3/4 does not cover step-5
    v = sm.validate_per_step_scope(PER_STEP_BLOCK, "step-5")
    assert v["covers_step"] is False
    assert v["malformed"] is False


def test_validate_per_step_scope_exact_match_only():
    # no prefix / substring matching
    v = sm.validate_per_step_scope(PER_STEP_BLOCK, "step-3-extra")
    assert v["covers_step"] is False


def test_validate_per_step_scope_malformed():
    # R1.6 — per_step_scope: true with no steps is malformed (distinct FAIL)
    v = sm.validate_per_step_scope(MALFORMED, "step-3")
    assert v["malformed"] is True
    assert v["covers_step"] is False


def test_validate_per_step_scope_blanket_not_malformed():
    v = sm.validate_per_step_scope(BLANKET, "step-3")
    assert v["per_step_scope"] is False
    assert v["malformed"] is False
    assert v["covers_step"] is False


def test_grandfathered_until_absent():
    g = sm.check_grandfathered_until(BLANKET)
    assert g["present"] is False
    assert g["status"] == "absent"


def test_grandfathered_until_future():
    text = "grandfathered_until: 2099-12-31\n"
    g = sm.check_grandfathered_until(text, today="2026-06-17")
    assert g["status"] == "future"
    assert g["date"] == "2099-12-31"


def test_grandfathered_until_expired_past():
    text = "grandfathered_until: 2020-01-01\n"
    g = sm.check_grandfathered_until(text, today="2026-06-17")
    assert g["status"] == "expired"


def test_grandfathered_until_today_is_expired():
    # boundary: today is not "in the future"
    text = "grandfathered_until: 2026-06-17\n"
    g = sm.check_grandfathered_until(text, today="2026-06-17")
    assert g["status"] == "expired"


def test_grandfathered_until_malformed_value_fails_closed():
    text = "grandfathered_until: someday\n"
    g = sm.check_grandfathered_until(text, today="2026-06-17")
    assert g["status"] == "malformed"


def test_grandfathered_until_ignores_commented():
    text = "# grandfathered_until: 2099-01-01\n"
    g = sm.check_grandfathered_until(text, today="2026-06-17")
    assert g["status"] == "absent"
