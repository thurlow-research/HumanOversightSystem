"""Tripwire plugin for the new-code gate's mutation runs (#2304, TD 5.7 and 5.18).

The gate copies this file to `<run_tmp>/ncg-plugin/_ncg_tripwire.py`, outside the
mutation workspace, and loads it with `-p _ncg_tripwire`. While active it

* logs every executed node ID, so the gate can prove executed is a subset of selected;
* raises `NCGRepoCopyError` when a test copies, clones, worktree-adds or archives the
  repository root (the workspace or its `mutants/` copy);
* records any load of the gated file under a non-canonical name: through the file
  loaders, a passive `sys.meta_path` observer, and a `sys.modules` scan.

It is inert unless activated. The four `NCG_*` variables are read once at import and
removed from the environment (R3-H), so a test cannot switch the real tripwire off, no
subprocess inherits the variables, and a second, canonically imported copy of this
module stays inert. At module level it imports only the stdlib and no `scripts.*`
module, because it runs from outside the workspace.

Shape (TD 5.18): the hooks are plain undecorated top-level functions, the wrappers
are built by undecorated helpers, and no module-level statement holds decision logic.
"""

from __future__ import annotations

import functools
import importlib.machinery
import importlib.util
import json
import os
import runpy
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

NCG_ENV = ("NCG_GATED_FILE", "NCG_CANONICAL", "NCG_WORKSPACE", "NCG_LOG")

# One atomic O_APPEND write per event: stay under PIPE_BUF-sized lines.
MAX_EVENT_BYTES = 4000
MAX_FIELD_CHARS = 600
GIT_COPY_COMMANDS = frozenset({"clone", "archive"})
GIT_VALUE_OPTIONS = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace"})

_THIS_FILE = __file__
_SENTINEL = object()
_RUNTIME: dict[str, Any] = {"phase": "session", "nodeid": None, "in_observer": False}
_SEEN: set[str] = set()
_INSTALLED: list[tuple[Any, str, Any, Any]] = []


class NCGRepoCopyError(Exception):
    """A test copied the repository inside a mutation run."""


class State(NamedTuple):
    gated_file: str | None
    canonical: str | None
    workspace: str | None
    log: str | None


def _load_state(mapping: Any) -> State:
    """Read every NCG variable out of `mapping`, removing each (R3-H)."""
    values = [mapping.pop(name, None) for name in NCG_ENV]
    return State(*values)


_STATE = _load_state(os.environ)


def is_active(state: State) -> bool:
    return state.workspace is not None and state.log is not None


def set_state(state: State) -> None:
    global _STATE
    _STATE = state


def current_state() -> State:
    return _STATE


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def _bound_fields(event: dict[str, Any], limit: int) -> dict[str, Any]:
    out = {}
    for key, value in event.items():
        out[key] = value[:limit] if isinstance(value, str) else value
    return out


def encode_event(event: dict[str, Any]) -> bytes:
    """One JSON line under MAX_EVENT_BYTES; long strings are cut to fit."""
    limit = MAX_FIELD_CHARS
    data = (json.dumps(_bound_fields(event, limit)) + "\n").encode("ascii", "replace")
    while len(data) >= MAX_EVENT_BYTES and limit > 8:
        limit //= 2
        data = (json.dumps(_bound_fields(event, limit)) + "\n").encode("ascii", "replace")
    return data


def emit(event: dict[str, Any]) -> None:
    """Append one event to NCG_LOG; a failed write never changes a test outcome."""
    state = _STATE
    if not is_active(state):
        return
    event = dict(event, pid=os.getpid())
    try:
        fd = os.open(str(state.log), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, encode_event(event))
        finally:
            os.close(fd)
    except OSError:
        return


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _resolve(path: Any) -> Path | None:
    try:
        return Path(os.fspath(path)).resolve()
    except (OSError, TypeError, ValueError):
        return None


def protected_roots(state: State) -> list[Path]:
    """The workspace and its `mutants/` copy: the latter is the repo root tests see."""
    ws = _resolve(state.workspace)
    if ws is None:
        return []
    return [ws, ws / "mutants"]


def gated_copies(state: State) -> list[Path]:
    """Both places the gated file lives: the copy tests import and the extracted one."""
    ws = _resolve(state.workspace)
    if ws is None or state.gated_file is None:
        return []
    return [(ws / "mutants" / state.gated_file).resolve(), (ws / state.gated_file).resolve()]


def touches_protected_root(path: Path, roots: list[Path]) -> bool:
    """True when `path` is a protected root or contains one."""
    return any(path == root or path in root.parents for root in roots)


def importer_file() -> str:
    """The file of the first frame that is neither this plugin nor importlib."""
    frame: Any = sys._getframe(1)
    while frame is not None:
        name = frame.f_code.co_filename
        if name != _THIS_FILE and not name.startswith("<frozen importlib"):
            return name
        frame = frame.f_back
    return "?"


