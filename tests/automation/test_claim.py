"""
Unit tests for claim.py — claim-then-verify with UUID instance-id + heartbeat.

The claim mechanism is a CONTENTION REDUCER (not mutual exclusion); its safety
contract is the deterministic tiebreak ("lowest instance-id among valid,
non-stale claims wins") and the staleness cutoff. These tests pin both, plus
the envelope shapes, heartbeat self-termination, and best-effort release.

All GitHub I/O (_run_gh, list_issue_comments) and the wall-clock/jitter
(time.sleep, random.uniform, uuid4) are mocked so the tests are deterministic.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

from scripts.automation.lib import claim as claim_mod
from scripts.automation.lib.claim import (
    ClaimResult,
    HeartbeatResult,
    claim,
    heartbeat,
    release_claim,
    _build_claim_body,
    _build_heartbeat_body,
    _extract_claims,
    CLAIM_TIMEOUT_MINUTES,
)
from scripts.automation.lib.github import GitHubError


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _comment(body: str, updated_at: str) -> dict:
    return {"body": body, "updated_at": updated_at}


# ── Envelope builders ─────────────────────────────────────────────────────────

class TestBuildClaimBody:
    def test_contains_required_envelope_fields(self):
        body = _build_claim_body("CID9", "iid-123", "hos-worker")
        assert "type: claim" in body
        assert "correlation-id: CID9" in body
        assert "instance-id: iid-123" in body
        assert "from: hos-worker" in body
        assert "claimed-at:" in body

    def test_includes_cid_marker_line(self):
        # The cid keystone line must be present so re-reads can match the claim.
        body = _build_claim_body("CID9", "iid-123", "hos-worker")
        assert "correlation-id: CID9" in body


class TestBuildHeartbeatBody:
    def test_default_status_in_progress(self):
        body = _build_heartbeat_body("CID9", "iid-1", "w")
        assert "type: heartbeat" in body
        assert "status: in-progress" in body
        assert "heartbeat-at:" in body

    def test_custom_terminal_status(self):
        body = _build_heartbeat_body("CID9", "iid-1", "w", status="terminal:completed")
        assert "status: terminal:completed" in body


# ── _extract_claims ───────────────────────────────────────────────────────────

class TestExtractClaims:
    def test_extracts_fresh_claim(self):
        now = _iso(datetime.now(timezone.utc))
        body = _build_claim_body("CID", "iid-aaa", "w")
        claims = _extract_claims([_comment(body, now)], "CID")
        assert claims == [("iid-aaa", now)]

    def test_ignores_other_cid(self):
        now = _iso(datetime.now(timezone.utc))
        body = _build_claim_body("OTHER", "iid-aaa", "w")
        assert _extract_claims([_comment(body, now)], "CID") == []

    def test_ignores_non_claim_non_heartbeat(self):
        now = _iso(datetime.now(timezone.utc))
        body = "correlation-id: CID\ntype: chatter\ninstance-id: iid-x"
        assert _extract_claims([_comment(body, now)], "CID") == []

    def test_heartbeat_envelope_counts_as_active_claim(self):
        now = _iso(datetime.now(timezone.utc))
        body = _build_heartbeat_body("CID", "iid-hb", "w")
        claims = _extract_claims([_comment(body, now)], "CID")
        assert claims == [("iid-hb", now)]

    def test_skips_stale_claim(self):
        stale = _iso(
            datetime.now(timezone.utc) - timedelta(minutes=CLAIM_TIMEOUT_MINUTES + 5)
        )
        body = _build_claim_body("CID", "iid-old", "w")
        assert _extract_claims([_comment(body, stale)], "CID") == []

    def test_skips_comment_with_no_instance_id(self):
        now = _iso(datetime.now(timezone.utc))
        body = "correlation-id: CID\ntype: claim\n(no instance line)"
        assert _extract_claims([_comment(body, now)], "CID") == []

    def test_skips_unparseable_timestamp(self):
        body = _build_claim_body("CID", "iid-aaa", "w")
        assert _extract_claims([_comment(body, "not-a-date")], "CID") == []

    def test_collects_multiple_competing_claims(self):
        now = _iso(datetime.now(timezone.utc))
        comments = [
            _comment(_build_claim_body("CID", "iid-2", "w"), now),
            _comment(_build_claim_body("CID", "iid-1", "w"), now),
        ]
        ids = sorted(iid for iid, _ in _extract_claims(comments, "CID"))
        assert ids == ["iid-1", "iid-2"]


# ── claim() — claim-then-verify ───────────────────────────────────────────────

class TestClaim:
    def _run(self, my_uuid, comments_after, post_ok=True):
        """Drive claim() with a fixed uuid and a controlled re-read result."""
        run_gh = patch.object(claim_mod, "_run_gh")
        list_comments = patch.object(claim_mod, "list_issue_comments", return_value=comments_after)
        uuid4 = patch.object(claim_mod.uuid, "uuid4", return_value=my_uuid)
        sleep = patch.object(claim_mod.time, "sleep")
        jitter = patch.object(claim_mod.random, "uniform", return_value=0)
        with run_gh as m_run, list_comments, uuid4, sleep, jitter:
            if not post_ok:
                m_run.side_effect = GitHubError("post failed")
            return claim("o", "r", 1, "CID", "hos-worker")

    def test_wins_when_lowest_instance_id(self):
        now = _iso(datetime.now(timezone.utc))
        comments = [
            _comment(_build_claim_body("CID", "iid-aaa", "w"), now),  # ours (lowest)
            _comment(_build_claim_body("CID", "iid-zzz", "w"), now),
        ]
        result = self._run("iid-aaa", comments)
        assert result.won is True
        assert result.instance_id == "iid-aaa"

    def test_loses_to_lower_instance_id(self):
        now = _iso(datetime.now(timezone.utc))
        comments = [
            _comment(_build_claim_body("CID", "iid-aaa", "w"), now),  # competitor (lower)
            _comment(_build_claim_body("CID", "iid-zzz", "w"), now),  # ours
        ]
        result = self._run("iid-zzz", comments)
        assert result.won is False
        assert "iid-aaa" in result.reason

    def test_no_active_claims_after_post_loses(self):
        result = self._run("iid-aaa", [])
        assert result.won is False
        assert "No active claims" in result.reason

    def test_post_failure_returns_loss(self):
        result = self._run("iid-aaa", [], post_ok=False)
        assert result.won is False
        assert "Failed to post claim" in result.reason

    def test_reread_failure_returns_loss(self):
        uuid4 = patch.object(claim_mod.uuid, "uuid4", return_value="iid-aaa")
        sleep = patch.object(claim_mod.time, "sleep")
        jitter = patch.object(claim_mod.random, "uniform", return_value=0)
        with patch.object(claim_mod, "_run_gh"), \
             patch.object(claim_mod, "list_issue_comments", side_effect=GitHubError("boom")), \
             uuid4, sleep, jitter:
            result = claim("o", "r", 1, "CID", "hos-worker")
        assert result.won is False
        assert "Failed to re-read" in result.reason


# ── heartbeat() ───────────────────────────────────────────────────────────────

class TestHeartbeat:
    def test_self_terminates_when_activation_lost(self):
        with patch.object(claim_mod, "_run_gh") as m_run:
            result = heartbeat(
                "o", "r", 1, "CID", "iid", "w",
                check_activation_fn=lambda: False,
            )
        assert result.should_continue is False
        assert "Activation" in result.reason
        m_run.assert_not_called()  # must short-circuit before posting

    def test_self_terminates_when_halt_present(self):
        with patch.object(claim_mod, "_run_gh") as m_run:
            result = heartbeat(
                "o", "r", 1, "CID", "iid", "w",
                check_activation_fn=lambda: True,
                check_halt_fn=lambda: True,
            )
        assert result.should_continue is False
        assert "halt" in result.reason.lower()
        m_run.assert_not_called()

    def test_posts_and_continues_on_healthy_beat(self):
        with patch.object(claim_mod, "_run_gh") as m_run:
            result = heartbeat(
                "o", "r", 1, "CID", "iid", "w",
                check_activation_fn=lambda: True,
                check_halt_fn=lambda: False,
            )
        assert result.should_continue is True
        m_run.assert_called_once()

    def test_post_failure_is_non_fatal(self):
        with patch.object(claim_mod, "_run_gh", side_effect=GitHubError("network")):
            result = heartbeat("o", "r", 1, "CID", "iid", "w")
        # A failed heartbeat POST must NOT stop the worker.
        assert result.should_continue is True

    def test_no_check_fns_still_posts_and_continues(self):
        with patch.object(claim_mod, "_run_gh") as m_run:
            result = heartbeat("o", "r", 1, "CID", "iid", "w")
        assert result.should_continue is True
        m_run.assert_called_once()


# ── release_claim() ───────────────────────────────────────────────────────────

class TestReleaseClaim:
    def test_posts_terminal_envelope_and_deletes_label(self):
        with patch.object(claim_mod, "_run_gh") as m_run:
            release_claim("o", "r", 1, "CID", "iid", "w", reason="completed")
        # Two calls: terminal comment POST, then hos-claimed label DELETE.
        assert m_run.call_count == 2
        comment_call, label_call = m_run.call_args_list
        assert "comments" in comment_call.args[0][0]
        assert "labels/hos-claimed" in label_call.args[0][0]
        assert "DELETE" in label_call.args[0]

    def test_best_effort_swallows_github_error(self):
        # Must not raise — a failed release ages out naturally.
        with patch.object(claim_mod, "_run_gh", side_effect=GitHubError("boom")):
            release_claim("o", "r", 1, "CID", "iid", "w")


# ── dataclasses ───────────────────────────────────────────────────────────────

class TestDataclasses:
    def test_claim_result_fields(self):
        r = ClaimResult(won=True, instance_id="x", reason="ok")
        assert (r.won, r.instance_id, r.reason) == (True, "x", "ok")

    def test_heartbeat_result_fields(self):
        r = HeartbeatResult(should_continue=False, reason="halt")
        assert (r.should_continue, r.reason) == (False, "halt")
