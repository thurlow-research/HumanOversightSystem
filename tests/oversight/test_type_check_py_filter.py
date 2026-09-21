"""type_check.sh mypy lane: non-.py args must not reach mypy (#1096).

run_gates.sh forwards the whole changeset to every gate. Before this fix,
type_check.sh appended every positional arg to FILES with no extension
filter, so a non-.py path (a .sh gate script, a .md doc, a JS/TS file) in
the changeset landed directly in mypy's argv and crashed the gate with a
spurious "Invalid syntax" error — unrelated to any real type issue.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TYPE_CHECK = _REPO / "scripts" / "oversight" / "gates" / "type_check.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")

_MYPY = (_REPO / "scripts" / "oversight" / ".venv" / "bin" / "mypy").exists()


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_TYPE_CHECK), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_non_py_arg_alone_skips_mypy_without_crashing(tmp_path):
    # Wording changed under #1759: the old string ("no Python files found in
    # project") was a false statement about the *project* when only the
    # *changeset* (an explicit, single non-.py argument here) had none — the
    # exact false statement the issue quotes. The subject of this test is
    # unchanged: a non-.py arg must not reach mypy, and must not crash it.
    sh_file = tmp_path / "some_gate.sh"
    sh_file.write_text("#!/usr/bin/env bash\necho hi\n")
    res = _run(tmp_path, "some_gate.sh")
    assert "SKIP — 0 of 1 changeset file(s) are Python" in res.stdout
    assert "Invalid syntax" not in res.stdout
    assert res.returncode == 0


@pytest.mark.skipif(not _MYPY, reason="mypy not present in oversight venv")
def test_non_py_arg_mixed_with_clean_py_does_not_crash_mypy(tmp_path):
    (tmp_path / "some_gate.sh").write_text("#!/usr/bin/env bash\necho hi\n")
    (tmp_path / "clean.py").write_text("x: int = 1\n")
    res = _run(tmp_path, "some_gate.sh", "clean.py")
    assert "Invalid syntax" not in res.stdout
    assert "GATE PASS" in res.stdout
    assert res.returncode == 0
