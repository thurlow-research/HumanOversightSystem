"""
Integration tests for n1_detector_js.py (S9, ADR-032 D8).

tree-sitter is an in-process library (unlike a subprocess-based linter), so
these tests exercise the real parser against real temp files rather than
mocking, matching test_function_metrics_js.py's approach.
"""
import os
import tempfile
import textwrap

import pytest

from n1_detector_js import analyse_files as n1js_analyse
from schema import WEIGHTS

CLEAN_TS = textwrap.dedent(
    """
    async function loadAll(ids: number[]) {
      const items = await Promise.all(ids.map(id => fetchOne(id)));
      return items;
    }
    """
)

AWAIT_IN_FOR_TS = textwrap.dedent(
    """
    async function loadAll(ids: number[]) {
      const items = [];
      for (const id of ids) {
        const item = await fetchOne(id);
        items.push(item);
      }
      return items;
    }
    """
)

FETCH_IN_WHILE_TS = textwrap.dedent(
    """
    async function poll(ids: number[]) {
      let i = 0;
      while (i < ids.length) {
        fetch(`/api/items/${ids[i]}`);
        i++;
      }
    }
    """
)

FETCH_IN_FOREACH_TS = textwrap.dedent(
    """
    function loadAll(ids: number[]) {
      ids.forEach(id => {
        fetch(`/api/items/${id}`);
      });
    }
    """
)

AWAIT_OUTSIDE_LOOP_TS = textwrap.dedent(
    """
    async function loadOne(id: number) {
      for (const x of []) {
        // no await here
      }
      const item = await fetchOne(id);
      return item;
    }
    """
)

GARBAGE_TS = "function broken( {{{ !!! not real syntax at all $$$ ###"


def _tmpfile(content: str, suffix: str = ".ts") -> str:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(content)
    f.close()
    return f.name


class TestN1DetectorJs:
    def test_no_files(self):
        result = n1js_analyse([])
        assert result["score"] == pytest.approx(0.0)
        assert result["dimension"] == "n1_queries"

    def test_clean_batched_code_scores_zero(self):
        path = _tmpfile(CLEAN_TS)
        try:
            result = n1js_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["candidate_count"] == 0
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_await_inside_for_of_flagged(self):
        path = _tmpfile(AWAIT_IN_FOR_TS)
        try:
            result = n1js_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["candidate_count"] >= 1
            assert result["score"] > 0.0
            assert "await" in result["evidence"][0]["message"]
        finally:
            os.unlink(path)

    def test_fetch_inside_while_flagged(self):
        path = _tmpfile(FETCH_IN_WHILE_TS)
        try:
            result = n1js_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["candidate_count"] >= 1
            assert "fetch" in result["evidence"][0]["message"]
        finally:
            os.unlink(path)

    def test_fetch_inside_foreach_callback_flagged(self):
        path = _tmpfile(FETCH_IN_FOREACH_TS)
        try:
            result = n1js_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["candidate_count"] >= 1
        finally:
            os.unlink(path)

    def test_await_after_loop_not_flagged(self):
        path = _tmpfile(AWAIT_OUTSIDE_LOOP_TS)
        try:
            result = n1js_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["candidate_count"] == 0
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_flagged_file_scores_higher_than_clean(self):
        clean = _tmpfile(CLEAN_TS)
        flagged = _tmpfile(AWAIT_IN_FOR_TS)
        try:
            r_clean = n1js_analyse([clean])
            r_flagged = n1js_analyse([flagged])
            assert r_flagged["score"] > r_clean["score"]
        finally:
            os.unlink(clean)
            os.unlink(flagged)

    def test_all_unparseable_excludes_dimension(self):
        path = _tmpfile(GARBAGE_TS)
        try:
            result = n1js_analyse([path])
            assert result["error"] is not None
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_partial_unparseable_keeps_signal_and_flags(self):
        good = _tmpfile(AWAIT_IN_FOR_TS)
        bad = _tmpfile(GARBAGE_TS)
        try:
            result = n1js_analyse([good, bad])
            assert result["error"] is None
            assert result["score"] > 0.0
            assert result["raw_value"]["parse_errors"]
            assert any("could not be fully parsed" in c for c in result["checklist_items"])
        finally:
            os.unlink(good)
            os.unlink(bad)

    def test_astro_extracts_frontmatter_and_script(self):
        src = textwrap.dedent(
            """\
            ---
            async function frontmatterFn(ids) {
              for (const id of ids) {
                await fetchOne(id);
              }
            }
            ---
            <div></div>
            <script>
            async function scriptFn(ids) {
              for (const id of ids) {
                fetch(`/api/${id}`);
              }
            }
            </script>
            """
        )
        path = _tmpfile(src, suffix=".astro")
        try:
            result = n1js_analyse([path])
            assert result["error"] is None
            assert result["raw_value"]["candidate_count"] >= 2
        finally:
            os.unlink(path)

    def test_result_envelope(self):
        path = _tmpfile(CLEAN_TS)
        try:
            result = n1js_analyse([path])
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
        # AC-3: same dimension string + WEIGHTS key as n1_detector.py.
        path = _tmpfile(CLEAN_TS)
        try:
            result = n1js_analyse([path])
            assert result["dimension"] == "n1_queries"
            assert result["weight"] == WEIGHTS["n1_queries"]
        finally:
            os.unlink(path)

    def test_raw_value_marked_provisional(self):
        # ADR-032 D8: raw_value.heuristic must read "provisional".
        path = _tmpfile(CLEAN_TS)
        try:
            result = n1js_analyse([path])
            assert result["raw_value"]["heuristic"] == "provisional"
        finally:
            os.unlink(path)
