"""Tests for the pure-Python reviewer-resolution logic backing #1657:
`scripts/oversight/codeowners.resolve_human_reviewer` and
`scripts/automation/pr_review_cli.evaluate_reviewer_trigger`, plus the
CLI-level fail-closed terminal checks (§4.5 step 7) they feed into.

R1-R12 per docs/v0.7.0/TECHNICAL-DESIGN-1657-overseer-review-objects.md §8.2
and ADR-1657 AD-3/ARCH-9's "must not widen" pin.

`codeowners.py` is loaded by file path (it is not an importable package —
same idiom as `merge_authority_cli._load_codeowners_module`).
`pr_review_cli.py` is a real package module and is imported normally.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest

import scripts.automation.pr_review_cli as cli
from scripts.automation.lib import github as gh
from scripts.automation.lib.merge_authority import RiskTier
from scripts.automation.lib.merge_config import MergeConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_codeowners_module():
    path = REPO_ROOT / "scripts" / "oversight" / "codeowners.py"
    spec = importlib.util.spec_from_file_location("hos_oversight_codeowners_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


codeowners = _load_codeowners_module()


def _write_codeowners(root: Path, lines: list[str]) -> None:
    p = root / ".github" / "CODEOWNERS"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _add_protected_surfaces(root: Path, patterns: list[str]) -> None:
    p = root / "scripts" / "framework" / "protected_surfaces.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(patterns) + "\n", encoding="utf-8")


DEFAULT_BOT_ACCOUNTS = {"hos-worker-hos[bot]", "hos-overseer-hos[bot]"}
DEFAULT_HUMAN_REVIEWER = "hos-default-human"


# --------------------------------------------------------------------------- #
# R1-R11 — resolve_human_reviewer
# --------------------------------------------------------------------------- #


def test_r1_protected_path_resolves_codeowners_user(tmp_path):
    _write_codeowners(tmp_path, ["/some/path/** @carol"])
    resolution = codeowners.resolve_human_reviewer(
        ["some/path/file.py"], tmp_path, DEFAULT_BOT_ACCOUNTS, DEFAULT_HUMAN_REVIEWER
    )
    assert resolution.login == "carol"
    assert resolution.source == "codeowners"


def test_r2_team_only_owner_falls_back_and_records_team(tmp_path):
    _write_codeowners(tmp_path, ["/team/** @org/team-a"])
    resolution = codeowners.resolve_human_reviewer(
        ["team/file.py"], tmp_path, DEFAULT_BOT_ACCOUNTS, DEFAULT_HUMAN_REVIEWER
    )
    assert resolution.login == DEFAULT_HUMAN_REVIEWER
    assert resolution.source == "machine-accounts.env"
    assert resolution.codeowners_team_owners == ["@org/team-a"]


def test_r3_bot_only_owner_falls_back_bot_never_returned(tmp_path):
    _write_codeowners(tmp_path, ["/bots/** @hos-worker-hos[bot]"])
    resolution = codeowners.resolve_human_reviewer(
        ["bots/file.py"], tmp_path, DEFAULT_BOT_ACCOUNTS, DEFAULT_HUMAN_REVIEWER
    )
    assert resolution.login == DEFAULT_HUMAN_REVIEWER
    assert resolution.login != "hos-worker-hos[bot]"
    assert resolution.source == "machine-accounts.env"


def test_r4_no_codeowners_file_falls_back(tmp_path):
    resolution = codeowners.resolve_human_reviewer(
        ["x.py"], tmp_path, DEFAULT_BOT_ACCOUNTS, DEFAULT_HUMAN_REVIEWER
    )
    assert resolution.login == DEFAULT_HUMAN_REVIEWER
    assert resolution.note == "no CODEOWNERS file"


def test_r5_no_entry_matches_falls_back(tmp_path):
    _write_codeowners(tmp_path, ["/other/** @carol"])
    resolution = codeowners.resolve_human_reviewer(
        ["nomatch.py"], tmp_path, DEFAULT_BOT_ACCOUNTS, DEFAULT_HUMAN_REVIEWER
    )
    assert resolution.login == DEFAULT_HUMAN_REVIEWER
    assert resolution.note == "no CODEOWNERS entry matched the changed files"


def test_r6_email_owner_not_returned_falls_back(tmp_path):
    _write_codeowners(tmp_path, ["/docs/** dev@example.com"])
    resolution = codeowners.resolve_human_reviewer(
        ["docs/readme.md"], tmp_path, DEFAULT_BOT_ACCOUNTS, DEFAULT_HUMAN_REVIEWER
    )
    assert resolution.login == DEFAULT_HUMAN_REVIEWER
    assert resolution.login != "dev@example.com"
    assert "e-mail" in resolution.note


def test_r10_last_match_wins(tmp_path):
    _write_codeowners(tmp_path, ["/dup/** @first", "/dup/** @second"])
    resolution = codeowners.resolve_human_reviewer(
        ["dup/file.py"], tmp_path, DEFAULT_BOT_ACCOUNTS, DEFAULT_HUMAN_REVIEWER
    )
    assert resolution.login == "second"


def test_r11_determinism_across_input_orderings(tmp_path):
    _write_codeowners(tmp_path, ["/aaa/** @alice", "/bbb/** @bob"])
    orderings = [
        ["aaa/file.py", "bbb/file.py"],
        ["bbb/file.py", "aaa/file.py"],
        ["aaa/file.py", "bbb/file.py", "aaa/file.py"],
    ]
    results = {
        codeowners.resolve_human_reviewer(
            files, tmp_path, DEFAULT_BOT_ACCOUNTS, DEFAULT_HUMAN_REVIEWER
        ).login
        for files in orderings
    }
    assert len(results) == 1, results


def test_r13_mixed_team_and_human_owner_resolves_to_human(tmp_path):
    """A single CODEOWNERS line with a team owner co-listed with a human
    owner (`@org/team @carol`) must resolve to the human — the mixed-
    owner-type case the code-reviewer self-flagged MEDIUM confidence on
    for #1657 PR-1, hand-traced correct but previously unpinned."""
    _write_codeowners(tmp_path, ["/mixed/** @org/team @carol"])
    resolution = codeowners.resolve_human_reviewer(
        ["mixed/file.py"], tmp_path, DEFAULT_BOT_ACCOUNTS, DEFAULT_HUMAN_REVIEWER
    )
    assert resolution.login == "carol"
    assert resolution.source == "codeowners"
    assert resolution.codeowners_team_owners == ["@org/team"]


