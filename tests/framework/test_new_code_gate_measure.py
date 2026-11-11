"""`measure`, `verdict` and the CLI of the new-code gate, in process (#2304, TD section 9).

Every case builds its own fixture git repository under `tmp_path`, writes coverage data through
the `CoverageData` API and drives `measure` with a fake `Runner` for the four subprocess phases,
so real mutmut is never imported here (A9a). The real-mutmut cases live in
`test_new_code_gate_e2e.py`, which runs the CLI as a subprocess.

The gate modules are imported canonically and at module level (TD 5.19), and nothing here reads
the real repository's `.git` or `.claude/` (G-NOGIT): fixtures are `git init`ed in `tmp_path`.
"""

import contextlib
import copy
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import tomllib
from pathlib import Path

import pytest

from scripts.framework import new_code_gate as gate
from scripts.framework import new_code_gate_logic as ncg
from scripts.oversight.validators.shell_logic_check import decision_lines

CALC = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"
CALC_PATH = "scripts/framework/calc.py"
TEST_CALC = (
    "from scripts.framework.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
)
TEST_CALC_ID = "tests/test_calc.py::test_add"
CALC_LINES = [1, 2, 5, 6]
FIXED_NOW = "2026-01-01T00:00:00Z"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def argv_safe_id(value):
    """A parametrize id with no whitespace, so the gate never widens a selection to this module.

    `sanitize_node_ids` widens an id with whitespace to its whole module, and then every test
    in the module runs in every mutation workspace.
    """
    if isinstance(value, str):
        return re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_")[:48] or "empty"
    return None


def key(rel, n, func="f"):
    return f"{ncg.canonical_name(rel)}.x_{func}{n}__mutmut_1"


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def utc_iso(self):
        return FIXED_NOW


class Templates:
    """Fixture repositories built once per module and copied per test (ADR-2304 RV3-2a2).

    Each distinct repository (its base commit, plus the feature commit for `standard`) costs a
    handful of `git` spawns to build. A test gets its own `copytree` of the template in its
    `tmp_path`, so it still has a private, writable repository; the copy is never the repo root.
    """

    def __init__(self, factory):
        self.factory = factory
        self.built = {}

    def get(self, key, build):
        if key not in self.built:
            rig = Rig(self.factory.mktemp("template"), None)
            build(rig)
            self.built[key] = (rig.root, rig.head(), rig.git("rev-parse", "HEAD^{tree}"))
        return self.built[key]


