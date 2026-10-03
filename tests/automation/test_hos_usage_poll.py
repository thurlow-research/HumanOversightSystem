"""#1944 S1: bin/hos-usage-poll integration (stub ssh, claude, crontab, ssh-keygen)."""

import json
import os
import re
import stat
import subprocess
import time

import pytest

from tests.automation.usage_support import POLLER, fx, up

SENTINEL = up.GATE_SENTINEL
PUB = "ssh-ed25519 AAAAC3NzaBLOB hos-loopback"


class Rig:
    def __init__(self, tmp_path):
        self.home = tmp_path / "home"
        self.state = self.home / ".hos"
        self.bin = self.home / ".local" / "bin"
        self.bin.mkdir(parents=True)
        (self.home / ".ssh").mkdir()
        (self.home / ".config" / "hos").mkdir(parents=True)
        self.out = self.home / "claude.out"
        self.out.write_bytes(fx("capture2-envelope-2026-10-03.json"))
        self.extra_env = {}
        self.claude = self.stub(
            "claude",
            'echo "$@" > "$HOME/claude.argv"\nenv > "$HOME/claude.env"\n'
            '[ -n "${HOS_TEST_CLAUDE_SLEEP:-}" ] && sleep "$HOS_TEST_CLAUDE_SLEEP"\n'
            'cat "$HOME/claude.out"\nexit "${HOS_TEST_CLAUDE_EXIT:-0}"\n',
        )
        self.stub(
            "ssh",
            'printf "%s\\n" "$@" > "$HOME/ssh.argv"\nenv > "$HOME/ssh.env"\n'
            'if [ -n "${HOS_TEST_FORCED_COMMAND:-}" ]; then $HOS_TEST_FORCED_COMMAND; fi\n'
            'exit "${HOS_TEST_SSH_EXIT:-0}"\n',
        )
        self.stub("ssh-keygen", 'exit "${HOS_TEST_KNOWN_HOSTS_RC:-0}"\n')
        self.stub("crontab", 'cat "$HOME/crontab.txt" 2>/dev/null || exit 1\n')
        self.key = self.home / ".ssh" / "hos_loopback"
        self.key.write_text("PRIVATE\n")
        self.key.chmod(0o600)
        (self.home / ".ssh" / "hos_loopback.pub").write_text(PUB + "\n")
        self.set_forced(True)
        self.write_authorized()
        self.write_crontab()

    def stub(self, name, body):
        p = self.bin / name
        p.write_text("#!/usr/bin/env bash\n" + body)
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
        return p

    def set_forced(self, on):
        if on:
            self.extra_env["HOS_TEST_FORCED_COMMAND"] = (
                "%s -p /usage --output-format json" % self.claude
            )
        else:
            self.extra_env.pop("HOS_TEST_FORCED_COMMAND", None)

    def write_authorized(self, options=None, cmd=None):
        cmd = cmd or "%s -p /usage --output-format json" % self.claude
        if options is None:
            options = 'from="127.0.0.1,::1",command="%s"' % cmd
        (self.home / ".ssh" / "authorized_keys").write_text("%s %s\n" % (options, PUB))

    def cron_copy(self, name="a", sentinel=True, lib=True):
        root = self.home / name / "bin"
        (root / "lib").mkdir(parents=True)
        (root / "hos-cron").write_text("#!/bin/bash\n%s\n" % (SENTINEL if sentinel else "# none"))
        if lib:
            (root / "lib" / "usage_pause.py").write_text("")
        return root / "hos-cron"

    def write_crontab(self, extra=(), poll_line=None):
        line = poll_line or "*/5 * * * *  %s > %s/.hos/usage-pause/poll.last.log 2>&1" % (
            POLLER,
            self.home,
        )
        (self.home / "crontab.txt").write_text("\n".join([line, *extra]) + "\n")

    def conf(self, text):
        (self.home / ".config" / "hos" / "usage-pause.conf").write_text(text)

    def env(self, **more):
        env = {
            "HOME": str(self.home),
            "PATH": os.environ["PATH"],
            "HOS_STATE_DIR": str(self.state),
            "TMPDIR": str(self.home),
        }
        env.update(self.extra_env)
        env.update(more)
        return env

    def run(self, *args, **env):
        return subprocess.run(
            ["bash", str(POLLER), *args],
            env=self.env(**env),
            capture_output=True,
            text=True,
            timeout=120,
        )

    @property
    def dir(self):
        return self.state / "usage-pause"

    def reading(self):
        return up.read_reading(self.dir / "reading")


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def test_poll_success_writes_reading(rig):
    r = rig.run()
    assert r.returncode == 0, r.stderr
    rd = rig.reading()
    assert rd.state == "ok" and rd.fields["outcome"] == "success"
    assert rd.fields["session_pct"] == "11" and rd.fields["parsed_via"] == "grep"
    assert rd.fields["poll_pause_condition"] == "0"
    assert "outcome=success" in r.stdout and "pause_condition=0" in r.stdout
    assert (rig.dir.stat().st_mode & 0o777) == 0o700


