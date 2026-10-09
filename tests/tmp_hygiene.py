"""In-run temp hygiene for the test suite (#2054, Layer 1).

Declared in the root tests/conftest.py. Every pytest run:

* redirects TMPDIR / tempfile.tempdir into ``<basetemp>/session-tmp`` so anything
  the run (or its subprocesses) puts in temp space is deleted with the run's
  own ``pytest-N`` dir;
* holds an exclusive flock on ``<basetemp>/.hos-live`` so a reaper can tell a
  live run from a dead one across PID namespaces;
* at session finish measures what is left and, on a run that would otherwise
  pass, fails it if anything leaked into ``session-tmp`` or the footprint
  exceeds the budget.

The plugin never deletes anything: deletion belongs to pytest's retention
policy (pyproject.toml) and to the backstop reaper. All per-session state lives
in ``config.stash`` so an in-process nested ``pytest.main`` (mutmut, tests)
cannot clobber the outer session.
"""

from __future__ import annotations

import fcntl
import gc
import os
import sys
import tempfile
import time
import uuid
import warnings
from collections.abc import Mapping
from fnmatch import fnmatch
from pathlib import Path
from typing import IO, Any

import pytest

BUDGET_BYTES = 50 * 1024 * 1024
BUDGET_ENV = "HOS_TEST_TMP_BUDGET_MB"
_SECTION_TITLE = "tmp-hygiene (#2054)"

# (glob, producer, reason, issue). Permitted only for a deterministic artifact
# of a third-party tool that a test cannot suppress through its environment.
# Producers in this repo are never allowlisted. Empty at merge (asserted by T7).
LEAK_ALLOWLIST: tuple[tuple[str, str, str, str], ...] = ()


class HygieneState:
    """Per-session state, kept in ``config.stash`` (never in module globals)."""

    __slots__ = (
        "fd",
        "basetemp",
        "session_tmp",
        "saved_tmpdir_env",
        "saved_tempfile_tempdir",
        "saved_node_cache_env",
        "restored",
        "report",
    )

    def __init__(
        self,
        fd: int | None,
        basetemp: Path,
        session_tmp: Path,
        saved_tmpdir_env: str | None,
        saved_tempfile_tempdir: str | None,
        saved_node_cache_env: str | None,
    ) -> None:
        self.fd = fd
        self.basetemp = basetemp
        self.session_tmp = session_tmp
        self.saved_tmpdir_env = saved_tmpdir_env  # None means TMPDIR was absent
        self.saved_tempfile_tempdir = saved_tempfile_tempdir
        self.saved_node_cache_env = saved_node_cache_env
        self.restored = False
        self.report: list[str] = []


# Node >= 22 (and npm/npx) write ``$TMPDIR/node-compile-cache`` unless told not
# to. It is a third-party artifact, suppressed through the environment rather
# than allowlisted (LEAK_ALLOWLIST is reserved for what env cannot suppress).
NODE_CACHE_ENV = "NODE_DISABLE_COMPILE_CACHE"

STATE_KEY: pytest.StashKey[HygieneState] = pytest.StashKey()


def child_env(env: Mapping[str, str] | None) -> dict[str, str] | None:
    """Copy of ``env`` that carries this session's TMPDIR into a child.

    Tests that build a subprocess env from scratch would otherwise let the child
    write to the real /tmp, outside the guardrail's view. A TMPDIR the caller set
    on purpose is never overridden. ``None`` (the child inherits ``os.environ``,
    TMPDIR included) is returned unchanged.
    """
    if env is None:
        return None
    out = dict(env)
    tmpdir = os.environ.get("TMPDIR")
    if tmpdir and "TMPDIR" not in out:
        out["TMPDIR"] = tmpdir
    return out


def resolve_budget(environ: Mapping[str, str]) -> tuple[int, str | None]:
    """Budget in bytes, lowerable (never raisable) through HOS_TEST_TMP_BUDGET_MB."""
    raw = environ.get(BUDGET_ENV)
    if raw is None:
        return BUDGET_BYTES, None
    try:
        mb = int(raw)
    except ValueError:
        mb = 0
    if 0 < mb <= BUDGET_BYTES // (1024 * 1024):
        return mb * 1024 * 1024, None
    return BUDGET_BYTES, (
        f"TMP_HYGIENE WARN {BUDGET_ENV}={raw!r} ignored: must be an integer in "
        f"1..{BUDGET_BYTES // (1024 * 1024)}; budget stays {BUDGET_BYTES // (1024 * 1024)} MiB"
    )


def measure_tree(root: Path, top_depth: int = 2) -> tuple[int, int, dict[str, int]]:
    """Allocated bytes (st_blocks * 512), inode count and per-subpath bytes.

    Each inode is counted once (hardlinks); symlinks are never followed. The
    tmpfs quota counts allocated pages, so apparent size would understate.
    """
    seen: set[tuple[int, int]] = set()
    by_path: dict[str, int] = {}

    def walk(path: str, depth: int) -> int:
        try:
            st = os.lstat(path)
        except OSError:
            return 0
        key = (st.st_dev, st.st_ino)
        if key in seen:
            return 0
        seen.add(key)
        total = st.st_blocks * 512
        if os.path.isdir(path) and not os.path.islink(path):
            try:
                with os.scandir(path) as it:
                    names = [e.name for e in it]
            except OSError:
                names = []
            for name in names:
                total += walk(os.path.join(path, name), depth + 1)
        if depth <= top_depth:
            by_path[os.path.relpath(path, root)] = total
        return total

    total = walk(str(root), 0)
    return total, len(seen), by_path


