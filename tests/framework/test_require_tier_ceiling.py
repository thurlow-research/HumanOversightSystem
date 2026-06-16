"""Tests for the overseer tier-ceiling gate (require_tier_ceiling.py).

Covers:
  - No overseer approval → gate passes (exit 0)
  - Overseer approved, tier ≤ ceiling → gate passes (exit 0)
  - Overseer approved, tier > ceiling → gate fails (exit 1)
  - Missing machine-accounts.env → fail-closed (exit 2)

All tests are fully offline: no git, no `gh` calls. Network calls are patched
via monkeypatching the module's helper functions directly.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load the module under test via file path (matches test_require_human_approval.py
# pattern so it works without the package on sys.path).
# ---------------------------------------------------------------------------

_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "framework"
    / "require_tier_ceiling.py"
)
_SPEC = importlib.util.spec_from_file_location("require_tier_ceiling", _MODULE_PATH)
rtc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rtc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OVERSEER = "HOSOversightTutelare"
_CEILING = "LOW"

_APPROVED_REVIEW = [{"state": "APPROVED", "user": {"login": _OVERSEER}}]
_DISMISSED_REVIEW = [{"state": "DISMISSED", "user": {"login": _OVERSEER}}]
_HUMAN_REVIEW = [{"state": "APPROVED", "user": {"login": "ScottThurlow"}}]
_NO_REVIEWS: list = []

_LOW_FILES = ["src/foo.py", "src/bar.py"]
_MEDIUM_FILES = [f"src/file{i}.py" for i in range(11)]  # >10 → MEDIUM fallback


def _fake_env(overseer: str = _OVERSEER, ceiling: str = _CEILING) -> dict:
    return {"BOT_OVERSEER_USERNAME": overseer, "OVERSEER_CEILING": ceiling}


# ---------------------------------------------------------------------------
# test_no_overseer_approval_passes
# ---------------------------------------------------------------------------

def test_no_overseer_approval_passes(monkeypatch):
    """No APPROVED review from the overseer → ceiling is N/A → returns 0."""
    monkeypatch.setattr(rtc, "load_env", lambda _path: _fake_env())
    monkeypatch.setattr(rtc, "get_reviews", lambda repo, pr: _HUMAN_REVIEW)
    monkeypatch.setattr(rtc, "get_changed_files", lambda pr: _LOW_FILES)

    monkeypatch.setattr(
        sys, "argv", ["require_tier_ceiling.py", "--pr", "42", "--repo", "org/repo"]
    )
    assert rtc.main() == 0


# ---------------------------------------------------------------------------
# test_low_tier_overseer_approval_passes
# ---------------------------------------------------------------------------

def test_low_tier_overseer_approval_passes(monkeypatch):
    """Overseer approved, tier=LOW, ceiling=LOW → returns 0 (at-ceiling is allowed)."""
    monkeypatch.setattr(rtc, "load_env", lambda _path: _fake_env(ceiling="LOW"))
    monkeypatch.setattr(rtc, "get_reviews", lambda repo, pr: _APPROVED_REVIEW)
    monkeypatch.setattr(rtc, "get_changed_files", lambda pr: _LOW_FILES)
    # Force simplified_tier to return LOW (files have no agents/ path, <10 .py files)
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(rtc, "_try_rn_calculator", lambda files: None)

    monkeypatch.setattr(
        sys, "argv", ["require_tier_ceiling.py", "--pr", "42", "--repo", "org/repo"]
    )
    assert rtc.main() == 0


# ---------------------------------------------------------------------------
# test_above_ceiling_fails
# ---------------------------------------------------------------------------

def test_above_ceiling_fails(monkeypatch):
    """Overseer approved, tier=MEDIUM, ceiling=LOW → returns 1 (above ceiling)."""
    monkeypatch.setattr(rtc, "load_env", lambda _path: _fake_env(ceiling="LOW"))
    monkeypatch.setattr(rtc, "get_reviews", lambda repo, pr: _APPROVED_REVIEW)
    monkeypatch.setattr(rtc, "get_changed_files", lambda pr: _MEDIUM_FILES)
    # Force tier to MEDIUM via simplified tier (>10 .py files)
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(rtc, "_try_rn_calculator", lambda files: None)

    monkeypatch.setattr(
        sys, "argv", ["require_tier_ceiling.py", "--pr", "42", "--repo", "org/repo"]
    )
    assert rtc.main() == 1


# ---------------------------------------------------------------------------
# test_missing_env_fails_closed
# ---------------------------------------------------------------------------

def test_missing_env_fails_closed(monkeypatch, tmp_path):
    """No machine-accounts.env → exit 2 (fail-closed)."""
    # load_env calls sys.exit(2) directly when the file is missing
    missing = tmp_path / "no-such-file.env"
    monkeypatch.setattr(rtc, "ENV_FILE", missing)

    monkeypatch.setattr(
        sys, "argv", ["require_tier_ceiling.py", "--pr", "42", "--repo", "org/repo"]
    )
    with pytest.raises(SystemExit) as exc_info:
        rtc.main()
    assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# Additional unit-level tests for helper functions
# ---------------------------------------------------------------------------

def test_overseer_has_approved_case_insensitive():
    reviews = [{"state": "APPROVED", "user": {"login": "HOSOversightTutelare"}}]
    assert rtc.overseer_has_approved(reviews, "hosoversighttutelare")


def test_overseer_dismissed_not_approved():
    reviews = [{"state": "DISMISSED", "user": {"login": _OVERSEER}}]
    assert not rtc.overseer_has_approved(reviews, _OVERSEER)


def test_tier_exceeds_ceiling_ordering():
    assert rtc.tier_exceeds_ceiling("MEDIUM", "LOW")
    assert rtc.tier_exceeds_ceiling("HIGH", "MEDIUM")
    assert not rtc.tier_exceeds_ceiling("LOW", "LOW")
    assert not rtc.tier_exceeds_ceiling("LOW", "MEDIUM")
    assert rtc.tier_exceeds_ceiling("CRITICAL", "HIGH")


def test_simplified_tier_agent_path():
    files = [".claude/agents/risk-assessor.md", "src/foo.py"]
    assert rtc._simplified_tier(files) == "MEDIUM"


def test_simplified_tier_many_py_files():
    files = [f"src/file{i}.py" for i in range(11)]
    assert rtc._simplified_tier(files) == "MEDIUM"


def test_simplified_tier_small_change():
    files = ["src/foo.py", "docs/README.md"]
    assert rtc._simplified_tier(files) == "LOW"


def test_load_env_parses_quoted_values(tmp_path):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text(
        '# comment\n'
        'BOT_OVERSEER_USERNAME="HOSOversightTutelare"\n'
        "OVERSEER_CEILING='LOW'\n"
        "TIER_CEILING_CHECK_NAME=require-tier-ceiling\n"
    )
    result = rtc.load_env(env_file)
    assert result["BOT_OVERSEER_USERNAME"] == "HOSOversightTutelare"
    assert result["OVERSEER_CEILING"] == "LOW"
    assert result["TIER_CEILING_CHECK_NAME"] == "require-tier-ceiling"


def test_try_validator_summary_reads_tier(tmp_path, monkeypatch):
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"tier": "HIGH", "score": 0.60}))
    monkeypatch.chdir(tmp_path)
    # summary.json must be at .claudetmp/oversight/validators/summary.json
    dest = tmp_path / ".claudetmp" / "oversight" / "validators"
    dest.mkdir(parents=True)
    (dest / "summary.json").write_text(json.dumps({"tier": "HIGH"}))
    result = rtc._try_validator_summary()
    assert result == "HIGH"
