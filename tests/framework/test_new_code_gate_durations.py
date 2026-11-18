"""The per-test durations the shard planner reads (#2304, TD 5.20.12, SH-DUR).

`tests/durations_writer.py` is registered by the root conftest only when
`HOS_TEST_DURATIONS_OUT` is set. These cases drive it directly and, once, through a real pytest
subprocess so the node IDs can be compared with the coverage contexts the planner joins them to.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.framework import new_code_gate as gate
from tests import durations_writer as dw

ROOT = Path(__file__).resolve().parents[2]
RUN_TESTS = ROOT / "scripts" / "framework" / "run_tests.sh"

CONFTEST = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from tests.durations_writer import register_if_requested


def pytest_configure(config):
    register_if_requested(config)
"""
SAMPLE = """
import pytest


def test_plain():
    assert 1 + 1 == 2


class TestGroup:
    def test_method(self):
        assert True


@pytest.mark.parametrize("n", [1, 2])
def test_param(n):
    assert n
"""


def report(node, seconds):
    return SimpleNamespace(nodeid=node, duration=seconds)


def sample_run(tmp_path, env_value):
    """Run SAMPLE under pytest-cov contexts in a subprocess, with the durations env as given."""
    (tmp_path / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (tmp_path / "test_sample.py").write_text(SAMPLE, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != dw.DURATIONS_ENV}
    env["PYTHONPATH"] = str(ROOT)
    if env_value is not None:
        env[dw.DURATIONS_ENV] = env_value
    argv = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-o", "addopts="]
    argv += [f"--cov={tmp_path}", "--cov-context=test", "--cov-report="]
    return subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True, check=False)


def test_conftest_writes_durations_only_when_env_set(tmp_path):
    out = tmp_path / "out" / "durations.json"
    proc = sample_run(tmp_path, str(out))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    written = json.loads(out.read_text(encoding="utf-8"))
    assert all(isinstance(ms, int) and ms >= 0 for ms in written.values())
    assert sorted(written) == [
        "test_sample.py::TestGroup::test_method",
        "test_sample.py::test_param[1]",
        "test_sample.py::test_param[2]",
        "test_sample.py::test_plain",
    ]
    from coverage import CoverageData

    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.read()
    contexts = {re.sub(r"\|(setup|run|teardown)$", "", c) for c in data.measured_contexts() if c}
    # Same node-ID spelling: every context coverage recorded is a key of the durations file.
    assert {"test_sample.py::test_plain", "test_sample.py::TestGroup::test_method"} <= contexts
    assert contexts <= set(written)
    quiet = tmp_path / "quiet"
    quiet.mkdir()
    assert sample_run(quiet, None).returncode == 0
    assert list(quiet.glob("*.json")) == [] and not (tmp_path / "durations.json").exists()


def test_a_leftover_durations_file_is_removed_before_the_run(tmp_path):
    out = tmp_path / "durations.json"
    out.write_text('{"old.py::t": 1}', encoding="utf-8")
    config = SimpleNamespace(pluginmanager=SimpleNamespace(register=lambda *a: None))
    os.environ[dw.DURATIONS_ENV] = str(out)
    try:
        dw.register_if_requested(config)
    finally:
        del os.environ[dw.DURATIONS_ENV]
    assert not out.exists()


def test_run_tests_removes_a_leftover_durations_file_first():
    lines = RUN_TESTS.read_text(encoding="utf-8").splitlines()
    rm = next(i for i, ln in enumerate(lines) if ln.strip() == "rm -f test-durations.json")
    run = next(i for i, ln in enumerate(lines) if " -m pytest tests/" in ln)
    assert rm < run


def test_durations_sum_setup_call_teardown_and_reruns():
    writer = dw.DurationsWriter(Path("unused"))
    for phase_seconds in (0.0004, 0.0012, 0.0004, 1.5):
        writer.pytest_runtest_logreport(report("t.py::a", phase_seconds))
    writer.pytest_runtest_logreport(report("t.py::b", 0.0004))
    assert writer.seconds["t.py::a"] == pytest.approx(1.502)
    assert {n: round(s * 1000) for n, s in writer.seconds.items()} == {
        "t.py::a": 1502,
        "t.py::b": 0,
    }


def test_the_write_is_atomic_and_a_failed_write_leaves_the_old_file(tmp_path, monkeypatch):
    target = tmp_path / "durations.json"
    dw.write_durations(target, {"t.py::a": 0.25})
    assert json.loads(target.read_text(encoding="utf-8")) == {"t.py::a": 250}
    assert [p.name for p in tmp_path.iterdir()] == ["durations.json"]

    def refuse(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(dw.os, "replace", refuse)
    with pytest.raises(OSError):
        dw.write_durations(target, {"t.py::a": 9.0})
    assert json.loads(target.read_text(encoding="utf-8")) == {"t.py::a": 250}
    assert [p.name for p in tmp_path.iterdir()] == ["durations.json"]


def test_a_failed_write_is_reported_and_does_not_fail_the_suite(tmp_path, monkeypatch, capsys):
    blocked = tmp_path / "file"
    blocked.write_text("x", encoding="utf-8")
    writer = dw.DurationsWriter(blocked / "durations.json")
    writer.pytest_sessionfinish(session=None)
    assert "test durations not written" in capsys.readouterr().err


def test_the_env_name_is_stripped_from_the_gates_child_environment():
    assert dw.DURATIONS_ENV in gate.STRIPPED_ENV_NAMES


def test_run_tests_sets_the_env_on_the_pytest_command_and_passes_the_file_to_meta():
    text = RUN_TESTS.read_text(encoding="utf-8")
    pytest_lines = [ln for ln in text.splitlines() if " -m pytest tests/" in ln]
    assert len(pytest_lines) == 1
    assert (
        pytest_lines[0]
        .strip()
        .startswith('HOS_TEST_DURATIONS_OUT=test-durations.json "$VENV_PYTHON" -m pytest')
    )
    assert text.count("HOS_TEST_DURATIONS_OUT") == 1
    (meta_line,) = [ln for ln in text.splitlines() if " meta --coverage-file" in ln]
    assert meta_line.strip().endswith("--durations test-durations.json")
