"""
Unit tests for probe.py — work-discovery probe for consumer repos and HOS self-development.

Covers:
  - STRATEGY_HOS_COORDINATION: hos-coordination label query + actor verification (R4.1.4)
  - STRATEGY_MILESTONE: milestone + needs-ai query, CODEOWNERS actor verification (#1539)
  - Shared gates: blast-radius cap, API quota, cadence/backoff
  - _verify_label_actor: allowlist matching, not-found, GitHubError
  - _codeowners_humans / _verify_codeowner_actor: CODEOWNERS-scoped verification (#1539)
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.automation.lib.github import GitHubError
from scripts.automation.lib.probe import (
    BLAST_CAPS,
    DEFAULT_API_BUDGET_PER_HOUR,
    STRATEGY_MILESTONE,
    CadenceState,
    _codeowners_humans,
    _compute_next_due,
    _fetch_events_paginated,
    _is_due,
    _verify_codeowner_actor,
    _verify_label_actor,
    probe_repo,
)
from scripts.framework import requester_trust

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_issue(number: int, labels: list[str] | None = None) -> dict:
    return {
        "number": number,
        "labels": [{"name": lbl} for lbl in (labels or [])],
    }


def _iso_future(minutes: int = 60) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_past(minutes: int = 60) -> str:
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# _is_due
# ---------------------------------------------------------------------------


class TestIsDue:
    def test_pinned_always_due(self):
        state = CadenceState(pinned=True, next_due=_iso_future())
        assert _is_due(state) is True

    def test_no_next_due_is_due(self):
        assert _is_due(CadenceState()) is True

    def test_future_next_due_not_due(self):
        state = CadenceState(next_due=_iso_future(60))
        assert _is_due(state) is False

    def test_past_next_due_is_due(self):
        state = CadenceState(next_due=_iso_past(1))
        assert _is_due(state) is True

    def test_invalid_next_due_treated_as_due(self):
        state = CadenceState(next_due="not-a-date")
        assert _is_due(state) is True


# ---------------------------------------------------------------------------
# _compute_next_due
# ---------------------------------------------------------------------------


class TestComputeNextDue:
    def test_level_zero_uses_floor(self):
        result = _compute_next_due(0, floor_minutes=15, ceiling_hours=24)
        dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        delta = dt - datetime.now(timezone.utc)
        assert 14 * 60 < delta.total_seconds() < 16 * 60

    def test_backoff_doubles(self):
        r0 = _compute_next_due(0, 15, 24)
        r1 = _compute_next_due(1, 15, 24)
        d0 = datetime.fromisoformat(r0.replace("Z", "+00:00")) - datetime.now(timezone.utc)
        d1 = datetime.fromisoformat(r1.replace("Z", "+00:00")) - datetime.now(timezone.utc)
        assert d1.total_seconds() > d0.total_seconds() * 1.8

    def test_ceiling_caps_interval(self):
        result = _compute_next_due(20, floor_minutes=15, ceiling_hours=1)
        dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        delta = dt - datetime.now(timezone.utc)
        assert delta.total_seconds() <= 61 * 60  # at most ceiling + 1 min slack


# ---------------------------------------------------------------------------
# _verify_label_actor
# ---------------------------------------------------------------------------


class TestVerifyLabelActor:
    def _labeled_event(self, actor: str, label: str) -> dict:
        return {"event": "labeled", "label": {"name": label}, "actor": {"login": actor}}

    def test_returns_actor_when_in_allowlist(self):
        events = [self._labeled_event("alice", "hos-coordination")]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_label_actor("o", "r", 1, "hos-coordination", ["alice"])
        assert result == "alice"

    def test_case_insensitive_allowlist(self):
        events = [self._labeled_event("Alice", "hos-coordination")]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_label_actor("o", "r", 1, "hos-coordination", ["alice"])
        assert result == "Alice"

    def test_returns_none_when_actor_not_in_allowlist(self):
        events = [self._labeled_event("eve", "hos-coordination")]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_label_actor("o", "r", 1, "hos-coordination", ["alice"])
        assert result is None

    def test_returns_none_when_label_event_not_found(self):
        events = [{"event": "assigned", "actor": {"login": "alice"}}]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_label_actor("o", "r", 1, "hos-coordination", ["alice"])
        assert result is None

    def test_returns_none_on_github_error(self):
        with patch("scripts.automation.lib.probe._run_gh", side_effect=GitHubError("fail")):
            result = _verify_label_actor("o", "r", 1, "hos-coordination", ["alice"])
        assert result is None

    def test_returns_none_when_non_list_response(self):
        with patch("scripts.automation.lib.probe._run_gh", return_value=None):
            result = _verify_label_actor("o", "r", 1, "hos-coordination", ["alice"])
        assert result is None


# ---------------------------------------------------------------------------
# probe_repo — shared gate fixtures
# ---------------------------------------------------------------------------


class _ProbeBase:
    """Common setup: temp repo_root with no soft state (clean cadence, no budget used)."""

    def setup_method(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_root = self._tmp.name

    def teardown_method(self):
        self._tmp.cleanup()

    def _patch_blast(self, under_cap: bool = True):
        """Return a patch context for ledger.sum_window_blast_radius."""
        if under_cap:
            return patch(
                "scripts.automation.lib.probe.sum_window_blast_radius",
                return_value={"prs": 0, "issues": 0, "files": 0},
            )
        return patch(
            "scripts.automation.lib.probe.sum_window_blast_radius",
            return_value={
                "prs": BLAST_CAPS["prs"],
                "issues": BLAST_CAPS["issues"],
                "files": BLAST_CAPS["files"],
            },
        )


# ---------------------------------------------------------------------------
# probe_repo — STRATEGY_HOS_COORDINATION
# ---------------------------------------------------------------------------


class TestProbeRepoHosCoordination(_ProbeBase):
    def test_returns_candidates_with_actor(self):
        issues = [_make_issue(42, ["hos-coordination", "enhancement"])]
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=issues):
                with patch(
                    "scripts.automation.lib.probe._verify_label_actor",
                    return_value="alice",
                ):
                    results = probe_repo(
                        "owner",
                        "repo",
                        "rid",
                        requester_allowlist=["alice"],
                        repo_root=self.repo_root,
                    )
        assert len(results) == 1
        c = results[0]
        assert c.issue_number == 42
        assert c.actor == "alice"
        assert "hos-coordination" in c.labels

    def test_skips_issue_when_actor_not_allowed(self):
        issues = [_make_issue(7, ["hos-coordination"])]
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=issues):
                with patch(
                    "scripts.automation.lib.probe._verify_label_actor",
                    return_value=None,
                ):
                    results = probe_repo(
                        "owner",
                        "repo",
                        "rid",
                        requester_allowlist=["alice"],
                        repo_root=self.repo_root,
                    )
        assert results == []

    def test_queries_hos_coordination_label(self):
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=[]) as mock_gh:
                probe_repo(
                    "owner",
                    "repo",
                    "rid",
                    requester_allowlist=[],
                    repo_root=self.repo_root,
                )
        called_path = mock_gh.call_args[0][0][0]
        assert "labels=hos-coordination" in called_path
        assert "milestone=" not in called_path

    def test_does_not_require_milestone_param(self):
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=[]):
                # Should not raise
                probe_repo("owner", "repo", "rid", repo_root=self.repo_root)

    def test_returns_empty_on_github_error(self):
        with self._patch_blast():
            with patch(
                "scripts.automation.lib.probe._run_gh",
                side_effect=GitHubError("network"),
            ):
                results = probe_repo(
                    "owner",
                    "repo",
                    "rid",
                    requester_allowlist=[],
                    repo_root=self.repo_root,
                )
        assert results == []

    def test_blast_radius_cap_returns_empty(self):
        with self._patch_blast(under_cap=False):
            results = probe_repo(
                "owner",
                "repo",
                "rid",
                requester_allowlist=[],
                customer="cust",
                repo_root=self.repo_root,
            )
        assert results == []

    def test_since_param_appended_after_first_poll(self):
        """When cadence has a last_poll, the since= filter is appended to the query."""
        # Write a cadence state that is already due and has a prior last_poll
        soft_state = Path(self.repo_root) / ".ai-local" / "hos-automation"
        soft_state.mkdir(parents=True, exist_ok=True)
        cadence = {
            "rid": {
                "backoff_level": 0,
                "last_poll": "2026-01-01T00:00:00Z",
                "next_due": _iso_past(1),
                "pinned": False,
                "pin_reason": None,
                "pin_since": None,
            }
        }
        (soft_state / "cadence-state.json").write_text(json.dumps(cadence))

        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=[]) as mock_gh:
                probe_repo(
                    "owner",
                    "repo",
                    "rid",
                    requester_allowlist=[],
                    repo_root=self.repo_root,
                )
        called_path = mock_gh.call_args[0][0][0]
        assert "since=2026-01-01T00:00:00Z" in called_path


# ---------------------------------------------------------------------------
# probe_repo — STRATEGY_MILESTONE
# ---------------------------------------------------------------------------


class TestProbeRepoMilestone(_ProbeBase):
    def test_raises_without_milestone(self):
        with pytest.raises(ValueError, match="milestone is required"):
            probe_repo(
                "owner",
                "repo",
                "rid",
                probe_strategy=STRATEGY_MILESTONE,
                repo_root=self.repo_root,
            )

    def test_queries_milestone_and_needs_ai(self):
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=[]) as mock_gh:
                probe_repo(
                    "owner",
                    "repo",
                    "rid",
                    probe_strategy=STRATEGY_MILESTONE,
                    milestone=8,
                    repo_root=self.repo_root,
                )
        called_path = mock_gh.call_args[0][0][0]
        assert "milestone=8" in called_path
        assert "labels=needs-ai" in called_path
        assert "hos-coordination" not in called_path

    def test_skips_issue_with_no_verified_codeowner_actor(self):
        """#1539: an issue whose needs-ai/milestone assignment was not applied
        by a verified human CODEOWNER must not be returned as a candidate —
        this closes the self-triage / unauthorized-labeler gap."""
        issues = [_make_issue(100, ["needs-ai", "enhancement"])]
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=issues):
                with patch(
                    "scripts.automation.lib.probe._verify_codeowner_actor",
                    return_value=None,
                ):
                    results = probe_repo(
                        "owner",
                        "repo",
                        "rid",
                        probe_strategy=STRATEGY_MILESTONE,
                        milestone=8,
                        repo_root=self.repo_root,
                    )
        assert results == []

    def test_returns_candidate_with_verified_codeowner_actor(self):
        issues = [_make_issue(100, ["needs-ai", "enhancement"])]
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=issues):
                with patch(
                    "scripts.automation.lib.probe._verify_codeowner_actor",
                    return_value="ScottThurlow",
                ):
                    results = probe_repo(
                        "owner",
                        "repo",
                        "rid",
                        probe_strategy=STRATEGY_MILESTONE,
                        milestone=8,
                        repo_root=self.repo_root,
                    )
        assert len(results) == 1
        c = results[0]
        assert c.issue_number == 100
        assert c.actor == "ScottThurlow"
        assert "needs-ai" in c.labels

    def test_calls_verify_codeowner_actor_not_verify_label_actor(self):
        issues = [_make_issue(5, ["needs-ai"])]
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=issues):
                with patch("scripts.automation.lib.probe._verify_label_actor") as mock_verify_label:
                    with patch(
                        "scripts.automation.lib.probe._verify_codeowner_actor",
                        return_value="ScottThurlow",
                    ) as mock_verify_codeowner:
                        probe_repo(
                            "owner",
                            "repo",
                            "rid",
                            probe_strategy=STRATEGY_MILESTONE,
                            milestone=8,
                            repo_root=self.repo_root,
                        )
        mock_verify_label.assert_not_called()
        mock_verify_codeowner.assert_called_once()

    def test_url_format_correct(self):
        issues = [_make_issue(42, ["needs-ai"])]
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=issues):
                with patch(
                    "scripts.automation.lib.probe._verify_codeowner_actor",
                    return_value="ScottThurlow",
                ):
                    results = probe_repo(
                        "owner",
                        "repo",
                        "rid",
                        probe_strategy=STRATEGY_MILESTONE,
                        milestone=3,
                        repo_root=self.repo_root,
                    )
        assert results[0].issue_url == "https://github.com/owner/repo/issues/42"

    def test_returns_empty_on_github_error(self):
        with self._patch_blast():
            with patch(
                "scripts.automation.lib.probe._run_gh",
                side_effect=GitHubError("timeout"),
            ):
                results = probe_repo(
                    "owner",
                    "repo",
                    "rid",
                    probe_strategy=STRATEGY_MILESTONE,
                    milestone=8,
                    repo_root=self.repo_root,
                )
        assert results == []

    def test_requester_allowlist_not_required(self):
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=[]):
                # Should not raise even without allowlist
                probe_repo(
                    "owner",
                    "repo",
                    "rid",
                    probe_strategy=STRATEGY_MILESTONE,
                    milestone=8,
                    repo_root=self.repo_root,
                )

    def test_multiple_issues_all_returned(self):
        issues = [_make_issue(10, ["needs-ai"]), _make_issue(20, ["needs-ai", "bug"])]
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=issues):
                with patch(
                    "scripts.automation.lib.probe._verify_codeowner_actor",
                    return_value="ScottThurlow",
                ):
                    results = probe_repo(
                        "owner",
                        "repo",
                        "rid",
                        probe_strategy=STRATEGY_MILESTONE,
                        milestone=8,
                        repo_root=self.repo_root,
                    )
        assert [c.issue_number for c in results] == [10, 20]


# ---------------------------------------------------------------------------
# _codeowners_humans / _verify_codeowner_actor (#1539)
# ---------------------------------------------------------------------------


class TestCodeownersActorVerification(_ProbeBase):
    def _write_codeowners(self, body: str) -> None:
        gh_dir = Path(self.repo_root) / ".github"
        gh_dir.mkdir(parents=True, exist_ok=True)
        (gh_dir / "CODEOWNERS").write_text(body)

    def test_codeowners_humans_parses_individual_owners(self):
        self._write_codeowners("# comment\n/AGENTS.md @ScottThurlow\n/docs/ @ScottThurlow\n")
        assert _codeowners_humans(self.repo_root) == {"scottthurlow"}

    def test_codeowners_humans_skips_team_patterns(self):
        self._write_codeowners("/foo/ @org/team @ScottThurlow\n")
        assert _codeowners_humans(self.repo_root) == {"scottthurlow"}

    def test_codeowners_humans_empty_when_file_missing(self):
        assert _codeowners_humans(self.repo_root) == set()

    def _labeled_event(self, actor: str, label: str, actor_type: str = "User") -> dict:
        return {
            "event": "labeled",
            "label": {"name": label},
            "actor": {"login": actor, "type": actor_type},
        }

    def _milestoned_event(self, actor: str, actor_type: str = "User") -> dict:
        return {"event": "milestoned", "actor": {"login": actor, "type": actor_type}}

    def test_verified_when_label_applied_by_codeowner_human(self):
        events = [self._labeled_event("ScottThurlow", "needs-ai")]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                {"scottthurlow"},
                set(),
            )
        assert result == "ScottThurlow"

    def test_milestoned_event_never_authorizes(self):
        """AR-7 / AM-35: the `milestoned` arm is DELETED. A milestoned event
        by a verified individual human CODEOWNER authorizes NOTHING — this
        is the mechanical statement that the channel is gone. If this test
        is ever "fixed" to make a milestoned event authorize, the fix is
        the re-introduction of FIND-1."""
        events = [self._milestoned_event("ScottThurlow")]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                {"scottthurlow"},
                set(),
            )
        assert result is None

    def test_bot_labeling_is_never_authorized_even_if_in_codeowners(self):
        """The worker/overseer applying needs-ai to its own issue must not
        self-authorize, even in the pathological case where a bot login were
        (mis)listed in CODEOWNERS — is_bot_reviewer wins over CODEOWNERS."""
        events = [self._labeled_event("hos-worker-hos[bot]", "needs-ai", actor_type="Bot")]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                {"hos-worker-hos[bot]"},
                set(),
            )
        assert result is None

    def test_bot_login_denylist_rejects_even_when_type_missing(self):
        events = [self._labeled_event("hos-worker-hos[bot]", "needs-ai", actor_type="")]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                {"scottthurlow"},
                {"hos-worker-hos[bot]"},
            )
        assert result is None

    def test_non_codeowner_human_not_authorized(self):
        events = [self._labeled_event("random-contributor", "needs-ai")]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                {"scottthurlow"},
                set(),
            )
        assert result is None

    def test_no_relevant_event_not_authorized(self):
        events = [{"event": "assigned", "actor": {"login": "ScottThurlow", "type": "User"}}]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                {"scottthurlow"},
                set(),
            )
        assert result is None

    def test_returns_none_on_github_error(self):
        with patch(
            "scripts.automation.lib.probe._run_gh",
            side_effect=GitHubError("timeout"),
        ):
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                {"scottthurlow"},
                set(),
            )
        assert result is None

    def test_empty_codeowners_set_fails_closed(self):
        """A missing/unreadable CODEOWNERS file yields an empty human set —
        every actor must be rejected, not treated as universally authorized."""
        events = [self._labeled_event("ScottThurlow", "needs-ai")]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                set(),
                set(),
            )
        assert result is None


# ---------------------------------------------------------------------------
# probe.py's refactor onto requester_trust.py (#1540 S1, §6.4)
# ---------------------------------------------------------------------------


class TestProbeRefactoredOntoRequesterTrust(_ProbeBase):
    def test_codeowners_humans_is_the_shared_function(self):
        assert _codeowners_humans is requester_trust.codeowners_humans

    def test_verify_codeowner_actor_delegates_to_shared_predicate(self):
        events = [
            {
                "event": "labeled",
                "label": {"name": "needs-ai"},
                "actor": {"login": "ScottThurlow", "type": "User"},
            }
        ]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            with patch(
                "scripts.automation.lib.probe._shared_verify_codeowner_actor",
                return_value="ScottThurlow",
            ) as mock_shared:
                result = _verify_codeowner_actor(
                    "o",
                    "r",
                    1,
                    "needs-ai",
                    {"scottthurlow"},
                    set(),
                )
        mock_shared.assert_called_once_with(
            events,
            {"scottthurlow"},
            set(),
            "needs-ai",
        )
        assert result == "ScottThurlow"

    def test_probe_call_site_passes_no_milestone_title(self):
        """probe.py:428-431 calls the shared predicate with FOUR arguments
        and no milestone title (§1.6): revision 4 was going to ADD an
        argument here; this call site is not edited at all."""
        issues = [_make_issue(100, ["needs-ai"])]
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=issues):
                with patch(
                    "scripts.automation.lib.probe._verify_codeowner_actor",
                    return_value="ScottThurlow",
                ) as mock_verify:
                    probe_repo(
                        "owner",
                        "repo",
                        "rid",
                        probe_strategy=STRATEGY_MILESTONE,
                        milestone=8,
                        repo_root=self.repo_root,
                    )
        args, kwargs = mock_verify.call_args
        assert len(args) + len(kwargs) == 6  # owner, repo, n, label, codeowners, bots
        assert "needs-ai" in args

    def test_probe_milestoned_event_does_not_authorize_at_the_shipped_call_site(self):
        """The gate-level twin of test_milestoned_event_never_authorizes:
        this proves the shipped defect (#1539) is closed in the module
        consumer deployments inherit, at the actual call site, not just
        the pure function."""
        events = [
            {
                "event": "milestoned",
                "actor": {"login": "ScottThurlow", "type": "User"},
            }
        ]
        with patch("scripts.automation.lib.probe._run_gh", return_value=events):
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                {"scottthurlow"},
                set(),
            )
        assert result is None

    def test_probe_events_fetch_is_bounded_paginated(self):
        """One `_run_gh` call per page, `per_page=100&page=<k>`, NEVER
        --paginate; stops at the first page shorter than 100; at most 10
        calls when every page is full."""
        full_page = [{"event": "assigned", "actor": {}} for _ in range(100)]
        short_page = [{"event": "assigned", "actor": {}} for _ in range(5)]

        # Case: 100 then 5 -> 2 calls, COMPLETE
        with patch(
            "scripts.automation.lib.probe._run_gh",
            side_effect=[full_page, short_page],
        ) as mock_gh:
            events = _fetch_events_paginated("o", "r", 1)
        assert mock_gh.call_count == 2
        assert len(events) == 105
        first_endpoint = mock_gh.call_args_list[0][0][0][0]
        assert "per_page=100&page=1" in first_endpoint
        for c in mock_gh.call_args_list:
            assert "--paginate" not in c[0][0][0]

        # Case: 5 alone -> 1 call
        with patch(
            "scripts.automation.lib.probe._run_gh",
            side_effect=[short_page],
        ) as mock_gh:
            events = _fetch_events_paginated("o", "r", 1)
        assert mock_gh.call_count == 1

        # Case: 100 then 0 -> 2 calls
        with patch(
            "scripts.automation.lib.probe._run_gh",
            side_effect=[full_page, []],
        ) as mock_gh:
            events = _fetch_events_paginated("o", "r", 1)
        assert mock_gh.call_count == 2
        assert len(events) == 100

        # Case: 10 full pages (the bound) -> at most 10 calls, no exception
        with patch(
            "scripts.automation.lib.probe._run_gh",
            side_effect=[full_page] * 10,
        ) as mock_gh:
            events = _fetch_events_paginated("o", "r", 1)
        assert mock_gh.call_count == 10
        assert len(events) == 1000

    def test_probe_bound_hit_returns_none_without_stderr(self, capsys):
        """RP6-4 / condition C4: rule 3's WARN belongs to the S2 gate's own
        wrapper alone. probe.py's bound-hit path (10 full pages, no
        qualifying actor found) returns None SILENTLY, as today's
        single-page fetch does — it gains no output surface."""
        full_page = [{"event": "assigned", "actor": {}} for _ in range(100)]
        with patch(
            "scripts.automation.lib.probe._run_gh",
            side_effect=[full_page] * 10,
        ) as mock_gh:
            result = _verify_codeowner_actor(
                "o",
                "r",
                1,
                "needs-ai",
                set(),
                set(),
            )
        assert mock_gh.call_count == 10
        assert result is None
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""

    def test_probe_does_not_construct_a_trusted_set_or_resolve_tiers(self):
        """H3's tier machinery is the S2 gate's. probe.py calls
        codeowners_humans and load_bot_accounts directly, exactly as it
        does today; it does NOT call load_trusted_set and does NOT call
        fetch_collaborators."""
        import scripts.automation.lib.probe as probe_module

        assert not hasattr(probe_module, "load_trusted_set")
        assert not hasattr(probe_module, "fetch_collaborators")


# ---------------------------------------------------------------------------
# probe_repo — cadence / backoff (strategy-agnostic)
# ---------------------------------------------------------------------------


class TestProbeRepoCadence(_ProbeBase):
    def test_not_due_returns_empty_without_api_call(self):
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=[]) as mock_gh:
                with patch(
                    "scripts.automation.lib.probe._load_cadence",
                    return_value=CadenceState(next_due=_iso_future(60)),
                ):
                    results = probe_repo(
                        "owner",
                        "repo",
                        "rid",
                        repo_root=self.repo_root,
                    )
        assert results == []
        mock_gh.assert_not_called()

    def test_backoff_increments_on_no_activity(self):
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=[]):
                probe_repo("owner", "repo", "rid", repo_root=self.repo_root)

        cadence_path = Path(self.repo_root) / ".ai-local" / "hos-automation" / "cadence-state.json"
        data = json.loads(cadence_path.read_text())
        assert data["rid"]["backoff_level"] == 1

    def test_backoff_resets_on_activity(self):
        issues = [_make_issue(1, ["needs-ai"])]
        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=issues):
                probe_repo(
                    "owner",
                    "repo",
                    "rid",
                    probe_strategy=STRATEGY_MILESTONE,
                    milestone=8,
                    repo_root=self.repo_root,
                )

        cadence_path = Path(self.repo_root) / ".ai-local" / "hos-automation" / "cadence-state.json"
        data = json.loads(cadence_path.read_text())
        assert data["rid"]["backoff_level"] == 0

    def test_api_quota_exhausted_returns_empty(self):
        """When the API budget is used up, probe returns [] without any calls."""
        # Fill up the budget by writing directly to the budget file
        soft_state = Path(self.repo_root) / ".ai-local" / "hos-automation"
        soft_state.mkdir(parents=True, exist_ok=True)
        budget = {
            "rid": {
                "window_start": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "calls_used": DEFAULT_API_BUDGET_PER_HOUR,
            }
        }
        (soft_state / "api-budget.json").write_text(json.dumps(budget))

        with self._patch_blast():
            with patch("scripts.automation.lib.probe._run_gh", return_value=[]) as mock_gh:
                results = probe_repo(
                    "owner",
                    "repo",
                    "rid",
                    repo_root=self.repo_root,
                )
        assert results == []
        mock_gh.assert_not_called()
