"""
Tests for rn_calculator_js.py — JS/TS sibling of rn_calculator.py (S8, ADR-032 D7).

tree-sitter is an in-process library (unlike radon's subprocess), so these
tests exercise the real parser against real temp files rather than mocking.

Primary mutation targets:
  - nesting_increment(): identical Dai et al. coefficient table to the Python sibling
  - _count_logical_ops(): &&/||/?? operators and ternaries in a condition
  - _FunctionRNVisitor: depth tracking, nesting increment application
  - the "provisional-js-reuses-python-weights" calibration flag (D7)
"""
import json
import os
import sys
import tempfile
import textwrap

import pytest

from rn_calculator_js import (
    _NESTING_TABLE,
    _NESTING_W,
    _NESTING_B,
    _CALIBRATION,
    _checklist_items,
    _count_logical_ops,
    _FunctionRNVisitor,
    analyse_files,
    apply_task_class_floor,
    nesting_increment,
)
from schema import WEIGHTS


def _tmpfile(content: str, suffix: str = ".ts") -> str:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(content)
    f.close()
    return f.name


def _first_function_node(src: str):
    """Parse src with tree-sitter and return the first function_declaration node."""
    from rn_calculator_js import _TS_LANGUAGE
    from tree_sitter import Parser

    parser = Parser(_TS_LANGUAGE)
    tree = parser.parse(textwrap.dedent(src).encode("utf-8"))

    def _find(node):
        if node.type == "function_declaration":
            return node
        for child in node.children:
            found = _find(child)
            if found is not None:
                return found
        return None

    return _find(tree.root_node)


# ── nesting_increment() — identical table to the Python sibling ─────────────

class TestNestingIncrement:
    @pytest.mark.parametrize("depth,expected", [
        (0, 0.0),
        (1, 1.0),
        (2, 3.0),
        (3, 4.8),
        (4, 7.1),
    ])
    def test_table_values(self, depth, expected):
        assert nesting_increment(depth) == pytest.approx(expected)

    def test_beyond_table_uses_linear_formula(self):
        result = nesting_increment(5)
        expected = max(0.0, _NESTING_W * 5 + _NESTING_B)
        assert result == pytest.approx(round(expected, 1))

    def test_linear_formula_never_negative(self):
        for depth in range(5, 20):
            assert nesting_increment(depth) >= 0.0

    def test_monotone_in_table(self):
        for d in range(len(_NESTING_TABLE) - 1):
            assert _NESTING_TABLE[d] <= _NESTING_TABLE[d + 1]


# ── _count_logical_ops() ──────────────────────────────────────────────────

class TestCountLogicalOps:
    def test_simple_if_no_ops(self):
        node = _first_function_node("function f(x) { if (x) {} }")
        if_node = next(c for c in node.children if c.type == "statement_block").children[1]
        assert _count_logical_ops(if_node) == 0

    def test_if_with_and(self):
        node = _first_function_node("function f(x, y) { if (x && y) {} }")
        if_node = next(c for c in node.children if c.type == "statement_block").children[1]
        assert _count_logical_ops(if_node) == 1

    def test_if_with_and_and_or(self):
        node = _first_function_node("function f(x, y, z) { if (x && y && z) {} }")
        if_node = next(c for c in node.children if c.type == "statement_block").children[1]
        assert _count_logical_ops(if_node) == 2

    def test_for_has_no_condition_ops(self):
        node = _first_function_node("function f(items) { for (const i of items) {} }")
        for_node = next(c for c in node.children if c.type == "statement_block").children[1]
        assert for_node.type == "for_in_statement"
        assert _count_logical_ops(for_node) == 0

    def test_ternary_counts_as_one(self):
        node = _first_function_node("function f(a, b) { if (a ? b : false) {} }")
        if_node = next(c for c in node.children if c.type == "statement_block").children[1]
        assert _count_logical_ops(if_node) == 1


# ── _FunctionRNVisitor — depth tracking and RN accumulation ─────────────────

def _visit(src: str) -> _FunctionRNVisitor:
    node = _first_function_node(src)
    visitor = _FunctionRNVisitor("test.ts", "f", node.start_point[0] + 1)
    visitor.visit(node)
    return visitor


