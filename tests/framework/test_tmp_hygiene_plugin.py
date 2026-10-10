"""Tests for the in-run temp hygiene plugin, tests/tmp_hygiene.py (#2054, Layer 1).

Each scenario generates a mini project in ``tmp_path`` whose conftest loads the
real plugin by path and reads the retention ini values from the real
``pyproject.toml``, then runs ``python -m pytest`` on it with its own
``PYTEST_DEBUG_TEMPROOT`` so nothing touches the real temp root. T6 runs an
in-process inner session inside this (outer, real) session.
"""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import pytest

from tests import tmp_hygiene

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "tests" / "tmp_hygiene.py"
REAL_PYPROJECT = ROOT / "pyproject.toml"

_CONFTEST = """
import os
import sys
import tempfile
import importlib.util

import pytest

_spec = importlib.util.spec_from_file_location("hos_tmp_hygiene_under_test", {plugin!r})
_m = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _m
_spec.loader.exec_module(_m)

_hos_tmp_hygiene = _m._hos_tmp_hygiene
pytest_runtest_setup = _m.pytest_runtest_setup
pytest_sessionfinish = _m.pytest_sessionfinish
pytest_unconfigure = _m.pytest_unconfigure


def pytest_terminal_summary(terminalreporter):
    _m.emit_report(terminalreporter)


class _Observer:
    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session):
        out = os.environ.get("HYGIENE_OBSERVE_FILE")
        if out:
            with open(out, "w") as fh:
                fh.write(f"{{os.environ.get('TMPDIR')}}|{{tempfile.tempdir}}")


def pytest_configure(config):
    config.pluginmanager.register(_Observer())
"""


def _retention_ini() -> str:
    """The D1 ini lines, read from the real pyproject.toml."""
    text = REAL_PYPROJECT.read_text()
    lines = re.findall(r"^tmp_path_retention_(?:count|policy) = .*$", text, re.M)
    assert len(lines) == 2, lines
    return "[tool.pytest.ini_options]\n" + "\n".join(lines) + "\n"


def _project(base: Path, name: str, test_src: str) -> Path:
    proj = base / name
    proj.mkdir(parents=True)
    (proj / "pyproject.toml").write_text(_retention_ini())
    (proj / "conftest.py").write_text(_CONFTEST.format(plugin=str(PLUGIN)))
    (proj / "test_mini.py").write_text(textwrap.dedent(test_src))
    return proj


def _env(temproot: Path, **extra: str) -> dict[str, str]:
    temproot.mkdir(parents=True, exist_ok=True)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("PYTEST_")
        and k not in ("HOS_TEST_TMP_BUDGET_MB", "HYGIENE_OBSERVE_FILE")
    }
    env["PYTEST_DEBUG_TEMPROOT"] = str(temproot)
    env.update(extra)
    return env


def _run(proj: Path, temproot: Path, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q"],
        cwd=proj,
        env=_env(temproot, **extra),
        capture_output=True,
        text=True,
        timeout=120,
    )


def _numbered(temproot: Path) -> list[str]:
    out = []
    for user_dir in temproot.glob("pytest-of-*"):
        out += [p.name for p in user_dir.iterdir() if re.fullmatch(r"pytest-\d+", p.name)]
    return sorted(out, key=lambda n: int(n.split("-")[1]))


GREEN = "def test_ok():\n    pass\n"
RED = "def test_bad():\n    assert False\n"


# --- T1: retention, sequential sessions only (AC-11) ---------------------------


