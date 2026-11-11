"""Static conditions on the new-code gate that need no real run (#2304, TD 9.3, REQ-35).

Includes the static checks of .github/workflows/tests.yml (S2d). Everything here reads source text
or runs a fresh interpreter: it imports **no** gate module in process, so these checks neither
depend on nor earn coverage for the code they guard.
"""

import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK = ROOT / "scripts" / "framework"
GATE_MODULES = (
    FRAMEWORK / "new_code_gate.py",
    FRAMEWORK / "new_code_gate_logic.py",
    FRAMEWORK / "new_code_gate_pytest_plugin.py",
)
SHELL_CHECK = ROOT / "scripts" / "oversight" / "validators" / "shell_logic_check.py"
TESTS = ROOT / "tests"
E2E = TESTS / "framework" / "test_new_code_gate_e2e.py"
IN_PROCESS_TESTS = (
    TESTS / "framework" / "test_new_code_gate_logic.py",
    TESTS / "framework" / "test_new_code_gate_measure.py",
    TESTS / "framework" / "test_new_code_gate_plugin.py",
    Path(__file__).resolve(),
    TESTS / "oversight" / "test_shell_logic_check.py",
)
REQUIREMENTS = ROOT / "scripts" / "oversight" / "requirements.txt"
GATE_PREFIX = "scripts.framework.new_code_gate"
STDLIB = set(sys.stdlib_module_names)
ROOT_MARKERS = {"__file__", "REPO_ROOT", "ROOT", "SOURCE_ROOT", "getcwd"}
PROTECTED_NAMES = {".git", ".claude"}


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_modules(tree):
    """Every module name imported anywhere in the tree, with the node's nesting depth."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            found.append(base)
            found.extend(f"{base}.{alias.name}" for alias in node.names)
    return found


def module_level_imports(tree):
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append("." * node.level + (node.module or ""))
    return names


def test_e2e_module_imports_no_gate_module():
    """S-E2E: the slow module only ever runs the gate as a subprocess."""
    offenders = [name for name in imported_modules(parse(E2E)) if name.startswith(GATE_PREFIX)]
    assert offenders == []
    assert {"importlib", "runpy"}.isdisjoint(
        name.split(".")[0] for name in imported_modules(parse(E2E))
    )


def test_gate_entry_module_is_stdlib_only_at_module_level():
    """S-STDLIB (static half): module-level imports are stdlib or the pure-logic module."""
    allowed = {f"{GATE_PREFIX}_logic", "scripts.framework"}
    offenders = []
    for name in module_level_imports(parse(FRAMEWORK / "new_code_gate.py")):
        top = name.split(".")[0]
        if top not in STDLIB and name not in allowed:
            offenders.append(name)
    assert offenders == []


def test_gate_entry_module_imports_with_only_the_stdlib_available():
    """S-STDLIB (dynamic half): no mutmut, libcst, coverage or pytest is needed to import the entry."""
    code = (
        "import sys\n"
        "import scripts.framework.new_code_gate\n"
        "heavy = sorted(m for m in sys.modules if m.split('.')[0] in "
        "('mutmut', 'libcst', 'coverage', 'pytest', '_pytest'))\n"
        "sys.exit(1 if heavy else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-E", "-S", "-c", code],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def is_real_cwd_call(node):
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "cwd"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "Path"
    )


def uses_repo_root(node):
    return any(
        (isinstance(n, ast.Name) and n.id in ROOT_MARKERS)
        or (isinstance(n, ast.Attribute) and n.attr in ROOT_MARKERS)
        or is_real_cwd_call(n)
        for n in ast.walk(node)
    )


def names_protected_path(node):
    return any(
        isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in PROTECTED_NAMES
        for n in ast.walk(node)
    )


@pytest.mark.parametrize("path", IN_PROCESS_TESTS, ids=lambda p: p.name)
def test_no_in_process_test_reads_the_real_git_or_claude(path):
    """G-NOGIT: a scope that names `.git`/`.claude` must not also be rooted at the real checkout."""
    tree = parse(path)
    scopes = [tree] if not any(isinstance(n, ast.FunctionDef) for n in tree.body) else []
    scopes += [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    offenders = [
        getattr(s, "name", "<module>")
        for s in scopes
        if names_protected_path(s) and uses_repo_root(s)
    ]
    assert offenders == []


GATE_SOURCE_MARKERS = ("new_code_gate", "shell_logic_check")
SOURCE_READERS = {"read_text", "read_bytes", "open", "getsource", "getsourcelines", "read_exact"}
GATE_ALIASES = {"ncg", "gate", "plugin"}
FOUR_GATE_TEST_MODULES = (
    TESTS / "framework" / "test_new_code_gate_logic.py",
    TESTS / "framework" / "test_new_code_gate_measure.py",
    TESTS / "framework" / "test_new_code_gate_plugin.py",
    E2E,
)


def is_gate_module_name(name):
    return name.startswith(GATE_PREFIX) or name.endswith("validators.shell_logic_check")


def names_from_gate_imports(tree):
    """Every local name bound by an import of a gate module or of something inside one."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if is_gate_module_name(module) or is_gate_module_name(f"{module}.{alias.name}"):
                    names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            names.update(
                (alias.asname or alias.name)
                for alias in node.names
                if is_gate_module_name(alias.name)
            )
    return names


def mentions_gate_source(node, path_names):
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if any(marker in n.value for marker in GATE_SOURCE_MARKERS):
                return True
        if isinstance(n, ast.Name) and n.id in path_names:
            return True
        if isinstance(n, ast.Attribute) and n.attr == "__file__":
            if isinstance(n.value, ast.Name) and n.value.id in GATE_ALIASES:
                return True
    return False


