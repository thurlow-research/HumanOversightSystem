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
    get_branch_protection,
    get_repo,
    list_issue_comments,
    list_pulls,
    post_comment,
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
        with _patch_run([
            _make_result(500),
            _make_result(500),
            _make_result(200, payload),
        ]):
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


class TestNoSearchApi:
    """
    Boundary contract: github.py must NOT expose a search surface.
    Any import of 'search' from this module is a contract violation.
    """
    def test_no_search_attribute(self):
        import scripts.automation.lib.github as gh_module
        public_names = [n for n in dir(gh_module) if not n.startswith("_")]
        search_names = [n for n in public_names if "search" in n.lower()]
        assert search_names == [], (
            f"github.py must not expose a Search surface — found: {search_names}"
        )


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
        post_result = {"id": 99, "body": body, "html_url": "https://github.com/o/r/issues/1#issuecomment-99"}
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
        assert not any("--field" in str(a) or "--raw-field" in str(a) for a in post_call_cmd), (
            "must not use --field or --raw-field for body"
        )
        assert post_call_kwargs.get("input") == json.dumps({"body": body}), (
            "body must be JSON-encoded in stdin"
        )

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
        post_result = {"id": 7, "body": body, "html_url": "https://github.com/o/r/issues/1#issuecomment-7"}
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
