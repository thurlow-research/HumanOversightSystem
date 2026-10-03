"""#1944 S1: /usage text parsing and read classification (ADR-1944 A2-7)."""

import json
import os
import stat
import time

import pytest

from tests.automation.usage_support import FIXTURES, fx, parse_fixture, sha, up


def _env_text(text):
    return json.dumps({"result": text, "total_cost_usd": 0, "usage": {}}).encode()


def test_d1_fixture_is_verbatim():
    data = fx("d1-loopback-2026-10-02.txt")
    assert len(data) == 1091
    expected = "c8d52b0ace496176dded36c78b13b587a2c378cd9d2f6a5acbfdf63266196683"  # pragma: allowlist secret
    assert sha(data) == expected
    derived = json.loads(fx("d1-envelope-derived.json"))
    assert derived["result"] + "\n" == data.decode()


def test_d1_success_values():
    _env, p = parse_fixture("d1-envelope-derived.json")
    assert p.ok and (p.session_pct, p.weekly_all_pct) == (6, 48)
    assert p.session_resets == "Oct 3, 2:40am (UTC)"
    assert p.weekly_all_resets == "Oct 3, 12am (UTC)"
    assert p.subscription_marker is True


def test_d1_breakdown_windows():
    _env, p = parse_fixture("d1-envelope-derived.json")
    by = {w.slug: w for w in p.windows}
    assert (by["24h"].requests, by["24h"].sessions) == (2049, 181)
    assert (
        by["24h"].subagent_heavy_pct,
        by["24h"].long_context_pct,
        by["24h"].long_session_pct,
    ) == (61, 36, 34)
    assert by["24h"].top_subagents[0] == ("technical-design", 6)
    assert by["24h"].top_subagents_more == 0
    assert len(by["7d"].top_subagents) == 8 and by["7d"].top_subagents_more == 2


def test_capture2_success_values():
    _env, p = parse_fixture("capture2-envelope-2026-10-03.json")
    assert (p.session_pct, p.weekly_all_pct) == (11, 1)
    assert [(m.name, m.pct) for m in p.models] == [("Fable", 0)]
    assert p.subscription_marker


def test_capture2_breakdown_24h():
    _env, p = parse_fixture("capture2-envelope-2026-10-03.json")
    w = {x.slug: x for x in p.windows}["24h"]
    assert (w.requests, w.sessions) == (2290, 175)
    assert (w.subagent_heavy_pct, w.long_context_pct, w.long_session_pct) == (67, 41, 30)
    assert w.top_subagents == (
        ("technical-design", 10),
        ("architect", 6),
        ("pm-agent", 2),
        ("coder", 1),
    )
    assert w.top_subagents_more == 0


def test_capture2_breakdown_7d_long_session_absent():
    _env, p = parse_fixture("capture2-envelope-2026-10-03.json")
    w = {x.slug: x for x in p.windows}["7d"]
    assert (w.requests, w.sessions) == (13401, 1433)
    assert (w.subagent_heavy_pct, w.long_context_pct) == (49, 29)
    assert w.long_session_pct is None
    assert len(w.top_subagents) == 8 and w.top_subagents_more == 1
    fields = dict(
        up.build_reading(
            run_epoch=1,
            classification=up.classify_read(
                up.ReadOutcome("exited", 0, None), fx("capture2-envelope-2026-10-03.json"), b""
            ),
            diagnostics=None,
            previous=None,
            settings=up.load_settings(up.Path("/nonexistent")),
        )
    )
    assert "long_session_pct_7d" not in fields and fields["long_session_pct_24h"] == "30"


def test_generic_third_window_parsed():
    _env, p = parse_fixture("envelope-third-window.json")
    assert [w.slug for w in p.windows] == ["24h", "7d", "30d"]


def test_window_cap_8():
    text = "Current session: 1% used\nCurrent week (all models): 1% used\n\n"
    text += "".join(
        "Last %dd · 1 requests · 1 sessions\n  5%% of your usage came from subagent-heavy sessions\n\n"
        % n
        for n in range(12)
    )
    p = up.parse_usage(text)
    assert len(p.windows) == up.MAX_WINDOWS


