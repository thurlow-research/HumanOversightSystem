"""astro_check.sh — Astro project sanity gate (ADR-032, #1029 S12, #1068).

`astro sync` then `astro check` — the Astro analog to django_check.sh's
`manage.py check` (ADR-032 D9). Behaviors pinned:

  - No Astro markers (no "astro" in package.json, no .astro files): SKIP,
    not an Astro project.
  - Astro markers present but the astro CLI is not resolvable: SKIP (the
    hard-fail-on-missing-tool authority is tool_preflight_or_fail/D1, not
    this gate — same convention as lint_check.sh/type_check.sh).
  - Astro markers present, astro resolvable, real errors: GATE FAIL.
  - Astro markers present, astro resolvable, clean: GATE PASS.

Mirrors the subprocess-driven pattern in test_type_check_ts.py.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ASTRO_CHECK = _REPO / "scripts" / "oversight" / "gates" / "astro_check.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash unavailable")

_ASTRO = shutil.which("astro") is not None


def _run(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_ASTRO_CHECK)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def test_no_astro_markers_skips(tmp_path):
    (tmp_path / "mod.ts").write_text("const x: number = 1;\n")
    res = _run(tmp_path)
    assert "SKIP: not an Astro project" in res.stdout
    assert "GATE PASS" not in res.stdout
    assert "GATE FAIL" not in res.stdout
    assert res.returncode == 0


def test_astro_package_json_dep_without_cli_skips(tmp_path):
    # Astro marker present via package.json, but no astro CLI resolvable in
    # this bare tmp_path (no node_modules/.bin, no PATH astro): SKIP, not
    # GATE FAIL — tool_preflight_or_fail (D1) is the hard-fail authority for
    # a depended-on-but-missing tool, not this gate.
    (tmp_path / "package.json").write_text('{"dependencies": {"astro": "^4.0.0"}}\n')
    res = _run(tmp_path)
    assert "SKIP: astro not resolvable" in res.stdout
    assert res.returncode == 0


def test_astro_file_marker_without_cli_skips(tmp_path):
    (tmp_path / "index.astro").write_text("<h1>hi</h1>\n")
    res = _run(tmp_path)
    assert "SKIP: astro not resolvable" in res.stdout
    assert res.returncode == 0


@pytest.mark.skipif(not _ASTRO, reason="astro CLI not resolvable on PATH")
def test_astro_check_detects_error(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"astro": "^4.0.0"}}\n')
    (tmp_path / "astro.config.mjs").write_text("export default {};\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pages").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "pages" / "bad.astro").write_text(
        "---\nconst x: number = 'not a number';\n---\n<h1>{x}</h1>\n"
    )
    res = _run(tmp_path)
    assert "GATE FAIL" in res.stdout
    assert res.returncode == 1


@pytest.mark.skipif(not _ASTRO, reason="astro CLI not resolvable on PATH")
def test_astro_check_clean_passes(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"astro": "^4.0.0"}}\n')
    (tmp_path / "astro.config.mjs").write_text("export default {};\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "pages").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "pages" / "clean.astro").write_text("<h1>hi</h1>\n")
    res = _run(tmp_path)
    assert "GATE PASS" in res.stdout
    assert res.returncode == 0
