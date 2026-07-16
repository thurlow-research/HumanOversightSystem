"""run_validators.sh must not delete run_gates.sh's gate-results.json (#980).

run_gates.sh and run_validators.sh share OUT_DIR=.claudetmp/oversight/validators.
run_gates.sh runs first and records gate-results.json there; the pipeline then
runs run_validators.sh, whose stale-result cleanup previously did a blanket
`rm -f "$OUT_DIR"/*.json` — wiping gate-results.json before the oversight
evaluator's REQ-GATE-NN-08/16 checks (gate_compliance.py) could read it. A failed
gate's evidence vanished and the gate-compliance invariant fail-opened.

The fix scopes the cleanup to spare gate-results.json AND excludes that file from
the composite-summary aggregation (it is a JSON list, not a validator envelope, so
feeding it to the `.get()`-based aggregator would crash it).

The script is driven as a subprocess with cwd set to a throwaway project so its
relative OUT_DIR lands under the temp dir, not the real repo.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_RUN_VALIDATORS = _REPO / "scripts" / "oversight" / "run_validators.sh"
_OUT_REL = Path(".claudetmp") / "oversight" / "validators"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash unavailable"
)

# run_gates.sh writes a JSON *list* of per-gate records.
_GATE_RECORDS = [{"gate": "lint", "exit_code": 1, "suspended": False}]


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    out_dir = tmp_path / _OUT_REL
    out_dir.mkdir(parents=True)
    # Plant the gate artifact (must survive) and a stale validator file (must go).
    (out_dir / "gate-results.json").write_text(json.dumps(_GATE_RECORDS))
    (out_dir / "complexity.json").write_text('{"stale": "prior-run"}')
    (tmp_path / "sample.py").write_text("def f(x):\n    return x\n")

    return subprocess.run(
        ["bash", str(_RUN_VALIDATORS), "sample.py"],
        cwd=tmp_path,
        env={"VALIDATOR_TIMEOUT": "10", "NETWORK_TIMEOUT": "5", "PATH": _path_env()},
        capture_output=True,
        text=True,
    )


def _path_env() -> str:
    import os

    # Prefer the oversight venv bin so the validators' python is found.
    venv_bin = _REPO / "scripts" / "oversight" / ".venv" / "bin"
    base = os.environ.get("PATH", "")
    return f"{venv_bin}:{base}" if venv_bin.exists() else base


def test_gate_results_survives_validator_cleanup(tmp_path: Path):
    proc = _run(tmp_path)
    gate_file = tmp_path / _OUT_REL / "gate-results.json"

    assert gate_file.exists(), (
        "gate-results.json was deleted by run_validators.sh cleanup — "
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    # Content must be untouched (not just present).
    assert json.loads(gate_file.read_text()) == _GATE_RECORDS


def test_stale_validator_file_still_removed(tmp_path: Path):
    _run(tmp_path)
    # The scoped cleanup must still clear stale prior-run validator results;
    # complexity.json is rewritten fresh, so the planted stale copy is gone —
    # verify the cleanup ran by checking the stale sentinel value is not present.
    stale = tmp_path / _OUT_REL / "complexity.json"
    if stale.exists():
        assert json.loads(stale.read_text()).get("stale") != "prior-run"


def test_aggregator_does_not_crash_on_gate_results(tmp_path: Path):
    # Keeping the gate list in OUT_DIR must not crash the summary aggregator,
    # which globs *.json and calls .get() on each entry.
    proc = _run(tmp_path)
    assert proc.returncode == 0, (
        "run_validators.sh exited non-zero — aggregator likely choked on the "
        f"gate-results.json list.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    summary = tmp_path / _OUT_REL / "summary.json"
    assert summary.exists()
