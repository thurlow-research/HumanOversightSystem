"""
Tests for prompt_audit_risk.py — prompt ambiguity and fidelity surface scoring.

The ambiguity scorer and fidelity surface are pure Python — excellent mutation targets.
Primary mutation targets:
  - _AMBIGUITY_PATTERNS weights (change 0.5 to 0.4, etc.)
  - _CLARITY_PATTERNS weights (change -0.2 to -0.1)
  - normalize() call boundaries
  - Pattern matching logic
"""
import json
import textwrap
import tempfile
import os
import pytest
from unittest.mock import patch, MagicMock
from prompt_audit_risk import (
    score_prompt_ambiguity,
    score_fidelity_surface,
    get_prompt_artifact,
    get_process_ambiguity,
    analyse_files,
)


# ── score_prompt_ambiguity() ──────────────────────────────────────────────────

class TestScorePromptAmbiguity:
    def test_empty_prompt_zero_score(self):
        score, signals = score_prompt_ambiguity("")
        assert score == pytest.approx(0.0)
        assert signals == []

    def test_clean_spec_prompt_low_score(self):
        prompt = textwrap.dedent("""
            Write a Django view that validates user input per spec §3.
            Must return 400 on invalid input. Required fields: email, name.
        """)
        score, _ = score_prompt_ambiguity(prompt)
        # Clarity markers reduce the score
        assert score < 0.5

    def test_vague_prompt_higher_score(self):
        prompt = "Maybe do something with the data. TBD. Handle edge cases etc."
        score, _ = score_prompt_ambiguity(prompt)
        assert score > 0.3

    def test_tbd_increases_score(self):
        score_without, _ = score_prompt_ambiguity("Write a function.")
        score_with, _    = score_prompt_ambiguity("Write a function. TBD: error handling.")
        assert score_with > score_without

    def test_question_marks_increase_score(self):
        score_clean, _ = score_prompt_ambiguity("Implement the login flow.")
        score_q, _     = score_prompt_ambiguity("Implement the login flow? Maybe add remember me?")
        assert score_q > score_clean

    def test_normative_language_reduces_score(self):
        score_a, _ = score_prompt_ambiguity("Write a validator.")
        score_b, _ = score_prompt_ambiguity("Write a validator. Must return 400. Required fields.")
        assert score_b <= score_a

    def test_spec_citation_reduces_score(self):
        score_no_cite, _ = score_prompt_ambiguity("Handle the booking flow.")
        score_cite, _    = score_prompt_ambiguity("Handle the booking flow per spec §4.2.")
        assert score_cite <= score_no_cite

    def test_signals_list_populated(self):
        _, signals = score_prompt_ambiguity("TBD: clarify requirements. Maybe use Redis?")
        assert len(signals) > 0

    def test_score_capped_at_one(self):
        # Pile on many ambiguity signals
        very_vague = " ".join([
            "TBD maybe probably perhaps unclear etc. I don't know.",
            "TBD maybe probably perhaps unclear etc. I don't know.",
            "TBD maybe probably perhaps unclear etc. I don't know.",
        ])
        score, _ = score_prompt_ambiguity(very_vague)
        assert score <= 1.0

    def test_score_non_negative(self):
        # Pile on clarity signals — should never go below 0
        very_clear = " ".join([
            "Must precisely implement per spec §1 §2 §3.",
            "Required: unit tests, exactly as specified.",
            "Specifically: must shall required per RFC.",
        ] * 5)
        score, _ = score_prompt_ambiguity(very_clear)
        assert score >= 0.0


# ── score_fidelity_surface() ──────────────────────────────────────────────────

class TestScoreFidelitySurface:
    """score_fidelity_surface(prompt_text, code_text) -> (float, list)"""

    def test_no_code_no_score(self):
        score, signals = score_fidelity_surface("", "")
        assert score == pytest.approx(0.0)

    def test_short_prompt_long_code_raises_score(self):
        prompt = "Do x."
        code = "\n".join(f"def fn_{i}(x): return x * {i}" for i in range(30))
        score, _ = score_fidelity_surface(prompt, code)
        assert score > 0.0

    def test_unmentioned_functions_raise_score(self):
        prompt = "Write two functions."
        code = "\n".join(f"def util_{i}(x): return x" for i in range(10))
        score, _ = score_fidelity_surface(prompt, code)
        prompt_all = " ".join(f"util_{i}" for i in range(10)) + " Write ten functions."
        score_mentioned, _ = score_fidelity_surface(prompt_all, code)
        assert score >= score_mentioned

    def test_result_is_float(self):
        score, _ = score_fidelity_surface("Write f.", "def f(): pass")
        assert isinstance(score, float)

    def test_score_bounded(self):
        score, _ = score_fidelity_surface("x", "def a(): pass\ndef b(): pass")
        assert 0.0 <= score <= 1.0


