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

_OVERSEER = "hos-overseer-hos[bot]"
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
    # rn_calculator scores the (fetched) head content as LOW; structural floor of
    # _LOW_FILES is also LOW → max(LOW, LOW) = LOW.
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(rtc, "_fetch_head_python", lambda repo, pr, files, dest: ["x.py"])
    monkeypatch.setattr(rtc, "_try_rn_calculator", lambda paths: "LOW")

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
    # rn_calculator scores the head content above the ceiling.
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(rtc, "_fetch_head_python", lambda repo, pr, files, dest: ["x.py"])
    monkeypatch.setattr(rtc, "_try_rn_calculator", lambda paths: "MEDIUM")

    monkeypatch.setattr(
        sys, "argv", ["require_tier_ceiling.py", "--pr", "42", "--repo", "org/repo"]
    )
    assert rtc.main() == 1


def test_critical_python_pr_caught_above_high_ceiling(monkeypatch):
    """#973 regression: a CRITICAL-tier PR the overseer approved must FAIL even
    with the production HIGH ceiling — the old MEDIUM-capped fallback let it pass."""
    monkeypatch.setattr(rtc, "load_env", lambda _path: _fake_env(ceiling="HIGH"))
    monkeypatch.setattr(rtc, "get_reviews", lambda repo, pr: _APPROVED_REVIEW)
    monkeypatch.setattr(rtc, "get_changed_files", lambda pr: _LOW_FILES)
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(rtc, "_fetch_head_python", lambda repo, pr, files, dest: ["x.py"])
    monkeypatch.setattr(rtc, "_try_rn_calculator", lambda paths: "CRITICAL")

    monkeypatch.setattr(
        sys, "argv", ["require_tier_ceiling.py", "--pr", "42", "--repo", "org/repo"]
    )
    assert rtc.main() == 1


def test_rn_failure_on_python_surface_fails_closed(monkeypatch):
    """A real Python surface that can't be scored (validator error) → exit 2,
    not a fail-open pass."""
    monkeypatch.setattr(rtc, "load_env", lambda _path: _fake_env(ceiling="HIGH"))
    monkeypatch.setattr(rtc, "get_reviews", lambda repo, pr: _APPROVED_REVIEW)
    monkeypatch.setattr(rtc, "get_changed_files", lambda pr: _LOW_FILES)
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(rtc, "_fetch_head_python", lambda repo, pr, files, dest: ["x.py"])
    monkeypatch.setattr(rtc, "_try_rn_calculator", lambda paths: None)

    monkeypatch.setattr(
        sys, "argv", ["require_tier_ceiling.py", "--pr", "42", "--repo", "org/repo"]
    )
    assert rtc.main() == 2


def test_head_fetch_error_fails_closed(monkeypatch):
    """Head-content fetch failure → exit 2 (never guess a tier)."""
    def _boom(repo, pr, files, dest):
        raise rtc._HeadFetchError("api down")

    monkeypatch.setattr(rtc, "load_env", lambda _path: _fake_env(ceiling="HIGH"))
    monkeypatch.setattr(rtc, "get_reviews", lambda repo, pr: _APPROVED_REVIEW)
    monkeypatch.setattr(rtc, "get_changed_files", lambda pr: _LOW_FILES)
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(rtc, "_fetch_head_python", _boom)

    monkeypatch.setattr(
        sys, "argv", ["require_tier_ceiling.py", "--pr", "42", "--repo", "org/repo"]
    )
    assert rtc.main() == 2


def test_no_python_files_uses_structural(monkeypatch):
    """A PR with no .py changes has no code-risk surface → structural estimate;
    head content is never fetched."""
    docs = ["docs/README.md", "config.yaml"]
    monkeypatch.setattr(rtc, "load_env", lambda _path: _fake_env(ceiling="LOW"))
    monkeypatch.setattr(rtc, "get_reviews", lambda repo, pr: _APPROVED_REVIEW)
    monkeypatch.setattr(rtc, "get_changed_files", lambda pr: docs)
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(
        rtc, "_fetch_head_python",
        lambda *a, **k: pytest.fail("must not fetch when no .py files changed"),
    )

    monkeypatch.setattr(
        sys, "argv", ["require_tier_ceiling.py", "--pr", "42", "--repo", "org/repo"]
    )
    assert rtc.main() == 0  # structural LOW ≤ LOW ceiling


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
    reviews = [{"state": "APPROVED", "user": {"login": "HOS-OVERSEER-HOS[BOT]"}}]
    assert rtc.overseer_has_approved(reviews, "hos-overseer-hos[bot]")


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
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n'
        "OVERSEER_CEILING='LOW'\n"
        "TIER_CEILING_CHECK_NAME=require-tier-ceiling\n"
    )
    result = rtc.load_env(env_file)
    assert result["BOT_OVERSEER_USERNAME"] == "hos-overseer-hos[bot]"
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


# ---------------------------------------------------------------------------
# _score_to_tier / _max_tier
# ---------------------------------------------------------------------------

def test_score_to_tier_boundaries():
    # Mirrors schema.py:score_to_tier exclusive-upper-bound semantics.
    assert rtc._score_to_tier(0.0) == "LOW"
    assert rtc._score_to_tier(0.299) == "LOW"
    assert rtc._score_to_tier(0.30) == "MEDIUM"
    assert rtc._score_to_tier(0.549) == "MEDIUM"
    assert rtc._score_to_tier(0.55) == "HIGH"
    assert rtc._score_to_tier(0.779) == "HIGH"
    assert rtc._score_to_tier(0.78) == "CRITICAL"
    assert rtc._score_to_tier(1.0) == "CRITICAL"


