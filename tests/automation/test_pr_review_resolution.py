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
import subprocess
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


def _init_git_origin(root: Path, slug: str = "test-owner/test-repo") -> None:
    """A real (if minimal) git checkout with an `origin` remote matching
    `_make_args`'s default explicit --repo, so MUST_FIX 2's repo-scope-match
    check (#1657 PR-1 review round 4) has something real to compare against
    — `_cmd_request_reviewer` now always resolves the checkout's own origin
    whenever --repo is explicit, even though that value is never itself used
    as the git remote target here (it never shells out further)."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin", f"https://github.com/{slug}.git"],
        check=True,
    )


def _make_ctx(
    tmp_path, *, human_reviewer=DEFAULT_HUMAN_REVIEWER, bot_accounts=None, ceiling="HIGH"
):
    _init_git_origin(tmp_path)
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


# --------------------------------------------------------------------------- #
# S1-S4 — Finding 1 (#1657 codex adversarial-security second review, CWE-863):
# G0b, the identity-match gate. Exercised directly against
# `cli._cmd_submit_verdict` (not through the bash wrapper) so the gate is
# proven to hold on a direct L2 invocation, which is the whole point of the
# finding — a caller invoking `python -m scripts.automation.pr_review_cli`
# (or any other path that never goes through bootstrap/pr_review.sh) must be
# refused exactly the same way.
# --------------------------------------------------------------------------- #

DEFAULT_OVERSEER_HANDLE = "hos-overseer-hos[bot]"
DEFAULT_PR_AUTHOR = "some-pr-author"


def _make_submit_ctx(tmp_path, *, overseer_handle=DEFAULT_OVERSEER_HANDLE, ceiling="HIGH"):
    _init_git_origin(tmp_path)
    config = MergeConfig(
        overseer_ceiling=RiskTier.from_str(ceiling),
        human_reviewer=DEFAULT_HUMAN_REVIEWER,
        overseer_handle=overseer_handle,
        worker_handle="hos-worker-hos[bot]",
        bot_accounts=frozenset(DEFAULT_BOT_ACCOUNTS),
        tier_ceiling_check_name="require-tier-ceiling",
        config_source="test-fixture",
    )
    return cli._Context(repo_root=tmp_path, config=config, app_role="overseer")


def _make_submit_args(
    body_file, *, event="approve", tier="LOW", pr=42, repo="test-owner/test-repo"
):
    return argparse.Namespace(
        app="overseer", repo=repo, pr=pr, tier=tier, event=event, body_file=str(body_file)
    )


@pytest.fixture
def submit_preamble_mocks(monkeypatch):
    """A PR authored by someone other than the acting bot, with no existing
    reviews — clears G2 (self-authored) and G3 (already-approved) so a test
    reaches whichever of G0/G0b it targets."""
    monkeypatch.setattr(
        gh,
        "get_pull",
        lambda o, r, n: {
            "head": {"sha": "sha1"},
            "user": {"login": DEFAULT_PR_AUTHOR},
            "requested_reviewers": [],
            "review_comments": 0,
        },
    )
    monkeypatch.setattr(gh, "list_pull_reviews", lambda o, r, n: [])


def test_s1_direct_l2_approve_refuses_on_bot_login_mismatch(
    tmp_path, monkeypatch, submit_preamble_mocks
):
    """The core of Finding 1: HOS_BOT_LOGIN (the acting identity) does not
    match `ctx.config.overseer_handle`, even though `--app overseer` was
    supplied — direct L2 invocation, no bash wrapper involved."""
    monkeypatch.setenv("HOS_BOT_LOGIN", "some-other-bot[bot]")
    body_file = tmp_path / "body.md"
    body_file.write_text("a verdict body\n")
    ctx = _make_submit_ctx(tmp_path)
    outcome = cli._cmd_submit_verdict(_make_submit_args(body_file), ctx)
    assert outcome.exit_code == 3
    assert outcome.payload["refusal_reason"] == "approve_requires_overseer_identity_match"
    assert outcome.payload["refused"] is True
    assert outcome.payload["commit_id"] == "sha1"
    # Distinguishable from G0's own refusal_reason (--app-only mismatch) in
    # the audit envelope.
    assert outcome.payload["refusal_reason"] != "approve_requires_overseer_identity"


def test_s2_direct_l2_approve_succeeds_when_identity_matches(
    tmp_path, monkeypatch, submit_preamble_mocks
):
    monkeypatch.setenv("HOS_BOT_LOGIN", DEFAULT_OVERSEER_HANDLE)
    monkeypatch.setattr(
        gh,
        "submit_pull_review",
        lambda o, r, n, event, body, sha: {
            "id": 9001,
            "state": "APPROVED",
            "body": body,
            "commit_id": sha,
            "html_url": "https://github.com/test-owner/test-repo/pull/42#pullrequestreview-9001",
        },
    )
    body_file = tmp_path / "body.md"
    body_file.write_text("a verdict body\n")
    ctx = _make_submit_ctx(tmp_path)
    outcome = cli._cmd_submit_verdict(_make_submit_args(body_file), ctx)
    assert outcome.exit_code == 0, outcome.error
    assert outcome.payload["posted"] is True
    assert outcome.payload["refused"] is False


def test_s3_direct_l2_comment_unaffected_by_identity_mismatch(
    tmp_path, monkeypatch, submit_preamble_mocks
):
    """G0/G0b are gated on `args.event == "approve"` — a mismatched identity
    must never block a comment verdict."""
    monkeypatch.setenv("HOS_BOT_LOGIN", "some-other-bot[bot]")
    monkeypatch.setattr(
        gh,
        "submit_pull_review",
        lambda o, r, n, event, body, sha: {
            "id": 9002,
            "state": "COMMENTED",
            "body": body,
            "commit_id": sha,
            "html_url": "https://github.com/test-owner/test-repo/pull/42#pullrequestreview-9002",
        },
    )
    body_file = tmp_path / "body.md"
    body_file.write_text("a verdict body\n")
    ctx = _make_submit_ctx(tmp_path)
    outcome = cli._cmd_submit_verdict(_make_submit_args(body_file, event="comment"), ctx)
    assert outcome.exit_code == 0, outcome.error
    assert outcome.payload["posted"] is True


def test_s4_case_insensitive_identity_match(tmp_path, monkeypatch, submit_preamble_mocks):
    """Case must not matter for the comparison — mirrors G2/G3's own
    `.lower()` comparisons elsewhere in this module and
    require_overseer_approval.py's login comparison idiom."""
    monkeypatch.setenv("HOS_BOT_LOGIN", DEFAULT_OVERSEER_HANDLE.upper())
    monkeypatch.setattr(
        gh,
        "submit_pull_review",
        lambda o, r, n, event, body, sha: {
            "id": 9003,
            "state": "APPROVED",
            "body": body,
            "commit_id": sha,
            "html_url": "https://github.com/test-owner/test-repo/pull/42#pullrequestreview-9003",
        },
    )
    body_file = tmp_path / "body.md"
    body_file.write_text("a verdict body\n")
    ctx = _make_submit_ctx(tmp_path)
    outcome = cli._cmd_submit_verdict(_make_submit_args(body_file), ctx)
    assert outcome.exit_code == 0, outcome.error
    assert outcome.payload["posted"] is True


