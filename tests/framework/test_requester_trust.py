"""Tests for scripts/framework/requester_trust.py — the requester-trust
primitive (S1 of #1540, fix path for #1539).

Covers: the loaders (§1.3), the permission-tier resolver and its fetch
wrapper (§1.3.2, H3), the predicates (§1.4), the machine-filing marker
(§1.5), requester_verdict, verify_codeowner_actor, and the conformance
tests that keep the next consumer honest (§6.1 of
docs/v0.7.0/TECHNICAL-DESIGN-1540-S1-S2-intake-trust-gate.md).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts.framework import requester_trust as rt
from scripts.framework.requester_trust import (
    COLLABORATOR_PAGE_BOUND,
    MACHINE_FILING_MARKERS,
    PERMISSION_TIERS,
    RequesterVerdict,
    RosterPolicy,
    TrustedSet,
    codeowners_humans,
    fetch_collaborators,
    is_trusted_requester,
    load_bot_accounts,
    load_trusted_apps,
    load_trusted_requesters,
    load_trusted_set,
    machine_accounts_file_absent,
    machine_filing_marker,
    requester_verdict,
    verify_codeowner_actor,
)

ROOT = Path(__file__).resolve().parents[2]

_EXCLUDED_DIR_PARTS = (".venv", "__pycache__", ".git")


def _iter_source_files(base: Path, suffixes: tuple[str, ...]):
    """Repo-scan helper for the conformance tests below. Skips vendored/
    generated trees (scripts/oversight/.venv/ is ~450MB of interpreter
    files, not source this module's conformance rules apply to)."""
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in _EXCLUDED_DIR_PARTS for part in path.parts):
            continue
        yield path


# ---------------------------------------------------------------------------
# Fixture helper
# ---------------------------------------------------------------------------


class _TmpRepo:
    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_root = self._tmp.name

    def teardown_method(self):
        self._tmp.cleanup()

    def _write(self, relative: str, body: str) -> Path:
        path = Path(self.repo_root) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        return path

    def _write_machine_accounts(self, **overrides) -> None:
        defaults = {
            "BOT_WORKER_USERNAME": "hos-worker-hos[bot]",
            "BOT_OVERSEER_USERNAME": "hos-overseer-hos[bot]",
            "BOT_HUMAN_USERNAME": "scottthurlow-claude[bot]",
            "COPILOT_BOT_LOGIN": "copilot[bot]",
        }
        defaults.update(overrides)
        body = "\n".join(f'{k}="{v}"' for k, v in defaults.items() if v is not None)
        self._write("scripts/framework/machine-accounts.env", body + "\n")

    def _write_roster(self, body: str) -> None:
        self._write("scripts/framework/trusted-requesters.txt", body)


# ---------------------------------------------------------------------------
# codeowners_humans (§1.3)
# ---------------------------------------------------------------------------


class TestCodeownersHumans(_TmpRepo):
    def test_parses_individual_owners(self):
        self._write(
            ".github/CODEOWNERS", "# comment\n/AGENTS.md @ScottThurlow\n/docs/ @ScottThurlow\n"
        )
        assert codeowners_humans(self.repo_root) == {"scottthurlow"}

    def test_skips_team_patterns(self):
        self._write(".github/CODEOWNERS", "/foo/ @org/team @ScottThurlow\n")
        assert codeowners_humans(self.repo_root) == {"scottthurlow"}

    def test_empty_when_file_missing(self):
        assert codeowners_humans(self.repo_root) == set()

    def test_ignores_the_path_field(self):
        self._write(".github/CODEOWNERS", "/scripts/framework/ @ScottThurlow\n")
        assert codeowners_humans(self.repo_root) == {"scottthurlow"}

    def test_lowercases_and_dedupes(self):
        self._write(".github/CODEOWNERS", "/a @ScottThurlow\n/b @scottthurlow\n")
        assert codeowners_humans(self.repo_root) == {"scottthurlow"}

    def test_unreadable_raises(self):
        """TD §1.3.1: file present but unreadable MUST propagate (never
        collapse to the absent-file empty-set result). A bare
        `except Exception: return set()` around the read would make this
        pass with an empty set instead of raising — the assertion is on the
        exception, not merely on non-emptiness, so that regression is
        caught."""
        path = self._write(".github/CODEOWNERS", "/x @ScottThurlow\n")
        path.chmod(0o000)
        try:
            with pytest.raises(OSError):
                codeowners_humans(self.repo_root)
        finally:
            path.chmod(0o644)


