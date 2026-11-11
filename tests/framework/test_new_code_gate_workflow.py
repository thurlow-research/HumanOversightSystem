"""Static conditions on the new-code gate that need no real run (#2304, TD 9.3, REQ-35).

Commit 6 adds the workflow-YAML cases to this module. Everything here reads source text or runs a
fresh interpreter: it imports **no** gate module in process, so these checks neither depend on nor
earn coverage for the code they guard.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

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
    """R-PIN: requirements.txt and PINNED agree on all five tools."""
    pinned = pinned_from_source()
    lines = [
        line.split("#")[0].strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    exact = dict(line.split("==") for line in lines if "==" in line)
    assert {tool: exact.get(tool) for tool in pinned} == pinned


RUN_TESTS = FRAMEWORK / "run_tests.sh"


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
    assert "--coverage-file .coverage --out coverage-meta.json" in lines
    assert (
        text.index("-m pytest")
        < text.index("-m coverage report")
        < text.index("-m scripts.framework.new_code_gate meta")
    )
