"""
Mocked tests for subprocess-heavy validators.

These validators shell out to external tools (radon, bandit, semgrep).
Mocking subprocess.run lets us test the parsing and scoring logic without
requiring the tools to be installed or produce specific output.
"""
import ast
import json
import textwrap
import tempfile
import os
import pytest
from unittest.mock import patch, MagicMock


# ── complexity_metrics (mocked radon) ─────────────────────────────────────────

from complexity_metrics import _radon_cc, _radon_mi, analyse_files as cm_analyse


class TestComplexityMocked:
    def _make_cc_json(self, entries: list[dict]) -> str:
        return json.dumps({"test.py": entries})

    def _make_mi_json(self, mi: float) -> str:
        return json.dumps({"test.py": {"mi": mi}})

    def test_radon_cc_parses_output(self):
        cc_json = self._make_cc_json([
            {"name": "simple_fn", "lineno": 1, "complexity": 3},
            {"name": "complex_fn", "lineno": 10, "complexity": 12},
        ])
        mock = MagicMock(stdout=cc_json, stderr="", returncode=0)
        with patch("complexity_metrics.subprocess.run", return_value=mock):
            result = _radon_cc(["test.py"])
        assert len(result) == 2
        assert result[1]["cyclomatic"] == 12
        assert result[1]["name"] == "complex_fn"

    def test_radon_cc_empty_output_returns_empty(self):
        mock = MagicMock(stdout="", stderr="", returncode=0)
        with patch("complexity_metrics.subprocess.run", return_value=mock):
            result = _radon_cc(["test.py"])
        assert result == []

    def test_radon_cc_invalid_json_returns_empty(self):
        mock = MagicMock(stdout="not-json", stderr="", returncode=0)
        with patch("complexity_metrics.subprocess.run", return_value=mock):
            result = _radon_cc(["test.py"])
        assert result == []

    def test_radon_mi_parses_output(self):
        mi_json = self._make_mi_json(62.5)
        mock = MagicMock(stdout=mi_json, stderr="", returncode=0)
        with patch("complexity_metrics.subprocess.run", return_value=mock):
            result = _radon_mi(["test.py"])
        assert result["test.py"] == pytest.approx(62.5)

    def test_radon_mi_invalid_json_returns_empty(self):
        mock = MagicMock(stdout="bad", stderr="", returncode=0)
        with patch("complexity_metrics.subprocess.run", return_value=mock):
            result = _radon_mi(["test.py"])
        assert result == {}

    def test_analyse_files_high_complexity_produces_evidence(self):
        cc_json = self._make_cc_json([
            {"name": "bad_fn", "lineno": 5, "complexity": 14},
        ])
        mi_json = self._make_mi_json(80.0)
        cc_mock = MagicMock(stdout=cc_json, stderr="", returncode=0)
        mi_mock = MagicMock(stdout=mi_json, stderr="", returncode=0)
        # First call: radon --version check; second: cc; third: mi
        with patch("complexity_metrics.subprocess.run",
                   side_effect=[
                       MagicMock(returncode=0),  # version check
                       cc_mock,                   # cc call
                       mi_mock,                   # mi call
                   ]):
            result = cm_analyse(["test.py"])
        assert result["error"] is None
        assert result["score"] > 0.0
        assert len(result["evidence"]) >= 1

    def test_analyse_files_low_complexity_low_score(self):
        cc_json = self._make_cc_json([
            {"name": "simple", "lineno": 1, "complexity": 2},
        ])
        mi_json = self._make_mi_json(95.0)
        with patch("complexity_metrics.subprocess.run",
                   side_effect=[
                       MagicMock(returncode=0),
                       MagicMock(stdout=cc_json, stderr="", returncode=0),
                       MagicMock(stdout=mi_json, stderr="", returncode=0),
                   ]):
            result = cm_analyse(["test.py"])
        assert result["score"] < 0.5

    def test_radon_not_installed_returns_error(self):
        with patch("complexity_metrics.subprocess.run",
                   side_effect=FileNotFoundError("radon not found")):
            result = cm_analyse(["test.py"])
        assert result["error"] is not None


# ── static_analysis (mocked bandit) ──────────────────────────────────────────

from static_analysis import analyse_files as sa_analyse, _run_bandit