# ---------------------------------------------------------------------------
# load_trusted_apps (§1.3)
# ---------------------------------------------------------------------------


class TestLoadTrustedApps(_TmpRepo):
    def test_returns_exactly_the_three_hos_roles(self):
        self._write_machine_accounts()
        assert load_trusted_apps(self.repo_root) == {
            "hos-worker-hos[bot]",
            "hos-overseer-hos[bot]",
            "scottthurlow-claude[bot]",
        }

    def test_excludes_copilot(self):
        self._write_machine_accounts()
        apps = load_trusted_apps(self.repo_root)
        assert "copilot[bot]" not in apps

    def test_does_not_execute_the_file(self):
        sentinel = Path(self.repo_root) / "sentinel"
        self._write(
            "scripts/framework/machine-accounts.env",
            'BOT_WORKER_USERNAME="hos-worker-hos[bot]"\n' "EVIL=$(touch sentinel)\n",
        )
        load_trusted_apps(self.repo_root)
        assert not sentinel.exists()

    def test_missing_file_is_empty(self):
        assert load_trusted_apps(self.repo_root) == set()

    def test_unreadable_raises(self):
        """TD §1.3.1: 'file present, read fails -> propagate -> gate exit 2
        config-error'. An empty-set fallback here is the promote-nothing
        case, but it is still a silent narrowing of an unreadable trust
        input into the SAME value as absence — the two facts the TD
        insists must never collapse into one another. Asserting the raise
        (not just a return value) is what would catch a coder adding
        `except Exception: return set()` around this loader's read."""
        self._write_machine_accounts()
        path = Path(self.repo_root) / "scripts" / "framework" / "machine-accounts.env"
        path.chmod(0o000)
        try:
            with pytest.raises(OSError):
                load_trusted_apps(self.repo_root)
        finally:
            path.chmod(0o644)


# ---------------------------------------------------------------------------
# load_bot_accounts (§1.3)
# ---------------------------------------------------------------------------


class TestLoadBotAccounts(_TmpRepo):
    def test_env_unions_with_file_baseline(self, monkeypatch):
        self._write_machine_accounts()
        monkeypatch.setenv("BOT_ACCOUNTS", "extra-bot[bot]")
        bots = load_bot_accounts(self.repo_root)
        assert "extra-bot[bot]" in bots
        assert "hos-worker-hos[bot]" in bots

    def test_env_cannot_shrink_the_baseline(self, monkeypatch):
        self._write_machine_accounts()
        for env_value in ("", "only-one[bot]"):
            monkeypatch.setenv("BOT_ACCOUNTS", env_value)
            bots = load_bot_accounts(self.repo_root)
            assert {
                "hos-worker-hos[bot]",
                "hos-overseer-hos[bot]",
                "scottthurlow-claude[bot]",
                "copilot[bot]",
            } <= bots

    def test_missing_file_env_still_unions(self, monkeypatch):
        monkeypatch.setenv("BOT_ACCOUNTS", "solo-bot[bot]")
        assert load_bot_accounts(self.repo_root) == {"solo-bot[bot]"}

    def test_unreadable_raises(self, monkeypatch):
        """TD §1.3.1: this is 'the most dangerous [row] to get wrong' —
        `bots` is the EXCLUSION input, so a swallowed read error that
        returned an empty baseline instead of raising would promote every
        bot to 'human' on the very next `is_bot_reviewer` check. Asserting
        the raise pins that a bare `except Exception: return set()`
        cannot land here undetected, even with BOT_ACCOUNTS populated
        (the env union must never mask a baseline-read failure either)."""
        monkeypatch.setenv("BOT_ACCOUNTS", "extra-bot[bot]")
        self._write_machine_accounts()
        path = Path(self.repo_root) / "scripts" / "framework" / "machine-accounts.env"
        path.chmod(0o000)
        try:
            with pytest.raises(OSError):
                load_bot_accounts(self.repo_root)
        finally:
            path.chmod(0o644)


# ---------------------------------------------------------------------------
# The roster (§1.3) — explicit-login form
# ---------------------------------------------------------------------------


