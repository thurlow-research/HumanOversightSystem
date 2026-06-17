"""Tests for scripts/oversight/signoff_gate.py — per-step stamp dirs (SPEC-366).

Required cases from the brief:
  - Deploy mode reads from manifest (not disk): a step with required roles but
    no signoffs/<step>/ directory → FAIL                         (REQ-366-06)
  - Orphan step directory (on disk, not in manifest) → FAIL      (REQ-366-09)
  - --step required in PR mode; omission → error                 (OQ-366-01)

Additional coverage:
  - Per-step isolation: step 1 signed, step 2 not                (REQ-366-01)
  - PR mode unknown step → FAIL                                  (REQ-366-09)
  - Happy path: a fully-signed step passes in PR and deploy mode

The gate shells out to `git` and reads commit timestamps, so each test builds a
throwaway git repo on disk, commits source + stamps (so commit times exist), and
invokes the gate as a subprocess. We run the gate with the oversight venv's
Python (it has PyYAML); fall back to sys.executable if the venv is absent.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GATE = _REPO / "scripts" / "oversight" / "signoff_gate.py"
_VENV_PY = _REPO / "scripts" / "oversight" / ".venv" / "bin" / "python3"


def _gate_python() -> str:
    return str(_VENV_PY) if _VENV_PY.exists() else "python3"


# --------------------------------------------------------------------------- #
# Temp-repo helpers                                                            #
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _write_manifest(repo: Path, steps: list[dict]) -> None:
    """Write contract/step-manifest.yaml with the given steps.

    Each step dict: {"id": ..., "required": [role, ...]}.
    """
    lines = [
        'contract_version: "1"',
        'project: "test"',
        "role_mappings:",
        "  code-review: code-reviewer",
        "  security: security-reviewer",
        "  test-unit: unit-test",
        "steps:",
    ]
    for s in steps:
        lines.append(f'  - id: {s["id"]}')
        lines.append(f'    name: "step {s["id"]}"')
        req = ", ".join(s["required"])
        lines.append(f"    required_signoffs: [{req}]")
    (repo / "contract").mkdir(parents=True, exist_ok=True)
    (repo / "contract" / "step-manifest.yaml").write_text("\n".join(lines) + "\n")


def _write_stamp(repo: Path, step_id: str, role: str, status: str = "APPROVED") -> None:
    d = repo / "signoffs" / str(step_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{role}.stamp").write_text(
        textwrap.dedent(
            f"""\
            role: {role}
            agent: test-agent
            status: {status}
            signed_at: 2026-06-16T00:00:00Z
            head_at_signing: deadbeef
            """
        )
    )


def _commit(repo: Path, msg: str = "c") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _run_gate(repo: Path, *args: str):
    """Invoke the gate as a subprocess; return CompletedProcess."""
    env = dict(os.environ)
    return subprocess.run(
        [_gate_python(), str(_GATE), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
    )


# --------------------------------------------------------------------------- #
# Required: --step required in PR mode                                         #
# --------------------------------------------------------------------------- #


def test_pr_mode_requires_step(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, [{"id": "1", "required": ["code-review"]}])
    (repo / "src.py").write_text("x = 1\n")
    _commit(repo, "init")

    res = _run_gate(repo, "--base", "HEAD")
    assert res.returncode == 2, res.stderr + res.stdout
    assert "--step" in (res.stderr + res.stdout)


# --------------------------------------------------------------------------- #
# Required: deploy mode is manifest-authoritative                             #
# --------------------------------------------------------------------------- #


def test_deploy_mode_missing_step_dir_fails(tmp_path):
    """A manifest step with required roles but no signoffs/<step>/ → FAIL.

    This proves the gate reads the manifest, not the disk: there is no
    signoffs/2/ directory at all, yet step 2 is required and must be reported
    missing (a disk-enumeration gate would silently skip it).
    """
    repo = _init_repo(tmp_path)
    _write_manifest(
        repo,
        [
            {"id": "1", "required": ["code-review"]},
            {"id": "2", "required": ["security"]},
        ],
    )
    (repo / "src.py").write_text("x = 1\n")
    _write_stamp(repo, "1", "code-review")
    # Deliberately do NOT create signoffs/2/.
    _commit(repo, "init")

    res = _run_gate(repo, "--all")
    assert res.returncode == 1, res.stderr + res.stdout
    out = res.stdout + res.stderr
    assert "step 2/security" in out or "signoffs/2/security" in out


# --------------------------------------------------------------------------- #
# Required: orphan step directory fails                                        #
# --------------------------------------------------------------------------- #


def test_orphan_step_directory_fails(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, [{"id": "1", "required": ["code-review"]}])
    (repo / "src.py").write_text("x = 1\n")
    _write_stamp(repo, "1", "code-review")
    # Orphan: a stamp dir for a step that is not in the manifest.
    _write_stamp(repo, "99", "code-review")
    _commit(repo, "init")

    res = _run_gate(repo, "--all")
    assert res.returncode == 1, res.stderr + res.stdout
    out = res.stdout + res.stderr
    assert "orphan" in out.lower()
    assert "99" in out


def test_orphan_fails_in_pr_mode_too(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, [{"id": "1", "required": ["code-review"]}])
    (repo / "src.py").write_text("x = 1\n")
    _write_stamp(repo, "1", "code-review")
    _write_stamp(repo, "bogus", "code-review")
    _commit(repo, "init")

    res = _run_gate(repo, "--base", "HEAD", "--step", "1")
    assert res.returncode == 1, res.stderr + res.stdout
    assert "orphan" in (res.stdout + res.stderr).lower()


# --------------------------------------------------------------------------- #
# Additional: per-step isolation + unknown step + happy path                  #
# --------------------------------------------------------------------------- #


def test_per_step_isolation(tmp_path):
    """Step 1 signed; step 2 not. PR --step 1 passes; PR --step 2 fails."""
    repo = _init_repo(tmp_path)
    _write_manifest(
        repo,
        [
            {"id": "1", "required": ["code-review"]},
            {"id": "2", "required": ["code-review"]},
        ],
    )
    (repo / "src.py").write_text("x = 1\n")
    _write_stamp(repo, "1", "code-review")
    _commit(repo, "init")

    # Using HEAD as base yields no changed files vs itself; the stamp existence
    # check still runs. Step 1 has its stamp → PASS.
    res1 = _run_gate(repo, "--base", "HEAD", "--step", "1")
    assert res1.returncode == 0, res1.stdout + res1.stderr

    res2 = _run_gate(repo, "--base", "HEAD", "--step", "2")
    assert res2.returncode == 1, res2.stdout + res2.stderr
    assert "step 2/code-review" in (res2.stdout + res2.stderr)


def test_pr_unknown_step_fails(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(repo, [{"id": "1", "required": ["code-review"]}])
    (repo / "src.py").write_text("x = 1\n")
    _write_stamp(repo, "1", "code-review")
    _commit(repo, "init")

    res = _run_gate(repo, "--base", "HEAD", "--step", "nope")
    assert res.returncode == 1, res.stdout + res.stderr
    assert "nope" in (res.stdout + res.stderr)


def test_deploy_happy_path_passes(tmp_path):
    repo = _init_repo(tmp_path)
    _write_manifest(
        repo,
        [
            {"id": "1", "required": ["code-review"]},
            {"id": "2", "required": ["security"]},
        ],
    )
    (repo / "src.py").write_text("x = 1\n")
    _write_stamp(repo, "1", "code-review")
    _write_stamp(repo, "2", "security")
    _commit(repo, "init")

    res = _run_gate(repo, "--all")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "PASS" in res.stdout
