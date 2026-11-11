"""Static conditions on the new-code gate that need no real run (#2304, TD 9.3, REQ-35).

Includes the static checks of .github/workflows/tests.yml (S2d). Everything here reads source text
or runs a fresh interpreter: it imports **no** gate module in process, so these checks neither
depend on nor earn coverage for the code they guard.
"""

import ast
import json
import re
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
    assert "--coverage-file .coverage --out coverage-meta.json" in lines
    assert (
        text.index("-m pytest")
        < text.index("-m coverage report")
        < text.index("-m scripts.framework.new_code_gate meta")
    )


WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
NEW_JOBS = ("new-code-measure", "new-code-gate")
ENTRY = "-m scripts.framework.new_code_gate"
ACTION_PIN = re.compile(r"^actions/[a-z-]+@v\d+$")


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
        assert re.search(rf"{ENTRY} {phase}( |$)", gate_lines[0]), gate_lines[0]
        for other in {"measure", "verdict", "run", "meta", "_enumerate", "_collect"} - {phase}:
            assert f"{ENTRY} {other}" not in gate_lines[0]
    text = workflow_text()
    assert "new_code_gate.sh" not in text
    assert len(re.findall(r"new_code_gate", text.split("\njobs:\n", 1)[1])) == 2


def test_new_jobs_shell_lines_are_only_the_designed_ones():
    """Only the venv build, the gate call and the one-line summary append run as shell."""
    allowed = {
        "new-code-measure": [
            "bash scripts/oversight/ensure_venv.sh",
            "scripts/oversight/.venv/bin/python",
        ],
        "new-code-gate": [
            "python -m scripts.framework.new_code_gate verdict",
            "cat new-code-summary.md",
        ],
    }
    for job, prefixes in allowed.items():
        lines = run_lines(job)
        assert len(lines) == len(prefixes), lines
        assert all(line.startswith(p) for line, p in zip(lines, prefixes)), lines
    (append,) = [c for c in run_lines("new-code-gate") if c.startswith("cat ")]
    assert append == 'cat new-code-summary.md >> "$GITHUB_STEP_SUMMARY"'
    assert "&&" not in append and ";" not in append


def test_gate_job_uses_system_python_and_measure_uses_the_venv():
    (measure_cmd,) = [c for c in run_lines("new-code-measure") if ENTRY in c]
    (gate_cmd,) = [c for c in run_lines("new-code-gate") if ENTRY in c]
    assert measure_cmd.startswith("scripts/oversight/.venv/bin/python " + ENTRY)
    assert gate_cmd.startswith("python " + ENTRY)
    assert not any("ensure_venv" in c for c in run_lines("new-code-gate"))


def test_summary_step_and_verdict_artifact_run_even_when_the_gate_fails():
    steps = steps_of("new-code-gate")
    summary = [s for s in steps if str(s.get("run", "")).startswith("cat ")]
    upload = step_using("new-code-gate", "actions/upload-artifact@")
    assert [s["if"] for s in summary] == ["always()"]
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "new-code-verdict"
    assert upload["with"]["path"].split() == ["new-code-verdict.json", "new-code-summary.md"]
    assert upload["with"]["retention-days"] == 90


def test_records_artifact_is_uploaded_always_and_kept_90_days():
    upload = step_using("new-code-measure", "actions/upload-artifact@")
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "new-code-records"
    assert upload["with"]["path"] == "new-code-records.json"
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
    for output in (*flag_values(measure_cmd, "--out"), *flag_values(gate_cmd, "--out")):
        assert "/" not in output
    assert flag_values(gate_cmd, "--summary") == ["new-code-summary.md"]


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
