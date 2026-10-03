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
FLAGS = up.AUTHORIZED_KEY_FLAGS
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
        self.timeout = self.stub("timeout", 'shift 3\nexec "$@"\n')
        self.stub("ssh-keygen", 'exit "${HOS_TEST_KNOWN_HOSTS_RC:-0}"\n')
        self.stub("crontab", 'cat "$HOME/crontab.txt" 2>/dev/null || exit 1\n')
        self.key = self.home / ".ssh" / "hos_loopback"
        self.key.write_text("PRIVATE\n")
        self.key.chmod(0o600)
        (self.home / ".ssh" / "hos_loopback.pub").write_text(PUB + "\n")
        self.dir.mkdir(parents=True)
        self.dir.chmod(0o700)
        self.set_forced(True)
        self.write_authorized()
        self.write_crontab()

    def stub(self, name, body):
        p = self.bin / name
        p.write_text("#!/usr/bin/env bash\n" + body)
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
        return p

    def forced(self, read_timeout=60):
        return "%s -k 5 %d %s -p /usage --output-format json" % (
            self.timeout,
            read_timeout - 10,
            self.claude,
        )

    def set_forced(self, on):
        if on:
            self.extra_env["HOS_TEST_FORCED_COMMAND"] = self.forced()
        else:
            self.extra_env.pop("HOS_TEST_FORCED_COMMAND", None)

    def write_authorized(self, options=None, cmd=None):
        cmd = cmd or self.forced()
        if options is None:
            options = 'from="127.0.0.1,::1",%s,command="%s"' % (",".join(FLAGS), cmd)
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
    rig.dir.mkdir(parents=True, exist_ok=True)
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
    rig.conf("read_timeout_seconds=20\n")
    rig.set_forced(True)
    start = time.time()
    r = rig.run(HOS_TEST_CLAUDE_SLEEP="60")
    assert rig.reading().fields["reason"] == "timeout"
    assert rig.reading().fields["detail"] == "local_timeout"
    assert "ABORT read timed out (local kill); retry next poll" in r.stdout
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
    assert r.returncode == 0 and "another poll holds the lock" in r.stderr
    assert "reading is unchanged" in r.stderr
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
        m = re.match(r"(PASS|FAIL|SKIP|INFO)  (\d+[ab]?)  (.*)", line)
        if m:
            key = int(m.group(2)) if m.group(2).isdigit() else m.group(2)
            items.setdefault(key, []).append((m.group(1), m.group(3)))
    return r, items


def status(items, n):
    return [s for s, _t in items[n]]


def good_rig(rig):
    rig.write_crontab(extra=["0 2 * * 0 %s/a/bin/hos-cron --role worker" % rig.home])
    rig.cron_copy("a")
    assert rig.run().returncode == 0  # a poll has run, so a fresh reading exists


def test_check_all_pass(rig):
    good_rig(rig)
    r, items = check(rig)
    assert r.returncode == 0, r.stdout
    assert r.stdout.rstrip().endswith("RESULT: PASS")
    for n in (1, 2, 3, 4, 5, "6a", "6b", 7, 8):
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
        options='restrict,from="127.0.0.1,::1",%s,command="%s"' % (",".join(FLAGS), rig.forced())
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
        items["6a"][0][0] == "FAIL"
        and "claude_not_executable: /nonexistent/claude" in items["6a"][0][1]
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
    target.parent.chmod(0o700)
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
        'from="127.0.0.1,::1",%s,command="%s" %s' % (",".join(FLAGS), rig.forced(), PUB)
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
    assert r.stdout.strip() == rig.forced() and r.returncode == 0
    rig.conf("read_timeout_seconds=30\npoll_interval_seconds=300\n")
    assert rig.run("remote-cmd").stdout.strip() == rig.forced(30)


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


def test_print_setup_claude_not_found_exits_1(rig):
    rig.claude.unlink()
    env = rig.env(PATH="/usr/bin:/bin")
    r = subprocess.run(
        ["bash", str(POLLER), "--print-setup"], env=env, capture_output=True, text=True, timeout=60
    )
    if "claude" in r.stdout and "MISSING" not in r.stdout:
        pytest.skip("a system claude exists on the pinned PATH")
    assert r.returncode == 1 and "MISSING: claude or timeout not found" in r.stdout
    assert not any(ln.startswith("from=") for ln in r.stdout.splitlines())


def test_check_capture_write_failure_reports_and_continues(rig, tmp_path):
    good_rig(rig)
    target = tmp_path / "no-such-dir" / "env.json"
    r, items = check(rig, "--capture-fixture", str(target))
    assert "Traceback" not in r.stderr and "Traceback" not in r.stdout
    assert any(s == "FAIL" and t.startswith("capture failed:") for s, t in items[7])
    assert r.stdout.rstrip().splitlines()[-1].startswith("RESULT: FAIL")
    assert 8 in items and 10 in items and r.returncode == 1


