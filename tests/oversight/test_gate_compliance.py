"""Tests for scripts/automation/lib/gate_compliance.py (SPEC-375).

Five required cases:
  - test_absent_gate_results_fails_when_required     REQ-NN-16
  - test_absent_gate_results_passes_when_not_required REQ-NN-16 (no-op)
  - test_failed_gate_produces_compliance_fail        REQ-NN-08
  - test_suspended_gate_ignored                      REQ-NN-08 (suspended)
  - test_composite_critical_threshold                REQ-NN-17

Additional: integration of all three checks, edge cases.
"""

import importlib.util
import json
import tempfile
from pathlib import Path

import pytest

# --------------------------------------------------------------------------- #
# Module loading (mirrors test_suspension_manager.py pattern)                 #
# --------------------------------------------------------------------------- #

_SPEC = importlib.util.spec_from_file_location(
    "gate_compliance",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "automation"
    / "lib"
    / "gate_compliance.py",
)
gc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gc)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _gate_record(gate: str, exit_code: int, suspended: bool) -> dict:
    return {
        "gate": gate,
        "exit_code": exit_code,
        "suspended": suspended,
        "script": f"scripts/oversight/gates/{gate}.sh",
        "ts": "2026-06-16T00:00:00Z",
    }


def _write_gate_results(tmp: Path, records: list[dict]) -> None:
    validators_dir = tmp / ".claudetmp" / "oversight" / "validators"
    validators_dir.mkdir(parents=True, exist_ok=True)
    (validators_dir / "gate-results.json").write_text(json.dumps(records))


def _write_summary(tmp: Path, composite_score: float) -> None:
    validators_dir = tmp / ".claudetmp" / "oversight" / "validators"
    validators_dir.mkdir(parents=True, exist_ok=True)
    (validators_dir / "summary.json").write_text(
        json.dumps({"composite_score": composite_score, "tier": "HIGH"})
    )


def _write_manifest(tmp: Path, step_id: int, gates_required: bool) -> Path:
    manifest_path = tmp / "contract" / "step-manifest.yaml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        f"contract_version: '1'\n"
        f"project: test\n"
        f"steps:\n"
        f"  - id: {step_id}\n"
        f"    name: Test Step\n"
        f"    risk_tier: HIGH\n"
        f"    required_signoffs: [code-review]\n"
        f"    system_test_applicable: false\n"
        + (f"    gates_required: true\n" if gates_required else "")
    )
    return manifest_path


# --------------------------------------------------------------------------- #
# load_gate_results                                                            #
# --------------------------------------------------------------------------- #


def test_load_gate_results_absent_returns_empty_list():
    with tempfile.TemporaryDirectory() as tmp:
        result = gc.load_gate_results(tmp)
    assert result == []


def test_load_gate_results_returns_records():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        records = [_gate_record("lint", 0, False)]
        _write_gate_results(tmp_path, records)
        result = gc.load_gate_results(tmp_path)
    assert result == records


def test_load_gate_results_invalid_json_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        validators_dir = tmp_path / ".claudetmp" / "oversight" / "validators"
        validators_dir.mkdir(parents=True)
        (validators_dir / "gate-results.json").write_text("not valid json {{{")
        result = gc.load_gate_results(tmp_path)
    assert result == []


def test_load_gate_results_non_list_json_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        validators_dir = tmp_path / ".claudetmp" / "oversight" / "validators"
        validators_dir.mkdir(parents=True)
        (validators_dir / "gate-results.json").write_text('{"not": "a list"}')
        result = gc.load_gate_results(tmp_path)
    assert result == []


# --------------------------------------------------------------------------- #
# load_composite_score                                                         #
# --------------------------------------------------------------------------- #


def test_load_composite_score_absent_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        result = gc.load_composite_score(tmp)
    assert result is None


def test_load_composite_score_reads_value():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_summary(tmp_path, 0.65)
        result = gc.load_composite_score(tmp_path)
    assert result == pytest.approx(0.65)


def test_load_composite_score_missing_field_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        validators_dir = tmp_path / ".claudetmp" / "oversight" / "validators"
        validators_dir.mkdir(parents=True)
        (validators_dir / "summary.json").write_text('{"tier": "HIGH"}')
        result = gc.load_composite_score(tmp_path)
    assert result is None


# --------------------------------------------------------------------------- #
# gates_required                                                               #
# --------------------------------------------------------------------------- #


def test_gates_required_true_when_declared():
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _write_manifest(Path(tmp), step_id=2, gates_required=True)
        assert gc.gates_required(manifest, 2) is True


def test_gates_required_false_when_absent():
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _write_manifest(Path(tmp), step_id=2, gates_required=False)
        assert gc.gates_required(manifest, 2) is False


def test_gates_required_false_when_manifest_missing():
    result = gc.gates_required("/nonexistent/path/step-manifest.yaml", 1)
    assert result is False


def test_gates_required_string_step_id():
    """Caller may pass step as a string — must still match integer id in YAML."""
    with tempfile.TemporaryDirectory() as tmp:
        manifest = _write_manifest(Path(tmp), step_id=3, gates_required=True)
        assert gc.gates_required(manifest, "3") is True


# --------------------------------------------------------------------------- #
# REQ-GATE-NN-16: absent gate-results when required                           #
# --------------------------------------------------------------------------- #


