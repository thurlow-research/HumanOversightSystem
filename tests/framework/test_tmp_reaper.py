"""Tests for bootstrap/tmp_reaper.py, the machine-level temp reaper (#2054, Layer 2).

Technical design section 10 (R1-R19, RS1-RS18) plus the quotactl_fd extension.
Every test sweeps roots under ``tmp_path`` only; none touches the real /tmp or a
real HOS tmp root. The reaper runs in process with an injected clock that is 48 h
ahead, so real ctimes count as "old" without lowering the 24 h threshold. The
host-view precondition is patched to pass except where a test is about it.
"""

import builtins
import errno
import getpass
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import load_module_from_path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "bootstrap" / "tmp_reaper.py"
tr = load_module_from_path("hos_tmp_reaper_tests", SCRIPT, register=True)
_REAL_HOST_VIEW = tr.check_host_view
_REAL_READ_REGISTRY = tr.read_registry
TEST_REGISTRY: list = []  # the fake machine registry every test machine has

HOUR = 3600
OFFSET = 48 * HOUR
USER = getpass.getuser()
SUMMARY_RE = re.compile(
    r"^TMP_REAPER roots=\d+ reaped=\d+ freed_bytes=\d+ skipped=\d+ errors=\d+ truncated=[01] "
    r"user_bytes=(\d+|-) pytest_runs=\d+ empty_tmp_dirs=\d+ tmp_files=\d+ scratch_trees=(\d+|-) dry_run=[01]$"
)
has_proc = pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="needs /proc")
not_root = pytest.mark.skipif(os.geteuid() == 0, reason="the reaper refuses to run as root")
pytestmark = not_root


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    FAKE_CTIME.clear()
    TEST_REGISTRY.clear()
    monkeypatch.setattr(tr, "_ts", _fake_ts)
    monkeypatch.setattr(tr, "read_registry", lambda: [dict(e) for e in TEST_REGISTRY])
    monkeypatch.setattr(tr, "check_host_view", lambda: None)
    monkeypatch.setattr(tr, "read_user_quota", lambda path: None)


def _reisolate(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(tr, "_ts", _fake_ts)
    monkeypatch.setattr(tr, "read_registry", lambda: [dict(e) for e in TEST_REGISTRY])
    monkeypatch.setattr(tr, "check_host_view", lambda: None)
    monkeypatch.setattr(tr, "read_user_quota", lambda path: None)


@pytest.fixture
def reap(capsys):
    def run(*args, offset=OFFSET):
        rc = tr.main(list(args), clock=lambda: time.time() + offset)
        return rc, capsys.readouterr().out.splitlines()

    return run


def summary(out):
    assert SUMMARY_RE.fullmatch(out[-1]), out[-1]
    return dict(kv.split("=") for kv in out[-1].split()[1:])


def verdicts(out, kind):
    return [ln for ln in out if ln.startswith(kind + " ")]


# The age signal is st_ctime alone, and a test cannot set ctime. So "this entry is N hours
# old" is recorded per inode here and returned by a patched ``tr._ts``; anything never
# registered keeps its real ctime, which the injected +48 h clock makes old.
FAKE_CTIME: dict = {}


def _fake_ts(st):
    return FAKE_CTIME.get((st.st_dev, st.st_ino), st.st_ctime)


def age(path, hours=48.0):
    """Make ``path`` and everything under it appear ``hours`` old at the fake now."""
    t = time.time() + OFFSET - hours * HOUR
    paths = [str(path)]
    for dirpath, dirs, files in os.walk(str(path)):
        paths.extend(os.path.join(dirpath, n) for n in dirs + files)
    for p in paths:
        try:
            st = os.lstat(p)
        except OSError:
            continue
        FAKE_CTIME[(st.st_dev, st.st_ino)] = t


def mark(role):
    """Register an HOS role dir the way bootstrap/lib/hos_tmp_root.py does (path, role and
    inode in the machine registry), plus the informational marker."""
    role = Path(role)
    role.mkdir(parents=True, exist_ok=True)
    (role / ".hos-tmp-root").write_text(f"hos-tmp-root v3 role={role.name}\n")
    st = os.lstat(role)
    TEST_REGISTRY[:] = [e for e in TEST_REGISTRY if e["path"] != str(role.resolve())]
    TEST_REGISTRY.append(
        {"path": str(role.resolve()), "role": role.name, "st_dev": st.st_dev, "st_ino": st.st_ino}
    )
    return role


def snapshot(path):
    out = {}
    for dirpath, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(dirpath, n)
            st = os.lstat(p)
            out[os.path.relpath(p, path)] = (st.st_ino, st.st_mtime_ns)
    return out


def pdir(root):
    d = Path(root) / f"pytest-of-{USER}"
    d.mkdir(exist_ok=True)
    return d


def make_run(root, n, *, lock=False, live_record=False, hours=48.0, name=None):
    run = pdir(root) / (name or f"pytest-{n}")
    run.mkdir()
    (run / "test_x0").mkdir()
    (run / "test_x0" / "f.txt").write_text("x")
    if lock:
        (run / ".lock").write_text("999999")
    if live_record:
        live = run / ".hos-live"
        live.write_text("")
        st = live.stat()
        live.write_text(f"pid=1 start=1 dev={st.st_dev} ino={st.st_ino}\n")
    age(run, hours)
    return run


HOLDER = """
import fcntl, os, sys, time
d = sys.argv[1]
fd = os.open(os.path.join(d, ".hos-live"), os.O_CREAT | os.O_RDWR, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
st = os.fstat(fd)
os.write(fd, ("pid=%d start=1 dev=%d ino=%d\\n" % (os.getpid(), st.st_dev, st.st_ino)).encode())
open(os.path.join(d, ".lock"), "w").write(str(os.getpid()))
print("ready", flush=True)
time.sleep(600)
"""


def spawn(code, *argv, cwd=None):
    p = subprocess.Popen(
        [sys.executable, "-c", code, *argv],
        stdout=subprocess.PIPE,
        text=True,
        cwd=cwd,
    )
    assert p.stdout.readline().strip() == "ready"
    return p


def kill(p):
    p.send_signal(signal.SIGKILL)
    p.wait()
    p.stdout.close()


SLEEPER = "import sys, time; print('ready', flush=True); time.sleep(600)"


# ── Class P ────────────────────────────────────────────────────────────────────
def test_r1_live_run_is_never_touched_until_the_holder_is_killed(tmp_path, reap):
    run = pdir(tmp_path) / "pytest-5"
    run.mkdir()
    holder = spawn(HOLDER, str(run))
    try:
        age(run)
        before = snapshot(run)
        for extra in ((), ("--dry-run",)):
            rc, out = reap("--root", str(tmp_path), "--no-scratch", *extra)
            assert rc == 0 and any(ln.startswith("SKIP live-flock") for ln in out), out
            assert snapshot(run) == before
    finally:
        kill(holder)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert any(ln.startswith("REAP P dead-flock") for ln in out), out
    assert not run.exists()


def test_r2_legacy_lock_uses_the_uniform_24h_threshold(tmp_path, reap):
    for n, hours in ((1, 3), (2, 23)):
        make_run(tmp_path, n, lock=True, hours=hours)
    old = make_run(tmp_path, 3, lock=True)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert sorted(ln.split()[2] for ln in out if ln.startswith("SKIP fresh")) == [
        str(pdir(tmp_path) / "pytest-1"),
        str(pdir(tmp_path) / "pytest-2"),
    ]
    assert any("REAP P legacy-stale" in ln for ln in out)
    assert not old.exists() and (pdir(tmp_path) / "pytest-1").exists()


@has_proc
def test_r3_legacy_lock_naming_a_live_pytest_process_is_kept(tmp_path, reap):
    child = spawn(SLEEPER + "  # pytest-marker")
    try:
        run = make_run(tmp_path, 4, lock=True)
        (run / ".lock").write_text(str(child.pid))
        age(run)
        cmd = Path(f"/proc/{child.pid}/cmdline").read_bytes()
        assert b"pytest" in cmd
        rc, out = reap("--root", str(tmp_path), "--no-scratch")
        assert any(ln.startswith("SKIP live-proc") for ln in out), out
        assert run.exists()
    finally:
        kill(child)


def test_r4_fresh_beats_a_dead_flock(tmp_path, reap):
    run = make_run(tmp_path, 6, lock=True, live_record=True, hours=1)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert any(ln.startswith("SKIP fresh") for ln in out) and run.exists()


def test_r5_both_old_finished_dirs_are_reaped_with_no_keep_newest(tmp_path, reap):
    a, b = make_run(tmp_path, 1), make_run(tmp_path, 2)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert len(verdicts(out, "REAP")) == 2 and not a.exists() and not b.exists()
    assert all("REAP P finished" in ln for ln in verdicts(out, "REAP"))


def test_r6_symlinks_are_never_followed(tmp_path, reap):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("k")
    secret = tmp_path / "secret.txt"
    secret.write_text("s")
    # pytest-of-<user> itself a symlink: nothing reaped in class P.
    real = tmp_path / "real-pytest-of"
    real.mkdir()
    (real / "pytest-1").mkdir()
    age(real)
    root_a = tmp_path / "a"
    root_a.mkdir()
    (root_a / f"pytest-of-{USER}").symlink_to(real)
    rc, out = reap("--root", str(root_a), "--no-scratch")
    assert any(ln.startswith("SKIP not-owned-or-symlink") for ln in out)
    assert (real / "pytest-1").exists()
    # pytest-7 -> outside dir; reaped dir containing a symlink to an outside file.
    root_b = tmp_path / "b"
    root_b.mkdir()
    pd = pdir(root_b)
    (pd / "pytest-7").symlink_to(outside)
    run = make_run(root_b, 8)
    (run / "link").symlink_to(secret)
    (pd / "pytest-current").symlink_to(run)
    age(run)
    rc, out = reap("--root", str(root_b), "--no-scratch")
    assert (outside / "keep.txt").exists() and secret.exists()
    assert (pd / "pytest-7").is_symlink()
    assert not run.exists()
    # pytest-current dangled once its target was reaped (it sorts after pytest-8): removed.
    assert not os.path.lexists(pd / "pytest-current")
    assert any("REAP P symlink-dangling" in ln for ln in out)
    # A valid pytest-current is kept.
    root_c = tmp_path / "c"
    root_c.mkdir()
    keep = make_run(root_c, 1, hours=1)
    (pdir(root_c) / "pytest-current").symlink_to(keep)
    reap("--root", str(root_c), "--no-scratch")
    assert (pdir(root_c) / "pytest-current").is_symlink() and keep.exists()


def _pfacts(**kw):
    base = dict(path="/r/pytest-1", name="pytest-1", uid=1000, quiet_ts=0.0)
    base.update(kw)
    return tr.PFacts(**base)


def test_r7_decide_with_synthetic_facts():
    pol = tr.Policy(uid=1000, age_s=24 * HOUR)
    now = 10 * 24 * HOUR
    idx = tr.ProcIndex(available=True, complete=True)
    assert tr.decide(_pfacts(uid=1), now, pol).action == "SKIP"
    probe = _pfacts(has_hos_live=True, probe="unknown", proc=idx)
    assert tr.decide(probe, now, pol) == tr.Decision("SKIP", "unknown")
    assert tr.decide(_pfacts(has_hos_live=True), now, pol) == tr.Decision("NEED", "probe")
    # an absent PID is not evidence: a lock with no pid and no other signal still needs the veto data
    assert tr.decide(_pfacts(has_lock=True), now, pol) == tr.Decision("NEED", "proc")
    incomplete = tr.ProcIndex(available=True, complete=False)
    assert tr.decide(_pfacts(proc=incomplete), now, pol) == tr.Decision(
        "SKIP", "proc-scan-incomplete"
    )
    gone = tr.ProcIndex(available=False)
    assert tr.decide(_pfacts(proc=gone), now, pol) == tr.Decision("REAP", "finished")
    assert tr.decide(_pfacts(has_lock=True, proc=gone), now, pol) == tr.Decision(
        "REAP", "legacy-stale"
    )
    hit = tr.ProcIndex(True, True, 0, frozenset({"/r/pytest-1/sub"}))
    assert tr.decide(_pfacts(proc=hit), now, pol) == tr.Decision("SKIP", "live-proc")


def test_r8_class_t_orphans(tmp_path, reap):
    empty = tmp_path / "tmpabcd1234"
    empty.mkdir()
    full = tmp_path / "tmpzzzz9999"
    (full / "x").mkdir(parents=True)
    (full / "x" / "f").write_text("1")
    mkt = tmp_path / "tmp.AbCdEf1234"
    mkt.write_text("v")
    pyf = tmp_path / "tmpabcd1234.py"
    pyf.write_text("x")
    fifo = tmp_path / "tmpfifo_999"
    os.mkfifo(fifo)
    other = tmp_path / "keepme.txt"
    other.write_text("k")
    fresh = tmp_path / "tmpfresh_11"
    fresh.mkdir()
    for p in (empty, full, mkt, pyf, fifo, other):
        age(p)
    age(fresh, 23)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert not empty.exists() and not mkt.exists() and not pyf.exists()
    assert any(ln.startswith("SKIP non-empty") for ln in out) and full.exists()
    assert any(ln.startswith("SKIP special") for ln in out) and fifo.exists()
    assert fresh.exists() and other.exists()
    reasons = {ln.split()[2] for ln in verdicts(out, "REAP")}
    assert reasons == {"empty-dir", "file"}


@has_proc
def test_r8_file_held_open_by_a_live_child_is_kept(tmp_path, reap):
    f = tmp_path / "tmp.QwErTy0123"
    f.write_text("v")
    code = f"import time; fh = open({str(f)!r}); print('ready', flush=True); time.sleep(600)"
    child = spawn(code)
    try:
        age(f)
        rc, out = reap("--root", str(tmp_path), "--no-scratch")
        assert any(ln.startswith("SKIP open") for ln in out) and f.exists()
    finally:
        kill(child)


def test_r9_garbage_dirs(tmp_path, reap):
    old = make_run(tmp_path, 0, name="garbage-1111")
    new = make_run(tmp_path, 0, name="garbage-2222", hours=23)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert not old.exists() and new.exists()
    assert any("REAP P garbage" in ln for ln in out)


def test_r10_dry_run_changes_nothing(tmp_path, reap):
    make_run(tmp_path, 1)
    (tmp_path / "tmpabcd1234").mkdir()
    age(tmp_path / "tmpabcd1234")
    tree = tmp_path / "claude" / "c1" / "a"
    tree.mkdir(parents=True)
    (tree / "f").write_text("1")
    age(tmp_path / "claude")
    before = snapshot(tmp_path)
    rc, out = reap("--root", str(tmp_path), "--dry-run")
    assert snapshot(tmp_path) == before
    kinds = {ln.split()[1] for ln in verdicts(out, "WOULD-REAP")}
    assert kinds == {"P", "T", "S"}
    assert summary(out)["reaped"] == "0" and summary(out)["dry_run"] == "1"


def _runner(root):
    code = (
        "import sys, time, importlib.util as u\n"
        f"s = u.spec_from_file_location('r', {str(SCRIPT)!r}); m = u.module_from_spec(s)\n"
        "sys.modules['r'] = m; s.loader.exec_module(m)\n"
        f"sys.exit(m.main(['--root', {str(root)!r}, '--no-scratch'], clock=lambda: time.time() + {OFFSET}))\n"
    )
    return subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )


