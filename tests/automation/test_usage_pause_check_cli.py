"""#1944 S2: `usage_pause.py check`, the verdict line bin/hos-cron's gate consumes (TD 4.3, 9.2)."""

import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.automation.usage_support import LIB, ROOT, up

HOS_CRON = ROOT / "bin" / "hos-cron"


def bash_ere() -> "re.Pattern[str]":
    """The verdict ERE, extracted from bin/hos-cron at test time so the two cannot drift."""
    match = re.search(r"^_UP_VERDICT_RE='(.*)'$", HOS_CRON.read_text(), re.M)
    assert match, "the gate must define _UP_VERDICT_RE on one line"
    return re.compile(match.group(1), re.ASCII)


def write_reading(state: Path, now=None, **overrides) -> Path:
    fields = {
        "kind": "reading",
        "run_epoch": int(time.time()) if now is None else now,
        "outcome": "success",
        "session_pct": 6,
        "weekly_all_pct": 48,
        "weekly_model_fable_name": "Fable",
        "weekly_model_fable_pct": 3,
    }
    fields.update(overrides)
    path = state / "usage-pause" / "reading"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["schema=1"] + ["%s=%s" % kv for kv in fields.items() if kv[1] is not None] + ["end=1"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def world(tmp_path, monkeypatch):
    """HOME, state dir and settings path isolated under tmp_path."""
    home = tmp_path / "home"
    (home / ".config" / "hos").mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HOS_USAGE_PAUSE_CONF", str(home / ".config" / "hos" / "usage-pause.conf"))
    monkeypatch.setenv("HOS_USAGE_KEY_PATH", str(home / ".ssh" / "hos_loopback"))

    class World:
        pass

    w = World()
    w.home, w.state = home, state
    w.conf = home / ".config" / "hos" / "usage-pause.conf"
    return w


def verdict(w) -> str:
    return up.gate_verdict(str(w.state), time.time())


def fields_of(line: str) -> dict:
    match = bash_ere().fullmatch(line)
    assert match, line
    names = ("decision", "class", "fail_mode", "settings", "session", "weekly", "age", "reason")
    return dict(zip(names, match.groups()))


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_verdict_line_matches_bash_ere(world):
    """Every class, plus a 200-char reason, matches the ERE the launcher carries."""
    seen = set()

    write_reading(world.state)
    seen.add(fields_of(verdict(world))["class"])  # ok

    write_reading(world.state, session_pct=95)
    seen.add(fields_of(verdict(world))["class"])  # limit

    write_reading(world.state, outcome="failure", reason="timeout")
    seen.add(fields_of(verdict(world))["class"])  # read_failed

    write_reading(world.state, now=1)
    seen.add(fields_of(verdict(world))["class"])  # reading_unusable (stale)

    world.conf.write_text("fail_mode=open\n")
    seen.add(fields_of(verdict(world))["class"])  # failopen (stale, open)

    world.conf.write_text("nonsense line\n")
    seen.add(fields_of(verdict(world))["class"])  # settings_invalid
    assert seen == {
        "ok",
        "limit",
        "read_failed",
        "reading_unusable",
        "failopen",
        "settings_invalid",
    }

    # a 200-char reason: three 64-char model names over the limit
    world.conf.unlink()
    models = {}
    for slug in ("a", "b", "c", "d"):
        models["weekly_model_%s_name" % slug] = slug.upper() * 64
        models["weekly_model_%s_pct" % slug] = 99
    write_reading(world.state, **models)
    line = verdict(world)
    parts = fields_of(line)
    assert len(parts["reason"]) == 200
    assert line.startswith("USAGE_PAUSE v=%d " % up.VERDICT_VERSION)


def test_ok_verdict_exact_shape(world):
    write_reading(world.state, now=int(time.time()) - 42)
    parts = fields_of(verdict(world))
    assert (parts["decision"], parts["class"], parts["fail_mode"], parts["settings"]) == (
        "run",
        "ok",
        "closed",
        "defaults",
    )
    assert (parts["session"], parts["weekly"]) == ("6", "48")
    assert parts["reason"].startswith(
        "session 6% < 90, weekly_all 48% < 90, weekly_model:Fable 3% < 90"
    )


def test_unknown_values_print_dash(world):
    world.conf.write_text("bogus=1\n")
    parts = fields_of(verdict(world))
    assert (parts["session"], parts["weekly"], parts["age"]) == ("-", "-", "-")
    assert parts["settings"] == "invalid:bogus" and parts["fail_mode"] == "closed"
    assert parts["reason"] == "settings_invalid:bogus"


def test_check_writes_nothing(world):
    """A read-only state tree stays byte-identical; the check never writes (A2-2)."""
    reading = write_reading(world.state, session_pct=95)
    before = tree_hash(world.state)
    modes = []
    for path in [world.state, *world.state.rglob("*")]:
        modes.append((path, path.stat().st_mode))
        path.chmod(0o500 if path.is_dir() else 0o400)
    try:
        proc = subprocess.run(
            [sys.executable, str(LIB), "check", "--state-dir", str(world.state)],
            capture_output=True,
            text=True,
            check=False,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )
    finally:
        for path, mode in reversed(modes):
            path.chmod(mode)
    assert proc.returncode == 0, proc.stderr
    assert "decision=pause" in proc.stdout
    assert tree_hash(world.state) == before
    assert reading.exists()


def test_check_ignores_poll_view(world):
    write_reading(world.state, session_pct=95, poll_pause_condition=0, poll_pause_reason="x")
    assert fields_of(verdict(world))["decision"] == "pause"
    write_reading(
        world.state,
        poll_pause_condition=1,
        poll_pause_reason="session 99% >= 90",
        poll_settings_status="invalid:x",
        poll_session_threshold=1,
    )
    parts = fields_of(verdict(world))
    assert (parts["decision"], parts["settings"]) == ("run", "defaults")


def test_check_uses_current_conf_not_poll_view(world):
    """AC-23: the gate applies today's conf to the reading, whatever the poller recorded."""
    write_reading(
        world.state,
        session_pct=85,
        poll_settings_status="defaults",
        poll_session_threshold=90,
        poll_pause_condition=0,
    )
    assert fields_of(verdict(world))["decision"] == "run"
    world.conf.write_text("session_threshold=80\n")
    parts = fields_of(verdict(world))
    assert parts["decision"] == "pause" and parts["reason"] == "session 85% >= 80"
    world.conf.write_text("session_threshold=86\n")
    assert fields_of(verdict(world))["decision"] == "run"


def test_check_crash_exit_70_no_stdout(world, monkeypatch, capsys):
    def boom(*_a, **_k):
        raise RuntimeError("boom\nsecond line")

    monkeypatch.setattr(up, "read_reading", boom)
    rc = up.main(["check", "--state-dir", str(world.state)])
    captured = capsys.readouterr()
    assert rc == 70
    assert captured.out == ""
    assert captured.err.count("\n") == 1 and "RuntimeError" in captured.err


def test_check_usage_error_is_nonzero_no_stdout(world):
    proc = subprocess.run(
        [sys.executable, str(LIB), "check"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 64 and proc.stdout == ""


def test_reason_ascii_only_in_verdict(world):
    """TD-O-14: a non-ASCII model name is folded to '?' in the verdict; the file keeps it."""
    reading = write_reading(
        world.state, weekly_model_fable_name="Fáble·Ünï", weekly_model_fable_pct=95
    )
    line = verdict(world)
    parts = fields_of(line)
    assert line.isascii()
    assert parts["reason"] == "weekly_model:F?ble??n? 95% >= 90"
    assert "Fáble" in reading.read_text(encoding="utf-8")


def test_missing_reading_reasons_and_fail_modes(world):
    parts = fields_of(verdict(world))
    assert (parts["class"], parts["reason"]) == ("reading_unusable", "poller_not_installed")
    world.conf.write_text("session_threshold=90\n")
    parts = fields_of(verdict(world))
    assert parts["reason"] == "reading_missing" and parts["decision"] == "pause"
    world.conf.write_text("fail_mode=open\n")
    parts = fields_of(verdict(world))
    assert (parts["decision"], parts["class"], parts["reason"]) == (
        "run",
        "failopen",
        "reading_missing",
    )


def test_key_alone_counts_as_poller_artifact(world):
    key = world.home / ".ssh" / "hos_loopback"
    key.parent.mkdir()
    key.write_text("k")
    assert fields_of(verdict(world))["reason"] == "reading_missing"


def test_comparison_is_greater_or_equal_for_every_limit(world):
    for fields, limit in (
        ({"session_pct": 90}, "session 90% >= 90"),
        ({"weekly_all_pct": 90}, "weekly_all 90% >= 90"),
        ({"weekly_model_fable_pct": 90}, "weekly_model:Fable 90% >= 90"),
    ):
        write_reading(world.state, **fields)
        assert fields_of(verdict(world))["reason"] == limit
    write_reading(world.state, session_pct=89, weekly_all_pct=89, weekly_model_fable_pct=89)
    assert fields_of(verdict(world))["decision"] == "run"


def test_check_crash_stderr_is_ascii_and_capped(world, monkeypatch, capsys):
    def boom(*_a, **_k):
        raise RuntimeError("caf\u00e9 " + "x" * 500)

    monkeypatch.setattr(up, "read_reading", boom)
    assert up.main(["check", "--state-dir", str(world.state)]) == 70
    err = capsys.readouterr().err.rstrip("\n")
    assert err.isascii() and len(err) <= 200 and "caf?" in err
