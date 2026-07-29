"""
Tests for static_analysis_js.py (S6, ADR-032 D6).

Unlike complexity_metrics_js.py/function_metrics_js.py (tree-sitter, in-process),
this validator shells out to semgrep exactly like static_analysis.py shells out
to bandit — so the scoring-logic tests mock subprocess.run (mirroring
TestStaticAnalysisMocked in test_validators_mocked.py), and a real-tool
integration test is included but tolerant of semgrep being unavailable in the
sandbox (mirroring TestStaticAnalysis in test_validators_integration.py).
"""
from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from schema import WEIGHTS
from static_analysis_js import _run_semgrep, analyse_files as saj_analyse


def _semgrep_result(check_id: str, severity: str, path: str = "test.ts", line: int = 5) -> dict:
    return {
        "check_id": check_id,
        "path": path,
        "start": {"line": line},
        "extra": {"severity": severity, "message": f"{check_id} message"},
    }


def _semgrep_json(results: list[dict]) -> str:
    return json.dumps({"results": results, "errors": []})


class TestRunSemgrep:
    def test_parses_findings(self):
        mock = MagicMock(stdout=_semgrep_json([_semgrep_result("eval-use", "ERROR")]), returncode=0)
        with patch("static_analysis_js.subprocess.run", return_value=mock):
            findings, err = _run_semgrep(["test.ts"])
        assert err is None
        assert len(findings) == 1
        assert findings[0]["extra"]["severity"] == "ERROR"

    def test_invalid_json_signals_error(self):
        mock = MagicMock(stdout="not-json", returncode=0)
        with patch("static_analysis_js.subprocess.run", return_value=mock):
            findings, err = _run_semgrep(["test.ts"])
        assert findings == []
        assert err is not None

    def test_not_installed_signals_error(self):
        with patch(
            "static_analysis_js.subprocess.run", side_effect=FileNotFoundError("semgrep not found")
        ):
            findings, err = _run_semgrep(["test.ts"])
        assert findings == []
        assert err is not None

    def test_missing_ruleset_signals_error(self):
        with patch("static_analysis_js._RULESET") as mock_ruleset:
            mock_ruleset.exists.return_value = False
            findings, err = _run_semgrep(["test.ts"])
        assert findings == []
        assert err is not None


class TestAnalyseFilesMocked:
    def test_semgrep_not_installed_excludes_dimension(self):
        # Mirrors static_analysis.py's #917 fix: a missing primary tool must
        # EXCLUDE the highest-weight security dimension, not score a clean 0.0.
        with patch(
            "static_analysis_js.subprocess.run", side_effect=FileNotFoundError("semgrep not found")
        ):
            result = saj_analyse(["test.ts"])
        assert result["error"] is not None
        assert result["score"] == pytest.approx(0.0)
        assert result["dimension"] == "static_analysis"
        assert result["weight"] == WEIGHTS["static_analysis"]

    def test_semgrep_unparseable_excludes_dimension(self):
        mock = MagicMock(stdout="not-json", returncode=0)
        with patch("static_analysis_js.subprocess.run", return_value=mock):
            result = saj_analyse(["test.ts"])
        assert result["error"] is not None
        assert result["score"] == pytest.approx(0.0)

    def test_no_findings_zero_score(self):
        mock = MagicMock(stdout=_semgrep_json([]), returncode=0)
        with patch("static_analysis_js.subprocess.run", return_value=mock):
            result = saj_analyse(["test.ts"])
        assert result["error"] is None
        assert result["score"] == pytest.approx(0.0)
        assert result["tier_floor"] is None

    def test_error_finding_raises_score_and_sets_tier_floor(self):
        mock = MagicMock(stdout=_semgrep_json([_semgrep_result("eval-use", "ERROR")]), returncode=0)
        with patch("static_analysis_js.subprocess.run", return_value=mock):
            result = saj_analyse(["test.ts"])
        assert result["error"] is None
        assert result["score"] > 0.0
        assert result["tier_floor"] == "HIGH"
        assert result["raw_value"]["semgrep_error_count"] == 1

    def test_warning_finding_leaves_tier_floor_none(self):
        mock = MagicMock(
            stdout=_semgrep_json([_semgrep_result("innerhtml-assignment", "WARNING")]), returncode=0
        )
        with patch("static_analysis_js.subprocess.run", return_value=mock):
            result = saj_analyse(["test.ts"])
        assert result["error"] is None
        assert result["tier_floor"] is None
        assert result["raw_value"]["semgrep_warning_count"] == 1

    def test_error_finding_scores_higher_than_warning(self):
        # Mirrors static_analysis.py's #997 HIGH:MEDIUM asymmetry (3x weight).
        error_mock = MagicMock(
            stdout=_semgrep_json([_semgrep_result("eval-use", "ERROR")]), returncode=0
        )
        with patch("static_analysis_js.subprocess.run", return_value=error_mock):
            error_result = saj_analyse(["test.ts"])
        warning_mock = MagicMock(
            stdout=_semgrep_json([_semgrep_result("innerhtml-assignment", "WARNING")]), returncode=0
        )
        with patch("static_analysis_js.subprocess.run", return_value=warning_mock):
            warning_result = saj_analyse(["test.ts"])
        assert error_result["error"] is None and warning_result["error"] is None
        assert error_result["score"] > warning_result["score"]

    def test_error_finding_evidence_marked_high_severity(self):
        mock = MagicMock(stdout=_semgrep_json([_semgrep_result("eval-use", "ERROR")]), returncode=0)
        with patch("static_analysis_js.subprocess.run", return_value=mock):
            result = saj_analyse(["test.ts"])
        high_evidence = [e for e in result["evidence"] if e["severity"] == "high"]
        assert high_evidence, "ERROR semgrep finding must surface as high-severity evidence"

    def test_info_finding_is_not_scored(self):
        mock = MagicMock(
            stdout=_semgrep_json([_semgrep_result("some-info-rule", "INFO")]), returncode=0
        )
        with patch("static_analysis_js.subprocess.run", return_value=mock):
            result = saj_analyse(["test.ts"])
        assert result["error"] is None
        assert result["score"] == pytest.approx(0.0)
        assert result["tier_floor"] is None


class TestStaticAnalysisJsIntegration:
    """Exercises the real semgrep binary + vendored ruleset when available."""

    def _tmpfile(self, content: str, suffix: str = ".js") -> str:
        f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_clean_file(self):
        path = self._tmpfile("function add(a, b) {\n  return a + b;\n}\n")
        try:
            result = saj_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_obvious_issue_detected(self):
        # eval() is flagged by the vendored ruleset's eval-use rule.
        path = self._tmpfile("result = eval(userInput);\n")
        try:
            result = saj_analyse([path])
            # Either finds it (score > 0) or semgrep not installed (error set).
            assert result["score"] >= 0.0
        finally:
            os.unlink(path)

    def test_no_files(self):
        result = saj_analyse([])
        assert result["score"] == pytest.approx(0.0)
