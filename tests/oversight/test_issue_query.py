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

    def test_security_finding_label_produces_high_severity_evidence(self):
        issues = [
            {
                "number": 7,
                "title": "Security flaw in views.py",
                "body": "views.py vulnerable",
                "url": "https://github.com/ex/issues/7",
                "labels": [{"name": "security-finding"}],
                "matched_file": "views.py",
                "matched_label": "security-finding",
            }
        ]
        with patch("issue_query._gh_issues_for_files", return_value=issues):
            with patch("issue_query._git_churn", return_value={}):
                result = iq_analyse(["views.py"])
        high_ev = [e for e in result["evidence"] if e["severity"] == "high"]
        assert len(high_ev) > 0

    def test_high_churn_file_appears_in_evidence(self):
        with patch("issue_query._gh_issues_for_files", return_value=[]):
            with patch("issue_query._git_churn", return_value={"views.py": 10}):
                result = iq_analyse(["views.py"])
        assert result["score"] > 0.0
        churn_ev = [e for e in result["evidence"] if "churn" in e["message"]]
        assert len(churn_ev) > 0

    def test_high_churn_adds_checklist_item(self):
        with patch("issue_query._gh_issues_for_files", return_value=[]):
            with patch("issue_query._git_churn", return_value={"views.py": 8}):
                result = iq_analyse(["views.py"])
        assert any("churn" in item for item in result["checklist_items"])

    def test_escaped_defect_label_high_severity(self):
        issues = [
            {
                "number": 3,
                "title": "Escaped defect in views.py",
                "body": "views.py has escaped defect",
                "url": "https://github.com/ex/issues/3",
                "labels": [{"name": "escaped-defect"}],
                "matched_file": "views.py",
                "matched_label": "escaped-defect",
            }
        ]
        with patch("issue_query._gh_issues_for_files", return_value=issues):
            with patch("issue_query._git_churn", return_value={}):
                result = iq_analyse(["views.py"])
        high_ev = [e for e in result["evidence"] if e["severity"] == "high"]
        assert len(high_ev) > 0

    def test_issues_checklist_populated_when_issues_present(self):
        issues = [
            {
                "number": 1,
                "title": "Bug in views.py",
                "body": "views.py issue",
                "url": "https://github.com/ex/issues/1",
                "labels": [{"name": "bug"}],
                "matched_file": "views.py",
                "matched_label": "bug",
            }
        ]
        with patch("issue_query._gh_issues_for_files", return_value=issues):
            with patch("issue_query._git_churn", return_value={}):
                result = iq_analyse(["views.py"])
        assert any("historical issue" in item for item in result["checklist_items"])


# ── _git_churn — exclude-prefix filtering ────────────────────────────────────

class TestGitChurn:
    from issue_query import _git_churn

    def test_docs_prefix_excluded(self):
        from issue_query import _git_churn
        git_log = "abc1234 docs: update README\n" \
                  "def5678 fix: real change\n"
        mock = MagicMock(stdout=git_log, returncode=0)
        with patch("issue_query.subprocess.run", return_value=mock):
            churn = _git_churn(["views.py"])
        # Only the "fix:" commit counts — docs: excluded
        assert churn["views.py"] == 1

    def test_spec_prefix_excluded(self):
        from issue_query import _git_churn
        git_log = "abc1234 spec: add spec section\n" \
                  "def5678 feat: add feature\n"
        mock = MagicMock(stdout=git_log, returncode=0)
        with patch("issue_query.subprocess.run", return_value=mock):
            churn = _git_churn(["auth.py"])
        assert churn["auth.py"] == 1

    def test_timeout_returns_zero(self):
        from issue_query import _git_churn
        import subprocess
        with patch("issue_query.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("git", 10)):
            churn = _git_churn(["views.py"])
        assert churn["views.py"] == 0

    def test_commit_with_no_subject_counted_as_logic(self):
        from issue_query import _git_churn
        # A line with only a hash (no whitespace-separated subject):
        # parts = ["abc1234"], len(parts) == 1, subject = "",
        # does not start with any excluded prefix → counted as a logic commit.
        git_log = "abc1234\n"
        mock = MagicMock(stdout=git_log, returncode=0)
        with patch("issue_query.subprocess.run", return_value=mock):
            churn = _git_churn(["views.py"])
        assert churn["views.py"] == 1

    def test_blank_lines_skipped(self):
        from issue_query import _git_churn
        git_log = "\n\nabc1234 fix: real\n\n"
        mock = MagicMock(stdout=git_log, returncode=0)
        with patch("issue_query.subprocess.run", return_value=mock):
            churn = _git_churn(["views.py"])
        assert churn["views.py"] == 1


# ── main() ────────────────────────────────────────────────────────────────────

class TestIssueQueryMain:
    def test_main_no_files_prints_json(self, capsys, monkeypatch):
        import sys
        monkeypatch.setattr(sys, "argv", ["issue_query.py"])
        import issue_query
        issue_query.main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["score"] == pytest.approx(0.0)
        assert data["error"] == "no input files"

    def test_main_valid_file_prints_json(self, capsys, monkeypatch, tmp_path):
        import sys
        p = tmp_path / "views.py"
        p.write_text("import os\n")
        monkeypatch.setattr(sys, "argv", ["issue_query.py", str(p)])
        import issue_query
        with patch("issue_query._gh_issues_for_files", return_value=[]):
            with patch("issue_query._git_churn", return_value={str(p): 0}):
                issue_query.main()
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "score" in data
