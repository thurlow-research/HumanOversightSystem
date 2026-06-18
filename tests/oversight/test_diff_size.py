"""
Tests for diff_size.py — diff-size risk floor + multi-purpose split trigger (#377).

Covers every acceptance criterion AC-377-01 .. AC-377-14 plus the architect
bindings (HOS_DOMAIN_MAP replace/fallback, top-level tier_floor via make_result,
zero-as-unavailable gating, strict-greater-than comparison).
"""
import os

import pytest

from diff_size import (
    _DEFAULT_DOMAIN_MAP,
    classify_domain,
    detect_domains,
    evaluate,
    parse_args,
    parse_domain_map,
)
from schema import WEIGHTS, make_result


# ── helpers ──────────────────────────────────────────────────────────────────

DEFAULTS = dict(
    diff_size_floor=400,
    file_count_floor=15,
    domain_split_threshold=3,
    domain_map=_DEFAULT_DOMAIN_MAP,
)


def run(changed_lines, changed_files, file_list, **over):
    kw = {**DEFAULTS, **over}
    return evaluate(
        changed_lines=changed_lines,
        changed_files=changed_files,
        file_list=file_list,
        **kw,
    )


# ── R1: diff-size floor ──────────────────────────────────────────────────────

class TestDiffSizeFloor:
    def test_ac01_lines_over_threshold(self):
        r = run(512, 2, ["a.py"])
        assert r["tier_floor"] == "HIGH"
        assert r["raw_value"]["floor_rule_fired"] == "changed_lines"

    def test_ac02_files_over_threshold(self):
        r = run(50, 20, ["a.py"])
        assert r["tier_floor"] == "HIGH"
        assert r["raw_value"]["floor_rule_fired"] == "changed_files"

    def test_ac03_both(self):
        r = run(512, 20, ["a.py"])
        assert r["raw_value"]["floor_rule_fired"] == "both"

    def test_ac04_neither(self):
        r = run(50, 5, ["a.py"])
        assert r["tier_floor"] is None
        assert r["raw_value"]["floor_rule_fired"] is None

    def test_ac05_zeros_never_fire(self):
        r = run(0, 0, [], diff_size_floor=1, file_count_floor=1)
        assert r["tier_floor"] is None

    def test_zero_lines_with_huge_threshold_unavailable(self):
        # changed_lines=0 must be gated out before comparison even if files fire.
        r = run(0, 20, ["a.py"])
        assert r["raw_value"]["floor_rule_fired"] == "changed_files"

    def test_strict_greater_than_boundary(self):
        # equal to threshold does NOT fire (strict >)
        assert run(400, 0, ["a.py"])["tier_floor"] is None
        assert run(401, 0, ["a.py"])["tier_floor"] == "HIGH"

    def test_ac08_custom_floor_fires(self):
        r = run(11, 1, ["a.py"], diff_size_floor=10)
        assert r["tier_floor"] == "HIGH"


# ── R2: split trigger ────────────────────────────────────────────────────────

class TestSplitTrigger:
    def test_ac06_advisory_phrase(self):
        r = run(5, 3, [".claude/agents/f.md", "scripts/b.sh", "docs/c.md"])
        joined = " ".join(r["checklist_items"])
        assert "Consider splitting into focused PRs" in joined
        assert "3 domains" in joined

    def test_ac07_split_does_not_set_tier_floor(self):
        r = run(5, 3, [".claude/agents/f.md", "scripts/b.sh", "docs/c.md"])
        assert r["tier_floor"] is None

    def test_below_threshold_no_advisory(self):
        r = run(5, 2, ["scripts/a.sh", "scripts/b.sh"])
        assert r["checklist_items"] == []

    def test_at_threshold_fires(self):
        r = run(5, 3, ["scripts/a", "docs/b", "packs/c"], domain_split_threshold=3)
        assert any("Consider splitting" in c for c in r["checklist_items"])

    def test_other_collapses_to_one_domain(self):
        # many unmatched files → single "other" domain → no split below threshold
        r = run(5, 3, ["Makefile", "README", "LICENSE"])
        assert r["raw_value"]["domain_count"] == 1


# ── domain detection ─────────────────────────────────────────────────────────

class TestDomainDetection:
    def test_ac13_three_domains(self):
        count, domains = detect_domains(
            [".claude/agents/foo.md", "scripts/bar.sh", "docs/baz.md"], _DEFAULT_DOMAIN_MAP
        )
        assert count == 3
        assert set(domains) == {"agents", "scripts", "docs"}

    def test_ac14_unmatched_is_other(self):
        assert classify_domain("Makefile", _DEFAULT_DOMAIN_MAP) == "other"

    def test_first_prefix_wins(self):
        assert classify_domain("scripts/x.py", _DEFAULT_DOMAIN_MAP) == "scripts"

    def test_empty_file_list(self):
        count, domains = detect_domains([], _DEFAULT_DOMAIN_MAP)
        assert count == 0 and domains == []

    def test_distinct_only(self):
        count, domains = detect_domains(
            ["scripts/a", "scripts/b", "scripts/c"], _DEFAULT_DOMAIN_MAP
        )
        assert count == 1 and domains == ["scripts"]


