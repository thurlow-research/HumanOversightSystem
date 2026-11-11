"""Pure-logic tests for the new-code gate (#2304, TD section 9).

The gate modules are imported canonically and at module level: a first import
inside a test would record the module's top-level statements under that test's
coverage context and drag the test into every selection (TD 5.19).
"""

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from scripts.framework import new_code_gate_logic as ncg
from scripts.oversight.validators.shell_logic_check import decision_lines, is_hard_exempt

REPO = Path(__file__).resolve().parents[2]
LOGIC_FILE = REPO / "scripts" / "framework" / "new_code_gate_logic.py"


def _src(text: str) -> str:
    return textwrap.dedent(text).lstrip("\n")


def _findings(source: str, lines=None):
    gated = ncg.statement_map(source)[0] if lines is None else lines
    return ncg.decision_logic_findings(source, gated)


def _codes(source: str, lines=None, path: str = "m.py") -> list[str]:
    return [r["code"] for r in ncg.decision_fail_reasons(path, _findings(source, lines))]


def _message(source: str, code: str, path: str = "m.py") -> str:
    reasons = ncg.decision_fail_reasons(path, _findings(source))
    return next(r["message"] for r in reasons if r["code"] == code)


# --------------------------------------------------------------------------
# Small helpers, thresholds, coverage
# --------------------------------------------------------------------------


def test_new_file_coverage_boundary_79_fails_80_passes():
    assert not ncg.meets_threshold(79, 100, 80)
    assert ncg.meets_threshold(80, 100, 80)
    low = ncg.blank_file_record("a.py", "new")
    low.update(ncg.coverage_fields(100, 79))
    assert [r["code"] for r in ncg.threshold_reasons(low, ncg.THRESHOLDS)] == [
        "coverage_below_threshold"
    ]
    ok = ncg.blank_file_record("a.py", "new")
    ok.update(ncg.coverage_fields(100, 80))
    assert ncg.threshold_reasons(ok, ncg.THRESHOLDS) == []


def test_failing_percentage_is_rounded_down_never_displayed_as_threshold():
    assert ncg.percent_floor(7996, 10000) == 79.9
    assert ncg.percent_floor(2, 3) == 66.6
    assert ncg.coverage_fields(0, 0)["coverage_pct"] is None


def test_new_file_mutant_score_boundary_74_fails_75_passes():
    rec = ncg.blank_file_record("a.py", "new")
    rec.update(mutation_ran=True, mutants_total=100, mutants_killed=74)
    codes = [r["code"] for r in ncg.threshold_reasons(rec, ncg.THRESHOLDS)]
    assert codes == ["mutant_score_below_threshold"]
    rec["mutants_killed"] = 75
    assert ncg.threshold_reasons(rec, ncg.THRESHOLDS) == []


def test_no_score_requirement_without_a_mutation_run_or_mutants():
    rec = ncg.blank_file_record("a.py", "new")
    rec.update(mutation_ran=False, mutants_total=10, mutants_killed=0)
    assert ncg.threshold_reasons(rec, ncg.THRESHOLDS) == []
    rec.update(mutation_ran=True, mutants_total=0)
    assert ncg.threshold_reasons(rec, ncg.THRESHOLDS) == []


def test_bound_text_and_format_lines_caps():
    assert ncg.bound_text("abc", 10) == "abc"
    cut = ncg.bound_text("x" * 50, 20)
    assert len(cut) == 20 and cut.endswith(ncg.TRUNCATION_SUFFIX)
    assert ncg.format_lines([3, 1, 3, 2]) == "1,2,3"
    many = ncg.format_lines(range(1, 53))
    assert many.endswith("…and 2 more") and many.count(",") == 49


def test_canonical_name_and_module_stem():
    assert ncg.canonical_name("scripts/framework/new_code_gate.py") == (
        "scripts.framework.new_code_gate"
    )
    assert ncg.canonical_name("scripts/automation/lib/__init__.py") == "scripts.automation.lib"
    assert ncg.module_stem("scripts/automation/lib/__init__.py") == "lib"
    assert ncg.module_stem("bootstrap/lib/hos_tmp_root.py") == "hos_tmp_root"


# --------------------------------------------------------------------------
# Version and sidecar guards
# --------------------------------------------------------------------------


def test_check_pins_names_the_first_mismatch():
    assert ncg.check_pins(dict(ncg.PINNED)) is None
    bad = dict(ncg.PINNED, libcst="1.0.0")
    assert ncg.check_pins(bad) == "tool version mismatch: libcst 1.0.0 != 1.9.0"
    missing = {k: v for k, v in ncg.PINNED.items() if k != "pytest"}
    assert ncg.check_pins(missing) == "tool version mismatch: pytest None != 9.2.0"


@pytest.mark.parametrize("tool", sorted(ncg.PINNED))
def test_sidecar_tool_versions_must_equal_install(tool):
    meta = {"tool_versions": dict(ncg.PINNED), "python": "3.12"}
    assert ncg.check_sidecar_environment(meta, dict(ncg.PINNED), "3.12") is None
    meta["tool_versions"][tool] = "0.0.1"
    msg = ncg.check_sidecar_environment(meta, dict(ncg.PINNED), "3.12")
    assert msg.startswith("sidecar tool versions differ from measure environment: " + tool)


def test_sidecar_python_must_equal_install():
    meta = {"tool_versions": dict(ncg.PINNED), "python": "3.11"}
    msg = ncg.check_sidecar_environment(meta, dict(ncg.PINNED), "3.12")
    assert msg == "sidecar tool versions differ from measure environment: python 3.11 != 3.12"


def test_sidecar_head_clean_and_core_checked():
    meta = {"head_sha": "abc", "clean": True, "coverage_core": "ctrace"}
    assert ncg.check_sidecar_head(meta, "abc") is None
    prefix = "coverage data stale or from a dirty tree: "
    for key, value, expected in (
        ("head_sha", "zzz", "head: sidecar describes zzz, gated commit is abc"),
        ("clean", False, "clean: tracked .py/.sh files were modified (no paths recorded)"),
        ("coverage_core", "sysmon", "core: coverage_core is sysmon, not ctrace"),
    ):
        broken = dict(meta, **{key: value})
        assert ncg.check_sidecar_head(broken, "abc") == prefix + expected


def test_sidecar_head_names_every_failed_condition_and_the_dirty_paths():
    paths = [f"scripts/p{i}.py" for i in range(30)] + ["x" * 3000]
    meta = {"head_sha": "zzz", "clean": False, "coverage_core": None, "dirty_paths": paths}
    message = ncg.check_sidecar_head(meta, "abc")
    parts = message.split(": ", 1)[1].split("; ")
    assert [p.split(":")[0] for p in parts] == ["head", "clean", "core"]
    assert "scripts/p0.py, scripts/p1.py" in parts[1] and "scripts/p19.py" in parts[1]
    assert "scripts/p20.py" not in parts[1]
    clean_only = {"head_sha": "abc", "clean": False, "coverage_core": "ctrace", "dirty_paths": "x"}
    assert ncg.check_sidecar_head(clean_only, "abc").endswith("(no paths recorded)")
    long_head = dict(meta, head_sha="h" * 5000, coverage_core="c" * 5000)
    assert len(ncg.check_sidecar_head(long_head, "abc")) < 4000


def test_merge_commit_must_have_two_parents_second_is_pr_head():
    assert ncg.check_merge_parents(["base", "head"], "head") is None
    expected = "merge commit does not contain the PR head"
    assert ncg.check_merge_parents(["base", "other"], "head") == expected
    assert ncg.check_merge_parents(["base"], "head") == expected
    assert ncg.check_merge_parents(["a", "b", "c"], "b") == expected


# --------------------------------------------------------------------------
# Diff parsing and scope
# --------------------------------------------------------------------------


def test_classify_status():
    assert ncg.classify_status("A") == "new"
    assert ncg.classify_status("C100") == "new"
    assert ncg.classify_status("M") == "changed"
    assert ncg.classify_status("T") == "changed"
    assert ncg.classify_status("R100") is None
    assert ncg.classify_status("R087") == "changed"
    assert ncg.classify_status("D") is None


def test_parse_name_status_handles_renames_and_quoted_paths():
    text = "A\tnew.py\nM\tx/y.py\nR090\told.py\tnew2.py\nD\tgone.py\n"
    text += 'M\t"caf\\303\\251.py"\n'
    got = ncg.parse_name_status(text)
    assert [(c.status, c.path, c.old_path, c.kind) for c in got] == [
        ("A", "new.py", None, "new"),
        ("M", "x/y.py", None, "changed"),
        ("R090", "new2.py", "old.py", "changed"),
        ("D", "gone.py", None, None),
        ("M", "café.py", None, "changed"),
    ]


@pytest.mark.parametrize(
    "status,old,new,kind",
    [
        ("R100", "tests/test_x.py", "scripts/x.py", "new"),
        ("R087", "tests/test_x.py", "scripts/x.py", "new"),
        ("R100", "docs/x.txt", "scripts/x.sh", "new"),
        ("R100", "scripts/x.sh", "scripts/x.py", "new"),
        ("R100", "scripts/a.py", "scripts/b.py", None),
        ("R100", "scripts/a.sh", "scripts/b.sh", None),
        ("R090", "scripts/a.py", "scripts/b.py", "changed"),
        ("R100", "scripts/a.py", "tests/test_a.py", "new"),
        ("M", None, "scripts/a.py", "changed"),
    ],
)
def test_classify_change_treats_a_cross_scope_rename_as_new(status, old, new, kind):
    assert ncg.classify_change(status, old, new) == kind