def test_r11_two_concurrent_reapers_converge(tmp_path):
    for n in range(1, 25):
        make_run(tmp_path, n)
    for i in range(40):
        f = tmp_path / f"tmp.{i:010d}"
        f.write_text("x")
        age(f)
    procs = [_runner(tmp_path), _runner(tmp_path)]
    results = [(p.wait(timeout=120), p.stdout.read(), p.stderr.read()) for p in procs]
    for rc, _out, err in results:
        assert rc == 0 and "Traceback" not in err, err
    assert not any(pdir(tmp_path).iterdir()) and not list(tmp_path.glob("tmp.*"))


def test_r12_root_resolution(tmp_path, reap, monkeypatch):
    assert tr.default_roots({"TMPDIR": "/x"}) == ["/x"]
    assert tr.default_roots({}) == ["/tmp"] == tr.default_roots({"TMPDIR": ""})
    rc, out = reap("--root", str(tmp_path / "nope"))
    assert rc == 3 and "SKIP root-invalid" in "\n".join(out)
    good = tmp_path / "good"
    good.mkdir()
    rc, out = reap("--root", str(tmp_path / "nope"), "--root", str(good))
    assert rc == 0 and summary(out)["roots"] == "1"
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    rc, out = reap("--root", str(good))
    assert rc == 3


def test_r13_output_framing_and_measure(tmp_path, reap):
    make_run(tmp_path, 1)
    before = snapshot(tmp_path)
    rc, out = reap("--root", str(tmp_path), "--measure")
    assert out[0].startswith("TMP_REAPER_RUN ts=") and "pid=" in out[0]
    assert snapshot(tmp_path) == before
    s = summary(out)
    assert s["user_bytes"].isdigit() and s["reaped"] == "0"
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert out[0].startswith("TMP_REAPER_RUN") and SUMMARY_RE.fullmatch(out[-1])
    assert summary(out)["user_bytes"] == "-"


def test_r14_zero_budget_truncates_and_reaps_nothing(tmp_path, reap):
    run = make_run(tmp_path, 1)
    rc, out = reap("--root", str(tmp_path), "--max-seconds", "0")
    assert rc == 0 and summary(out)["truncated"] == "1" and run.exists()


def test_r15_routing_of_finished_versus_dead_flock(tmp_path, reap):
    finished = make_run(tmp_path, 1, live_record=True)
    killed = make_run(tmp_path, 2, live_record=True, lock=True)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    reaps = {Path(ln.split()[3]).name: ln.split()[2] for ln in verdicts(out, "REAP")}
    assert reaps == {"pytest-1": "finished", "pytest-2": "dead-flock"}
    assert not finished.exists() and not killed.exists()


def test_r16_hos_live_edge_cases(tmp_path, reap):
    mismatch = make_run(tmp_path, 1)
    (mismatch / ".hos-live").write_text("pid=1 start=1 dev=1 ino=1\n")
    fifo = make_run(tmp_path, 2)
    os.mkfifo(fifo / ".hos-live")
    sym = make_run(tmp_path, 3)
    (sym / "real").write_text("x")
    (sym / ".hos-live").symlink_to(sym / "real")
    for r in (mismatch, fifo, sym):
        age(r)
    t0 = time.monotonic()
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert time.monotonic() - t0 < 30
    assert len([ln for ln in out if ln.startswith("SKIP unknown")]) == 3
    assert all(r.exists() for r in (mismatch, fifo, sym))


@has_proc
def test_r17_a_dir_that_is_a_live_childs_cwd_is_kept(tmp_path, reap):
    finished = make_run(tmp_path, 1)
    killed = make_run(tmp_path, 2, lock=True, live_record=True)
    kids = [spawn(SLEEPER, cwd=str(finished)), spawn(SLEEPER, cwd=str(killed / "test_x0"))]
    try:
        rc, out = reap("--root", str(tmp_path), "--no-scratch")
        assert len([ln for ln in out if ln.startswith("SKIP live-proc")]) == 2, out
        assert finished.exists() and killed.exists()
    finally:
        for k in kids:
            kill(k)


def test_r18_min_age_is_raise_only(tmp_path, reap):
    assert reap("--root", str(tmp_path), "--min-age-hours", "2")[0] == 2
    assert reap("--root", str(tmp_path), "--min-age-hours", "nan")[0] == 2
    assert reap("--root", str(tmp_path), "--min-age-hours", "48")[0] == 0


