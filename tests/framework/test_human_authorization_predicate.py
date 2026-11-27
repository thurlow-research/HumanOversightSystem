"""Tests for human_authorization.decide (TD-2101 §7.1, T-P-*). Pure: no network, no git."""

from __future__ import annotations

import builtins
import dataclasses
import socket
import subprocess
import time

import pytest

from scripts.framework import human_authorization as ha
from scripts.framework.human_authorization import Comment, Deletion, decide, render_form

CO = frozenset({"scottthurlow"})
BOTS = frozenset(
    {
        "hos-worker-hos[bot]",
        "hos-overseer-hos[bot]",
        "scottthurlow-claude[bot]",
        "copilot[bot]",
        "pat-machine-user",
    }
)
B = "patch:" + "a" * 40
OTHER_B = "patch:" + "b" * 40
FILES = ("scripts/x.py", "docs/y.md")
T1, T2, T3 = "2026-10-20T10:00:00Z", "2026-10-20T11:00:00Z", "2026-10-20T12:00:00Z"


def _c(id, login, type="User", created=T1, updated=None, body="", issue=2101, edited=False):
    return Comment(
        id=id,
        url=f"https://github.com/o/r/issues/{issue}#issuecomment-{id}",
        login=login,
        user_type=type,
        created_at=created,
        updated_at=updated or created,
        body=body,
        issue_number=issue,
        edited=edited,
    )


def _form(step=5, binding=B, items=("C7",), files=FILES):
    return render_form(step, binding, items, files)


def _decide(
    comments, step=5, binding=B, required=("C7",), files=FILES, co=CO, bots=BOTS, deletions=()
):
    return decide(comments, co, bots, step, binding, required, files, deletions=deletions)


def _del(eid, at, author="scottthurlow", issue=2101):
    return Deletion(event_id=eid, deleted_at=at, author_login=author, issue_number=issue)


def _reasons(v):
    return [r.reason for r in v.refusals]


def test_t_p_1_codeowner_authorizes():
    v = _decide([_c(1, "ScottThurlow", body=_form())])
    assert v.authorized and v.covered == ("C7",) and v.unmet == ()
    assert v.accepted is not None and v.accepted.overlap == ("docs/y.md", "scripts/x.py")
    assert v.refusals == ()


@pytest.mark.parametrize(
    "login,utype,reason",
    [
        ("scottthurlow-claude[bot]", "Bot", "bot-actor"),
        ("hos-worker-hos[bot]", "Bot", "bot-actor"),
        ("someapp[bot]", "Bot", "bot-actor"),
        ("pat-machine-user", "User", "bot-actor"),
        ("alice", "User", "not-codeowner"),
    ],
)
def test_t_p_2_to_6_actor_refusals(login, utype, reason):
    co = CO | {"pat-machine-user"}
    v = _decide([_c(1, login, type=utype, body=_form())], co=co)
    assert not v.authorized and v.covered == ()
    assert _reasons(v) == [reason]
    assert v.refusals[0].actor_type == utype


def test_t_p_7_body_naming_the_codeowner_is_not_authority():
    body = "authorized by ScottThurlow\n" + _form()
    # Not a candidate (first line is chatter): no act, no refusal.
    v = _decide([_c(1, "alice", body=body)])
    assert not v.authorized and v.refusals == ()
    v = _decide([_c(1, "alice", body=_form() + "\n---\nauthorized by ScottThurlow")])
    assert _reasons(v) == ["not-codeowner"]


def test_t_p_8_default_branch_set_governs_not_a_working_tree():
    v = _decide([_c(1, "alice", body=_form())], co=frozenset({"scottthurlow"}))
    assert _reasons(v) == ["not-codeowner"]


def test_t_p_9_edited_act_refused():
    v = _decide([_c(1, "scottthurlow", updated=T2, body=_form())])
    assert not v.authorized and _reasons(v) == ["edited"]
    assert v.governing.decision == "edited"


def test_t_p_10_deleted_act_absent_older_decline_stands():
    decline = _c(1, "scottthurlow", created=T1, body="/hos decline step=5")
    v = _decide([decline])
    assert not v.authorized and _reasons(v) == ["declined"]


def test_t_p_11_wrong_step():
    v = _decide([_c(1, "scottthurlow", body=_form(step=4))])
    assert not v.authorized and _reasons(v) == ["wrong-step"]
    ok = _c(1, "scottthurlow", created=T1, body=_form(step=5))
    other = _c(2, "scottthurlow", created=T2, body=_form(step=4))
    v = _decide([ok, other])
    assert v.authorized and _reasons(v) == ["wrong-step"]


