"""Cheap in-process pins for mutants of `new_code_gate` that survived, or timed out, in its own run.

Condition 6 of ADR-2304 (section 2j, C6-3 b and c). A surviving mutant of the gate file runs every
test that reaches its function, and nearly every test of `test_new_code_gate_measure.py` does. Each
test here calls one function of the gate directly, with the git, subprocess and clock edges replaced
by recorders, so it fails in milliseconds on the mutant it names. None of them builds a repository.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.framework import new_code_gate as gate
from scripts.framework import new_code_gate_logic as ncg
from scripts.framework import new_code_gate_shard as ncs

SHA = "a" * 40
KEY = "scripts.framework.calc.x_add__mutmut_1"
PREFIX = "scripts.framework.calc.x_add"


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path, monkeypatch):
    """A mutant that turns a computed path relative lands here, never in mutmut's cwd (RV3-7a)."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def drop_tmp_path_link_at_teardown(request, tmp_path):
    """Remove this test's `<name>current` link from the session's base temp once the test passed."""
    failed_before = request.session.testsfailed
    yield
    if request.session.testsfailed == failed_before:
        link = tmp_path.parent / (re.sub(r"\d+$", "", tmp_path.name) + "current")
        if link.is_symlink() and link.resolve() == tmp_path.resolve():
            link.unlink()


class ScriptedClock:
    """`monotonic` and `utc_iso` return the given values in order; reading more is a failed test."""

    def __init__(self, *values, utc=(), epoch=1_000):
        self.values = list(values)
        self.utc = list(utc)
        self.epoch_value = epoch

    def monotonic(self):
        return self.values.pop(0)

    def utc_iso(self):
        return self.utc.pop(0)

    def epoch(self):
        return self.epoch_value


class NoRunner:
    def run(self, phase, spec):
        raise AssertionError("no subprocess phase is expected here")


def make_ctx(tmp_path, clock=None, **opts):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    values = {
        "repo": repo,
        "gated_sha": SHA,
        "keep_workspace": False,
        "python_exe": sys.executable,
        "environ": {},
        "mode": "local",
        "run_id": None,
        "pr_head_sha": SHA,
        "installed": {},
    }
    values.update(opts)
    return gate.Context(SimpleNamespace(**values), NoRunner(), clock or ScriptedClock(100.0), 50)


def make_workspace(tmp_path):
    root = tmp_path / "ws"
    tree = root / "tree"
    tree.mkdir(parents=True)
    return gate.Workspace(root, tree, root / "plugin", root / "events.jsonl")


# --------------------------------------------------------------------------
# git helpers: the messages and the arguments a failing or recording git sees
# --------------------------------------------------------------------------


def test_blob_text_names_the_path_and_twelve_characters_of_the_sha_when_git_cannot_read_it(
    tmp_path,
):
    with pytest.raises(gate.GateError) as caught:
        gate.blob_text(tmp_path, "b" * 40, "scripts/x.py")
    assert str(caught.value) == f"could not read scripts/x.py at {'b' * 12}"


class GitRecorder:
    """Stands in for `git_text`: records every call and answers with `reply`."""

    def __init__(self, reply=""):
        self.calls = []
        self.reply = reply

    def __call__(self, repo, args, fail=None):
        self.calls.append((repo, list(args), fail))
        return self.reply


def test_changed_lines_diffs_the_rename_source_before_the_path_with_one_message(
    tmp_path, monkeypatch
):
    git = GitRecorder()
    monkeypatch.setattr(gate, "git_text", git)
    ctx = make_ctx(tmp_path)
    ctx.base_sha = "c" * 40
    change = ncg.ChangedPath("M", "scripts/new.py", "scripts/old.py", "changed")
    assert gate.changed_lines(ctx, change) == []
    repo, args, fail = git.calls[0]
    assert repo == ctx.repo and fail == "diff could not be computed"
    assert args == [
        *gate.GIT_DIFF_PREFIX,
        "--unified=0",
        "c" * 40,
        SHA,
        "--",
        "scripts/old.py",
        "scripts/new.py",
    ]
    specs = [call[1][1] for call in git.calls[1:]]
    assert specs == [f"{'c' * 40}:scripts/old.py", f"{SHA}:scripts/new.py"]


def test_changed_lines_of_a_new_file_diffs_only_that_path_and_reads_no_blobs(tmp_path, monkeypatch):
    git = GitRecorder()
    monkeypatch.setattr(gate, "git_text", git)
    ctx = make_ctx(tmp_path)
    ctx.base_sha = "c" * 40
    gate.changed_lines(ctx, ncg.ChangedPath("A", "scripts/new.py", None, "new"))
    assert len(git.calls) == 1 and git.calls[0][1][-2:] == ["--", "scripts/new.py"]


def test_extract_archive_writes_tree_tar_under_the_root_extracts_it_and_removes_it(
    tmp_path, monkeypatch
):
    seen = []

    def fake_run_git(repo, args, fail=None):
        seen.append((repo, list(args), fail))
        output = next(a for a in args if a.startswith("--output=")).split("=", 1)[1]
        payload = tmp_path / "payload.txt"
        payload.write_text("hello", encoding="utf-8")
        with tarfile.open(output, "w") as tar:
            tar.add(payload, arcname="payload.txt")
        return b""

    monkeypatch.setattr(gate, "run_git", fake_run_git)
    ctx = make_ctx(tmp_path)
    root, tree = tmp_path / "root", tmp_path / "root" / "tree"
    root.mkdir()
    gate.extract_archive(ctx, root, tree)
    repo, args, fail = seen[0]
    assert fail == "could not archive the gated tree"
    assert args[:3] == ["archive", "--format=tar", f"--output={root / 'tree.tar'}"]
    assert (tree / "payload.txt").read_text(encoding="utf-8") == "hello"
    assert not (root / "tree.tar").exists()


# --------------------------------------------------------------------------
# dirty_paths: a stalled scan would hang a worker, so a counting list bounds it
# --------------------------------------------------------------------------


class _BoundedEntries(list):
    def __init__(self, items, limit=40):
        super().__init__(items)
        self.reads = 0
        self.limit = limit

    def __getitem__(self, index):
        self.reads += 1
        assert self.reads <= self.limit, "dirty_paths stopped advancing"
        return super().__getitem__(index)


class _BoundedPorcelain(str):
    def split(self, sep=None, maxsplit=-1):
        return _BoundedEntries(super().split(sep, maxsplit))


@pytest.mark.parametrize(
    "porcelain,expected",
    [
        (" M a.py\0", ["a.py"]),
        (" M a.py\0?? b.sh\0 M c.txt\0", ["a.py", "b.sh"]),
        ("R  new.py\0old.py\0 M b.py\0", ["new.py", "old.py", "b.py"]),
    ],
)
def test_dirty_paths_advances_one_entry_at_a_time(porcelain, expected):
    assert gate.dirty_paths(_BoundedPorcelain(porcelain)) == expected


def test_dirty_paths_reads_a_rename_origin_that_is_the_last_entry_without_running_off_the_end():
    assert gate.dirty_paths("R  new.py") == ["new.py"]


def test_dirty_paths_treats_an_entry_of_four_characters_as_a_path_and_reads_its_rename_origin():
    assert gate.dirty_paths("R  x\0old.py\0") == ["old.py"]


def test_dirty_paths_goes_on_past_a_short_entry():
    assert gate.dirty_paths("\0 M a.py\0") == ["a.py"]


@pytest.mark.parametrize("flag", ["R", "C"])
def test_dirty_paths_looks_for_rename_and_copy_codes_in_the_two_status_columns_only(flag):
    assert gate.dirty_paths(f"MM{flag}a.py\0b.py\0") == ["a.py"]


# --------------------------------------------------------------------------
# cleanup_workspaces
# --------------------------------------------------------------------------


def test_kept_workspaces_are_reported_on_stderr_one_line_each_and_left_in_place(tmp_path, capsys):
    ctx = make_ctx(tmp_path, keep_workspace=True)
    first, second = make_workspace(tmp_path), make_workspace(tmp_path / "two")
    ctx.workspaces = [first, second]
    gate.cleanup_workspaces(ctx)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"kept workspace: {first.root}\nkept workspace: {second.root}\n"
    assert first.root.is_dir() and second.root.is_dir()


def test_workspaces_are_removed_and_a_missing_one_is_not_an_error(tmp_path, capsys):
    ctx = make_ctx(tmp_path)
    present = make_workspace(tmp_path)
    gone = gate.Workspace(
        tmp_path / "gone", tmp_path / "gone" / "t", tmp_path / "p", tmp_path / "e"
    )
    ctx.workspaces = [gone, present]
    gate.cleanup_workspaces(ctx)
    assert not present.root.exists()
    assert capsys.readouterr().err == ""


# --------------------------------------------------------------------------
# build_context: the setup default, and the run id handed to the sidecar check
# --------------------------------------------------------------------------


class _Stop(Exception):
    pass


def test_build_context_charges_no_setup_time_unless_asked_to(tmp_path, monkeypatch):
    made = []

    class Spy(gate.Context):
        def __init__(self, *args):
            super().__init__(*args)
            made.append(self)

    monkeypatch.setattr(gate, "Context", Spy)
    opts = SimpleNamespace(repo=tmp_path, gated_sha=SHA, installed={})
    with pytest.raises(gate.GateError):
        gate.build_context(opts, NoRunner(), ScriptedClock(100.0))
    assert made[0].setup_seconds == 0 and made[0].deadline == 100.0 + ncg.PLAN_BUDGET_SECONDS


@pytest.mark.parametrize(
    "mode,run_id,expected", [("ci", None, ""), ("ci", "77", "77"), ("local", "77", None)]
)
def test_build_context_hands_the_ci_run_id_to_the_sidecar_head_check(
    tmp_path, monkeypatch, mode, run_id, expected
):
    given = []

    def fake_head(meta, gated_sha, ci_run=None):
        given.append(ci_run)
        return "stop here"

    monkeypatch.setattr(ncg, "check_pins", lambda installed: None)
    monkeypatch.setattr(gate, "require_regular_inputs", lambda opts: None)
    monkeypatch.setattr(gate, "load_meta", lambda path: {"test_seconds_ms": {}})
    monkeypatch.setattr(gate, "valid_durations", lambda value: True)
    monkeypatch.setattr(ncg, "check_sidecar_environment", lambda meta, installed, python: None)
    monkeypatch.setattr(ncg, "check_sidecar_head", fake_head)
    opts = SimpleNamespace(
        repo=tmp_path,
        gated_sha=SHA,
        installed={},
        meta_path=tmp_path / "m",
        python="3.12",
        mode=mode,
        run_id=run_id,
    )
    with pytest.raises(gate.GateError, match="stop here"):
        gate.build_context(opts, NoRunner(), ScriptedClock(100.0))
    assert given == [expected]


# --------------------------------------------------------------------------
# cost_files
# --------------------------------------------------------------------------


