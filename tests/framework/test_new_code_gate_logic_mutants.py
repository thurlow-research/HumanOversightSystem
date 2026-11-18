"""Behaviour pins for `new_code_gate_logic`, found by a mutation run of the gate itself.

Each test asserts a documented behaviour of a pure function that the existing logic tests left
unpinned: boundaries of the truncation and threshold helpers, git's C-style path quoting, the
line sets a compound statement owns, and the generated `[tool.mutmut]` table (TD 5.8).
"""

import ast
import json
import textwrap

import pytest

from scripts.framework import new_code_gate_logic as ncg

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def test_bound_text_keeps_text_of_exactly_the_limit_whole():
    text = "x" * 20
    assert ncg.bound_text(text, 20) == text


def test_bound_text_cuts_longer_text_to_the_limit_ending_in_the_suffix():
    got = ncg.bound_text("x" * 21, 20)
    assert len(got) == 20 and got.endswith(ncg.TRUNCATION_SUFFIX)
    assert got == "x" * (20 - len(ncg.TRUNCATION_SUFFIX)) + ncg.TRUNCATION_SUFFIX


@pytest.mark.parametrize(
    "numerator,denominator,threshold,expected",
    [
        (80, 100, 80, True),
        (79, 100, 80, False),
        (793, 1000, 80, False),
        (800, 1000, 80, True),
        (3, 4, 75, True),
        (74, 100, 75, False),
        (0, 5, 0, True),
    ],
)
def test_meets_threshold_is_exact_integer_arithmetic(numerator, denominator, threshold, expected):
    assert ncg.meets_threshold(numerator, denominator, threshold) is expected


# --------------------------------------------------------------------------
# unquote_git_path
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "quoted,expected",
    [
        ('"a\\nb"', "a\nb"),
        ('"a\\tb"', "a\tb"),
        ('"a\\"b"', 'a"b'),
        ('"a\\\\b"', "a\\b"),
        ('"caf\\303\\251.py"', "café.py"),
        ('"bad\\377.py"', "bad�.py"),
        ('"naïve.py"', "naïve.py"),
        ('"x\\ay"', "xay"),
        ('"\\101"', "A"),
    ],
)
def test_unquote_git_path_decodes_each_kind_of_escape(quoted, expected):
    assert ncg.unquote_git_path(quoted) == expected


def test_unquote_git_path_leaves_an_unquoted_or_half_quoted_name_alone():
    assert ncg.unquote_git_path('"half') == '"half'
    assert ncg.unquote_git_path('half"') == 'half"'


# --------------------------------------------------------------------------
# Lines a statement owns
# --------------------------------------------------------------------------


def first_stmt(source):
    return ast.parse(textwrap.dedent(source)).body[0]


def test_own_lines_of_a_simple_statement_is_every_line_it_spans():
    node = first_stmt(
        """\
        value = call(
            1,
            2,
        )
        """
    )
    assert ncg._own_lines(node) == {1, 2, 3, 4}


def test_own_lines_of_an_if_is_its_header_only():
    node = first_stmt(
        """\
        if (a and
                b):
            x = 1
        """
    )
    assert ncg._own_lines(node) == {1, 2}


def test_own_lines_of_a_try_includes_each_except_header_but_not_the_bodies():
    node = first_stmt(
        """\
        try:
            x = 1
        except (ValueError,
                TypeError):
            y = 2
        except KeyError:
            z = 3
        """
    )
    assert ncg._own_lines(node) == {1, 3, 4, 6}


def test_own_lines_of_a_match_includes_each_case_pattern_but_not_the_bodies():
    node = first_stmt(
        """\
        match value:
            case [a,
                  b]:
                z = 1
            case _:
                z = 2
        """
    )
    assert ncg._own_lines(node) == {1, 2, 3, 5}


def test_own_lines_of_a_decorated_function_starts_at_its_first_decorator():
    node = first_stmt(
        """\
        @decorator
        def f(a,
              b):
            return a
        """
    )
    assert ncg._own_lines(node) == {1, 2, 3}


# --------------------------------------------------------------------------
# The generated [tool.mutmut] table (TD 5.8)
# --------------------------------------------------------------------------


