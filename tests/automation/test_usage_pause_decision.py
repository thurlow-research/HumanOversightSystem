"""#1944 S1: the decision rule, section 3.6 R1-R13."""

import pytest

from tests.automation.usage_support import fx, reading, settings, up

NOW = 1_000_000


def ev(r, s=None, now=NOW, artifacts=True):
    return up.evaluate_cycle(r, s or settings(), float(now), poller_artifacts_present=artifacts)


def test_session_90_pauses():
    d = ev(reading(session_pct=90, weekly_all_pct=10))
    assert (d.decision, d.klass, d.reason) == ("pause", "limit", "session 90% >= 90")


def test_weekly_90_pauses():
    assert ev(reading(session_pct=10, weekly_all_pct=90)).decision == "pause"


def test_89_89_runs():
    d = ev(reading(session_pct=89, weekly_all_pct=89))
    assert d.decision == "run" and d.klass == "ok" and not d.unchecked


def test_exact_90_is_reached():
    assert ev(reading(session_pct=89, weekly_all_pct=90)).decision == "pause"


def test_weekly_only_reason_names_weekly_all():
    assert ev(reading(session_pct=10, weekly_all_pct=90)).reason == "weekly_all 90% >= 90"


def test_model_90_pauses_reason_exact():
    d = ev(reading(weekly_model_fable_pct=90))
    assert d.reason == "weekly_model:Fable 90% >= 90"


def test_model_89_runs():
    assert ev(reading(weekly_model_fable_pct=89)).decision == "run"


def test_either_of_two_models_pauses():
    r = reading(weekly_model_opus_name="Opus", weekly_model_opus_pct=95)
    assert ev(r).reason == "weekly_model:Opus 95% >= 90"
    r = reading(weekly_model_opus_name="Opus", weekly_model_opus_pct=5, weekly_model_fable_pct=91)
    assert ev(r).reason == "weekly_model:Fable 91% >= 90"


def test_absent_model_uses_two_limits():
    d = ev(reading(weekly_model_fable_name=None, weekly_model_fable_pct=None))
    assert d.decision == "run" and "weekly_model" not in d.reason


def test_reason_order_and_join():
    r = reading(
        session_pct=95,
        weekly_all_pct=96,
        weekly_model_zed_name="Zed",
        weekly_model_zed_pct=97,
        weekly_model_fable_pct=98,
    )
    assert (
        ev(r).reason
        == "session 95% >= 90; weekly_all 96% >= 90; weekly_model:Fable 98% >= 90; weekly_model:Zed 97% >= 90"
    )
    many = {}
    for i in range(30):
        many["weekly_model_m%02d_name" % i] = "Model%02d" % i
        many["weekly_model_m%02d_pct" % i] = 99
    assert len(ev(reading(**many)).reason) <= up.REASON_CAP_CHARS


def test_non_ascii_model_name_folded_in_verdict_only():
    d = ev(reading(weekly_model_fable_name="Faéble", weekly_model_fable_pct=95))
    assert "é" in d.reason  # the decision keeps the raw name
    assert up.ascii_fold(d.reason) == "weekly_model:Fa?ble 95% >= 90"


def test_resume_all_below():
    assert ev(reading(session_pct=90)).decision == "pause"
    assert ev(reading(session_pct=89)).decision == "run"


def test_threshold_80():
    s = settings(session_threshold=80)
    assert ev(reading(session_pct=80), s).decision == "pause"
    assert ev(reading(session_pct=79), s).decision == "run"


def test_model_threshold_independent():
    s = settings(weekly_model_threshold=5)
    d = ev(reading(session_pct=50, weekly_all_pct=50, weekly_model_fable_pct=5), s)
    assert d.reason == "weekly_model:Fable 5% >= 5"


def test_stale_boundary_900_fresh_901_stale():
    assert ev(reading(now=NOW - 900)).klass == "ok"
    d = ev(reading(now=NOW - 901))
    assert (d.decision, d.klass, d.reason) == ("pause", "reading_unusable", "reading_stale")


def test_future_boundary():
    assert ev(reading(now=NOW + 120)).klass == "ok"
    assert ev(reading(now=NOW + 121)).reason == "reading_future"