class Rig:
    """A fixture repository plus the coverage data and sidecar that describe it."""

    def __init__(self, tmp_path, templates):
        self.templates = templates
        self.tmp = tmp_path
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.work = tmp_path / "work"
        self.work.mkdir()
        self.git("init", "-q", "-b", "main")

    def git(self, *args, cwd=None):
        env = dict(os.environ, **GIT_ENV)
        proc = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", *args],
            cwd=cwd or self.root,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self, message="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.head()

    def head(self):
        return self.git("rev-parse", "HEAD")

    def build_base(self, extra=None):
        for rel, text in (extra or {}).items():
            self.write(rel, text)
        self.write("README.md", "fixture\n")
        self.write("pyproject.toml", '[tool.pytest.ini_options]\naddopts = "-q"\n')
        self.write(gate.PLUGIN_RELPATH, "# stand-in plugin\n")
        self.write(".claude/settings.json", "{}\n")
        self.write("prompts/.claude/note.md", "x\n")
        self.commit("base")
        self.git("checkout", "-q", "-b", "feature")

    def build_standard(self):
        self.build_base()
        self.write(CALC_PATH, CALC)
        self.write("tests/test_calc.py", TEST_CALC)
        self.commit("feature")

    def adopt(self, key, build):
        """Copy the template repository for `key` (built on first use) over this rig's empty one."""
        path, head, tree = self.templates.get(key, build)
        shutil.copytree(path, self.root, dirs_exist_ok=True)
        return head, tree

    def base(self, extra=None):
        key = ("base", tuple(sorted((extra or {}).items())))
        self.adopt(key, lambda rig: rig.build_base(extra))

    def standard(self):
        """The base commit, then a feature commit adding `calc.py` and its test."""
        head, tree = self.adopt(("standard",), Rig.build_standard)
        self.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
        self.sidecar(head_sha=head, head_tree=tree)

    def coverage(self, mapping):
        """mapping: {rel: {context: [lines]}}, written under the repo's absolute paths."""
        from coverage import CoverageData

        path = self.tmp / ".coverage"
        path.unlink(missing_ok=True)
        data = CoverageData(basename=str(path))
        for rel, contexts in mapping.items():
            for context, lines in contexts.items():
                data.set_context(context)
                data.add_lines({str(self.root.resolve() / rel): lines})
        data.write()

    def sidecar(self, **override):
        meta = {
            "schema": ncg.SCHEMA_META,
            "head_sha": override.get("head_sha") or self.head(),
            "head_tree": override.get("head_tree") or self.git("rev-parse", "HEAD^{tree}"),
            "checkout_root": str(self.root.resolve()),
            "clean": True,
            "coverage_core": "ctrace",
            "run_id": None,
            "measured_sources": list(ncg.MEASURED_SOURCES),
            "tool_versions": dict(ncg.PINNED),
            "python": "3.12",
        }
        meta.update(override)
        (self.tmp / "coverage-meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def options(self, **override):
        values = {
            "repo": self.root,
            "gated_sha": self.head(),
            "pr_head_sha": self.head(),
            "pr": None,
            "coverage_file": self.tmp / ".coverage",
            "meta_path": self.tmp / "coverage-meta.json",
            "tests_result": None,
            "run_id": None,
            "run_attempt": None,
            "mode": "local",
            "base_ref": "main",
            "installed": dict(ncg.PINNED),
            "python": "3.12",
            "python_exe": sys.executable,
            "environ": {"TMPDIR": str(self.work)},
            "keep_workspace": False,
        }
        values.update(override)
        return gate.MeasureOptions(**values)

    def measure(self, runner=None, clock=None, **override):
        runner = runner or FakeRunner(self)
        return gate.measure(self.options(**override), runner, clock or FakeClock())


def write_files(root, files):
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class FakeRunner:
    """Scripts the four subprocess phases; every call is recorded."""

    def __init__(self, rig, clock=None):
        self.rig = rig
        self.clock = clock
        self.calls = []
        self.enum = {}
        self.statuses = {}
        self.repo_copy = (5, "")
        self.mutmut_rc = {}
        self.mutmut_output = {}
        self.extra_events = {}
        self.plugin_path = None
        self.write_plugin_event = True
        self.enum_result = {}
        self.collect_result = {}
        self.unmappable = {}
        self.gate_file = str(rig.root / "scripts/framework/new_code_gate.py")
        self.collect_gate_file = None
        self.timeout_on = set()
        self.hook = None
        self.mirror = True
        self.tamper = None

    def mirror_workspace(self, spec):
        """What a real `mutmut run` leaves in `mutants/`: a copy of the tree plus its own outputs."""
        tree = Path(spec.cwd)
        mutants = tree / "mutants"
        shutil.copytree(
            tree, mutants, ignore=lambda src, names: ["mutants"] if Path(src) == tree else []
        )
        rel = spec.env["NCG_GATED_FILE"]
        write_files(
            mutants,
            {
                rel: "# trampolined copy\n",
                rel + ".meta": "{}",
                rel + ".spans": "{}",
                "mutmut-stats.json": "{}",
                "mutmut-cicd-stats.json": "{}",
                "mutmut-debug.log": "log\n",
                "tests/__pycache__/test_calc.cpython-312.pyc": "pyc",
                ".pytest_cache/README.md": "cache",
            },
        )
        if self.tamper is not None:
            self.tamper(mutants)

    def mutants(self, rel, killed, survived, ungated_survived=0):
        gated = [key(rel, i) for i in range(killed + survived)]
        ungated = [key(rel, 1000 + i) for i in range(ungated_survived)]
        self.enum[rel] = (gated + ungated, gated)
        status = {k: "killed" for k in gated[:killed]}
        status.update({k: "survived" for k in gated[killed:] + ungated})
        self.statuses[rel] = status

    def run(self, phase, spec):
        self.calls.append((phase, spec))
        if self.hook is not None:
            self.hook(phase, spec)
        if phase in self.timeout_on:
            return gate.ProcResult(-15, "", "", True)
        return getattr(self, "on_" + phase)(spec)

    def calls_for(self, phase):
        return [spec for p, spec in self.calls if p == phase]

    def rel(self, spec):
        return spec.argv[spec.argv.index("--file") + 1]

    def on_repo_copy_collect(self, spec):
        rc, out = self.repo_copy
        return gate.ProcResult(rc, out, "", False)

    def on_enumerate(self, spec):
        rel = self.rel(spec)
        if rel in self.enum_result:
            return self.enum_result[rel]
        names, gated = self.enum.get(rel, ([], []))
        doc = {
            "schema": ncg.SCHEMA_ENUM,
            "file": rel,
            "gate_file": self.gate_file,
            "mutant_names": names,
            "gated_mutant_names": gated,
            "line_map": {},
            "unmappable": self.unmappable.get(rel, []),
        }
        return gate.ProcResult(0, json.dumps(doc), "", False)

    def selection(self, spec):
        parsed = tomllib.loads((Path(spec.cwd) / "pyproject.toml").read_text(encoding="utf-8"))
        return parsed["tool"]["mutmut"]["pytest_add_cli_args_test_selection"]

    def on_mutmut_run(self, spec):
        rel = spec.env["NCG_GATED_FILE"]
        events = []
        if self.write_plugin_event:
            plugin = self.plugin_path or str(
                Path(spec.env["PYTHONPATH"].split(os.pathsep)[0]) / "_ncg_tripwire.py"
            )
            events.append({"event": "plugin_loaded", "path": plugin})
        events.extend({"event": "executed", "node": n} for n in self.selection(spec))
        events.extend(self.extra_events.get(rel, []))
        with open(spec.env["NCG_LOG"], "a", encoding="utf-8") as log:
            log.writelines(json.dumps(e) + "\n" for e in events)
        if self.mirror:
            self.mirror_workspace(spec)
        rc = self.mutmut_rc.get(rel, 0)
        return gate.ProcResult(rc, self.mutmut_output.get(rel, ""), "", False)

    def on_collect(self, spec):
        rel = self.rel(spec)
        if rel in self.collect_result:
            return self.collect_result[rel]
        statuses = self.statuses.get(rel, {})
        doc = {
            "schema": ncg.SCHEMA_COLLECT,
            "file": rel,
            "gate_file": self.collect_gate_file or self.gate_file,
            "exit_code_by_key": {k: (None if v is None else 1) for k, v in statuses.items()},
            "status_by_key": statuses,
        }
        return gate.ProcResult(0, json.dumps(doc), "", False)


@pytest.fixture(scope="session")
def templates(tmp_path_factory):
    # Session scope, not module: a mutation run hands pytest its node IDs in arbitrary order, which
    # interleaves this module's tests with another's, and a module-scoped fixture would then be
    # rebuilt at every switch (a hundred templates, past the tmp budget).
    return Templates(tmp_path_factory)


@pytest.fixture
def rig(tmp_path, templates):
    return Rig(tmp_path, templates)


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path, monkeypatch):
    """A mutant that turns a computed path relative lands here, never in mutmut's cwd (RV3-7a)."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def keep_the_hosts_sigterm_handler():
    """`measure` and `run` install a SIGTERM handler (RV-4); no test may leave it in the host."""
    before = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGTERM, before)


@pytest.fixture
def std(rig):
    rig.standard()
    runner = FakeRunner(rig)
    runner.mutants(CALC_PATH, killed=3, survived=1)
    return rig, runner


def file_rec(doc, path=CALC_PATH):
    return next(f for f in doc["files"] if f["path"] == path)


def codes_of(rec):
    return [r["code"] for r in rec["fail_reasons"]]


def verdict_of(doc):
    vdoc, summary, code = gate.build_verdict(doc, None)
    return vdoc, summary, code


def verdict_codes(doc, path=CALC_PATH):
    vdoc = verdict_of(doc)[0]
    return [r["code"] for r in next(f for f in vdoc["files"] if f["path"] == path)["fail_reasons"]]


def internal_messages(doc):
    return [e["message"] for e in doc["internal_errors"]]


def lines_text(n, start=1, offset=0):
    return "".join(f"a{i} = {i + offset}\n" for i in range(start, start + n))


# --------------------------------------------------------------------------
# Happy path, schema, determinism
# --------------------------------------------------------------------------


def test_pr_meeting_targets_passes_and_record_has_every_field(std):
    rig, runner = std
    doc, code = rig.measure(runner)
    assert code == 0
    assert set(doc) == set(ncg.TOP_LEVEL_FIELDS)
    rec = file_rec(doc)
    assert set(rec) == set(ncg.FILE_FIELDS)
    assert (rec["kind"], rec["gated_statements"], rec["executed_gated"]) == ("new", 4, 4)
    assert (rec["mutants_total"], rec["mutants_killed"], rec["mutant_score_pct"]) == (4, 3, 75.0)
    assert rec["mutation_ran"] is True
    assert rec["selection_method"] == "context"
    assert rec["selected_tests"] == [TEST_CALC_ID]
    assert verdict_of(doc)[2] == 0
    assert doc["phase"] == "measure" and doc["mode"] == "local"
    assert doc["gated_tree"] == rig.git("rev-parse", "HEAD^{tree}")
    assert doc["base_sha"] == rig.git("rev-parse", "main")


def test_record_carries_blob_sha(std):
    rig, runner = std
    rec = file_rec(rig.measure(runner)[0])
    assert rec["blob_sha"] == rig.git("rev-parse", f"HEAD:{CALC_PATH}")
    assert rec["pr_head_blob_sha"] == rec["blob_sha"]


def measure_with_step(rig, step, killed=3):
    clock = FakeClock()
    runner = FakeRunner(rig)
    runner.mutants(CALC_PATH, killed=killed, survived=4 - killed)
    runner.hook = lambda phase, spec: setattr(clock, "t", clock.t + step)
    return rig.measure(runner, clock)[0]


def test_twice_identical_records_sha256(std):
    rig, _ = std
    first = measure_with_step(rig, 1.0)
    second = measure_with_step(rig, 3.5)
    assert file_rec(first)["seconds"] != file_rec(second)["seconds"]
    assert first["seconds"] != second["seconds"]
    assert first["records_sha256"] == second["records_sha256"] == ncg.records_sha256(first["files"])
    assert measure_with_step(rig, 1.0, killed=4)["records_sha256"] != first["records_sha256"]
    assert file_rec(first)["enumerate_seconds"] != file_rec(second)["enumerate_seconds"]


def test_the_enumerate_phase_seconds_are_recorded_per_file_apart_from_the_total(std):
    """RV-3 (P-E): `_enumerate` time is its own field, so the 60 s / 25% trigger can be read."""
    rig, runner = std
    clock = FakeClock()
    runner.hook = lambda phase, spec: setattr(
        clock, "t", clock.t + {"enumerate": 7.0, "mutmut_run": 2.0}.get(phase, 0.0)
    )
    rec = file_rec(rig.measure(runner, clock)[0])
    assert rec["enumerate_seconds"] == 7.0
    assert rec["seconds"] == 9.0
    zero = ncg.blank_file_record("scripts/framework/z.py", "new")
    assert zero["enumerate_seconds"] == 0.0


def test_phase_seconds_are_recorded_apart_unhashed_and_sum_to_at_most_the_total(std, monkeypatch):
    """PHASE-SEC (RV3-4b): workspace, enumerate, mutmut and collect seconds, each its own field."""
    rig, runner = std
    clock = FakeClock()
    real = gate.make_workspace

    def slow_workspace(ctx, work):
        clock.t += 3.0
        return real(ctx, work)

    monkeypatch.setattr(gate, "make_workspace", slow_workspace)
    steps = {"enumerate": 7.0, "mutmut_run": 2.0, "collect": 0.5}
    runner.hook = lambda phase, spec: setattr(clock, "t", clock.t + steps.get(phase, 0.0))
    doc, _ = rig.measure(runner, clock)
    rec = file_rec(doc)
    phases = [rec[n] for n in ("workspace_seconds", "enumerate_seconds", "mutmut_seconds")]
    assert phases + [rec["collect_seconds"]] == [3.0, 7.0, 2.0, 0.5]
    assert rec["seconds"] == 12.5 and sum(phases) + rec["collect_seconds"] <= rec["seconds"]
    other = dict(rec, workspace_seconds=1.0, enumerate_seconds=1.0, mutmut_seconds=1.0)
    other["collect_seconds"] = 1.0
    assert ncg.records_sha256([other]) == ncg.records_sha256([rec]) == doc["records_sha256"]
    idle = file_rec(rig.measure(FakeRunner(rig), FakeClock())[0])
    assert (idle["workspace_seconds"], idle["mutmut_seconds"], idle["collect_seconds"]) == (
        0.0,
    ) * 3


ANSI_FAILURES = (
    "\x1b[31m==== FAILURES ====\x1b[0m\n"
    "____ test_add ____\n"
    "E   AssertionError: <b>|x`\n"
    "==== short test summary info ====\n"
    "FAILED tests/test_calc.py::test_add - AssertionError: <b>|x`\n"
    "!!!! stopping after 1 failures !!!!\n"
)


def test_isolation_failure_keeps_summary_and_tail_unhashed_and_never_decides(std):
    """ISO-DIAG (RV3-4a): the evidence rides in the record, is escaped when shown, and decides nothing."""
    rig, runner = std
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = ANSI_FAILURES + ncg.MUTMUT_STATS_FAILED_MESSAGE + "1\n"
    doc, code = rig.measure(runner)
    rec = file_rec(doc)
    failure = rec["isolation_failure"]
    assert code == 0 and codes_of(rec) == ["selected_test_fails_in_isolation"]
    assert failure["stage"] == "stats" and failure["node_ids"] == [TEST_CALC_ID]
    assert failure["summary_lines"] == [
        "FAILED tests/test_calc.py::test_add - AssertionError: <b>|x`"
    ]
    assert "\x1b" not in failure["output_tail"] and "FAILURES ====" in failure["output_tail"]
    assert failure["output_tail"].splitlines()[-1].endswith("runner returned 1")
    stripped = dict(rec, isolation_failure=None)
    assert doc["records_sha256"] == ncg.records_sha256([stripped])
    vdoc, summary, _ = verdict_of(doc)
    shown = "- FAILED tests/test_calc.py::test_add - AssertionError: &lt;b&gt;\\|x\\`"
    assert shown in summary
    quiet = dict(doc, files=[stripped], records_sha256=ncg.records_sha256([stripped]))
    assert verdict_of(quiet)[0]["files"][0]["fail_reasons"] == vdoc["files"][0]["fail_reasons"]


def alter(rel, text):
    def tamper(mutants):
        write_files(mutants, {rel: text})

    return tamper


def remove(rel):
    def tamper(mutants):
        (mutants / rel).unlink()

    return tamper


def link(rel, target):
    def tamper(mutants):
        (mutants / rel).symlink_to(target)

    return tamper


@pytest.mark.parametrize(
    "tamper,path",
    [
        (alter("tests/test_calc.py", "def test_add():\n    pass\n"), "tests/test_calc.py"),
        (alter("tests/injected.py", "x = 1\n"), "tests/injected.py"),
        (alter("scripts/framework/calc.py.bak", "x\n"), "scripts/framework/calc.py.bak"),
        (alter("mutmut-stats.json.old", "{}"), "mutmut-stats.json.old"),
        (alter("other/__pycache__x/y.py", "x"), "other/__pycache__x/y.py"),
        (remove("README.md"), "README.md"),
        (remove("tests/test_calc.py"), "tests/test_calc.py"),
        (link("tests/ghost.py", "/nonexistent"), "tests/ghost.py"),
    ],
    ids=[
        "altered",
        "added",
        "added-near-gated",
        "added-near-output",
        "added-fake-cache",
        "removed",
        "removed-test",
        "dangling-link",
    ],
)
def test_ws_integ_1_a_run_that_changes_the_mutants_tree_is_exit_3_and_names_the_path(
    std, tamper, path
):
    rig, runner = std
    runner.tamper = tamper
    doc, code = rig.measure(runner)
    assert code == 3
    assert internal_messages(doc) == [f"mutation run modified the workspace: {path}"]
    rec = file_rec(doc)
    assert rec["mutation_reason"] == "internal_error" and rec["mutants_total"] == 0
    assert runner.calls_for(gate.PHASE_COLLECT) == []


def test_ws_integ_1_the_check_runs_whatever_mutmuts_exit_code_and_before_any_attribution(std):
    rig, runner = std
    runner.tamper = alter("tests/injected.py", "x = 1\n")
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = SUMMARY + "\n" + ncg.MUTMUT_STATS_FAILED_MESSAGE + "1\n"
    doc, code = rig.measure(runner)
    assert code == 3 and codes_of(file_rec(doc)) == []
    assert internal_messages(doc) == ["mutation run modified the workspace: tests/injected.py"]


def test_ws_integ_1_names_at_most_twenty_paths_sorted(std):
    rig, runner = std
    runner.tamper = lambda mutants: write_files(mutants, {f"x/f{i:02d}.py": "x" for i in range(25)})
    message = internal_messages(rig.measure(runner)[0])[0]
    paths = message.removeprefix("mutation run modified the workspace: ").split(", ")
    assert paths == [f"x/f{i:02d}.py" for i in range(20)]


def test_ws_integ_2_a_clean_run_with_mutmuts_own_outputs_passes(std):
    rig, runner = std
    doc, code = rig.measure(runner)
    assert code == 0 and file_rec(doc)["mutation_ran"] is True and doc["internal_errors"] == []
    assert runner.calls_for(gate.PHASE_COLLECT)


def test_ws_integ_2_a_run_that_made_no_mutants_dir_is_judged_by_its_exit_code_alone(std):
    rig, runner = std
    runner.mirror = False
    runner.mutmut_rc[CALC_PATH] = 2
    doc, code = rig.measure(runner)
    assert code == 3 and internal_messages(doc) == ["mutmut exited 2"]


def build_tree(tmp_path, files):
    tree = tmp_path / "ws"
    write_files(tree, files)
    return tree


def mirror_tree(tree, extra=None):
    shutil.copytree(
        tree, tree / "mutants", ignore=lambda src, names: ["mutants"] if Path(src) == tree else []
    )
    write_files(tree / "mutants", extra or {})


def test_workspace_changes_compares_size_then_content_and_prunes_caches(tmp_path):
    tree = build_tree(tmp_path, {"a.py": "aaaa\n", "pkg/b.py": "bbbb\n", "pkg/m.py": "orig\n"})
    mirror_tree(tree, {"pkg/m.py": "TRAMP\n", "pkg/m.py.meta": "{}", "pkg/m.py.spans": "{}"})
    write_files(tree / "mutants", {"mutmut-stats.json": "{}", "__pycache__/a.pyc": "x"})
    write_files(tree / "mutants", {"pkg/__pycache__/b.pyc": "x", ".pytest_cache/v/c": "x"})
    assert gate.workspace_changes(tree, "pkg/m.py") == []
    write_files(tree / "mutants", {"a.py": "aaab\n"})
    assert gate.workspace_changes(tree, "pkg/m.py") == ["a.py"]
    write_files(tree / "mutants", {"a.py": "aaaa\n", "pkg/b.py": "bbbbbb\n"})
    assert gate.workspace_changes(tree, "pkg/m.py") == ["pkg/b.py"]


def test_workspace_changes_sees_other_files_named_like_outputs_and_other_gated_names(tmp_path):
    tree = build_tree(tmp_path, {"a.py": "a\n", "pkg/m.py": "orig\n", "pkg/n.py": "orig\n"})
    mirror_tree(tree, {"pkg/m.py": "TRAMP\n", "pkg/n.py": "CHANGED\n", "pkg/n.py.meta": "{}"})
    write_files(tree / "mutants", {"sub/mutmut-stats.json": "{}", "pkg/m.py.meta.x": "{}"})
    assert gate.workspace_changes(tree, "pkg/m.py") == [
        "pkg/m.py.meta.x",
        "pkg/n.py",
        "pkg/n.py.meta",
        "sub/mutmut-stats.json",
    ]


def test_workspace_changes_follows_links_and_flags_a_replaced_mutants_dir(tmp_path):
    tree = build_tree(tmp_path, {"real.txt": "r\n", "pkg/m.py": "orig\n", "d/inner.txt": "i\n"})
    (tree / "link.txt").symlink_to("real.txt")
    (tree / "dlink").symlink_to("d")
    mirror_tree(tree)
    assert gate.workspace_changes(tree, "pkg/m.py") == []
    (tree / "mutants" / "evil").symlink_to(tree / "d")
    assert gate.workspace_changes(tree, "pkg/m.py") == ["evil"]
    (tree / "mutants" / "evil").unlink()
    shutil.rmtree(tree / "mutants")
    assert gate.workspace_changes(tree, "pkg/m.py") == []
    (tree / "elsewhere").mkdir()
    (tree / "mutants").symlink_to(tree / "elsewhere")
    assert gate.workspace_changes(tree, "pkg/m.py") == ["mutants"]


def test_same_file_needs_two_files_of_equal_size_and_content(tmp_path):
    one, two, three = tmp_path / "one", tmp_path / "two", tmp_path / "three"
    one.write_text("abc")
    two.write_text("abc")
    three.write_text("abd")
    assert gate.same_file(one, two) and not gate.same_file(one, three)
    assert not gate.same_file(one, tmp_path) and not gate.same_file(tmp_path, one)
    assert not gate.same_file(one, tmp_path / "missing")
    two.write_text("abcd")
    assert not gate.same_file(one, two)
    big = tmp_path / "big"
    big.write_bytes(b"x" * (3 << 20))
    assert gate.sha256_file(big) == hashlib.sha256(b"x" * (3 << 20)).hexdigest()
    assert gate.sha256_file(one) == hashlib.sha256(b"abc").hexdigest()


def test_no_other_outcome_carries_isolation_failure(std):
    rig, runner = std
    assert file_rec(rig.measure(runner)[0])["isolation_failure"] is None
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = ncg.MUTMUT_CLEAN_FAILED_MESSAGE
    doc, code = rig.measure(runner)
    assert code == 3 and file_rec(doc)["isolation_failure"] is None


def test_noop_diff_zero_files_pass(rig):
    rig.base()
    rig.write("docs/note.md", "text\n")
    rig.commit("docs only")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    runner = FakeRunner(rig)
    doc, code = rig.measure(runner)
    assert (code, doc["files"], runner.calls) == (0, [], [])
    vdoc, summary, vcode = verdict_of(doc)
    assert vcode == 0 and summary == "No gated files in this PR.\n"


def test_workspaces_are_removed_unless_kept(std, capsys):
    rig, runner = std
    rig.measure(runner)
    assert list(rig.work.iterdir()) == []
    rig.measure(FakeRunner(rig), keep_workspace=True)
    kept = list(rig.work.iterdir())
    assert len(kept) == 1 and (kept[0] / "workspace" / CALC_PATH).is_file()
    assert "kept workspace" in capsys.readouterr().err


def test_each_files_workspace_is_deleted_as_soon_as_that_file_is_done(rig):
    """M4: two files must not hold two workspaces at once just because one finished first."""
    runner = two_file_rig(rig)
    live = []
    runner.hook = lambda phase, spec: phase == "mutmut_run" and live.append(
        len(list(rig.work.iterdir()))
    )
    doc, code = rig.measure(runner)
    assert code == 0 and all(f["mutation_ran"] for f in doc["files"])
    assert live == [2, 1]
    assert list(rig.work.iterdir()) == []


def test_a_zero_mutant_file_releases_its_workspace_before_the_others_run(rig):
    runner = two_file_rig(rig)
    runner.enum[CALC_PATH] = ([], [])
    live = []
    runner.hook = lambda phase, spec: phase == "mutmut_run" and live.append(
        len(list(rig.work.iterdir()))
    )
    rig.measure(runner)
    assert live == [1]


def test_kept_workspaces_are_reported_once_per_file(two_files, capsys):
    rig, runner = two_files
    rig.measure(runner, keep_workspace=True)
    kept = [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith("kept workspace")]
    assert len(kept) == 2 and len(set(kept)) == 2 and len(list(rig.work.iterdir())) == 2


@pytest.fixture
def two_files(rig):
    return rig, two_file_rig(rig)


def test_a_file_that_fails_while_building_its_workspace_leaves_nothing_behind(std, monkeypatch):
    rig, runner = std
    monkeypatch.setattr(gate, "contaminated", lambda tree: "mutants")
    doc, code = rig.measure(runner)
    assert code == 3 and internal_messages(doc) == ["workspace contaminated: mutants"]
    assert list(rig.work.iterdir()) == []


# --------------------------------------------------------------------------
# Coverage (AC-2, AC-3, AC-7, R-H2a, R-F8)
# --------------------------------------------------------------------------


def two_hundred_line_pr(rig, covered_changed, covered_unchanged):
    rig.base(extra={"scripts/framework/big.py": lines_text(200)})
    rig.write("scripts/framework/big.py", lines_text(100, offset=1) + lines_text(100, start=101))
    rig.commit("edit first hundred")
    executed = list(range(1, covered_changed + 1)) + list(range(101, 101 + covered_unchanged))
    rig.coverage({"scripts/framework/big.py": {"tests/test_big.py::t|run": executed}})
    rig.sidecar()


def test_changed_lines_79_fail_despite_file_above_80(rig):
    two_hundred_line_pr(rig, covered_changed=79, covered_unchanged=100)
    doc, code = rig.measure()
    rec = file_rec(doc, "scripts/framework/big.py")
    assert (rec["gated_statements"], rec["executed_gated"], rec["coverage_pct"]) == (100, 79, 79.0)
    assert code == 0
    assert verdict_codes(doc, rec["path"]) == ["coverage_below_threshold"]
    assert verdict_of(doc)[2] == 1


def test_changed_lines_80_pass_despite_file_below_80(rig):
    two_hundred_line_pr(rig, covered_changed=80, covered_unchanged=0)
    doc, _ = rig.measure()
    rec = file_rec(doc, "scripts/framework/big.py")
    assert (rec["gated_statements"], rec["executed_gated"], rec["coverage_pct"]) == (100, 80, 80.0)
    assert verdict_codes(doc, rec["path"]) == []


def test_pragma_no_cover_on_gated_line_still_counted(rig):
    rig.base()
    rig.write("scripts/framework/p.py", "a = 1\nb = 2  # pragma: no cover\n")
    rig.commit("p")
    rig.coverage({"scripts/framework/p.py": {"tests/test_p.py::t|run": [1]}})
    rig.sidecar()
    rec = file_rec(rig.measure()[0], "scripts/framework/p.py")
    assert (rec["gated_statements"], rec["executed_gated"], rec["coverage_pct"]) == (2, 1, 50.0)


def test_new_nonempty_init_measured(rig):
    rig.base()
    rig.write("scripts/framework/pkg/__init__.py", "A = 1\nB = 2\n")
    rig.commit("init")
    rig.coverage(
        {"scripts/framework/pkg/__init__.py": {"": [1, 2]}, "x.py": {"tests/t.py::t|run": [1]}}
    )
    rig.sidecar()
    rec = file_rec(rig.measure()[0], "scripts/framework/pkg/__init__.py")
    assert (rec["gated_statements"], rec["executed_gated"]) == (2, 2)
    assert rec["selection_method"] == "not_required_zero_mutants"
    assert codes_of(rec) == []


def test_new_file_outside_coverage_source_measured(rig):
    rig.base()
    rig.write("bootstrap/tool.py", lines_text(10))
    rig.commit("bootstrap")
    rig.coverage({"bootstrap/tool.py": {"tests/test_tool.py::t|run": list(range(1, 8))}})
    rig.sidecar()
    doc, _ = rig.measure()
    rec = file_rec(doc, "bootstrap/tool.py")
    assert (rec["gated_statements"], rec["executed_gated"], rec["coverage_pct"]) == (10, 7, 70.0)
    assert verdict_codes(doc, "bootstrap/tool.py") == ["coverage_below_threshold"]


def test_file_outside_the_measured_surface_fails_not_measured(rig):
    rig.base()
    rig.write("tools/thing.py", "a = 1\n")
    rig.commit("tools")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    runner = FakeRunner(rig)
    doc, code = rig.measure(runner)
    rec = file_rec(doc, "tools/thing.py")
    assert codes_of(rec) == ["not_measured"]
    assert rec["coverage_pct"] is None and rec["mutation_reason"] == "blocked_by:not_measured"
    assert rec["fail_reasons"][0]["message"] == ncg.MSG_NOT_MEASURED
    assert code == 0 and runner.calls == []
    assert verdict_codes(doc, "tools/thing.py") == ["not_measured"]


# --------------------------------------------------------------------------
# Mutant score and classification (AC-5, AC-27, H3)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("killed,expected", [(74, ["mutant_score_below_threshold"]), (75, [])])
def test_changed_lines_survivors_26pct_fail_unchanged_ignored(rig, killed, expected):
    rig.standard()
    runner = FakeRunner(rig)
    runner.mutants(CALC_PATH, killed=killed, survived=100 - killed, ungated_survived=20)
    doc, _ = rig.measure(runner)
    rec = file_rec(doc)
    assert (rec["mutants_total"], rec["mutants_killed"]) == (100, killed)
    assert verdict_codes(doc) == expected
    argv = runner.calls_for("mutmut_run")[0].argv
    assert argv[:4] == [sys.executable, "-m", "mutmut", "run"] and len(argv) == 104


def test_timeout_status_counts_as_killed_segfault_does_not(std):
    rig, runner = std
    names = runner.enum[CALC_PATH][1]
    runner.statuses[CALC_PATH] = dict(zip(names, ["timeout", "killed", "segfault", "survived"]))
    rec = file_rec(rig.measure(runner)[0])
    assert (rec["mutants_killed"], rec["mutant_status_counts"]) == (
        2,
        {"killed": 1, "timeout": 1, "segfault": 1, "survived": 1},
    )


def test_unexpected_mutant_status_exits_3(std):
    rig, runner = std
    names = runner.enum[CALC_PATH][1]
    runner.statuses[CALC_PATH][names[0]] = "caught by type check"
    doc, code = rig.measure(runner)
    assert code == 3 and "unexpected mutant status" in internal_messages(doc)[0]


def test_zero_mutants_clean_pass_total_0(std):
    rig, runner = std
    runner.enum[CALC_PATH] = ([], [])
    doc, code = rig.measure(runner)
    rec = file_rec(doc)
    assert (code, rec["mutation_ran"], rec["mutants_total"], rec["mutant_score_pct"]) == (
        0,
        True,
        0,
        None,
    )
    assert runner.calls_for("mutmut_run") == [] and runner.calls_for("collect") == []
    assert verdict_codes(doc) == []


def test_new_file_outside_source_paths_is_mutated(rig):
    rig.base()
    rig.write("bootstrap/tool.py", "def go():\n    return 1\n")
    rig.write("tests/test_tool.py", "def test_go():\n    pass\n")
    rig.commit("bootstrap")
    rig.coverage({"bootstrap/tool.py": {"tests/test_tool.py::test_go|run": [1, 2]}})
    rig.sidecar()
    seen = {}

    def hook(phase, spec):
        if phase == "enumerate":
            config = tomllib.loads((Path(spec.cwd) / "pyproject.toml").read_text())["tool"][
                "mutmut"
            ]
            seen.update(config)

    runner = FakeRunner(rig)
    runner.hook = hook
    runner.mutants("bootstrap/tool.py", killed=4, survived=0)
    rec = file_rec(rig.measure(runner)[0], "bootstrap/tool.py")
    assert rec["mutation_ran"] is True and rec["mutants_total"] == 4
    assert seen["only_mutate"] == ["bootstrap/tool.py"]
    assert "bootstrap/" in seen["source_paths"]


def test_mutmut_error_fails(std):
    rig, runner = std
    runner.mutmut_rc[CALC_PATH] = 2
    runner.mutmut_output[CALC_PATH] = "boom\n" * 100
    doc, code = rig.measure(runner)
    entry = doc["internal_errors"][0]
    assert code == 3 and entry["message"] == "mutmut exited 2" and entry["file"] == CALC_PATH
    assert len(entry["output_tail"].splitlines()) == gate.OUTPUT_TAIL_LINES
    assert file_rec(doc)["mutation_reason"] == "internal_error"
    assert verdict_of(doc)[2] == 3


# --------------------------------------------------------------------------
# Selection (AC-11, AC-12, AC-13, AC-14)
# --------------------------------------------------------------------------


def test_selection_only_tests_executing_gated_lines(rig):
    rig.standard()
    rig.coverage(
        {
            CALC_PATH: {
                "tests/test_calc.py::test_add|run": [1, 2, 5, 6],
                "tests/test_calc.py::test_add|setup": [1],
                "tests/test_other.py::test_other|run": [3],
                "": [1, 2, 5, 6],
            }
        }
    )
    runner = FakeRunner(rig)
    runner.mutants(CALC_PATH, killed=4, survived=0)
    rec = file_rec(rig.measure(runner)[0])
    assert rec["selected_tests"] == [TEST_CALC_ID]
    assert rec["selection_method"] == "context"


def test_no_contexts_no_name_match_fails_no_test_exercises(rig):
    rig.base()
    rig.write(CALC_PATH, CALC)
    rig.commit("calc without a test")
    rig.coverage({CALC_PATH: {"": CALC_LINES}, "x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    runner = FakeRunner(rig)
    runner.mutants(CALC_PATH, killed=4, survived=0)
    doc, code = rig.measure(runner)
    rec = file_rec(doc)
    assert codes_of(rec) == ["no_test_exercises"]
    assert (rec["selection_method"], rec["mutation_ran"], rec["mutation_reason"]) == (
        "none",
        False,
        "selection_empty",
    )
    assert runner.calls_for("mutmut_run") == [] and code == 0
    assert verdict_of(doc)[2] == 1


def test_empty_context_uses_name_fallback_recorded(rig):
    rig.base()
    rig.write(CALC_PATH, CALC)
    rig.write("tests/test_calc.py", TEST_CALC)
    rig.commit("calc")
    rig.coverage({CALC_PATH: {"": CALC_LINES}, "x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    runner = FakeRunner(rig)
    runner.mutants(CALC_PATH, killed=4, survived=0)
    rec = file_rec(rig.measure(runner)[0])
    assert (rec["selection_method"], rec["selected_tests"]) == (
        "name_fallback",
        ["tests/test_calc.py"],
    )
    assert rec["mutation_ran"] is True


def test_repo_copy_test_removed_and_listed_only_test_fails(rig):
    rig.standard()
    rig.coverage(
        {CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES, "tests/test_clone.py::test_clone|run": [1]}}
    )
    runner = FakeRunner(rig)
    runner.repo_copy = (
        0,
        "tests/test_clone.py::test_clone\n\n1/2 tests collected (1 deselected) in 0.01s\n",
    )
    runner.mutants(CALC_PATH, killed=4, survived=0)
    rec = file_rec(rig.measure(runner)[0])
    assert rec["selected_tests"] == [TEST_CALC_ID]
    assert rec["removed_repo_copy"] == ["tests/test_clone.py::test_clone"]
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
    only = FakeRunner(rig)
    only.repo_copy = (0, "tests/test_calc.py::test_add\n\n1 test collected\n")
    only.mutants(CALC_PATH, killed=4, survived=0)
    rec = file_rec(rig.measure(only)[0])
    assert (rec["selected_tests"], codes_of(rec)) == ([], ["no_test_exercises"])
    assert rec["removed_repo_copy"] == [TEST_CALC_ID]


def test_repo_copy_collect_argv_and_exit_codes(std):
    rig, runner = std
    environ = {"TMPDIR": str(rig.work), "NCG_LOG": "x", "GITHUB_TOKEN": "t", "KEEP": "1"}
    rig.measure(runner, environ=environ)
    spec = runner.calls_for("repo_copy_collect")[0]
    assert spec.argv == [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-m",
        "repo_copy",
        "-o",
        "addopts=",
        "-p",
        "no:cacheprovider",
        "--",
        TEST_CALC_ID,
    ]
    assert spec.cwd == str(rig.root) and spec.env["KEEP"] == "1"
    assert (
        "NCG_LOG" not in spec.env
        and "GITHUB_TOKEN" not in spec.env
        and "_ncg_tripwire" not in spec.argv
    )


def test_repo_copy_container_selection_keeps_id_and_lists_child(rig):
    rig.base()
    rig.write(CALC_PATH, CALC)
    rig.write("tests/test_calc.py", TEST_CALC)
    rig.commit("calc")
    rig.coverage({CALC_PATH: {"": CALC_LINES}, "x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    runner = FakeRunner(rig)
    runner.repo_copy = (0, "tests/test_calc.py::test_copy\n\n1 test collected\n")
    runner.mutants(CALC_PATH, killed=4, survived=0)
    rec = file_rec(rig.measure(runner)[0])
    assert rec["selected_tests"] == ["tests/test_calc.py"]
    assert rec["removed_repo_copy"] == ["tests/test_calc.py::test_copy"]


@pytest.mark.parametrize(
    "result,message",
    [
        ((2, ""), "repo_copy collection failed: pytest exited 2"),
        ((0, "garbage line\n"), "unparseable output"),
    ],
    ids=argv_safe_id,
)
def test_repo_copy_collect_failure_exits_3(std, result, message):
    rig, runner = std
    runner.repo_copy = result
    doc, code = rig.measure(runner)
    assert code == 3 and message in internal_messages(doc)[0]


# --------------------------------------------------------------------------
# Path-loaded modules (AC-16, AC-17)
# --------------------------------------------------------------------------


def test_static_spec_from_file_location_fails_with_named_fix(std):
    rig, runner = std
    rig.write(
        "tests/test_calc.py",
        'import importlib.util\nspec = importlib.util.spec_from_file_location("c", "scripts/framework/calc.py")\n',
    )
    rig.commit("path load")
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
    rig.sidecar()
    doc, _ = rig.measure(runner)
    rec = file_rec(doc)
    assert codes_of(rec) == ["path_loaded_module"] and rec["mutation_reason"] == "path_load"
    assert rec["fail_reasons"][0]["message"] == (
        "tests/test_calc.py loads scripts/framework/calc.py as module 'c' (static:spec_from_file_location) "
        "instead of the canonical 'import scripts.framework.calc' — convert to a canonical scripts.... "
        "import in this PR"
    )
    assert rec["path_load_findings"][0]["via"] == "static:spec_from_file_location"
    assert runner.calls_for("enumerate") == [] and runner.calls_for("mutmut_run") == []


def test_bare_sys_path_import_fails_with_named_fix(rig):
    rig.base()
    rig.write("scripts/oversight/shared_logic.py", "def f():\n    return 1\n")
    rig.write(
        "tests/test_shared.py",
        "import shared_logic\n\n\ndef test_f():\n    assert shared_logic.f()\n",
    )
    rig.commit("bare import")
    rig.coverage(
        {"scripts/oversight/shared_logic.py": {"tests/test_shared.py::test_f|run": [1, 2]}}
    )
    rig.sidecar()
    rec = file_rec(rig.measure()[0], "scripts/oversight/shared_logic.py")
    assert codes_of(rec) == ["path_loaded_module"]
    assert "'shared_logic' (static:bare_import)" in rec["fail_reasons"][0]["message"]


def test_shared_loaders_are_scanned_too(std):
    rig, runner = std
    rig.write("tests/registry_guard.py", 'spec_from_file_location("x", "calc.py")\n')
    rig.commit("shared loader")
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
    rig.sidecar()
    rec = file_rec(rig.measure(runner)[0])
    assert rec["path_load_findings"][0]["importer"] == "tests/registry_guard.py"


TRAMPOLINE = "... tests recorded trampoline hits but none match any mutant key ..."


def test_mutmut_trampoline_message_translated(std):
    rig, runner = std
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = TRAMPOLINE
    doc, code = rig.measure(runner)
    rec = file_rec(doc)
    message = rec["fail_reasons"][0]["message"]
    assert codes_of(rec) == ["path_loaded_module"] and code == 0
    assert ncg.MUTMUT_TRAMPOLINE_MESSAGE not in message
    assert "tests/test_calc.py" in message and ncg.MSG_PATH_LOAD_FIX in message
    assert verdict_of(doc)[2] == 1


def test_runtime_path_load_names_importer_and_wins_over_trampoline(std):
    rig, runner = std
    event = {
        "event": "path_load",
        "kind": "SourceFileLoader",
        "loaded_as": "calc",
        "importer": "tests/x.py",
        "phase": "session",
    }
    runner.extra_events[CALC_PATH] = [event]
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = TRAMPOLINE
    rec = file_rec(rig.measure(runner)[0])
    assert codes_of(rec) == ["path_loaded_module"]
    assert rec["path_load_findings"] == [
        {
            "importer": "tests/x.py",
            "loaded_as": "calc",
            "canonical": "scripts.framework.calc",
            "via": "runtime:SourceFileLoader",
            "phase": "session",
        }
    ]
    assert (
        "tests/x.py loads scripts/framework/calc.py as module 'calc' (runtime:SourceFileLoader)"
        in (rec["fail_reasons"][0]["message"])
    )


# --------------------------------------------------------------------------
# Integrity checks and attribution (A4a-A4c, A4f, A6a)
# --------------------------------------------------------------------------

REPO_COPY_EVENT = {
    "event": "repo_copy",
    "node": TEST_CALC_ID,
    "source": "/x",
    "via": "shutil.copytree",
}
PATH_LOAD_EVENT = {
    "event": "path_load",
    "kind": "run_path",
    "loaded_as": "c",
    "importer": "tests/x.py",
    "phase": "s",
}
SUMMARY = "=== short test summary info ===\nFAILED tests/test_calc.py::test_add - AssertionError\n=== 1 failed ==="


@pytest.mark.parametrize(
    "stage_message,stage",
    [(ncg.MUTMUT_STATS_FAILED_MESSAGE + "1", "stats"), (ncg.MUTMUT_CLEAN_FAILED_MESSAGE, "clean")],
    ids=argv_safe_id,
)
def test_isolation_failure_attributed_is_per_file_fail(std, stage_message, stage):
    rig, runner = std
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = f"{SUMMARY}\n{stage_message}\n"
    doc, code = rig.measure(runner)
    rec = file_rec(doc)
    assert codes_of(rec) == ["selected_test_fails_in_isolation"] and code == 0
    assert (
        TEST_CALC_ID in rec["fail_reasons"][0]["message"]
        and stage in rec["fail_reasons"][0]["message"]
    )
    assert rec["mutation_reason"] == "blocked_by:selected_test_fails_in_isolation"
    assert verdict_of(doc)[2] == 1


@pytest.mark.parametrize(
    "stage_message,stage",
    [(ncg.MUTMUT_STATS_FAILED_MESSAGE + "1", "stats"), (ncg.MUTMUT_CLEAN_FAILED_MESSAGE, "clean")],
    ids=argv_safe_id,
)
@pytest.mark.parametrize(
    "summary",
    ["", "=== short test summary info ===\nFAILED tests/elsewhere.py::t - boom\n"],
    ids=["no-id", "outside"],
)
def test_isolation_failure_unattributed_exit_3(std, stage_message, stage, summary):
    rig, runner = std
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = f"{summary}{stage_message}\n"
    doc, code = rig.measure(runner)
    entry = doc["internal_errors"][0]
    assert code == 3
    assert (entry["code"], entry["stage"]) == ("clean_run_unattributed", stage)
    assert entry["message"] == "clean run failed and no selected test could be identified"
    assert "see log" not in json.dumps(doc)


def test_no_test_case_stop_records_all_gated_no_tests(std):
    rig, runner = std
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = "x\n" + ncg.MUTMUT_NO_TEST_CASE_MESSAGE + "\n" + SUMMARY
    runner.statuses[CALC_PATH] = {k: None for k in runner.enum[CALC_PATH][0]}
    doc, code = rig.measure(runner)
    rec = file_rec(doc)
    assert code == 0
    assert (rec["mutants_killed"], rec["mutant_score_pct"], rec["mutation_ran"]) == (0, 0.0, True)
    assert rec["mutant_status_counts"] == {"no tests": 4} and rec["fail_reasons"] == []
    assert verdict_codes(doc) == ["mutant_score_below_threshold"]


@pytest.mark.parametrize(
    "events,expected",
    [
        ([{"event": "observer_error", "message": "x"}], "path-load recorder failed"),
        (
            [{"event": "executed", "node": "tests/other.py::stray"}],
            "mutation run executed unselected tests",
        ),
    ],
    ids=argv_safe_id,
)
@pytest.mark.parametrize(
    "extra", [[REPO_COPY_EVENT, PATH_LOAD_EVENT], []], ids=["with-tripwire", "alone"]
)
def test_integrity_checks_win_over_every_attribution_rule(std, events, expected, extra):
    rig, runner = std
    runner.extra_events[CALC_PATH] = events + extra
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = f"{SUMMARY}\n{ncg.MUTMUT_CLEAN_FAILED_MESSAGE}\n"
    doc, code = rig.measure(runner)
    assert code == 3 and expected in internal_messages(doc)[0]
    assert file_rec(doc)["fail_reasons"] == []


@pytest.mark.parametrize(
    "inside", [True, False], ids=["plugin-inside-workspace", "no-plugin-event"]
)
def test_plugin_dir_is_workspace_sibling_and_location_asserted(std, inside):
    rig, runner = std
    seen = {}

    def hook(phase, spec):
        if phase == "mutmut_run":
            plugin = Path(spec.env["PYTHONPATH"].split(os.pathsep)[0])
            seen["plugin"], seen["tree"] = plugin, Path(spec.cwd)

    runner.hook = hook
    runner.write_plugin_event = inside
    if inside:
        runner.plugin_path = "inside"
    doc, code = rig.measure(runner)
    assert code == 3
    assert internal_messages(doc) == ["tripwire plugin not loaded from outside the workspace"]
    plugin, tree = seen["plugin"], seen["tree"]
    assert plugin.name == "ncg-plugin" and tree.name == "workspace" and plugin.parent == tree.parent
    assert not tree.is_relative_to(plugin) and not plugin.is_relative_to(tree)


def test_plugin_path_inside_workspace_is_rejected(std):
    rig, runner = std

    def hook(phase, spec):
        if phase == "mutmut_run":
            runner.plugin_path = str(Path(spec.cwd) / "_ncg_tripwire.py")

    runner.hook = hook
    doc, code = rig.measure(runner)
    assert code == 3 and internal_messages(doc) == [
        "tripwire plugin not loaded from outside the workspace"
    ]


def test_tripwire_event_fails_unmarked_repo_copy_before_path_load(std):
    rig, runner = std
    runner.extra_events[CALC_PATH] = [REPO_COPY_EVENT, PATH_LOAD_EVENT]
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = f"{SUMMARY}\n{ncg.MUTMUT_CLEAN_FAILED_MESSAGE}\n"
    doc, code = rig.measure(runner)
    rec = file_rec(doc)
    assert codes_of(rec) == ["unmarked_repo_copy"] and code == 0
    assert (
        TEST_CALC_ID in rec["fail_reasons"][0]["message"]
        and "repo_copy" in rec["fail_reasons"][0]["message"]
    )
    assert verdict_of(doc)[2] == 1


def test_path_load_event_wins_over_isolation_and_trampoline_over_isolation(std):
    rig, runner = std
    runner.extra_events[CALC_PATH] = [PATH_LOAD_EVENT]
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = f"{SUMMARY}\n{ncg.MUTMUT_CLEAN_FAILED_MESSAGE}\n"
    assert codes_of(file_rec(rig.measure(runner)[0])) == ["path_loaded_module"]
    other = FakeRunner(rig)
    other.mutants(CALC_PATH, killed=3, survived=1)
    other.mutmut_rc[CALC_PATH] = 1
    other.mutmut_output[CALC_PATH] = f"{TRAMPOLINE}\n{SUMMARY}\n{ncg.MUTMUT_CLEAN_FAILED_MESSAGE}\n"
    assert codes_of(file_rec(rig.measure(other)[0])) == ["path_loaded_module"]


def test_no_test_case_stop_wins_over_isolation_message(std):
    rig, runner = std
    runner.statuses[CALC_PATH] = {k: None for k in runner.enum[CALC_PATH][0]}
    runner.mutmut_rc[CALC_PATH] = 1
    runner.mutmut_output[CALC_PATH] = (
        f"{SUMMARY}\n{ncg.MUTMUT_CLEAN_FAILED_MESSAGE}\n{ncg.MUTMUT_NO_TEST_CASE_MESSAGE}\n"
    )
    rec = file_rec(rig.measure(runner)[0])
    assert rec["mutant_status_counts"] == {"no tests": 4} and rec["fail_reasons"] == []


# --------------------------------------------------------------------------
# `_collect` read-back and `_enumerate` validation (A9a, A9d, A9e)
# --------------------------------------------------------------------------


def two_file_rig(rig):
    rig.base()
    rig.write(CALC_PATH, CALC)
    rig.write("scripts/framework/other.py", CALC)
    rig.write("tests/test_calc.py", TEST_CALC)
    rig.commit("two files")
    rig.coverage(
        {
            CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES},
            "scripts/framework/other.py": {"tests/test_other.py::test_o|run": CALC_LINES},
        }
    )
    rig.sidecar()
    runner = FakeRunner(rig)
    runner.mutants(CALC_PATH, killed=4, survived=0)
    runner.mutants("scripts/framework/other.py", killed=4, survived=0)
    return runner


class ForbidMutmut:
    """A meta-path finder that refuses `mutmut` and `libcst` and records every request."""

    def __init__(self):
        self.requests = []

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("mutmut", "libcst"):
            self.requests.append(name)
            raise ImportError(name)
        return None


def test_enumerate_and_collect_run_in_per_file_subprocesses_with_workspace_cwd(rig, monkeypatch):
    runner = two_file_rig(rig)
    environ = {
        "TMPDIR": str(rig.work),
        "NCG_LOG": "x",
        "GITHUB_TOKEN": "t",
        "ACTIONS_RUNTIME_TOKEN": "a",
        "KEEP": "1",
    }
    seen = []

    def hook(phase, spec):
        if phase in ("enumerate", "collect", "mutmut_run"):
            config = tomllib.loads((Path(spec.cwd) / "pyproject.toml").read_text())["tool"][
                "mutmut"
            ]
            seen.append((phase, spec, config["only_mutate"]))

    runner.hook = hook
    for name in [n for n in sys.modules if n.split(".")[0] in ("mutmut", "libcst")]:
        monkeypatch.delitem(sys.modules, name)
    finder = ForbidMutmut()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    doc, code = rig.measure(runner, environ=environ)
    assert code == 0 and finder.requests == []
    assert [f["mutation_ran"] for f in doc["files"]] == [True, True]
    by_phase = {
        p: [(s, o) for q, s, o in seen if q == p] for p in ("enumerate", "collect", "mutmut_run")
    }
    assert [len(v) for v in by_phase.values()] == [2, 2, 2]
    for phase in ("enumerate", "collect"):
        for spec, only in by_phase[phase]:
            assert spec.argv[1:5] == [
                "-I",
                "-c",
                ncg.ENTRY_SNIPPET,
                str(rig.root.resolve()),
            ]
            assert spec.argv[5] == f"_{phase}"
            assert spec.argv[spec.argv.index("--file") + 1] == only[0]
            assert "-m" not in spec.argv and "-P" not in spec.argv
            assert "PYTHONPATH" not in spec.env
            assert not any(
                k.startswith("NCG_") or k.startswith("ACTIONS_") or k == "GITHUB_TOKEN"
                for k in spec.env
            )
            assert spec.env["KEEP"] == "1"
    cwds = {spec.cwd for spec, _ in by_phase["enumerate"]}
    assert len(cwds) == 2 and cwds == {spec.cwd for spec, _ in by_phase["collect"]}
    for spec, only in by_phase["mutmut_run"]:
        assert spec.env["NCG_GATED_FILE"] == only[0] and "GITHUB_TOKEN" not in spec.env
        assert spec.env["NCG_WORKSPACE"] == spec.cwd and spec.env[
            "NCG_CANONICAL"
        ] == ncg.canonical_name(only[0])
        assert spec.env["PYTHONPATH"].split(os.pathsep)[0].endswith("ncg-plugin")


def inside_gate_hook(runner):
    def hook(phase, spec):
        runner.gate_file = str(Path(spec.cwd) / "scripts/framework/new_code_gate.py")

    return hook


def test_gate_file_outside_checkout_or_inside_workspace_exits_3(std):
    rig, runner = std
    for bad in ("/elsewhere/new_code_gate.py", "inside"):
        other = FakeRunner(rig)
        other.mutants(CALC_PATH, killed=4, survived=0)
        if bad == "inside":
            other.hook = inside_gate_hook(other)
        else:
            other.gate_file = bad
        doc, code = rig.measure(other)
        assert code == 3
        assert internal_messages(doc)[0].startswith("gate subprocess imported from the workspace: ")
    collect = FakeRunner(rig)
    collect.mutants(CALC_PATH, killed=4, survived=0)
    collect.collect_gate_file = "/elsewhere/new_code_gate.py"
    doc, code = rig.measure(collect)
    assert code == 3 and "imported from the workspace" in internal_messages(doc)[0]
    good, code = rig.measure(FakeRunner(rig))
    assert code == 0


def test_collect_drift_and_completeness_exit_3(std):
    rig, runner = std
    names = runner.enum[CALC_PATH][0]
    drift = "mutant enumeration drift"
    unread = f"mutation results could not be read: {CALC_PATH}"

    def doc_with(codes, statuses=None):
        return gate.ProcResult(
            0,
            json.dumps(
                {
                    "schema": ncg.SCHEMA_COLLECT,
                    "file": CALC_PATH,
                    "gate_file": runner.gate_file,
                    "exit_code_by_key": codes,
                    "status_by_key": (
                        statuses
                        if statuses is not None
                        else {k: None if v is None else "killed" for k, v in codes.items()}
                    ),
                }
            ),
            "",
            False,
        )

    cases = {
        drift: [
            doc_with({n: 1 for n in names[:-1]}),
            doc_with({**{n: 1 for n in names}, key(CALC_PATH, 99): 1}),
            doc_with({**{n: 1 for n in names[:-1]}, names[-1]: None}),
            doc_with({n: 1 for n in names}, {n: "killed" for n in names[:-1]}),
        ],
        unread: [
            gate.ProcResult(1, "{}", "", False),
            gate.ProcResult(0, "not json", "", False),
            gate.ProcResult(0, json.dumps({"schema": "other", "file": CALC_PATH}), "", False),
            gate.ProcResult(
                0, json.dumps({"schema": ncg.SCHEMA_COLLECT, "file": "other.py"}), "", False
            ),
            gate.ProcResult(
                0,
                json.dumps(
                    {"schema": ncg.SCHEMA_COLLECT, "file": CALC_PATH, "gate_file": runner.gate_file}
                ),
                "",
                False,
            ),
            doc_with({"bad name": 1}),
        ],
    }
    for expected, results in cases.items():
        for result in results:
            other = FakeRunner(rig)
            other.mutants(CALC_PATH, killed=4, survived=0)
            other.collect_result[CALC_PATH] = result
            doc, code = rig.measure(other)
            assert code == 3 and internal_messages(doc)[0] == expected, result
    expect_unrun = FakeRunner(rig)
    expect_unrun.mutants(CALC_PATH, killed=4, survived=0)
    expect_unrun.mutmut_rc[CALC_PATH] = 1
    expect_unrun.mutmut_output[CALC_PATH] = ncg.MUTMUT_NO_TEST_CASE_MESSAGE
    doc, code = rig.measure(expect_unrun)
    assert code == 3 and internal_messages(doc)[0] == drift


@pytest.mark.parametrize(
    "result,message",
    [
        (
            gate.ProcResult(3, "", "boom", False),
            "mutant enumeration failed: scripts/framework/calc.py",
        ),
        (
            gate.ProcResult(0, "not json", "", False),
            "mutant enumeration failed: scripts/framework/calc.py",
        ),
        (
            gate.ProcResult(0, json.dumps({"schema": "x", "file": CALC_PATH}), "", False),
            "mutant enumeration failed",
        ),
        (
            gate.ProcResult(
                0, json.dumps({"schema": ncg.SCHEMA_ENUM, "file": "other.py"}), "", False
            ),
            "mutant enumeration failed",
        ),
    ],
    ids=argv_safe_id,
)
def test_enumeration_subprocess_failure_exit_3(std, result, message):
    rig, runner = std
    runner.enum_result[CALC_PATH] = result
    doc, code = rig.measure(runner)
    assert code == 3 and message in internal_messages(doc)[0]
    assert doc["internal_errors"][0]["file"] == CALC_PATH


def test_unmappable_mutant_and_gated_outside_set_exit_3(std):
    rig, runner = std
    runner.unmappable[CALC_PATH] = [key(CALC_PATH, 7)]
    doc, code = rig.measure(runner)
    assert code == 3 and internal_messages(doc) == [
        f"mutant could not be mapped: {key(CALC_PATH, 7)}"
    ]
    other = FakeRunner(rig)
    other.enum[CALC_PATH] = ([key(CALC_PATH, 1)], [key(CALC_PATH, 2)])
    doc, code = rig.measure(other)
    assert code == 3 and "mutant enumeration failed" in internal_messages(doc)[0]


def test_other_files_still_get_records_when_one_file_errors(rig):
    runner = two_file_rig(rig)
    runner.enum_result[CALC_PATH] = gate.ProcResult(3, "", "boom", False)
    doc, code = rig.measure(runner)
    assert code == 3 and len(doc["files"]) == 2
    assert file_rec(doc, "scripts/framework/other.py")["mutation_ran"] is True
    assert [e["file"] for e in doc["internal_errors"]] == [CALC_PATH]
    vdoc, summary, vcode = verdict_of(doc)
    assert vcode == 3 and "Internal errors:" in summary


# --------------------------------------------------------------------------
# Budget (AC-10)
# --------------------------------------------------------------------------


def test_budget_exhausted_records_timeout_and_fails(rig):
    runner = two_file_rig(rig)
    clock = FakeClock()
    runner.clock = clock

    def hook(phase, spec):
        if phase == "mutmut_run":
            clock.t += ncg.BUDGET_SECONDS + 1

    runner.hook = hook
    runner.timeout_on = {"mutmut_run"}
    runner.mutants("scripts/framework/other.py", killed=0, survived=0)
    doc, code = rig.measure(runner, clock)
    assert code == 0
    by_path = {f["path"]: f for f in doc["files"]}
    calc, other = by_path[CALC_PATH], by_path["scripts/framework/other.py"]
    assert [codes_of(calc), calc["mutation_ran"], calc["mutation_reason"]] == [
        ["mutation_timeout"],
        False,
        "timeout",
    ]
    assert other["mutation_ran"] is True and codes_of(other) == []
    message = calc["fail_reasons"][0]["message"]
    assert message.startswith("mutation budget exhausted; split the PR (ran out in mutmut_run of ")
    assert verdict_of(doc)[2] == 1


def test_timeout_message_says_where_the_budget_went(rig):
    """M6: per-phase seconds, per-file seconds, and the file the budget ran out in."""
    runner = two_file_rig(rig)
    clock = FakeClock()
    runner.clock = clock

    def hook(phase, spec):
        clock.t += {"enumerate": 7.0, "mutmut_run": ncg.BUDGET_SECONDS}.get(phase, 0.0)

    runner.hook = hook
    runner.timeout_on = {"mutmut_run"}
    doc, _ = rig.measure(runner, clock)
    messages = {f["path"]: f["fail_reasons"][0]["message"] for f in doc["files"]}
    assert len(set(messages.values())) == 1
    message = messages[CALC_PATH]
    assert f"(ran out in mutmut_run of {CALC_PATH}; phases: " in message
    assert "enumerate 14.0s" in message and "mutmut_run 1500.0s" in message
    assert f"{CALC_PATH} 1507.0s (workspace 0.0s)" in message
    assert "scripts/framework/other.py 7.0s (workspace 0.0s)" in message


def test_timeout_before_any_file_step_still_names_the_phase(rig):
    runner = two_file_rig(rig)
    runner.timeout_on = {"repo_copy_collect"}
    doc, _ = rig.measure(runner)
    assert "ran out in repo_copy_collect; phases: " in doc["files"][0]["fail_reasons"][0]["message"]


def test_budget_expiry_marks_in_progress_and_not_started_files(rig):
    runner = two_file_rig(rig)
    runner.timeout_on = {"mutmut_run"}
    doc, code = rig.measure(runner)
    assert code == 0
    assert [(codes_of(f), f["mutation_ran"], f["mutation_reason"]) for f in doc["files"]] == [
        (["mutation_timeout"], False, "timeout")
    ] * 2
    assert len(runner.calls_for("mutmut_run")) == 1
    assert verdict_of(doc)[2] == 1


def test_budget_gone_before_repo_copy_collect_times_out_every_file(rig):
    runner = two_file_rig(rig)
    runner.timeout_on = {"repo_copy_collect"}
    doc, _ = rig.measure(runner)
    assert all(codes_of(f) == ["mutation_timeout"] for f in doc["files"])
    assert runner.calls_for("enumerate") == []


def test_budget_is_checked_before_a_phase_starts(std):
    rig, runner = std
    clock = FakeClock()
    runner.hook = lambda phase, spec: setattr(clock, "t", clock.t + ncg.BUDGET_SECONDS + 1)
    doc, code = rig.measure(runner, clock)
    assert codes_of(file_rec(doc)) == ["mutation_timeout"] and len(runner.calls) == 1


# --------------------------------------------------------------------------
# Workspace (AC-18, AC-19, R-H2b, A2a)
# --------------------------------------------------------------------------


def test_workspace_has_no_claude_at_any_depth(std):
    rig, runner = std
    assert "prompts/.claude/note.md" in rig.git("ls-files") and ".claude/settings.json" in rig.git(
        "ls-files"
    )
    found = {}

    def hook(phase, spec):
        if phase == "enumerate":
            tree = Path(spec.cwd)
            found["claude"] = [p for p in tree.rglob(".claude")]
            found["listing"] = sorted(p.name for p in tree.iterdir())
            found["mutants"] = (tree / "mutants").exists()

    runner.hook = hook
    doc, code = rig.measure(runner)
    assert code == 0 and found["claude"] == [] and found["mutants"] is False
    assert "README.md" in found["listing"] and "pyproject.toml" in found["listing"]
    assert "prompts" not in found["listing"] and ".claude" not in found["listing"]


def test_tracked_mutants_dir_exits_3(std):
    rig, runner = std
    rig.write("mutants/x.txt", "stale\n")
    rig.commit("tracked mutants")
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
    rig.sidecar()
    doc, code = rig.measure(runner)
    assert code == 3 and internal_messages(doc) == ["workspace contaminated: mutants"]
    assert runner.calls_for("enumerate") == []


def test_pragma_no_mutate_stripped_block_pragma_on_unchanged_line_does_not_shield(rig):
    rig.base()
    rig.write(
        "scripts/framework/shield.py",
        "# pragma: no mutate block\ndef f(x):\n    return x + 1  # pragma: no mutate\n",
    )
    rig.commit("shield")
    rig.coverage({"scripts/framework/shield.py": {"tests/test_s.py::t|run": [2, 3]}})
    rig.sidecar()
    seen = {}

    def hook(phase, spec):
        if phase == "enumerate":
            seen["text"] = (Path(spec.cwd) / "scripts/framework/shield.py").read_text()

    runner = FakeRunner(rig)
    runner.hook = hook
    rig.measure(runner)
    assert seen["text"] == "\ndef f(x):\n    return x + 1  \n"
    assert "no mutate" not in seen["text"]


def test_generated_config_selection_equals_selection(std):
    rig, runner = std
    config = {}

    def hook(phase, spec):
        if phase == "enumerate":
            config.update(tomllib.loads((Path(spec.cwd) / "pyproject.toml").read_text()))

    runner.hook = hook
    rig.measure(runner)
    mutmut = config["tool"]["mutmut"]
    assert mutmut["pytest_add_cli_args_test_selection"] == [TEST_CALC_ID]
    assert mutmut["only_mutate"] == [CALC_PATH] and mutmut["source_paths"] == ["scripts/"]
    assert mutmut["pytest_add_cli_args"] == ncg.generated_pytest_args()
    assert config["tool"]["pytest"]["ini_options"]["addopts"] == "-q"
    assert ".claude/" not in mutmut["also_copy"] and "README.md" in mutmut["also_copy"]
    assert mutmut["also_copy"] == ["README.md"]


# --------------------------------------------------------------------------
# Decision logic through measure (R-NQ1, R-NQ2, Q5-RUN, Q5-NQ1)
# --------------------------------------------------------------------------

TOP = "def f(x):\n    return x\n"


def decision_rig(rig, text, tests=True, contexts=None, name="scripts/framework/d.py"):
    rig.base()
    rig.write(name, text)
    if tests:
        rig.write("tests/test_d.py", "def test_d():\n    pass\n")
    rig.commit("d")
    lines = sorted(ncg.statement_map(text)[0])
    rig.coverage(
        {
            name: contexts if contexts is not None else {"tests/test_d.py::test_d|run": lines},
            "x.py": {"tests/t.py::t|run": [1]},
        }
    )
    rig.sidecar()
    runner = FakeRunner(rig)
    return name, runner


def test_module_level_logic_fails_file_with_mutants_and_selection(rig):
    text = "VALUE = 1 if __debug__ else 2\n\n\ndef f(x):\n    return x + 1\n"
    name, runner = decision_rig(rig, text)
    runner.mutants(name, killed=3, survived=0)
    doc, code = rig.measure(runner)
    rec = file_rec(doc, name)
    assert codes_of(rec) == ["module_level_decision_logic"] and code == 0
    assert (
        rec["mutation_ran"],
        rec["mutants_total"],
        rec["mutants_killed"],
        rec["mutant_score_pct"],
    ) == (
        True,
        3,
        3,
        100.0,
    )
    assert rec["fail_reasons"][0]["message"] == (
        f"module-level decision logic at {name}:1 — move the logic into a function so it can be mutated"
    )
    assert [f["construct"] for f in rec["decision_logic_findings"]] == ["IfExp"]
    assert verdict_of(doc)[2] == 1


def test_decorated_function_decision_logic_fails_undecorated_helper(rig):
    text = "import functools\n\n\n@functools.cache\ndef f(x):\n    if x:\n        return 1\n    return 2\n"
    name, runner = decision_rig(rig, text)
    runner.mutants(name, killed=0, survived=0)
    rec = file_rec(rig.measure(runner)[0], name)
    assert codes_of(rec) == ["unmutatable_decision_logic"]
    assert "undecorated helper" in rec["fail_reasons"][0]["message"]
    assert ("decorated_function", True) in [
        (u["reason"], u["has_decision_logic"]) for u in rec["unmutatable_gated_lines"]
    ]


def test_decorated_function_without_logic_reported_only(rig):
    text = "import functools\n\n\n@functools.cache\ndef f(x):\n    return x\n"
    name, runner = decision_rig(rig, text)
    runner.mutants(name, killed=0, survived=0)
    rec = file_rec(rig.measure(runner)[0], name)
    assert codes_of(rec) == []
    assert rec["unmutatable_gated_lines"] and not any(
        u["has_decision_logic"] for u in rec["unmutatable_gated_lines"]
    )


def test_zero_mutant_empty_selection_no_logic_passes(rig):
    name, runner = decision_rig(rig, "X = 1\nY = 2\n", tests=False, contexts={"": [1, 2]})
    runner.hook = None
    doc, code = rig.measure(runner)
    rec = file_rec(doc, name)
    assert codes_of(rec) == [] and rec["selection_method"] == "not_required_zero_mutants"
    assert (rec["mutation_ran"], rec["mutants_total"], rec["selected_tests"]) == (True, 0, [])
    assert verdict_codes(doc, name) == []


def test_zero_mutant_empty_selection_with_logic_fails_move_into_function(rig):
    name, runner = decision_rig(rig, "X = 1 if __debug__ else 2\n", tests=False, contexts={"": [1]})
    rec = file_rec(rig.measure(runner)[0], name)
    assert codes_of(rec) == ["zero_mutant_decision_logic", "module_level_decision_logic"]
    assert rec["fail_reasons"][0]["message"] == (
        f"decision logic at {name}:1 — move logic into a function so it can be mutated"
    )
    assert rec["mutation_ran"] is True and rec["selection_method"] == "none"


NQ1_IMPORT = "try:\n    import tomllib\nexcept ImportError:\n    tomllib = None\n"
NQ1_PLAIN = "".join(f"V{i} = {i}\n" for i in range(12))
NQ1_NAME = "scripts/framework/pkg/__init__.py"


def nq1_case(rig, text, skip_text=None, executed=None):
    """A new zero-mutant file, imported but never selected, with one carved line never run."""
    statements = sorted(ncg.statement_map(text)[0])
    if executed is None:
        skipped = [text.splitlines().index(skip_text) + 1] if skip_text else []
        executed = [n for n in statements if n not in skipped]
    rig.base()
    rig.write(NQ1_NAME, text)
    rig.commit("nq1")
    rig.coverage({NQ1_NAME: {"": executed}, "x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    return NQ1_NAME


@pytest.mark.parametrize(
    "text,skip_text,carved",
    [
        (NQ1_IMPORT + NQ1_PLAIN, "    tomllib = None", {"import_fallback"}),
        (
            "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from os import path\n"
            + NQ1_PLAIN,
            "    from os import path",
            {"type_checking"},
        ),
        (
            "from os import sep\n\n"
            + NQ1_PLAIN
            + 'if __name__ == "__main__":\n    sys.exit(main())\n',
            "    sys.exit(main())",
            {"main_guard"},
        ),
        (
            "from os import sep\n\n"
            + NQ1_PLAIN
            + 'if __name__ == "__main__":\n    raise SystemExit(main())\n',
            "    raise SystemExit(main())",
            {"main_guard"},
        ),
        ("X = 1\n", None, set()),
    ],
    ids=["import-fallback", "type-checking", "main-guard-sys-exit", "main-guard-raise", "plain"],
)
def test_nq1_applies_carve_outs(rig, text, skip_text, carved):
    name = nq1_case(rig, text, skip_text)
    doc, _ = rig.measure()
    rec = file_rec(doc, name)
    assert codes_of(rec) == []
    assert rec["selection_method"] == "not_required_zero_mutants"
    assert (rec["mutation_ran"], rec["mutants_total"], rec["selected_tests"]) == (True, 0, [])
    assert {f["carve_out"] for f in rec["decision_logic_findings"] if f["carve_out"]} == carved
    assert all(f["carve_out"] for f in rec["decision_logic_findings"])
    assert verdict_codes(doc, name) == []


def test_nq1_carved_file_still_fails_coverage_not_decision_logic(rig):
    statements = sorted(ncg.statement_map(NQ1_IMPORT)[0])
    name = nq1_case(rig, NQ1_IMPORT, executed=statements[:2])
    doc, _ = rig.measure()
    rec = file_rec(doc, name)
    assert (
        codes_of(rec) == []
        and rec["executed_gated"] == 2
        and rec["gated_statements"] == len(statements)
    )
    assert verdict_codes(doc, name) == ["coverage_below_threshold"]


def test_nq1_uncarved_logic_beside_a_carved_try_names_only_the_uncarved_line(rig):
    text = NQ1_IMPORT + NQ1_PLAIN + "if __debug__:\n    pass\n"
    name = nq1_case(rig, text, "    tomllib = None")
    rec = file_rec(rig.measure()[0], name)
    assert codes_of(rec) == ["zero_mutant_decision_logic", "module_level_decision_logic"]
    for reason in rec["fail_reasons"]:
        assert reason["message"].split(f"{name}:")[1].startswith("17 ")


def test_nq1_near_miss_is_not_carved(rig):
    text = "try:\n    import x\nexcept ModuleNotFoundError:\n    x = None\n"
    name = nq1_case(rig, text)
    rec = file_rec(rig.measure()[0], name)
    assert codes_of(rec) == ["zero_mutant_decision_logic", "module_level_decision_logic"]


def test_logic_free_is_computed_from_uncarved_findings_never_from_nothing(rig):
    text = NQ1_IMPORT + NQ1_PLAIN
    name = nq1_case(rig, text, "    tomllib = None")
    rec = file_rec(rig.measure()[0], name)
    assert rec["decision_logic_findings"] and codes_of(rec) == []


# --------------------------------------------------------------------------
# Shell (AC-8, AC-9, R-H4a)
# --------------------------------------------------------------------------


SHELL_LOGIC = 'if [ -z "$1" ]; then\n  echo a\nelse\n  echo b\nfi\n'


def shell_lines(text):
    return ncg.format_lines(decision_lines(text.splitlines()))


def test_shell_new_file_if_else_fails_and_hos_bootstrap_is_exempt(rig):
    rig.base()
    rig.write("scripts/run_it.sh", SHELL_LOGIC)
    rig.write("bootstrap/hos_bootstrap.sh", SHELL_LOGIC)
    rig.write("scripts/guard.sh", 'if [ -z "$1" ]; then\n  exit 1\nfi\n')
    rig.commit("shell")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    runner = FakeRunner(rig)
    doc, code = rig.measure(runner)
    assert code == 0 and runner.calls == []
    names = ("scripts/run_it.sh", "bootstrap/hos_bootstrap.sh", "scripts/guard.sh")
    run_it, boot, guard = (file_rec(doc, p) for p in names)
    assert codes_of(run_it) == ["shell_decision_logic"] and run_it["kind"] == "shell"
    assert run_it["fail_reasons"][0]["message"] == (
        f"shell decision logic at scripts/run_it.sh:{shell_lines(SHELL_LOGIC)} — move decision logic into "
        "tested Python (recommended home: scripts/automation/lib)"
    )
    assert boot["shell"] == {"exempt": "hos_bootstrap"} and codes_of(boot) == []
    assert guard["shell"]["head_count"] == 0 and codes_of(guard) == []
    assert run_it["mutation_reason"] == "not_python" and run_it["blob_sha"]


def test_shell_changed_file_counts_added_logic_only(rig):
    rig.base(extra={"scripts/t.sh": "echo start\n" + SHELL_LOGIC})
    rig.write("scripts/t.sh", "echo start\n" + SHELL_LOGIC + "echo end\n")
    rig.commit("untouched logic")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    rec = file_rec(rig.measure()[0], "scripts/t.sh")
    assert codes_of(rec) == [] and rec["shell"]["head_count"] == rec["shell"]["base_count"] > 0
    added = "echo start\n" + SHELL_LOGIC + 'case "$2" in\n  a) echo c;;\nesac\n'
    rig.write("scripts/t.sh", added)
    rig.commit("added case")
    rig.sidecar()
    rec = file_rec(rig.measure()[0], "scripts/t.sh")
    assert codes_of(rec) == ["shell_decision_logic"]
    assert rec["shell"]["head_count"] == len(decision_lines(added.splitlines()))


def test_shell_renamed_file_uses_the_old_path_as_base(rig):
    rig.base(extra={"scripts/old.sh": SHELL_LOGIC})
    rig.git("mv", "scripts/old.sh", "scripts/new.sh")
    rig.commit("rename")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    assert rig.measure()[0]["files"] == []
    rig.write("scripts/new.sh", SHELL_LOGIC + "# note\n")
    rig.commit("edit")
    rig.sidecar()
    rec = file_rec(rig.measure()[0], "scripts/new.sh")
    assert rec["shell"]["base_count"] == rec["shell"]["head_count"] > 0 and codes_of(rec) == []


# --------------------------------------------------------------------------
# The diff the gate reads is attacker-shaped input: F1 to F4, R100 and scope
# --------------------------------------------------------------------------


def edit_case(rig, path, before, after, base_extra=None):
    """A base commit holding `path` as `before`, then a feature commit that makes it `after`."""
    rig.base(extra={path: before, **(base_extra or {})})
    rig.write(path, after)
    rig.commit("edit")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    return rig.measure()[0]


FORGED_HEADER_DOC = 'doc = """\n++ b/scripts/framework/victim.py\n"""\n'


def test_a_content_line_that_forges_a_file_header_cannot_hide_later_hunks(rig):
    """F1: `++ b/victim.py` added as content reads as a `+++ ` header and retargets later hunks."""
    after = FORGED_HEADER_DOC + lines_text(8, start=2) + "a10 = 999\n" + lines_text(10, start=11)
    doc = edit_case(
        rig,
        "scripts/framework/a.py",
        lines_text(20),
        after,
        base_extra={"scripts/framework/victim.py": lines_text(5)},
    )
    assert [f["path"] for f in doc["files"]] == ["scripts/framework/a.py"]
    assert file_rec(doc, "scripts/framework/a.py")["gated_lines"] == [1, 12]


@pytest.mark.parametrize(
    "name",
    ["my file.py", "w[1].py", "tab\tname.py", "café  .py"],
    ids=["space", "glob", "tab", "unicode"],
)
def test_paths_with_spaces_globs_and_tabs_are_gated_by_their_own_diff(rig, name):
    """F3: a path with a space gets a trailing TAB on its `+++` line; a glob must stay literal."""
    path = f"scripts/framework/{name}"
    doc = edit_case(rig, path, lines_text(5), lines_text(1) + "a2 = 99\n" + lines_text(3, start=3))
    assert file_rec(doc, path)["gated_lines"] == [2]


def test_a_shell_file_with_a_space_in_its_name_is_checked_on_its_edited_lines(rig):
    """F3: the old header lookup lost the changed lines, so an edited condition passed unseen."""
    path = "scripts/my script.sh"
    rec = file_rec(edit_case(rig, path, SHELL_LOGIC, SHELL_LOGIC.replace("-z", "-n")), path)
    assert codes_of(rec) == ["shell_decision_logic"]
    assert rec["shell"]["counted_on_changed_lines"] == [1]


def test_gitattributes_binary_and_noprefix_config_cannot_blank_the_diff(rig):
    """F2: `-diff` yields 'Binary files differ' with no hunks; `diff.noprefix` drops the `b/`."""
    rig.git("config", "diff.noprefix", "true")
    rig.git("config", "diff.mnemonicPrefix", "true")
    path = "scripts/framework/b.py"
    doc = edit_case(
        rig,
        path,
        lines_text(10),
        lines_text(2) + "a3 = 99\n" + lines_text(3, start=4) + "a7 = 77\n" + lines_text(3, start=8),
        base_extra={".gitattributes": "*.py -diff\n"},
    )
    assert file_rec(doc, path)["gated_lines"] == [3, 7]


def test_a_changed_file_whose_diff_has_no_hunks_fails_closed(rig, monkeypatch):
    """F1: changed content with no hunk must not read as 'nothing changed'."""
    real = gate.git_text

    def blank_patch(repo, args, fail=None):
        return "" if "--unified=0" in args else real(repo, args, fail)

    monkeypatch.setattr(gate, "git_text", blank_patch)
    path = "scripts/framework/c.py"
    doc = edit_case(rig, path, lines_text(5), lines_text(2) + "a3 = 99\n" + lines_text(2, start=4))
    assert doc["files"] == []
    assert internal_messages(doc) == [f"diff for {path} changed content but produced no hunks"]


def test_a_mode_only_change_keeps_the_blob_and_gates_nothing(rig):
    rig.base(extra={"scripts/framework/m.py": lines_text(3)})
    (rig.root / "scripts/framework/m.py").chmod(0o755)
    rig.git("add", "-A")
    rig.git("commit", "-q", "-m", "mode")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    doc, code = rig.measure()
    assert code == 0 and file_rec(doc, "scripts/framework/m.py")["gated_lines"] == []


def test_a_form_feed_in_a_shell_file_does_not_shift_the_checked_line(rig):
    """F4: `str.splitlines` counts form feed as a line break, git does not."""
    path = "scripts/ff.sh"
    before = "# a\x0cb\n" + SHELL_LOGIC
    rec = file_rec(edit_case(rig, path, before, before.replace("-z", "-n")), path)
    assert codes_of(rec) == ["shell_decision_logic"]
    assert rec["shell"]["counted_on_changed_lines"] == [2]


def test_rename_from_a_test_into_production_is_a_new_gated_file(rig):
    """R100: a pure rename from outside the gated scope has no gated history."""
    rig.base(extra={"tests/test_moved.py": CALC})
    rig.git("mv", "tests/test_moved.py", "scripts/framework/moved.py")
    rig.commit("move into production")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    rec = file_rec(rig.measure()[0], "scripts/framework/moved.py")
    assert rec["kind"] == "new" and rec["gated_lines"] == CALC_LINES


def test_rename_from_text_into_a_shell_script_is_a_new_shell_file(rig):
    rig.base(extra={"docs/notes.txt": SHELL_LOGIC})
    rig.git("mv", "docs/notes.txt", "scripts/notes.sh")
    rig.commit("text becomes shell")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    rec = file_rec(rig.measure()[0], "scripts/notes.sh")
    assert codes_of(rec) == ["shell_decision_logic"] and rec["shell"]["base_count"] == 0


def test_a_same_scope_rename_is_still_not_gated(rig):
    rig.base(extra={"scripts/framework/old.py": CALC})
    rig.git("mv", "scripts/framework/old.py", "scripts/framework/renamed.py")
    rig.commit("rename")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    assert rig.measure()[0]["files"] == []


@pytest.mark.parametrize("folder", ["venv", ".venv", "site-packages"])
def test_production_code_under_a_directory_named_like_an_environment_is_gated(rig, folder):
    rig.base()
    path = f"scripts/framework/{folder}/hidden.py"
    rig.write(path, "a = 1\n")
    rig.commit("hidden")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    assert file_rec(rig.measure()[0], path)["kind"] == "new"


# --------------------------------------------------------------------------
# Workspace extraction and test selection (should-fix)
# --------------------------------------------------------------------------


def archive_case(rig, attributes, calc=CALC):
    rig.base()
    rig.write(CALC_PATH, calc)
    rig.write("tests/test_calc.py", TEST_CALC)
    rig.write(".gitattributes", attributes)
    rig.commit("feature")
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
    rig.sidecar()
    runner = FakeRunner(rig)
    runner.mutants(CALC_PATH, killed=4, survived=0)
    return rig.measure(runner)


def test_export_subst_rewriting_the_gated_file_in_the_archive_is_refused(rig):
    calc = "def add(a, b):\n    return a + b  # $Format:%H$\n\n\ndef sub(a, b):\n    return a - b\n"
    doc, code = archive_case(rig, f"{CALC_PATH} export-subst\n", calc=calc)
    assert code == 3
    assert internal_messages(doc) == [
        f"extracted workspace differs from the gated commit: {CALC_PATH}"
    ]
    assert list(rig.work.iterdir()) == []


def test_export_ignore_dropping_a_selected_test_from_the_archive_is_refused(rig):
    doc, code = archive_case(rig, "tests/test_calc.py export-ignore\n")
    assert code == 3
    assert internal_messages(doc) == ["could not hash the extracted workspace"]


def test_an_untouched_archive_matches_every_blob(rig):
    doc, code = archive_case(rig, "*.md text\n")
    assert code == 0 and file_rec(doc)["mutation_ran"] is True


@pytest.mark.parametrize(
    "context",
    ["--rootdir=/x", "-p evil", "tests/../../x.py::t", "scripts/calc.py::t"],
    ids=argv_safe_id,
)
def test_a_coverage_context_that_is_a_pytest_option_is_refused_before_pytest_runs(std, context):
    """A PR's tests write the coverage contexts, so an ID is untrusted argv."""
    rig, runner = std
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES, context + "|run": [1]}})
    doc, code = rig.measure(runner)
    assert code == 3
    assert "unsafe test id in coverage contexts" in internal_messages(doc)[0]
    assert runner.calls_for("repo_copy_collect") == [] and runner.calls_for("mutmut_run") == []
    assert file_rec(doc)["mutation_reason"] == "internal_error"


