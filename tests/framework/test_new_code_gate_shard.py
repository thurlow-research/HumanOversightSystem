"""Pure, in-process tests of the sharding logic of the new-code gate (#2304, TD 9.4).

`new_code_gate_shard` does no I/O and reads no clock or environment, so every case here builds
plan and fragment documents as dictionaries and calls the functions directly. The fixture rule
for N (TD 9.4): the merge recomputes N and the whole partition from the plan's stored weights,
so no plan here is given an N its own weights do not produce. A test that needs N = 3 gets it
from per-function weights that sum into N = 3's band. Only the pure `partition` tests pass N
directly, because they do not go through the merge.

The gate modules are imported canonically and at module level (TD 5.19).
"""

import copy

import pytest

from scripts.framework import new_code_gate_logic as ncg
from scripts.framework import new_code_gate_shard as ncs

GATED = "a" * 40
BIND = {"mode": "ci", "gated_sha": GATED, "pr": 7, "run_id": "99", "run_attempt": 1}
CORE_MS = ncs.CI_CORES * ncs.T_MS


@pytest.fixture(autouse=True)
def run_in_tmp_path(tmp_path, monkeypatch):
    """A mutant that turns a computed path relative lands here, never in mutmut's cwd (RV3-7a)."""
    monkeypatch.chdir(tmp_path)


def key(rel, n, func="f"):
    return f"{ncg.canonical_name(rel)}.x_{func}{n}__mutmut_1"


def plan_file(path, mutants, to_shards=True, tests=("tests/test_x.py::test_a",)):
    """A plan file record. `mutants` is a list of (key, weight); one function per mutant."""
    rec = ncg.blank_file_record(path, "new")
    names = sorted(name for name, _ in mutants)
    costs = {ncs.mutant_prefix(name): weight for name, weight in mutants}
    rec.update(
        mutant_names=names,
        gated_mutant_names=names if to_shards else [],
        selection_full=list(tests),
        function_cost_ms=costs if to_shards else {},
        W_F_ms=sum(costs.values()) if to_shards else 0,
        fixed_est_ms=ncs.STATS_PASSES * 100,
        cost_ms=sum(costs.values()) // len(names) if to_shards else 0,
        to_shards=to_shards,
    )
    rec.update(ncg.selection_fields("context", list(tests)))
    return rec


def finish_plan(files, attempt=1, **override):
    lay = ncs.layout(files)
    plan = {
        "schema": ncg.SCHEMA_PLAN,
        "gate_version": ncg.GATE_VERSION,
        "binding": {
            "mode": "ci",
            "gated_sha": GATED,
            "pr_head_sha": "b" * 40,
            "base_sha": "c" * 40,
            "gated_tree": "d" * 40,
            "pr": 7,
            "run_id": "99",
            "run_attempt": attempt,
        },
        "tool_versions": dict(ncg.PINNED),
        "python": "3.12",
        "coverage_core": "ctrace",
        "constants": ncs.plan_constants(),
        "files": files,
        "W_ms": lay["W_ms"],
        "W_ci_minutes": ncs.ci_minutes(lay["W_ms"]),
        "N": lay["N"],
        "capped": lay["capped"],
        "assignment": lay["assignment"],
        "internal_errors": [],
        "started_at": "t0",
        "finished_at": "t1",
        "seconds": 5.0,
        "job_seconds": 9,
    }
    plan.update(override)
    plan["plan_hash"] = ncs.plan_hash(plan)
    return plan


def uniform(path, count, weight, prefix="m"):
    return plan_file(path, [(key(path, i, prefix), weight) for i in range(count)])


