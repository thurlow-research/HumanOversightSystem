"""Behaviour pins for the new-code gate's tripwire plugin found by a mutation run of the gate itself.

Each test pins one observable behaviour of `new_code_gate_pytest_plugin` that the existing
plugin tests left unasserted (keyword-argument paths of the `check_*` hooks, event encoding
bounds, log file mode, git global-option parsing, observer re-entrancy, install idempotence).
The module is imported canonically and an autouse fixture keeps every copy inert around each
test, like `test_new_code_gate_plugin.py`.
"""

import json
import os
import re
import sys
import types
from pathlib import Path

import pytest

from scripts.framework import new_code_gate_pytest_plugin as plugin


@pytest.fixture(autouse=True)
def drop_tmp_path_link_at_teardown(request, tmp_path):
    """Remove this test's `<name>current` link from the session's base temp once the test passed.

    pytest deletes a passing test's tmp_path itself (retention policy "failed") but leaves the
    link to it, and every such link is allocated space in the session's temp budget. A failed test
    keeps both the directory and its link, for diagnosis.
    """
    failed_before = request.session.testsfailed
    yield
    if request.session.testsfailed == failed_before:
        link = tmp_path.parent / (re.sub(r"\d+$", "", tmp_path.name) + "current")
        if link.is_symlink() and link.resolve() == tmp_path.resolve():
            link.unlink()


@pytest.fixture(autouse=True)
def _isolation(monkeypatch, tmp_path):
    for name in plugin.NCG_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    plugin.uninstall()
    plugin.set_state(plugin._load_state({}))
    yield
    plugin.uninstall()
    plugin.set_state(plugin._load_state({}))
    plugin._RUNTIME.update(phase="session", nodeid=None, in_observer=False)


@pytest.fixture
def active(tmp_path):
    ws = tmp_path / "ws"
    (ws / "mutants" / "pkg").mkdir(parents=True)
    (ws / "pkg").mkdir()
    gated = ws / "mutants" / "pkg" / "mod.py"
    gated.write_text("X = 1\n", encoding="utf-8")
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

    def events():
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="ascii").splitlines()]

    return types.SimpleNamespace(ws=ws, gated=gated, log=log, events=events)


# --------------------------------------------------------------------------
# encode_event
# --------------------------------------------------------------------------


def test_encode_event_cuts_each_string_field_to_the_field_limit():
    data = plugin.encode_event({"msg": "a" * 700})
    assert json.loads(data)["msg"] == "a" * plugin.MAX_FIELD_CHARS


def _event_of_exact_size(size):
    """An event whose first-pass encoding is exactly `size` bytes (one trailing newline included)."""
    base = {f"k{i}": "x" * 500 for i in range(7)}
    for pad in range(0, 600):
        event = dict(base, pad="y" * pad)
        if len(json.dumps(event).encode("ascii") + b"\n") == size:
            return event
    raise AssertionError("no event of that size")


def test_encode_event_shortens_an_event_of_exactly_the_byte_ceiling():
    event = _event_of_exact_size(plugin.MAX_EVENT_BYTES)
    data = plugin.encode_event(event)
    assert len(data) < plugin.MAX_EVENT_BYTES


def test_encode_event_keeps_an_event_one_byte_under_the_ceiling_whole():
    event = _event_of_exact_size(plugin.MAX_EVENT_BYTES - 1)
    data = plugin.encode_event(event)
    assert json.loads(data) == event


def test_encode_event_halves_the_limit_down_to_four_when_nothing_fits():
    event = {f"k{i}": "abcdefghijklmnop" for i in range(2000)}
    data = plugin.encode_event(event)
    values = set(json.loads(data).values())
    assert values == {"abcd"}


# --------------------------------------------------------------------------
# emit
# --------------------------------------------------------------------------


def test_emit_records_the_process_id_and_the_event_fields(active):
    plugin.emit({"event": "ping"})
    assert active.events() == [{"event": "ping", "pid": os.getpid()}]


def test_emit_creates_the_log_readable_by_its_owner_only(active):
    old = os.umask(0)
    try:
        plugin.emit({"event": "ping"})
    finally:
        os.umask(old)
    assert (active.log.stat().st_mode & 0o777) == 0o600


