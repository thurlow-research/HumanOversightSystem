"""
Tests for schema.py — the shared output contract.

These are the richest mutation targets in the codebase:
  - normalize():       linear math with clamping edge cases
  - score_to_tier():   boundary comparisons (< vs <=, threshold values)
  - composite_score(): weighted average with error exclusion
  - make_result():     score clamping, default population
"""
import pytest
from schema import make_finding, make_result, normalize, composite_score, score_to_tier, WEIGHTS


# ── normalize() ──────────────────────────────────────────────────────────────

class TestNormalize:
    def test_midpoint(self):
        assert normalize(5.0, 0.0, 10.0) == pytest.approx(0.5)

    def test_at_low_bound(self):
        assert normalize(0.0, 0.0, 10.0) == pytest.approx(0.0)

    def test_at_high_bound(self):
        assert normalize(10.0, 0.0, 10.0) == pytest.approx(1.0)

    def test_below_low_clamped(self):
        assert normalize(-5.0, 0.0, 10.0) == pytest.approx(0.0)

    def test_above_high_clamped(self):
        assert normalize(15.0, 0.0, 10.0) == pytest.approx(1.0)

    def test_degenerate_hi_equals_lo(self):
        # hi <= lo → always 0.0
        assert normalize(5.0, 5.0, 5.0) == pytest.approx(0.0)

    def test_degenerate_hi_less_than_lo(self):
        assert normalize(5.0, 10.0, 5.0) == pytest.approx(0.0)

    def test_three_quarter(self):
        assert normalize(7.5, 0.0, 10.0) == pytest.approx(0.75)

    def test_one_quarter(self):
        assert normalize(2.5, 0.0, 10.0) == pytest.approx(0.25)

    def test_non_zero_origin(self):
        # [10, 20]: value 15 → 0.5
        assert normalize(15.0, 10.0, 20.0) == pytest.approx(0.5)


# ── score_to_tier() — boundary conditions are the key mutation targets ───────

class TestScoreToTier:
    # LOW: score < 0.30
    def test_zero_is_low(self):
        assert score_to_tier(0.0) == "LOW"

    def test_just_below_medium_boundary(self):
        assert score_to_tier(0.299) == "LOW"

    # MEDIUM boundary: 0.30 (inclusive) → MEDIUM, not LOW
    def test_medium_boundary_exact(self):
        assert score_to_tier(0.30) == "MEDIUM"

    def test_mid_medium(self):
        assert score_to_tier(0.40) == "MEDIUM"

    def test_just_below_high_boundary(self):
        assert score_to_tier(0.549) == "MEDIUM"

    # HIGH boundary: 0.55 (inclusive) → HIGH, not MEDIUM
    def test_high_boundary_exact(self):
        assert score_to_tier(0.55) == "HIGH"

    def test_mid_high(self):
        assert score_to_tier(0.65) == "HIGH"

    def test_just_below_critical_boundary(self):
        assert score_to_tier(0.779) == "HIGH"

    # CRITICAL boundary: 0.78 (inclusive) → CRITICAL, not HIGH
    def test_critical_boundary_exact(self):
        assert score_to_tier(0.78) == "CRITICAL"

    def test_mid_critical(self):
        assert score_to_tier(0.90) == "CRITICAL"

    def test_max_score_is_critical(self):
        assert score_to_tier(1.0) == "CRITICAL"

    # Verify tier ordering is monotone
    def test_tier_order(self):
        scores = [0.0, 0.29, 0.30, 0.54, 0.55, 0.77, 0.78, 1.0]
        tiers  = [score_to_tier(s) for s in scores]
        order  = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
        for i in range(len(tiers) - 1):
            assert order[tiers[i]] <= order[tiers[i + 1]], \
                f"tier not monotone at index {i}: {tiers[i]} → {tiers[i+1]}"


# ── composite_score() ────────────────────────────────────────────────────────

class TestCompositeScore:
    def test_empty_list(self):
        assert composite_score([]) == pytest.approx(0.0)

    def test_single_validator(self):
        result = composite_score([make_result("dim", 0.5, {}, weight=1.0)])
        assert result == pytest.approx(0.5)

    def test_equal_weights(self):
        results = [
            make_result("a", 0.2, {}, weight=1.0),
            make_result("b", 0.8, {}, weight=1.0),
        ]
        assert composite_score(results) == pytest.approx(0.5)

    def test_unequal_weights(self):
        # weight 2 @ 0.0 + weight 1 @ 0.9 → (0.0*2 + 0.9*1) / 3 = 0.3
        results = [
            make_result("a", 0.0, {}, weight=2.0),
            make_result("b", 0.9, {}, weight=1.0),
        ]
        assert composite_score(results) == pytest.approx(0.3)

    def test_errored_validators_excluded(self):
        results = [
            make_result("good", 0.6, {}, weight=1.0),
            make_result("bad",  0.0, {}, weight=1.0, error="tool missing"),
        ]
        # Only "good" contributes: 0.6 / 1.0 = 0.6
        assert composite_score(results) == pytest.approx(0.6)

    def test_all_errored_returns_zero(self):
        results = [
            make_result("a", 0.5, {}, weight=1.0, error="err"),
            make_result("b", 0.5, {}, weight=1.0, error="err"),
        ]
        assert composite_score(results) == pytest.approx(0.0)

    def test_score_above_one_clamped_by_make_result(self):
        # make_result clamps score to [0,1] before composite_score sees it
        r = make_result("x", 2.0, {})
        assert r["score"] == pytest.approx(1.0)

    def test_score_below_zero_clamped(self):
        r = make_result("x", -1.0, {})
        assert r["score"] == pytest.approx(0.0)


# ── make_result() — envelope structure ───────────────────────────────────────

class TestMakeResult:
    def test_required_fields_present(self):
        r = make_result("dim", 0.5, {"k": "v"})
        for field in ("dimension", "score", "raw_value", "weight",
                      "evidence", "checklist_items", "findings", "error"):
            assert field in r

    def test_score_rounded_to_4dp(self):
        r = make_result("x", 1/3, {})
        assert r["score"] == pytest.approx(0.3333, abs=1e-4)

    def test_defaults(self):
        r = make_result("x", 0.5, {})
        assert r["evidence"] == []
        assert r["checklist_items"] == []
        assert r["findings"] == []
        assert r["error"] is None
        assert r["weight"] == pytest.approx(1.0)

    def test_dimension_preserved(self):
        assert make_result("complexity", 0.5, {})["dimension"] == "complexity"


# ── make_finding() ────────────────────────────────────────────────────────────

class TestMakeFinding:
    def test_fields(self):
        f = make_finding("auth/views.py", 42, "N+1 query")
        assert f["file"] == "auth/views.py"
        assert f["line"] == 42
        assert f["message"] == "N+1 query"
        assert f["severity"] == "medium"  # default

    def test_severity_override(self):
        f = make_finding("x.py", 1, "msg", severity="high")
        assert f["severity"] == "high"
