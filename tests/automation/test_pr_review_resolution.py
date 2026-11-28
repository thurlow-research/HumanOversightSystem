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
import dataclasses
import functools
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

import scripts.automation.pr_review_cli as cli
from scripts.automation.lib import github as gh
from scripts.automation.lib import merge_authority as ma
from scripts.automation.lib import overseer_second_review as osr
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


def _make_args(
    tier="CRITICAL",
    reviewer=None,
    pr=42,
    repo="test-owner/test-repo",
    app="overseer",
    disposition="HUMAN_REQUIRED",
):
    return argparse.Namespace(
        app=app, repo=repo, pr=pr, tier=tier, reviewer=reviewer, disposition=disposition
    )


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
    # Without a disposition (non-overseer caller) the PR-author case still halts.
    worker_ctx = dataclasses.replace(ctx, app_role="worker")
    outcome = cli._cmd_request_reviewer(_make_args(app="worker", disposition=None), worker_ctx)
    assert outcome.exit_code == 1
    assert "author" in (outcome.error or "").lower()
    # With a disposition (#2174) the human is already the named actor: skip, exit 0.
    outcome = cli._cmd_request_reviewer(_make_args(), ctx)
    assert outcome.exit_code == 0
    assert outcome.payload["skipped"] is True
    assert outcome.payload["skip_reason"] == "reviewer_is_pr_author"


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
    body_file,
    *,
    event="approve",
    tier="LOW",
    pr=42,
    repo="test-owner/test-repo",
    app="overseer",
    disposition="default",
    expected_action=None,
):
    if disposition == "default":
        disposition = "AUTO_MERGE" if event == "approve" else "PROPOSE_ONLY"
        expected_action = expected_action or (None if event == "approve" else "APPROVE")
    return argparse.Namespace(
        app=app,
        repo=repo,
        pr=pr,
        tier=tier,
        event=event,
        body_file=str(body_file),
        disposition=disposition,
        expected_action=expected_action,
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


# --------------------------------------------------------------------------- #
# G1c / check marker fixtures (#2357 S1b): a real git checkout so the base the
# gate pins is a real merge-base, and records written through the runner's own
# atomic writer so they are private (0600 file, 0700 dir) like the real ones.
# --------------------------------------------------------------------------- #
SLUG = "test-owner/test-repo"
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}
_TIER_FOR_SET = {"none": "LOW", "agy": "MEDIUM", "agy+codex": "HIGH"}
_CHECK_MARKER_PREFIX = "<!-- hos-overseer-check"


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
        check=True,
    )
    return proc.stdout.strip()