# ── get_prompt_artifact() ────────────────────────────────────────────────────

class TestGetPromptArtifact:
    def test_direct_mirror_path_found(self):
        tmpdir = tempfile.mkdtemp()
        artifact = os.path.join(tmpdir, "views.md")
        with open(artifact, "w") as f:
            f.write("prompt content")
        src = os.path.join(tmpdir, "views.py")
        try:
            text, path = get_prompt_artifact(src, tmpdir)
            assert text is not None
            assert "prompt content" in text
        finally:
            import shutil; shutil.rmtree(tmpdir)

    def test_no_artifact_returns_none(self):
        text, path = get_prompt_artifact("/nonexistent/views.py", "/nonexistent/prompts")
        assert text is None
        assert path is None

    def test_git_trailer_path_used(self):
        tmpdir = tempfile.mkdtemp()
        artifact = os.path.join(tmpdir, "custom.md")
        with open(artifact, "w") as f:
            f.write("from git trailer")
        git_log = f"Prompt-Artifact: {artifact}\nAI-Risk: HIGH\n"
        with patch("prompt_audit_risk.subprocess.run",
                   return_value=MagicMock(stdout=git_log)):
            text, path = get_prompt_artifact("auth/views.py", tmpdir)
        try:
            assert text is not None
        finally:
            import shutil; shutil.rmtree(tmpdir)


# ── get_process_ambiguity() ───────────────────────────────────────────────────

class TestGetProcessAmbiguity:
    def test_no_step_returns_zero(self):
        score, signals = get_process_ambiguity(step=None)
        assert 0.0 <= score <= 1.0

    def test_with_step_runs_without_error(self):
        with patch("prompt_audit_risk.subprocess.run",
                   return_value=MagicMock(stdout="[]", returncode=0)):
            score, signals = get_process_ambiguity(step="3")
        assert 0.0 <= score <= 1.0

    def test_spec_gap_issues_raise_score(self):
        issues = [{"number": i, "title": f"gap {i}"} for i in range(5)]
        with patch("prompt_audit_risk.subprocess.run",
                   return_value=MagicMock(stdout=json.dumps(issues), returncode=0)):
            score, signals = get_process_ambiguity(step="3")
        assert score > 0.0


# ── analyse_files() ───────────────────────────────────────────────────────────

class TestPromptAuditAnalyse:
    def test_no_files(self):
        result = analyse_files([])
        assert result["score"] == pytest.approx(0.0)

    def test_py_file_no_artifact(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def greet(name): return f'hello {name}'\n")
            path = f.name
        try:
            result = analyse_files([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_md_prompt_file_analysed(self):
        prompt = "Write a function. TBD: add tests. Maybe use Redis?\n"
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(prompt)
            path = f.name
        try:
            result = analyse_files([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_py_file_with_matching_prompt_artifact(self):
        tmpdir = tempfile.mkdtemp()
        py_path = os.path.join(tmpdir, "views.py")
        md_path = os.path.join(tmpdir, "views.md")
        with open(py_path, "w") as f:
            f.write("def view(request): return None\n")
        with open(md_path, "w") as f:
            f.write("Implement a Django view. Must handle GET requests per spec §5.\n")
        try:
            result = analyse_files([py_path], prompts_dir=tmpdir)
            assert 0.0 <= result["score"] <= 1.0
            assert result["error"] is None
        finally:
            import shutil; shutil.rmtree(tmpdir)

    def test_high_ambiguity_prompt_raises_score(self):
        tmpdir = tempfile.mkdtemp()
        py_path = os.path.join(tmpdir, "service.py")
        md_path = os.path.join(tmpdir, "service.md")
        with open(py_path, "w") as f:
            f.write("def process(): pass\n")
        with open(md_path, "w") as f:
            f.write("TBD: maybe do something. I don't know. Unclear requirements. etc.\n")
        try:
            result = analyse_files([py_path], prompts_dir=tmpdir)
            assert result["score"] > 0.0
        finally:
            import shutil; shutil.rmtree(tmpdir)
