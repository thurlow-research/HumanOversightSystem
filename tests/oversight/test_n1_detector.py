"""
Tests for n1_detector.py — Django N+1 query heuristic.

Primary mutation targets:
  - _N1Visitor._in_loop(): depth comparison (> 0 vs >= 1, off-by-one)
  - _N1Visitor._enter_loop(): depth increment/decrement
  - _ORM_METHODS membership: what triggers a finding
  - Loop nesting: findings inside nested loops, no findings outside loops
"""
import ast
import textwrap
import pytest
from n1_detector import _N1Visitor, analyse_files, _ORM_METHODS


# ── helpers ───────────────────────────────────────────────────────────────────

def _detect(src: str) -> list[dict]:
    """Run _N1Visitor on parsed source, return findings."""
    tree = ast.parse(textwrap.dedent(src))
    visitor = _N1Visitor("test.py")
    visitor.visit(tree)
    return visitor.findings


# ── loop depth tracking ───────────────────────────────────────────────────────

class TestLoopDepthTracking:
    def test_not_in_loop_initially(self):
        v = _N1Visitor("test.py")
        assert v._loop_depth == 0
        assert not v._in_loop()

    def test_in_loop_inside_for(self):
        """ORM call inside for → finding."""
        findings = _detect("""
            for item in queryset:
                result = Model.objects.filter(pk=item.pk)
        """)
        assert len(findings) >= 1

    def test_not_in_loop_outside_for(self):
        """ORM call outside any loop → no finding."""
        findings = _detect("""
            result = Model.objects.filter(pk=1)
        """)
        assert len(findings) == 0

    def test_in_loop_inside_while(self):
        findings = _detect("""
            while condition:
                result = Model.objects.all()
        """)
        assert len(findings) >= 1

    def test_depth_restored_after_for(self):
        """Code after a for loop should not trigger findings."""
        findings = _detect("""
            for x in items:
                pass
            result = Model.objects.filter(x=1)
        """)
        # The filter is outside the loop — should produce 0 findings
        assert len(findings) == 0

    def test_depth_restored_after_while(self):
        findings = _detect("""
            while flag:
                pass
            result = Queryset.objects.all()
        """)
        assert len(findings) == 0

    def test_nested_loops_both_trigger(self):
        """Inner loop should still trigger even though outer also triggers."""
        findings = _detect("""
            for x in outer:
                for y in inner:
                    Model.objects.filter(x=x, y=y)
        """)
        assert len(findings) >= 1


# ── ORM method detection ──────────────────────────────────────────────────────

class TestORMMethodDetection:
    @pytest.mark.parametrize("method", ["filter", "all", "get", "first",
                                          "exclude", "count", "exists"])
    def test_orm_methods_detected_in_loop(self, method):
        src = f"""
            for item in items:
                x = Model.objects.{method}()
        """
        findings = _detect(src)
        assert len(findings) >= 1, f"Expected finding for .{method}() in loop"

    def test_non_orm_method_in_loop_no_finding(self):
        findings = _detect("""
            for item in items:
                x = something.totally_custom_method()
        """)
        assert len(findings) == 0

    def test_orm_method_set_is_non_empty(self):
        assert len(_ORM_METHODS) > 0

    def test_common_methods_in_set(self):
        for method in ("filter", "all", "get", "first", "last", "count"):
            assert method in _ORM_METHODS, f"{method} should be in _ORM_METHODS"


# ── analyse_files() integration ───────────────────────────────────────────────

import tempfile
import os

class TestAnalyseFiles:
    def test_clean_file_zero_score(self):
        src = textwrap.dedent("""
            def process(items):
                return [str(i) for i in items]
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = analyse_files([path])
            assert result["error"] is None
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_file_with_n1_has_nonzero_score(self):
        src = textwrap.dedent("""
            def bad_view(pks):
                results = []
                for pk in pks:
                    obj = MyModel.objects.get(pk=pk)
                    results.append(obj)
                return results
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = analyse_files([path])
            assert result["error"] is None
            assert result["score"] > 0.0
            assert len(result["evidence"]) >= 1
        finally:
            os.unlink(path)

    def test_empty_file_list(self):
        # No files → zero score, no error (graceful empty input)
        result = analyse_files([])
        assert result["score"] == pytest.approx(0.0)

    def test_result_score_in_range(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("x = 1\n")
            path = f.name
        try:
            result = analyse_files([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_all_unparseable_excludes_dimension(self):
        # #979: a syntax-error file must EXCLUDE the dimension (error set)
        # rather than report a clean 0.0 with error=None.
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def broken(:\n    for x in\n")
            path = f.name
        try:
            result = analyse_files([path])
            assert result["error"] is not None
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_non_utf8_file_excludes_dimension(self):
        # #979: latin-1 non-UTF8 bytes (passes flake8 per PEP 263) → exclude.
        with tempfile.NamedTemporaryFile(suffix=".py", mode="wb", delete=False) as f:
            f.write(b"# -*- coding: latin-1 -*-\nx = '\xe9'\n")
            path = f.name
        try:
            result = analyse_files([path])
            assert result["error"] is not None
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_partial_parse_failure_keeps_signal_and_flags(self):
        # #979: one parseable N+1 file + one broken file → keep the signal,
        # do NOT exclude, but flag the unparseable file for review.
        src = textwrap.dedent("""
            def bad_view(pks):
                for pk in pks:
                    obj = MyModel.objects.get(pk=pk)
                return obj
        """)
        good = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        good.write(src)
        good.close()
        bad = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        bad.write("def broken(:\n")
        bad.close()
        try:
            result = analyse_files([good.name, bad.name])
            assert result["error"] is None
            assert result["score"] > 0.0
            assert result["raw_value"]["parse_errors"]
            assert any("could not be parsed" in c for c in result["checklist_items"])
        finally:
            os.unlink(good.name)
            os.unlink(bad.name)