def test_parse_name_status_marks_cross_scope_renames_new():
    got = ncg.parse_name_status("R100\ttests/test_x.py\tscripts/x.py\nR100\ta/b.py\ta/c.py\n")
    assert [(c.path, c.old_path, c.kind) for c in got] == [
        ("scripts/x.py", "tests/test_x.py", "new"),
        ("a/c.py", "a/b.py", None),
    ]


def test_parse_name_status_splits_on_newline_only():
    got = ncg.parse_name_status("M\ta\x0cb.py\nM\tc d.py\n")
    assert [c.path for c in got] == ["a\x0cb.py", "c d.py"]


def test_unquote_git_path_escapes():
    assert ncg.unquote_git_path("plain.py") == "plain.py"
    assert ncg.unquote_git_path('"a\\tb\\"c\\\\d.py"') == 'a\tb"c\\d.py'


def test_parse_hunks_collects_head_side_lines_and_counts_hunks():
    diff = _src(
        """
        diff --git a/a.py b/a.py
        --- a/a.py
        +++ b/a.py
        @@ -3,2 +3,3 @@ def f():
        -x
        -y
        +x1
        +y1
        +z1
        @@ -10 +12 @@
        -q
        +q1
        @@ -20,2 +22,0 @@
        -gone
        -gone2
        """
    )
    assert ncg.parse_hunks(diff) == ([3, 4, 5, 12], 3)
    assert ncg.parse_hunks("") == ([], 0)


def test_parse_hunks_ignores_forged_file_headers_and_content_lines():
    """F1: a content line `++ b/other.py` shows up as `+++ b/other.py` and must not retarget lines."""
    diff = _src(
        """
        diff --git a/a.py b/a.py
        --- a/a.py
        +++ b/a.py
        @@ -1 +1,2 @@
        -x
        +++ b/victim.py
        +@@ -1 +40,9 @@
        @@ -9 +10 @@
        -y
        +z
        """
    )
    assert ncg.parse_hunks(diff) == ([1, 2, 10], 2)


def test_parse_hunks_splits_on_newline_only():
    """A form feed or U+2028 inside a content line must not start a fake `@@` line."""
    diff = "@@ -1 +1 @@\n+a\x0c@@ -5 +99 @@\n+b @@ -7 +77 @@\n"
    assert ncg.parse_hunks(diff) == ([1], 1)


def test_check_diff_complete_fails_closed_on_changed_content_without_hunks():
    ncg.check_diff_complete("a.py", "b1", "b1", 0)
    ncg.check_diff_complete("a.py", "b1", "b2", 1)
    with pytest.raises(ncg.GateError, match="a.py changed content but produced no hunks"):
        ncg.check_diff_complete("a.py", "b1", "b2", 0)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("scripts/oversight/x.py", True),
        ("bin/tool.py", True),
        ("tests/test_x.py", False),
        ("scripts/conftest.py", False),
        ("mutants/x.py", False),
        ("scripts/venv/lib/x.py", True),
        ("scripts/.venv/x.py", True),
        ("a/site-packages/x.py", True),
        ("scripts/x.sh", False),
    ],
)
def test_in_python_scope(path, expected):
    assert ncg.in_python_scope(path) is expected


def test_shell_scope_and_measured_surface():
    assert ncg.in_shell_scope("scripts/framework/run_tests.sh")
    assert not ncg.in_shell_scope("bin/hos-cron")
    assert ncg.in_measured_surface("bootstrap/x.py", ncg.MEASURED_SOURCES)
    assert ncg.in_measured_surface("scripts/automation/lib/x.py", ncg.MEASURED_SOURCES)
    assert not ncg.in_measured_surface("newdir/x.py", ncg.MEASURED_SOURCES)


def test_continuation_line_edit_is_gated():
    source = _src(
        """
        import os
        x = foo(
            1,
            2,
        )
        # a comment

        @deco
        def f():
            return 1
        """
    )
    statements, multiline = ncg.statement_map(source)
    assert ncg.gated_statement_lines([3], statements, multiline, False) == [2]
    assert ncg.gated_statement_lines([6, 7], statements, multiline, False) == []
    assert ncg.gated_statement_lines([8], statements, multiline, False) == [8]
    assert ncg.gated_statement_lines([], statements, multiline, True) == sorted(statements)


def test_pragma_no_cover_on_gated_line_still_counted():
    source = "x = 1  # pragma: no cover\nif x:  # pragma: no cover\n    y = 2\n"
    statements, _ = ncg.statement_map(source)
    assert statements == {1, 2, 3}


# --------------------------------------------------------------------------
# Decision logic: R-DL
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "if a:\n    pass\n",
        "for x in y:\n    pass\n",
        "async def f(y):\n    async for x in y:\n        pass\n",
        "while a:\n    pass\n",
        "try:\n    a()\nexcept E:\n    pass\n",
        "try:\n    a()\nexcept* E:\n    pass\n",
        "match a:\n    case 1:\n        pass\n",
        "x = a or b\n",
        "x = a < b\n",
        "x = 1 if a else 2\n",
        "x = [i for i in y if i]\n",
        "x = {i for i in y if i}\n",
        "x = {i: 1 for i in y if i}\n",
        "x = (i for i in y if i)\n",
    ],
)
def test_has_decision_logic_each_node_type(source):
    gated = ncg.statement_map(source)[0]
    assert ncg.has_decision_logic(source, gated)


@pytest.mark.parametrize(
    "source",
    [
        "x = [i for i in y]\n",
        "x = 1\n",
        "import os\n",
        "x = f(1, 2)\nassert x\nwith a:\n    pass\n",
    ],
)
def test_no_decision_node_without_ifs_asserts_or_with(source):
    gated = ncg.statement_map(source)[0]
    assert not ncg.has_decision_logic(source, gated)


# --------------------------------------------------------------------------
# Q5-MOD
# --------------------------------------------------------------------------

MODULE_CASES = [
    ("if x:\n    y = 1\n", "1", "If"),
    ("for i in x:\n    pass\n", "1", "For"),
    ("while x:\n    pass\n", "1", "While"),
    ("try:\n    import a\n    b()\nexcept E:\n    pass\n", "1", "Try"),
    ("try:\n    x()\nexcept* E:\n    pass\n", "1", "TryStar"),
    ("match x:\n    case 1:\n        pass\n", "1", "Match"),
    ("X = a or b\n", "1", "BoolOp"),
    ("X = a == b\n", "1", "Compare"),
    ("X = a if c else b\n", "1", "IfExp"),
    ("X = [i for i in y if i]\n", "1", "ListComp"),
    ("X = {i for i in y if i}\n", "1", "SetComp"),
    ("X = {i: 1 for i in y if i}\n", "1", "DictComp"),
    ("X = (i for i in y if i)\n", "1", "GeneratorExp"),
    ("f = lambda: (1 if a else 2)\n", "1", "IfExp"),
    ("with a:\n    if b:\n        pass\n", "2", "If"),
]


@pytest.mark.parametrize("source,lines,construct", MODULE_CASES)
def test_module_level_decision_logic_fails_move_into_function(source, lines, construct):
    findings = _findings(source)
    assert any(f["construct"] == construct and f["region"] == "module" for f in findings)
    expected = (
        f"module-level decision logic at m.py:{lines} — "
        "move the logic into a function so it can be mutated"
    )
    assert _message(source, "module_level_decision_logic") == expected
    assert "unmutatable_decision_logic" not in _codes(source)


def test_module_level_logic_on_ungated_line_is_not_a_finding():
    source = "A = 1\nB = x or y\n"
    assert _findings(source, [1]) == []
    assert _codes(source, [1]) == []
    assert _codes(source, [2]) == ["module_level_decision_logic"]


def test_finding_fields_are_complete_and_sorted():
    source = "X = a if b else (c or d)\n"
    findings = _findings(source)
    assert [f["construct"] for f in findings] == ["BoolOp", "IfExp"]
    for finding in findings:
        assert set(finding) == {
            "line",
            "node_line",
            "construct",
            "region",
            "unmutatable_reason",
            "carve_out",
        }
        assert finding["line"] == 1 and finding["region"] == "module"
    keys = [(f["line"], f["node_line"], f["construct"]) for f in findings]
    assert keys == sorted(keys)


# --------------------------------------------------------------------------
# Q5-CLS
# --------------------------------------------------------------------------

CLASS_CASES = [
    ("class A:\n    x = 1 if c else 2\n", "2"),
    ("class A:\n    if c:\n        x = 1\n", "2"),
    ("class E(Enum):\n    A = 1 == 1\n", "2"),
    ("class A: x = a or b\n", "1"),
    ("class A:\n    class B:\n        y = c or d\n", "3"),
    ("class A:\n    def m(self, x=a == b):\n        return x\n", "2"),
    ("class A:\n    @deco(1 if c else 2)\n    def m(self):\n        return 1\n", "2"),
]


@pytest.mark.parametrize("source,lines", CLASS_CASES)
def test_class_level_decision_logic_fails(source, lines):
    expected = (
        f"class-level decision logic at m.py:{lines} — "
        "move the logic into a function so it can be mutated"
    )
    assert _message(source, "class_level_decision_logic") == expected
    assert "unmutatable_decision_logic" not in _codes(source)


