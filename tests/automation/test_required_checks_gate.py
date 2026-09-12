"""Tests for the required-content-checks bounce gate (#1580, overseer.md step 4c).

Covers check_required_content_checks: a PR whose own required, worker-fixable
CI checks (oversight-gate-*, oversight-validator-*, tests, ...) are currently
failing should bounce back to the worker, the same as the register-completeness
gate (step 4a) — regardless of whether the PR also touches a protected surface.
The three approval-gate meta-checks (require-human-approval,
require-overseer-approval, require-tier-ceiling) must never trigger this gate:
a worker push cannot make those pass by itself.
"""

from __future__ import annotations

from unittest.mock import patch

from scripts.automation.lib.merge_authority import (
    RequiredChecksResult,
    check_required_content_checks,
)

OWNER = "thurlow-research"
REPO = "HumanOversightSystem"
HEAD_SHA = "a1b2c3d4e5f6"


def _protection(contexts: list[str]) -> dict:
    return {"required_status_checks": {"strict": False, "contexts": contexts}}


def _run(name: str, conclusion: str | None, status: str = "completed") -> dict:
    return {"name": name, "status": status, "conclusion": conclusion}


def _patch_protection(protection):
    return patch(
        "scripts.automation.lib.merge_authority.get_branch_protection",
        return_value=protection,
    )


def _patch_runs(runs):
    return patch(
        "scripts.automation.lib.merge_authority.list_check_runs_for_ref",
        return_value=runs,
    )


class TestCheckRequiredContentChecks:
    def test_no_protection_does_not_bounce(self):
        with _patch_protection(None), _patch_runs([]):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert result.bounce_required is False

    def test_no_required_contexts_does_not_bounce(self):
        with _patch_protection({"required_status_checks": {"contexts": []}}), _patch_runs([]):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert result.bounce_required is False

    def test_only_meta_gate_checks_required_does_not_bounce(self):
        protection = _protection(
            ["require-human-approval", "require-overseer-approval", "require-tier-ceiling"]
        )
        runs = [
            _run("require-human-approval", None, status="in_progress"),
            _run("require-overseer-approval", "failure"),
            _run("require-tier-ceiling", "failure"),
        ]
        with _patch_protection(protection), _patch_runs(runs):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert result.bounce_required is False

    def test_failing_content_check_bounces(self):
        protection = _protection(["oversight-gate-lint", "tests"])
        runs = [
            _run("oversight-gate-lint", "failure"),
            _run("tests", "success"),
        ]
        with _patch_protection(protection), _patch_runs(runs):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert result.bounce_required is True
        assert result.failures == ["check-failing:oversight-gate-lint"]
        assert result.reason_category == "COMPLIANCE_FAILURE"
        assert "oversight-gate-lint" in result.summary

    def test_passing_content_checks_do_not_bounce(self):
        protection = _protection(["oversight-gate-lint", "tests"])
        runs = [_run("oversight-gate-lint", "success"), _run("tests", "success")]
        with _patch_protection(protection), _patch_runs(runs):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert result.bounce_required is False

    def test_not_yet_reported_check_does_not_bounce(self):
        # A required check with no check-run yet (queued/not started) is not
        # a bounce condition — it just hasn't run, not failed.
        protection = _protection(["oversight-gate-lint"])
        with _patch_protection(protection), _patch_runs([]):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert result.bounce_required is False

    def test_meta_gate_check_ignored_even_when_content_check_also_fails(self):
        protection = _protection(["require-human-approval", "oversight-gate-lint"])
        runs = [
            _run("require-human-approval", "failure"),
            _run("oversight-gate-lint", "failure"),
        ]
        with _patch_protection(protection), _patch_runs(runs):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert result.bounce_required is True
        assert result.failures == ["check-failing:oversight-gate-lint"]

    def test_timed_out_and_cancelled_conclusions_bounce(self):
        protection = _protection(["oversight-validator-python", "oversight-validator-shell"])
        runs = [
            _run("oversight-validator-python", "timed_out"),
            _run("oversight-validator-shell", "cancelled"),
        ]
        with _patch_protection(protection), _patch_runs(runs):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert result.bounce_required is True
        assert set(result.failures) == {
            "check-failing:oversight-validator-python",
            "check-failing:oversight-validator-shell",
        }

    def test_neutral_and_skipped_conclusions_do_not_bounce(self):
        protection = _protection(["oversight-gate-template-refs"])
        runs = [_run("oversight-gate-template-refs", "skipped")]
        with _patch_protection(protection), _patch_runs(runs):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert result.bounce_required is False

    def test_returns_dataclass_type(self):
        with _patch_protection(None), _patch_runs([]):
            result = check_required_content_checks(OWNER, REPO, HEAD_SHA)
        assert isinstance(result, RequiredChecksResult)