def test_ac1_shape_success_no_breakdown():
    _env, p = parse_fixture("ac1-real-shape-envelope.json")
    assert p.ok and (p.session_pct, p.weekly_all_pct) == (4, 29)
    assert [(m.name, m.pct) for m in p.models] == [("Fable", 6)]
    assert p.windows == ()


def test_empty_session_envelopes_failed():
    for name in ("empty-session-envelope-blank.json", "empty-session-envelope-legacy-text.json"):
        env, p = parse_fixture(name)
        assert not p.ok and p.reason == "empty_session"
        assert p.session_pct is None and p.weekly_all_pct is None and p.models == ()
        assert env.cost_usd == 0


def test_missing_weekly():
    assert parse_fixture("envelope-session-only.json")[1].reason == "missing_weekly"


def test_missing_session():
    assert parse_fixture("envelope-weekly-only.json")[1].reason == "missing_session"


def test_unparseable_nonempty_result():
    assert up.parse_usage("hello there\nno numbers").reason == "unparseable"
    assert up.parse_usage("Current week (Fable): 3% used").reason == "unparseable"


def test_decimal_percent_fails():
    assert not parse_fixture("envelope-decimal-percent.json")[1].ok


def test_over_100_accepted_unclamped():
    assert parse_fixture("envelope-over-100.json")[1].session_pct == 150


def test_last_match_wins():
    p = up.parse_usage(
        "Current session: 1% used\nCurrent session: 2% used\nCurrent week (all models): 3% used"
    )
    assert p.session_pct == 2


def test_ansi_crlf_stripped():
    env, p = parse_fixture("envelope-ansi-crlf.json")
    assert "\x1b" not in env.result_text and "\r" not in env.result_text
    assert p.ok and p.session_pct == 11
    assert p.session_resets == "Oct 3, 2:40am (UTC)"


def test_unicode_digits_rejected():
    p = up.parse_usage("Current session: ٤٢% used\nCurrent week (all models): 3% used")
    assert not p.ok


def test_marker_absent_still_success():
    p = up.parse_usage("Current session: 1% used\nCurrent week (all models): 3% used")
    assert p.ok and p.subscription_marker is False


def test_breakdown_line_garbled_isolated():
    _env, p = parse_fixture("envelope-breakdown-garbled.json")
    assert p.ok
    w = {x.slug: x for x in p.windows}["24h"]
    assert w.subagent_heavy_pct is None and w.top_subagents is None
    assert w.long_context_pct == 41