class _Cov:
    def contexts_by_line(self, path):
        return {}


def _cost_work(tmp_path):
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    work.to_shards = True
    work.selected = ["tests/t.py::a"]
    work.method = "context"
    work.functions = {"scripts.a.x_f": (1, 2)}
    work.gated_names = ["scripts.a.x_f__mutmut_1"]
    return work


def test_cost_files_passes_the_files_own_selection_method_functions_and_names(
    tmp_path, monkeypatch
):
    got = []

    def fake_cost(*args):
        got.append(args)
        return {"cost_ms": 1}

    monkeypatch.setattr(gate.ncs, "file_cost", fake_cost)
    ctx = make_ctx(tmp_path)
    ctx.cov = _Cov()
    ctx.durations = {"tests/t.py::a": 5}
    work = _cost_work(tmp_path)
    gate.cost_files(ctx, [work])
    assert got == [
        (
            "scripts/a.py",
            ["tests/t.py::a"],
            "context",
            {"tests/t.py::a": 5},
            {"scripts.a.x_f": (1, 2)},
            ["scripts.a.x_f__mutmut_1"],
            {"tests/t.py::a": frozenset()},
        )
    ]
    assert work.cost == {"cost_ms": 1}


def test_cost_files_records_a_cost_failure_as_an_internal_error_naming_the_file(
    tmp_path, monkeypatch
):
    def failing_cost(*args):
        raise gate.GateError("no duration for a selected test")

    monkeypatch.setattr(gate.ncs, "file_cost", failing_cost)
    ctx = make_ctx(tmp_path)
    ctx.cov = _Cov()
    gate.cost_files(ctx, [_cost_work(tmp_path)])
    assert ctx.internal_errors == [
        {
            "code": "internal_error",
            "message": "no duration for a selected test",
            "file": "scripts/a.py",
        }
    ]


# --------------------------------------------------------------------------
# build_verdict
# --------------------------------------------------------------------------


def test_build_verdict_asks_for_rulings_by_pr_head_sha_and_every_file_path(monkeypatch):
    asked = []

    def fake_rulings(pr, head_sha, paths):
        asked.append((pr, head_sha, paths))
        return []

    monkeypatch.setattr(gate, "fetch_rulings", fake_rulings)
    records = {
        "files": [
            ncg.blank_file_record("scripts/b.py", "new"),
            ncg.blank_file_record("a.py", "new"),
        ],
        "internal_errors": [],
        "records_sha256": None,
        "pr": 7,
        "pr_head_sha": "d" * 40,
    }
    doc, summary, code = gate.build_verdict(records)
    assert asked == [(7, "d" * 40, ["scripts/b.py", "a.py"])]
    assert doc["phase"] == "verdict" and code == 0 and summary.endswith("overall pass.\n")


def test_build_verdict_with_no_pr_head_sha_asks_with_the_text_none(monkeypatch):
    asked = []
    monkeypatch.setattr(
        gate, "fetch_rulings", lambda pr, head, paths: asked.append((pr, head)) or []
    )
    gate.build_verdict({"files": [], "internal_errors": [], "records_sha256": None})
    assert asked == [(None, "None")]


# --------------------------------------------------------------------------
# build_workspace, enumerate_file
# --------------------------------------------------------------------------


def test_build_workspace_records_its_seconds_to_the_millisecond_in_the_file_and_the_phase(
    tmp_path, monkeypatch
):
    ws = make_workspace(tmp_path)
    monkeypatch.setattr(gate, "make_workspace", lambda ctx, work: ws)
    ctx = make_ctx(tmp_path, clock=ScriptedClock(0.0, 10.0, 11.23456, 11.23456))
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    assert gate.build_workspace(ctx, work) is ws
    assert work.workspace_seconds == 1.235
    assert work.record["workspace_seconds"] == 1.235
    assert ctx.phase_seconds == {"workspace": 1.235}


def enumeration_doc(**override):
    doc = {
        "schema": ncg.SCHEMA_ENUM,
        "file": "scripts/framework/calc.py",
        "gate_file": "scripts/framework/new_code_gate.py",
        "mutant_names": [KEY],
        "gated_mutant_names": [KEY],
        "unmappable": [],
        "functions": [{"prefix": PREFIX, "start_line": 1, "end_line": 3}],
    }
    doc.update(override)
    return doc


class EnumerationRig:
    """`enumerate_file` with the workspace and the child process replaced by recorders."""

    def __init__(self, tmp_path, monkeypatch, doc, clock=None):
        self.ws = make_workspace(tmp_path)
        self.ctx = make_ctx(tmp_path, clock=clock or ScriptedClock(100.0, 101.0, 102.0))
        doc = dict(doc)
        doc["gate_file"] = str(self.ctx.repo / doc["gate_file"])
        self.phases = []
        record = ncg.blank_file_record("scripts/framework/calc.py", "new")
        self.work = gate.FileRun(record, "")
        self.work.gated = [1, 2]
        monkeypatch.setattr(gate, "build_workspace", lambda ctx, work: self.ws)

        def fake_run_phase(ctx, phase, argv, cwd, env):
            self.phases.append((phase, argv, cwd))
            return gate.ProcResult(0, json.dumps(doc), "", False)

        monkeypatch.setattr(gate, "run_phase", fake_run_phase)

    def run(self):
        gate.enumerate_file(self.ctx, self.work)


def test_enumerate_file_hands_the_child_the_gated_lines_file_in_the_workspace_root(
    tmp_path, monkeypatch
):
    rig = EnumerationRig(tmp_path, monkeypatch, enumeration_doc())
    rig.run()
    lines_file = rig.ws.root / "gated-lines.json"
    assert json.loads(lines_file.read_text(encoding="utf-8")) == [1, 2]
    phase, argv, cwd = rig.phases[0]
    assert phase == gate.PHASE_ENUMERATE and cwd == rig.ws.tree
    assert argv[-4:] == [
        "--file",
        "scripts/framework/calc.py",
        "--gated-lines-json",
        str(lines_file),
    ]
    assert argv[argv.index("-c") + 2 : argv.index("-c") + 4] == [
        str(rig.ctx.repo.resolve()),
        "_enumerate",
    ]


def test_enumerate_file_records_the_enumeration_seconds_to_the_millisecond(tmp_path, monkeypatch):
    rig = EnumerationRig(
        tmp_path, monkeypatch, enumeration_doc(), clock=ScriptedClock(100.0, 200.0, 201.23456)
    )
    rig.run()
    assert rig.work.record["enumerate_seconds"] == 1.235


def test_enumerate_file_keeps_the_names_and_spans_the_child_reported(tmp_path, monkeypatch):
    rig = EnumerationRig(tmp_path, monkeypatch, enumeration_doc())
    rig.run()
    assert rig.work.mutant_names == [KEY] and rig.work.gated_names == [KEY]
    assert rig.work.functions == {PREFIX: (1, 3)}


@pytest.mark.parametrize("field", ["mutant_names", "gated_mutant_names", "unmappable", "functions"])
def test_enumerate_file_names_the_file_when_any_list_in_the_reply_is_malformed(
    tmp_path, monkeypatch, field
):
    rig = EnumerationRig(tmp_path, monkeypatch, enumeration_doc(**{field: "not a list"}))
    with pytest.raises(gate.GateError) as caught:
        rig.run()
    assert str(caught.value) == "mutant enumeration failed: scripts/framework/calc.py"


# --------------------------------------------------------------------------
# assigned_works
# --------------------------------------------------------------------------


def plan_for(to_shards=True):
    rec = ncg.blank_file_record("scripts/a.py", "changed")
    rec.update(
        to_shards=to_shards,
        selection_full=["tests/t.py::a"],
        selection_method="context",
        mutant_names=["m.x_f__mutmut_1", "m.x_f__mutmut_2"],
        gated_mutant_names=["m.x_f__mutmut_1", "m.x_f__mutmut_2"],
    )
    member = {"path": "scripts/a.py", "names": ["m.x_f__mutmut_1"]}
    return {"files": [rec], "N": 1, "assignment": [{"index": 1, "members": [member]}]}


def test_assigned_works_builds_each_file_run_from_its_plan_record_and_its_own_names():
    (work,) = gate.assigned_works(plan_for(), 1)
    assert work.path == "scripts/a.py" and work.record["kind"] == "changed" and work.text == ""
    assert work.selected == ["tests/t.py::a"] and work.method == "context"
    assert work.mutant_names == ["m.x_f__mutmut_1", "m.x_f__mutmut_2"]
    assert work.gated_names == ["m.x_f__mutmut_1"]
    assert work.foreign_names == ["m.x_f__mutmut_2"]


def test_assigned_works_refuses_a_member_the_plan_does_not_shard():
    with pytest.raises(gate.GateError) as caught:
        gate.assigned_works(plan_for(to_shards=False), 1)
    assert str(caught.value) == "plan assigns shard 1 a file it does not shard: scripts/a.py"


def test_assigned_works_refuses_a_member_that_is_not_a_planned_file_at_all():
    plan = plan_for()
    plan["assignment"][0]["members"][0]["path"] = "scripts/other.py"
    with pytest.raises(gate.GateError) as caught:
        gate.assigned_works(plan, 1)
    assert str(caught.value) == "plan assigns shard 1 a file it does not shard: scripts/other.py"


# --------------------------------------------------------------------------
# check_gate_file, check_integrity, attribute_failure, analyze_python
# --------------------------------------------------------------------------


def test_a_gate_file_inside_the_workspace_is_refused_even_when_the_workspace_is_in_the_checkout(
    tmp_path,
):
    ctx = make_ctx(tmp_path)
    tree = ctx.repo / "ws" / "tree"
    tree.mkdir(parents=True)
    ws = gate.Workspace(tree.parent, tree, tree.parent / "p", tree.parent / "e")
    inside = tree / "scripts" / "new_code_gate.py"
    with pytest.raises(gate.GateError) as caught:
        gate.check_gate_file(str(inside), ws, ctx)
    assert str(caught.value) == f"gate subprocess imported from the workspace: {inside}"
    gate.check_gate_file(str(ctx.repo / "scripts" / "new_code_gate.py"), ws, ctx)


def integrity_rig(tmp_path):
    ws = make_workspace(tmp_path)
    ok = {"event": "plugin_loaded", "path": str(ws.plugin_dir / f"{gate.PLUGIN_MODULE}.py")}
    return ws, ok


def test_integrity_names_a_failed_path_load_recorder_exactly(tmp_path):
    ws, ok = integrity_rig(tmp_path)
    with pytest.raises(gate.GateError) as caught:
        gate.check_integrity([ok, {"event": "observer_error"}], ws, [])
    assert str(caught.value) == "path-load recorder failed"


def test_integrity_lists_the_unselected_tests_that_ran_sorted_and_comma_separated(tmp_path):
    ws, ok = integrity_rig(tmp_path)
    events = [ok] + [{"event": "executed", "node": n} for n in ("tests/b.py::t", "tests/a.py::t")]
    with pytest.raises(gate.GateError) as caught:
        gate.check_integrity(events, ws, ["tests/c.py"])
    assert str(caught.value) == (
        "mutation run executed unselected tests: tests/a.py::t, tests/b.py::t"
    )


