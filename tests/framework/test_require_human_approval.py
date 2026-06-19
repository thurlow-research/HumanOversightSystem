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
        "METHODOLOGY.md",
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


# ── AC-06: copilot[bot] APPROVED is rejected as non-human (REQ-255-23) ────────
# This test exercises the real env-sourcing path: it sets the BOT_ACCOUNTS env
# var (as machine-accounts.env would do when sourced into the environment) and
# then calls human_approval_present with the bot set loaded from the environment.
def test_copilot_bot_approved_is_not_human():
    """copilot[bot] must be excluded from human approvals even when it APPROVED.

    REQ-255-22/23: copilot[bot] is a bot identity; its APPROVED review is
    advisory only and must never satisfy the human-approval gate.
    """
    import os
    # Simulate sourcing machine-accounts.env: set BOT_ACCOUNTS in the environment
    os.environ["BOT_ACCOUNTS"] = "hos-worker-hos[bot] hos-overseer-hos[bot] copilot[bot]"
    try:
        # Load the bot set from env exactly as require_human_approval.py does (L182).
        bot_accounts = set(os.environ.get("BOT_ACCOUNTS", "").split())
        reviews = [
            {"state": "APPROVED", "user": {"login": "copilot[bot]"}},
        ]
        # copilot[bot] is in BOT_ACCOUNTS → must be excluded → empty human list
        result = rha.human_approval_present(reviews, bot_accounts)
        assert result == [], (
            f"copilot[bot] APPROVED should not count as human; got {result}"
        )
    finally:
        os.environ.pop("BOT_ACCOUNTS", None)


def test_copilot_bot_approved_does_not_block_human_approval():
    """When both copilot[bot] and a human approve, the human approval stands."""
    import os
    os.environ["BOT_ACCOUNTS"] = "hos-worker-hos[bot] hos-overseer-hos[bot] copilot[bot]"
    try:
        bot_accounts = set(os.environ.get("BOT_ACCOUNTS", "").split())
        reviews = [
            {"state": "APPROVED", "user": {"login": "copilot[bot]"}},
            {"state": "APPROVED", "user": {"login": "ScottThurlow"}},
        ]
        result = rha.human_approval_present(reviews, bot_accounts)
        assert result == ["ScottThurlow"], (
            f"Human approval alongside copilot should count; got {result}"
        )
    finally:
        os.environ.pop("BOT_ACCOUNTS", None)


def test_copilot_exact_login_match():
    """Exact-string matching on 'copilot[bot]' — the brackets are literal."""
    # 'copilot' without brackets must NOT be excluded if COPILOT_BOT_LOGIN="copilot[bot]"
    # (GitHub returns the login as 'copilot[bot]'; plain 'copilot' would be a different user)
    bot_accounts = {"copilot[bot]"}
    reviews_bare = [{"state": "APPROVED", "user": {"login": "copilot"}}]
    # 'copilot' (no brackets) is NOT in bot_accounts → treated as human
    result = rha.human_approval_present(reviews_bare, bot_accounts)
    assert "copilot" in result, "bare 'copilot' (not the bot) should be treated as human"

    # 'copilot[bot]' IS in bot_accounts → excluded
    reviews_bot = [{"state": "APPROVED", "user": {"login": "copilot[bot]"}}]
    result_bot = rha.human_approval_present(reviews_bot, bot_accounts)
    assert result_bot == [], "copilot[bot] must be excluded"
