"""
Unit tests for stale_commit_detector.py (#850).

Covers:
  - get_branch_commits: parses git log output, empty branch
  - find_redundant_in_main: parses git cherry output (- vs + marks)
  - find_redundant_in_open_prs: SHA overlap detection, bot-PR skip, branch skip,
    API error tolerance
  - check_stale_commits: orchestration, audit log emission, clean/unclean result
  - strip_redundant_commits: success and failure paths
  - StaleCommitResult: is_clean, all_redundant dedup
"""

import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from scripts.automation.lib.stale_commit_detector import (
    StaleCommitResult,
    check_stale_commits,
    find_redundant_in_main,
    find_redundant_in_open_prs,
    get_branch_commits,
    strip_redundant_commits,
)
from scripts.automation.lib.github import GitHubError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40
SHA_D = "d" * 40

OWNER = "thurlow-research"
REPO = "HumanOversightSystem"


def _git_ok(stdout: str) -> MagicMock:
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = 0
    return m


def _git_fail(stderr: str = "error") -> MagicMock:
    m = MagicMock()
    m.stdout = ""
    m.stderr = stderr
    m.returncode = 1
    return m


# ---------------------------------------------------------------------------
# get_branch_commits
# ---------------------------------------------------------------------------

class TestGetBranchCommits:
    def test_returns_shas_oldest_first(self):
        git_log_out = f"{SHA_A}\n{SHA_B}\n{SHA_C}"
        with patch("subprocess.run", return_value=_git_ok(git_log_out)) as mock_run:
            result = get_branch_commits(base="main", head="HEAD")

        assert result == [SHA_A, SHA_B, SHA_C]
        cmd = mock_run.call_args[0][0]
        assert "log" in cmd
        assert "--reverse" in cmd
        assert "main..HEAD" in cmd

    def test_empty_when_no_unique_commits(self):
        with patch("subprocess.run", return_value=_git_ok("")):
            result = get_branch_commits()
        assert result == []

    def test_single_commit(self):
        with patch("subprocess.run", return_value=_git_ok(SHA_A)):
            result = get_branch_commits()
        assert result == [SHA_A]

    def test_raises_on_git_failure(self):
        with patch("subprocess.run", return_value=_git_fail("fatal: not a git repo")):
            with pytest.raises(RuntimeError, match="git log"):
                get_branch_commits()


# ---------------------------------------------------------------------------
# find_redundant_in_main
# ---------------------------------------------------------------------------

class TestFindRedundantInMain:
    def test_returns_shas_marked_with_minus(self):
        cherry_out = f"- {SHA_A}\n+ {SHA_B}\n- {SHA_C}"
        with patch("subprocess.run", return_value=_git_ok(cherry_out)):
            result = find_redundant_in_main()
        assert result == [SHA_A, SHA_C]

    def test_empty_when_all_unique(self):
        cherry_out = f"+ {SHA_A}\n+ {SHA_B}"
        with patch("subprocess.run", return_value=_git_ok(cherry_out)):
            result = find_redundant_in_main()
        assert result == []

    def test_empty_when_no_commits(self):
        with patch("subprocess.run", return_value=_git_ok("")):
            result = find_redundant_in_main()
        assert result == []

    def test_all_redundant(self):
        cherry_out = f"- {SHA_A}\n- {SHA_B}"
        with patch("subprocess.run", return_value=_git_ok(cherry_out)):
            result = find_redundant_in_main()
        assert result == [SHA_A, SHA_B]

    def test_git_failure_returns_empty_not_raises(self):
        with patch("subprocess.run", return_value=_git_fail("bad ref")):
            result = find_redundant_in_main()
        assert result == []

    def test_passes_base_and_head_to_git_cherry(self):
        with patch("subprocess.run", return_value=_git_ok("")) as mock_run:
            find_redundant_in_main(base="origin/main", head="feat/x")
        cmd = mock_run.call_args[0][0]
        assert "cherry" in cmd
        assert "origin/main" in cmd
        assert "feat/x" in cmd


# ---------------------------------------------------------------------------
# find_redundant_in_open_prs
# ---------------------------------------------------------------------------

def _pr(number, author="other-user", branch="feat/other", commit_shas=None):
    return {
        "number": number,
        "user": {"login": author},
        "head": {"ref": branch},
    }