def _is_allowlisted(name: str) -> bool:
    return any(fnmatch(name, entry[0]) for entry in LEAK_ALLOWLIST)


def _restore_env(state: HygieneState) -> None:
    if state.saved_tmpdir_env is None:
        os.environ.pop("TMPDIR", None)
    else:
        os.environ["TMPDIR"] = state.saved_tmpdir_env
    tempfile.tempdir = state.saved_tempfile_tempdir
    if state.saved_node_cache_env is None:
        os.environ.pop(NODE_CACHE_ENV, None)
    else:
        os.environ[NODE_CACHE_ENV] = state.saved_node_cache_env
    state.restored = True


@pytest.fixture(scope="session", autouse=True)
def _hos_tmp_hygiene(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> None:
    basetemp = tmp_path_factory.getbasetemp()
    fd: int | None = None
    try:
        fd = os.open(basetemp / ".hos-live", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        st = os.fstat(fd)
        os.ftruncate(fd, 0)
        os.write(
            fd,
            f"pid={os.getpid()} start={int(time.time())} dev={st.st_dev} ino={st.st_ino}\n".encode(),
        )
    except OSError as exc:
        warnings.warn(f"tmp-hygiene: could not take the .hos-live flock: {exc}", stacklevel=1)
        if fd is not None:
            os.close(fd)
            fd = None

    session_tmp = basetemp / "session-tmp"
    session_tmp.mkdir(mode=0o700, exist_ok=True)
    state = HygieneState(
        fd,
        basetemp,
        session_tmp,
        os.environ.get("TMPDIR"),
        tempfile.tempdir,
        os.environ.get(NODE_CACHE_ENV),
    )
    os.environ["TMPDIR"] = str(session_tmp)
    os.environ[NODE_CACHE_ENV] = "1"
    tempfile.tempdir = str(session_tmp)
    request.config.stash[STATE_KEY] = state


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Heartbeat: touch .hos-live at each test start (the design's logstart
    hook receives no config, so setup, which receives the item, is used)."""
    state = item.config.stash.get(STATE_KEY, None)
    if state is not None and state.fd is not None:
        try:
            os.utime(state.basetemp / ".hos-live")
        except OSError:
            pass


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int | pytest.ExitCode) -> None:
    state = session.config.stash.get(STATE_KEY, None)
    if state is None:
        return
    gc.collect()

    leaks: list[tuple[str, int]] = []
    if state.session_tmp.is_dir():
        for child in sorted(state.session_tmp.iterdir()):
            if _is_allowlisted(child.name):
                continue
            leaks.append((str(child), measure_tree(child)[0]))
    footprint, inodes, by_path = measure_tree(state.basetemp)
    _restore_env(state)

    budget, warn_line = resolve_budget(os.environ)
    state.report = [
        f"TMP_HYGIENE footprint_bytes={footprint} inodes={inodes} budget_bytes={budget} leaks={len(leaks)}"
    ]
    if warn_line:
        state.report.append(warn_line)
    for path, size in leaks:
        state.report.append(f"TMP_HYGIENE leak path={path} bytes={size}")

    over_budget = footprint > budget
    xdist = bool(os.environ.get("PYTEST_XDIST_WORKER"))
    if int(exitstatus) == 0 and not xdist:
        if leaks:
            state.report.append("TMP_HYGIENE FAIL leak")
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
        if over_budget:
            state.report.append("TMP_HYGIENE FAIL budget")
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
    elif xdist:
        state.report.append("TMP_HYGIENE report-only: xdist worker")
    if leaks or over_budget:
        top = sorted(by_path.items(), key=lambda kv: kv[1], reverse=True)[:20]
        state.report.append("TMP_HYGIENE top subpaths by allocated bytes:")
        state.report.extend(f"  {size:>12}  {rel}" for rel, size in top)

    if session.config.pluginmanager.get_plugin("terminalreporter") is None:
        print("\n".join(state.report), file=sys.stderr)


def pytest_unconfigure(config: pytest.Config) -> None:
    state = config.stash.get(STATE_KEY, None)
    if state is None:
        return
    if not state.restored:
        _restore_env(state)
    if state.fd is not None:
        try:
            os.close(state.fd)  # releases the flock
        except OSError:
            pass
        state.fd = None


def emit_report(terminalreporter: object) -> None:
    """Write the hygiene report as a terminal-summary section (called from conftest)."""
    config = terminalreporter.config  # type: ignore[attr-defined]
    state = config.stash.get(STATE_KEY, None)
    if state is None or not state.report:
        return
    terminalreporter.section(_SECTION_TITLE)  # type: ignore[attr-defined]
    for line in state.report:
        terminalreporter.write_line(line)  # type: ignore[attr-defined]


def named_temp(
    directory: Path | str, suffix: str = "", prefix: str = "", mode: str = "w", **open_kwargs: Any
) -> IO[Any]:
    """Open a uniquely named new file inside ``directory`` (a test's tmp_path).

    Replaces ``tempfile.NamedTemporaryFile(delete=False)`` in tests: the file
    lives under the test's own tmp_path, so pytest's retention policy deletes
    it and nothing can leak into the shared temp root. The caller closes it.
    """
    return open(Path(directory) / f"{prefix}{uuid.uuid4().hex[:12]}{suffix}", mode, **open_kwargs)


def make_dir(directory: Path | str) -> str:
    """Create and return a uniquely named empty dir inside ``directory``.

    Replaces ``tempfile.mkdtemp()`` in tests (same str return type).
    """
    path = Path(directory) / uuid.uuid4().hex[:12]
    path.mkdir()
    return str(path)
