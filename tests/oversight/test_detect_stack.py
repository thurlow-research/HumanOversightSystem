"""Tests for scripts/oversight/lib/detect_stack.sh (S2, ADR-032 D1).

Two functions under test:
  detect_required_tools() — repo-marker -> required-tool-key table.
  tool_preflight_or_fail() — resolves every required tool + the Node floor;
    hard-fails (rc1, structured stderr) on any miss. Honors the audited
    `SUSPENDED: tools` escape hatch and the non-default `HOS_REQUIRE_TOOLS=warn`
    downgrade. Default mode is enforce (no warn-grace, D1 ratified).

`HOS_NODE_FLOOR_MAJOR` is read at source time as a test-only override so the
node-floor assertions do not depend on the actual Node major installed on the
test machine.
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


def _detect(tmp_path: Path) -> list[str]:
    script = f'set -euo pipefail; . "{HELPER}"; detect_required_tools'
    res = subprocess.run(
        [BASH, "-c", script], cwd=str(tmp_path), capture_output=True, text=True
    )
    assert res.returncode == 0, res.stderr
    return sorted(line for line in res.stdout.splitlines() if line)


def _preflight(tmp_path: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    script = f'set -euo pipefail; . "{HELPER}"; tool_preflight_or_fail'
    full_env = {**os.environ}
    if env:
        full_env.update(env)
    return subprocess.run(
        [BASH, "-c", script], cwd=str(tmp_path), capture_output=True, text=True, env=full_env
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
