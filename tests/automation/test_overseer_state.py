"""
Unit tests for overseer_state.py — deterministic state helpers for the
oversight loop.

The module deliberately separates pure JSON/predicate logic from the agent's
GitHub/cron calls so the safety-relevant predicates (stale detection, new-PR
detection, duplicate-in-progress guard, atomic writes) can be unit-tested.
These tests pin those predicates and the atomic-write/round-trip contract.
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from scripts.automation.lib import overseer_state as ostate


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Time helpers ──────────────────────────────────────────────────────────────

class TestParseIso:
    def test_valid_round_trips(self):
        s = "2026-06-21T12:30:00Z"
        parsed = ostate._parse_iso(s)
        assert parsed == datetime(2026, 6, 21, 12, 30, 0, tzinfo=timezone.utc)

    def test_parsed_is_tz_aware_utc(self):
        parsed = ostate._parse_iso("2026-01-01T00:00:00Z")
        assert parsed.tzinfo == timezone.utc

    @pytest.mark.parametrize("bad", ["", "not-a-date", "2026-06-21", None, "2026-06-21 12:00:00"])
    def test_invalid_returns_none(self, bad):
        assert ostate._parse_iso(bad) is None


# ── Atomic write + read_state/write_state round trip ──────────────────────────

class TestAtomicWriteAndState:
    def test_write_then_read_round_trip(self, tmp_path):
        path = tmp_path / "oversight-state.json"
        ostate.write_state(str(path), {"prs": {"1": {"pr_number": 1}}})
        assert ostate.read_state(str(path)) == {"prs": {"1": {"pr_number": 1}}}

    def test_read_missing_returns_empty_dict(self, tmp_path):
        assert ostate.read_state(str(tmp_path / "absent.json")) == {}

    def test_read_corrupt_returns_empty_dict(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{not valid json")
        assert ostate.read_state(str(path)) == {}

    def test_write_none_state_writes_empty_object(self, tmp_path):
        path = tmp_path / "s.json"
        ostate.write_state(str(path), None)
        assert ostate.read_state(str(path)) == {}

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "a" / "b" / "c.json"
        ostate._atomic_write(path, {"k": "v"})
        assert json.loads(path.read_text()) == {"k": "v"}

    def test_atomic_write_leaves_no_tmp_files(self, tmp_path):
        path = tmp_path / "s.json"
        ostate._atomic_write(path, {"k": 1})
        leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith(".tmp-overseer-")]
        assert leftovers == []

    def test_atomic_write_overwrites_prior_content(self, tmp_path):
        path = tmp_path / "s.json"
        ostate._atomic_write(path, {"v": 1})
        ostate._atomic_write(path, {"v": 2})
        assert json.loads(path.read_text()) == {"v": 2}


# ── upsert_pr ─────────────────────────────────────────────────────────────────

class TestUpsertPr:
    def test_first_sight_sets_first_seen(self):
        state = ostate.upsert_pr(
            {}, 7, sign_off_status="pending", second_review_status="none",
            now_iso="2026-06-21T00:00:00Z",
        )
        entry = state["prs"]["7"]
        assert entry["first_seen"] == "2026-06-21T00:00:00Z"
        assert entry["pr_number"] == 7
        assert entry["sign_off_status"] == "pending"
        assert entry["second_review_status"] == "none"

    def test_status_change_updates_status_changed_at(self):
        state = ostate.upsert_pr(
            {}, 7, sign_off_status="pending", second_review_status="none",
            now_iso="2026-06-21T00:00:00Z",
        )
        assert state["prs"]["7"]["status_changed_at"] == "2026-06-21T00:00:00Z"

        state = ostate.upsert_pr(
            state, 7, sign_off_status="approved", second_review_status="none",
            now_iso="2026-06-21T01:00:00Z",
        )
        # Status changed → status_changed_at advances.
        assert state["prs"]["7"]["status_changed_at"] == "2026-06-21T01:00:00Z"

    def test_unchanged_status_keeps_status_changed_at(self):
        state = ostate.upsert_pr(
            {}, 7, sign_off_status="pending", second_review_status="none",
            now_iso="2026-06-21T00:00:00Z",
        )
        state = ostate.upsert_pr(
            state, 7, sign_off_status="pending", second_review_status="r2",
            now_iso="2026-06-21T05:00:00Z",
        )
        # sign_off_status unchanged → status_changed_at frozen at first value.
        assert state["prs"]["7"]["status_changed_at"] == "2026-06-21T00:00:00Z"
        # but last_checked still advances every call.
        assert state["prs"]["7"]["last_checked"] == "2026-06-21T05:00:00Z"
        assert state["prs"]["7"]["second_review_status"] == "r2"

    def test_first_seen_is_not_overwritten_on_reupsert(self):
        state = ostate.upsert_pr(
            {}, 7, sign_off_status="pending", second_review_status="none",
            now_iso="2026-06-21T00:00:00Z",
        )
        state = ostate.upsert_pr(
            state, 7, sign_off_status="approved", second_review_status="none",
            now_iso="2026-06-22T00:00:00Z",
        )
        assert state["prs"]["7"]["first_seen"] == "2026-06-21T00:00:00Z"

    def test_sets_queue_nonempty_and_last_tick(self):
        state = ostate.upsert_pr(
            {}, 7, sign_off_status="pending", second_review_status="none",
            now_iso="2026-06-21T00:00:00Z",
        )
        assert state["queue"] == "non-empty"
        assert state["last_tick"] == "2026-06-21T00:00:00Z"

    def test_mutates_in_place_and_returns_same_object(self):
        original = {}
        returned = ostate.upsert_pr(
            original, 1, sign_off_status="pending", second_review_status="none",
            now_iso="2026-06-21T00:00:00Z",
        )
        assert returned is original


# ── reconcile ─────────────────────────────────────────────────────────────────

class TestReconcile:
    def test_removes_closed_prs(self):
        state = {"prs": {"1": {"pr_number": 1}, "2": {"pr_number": 2}}}
        ostate.reconcile(state, [1])
        assert set(state["prs"].keys()) == {"1"}

    def test_empty_open_set_clears_all_and_marks_empty(self):
        state = {"prs": {"1": {"pr_number": 1}}}
        ostate.reconcile(state, [])
        assert state["prs"] == {}
        assert state["queue"] == "empty"

    def test_keeps_still_open_prs(self):
        state = {"prs": {"3": {"pr_number": 3}, "4": {"pr_number": 4}}}
        ostate.reconcile(state, [3, 4])
        assert set(state["prs"].keys()) == {"3", "4"}

    def test_no_prs_key_is_safe(self):
        state = {}
        result = ostate.reconcile(state, [1, 2])
        assert result is state


# ── stale_prs ─────────────────────────────────────────────────────────────────

class TestStalePrs:
    def test_flags_pr_past_threshold(self):
        now = "2026-06-21T00:00:00Z"
        old = _iso(datetime(2026, 6, 18, 0, 0, 0, tzinfo=timezone.utc))  # 72h prior
        state = {"prs": {"5": {"pr_number": 5, "status_changed_at": old}}}
        assert ostate.stale_prs(state, now_iso=now, threshold_hours=48) == [5]

    def test_does_not_flag_fresh_pr(self):
        now = "2026-06-21T00:00:00Z"
        recent = _iso(datetime(2026, 6, 20, 18, 0, 0, tzinfo=timezone.utc))  # 6h prior
        state = {"prs": {"5": {"pr_number": 5, "status_changed_at": recent}}}
        assert ostate.stale_prs(state, now_iso=now, threshold_hours=48) == []

    def test_skips_already_escalated(self):
        now = "2026-06-21T00:00:00Z"
        old = _iso(datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc))
        state = {"prs": {"5": {"pr_number": 5, "status_changed_at": old, "escalated": True}}}
        assert ostate.stale_prs(state, now_iso=now, threshold_hours=48) == []

    def test_uses_first_seen_when_no_status_change_recorded(self):
        now = "2026-06-21T00:00:00Z"
        old = _iso(datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc))
        # No status_changed_at — falls back to first_seen, which is old → stale.
        state = {"prs": {"5": {"pr_number": 5, "first_seen": old}}}
        assert ostate.stale_prs(state, now_iso=now, threshold_hours=48) == [5]

    def test_brand_new_pr_not_immediately_stale(self):
        now = "2026-06-21T00:00:00Z"
        # No status_changed_at and no first_seen → falls back to now → never stale.
        state = {"prs": {"5": {"pr_number": 5}}}
        assert ostate.stale_prs(state, now_iso=now, threshold_hours=48) == []

    def test_invalid_now_returns_empty(self):
        state = {"prs": {"5": {"pr_number": 5, "status_changed_at": "2020-01-01T00:00:00Z"}}}
        assert ostate.stale_prs(state, now_iso="garbage") == []

    def test_exactly_at_threshold_is_stale(self):
        now = "2026-06-21T00:00:00Z"
        exactly = _iso(datetime(2026, 6, 19, 0, 0, 0, tzinfo=timezone.utc))  # exactly 48h
        state = {"prs": {"5": {"pr_number": 5, "status_changed_at": exactly}}}
        assert ostate.stale_prs(state, now_iso=now, threshold_hours=48) == [5]


# ── is_new_pr ─────────────────────────────────────────────────────────────────

class TestIsNewPr:
    def test_unknown_pr_is_new(self):
        assert ostate.is_new_pr({"prs": {"1": {}}}, 2) is True

    def test_known_pr_is_not_new(self):
        assert ostate.is_new_pr({"prs": {"1": {}}}, 1) is False

    def test_empty_state_means_new(self):
        assert ostate.is_new_pr({}, 1) is True


# ── schedule read/write/clear ─────────────────────────────────────────────────

class TestSchedule:
    def test_write_then_read(self, tmp_path):
        path = tmp_path / "oversight-schedule.json"
        ostate.write_schedule(
            str(path),
            stop_at="2026-06-22T00:00:00Z",
            created_at="2026-06-21T00:00:00Z",
            loop_job_tag="job-abc",
        )
        sched = ostate.read_schedule(str(path))
        assert sched == {
            "stop_at": "2026-06-22T00:00:00Z",
            "created_at": "2026-06-21T00:00:00Z",
            "loop_job_tag": "job-abc",
        }

    def test_read_missing_returns_empty(self, tmp_path):
        assert ostate.read_schedule(str(tmp_path / "none.json")) == {}

    def test_clear_removes_file(self, tmp_path):
        path = tmp_path / "sched.json"
        ostate.write_schedule(
            str(path), stop_at="x", created_at="y", loop_job_tag="z",
        )
        assert path.exists()
        ostate.clear_schedule(str(path))
        assert not path.exists()

    def test_clear_absent_file_is_noop(self, tmp_path):
        # missing_ok=True — must not raise.
        ostate.clear_schedule(str(tmp_path / "never.json"))


# ── record_stop ───────────────────────────────────────────────────────────────

class TestRecordStop:
    def test_writes_stop_record_with_safe_timestamp(self, tmp_path):
        ostate.record_stop("manual-stop", repo_root=str(tmp_path))
        records = list((tmp_path / ".ai-local" / "hos-automation").glob("overseer-stop-*.json"))
        assert len(records) == 1
        # Colons replaced with dashes so the filename is portable.
        assert ":" not in records[0].name
        data = json.loads(records[0].read_text())
        assert data["reason"] == "manual-stop"
        assert "stopped_at" in data


# ── per-PR state cache ────────────────────────────────────────────────────────

class TestUpdatePrState:
    def test_writes_valid_status(self, tmp_path):
        ostate.update_pr_state(42, "cid-1", "reviewing", repo_root=str(tmp_path))
        path = tmp_path / ".ai-local" / "hos-automation" / "pr-state-42.json"
        data = json.loads(path.read_text())
        assert data["pr"] == 42
        assert data["cid"] == "cid-1"
        assert data["status"] == "reviewing"
        assert "last_checked" in data

    @pytest.mark.parametrize("status", ["reviewing", "waiting", "bounced", "merged"])
    def test_all_valid_statuses_accepted(self, tmp_path, status):
        ostate.update_pr_state(1, "cid", status, repo_root=str(tmp_path))

    def test_invalid_status_raises_value_error(self, tmp_path):
        with pytest.raises(ValueError, match="invalid status"):
            ostate.update_pr_state(1, "cid", "bogus", repo_root=str(tmp_path))


class TestIsDuplicateInProgress:
    def test_reviewing_and_fresh_is_duplicate(self, tmp_path):
        ostate.update_pr_state(9, "cid", "reviewing", repo_root=str(tmp_path))
        assert ostate.is_duplicate_in_progress(9, repo_root=str(tmp_path)) is True

    def test_missing_file_is_not_duplicate(self, tmp_path):
        assert ostate.is_duplicate_in_progress(9, repo_root=str(tmp_path)) is False

    def test_non_reviewing_status_is_not_duplicate(self, tmp_path):
        ostate.update_pr_state(9, "cid", "waiting", repo_root=str(tmp_path))
        assert ostate.is_duplicate_in_progress(9, repo_root=str(tmp_path)) is False

    def test_stale_reviewing_is_not_duplicate(self, tmp_path):
        path = tmp_path / ".ai-local" / "hos-automation" / "pr-state-9.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        old = _iso(datetime.now(timezone.utc) - timedelta(minutes=30))
        path.write_text(json.dumps({"pr": 9, "status": "reviewing", "last_checked": old}))
        # 30m old > 20m timeout → prior instance presumed dead.
        assert ostate.is_duplicate_in_progress(9, repo_root=str(tmp_path)) is False

    def test_corrupt_file_is_not_duplicate(self, tmp_path):
        path = tmp_path / ".ai-local" / "hos-automation" / "pr-state-9.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken")
        assert ostate.is_duplicate_in_progress(9, repo_root=str(tmp_path)) is False

    def test_missing_last_checked_is_not_duplicate(self, tmp_path):
        path = tmp_path / ".ai-local" / "hos-automation" / "pr-state-9.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pr": 9, "status": "reviewing"}))
        assert ostate.is_duplicate_in_progress(9, repo_root=str(tmp_path)) is False
