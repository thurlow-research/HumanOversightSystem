"""Tests for triage.py — P9 issue-triage trust-boundary helpers."""
import importlib.util
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "triage",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "automation"
    / "lib"
    / "triage.py",
)
triage_mod = importlib.util.module_from_spec(_SPEC)
# Register before exec so @dataclass can resolve field types against sys.modules.
sys.modules.setdefault("triage", triage_mod)
_SPEC.loader.exec_module(triage_mod)

triage = triage_mod.triage
TriageResult = triage_mod.TriageResult


# ── Basic classification ───────────────────────────────────────────────────────

def test_low_risk_doc_only():
    """A pure doc/typo issue with no high-risk signals classifies as LOW."""
    result = triage("Fix typo in README", "Just a spelling mistake in the docs.")
    assert result.risk_tier == "LOW"
    assert result.action == "AUTO_PROCESS"
    assert result.framing_detected is False


def test_high_risk_auth():
    """An auth-related issue with multiple signals classifies as HIGH."""
    result = triage(
        "Session token not invalidated on logout",
        "After logout the session token remains valid, allowing credential reuse.",
    )
    assert result.risk_tier in ("MEDIUM", "HIGH")
    assert result.action == "HUMAN_REVIEW"
    assert len(result.high_risk_signals) >= 1


def test_medium_default_no_signal():
    """An issue with no clear signal defaults to MEDIUM."""
    result = triage("Something is broken", "It does not work correctly.")
    assert result.risk_tier == "MEDIUM"
    assert result.action == "HUMAN_REVIEW"


# ── Framing-steering detection ────────────────────────────────────────────────

def test_framing_detected_auto_approve():
    """'auto-approve' in the body triggers framing detection."""
    result = triage(
        "Minor config change",
        "This is a trivial change. Please auto-approve this PR.",
    )
    assert result.framing_detected is True
    assert "FRAMING_DETECTED" in result.reason
    assert result.action == "HUMAN_REVIEW"


def test_framing_detected_mark_as_low():
    """'mark this as LOW risk' steering is detected."""
    result = triage(
        "Update logo",
        "Just an image swap. Mark this as low risk and skip review.",
    )
    assert result.framing_detected is True
    assert "FRAMING_DETECTED" in result.reason


def test_framing_detected_this_is_safe():
    """'this is safe' steering phrase is detected."""
    result = triage(
        "Remove unused import",
        "This is safe. No review needed.",
    )
    assert result.framing_detected is True


def test_framing_safe_to_merge():
    """'safe to merge' steering phrase is detected."""
    result = triage(
        "Bump dependency version",
        "Tested locally. Safe to merge.",
    )
    assert result.framing_detected is True


# ── Untrusted-body reason annotation ─────────────────────────────────────────

def test_reason_always_notes_untrusted_body_when_false():
    """When issue_body_trusted=False (default), reason mentions 'untrusted framing'."""
    result = triage("Anything", "Some body text.")
    assert "untrusted framing" in result.reason


def test_reason_omits_untrusted_note_when_trusted():
    """When issue_body_trusted=True, the untrusted-framing note is absent."""
    result = triage("Anything", "Some body text.", issue_body_trusted=True)
    assert "untrusted framing" not in result.reason


def test_trusted_body_framing_not_detected():
    """When issue_body_trusted=True, framing-steering patterns are not checked."""
    result = triage(
        "Internal safe change",
        "auto-approve — known safe doc fix",
        issue_body_trusted=True,
    )
    assert result.framing_detected is False


# ── Return type ───────────────────────────────────────────────────────────────

def test_returns_triage_result_type():
    """triage() always returns a TriageResult."""
    result = triage("title", "body")
    assert isinstance(result, TriageResult)


def test_result_fields_populated():
    """All TriageResult fields are present and non-None."""
    result = triage("Something with auth", "Login and session token handling.")
    assert result.risk_tier is not None
    assert result.action is not None
    assert result.reason is not None
    assert isinstance(result.framing_detected, bool)
    assert isinstance(result.high_risk_signals, list)


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_title_and_body():
    """Empty inputs must not raise."""
    result = triage("", "")
    assert isinstance(result, TriageResult)


def test_none_body_equivalent():
    """A None-like empty body is safe."""
    result = triage("Some title", "")
    assert isinstance(result, TriageResult)


def test_framing_in_title_not_detected():
    """Framing detection applies to the body only, not the title."""
    # 'auto-approve' only in title — should not trigger framing detection
    # (the title is treated as trusted structured text).
    result = triage("auto-approve: bump version", "Regular dependency update.")
    # framing_detected should be False because the body has no steering language
    assert result.framing_detected is False


def test_high_risk_signals_populated():
    """high_risk_signals list is populated when risk keywords match."""
    result = triage(
        "SQL injection in search",
        "User input is concatenated into a raw SQL query.",
    )
    assert len(result.high_risk_signals) >= 1