def band_plan(count, files=3):
    """A plan whose weights sum into the band of `count` shards (the fixture rule)."""
    per = (count * CORE_MS - CORE_MS // 2) // (files * 10)
    return finish_plan(
        [uniform(f"scripts/framework/f{i}.py", 10, per, f"f{i}") for i in range(files)]
    )


def fragment(plan, index, killed=None, status="complete", attempt=1, **override):
    """The fragment shard `index` would write. `killed(name)` says which mutants are killed."""
    killed = killed or (lambda name: True)
    entries = []
    for member in plan["assignment"][index - 1]["members"]:
        results = {n: ("killed" if killed(n) else "survived") for n in member["names"]}
        done = sum(1 for v in results.values() if v == "killed")
        counts = {}
        for value in results.values():
            counts[value] = counts.get(value, 0) + 1
        entries.append(
            {
                "path": member["path"],
                "assigned": len(member["names"]),
                "status_by_key": results,
                "killed": done,
                "total": len(results),
                "mutant_status_counts": counts,
                "fail_reasons": [],
                "mutation_reason": None,
                "path_load_findings": [],
                "isolation_failure": None,
                "workspace_seconds": 1.0,
                "mutmut_seconds": 2.0,
                "collect_seconds": 0.5,
                "seconds": 4.0,
                "finished": True,
            }
        )
    doc = {
        "schema": ncg.SCHEMA_FRAGMENT,
        "binding": {
            "gated_sha": plan["binding"]["gated_sha"],
            "pr": plan["binding"]["pr"],
            "run_id": plan["binding"]["run_id"],
            "run_attempt": attempt,
            "index": index,
            "N": plan["N"],
            "plan_hash": plan["plan_hash"],
        },
        "status": status,
        "timeout": None,
        "internal_errors": [],
        "files": entries,
        "started_at": "t0",
        "finished_at": "t1",
        "seconds": 30.0,
        "job_seconds": 40,
    }
    doc.update(override)
    doc["fragment_sha256"] = ncs.fragment_hash(doc)
    return doc


def rehash(doc):
    doc["fragment_sha256"] = ncs.fragment_hash(doc)
    return doc


def fragment_set(plan, **kwargs):
    return {
        f"new-code-fragment-{i}-of-{plan['N']}": fragment(plan, i, **kwargs)
        for i in range(1, plan["N"] + 1)
    }


def do_merge(plan, fragments, plan_result="success", shard_result="success", binding=BIND):
    return ncs.merge(plan, fragments, plan_result, shard_result, binding)


def codes(problems):
    return [p["code"] for p in problems]


def file_of(records, path):
    return next(f for f in records["files"] if f["path"] == path)


def exit_of(records):
    return ncg.decide(records, [], ncg.THRESHOLDS)["exit_code"]


# --------------------------------------------------------------------------
# AC-35(a): the shard count, in integers
# --------------------------------------------------------------------------


@pytest.mark.parametrize("k", range(0, 9))
def test_shard_count_boundaries(k):
    exact = k * CORE_MS
    assert ncs.shard_count(exact) == (max(1, k), False)
    assert ncs.shard_count(exact + 1) == (min(k + 1, ncs.N_MAX), k + 1 > ncs.N_MAX)


def test_shard_count_zero_work_is_one_and_far_above_the_cap_is_n_max_capped():
    assert ncs.shard_count(0) == (1, False)
    assert ncs.shard_count(ncs.N_MAX * CORE_MS) == (8, False)
    assert ncs.shard_count(ncs.N_MAX * CORE_MS + 1) == (8, True)
    assert ncs.shard_count(100 * CORE_MS) == (8, True)


def test_the_constants_are_the_ruled_numbers():
    assert (ncs.T_MS, ncs.N_MAX, ncs.CI_CORES) == (900_000, 8, 4)
    assert (ncs.C_MUTANT_MS, ncs.D_DEFAULT_MS, ncs.D_CLAMP_MS) == (50, 1_000, 600_000)
    assert (ncs.STATS_PASSES, ncs.COST_MODEL) == (2, "per-function-fan-in/1")
    constants = ncs.plan_constants()
    assert constants["BUDGET_SECONDS"] == 1500 and constants["PLAN_BUDGET_SECONDS"] == 600
    assert set(constants) == {
        "T_MS",
        "N_MAX",
        "CI_CORES",
        "C_MUTANT_MS",
        "D_DEFAULT_MS",
        "D_CLAMP_MS",
        "STATS_PASSES",
        "COST_MODEL",
        "BUDGET_SECONDS",
        "PLAN_BUDGET_SECONDS",
    }


def test_ci_minutes_is_one_decimal_of_w_over_the_cores():
    assert ncs.ci_minutes(0) == 0.0
    assert ncs.ci_minutes(4 * 60_000) == 1.0
    assert ncs.ci_minutes(4 * 60_000 * 15 + 12_000) == 15.1


def test_ceil_div_rounds_up_only_when_there_is_a_remainder():
    assert [ncs.ceil_div(a, 4) for a in (0, 1, 4, 5, 8)] == [0, 1, 1, 2, 2]


# --------------------------------------------------------------------------
# AC-36: the partition
# --------------------------------------------------------------------------


def names_and_weights(spec):
    names = {path: [n for n, _ in mutants] for path, mutants in spec.items()}
    weights = {path: dict(mutants) for path, mutants in spec.items()}
    return weights, names


def spec_of_three_files():
    return {
        "a.py": [(key("a.py", i), 100 + i) for i in range(6)],
        "b.py": [(key("b.py", i), 900 - 10 * i) for i in range(5)],
        "c.py": [(key("c.py", i), 10) for i in range(9)],
    }


def test_partition_complete_disjoint_and_spans():
    weights, names = names_and_weights(spec_of_three_files())
    parts = ncs.partition(weights, names, 3)
    assert [p["index"] for p in parts] == [1, 2, 3]
    flat = [(m["path"], n) for p in parts for m in p["members"] for n in m["names"]]
    assert sorted(flat) == sorted((path, n) for path, ns in names.items() for n in ns)
    assert len(flat) == len(set(flat))
    holders = {}
    for p in parts:
        for m in p["members"]:
            holders.setdefault(m["path"], []).append(p["index"])
    assert any(len(v) > 1 for v in holders.values())
    for p in parts:
        assert p["est_mutation_ms"] == sum(
            weights[m["path"]][n] for m in p["members"] for n in m["names"]
        )
        assert [m["path"] for m in p["members"]] == sorted(m["path"] for m in p["members"])
        for m in p["members"]:
            assert m["names"] == sorted(m["names"])


def test_partition_cuts_where_the_running_total_reaches_k_over_n_of_the_whole():
    weights = {"a.py": {key("a.py", i): 10 for i in range(6)}}
    names = {"a.py": list(weights["a.py"])}
    parts = ncs.partition(weights, names, 3)
    assert [len(p["members"][0]["names"]) for p in parts] == [2, 2, 2]
    assert [p["est_mutation_ms"] for p in parts] == [20, 20, 20]
    one = ncs.partition(weights, names, 1)
    assert len(one) == 1 and len(one[0]["members"][0]["names"]) == 6


def test_partition_never_splits_a_mutant_or_adjusts_n_and_trailing_shards_stay_empty():
    weights = {"a.py": {key("a.py", 0): 1000, key("a.py", 1): 1}}
    names = {"a.py": list(weights["a.py"])}
    parts = ncs.partition(weights, names, 4)
    assert [p["index"] for p in parts] == [1, 2, 3, 4]
    assert [len(p["members"]) for p in parts] == [1, 1, 0, 0]
    assert parts[2] == {"index": 3, "members": [], "est_mutation_ms": 0}


def test_partition_of_nothing_is_one_empty_shard_per_index():
    assert ncs.partition({}, {}, 1) == [{"index": 1, "members": [], "est_mutation_ms": 0}]


def test_an_empty_plan_has_n_one_and_one_empty_assignment():
    plan = finish_plan([plan_file("scripts/framework/z.py", [], to_shards=False)])
    assert (plan["N"], plan["W_ms"], plan["capped"]) == (1, 0, False)
    assert plan["assignment"] == [
        {"index": 1, "members": [], "est_mutation_ms": 0, "est_fixed_ms": 0}
    ]
    assert finish_plan([])["assignment"][0]["members"] == []


def test_plan_hash_changes_with_any_assignment_change():
    plan = band_plan(3)
    base = plan["plan_hash"]
    assert ncs.plan_hash(plan) == base

    def with_assignment(change):
        other = copy.deepcopy(plan)
        change(other["assignment"])
        return ncs.plan_hash(other)

    def move_one(assignment):
        name = assignment[0]["members"][0]["names"].pop()
        assignment[1]["members"][0]["names"].append(name)

    def swap_two(assignment):
        first, second = assignment[0]["members"][0], assignment[1]["members"][-1]
        first["names"][0], second["names"][0] = second["names"][0], first["names"][0]

    assert with_assignment(move_one) != base
    assert with_assignment(swap_two) != base
    assert with_assignment(lambda a: a.pop()) != base
    reordered = copy.deepcopy(plan)
    reordered["files"].reverse()
    assert ncs.plan_hash(reordered) != base
    other_weights = band_plan(2)
    assert other_weights["plan_hash"] != base and other_weights["N"] == 2


def test_plan_hash_ignores_timings_and_its_own_field_only():
    plan = band_plan(3)
    other = dict(plan, started_at="x", finished_at="y", seconds=99.0, job_seconds=None)
    other["files"] = [dict(f, seconds=77.0, mutmut_seconds=5.0) for f in plan["files"]]
    assert ncs.plan_hash(other) == plan["plan_hash"]
    assert ncs.plan_hash(dict(plan, plan_hash="x")) == plan["plan_hash"]
    assert ncs.plan_hash(dict(plan, python="3.13")) != plan["plan_hash"]


def test_fragment_hash_ignores_timings_and_its_own_field_only():
    plan = band_plan(3)
    frag = fragment(plan, 1)
    other = dict(frag, started_at="z", seconds=1.0, job_seconds=None, fragment_sha256="q")
    assert ncs.fragment_hash(other) == frag["fragment_sha256"]
    assert ncs.fragment_hash(dict(frag, status="timeout")) != frag["fragment_sha256"]


def test_plan_hash_covers_n():
    plan = band_plan(3)
    other = dict(plan, N=plan["N"] + 1)
    assert ncs.plan_hash(other) != plan["plan_hash"]
    assert ncs.plan_hash(dict(plan, shards=[{"index": 1}])) != plan["plan_hash"]


def test_fragment_hash_covers_its_binding_n_and_plan_hash():
    plan = band_plan(3)
    frag = fragment(plan, 1)
    for field, value in (("N", 4), ("plan_hash", "f" * 64)):
        other = copy.deepcopy(frag)
        other["binding"][field] = value
        assert ncs.fragment_hash(other) != frag["fragment_sha256"], field


def test_document_hash_drops_exactly_the_eight_timing_names():
    assert ncs.DOCUMENT_HASH_DROPS == {
        "started_at",
        "finished_at",
        "seconds",
        "job_seconds",
        "enumerate_seconds",
        "workspace_seconds",
        "mutmut_seconds",
        "collect_seconds",
    }


def test_isolation_failure_is_hashed_in_plan_and_fragment():
    plan = band_plan(3)
    changed = copy.deepcopy(plan)
    changed["files"][0]["isolation_failure"] = {"stage": "x"}
    assert ncs.plan_hash(changed) != plan["plan_hash"]
    frag = fragment(plan, 1)
    other = copy.deepcopy(frag)
    other["files"][0]["isolation_failure"] = {"stage": "x"}
    assert ncs.fragment_hash(other) != frag["fragment_sha256"]


def test_timing_only_changes_change_neither_plan_hash_nor_fragment_hash():
    plan = band_plan(3)
    frag = fragment(plan, 1)
    timings = {name: 123 for name in ncs.DOCUMENT_HASH_DROPS}
    other_plan = copy.deepcopy(plan)
    other_plan.update(timings)
    for rec in other_plan["files"]:
        rec.update(timings)
    assert ncs.plan_hash(other_plan) == plan["plan_hash"]
    other_frag = copy.deepcopy(frag)
    other_frag.update(timings)
    for entry in other_frag["files"]:
        entry.update(timings)
    assert ncs.fragment_hash(other_frag) == frag["fragment_sha256"]


def test_records_sha256_still_ignores_n_plan_hash_and_shards():
    files = [{"path": "a.py", "mutants_killed": 3}]
    base = ncg.records_sha256(files)
    varied = [dict(files[0], N=9, plan_hash="x", shards=[{"index": 1}])]
    assert ncg.records_sha256(varied) == base


def test_layout_names_the_function_it_lacks_a_cost_for():
    rec = uniform("a.py", 2, 10)
    rec["function_cost_ms"] = {}
    with pytest.raises(ncg.GateError, match="plan lacks a function cost for a.py"):
        ncs.layout([rec])


def test_layout_est_fixed_counts_each_file_once_per_shard_it_has_mutants_in():
    first = uniform("a.py", 4, 10, "a")
    second = uniform("b.py", 4, 10, "b")
    first["fixed_est_ms"], second["fixed_est_ms"] = 7, 11
    lay = ncs.layout([first, second])
    assert lay["N"] == 1 and lay["assignment"][0]["est_fixed_ms"] == 18
    assert lay["W_F_ms"] == {"a.py": 40, "b.py": 40}


# --------------------------------------------------------------------------
# SH-COST: the per-function fan-in cost model
# --------------------------------------------------------------------------

SPANS = {"mod.x_a": (1, 5), "mod.x_b": (10, 15)}
NAMES = ["mod.x_a__mutmut_1", "mod.x_a__mutmut_2", "mod.x_b__mutmut_1"]
SEL = ["tests/t.py::one", "tests/t.py::two"]


def cost(durations, executed, method="context", selection=SEL, names=NAMES, spans=SPANS):
    return ncs.file_cost("mod.py", selection, method, durations, spans, names, executed)


def test_cost_per_function_fan_in():
    durations = {SEL[0]: 200, SEL[1]: 7000}
    executed = {SEL[0]: {1, 2}, SEL[1]: {11, 12}}
    got = cost(durations, executed)
    assert got["function_cost_ms"] == {
        "mod.x_a": ncs.C_MUTANT_MS + 200,
        "mod.x_b": ncs.C_MUTANT_MS + 7000,
    }
    w = [ncs.C_MUTANT_MS + 200, ncs.C_MUTANT_MS + 200, ncs.C_MUTANT_MS + 7000]
    assert got["W_F_ms"] == sum(w)
    assert got["cost_ms"] == sum(w) // 3
    assert got["fixed_est_ms"] == ncs.STATS_PASSES * 7200


def test_a_selected_test_that_ran_no_line_in_the_span_adds_nothing():
    durations = {SEL[0]: 200, SEL[1]: 7000}
    got = cost(durations, {SEL[0]: {1}, SEL[1]: {99}})
    assert got["function_cost_ms"]["mod.x_a"] == ncs.C_MUTANT_MS + 200
    assert got["function_cost_ms"]["mod.x_b"] == ncs.C_MUTANT_MS
    edges = cost(durations, {SEL[0]: {5}, SEL[1]: {10}})
    assert edges["function_cost_ms"]["mod.x_a"] == ncs.C_MUTANT_MS + 200
    assert edges["function_cost_ms"]["mod.x_b"] == ncs.C_MUTANT_MS + 7000
    outside = cost(durations, {SEL[0]: {6}, SEL[1]: {16}})
    assert set(outside["function_cost_ms"].values()) == {ncs.C_MUTANT_MS}


def test_name_fallback_charges_every_mutant_for_the_whole_selection():
    durations = {SEL[0]: 200, SEL[1]: 7000}
    got = cost(durations, {}, method="name_fallback")
    assert set(got["function_cost_ms"].values()) == {ncs.C_MUTANT_MS + 7200}


def test_missing_ids_get_the_default_values_are_clamped_and_containers_sum_children():
    got = cost({}, {SEL[0]: {1}, SEL[1]: {1}})
    assert got["function_cost_ms"]["mod.x_a"] == ncs.C_MUTANT_MS + 2 * ncs.D_DEFAULT_MS
    big = cost({SEL[0]: 10**9, SEL[1]: 5}, {SEL[0]: {1}, SEL[1]: {1}})
    assert big["function_cost_ms"]["mod.x_a"] == ncs.C_MUTANT_MS + ncs.D_CLAMP_MS + 5
    module = "tests/t.py"
    kids = {f"{module}::one": 300, f"{module}::two[1]": 400, "tests/other.py::x": 9999}
    fallback = cost(kids, {}, method="name_fallback", selection=[module])
    assert fallback["function_cost_ms"]["mod.x_a"] == ncs.C_MUTANT_MS + 700
    lonely = cost({}, {}, method="name_fallback", selection=["tests/none.py"])
    assert lonely["function_cost_ms"]["mod.x_a"] == ncs.C_MUTANT_MS + ncs.D_DEFAULT_MS


def test_duration_of_prefers_an_exact_entry_over_children():
    durations = {"t.py::a": 5, "t.py::a::b": 70}
    assert ncs.duration_of("t.py::a", durations) == 5
    assert ncs.duration_of("t.py::a::b", durations) == 70
    assert ncs.duration_of("t.py", durations) == 75
    assert ncs.duration_of("t.py::x", durations) == ncs.D_DEFAULT_MS
    assert ncs.duration_of("t.py::a", {"t.py::a": -4}) == 0


def test_a_gated_mutant_with_no_span_is_an_error_naming_the_path_and_mutant():
    with pytest.raises(
        ncg.GateError, match=r"mutant function span missing: mod.py mod.x_c__mutmut_1"
    ):
        cost({}, {}, names=[*NAMES, "mod.x_c__mutmut_1"])


def test_w_is_the_sum_of_per_mutant_weights_and_changing_fixed_est_moves_neither_n_nor_the_cut():
    durations = {SEL[0]: 200, SEL[1]: 7000}
    got = cost(durations, {SEL[0]: {1}, SEL[1]: {11}})
    per_mutant = [got["function_cost_ms"][ncs.mutant_prefix(n)] for n in NAMES]
    assert got["W_F_ms"] == sum(per_mutant)
    base = uniform("a.py", 6, 600_000, "a")
    other = copy.deepcopy(base)
    other["fixed_est_ms"] = 10**9
    first, second = ncs.layout([base, other])["assignment"], ncs.layout([base, base])["assignment"]
    assert [a["members"] for a in first] == [a["members"] for a in second]
    assert ncs.layout([base, other])["N"] == ncs.layout([base, base])["N"]


def test_executed_by_selected_takes_exact_contexts_and_every_context_under_a_container():
    lines = {"t.py::a": {1, 2}, "t.py::b[1]": {3}, "t.py::b[2]": {4}, "u.py::z": {9}}
    got = ncs.executed_by_selected(["t.py::a", "t.py", "t.py::b", "t.py::none"], lines)
    assert got["t.py::a"] == {1, 2}
    assert got["t.py"] == {1, 2, 3, 4}
    assert got["t.py::b"] == frozenset()
    assert got["t.py::none"] == frozenset()


def test_the_whole_file_cost_uses_executed_lines_of_container_selections():
    lines = {"tests/t.py::one": {1}, "tests/t.py::two": {11}}
    got = ncs.executed_by_selected(["tests/t.py"], lines)
    assert got["tests/t.py"] == {1, 11}
    assert ncs.executed_by_selected(["tests/t.py::one"], lines)["tests/t.py::one"] == {1}


# --------------------------------------------------------------------------
# Merge: the happy path and its identities
# --------------------------------------------------------------------------


def test_an_unmodified_plan_and_its_fragments_merge_with_no_problem():
    plan = band_plan(3)
    assert plan["N"] == 3
    records, problems = do_merge(plan, fragment_set(plan))
    assert problems == [] and records["internal_errors"] == []
    assert exit_of(records) == 0
    assert records["schema"] == ncg.SCHEMA_RECORDS and records["phase"] == "merge"
    for rec in records["files"]:
        assert rec["mutation_ran"] is True and rec["mutants_total"] == 10
        assert rec["mutants_killed"] == 10 and rec["mutant_score_pct"] == 100.0
        assert rec["N"] == 3 and rec["plan_hash"] == plan["plan_hash"]
        assert set(rec) == set(ncg.FILE_FIELDS)
    assert set(records) >= set(ncg.TOP_LEVEL_FIELDS) - {"started_at", "finished_at", "seconds"}


def test_merge_sums_never_averages():
    paths = ["scripts/framework/a.py"]
    names = [key(paths[0], f"{i:03d}") for i in range(100)]
    mutants = [(n, 62_000 if i < 40 else 40_000) for i, n in enumerate(names)]
    plan = finish_plan([plan_file(paths[0], mutants)])
    assert plan["N"] == 2
    sizes = [len(s["members"][0]["names"]) for s in plan["assignment"]]
    assert sizes == [40, 60]

    def killer(limit_one, limit_two):
        def kill(name):
            index = names.index(name)
            return index < limit_one if index < 40 else index - 40 < limit_two

        return kill

    records, problems = do_merge(plan, fragment_set(plan, killed=killer(30, 50)))
    assert problems == []
    rec = file_of(records, paths[0])
    assert (rec["mutants_killed"], rec["mutants_total"], rec["mutant_score_pct"]) == (80, 100, 80.0)
    assert [r["killed"] for r in rec["shards"]] == [30, 50]
    assert exit_of(records) == 0
    at = do_merge(plan, fragment_set(plan, killed=killer(30, 45)))[0]
    assert file_of(at, paths[0])["mutant_score_pct"] == 75.0 and exit_of(at) == 0
    below = do_merge(plan, fragment_set(plan, killed=killer(29, 45)))[0]
    assert file_of(below, paths[0])["mutant_score_pct"] == 74.0
    assert exit_of(below) == 1
    verdict = ncg.decide(below, [], ncg.THRESHOLDS)
    assert [r["code"] for r in verdict["files"][0]["fail_reasons"]] == [
        "mutant_score_below_threshold"
    ]


def test_the_merged_records_hash_is_the_same_for_any_shard_count():
    path = "scripts/framework/a.py"
    mutants = [(key(path, f"{i:03d}"), 400_000) for i in range(30)]
    one = finish_plan([plan_file(path, [(n, 1) for n, _ in mutants])])
    three = finish_plan([plan_file(path, mutants)])
    assert (one["N"], three["N"]) == (1, 4)

    def hash_kill(name):
        return sum(map(ord, name)) % 4 != 0

    a = do_merge(one, fragment_set(one, killed=hash_kill))[0]
    b = do_merge(three, fragment_set(three, killed=hash_kill))[0]
    assert a["records_sha256"] == b["records_sha256"]
    assert file_of(a, "scripts/framework/a.py")["mutants_killed"] == (
        file_of(b, "scripts/framework/a.py")["mutants_killed"]
    )
    assert a["plan_hash"] != b["plan_hash"]


def test_merge_accepts_mixed_attempts_when_bound():
    plan = band_plan(3)
    frags = fragment_set(plan)
    frags["new-code-fragment-2-of-3"] = fragment(plan, 2, attempt=2)
    records, problems = do_merge(plan, frags, binding=dict(BIND, run_attempt=2))
    assert problems == [] and exit_of(records) == 0


def test_verdict_only_rerun_same_records_sha():
    plan = band_plan(3)
    frags = fragment_set(plan)
    first = do_merge(plan, frags)[0]
    second = do_merge(copy.deepcopy(plan), copy.deepcopy(frags))[0]
    assert first["records_sha256"] == second["records_sha256"]
    rerun = do_merge(plan, frags, binding=dict(BIND, run_attempt=2))[0]
    assert rerun["records_sha256"] == first["records_sha256"]


# --------------------------------------------------------------------------
# AC-38 and SH-PART-EQ: the merge refuses each injected case
# --------------------------------------------------------------------------


def a_name(plan, index=1):
    return plan["assignment"][index - 1]["members"][0]["names"][0]


def resync(plan, frags):
    """After a plan edit: a fresh plan hash, and fragments bound to it."""
    plan["plan_hash"] = ncs.plan_hash(plan)
    for doc in frags.values():
        doc["binding"]["plan_hash"] = plan["plan_hash"]
        rehash(doc)


def case_missing(plan, frags):
    del frags["new-code-fragment-2-of-3"]


def case_duplicate(plan, frags):
    frags["new-code-fragment-02-of-3"] = copy.deepcopy(frags["new-code-fragment-2-of-3"])


def case_index_zero(plan, frags):
    frags["new-code-fragment-0-of-3"] = copy.deepcopy(frags["new-code-fragment-1-of-3"])


def case_index_n_plus_one(plan, frags):
    frags["new-code-fragment-4-of-3"] = copy.deepcopy(frags["new-code-fragment-1-of-3"])


def case_extra_entry(plan, frags):
    frags["stray"] = "not a directory"


def case_wrong_n_in_name(plan, frags):
    frags["new-code-fragment-1-of-5"] = copy.deepcopy(frags["new-code-fragment-1-of-3"])


def case_unreadable(plan, frags):
    frags["new-code-fragment-2-of-3"] = None


def case_wrong_schema(plan, frags):
    frags["new-code-fragment-2-of-3"]["schema"] = "other/1"


def binding_edit(field, value):
    def edit(plan, frags):
        doc = frags["new-code-fragment-2-of-3"]
        doc["binding"][field] = value
        rehash(doc)

    return edit


def case_hash_mismatch(plan, frags):
    frags["new-code-fragment-2-of-3"]["status"] = "timeout"


def case_index_disagrees_with_name(plan, frags):
    doc = frags["new-code-fragment-2-of-3"]
    doc["binding"]["index"] = 3
    rehash(doc)


def case_mutant_in_two_fragments(plan, frags):
    donor = frags["new-code-fragment-1-of-3"]["files"][0]
    first = next(iter(donor["status_by_key"]))
    target = frags["new-code-fragment-2-of-3"]["files"][0]
    target["status_by_key"][first] = "killed"
    target["path"] = donor["path"]
    rehash(frags["new-code-fragment-2-of-3"])


def case_mutant_in_wrong_fragment(plan, frags):
    first = frags["new-code-fragment-1-of-3"]["files"][0]
    moved = next(iter(first["status_by_key"]))
    del first["status_by_key"][moved]
    second = frags["new-code-fragment-2-of-3"]["files"][0]
    second["status_by_key"][moved] = "killed"
    rehash(frags["new-code-fragment-1-of-3"])
    rehash(frags["new-code-fragment-2-of-3"])


def case_planned_without_result(plan, frags):
    entry = frags["new-code-fragment-2-of-3"]["files"][0]
    del entry["status_by_key"][next(iter(entry["status_by_key"]))]
    rehash(frags["new-code-fragment-2-of-3"])


def case_stored_counts_mismatch(plan, frags):
    doc = frags["new-code-fragment-2-of-3"]
    doc["files"][0]["killed"] = 0
    rehash(doc)


def case_plan_hash_mismatch(plan, frags):
    plan["python"] = "3.13"


def case_plan_n_disagrees_with_its_weights(plan, frags):
    first = plan["files"][0]
    first["function_cost_ms"] = {k: v * 4 for k, v in first["function_cost_ms"].items()}
    resync(plan, frags)


def case_plan_stored_n_is_wrong(plan, frags):
    plan["N"] = 2
    resync(plan, frags)


def case_plan_stored_w_f_is_wrong(plan, frags):
    plan["files"][0]["W_F_ms"] += 1
    resync(plan, frags)


def case_valid_cover_that_is_not_the_partition(plan, frags):
    assignment = plan["assignment"]
    name = assignment[0]["members"][-1]["names"].pop()
    assignment[1]["members"][0]["names"].insert(0, name)
    resync(plan, frags)


def case_plan_not_bound(plan, frags):
    plan["binding"]["pr"] = 8
    resync(plan, frags)


def case_plan_internal_errors(plan, frags):
    plan["internal_errors"] = [{"code": "internal_error", "message": "boom"}]
    resync(plan, frags)


CASES = [
    ("missing", case_missing, "fragment_missing", 2),
    ("duplicate", case_duplicate, "fragment_duplicate", 2),
    ("index-0", case_index_zero, "fragment_out_of_range", None),
    ("index-n-plus-1", case_index_n_plus_one, "fragment_out_of_range", None),
    ("extra-entry", case_extra_entry, "fragment_extra", None),
    ("name-n-differs", case_wrong_n_in_name, "fragment_extra", None),
    ("unreadable", case_unreadable, "fragment_unreadable", 2),
    ("wrong-schema", case_wrong_schema, "fragment_unreadable", 2),
    ("gated-sha", binding_edit("gated_sha", "e" * 40), "fragment_not_bound", 2),
    ("pr", binding_edit("pr", 8), "fragment_not_bound", 2),
    ("run-id", binding_edit("run_id", "100"), "fragment_not_bound", 2),
    ("n", binding_edit("N", 4), "fragment_not_bound", 2),
    ("plan-hash", binding_edit("plan_hash", "f" * 64), "fragment_not_bound", 2),
    ("attempt-x", binding_edit("run_attempt", "x"), "fragment_attempt", 2),
    ("attempt-future", binding_edit("run_attempt", 2), "fragment_attempt", 2),
    ("attempt-bool", binding_edit("run_attempt", True), "fragment_attempt", 2),
    ("name-index", case_index_disagrees_with_name, "fragment_name_mismatch", 2),
    ("two-fragments", case_mutant_in_two_fragments, "mutant_in_two_fragments", 2),
    ("wrong-fragment", case_mutant_in_wrong_fragment, "mutant_in_wrong_fragment", 2),
    ("no-result", case_planned_without_result, "planned_mutant_without_result", 2),
    ("stored-counts", case_stored_counts_mismatch, "fragment_count_mismatch", 2),
    ("fragment-hash", case_hash_mismatch, "fragment_hash_mismatch", 2),
    ("plan-hash-mismatch", case_plan_hash_mismatch, "plan_hash_mismatch", None),
    ("plan-n-vs-weights", case_plan_n_disagrees_with_its_weights, "plan_inconsistent", None),
    ("plan-stored-n", case_plan_stored_n_is_wrong, "plan_inconsistent", None),
    ("plan-stored-w-f", case_plan_stored_w_f_is_wrong, "plan_inconsistent", None),
    ("not-the-partition", case_valid_cover_that_is_not_the_partition, "plan_inconsistent", None),
    ("plan-not-bound", case_plan_not_bound, "plan_not_bound", None),
    ("plan-internal", case_plan_internal_errors, "plan_internal_error", None),
]


@pytest.mark.parametrize("label,inject,code,shard", CASES, ids=[c[0] for c in CASES])
def test_merge_refuses_each_injected_case(label, inject, code, shard):
    plan = band_plan(3)
    frags = fragment_set(plan)
    inject(plan, frags)
    records, problems = do_merge(plan, frags)
    hits = [p for p in problems if p["code"] == code]
    assert hits, (code, codes(problems))
    if shard is not None:
        assert any(f"shard {shard}" in p["message"] and p.get("shard") == shard for p in hits)
    assert exit_of(records) == 3
    assert ncg.decide(records, [], ncg.THRESHOLDS)["overall"] != "pass"


def test_attempt_below_the_plans_is_refused():
    plan = band_plan(3)
    plan = finish_plan(plan["files"], attempt=2)
    frags = fragment_set(plan, attempt=1)
    _, problems = do_merge(plan, frags, binding=dict(BIND, run_attempt=2))
    assert codes(problems) == ["fragment_attempt"] * 3
    assert all(p["shard"] in (1, 2, 3) for p in problems)


def test_a_plan_from_a_later_attempt_than_this_run_is_not_bound():
    plan = finish_plan(band_plan(3)["files"], attempt=3)
    _, problems = do_merge(plan, fragment_set(plan, attempt=3), binding=dict(BIND, run_attempt=2))
    assert "plan_not_bound" in codes(problems)


def test_merge_names_every_problem_instead_of_stopping_at_the_first():
    plan = band_plan(3)
    frags = fragment_set(plan)
    del frags["new-code-fragment-1-of-3"]
    frags["new-code-fragment-3-of-3"]["status"] = "timeout"
    frags["stray"] = "x"
    _, problems = do_merge(plan, frags, shard_result="failure")
    assert {"fragment_missing", "fragment_hash_mismatch", "fragment_extra"} <= set(codes(problems))
    assert "shard_job_not_successful" in codes(problems)


def test_an_unreadable_plan_gives_a_problem_and_no_files():
    for bad in (None, [], {"schema": "x"}, {**band_plan(3), "N": 99}):
        records, problems = do_merge(bad, {})
        assert "plan_unreadable" in codes(problems)
        assert records["files"] == [] and records["shards"] is None
        assert exit_of(records) == 3


@pytest.mark.parametrize(
    "mangle",
    [
        lambda p: p["files"].append("x"),
        lambda p: p["files"][0].pop("function_cost_ms"),
        lambda p: p["files"][0].update(to_shards="yes"),
        lambda p: p["files"][0].update(gated_mutant_names=["a", "a"]),
        lambda p: p["assignment"].append({"index": 1}),
        lambda p: p.update(internal_errors=["x"]),
        lambda p: p.update(capped="no"),
        lambda p: p.update(W_ms=True),
        lambda p: p.update(seconds="slow"),
        lambda p: p["files"][0].update(fail_reasons=[{"code": "nope", "message": "m"}]),
    ],
)
def test_plan_shape_errors_are_plan_unreadable_never_an_exception(mangle):
    plan = band_plan(3)
    mangle(plan)
    assert ncs.plan_shape_error(plan) is not None
    records, problems = do_merge(plan, {})
    assert codes(problems)[0] == "plan_unreadable" and exit_of(records) == 3


@pytest.mark.parametrize(
    "mangle",
    [
        lambda d: d.update(status="done"),
        lambda d: d.update(timeout={"phase": 1}),
        lambda d: d.update(files=[1]),
        lambda d: d["files"][0].update(killed=-1),
        lambda d: d["files"][0].update(status_by_key={"bad key": "killed"}),
        lambda d: d["files"][0]["status_by_key"].update({key("a.py", 1): "weird"}),
        lambda d: d["files"][0].update(mutation_reason="elsewhere"),
        lambda d: d["files"][0].update(
            fail_reasons=[{"code": "coverage_below_threshold", "message": "x"}]
        ),
        lambda d: d["files"][0].update(path_load_findings=["x"]),
        lambda d: d["files"][0].update(isolation_failure={"stage": "x"}),
        lambda d: d["files"][0].update(finished="yes"),
        lambda d: d["files"].append(dict(d["files"][0])),
        lambda d: d["files"][0].update(seconds=True),
        lambda d: d.update(seconds="slow"),
        lambda d: d.pop("binding"),
    ],
)
def test_fragment_shape_errors_are_fragment_unreadable_never_an_exception(mangle):
    plan = band_plan(3)
    frags = fragment_set(plan)
    doc = frags["new-code-fragment-2-of-3"]
    mangle(doc)
    rehash_ok = isinstance(doc.get("files"), list)
    if rehash_ok and "binding" in doc:
        rehash(doc)
    assert ncs.fragment_shape_error(doc) is not None
    _, problems = do_merge(plan, frags)
    assert "fragment_unreadable" in codes(problems)


def test_a_plan_with_a_valid_cover_that_is_not_the_partition_is_plan_inconsistent():
    """SH-PART-EQ: one mutant moved across a cut, hash recomputed, N right, indices right."""
    plan = band_plan(3)
    frags = fragment_set(plan)
    case_valid_cover_that_is_not_the_partition(plan, frags)
    names = sorted(n for shard in plan["assignment"] for m in shard["members"] for n in m["names"])
    wanted = sorted(n for f in plan["files"] for n in f["gated_mutant_names"])
    assert names == wanted and plan["N"] == 3
    assert plan["plan_hash"] == ncs.plan_hash(plan)
    _, problems = do_merge(plan, frags)
    assert "plan_inconsistent" in codes(problems)
    assert "plan_hash_mismatch" not in codes(problems)


def test_a_plan_whose_stored_n_is_not_the_recomputed_n_is_plan_inconsistent():
    plan = band_plan(3)
    frags = fragment_set(plan)
    case_plan_stored_n_is_wrong(plan, frags)
    problems = do_merge(plan, frags)[1]
    assert "plan_inconsistent" in codes(problems)
    assert any("N is 2" in p["message"] for p in problems)


def test_merge_refuses_same_n_fragment_from_earlier_plan():
    """SH-RERUN-N(b): same gated sha, pr, run id and N; a different plan hash."""
    plan = band_plan(3)
    earlier = finish_plan(plan["files"], python="3.13")
    assert earlier["N"] == 3 and earlier["plan_hash"] != plan["plan_hash"]
    frags = fragment_set(plan)
    frags["new-code-fragment-2-of-3"] = fragment(earlier, 2)
    records, problems = do_merge(plan, frags)
    stale = [p for p in problems if p["code"] == "fragment_not_bound"]
    assert [p["shard"] for p in stale] == [2] and "plan_hash" in stale[0]["message"]
    assert exit_of(records) == 3


# --------------------------------------------------------------------------
# AC-39(a): the aggregate shard result
# --------------------------------------------------------------------------


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "timed_out", ""])
def test_merge_non_success_shard_result_fails(result):
    plan = band_plan(3)
    records, problems = do_merge(plan, fragment_set(plan), shard_result=result)
    assert codes(problems) == ["shard_job_not_successful"]
    assert "no fragment identifies the failing shard" in problems[0]["message"]
    assert exit_of(records) == 3