def gate_source_path_names(tree):
    """Module-level names assigned from an expression that names a gate file or a module's `__file__`."""
    return {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign) and mentions_gate_source(node.value, set())
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def reads_source(node):
    return any(
        isinstance(n, ast.Call)
        and (
            (isinstance(n.func, ast.Attribute) and n.func.attr in SOURCE_READERS)
            or (isinstance(n.func, ast.Name) and n.func.id in SOURCE_READERS)
        )
        for n in ast.walk(node)
    )


def reads_gate_source(node, imported, path_names):
    """A read of a gate file's text, or `inspect.getsource` of something a gate module defines."""
    names_a_file = reads_source(node) and mentions_gate_source(node, path_names)
    inspects_gate_code = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr.startswith("getsource")
        and any(
            (isinstance(a, ast.Name) and a.id in imported | GATE_ALIASES)
            or (
                isinstance(a, ast.Attribute)
                and isinstance(a.value, ast.Name)
                and a.value.id in imported | GATE_ALIASES
            )
            for a in n.args
        )
        for n in ast.walk(node)
    )
    return names_a_file or inspects_gate_code


def gate_code_calls(node, imported):
    return [
        n
        for n in ast.walk(node)
        if (
            isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id in GATE_ALIASES
        )
        or (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in imported)
    ]


@pytest.mark.parametrize("path", IN_PROCESS_TESTS + (E2E,), ids=lambda p: p.name)
def test_source_reading_gate_tests_run_no_gate_code(path):
    """G-SRCREAD (RV3-3a): a test that reads gate source in a workspace reads mutmut's copy and kills
    nothing, and a test that also runs gate code is selected for it. So a test does one or the other.
    """
    tree = parse(path)
    imported = names_from_gate_imports(tree)
    path_names = gate_source_path_names(tree)
    offenders = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("test_")
        and reads_gate_source(node, imported, path_names)
        and gate_code_calls(node, imported)
    ]
    assert offenders == []


def test_g_srcread_sees_what_it_is_meant_to_see():
    reader = ast.parse(
        "def test_a():\n    text = Path('scripts/framework/new_code_gate.py').read_text()\n"
        "    assert ncg.X in text\n"
    )
    clean = ast.parse(
        "def test_a():\n    text = Path('scripts/framework/new_code_gate.py').read_text()\n"
        "    assert 'ncg.X' in text\n"
    )
    other = ast.parse("def test_a():\n    assert ncg.X\n    Path('notes.txt').read_text()\n")
    called = ast.parse(
        "from scripts.framework.new_code_gate_logic import helper\n"
        "def test_a():\n    Path('new_code_gate.py').read_text()\n    helper()\n"
    )
    inspected = ast.parse(
        "from scripts.oversight.validators.shell_logic_check import decision_lines\n"
        "def test_a():\n    src = inspect.getsource(decision_lines)\n    decision_lines([])\n"
    )
    for tree, expected in (
        (reader, True),
        (clean, False),
        (other, False),
        (called, True),
        (inspected, True),
    ):
        func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        imported = names_from_gate_imports(tree)
        flagged = reads_gate_source(func, imported, set()) and bool(gate_code_calls(func, imported))
        assert flagged is expected


def config_assignments(tree):
    """(value node, line) of every assignment to a `_config` attribute, by `=` or by `setattr`."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            found.extend(
                (node.value, node.lineno)
                for t in node.targets
                if isinstance(t, ast.Attribute) and t.attr == "_config"
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute):
            if node.target.attr == "_config" and node.value is not None:
                found.append((node.value, node.lineno))
        elif isinstance(node, ast.Call) and len(node.args) >= 3:
            if isinstance(node.args[1], ast.Constant) and node.args[1].value == "_config":
                found.append((node.args[2], node.lineno))
    return found


def is_config_copy(value):
    """`copy.copy(<anything>.config())`."""
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "copy"
        and isinstance(value.func.value, ast.Name)
        and value.func.value.id == "copy"
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Call)
        and isinstance(value.args[0].func, ast.Attribute)
        and value.args[0].func.attr == "config"
    )


def allowed_config_values(tree):
    """Names bound by `copy.copy(...config())`, plus the saved original."""
    bound = {
        target.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and is_config_copy(node.value)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    return bound, {"saved"}


def refused_config_values(tree):
    bound, saved = allowed_config_values(tree)
    refused = []
    for value, line in config_assignments(tree):
        name = value.id if isinstance(value, ast.Name) else getattr(value, "attr", None)
        ok = (isinstance(value, ast.Name) and value.id in bound | saved) or (
            isinstance(value, ast.Attribute) and value.attr in saved
        )
        if not ok:
            refused.append((line, name or type(value).__name__))
    return refused


@pytest.mark.parametrize("path", FOUR_GATE_TEST_MODULES, ids=lambda p: p.name)
def test_no_gate_test_puts_a_non_config_in_mutmut_config(path):
    """G-MUTSTATE (RV3-3c): the stats run's trampoline reads `config()` on every gated call, so a
    sentinel in `mutmut.configuration._config` is a real `Config` copy, never `object()`."""
    assert refused_config_values(parse(path)) == []


def test_g_mutstate_refuses_what_it_should():
    def refused(code):
        return refused_config_values(ast.parse(code))

    assert refused("m._config = object()\n") == [(1, "Call")]
    assert refused("m._config = None\n") == [(1, "Constant")]
    assert refused("setattr(m, '_config', object())\n") == [(1, "Call")]
    assert refused("monkeypatch.setattr(m, '_config', 5)\n") == [(1, "Constant")]
    assert refused("s = copy.copy(m.config())\nm._config = s\nm._config = saved\n") == []
    assert refused("s = copy.copy(m.config())\nself.module._config = self.saved\n") == []
    assert refused("s = copy.copy(m.cfg())\nm._config = s\n") == [(2, "s")]
    assert refused("s = copy.deepcopy(m.config())\nm._config = s\n") == [(2, "s")]
    assert refused("m._config: object = object()\n") == [(1, "Call")]
    assert refused("m.other = object()\nx = 1\n") == []


@pytest.mark.parametrize("path", FOUR_GATE_TEST_MODULES, ids=lambda p: p.name)
def test_ws_integ_3_each_gate_test_module_starts_every_test_in_its_own_tmp_path(path):
    """RV3-7a: a mutant that makes a computed path relative writes into the test's tmp dir."""
    fixtures = [
        node
        for node in ast.walk(parse(path))
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(d, ast.Call)
            and ast.unparse(d.func) == "pytest.fixture"
            and any(
                k.arg == "autouse" and getattr(k.value, "value", None) is True for k in d.keywords
            )
            for d in node.decorator_list
        )
    ]
    changes_dir = [
        f.name
        for f in fixtures
        if any(
            isinstance(n, ast.Call)
            and ast.unparse(n.func) == "monkeypatch.chdir"
            and [ast.unparse(a) for a in n.args] == ["tmp_path"]
            for n in ast.walk(f)
        )
        and [a.arg for a in f.args.args] == ["tmp_path", "monkeypatch"]
    ]
    assert len(changes_dir) == 1