def test_a_parametrized_id_with_spaces_widens_to_its_module(std):
    rig, runner = std
    rig.coverage({CALC_PATH: {"tests/test_calc.py::test_add[a b]|run": CALC_LINES}})
    doc, _ = rig.measure(runner)
    assert file_rec(doc)["selected_tests"] == ["tests/test_calc.py"]
    assert runner.calls_for("repo_copy_collect")[0].argv[-2:] == ["--", "tests/test_calc.py"]


def test_one_unsafe_file_does_not_stop_the_other_files(rig):
    runner = two_file_rig(rig)
    rig.coverage(
        {
            CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES},
            "scripts/framework/other.py": {"-x|run": CALC_LINES},
        }
    )
    doc, code = rig.measure(runner)
    assert code == 3 and [e["file"] for e in doc["internal_errors"]] == [
        "scripts/framework/other.py"
    ]
    assert file_rec(doc)["mutation_ran"] is True


# --------------------------------------------------------------------------
# AR-1: CI mode on a real merge commit
# --------------------------------------------------------------------------


def merge_rig(rig, base_side_edit=True):
    rig.base(extra={"scripts/framework/m.py": lines_text(6)})
    rig.write("scripts/framework/m.py", lines_text(1, offset=100) + lines_text(5, start=2))
    pr_head = rig.commit("pr edits line 1")
    rig.git("checkout", "-q", "main")
    if base_side_edit:
        rig.write("scripts/framework/m.py", lines_text(5) + "a6 = 600\n")
        rig.commit("base edits line 6")
    rig.git("merge", "-q", "--no-ff", "-m", "merge", "feature")
    return pr_head