def test_a_non_success_shard_result_with_a_missing_fragment_names_that_shard():
    plan = band_plan(3)
    frags = fragment_set(plan)
    del frags["new-code-fragment-2-of-3"]
    _, problems = do_merge(plan, frags, shard_result="failure")
    assert codes(problems) == ["fragment_missing", "shard_job_not_successful"]
    assert "shard(s) 2" in problems[1]["message"]


def test_a_non_success_plan_result_is_its_own_problem_and_no_fragment_is_judged():
    plan = band_plan(3)
    records, problems = do_merge(plan, fragment_set(plan), plan_result="failure")
    assert codes(problems) == ["plan_not_successful"]
    assert exit_of(records) == 3 and [f["path"] for f in records["files"]] == [
        f["path"] for f in plan["files"]
    ]


# --------------------------------------------------------------------------
# AC-42: every failed shard is named, completed shards stay visible
# --------------------------------------------------------------------------


def test_merge_names_every_failed_shard_and_keeps_completed():
    plan = band_plan(4, files=4)
    assert plan["N"] == 4
    frags = fragment_set(plan)
    timeout = fragment(plan, 2, status="timeout")
    timeout["timeout"] = {"phase": "mutmut_run", "file": "scripts/framework/f1.py", "message": "x"}
    timeout["files"][0]["finished"] = False
    timeout["files"][0]["status_by_key"] = {}
    timeout["files"][0].update(killed=0, total=0, mutant_status_counts={})
    frags["new-code-fragment-2-of-4"] = rehash(timeout)
    broken = fragment(
        plan,
        3,
        status="internal_error",
        internal_errors=[
            {"code": "internal_error", "message": "boom", "file": "scripts/framework/f2.py"}
        ],
    )
    broken["files"] = []
    frags["new-code-fragment-3-of-4"] = rehash(broken)
    records, problems = do_merge(plan, frags)
    internal = [p for p in problems if p["code"] == "shard_internal_error"]
    assert [(p["shard"], p["file"]) for p in internal] == [(3, "scripts/framework/f2.py")]
    assert "boom" in internal[0]["message"] and "shard 3" in internal[0]["message"]
    assert exit_of(records) == 3
    rows = {r["index"]: r for r in records["shards"]["per_shard"]}
    assert [rows[i]["status"] for i in (1, 2, 3, 4)] == [
        "complete",
        "timeout",
        "internal_error",
        "complete",
    ]
    held_by_two = {m["path"] for m in plan["assignment"][1]["members"]}
    for rec in records["files"]:
        if rec["path"] in held_by_two:
            assert rec["mutation_ran"] is False and rec["mutation_reason"] == "timeout"
            assert "mutation_timeout" in [r["code"] for r in rec["fail_reasons"]]
            assert rec["mutants_total"] is None and rec["mutant_score_pct"] is None
            assert any(s["index"] == 2 and s["status"] == "timeout" for s in rec["shards"])
    summary = ncg.render_summary(
        ncg.verdict_document(records, ncg.decide(records, [], ncg.THRESHOLDS))
    )
    assert "(not final)" in summary and "timeout" in summary and "boom" in summary
    assert "| 1 | complete |" in summary and "| 4 | complete |" in summary