def test_missing_vs_poller_not_installed():
    miss = up.ReadingRead("missing", {})
    assert ev(miss, artifacts=False).reason == "poller_not_installed"
    assert ev(miss, artifacts=True).reason == "reading_missing"


@pytest.mark.parametrize(
    "state,reason",
    [
        ("truncated", "reading_truncated"),
        ("schema_unknown", "schema_unknown"),
        ("unreadable", "reading_unreadable"),
    ],
)
def test_each_unusable_reason_distinct(state, reason):
    assert ev(up.ReadingRead(state, {})).reason == reason
    assert ev(reading(kind="other")).reason == "reading_unreadable"
    assert ev(reading(run_epoch="abc")).reason == "reading_unreadable"
    assert ev(reading(outcome="weird")).reason == "reading_unreadable"


def test_failure_closed_pauses():
    d = ev(reading(outcome="failure", reason="timeout"))
    assert (d.decision, d.klass, d.reason) == ("pause", "read_failed", "read_failed:timeout")
    assert ev(reading(outcome="failure", reason="nonsense")).reason == "read_failed:unknown"
    assert ev(reading(outcome="crashed", reason="crashed")).reason == "read_failed:crashed"


def test_failure_open_runs_unchecked():
    s = settings(fail_mode="open")
    d = ev(reading(outcome="failure", reason="timeout"), s)
    assert (d.decision, d.klass, d.unchecked) == ("run", "failopen", True)
    assert ev(up.ReadingRead("missing", {}), s).klass == "failopen"
    assert ev(reading(), s).unchecked is False


def test_invalid_settings_pause_even_open():
    bad = up.SettingsResult(
        dict(up.DEFAULTS, fail_mode="open"), "invalid:history_days", "history_days", "0"
    )
    d = ev(reading(), bad)
    assert (d.decision, d.klass, d.reason) == (
        "pause",
        "settings_invalid",
        "settings_invalid:history_days",
    )


def test_limit_pause_regardless_of_fail_mode():
    assert ev(reading(session_pct=95), settings(fail_mode="open")).decision == "pause"


@pytest.mark.parametrize(
    "overrides",
    [
        {"session_pct": None},
        {"weekly_all_pct": "x"},
        {"weekly_model_fable_pct": "x"},
    ],
)
def test_success_missing_pct_is_unreadable(overrides):
    assert ev(reading(**overrides)).reason == "reading_unreadable"


def test_model_pct_without_name_unreadable():
    assert ev(reading(weekly_model_fable_name=None)).reason == "reading_unreadable"


def test_check_ignores_poll_view():
    r = reading(poll_pause_condition=1, poll_pause_reason="session 99% >= 1", poll_fail_mode="open")
    assert ev(r).klass == "ok"
    assert not any(k.startswith("poll_") for k in up.CHECK_READ_KEYS)


def test_evaluate_never_raises():
    class Bad:
        state = "ok"
        fields = None

    d = ev(Bad())
    assert d.decision == "pause"


@pytest.mark.parametrize(
    "name",
    [
        "capture2-envelope-2026-10-03.json",
        "d1-envelope-derived.json",
        "ac1-real-shape-envelope.json",
        "envelope-two-models.json",
        "live-full-envelope-2026-10-03.json",
        "envelope-over-100.json",
    ],
)
def test_poll_view_equals_cycle_rule(name):
    for sett in (
        settings(),
        settings(session_threshold=5),
        settings(weekly_threshold=1),
        settings(fail_mode="open"),
    ):
        cls = up.classify_read(up.ReadOutcome("exited", 0, None), fx(name), b"")
        fields = up.build_reading(
            run_epoch=NOW, classification=cls, diagnostics=None, previous=None, settings=sett
        )
        d = dict(fields)
        expected = up.evaluate_cycle(
            up.ReadingRead("ok", {k: v for k, v in d.items() if k != "schema"}),
            sett,
            float(NOW),
            poller_artifacts_present=True,
        )
        assert d["poll_pause_condition"] == ("1" if expected.decision == "pause" else "0")
        assert d["poll_pause_reason"] == expected.reason
