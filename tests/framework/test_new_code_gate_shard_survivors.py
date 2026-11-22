"""Cheap in-process pins for mutants of `new_code_gate_shard` that survived in its own run.

Condition 6 of ADR-2304 (section 2j, C6-3 c). The plan and fragment documents are dictionaries,
so each test calls one function and compares its text exactly. The fixtures are the ones
`test_new_code_gate_shard.py` builds its own cases from.
"""

import copy
import re

import pytest

from scripts.framework import new_code_gate_logic as ncg
from scripts.framework import new_code_gate_shard as ncs
from tests.framework.test_new_code_gate_shard import (
    BIND,
    CASES,
    CORE_MS,
    band_plan,
    codes,
    do_merge,
    finish_plan,
    fragment,
    fragment_set,
    plan_file,
    rehash,
    uniform,
)


@pytest.fixture(autouse=True)
def drop_tmp_path_link_at_teardown(request, tmp_path):
    """Remove this test's `<name>current` link from the session's base temp once the test passed."""
    failed_before = request.session.testsfailed
    yield
    if request.session.testsfailed == failed_before:
        link = tmp_path.parent / (re.sub(r"\d+$", "", tmp_path.name) + "current")
        if link.is_symlink() and link.resolve() == tmp_path.resolve():
            link.unlink()


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path, monkeypatch):
    """A mutant that turns a computed path relative lands here, never in mutmut's cwd (RV3-7a)."""
    monkeypatch.chdir(tmp_path)


MESSAGES = {
    "missing": ("fragment_missing", "shard 2 of 3: no fragment"),
    "duplicate": (
        "fragment_duplicate",
        "shard 2 of 3 has 2 fragments: new-code-fragment-02-of-3, new-code-fragment-2-of-3",
    ),
    "index-0": ("fragment_out_of_range", "new-code-fragment-0-of-3: shard index is not in 1..3"),
    "index-n-plus-1": (
        "fragment_out_of_range",
        "new-code-fragment-4-of-3: shard index is not in 1..3",
    ),
    "extra-entry": ("fragment_extra", "unexpected entry: stray"),
    "name-n-differs": (
        "fragment_extra",
        "new-code-fragment-1-of-5 is not for this plan's 3 shards",
    ),
    "unreadable": ("fragment_unreadable", "shard 2 of 3: fragment is not an object"),
    "wrong-schema": ("fragment_unreadable", "shard 2 of 3: fragment has the wrong schema"),
    "gated-sha": ("fragment_not_bound", "shard 2 of 3: gated_sha differ from the plan's"),
    "pr": ("fragment_not_bound", "shard 2 of 3: pr differ from the plan's"),
    "name-index": (
        "fragment_name_mismatch",
        "shard 2 of 3: new-code-fragment-2-of-3 holds index 3",
    ),
    "two-fragments": (
        "mutant_in_two_fragments",
        "shard 2: scripts.framework.f0.x_f00__mutmut_1 also has a result in shard 1",
    ),
    "stored-counts": (
        "fragment_count_mismatch",
        "shard 2 states killed/total 0/10, its mutant statuses give 10/10",
    ),
}


@pytest.mark.parametrize(
    "label,inject,code,shard", [c for c in CASES if c[0] in MESSAGES], ids=lambda v: str(v)[:20]
)
def test_each_merge_problem_carries_its_exact_message_code_and_shard(label, inject, code, shard):
    plan = band_plan(3)
    frags = fragment_set(plan)
    inject(plan, frags)
    _, problems = do_merge(plan, frags)
    expected_code, message = MESSAGES[label]
    hits = [p for p in problems if p["code"] == expected_code]
    assert [p["message"] for p in hits][0] == message
    assert hits[0].get("shard") == shard