def test_r19_measure_only_walks_and_warns(tmp_path, reap, monkeypatch):
    base = tmp_path / "base"
    base.mkdir()
    big = base / "bigthing"
    big.mkdir()
    (big / "f").write_bytes(b"x" * 8000)
    role = mark(tmp_path / "hos" / "Worker")
    (role / "claude-1000").mkdir(parents=True)
    (role / "claude-1000" / "f").write_bytes(b"x" * 8000)
    age(role)
    age(big)
    boom = SimpleNamespace(called=False)

    def walk_boom(*a, **k):
        boom.called = True
        raise AssertionError("size walk ran in a non-measure run")

    monkeypatch.setattr(tr, "allocated_tree", walk_boom)
    monkeypatch.setattr(tr.Reaper, "run_measure", walk_boom)
    for extra in ((), ("--summary-only",)):
        rc, out = reap("--root", str(base), "--hos-tmp-root", str(tmp_path / "hos"), *extra)
        assert not boom.called and summary(out)["user_bytes"] == "-"
        assert not [ln for ln in out if ln.startswith("WARN")]
    _reisolate(monkeypatch)
    monkeypatch.setattr(tr, "LARGE_UNOWNED_BYTES", 6000)
    rc, out = reap("--root", str(base), "--hos-tmp-root", str(tmp_path / "hos"), "--measure")
    warns = [ln for ln in out if ln.startswith("WARN large-unowned")]
    assert {Path(w.split()[2]).name for w in warns} == {"bigthing", "claude-1000"}
    for mode in ((), ("--measure",)):
        reap("--root", str(base), "--hos-tmp-root", str(tmp_path / "hos"), *mode)
        assert (role / "claude-1000" / "f").exists()


# ── Class S ────────────────────────────────────────────────────────────────────
def make_tree(root, name="clone1", rel="a/b/c.txt", hours=48.0):
    tree = Path(root) / "claude" / name
    f = tree / rel
    f.parent.mkdir(parents=True)
    f.write_text("data")
    age(tree, hours)
    age(Path(root) / "claude", hours)
    return tree


def test_rs1_stale_tree_is_removed(tmp_path, reap):
    tree = make_tree(tmp_path)
    rc, out = reap("--root", str(tmp_path))
    assert any(ln.startswith("REAP S scratch-stale") for ln in out), out
    assert not tree.exists() and not list((tmp_path / "claude").glob("garbage-hos-*"))
    assert summary(out)["scratch_trees"] == "0"


def test_rs2_one_recent_deep_file_keeps_the_tree(tmp_path, reap):
    tree = make_tree(tmp_path)
    age(tree / "a" / "b" / "c.txt", 1)
    before = snapshot(tree)
    rc, out = reap("--root", str(tmp_path))
    assert any(ln.startswith("SKIP fresh-deep") for ln in out)
    assert snapshot(tree) == before


@has_proc
def test_rs3_a_tree_that_is_a_cwd_is_kept(tmp_path, reap):
    tree = make_tree(tmp_path, "clone2", "sub/x.txt")
    child = spawn(SLEEPER, cwd=str(tree / "sub"))
    try:
        rc, out = reap("--root", str(tmp_path))
        assert any(ln.startswith("SKIP live-proc") for ln in out) and tree.exists()
    finally:
        kill(child)
    rc, out = reap("--root", str(tmp_path))
    assert not tree.exists()


FLOCKER = """
import fcntl, os, sys, time
fd = os.open(sys.argv[1], os.O_CREAT | os.O_RDWR, 0o600)
(fcntl.flock if sys.argv[2] == "flock" else fcntl.lockf)(fd, fcntl.LOCK_EX)
print("ready", flush=True)
time.sleep(600)
"""


@pytest.mark.parametrize("mode,fname", [("flock", "index.lock"), ("lockf", "data.bin")])
def test_rs4_a_held_lock_keeps_the_tree(tmp_path, reap, monkeypatch, mode, fname):
    tree = make_tree(tmp_path, "clone3", "x/keep.txt")
    target = tree / "x" / fname
    child = spawn(FLOCKER, str(target), mode)
    try:
        age(tree)
        # Model a holder the /proc index cannot see (non-dumpable, other namespace).
        blind = tr.ProcIndex(available=True, complete=True)
        monkeypatch.setattr(tr, "scan_proc", lambda expired: blind)
        seen = []
        real_parse = tr.parse_proc_locks

        def spy(text):
            out = real_parse(text)
            seen.append(out)
            return out

        monkeypatch.setattr(tr, "parse_proc_locks", spy)
        if mode == "lockf":
            st = target.stat()
            key = (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino)
            if not any(key in s for s in [real_parse(Path("/proc/locks").read_text())]):
                pytest.skip("holder's lock is not visible in this PID namespace")
        rc, out = reap("--root", str(tmp_path))
        assert any(ln.startswith("SKIP held-lock") for ln in out), out
        assert tree.exists()
        if mode == "lockf":
            assert seen and key in seen[-1]
    finally:
        kill(child)
    rc, out = reap("--root", str(tmp_path))
    assert not tree.exists()


def test_rs5_symlinks(tmp_path, reap):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("k")
    root = tmp_path / "r"
    root.mkdir()
    sc = root / "claude"
    sc.mkdir()
    tree = sc / "withlink"
    tree.mkdir()
    (tree / "f").write_text("1")
    (tree / "out").symlink_to(outside)
    (sc / "linkchild").symlink_to(outside)
    age(tree)
    age(sc)
    rc, out = reap("--root", str(root))
    assert not tree.exists() and (outside / "keep").exists() and (sc / "linkchild").is_symlink()
    # A scratch root that is itself a symlink is invalid.
    root2 = tmp_path / "r2"
    root2.mkdir()
    (root2 / "claude").symlink_to(outside)
    rc, out = reap("--root", str(root2))
    assert any(ln.startswith("SKIP scratch-root-invalid") for ln in out)
    assert (outside / "keep").exists()


def test_rs6_session_dir_exclusions(tmp_path, reap, monkeypatch):
    sess = tmp_path / "claude-1000" / "proj" / "x"
    sess.mkdir(parents=True)
    age(tmp_path / "claude-1000")
    claude = tmp_path / "claude"
    (claude / "claude-1000").mkdir(parents=True)
    (claude / "pad" / "scratchpad").mkdir(parents=True)
    (claude / "withuuid" / "d" / "123e4567-e89b-12d3-a456-426614174000").mkdir(parents=True)
    selfdir = claude / "selfdir"
    (selfdir / "inner").mkdir(parents=True)
    age(claude)
    monkeypatch.chdir(selfdir / "inner")
    rc, out = reap("--root", str(tmp_path))
    text = "\n".join(out)
    assert "SKIP session-dir" in text and text.count("SKIP session-like") == 2
    assert "SKIP self" in text
    assert sess.exists() and selfdir.exists() and (claude / "pad").exists()


def test_rs7_fail_safe_walk(tmp_path, reap, monkeypatch):
    big = make_tree(tmp_path, "many", "a/1")
    for i in range(5):
        (big / "a" / f"f{i}").write_text("x")
    age(big)
    monkeypatch.setattr(tr, "SCRATCH_MAX_INODES", 2)
    rc, out = reap("--root", str(tmp_path))
    assert any(ln.startswith("SKIP walk-truncated") for ln in out) and big.exists()
    _reisolate(monkeypatch)
    shutil.rmtree(big)
    fifo_tree = make_tree(tmp_path, "withfifo", "a/f")
    os.mkfifo(fifo_tree / "a" / "pipe")
    age(fifo_tree)
    rc, out = reap("--root", str(tmp_path))
    assert any(ln.startswith("SKIP special") for ln in out) and fifo_tree.exists()
    shutil.rmtree(fifo_tree)
    if os.geteuid() != 0:
        locked = make_tree(tmp_path, "locked", "a/b/f")
        os.chmod(locked / "a" / "b", 0)
        try:
            rc, out = reap("--root", str(tmp_path))
            assert any(ln.startswith("SKIP unreadable") for ln in out) and locked.exists()
        finally:
            os.chmod(locked / "a" / "b", 0o700)


def _no_locks_view():
    raise tr.ScratchDisabled("no-locks-view")


@pytest.mark.parametrize("reason", ["no-host-view", "no-locks-view", "proc-scan-incomplete"])
def test_rs8_run_level_gating(tmp_path, reap, monkeypatch, reason):
    tree = make_tree(tmp_path)
    if reason == "no-host-view":
        monkeypatch.setattr(tr, "check_host_view", lambda: "no-host-view")
    elif reason == "no-locks-view":
        monkeypatch.setattr(tr, "load_proc_locks", _no_locks_view)
    else:
        monkeypatch.setattr(
            tr, "scan_proc", lambda expired: tr.ProcIndex(available=True, complete=False)
        )
    rc, out = reap("--root", str(tmp_path))
    assert f"SKIP scratch-disabled {reason}" in out, out
    assert tree.exists() and summary(out)["scratch_trees"] == "-"


def test_rs8_no_scratch_produces_no_class_s_output(tmp_path, reap):
    tree = make_tree(tmp_path)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert tree.exists() and summary(out)["scratch_trees"] == "-"
    assert not [ln for ln in out if " S " in ln or "scratch-" in ln]


