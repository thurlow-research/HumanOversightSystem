"""Tests for scripts/oversight/panel_logic.py — corroboration ranking (SPEC-376).

These exercise the PURE public interface (count_corroboration, reconcile_membership,
rank_findings) plus the annotate_and_rank assembler — all with plain dicts, no
subprocess / network / file I/O (AC4 / binding 6).

Coverage:
  AC1 — corroboration counts (two vendors, single vendor, same-vendor-two-lenses).
  AC2 — tier assignment + ordering (tier1 before tier2, severity within tier).
  Binding 7 — fail-open: missing/empty/malformed merged_from -> (1, [...]).
  reconcile_membership — file+line+/-5 match/no-match boundaries.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "oversight"
    / "panel_logic.py"
)
_spec = importlib.util.spec_from_file_location("panel_logic", _MOD_PATH)
panel_logic = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(panel_logic)

count_corroboration = panel_logic.count_corroboration
reconcile_membership = panel_logic.reconcile_membership
rank_findings = panel_logic.rank_findings
annotate_and_rank = panel_logic.annotate_and_rank


# --------------------------------------------------------------------------- #
# AC1 — corroboration counting                                                #
# --------------------------------------------------------------------------- #
def test_two_distinct_vendors_corroborated_by_2():
    finding = {
        "file": "a.py",
        "line": 10,
        "merged_from": [
            {"reviewer": "agy", "lens": "correctness"},
            {"reviewer": "codex", "lens": "security"},
        ],
    }
    count, reviewers = count_corroboration(finding)
    assert count == 2
    assert reviewers == ["agy", "codex"]  # sorted, deterministic


def test_single_vendor_corroborated_by_1():
    finding = {"reviewer": "agy", "merged_from": [{"reviewer": "agy", "lens": "correctness"}]}
    count, reviewers = count_corroboration(finding)
    assert count == 1
    assert reviewers == ["agy"]


def test_same_vendor_two_lenses_collapses_to_1():
    finding = {
        "merged_from": [
            {"reviewer": "codex", "lens": "security"},
            {"reviewer": "codex", "lens": "adversary"},
        ]
    }
    count, reviewers = count_corroboration(finding)
    assert count == 1  # same vendor, two lenses -> 1 independent source (binding 3)
    assert reviewers == ["codex"]


def test_three_findings_two_vendors_collapses_correctly():
    # agy + codex:security + codex:adversary -> {agy, codex} -> 2
    finding = {
        "merged_from": [
            {"reviewer": "agy", "lens": "correctness"},
            {"reviewer": "codex", "lens": "security"},
            {"reviewer": "codex", "lens": "adversary"},
        ]
    }
    count, reviewers = count_corroboration(finding)
    assert count == 2
    assert reviewers == ["agy", "codex"]


# --------------------------------------------------------------------------- #
# Binding 7 — fail-open                                                        #
# --------------------------------------------------------------------------- #
def test_missing_merged_from_fails_open_to_own_reviewer():
    count, reviewers = count_corroboration({"reviewer": "agy"})
    assert count == 1
    assert reviewers == ["agy"]


def test_empty_merged_from_fails_open_to_unknown():
    count, reviewers = count_corroboration({"merged_from": []})
    assert count == 1
    assert reviewers == ["unknown"]


def test_malformed_merged_from_entries_fail_open():
    # entries without a usable reviewer key -> floor
    count, reviewers = count_corroboration(
        {"reviewer": "codex", "merged_from": [{"lens": "x"}, "garbage", 7]}
    )
    assert count == 1
    assert reviewers == ["codex"]


def test_merged_from_not_a_list_fails_open():
    count, reviewers = count_corroboration({"merged_from": "agy", "reviewer": "agy"})
    assert count == 1
    assert reviewers == ["agy"]


# --------------------------------------------------------------------------- #
# reconcile_membership — file + line +/-5 proximity                           #
# --------------------------------------------------------------------------- #
def _raw(file, line, reviewer, lens="correctness"):
    return {"file": file, "line": line, "reviewer": reviewer, "lens": lens}


def test_reconcile_matches_within_5_lines():
    raw = [_raw("a.py", 12, "agy"), _raw("a.py", 100, "codex")]
    finding = {"file": "a.py", "line": 10}
    membership = reconcile_membership(raw, finding)
    assert membership == [{"reviewer": "agy", "lens": "correctness"}]


def test_reconcile_delta_5_matches_delta_6_does_not():
    finding = {"file": "a.py", "line": 10}
    assert reconcile_membership([_raw("a.py", 15, "agy")], finding)  # delta 5 matches
    assert reconcile_membership([_raw("a.py", 16, "agy")], finding) == []  # delta 6 no


def test_reconcile_different_file_no_match():
    finding = {"file": "a.py", "line": 10}
    assert reconcile_membership([_raw("b.py", 10, "agy")], finding) == []


def test_reconcile_finding_without_line_returns_empty():
    assert reconcile_membership([_raw("a.py", 10, "agy")], {"file": "a.py"}) == []


def test_reconcile_raw_without_line_skipped():
    finding = {"file": "a.py", "line": 10}
    raw = [{"file": "a.py", "reviewer": "agy"}, _raw("a.py", 11, "codex")]
    membership = reconcile_membership(raw, finding)
    assert membership == [{"reviewer": "codex", "lens": "correctness"}]


# --------------------------------------------------------------------------- #
# AC2 — tier assignment + ordering                                            #
# --------------------------------------------------------------------------- #
def test_rank_tier1_before_tier2():
    findings = [
        {"corroboration_tier": 2, "severity": "tier1", "file": "a.py", "line": 1},
        {"corroboration_tier": 1, "severity": "tier4", "file": "b.py", "line": 2},
    ]
    ranked = rank_findings(findings)
    # tier-1 finding first even though its severity is lower
    assert ranked[0]["corroboration_tier"] == 1
    assert ranked[1]["corroboration_tier"] == 2


def test_rank_severity_within_tier():
    findings = [
        {"corroboration_tier": 1, "severity": "tier3", "file": "a.py", "line": 1},
        {"corroboration_tier": 1, "severity": "tier1", "file": "b.py", "line": 2},
        {"corroboration_tier": 1, "severity": "tier2", "file": "c.py", "line": 3},
    ]
    ranked = rank_findings(findings)
    assert [f["severity"] for f in ranked] == ["tier1", "tier2", "tier3"]


def test_rank_missing_tier_treated_as_tier2():
    findings = [
        {"severity": "tier1", "file": "a.py", "line": 1},  # no corroboration_tier
        {"corroboration_tier": 1, "severity": "tier4", "file": "b.py", "line": 2},
    ]
    ranked = rank_findings(findings)
    assert ranked[0]["corroboration_tier"] == 1


def test_rank_is_deterministic_and_pure():
    findings = [
        {"corroboration_tier": 2, "severity": "tier2", "file": "z.py", "line": 9},
        {"corroboration_tier": 1, "severity": "tier1", "file": "a.py", "line": 1},
    ]
    snapshot = [dict(f) for f in findings]
    first = rank_findings(findings)
    second = rank_findings(findings)
    assert [id(x) for x in first] != [id(findings)]  # new list
    assert first == second  # deterministic
    assert findings == snapshot  # input not mutated


# --------------------------------------------------------------------------- #
# annotate_and_rank — end-to-end assembler (still pure, dict in / dict out)   #
# --------------------------------------------------------------------------- #
def test_annotate_and_rank_full_object():
    arbiter = {
        "summary": "overview",
        "findings": [
            {
                "file": "a.py",
                "line": 5,
                "severity": "tier3",
                "merged_from": [{"reviewer": "agy", "lens": "correctness"}],
            },
            {
                "file": "b.py",
                "line": 20,
                "severity": "tier2",
                "merged_from": [
                    {"reviewer": "agy", "lens": "correctness"},
                    {"reviewer": "codex", "lens": "security"},
                ],
            },
        ],
    }
    out = annotate_and_rank(arbiter)
    assert out["summary"] == "overview"  # passed through untouched
    # Tier 1 (two vendors) ordered first
    assert out["findings"][0]["file"] == "b.py"
    assert out["findings"][0]["corroboration_tier"] == 1
    assert out["findings"][0]["corroborated_by"] == 2
    assert out["findings"][0]["corroborating_reviewers"] == ["agy", "codex"]
    assert out["findings"][1]["corroboration_tier"] == 2
    assert out["findings"][1]["corroborated_by"] == 1


def test_annotate_reconciles_missing_membership_from_raw():
    arbiter = {
        "summary": "s",
        "findings": [{"file": "a.py", "line": 10, "severity": "tier1"}],  # no merged_from
    }
    raw = [
        {"file": "a.py", "line": 11, "reviewer": "agy", "lens": "correctness"},
        {"file": "a.py", "line": 12, "reviewer": "codex", "lens": "security"},
    ]
    out = annotate_and_rank(arbiter, raw_findings=raw)
    f = out["findings"][0]
    assert f["corroborated_by"] == 2
    assert f["corroborating_reviewers"] == ["agy", "codex"]
    assert f["corroboration_tier"] == 1


def test_annotate_no_suppression_all_findings_survive():
    arbiter = {"findings": [{"file": "a", "line": 1}, {"file": "b", "line": 2}]}
    out = annotate_and_rank(arbiter)
    assert len(out["findings"]) == 2  # binding 9: nothing dropped
