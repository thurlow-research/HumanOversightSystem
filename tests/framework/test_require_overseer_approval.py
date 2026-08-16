"""Tests for the #621 server-side overseer-approval gate.

Covers env-file parsing (load_env), the pure approval-matching logic
(overseer_has_approved), and main()'s exit-code contract via a stubbed
_gh so no real `gh` binary or network access is required.

Also covers the #1426 above-ceiling bypass: when the overseer posted some
review (any state, i.e. it deliberately withheld APPROVED authority above
its ceiling) and a human approved instead, the gate passes. The bypass never
fires when the overseer posted no review at all (the #621 property).
"""
import importlib.util
import json
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "require_overseer_approval",
    Path(__file__).resolve().parents[2] / "scripts" / "framework" / "require_overseer_approval.py",
)
roa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(roa)


# ── load_env ─────────────────────────────────────────────────────────────────
def test_load_env_parses_quoted_values(tmp_path):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text('BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"  # comment\n')
    result = roa.load_env(env_file)
    assert result["BOT_OVERSEER_USERNAME"] == "hos-overseer-hos[bot]"


def test_load_env_skips_blank_and_comment_lines(tmp_path):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text("\n# a comment\nFOO=bar\n\n# another\nBAZ=qux\n")
    result = roa.load_env(env_file)
    assert result == {"FOO": "bar", "BAZ": "qux"}


def test_load_env_skips_lines_without_equals(tmp_path):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text("not_an_assignment\nFOO=bar\n")
    result = roa.load_env(env_file)
    assert result == {"FOO": "bar"}


def test_load_env_expands_variable_references(tmp_path):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text('WORKER="hos-worker-hos[bot]"\nALL="${WORKER} extra"\n')
    result = roa.load_env(env_file)
    assert result["ALL"] == "hos-worker-hos[bot] extra"


def test_load_env_missing_file_exits_2(tmp_path):
    missing = tmp_path / "does-not-exist.env"
    try:
        roa.load_env(missing)
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert e.code == 2


# ── overseer_has_approved ────────────────────────────────────────────────────
def test_overseer_approved_matches_login_case_insensitively():
    reviews = [{"state": "APPROVED", "user": {"login": "Hos-Overseer-Hos[bot]"}}]
    assert roa.overseer_has_approved(reviews, "hos-overseer-hos[bot]") is True


def test_overseer_not_approved_when_only_other_user_approved():
    reviews = [{"state": "APPROVED", "user": {"login": "ScottThurlow"}}]
    assert roa.overseer_has_approved(reviews, "hos-overseer-hos[bot]") is False


def test_overseer_non_approved_states_ignored():
    reviews = [
        {"state": "COMMENTED", "user": {"login": "hos-overseer-hos[bot]"}},
        {"state": "CHANGES_REQUESTED", "user": {"login": "hos-overseer-hos[bot]"}},
        {"state": "DISMISSED", "user": {"login": "hos-overseer-hos[bot]"}},
    ]
    assert roa.overseer_has_approved(reviews, "hos-overseer-hos[bot]") is False


def test_overseer_empty_reviews_list():
    assert roa.overseer_has_approved([], "hos-overseer-hos[bot]") is False


def test_overseer_missing_user_field_does_not_crash():
    reviews = [{"state": "APPROVED"}]
    assert roa.overseer_has_approved(reviews, "hos-overseer-hos[bot]") is False


# ── get_reviews JSON handling ─────────────────────────────────────────────────
def test_get_reviews_empty_output_returns_empty_list(monkeypatch):
    monkeypatch.setattr(roa, "_gh", lambda *a: "")
    assert roa.get_reviews("owner/repo", "1") == []


def test_get_reviews_single_object_wrapped_in_list(monkeypatch):
    monkeypatch.setattr(roa, "_gh", lambda *a: json.dumps({"state": "APPROVED"}))
    assert roa.get_reviews("owner/repo", "1") == [{"state": "APPROVED"}]


