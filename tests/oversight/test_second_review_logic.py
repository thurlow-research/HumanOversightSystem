"""Tests for scripts/oversight/second_review_logic.py — second-review logic (SPEC-331).

These exercise the PURE public interface (select_reviewers, classify_prose,
aggregate_verdicts) with synthetic content strings — no subprocess, network, or
file I/O, and no live model run (architect binding 5/6).

Coverage:
  AC1 — reviewer selection (score-only, tier-floor, below-both, boundary equality).
  AC2 — verdict aggregation (approve + request_changes/high → request_changes/high/1).
  AC3 — prose classification (must-fix, no-issues, unrecognizable).
  AC4 — error precedence + empty reviewer list → error (binding 4).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "oversight"
    / "second_review_logic.py"
)
_spec = importlib.util.spec_from_file_location("second_review_logic", _MOD_PATH)
second_review_logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(second_review_logic)

select_reviewers = second_review_logic.select_reviewers
classify_prose = second_review_logic.classify_prose
aggregate_verdicts = second_review_logic.aggregate_verdicts


# Convenience: a valid second-review output-file header (the "## " sections are
# what get parsed; the header lines are ignored by aggregation but present in
# real files).
_HEADER = (
    "# Second Review — Step 3\n"
    "Score: 0.67 | Timestamp: 20260617T000000\n"
    "verdict: pending\n"
    "highest_severity: none\n"
    "unresolved_findings: 0\n"
    "agy_threshold: 0.30 | codex_threshold: 0.55\n\n"
)


def _section(name: str, payload: str) -> str:
    """Render one reviewer section with a fenced JSON (or prose) body."""
    return f"## {name}\n```json\n{payload}\n```\n\n"


# --------------------------------------------------------------------------- #
# AC1 — reviewer selection                                                    #
# --------------------------------------------------------------------------- #
def test_ac1a_score_only_agy_fires():
    assert select_reviewers(0.45, "", 0.30, 0.55) == (True, False)


def test_ac1b_high_tier_forces_both():
    assert select_reviewers(0.20, "HIGH", 0.30, 0.55) == (True, True)


def test_ac1c_low_tier_below_thresholds_neither():
    assert select_reviewers(0.20, "LOW", 0.30, 0.55) == (False, False)


def test_medium_tier_floor_forces_agy_only():
    assert select_reviewers(0.0, "medium", 0.30, 0.55) == (True, False)


def test_critical_tier_floor_forces_both():
    assert select_reviewers(0.0, "CRITICAL", 0.30, 0.55) == (True, True)


def test_threshold_boundary_is_inclusive():
    # score == agy_threshold fires agy (>= is inclusive).
    assert select_reviewers(0.30, "", 0.30, 0.55) == (True, False)
    assert select_reviewers(0.55, "", 0.30, 0.55) == (True, True)


def test_tier_whitespace_and_case_tolerated():
    assert select_reviewers(0.0, "  high  ", 0.30, 0.55) == (True, True)


# --------------------------------------------------------------------------- #
# AC3 — prose classification                                                  #
# --------------------------------------------------------------------------- #
def test_ac3a_must_fix_is_request_changes():
    assert classify_prose("This has a must-fix problem in the handler.") == "request_changes"


def test_ac3b_no_issues_found_is_approve():
    assert classify_prose("Reviewed the diff: no issues found.") == "approve"


def test_ac3c_unrecognizable_is_unparseable():
    assert classify_prose("The weather today is pleasant and sunny.") == "unparseable"


def test_prose_branch_order_critical_beats_approve():
    # Body with both "critical" and "approve" → request_changes (risk/blocking
    # checks precede the approve check).
    assert classify_prose("A critical bug here, but otherwise I approve.") == "request_changes"


def test_prose_risk_low_is_approve():
    assert classify_prose("Risk: low — minor nit only.") == "approve"


def test_prose_risk_high_is_request_changes():
    assert classify_prose("Risk: high — auth bypass.") == "request_changes"


# --------------------------------------------------------------------------- #
# AC2 — verdict aggregation                                                    #
# --------------------------------------------------------------------------- #
def test_ac2_approve_plus_request_changes_high():
    content = (
        _HEADER
        + _section("agy — Correctness", '{"reviewer":"agy","findings":[],"verdict":"approve"}')
        + _section(
            "codex — Security",
            '{"reviewer":"codex","verdict":"request_changes",'
            '"findings":[{"severity":"high","finding":"x"}]}',
        )
    )
    result = aggregate_verdicts(content)
    assert result == {
        "verdict": "request_changes",
        "highest_severity": "high",
        "unresolved_findings": 1,
    }


# --------------------------------------------------------------------------- #
# AC4 — error precedence + empty reviewer list                                #
# --------------------------------------------------------------------------- #
def test_ac4_error_precedence_over_request_changes():
    content = (
        _HEADER
        + _section("agy — Correctness", '{"reviewer":"agy","verdict":"error","findings":[]}')
        + _section(
            "codex — Security",
            '{"reviewer":"codex","verdict":"request_changes",'
            '"findings":[{"severity":"critical","finding":"x"}]}',
        )
    )
    assert aggregate_verdicts(content)["verdict"] == "error"


def test_empty_reviewer_list_is_error():
    # Only the header, no ## agy / ## codex sections.
    assert aggregate_verdicts(_HEADER) == {
        "verdict": "error",
        "highest_severity": "none",
        "unresolved_findings": 0,
    }


def test_skipped_section_ignored():
    content = (
        _HEADER
        + "## agy — SKIPPED\n\n"
        + _section("codex — Security", '{"reviewer":"codex","findings":[],"verdict":"approve"}')
    )
    assert aggregate_verdicts(content)["verdict"] == "approve"


def test_unparseable_precedence_below_error_above_approve():
    content = (
        _HEADER
        + _section("agy — Correctness", "The weather is sunny and pleasant today.")
        + _section("codex — Security", '{"reviewer":"codex","findings":[],"verdict":"approve"}')
    )
    assert aggregate_verdicts(content)["verdict"] == "unparseable"


def test_severity_walk_counts_critical_and_high():
    content = _HEADER + _section(
        "agy — Correctness",
        '{"reviewer":"agy","verdict":"request_changes","findings":['
        '{"severity":"critical","finding":"a"},{"severity":"critical","finding":"b"}]}',
    )
    result = aggregate_verdicts(content)
    assert result["unresolved_findings"] == 2
    assert result["highest_severity"] == "critical"


def test_empty_body_section_is_error():
    # A reviewer section with an empty fenced body → error ("empty" branch).
    content = _HEADER + "## agy — Correctness\n```json\n\n```\n\n"
    assert aggregate_verdicts(content)["verdict"] == "error"


def test_fenced_body_json_parses():
    content = _HEADER + _section(
        "codex — Security",
        '{"reviewer":"codex","verdict":"approve","findings":[]}',
    )
    assert aggregate_verdicts(content)["verdict"] == "approve"
