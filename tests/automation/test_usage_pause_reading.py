"""#1944 S1: the reading file (ADR-1944 A2-2, A2-3)."""

import os

import pytest

from tests.automation.usage_support import fx, settings, up


def cls_for(name, outcome=None):
    return up.classify_read(outcome or up.ReadOutcome("exited", 0, None), fx(name), b"")


def build(
    name="capture2-envelope-2026-10-03.json", epoch=1_000_000, previous=None, sett=None, **kw
):
    return up.build_reading(
        run_epoch=epoch,
        classification=cls_for(name),
        diagnostics=kw.get("diagnostics"),
        previous=previous,
        settings=sett or settings(),
    )


def write(tmp_path, fields):
    p = tmp_path / "reading"
    p.write_text(up.render_reading(fields), encoding="utf-8")
    return p


def test_render_read_roundtrip(tmp_path):
    fields = build()
    r = up.read_reading(write(tmp_path, fields))
    assert r.state == "ok"
    d = dict(fields)
    d.pop("schema")
    assert dict(r.fields) == {k: v for k, v in d.items() if v}
    assert r.fields["session_pct"] == "11" and r.fields["weekly_model_fable_pct"] == "0"
    assert r.fields["parsed_via"] == "grep" and r.fields["cost_usd"] == "0"


def test_missing(tmp_path):
    assert up.read_reading(tmp_path / "nope").state == "missing"


def _raw(tmp_path, data):
    p = tmp_path / "r"
    p.write_bytes(data)
    return up.read_reading(p)


def test_truncated_cases(tmp_path):
    assert _raw(tmp_path, b"").state == "truncated"
    assert _raw(tmp_path, b"schema=1\nkind=reading\n").state == "truncated"
    assert _raw(tmp_path, b"schema=1\nkind=reading\nend=1").state == "truncated"


def test_schema_2_unknown(tmp_path):
    assert _raw(tmp_path, b"schema=2\nkind=reading\nend=1\n").state == "schema_unknown"


def test_garbled_line_unreadable(tmp_path):
    assert _raw(tmp_path, b"schema=1\nnot a line\nend=1\n").state == "unreadable"
    assert _raw(tmp_path, b"kind=reading\nend=1\n").state == "unreadable"
    assert _raw(tmp_path, b"schema=1\nschema=1\nend=1\n").state == "unreadable"


def test_duplicate_key_unreadable(tmp_path):
    assert _raw(tmp_path, b"schema=1\nkind=reading\nkind=reading\nend=1\n").state == "unreadable"


def test_oversize_unreadable(tmp_path):
    assert _raw(tmp_path, b"schema=1\n" + b"a=" + b"x" * 70000 + b"\nend=1\n").state == "unreadable"


def test_values_sanitized():
    text = up.render_reading(
        [("schema", "1"), ("detail", "a\nb\x07c " + "x" * 300), ("empty", "  ")]
    )
    lines = text.split("\n")
    assert all("\x07" not in ln for ln in lines)
    detail = [ln for ln in lines if ln.startswith("detail=")][0]
    assert len(detail) - len("detail=") <= up.VALUE_CAP_CHARS
    assert "empty=" not in text and text.endswith("end=1\n")


def test_atomic_write_no_tmp_left(tmp_path):
    target = tmp_path / "reading"
    up.write_atomic(target, b"x", 0o600)
    up.write_atomic(target, b"y", 0o600)
    assert target.read_bytes() == b"y" and sorted(os.listdir(tmp_path)) == ["reading"]
    assert (target.stat().st_mode & 0o777) == 0o600


def test_failure_reading_has_no_pct_keys():
    f = dict(build("empty-session-envelope-blank.json"))
    assert f["outcome"] == "failure" and f["reason"] == "empty_session"
    assert not any(
        k.endswith("_pct") or k.startswith("weekly_model_") or k == "parsed_via" for k in f
    )
    assert f["subscription_marker"] == "absent"


def test_failure_reading_keeps_cost_tokens():
    f = dict(build("empty-session-envelope-legacy-text.json"))
    assert f["cost_usd"] == "0" and f["read_tokens"] == "0" and f["input_tokens"] == "0"


def test_transport_failure_records_no_cost():
    cls = up.classify_read(up.ReadOutcome("exited", 255, None), b"", b"Permission denied")
    f = dict(
        up.build_reading(
            run_epoch=1, classification=cls, diagnostics=None, previous=None, settings=settings()
        )
    )
    assert f["reason"] == "ssh_failed" and f["remote_exit"] == "255" and "cost_usd" not in f
    assert f["detail"].startswith("stderr:")


def test_carryover_consecutive_and_last_success(tmp_path):
    ok1 = write(tmp_path, build(epoch=100))
    prev = up.read_reading(ok1)
    assert prev.fields["consecutive_failures"] == "0" and prev.fields["last_success_epoch"] == "100"
    bad = build("empty-session-envelope-blank.json", epoch=200, previous=prev)
    assert dict(bad)["consecutive_failures"] == "1" and dict(bad)["last_success_epoch"] == "100"
    prev2 = up.read_reading(write(tmp_path, bad))
    bad2 = dict(build("empty-session-envelope-blank.json", epoch=300, previous=prev2))
    assert bad2["consecutive_failures"] == "2" and bad2["last_success_epoch"] == "100"
    fresh = dict(
        build(
            "empty-session-envelope-blank.json", epoch=300, previous=up.ReadingRead("missing", {})
        )
    )
    assert fresh["consecutive_failures"] == "1" and "last_success_epoch" not in fresh
    assert dict(build(epoch=400, previous=prev2))["consecutive_failures"] == "0"


