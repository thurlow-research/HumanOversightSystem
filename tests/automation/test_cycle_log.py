"""
Unit tests for cycle_log.py — structured cycle-event audit logging.

Covers: JSON line shape (event/role/timestamp/kwargs), append semantics,
argument parsing (int coercion, bare-flag → True), and the empty-args
usage-error exit. The cron scripts call this on every cycle, so a silently
broken JSON line would corrupt the audit trail.
"""

import json
from pathlib import Path

import pytest

from scripts.automation.lib import cycle_log


class TestLogEvent:
    def test_writes_single_json_line(self, tmp_path, monkeypatch):
        log_file = tmp_path / "audit" / "oversight-log.jsonl"
        monkeypatch.setattr(cycle_log, "_find_audit_log", lambda: log_file)

        cycle_log.log_event("cycle-stop", reason="pr-awaiting-review", pr=587)

        lines = log_file.read_text().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "cycle-stop"
        assert entry["role"] == "worker"
        assert entry["reason"] == "pr-awaiting-review"
        assert entry["pr"] == 587

    def test_timestamp_is_iso_utc_z(self, tmp_path, monkeypatch):
        log_file = tmp_path / "oversight-log.jsonl"
        monkeypatch.setattr(cycle_log, "_find_audit_log", lambda: log_file)

        cycle_log.log_event("cycle-pick", issue=559)

        entry = json.loads(log_file.read_text().splitlines()[0])
        ts = entry["timestamp"]
        # Strict ISO-8601 UTC with trailing Z, no microseconds.
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(ts) == len("2026-06-21T00:00:00Z")

    def test_appends_rather_than_truncates(self, tmp_path, monkeypatch):
        log_file = tmp_path / "oversight-log.jsonl"
        monkeypatch.setattr(cycle_log, "_find_audit_log", lambda: log_file)

        cycle_log.log_event("cycle-pick", issue=1)
        cycle_log.log_event("cycle-pr-opened", pr=2, issue=1)

        lines = log_file.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "cycle-pick"
        assert json.loads(lines[1])["event"] == "cycle-pr-opened"

    def test_creates_parent_directory(self, tmp_path, monkeypatch):
        log_file = tmp_path / "deep" / "nested" / "audit" / "log.jsonl"
        monkeypatch.setattr(cycle_log, "_find_audit_log", lambda: log_file)

        cycle_log.log_event("cycle-stop", reason="done")

        assert log_file.exists()

    def test_kwargs_with_special_chars_are_json_escaped(self, tmp_path, monkeypatch):
        log_file = tmp_path / "log.jsonl"
        monkeypatch.setattr(cycle_log, "_find_audit_log", lambda: log_file)

        title = 'fix "quoted" thing\nwith newline'
        cycle_log.log_event("cycle-pick", title=title)

        # The on-disk line must remain a single, parseable JSON record.
        lines = log_file.read_text().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["title"] == title


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


class TestFindAuditLog:
    def test_returns_path_object(self):
        result = cycle_log._find_audit_log()
        assert isinstance(result, Path)
        assert result.name == "oversight-log.jsonl"
