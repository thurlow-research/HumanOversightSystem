"""type_check.sh tsc --noEmit lane (ADR-032, #1029 S11, #1067).

Extends the Python-only mypy gate to run `tsc --noEmit` (whole-project, via
tsconfig.json) via the discover-only resolver (D2). Three behaviors pinned:

  - No tsconfig.json in the project: the tsc lane SKIPs (not a TS project).
  - An Astro project is detected (package.json "astro" dep, or any .astro
    file): the tsc lane DEFERS (SKIP) — astro_check.sh (S12) owns
    type-checking there instead (ADR-032 D9).
  - tsconfig.json present, no Astro markers, tsc resolvable: a real type
    error is GATE FAIL; clean files are GATE PASS.

Mirrors the subprocess-driven pattern in test_lint_check_js.py.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TYPE_CHECK = _REPO / "scripts" / "oversight" / "gates" / "type_check.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")

_TSC = shutil.which("tsc") is not None

_MIN_TSCONFIG = '{"compilerOptions": {"strict": true, "noEmit": true}}\n'


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_TYPE_CHECK), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_no_tsconfig_skips_ts_lane(tmp_path):
    (tmp_path / "mod.ts").write_text("const x: number = 1;\n")
    res = _run(tmp_path, "--all")
    assert "SKIP: no tsconfig.json" in res.stdout


def test_astro_package_json_dep_defers_ts_lane(tmp_path):
    (tmp_path / "tsconfig.json").write_text(_MIN_TSCONFIG)
    (tmp_path / "package.json").write_text('{"dependencies": {"astro": "^4.0.0"}}\n')
    res = _run(tmp_path, "--all")
    assert "SKIP: Astro project detected" in res.stdout
    assert "S12" in res.stdout


def test_astro_file_marker_defers_ts_lane(tmp_path):
    (tmp_path / "tsconfig.json").write_text(_MIN_TSCONFIG)
    (tmp_path / "index.astro").write_text("<h1>hi</h1>\n")
    res = _run(tmp_path, "--all")
    assert "SKIP: Astro project detected" in res.stdout


@pytest.mark.skipif(not _TSC, reason="tsc not resolvable on PATH")
def test_tsc_detects_type_error(tmp_path):
    (tmp_path / "tsconfig.json").write_text(_MIN_TSCONFIG)
    (tmp_path / "bad.ts").write_text("const x: number = 'not a number';\n")
    res = _run(tmp_path, "--all")
    assert "GATE FAIL" in res.stdout
    assert res.returncode == 1


@pytest.mark.skipif(not _TSC, reason="tsc not resolvable on PATH")
def test_tsc_clean_passes(tmp_path):
    (tmp_path / "tsconfig.json").write_text(_MIN_TSCONFIG)
    (tmp_path / "clean.ts").write_text("const x: number = 1;\nconsole.log(x);\n")
    res = _run(tmp_path, "--all")
    assert "GATE PASS" in res.stdout
    assert res.returncode == 0


def test_no_args_defaults_to_full_scan_checks_ts(tmp_path):
    (tmp_path / "mod.py").write_text("x: int = 1\n")
    (tmp_path / "tsconfig.json").write_text(_MIN_TSCONFIG)
    res = _run(tmp_path)
    assert "no files specified — defaulting" in res.stdout
    assert "=== tsc --noEmit ===" in res.stdout
