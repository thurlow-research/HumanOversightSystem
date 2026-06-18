"""
Unit tests for config_resolver.py — 4-layer resolve + narrow-only enforcement (R13.1).
"""

import json
import os
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from scripts.automation.lib.config_resolver import (
    EffectiveConfig,
    _narrow_allowlist,
    _narrow_enabled,
    _narrow_mode,
    _narrow_thresholds,
    _normalize_keys,
    resolve,
)


# ---------------------------------------------------------------------------
# Key normalization
# ---------------------------------------------------------------------------

class TestNormalizeKeys:
    def test_hyphens_replaced_by_underscores(self):
        d = {"self-review": {"cross-vendor": True}, "per-task-tokens": 100}
        result = _normalize_keys(d)
        assert "self_review" in result
        assert "cross_vendor" in result["self_review"]
        assert "per_task_tokens" in result

    def test_list_values_recursed(self):
        d = {"some-list": [{"nested-key": "val"}]}
        result = _normalize_keys(d)
        assert result["some_list"][0]["nested_key"] == "val"

    def test_scalar_unchanged(self):
        assert _normalize_keys("hello") == "hello"
        assert _normalize_keys(42) == 42


# ---------------------------------------------------------------------------
# Narrow-only primitives
# ---------------------------------------------------------------------------

class TestNarrowEnabled:
    def test_false_and_true_returns_false(self):
        assert _narrow_enabled(False, True) is False

    def test_true_and_false_returns_false(self):
        assert _narrow_enabled(True, False) is False

    def test_true_and_true_returns_true(self):
        assert _narrow_enabled(True, True) is True

    def test_false_and_false_returns_false(self):
        assert _narrow_enabled(False, False) is False


class TestNarrowMode:
    def test_propose_only_base_wins(self):
        assert _narrow_mode("propose-only", "autonomous") == "propose-only"

    def test_propose_only_overlay_wins(self):
        assert _narrow_mode("autonomous", "propose-only") == "propose-only"

    def test_autonomous_stays_if_both_autonomous(self):
        assert _narrow_mode("autonomous", "autonomous") == "autonomous"


class TestNarrowAllowlist:
    def test_intersection_used(self):
        result = _narrow_allowlist(["alice", "bob"], ["bob", "carol"])
        assert sorted(result) == ["bob"]

    def test_empty_overlay_returns_empty(self):
        result = _narrow_allowlist(["alice"], [])
        assert result == []

    def test_empty_base_returns_overlay(self):
        result = _narrow_allowlist([], ["alice"])
        assert result == ["alice"]


class TestNarrowThresholds:
    def test_budget_uses_min(self):
        result = _narrow_thresholds(
            {"per_task_tokens": 200_000},
            {"per_task_tokens": 100_000},
        )
        assert result["per_task_tokens"] == 100_000

    def test_confidence_floor_uses_max(self):
        result = _narrow_thresholds(
            {"triage_confidence_floor": 0.5},
            {"triage_confidence_floor": 0.9},
        )
        assert result["triage_confidence_floor"] == pytest.approx(0.9)

    def test_floor_cannot_be_lowered_by_overlay(self):
        """A later layer trying to lower a confidence floor is a widen — must be ignored."""
        result = _narrow_thresholds(
            {"triage_confidence_floor": 0.8},
            {"triage_confidence_floor": 0.3},  # attempt to lower the floor
        )
        assert result["triage_confidence_floor"] == pytest.approx(0.8)

    def test_budget_cannot_be_raised_by_overlay(self):
        """A later layer trying to raise a budget is a widen — must be ignored."""
        result = _narrow_thresholds(
            {"per_task_tokens": 100_000},
            {"per_task_tokens": 200_000},  # attempt to widen the budget
        )
        assert result["per_task_tokens"] == 100_000


# ---------------------------------------------------------------------------
# resolve() — full integration via temp files
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content), encoding="utf-8")


