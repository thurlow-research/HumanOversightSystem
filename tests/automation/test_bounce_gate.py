"""Tests for the register-completeness bounce gate (#1125, overseer.md step 4a).

Covers the three functions overseer.md's step 4a names but that never existed:
  - check_register_completeness: re-checks contract §7 conditions 1-3 against
    the sign-off register on disk
  - bounce_count: derives the per-cid bounce counter from the audit trail
  - record_pr_bounce: comment -> confirm -> audit event -> finalize, with the
    SPEC-378 R3.3 halt-on-failure ordering
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.automation.lib.github import GitHubError
from scripts.automation.lib.merge_authority import (
    BounceResult,
    RegisterCompletenessResult,
    _required_signoffs_for_step,
    bounce_count,
    check_register_completeness,
    record_pr_bounce,
)

OWNER = "thurlow-research"
REPO = "HumanOversightSystem"


def _write_manifest(tmp_path, roles, *, name="step-manifest.yaml"):
    """Write a manifest at the default path check_register_completeness expects.

    check_register_completeness()'s default manifest_path is
    <repo_root>/contract/step-manifest.yaml, so tests exercising the default
    (no explicit manifest_path) must write there.
    """
    manifest_dir = tmp_path / "contract"
    manifest_dir.mkdir(exist_ok=True)
    manifest = manifest_dir / name
    manifest.write_text(
        "steps:\n"
        "  - id: 1\n"
        f"    required_signoffs: [{', '.join(roles)}]\n"
    )
    return manifest


# ---------------------------------------------------------------------------
# _required_signoffs_for_step
# ---------------------------------------------------------------------------


class TestRequiredSignoffsForStep:
    def test_finds_step(self, tmp_path):
        manifest = _write_manifest(tmp_path, ["code-review", "security"])
        assert _required_signoffs_for_step(manifest, 1) == ["code-review", "security"]

    def test_missing_step_returns_empty(self, tmp_path):
        manifest = _write_manifest(tmp_path, ["code-review"])
        assert _required_signoffs_for_step(manifest, 99) == []

    def test_missing_file_returns_empty(self, tmp_path):
        assert _required_signoffs_for_step(tmp_path / "nope.yaml", 1) == []


# ---------------------------------------------------------------------------
# check_register_completeness
# ---------------------------------------------------------------------------


class TestCheckRegisterCompleteness:
    def test_register_missing_bounces(self, tmp_path):
        _write_manifest(tmp_path, ["code-review"])
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is True
        assert result.failures == ["register-missing"]
        assert result.reason_category == "REGISTER_GAP"

    def test_no_required_roles_passes_even_without_register(self, tmp_path):
        _write_manifest(tmp_path, [])
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is False

    def test_complete_register_passes(self, tmp_path):
        _write_manifest(tmp_path, ["code-review"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## code-review | app/views.py | T1\n"
            "Status: APPROVED\n"
            "Agent: code-reviewer\n"
            "Artifact: app/views.py\n"
            "Iterations: 1\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is False
        assert result.failures == []

    def test_missing_role_entry_bounces(self, tmp_path):
        _write_manifest(tmp_path, ["code-review", "security"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## code-review | app/views.py | T1\n"
            "Status: APPROVED\n"
            "Agent: code-reviewer\n"
            "Artifact: app/views.py\n"
            "Iterations: 1\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is True
        assert result.failures == ["register-missing-role:security"]
        assert result.reason_category == "REGISTER_GAP"

    def test_missing_required_field_bounces(self, tmp_path):
        _write_manifest(tmp_path, ["code-review"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## code-review | app/views.py | T1\n"
            "Status: APPROVED\n"
            "Agent: code-reviewer\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is True
        assert "register-missing-fields:code-review:Artifact,Iterations" in result.failures

    def test_unresolved_escalation_bounces(self, tmp_path):
        _write_manifest(tmp_path, ["security"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## security | app/auth.py | T1\n"
            "Status: ESCALATED\n"
            "Agent: security-reviewer\n"
            "Artifact: app/auth.py\n"
            "Iterations: 1\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is True
        assert result.failures == ["register-unresolved-escalation:security"]

    def test_resolved_escalation_with_human_resolution_passes(self, tmp_path):
        _write_manifest(tmp_path, ["security"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## security | app/auth.py | T1\n"
            "Status: ESCALATED\n"
            "Agent: security-reviewer\n"
            "Artifact: app/auth.py\n"
            "Iterations: 1\n"
            "Human_resolution: Accepted by ScottThurlow 2026-08-01\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is False

    def test_later_entry_supersedes_earlier_escalation(self, tmp_path):
        _write_manifest(tmp_path, ["security"])
        register_dir = tmp_path / ".claudetmp" / "signoffs"
        register_dir.mkdir(parents=True)
        (register_dir / "step1-register.md").write_text(
            "## security | app/auth.py | T1\n"
            "Status: ESCALATED\n"
            "Agent: security-reviewer\n"
            "## security | app/auth.py | T2\n"
            "Status: APPROVED\n"
            "Agent: security-reviewer\n"
            "Artifact: app/auth.py\n"
            "Iterations: 2\n"
        )
        result = check_register_completeness(1, repo_root=str(tmp_path))
        assert result.bounce_required is False


# ---------------------------------------------------------------------------
# bounce_count
# ---------------------------------------------------------------------------


class TestBounceCount:
    def test_zero_when_no_audit_log(self, tmp_path):
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 0

    def test_counts_only_matching_cid(self, tmp_path):
        from scripts.oversight.lib import audit_log

        audit_log.write_event(
            {"event": "pr-bounced", "cid": "cid-1", "timestamp": "2026-08-01T00:00:00Z"},
            root=str(tmp_path),
        )
        audit_log.write_event(
            {"event": "pr-bounced", "cid": "cid-2", "timestamp": "2026-08-01T00:00:01Z"},
            root=str(tmp_path),
        )
        audit_log.write_event(
            {"event": "human-required", "cid": "cid-1", "timestamp": "2026-08-01T00:00:02Z"},
            root=str(tmp_path),
        )
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 1
        assert bounce_count("cid-2", repo_root=str(tmp_path)) == 1
        assert bounce_count("cid-3", repo_root=str(tmp_path)) == 0

    def test_counts_multiple_bounces_same_cid(self, tmp_path):
        from scripts.oversight.lib import audit_log

        for i in range(2):
            audit_log.write_event(
                {
                    "event": "pr-bounced",
                    "cid": "cid-1",
                    "bounce_number": i + 1,
                    "timestamp": f"2026-08-01T00:00:0{i}Z",
                },
                root=str(tmp_path),
            )
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 2


# ---------------------------------------------------------------------------
# record_pr_bounce
# ---------------------------------------------------------------------------


class TestRecordPrBounce:
    def test_invalid_reason_category_raises(self, tmp_path):
        with pytest.raises(ValueError):
            record_pr_bounce(
                OWNER, REPO, 123,
                cid="cid-1", reason_category="NOT_A_CATEGORY", summary="x",
                failures=["register-missing"], repo_root=str(tmp_path),
            )

    def test_happy_path_posts_comment_writes_audit_event_and_finalizes(self, tmp_path):
        with patch(
            "scripts.automation.lib.merge_authority.post_comment",
            return_value={"id": 1, "html_url": "https://example/pr/123#comment-1"},
        ) as mock_post, patch(
            "scripts.automation.lib.merge_authority._run_gh", return_value={"isDraft": True}
        ) as mock_run_gh, patch(
            "scripts.automation.lib.merge_authority._convert_pr_to_draft"
        ) as mock_draft:
            result = record_pr_bounce(
                OWNER, REPO, 123,
                cid="cid-1", reason_category="REGISTER_GAP",
                summary="missing security sign-off",
                failures=["register-missing-role:security"],
                repo_root=str(tmp_path),
            )

        assert isinstance(result, BounceResult)
        assert result.bounce_number == 1
        assert result.comment_url == "https://example/pr/123#comment-1"
        assert result.finalize_errors == []
        mock_post.assert_called_once()
        posted_body = mock_post.call_args[0][3]
        assert "**Reason category:** REGISTER_GAP" in posted_body
        assert "**Summary:** missing security sign-off" in posted_body
        assert "register-missing-role:security" in posted_body
        mock_draft.assert_called_once_with(OWNER, REPO, 123)
        # assignee + label calls went through _run_gh
        assert mock_run_gh.call_count == 2

        # audit event was committed and is counted by bounce_count
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 1

    def test_second_bounce_increments_bounce_number(self, tmp_path):
        with patch(
            "scripts.automation.lib.merge_authority.post_comment",
            return_value={"id": 1, "html_url": "https://example/pr/123#comment-1"},
        ), patch(
            "scripts.automation.lib.merge_authority._run_gh", return_value={}
        ), patch(
            "scripts.automation.lib.merge_authority._convert_pr_to_draft"
        ):
            record_pr_bounce(
                OWNER, REPO, 123,
                cid="cid-1", reason_category="REGISTER_GAP", summary="first",
                failures=["register-missing"], repo_root=str(tmp_path),
            )
            second = record_pr_bounce(
                OWNER, REPO, 123,
                cid="cid-1", reason_category="REGISTER_GAP", summary="second",
                failures=["register-missing"], repo_root=str(tmp_path),
            )
        assert second.bounce_number == 2

    def test_comment_post_failure_halts_before_audit_event(self, tmp_path):
        with patch(
            "scripts.automation.lib.merge_authority.post_comment",
            side_effect=GitHubError("boom"),
        ):
            with pytest.raises(GitHubError):
                record_pr_bounce(
                    OWNER, REPO, 123,
                    cid="cid-1", reason_category="REGISTER_GAP", summary="x",
                    failures=["register-missing"], repo_root=str(tmp_path),
                )
        # No audit event was written -- the halt-on-failure ordering held.
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 0
        assert not (tmp_path / "audit" / "log").exists()

    def test_finalize_step_failure_is_recorded_not_raised(self, tmp_path):
        with patch(
            "scripts.automation.lib.merge_authority.post_comment",
            return_value={"id": 1, "html_url": "https://example/pr/123#comment-1"},
        ), patch(
            "scripts.automation.lib.merge_authority._run_gh",
            side_effect=GitHubError("assign failed"),
        ), patch(
            "scripts.automation.lib.merge_authority._convert_pr_to_draft",
            side_effect=GitHubError("draft failed"),
        ):
            result = record_pr_bounce(
                OWNER, REPO, 123,
                cid="cid-1", reason_category="REGISTER_GAP", summary="x",
                failures=["register-missing"], repo_root=str(tmp_path),
            )
        # Audit event still committed -- only finalize sub-steps failed.
        assert bounce_count("cid-1", repo_root=str(tmp_path)) == 1
        assert len(result.finalize_errors) == 3  # assign, label, draft all failed
