"""Tests for the new-code gate's tripwire plugin (#2304, TD 5.7, 5.18 and 9).

The plugin is imported canonically and at module level. Its in-process copy
starts inert: the real `NCG_*` variables, if any, were removed from the
environment when the real tripwire was imported (R3-H), and the autouse fixture
below clears them again and resets the copy's state around every test.

Tests that need an active copy activate it through `_load_state(mapping)` with
values under `tmp_path`, never through the process environment.
"""

import ast
import importlib
import importlib.util
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

from scripts.framework import new_code_gate_pytest_plugin as plugin

pytest_plugins = ["pytester"]

PLUGIN_SOURCE = Path(plugin.__file__)
THIS_FILE = Path(__file__)
# Tests that read the plugin's text read the original: in a mutation workspace the imported plugin
# is mutmut's trampolined copy under `mutants/`, and the untouched file is the root beside it.
PLUGIN_TEXT = (
    PLUGIN_SOURCE.parents[2].parent / "scripts/framework" / PLUGIN_SOURCE.name
    if PLUGIN_SOURCE.parents[2].name == "mutants"
    else PLUGIN_SOURCE
)


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path, monkeypatch):
    """A mutant that turns a computed path relative lands here, never in mutmut's cwd (RV3-7a)."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _ncg_isolation(monkeypatch):
    """No test sees the gate's real NCG_*, and none leaves a copy active or installed."""
    for name in plugin.NCG_ENV:
        monkeypatch.delenv(name, raising=False)
    plugin.uninstall()
    plugin.set_state(plugin._load_state({}))
    yield
    plugin.uninstall()
    plugin.set_state(plugin._load_state({}))
    plugin._RUNTIME.update(phase="session", nodeid=None, in_observer=False)


def _events(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="ascii").splitlines()]


@pytest.fixture
def active(tmp_path):
    ws = tmp_path / "ws"
    (ws / "mutants" / "pkg").mkdir(parents=True)
    (ws / "pkg").mkdir()
    log = tmp_path / "events.jsonl"
    state = plugin._load_state(
        {
            "NCG_GATED_FILE": "pkg/mod.py",
            "NCG_CANONICAL": "pkg.mod",
            "NCG_WORKSPACE": str(ws),
            "NCG_LOG": str(log),
        }
    )
    plugin.set_state(state)
    return types.SimpleNamespace(ws=ws, log=log, state=state, events=lambda: _events(log))


# --------------------------------------------------------------------------
# State: the env is read once, then removed (P-ENV)
# --------------------------------------------------------------------------


def test_load_state_pops_every_variable_and_defaults_to_none():
    mapping = {"NCG_GATED_FILE": "a.py", "NCG_LOG": "/x", "OTHER": "kept"}
    state = plugin._load_state(mapping)
    assert state == plugin.State("a.py", None, None, "/x")
    assert mapping == {"OTHER": "kept"}
    assert not plugin.is_active(state)
    assert plugin.is_active(plugin._load_state({"NCG_WORKSPACE": "/w", "NCG_LOG": "/l"}))
    assert not plugin.is_active(plugin._load_state({"NCG_WORKSPACE": "/w"}))


def test_plugin_reads_ncg_env_once_and_removes_it(monkeypatch, tmp_path):
    values = {name: str(tmp_path / name.lower()) for name in plugin.NCG_ENV}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    reloaded = importlib.reload(plugin)
    try:
        assert reloaded is plugin
        assert reloaded.current_state() == plugin.State(*(values[n] for n in plugin.NCG_ENV))
        import os

        assert not [n for n in plugin.NCG_ENV if n in os.environ]
        monkeypatch.setenv("NCG_WORKSPACE", "/elsewhere")
        assert reloaded.current_state().workspace == values["NCG_WORKSPACE"]
    finally:
        plugin.set_state(plugin._load_state({}))


