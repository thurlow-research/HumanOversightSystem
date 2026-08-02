"""Tests for scripts/automation/lib/pr_readiness.py (#317, #1131).

Covers:
  - register parsing: multi-entry, latest-wins, missing fields
  - required_signoffs manifest parsing (flow-style list)
  - tier-gte ordering (delegates to merge_authority.RiskTier)
  - ReadinessResult: checks_passed / passed / failures / to_markdown
  - write_session_state: append behavior, hard-fail on write error
  - individual checks that don't require subprocess (risk-assessment scope,
    signoffs present, unresolved escalations, CRITICAL human-authorization,
    second-review verdict, system-test applicability, evaluator verdict,
    handoff artifacts)
  - git-backed checks (Prompt-Artifact trailers, doc currency) against a real
    temp git repo — marked slow
  - end-to-end assess_pr_readiness wiring with every artifact stubbed — marked slow
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.automation.lib.pr_readiness import (
    CheckResult,
    ReadinessResult,
    _check_critical_human_authorization,
    _check_doc_currency,
    _check_evaluator_verdict,
    _check_handoff_artifacts,
    _check_na_domains,
    _check_no_unresolved_escalations,
    _check_prompt_artifact_trailers,
    _check_risk_assessment_scope,
    _check_second_review,
    _check_signoffs_present,
    _check_system_tests,
    _parse_register,
    _parse_required_signoffs,
    _tier_gte,
    assess_pr_readiness,
    write_session_state,
)

BASE = "a" * 40
HEAD = "b" * 40


# ---------------------------------------------------------------------------
# Register parsing
# ---------------------------------------------------------------------------


def test_parse_register_single_entry():
    text = (
        "## code-review | app/views.py | 2026-06-11T14:30Z\n"
        "Status: APPROVED\n"
        "Agent: code-reviewer\n"
        "Artifact: app/views.py\n"
        "Iterations: 2\n"
    )
    entries = _parse_register(text)
    assert len(entries) == 1
    assert entries[0]["role"] == "code-review"
    assert entries[0]["fields"]["Status"] == "APPROVED"
    assert entries[0]["fields"]["Iterations"] == "2"


def test_parse_register_multiple_entries_latest_wins():
    text = (
        "## security | a.py | T1\n"
        "Status: ESCALATED\n"
        "Agent: security-reviewer\n"
        "## security | a.py | T2\n"
        "Status: APPROVED\n"
        "Agent: security-reviewer\n"
        "Artifact: a.py\n"
        "Iterations: 2\n"
    )
    entries = _parse_register(text)
    assert len(entries) == 2
    from scripts.automation.lib.pr_readiness import _latest_entry_by_role
    latest = _latest_entry_by_role(entries, "security")
    assert latest["fields"]["Status"] == "APPROVED"


def test_parse_register_empty_text():
    assert _parse_register("") == []


def test_parse_register_ignores_lines_before_first_header():
    text = "some preamble\nnot: a header\n## code-review | x | t\nStatus: N/A\n"
    entries = _parse_register(text)
    assert len(entries) == 1
    assert entries[0]["fields"]["Status"] == "N/A"


# ---------------------------------------------------------------------------
# required_signoffs manifest parsing
# ---------------------------------------------------------------------------


def test_parse_required_signoffs_finds_step(tmp_path):
    manifest = tmp_path / "step-manifest.yaml"
    manifest.write_text(
        "steps:\n"
        "  - id: 1\n"
        "    name: Scaffold\n"
        "    required_signoffs: [code-review]\n"
        "  - id: 2\n"
        "    name: Auth\n"
        "    required_signoffs: [code-review, security, test-unit]\n"
    )
    assert _parse_required_signoffs(manifest, 1) == ["code-review"]
    assert _parse_required_signoffs(manifest, 2) == ["code-review", "security", "test-unit"]


def test_parse_required_signoffs_missing_step_returns_empty(tmp_path):
    manifest = tmp_path / "step-manifest.yaml"
    manifest.write_text("steps:\n  - id: 1\n    required_signoffs: [code-review]\n")
    assert _parse_required_signoffs(manifest, 99) == []


def test_parse_required_signoffs_missing_file_returns_empty(tmp_path):
    assert _parse_required_signoffs(tmp_path / "nope.yaml", 1) == []


def test_parse_required_signoffs_empty_list(tmp_path):
    manifest = tmp_path / "step-manifest.yaml"
    manifest.write_text("steps:\n  - id: 1\n    required_signoffs: []\n")
    assert _parse_required_signoffs(manifest, 1) == []


# ---------------------------------------------------------------------------
# Tier ordering
# ---------------------------------------------------------------------------


def test_tier_gte_ordering():
    assert _tier_gte("CRITICAL", "MEDIUM") is True
    assert _tier_gte("MEDIUM", "MEDIUM") is True
    assert _tier_gte("LOW", "MEDIUM") is False
    assert _tier_gte("SAFE", "LOW") is False


# ---------------------------------------------------------------------------
# ReadinessResult
# ---------------------------------------------------------------------------


def test_readiness_result_passed_when_all_checks_pass():
    result = ReadinessResult(cid="abc123", step=1, checks=[CheckResult("REQ-W-01", True, "ok")])
    assert result.checks_passed is True
    assert result.passed is True
    assert result.failures == []


def test_readiness_result_failed_when_any_check_fails():
    result = ReadinessResult(
        cid="abc123", step=1,
        checks=[CheckResult("REQ-W-01", True, "ok"), CheckResult("REQ-W-05", False, "missing role")],
    )
    assert result.checks_passed is False
    assert result.passed is False
    assert [c.check_id for c in result.failures] == ["REQ-W-05"]


def test_readiness_result_session_state_error_forces_fail_despite_passing_checks():
    result = ReadinessResult(cid="abc123", step=1, checks=[CheckResult("REQ-W-01", True, "ok")])
    result.session_state_error = "disk full"
    assert result.checks_passed is True
    assert result.passed is False


def test_readiness_result_to_markdown_lists_failures():
    result = ReadinessResult(
        cid="abc123", step=1,
        checks=[CheckResult("REQ-W-06", False, "ESCALATED without Human_resolution: security")],
    )
    md = result.to_markdown(timestamp="2026-08-02T06:00:00Z")
    assert "## Pre-PR gate result" in md
    assert "Result: FAIL" in md
    assert "[REQ-W-06] ESCALATED without Human_resolution: security" in md


# ---------------------------------------------------------------------------
# write_session_state
# ---------------------------------------------------------------------------


def test_write_session_state_appends_and_creates_dir(tmp_path):
    result = ReadinessResult(cid="c1", step=1, checks=[CheckResult("REQ-W-01", True, "ok")])
    write_session_state(tmp_path, result)
    assert result.session_state_written is True
    assert result.session_state_error is None
    content = (tmp_path / ".claudetmp" / "session-state.md").read_text()
    assert "## Pre-PR gate result" in content


def test_write_session_state_preserves_prior_content(tmp_path):
    state_path = tmp_path / ".claudetmp" / "session-state.md"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("# Session State\nprior content\n")
    result = ReadinessResult(cid="c1", step=1, checks=[CheckResult("REQ-W-01", True, "ok")])
    write_session_state(tmp_path, result)
    content = state_path.read_text()
    assert "prior content" in content
    assert "## Pre-PR gate result" in content


def test_write_session_state_failure_recorded(tmp_path):
    # .claudetmp exists as a FILE, not a dir, so mkdir(parents=True, exist_ok=True) raises.
    blocker = tmp_path / ".claudetmp"
    blocker.write_text("not a directory")
    result = ReadinessResult(cid="c1", step=1, checks=[CheckResult("REQ-W-01", True, "ok")])
    write_session_state(tmp_path, result)
    assert result.session_state_written is False
    assert result.session_state_error is not None
    assert result.passed is False


# ---------------------------------------------------------------------------
# Individual checks — no subprocess required
# ---------------------------------------------------------------------------


def test_risk_assessment_scope_matches(tmp_path):
    p = tmp_path / ".claudetmp" / "oversight" / "validators"
    p.mkdir(parents=True)
    (p / "risk-assessment.md").write_text(
        f"# Risk Assessment — Step 1\nvalidated_tier: MEDIUM\nbase_sha: {BASE}\nhead_sha: {HEAD}\n"
    )
    check = _check_risk_assessment_scope(tmp_path, BASE, HEAD)
    assert check.passed is True


def test_risk_assessment_scope_mismatch(tmp_path):
    p = tmp_path / ".claudetmp" / "oversight" / "validators"
    p.mkdir(parents=True)
    (p / "risk-assessment.md").write_text(f"base_sha: {'c' * 40}\nhead_sha: {HEAD}\n")
    check = _check_risk_assessment_scope(tmp_path, BASE, HEAD)
    assert check.passed is False
    assert check.check_id == "REQ-W-04"


def test_risk_assessment_scope_missing_file(tmp_path):
    check = _check_risk_assessment_scope(tmp_path, BASE, HEAD)
    assert check.passed is False


def test_signoffs_present_all_required_roles_ok():
    entries = [
        {"role": "code-review", "fields": {"Status": "APPROVED", "Agent": "code-reviewer", "Artifact": "a.py", "Iterations": "1"}},
        {"role": "security", "fields": {"Status": "N/A", "Agent": "security-reviewer", "Artifact": "a.py", "Iterations": "1"}},
    ]
    check = _check_signoffs_present(entries, True, ["code-review", "security"])
    assert check.passed is True


def test_signoffs_present_missing_role():
    entries = [{"role": "code-review", "fields": {"Status": "APPROVED", "Agent": "x", "Artifact": "a.py", "Iterations": "1"}}]
    check = _check_signoffs_present(entries, True, ["code-review", "security"])
    assert check.passed is False
    assert "security" in check.detail


def test_signoffs_present_missing_required_field():
    entries = [{"role": "code-review", "fields": {"Status": "APPROVED", "Agent": "x"}}]  # no Artifact/Iterations
    check = _check_signoffs_present(entries, True, ["code-review"])
    assert check.passed is False
    assert "Artifact" in check.detail


def test_signoffs_present_register_missing():
    check = _check_signoffs_present([], False, ["code-review"])
    assert check.passed is False


def test_signoffs_present_no_required_roles_configured():
    check = _check_signoffs_present([], True, [])
    assert check.passed is True


def test_no_unresolved_escalations_passes_when_resolved():
    entries = [{"role": "security", "fields": {"Status": "ESCALATED", "Human_resolution": "2026-06-11 — waived by human"}}]
    check = _check_no_unresolved_escalations(entries, True)
    assert check.passed is True


def test_no_unresolved_escalations_fails_when_unresolved():
    entries = [{"role": "security", "fields": {"Status": "ESCALATED"}}]
    check = _check_no_unresolved_escalations(entries, True)
    assert check.passed is False
    assert "security" in check.detail


def test_critical_human_authorization_not_required_below_critical(tmp_path):
    check = _check_critical_human_authorization(tmp_path, 1, "HIGH")
    assert check.passed is True


def test_critical_human_authorization_missing_file(tmp_path):
    check = _check_critical_human_authorization(tmp_path, 1, "CRITICAL")
    assert check.passed is False


def test_critical_human_authorization_present(tmp_path):
    p = tmp_path / ".claudetmp" / "oversight"
    p.mkdir(parents=True)
    (p / "step1-human-authorization.md").write_text("Authorized by ScottThurlow on 2026-08-02.\n")
    check = _check_critical_human_authorization(tmp_path, 1, "CRITICAL")
    assert check.passed is True


def test_second_review_not_required_below_medium(tmp_path):
    check = _check_second_review(tmp_path, 1, "LOW")
    assert check.passed is True


def test_second_review_missing_file_fails(tmp_path):
    check = _check_second_review(tmp_path, 1, "MEDIUM")
    assert check.passed is False


def test_second_review_error_verdict_fails(tmp_path):
    d = tmp_path / ".claudetmp" / "second-review"
    d.mkdir(parents=True)
    (d / "step1-20260802T060000Z.md").write_text("verdict: error\nreviewed_range: none\n")
    check = _check_second_review(tmp_path, 1, "MEDIUM")
    assert check.passed is False


def test_second_review_approve_verdict_passes(tmp_path):
    d = tmp_path / ".claudetmp" / "second-review"
    d.mkdir(parents=True)
    (d / "step1-20260802T060000Z.md").write_text("verdict: approve\nreviewed_range: x..y\n")
    check = _check_second_review(tmp_path, 1, "HIGH")
    assert check.passed is True


def test_system_tests_not_applicable_passes(tmp_path):
    check = _check_system_tests([], False, False)
    assert check.passed is True


def test_system_tests_applicable_missing_entry_fails(tmp_path):
    check = _check_system_tests([], True, True)
    assert check.passed is False


def test_system_tests_applicable_approved_passes():
    entries = [{"role": "test-system", "fields": {"Status": "APPROVED"}}]
    check = _check_system_tests(entries, True, True)
    assert check.passed is True


def test_evaluator_verdict_missing_file_fails(tmp_path):
    check = _check_evaluator_verdict(tmp_path, 1)
    assert check.passed is False


def test_evaluator_verdict_proceed_passes(tmp_path):
    d = tmp_path / ".claudetmp" / "oversight"
    d.mkdir(parents=True)
    (d / "step1-evaluation-20260802T060000Z.md").write_text(
        "## Oversight Evaluation complete — PROCEED\n\n---\n**Recommendation:** PROCEED\n**Reason:** clean.\n"
    )
    check = _check_evaluator_verdict(tmp_path, 1)
    assert check.passed is True


def test_evaluator_verdict_escalate_fails(tmp_path):
    d = tmp_path / ".claudetmp" / "oversight"
    d.mkdir(parents=True)
    (d / "step1-evaluation-20260802T060000Z.md").write_text("**Recommendation:** ESCALATE\n")
    check = _check_evaluator_verdict(tmp_path, 1)
    assert check.passed is False


def test_evaluator_verdict_picks_latest_by_sort_order(tmp_path):
    d = tmp_path / ".claudetmp" / "oversight"
    d.mkdir(parents=True)
    (d / "step1-evaluation-20260802T060000Z.md").write_text("**Recommendation:** ESCALATE\n")
    (d / "step1-evaluation-20260802T070000Z.md").write_text("**Recommendation:** PROCEED\n")
    check = _check_evaluator_verdict(tmp_path, 1)
    assert check.passed is True


def test_handoff_artifacts_both_present(tmp_path):
    d = tmp_path / ".claudetmp" / "oversight"
    d.mkdir(parents=True)
    (d / "step1-panel-context.md").write_text("x")
    (d / "step1-handoff.md").write_text("x")
    check = _check_handoff_artifacts(tmp_path, 1)
    assert check.passed is True


def test_handoff_artifacts_missing_one(tmp_path):
    d = tmp_path / ".claudetmp" / "oversight"
    d.mkdir(parents=True)
    (d / "step1-panel-context.md").write_text("x")
    check = _check_handoff_artifacts(tmp_path, 1)
    assert check.passed is False
    assert "handoff.md" in check.detail


def test_na_domains_no_na_entries_passes(tmp_path):
    check = _check_na_domains(tmp_path, [], BASE, HEAD)
    assert check.passed is True


def test_na_domains_skips_non_checkable_roles(tmp_path):
    entries = [{"role": "code-review", "fields": {"Status": "N/A"}}]
    check = _check_na_domains(tmp_path, entries, BASE, HEAD)
    assert check.passed is True  # code-review has no domain rule — not independently checkable


# ---------------------------------------------------------------------------
# Git-backed checks — real temp git repo
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("init\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")
    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    return repo, base


@pytest.mark.slow
def test_prompt_artifact_trailers_all_present(git_repo):
    repo, base = git_repo
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "add a.py\n\nPrompt-Artifact: none (LOW risk)\n")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    check = _check_prompt_artifact_trailers(repo, base, head, "MEDIUM")
    assert check.passed is True


@pytest.mark.slow
def test_prompt_artifact_trailers_missing(git_repo):
    repo, base = git_repo
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "add a.py without trailer")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    check = _check_prompt_artifact_trailers(repo, base, head, "MEDIUM")
    assert check.passed is False


@pytest.mark.slow
def test_prompt_artifact_trailers_not_required_below_medium(git_repo):
    repo, base = git_repo
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "no trailer")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    check = _check_prompt_artifact_trailers(repo, base, head, "LOW")
    assert check.passed is True


@pytest.mark.slow
def test_doc_currency_no_trigger_passes(git_repo):
    repo, base = git_repo
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "unrelated change")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    check = _check_doc_currency(repo, base, head)
    assert check.passed is True


@pytest.mark.slow
def test_doc_currency_agent_surface_without_docs_fails(git_repo):
    repo, base = git_repo
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "agents" / "worker.md").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "edit agent contract")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    check = _check_doc_currency(repo, base, head)
    assert check.passed is False


@pytest.mark.slow
def test_doc_currency_agent_surface_with_docs_passes(git_repo):
    repo, base = git_repo
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "agents" / "worker.md").write_text("x")
    (repo / "docs").mkdir()
    (repo / "docs" / "NOTE.md").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "edit agent contract with doc update")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    check = _check_doc_currency(repo, base, head)
    assert check.passed is True


# ---------------------------------------------------------------------------
# End-to-end wiring
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_assess_pr_readiness_all_pass(git_repo):
    """Every artifact stubbed minimally so all 14 checks pass; verifies wiring."""
    repo, base = git_repo
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "a.py")
    _git(repo, "commit", "-q", "-m", "add a.py\n\nPrompt-Artifact: none (LOW risk)\n")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()

    # inner-loop test stub — always exits 0
    scripts_dir = repo / "scripts" / "framework"
    scripts_dir.mkdir(parents=True)
    (scripts_dir / "run_tests_inner_loop.sh").write_text("#!/bin/bash\nexit 0\n")

    # step manifest — no required signoffs, system tests not applicable
    contract_dir = repo / "contract"
    contract_dir.mkdir()
    (contract_dir / "step-manifest.yaml").write_text(
        "steps:\n  - id: 1\n    required_signoffs: []\n    system_test_applicable: false\n"
    )

    # register present but empty (no required roles to satisfy)
    signoffs_dir = repo / ".claudetmp" / "signoffs"
    signoffs_dir.mkdir(parents=True)
    (signoffs_dir / "step1-register.md").write_text(f"# Sign-off Register — Step 1\nbase_sha: {base}\nhead_sha: {head}\n")

    # risk-assessment.md scoped correctly
    validators_dir = repo / ".claudetmp" / "oversight" / "validators"
    validators_dir.mkdir(parents=True)
    (validators_dir / "risk-assessment.md").write_text(f"base_sha: {base}\nhead_sha: {head}\nvalidated_tier: LOW\n")
    (validators_dir / "summary.json").write_text('{"composite_score": 0.1}')

    # evaluator verdict + handoff artifacts
    oversight_dir = repo / ".claudetmp" / "oversight"
    (oversight_dir / "step1-evaluation-20260802T060000Z.md").write_text("**Recommendation:** PROCEED\n")
    (oversight_dir / "step1-panel-context.md").write_text("x")
    (oversight_dir / "step1-handoff.md").write_text("x")

    result = assess_pr_readiness(
        "cid123", base, head, 1, "LOW",
        repo_root=repo, system_test_applicable=False, write_state=True,
    )
    assert result.passed, [(c.check_id, c.detail) for c in result.failures]
    assert result.session_state_written is True


@pytest.mark.slow
def test_assess_pr_readiness_fails_closed_when_artifacts_absent(tmp_path):
    (tmp_path / "scripts" / "framework").mkdir(parents=True)
    (tmp_path / "scripts" / "framework" / "run_tests_inner_loop.sh").write_text("#!/bin/bash\nexit 0\n")
    result = assess_pr_readiness(
        "cid123", BASE, HEAD, 1, "LOW",
        repo_root=tmp_path, write_state=False,
    )
    assert result.passed is False
    failing_ids = {c.check_id for c in result.failures}
    assert "REQ-W-04" in failing_ids  # risk-assessment.md absent
    assert "REQ-W-05" in failing_ids  # register absent
    assert "REQ-W-13" in failing_ids  # evaluation file absent
    assert "REQ-W-14" in failing_ids  # panel-context/handoff absent