# --------------------------------------------------------------------------
# gated_copies, importer_file
# --------------------------------------------------------------------------


def test_gated_copies_is_empty_when_no_gated_file_is_named(tmp_path):
    state = plugin.State(None, "pkg.mod", str(tmp_path), str(tmp_path / "log"))
    assert plugin.gated_copies(state) == []


def test_gated_copies_lists_the_mutants_copy_first_then_the_extracted_file(active):
    got = plugin.gated_copies(plugin.current_state())
    assert got == [
        (active.ws / "mutants" / "pkg" / "mod.py").resolve(),
        (active.ws / "pkg" / "mod.py").resolve(),
    ]


class _Code:
    def __init__(self, filename):
        self.co_filename = filename


class _Frame:
    def __init__(self, filename, back=None):
        self.f_code = _Code(filename)
        self.f_back = back


def test_importer_file_starts_at_the_direct_caller_and_skips_plugin_importlib_and_trampoline(
    monkeypatch,
):
    real = _Frame("/work/real_importer.py")
    chain = _Frame(
        plugin._THIS_FILE,
        _Frame("<frozen importlib._bootstrap>", _Frame("/x/mutmut/mutation/trampoline.py", real)),
    )
    other = _Frame("/work/wrong_start.py")
    heads = {1: chain, 2: other}
    monkeypatch.setattr(sys, "_getframe", lambda depth: heads[depth])
    assert plugin.importer_file() == "/work/real_importer.py"


def test_importer_file_answers_a_question_mark_when_every_frame_is_skipped(monkeypatch):
    chain = _Frame(plugin._THIS_FILE, _Frame("<frozen importlib._bootstrap_external>"))
    monkeypatch.setattr(sys, "_getframe", lambda depth: chain)
    assert plugin.importer_file() == "?"


# --------------------------------------------------------------------------
# Repo-copy tripwire events
# --------------------------------------------------------------------------


def test_copytree_of_the_workspace_logs_the_source_and_raises(active):
    with pytest.raises(plugin.NCGRepoCopyError):
        plugin.check_copytree((str(active.ws),), {})
    (event,) = active.events()
    assert (event["event"], event["source"], event["via"]) == (
        "repo_copy",
        str(active.ws),
        "shutil.copytree",
    )


def test_copytree_source_given_as_keyword_is_checked_too(active):
    with pytest.raises(plugin.NCGRepoCopyError):
        plugin.check_copytree((), {"src": str(active.ws)})
    assert active.events()[0]["source"] == str(active.ws)


def test_copytree_of_an_unrelated_directory_is_allowed(active, tmp_path):
    plugin.check_copytree((str(tmp_path / "elsewhere"),), {})
    assert active.events() == []


def test_popen_git_clone_of_the_workspace_logs_the_token_and_via(active):
    with pytest.raises(plugin.NCGRepoCopyError):
        plugin.check_popen(
            (["git", "clone", str(active.ws), "dest"],), {"cwd": str(active.ws.parent)}
        )
    (event,) = active.events()
    assert event["via"] == "subprocess.Popen" and event["source"] == str(active.ws)


def test_popen_reads_argv_and_cwd_from_keywords(active):
    with pytest.raises(plugin.NCGRepoCopyError):
        plugin.check_popen((), {"args": ["git", "archive", "HEAD"], "cwd": str(active.ws)})
    (event,) = active.events()
    assert event["source"] == str(active.ws.resolve())


def test_popen_uses_the_process_cwd_when_no_cwd_is_given(active, monkeypatch):
    monkeypatch.chdir(active.ws)
    with pytest.raises(plugin.NCGRepoCopyError):
        plugin.check_popen((["git", "worktree", "add", "x"],), {})


def test_popen_of_a_non_copying_command_is_allowed(active):
    plugin.check_popen((["git", "status"],), {"cwd": str(active.ws)})
    assert active.events() == []


# --------------------------------------------------------------------------
# git option parsing
# --------------------------------------------------------------------------


def test_git_base_strips_dash_c_and_follows_it_into_the_directory(tmp_path):
    rest, base = plugin._git_base(["git", "-C", "sub", "status"], str(tmp_path))
    assert rest == ["status"] and base == (tmp_path / "sub").resolve()