def test_enum_and_single_line_class_bodies_are_listed_with_region_class():
    enum = "class E(Enum):\n    A = 1 == 1\n"
    got = ncg.unmutatable_gated_lines(enum, ncg.statement_map(enum)[0])
    assert got == [
        {"line": 2, "reason": "enum_body", "region": "class", "has_decision_logic": True}
    ]
    single = "class A: x = a or b\n"
    got = ncg.unmutatable_gated_lines(single, ncg.statement_map(single)[0])
    assert got == [
        {"line": 1, "reason": "single_line_class", "region": "class", "has_decision_logic": True}
    ]


# --------------------------------------------------------------------------
# Q5-MAIN
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        "sys.exit(main())",
        "main()",
        "sys.exit(_main(sys.argv[1:]))",
        "raise SystemExit(main())",
        "raise SystemExit(_main(sys.argv[1:]))",
    ],
)
def test_main_guard_carve_out_passes_exact_shape(call):
    source = f'if __name__ == "__main__":\n    {call}\n'
    assert _codes(source) == []
    carved = [f for f in _findings(source) if f["carve_out"]]
    assert {f["construct"] for f in carved} == {"If", "Compare"}
    assert {f["carve_out"] for f in carved} == {"main_guard"}


@pytest.mark.parametrize(
    "source",
    [
        'if __name__ == "__main__":\n    a()\n    b()\n',
        'if __name__ == "__main__":\n    main()\nelse:\n    other()\n',
        'if "__main__" == __name__:\n    main()\n',
        'if __name__ != "__main__":\n    main()\n',
        'if a:\n    if __name__ == "__main__":\n        main()\n',
        'class A:\n    if __name__ == "__main__":\n        main()\n',
    ],
)
def test_main_guard_near_misses_fail(source):
    assert any(c.endswith("_level_decision_logic") for c in _codes(source))
    guard_findings = [f for f in _findings(source) if f["carve_out"] == "main_guard"]
    assert guard_findings == []


@pytest.mark.parametrize(
    "body",
    [
        "raise SystemExit()",
        "raise SystemExit(1)",
        "raise SystemExit(code)",
        "raise SystemExit(main(), 1)",
        "raise SystemExit(main(), code=1)",
        "raise SystemExit(main()) from None",
        "raise SystemExit(main()) from err",
        "raise builtins.SystemExit(main())",
        "raise KeyboardInterrupt(main())",
        "raise ValueError(main())",
        "raise SystemExit",
        "raise",
        "raise SystemExit(*main())",
        "raise SystemExit(**main())",
        "raise SystemExit(code=main())",
    ],
)
def test_main_guard_raise_near_misses_fail(body):
    source = f'if __name__ == "__main__":\n    {body}\n'
    assert "module_level_decision_logic" in _codes(source)
    assert [f for f in _findings(source) if f["carve_out"] == "main_guard"] == []


def test_main_guard_body_logic_is_still_judged():
    source = 'if __name__ == "__main__":\n    sys.exit(main() or 1)\n'
    findings = _findings(source)
    assert {f["construct"]: f["carve_out"] for f in findings} == {
        "If": "main_guard",
        "Compare": "main_guard",
        "BoolOp": None,
    }
    assert _message(source, "module_level_decision_logic").endswith(
        "m.py:2 — move the logic into a function so it can be mutated"
    )


# --------------------------------------------------------------------------
# Q5-IMP
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    import x\nexcept ImportError:\n    x = None\n",
        "try:\n    from a import b\nexcept ImportError as e:\n    b = None\n",
        (
            "try:\n    import x\nexcept ImportError:\n    x = None\n"
            "except ImportError as e:\n    x = 2\n"
        ),
    ],
)
def test_import_fallback_carve_out_passes_exact_shape(source):
    assert _codes(source) == []
    assert [f["carve_out"] for f in _findings(source)] == ["import_fallback"]


@pytest.mark.parametrize(
    "source",
    [
        "try:\n    import x\nexcept ModuleNotFoundError:\n    x = None\n",
        "try:\n    import x\nexcept (ImportError, OSError):\n    x = None\n",
        "try:\n    import x\nexcept:\n    x = None\n",
        "try:\n    sys.path.insert(0, p)\n    import x\nexcept ImportError:\n    x = None\n",
        "try:\n    import x\nexcept ImportError:\n    x = None\nelse:\n    y = 1\n",
        "try:\n    import x\nexcept ImportError:\n    x = None\nfinally:\n    y = 1\n",
        "if TYPE_CHECKING:\n    try:\n        import x\n    except ImportError:\n        x = 1\n",
    ],
)
def test_import_fallback_near_misses_fail(source):
    assert "module_level_decision_logic" in _codes(source)


def test_import_fallback_inside_a_function_has_no_q5_reason():
    source = "def f():\n    try:\n        import x\n    except ImportError:\n        x = None\n"
    assert _codes(source) == []


def test_import_fallback_handler_contents_are_still_judged():
    source = "try:\n    import x\nexcept ImportError:\n    if a:\n        x = 1\n"
    assert _message(source, "module_level_decision_logic").endswith(
        "m.py:4 — " + ("move the logic into a function so it can be mutated")
    )
    nested = (
        "try:\n    import x\nexcept ImportError:\n    def fallback():\n"
        "        if a:\n            return 1\n"
    )
    reasons = {f["unmutatable_reason"] for f in _findings(nested) if f["region"] == "function"}
    assert reasons == {"non_top_level_function"}
    assert "unmutatable_decision_logic" in _codes(nested)


# --------------------------------------------------------------------------
# Q5-TC
# --------------------------------------------------------------------------


def test_type_checking_carve_out_passes_exact_shape():
    source = "if TYPE_CHECKING:\n    import x\n"
    assert _codes(source) == []
    assert [f["carve_out"] for f in _findings(source)] == ["type_checking"]


@pytest.mark.parametrize(
    "source",
    [
        "if typing.TYPE_CHECKING:\n    import x\n",
        "if not TYPE_CHECKING:\n    import x\n",
        "if TYPE_CHECKING:\n    import x\nelse:\n    y = 1\n",
    ],
)
def test_type_checking_near_misses_fail(source):
    assert "module_level_decision_logic" in _codes(source)


def test_type_checking_body_logic_still_fails():
    source = "if TYPE_CHECKING:\n    X = a if b else c\n"
    findings = _findings(source)
    assert {f["construct"]: f["carve_out"] for f in findings} == {
        "If": "type_checking",
        "IfExp": None,
    }
    assert _codes(source) == ["module_level_decision_logic"]


# --------------------------------------------------------------------------
# Q5-DEC
# --------------------------------------------------------------------------


def _reasons(source: str) -> set[str]:
    return {f["unmutatable_reason"] for f in _findings(source) if f["unmutatable_reason"]}


def test_decorated_function_body_logic_is_nq2_not_q5():
    source = "@deco\ndef f(x):\n    if x:\n        return 1\n    return 2\n"
    assert _codes(source) == ["unmutatable_decision_logic"]
    assert _reasons(source) == {"decorated_function"}
    message = _message(source, "unmutatable_decision_logic")
    assert message == (
        "unmutatable decision logic at m.py:3 — "
        "move the logic into an undecorated helper so it can be mutated"
    )


def test_decorator_argument_logic_is_module_level():
    source = "@retry(times=3 if CI else 1)\ndef f():\n    return 1\n"
    assert _codes(source) == ["module_level_decision_logic"]
    assert _findings(source)[0]["line"] == 1


def test_single_line_def_default_is_module_level():
    assert _codes("def f(x=a == b): return x\n") == ["module_level_decision_logic"]


def test_mutated_code_carries_no_decision_reason():
    plain = "def f(x):\n    if x:\n        return 1\n    return 2\n"
    assert _codes(plain) == []
    static = (
        "class A:\n    @staticmethod\n    def m(x):\n        if x:\n            return 1\n"
        "        return 2\n"
    )
    assert _codes(static) == []


def test_nested_decorated_wrapper_is_unmutatable_at_any_depth():
    source = _src(
        """
        def outer(orig):
            @functools.wraps(orig)
            def wrapper(*a):
                if a:
                    return 1
                return orig()
            return wrapper
        """
    )
    assert _reasons(source) == {"decorated_function"}
    assert _codes(source) == ["unmutatable_decision_logic"]


def test_def_inside_module_level_with_is_not_a_mutated_unit():
    source = "with a:\n    def g(x):\n        if x:\n            return 1\n"
    assert _reasons(source) == {"non_top_level_function"}


def test_method_of_nested_class_is_not_a_mutated_unit():
    source = (
        "class A:\n    class B:\n        def m(self, x):\n            if x:\n"
        "                return 1\n"
    )
    assert _reasons(source) == {"non_top_level_function"}


def test_nested_def_non_simple_default_is_definition_time():
    source = "def outer():\n    def inner(x=a == b):\n        return x\n    return inner\n"
    assert _reasons(source) == {"definition_time_expression"}


def test_decorated_method_splits_decorator_and_body_logic():
    source = _src(
        """
        class A:
            @deco(1 if c else 2)
            def m(self):
                if self:
                    return 1
        """
    )
    codes = _codes(source)
    assert "class_level_decision_logic" in codes and "unmutatable_decision_logic" in codes
    by_line = {f["line"]: f for f in _findings(source) if f["construct"] == "IfExp"}
    assert by_line[2]["region"] == "class"