def ci_opts(rig, pr_head, **override):
    values = {"mode": "ci", "base_ref": None, "pr_head_sha": pr_head, "pr": 7}
    values.update(run_id="1", run_attempt="2")
    values.update(override)
    return rig.options(**values)


def test_ci_mode_gates_merge_commit_base_is_first_parent(rig):
    pr_head = merge_rig(rig)
    rig.coverage({"scripts/framework/m.py": {"tests/test_m.py::t|run": [1, 2, 3, 4, 5, 6]}})
    rig.sidecar(run_id="1")
    doc, code = gate.measure(ci_opts(rig, pr_head), FakeRunner(rig), FakeClock())
    rec = file_rec(doc, "scripts/framework/m.py")
    assert code == 0 and rec["gated_lines"] == [1]
    assert doc["base_sha"] == rig.git("rev-parse", "HEAD^1") and doc["gated_sha"] == rig.head()
    assert (doc["pr"], doc["run_id"], doc["run_attempt"], doc["pr_head_sha"]) == (
        7,
        "1",
        "2",
        pr_head,
    )
    assert doc["mode"] == "ci"


def test_ci_mode_second_parent_must_equal_pr_head(rig):
    pr_head = merge_rig(rig)
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    rig.sidecar(run_id="1")
    doc, code = gate.measure(ci_opts(rig, "0" * 40), FakeRunner(rig), FakeClock())
    assert code == 3 and internal_messages(doc) == ["merge commit does not contain the PR head"]
    rig.git("checkout", "-q", "-B", "linear", "feature")
    rig.sidecar(run_id="1")
    doc, code = gate.measure(ci_opts(rig, rig.head()), FakeRunner(rig), FakeClock())
    assert code == 3 and internal_messages(doc) == ["merge commit does not contain the PR head"]
    assert pr_head


