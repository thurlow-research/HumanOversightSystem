#!/usr/bin/env python3
"""tmp_reaper.py -- machine-level temp reaper (#2054, Layer 2 backstop).

Removes what in-run cleanup cannot: pytest run dirs of killed sessions, leaked
``tmp*`` entries, stale agent scratch trees. It sweeps explicit roots only
(``--root``, ``--hos-tmp-root``); there is no config discovery.

Safety model (technical design section 5, binding):
  * One uniform minimum age, 24 h, raise-only. Age alone never deletes: every
    removal also needs a non-age signal (dead flock on a verified inode, lock-free
    finished dir, class-T shape, whole-tree class-S walk) AND a live-process veto.
  * Class order is P (pytest run dirs), T (top-level tmp* orphans), S (stale trees,
    on by default, ``--no-scratch`` opts out). Class S refuses without a host view
    of processes and locks; it never runs git and reads no git metadata.
  * Removal is rename-to-garbage with dev/ino re-checks before and after, then a
    symlink-safe rmtree. Only entries owned by the current uid are touched.
  * Never runs as root. Never spawns a subprocess or calls exec*.
  * ``.claudetmp/`` and ``claude-*`` entries are never touched.
  * Every directory it deletes from is opened once (O_DIRECTORY|O_NOFOLLOW) and all
    child operations go through that fd, so swapping a parent *path* for a symlink
    after validation cannot redirect a deletion; a swap reports ``SKIP raced``.
  * Under ``--hos-tmp-root`` role dirs only (human ruling "anything older than a day
    goes"), ANY top-level child older than 24 h is a candidate, judged like class S by
    the newest ctime in its tree. Not applied to ``--root`` dirs such as /tmp. A role dir
    is trusted only if it is registered (path, role and inode) in the machine registry
    ``~/.local/state/hos/tmp-roots.json`` (written by bootstrap/lib/hos_tmp_root.py; never
    granted to a sandbox, so it cannot be forged from one). Nothing inside the dir is
    consulted. No registry: nothing is reaped.

Output lines (design 5.5): TMP_REAPER_RUN, TMP_REAPER_PROBE, REAP, WOULD-REAP, SKIP,
ERROR, WARN large-unowned, the final TMP_REAPER summary, and (--measure, or a
quota-triggered --if-low-space) ``QUOTA root=<dir> used_bytes=<n> hard_bytes=<n|->``:
the real per-user quota of that mount via quotactl_fd, where the platform supports it.

Exit codes: 0 completed (including skips, per-entry errors and truncation),
2 usage error, 3 no valid root or running as root. Callers treat any non-zero
as a warning, never as a failure. Stdlib only; Python 3.10+.
"""

from __future__ import annotations

import argparse
import bisect
import errno
import fcntl
import getpass
import json
import math
import os
import pwd
import re
import shutil
import stat
import struct
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

# ── Constants (protected: changing one is a code change with a test) ──────────
MIN_AGE_HOURS = 24.0
DEFAULT_MAX_SECONDS = 20.0
SCRATCH_ROOTS = ("claude",)  # relative to each root; /tmp/claude/ in practice
SCRATCH_MAX_INODES = 1_000_000
MAX_TREE_DEPTH = 512  # deeper trees are refused (SKIP too-deep), never walked or removed
HOS_MARKER = ".hos-tmp-root"  # written by bootstrap/lib/hos_tmp_root.py in role dirs it creates
HOST_PID_NS_INO = 0xEFFFFFFC  # the initial PID namespace
LARGE_UNOWNED_BYTES = 100 * 1024 * 1024
PROBE_BYTES = 64 * 1024
QUOTA_LOW_RATIO = 0.8
PROC_ROOT = "/proc"

ROLE_DIR_RE = re.compile(r"^(Worker|Overseer|Human|Local)$")
PYTEST_RUN_RE = re.compile(r"^pytest-\d+$")
T_PATTERNS = (
    re.compile(r"^tmp[a-z0-9_]{8}$"),
    re.compile(r"^tmp[a-z0-9_]{8}[A-Za-z0-9_.-]{1,32}$"),
    re.compile(r"^tmp\.[A-Za-z0-9]{10}$"),
)
OTHER_CLASS_RE = re.compile(r"^(pytest-of-|garbage-(?!hos-)|tmp|hos-)")
GARBAGE_HOS_RE = re.compile(r"^garbage-hos-")
SESSION_DIR_RE = re.compile(r"^claude-")  # Claude Code keeps claude-<uid> and claude-<hex>-cwd
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
LOCK_FILE_RE = re.compile(r"(\.lock|\.lck)$|^(\.hos-live|LOCK|lock)$")
LIVE_RECORD_RE = re.compile(rb"^pid=(\d+) start=(\d+(?:\.\d+)?) dev=(\d+) ino=(\d+)\n?$")
PROC_LOCK_RE = re.compile(
    r"^\d+:\s+(?:->\s+)?\S+\s+\S+\s+\S+\s+-?\d+\s+"
    r"([0-9a-fA-F]+):([0-9a-fA-F]+):(\d+)\s+\S+\s+\S+\s*$"
)

# quotactl_fd (Linux 5.14+) syscall number by machine; unlisted machines fail soft.
QUOTACTL_FD_SYSCALL = {"x86_64": 443, "aarch64": 443, "riscv64": 443}
_Q_GETQUOTA = 0x800007
_USRQUOTA = 0
_QIF_BLIMITS = 1
_QIF_SPACE = 2

# Test seam: called with the tree path between the walk and the removal (RS9).
_before_remove: Optional[Callable[[str], None]] = None


# ── Pure data ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Decision:
    action: str  # REAP | SKIP | NEED | HANDOFF
    reason: str


@dataclass
class Policy:
    uid: int
    age_s: float
    scratch_active: bool = False
    dry_run: bool = False


@dataclass
class ProcIndex:
    """Resolved cwd/root/exe/fd targets of every readable process (own pid excluded)."""

    available: bool = False
    complete: bool = True
    n_unreadable: int = 0
    targets: frozenset = frozenset()
    pytest_pids: frozenset = frozenset()
    _sorted: list = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self._sorted = sorted(self.targets)

    def hit_exact(self, path: str) -> bool:
        return path in self.targets

    def hit_under(self, path: str) -> bool:
        if path in self.targets:
            return True
        prefix = path.rstrip("/") + "/"
        i = bisect.bisect_left(self._sorted, prefix)
        return i < len(self._sorted) and self._sorted[i].startswith(prefix)


@dataclass
class PFacts:
    path: str
    name: str
    uid: int
    quiet_ts: float
    is_garbage: bool = False
    has_hos_live: bool = False
    has_lock: bool = False
    lock_pid: Optional[int] = None
    probe: Optional[str] = None  # None = not probed | dead | live | unknown
    probe_fd: Optional[int] = None
    proc: Optional[ProcIndex] = None
    bd: Any = None  # the fd-bound parent, used to reach children safely


@dataclass
class TFacts:
    path: str
    uid: int
    kind: str  # file | empty-dir | dir | special
    is_symlink: bool
    quiet_ts: float
    proc: Optional[ProcIndex] = None


@dataclass
class WalkResult:
    problem: Optional[str]
    newest: float = 0.0
    nbytes: int = 0
    inodes: int = 0


@dataclass
class SFacts:
    path: str
    uid: int
    same_dev: bool
    excluded: Optional[str]  # other-class | session-dir | None
    is_self: bool
    top_quiet_ts: float
    proc: Optional[ProcIndex] = None
    walk: Optional[WalkResult] = None