def test_check_duplicate_from_option_fails(rig):
    good_rig(rig)
    cmd = rig.forced()
    rig.write_authorized(options='from="0.0.0.0/0",from="127.0.0.1,::1",command="%s"' % cmd)
    item = check(rig)[1][2][0]
    assert item == ("FAIL", "duplicate option: from= — re-run --print-setup block 3")


def test_check_duplicate_command_option_fails(rig):
    good_rig(rig)
    cmd = rig.forced()
    rig.write_authorized(options='from="127.0.0.1,::1",command="/bin/sh",command="%s"' % cmd)
    assert "duplicate option: command=" in check(rig)[1][2][0][1]


def test_check_unquoted_option_value_fails(rig):
    good_rig(rig)
    rig.write_authorized(options="from=127.0.0.1,command=x")
    item = check(rig)[1][2][0]
    assert item[0] == "FAIL" and "must be double-quoted" in item[1]


def test_check_unquoted_from_value_names_quoting(rig):
    ok, text = up.check_authorized_keys(
        rig.home / ".ssh" / "hos_loopback.pub",
        _write(rig, 'from=127.0.0.1 command="x" ' + PUB),
        "x",
    )
    assert not ok and "must be double-quoted" in text


def _write(rig, line):
    path = rig.home / ".ssh" / "ak2"
    path.write_text(line + "\n")
    return path


def test_check_temp_dir_failure_is_a_fail_line(rig):
    good_rig(rig)
    r, items = check(rig, TMPDIR=str(rig.home / "does-not-exist"))
    assert "Traceback" not in r.stderr
    assert items[7][0][0] == "FAIL" and "cannot create a temp directory" in items[7][0][1]
    assert r.returncode == 1 and 8 in items