def test_blob_sha_from_gated_tree_pr_head_blob_alongside(rig):
    pr_head = merge_rig(rig)
    rig.coverage({"scripts/framework/m.py": {"tests/test_m.py::t|run": [1]}})
    rig.sidecar(run_id="1")
    rec = file_rec(
        gate.measure(ci_opts(rig, pr_head), FakeRunner(rig), FakeClock())[0],
        "scripts/framework/m.py",
    )
    assert rec["blob_sha"] == rig.git("rev-parse", "HEAD:scripts/framework/m.py")
    assert rec["pr_head_blob_sha"] == rig.git("rev-parse", f"{pr_head}:scripts/framework/m.py")
    assert rec["blob_sha"] != rec["pr_head_blob_sha"]


def test_blob_sha_equals_pr_head_blob_when_base_did_not_touch_the_file(rig):
    pr_head = merge_rig(rig, base_side_edit=False)
    rig.coverage({"scripts/framework/m.py": {"tests/test_m.py::t|run": [1]}})
    rig.sidecar(run_id="1")
    rec = file_rec(
        gate.measure(ci_opts(rig, pr_head), FakeRunner(rig), FakeClock())[0],
        "scripts/framework/m.py",
    )
    assert rec["blob_sha"] == rec["pr_head_blob_sha"]


def test_pr_head_blob_is_null_when_the_path_is_absent_there(std):
    rig, _ = std
    base = rig.git("rev-parse", "main")
    ctx = gate.Context(rig.options(pr_head_sha=base), FakeRunner(rig), FakeClock())
    assert gate.blob_shas(ctx, CALC_PATH) == (rig.git("rev-parse", f"HEAD:{CALC_PATH}"), None)
    assert gate.blob_shas(ctx, "README.md")[1] == gate.blob_shas(ctx, "README.md")[0]


# --------------------------------------------------------------------------
# BIND-5: the sidecar belongs to this run; inputs are regular files (RV-7)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("sidecar_run", [None, "2", ""], ids=["no-run-id", "other-run", "empty"])
def test_bind5_a_sidecar_from_another_run_exits_3_in_ci(rig, sidecar_run):
    pr_head = merge_rig(rig)
    rig.coverage({"scripts/framework/m.py": {"tests/test_m.py::t|run": [1]}})
    rig.sidecar(run_id=sidecar_run)
    runner = FakeRunner(rig)
    doc, code = gate.measure(ci_opts(rig, pr_head), runner, FakeClock())
    assert code == 3 and runner.calls == [] and doc["files"] == []
    (message,) = internal_messages(doc)
    assert message.startswith("coverage data stale or from a dirty tree: run: sidecar was written")
    assert message.endswith(f"written by run {sidecar_run}, this is run 1")


def test_bind5_a_ci_measure_with_no_run_id_never_matches_a_sidecar(rig):
    pr_head = merge_rig(rig)
    rig.coverage({"scripts/framework/m.py": {"tests/test_m.py::t|run": [1]}})
    rig.sidecar(run_id=None)
    doc, code = gate.measure(ci_opts(rig, pr_head, run_id=None), FakeRunner(rig), FakeClock())
    assert code == 3 and "run: sidecar was written by run None, this is run " in str(
        internal_messages(doc)
    )


def test_bind5_local_mode_ignores_the_sidecar_run_id(std):
    rig, runner = std
    rig.sidecar(run_id="77")
    assert rig.measure(runner)[1] == 0


@pytest.mark.parametrize("which", ["coverage", "meta"])
def test_the_coverage_inputs_must_be_regular_files_not_symlinks(std, which):
    rig, runner = std
    real = rig.tmp / (".coverage" if which == "coverage" else "coverage-meta.json")
    moved = rig.tmp / "elsewhere"
    real.rename(moved)
    real.symlink_to(moved)
    doc, code = rig.measure(runner)
    assert code == 3 and internal_messages(doc) == ["coverage data missing contexts"]
    assert runner.calls == []


def test_a_coverage_input_that_is_a_directory_is_refused(std):
    rig, runner = std
    (rig.tmp / ".coverage").unlink()
    (rig.tmp / ".coverage").mkdir()
    doc, code = rig.measure(runner)
    assert code == 3 and internal_messages(doc) == ["coverage data missing contexts"]


# --------------------------------------------------------------------------
# SYM-1 and SYM-2: a gated symlink fails closed before any blob is parsed (RV-2)
# --------------------------------------------------------------------------


def symlink_pr(rig, rel, target, base_files=None):
    """A feature commit that adds `rel` as a git symlink (mode 120000) to `target`."""
    rig.base(extra=base_files)
    path = rig.root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)
    rig.commit("symlink")
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
    rig.sidecar()


def parsed_nothing(monkeypatch):
    """Fail the test if anything parses source: the link-target text is never source."""

    def refuse(*args, **kwargs):
        raise AssertionError("a symlink's content was parsed")

    monkeypatch.setattr(ncg, "statement_map", refuse)
    monkeypatch.setattr(gate, "blob_text", refuse)


@pytest.mark.parametrize(
    ("rel", "kind"),
    [("scripts/framework/link.py", "new"), ("scripts/framework/link.sh", "shell")],
)
def test_sym1_a_symlink_in_python_or_shell_scope_fails_closed_without_parsing(
    rig, monkeypatch, rel, kind
):
    symlink_pr(rig, rel, "../../README.md")
    assert rig.git("ls-tree", "HEAD", rel).startswith("120000 ")
    parsed_nothing(monkeypatch)
    runner = FakeRunner(rig)
    doc, code = rig.measure(runner)
    assert code == 0 and runner.calls == []
    rec = file_rec(doc, rel)
    assert rec["kind"] == kind and rec["mutation_reason"] == "blocked_by:symlink_not_gateable"
    assert rec["fail_reasons"] == [{"code": "symlink_not_gateable", "message": ncg.MSG_SYMLINK}]
    assert rec["gated_statements"] == 0 and rec["mutation_ran"] is False
    assert rec["blob_sha"] == rig.git("rev-parse", f"HEAD:{rel}")
    vdoc, summary, vcode = gate.build_verdict(doc, None)
    assert vcode == 1 and vdoc["files"][0]["outcome"] == "fail"
    assert "symlink_not_gateable" in summary


def test_sym1_a_symlink_to_python_source_is_not_read_as_source(rig):
    symlink_pr(rig, "scripts/framework/alias.py", "calc.py", base_files={CALC_PATH: CALC})
    doc, code = rig.measure(FakeRunner(rig))
    assert code == 0
    assert [f["path"] for f in doc["files"]] == ["scripts/framework/alias.py"]
    assert codes_of(file_rec(doc, "scripts/framework/alias.py")) == ["symlink_not_gateable"]