# --------------------------------------------------------------------------- #
# T1-T8 — Finding 2 (#1657 codex adversarial-security second review, CWE-200):
# `cli._scrub_secrets` / `cli._scrub_exc`, the exception-text redaction
# helper. Each token shape named in the finding, plus that a bounded,
# non-secret message survives untouched (the envelope must stay
# diagnosable).
# --------------------------------------------------------------------------- #


def test_t1_gh_token_env_value_redacted(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "sekrit-value-12345")
    assert cli._scrub_secrets("boom: sekrit-value-12345 was rejected") == (
        "boom: [REDACTED] was rejected"
    )


def test_t1b_github_token_env_value_redacted(monkeypatch):
    # Finding 4 (#1657 round-3 cross-vendor second review, LOW): GITHUB_TOKEN
    # is the GitHub Actions default env var name — a token supplied that way
    # must be scrubbed too, not only GH_TOKEN.
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "actions-default-token-67890")  # pragma: allowlist secret
    assert cli._scrub_secrets(
        "boom: actions-default-token-67890 was rejected"
    ) == (  # pragma: allowlist secret
        "boom: [REDACTED] was rejected"
    )


def test_t2_authorization_header_redacted():
    text = "request failed, headers: {'Authorization': 'Bearer abcdEFGH12345678'}"
    scrubbed = cli._scrub_secrets(text)
    assert "abcdEFGH12345678" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t2b_authorization_header_token_scheme_redacted():
    # Finding 1 (#1657 round-3 cross-vendor second review, HIGH, agy and
    # codex independently): the prior regex's optional group only matched
    # the literal word "bearer", so "Authorization: token <secret>" left the
    # secret itself in plaintext and redacted only the word "token".
    text = "request failed: Authorization: token abcdEFGH12345678secret"
    scrubbed = cli._scrub_secrets(text)
    assert "abcdEFGH12345678secret" not in scrubbed  # pragma: allowlist secret
    assert "[REDACTED]" in scrubbed


