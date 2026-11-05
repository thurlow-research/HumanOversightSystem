"""#2229 S2: `usage_pause.py show-last-raw`, the read-only last-raw diagnostic."""

import json
import os
import subprocess
import sys

from tests.automation.usage_support import LIB, fx, up

HEADER = "# hos-usage-poll last-raw run_epoch=1760000000 read=%s rc=%s stream=%s bytes=%d\n"
WEEKLY = "Current week (all models): 12% used · resets Oct 10, 12am (UTC)\n"


def envelope(text):
    return json.dumps({"result": text}).encode("utf-8")


def write_raw(state, header, body=b""):
    path = state / "usage-pause" / "last-raw"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header.encode("utf-8") + body)
    return path


def stdout_raw(state, body):
    return write_raw(state, HEADER % ("exited", "0", "stdout", len(body)), body)


def run(state):
    return subprocess.run(
        [sys.executable, str(LIB), "show-last-raw", "--state-dir", str(state)],
        capture_output=True,
        text=True,
        check=False,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )


def snapshot(state):
    snap = {}
    for path in [state, *state.rglob("*")]:
        st = path.stat()
        snap[str(path)] = (st.st_mtime_ns, path.read_bytes() if path.is_file() else None)
    return snap


def test_current_format_no_session_line(tmp_path):
    body = envelope("Current week (Fable): 3% used\n" + WEEKLY)
    stdout_raw(tmp_path, body)
    proc = run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert "parse: outcome=success reason=-" in proc.stdout
    assert "session_limit=none" in proc.stdout
    assert "weekly_all_pct=12" in proc.stdout
    assert "model fable=3" in proc.stdout
    assert "--- result text ---" in proc.stdout
    assert "header: run_epoch=1760000000 (2025-10-09T08:53:20Z) read=exited" in proc.stdout


def test_old_format_with_session_line(tmp_path):
    stdout_raw(tmp_path, envelope("Current session: 41% used · resets 3am\n" + WEEKLY))
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "session_limit=present" in proc.stdout
    assert "session_pct=41" in proc.stdout


def test_unrecognised_limit_line_is_reported_failure_exit_zero(tmp_path):
    stdout_raw(tmp_path, envelope("Current session (5h): 12% used\n" + WEEKLY))
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "parse: outcome=failure reason=missing_session" in proc.stdout
    assert "detail: result:" in proc.stdout


def test_real_fixture_classifies(tmp_path):
    stdout_raw(tmp_path, fx("envelope-weekly-only.json"))
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "outcome=success" in proc.stdout


def test_header_only_read_none(tmp_path):
    write_raw(tmp_path, HEADER % ("none", "-", "none", 0))
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "parse: not_classified (stream=none read=none)" in proc.stdout


def test_stderr_stream_not_classified_body_printed(tmp_path):
    body = b"ssh: connect to host failed"
    write_raw(tmp_path, HEADER % ("exited", "255", "stderr", len(body)), body)
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "parse: not_classified (stream=stderr read=exited)" in proc.stdout
    assert "--- raw body ---" in proc.stdout
    assert "ssh: connect to host failed" in proc.stdout


def test_missing_file(tmp_path):
    proc = run(tmp_path)
    assert proc.returncode == up.EXIT_FAIL
    assert proc.stdout == ""
    assert "usage_pause show-last-raw:" in proc.stderr


def test_garbage_header_body_still_printed(tmp_path):
    write_raw(tmp_path, "garbage header\n", b"some body text\n")
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "header: invalid" in proc.stdout
    assert "parse: header_invalid" in proc.stdout
    assert "some body text" in proc.stdout


def test_read_only(tmp_path):
    stdout_raw(tmp_path, envelope(WEEKLY))
    (tmp_path / "usage-pause" / "reading").write_text("schema=1\n")
    before = snapshot(tmp_path)
    assert run(tmp_path).returncode == 0
    assert snapshot(tmp_path) == before