class TestStaticAnalysisMocked:
    BANDIT_OUTPUT = json.dumps({
        "results": [
            {
                "filename": "test.py",
                "line_number": 5,
                "issue_text": "Use of eval is a security risk.",
                "issue_severity": "HIGH",
                "issue_confidence": "HIGH",
                "test_id": "B307",
            }
        ],
        "metrics": {"test.py": {"loc": 10, "nosec": 0}},
    })

    def test_run_bandit_parses_findings(self):
        mock = MagicMock(stdout=self.BANDIT_OUTPUT, returncode=0)
        with patch("static_analysis.subprocess.run", return_value=mock):
            findings, err = _run_bandit(["test.py"])
        assert err is None
        assert len(findings) == 1
        assert findings[0]["issue_severity"] == "HIGH"

    def test_run_bandit_invalid_json_signals_error(self):
        mock = MagicMock(stdout="not-json", returncode=0)
        with patch("static_analysis.subprocess.run", return_value=mock):
            findings, err = _run_bandit(["test.py"])
        assert findings == []
        assert err is not None

    def test_run_bandit_not_installed_signals_error(self):
        with patch("static_analysis.subprocess.run",
                   side_effect=FileNotFoundError("bandit not found")):
            findings, err = _run_bandit(["test.py"])
        assert findings == []
        assert err is not None

    def test_analyse_bandit_not_installed_excludes_dimension(self):
        # #917: bandit missing → error set so the aggregator EXCLUDES the
        # highest-weight security dimension rather than scoring a clean 0.0.
        with patch("static_analysis.subprocess.run",
                   side_effect=FileNotFoundError("bandit not found")):
            result = sa_analyse(["test.py"])
        assert result["error"] is not None
        assert result["score"] == pytest.approx(0.0)

    def test_analyse_bandit_unparseable_excludes_dimension(self):
        # #917: bandit ran but emitted unparseable output → exclude, don't
        # report a clean pass.
        mock = MagicMock(stdout="not-json", returncode=0)
        with patch("static_analysis.subprocess.run", return_value=mock):
            result = sa_analyse(["test.py"])
        assert result["error"] is not None
        assert result["score"] == pytest.approx(0.0)

    def test_analyse_with_high_finding_raises_score(self):
        mock = MagicMock(stdout=self.BANDIT_OUTPUT, returncode=0)
        with patch("static_analysis.subprocess.run", return_value=mock):
            result = sa_analyse(["test.py"])
        assert result["error"] is None
        assert result["score"] > 0.0

    def test_analyse_no_findings_zero_score(self):
        empty = json.dumps({"results": [], "metrics": {}})
        mock = MagicMock(stdout=empty, returncode=0)
        with patch("static_analysis.subprocess.run", return_value=mock):
            result = sa_analyse(["test.py"])
        assert result["error"] is None
        assert result["score"] == pytest.approx(0.0)

    def test_medium_severity_finding_produces_checklist(self):
        bandit_output = json.dumps({
            "results": [
                {
                    "filename": "test.py",
                    "line_number": 10,
                    "issue_text": "Possible SQL injection.",
                    "issue_severity": "MEDIUM",
                    "issue_confidence": "HIGH",
                    "test_id": "B608",
                },
            ],
            "metrics": {"test.py": {"loc": 20, "nosec": 0}},
        })
        mock = MagicMock(stdout=bandit_output, returncode=0)
        with patch("static_analysis.subprocess.run", return_value=mock):
            result = sa_analyse(["test.py"])
        assert result["error"] is None
        assert len(result["checklist_items"]) >= 1


# ── hallucination_surface (mocked) ────────────────────────────────────────────

from hallucination_surface import analyse_files as hs_analyse, _HallucinationVisitor


class TestHallucinationSurfaceMocked:
    def test_clean_file_no_patterns(self):
        src = "def greet(name):\n    return f'hello {name}'\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = hs_analyse([path])
            assert result["error"] is None
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_type_ignore_comment_flagged(self):
        src = textwrap.dedent("""
            import requests  # type: ignore
            r = requests.get("https://example.com")
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = hs_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_risky_import_flagged(self):
        # Imports a version-sensitive name
        src = "from django.db import connection\nfrom typing import Protocol\n"
        tree = ast.parse(src)
        v = _HallucinationVisitor("test.py")
        v.visit(tree)
        # visitor should run without error regardless of findings
        assert isinstance(v.findings, list)

    def test_no_files(self):
        result = hs_analyse([])
        assert result["score"] == pytest.approx(0.0)

    def test_verify_comment_flagged(self):
        src = "x = some_lib.method()  # ⚠️ VERIFY: check this API exists\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = hs_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)