def test_t2c_authorization_header_basic_scheme_redacted():
    text = "request failed: Authorization: Basic abcdEFGH12345678secret"
    scrubbed = cli._scrub_secrets(text)
    assert "abcdEFGH12345678secret" not in scrubbed  # pragma: allowlist secret
    assert "[REDACTED]" in scrubbed


def test_t2d_authorization_header_bearer_scheme_redacted():
    text = "request failed: Authorization: Bearer abcdEFGH12345678secret"
    scrubbed = cli._scrub_secrets(text)
    assert "abcdEFGH12345678secret" not in scrubbed  # pragma: allowlist secret
    assert "[REDACTED]" in scrubbed


def test_t2e_authorization_header_dict_repr_redacted():
    # A Python dict repr embeds the header as a quoted key/value pair rather
    # than a "Name: value" line — a shape a bare requests/urllib exception
    # commonly produces.
    text = "headers={'Authorization': 'token abcdEFGH12345678secret', 'Accept': '*/*'}"
    scrubbed = cli._scrub_secrets(text)
    assert "abcdEFGH12345678secret" not in scrubbed  # pragma: allowlist secret
    assert "[REDACTED]" in scrubbed
    # The redaction is deliberately whole-line (see _AUTH_HEADER_RE's
    # comment): a same-line "Accept" header sitting after Authorization in
    # this dict repr is accepted collateral, not preserved. Diagnosability
    # across *lines* is what's guaranteed — see test_t2g.
    assert "'Accept': '*/*'" not in scrubbed


def test_t2f_authorization_header_base64_padding_redacted():
    # Finding 2 (#1657 round-3 cross-vendor second review, MEDIUM): a
    # trailing `\b` after a greedy `\S+` forced backtracking off a token's
    # trailing non-word characters (base64 `=` padding), leaving them
    # unredacted.
    text = "Authorization: Bearer abcdEFGH12345678secret=="
    scrubbed = cli._scrub_secrets(text)
    assert "abcdEFGH12345678secret" not in scrubbed  # pragma: allowlist secret
    assert "==" not in scrubbed


def test_t2g_diagnostic_text_either_side_of_header_preserved():
    # The redaction must not swallow the whole message — only the header
    # line itself.
    text = (
        "fetching PR #42 failed with status 401\n"
        "Authorization: Bearer abcdEFGH12345678secret\n"
        'response body: {"message": "Bad credentials"}'
    )
    scrubbed = cli._scrub_secrets(text)
    assert "abcdEFGH12345678secret" not in scrubbed  # pragma: allowlist secret
    assert "fetching PR #42 failed with status 401" in scrubbed
    assert "Bad credentials" in scrubbed