class GateKit:
    """A submit context over a real repo plus the record fixtures G1c reads."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.root = tmp_path
        self.ctx = _make_submit_ctx(tmp_path)
        _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "base")
        self.base = _git(tmp_path, "rev-parse", "HEAD")
        _git(tmp_path, "checkout", "-q", "-b", "feat")
        _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "feature")
        self.head = _git(tmp_path, "rev-parse", "HEAD")
        self.posted: list[tuple] = []
        self.body_file = tmp_path / "body.md"
        self.body_file.write_text("a verdict body\n")
        monkeypatch.setenv("HOS_BOT_LOGIN", DEFAULT_OVERSEER_HANDLE)
        self.pull = {
            "head": {"sha": self.head},
            "base": {"sha": self.base},
            "user": {"login": DEFAULT_PR_AUTHOR},
            "requested_reviewers": [],
            "review_comments": 0,
        }
        monkeypatch.setattr(gh, "get_pull", lambda o, r, n: self.pull)
        monkeypatch.setattr(gh, "list_pull_reviews", lambda o, r, n: [])
        monkeypatch.setattr(gh, "submit_pull_review", self._submit)

    def _submit(self, owner, repo, number, event, body, sha):
        self.posted.append((event, body, sha))
        return {
            "id": 9001,
            "state": "APPROVED" if event == "APPROVE" else "COMMENTED",
            "body": body,
            "commit_id": sha,
            "html_url": f"https://github.com/{owner}/{repo}/pull/{number}#pullrequestreview-9001",
        }

    def record(self, vendorset, **over) -> dict:
        required = osr.vendors_list(vendorset)
        verdict = "not-required" if vendorset == "none" else "approve"
        rec = {
            "schema": 1,
            "check": osr.CHECK,
            "repo": SLUG,
            "pr": 42,
            "head_sha": self.head,
            "base_sha": self.base,
            "range": f"{self.base}..{self.head}",
            "tier": _TIER_FOR_SET[vendorset],
            "tier_sources": None,
            "vendors_required": required,
            "vendors_run": [] if vendorset == "none" else list(required),
            "status": "final",
            "verdict": verdict,
            "reason": osr.FINAL_REASON_FOR_VERDICT[verdict],
            "unresolved_findings": 0,
            "findings_file": None,
            "outfile": f"{self.root}/out/steppr42.md",
            "files_reviewed": None if vendorset == "none" else 5,
            "binary_files": None if vendorset == "none" else 0,
            "hold_label_applied": None,
            "vendor_failures": [],
            "created_at": "2026-11-18T01:02:03Z",
        }
        rec.update(over)
        return rec

    def write(self, vendorset, **over) -> dict:
        rec = self.record(vendorset, **over)
        osr._atomic_write_json(osr._record_path(self.root, 42, self.head, vendorset), rec)
        return rec

    def write_hold(self, vendorset, **over) -> dict:
        base = {
            "status": "hold",
            "verdict": "hold",
            "reason": "binary-unreviewed",
            "vendors_run": [],
            "files_reviewed": 2,
            "binary_files": 1,
            "hold_label_applied": False,
        }
        return self.write(vendorset, **{**base, **over})

    def write_findings(self) -> str:
        runs = osr.runs_dir(self.root)
        osr._ensure_private_dir(runs)
        path = runs / "pr42" / "findings.json"
        osr._atomic_write_json(
            path,
            {
                "findings": [
                    {
                        "class": "REVIEW_FINDING",
                        "slug": "sr-agy-aaaaaaaa",
                        "summary": "s",
                        "detail": "d",
                        "path": None,
                    }
                ],
                "reviewed_head": self.head,
            },
        )
        return str(path)

    def submit(self, *, tier="MEDIUM", event="approve", body=None, **kw):
        if body is None and kw.get("expected_action"):
            body = f"a verdict body\n\nExpected action: **{kw['expected_action']}**\n"
        if body is not None:
            self.body_file.write_text(body)
        args = _make_submit_args(self.body_file, event=event, tier=tier, **kw)
        return cli._cmd_submit_verdict(args, self.ctx)

    def lock(self):
        return ma.keyed_flock(
            "osr", f"{SLUG}\0pr42\0{self.head}", subject="t", repo_root=str(self.root), timeout=1
        )

    def expected_marker(self, tier, vendors, verdict):
        return (
            f"{_CHECK_MARKER_PREFIX} v=1 check=second-review pr=42 head={self.head} "
            f"tier={tier} vendors={vendors} verdict={verdict} bounced=false -->"
        )


@pytest.fixture
def kit(tmp_path, monkeypatch):
    return GateKit(tmp_path, monkeypatch)


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
    # D-1 (#2174) now catches the mismatch first: every overseer call carries a
    # disposition (D-0), and a disposition requires the matching identity.
    assert outcome.payload["refusal_reason"] == "disposition_requires_overseer_identity"
    assert outcome.payload["refused"] is True
    assert outcome.payload["commit_id"] == "sha1"
    assert outcome.payload["refusal_reason"] != "approve_requires_overseer_identity"


def test_s2_direct_l2_approve_succeeds_when_identity_matches(kit):
    kit.write("none")
    outcome = kit.submit(tier="LOW")
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
    # A mismatched identity never blocks a verdict that claims no disposition.
    ctx = dataclasses.replace(_make_submit_ctx(tmp_path), app_role="worker")
    args = _make_submit_args(body_file, event="comment", app="worker", disposition=None)
    outcome = cli._cmd_submit_verdict(args, ctx)
    assert outcome.exit_code == 0, outcome.error
    assert outcome.payload["posted"] is True


def test_s4_case_insensitive_identity_match(kit, monkeypatch):
    """Case must not matter for the comparison — mirrors G2/G3's own
    `.lower()` comparisons elsewhere in this module and
    require_overseer_approval.py's login comparison idiom."""
    monkeypatch.setenv("HOS_BOT_LOGIN", DEFAULT_OVERSEER_HANDLE.upper())
    kit.write("none")
    outcome = kit.submit(tier="LOW")
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


