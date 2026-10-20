"""
Add the validators directory to sys.path so tests can import validators
directly without package-relative imports.

Also add the project root so `from scripts.automation.lib.X import ...`
works for the automation subsystem (scripts/ is a namespace package).
"""

import hashlib
import importlib.util
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parent.parent

# #2054 in-run temp hygiene. Importing the hooks and fixture here registers them
# for every run of this suite; all logic lives in tests/tmp_hygiene.py.
from tests.tmp_hygiene import (  # noqa: E402,F401
    _hos_tmp_hygiene,
    emit_report,
    pytest_runtest_setup,
    pytest_sessionfinish,
    pytest_unconfigure,
)


def load_module_from_path(name: str, path: Path, *, register: bool = False) -> ModuleType:
    """Load a module from a file path for tests that import project scripts
    directly rather than as installed packages.

    Narrows importlib.util's Optional return types once so call sites don't
    each repeat the same `assert spec is not None and spec.loader is not None`.

    `register=True` registers the module in sys.modules under `name` before
    executing it — needed when the module's own top-level code (e.g. a
    @dataclass that introspects sys.modules[cls.__module__]) requires the
    module to already be resolvable during exec.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Allow `import schema`, `import rn_calculator`, etc. from tests
VALIDATORS_DIR = ROOT / "scripts" / "oversight" / "validators"
OVERSIGHT_DIR = ROOT / "scripts" / "oversight"
for p in (str(VALIDATORS_DIR), str(OVERSIGHT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Allow `from scripts.automation.lib.X import ...`
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# #2100 AD-10: tests never write the real tmp-root trust registry. The override is
# set for the whole session (before any test or fixture runs) and a guard proves the
# real file is untouched. Production registry_path() stays free of test-awareness.
REGISTRY_ENV = "HOS_TMP_REGISTRY_FILE"
NOT_OBSERVABLE = "not observable"
_REGISTRY_READ_CAP = 4 << 20


def real_registry_path() -> str:
    """The registry path a launcher would use with no override, from the module's own helper."""
    mod = load_module_from_path(
        "hos_tmp_root_registry_guard", ROOT / "bootstrap" / "lib" / "hos_tmp_root.py"
    )
    saved = os.environ.pop(REGISTRY_ENV, None)
    try:
        return mod.registry_path()
    finally:
        if saved is not None:
            os.environ[REGISTRY_ENV] = saved


def registry_fingerprint(path: str) -> dict | str:
    """lstat presence, inode, mtime, size and sha256 of ``path``; NOT_OBSERVABLE if unreadable.

    Read-only: it never creates the file or its directory. An absent file is a
    legitimate observable state (a later appearance is a change); any other failure to
    look is not observable.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {"present": False}
    except OSError:
        return NOT_OBSERVABLE
    fp: dict = {
        "present": True,
        "ino": info.st_ino,
        "mtime_ns": info.st_mtime_ns,
        "size": info.st_size,
        "sha256": None,
    }
    if stat.S_ISREG(info.st_mode):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError:
            return NOT_OBSERVABLE
        try:
            fp["sha256"] = hashlib.sha256(os.read(fd, _REGISTRY_READ_CAP)).hexdigest()
        except OSError:
            return NOT_OBSERVABLE
        finally:
            os.close(fd)
    return fp


def registry_changes(before: dict | str, after: dict | str) -> str | None:
    """A description of the change between two fingerprints, or None if the guard passes."""
    if before == NOT_OBSERVABLE or after == NOT_OBSERVABLE:
        return None
    if before == after:
        return None
    return f"before={before} after={after}"


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _RegistryIsolation:
    """Session-end half of the AD-10 guard. Registered by pytest_configure below, because
    the hygiene hooks imported above already occupy the pytest_sessionfinish and
    pytest_unconfigure names in this module."""

    def __init__(self, real_path: str, before: dict | str, saved_env: str | None):
        self.real_path = real_path
        self.before = before
        self.saved_env = saved_env
        self.started = _utcnow()
        self.failure: str | None = None
        self.restored = False

    def restore_env(self) -> None:
        if self.restored:
            return
        self.restored = True
        if self.saved_env is None:
            os.environ.pop(REGISTRY_ENV, None)
        else:
            os.environ[REGISTRY_ENV] = self.saved_env

    def pytest_sessionfinish(self, session):
        change = registry_changes(self.before, registry_fingerprint(self.real_path))
        if change:
            self.failure = (
                f"REGISTRY_ISOLATION FAIL the real tmp-root registry {self.real_path} changed "
                f"during the test run {self.started} .. {_utcnow()}: {change}"
            )
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_terminal_summary(self, terminalreporter):
        if self.failure:
            terminalreporter.section("registry-isolation (#2100)")
            terminalreporter.write_line(self.failure)

    def pytest_unconfigure(self, config):
        self.restore_env()


@pytest.hookimpl(trylast=True)  # after pytest's tmpdir plugin has created its factory
def pytest_configure(config):
    real = real_registry_path()
    saved = os.environ.get(REGISTRY_ENV)
    # A caller-set override is kept only when it is not the real path (a fixture-style
    # value such as a test rig's own file); otherwise the session-owned path under the
    # run's basetemp (deleted with the run's pytest-N dir) replaces it.
    if not saved or os.path.realpath(saved) == os.path.realpath(real):
        basetemp = config._tmp_path_factory.getbasetemp()
        os.environ[REGISTRY_ENV] = str(basetemp / "hos-registry" / "tmp-roots.json")
    config.pluginmanager.register(
        _RegistryIsolation(real, registry_fingerprint(real), saved), "hos-registry-isolation"
    )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Surface pytest-rerunfailures retry-rescues (#1244 ruling item 4).

    A test that fails once then passes on the --reruns 1 retry doesn't fail
    the build, but going silent about it is exactly the drift this repo's
    testability work exists to catch. Detection/formatting logic lives in
    retry_rescue_logic.py (importable, unit-tested); this hook only reads
    pytest's own per-outcome report buckets and does the I/O.

    Best-effort only: on a CI checkout (`permissions: contents: read` in
    tests.yml) the audit-log write happens on a filesystem that is never
    committed back, so it doesn't durably land — the terminal-summary lines
    below are what keeps CI visible in that case. Persisting CI-originated
    events and escalating a threshold breach into a filed bug ticket needs
    its own design (state channel, de-dup) and is tracked separately.
    """
    emit_report(terminalreporter)

    from retry_rescue_logic import build_retry_rescue_event, now_iso, rescued_nodeids

    rerun_nodeids = [r.nodeid for r in terminalreporter.stats.get("rerun", [])]
    if not rerun_nodeids:
        return
    passed_nodeids = [r.nodeid for r in terminalreporter.stats.get("passed", [])]
    rescues = rescued_nodeids(rerun_nodeids, passed_nodeids)
    if not rescues:
        return

    terminalreporter.section("retry-rescues (#1244 ruling item 4)")
    ts = now_iso()
    pr_number = os.environ.get("PR_NUMBER") or None
    for nodeid in rescues:
        terminalreporter.write_line(f"RETRY-RESCUE: {nodeid} failed once, passed on retry")
        try:
            from scripts.oversight.lib.audit_log import write_event

            write_event(build_retry_rescue_event(nodeid, ts, pr_number), root=str(ROOT))
        except Exception as exc:  # best-effort — never fail the test run over logging
            terminalreporter.write_line(f"  (audit write skipped: {exc})")