def attribution_rig(tmp_path):
    ctx = make_ctx(tmp_path)
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    work.selected = ["tests/t.py"]
    return ctx, work


def test_an_unattributed_mutmut_failure_is_an_internal_error_and_ends_the_file(tmp_path):
    ctx, work = attribution_rig(tmp_path)
    result = gate.ProcResult(2, "", "", False)
    gate.attribute_failure(ctx, work, result, "boom\n")
    assert ctx.internal_errors == [
        {
            "code": "mutmut_failed",
            "message": "mutmut exited 2",
            "file": "scripts/a.py",
            "output_tail": "boom",
        }
    ]
    assert work.record["mutation_reason"] == "internal_error" and work.done is True


def test_a_clean_run_failure_with_no_selected_test_named_carries_its_stage(tmp_path):
    ctx, work = attribution_rig(tmp_path)
    output = f"{ncg.MUTMUT_CLEAN_FAILED_MESSAGE}\n"
    gate.attribute_failure(ctx, work, gate.ProcResult(1, "", "", False), output)
    assert ctx.internal_errors[0]["code"] == "clean_run_unattributed"
    assert ctx.internal_errors[0]["stage"] == "clean"
    assert work.record["mutation_reason"] == "internal_error" and work.done is True


def test_selected_tests_failing_in_isolation_are_named_joined_by_commas(tmp_path):
    ctx, work = attribution_rig(tmp_path)
    output = (
        f"{ncg.MUTMUT_CLEAN_FAILED_MESSAGE}\n=== short test summary info ===\n"
        "FAILED tests/t.py::a - E\nFAILED tests/t.py::b - E\n"
    )
    gate.attribute_failure(ctx, work, gate.ProcResult(1, "", "", False), output)
    reason = work.record["fail_reasons"][0]
    assert reason["code"] == "selected_test_fails_in_isolation"
    assert reason["message"] == (
        "tests/t.py::a, tests/t.py::b failed in the clean run: "
        "this test fails when run alone in the mutation workspace"
    )
    assert ctx.internal_errors == []


def test_two_static_path_loads_are_reported_in_one_message_joined_by_semicolons(
    tmp_path, monkeypatch
):
    ctx = make_ctx(tmp_path)
    work = gate.FileRun(
        ncg.blank_file_record("scripts/oversight/validators/foo.py", "new"), "x = 1\n"
    )
    work.selected = ["tests/t.py::a"]
    work.gated = [1]
    sources = {
        "tests/a.py": "import foo\n",
        "tests/b.py": "import foo\n",
    }
    monkeypatch.setattr(gate, "test_sources", lambda ctx_, work_: sources)
    gate.analyze_python(ctx, work)
    reason = next(r for r in work.record["fail_reasons"] if r["code"] == "path_loaded_module")
    first, second = (
        ncg.path_load_message(i, work.path, "foo", "static:bare_import")
        for i in ("tests/a.py", "tests/b.py")
    )
    assert reason["message"] == f"{first}; {second}"
    assert work.record["mutation_reason"] == "path_load" and work.done is True


# --------------------------------------------------------------------------
# build_parser: the module docstring and one help line per command
# --------------------------------------------------------------------------


def test_the_parser_describes_itself_with_the_module_docstring():
    parser = gate.build_parser()
    assert parser.prog == "new_code_gate" and parser.description == gate.__doc__
    assert parser.description


