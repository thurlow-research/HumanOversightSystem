"""End-to-end runs of the new-code gate with real coverage and real mutmut (#2304, TD 9.1, 5.19).

The CLI runs as a **subprocess** on a fixture repository that carries its own copy of the three
gate modules. This module imports no `scripts.framework.new_code_gate*` module, in process or
otherwise (ADR-2304 section 2b condition 4, static test S-E2E): that is what keeps these slow
tests out of every coverage-context selection, so real mutmut is never nested inside a per-mutant
run and these tests can neither multiply mutation cost nor earn coverage for the gate.

Each case needs real mutmut, which forks workers and uses multiprocessing primitives. They carry
the repo's `slow` marker and nothing else: the required `tests` job runs `tests/` whole, so a
broken mutmut fails there rather than being skipped.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path, monkeypatch):
    """A relative path in a test lands in its tmp dir, never in the developer's checkout (RV3-7a)."""
    monkeypatch.chdir(tmp_path)


SOURCE_ROOT = Path(__file__).resolve().parents[2]
GATE_FILES = (
    "scripts/__init__.py",
    "scripts/framework/new_code_gate.py",
    "scripts/framework/new_code_gate_logic.py",
    "scripts/framework/new_code_gate_shard.py",
    "scripts/framework/new_code_gate_pytest_plugin.py",
)
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}
PYPROJECT = """[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "--tb=short -q --strict-markers"
markers = ["repo_copy: copies the repository root"]

[tool.coverage.run]
branch = true
"""
CALC = """def add(a, b):
    return a + b


def scale(x):
    return x * 2 + 1


def sign(n):
    if n > 0:
        return "pos"
    if n < 0:
        return "neg"
    return "zero"
"""
STRONG_TESTS = """from bootstrap.calc import add, scale, sign


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0


def test_scale():
    assert scale(3) == 7
    assert scale(0) == 1


def test_sign():
    assert sign(5) == "pos"
    assert sign(1) == "pos"
    assert sign(-5) == "neg"
    assert sign(-1) == "neg"
    assert sign(0) == "zero"
"""
UNRELATED_TEST = "def test_unrelated():\n    assert 1 + 1 == 2\n"
CALC_PATH = "bootstrap/calc.py"
FEATURE_COVERAGE_ARGS = ["--cov=scripts", "--cov=bootstrap", "--cov-context=test", "--cov-report="]


def git(repo, *args):
    proc = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        env=dict(os.environ, **GIT_ENV),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def write(repo, rel, text):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def clean_env(tmp_path, **extra):
    env = {
        k: v for k, v in os.environ.items() if not k.startswith(("NCG_", "COVERAGE_", "PYTEST_"))
    }
    tmp = tmp_path / "tmp"
    tmp.mkdir(exist_ok=True)
    env.update(TMPDIR=str(tmp), COVERAGE_CORE="ctrace", **extra)
    return env