def test_run_text_has_timeout(monkeypatch):
    seen = {}

    def fake(argv, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(up.subprocess, "run", fake)
    assert up._run_text(["crontab", "-l"]) is None
    assert seen["timeout"] == up.SUBPROCESS_TIMEOUT_SECONDS


def test_print_setup_quotes_paths(tmp_path):
    spaced = Rig(_mk(tmp_path / "a b"))
    out = spaced.run("--print-setup").stdout
    assert "'%s/.hos/usage-pause/poll.last.log' 2>&1" % spaced.home in out
    assert "--capture-fixture '%s/hos-usage-envelope-" % spaced.home in out


def _mk(path):
    path.mkdir()
    return path


def test_check_state_dir_item12(rig):
    good_rig(rig)
    assert check(rig)[1][12][0][0] == "PASS"
    rig.dir.chmod(0o755)
    _r, items = check(rig)
    assert items[12][0][0] == "FAIL" and "run --print-setup block 1" in items[12][0][1]
    rig.dir.chmod(0o700)
    (rig.dir / "last-raw").unlink(missing_ok=True)
    (rig.dir / "reading").unlink()
    rig.dir.rmdir()
    assert check(rig)[1][12][0][0] == "FAIL"
    rig.dir.write_text("a file")
    assert "not a directory" in check(rig)[1][12][0][1]


def test_check_state_dir_honours_hos_state_dir(rig, tmp_path):
    other = tmp_path / "elsewhere"
    r, items = check(rig, HOS_STATE_DIR=str(other))
    assert items[12][0][0] == "FAIL" and str(other) in items[12][0][1]


def test_check_item11_reading_age_and_failures(rig):
    good_rig(rig)
    _r, items = check(rig)
    assert items[11][0][0] == "INFO"
    assert "outcome=success reason=- consecutive_failures=0" in items[11][0][1]


def test_check_item11_missing_reading_fails_only_when_cron_passed(rig):
    good_rig(rig)
    (rig.dir / "reading").unlink()
    r, items = check(rig)
    assert items[11][0][0] == "FAIL" and r.returncode == 1
    rig.write_crontab(poll_line="*/10 * * * * %s > /tmp/x 2>&1" % POLLER)
    assert check(rig)[1][11][0][0] == "INFO"


def test_check_item11_stale_reading_fails(rig):
    good_rig(rig)
    rig.conf("staleness_seconds=900\n")
    text = (rig.dir / "reading").read_text()
    old = int(time.time()) - 5000
    text = re.sub(r"run_epoch=\d+", "run_epoch=%d" % old, text)
    (rig.dir / "reading").write_text(text)
    _r, items = check(rig)
    assert items[11][0][0] == "FAIL" and "age=" in items[11][0][1]


def test_ssh_argv_has_hardening_options(rig):
    rig.run()
    argv = (rig.home / "ssh.argv").read_text().split("\n")
    for opt in (
        "ClearAllForwardings=yes",
        "ForwardAgent=no",
        "ForwardX11=no",
        "IdentityAgent=none",
    ):
        assert opt in argv
    assert argv[-2] == "127.0.0.1"


def test_check_capture_refuses_group_writable_parent(rig, tmp_path):
    bad = tmp_path / "shared"
    bad.mkdir()
    bad.chmod(0o770)
    r, items = check(rig, "--capture-fixture", str(bad / "env.json"))
    assert r.returncode == 64 and items == {} and "refused" in r.stderr
    assert not (bad / "env.json").exists()


@pytest.mark.slow
def test_check_capture_skipped_when_read_did_not_exit(rig, tmp_path):
    good_rig(rig)
    rig.conf("read_timeout_seconds=20\n")
    target = tmp_path / "cap.json"
    _r, items = check(rig, "--capture-fixture", str(target), HOS_TEST_CLAUDE_SLEEP="30")
    assert ("INFO", "capture skipped: read did not exit") in items[7]
    assert not target.exists()


def test_lock_dead_pid_reclaimed(rig):
    lock = rig.state / "locks" / "usage-poll.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("999999\n")
    rig.run()
    assert rig.reading().fields["diagnostics"] == "lock_stale_reclaimed"
    assert not lock.exists()


def test_lock_live_pid_holds_and_is_diagnosable(rig):
    lock = rig.state / "locks" / "usage-poll.lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("%d\n" % os.getpid())
    r = rig.run()
    assert r.returncode == 0 and ("pid %d" % os.getpid()) in r.stderr
    assert not (rig.dir / "reading").exists() and lock.is_dir()


def test_lock_not_removed_when_no_longer_ours(rig):
    lock = rig.state / "locks" / "usage-poll.lock"
    rig.stub(
        "claude",
        'echo 4242 > "%s/pid"\ncat "$HOME/claude.out"\n' % lock,
    )
    rig.run()
    assert lock.is_dir() and (lock / "pid").read_text().strip() == "4242"
    assert sorted(p.name for p in rig.dir.iterdir()) == ["last-raw", "reading"]


def test_lock_stale_by_age_without_pid_uses_backstop(rig):
    lock = rig.state / "locks" / "usage-poll.lock"
    lock.mkdir(parents=True)
    fresh = rig.run()
    assert "holds the lock" in fresh.stderr
    old = time.time() - 3600
    os.utime(lock, (old, old))
    rig.run()
    assert rig.reading().fields["diagnostics"] == "lock_stale_reclaimed"


def test_helper_stderr_reaches_log_and_detail(rig, tmp_path):
    copy = tmp_path / "copy" / "bin"
    (copy / "lib").mkdir(parents=True)
    (copy / "hos-usage-poll").write_text(POLLER.read_text())
    (copy / "lib" / "usage_pause.py").write_text(
        "import sys\nsys.stderr.write('boom from helper\\n')\nsys.exit(3)\n"
    )
    r = subprocess.run(
        ["bash", str(copy / "hos-usage-poll")],
        env=rig.env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "boom from helper" in r.stderr
    assert r.returncode != 0


def test_check_each_missing_flag_fails(rig):
    good_rig(rig)
    for flag in FLAGS:
        rest = [f for f in FLAGS if f != flag]
        rig.write_authorized(
            options='from="127.0.0.1,::1",%s,command="%s"' % (",".join(rest), rig.forced())
        )
        item = check(rig)[1][2][0]
        assert item[0] == "FAIL" and ("missing option: %s" % flag) in item[1]


def test_check_duplicate_flag_fails(rig):
    good_rig(rig)
    rig.write_authorized(
        options='from="127.0.0.1,::1",%s,no-pty,command="%s"' % (",".join(FLAGS), rig.forced())
    )
    assert "duplicate option: no-pty" in check(rig)[1][2][0][1]


def test_check_flag_order_is_free(rig):
    good_rig(rig)
    rig.write_authorized(
        options='command="%s",%s,from="127.0.0.1,::1"' % (rig.forced(), ",".join(reversed(FLAGS)))
    )
    assert check(rig)[1][2][0][0] == "PASS"


def test_check_unknown_extra_option_still_fails(rig):
    good_rig(rig)
    rig.write_authorized(
        options='from="127.0.0.1,::1",%s,no-touch-required,command="%s"'
        % (",".join(FLAGS), rig.forced())
    )
    assert "extra option: no-touch-required" in check(rig)[1][2][0][1]


def test_check_changed_read_timeout_needs_regenerated_line(rig):
    good_rig(rig)
    rig.conf("read_timeout_seconds=30\n")
    item = check(rig)[1][2][0]
    assert item[0] == "FAIL" and "command mismatch" in item[1]
    assert item[1].endswith("re-run --print-setup block 3")
    rig.write_authorized(cmd=rig.forced(30))
    assert check(rig)[1][2][0][0] == "PASS"


def test_check_timeout_bin_missing_or_not_executable(rig):
    good_rig(rig)
    assert ("PASS", "timeout_bin %s is executable" % rig.timeout) in check(rig)[1]["6b"]
    rig.conf("timeout_bin=/nonexistent/timeout\n")
    fails = [t for s, t in check(rig)[1]["6b"] if s == "FAIL"]
    assert fails and fails[0].startswith("timeout_not_executable: /nonexistent/timeout")


def test_timeout_bin_setting_used_in_command(rig):
    rig.conf("timeout_bin=/opt/bin/timeout\n")
    assert rig.run("remote-cmd").stdout.startswith("/opt/bin/timeout -k 5 50 ")


def test_remote_cmd_needs_timeout_binary(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOS_USAGE_PAUSE_CONF", str(tmp_path / "none.conf"))
    monkeypatch.setattr(
        up.shutil, "which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )
    assert up.main(["remote-cmd"]) == 1
    assert "timeout" in capsys.readouterr().err


def _no_envelope(rig, rc):
    rig.set_forced(False)
    return rig.run(HOS_TEST_SSH_EXIT=str(rc))


def test_remote_timeout_124_and_137_classified_timeout(rig):
    for rc in (124, 137):
        r = _no_envelope(rig, rc)
        f = rig.reading().fields
        assert f["reason"] == "timeout" and f["detail"] == "remote_timeout rc=%d" % rc
        assert f["remote_exit"] == str(rc) and f["outcome"] == "failure"
        assert "ABORT read timed out (remote rc=%d); retry next poll" % rc in r.stdout, r.stdout
    assert rig.reading().fields["consecutive_failures"] == "2"


def test_remote_124_with_valid_envelope_is_not_a_timeout(rig):
    rig.run(HOS_TEST_SSH_EXIT="124")
    assert rig.reading().fields["outcome"] == "success"


def test_remote_timeout_is_not_retried_in_the_same_poll(rig):
    rig.set_forced(False)
    rig.run(HOS_TEST_SSH_EXIT="124")
    assert (rig.home / "ssh.argv").exists()
    calls = rig.home / "ssh.count"
    rig.stub("ssh", 'echo x >> "%s"\nexit 124\n' % calls)
    rig.run()
    assert calls.read_text().count("x") == 1


def test_check_state_dir_item_prints_first(rig):
    good_rig(rig)
    lines = rig.run("--check").stdout.splitlines()
    first = [ln for ln in lines if ln[:4] in ("PASS", "FAIL", "INFO", "SKIP")][0]
    assert first.startswith("PASS  12  ")


def test_check_item6_rows_are_6a_and_6b(rig):
    good_rig(rig)
    _r, items = check(rig)
    assert 6 not in items and items["6a"][0][1].startswith("claude_bin ")
    assert items["6b"][0][1].startswith("timeout_bin ")


def test_check_ssh_failed_cross_references_setup_items(rig):
    good_rig(rig)
    rig.write_authorized(options='from="127.0.0.1,::1",command="x"')
    rig.set_forced(False)
    _r, items = check(rig, HOS_TEST_SSH_EXIT="255")
    assert items[2][0][0] == "FAIL"
    text = items[7][0][1]
    assert "FAILED reason=ssh_failed" in text
    assert "likely caused by item 2 (authorized_keys line)" in text


def test_check_ssh_failed_cross_reference_multiple_and_key_missing(rig):
    good_rig(rig)
    rig.key.unlink()
    _r, items = check(rig, HOS_TEST_KNOWN_HOSTS_RC="1")
    assert "likely caused by item 1 (loopback key); item 3 (known_hosts)" in items[7][0][1]


def test_check_no_cross_reference_when_setup_items_pass(rig):
    good_rig(rig)
    rig.set_forced(False)
    _r, items = check(rig, HOS_TEST_SSH_EXIT="255")
    assert "likely caused by" not in items[7][0][1]


def test_timeout_side_remote_in_reading_after_remote_exit(rig):
    r = _no_envelope(rig, 137)
    f = rig.reading().fields
    assert f["timeout_side"] == "remote" and f["remote_exit"] == "137"
    names = [ln.split("=")[0] for ln in (rig.dir / "reading").read_text().splitlines()]
    assert names.index("timeout_side") == names.index("remote_exit") + 1
    assert "remote rc=137" in r.stdout


def test_timeout_side_absent_unless_timeout(rig):
    rig.run()
    assert "timeout_side" not in rig.reading().fields
    rig.set_forced(False)
    rig.run(HOS_TEST_SSH_EXIT="255")
    assert "timeout_side" not in rig.reading().fields
    rig.run(HOS_TEST_SSH_EXIT="2")
    assert rig.reading().fields["reason"] == "envelope_invalid"
    assert "timeout_side" not in rig.reading().fields