def test_plugin_reads_environ_only_in_load_state():
    tree = ast.parse(PLUGIN_TEXT.read_text(encoding="utf-8"))
    load_state = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_load_state"
    )
    inside = {id(n) for n in ast.walk(load_state)}
    module_call = next(
        n
        for n in tree.body
        if isinstance(n, ast.Assign) and n.targets[0].id == "_STATE"  # type: ignore[attr-defined]
    )
    allowed = inside | {id(n) for n in ast.walk(module_call)}
    for node in ast.walk(tree):
        is_environ = isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv")
        assert not is_environ or id(node) in allowed
    assert ast.unparse(module_call) == "_STATE = _load_state(os.environ)"
    names = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("NCG_")
    }
    literals = {v for v in names if v.replace("_", "").isalnum() and v.isupper()}
    # Read from the source, not `plugin.NCG_ENV`: a test that reads the plugin's text runs no
    # plugin code (G-SRCREAD, RV3-3a), so a workspace's trampolined copy cannot fail it.
    declared = next(
        n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "NCG_ENV"  # type: ignore[attr-defined]
    )
    assert literals == set(ast.literal_eval(declared.value))


SELF_CHECK = """
import json, sys
sys.path.insert(0, ".")
from pathlib import Path
from scripts.framework import new_code_gate_logic as ncg

src = Path(sys.argv[1]).read_text(encoding="utf-8")
findings = ncg.decision_logic_findings(src, ncg.statement_map(src)[0])
print(json.dumps([
    f for f in findings
    if (f["region"] in ("module", "class") and ncg.is_decision_logic(f))
    or (f["region"] == "function" and f["unmutatable_reason"])
]))
"""