def build_fixture(tmp_path, tests, calc=CALC, extra_pr_files=None, base_extra=None):
    """A repo whose base commit holds the gate and whose feature commit adds `bootstrap/calc.py`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    for rel in GATE_FILES:
        write(repo, rel, (SOURCE_ROOT / rel).read_text(encoding="utf-8"))
    write(repo, "pyproject.toml", PYPROJECT)
    write(repo, "README.md", "fixture\n")
    for rel, text in (base_extra or {}).items():
        write(repo, rel, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "feature")
    write(repo, CALC_PATH, calc)
    for rel, text in {**tests, **(extra_pr_files or {})}.items():
        write(repo, rel, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "feature")
    return repo


def measure_coverage(repo, tmp_path, **extra_env):
    """What the `tests` job does: run the suite (with `--reruns 1`) with contexts, then write the sidecar."""
    env = clean_env(tmp_path, **extra_env)
    argv = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--reruns", "1"]
    argv += FEATURE_COVERAGE_ARGS
    proc = subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    meta = [sys.executable, "-m", "scripts.framework.new_code_gate", "meta"]
    (repo / "test-durations.json").write_text("{}", encoding="utf-8")
    proc = subprocess.run(
        [*meta, "--coverage-file", ".coverage", "--out", "coverage-meta.json"]
        + ["--durations", "test-durations.json"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def run_gate(repo, tmp_path, keep=False):
    argv = [sys.executable, "-m", "scripts.framework.new_code_gate", "run", "--base", "main"]
    if keep:
        argv.append("--keep-workspace")
    proc = subprocess.run(
        argv,
        cwd=repo,
        env=clean_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    written = re.search(r"records and verdict written to (\S+)", proc.stderr)
    records = verdict = None
    if written:
        out_dir = Path(written.group(1))
        records = json.loads((out_dir / "new-code-records.json").read_text(encoding="utf-8"))
        verdict = json.loads((out_dir / "new-code-verdict.json").read_text(encoding="utf-8"))
    return proc, records, verdict


def file_record(doc, path=CALC_PATH):
    return next(f for f in doc["files"] if f["path"] == path)


def reason_codes(rec):
    return [r["code"] for r in rec["fail_reasons"]]


def explain(proc):
    return f"exit {proc.returncode}\n--- stdout\n{proc.stdout}\n--- stderr\n{proc.stderr}"


def test_pr_meeting_all_targets_passes(tmp_path):
    repo = build_fixture(tmp_path, {"tests/test_calc.py": STRONG_TESTS})
    measure_coverage(repo, tmp_path)
    proc, records, verdict = run_gate(repo, tmp_path)
    assert proc.returncode == 0, explain(proc)
    rec = file_record(verdict)
    assert rec["outcome"] == "pass" and rec["fail_reasons"] == [], explain(proc)
    assert rec["kind"] == "new" and rec["mutation_ran"] is True
    assert rec["mutants_total"] >= 6 and rec["mutant_score_pct"] >= 75.0
    assert rec["gated_statements"] == rec["executed_gated"] > 0
    assert rec["selection_method"] == "context" and rec["selected_tests"]
    assert records["internal_errors"] == [] and verdict["overall"] == "pass"
    assert f"| {CALC_PATH} | new |" in proc.stdout


def test_mutation_run_executes_exactly_selected_tests(tmp_path):
    tests = {"tests/test_calc.py": STRONG_TESTS, "tests/test_unrelated.py": UNRELATED_TEST}
    repo = build_fixture(tmp_path, tests)
    measure_coverage(repo, tmp_path)
    proc, records, verdict = run_gate(repo, tmp_path, keep=True)
    assert proc.returncode == 0, explain(proc)
    selected = set(file_record(records)["selected_tests"])
    assert selected == {
        "tests/test_calc.py::test_add",
        "tests/test_calc.py::test_scale",
        "tests/test_calc.py::test_sign",
    }
    kept = re.search(r"kept workspace: (\S+)", proc.stderr)
    assert kept, explain(proc)
    root = Path(kept.group(1))
    try:
        events = [
            json.loads(line) for line in (root / "ncg-plugin/events.jsonl").read_text().splitlines()
        ]
        executed = {e["node"] for e in events if e["event"] == "executed"}
        assert executed == selected
        loaded = [e["path"] for e in events if e["event"] == "plugin_loaded"]
        assert loaded and all(
            Path(p).resolve() == (root / "ncg-plugin/_ncg_tripwire.py").resolve() for p in loaded
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_stale_mutants_tree_in_checkout_has_no_effect(tmp_path):
    repo = build_fixture(tmp_path, {"tests/test_calc.py": STRONG_TESTS})
    measure_coverage(repo, tmp_path)
    stale = repo / "mutants" / "bootstrap"
    stale.mkdir(parents=True)
    (stale / "calc.py").write_text("raise RuntimeError('stale mutants tree')\n", encoding="utf-8")
    proc, records, verdict = run_gate(repo, tmp_path)
    assert proc.returncode == 0, explain(proc)
    assert file_record(verdict)["outcome"] == "pass"
    assert (stale / "calc.py").read_text(
        encoding="utf-8"
    ) == "raise RuntimeError('stale mutants tree')\n"
    assert sorted(p.name for p in (repo / "mutants").iterdir()) == ["bootstrap"]


def test_weak_tests_fail_the_mutant_score_with_exit_1(tmp_path):
    weak = (
        "from bootstrap.calc import add, sign\n\n\n"
        "def test_weak():\n    assert add(1, 1) == 2\n    assert sign(5) == 'pos'\n"
    )
    repo = build_fixture(tmp_path, {"tests/test_calc.py": weak})
    measure_coverage(repo, tmp_path)
    proc, records, verdict = run_gate(repo, tmp_path)
    assert proc.returncode == 1, explain(proc)
    rec = file_record(verdict)
    assert rec["outcome"] == "fail" and "mutant_score_below_threshold" in reason_codes(rec)
    assert rec["mutants_total"] > 0 and rec["mutant_score_pct"] < 75.0
    assert records["internal_errors"] == []


def test_real_mutmut_isolation_failure_attributed(tmp_path):
    needs_git = (
        "from pathlib import Path\n\nfrom bootstrap.calc import add, scale, sign\n\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n    assert scale(3) == 7\n"
        "    assert [sign(1), sign(-1), sign(0)] == ['pos', 'neg', 'zero']\n"
        "    assert (Path(__file__).resolve().parents[1] / '.git').is_dir()\n"
    )
    repo = build_fixture(tmp_path, {"tests/test_calc.py": needs_git})
    measure_coverage(repo, tmp_path)
    proc, records, verdict = run_gate(repo, tmp_path)
    assert proc.returncode == 1, explain(proc)
    rec = file_record(verdict)
    assert reason_codes(rec) == ["selected_test_fails_in_isolation"], explain(proc)
    message = rec["fail_reasons"][0]["message"]
    assert "tests/test_calc.py::test_add" in message and "stats" in message
    assert records["internal_errors"] == []


def test_real_path_loaded_test_fails_with_a_named_fix(tmp_path):
    loader = (
        "import importlib.util\n\n"
        "spec = importlib.util.spec_from_file_location('calc', 'bootstrap/calc.py')\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n\n\n"
        "def test_loaded_add():\n    assert module.add(1, 2) == 3\n"
    )
    repo = build_fixture(
        tmp_path, {"tests/test_calc.py": STRONG_TESTS, "tests/test_loader.py": loader}
    )
    measure_coverage(repo, tmp_path)
    proc, records, verdict = run_gate(repo, tmp_path)
    assert proc.returncode == 1, explain(proc)
    assert records["internal_errors"] == []
    rec = file_record(verdict)
    assert reason_codes(rec) == ["path_loaded_module"], explain(proc)
    assert "tests/test_loader.py" in rec["fail_reasons"][0]["message"]
    assert "canonical" in rec["fail_reasons"][0]["message"]


FLAKY = "def pick(x):\n    return x + 1\n"
FAIL_ONCE_TESTS = """import os
import tempfile
from pathlib import Path

