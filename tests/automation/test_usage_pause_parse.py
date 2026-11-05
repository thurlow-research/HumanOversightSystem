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


HUGE = "9" * 5000


def test_overlong_percent_is_unparseable_not_a_crash():
    text = "Current session: %s%% used\nCurrent week (all models): 3%% used" % HUGE
    assert up.parse_usage(text).reason == "missing_session"
    text = "Current session: 1%% used\nCurrent week (all models): %s%% used" % HUGE
    assert up.parse_usage(text).reason == "missing_weekly"
    both = "Current session: %s%% used\nCurrent week (all models): %s%% used" % (HUGE, HUGE)
    assert up.parse_usage(both).reason == "unparseable"
    assert up.parse_usage(
        "Current session: 1000% used\nCurrent week (all models): 1% used"
    ).reason == ("missing_session")


def test_overlong_counters_and_model_percent_never_raise():
    base = "Current session: 1% used\nCurrent week (all models): 3% used\n"
    p = up.parse_usage(
        base
        + "Current week (Fable): %s%% used\n\nLast 24h · %s requests · 1 sessions\n" % (HUGE, HUGE)
    )
    assert p.ok and p.models == () and p.windows == ()
    top = base + "\nLast 24h · 1 requests · 1 sessions\n  Top subagents: a %s%%, +%s more\n" % (
        HUGE,
        HUGE,
    )
    assert up.parse_usage(top).windows[0].top_subagents is None
    big_more = (
        base + "\nLast 24h · 1 requests · 1 sessions\n  Top subagents: a 5%, +" + HUGE + " more\n"
    )
    assert up.parse_usage(big_more).windows[0].top_subagents is None


def test_kill_group_second_timeout_returns_without_raising(monkeypatch):
    calls = []

    class Stuck:
        pid = 123456789

        def wait(self, timeout=None):
            calls.append(timeout)
            raise up.subprocess.TimeoutExpired("x", timeout)

    monkeypatch.setattr(up.os, "killpg", lambda *_a: None)
    assert up._kill_group(Stuck()) is None
    assert calls == [up.KILL_GRACE_SECONDS, up.KILL_GRACE_SECONDS]


def test_kill_group_permission_error_recorded_in_detail(monkeypatch):
    class Stuck:
        pid = 1

        def wait(self, timeout=None):
            return 0

    def refuse(*_a):
        raise PermissionError("nope")

    monkeypatch.setattr(up.os, "killpg", refuse)
    detail = up._kill_group(Stuck())
    assert detail and "refused" in detail and "nope" in detail


def test_read_usage_timeout_carries_kill_problem(tmp_path, monkeypatch):
    class P:
        pid = 1

        def wait(self, timeout=None):
            raise up.subprocess.TimeoutExpired("x", timeout)

    monkeypatch.setattr(up.subprocess, "Popen", lambda *a, **k: P())
    monkeypatch.setattr(up, "_kill_group", lambda _p: "kill SIGTERM refused: x")
    out = up.read_usage(
        key_path=tmp_path / "k", timeout_s=1, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e"
    )
    assert out.kind == "timeout" and out.detail == "kill SIGTERM refused: x"
    cls = up.classify_read(out, b"", b"")
    assert cls.reason == "timeout"
    assert cls.detail == "local_timeout; kill SIGTERM refused: x"


def test_local_timeout_detail_is_distinct_from_remote():
    local = up.classify_read(up.ReadOutcome("timeout", None, None), b"", b"")
    assert (local.reason, local.detail, local.remote_exit) == ("timeout", "local_timeout", None)
    remote = up.classify_read(up.ReadOutcome("exited", 124, None), b"", b"")
    assert (remote.reason, remote.detail, remote.remote_exit) == (
        "timeout",
        "remote_timeout rc=124",
        124,
    )


def test_remote_cmd_template_rendering():
    assert up.remote_cmd("/c/claude", "/t/timeout", 60) == (
        "/t/timeout -k 5 50 /c/claude -p /usage --output-format json"
    )
    assert "-k 5 20 " in up.remote_cmd("/c/claude", "/t/timeout", 30)