def test_t_p_12_stale_binding():
    v = _decide([_c(1, "scottthurlow", body=_form(binding=OTHER_B))])
    assert not v.authorized and v.covered == () and _reasons(v) == ["stale"]


def test_t_p_13_authorize_then_decline():
    a = _c(1, "scottthurlow", created=T1, body=_form())
    d = _c(2, "scottthurlow", created=T2, body="/hos decline step=5")
    v = _decide([a, d])
    assert not v.authorized
    assert _reasons(v) == ["superseded", "declined"]


def test_t_p_14_decline_then_authorize():
    d = _c(1, "scottthurlow", created=T1, body="/hos decline step=5")
    a = _c(2, "scottthurlow", created=T2, body=_form())
    v = _decide([d, a])
    assert v.authorized and _reasons(v) == ["superseded"]


def test_t_p_15_malformed_newest_after_valid_act():
    a = _c(1, "scottthurlow", created=T1, body=_form())
    bad = _c(
        2, "scottthurlow", created=T2, body="/hos authorize step=5 binding=patch:zz\ncovers: C7"
    )
    v = _decide([a, bad])
    assert not v.authorized
    assert _reasons(v) == ["superseded", "malformed-latest"]
    assert v.refusals[1].detail == "bad-binding"
    assert v.governing.decision == "malformed"


def test_t_p_16_ties_ordered_by_id():
    a = _c(1, "scottthurlow", created=T1, body=_form())
    d = _c(2, "scottthurlow", created=T1, body="/hos decline step=5")
    assert not _decide([d, a]).authorized
    assert not _decide([a, d]).authorized


def test_t_p_17_reviewed_files_absent_empty_or_disjoint():
    no_files = "/hos authorize step=5 binding=" + B + "\ncovers: C7"
    empty = no_files + "\nreviewed_files:"
    disjoint = _form(files=("other/z.py",))
    for body in (no_files, empty, disjoint):
        v = _decide([_c(1, "scottthurlow", body=body)])
        assert _reasons(v) == ["no-overlap"], body


def test_t_p_18_path_matching_is_exact():
    def body(path):
        return f"/hos authorize step=5 binding={B}\ncovers: C7\nreviewed_files:\n  - {path}"

    for path in ("./scripts/x.py", '"scripts/x.py"'):
        assert _decide([_c(1, "scottthurlow", body=body(path))]).authorized, path
    for path in ("scripts/", "x.py", "Scripts/x.py"):
        v = _decide([_c(1, "scottthurlow", body=body(path))])
        assert _reasons(v) == ["no-overlap"], path


def test_t_p_19_spec_267_table():
    hdr = f"/hos authorize step=5 binding={B}\ncovers: C7\n"
    assert _decide(
        [_c(1, "scottthurlow", body=hdr + "reviewed_files:\n  - scripts/x.py\n  - nope.py")]
    ).authorized
    assert _reasons(
        _decide([_c(1, "scottthurlow", body=hdr + "reviewed_files:\n  - nope.py")])
    ) == ["no-overlap"]
    assert _reasons(_decide([_c(1, "scottthurlow", body=hdr)])) == ["no-overlap"]
    assert _reasons(_decide([_c(1, "scottthurlow", body=hdr + "reviewed_files:\n")])) == [
        "no-overlap"
    ]


def test_t_p_20_one_event_per_candidate():
    comments = [
        _c(1, "someapp[bot]", type="Bot", created="2026-10-20T09:00:00Z", body=_form()),  # bot
        _c(2, "alice", created="2026-10-20T09:01:00Z", body=_form()),  # not codeowner
        _c(3, "scottthurlow", created="2026-10-20T09:02:00Z", body=_form(step=9)),  # wrong step
        _c(
            4,
            "scottthurlow",
            created="2026-10-20T09:03:00Z",
            updated="2026-10-20T09:04:00Z",
            body=_form(),
        ),
        _c(
            5, "scottthurlow", created="2026-10-20T09:05:00Z", body="/hos authorize step=5"
        ),  # malformed
        _c(6, "scottthurlow", created="2026-10-20T09:06:00Z", body=_form()),  # superseded
        _c(7, "scottthurlow", created="2026-10-20T09:07:00Z", body=_form()),  # accepted
        _c(8, "scottthurlow", created="2026-10-20T09:08:00Z", body="thanks"),  # non-candidate
        _c(9, "alice", created="2026-10-20T09:09:00Z", body="hello"),
        _c(10, "someapp[bot]", type="Bot", created="2026-10-20T09:10:00Z", body="/hostile"),
    ]
    # Comment 8 is an unedited non-candidate: ignored. 7 is the governing act.
    v = _decide(comments)
    assert v.authorized and v.accepted.governing.comment_id == 7
    assert len(v.refusals) == 6
    assert sorted(r.comment_id for r in v.refusals) == [1, 2, 3, 4, 5, 6]
    assert {r.reason for r in v.refusals} == {
        "bot-actor",
        "not-codeowner",
        "wrong-step",
        "edited",
        "malformed",
        "superseded",
    }


