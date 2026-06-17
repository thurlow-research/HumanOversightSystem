"""Tests for issue_query.py and ip_check network API calls."""
import json
import pytest
from unittest.mock import patch, MagicMock

from issue_query import _gh_issues_for_files, analyse_files as iq_analyse


# ── issue_query mocked ────────────────────────────────────────────────────────

def _make_gh_mock(issues: list[dict]) -> MagicMock:
    return MagicMock(stdout=json.dumps(issues), returncode=0)


class TestGhIssuesForFiles:
    def test_gh_not_installed_returns_empty(self):
        with patch("issue_query.subprocess.run",
                   side_effect=FileNotFoundError("gh not found")):
            result = _gh_issues_for_files(["auth/views.py"])
        assert result == []

    def test_file_mentioned_in_issue_body_matched(self):
        issues = [{
            "number": 42,
            "title": "Bug in views.py",
            "body": "views.py has an N+1 query at line 30",
            "url": "https://github.com/example/issues/42",
            "labels": [{"name": "bug"}],
        }]
        help_mock = MagicMock(returncode=0)
        issue_mock = _make_gh_mock(issues)
        with patch("issue_query.subprocess.run",
                   side_effect=[help_mock] + [issue_mock] * 8):
            result = _gh_issues_for_files(["auth/views.py"])
        assert any(i["number"] == 42 for i in result)

    def test_unrelated_issues_not_matched(self):
        issues = [{
            "number": 99,
            "title": "Unrelated issue",
            "body": "This is about something else entirely",
            "url": "https://github.com/example/issues/99",
            "labels": [{"name": "bug"}],
        }]
        help_mock = MagicMock(returncode=0)
        issue_mock = _make_gh_mock(issues)
        with patch("issue_query.subprocess.run",
                   side_effect=[help_mock] + [issue_mock] * 8):
            result = _gh_issues_for_files(["auth/views.py"])
        assert result == []

    def test_duplicate_issues_deduplicated(self):
        # Same issue matches on two different labels
        issue = {
            "number": 1,
            "title": "Bug",
            "body": "views.py issue",
            "url": "https://github.com/example/issues/1",
            "labels": [{"name": "bug"}],
        }
        help_mock = MagicMock(returncode=0)
        # Return same issue for every label query
        issue_mock = _make_gh_mock([issue])
        with patch("issue_query.subprocess.run",
                   side_effect=[help_mock] + [issue_mock] * 8):
            result = _gh_issues_for_files(["views.py"])
        # Should appear only once despite matching on multiple labels
        numbers = [i["number"] for i in result]
        assert numbers.count(1) == 1

    def test_json_error_skipped(self):
        help_mock = MagicMock(returncode=0)
        bad_mock = MagicMock(stdout="not-json", returncode=0)
        with patch("issue_query.subprocess.run",
                   side_effect=[help_mock] + [bad_mock] * 8):
            result = _gh_issues_for_files(["views.py"])
        assert result == []


class TestIssueQueryAnalyse:
    def test_no_files(self):
        result = iq_analyse([])
        assert result["score"] == pytest.approx(0.0)

    def test_gh_unavailable_zero_score(self):
        # gh issues unavailable → _gh_issues_for_files returns []
        with patch("issue_query._gh_issues_for_files", return_value=[]):
            with patch("issue_query._git_churn", return_value={}):
                result = iq_analyse(["auth/views.py"])
        assert result["score"] == pytest.approx(0.0)
        assert result["error"] is None

    def test_high_issue_density_raises_score(self):
        issues = [
            {"number": i, "title": f"Bug {i}", "body": "views.py issue",
             "url": f"https://github.com/ex/issues/{i}",
             "labels": [{"name": "bug"}],
             "matched_file": "views.py", "matched_label": "bug"}
            for i in range(5)
        ]
        with patch("issue_query._gh_issues_for_files", return_value=issues):
            with patch("issue_query._git_churn", return_value={"views.py": 3}):
                result = iq_analyse(["views.py"])
        assert result["score"] > 0.0

    def test_result_envelope(self):
        result = iq_analyse([])
        for key in ("dimension", "score", "raw_value", "weight",
                    "evidence", "checklist_items", "findings", "error"):
            assert key in result