def test_a_fragment_that_is_a_refusal_text_is_reported_under_its_own_name_with_that_text():
    plan = band_plan(3)
    frags = fragment_set(plan)
    frags["new-code-fragment-2-of-3"] = "must be a directory holding exactly the fragment"
    _, problems = do_merge(plan, frags)
    extra = [p for p in problems if p["code"] == "fragment_extra"]
    assert [p["message"] for p in extra] == [
        "new-code-fragment-2-of-3: must be a directory holding exactly the fragment"
    ]


def test_a_missing_shard_is_marked_missing_and_an_invalid_one_invalid_in_the_summary():
    plan = band_plan(3)
    frags = fragment_set(plan)
    del frags["new-code-fragment-1-of-3"]
    frags["new-code-fragment-2-of-3"]["status"] = "timeout"
    records, _ = do_merge(plan, frags)
    by_index = {s["index"]: s["status"] for s in records["shards"]["per_shard"]}
    assert by_index == {1: "missing", 2: "invalid", 3: "complete"}


def test_the_shard_job_result_is_named_with_the_shards_that_have_problems_or_without_any():
    plan = band_plan(3)
    frags = fragment_set(plan)
    del frags["new-code-fragment-2-of-3"]
    _, problems = do_merge(plan, frags, shard_result="failure")
    failing = [p for p in problems if p["code"] == "shard_job_not_successful"]
    assert [p["message"] for p in failing] == ["shard job result failure; shard(s) 2"]
    two = fragment_set(plan)
    del two["new-code-fragment-1-of-3"]
    del two["new-code-fragment-3-of-3"]
    _, problems = do_merge(plan, two, shard_result="cancelled")
    failing = [p for p in problems if p["code"] == "shard_job_not_successful"]
    assert [p["message"] for p in failing] == ["shard job result cancelled; shard(s) 1, 3"]
    _, problems = do_merge(plan, fragment_set(plan), shard_result="failure")
    failing = [p for p in problems if p["code"] == "shard_job_not_successful"]
    assert [p["message"] for p in failing] == [
        "shard job result failure; no fragment identifies the failing shard"
    ]


def test_an_unreadable_plan_is_finished_with_the_shard_result_it_was_given():
    _, problems = do_merge(None, {}, shard_result="failure")
    last = problems[-1]
    assert last["code"] == "shard_job_not_successful"
    assert last["message"].startswith("shard job result failure; ")


def test_a_shard_that_ended_in_internal_error_is_reported_per_entry_with_code_message_and_file():
    plan = band_plan(3)
    frags = fragment_set(plan)
    doc = frags["new-code-fragment-2-of-3"]
    doc["status"] = "internal_error"
    doc["internal_errors"] = [
        {"code": "boom", "message": "it broke", "file": "scripts/a.py"},
        {"file": 5},
    ]
    rehash(doc)
    _, problems = do_merge(plan, frags)
    found = [p for p in problems if p["code"] == "shard_internal_error"]
    assert found == [
        {
            "code": "shard_internal_error",
            "message": "shard 2: boom: it broke",
            "shard": 2,
            "file": "scripts/a.py",
        },
        {
            "code": "shard_internal_error",
            "message": "shard 2: internal_error: no detail",
            "shard": 2,
        },
    ]


def test_a_shard_that_ended_in_internal_error_with_no_entries_is_still_one_problem():
    plan = band_plan(3)
    frags = fragment_set(plan)
    doc = frags["new-code-fragment-2-of-3"]
    doc["status"] = "internal_error"
    rehash(doc)
    _, problems = do_merge(plan, frags)
    found = [p for p in problems if p["code"] == "shard_internal_error"]
    assert [p["message"] for p in found] == ["shard 2: internal_error: no detail"]


@pytest.mark.parametrize(
    "doc,message",
    [
        ("text", "fragment is not an object"),
        ({"schema": "other"}, "fragment has the wrong schema"),
    ],
)
def test_a_fragment_that_is_not_an_object_or_has_another_schema_says_which(doc, message):
    assert ncs.fragment_shape_error(doc) == message


def good_fragment():
    plan = band_plan(3)
    return fragment(plan, 1)


