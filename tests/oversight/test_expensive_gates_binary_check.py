"""expensive_gates_stub.sh must catch pip-package process managers (#977).

Before the fix KNOWN_BASE_BINARIES whitelisted gunicorn/uvicorn/celery, and
_check_binary_in_requirements returned success for any whitelisted binary
*before* consulting requirements*.txt. Those three are pip packages, not
base-image binaries, so a container that declared e.g. `CMD ["gunicorn", ...]`
while requirements.txt omitted gunicorn recorded a green gate — the exact defect
class the check header says it exists to catch (HOS issue #8 defect 4). The fix
drops the three pip packages from the whitelist while keeping genuine base/init
binaries (python, python3, sh, bash, env, tini, dumb-init).

The gate is driven as a subprocess with cwd set to a throwaway project so its
`for f in Dockerfile* ...` enumeration sees only the planted fixture files.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_GATE = _REPO / "scripts" / "oversight" / "gates" / "expensive_gates_stub.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash unavailable"
)


def _run(cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(_GATE)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("proc_mgr", ["gunicorn", "uvicorn", "celery"])
def test_declared_process_manager_missing_from_requirements_fails(tmp_path, proc_mgr):
    # Container declares the process manager but requirements.txt omits it — the
    # gate must now FAIL and name the missing binary (pre-fix: silent PASS).
    (tmp_path / "Dockerfile").write_text(f'CMD ["{proc_mgr}", "app.wsgi"]\n')
    (tmp_path / "requirements.txt").write_text("django==5.0\n")
    res = _run(tmp_path)
    assert res.returncode == 1, res.stdout
    assert "GATE FAIL" in res.stdout
    assert proc_mgr in res.stdout


def test_declared_process_manager_present_in_requirements_passes(tmp_path):
    # When requirements.txt does list it, the gate passes — the fix must not
    # produce a false positive for a correctly-declared dependency.
    (tmp_path / "Dockerfile").write_text('CMD ["gunicorn", "app.wsgi"]\n')
    (tmp_path / "requirements.txt").write_text("gunicorn==21.2.0\ndjango==5.0\n")
    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout
    assert "GATE PASS" in res.stdout


@pytest.mark.parametrize("base_bin", ["python3", "sh", "bash", "tini", "dumb-init"])
def test_genuine_base_binaries_still_whitelisted(tmp_path, base_bin):
    # Real base-image / init binaries stay whitelisted — declaring one with no
    # requirements.txt entry must still pass (no false positive).
    (tmp_path / "Dockerfile").write_text(f'ENTRYPOINT ["{base_bin}", "-c", "x"]\n')
    res = _run(tmp_path)
    assert res.returncode == 0, res.stdout
    assert "GATE PASS" in res.stdout