def test_rs9_removal_identity(tmp_path, reap, monkeypatch):
    # (i) swapped between the walk and the rename -> raced, no rename
    tree = make_tree(tmp_path, "swap")
    renames = []
    real_rename = os.rename
    monkeypatch.setattr(
        os,
        "rename",
        lambda a, b, *k, **kw: (renames.append((a, b)), real_rename(a, b, *k, **kw))[1],
    )

    def swap(path):
        os.replace(path, path + ".moved")
        os.mkdir(path)

    monkeypatch.setattr(tr, "_before_remove", swap)
    rc, out = reap("--root", str(tmp_path))
    assert any(ln.startswith("SKIP raced") for ln in out) and renames == []
    assert tree.is_dir() and Path(str(tree) + ".moved").is_dir()
    monkeypatch.setattr(tr, "_before_remove", None)
    shutil.rmtree(tree)
    shutil.rmtree(str(tree) + ".moved")
    # (ii) identity differs after the rename -> ERROR, no rmtree, garbage remains
    make_tree(tmp_path, "post")
    real_lstat = os.lstat

    def fake_lstat(p, *a, **k):
        st = real_lstat(p, *a, **k)
        if os.path.basename(str(p)).startswith("garbage-hos-"):
            return SimpleNamespace(
                st_dev=st.st_dev, st_ino=st.st_ino + 1, st_mode=st.st_mode, st_uid=st.st_uid
            )
        return st

    called = []
    real_rmtree = shutil.rmtree
    monkeypatch.setattr(os, "lstat", fake_lstat)

    def fake_rmtree(*a, **k):
        called.append(a)

    fake_rmtree.avoids_symlink_attacks = True
    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)
    rc, out = reap("--root", str(tmp_path))
    monkeypatch.setattr(os, "lstat", real_lstat)
    monkeypatch.setattr(shutil, "rmtree", real_rmtree)
    assert any(ln.startswith("ERROR identity-changed") for ln in out) and called == [], out
    assert list((tmp_path / "claude").glob("garbage-hos-*"))
    # (iii) dry-run -> WOULD-REAP and no rename
    for g in (tmp_path / "claude").glob("garbage-hos-*"):
        shutil.rmtree(g)
    tree3 = make_tree(tmp_path, "dry")
    rc, out = reap("--root", str(tmp_path), "--dry-run")
    assert any(ln.startswith("WOULD-REAP S scratch-stale") for ln in out) and tree3.exists()


def _sfacts(**kw):
    base = dict(
        path="/r/claude/t",
        uid=1000,
        same_dev=True,
        excluded=None,
        is_self=False,
        top_quiet_ts=0.0,
        proc=tr.ProcIndex(available=True, complete=True),
        walk=tr.WalkResult(None),
    )
    base.update(kw)
    return tr.SFacts(**base)


def test_rs10_decide_scratch_is_pure_and_ordered():
    pol = tr.Policy(uid=1000, age_s=24 * HOUR, scratch_active=True)
    now = 10 * 24 * HOUR
    assert tr.decide_scratch(_sfacts(), now, pol) == tr.Decision("REAP", "scratch-stale")
    for kw, reason in (
        (dict(uid=1), "not-owned-or-foreign-dev"),
        (dict(same_dev=False), "not-owned-or-foreign-dev"),
        (dict(excluded="other-class"), "other-class"),
        (dict(excluded="session-dir"), "session-dir"),
        (dict(is_self=True), "self"),
        (dict(top_quiet_ts=now), "fresh"),
        (dict(walk=tr.WalkResult("fresh-deep")), "fresh-deep"),
        (dict(walk=tr.WalkResult("foreign-owned")), "foreign-owned"),
        (dict(walk=tr.WalkResult("cross-device")), "cross-device"),
        (dict(walk=tr.WalkResult("held-lock")), "held-lock"),
        (dict(walk=tr.WalkResult("session-like")), "session-like"),
        (dict(proc=tr.ProcIndex(True, True, 0, frozenset({"/r/claude/t/x"}))), "live-proc"),
    ):
        assert tr.decide_scratch(_sfacts(**kw), now, pol) == tr.Decision("SKIP", reason), kw
    assert tr.decide_scratch(_sfacts(walk=None), now, pol) == tr.Decision("NEED", "walk")


def _git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def _git_fixtures(root):
    sc = Path(root) / "claude"
    sc.mkdir()
    unpushed = sc / "unpushed"
    unpushed.mkdir()
    _git(unpushed, "init", "-q")
    (unpushed / "f").write_text("1")
    _git(unpushed, "add", "-A")
    _git(unpushed, "commit", "-q", "-m", "local only")
    detached = sc / "detached"
    shutil.copytree(unpushed, detached)
    _git(detached, "checkout", "-q", "--detach")
    main_repo = sc / "mainrepo"
    shutil.copytree(unpushed, main_repo)
    _git(main_repo, "worktree", "add", "-q", str(sc / "linked"))
    stash = sc / "stash"
    shutil.copytree(unpushed, stash)
    (stash / "f").write_text("changed")
    _git(stash, "stash")
    age(sc)
    return sc


def test_rs11_git_state_is_not_a_veto_and_git_is_never_read(tmp_path, reap, monkeypatch):
    sc = _git_fixtures(tmp_path)
    opened = []
    real_open, real_osopen = builtins.open, os.open
    monkeypatch.setattr(
        builtins, "open", lambda f, *a, **k: (opened.append(str(f)), real_open(f, *a, **k))[1]
    )
    monkeypatch.setattr(
        os, "open", lambda f, *a, **k: (opened.append(str(f)), real_osopen(f, *a, **k))[1]
    )
    rc, out = reap("--root", str(tmp_path))
    _reisolate(monkeypatch)
    assert len(verdicts(out, "REAP")) == 5, out
    assert not list(sc.iterdir())
    assert not [p for p in opened if "/.git/" in p or p.endswith("/.git")], opened


def test_rs12_the_reaper_never_executes_anything(tmp_path, reap, monkeypatch):
    _git_fixtures(tmp_path)

    def boom(*a, **k):
        raise AssertionError("the reaper executed something")

    for mod, name in (
        (subprocess, "Popen"),
        (subprocess, "run"),
        (os, "system"),
        (os, "posix_spawn"),
        (os, "posix_spawnp"),
        (os, "fork"),
        *((os, n) for n in dir(os) if n.startswith("exec")),
    ):
        if hasattr(mod, name):
            monkeypatch.setattr(mod, name, boom)
    rc, out = reap("--root", str(tmp_path))
    assert rc == 0 and len(verdicts(out, "REAP")) == 5
    src = SCRIPT.read_text()
    assert not re.search(r"^\s*(import|from)\s+(subprocess|pty)\b", src, re.M)


def test_rs13_no_size_floor(tmp_path, reap):
    small = make_tree(tmp_path, "small", "one.txt")
    big = make_tree(tmp_path, "big", "blob.bin")
    (big / "blob.bin").write_bytes(b"x" * (1 << 20))
    age(big)
    rc, out = reap("--root", str(tmp_path))
    assert not small.exists() and not big.exists()


def test_rs14_other_classes_are_not_swallowed(tmp_path, reap):
    sc = tmp_path / "claude"
    names = ("pytest-of-x", "garbage-abc", "tmpabcd1234", "hos-foo")
    for n in names:
        (sc / n).mkdir(parents=True)
    age(sc)
    rc, out = reap("--root", str(tmp_path))
    assert len([ln for ln in out if ln.startswith("SKIP other-class")]) == 4
    assert all((sc / n).exists() for n in names)


def test_rs14_classes_run_p_then_t_then_s(tmp_path, capsys, monkeypatch):
    run = make_run(tmp_path, 1)
    old_file = tmp_path / "tmp.AbCdEf1234"
    old_file.write_text("x")
    age(old_file)
    tree = make_tree(tmp_path, "slow", "a/b/f")
    bump = [0.0]
    real_scandir = os.scandir

    def slow(path=".", *a, **k):
        if str(path).endswith("/slow") or "/slow/" in str(path):
            bump[0] = 1000.0
        return real_scandir(path, *a, **k)

    monkeypatch.setattr(os, "scandir", slow)
    rc = tr.main(
        ["--root", str(tmp_path), "--max-seconds", "30"],
        clock=lambda: time.time() + OFFSET + bump[0],
    )
    out = capsys.readouterr().out.splitlines()
    assert rc == 0 and not run.exists() and not old_file.exists() and tree.exists()
    assert (
        any(ln.startswith("SKIP walk-truncated") for ln in out) and summary(out)["truncated"] == "1"
    )


def test_rs15_preconditions(tmp_path, reap, monkeypatch):
    assert tr.parse_proc_locks("1: FLOCK  ADVISORY  WRITE 1234 00:26:12345 0 EOF") == {
        (0, 38, 12345)
    }
    assert tr.parse_proc_locks("2: -> POSIX  ADVISORY  READ 7 fe:0a:99 0 10\n") == {(254, 10, 99)}
    assert tr.parse_proc_locks("") == set()
    with pytest.raises(ValueError):
        tr.parse_proc_locks("1: FLOCK  ADVISORY  WRITE 1234 00:26:12345 0 EOF\ngarbage line\n")
    tree = make_tree(tmp_path)
    monkeypatch.setattr(
        tr, "_slurp", lambda path, limit=0: "1: nonsense\n" if path.endswith("/locks") else ""
    )
    rc, out = reap("--root", str(tmp_path))
    assert "SKIP scratch-disabled locks-unparseable" in out and tree.exists()
    _reisolate(monkeypatch)
    order = []
    monkeypatch.setattr(tr, "check_host_view", lambda: order.append("host") or None)
    monkeypatch.setattr(tr, "load_proc_locks", lambda: order.append("locks") or set())
    reap("--root", str(tmp_path), "--dry-run")
    assert order[:2] == ["host", "locks"]
    monkeypatch.setattr(tr, "scan_proc", lambda expired: tr.ProcIndex(True, True, 3))
    rc, out = reap("--root", str(tmp_path), "--dry-run")
    assert "SKIP proc-unreadable 3" in out and any(ln.startswith("WOULD-REAP S") for ln in out)


def test_rs16_non_empty_top_level_tmp_dirs(tmp_path, reap, monkeypatch):
    d = tmp_path / "tmpabcd1234"
    (d / "x").mkdir(parents=True)
    (d / "x" / "y.txt").write_text("1")
    age(d)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert any(ln.startswith("SKIP non-empty") for ln in out) and d.exists()
    age(d / "x" / "y.txt", 1)
    rc, out = reap("--root", str(tmp_path))
    assert any(ln.startswith("SKIP fresh-deep") for ln in out) and d.exists()
    age(d)
    rc, out = reap("--root", str(tmp_path))
    assert any(ln.startswith("REAP S scratch-stale") for ln in out) and not d.exists()
    assert not list(tmp_path.glob("garbage-hos-*"))
    leftover = tmp_path / "garbage-hos-1234"
    (leftover / "z").mkdir(parents=True)
    age(leftover)
    rc, out = reap("--root", str(tmp_path))
    assert any("REAP S garbage" in ln for ln in out) and not leftover.exists()


