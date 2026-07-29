"""
Integration tests for function_metrics_js.py (S5, ADR-032 D5).

tree-sitter is an in-process library (unlike radon's subprocess), so these
tests exercise the real parser against real temp files rather than mocking.
"""
import os
import tempfile
import textwrap

import pytest

from function_metrics_js import analyse_files as fmjs_analyse
from schema import WEIGHTS

SIMPLE_TS = textwrap.dedent(
    """
    function greet(name: string): string {
      return `hello ${name}`;
    }
    """
)

# 7 params (>6), nesting if->for->while->if = depth 4 (>=4), 6 return/throw
# paths (>5): every threshold is tripped by one function.
CONCERNING_TS = textwrap.dedent(
    """
    function complex(a: number, b: number, c: number, d: number, e: number, f: number, g: number): number {
      if (a > 0) {
        for (let i = 0; i < b; i++) {
          while (i > 0) {
            if (c > 0) {
              return 1;
            }
          }
        }
      }
      if (d) return 2;
      if (e) return 3;
      if (f) return 4;
      if (g) return 5;
      throw new Error("no");
    }
    """
)

GARBAGE_TS = "function broken( {{{ !!! not real syntax at all $$$ ###"


def _tmpfile(content: str, suffix: str = ".ts") -> str:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestFunctionMetricsJs:
    def test_simple_function_scores_low(self):
        path = _tmpfile(SIMPLE_TS)
        try:
            result = fmjs_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["total_functions"] == 1
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_concerning_function_trips_every_threshold(self):
        path = _tmpfile(CONCERNING_TS)
        try:
            result = fmjs_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["high_param_count"] == 1
            assert result["raw_value"]["deeply_nested"] == 1
            assert result["raw_value"]["many_return_paths"] == 1
            assert result["score"] > 0.5
            assert "params=7" in result["evidence"][0]["message"]
            assert "nesting=4" in result["evidence"][0]["message"]
        finally:
            os.unlink(path)

    def test_concerning_file_scores_higher_than_simple(self):
        simple = _tmpfile(SIMPLE_TS)
        concerning = _tmpfile(CONCERNING_TS)
        try:
            r_simple = fmjs_analyse([simple])
            r_concerning = fmjs_analyse([concerning])
            assert r_concerning["score"] > r_simple["score"]
        finally:
            os.unlink(simple)
            os.unlink(concerning)

    def test_this_parameter_excluded_from_param_count(self):
        src = textwrap.dedent(
            """
            class C {
              method(this: C, a: number, b: number): number {
                return a + b;
              }
            }
            """
        )
        path = _tmpfile(src)
        try:
            result = fmjs_analyse([path])
            assert result["raw_value"]["high_param_count"] == 0
        finally:
            os.unlink(path)

    def test_unparenthesized_arrow_param_counts_as_one(self):
        src = "const h = x => x + 1;\n"
        path = _tmpfile(src)
        try:
            result = fmjs_analyse([path])
            assert result["raw_value"]["total_functions"] == 1
            assert result["raw_value"]["high_param_count"] == 0
        finally:
            os.unlink(path)

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
            result = fmjs_analyse([path])
            # inner() has 3 return paths, nesting=1; outer() has 1 return path
            # of its own. If inner's leaked into outer, total would differ.
            assert result["raw_value"]["total_functions"] == 2
            assert result["raw_value"]["many_return_paths"] == 0
        finally:
            os.unlink(path)

    def test_all_unparseable_excludes_dimension(self):
        path = _tmpfile(GARBAGE_TS)
        try:
            result = fmjs_analyse([path])
            assert result["error"] is not None
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_partial_unparseable_keeps_signal_and_flags(self):
        good = _tmpfile(CONCERNING_TS)
        bad = _tmpfile(GARBAGE_TS)
        try:
            result = fmjs_analyse([good, bad])
            assert result["error"] is None
            assert result["score"] > 0.0
            assert result["raw_value"]["parse_errors"]
            assert any("could not be fully parsed" in c for c in result["checklist_items"])
        finally:
            os.unlink(good)
            os.unlink(bad)

    def test_no_files(self):
        result = fmjs_analyse([])
        assert result["score"] == pytest.approx(0.0)
        assert result["dimension"] == "function_metrics"

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
            result = fmjs_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["total_functions"] == 2
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
            result = fmjs_analyse([path])
            assert result["error"] is None
            assert not result["raw_value"]["parse_errors"]
        finally:
            os.unlink(path)

    def test_result_envelope(self):
        path = _tmpfile(SIMPLE_TS)
        try:
            result = fmjs_analyse([path])
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
        # AC-3: same dimension string + WEIGHTS key as function_metrics.py.
        path = _tmpfile(SIMPLE_TS)
        try:
            result = fmjs_analyse([path])
            assert result["dimension"] == "function_metrics"
            assert result["weight"] == WEIGHTS["function_metrics"]
        finally:
            os.unlink(path)
