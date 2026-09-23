"""
Unit tests for github.py — the REST-by-id wrapper.

Tests verify: retry logic, rate-limit handling, 404→None, and that the
module exposes no Search API surface (critical boundary contract).
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from scripts.automation.lib.github import (
    GitHubError,
    RateLimitError,
    _run_gh,
    get_branch,
    list_check_runs_for_ref,
    list_issue_comments,
    list_pulls,
    post_comment,
    request_reviewers,
    submit_pull_review,
)


def _make_result(status: int, body: dict | list | None = None, stderr: str = "") -> MagicMock:
    """Build a fake subprocess.CompletedProcess mirroring gh --include output."""
    body_str = json.dumps(body) if body is not None else ""
    stdout = f"HTTP/2 {status}\r\n\r\n{body_str}"
    mock = MagicMock()
    mock.stdout = stdout
    mock.stderr = stderr
    mock.returncode = 0 if status < 400 else 1
    return mock


def _patch_run(side_effects):
    return patch("subprocess.run", side_effect=side_effects)


class TestRunGh:
    def test_returns_parsed_json(self):
        payload = {"ref": "refs/heads/main"}
        with _patch_run([_make_result(200, payload)]):
            result = _run_gh(["/repos/o/r/git/ref/heads/main"])
        assert result == payload

    def test_404_returns_none(self):
        with _patch_run([_make_result(404)]):
            result = _run_gh(["/repos/o/r/git/ref/heads/nonexistent"])
        assert result is None

    def test_retries_on_500(self):
        payload = {"sha": "abc"}
        with _patch_run(
            [
                _make_result(500),
                _make_result(500),
                _make_result(200, payload),
            ]
        ):
            result = _run_gh(["/repos/o/r/git/ref/heads/main"], retries=3, backoff_base=0)
        assert result == payload

    def test_raises_after_exhausted_retries_on_500(self):
        with _patch_run([_make_result(500)] * 4):
            with pytest.raises(GitHubError):
                _run_gh(["/repos/o/r/git/ref/heads/main"], retries=3, backoff_base=0)

    def test_rate_limit_raises_after_retries(self):
        with _patch_run([_make_result(429)] * 4):
            with pytest.raises(RateLimitError):
                _run_gh(["/repos/o/r/git/ref/heads/main"], retries=3, backoff_base=0)

    def test_rate_limit_retries_then_succeeds(self):
        payload = {"sha": "abc"}
        with _patch_run([_make_result(429), _make_result(200, payload)]):
            result = _run_gh(["/repos/o/r/git/ref/heads/main"], retries=2, backoff_base=0)
        assert result == payload

    def test_empty_body_returns_none(self):
        mock = MagicMock()
        mock.stdout = "HTTP/2 200\r\n\r\n"
        mock.stderr = ""
        mock.returncode = 0
        with patch("subprocess.run", return_value=mock):
            result = _run_gh(["/repos/o/r/git/ref/heads/main"])
        assert result is None

    def test_gh_not_found_raises(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(GitHubError, match="gh CLI not found"):
                _run_gh(["/repos/o/r/git/ref/heads/main"])

    def test_passes_bounded_timeout_to_subprocess_run(self):
        """MUST_FIX C (#1657 PR-1 review round 2): every subprocess.run call
        this module makes must carry a bounded timeout= — without one, `gh`
        stalling on DNS/TLS/a proxy blocks the caller forever, and on
        Worker/Overseer's unattended cron nothing interrupts a hang."""
        with _patch_run([_make_result(200, {"ok": True})]) as mock_run:
            _run_gh(["/repos/o/r/git/ref/heads/main"])
        _, kwargs = mock_run.call_args
        assert isinstance(kwargs.get("timeout"), (int, float))
        assert kwargs["timeout"] > 0

    def test_timeout_raises_github_error(self):
        """A lone TimeoutExpired (retries exhausted) converts to GitHubError
        — never propagates as a raw subprocess.TimeoutExpired, and never
        silently reports success."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=30),
        ):
            with pytest.raises(GitHubError, match="timed out"):
                _run_gh(["/repos/o/r/git/ref/heads/main"], retries=0)

    def test_timeout_retries_then_succeeds(self):
        """A timeout on an idempotent GET is an ordinary retryable failure —
        each attempt is a fresh subprocess.run call, so a later success is a
        genuine success, not a masked failure."""
        payload = {"sha": "abc"}
        with _patch_run(
            [
                subprocess.TimeoutExpired(cmd=["gh"], timeout=30),
                _make_result(200, payload),
            ]
        ):
            result = _run_gh(["/repos/o/r/git/ref/heads/main"], retries=1, backoff_base=0)
        assert result == payload

    def test_timeout_exhausted_retries_raises_github_error_not_success(self):
        """A timeout on every attempt must never be mistaken for a
        retryable-and-then-successful outcome (MUST_FIX C's explicit
        requirement) — it raises, it does not return."""
        with _patch_run([subprocess.TimeoutExpired(cmd=["gh"], timeout=30)] * 2):
            with pytest.raises(GitHubError, match="timed out"):
                _run_gh(["/repos/o/r/git/ref/heads/main"], retries=1, backoff_base=0)


class TestGetBranch:
    def test_returns_ref_when_found(self):
        payload = {"ref": "refs/heads/hos/auto/abc123def456"}
        with _patch_run([_make_result(200, payload)]):
            result = get_branch("o", "r", "hos/auto/abc123def456")
        assert result == payload

    def test_returns_none_when_not_found(self):
        with _patch_run([_make_result(404)]):
            result = get_branch("o", "r", "nonexistent-branch")
        assert result is None


class TestListPulls:
    def test_returns_list(self):
        prs = [{"number": 1, "merged_at": None}]
        with _patch_run([_make_result(200, prs)]):
            result = list_pulls("o", "r", head="o:branch", state="all")
        assert result == prs

    def test_returns_empty_on_404(self):
        with _patch_run([_make_result(404)]):
            result = list_pulls("o", "r", head="o:branch", state="all")
        assert result == []


class TestListIssueComments:
    def test_returns_all_comments(self):
        comments = [{"body": "hi"}, {"body": "there"}]
        with _patch_run([_make_result(200, comments)]):
            result = list_issue_comments("o", "r", 1)
        assert result == comments

    def test_returns_empty_on_404(self):
        with _patch_run([_make_result(404)]):
            result = list_issue_comments("o", "r", 1)
        assert result == []


class TestListCheckRunsForRef:
    def test_returns_all_check_runs(self):
        runs = [{"name": "tests", "conclusion": "success"}]
        with _patch_run([_make_result(200, {"check_runs": runs})]):
            result = list_check_runs_for_ref("o", "r", "abc123")
        assert result == runs

    def test_returns_empty_on_404(self):
        with _patch_run([_make_result(404)]):
            result = list_check_runs_for_ref("o", "r", "abc123")
        assert result == []

    def test_paginates(self):
        page1 = [{"name": f"check-{i}"} for i in range(100)]
        page2 = [{"name": "check-100"}]
        with _patch_run(
            [
                _make_result(200, {"check_runs": page1}),
                _make_result(200, {"check_runs": page2}),
            ]
        ):
            result = list_check_runs_for_ref("o", "r", "abc123")
        assert len(result) == 101
        assert result[-1]["name"] == "check-100"


class TestNoSearchApi:
    """
    Boundary contract: github.py must NOT expose a search surface.
    Any import of 'search' from this module is a contract violation.
    """

    def test_no_search_attribute(self):
        import scripts.automation.lib.github as gh_module

        public_names = [n for n in dir(gh_module) if not n.startswith("_")]
        search_names = [n for n in public_names if "search" in n.lower()]
        assert (
            search_names == []
        ), f"github.py must not expose a Search surface — found: {search_names}"


class TestPostComment:
    """Regression tests for #752 — @path literal in comment body.

    The critical invariant: post_comment must never use --field or --raw-field
    for the body, because gh's -F flag expands '@/path' to file content and
    -f flag silently posts the literal '@/path' string. Both are wrong.
    Instead we use --input - (JSON via stdin), where '@' is inert.
    """

    def test_uses_stdin_json_not_field_flag(self):
        """post_comment must pipe JSON via --input -, never --field body=..."""
        body = "## Escalation\n\nHuman review required."
        post_result = {
            "id": 99,
            "body": body,
            "html_url": "https://github.com/o/r/issues/1#issuecomment-99",
        }
        readback_result = {"id": 99, "body": body}

        captured_calls = []

        def fake_run(cmd, **kwargs):
            captured_calls.append((cmd, kwargs))
            if "--input" in cmd:
                return _make_result(201, post_result)
            return _make_result(200, readback_result)

        with patch("subprocess.run", side_effect=fake_run):
            result = post_comment("o", "r", 1, body)

        assert result["id"] == 99
        post_call_cmd, post_call_kwargs = captured_calls[0]
        assert "--input" in post_call_cmd, "must use --input flag (JSON via stdin)"
        assert not any(
            "--field" in str(a) or "--raw-field" in str(a) for a in post_call_cmd
        ), "must not use --field or --raw-field for body"
        assert post_call_kwargs.get("input") == json.dumps(
            {"body": body}
        ), "body must be JSON-encoded in stdin"

    def test_detects_at_path_literal_in_readback(self):
        """If GitHub stores '@/path' literally, post_comment raises GitHubError (#752)."""
        at_path_body = "@/tmp/pr751-review.md"
        post_result = {"id": 42, "body": at_path_body}
        readback_result = {"id": 42, "body": at_path_body}

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_result(201, post_result),
                _make_result(200, readback_result),
            ]
            with pytest.raises(GitHubError, match="#752"):
                post_comment("o", "r", 751, at_path_body)

    def test_normal_body_succeeds(self):
        """post_comment returns the comment object when body is stored correctly."""
        body = "HUMAN_REQUIRED — escalating for review."
        post_result = {
            "id": 7,
            "body": body,
            "html_url": "https://github.com/o/r/issues/1#issuecomment-7",
        }
        readback_result = {"id": 7, "body": body}

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                _make_result(201, post_result),
                _make_result(200, readback_result),
            ]
            result = post_comment("o", "r", 1, body)
        assert result["id"] == 7

    def test_verify_false_skips_readback(self):
        """With verify=False, only one API call is made (no read-back GET)."""
        body = "quick comment"
        post_result = {"id": 5, "body": body}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = _make_result(201, post_result)
            result = post_comment("o", "r", 1, body, verify=False)

        assert mock_run.call_count == 1
        assert result["id"] == 5

    def test_raises_when_post_returns_none(self):
        """GitHubError raised if POST returns no response."""
        with patch("subprocess.run", return_value=_make_result(404)):
            with pytest.raises(GitHubError, match="no response"):
                post_comment("o", "r", 1, "body")