class TestRoster(_TmpRepo):
    def test_shipped_file_is_empty_by_default(self):
        """The real shipped scripts/framework/trusted-requesters.txt parses
        to RosterPolicy(frozenset(), frozenset()) — both halves empty."""
        assert load_trusted_requesters(str(ROOT)) == RosterPolicy(frozenset(), frozenset())

    def test_accepts_a_well_formed_entry(self):
        self._write_roster(
            "SomeContributor   # added-by: ScottThurlow added: 2026-09-01 why: vetted\n"
        )
        policy = load_trusted_requesters(self.repo_root)
        assert policy.logins == {"somecontributor"}
        assert policy.tiers == frozenset()

    @pytest.mark.parametrize(
        "line",
        [
            "SomeContributor   # added: 2026-09-01 why: vetted",  # missing added-by
            "SomeContributor   # added-by: ScottThurlow why: vetted",  # missing added
            "SomeContributor   # added-by: ScottThurlow added: 2026-09-01",  # missing why
            "tier:write   # added: 2026-09-01 why: vetted",
            "tier:write   # added-by: ScottThurlow why: vetted",
            "tier:write   # added-by: ScottThurlow added: 2026-09-01",
        ],
    )
    def test_rejects_entry_missing_provenance(self, line):
        self._write_roster(line + "\n")
        policy = load_trusted_requesters(self.repo_root)
        assert policy.logins == frozenset()
        assert policy.tiers == frozenset()

    def test_rejects_bot_login_by_suffix(self):
        self._write_roster("evil-bot[bot]   # added-by: ScottThurlow added: 2026-09-01 why: oops\n")
        policy = load_trusted_requesters(self.repo_root)
        assert policy.logins == frozenset()

    def test_rejects_bot_login_via_bot_accounts(self):
        self._write_machine_accounts()
        self._write_roster(
            "hos-worker-hos[bot]   # added-by: ScottThurlow added: 2026-09-01 why: oops\n"
        )
        policy = load_trusted_requesters(self.repo_root)
        assert policy.logins == frozenset()

    def test_missing_file_is_empty(self):
        assert load_trusted_requesters(self.repo_root) == RosterPolicy(frozenset(), frozenset())

    def test_unreadable_raises(self):
        path = self._write(
            "scripts/framework/trusted-requesters.txt",
            "x   # added-by: a added: 2026-09-01 why: b\n",
        )
        path.chmod(0o000)
        try:
            with pytest.raises(OSError):
                load_trusted_requesters(self.repo_root)
        finally:
            path.chmod(0o644)


# ---------------------------------------------------------------------------
# The roster's tier form (H3)
# ---------------------------------------------------------------------------


class TestRosterTierForm(_TmpRepo):
    def test_tier_entry_parses_into_tiers_not_logins(self):
        self._write_roster("tier:write   # added-by: a added: 2026-09-01 why: b\n")
        policy = load_trusted_requesters(self.repo_root)
        assert policy.logins == frozenset()
        assert policy.tiers == {"write"}

    def test_bare_tier_name_without_the_prefix_is_a_login(self):
        self._write_roster("write   # added-by: a added: 2026-09-01 why: b\n")
        policy = load_trusted_requesters(self.repo_root)
        assert policy.logins == {"write"}
        assert policy.tiers == frozenset()

    def test_tier_token_matching_is_case_insensitive(self):
        self._write_roster("tier:Write   # added-by: a added: 2026-09-01 why: b\n")
        policy = load_trusted_requesters(self.repo_root)
        assert policy.tiers == {"write"}

    def test_unrecognised_tier_name_is_skipped_with_a_diagnostic_listing_the_five(self, capsys):
        for bad in ("tier:owner", "tier:push", "tier:collaborator"):
            self._write_roster(f"{bad}   # added-by: a added: 2026-09-01 why: b\n")
            policy = load_trusted_requesters(self.repo_root)
            assert policy.tiers == frozenset()
            err = capsys.readouterr().err
            for legal in PERMISSION_TIERS:
                assert legal in err

    def test_the_rest_of_the_roster_loads_around_a_malformed_tier_line(self):
        self._write_roster(
            "tier:owner   # added-by: a added: 2026-09-01 why: bad\n"
            "GoodLogin    # added-by: a added: 2026-09-01 why: fine\n"
        )
        policy = load_trusted_requesters(self.repo_root)
        assert policy.logins == {"goodlogin"}
        assert policy.tiers == frozenset()

    def test_permission_tiers_is_exactly_githubs_five_names(self):
        assert PERMISSION_TIERS == ("read", "triage", "write", "maintain", "admin")


# ---------------------------------------------------------------------------
# The permission-tier resolver's fetch wrapper (H3, §1.3.2)
# ---------------------------------------------------------------------------


def _collab(login: str, role_name: str, user_type: str = "User") -> dict:
    return {"login": login, "role_name": role_name, "type": user_type}


def _never_stop() -> bool:
    return False


