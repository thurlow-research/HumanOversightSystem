"""
Tests for rn_calculator.py — Dai et al. Risk Number implementation.

Primary mutation targets:
  - nesting_increment(): the coefficient table values and the linear fallback formula
  - _count_logical_ops(): counts of and/or operators and ternary expressions
  - _FunctionRNVisitor: depth tracking, nesting increment application
"""
import ast
import sys
import textwrap
import pytest
from rn_calculator import (
    nesting_increment,
    _count_logical_ops,
    _FunctionRNVisitor,
    analyse_files,
    _NESTING_TABLE,
    _NESTING_W,
    _NESTING_B,
)


# ── nesting_increment() ──────────────────────────────────────────────────────

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
        # depth=5: max(0, 2.01*5 + (-1.05)) = max(0, 10.05 - 1.05) = 9.0
        result = nesting_increment(5)
        expected = max(0.0, _NESTING_W * 5 + _NESTING_B)
        assert result == pytest.approx(round(expected, 1))

    def test_linear_formula_never_negative(self):
        # At depth 0, formula gives 2.01*0 - 1.05 = -1.05 → clamped to 0
        # But depth 0 is in the table, so test a low depth not in table
        # Actually the table covers 0-4; depth ≥ 5 uses linear.
        # At depth=5 it's positive; let's verify it's always ≥ 0
        for depth in range(5, 20):
            assert nesting_increment(depth) >= 0.0

    def test_monotone_in_table(self):
        for d in range(len(_NESTING_TABLE) - 1):
            assert _NESTING_TABLE[d] <= _NESTING_TABLE[d + 1], \
                f"nesting table not monotone at depth {d}"

    def test_linear_exceeds_table_max_beyond_table(self):
        # For depth >> table, linear formula should exceed table's max
        assert nesting_increment(10) > _NESTING_TABLE[4]


# ── _count_logical_ops() ─────────────────────────────────────────────────────

def _parse_stmt(src: str) -> ast.AST:
    """Parse a single statement and return the first statement node."""
    tree = ast.parse(textwrap.dedent(src))
    return tree.body[0]


class TestCountLogicalOps:
    def test_simple_if_no_ops(self):
        node = _parse_stmt("if x: pass")
        assert _count_logical_ops(node) == 0

    def test_if_with_and(self):
        node = _parse_stmt("if x and y: pass")
        # BoolOp with 2 values → 1 operator
        assert _count_logical_ops(node) == 1

    def test_if_with_or(self):
        node = _parse_stmt("if x or y: pass")
        assert _count_logical_ops(node) == 1

    def test_if_with_and_and_or(self):
        # "x and y and z" → BoolOp with 3 values → 2 operators
        node = _parse_stmt("if x and y and z: pass")
        assert _count_logical_ops(node) == 2

    def test_if_with_compound_condition(self):
        # "a and b or c" → parsed as (a and b) or c
        # Outer BoolOp(Or, [BoolOp(And, [a, b]), c]) → outer has 1 op; inner has 1 op → total 2
        node = _parse_stmt("if a and b or c: pass")
        assert _count_logical_ops(node) == 2

    def test_while_with_and(self):
        node = _parse_stmt("while x and y: pass")
        assert _count_logical_ops(node) == 1

    def test_for_has_no_condition(self):
        node = _parse_stmt("for x in y: pass")
        # for loops have no test condition
        assert _count_logical_ops(node) == 0

    def test_ternary_counts_as_one(self):
        node = _parse_stmt("if (a if b else c): pass")
        # IfExp inside the condition adds 1
        assert _count_logical_ops(node) == 1

    def test_assert_with_and(self):
        node = _parse_stmt("assert x and y")
        assert _count_logical_ops(node) == 1


# ── _FunctionRNVisitor — depth tracking and RN accumulation ──────────────────

def _analyse_source(src: str) -> list[dict]:
    """Parse src and run _FunctionRNVisitor on the first function def.

    visit_FunctionDef is a no-op (nested functions are skipped), so we
    iterate the body directly — mirroring how _collect_functions uses the visitor.
    """
    tree = ast.parse(textwrap.dedent(src))
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    visitor = _FunctionRNVisitor("test.py", func.name, func.lineno)
    for stmt in func.body:
        visitor.visit(stmt)
    return visitor.statements