class TestFunctionRNVisitor:
    def test_empty_function_no_statements(self):
        visitor = _visit("function f() {}")
        assert visitor.statements == []

    def test_single_if_at_depth_zero(self):
        visitor = _visit("function f(x) { if (x) {} }")
        assert len(visitor.statements) == 1
        s = visitor.statements[0]
        assert s["nesting_depth"] == 0
        assert s["rn"] == pytest.approx(1.0)

    def test_nested_if_increments_depth(self):
        visitor = _visit("function f(x, y) { if (x) { if (y) {} } }")
        assert len(visitor.statements) == 2
        assert visitor.statements[0]["nesting_depth"] == 0
        assert visitor.statements[1]["nesting_depth"] == 1
        assert visitor.statements[0]["rn"] == pytest.approx(1.0)
        # inner: nesting_increment(1) + 1 = 2.0
        assert visitor.statements[1]["rn"] == pytest.approx(2.0)

    def test_if_with_and_adds_logical_op(self):
        visitor = _visit("function f(x, y) { if (x && y) {} }")
        assert visitor.statements[0]["rn"] == pytest.approx(2.0)

    def test_for_loop_at_depth_zero(self):
        visitor = _visit("function f(items) { for (const i of items) {} }")
        assert len(visitor.statements) == 1
        assert visitor.statements[0]["rn"] == pytest.approx(1.0)

    def test_depth_restored_after_block(self):
        visitor = _visit("function f(x, y) { if (x) {} if (y) {} }")
        assert visitor.statements[0]["nesting_depth"] == 0
        assert visitor.statements[1]["nesting_depth"] == 0

    def test_while_recorded(self):
        visitor = _visit("function f(cond) { while (cond) {} }")
        assert len(visitor.statements) == 1
        assert visitor.statements[0]["type"] == "while_statement"

    def test_try_catch_recorded(self):
        visitor = _visit("function f() { try { risky(); } catch (e) { handle(e); } }")
        assert any(s["type"] == "catch_clause" for s in visitor.statements)

    def test_switch_recorded(self):
        visitor = _visit("function f(a) { switch (a) { case 1: break; default: break; } }")
        assert any(s["type"] == "switch_statement" for s in visitor.statements)

    def test_nested_function_not_folded_in(self):
        visitor = _visit(
            """
            function f(a) {
              const inner = (b) => { if (b) {} };
              if (a) {}
            }
            """
        )
        # Only the outer if is scored; the arrow function's if is a separate entry.
        assert len(visitor.statements) == 1
        assert visitor.statements[0]["type"] == "if_statement"

    def test_total_rn_accumulates(self):
        visitor = _visit("function f(x, y) { if (x) { if (y) {} } }")
        assert visitor.total_rn == pytest.approx(3.0)


# ── analyse_files() integration — uses actual temp files ────────────────────

class TestAnalyseFiles:
    def test_empty_file_returns_error(self):
        path = _tmpfile("")
        try:
            result = analyse_files([path])
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_simple_function_runs_without_error(self):
        src = "function greet(name) { if (name) { return name; } return ''; }"
        path = _tmpfile(src)
        try:
            result = analyse_files([path])
            assert result["error"] is None
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_garbage_returns_error(self):
        path = _tmpfile("function broken( {{{ !!! not real syntax at all $$$ ###")
        try:
            result = analyse_files([path])
            assert result["error"] is not None
        finally:
            os.unlink(path)

    def test_nested_function_not_double_counted(self):
        src = textwrap.dedent(
            """
            function outer(x) {
              const inner = (y) => {
                if (y) { return 1; }
              };
              return inner(x);
            }
            """
        )
        path = _tmpfile(src)
        try:
            result = analyse_files([path])
            assert result["error"] is None
            func_names = [f["function"] for f in result["findings"]]
            assert "outer" in func_names
            assert "inner" in func_names
            outer = next(f for f in result["findings"] if f["function"] == "outer")
            assert outer["risk_number"] == 0.0
        finally:
            os.unlink(path)

    def test_high_rn_function_flagged_high_risk(self):
        src = textwrap.dedent(
            """
            function risky(a, b) {
              if (a) {
                if (b) {
                  if (a && b) {
                    if (a || b) {
                      return 1;
                    }
                  }
                }
              }
              return 0;
            }
            """
        )
        path = _tmpfile(src)
        try:
            result = analyse_files([path])
            assert result["error"] is None
            assert "risky" in result["raw_value"]["high_risk_functions"]
        finally:
            os.unlink(path)

    def test_no_files(self):
        result = analyse_files([])
        assert result["dimension"] == "risk_number"
        assert result["score"] == pytest.approx(0.0)


