"""Session-wide isolation of the tmp-root trust registry from the test run (#2100 AD-10).

Wired up by tests/conftest.py; kept out of it so the hook names defined here do not
shadow the hygiene hooks conftest imports.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parent.parent

# #2100 AD-10: tests never write the real tmp-root trust registry. The override is
# set for the whole session (before any test or fixture runs) and a guard proves the
# real file is untouched. Production registry_path() stays free of test-awareness.
REGISTRY_ENV = "HOS_TMP_REGISTRY_FILE"
NOT_OBSERVABLE = "not observable"
_REGISTRY_READ_CAP = 4 << 20


def load_resolver() -> ModuleType:
    """bootstrap/lib/hos_tmp_root.py, loaded privately (not registered in sys.modules)."""
    spec = importlib.util.spec_from_file_location(
        "hos_tmp_root_registry_guard", ROOT / "bootstrap" / "lib" / "hos_tmp_root.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def real_registry_path() -> str:
    """The registry path a launcher would use with no override, from the module's own helper."""
    mod = load_resolver()
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
    look is not observable. A legitimate concurrent write by a real launcher or cron cycle
    during a long run trips the guard by design (AD-10: fail on any change).
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
    """Session-end half of the AD-10 guard. Registered by tests/conftest.py's pytest_configure."""

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