def collected_ids():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"]
        + ["-o", "addopts="]
        + [str(p.relative_to(ROOT)) for p in FOUR_GATE_TEST_MODULES + (Path(__file__).resolve(),)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    return [line for line in proc.stdout.splitlines() if "::" in line]


def test_every_gate_test_id_is_argv_safe_so_no_selection_widens_to_a_module():
    """`sanitize_node_ids` widens an id with whitespace to its module, which runs every test in it
    in every mutation workspace. Parameters made of code text need explicit ids."""
    ids = collected_ids()
    assert len(ids) > 500
    unsafe = [i for i in ids if not re.fullmatch(r"tests/[\w./\-]+\.py(::\S+)?", i)]
    assert unsafe == []


def gate_decorators():
    found = []
    for path in GATE_MODULES:
        for node in ast.walk(parse(path)):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and node.decorator_list
            ):
                found.append((path.name, node.name))
    return found


def test_gate_modules_use_no_decorators():
    """Decorated functions are unmutatable (mutmut skips them), so the gate has none."""
    assert gate_decorators() == []


SELF_CHECK = """
import json, sys
sys.path.insert(0, ".")
from pathlib import Path
from scripts.framework import new_code_gate_logic as ncg

out = {}
for rel in sys.argv[1:]:
    src = Path(rel).read_text(encoding="utf-8")
    findings = ncg.decision_logic_findings(src, ncg.statement_map(src)[0])
    out[rel] = [
        f for f in findings
        if (f["region"] in ("module", "class") and ncg.is_decision_logic(f))
        or (f["region"] == "function" and f["unmutatable_reason"])
    ]
print(json.dumps(out))
"""


def self_check(*paths):
    proc = subprocess.run(
        [sys.executable, "-c", SELF_CHECK, *[str(p.relative_to(ROOT)) for p in paths]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_gate_modules_have_no_uncarved_module_level_decision_logic():
    """Q5-SELF: the gate must satisfy the rule it enforces (REQ-35)."""
    failing = self_check(*GATE_MODULES)
    assert {rel: found for rel, found in failing.items() if found} == {}


def test_shell_logic_check_decision_logic_only_inside_its_main_guard():
    """Q5-SELF: any module-level decision logic in shell_logic_check.py sits in its final guard."""
    guard = parse(SHELL_CHECK).body[-1]
    assert isinstance(guard, ast.If) and ast.unparse(guard.test) == "__name__ == '__main__'"
    (found,) = self_check(SHELL_CHECK).values()
    assert all(guard.lineno <= f["node_line"] <= guard.end_lineno for f in found), found


def pinned_from_source():
    tree = parse(FRAMEWORK / "new_code_gate_logic.py")
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "PINNED" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("PINNED not found")


def test_requirements_pin_exactly_the_versions_the_gate_enforces():
    """R-PIN: requirements.txt and PINNED agree on all six tools (RV-1 added pytest-rerunfailures)."""
    pinned = pinned_from_source()
    assert sorted(pinned) == [
        "coverage",
        "libcst",
        "mutmut",
        "pytest",
        "pytest-cov",
        "pytest-rerunfailures",
    ]
    assert pinned["pytest-rerunfailures"] == "16.7"
    lines = [
        line.split("#")[0].strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    exact = dict(line.split("==") for line in lines if "==" in line)
    assert {tool: exact.get(tool) for tool in pinned} == pinned


RUN_TESTS = FRAMEWORK / "run_tests.sh"


def enclosing_function_names(tree, callee):
    """Name of the function (or `<module>`) that holds each call to `callee`."""
    found = []

    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, ast.FunctionDef) else scope
            if isinstance(child, ast.Call) and getattr(child.func, "id", "") == callee:
                found.append(scope)
            visit(child, inner)

    visit(tree, "<module>")
    return found


def test_only_measure_and_run_install_the_sigterm_handler():
    """RV-4: never at import, never in the hidden `_enumerate` / `_collect` children."""
    tree = parse(FRAMEWORK / "new_code_gate.py")
    assert sorted(enclosing_function_names(tree, "install_sigterm_handler")) == [
        "command_measure",
        "command_run",
    ]
    signal_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "signal.signal"
    ]
    assert len(signal_calls) == 1


def measured_sources_from_source():
    for node in parse(FRAMEWORK / "new_code_gate_logic.py").body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "MEASURED_SOURCES" for t in node.targets
        ):
            return list(ast.literal_eval(node.value))
    raise AssertionError("MEASURED_SOURCES not found")