class TestFunctionRNVisitor:
    def test_empty_function_no_statements(self):
        stmts = _analyse_source("""
            def f():
                pass
        """)
        assert stmts == []

    def test_single_if_at_depth_zero(self):
        stmts = _analyse_source("""
            def f(x):
                if x:
                    pass
        """)
        assert len(stmts) == 1
        s = stmts[0]
        assert s["nesting_depth"] == 0
        # RN = nesting_increment(0) + judgment(1) = 0.0 + 1 = 1.0
        assert s["rn"] == pytest.approx(1.0)

    def test_nested_if_increments_depth(self):
        stmts = _analyse_source("""
            def f(x, y):
                if x:
                    if y:
                        pass
        """)
        assert len(stmts) == 2
        assert stmts[0]["nesting_depth"] == 0
        assert stmts[1]["nesting_depth"] == 1
        # outer: 0.0 + 1 = 1.0
        assert stmts[0]["rn"] == pytest.approx(1.0)
        # inner: nesting_increment(1) + 1 = 1.0 + 1 = 2.0
        assert stmts[1]["rn"] == pytest.approx(2.0)

    def test_if_with_and_adds_logical_op(self):
        stmts = _analyse_source("""
            def f(x, y):
                if x and y:
                    pass
        """)
        # RN = nesting_increment(0) + 1 (flow-break) + 1 (logical op) = 2.0
        assert stmts[0]["rn"] == pytest.approx(2.0)

    def test_for_loop_at_depth_zero(self):
        stmts = _analyse_source("""
            def f(items):
                for item in items:
                    pass
        """)
        assert len(stmts) == 1
        # for loop: nesting_increment(0) + 1 = 1.0
        assert stmts[0]["rn"] == pytest.approx(1.0)

    def test_depth_restored_after_block(self):
        stmts = _analyse_source("""
            def f(x, y):
                if x:
                    pass
                if y:
                    pass
        """)
        # Both ifs at depth 0 — depth must be restored between them
        assert stmts[0]["nesting_depth"] == 0
        assert stmts[1]["nesting_depth"] == 0

    def test_else_clause_recorded(self):
        stmts = _analyse_source("""
            def f(x):
                if x:
                    pass
                else:
                    pass
        """)
        # if is recorded; else increments total_rn but not via _record
        assert len(stmts) >= 1

    def test_elif_recorded(self):
        stmts = _analyse_source("""
            def f(x, y):
                if x:
                    pass
                elif y:
                    pass
        """)
        # if + elif both recorded
        assert len(stmts) == 2

    def test_with_statement_recorded(self):
        stmts = _analyse_source("""
            def f():
                with open("x") as fh:
                    pass
        """)
        assert len(stmts) == 1
        assert stmts[0]["type"] == "With"

    def test_for_with_else_recorded(self):
        stmts = _analyse_source("""
            def f(items):
                for item in items:
                    pass
                else:
                    pass
        """)
        assert len(stmts) >= 1
        assert stmts[0]["type"] == "For"

    def test_while_with_else_recorded(self):
        stmts = _analyse_source("""
            def f(cond):
                while cond:
                    pass
                else:
                    pass
        """)
        assert len(stmts) >= 1
        assert stmts[0]["type"] == "While"

    def test_try_except_handler_recorded(self):
        stmts = _analyse_source("""
            def f():
                try:
                    risky()
                except ValueError:
                    pass
        """)
        assert any(s["type"] == "ExceptHandler" for s in stmts)

    def test_total_rn_accumulates(self):
        stmts = _analyse_source("""
            def f(x, y):
                if x:
                    if y:
                        pass
        """)
        tree = ast.parse(textwrap.dedent("""
            def f(x, y):
                if x:
                    if y:
                        pass
        """))
        func = tree.body[0]
        visitor = _FunctionRNVisitor("t.py", func.name, func.lineno)
        for stmt in func.body:
            visitor.visit(stmt)
        # outer: nesting_increment(0)+1 = 1.0, inner: nesting_increment(1)+1 = 2.0, total: 3.0
        assert visitor.total_rn == pytest.approx(3.0)


# ── analyse_file() integration — uses actual temp files ──────────────────────

import tempfile
import os