def _make_commits(shas):
    return [{"sha": sha} for sha in shas]


class TestFindRedundantInOpenPrs:
    def test_detects_sha_overlap_with_open_pr(self):
        prs = [_pr(42, branch="feat/fix-806")]
        pr_commits = _make_commits([SHA_A, SHA_B])

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=[prs, pr_commits],
        ):
            result = find_redundant_in_open_prs(
                OWNER, REPO, [SHA_A, SHA_C]
            )

        assert result == {"42": [SHA_A]}

    def test_empty_when_no_overlap(self):
        prs = [_pr(42, branch="feat/fix-806")]
        pr_commits = _make_commits([SHA_D])

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=[prs, pr_commits],
        ):
            result = find_redundant_in_open_prs(
                OWNER, REPO, [SHA_A, SHA_B]
            )

        assert result == {}

    def test_skips_bot_own_prs(self):
        bot_pr = _pr(10, author="hos-worker-hos[bot]", branch="feat/bot-fix")
        prs = [bot_pr]

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=[prs],
        ):
            result = find_redundant_in_open_prs(
                OWNER, REPO, [SHA_A],
                bot_login="hos-worker-hos[bot]",
            )

        assert result == {}

    def test_skips_current_branch_pr(self):
        same_branch_pr = _pr(20, branch="feat/my-fix")
        prs = [same_branch_pr]

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=[prs],
        ):
            result = find_redundant_in_open_prs(
                OWNER, REPO, [SHA_A],
                current_branch="feat/my-fix",
            )

        assert result == {}

    def test_empty_when_no_open_prs(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            return_value=[],
        ):
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

        assert result == {}

    def test_empty_input_commits_returns_empty(self):
        result = find_redundant_in_open_prs(OWNER, REPO, [])
        assert result == {}

    def test_api_error_on_list_prs_returns_empty(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=GitHubError("503"),
        ):
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

        assert result == {}

    def test_api_error_on_pr_commits_skips_that_pr(self):
        prs = [_pr(42), _pr(99)]
        pr_42_commits = _make_commits([SHA_A])

        def _side_effect(args):
            url = args[0]
            if "pulls/42/commits" in url:
                raise GitHubError("timeout")
            if "pulls/99/commits" in url:
                return pr_42_commits
            return prs

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

        # PR #42 errored out (skipped), PR #99's commits overlap → detected
        assert "42" not in result
        assert result.get("99") == [SHA_A]

    def test_multiple_overlapping_shas_in_one_pr(self):
        prs = [_pr(55)]
        pr_commits = _make_commits([SHA_A, SHA_B, SHA_C])

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=[prs, pr_commits],
        ):
            result = find_redundant_in_open_prs(
                OWNER, REPO, [SHA_A, SHA_B, SHA_D]
            )

        assert set(result["55"]) == {SHA_A, SHA_B}


# ---------------------------------------------------------------------------
# check_stale_commits
# ---------------------------------------------------------------------------