def test_bash_crash_file_parses(tmp_path):
    p = tmp_path / "r"
    p.write_text(
        "schema=1\nkind=reading\nrun_at=2026-10-03T00:00:00Z\nrun_epoch=5\n"
        "outcome=crashed\nreason=crashed\ndetail=exit=1 at P4\nend=1\n"
    )
    r = up.read_reading(p)
    assert r.state == "ok" and r.fields["outcome"] == "crashed"
    d = up.evaluate_cycle(r, settings(), 6.0, poller_artifacts_present=True)
    assert d.reason == "read_failed:crashed"


def test_poll_view_keys_present():
    f = dict(build())
    assert f["poll_settings_status"] == "valid" and f["poll_fail_mode"] == "closed"
    assert (
        f["poll_session_threshold"],
        f["poll_weekly_threshold"],
        f["poll_weekly_model_threshold"],
    ) == ("90", "90", "90")
    assert f["poll_staleness_seconds"] == "900" and f["poll_pause_condition"] == "0"
    assert f["poll_pause_reason"].startswith("session 11% < 90")


def test_poll_view_invalid_settings():
    bad = up.SettingsResult(
        dict(up.DEFAULTS), "invalid:session_threshold", "session_threshold", "0"
    )
    f = dict(build(sett=bad))
    assert f["poll_settings_status"] == "invalid:session_threshold"
    assert (
        f["poll_pause_condition"] == "1"
        and f["poll_pause_reason"] == "settings_invalid:session_threshold"
    )
    assert not any(k.startswith("poll_") and k.endswith("_threshold") for k in f)
    assert f["poll_staleness_seconds"] == "900"


def test_poll_view_pause_reason_exact():
    f = dict(build(sett=settings(session_threshold=5)))
    assert f["poll_pause_condition"] == "1" and f["poll_pause_reason"] == "session 11% >= 5"
    assert f["poll_session_threshold"] == "5"


def test_top_subagents_value_bounded():
    items = tuple(("name%03d" % i, 1) for i in range(100))
    assert len(up._bounded_top(items)[0]) <= up.VALUE_CAP_CHARS


def test_cost_format():
    assert (
        up.format_cost(0) == "0" and up.format_cost(0.0123) == "0.0123" and up.format_cost(2) == "2"
    )
    assert "e" in up.format_cost(1e-30)


def _win(items, more):
    return up.ParseResult(
        True,
        None,
        1,
        None,
        2,
        None,
        (),
        (up.WindowBreakdown("24h", "24h", 1, 1, None, None, None, items, more),),
        False,
    )


def test_top_subagents_cap_adds_dropped_to_more():
    items = tuple(("n%02d" % i, 1) for i in range(60))
    fields = dict(up._success_fields(_win(items, 3)))
    kept = fields["top_subagents_24h"].count("=")
    assert kept < 60 and len(fields["top_subagents_24h"]) <= up.VALUE_CAP_CHARS
    assert fields["top_subagents_more_24h"] == str(3 + 60 - kept)


def test_top_subagents_nothing_dropped_keeps_more():
    fields = dict(up._success_fields(_win((("a", 1), ("b", 2)), 4)))
    assert fields["top_subagents_24h"] == "a=1,b=2" and fields["top_subagents_more_24h"] == "4"


def test_top_subagents_first_item_too_long_both_absent():
    fields = dict(up._success_fields(_win((("x" * 300, 1),), 0)))
    assert "top_subagents_24h" not in fields and "top_subagents_more_24h" not in fields


def test_write_atomic_does_not_follow_planted_symlink(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("precious")
    (tmp_path / "reading.tmp").symlink_to(victim)
    up.write_atomic(tmp_path / "reading", b"new", 0o600)
    assert victim.read_text() == "precious"
    assert (tmp_path / "reading").read_bytes() == b"new"
    assert not (tmp_path / "reading.tmp").exists()


def test_write_atomic_mode_correct_over_existing_loose_file(tmp_path):
    stale = tmp_path / "reading.tmp"
    stale.write_text("old")
    stale.chmod(0o666)
    up.write_atomic(tmp_path / "reading", b"x", 0o600)
    assert (tmp_path / "reading").stat().st_mode & 0o777 == 0o600


def test_open_private_replaces_symlink(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("precious")
    (tmp_path / "out").symlink_to(victim)
    with up._open_private(tmp_path / "out") as fh:
        fh.write(b"data")
    assert victim.read_text() == "precious"
    assert (tmp_path / "out").read_bytes() == b"data"
    assert (tmp_path / "out").stat().st_mode & 0o777 == 0o600


def test_write_atomic_removes_tmp_on_failure(tmp_path, monkeypatch):
    def boom(*_a):
        raise OSError("disk full")

    monkeypatch.setattr(up.os, "fsync", boom)
    with pytest.raises(OSError):
        up.write_atomic(tmp_path / "reading", b"x", 0o600)
    assert list(tmp_path.iterdir()) == []
    monkeypatch.undo()
    (tmp_path / "reading").mkdir()
    with pytest.raises(OSError):
        up.write_atomic(tmp_path / "reading", b"x", 0o600)
    assert not (tmp_path / "reading.tmp").exists()


def test_stderr_detail_keeps_the_tail():
    cls = up.classify_read(
        up.ReadOutcome("exited", 255, None),
        b"",
        ("head-marker " + "x" * 500 + " tail-marker").encode(),
    )
    assert cls.detail.endswith("tail-marker") and "head-marker" not in cls.detail
    assert len(cls.detail) <= up.VALUE_CAP_CHARS
