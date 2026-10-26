"""
Unit tests for stale_commit_detector.py (#850).

Covers:
  - get_branch_commits: parses git log output, empty branch
  - find_redundant_in_main: parses git cherry output (- vs + marks)
  - find_redundant_in_open_prs: SHA overlap detection, bot-PR skip, branch skip,
    fail-closed on any API/response failure (#1681)
  - check_stale_commits: orchestration, audit log emission, clean/unclean result
  - strip_redundant_commits: success and failure paths
  - StaleCommitResult: is_clean, all_redundant dedup
"""

from unittest.mock import MagicMock, patch

import pytest

from scripts.automation.lib.github import GitHubError, RateLimitError
from scripts.automation.lib.stale_commit_detector import (
    OpenPrsUnverifiedError,
    StaleCommitResult,
    check_stale_commits,
    find_redundant_in_main,
    find_redundant_in_open_prs,
    get_branch_commits,
    strip_redundant_commits,
)

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

    def test_git_failure_raises_runtime_error(self):
        with patch("subprocess.run", return_value=_git_fail("bad ref")):
            with pytest.raises(RuntimeError, match="git cherry"):
                find_redundant_in_main()

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
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A, SHA_C])

        assert result == {"42": [SHA_A]}

    def test_empty_when_no_overlap(self):
        prs = [_pr(42, branch="feat/fix-806")]
        pr_commits = _make_commits([SHA_D])

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=[prs, pr_commits],
        ):
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A, SHA_B])

        assert result == {}

    def test_bot_authored_prs_are_checked_not_skipped(self):
        # #987: in autonomous mode *every* open PR is bot-authored, so the old
        # bot-login skip made this guard a no-op against the worker's own
        # stacked branches. A bot-authored PR on a *different* branch must now
        # be checked like any other, and its overlapping commits detected.
        bot_pr = _pr(10, author="hos-worker-hos[bot]", branch="feat/bot-fix")
        prs = [bot_pr]
        pr_commits = _make_commits([SHA_A, SHA_B])

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=[prs, pr_commits],
        ):
            result = find_redundant_in_open_prs(
                OWNER,
                REPO,
                [SHA_A],
                bot_login="hos-worker-hos[bot]",
            )

        assert result == {"10": [SHA_A]}

    def test_skips_current_branch_pr_even_when_bot_authored(self):
        # The branch under check may already have its own open PR (e.g. a re-run
        # after CHANGES_REQUESTED). Its own already-pushed commits are not
        # "stale" against itself and must still be skipped via current_branch,
        # regardless of authorship.
        own_pr = _pr(30, author="hos-worker-hos[bot]", branch="feat/my-fix")
        prs = [own_pr]

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=[prs],
        ):
            result = find_redundant_in_open_prs(
                OWNER,
                REPO,
                [SHA_A],
                current_branch="feat/my-fix",
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
                OWNER,
                REPO,
                [SHA_A],
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

    # --- Fail-closed cases (#1681): formerly returned {} / skipped the PR. ---

    def test_api_error_on_list_prs_raises_unverified(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=GitHubError("503"),
        ):
            with pytest.raises(OpenPrsUnverifiedError, match="503"):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_api_error_on_pr_commits_raises_unverified(self):
        prs = [_pr(42), _pr(99)]
        pr_99_commits = _make_commits([SHA_A])

        def _side_effect(args):
            url = args[0]
            if "pulls/42/commits" in url:
                raise GitHubError("timeout")
            if "pulls/99/commits" in url:
                return pr_99_commits
            return prs

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            with pytest.raises(OpenPrsUnverifiedError, match="PR #42"):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_non_list_pr_listing_raises_unverified(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            return_value={"message": "API error"},
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_non_list_pr_commits_response_raises_unverified(self):
        prs = [_pr(42), _pr(99)]

        def _side_effect(args):
            url = args[0]
            if "pulls/42/commits" in url:
                return {"message": "unexpected dict"}
            if "pulls/99/commits" in url:
                return _make_commits([SHA_A])
            return prs

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_rate_limit_error_raises_unverified(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=RateLimitError("403 rate limited"),
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_unverified_error_is_not_a_github_error(self):
        assert not issubclass(OpenPrsUnverifiedError, GitHubError)

    def test_non_github_exception_propagates(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=ValueError("boom"),
        ):
            with pytest.raises(ValueError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_none_on_first_listing_page_raises_unverified(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            return_value=None,
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_none_on_second_listing_page_raises_unverified(self):
        page1 = [_pr(1000 + i, branch=f"feat/x{i}") for i in range(100)]

        def _side_effect(args):
            url = args[0]
            if "pulls?state=open" in url:
                return page1 if "&page=1" in url else None
            return _make_commits([SHA_D])

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_pr_without_number_raises_unverified(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            return_value=[{"head": {"ref": "feat/x"}}],
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_error_reason_is_sanitized_single_line_bounded(self):
        raw = "boom\n\x1b[31mred\x1b[0m\tline2\r\x07" + "x" * 1000
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=GitHubError(raw, 401),
        ):
            with pytest.raises(OpenPrsUnverifiedError) as ei:
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])
        reason = str(ei.value)
        assert "\n" not in reason and "\x1b" not in reason and "\x07" not in reason
        assert not any(ord(c) < 32 or 0x7F <= ord(c) <= 0x9F for c in reason)
        assert len(reason) <= 300
        assert reason.endswith("\u2026")
        assert "boom red line2" in reason

    def test_error_reason_has_no_tuple_repr_and_includes_status(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=GitHubError("bad token", 401),
        ):
            with pytest.raises(OpenPrsUnverifiedError) as ei:
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])
        reason = str(ei.value)
        assert "('bad token'" not in reason
        assert "bad token (HTTP 401)" in reason

    @pytest.mark.parametrize("number", ["42", True, 4.5])
    def test_non_int_pr_number_raises_unverified(self, number):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            return_value=[{"number": number, "head": {"ref": "feat/x"}}],
        ) as mock_gh:
            with pytest.raises(OpenPrsUnverifiedError, match="non-integer"):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])
        assert mock_gh.call_count == 1  # never used in a commits API path

    def test_non_dict_head_is_not_treated_as_current_branch(self):
        pr = {"number": 7, "head": "feat/x"}
        responses = [[pr], _make_commits([SHA_A])]
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=responses,
        ):
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A], current_branch="feat/x")
        assert result == {"7": [SHA_A]}

    def test_non_dict_pr_entry_raises_unverified(self):
        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            return_value=["not-a-dict"],
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_none_commit_page_raises_unverified(self):
        def _side_effect(args):
            return [_pr(42)] if "pulls?state=open" in args[0] else None

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            with pytest.raises(OpenPrsUnverifiedError, match="PR #42"):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_commit_without_sha_raises_unverified(self):
        def _side_effect(args):
            if "pulls?state=open" in args[0]:
                return [_pr(42)]
            return [{"commit": {}}]

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_non_dict_commit_entry_raises_unverified(self):
        def _side_effect(args):
            if "pulls?state=open" in args[0]:
                return [_pr(42)]
            return ["not-a-dict"]

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_empty_sha_commit_raises_unverified(self):
        def _side_effect(args):
            if "pulls?state=open" in args[0]:
                return [_pr(42)]
            return [{"sha": ""}]

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            with pytest.raises(OpenPrsUnverifiedError):
                find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

    def test_current_branch_pr_with_bad_commits_is_not_fetched(self):
        # The current-branch skip precedes any commit fetch, so it cannot fail.
        def _side_effect(args):
            if "pulls?state=open" in args[0]:
                return [_pr(42, branch="feat/me")]
            raise AssertionError("commits of the current branch's PR fetched")

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A], current_branch="feat/me")
        assert result == {}

    def test_multiple_overlapping_shas_in_one_pr(self):
        prs = [_pr(55)]
        pr_commits = _make_commits([SHA_A, SHA_B, SHA_C])

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=[prs, pr_commits],
        ):
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A, SHA_B, SHA_D])

        assert set(result["55"]) == {SHA_A, SHA_B}

    def test_paginates_open_pr_listing(self):
        # #987: an overlapping PR sitting past the first 100 must still be
        # found. Page 1 returns a full 100 non-overlapping PRs (forcing a second
        # page fetch); the overlapping PR is the 101st, on page 2.
        page1 = [_pr(1000 + i, branch=f"feat/x{i}") for i in range(100)]
        page2 = [_pr(2000, branch="feat/overlap")]
        non_overlap = _make_commits([SHA_D])
        overlap = _make_commits([SHA_A])

        def _side_effect(args):
            url = args[0]
            if "pulls?state=open" in url:
                if "&page=1" in url:
                    return page1
                if "&page=2" in url:
                    return page2
                return []
            if "pulls/2000/commits" in url:
                return overlap
            return non_overlap

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

        assert result == {"2000": [SHA_A]}

    def test_paginates_pr_commits(self):
        # #987: a PR carrying >100 commits must have every page scanned; the
        # overlapping commit here lands on page 2 of the PR's commit list.
        prs = [_pr(77, branch="feat/big")]
        commits_page1 = _make_commits([f"{i:040x}" for i in range(100)])
        commits_page2 = _make_commits([SHA_A])

        def _side_effect(args):
            url = args[0]
            if "pulls?state=open" in url:
                return prs if "&page=1" in url else []
            if "pulls/77/commits" in url:
                if "&page=1" in url:
                    return commits_page1
                if "&page=2" in url:
                    return commits_page2
                return []
            return []

        with patch(
            "scripts.automation.lib.stale_commit_detector._run_gh",
            side_effect=_side_effect,
        ):
            result = find_redundant_in_open_prs(OWNER, REPO, [SHA_A])

        assert result == {"77": [SHA_A]}


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
        with p1, p2, p3 as mock_pr_check, p4:
            check_stale_commits(OWNER, REPO, branch="feat/x", check_open_prs=False)
        mock_pr_check.assert_not_called()

    def test_skips_open_pr_check_when_no_commits(self):
        p1, p2, p3, p4 = self._patch_sub_fns(all_commits=[])
        with p1, p2, p3 as mock_pr_check, p4:
            check_stale_commits(OWNER, REPO, branch="feat/x")
        mock_pr_check.assert_not_called()

    def test_unverified_open_prs_is_not_clean_and_emits_event(self):
        # #1681: an API failure must never read as clean.
        p1, p2, p3, p4 = self._patch_sub_fns(all_commits=[SHA_A])
        with p1, p2, p3 as mock_pr_check, p4 as mock_log:
            mock_pr_check.side_effect = OpenPrsUnverifiedError("401 bad token")
            result = check_stale_commits(OWNER, REPO, branch="feat/x")

        assert result.open_prs_unverified == "401 bad token"
        assert not result.is_clean
        assert result.redundant_in_prs == {}
        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == "pre-pr-stale-check-unverified"
        assert mock_log.call_args[1]["reason"] == "401 bad token"
        assert mock_log.call_args[1]["branch"] == "feat/x"

    def test_unverified_reason_is_sanitized_everywhere(self):
        p1, p2, p3, p4 = self._patch_sub_fns(all_commits=[SHA_A])
        with p1, p2, p3 as mock_pr_check, p4 as mock_log:
            mock_pr_check.side_effect = OpenPrsUnverifiedError("a\nb\x1b[1m" + "y" * 500)
            result = check_stale_commits(OWNER, REPO, branch="feat/x")
        assert "\n" not in result.open_prs_unverified
        assert len(result.open_prs_unverified) <= 300
        assert mock_log.call_args[1]["reason"] == result.open_prs_unverified

    def test_unverified_with_real_redundancy_emits_both_events(self):
        p1, p2, p3, p4 = self._patch_sub_fns(all_commits=[SHA_A], redundant_main=[SHA_A])
        with p1, p2, p3 as mock_pr_check, p4 as mock_log:
            mock_pr_check.side_effect = OpenPrsUnverifiedError("x")
            result = check_stale_commits(OWNER, REPO, branch="feat/x")

        assert not result.is_clean
        assert [c[0][0] for c in mock_log.call_args_list] == [
            "pre-pr-stale-check-unverified",
            "pre-pr-stale-commits",
        ]

    @pytest.mark.parametrize(
        "gh_effect",
        [
            GitHubError("401"),
            RateLimitError("403"),
            None,
            {"message": "x"},
        ],
    )
    def test_end_to_end_api_failure_is_unverified(self, gh_effect):
        p1, p2, _, p4 = self._patch_sub_fns(all_commits=[SHA_A])
        if isinstance(gh_effect, Exception):
            gh_patch = patch(
                "scripts.automation.lib.stale_commit_detector._run_gh",
                side_effect=gh_effect,
            )
        else:
            gh_patch = patch(
                "scripts.automation.lib.stale_commit_detector._run_gh",
                return_value=gh_effect,
            )
        with p1, p2, gh_patch, p4 as mock_log:
            result = check_stale_commits(OWNER, REPO, branch="feat/x")

        assert result.open_prs_unverified
        assert not result.is_clean
        assert mock_log.call_args[0][0] == "pre-pr-stale-check-unverified"

    def test_disabled_open_pr_check_is_not_unverified(self):
        p1, p2, p3, p4 = self._patch_sub_fns(all_commits=[SHA_A])
        with p1, p2, p3, p4:
            result = check_stale_commits(OWNER, REPO, branch="feat/x", check_open_prs=False)
        assert result.open_prs_unverified is None
        assert result.is_clean

    def test_result_carries_correct_branch_and_base(self):
        p1, p2, p3, p4 = self._patch_sub_fns()
        with p1, p2, p3, p4:
            result = check_stale_commits(OWNER, REPO, branch="feat/thing", base="origin/main")
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
            branch="b",
            base="main",
            all_commits=[SHA_A],
            redundant_in_main=[],
            redundant_in_prs={},
        )
        assert r.is_clean

    def test_not_clean_when_open_prs_unverified(self):
        r = StaleCommitResult(
            branch="b",
            base="main",
            all_commits=[SHA_A],
            redundant_in_main=[],
            redundant_in_prs={},
            open_prs_unverified="401",
        )
        assert not r.is_clean
        assert r.all_redundant == []

    def test_not_clean_when_redundant_in_main(self):
        r = StaleCommitResult(
            branch="b",
            base="main",
            all_commits=[SHA_A],
            redundant_in_main=[SHA_A],
            redundant_in_prs={},
        )
        assert not r.is_clean

    def test_not_clean_when_redundant_in_pr(self):
        r = StaleCommitResult(
            branch="b",
            base="main",
            all_commits=[SHA_A],
            redundant_in_main=[],
            redundant_in_prs={"42": [SHA_A]},
        )
        assert not r.is_clean

    def test_all_redundant_deduplicates_across_sources(self):
        r = StaleCommitResult(
            branch="b",
            base="main",
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
            branch="b",
            base="main",
            all_commits=[SHA_A],
            redundant_in_main=[],
            redundant_in_prs={},
        )
        assert r.all_redundant == []
