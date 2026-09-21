"""run_gates.sh's gate-results.json artifact under the new changeset grammar (#1759).

Complements test_run_gates_changeset.py (which pins resolution via the
RUN_GATES_RESOLVE_ONLY seam, before any gate runs) by driving the real,
full gate loop and inspecting the written artifact: a resolution failure
must overwrite stale evidence with `[]` (§5 step 2), and every record must
carry the new additive `changeset_mode` / `files_forwarded` / `outcome`
fields (§8), constant across the array regardless of what each individual
gate does with them.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "oversight" / "run_gates.sh"
_ARTIFACT = Path(".claudetmp") / "oversight" / "validators" / "gate-results.json"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git required",
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(cwd: Path) -> None:
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@example.com")
    _git(cwd, "config", "user.name", "t")
    (cwd / "seed.txt").write_text("seed\n")
    _git(cwd, "add", "seed.txt")
    _git(cwd, "commit", "-q", "-m", "base")


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GATE_TIMEOUT": "20", "GATE_RETRIES": "1"}
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


def _artifact(cwd: Path) -> list:
    return json.loads((cwd / _ARTIFACT).read_text())


# ── TC-A1 — a resolution failure overwrites stale evidence ─────────────────


def test_resolution_failure_overwrites_stale_artifact(tmp_path):
    _init_repo(tmp_path)
    stale_dir = tmp_path / _ARTIFACT.parent
    stale_dir.mkdir(parents=True)
    (tmp_path / _ARTIFACT).write_text(
        json.dumps([{"gate": "lint_check", "exit_code": 0, "suspended": False}])
    )

    res = _run(tmp_path, "--diff", "nosuchref")
    assert res.returncode == 3
    assert _artifact(tmp_path) == []


# ── TC-A2 — an empty changeset: every gate NOT CHECKED, never GATE PASS ─────


def test_empty_changeset_full_run(tmp_path):
    _init_repo(tmp_path)
    res = _run(tmp_path, "--diff", "HEAD")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "GATE NOT RUN" in res.stdout
    assert "GATE PASS: all non-suspended gates passed" not in res.stdout
    assert "no files specified — defaulting" not in res.stdout

    records = _artifact(tmp_path)
    assert records, "expected at least one gate record"
    for record in records:
        assert record["outcome"] == "not-checked", record
        assert record["exit_code"] == 0, record
        assert record["changeset_mode"] == "diff"
        assert record["files_forwarded"] == 0


# ── TC-A3 — a real changeset: changeset_mode/files_forwarded on every record ─


def test_real_changeset_records_changeset_fields(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "a.py").write_text("a = 1\n")
    (tmp_path / "b.py").write_text("b = 1\n")
    _git(tmp_path, "add", "a.py", "b.py")
    _git(tmp_path, "commit", "-q", "-m", "add two files")

    _run(tmp_path, "--diff", "HEAD~1")
    # Not asserting overall rc: a real gate finding (e.g. an unrelated
    # dependency advisory in the shared oversight venv) is orthogonal to
    # what this test pins — the artifact's changeset bookkeeping.
    records = _artifact(tmp_path)
    assert records, "expected at least one gate record"
    for record in records:
        assert record["changeset_mode"] == "diff", record
        assert record["files_forwarded"] == 2, record
        assert record["outcome"] == "checked", record