def test_no_line_carries_both_q5_and_nq2_reasons():
    sources = [case[0] for case in CLASS_CASES] + [case[0] for case in MODULE_CASES]
    sources.append("@deco\ndef f(x):\n    if x:\n        return 1\n")
    for source in sources:
        findings = _findings(source)
        nq2 = {f["line"] for f in findings if f["region"] == "function" and f["unmutatable_reason"]}
        q5 = {f["line"] for f in findings if f["region"] != "function"}
        assert nq2.isdisjoint(q5)
        for entry in ncg.unmutatable_gated_lines(source, ncg.statement_map(source)[0]):
            if entry["region"] == "function":
                assert entry["reason"] in {
                    "decorated_function",
                    "enum_body",
                    "never_mutate_name",
                    "non_top_level_function",
                }


@pytest.mark.parametrize(
    "source,expected",
    [
        ("def f(r):\n    return len(r.get('e') or [])\n", {"never_mutate_name"}),
        ("def f(x):\n    return isinstance(x, A if c else B)\n", {"never_mutate_name"}),
        ("def f(a, b):\n    return len(a) > 0 and b\n", set()),
        (
            "class C:\n    def __setattr__(self, k, v):\n        if k:\n            pass\n",
            {"never_mutate_name"},
        ),
    ],
)
def test_never_mutate_name_reasons(source, expected):
    assert _reasons(source) == expected


@pytest.mark.parametrize("base", ["Enum", "enum.IntEnum"])
def test_enum_special_methods_are_unmutatable_other_methods_are_not(base):
    label = (
        f"class E({base}):\n    def label(self):\n        if self:\n            return 1\n"
        "        return 2\n"
    )
    assert _reasons(label) == set()
    init = f"class E({base}):\n    def __init__(self, v):\n        if v:\n            self.v = 1\n"
    assert _reasons(init) == {"enum_body"}


def test_definition_time_expressions_inside_function_bodies():
    annotated = "def f():\n    x: (A if c else B) = 1\n    return x\n"
    assert _reasons(annotated) == {"definition_time_expression"}
    lam = "def f():\n    g = lambda y=a == b: y\n    return g\n"
    assert _reasons(lam) == {"definition_time_expression"}
    fstring = 'def f():\n    def inner(x=f"{a if b else c}"):\n        return x\n    return inner\n'
    assert _reasons(fstring) == set()


def test_unmutatable_gated_lines_lists_body_statements_without_logic():
    source = "@deco\ndef f(x):\n    y = x\n    if y:\n        return 1\n"
    got = ncg.unmutatable_gated_lines(source, ncg.statement_map(source)[0])
    assert [(e["line"], e["reason"], e["has_decision_logic"]) for e in got] == [
        (3, "decorated_function", False),
        (4, "decorated_function", True),
        (5, "decorated_function", False),
    ]
    assert {e["region"] for e in got} == {"function"}


# --------------------------------------------------------------------------
# NQ-1
# --------------------------------------------------------------------------


CARVED_TRY = "try:\n    import tomllib\nexcept ImportError:\n    tomllib = None\n"


def test_zero_mutant_reason_ignores_carve_outs_and_names_uncarved_lines():
    assert ncg.zero_mutant_reason("pkg/__init__.py", _findings(CARVED_TRY)) is None
    assert ncg.zero_mutant_reason("x.py", _findings("X = 1\n")) is None
    assert _codes(CARVED_TRY) == []
    mixed = CARVED_TRY + "if flag:\n    X = 1\n"
    reason = ncg.zero_mutant_reason("pkg/__init__.py", _findings(mixed))
    assert reason["code"] == "zero_mutant_decision_logic"
    assert reason["message"] == (
        "decision logic at pkg/__init__.py:5 — move logic into a function so it can be mutated"
    )


# --------------------------------------------------------------------------
# Q8-PRED
# --------------------------------------------------------------------------


def test_is_decision_logic_is_true_only_for_uncarved_findings():
    source = CARVED_TRY + "if flag:\n    X = 1\n"
    verdicts = {f["line"]: ncg.is_decision_logic(f) for f in _findings(source)}
    assert verdicts == {1: False, 5: True}
    assert ncg.has_decision_logic(CARVED_TRY, ncg.statement_map(CARVED_TRY)[0]) is False
    assert ncg.has_decision_logic(source, ncg.statement_map(source)[0]) is True


def test_unmutatable_gated_lines_has_decision_logic_ignores_carve_outs():
    source = "class E(Enum):\n    A = 1 == 1\n" + CARVED_TRY
    got = ncg.unmutatable_gated_lines(source, ncg.statement_map(source)[0])
    assert [(e["line"], e["has_decision_logic"]) for e in got] == [(2, True)]


def _nq1_decision(executed: int):
    gated = ncg.statement_map(CARVED_TRY)[0]
    assert ncg.zero_mutant_reason("a.py", _findings(CARVED_TRY)) is None
    rec = _record(executed_gated=executed, gated_statements=len(gated))
    return ncg.decide(_records(rec), [], ncg.THRESHOLDS)["files"][0]


def test_nq1_passes_carved_only_file_at_full_coverage():
    got = _nq1_decision(len(ncg.statement_map(CARVED_TRY)[0]))
    assert got["outcome"] == "pass" and got["fail_reasons"] == []


def test_nq1_carved_only_file_under_threshold_fails_on_coverage():
    got = _nq1_decision(0)
    assert [r["code"] for r in got["fail_reasons"]] == ["coverage_below_threshold"]


def test_only_is_decision_logic_and_findings_builder_read_carve_out():
    tree = ast.parse((REPO / "scripts/framework/new_code_gate_logic.py").read_text("utf-8"))
    readers = set()
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Subscript) and ast.unparse(node.slice) == "'carve_out'":
                readers.add(func.name)
    assert readers == {"is_decision_logic"}
    assert "ncg.is_decision_logic" in SELF_CHECK
    plugin = (REPO / "tests/framework/test_new_code_gate_plugin.py").read_text("utf-8")
    assert "ncg.is_decision_logic" in plugin


def test_selection_reason_nq1_carve_out():
    assert ncg.selection_reason(["t::a"], False, False) is None
    assert ncg.selection_reason([], True, True) is None
    assert ncg.selection_reason([], True, False) == "zero_mutant_decision_logic"
    assert ncg.selection_reason([], False, True) == "no_test_exercises"


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def test_selection_only_tests_executing_gated_lines():
    by_line = {
        1: ["tests/a.py::t1|run", "tests/a.py::t1|setup", ""],
        2: ["tests/b.py::t2|run"],
        3: ["tests/c.py::t3|run"],
    }
    assert ncg.select_by_context(by_line, [1, 2]) == ["tests/a.py::t1", "tests/b.py::t2"]
    assert ncg.select_by_context(by_line, [9]) == []
    assert ncg.contexts_to_node_ids(["", "|run"]) == []


def test_name_fallback_matches_stem_and_package_name():
    tracked = [
        "tests/framework/test_foo.py",
        "tests/test_foo.py",
        "tests/x/test_foobar.py",
        "a/test_foo.py",
    ]
    assert ncg.name_fallback_ids("scripts/oversight/foo.py", tracked) == [
        "tests/framework/test_foo.py",
        "tests/test_foo.py",
    ]
    assert ncg.name_fallback_ids("scripts/pkg/__init__.py", ["tests/test_pkg.py"]) == [
        "tests/test_pkg.py"
    ]


def test_remove_repo_copy_exact_and_container_children():
    selected = ["tests/a.py::t1", "tests/b.py"]
    kept, removed = ncg.remove_repo_copy(
        selected, ["tests/a.py::t1", "tests/b.py::tc", "tests/z.py::q"]
    )
    assert kept == ["tests/b.py"]
    assert removed == ["tests/a.py::t1", "tests/b.py::tc"]


def test_parse_repo_copy_collect_exit_codes_and_output():
    out = "tests/a.py::t1\ntests/b.py::T::t2\n\n2/9 tests collected (7 deselected)\n"
    assert ncg.parse_repo_copy_collect(0, out) == ["tests/a.py::t1", "tests/b.py::T::t2"]
    assert ncg.parse_repo_copy_collect(5, "no tests ran") == []
    with pytest.raises(ncg.GateError, match="pytest exited 2"):
        ncg.parse_repo_copy_collect(2, "")
    for bad in ("some noise\n\n", "other/x.py::t\n\n", "tests/a.py\n\n"):
        with pytest.raises(ncg.GateError, match="unparseable output"):
            ncg.parse_repo_copy_collect(0, bad)


def test_selection_fields_are_capped_and_bounded():
    ids = [f"tests/t.py::t{i}" for i in range(ncg.MAX_SELECTED_TESTS + 5)]
    fields = ncg.selection_fields("context", ids)
    assert fields["selected_tests_count"] == len(ids)
    assert len(fields["selected_tests"]) == ncg.MAX_SELECTED_TESTS
    assert fields["selected_tests_truncated"] is True
    small = ncg.selection_fields("name_fallback", ["tests/a.py"])
    assert small["selected_tests_truncated"] is False


def test_is_attributable_equal_under_or_module_of_selection():
    selected = ["tests/a.py::t1", "tests/b.py"]
    assert ncg.is_attributable("tests/a.py::t1", selected)
    assert ncg.is_attributable("tests/a.py", selected)
    assert ncg.is_attributable("tests/b.py::anything", selected)
    assert not ncg.is_attributable("tests/c.py::t", selected)


# --------------------------------------------------------------------------
# Path-load static pre-check
# --------------------------------------------------------------------------

GATED = "scripts/oversight/validators/foo.py"


