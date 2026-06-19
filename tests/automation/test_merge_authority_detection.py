"""
Tests for merge_authority.py — detect_server_side_gate (B4, O3).

The #152-followup stub means detect_server_side_gate always returns PROPOSE_ONLY
for now (fail-safe default).  These tests also cover the detection sub-steps
that will be active once the DEP is fulfilled.
"""

from unittest.mock import patch

import pytest

from scripts.automation.lib.merge_authority import (
    GateDetectionResult,
    _dep_ceiling_check_present,
    _verify_overseer_cannot_bypass,
    _verify_overseer_review_accepted,
    detect_server_side_gate,
)


OWNER = "thurlow-research"
REPO = "HumanOversightSystem"


def _make_protection(
    required_count: int = 1,
    dismiss_stale: bool = True,
    enforce_admins: bool = True,
    require_codeowners: bool = True,
    bypass_users: list[dict] | None = None,
    bypass_teams: list[dict] | None = None,
) -> dict:
    return {
        "required_pull_request_reviews": {
            "required_approving_review_count": required_count,
            "dismiss_stale_reviews": dismiss_stale,
            "require_code_owner_reviews": require_codeowners,
        },
        "enforce_admins": {"enabled": enforce_admins},
        "bypass_pull_request_allowances": {
            "users": bypass_users or [],
            "teams": bypass_teams or [],
        },
    }


# ---------------------------------------------------------------------------
# DEP stub — always PROPOSE_ONLY until #152-followup ships
# ---------------------------------------------------------------------------

class TestDepStub:
    def test_dep_ceiling_check_absent_by_default(self):
        assert _dep_ceiling_check_present(OWNER, REPO) is False

    def test_detect_returns_propose_only_when_dep_absent(self):
        result = detect_server_side_gate(OWNER, REPO)
        assert not result.autonomous_capable
        assert "DEP[#152-followup]" in result.reason or "PROPOSE_ONLY" in result.reason


# ---------------------------------------------------------------------------
# Gate detection sub-steps (tested in isolation by patching the DEP stub)
# ---------------------------------------------------------------------------

def _patch_dep(present: bool):
    return patch(
        "scripts.automation.lib.merge_authority._dep_ceiling_check_present",
        return_value=present,
    )


def _patch_protection(protection):
    return patch(
        "scripts.automation.lib.merge_authority.get_branch_protection",
        return_value=protection,
    )


class TestDetectServerSideGate:
    def test_propose_only_when_no_protection(self):
        with _patch_dep(True), _patch_protection(None):
            result = detect_server_side_gate(OWNER, REPO)
        assert not result.autonomous_capable
        assert "not enabled" in result.reason

    def test_propose_only_when_required_count_zero(self):
        protection = _make_protection(required_count=0)
        with _patch_dep(True), _patch_protection(protection):
            result = detect_server_side_gate(OWNER, REPO)
        assert not result.autonomous_capable

    def test_propose_only_when_stale_reviews_not_dismissed(self):
        protection = _make_protection(dismiss_stale=False)
        with _patch_dep(True), _patch_protection(protection):
            result = detect_server_side_gate(OWNER, REPO)
        assert not result.autonomous_capable

    def test_propose_only_when_overseer_in_bypass_users(self):
        # enforce_admins=False so bypass_users is actually checked.
        # Updated for GitHub App auth (#547): default overseer handle is now App bot.
        protection = _make_protection(
            enforce_admins=False,
            bypass_users=[{"login": "hos-overseer-hos[bot]"}],
        )
        with _patch_dep(True), _patch_protection(protection):
            result = detect_server_side_gate(OWNER, REPO)
        assert not result.autonomous_capable
        assert "bypass" in result.reason.lower()

    def test_autonomous_capable_when_gate_fully_configured(self):
        protection = _make_protection()  # enforce_admins=True → clean
        with _patch_dep(True), _patch_protection(protection):
            result = detect_server_side_gate(OWNER, REPO)
        assert result.autonomous_capable

    def test_case_insensitive_overseer_bypass_check(self):
        """Overseer handle comparison is case-insensitive."""
        protection = _make_protection(
            enforce_admins=False,
            bypass_users=[{"login": "hosoversighttutelare"}],  # lowercase
        )
        with _patch_dep(True), _patch_protection(protection):
            result = detect_server_side_gate(OWNER, REPO, overseer_handle="HOSOversightTutelare")
        assert not result.autonomous_capable

    def test_bypass_team_blocks_detection(self):
        """A bypass team means we can't verify overseer exclusion → PROPOSE_ONLY."""
        protection = _make_protection(
            enforce_admins=False,
            bypass_teams=[{"slug": "admins"}],
        )
        with _patch_dep(True), _patch_protection(protection):
            result = detect_server_side_gate(OWNER, REPO)
        assert not result.autonomous_capable


# ---------------------------------------------------------------------------
# _verify_overseer_cannot_bypass
# ---------------------------------------------------------------------------

class TestVerifyOverseerCannotBypass:
    def test_ok_when_enforce_admins(self):
        protection = {"enforce_admins": {"enabled": True}, "bypass_pull_request_allowances": {}}
        result = _verify_overseer_cannot_bypass(protection, "hos-overseer")
        assert result.autonomous_capable

    def test_blocked_when_overseer_in_bypass(self):
        protection = {
            "enforce_admins": {"enabled": False},
            "bypass_pull_request_allowances": {
                "users": [{"login": "hos-overseer"}],
                "teams": [],
            },
        }
        result = _verify_overseer_cannot_bypass(protection, "hos-overseer")
        assert not result.autonomous_capable

    def test_ok_when_no_bypass_actors(self):
        protection = {
            "enforce_admins": {"enabled": False},
            "bypass_pull_request_allowances": {"users": [], "teams": []},
        }
        result = _verify_overseer_cannot_bypass(protection, "hos-overseer")
        assert result.autonomous_capable


# ---------------------------------------------------------------------------
# GateDetectionResult bool
# ---------------------------------------------------------------------------

class TestGateDetectionResultBool:
    def test_autonomous_capable_true_is_truthy(self):
        assert GateDetectionResult(autonomous_capable=True, reason="ok")

    def test_autonomous_capable_false_is_falsy(self):
        assert not GateDetectionResult(autonomous_capable=False, reason="no")
