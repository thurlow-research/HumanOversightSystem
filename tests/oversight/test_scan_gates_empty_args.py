"""security_scan.sh / secret_scan.sh must not fail-open on zero file args (#976).

Before the fix both gates treated an empty FILES list as "nothing to scan" and
exited 0 — bandit was skipped outright and detect-secrets printed "No files to
scan" — so HIGH-severity findings and hardcoded secrets recorded a green gate.
The fix mirrors lint_check.sh: on empty FILES (and no --all/--staged) default to
a full-project scan.

The gates are driven as subprocesses with cwd set to a throwaway project so the
scripts' `find .` enumerates only the planted fixture files. Assertions that
depend on a tool (bandit / detect-secrets) are skipped when it is absent from
the oversight venv; the "default scan engaged" guards run regardless and pin the
regression directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GATES = _REPO / "scripts" / "oversight" / "gates"
_SECURITY = _GATES / "security_scan.sh"
_SECRET = _GATES / "secret_scan.sh"
_VENV_BIN = _REPO / "scripts" / "oversight" / ".venv" / "bin"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash unavailable"
)

_BANDIT = (_VENV_BIN / "bandit").exists() or shutil.which("bandit") is not None
_DETECT_SECRETS = (
    (_VENV_BIN / "detect-secrets").exists()
    or shutil.which("detect-secrets") is not None
)

# A subprocess.Popen(..., shell=True) call is bandit B602 (HIGH severity).
_HIGH_FINDING_PY = (
    "import subprocess\n"
    "def run(cmd):\n"
    "    subprocess.Popen(cmd, shell=True)  # bandit B602 HIGH\n"
)
# A recognizable AWS-style access key for detect-secrets.
_SECRET_PY = 'API_TOKEN = "AKIAIOSFODNN7EXAMPLEKEY1234567890abcd"\n'


def _run(script: Path, cwd: Path) -> subprocess.CompletedProcess:
    # Bound the (network-dependent, non-blocking) pip-audit step so the suite
    # cannot hang if advisory fetch is slow/offline; it warns and continues.
    env = {**os.environ, "GATE_TIMEOUT": "20", "GATE_RETRIES": "1"}
    return subprocess.run(
        ["bash", str(script)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


# ── security_scan.sh ──────────────────────────────────────────────────────────


def test_security_scan_no_args_engages_full_scan(tmp_path):
    # With scannable Python present and no positional args, the empty-FILES
    # default branch must fire — the pre-fix code skipped bandit outright.
    (tmp_path / "mod.py").write_text("x = 1\n")
    res = _run(_SECURITY, tmp_path)
    assert "no files specified — defaulting" in res.stdout


@pytest.mark.skipif(not _BANDIT, reason="bandit not installed in oversight venv")
def test_security_scan_no_args_detects_high_finding(tmp_path):
    # bandit must actually scan the planted file and flag the HIGH finding
    # (independent of the incidental pip-audit result).
    (tmp_path / "vuln.py").write_text(_HIGH_FINDING_PY)
    res = _run(_SECURITY, tmp_path)
    assert "HIGH severity bandit finding" in res.stdout
    assert "vuln.py" in res.stdout


# ── secret_scan.sh ────────────────────────────────────────────────────────────


def test_secret_scan_no_args_engages_full_scan(tmp_path):
    (tmp_path / "mod.py").write_text("x = 1\n")
    res = _run(_SECRET, tmp_path)
    assert "no files specified — defaulting" in res.stdout
    # The old fail-open path must be gone when scannable files exist.
    assert "No files to scan" not in res.stdout


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_secret_scan_no_args_detects_planted_secret(tmp_path):
    (tmp_path / "creds.py").write_text(_SECRET_PY)
    res = _run(_SECRET, tmp_path)
    assert res.returncode == 1
    assert "potential secret" in res.stdout.lower()