def test_static_spec_from_file_location_fails_with_named_fix():
    sources = {
        "tests/oversight/test_foo.py": _src(
            """
            import importlib.util

            spec = importlib.util.spec_from_file_location(
                "foo_mod", "scripts/oversight/validators/foo.py"
            )
            """
        )
    }
    found = ncg.static_path_load_findings(GATED, sources)
    assert found == [
        {
            "importer": "tests/oversight/test_foo.py",
            "loaded_as": "foo_mod",
            "canonical": "scripts.oversight.validators.foo",
            "via": "static:spec_from_file_location",
            "phase": "static",
        }
    ]
    message = ncg.path_load_message("tests/oversight/test_foo.py", GATED, "foo_mod", "static:x")
    assert message == (
        "tests/oversight/test_foo.py loads scripts/oversight/validators/foo.py as module "
        "'foo_mod' (static:x) instead of the canonical "
        "'import scripts.oversight.validators.foo' — convert to a canonical scripts.... "
        "import in this PR"
    )


def test_static_path_load_matches_filename_segment_and_helper():
    sources = {"tests/t.py": 'load_module_from_path("m", ROOT / "validators" / "foo.py")\n'}
    assert [f["via"] for f in ncg.static_path_load_findings(GATED, sources)] == [
        "static:load_module_from_path"
    ]


def test_bare_sys_path_import_fails_with_named_fix():
    sources = {"tests/a.py": "from foo import main\n", "tests/b.py": "import foo\n"}
    found = ncg.static_path_load_findings(GATED, sources)
    assert [(f["importer"], f["via"], f["loaded_as"]) for f in found] == [
        ("tests/a.py", "static:bare_import", "foo"),
        ("tests/b.py", "static:bare_import", "foo"),
    ]


def test_canonical_import_and_unrelated_modules_are_clean():
    sources = {
        "tests/a.py": "from scripts.oversight.validators.foo import main\n",
        "tests/b.py": 'spec_from_file_location("x", "scripts/other.py")\nimport bar\n',
        "tests/broken.py": "def (:\n",
    }
    assert ncg.static_path_load_findings(GATED, sources) == []


def test_bare_import_only_applies_to_conftest_path_directories():
    sources = {"tests/a.py": "import foo\n"}
    assert ncg.static_path_load_findings("scripts/framework/foo.py", sources) == []


def _path_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.BinOp):
        return _path_parts(node.left) + _path_parts(node.right)
    if isinstance(node, ast.Constant):
        return [node.value]
    return []


def _assign_parts(tree: ast.AST, name: str) -> str:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.targets[0].id == name:
            return "/".join(_path_parts(node.value))
    raise AssertionError(name)


def test_bare_import_dirs_equal_conftest_insertions():
    tree = ast.parse((REPO / "tests" / "conftest.py").read_text(encoding="utf-8"))
    dirs = {_assign_parts(tree, "VALIDATORS_DIR"), _assign_parts(tree, "OVERSIGHT_DIR")}
    assert dirs == set(ncg.BARE_IMPORT_DIRS)


def test_no_path_literal_allow_list_in_logic_module():
    tree = ast.parse(LOGIC_FILE.read_text(encoding="utf-8"))
    names = {
        t.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    }
    assert not {n for n in names if "EXEMPT" in n.upper() and "SHELL" not in n.upper()}
    assert not {n for n in names if "ALLOW" in n.upper() or "SKIP" in n.upper()}


# --------------------------------------------------------------------------
# Workspace configuration
# --------------------------------------------------------------------------


def test_strip_no_mutate_pragmas_removes_only_those_tokens():
    source = _src(
        """
        x = 1  # pragma: no mutate
        y = "# pragma: no mutate"
        z = 2  # pragma: no cover
        # pragma: no mutate block
        if x:  # pragma: no mutate class
            pass
        """
    )
    out = ncg.strip_no_mutate_pragmas(source)
    # Lines keep their other bytes, so the two spaces before the comment remain.
    gap = " " * 2
    assert out == (
        f'x = 1{gap}\ny = "# pragma: no mutate"\nz = 2  # pragma: no cover\n\n'
        f"if x:{gap}\n    pass\n"
    )


@pytest.mark.parametrize("sep", ["\x0c", "\x0b", "\x1c", "\x85", " ", " "])
def test_strip_pragmas_is_not_fooled_by_characters_splitlines_breaks_on(sep):
    """F4: these inside a string shift `str.splitlines` rows away from the tokenizer's."""
    source = f'a = "1{sep}2"\nb = 2\nc = 3  # pragma: no mutate\n'
    assert ncg.strip_no_mutate_pragmas(source) == f'a = "1{sep}2"\nb = 2\nc = 3  \n'


def test_strip_pragmas_handles_crlf_and_a_pragma_on_the_last_unterminated_line():
    assert (
        ncg.strip_no_mutate_pragmas("a = 1  # pragma: no mutate\r\nb = 2\r\n")
        == "a = 1  \r\nb = 2\r\n"
    )
    assert ncg.strip_no_mutate_pragmas("a = 1\n# pragma: no mutate") == "a = 1\n"


def test_strip_pragmas_refuses_a_result_that_still_holds_a_pragma():
    """A bare `\\r` file leaves the tokenizer and the splitter disagreeing: refuse, never run it."""
    with pytest.raises(ncg.GateError, match="a no-mutate pragma survived stripping"):
        ncg.strip_no_mutate_pragmas("a = 1\rb = 2  # pragma: no mutate\r")


def test_strip_pragmas_refuses_a_cut_that_changes_a_non_comment_token(monkeypatch):
    monkeypatch.setattr(
        ncg, "_pragma_cuts", lambda source: [(0, 0, 3)] if "x = 1" in source else []
    )
    with pytest.raises(ncg.GateError, match="changed more than comments"):
        ncg.strip_no_mutate_pragmas("x = 1\n")


def test_split_lines_counts_only_newline_cr_and_crlf():
    assert ncg.split_lines("a\nb\n") == ["a", "b"]
    assert ncg.split_lines("a\r\nb\rc") == ["a", "b", "c"]
    assert ncg.split_lines("") == []
    assert ncg.split_lines("\n") == [""]
    assert ncg.split_lines("a\x0cb\x85c d\x0be\x1cf") == ["a\x0cb\x85c d\x0be\x1cf"]
    assert ncg.split_lines_keepends("a\r\nb\rc\n\nd") == ["a\r\n", "b\r", "c\n", "\n", "d"]
    assert ncg.split_lines_keepends("") == []


def test_changed_original_lines_numbers_lines_like_ast_after_a_form_feed():
    original = "a = '1\x0c2'\nb = 1\n"
    mutated = "a = '1\x0c2'\nb = 2\n"
    assert ncg.changed_original_lines(original, mutated) == [2]
    assert ncg.statement_map(original)[0] == {1, 2}


def test_safe_echo_has_no_cr_or_lf_and_no_leading_command_marker():
    assert ncg.safe_echo("a\r\n::error::x") == "a\\r\\n::error::x"
    assert ncg.safe_echo("::set-output name=x::y") == "\\::set-output name=x::y"
    assert ncg.safe_echo("plain") == "plain"


@pytest.mark.parametrize(
    "ids,expected",
    [
        (["tests/a.py::t", "tests/a.py::t", "tests/b/c.py"], ["tests/a.py::t", "tests/b/c.py"]),
        (["tests/a.py::t[x y]"], ["tests/a.py"]),
        (["tests/a.py::t[a\nb]", "tests/a.py::u"], ["tests/a.py", "tests/a.py::u"]),
        ([], []),
    ],
)
def test_sanitize_node_ids_keeps_safe_ids_and_widens_odd_ones_to_their_module(ids, expected):
    assert ncg.sanitize_node_ids(ids) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "--rootdir=/x",
        "-p evil",
        "-p evil::t",
        "tests/../../x.py::t",
        "scripts/a.py::t",
        "tests/a.py\n",
        "tests/a b.py::t",
        "tests/a.txt",
        "",
    ],
)
def test_sanitize_node_ids_refuses_anything_that_could_be_a_pytest_option_or_escape(bad):
    with pytest.raises(ncg.GateError, match="unsafe test id in coverage contexts"):
        ncg.sanitize_node_ids(["tests/ok.py::t", bad])


def test_blob_mismatches_lists_changed_and_missing_paths_sorted():
    expected = {"b.py": "1", "a.py": "2", "c.py": "3"}
    assert ncg.blob_mismatches(expected, {"a.py": "2", "b.py": "x"}) == ["b.py", "c.py"]
    assert ncg.blob_mismatches(expected, dict(expected)) == []


BOUND = {"mode": "ci", "gated_sha": "g1", "pr": 5, "run_id": "7", "run_attempt": "2"}
NOT_BOUND = "records not bound to this run: "


def test_check_records_binding_names_the_first_field_that_differs():
    assert ncg.check_records_binding(BOUND, "ci", "g1", 5, "7", 2) is None
    assert ncg.check_records_binding(BOUND, "local", "g1", 5, "7", 2) == (
        NOT_BOUND + "mode is ci, expected local"
    )
    assert ncg.check_records_binding(BOUND, "ci", "g2", 5, "7", 2) == (
        NOT_BOUND + "gated_sha is g1, expected g2"
    )
    assert ncg.check_records_binding(BOUND, "ci", "g1", 6, "7", 2) == (
        NOT_BOUND + "pr is 5, expected 6"
    )
    assert ncg.check_records_binding(BOUND, "ci", "g1", 5, "8", 2) == (
        NOT_BOUND + "run_id is 7, expected 8"
    )
    no_run = {k: v for k, v in BOUND.items() if k != "run_id"}
    assert NOT_BOUND + "run_id is None, expected 7" == ncg.check_records_binding(
        no_run, "ci", "g1", 5, "7", 2
    )


