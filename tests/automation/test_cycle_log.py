"""
Unit tests for cycle_log.py — structured cycle-event audit logging.

Covers: record shape (event/role/timestamp/kwargs), per-entry write semantics
(one write-once file per event under audit/log/, SPEC-888 #888 P2), argument
parsing (int coercion, bare-flag → True), and the empty-args usage-error exit.
The cron scripts call this on every cycle, so a silently broken record would
corrupt the audit trail.
"""

import json
from pathlib import Path

import pytest

from scripts.automation.lib import cycle_log


def _read_events(root: Path) -> list[dict]:
    """Reconstruct the chronological event list from the per-entry records."""
    return [json.loads(b) for b in cycle_log._AUDIT_LOG.read_stream(str(root))]


class TestLogEvent:
    def test_writes_single_record(self, tmp_path, monkeypatch):
        (tmp_path / "audit").mkdir()
        monkeypatch.setattr(cycle_log, "_find_root", lambda: tmp_path)

        cycle_log.log_event("cycle-stop", reason="pr-awaiting-review", pr=587)

        events = _read_events(tmp_path)
        assert len(events) == 1
        entry = events[0]
        assert entry["event"] == "cycle-stop"
        assert entry["role"] == "worker"
        assert entry["reason"] == "pr-awaiting-review"
        assert entry["pr"] == 587

    def test_record_lands_under_month_shard(self, tmp_path, monkeypatch):
        (tmp_path / "audit").mkdir()
        monkeypatch.setattr(cycle_log, "_find_root", lambda: tmp_path)

        cycle_log.log_event("cycle-pick", issue=559)

        records = list((tmp_path / "audit" / "log").rglob("*.json"))
        assert len(records) == 1
        # audit/log/<YYYY>/<MM>/<ts>-cycle-pick-<hash>.json
        rel = records[0].relative_to(tmp_path / "audit" / "log").as_posix()
        assert rel.count("/") == 2  # <YYYY>/<MM>/<file>
        assert "cycle-pick" in records[0].name

    def test_timestamp_is_iso_utc_z(self, tmp_path, monkeypatch):
        (tmp_path / "audit").mkdir()
        monkeypatch.setattr(cycle_log, "_find_root", lambda: tmp_path)

        cycle_log.log_event("cycle-pick", issue=559)

        ts = _read_events(tmp_path)[0]["timestamp"]
        # Strict ISO-8601 UTC with trailing Z, no microseconds.
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(ts) == len("2026-06-21T00:00:00Z")

    def test_distinct_events_are_distinct_records(self, tmp_path, monkeypatch):
        (tmp_path / "audit").mkdir()
        monkeypatch.setattr(cycle_log, "_find_root", lambda: tmp_path)

        cycle_log.log_event("cycle-pick", issue=1)
        cycle_log.log_event("cycle-pr-opened", pr=2, issue=1)

        events = _read_events(tmp_path)
        assert {e["event"] for e in events} == {"cycle-pick", "cycle-pr-opened"}
        # Two events → two distinct files (the conflict-free property).
        assert len(list((tmp_path / "audit" / "log").rglob("*.json"))) == 2

    def test_creates_log_directory(self, tmp_path, monkeypatch):
        # No audit/log subtree yet — write_event must create it.
        (tmp_path / "audit").mkdir()
        monkeypatch.setattr(cycle_log, "_find_root", lambda: tmp_path)

        cycle_log.log_event("cycle-stop", reason="done")

        assert (tmp_path / "audit" / "log").is_dir()
        assert _read_events(tmp_path)[0]["reason"] == "done"

    def test_kwargs_with_special_chars_are_json_escaped(self, tmp_path, monkeypatch):
        (tmp_path / "audit").mkdir()
        monkeypatch.setattr(cycle_log, "_find_root", lambda: tmp_path)

        title = 'fix "quoted" thing\nwith newline'
        cycle_log.log_event("cycle-pick", title=title)

        # The record must remain a single, parseable JSON object that round-trips.
        events = _read_events(tmp_path)
        assert len(events) == 1
        assert events[0]["title"] == title


class TestParseArgs:
    def test_event_only(self):
        event, kwargs = cycle_log._parse_args(["cycle-start"])
        assert event == "cycle-start"
        assert kwargs == {}

    def test_key_value_pairs(self):
        event, kwargs = cycle_log._parse_args(["cycle-pr-opened", "pr=613", "issue=559"])
        assert event == "cycle-pr-opened"
        assert kwargs == {"pr": 613, "issue": 559}

    def test_integer_coercion(self):
        _, kwargs = cycle_log._parse_args(["e", "pr=587"])
        assert kwargs["pr"] == 587
        assert isinstance(kwargs["pr"], int)

    def test_non_integer_stays_string(self):
        _, kwargs = cycle_log._parse_args(["e", "reason=pr-awaiting-review"])
        assert kwargs["reason"] == "pr-awaiting-review"

    def test_value_with_embedded_equals_splits_once(self):
        _, kwargs = cycle_log._parse_args(["e", "url=https://x/y?a=b"])
        assert kwargs["url"] == "https://x/y?a=b"

    def test_bare_flag_becomes_true(self):
        _, kwargs = cycle_log._parse_args(["e", "blocked"])
        assert kwargs["blocked"] is True

    def test_empty_args_exits_nonzero(self):
        with pytest.raises(SystemExit) as exc:
            cycle_log._parse_args([])
        assert exc.value.code == 1


class TestFindRoot:
    def test_returns_repo_root_with_audit_dir(self):
        # In this repo the module sits under a tree whose root has an audit/ dir.
        result = cycle_log._find_root()
        assert isinstance(result, Path)
        assert (result / "audit").is_dir()