class TestResolve:
    def test_defaults_are_inert(self):
        """Without any governance config, the resolved config is disabled."""
        config = resolve(Path("/nonexistent-repo-root-that-has-no-project-dir"))
        assert config.enabled is False
        assert config.mode == "propose-only"

    def test_governance_enabled_true_resolves(self, tmp_path):
        _write_yaml(
            tmp_path / "PROJECT" / "hos-coordination.yaml",
            """\
            enabled: true
            customer: cps
            requester-allowlist:
              - ScottThurlow
            """,
        )
        config = resolve(tmp_path)
        assert config.enabled is True
        assert config.customer == "cps"
        assert "ScottThurlow" in config.requester_allowlist

    def test_enabled_false_in_defaults_cannot_be_widened_by_env(self, tmp_path):
        """HOS_AUTO_ENABLED=true cannot override a governance-layer enabled=false."""
        # No governance config → defaults enabled=false.
        with patch.dict(os.environ, {"HOS_AUTO_ENABLED": "true"}):
            config = resolve(tmp_path)
        assert config.enabled is False

    def test_governance_false_overrides_env_true(self, tmp_path):
        _write_yaml(
            tmp_path / "PROJECT" / "hos-coordination.yaml",
            "enabled: false\n",
        )
        with patch.dict(os.environ, {"HOS_AUTO_ENABLED": "true"}):
            config = resolve(tmp_path)
        assert config.enabled is False

    def test_budget_narrowed_by_governance(self, tmp_path):
        _write_yaml(
            tmp_path / "PROJECT" / "hos-coordination.yaml",
            """\
            enabled: true
            thresholds:
              per-task-tokens: 80000
            """,
        )
        config = resolve(tmp_path)
        assert config.thresholds.per_task_tokens == 80_000

    def test_confidence_floor_raised_by_governance(self, tmp_path):
        _write_yaml(
            tmp_path / "PROJECT" / "hos-coordination.yaml",
            """\
            enabled: true
            thresholds:
              triage-confidence-floor: 0.9
            """,
        )
        config = resolve(tmp_path)
        assert config.thresholds.triage_confidence_floor == pytest.approx(0.9)

    def test_allowlist_is_intersection(self, tmp_path):
        """governance narrowing: base=[], overlay=[alice] → [alice]; then intersection."""
        _write_yaml(
            tmp_path / "PROJECT" / "hos-coordination.yaml",
            """\
            enabled: true
            requester-allowlist:
              - alice
              - bob
            """,
        )
        config = resolve(tmp_path)
        # Base has [] — intersection with [alice, bob] = [alice, bob].
        assert set(config.requester_allowlist) == {"alice", "bob"}

    def test_mode_forced_to_propose_only_by_governance(self, tmp_path):
        _write_yaml(
            tmp_path / "PROJECT" / "hos-coordination.yaml",
            "mode: propose-only\n",
        )
        config = resolve(tmp_path)
        assert config.mode == "propose-only"

    def test_soft_state_cadence_only_not_governance(self, tmp_path):
        """Soft state cannot set governance fields."""
        soft_dir = tmp_path / ".ai-local" / "hos-automation"
        soft_dir.mkdir(parents=True)
        (soft_dir / "cadence-state.json").write_text(
            json.dumps({"enabled": True, "cadence_backoff_level": 2}),
            encoding="utf-8",
        )
        config = resolve(tmp_path)
        # enabled stays False — soft state cannot widen it.
        assert config.enabled is False

    def test_defaults_have_correct_orchestrator_lock_timeout(self):
        """The orchestrator lock timeout must be 20m (ADR-3), not 4h."""
        config = resolve(Path("/nonexistent"))
        assert config.orchestrator_lock_timeout == "20m"
        assert config.breakers.max_task_runtime == "4h"

    def test_defaults_disable_is_canonical(self):
        """A fresh config carries all expected safe defaults."""
        config = resolve(Path("/nonexistent"))
        assert config.enabled is False
        assert config.mode == "propose-only"
        assert config.requester_allowlist == []
        assert config.thresholds.per_task_tokens == 150_000
        assert config.thresholds.triage_confidence_floor == pytest.approx(0.75)
        assert config.cadence.floor == "15m"
        assert config.cadence.ceiling == "24h"
        assert config.breakers.per_issue_failures == 3
