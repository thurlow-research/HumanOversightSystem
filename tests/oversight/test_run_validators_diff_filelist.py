"""run_validators.sh --diff must not filter the changed-file list to *.py (#981).

Before the fix, `--diff <ref>` ran `git diff --name-only | grep '\\.py$'`, so FILES
(and therefore ALL_FILES) contained only Python files. But ip_check.py's Level-1
license/provenance gate and issue_query.py key off dependency manifests
(requirements*.txt, pyproject.toml, package.json) — none of which end in .py.
On the release gate a copyleft/unknown-license dependency added via requirements.txt
was filtered out, so the IP dimension scored a false-clean 0.0.

The fix collects the FULL changed-file list into ALL_FILES (so the manifest-aware
validators see it) while the existing PY_FILES split keeps the Python-only
validators .py-only.

These tests drive the real script through its RUN_VALIDATORS_FILELIST_ONLY seam,
which emits the resolved ALL_FILES / PY_FILES split and exits before any (heavy,
network-dependent) validator runs — so the assertions pin the file collection
directly, deterministically, and without external tooling.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "oversight" / "run_validators.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git required",
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(cwd: Path) -> None:
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@example.com")
    _git(cwd, "config", "user.name", "t")
    (cwd / "seed.txt").write_text("seed\n")
    _git(cwd, "add", "seed.txt")
    _git(cwd, "commit", "-q", "-m", "base")


def _run_filelist(cwd: Path, diff_ref: str) -> dict[str, list[str]]:
    """Run the script in --diff mode via the file-list seam; parse the split."""
    env = {**os.environ, "RUN_VALIDATORS_FILELIST_ONLY": "1"}
    res = subprocess.run(
        ["bash", str(_SCRIPT), "--diff", diff_ref],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0, res.stderr
    split: dict[str, list[str]] = {"ALL_FILES": [], "PY_FILES": []}
    for line in res.stdout.splitlines():
        if "\t" not in line:
            continue
        key, _, val = line.partition("\t")
        if key in split:
            split[key].append(val)
    return split


def test_diff_manifest_reaches_all_files_not_py_files(tmp_path):
    """A requirements.txt change must land in ALL_FILES (ip_check) but not PY_FILES."""
    _init_repo(tmp_path)
    (tmp_path / "mod.py").write_text("x = 1\n")
    (tmp_path / "requirements.txt").write_text("some-agpl-package==1.0\n")
    _git(tmp_path, "add", "mod.py", "requirements.txt")
    _git(tmp_path, "commit", "-q", "-m", "add dep + code")

    split = _run_filelist(tmp_path, "HEAD~1")

    # Regression: the manifest must NOT be filtered out — this is the whole bug.
    assert "requirements.txt" in split["ALL_FILES"]
    assert "mod.py" in split["ALL_FILES"]
    # The manifest must stay out of the Python-only subset.
    assert "requirements.txt" not in split["PY_FILES"]
    assert "mod.py" in split["PY_FILES"]


def test_diff_multiple_manifest_types_all_reach_all_files(tmp_path):
    """pyproject.toml and package.json (also non-.py) must reach ALL_FILES too."""
    _init_repo(tmp_path)
    for name in ("pyproject.toml", "package.json", "helper.py"):
        (tmp_path / name).write_text("{}\n" if name.endswith(".json") else "content\n")
    _git(tmp_path, "add", "pyproject.toml", "package.json", "helper.py")
    _git(tmp_path, "commit", "-q", "-m", "manifests + code")

    split = _run_filelist(tmp_path, "HEAD~1")

    for manifest in ("pyproject.toml", "package.json"):
        assert manifest in split["ALL_FILES"]
        assert manifest not in split["PY_FILES"]
    assert "helper.py" in split["PY_FILES"]


def test_diff_python_only_change_unaffected(tmp_path):
    """A pure-Python diff still populates both lists identically (no regression)."""
    _init_repo(tmp_path)
    (tmp_path / "only.py").write_text("y = 2\n")
    _git(tmp_path, "add", "only.py")
    _git(tmp_path, "commit", "-q", "-m", "py only")

    split = _run_filelist(tmp_path, "HEAD~1")

    assert split["ALL_FILES"] == ["only.py"]
    assert split["PY_FILES"] == ["only.py"]