def test_get_reviews_paginated_concatenated_arrays(monkeypatch):
    # gh --paginate may emit "][" (or with whitespace) between page arrays.
    monkeypatch.setattr(roa, "_gh", lambda *a: '[{"state": "APPROVED"}][{"state": "COMMENTED"}]')
    result = roa.get_reviews("owner/repo", "1")
    assert result == [{"state": "APPROVED"}, {"state": "COMMENTED"}]


# ── main() exit-code contract ─────────────────────────────────────────────────
def _run_main(monkeypatch, tmp_path, argv, env_contents, gh_reviews):
    env_file = tmp_path / "machine-accounts.env"
    env_file.write_text(env_contents)
    monkeypatch.setattr(roa, "ENV_FILE", env_file)
    monkeypatch.setattr(roa, "_gh", lambda *a: json.dumps(gh_reviews))
    monkeypatch.setattr(sys, "argv", ["require_overseer_approval.py"] + argv)
    return roa.main()


def test_main_exits_0_when_overseer_approved(monkeypatch, tmp_path):
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n',
        [{"state": "APPROVED", "user": {"login": "hos-overseer-hos[bot]"}}],
    )
    assert rc == 0


def test_main_exits_1_when_overseer_has_not_approved(monkeypatch, tmp_path):
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n',
        [{"state": "APPROVED", "user": {"login": "ScottThurlow"}}],
    )
    assert rc == 1


def test_main_exits_2_when_bot_overseer_username_unset(monkeypatch, tmp_path):
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        "SOME_OTHER_KEY=value\n",
        [],
    )
    assert rc == 2


def test_main_exits_2_when_no_repo_available(monkeypatch, tmp_path):
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1"],
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n',
        [],
    )
    assert rc == 2


def test_main_uses_github_repository_env_when_repo_flag_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1"],
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n',
        [{"state": "APPROVED", "user": {"login": "hos-overseer-hos[bot]"}}],
    )
    assert rc == 0


# ── overseer_posted_any_review ────────────────────────────────────────────────
def test_overseer_posted_any_review_true_for_non_approved_state():
    reviews = [{"state": "COMMENTED", "user": {"login": "hos-overseer-hos[bot]"}}]
    assert roa.overseer_posted_any_review(reviews, "hos-overseer-hos[bot]") is True


def test_overseer_posted_any_review_false_when_absent():
    reviews = [{"state": "APPROVED", "user": {"login": "ScottThurlow"}}]
    assert roa.overseer_posted_any_review(reviews, "hos-overseer-hos[bot]") is False


# ── #1426 above-ceiling bypass ────────────────────────────────────────────────
_BYPASS_ENV = (
    'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n'
    'OVERSEER_CEILING="MEDIUM"\n'
    'BOT_ACCOUNTS="hos-overseer-hos[bot] hos-worker-hos[bot]"\n'
)

_OVERSEER_COMMENTED_HUMAN_APPROVED = [
    {"state": "COMMENTED", "user": {"login": "hos-overseer-hos[bot]"}},
    {"state": "APPROVED", "user": {"login": "ScottThurlow"}},
]

_OVERSEER_CHANGES_REQUESTED_HUMAN_APPROVED = [
    {"state": "CHANGES_REQUESTED", "user": {"login": "hos-overseer-hos[bot]"}},
    {"state": "APPROVED", "user": {"login": "ScottThurlow"}},
]