def test_nothing_created_when_dir_absent(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    assert run(state).returncode == up.EXIT_FAIL
    assert list(state.iterdir()) == []


def test_ansi_and_non_ascii_neutralised(tmp_path):
    write_raw(tmp_path, "garbage\n", "\x1b[31mred\x1b[0m café \x07bell\n".encode("utf-8"))
    proc = run(tmp_path)
    assert "\x1b" not in proc.stdout
    assert "\x07" not in proc.stdout
    assert "é" not in proc.stdout
    assert "caf?" in proc.stdout


def test_ansi_in_envelope_result_text(tmp_path):
    stdout_raw(tmp_path, envelope("\x1b[31m" + WEEKLY + "é\n"))
    proc = run(tmp_path)
    assert "\x1b" not in proc.stdout
    assert "é" not in proc.stdout


def test_stdout_stream_nonzero_rc_is_classified(tmp_path):
    body = envelope(WEEKLY)
    write_raw(tmp_path, HEADER % ("exited", "1", "stdout", len(body)), body)
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "rc=1 stream=stdout" in proc.stdout
    assert "parse: outcome=" in proc.stdout
    assert "not_classified" not in proc.stdout


def test_stdout_stream_without_rc_is_classified(tmp_path):
    body = envelope(WEEKLY)
    write_raw(tmp_path, HEADER % ("exited", "-", "stdout", len(body)), body)
    proc = run(tmp_path)
    assert "rc=- stream=stdout" in proc.stdout
    assert "parse: outcome=" in proc.stdout
    assert "not_classified" not in proc.stdout


def test_stdout_stream_with_timeout_read_not_classified(tmp_path):
    body = envelope(WEEKLY)
    write_raw(tmp_path, HEADER % ("timeout", "-", "stdout", len(body)), body)
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "parse: not_classified (stream=stdout read=timeout)" in proc.stdout
    assert "--- raw body ---" in proc.stdout
    assert "outcome=" not in proc.stdout


def test_exited_stderr_stream_never_shows_result_text(tmp_path):
    write_raw(tmp_path, HEADER % ("exited", "0", "stderr", 5), envelope(WEEKLY))
    proc = run(tmp_path)
    assert "--- result text ---" not in proc.stdout
    assert "--- raw body ---" in proc.stdout


def test_envelope_result_text_replaces_raw_json_body(tmp_path):
    stdout_raw(tmp_path, envelope(WEEKLY))
    proc = run(tmp_path)
    assert '{"result"' not in proc.stdout
    assert "Current week (all models): 12% used" in proc.stdout


def test_non_envelope_stdout_body_falls_back_to_raw_body(tmp_path):
    stdout_raw(tmp_path, b"not json at all\n")
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "--- raw body ---" in proc.stdout
    assert "not json at all" in proc.stdout
    assert "--- result text ---" not in proc.stdout


def test_read_is_capped(tmp_path):
    head = b"KEEP-MARKER\n"
    tail = b"DROP-MARKER"
    pad = b"x" * (up.INPUT_CAP_BYTES + 256)
    write_raw(tmp_path, "garbage\n", head + pad + tail)
    proc = run(tmp_path)
    assert proc.returncode == 0
    assert "KEEP-MARKER" in proc.stdout
    assert "DROP-MARKER" not in proc.stdout
    assert len(proc.stdout) < up.INPUT_CAP_BYTES + 1024


def test_control_characters_stripped_but_tab_and_newline_kept(tmp_path):
    write_raw(tmp_path, "garbage\n", b"a\tb\nc\x00d\x7fe\x1b]0;title\x07f\n")
    proc = run(tmp_path)
    assert "a\tb\nc" in proc.stdout
    assert "\x00" not in proc.stdout and "\x7f" not in proc.stdout
    assert "title" not in proc.stdout


def test_fifo_last_raw_fails_promptly_without_hanging(tmp_path):
    path = tmp_path / "usage-pause" / "last-raw"
    path.parent.mkdir(parents=True)
    os.mkfifo(path)
    proc = subprocess.run(
        [sys.executable, str(LIB), "show-last-raw", "--state-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    assert proc.returncode == up.EXIT_FAIL
    assert "is not a regular file" in proc.stderr
    assert proc.stdout == ""


def test_symlinked_last_raw_is_refused(tmp_path):
    target = tmp_path / "elsewhere"
    target.write_bytes(HEADER.encode() % (b"none", b"-", b"none", 0))
    path = tmp_path / "usage-pause" / "last-raw"
    path.parent.mkdir(parents=True)
    path.symlink_to(target)
    proc = run(tmp_path)
    assert proc.returncode == up.EXIT_FAIL
    assert "usage_pause show-last-raw:" in proc.stderr
    assert proc.stdout == ""
