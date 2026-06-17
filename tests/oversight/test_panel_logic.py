"""Tests for scripts/oversight/panel_logic.py — corroboration ranking (SPEC-376)
plus the deterministic triage floor + SQC sampling (SPEC-332).

These exercise the PURE public interface (count_corroboration, reconcile_membership,
rank_findings, compute_triage_floor, compute_sqc_sample) plus the annotate_and_rank
assembler — all with plain dicts / synthetic inputs, no subprocess / network /
file I/O (AC4 / R4 / binding 6).

Coverage:
  SPEC-376 AC1 — corroboration counts (two vendors, single, same-vendor-two-lenses).
  SPEC-376 AC2 — tier assignment + ordering (tier1 before tier2, severity within).
  SPEC-376 binding 7 — fail-open: missing/empty/malformed merged_from -> (1, [...]).
  SPEC-376 — reconcile_membership file+line+/-5 match/no-match boundaries.
  SPEC-332 AC1-AC5 — triage floor escalation (source/auth/payment/size/multi-file).
  SPEC-332 AC6-AC8 — SQC reproducibility, threshold boundary, HIGH/CRITICAL rate=0.
"""

from __future__ import annotations

import hashlib
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
compute_triage_floor = panel_logic.compute_triage_floor
compute_sqc_sample = panel_logic.compute_sqc_sample


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


# --------------------------------------------------------------------------- #
# SPEC-332 — deterministic triage floor (compute_triage_floor)                #
# --------------------------------------------------------------------------- #
def test_triage_floor_source_file_medium():
    # AC1: a source-code file escalates LOW -> MEDIUM.
    assert compute_triage_floor(["src/views.py"], 10) == "MEDIUM"


def test_triage_floor_auth_high():
    # AC2: an auth path escalates to HIGH.
    assert compute_triage_floor(["app/auth/login.py"], 10) == "HIGH"


def test_triage_floor_payment_critical():
    # AC3: a payment/billing path escalates to CRITICAL.
    assert compute_triage_floor(["billing/stripe.py"], 10) == "CRITICAL"


def test_triage_floor_size_boundary():
    # AC4: strict `>` boundary — 501 trips MEDIUM, 500 does not (parity with shell).
    assert compute_triage_floor(["README.md"], 501, size_floor=500) == "MEDIUM"
    assert compute_triage_floor(["README.md"], 500, size_floor=500) == "LOW"


def test_triage_floor_multi_file_max():
    # AC5: across files the highest floor wins (auth beats a plain README).
    files = ["README.md", "app/auth/session.py"]
    assert compute_triage_floor(files, 5) == "HIGH"


def test_triage_floor_default_low():
    # A docs-only small change stays LOW.
    assert compute_triage_floor(["README.md"], 5) == "LOW"


def test_triage_floor_dep_manifest_medium():
    # A dependency manifest escalates to MEDIUM.
    assert compute_triage_floor(["package-lock.json"], 1) == "MEDIUM"


def test_triage_floor_case_insensitive():
    # Parity with the shell's `grep -qiE` — patterns match case-insensitively.
    assert compute_triage_floor(["APP/AUTH/Login.PY"], 1) == "HIGH"


def test_triage_floor_is_pure():
    # R4: deterministic, input not mutated.
    files = ["src/a.py", "app/auth/b.py"]
    snapshot = list(files)
    first = compute_triage_floor(files, 10)
    second = compute_triage_floor(files, 10)
    assert first == second == "HIGH"
    assert files == snapshot  # not mutated


# --------------------------------------------------------------------------- #
# SPEC-332 — SQC sampling (compute_sqc_sample)                                 #
# --------------------------------------------------------------------------- #
_RATES = {"LOW": 25, "MEDIUM": 50}


def _expected_roll(head_sha: str, salt: str) -> int:
    # The same byte recipe the function uses — pins parity with run_panel.sh.
    return int(hashlib.sha256((head_sha + salt).encode()).hexdigest()[:8], 16) % 100


def test_sqc_reproducible():
    # AC6: identical args -> identical sampled/roll on every call (non-gameability).
    a = compute_sqc_sample("deadbeef", "s3cr3t", "LOW", _RATES)
    b = compute_sqc_sample("deadbeef", "s3cr3t", "LOW", _RATES)
    assert a == b
    assert a["roll"] == _expected_roll("deadbeef", "s3cr3t")


def test_sqc_threshold_boundary():
    # AC7: strict `<` — roll < rate selected; roll == rate not selected.
    roll = _expected_roll("abc", "salt")  # 23 for this vector
    # rate one above the roll -> selected
    sel = compute_sqc_sample("abc", "salt", "LOW", {"LOW": roll + 1, "MEDIUM": 50})
    assert sel == {"sampled": True, "roll": roll, "rate": roll + 1}
    # rate exactly equal to the roll -> NOT selected (boundary)
    notsel = compute_sqc_sample("abc", "salt", "LOW", {"LOW": roll, "MEDIUM": 50})
    assert notsel == {"sampled": False, "roll": roll, "rate": roll}


def test_sqc_high_returns_rate_zero():
    # AC8: HIGH is not sampled by this function (fires the adversary via shell roster).
    assert compute_sqc_sample("abc", "salt", "HIGH", _RATES) == {
        "sampled": False,
        "roll": -1,
        "rate": 0,
    }


def test_sqc_critical_returns_rate_zero():
    # AC8: CRITICAL likewise returns rate=0, sampled=False from this function.
    assert compute_sqc_sample("abc", "salt", "CRITICAL", _RATES) == {
        "sampled": False,
        "roll": -1,
        "rate": 0,
    }


def test_sqc_hash_matches_known_vector():
    # Byte-for-byte parity anchor (binding 6): pin the exact SHA256 recipe.
    expected = int(hashlib.sha256(("abc" + "salt").encode()).hexdigest()[:8], 16) % 100
    result = compute_sqc_sample("abc", "salt", "LOW", {"LOW": 100, "MEDIUM": 100})
    assert result["roll"] == expected == 23


def test_sqc_missing_rate_key_not_sampled():
    # A tier absent from sample_rates defaults to rate 0 -> not sampled (safe parity).
    assert compute_sqc_sample("abc", "salt", "LOW", {"MEDIUM": 50}) == {
        "sampled": False,
        "roll": -1,
        "rate": 0,
    }