@pytest.mark.parametrize(
    "mangle,message",
    [
        (
            lambda d: d.update(job_seconds="slow"),
            "fragment is missing a field or has one of the wrong type",
        ),
        (
            lambda d: d.update(seconds="slow"),
            "fragment is missing a field or has one of the wrong type",
        ),
        (lambda d: d["files"][0].update(killed=-1), "a fragment file entry has the wrong shape"),
        (lambda d: d["files"].append(dict(d["files"][0])), "a fragment lists a file twice"),
    ],
)
def test_each_malformed_fragment_part_is_named_in_the_shape_error(mangle, message):
    doc = good_fragment()
    assert ncs.fragment_shape_error(doc) is None
    mangle(doc)
    assert ncs.fragment_shape_error(doc) == message


def test_a_fragment_with_a_null_job_time_is_readable():
    doc = good_fragment()
    doc["job_seconds"] = None
    assert ncs.fragment_shape_error(doc) is None


def test_the_one_shard_summary_lists_each_file_its_reasons_and_each_internal_error():
    doc = good_fragment()
    first, second = doc["files"][0], dict(doc["files"][0], path="scripts/b.py")
    second.update(
        finished=False,
        fail_reasons=[
            {"code": "mutation_timeout", "message": "m"},
            {"code": "path_loaded_module", "message": "m"},
        ],
    )
    doc["files"] = [first, second]
    doc["internal_errors"] = [{"code": "c", "message": "m"}]
    text = ncs.fragment_summary(doc)
    killed, total, assigned = first["killed"], first["total"], first["assigned"]
    assert text == (
        f"shard 1 of 3: complete\n"
        f"- {first['path']}: {killed}/{total} killed of {assigned} assigned\n"
        f"- scripts/b.py: {killed}/{total} killed of {assigned} assigned (not finished); "
        f"mutation_timeout; path_loaded_module\n"
        f"- c: m\n"
    )


def test_a_summary_of_a_fragment_with_no_files_still_ends_in_one_newline():
    doc = good_fragment()
    doc["files"] = []
    assert ncs.fragment_summary(doc) == "shard 1 of 3: complete\n"


@pytest.mark.parametrize(
    "rec,message",
    [
        ("x", "a plan file entry is not an object"),
        ({}, None),
    ],
)
def test_a_plan_file_entry_that_is_not_an_object_or_lacks_fields_is_refused_by_name(rec, message):
    got = ncs._plan_file_error(rec)
    if message is not None:
        assert got == message
    else:
        names = sorted(set(ncg.FILE_FIELDS) | set(ncs.PLAN_FILE_EXTRA))
        assert got == "a plan file entry lacks " + ", ".join(names)


def test_a_complete_plan_file_entry_with_a_wrong_type_has_the_wrong_shape():
    rec = plan_file("scripts/a.py", [("scripts.a.x_f__mutmut_1", 5)])
    assert ncs._plan_file_error(rec) is None
    rec["to_shards"] = "yes"
    assert ncs._plan_file_error(rec) == "a plan file entry has the wrong shape"


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, True),
        ({"stage": "s", "node_ids": [], "summary_lines": [], "output_tail": ""}, True),
        ({"stage": 1, "node_ids": [], "summary_lines": [], "output_tail": ""}, False),
        ({"stage": "s", "node_ids": "x", "summary_lines": [], "output_tail": ""}, False),
        ({"stage": "s", "node_ids": [], "summary_lines": "x", "output_tail": ""}, False),
        ({"stage": "s", "node_ids": [], "summary_lines": [], "output_tail": 1}, False),
        ("x", False),
    ],
)
def test_an_isolation_failure_needs_every_field_to_be_the_right_type(value, expected):
    assert ncs._isolation_ok(value) is expected


@pytest.mark.parametrize(
    "value,expected",
    [({}, True), ({"a": 1}, True), ({"a": -1}, False), ({1: 1}, False), ([], False)],
)
def test_a_count_map_is_a_dict_of_text_keys_to_counts(value, expected):
    assert ncs._is_count_map(value) is expected