@pytest.mark.parametrize(
    ("written", "current", "ok"),
    [
        ("2", 2, True),
        ("1", 2, True),
        (1, 2, True),
        ("3", 2, False),
        (3, 2, False),
        ("two", 2, False),
        ("-1", 2, False),
        ("٢", 2, False),
        (True, 2, False),
        (None, 2, False),
        (2.0, 2, False),
    ],
)
def test_binding_accepts_an_equal_or_earlier_integer_attempt_only(written, current, ok):
    records = dict(BOUND, run_attempt=written)
    message = ncg.check_records_binding(records, "ci", "g1", 5, "7", current)
    if ok:
        assert message is None
    else:
        assert message.startswith(NOT_BOUND + "run_attempt is ")
        assert f"expected an integer of at most {current}" in message


def test_local_binding_expects_no_run_id_no_attempt_and_no_pr():
    local = {"mode": "local", "gated_sha": "g1", "pr": None, "run_id": None, "run_attempt": None}
    assert ncg.check_records_binding(local, "local", "g1", None, None, None) is None
    for field, value in (("run_id", "1"), ("pr", 1)):
        message = ncg.check_records_binding(
            dict(local, **{field: value}), "local", "g1", None, None, None
        )
        assert message == NOT_BOUND + f"{field} is {value}, expected None"
    assert ncg.check_records_binding(
        dict(local, run_attempt="1"), "local", "g1", None, None, None
    ) == (NOT_BOUND + "run_attempt is 1, expected none")


def test_binding_message_bounds_a_hostile_value():
    message = ncg.check_records_binding(dict(BOUND, run_id="x" * 5000), "ci", "g1", 5, "7", 2)
    assert len(message) < 1200 and message.endswith("expected 7")


def test_attempt_number_reads_integers_and_ascii_digit_strings():
    assert [ncg.attempt_number(v) for v in (4, "4", "04", True, "x", "", None, "४")] == [
        4,
        4,
        4,
        None,
        None,
        None,
        None,
        None,
    ]


def test_sidecar_run_is_checked_only_when_a_run_id_is_given():
    meta = {"head_sha": "abc", "clean": True, "coverage_core": "ctrace", "run_id": "9"}
    assert ncg.check_sidecar_head(meta, "abc") is None
    assert ncg.check_sidecar_head(meta, "abc", "9") is None
    prefix = "coverage data stale or from a dirty tree: "
    assert ncg.check_sidecar_head(meta, "abc", "10") == (
        prefix + "run: sidecar was written by run 9, this is run 10"
    )
    assert ncg.check_sidecar_head({**meta, "run_id": None}, "abc", "10").endswith(
        "written by run None, this is run 10"
    )


def test_tree_modes_read_every_entry_and_spot_only_symlinks():
    entries = [
        "100644 blob a1\ta.py",
        "120000 blob b2\tlink.py",
        "100755 blob c3\tdir/with space.sh",
        "120000 blob d4\ttab\tname.py",
    ]
    listing = "\x00".join(entries) + "\x00"
    modes = ncg.parse_tree_modes(listing)
    assert modes == {
        "a.py": "100644",
        "link.py": "120000",
        "dir/with space.sh": "100755",
        "tab\tname.py": "120000",
    }
    assert [ncg.mode_fail_code(m) for m in modes.values()] == [
        None,
        "symlink_not_gateable",
        None,
        "symlink_not_gateable",
    ]
    assert ncg.parse_tree_modes("") == {}


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("100644", None),
        ("100755", None),
        ("120000", "symlink_not_gateable"),
        ("160000", "mode_not_gateable"),
        ("040000", "mode_not_gateable"),
        ("100664", "mode_not_gateable"),
        ("", "mode_not_gateable"),
    ],
)
def test_mode_allow_list_has_one_decision_per_mode(mode, code):
    """MODE-L (RV2-4a): regular files pass, a symlink and anything unexpected fail, each with its own code."""
    assert ncg.mode_fail_code(mode) == code
    if code == "mode_not_gateable":
        message = ncg.mode_message(mode)
        assert f"(mode {mode}, for example a submodule)" in message
        assert "only regular files (100644, 100755) can be gated" in message
    if code == "symlink_not_gateable":
        assert ncg.mode_message(mode) == ncg.MSG_SYMLINK


def test_mode_not_gateable_follows_symlink_and_is_never_ruling_eligible():
    assert ncg.FAIL_ORDER[:2] == ("symlink_not_gateable", "mode_not_gateable")
    assert "mode_not_gateable" not in ncg.RULING_ELIGIBLE
    record = ncg.blank_file_record("scripts/x.py", "new")
    record["fail_reasons"] = [ncg.fail_reason("mode_not_gateable", ncg.mode_message("160000"))]
    ruling = [{"path": "scripts/x.py", "blob_sha": None}]
    decision = ncg.decide({"files": [record]}, ruling, ncg.THRESHOLDS)
    assert decision["files"][0]["outcome"] == "fail" and decision["exit_code"] == 1


def test_cell_1_escapes_html_then_backslash_then_markdown_then_newlines():
    """CELL-1 (RV2-4b): the exact order matters; a hostile path renders to one inert string."""
    hostile = "a|b`c[d](e)<img src=x>&\\.py"
    assert ncg._cell(hostile) == "a\\|b\\`c\\[d\\](e)&lt;img src=x&gt;&amp;\\\\.py"
    assert ncg._cell("one\r\ntwo\nthree\rfour") == "one  two three four"
    assert ncg._cell("&lt;") == "&amp;lt;"
    assert ncg._cell(7) == "7"


def test_cell_is_used_for_every_table_cell_and_detail_and_error_line():
    record = ncg.blank_file_record("a|b`c[d](e)<img>.py", "new")
    record["outcome"] = "fail"
    record["fail_reasons"] = [{"code": "x", "message": "see [here](http://x) <b>"}]
    verdict = {
        "files": [record],
        "overall": "fail",
        "internal_errors": [{"code": "e", "message": "<script>`"}],
    }
    text = ncg.render_summary(verdict)
    assert "a\\|b\\`c\\[d\\](e)&lt;img&gt;.py" in text
    assert "- see \\[here\\](http://x) &lt;b&gt;" in text
    assert "- e: &lt;script&gt;\\`" in text
    assert "<" not in text and "`" not in text.replace("\\`", "")


def test_symlink_not_gateable_is_the_first_fail_code_and_never_ruling_eligible():
    assert ncg.FAIL_ORDER[0] == "symlink_not_gateable"
    assert "symlink_not_gateable" not in ncg.RULING_ELIGIBLE
    assert "re-exports the target" in ncg.MSG_SYMLINK
    record = ncg.blank_file_record("scripts/x.py", "new")
    record["fail_reasons"] = [ncg.fail_reason("symlink_not_gateable", ncg.MSG_SYMLINK)]
    ruling = [{"path": "scripts/x.py", "blob_sha": None}]
    decision = ncg.decide({"files": [record]}, ruling, ncg.THRESHOLDS)
    assert decision["files"][0]["outcome"] == "fail" and decision["exit_code"] == 1


def test_enumerate_seconds_is_a_timing_field_outside_the_record_hash():
    record = ncg.blank_file_record("scripts/x.py", "new")
    assert record["enumerate_seconds"] == 0.0 and "enumerate_seconds" in ncg.FILE_FIELDS
    slower = dict(record, seconds=9.0, enumerate_seconds=4.5)
    assert ncg.records_sha256([record]) == ncg.records_sha256([slower])
    assert ncg.TIMING_FIELDS == {"seconds", "enumerate_seconds"}


def test_timeout_message_reports_phases_slowest_files_and_where_it_ran_out():
    files = {f"f{i}.py": (float(i), 0.5) for i in range(8)}
    message = ncg.timeout_message(
        {"mutmut_run": 1400.04, "enumerate": 12.0}, files, "mutmut_run of f7.py"
    )
    assert message.startswith(ncg.MSG_TIMEOUT + " (ran out in mutmut_run of f7.py; ")
    assert "phases: enumerate 12.0s, mutmut_run 1400.0s;" in message
    assert "slowest files: f7.py 7.0s (workspace 0.5s), f6.py 6.0s" in message
    assert "f3.py" in message and "f2.py" not in message


def test_also_copy_has_only_top_level_entries():
    dirs = [".github", ".claude", "audit", "bin", "scripts", "tests", "docs/"]
    files = ["CLAUDE.md", "setup.cfg", "pyproject.toml", "AGENTS.md"]
    source_paths = ncg.mutmut_source_paths(["bin", "scripts", "tests"], "scripts/x.py")
    assert source_paths == ["bin/", "scripts/"]
    got = ncg.mutmut_also_copy(dirs, files, source_paths)
    assert got == [".github/", "audit/", "docs/", "AGENTS.md", "CLAUDE.md"]
    for entry in got:
        assert "/" not in entry.rstrip("/")
    assert ".claude/" not in got and "setup.cfg" not in got and "pyproject.toml" not in got


def test_source_paths_include_a_top_level_gated_file():
    assert ncg.mutmut_source_paths(["scripts"], "tool.py") == ["scripts/", "tool.py"]


def test_generated_pytest_args_pin_report_chars():
    args = ncg.generated_pytest_args()
    assert args.count("-rfE") == 1
    assert [a for a in args if a.startswith("-r") and a != "-rfE"] == []
    assert not [a for a in args if a.startswith("--report-chars")]
    assert "--no-summary" not in args and "-q" not in args
    assert ["-p", "_ncg_tripwire"] == args[
        args.index("_ncg_tripwire") - 1 : args.index("_ncg_tripwire") + 1
    ]
    assert args[-2:] == ["-m", "not repo_copy"]
    assert ncg.mutmut_table(["a/"], "a/x.py", [], ["t"])["pytest_add_cli_args"] == args


