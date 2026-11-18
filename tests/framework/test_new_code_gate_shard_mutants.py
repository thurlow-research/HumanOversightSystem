"""Behaviour pins for `new_code_gate_shard`, found by a mutation run of the gate itself.

Pure-function behaviour of the cost partition, the mutant-name prefix and the canonical
document hash, which the shard tests left unpinned (the hash is the wire format that binds a
fragment to its plan, so its canonical byte form is asserted against a literal digest).
"""

from scripts.framework import new_code_gate_shard as ncs


def test_mutant_prefix_is_the_text_before_the_first_separator():
    assert ncs.mutant_prefix("x_add__mutmut_3") == "x_add"
    assert ncs.mutant_prefix("x_a__mutmut_b__mutmut_2") == "x_a"
    assert ncs.mutant_prefix("x_add") == "x_add"


def test_partition_cuts_equal_weights_into_equal_chunks():
    names = {"a.py": ["m1", "m2", "m3", "m4"]}
    weights = {"a.py": {"m1": 1, "m2": 1, "m3": 1, "m4": 1}}
    got = ncs.partition(weights, names, 2)
    assert [(s["index"], s["est_mutation_ms"]) for s in got] == [(1, 2), (2, 2)]
    assert [m["names"] for s in got for m in s["members"]] == [["m1", "m2"], ["m3", "m4"]]


def test_partition_advances_a_shard_once_it_reaches_its_share_of_the_total():
    names = {"a.py": ["m1", "m2", "m3"], "b.py": ["m4"]}
    weights = {"a.py": {"m1": 5, "m2": 1, "m3": 1}, "b.py": {"m4": 1}}
    got = ncs.partition(weights, names, 4)
    assert [s["est_mutation_ms"] for s in got] == [5, 1, 1, 1]
    assert [[(m["path"], m["names"]) for m in s["members"]] for s in got] == [
        [("a.py", ["m1"])],
        [("a.py", ["m2"])],
        [("a.py", ["m3"])],
        [("b.py", ["m4"])],
    ]


def test_partition_leaves_trailing_shards_empty_when_the_work_is_one_mutant():
    got = ncs.partition({"a.py": {"m": 7}}, {"a.py": ["m"]}, 3)
    assert [(s["index"], s["est_mutation_ms"], s["members"]) for s in got] == [
        (1, 7, [{"path": "a.py", "names": ["m"]}]),
        (2, 0, []),
        (3, 0, []),
    ]


def test_document_hash_is_the_sha256_of_the_canonical_compact_sorted_ascii_json():
    doc = {"z": True, "a": [1, {"b": "café"}], "plan_hash": "ignored"}
    assert (
        ncs.document_hash(doc, "plan_hash")
        == "755a75ffea7b2b6e0ee82d17b4cda0196006afaa375110afe8872cb38e73d217"
    )


def test_document_hash_ignores_its_own_field_and_timing_keys_at_any_depth():
    base = {"a": [1, {"b": 2}], "z": 1}
    noisy = {
        "a": [1, {"b": 2, "started_at": "t0"}],
        "z": 1,
        "finished_at": "t1",
        "plan_hash": "x",
    }
    assert ncs.document_hash(noisy, "plan_hash") == ncs.document_hash(base, "plan_hash")
    assert ncs.plan_hash(noisy) == ncs.document_hash(base, "plan_hash")
    assert ncs.fragment_hash({**base, "fragment_sha256": "q"}) == ncs.document_hash(
        base, "fragment_sha256"
    )