def test_rs16b_shape_2_honours_locks_and_cwd(tmp_path, reap, monkeypatch):
    d = tmp_path / "tmpqwer5678"
    d.mkdir()
    (d / "work.lock").write_text("")
    age(d)
    child = spawn(FLOCKER, str(d / "work.lock"), "flock")
    try:
        monkeypatch.setattr(
            tr, "scan_proc", lambda expired: tr.ProcIndex(available=True, complete=True)
        )
        rc, out = reap("--root", str(tmp_path))
        assert any(ln.startswith("SKIP held-lock") for ln in out) and d.exists()
    finally:
        kill(child)


def test_rs17_multiple_roots(tmp_path, reap):
    hos = tmp_path / ".tmp"
    for n in ("Worker", "Overseer", "Human", "Local", "junk"):
        (hos / n).mkdir(parents=True, exist_ok=True)
    for n in ("Worker", "Overseer", "Human", "Local"):
        mark(hos / n)
    (hos / "notes").write_text("n")
    (hos / "evil").symlink_to(tmp_path / "elsewhere")
    lower = hos / "worker"
    expected_skips = {"junk", "notes", "evil"}
    if not lower.exists():
        lower.mkdir()
        expected_skips.add("worker")
    run_w = make_run(hos / "Worker", 1)
    plain = tmp_path / "plain"
    plain.mkdir()
    run_p = make_run(plain, 2)
    alias = tmp_path / "alias"
    alias.symlink_to(plain)
    rc, out = reap(
        "--root", str(plain), "--root", str(alias), "--root", str(plain), "--hos-tmp-root", str(hos)
    )
    assert not run_w.exists() and not run_p.exists()
    skips = {Path(ln.split()[2]).name for ln in out if ln.startswith("SKIP not-a-role-dir")}
    assert skips == expected_skips
    assert summary(out)["roots"] == "5" and hos.exists()


class _FakeQuota:
    def __init__(self, ratio):
        self.ratio = ratio

    def __call__(self, path):
        return (int(self.ratio * 1000), 1000)


def test_rs18_if_low_space(tmp_path, reap, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    for r in (a, b):
        make_run(r, 1)
        make_run(r, 2, hours=23)
        orphan = r / ".hos-space-probe.1.deadbeef"
        orphan.write_text("x")
        age(orphan)
    rc, out = reap("--root", str(a), "--root", str(b), "--if-low-space")
    assert rc == 0 and out[1] == "TMP_REAPER_PROBE ok" and summary(out)["reaped"] == "0"
    assert (pdir(a) / "pytest-1").exists()
    real_write = os.write
    for errno_ in (errno.EDQUOT, errno.ENOSPC):

        def failing(fd, data, _e=errno_, _real=real_write):
            if os.readlink(f"/proc/self/fd/{fd}").startswith(str(a)):
                raise OSError(_e, "quota")
            return _real(fd, data)

        monkeypatch.setattr(os, "write", failing)
        rc, out = reap("--root", str(a), "--root", str(b), "--if-low-space")
        monkeypatch.setattr(os, "write", real_write)
        assert out[1] == f"TMP_REAPER_PROBE low roots={a}", out
        assert not (pdir(a) / "pytest-1").exists() and not (pdir(b) / "pytest-1").exists()
        assert (pdir(a) / "pytest-2").exists() and (pdir(b) / "pytest-2").exists()  # 23 h survives
        make_run(a, 1)
        make_run(b, 1)
    for r in (a, b):
        probes = [p.name for p in r.iterdir() if p.name.startswith(".hos-space-probe.")]
        assert probes == [".hos-space-probe.1.deadbeef"]
        assert (r / ".hos-space-probe.1.deadbeef").exists()


def test_quota_reading_and_trigger(tmp_path, reap, monkeypatch):
    raw = tr.struct.pack("8QI4x", 5000, 0, 123456, 0, 0, 0, 0, 0, 3)
    assert tr.parse_dqblk(raw) == (123456, 5000 * 1024)
    assert tr.parse_dqblk(tr.struct.pack("8QI4x", 0, 0, 7, 0, 0, 0, 0, 0, 2)) == (7, 0)
    assert tr.parse_dqblk(tr.struct.pack("8QI4x", 0, 0, 7, 0, 0, 0, 0, 0, 0)) is None
    assert tr.parse_dqblk(b"short") is None
    res = tr.read_user_quota(str(tmp_path))  # never raises; None where unsupported
    assert res is None or (len(res) == 2 and res[0] >= 0)
    monkeypatch.setattr(os, "uname", lambda: SimpleNamespace(machine="mips64"))
    assert tr.read_user_quota(str(tmp_path)) is None
    _reisolate(monkeypatch)
    run = make_run(tmp_path, 1)
    monkeypatch.setattr(tr, "read_user_quota", _FakeQuota(0.5))
    rc, out = reap("--root", str(tmp_path), "--if-low-space")
    assert out[1] == "TMP_REAPER_PROBE ok" and run.exists()
    monkeypatch.setattr(tr, "read_user_quota", _FakeQuota(0.85))
    rc, out = reap("--root", str(tmp_path), "--if-low-space")
    assert out[1].startswith("TMP_REAPER_PROBE low") and any(
        ln.startswith("QUOTA root=") for ln in out
    )
    assert not run.exists()
    rc, out = reap("--root", str(tmp_path), "--measure")
    quota = [ln for ln in out if ln.startswith("QUOTA ")]
    assert quota and "used_bytes=850" in quota[0] and "hard_bytes=1000" in quota[0]


def test_allocated_tree_counts_allocated_bytes_and_each_inode_once(tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 100_000)
    os.link(tmp_path / "a", tmp_path / "b")
    (tmp_path / "link").symlink_to(tmp_path / "a")
    total, inodes, by_path, truncated = tr.allocated_tree(tmp_path)
    once = (tmp_path / "a").stat().st_blocks * 512
    assert once <= total < once + 64 * 1024 and inodes == 3 and not truncated and "." in by_path


def test_paths_are_escaped_in_output():
    assert tr.fmt_path("/tmp/a b\n%x") == "/tmp/a%20b%0A%25x"


def test_the_script_is_executable_and_stdlib_only():
    assert SCRIPT.stat().st_mode & stat.S_IXUSR
    assert SCRIPT.read_text().startswith("#!/usr/bin/env python3\n")
    proc = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--root", str(SCRIPT.parent / "no-such-dir")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 3 and proc.stdout.splitlines()[-1].startswith("TMP_REAPER roots=0")


# ── Review fixes: hardened reads, parent-swap immunity, HOS role dirs ─────────────
class _Bound:
    """Fail the test (instead of hanging the suite) if a block takes too long."""

    def __init__(self, seconds=20):
        self.seconds = seconds

    def __enter__(self):
        def boom(*_):
            raise AssertionError(f"reaper blocked for more than {self.seconds}s")

        self._old = signal.signal(signal.SIGALRM, boom)
        signal.alarm(self.seconds)

    def __exit__(self, *exc):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self._old)


@pytest.mark.parametrize("kind", ["fifo", "symlink-to-live-pid"])
def test_lock_file_that_is_a_fifo_or_symlink_neither_hangs_nor_is_followed(tmp_path, reap, kind):
    run = make_run(tmp_path, 1)
    lock = run / ".lock"
    child = None
    if kind == "fifo":
        os.mkfifo(lock)
    else:
        child = spawn(SLEEPER + "  # pytest-marker")
        target = tmp_path / "pid-elsewhere"
        target.write_text(str(child.pid))
        lock.symlink_to(target)
    age(run)
    try:
        with _Bound():
            rc, out = reap("--root", str(tmp_path), "--no-scratch")
    finally:
        if child:
            kill(child)
    # not followed: the pid in the symlink target is never consulted, so the old dir is reaped
    assert any("REAP P legacy-stale" in ln for ln in out), out
    assert not run.exists()


def test_read_lock_pid_is_hardened(tmp_path):
    good = tmp_path / "good"
    good.write_text("1234\n")
    assert tr.read_lock_pid(str(good)) == 1234
    huge = tmp_path / "huge"
    huge.write_text("9" * 100)
    assert tr.read_lock_pid(str(huge)) is None  # only 32 bytes are read
    os.mkfifo(tmp_path / "fifo")
    link = tmp_path / "link"
    link.symlink_to(good)
    with _Bound(5):
        assert tr.read_lock_pid(str(tmp_path / "fifo")) is None
    assert tr.read_lock_pid(str(link)) is None
    assert tr.read_lock_pid(str(tmp_path / "missing")) is None


# Parent-directory swap immunity (the reviewer's poc_swap.py, for every class).
def _swap_for_symlink(path, outside):
    os.rename(path, path + ".moved")
    os.symlink(outside, path)


def _old_tree(path, hours=48.0):
    Path(path, "sub").mkdir(parents=True)
    Path(path, "sub", "precious.txt").write_text("PRECIOUS")
    age(path, hours)


@pytest.mark.parametrize("when", ["after-listing", "before-rename"])
def test_swapping_the_scratch_root_for_a_symlink_deletes_nothing_outside(
    tmp_path, reap, monkeypatch, when
):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    _old_tree(root / "claude" / "victim")
    age(root / "claude")
    _old_tree(outside / "victim")
    age(outside)
    done = []
    scratch = str(root / "claude")
    if when == "after-listing":
        real = tr.scratch_candidates

        def swapping(rb, hos, uid, opened):
            res = real(rb, hos, uid, opened)
            if not done:
                done.append(1)
                _swap_for_symlink(scratch, str(outside))
            return res

        monkeypatch.setattr(tr, "scratch_candidates", swapping)
    else:
        monkeypatch.setattr(
            tr, "_before_remove", lambda p: _swap_for_symlink(scratch, str(outside))
        )
    rc, out = reap("--root", str(root))
    assert (outside / "victim" / "sub" / "precious.txt").exists(), out
    assert any(ln.startswith("SKIP raced") for ln in out), out
    assert not [ln for ln in out if ln.startswith("REAP")]