def test_run_tests_sets_ctrace_contexts_and_split_report():
    """R-S1a: the exact S1 flags (TD 4.1) and the sidecar roots equal the --cov list."""
    lines = [line.strip() for line in RUN_TESTS.read_text(encoding="utf-8").splitlines()]
    text = "\n".join(lines)
    assert "export COVERAGE_CORE=ctrace" in lines
    assert [line.rstrip(" \\")[len("--cov=") :] for line in lines if line.startswith("--cov=")] == (
        measured_sources_from_source()
    )
    for flag in ("--cov-context=test \\", "--cov-report= \\"):
        assert flag in lines
    assert "--cov-fail-under" not in text
    assert (
        "--include='scripts/oversight/*,scripts/automation/lib/*,scripts/framework/*' \\" in lines
    )
    assert "--omit='*/test_*,*/__init__.py,*/conftest.py,*/.venv/*,*/__pycache__/*' \\" in lines
    assert "--fail-under=$COVERAGE_TARGET" in lines
    assert '"$REPO_ROOT" meta --coverage-file .coverage --out coverage-meta.json' in lines
    assert text.index("-m pytest") < text.index("-m coverage report") < text.index(" meta --cov")


def entry_snippet_from_source():
    for node in parse(FRAMEWORK / "new_code_gate_logic.py").body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "ENTRY_SNIPPET" for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("ENTRY_SNIPPET not found")


WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
NEW_JOBS = ("new-code-measure", "new-code-gate")
SNIPPET = entry_snippet_from_source()
# Marks a gate invocation in a folded `run:` line; the wrapper imports `main` from the gate module.
ENTRY = "from scripts.framework.new_code_gate import main"
WRAPPER_ARGS = "${{ github.workspace }}"
ACTION_PIN = re.compile(r"^actions/[a-z-]+@v\d+$")
OUT_ROOT = "${{ runner.temp }}/ncg-out"


def wrapper(python):
    return f'{python} -I -c "{SNIPPET}" {WRAPPER_ARGS}'


def workflow_text():
    return WORKFLOW.read_text(encoding="utf-8")


def workflow_jobs():
    return yaml.safe_load(workflow_text())["jobs"]


def steps_of(job):
    return workflow_jobs()[job]["steps"]


def step_using(job, action):
    (found,) = [s for s in steps_of(job) if str(s.get("uses", "")).startswith(action)]
    return found


def run_lines(job):
    """Each `run:` body of the job, folded onto one line with its whitespace collapsed."""
    return [" ".join(s["run"].split()) for s in steps_of(job) if "run" in s]


