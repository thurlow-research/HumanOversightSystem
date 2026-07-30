"""lint_check.sh JS/TS/Astro eslint lane (ADR-032, #1029 S10, #1066).

Extends the Python-only lint gate to run eslint on JS/TS/JSX/TSX/Astro files
via the discover-only resolver (D2). Three behaviors pinned:

  - No eslint config in the project: the eslint lane SKIPs (never fail-open
    on a tool that was never configured — a bare `eslint` invocation on an
    unconfigured project errors out with "couldn't find a configuration
    file", which is not a real lint violation).
  - An eslint config present + a real violation: GATE FAIL, eslint's own
    output surfaces for the human.
  - An eslint config present + clean files: GATE PASS.

Mirrors the subprocess-driven pattern in test_scan_gates_empty_args.py.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_LINT_CHECK = _REPO / "scripts" / "oversight" / "gates" / "lint_check.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")

_ESLINT = shutil.which("eslint") is not None

_MIN_ESLINTRC = '{"rules": {"no-unused-vars": "error"}}\n'


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_LINT_CHECK), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_no_eslint_config_skips_js_lane(tmp_path):
    # A JS file with an obvious violation but no project eslint config must
    # not fail the gate — there is nothing configured to lint against.
    (tmp_path / "bad.js").write_text("var unused = 1;\n")
    res = _run(tmp_path, "--all")
    assert "SKIP: no eslint config" in res.stdout
    assert "GATE PASS" in res.stdout
    assert res.returncode == 0


@pytest.mark.skipif(not _ESLINT, reason="eslint not resolvable on PATH")
def test_eslint_config_detects_violation(tmp_path):
    (tmp_path / ".eslintrc.json").write_text(_MIN_ESLINTRC)
    (tmp_path / "bad.js").write_text("var unused = 1;\n")
    res = _run(tmp_path, "--all")
    assert "no-unused-vars" in res.stdout
    assert "GATE FAIL" in res.stdout
    assert res.returncode == 1


@pytest.mark.skipif(not _ESLINT, reason="eslint not resolvable on PATH")
def test_eslint_config_clean_passes(tmp_path):
    (tmp_path / ".eslintrc.json").write_text(_MIN_ESLINTRC)
    (tmp_path / "clean.js").write_text("var used = 1;\nconsole.log(used);\n")
    res = _run(tmp_path, "--all")
    assert "GATE PASS" in res.stdout
    assert res.returncode == 0


def test_no_args_defaults_to_full_scan_includes_js(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n")
    (tmp_path / "mod.ts").write_text("const x: number = 1;\n")
    res = _run(tmp_path)
    assert "no files specified — defaulting" in res.stdout


@pytest.mark.skipif(not _ESLINT, reason="eslint not resolvable on PATH")
def test_all_excludes_node_modules(tmp_path):
    # node_modules JS must never reach the eslint lane (consumer-vendored
    # code, not the changeset under review) — only the vendored violation
    # exists inside node_modules, so a clean overall PASS pins the exclusion.
    (tmp_path / ".eslintrc.json").write_text(_MIN_ESLINTRC)
    (tmp_path / "clean.js").write_text("var used = 1;\nconsole.log(used);\n")
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    (node_modules / "vendored.js").write_text("var unused = 1;\n")
    res = _run(tmp_path, "--all")
    assert "GATE PASS" in res.stdout
    assert res.returncode == 0