@dataclass
class Cand:
    path: str
    name: str
    parent: str
    shape: int  # 1 = scratch-root child, 2 = non-empty tmp* in a root, 3 = HOS role-dir child
    garbage: bool = False
    bd: Any = None  # the validated, fd-bound parent directory


_UNSET = object()


class ScratchDisabled(Exception):
    """Class S cannot run safely this invocation; ``args[0]`` is the reason."""


# ── Pure decisions ─────────────────────────────────────────────────────────────
def _veto(
    path: str,
    proc: Optional[ProcIndex],
    reason: str,
    *,
    lock_pid: Optional[int] = None,
    exact: bool = False,
    hit_reason: str = "live-proc",
) -> Decision:
    """The live-process veto shared by every class. Absence of /proc removes the
    veto but never creates a REAP by itself."""
    if proc is None:
        return Decision("NEED", "proc")
    if proc.available:
        if lock_pid is not None and lock_pid in proc.pytest_pids:
            return Decision("SKIP", "live-proc")
        if proc.hit_exact(path) if exact else proc.hit_under(path):
            return Decision("SKIP", hit_reason)
        if not proc.complete:
            return Decision("SKIP", "proc-scan-incomplete")
    return Decision("REAP", reason)


def decide(f: PFacts, now: float, policy: Policy) -> Decision:
    """Class P decision table (design 5.3.2). Pure; NEED asks the caller for a fact."""
    if f.uid != policy.uid:
        return Decision("SKIP", "not-owned-or-symlink")
    if now - f.quiet_ts < policy.age_s:
        return Decision("SKIP", "fresh")
    if f.is_garbage:
        reason = "garbage"
    elif f.has_hos_live:
        if f.probe is None:
            return Decision("NEED", "probe")
        if f.probe == "unknown":
            return Decision("SKIP", "unknown")
        if f.probe == "live":
            return Decision("SKIP", "live-flock")
        reason = "dead-flock" if f.has_lock else "finished"
    elif f.has_lock:
        reason = "legacy-stale"
    else:
        reason = "finished"
    return _veto(f.path, f.proc, reason, lock_pid=f.lock_pid)


def decide_t(f: TFacts, now: float, policy: Policy) -> Decision:
    """Class T decision (design 5.4). Non-empty dirs are handed to class S."""
    if f.uid != policy.uid or f.is_symlink:
        return Decision("SKIP", "not-owned-or-symlink")
    if f.kind == "special":
        return Decision("SKIP", "special")
    if f.kind == "dir":
        return Decision("HANDOFF" if policy.scratch_active else "SKIP", "non-empty")
    if now - f.quiet_ts < policy.age_s:
        return Decision("SKIP", "fresh")
    reason = "empty-dir" if f.kind == "empty-dir" else "file"
    return _veto(f.path, f.proc, reason, exact=True, hit_reason="open")


def decide_scratch(f: SFacts, now: float, policy: Policy) -> Decision:
    """Class S per-tree decision (design 5.7.4), cheap checks first. Pure."""
    if f.uid != policy.uid or not f.same_dev:
        return Decision("SKIP", "not-owned-or-foreign-dev")
    if f.excluded:
        return Decision("SKIP", f.excluded)
    if f.is_self:
        return Decision("SKIP", "self")
    if now - f.top_quiet_ts < policy.age_s:
        return Decision("SKIP", "fresh")
    if f.proc is None:
        return Decision("NEED", "proc")
    if f.proc.available and f.proc.hit_under(f.path):
        return Decision("SKIP", "live-proc")
    if f.walk is None:
        return Decision("NEED", "walk")
    if f.walk.problem:
        return Decision("SKIP", f.walk.problem)
    return Decision("REAP", "scratch-stale")


def parse_proc_locks(text: str) -> set:
    """Parse /proc/locks into {(major, minor, inode)}. Major/minor are HEX, the
    inode decimal. Any unparseable line raises ValueError (class S then refuses)."""
    out = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        m = PROC_LOCK_RE.match(line)
        if not m:
            raise ValueError(f"unparseable /proc/locks line: {line!r}")
        out.add((int(m.group(1), 16), int(m.group(2), 16), int(m.group(3))))
    return out


def name_exclusion(c: Cand) -> Optional[str]:
    """Name-based class-S exclusions (design 5.7.2 / 5.7.3 layers 1-2)."""
    if c.shape in (1, 3) and SESSION_DIR_RE.match(c.name):
        return "session-dir"
    if c.shape == 1 and OTHER_CLASS_RE.match(c.name):
        return "other-class"
    if c.shape == 3 and c.name.startswith("pytest-of-"):
        return "other-class"
    return None


def parse_dqblk(raw: bytes) -> Optional[tuple]:
    """(used_bytes, hard_limit_bytes) from a struct if_dqblk; hard 0 = no limit."""
    if len(raw) < 72:
        return None
    bhard, _bsoft, cur, _ih, _is, _ci, _bt, _it, valid = struct.unpack("8QI4x", raw[:72])
    if not valid & _QIF_SPACE:
        return None
    return cur, (bhard * 1024 if valid & _QIF_BLIMITS else 0)


def read_user_quota(path: str) -> Optional[tuple]:
    """Real per-user quota of the mount holding ``path`` via quotactl_fd (works on
    tmpfs without root). Returns (used_bytes, hard_bytes) or None. Fails soft: any
    unsupported platform, architecture, kernel or filesystem yields None."""
    if not sys.platform.startswith("linux"):
        return None
    nr = QUOTACTL_FD_SYSCALL.get(os.uname().machine)
    if nr is None:
        return None
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        buf = ctypes.create_string_buffer(72)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            cmd = (_Q_GETQUOTA << 8) | _USRQUOTA
            rc = libc.syscall(
                ctypes.c_long(nr),
                ctypes.c_int(fd),
                ctypes.c_uint(cmd),
                ctypes.c_uint(os.getuid()),
                buf,
            )
        finally:
            os.close(fd)
    except (OSError, AttributeError, ImportError, ValueError, TypeError):
        return None
    return parse_dqblk(buf.raw) if rc == 0 else None


# ── Filesystem helpers ─────────────────────────────────────────────────────────
def fmt_path(path: str) -> str:
    """One greppable token: bytes outside 0x21-0x7e (and %) are %XX-escaped."""
    out = []
    for b in os.fsencode(path):
        out.append(chr(b) if 0x21 <= b <= 0x7E and b != 0x25 else "%%%02X" % b)
    return "".join(out)


def _ts(st: os.stat_result) -> float:
    """The age signal: st_ctime ALONE. A user can set mtime (``touch -d 2100`` would make
    a tree permanently un-reapable) but cannot set ctime, and ctime is >= mtime on every
    write."""
    return st.st_ctime


def _excname(exc: BaseException) -> str:
    """ERROR token for any exception: the errno name for OSError, else the class name."""
    return _errname(exc) if isinstance(exc, OSError) else type(exc).__name__


def _errname(exc: BaseException) -> str:
    return errno.errorcode.get(getattr(exc, "errno", None) or 0, "EIO")


def _slurp(path: str, limit: int = 1 << 20) -> str:
    with open(path, "rb") as fh:
        return fh.read(limit).decode("utf-8", "replace")