def test_breakdown_exception_isolated(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(up, "_parse_window_block", boom)
    _env, p = parse_fixture("capture2-envelope-2026-10-03.json")
    assert p.ok and p.windows == ()
    monkeypatch.setattr(up, "_extract_models", boom)
    assert up.parse_usage(parse_fixture("capture2-envelope-2026-10-03.json")[0].result_text).ok


def test_duplicate_window_absent():
    block = "Last 24h · 1 requests · 1 sessions\n  5% of your usage came from subagent-heavy sessions\n\n"
    p = up.parse_usage(
        "Current session: 1% used\nCurrent week (all models): 3% used\n\n" + block + block
    )
    assert p.ok and p.windows == ()


def test_top_list_bad_item_whole_line_absent():
    _env, p = parse_fixture("envelope-top-bad-item.json")
    w = {x.slug: x for x in p.windows}["24h"]
    assert w.top_subagents is None and w.top_subagents_more is None
    assert w.subagent_heavy_pct == 67


def test_no_model_line_success_absent():
    _env, p = parse_fixture("envelope-no-model.json")
    assert p.ok and p.models == ()


def test_two_models_parsed():
    _env, p = parse_fixture("envelope-two-models.json")
    assert [(m.name, m.pct) for m in p.models] == [("Fable", 0), ("Opus", 7)]


@pytest.mark.parametrize(
    "name",
    sorted(
        p.name
        for p in FIXTURES.glob("*.json")
        if p.name.startswith(("capture2", "d1-", "live-", "ac1-", "envelope-", "empty-"))
    ),
)
def test_per_model_set_never_contains_all_models(name):
    env = up.parse_envelope(fx(name))
    if not env.ok:
        return
    p = up.parse_usage(env.result_text)
    assert all(m.name != "all models" and "all models" not in m.name for m in p.models)


def test_per_model_all_models_line_excluded_inline():
    p = up.parse_usage(
        "Current session: 1% used\nCurrent week (all models): 95% used\nCurrent week (Fable): 2% used"
    )
    assert [m.name for m in p.models] == ["Fable"]


def test_model_name_raw_kept_control_stripped():
    p = up.parse_usage(
        "Current session: 1% used\nCurrent week (all models): 3% used\nCurrent week (Fa\x07ble é): 2% used"
    )
    assert p.models[0].name == "Fable é" and p.models[0].slug == "fable"


def test_window_length_never_parsed():
    p = up.parse_usage(
        "Current session: 1% used\nCurrent week (all models): 3% used\n\nLast 12h · 5 requests · 2 sessions\n"
    )
    assert p.windows[0].window_label == "12h" and p.windows[0].requests == 5


def test_classify_transport():
    c = up.classify_transport
    assert c(up.ReadOutcome("timeout", None, None)) == "timeout"
    assert c(up.ReadOutcome("spawn_failed", None, None)) == "spawn_failed"
    assert c(up.ReadOutcome("exited", 255, None)) == "ssh_failed"
    for rc in (0, 1, 2, 124, 127):
        assert c(up.ReadOutcome("exited", rc, None)) is None


def _stub_ssh(tmp_path, body):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "ssh"
    stub.write_text("#!/usr/bin/env bash\n" + body)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    return bindir


def test_read_usage_timeout_kills_process_group(tmp_path, monkeypatch):
    marker = tmp_path / "child.pid"
    bindir = _stub_ssh(tmp_path, "sleep 300 &\necho $! > %s\nwait\n" % marker)
    monkeypatch.setenv("PATH", "%s:%s" % (bindir, os.environ["PATH"]))
    monkeypatch.setattr(up, "KILL_GRACE_SECONDS", 2)
    started = time.time()
    out = up.read_usage(
        key_path=tmp_path / "k", timeout_s=1, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e"
    )
    assert out.kind == "timeout" and out.rc is None
    assert time.time() - started < 20
    pid = int(marker.read_text())
    time.sleep(0.3)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
        # a zombie reaped by init disappears; if it lingers it is not running
        os.waitpid(pid, os.WNOHANG)
        raise ProcessLookupError


def test_read_usage_spawn_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    out = up.read_usage(
        key_path=tmp_path / "k", timeout_s=1, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e"
    )
    assert out.kind == "spawn_failed"


def test_read_usage_argv_ends_at_host(tmp_path, monkeypatch):
    seen = []

    class P:
        pid = 1

        def wait(self, timeout=None):
            return 0

    def popen(argv, **kw):
        seen.append((list(argv), kw))
        return P()

    monkeypatch.setattr(up.subprocess, "Popen", popen)
    up.read_usage(
        key_path=tmp_path / "k", timeout_s=1, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e"
    )
    argv, kw = seen[0]
    assert argv[-1] == "127.0.0.1" and argv[:2] == ["ssh", "-n"]
    assert "env" not in kw and kw["start_new_session"] is True


def test_read_usage_inherits_env_unchanged(tmp_path, monkeypatch):
    bindir = _stub_ssh(tmp_path, 'printf "%s" "${HOS_TEST_SENTINEL:-unset}"\n')
    monkeypatch.setenv("PATH", "%s:%s" % (bindir, os.environ["PATH"]))
    monkeypatch.setenv("HOS_TEST_SENTINEL", "kept")
    out = up.read_usage(
        key_path=tmp_path / "k",
        timeout_s=10,
        stdout_path=tmp_path / "o",
        stderr_path=tmp_path / "e",
    )
    assert out.kind == "exited" and out.rc == 0
    assert (tmp_path / "o").read_text() == "kept"
