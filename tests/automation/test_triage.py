"""Tests for triage.py — HOS automation issue-triage helpers.

Covers:
  - Basic label-based classification
  - Content-based classification
  - Security-pattern matching (tightened, Fix 2 / #311)
  - needs-human label authoritative (Fix 1 / #311)
  - field-report label classification (Fix 3 / #311)
  - Repo-scope docstring note (Fix 4 / #311) — documented via triage.__doc__
"""
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
sys.modules.setdefault("triage", triage_mod)
_SPEC.loader.exec_module(triage_mod)

triage = triage_mod.triage
TriageResult = triage_mod.TriageResult
TriageClass = triage_mod.TriageClass


# ── Return type ───────────────────────────────────────────────────────────────

def test_returns_triage_result_type():
    """triage() always returns a TriageResult."""
    result = triage("title", "body")
    assert isinstance(result, TriageResult)


def test_result_fields_populated():
    """All TriageResult fields are present and non-None."""
    result = triage("Something is broken", "It does not work correctly.")
    assert result.triage_class is not None
    assert result.confidence is not None
    assert result.reason is not None
    assert isinstance(result.autonomous, bool)
    assert isinstance(result.embargo, bool)


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_empty_title_and_body():
    """Empty inputs must not raise."""
    result = triage("", "")
    assert isinstance(result, TriageResult)


def test_none_body_equivalent():
    """An empty body is safe."""
    result = triage("Some title", "")
    assert isinstance(result, TriageResult)


# ── Label-based fast-path ─────────────────────────────────────────────────────

def test_bug_label():
    """Explicit 'bug' label → BUG class, autonomous=True."""
    result = triage("Something broken", "It crashes.", labels=["bug"])
    assert result.triage_class == TriageClass.BUG
    assert result.autonomous is True
    assert result.confidence >= 0.9


def test_enhancement_label():
    """Explicit 'enhancement' label → FEATURE class, autonomous=False."""
    result = triage("Add new thing", "Please add X.", labels=["enhancement"])
    assert result.triage_class == TriageClass.FEATURE
    assert result.autonomous is False


def test_feature_label():
    """Explicit 'feature' label → FEATURE class, autonomous=False."""
    result = triage("Add new thing", "Please add X.", labels=["feature"])
    assert result.triage_class == TriageClass.FEATURE
    assert result.autonomous is False


def test_duplicate_label():
    """Explicit 'duplicate' label → DUPLICATE class."""
    result = triage("Same issue again", "Already reported.", labels=["duplicate"])
    assert result.triage_class == TriageClass.DUPLICATE
    assert result.autonomous is False


def test_invalid_label():
    """Explicit 'invalid' label → INVALID class."""
    result = triage("Not an issue", "Misuse.", labels=["invalid"])
    assert result.triage_class == TriageClass.INVALID
    assert result.autonomous is False


def test_wontfix_label():
    """'wontfix' label → INVALID class."""
    result = triage("By design", "Working as intended.", labels=["wontfix"])
    assert result.triage_class == TriageClass.INVALID
    assert result.autonomous is False


def test_spec_gap_label():
    """Explicit 'spec-gap' label → SPEC_GAP class, autonomous=True."""
    result = triage("Spec missing", "No spec for this flow.", labels=["spec-gap"])
    assert result.triage_class == TriageClass.SPEC_GAP
    assert result.autonomous is True


# ── Fix 1 (#311): needs-human label is authoritative ─────────────────────────

def test_needs_human_label_forces_needs_human_class():
    """needs-human label → NEEDS_HUMAN class, autonomous=False, confidence=1.0."""
    result = triage(
        "needs-human: review this edge case",
        "Requires human judgment on the security trade-off.",
        labels=["needs-human"],
    )
    assert result.triage_class == TriageClass.NEEDS_HUMAN
    assert result.autonomous is False
    assert result.confidence == 1.0


def test_needs_human_label_overrides_bug_label():
    """needs-human label takes priority over bug label."""
    result = triage("needs-human: tricky bug", "Crash in auth.", labels=["needs-human", "bug"])
    assert result.triage_class == TriageClass.NEEDS_HUMAN
    assert result.autonomous is False
    assert result.confidence == 1.0


def test_needs_human_label_overrides_security_content():
    """needs-human label is checked before security patterns — returns NEEDS_HUMAN."""
    result = triage(
        "needs-human: credential handling",
        "Involves SQL injection and XSS vectors.",
        labels=["needs-human"],
    )
    assert result.triage_class == TriageClass.NEEDS_HUMAN
    assert result.autonomous is False
    assert result.confidence == 1.0


def test_issue_398_needs_human_title_prefix():
    """Reproduces calibration finding: #398 'needs-human: ...' title → NEEDS_HUMAN."""
    result = triage(
        "needs-human: coordinate release timing",
        "Coordination needed with external team.",
        labels=["needs-human"],
    )
    assert result.triage_class == TriageClass.NEEDS_HUMAN
    assert result.autonomous is False


def test_issue_396_needs_human():
    """Reproduces calibration finding: #396 needs-human labeled → NEEDS_HUMAN."""
    result = triage(
        "needs-human: escalate ambiguous spec",
        "Two interpretations are possible; human judgment required.",
        labels=["needs-human"],
    )
    assert result.triage_class == TriageClass.NEEDS_HUMAN
    assert result.autonomous is False