# --------------------------------------------------------------------------- #
# #2174 — evaluate_reviewer_trigger with a non-merge disposition (AM-1).
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("disposition", ["HUMAN_REQUIRED", "PROPOSE_ONLY"])
@pytest.mark.parametrize("tier", _TIERS)
def test_disposition_triggers_regardless_of_tier_and_surface(surfaces_root, tier, disposition):
    result = cli.evaluate_reviewer_trigger(
        tier, "HIGH", [NON_PROTECTED_FILE], surfaces_root, disposition
    )
    assert result.triggered is True
    assert result.non_merge_disposition is True


@pytest.mark.parametrize("tier", ["SAFE", "LOW", "MEDIUM", "HIGH"])
def test_no_disposition_scoping_unchanged(surfaces_root, tier):
    result = cli.evaluate_reviewer_trigger(tier, "HIGH", [NON_PROTECTED_FILE], surfaces_root)
    assert result.triggered is False
    assert result.non_merge_disposition is False


def test_auto_merge_value_never_widens_the_trigger(surfaces_root):
    result = cli.evaluate_reviewer_trigger(
        "LOW", "HIGH", [NON_PROTECTED_FILE], surfaces_root, "AUTO_MERGE"
    )
    assert result.triggered is False


def test_write_audit_failure_emits_one_stderr_line(tmp_path, monkeypatch, capsys):
    from scripts.oversight.lib import audit_log

    def _boom(event, root="."):
        raise OSError("disk full")

    monkeypatch.setattr(audit_log, "write_event", _boom)
    record, failure = cli._write_audit({"event": "x"}, _make_ctx(tmp_path))
    assert record is None and "audit write failed" in failure
    err = capsys.readouterr().err
    assert err.count("audit write failed") == 1


# --------------------------------------------------------------------------- #
# T-G1c-01..18 and T-MK-01..05 — #2357 S1b: the overseer's own second-review
# gate and the check marker it appends. Each refusal is read back through the
# real CLI path, so every record field the gate reads is exercised as a reader.
# --------------------------------------------------------------------------- #


def _refused(outcome, reason):
    assert outcome.exit_code == 3, outcome.error
    assert outcome.payload["refused"] is True
    assert outcome.payload["refusal_reason"] == reason
    assert outcome.payload["commit_id"] is not None
    assert "second_review" in outcome.payload


def test_g1c_01_an_approve_at_medium_with_an_agy_approve_record_posts(kit):
    kit.write("agy")
    outcome = kit.submit(tier="MEDIUM")
    assert outcome.exit_code == 0, outcome.error
    assert outcome.payload["posted"] is True
    assert outcome.payload["second_review"]["verdict"] == "approve"
    assert len(kit.posted) == 1 and kit.posted[0][0] == "APPROVE"


def test_g1c_02_no_record_refuses(kit):
    outcome = kit.submit(tier="MEDIUM")
    _refused(outcome, "second_review_record_missing")
    assert kit.posted == []


def test_g1c_03_a_record_on_another_base_is_missing(kit):
    kit.write("agy", base_sha="9" * 40)
    _refused(kit.submit(tier="MEDIUM"), "second_review_record_missing")


def test_g1c_04_an_agy_only_record_at_a_high_argv_is_a_tier_raise_and_the_raise_is_written(kit):
    kit.write("agy")
    outcome = kit.submit(tier="HIGH")
    _refused(outcome, "second_review_tier_raise")
    assert outcome.payload["second_review"]["raise_written"] is True
    assert osr.read_raise(kit.root, slug=SLUG, pr=42, head=kit.head) == ("HIGH", False)
    assert kit.posted == []