class TestFetchCollaborators:
    def _run(self, side_effect):
        spent = {"n": 0}

        def record():
            spent["n"] += 1

        with patch(
            "scripts.framework.requester_trust._run_gh_get", side_effect=side_effect
        ) as mock_gh:
            payload, requests_spent = fetch_collaborators("o/r", _never_stop, record)
        return payload, requests_spent, mock_gh, spent["n"]

    def test_one_fetch_of_a_short_page_costs_one_request(self):
        page = [_collab("alice", "write")]
        payload, spent, mock_gh, recorded = self._run([page])
        assert mock_gh.call_count == 1
        assert spent == 1
        assert recorded == 1
        assert payload == page
        endpoint = mock_gh.call_args_list[0][0][0]
        assert "per_page=100&page=1" in endpoint
        assert "--paginate" not in endpoint

    def test_multiple_full_pages_then_a_short_page(self):
        full = [_collab(f"user{i}", "write") for i in range(100)]
        short = [_collab("last", "write")]
        payload, spent, mock_gh, _ = self._run([full, short])
        assert mock_gh.call_count == 2
        assert spent == 2
        assert len(payload) == 101

    def test_page_bound_exhaustion_resolves_over_what_was_fetched(self):
        """4 full pages offered, 3 consumed (COLLABORATOR_PAGE_BOUND), no
        request for page 4 — not an error, one-directional (can only
        under-trust)."""
        full = [_collab(f"user{i}", "write") for i in range(100)]
        payload, spent, mock_gh, _ = self._run([full, full, full, full])
        assert mock_gh.call_count == COLLABORATOR_PAGE_BOUND
        assert spent == COLLABORATOR_PAGE_BOUND
        assert len(payload) == 300

    @pytest.mark.parametrize(
        "side_effect",
        [
            [rt._FetchFailure("non-zero exit")],
            [rt._FetchFailure("bad json")],
            [{"not": "a list"}],
        ],
    )
    def test_resolution_failure_yields_none_and_never_raises(self, side_effect):
        payload, spent, mock_gh, _ = self._run(side_effect)
        assert payload is None

    def test_ceiling_refusal_on_first_page_is_quiet_and_spends_nothing(self, capsys):
        """RP6-2 / condition C2: fetch_collaborators takes the request
        budget and reports how many requests it spent. A ceiling refusal
        emits no WARN — this function never prints anything at all."""
        recorded = []
        with patch("scripts.framework.requester_trust._run_gh_get") as mock_gh:
            payload, spent = fetch_collaborators(
                "o/r", stop_test=lambda: True, record_request=lambda: recorded.append(1)
            )
        assert payload is None
        assert spent == 0
        mock_gh.assert_not_called()
        assert recorded == []
        captured = capsys.readouterr()
        assert captured.err == "" and captured.out == ""

    def test_ceiling_refusal_mid_fetch_discards_the_partial_fetch_and_reports_spend(self):
        """A refusal after page 1 succeeded is treated the same as any
        other resolution failure (F35-class): the whole result is
        discarded, and requests_spent reflects only what was actually
        issued."""
        full = [_collab(f"user{i}", "write") for i in range(100)]
        calls = {"n": 0}

        def stop_test():
            # Refuse before the second page (i.e. after page 1 succeeded).
            return calls["n"] >= 1

        def record_request():
            calls["n"] += 1

        with patch("scripts.framework.requester_trust._run_gh_get", side_effect=[full]) as mock_gh:
            payload, spent = fetch_collaborators("o/r", stop_test, record_request)
        assert mock_gh.call_count == 1
        assert payload is None
        assert spent == 1


# ---------------------------------------------------------------------------
# The permission-tier resolver, via load_trusted_set (H3, §1.3.2)
# ---------------------------------------------------------------------------