# --------------------------------------------------------------------------
# AC-45(c) and the timeout rule
# --------------------------------------------------------------------------


def heavy_and_light():
    names = {
        path: [key(path, i) for i in range(20)]
        for path in ("scripts/framework/a.py", "scripts/framework/b.py")
    }
    heavy = finish_plan([plan_file(p, [(n, 1_000_000) for n in ns]) for p, ns in names.items()])
    light = finish_plan([plan_file(p, [(n, 10) for n in ns]) for p, ns in names.items()])
    return heavy, light


def test_capped_merge_matches_uncapped_for_fitting_shards():
    heavy, light = heavy_and_light()
    assert (heavy["N"], heavy["capped"]) == (8, True) and (light["N"], light["capped"]) == (
        1,
        False,
    )
    assert all(s["members"] for s in heavy["assignment"])
    kill = lambda name: sum(map(ord, name)) % 5 != 0  # noqa: E731
    frags = fragment_set(heavy, killed=kill)
    overrun = fragment(heavy, 5, status="timeout")
    overrun["timeout"] = {"phase": "mutmut_run", "file": "scripts/framework/b.py", "message": ""}
    frags["new-code-fragment-5-of-8"] = rehash(overrun)
    capped, problems = do_merge(heavy, frags)
    assert problems == []
    uncapped, light_problems = do_merge(light, fragment_set(light, killed=kill))
    assert light_problems == []
    held = {m["path"] for m in heavy["assignment"][4]["members"]}
    fitting = "scripts/framework/a.py"
    assert fitting not in held
    got, want = file_of(capped, fitting), file_of(uncapped, fitting)
    for field in ("mutants_killed", "mutants_total", "mutant_score_pct", "mutant_status_counts"):
        assert got[field] == want[field]
    assert got["mutation_ran"] is True and got["fail_reasons"] == []
    late = file_of(capped, "scripts/framework/b.py")
    assert late["mutation_ran"] is False and late["mutation_reason"] == "timeout"
    message = late["fail_reasons"][0]["message"]
    assert "shard 5 of 8" in message and "split the PR" in message
    assert "scripts/framework/b.py" in message and "mutmut_run of scripts/framework/b.py" in message
    verdict = ncg.decide(capped, [], ncg.THRESHOLDS)
    assert verdict["exit_code"] == 1 and verdict["overall"] == "fail"
    summary = ncg.render_summary(ncg.verdict_document(capped, verdict))
    assert "capped true" in summary and "exceeds 8 x 15; running 8 shards" in summary
    assert "est_mutation_ms" in summary and "est_fixed_ms" in summary


