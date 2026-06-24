"""
Tests for function_metrics.py, portability_check.py, and migration_scorer.py.
All three have pure-Python logic that is well-suited to unit testing.
"""
import ast
import textwrap
import tempfile
import os
import pytest


# ── function_metrics ──────────────────────────────────────────────────────────

from function_metrics import (
    _FuncMetricsVisitor,
    _depth_recursive,
    analyse_files as fm_analyse_files,
)


def _visit_src(src: str) -> list[dict]:
    tree = ast.parse(textwrap.dedent(src))
    v = _FuncMetricsVisitor()
    v.visit(tree)
    return v.functions


class TestFuncMetricsVisitor:
    def test_empty_module(self):
        assert _visit_src("x = 1") == []

    def test_simple_function_detected(self):
        funcs = _visit_src("""
            def greet(name):
                return f"hello {name}"
        """)
        assert len(funcs) == 1
        assert funcs[0]["name"] == "greet"

    def test_param_count(self):
        funcs = _visit_src("""
            def f(a, b, c):
                pass
        """)
        assert funcs[0]["params"] == 3

    def test_self_excluded_from_param_count(self):
        funcs = _visit_src("""
            class C:
                def method(self, x, y):
                    pass
        """)
        m = next(f for f in funcs if f["name"] == "method")
        assert m["params"] == 2  # self excluded

    def test_cls_excluded_from_param_count(self):
        funcs = _visit_src("""
            class C:
                @classmethod
                def factory(cls, x):
                    return cls()
        """)
        m = next(f for f in funcs if f["name"] == "factory")
        assert m["params"] == 1

    def test_vararg_and_kwarg_count(self):
        funcs = _visit_src("""
            def f(*args, **kwargs):
                pass
        """)
        assert funcs[0]["params"] == 2

    def test_return_paths_counted(self):
        funcs = _visit_src("""
            def f(x):
                if x > 0:
                    return x
                return -x
        """)
        assert funcs[0]["return_paths"] == 2

    def test_raise_counts_as_return_path(self):
        funcs = _visit_src("""
            def f(x):
                if x < 0:
                    raise ValueError("negative")
                return x
        """)
        assert funcs[0]["return_paths"] == 2

    def test_line_count_approximate(self):
        funcs = _visit_src("""
            def f():
                x = 1
                y = 2
                return x + y
        """)
        assert funcs[0]["lines"] >= 4

    def test_multiple_functions(self):
        funcs = _visit_src("""
            def a(): pass
            def b(): pass
            def c(): pass
        """)
        assert len(funcs) == 3
        names = {f["name"] for f in funcs}
        assert names == {"a", "b", "c"}


class TestDepthRecursive:
    def _stmts(self, src: str) -> list:
        return ast.parse(textwrap.dedent(src)).body

    def test_flat_code_depth_zero(self):
        stmts = self._stmts("x = 1\ny = 2")
        assert _depth_recursive(stmts, 0) == 0

    def test_single_if_depth_one(self):
        stmts = self._stmts("if x:\n    pass")
        assert _depth_recursive(stmts, 0) >= 1

    def test_nested_if_depth_two(self):
        stmts = self._stmts("if x:\n    if y:\n        pass")
        assert _depth_recursive(stmts, 0) >= 2

    def test_for_loop_depth(self):
        stmts = self._stmts("for i in range(10):\n    pass")
        assert _depth_recursive(stmts, 0) >= 1

    def test_try_except_depth(self):
        stmts = self._stmts("try:\n    pass\nexcept Exception:\n    pass")
        assert _depth_recursive(stmts, 0) >= 1

    def test_if_else_depth(self):
        src = textwrap.dedent("""
            if x:
                pass
            else:
                if y:
                    pass
        """)
        stmts = self._stmts(src)
        assert _depth_recursive(stmts, 0) >= 2

    def test_while_loop_depth(self):
        stmts = self._stmts("while True:\n    if x:\n        pass")
        assert _depth_recursive(stmts, 0) >= 2


class TestFunctionMetricsAnalyse:
    def test_analyse_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("")
            path = f.name
        try:
            result = fm_analyse_files([path])
            assert result["error"] is None
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_analyse_simple_function(self):
        src = textwrap.dedent("""
            def greet(name, greeting="hello"):
                if name:
                    return f"{greeting} {name}"
                return greeting
        """)
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = fm_analyse_files([path])
            assert result["error"] is None
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_analyse_no_files(self):
        result = fm_analyse_files([])
        assert result["score"] == pytest.approx(0.0)

    def test_long_function_raises_score(self):
        # A function with many lines should produce a non-zero score
        lines = ["    x = 1"] * 60  # 60-line function body
        src = "def big_fn(" + ", ".join(f"a{i}" for i in range(10)) + "):\n"
        src += "\n".join(lines) + "\n    return x\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = fm_analyse_files([path])
            assert result["score"] > 0.0
            # Long function + many params should produce checklist items
            assert result["error"] is None
        finally:
            os.unlink(path)

    def test_too_many_params_flagged(self):
        params = ", ".join(f"p{i}" for i in range(12))
        src = f"def bloated({params}):\n    pass\n"
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        try:
            result = fm_analyse_files([path])
            assert result["score"] > 0.0
        finally:
            os.unlink(path)


# ── portability_check ─────────────────────────────────────────────────────────

from portability_check import _scan_file, main as pc_main