def test_absent_gate_results_fails_when_required():
    """Empty gate_results + gates_required=True → compliance fail REQ-NN-16."""
    failures = gc.check_gate_compliance(
        gate_results=[],
        composite_score=None,
        step=1,
        gates_required=True,
    )
    assert len(failures) == 1
    assert "REQ-GATE-NN-16" in failures[0]
    assert "step 1" in failures[0]


def test_absent_gate_results_passes_when_not_required():
    """Empty gate_results + gates_required=False → no compliance failure."""
    failures = gc.check_gate_compliance(
        gate_results=[],
        composite_score=None,
        step=1,
        gates_required=False,
    )
    assert failures == []


# --------------------------------------------------------------------------- #
# REQ-GATE-NN-08: failed non-suspended gate                                   #
# --------------------------------------------------------------------------- #


def test_failed_gate_produces_compliance_fail():
    """exit_code=1, suspended=False → fail REQ-NN-08."""
    results = [_gate_record("security", exit_code=1, suspended=False)]
    failures = gc.check_gate_compliance(
        gate_results=results,
        composite_score=None,
        step=2,
        gates_required=False,
    )
    assert len(failures) == 1
    assert "REQ-GATE-NN-08" in failures[0]
    assert "security" in failures[0]
    assert "exit 1" in failures[0]


def test_suspended_gate_ignored():
    """exit_code=1, suspended=True → no compliance failure."""
    results = [_gate_record("lint", exit_code=1, suspended=True)]
    failures = gc.check_gate_compliance(
        gate_results=results,
        composite_score=None,
        step=2,
        gates_required=False,
    )
    assert failures == []


def test_passed_gate_no_failure():
    """exit_code=0, suspended=False → no failure regardless."""
    results = [_gate_record("lint", exit_code=0, suspended=False)]
    failures = gc.check_gate_compliance(
        gate_results=results,
        composite_score=None,
        step=1,
        gates_required=False,
    )
    assert failures == []


def test_multiple_failed_gates_all_reported():
    results = [
        _gate_record("lint", exit_code=1, suspended=False),
        _gate_record("security", exit_code=2, suspended=False),
        _gate_record("types", exit_code=1, suspended=True),  # suspended — ignored
    ]
    failures = gc.check_gate_compliance(
        gate_results=results,
        composite_score=None,
        step=3,
        gates_required=False,
    )
    assert len(failures) == 2
    gate_names = [f for f in failures if "lint" in f or "security" in f]
    assert len(gate_names) == 2


# --------------------------------------------------------------------------- #
# REQ-GATE-NN-17: composite score >= CRITICAL threshold                       #
# --------------------------------------------------------------------------- #


def test_composite_critical_threshold_at_boundary():
    """score=0.78 → fail REQ-NN-17; score=0.77 → no fail."""
    at_boundary = gc.check_gate_compliance(
        gate_results=[],
        composite_score=0.78,
        step=1,
        gates_required=False,
    )
    assert len(at_boundary) == 1
    assert "REQ-GATE-NN-17" in at_boundary[0]
    assert "0.780" in at_boundary[0]

    below_boundary = gc.check_gate_compliance(
        gate_results=[],
        composite_score=0.77,
        step=1,
        gates_required=False,
    )
    assert below_boundary == []


def test_composite_score_none_no_failure():
    """When composite_score is None (summary.json absent), REQ-NN-17 is silent."""
    failures = gc.check_gate_compliance(
        gate_results=[],
        composite_score=None,
        step=1,
        gates_required=False,
    )
    assert failures == []


def test_composite_above_threshold():
    failures = gc.check_gate_compliance(
        gate_results=[],
        composite_score=0.95,
        step=4,
        gates_required=False,
    )
    assert len(failures) == 1
    assert "REQ-GATE-NN-17" in failures[0]


# --------------------------------------------------------------------------- #
# Combined scenarios                                                           #
# --------------------------------------------------------------------------- #


def test_all_three_failures_reported_together():
    """All three REQ checks can fire simultaneously."""
    results = [_gate_record("security", exit_code=1, suspended=False)]
    failures = gc.check_gate_compliance(
        gate_results=results,
        composite_score=0.90,
        step=5,
        gates_required=True,  # results non-empty so REQ-NN-16 does NOT fire here
    )
    # gates_required=True but results is non-empty → no REQ-NN-16 failure
    assert len(failures) == 2
    assert any("REQ-GATE-NN-08" in f for f in failures)
    assert any("REQ-GATE-NN-17" in f for f in failures)


def test_all_three_reqs_fire_with_empty_results_and_critical_score():
    """Empty results + gates_required=True + critical score → two failures."""
    failures = gc.check_gate_compliance(
        gate_results=[],
        composite_score=0.80,
        step=6,
        gates_required=True,
    )
    assert len(failures) == 2
    assert any("REQ-GATE-NN-16" in f for f in failures)
    assert any("REQ-GATE-NN-17" in f for f in failures)


def test_clean_state_no_failures():
    """All checks pass when everything is in order."""
    results = [
        _gate_record("lint", 0, False),
        _gate_record("security", 0, False),
        _gate_record("types", 1, True),  # suspended — does not count
    ]
    failures = gc.check_gate_compliance(
        gate_results=results,
        composite_score=0.45,
        step=1,
        gates_required=True,
    )
    assert failures == []