def test_a_timeout_names_every_overrunning_shard_that_holds_the_file_once():
    heavy, _ = heavy_and_light()
    frags = fragment_set(heavy)
    for index in (6, 7):
        late = fragment(heavy, index, status="timeout")
        late["timeout"] = {"phase": "collect", "file": "", "message": ""}
        frags[f"new-code-fragment-{index}-of-8"] = rehash(late)
    records, _ = do_merge(heavy, frags)
    rec = file_of(records, "scripts/framework/b.py")
    timeouts = [r for r in rec["fail_reasons"] if r["code"] == "mutation_timeout"]
    assert len(timeouts) == 1
    assert "shard 6 of 8" in timeouts[0]["message"] and "shard 7 of 8" in timeouts[0]["message"]
    assert "ran out in collect)" in timeouts[0]["message"]
    assert "25-minute" in timeouts[0]["message"]


def test_shard_time_fail_reasons_make_the_file_not_final_and_pass_through_bounded():
    plan = band_plan(3)
    frags = fragment_set(plan)
    doc = frags["new-code-fragment-2-of-3"]
    entry = doc["files"][0]
    entry.update(
        fail_reasons=[{"code": "path_loaded_module", "message": "m" * 5000}],
        mutation_reason="path_load",
        status_by_key={},
        killed=0,
        total=0,
        mutant_status_counts={},
        path_load_findings=[
            {"importer": "i", "loaded_as": "l", "canonical": "c", "via": "v", "phase": "p"}
        ],
    )
    rehash(doc)
    records, problems = do_merge(plan, frags)
    assert problems == []
    rec = file_of(records, entry["path"])
    assert rec["mutation_ran"] is False and rec["mutation_reason"] == "path_load"
    assert rec["mutants_total"] is None and rec["mutant_score_pct"] is None
    assert [r["code"] for r in rec["fail_reasons"]] == ["path_loaded_module"]
    assert len(rec["fail_reasons"][0]["message"]) <= ncg.MAX_MESSAGE_CHARS
    assert rec["path_load_findings"][0]["importer"] == "i"
    assert exit_of(records) == 1