def test_plugin_has_no_q5_or_nq2_findings():
    # Q5-SELF for this file (TD 5.19). A subprocess, so it earns no coverage context. In a mutation
    # workspace this file sits in mutmut's `mutants/` copy, whose plugin is trampolined; the
    # untouched original is the workspace root beside it, and that is the source to judge.
    repo = THIS_FILE.resolve().parents[2]
    if repo.name == "mutants":
        repo = repo.parent
    proc = subprocess.run(
        [sys.executable, "-c", SELF_CHECK, "scripts/framework/new_code_gate_pytest_plugin.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == []


def test_autouse_fixture_covers_every_ncg_variable():
    tree = ast.parse(THIS_FILE.read_text(encoding="utf-8"))
    fixture = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_ncg_isolation"
    )
    loops = [n for n in ast.walk(fixture) if isinstance(n, ast.For)]
    assert [ast.unparse(loop.iter) for loop in loops] == ["plugin.NCG_ENV"]
    assert len(plugin.NCG_ENV) == 4


# --------------------------------------------------------------------------
# Idempotent wrapping per copy (P-ENV c)
# --------------------------------------------------------------------------


def test_plugin_wrapping_is_idempotent_per_copy(active):
    originals = (shutil.copytree, subprocess.Popen, importlib.util.spec_from_file_location)
    for _ in range(3):
        plugin.pytest_configure(None)
    assert shutil.copytree.__ncg_wrapped__ is plugin._SENTINEL
    assert shutil.copytree.__wrapped__ is originals[0]
    assert subprocess.Popen.__mro__[1] is originals[1]
    assert importlib.util.spec_from_file_location.__wrapped__ is originals[2]
    assert len(plugin._INSTALLED) == 6
    assert sum(isinstance(f, plugin._Observer) for f in sys.meta_path) == 1
    plugin.uninstall()
    assert (shutil.copytree, subprocess.Popen) == originals[:2]
    assert not [f for f in sys.meta_path if isinstance(f, plugin._Observer)]


def test_a_copy_still_wraps_over_another_copys_wrapper(active):
    real = shutil.copytree

    def stand_in(*args, **kwargs):
        return real(*args, **kwargs)

    stand_in.__ncg_wrapped__ = object()
    shutil.copytree = stand_in
    try:
        plugin.install()
        assert shutil.copytree is not stand_in
        assert shutil.copytree.__wrapped__ is stand_in
        assert shutil.copytree.__ncg_wrapped__ is plugin._SENTINEL
        plugin.uninstall()
        assert shutil.copytree is stand_in
    finally:
        shutil.copytree = real


def test_inert_copy_installs_nothing_and_logs_nothing(tmp_path):
    before = shutil.copytree
    plugin.pytest_configure(None)
    plugin.pytest_runtest_logstart("tests/x.py::t", None)
    plugin.emit({"event": "x"})
    assert shutil.copytree is before and plugin._INSTALLED == []
    assert not [f for f in sys.meta_path if isinstance(f, plugin._Observer)]
    assert not list(tmp_path.iterdir())


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


def test_plugin_loaded_event_carries_resolved_file(active):
    plugin.pytest_configure(None)
    loaded = [e for e in active.events() if e["event"] == "plugin_loaded"]
    assert [e["path"] for e in loaded] == [str(PLUGIN_SOURCE.resolve())]


def test_executed_node_ids_and_phases(active):
    collector = types.SimpleNamespace(nodeid="tests/x.py")
    plugin.pytest_collectstart(collector)
    assert plugin._RUNTIME["phase"] == "collect:tests/x.py"
    plugin.pytest_collectreport(None)
    assert plugin._RUNTIME["phase"] == "session"
    plugin.pytest_runtest_logstart("tests/x.py::t1", None)
    assert plugin._RUNTIME["phase"] == "test:tests/x.py::t1"
    plugin.pytest_runtest_teardown(None, None)
    plugin.pytest_runtest_logfinish("tests/x.py::t1", None)
    assert plugin._RUNTIME["nodeid"] is None
    executed = [e["node"] for e in active.events() if e["event"] == "executed"]
    assert executed == ["tests/x.py::t1"]


def test_encode_event_is_one_bounded_json_line():
    huge = {"event": "x", "message": "é" * 5000, "other": "y" * 5000, "n": 3}
    data = plugin.encode_event(huge)
    assert data.endswith(b"\n") and data.count(b"\n") == 1
    assert len(data) < plugin.MAX_EVENT_BYTES
    parsed = json.loads(data)
    assert parsed["event"] == "x" and parsed["n"] == 3
    assert len(plugin.encode_event({"a": "b"})) < 40


def test_emit_survives_an_unwritable_log(active, tmp_path):
    blocked = tmp_path / "is_a_dir"
    blocked.mkdir()
    plugin.set_state(plugin.State("pkg/mod.py", "pkg.mod", str(active.ws), str(blocked)))
    plugin.emit({"event": "x"})


# --------------------------------------------------------------------------
# Repo-copy tripwire (TRIP-MUT)
# --------------------------------------------------------------------------


def test_tripwire_flags_copy_of_mutants_root(active, tmp_path):
    plugin.install()
    deep = active.ws / "mutants" / "tests" / "fixtures" / "x"
    deep.mkdir(parents=True)
    (deep / "f.txt").write_text("x", encoding="utf-8")
    for source in (active.ws / "mutants", active.ws, tmp_path):
        with pytest.raises(plugin.NCGRepoCopyError, match="mark it @pytest.mark.repo_copy"):
            shutil.copytree(source, tmp_path / "out")
    shutil.copytree(deep, tmp_path / "ok")
    assert (tmp_path / "ok" / "f.txt").read_text(encoding="utf-8") == "x"
    events = [e for e in active.events() if e["event"] == "repo_copy"]
    assert len(events) == 3 and events[0]["node"] == "<session>"
    assert events[0]["via"] == "shutil.copytree"


def test_tripwire_error_names_the_running_test(active, tmp_path):
    plugin.install()
    plugin.pytest_runtest_logstart("tests/a.py::test_x", None)
    with pytest.raises(plugin.NCGRepoCopyError) as err:
        shutil.copytree(active.ws, tmp_path / "out", dirs_exist_ok=True)
    assert str(err.value) == (
        "tests/a.py::test_x: copies the repository; mark it @pytest.mark.repo_copy"
    )


def test_copytree_src_keyword_is_checked(active, tmp_path):
    plugin.install()
    with pytest.raises(plugin.NCGRepoCopyError):
        shutil.copytree(src=active.ws, dst=tmp_path / "out")


@pytest.mark.parametrize(
    "build,expected",
    [
        (lambda ws, base: ["git", "clone", "-q", str(ws / "mutants"), str(base / "d")], True),
        (lambda ws, base: ["git", "clone", f"file://{ws / 'mutants'}", str(base / "d")], True),
        (lambda ws, base: ["git", "-C", str(ws / "mutants"), "archive", "HEAD"], True),
        (lambda ws, base: ["git", "-c", "a.b=c", "-C", str(ws), "worktree", "add", "x"], True),
        (lambda ws, base: ["git", "worktree", "list"], False),
        (lambda ws, base: ["git", "clone", str(base / "other"), str(base / "d")], False),
        (lambda ws, base: ["echo", "clone", str(ws)], False),
        (lambda ws, base: ["git", "status"], False),
        (lambda ws, base: [], False),
        (lambda ws, base: [object()], False),
    ],
)
def test_git_copy_source_classification(active, tmp_path, build, expected):
    argv = build(active.ws, tmp_path)
    cwd = active.ws / "mutants" if argv[:2] == ["git", "worktree"] else tmp_path
    found = plugin.git_copy_source(argv, cwd)
    assert (found is not None) is expected


def test_git_copy_source_uses_cwd_and_shell_strings(active, tmp_path, monkeypatch):
    assert plugin.git_copy_source("git archive HEAD", active.ws / "mutants") is not None
    assert plugin.git_copy_source("git archive HEAD", tmp_path) == str(tmp_path.resolve())
    assert plugin.git_copy_source("git archive HEAD", tmp_path / "elsewhere") is None
    assert plugin.git_copy_source("git 'unbalanced", active.ws) is None
    # No cwd means the process's own cwd: outside the workspace it is not a copy, inside it is.
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.chdir(tmp_path / "elsewhere")
    assert plugin.git_copy_source(["git", "archive", "HEAD"], None) is None
    monkeypatch.chdir(active.ws)
    assert plugin.git_copy_source(["git", "archive", "HEAD"], None) == str(active.ws.resolve())


def test_popen_wrapper_raises_before_spawning(active, tmp_path):
    plugin.install()
    with pytest.raises(plugin.NCGRepoCopyError):
        subprocess.Popen(["git", "archive", "HEAD"], cwd=active.ws / "mutants")
    with pytest.raises(plugin.NCGRepoCopyError):
        subprocess.run(["git", "clone", str(active.ws), str(tmp_path / "d")], check=False)
    done = subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True, check=True)
    assert done.stdout.strip() == b"1"
    assert isinstance(subprocess.Popen, type) and subprocess.Popen.__name__ == "Popen"