class TestSubmitPullReview:
    """G1 (#1657) — submit_pull_review must never use --field/-f/-F/--raw-field
    for the review body: the #752/#1155 @path class must not recur here
    either."""

    def test_uses_stdin_json_not_field_flag(self):
        body = "**Executive summary:** ... Expected action: **NO ACTION**."
        post_result = {
            "id": 55,
            "state": "APPROVED",
            "body": body,
            "commit_id": "abc123",
            "html_url": "https://github.com/o/r/pull/1#pullrequestreview-55",
        }
        captured_calls = []

        def fake_run(cmd, **kwargs):
            captured_calls.append((cmd, kwargs))
            return _make_result(200, post_result)

        with patch("subprocess.run", side_effect=fake_run):
            result = submit_pull_review("o", "r", 1, "APPROVE", body, "abc123")

        assert result["id"] == 55
        assert len(captured_calls) == 1
        cmd, kwargs = captured_calls[0]
        assert "--input" in cmd, "must use --input flag (JSON via stdin)"
        assert not any(
            "--field" in str(a) or "--raw-field" in str(a) for a in cmd
        ), "must not use --field or --raw-field for the review body"
        assert not any(a in ("-f", "-F") for a in cmd), "must not use -f/-F either"
        assert kwargs.get("input") == json.dumps(
            {"event": "APPROVE", "body": body, "commit_id": "abc123"}
        )

    def test_invalid_event_raises_without_calling_gh(self):
        with patch("subprocess.run") as mock_run:
            with pytest.raises(GitHubError, match="APPROVE.*COMMENT"):
                submit_pull_review("o", "r", 1, "REQUEST_CHANGES", "body", "abc123")
        mock_run.assert_not_called()

    def test_raises_when_post_returns_none(self):
        with patch("subprocess.run", return_value=_make_result(404)):
            with pytest.raises(GitHubError, match="no response"):
                submit_pull_review("o", "r", 1, "COMMENT", "body", "abc123")

    def test_calls_run_gh_with_retries_zero(self):
        """MUST_FIX D (#1657 PR-1 review round 2): this POST is not
        idempotent and carries no idempotency key, so it must never be
        handed to _run_gh's generic retry loop — only the caller
        (pr_review_cli.py), which can re-fetch and check whether a write
        already landed, may decide whether to retry."""
        with patch("scripts.automation.lib.github._run_gh") as mock_run_gh:
            mock_run_gh.return_value = {"id": 1, "state": "APPROVED"}
            submit_pull_review("o", "r", 1, "APPROVE", "body", "abc123")
        _, kwargs = mock_run_gh.call_args
        assert kwargs.get("retries") == 0

    def test_stale_commit_id_surfaces_422_status_code(self):
        with patch(
            "subprocess.run",
            return_value=_make_result(422, stderr="commit_id is not part of the pull request"),
        ):
            with pytest.raises(GitHubError) as excinfo:
                submit_pull_review("o", "r", 1, "APPROVE", "body", "stale-sha")
        assert excinfo.value.status_code == 422