FORBIDDEN_RERUN_FLAGS = (
    "--fail-on-flaky",
    "--only-rerun",
    "--rerun-except",
    "--max-suite-reruns",
    "--reruns-delay",
    "-p no:rerunfailures",
)


def test_a4d_generated_args_rerun_once_and_never_change_how_reruns_are_judged():
    """RV-1: `--reruns 1` matches the `tests` job; no other rerun option may appear."""
    args = ncg.generated_pytest_args()
    assert args.count("--reruns") == 1 and args[args.index("--reruns") + 1] == "1"
    assert args == [
        "--no-header",
        "-rfE",
        "--reruns",
        "1",
        "-p",
        "no:cacheprovider",
        "-p",
        "no:randomly",
        "-p",
        "_ncg_tripwire",
        "-m",
        "not repo_copy",
    ]
    joined = " ".join(args)
    for flag in FORBIDDEN_RERUN_FLAGS:
        assert flag not in joined
    assert not [a for a in args if a.startswith("--reruns") and a != "--reruns"]
    assert "rerunfailures" not in joined


def test_generated_config_selection_equals_selection():
    table = ncg.mutmut_table(["a/"], "a/x.py", ["docs/"], ["tests/t.py::a", "tests/t.py::b"])
    assert table["pytest_add_cli_args_test_selection"] == ["tests/t.py::a", "tests/t.py::b"]
    assert table["only_mutate"] == ["a/x.py"]
    assert (
        table["use_git_change_detection"] is False and table["mutate_only_covered_lines"] is False
    )
    assert table["timeout_multiplier"] == 15.0 and table["max_stack_depth"] == -1


def test_compose_pyproject_replaces_only_the_mutmut_table():
    head = _src(
        """
        [tool.black]
        line-length = 100

        [tool.mutmut]
        source_paths = [
            "old/",
        ]
        also_copy = ["x/"]

        [tool.other]
        keep = true
        """
    )
    table = ncg.mutmut_table(["a/"], "a/x.py", ["docs/"], ["tests/t.py::a"])
    out = ncg.compose_pyproject(head, table)
    parsed = __import__("tomllib").loads(out)
    assert parsed["tool"]["mutmut"] == table
    assert parsed["tool"]["black"] == {"line-length": 100}
    assert parsed["tool"]["other"] == {"keep": True}
    assert "old/" not in out


def test_compose_pyproject_round_trips_the_real_file():
    head = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    table = ncg.mutmut_table(["bin/", "scripts/"], "scripts/x.py", [".github/"], ["tests/t.py"])
    out = ncg.compose_pyproject(head, table)
    assert "[tool.mutmut]" in out and 'only_mutate = ["scripts/x.py"]' in out


def test_compose_pyproject_rejects_a_table_that_does_not_round_trip():
    with pytest.raises(ncg.GateError, match="failed round-trip"):
        ncg.compose_pyproject("[tool.black]\nx = 1\n", {"bad": {"k": 1}})


# --------------------------------------------------------------------------
# Mutants: mapping, classification, score
# --------------------------------------------------------------------------


def test_changed_original_lines_and_mapping():
    original = "def f(a):\n    x = (1 +\n         2)\n    return a + x\n"
    mutated = "def f(a):\n    x = (1 -\n         2)\n    return a + x\n"
    changed = ncg.changed_original_lines(original, mutated)
    assert changed == [2]
    statements, multiline = ncg.statement_map(original)
    assert ncg.map_mutant_lines([3], statements, multiline) == [2]
    assert ncg.is_gated_mutant([2], [2, 4]) and not ncg.is_gated_mutant([3], [2, 4])
    assert ncg.changed_original_lines("a\n", "a\nb\n") == [2]
    assert ncg.changed_original_lines("a\nb\n", "a\n") == [2]
    assert ncg.changed_original_lines("a\n", "a\n") == []


@pytest.mark.parametrize(
    "key,ok",
    [
        ("scripts.framework.m.x_main__mutmut_1", True),
        ("scripts.framework.m.xǁKlassǁrun__mutmut_12", True),
        ("scripts.framework.m.x_main", False),
        ("x" * 600 + ".x_a__mutmut_1", False),
        ("evil; rm -rf", False),
    ],
)
def test_mutant_key_pattern(key, ok):
    assert ncg.check_mutant_key(key) is ok


def test_timeout_status_counts_killed_segfault_does_not():
    statuses = {
        "a": "killed",
        "b": "timeout",
        "c": "segfault",
        "d": "survived",
        "e": "no tests",
        "f": "suspicious",
    }
    got = ncg.classify_statuses(statuses, ["a", "b", "c", "d", "e"])
    assert got == {
        "mutants_total": 5,
        "mutants_killed": 2,
        "mutant_status_counts": {
            "killed": 1,
            "timeout": 1,
            "segfault": 1,
            "survived": 1,
            "no tests": 1,
        },
    }
    assert ncg.mutant_score_pct(2, 5) == 40.0 and ncg.mutant_score_pct(0, 0) is None


@pytest.mark.parametrize("status", ["caught by type check", "mystery"])
def test_unexpected_mutant_status_raises(status):
    with pytest.raises(ncg.GateError, match="unexpected mutant status"):
        ncg.classify_statuses({"a": status}, ["a"])


def test_short_summary_parse_reads_only_the_section():
    noise = _src(
        """
        FAILED: Unable to force test failures
        ----- Captured stdout call -----
        FAILED tests/x.py::fake
        =================================== FAILURES ===================================
        ___ test_a ___
        """
    )
    assert ncg.parse_short_summary(noise) == []
    real = noise + _src(
        """
        =========================== short test summary info ============================
        FAILED tests/a.py::t - msg
        ERROR tests/b.py
        =========================== warnings summary ===================================
        FAILED tests/after.py::no
        """
    )
    assert ncg.parse_short_summary(real) == ["tests/a.py::t", "tests/b.py"]
    colored = "\x1b[31m=== short test summary info ===\x1b[0m\nFAILED tests/a.py::t - boom\n"
    assert ncg.parse_short_summary(colored) == ["tests/a.py::t"]
    two = (
        "=== short test summary info ===\nFAILED tests/old.py::x\n"
        "FAILED tests/y.py::fake - forged\n=== short test summary info ===\n"
        "FAILED tests/new.py::z\n"
    )
    assert ncg.parse_short_summary(two) == ["tests/new.py::z"]


# --------------------------------------------------------------------------
# Shell: AC-8, AC-9, R-H4
# --------------------------------------------------------------------------

IF_ELSE_SH = 'if [[ -z "$a" ]]; then\n  x=1\nelse\n  x=2\nfi\n'
GUARD_SH = 'if [[ -z "$a" ]]; then\n  echo hi\nfi\n'
FLAG_PARSE_SH = 'while [[ $# -gt 0 ]]; do\n  case "$1" in\n    *) shift ;;\n  esac\ndone\n'


def _shell(path, head, base="", changed=None, exempt=None):
    head_lines = decision_lines(head.splitlines())
    base_lines = decision_lines(base.splitlines())
    if changed is None:
        changed = range(1, len(head.splitlines()) + 1)
    return ncg.shell_gate(
        path,
        is_hard_exempt(path) if exempt is None else exempt,
        head_lines,
        base_lines,
        changed,
    )


def test_shell_new_file_if_else_fails_guard_and_flagparse_pass():
    record, reasons = _shell("s.sh", IF_ELSE_SH)
    assert [r["code"] for r in reasons] == ["shell_decision_logic"]
    assert reasons[0]["message"] == (
        "shell decision logic at s.sh:1 — move decision logic into tested Python "
        "(recommended home: scripts/automation/lib)"
    )
    assert record["head_count"] == 1 and record["counted_on_changed_lines"] == [1]
    assert _shell("g.sh", GUARD_SH)[1] == []
    assert _shell("f.sh", FLAG_PARSE_SH)[1] == []


def test_shell_changed_case_fails_untouched_logic_passes():
    base = IF_ELSE_SH
    added_case = base + 'case "$m" in\n  a) : ;;\nesac\n'
    _record, reasons = _shell("s.sh", added_case, base, changed=[6, 7, 8])
    assert [r["code"] for r in reasons] == ["shell_decision_logic"]
    assert reasons[0]["message"].startswith("shell decision logic at s.sh:6")
    shifted = "echo header\n" + base
    assert _shell("s.sh", shifted, base, changed=[1])[1] == []


def test_hos_bootstrap_sh_exempt():
    record, reasons = _shell("bootstrap/hos_bootstrap.sh", IF_ELSE_SH)
    assert record == {"exempt": "hos_bootstrap"} and reasons == []


def test_edited_counted_if_line_fails_edited_guard_line_passes():
    edited = IF_ELSE_SH.replace('"$a"', '"$b"')
    assert [r["code"] for r in _shell("s.sh", edited, IF_ELSE_SH, changed=[1])[1]] == [
        "shell_decision_logic"
    ]
    guard_edit = GUARD_SH.replace('"$a"', '"$b"')
    assert _shell("s.sh", guard_edit, GUARD_SH, changed=[1])[1] == []


def test_for_loop_not_counted():
    assert decision_lines(["for i in a; do", "  echo $i", "done"]) == []
    assert _shell("s.sh", "for i in a; do\n  echo $i\ndone\n")[1] == []


