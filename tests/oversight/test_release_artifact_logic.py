"""Tests for scripts/oversight/release_artifact_logic.py — release-gate deep
artifact validation (#695).

These exercise the public interface with synthetic inputs / tmp dirs — no
subprocess, network, git, gh, or live release run (matching the purity pattern
in test_release_logic.py).

Coverage:
  AC1 — artifact integrity check: missing field, bad score range, malformed JSON.
  AC2 — blocking-findings extraction: correct severity filtering.
  AC3 — validate_release_artifacts: no artifacts found → pass (graceful skip).
  AC4 — validate_release_artifacts: LOW tier step → pass, no escalation.
  AC5 — validate_release_artifacts: HIGH tier, no blocking findings → pass with warning.
  AC6 — validate_release_artifacts: HIGH tier WITH blocking findings → escalate.
  AC7 — validate_release_artifacts: CRITICAL tier WITH blocking findings → escalate.
  AC8 — validate_release_artifacts: unreadable artifact → escalate.
  AC9 — validate_release_artifacts: manifest provided, all stamps present → pass.
  AC10 — validate_release_artifacts: manifest provided, missing stamp → escalate.
  AC11 — validate_release_artifacts: manifest provided, invalid stamp status → escalate.
  AC12 — to_audit_event produces correct structure.
  AC13 — validate_release_artifacts: parse error in summary.json → escalate.
  AC14 — mixed steps: one LOW, one HIGH+blocking, one CRITICAL+clean → escalate for HIGH.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_MOD_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "oversight"
    / "release_artifact_logic.py"
)
_spec = importlib.util.spec_from_file_location("release_artifact_logic", _MOD_PATH)
ral = importlib.util.module_from_spec(_spec)
# @dataclass introspects sys.modules[cls.__module__] — register before exec_module.
sys.modules["release_artifact_logic"] = ral
_spec.loader.exec_module(ral)

check_artifact_integrity = ral.check_artifact_integrity
extract_blocking_findings = ral.extract_blocking_findings
validate_release_artifacts = ral.validate_release_artifacts

# ── shared fixture helpers ────────────────────────────────────────────────────


def _make_summary(
    step: int,
    tier: str,
    composite_score: float = 0.1,
    results: list | None = None,
) -> dict:
    """Minimal valid summary.json dict for a step."""
    return {
        "head_sha": "abc123",
        "head_sha_source": "git_head_fallback",
        "artifact_version": "1",
        "step": step,
        "written_at": "2026-01-01T00:00:00Z",
        "composite_score": composite_score,
        "tier": tier,
        "validator_count": 2,
        "successful_validators": 2,
        "results": results or [],
    }


def _write_summary(step_dir: Path, data: dict) -> None:
    """Write a summary.json into a step subdirectory."""
    step_dir.mkdir(parents=True, exist_ok=True)
    (step_dir / "summary.json").write_text(json.dumps(data), encoding="utf-8")


def _write_stamp(signoffs_dir: Path, role: str, status: str = "APPROVED") -> None:
    """Write a minimal .stamp file for a role."""
    signoffs_dir.mkdir(parents=True, exist_ok=True)
    (signoffs_dir / f"{role}.stamp").write_text(
        f"role: {role}\nstatus: {status}\nsigned_at: 2026-01-01T00:00:00Z\n",
        encoding="utf-8",
    )


def _manifest(required_roles: list[str]) -> dict:
    """Minimal manifest dict with a single step requiring the given roles."""
    return {
        "contract_version": "1",
        "role_mappings": {r: r + "-agent" for r in required_roles},
        "steps": [
            {
                "id": 1,
                "name": "Test Step",
                "risk_tier": "LOW",
                "required_signoffs": required_roles,
            }
        ],
    }


# ── AC1 — artifact integrity ──────────────────────────────────────────────────


def test_ac1_valid_artifact_passes():
    assert check_artifact_integrity(_make_summary(1, "LOW")) is None


def test_ac1_missing_tier():
    d = _make_summary(1, "LOW")
    del d["tier"]
    assert "tier" in check_artifact_integrity(d)


def test_ac1_missing_head_sha():
    d = _make_summary(1, "LOW")
    del d["head_sha"]
    assert "head_sha" in check_artifact_integrity(d)


def test_ac1_missing_composite_score():
    d = _make_summary(1, "LOW")
    del d["composite_score"]
    assert "composite_score" in check_artifact_integrity(d)


def test_ac1_non_numeric_score():
    d = _make_summary(1, "LOW")
    d["composite_score"] = "bad"
    assert "numeric" in check_artifact_integrity(d)


def test_ac1_score_out_of_range_high():
    d = _make_summary(1, "LOW")
    d["composite_score"] = 1.5
    assert "out of range" in check_artifact_integrity(d)


def test_ac1_score_out_of_range_low():
    d = _make_summary(1, "LOW")
    d["composite_score"] = -0.1
    assert "out of range" in check_artifact_integrity(d)


def test_ac1_score_boundary_zero_passes():
    d = _make_summary(1, "LOW", composite_score=0.0)
    assert check_artifact_integrity(d) is None


def test_ac1_score_boundary_one_passes():
    d = _make_summary(1, "HIGH", composite_score=1.0)
    assert check_artifact_integrity(d) is None


# ── AC2 — blocking-findings extraction ────────────────────────────────────────


def test_ac2_no_results_returns_empty():
    assert extract_blocking_findings([]) == []


def test_ac2_no_findings_in_result():
    results = [{"dimension": "complexity", "score": 0.3, "findings": []}]
    assert extract_blocking_findings(results) == []


def test_ac2_low_severity_not_included():
    results = [
        {
            "dimension": "complexity",
            "findings": [{"severity": "low", "message": "fine"}],
        }
    ]
    assert extract_blocking_findings(results) == []


def test_ac2_warning_severity_not_included():
    results = [
        {
            "dimension": "diff_size",
            "findings": [{"severity": "warning", "message": "ok"}],
        }
    ]
    assert extract_blocking_findings(results) == []


def test_ac2_critical_severity_included():
    finding = {"severity": "critical", "message": "bad"}
    results = [{"dimension": "security", "findings": [finding]}]
    out = extract_blocking_findings(results)
    assert len(out) == 1
    assert out[0]["severity"] == "critical"
    assert out[0]["_dimension"] == "security"


def test_ac2_high_severity_included():
    finding = {"severity": "high", "message": "risky"}
    results = [{"dimension": "rn", "findings": [finding]}]
    out = extract_blocking_findings(results)
    assert len(out) == 1


def test_ac2_blocking_severity_included():
    finding = {"severity": "blocking", "message": "must fix"}
    results = [{"dimension": "static", "findings": [finding]}]
    out = extract_blocking_findings(results)
    assert len(out) == 1


def test_ac2_severity_case_insensitive():
    results = [
        {"dimension": "x", "findings": [{"severity": "CRITICAL", "message": "bad"}]}
    ]
    assert len(extract_blocking_findings(results)) == 1


def test_ac2_mixed_severities_only_blocking_extracted():
    results = [
        {
            "dimension": "x",
            "findings": [
                {"severity": "low"},
                {"severity": "critical"},
                {"severity": "warning"},
                {"severity": "blocking"},
            ],
        }
    ]
    out = extract_blocking_findings(results)
    assert len(out) == 2


def test_ac2_multiple_dimensions_combined():
    results = [
        {"dimension": "a", "findings": [{"severity": "critical"}]},
        {"dimension": "b", "findings": [{"severity": "high"}]},
    ]
    out = extract_blocking_findings(results)
    assert len(out) == 2
    dimensions = {f["_dimension"] for f in out}
    assert dimensions == {"a", "b"}


# ── AC3 — no artifacts → pass (graceful skip) ────────────────────────────────


def test_ac3_no_validators_dir_passes(tmp_path):
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "pass"
    assert result.steps_found == 0
    assert result.escalation_reasons == []


def test_ac3_empty_validators_dir_passes(tmp_path):
    (tmp_path / "signoffs" / "validators").mkdir(parents=True)
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "pass"
    assert result.steps_found == 0


# ── AC4 — LOW tier step → pass ────────────────────────────────────────────────


def test_ac4_single_low_tier_step_passes(tmp_path):
    step_dir = tmp_path / "signoffs" / "validators" / "step1"
    _write_summary(step_dir, _make_summary(1, "LOW", composite_score=0.1))
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "pass"
    assert result.steps_found == 1
    assert result.high_plus_steps == []
    assert result.escalation_reasons == []
    assert "signoffs/validators/step1/summary.json" in result.artifacts_read


# ── AC5 — HIGH tier, no blocking findings → pass with warning ─────────────────


def test_ac5_high_tier_no_blocking_findings_passes(tmp_path):
    step_dir = tmp_path / "signoffs" / "validators" / "step2"
    _write_summary(
        step_dir,
        _make_summary(
            2,
            "HIGH",
            composite_score=0.8,
            results=[
                {"dimension": "complexity", "score": 0.8, "findings": [{"severity": "medium"}]}
            ],
        ),
    )
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "pass"
    assert len(result.high_plus_steps) == 1
    assert result.high_plus_steps[0].tier == "HIGH"
    assert result.escalation_reasons == []
    assert any("HIGH" in w for w in result.warnings)


# ── AC6 — HIGH tier WITH blocking findings → escalate ────────────────────────


def test_ac6_high_tier_with_blocking_findings_escalates(tmp_path):
    step_dir = tmp_path / "signoffs" / "validators" / "step3"
    _write_summary(
        step_dir,
        _make_summary(
            3,
            "HIGH",
            composite_score=0.9,
            results=[
                {"dimension": "static", "findings": [{"severity": "critical", "message": "SQL injection"}]}
            ],
        ),
    )
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "escalate"
    assert result.should_escalate
    assert len(result.escalation_reasons) == 1
    assert "HIGH" in result.escalation_reasons[0]
    assert "blocking" in result.escalation_reasons[0]


# ── AC7 — CRITICAL tier WITH blocking findings → escalate ────────────────────


def test_ac7_critical_tier_with_blocking_findings_escalates(tmp_path):
    step_dir = tmp_path / "signoffs" / "validators" / "step4"
    _write_summary(
        step_dir,
        _make_summary(
            4,
            "CRITICAL",
            composite_score=1.0,
            results=[
                {"dimension": "rn", "findings": [{"severity": "high", "message": "complex"}]}
            ],
        ),
    )
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "escalate"
    assert any("CRITICAL" in r for r in result.escalation_reasons)


# ── AC8 — unreadable artifact → escalate ─────────────────────────────────────


def test_ac8_malformed_json_escalates(tmp_path):
    step_dir = tmp_path / "signoffs" / "validators" / "step5"
    step_dir.mkdir(parents=True)
    (step_dir / "summary.json").write_text("{not valid json}", encoding="utf-8")
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "escalate"
    assert any("parse error" in r.lower() for r in result.escalation_reasons)


def test_ac8_missing_required_field_escalates(tmp_path):
    step_dir = tmp_path / "signoffs" / "validators" / "step6"
    d = _make_summary(6, "LOW")
    del d["head_sha"]
    _write_summary(step_dir, d)
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "escalate"
    assert any("head_sha" in r for r in result.escalation_reasons)


# ── AC9 — manifest provided, all stamps present → pass ───────────────────────


def test_ac9_all_stamps_present_passes(tmp_path):
    _write_stamp(tmp_path / "signoffs", "code-review")
    _write_stamp(tmp_path / "signoffs", "security")
    manifest = _manifest(["code-review", "security"])
    result = validate_release_artifacts(tmp_path, manifest_data=manifest)
    assert result.verdict == "pass"
    assert result.missing_signoffs == []


def test_ac9_no_manifest_skips_signoff_check(tmp_path):
    result = validate_release_artifacts(tmp_path, manifest_data=None)
    assert result.verdict == "pass"
    assert result.missing_signoffs == []


# ── AC10 — manifest provided, missing stamp → escalate ───────────────────────


def test_ac10_missing_stamp_escalates(tmp_path):
    _write_stamp(tmp_path / "signoffs", "code-review")
    # security stamp is missing
    manifest = _manifest(["code-review", "security"])
    result = validate_release_artifacts(tmp_path, manifest_data=manifest)
    assert result.verdict == "escalate"
    assert "security" in result.missing_signoffs
    assert any("security" in r for r in result.escalation_reasons)


# ── AC11 — manifest provided, invalid stamp status → escalate ────────────────


def test_ac11_invalid_stamp_status_escalates(tmp_path):
    _write_stamp(tmp_path / "signoffs", "code-review", status="ESCALATED")
    manifest = _manifest(["code-review"])
    result = validate_release_artifacts(tmp_path, manifest_data=manifest)
    assert result.verdict == "escalate"
    assert "code-review" in result.missing_signoffs


def test_ac11_conditional_stamp_passes(tmp_path):
    _write_stamp(tmp_path / "signoffs", "code-review", status="CONDITIONAL")
    manifest = _manifest(["code-review"])
    result = validate_release_artifacts(tmp_path, manifest_data=manifest)
    assert result.verdict == "pass"


def test_ac11_not_applicable_stamp_passes(tmp_path):
    _write_stamp(tmp_path / "signoffs", "code-review", status="NOT_APPLICABLE")
    manifest = _manifest(["code-review"])
    result = validate_release_artifacts(tmp_path, manifest_data=manifest)
    assert result.verdict == "pass"


# ── #968 — per-branch namespaced stamps satisfy the aggregating release gate ──


def test_namespaced_stamp_satisfies_release(tmp_path):
    # Stamps committed under per-branch namespaces (no legacy flat stamp) must
    # still satisfy the release gate, which aggregates across all namespaces.
    _write_stamp(tmp_path / "signoffs" / "branch-a", "code-review")
    _write_stamp(tmp_path / "signoffs" / "branch-b", "security")
    manifest = _manifest(["code-review", "security"])
    result = validate_release_artifacts(tmp_path, manifest_data=manifest)
    assert result.verdict == "pass"
    assert result.missing_signoffs == []


def test_validators_subdir_is_not_a_namespace(tmp_path):
    # signoffs/validators/ holds validator artifacts, not stamps — it must never
    # be treated as a stamp namespace, so a required role with only a stray file
    # there is still reported missing.
    (tmp_path / "signoffs" / "validators").mkdir(parents=True)
    (tmp_path / "signoffs" / "validators" / "code-review.stamp").write_text(
        "role: code-review\nstatus: APPROVED\n", encoding="utf-8"
    )
    manifest = _manifest(["code-review"])
    result = validate_release_artifacts(tmp_path, manifest_data=manifest)
    assert result.verdict == "escalate"
    assert "code-review" in result.missing_signoffs


def test_namespaced_overrides_invalid_legacy(tmp_path):
    # A valid namespaced stamp satisfies the role even if a stale legacy flat
    # stamp has an invalid status (any valid stamp across namespaces suffices).
    _write_stamp(tmp_path / "signoffs", "code-review", status="ESCALATED")
    _write_stamp(tmp_path / "signoffs" / "branch-a", "code-review", status="APPROVED")
    manifest = _manifest(["code-review"])
    result = validate_release_artifacts(tmp_path, manifest_data=manifest)
    assert result.verdict == "pass"


# ── AC12 — audit event structure ─────────────────────────────────────────────


def test_ac12_audit_event_structure(tmp_path):
    step_dir = tmp_path / "signoffs" / "validators" / "step1"
    _write_summary(step_dir, _make_summary(1, "LOW"))
    result = validate_release_artifacts(tmp_path)
    event = result.to_audit_event(version="v0.4.2", timestamp="2026-06-23T04:31:38Z")
    assert event["event"] == "release-artifact-validation"
    assert event["version"] == "v0.4.2"
    assert event["verdict"] == "pass"
    assert event["timestamp"] == "2026-06-23T04:31:38Z"
    assert event["steps_found"] == 1
    assert isinstance(event["escalation_reasons"], list)
    assert isinstance(event["artifacts_read"], list)


def test_ac12_audit_event_escalate_records_reasons(tmp_path):
    step_dir = tmp_path / "signoffs" / "validators" / "step1"
    _write_summary(
        step_dir,
        _make_summary(
            1,
            "CRITICAL",
            composite_score=1.0,
            results=[{"dimension": "rn", "findings": [{"severity": "critical"}]}],
        ),
    )
    result = validate_release_artifacts(tmp_path)
    event = result.to_audit_event("v0.4.2", "2026-06-23T00:00:00Z")
    assert event["verdict"] == "escalate"
    assert len(event["escalation_reasons"]) >= 1


def test_audit_event_written_as_per_entry_record(tmp_path):
    """The --log-to path now writes a write-once per-entry record under
    audit/log/ (SPEC-888 #888 P2), readable back via the canonical read-shim."""
    audit_log = ral._load_audit_log()
    step_dir = tmp_path / "signoffs" / "validators" / "step1"
    _write_summary(step_dir, _make_summary(1, "LOW"))
    result = validate_release_artifacts(tmp_path)
    event = result.to_audit_event(version="v0.5.0", timestamp="2026-06-27T17:00:00Z")

    relpath = audit_log.write_event(event, root=str(tmp_path))

    # One record on disk, month-sharded, sorted lexically == chronologically.
    records = list((tmp_path / "audit" / "log").rglob("*.json"))
    assert len(records) == 1
    assert relpath.endswith(".json")
    back = [json.loads(b) for b in audit_log.read_stream(str(tmp_path))]
    assert len(back) == 1
    assert back[0]["event"] == "release-artifact-validation"
    assert back[0]["version"] == "v0.5.0"


# ── AC13 — parse error in summary.json → escalate ────────────────────────────


def test_ac13_empty_file_escalates(tmp_path):
    step_dir = tmp_path / "signoffs" / "validators" / "step1"
    step_dir.mkdir(parents=True)
    (step_dir / "summary.json").write_text("", encoding="utf-8")
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "escalate"


# ── AC14 — mixed steps ────────────────────────────────────────────────────────


def test_ac14_mixed_steps_escalates_for_blocking(tmp_path):
    validators = tmp_path / "signoffs" / "validators"
    _write_summary(validators / "step1", _make_summary(1, "LOW"))
    _write_summary(
        validators / "step2",
        _make_summary(
            2,
            "HIGH",
            results=[{"dimension": "a", "findings": [{"severity": "critical"}]}],
        ),
    )
    _write_summary(
        validators / "step3",
        _make_summary(3, "CRITICAL", composite_score=0.9),  # no blocking findings
    )
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "escalate"
    assert result.steps_found == 3
    # step2 escalates (HIGH + blocking); step3 warns (CRITICAL, no blocking)
    assert len(result.high_plus_steps) == 2
    escalation_steps = [r for r in result.escalation_reasons if "step 2" in r]
    assert len(escalation_steps) == 1
    warning_steps = [w for w in result.warnings if "CRITICAL" in w]
    assert len(warning_steps) == 1


def test_ac14_multiple_clean_high_tier_steps_all_warn(tmp_path):
    validators = tmp_path / "signoffs" / "validators"
    for i in range(1, 4):
        _write_summary(validators / f"step{i}", _make_summary(i, "HIGH"))
    result = validate_release_artifacts(tmp_path)
    assert result.verdict == "pass"
    assert len(result.warnings) == 3
    assert result.steps_found == 3


# ── #984 — sign-off stamps must be committed (no uncommitted / stale accept) ──
#
# (b) _role_stamp_paths counts any on-disk stamp; a worker `touch`ing
# signoffs/x/security.stamp with status APPROVED just before a release run —
# never committed, never reviewed — must NOT satisfy the release gate. The CLI
# injects a git-backed commit_time_fn; only stamps with commit_time > 0 count.


def test_984_uncommitted_stamp_does_not_count(tmp_path):
    # Stamp exists on disk with a valid status but has no committed history
    # (commit_time 0) → treated as missing → escalate.
    _write_stamp(tmp_path / "signoffs", "security", status="APPROVED")
    manifest = _manifest(["security"])
    result = validate_release_artifacts(
        tmp_path, manifest_data=manifest, commit_time_fn=lambda p: 0
    )
    assert result.verdict == "escalate"
    assert "security" in result.missing_signoffs
    assert any("security" in r for r in result.escalation_reasons)


def test_984_committed_stamp_counts(tmp_path):
    # Same stamp, but the injected clock reports committed history → pass.
    _write_stamp(tmp_path / "signoffs", "security", status="APPROVED")
    manifest = _manifest(["security"])
    result = validate_release_artifacts(
        tmp_path, manifest_data=manifest, commit_time_fn=lambda p: 1_700_000_000
    )
    assert result.verdict == "pass"
    assert result.missing_signoffs == []


def test_984_committed_stamp_beats_uncommitted_sibling(tmp_path):
    # Two namespaces carry the role: one committed, one not. The role is
    # satisfied because at least one committed valid-status stamp exists.
    _write_stamp(tmp_path / "signoffs" / "branch-uncommitted", "security")
    committed = tmp_path / "signoffs" / "branch-committed" / "security.stamp"
    _write_stamp(tmp_path / "signoffs" / "branch-committed", "security")
    manifest = _manifest(["security"])
    result = validate_release_artifacts(
        tmp_path,
        manifest_data=manifest,
        commit_time_fn=lambda p: 1_700_000_000 if p == committed else 0,
    )
    assert result.verdict == "pass"
    assert result.missing_signoffs == []


def test_984_all_uncommitted_stamps_escalate(tmp_path):
    # Every candidate stamp is uncommitted → role reported missing.
    _write_stamp(tmp_path / "signoffs" / "branch-a", "security")
    _write_stamp(tmp_path / "signoffs" / "branch-b", "security")
    manifest = _manifest(["security"])
    result = validate_release_artifacts(
        tmp_path, manifest_data=manifest, commit_time_fn=lambda p: 0
    )
    assert result.verdict == "escalate"
    assert "security" in result.missing_signoffs


def test_984_commit_time_fn_none_preserves_pure_path(tmp_path):
    # Backward compatibility: with no commit_time_fn injected, on-disk presence
    # alone satisfies the role (the pure, subprocess-free path unit tests use).
    _write_stamp(tmp_path / "signoffs", "security", status="APPROVED")
    manifest = _manifest(["security"])
    result = validate_release_artifacts(tmp_path, manifest_data=manifest)
    assert result.verdict == "pass"


def test_984_git_commit_time_untracked_returns_zero(tmp_path):
    # The git helper degrades to 0 (not committed) for a path with no history —
    # here a non-repository tmp dir — so an unverifiable stamp never counts.
    stamp = tmp_path / "signoffs" / "x" / "security.stamp"
    stamp.parent.mkdir(parents=True)
    stamp.write_text("status: APPROVED\n", encoding="utf-8")
    assert ral._git_commit_time(tmp_path, stamp) == 0


# ── #984 — a requested but unloadable --manifest fails closed (exit 2) ────────
#
# (a) _load_manifest returned None on any failure and _cmd_validate warned +
# skipped sign-off completeness → exit 0. A YAML typo (or a venv without PyYAML)
# would silently skip release sign-off completeness. Now: exit 2, matching
# signoff_gate.py.


def _write_manifest_yaml(tmp_path, text: str) -> str:
    path = tmp_path / "step-manifest.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_984_missing_manifest_path_exits_2(tmp_path):
    missing = str(tmp_path / "does-not-exist.yaml")
    rc = ral.main(["validate", "--repo-root", str(tmp_path), "--manifest", missing])
    assert rc == 2


def test_984_malformed_manifest_exits_2(tmp_path):
    # Unbalanced brackets → YAMLError → fail closed.
    bad = _write_manifest_yaml(tmp_path, "steps: [ {id: 1, required_signoffs: [sec }\n")
    rc = ral.main(["validate", "--repo-root", str(tmp_path), "--manifest", bad])
    assert rc == 2


def test_984_non_mapping_manifest_exits_2(tmp_path):
    # Valid YAML that is a scalar, not a mapping → fail closed.
    scalar = _write_manifest_yaml(tmp_path, "just a string\n")
    rc = ral.main(["validate", "--repo-root", str(tmp_path), "--manifest", scalar])
    assert rc == 2


def test_984_no_manifest_flag_does_not_exit_2(tmp_path):
    # Manifest-free deployment: sign-off completeness is legitimately skipped,
    # NOT a fail-closed error. No artifacts, no manifest → pass (exit 0).
    rc = ral.main(["validate", "--repo-root", str(tmp_path)])
    assert rc == 0


@pytest.mark.skipif(ral._yaml is None, reason="PyYAML required to parse manifest")
def test_984_empty_manifest_is_valid_no_roles(tmp_path):
    # An empty-but-valid manifest defines no required roles → loads to {} → the
    # completeness check runs vacuously (no roles) rather than failing closed.
    empty = _write_manifest_yaml(tmp_path, "\n")
    rc = ral.main(["validate", "--repo-root", str(tmp_path), "--manifest", empty])
    assert rc == 0


@pytest.mark.skipif(ral._yaml is None, reason="PyYAML required to parse manifest")
def test_984_cli_uncommitted_stamp_escalates_end_to_end(tmp_path):
    # End-to-end through the CLI in a non-git tree: a required stamp is present
    # on disk but has no commit history, so the git-backed check reports it
    # uncommitted → the release gate escalates (exit 1) instead of passing open.
    _write_stamp(tmp_path / "signoffs", "security", status="APPROVED")
    manifest = _write_manifest_yaml(
        tmp_path, "steps:\n  - id: 1\n    required_signoffs:\n      - security\n"
    )
    rc = ral.main(["validate", "--repo-root", str(tmp_path), "--manifest", manifest])
    assert rc == 1