def test_a_file_with_no_gated_mutants_costs_nothing_per_mutant():
    cost = ncs.file_cost("scripts/a.py", ["t::a"], "context", {"t::a": 10}, {}, [], {})
    assert cost["cost_ms"] == 0 and cost["W_F_ms"] == 0 and cost["function_cost_ms"] == {}


def test_a_fragment_that_holds_another_index_names_the_index_and_the_fragment():
    plan = band_plan(3)
    doc = fragment(plan, 2)
    doc["binding"]["index"] = 3
    rehash(doc)
    found = ncs.fragment_problems(doc, 2, "name-2", plan, BIND)
    assert [p["message"] for p in found] == ["shard 2 of 3: name-2 holds index 3"]
    doc["binding"]["index"] = None
    rehash(doc)
    found = ncs.fragment_problems(doc, 2, "name-2", plan, BIND)
    assert [p["message"] for p in found] == ["shard 2 of 3: name-2 holds index None"]


def test_a_fragment_that_differs_in_several_fields_lists_them_in_order_with_commas():
    plan = band_plan(3)
    doc = fragment(plan, 2)
    doc["binding"].update(pr=8, run_id="1")
    rehash(doc)
    (found,) = ncs.fragment_problems(doc, 2, "n", plan, BIND)
    assert found["message"] == "shard 2 of 3: pr, run_id differ from the plan's"


def test_a_shard_that_misses_results_names_the_count_and_the_first_missing_mutant():
    plan = band_plan(3)
    doc = fragment(plan, 2)
    entry = doc["files"][0]
    assigned = {m["path"]: list(m["names"]) for m in plan["assignment"][1]["members"]}
    dropped = sorted(entry["status_by_key"])[:2]
    for name in dropped:
        del entry["status_by_key"][name]
    found = ncs._missing_results(2, doc, assigned)
    assert [p["message"] for p in found] == [
        f"shard 2 has no result for 2 planned mutant(s), first {dropped[0]}"
    ]
    assert found[0]["file"] == entry["path"] and found[0]["shard"] == 2


def test_a_file_that_already_failed_in_its_shard_does_not_stop_the_check_of_the_next_file():
    entry = {
        "fail_reasons": [{"code": "mutation_timeout", "message": "m"}],
        "status_by_key": {},
        "finished": True,
    }
    other = {"fail_reasons": [], "status_by_key": {}, "finished": True}
    doc = {"files": [dict(entry, path="a.py"), dict(other, path="b.py")]}
    found = ncs._missing_results(1, doc, {"a.py": ["a.x_f__mutmut_1"], "b.py": ["b.x_f__mutmut_1"]})
    assert [p["file"] for p in found] == ["b.py"]


def test_a_shard_whose_stated_counts_disagree_names_both_pairs():
    plan = band_plan(3)
    doc = fragment(plan, 2)
    doc["files"][0]["killed"] = 1
    doc["files"][0]["total"] = 2
    assigned = {m["path"]: list(m["names"]) for m in plan["assignment"][1]["members"]}
    found = [
        p for p in ncs._missing_results(2, doc, assigned) if p["code"] == "fragment_count_mismatch"
    ]
    assert [p["message"] for p in found] == [
        "shard 2 states killed/total 1/2, its mutant statuses give 10/10"
    ]


def test_a_clean_merge_scores_each_file_over_its_shards_and_clears_its_reason(monkeypatch):
    plan = band_plan(3)
    for rec in plan["files"]:
        rec["mutation_reason"] = "stale"
    plan["plan_hash"] = ncs.plan_hash(plan)
    frags = fragment_set(plan)
    for doc in frags.values():
        doc["binding"]["plan_hash"] = plan["plan_hash"]
        rehash(doc)
    records, problems = do_merge(plan, frags)
    assert problems == []
    out = records["files"][0]
    assert out["mutation_ran"] is True and out["mutation_reason"] is None
    assert (out["mutants_killed"], out["mutants_total"]) == (10, 10)
    assert out["mutant_score_pct"] == 100 and out["mutant_status_counts"] == {"killed": 10}