def test_sym1_regular_files_beside_a_symlink_are_still_measured(std):
    rig, runner = std
    rig.write("scripts/framework/other.sh", "echo hi\n")
    (rig.root / "scripts/framework/alias.py").symlink_to("calc.py")
    rig.commit("alias")
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
    rig.sidecar()
    doc, code = rig.measure(runner, base_ref="HEAD~1")
    assert [f["path"] for f in doc["files"]] == [
        "scripts/framework/alias.py",
        "scripts/framework/other.sh",
    ]
    assert codes_of(file_rec(doc, "scripts/framework/alias.py")) == ["symlink_not_gateable"]
    assert codes_of(file_rec(doc, "scripts/framework/other.sh")) == []


def test_sym2_a_type_change_from_a_regular_file_to_a_symlink_fails_closed(rig, monkeypatch):
    rel = "scripts/framework/m.py"
    rig.base(extra={rel: "a = 1\n"})
    (rig.root / rel).unlink()
    (rig.root / rel).symlink_to("../../README.md")
    rig.commit("now a link")
    assert rig.git("diff", "--name-status", "HEAD~1", "HEAD").startswith("T\t")
    rig.coverage({rel: {"tests/t.py::t|run": [1]}})
    rig.sidecar()
    parsed_nothing(monkeypatch)
    doc, code = rig.measure(FakeRunner(rig))
    rec = file_rec(doc, rel)
    assert (code, rec["kind"]) == (0, "changed")
    assert codes_of(rec) == ["symlink_not_gateable"]
    assert rec["mutation_reason"] == "blocked_by:symlink_not_gateable"


def test_sym2_a_symlink_turned_back_into_a_regular_file_is_gated_normally(rig):
    rel = "scripts/framework/m.py"
    rig.base()
    (rig.root / rel).parent.mkdir(parents=True, exist_ok=True)
    (rig.root / rel).symlink_to("../../README.md")
    rig.commit("link")
    (rig.root / rel).unlink()
    rig.write(rel, lines_text(3))
    rig.commit("regular")
    rig.coverage({rel: {"tests/t.py::t|run": [1, 2, 3]}})
    rig.sidecar()
    doc, code = rig.measure(FakeRunner(rig), base_ref="HEAD~1")
    rec = file_rec(doc, rel)
    assert code == 0 and codes_of(rec) != ["symlink_not_gateable"]
    assert rec["gated_statements"] == 3


def gitlink_pr(rig, rel):
    """A feature commit that adds `rel` as a gitlink (mode 160000, a submodule) with no content."""
    rig.base()
    commit = rig.head()
    rig.git("update-index", "--add", "--cacheinfo", f"160000,{commit},{rel}")
    rig.git("commit", "-q", "-m", "gitlink")
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
    rig.sidecar()
    return commit


@pytest.mark.parametrize(
    ("rel", "kind"),
    [("scripts/framework/sub.py", "new"), ("scripts/framework/sub.sh", "shell")],
)
def test_mode_1_a_gitlink_at_a_gated_path_fails_closed_without_a_blob_read(
    rig, monkeypatch, rel, kind
):
    commit = gitlink_pr(rig, rel)
    assert rig.git("ls-tree", "HEAD", rel).startswith("160000 ")
    parsed_nothing(monkeypatch)
    runner = FakeRunner(rig)
    doc, code = rig.measure(runner)
    assert code == 0 and runner.calls == []
    rec = file_rec(doc, rel)
    message = ncg.mode_message("160000")
    assert rec["kind"] == kind and rec["mutation_reason"] == "blocked_by:mode_not_gateable"
    assert rec["fail_reasons"] == [{"code": "mode_not_gateable", "message": message}]
    assert "(mode 160000, for example a submodule)" in message
    assert rec["gated_statements"] == 0 and rec["mutation_ran"] is False
    assert rec["blob_sha"] == commit
    vdoc, summary, vcode = gate.build_verdict(doc, None)
    assert vcode == 1 and vdoc["files"][0]["outcome"] == "fail"
    assert "mode_not_gateable" in summary


def test_mode_2_a_path_the_diff_reports_but_the_tree_listing_omits_is_exit_3(std, monkeypatch):
    rig, runner = std
    monkeypatch.setattr(gate, "tracked_modes", lambda repo, sha: {"README.md": "100644"})
    doc, code = rig.measure(runner)
    assert code == 3
    (error,) = doc["internal_errors"]
    assert error["message"] == f"tree listing and diff disagree: {CALC_PATH}"
    assert doc["files"] == []


def test_env_strip_drops_the_runner_file_command_variables_too():
    """ENV-STRIP (RV2-3): partial hardening; every child env is built by scrubbed_env."""
    names = ("GITHUB_ENV", "GITHUB_PATH", "GITHUB_OUTPUT", "GITHUB_STATE", "GITHUB_STEP_SUMMARY")
    env = {name: "/runner/file" for name in names}
    env.update(GITHUB_TOKEN="a", GH_TOKEN="b", ACTIONS_X="c", NCG_LOG="d", GITHUB_SHA="keep")
    assert gate.scrubbed_env(env) == {"GITHUB_SHA": "keep"}
    assert set(names) <= gate.STRIPPED_ENV_NAMES


def test_atomic_1_an_output_symlink_is_replaced_not_followed(tmp_path):
    """ATOMIC-1 (RV2-4c): a symlink at the destination never redirects the write."""
    victim = tmp_path / "victim.json"
    victim.write_text("untouched", encoding="utf-8")
    out = tmp_path / "out" / "nested" / "new-code-verdict.json"
    out.parent.mkdir(parents=True)
    out.symlink_to(victim)
    gate.write_json(out, {"a": 1})
    assert not out.is_symlink() and json.loads(out.read_text(encoding="utf-8")) == {"a": 1}
    assert victim.read_text(encoding="utf-8") == "untouched"
    summary = tmp_path / "fresh" / "dir" / "new-code-summary.md"
    gate.write_text_atomic(summary, "hello\n")
    assert summary.read_text(encoding="utf-8") == "hello\n"
    assert [p.name for p in out.parent.iterdir()] == [out.name]


def test_atomic_1_a_failed_write_leaves_no_temp_file_and_the_old_file(tmp_path, monkeypatch):
    out = tmp_path / "records.json"
    out.write_text("old", encoding="utf-8")

    def boom(src, dst):
        raise OSError("disk")

    monkeypatch.setattr(gate.os, "replace", boom)
    with pytest.raises(OSError, match="disk"):
        gate.write_json(out, {"a": 1})
    assert out.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["records.json"]


def test_a_tracked_symlink_that_a_pr_did_not_touch_is_not_gated(std):
    rig, runner = std
    (rig.root / "scripts/framework/old.py").symlink_to("calc.py")
    rig.commit("old link")
    rig.git("checkout", "-q", "-b", "next")
    rig.write("docs/n.md", "x\n")
    rig.commit("docs")
    rig.coverage({CALC_PATH: {TEST_CALC_ID + "|run": CALC_LINES}})
    rig.sidecar()
    doc, code = rig.measure(runner, base_ref="HEAD~1")
    assert code == 0 and doc["files"] == []


# --------------------------------------------------------------------------
# Guards: internal errors with a cause (AC-26, A7a, AC-21)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(ncg.PINNED))
def test_sidecar_tool_versions_and_python_must_equal_install(std, tool):
    rig, runner = std
    versions = dict(ncg.PINNED, **{tool: "0.0.1"})
    rig.sidecar(tool_versions=versions)
    doc, code = rig.measure(runner)
    assert code == 3
    assert internal_messages(doc) == [
        f"sidecar tool versions differ from measure environment: {tool} 0.0.1 != {ncg.PINNED[tool]}"
    ]
    assert doc["files"] == [] and runner.calls == []


def test_sidecar_python_mismatch_exits_3(std):
    rig, runner = std
    rig.sidecar(python="3.11")
    doc, code = rig.measure(runner)
    assert code == 3 and "python 3.11 != 3.12" in internal_messages(doc)[0]


def test_wrong_installed_pin_exits_3(std):
    rig, runner = std
    doc, code = rig.measure(runner, installed=dict(ncg.PINNED, mutmut="3.8.2"))
    assert code == 3 and internal_messages(doc) == ["tool version mismatch: mutmut 3.8.2 != 3.8.1"]


@pytest.mark.parametrize(
    "override,detail",
    [
        ({"head_sha": "f" * 40}, "head: sidecar describes " + "f" * 40),
        (
            {"clean": False, "dirty_paths": ["scripts/a.py", "b.sh"]},
            "clean: tracked .py/.sh files were modified (scripts/a.py, b.sh)",
        ),
        ({"coverage_core": "sysmon"}, "core: coverage_core is sysmon, not ctrace"),
    ],
    ids=["other-head", "dirty", "not-ctrace"],
)
def test_sidecar_head_mismatch_exits_3_and_names_the_failed_condition(std, override, detail):
    rig, runner = std
    rig.sidecar(**override)
    doc, code = rig.measure(runner)
    assert code == 3
    (message,) = internal_messages(doc)
    assert message.startswith("coverage data stale or from a dirty tree: " + detail)


@pytest.mark.parametrize("break_it", ["missing", "unreadable", "schema"])
def test_sidecar_problems_exit_3(std, break_it):
    rig, runner = std
    path = rig.tmp / "coverage-meta.json"
    if break_it == "missing":
        path.unlink()
    elif break_it == "unreadable":
        path.write_text("{", encoding="utf-8")
    else:
        rig.sidecar(schema="other/9")
    doc, code = rig.measure(runner)
    assert code == 3 and "coverage sidecar" in internal_messages(doc)[0]


@pytest.mark.parametrize("break_it", ["missing", "garbage", "no-contexts"])
def test_missing_coverage_data_exits_3(std, break_it):
    rig, runner = std
    path = rig.tmp / ".coverage"
    if break_it == "missing":
        path.unlink()
    elif break_it == "garbage":
        path.write_text("not a database", encoding="utf-8")
    else:
        rig.coverage({CALC_PATH: {"": CALC_LINES}})
    doc, code = rig.measure(runner)
    assert code == 3 and internal_messages(doc) == ["coverage data missing contexts"]


def test_diff_failure_exits_3(std):
    rig, runner = std
    doc, code = rig.measure(runner, base_ref="no-such-ref")
    assert code == 3 and internal_messages(doc) == ["diff could not be computed"]


def test_unknown_gated_sha_exits_3_without_crashing(std):
    rig, runner = std
    rig.sidecar(head_sha="e" * 40)
    doc, code = rig.measure(runner, gated_sha="e" * 40)
    assert code == 3 and doc["gated_tree"] is None


def test_upstream_tests_result_not_success_exits_3_with_records(std):
    rig, runner = std
    doc, code = rig.measure(runner, tests_result="failure")
    assert code == 3 and doc["internal_errors"] == [
        {"code": "upstream", "message": "upstream job not successful: failure"}
    ]
    assert doc["files"] == [] and runner.calls == []
    ok, code = rig.measure(FakeRunner(rig), tests_result="success")
    assert code == 0 and ok["files"]


def test_unexpected_exception_is_recorded_not_raised(std, monkeypatch):
    rig, runner = std
    monkeypatch.setattr(gate, "prepare_files", lambda ctx: 1 / 0)
    doc, code = rig.measure(runner)
    assert code == 3 and internal_messages(doc) == ["ZeroDivisionError: division by zero"]


def test_unexpected_exception_in_a_file_step_is_recorded_per_file(std, monkeypatch):
    rig, runner = std

    def boom(ctx, work):
        raise KeyError("x")

    monkeypatch.setattr(gate, "analyze_python", boom)
    doc, code = rig.measure(runner)
    assert code == 3 and doc["internal_errors"][0]["file"] == CALC_PATH
    assert file_rec(doc)["mutation_reason"] == "internal_error"


def test_env_label_flag_cannot_turn_fail_to_pass(rig, monkeypatch, capsys):
    two_hundred_line_pr(rig, covered_changed=10, covered_unchanged=0)
    (rig.root / "labels.txt").write_text("exception\n")
    for name in ("NCG_EXCEPTION", "HOS_EXCEPTION", "GITHUB_EVENT_LABELS"):
        monkeypatch.setenv(name, "1")
    doc, _ = rig.measure(
        environ={"TMPDIR": str(rig.work), "NCG_EXCEPTION": "1", "LABELS": "exception"}
    )
    rec = file_rec(doc, "scripts/framework/big.py")
    assert rec["exception"] is None and rec["exception_path"] == ncg.EXCEPTION_PATH_TEXT
    assert verdict_codes(doc, rec["path"]) == ["coverage_below_threshold"]
    with pytest.raises(SystemExit) as raised:
        gate.main([*verdict_argv(rig, doc), "--exception", "x"])
    assert raised.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


# --------------------------------------------------------------------------
# verdict, meta and the CLI
# --------------------------------------------------------------------------


RUN = {"run_id": "9", "run_attempt": "1"}
PR = 7


def ci_doc(rig, runner, **override):
    """Records as a CI `measure` writes them (mode ci, this PR), measured in process."""
    doc, _ = rig.measure(runner, **RUN)
    return dict(doc, **{"mode": "ci", "pr": PR, **override})


def write_records(rig, doc):
    """A fresh records directory holding the one artifact file; returns that file's path."""
    directory = rig.tmp / "records"
    directory.mkdir(exist_ok=True)
    path = directory / gate.RECORDS_FILENAME
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def verdict_inputs(rig, doc, **override):
    """Inputs for `verdict`; the records are staged unless a test already staged (or damaged) them."""
    staged = rig.tmp / "records"
    if not staged.exists():
        write_records(rig, doc)
    values = {
        "records_dir": staged,
        "gated_sha": rig.head(),
        "pr": PR,
        "run_id": "9",
        "run_attempt": 1,
        "measure_result": "success",
    }
    values.update(override)
    return gate.VerdictInputs(**values)


def verdict_argv(rig, doc, **override):
    inputs = verdict_inputs(rig, doc, **override)
    return [
        "verdict",
        "--records-dir",
        str(inputs.records_dir),
        "--gated-sha",
        inputs.gated_sha,
        "--pr",
        str(inputs.pr),
        "--run-id",
        inputs.run_id,
        "--run-attempt",
        str(inputs.run_attempt),
        "--measure-result",
        inputs.measure_result,
        "--out",
        str(rig.tmp / "v.json"),
        "--summary",
        str(rig.tmp / "s.md"),
    ]


def run_verdict(rig, inputs):
    out, summary = rig.tmp / "v.json", rig.tmp / "s.md"
    return gate.verdict(inputs, out, summary), out, summary


def test_verdict_writes_artifact_and_summary_and_exit_code(std):
    rig, runner = std
    doc = ci_doc(rig, runner)
    code, out, summary = run_verdict(rig, verdict_inputs(rig, doc))
    assert code == 0
    vdoc = json.loads(out.read_text())
    assert vdoc["phase"] == "verdict" and vdoc["overall"] == "pass" and vdoc["exit_code"] == 0
    assert vdoc["measure_records_sha256"] == doc["records_sha256"]
    assert vdoc["files"][0]["outcome"] == "pass" and f"| {CALC_PATH} | new |" in summary.read_text()


def test_verdict_upstream_not_success_exits_3_after_rendering(std):
    rig, runner = std
    doc = ci_doc(rig, runner)
    code, out, summary = run_verdict(rig, verdict_inputs(rig, doc, measure_result="cancelled"))
    assert code == 3
    assert "upstream job not successful: cancelled" in summary.read_text()
    assert json.loads(out.read_text())["files"][0]["path"] == CALC_PATH


def test_verdict_with_an_empty_measure_result_is_not_success(std):
    rig, runner = std
    doc = ci_doc(rig, runner)
    assert run_verdict(rig, verdict_inputs(rig, doc, measure_result=""))[0] == 3


@pytest.mark.parametrize("damage", ["missing", "garbage", "schema", "sha"])
def test_verdict_with_bad_records_exits_3_and_still_writes_files(std, damage):
    rig, runner = std
    doc = ci_doc(rig, runner)
    records = write_records(rig, doc)
    if damage == "missing":
        records.unlink()
    elif damage == "garbage":
        records.write_text("[", encoding="utf-8")
    elif damage == "schema":
        records.write_text(json.dumps(dict(doc, schema="x")), encoding="utf-8")
    else:
        doc["files"][0]["executed_gated"] = 0
        records.write_text(json.dumps(doc), encoding="utf-8")
    code, out, summary = run_verdict(rig, verdict_inputs(rig, doc))
    assert code == 3
    assert json.loads(out.read_text())["overall"] == "fail"
    assert "Internal errors:" in summary.read_text()


def test_verdict_of_measure_with_internal_error_is_exit_3(std):
    rig, runner = std
    doc, code = rig.measure(runner, tests_result="failure", **RUN)
    assert run_verdict(rig, verdict_inputs(rig, dict(doc, mode="ci", pr=PR)))[0] == 3


BIND_MESSAGE = "records not bound to this run: "


@pytest.mark.parametrize(
    "override,detail",
    [
        ({"gated_sha": "d" * 40}, "gated_sha is "),
        ({"pr": 8}, "pr is 7, expected 8"),
        ({"run_id": "10"}, "run_id is 9, expected 10"),
    ],
    ids=["other-sha", "other-pr", "other-run"],
)
def test_bind1_to_3_verdict_refuses_records_from_another_commit_pr_or_run(std, override, detail):
    """BIND-1..3 (F5, RV-7): a stale or foreign records artifact must not pass this run's verdict."""
    rig, runner = std
    doc = ci_doc(rig, runner)
    code, out, summary = run_verdict(rig, verdict_inputs(rig, doc, **override))
    assert code == 3
    vdoc = json.loads(out.read_text())
    assert vdoc["overall"] == "fail" and vdoc["files"] == []
    message = vdoc["internal_errors"][0]["message"]
    assert message.startswith(BIND_MESSAGE) and detail in message
    assert BIND_MESSAGE in summary.read_text()


def test_bind4_a_later_attempt_is_refused_and_an_equal_or_earlier_one_is_accepted(std):
    rig, runner = std
    doc = ci_doc(rig, runner, run_attempt="3")
    code, out, _ = run_verdict(rig, verdict_inputs(rig, doc, run_attempt=2))
    assert code == 3
    message = json.loads(out.read_text())["internal_errors"][0]["message"]
    assert message == BIND_MESSAGE + "run_attempt is 3, expected an integer of at most 2"
    for attempt in (3, 4):
        assert run_verdict(rig, verdict_inputs(rig, doc, run_attempt=attempt))[0] == 0
    write_records(rig, ci_doc(rig, runner, run_attempt="1"))
    assert run_verdict(rig, verdict_inputs(rig, doc, run_attempt=5))[0] == 0
    write_records(rig, ci_doc(rig, runner, run_attempt=1))
    assert run_verdict(rig, verdict_inputs(rig, doc, run_attempt=1))[0] == 0
    write_records(rig, ci_doc(rig, runner, run_attempt="x"))
    assert run_verdict(rig, verdict_inputs(rig, doc, run_attempt=1))[0] == 3


def test_bind4_a_verdict_only_rerun_reads_the_first_attempts_records(std):
    """RV-7: re-running only `new-code-gate` (attempt 2) must judge the attempt-1 records."""
    rig, runner = std
    doc = ci_doc(rig, runner)
    assert doc["run_attempt"] == "1"
    argv = verdict_argv(rig, doc, run_attempt=2)
    assert argv[argv.index("--run-attempt") + 1] == "2" and gate.main(argv) == 0


def test_bind4_records_that_are_not_ci_records_are_refused(std):
    rig, runner = std
    doc = ci_doc(rig, runner, mode="local")
    code, out, _ = run_verdict(rig, verdict_inputs(rig, doc))
    assert code == 3
    assert (
        json.loads(out.read_text())["internal_errors"][0]["message"]
        == BIND_MESSAGE + "mode is local, expected ci"
    )