def test_r13_mixed_bot_and_human_owner_resolves_to_human(tmp_path):
    """Same case with a bot account co-listed instead of a team
    (`@bot-account @carol`) — the bot must never be returned."""
    bot_accounts = DEFAULT_BOT_ACCOUNTS | {"bot-account"}
    _write_codeowners(tmp_path, ["/mixed/** @bot-account @carol"])
    resolution = codeowners.resolve_human_reviewer(
        ["mixed/file.py"], tmp_path, bot_accounts, DEFAULT_HUMAN_REVIEWER
    )
    assert resolution.login == "carol"
    assert resolution.login != "bot-account"
    assert resolution.source == "codeowners"


# --------------------------------------------------------------------------- #
# R7-R9 — pr_review_cli's fail-closed terminal checks (§4.5 step 7), exercised
# directly against _cmd_request_reviewer so the guard is verified regardless
# of whether merge_config's own required-key gate would also have caught the
# misconfiguration upstream.
# --------------------------------------------------------------------------- #


def _make_ctx(
    tmp_path, *, human_reviewer=DEFAULT_HUMAN_REVIEWER, bot_accounts=None, ceiling="HIGH"
):
    config = MergeConfig(
        overseer_ceiling=RiskTier.from_str(ceiling),
        human_reviewer=human_reviewer,
        overseer_handle="hos-overseer-hos[bot]",
        worker_handle="hos-worker-hos[bot]",
        bot_accounts=frozenset(bot_accounts or DEFAULT_BOT_ACCOUNTS),
        tier_ceiling_check_name="require-tier-ceiling",
        config_source="test-fixture",
    )
    return cli._Context(repo_root=tmp_path, config=config, app_role="overseer")


def _make_args(tier="CRITICAL", reviewer=None, pr=42, repo="test-owner/test-repo"):
    return argparse.Namespace(app="overseer", repo=repo, pr=pr, tier=tier, reviewer=reviewer)


@pytest.fixture
def preamble_mocks(monkeypatch, tmp_path):
    """A PR whose changed files trigger the reviewer request (CRITICAL tier),
    with no CODEOWNERS entry matching, so resolve_human_reviewer falls back
    to whatever `human_reviewer` the test's ctx carries."""
    _add_protected_surfaces(tmp_path, [".claude/agents/**"])
    monkeypatch.setenv("HOS_BOT_LOGIN", "hos-overseer-hos[bot]")
    monkeypatch.setattr(
        gh,
        "get_pull",
        lambda o, r, n: {
            "head": {"sha": "sha1"},
            "user": {"login": "some-pr-author"},
            "requested_reviewers": [],
        },
    )
    monkeypatch.setattr(gh, "list_pull_reviews", lambda o, r, n: [])
    monkeypatch.setattr(gh, "list_pull_files", lambda o, r, n: [{"filename": "README.md"}])