def test_git_base_follows_dash_c_given_as_the_only_option_value(tmp_path):
    rest, base = plugin._git_base(["git", "-C", "sub"], str(tmp_path))
    assert rest == [] and base == (tmp_path / "sub").resolve()


def test_git_base_dash_c_without_a_value_does_not_fail(tmp_path):
    rest, base = plugin._git_base(["git", "-C"], str(tmp_path))
    assert rest == [] and base == tmp_path.resolve()


def test_git_base_only_dash_c_changes_the_directory(tmp_path):
    rest, base = plugin._git_base(["git", "--no-pager", "-C", "sub", "log"], str(tmp_path))
    assert rest == ["log"] and base == (tmp_path / "sub").resolve()


def test_git_base_skips_the_value_of_a_value_option_but_not_of_a_flag(tmp_path):
    rest, _ = plugin._git_base(["git", "-c", "a=b", "status"], str(tmp_path))
    assert rest == ["status"]
    rest, _ = plugin._git_base(["git", "--no-pager", "status"], str(tmp_path))
    assert rest == ["status"]


def test_git_copy_source_of_a_bare_git_command_is_none(active):
    assert plugin.git_copy_source(["git"], str(active.ws)) is None
    assert plugin.git_copy_source(["git", "-C", str(active.ws)], str(active.ws)) is None


# --------------------------------------------------------------------------
# Path-load recorder: positional and keyword argument forms
# --------------------------------------------------------------------------


def test_spec_from_file_location_is_recorded_from_positional_arguments(active):
    plugin.check_spec(("alias", str(active.gated)), {})
    (event,) = active.events()
    assert (event["kind"], event["loaded_as"]) == ("spec_from_file_location", "alias")


def test_spec_from_file_location_is_recorded_from_keyword_arguments(active):
    plugin.check_spec((), {"name": "alias", "location": str(active.gated)})
    (event,) = active.events()
    assert (event["kind"], event["loaded_as"]) == ("spec_from_file_location", "alias")


def test_spec_with_a_positional_name_takes_its_location_from_the_keyword(active):
    plugin.check_spec(("alias",), {"location": str(active.gated)})
    assert active.events()[0]["loaded_as"] == "alias"


@pytest.mark.parametrize(
    "check,kind",
    [
        (plugin.check_source_loader, "SourceFileLoader"),
        (plugin.check_sourceless_loader, "SourcelessFileLoader"),
    ],
)
def test_loader_constructions_are_recorded_for_both_argument_forms(active, check, kind):
    check(("alias", str(active.gated)), {})
    check((), {"fullname": "alias2", "path": str(active.gated)})
    check(("alias3",), {"path": str(active.gated)})
    got = [(e["kind"], e["loaded_as"]) for e in active.events()]
    assert got == [(kind, "alias"), (kind, "alias2"), (kind, "alias3")]


def test_run_path_is_recorded_with_positional_keyword_and_default_names(active):
    plugin.check_run_path((str(active.gated), {}, "named"), {})
    plugin.check_run_path((), {"path_name": str(active.gated), "run_name": "kw"})
    plugin.check_run_path((str(active.gated), {}), {})
    plugin.check_run_path((str(active.gated),), {})
    got = [e["loaded_as"] for e in active.events()]
    assert got == ["named", "kw", "<run_path>", "<run_path>"]


def test_a_load_under_the_canonical_name_is_not_recorded(active):
    plugin.check_spec(("pkg.mod", str(active.gated)), {})
    assert active.events() == []


# --------------------------------------------------------------------------
# observe_import
# --------------------------------------------------------------------------


def test_observe_import_records_a_bare_named_load_once(active):
    path = [str(active.gated.parent)]
    plugin.observe_import("other.mod", path)
    plugin.observe_import("other.mod", path)
    got = [(e["kind"], e["loaded_as"]) for e in active.events()]
    assert got == [("meta_path", "other.mod")]
    assert "other.mod" in plugin._SEEN


def test_observe_import_ignores_a_name_whose_last_part_is_not_the_stem(active):
    plugin.observe_import("other.nope", [str(active.gated.parent)])
    assert active.events() == []