def test_t2h_authorization_header_bytes_prefix_non_bearer_scheme_redacted():
    # Finding (#1657 round-4 second review, codex, CWE-200): a
    # bytes-repr value with a non-Bearer scheme was caught by neither the
    # header-value regex (which stopped before the `b` prefix) nor the
    # standalone-Bearer layer (which only ever matches the literal word
    # "Bearer") — the credential leaked in full. This is the exact reported
    # shape.
    text = '{"Authorization": b"token SEKRIT123"}'
    scrubbed = cli._scrub_secrets(text)
    assert "SEKRIT123" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t2i_authorization_header_bytes_prefix_bearer_scheme_redacted():
    text = "{'Authorization': b'Bearer SEKRIT123'}"
    scrubbed = cli._scrub_secrets(text)
    assert "SEKRIT123" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t2j_authorization_header_raw_bytes_prefix_redacted():
    text = "{'Authorization': rb'Bearer SEKRIT123'}"
    scrubbed = cli._scrub_secrets(text)
    assert "SEKRIT123" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t2k_authorization_header_raw_bytes_prefix_non_bearer_scheme_redacted():
    text = "{'Authorization': rb'token SEKRIT123'}"
    scrubbed = cli._scrub_secrets(text)
    assert "SEKRIT123" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t2l_authorization_header_unquoted_line_redacted():
    text = "Authorization: token SEKRIT123"
    scrubbed = cli._scrub_secrets(text)
    assert "SEKRIT123" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t2m_authorization_header_single_quoted_redacted():
    text = "{'Authorization': 'token SEKRIT123'}"
    scrubbed = cli._scrub_secrets(text)
    assert "SEKRIT123" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t2n_authorization_header_double_quoted_redacted():
    text = '{"Authorization": "token SEKRIT123"}'
    scrubbed = cli._scrub_secrets(text)
    assert "SEKRIT123" not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t2o_bytes_prefix_leak_redacted_across_lines_following_line_survives():
    # Same reported bytes-prefix/non-Bearer shape as test_t2h, but embedded
    # in a multi-line message — proves the fix redacts to end-of-*line*,
    # not end-of-string: the credential on the marker's own line must be
    # gone, and a *following* line's ordinary diagnostic text must survive
    # untouched.
    text = (
        "fetching PR #42 failed with status 401\n"
        '{"Authorization": b"token SEKRIT123"}\n'
        'response body: {"message": "Bad credentials"}'
    )
    scrubbed = cli._scrub_secrets(text)
    assert "SEKRIT123" not in scrubbed
    assert "fetching PR #42 failed with status 401" in scrubbed
    assert "Bad credentials" in scrubbed


def test_t2p_reauthorization_word_not_treated_as_header_marker():
    text = "reauthorization: notasecret"
    assert cli._scrub_secrets(text) == text


def test_t3_bare_bearer_token_redacted():
    text = "curl error: Bearer ghs_abcdefgh12345678 invalid"
    scrubbed = cli._scrub_secrets(text)
    assert "ghs_abcdefgh12345678" not in scrubbed


def test_t3b_bare_bearer_token_base64_padding_redacted():
    text = "curl error: Bearer abcdEFGH12345678secret== invalid"
    scrubbed = cli._scrub_secrets(text)
    assert "abcdEFGH12345678secret" not in scrubbed  # pragma: allowlist secret
    assert "==" not in scrubbed


@pytest.mark.parametrize(
    "prefix",
    ["ghs", "ghp", "gho", "ghu", "ghr"],
)
def test_t4_github_token_prefixes_redacted(prefix):
    token = f"{prefix}_ABCDEFGHijklmnop12345678"
    text = f"gh api failed: token {token} rejected"
    scrubbed = cli._scrub_secrets(text)
    assert token not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t5_github_pat_prefix_redacted():
    token = "github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz"  # pragma: allowlist secret
    text = f"failed to authenticate with {token}"
    scrubbed = cli._scrub_secrets(text)
    assert token not in scrubbed
    assert "[REDACTED]" in scrubbed


def test_t6_non_secret_message_preserved_diagnosable():
    text = "PR #42 not found"
    assert cli._scrub_secrets(text) == text


def test_t7_scrub_exc_wraps_str_exc():
    exc = ValueError("contains ghp_ABCDEFGHijklmnop12345678 inline")  # pragma: allowlist secret
    scrubbed = cli._scrub_exc(exc)
    assert "ghp_ABCDEFGHijklmnop12345678" not in scrubbed  # pragma: allowlist secret
    assert "contains" in scrubbed and "inline" in scrubbed


def test_t8_empty_text_returned_as_is():
    assert cli._scrub_secrets("") == ""