def test_tests_job_keeps_its_shape_and_uploads_the_coverage_contexts():
    """S1 (TD 4.3): the required `tests` job is unchanged except for the upload step."""
    job = workflow_jobs()["tests"]
    assert job["name"] == "tests"
    assert job["timeout-minutes"] == 30
    checkout = job["steps"][0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert "ref" not in checkout["with"]  # the default checkout IS github.sha (the merge commit)
    assert any(s.get("run") == "bash scripts/framework/run_tests.sh" for s in job["steps"])
    upload = job["steps"][-1]
    assert upload["uses"].startswith("actions/upload-artifact@v4")
    assert upload["with"]["name"] == "coverage-contexts"
    assert upload["with"]["path"].split() == [".coverage", "coverage-meta.json"]
    assert upload["with"]["retention-days"] == 7
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["include-hidden-files"] is True
    assert upload["with"]["overwrite"] is True


def test_workflow_permissions_stay_read_only_everywhere():
    """No write token and no pull-requests: read until S5 (TD 5.17)."""
    data = yaml.safe_load(workflow_text())
    assert data["permissions"] == {"contents": "read"}
    for name, job in data["jobs"].items():
        assert job.get("permissions", {"contents": "read"}) == {"contents": "read"}, name


def test_new_jobs_exist_with_the_designed_names_needs_and_timeouts():
    jobs = workflow_jobs()
    measure, gate = jobs["new-code-measure"], jobs["new-code-gate"]
    assert (measure["name"], measure["needs"], measure["timeout-minutes"]) == (
        "new-code-measure",
        "tests",
        30,
    )
    assert (gate["name"], gate["needs"], gate["timeout-minutes"]) == (
        "new-code-gate",
        "new-code-measure",
        5,
    )


@pytest.mark.parametrize("job", NEW_JOBS)
def test_new_jobs_if_always(job):
    """AC-30: a skipped required check counts as a pass, so neither job may be skipped."""
    assert workflow_jobs()[job]["if"] == "always()"


def test_new_jobs_pass_the_upstream_result_to_the_gate_to_judge():
    """The needs-result check lives in Python (H1), so a skipped upstream cannot pass."""
    (measure_cmd,) = [c for c in run_lines("new-code-measure") if ENTRY in c]
    (gate_cmd,) = [c for c in run_lines("new-code-gate") if ENTRY in c]
    assert "--tests-result ${{ needs.tests.result }}" in measure_cmd
    assert "--measure-result ${{ needs.new-code-measure.result }}" in gate_cmd


@pytest.mark.parametrize("job", NEW_JOBS)
def test_new_jobs_checkout_github_sha_without_credentials(job):
    """AR-1d: the merge commit is named explicitly, and no token is left in the clone."""
    checkout = step_using(job, "actions/checkout@")
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["fetch-depth"] == (0 if job == "new-code-measure" else 1)


def test_new_jobs_pass_gated_sha_and_pr_head_and_no_base_sha():
    (cmd,) = [c for c in run_lines("new-code-measure") if ENTRY in c]
    assert "--gated-sha ${{ github.sha }}" in cmd
    assert "--pr-head-sha ${{ github.event.pull_request.head.sha }}" in cmd
    assert "--base-sha" not in cmd
    assert "--base-sha" not in workflow_text()


def test_ci_invokes_only_measure_and_verdict_entry_points():
    """AC-30: no shell wrapper (it would itself be gated shell); only measure and verdict."""
    phases = {"new-code-measure": "measure", "new-code-gate": "verdict"}
    for job, phase in phases.items():
        gate_lines = [c for c in run_lines(job) if "new_code_gate" in c]
        assert len(gate_lines) == 1, job
        assert re.search(rf'" {re.escape(WRAPPER_ARGS)} {phase}( |$)', gate_lines[0]), gate_lines[0]
        for other in {"measure", "verdict", "run", "meta", "_enumerate", "_collect"} - {phase}:
            assert f"{WRAPPER_ARGS} {other} " not in gate_lines[0]
    text = workflow_text()
    assert "new_code_gate.sh" not in text
    assert len(re.findall(r"new_code_gate import", text.split("\njobs:\n", 1)[1])) == 2


def test_new_jobs_shell_lines_are_only_the_designed_ones():
    """Only the venv build, the gate call and the one-line summary append run as shell."""
    allowed = {
        "new-code-measure": [
            "bash scripts/oversight/ensure_venv.sh",
            "scripts/oversight/.venv/bin/python",
        ],
        "new-code-gate": [
            wrapper("python") + " verdict",
            "cat ",
        ],
    }
    for job, prefixes in allowed.items():
        lines = run_lines(job)
        assert len(lines) == len(prefixes), lines
        assert all(line.startswith(p) for line, p in zip(lines, prefixes)), lines
    (append,) = [c for c in run_lines("new-code-gate") if c.startswith("cat ")]
    assert append == f'cat "{OUT_ROOT}/new-code-summary.md" >> "$GITHUB_STEP_SUMMARY"'
    assert "&&" not in append and ";" not in append


def test_gate_job_uses_system_python_and_measure_uses_the_venv():
    (measure_cmd,) = [c for c in run_lines("new-code-measure") if ENTRY in c]
    (gate_cmd,) = [c for c in run_lines("new-code-gate") if ENTRY in c]
    assert measure_cmd.startswith(wrapper("scripts/oversight/.venv/bin/python") + " measure ")
    assert gate_cmd.startswith(wrapper("python") + " verdict ")
    assert not any("ensure_venv" in c for c in run_lines("new-code-gate"))


def test_wf_entry_no_step_runs_the_gate_with_dash_m_or_without_isolation():
    """WF-ENTRY (RV2-1): every gate invocation is the `-I -c ENTRY_SNIPPET <root>` wrapper, byte for byte.

    A `-m` run (or any run without `-I`) puts the checkout root first on sys.path, so a
    PR-added `json.py` or `scripts/__init__.py` would run inside the gate process.
    """
    run_tests = RUN_TESTS.read_text(encoding="utf-8")
    texts = [workflow_text(), run_tests]
    for text in texts:
        assert "-m scripts.framework.new_code_gate" not in text
    folded = " ".join(workflow_text().split())
    invocations = [c for job in workflow_jobs() for c in run_lines(job) if "new_code_gate" in c] + [
        " ".join(line.split()) for line in run_tests.splitlines() if "new_code_gate import" in line
    ]
    assert len(invocations) == 3
    for command in invocations:
        python, rest = command.split(" -I -c ", 1)
        assert python.endswith("python") or python.endswith('"$VENV_PYTHON"'), command
        assert rest.startswith(f'"{SNIPPET}" '), command
        assert command.count("new_code_gate import") == 1
    assert folded.count(f'"{SNIPPET}"') == 2
    assert run_tests.count(f'-I -c "{SNIPPET}"') == 1
    assert SNIPPET.endswith("sys.exit(main(sys.argv[2:]))")


def test_new_code_gate_job_steps_are_exactly_the_inv_g_whitelist():
    """INV-G: the job that decides runs no PR-controlled build step (no venv, pip, or repo script)."""
    steps = steps_of("new-code-gate")
    kinds = [str(s.get("uses", "")).split("@")[0] or s["name"] for s in steps]
    assert kinds == [
        "actions/checkout",
        "actions/setup-python",
        "actions/download-artifact",
        "Apply thresholds",
        "Publish step summary",
        "actions/upload-artifact",
    ]
    text = " ".join(run_lines("new-code-gate"))
    assert "pip" not in text and "bash scripts/" not in text and "ensure_venv" not in text


def test_summary_step_and_verdict_artifact_run_even_when_the_gate_fails():
    steps = steps_of("new-code-gate")
    summary = [s for s in steps if str(s.get("run", "")).startswith("cat ")]
    upload = step_using("new-code-gate", "actions/upload-artifact@")
    assert [s["if"] for s in summary] == ["always()"]
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "new-code-verdict"
    assert upload["with"]["path"].splitlines() == [
        f"{OUT_ROOT}/new-code-verdict.json",
        f"{OUT_ROOT}/new-code-summary.md",
    ]
    assert upload["with"]["retention-days"] == 90


def test_records_artifact_is_uploaded_always_and_kept_90_days():
    upload = step_using("new-code-measure", "actions/upload-artifact@")
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "new-code-records"
    assert upload["with"]["path"] == f"{OUT_ROOT}/new-code-records.json"
    assert upload["with"]["retention-days"] == 90


@pytest.mark.parametrize(
    ("job", "name"),
    [("new-code-measure", "coverage-contexts"), ("new-code-gate", "new-code-records")],
)
def test_downloads_tolerate_a_missing_artifact_so_the_gate_reports_it(job, name):
    download = step_using(job, "actions/download-artifact@")
    assert download["continue-on-error"] is True
    assert download["with"]["name"] == name


INPUT_ROOT = "${{ runner.temp }}/ncg-in"


def flag_values(command, flag):
    """Every value that follows `flag` in a folded command line (an expression is one value)."""
    value = r"(\$\{\{ [^}]+ \}\}\S*|\S+)"
    return re.findall(rf"(?:^| ){re.escape(flag)} {value}", command)


def test_downloads_land_in_fresh_directories_under_runner_temp():
    """RV-7: no artifact is downloaded into the checkout, where PR code can pre-place files."""
    paths = {
        "new-code-measure": f"{INPUT_ROOT}/coverage",
        "new-code-gate": f"{INPUT_ROOT}/records",
    }
    for job, expected in paths.items():
        download = step_using(job, "actions/download-artifact@")
        assert download["with"]["path"] == expected, job
        assert expected.startswith("${{ runner.temp }}/")


def test_no_gate_input_path_is_checkout_relative():
    """RV-7: the coverage data, sidecar and records are read from the download directories only."""
    (measure_cmd,) = [c for c in run_lines("new-code-measure") if ENTRY in c]
    (gate_cmd,) = [c for c in run_lines("new-code-gate") if ENTRY in c]
    assert flag_values(measure_cmd, "--coverage-file") == [f"{INPUT_ROOT}/coverage/.coverage"]
    assert flag_values(measure_cmd, "--meta") == [f"{INPUT_ROOT}/coverage/coverage-meta.json"]
    assert flag_values(gate_cmd, "--records-dir") == [f"{INPUT_ROOT}/records"]
    assert "--records " not in gate_cmd
    inputs = [
        *flag_values(measure_cmd, "--coverage-file"),
        *flag_values(measure_cmd, "--meta"),
        *flag_values(gate_cmd, "--records-dir"),
    ]
    assert inputs and all(p.startswith("${{ runner.temp }}/") for p in inputs)
    assert flag_values(measure_cmd, "--out") == [f"{OUT_ROOT}/new-code-records.json"]
    assert flag_values(gate_cmd, "--out") == [f"{OUT_ROOT}/new-code-verdict.json"]
    assert flag_values(gate_cmd, "--summary") == [f"{OUT_ROOT}/new-code-summary.md"]


def test_verdict_is_passed_all_four_binding_values_and_each_measure_value():
    """RV-7: gated SHA, PR number, run ID and run attempt, exactly as the platform states them."""
    (gate_cmd,) = [c for c in run_lines("new-code-gate") if ENTRY in c]
    assert flag_values(gate_cmd, "--gated-sha") == ["${{ github.sha }}"]
    assert flag_values(gate_cmd, "--pr") == ["${{ github.event.pull_request.number }}"]
    assert flag_values(gate_cmd, "--run-id") == ["${{ github.run_id }}"]
    assert flag_values(gate_cmd, "--run-attempt") == ["${{ github.run_attempt }}"]
    (measure_cmd,) = [c for c in run_lines("new-code-measure") if ENTRY in c]
    assert flag_values(measure_cmd, "--run-id") == ["${{ github.run_id }}"]
    assert flag_values(measure_cmd, "--run-attempt") == ["${{ github.run_attempt }}"]
    assert flag_values(measure_cmd, "--pr") == ["${{ github.event.pull_request.number }}"]


def test_every_upload_replaces_an_earlier_attempts_artifact():
    """RV-5: a re-run of one job must not fail on a same-name artifact from an earlier attempt."""
    uploads = [
        (job, step)
        for job, body in workflow_jobs().items()
        for step in body["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert sorted(step["with"]["name"] for _job, step in uploads) == [
        "coverage-contexts",
        "new-code-records",
        "new-code-verdict",
    ]
    assert all(step["with"]["overwrite"] is True for _job, step in uploads)


def test_the_new_jobs_stay_read_only_and_run_even_when_upstream_fails():
    """RV-5/7 keep the TD 5.17 shape: contents: read, `if: always()`, explicit upstream results."""
    jobs = workflow_jobs()
    for job in NEW_JOBS:
        assert jobs[job].get("permissions") == {"contents": "read"}
        assert jobs[job]["if"] == "always()"
    assert "secrets." not in workflow_text()


def test_no_cache_in_gate_jobs_or_code():
    """AC-25: nothing is cached, so a poisoned cache cannot reach the verdict."""
    assert "actions/cache" not in workflow_text()
    for path in GATE_MODULES:
        assert "actions/cache" not in path.read_text(encoding="utf-8")


def test_workflow_has_no_privileged_trigger_secrets_or_unpinned_actions():
    data = yaml.safe_load(workflow_text())
    triggers = data.get("on", data.get(True))  # YAML 1.1 reads a bare `on` as True
    assert set(triggers) == {"pull_request"}
    assert "secrets." not in workflow_text()
    uses = [s["uses"] for job in workflow_jobs().values() for s in job["steps"] if "uses" in s]
    assert uses and all(ACTION_PIN.match(u) for u in uses), uses


# --------------------------------------------------------------------------
# SHADOW-1/2, SHADOW-CTRL, VER-IMPORTS, SLC-PATH: a planted file never runs (RV2-1, RV2-2a)
# --------------------------------------------------------------------------

SHA = "a" * 40
PLANTED_MODULES = ("json", "argparse", "re", "coverage", "mutmut", "libcst", "sitecustomize")
GATE_FILES = ("new_code_gate.py", "new_code_gate_logic.py")
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}
RECORDS_WRITER = """
import sys
sys.path.insert(0, sys.argv[1])
import json
from scripts.framework import new_code_gate_logic as ncg
sha, out = sys.argv[2], sys.argv[3]
rec = ncg.blank_file_record("scripts/x.py", "new")
rec["fail_reasons"] = [ncg.fail_reason("mode_not_gateable", ncg.mode_message("160000"))]
doc = {
    "schema": ncg.SCHEMA_RECORDS, "gate_version": ncg.GATE_VERSION, "phase": "measure",
    "mode": "ci", "pr": 7, "gated_sha": sha, "pr_head_sha": sha, "base_sha": None,
    "gated_tree": None, "run_id": "99", "run_attempt": 1, "tool_versions": {}, "python": "3.12",
    "coverage_core": None, "budget_seconds": ncg.BUDGET_SECONDS,
    "thresholds": dict(ncg.THRESHOLDS), "files": [rec], "internal_errors": [],
    "records_sha256": ncg.records_sha256([rec]), "started_at": "s", "finished_at": "f",
    "seconds": 0,
}
open(out, "w").write(json.dumps(doc))
"""


def plant(directory, markers):
    """Root-level files that write a marker and exit 0 if anything imports or runs them."""
    markers.mkdir(parents=True, exist_ok=True)
    names = {f"{name}.py": f"m_{name}" for name in PLANTED_MODULES}
    names["scripts/__init__.py"] = "m_scripts_init"
    for rel, marker in names.items():
        path = directory / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        body = f"import os\nopen({str(markers / marker)!r}, 'w').close()\nos._exit(0)\n"
        path.write_text(body, encoding="utf-8")


def fixture_checkout(tmp_path):
    """A checkout holding only the two gate modules, plus every planted shadow."""
    root = tmp_path / "checkout"
    (root / "scripts" / "framework").mkdir(parents=True)
    for name in GATE_FILES:
        shutil.copy(FRAMEWORK / name, root / "scripts" / "framework" / name)
    markers = tmp_path / "markers"
    plant(root, markers)
    return root, markers


def child_env():
    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


def run(argv, cwd, env=None):
    return subprocess.run(
        argv, cwd=cwd, env=env or child_env(), capture_output=True, text=True, timeout=120
    )


def bound_records(tmp_path):
    records = tmp_path / "runner" / "ncg-in" / "records" / "new-code-records.json"
    records.parent.mkdir(parents=True)
    argv = [sys.executable, "-I", "-c", RECORDS_WRITER, str(ROOT), SHA, str(records)]
    proc = run(argv, tmp_path)
    assert proc.returncode == 0, proc.stderr
    return records


def literal_verdict_argv(tmp_path, root):
    """The 'Apply thresholds' command exactly as tests.yml spells it, with its expressions filled in."""
    values = {
        "github.workspace": str(root),
        "runner.temp": str(tmp_path / "runner"),
        "github.sha": SHA,
        "github.event.pull_request.number": "7",
        "github.run_id": "99",
        "github.run_attempt": "1",
        "needs.new-code-measure.result": "success",
    }
    (step,) = [s for s in steps_of("new-code-gate") if s["name"] == "Apply thresholds"]
    text = re.sub(
        r"\$\{\{ ([^}]+) \}\}", lambda m: values[m.group(1)], " ".join(step["run"].split())
    )
    argv = shlex.split(text)
    assert argv[:3] == ["python", "-I", "-c"] and argv[3] == SNIPPET
    return [sys.executable, *argv[1:]]


def markers_written(markers):
    return sorted(p.name for p in markers.iterdir())


def test_shadow_1_planted_root_modules_are_not_imported_by_the_workflows_verdict_command(tmp_path):
    root, markers = fixture_checkout(tmp_path)
    bound_records(tmp_path)
    proc = run(literal_verdict_argv(tmp_path, root), root)
    assert (proc.returncode, markers_written(markers)) == (1, []), proc.stderr
    out = tmp_path / "runner" / "ncg-out"
    verdict = json.loads((out / "new-code-verdict.json").read_text(encoding="utf-8"))
    assert verdict["overall"] == "fail"
    assert "mode_not_gateable" in (out / "new-code-summary.md").read_text(encoding="utf-8")


def test_shadow_ctrl_the_dash_m_form_does_trip_the_same_fixture(tmp_path):
    """SHADOW-CTRL: without this, SHADOW-1 could pass because the fixture plants nothing that bites."""
    root, markers = fixture_checkout(tmp_path)
    bound_records(tmp_path)
    argv = literal_verdict_argv(tmp_path, root)
    dash_m = [argv[0], "-m", "scripts.framework.new_code_gate", *argv[argv.index("verdict") :]]
    proc = run(dash_m, root)
    assert proc.returncode == 0 and markers_written(markers) != [], proc.stderr


def test_ver_imports_the_verdict_process_loads_only_stdlib_and_the_gate_modules(tmp_path):
    root, markers = fixture_checkout(tmp_path)
    bound_records(tmp_path)
    argv = literal_verdict_argv(tmp_path, root)
    dump = tmp_path / "modules.txt"
    tail = "sys.exit(main(sys.argv[2:]))"
    report = f"rc = main(sys.argv[2:]); open({str(dump)!r}, 'w').write(' '.join(sorted(sys.modules))); sys.exit(rc)"
    assert argv[3].endswith(tail)
    argv[3] = argv[3].replace(tail, report)
    proc = run(argv, root)
    assert (proc.returncode, markers_written(markers)) == (1, []), proc.stderr
    baseline = run([sys.executable, "-I", "-c", "import sys; print(' '.join(sys.modules))"], root)
    allowed_gate = {"scripts", "scripts.framework"} | {
        f"scripts.framework.{n[:-3]}" for n in GATE_FILES
    }
    allowed = set(baseline.stdout.split()) | allowed_gate | {"__main__"}
    loaded = dump.read_text(encoding="utf-8").split()
    foreign = [
        m for m in loaded if m not in allowed and m.split(".")[0] not in sys.stdlib_module_names
    ]
    assert foreign == []
    assert allowed_gate <= set(loaded)
    assert {"coverage", "mutmut", "libcst", "pytest"}.isdisjoint(loaded)


def test_ver_imports_the_children_still_resolve_mutmut_libcst_and_pytest_from_site_packages(
    tmp_path,
):
    """The `-I -c` child form keeps the venv's site-packages and drops every checkout path."""
    root, markers = fixture_checkout(tmp_path)
    code = "import libcst, mutmut, pytest, coverage; print(libcst.__file__, mutmut.__file__)"
    proc = run([sys.executable, "-I", "-c", code], root)
    assert proc.returncode == 0 and markers_written(markers) == [], proc.stderr
    assert str(root) not in proc.stdout


def git_commit_all(directory):
    env = {**child_env(), **GIT_IDENTITY}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
        proc = run(["git", *args], directory, env)
        assert proc.returncode == 0, proc.stderr


def run_tests_meta_argv(root):
    """The `meta` call in run_tests.sh, with its two shell variables filled in."""
    lines = RUN_TESTS.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if "new_code_gate import main" in line)
    command = lines[start].strip().rstrip("\\") + " " + lines[start + 1].strip()
    values = {"$VENV_PYTHON": sys.executable, "$REPO_ROOT": str(root)}
    argv = [values.get(token, token) for token in shlex.split(command)]
    assert argv[1:4] == ["-I", "-c", SNIPPET]
    return argv