def test_mutmut_table_has_exactly_the_keys_and_values_of_the_design():
    table = ncg.mutmut_table(["scripts/"], "scripts/x.py", ["docs/"], ["tests/t.py::a"])
    assert table == {
        "source_paths": ["scripts/"],
        "only_mutate": ["scripts/x.py"],
        "do_not_mutate": [],
        "do_not_mutate_patterns": [],
        "type_check_command": [],
        "cache_invalidation_files": [],
        "also_copy": ["docs/"],
        "pytest_add_cli_args": list(ncg.PYTEST_ADD_CLI_ARGS),
        "pytest_add_cli_args_test_selection": ["tests/t.py::a"],
        "use_git_change_detection": False,
        "mutate_only_covered_lines": False,
        "track_dependencies": False,
        "timeout_multiplier": 15.0,
        "timeout_constant": 1.0,
        "max_stack_depth": -1,
        "process_isolation": "fork",
        "debug": False,
        "log_to_file": False,
    }
    assert list(table) == [
        "source_paths",
        "only_mutate",
        "do_not_mutate",
        "do_not_mutate_patterns",
        "type_check_command",
        "cache_invalidation_files",
        "also_copy",
        "pytest_add_cli_args",
        "pytest_add_cli_args_test_selection",
        "use_git_change_detection",
        "mutate_only_covered_lines",
        "track_dependencies",
        "timeout_multiplier",
        "timeout_constant",
        "max_stack_depth",
        "process_isolation",
        "debug",
        "log_to_file",
    ]


def test_render_mutmut_table_writes_each_value_in_toml_syntax():
    text = ncg.render_mutmut_table(
        {"flag_on": True, "flag_off": False, "n": 3, "x": 1.5, "s": "café", "l": ["a", 1]}
    )
    assert text == (
        "[tool.mutmut]\n"
        "flag_on = true\n"
        "flag_off = false\n"
        "n = 3\n"
        "x = 1.5\n"
        's = "café"\n'
        'l = ["a", 1]\n'
    )


def test_compose_pyproject_replaces_the_table_and_keeps_the_rest():
    head = '[tool.black]\nline-length = 100\n\n[tool.mutmut]\nold = 1\n\n[tool.other]\nk = "v"\n'
    table = ncg.mutmut_table(["scripts/"], "scripts/x.py", [], ["tests/t.py"])
    out = ncg.compose_pyproject(head, table)
    assert "old = 1" not in out
    assert out.startswith(
        '[tool.black]\nline-length = 100\n\n[tool.other]\nk = "v"\n\n[tool.mutmut]\n'
    )
    assert out.endswith("\n") and not out.endswith("\n\n")


def test_compose_pyproject_without_an_existing_table_appends_one_blank_line_apart():
    head = "[tool.black]\nline-length = 100\n\n\n"
    out = ncg.compose_pyproject(head, ncg.mutmut_table([], "a.py", [], []))
    assert out.startswith("[tool.black]\nline-length = 100\n\n[tool.mutmut]\n")


def test_mutmut_source_paths_are_sorted_directories_plus_a_top_level_gated_file():
    got = ncg.mutmut_source_paths(["scripts", "bin/", "tests"], "top.py")
    assert got == ["bin/", "scripts/", "top.py"]
    assert ncg.mutmut_source_paths(["scripts"], "scripts/x.py") == ["scripts/"]


def test_mutmut_also_copy_lists_directories_then_files_never_claude_or_own_paths():
    got = ncg.mutmut_also_copy(
        ["scripts/", "docs", ".claude", "tests", "audit/"],
        ["README.md", "pyproject.toml", "setup.cfg", "top.py"],
        ["scripts/", "top.py"],
    )
    assert got == ["audit/", "docs/", "README.md"]


def test_strip_tool_mutmut_removes_only_that_table():
    text = "[a]\nx = 1\n[tool.mutmut]\ny = 2\n[b]\nz = 3\n"
    assert ncg.strip_tool_mutmut(text) == "[a]\nx = 1\n[b]\nz = 3\n"
    text = "[tool.mutmut]\ny = 2\n[b]\nz = 3\n[c]\nw = 4\n"
    assert ncg.strip_tool_mutmut(text) == "[b]\nz = 3\n[c]\nw = 4\n"


def test_json_values_in_the_table_round_trip_through_tomllib():
    import tomllib

    table = ncg.mutmut_table(["a/"], "a/x.py", ["d/"], ["tests/t.py::é"])
    parsed = tomllib.loads(ncg.render_mutmut_table(table))["tool"]["mutmut"]
    assert parsed == json.loads(json.dumps(table))