# --------------------------------------------------------------------------
# Path-load recorder
# --------------------------------------------------------------------------


def _write_gated(active, text="X = 1\n"):
    path = active.ws / "mutants" / "pkg" / "mod.py"
    path.write_text(text, encoding="utf-8")
    return path


def test_loader_wrappers_record_non_canonical_loads(active):
    path = _write_gated(active)
    plugin.install()
    importlib.util.spec_from_file_location("alias_mod", path)
    importlib.util.spec_from_file_location("pkg.mod", path)
    importlib.util.spec_from_file_location("alias2", active.ws / "pkg" / "mod.py")
    importlib.util.spec_from_file_location("elsewhere", active.ws / "other.py")
    importlib.machinery.SourceFileLoader("alias3", str(path))
    importlib.machinery.SourcelessFileLoader("alias4", str(path))
    found = [e for e in active.events() if e["event"] == "path_load"]
    assert [(e["kind"], e["loaded_as"]) for e in found] == [
        ("spec_from_file_location", "alias_mod"),
        ("spec_from_file_location", "alias2"),
        ("SourceFileLoader", "alias3"),
        ("SourcelessFileLoader", "alias4"),
    ]
    assert all(e["canonical"] == "pkg.mod" and e["phase"] == "session" for e in found)
    assert all(e["importer"] == str(THIS_FILE) or e["importer"] == __file__ for e in found)