def test_g1c_05_a_stored_high_raise_outranks_a_medium_argv(kit):
    kit.write("agy")
    osr.write_raise(kit.root, repo=SLUG, pr=42, head_sha=kit.head, tier="HIGH")
    outcome = kit.submit(tier="MEDIUM")
    _refused(outcome, "second_review_tier_raise")
    diag = outcome.payload["second_review"]
    assert (diag["required_tier"], diag["required_vendors"], diag["raise_tier"]) == (
        "HIGH",
        "agy+codex",
        "HIGH",
    )
    assert diag["raise_written"] is False


def test_g1c_06_an_invalid_raise_file_counts_as_high(kit):
    kit.write("agy")
    path = osr._raise_path(kit.root, 42, kit.head)
    osr._atomic_write_json(path, {"tier": "NOPE"})
    outcome = kit.submit(tier="MEDIUM")
    _refused(outcome, "second_review_tier_raise")
    diag = outcome.payload["second_review"]
    assert diag["raise_invalid"] is True and diag["required_tier"] == "HIGH"


def test_g1c_07_a_hold_record_is_not_approved(kit):
    kit.write_hold("agy")
    _refused(kit.submit(tier="MEDIUM"), "second_review_not_approved")


def test_g1c_08_a_request_changes_record_is_not_approved(kit):
    kit.write(
        "agy",
        verdict="request_changes",
        reason="findings",
        unresolved_findings=1,
        findings_file=kit.write_findings(),
    )
    _refused(kit.submit(tier="MEDIUM"), "second_review_not_approved")


def test_g1c_09_not_required_is_accepted_at_none_and_an_approve_there_is_refused(kit):
    kit.write("none")
    outcome = kit.submit(tier="LOW")
    assert outcome.exit_code == 0, outcome.error
    assert outcome.payload["second_review"]["verdict"] == "not-required"


def test_g1c_09b_an_approve_record_at_none_is_refused(kit):
    kit.write("none", verdict="approve", reason="ok", files_reviewed=5, binary_files=0)
    _refused(kit.submit(tier="LOW"), "second_review_not_approved")


@pytest.mark.parametrize(
    "change",
    [{"unresolved_findings": 1}, {"binary_files": 1}, {"vendors_run": []}],
    ids=["unresolved", "binary", "vendors-run"],
)
def test_g1c_10_12_the_gate_re_checks_what_load_record_checks(kit, monkeypatch, change):
    rec = kit.record("agy", **change)
    monkeypatch.setattr(
        osr, "load_record", lambda *a, vendorset, **k: rec if vendorset == "agy" else None
    )
    _refused(kit.submit(tier="MEDIUM"), "second_review_not_approved")


@pytest.mark.parametrize(
    "change",
    [{"unresolved_findings": 1}, {"binary_files": 1}, {"vendors_run": []}],
    ids=["unresolved", "binary", "vendors-run"],
)
def test_g1c_10r_12r_the_real_loader_drops_those_records_so_g1c_sees_none(kit, change):
    """No monkeypatch: the same records, written to disk, never reach the gate's own check."""
    kit.write("agy", **change)
    assert (
        osr.load_record(
            kit.root, repo=SLUG, pr=42, head_sha=kit.head, base_sha=kit.base, vendorset="agy"
        )
        is None
    )
    outcome = kit.submit(tier="MEDIUM")
    _refused(outcome, "second_review_record_missing")
    assert kit.posted == []


def test_g1c_13_a_safe_argv_is_low_and_needs_the_not_required_record(kit):
    kit.write("none")
    outcome = kit.submit(tier="SAFE")
    assert outcome.exit_code == 0, outcome.error
    diag = outcome.payload["second_review"]
    assert (diag["required_tier"], diag["required_vendors"]) == ("LOW", "none")
    _refused(GateKit.submit(_empty_kit(kit), tier="SAFE"), "second_review_record_missing")


def _empty_kit(kit):
    """The same repo with the record removed."""
    osr._record_path(kit.root, 42, kit.head, "none").unlink()
    return kit


def test_g1c_14_a_held_head_lock_makes_the_record_unverifiable(kit, monkeypatch):
    kit.write("agy")
    monkeypatch.setattr(
        osr, "approval_gate", functools.partial(osr.approval_gate, lock_timeout=0.2)
    )
    with kit.lock():
        outcome = kit.submit(tier="MEDIUM")
    _refused(outcome, "second_review_record_unverifiable")
    assert kit.posted == []