def test_isolation_evidence_is_copied_bounded_from_the_lowest_shard_that_has_it():
    plan = band_plan(3)
    frags = fragment_set(plan)
    isolated = {
        "stage": "stats",
        "node_ids": ["tests/t.py::x"],
        "summary_lines": ["FAILED tests/t.py::x"] * 40,
        "output_tail": "t" * 20_000,
    }
    for index in (1, 3):
        doc = frags[f"new-code-fragment-{index}-of-3"]
        doc["files"][0].update(
            fail_reasons=[{"code": "selected_test_fails_in_isolation", "message": f"s{index}"}],
            mutation_reason="blocked_by:selected_test_fails_in_isolation",
            isolation_failure=isolated,
            status_by_key={},
            killed=0,
            total=0,
            mutant_status_counts={},
        )
        rehash(doc)
    records, _ = do_merge(plan, frags)
    rec = next(r for r in records["files"] if r["isolation_failure"] is not None)
    assert [r["message"] for r in rec["fail_reasons"]] == ["s1"]
    assert len(rec["isolation_failure"]["summary_lines"]) == ncg.MAX_SUMMARY_LINES
    assert len(rec["isolation_failure"]["output_tail"]) <= ncg.ISOLATION_TAIL_CHARS
    assert rec["mutation_reason"] == "blocked_by:selected_test_fails_in_isolation"