# ── HOS_DOMAIN_MAP override (binding #4) ─────────────────────────────────────

class TestDomainMapOverride:
    def test_unset_uses_default(self, monkeypatch):
        monkeypatch.delenv("HOS_DOMAIN_MAP", raising=False)
        assert parse_domain_map() == _DEFAULT_DOMAIN_MAP

    def test_wellformed_replaces(self, monkeypatch):
        monkeypatch.setenv("HOS_DOMAIN_MAP", "src/=source;test/=tests")
        assert parse_domain_map() == [("src/", "source"), ("test/", "tests")]

    def test_replace_not_extend(self, monkeypatch):
        # scripts/ is in the default map but NOT in the override → falls to other
        monkeypatch.setenv("HOS_DOMAIN_MAP", "src/=source")
        dm = parse_domain_map()
        assert classify_domain("scripts/x.py", dm) == "other"

    def test_malformed_missing_eq_falls_back(self, monkeypatch):
        monkeypatch.setenv("HOS_DOMAIN_MAP", "broken")
        assert parse_domain_map() == _DEFAULT_DOMAIN_MAP

    def test_malformed_empty_label_falls_back(self, monkeypatch):
        monkeypatch.setenv("HOS_DOMAIN_MAP", "src/=")
        assert parse_domain_map() == _DEFAULT_DOMAIN_MAP

    def test_malformed_empty_prefix_falls_back(self, monkeypatch):
        monkeypatch.setenv("HOS_DOMAIN_MAP", "=label")
        assert parse_domain_map() == _DEFAULT_DOMAIN_MAP

    def test_trailing_separator_tolerated(self, monkeypatch):
        monkeypatch.setenv("HOS_DOMAIN_MAP", "src/=source;")
        assert parse_domain_map() == [("src/", "source")]


# ── CLI parsing (binding #3) ─────────────────────────────────────────────────

class TestParseArgs:
    def test_full(self):
        cl, cf, fl = parse_args(
            ["--changed-lines", "100", "--changed-files", "5",
             "--changed-file-list", "a.py", "b.py"]
        )
        assert (cl, cf, fl) == (100, 5, ["a.py", "b.py"])

    def test_empty_file_list_flag(self):
        cl, cf, fl = parse_args(
            ["--changed-lines", "100", "--changed-files", "5", "--changed-file-list"]
        )
        assert fl == []

    def test_missing_numeric_defaults_zero(self):
        cl, cf, fl = parse_args(["--changed-file-list", "a.py"])
        assert (cl, cf) == (0, 0)

    def test_non_integer_numeric_treated_as_zero(self):
        cl, cf, _ = parse_args(["--changed-lines", "abc", "--changed-files", "5",
                                "--changed-file-list", "a.py"])
        assert cl == 0 and cf == 5

    def test_file_list_consumes_all_trailing(self):
        _, _, fl = parse_args(["--changed-file-list", "a", "b", "c", "d"])
        assert fl == ["a", "b", "c", "d"]


# ── output envelope (binding #2, REQ-377-21/22) ──────────────────────────────

class TestEnvelope:
    def test_ac10_tier_floor_top_level(self):
        r = run(512, 2, ["a.py"])
        assert "tier_floor" in r  # top-level, not only inside raw_value
        assert r["tier_floor"] == "HIGH"

    def test_weight_is_zero_inert(self):
        assert WEIGHTS["diff_size"] == 0.0
        assert run(512, 2, ["a.py"])["weight"] == 0.0

    def test_domain_count_always_present(self):
        r = run(0, 0, [])
        assert r["raw_value"]["domain_count"] == 0
        assert r["raw_value"]["domains_detected"] == []

    def test_make_result_tier_floor_default_none(self):
        # existing call sites that omit tier_floor get null (backward compat)
        r = make_result("x", 0.0, {})
        assert r["tier_floor"] is None

    def test_thresholds_echoed(self):
        r = run(5, 2, ["a.py"], diff_size_floor=400, file_count_floor=15)
        assert r["raw_value"]["thresholds"]["diff_size_floor"] == 400
        assert r["raw_value"]["thresholds"]["file_count_floor"] == 15

    def test_score_always_zero(self):
        assert run(999, 99, ["scripts/a", "docs/b", "packs/c"])["score"] == 0.0