class TestTierResolution(_TmpRepo):
    def test_membership_is_matched_on_role_name_not_the_permissions_object(self):
        self._write_roster("tier:write   # added-by: a added: 2026-09-01 why: b\n")
        collaborators = [
            {"login": "alice", "role_name": "write", "permissions": {"push": True, "pull": True}},
            {"login": "bob", "permissions": {"push": True, "pull": True}},  # no role_name
        ]
        ts = load_trusted_set(self.repo_root, collaborators=collaborators)
        assert ts.tier_members == {"alice"}

    def test_tier_matching_is_exact_not_hierarchical(self):
        self._write_roster("tier:write   # added-by: a added: 2026-09-01 why: b\n")
        collaborators = [
            _collab("alice", "write"),
            _collab("carol", "maintain"),
            _collab("dave", "admin"),
        ]
        ts = load_trusted_set(self.repo_root, collaborators=collaborators)
        assert ts.tier_members == {"alice"}

    def test_bot_login_from_the_collaborators_endpoint_is_rejected(self):
        self._write_machine_accounts()
        self._write_roster("tier:write   # added-by: a added: 2026-09-01 why: b\n")
        collaborators = [
            _collab("evil-bot[bot]", "write", user_type="Bot"),
            _collab("hos-worker-hos[bot]", "write", user_type="User"),
            _collab("alice", "write"),
        ]
        ts = load_trusted_set(self.repo_root, collaborators=collaborators)
        assert ts.tier_members == {"alice"}

    def test_tier_membership_is_never_written_to_disk(self):
        self._write_roster("tier:write   # added-by: a added: 2026-09-01 why: b\n")
        before = set(Path(self.repo_root).rglob("*"))
        load_trusted_set(self.repo_root, collaborators=[_collab("alice", "write")])
        after = set(Path(self.repo_root).rglob("*"))
        assert before == after

    def test_load_trusted_set_performs_no_network_io(self):
        with patch("subprocess.run", side_effect=AssertionError("network touched")):
            load_trusted_set(self.repo_root, collaborators=[_collab("alice", "write")])
            load_trusted_set(self.repo_root, collaborators=None)

    def test_collaborators_none_is_the_same_as_a_failed_resolution(self):
        self._write_roster("tier:write   # added-by: a added: 2026-09-01 why: b\n")
        ts_none = load_trusted_set(self.repo_root, collaborators=None)
        ts_bad = load_trusted_set(self.repo_root, collaborators="not-a-list")
        assert ts_none.tier_members == frozenset()
        assert ts_bad.tier_members == frozenset()


# ---------------------------------------------------------------------------
# is_trusted_requester (§1.4)
# ---------------------------------------------------------------------------


def _trusted_set(**overrides: Any) -> TrustedSet:
    defaults: dict[str, Any] = dict(
        codeowners=frozenset(),
        roster=frozenset(),
        tier_members=frozenset(),
        tier_of={},
        tiers=frozenset(),
        apps=frozenset(),
        bots=frozenset(),
    )
    defaults.update(overrides)
    return TrustedSet(**defaults)


class TestIsTrustedRequester:
    def test_codeowner_is_trusted(self):
        ts = _trusted_set(codeowners=frozenset({"scottthurlow"}))
        assert is_trusted_requester("ScottThurlow", "User", ts) == (True, "codeowner")

    def test_roster_member_is_trusted(self):
        ts = _trusted_set(roster=frozenset({"somecontributor"}))
        assert is_trusted_requester("SomeContributor", "User", ts) == (True, "roster")

    def test_trusted_app_returns_trusted_app_reason(self):
        ts = _trusted_set(apps=frozenset({"hos-worker-hos[bot]"}))
        assert is_trusted_requester("hos-worker-hos[bot]", "Bot", ts) == (True, "trusted-app")

    def test_tier_member_is_trusted_with_the_tier_in_the_reason(self):
        ts = _trusted_set(tier_members=frozenset({"alice"}), tier_of={"alice": "write"})
        assert is_trusted_requester("alice", "User", ts) == (True, "roster-tier:write")

    def test_codeowner_wins_over_tier(self):
        ts = _trusted_set(
            codeowners=frozenset({"alice"}),
            tier_members=frozenset({"alice"}),
            tier_of={"alice": "write"},
        )
        assert is_trusted_requester("alice", "User", ts) == (True, "codeowner")

    def test_bot_in_tier_members_is_untrusted(self):
        ts = _trusted_set(
            tier_members=frozenset({"evil-bot[bot]"}), tier_of={"evil-bot[bot]": "write"}
        )
        assert is_trusted_requester("evil-bot[bot]", "Bot", ts) == (False, "bot-in-human-category")

    def test_tiers_field_is_never_consulted_for_membership(self):
        ts = _trusted_set(tiers=frozenset({"write"}), tier_members=frozenset())
        assert is_trusted_requester("alice", "User", ts) == (False, "not-in-trusted-set")

    def test_arbitrary_public_user_is_untrusted(self):
        ts = _trusted_set()
        assert is_trusted_requester("random-person", "User", ts) == (False, "not-in-trusted-set")

    def test_copilot_bot_is_untrusted(self):
        ts = _trusted_set()
        assert is_trusted_requester("copilot[bot]", "Bot", ts) == (False, "not-in-trusted-set")

    def test_empty_login_is_untrusted(self):
        ts = _trusted_set()
        assert is_trusted_requester("", "User", ts) == (False, "no-login")

    def test_bot_listed_in_codeowners_is_untrusted(self):
        ts = _trusted_set(codeowners=frozenset({"hos-worker-hos[bot]"}))
        assert is_trusted_requester("hos-worker-hos[bot]", "Bot", ts) == (
            False,
            "bot-in-human-category",
        )

    def test_bot_listed_in_roster_is_untrusted(self):
        ts = _trusted_set(roster=frozenset({"hos-worker-hos[bot]"}))
        assert is_trusted_requester("hos-worker-hos[bot]", "Bot", ts) == (
            False,
            "bot-in-human-category",
        )

    def test_matching_is_case_insensitive(self):
        ts = _trusted_set(codeowners=frozenset({"scottthurlow"}))
        assert is_trusted_requester("SCOTTTHURLOW", "User", ts) == (True, "codeowner")

    def test_is_pure(self):
        ts = _trusted_set(codeowners=frozenset({"scottthurlow"}))
        with patch("builtins.open", side_effect=AssertionError("fs touched")):
            with patch("subprocess.run", side_effect=AssertionError("net touched")):
                assert is_trusted_requester("ScottThurlow", "User", ts) == (True, "codeowner")


