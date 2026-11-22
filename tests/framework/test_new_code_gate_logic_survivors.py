"""Cheap in-process pins for mutants that survived, or timed out, in the gate's own mutation run.

Condition 6 of ADR-2304 (section 2j, C6-3 b and c): a surviving mutant runs every test that reaches
its function, so a survivor on a function the end-to-end tests reach costs the whole measure suite,
and a timed-out mutant holds a worker for its whole CPU limit. Each test here is a millisecond
call of one pure function that fails on the mutant it names, so mutmut kills the mutant on the
first test it runs. None of them starts a process, a repository or a file.
"""

import ast
import hashlib
import re

import pytest

from scripts.framework import new_code_gate_logic as ncg
from scripts.framework import new_code_gate_shard as ncs

GATED = "scripts/oversight/validators/foo.py"


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path, monkeypatch):
    """A mutant that turns a computed path relative lands here, never in mutmut's cwd (RV3-7a)."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def drop_tmp_path_link_at_teardown(request, tmp_path):
    """Remove this test's `<name>current` link from the session's base temp once the test passed."""
    failed_before = request.session.testsfailed
    yield
    if request.session.testsfailed == failed_before:
        link = tmp_path.parent / (re.sub(r"\d+$", "", tmp_path.name) + "current")
        if link.is_symlink() and link.resolve() == tmp_path.resolve():
            link.unlink()


# --------------------------------------------------------------------------
# unquote_git_path: the loop must advance (a mutant that never does would hang a worker)
# --------------------------------------------------------------------------


class _CountingRegex:
    """Wraps the octal-escape pattern and fails the test, rather than spin, when the scan stalls."""

    def __init__(self, real, limit):
        self.real = real
        self.limit = limit
        self.positions = []

    def match(self, body, pos):
        self.positions.append(pos)
        assert len(self.positions) <= self.limit, "unquote_git_path stopped advancing"
        return self.real.match(body, pos)


def test_unquote_git_path_steps_one_character_at_a_time_through_plain_text(monkeypatch):
    counting = _CountingRegex(ncg.OCTAL_ESCAPE_RE, 12)
    monkeypatch.setattr(ncg, "OCTAL_ESCAPE_RE", counting)
    assert ncg.unquote_git_path('"abcd"') == "abcd"
    assert counting.positions == [0, 1, 2, 3]


def test_unquote_git_path_steps_past_an_escape_to_the_character_after_it(monkeypatch):
    counting = _CountingRegex(ncg.OCTAL_ESCAPE_RE, 12)
    monkeypatch.setattr(ncg, "OCTAL_ESCAPE_RE", counting)
    assert ncg.unquote_git_path('"a\\tb"') == "a\tb"
    assert counting.positions == [0, 1, 3]


# --------------------------------------------------------------------------
# selection_fields, parse_tree_modes, timeout_message
# --------------------------------------------------------------------------


def test_selection_is_not_truncated_at_exactly_the_cap_and_is_truncated_one_over():
    at_cap = [f"tests/t.py::t{i}" for i in range(ncg.MAX_SELECTED_TESTS)]
    fields = ncg.selection_fields("context", at_cap)
    assert fields["selected_tests_truncated"] is False
    assert fields["selected_tests_count"] == ncg.MAX_SELECTED_TESTS
    over = ncg.selection_fields("context", [*at_cap, "tests/t.py::extra"])
    assert over["selected_tests_truncated"] is True
    assert len(over["selected_tests"]) == ncg.MAX_SELECTED_TESTS


def test_parse_tree_modes_takes_the_mode_before_the_first_single_space():
    listing = "100644 blob aaa\ta.py\0 100755 blob bbb\tb.py\0"
    assert ncg.parse_tree_modes(listing) == {"a.py": "100644", "b.py": ""}


def test_timeout_message_orders_equal_totals_by_path_not_by_setup_seconds():
    text = ncg.timeout_message({}, {"b.py": (5.0, 1.0), "a.py": (5.0, 2.0)}, "mutation")
    assert text.index("a.py 5.0s") < text.index("b.py 5.0s")


# --------------------------------------------------------------------------
# parse_name_status
# --------------------------------------------------------------------------


def test_parse_name_status_skips_a_line_with_no_tab_and_reads_the_lines_after_it():
    parsed = ncg.parse_name_status("not a status line\nM\tscripts/a.py\n")
    assert parsed == [ncg.ChangedPath("M", "scripts/a.py", None, "changed")]


@pytest.mark.parametrize("status", ["R100", "R075", "C100", "C075"])
def test_parse_name_status_reads_the_old_path_of_a_rename_and_of_a_copy(status):
    parsed = ncg.parse_name_status(f"{status}\tscripts/old.py\tscripts/new.py\n")
    assert [(p.path, p.old_path) for p in parsed] == [("scripts/new.py", "scripts/old.py")]


def test_parse_name_status_gives_no_old_path_to_a_plain_status():
    parsed = ncg.parse_name_status("A\tscripts/new.py\n")
    assert parsed[0].old_path is None


# --------------------------------------------------------------------------
# sanitize_node_ids
# --------------------------------------------------------------------------


def test_unsafe_test_id_message_shows_the_id_cut_to_200_characters():
    bad = "--rootdir=" + "x" * 300
    with pytest.raises(ncg.GateError) as caught:
        ncg.sanitize_node_ids([bad])
    assert str(caught.value) == (
        f"unsafe test id in coverage contexts: {ncg.bound_text(repr(bad), 200)}"
    )
    assert len(ncg.bound_text(repr(bad), 200)) == 200


# --------------------------------------------------------------------------
# verdict_document
# --------------------------------------------------------------------------


def _verdict_inputs():
    rec = ncg.blank_file_record("scripts/a.py", "new")
    records = {"files": [rec], "internal_errors": [], "records_sha256": "measure-sha", "pr": 7}
    decision = ncg.decide(records, [], ncg.THRESHOLDS)
    return records, decision


def test_verdict_document_carries_its_own_digest_apart_from_the_measure_digest():
    records, decision = _verdict_inputs()
    doc = ncg.verdict_document(records, decision)
    assert doc["measure_records_sha256"] == "measure-sha"
    assert doc["records_sha256"] == ncg.records_sha256(doc["files"])
    assert doc["records_sha256"] != "measure-sha"


def test_verdict_document_keeps_the_record_envelope_and_adds_the_decision():
    records, decision = _verdict_inputs()
    doc = ncg.verdict_document(records, decision)
    assert doc["phase"] == "verdict" and doc["pr"] == 7
    assert doc["overall"] == decision["overall"] and doc["exit_code"] == decision["exit_code"]
    assert doc["files"][0]["outcome"] == "pass" and doc["files"][0]["fail_reasons"] == []


# --------------------------------------------------------------------------
# render_summary: the whole text, once for a table with details and once without
# --------------------------------------------------------------------------


def _summary_record(path, outcome, reasons=()):
    rec = ncg.blank_file_record(path, "new")
    rec.update(
        executed_gated=8,
        gated_statements=10,
        coverage_pct=80.0,
        mutants_total=4,
        mutants_killed=3,
        mutant_score_pct=75.0,
        selection_method="context",
        outcome=outcome,
        fail_reasons=[{"code": code, "message": message} for code, message in reasons],
    )
    return rec


HEADER = (
    "| File | Kind | Coverage (covered/gated) | Mutant score (killed/total) | Shards "
    "| Selection | Outcome | Reasons |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def test_summary_text_is_exactly_the_table_the_counts_and_the_detail_lines():
    failing = _summary_record("a.py", "fail", [("c1", "m1"), ("c2", "m2")])
    verdict = {"files": [failing], "overall": "fail", "internal_errors": []}
    assert ncg.render_summary(verdict) == (
        HEADER
        + "| a.py | new | 80.0% (8/10) | 75.0% (3/4) | - | context | fail | c1, c2 |\n"
        + "\n1 gated file(s): 0 pass, overall fail.\n"
        + "\n- m1\n- m2\n"
    )


def test_summary_text_counts_only_files_that_passed_and_has_no_detail_block_without_reasons():
    files = [_summary_record("a.py", "pass"), _summary_record("b.py", "fail")]
    verdict = {"files": files, "overall": "fail", "internal_errors": []}
    assert ncg.render_summary(verdict) == (
        HEADER
        + "| a.py | new | 80.0% (8/10) | 75.0% (3/4) | - | context | pass |  |\n"
        + "| b.py | new | 80.0% (8/10) | 75.0% (3/4) | - | context | fail |  |\n"
        + "\n2 gated file(s): 1 pass, overall fail.\n"
    )


# --------------------------------------------------------------------------
# strip_tool_mutmut and strip_no_mutate_pragmas
# --------------------------------------------------------------------------


def test_strip_tool_mutmut_keeps_everything_before_and_after_the_table():
    text = "a = 1\n[tool.x]\nb = 2\n[tool.mutmut]\nc = 3\n# note\n[tool.y]\nd = 4\n"
    assert ncg.strip_tool_mutmut(text) == "a = 1\n[tool.x]\nb = 2\n[tool.y]\nd = 4\n"


def test_strip_no_mutate_pragmas_refuses_when_a_pragma_survives_the_cut(monkeypatch):
    monkeypatch.setattr(ncg, "_pragma_cuts", lambda source: [(0, 0, 0)])
    with pytest.raises(ncg.GateError) as caught:
        ncg.strip_no_mutate_pragmas("x = 1  # pragma: no mutate\n")
    assert str(caught.value) == "a no-mutate pragma survived stripping"


def test_strip_no_mutate_pragmas_refuses_when_the_cut_changed_more_than_comments(monkeypatch):
    monkeypatch.setattr(ncg, "_pragma_cuts", lambda source: [])
    seen = iter(["after", "before"])
    monkeypatch.setattr(ncg, "_tokens_without_comments", lambda text: next(seen))
    with pytest.raises(ncg.GateError) as caught:
        ncg.strip_no_mutate_pragmas("x = 1\n")
    assert str(caught.value) == "stripping no-mutate pragmas changed more than comments"


# --------------------------------------------------------------------------
# ordered_reasons and threshold_reasons
# --------------------------------------------------------------------------


def test_ordered_reasons_puts_a_code_outside_the_fail_order_after_every_known_code():
    unknown = {"code": "zz_unknown", "message": "u"}
    known = {"code": ncg.FAIL_ORDER[-1], "message": "k"}
    first = {"code": ncg.FAIL_ORDER[0], "message": "f"}
    assert ncg.ordered_reasons([unknown, known, first]) == [first, known, unknown]


def test_threshold_reasons_name_the_path_the_floored_percent_and_the_counts():
    record = ncg.blank_file_record("scripts/a.py", "new")
    record.update(
        gated_statements=10,
        executed_gated=7,
        mutation_ran=True,
        mutants_total=3,
        mutants_killed=2,
    )
    got = ncg.threshold_reasons(record, {"coverage": 80, "mutant_score": 75})
    assert got == [
        {
            "code": "coverage_below_threshold",
            "message": "scripts/a.py: gated line coverage 70.0% is below 80% (7/10)",
        },
        {
            "code": "mutant_score_below_threshold",
            "message": "scripts/a.py: mutant score 66.6% is below 75% (2/3)",
        },
    ]


# --------------------------------------------------------------------------
# parse_repo_copy_collect, static_path_load_findings, parse_short_summary, shell_gate
# --------------------------------------------------------------------------


def test_repo_copy_collect_names_unparseable_output_exactly():
    with pytest.raises(ncg.GateError) as caught:
        ncg.parse_repo_copy_collect(0, "tests/a.py::t\nnot a node id\n")
    assert str(caught.value) == "repo_copy collection failed: unparseable output"


def test_static_path_load_scan_goes_on_to_the_next_importer_after_one_that_does_not_parse():
    sources = {"tests/a_broken.py": "def (:\n", "tests/b.py": "import foo\n"}
    found = ncg.static_path_load_findings(GATED, sources)
    assert [(f["importer"], f["via"]) for f in found] == [("tests/b.py", "static:bare_import")]


SUMMARY = "=== short test summary info ===\n{}\n=== 1 failed ===\n"


def test_parse_short_summary_cuts_at_the_first_separator_and_keeps_spaces_in_the_id():
    lines = "FAILED tests/x.py::t[a b] - AssertionError: one - two"
    assert ncg.parse_short_summary(SUMMARY.format(lines)) == ["tests/x.py::t[a b]"]


def test_parse_short_summary_of_a_line_with_no_message_is_the_whole_id():
    assert ncg.parse_short_summary(SUMMARY.format("ERROR tests/x.py::t[a b]")) == [
        "tests/x.py::t[a b]"
    ]


def test_shell_gate_record_has_the_exempt_key_set_to_none_when_not_exempt():
    record, reasons = ncg.shell_gate("scripts/a.sh", False, [], [], [])
    assert record == {
        "exempt": None,
        "base_count": 0,
        "head_count": 0,
        "counted_on_changed_lines": [],
    }
    assert reasons == []


# --------------------------------------------------------------------------
# new_code_gate_shard: _assignment_error and _attempt_problem
# --------------------------------------------------------------------------


def _shard_entry(**override):
    entry = {
        "index": 1,
        "est_mutation_ms": 5,
        "est_fixed_ms": 2,
        "members": [{"path": "a.py", "names": ["n"]}],
    }
    entry.update(override)
    return entry


def test_a_well_formed_assignment_has_no_error():
    assert ncs._assignment_error([_shard_entry()]) is None
    assert ncs._assignment_error([]) is None


def test_an_assignment_that_is_not_a_list_is_named_as_such():
    assert ncs._assignment_error({"index": 1}) == "assignment is not a list"


@pytest.mark.parametrize(
    "override",
    [
        {"index": "1"},
        {"est_mutation_ms": -1},
        {"est_fixed_ms": None},
        {"members": "a.py"},
        {"members": ["a.py"]},
        {"members": [{"path": 3, "names": ["n"]}]},
        {"members": [{"path": "a.py", "names": [3]}]},
        {"members": [{"path": "a.py"}]},
    ],
)
def test_each_wrong_field_of_an_assignment_entry_is_the_wrong_shape(override):
    assert ncs._assignment_error([_shard_entry(**override)]) == (
        "assignment entry has the wrong shape"
    )


def test_an_assignment_entry_that_is_not_a_dict_is_the_wrong_shape():
    assert ncs._assignment_error(["x"]) == "assignment entry has the wrong shape"


def test_a_run_with_no_attempt_number_accepts_no_attempt_value_and_names_one_that_is_set():
    assert ncs._attempt_problem(None, None, None) is None
    assert ncs._attempt_problem(3, None, None) == "run_attempt is set but this run has none"


def test_an_attempt_may_equal_zero_when_the_plan_recorded_none_and_the_message_shows_the_value():
    assert ncs._attempt_problem(0, None, 3) is None
    assert ncs._attempt_problem(5, None, 3) == "run_attempt 5 is not an integer from 0 to 3"
    assert ncs._attempt_problem(1, 2, 3) == "run_attempt 1 is not an integer from 2 to 3"


# --------------------------------------------------------------------------
# Summary helpers: _fraction, _cell, _not_final_lines, _runner_minutes_line, _shard_lines
# --------------------------------------------------------------------------


def test_a_fraction_with_no_percent_is_the_text_n_a_and_one_with_a_percent_shows_its_counts():
    assert ncg._fraction(None, 1, 2) == "n/a"
    assert ncg._fraction(50.0, 1, 2) == "50.0% (1/2)"


def test_cell_leaves_a_capital_x_alone_while_escaping_the_markdown_characters():
    assert ncg._cell("aXb|c") == "aXb\\|c"


def test_a_file_whose_score_is_final_lists_no_partial_shard_lines():
    rec = {
        "path": "a.py",
        "mutants_total": 4,
        "shards": [{"index": 1, "status": "complete", "killed": 3, "total": 4}],
    }
    assert ncg._not_final_lines(rec) == []


def test_a_file_with_no_final_score_lists_each_shard_with_its_counts_or_n_a():
    rec = {
        "path": "a|b.py",
        "mutants_total": None,
        "shards": [
            {"index": 1, "status": "complete", "killed": 3, "total": 4},
            {"index": 2, "status": "missing", "killed": None, "total": None},
        ],
    }
    assert ncg._not_final_lines(rec) == [
        "- a\\|b.py: shard 1 (complete): 3/4 killed (not final)",
        "- a\\|b.py: shard 2 (missing): n/a (not final)",
    ]


SHARDS = {
    "N": 2,
    "capped": True,
    "N_max": 8,
    "T_minutes": 15,
    "W_ci_minutes": 40.5,
    "per_shard": [
        {"index": 1, "status": "complete", "files": ["a.py", "b.py"], "est_mutation_ms": 11}
        | {"est_fixed_ms": 5, "job_seconds": 7, "run_attempt": 1},
        {"index": 2, "status": "missing", "files": [], "est_mutation_ms": 12}
        | {"est_fixed_ms": 0, "job_seconds": None, "run_attempt": None},
    ],
}


def test_the_shards_block_is_exactly_the_heading_the_table_and_the_runner_minutes_line():
    verdict = {"shards": SHARDS, "plan_job_seconds": None, "runner_minutes_total": 12.5}
    assert ncg._shard_lines(verdict) == [
        "",
        "Shards: 2, capped true, estimated work 40.5 CI-min exceeds 8 x 15; running 2 shards.",
        "",
        "| Shard | Status | Files | est_mutation_ms | est_fixed_ms | job_seconds | Attempt |",
        "|---|---|---|---|---|---|---|",
        "| 1 | complete | a.py, b.py | 11 | 5 | 7 | 1 |",
        "| 2 | missing | - | 12 | 0 | n/a | None |",
        "",
        f"Runner minutes: 12.5 ({ncg.RUNNER_MINUTES_LABEL})",
    ]


def test_runner_minutes_with_no_total_names_every_phase_that_lacks_a_job_start_time():
    verdict = {"shards": SHARDS, "plan_job_seconds": None, "runner_minutes_total": None}
    assert ncg._runner_minutes_line(SHARDS, verdict) == (
        "Runner minutes: n/a (no job-start time for: plan, shard 2)"
    )


def test_runner_minutes_with_no_total_and_nothing_lacking_says_unknown():
    shards = {"per_shard": [{"index": 1, "job_seconds": 3}]}
    verdict = {"plan_job_seconds": 4, "runner_minutes_total": None}
    assert ncg._runner_minutes_line(shards, verdict) == (
        "Runner minutes: n/a (no job-start time for: unknown)"
    )


# --------------------------------------------------------------------------
# _loaded_name, _call_name, _gated_statements
# --------------------------------------------------------------------------


def _first_node(text):
    node = ast.parse(text).body[0]
    return node.value if isinstance(node, ast.Expr) else node


NAMES = {"scripts/oversight/validators/foo.py", "foo.py", "foo"}


@pytest.mark.parametrize(
    "call",
    [
        'load_module_from_path("m", ROOT / "validators" / "foo.py")',
        'spec_from_file_location("m", "x/y/foo.py")',
        'spec_from_file_location("m", "x\\\\y\\\\foo.py")',
    ],
)
def test_a_loader_call_naming_the_file_in_any_path_segment_is_reported_by_its_loader(call):
    node = _first_node(call)
    loaded, kind = ncg._loaded_name(node, NAMES, "foo", False)
    assert kind == ncg._call_name(node) and kind in ncg.LOADER_NAMES
    assert loaded


def test_a_loader_call_matches_when_only_the_whole_literal_is_a_known_name():
    node = _first_node('spec_from_file_location("m", "x/y")')
    assert ncg._loaded_name(node, {"x/y"}, "foo", False) == ("m", "spec_from_file_location")


def test_a_loader_call_matches_when_only_one_segment_of_a_literal_is_a_known_name():
    node = _first_node('spec_from_file_location("m", "x/y")')
    assert ncg._loaded_name(node, {"y"}, "foo", False) == ("m", "spec_from_file_location")


@pytest.mark.parametrize("text", ["import foo.helpers", "import foo"])
def test_a_bare_import_of_a_submodule_of_the_stem_is_reported_under_its_full_name(text):
    node = _first_node(text)
    assert ncg._loaded_name(node, NAMES, "foo", True) == (text.split()[1], "bare_import")


@pytest.mark.parametrize("text", ["from foo.helpers import x", "from foo import x"])
def test_a_bare_from_import_of_a_submodule_of_the_stem_is_reported_under_its_module_name(text):
    node = _first_node(text)
    assert ncg._loaded_name(node, NAMES, "foo", True) == (text.split()[1], "bare_import")


def test_a_node_that_loads_nothing_is_reported_as_an_empty_name_and_no_kind():
    assert ncg._loaded_name(_first_node("x = 1"), NAMES, "foo", True) == ("", None)
    assert ncg._loaded_name(_first_node("import bar"), NAMES, "foo", True) == ("", None)


def test_the_name_of_a_call_is_its_attribute_or_name_and_empty_for_anything_else():
    assert ncg._call_name(_first_node("a.b()")) == "b"
    assert ncg._call_name(_first_node("f()")) == "f"
    assert ncg._call_name(_first_node("f()()")) == ""


def test_a_decorated_statement_is_gated_by_its_first_decorator_line_alone():
    tree = ast.parse("@deco\ndef f():\n    pass\n")
    (found,) = [s for s in ncg._gated_statements(tree, {1}) if isinstance(s, ast.FunctionDef)]
    assert found.name == "f"
    assert [s for s in ncg._gated_statements(tree, {2}) if isinstance(s, ast.FunctionDef)] == [
        found
    ]


# --------------------------------------------------------------------------
# The AST helpers behind decision logic and the unmutatable-line rule
# --------------------------------------------------------------------------


def _chain_of(source, pick):
    """The tree, the parent map, and the (child, parent) chain from the node `pick(tree)` returns."""
    tree = ast.parse(source)
    parents = ncg._parent_map(tree)
    node = pick(tree)
    return tree, parents, node, ncg._chain(node, parents)


def test_an_annotation_a_decorator_and_a_return_type_are_definition_time_positions():
    _, _, deco, chain = _chain_of(
        "@deco(1)\ndef f(): pass\n", lambda t: t.body[0].decorator_list[0]
    )
    assert ncg._is_definition_time(chain, chain[0][1]) is True
    _, _, ret, chain = _chain_of("def f() -> str: pass\n", lambda t: t.body[0].returns)
    assert ncg._is_definition_time(chain, chain[0][1]) is True
    _, _, ann, chain = _chain_of(
        "def f(x: int): pass\n", lambda t: t.body[0].args.args[0].annotation
    )
    assert ncg._is_definition_time(chain, chain[0][1]) is True


def test_a_node_in_a_body_is_not_definition_time_and_neither_is_one_past_the_outermost_def():
    _, _, stmt, chain = _chain_of("def f():\n    x = 1\n", lambda t: t.body[0].body[0])
    assert ncg._is_definition_time(chain, chain[0][1]) is False
    unrelated = ast.parse("y = 2\n").body[0]
    assert ncg._is_definition_time(chain, unrelated) is False


def test_a_node_inside_the_arguments_of_len_is_in_a_never_mutate_call_even_past_other_parents():
    _, _, node, chain = _chain_of("len(a + b)\n", lambda t: t.body[0].value.args[0].left)
    assert ncg._in_never_mutate_call(chain) is True


def test_a_node_in_another_call_or_a_method_call_is_not_in_a_never_mutate_call():
    _, _, node, chain = _chain_of("foo(x)\n", lambda t: t.body[0].value.args[0])
    assert ncg._in_never_mutate_call(chain) is False
    _, _, node, chain = _chain_of("obj.meth(x)\n", lambda t: t.body[0].value.args[0])
    assert ncg._in_never_mutate_call(chain) is False


@pytest.mark.parametrize(
    "source,expected",
    [
        ("class A(Enum): pass\n", True),
        ("class A(enum.IntEnum): pass\n", True),
        ("class A(Base): pass\n", False),
        ("class A(mod.Base): pass\n", False),
        ("class A: pass\n", False),
    ],
)
def test_a_class_is_an_enum_when_a_base_is_named_like_one_by_name_or_attribute(source, expected):
    assert ncg._is_enum_class(ast.parse(source).body[0]) is expected


def test_a_node_contains_itself_and_nothing_that_starts_before_or_ends_after_it():
    first, second = ast.parse("a = 1\nb = 2\n").body
    assert ncg._contains(first, first) is True
    assert ncg._contains(first, first.value) is True
    assert ncg._contains(first, second) is False
    assert ncg._contains(second, first) is False


def test_the_owner_of_a_statement_is_itself_only_when_it_is_gated():
    stmt = ast.parse("a = 1\n").body[0]
    assert ncg._owner_of(stmt, [stmt]) is stmt
    assert ncg._owner_of(stmt, []) is None


def test_the_owner_of_an_expression_is_the_innermost_gated_statement_that_holds_it():
    tree = ast.parse("if a: b = 1\n")
    compound = tree.body[0]
    inner = compound.body[0]
    name = inner.targets[0]
    assert ncg._owner_of(name, [compound, inner]) is inner
    assert ncg._owner_of(name, [inner, compound]) is inner


def test_an_expression_on_a_line_shared_by_two_statements_belongs_to_the_one_that_holds_it():
    first, second = ast.parse("a = 1; b = 2\n").body
    name = second.targets[0]
    assert ncg._owner_of(name, [first, second]) is second


def test_a_module_level_main_guard_is_its_own_carve_out_when_no_chain_is_given():
    guard = ast.parse('if __name__ == "__main__":\n    main()\n').body[0]
    assert ncg._carve_out_for(guard, []) == "main_guard"


# --------------------------------------------------------------------------
# Hashing, pyproject composition, source paths, coverage fields, the verdict
# --------------------------------------------------------------------------


def test_the_canonical_hash_is_over_sorted_compact_ascii_json_without_the_unhashed_fields():
    value = {"b": [1, {"seconds": 9, "z": 1}], "a": "\u00e9", "seconds": 3}
    expected = hashlib.sha256(b'{"a":"\\u00e9","b":[1,{"z":1}]}').hexdigest()
    assert ncg.canonical_sha256(value) == expected


def test_a_pyproject_with_a_mutmut_table_gets_it_replaced_after_one_blank_line():
    head = '[project]\nname = "x"   \n\n[tool.mutmut]\nold = 1\n\n\n'
    out = ncg.compose_pyproject(head, {"only_mutate": ["a.py"]})
    assert out.startswith('[project]\nname = "x"   \n\n[tool.mutmut]')
    assert ncg.tomllib.loads(out)["tool"]["mutmut"] == {"only_mutate": ["a.py"]}


def test_composing_a_pyproject_keeps_a_trailing_x_of_the_text_before_the_table():
    head = '[project]\nname = "x"\n# X\n\n[tool.mutmut]\nold = 1\n'
    assert "# X\n\n[tool.mutmut]" in ncg.compose_pyproject(head, {"only_mutate": ["a.py"]})


def test_a_pyproject_with_no_tool_table_at_all_fails_the_round_trip_by_name():
    with pytest.raises(ncg.GateError) as caught:
        ncg.compose_pyproject('[project]\nname = "x"\n', {"only_mutate": ["a.py"]})
    assert str(caught.value) == "generated mutmut config failed round-trip"


def test_a_composed_pyproject_that_does_not_round_trip_is_refused(monkeypatch):
    monkeypatch.setattr(ncg, "render_mutmut_table", lambda table: "other = 1\n")
    with pytest.raises(ncg.GateError) as caught:
        ncg.compose_pyproject("[tool.mutmut]\nold = 1\n", {"only_mutate": ["a.py"]})
    assert str(caught.value) == "generated mutmut config failed round-trip"


def test_the_also_copy_list_drops_source_tests_and_claude_dirs_however_they_are_spelled():
    got = ncg.mutmut_also_copy(
        ["docs/", "tests/", ".claude/", "scripts/", "tests", "dirX/"],
        ["pyproject.toml", "setup.cfg", "Makefile", "scripts"],
        ["scripts/"],
    )
    assert got == ["dirX/", "docs/", "Makefile"]


def test_the_source_paths_are_the_sorted_top_dirs_without_tests_plus_a_top_level_gated_file():
    assert ncg.mutmut_source_paths(["scripts/", "tests", "docs/"], "a.py") == [
        "a.py",
        "docs/",
        "scripts/",
    ]
    assert ncg.mutmut_source_paths(["scripts"], "scripts/x.py") == ["scripts/"]
    assert ncg.mutmut_source_paths(["dirX/"], "a/b.py") == ["dirX/"]


def test_a_file_with_nothing_gated_has_zero_counts_and_no_percentage_whatever_was_executed():
    assert ncg.coverage_fields(0, 5) == {
        "gated_statements": 0,
        "executed_gated": 0,
        "coverage_pct": None,
    }


def test_an_upstream_error_becomes_an_internal_error_carrying_its_message():
    verdict = ncg.decide({"files": [], "internal_errors": None}, [], {}, ["tests failed"])
    assert verdict["internal_errors"] == [{"code": "upstream", "message": "tests failed"}]
    assert verdict["exit_code"] == 3


def test_a_file_whose_every_reason_is_ruling_eligible_is_excepted_when_a_ruling_applies(
    monkeypatch,
):
    monkeypatch.setattr(ncg, "ruling_applies", lambda record, rulings: True)
    monkeypatch.setattr(ncg, "threshold_reasons", lambda record, thresholds: [])
    record = ncg.blank_file_record("scripts/a.py", "new")
    record["fail_reasons"] = [ncg.fail_reason(c, "m") for c in sorted(ncg.RULING_ELIGIBLE)]
    verdict = ncg.decide({"files": [record]}, [{}], {})
    assert verdict["files"][0]["outcome"] == "excepted"


def test_the_changed_original_lines_are_found_without_difflibs_autojunk_heuristic():
    original = "x\n" * 300
    mutated = "x\n" * 150 + "y\n" + "x\n" * 150
    assert ncg.changed_original_lines(original, mutated) == [151]


def test_a_function_prefix_may_be_at_most_the_key_limit_and_must_match_the_shape():
    shape = "a.x"
    assert ncg.check_function_prefix(shape + "b" * (ncg.MAX_KEY_CHARS - 3)) is True
    assert ncg.check_function_prefix(shape + "b" * (ncg.MAX_KEY_CHARS - 2)) is False
    assert ncg.check_function_prefix("not a prefix!") is False


def test_a_mutant_key_may_be_at_most_the_key_limit_and_must_match_the_shape():
    tail = "__mutmut_1"
    key = "a.x" + "b" * (ncg.MAX_KEY_CHARS - 3 - len(tail)) + tail
    assert len(key) == ncg.MAX_KEY_CHARS and ncg.check_mutant_key(key) is True
    assert ncg.check_mutant_key("a" + key) is False
    assert ncg.check_mutant_key("not a key") is False


def test_a_decision_node_with_no_gated_owner_is_skipped_and_the_search_goes_on():
    findings = ncg.decision_logic_findings("if a:\n    pass\nif b:\n    pass\n", {3})
    assert [f["line"] for f in findings] == [3]


def test_a_module_level_decision_has_no_unmutatable_reason_and_a_function_one_has():
    module = ncg.decision_logic_findings("if a:\n    pass\n", {1})
    assert module[0]["unmutatable_reason"] is None and module[0]["carve_out"] is None
    inside = ncg.decision_logic_findings("def f():\n    return 1 if a else 2\n", {2})
    assert inside[0]["carve_out"] is None and inside[0]["region"] == "function"


def test_a_path_is_measured_when_its_top_directory_is_the_top_of_a_measured_root():
    assert ncg.in_measured_surface("scripts/a.py", ["scripts/framework"]) is True
    assert ncg.in_measured_surface("docs/a.py", ["scripts/framework", "tests"]) is False


@pytest.mark.parametrize("count,truncated", [(5000, False), (5001, True)])
def test_gated_lines_and_findings_are_cut_at_the_limit_and_flagged_only_above_it(count, truncated):
    lines = ncg.gated_lines_fields(list(range(count)))
    assert len(lines["gated_lines"]) == 5000 and lines["gated_lines_truncated"] is truncated
    findings = ncg.findings_fields([{"line": n} for n in range(count)])
    assert len(findings["decision_logic_findings"]) == 5000
    assert findings["decision_logic_findings_truncated"] is truncated


def test_a_node_id_with_a_pipe_in_its_parameters_loses_only_its_phase_suffix():
    contexts = ["tests/t.py::a[x|y]|run", "tests/t.py::a[x|y]|setup", "", "tests/t.py::b|teardown"]
    assert ncg.contexts_to_node_ids(contexts) == ["tests/t.py::a[x|y]", "tests/t.py::b"]


def test_an_unknown_mutant_status_is_refused_by_name():
    with pytest.raises(ncg.GateError) as caught:
        ncg.classify_statuses({"k": "weird"}, ["k"])
    assert str(caught.value) == "unexpected mutant status"


def test_a_blank_record_starts_every_count_flag_and_method_at_its_neutral_value():
    record = ncg.blank_file_record("scripts/a.py", "new")
    assert record["gated_lines_truncated"] is False and record["executed_gated"] == 0
    assert record["mutants_killed"] == 0 and record["selected_tests_count"] == 0
    assert record["decision_logic_findings_truncated"] is False
    assert record["selected_tests_truncated"] is False and record["selection_method"] == "none"