def test_bind4_a_records_file_that_is_a_symlink_is_refused(std):
    rig, runner = std
    doc = ci_doc(rig, runner)
    real = rig.tmp / "real-records"
    real.mkdir()
    (real / gate.RECORDS_FILENAME).write_text(json.dumps(doc), encoding="utf-8")
    linked = rig.tmp / "linked"
    linked.mkdir()
    (linked / gate.RECORDS_FILENAME).symlink_to(real / gate.RECORDS_FILENAME)
    inputs = verdict_inputs(rig, doc)._replace(records_dir=linked)
    code, out, _ = run_verdict(rig, inputs)
    assert code == 3
    assert "as a regular file" in json.loads(out.read_text())["internal_errors"][0]["message"]


def test_verdict_cli_passes_with_every_binding_flag_and_exits_3_on_a_mismatch(std):
    rig, runner = std
    doc = ci_doc(rig, runner)
    assert gate.main(verdict_argv(rig, doc)) == 0
    assert gate.main(verdict_argv(rig, doc, run_id="10")) == 3
    assert gate.main(verdict_argv(rig, doc, gated_sha="c" * 40)) == 3
    assert gate.main(verdict_argv(rig, doc, pr=8)) == 3
    write_records(rig, ci_doc(rig, runner, run_attempt="2"))
    assert gate.main(verdict_argv(rig, doc)) == 3
    assert gate.main(verdict_argv(rig, doc, run_attempt=2)) == 0


@pytest.mark.parametrize(
    "omit",
    [
        "--records-dir",
        "--gated-sha",
        "--pr",
        "--run-id",
        "--run-attempt",
        "--measure-result",
        "--out",
        "--summary",
    ],
)
def test_verdict_cli_requires_every_binding_flag(std, omit, capsys):
    """F5: leaving a flag out must be a usage error (exit 2), never a default that reads as success."""
    rig, runner = std
    doc = ci_doc(rig, runner)
    argv = verdict_argv(rig, doc)
    at = argv.index(omit)
    with pytest.raises(SystemExit) as raised:
        gate.main(argv[:at] + argv[at + 2 :])
    assert raised.value.code == 2
    assert omit in capsys.readouterr().err


@pytest.mark.parametrize("omit", ["--tests-result", "--run-id", "--run-attempt"])
def test_measure_cli_requires_the_ci_binding_flags(omit, capsys):
    argv = [
        "measure",
        "--gated-sha",
        "a",
        "--pr-head-sha",
        "b",
        "--pr",
        "1",
        "--coverage-file",
        "c",
        "--meta",
        "m",
        "--out",
        "o",
        "--tests-result",
        "success",
        "--run-id",
        "9",
        "--run-attempt",
        "1",
    ]
    at = argv.index(omit)
    with pytest.raises(SystemExit) as raised:
        gate.main(argv[:at] + argv[at + 2 :])
    assert raised.value.code == 2
    assert omit in capsys.readouterr().err


def test_verdict_refuses_records_written_without_a_run_id(std):
    rig, runner = std
    doc, _ = rig.measure(runner)
    doc = dict(doc, mode="ci", pr=PR)
    assert doc["run_id"] is None
    assert run_verdict(rig, verdict_inputs(rig, doc))[0] == 3


def test_verdict_reads_only_a_directory_holding_exactly_the_records_file(std):
    """F5: the checkout (or any directory with other files in it) is not a records directory."""
    rig, runner = std
    doc = ci_doc(rig, runner)
    inputs = verdict_inputs(rig, doc)
    (inputs.records_dir / "extra.json").write_text("{}", encoding="utf-8")
    code, out, _summary = run_verdict(rig, inputs)
    assert code == 3
    assert (
        "must hold exactly new-code-records.json"
        in json.loads(out.read_text())["internal_errors"][0]["message"]
    )
    (inputs.records_dir / "extra.json").unlink()
    assert run_verdict(rig, inputs)[0] == 0
    elsewhere = rig.tmp / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / gate.RECORDS_FILENAME).symlink_to(inputs.records_dir / gate.RECORDS_FILENAME)
    assert run_verdict(rig, inputs._replace(records_dir=elsewhere))[0] == 3
    code, out, _summary = run_verdict(rig, inputs._replace(records_dir=rig.tmp / "no-such-dir"))
    assert code == 3
    assert (
        "records directory missing" in json.loads(out.read_text())["internal_errors"][0]["message"]
    )


def test_fetch_rulings_is_the_empty_s2_seam():
    assert gate.fetch_rulings(1, "abc", ["a.py"]) == []


def test_main_meta_writes_sidecar_and_measure_runs_end_to_end_on_a_noop_diff(
    rig, monkeypatch, capsys
):
    rig.base()
    rig.write("docs/n.md", "x\n")
    rig.commit("docs")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    monkeypatch.chdir(rig.root)
    monkeypatch.setenv("COVERAGE_CORE", "ctrace")
    monkeypatch.setenv("GITHUB_RUN_ID", "9")
    cov, meta = str(rig.tmp / ".coverage"), rig.tmp / "meta.json"
    assert gate.main(["meta", "--coverage-file", cov, "--out", str(meta)]) == 0
    sidecar = json.loads(meta.read_text())
    assert (
        sidecar["head_sha"] == rig.head()
        and sidecar["clean"] is True
        and sidecar["coverage_core"] == "ctrace"
        and sidecar["run_id"] == "9"
    )
    assert sidecar["tool_versions"] == gate.installed_versions() == dict(ncg.PINNED)
    assert sidecar["measured_sources"] == list(ncg.MEASURED_SOURCES) and sidecar[
        "checkout_root"
    ] == str(rig.root.resolve())
    assert sidecar["python"] == gate.python_version() and sidecar["schema"] == ncg.SCHEMA_META
    head, base = rig.head(), rig.git("rev-parse", "HEAD^")
    assert head and base
    # a one-parent gated commit under CI-style flags fails the AR-1 guard with exit 3
    out = rig.tmp / "records.json"
    argv = [
        "measure",
        "--gated-sha",
        head,
        "--pr-head-sha",
        head,
        "--pr",
        "5",
        "--coverage-file",
        cov,
        "--run-id",
        "9",
        "--run-attempt",
        "1",
    ]
    ci = [*argv, "--meta", str(meta), "--out", str(out)]
    assert gate.main([*ci, "--tests-result", "success"]) == 3
    assert (
        json.loads(out.read_text())["internal_errors"][0]["message"]
        == "merge commit does not contain the PR head"
    )
    assert json.loads(out.read_text())["run_id"] == "9"
    assert gate.main([*ci, "--tests-result", "failure"]) == 3
    assert "upstream job not successful: failure" in out.read_text()
    capsys.readouterr()


def test_main_meta_flags_a_dirty_tree_and_a_missing_coverage_file(rig, monkeypatch, capsys):
    rig.base()
    rig.write("scripts/a.py", "a = 1\n")
    rig.commit("a")
    monkeypatch.chdir(rig.root)
    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    (rig.root / "scripts/a.py").write_text("a = 2\n")
    meta = rig.tmp / "meta.json"
    cov = rig.tmp / ".coverage"
    assert gate.main(["meta", "--coverage-file", str(cov), "--out", str(meta)]) == 3
    assert "coverage file missing" in capsys.readouterr().err
    cov.write_text("x")
    assert gate.main(["meta", "--coverage-file", str(cov), "--out", str(meta)]) == 0
    sidecar = json.loads(meta.read_text())
    assert sidecar["clean"] is False and sidecar["dirty_paths"] == ["scripts/a.py"]
    assert sidecar["run_id"] is None
    monkeypatch.setenv("GITHUB_RUN_ID", "")
    gate.main(["meta", "--coverage-file", str(cov), "--out", str(meta)])
    assert json.loads(meta.read_text())["run_id"] is None
    many = [f"scripts/m{i}.py" for i in range(30)]
    for rel in many:
        rig.write(rel, "a = 1\n")
    rig.commit("many")
    for rel in many:
        (rig.root / rel).write_text("a = 2\n")
    assert gate.main(["meta", "--coverage-file", str(cov), "--out", str(meta)]) == 0
    assert len(json.loads(meta.read_text())["dirty_paths"]) == ncg.MAX_SIDECAR_PATHS


@pytest.mark.parametrize(
    "porcelain,expected",
    [
        ("", []),
        (" M a.py\0?? b.txt\0", ["a.py"]),
        ("M  s.sh\0 M README.md\0", ["s.sh"]),
        ("R  new.py\0old.sh\0 M c.txt\0", ["new.py", "old.sh"]),
        ("RM x.md\0y.md\0", []),
        ("C  copy.sh\0orig.sh\0", ["copy.sh", "orig.sh"]),
        ("ab\0", []),
    ],
    ids=argv_safe_id,
)
def test_dirty_paths_reads_z_porcelain(porcelain, expected):
    assert gate.dirty_paths(porcelain) == expected


def test_main_usage_errors_exit_2(capsys):
    for argv in ([], ["bogus"], ["measure"], ["meta", "--nope"]):
        with pytest.raises(SystemExit) as raised:
            gate.main(argv)
        assert raised.value.code == 2
    capsys.readouterr()


def test_main_maps_gate_errors_and_crashes_to_exit_3(monkeypatch, capsys):
    def explode(args):
        raise RuntimeError("kaboom")

    def refuse(args):
        raise gate.GateError("no go")

    monkeypatch.setitem(gate.HANDLERS, "meta", explode)
    assert gate.main(["meta", "--coverage-file", "c", "--out", "o"]) == 3
    assert "internal error: RuntimeError: kaboom" in capsys.readouterr().err
    monkeypatch.setitem(gate.HANDLERS, "meta", refuse)
    assert gate.main(["meta", "--coverage-file", "c", "--out", "o"]) == 3
    assert "new_code_gate: no go" in capsys.readouterr().err