def test_count_growth_on_unchanged_lines_still_fails():
    _record, reasons = ncg.shell_gate("s.sh", False, [5], [], [1])
    assert reasons[0]["message"].startswith("shell decision logic at s.sh:5")


# --------------------------------------------------------------------------
# decide, records, rendering
# --------------------------------------------------------------------------


def _record(path="a.py", **fields):
    rec = ncg.blank_file_record(path, "new")
    rec.update(fields)
    return rec


def _records(*files, internal=()):
    return {"files": list(files), "internal_errors": list(internal), "records_sha256": None}


def test_record_has_every_req24_field():
    rec = ncg.blank_file_record("a.py", "new")
    assert set(rec) == set(ncg.FILE_FIELDS)
    for name in (
        "blob_sha",
        "pr_head_blob_sha",
        "decision_logic_findings",
        "decision_logic_findings_truncated",
        "unmutatable_gated_lines",
        "removed_repo_copy",
        "path_load_findings",
        "exception_path",
    ):
        assert name in rec
    assert rec["exception"] is None and rec["exception_path"] == ncg.EXCEPTION_PATH_TEXT


def test_record_carries_blob_sha_and_bounded_fields():
    rec = ncg.blank_file_record("p" * 2000, "changed")
    assert len(rec["path"]) == ncg.MAX_PATH_CHARS
    fields = ncg.gated_lines_fields(list(range(ncg.MAX_GATED_LINES + 1)))
    assert fields["gated_lines_truncated"] is True and len(fields["gated_lines"]) == 5000
    found = ncg.findings_fields([{"line": 1}] * (ncg.MAX_GATED_LINES + 1))
    assert found["decision_logic_findings_truncated"] is True


def test_no_ruling_input_in_s2_failing_file_stays_fail():
    rec = _record(executed_gated=1, gated_statements=10, blob_sha="b1")
    decision = ncg.decide(_records(rec), [], ncg.THRESHOLDS)
    assert decision["exit_code"] == 1 and decision["overall"] == "fail"
    assert decision["files"][0]["outcome"] == "fail"
    assert [r["code"] for r in decision["files"][0]["fail_reasons"]] == ["coverage_below_threshold"]


def test_ruling_binds_to_blob_and_covers_thresholds_only():
    rec = _record(executed_gated=1, gated_statements=10, blob_sha="b1")
    good = [{"path": "a.py", "blob_sha": "b1"}]
    assert ncg.decide(_records(rec), good, ncg.THRESHOLDS)["files"][0]["outcome"] == "excepted"
    stale = [{"path": "a.py", "blob_sha": "other"}]
    assert ncg.decide(_records(rec), stale, ncg.THRESHOLDS)["files"][0]["outcome"] == "fail"
    rec["fail_reasons"] = [ncg.fail_reason("path_loaded_module", "x")]
    assert ncg.decide(_records(rec), good, ncg.THRESHOLDS)["files"][0]["outcome"] == "fail"


def test_decide_orders_reasons_and_merges_duplicates():
    rec = _record(
        executed_gated=0,
        gated_statements=5,
        fail_reasons=[
            ncg.fail_reason("module_level_decision_logic", "m"),
            ncg.fail_reason("no_test_exercises", "n"),
            ncg.fail_reason("coverage_below_threshold", "already"),
        ],
    )
    reasons = ncg.decide(_records(rec), [], ncg.THRESHOLDS)["files"][0]["fail_reasons"]
    assert [r["code"] for r in reasons] == [
        "no_test_exercises",
        "module_level_decision_logic",
        "coverage_below_threshold",
    ]
    assert reasons[-1]["message"] == "already"


def test_decide_exit_codes_zero_files_internal_and_upstream():
    assert ncg.decide(_records(), [], ncg.THRESHOLDS)["exit_code"] == 0
    ok = _record(executed_gated=10, gated_statements=10)
    assert ncg.decide(_records(ok), [], ncg.THRESHOLDS)["exit_code"] == 0
    err = {"code": "x", "message": "boom"}
    assert ncg.decide(_records(ok, internal=[err]), [], ncg.THRESHOLDS)["exit_code"] == 3
    upstream = ncg.decide(
        _records(ok), [], ncg.THRESHOLDS, ["upstream job not successful: failure"]
    )
    assert upstream["exit_code"] == 3 and upstream["internal_errors"][0]["code"] == "upstream"
    flagged = ncg.decide(_records(ok, internal=[{**err, "file": "a.py"}]), [], ncg.THRESHOLDS)
    assert flagged["files"][0]["outcome"] == "fail" and flagged["exit_code"] == 3


def test_decide_reads_no_environment():
    tree = ast.parse(LOGIC_FILE.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "os" not in names and "getenv" not in attrs and "environ" not in attrs


def test_gate_modules_import_only_stdlib_at_module_level():
    tree = ast.parse(LOGIC_FILE.read_text(encoding="utf-8"))
    allowed = set(sys.stdlib_module_names) | {"__future__"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert {a.name.split(".")[0] for a in node.names} <= allowed
        if isinstance(node, ast.ImportFrom):
            assert node.module.split(".")[0] in allowed


def test_summary_table_per_file_columns():
    rec = _record(
        "a|b.py",
        executed_gated=8,
        gated_statements=10,
        coverage_pct=80.0,
        mutation_ran=True,
        mutants_total=4,
        mutants_killed=3,
        mutant_score_pct=75.0,
        selection_method="context",
        fail_reasons=[ncg.fail_reason("no_test_exercises", "line one\nline two | x")],
    )
    decision = ncg.decide(_records(rec), [], ncg.THRESHOLDS)
    doc = ncg.verdict_document(_records(rec), decision)
    text = ncg.render_summary(doc)
    header = text.splitlines()[0]
    assert header == (
        "| File | Kind | Coverage (covered/gated) | Mutant score (killed/total) "
        "| Selection | Outcome | Reasons |"
    )
    row = text.splitlines()[2]
    assert row == (
        "| a\\|b.py | new | 80.0% (8/10) | 75.0% (3/4) | context | fail | no_test_exercises |"
    )
    assert "line one line two \\| x" in text
    assert "1 gated file(s): 0 pass, overall fail." in text


def test_summary_with_no_files_and_internal_errors():
    empty = ncg.verdict_document(_records(), ncg.decide(_records(), [], ncg.THRESHOLDS))
    assert ncg.render_summary(empty) == "No gated files in this PR.\n"
    err = ncg.decide(_records(internal=[{"code": "c", "message": "m"}]), [], ncg.THRESHOLDS)
    text = ncg.render_summary(ncg.verdict_document(_records(), err))
    assert text == "No gated files in this PR.\n\nInternal errors:\n- c: m\n"


def test_verdict_artifact_matches_schema_v1_and_sha():
    a = _record("a.py", seconds=1.5, executed_gated=10, gated_statements=10)
    b = _record("b.py", seconds=9.0)
    records = _records(a, b)
    records["records_sha256"] = ncg.records_sha256(records["files"])
    slower = [dict(a, seconds=99.0), dict(b, seconds=0.1)]
    assert ncg.records_sha256(slower) == records["records_sha256"]
    assert ncg.verify_measure_sha(records)
    changed = _records(dict(a, executed_gated=9), b)
    changed["records_sha256"] = records["records_sha256"]
    assert not ncg.verify_measure_sha(changed)
    doc = ncg.verdict_document(records, ncg.decide(records, [], ncg.THRESHOLDS))
    assert doc["phase"] == "verdict" and doc["measure_records_sha256"] == records["records_sha256"]
    assert [f["outcome"] for f in doc["files"]] == ["pass", "pass"]
    assert doc["overall"] == "pass" and doc["exit_code"] == 0
    assert set(ncg.TOP_LEVEL_FIELDS) >= {"gated_sha", "pr_head_sha", "base_sha", "gated_tree"}
    assert json.loads(json.dumps(doc)) == doc


# --------------------------------------------------------------------------
# Q5-SELF: the gate's own files pass its own rules (TD 5.19)
# --------------------------------------------------------------------------

SELF_CHECK = """
import json, sys
sys.path.insert(0, ".")
from pathlib import Path
from scripts.framework import new_code_gate_logic as ncg

out = {}
for rel in sys.argv[1:]:
    src = Path(rel).read_text(encoding="utf-8")
    findings = ncg.decision_logic_findings(src, ncg.statement_map(src)[0])
    out[rel] = [
        f for f in findings
        if (f["region"] in ("module", "class") and ncg.is_decision_logic(f))
        or (f["region"] == "function" and f["unmutatable_reason"])
    ]
print(json.dumps(out))
"""

SELF_FILES = [
    "scripts/framework/new_code_gate_logic.py",
    "scripts/oversight/validators/shell_logic_check.py",
]


def _final_main_block_lines(rel: str) -> set[int]:
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    last = tree.body[-1]
    assert isinstance(last, ast.If)
    return set(range(last.lineno, last.end_lineno + 1))


def test_gate_modules_have_no_q5_or_nq2_findings():
    # Runs in a subprocess so it earns no coverage context and never reads a
    # trampolined copy of the file under mutation.
    proc = subprocess.run(
        [sys.executable, "-c", SELF_CHECK, *SELF_FILES],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    failing = json.loads(proc.stdout)
    assert failing["scripts/framework/new_code_gate_logic.py"] == []
    shell = failing["scripts/oversight/validators/shell_logic_check.py"]
    inside = _final_main_block_lines("scripts/oversight/validators/shell_logic_check.py")
    assert shell and all(f["node_line"] in inside for f in shell)