from bootstrap.flaky import pick


def test_pick_fails_on_each_processs_first_attempt_only():
    marker = Path(tempfile.gettempdir()) / f"rr-first-attempt-{os.getpid()}"
    first = not marker.exists()
    marker.touch()
    pick(1)
    assert not first, "fails once per process, then passes on the rerun"
"""


def test_rr1_a_deterministic_kill_stays_killed_and_a_fail_once_test_leaves_its_mutant_survived(
    tmp_path,
):
    """RV-1: `--reruns 1` in the mutation workspace. Two consecutive failures are a kill; one is not."""
    repo = build_fixture(
        tmp_path,
        {"tests/test_calc.py": STRONG_TESTS, "tests/test_flaky.py": FAIL_ONCE_TESTS},
        extra_pr_files={"bootstrap/flaky.py": FLAKY},
    )
    measure_coverage(repo, tmp_path)
    proc, records, verdict = run_gate(repo, tmp_path)
    assert proc.returncode == 1, explain(proc)
    assert records["internal_errors"] == [], explain(proc)
    calc = file_record(verdict, CALC_PATH)
    assert calc["outcome"] == "pass" and calc["mutants_killed"] == calc["mutants_total"] > 0
    assert set(calc["mutant_status_counts"]) <= {"killed", "timeout"}
    flaky = file_record(verdict, "bootstrap/flaky.py")
    assert flaky["mutants_total"] > 0, explain(proc)
    assert flaky["mutants_killed"] == 0 and flaky["mutant_status_counts"] == {
        "survived": flaky["mutants_total"]
    }
    assert reason_codes(flaky) == ["mutant_score_below_threshold"], explain(proc)


HOLD_TEST = """