def test_swapping_the_scratch_root_during_the_walk_is_caught(tmp_path, reap, monkeypatch):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    _old_tree(root / "claude" / "victim")
    age(root / "claude")
    _old_tree(outside / "victim")
    age(outside)
    real_walk = tr.walk_scratch_tree

    def swap_then_walk(*a, **k):
        _swap_for_symlink(str(root / "claude"), str(outside))
        return real_walk(*a, **k)

    monkeypatch.setattr(tr, "walk_scratch_tree", swap_then_walk)
    rc, out = reap("--root", str(root))
    assert (outside / "victim" / "sub" / "precious.txt").exists()
    assert any(ln.startswith("SKIP raced") for ln in out)
    assert (
        Path(str(root / "claude") + ".moved") / "victim"
    ).exists(), "the validated dir is untouched"


def test_swapping_pytest_of_user_for_a_symlink_deletes_nothing_outside(tmp_path, reap, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    make_run(root, 1)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = make_run(outside, 1)
    pd = str(pdir(root))
    monkeypatch.setattr(tr, "_before_remove", lambda p: _swap_for_symlink(pd, str(pdir(outside))))
    rc, out = reap("--root", str(root), "--no-scratch")
    assert victim.exists() and (Path(pd + ".moved") / "pytest-1").exists()
    assert any(ln.startswith("SKIP raced") for ln in out)


def test_swapping_the_root_for_a_symlink_deletes_nothing_outside_class_t(
    tmp_path, reap, monkeypatch
):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    for d in (root, outside):
        f = d / "tmp.AbCdEf1234"
        f.write_text("x")
        age(f)
    monkeypatch.setattr(tr, "_before_remove", lambda p: _swap_for_symlink(str(root), str(outside)))
    rc, out = reap("--root", str(root), "--no-scratch")
    assert (outside / "tmp.AbCdEf1234").exists()
    assert any(ln.startswith("SKIP raced") for ln in out)


def test_swapping_a_role_dir_for_a_symlink_deletes_nothing_outside(tmp_path, reap, monkeypatch):
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    outside = tmp_path / "outside"
    _old_tree(role / "review-copy")
    _old_tree(outside / "review-copy")
    age(role)
    age(outside)
    monkeypatch.setattr(tr, "_before_remove", lambda p: _swap_for_symlink(str(role), str(outside)))
    rc, out = reap("--hos-tmp-root", str(hos))
    assert (outside / "review-copy" / "sub" / "precious.txt").exists()
    assert any(ln.startswith("SKIP raced") for ln in out)


# HOS role dirs: anything older than a day goes (human ruling), except protected names.
def _role_dir(tmp_path, name="Worker"):
    hos = tmp_path / ".tmp"
    return hos, mark(hos / name)


def test_role_dir_children_older_than_a_day_are_reaped(tmp_path, reap):
    hos, role = _role_dir(tmp_path)
    old_dir = role / "review-copy"
    _old_tree(old_dir)
    fresh = role / "fresh-copy"
    _old_tree(fresh, hours=1)
    deep = role / "mixed"
    _old_tree(deep)
    age(deep / "sub" / "precious.txt", 1)
    old_file = role / "notes.log"
    old_file.write_text("n")
    age(old_file)
    rc, out = reap("--hos-tmp-root", str(hos))
    assert not old_dir.exists() and not old_file.exists()
    assert fresh.exists() and deep.exists(), "newest mtime in the tree decides"
    assert hos.exists() and role.exists()
    assert any(ln.startswith("SKIP fresh-deep") for ln in out)


def test_role_dir_protected_names_are_never_reaped(tmp_path, reap):
    hos, role = _role_dir(tmp_path)
    protected = [role / "claude-1000", role / ".claudetmp"]
    for d in protected:
        _old_tree(d)
    _old_tree(role / "claude" / "stale-scratch")
    age(role)
    pt = make_run(role, 1, hours=1)  # fresh class-P run stays
    snaps = {d: snapshot(d) for d in protected}
    for extra in ((), ("--dry-run",), ("--measure",)):
        reap("--hos-tmp-root", str(hos), *extra)
        for d, snap in snaps.items():
            assert snapshot(d) == snap, (d, extra)
    assert pt.exists()
    assert (role / "claude").is_dir() and not (role / "claude" / "stale-scratch").exists()


def test_role_dir_rule_does_not_apply_to_plain_roots(tmp_path, reap):
    plain = tmp_path / "plain"
    plain.mkdir()
    keep = plain / "review-copy"
    _old_tree(keep)
    note = plain / "notes.log"
    note.write_text("n")
    age(note)
    reap("--root", str(plain))
    assert keep.exists() and note.exists()


def test_role_dir_tree_in_use_is_kept(tmp_path, reap):
    hos, role = _role_dir(tmp_path)
    busy = role / "busy"
    _old_tree(busy)
    child = spawn(SLEEPER, cwd=str(busy / "sub"))
    try:
        rc, out = reap("--hos-tmp-root", str(hos))
        assert busy.exists() and any(ln.startswith("SKIP live-proc") for ln in out)
    finally:
        kill(child)
    reap("--hos-tmp-root", str(hos))
    assert not busy.exists()


def test_role_dir_no_scratch_leaves_dirs_alone(tmp_path, reap):
    hos, role = _role_dir(tmp_path)
    d = role / "review-copy"
    _old_tree(d)
    reap("--hos-tmp-root", str(hos), "--no-scratch")
    assert d.exists()


def test_role_dir_symlink_children_are_never_followed(tmp_path, reap):
    hos, role = _role_dir(tmp_path)
    outside = tmp_path / "outside"
    _old_tree(outside)
    (role / "link").symlink_to(outside)
    age(role)
    reap("--hos-tmp-root", str(hos))
    assert (outside / "sub" / "precious.txt").exists() and (role / "link").is_symlink()


def test_claudetmp_lookalikes_survive_every_mode_while_tmp_entries_go(tmp_path, reap):
    hos, role = _role_dir(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    keep = []
    for base in (plain, role):
        _old_tree(base / ".claudetmp" / "signoffs")
        keep.append(base / ".claudetmp")
    empty = role / "tmpabcd1234"
    empty.mkdir()
    age(empty)
    age(role)
    age(plain)
    snaps = {d: snapshot(d) for d in keep}
    for extra in (("--dry-run",), ("--measure",)):
        reap("--root", str(plain), "--hos-tmp-root", str(hos), *extra)
        assert empty.exists()
        for d, snap in snaps.items():
            assert snapshot(d) == snap
    reap("--root", str(plain), "--hos-tmp-root", str(hos))
    assert not empty.exists()
    for d, snap in snaps.items():
        assert snapshot(d) == snap


def test_measure_with_if_low_space_deletes_nothing(tmp_path, reap, monkeypatch):
    run = make_run(tmp_path, 1)
    junk = tmp_path / "tmp.AbCdEf1234"
    junk.write_text("x")
    age(junk)
    tree = make_tree(tmp_path)
    monkeypatch.setattr(tr, "read_user_quota", _FakeQuota(0.95))  # forces "low"
    before = snapshot(tmp_path)
    rc, out = reap("--root", str(tmp_path), "--if-low-space", "--measure")
    assert out[1].startswith("TMP_REAPER_PROBE low")
    assert snapshot(tmp_path) == before and run.exists() and tree.exists()
    assert summary(out)["reaped"] == "0"


# RS4 variants: each detection mechanism must be the only detector for its variant.
def test_rs4_the_flock_probe_alone_detects_a_held_lock(tmp_path, reap, monkeypatch):
    tree = make_tree(tmp_path, "probe-only", "x/keep.txt")
    child = spawn(FLOCKER, str(tree / "x" / "index.lock"), "flock")
    try:
        age(tree)
        monkeypatch.setattr(
            tr, "scan_proc", lambda expired: tr.ProcIndex(available=True, complete=True)
        )
        monkeypatch.setattr(tr, "load_proc_locks", lambda: set())
        rc, out = reap("--root", str(tmp_path))
        assert any(ln.startswith("SKIP held-lock") for ln in out) and tree.exists()
        # mutation: with the probe disabled the same fixture must be reaped, proving sensitivity
        monkeypatch.setattr(tr, "probe_lock_file", lambda path: None)
        rc, out = reap("--root", str(tmp_path), "--dry-run")
        assert any(ln.startswith("WOULD-REAP S") for ln in out)
    finally:
        kill(child)


def test_rs4_an_unopenable_lock_named_file_is_unknown(tmp_path, reap, monkeypatch):
    tree = make_tree(tmp_path, "odd", "x/keep.txt")
    odd = tree / "x" / "thing.lock"
    odd.write_text("")
    age(tree)
    os.chmod(odd, 0)
    try:
        monkeypatch.setattr(
            tr, "scan_proc", lambda expired: tr.ProcIndex(available=True, complete=True)
        )
        rc, out = reap("--root", str(tmp_path))
        if os.access(odd, os.R_OK):
            pytest.skip("permission bits are not enforced for this user")
        assert any(ln.startswith("SKIP unknown") for ln in out) and tree.exists()
    finally:
        os.chmod(odd, 0o600)


# ── Security review: delete authority, ctime-only age, bounded work, host view ───────
def _foreign_project(tmp_path):
    foreign = tmp_path / "otherproj"
    for sub in (".git", "src", "docs"):
        _old_tree(foreign / "Human" / sub)
    age(foreign)
    return foreign


def test_f1_a_foreign_project_that_is_not_registered_is_never_reaped(tmp_path, reap):
    """The reviewer's PoC: --hos-tmp-root steered at another project's directory."""
    foreign = _foreign_project(tmp_path)
    os.chmod(foreign / "Human", 0o755)
    before = snapshot(foreign)
    for extra in ((), ("--dry-run",), ("--measure",)):
        rc, out = reap("--hos-tmp-root", str(foreign), *extra)
        assert rc == 3 and any(ln.startswith("SKIP unregistered") for ln in out), out
        assert not verdicts(out, "REAP") and not verdicts(out, "WOULD-REAP")
    assert snapshot(foreign) == before
    assert stat.S_IMODE((foreign / "Human").stat().st_mode) == 0o755


@pytest.mark.parametrize(
    "contents",
    [
        "hos-tmp-root v3 role=Human\n",
        "hos-tmp-root v2 role=Human nonce=" + "ab" * 32 + "\n",  # an old-style marker
        "anything at all\n",
    ],
)
def test_b2_copying_a_marker_into_another_dir_grants_nothing(tmp_path, reap, contents):
    """B2 PoC: the agent reads a role dir's marker and plants copies in a sibling dir and
    in a clone. Trust lives in the registry, so no copy grants anything."""
    hos = tmp_path / ".tmp"
    real = mark(hos / "Worker")
    (real / ".hos-tmp-root").write_text(contents)
    sibling = hos / "Human"
    _old_tree(sibling / "review-copy")
    (sibling / ".hos-tmp-root").write_text(contents)
    clone = tmp_path / "clones" / "Overseer"
    _old_tree(clone / "src")
    (clone / ".git").mkdir()
    (clone / ".hos-tmp-root").write_text(contents)
    age(hos)
    age(clone)
    before = snapshot(clone)
    rc, out = reap("--hos-tmp-root", str(hos))
    assert any(ln.startswith("SKIP unregistered") for ln in out), out
    assert (sibling / "review-copy" / "sub" / "precious.txt").exists()
    rc, out = reap("--hos-tmp-root", str(tmp_path / "clones"))
    assert snapshot(clone) == before and not verdicts(out, "REAP")


@pytest.mark.parametrize("state", ["deleted", "garbage", "symlink", "fifo", "directory"])
def test_b1_the_marker_is_not_consulted_so_deleting_it_changes_nothing(tmp_path, reap, state):
    """B1 PoC: the agent removes (or mangles) its own marker and keeps a non-HOS child."""
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    marker = role / ".hos-tmp-root"
    marker.unlink()
    if state == "garbage":
        marker.write_text("x\n")
    elif state == "symlink":
        marker.symlink_to(tmp_path)
    elif state == "fifo":
        os.mkfifo(marker)
    elif state == "directory":
        marker.mkdir()
    _old_tree(role / "hog")
    age(role)
    with _Bound():
        rc, out = reap("--hos-tmp-root", str(hos))
    assert rc == 0 and not (role / "hog").exists(), out


def test_a_registry_entry_for_a_replaced_dir_is_unregistered(tmp_path, reap):
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    role.rename(str(role) + ".old")  # replaced: same path, new inode (old one kept alive)
    role.mkdir()
    _old_tree(role / "hog")
    age(role)
    rc, out = reap("--hos-tmp-root", str(hos))
    assert rc == 3 and any(ln.startswith("SKIP unregistered") for ln in out), out
    assert (role / "hog").exists()


def test_an_entry_for_another_role_or_path_does_not_register_a_dir(tmp_path, reap):
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    entry = TEST_REGISTRY[-1]
    TEST_REGISTRY.clear()
    TEST_REGISTRY.append({**entry, "role": "Human"})
    _old_tree(role / "hog")
    age(role)
    assert any(ln.startswith("SKIP unregistered") for ln in reap("--hos-tmp-root", str(hos))[1])
    TEST_REGISTRY[:] = [{**entry, "path": entry["path"] + "-x"}]
    assert any(ln.startswith("SKIP unregistered") for ln in reap("--hos-tmp-root", str(hos))[1])
    assert (role / "hog").exists()


def test_a_full_registry_is_read_normally_and_registered_dirs_are_still_reaped(tmp_path, reap):
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    for i in range(255):  # pad to the resolver's cap with entries for other repos
        TEST_REGISTRY.append(
            {
                "path": f"/gone/{i}/Worker",
                "role": "Worker",
                "repo": f"/r/{i}",
                "st_dev": 1,
                "st_ino": i,
            }
        )
    assert len(TEST_REGISTRY) == 256
    _old_tree(role / "review-copy")
    age(role)
    rc, out = reap("--hos-tmp-root", str(hos))
    assert rc == 0 and not (role / "review-copy").exists(), out


def test_the_real_reader_accepts_a_full_registry_with_and_without_repo(tmp_path, monkeypatch):
    path = tmp_path / "tmp-roots.json"
    entries = [
        {"path": f"/x/{i}/Worker", "role": "Worker", "st_dev": 1, "st_ino": i}
        | ({"repo": f"/r/{i}"} if i % 2 else {})
        for i in range(256)
    ]
    path.write_text(json.dumps({"version": 1, "entries": entries}))
    os.chmod(path, 0o600)
    monkeypatch.setattr(tr, "registry_file", lambda: str(path))
    assert len(_REAL_READ_REGISTRY()) == 256 and path.stat().st_size < 1 << 20


def test_a_missing_registry_means_nothing_is_reaped(tmp_path, reap, monkeypatch):
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    _old_tree(role / "review-copy")
    age(role)
    monkeypatch.setattr(tr, "read_registry", lambda: None)
    before = snapshot(role)
    rc, out = reap("--hos-tmp-root", str(hos))
    assert rc == 3 and any(ln.startswith("SKIP no-registry") for ln in out), out
    assert snapshot(role) == before


@pytest.mark.parametrize("project", [".git", ".claude", "scripts"])
def test_jam_poc_project_looking_children_do_not_stop_reaping(tmp_path, reap, project):
    """An agent that mkdirs .git in its own (registered) role dir cannot jam reaping."""
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    (role / project / "framework").mkdir(parents=True)
    (role / project / "framework" / "config.sh").write_text("x")
    _old_tree(role / "review-copy")
    age(role)
    rc, out = reap("--hos-tmp-root", str(hos))
    assert rc == 0 and not [ln for ln in out if "project-content" in ln], out
    assert not (role / "review-copy").exists(), "old children are reaped"
    assert not (role / project).exists(), "a .git child is an ordinary old child"
    assert (role / ".hos-tmp-root").exists()


def _registry_json(entries=()):
    return json.dumps({"version": 1, "entries": list(entries)})


def test_the_real_registry_reader_is_strict(tmp_path, monkeypatch):
    path = tmp_path / "state" / "tmp-roots.json"
    path.parent.mkdir()
    monkeypatch.setattr(tr, "registry_file", lambda: str(path))
    entry = {"path": "/x/Worker", "role": "Worker", "st_dev": 1, "st_ino": 2}
    assert _REAL_READ_REGISTRY() is None  # missing
    path.write_text(_registry_json([entry]))
    os.chmod(path, 0o600)
    assert _REAL_READ_REGISTRY() == [entry]
    os.chmod(path, 0o640)
    assert _REAL_READ_REGISTRY() is None  # group/other access
    os.chmod(path, 0o600)
    for bad in (
        "not json",
        "[]",
        json.dumps({"version": 2, "entries": []}),
        json.dumps({"version": 1, "entries": [{"path": "/x"}]}),
        json.dumps({"version": 1, "entries": [{**entry, "st_ino": "2"}]}),
    ):
        path.write_text(bad)
        assert _REAL_READ_REGISTRY() is None, bad  # malformed
    path.unlink()
    real = tmp_path / "real-registry"
    real.write_text(_registry_json([entry]))
    os.chmod(real, 0o600)
    path.symlink_to(real)
    assert _REAL_READ_REGISTRY() is None  # never a symlink
    path.unlink()
    os.mkfifo(path)
    with _Bound(5):
        assert _REAL_READ_REGISTRY() is None  # a FIFO neither hangs nor counts


def test_the_registry_path_comes_from_the_passwd_entry_with_no_override(monkeypatch):
    monkeypatch.setenv("HOME", "/nonexistent-home")
    monkeypatch.setenv("HOS_TMP_REGISTRY_FILE", "/nonexistent-override")
    assert tr.registry_file().endswith("/.local/state/hos/tmp-roots.json")
    assert "nonexistent" not in tr.registry_file()
    assert "environ" not in SCRIPT.read_text().split("def registry_file")[1].split("def ")[0]


def test_a_root_that_is_inside_a_git_work_tree_is_refused(tmp_path, reap):
    (tmp_path / ".git").mkdir()
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    _old_tree(role / "review-copy")
    age(role)
    rc, out = reap("--hos-tmp-root", str(hos))
    assert rc == 3 and any(ln.startswith("SKIP root-in-work-tree") for ln in out), out
    assert (role / "review-copy").exists()
    # a .git file (linked worktree) counts too, and so does a .git in the root itself
    (tmp_path / ".git").rmdir()
    (tmp_path / ".git").write_text("gitdir: /x\n")
    assert reap("--hos-tmp-root", str(hos))[0] == 3
    (tmp_path / ".git").unlink()
    (hos / ".git").mkdir()
    assert reap("--hos-tmp-root", str(hos))[0] == 3


def test_a_mis_passed_hos_root_whose_children_are_clones_reaps_nothing(tmp_path, reap):
    hos_root = tmp_path / "HumanOversightSystem"
    for clone in ("Human", "Worker", "Overseer"):
        (hos_root / clone / ".git").mkdir(parents=True)
        _old_tree(hos_root / clone / "src")
        # even a perfectly forged marker (everything an agent can read or write) grants nothing
        (hos_root / clone / ".hos-tmp-root").write_text(f"hos-tmp-root v3 role={clone}\n")
    age(hos_root)
    before = snapshot(hos_root)
    rc, out = reap("--hos-tmp-root", str(hos_root))
    assert rc == 3 and len([ln for ln in out if ln.startswith("SKIP unregistered")]) == 3
    assert snapshot(hos_root) == before


def test_f1_the_marker_itself_is_never_reaped(tmp_path, reap):
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    age(role)
    reap("--hos-tmp-root", str(hos))
    assert (role / ".hos-tmp-root").exists()


def test_claude_prefixed_entries_in_role_dirs_are_never_reaped(tmp_path, reap):
    hos = tmp_path / ".tmp"
    role = mark(hos / "Worker")
    keep = [role / "claude-1000", role / "claude-abc123-cwd"]
    for d in keep:
        _old_tree(d)
    cwdfile = role / "claude-ffee-cwd.txt"
    cwdfile.write_text("x")
    age(role)
    reap("--hos-tmp-root", str(hos))
    assert all(d.exists() for d in keep) and cwdfile.exists()


def test_f2_a_future_mtime_cannot_make_a_tree_unreapable(tmp_path, reap):
    far = 4102444800  # 2100-01-01
    tree = tmp_path / "claude" / "future"
    (tree / "sub").mkdir(parents=True)
    (tree / "sub" / "f").write_text("x")
    run = make_run(tmp_path, 1)
    junk = tmp_path / "tmp.AbCdEf1234"
    junk.write_text("x")
    for base in (tree, run, junk):
        paths = [base] if base.is_file() else [base, *base.rglob("*")]
        for p in paths:
            os.utime(p, (far, far), follow_symlinks=False)
    # no ctime override: the real ctime (now) is what the +48 h clock sees as old
    FAKE_CTIME.clear()
    rc, out = reap("--root", str(tmp_path))
    assert not tree.exists() and not run.exists() and not junk.exists(), out
    assert tr._ts.__name__ == "_fake_ts"  # the seam only overrides registered inodes


def test_f2_age_is_ctime_alone():
    st = SimpleNamespace(st_mtime=4102444800.0, st_ctime=1000.0)
    assert _REAL_TS(st) == 1000.0


_REAL_TS = tr._ts


def test_f3_one_bad_entry_does_not_stop_the_sweep(tmp_path, reap, monkeypatch):
    for name in ("tmp.AAAAAAAAAA", "tmp.BBBBBBBBBB"):
        f = tmp_path / name
        f.write_text("x")
        age(f)
    real = tr.Reaper.handle_t
    calls = []

    def flaky(self, rb, name):
        calls.append(name)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(self, rb, name)

    monkeypatch.setattr(tr.Reaper, "handle_t", flaky)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert rc == 0 and any(ln.startswith("ERROR RuntimeError ") for ln in out), out
    assert len(verdicts(out, "REAP")) == 1 and summary(out)["errors"] == "1"


def test_f3_main_never_leaks_a_traceback(tmp_path, reap, monkeypatch):
    monkeypatch.setattr(tr.Reaper, "run", lambda self: (_ for _ in ()).throw(ValueError("x")))
    rc, out = reap("--root", str(tmp_path))
    assert rc == 1 and out == ["ERROR ValueError -"]


def _deep(base: Path, levels: int) -> None:
    fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for _ in range(levels):
            os.mkdir("d", dir_fd=fd)
            nxt = os.open("d", os.O_RDONLY | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = nxt
    finally:
        os.close(fd)


def test_f3_trees_deeper_than_the_cap_are_refused(tmp_path, reap):
    deep_scratch = tmp_path / "claude" / "deep"
    deep_scratch.mkdir(parents=True)
    _deep(deep_scratch, tr.MAX_TREE_DEPTH + 8)
    run = pdir(tmp_path) / "pytest-1"
    run.mkdir()
    _deep(run, tr.MAX_TREE_DEPTH + 8)
    shallow = make_run(tmp_path, 2)
    with _Bound(60):
        rc, out = reap("--root", str(tmp_path))
    assert len([ln for ln in out if ln.startswith("SKIP too-deep")]) == 2, out
    assert deep_scratch.exists() and run.exists() and not shallow.exists()


def test_f3_a_tree_just_under_the_cap_is_still_reaped(tmp_path, reap):
    tree = tmp_path / "claude" / "ok"
    tree.mkdir(parents=True)
    _deep(tree, tr.MAX_TREE_DEPTH - 8)
    with _Bound(60):
        rc, out = reap("--root", str(tmp_path))
    assert not tree.exists(), out


def _host_view(monkeypatch, *, ino=0xEFFFFFFC, nspid="1234", comm="systemd"):
    real_stat = os.stat

    def fake_stat(p, *a, **k):
        if str(p).endswith("/self/ns/pid"):
            return SimpleNamespace(st_ino=ino)
        return real_stat(p, *a, **k)

    monkeypatch.setattr(os, "stat", fake_stat)
    monkeypatch.setattr(
        tr,
        "_slurp",
        lambda path, limit=0: f"Name:\tx\nNSpid:\t{nspid}\n" if path.endswith("/status") else comm,
    )


def test_f4_only_the_initial_pid_namespace_is_a_host_view(monkeypatch):
    _host_view(monkeypatch)
    assert _REAL_HOST_VIEW() is None
    _host_view(monkeypatch, ino=4026532999)  # a child PID namespace
    assert _REAL_HOST_VIEW() == "no-host-view"
    _host_view(monkeypatch, nspid="1234 5")
    assert _REAL_HOST_VIEW() == "no-host-view"
    _host_view(monkeypatch, comm="bwrap")
    assert _REAL_HOST_VIEW() == "no-host-view"


def test_f4_an_unreadable_namespace_link_fails_safe(monkeypatch):
    def deny(p, *a, **k):
        raise PermissionError(errno.EACCES, "no")

    monkeypatch.setattr(os, "stat", deny)
    assert _REAL_HOST_VIEW() == "no-host-view"


def test_a_user_name_that_is_not_one_path_component_is_refused(tmp_path, reap, monkeypatch):
    for bad in ("a/b", "..", ""):
        monkeypatch.setattr(getpass, "getuser", lambda bad=bad: bad)
        rc, out = reap("--root", str(tmp_path))
        assert rc == 3 and out == [], bad


def test_the_device_boundary_in_class_p_walks(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f").write_text("x")
    dev = os.lstat(tmp_path).st_dev
    assert tr.guard_tree(str(tmp_path), dev, lambda: False) is None
    assert tr.guard_tree(str(tmp_path), dev + 1, lambda: False) == "cross-device"
    assert tr.allocated_tree(tmp_path, dev=dev + 1)[0] == 0
    assert tr.allocated_tree(tmp_path, dev=dev)[0] > 0


def test_without_proc_fd_paths_a_garbage_tree_is_not_reaped(tmp_path, reap, monkeypatch):
    leftover = tmp_path / "garbage-hos-1234"
    (leftover / "z").mkdir(parents=True)
    age(leftover)
    real_isdir = os.path.isdir
    monkeypatch.setattr(
        os.path, "isdir", lambda p: False if str(p) == "/proc/self/fd" else real_isdir(p)
    )
    rc, out = reap("--root", str(tmp_path))
    assert any(ln.startswith("SKIP no-fd-paths") for ln in out) and leftover.exists()


# ── Second-review fixes ─────────────────────────────────────────────────────────
def test_a_relative_or_symlinked_hos_tmp_root_argument_still_matches_the_registry(
    tmp_path, reap, monkeypatch
):
    real = tmp_path / "real"
    role = mark(real / ".tmp" / "Worker")
    _old_tree(role / "review-copy")
    age(role)
    (tmp_path / "alias").symlink_to(real)  # a symlinked ANCESTOR of the root
    monkeypatch.chdir(real)
    rc, out = reap("--hos-tmp-root", ".tmp")  # relative
    assert rc == 0 and not (role / "review-copy").exists(), out
    _old_tree(role / "again")
    age(role)
    rc, out = reap("--hos-tmp-root", str(tmp_path / "alias" / ".tmp"))
    assert rc == 0 and not (role / "again").exists(), out


def test_a_hos_tmp_root_that_is_itself_a_symlink_is_refused(tmp_path, reap):
    real = tmp_path / "real-tmp"
    role = mark(real / "Worker")
    _old_tree(role / "review-copy")
    age(role)
    (tmp_path / ".tmp").symlink_to(real)
    rc, out = reap("--hos-tmp-root", str(tmp_path / ".tmp"))
    assert rc == 3 and any(ln.startswith("SKIP root-invalid") for ln in out), out
    assert (role / "review-copy").exists()


def test_a_dangling_symlink_that_vanishes_before_the_unlink_is_raced_not_an_error(
    tmp_path, reap, monkeypatch
):
    pd = pdir(tmp_path)
    (pd / "pytest-current").symlink_to(tmp_path / "nowhere")
    real_unlink = os.unlink

    def vanish(path, *a, **k):
        if str(path) == "pytest-current":
            real_unlink(path, *a, **k)  # a concurrent cleaner won
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(os, "unlink", vanish)
    rc, out = reap("--root", str(tmp_path), "--no-scratch")
    assert any(ln.startswith("SKIP raced") for ln in out), out
    assert summary(out)["errors"] == "0" and not [ln for ln in out if ln.startswith("ERROR")]


def test_an_rmtree_that_is_not_the_fd_based_variant_reaps_nothing(tmp_path, reap, monkeypatch):
    run = make_run(tmp_path, 1)
    tree = make_tree(tmp_path)
    leftover = tmp_path / "claude" / "garbage-hos-1234"
    (leftover / "z").mkdir(parents=True)
    age(leftover)
    real = shutil.rmtree

    def plain_rmtree(*a, **k):  # no avoids_symlink_attacks attribute
        return real(*a, **k)

    monkeypatch.setattr(shutil, "rmtree", plain_rmtree)
    rc, out = reap("--root", str(tmp_path))
    assert len([ln for ln in out if ln.startswith("SKIP unsafe-rmtree")]) == 3, out
    assert run.exists() and tree.exists() and leftover.exists()
    assert tr.Reaper._rmtree_is_safe() is False
    monkeypatch.setattr(shutil, "rmtree", real)
    assert tr.Reaper._rmtree_is_safe() is True or sys.platform == "darwin"