def test_shadow_2_the_run_tests_meta_form_ignores_planted_files(tmp_path):
    root, markers = fixture_checkout(tmp_path)
    (root / ".coverage").write_bytes(b"")
    git_commit_all(root)
    proc = run(run_tests_meta_argv(root), root)
    assert (proc.returncode, markers_written(markers)) == (0, []), proc.stderr
    meta = json.loads((root / "coverage-meta.json").read_text(encoding="utf-8"))
    assert meta["checkout_root"] == str(root.resolve())


def child_fixture(tmp_path, root):
    """A workspace (the child's cwd) holding a mutmut config for x.py and the same planted files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text('[tool.mutmut]\nonly_mutate = ["x.py"]\n', "utf-8")
    plant(workspace, tmp_path / "markers")
    return workspace


def test_shadow_2_a_child_phase_resolves_real_mutmut_and_runs_no_planted_file(tmp_path):
    root, markers = fixture_checkout(tmp_path)
    workspace = child_fixture(tmp_path, root)
    argv = [sys.executable, "-I", "-c", SNIPPET, str(root), "_collect", "--file", "x.py"]
    proc = run(argv, workspace)
    assert markers_written(markers) == [], proc.stderr
    assert proc.returncode == 3 and "mutmut wrote no meta file for x.py" in proc.stderr


def test_shadow_ctrl_the_old_child_form_ran_planted_files_from_the_workspace(tmp_path):
    root, markers = fixture_checkout(tmp_path)
    workspace = child_fixture(tmp_path, root)
    old = [sys.executable, "-m", "scripts.framework.new_code_gate", "_collect", "--file", "x.py"]
    proc = run(old, workspace, {**child_env(), "PYTHONPATH": str(root)})
    assert markers_written(markers) != [] and proc.returncode == 0, proc.stderr


def validators_fixture(tmp_path):
    """Gate modules plus a copy of the validators package, with a planted `coverage.py` inside it."""
    root, markers = fixture_checkout(tmp_path)
    oversight = ROOT / "scripts" / "oversight"
    target = root / "scripts" / "oversight"
    target.mkdir()
    if (oversight / "__init__.py").exists():
        shutil.copy(oversight / "__init__.py", target / "__init__.py")
    shutil.copytree(
        oversight / "validators",
        target / "validators",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    body = (
        f"import os\nopen({str(markers / 'm_validators_coverage')!r}, 'w').close()\nos._exit(0)\n"
    )
    (target / "validators" / "coverage.py").write_text(body, encoding="utf-8")
    return root, markers


SLC_PROBE = """
import os, sys, types
r = os.path.realpath(sys.argv[1])
p = types.ModuleType('scripts'); p.__path__ = [os.path.join(r, 'scripts')]; sys.modules['scripts'] = p
from scripts.framework import new_code_gate as gate
before = list(sys.path)
if sys.argv[2] == 'restore':
    gate.load_shell_rules()
else:
    from scripts.oversight.validators.shell_logic_check import decision_lines
print('PATH_RESTORED' if sys.path == before else 'PATH_CHANGED', flush=True)
import coverage
print(coverage.__file__)
"""


def test_slc_path_the_shell_rules_import_leaves_sys_path_as_it_found_it(tmp_path):
    root, markers = validators_fixture(tmp_path)
    proc = run([sys.executable, "-I", "-c", SLC_PROBE, str(root), "restore"], root)
    assert markers_written(markers) == [], proc.stderr
    assert proc.stdout.split()[0] == "PATH_RESTORED"
    assert str(root) not in proc.stdout.split()[1]


def test_slc_path_control_the_unrestored_import_does_let_a_later_import_resolve_there(tmp_path):
    root, markers = validators_fixture(tmp_path)
    proc = run([sys.executable, "-I", "-c", SLC_PROBE, str(root), "plain"], root)
    assert markers_written(markers) == ["m_validators_coverage"], proc.stderr
    assert proc.stdout.split()[0] == "PATH_CHANGED"