def test_each_command_has_its_help_line_and_the_two_child_phases_are_hidden():
    parser = gate.build_parser()
    (sub,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    helps = {a.dest: a.help for a in sub._choices_actions}
    assert helps == {
        "meta": "write the coverage sidecar",
        "plan": "cheap phase, cost, shard count and assignment",
        "shard": "mutate one shard's assigned mutants",
        "verdict": "merge the fragments and decide pass or fail",
        "run": "local: plan, every shard, merge and verdict on HEAD",
        "_enumerate": argparse.SUPPRESS,
        "_collect": argparse.SUPPRESS,
    }


# --------------------------------------------------------------------------
# Context and FileRun: their starting state, and the seconds they add up
# --------------------------------------------------------------------------


def test_a_new_context_starts_empty_with_no_coverage_and_no_expired_phase(tmp_path):
    ctx = make_ctx(tmp_path)
    assert ctx.setup_seconds == 0 and ctx.label == "" and ctx.base_sha == ""
    assert ctx.durations == {} and ctx.meta == {} and ctx.modes == {} and ctx.sources == {}
    assert ctx.tracked == [] and ctx.workspaces == [] and ctx.internal_errors == []
    assert ctx.phase_seconds == {} and ctx.expired_phase == "" and ctx.expired_file == ""
    assert ctx.cov is None and ctx.deadline == 150.0 and ctx.gated_sha == SHA


def test_a_new_file_run_starts_with_nothing_found_and_no_decision_logic_ruled_out():
    work = gate.FileRun({"path": "scripts/a.py"}, "text")
    assert work.path == "scripts/a.py" and work.text == "text"
    assert work.gated == [] and work.statements == set() and work.selected == []
    assert work.method == "none" and work.findings == [] and work.logic_free is True
    assert work.workspace is None and work.mutant_names == [] and work.gated_names == []
    assert work.foreign_names == [] and work.functions == {} and work.cost is None
    assert work.status_by_key == {} and work.to_shards is False
    assert work.workspace_seconds == 0.0 and work.done is False


def test_phase_seconds_add_up_to_the_millisecond_per_phase(tmp_path):
    ctx = make_ctx(tmp_path, clock=ScriptedClock(100.0, 11.23456, 20.5))
    ctx.spend_phase("workspace", 10.0)
    assert ctx.phase_seconds == {"workspace": 1.235}
    ctx.spend_phase("workspace", 20.0)
    assert ctx.phase_seconds == {"workspace": 1.735}


def test_a_phase_not_yet_seen_starts_from_zero_seconds(tmp_path):
    ctx = make_ctx(tmp_path, clock=ScriptedClock(100.0, 12.0, 13.0))
    ctx.spend_phase("a", 10.0)
    ctx.spend_phase("b", 12.5)
    assert ctx.phase_seconds == {"a": 2.0, "b": 0.5}


def test_the_lead_names_any_setup_time_charged_to_the_budget_even_one_second(tmp_path):
    ctx = make_ctx(tmp_path)
    assert ctx.lead("late") == "late"
    ctx.charge_setup(1)
    assert ctx.lead("late") == "late (1s of job setup was charged to the budget)"


def test_a_file_run_adds_the_seconds_it_spent_to_the_millisecond():
    work = gate.FileRun({"path": "a.py", "seconds": 0.0}, "")
    work.spend(4.0, ScriptedClock(5.23456))
    assert work.record["seconds"] == 1.235


# --------------------------------------------------------------------------
# Files written by the gate
# --------------------------------------------------------------------------


def test_write_text_atomic_makes_its_temp_file_beside_the_target_and_replaces_it(
    tmp_path, monkeypatch
):
    seen = []
    real_replace = gate.os.replace

    def spy(src, dst):
        seen.append((Path(src), Path(dst), Path(src).read_text(encoding="utf-8")))
        real_replace(src, dst)

    monkeypatch.setattr(gate.os, "replace", spy)
    target = tmp_path / "sub" / "out.json"
    gate.write_text_atomic(target, "é\n")
    ((tmp, dst, text),) = seen
    assert dst == target and tmp.parent == target.parent and text == "é\n"
    assert tmp.name.startswith(".out.json.") and tmp.name.endswith(".tmp")
    assert target.read_text(encoding="utf-8") == "é\n" and list(target.parent.iterdir()) == [target]


def test_write_text_atomic_keeps_the_original_error_when_its_temp_file_is_already_gone(
    tmp_path, monkeypatch
):
    def failing_replace(src, dst):
        Path(src).unlink()
        raise RuntimeError("replace failed")

    monkeypatch.setattr(gate.os, "replace", failing_replace)
    with pytest.raises(RuntimeError, match="replace failed"):
        gate.write_text_atomic(tmp_path / "out.json", "x")


def test_write_json_is_two_space_indented_ascii_with_a_final_newline(tmp_path):
    target = tmp_path / "doc.json"
    gate.write_json(target, {"a": "é", "b": [1]})
    assert target.read_text(encoding="utf-8") == '{\n  "a": "\\u00e9",\n  "b": [\n    1\n  ]\n}\n'


@pytest.mark.parametrize("good", [{}, {"a": 0}, {"a": 5, "b": 1_000_000}])
def test_durations_are_a_map_of_names_to_non_negative_integers(good):
    assert gate.valid_durations(good) is True


@pytest.mark.parametrize(
    "bad", [[], None, {"a": -1}, {"a": True}, {1: 5}, {"a": "x"}, {"a": 1.5}, {"a": None}]
)
def test_anything_else_is_not_a_durations_map(bad):
    assert gate.valid_durations(bad) is False


def test_tracked_modes_names_twelve_characters_of_the_sha_when_git_cannot_list_it(tmp_path):
    with pytest.raises(gate.GateError) as caught:
        gate.tracked_modes(tmp_path, "c" * 40)
    assert str(caught.value) == f"could not list files at {'c' * 12}"


class _FakeData:
    def measured_files(self):
        return ["/r/boX/a.py", "/elsewhere/b.py"]


def test_coverage_view_keys_files_by_their_path_under_the_checkout_root():
    view = gate.CoverageView(_FakeData(), "/r/boX/")
    assert view.files == {"a.py": "/r/boX/a.py"}
    assert gate.CoverageView(_FakeData(), "/r/boX").files == {"a.py": "/r/boX/a.py"}


def test_a_workspace_with_no_pyproject_is_refused_by_the_round_trip_check_of_the_generated_table(
    tmp_path,
):
    ctx = make_ctx(tmp_path)
    ctx.tracked = ["scripts/framework/calc.py", "tests/test_calc.py"]
    work = gate.FileRun(ncg.blank_file_record("scripts/framework/calc.py", "new"), "")
    work.selected = ["tests/test_calc.py::test_add"]
    tree = tmp_path / "tree"
    tree.mkdir()
    with pytest.raises(gate.GateError) as caught:
        gate.write_mutmut_config(ctx, work, tree)
    assert str(caught.value) == "generated mutmut config failed round-trip"
    assert not (tree / "pyproject.toml").exists()


def test_verify_extracted_lists_the_files_that_differ_joined_by_commas(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path)
    ctx.tracked = ["scripts/a.py", "tests/conftest.py", "tests/t.py"]
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    work.selected = ["tests/t.py::x"]
    monkeypatch.setattr(gate, "git_text", lambda repo, args, fail=None: "h1 h2 h3")
    monkeypatch.setattr(gate, "run_git", lambda repo, args, fail=None: b"h1 other1 other2")
    with pytest.raises(gate.GateError) as caught:
        gate.verify_extracted(ctx, work, tmp_path / "tree")
    assert str(caught.value) == (
        "extracted workspace differs from the gated commit: tests/conftest.py, tests/t.py"
    )


# --------------------------------------------------------------------------
# write_job_outputs, trampoline_message
# --------------------------------------------------------------------------


@pytest.mark.parametrize("count", [1, 2, 8])
def test_job_outputs_append_the_count_and_the_compact_shard_list(tmp_path, count):
    out = tmp_path / "out"
    out.write_text("earlier=1\n", encoding="utf-8")
    gate.write_job_outputs(out, {"N": count})
    shards = "[" + ",".join(str(i) for i in range(1, count + 1)) + "]"
    assert out.read_text(encoding="utf-8") == f"earlier=1\ncount={count}\nshards={shards}\n"


@pytest.mark.parametrize("count", [0, 9, -1])
def test_a_shard_count_outside_one_to_n_max_is_refused_before_anything_is_written(tmp_path, count):
    out = tmp_path / "out"
    with pytest.raises(gate.GateError) as caught:
        gate.write_job_outputs(out, {"N": count})
    assert str(caught.value) == f"shard count {count} is outside 1..8"
    assert not out.exists()


def test_a_trampoline_message_with_no_static_finding_names_each_selected_module_once_sorted():
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    work.selected = ["tests/b.py::u", "tests/a.py::t", "tests/a.py::v"]
    assert gate.trampoline_message(work, []) == (
        "mutmut found trampoline hits that match no mutant key, so a selected test loads "
        "scripts/a.py under a non-canonical name; candidate importers: tests/a.py, tests/b.py "
        f"\u2014 {ncg.MSG_PATH_LOAD_FIX}"
    )


def test_a_trampoline_message_with_static_findings_joins_their_messages_with_semicolons():
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    found = [
        {"importer": "tests/a.py", "loaded_as": "a", "via": "static:x"},
        {"importer": "tests/b.py", "loaded_as": "a", "via": "static:x"},
    ]
    first, second = (
        ncg.path_load_message(i, "scripts/a.py", "a", "static:x")
        for i in ("tests/a.py", "tests/b.py")
    )
    assert gate.trampoline_message(work, found) == f"{first}; {second}"


# --------------------------------------------------------------------------
# SubprocessRunner and Clock
# --------------------------------------------------------------------------


def test_the_runner_starts_the_child_in_its_cwd_and_env_and_reads_text_with_replacement(tmp_path):
    child_dir = tmp_path / "child"
    child_dir.mkdir()
    code = (
        "import os, sys\n"
        "print(os.getcwd(), os.environ.get('NCG_PIN'))\n"
        "sys.stdout.flush()\n"
        "sys.stdout.buffer.write(bytes([0xff]))\n"
    )
    spec = gate.ProcSpec(
        [sys.executable, "-I", "-c", code], str(child_dir), {"NCG_PIN": "pinned"}, 30.0
    )
    result = gate.SubprocessRunner().run("test", spec)
    assert result.returncode == 0 and result.timed_out is False
    assert result.stdout == f"{child_dir.resolve()} pinned\n\ufffd"


class _Pipe:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _StuckProc:
    def __init__(self, polled=None):
        self.stdout, self.stderr = _Pipe(), _Pipe()
        self.timeouts = []
        self.polled = polled

    def communicate(self, timeout=None):
        self.timeouts.append(timeout)
        raise subprocess.TimeoutExpired(
            "cmd", timeout, output=b"partial out", stderr=b"partial err"
        )

    def poll(self):
        return self.polled


def test_drain_waits_one_grace_period_then_closes_both_pipes_and_returns_what_was_written():
    proc = _StuckProc()
    out, err = gate.SubprocessRunner(grace=3.0).drain(proc)
    assert (out, err) == ("partial out", "partial err")
    assert proc.timeouts == [3.0] and proc.stdout.closed and proc.stderr.closed


def test_a_child_that_has_not_exited_reports_the_kill_signal_and_one_that_has_reports_its_code():
    runner = gate.SubprocessRunner()
    assert runner.exit_code(_StuckProc(polled=None)) == -9
    assert runner.exit_code(_StuckProc(polled=0)) == 0
    assert runner.exit_code(_StuckProc(polled=3)) == 3


def test_the_utc_timestamp_is_utc_whatever_the_local_zone_is(monkeypatch):
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    try:
        before = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        got = gate.Clock().utc_iso()
        after = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    finally:
        monkeypatch.undo()
        time.tzset()
    assert before <= got <= after


# --------------------------------------------------------------------------
# wanted_test_paths
# --------------------------------------------------------------------------


def test_wanted_test_paths_are_each_module_and_every_conftest_from_the_root_down():
    assert gate.wanted_test_paths(["tests/oversight/test_x.py::t", "tests/test_y.py"]) == [
        "tests/oversight/test_x.py",
        "conftest.py",
        "tests/conftest.py",
        "tests/oversight/conftest.py",
        "tests/test_y.py",
        "conftest.py",
        "tests/conftest.py",
    ]


# --------------------------------------------------------------------------
# load_shard_plan: each refusal says which check failed
# --------------------------------------------------------------------------


def shard_plan_rig(tmp_path, monkeypatch, **plan_override):
    plan_doc = {
        "N": 2,
        "plan_hash": "h",
        "internal_errors": [],
        "binding": {},
        "tool_versions": {"mutmut": "3"},
        "python": "3.12",
    }
    plan_doc.update(plan_override)
    monkeypatch.setattr(gate, "sole_file", lambda directory, name: directory / name)
    monkeypatch.setattr(gate, "read_json_file", lambda path: plan_doc)
    monkeypatch.setattr(ncs, "plan_shape_error", lambda doc: None)
    monkeypatch.setattr(ncs, "plan_hash", lambda doc: "h")
    monkeypatch.setattr(ncg, "check_records_binding", lambda *args: None)
    monkeypatch.setattr(gate, "rev_parse", lambda repo, spec: SHA)
    opts = SimpleNamespace(
        index=1,
        plan_dir=tmp_path,
        mode="local",
        gated_sha=SHA,
        pr=None,
        run_id=None,
        run_attempt=None,
        repo=tmp_path,
        installed={"mutmut": "3"},
        python="3.12",
    )
    return opts, plan_doc


def test_a_plan_that_passes_every_check_is_returned_whole(tmp_path, monkeypatch):
    opts, plan_doc = shard_plan_rig(tmp_path, monkeypatch)
    assert gate.load_shard_plan(opts) is plan_doc


def test_a_plan_that_is_not_the_one_file_in_its_directory_is_refused_by_name(tmp_path, monkeypatch):
    opts, _ = shard_plan_rig(tmp_path, monkeypatch)
    monkeypatch.setattr(gate, "sole_file", lambda directory, name: None)
    with pytest.raises(gate.GateError) as caught:
        gate.load_shard_plan(opts)
    assert str(caught.value) == (
        "shard 1: the plan directory must hold exactly new-code-plan.json, as a regular file"
    )


def test_a_plan_with_a_wrong_shape_is_refused_with_the_shape_error(tmp_path, monkeypatch):
    opts, _ = shard_plan_rig(tmp_path, monkeypatch)
    monkeypatch.setattr(ncs, "plan_shape_error", lambda doc: "files is not a list")
    with pytest.raises(gate.GateError) as caught:
        gate.load_shard_plan(opts)
    assert str(caught.value) == "shard 1: files is not a list"


@pytest.mark.parametrize(
    "case,message",
    [
        ("hash", "plan_hash does not match the plan"),
        ("errors", "the plan has internal errors"),
        ("binding", "the plan is bound to another run"),
        ("index", "the shard index is outside the plan"),
        ("head", "HEAD is not the gated commit"),
        ("tools", "tool versions differ from the plan's"),
        ("python", "python differs from the plan's"),
    ],
)
def test_each_refusal_of_a_plan_names_its_own_reason_after_the_shard_and_count(
    tmp_path, monkeypatch, case, message
):
    opts, plan_doc = shard_plan_rig(tmp_path, monkeypatch)
    if case == "hash":
        plan_doc["plan_hash"] = "other"
    elif case == "errors":
        plan_doc["internal_errors"] = [{"code": "x", "message": "y"}]
    elif case == "binding":
        monkeypatch.setattr(
            ncg, "check_records_binding", lambda *args: "the plan is bound to another run"
        )
    elif case == "index":
        opts.index = 3
    elif case == "head":
        monkeypatch.setattr(gate, "rev_parse", lambda repo, spec: "f" * 40)
    elif case == "tools":
        opts.installed = {"mutmut": "4"}
    else:
        opts.python = "3.13"
    with pytest.raises(gate.GateError) as caught:
        gate.load_shard_plan(opts)
    assert str(caught.value) == f"shard {opts.index} of 2: {message}"


# --------------------------------------------------------------------------
# plan, merge_records, plan_document, plan_record, plan_timeout_message, plan_files
# --------------------------------------------------------------------------


def plan_options(**override):
    values = {
        "repo": Path("/repo"),
        "gated_sha": SHA,
        "pr_head_sha": "b" * 40,
        "pr": 7,
        "coverage_file": Path("/cov"),
        "meta_path": Path("/meta"),
        "tests_result": None,
        "run_id": "11",
        "run_attempt": 2,
        "mode": "ci",
        "base_ref": None,
        "installed": {"mutmut": "3"},
        "python": "3.12",
        "python_exe": sys.executable,
        "environ": {},
        "keep_workspace": True,
        "job_start_file": None,
        "github_output": None,
    }
    values.update(override)
    return gate.PlanOptions(**values)


def test_plan_stamps_its_start_finish_and_seconds_and_hands_the_context_a_discarded_workspace(
    tmp_path, monkeypatch
):
    built = {}
    ctx = make_ctx(tmp_path, clock=ScriptedClock(0.0))
    ctx.meta = {"coverage_core": "ctrace"}
    ctx.base_sha = "c" * 40

    def fake_build(opts, runner, clock, setup):
        built.update(keep=opts.keep_workspace, setup=setup)
        return ctx

    monkeypatch.setattr(gate, "build_context", fake_build)
    monkeypatch.setattr(gate, "plan_files", lambda c: [])
    monkeypatch.setattr(gate, "cost_files", lambda c, works: None)
    monkeypatch.setattr(gate, "rev_parse", lambda repo, spec: "t" * 40)
    clock = ScriptedClock(10.0, 11.23456, utc=["2026-01-01T00:00:00Z", "2026-01-01T00:00:02Z"])
    doc, code = gate.plan(plan_options(), NoRunner(), clock)
    assert code == 0 and built == {"keep": False, "setup": 0}
    assert doc["started_at"] == "2026-01-01T00:00:00Z"
    assert doc["finished_at"] == "2026-01-01T00:00:02Z"
    assert doc["seconds"] == 1.235
    assert doc["job_seconds"] is None and doc["internal_errors"] == []


def test_plan_keeps_what_the_context_already_recorded_before_an_exception_and_adds_its_own(
    tmp_path, monkeypatch
):
    ctx = make_ctx(tmp_path, clock=ScriptedClock(0.0))
    ctx.internal_errors = [{"code": "internal_error", "message": "earlier", "file": "a.py"}]
    monkeypatch.setattr(gate, "build_context", lambda *args: ctx)

    def failing(c):
        raise ValueError("boom")

    monkeypatch.setattr(gate, "plan_files", failing)
    monkeypatch.setattr(gate, "rev_parse", lambda repo, spec: "t" * 40)
    clock = ScriptedClock(0.0, 1.0, utc=["a", "b"])
    doc, code = gate.plan(plan_options(), NoRunner(), clock)
    assert code == 3
    assert doc["internal_errors"] == [
        {"code": "internal_error", "message": "earlier", "file": "a.py"},
        {"code": "internal_error", "message": "ValueError: boom"},
    ]


def test_plan_with_no_context_reports_only_the_error_it_raised(tmp_path, monkeypatch):
    def failing(*args):
        raise gate.GateError("no sidecar")

    monkeypatch.setattr(gate, "build_context", failing)
    doc, code = gate.plan(plan_options(), NoRunner(), ScriptedClock(0.0, 1.0, utc=["a", "b"]))
    assert code == 3
    assert doc["internal_errors"] == [{"code": "internal_error", "message": "no sidecar"}]


def test_plan_of_a_run_whose_tests_failed_reports_the_upstream_result(tmp_path):
    doc, code = gate.plan(
        plan_options(tests_result="failure"), NoRunner(), ScriptedClock(0.0, 1.0, utc=["a", "b"])
    )
    assert code == 3
    assert doc["internal_errors"] == [
        {"code": "upstream", "message": "upstream job not successful: failure"}
    ]


def test_plan_document_carries_the_binding_the_versions_and_the_plan_constants(monkeypatch):
    doc = gate.plan_document(plan_options(), None, [], [], {"seconds": 1.0})
    assert doc["schema"] == ncg.SCHEMA_PLAN and doc["gate_version"] == ncg.GATE_VERSION
    assert doc["binding"] == {
        "mode": "ci",
        "gated_sha": SHA,
        "pr_head_sha": "b" * 40,
        "base_sha": None,
        "gated_tree": None,
        "pr": 7,
        "run_id": "11",
        "run_attempt": 2,
    }
    assert doc["tool_versions"] == {"mutmut": "3"} and doc["python"] == "3.12"
    assert doc["coverage_core"] is None and doc["constants"] == gate.ncs.plan_constants()
    assert doc["seconds"] == 1.0 and doc["plan_hash"] == gate.ncs.plan_hash(doc)


def test_plan_document_with_a_context_names_its_base_tree_and_coverage_core(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path)
    ctx.meta = {"coverage_core": "ctrace"}
    ctx.base_sha = "c" * 40
    monkeypatch.setattr(gate, "rev_parse", lambda repo, spec: "tree-of:" + spec)
    doc = gate.plan_document(plan_options(), ctx, [], [], {})
    assert doc["coverage_core"] == "ctrace"
    assert doc["binding"]["base_sha"] == "c" * 40
    assert doc["binding"]["gated_tree"] == f"tree-of:{SHA}^{{tree}}"


def test_a_file_with_no_cost_yet_plans_at_zero_cost():
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    rec = gate.plan_record(work, True)
    assert (rec["function_cost_ms"], rec["W_F_ms"], rec["fixed_est_ms"], rec["cost_ms"]) == (
        {},
        0,
        0,
        0,
    )
    assert rec["to_shards"] is False


def test_the_plan_timeout_message_names_the_phase_and_file_that_ran_out(tmp_path):
    ctx = make_ctx(tmp_path)
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    assert "ran out in an unrecorded phase;" in gate.plan_timeout_message(ctx, [work])
    ctx.expired_file = "scripts/a.py"
    assert "ran out in an unrecorded phase of scripts/a.py;" in gate.plan_timeout_message(
        ctx, [work]
    )
    ctx.expired_phase = "enumerate"
    assert "ran out in enumerate of scripts/a.py;" in gate.plan_timeout_message(ctx, [work])


def test_a_budget_that_ends_before_any_file_is_prepared_leaves_an_empty_plan(tmp_path, monkeypatch):
    def expired(ctx):
        raise gate.BudgetExpired("prepare")

    monkeypatch.setattr(gate, "prepare_files", expired)
    assert gate.plan_files(make_ctx(tmp_path)) == []


def test_merge_records_stamps_its_own_times_and_the_runner_minutes_from_its_seconds(monkeypatch):
    seen = {}
    monkeypatch.setattr(gate, "sole_file", lambda directory, name: None)
    monkeypatch.setattr(gate, "read_fragments", lambda directory: {})

    def fake_merge(plan_doc, fragments, plan_result, shard_result, binding):
        seen["merge"] = (plan_doc, plan_result, shard_result)
        return {"files": []}, []

    def fake_minutes(records, seconds):
        seen["minutes"] = seconds
        return 4.5

    monkeypatch.setattr(gate.ncs, "merge", fake_merge)
    monkeypatch.setattr(gate.ncs, "runner_minutes_total", fake_minutes)
    clock = ScriptedClock(10.0, 11.23456, utc=["start", "finish"])
    records = gate.merge_records(Path("p"), Path("f"), ("success", "failure"), {}, clock)
    assert seen["merge"] == (None, "success", "failure") and seen["minutes"] == 1.235
    assert records["started_at"] == "start" and records["finished_at"] == "finish"
    assert records["seconds"] == 1.235 and records["merge_verdict_seconds"] == 1.235
    assert records["runner_minutes_total"] == 4.5


# --------------------------------------------------------------------------
# fragment_entry
# --------------------------------------------------------------------------


def fragment_work(done=True, reasons=(), reason=None, path="scripts/a.py"):
    record = ncg.blank_file_record(path, "new")
    record.update(
        mutants_killed=3,
        mutants_total=4,
        mutant_status_counts={"killed": 3, "survived": 1},
        mutation_reason=reason,
        workspace_seconds=1.0,
        mutmut_seconds=2.0,
        collect_seconds=3.0,
        seconds=4.0,
    )
    record["fail_reasons"] = [{"code": code, "message": "m"} for code in reasons]
    work = gate.FileRun(record, "")
    work.done = done
    work.gated_names = ["m.x_f__mutmut_1", "m.x_f__mutmut_2"]
    work.status_by_key = {"m.x_f__mutmut_1": "killed"}
    return work


def test_a_finished_file_with_no_shard_time_reason_is_scored():
    entry = gate.fragment_entry(fragment_work(), set())
    assert entry["finished"] is True and entry["assigned"] == 2
    assert entry["killed"] == 3 and entry["total"] == 4
    assert entry["status_by_key"] == {"m.x_f__mutmut_1": "killed"}
    assert entry["mutant_status_counts"] == {"killed": 3, "survived": 1}
    assert (entry["workspace_seconds"], entry["mutmut_seconds"]) == (1.0, 2.0)
    assert (entry["collect_seconds"], entry["seconds"]) == (3.0, 4.0)


@pytest.mark.parametrize(
    "work,errored",
    [
        (fragment_work(done=False), set()),
        (fragment_work(done=True), {"scripts/a.py"}),
        (fragment_work(done=True, reasons=["mutation_timeout"]), set()),
        (fragment_work(done=False), {"scripts/a.py"}),
    ],
)
def test_a_file_that_did_not_finish_cleanly_or_has_a_shard_reason_is_not_scored(work, errored):
    entry = gate.fragment_entry(work, errored)
    assert (entry["killed"], entry["total"]) == (0, 0)
    assert entry["status_by_key"] == {} and entry["mutant_status_counts"] == {}


def test_a_file_that_has_a_shard_reason_is_finished_but_not_scored():
    entry = gate.fragment_entry(fragment_work(reasons=["mutation_timeout"]), set())
    assert entry["finished"] is True
    assert [r["code"] for r in entry["fail_reasons"]] == ["mutation_timeout"]


def test_only_the_shard_time_reasons_travel_and_only_the_known_mutation_reasons():
    work = fragment_work(reasons=["coverage_below_threshold", "path_loaded_module"], reason="x")
    entry = gate.fragment_entry(work, set())
    assert [r["code"] for r in entry["fail_reasons"]] == ["path_loaded_module"]
    assert entry["mutation_reason"] is None
    assert (
        gate.fragment_entry(fragment_work(reason="timeout"), set())["mutation_reason"] == "timeout"
    )


# --------------------------------------------------------------------------
# parse_functions: every malformed shape is refused with the caller's own message
# --------------------------------------------------------------------------

GOOD_SPAN = {"prefix": PREFIX, "start_line": 1, "end_line": 3}


def test_functions_parse_to_their_line_spans_and_a_one_line_function_is_allowed():
    one = {"prefix": PREFIX + "2", "start_line": 5, "end_line": 5}
    assert gate.parse_functions([GOOD_SPAN, one], "bad") == {PREFIX: (1, 3), PREFIX + "2": (5, 5)}


@pytest.mark.parametrize(
    "raw",
    [
        "not a list",
        ["not a dict"],
        [{"prefix": 5, "start_line": 1, "end_line": 3}],
        [{"prefix": "not a prefix!", "start_line": 1, "end_line": 3}],
        [{"prefix": PREFIX, "end_line": 3}],
        [{"prefix": PREFIX, "start_line": True, "end_line": 3}],
        [{"prefix": PREFIX, "start_line": 1, "end_line": True}],
        [{"prefix": PREFIX, "start_line": "1", "end_line": 3}],
        [{"prefix": PREFIX, "start_line": 0, "end_line": 3}],
        [{"prefix": PREFIX, "start_line": 4, "end_line": 3}],
    ],
)
def test_a_malformed_function_list_is_refused_with_the_given_failure_text(raw):
    with pytest.raises(gate.GateError) as caught:
        gate.parse_functions(raw, "enumeration failed here")
    assert str(caught.value) == "enumeration failed here"


# --------------------------------------------------------------------------
# mutate_file, make_workspace, mutation_env, job_start_seconds, guarded
# --------------------------------------------------------------------------


class MutateRig:
    def __init__(self, tmp_path, monkeypatch, events=(), result=None, clock=None):
        self.ctx = make_ctx(tmp_path, clock=clock or ScriptedClock(100.0, 10.0, 11.23456))
        self.ws = make_workspace(tmp_path)
        self.work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
        self.work.workspace = self.ws
        self.work.selected = ["tests/t.py::a"]
        self.attributed = []
        result = result or gate.ProcResult(0, "", "", False)
        monkeypatch.setattr(gate, "run_phase", lambda *args: result)
        monkeypatch.setattr(gate, "read_events", lambda path: list(events))
        monkeypatch.setattr(gate, "check_integrity", lambda events_, ws, selected: None)
        monkeypatch.setattr(gate, "check_workspace_unchanged", lambda ws, path: None)
        monkeypatch.setattr(
            gate,
            "attribute_failure",
            lambda ctx, work, result_, output: self.attributed.append(output),
        )


def test_a_test_that_copies_the_repository_unmarked_fails_the_file_naming_each_test_once(
    tmp_path, monkeypatch
):
    events = [{"event": "repo_copy", "node": n} for n in ("tests/b.py::t", "tests/a.py::t")]
    rig = MutateRig(tmp_path, monkeypatch, events=events + events[:1])
    gate.mutate_file(rig.ctx, rig.work)
    (reason,) = rig.work.record["fail_reasons"]
    assert reason["code"] == "unmarked_repo_copy"
    assert reason["message"] == (
        "tests/a.py::t, tests/b.py::t copies the repository; mark it @pytest.mark.repo_copy"
    )
    assert rig.work.record["mutation_reason"] == "blocked_by:unmarked_repo_copy"
    assert rig.work.record["mutmut_seconds"] == 1.235


def test_a_runtime_path_load_blocks_the_file_with_the_path_load_reason(tmp_path, monkeypatch):
    events = [{"event": "path_load", "importer": "tests/a.py", "loaded_as": "calc", "kind": "x"}]
    rig = MutateRig(tmp_path, monkeypatch, events=events)
    gate.mutate_file(rig.ctx, rig.work)
    assert rig.work.record["mutation_reason"] == "path_load"
    assert [f["importer"] for f in rig.work.record["path_load_findings"]] == ["tests/a.py"]
    assert rig.work.record["fail_reasons"][0]["code"] == "path_loaded_module"
    assert rig.work.done is True


def test_a_failed_mutmut_run_is_attributed_from_its_output_with_colour_codes_removed(
    tmp_path, monkeypatch
):
    result = gate.ProcResult(2, "\x1b[31mred\x1b[0m", "err", False)
    rig = MutateRig(tmp_path, monkeypatch, result=result)
    gate.mutate_file(rig.ctx, rig.work)
    assert rig.attributed == ["red\nerr"]


@pytest.mark.parametrize(
    "environ,chosen",
    [
        ({"RUNNER_TEMP": "runner", "TMPDIR": "tmpdir"}, "runner"),
        ({"TMPDIR": "tmpdir"}, "tmpdir"),
        ({"runner_temp": "wrong", "TMPDIR": "tmpdir"}, "tmpdir"),
    ],
)
def test_a_workspace_is_made_under_runner_temp_first_then_tmpdir_with_its_events_file_named(
    tmp_path, monkeypatch, environ, chosen
):
    for name in ("runner", "tmpdir", "wrong"):
        (tmp_path / name).mkdir()
    environ = {k: str(tmp_path / v) for k, v in environ.items()}
    ctx = make_ctx(tmp_path, environ=environ)
    (ctx.repo / "scripts" / "framework").mkdir(parents=True)
    (ctx.repo / gate.PLUGIN_RELPATH).write_text("# plugin\n", encoding="utf-8")

    def fake_extract(ctx_, root, tree):
        (tree / "scripts").mkdir(parents=True)
        (tree / "scripts" / "a.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(gate, "extract_archive", fake_extract)
    monkeypatch.setattr(gate, "verify_extracted", lambda *args: None)
    monkeypatch.setattr(gate, "write_mutmut_config", lambda *args: None)
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    ws = gate.make_workspace(ctx, work)
    assert ws.root.parent == (tmp_path / chosen).resolve()
    assert ws.events == ws.plugin_dir / "events.jsonl"
    assert (ws.plugin_dir / f"{gate.PLUGIN_MODULE}.py").read_text(encoding="utf-8") == "# plugin\n"
    assert work.workspace is ws and ctx.workspaces == [ws]


def test_the_mutation_env_puts_the_plugin_dir_before_an_inherited_pythonpath(tmp_path):
    ws = make_workspace(tmp_path)
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    with_path = make_ctx(tmp_path, environ={"PYTHONPATH": "/inherited", "pythonpath": "/lower"})
    env = gate.mutation_env(with_path, work, ws)
    assert env["PYTHONPATH"] == f"{ws.plugin_dir}{gate.os.pathsep}/inherited"
    assert env["NCG_GATED_FILE"] == "scripts/a.py" and env["NCG_WORKSPACE"] == str(ws.tree)
    without = gate.mutation_env(make_ctx(tmp_path), work, ws)
    assert without["PYTHONPATH"] == str(ws.plugin_dir)


def test_a_job_start_file_may_hold_up_to_twelve_digits_and_no_more(tmp_path):
    path = tmp_path / "start"
    path.write_text("1" * 12 + "\n", encoding="utf-8")
    assert gate.job_start_seconds(path) == int("1" * 12)
    path.write_text("1" * 13, encoding="utf-8")
    assert gate.job_start_seconds(path) is None


def test_a_step_that_raises_is_recorded_as_an_internal_error_for_its_file_and_ends_it(tmp_path):
    ctx = make_ctx(tmp_path, clock=ScriptedClock(100.0, 1.0, 2.0))
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")

    def failing(ctx_, work_):
        raise ValueError("boom")

    gate.guarded(ctx, work, failing)
    assert ctx.internal_errors == [
        {"code": "internal_error", "message": "ValueError: boom", "file": "scripts/a.py"}
    ]
    assert work.record["mutation_reason"] == "internal_error" and work.done is True
    assert work.record["seconds"] == 1.0


def test_parse_child_json_refuses_a_zero_exit_with_a_reply_that_is_not_an_object():
    for stdout in ("[]", "3"):
        with pytest.raises(gate.GateError, match="failed"):
            gate.parse_child_json(gate.ProcResult(0, stdout, "", False), "s", "a.py", "failed")
    with pytest.raises(gate.GateError, match="failed"):
        gate.parse_child_json(
            gate.ProcResult(1, json.dumps({"schema": "s", "file": "a.py"}), "", False),
            "s",
            "a.py",
            "failed",
        )
    doc = {"schema": "s", "file": "a.py"}
    assert (
        gate.parse_child_json(gate.ProcResult(0, json.dumps(doc), "", False), "s", "a.py", "f")
        == doc
    )


def test_a_timed_out_file_records_that_no_mutation_ran_and_is_finished():
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    gate.mark_timeout(work, "ran out")
    assert work.record["mutation_ran"] is False
    assert work.record["mutation_reason"] == "timeout"
    assert work.done is True
    assert [r["code"] for r in work.record["fail_reasons"]] == ["mutation_timeout"]


# --------------------------------------------------------------------------
# run_git, read_durations, read_events, sha256_file, read_fragments, release_workspace
# --------------------------------------------------------------------------


def fake_git_process(stderr, returncode=1, stdout=b""):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    return run


def test_a_failed_git_command_names_its_verb_and_the_last_three_stderr_lines(monkeypatch):
    monkeypatch.setattr(gate.subprocess, "run", fake_git_process(b"l1\nl2\nl3\nl4\nl5\n"))
    with pytest.raises(gate.GateError) as caught:
        gate.run_git(Path("/r"), ["status", "-s"])
    assert str(caught.value) == "git status failed: l3 l4 l5"


def test_a_failed_git_command_prefers_the_callers_own_message(monkeypatch):
    monkeypatch.setattr(gate.subprocess, "run", fake_git_process(b"x\n"))
    with pytest.raises(gate.GateError) as caught:
        gate.run_git(Path("/r"), ["status"], "custom failure")
    assert str(caught.value) == "custom failure"


def test_a_failed_git_command_replaces_stderr_bytes_that_are_not_utf8(monkeypatch):
    monkeypatch.setattr(gate.subprocess, "run", fake_git_process(b"bad \xff byte\n"))
    with pytest.raises(gate.GateError) as caught:
        gate.run_git(Path("/r"), ["log"])
    assert str(caught.value) == "git log failed: bad � byte"


def test_a_git_command_runs_in_the_repo_and_returns_its_stdout_bytes(monkeypatch):
    seen = {}

    def run(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return subprocess.CompletedProcess(argv, 0, b"out", b"")

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate.run_git(Path("/r"), ["rev-parse", "HEAD"]) == b"out"
    assert seen["argv"] == ["git", "-C", "/r", "rev-parse", "HEAD"]
    assert seen["kwargs"]["capture_output"] is True


@pytest.mark.parametrize("spec", ["HEAD", "abc^{tree}"])
def test_rev_parse_names_what_it_could_not_resolve(monkeypatch, spec):
    seen = GitRecorder()
    monkeypatch.setattr(gate, "git_text", seen)
    gate.rev_parse(Path("/r"), spec)
    assert seen.calls[0][1] == ["rev-parse", spec]
    assert seen.calls[0][2] == f"could not resolve {spec}"


def test_the_base_is_the_first_parent_in_ci_and_the_merge_base_locally(monkeypatch):
    seen = GitRecorder()
    monkeypatch.setattr(gate, "git_text", seen)
    ci = SimpleNamespace(repo=Path("/r"), mode="ci", gated_sha=SHA, base_ref="main")
    gate.resolve_base(ci)
    local = SimpleNamespace(repo=Path("/r"), mode="local", gated_sha=SHA, base_ref="main")
    gate.resolve_base(local)
    assert seen.calls[0][1:] == (["rev-parse", f"{SHA}^1"], "diff could not be computed")
    assert seen.calls[1][1:] == (["merge-base", "main", SHA], "diff could not be computed")


@pytest.mark.parametrize(
    "content,reason",
    [
        (None, "no durations file was given"),
        ("missing", "durations file missing or unreadable"),
        ("{not json", "durations file is not valid JSON"),
        ('{"t": -1}', "durations file is not a JSON object of node ID to non-negative integer"),
        ('["t"]', "durations file is not a JSON object of node ID to non-negative integer"),
    ],
)
def test_each_unusable_durations_file_gives_its_own_reason(tmp_path, content, reason):
    path = None
    if content is not None:
        path = tmp_path / "durations.json"
        if content != "missing":
            path.write_text(content, encoding="utf-8")
    assert gate.read_durations(path) == (None, reason)


def test_events_skip_a_line_that_is_not_json_and_carry_on_and_replace_bytes_that_are_not_utf8(
    tmp_path,
):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'\xff garbage\nnot json\n[1]\n{"event": "a"}\n{"event": "b"}\n')
    assert gate.read_events(path) == [{"event": "a"}, {"event": "b"}]


def test_a_missing_events_file_is_no_events(tmp_path):
    assert gate.read_events(tmp_path / "none.jsonl") == []


class ChunkHandle:
    """A binary file that yields the given chunks, then empty reads, and fails the test if over-read."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sizes = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=None):
        self.sizes.append(size)
        assert len(self.sizes) < 10, "read past the end of the file"
        return self.chunks.pop(0) if self.chunks else b""


def test_a_file_is_hashed_in_one_mebibyte_reads_until_the_first_empty_read(monkeypatch):
    handle = ChunkHandle([b"ab", b"cd"])
    monkeypatch.setattr(gate, "open", lambda path, mode: handle, raising=False)
    assert gate.sha256_file(Path("/x")) == hashlib.sha256(b"abcd").hexdigest()
    assert handle.sizes == [1 << 20] * 3


def test_a_fragment_that_is_a_symlink_or_a_file_is_refused_with_the_shape_message(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / gate.FRAGMENT_FILENAME).write_text('{"a": 1}', encoding="utf-8")
    fragments = tmp_path / "fragments"
    fragments.mkdir()
    (fragments / "good").mkdir()
    (fragments / "good" / gate.FRAGMENT_FILENAME).write_text('{"b": 2}', encoding="utf-8")
    (fragments / "link").symlink_to(real, target_is_directory=True)
    (fragments / "plain").write_text("x", encoding="utf-8")
    refusal = f"must be a directory holding exactly {gate.FRAGMENT_FILENAME}"
    assert gate.read_fragments(fragments) == {"good": {"b": 2}, "link": refusal, "plain": refusal}


def test_a_missing_fragments_directory_holds_no_fragments(tmp_path):
    assert gate.read_fragments(tmp_path / "none") == {}


def test_releasing_a_workspace_forgets_it_and_deletes_it_even_when_it_is_already_gone(tmp_path):
    ctx = make_ctx(tmp_path)
    ws = make_workspace(tmp_path)
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    work.workspace = ws
    ctx.workspaces.append(ws)
    gate.release_workspace(ctx, work)
    assert work.workspace is None and ctx.workspaces == [] and not ws.root.exists()
    gone = gate.Workspace(tmp_path / "gone", tmp_path / "gone" / "tree", tmp_path, tmp_path)
    work.workspace = gone
    ctx.workspaces.append(gone)
    gate.release_workspace(ctx, work)
    assert work.workspace is None


# --------------------------------------------------------------------------
# shard_timeout, require_mutmut_config, run_phase
# --------------------------------------------------------------------------


def test_the_shard_timeout_names_the_phase_that_ran_out_or_says_it_is_unrecorded(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.label = "shard 1 of 2"
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    unrecorded = gate.shard_timeout(ctx, [work])
    assert unrecorded["phase"] == "" and unrecorded["file"] == ""
    assert unrecorded["message"].startswith(
        "shard 1 of 2 overran its budget (ran out in an unrecorded phase;"
    )
    ctx.expired_phase, ctx.expired_file = "mutate", "scripts/a.py"
    named = gate.shard_timeout(ctx, [work])
    assert named["phase"] == "mutate" and named["file"] == "scripts/a.py"
    assert "(ran out in mutate;" in named["message"]
    ctx.charge_setup(7)
    assert (
        "(7s of job setup was charged to the budget)" in gate.shard_timeout(ctx, [work])["message"]
    )


@pytest.mark.parametrize(
    "pyproject",
    [
        None,
        "not = [valid",
        "x = 1\n",
        "[tool]\nx = 1\n",
        '[tool.mutmut]\nonly_mutate = ["other.py"]\n',
    ],
)
def test_a_child_phase_refuses_a_workspace_without_the_exact_mutmut_config(tmp_path, pyproject):
    if pyproject is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    with pytest.raises(gate.GateError) as caught:
        gate.require_mutmut_config(tmp_path, "scripts/a.py")
    expected = (
        "child phase needs a workspace pyproject.toml"
        if pyproject in (None, "not = [valid")
        else "workspace only_mutate is not [scripts/a.py]"
    )
    assert str(caught.value) == expected


def test_a_child_phase_accepts_a_workspace_that_mutates_exactly_the_file(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.mutmut]\nonly_mutate = ["scripts/a.py"]\n', encoding="utf-8"
    )
    gate.require_mutmut_config(tmp_path, "scripts/a.py")


class RecordingRunner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, phase, spec):
        self.calls.append((phase, spec))
        return self.result


def phase_ctx(tmp_path, runner, clock):
    ctx = make_ctx(tmp_path, clock=clock)
    ctx.runner = runner
    return ctx


def test_a_phase_is_given_the_time_left_and_its_spend_is_charged(tmp_path):
    runner = RecordingRunner(gate.ProcResult(0, "o", "e", False))
    ctx = phase_ctx(tmp_path, runner, ScriptedClock(100.0, 110.0, 112.5))
    result = gate.run_phase(ctx, "collect", ["a"], tmp_path, {"E": "1"})
    assert result.stdout == "o"
    phase, spec = runner.calls[0]
    assert phase == "collect" and spec == gate.ProcSpec(["a"], str(tmp_path), {"E": "1"}, 40.0)
    assert ctx.phase_seconds == {"collect": 2.5}


@pytest.mark.parametrize("now", [150.0, 151.0])
def test_a_phase_that_starts_with_no_time_left_is_never_run_and_names_itself(tmp_path, now):
    runner = RecordingRunner(gate.ProcResult(0, "", "", False))
    ctx = phase_ctx(tmp_path, runner, ScriptedClock(100.0, now))
    with pytest.raises(gate.BudgetExpired) as caught:
        gate.run_phase(ctx, "mutate", ["a"], tmp_path, {})
    assert str(caught.value) == "mutate" and ctx.expired_phase == "mutate" and runner.calls == []


def test_a_phase_with_under_one_second_left_still_runs(tmp_path):
    runner = RecordingRunner(gate.ProcResult(0, "", "", False))
    ctx = phase_ctx(tmp_path, runner, ScriptedClock(100.0, 149.5, 149.6))
    gate.run_phase(ctx, "mutate", ["a"], tmp_path, {})
    assert runner.calls[0][1].timeout == 0.5


def test_a_phase_that_times_out_names_itself_in_the_budget_error(tmp_path):
    runner = RecordingRunner(gate.ProcResult(-9, "", "", True))
    ctx = phase_ctx(tmp_path, runner, ScriptedClock(100.0, 110.0, 111.0))
    with pytest.raises(gate.BudgetExpired) as caught:
        gate.run_phase(ctx, "collect", ["a"], tmp_path, {})
    assert str(caught.value) == "collect" and ctx.expired_phase == "collect"


# --------------------------------------------------------------------------
# run_local, run_shards, settle_selection, record_mutants
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plan_code,shards_ok,expected",
    [
        (0, True, ("success", "success")),
        (3, True, ("failure", "success")),
        (0, False, ("success", "failure")),
        (3, False, ("failure", "failure")),
    ],
)
def test_the_local_run_hands_the_merge_a_success_or_failure_for_the_plan_and_for_the_shards(
    monkeypatch, tmp_path, plan_code, shards_ok, expected
):
    shard_run = gate.ShardRun({}, plan_code, [], shards_ok)
    seen = {}
    monkeypatch.setattr(gate, "run_shards", lambda *args: shard_run)

    def fake_merge(plan_dir, fragments_dir, results, binding, clock):
        seen.update(results=results, binding=binding, plan=plan_dir, fragments=fragments_dir)
        return {"r": 1}

    monkeypatch.setattr(gate, "merge_records", fake_merge)
    monkeypatch.setattr(gate, "build_verdict", lambda records: ("doc", "text", 0))
    run = gate.run_local(plan_options(), NoRunner(), ScriptedClock(), tmp_path)
    assert seen["results"] == expected
    assert seen["binding"] == {
        "mode": "ci",
        "gated_sha": SHA,
        "pr": 7,
        "run_id": "11",
        "run_attempt": 2,
    }
    assert seen["plan"] == tmp_path / "plan" and seen["fragments"] == tmp_path / "fragments"
    assert (run.records, run.verdict, run.summary, run.code) == ({"r": 1}, "doc", "text", 0)


@pytest.mark.parametrize("only,allowed", [(0, False), (1, True), (3, True), (4, False)])
def test_only_a_shard_inside_one_to_n_may_be_asked_for(monkeypatch, tmp_path, only, allowed):
    monkeypatch.setattr(gate, "plan", lambda *args: ({"N": 3}, 0))
    monkeypatch.setattr(gate, "shard_options", lambda opts, index, plan_dir: index)
    ran = []

    def fake_shard(index, runner, clock):
        ran.append(index)
        return {"index": index}, 0

    monkeypatch.setattr(gate, "run_shard", fake_shard)
    if allowed:
        result = gate.run_shards(plan_options(), NoRunner(), ScriptedClock(), tmp_path, only)
        assert ran == [only] and result.shards_ok is True
        name = gate.FRAGMENT_DIR_FORMAT.format(index=only, count=3)
        assert (tmp_path / "fragments" / name / gate.FRAGMENT_FILENAME).is_file()
    else:
        with pytest.raises(gate.GateError) as caught:
            gate.run_shards(plan_options(), NoRunner(), ScriptedClock(), tmp_path, only)
        assert str(caught.value) == f"--only-shard {only} is outside 1..3"


@pytest.mark.parametrize(
    "selected,gated,logic_free,code,done",
    [
        ([], ["m1"], True, "no_test_exercises", True),
        ([], [], False, "zero_mutant_decision_logic", True),
    ],
)
def test_an_empty_selection_that_fails_finishes_the_file_with_its_reason(
    selected, gated, logic_free, code, done
):
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    work.selected, work.gated_names, work.logic_free = selected, gated, logic_free
    work.findings = [{"line": 1, "kind": "if", "carve_out": None}]
    gate.settle_selection(work)
    assert work.done is done
    assert [r["code"] for r in work.record["fail_reasons"]] == [
        work.record["fail_reasons"][0]["code"]
    ]
    if code == "no_test_exercises":
        assert work.record["mutation_reason"] == "selection_empty"
    else:
        assert work.record["mutation_ran"] is True


def test_a_file_with_no_gated_mutants_and_no_logic_is_finished_and_a_selected_one_is_left_open():
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    gate.settle_selection(work)
    assert work.done is True and work.record["mutation_ran"] is True
    assert work.record["selection_method"] == "not_required_zero_mutants"
    selected = gate.FileRun(ncg.blank_file_record("scripts/b.py", "new"), "")
    selected.selected = ["tests/t.py::a"]
    gate.settle_selection(selected)
    assert selected.done is True and selected.record["mutation_ran"] is True
    assert selected.record["selection_method"] != "not_required_zero_mutants"


class CollectRig:
    def __init__(self, tmp_path, monkeypatch, doc, clock=None):
        self.ctx = make_ctx(tmp_path, clock=clock or ScriptedClock(100.0, 1.0, 2.23456))
        self.ctx.label = "shard 1 of 2"
        self.work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
        self.work.workspace = make_workspace(tmp_path)
        self.work.mutant_names = [KEY]
        self.work.gated_names = [KEY]
        monkeypatch.setattr(gate, "run_phase", lambda *args: gate.ProcResult(0, "", "", False))
        monkeypatch.setattr(gate, "child_argv", lambda *args: ["x"])
        monkeypatch.setattr(gate, "child_env", lambda ctx: {})
        monkeypatch.setattr(gate, "parse_child_json", lambda *args: doc)
        monkeypatch.setattr(gate, "check_gate_file", lambda *args: None)


def test_collected_mutants_are_classified_and_the_file_is_marked_as_run(tmp_path, monkeypatch):
    doc = {"exit_code_by_key": {KEY: 1}, "status_by_key": {KEY: "killed"}}
    rig = CollectRig(tmp_path, monkeypatch, doc)
    gate.record_mutants(rig.ctx, rig.work, False)
    assert rig.work.status_by_key == {KEY: "killed"}
    assert rig.work.record["mutation_ran"] is True and rig.work.done is True
    assert rig.work.record["collect_seconds"] == 1.235


@pytest.mark.parametrize(
    "doc",
    [
        {"exit_code_by_key": [], "status_by_key": {}},
        {"exit_code_by_key": {}, "status_by_key": []},
    ],
)
def test_collected_results_with_either_part_not_an_object_are_unreadable(
    tmp_path, monkeypatch, doc
):
    rig = CollectRig(tmp_path, monkeypatch, doc)
    with pytest.raises(gate.GateError) as caught:
        gate.record_mutants(rig.ctx, rig.work, False)
    assert str(caught.value) == "mutation results could not be read: scripts/a.py"


# --------------------------------------------------------------------------
# run_shard, prepare_files, prepare_python, prepare_shell, prepare_non_regular
# --------------------------------------------------------------------------


class StepClock:
    """The first `monotonic` read is `first`; every later one is `later`."""

    def __init__(self, first, later, utc):
        self.reads = [first]
        self.later = later
        self.utc = list(utc)

    def monotonic(self):
        return self.reads.pop(0) if self.reads else self.later

    def utc_iso(self):
        return self.utc.pop(0)

    def epoch(self):
        return 0


def shard_options_for(tmp_path):
    return gate.ShardOptions(
        repo=tmp_path / "repo",
        gated_sha=SHA,
        pr=7,
        run_id="11",
        run_attempt=2,
        mode="ci",
        index=1,
        plan_dir=tmp_path,
        installed={},
        python="3.12",
        python_exe=sys.executable,
        environ={},
        keep_workspace=False,
        job_start_file=None,
    )


def shard_rig(monkeypatch, work, run_assigned):
    monkeypatch.setattr(gate, "load_shard_plan", lambda opts: {"N": 2, "plan_hash": "h"})
    monkeypatch.setattr(gate, "tracked_modes", lambda repo, sha: {})
    monkeypatch.setattr(gate, "assigned_works", lambda plan_doc, index: [work])
    monkeypatch.setattr(gate, "run_assigned", run_assigned)


def shard_work():
    work = gate.FileRun(ncg.blank_file_record("scripts/a.py", "new"), "")
    work.done = True
    return work


def test_a_shard_that_finishes_stamps_its_times_and_reports_a_complete_fragment(
    tmp_path, monkeypatch
):
    shard_rig(monkeypatch, shard_work(), lambda ctx, works: False)
    clock = StepClock(10.0, 11.23456, ["start", "finish"])
    doc, code = gate.run_shard(shard_options_for(tmp_path), NoRunner(), clock)
    assert code == 0 and doc["status"] == "complete" and doc["timeout"] is None
    assert doc["started_at"] == "start" and doc["finished_at"] == "finish"
    assert doc["seconds"] == 1.235 and doc["job_seconds"] is None
    assert doc["internal_errors"] == [] and doc["files"][0]["finished"] is True
    assert doc["binding"]["N"] == 2 and doc["binding"]["index"] == 1


def test_a_shard_that_overruns_reports_the_timeout_and_still_exits_zero(tmp_path, monkeypatch):
    shard_rig(monkeypatch, shard_work(), lambda ctx, works: True)
    doc, code = gate.run_shard(
        shard_options_for(tmp_path), NoRunner(), StepClock(10.0, 11.0, ["a", "b"])
    )
    assert code == 0 and doc["status"] == "timeout"
    assert doc["timeout"]["message"].startswith("shard 1 of 2 overran its budget")


def test_a_shard_that_fails_after_a_file_error_keeps_that_error_and_does_not_score_the_file(
    tmp_path, monkeypatch
):
    work = shard_work()

    def failing(ctx, works):
        ctx.internal_errors.append(
            {"code": "internal_error", "message": "first", "file": "scripts/a.py"}
        )
        raise ValueError("boom")

    shard_rig(monkeypatch, work, failing)
    doc, code = gate.run_shard(
        shard_options_for(tmp_path), NoRunner(), StepClock(10.0, 11.0, ["a", "b"])
    )
    assert code == 3 and doc["status"] == "internal_error" and doc["timeout"] is None
    assert doc["internal_errors"] == [
        {"code": "internal_error", "message": "first", "file": "scripts/a.py"},
        {"code": "internal_error", "message": "ValueError: boom"},
    ]
    assert doc["files"][0]["finished"] is False


def test_a_shard_that_fails_before_its_context_exists_reports_only_its_own_error(
    tmp_path, monkeypatch
):
    def refused(opts):
        raise gate.GateError("plan refused")

    monkeypatch.setattr(gate, "load_shard_plan", refused)
    doc, code = gate.run_shard(
        shard_options_for(tmp_path), NoRunner(), StepClock(10.0, 11.0, ["a", "b"])
    )
    assert code == 3 and doc["files"] == []
    assert doc["internal_errors"] == [{"code": "internal_error", "message": "plan refused"}]
    assert doc["binding"]["N"] is None and doc["binding"]["plan_hash"] is None


def prepare_ctx(tmp_path, monkeypatch, names):
    ctx = make_ctx(tmp_path)
    ctx.base_sha = "b" * 40
    ctx.modes = {"scripts/a.sh": "100644", "scripts/b.sh": "100644"}
    seen = GitRecorder(names)
    monkeypatch.setattr(gate, "git_text", seen)
    monkeypatch.setattr(
        gate, "prepare_shell", lambda ctx_, change: SimpleNamespace(path=change.path)
    )
    return ctx, seen


def test_the_changed_files_are_prepared_in_path_order_after_one_named_diff(tmp_path, monkeypatch):
    ctx, seen = prepare_ctx(tmp_path, monkeypatch, "names")
    monkeypatch.setattr(
        ncg,
        "parse_name_status",
        lambda names: [
            ncg.ChangedPath("A", "scripts/b.sh", None, "new"),
            ncg.ChangedPath("M", "scripts/a.sh", None, "modified"),
        ],
    )
    works = gate.prepare_files(ctx)
    assert [w.path for w in works] == ["scripts/a.sh", "scripts/b.sh"]
    assert seen.calls == [
        (
            ctx.repo,
            [*gate.GIT_DIFF_PREFIX, "--name-status", "b" * 40, SHA],
            "diff could not be computed",
        )
    ]


def test_a_changed_file_the_tree_listing_lacks_is_a_disagreement(tmp_path, monkeypatch):
    ctx, _ = prepare_ctx(tmp_path, monkeypatch, "names")
    ctx.modes = {}
    monkeypatch.setattr(
        ncg, "parse_name_status", lambda names: [ncg.ChangedPath("A", "scripts/a.sh", None, "new")]
    )
    with pytest.raises(gate.GateError) as caught:
        gate.prepare_files(ctx)
    assert str(caught.value) == "tree listing and diff disagree: scripts/a.sh"


class PythonRig:
    def __init__(self, tmp_path, monkeypatch, measured):
        self.ctx = make_ctx(tmp_path)
        self.ctx.cov = SimpleNamespace(lines=lambda path: {1, 5})
        self.ctx.meta = {"measured_sources": ["scripts"]}
        self.gated_args = []
        monkeypatch.setattr(gate, "blob_text", lambda repo, sha, path: "x = 1\ny = 2\n")
        monkeypatch.setattr(gate, "blob_shas", lambda ctx, path: ("b1", "b2"))
        monkeypatch.setattr(gate, "changed_lines", lambda ctx, change: {1, 2})
        monkeypatch.setattr(ncg, "in_measured_surface", lambda path, sources: measured)

        def gated(changed, statements, multiline, is_new):
            self.gated_args.append((changed, statements, multiline, is_new))
            return [1, 2]

        monkeypatch.setattr(ncg, "gated_statement_lines", gated)


@pytest.mark.parametrize("kind,is_new", [("new", True), ("modified", False)])
def test_a_measured_python_file_records_its_blobs_statements_and_executed_gated_lines(
    tmp_path, monkeypatch, kind, is_new
):
    rig = PythonRig(tmp_path, monkeypatch, True)
    work = gate.prepare_python(rig.ctx, ncg.ChangedPath("A", "scripts/a.py", None, kind))
    assert work.statements == {1, 2} and work.gated == [1, 2]
    assert rig.gated_args == [({1, 2}, {1, 2}, rig.gated_args[0][2], is_new)]
    assert (work.record["blob_sha"], work.record["pr_head_blob_sha"]) == ("b1", "b2")
    for name, value in ncg.coverage_fields(2, 1).items():
        assert work.record[name] == value
    assert work.done is False


def test_a_python_file_outside_the_measured_surface_is_blocked_with_zero_coverage(
    tmp_path, monkeypatch
):
    rig = PythonRig(tmp_path, monkeypatch, False)
    work = gate.prepare_python(rig.ctx, ncg.ChangedPath("A", "scripts/a.py", None, "new"))
    for name, value in ncg.coverage_fields(0, 0).items():
        assert work.record[name] == value
    assert work.record["mutation_reason"] == "blocked_by:not_measured" and work.done is True


def test_a_shell_file_and_a_non_regular_path_keep_both_blob_names_and_an_empty_text(
    tmp_path, monkeypatch
):
    ctx = make_ctx(tmp_path)
    monkeypatch.setattr(gate, "blob_shas", lambda ctx_, path: ("b1", "b2"))
    monkeypatch.setattr(gate, "blob_text", lambda repo, sha, path: "echo hi\n")
    monkeypatch.setattr(gate, "changed_lines", lambda ctx_, change: {1})
    monkeypatch.setattr(gate, "load_shell_rules", lambda: (lambda lines: [], lambda path: False))
    shell = gate.prepare_shell(ctx, ncg.ChangedPath("A", "scripts/x.sh", None, "new"))
    assert shell.text == "" and shell.record["pr_head_blob_sha"] == "b2"
    assert shell.record["blob_sha"] == "b1" and shell.done is True
    plain = gate.prepare_non_regular(
        ctx, ncg.ChangedPath("A", "scripts/a.py", None, "new"), "python", "120000"
    )
    assert plain.text == "" and plain.record["pr_head_blob_sha"] == "b2"
    assert plain.record["blob_sha"] == "b1" and plain.done is True