def test_r7_empty_human_reviewer_errors_never_returns_empty(tmp_path, preamble_mocks):
    ctx = _make_ctx(tmp_path, human_reviewer="")
    outcome = cli._cmd_request_reviewer(_make_args(), ctx)
    assert outcome.exit_code == 1
    assert outcome.payload.get("resolved_reviewer") != ""
    assert "empty" in (outcome.error or "")


def test_r7_whitespace_human_reviewer_errors(tmp_path, preamble_mocks):
    ctx = _make_ctx(tmp_path, human_reviewer="   ")
    outcome = cli._cmd_request_reviewer(_make_args(), ctx)
    assert outcome.exit_code == 1


def test_r8_bot_resolved_login_errors_never_returned(tmp_path, preamble_mocks):
    ctx = _make_ctx(tmp_path, human_reviewer="hos-worker-hos[bot]")
    outcome = cli._cmd_request_reviewer(_make_args(), ctx)
    assert outcome.exit_code == 1
    assert "bot" in (outcome.error or "").lower()


def test_r9_resolved_login_equal_to_pr_author_errors(tmp_path, monkeypatch):
    _add_protected_surfaces(tmp_path, [".claude/agents/**"])
    monkeypatch.setenv("HOS_BOT_LOGIN", "hos-overseer-hos[bot]")
    monkeypatch.setattr(
        gh,
        "get_pull",
        lambda o, r, n: {
            "head": {"sha": "sha1"},
            "user": {"login": DEFAULT_HUMAN_REVIEWER},
            "requested_reviewers": [],
        },
    )
    monkeypatch.setattr(gh, "list_pull_reviews", lambda o, r, n: [])
    monkeypatch.setattr(gh, "list_pull_files", lambda o, r, n: [{"filename": "README.md"}])
    ctx = _make_ctx(tmp_path)
    outcome = cli._cmd_request_reviewer(_make_args(), ctx)
    assert outcome.exit_code == 1
    assert "author" in (outcome.error or "").lower()


# --------------------------------------------------------------------------- #
# R12 — evaluate_reviewer_trigger: the "must not widen" pin at the predicate
# level (ADR-1657 AD-3). Ten explicit rows: {SAFE, LOW, MEDIUM, HIGH,
# CRITICAL} x {protected file, non-protected file}, ceiling == HIGH.
# --------------------------------------------------------------------------- #


@pytest.fixture
def surfaces_root(tmp_path):
    _add_protected_surfaces(tmp_path, [".claude/agents/**"])
    return tmp_path


_TIERS = ("SAFE", "LOW", "MEDIUM", "HIGH", "CRITICAL")
PROTECTED_FILE = ".claude/agents/overseer.md"
NON_PROTECTED_FILE = "README.md"

# (tier, is_protected) -> expected (above_ceiling, critical_tier, protected_surface, triggered)
_EXPECTED = {
    ("SAFE", False): (False, False, False, False),
    ("LOW", False): (False, False, False, False),
    ("MEDIUM", False): (False, False, False, False),
    ("HIGH", False): (False, False, False, False),
    ("CRITICAL", False): (True, True, False, True),
    ("SAFE", True): (False, False, True, True),
    ("LOW", True): (False, False, True, True),
    ("MEDIUM", True): (False, False, True, True),
    ("HIGH", True): (False, False, True, True),
    ("CRITICAL", True): (True, True, True, True),
}


@pytest.mark.parametrize("tier", _TIERS)
@pytest.mark.parametrize("is_protected", [False, True])
def test_r12_trigger_predicate_cross_product(tier, is_protected, surfaces_root):
    changed_files = [PROTECTED_FILE if is_protected else NON_PROTECTED_FILE]
    result = cli.evaluate_reviewer_trigger(tier, "HIGH", changed_files, surfaces_root)
    expected_above, expected_critical, expected_protected, expected_triggered = _EXPECTED[
        (tier, is_protected)
    ]
    assert result.above_ceiling == expected_above, (tier, is_protected, result)
    assert result.critical_tier == expected_critical, (tier, is_protected, result)
    assert result.protected_surface == expected_protected, (tier, is_protected, result)
    assert result.triggered == expected_triggered, (tier, is_protected, result)


def test_r12_at_or_below_ceiling_non_protected_never_triggers(surfaces_root):
    """The mechanical statement of the ruling's scoping: every at-or-below-
    ceiling, non-protected cell is triggered == False. Changing a cell here
    requires editing this test, which is the point (ADR-1657 AD-3)."""
    for tier in ("SAFE", "LOW", "MEDIUM", "HIGH"):
        result = cli.evaluate_reviewer_trigger(tier, "HIGH", [NON_PROTECTED_FILE], surfaces_root)
        assert result.triggered is False, (tier, result)
