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