class TestPortabilityCheck:
    def _write(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
        f.write(textwrap.dedent(content))
        f.close()
        return f.name

    def test_clean_file_no_findings(self):
        path = self._write("x = 1\nprint(x)\n")
        try:
            assert _scan_file(path) == []
        finally:
            os.unlink(path)

    def test_hardcoded_home_path_flagged(self):
        path = self._write('CONFIG = "/Users/alice/config.json"\n')
        try:
            findings = _scan_file(path)
            assert len(findings) >= 1
            assert findings[0]["severity"] == "high"
        finally:
            os.unlink(path)

    def test_linux_home_path_flagged(self):
        path = self._write('LOG = "/home/bob/app.log"\n')
        try:
            findings = _scan_file(path)
            assert len(findings) >= 1
        finally:
            os.unlink(path)

    def test_score_zero_for_clean(self):
        path = self._write("x = 1\n")
        try:
            result = pc_main([path])
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_score_elevated_for_finding(self):
        path = self._write('CONFIG = "/Users/alice/settings.py"\n')
        try:
            result = pc_main([path])
            assert result["score"] >= 0.55  # one finding → 0.55 floor
        finally:
            os.unlink(path)

    def test_multiple_findings_increase_score(self):
        path = self._write(
            'A = "/Users/alice/a.py"\n'
            'B = "/Users/alice/b.py"\n'
            'C = "/home/bob/c.py"\n'
        )
        try:
            result = pc_main([path])
            # 3 findings: 0.55 + 2*0.15 = 0.85
            assert result["score"] == pytest.approx(0.85)
        finally:
            os.unlink(path)

    def test_score_capped_at_one(self):
        lines = "\n".join(f'P{i} = "/Users/alice/p{i}.py"' for i in range(10))
        path = self._write(lines + "\n")
        try:
            result = pc_main([path])
            assert result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_empty_file_list(self):
        result = pc_main([])
        assert result["score"] == pytest.approx(0.0)


# ── migration_scorer ──────────────────────────────────────────────────────────

from migration_scorer import (
    _MigrationVisitor,
    _check_add_field_nullable,
    analyse_files as ms_analyse_files,
)


class TestMigrationVisitor:
    def test_empty_file_no_ops(self):
        tree = ast.parse("x = 1")
        v = _MigrationVisitor()
        v.visit(tree)
        assert v.operations == []

    def test_add_field_detected(self):
        src = textwrap.dedent("""
            operations = [
                migrations.AddField(model_name='user', name='bio', field=models.TextField()),
            ]
        """)
        tree = ast.parse(src)
        v = _MigrationVisitor()
        v.visit(tree)
        assert any(op == "AddField" for op, _ in v.operations)

    def test_remove_field_detected(self):
        src = "operations = [migrations.RemoveField(model_name='x', name='y')]"
        tree = ast.parse(src)
        v = _MigrationVisitor()
        v.visit(tree)
        assert any(op == "RemoveField" for op, _ in v.operations)

    def test_run_python_detected(self):
        src = "ops = [migrations.RunPython(forwards, backwards)]"
        tree = ast.parse(src)
        v = _MigrationVisitor()
        v.visit(tree)
        assert any(op == "RunPython" for op, _ in v.operations)


class TestCheckAddFieldNullable:
    def test_with_null_true_not_risky(self):
        src = "migrations.AddField(name='x', field=models.CharField(null=True))"
        assert _check_add_field_nullable(src, 1) is False

    def test_with_default_not_risky(self):
        src = "migrations.AddField(name='x', field=models.CharField(default=''))"
        assert _check_add_field_nullable(src, 1) is False

    def test_without_null_or_default_risky(self):
        src = "migrations.AddField(name='x', field=models.CharField(max_length=100))"
        assert _check_add_field_nullable(src, 1) is True


class TestMigrationScorerAnalyse:
    def test_non_migration_files_zero_score(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("x = 1\n")
            path = f.name
        try:
            result = ms_analyse_files([path])
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_empty_file_list(self):
        result = ms_analyse_files([])
        assert result["score"] == pytest.approx(0.0)

    def test_migration_file_with_remove_field_is_risky(self):
        src = textwrap.dedent("""
            from django.db import migrations
            class Migration(migrations.Migration):
                operations = [
                    migrations.RemoveField(model_name='user', name='bio'),
                ]
        """)
        with tempfile.NamedTemporaryFile(
            suffix=".py", prefix="0001_migration_", mode="w", delete=False
        ) as f:
            f.write(src)
            path = f.name
        try:
            result = ms_analyse_files([path])
            assert result["score"] > 0.0
        finally:
            os.unlink(path)

    def test_migration_file_with_add_field_no_default_is_high_risk(self):
        src = textwrap.dedent("""
            from django.db import migrations, models
            class Migration(migrations.Migration):
                operations = [
                    migrations.AddField(
                        model_name='user',
                        name='phone',
                        field=models.CharField(max_length=20),
                    ),
                ]
        """)
        with tempfile.NamedTemporaryFile(
            suffix=".py", prefix="0002_migration_", mode="w", delete=False
        ) as f:
            f.write(src)
            path = f.name
        try:
            result = ms_analyse_files([path])
            # AddField without null=True or default → HIGH risk → elevated score
            assert result["score"] > 0.0
            assert result["error"] is None
        finally:
            os.unlink(path)

    def test_multiple_critical_ops_trigger_checklist(self):
        src = textwrap.dedent("""
            from django.db import migrations, models
            class Migration(migrations.Migration):
                operations = [
                    migrations.RunSQL('DROP TABLE users'),
                    migrations.RemoveField(model_name='user', name='email'),
                ]
        """)
        with tempfile.NamedTemporaryFile(
            suffix=".py", prefix="0003_migration_", mode="w", delete=False
        ) as f:
            f.write(src)
            path = f.name
        try:
            result = ms_analyse_files([path])
            assert result["score"] > 0.0
            # High risk operations should populate checklist
            assert len(result["checklist_items"]) > 0
        finally:
            os.unlink(path)