def test_timeout_side_remote_and_local():
    local = up.classify_read(up.ReadOutcome("timeout", None, None), b"", b"")
    remote = up.classify_read(up.ReadOutcome("exited", 137, None), b"", b"")
    ok = up.classify_read(
        up.ReadOutcome("exited", 124, None), fx("capture2-envelope-2026-10-03.json"), b""
    )
    assert (local.timeout_side, remote.timeout_side, ok.timeout_side) == ("local", "remote", None)
    settings = up.load_settings(up.Path("/nonexistent"))

    def keys(cls):
        return dict(
            up.build_reading(
                run_epoch=1, classification=cls, diagnostics=None, previous=None, settings=settings
            )
        )

    assert keys(local)["timeout_side"] == "local" and "remote_exit" not in keys(local)
    assert keys(remote)["timeout_side"] == "remote" and keys(remote)["remote_exit"] == "137"
    assert "timeout_side" not in keys(ok)
    other = up.classify_read(up.ReadOutcome("exited", 255, None), b"", b"x")
    assert "timeout_side" not in keys(other)


# ── per-model reset text (carried-forward bug: _resets read the model NAME) ──


def _model_reset_from_text(text, name):
    """The reset text on `Current week (<name>): N% used · resets <text>`, read independently."""
    import re

    pattern = r"Current week \(" + re.escape(name) + r"\): [0-9]+% used · resets (.*)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def _fixtures_with_models():
    found = []
    for path in sorted(FIXTURES.glob("*.json")):
        env = up.parse_envelope(path.read_bytes())
        if not env.ok:
            continue
        parsed = up.parse_usage(env.result_text)
        if parsed.ok and parsed.models:
            found.append(path.name)
    return found


def test_fixtures_with_models_exist():
    assert len(_fixtures_with_models()) >= 5


@pytest.mark.parametrize("name", _fixtures_with_models())
def test_model_resets_is_the_reset_text_for_every_fixture(name):
    env, parsed = parse_fixture(name)
    for model in parsed.models:
        expected = _model_reset_from_text(env.result_text, model.name)
        assert model.resets == expected, (name, model)
        assert model.resets != model.name, (name, model)


@pytest.mark.parametrize("name", _fixtures_with_models())
def test_reading_weekly_model_resets_is_the_reset_text_for_every_fixture(name):
    env, parsed = parse_fixture(name)
    cls = up.classify_read(up.ReadOutcome("exited", 0, None), fx(name), b"")
    fields = dict(
        up.build_reading(
            run_epoch=1_000_000,
            classification=cls,
            diagnostics=None,
            previous=None,
            settings=up.SettingsResult(dict(up.DEFAULTS), "defaults", None, None),
        )
    )
    for model in parsed.models:
        key = "weekly_model_%s_resets" % model.slug
        assert fields.get(key) == _model_reset_from_text(env.result_text, model.name), (name, key)
        assert fields[key] != model.name


def test_model_resets_pinned_values():
    _env, d1 = parse_fixture("d1-envelope-derived.json")
    assert [(m.name, m.resets) for m in d1.models] == [("Fable", "Oct 3, 12am (UTC)")]
    _env, two = parse_fixture("envelope-two-models.json")
    assert {m.name: m.resets for m in two.models}["Opus"] == "Oct 10, 12am (UTC)"


def test_model_line_without_resets_has_none():
    text = "Current session: 5% used\nCurrent week (all models): 6% used\nCurrent week (Fable): 7% used\n"
    parsed = up.parse_usage(text)
    assert parsed.ok and [(m.name, m.resets) for m in parsed.models] == [("Fable", None)]


# ───────────── #2229: an absent session line means no 5-hour limit ─────────────

NO_SESSION_TEXT = (
    "You are currently using your subscription to power your Claude Code usage\n\n"
    "Current week (all models): 7% used · resets Nov 6, 11:59pm (UTC)\n"
    "Current week (Fable): 0% used · resets Nov 7, 12am (UTC)\n\n"
    "What's contributing to your limits usage?\n"
)


