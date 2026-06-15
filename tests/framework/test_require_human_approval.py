"""Tests for the §9 protected-surface human-approval gate.

Covers the glob matcher (each protected class matches; near-misses don't) and the
bot-vs-human approval logic — the load-bearing determination-honesty check.
"""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "require_human_approval",
    Path(__file__).resolve().parents[2] / "scripts" / "framework" / "require_human_approval.py",
)
rha = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rha)

GLOBS = rha.load_globs(rha.SURFACES_FILE)


# ── Glob matching ────────────────────────────────────────────────────────────
def _matches(path: str) -> bool:
    return bool(rha.matched_surfaces([path], GLOBS))


def test_protected_dir_globs_match():
    for p in [
        ".claude/agents/risk-assessor.md",
        "contract/OVERSIGHT-CONTRACT.md",
        "bootstrap/hos_install.sh",
        "scripts/framework/cut_release.sh",
        "scripts/oversight/gates/secret_scan.sh",
        ".github/workflows/ci.yml",
    ]:
        assert _matches(p), f"{p} should be protected"


def test_protected_exact_files_match():
    for p in [
        "AGENTS.md",
        "docs/METHODOLOGY.md",
        "docs/AGENT-IDENTITY.md",
        "scripts/oversight/run_validators.sh",
        "scripts/oversight/validators/schema.py",
        ".github/CODEOWNERS",
    ]:
        assert _matches(p), f"{p} should be protected"


def test_near_misses_do_not_match():
    # Anchored matching must not over-match lookalikes.
    for p in [
        "AGENTS-GUIDE.md",                                  # not AGENTS.md
        "scripts/oversight/validators/rn_calculator.py",   # only schema.py is protected
        "scripts/run_second_review.sh",                    # not under scripts/oversight/gates
        "docs/QUICKSTART.md",                              # not a protected doc
        "README.md",
        "research/findings/x.md",
        "src/app.py",
    ]:
        assert not _matches(p), f"{p} should NOT be protected"


# ── Approval logic ───────────────────────────────────────────────────────────
def test_human_approval_present_excludes_bots():
    reviews = [
        {"state": "APPROVED", "user": {"login": "hos-oversight"}},
        {"state": "APPROVED", "user": {"login": "ScottThurlow"}},
    ]
    bots = {"hos-worker", "hos-oversight"}
    assert rha.human_approval_present(reviews, bots) == ["ScottThurlow"]


def test_only_bot_approval_is_not_human():
    reviews = [{"state": "APPROVED", "user": {"login": "hos-oversight"}}]
    assert rha.human_approval_present(reviews, {"hos-oversight"}) == []


def test_non_approved_states_ignored():
    reviews = [
        {"state": "COMMENTED", "user": {"login": "ScottThurlow"}},
        {"state": "CHANGES_REQUESTED", "user": {"login": "ScottThurlow"}},
    ]
    assert rha.human_approval_present(reviews, set()) == []


def test_empty_bot_set_treats_any_approval_as_human():
    # Safe-degrade: before bot handles are configured, any approval counts.
    reviews = [{"state": "APPROVED", "user": {"login": "anyone"}}]
    assert rha.human_approval_present(reviews, set()) == ["anyone"]