def test_t_p_21_partial_coverage_bf_item_unmet():
    body = _form(items=("C10:new-user-flow-or-route",))
    v = _decide(
        [_c(1, "scottthurlow", body=body)],
        required=("C10:new-user-flow-or-route", "BF:dep-mapper-low"),
    )
    assert not v.authorized
    assert v.covered == ("C10:new-user-flow-or-route",) and v.unmet == ("BF:dep-mapper-low",)


def test_t_p_22_each_c10_signal_is_separate():
    v = _decide([_c(1, "scottthurlow", body=_form(items=("C10:a",)))], required=("C10:a", "C10:b"))
    assert v.unmet == ("C10:b",) and v.covered == ("C10:a",)


def test_t_p_23_decline_edited_into_chatter_still_participates():
    a = _c(1, "scottthurlow", created=T1, body=_form())
    d = _c(2, "scottthurlow", created=T2, updated=T3, body="hello")
    v = _decide([a, d])
    assert not v.authorized
    assert _reasons(v) == ["superseded", "edited"] and v.refusals[1].detail == "non-candidate"
    assert v.governing.decision == "edited"


def test_t_p_24_decline_edited_to_another_step_still_participates():
    a = _c(1, "scottthurlow", created=T1, body=_form())
    d = _c(2, "scottthurlow", created=T2, updated=T3, body="/hos decline step=99")
    v = _decide([a, d])
    assert not v.authorized and _reasons(v) == ["superseded", "edited"]


def test_t_p_25_older_edited_chatter_has_no_effect():
    chatter = _c(1, "scottthurlow", created=T1, updated=T2, body="hello")
    a = _c(2, "scottthurlow", created=T3, body=_form())
    v = _decide([chatter, a])
    assert v.authorized and v.refusals == ()


def test_t_p_26_no_accumulation():
    a1 = _c(1, "scottthurlow", created=T1, body=_form(items=("C7",)))
    a2 = _c(2, "scottthurlow", created=T2, body=_form(items=("BF:x",)))
    v = _decide([a1, a2], required=("C7", "BF:x"))
    assert v.covered == ("BF:x",) and v.unmet == ("C7",) and not v.authorized


def test_t_p_27_missing_user_is_not_codeowner():
    v = _decide([_c(1, "", type="", body=_form())])
    assert _reasons(v) == ["not-codeowner"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"co": frozenset()},
        {"bots": frozenset()},
        {"required": ()},
        {"binding": "patch:xyz"},
        {"required": ("C7", "C7")},
        {"required": ("not an item",)},
        {"co": frozenset({"MixedCase"})},
    ],
)
def test_t_p_28_preconditions(kwargs):
    with pytest.raises(ValueError):
        _decide([], **kwargs)


