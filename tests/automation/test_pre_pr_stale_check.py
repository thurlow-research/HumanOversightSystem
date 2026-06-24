"""
Unit tests for pre_pr_stale_check.py (#850).

Covers:
  - parse_remote_url: HTTPS, SSH, with/without .git suffix
  - resolve_owner_repo: explicit args, falls back to git remote
  - resolve_branch: explicit arg, falls back to git
  - run_check: clean branch, auto-strip success, rebase failure,
               overlap with open PR, both overlap types
"""

import subprocess
import sys
from unittest.mock import MagicMock, call, patch

import pytest

from scripts.automation.pre_pr_stale_check import (
    parse_remote_url,
    resolve_branch,
    resolve_owner_repo,
    run_check,
)
from scripts.automation.lib.stale_commit_detector import StaleCommitResult

SHA_A = "a" * 40
SHA_B = "b" * 40

OWNER = "thurlow-research"
REPO = "HumanOversightSystem"
BRANCH = "feat/my-fix-850"
BASE = "main"


def _clean_result(branch=BRANCH, base=BASE):
    return StaleCommitResult(
        branch=branch, base=base,
        all_commits=[SHA_A],
        redundant_in_main=[],
        redundant_in_prs={},
    )


def _stale_main_result(branch=BRANCH, base=BASE):
    return StaleCommitResult(
        branch=branch, base=base,
        all_commits=[SHA_A, SHA_B],
        redundant_in_main=[SHA_A],
        redundant_in_prs={},
    )


def _stale_pr_result(branch=BRANCH, base=BASE):
    return StaleCommitResult(
        branch=branch, base=base,
        all_commits=[SHA_A],
        redundant_in_main=[],
        redundant_in_prs={"42": [SHA_A]},
    )


def _stale_both_result(branch=BRANCH, base=BASE):
    return StaleCommitResult(
        branch=branch, base=base,
        all_commits=[SHA_A, SHA_B],
        redundant_in_main=[SHA_A],
        redundant_in_prs={"42": [SHA_B]},
    )


# ---------------------------------------------------------------------------
# parse_remote_url
# ---------------------------------------------------------------------------

class TestParseRemoteUrl:
    def test_https_with_git_suffix(self):
        assert parse_remote_url(
            "https://github.com/thurlow-research/HumanOversightSystem.git"
        ) == ("thurlow-research", "HumanOversightSystem")

    def test_https_without_git_suffix(self):
        assert parse_remote_url(
            "https://github.com/thurlow-research/HumanOversightSystem"
        ) == ("thurlow-research", "HumanOversightSystem")

    def test_ssh_with_git_suffix(self):
        assert parse_remote_url(
            "git@github.com:thurlow-research/HumanOversightSystem.git"
        ) == ("thurlow-research", "HumanOversightSystem")

    def test_ssh_without_git_suffix(self):
        assert parse_remote_url(
            "git@github.com:thurlow-research/HumanOversightSystem"
        ) == ("thurlow-research", "HumanOversightSystem")

    def test_raises_on_unrecognised_url(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_remote_url("https://gitlab.com/owner/repo.git")

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError):
            parse_remote_url("")


# ---------------------------------------------------------------------------
# resolve_owner_repo
# ---------------------------------------------------------------------------

class TestResolveOwnerRepo:
    def test_explicit_args_bypass_git(self):
        with patch("subprocess.run") as mock_run:
            owner, repo = resolve_owner_repo("my-org", "my-repo")
        mock_run.assert_not_called()
        assert (owner, repo) == ("my-org", "my-repo")

    def test_falls_back_to_git_remote(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "https://github.com/thurlow-research/HumanOversightSystem.git\n"
        )
        with patch("subprocess.run", return_value=mock_result):
            owner, repo = resolve_owner_repo(None, None)
        assert (owner, repo) == ("thurlow-research", "HumanOversightSystem")

    def test_exits_2_on_git_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "not a git repo"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                resolve_owner_repo(None, None)
        assert exc_info.value.code == 2

    def test_exits_2_on_unparseable_remote_url(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "https://gitlab.com/owner/repo.git\n"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                resolve_owner_repo(None, None)
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# resolve_branch
# ---------------------------------------------------------------------------

class TestResolveBranch:
    def test_returns_explicit_branch(self):
        with patch("subprocess.run") as mock_run:
            result = resolve_branch("feat/my-fix")
        mock_run.assert_not_called()
        assert result == "feat/my-fix"

    def test_falls_back_to_git(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "feat/auto-branch\n"
        with patch("subprocess.run", return_value=mock_result):
            result = resolve_branch(None)
        assert result == "feat/auto-branch"

    def test_exits_2_on_git_failure(self):
        mock_result = MagicMock()
        mock_result.returncode = 128
        mock_result.stdout = ""
        mock_result.stderr = "fatal: not a git repo"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                resolve_branch(None)
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# run_check
# ---------------------------------------------------------------------------

class TestRunCheck:
    def test_clean_branch_returns_0(self):
        with patch(
            "scripts.automation.pre_pr_stale_check.check_stale_commits",
            return_value=_clean_result(),
        ):
            rc = run_check(OWNER, REPO, branch=BRANCH, base=BASE)
        assert rc == 0

    def test_redundant_in_main_auto_strips_and_returns_0(self):
        with (
            patch(
                "scripts.automation.pre_pr_stale_check.check_stale_commits",
                side_effect=[_stale_main_result(), _clean_result()],
            ),
            patch(
                "scripts.automation.pre_pr_stale_check.strip_redundant_commits",
                return_value=True,
            ) as mock_strip,
        ):
            rc = run_check(OWNER, REPO, branch=BRANCH, base=BASE)

        assert rc == 0
        mock_strip.assert_called_once_with(base=BASE)

    def test_redundant_in_main_rebase_failure_returns_1(self):
        with (
            patch(
                "scripts.automation.pre_pr_stale_check.check_stale_commits",
                return_value=_stale_main_result(),
            ),
            patch(
                "scripts.automation.pre_pr_stale_check.strip_redundant_commits",
                return_value=False,
            ),
        ):
            rc = run_check(OWNER, REPO, branch=BRANCH, base=BASE)

        assert rc == 1

    def test_still_stale_after_rebase_returns_1(self):
        with (
            patch(
                "scripts.automation.pre_pr_stale_check.check_stale_commits",
                side_effect=[_stale_main_result(), _stale_main_result()],
            ),
            patch(
                "scripts.automation.pre_pr_stale_check.strip_redundant_commits",
                return_value=True,
            ),
        ):
            rc = run_check(OWNER, REPO, branch=BRANCH, base=BASE)

        assert rc == 1

    def test_redundant_in_pr_returns_1_without_strip(self):
        with (
            patch(
                "scripts.automation.pre_pr_stale_check.check_stale_commits",
                return_value=_stale_pr_result(),
            ),
            patch(
                "scripts.automation.pre_pr_stale_check.strip_redundant_commits",
            ) as mock_strip,
        ):
            rc = run_check(OWNER, REPO, branch=BRANCH, base=BASE)

        assert rc == 1
        mock_strip.assert_not_called()

    def test_redundant_in_both_returns_1_without_strip(self):
        """When commits overlap both main and an open PR, still exits 1 without rebase."""
        with (
            patch(
                "scripts.automation.pre_pr_stale_check.check_stale_commits",
                return_value=_stale_both_result(),
            ),
            patch(
                "scripts.automation.pre_pr_stale_check.strip_redundant_commits",
            ) as mock_strip,
        ):
            rc = run_check(OWNER, REPO, branch=BRANCH, base=BASE)

        assert rc == 1
        mock_strip.assert_not_called()