def test_max_tier():
    assert rtc._max_tier("LOW", "HIGH", "MEDIUM") == "HIGH"
    assert rtc._max_tier("SAFE", "LOW") == "LOW"
    assert rtc._max_tier("CRITICAL", "HIGH") == "CRITICAL"


# ---------------------------------------------------------------------------
# compute_tier precedence / flooring
# ---------------------------------------------------------------------------

def test_compute_tier_prefers_summary(monkeypatch):
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: "HIGH")
    assert rtc.compute_tier("org/repo", "1", _LOW_FILES) == "HIGH"


def test_compute_tier_floors_rn_by_structural(monkeypatch):
    """rn says LOW but >10 .py files changed → structural MEDIUM floors it up."""
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(rtc, "_fetch_head_python", lambda repo, pr, files, dest: ["x.py"])
    monkeypatch.setattr(rtc, "_try_rn_calculator", lambda paths: "LOW")
    assert rtc.compute_tier("org/repo", "1", _MEDIUM_FILES) == "MEDIUM"


def test_compute_tier_all_python_deleted_uses_structural(monkeypatch):
    """Every changed .py deleted at head → no live surface → structural, and
    rn_calculator is never consulted."""
    monkeypatch.setattr(rtc, "_try_validator_summary", lambda: None)
    monkeypatch.setattr(rtc, "_fetch_head_python", lambda repo, pr, files, dest: [])
    calls: list = []
    monkeypatch.setattr(
        rtc, "_try_rn_calculator", lambda paths: calls.append(1) or "CRITICAL"
    )
    assert rtc.compute_tier("org/repo", "1", _LOW_FILES) == "LOW"
    assert not calls


# ---------------------------------------------------------------------------
# _try_rn_calculator — derives tier from score (rn emits no `tier` key, #973)
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_try_rn_calculator_derives_tier_from_score(monkeypatch):
    monkeypatch.setattr(
        rtc.subprocess, "run",
        lambda *a, **k: _FakeProc(0, json.dumps(
            {"dimension": "risk_number", "score": 0.60, "error": None, "tier_floor": None}
        )),
    )
    assert rtc._try_rn_calculator(["x.py"]) == "HIGH"  # 0.60 → HIGH


def test_try_rn_calculator_honors_tier_floor(monkeypatch):
    monkeypatch.setattr(
        rtc.subprocess, "run",
        lambda *a, **k: _FakeProc(0, json.dumps(
            {"score": 0.10, "error": None, "tier_floor": "MEDIUM"}
        )),
    )
    # score 0.10 → LOW, floored up to MEDIUM by tier_floor.
    assert rtc._try_rn_calculator(["x.py"]) == "MEDIUM"


def test_try_rn_calculator_error_envelope_returns_none(monkeypatch):
    monkeypatch.setattr(
        rtc.subprocess, "run",
        lambda *a, **k: _FakeProc(0, json.dumps(
            {"score": 0.0, "error": "no input files"}
        )),
    )
    assert rtc._try_rn_calculator(["x.py"]) is None


def test_try_rn_calculator_nonzero_exit_returns_none(monkeypatch):
    monkeypatch.setattr(rtc.subprocess, "run", lambda *a, **k: _FakeProc(1, ""))
    assert rtc._try_rn_calculator(["x.py"]) is None


def test_try_rn_calculator_empty_paths_returns_none():
    assert rtc._try_rn_calculator([]) is None


# ---------------------------------------------------------------------------
# _fetch_head_python — DATA-only head fetch, skip deleted, fail-closed on error
# ---------------------------------------------------------------------------

def test_fetch_head_python_skips_deleted(monkeypatch, tmp_path):
    monkeypatch.setattr(rtc, "_pr_head_sha", lambda repo, pr: "deadbeef")

    def _fake_run(cmd, **kw):
        target = cmd[-1]  # repos/o/r/contents/<rel>?ref=...
        if "gone.py" in target:
            return _FakeProc(1, "", "gh: Not Found (HTTP 404)")
        return _FakeProc(0, "y = 2\n")

    monkeypatch.setattr(rtc.subprocess, "run", _fake_run)
    out = rtc._fetch_head_python("o/r", "1", ["live.py", "sub/gone.py"], tmp_path)
    assert len(out) == 1
    assert Path(out[0]).read_text() == "y = 2\n"


def test_fetch_head_python_raises_on_non_404(monkeypatch, tmp_path):
    monkeypatch.setattr(rtc, "_pr_head_sha", lambda repo, pr: "deadbeef")
    monkeypatch.setattr(
        rtc.subprocess, "run",
        lambda *a, **k: _FakeProc(1, "", "gh: Server Error (HTTP 500)"),
    )
    with pytest.raises(rtc._HeadFetchError):
        rtc._fetch_head_python("o/r", "1", ["a.py"], tmp_path)


def test_fetch_head_python_skips_escaping_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(rtc, "_pr_head_sha", lambda repo, pr: "deadbeef")
    called: list = []
    monkeypatch.setattr(
        rtc.subprocess, "run",
        lambda *a, **k: called.append(1) or _FakeProc(0, "z=1\n"),
    )
    out = rtc._fetch_head_python(
        "o/r", "1", ["../escape.py", "/abs.py"], tmp_path
    )
    assert out == []
    assert not called  # both paths rejected before any fetch