def test_t_p_29_decide_is_pure(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("I/O attempted")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(builtins, "open", boom)
    monkeypatch.setattr(time, "time", boom)
    monkeypatch.setattr(ha, "_run_gh_get", boom)
    monkeypatch.setattr(ha, "_run_gh_graphql", boom)
    monkeypatch.setattr(ha, "_run_git", boom)
    monkeypatch.setattr(ha, "_audit_write", boom)
    assert _decide([_c(1, "scottthurlow", body=_form())]).authorized


def test_t_p_30_authorization_required_banner_is_not_a_candidate():
    v = _decide([_c(1, "scottthurlow", body="Authorization required: release v0.7.0\n" + _form())])
    assert not v.authorized and v.refusals == () and v.governing is None


def test_refusals_sorted_by_created_then_id():
    comments = [
        _c(9, "alice", created=T2, body=_form()),
        _c(3, "alice", created=T2, body=_form()),
        _c(5, "alice", created=T1, body=_form()),
    ]
    v = _decide(comments)
    assert [r.comment_id for r in v.refusals] == [5, 3, 9]


def test_content_sha256_is_of_the_exact_body():
    import hashlib

    body = _form() + "\n"
    v = _decide([_c(1, "alice", body=body)])
    assert v.refusals[0].content_sha256 == hashlib.sha256(body.encode()).hexdigest()


def test_lone_surrogate_body_does_not_crash():
    v = _decide([_c(1, "alice", body="/hos authorize \ud800")])
    assert _reasons(v) == ["not-codeowner"]


def test_inline_comment_owner_cannot_authorize():
    from scripts.framework.requester_trust import parse_codeowners_humans

    owners = frozenset(parse_codeowners_humans("* @maintainer # alice handles triage\n"))
    assert owners == {"maintainer"}
    by_alice = _decide([_c(1, "alice", body=_form())], co=owners)
    assert not by_alice.authorized and by_alice.covered == ()
    assert _reasons(by_alice) == ["not-codeowner"]
    assert _decide([_c(1, "maintainer", body=_form())], co=owners).authorized


def test_attached_hash_comment_owner_cannot_authorize():
    from scripts.framework.requester_trust import parse_codeowners_humans

    owners = frozenset(parse_codeowners_humans("* @maintainer @carol# see @alice\n"))
    assert owners == {"maintainer"}
    for login in ("alice", "carol"):
        v = _decide([_c(1, login, body=_form())], co=owners)
        assert not v.authorized and v.covered == ()
        assert _reasons(v) == ["not-codeowner"]
    assert _decide([_c(1, "maintainer", body=_form())], co=owners).authorized


# ---------------------------------------------------------------------------
# S1b (#2151, TD-2101 §10.4.5): the deleted-later refusal. A is a valid, current,
# overlapping authorize by scottthurlow created at T1.
# ---------------------------------------------------------------------------


def _a(id=1, created=T1):
    return _c(id, "scottthurlow", created=created, body=_form())


def test_t_p_31_deleted_newer_decline_does_not_resurrect_the_older_authorize():
    v = _decide([_a()], deletions=(_del(901, T3),))
    assert v.authorized is False and v.covered == () and v.unmet == ("C7",)
    assert v.accepted is None and v.governing.decision == "authorize"
    assert len(v.refusals) == 1
    r = v.refusals[0]
    assert (r.reason, r.detail, r.comment_id) == ("deleted-later", "event:901", 1)


def test_t_p_32_deletion_older_than_the_act_is_ignored():
    assert _decide([_a()], deletions=(_del(901, "2026-10-20T09:59:59Z"),)).authorized


def test_t_p_33_same_second_deletion_counts():
    assert _reasons(_decide([_a()], deletions=(_del(901, T1),))) == ["deleted-later"]


def test_t_p_34_unknown_author_counts():
    assert _reasons(_decide([_a()], deletions=(_del(901, T3, author=None),))) == ["deleted-later"]


def test_t_p_35_only_codeowner_authors_count_case_insensitively():
    assert _decide([_a()], deletions=(_del(901, T3, author="alice"),)).authorized
    assert _decide([_a()], deletions=(_del(902, T3, author="hos-worker-hos[bot]"),)).authorized
    v = _decide([_a()], deletions=(_del(903, T3, author="ScottThurlow"),))
    assert _reasons(v) == ["deleted-later"]


@pytest.mark.parametrize("kind", ["declined", "stale", "edited"])
def test_t_p_36_other_governing_outcomes_keep_their_reason(kind):
    dels = (_del(901, T3),)
    if kind == "declined":
        comments = [_c(1, "scottthurlow", body="/hos decline step=5")]
    elif kind == "stale":
        comments = [_c(1, "scottthurlow", body=_form(binding=OTHER_B))]
    else:
        comments = [_c(1, "scottthurlow", updated=T2, body=_form())]
    with_del = _decide(comments, deletions=dels)
    without = _decide(comments)
    assert _reasons(with_del) == _reasons(without) == [kind]
    assert len(with_del.refusals) == len(without.refusals)


def test_t_p_37_earliest_qualifying_deletion_is_named():
    dels = (_del(950, T3), _del(940, T3), _del(930, "2026-10-20T13:00:00Z"))
    v = _decide([_a()], deletions=dels)
    assert [(r.reason, r.detail) for r in v.refusals] == [("deleted-later", "event:940")]


def test_t_p_38_a_fresh_authorize_after_the_deletion_recovers():
    fresh = _c(2, "scottthurlow", created="2026-10-20T13:00:00Z", body=_form())
    v = _decide([_a(), fresh], deletions=(_del(901, T3),))
    assert v.authorized and v.accepted.governing.comment_id == 2
    assert _reasons(v) == ["superseded"]


def test_t_p_39_deletion_on_the_pr_source_applies():
    v = _decide([_a()], deletions=(_del(901, T3, issue=2200),))
    assert _reasons(v) == ["deleted-later"]


def test_t_p_40_deletions_is_required_and_typed():
    with pytest.raises(TypeError):
        decide([], CO, BOTS, 5, B, ("C7",), FILES)
    with pytest.raises(ValueError):
        _decide([], deletions=("x",))


def test_t_p_41_one_event_per_candidate_with_a_qualifying_deletion():
    comments = [
        _c(1, "someapp[bot]", type="Bot", created="2026-10-20T09:00:00Z", body=_form()),
        _c(2, "alice", created="2026-10-20T09:01:00Z", body=_form()),
        _c(3, "scottthurlow", created="2026-10-20T09:02:00Z", body=_form(step=9)),
        _c(5, "scottthurlow", created="2026-10-20T09:05:00Z", body="/hos authorize step=5"),
        _c(6, "scottthurlow", created="2026-10-20T09:06:00Z", body=_form()),
        _c(7, "scottthurlow", created="2026-10-20T09:07:00Z", body=_form()),
    ]
    v = _decide(comments, deletions=(_del(901, "2026-10-20T10:00:00Z"),))
    assert v.authorized is False and v.accepted is None and v.covered == ()
    ids = [r.comment_id for r in v.refusals]
    assert sorted(ids) == [1, 2, 3, 5, 6, 7] and len(set(ids)) == len(ids)
    assert [r.reason for r in v.refusals if r.comment_id == 7] == ["deleted-later"]


@pytest.mark.parametrize("bad", ["", "2026-10-20T12:00:00.5Z", "2026-10-20 12:00:00", "x"])
def test_t_p_42_malformed_deletion_timestamp_is_a_precondition_error(bad):
    with pytest.raises(ValueError):
        _decide([_a()], deletions=(_del(901, bad),))


def test_t_p_42_malformed_comment_created_at_is_a_precondition_error():
    with pytest.raises(ValueError):
        _decide([_c(1, "scottthurlow", created="", body=_form())], deletions=(_del(901, T3),))


# ---------------------------------------------------------------------------
# #2151 bounce F3 (TD-2101 §10.5.2): the edit probe flag, ANDed with the REST rule.
# ---------------------------------------------------------------------------


def test_t_p_43_same_second_edit_is_refused_as_edited():
    v = _decide([_c(1, "scottthurlow", body=_form(), edited=True)])
    assert not v.authorized and v.covered == ()
    assert _reasons(v) == ["edited"]
    assert v.governing.decision == "edited"


def test_t_p_44_same_second_edited_chatter_supersedes_an_older_authorize():
    a = _c(1, "scottthurlow", created=T1, body=_form())
    d = _c(2, "scottthurlow", created=T2, body="hello", edited=True)
    v = _decide([a, d])
    assert not v.authorized and v.unmet == ("C7",)
    assert _reasons(v) == ["superseded", "edited"]
    assert v.refusals[1].detail == "non-candidate"
    assert v.governing.decision == "edited"


@pytest.mark.parametrize("bad", [1, None, "false"])
def test_t_p_45_edited_flag_must_be_a_bool(bad):
    c = dataclasses.replace(_c(1, "scottthurlow", body=_form()), edited=bad)
    with pytest.raises(ValueError, match="edited flag"):
        _decide([c])


def test_t_p_46_control_unedited_flag_with_equal_timestamps_authorizes():
    v = _decide([_c(1, "scottthurlow", body=_form(), edited=False)])
    assert v.authorized and v.covered == ("C7",)


def test_hash_path_owner_cannot_authorize():
    """T-P-47 (TD-2101 §10.5.1): R-A7b keeps a `#`-path owner out of the CODEOWNERS set."""
    from scripts.framework.requester_trust import parse_codeowners_humans

    owners = frozenset(parse_codeowners_humans("docs/a#b.md @alice\n* @maintainer\n"))
    assert owners == {"maintainer"}
    by_alice = _decide([_c(1, "alice", body=_form())], co=owners)
    assert not by_alice.authorized and by_alice.covered == ()
    assert _reasons(by_alice) == ["not-codeowner"]
    assert _decide([_c(1, "maintainer", body=_form())], co=owners).authorized


@pytest.mark.parametrize("body", ["/hos  decline step=5", "/hos\tdecline step=5"])
def test_whitespace_variant_decline_blocks_an_older_authorize(body):
    """T-P-48 (TD-2101 §10.5.5 R3): a mistyped decline governs as malformed-latest."""
    a = _c(1, "scottthurlow", created=T1, body=_form())
    d = _c(2, "scottthurlow", created=T2, body=body)
    v = _decide([a, d])
    assert not v.authorized
    assert _reasons(v) == ["superseded", "malformed-latest"]
    assert v.refusals[1].detail == "marker-line"
    assert v.governing.decision == "malformed"