def test_poll_ssh_argv_ends_at_host(rig):
    rig.run()
    argv = (rig.home / "ssh.argv").read_text().split("\n")
    assert argv[:3] == ["-n", "-i", str(rig.key)] and argv[-2] == "127.0.0.1" and argv[-1] == ""


def test_forced_command_argv_exact(rig):
    rig.run()
    assert (rig.home / "claude.argv").read_text().strip() == "-p /usage --output-format json"


def test_poll_no_forced_command_envelope_invalid(rig):
    rig.set_forced(False)
    rig.run()
    assert rig.reading().fields["reason"] == "envelope_invalid"
    assert rig.reading().fields["outcome"] == "failure"


def test_poll_env_passed_through(rig):
    rig.run(HOS_TEST_MARKER="kept", CLAUDE_CODE_OAUTH_TOKEN="sentinel-token")
    env = (rig.home / "claude.env").read_text()
    assert "HOS_TEST_MARKER=kept" in env and "CLAUDE_CODE_OAUTH_TOKEN=sentinel-token" in env


def test_poll_ssh_255_ssh_failed(rig):
    rig.set_forced(False)
    rig.run(HOS_TEST_SSH_EXIT="255")
    f = rig.reading().fields
    assert f["reason"] == "ssh_failed" and f["remote_exit"] == "255"


def test_poll_key_missing_ssh_failed(rig):
    rig.key.unlink()
    assert rig.run().returncode == 0
    f = rig.reading().fields
    assert f["reason"] == "ssh_failed" and f["detail"] == "loopback key missing"