def test_observe_import_resolves_through_the_given_path_not_sys_path(active, monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(active.gated.parent))
    (tmp_path / "empty").mkdir()
    plugin.observe_import("mod", [str(tmp_path / "empty")])
    assert active.events() == []
    plugin.observe_import("mod", None)
    assert [e["kind"] for e in active.events()] == ["meta_path"]


def test_observe_import_with_no_spec_found_records_nothing(active, tmp_path):
    plugin.observe_import("pkg2.mod", [str(tmp_path / "empty")])
    assert active.events() == []


def test_observe_import_does_nothing_while_inactive(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("PathFinder consulted while inactive")

    monkeypatch.setattr(plugin.importlib.machinery.PathFinder, "find_spec", boom)
    plugin.observe_import("other.mod", ["/x"])


def test_observe_import_does_nothing_for_the_canonical_name(active, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("PathFinder consulted for the canonical name")

    monkeypatch.setattr(plugin.importlib.machinery.PathFinder, "find_spec", boom)
    plugin.observe_import("pkg.mod", [str(active.gated.parent)])


def test_observe_import_does_nothing_when_no_gated_file_is_named(tmp_path):
    state = plugin.State(None, "pkg.mod", str(tmp_path), str(tmp_path / "log"))
    plugin.set_state(state)
    plugin.observe_import("other.mod", [str(tmp_path)])
    assert not (tmp_path / "log").exists()


def test_observer_marks_itself_busy_while_observing_and_passes_the_search_path(monkeypatch):
    seen = {}

    def fake_observe(fullname, path):
        seen.update(busy=plugin._RUNTIME["in_observer"], fullname=fullname, path=path)

    monkeypatch.setattr(plugin, "observe_import", fake_observe)
    result = plugin._Observer().find_spec("a.b", ["/p"])
    assert result is None
    assert seen == {"busy": True, "fullname": "a.b", "path": ["/p"]}
    assert plugin._RUNTIME["in_observer"] is False


def test_observer_does_not_reenter_while_busy(monkeypatch):
    called = []
    monkeypatch.setattr(plugin, "observe_import", lambda *a: called.append(a))
    plugin._RUNTIME["in_observer"] = True
    assert plugin._Observer().find_spec("a.b", None) is None
    assert called == []


# --------------------------------------------------------------------------
# Wrappers, install, hooks
# --------------------------------------------------------------------------


def test_wrapped_function_forwards_positional_and_keyword_arguments_after_the_check():
    seen = []
    wrapped = plugin._wrap_function(lambda *a, **k: (a, k), lambda a, k: seen.append((a, k)))
    assert wrapped(1, x=2) == ((1,), {"x": 2})
    assert seen == [((1,), {"x": 2})]


def test_install_wraps_a_target_that_was_unwrapped_after_an_earlier_install():
    import subprocess

    original = subprocess.Popen
    plugin.install()
    assert getattr(subprocess.Popen, "__ncg_wrapped__", None) is plugin._SENTINEL
    subprocess.Popen = original  # a later target is lost; an earlier one stays wrapped
    plugin.install()
    assert getattr(subprocess.Popen, "__ncg_wrapped__", None) is plugin._SENTINEL


def test_install_puts_the_observer_first_on_the_meta_path():
    plugin.install()
    assert isinstance(sys.meta_path[0], plugin._Observer)


def test_logfinish_returns_the_runtime_to_the_session_phase(active):
    plugin._RUNTIME.update(phase="test:x", nodeid="x")
    plugin.pytest_runtest_logfinish("x", None)
    assert plugin._RUNTIME["phase"] == "session" and plugin._RUNTIME["nodeid"] is None


def test_logstart_records_the_running_test_and_logs_it(active):
    plugin.pytest_runtest_logstart("t.py::a", ("t.py", 1, "a"))
    assert plugin._RUNTIME["phase"] == "test:t.py::a" and plugin._RUNTIME["nodeid"] == "t.py::a"
    assert active.events() == [{"event": "executed", "node": "t.py::a", "pid": os.getpid()}]


def test_resolve_returns_a_path_for_a_pathlike(tmp_path):
    assert plugin._resolve(Path(tmp_path)) == tmp_path.resolve()
