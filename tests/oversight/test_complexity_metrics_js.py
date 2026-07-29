"""
Integration tests for complexity_metrics_js.py (S4, ADR-032 D4).

tree-sitter is an in-process library (unlike radon's subprocess), so these
tests exercise the real parser against real temp files rather than mocking.
"""
import os
import tempfile
import textwrap

import pytest

from complexity_metrics_js import analyse_files as cmjs_analyse
from schema import WEIGHTS

SIMPLE_TS = textwrap.dedent(
    """
    function greet(name: string): string {
      return `hello ${name}`;
    }
    """
)

# 1 (base) + if + elif + for + while + catch + case + case + && + || + ternary = 11
COMPLEX_TS = textwrap.dedent(
    """
    function risky(a: number, b: number): number {
      if (a > b) {
        return a;
      } else if (a < b) {
        return b;
      }
      for (let i = 0; i < 10; i++) {
        while (i > 0) {
          i--;
        }
      }
      try {
        doThing();
      } catch (e) {
        handle(e);
      }
      switch (a) {
        case 1:
          break;
        case 2:
          break;
        default:
          break;
      }
      return (a && b) || (a ? 1 : 2);
    }
    """
)

GARBAGE_TS = "function broken( {{{ !!! not real syntax at all $$$ ###"


def _tmpfile(content: str, suffix: str = ".ts") -> str:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestComplexityMetricsJs:
    def test_simple_function_scores_low(self):
        path = _tmpfile(SIMPLE_TS)
        try:
            result = cmjs_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["max_cyclomatic"] == 1
            assert result["score"] < 0.2
        finally:
            os.unlink(path)

    def test_complex_function_counts_every_decision_point(self):
        path = _tmpfile(COMPLEX_TS)
        try:
            result = cmjs_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["max_cyclomatic"] == 11
            assert "risky" in result["raw_value"]["high_complexity_functions"]
        finally:
            os.unlink(path)

    def test_complex_file_scores_higher_than_simple(self):
        simple = _tmpfile(SIMPLE_TS)
        complex_ = _tmpfile(COMPLEX_TS)
        try:
            r_simple = cmjs_analyse([simple])
            r_complex = cmjs_analyse([complex_])
            assert r_complex["score"] > r_simple["score"]
        finally:
            os.unlink(simple)
            os.unlink(complex_)

    def test_nested_function_scored_separately_not_folded_into_outer(self):
        src = textwrap.dedent(
            """
            function outer(a: number) {
              const inner = (b: number) => {
                if (b > 0) { return 1; }
                if (b < 0) { return -1; }
                return 0;
              };
              return inner(a);
            }
            """
        )
        path = _tmpfile(src)
        try:
            result = cmjs_analyse([path])
            # inner() has 2 ifs (cyclomatic=3); outer() has none of its own (cyclomatic=1).
            # If inner's branches leaked into outer, mean_cyclomatic would differ.
            assert result["raw_value"]["max_cyclomatic"] == 3
            assert result["raw_value"]["mean_cyclomatic"] == 2.0
        finally:
            os.unlink(path)

    def test_all_unparseable_excludes_dimension(self):
        path = _tmpfile(GARBAGE_TS)
        try:
            result = cmjs_analyse([path])
            assert result["error"] is not None
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_partial_unparseable_keeps_signal_and_flags(self):
        good = _tmpfile(COMPLEX_TS)
        bad = _tmpfile(GARBAGE_TS)
        try:
            result = cmjs_analyse([good, bad])
            assert result["error"] is None
            assert result["score"] > 0.0
            assert result["raw_value"]["parse_errors"]
            assert any("could not be fully parsed" in c for c in result["checklist_items"])
        finally:
            os.unlink(good)
            os.unlink(bad)

    def test_no_files(self):
        result = cmjs_analyse([])
        assert result["score"] == pytest.approx(0.0)
        assert result["dimension"] == "complexity"

    def test_astro_extracts_frontmatter_and_script_with_correct_lines(self):
        src = textwrap.dedent(
            """\
            ---
            function frontmatterFn(a) {
              if (a) { return 1; } else { return 2; }
            }
            ---
            <div>{frontmatterFn(1)}</div>
            <script>
            function scriptFn(x) {
              return x ? 1 : 0;
            }
            </script>
            """
        )
        path = _tmpfile(src, suffix=".astro")
        try:
            result = cmjs_analyse([path])
            assert result["error"] is None
            lines = {e["line"] for e in result["evidence"]}
            # frontmatterFn declared on line 2, scriptFn on line 8 of the source.
            assert 2 in lines
            assert 8 in lines
        finally:
            os.unlink(path)

    def test_tsx_jsx_syntax_parses_without_error(self):
        src = textwrap.dedent(
            """
            function Widget(props: { on: boolean }) {
              return props.on ? <div>on</div> : <div>off</div>;
            }
            """
        )
        path = _tmpfile(src, suffix=".tsx")
        try:
            result = cmjs_analyse([path])
            assert result["error"] is None
            assert not result["raw_value"]["parse_errors"]
        finally:
            os.unlink(path)

    def test_result_envelope(self):
        path = _tmpfile(SIMPLE_TS)
        try:
            result = cmjs_analyse([path])
            for key in (
                "dimension",
                "score",
                "raw_value",
                "weight",
                "evidence",
                "checklist_items",
                "findings",
                "error",
            ):
                assert key in result
        finally:
            os.unlink(path)

    def test_dimension_and_weight_match_python_sibling(self):
        # AC-3: same dimension string + WEIGHTS key as complexity_metrics.py.
        path = _tmpfile(SIMPLE_TS)
        try:
            result = cmjs_analyse([path])
            assert result["dimension"] == "complexity"
            assert result["weight"] == WEIGHTS["cyclomatic"]
        finally:
            os.unlink(path)