def allocated_tree(
    root,
    top_depth: int = 2,
    expired: Optional[Callable[[], bool]] = None,
    dev: Optional[int] = None,
):
    """Allocated bytes (st_blocks*512, what a tmpfs quota counts), inode count and
    per-subpath bytes (depth <= top_depth). Each inode counts once; symlinks are
    never followed. Iterative (no recursion limit). With ``dev``, entries on another
    device (a mount point inside the tree) are not counted or descended. Returns
    (total, inodes, by_path, truncated)."""
    root = str(root)
    seen: set = set()
    totals: list = []
    parents: list = []
    paths: list = []
    depths: list = []
    stack = [(root, 0, -1)]
    truncated = False
    n = 0
    while stack:
        path, depth, parent = stack.pop()
        n += 1
        if expired is not None and n % 256 == 0 and expired():
            truncated = True
            break
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if dev is not None and st.st_dev != dev:
            continue
        key = (st.st_dev, st.st_ino)
        if key in seen:
            continue
        seen.add(key)
        idx = len(totals)
        totals.append(st.st_blocks * 512)
        parents.append(parent)
        paths.append(path)
        depths.append(depth)
        if stat.S_ISDIR(st.st_mode):
            try:
                with os.scandir(path) as it:
                    names = [e.name for e in it]
            except OSError:
                names = []
            stack.extend((os.path.join(path, nm), depth + 1, idx) for nm in names)
    for i in range(len(totals) - 1, 0, -1):
        if parents[i] >= 0:
            totals[parents[i]] += totals[i]
    by_path = {
        os.path.relpath(paths[i], root): totals[i]
        for i in range(len(totals))
        if depths[i] <= top_depth
    }
    return (totals[0] if totals else 0), len(seen), by_path, truncated


def scan_proc(expired: Callable[[], bool]) -> ProcIndex:
    """Index every readable process's cwd/root/exe/fd targets. ``complete`` means
    only that the scan was not cut short by the time budget. Per-process
    EACCES/ENOENT/ESRCH are tolerated and counted in n_unreadable."""
    try:
        names = os.listdir(PROC_ROOT)
    except OSError:
        return ProcIndex(available=False)
    me = os.getpid()
    targets: set = set()
    pytest_pids: set = set()
    unreadable = 0
    complete = True
    for name in sorted((n for n in names if n.isdigit()), key=int):
        if expired():
            complete = False
            break
        pid = int(name)
        if pid == me:
            continue
        base = f"{PROC_ROOT}/{pid}"
        bad = False
        links = []
        for link in ("cwd", "root", "exe"):
            try:
                links.append(os.readlink(f"{base}/{link}"))
            except OSError:
                if link == "cwd":
                    bad = True
        try:
            for fd in os.listdir(f"{base}/fd"):
                try:
                    links.append(os.readlink(f"{base}/fd/{fd}"))
                except OSError:
                    pass
        except OSError:
            bad = True
        unreadable += bad
        for t in links:
            if t.startswith("/"):
                targets.add(t[: -len(" (deleted)")] if t.endswith(" (deleted)") else t)
        try:
            with open(f"{base}/cmdline", "rb") as fh:
                if b"pytest" in fh.read(4096):
                    pytest_pids.add(pid)
        except OSError:
            pass
    return ProcIndex(True, complete, unreadable, frozenset(targets), frozenset(pytest_pids))


def probe_hos_live(path: str) -> tuple:
    """Safe ``.hos-live`` probe (design 5.3.1). Returns (verdict, fd): 'dead' keeps
    the flock held on ``fd`` (caller closes); 'live' / 'unknown' return fd None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return "unknown", None
    keep = False
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            return "unknown", None
        m = LIVE_RECORD_RE.match(os.read(fd, 256))
        if not m or int(m.group(3)) != st.st_dev or int(m.group(4)) != st.st_ino:
            return "unknown", None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            return ("live" if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN) else "unknown"), None
        keep = True
        return "dead", fd
    except OSError:
        return "unknown", None
    finally:
        if not keep:
            os.close(fd)


def probe_lock_file(path: str) -> Optional[str]:
    """Probe a lock-named file inside a class-S tree: 'held-lock', 'unknown' or None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return "unknown"
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None
    except OSError as exc:
        return "held-lock" if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN) else "unknown"
    finally:
        os.close(fd)


def walk_scratch_tree(
    top: str,
    *,
    tree_dev: int,
    uid: int,
    now: float,
    age_s: float,
    locks: set,
    expired: Callable[[], bool],
) -> WalkResult:
    """Bounded whole-tree walk (design 5.7.4 step 5). Stops at the first failing
    entry; a tree is never partly judged. Age is the newest timestamp in the tree.
    Symlinks are lstat'ed only, never followed. Nothing in .git is parsed."""
    seen: set = set()
    nbytes = 0
    newest = 0.0
    count = 0
    try:
        st0 = os.lstat(top)
    except OSError:
        return WalkResult("unreadable")
    seen.add((st0.st_dev, st0.st_ino))
    nbytes += st0.st_blocks * 512
    stack = [(top, 0)]
    while stack:
        d, depth = stack.pop()
        if expired():
            return WalkResult("walk-truncated", newest, nbytes, count)
        try:
            it = os.scandir(d)
        except OSError:
            return WalkResult("unreadable", newest, nbytes, count)
        with it:
            for entry in it:
                count += 1
                if count > SCRATCH_MAX_INODES:
                    return WalkResult("walk-truncated", newest, nbytes, count)
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    return WalkResult("unreadable", newest, nbytes, count)
                ts = _ts(st)
                newest = max(newest, ts)
                if now - ts < age_s:
                    return WalkResult("fresh-deep", newest, nbytes, count)
                if st.st_uid != uid:
                    return WalkResult("foreign-owned", newest, nbytes, count)
                if st.st_dev != tree_dev:
                    return WalkResult("cross-device", newest, nbytes, count)
                mode = st.st_mode
                if (
                    stat.S_ISSOCK(mode)
                    or stat.S_ISFIFO(mode)
                    or stat.S_ISCHR(mode)
                    or stat.S_ISBLK(mode)
                ):
                    return WalkResult("special", newest, nbytes, count)
                name = entry.name
                is_dir = stat.S_ISDIR(mode)
                if (is_dir and name == "scratchpad") or (depth + 1 <= 3 and UUID_RE.match(name)):
                    return WalkResult("session-like", newest, nbytes, count)
                if (os.major(st.st_dev), os.minor(st.st_dev), st.st_ino) in locks:
                    return WalkResult("held-lock", newest, nbytes, count)
                if stat.S_ISREG(mode) and LOCK_FILE_RE.search(name):
                    verdict = probe_lock_file(entry.path)
                    if verdict:
                        return WalkResult(verdict, newest, nbytes, count)
                key = (st.st_dev, st.st_ino)
                if key not in seen:
                    seen.add(key)
                    nbytes += st.st_blocks * 512
                if is_dir:
                    if depth + 1 >= MAX_TREE_DEPTH:
                        return WalkResult("too-deep", newest, nbytes, count)
                    stack.append((entry.path, depth + 1))
    return WalkResult(None, newest, nbytes, count)