# ---------------------------------------------------------------------------
# Repo-copy tripwire
# ---------------------------------------------------------------------------


def raise_repo_copy(source: Any, via: str) -> None:
    node = _RUNTIME["nodeid"] or "<session>"
    emit({"event": "repo_copy", "node": node, "source": str(source), "via": via})
    raise NCGRepoCopyError(f"{node}: copies the repository; mark it @pytest.mark.repo_copy")


def check_copytree(args: tuple, kwargs: dict) -> None:
    state = _STATE
    if not is_active(state):
        return
    src = args[0] if args else kwargs.get("src")
    resolved = _resolve(src)
    if resolved is not None and touches_protected_root(resolved, protected_roots(state)):
        raise_repo_copy(src, "shutil.copytree")


def argv_tokens(argv: Any) -> list[str]:
    """Flatten a Popen `args` value into strings; a shell string is split like a shell."""
    if isinstance(argv, (str, bytes, os.PathLike)):
        text = os.fsdecode(argv)
        try:
            return shlex.split(text)
        except ValueError:
            return []
    try:
        return [os.fsdecode(a) for a in argv]
    except TypeError:
        return []


def _git_base(tokens: list[str], cwd: Any) -> tuple[list[str], Path | None]:
    """Strip git's global options; return the remaining tokens and the effective cwd."""
    base = _resolve(cwd if cwd is not None else os.getcwd())
    rest = tokens[1:]
    while rest and rest[0].startswith("-"):
        option = rest[0]
        if option == "-C" and len(rest) > 1 and base is not None:
            base = (base / rest[1]).resolve()
        rest = rest[2:] if option in GIT_VALUE_OPTIONS else rest[1:]
    return rest, base


def git_copy_source(argv: Any, cwd: Any) -> str | None:
    """The repo-root path a `git clone | worktree add | archive` command would copy, if any."""
    tokens = argv_tokens(argv)
    if not tokens or os.path.basename(tokens[0]) != "git":
        return None
    rest, base = _git_base(tokens, cwd)
    if not rest or base is None:
        return None
    command, tail = rest[0], rest[1:]
    roots = protected_roots(_STATE)
    if command == "clone":
        for token in [t for t in tail if not t.startswith("-")]:
            candidate = _resolve(base / token.removeprefix("file://"))
            if candidate is not None and touches_protected_root(candidate, roots):
                return token
        return None
    copies = command in GIT_COPY_COMMANDS or (command == "worktree" and tail[:1] == ["add"])
    if copies and touches_protected_root(base, roots):
        return str(base)
    return None


def check_popen(args: tuple, kwargs: dict) -> None:
    if not is_active(_STATE):
        return
    argv = args[0] if args else kwargs.get("args")
    found = git_copy_source(argv, kwargs.get("cwd"))
    if found is not None:
        raise_repo_copy(found, "subprocess.Popen")


# ---------------------------------------------------------------------------
# Path-load recorder
# ---------------------------------------------------------------------------


def record_load(path: Any, loaded_as: Any, kind: str) -> None:
    """Log a load of the gated file's copy under a name other than the canonical one."""
    state = _STATE
    if not is_active(state) or loaded_as == state.canonical or path is None:
        return
    if _resolve(path) not in gated_copies(state):
        return
    emit(
        {
            "event": "path_load",
            "kind": kind,
            "loaded_as": str(loaded_as),
            "canonical": state.canonical,
            "importer": importer_file(),
            "phase": _RUNTIME["phase"],
        }
    )


def check_spec(args: tuple, kwargs: dict) -> None:
    name = args[0] if args else kwargs.get("name")
    location = args[1] if len(args) > 1 else kwargs.get("location")
    record_load(location, name, "spec_from_file_location")


def check_source_loader(args: tuple, kwargs: dict) -> None:
    name = args[0] if args else kwargs.get("fullname")
    path = args[1] if len(args) > 1 else kwargs.get("path")
    record_load(path, name, "SourceFileLoader")


def check_sourceless_loader(args: tuple, kwargs: dict) -> None:
    name = args[0] if args else kwargs.get("fullname")
    path = args[1] if len(args) > 1 else kwargs.get("path")
    record_load(path, name, "SourcelessFileLoader")


def check_run_path(args: tuple, kwargs: dict) -> None:
    path = args[0] if args else kwargs.get("path_name")
    name = kwargs.get("run_name") or (args[2] if len(args) > 2 else None)
    record_load(path, name or "<run_path>", "run_path")


def stem_of(gated_file: str) -> str:
    parts = gated_file.removesuffix(".py").split("/")
    return parts[-2] if parts[-1] == "__init__" else parts[-1]