class TestRequestReviewers:
    """G2 (#1657) — request_reviewers must never use --field/-f/-F/--raw-field
    for the reviewers list, and must raise ValueError on a team token rather
    than silently posting it as a user login."""

    def test_uses_stdin_json_not_field_flag(self):
        post_result = {"number": 1, "requested_reviewers": [{"login": "ScottThurlow"}]}
        captured_calls = []

        def fake_run(cmd, **kwargs):
            captured_calls.append((cmd, kwargs))
            return _make_result(200, post_result)

        with patch("subprocess.run", side_effect=fake_run):
            result = request_reviewers("o", "r", 1, ["ScottThurlow"])

        assert result["number"] == 1
        cmd, kwargs = captured_calls[0]
        assert "--input" in cmd
        assert not any("--field" in str(a) or "--raw-field" in str(a) for a in cmd)
        assert not any(a in ("-f", "-F") for a in cmd)
        assert kwargs.get("input") == json.dumps({"reviewers": ["ScottThurlow"]})

    def test_team_token_raises_value_error_without_calling_gh(self):
        with patch("subprocess.run") as mock_run:
            with pytest.raises(ValueError, match="team reviewers are not supported"):
                request_reviewers("o", "r", 1, ["@org/some-team"])
        mock_run.assert_not_called()

    def test_empty_logins_raises_without_calling_gh(self):
        with patch("subprocess.run") as mock_run:
            with pytest.raises(GitHubError, match="non-empty"):
                request_reviewers("o", "r", 1, [])
        mock_run.assert_not_called()

    def test_raises_when_post_returns_none(self):
        with patch("subprocess.run", return_value=_make_result(404)):
            with pytest.raises(GitHubError, match="no response"):
                request_reviewers("o", "r", 1, ["ScottThurlow"])

    def test_422_surfaces_status_code(self):
        with patch(
            "subprocess.run",
            return_value=_make_result(
                422, stderr="Reviews may only be requested from collaborators."
            ),
        ):
            with pytest.raises(GitHubError) as excinfo:
                request_reviewers("o", "r", 1, ["not-a-collaborator"])
        assert excinfo.value.status_code == 422