class TestCalibrationFlag:
    """D7: the provisional calibration flag must always be present."""

    def test_calibration_flag_on_success(self):
        path = _tmpfile("function f(x) { if (x) { return 1; } }")
        try:
            result = analyse_files([path])
            assert result["raw_value"]["calibration"] == _CALIBRATION
        finally:
            os.unlink(path)

    def test_calibration_flag_on_empty(self):
        result = analyse_files([])
        assert result["raw_value"]["calibration"] == _CALIBRATION

    def test_calibration_value_matches_adr(self):
        assert _CALIBRATION == "provisional-js-reuses-python-weights"


class TestDimensionAndWeightMatchPythonSibling:
    def test_dimension_and_weight(self):
        path = _tmpfile("function f() {}")
        try:
            result = analyse_files([path])
            assert result["dimension"] == "risk_number"
            assert result["weight"] == WEIGHTS["risk_number"]
        finally:
            os.unlink(path)


class TestChecklistItems:
    def test_if_checklist(self):
        func = {
            "name": "f",
            "statements": [{"type": "if_statement", "line": 3, "rn": 1.0, "nesting_depth": 0}],
        }
        items = _checklist_items(func)
        assert any("condition" in i.lower() for i in items)

    def test_for_checklist(self):
        func = {
            "name": "f",
            "statements": [{"type": "for_statement", "line": 3, "rn": 1.0, "nesting_depth": 0}],
        }
        items = _checklist_items(func)
        assert any("loop" in i.lower() or "bound" in i.lower() for i in items)

    def test_catch_checklist(self):
        func = {
            "name": "f",
            "statements": [{"type": "catch_clause", "line": 3, "rn": 1.0, "nesting_depth": 0}],
        }
        items = _checklist_items(func)
        assert any("exception" in i.lower() or "catch" in i.lower() for i in items)

    def test_zero_rn_statements_skipped(self):
        func = {
            "name": "f",
            "statements": [{"type": "if_statement", "line": 1, "rn": 0.0, "nesting_depth": 0}],
        }
        assert _checklist_items(func) == []


class TestApplyTaskClassFloor:
    def test_unknown_task_class_no_floor(self):
        result = {"score": 0.0, "raw_value": {}}
        out = apply_task_class_floor(result, None)
        assert out["raw_value"]["floor_applied"] is False
        assert out["raw_value"]["task_class"] is None
        assert "tier_floor" not in out

    def test_refactor_low_tier_floors_to_medium(self):
        result = {"score": 0.0, "raw_value": {}}
        out = apply_task_class_floor(result, "refactor", source="commit_prefix")
        assert out["raw_value"]["floor_applied"] is True
        assert out["raw_value"]["post_floor_tier"] == "MEDIUM"
        assert out["tier_floor"] == "MEDIUM"

    def test_feat_low_tier_not_floored(self):
        result = {"score": 0.0, "raw_value": {}}
        out = apply_task_class_floor(result, "feat", source="commit_prefix")
        assert out["raw_value"]["floor_applied"] is False
        assert "tier_floor" not in out


class TestMain:
    def test_main_no_files(self, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["rn_calculator_js.py"])
        from rn_calculator_js import main
        main()
        data = json.loads(capsys.readouterr().out)
        assert data["score"] == 0.0
        assert data["error"] == "no input files"

    def test_main_with_files_flag(self, capsys, monkeypatch, tmp_path):
        ts = tmp_path / "mod.ts"
        ts.write_text("function f(x) { if (x) { return x; } }")
        monkeypatch.setattr(sys, "argv", ["rn_calculator_js.py", "--files", str(ts)])
        from rn_calculator_js import main
        main()
        data = json.loads(capsys.readouterr().out)
        assert "score" in data
        assert data["dimension"] == "risk_number"

    def test_main_valid_file_direct(self, capsys, monkeypatch, tmp_path):
        ts = tmp_path / "service.ts"
        ts.write_text("function process(x) { for (const i of x) {} }")
        monkeypatch.setattr(sys, "argv", ["rn_calculator_js.py", str(ts)])
        from rn_calculator_js import main
        main()
        data = json.loads(capsys.readouterr().out)
        assert data["error"] is None