def test_main_hidden_phases_take_their_arguments(monkeypatch, tmp_path, capsys):
    lines = tmp_path / "lines.json"
    lines.write_text("[1, 2]")
    seen = {}

    def fake_enumerate(rel, gated, cwd):
        seen["enumerate"] = (rel, gated, cwd)
        return {"ok": 1}

    def fake_collect(rel, cwd):
        seen["collect"] = (rel, cwd)
        return {"ok": 2}

    monkeypatch.setattr(gate, "enumerate_child", fake_enumerate)
    monkeypatch.setattr(gate, "collect_child", fake_collect)
    monkeypatch.chdir(tmp_path)
    assert gate.main(["_enumerate", "--file", "a.py", "--gated-lines-json", str(lines)]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": 1}
    assert gate.main(["_collect", "--file", "a.py"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": 2}
    assert seen["enumerate"][:2] == ("a.py", [1, 2]) and seen["collect"][0] == "a.py"


# --------------------------------------------------------------------------
# `run` (local)
# --------------------------------------------------------------------------


def run_args(**override):
    import argparse

    return argparse.Namespace(**{"base": "main", "keep_workspace": False, **override})


def test_run_refuses_a_dirty_tree_a_stale_sidecar_and_a_missing_one(std):
    rig, _ = std
    rig.sidecar()
    (rig.root / "coverage-meta.json").write_text((rig.tmp / "coverage-meta.json").read_text())
    (rig.root / CALC_PATH).write_text(CALC + "# edit\n")
    with pytest.raises(
        gate.GateError, match="tracked .py/.sh files are modified: scripts/framework/calc.py"
    ):
        gate.local_options(run_args(), rig.root)
    rig.git("checkout", "--", CALC_PATH)
    options = gate.local_options(run_args(base="origin/main", keep_workspace=True), rig.root)
    assert (options.mode, options.base_ref, options.keep_workspace) == (
        "local",
        "origin/main",
        True,
    )
    assert options.gated_sha == options.pr_head_sha == rig.head()
    (rig.root / "coverage-meta.json").write_text(
        json.dumps(
            {
                "schema": ncg.SCHEMA_META,
                "head_sha": "0" * 40,
                "clean": True,
                "coverage_core": "ctrace",
            }
        )
    )
    with pytest.raises(gate.GateError, match="coverage data stale or from a dirty tree"):
        gate.local_options(run_args(), rig.root)
    (rig.root / "coverage-meta.json").unlink()
    with pytest.raises(gate.GateError, match="coverage sidecar missing"):
        gate.local_options(run_args(), rig.root)


def test_command_run_measures_head_prints_the_table_and_writes_artifacts(rig, monkeypatch, capsys):
    rig.base()
    rig.write("docs/n.md", "x\n")
    rig.commit("docs")
    rig.coverage({"x.py": {"tests/t.py::t|run": [1]}})
    monkeypatch.chdir(rig.root)
    monkeypatch.setenv("COVERAGE_CORE", "ctrace")
    meta = rig.root / "coverage-meta.json"
    assert (
        gate.main(["meta", "--coverage-file", str(rig.tmp / ".coverage"), "--out", str(meta)]) == 0
    )
    (rig.root / ".coverage").write_bytes((rig.tmp / ".coverage").read_bytes())
    monkeypatch.setattr(tempfile, "tempdir", str(rig.work))
    assert gate.main(["run", "--base", "main"]) == 0
    captured = capsys.readouterr()
    assert "No gated files in this PR." in captured.out
    out_dir = Path(captured.err.split("written to ")[1].strip())
    assert json.loads((out_dir / "new-code-records.json").read_text())["mode"] == "local"
    assert json.loads((out_dir / "new-code-verdict.json").read_text())["overall"] == "pass"
    assert gate.main(["run", "--base", "main", "--keep-workspace"]) == 0
    capsys.readouterr()
    rig.write("scripts/dirty.py", "a = 1\n")
    rig.commit("dirty")
    (rig.root / "scripts/dirty.py").write_text("a = 2\n")
    assert gate.main(["run"]) == 3
    assert "tracked .py/.sh files are modified" in capsys.readouterr().err


# --------------------------------------------------------------------------
# The real runner, clock and small helpers
# --------------------------------------------------------------------------


def spec_for(argv, timeout=30.0, env=None, cwd=None):
    return gate.ProcSpec(argv, str(cwd or Path.cwd()), env or dict(os.environ), timeout)


def test_subprocess_runner_reports_output_and_exit_code(tmp_path):
    runner = gate.SubprocessRunner()
    argv = [
        sys.executable,
        "-c",
        "import sys; print('out'); print('err', file=sys.stderr); sys.exit(4)",
    ]
    result = runner.run("x", spec_for(argv, cwd=tmp_path))
    assert result == gate.ProcResult(4, "out\n", "err\n", False)


# RV3-2(a): these tests run once per surviving SubprocessRunner mutant, so each takes its kill grace
# from the `SubprocessRunner(grace=...)` seam and its children live at most CHILD_LIFE seconds.
# The runner's timeout (CUT_AFTER) fires inside that life, and the grace is far shorter than it.
CHILD_LIFE = 0.2
CUT_AFTER = 0.12
GRACE = 0.03
CHILD_SLEEP = f"time.sleep({CHILD_LIFE})"


def wait_until_gone(pid, seconds=0.1):
    """True once the process has exited (a zombie counts as gone)."""
    deadline = gate.Clock().monotonic() + seconds
    while gate.Clock().monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
        except OSError:
            return True
        if state == "Z":
            return True
        time.sleep(0.005)
    return False


def test_subprocess_runner_kills_the_process_group_on_timeout(tmp_path):
    marker = tmp_path / "grandchild.pid"
    script = textwrap.dedent(
        f"""
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, "-c", "import time; {CHILD_SLEEP}"])
        open({str(marker)!r}, "w").write(str(child.pid))
        {CHILD_SLEEP}
        """
    )
    started = gate.Clock().monotonic()
    result = gate.SubprocessRunner(grace=GRACE).run(
        "x", spec_for([sys.executable, "-c", script], timeout=CUT_AFTER, cwd=tmp_path)
    )
    assert result.timed_out is True and result.returncode != 0
    assert gate.Clock().monotonic() - started < 30
    assert wait_until_gone(int(marker.read_text()))


def test_subprocess_runner_escalates_to_sigkill_when_sigterm_is_ignored(tmp_path):
    script = (
        "import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"print('ready', flush=True)\n{CHILD_SLEEP}\n"
    )
    result = gate.SubprocessRunner(grace=GRACE).run(
        "x", spec_for([sys.executable, "-c", script], timeout=CUT_AFTER, cwd=tmp_path)
    )
    assert result.timed_out is True and result.returncode == -9


def test_subprocess_runner_kills_a_sigterm_ignoring_group_member_that_holds_the_pipe(tmp_path):
    """M1: the leader dies on SIGTERM but a member ignores it and keeps the output pipe open."""
    marker = tmp_path / "member.pid"
    script = textwrap.dedent(
        f"""
        import subprocess, sys, time
        member = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); {CHILD_SLEEP}",
            ]
        )
        open({str(marker)!r}, "w").write(str(member.pid))
        print("partial", flush=True)
        {CHILD_SLEEP}
        """
    )
    started = gate.Clock().monotonic()
    result = gate.SubprocessRunner(grace=GRACE).run(
        "x", spec_for([sys.executable, "-c", script], timeout=CUT_AFTER, cwd=tmp_path)
    )
    assert gate.Clock().monotonic() - started < 30
    assert result.timed_out is True and "partial" in result.stdout
    assert wait_until_gone(int(marker.read_text()))


def test_subprocess_runner_gives_up_on_a_pipe_held_by_a_process_outside_the_group(tmp_path):
    """M1: a holder in another session survives killpg, so the second read must be bounded too."""
    marker = tmp_path / "holder.pid"
    script = textwrap.dedent(
        f"""
        import subprocess, sys, time
        holder = subprocess.Popen(
            [sys.executable, "-c", "import time; {CHILD_SLEEP}"], start_new_session=True
        )
        open({str(marker)!r}, "w").write(str(holder.pid))
        print("partial", flush=True)
        {CHILD_SLEEP}
        """
    )
    started = gate.Clock().monotonic()
    try:
        result = gate.SubprocessRunner(grace=GRACE).run(
            "x", spec_for([sys.executable, "-c", script], timeout=CUT_AFTER, cwd=tmp_path)
        )
        assert gate.Clock().monotonic() - started < 30
        assert result.timed_out is True and "partial" in result.stdout and result.stderr == ""
        assert result.returncode == -15
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(int(marker.read_text()), 9)
        assert wait_until_gone(int(marker.read_text()))


@contextlib.contextmanager
def interrupt_after(seconds, exc):
    """Raise `exc` in the main thread after `seconds`, as Ctrl-C or the SIGTERM handler would."""

    def raiser(signum, frame):
        raise exc

    previous = signal.signal(signal.SIGALRM, raiser)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@pytest.mark.parametrize("exc", [KeyboardInterrupt, SystemExit], ids=["ctrl-c", "sigterm-exit"])
def test_int1_an_interrupt_kills_the_whole_child_group_and_is_re_raised(tmp_path, exc):
    """RV-4: nothing is left running when the gate is interrupted, even a SIGTERM-ignoring child."""
    marker = tmp_path / "pids.txt"
    script = textwrap.dedent(
        f"""
        import os, signal, subprocess, sys, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        member = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); {CHILD_SLEEP}",
            ]
        )
        open({str(marker)!r}, "w").write(f"{{os.getpid()}} {{member.pid}}")
        {CHILD_SLEEP}
        """
    )
    started = gate.Clock().monotonic()
    with pytest.raises(exc):
        with interrupt_after(CUT_AFTER, exc):
            gate.SubprocessRunner(grace=GRACE).run(
                "x", spec_for([sys.executable, "-c", script], timeout=120.0, cwd=tmp_path)
            )
    assert gate.Clock().monotonic() - started < 40
    leader, member = (int(pid) for pid in marker.read_text().split())
    assert wait_until_gone(leader) and wait_until_gone(member)


def test_int1_an_interrupt_in_a_phase_removes_every_workspace_and_is_not_swallowed(std):
    rig, runner = std
    seen = {}

    def hook(phase, spec):
        if phase == gate.PHASE_MUTMUT:
            seen["workspaces"] = len(list(rig.work.glob("ncg-*")))
            raise KeyboardInterrupt

    runner.hook = hook
    with pytest.raises(KeyboardInterrupt):
        rig.measure(runner)
    assert seen["workspaces"] == 1
    assert list(rig.work.iterdir()) == []


def test_the_sigterm_handler_turns_the_signal_into_system_exit_143():
    gate.install_sigterm_handler()
    assert signal.getsignal(signal.SIGTERM) is gate.exit_on_sigterm
    with pytest.raises(SystemExit) as raised:
        signal.raise_signal(signal.SIGTERM)
    assert raised.value.code == gate.EXIT_SIGTERM == 143


def test_only_measure_and_run_install_the_sigterm_handler(std, monkeypatch, capsys):
    rig, runner = std
    calls = []
    monkeypatch.setattr(gate, "install_sigterm_handler", lambda: calls.append("installed"))
    monkeypatch.setattr(gate, "local_options", lambda args, repo: rig.options())
    monkeypatch.setattr(gate, "SubprocessRunner", lambda: runner)
    monkeypatch.setattr(tempfile, "tempdir", str(rig.work))
    assert gate.main(["run", "--base", "main"]) == 0
    assert calls == ["installed"]
    out = rig.tmp / "r.json"
    argv = ["measure", "--gated-sha", "a", "--pr-head-sha", "b", "--pr", "1"]
    argv += ["--coverage-file", "c", "--meta", "m", "--out", str(out)]
    argv += ["--tests-result", "failure", "--run-id", "9", "--run-attempt", "1"]
    assert gate.main(argv) == 3
    assert calls == ["installed", "installed"]
    monkeypatch.setattr(gate, "collect_child", lambda rel, cwd: {})
    assert gate.main(["_collect", "--file", "a.py"]) == 0
    assert calls == ["installed", "installed"]
    capsys.readouterr()


def test_as_text_accepts_bytes_text_and_nothing():
    assert gate.as_text(None) == ""
    assert gate.as_text(b"a\xffb") == "a�b"
    assert gate.as_text("plain") == "plain"


def test_signal_group_ignores_a_process_that_is_already_gone():
    done = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    done.wait()
    gate.SubprocessRunner().signal_group(done.pid, 15)


def test_clock_reports_monotonic_time_and_utc_iso():
    clock = gate.Clock()
    first = clock.monotonic()
    assert clock.monotonic() >= first
    stamp = clock.utc_iso()
    assert len(stamp) == 20 and stamp.endswith("Z") and stamp[10] == "T"


def test_scrubbed_env_drops_credentials_and_ncg_variables():
    env = {
        "PATH": "/bin",
        "GITHUB_TOKEN": "a",
        "GH_TOKEN": "b",
        "ACTIONS_X": "c",
        "NCG_LOG": "d",
        "OTHER": "f",
    }
    assert gate.scrubbed_env(env) == {"PATH": "/bin", "OTHER": "f"}


def test_output_tail_keeps_the_last_forty_lines_bounded():
    text = "\n".join(f"line {i}" for i in range(100))
    tail = gate.output_tail(text)
    assert tail.splitlines()[0] == "line 60" and tail.splitlines()[-1] == "line 99"
    assert len(gate.output_tail("x" * 10000)) == gate.OUTPUT_TAIL_CHARS


def test_installed_versions_reports_missing_packages(monkeypatch):
    import importlib.metadata

    def fake(name):
        if name == "libcst":
            raise importlib.metadata.PackageNotFoundError(name)
        return "1.0"

    monkeypatch.setattr(importlib.metadata, "version", fake)
    versions = gate.installed_versions()
    assert versions["libcst"] == "missing" and versions["mutmut"] == "1.0"
    assert ncg.check_pins(versions) == "tool version mismatch: coverage 1.0 != 7.17.2"


def test_python_version_is_major_dot_minor():
    assert gate.python_version() == f"{sys.version_info.major}.{sys.version_info.minor}"


def test_contaminated_finds_nested_claude_and_mutants(tmp_path):
    assert gate.contaminated(tmp_path) is None
    (tmp_path / "a" / "b" / ".claude").mkdir(parents=True)
    assert gate.contaminated(tmp_path) == str(Path("a/b/.claude"))
    (tmp_path / "mutants").mkdir()
    assert gate.contaminated(tmp_path) == "mutants"


def test_top_level_entries_split_dirs_and_files_and_skip_symlinks(tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "f.txt").write_text("x")
    (tmp_path / "link").symlink_to(tmp_path / "f.txt")
    (tmp_path / "dlink").symlink_to(tmp_path / "d")
    assert gate.top_level_entries(tmp_path) == (["d"], ["f.txt"])


def test_exact_text_round_trip_keeps_line_endings(tmp_path):
    path = tmp_path / "f.py"
    gate.write_exact(path, "a = 1\r\nb = 2\r\n")
    assert (
        path.read_bytes() == b"a = 1\r\nb = 2\r\n" and gate.read_exact(path) == "a = 1\r\nb = 2\r\n"
    )


def test_under_selection_matches_equal_or_nested_ids_only():
    assert gate.under_selection("tests/a.py::t", ["tests/a.py::t"])
    assert gate.under_selection("tests/a.py::t[1]", ["tests/a.py"])
    assert gate.under_selection("tests/a.py::t[1]", ["tests/a.py::t"]) is False
    assert gate.under_selection("tests/a.py::t[1]", ["tests/a.py::t[1]"])
    assert gate.under_selection("tests/a.py::C::t", ["tests/a.py"])
    assert gate.under_selection("tests/ab.py::t", ["tests/a.py"]) is False


def test_isolation_stage_names_the_two_mutmut_messages():
    assert gate.isolation_stage("x failed to collect stats. runner returned 1") == "stats"
    assert gate.isolation_stage("Failed to run clean test") == "clean"
    assert gate.isolation_stage("nothing") is None


# --------------------------------------------------------------------------
# NOGLOBAL and the child phases with real mutmut (A9b, A9c)
# --------------------------------------------------------------------------


class ConfigGuard:
    """Save the host mutmut's cached config object and put the same object back (TD 5.19, NOGLOBAL)."""

    def __enter__(self):
        import mutmut.configuration as configuration

        self.module = configuration
        self.saved = configuration._config
        return configuration

    def __exit__(self, *exc_info):
        self.module._config = self.saved
        return False


@pytest.fixture
def restore_mutmut_config():
    with ConfigGuard() as configuration:
        yield configuration


def child_workspace(tmp_path, monkeypatch, source, only_mutate=None, rel="pkg/mod.py"):
    tree = tmp_path / "ws"
    (tree / "pkg").mkdir(parents=True)
    (tree / rel).write_text(source, encoding="utf-8")
    only = [rel] if only_mutate is None else only_mutate
    (tree / "pyproject.toml").write_text(
        f'[tool.mutmut]\nonly_mutate = {json.dumps(only)}\nsource_paths = ["pkg/"]\n'
        'pytest_add_cli_args_test_selection = ["tests/"]\nuse_git_change_detection = false\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(tree)
    return tree


MOD = (
    "def add(a, b):\n    return a + b\n\n\n"
    "class K:\n    def m(self, x):\n        return x - 1\n\n\n"
    "def other(a):\n    return a * 2\n"
)


def test_enumerate_child_maps_mutants_to_gated_lines(tmp_path, monkeypatch, restore_mutmut_config):
    tree = child_workspace(tmp_path, monkeypatch, MOD)
    doc = gate.enumerate_child("pkg/mod.py", [2, 7], tree)
    assert doc["schema"] == ncg.SCHEMA_ENUM and doc["file"] == "pkg/mod.py"
    assert doc["gate_file"] == str(Path(gate.__file__).resolve())
    names = doc["mutant_names"]
    assert names == sorted(names) and all(ncg.check_mutant_key(n) for n in names)
    assert doc["unmappable"] == []
    assert any(".x_add__mutmut_" in n for n in names) and any("xǁKǁm__mutmut_" in n for n in names)
    gated = set(doc["gated_mutant_names"])
    assert gated and gated < set(names)
    for name in names:
        lines = doc["line_map"][name]
        assert lines and (name in gated) == bool({2, 7} & set(lines))
    assert not any(".x_other__mutmut_" in n for n in gated)


def test_enumerate_child_uses_the_class_of_a_same_named_method(
    tmp_path, monkeypatch, restore_mutmut_config
):
    source = "class A:\n    def run(self):\n        return 1\n\n\nclass B:\n    def run(self):\n        return 2\n"
    tree = child_workspace(tmp_path, monkeypatch, source)
    doc = gate.enumerate_child("pkg/mod.py", [3], tree)
    gated = doc["gated_mutant_names"]
    assert gated and all("ǁAǁrun" in n for n in gated)
    assert all(doc["line_map"][n] == [8] for n in doc["mutant_names"] if "ǁBǁrun" in n)


def test_enumerate_child_reports_a_file_with_no_mutants(
    tmp_path, monkeypatch, restore_mutmut_config
):
    tree = child_workspace(tmp_path, monkeypatch, "X = 1\n")
    doc = gate.enumerate_child("pkg/mod.py", [1], tree)
    assert (doc["mutant_names"], doc["gated_mutant_names"], doc["unmappable"]) == ([], [], [])


def test_a_scoped_result_is_final_and_an_empty_one_falls_back_to_the_whole_module(
    tmp_path, monkeypatch, restore_mutmut_config
):
    """RV3-1: only an empty scoped mapping reaches the whole-module diff; both empty is unmappable."""
    tree = child_workspace(tmp_path, monkeypatch, MOD)
    expected = gate.enumerate_child("pkg/mod.py", [2, 7], tree)
    assert expected["unmappable"] == []

    def whole_module_is_never_asked(*args):
        raise AssertionError("a non-empty scoped result was second-guessed")

    with monkeypatch.context() as scoped_only:
        scoped_only.setattr(gate, "mutant_lines", whole_module_is_never_asked)
        assert gate.enumerate_child("pkg/mod.py", [2, 7], tree) == expected
    with monkeypatch.context() as fallback:
        fallback.setattr(gate, "scoped_mutant_lines", lambda *args: [])
        assert gate.enumerate_child("pkg/mod.py", [2, 7], tree) == expected
        fallback.setattr(gate, "mutant_lines", lambda *args: [])
        doc = gate.enumerate_child("pkg/mod.py", [2, 7], tree)
    assert doc["unmappable"] == doc["mutant_names"] != [] and doc["gated_mutant_names"] == []


def test_scoped_lines_use_the_position_of_the_function_including_its_leading_lines(
    tmp_path, monkeypatch, restore_mutmut_config
):
    source = "X = 1\n\n\n# note one\n# note two\ndef f(a):\n    return a + 1\n\n\ndef g(a):\n    return a - 1\n"
    tree = child_workspace(tmp_path, monkeypatch, source)
    made = gate.generate_mutants("pkg/mod.py", tree)
    rendered = {}
    by_name = {
        n: gate.scoped_mutant_lines(
            n, made.orig_module, made.mutated_module, made.positions, rendered
        )
        for n in made.names
    }
    assert {tuple(v) for n, v in by_name.items() if ".x_f__" in n} == {(7,)}
    assert {tuple(v) for n, v in by_name.items() if ".x_g__" in n} == {(11,)}
    # `start` is the first of the leading lines (the blank lines and comments above the def)
    assert len(rendered) == 2 and {start for start, _ in rendered.values()} == {2, 8}
    assert (
        gate.scoped_mutant_lines(
            "pkg.mod.xǁMissingǁf__mutmut_1",
            made.orig_module,
            made.mutated_module,
            made.positions,
            rendered,
        )
        == []
    )


def mapping_check(tmp_path, rel, source, limit):
    """Run both mappings over a file's mutants in a subprocess and report any difference (EQ-MAP)."""
    ws = tmp_path / "eq-ws"
    target = ws / rel
    target.parent.mkdir(parents=True)
    target.write_bytes(source)
    source_dir = rel.rsplit("/", 1)[0] + "/"
    (ws / "pyproject.toml").write_text(
        f'[tool.mutmut]\nonly_mutate = ["{rel}"]\nsource_paths = ["{source_dir}"]\n'
        'pytest_add_cli_args_test_selection = ["tests/"]\nuse_git_change_detection = false\n',
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", EQ_SNIPPET, str(EQ_REPO), rel, str(limit)],
        cwd=ws,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout)


EQ_REPO = Path(__file__).resolve().parents[2]
EQ_SNIPPET = textwrap.dedent(
    """
    import json, sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from scripts.framework import new_code_gate as gate
    rel, limit = sys.argv[2], int(sys.argv[3])
    made = gate.generate_mutants(rel, Path.cwd())
    first_of = {}
    for name in made.names:
        first_of.setdefault(name.rsplit("__mutmut_", 1)[0], name)
    chosen = set(first_of.values())
    if limit and len(made.names) > limit:
        chosen |= set(made.names[:: max(1, len(made.names) // (limit - len(chosen)))])
    else:
        chosen = set(made.names)
    rendered, bad, empty = {}, [], []
    for name in sorted(chosen):
        args = (name, made.orig_module, made.mutated_module)
        scoped = gate.scoped_mutant_lines(*args, made.positions, rendered)
        whole = gate.mutant_lines(made.original, *args)
        if scoped != whole:
            bad.append([name, scoped, whole])
        if not whole:
            empty.append(name)
    print(json.dumps({"mutants": len(made.names), "checked": len(chosen), "functions": len(first_of),
                      "bad": bad[:5], "empty": empty[:5]}))
    """
)
EQ_FIXTURE = (
    '"""Doc."""\n\nimport os\n\n\n# a comment block\n# over two lines\ndef lead(a, b):\n    return a + b\n\n\n'
    "class K:\n    def run(self, x):\n        return x - 1\n\n    @staticmethod\n    def helper(a):\n"
    "        return a * 2\n\n\nclass L:\n    def run(self, x):\n        return x + 1\n\n\n"
    "def multi(a, b):\n    total = (\n        a\n        + b\n    )\n    return total\n\n\n"
    "def last(a):\n    return a - 1"
)


@pytest.mark.slow
def test_function_scoped_mapping_equals_whole_module_on_the_edge_fixtures(tmp_path):
    """EQ-MAP: a method, same-named methods, a leading comment, a staticmethod, a multi-line statement,
    and a last function with no trailing newline give the same lines both ways."""
    got = mapping_check(tmp_path, "pkg/mod.py", EQ_FIXTURE.encode(), 0)
    assert got["bad"] == [] and got["empty"] == []
    assert got["checked"] == got["mutants"] > 10 and got["functions"] == 6


@pytest.mark.slow
@pytest.mark.parametrize(
    "rel,limit",
    [
        ("scripts/oversight/validators/shell_logic_check.py", 0),
        ("scripts/framework/new_code_gate_pytest_plugin.py", 0),
        ("scripts/framework/new_code_gate.py", 210),
        ("scripts/framework/new_code_gate_logic.py", 210),
    ],
    ids=["shell_logic_check", "plugin", "gate", "logic"],
)
def test_function_scoped_mapping_equals_whole_module(tmp_path, rel, limit):
    """EQ-MAP (ADR-2304 RV3-1): every mutant of the small files, and at least 200 of the large ones
    (one of each function and method first), map to the same lines with the function-scoped diff."""
    got = mapping_check(tmp_path, rel, (EQ_REPO / rel).read_bytes(), limit)
    assert got["bad"] == [] and got["empty"] == []
    if limit:
        assert got["checked"] >= 200 and got["checked"] <= limit + got["functions"]
    else:
        assert got["checked"] == got["mutants"]


def test_enumerate_refuses_when_only_mutate_differs(tmp_path, monkeypatch, restore_mutmut_config):
    tree = child_workspace(tmp_path, monkeypatch, MOD, only_mutate=["pkg/other.py"])
    with pytest.raises(gate.GateError, match=r"only_mutate is not \[pkg/mod.py\]"):
        gate.enumerate_child("pkg/mod.py", [1], tree)
    with pytest.raises(gate.GateError, match="only_mutate"):
        gate.collect_child("pkg/mod.py", tree)
    (tree / "pyproject.toml").unlink()
    with pytest.raises(gate.GateError, match="needs a workspace pyproject.toml"):
        gate.enumerate_child("pkg/mod.py", [1], tree)
    (tree / "pyproject.toml").write_text("not [valid", encoding="utf-8")
    with pytest.raises(gate.GateError, match="needs a workspace pyproject.toml"):
        gate.collect_child("pkg/mod.py", tree)


def test_collect_child_reads_meta_and_reports_statuses(
    tmp_path, monkeypatch, restore_mutmut_config
):
    tree = child_workspace(tmp_path, monkeypatch, MOD)
    (tree / "mutants" / "pkg").mkdir(parents=True)
    codes = {
        "pkg.mod.x_add__mutmut_1": 1,
        "pkg.mod.x_add__mutmut_2": 36,
        "pkg.mod.x_add__mutmut_3": 33,
        "pkg.mod.x_add__mutmut_4": 77,
        "pkg.mod.x_add__mutmut_5": None,
        "pkg.mod.x_add__mutmut_6": 0,
    }
    meta = {
        "exit_code_by_key": codes,
        "hash_by_function_name": {},
        "type_check_error_by_key": {},
        "durations_by_key": {},
        "estimated_durations_by_key": {},
    }
    (tree / "mutants" / "pkg" / "mod.py.meta").write_text(json.dumps(meta), encoding="utf-8")
    # A real Config (RV3-3c): the stats run's trampoline reads config() on every gated call.
    sentinel = copy.copy(restore_mutmut_config.config())
    restore_mutmut_config._config = sentinel
    doc = gate.collect_child("pkg/mod.py", tree)
    assert restore_mutmut_config._config is None
    assert doc["schema"] == ncg.SCHEMA_COLLECT and doc["gate_file"] == str(
        Path(gate.__file__).resolve()
    )
    assert doc["exit_code_by_key"] == codes
    assert [doc["status_by_key"][k] for k in codes] == [
        "killed",
        "timeout",
        "no tests",
        "suspicious",
        None,
        "survived",
    ]
    (tree / "mutants" / "pkg" / "mod.py.meta").unlink()
    with pytest.raises(gate.GateError, match="wrote no meta file"):
        gate.collect_child("pkg/mod.py", tree)


def test_child_side_calls_restore_host_mutmut_config(tmp_path, monkeypatch):
    import mutmut.configuration as configuration

    saved = configuration._config
    tree = child_workspace(tmp_path, monkeypatch, MOD)
    try:
        sentinel = copy.copy(configuration.config())
        configuration._config = sentinel
        with ConfigGuard():
            gate.enumerate_child("pkg/mod.py", [2], tree)
            assert configuration._config is not sentinel
        assert configuration._config is sentinel
        with ConfigGuard():
            with pytest.raises(gate.GateError):
                gate.collect_child("pkg/mod.py", tree)
        assert configuration._config is sentinel
    finally:
        configuration._config = saved


def test_every_test_calling_a_child_phase_restores_the_host_mutmut_config():
    import ast

    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    source = Path(__file__).read_text(encoding="utf-8")
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
            continue
        calls = {
            n.func.attr
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        guarded = "restore_mutmut_config" in [a.arg for a in node.args.args] or "ConfigGuard" in (
            ast.get_source_segment(source, node) or ""
        )
        if calls & {"enumerate_child", "collect_child"} and not guarded:
            offenders.append(node.name)
    assert offenders == []