# ── Fix 2 (#311): tightened security patterns ────────────────────────────────

def test_security_real_vulnerability_term():
    """A real vulnerability term still triggers security-report."""
    result = triage("SQL injection in search", "User input is unsanitized.")
    assert result.triage_class == TriageClass.SECURITY_REPORT
    assert result.embargo is True
    assert result.autonomous is False


def test_security_xss_pattern():
    """XSS triggers security-report."""
    result = triage("XSS in comment field", "Reflected cross-site scripting.")
    assert result.triage_class == TriageClass.SECURITY_REPORT
    assert result.embargo is True


def test_security_cve_pattern():
    """CVE reference triggers security-report."""
    result = triage("CVE-2024-1234 affects dependency", "Patch required.")
    assert result.triage_class == TriageClass.SECURITY_REPORT
    assert result.embargo is True


def test_security_word_paired_with_flaw():
    """'security' + 'flaw' → security-report."""
    result = triage("Security flaw in auth flow", "The auth flow has a security flaw.")
    assert result.triage_class == TriageClass.SECURITY_REPORT
    assert result.embargo is True


def test_issue_311_calibrate_not_security():
    """Reproduces calibration finding: 'calibrate triage thresholds' is NOT security."""
    result = triage(
        "calibrate: triage thresholds",
        "Calibration findings: confidence and threshold values need tuning.",
    )
    assert result.triage_class != TriageClass.SECURITY_REPORT
    assert result.embargo is False


def test_threshold_alone_not_security():
    """'threshold' alone does not trigger security-report."""
    result = triage("Adjust confidence threshold", "The threshold for auto-process is too low.")
    assert result.triage_class != TriageClass.SECURITY_REPORT
    assert result.embargo is False


def test_confidence_alone_not_security():
    """'confidence' alone does not trigger security-report."""
    result = triage("Low confidence triage results", "Confidence floor at 0.75 is too strict.")
    assert result.triage_class != TriageClass.SECURITY_REPORT
    assert result.embargo is False


def test_protocol_alone_not_security():
    """'protocol' alone does not trigger security-report."""
    result = triage("Out-of-scope commits field report", "The commit protocol was not followed.")
    assert result.triage_class != TriageClass.SECURITY_REPORT
    assert result.embargo is False


# ── Fix 3 (#311): field-report label ─────────────────────────────────────────

def test_field_report_label_not_security():
    """field-report label prevents security-report misclassification."""
    result = triage(
        "Field report: out-of-scope commits protocol",
        "Observed commits being made outside the defined protocol.",
        labels=["field-report"],
    )
    assert result.triage_class != TriageClass.SECURITY_REPORT
    assert result.embargo is False


def test_field_report_label_spec_gap_when_behavior_gap():
    """field-report with behavior-gap language → spec-gap."""
    result = triage(
        "Field report: missing spec for edge case",
        "Expected behavior is not specified. Actual behavior differs from what was expected.",
        labels=["field-report"],
    )
    assert result.triage_class == TriageClass.SPEC_GAP
    assert result.autonomous is True
    assert result.embargo is False


def test_field_report_label_communication_without_gap_signals():
    """field-report without behavior-gap signals → communication."""
    result = triage(
        "Field report: status observation",
        "Observed the following during our review session.",
        labels=["field-report"],
    )
    assert result.triage_class == TriageClass.COMMUNICATION
    assert result.autonomous is True
    assert result.embargo is False


def test_issue_328_field_report_out_of_scope_commits():
    """Reproduces calibration finding: #328 field-report → not security-report."""
    result = triage(
        "Field report: out-of-scope commits",
        "The worker made commits outside its authorized scope. This was observed in the "
        "protocol review.",
        labels=["field-report"],
    )
    assert result.triage_class != TriageClass.SECURITY_REPORT
    assert result.embargo is False


# ── Fix 4 (#311): repo-scope docstring ───────────────────────────────────────

def test_repo_scope_note_in_docstring():
    """triage() docstring documents that callers own the repo-scope guard."""
    doc = triage.__doc__ or ""
    assert "repo" in doc.lower()
    assert "caller" in doc.lower()


# ── Content-based fallback classification ─────────────────────────────────────

def test_bug_content_no_label():
    """Bug language without label → BUG or COMMUNICATION class (not security)."""
    result = triage(
        "Session token not invalidated on logout",
        "After logout the session remains valid.",
    )
    # Should NOT be security-report (no exploit/vuln vocabulary)
    assert result.triage_class != TriageClass.SECURITY_REPORT
    assert result.embargo is False


def test_no_signal_defaults_to_communication():
    """No pattern match → COMMUNICATION with low confidence."""
    result = triage("Something is off", "It does not work correctly.")
    assert result.triage_class == TriageClass.COMMUNICATION
    assert result.confidence < 0.75  # below floor → not autonomous


def test_needs_human_is_in_human_only_classes():
    """NEEDS_HUMAN is in HUMAN_ONLY_CLASSES."""
    assert TriageClass.NEEDS_HUMAN in triage_mod.HUMAN_ONLY_CLASSES


def test_needs_human_not_autonomous_via_should_escalate():
    """TriageResult.should_escalate is True for NEEDS_HUMAN."""
    result = triage("needs-human: check this", "Needs review.", labels=["needs-human"])
    assert result.should_escalate is True
