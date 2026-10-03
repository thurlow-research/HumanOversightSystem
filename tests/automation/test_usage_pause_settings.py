"""#1944 S1: settings parsing (ADR-1944 A2-10)."""

import pytest

from tests.automation.usage_support import up


def load(tmp_path, text, raw=False):
    p = tmp_path / "usage-pause.conf"
    if raw:
        p.write_bytes(text)
    else:
        p.write_text(text, encoding="utf-8")
    return up.load_settings(p)


def test_missing_file_defaults(tmp_path):
    r = up.load_settings(tmp_path / "absent.conf")
    assert r.status == "defaults"
    v = r.values
    assert (v["session_threshold"], v["weekly_threshold"], v["weekly_model_threshold"]) == (
        90,
        90,
        90,
    )
    assert v["fail_mode"] == "closed"
    assert (v["poll_interval_seconds"], v["staleness_seconds"], v["read_timeout_seconds"]) == (
        300,
        900,
        60,
    )
    assert (v["history_days"], v["history_max_mb"], v["claude_bin"]) == (90, 100, None)


@pytest.mark.parametrize(
    "line",
    [
        "session_threshold=1",
        "session_threshold=100",
        "weekly_threshold=1",
        "weekly_threshold=100",
        "weekly_model_threshold=1",
        "weekly_model_threshold=100",
        "fail_mode=open",
        "fail_mode=closed",
        "poll_interval_seconds=60\nread_timeout_seconds=5\nstaleness_seconds=100",
        "poll_interval_seconds=3600\nstaleness_seconds=7200",
        "staleness_seconds=7200",
        "read_timeout_seconds=5",
        "read_timeout_seconds=270",
        "history_days=1",
        "history_days=3650",
        "history_max_mb=1",
        "history_max_mb=10240",
        "claude_bin=/usr/local/bin/claude",
    ],
)
def test_each_key_valid_bounds(tmp_path, line):
    r = load(tmp_path, line + "\n")
    assert r.status == "valid", (line, r.status)


@pytest.mark.parametrize(
    "line,key",
    [
        ("session_threshold=0", "session_threshold"),
        ("session_threshold=101", "session_threshold"),
        ("weekly_threshold=8O", "weekly_threshold"),
        ("weekly_model_threshold=090", "weekly_model_threshold"),
        ("session_threshold=+90", "session_threshold"),
        ("session_threshold=90 # c", "session_threshold"),
        ("session_threshold=", "session_threshold"),
        ("session_threshold=٩٠", "session_threshold"),
        ("fail_mode=Closed", "fail_mode"),
        ("poll_interval_seconds=90", "poll_interval_seconds"),
        ("poll_interval_seconds=3660", "poll_interval_seconds"),
        ("staleness_seconds=360", "staleness_seconds"),
        ("staleness_seconds=7201", "staleness_seconds"),
        ("read_timeout_seconds=4", "read_timeout_seconds"),
        ("read_timeout_seconds=271", "read_timeout_seconds"),
        ("history_days=0", "history_days"),
        ("history_days=3651", "history_days"),
        ("history_max_mb=0", "history_max_mb"),
        ("history_max_mb=10241", "history_max_mb"),
        ("claude_bin=claude", "claude_bin"),
        ("claude_bin=/usr/../bin/claude", "claude_bin"),
        ("claude_bin=/usr/./bin/claude", "claude_bin"),
        ("claude_bin=/usr/bin/", "claude_bin"),
    ],
)
def test_each_key_invalid(tmp_path, line, key):
    r = load(tmp_path, line + "\n")
    assert r.status == "invalid:" + key
    assert r.invalid_key == key
    assert r.values["session_threshold"] == 90  # defaults on invalid


def test_failopen_issue_after_now_unknown_key(tmp_path):
    assert load(tmp_path, "failopen_issue_after=3\n").status == "invalid:failopen_issue_after"


def test_unknown_key_invalid(tmp_path):
    assert load(tmp_path, "bogus_key=1\n").status == "invalid:bogus_key"


def test_duplicate_key_invalid(tmp_path):
    assert load(tmp_path, "fail_mode=open\nfail_mode=closed\n").status == "invalid:fail_mode"


def test_malformed_line_invalid_line_n(tmp_path):
    assert load(tmp_path, "# c\n\nnot a setting\n").status == "invalid:line_3"
    assert load(tmp_path, "Session=1\n").status == "invalid:line_1"


def test_comments_blank_lines_and_crlf_ok(tmp_path):
    r = load(tmp_path, b"# comment\r\n\r\nfail_mode=open\r\n", raw=True)
    assert r.status == "valid" and r.values["fail_mode"] == "open"


def test_unreadable_file(tmp_path):
    p = tmp_path / "c.conf"
    p.write_text("fail_mode=open\n")
    p.chmod(0)
    r = up.load_settings(p)
    p.chmod(0o600)
    if r.status == "defaults":  # running as root defeats chmod 0
        pytest.skip("permissions not enforced")
    assert r.status == "invalid:file_unreadable"


def test_directory_path(tmp_path):
    assert up.load_settings(tmp_path).status == "invalid:file_unreadable"


def test_non_utf8_file(tmp_path):
    assert load(tmp_path, b"fail_mode=\xff\n", raw=True).status == "invalid:file_unreadable"


def test_oversize_file(tmp_path):
    assert (
        load(tmp_path, b"#" * (up.SETTINGS_FILE_CAP_BYTES + 1), raw=True).status
        == "invalid:file_unreadable"
    )


def test_first_violation_reported(tmp_path):
    r = load(tmp_path, "weekly_threshold=0\nsession_threshold=0\n")
    assert r.invalid_key == "weekly_threshold"
    cross = load(tmp_path, "staleness_seconds=100\nread_timeout_seconds=271\n")
    assert cross.invalid_key == "read_timeout_seconds"  # cross-field: timeout first


def test_never_raises(tmp_path, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("x")

    monkeypatch.setattr(up, "_parse_settings_text", boom)
    p = tmp_path / "c"
    p.write_text("a=b\n")
    assert up.load_settings(p).status == "invalid:file_unreadable"


def test_conf_path_never_from_hos_config_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("HOS_USAGE_PAUSE_CONF", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("HOS_CONFIG_DIR", "/elsewhere")
    assert up.default_conf_path() == tmp_path / ".config" / "hos" / "usage-pause.conf"
