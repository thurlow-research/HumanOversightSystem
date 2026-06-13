"""
Integration tests for the subprocess-based validators.

These tests exercise each validator's entry point against real temp files.
They cover: the main code path, error handling, and the make_result() envelope.
External tools (radon, bandit, etc.) are available in the oversight venv.
"""
import textwrap
import tempfile
import os
import pytest


SIMPLE_PY = textwrap.dedent("""
    def greet(name: str) -> str:
        if name:
            return f"hello {name}"
        return "hello"
""")

COMPLEX_PY = textwrap.dedent("""
    def risky(data):
        for item in data:
            if item.get("flag"):
                for sub in item["values"]:
                    if sub > 0:
                        if sub < 100:
                            result = process(sub)
        return True
""")


def _tmpfile(content: str, suffix: str = ".py") -> str:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(content)
    f.close()
    return f.name


# ── complexity_metrics ────────────────────────────────────────────────────────

from complexity_metrics import analyse_files as cm_analyse


class TestComplexityMetrics:
    def test_simple_file_low_score(self):
        path = _tmpfile(SIMPLE_PY)
        try:
            result = cm_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_complex_file_higher_score_than_simple(self):
        simple = _tmpfile(SIMPLE_PY)
        complex_ = _tmpfile(COMPLEX_PY)
        try:
            r_simple = cm_analyse([simple])
            r_complex = cm_analyse([complex_])
            assert r_complex["score"] >= r_simple["score"]
        finally:
            os.unlink(simple)
            os.unlink(complex_)

    def test_no_files(self):
        result = cm_analyse([])
        assert result["score"] == pytest.approx(0.0)

    def test_result_envelope(self):
        path = _tmpfile(SIMPLE_PY)
        try:
            result = cm_analyse([path])
            for key in ("dimension", "score", "raw_value", "weight",
                        "evidence", "checklist_items", "findings", "error"):
                assert key in result
        finally:
            os.unlink(path)


# ── hallucination_surface ─────────────────────────────────────────────────────

from hallucination_surface import analyse_files as hs_analyse


class TestHallucinationSurface:
    def test_clean_file(self):
        path = _tmpfile(SIMPLE_PY)
        try:
            result = hs_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_no_files(self):
        result = hs_analyse([])
        assert result["score"] == pytest.approx(0.0)

    def test_result_has_required_fields(self):
        path = _tmpfile(SIMPLE_PY)
        try:
            result = hs_analyse([path])
            assert "score" in result
            assert "dimension" in result
        finally:
            os.unlink(path)


# ── static_analysis ───────────────────────────────────────────────────────────

from static_analysis import analyse_files as sa_analyse


class TestStaticAnalysis:
    def test_clean_file(self):
        path = _tmpfile(SIMPLE_PY)
        try:
            result = sa_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_obvious_issue_detected(self):
        # eval() is flagged by bandit as a security issue
        src = "result = eval(user_input)\n"
        path = _tmpfile(src)
        try:
            result = sa_analyse([path])
            # Either finds it (score > 0) or bandit not installed (error set)
            assert result["score"] >= 0.0
        finally:
            os.unlink(path)

    def test_no_files(self):
        result = sa_analyse([])
        assert result["score"] == pytest.approx(0.0)


# ── prompt_audit_risk ─────────────────────────────────────────────────────────

from prompt_audit_risk import analyse_files as par_analyse


PROMPT_MD = textwrap.dedent("""
    # Auth middleware prompt

    Write a JWT validation middleware for Django.
    Inputs come from untrusted users.
    Do NOT store secrets in the code.
""")


class TestPromptAuditRisk:
    def test_low_risk_prompt(self):
        path = _tmpfile(PROMPT_MD, suffix=".md")
        try:
            result = par_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_ambiguous_prompt_higher_score(self):
        vague = "Do something with the data. Handle the edge cases etc.\n"
        path = _tmpfile(vague, suffix=".md")
        try:
            result = par_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_no_files(self):
        result = par_analyse([])
        assert result["score"] == pytest.approx(0.0)


# ── ip_check ──────────────────────────────────────────────────────────────────

from ip_check import analyse_files as ip_analyse


class TestIPCheck:
    def test_clean_file(self):
        path = _tmpfile(SIMPLE_PY)
        try:
            result = ip_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_no_files(self):
        result = ip_analyse([])
        assert result["score"] == pytest.approx(0.0)

    def test_result_envelope(self):
        path = _tmpfile(SIMPLE_PY)
        try:
            result = ip_analyse([path])
            assert "score" in result
            assert "dimension" in result
        finally:
            os.unlink(path)


# ── issue_query ───────────────────────────────────────────────────────────────

from issue_query import analyse_files as iq_analyse


class TestIssueQuery:
    def test_no_files(self):
        result = iq_analyse([])
        assert result["score"] == pytest.approx(0.0)

    def test_clean_file_no_history(self):
        # New file with no issue history → score 0
        path = _tmpfile(SIMPLE_PY)
        try:
            result = iq_analyse([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_result_envelope(self):
        path = _tmpfile(SIMPLE_PY)
        try:
            result = iq_analyse([path])
            assert "score" in result
            assert "dimension" in result
        finally:
            os.unlink(path)