class TestTrustedSetInvariant:
    def test_tier_of_matches_tier_members_via_load_trusted_set(self, tmp_path):
        collaborators = [_collab("alice", "write")]
        (tmp_path / "scripts" / "framework").mkdir(parents=True)
        (tmp_path / "scripts" / "framework" / "trusted-requesters.txt").write_text(
            "tier:write   # added-by: a added: 2026-09-01 why: b\n"
        )
        ts = load_trusted_set(str(tmp_path), collaborators=collaborators)
        assert frozenset(ts.tier_of) == ts.tier_members
        assert all(tier in ts.tiers for tier in ts.tier_of.values())

    def test_mismatched_tier_of_raises(self):
        with pytest.raises(ValueError):
            _trusted_set(tier_members=frozenset({"alice"}), tier_of={})


# ---------------------------------------------------------------------------
# Conformance
# ---------------------------------------------------------------------------


class TestConformance:
    def test_no_production_use_of_not_is_bot_reviewer(self):
        """VF-5: inverting exclusion-then-positive-membership (reading
        `not is_bot_reviewer(...)` alone as authorization) admits every
        anonymous member of the public. Scoped to the AD-1/AD-4
        authorization-decision surface this design owns — requester_trust.py,
        probe.py, and (once it exists) select_work_candidates.py — not the
        whole repo: require_human_approval.py's existing `not
        is_bot_reviewer(...)` (its own, unrelated, already-shipped gate:
        filtering PR *review* authors down to humans, not deciding whether a
        record's AUTHOR may file work) is a different domain and is not what
        VF-5 is about."""
        surface = [
            ROOT / "scripts" / "framework" / "requester_trust.py",
            ROOT / "scripts" / "automation" / "lib" / "probe.py",
        ]
        for path in surface:
            assert "not is_bot_reviewer" not in path.read_text(encoding="utf-8"), path

    def test_is_trusted_requester_has_one_production_caller(self):
        hits = [
            path
            for base in ("scripts", "bin")
            for path in _iter_source_files(ROOT / base, (".py",))
            if "is_trusted_requester(" in path.read_text(encoding="utf-8")
        ]
        assert hits == [ROOT / "scripts" / "framework" / "requester_trust.py"]

    def test_no_second_codeowners_parser_in_framework(self):
        hits = [
            path
            for path in _iter_source_files(ROOT / "scripts" / "framework", (".py",))
            if "CODEOWNERS" in path.read_text(encoding="utf-8")
        ]
        assert hits == [ROOT / "scripts" / "framework" / "requester_trust.py"]
        probe_text = (ROOT / "scripts" / "automation" / "lib" / "probe.py").read_text()
        assert "CODEOWNERS" not in probe_text

    def test_requester_trust_imports_nothing_from_automation_or_oversight(self):
        text = (ROOT / "scripts" / "framework" / "requester_trust.py").read_text()
        assert "scripts.automation" not in text
        assert "scripts.oversight" not in text


# ---------------------------------------------------------------------------
# Marker (§1.5)
# ---------------------------------------------------------------------------