# --------------------------------------------------------------------------
# AC-44: cost and timing fields
# --------------------------------------------------------------------------


def test_records_carry_shard_and_cost_timings():
    plan = band_plan(3)
    frags = fragment_set(plan)
    records, problems = do_merge(plan, frags)
    assert problems == []
    shards = records["shards"]
    assert (shards["N"], shards["capped"], shards["N_max"], shards["T_minutes"]) == (
        3,
        False,
        8,
        15,
    )
    assert shards["W_ms"] == plan["W_ms"] and shards["plan_hash"] == plan["plan_hash"]
    assert shards["W_ci_minutes"] == ncs.ci_minutes(plan["W_ms"])
    for row, assigned in zip(shards["per_shard"], plan["assignment"]):
        doc = frags[f"new-code-fragment-{row['index']}-of-3"]
        assert row["seconds"] == 30.0 and row["job_seconds"] == 40
        assert row["est_mutation_ms"] == assigned["est_mutation_ms"]
        assert row["est_fixed_ms"] == assigned["est_fixed_ms"]
        assert row["fragment_sha256"] == doc["fragment_sha256"]
        assert row["run_attempt"] == 1 and row["status"] == "complete"
        assert row["files"] == [m["path"] for m in assigned["members"]]
    assert records["plan_hash"] == plan["plan_hash"]
    assert (records["plan_seconds"], records["plan_job_seconds"]) == (5.0, 9)
    assert records["merge_verdict_seconds"] is None
    assert ncs.runner_minutes_total(records, 12.0) == round((9 + 3 * 40 + 12.0) / 60, 1)
    assert ncs.runner_minutes_total(records, 12.0) == 2.4


def test_runner_minutes_total_is_none_when_any_job_seconds_is_unknown():
    plan = band_plan(3)
    frags = fragment_set(plan)
    frags["new-code-fragment-2-of-3"] = rehash(
        dict(frags["new-code-fragment-2-of-3"], job_seconds=None)
    )
    records, _ = do_merge(plan, frags)
    assert ncs.runner_minutes_total(records, 1.0) is None
    summary_doc = ncg.verdict_document(records, ncg.decide(records, [], ncg.THRESHOLDS))
    summary_doc["runner_minutes_total"] = None
    assert "no job-start time for: shard 2" in ncg.render_summary(summary_doc)
    plain, _ = do_merge(plan, fragment_set(plan))
    plain["plan_job_seconds"] = None
    assert ncs.runner_minutes_total(plain, 1.0) is None
    assert ncs.runner_minutes_total(plain | {"plan_job_seconds": 3}, None) is None
    assert ncs.runner_minutes_total({"plan_job_seconds": 60, "shards": None}, 60) == 2.0


def test_every_cost_and_timing_field_stays_out_of_records_sha256():
    plan = band_plan(3)
    frags = fragment_set(plan)
    first, _ = do_merge(plan, frags)
    changed = copy.deepcopy(frags)
    for doc in changed.values():
        doc["job_seconds"] = 7
        doc["seconds"] = 1.0
        doc["files"][0]["seconds"] = 99.0
        doc["files"][0]["mutmut_seconds"] = 99.0
        rehash(doc)
    second, _ = do_merge(plan, changed)
    assert first["records_sha256"] == second["records_sha256"]
    assert ncg.UNHASHED_FIELDS >= {
        "shards",
        "plan_hash",
        "N",
        "job_seconds",
        "plan_job_seconds",
        "runner_minutes_total",
    }
    assert first["files"][0]["N"] == 3
    only_partition = copy.deepcopy(first["files"])
    for rec in only_partition:
        rec["N"], rec["plan_hash"], rec["shards"] = 1, "x", []
    assert ncg.records_sha256(only_partition) == first["records_sha256"]


def test_fragment_summary_lists_each_file_and_each_internal_error():
    plan = band_plan(3)
    doc = fragment(plan, 1, status="internal_error")
    doc["internal_errors"] = [{"code": "internal_error", "message": "boom"}]
    doc["files"][0]["finished"] = False
    text = ncs.fragment_summary(doc)
    assert text.startswith("shard 1 of 3: internal_error\n")
    assert "(not finished)" in text and "- internal_error: boom" in text
    assert f"{doc['files'][0]['path']}: 10/10 killed of 10 assigned" in text


def test_a_plan_with_no_files_still_merges_to_a_pass_with_zero_gated_files():
    plan = finish_plan([])
    records, problems = do_merge(plan, fragment_set(plan))
    assert problems == [] and records["files"] == []
    assert records["shards"]["N"] == 1 and exit_of(records) == 0
    assert fragment_set(plan)["new-code-fragment-1-of-1"]["files"] == []
    summary = ncg.render_summary(
        ncg.verdict_document(records, ncg.decide(records, [], ncg.THRESHOLDS))
    )
    assert summary.startswith("No gated files in this PR.")


