"""AC-1 (--diff parity with an equivalent explicit list) and AC-4 (a usage
error must never read as tool flakiness) against real tools (#1759).

Fixture: a tmp git repo; commit 1 is a clean seed, commit 2 adds `bad.py`
(carrying both a real black violation and a real mypy error), `notes.md`
and `helper.sh`. Skip-guarded per tool so this file degrades gracefully on a
machine without the full oversight venv.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GATES_DIR = _REPO / "scripts" / "oversight" / "gates"
_VENV_BIN = _REPO / "scripts" / "oversight" / ".venv" / "bin"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash and git required",
)

_FLAKE8 = (_VENV_BIN / "flake8").exists()
_BLACK = (_VENV_BIN / "black").exists()
_MYPY = (_VENV_BIN / "mypy").exists()
_DETECT_SECRETS = (_VENV_BIN / "detect-secrets").exists()

_BAD_PY = "import os\n" 'x: int = "not an int"\n' "y=1\n"
_NOTES_MD = "# notes\n\nnothing interesting here.\n"
_HELPER_SH = "#!/usr/bin/env bash\necho hi\n"

# Built by concatenation so this test's own source never contains the literal
# substring — portability_check.sh would otherwise flag this very file when
# the PR that adds it is itself scanned (TC-P3 design note).
_HOME_PATH_LINE = (
    "config_path = " + '"' + "/" + "home" + "/" + "devuser" + "/project/config.py" + '"' + "\n"
)
# A recognizable AWS-style access key for detect-secrets.
_SECRET_LINE = 'API_TOKEN = "AKIAIOSFODNN7EXAMPLEKEY1234567890abcd"\n'  # pragma: allowlist secret


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _build_fixture(cwd: Path, bad_py_extra: str = "", extra_files: dict | None = None) -> None:
    _git(cwd, "init", "-q")
    _git(cwd, "config", "user.email", "t@example.com")
    _git(cwd, "config", "user.name", "t")
    (cwd / "seed.txt").write_text("seed\n")
    _git(cwd, "add", "seed.txt")
    _git(cwd, "commit", "-q", "-m", "base")

    (cwd / "bad.py").write_text(_BAD_PY + bad_py_extra)
    (cwd / "notes.md").write_text(_NOTES_MD)
    (cwd / "helper.sh").write_text(_HELPER_SH)
    for name, content in (extra_files or {}).items():
        (cwd / name).write_text(content)
    _git(cwd, "add", "-A")
    _git(cwd, "commit", "-q", "-m", "changeset")


def _run(
    gate: str, cwd: Path, *args: str, env_extra: dict | None = None
) -> subprocess.CompletedProcess:
    script = _GATES_DIR / f"{gate}.sh"
    env = {**os.environ, "GATE_TIMEOUT": "20", "GATE_RETRIES": "1"}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+(\+\d{2}:\d{2})?")


def _findings_from(marker: str, stdout: str) -> str:
    idx = stdout.find(marker)
    assert idx != -1, f"{marker!r} not found in: {stdout}"
    # black's --diff header embeds each file's mtime, which legitimately
    # differs by microseconds between two subprocess invocations of the same
    # fixture — normalize it out so this asserts finding *content* parity,
    # not incidental timing.
    return _TIMESTAMP_RE.sub("<ts>", stdout[idx:])


# ── TC-P1 — lint_check parity ────────────────────────────────────────────────


@pytest.mark.skipif(not (_FLAKE8 and _BLACK), reason="flake8/black not installed")
def test_lint_check_diff_matches_explicit(tmp_path):
    _build_fixture(tmp_path)

    diff_res = _run("lint_check", tmp_path, "--diff", "HEAD~1")
    explicit_res = _run("lint_check", tmp_path, "bad.py", "notes.md", "helper.sh")

    assert diff_res.returncode == explicit_res.returncode == 1
    assert _findings_from("=== flake8 ===", diff_res.stdout) == _findings_from(
        "=== flake8 ===", explicit_res.stdout
    )


# ── TC-P2 — type_check parity ────────────────────────────────────────────────


@pytest.mark.skipif(not _MYPY, reason="mypy not installed")
def test_type_check_diff_matches_explicit(tmp_path):
    _build_fixture(tmp_path)

    diff_res = _run("type_check", tmp_path, "--diff", "HEAD~1")
    explicit_res = _run("type_check", tmp_path, "bad.py", "notes.md", "helper.sh")

    assert diff_res.returncode == explicit_res.returncode == 1
    assert _findings_from("=== mypy ===", diff_res.stdout) == _findings_from(
        "=== mypy ===", explicit_res.stdout
    )


# ── TC-P3 — portability_check parity ─────────────────────────────────────────


def test_portability_check_diff_matches_explicit(tmp_path):
    _build_fixture(tmp_path, extra_files={"homepath.py": _HOME_PATH_LINE})

    diff_res = _run("portability_check", tmp_path, "--diff", "HEAD~1")
    explicit_res = _run(
        "portability_check", tmp_path, "bad.py", "notes.md", "helper.sh", "homepath.py"
    )

    assert diff_res.returncode == explicit_res.returncode == 1
    assert _findings_from("machine-specific absolute path", diff_res.stdout) == _findings_from(
        "machine-specific absolute path", explicit_res.stdout
    )


# ── TC-P4 — secret_scan primary AC-4 ─────────────────────────────────────────


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_secret_scan_diff_detects_planted_secret(tmp_path):
    _build_fixture(tmp_path, extra_files={"creds.py": _SECRET_LINE})

    res = _run("secret_scan", tmp_path, "--diff", "HEAD~1")
    assert res.returncode == 1
    assert "potential secret" in res.stdout.lower()
    assert "did not complete after retries" not in res.stdout


# ── TC-P5/TC-P6 — Ruling H seam ──────────────────────────────────────────────

_STUB_EXIT_2 = "#!/usr/bin/env bash\nexit 2\n"


def test_secret_scan_bin_seam_reports_usage_error_not_flakiness(tmp_path):
    _build_fixture(tmp_path)
    stub = tmp_path / "fake-detect-secrets.sh"
    stub.write_text(_STUB_EXIT_2)
    stub.chmod(0o755)

    res = _run(
        "secret_scan",
        tmp_path,
        "--diff",
        "HEAD~1",
        env_extra={"HOS_DETECT_SECRETS_BIN": str(stub)},
    )
    assert res.returncode == 1
    assert "rejected its arguments (exit 2 — a usage error, not tool flakiness)" in res.stdout
    assert "did not complete after retries" not in res.stdout


@pytest.mark.skipif(not _DETECT_SECRETS, reason="detect-secrets not installed")
def test_secret_scan_bin_seam_inert_when_unset(tmp_path):
    _build_fixture(tmp_path)
    res = _run("secret_scan", tmp_path, "--diff", "HEAD~1")
    # No secret planted in this fixture — the real binary resolution is used
    # and the gate passes cleanly, proving the seam does nothing by default.
    assert res.returncode == 0
    assert "GATE PASS" in res.stdout