class _FakeTierCeilingModule:
    """Stand-in for the dynamically-loaded require_tier_ceiling.py sibling."""

    TIER_ORDER = {"SAFE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

    def __init__(self, tier):
        self._tier = tier

    def compute_tier_for_pr(self, repo, pr):
        return self._tier

    def tier_exceeds_ceiling(self, tier, ceiling):
        return self.TIER_ORDER.get(tier, 4) > self.TIER_ORDER.get(ceiling, 4)


class _FakeHumanApprovalModule:
    """Stand-in for the dynamically-loaded require_human_approval.py sibling."""

    def __init__(self, humans):
        self._humans = humans

    def human_approval_present(self, reviews, bot_accounts):
        return self._humans


def _make_sibling_loader(tier, humans):
    """Build a fake `_load_sibling_module` that returns fixed fakes, and
    asserts require_human_approval.py is never loaded when it shouldn't be
    (e.g. tier within ceiling, or empty BOT_ACCOUNTS short-circuits first).
    """
    def _loader(name):
        if name == "require_tier_ceiling.py":
            return _FakeTierCeilingModule(tier)
        if name == "require_human_approval.py":
            return _FakeHumanApprovalModule(humans)
        raise AssertionError(f"unexpected sibling module requested: {name}")
    return _loader


def test_bypass_passes_when_overseer_commented_tier_above_ceiling_human_approved(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(roa, "_load_sibling_module", _make_sibling_loader("HIGH", ["ScottThurlow"]))
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        _BYPASS_ENV,
        _OVERSEER_COMMENTED_HUMAN_APPROVED,
    )
    assert rc == 0


def test_bypass_passes_when_overseer_requested_changes_tier_above_ceiling_human_approved(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(roa, "_load_sibling_module", _make_sibling_loader("HIGH", ["ScottThurlow"]))
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        _BYPASS_ENV,
        _OVERSEER_CHANGES_REQUESTED_HUMAN_APPROVED,
    )
    assert rc == 0


def test_bypass_does_not_apply_when_tier_within_ceiling(monkeypatch, tmp_path):
    """Overseer commented, human approved, but tier does NOT exceed ceiling —
    bypass condition isn't met (overseer simply never approved) → FAIL."""
    monkeypatch.setattr(roa, "_load_sibling_module", _make_sibling_loader("LOW", ["ScottThurlow"]))
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        _BYPASS_ENV,
        _OVERSEER_COMMENTED_HUMAN_APPROVED,
    )
    assert rc == 1


def test_bypass_does_not_apply_without_human_approval(monkeypatch, tmp_path):
    """Overseer commented, tier above ceiling, but no human approval → FAIL."""
    monkeypatch.setattr(roa, "_load_sibling_module", _make_sibling_loader("HIGH", []))
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        _BYPASS_ENV,
        [{"state": "COMMENTED", "user": {"login": "hos-overseer-hos[bot]"}}],
    )
    assert rc == 1


def test_no_overseer_review_at_all_still_fails_621_regression(monkeypatch, tmp_path):
    """#621 regression, re-confirmed post-#1426: a human APPROVED review with
    NO overseer review at all (any state) must still fail — the bypass only
    fires when the overseer reviewed."""
    monkeypatch.setattr(
        roa,
        "_load_sibling_module",
        lambda name: (_ for _ in ()).throw(
            AssertionError(f"sibling module {name} must not be loaded — overseer never reviewed")
        ),
    )
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        _BYPASS_ENV,
        [{"state": "APPROVED", "user": {"login": "ScottThurlow"}}],
    )
    assert rc == 1


def test_bypass_fails_closed_when_bot_accounts_empty(monkeypatch, tmp_path):
    """Overseer commented, tier above ceiling, human approved — but
    BOT_ACCOUNTS is empty/unset → do not treat as license to bypass; fail
    closed rather than fail open."""
    monkeypatch.setattr(roa, "_load_sibling_module", _make_sibling_loader("HIGH", ["ScottThurlow"]))
    env_no_bot_accounts = (
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n'
        'OVERSEER_CEILING="MEDIUM"\n'
    )
    rc = _run_main(
        monkeypatch,
        tmp_path,
        ["--pr", "1", "--repo", "owner/repo"],
        env_no_bot_accounts,
        _OVERSEER_COMMENTED_HUMAN_APPROVED,
    )
    assert rc == 1