def test_T1_green_run_leaves_no_numbered_dir(tmp_path):
    proj, root = _project(tmp_path, "p", GREEN), tmp_path / "root"
    r = _run(proj, root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _numbered(root) == []


def test_T1_red_run_keeps_exactly_one_dir(tmp_path):
    proj, root = _project(tmp_path, "p", RED), tmp_path / "root"
    assert _run(proj, root).returncode == 1
    assert len(_numbered(root)) == 1


def test_T1_red_green_red_keeps_only_the_newest_red(tmp_path):
    red, green, root = (
        _project(tmp_path, "red", RED),
        _project(tmp_path, "green", GREEN),
        tmp_path / "root",
    )
    assert _run(red, root).returncode == 1
    first = _numbered(root)
    assert _run(green, root).returncode == 0
    assert _run(red, root).returncode == 1
    last = _numbered(root)
    assert len(last) == 1
    assert int(last[0].split("-")[1]) > max(int(n.split("-")[1]) for n in first)


# --- T2: leak gate --------------------------------------------------------------


def test_T2_mkdtemp_leak_fails_a_green_run_and_names_the_path(tmp_path):
    proj = _project(
        tmp_path, "p", "def test_leak():\n    import tempfile\n    tempfile.mkdtemp()\n"
    )
    r = _run(proj, tmp_path / "root")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "TMP_HYGIENE FAIL leak" in out
    assert re.search(r"TMP_HYGIENE leak path=\S*session-tmp/tmp\w+", out), out


def test_T2_subprocess_mktemp_leak_is_caught(tmp_path):
    proj = _project(
        tmp_path,
        "p",
        'def test_leak():\n    import subprocess\n    subprocess.run(["mktemp"], check=True)\n',
    )
    r = _run(proj, tmp_path / "root")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "TMP_HYGIENE FAIL leak" in out
    assert re.search(r"leak path=\S*session-tmp/tmp\.\w+", out), out


def test_T2_tempdir_held_in_a_reference_cycle_is_collected_not_reported(tmp_path):
    """Proves gc.collect() runs before measuring (AC-7)."""
    proj = _project(
        tmp_path,
        "p",
        """
        import gc, tempfile

        def test_cycle():
            gc.disable()
            holder = type("Holder", (), {})()
            holder.me = holder
            holder.td = tempfile.TemporaryDirectory()
            del holder
        """,
    )
    r = _run(proj, tmp_path / "root")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "leaks=0" in r.stdout + r.stderr


# --- T3: budget gate ------------------------------------------------------------

_BIG = """
import pytest

@pytest.fixture(scope="session")
def big(tmp_path_factory):
    d = tmp_path_factory.mktemp("big")
    (d / "blob").write_bytes(b"x" * (2 * 1024 * 1024))

def test_a(big):
    pass
"""


def test_T3_budget_can_be_lowered_and_then_fails_the_run(tmp_path):
    proj = _project(tmp_path, "p", _BIG)
    r = _run(proj, tmp_path / "root", HOS_TEST_TMP_BUDGET_MB="1")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "TMP_HYGIENE FAIL budget" in out


def test_T3_budget_cannot_be_raised(tmp_path):
    proj = _project(tmp_path, "p", GREEN)
    r = _run(proj, tmp_path / "root", HOS_TEST_TMP_BUDGET_MB="500")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "ignored" in out
    assert f"budget_bytes={50 * 1024 * 1024}" in out


@pytest.mark.parametrize(
    "raw,expected_ok",
    [
        ("1", True),
        ("50", True),
        ("51", False),
        ("0", False),
        ("-3", False),
        ("abc", False),
        ("", False),
    ],
)
def test_T3_resolve_budget(raw, expected_ok):
    budget, warning = tmp_hygiene.resolve_budget({tmp_hygiene.BUDGET_ENV: raw})
    assert (warning is None) is expected_ok
    assert budget <= tmp_hygiene.BUDGET_BYTES
    if not expected_ok:
        assert budget == tmp_hygiene.BUDGET_BYTES


def test_T3_unset_budget_is_the_default():
    assert tmp_hygiene.resolve_budget({}) == (tmp_hygiene.BUDGET_BYTES, None)


# --- T4: red run reports but does not escalate -----------------------------------


def test_T4_red_run_with_a_leak_reports_without_a_leak_failure(tmp_path):
    proj = _project(
        tmp_path,
        "p",
        "def test_bad():\n    import tempfile\n    tempfile.mkdtemp()\n    assert False\n",
    )
    r = _run(proj, tmp_path / "root")
    out = r.stdout + r.stderr
    assert r.returncode == 1
    assert "TMP_HYGIENE leak path=" in out
    assert "FAIL leak" not in out


# --- T5: flock and record (AC-4) --------------------------------------------------

_HOLD = """
import os, time
from pathlib import Path

def test_hold():
    ready, go = Path(os.environ["HOLD_DIR"], "ready"), Path(os.environ["HOLD_DIR"], "go")
    ready.write_text("1")
    deadline = time.time() + 60
    while not go.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert False, "red on purpose so the basetemp (and .hos-live) stays for inspection"
"""


def _flock_probe(path: Path) -> bool:
    """True when the exclusive flock could be taken (nobody holds it)."""
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


def test_T5_live_session_holds_the_flock_and_records_its_inode(tmp_path):
    proj, root, hold = _project(tmp_path, "p", _HOLD), tmp_path / "root", tmp_path / "hold"
    hold.mkdir()
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q"],
        cwd=proj,
        env=_env(root, HOLD_DIR=str(hold)),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.time() + 60
        while not (hold / "ready").exists() and time.time() < deadline:
            time.sleep(0.05)
        assert (hold / "ready").exists(), "mini session never reached its test"
        (live,) = list(root.glob("pytest-of-*/pytest-[0-9]*/.hos-live"))
        assert _flock_probe(live) is False, "a running session must hold the flock"
        record = dict(kv.split("=") for kv in live.read_text().split())
        st = os.stat(live)
        assert (int(record["dev"]), int(record["ino"])) == (st.st_dev, st.st_ino)
        assert int(record["pid"]) == proc.pid
        (hold / "go").write_text("1")
        proc.communicate(timeout=60)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 1
    assert live.exists(), "red run keeps its dir"
    assert _flock_probe(live) is True, "the flock is released when the session ends"


# --- T6: in-process nesting and restore (AC-5, AC-6) ---------------------------------


def test_T6_inner_session_does_not_disturb_the_outer_one(request, tmp_path):
    outer = request.config.stash[tmp_hygiene.STATE_KEY]
    before = (outer.fd, outer.basetemp, outer.session_tmp)
    live = outer.basetemp / ".hos-live"
    proj = _project(tmp_path, "inner", GREEN)

    saved_cwd = os.getcwd()
    os.chdir(proj)
    try:
        code = pytest.main(
            ["-p", "no:cacheprovider", "-q", "--basetemp", str(tmp_path / "inner-base"), str(proj)]
        )
    finally:
        os.chdir(saved_cwd)
    assert code == 0

    assert (outer.fd, outer.basetemp, outer.session_tmp) == before
    assert os.environ["TMPDIR"] == str(outer.session_tmp)
    assert tempfile.tempdir == str(outer.session_tmp)
    assert outer.restored is False
    assert _flock_probe(live) is False, "the outer session must still hold its flock"


def test_T6_tmpdir_is_restored_before_later_session_finish_hooks(tmp_path):
    proj, root = _project(tmp_path, "p", GREEN), tmp_path / "root"
    original = tmp_path / "original-tmpdir"
    original.mkdir()
    observed = tmp_path / "observed.txt"
    r = _run(proj, root, TMPDIR=str(original), HYGIENE_OBSERVE_FILE=str(observed))
    assert r.returncode == 0, r.stdout + r.stderr
    tmpdir_env, tempdir = observed.read_text().split("|")
    assert tmpdir_env == str(original)
    assert tempdir in ("None", str(original))


# --- T11: child_env (AC-12) -------------------------------------------------------------


def test_T11_child_env_adds_tmpdir_when_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert tmp_hygiene.child_env({"PATH": "/bin"}) == {"PATH": "/bin", "TMPDIR": str(tmp_path)}


def test_T11_child_env_never_overrides_a_callers_tmpdir(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert tmp_hygiene.child_env({"TMPDIR": "/somewhere/else"}) == {"TMPDIR": "/somewhere/else"}


def test_T11_child_env_copies_and_passes_none_through(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    original = {"A": "1"}
    assert tmp_hygiene.child_env(original) is not original
    assert original == {"A": "1"}
    assert tmp_hygiene.child_env(None) is None


def test_T11_child_env_leaves_env_alone_without_a_session_tmpdir(monkeypatch):
    monkeypatch.delenv("TMPDIR", raising=False)
    assert tmp_hygiene.child_env({"A": "1"}) == {"A": "1"}


# --- helpers shipped for tests ----------------------------------------------------------------


def test_named_temp_and_make_dir_live_under_the_given_directory(tmp_path):
    with tmp_hygiene.named_temp(tmp_path, suffix=".py", prefix="0001_migration_") as f:
        f.write("x = 1\n")
    p = Path(f.name)
    assert p.parent == tmp_path and p.name.startswith("0001_migration_") and p.suffix == ".py"
    d = Path(tmp_hygiene.make_dir(tmp_path))
    assert d.is_dir() and d.parent == tmp_path
    assert tmp_hygiene.make_dir(tmp_path) != str(d)


def test_measure_tree_counts_allocated_bytes_and_each_inode_once(tmp_path):
    (tmp_path / "a").write_bytes(b"x" * 100_000)
    os.link(tmp_path / "a", tmp_path / "b")
    (tmp_path / "link").symlink_to(tmp_path / "a")
    total, inodes, by_path = tmp_hygiene.measure_tree(tmp_path)
    once = (tmp_path / "a").stat().st_blocks * 512
    assert once <= total < once + 64 * 1024
    assert inodes == 3  # root, a (== b), link
    assert "." in by_path