def guard_tree(top: str, dev: int, expired: Callable[[], bool]) -> Optional[str]:
    """Pre-removal guard for class P / garbage trees: None when the tree is safe to
    hand to rmtree, else 'too-deep' (deeper than MAX_TREE_DEPTH), 'cross-device' (a mount
    point inside), 'unreadable' or 'walk-truncated'. Iterative, never follows symlinks."""
    stack = [(top, 0)]
    while stack:
        d, depth = stack.pop()
        if expired():
            return "walk-truncated"
        try:
            it = os.scandir(d)
        except OSError:
            return "unreadable"
        with it:
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    return "unreadable"
                if st.st_dev != dev:
                    return "cross-device"
                if stat.S_ISDIR(st.st_mode):
                    if depth + 1 >= MAX_TREE_DEPTH:
                        return "too-deep"
                    stack.append((entry.path, depth + 1))
    return None


def check_host_view() -> Optional[str]:
    """Reason class S must refuse, or None. Needs the host PID namespace view
    because /proc/locks is namespace-filtered; evaluated BEFORE /proc/locks."""
    try:
        # A process in a child PID namespace cannot see every process or lock. The
        # initial PID namespace has the fixed inode number 0xEFFFFFFC.
        if os.stat(f"{PROC_ROOT}/self/ns/pid").st_ino != HOST_PID_NS_INO:
            return "no-host-view"
        status = _slurp(f"{PROC_ROOT}/self/status")
        comm = _slurp(f"{PROC_ROOT}/1/comm").strip()
    except OSError:
        return "no-host-view"
    m = re.search(r"^NSpid:\s*(.*)$", status, re.M)
    if not m or len(m.group(1).split()) != 1 or comm == "bwrap":
        return "no-host-view"
    return None


def load_proc_locks() -> set:
    try:
        text = _slurp(f"{PROC_ROOT}/locks")
    except OSError as exc:
        raise ScratchDisabled("no-locks-view") from exc
    try:
        return parse_proc_locks(text)
    except ValueError as exc:
        raise ScratchDisabled("locks-unparseable") from exc


def default_roots(environ) -> list:
    tmpdir = environ.get("TMPDIR", "")
    return [tmpdir if tmpdir else "/tmp"]


def _is_empty_dir(path: str) -> Optional[bool]:
    try:
        with os.scandir(path) as it:
            return next(it, None) is None
    except OSError:
        return None


def _is_t_name(name: str) -> bool:
    return any(p.match(name) for p in T_PATTERNS)


def hos_child_name(name: str) -> bool:
    """A role-dir child that the human-ruled "anything older than a day goes" rule may
    reap (design 8.6 rule 1): everything except pytest-of-* (class P), Claude Code's
    own claude-* dirs, the claude scratch root itself, and .claudetmp."""
    return not (
        name.startswith("pytest-of-")
        or SESSION_DIR_RE.match(name)
        or name in SCRATCH_ROOTS
        or name == ".claudetmp"
        or name == HOS_MARKER
    )


def read_lock_pid(path: str) -> Optional[int]:
    """The pid recorded in a pytest ``.lock``. Hardened: a FIFO, a symlink or a foreign
    file at that name never blocks or is followed; any problem yields None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
            return None
        txt = os.read(fd, 32).strip()
    except OSError:
        return None
    finally:
        os.close(fd)
    return int(txt) if txt.isdigit() and len(txt) <= 10 else None


class BoundDir:
    """A directory opened once (O_DIRECTORY|O_NOFOLLOW). Every lstat, rename, unlink and
    rmdir of a child goes through this fd, and children are read and walked through
    /proc/self/fd/<fd> where it exists, so swapping the directory's *path* for a symlink
    after validation cannot redirect an operation (the swap-TOCTOU hardening).
    ``intact()`` additionally detects that the path no longer names this directory."""

    def __init__(self, path: str, parent: Optional["BoundDir"] = None, name: str = ""):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        self.path = path
        self.fd: int = os.open(name, flags, dir_fd=parent.fd) if parent else os.open(path, flags)
        try:
            self.st = os.fstat(self.fd)
        except OSError:
            os.close(self.fd)
            raise
        self.id = (self.st.st_dev, self.st.st_ino)
        self.fd_paths = os.path.isdir("/proc/self/fd")

    def open_child(self, name: str) -> "BoundDir":
        return BoundDir(os.path.join(self.path, name), self, name)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def intact(self) -> bool:
        try:
            st = os.lstat(self.path)
        except OSError:
            return False
        return (st.st_dev, st.st_ino) == self.id and os.path.realpath(self.path) == self.path

    def lstat(self, name: str) -> os.stat_result:
        return os.lstat(name, dir_fd=self.fd)

    def names(self) -> list:
        return sorted(os.listdir(self.fd))

    def spath(self, name: str) -> str:
        """A path to ``name`` that cannot be redirected by swapping this dir's path."""
        base = f"/proc/self/fd/{self.fd}" if self.fd_paths else self.path
        return os.path.join(base, name)

    def child_path(self, name: str) -> str:
        return os.path.join(self.path, name)


def _lstat_or_none(bd: BoundDir, name: str) -> Optional[os.stat_result]:
    try:
        return bd.lstat(name)
    except OSError:
        return None


def scratch_candidates(rb: BoundDir, hos: bool, uid: int, opened: list) -> tuple:
    """Class-S candidates under one bound root (design 5.7.2). Shape 1: real-dir children
    of each scratch root. Shape 2: non-empty tmp* dirs directly in the root. Shape 3 (HOS
    role dirs only, human ruling): any other top-level dir. Also ``garbage-hos-*``
    leftovers. Returns (Cand list, invalid scratch-root paths); BoundDirs opened here are
    appended to ``opened`` for the caller to close."""
    out: list = []
    invalid: list = []
    for sname in SCRATCH_ROOTS:
        spath = os.path.join(rb.path, sname)
        try:
            sb = rb.open_child(sname)
        except FileNotFoundError:
            continue
        except OSError:
            invalid.append(spath)
            continue
        opened.append(sb)
        if sb.st.st_uid != uid or sb.st.st_dev != rb.st.st_dev or os.path.realpath(spath) != spath:
            invalid.append(spath)
            continue
        try:
            names = sb.names()
        except OSError:
            continue
        for name in names:
            st = _lstat_or_none(sb, name)
            if st is not None and stat.S_ISDIR(st.st_mode):
                garbage = bool(GARBAGE_HOS_RE.match(name))
                out.append(Cand(os.path.join(spath, name), name, spath, 1, garbage, sb))
    try:
        names = rb.names()
    except OSError:
        return out, invalid
    for name in names:
        garbage = bool(GARBAGE_HOS_RE.match(name))
        if hos:
            if not garbage and not hos_child_name(name):
                continue
        elif not garbage and not _is_t_name(name):
            continue
        st = _lstat_or_none(rb, name)
        if st is None or not stat.S_ISDIR(st.st_mode) or st.st_uid != uid:
            continue
        path = os.path.join(rb.path, name)
        if garbage:
            out.append(Cand(path, name, rb.path, 2, True, rb))
        elif hos:
            out.append(Cand(path, name, rb.path, 3, False, rb))
        elif _is_empty_dir(rb.spath(name)) is False:
            out.append(Cand(path, name, rb.path, 2, False, rb))
    return out, invalid


def count_scratch_trees(rb: BoundDir, hos: bool, uid: int) -> int:
    opened: list = []
    try:
        cands, _bad = scratch_candidates(rb, hos, uid, opened)
    finally:
        for b in opened:
            b.close()
    return sum(1 for c in cands if not c.garbage and name_exclusion(c) is None)


def registry_file() -> str:
    """~/.local/state/hos/tmp-roots.json, from the passwd entry (not $HOME). No env or
    flag override exists: the reaper reads exactly this file."""
    return os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".local/state/hos/tmp-roots.json")


