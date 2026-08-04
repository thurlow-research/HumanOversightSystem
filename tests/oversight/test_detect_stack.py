"""Tests for scripts/oversight/lib/detect_stack.sh (S2, ADR-032 D1; #1266).

Two functions under test:
  detect_required_tools([py_files_present]) — repo-marker -> required-tool-key
    table for JS/Astro, plus bandit/radon when py_files_present is passed
    (changeset-scoped, mirrors run_validators.sh's PY_FILES gate — #1266).
  tool_preflight_or_fail([py_files_present]) — resolves every required tool
    (venv bin then PATH for bandit/radon, resolve_node_tool for JS/Astro
    tools) + the Node floor; hard-fails (rc1, structured stderr) on any miss.
    Honors the audited `SUSPENDED: tools` escape hatch and the non-default
    `HOS_REQUIRE_TOOLS=warn` downgrade. Default mode is enforce (no
    warn-grace, D1 ratified).

`HOS_NODE_FLOOR_MAJOR` is read at source time as a test-only override so the
node-floor assertions do not depend on the actual Node major installed on the
test machine. `VENV_BIN` is overridden the same way for the bandit/radon
assertions so they do not depend on this repo's own oversight venv.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "oversight" / "lib" / "detect_stack.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    BASH is None or shutil.which("node") is None, reason="bash and node required"
)


def _stub_tool(tmp_path: Path, name: str) -> None:
    stub = tmp_path / "node_modules" / ".bin" / name
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(f"#!/usr/bin/env bash\necho '{name} 0.0.0-stub'\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _stub_python_tool(bin_dir: Path, name: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / name
    stub.write_text(f"#!/usr/bin/env bash\necho '{name} 0.0.0-stub'\n")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _detect(tmp_path: Path, py_files_present: str = "") -> list[str]:
    script = f'set -euo pipefail; . "{HELPER}"; detect_required_tools "$1"'
    res = subprocess.run(
        [BASH, "-c", script, "_", py_files_present],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr
    return sorted(line for line in res.stdout.splitlines() if line)


def _preflight(
    tmp_path: Path, env: dict | None = None, py_files_present: str = ""
) -> subprocess.CompletedProcess:
    script = f'set -euo pipefail; . "{HELPER}"; tool_preflight_or_fail "$1"'
    full_env = {**os.environ}
    if env:
        full_env.update(env)
    return subprocess.run(
        [BASH, "-c", script, "_", py_files_present],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        env=full_env,
    )


# ── detect_required_tools() — repo-marker table ──────────────────────────────


def test_no_markers_returns_empty(tmp_path):
    assert _detect(tmp_path) == []


def test_tsconfig_marker_requires_tsc_and_node_floor(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}\n")
    assert _detect(tmp_path) == ["node-floor", "tsc"]


def test_astro_file_marker_requires_astro_and_astro_check(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "page.astro").write_text("---\n---\n<p>hi</p>\n")
    assert _detect(tmp_path) == ["astro", "astro-check", "node-floor"]


def test_astro_in_package_json_deps_is_also_a_marker(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"astro": "^7.0.0"}}\n')
    assert _detect(tmp_path) == ["astro", "astro-check", "node-floor"]


def test_package_json_without_astro_dep_is_not_a_marker(tmp_path):
    (tmp_path / "package.json").write_text("{}\n")
    assert _detect(tmp_path) == []


def test_eslint_config_marker_requires_eslint_and_node_floor(tmp_path):
    (tmp_path / ".eslintrc.json").write_text("{}\n")
    assert _detect(tmp_path) == ["eslint", "node-floor"]


def test_flat_eslint_config_is_also_a_marker(tmp_path):
    (tmp_path / "eslint.config.js").write_text("export default [];\n")
    assert _detect(tmp_path) == ["eslint", "node-floor"]


def test_combined_markers_union_without_duplicating_node_floor(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}\n")
    (tmp_path / ".eslintrc.json").write_text("{}\n")
    assert _detect(tmp_path) == ["eslint", "node-floor", "tsc"]


# ── tool_preflight_or_fail() ──────────────────────────────────────────────────


def test_no_op_outside_js_project(tmp_path):
    res = _preflight(tmp_path)
    assert res.returncode == 0, res.stderr
    assert res.stderr == ""


def test_all_tools_present_passes(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}\n")
    _stub_tool(tmp_path, "tsc")
    res = _preflight(tmp_path, env={"HOS_NODE_FLOOR_MAJOR": "1"})
    assert res.returncode == 0, res.stderr


def test_missing_tool_blocks_with_structured_message(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}\n")
    res = _preflight(tmp_path, env={"HOS_NODE_FLOOR_MAJOR": "1"})
    assert res.returncode == 1
    assert "tsc" in res.stderr
    assert "ADR-032" in res.stderr
    assert "HOS_REQUIRE_TOOLS=warn" in res.stderr


def test_node_floor_violation_blocks(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}\n")
    _stub_tool(tmp_path, "tsc")
    # Raise the floor above whatever Node major is actually installed —
    # deterministic regardless of the test machine's Node version.
    res = _preflight(tmp_path, env={"HOS_NODE_FLOOR_MAJOR": "999"})
    assert res.returncode == 1
    assert "node" in res.stderr.lower()


def test_warn_mode_downgrades_missing_tool_to_non_fatal(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}\n")
    res = _preflight(
        tmp_path, env={"HOS_NODE_FLOOR_MAJOR": "1", "HOS_REQUIRE_TOOLS": "warn"}
    )
    assert res.returncode == 0, res.stderr
    assert "WARN" in res.stderr


def test_suspended_tools_bypasses_enforcement(tmp_path):
    (tmp_path / "tsconfig.json").write_text("{}\n")
    contract_dir = tmp_path / "contract"
    contract_dir.mkdir()
    (contract_dir / "gate-suspension.md").write_text(
        "Authorized by: Test Human\nDate: 2026-07-27\n\n"
        "## Currently suspended\nSUSPENDED: tools\n"
    )
    res = _preflight(tmp_path, env={"HOS_NODE_FLOOR_MAJOR": "1"})
    assert res.returncode == 0, res.stderr
    assert "GATE SUSPENDED: tools" in res.stdout


# ── Python analysis tools (bandit, radon) — changeset-scoped, #1266 ──────────


def test_detect_python_files_present_requires_bandit_and_radon(tmp_path):
    assert _detect(tmp_path, py_files_present="1") == ["bandit", "radon"]


def test_detect_python_files_flag_unset_does_not_require_bandit_radon(tmp_path):
    # An on-disk .py file alone must not trigger the requirement — the flag,
    # mirroring run_validators.sh's PY_FILES (the diff), is the sole signal.
    (tmp_path / "app.py").write_text("print('hi')\n")
    assert _detect(tmp_path) == []


def test_python_files_present_and_tool_missing_blocks(tmp_path):
    # VENV_BIN pointed at a dir with nothing in it — deterministic "missing"
    # regardless of whether this repo's own oversight venv happens to be on
    # the test runner's PATH.
    res = _preflight(
        tmp_path,
        env={"VENV_BIN": str(tmp_path / "no-such-venv-bin")},
        py_files_present="1",
    )
    assert res.returncode == 1
    assert "bandit" in res.stderr
    assert "radon" in res.stderr
    assert "ensure_venv.sh" in res.stderr
    assert "HOS_REQUIRE_TOOLS=warn" in res.stderr


def test_no_python_files_python_tool_missing_is_no_op(tmp_path):
    res = _preflight(
        tmp_path, env={"VENV_BIN": str(tmp_path / "no-such-venv-bin")}
    )
    assert res.returncode == 0, res.stderr
    assert res.stderr == ""


def test_python_files_present_and_tool_resolvable_via_venv_bin_passes(tmp_path):
    venv_bin = tmp_path / "venv-bin"
    _stub_python_tool(venv_bin, "bandit")
    _stub_python_tool(venv_bin, "radon")
    res = _preflight(
        tmp_path, env={"VENV_BIN": str(venv_bin)}, py_files_present="1"
    )
    assert res.returncode == 0, res.stderr