def test_files_decided_in_the_cheap_phase_pass_through_the_merge_unchanged():
    blocked = plan_file("scripts/framework/blocked.py", [], to_shards=False)
    blocked["fail_reasons"] = [ncg.fail_reason("path_loaded_module", "static")]
    blocked["mutation_reason"] = "path_load"
    plan = finish_plan([blocked, uniform("scripts/framework/a.py", 5, 100, "a")])
    records, problems = do_merge(plan, fragment_set(plan))
    assert problems == []
    rec = file_of(records, "scripts/framework/blocked.py")
    assert rec["shards"] == [] and rec["mutation_reason"] == "path_load"
    assert [r["code"] for r in rec["fail_reasons"]] == ["path_loaded_module"]
    assert set(rec) == set(ncg.FILE_FIELDS)
    assert exit_of(records) == 1


# --------------------------------------------------------------------------
# Merge integrity: counts recomputed from statuses; timeout keeps other shards' reasons
# --------------------------------------------------------------------------


def test_plan_hash_covers_every_binding_field():
    """SH-HASH(a): each plan binding field alone moves the plan hash."""
    plan = band_plan(3)
    for field, value in (
        ("mode", "local"),
        ("gated_sha", "e" * 40),
        ("pr_head_sha", "e" * 40),
        ("base_sha", "e" * 40),
        ("gated_tree", "e" * 40),
        ("pr", 8),
        ("run_id", "100"),
        ("run_attempt", 2),
    ):
        assert field in plan["binding"], field
        other = copy.deepcopy(plan)
        other["binding"][field] = value
        assert ncs.plan_hash(other) != plan["plan_hash"], field


def test_fragment_hash_covers_binding_index():
    """SH-HASH(b)."""
    frag = fragment(band_plan(3), 1)
    other = copy.deepcopy(frag)
    other["binding"]["index"] = 2
    assert ncs.fragment_hash(other) != frag["fragment_sha256"]


def test_document_drop_set_is_timing_only():
    assert not {"N", "plan_hash", "shards", "isolation_failure"} & ncs.DOCUMENT_HASH_DROPS


def test_merge_counts_from_status_by_key():
    """SH-RECOUNT: the merge's numbers come from the statuses, and a stored count cannot move them."""
    plan = band_plan(3)
    honest = fragment_set(plan, killed=lambda name: sum(map(ord, name)) % 3 != 0)
    good, good_problems = do_merge(plan, honest)
    assert "fragment_count_mismatch" not in codes(good_problems)
    bad_frags = copy.deepcopy(honest)
    path = plan["assignment"][1]["members"][0]["path"]
    doc = bad_frags["new-code-fragment-2-of-3"]
    entry = next(e for e in doc["files"] if e["path"] == path)
    entry["killed"] = entry["total"]
    rehash(doc)
    bad, problems = do_merge(plan, bad_frags)
    hits = [p for p in problems if p["code"] == "fragment_count_mismatch"]
    assert hits and hits[0]["shard"] == 2 and hits[0]["file"] == path
    assert exit_of(bad) == 3
    want, got = file_of(good, path), file_of(bad, path)
    for field in ("mutants_killed", "mutants_total", "mutant_score_pct", "mutant_status_counts"):
        assert got[field] == want[field], field
    assert [(r["index"], r["total"]) for r in got["shards"]] == [
        (r["index"], r["total"]) for r in want["shards"]
    ]
    assert exit_of(good) in (0, 1)


def test_a_fragment_whose_killed_count_disagrees_with_its_statuses_does_not_merge():
    plan = band_plan(3)
    frags = fragment_set(plan, killed=lambda name: False)
    doc = frags["new-code-fragment-1-of-3"]
    doc["files"][0]["killed"] = doc["files"][0]["total"]
    rehash(doc)
    _, problems = do_merge(plan, frags)
    hits = [p for p in problems if p["code"] == "fragment_count_mismatch"]
    assert hits and hits[0]["shard"] == 1


def test_a_timeout_keeps_the_shard_time_reasons_of_the_files_other_complete_shards():
    heavy, _ = heavy_and_light()
    frags = fragment_set(heavy)
    late = fragment(heavy, 6, status="timeout")
    late["timeout"] = {"phase": "collect", "file": "", "message": ""}
    frags["new-code-fragment-6-of-8"] = rehash(late)
    other = frags["new-code-fragment-7-of-8"]
    entry = next(e for e in other["files"] if e["path"] == "scripts/framework/b.py")
    entry.update(
        fail_reasons=[{"code": "path_loaded_module", "message": "loaded"}],
        mutation_reason="path_load",
        status_by_key={},
        killed=0,
        total=0,
        mutant_status_counts={},
    )
    rehash(other)
    records, _ = do_merge(heavy, frags)
    rec = file_of(records, "scripts/framework/b.py")
    assert rec["mutation_reason"] == "timeout"
    assert {"mutation_timeout", "path_loaded_module"} <= {r["code"] for r in rec["fail_reasons"]}


def test_a_timed_out_holders_own_reason_is_in_the_union_once_with_the_merges_timeout():
    """SH-UNION (ADR-2304 2i D-3): a timeout fragment's recorded reason is kept, not dropped."""
    heavy, _ = heavy_and_light()
    path = "scripts/framework/b.py"
    holders = [
        i
        for i, shard in enumerate(heavy["assignment"], 1)
        if any(m["path"] == path for m in shard["members"])
    ]
    frags = fragment_set(heavy)
    late = fragment(heavy, holders[0], status="timeout")
    late["timeout"] = {"phase": "mutmut_run", "file": path, "message": "x"}
    entry = next(e for e in late["files"] if e["path"] == path)
    entry["fail_reasons"] = [{"code": "path_loaded_module", "message": "loaded"}]
    frags[f"new-code-fragment-{holders[0]}-of-{heavy['N']}"] = rehash(late)
    records, _ = do_merge(heavy, frags)
    reasons = [r["code"] for r in file_of(records, path)["fail_reasons"]]
    assert reasons.count("mutation_timeout") == 1
    assert reasons.count("path_loaded_module") == 1


def test_the_merges_own_timeout_wins_over_a_fragment_carried_one_and_reasons_are_deduped():
    """SH-UNION: one `mutation_timeout`, the merge's wording; other codes once."""
    heavy, _ = heavy_and_light()
    path = "scripts/framework/b.py"
    holders = [
        i
        for i, shard in enumerate(heavy["assignment"], 1)
        if any(m["path"] == path for m in shard["members"])
    ]
    frags = fragment_set(heavy)
    late = fragment(heavy, holders[0], status="timeout")
    late["timeout"] = {"phase": "mutmut_run", "file": path, "message": "x"}
    carried = [
        {"code": "mutation_timeout", "message": "FRAGMENT-CARRIED"},
        {"code": "path_loaded_module", "message": "loaded"},
    ]
    next(e for e in late["files"] if e["path"] == path)["fail_reasons"] = carried
    frags[f"new-code-fragment-{holders[0]}-of-{heavy['N']}"] = rehash(late)
    if len(holders) > 1:
        other = frags[f"new-code-fragment-{holders[1]}-of-{heavy['N']}"]
        next(e for e in other["files"] if e["path"] == path)["fail_reasons"] = carried[:1]
        rehash(other)
    records, _ = do_merge(heavy, frags)
    reasons = file_of(records, path)["fail_reasons"]
    timeouts = [r for r in reasons if r["code"] == "mutation_timeout"]
    assert len(timeouts) == 1
    assert "FRAGMENT-CARRIED" not in timeouts[0]["message"]
    assert f"shard {holders[0]} of {heavy['N']}" in timeouts[0]["message"]
    assert "split the PR" in timeouts[0]["message"]
    assert [r["code"] for r in reasons].count("path_loaded_module") == 1