def test_poll_spawn_failed(rig, tmp_path):
    """The poller pins PATH (so a real ssh is always found); drive the library steps with ssh absent."""
    empty = tmp_path / "empty"
    empty.mkdir()
    env = rig.env(PATH=str(empty))
    lib = [os.sys.executable, str(up.__file__)]
    out = subprocess.run(
        [
            *lib,
            "read-usage",
            "--timeout",
            "5",
            "--key",
            str(rig.key),
            "--stdout",
            str(rig.home / "o"),
            "--stderr",
            str(rig.home / "e"),
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    assert out.stdout.strip() == "read=spawn_failed rc=-"
    (rig.dir).mkdir(parents=True)
    subprocess.run(
        [*lib, "poll-record", "--state-dir", str(rig.state), "--read", "spawn_failed"],
        env=env,
        check=True,
        capture_output=True,
    )
    assert rig.reading().fields["reason"] == "spawn_failed"


def test_poll_needs_no_timeout_binary(rig):
    text = POLLER.read_text()
    assert not re.search(r"(^|[\s;&|(])(g?timeout)\s", text, re.M)
    assert rig.run().returncode == 0


@pytest.mark.slow
def test_poll_timeout(rig):
    rig.conf("read_timeout_seconds=5\n")
    rig.set_forced(True)
    start = time.time()
    rig.run(HOS_TEST_CLAUDE_SLEEP="60")
    assert rig.reading().fields["reason"] == "timeout"
    assert time.time() - start < 40


def test_poll_remote_124_is_not_timeout(rig):
    rig.run(HOS_TEST_SSH_EXIT="124")
    f = rig.reading().fields
    assert f["outcome"] == "success" and f["remote_exit"] == "124"


def test_poll_nonzero_remote_exit_content_decides(rig):
    rig.run(HOS_TEST_SSH_EXIT="2")
    assert rig.reading().fields["outcome"] == "success"
    rig.out.write_bytes(fx("empty-session-envelope-blank.json"))
    rig.run(HOS_TEST_SSH_EXIT="2")
    assert rig.reading().fields["reason"] == "empty_session"


def test_poll_failure_overwrites_success(rig):
    rig.run()
    rig.out.write_bytes(fx("empty-session-envelope-blank.json"))
    rig.run()
    f = rig.reading().fields
    assert f["outcome"] == "failure" and "session_pct" not in f
    assert f["consecutive_failures"] == "1" and "last_success_epoch" in f


def test_poll_dir_bounded(rig):
    rig.run()
    rig.out.write_bytes(fx("envelope-not-json.txt"))
    rig.run()
    rig.key.unlink()
    rig.run()
    assert sorted(os.listdir(rig.dir)) == ["last-raw", "reading"]
    assert os.listdir(rig.state / "locks") == []


def test_poll_runs_while_project_suspended(rig):
    (rig.state / "suspend").mkdir(parents=True)
    (rig.state / "suspend" / "hos").write_text("x")
    assert rig.run().returncode == 0
    assert rig.reading().fields["outcome"] == "success"


def test_poll_lock_held_exits_without_write(rig):
    (rig.state / "locks" / "usage-poll.lock").mkdir(parents=True)
    r = rig.run()
    assert r.returncode == 0 and "another poll holds the lock" in r.stdout
    assert not (rig.dir / "reading").exists()
    assert (rig.state / "locks" / "usage-poll.lock").is_dir()


def test_poll_stale_lock_reclaimed_diagnostic(rig):
    lock = rig.state / "locks" / "usage-poll.lock"
    lock.mkdir(parents=True)
    old = time.time() - 3600
    os.utime(lock, (old, old))
    rig.run()
    assert rig.reading().fields["diagnostics"] == "lock_stale_reclaimed"


def test_poll_lib_missing_bash_crash_file(rig, tmp_path):
    copy = tmp_path / "copy" / "bin"
    copy.mkdir(parents=True)
    script = copy / "hos-usage-poll"
    script.write_text(POLLER.read_text())
    script.chmod(0o755)
    r = subprocess.run(
        ["bash", str(script)], env=rig.env(), capture_output=True, text=True, timeout=60
    )
    assert r.returncode != 0
    f = rig.reading().fields
    assert (
        f["outcome"] == "crashed" and f["reason"] == "crashed" and f["detail"].startswith("exit=")
    )


def test_poll_invalid_settings_still_polls(rig):
    rig.conf("session_threshold=0\n")
    rig.run()
    f = rig.reading().fields
    assert f["outcome"] == "success"
    assert (
        f["poll_settings_status"] == "invalid:session_threshold"
        and f["poll_pause_condition"] == "1"
    )
    assert "poll_session_threshold" not in f


def test_poll_emits_no_audit(rig):
    rig.run()
    assert not (rig.home / "audit").exists()
    assert not list(rig.home.rglob("*.json"))


def test_last_raw_success_then_failure(rig):
    rig.run()
    first = (rig.dir / "last-raw").read_bytes()
    assert first.split(b"\n", 1)[0].startswith(b"# hos-usage-poll last-raw run_epoch=")
    assert b"read=exited rc=0 stream=stdout" in first.split(b"\n", 1)[0]
    rig.out.write_bytes(fx("envelope-not-json.txt"))
    rig.run()
    raw = (rig.dir / "last-raw").read_bytes()
    header, body = raw.split(b"\n", 1)
    assert body == fx("envelope-not-json.txt") and b"bytes=%d" % len(body) in header
    assert [p for p in os.listdir(rig.dir) if p.startswith("last-raw")] == ["last-raw"]


def test_last_raw_transport_failure_holds_stderr_tail(rig):
    rig.stub("ssh", 'echo "Permission denied (publickey)." >&2\nexit 255\n')
    rig.run()
    header, body = (rig.dir / "last-raw").read_bytes().split(b"\n", 1)
    assert b"rc=255 stream=stderr" in header and b"Permission denied" in body


def test_last_raw_no_read_header_only(rig):
    rig.run()
    rig.key.unlink()
    rig.run()
    raw = (rig.dir / "last-raw").read_bytes()
    assert raw.endswith(b"read=none rc=- stream=none bytes=0\n")
    assert b"Current session" not in raw and raw.count(b"\n") == 1


def test_last_raw_unwritable_reading_identical(rig):
    rig.run()
    base = dict(rig.reading().fields)
    (rig.dir / "last-raw").unlink()
    (rig.dir / "last-raw").mkdir()  # make the last-raw write fail
    r = rig.run()
    assert r.returncode == 0
    again = dict(rig.reading().fields)
    for key in ("outcome", "session_pct", "poll_pause_condition"):
        assert again[key] == base[key]


# ── --check ────────────────────────────────────────────────────────────────


def check(rig, *args, **env):
    r = rig.run("--check", *args, **env)
    items = {}
    for line in r.stdout.splitlines():
        m = re.match(r"(PASS|FAIL|SKIP|INFO)  (\d+)  (.*)", line)
        if m:
            items.setdefault(int(m.group(2)), []).append((m.group(1), m.group(3)))
    return r, items


def status(items, n):
    return [s for s, _t in items[n]]


def good_rig(rig):
    rig.write_crontab(extra=["0 2 * * 0 %s/a/bin/hos-cron --role worker" % rig.home])
    rig.cron_copy("a")


def test_check_all_pass(rig):
    good_rig(rig)
    r, items = check(rig)
    assert r.returncode == 0, r.stdout
    assert r.stdout.rstrip().endswith("RESULT: PASS")
    for n in (1, 2, 3, 4, 5, 6, 7, 8):
        assert "FAIL" not in status(items, n), (n, items[n])
    assert any(
        "SUCCESS session=11 weekly_all=1 fable=0 cost_usd=0 read_tokens=0" in t
        for _s, t in items[7]
    )
    assert items[10][0][0] == "INFO"


def tree(rig):
    """Home tree minus the stubs' own invocation records."""
    records = {"claude.argv", "claude.env", "ssh.argv", "ssh.env"}
    return sorted(str(p) for p in rig.home.rglob("*") if p.name not in records)


def test_check_idempotent_writes_nothing(rig):
    good_rig(rig)
    before = tree(rig)
    check(rig)
    check(rig)
    assert before == tree(rig)


def test_check_missing_key_fails_nonzero(rig):
    good_rig(rig)
    rig.key.unlink()
    r, items = check(rig)
    assert r.returncode == 1 and "FAIL" in status(items, 1)
    assert "RESULT: FAIL" in r.stdout


def test_check_key_mode_0644_fails(rig):
    good_rig(rig)
    rig.key.chmod(0o644)
    _r, items = check(rig)
    assert "FAIL" in status(items, 1)


def test_check_authorized_keys_exact_pass(rig):
    good_rig(rig)
    assert check(rig)[1][2][0][0] == "PASS"


def test_check_restrict_option_fails(rig):
    good_rig(rig)
    rig.write_authorized(
        options='restrict,from="127.0.0.1,::1",command="%s -p /usage --output-format json"'
        % rig.claude
    )
    _r, items = check(rig)
    assert items[2][0][0] == "FAIL" and "extra option: restrict" in items[2][0][1]


def test_check_command_mismatch_fails(rig):
    good_rig(rig)
    rig.write_authorized(cmd="/usr/bin/claude -p /usage")
    _r, items = check(rig)
    assert items[2][0][0] == "FAIL" and "command mismatch" in items[2][0][1]


def test_check_missing_from_fails(rig):
    good_rig(rig)
    rig.write_authorized(options='command="%s -p /usage --output-format json"' % rig.claude)
    assert "missing from=" in check(rig)[1][2][0][1]


def test_check_two_lines_fail(rig):
    good_rig(rig)
    ak = rig.home / ".ssh" / "authorized_keys"
    ak.write_text(ak.read_text() * 2)
    assert check(rig)[1][2][0][0] == "FAIL"


def test_check_known_hosts_missing_fails(rig):
    good_rig(rig)
    assert "FAIL" in status(check(rig, HOS_TEST_KNOWN_HOSTS_RC="1")[1], 3)


def test_check_crontab_append_fails(rig):
    good_rig(rig)
    rig.write_crontab(poll_line="*/5 * * * * %s >> /tmp/x 2>&1" % POLLER)
    assert check(rig)[1][5][0][0] == "FAIL"


def test_check_crontab_interval_mismatch_fails(rig):
    good_rig(rig)
    rig.write_crontab(poll_line="*/10 * * * * %s > /tmp/x 2>&1" % POLLER)
    assert check(rig)[1][5][0][0] == "FAIL"
    rig.conf("poll_interval_seconds=600\nstaleness_seconds=1800\n")
    assert check(rig)[1][5][0][0] == "PASS"


def test_check_crontab_path_not_self_fails(rig):
    good_rig(rig)
    rig.write_crontab(poll_line="*/5 * * * * /elsewhere/bin/hos-usage-poll > /tmp/x 2>&1")
    assert check(rig)[1][5][0][0] == "FAIL"


def test_check_crontab_absent_fails(rig):
    (rig.home / "crontab.txt").unlink()
    _r, items = check(rig)
    assert items[5][0][0] == "FAIL"


def test_check_claude_not_executable_item6(rig):
    good_rig(rig)
    rig.conf("claude_bin=/nonexistent/claude\n")
    _r, items = check(rig)
    assert (
        items[6][0][0] == "FAIL" and "claude_not_executable: /nonexistent/claude" in items[6][0][1]
    )


def test_check_read_failure_fails(rig):
    good_rig(rig)
    rig.out.write_bytes(fx("envelope-not-json.txt"))
    r, items = check(rig)
    assert items[7][0][0] == "FAIL" and "FAILED reason=envelope_invalid" in items[7][0][1]
    assert items[10] == [("SKIP", "no successful read")] and r.returncode == 1


def test_check_nonzero_cost_fails(rig):
    good_rig(rig)
    doc = json.loads(fx("capture2-envelope-2026-10-03.json"))
    doc["total_cost_usd"] = 0.5
    rig.out.write_text(json.dumps(doc))
    assert check(rig)[1][7][0][0] == "FAIL"


def test_check_absent_tokens_fails(rig):
    good_rig(rig)
    doc = json.loads(fx("capture2-envelope-2026-10-03.json"))
    del doc["usage"]
    rig.out.write_text(json.dumps(doc))
    _r, items = check(rig)
    assert items[7][0][0] == "FAIL" and "read_tokens=absent" in items[7][0][1]


def test_check_capture_fixture_writes_unfiltered_stdout(rig, tmp_path):
    good_rig(rig)
    full = fx("live-full-envelope-2026-10-03.json")
    rig.out.write_bytes(full)
    target = tmp_path / "cap" / "env.json"
    target.parent.mkdir()
    before = tree(rig)
    r, items = check(rig, "--capture-fixture", str(target))
    assert target.read_bytes() == full and (target.stat().st_mode & 0o777) == 0o600
    assert not (target.parent / "env.json.tmp").exists()
    assert any(t.startswith("captured %d bytes" % len(full)) for _s, t in items[7])
    assert tree(rig) == before


def test_check_capture_fixture_refuses_existing_path(rig, tmp_path):
    existing = tmp_path / "there.json"
    existing.write_text("keep")
    r, items = check(rig, "--capture-fixture", str(existing))
    assert r.returncode == 64 and items == {} and existing.read_text() == "keep"


def test_check_gate_sentinel_all_copies(rig):
    a, b = rig.cron_copy("a"), rig.cron_copy("b")
    rig.write_crontab(extra=["0 * * * * %s --role worker" % a, "5 * * * * %s --role overseer" % b])
    _r, items = check(rig)
    assert [s for s, _t in items[8]] == ["PASS", "PASS"]


def test_check_gate_missing_in_one_copy_fails_naming_path(rig):
    a, b = rig.cron_copy("a"), rig.cron_copy("b", sentinel=False)
    rig.write_crontab(extra=["0 * * * * %s --role worker" % a, "5 * * * * %s --role overseer" % b])
    r, items = check(rig)
    fails = [t for s, t in items[8] if s == "FAIL"]
    assert len(fails) == 1 and str(b) in fails[0] and "NOT paused" in fails[0] and r.returncode == 1


def test_check_gate_lib_missing_fails(rig):
    a = rig.cron_copy("a", lib=False)
    rig.write_crontab(extra=["0 * * * * %s --role worker" % a])
    assert "usage_pause.py missing" in check(rig)[1][8][0][1]


def test_check_gate_home_expansion(rig):
    rig.cron_copy("a")
    rig.write_crontab(
        extra=[
            "0 * * * * $HOME/a/bin/hos-cron --role worker",
            "1 * * * * ${HOME}/a/bin/hos-cron --role overseer",
            "2 * * * * ~/a/bin/hos-cron --role x",
        ]
    )
    _r, items = check(rig)
    assert [s for s, _t in items[8]] == ["PASS"]  # one distinct resolved file


def test_check_gate_relative_path_fails(rig):
    rig.write_crontab(extra=["0 * * * * bin/hos-cron --role worker"])
    assert "relative hos-cron path" in check(rig)[1][8][0][1]


def test_check_no_hos_cron_info(rig):
    _r, items = check(rig)
    assert items[8] == [("INFO", "no hos-cron scheduled in this user's crontab")]


def seven_percent(rig):
    doc = json.loads(fx("capture2-envelope-2026-10-03.json"))
    doc["result"] = doc["result"].replace("Current session: 11%", "Current session: 7%")
    rig.out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_check_item10_over_threshold_info_pause_1(rig):
    good_rig(rig)
    seven_percent(rig)
    rig.conf("session_threshold=5\n")
    r, items = check(rig)
    assert items[10] == [("INFO", "pause_condition=1 reason=session 7% >= 5")]
    assert r.returncode == 0 and r.stdout.rstrip().endswith("RESULT: PASS")


def test_check_item10_under_threshold_info_pause_0(rig):
    good_rig(rig)
    _r, items = check(rig)
    assert items[10][0][1].startswith("pause_condition=0 reason=session 11% < 90")


def test_check_item10_reason_equals_poll_view(rig):
    good_rig(rig)
    seven_percent(rig)
    rig.conf("session_threshold=5\n")
    _r, items = check(rig)
    rig.run()
    assert (
        items[10][0][1] == "pause_condition=1 reason=" + rig.reading().fields["poll_pause_reason"]
    )


def test_check_item10_invalid_settings(rig):
    good_rig(rig)
    rig.conf("session_threshold=0\n")
    r, items = check(rig)
    assert items[10] == [("INFO", "pause_condition=1 reason=settings_invalid:session_threshold")]
    assert "FAIL" in status(items, 4)


def test_check_item10_skip_on_failed_read(rig):
    good_rig(rig)
    rig.out.write_bytes(fx("empty-session-envelope-blank.json"))
    assert check(rig)[1][10] == [("SKIP", "no successful read")]


def test_check_item10_never_fails_result(rig):
    good_rig(rig)
    seven_percent(rig)
    rig.conf("session_threshold=1\n")
    r, items = check(rig)
    assert items[10][0][1].startswith("pause_condition=1") and r.returncode == 0


# ── --print-setup, remote-cmd ──────────────────────────────────────────────


def test_print_setup_never_mutates(rig):
    before = sorted((str(p), p.stat().st_mtime_ns) for p in rig.home.rglob("*"))
    r = rig.run("--print-setup")
    after = sorted((str(p), p.stat().st_mtime_ns) for p in rig.home.rglob("*"))
    assert r.returncode == 0 and before == after


def test_print_setup_one_authorized_keys_line_no_restrict(rig):
    out = rig.run("--print-setup").stdout
    lines = [ln for ln in out.splitlines() if ln.startswith("from=")]
    assert lines == [
        'from="127.0.0.1,::1",command="%s -p /usage --output-format json" %s' % (rig.claude, PUB)
    ]
    assert "restrict" not in out and "env -u" not in out


def test_print_setup_crontab_matches_interval_and_self(rig):
    out = rig.run("--print-setup").stdout
    assert "*/5 * * * *  %s > %s/.hos/usage-pause/poll.last.log 2>&1" % (POLLER, rig.home) in out
    rig.conf("poll_interval_seconds=3600\nstaleness_seconds=7200\n")
    assert "0 * * * *  %s >" % POLLER in rig.run("--print-setup").stdout
    assert "--check --capture-fixture %s/hos-usage-envelope-" % rig.home in out


def test_print_setup_missing_pub(rig):
    (rig.home / ".ssh" / "hos_loopback.pub").unlink()
    r = rig.run("--print-setup")
    assert r.returncode == 1 and "MISSING:" in r.stdout


def test_remote_cmd_output(rig):
    r = rig.run("remote-cmd")
    assert (
        r.stdout.strip() == "%s -p /usage --output-format json" % rig.claude and r.returncode == 0
    )


def test_remote_cmd_without_claude_exits_1(monkeypatch, tmp_path):
    monkeypatch.setenv("HOS_USAGE_PAUSE_CONF", str(tmp_path / "none.conf"))
    monkeypatch.setattr(up.shutil, "which", lambda _name: None)
    assert up.main(["remote-cmd"]) == 1


def test_help_first_description_line():
    r = subprocess.run(["bash", str(POLLER), "--help"], capture_output=True, text=True)
    assert r.stdout.splitlines()[0] == (
        "Reads Claude subscription usage (/usage) over SSH loopback (ADR-1944); "
        "the read itself is bin/lib/usage_pause.py read-usage."
    )


def test_usage_error_exit_64():
    assert subprocess.run(["bash", str(POLLER), "--bogus"], capture_output=True).returncode == 64