def read_registry() -> Optional[list]:
    """The registered role dirs [{path, role, st_dev, st_ino}], or None when the registry
    is missing, unreadable, a symlink/FIFO, group/other-accessible, not ours or malformed
    (fail safe: no registry means no role dir is trusted, nothing is reaped)."""
    try:
        fd = os.open(registry_file(), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
            return None
        raw = os.read(fd, 1 << 20)
    except OSError:
        return None
    finally:
        os.close(fd)
    try:
        doc = json.loads(raw)
        entries = doc["entries"]
        if doc["version"] != 1 or not isinstance(entries, list):
            return None
        for e in entries:
            if not (
                isinstance(e["path"], str)
                and isinstance(e["role"], str)
                and isinstance(e["st_dev"], int)
                and isinstance(e["st_ino"], int)
            ):
                return None
    except (ValueError, KeyError, TypeError):
        return None
    return entries


def hos_root_problem(path: str) -> Optional[str]:
    """Defence in depth: refuse an --hos-tmp-root that is, or is inside, a git work tree
    (a `.git` in the root or any ancestor). The root is the parent of every role dir, so
    this is also the "role dir's parent contains .git" check. A mis-passed HOS_ROOT whose
    children are clones is stopped by the registry, not here."""
    cur = os.path.realpath(path)
    while True:
        if os.path.lexists(os.path.join(cur, ".git")):
            return "root-in-work-tree"
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def _role_problem_at(path: str, registry: Optional[list]) -> Optional[str]:
    try:
        bd = BoundDir(path)
    except OSError:
        return "not-a-role-dir"
    try:
        return role_dir_problem(bd, registry)
    finally:
        bd.close()


def role_dir_problem(bd: "BoundDir", registry: Optional[list]) -> Optional[str]:
    """Why an HOS role dir must not be reaped from, or None. The sole authority is the
    machine registry (~/.local/state/hos/tmp-roots.json, outside anything a sandbox can
    read or write): the role dir must be registered with exactly this path, role name and
    (st_dev, st_ino). Nothing inside the dir is consulted, so an agent can neither forge
    trust by writing files nor lose it by deleting the informational marker. There is no
    content heuristic here either: a `.git` child of a registered role dir is an ordinary
    child; project content is checked at first adoption by the resolver only."""
    if registry is None:
        return "no-registry"
    for e in registry:
        if (
            e["path"] == bd.path
            and e["role"] == os.path.basename(bd.path)
            and e["st_dev"] == bd.id[0]
            and e["st_ino"] == bd.id[1]
        ):
            return None
    return "unregistered"


def resolve_roots(root_args: Iterable[str], hos_args: Iterable[str], environ, uid: int) -> tuple:
    """(valid realpath roots, notes [(reason, path)], hos roots). No flags -> $TMPDIR
    or /tmp. ``hos roots`` are the role dirs found through --hos-tmp-root."""
    cands: list = []
    hos_cands: list = []
    notes: list = []
    registry: Any = _UNSET
    explicit = False
    for r in root_args:
        explicit = True
        cands.append(r)
    for h in hos_args:
        explicit = True
        try:
            hst = os.lstat(h)
            if not stat.S_ISDIR(hst.st_mode) or hst.st_uid not in (0, uid):
                raise OSError
            children = sorted(os.listdir(h))
        except OSError:
            notes.append(("root-invalid", h))
            continue
        bad_root = hos_root_problem(h)
        if bad_root:
            notes.append((bad_root, h))
            continue
        for child in children:
            p = os.path.join(h, child)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if ROLE_DIR_RE.match(child) and stat.S_ISDIR(st.st_mode) and st.st_uid == uid:
                if registry is _UNSET:
                    registry = read_registry()
                problem = _role_problem_at(p, registry)
                if problem:
                    notes.append((problem, p))
                    continue
                cands.append(p)
                hos_cands.append(p)
            else:
                notes.append(("not-a-role-dir", p))
    if not explicit:
        cands = default_roots(environ)
    roots: list = []
    hos_roots: set = set()
    for c in cands:
        rp = os.path.realpath(c)
        try:
            st = os.lstat(rp)
        except OSError:
            notes.append(("root-invalid", c))
            continue
        if not stat.S_ISDIR(st.st_mode) or st.st_uid not in (0, uid):
            notes.append(("root-invalid", c))
            continue
        if rp not in roots:
            roots.append(rp)
        if c in hos_cands:
            hos_roots.add(rp)
    return roots, notes, hos_roots


# ── The reaper ─────────────────────────────────────────────────────────────────
class Reaper:
    def __init__(self, args: argparse.Namespace, clock: Callable[[], float], uid: int, user: str):
        self.args = args
        self.clock = clock
        self.uid = uid
        self.user = user
        self.policy = Policy(uid, args.min_age_hours * 3600.0, False, args.dry_run)
        self.deadline = clock() + args.max_seconds
        self.roots: list = []
        self.hos_roots: set = set()
        self.truncated = False
        self.reaped = 0
        self.freed = 0
        self.skipped = 0
        self.errors = 0
        self.user_bytes: Optional[int] = None
        self.scratch_enabled = False  # class S runs this invocation
        self._proc: Optional[ProcIndex] = None
        self.locks: set = set()
        self._bound: dict = {}
        self._opened: list = []
        self._registry: Any = _UNSET

    # ── output ──
    def emit(self, line: str) -> None:
        print(line, flush=True)

    def skip(self, reason: str, path: str, *, run_level: bool = False) -> None:
        self.skipped += 1
        if run_level or not self.args.summary_only:
            self.emit(f"SKIP {reason} {fmt_path(path)}")

    def error(self, name: str, path: str) -> None:
        self.errors += 1
        self.emit(f"ERROR {name} {fmt_path(path)}")

    def reap(self, cls: str, reason: str, path: str, nbytes: int) -> None:
        if self.policy.dry_run:
            self.emit(f"WOULD-REAP {cls} {reason} {fmt_path(path)} {nbytes}")
            return
        self.reaped += 1
        self.freed += nbytes
        self.emit(f"REAP {cls} {reason} {fmt_path(path)} {nbytes}")

    # ── budget and shared facts ──
    def out_of_time(self) -> bool:
        if self.clock() >= self.deadline:
            self.truncated = True
            return True
        return False

    def proc_index(self) -> ProcIndex:
        if self._proc is None:
            self._proc = scan_proc(self.out_of_time)
        return self._proc

    def resolve(self, decide_fn, facts, fills: dict) -> Decision:
        while True:
            d = decide_fn(facts, self.clock(), self.policy)
            if d.action != "NEED":
                return d
            fills[d.reason](facts)

    def _fill_proc(self, facts) -> None:
        facts.proc = self.proc_index()

    # ── bound directories ──
    def bind_root(self, root: str) -> Optional[BoundDir]:
        """Open each root once; every class then works through this fd, not the path."""
        if root not in self._bound:
            bd = None
            try:
                bd = BoundDir(root)
                if bd.st.st_uid not in (0, self.uid) or os.path.realpath(root) != root:
                    bd.close()
                    bd = None
                elif root in self.hos_roots:
                    if self._registry is _UNSET:
                        self._registry = read_registry()
                    problem = role_dir_problem(bd, self._registry)
                    if problem:
                        self.skip(problem, root)
                        bd.close()
                        self._bound[root] = None
                        return None
            except OSError:
                bd = None
            if bd is None:
                self.skip("root-invalid", root)
            self._bound[root] = bd
        return self._bound[root]

    def close_bound(self) -> None:
        for b in [*self._bound.values(), *self._opened]:
            if b is not None:
                b.close()
        self._bound = {}
        self._opened = []

    # ── probe / low-space ──
    def write_probe(self, root: str) -> Optional[OSError]:
        path = os.path.join(root, f".hos-space-probe.{os.getpid()}.{uuid.uuid4().hex[:8]}")
        fd = None
        try:
            fd = os.open(
                path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
            )
            data = b"\0" * PROBE_BYTES
            while data:
                data = data[os.write(fd, data) :]
            os.fsync(fd)
            return None
        except OSError as exc:
            return exc
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def probe_roots(self) -> tuple:
        """(low roots, [(root, used, hard)] for roots whose real quota is high)."""
        low: list = []
        quota_hits: list = []
        for root in self.roots:
            if self.write_probe(root) is not None:
                low.append(root)
                continue
            q = read_user_quota(root)
            if q and q[1] > 0 and q[0] >= QUOTA_LOW_RATIO * q[1]:
                low.append(root)
                quota_hits.append((root, q[0], q[1]))
        return low, quota_hits

    # ── scratch preconditions (design 5.7.1) ──
    def prepare_scratch(self) -> None:
        reason = None
        try:
            if not os.path.isdir(PROC_ROOT) or not os.access(PROC_ROOT, os.R_OK):
                raise ScratchDisabled("no-proc")
            hv = check_host_view()
            if hv:
                raise ScratchDisabled(hv)
            self.locks = load_proc_locks()
            idx = self.proc_index()
            if not idx.available:
                raise ScratchDisabled("no-proc")
            if not idx.complete:
                raise ScratchDisabled("proc-scan-incomplete")
            if idx.n_unreadable:
                self.skip("proc-unreadable", str(idx.n_unreadable), run_level=True)
        except ScratchDisabled as exc:
            reason = str(exc)
        if reason:
            self.scratch_enabled = False
            self._scratch_disabled(reason)
        else:
            self.scratch_enabled = True
            self.policy.scratch_active = True

    def _scratch_disabled(self, reason: str) -> None:
        self.skipped += 1
        self.emit(f"SKIP scratch-disabled {reason}")

    # ── class P ──
    def run_class_p(self) -> None:
        for root in self.roots:
            if self.out_of_time():
                return
            rb = self.bind_root(root)
            if rb is None:
                continue
            pdir = os.path.join(root, f"pytest-of-{self.user}")
            try:
                pb = rb.open_child(f"pytest-of-{self.user}")
            except FileNotFoundError:
                continue
            except OSError:
                self.skip("not-owned-or-symlink", pdir)
                continue
            self._opened.append(pb)
            if pb.st.st_uid != self.uid:
                self.skip("not-owned-or-symlink", pdir)
                continue
            try:
                names = pb.names()
            except OSError as exc:
                self.error(_errname(exc), pdir)
                continue
            for name in names:
                if self.out_of_time():
                    return
                try:
                    self.handle_p(pb, name)
                except Exception as exc:  # one bad entry must not stop the sweep
                    self.error(_excname(exc), pb.child_path(name))

    def handle_p(self, pb: BoundDir, name: str) -> None:
        path = pb.child_path(name)
        st = _lstat_or_none(pb, name)
        if st is None:
            return
        if stat.S_ISLNK(st.st_mode):
            try:
                os.stat(name, dir_fd=pb.fd)
                self.skip("symlink", path)
                return
            except OSError:
                pass
            if st.st_uid == self.uid:
                if not self.policy.dry_run:
                    os.unlink(name, dir_fd=pb.fd)
                self.reap("P", "symlink-dangling", path, 0)
            return
        is_garbage = name.startswith("garbage-")
        if not (PYTEST_RUN_RE.match(name) or is_garbage) or not stat.S_ISDIR(st.st_mode):
            self.skip("unknown", path)
            return
        facts = self.collect_pfacts(pb, name, st, is_garbage)
        try:
            d = self.resolve(decide, facts, {"proc": self._fill_proc, "probe": self._fill_probe})
            if d.action != "REAP":
                self.skip(d.reason, path)
                return
            bad = guard_tree(pb.spath(name), st.st_dev, self.out_of_time)
            if bad:
                self.skip(bad, path)
                return
            nbytes = allocated_tree(pb.spath(name), dev=st.st_dev)[0]
            if self.policy.dry_run:
                self.reap("P", d.reason, path, nbytes)
            elif is_garbage:
                self.remove_garbage("P", d.reason, pb, name, (st.st_dev, st.st_ino), nbytes)
            else:
                self.remove_tree(
                    "P", d.reason, pb, name, (st.st_dev, st.st_ino), "garbage-", nbytes
                )
        finally:
            if facts.probe_fd is not None:
                os.close(facts.probe_fd)
                facts.probe_fd = None

    def collect_pfacts(
        self, pb: BoundDir, name: str, st: os.stat_result, is_garbage: bool
    ) -> PFacts:
        base = pb.spath(name)
        quiet = _ts(st)
        has_live = has_lock = False
        with os.scandir(base) as it:
            for e in it:
                try:
                    cst = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                quiet = max(quiet, _ts(cst))
                if e.name == ".hos-live":
                    has_live = True
                elif e.name == ".lock":
                    has_lock = True
        lock_pid = read_lock_pid(os.path.join(base, ".lock")) if has_lock else None
        path = pb.child_path(name)
        return PFacts(path, name, st.st_uid, quiet, is_garbage, has_live, has_lock, lock_pid, bd=pb)

    def _fill_probe(self, facts: PFacts) -> None:
        base = facts.bd.spath(facts.name) if facts.bd else facts.path
        facts.probe, facts.probe_fd = probe_hos_live(os.path.join(base, ".hos-live"))

    # ── removal ──
    def _rmtree(self, bd: BoundDir, name: str) -> list:
        errs: list = []
        base = bd.spath("")

        def handler(*a):
            exc = a[-1] if sys.version_info >= (3, 12) else a[-1][1]
            if getattr(exc, "errno", None) != errno.ENOENT:
                shown = str(getattr(exc, "filename", None) or name)
                errs.append((_errname(exc), shown.replace(base, bd.path + "/", 1)))

        target = bd.spath(name)
        if sys.version_info >= (3, 12):
            shutil.rmtree(target, onexc=handler)
        else:
            shutil.rmtree(target, onerror=handler)
        return errs

    def remove_tree(
        self,
        cls: str,
        reason: str,
        bd: BoundDir,
        name: str,
        walked_id: tuple,
        prefix: str,
        nbytes: int,
    ) -> None:
        """Rename-to-garbage inside the bound parent, with dev/ino re-checks before and
        after (R2-2) and a check that the parent path still names the bound directory."""
        path = bd.child_path(name)
        if _before_remove is not None:
            _before_remove(path)
        if not bd.intact():
            self.skip("raced", path)
            return
        st = _lstat_or_none(bd, name)
        if st is None or (st.st_dev, st.st_ino) != walked_id:
            self.skip("raced", path)
            return
        gname = f"{prefix}{uuid.uuid4()}"
        try:
            os.rename(name, gname, src_dir_fd=bd.fd, dst_dir_fd=bd.fd)
        except FileNotFoundError:
            self.skip("raced", path)
            return
        try:
            gst = bd.lstat(gname)
        except OSError as exc:
            self.error(_errname(exc), bd.child_path(gname))
            return
        if (gst.st_dev, gst.st_ino) != walked_id:
            self.error("identity-changed", bd.child_path(gname))
            return
        self._finish_rmtree(cls, reason, path, bd, gname, nbytes)

    def remove_garbage(
        self, cls: str, reason: str, bd: BoundDir, name: str, walked_id: tuple, nbytes: int
    ) -> None:
        """A tree that is already named garbage: re-check identity, then rmtree."""
        path = bd.child_path(name)
        if not bd.fd_paths:
            # Without /proc/self/fd the rmtree would be path-based and so swappable.
            self.skip("no-fd-paths", path)
            return
        if not bd.intact():
            self.skip("raced", path)
            return
        st = _lstat_or_none(bd, name)
        if st is None or (st.st_dev, st.st_ino) != walked_id:
            self.skip("raced", path)
            return
        self._finish_rmtree(cls, reason, path, bd, name, nbytes)

    def _finish_rmtree(
        self, cls: str, reason: str, path: str, bd: BoundDir, gname: str, nbytes: int
    ) -> None:
        errs = self._rmtree(bd, gname)
        if errs:
            for name, p in errs:
                self.error(name, str(p))
        else:
            self.reap(cls, reason, path, nbytes)

    # ── class T ──
    def run_class_t(self) -> None:
        for root in self.roots:
            if self.out_of_time():
                return
            rb = self.bind_root(root)
            if rb is None:
                continue
            hos = root in self.hos_roots
            try:
                names = rb.names()
            except OSError as exc:
                self.error(_errname(exc), root)
                continue
            for name in names:
                if not (_is_t_name(name) or (hos and hos_child_name(name))):
                    continue
                if self.out_of_time():
                    return
                try:
                    self.handle_t(rb, name)
                except Exception as exc:
                    self.error(_excname(exc), rb.child_path(name))

    def handle_t(self, rb: BoundDir, name: str) -> None:
        path = rb.child_path(name)
        st = _lstat_or_none(rb, name)
        if st is None:
            return
        mode = st.st_mode
        if stat.S_ISDIR(mode):
            if not _is_t_name(name):
                return  # a non-pattern dir in an HOS role dir is class S's
            kind = "empty-dir" if _is_empty_dir(rb.spath(name)) else "dir"
        elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            kind = "file"
        else:
            kind = "special"
        facts = TFacts(path, st.st_uid, kind, stat.S_ISLNK(mode), _ts(st))
        d = self.resolve(decide_t, facts, {"proc": self._fill_proc})
        if d.action == "HANDOFF":
            return
        if d.action != "REAP":
            self.skip(d.reason, path)
            return
        nbytes = st.st_blocks * 512
        if self.policy.dry_run:
            self.reap("T", d.reason, path, nbytes)
            return
        if _before_remove is not None:
            _before_remove(path)
        if not rb.intact():
            self.skip("raced", path)
            return
        st2 = _lstat_or_none(rb, name)
        if st2 is None or (st2.st_dev, st2.st_ino) != (st.st_dev, st.st_ino):
            self.skip("raced", path)
            return
        try:
            if kind == "empty-dir":
                os.rmdir(name, dir_fd=rb.fd)
            else:
                os.unlink(name, dir_fd=rb.fd)
        except FileNotFoundError:
            self.skip("raced", path)
            return
        except OSError as exc:
            if exc.errno == errno.ENOTEMPTY:
                self.skip("raced", path)
                return
            raise
        self.reap("T", d.reason, path, nbytes)

    # ── class S ──
    def run_class_s(self) -> None:
        if not self.scratch_enabled:
            return
        for root in self.roots:
            if self.out_of_time():
                return
            rb = self.bind_root(root)
            if rb is None:
                continue
            cands, invalid = scratch_candidates(rb, root in self.hos_roots, self.uid, self._opened)
            for bad in invalid:
                self.skip("scratch-root-invalid", bad)
            for cand in cands:
                if self.out_of_time():
                    return
                try:
                    self.handle_s(cand)
                except Exception as exc:
                    self.error(_excname(exc), cand.path)

    def _is_self(self, tree: str, parent: str) -> bool:
        probes = []
        try:
            probes.append(os.path.realpath(os.getcwd()))
        except OSError:
            pass
        for v in [os.environ.get("TMPDIR", "")] + list(os.environ.values()):
            if v.startswith("/"):
                rp = os.path.realpath(v)
                if rp.startswith(parent.rstrip("/") + "/") or rp == parent:
                    probes.append(rp)
        tmpdir = os.environ.get("TMPDIR", "")
        if tmpdir.startswith("/"):
            probes.append(os.path.realpath(tmpdir))
        return any(p == tree or p.startswith(tree + "/") for p in probes)

    def handle_s(self, cand: Cand) -> None:
        bd, name, path = cand.bd, cand.name, cand.path
        st = _lstat_or_none(bd, name)
        if st is None or not stat.S_ISDIR(st.st_mode):
            return
        walked_id = (st.st_dev, st.st_ino)
        if not bd.intact():
            self.skip("raced", path)
            return
        if cand.garbage:
            self.handle_garbage_hos(cand, st)
            return
        facts = SFacts(
            path=path,
            uid=st.st_uid,
            same_dev=st.st_dev == bd.st.st_dev,
            excluded=name_exclusion(cand),
            is_self=self._is_self(os.path.realpath(path), os.path.realpath(cand.parent)),
            top_quiet_ts=_ts(st),
        )

        def fill_walk(f: SFacts) -> None:
            if not bd.intact():  # the parent was swapped after validation
                f.walk = WalkResult("raced")
                return
            f.walk = walk_scratch_tree(
                bd.spath(name),
                tree_dev=st.st_dev,
                uid=self.uid,
                now=self.clock(),
                age_s=self.policy.age_s,
                locks=self.locks,
                expired=self.out_of_time,
            )
            again = _lstat_or_none(bd, name)
            if again is None or (again.st_dev, again.st_ino) != walked_id:
                f.walk = WalkResult("raced")

        d = self.resolve(decide_scratch, facts, {"proc": self._fill_proc, "walk": fill_walk})
        if d.action != "REAP":
            self.skip(d.reason, path)
            return
        nbytes = facts.walk.nbytes if facts.walk else 0
        if self.policy.dry_run:
            self.reap("S", d.reason, path, nbytes)
            return
        self.remove_tree("S", d.reason, bd, name, walked_id, "garbage-hos-", nbytes)

    def handle_garbage_hos(self, cand: Cand, st: os.stat_result) -> None:
        bd, name, path = cand.bd, cand.name, cand.path
        facts = PFacts(path, name, st.st_uid, _ts(st), is_garbage=True)
        if st.st_dev != bd.st.st_dev:
            self.skip("not-owned-or-foreign-dev", path)
            return
        d = self.resolve(decide, facts, {"proc": self._fill_proc})
        if d.action != "REAP":
            self.skip(d.reason, path)
            return
        bad = guard_tree(bd.spath(name), st.st_dev, self.out_of_time)
        if bad:
            self.skip(bad, path)
            return
        nbytes = allocated_tree(bd.spath(name), dev=st.st_dev)[0]
        if self.policy.dry_run:
            self.reap("S", "garbage", path, nbytes)
        else:
            self.remove_garbage("S", "garbage", bd, name, (st.st_dev, st.st_ino), nbytes)

    # ── measure ──
    def run_measure(self) -> None:
        total = 0
        complete = True
        for root in self.roots:
            try:
                names = sorted(os.listdir(root))
            except OSError:
                continue
            for name in names:
                path = os.path.join(root, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if st.st_uid != self.uid:
                    continue
                nbytes, _n, _bp, trunc = allocated_tree(path, 0, self.out_of_time)
                complete = complete and not trunc
                total += nbytes
                if nbytes > LARGE_UNOWNED_BYTES and not self._covered_by_a_class(root, name):
                    self.emit(f"WARN large-unowned {fmt_path(path)} {nbytes}")
        self.user_bytes = total if complete else None
        seen_dev: set = set()
        for root in self.roots:
            dev = os.lstat(root).st_dev
            if dev in seen_dev:
                continue
            seen_dev.add(dev)
            q = read_user_quota(root)
            if q:
                self.emit(f"QUOTA root={fmt_path(root)} used_bytes={q[0]} hard_bytes={q[1] or '-'}")

    def _covered_by_a_class(self, root: str, name: str) -> bool:
        """True when a reaping class can remove this top-level entry (so it is not
        'unowned'). In HOS role dirs that is everything except claude-* dirs."""
        if name.startswith("pytest-of-") or name.startswith("garbage-") or _is_t_name(name):
            return True
        if name in SCRATCH_ROOTS:
            return True
        return root in self.hos_roots and hos_child_name(name)

    # ── remaining counts (cheap listings) ──
    def counts(self) -> dict:
        pytest_runs = empty_dirs = files = 0
        scratch = 0
        for root in self.roots:
            pdir = os.path.join(root, f"pytest-of-{self.user}")
            try:
                pytest_runs += sum(1 for n in os.listdir(pdir) if PYTEST_RUN_RE.match(n))
            except OSError:
                pass
            try:
                names = os.listdir(root)
            except OSError:
                names = []
            for n in names:
                if not _is_t_name(n):
                    continue
                try:
                    st = os.lstat(os.path.join(root, n))
                except OSError:
                    continue
                if st.st_uid != self.uid or stat.S_ISLNK(st.st_mode):
                    continue
                if stat.S_ISDIR(st.st_mode):
                    empty_dirs += 1 if _is_empty_dir(os.path.join(root, n)) else 0
                elif stat.S_ISREG(st.st_mode):
                    files += 1
            if self.scratch_countable():
                rb = self.bind_root(root)
                if rb is not None:
                    scratch += count_scratch_trees(rb, root in self.hos_roots, self.uid)
        return {
            "pytest_runs": pytest_runs,
            "empty_tmp_dirs": empty_dirs,
            "tmp_files": files,
            "scratch_trees": scratch if self.scratch_countable() else "-",
        }

    def scratch_countable(self) -> bool:
        if self.args.no_scratch:
            return False
        return self.scratch_enabled or self.args.measure or self._scratch_not_attempted

    _scratch_not_attempted = False  # set when the run never evaluated class S (low-space ok)

    # ── driver ──
    def run(self) -> int:
        a = self.args
        self.roots, notes, self.hos_roots = resolve_roots(
            a.root, a.hos_tmp_root, os.environ, self.uid
        )
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock()))
        self.emit(
            f"TMP_REAPER_RUN ts={ts} pid={os.getpid()} roots="
            + ",".join(fmt_path(r) for r in self.roots)
        )
        for reason, p in notes:
            self.skip(reason, p)
        if not self.roots:
            self.finish()
            return 3
        try:
            return self._run_valid()
        finally:
            self.close_bound()

    def _run_valid(self) -> int:
        a = self.args
        evaluate = True
        if a.if_low_space:
            low, quota_hits = self.probe_roots()
            if low:
                self.emit("TMP_REAPER_PROBE low roots=" + ",".join(fmt_path(r) for r in low))
                for root, used, hard in quota_hits:
                    self.emit(f"QUOTA root={fmt_path(root)} used_bytes={used} hard_bytes={hard}")
            else:
                self.emit("TMP_REAPER_PROBE ok")
                evaluate = False
                self._scratch_not_attempted = True
        if a.measure:
            self.run_measure()
        elif evaluate:
            if not a.no_scratch:
                self.prepare_scratch()
            self.run_class_p()
            self.run_class_t()
            self.run_class_s()
        self.finish()
        return 0

    def finish(self) -> None:
        c = (
            self.counts()
            if self.roots
            else {
                "pytest_runs": 0,
                "empty_tmp_dirs": 0,
                "tmp_files": 0,
                "scratch_trees": "-",
            }
        )
        ub = "-" if self.user_bytes is None else self.user_bytes
        self.emit(
            f"TMP_REAPER roots={len(self.roots)} reaped={self.reaped} freed_bytes={self.freed} "
            f"skipped={self.skipped} errors={self.errors} truncated={int(self.truncated)} "
            f"user_bytes={ub} pytest_runs={c['pytest_runs']} empty_tmp_dirs={c['empty_tmp_dirs']} "
            f"tmp_files={c['tmp_files']} scratch_trees={c['scratch_trees']} "
            f"dry_run={int(self.policy.dry_run)}"
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tmp_reaper.py",
        description="Machine-level temp reaper (#2054): removes stale, dead temp entries.",
    )
    p.add_argument(
        "--root", action="append", default=[], metavar="DIR", help="temp root to sweep (repeatable)"
    )
    p.add_argument(
        "--hos-tmp-root",
        action="append",
        default=[],
        metavar="DIR",
        help="sweep the Worker/Overseer/Human/Local children of an HOS tmp root (repeatable)",
    )
    p.add_argument(
        "--if-low-space", action="store_true", help="reap only when a write probe or quota says low"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="decide exactly as a real run, delete nothing"
    )
    p.add_argument(
        "--measure", action="store_true", help="delete nothing; report user_bytes and large entries"
    )
    p.add_argument(
        "--summary-only", action="store_true", help="print only REAP/ERROR and run-level lines"
    )
    p.add_argument(
        "--no-scratch", action="store_true", help="disable class S (stale scratch trees)"
    )
    p.add_argument(
        "--min-age-hours", type=float, default=MIN_AGE_HOURS, help="minimum age; raise-only (>= 24)"
    )
    p.add_argument(
        "--max-seconds", type=float, default=DEFAULT_MAX_SECONDS, help="wall-clock budget"
    )
    return p


def main(argv: Optional[list] = None, *, clock: Callable[[], float] = time.time) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not math.isfinite(args.min_age_hours) or args.min_age_hours < MIN_AGE_HOURS:
        print(f"tmp_reaper: --min-age-hours must be a number >= {MIN_AGE_HOURS:g}", file=sys.stderr)
        return 2
    if not math.isfinite(args.max_seconds) or args.max_seconds < 0:
        print("tmp_reaper: --max-seconds must be a number >= 0", file=sys.stderr)
        return 2
    if os.geteuid() == 0:
        print("tmp_reaper: refusing to run as root", file=sys.stderr)
        return 3
    try:
        user = getpass.getuser()
    except Exception:
        user = str(os.getuid())
    if not user or "/" in user or "\0" in user or user in (".", ".."):
        # The name is spliced into the pytest-of-<user> path; refuse anything that is not
        # a single path component.
        print("tmp_reaper: refusing an unsafe user name", file=sys.stderr)
        return 3
    try:
        return Reaper(args, clock, os.getuid(), user).run()
    except Exception as exc:  # last resort: never a bare traceback in a cron log
        print(f"ERROR {_excname(exc)} -", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
