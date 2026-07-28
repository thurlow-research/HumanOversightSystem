"""Tests for scripts/oversight/lib/resolve_node_tool.sh (S2, ADR-032 D2).

Discover-only consumer JS tool resolver: ./node_modules/.bin -> `npx --no-install`
-> PATH. Never installs, never ships node_modules, never triggers a network
fetch. These tests drive the sourced function directly (matching the
`test_step_range.py` pattern) rather than the full run_validators.sh pipeline.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts" / "oversight" / "lib" / "resolve_node_tool.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash required")


def _make_executable(path: Path, content: str = "#!/usr/bin/env bash\ntrue\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(cwd: Path, tool: str, path_env: str | None = None) -> subprocess.CompletedProcess:
    script = f'set -euo pipefail; . "{HELPER}"; resolve_node_tool "{tool}"'
    env = {**os.environ}
    if path_env is not None:
        # Stub scripts use `#!/usr/bin/env bash`; env resolves "bash" via PATH,
        # so bash's own directory must stay reachable even in an otherwise
        # minimal/isolated PATH, or nested stub invocations (e.g. the npx stub)
        # fail to launch at all rather than exercising the tier under test.
        env["PATH"] = f"{path_env}:{os.path.dirname(BASH)}"
    return subprocess.run(
        [BASH, "-c", script], cwd=str(cwd), capture_output=True, text=True, env=env
    )


def test_resolves_project_local_node_modules_bin_first(tmp_path):
    _make_executable(tmp_path / "node_modules" / ".bin" / "eslint")
    res = _run(tmp_path, "eslint", path_env="/nonexistent-bin-dir")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "./node_modules/.bin/eslint"


def test_falls_back_to_path_when_no_local_install(tmp_path):
    path_dir = tmp_path / "sysbin"
    _make_executable(path_dir / "eslint")
    res = _run(tmp_path, "eslint", path_env=str(path_dir))
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "eslint"


def test_node_modules_bin_takes_priority_over_path(tmp_path):
    _make_executable(tmp_path / "node_modules" / ".bin" / "eslint")
    path_dir = tmp_path / "sysbin"
    _make_executable(path_dir / "eslint")
    res = _run(tmp_path, "eslint", path_env=str(path_dir))
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "./node_modules/.bin/eslint"


def test_not_found_returns_empty_and_rc1(tmp_path):
    res = _run(tmp_path, "totally-absent-tool-xyz", path_env="/nonexistent-bin-dir")
    assert res.returncode == 1
    assert res.stdout.strip() == ""


def test_npx_no_install_tier_used_between_local_and_path(tmp_path):
    """A stub `npx` that resolves via --no-install for a tool absent from
    node_modules/.bin and PATH must be picked up as the middle tier."""
    path_dir = tmp_path / "sysbin"
    _make_executable(
        path_dir / "npx",
        "#!/usr/bin/env bash\n"
        'if [[ "$1" == "--no-install" && "$2" == "widget" && "$3" == "--version" ]]; then\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
    )
    res = _run(tmp_path, "widget", path_env=str(path_dir))
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "npx --no-install widget"


def test_npx_probe_failure_falls_through_to_path(tmp_path):
    """A present-but-rejecting npx (the real --no-install behavior for a
    genuinely uninstalled package) must not block the PATH tier."""
    path_dir = tmp_path / "sysbin"
    _make_executable(path_dir / "npx", "#!/usr/bin/env bash\nexit 1\n")
    _make_executable(path_dir / "widget")
    res = _run(tmp_path, "widget", path_env=str(path_dir))
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == "widget"