def _called_from(filename, function, *args):
    """Call `function(*args)` from a frame whose code object says it lives in `filename`."""
    namespace = {}
    exec(compile("def call(f, *a):\n    return f(*a)\n", str(filename), "exec"), namespace)
    return namespace["call"](function, *args)


def test_importer_skips_mutmut_trampoline_frames(active, tmp_path):
    """IMP-TRAMP (RV3-3b): when the plugin itself is gated, its wrappers sit under mutmut's trampoline."""
    path = _write_gated(active)
    plugin.install()
    trampoline = tmp_path / "mutmut" / "mutation" / "trampoline.py"
    lookalike = tmp_path / "pkg" / "trampoline.py"
    _called_from(trampoline, importlib.util.spec_from_file_location, "via_trampoline", path)
    _called_from(lookalike, importlib.util.spec_from_file_location, "via_lookalike", path)
    found = [e for e in active.events() if e["event"] == "path_load"]
    assert [(e["loaded_as"], e["importer"]) for e in found] == [
        ("via_trampoline", str(THIS_FILE)),
        ("via_lookalike", str(lookalike)),
    ]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("/site/mutmut/mutation/trampoline.py", True),
        ("C:\\site\\mutmut\\mutation\\trampoline.py", True),
        ("/site/mutmut/mutation/trampoline_templates.py", False),
        ("/site/notmutmut/mutation/trampoline.py", False),
        ("/site/mutmut/trampoline.py", False),
        ("/site/mutmut/mutation/trampoline.pyc", False),
    ],
)
def test_only_mutmuts_own_trampoline_module_is_skipped(name, expected):
    assert plugin.is_trampoline_file(name) is expected


def test_run_path_wrapper_records_and_still_runs(active):
    path = _write_gated(active, "VALUE = 5\n")
    plugin.install()
    import runpy

    assert runpy.run_path(str(path))["VALUE"] == 5
    assert runpy.run_path(str(path), run_name="named")["VALUE"] == 5
    kinds = [(e["kind"], e["loaded_as"]) for e in active.events() if e["event"] == "path_load"]
    assert kinds == [("run_path", "<run_path>"), ("run_path", "named")]


def test_sys_modules_scan_records_aliases_once(active):
    path = _write_gated(active)
    alias = types.ModuleType("alias_in_modules")
    alias.__file__ = str(path)
    canonical = types.ModuleType("pkg.mod")
    canonical.__file__ = str(path)
    sys.modules["alias_in_modules"] = alias
    sys.modules["pkg.mod"] = canonical
    try:
        plugin.scan_modules()
        plugin.scan_modules()
    finally:
        del sys.modules["alias_in_modules"]
        del sys.modules["pkg.mod"]
    found = [(e["kind"], e["loaded_as"]) for e in active.events() if e["event"] == "path_load"]
    assert found == [("sys_modules", "alias_in_modules")]


def test_meta_path_observer_records_bare_import(active, monkeypatch):
    gated = active.ws / "mutants" / "pkg"
    (gated / "bare_gated.py").write_text("X = 7\n", encoding="utf-8")
    plugin.set_state(
        plugin.State("pkg/bare_gated.py", "pkg.bare_gated", str(active.ws), str(active.log))
    )
    monkeypatch.syspath_prepend(str(gated))
    plugin.install()
    try:
        import bare_gated  # type: ignore[import-not-found]

        assert bare_gated.X == 7
    finally:
        sys.modules.pop("bare_gated", None)
    found = [e for e in active.events() if e["event"] == "path_load"]
    assert [(e["kind"], e["loaded_as"]) for e in found] == [("meta_path", "bare_gated")]
    assert found[0]["importer"] == __file__