class TestMachineFilingMarker:
    @pytest.mark.parametrize(
        "title",
        [
            "[BLOCKED] agent unavailable — worker halted (missing: foo)",
            "[BLOCKED] local main diverged on my-project (worker) — needs manual recovery",
            "[BLOCKED] inner-loop tests failing on my-project — diagnose and fix",
            "[SUSPENDED] worker timeout breaker tripped on my-project — worker halted",
            "[SUSPENDED] worker usage-limit breaker tripped on my-project",
            "[AI: self-review] some-class: some description here",
            "[AI: security-reviewer] design-concern: 2 HIGH/CRITICAL self-review findings (2026-01-01)",
        ],
    )
    def test_each_marker_matches_a_real_title_from_its_site(self, title):
        assert machine_filing_marker(title) is not None

    def test_marker_table_literals_exist_in_emitting_files(self):
        for marker in MACHINE_FILING_MARKERS:
            site_path = marker.emitting_site.split("::")[0]
            text = (ROOT / site_path).read_text(encoding="utf-8")
            assert marker.title_prefix in text, marker
            if marker.title_contains is not None:
                assert marker.title_contains in text, marker

    def test_issue_creation_site_count_is_pinned(self):
        hos_cron = (ROOT / "bin" / "hos-cron").read_text()
        assert hos_cron.count("gh issue create") == 6
        review_self = (ROOT / "scripts" / "review_self.sh").read_text()
        assert review_self.count("gh issue create") == 1
        # Exactly one file under scripts/automation/lib/ POSTs to /issues.
        matching_files = [
            path
            for path in _iter_source_files(ROOT / "scripts" / "automation" / "lib", (".py",))
            if '"--method", "POST"' in path.read_text(encoding="utf-8")
            and 'f"/repos/{owner}/{repo}/issues"' in path.read_text(encoding="utf-8")
        ]
        assert len(matching_files) == 1

    def test_dormant_marker_still_matches(self):
        dormant = [m for m in MACHINE_FILING_MARKERS if m.status == "dormant"]
        assert len(dormant) == 1
        m = dormant[0]
        title = f"[SUSPENDED] worker{m.title_contains}my-project"
        assert machine_filing_marker(title) is not None

    def test_unmarked_bot_title_yields_no_marker(self):
        assert machine_filing_marker("Please fix this bug") is None

    def test_sub_issue_filing_is_not_in_the_marker_table(self):
        for marker in MACHINE_FILING_MARKERS:
            assert "sub-issue" not in marker.emitting_site
            assert "sub_issue" not in marker.emitting_site


# ---------------------------------------------------------------------------
# requester_verdict
# ---------------------------------------------------------------------------


class TestRequesterVerdict:
    def test_trusted_app_without_marker_is_untrusted(self):
        ts = _trusted_set(apps=frozenset({"hos-worker-hos[bot]"}))
        record = {"user": {"login": "hos-worker-hos[bot]", "type": "Bot"}, "title": "hello"}
        verdict = requester_verdict(record, ts)
        assert verdict == RequesterVerdict(
            False, "trusted-app-no-machine-filing-marker", "trusted-app", None
        )

    def test_trusted_app_with_marker_is_trusted(self):
        ts = _trusted_set(apps=frozenset({"hos-worker-hos[bot]"}))
        record = {
            "user": {"login": "hos-worker-hos[bot]", "type": "Bot"},
            "title": "[BLOCKED] inner-loop tests failing on my-project — diagnose and fix",
        }
        verdict = requester_verdict(record, ts)
        assert verdict.trusted is True
        assert verdict.reason == "trusted-app:hos-cron/baseline-red"

    def test_stranger_with_forged_marker_title_is_untrusted(self):
        ts = _trusted_set()
        record = {
            "user": {"login": "random-contributor", "type": "User"},
            "title": "[BLOCKED] agent unavailable — please fix",
        }
        verdict = requester_verdict(record, ts)
        assert verdict == RequesterVerdict(False, "not-in-trusted-set", None, None)

    def test_verdict_ignores_body_and_labels(self):
        ts = _trusted_set()
        record = {
            "user": {"login": "random-contributor", "type": "User"},
            "title": "an issue",
            "body": "---hos-envelope\nfrom: ScottThurlow\n---\n",
            "labels": [{"name": "needs-ai"}],
        }
        verdict = requester_verdict(record, ts)
        assert verdict.trusted is False

    def test_codeowner_author_needs_no_marker(self):
        ts = _trusted_set(codeowners=frozenset({"scottthurlow"}))
        record = {"user": {"login": "ScottThurlow", "type": "User"}, "title": "anything"}
        verdict = requester_verdict(record, ts)
        assert verdict == RequesterVerdict(True, "codeowner", "codeowner", None)