def observe_import(fullname: str, path: Any) -> None:
    """Resolve where a bare-named import would load from; record it if it is the gated file."""
    state = _STATE
    if not is_active(state) or state.gated_file is None or fullname == state.canonical:
        return
    if fullname.rpartition(".")[2] != stem_of(state.gated_file) or fullname in _SEEN:
        return
    spec = importlib.machinery.PathFinder.find_spec(fullname, path)
    if spec is None or spec.origin is None:
        return
    if _resolve(spec.origin) in gated_copies(state):
        _SEEN.add(fullname)
        record_load(spec.origin, fullname, "meta_path")


def log_observer_error(exc: BaseException) -> None:
    emit({"event": "observer_error", "message": f"{type(exc).__name__}: {exc}"})


class _Observer:
    """A passive `sys.meta_path` finder: it only watches, and always answers None."""

    def find_spec(self, fullname, path=None, target=None):
        if _RUNTIME["in_observer"]:
            return None
        _RUNTIME["in_observer"] = True
        try:
            observe_import(fullname, path)
        except Exception as exc:
            log_observer_error(exc)
        finally:
            _RUNTIME["in_observer"] = False
        return None


def scan_modules() -> None:
    """Record any module whose file is the gated copy but whose name is not canonical."""
    state = _STATE
    if not is_active(state):
        return
    copies = gated_copies(state)
    for name, module in list(sys.modules.items()):
        origin = getattr(module, "__file__", None)
        if name == state.canonical or name in _SEEN or origin is None:
            continue
        if _resolve(origin) in copies:
            _SEEN.add(name)
            record_load(origin, name, "sys_modules")


# ---------------------------------------------------------------------------
# Install and uninstall (idempotent per module copy)
# ---------------------------------------------------------------------------


def _wrap_function(orig: Any, check: Any) -> Any:
    def wrapper(*args, **kwargs):
        check(args, kwargs)
        return orig(*args, **kwargs)

    functools.update_wrapper(wrapper, orig)
    wrapper.__dict__["__ncg_wrapped__"] = _SENTINEL
    return wrapper


def _wrap_class(orig: Any, check: Any) -> Any:
    class Guarded(orig):
        __ncg_wrapped__ = _SENTINEL

        def __init__(self, *args, **kwargs):
            check(args, kwargs)
            super().__init__(*args, **kwargs)

    Guarded.__name__ = orig.__name__
    Guarded.__qualname__ = orig.__qualname__
    return Guarded


def _targets() -> list[tuple[Any, str, Any, Any]]:
    return [
        (shutil, "copytree", _wrap_function, check_copytree),
        (subprocess, "Popen", _wrap_class, check_popen),
        (importlib.util, "spec_from_file_location", _wrap_function, check_spec),
        (importlib.machinery, "SourceFileLoader", _wrap_class, check_source_loader),
        (importlib.machinery, "SourcelessFileLoader", _wrap_class, check_sourceless_loader),
        (runpy, "run_path", _wrap_function, check_run_path),
    ]


def install() -> None:
    """Wrap every target once per copy, and add one observer of this copy."""
    for owner, name, wrap, check in _targets():
        current = getattr(owner, name)
        if getattr(current, "__ncg_wrapped__", None) is _SENTINEL:
            continue
        wrapped = wrap(current, check)
        setattr(owner, name, wrapped)
        _INSTALLED.append((owner, name, current, wrapped))
    if not any(isinstance(finder, _Observer) for finder in sys.meta_path):
        sys.meta_path.insert(0, _Observer())


def uninstall() -> None:
    """Restore exactly what this copy replaced, and remove its observer."""
    for owner, name, original, wrapped in reversed(_INSTALLED):
        if getattr(owner, name) is wrapped:
            setattr(owner, name, original)
    _INSTALLED.clear()
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, _Observer)]
    _SEEN.clear()


# ---------------------------------------------------------------------------
# pytest hooks (plain undecorated functions; pytest finds them by name)
# ---------------------------------------------------------------------------


def pytest_configure(config):
    if not is_active(_STATE):
        return
    emit({"event": "plugin_loaded", "path": str(Path(__file__).resolve())})
    install()
    scan_modules()


def pytest_collectstart(collector):
    if is_active(_STATE):
        _RUNTIME["phase"] = f"collect:{collector.nodeid}"


def pytest_collectreport(report):
    if is_active(_STATE):
        scan_modules()
        _RUNTIME["phase"] = "session"


def pytest_runtest_logstart(nodeid, location):
    if is_active(_STATE):
        _RUNTIME.update(phase=f"test:{nodeid}", nodeid=nodeid)
        emit({"event": "executed", "node": nodeid})


def pytest_runtest_teardown(item, nextitem):
    if is_active(_STATE):
        scan_modules()


def pytest_runtest_logfinish(nodeid, location):
    if is_active(_STATE):
        _RUNTIME.update(phase="session", nodeid=None)