def test_stem_of_handles_packages():
    assert plugin.stem_of("a/b/mod.py") == "mod"
    assert plugin.stem_of("a/pkg/__init__.py") == "pkg"


# --------------------------------------------------------------------------
# Passive observer (S-PASSIVE)
# --------------------------------------------------------------------------


def test_meta_path_observer_is_passive_static():
    tree = ast.parse(PLUGIN_TEXT.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_Observer")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "find_spec")
    returns = [n for n in ast.walk(method) if isinstance(n, ast.Return)]
    assert returns
    for ret in returns:
        assert ret.value is None or (
            isinstance(ret.value, ast.Constant) and ret.value.value is None
        )
    last = method.body[-1]
    assert isinstance(last, ast.Return) and ast.unparse(last) == "return None"
    for node in ast.walk(method):
        if isinstance(node, ast.Assign):
            targets = [ast.unparse(t) for t in node.targets]
            assert not [t for t in targets if t.startswith("sys.modules[")]


def test_meta_path_observer_is_passive_behaviour(active):
    observer = plugin._Observer()
    _write_gated(active)
    for name in ("os", "definitely_missing_module_xyz", "pkg.mod", "mod", "json.decoder"):
        assert observer.find_spec(name, None, None) is None
    plugin.install()
    plain = importlib.util.find_spec("json")
    assert plain is not None and plain.origin == importlib.util.find_spec("json").origin
    sys.meta_path.remove(next(f for f in sys.meta_path if isinstance(f, plugin._Observer)))
    assert importlib.util.find_spec("json").origin == plain.origin


def test_observer_error_is_logged_and_none_is_still_returned(active, monkeypatch):
    def boom(fullname, path):
        raise RuntimeError("resolver broke")

    monkeypatch.setattr(plugin, "observe_import", boom)
    assert plugin._Observer().find_spec("anything", None, None) is None
    errors = [e for e in active.events() if e["event"] == "observer_error"]
    assert [e["message"] for e in errors] == ["RuntimeError: resolver broke"]
    assert plugin._RUNTIME["in_observer"] is False


def test_observer_is_not_reentrant(active, monkeypatch):
    calls = []
    monkeypatch.setattr(plugin, "observe_import", lambda name, path: calls.append(name))
    plugin._RUNTIME["in_observer"] = True
    assert plugin._Observer().find_spec("x", None, None) is None
    assert calls == []


# --------------------------------------------------------------------------
# The hooks in a real inner pytest session
# --------------------------------------------------------------------------


def test_hooks_in_an_inner_session(active, pytester, tmp_path):
    pytester.makepyfile(
        test_inner=f"""
        import shutil

        def test_ok():
            assert True

        def test_copies_the_repo():
            shutil.copytree({str(active.ws / "mutants")!r}, {str(tmp_path / "dst")!r})
        """
    )
    result = pytester.runpytest_inprocess("-p", "scripts.framework.new_code_gate_pytest_plugin")
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(["*copies the repository; mark it @pytest.mark.repo_copy*"])
    events = active.events()
    executed = [e["node"] for e in events if e["event"] == "executed"]
    assert executed == ["test_inner.py::test_ok", "test_inner.py::test_copies_the_repo"]
    copies = [e for e in events if e["event"] == "repo_copy"]
    assert [e["node"] for e in copies] == ["test_inner.py::test_copies_the_repo"]
    assert [e["path"] for e in events if e["event"] == "plugin_loaded"] == [
        str(PLUGIN_SOURCE.resolve())
    ]
    assert not [e for e in events if e["event"] in ("observer_error", "path_load")]