@pytest.mark.parametrize("which", ["head", "base"])
def test_g1c_15_a_non_sha_head_or_base_is_missing(kit, which):
    kit.write("agy")
    kit.pull[which] = {"sha": "not-a-sha"}
    _refused(kit.submit(tier="MEDIUM"), "second_review_record_missing")
    assert kit.posted == []


def test_g1c_15b_a_missing_base_is_missing(kit):
    kit.write("agy")
    del kit.pull["base"]
    _refused(kit.submit(tier="MEDIUM"), "second_review_record_missing")


def test_g1c_16_a_comment_never_runs_g1c_and_still_gets_a_marker(kit):
    outcome = kit.submit(event="comment", disposition="PROPOSE_ONLY", expected_action="APPROVE")
    assert outcome.exit_code == 0, outcome.error
    assert "second_review" not in outcome.payload
    assert outcome.payload["check_marker"] == kit.expected_marker("-", "-", "none")
    assert kit.posted[0][1].rstrip().endswith(outcome.payload["check_marker"])


_DIAG_KEYS = set(osr._DIAG_KEYS)


def test_g1c_17_the_diag_carries_every_key_with_the_records_values(kit):
    rec = kit.write("agy", files_reviewed=7, vendor_failures=[], outfile="/o/steppr42.md")
    outcome = kit.submit(tier="MEDIUM")
    assert outcome.exit_code == 0, outcome.error
    diag = outcome.payload["second_review"]
    assert set(diag) == _DIAG_KEYS
    for key in (
        "status",
        "verdict",
        "reason",
        "tier",
        "vendors_run",
        "unresolved_findings",
        "files_reviewed",
        "binary_files",
        "vendor_failures",
        "outfile",
        "findings_file",
        "created_at",
        "base_sha",
    ):
        assert diag[key] == rec[key], key
    assert diag["record_path"] == str(osr._record_path(kit.root, 42, kit.head, "agy"))
    assert (diag["required_tier"], diag["required_vendors"]) == ("MEDIUM", "agy")
    assert diag["tier_sources"] == {
        "argv": "MEDIUM",
        "raise": None,
        "records": [{"vendors": "agy", "tier": "MEDIUM"}],
    }
    assert (diag["raise_tier"], diag["raise_invalid"], diag["raise_written"]) == (
        None,
        False,
        False,
    )
    assert diag["raise_error"] is None


def test_g1c_17b_diag_values_are_sanitized(kit):
    kit.write("agy", outfile="/o/@alice [x](http://e)\x00.md")
    diag = kit.submit(tier="MEDIUM").payload["second_review"]
    assert "@‍alice" in diag["outfile"] and "](" not in diag["outfile"]
    assert "\x00" not in diag["outfile"]


def test_g1c_18_the_diag_is_present_on_a_refusal_too(kit):
    rec = kit.write_hold("agy", files_reviewed=3, outfile="/o/h.md")
    outcome = kit.submit(tier="MEDIUM")
    _refused(outcome, "second_review_not_approved")
    diag = outcome.payload["second_review"]
    assert set(diag) == _DIAG_KEYS
    assert (diag["status"], diag["verdict"], diag["reason"]) == ("hold", "hold", rec["reason"])
    assert (diag["files_reviewed"], diag["binary_files"], diag["outfile"]) == (3, 1, "/o/h.md")
    assert diag["base_sha"] == kit.base


def test_g1c_a_refusal_posts_nothing_and_is_exit_3_before_the_already_approved_check(
    kit, monkeypatch
):
    already = {
        "state": "APPROVED",
        "user": {"login": DEFAULT_OVERSEER_HANDLE},
        "commit_id": kit.head,
    }
    monkeypatch.setattr(gh, "list_pull_reviews", lambda o, r, n: [already])
    outcome = kit.submit(tier="HIGH")
    _refused(outcome, "second_review_record_missing")
    assert outcome.payload["second_review"]["raise_written"] is True
    assert kit.posted == []