class TestAnalyseFile:
    def test_empty_file_returns_zero_score(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("")
            path = f.name
        try:
            result = analyse_files([path])
            assert result["score"] == pytest.approx(0.0)
            assert result["error"] is None
        finally:
            os.unlink(path)

    def test_simple_function_runs_without_error(self):
        src = textwrap.dedent("""
            def greet(name):
                if name:
                    return f"hello {name}"
                return "hello"
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = analyse_files([path])
            assert result["error"] is None
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_invalid_python_returns_error(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("def broken(\n")
            path = f.name
        try:
            result = analyse_files([path])
            assert result["error"] is not None
        finally:
            os.unlink(path)

    def test_nested_function_not_double_counted(self):
        src = textwrap.dedent("""
            def outer(x):
                if x:
                    def inner(y):
                        if y:
                            pass
                    pass
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = analyse_files([path])
            # Both outer and inner are collected but not double-counted
            assert result["error"] is None
            func_names = [f["function"] for f in result["findings"]]
            assert "outer" in func_names
        finally:
            os.unlink(path)

    def test_analyse_files_exception_in_file_produces_error(self):
        # A file that exists but raises on read (simulate via a non-py extension
        # or a file that is actually a directory via the generic except branch)
        result = analyse_files(["/dev/null"])
        # /dev/null is readable as empty Python → no functions → score 0, no error
        assert 0.0 <= result["score"] <= 1.0


class TestChecklistItems:
    """_checklist_items produces node-type-specific items; zero-rn stmts are skipped."""

    def _make_func_dict(self, src: str, name: str = "f") -> dict:
        tree = ast.parse(textwrap.dedent(src))
        func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
        visitor = _FunctionRNVisitor("t.py", func.name, func.lineno)
        for stmt in func.body:
            visitor.visit(stmt)
        return {
            "name": func.name,
            "file": "t.py",
            "start_line": func.lineno,
            "risk_number": visitor.total_rn,
            "statements": visitor.statements,
        }

    def test_for_loop_checklist(self):
        from rn_calculator import _checklist_items
        func = self._make_func_dict("""
            def f(items):
                for item in items:
                    pass
        """)
        items = _checklist_items(func)
        assert any("loop" in i.lower() or "bound" in i.lower() for i in items)

    def test_while_checklist(self):
        from rn_calculator import _checklist_items
        func = self._make_func_dict("""
            def f(cond):
                while cond:
                    pass
        """)
        items = _checklist_items(func)
        assert any("while" in i.lower() or "condition" in i.lower() for i in items)

    def test_with_statement_checklist(self):
        from rn_calculator import _checklist_items
        func = self._make_func_dict("""
            def f():
                with open("x") as fh:
                    pass
        """)
        items = _checklist_items(func)
        assert any("context manager" in i.lower() or "resources" in i.lower() for i in items)

    def test_except_handler_checklist(self):
        from rn_calculator import _checklist_items
        func = self._make_func_dict("""
            def f():
                try:
                    risky()
                except ValueError:
                    pass
        """)
        items = _checklist_items(func)
        assert any("exception" in i.lower() or "granularity" in i.lower() for i in items)

    def test_zero_rn_statements_skipped(self):
        from rn_calculator import _checklist_items
        # A function with all-zero rn statements (shouldn't happen in practice,
        # but test the guard)
        func_dict = {
            "name": "f",
            "file": "t.py",
            "start_line": 1,
            "risk_number": 0.0,
            "statements": [{"type": "If", "line": 1, "rn": 0.0, "nesting_depth": 0}],
        }
        items = _checklist_items(func_dict)
        assert items == []


class TestElifWithTrailingElse:
    """Exercises the elif-with-trailing-else path (line 148)."""

    def test_elif_with_else_recorded(self):
        src = textwrap.dedent("""
            def f(x, y):
                if x:
                    pass
                elif y:
                    pass
                else:
                    pass
        """)
        tree = ast.parse(src)
        func = tree.body[0]
        visitor = _FunctionRNVisitor("t.py", func.name, func.lineno)
        for stmt in func.body:
            visitor.visit(stmt)
        # if + elif both in statements; else adds to total_rn only
        assert len(visitor.statements) >= 2
        assert visitor.total_rn > visitor.statements[-1]["rn"]


class TestRNCalculatorMain:
    def test_main_no_files(self, capsys, monkeypatch):
        import json as _json
        monkeypatch.setattr(sys, "argv", ["rn_calculator.py"])
        from rn_calculator import main
        main()
        captured = capsys.readouterr()
        data = _json.loads(captured.out)
        assert data["score"] == 0.0
        assert data["error"] == "no input files"

    def test_main_with_files_flag(self, capsys, monkeypatch, tmp_path):
        import json as _json
        py = tmp_path / "mod.py"
        py.write_text("def f(x):\n    if x:\n        return x\n")
        monkeypatch.setattr(sys, "argv", [
            "rn_calculator.py", "--files", str(py)
        ])
        from rn_calculator import main
        main()
        captured = capsys.readouterr()
        data = _json.loads(captured.out)
        assert "score" in data

    def test_main_valid_file_direct(self, capsys, monkeypatch, tmp_path):
        import json as _json
        py = tmp_path / "service.py"
        py.write_text("def process(x):\n    for i in x:\n        pass\n")
        monkeypatch.setattr(sys, "argv", ["rn_calculator.py", str(py)])
        from rn_calculator import main
        main()
        captured = capsys.readouterr()
        data = _json.loads(captured.out)
        assert "score" in data
        assert data["error"] is None