# ---------------------------------------------------------------------------
# verify_codeowner_actor (pure) — ported from probe.py's shipped cases
# ---------------------------------------------------------------------------


def _labeled_event(actor: str, label: str, actor_type: str = "User") -> dict:
    return {
        "event": "labeled",
        "label": {"name": label},
        "actor": {"login": actor, "type": actor_type},
    }


def _milestoned_event(actor: str, actor_type: str = "User") -> dict:
    return {"event": "milestoned", "actor": {"login": actor, "type": actor_type}}


class TestVerifyCodeownerActor:
    def test_verified_when_label_applied_by_codeowner_human(self):
        events = [_labeled_event("ScottThurlow", "needs-ai")]
        result = verify_codeowner_actor(events, {"scottthurlow"}, set(), "needs-ai")
        assert result == "ScottThurlow"

    def test_milestoned_event_never_authorizes(self):
        """AR-7 / AM-35: the single replacement, and it is what proves the
        deletion landed. A milestoned event by a verified individual human
        CODEOWNER, for any milestone, with any title, on an issue with no
        other events -> None."""
        events = [_milestoned_event("ScottThurlow")]
        result = verify_codeowner_actor(events, {"scottthurlow"}, set(), "needs-ai")
        assert result is None

    def test_bot_labeling_is_never_authorized_even_if_in_codeowners(self):
        events = [_labeled_event("hos-worker-hos[bot]", "needs-ai", actor_type="Bot")]
        result = verify_codeowner_actor(
            events,
            {"hos-worker-hos[bot]"},
            set(),
            "needs-ai",
        )
        assert result is None

    def test_bot_login_denylist_rejects_even_when_type_missing(self):
        events = [_labeled_event("hos-worker-hos[bot]", "needs-ai", actor_type="")]
        result = verify_codeowner_actor(
            events,
            {"scottthurlow"},
            {"hos-worker-hos[bot]"},
            "needs-ai",
        )
        assert result is None

    def test_non_codeowner_human_not_authorized(self):
        events = [_labeled_event("random-contributor", "needs-ai")]
        result = verify_codeowner_actor(events, {"scottthurlow"}, set(), "needs-ai")
        assert result is None

    def test_no_relevant_event_not_authorized(self):
        events = [{"event": "assigned", "actor": {"login": "ScottThurlow", "type": "User"}}]
        result = verify_codeowner_actor(events, {"scottthurlow"}, set(), "needs-ai")
        assert result is None

    def test_non_list_events_returns_none(self):
        assert verify_codeowner_actor(None, {"scottthurlow"}, set(), "needs-ai") is None
        assert verify_codeowner_actor("not-a-list", {"scottthurlow"}, set(), "needs-ai") is None

    def test_empty_codeowners_set_fails_closed(self):
        events = [_labeled_event("ScottThurlow", "needs-ai")]
        result = verify_codeowner_actor(events, set(), set(), "needs-ai")
        assert result is None

    def test_verify_codeowner_actor_takes_exactly_four_arguments(self):
        import inspect

        sig = inspect.signature(verify_codeowner_actor)
        assert list(sig.parameters) == [
            "events",
            "codeowners_humans",
            "bot_accounts",
            "label_name",
        ]

    def test_bot_actor_after_codeowner_does_not_erase_authorization(self):
        """A bot actor is `continue`, not `return None`: a bot relabelling
        after a CODEOWNER does not erase the CODEOWNER's act. This is also
        the demonstration of residual R-3: a labeled event authorizes
        forever, even after a bot has removed and re-applied the label."""
        events = [
            _labeled_event("ScottThurlow", "needs-ai"),
            _labeled_event("hos-worker-hos[bot]", "needs-ai", actor_type="Bot"),
        ]
        result = verify_codeowner_actor(events, {"scottthurlow"}, set(), "needs-ai")
        assert result == "ScottThurlow"

    def test_only_the_queried_label_authorizes(self):
        events = [_labeled_event("ScottThurlow", "some-other-label")]
        result = verify_codeowner_actor(events, {"scottthurlow"}, set(), "needs-ai")
        assert result is None


# ---------------------------------------------------------------------------
# machine_accounts_file_absent (RP6-3 / condition C3 — S1 support)
# ---------------------------------------------------------------------------


class TestMachineAccountsFileAbsent(_TmpRepo):
    def test_true_when_absent(self):
        assert machine_accounts_file_absent(self.repo_root) is True

    def test_false_when_present(self):
        self._write_machine_accounts()
        assert machine_accounts_file_absent(self.repo_root) is False