def test_mk_01_an_approve_body_ends_with_the_marker_after_the_interim_signoff(kit):
    kit.write("agy")
    outcome = kit.submit(tier="MEDIUM")
    assert outcome.exit_code == 0, outcome.error
    body = kit.posted[0][1]
    marker = kit.expected_marker("MEDIUM", "agy", "approve")
    assert body.endswith(marker + "\n") and body.count(_CHECK_MARKER_PREFIX) == 1
    assert outcome.payload["check_marker"] == marker


def test_mk_02_a_comment_with_no_record_says_none(kit):
    outcome = kit.submit(event="comment", disposition="PROPOSE_ONLY", expected_action="APPROVE")
    assert outcome.payload["check_marker"] == kit.expected_marker("-", "-", "none")


def test_mk_03_a_tier_null_hold_renders_dashes(kit):
    kit.write_hold(
        "agy+codex", tier=None, reason="pending-stuck", base_sha=None, range=None, binary_files=None
    )
    outcome = kit.submit(event="comment", disposition="PROPOSE_ONLY", expected_action="APPROVE")
    assert outcome.payload["check_marker"] == kit.expected_marker("-", "-", "hold")


def test_mk_03b_a_comment_marker_reports_the_newest_record_for_the_pinned_base(kit):
    comment = {"event": "comment", "disposition": "PROPOSE_ONLY", "expected_action": "APPROVE"}
    kit.write("agy", base_sha="9" * 40)
    outcome = kit.submit(**comment)
    assert outcome.payload["check_marker"] == kit.expected_marker("-", "-", "none")
    kit.write("agy", created_at="2026-11-18T01:00:00Z")
    kit.write("agy+codex", created_at="2026-11-18T02:00:00Z")
    kit.write("none", created_at="2026-11-18T03:00:00Z", base_sha="9" * 40)
    outcome = kit.submit(**comment)
    assert outcome.payload["check_marker"] == kit.expected_marker("HIGH", "agy+codex", "approve")


def test_mk_04_the_interim_signoff_marker_still_parses(kit):
    roa = cli._load_require_overseer_approval()
    outcome = kit.submit(event="comment", disposition="PROPOSE_ONLY", expected_action="APPROVE")
    body = kit.posted[0][1]
    assert outcome.payload["marker_appended"] is True
    assert roa.parse_interim_marker(body) == ("PROPOSE_ONLY", "APPROVE", kit.head)
    assert body.index(roa.MARKER_PREFIX) < body.index(_CHECK_MARKER_PREFIX)


def test_mk_05_a_body_containing_a_check_marker_line_is_refused(kit):
    kit.write("agy")
    forged = kit.expected_marker("MEDIUM", "agy", "approve")
    outcome = kit.submit(tier="MEDIUM", body=f"fine\n  {forged}\n")
    assert outcome.exit_code == 2
    assert kit.posted == []


def test_mk_a_worker_verdict_carries_no_check_marker(kit):
    ctx = dataclasses.replace(kit.ctx, app_role="worker")
    args = _make_submit_args(kit.body_file, event="comment", app="worker", disposition=None)
    outcome = cli._cmd_submit_verdict(args, ctx)
    assert outcome.exit_code == 0, outcome.error
    assert outcome.payload["check_marker"] is None
    assert _CHECK_MARKER_PREFIX not in kit.posted[0][1]


def test_check_marker_rejects_a_bad_pr_or_head():
    with pytest.raises(ValueError):
        osr.check_marker(pr=0, head_sha="1" * 40, record=None)
    with pytest.raises(ValueError):
        osr.check_marker(pr=7, head_sha="short", record=None)


def test_mk_06_check_marker_renders_bounced_and_rejects_non_bool():
    head = "1" * 40
    assert osr.check_marker(pr=7, head_sha=head, record=None, bounced=True).endswith(
        "verdict=none bounced=true -->"
    )
    assert osr.check_marker(pr=7, head_sha=head, record=None).endswith("bounced=false -->")
    for bad in (1, "true", None):
        with pytest.raises(ValueError):
            osr.check_marker(pr=7, head_sha=head, record=None, bounced=bad)


