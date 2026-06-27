"""Fail-closed behaviour of scripts/run_red_team.sh (#911).

The milestone red-team checkpoint runs two external reviewers (codex, agy) whose
invocations swallow their own failure into placeholder JSON — an absent CLI
yields {"skipped":true} and a fired-but-crashed CLI yields {"error":...}. Before
#911 the script exited 0 regardless, so a checkpoint with ZERO real reviewers
reported 'complete' having performed no review (the highest-leverage gate became
a no-op precisely when tooling was degraded).

These tests drive the real script as a subprocess with stubbed reviewer CLIs and
assert the exit code. They are hermetic: cwd is a tmp dir (so the report, the
token log, and `find .` all resolve inside it) and `gh` is stubbed (no network).

Mirrors the runtime fail-closed guard tested for the sibling run_second_review.sh
(#681/#765).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "run_red_team.sh"

# A valid (non-error, non-skipped) reviewer JSON with no findings — a clean
# checkpoint that still produced a real review.
_CLEAN_CODEX = (
    '{"reviewer":"codex","milestone":"auth","exploitable_findings":[],'
    '"not_exploitable_attestations":[{"vector":"replay","verdict":"NOT EXPLOITABLE",'
    '"reason":"nonce enforced"}],"summary":"clean"}'
)
_CLEAN_AGY = (
    '{"reviewer":"agy","milestone":"auth","exploitable_findings":[],'
    '"not_exploitable_attestations":[{"vector":"spec","verdict":"CORRECTLY IMPLEMENTED",'
    '"reason":"verified"}],"summary":"clean"}'
)

# Externals run_red_team.sh needs before/around the guard (codex/agy deliberately
# excluded so we can simulate them being absent).
_REQUIRED_BINS = [
    "env", "bash", "find", "tr", "cat", "mkdir", "date",
    "git", "python3", "dirname", "grep", "awk", "head",
]


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _gh_stub(stub_dir: Path) -> None:
    """A gh that succeeds silently — `gh pr view` returns empty, no network."""
    _write_exec(stub_dir / "gh", "#!/bin/sh\nexit 0\n")


def _reviewer_stub(stub_dir: Path, name: str, *, fail: bool, output: str = "") -> None:
    """Stub a reviewer CLI: `fail` → non-zero exit (triggers the script's error
    placeholder); otherwise print `output` and exit 0."""
    if fail:
        body = "#!/bin/sh\nexit 3\n"
    else:
        # Single-quote the JSON; it contains no single quotes.
        body = f"#!/bin/sh\nprintf '%s' '{output}'\n"
    _write_exec(stub_dir / name, body)


def _run(stub_dir: Path, tmp_path: Path, *extra_args: str,
         minimal_path: bool = False) -> subprocess.CompletedProcess:
    if minimal_path:
        path = str(stub_dir)
    else:
        path = os.pathsep.join([str(stub_dir), os.environ.get("PATH", "")])
    env = {**os.environ, "PATH": path}
    return subprocess.run(
        ["bash", str(_SCRIPT), "--milestone", "auth", *extra_args],
        cwd=str(tmp_path), env=env, capture_output=True, text=True, timeout=60,
    )


def test_both_reviewers_error_fails_closed(tmp_path):
    """Both fired reviewers crash → checkpoint FAILURE (exit 1)."""
    stub = tmp_path / "stub_bin"
    stub.mkdir()
    _gh_stub(stub)
    _reviewer_stub(stub, "codex", fail=True)
    _reviewer_stub(stub, "agy", fail=True)
    r = _run(stub, tmp_path)
    assert r.returncode == 1, r.stderr
    assert "FAIL-CLOSED" in r.stderr


def test_one_reviewer_error_fails_closed(tmp_path):
    """A fired reviewer that errors is a checkpoint FAILURE even when its sibling
    produced a real review."""
    stub = tmp_path / "stub_bin"
    stub.mkdir()
    _gh_stub(stub)
    _reviewer_stub(stub, "codex", fail=False, output=_CLEAN_CODEX)
    _reviewer_stub(stub, "agy", fail=True)
    r = _run(stub, tmp_path)
    assert r.returncode == 1, r.stderr
    assert "FAIL-CLOSED" in r.stderr


def test_both_reviewers_real_passes(tmp_path):
    """Two real reviews (clean, no findings) → checkpoint succeeds (exit 0)."""
    stub = tmp_path / "stub_bin"
    stub.mkdir()
    _gh_stub(stub)
    _reviewer_stub(stub, "codex", fail=False, output=_CLEAN_CODEX)
    _reviewer_stub(stub, "agy", fail=False, output=_CLEAN_AGY)
    r = _run(stub, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "FAIL-CLOSED" not in r.stderr


def test_dry_run_is_exempt(tmp_path):
    """--dry-run is intentionally exempt: its skipped placeholders are expected."""
    stub = tmp_path / "stub_bin"
    stub.mkdir()
    _gh_stub(stub)
    r = _run(stub, tmp_path, "--dry-run")
    assert r.returncode == 0, r.stderr


def test_both_reviewers_absent_fails_closed(tmp_path):
    """Neither reviewer CLI installed (the headline #911 scenario): zero real
    reviewers must NOT exit 0."""
    resolved = {b: shutil.which(b) for b in _REQUIRED_BINS}
    missing = [b for b, p in resolved.items() if p is None]
    if missing:
        pytest.skip(f"required binaries unavailable for minimal-PATH test: {missing}")

    stub = tmp_path / "stub_bin"
    stub.mkdir()
    _gh_stub(stub)
    for b, p in resolved.items():
        (stub / b).symlink_to(p)

    # Minimal PATH containing only the stub dir → codex/agy resolve to nothing.
    r = _run(stub, tmp_path, minimal_path=True)
    assert r.returncode == 1, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "FAIL-CLOSED" in r.stderr