def test_a_file_with_fewer_results_than_planned_mutants_is_reported_with_both_counts():
    plan = band_plan(3)
    frags = fragment_set(plan)
    entry = frags["new-code-fragment-2-of-3"]["files"][0]
    del entry["status_by_key"][sorted(entry["status_by_key"])[0]]
    rehash(frags["new-code-fragment-2-of-3"])
    _, problems = do_merge(plan, frags)
    counted = [p for p in problems if p["message"].startswith("shards report")]
    assert counted == [
        {
            "code": "planned_mutant_without_result",
            "message": "shards report 9 mutants, the plan has 10",
            "file": entry["path"],
        }
    ]


def straddling_plan():
    """A band plan where one file has mutants in two shards, and that file's record is dirty."""
    per = (2 * CORE_MS - CORE_MS // 2) // 10
    plan = finish_plan([uniform("scripts/framework/f0.py", 10, per, "f0")])
    assert plan["N"] == 2
    held = {}
    for shard in plan["assignment"]:
        for member in shard["members"]:
            held.setdefault(member["path"], []).append(shard["index"])
    path, holders = next((p, h) for p, h in held.items() if len(h) >= 2)
    for rec in plan["files"]:
        if rec["path"] == path:
            rec.update(
                mutation_ran=True,
                mutants_killed=3,
                mutants_total=4,
                mutant_score_pct=75,
                mutant_status_counts={"killed": 3},
            )
    plan["plan_hash"] = ncs.plan_hash(plan)
    return plan, path, holders


def time_out(frags, plan, index, phase="mutate", file="scripts/framework/f1.py"):
    doc = frags[f"new-code-fragment-{index}-of-{plan['N']}"]
    doc["status"] = "timeout"
    doc["timeout"] = {"phase": phase, "file": file, "message": "m"}
    for entry in doc["files"]:
        entry.update(finished=False, status_by_key={}, killed=0, total=0, mutant_status_counts={})


def test_timed_out_shards_make_the_file_unscored_and_are_described_in_one_message():
    plan, path, holders = straddling_plan()
    frags = {}
    for index in range(1, plan["N"] + 1):
        doc = fragment(plan, index)
        doc["binding"]["plan_hash"] = plan["plan_hash"]
        frags[f"new-code-fragment-{index}-of-{plan['N']}"] = doc
    for index in holders:
        time_out(frags, plan, index, file=path)
    for doc in frags.values():
        rehash(doc)
    records, _ = do_merge(plan, frags)
    out = next(f for f in records["files"] if f["path"] == path)
    assert out["mutation_ran"] is False and out["mutation_reason"] == "timeout"
    assert out["mutants_killed"] is None and out["mutants_total"] is None
    assert out["mutant_score_pct"] is None and out["mutant_status_counts"] == {}
    (reason,) = [r for r in out["fail_reasons"] if r["code"] == "mutation_timeout"]
    texts = [
        ncs.timeout_text(
            i,
            2,
            {"phase": "mutate", "file": path, "message": "m"},
            sorted(m["path"] for m in plan["assignment"][i - 1]["members"]),
        )
        for i in holders
    ]
    assert reason["message"] == " ".join(texts)
    assert texts[0].startswith(
        f"shard {holders[0]} of 2 overran its 25-minute budget (ran out in mutate of {path}); "
    )


def test_the_timeout_text_of_a_shard_with_no_recorded_phase_has_no_where_clause():
    assert ncs.timeout_text(1, 2, None, ["a.py"]) == (
        "shard 1 of 2 overran its 25-minute budget; files with mutants in shard 1: a.py; split the PR"
    )
    assert (
        ncs.timeout_text(1, 2, {"phase": "", "file": "", "message": ""}, ["a.py"]).count("(") == 0
    )


# --------------------------------------------------------------------------
# plan_shape_error, plan_problems, plan_consistency_error
# --------------------------------------------------------------------------


def resynced(plan):
    plan["plan_hash"] = ncs.plan_hash(plan)
    return plan


@pytest.mark.parametrize(
    "mangle,message",
    [
        (lambda p: "x", "plan is not an object"),
        (lambda p: dict(p, schema="other"), "plan has the wrong schema"),
        (
            lambda p: dict(p, job_seconds="slow"),
            "plan is missing a field or has one of the wrong type",
        ),
        (lambda p: dict(p, internal_errors=["x"]), "plan internal_errors holds a non-object"),
    ],
)
def test_each_unreadable_plan_is_refused_with_its_own_text(mangle, message):
    assert ncs.plan_shape_error(mangle(band_plan(3))) == message


def test_a_plan_with_a_null_job_time_is_readable():
    assert ncs.plan_shape_error(dict(band_plan(3), job_seconds=None)) is None


def test_a_plan_job_that_did_not_succeed_is_named_first_with_its_result():
    found, readable = ncs.plan_problems(band_plan(3), "failure", BIND)
    assert readable is True
    assert found[0] == {"code": "plan_not_successful", "message": "plan job result failure"}


def test_a_plan_whose_hash_is_stale_says_the_hash_does_not_match_its_content():
    plan = band_plan(3)
    plan["python"] = "3.13"
    found, _ = ncs.plan_problems(plan, "success", BIND)
    assert found == [
        {
            "code": "plan_hash_mismatch",
            "message": "plan_hash does not match the plan's content",
        }
    ]


def test_each_internal_error_of_the_plan_is_reported_as_its_code_and_message():
    plan = band_plan(3)
    plan["internal_errors"] = [{"code": "c", "message": "m"}, {"x": 1}]
    found, _ = ncs.plan_problems(resynced(plan), "success", BIND)
    assert [p["message"] for p in found if p["code"] == "plan_internal_error"] == [
        "c: m",
        "None: None",
    ]


def test_a_plan_whose_weights_cannot_be_laid_out_reports_the_layout_error_itself():
    plan = band_plan(3)
    for rec in plan["files"]:
        rec["function_cost_ms"] = {}
    with pytest.raises(ncs.GateError) as caught:
        ncs.layout(plan["files"])
    assert ncs.plan_consistency_error(plan) == str(caught.value)
    assert str(caught.value) != "None"


def test_a_plan_with_a_wrong_total_weight_or_cap_flag_is_inconsistent_by_either_alone():
    message = "plan W_ms or capped differs from its own weights"
    plan = band_plan(3)
    assert ncs.plan_consistency_error(plan) is None
    assert ncs.plan_consistency_error(dict(plan, W_ms=plan["W_ms"] + 1)) == message
    assert ncs.plan_consistency_error(dict(plan, capped=not plan["capped"])) == message


def test_a_plan_with_a_wrong_file_weight_names_the_file():
    plan = band_plan(3)
    plan["files"][0]["W_F_ms"] += 1
    assert ncs.plan_consistency_error(plan) == (
        "plan W_F_ms for scripts/framework/f0.py differs from its own weights"
    )


def test_a_plan_whose_assignment_is_not_the_partition_says_so():
    plan = band_plan(3)
    plan["assignment"] = list(reversed(plan["assignment"]))
    assert ncs.plan_consistency_error(plan) == (
        "plan assignment is not the partition this code produces from its weights"
    )


# --------------------------------------------------------------------------
# result_problems, FileMerge.row, skeleton, shard_summary, merge, partition
# --------------------------------------------------------------------------


def test_a_mutant_in_a_shard_the_plan_does_not_know_is_in_the_wrong_fragment():
    doc = {"status": "timeout", "files": [{"path": "a.py", "status_by_key": {"k": "killed"}}]}
    assert ncs.result_problems({5: doc}, {}) == [
        {
            "code": "mutant_in_wrong_fragment",
            "message": "shard 5: k was not assigned to this shard",
            "shard": 5,
            "file": "a.py",
        }
    ]


def test_a_mutant_with_a_result_in_two_shards_names_the_file_and_the_earlier_shard():
    entry = {"path": "a.py", "status_by_key": {"k": "killed"}}
    docs = {1: {"status": "timeout", "files": [entry]}, 2: {"status": "timeout", "files": [entry]}}
    found = ncs.result_problems(docs, {1: {"a.py": ["k"]}, 2: {"a.py": ["k"]}})
    assert found == [
        {
            "code": "mutant_in_two_fragments",
            "message": "shard 2: k also has a result in shard 1",
            "shard": 2,
            "file": "a.py",
        }
    ]


def test_the_row_of_a_shard_with_no_fragment_uses_its_state_or_says_missing():
    fm = ncs.FileMerge({"path": "a.py"}, [1, 2], {}, {1: "invalid"})
    assert fm.row(1) == {"index": 1, "killed": None, "total": None, "status": "invalid"}
    assert fm.row(2) == {"index": 2, "killed": None, "total": None, "status": "missing"}


def test_the_row_of_a_shard_with_a_fragment_carries_its_counts_and_its_status():
    usable = {1: {"status": "complete", "files": [{"path": "a.py", "killed": 3, "total": 4}]}}
    fm = ncs.FileMerge({"path": "a.py"}, [1], usable, {})
    assert fm.row(1) == {"index": 1, "killed": 3, "total": 4, "status": "complete"}


def test_the_merged_top_level_takes_versions_python_and_core_from_a_readable_plan_only():
    plan = band_plan(3)
    top = ncs.skeleton(plan, BIND)
    assert top["tool_versions"] == plan["tool_versions"] and top["python"] == "3.12"
    assert top["coverage_core"] == "ctrace"
    bare = ncs.skeleton(None, BIND)
    assert bare["tool_versions"] == {} and bare["python"] is None
    assert bare["coverage_core"] is None


def test_the_shard_summary_gives_a_shard_without_a_fragment_its_state_or_missing():
    plan = band_plan(3)
    per_shard = ncs.shard_summary(plan, {1: "invalid"}, {})["per_shard"]
    assert [s["status"] for s in per_shard] == ["invalid", "missing", "missing"]


def test_a_shard_that_has_a_duplicate_fragment_is_not_also_reported_as_missing():
    plan = band_plan(3)
    frags = fragment_set(plan)
    frags["new-code-fragment-02-of-3"] = copy.deepcopy(frags["new-code-fragment-2-of-3"])
    _, problems = do_merge(plan, frags)
    assert "fragment_duplicate" in codes(problems) and "fragment_missing" not in codes(problems)


def test_a_files_seconds_are_the_running_sum_of_its_shards_rounded_to_three_places():
    plan = band_plan(3)
    frags = fragment_set(plan)
    for doc in frags.values():
        for entry in doc["files"]:
            entry["seconds"] = 1.23456
        rehash(doc)
    records, _ = do_merge(plan, frags)
    holders = sum(
        1
        for s in plan["assignment"]
        for m in s["members"]
        if m["path"] == "scripts/framework/f0.py"
    )
    total = 0.0
    for _ in range(holders):
        total = round(total + 1.23456, 3)
    assert records["files"][0]["seconds"] == total


def test_a_mutant_of_zero_weight_after_the_last_shard_is_filled_stays_in_it():
    weights = {"a.py": {"x": 5, "y": 0}}
    cut = ncs.partition(weights, {"a.py": ["x", "y"]}, 1)
    assert cut == [
        {"index": 1, "members": [{"path": "a.py", "names": ["x", "y"]}], "est_mutation_ms": 5}
    ]


def test_the_timeout_text_lists_a_shards_files_separated_by_commas():
    assert ncs.timeout_text(2, 3, None, ["a.py", "b.py"]).endswith(
        "files with mutants in shard 2: a.py, b.py; split the PR"
    )