@pytest.mark.parametrize("head", [None, 123, b"1" * 40, "1" * 40 + "\n"])
def test_mk_07_check_marker_non_str_or_newline_head_is_value_error(head):
    with pytest.raises(ValueError):
        osr.check_marker(pr=7, head_sha=head, record=None)


@pytest.mark.parametrize("bounced", [False, True])
@pytest.mark.parametrize(
    "vendorset, over",
    [
        ("none", {}),
        ("agy+codex", {"tier": None}),
        ("agy", {}),
        ("agy+codex", {"verdict": "request_changes"}),
        ("none", {"verdict": "not-required"}),
    ],
)
def test_mk_08_every_check_marker_fullmatches_the_one_grammar(kit, vendorset, over, bounced):
    rec = kit.record(vendorset, **over)
    out = osr.check_marker(pr=42, head_sha=kit.head, record=rec, bounced=bounced)
    assert ma.CHECK_MARKER_RE.fullmatch(out) is not None
    assert out.startswith(osr.CHECK_MARKER_PREFIX)
    fields = osr.parse_check_marker(out)
    assert fields["vendors"] == ("-" if rec["tier"] is None else vendorset)
    assert fields["bounced"] == ("true" if bounced else "false")
    assert osr.CHECK_MARKER_RE is ma.CHECK_MARKER_RE


@pytest.mark.parametrize(
    "over",
    [
        {"verdict": "maybe"},
        {"tier": "SEVERE"},
        {"vendors_required": ["agy", "grok"]},
    ],
)
def test_mk_08b_check_marker_refuses_a_record_value_outside_the_one_grammar(kit, over):
    # The marker is checked against CHECK_MARKER_RE before it is returned, so a record
    # field the grammar does not allow can never produce a marker the parser would reject.
    rec = {**kit.record("agy"), **over}
    with pytest.raises(ValueError, match="^check marker does not match the marker grammar$"):
        osr.check_marker(pr=42, head_sha=kit.head, record=rec)


@pytest.mark.parametrize(
    "pr, valid",
    [
        (0, False),
        (1, True),
        (osr.MAX_PR_NUMBER - 1, True),
        (osr.MAX_PR_NUMBER, True),
        (osr.MAX_PR_NUMBER + 1, False),
    ],
)
def test_mk_08c_check_marker_accepts_exactly_the_pr_numbers_the_grammar_allows(kit, pr, valid):
    if valid:
        out = osr.check_marker(pr=pr, head_sha=kit.head, record=None)
        assert osr.parse_check_marker(out)["pr"] == str(pr)
    else:
        with pytest.raises(ValueError, match="^pr, head_sha or bounced is not valid$"):
            osr.check_marker(pr=pr, head_sha=kit.head, record=None)


@pytest.mark.parametrize(
    "body, refused",
    [
        ("<!-- hos:overseer-interim-signoff v=1 -->\nbody\n", True),
        ("ok\n   <!-- hos:overseer-interim-signoff v=1 -->\n", True),
        ("see <!-- hos:overseer-interim-signoff mid-line\n", False),
        ("no marker here\n", False),
    ],
)
def test_mk_10b_body_has_marker_refuses_a_line_that_opens_the_interim_marker(body, refused):
    roa = cli._load_require_overseer_approval()
    assert cli._body_has_marker(body, roa, osr) is refused


def _marker_line(**over):
    fields = {"pr": 7, "head": "a" * 40, "tier": "HIGH", "vendors": "agy+codex"}
    fields.update({"verdict": "request_changes", "bounced": "true"})
    fields.update(over)
    return (
        f"{osr.CHECK_MARKER_PREFIX} v=1 check=second-review pr={fields['pr']} "
        f"head={fields['head']} tier={fields['tier']} vendors={fields['vendors']} "
        f"verdict={fields['verdict']} bounced={fields['bounced']} -->"
    )


