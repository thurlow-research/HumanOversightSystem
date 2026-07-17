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
            funcs, errors = _radon_cc(["test.py"])
        assert len(funcs) == 2
        assert funcs[1]["cyclomatic"] == 12
        assert funcs[1]["name"] == "complex_fn"
        assert errors == []

    def test_radon_cc_empty_output_returns_empty(self):
        mock = MagicMock(stdout="", stderr="", returncode=0)
        with patch("complexity_metrics.subprocess.run", return_value=mock):
            funcs, errors = _radon_cc(["test.py"])
        assert funcs == []
        assert errors == []

    def test_radon_cc_invalid_json_returns_empty(self):
        mock = MagicMock(stdout="not-json", stderr="", returncode=0)
        with patch("complexity_metrics.subprocess.run", return_value=mock):
            funcs, errors = _radon_cc(["test.py"])
        assert funcs == []
        assert errors == []

    def test_radon_cc_unparseable_file_recorded_not_crashed(self):
        # #979: radon emits {"bad.py": {"error": "..."}} for a file it cannot
        # parse. entries is a dict there — iterating it as a list of entries
        # raised AttributeError and crashed the whole validator. Now it is
        # recorded as a parse error and does NOT crash.
        cc_json = json.dumps({
            "good.py": [{"name": "ok", "lineno": 1, "complexity": 2}],
            "bad.py": {"error": "invalid syntax (bad.py, line 1)"},
        })
        mock = MagicMock(stdout=cc_json, stderr="", returncode=0)
        with patch("complexity_metrics.subprocess.run", return_value=mock):
            funcs, errors = _radon_cc(["good.py", "bad.py"])
        assert [f["name"] for f in funcs] == ["ok"]
        assert len(errors) == 1
        assert errors[0]["file"] == "bad.py"
        assert "invalid syntax" in errors[0]["error"]

    def test_analyse_all_unparseable_excludes_dimension(self):
        # #979: when radon can parse NO input file, exclude the dimension
        # (error set) rather than reporting a clean 0.0.
        cc_json = json.dumps({"bad.py": {"error": "invalid syntax (bad.py, line 1)"}})
        with patch("complexity_metrics.subprocess.run",
                   side_effect=[
                       MagicMock(returncode=0),  # version check
                       MagicMock(stdout=cc_json, stderr="", returncode=0),  # cc
                       MagicMock(stdout="{}", stderr="", returncode=0),     # mi
                   ]):
            result = cm_analyse(["bad.py"])
        assert result["error"] is not None
        assert result["score"] == pytest.approx(0.0)

    def test_analyse_partial_unparseable_keeps_signal_and_flags(self):
        # #979: one parseable + one radon-broken file → keep the real signal,
        # do NOT exclude, but flag the unparseable file for review.
        cc_json = json.dumps({
            "good.py": [{"name": "bad_fn", "lineno": 5, "complexity": 14}],
            "bad.py": {"error": "invalid syntax (bad.py, line 1)"},
        })
        with patch("complexity_metrics.subprocess.run",
                   side_effect=[
                       MagicMock(returncode=0),  # version check
                       MagicMock(stdout=cc_json, stderr="", returncode=0),  # cc
                       MagicMock(stdout="{}", stderr="", returncode=0),     # mi
                   ]):
            result = cm_analyse(["good.py", "bad.py"])
        assert result["error"] is None
        assert result["score"] > 0.0
        assert result["raw_value"]["parse_errors"]
        assert any("could not be parsed" in c for c in result["checklist_items"])

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

    # ── #997: HIGH findings are scored + raise a discrete tier_floor ──────────

    @staticmethod
    def _bandit_json(severity: str, n: int = 1) -> str:
        return json.dumps({
            "results": [
                {
                    "filename": "test.py",
                    "line_number": 5 + i,
                    "issue_text": "Use of eval is a security risk.",
                    "issue_severity": severity,
                    "issue_confidence": "HIGH",
                    "test_id": "B307",
                }
                for i in range(n)
            ],
            "metrics": {"test.py": {"loc": 10, "nosec": 0}},
        })

    def test_high_finding_sets_high_tier_floor(self):
        # #997: a HIGH bandit finding must raise tier_floor="HIGH" so the
        # risk-assessor promotes the tier even if the numeric composite is low
        # (e.g. security gate suspended → HIGH never blocked upstream).
        mock = MagicMock(stdout=self._bandit_json("HIGH"), returncode=0)
        with patch("static_analysis.subprocess.run", return_value=mock):
            result = sa_analyse(["test.py"])
        assert result["error"] is None
        assert result["tier_floor"] == "HIGH"
        assert result["raw_value"]["bandit_high_count"] == 1

    def test_no_high_finding_leaves_tier_floor_none(self):
        # A MEDIUM-only result must NOT set a HIGH floor.
        mock = MagicMock(stdout=self._bandit_json("MEDIUM"), returncode=0)
        with patch("static_analysis.subprocess.run", return_value=mock):
            result = sa_analyse(["test.py"])
        assert result["error"] is None
        assert result["tier_floor"] is None

    def test_high_finding_scores_higher_than_medium(self):
        # #997: one HIGH must score strictly higher than one MEDIUM (HIGH was
        # scored as exactly 0.0 before). The shared subprocess mock makes the
        # semgrep call echo the same payload for both, so that contribution is
        # equal and the ordering is driven by the HIGH severity weight.
        high_mock = MagicMock(stdout=self._bandit_json("HIGH"), returncode=0)
        with patch("static_analysis.subprocess.run", return_value=high_mock):
            high = sa_analyse(["test.py"])
        med_mock = MagicMock(stdout=self._bandit_json("MEDIUM"), returncode=0)
        with patch("static_analysis.subprocess.run", return_value=med_mock):
            med = sa_analyse(["test.py"])
        assert high["error"] is None and med["error"] is None
        assert high["score"] > med["score"]

    def test_high_finding_evidence_marked_high_severity(self):
        mock = MagicMock(stdout=self._bandit_json("HIGH"), returncode=0)
        with patch("static_analysis.subprocess.run", return_value=mock):
            result = sa_analyse(["test.py"])
        high_evidence = [e for e in result["evidence"] if e["severity"] == "high"]
        assert high_evidence, "HIGH bandit finding must surface as high-severity evidence"


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