class TestCheckStaleCommits:
    def _patch_sub_fns(self, all_commits=None, redundant_main=None, redundant_prs=None):
        all_commits = all_commits or []
        redundant_main = redundant_main or []
        redundant_prs = redundant_prs or {}
        return (
            patch(
                "scripts.automation.lib.stale_commit_detector.get_branch_commits",
                return_value=all_commits,
            ),
            patch(
                "scripts.automation.lib.stale_commit_detector.find_redundant_in_main",
                return_value=redundant_main,
            ),
            patch(
                "scripts.automation.lib.stale_commit_detector.find_redundant_in_open_prs",
                return_value=redundant_prs,
            ),
            patch("scripts.automation.lib.stale_commit_detector.log_event"),
        )

    def test_clean_result_when_no_redundancies(self):
        p1, p2, p3, p4 = self._patch_sub_fns(all_commits=[SHA_A])
        with p1, p2, p3, p4 as mock_log:
            result = check_stale_commits(OWNER, REPO, branch="feat/clean")

        assert result.is_clean
        assert result.all_commits == [SHA_A]
        mock_log.assert_not_called()

    def test_emits_audit_event_when_redundant_in_main(self):
        p1, p2, p3, p4 = self._patch_sub_fns(
            all_commits=[SHA_A, SHA_B],
            redundant_main=[SHA_A],
        )
        with p1, p2, p3, p4 as mock_log:
            result = check_stale_commits(OWNER, REPO, branch="feat/stacked")

        assert not result.is_clean
        assert result.redundant_in_main == [SHA_A]
        mock_log.assert_called_once()
        event_name = mock_log.call_args[0][0]
        assert event_name == "pre-pr-stale-commits"

    def test_emits_audit_event_when_redundant_in_pr(self):
        p1, p2, p3, p4 = self._patch_sub_fns(
            all_commits=[SHA_A],
            redundant_prs={"42": [SHA_A]},
        )
        with p1, p2, p3, p4 as mock_log:
            result = check_stale_commits(OWNER, REPO, branch="feat/stacked")

        assert not result.is_clean
        assert result.redundant_in_prs == {"42": [SHA_A]}
        mock_log.assert_called_once()

    def test_skips_open_pr_check_when_disabled(self):
        p1, p2, p3, p4 = self._patch_sub_fns(all_commits=[SHA_A])
        with p1, p2 as mock_gcbc, p3 as mock_pr_check, p4:
            check_stale_commits(
                OWNER, REPO, branch="feat/x", check_open_prs=False
            )
        mock_pr_check.assert_not_called()

    def test_skips_open_pr_check_when_no_commits(self):
        p1, p2, p3, p4 = self._patch_sub_fns(all_commits=[])
        with p1, p2, p3 as mock_pr_check, p4:
            check_stale_commits(OWNER, REPO, branch="feat/x")
        mock_pr_check.assert_not_called()

    def test_result_carries_correct_branch_and_base(self):
        p1, p2, p3, p4 = self._patch_sub_fns()
        with p1, p2, p3, p4:
            result = check_stale_commits(
                OWNER, REPO, branch="feat/thing", base="origin/main"
            )
        assert result.branch == "feat/thing"
        assert result.base == "origin/main"


# ---------------------------------------------------------------------------
# strip_redundant_commits
# ---------------------------------------------------------------------------

class TestStripRedundantCommits:
    def test_returns_true_on_success(self):
        with patch("subprocess.run", return_value=_git_ok("")) as mock_run:
            assert strip_redundant_commits(base="main") is True
        cmd = mock_run.call_args[0][0]
        assert "rebase" in cmd
        assert "main" in cmd

    def test_returns_false_on_conflict(self):
        with patch("subprocess.run", return_value=_git_fail("CONFLICT")):
            assert strip_redundant_commits(base="main") is False

    def test_uses_supplied_base(self):
        with patch("subprocess.run", return_value=_git_ok("")) as mock_run:
            strip_redundant_commits(base="origin/main")
        cmd = mock_run.call_args[0][0]
        assert "origin/main" in cmd


# ---------------------------------------------------------------------------
# StaleCommitResult
# ---------------------------------------------------------------------------

class TestStaleCommitResult:
    def test_is_clean_when_no_redundancies(self):
        r = StaleCommitResult(
            branch="b", base="main",
            all_commits=[SHA_A],
            redundant_in_main=[],
            redundant_in_prs={},
        )
        assert r.is_clean

    def test_not_clean_when_redundant_in_main(self):
        r = StaleCommitResult(
            branch="b", base="main",
            all_commits=[SHA_A],
            redundant_in_main=[SHA_A],
            redundant_in_prs={},
        )
        assert not r.is_clean

    def test_not_clean_when_redundant_in_pr(self):
        r = StaleCommitResult(
            branch="b", base="main",
            all_commits=[SHA_A],
            redundant_in_main=[],
            redundant_in_prs={"42": [SHA_A]},
        )
        assert not r.is_clean

    def test_all_redundant_deduplicates_across_sources(self):
        r = StaleCommitResult(
            branch="b", base="main",
            all_commits=[SHA_A, SHA_B, SHA_C],
            redundant_in_main=[SHA_A, SHA_B],
            redundant_in_prs={"42": [SHA_B, SHA_C]},
        )
        all_r = r.all_redundant
        assert set(all_r) == {SHA_A, SHA_B, SHA_C}
        # No duplicates
        assert len(all_r) == len(set(all_r))

    def test_all_redundant_empty_when_clean(self):
        r = StaleCommitResult(
            branch="b", base="main",
            all_commits=[SHA_A],
            redundant_in_main=[],
            redundant_in_prs={},
        )
        assert r.all_redundant == []