@pytest.mark.parametrize(
    "body, accepted",
    [
        ("text\n" + _marker_line(), True),
        ("text\n" + _marker_line() + "\n", True),
        ("text\r\n" + _marker_line() + "\r\n", True),
        (_marker_line() + "\ntext", False),
        (_marker_line() + " trailing", False),
        (" " + _marker_line(), False),
        (_marker_line().replace("hos-overseer", "ｈｏｓ-overseer"), False),
        (_marker_line().replace("hos-overseer", "HOS-OVERSEER"), False),
        (_marker_line(), True),
        (None, False),
        (b"x", False),
    ],
)
def test_mk_09_parse_check_marker_accepts_only_the_exact_final_line(body, accepted):
    got = osr.parse_check_marker(body)
    assert (got is not None) == accepted
    if accepted:
        assert got["pr"] == "7" and got["head"] == "a" * 40 and got["bounced"] == "true"


def test_mk_09b_with_two_markers_the_last_line_wins():
    body = _marker_line(bounced="false") + "\n" + _marker_line(bounced="true", tier="-")
    got = osr.parse_check_marker(body)
    assert (got["bounced"], got["tier"]) == ("true", "-")


def test_mk_11_marker_record_ignores_a_tiered_record_when_the_base_cannot_be_pinned(
    kit, monkeypatch
):
    kit.write("agy", base_sha=None)
    monkeypatch.setattr(osr, "pinned_base", lambda *a, **k: None)
    outcome = kit.submit(event="comment", disposition="PROPOSE_ONLY", expected_action="APPROVE")
    assert outcome.payload["check_marker"] == kit.expected_marker("-", "-", "none")
    rec = osr.marker_record(
        kit.root, repo=SLUG, pr=42, head_sha=kit.head, base_tip=kit.pull["base"]["sha"]
    )
    assert rec is None


@pytest.mark.parametrize(
    "body, posts",
    [
        ("see hos-overseer-check here\n", False),
        ("see ｈｏｓ-overseer-check here\n", False),
        ("see HOS-OVERSEER-CHECK here\n", False),
        ("see hos overseer check here\n", True),
    ],
)
@pytest.mark.parametrize("app", ["overseer", "worker"])
def test_mk_10_d4_refuses_any_check_marker_mention_after_nfkc(kit, body, posts, app):
    ctx = kit.ctx
    kwargs = {"event": "comment", "disposition": "PROPOSE_ONLY", "expected_action": "APPROVE"}
    if app == "worker":
        ctx = dataclasses.replace(ctx, app_role="worker")
        kwargs = {"event": "comment", "app": "worker", "disposition": None}
    else:
        body += "Expected action: **APPROVE**\n"
    kit.body_file.write_text(body)
    outcome = cli._cmd_submit_verdict(_make_submit_args(kit.body_file, **kwargs), ctx)
    if posts:
        assert outcome.exit_code == 0, outcome.error
        assert len(kit.posted) == 1
    else:
        assert outcome.exit_code == 2
        assert outcome.error.startswith("body_contains_marker")
        assert kit.posted == []


def test_mk_10b_d4_still_refuses_an_interim_signoff_line_but_allows_a_mid_line_mention(kit):
    roa = cli._load_require_overseer_approval()
    kit.body_file.write_text(f"  {roa.MARKER_PREFIX} x\n")
    kwargs = {"event": "comment", "disposition": "PROPOSE_ONLY", "expected_action": "APPROVE"}
    outcome = cli._cmd_submit_verdict(_make_submit_args(kit.body_file, **kwargs), kit.ctx)
    assert outcome.exit_code == 2 and kit.posted == []
    kit.body_file.write_text(
        f"it said {roa.MARKER_PREFIX} earlier\n\nExpected action: **APPROVE**\n"
    )
    outcome = cli._cmd_submit_verdict(_make_submit_args(kit.body_file, **kwargs), kit.ctx)
    assert outcome.exit_code == 0, outcome.error


def test_mk_12_a_check_marker_failure_refuses_with_check_marker_unavailable(kit, monkeypatch):
    def bad(*a, **k):
        raise ValueError("no")

    monkeypatch.setattr(osr, "check_marker", bad)
    outcome = kit.submit(event="comment", disposition="PROPOSE_ONLY", expected_action="APPROVE")
    assert outcome.exit_code == 1
    assert outcome.error.startswith("check_marker_unavailable:")
    assert kit.posted == []