def test_no_session_line_parses_as_no_session_limit():
    p = up.parse_usage(NO_SESSION_TEXT)
    assert p.ok and p.reason is None
    assert p.session_limit == "none" and p.session_pct is None
    assert (p.weekly_all_pct, [(m.name, m.pct) for m in p.models]) == (7, [("Fable", 0)])


def test_session_line_present_keeps_session_limit_present():
    p = up.parse_usage("Current session: 1% used\nCurrent week (all models): 3% used")
    assert p.ok and p.session_limit == "present" and p.session_pct == 1


def test_weekly_only_fixture_is_now_a_valid_no_session_reading():
    p = parse_fixture("envelope-weekly-only.json")[1]
    assert p.ok and p.session_limit == "none"
    assert len(p.windows) == 2  # window blocks do not trip the unrecognised-line check


@pytest.mark.parametrize(
    "line",
    [
        "Current session (5h): 12% used",
        "Current 5-hour window: 12% used",
        "Current session: unlimited",
        "current session: 12 percent",
    ],
)
def test_reworded_session_line_is_missing_session(line):
    p = up.parse_usage(line + "\nCurrent week (all models): 3% used")
    assert not p.ok and p.reason == "missing_session"


def test_no_weekly_line_still_fails():
    assert up.parse_usage("Current week (Fable): 3% used").reason == "unparseable"
    assert up.parse_usage("Current session: 3% used").reason == "missing_weekly"


def test_no_session_success_fields_write_session_limit_none_only():
    fields = dict(up._success_fields(up.parse_usage(NO_SESSION_TEXT)))
    assert fields["session_limit"] == "none"
    assert "session_pct" not in fields and "session_resets" not in fields
    assert fields["weekly_all_pct"] == "7"


@pytest.mark.parametrize(
    "line",
    [
        "Current session: 12 % used",
        "5-hour limit: 12%",
        "Current 5h window: 12 percent",
        "Limit: 5 hours, 12 used",
        "Limit: five hours, 12 used",
        "Limit: 5 hrs, 12 used",
        "Usage limit reached, resets 5pm",
        "Session usage: 40% used",
        # Deliberate: a tips-style line with "session" and "%" is not a limit line, but the guard
        # is deny-by-default, so it fails closed. A false positive is the safe direction.
        "Tip: end your session early to save up to 10% of your limit",
    ],
)
def test_unrecognised_limit_like_line_fails_closed(line):
    p = up.parse_usage(NO_SESSION_TEXT + line + "\n")
    assert not p.ok and p.reason == "missing_session"


def test_prose_and_window_blocks_do_not_trip_the_guard():
    text = NO_SESSION_TEXT + "Some tips prose with no limit words.\n"
    assert up.parse_usage(text).ok


def test_limit_word_without_digit_is_prose_not_a_limit_line():
    assert up.parse_usage(NO_SESSION_TEXT + "Learn more about your limits\n").ok
    # Accepted residual: a reworded limit line with no digit, no percent and no session/5-hour
    # token cannot be told from prose, so it fails open.
    assert up.parse_usage(NO_SESSION_TEXT + "Rate limit hit\n").ok


def test_five_hour_per_model_week_line_is_enforced_as_weekly_model():
    # Deliberate and conservative: _MODEL_RE accepts this as a per-model weekly line, so it is
    # enforced against the weekly model threshold (an over-threshold value still pauses).
    text = "Current week (all models): 7% used\nCurrent week (5-hour): 95% used\n"
    p = up.parse_usage(text)
    assert p.ok and [(m.name, m.pct) for m in p.models] == [("5-hour", 95)]


def test_pathological_top_subagents_line_is_linear():
    # CWE-1333: the old lazy `(.+?)\s*$` was quadratic on a long interior whitespace run.
    line = "Top subagents: a" + " " * 65_000 + "b\n"
    start = time.monotonic()
    assert up.parse_usage(NO_SESSION_TEXT + line).ok
    assert time.monotonic() - start < 2


def test_top_subagents_capture_unchanged_by_linear_pattern():
    m = up._TOP_RE.match("  Top subagents: coder 13%, architect 3%, +1 more   ")
    assert m is not None and m.group(1) == "coder 13%, architect 3%, +1 more"
    assert up._TOP_RE.match("Top subagents:  ") is None
