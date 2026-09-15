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
import json
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
digest_validators = second_review_logic.digest_validators


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


# --------------------------------------------------------------------------- #
# #982 — prose reviewer report with its own "## " headings must not truncate  #
# --------------------------------------------------------------------------- #
def test_prose_report_with_internal_headings_not_truncated():
    """A prose reviewer report (agy returned markdown, not JSON) whose body has
    its own '## ' headings must be classified in full — the must-fix content
    below the model's first heading must NOT be silently dropped (#982, the #113
    degradation path). Previously the naïve '^## ' split truncated the reviewer
    section at '## Critical Issues', leaving only the 'Looks good' preamble →
    approve."""
    prose = (
        "Looks good overall.\n"
        "## Critical Issues\n"
        "- must-fix: SQL injection in views.py\n"
    )
    content = _HEADER + _section("agy — Correctness", prose)
    result = aggregate_verdicts(content)
    assert result["verdict"] == "request_changes"
    assert result["highest_severity"] == "critical"


def test_advisory_block_after_reviewer_does_not_corrupt_json():
    """A '## [ADVISORY]' block the shell appends AFTER a reviewer section (a
    top-level, outside-fence header) is not a reviewer and must not be pulled
    into the preceding reviewer's fenced JSON body (fence-aware split guard for
    the #982 fix — greedy fence extraction must still see only the reviewer's
    own JSON)."""
    content = (
        _HEADER
        + _section("agy — Correctness", '{"reviewer":"agy","verdict":"approve","findings":[]}')
        + "## [ADVISORY] Full-context request — diff-centric mode (SPEC-379)\n"
        + "```\n[ADVISORY] Reviewer requested full-repository context.\n```\n\n"
    )
    assert aggregate_verdicts(content)["verdict"] == "approve"


# --------------------------------------------------------------------------- #
# ADR-1683 D-3 — validator-summary digest (three-tier degradation)            #
# --------------------------------------------------------------------------- #
def _make_summary(n_results: int, raw_value_len: int = 0, error_len: int = 0) -> dict:
    """A synthetic validators/summary.json shaped like the real thing (13
    dimensions in production; arbitrary count here to control serialized
    size). `raw_value_len` / `error_len` pad specific fields to force a
    tier to exceed the 16,384-byte cap."""
    results = []
    for i in range(n_results):
        results.append({
            "dimension": f"dim{i}",
            "score": 0.5,
            "weight": 0.1,
            "tier_floor": None,
            "error": ("e" * error_len) if error_len else None,
            "raw_value": {"blob": "x" * raw_value_len} if raw_value_len else {"ok": True},
            "evidence": [{"file": "a.py", "line": 1, "message": "m", "severity": "low"}] * 2,
            "findings": [{"severity": "low", "file": "a.py", "line": 1, "message": "m"}],
            "checklist_items": ["c1", "c2"],
        })
    return {
        "composite_score": 0.42,
        "tier": "MEDIUM",
        "validator_count": n_results,
        "successful_validators": n_results,
        "results": results,
    }


def test_digest_tier1_used_when_within_cap():
    """A small summary fits tier 1 (full per-validator scores/weights/floors +
    evidence/finding/checklist COUNTS) with no degradation and no stderr line."""
    digest, stderr_lines = digest_validators(_make_summary(3, raw_value_len=50))
    assert digest["_digest_tier"] == 1
    assert stderr_lines == []
    assert digest["results"][0]["raw_value"] == {"blob": "x" * 50}
    assert digest["results"][0]["evidence_count"] == 2
    assert digest["results"][0]["finding_count"] == 1
    assert digest["results"][0]["checklist_count"] == 2
    json.loads(json.dumps(digest))


def test_digest_degrades_to_tier2_at_the_16384_byte_boundary():
    """Tier 1 exceeds the cap (large `raw_value`s) -> tier 2 drops `raw_value`
    per validator and fits; exactly one degradation line is printed."""
    digest, stderr_lines = digest_validators(_make_summary(10, raw_value_len=3000))
    assert digest["_digest_tier"] == 2
    assert len(stderr_lines) == 1
    assert "tier 2" in stderr_lines[0]
    assert "16384" in stderr_lines[0]
    assert "raw_value" not in digest["results"][0]
    assert digest["results"][0]["dimension"] == "dim0"
    json.loads(json.dumps(digest))


def test_digest_degrades_to_tier3_when_tier2_also_exceeds_cap():
    """Even with `raw_value` dropped, enough validators (large `error` text)
    still exceed the cap -> tier 3 drops all per-validator detail down to a
    bare `dimension: score` map. Two degradation lines are printed (2, then 3)."""
    digest, stderr_lines = digest_validators(_make_summary(120, error_len=250))
    assert digest["_digest_tier"] == 3
    assert len(stderr_lines) == 2
    assert "tier 2" in stderr_lines[0]
    assert "tier 3" in stderr_lines[1]
    assert "results" not in digest
    assert digest["scores"] == {f"dim{i}": 0.5 for i in range(120)}
    json.loads(json.dumps(digest))


def test_digest_never_carries_evidence_findings_or_checklist_arrays():
    """D-3's whole point: the anchoring content (evidence/findings/checklist
    arrays — file:line:message pointers) must never survive into the prompt,
    at ANY tier — only aggregate counts (tier 1/2) or nothing (tier 3)."""
    for summary, expect_tier in (
        (_make_summary(3, raw_value_len=10), 1),
        (_make_summary(10, raw_value_len=3000), 2),
        (_make_summary(120, error_len=250), 3),
    ):
        digest, _ = digest_validators(summary)
        assert digest["_digest_tier"] == expect_tier
        blob = json.dumps(digest)
        assert '"evidence"' not in blob, blob
        assert '"findings"' not in blob, blob
        assert '"checklist_items"' not in blob, blob


def test_digest_carries_tier_and_note_and_is_valid_json_at_every_tier():
    for summary in (
        _make_summary(3, raw_value_len=10),
        _make_summary(10, raw_value_len=3000),
        _make_summary(120, error_len=250),
    ):
        digest, _ = digest_validators(summary)
        assert digest["_digest_tier"] in (1, 2, 3)
        assert digest["_digest_note"]
        json.loads(json.dumps(digest))