def test_hold():
    assert add(1, 1) == 2
    if os.environ.get("MUTANT_UNDER_TEST"):
        with open(os.environ["HOLD_PIDFILE"], "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        time.sleep(300)
"""


def process_is_gone(pid):
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    except OSError:
        return True
    return state == "Z"


def wait_for(condition, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return condition()


def test_int2_sigterm_to_a_shard_removes_its_workspace_and_leaves_no_live_child_group(tmp_path):
    """RV-4: SIGTERM mid-mutation exits 143, writes no fragment, and kills the mutmut group."""
    held = "import os\nimport time\n\n" + STRONG_TESTS + HOLD_TEST
    repo = build_fixture(tmp_path, {"tests/test_calc.py": held})
    git(repo, "checkout", "-q", "main")
    pr_head = git(repo, "rev-parse", "feature")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge", "feature")
    gated = git(repo, "rev-parse", "HEAD")
    measure_coverage(repo, tmp_path, GITHUB_RUN_ID="5")
    pidfile = tmp_path / "hold.pid"
    plan_out = tmp_path / "plan" / "new-code-plan.json"
    gate = [sys.executable, "-m", "scripts.framework.new_code_gate"]
    plan = [*gate, "plan", "--gated-sha", gated, "--pr-head-sha", pr_head, "--pr", "1"]
    plan += ["--coverage-file", ".coverage", "--meta", "coverage-meta.json"]
    plan += ["--out", str(plan_out), "--tests-result", "success", "--run-id", "5"]
    plan += ["--run-attempt", "1"]
    planned = subprocess.run(
        plan, cwd=repo, env=clean_env(tmp_path), capture_output=True, text=True, check=False
    )
    assert planned.returncode == 0, planned.stdout + planned.stderr
    out = tmp_path / "fragment.json"
    argv = [*gate, "shard", "--index", "1", "--plan-dir", str(plan_out.parent)]
    argv += ["--gated-sha", gated, "--pr", "1", "--run-id", "5", "--run-attempt", "1"]
    argv += ["--out", str(out)]
    proc = subprocess.Popen(
        argv,
        cwd=repo,
        env=clean_env(tmp_path, HOLD_PIDFILE=str(pidfile)),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert wait_for(lambda: pidfile.exists() or proc.poll() is not None, 300)
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            recorded = out.read_text(encoding="utf-8") if out.exists() else "no fragment"
            pytest.fail(f"shard ended early: {proc.returncode}\n{stdout}{stderr}\n{recorded}")
        assert wait_for(lambda: pidfile.read_text(encoding="utf-8") != "", 10)
        held_pid = int(pidfile.read_text(encoding="utf-8"))
        assert not process_is_gone(held_pid)
        proc.send_signal(signal.SIGTERM)
        stdout, stderr = proc.communicate(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    assert proc.returncode == 143, stdout + stderr
    assert not out.exists()
    assert wait_for(lambda: process_is_gone(held_pid), 30)
    assert list((tmp_path / "tmp").glob("ncg-*")) == []
