"""Tests for the #2209 S1a rejection-routing core (docs/v0.7.0/
TECHNICAL-DESIGN-2209-s1-route-bounce.md §5.1).

Covers the pure `route_pr` precedence list (rule table + property test),
`latest_reviewer_act`, CODEOWNERS resolution and parity, `bounce_cid`, the
bounce epoch, findings canonicalization, the #902 head-time bound, the three
new github.py reads, and the PR #2207 replay through the CLI. Everything is
hermetic: no network, temp files only through `tmp_path`.
"""

from __future__ import annotations

import base64
import dataclasses
import importlib.util
import itertools
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import scripts.automation.merge_authority_cli as cli
from scripts.automation.lib import github as gh
from scripts.automation.lib import merge_authority as ma
from scripts.automation.lib.github import GitHubError
from scripts.automation.lib.merge_authority import (
    Block,
    Decision,
    Disposition,
    EscalationRecord,
    Finding,
    FindingsSchemaError,
    Option,
    PrClosure,
    PriorFinding,
    ReviewerAct,
    RouteInputs,
    VetoState,
    route_pr,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "automation" / "fixtures" / "pr2207_0227Z.json"
HEAD = "d" * 40
BOT_ACCOUNTS = {"hos-worker-hos[bot]", "hos-overseer-hos[bot]"}
PR = 7


def _load_codeowners_module():
    path = REPO_ROOT / "scripts" / "oversight" / "codeowners.py"
    spec = importlib.util.spec_from_file_location("hos_oversight_codeowners_t2209", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


codeowners = _load_codeowners_module()


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #


def llm(slug="one", path="a.py", cls="MERITS", **kw) -> Finding:
    key = f"{cls}:{path or '-'}:{slug}"
    return Finding(
        cls=cls,
        key=key,
        identity=(cls, path or "-"),
        origin="llm",
        path=path,
        summary="problem",
        **kw,
    )


def code(check_id="register-missing", cls="PROCEDURAL") -> Finding:
    key = f"{cls}:{check_id}"
    return Finding(cls=cls, key=key, identity=(cls, key), origin="code", path=None, summary="gap")


def decision_finding(slug="pick") -> Finding:
    d = Decision("Which?", (Option("A", "first"), Option("B", "second")))
    return llm(slug, path=None, decision=d)


def prior_of(f: Finding, finding_id="") -> PriorFinding:
    return PriorFinding(finding_id, f.cls, f.key, f.identity, f.origin)


def act(kind="APPROVED", option=None, at="2026-10-31T01:00:00Z", source_id=1) -> ReviewerAct:
    return ReviewerAct(kind, source_id, at, option)


def esc(trigger="bounce-cap", options=()) -> EscalationRecord:
    return EscalationRecord(PR, HEAD, trigger, "2026-10-31T00:00:00Z", tuple(options))


def inputs(**kw) -> RouteInputs:
    base: dict[str, Any] = dict(
        pr=PR,
        worker_authored=True,
        head_sha=HEAD,
        findings=(),
        collectors_complete=True,
        hold_on_head=False,
        prior_on_head=(),
        epoch_bounce_count=0,
    )
    base.update(kw)
    return RouteInputs(**base)


def verdict(r):
    return (r.disposition, r.rule, r.trigger, r.reasons[0] if r.reasons else None)


# --------------------------------------------------------------------------- #
# T-RP-T: one row per precedence-list row
# --------------------------------------------------------------------------- #

D = Disposition
OWN_PENDING = Block("PATH_PENDING_ESCALATION", PR, "own")
OTHER_PENDING = Block("PATH_PENDING_ESCALATION", PR + 1, "other")
LLM1 = llm()
APPROVED = act("APPROVED")

RULE_ROWS = [
    ("1-non-worker", dict(worker_authored=False), (D.LEGACY, "1", None, "non-worker-pr")),
    ("1-path-hold", dict(blocks=(Block("PATH_HOLD", 9, "r"),)), (D.LEGACY, "1", None, "path-hold")),
    (
        "1-unknown-scope",
        dict(blocks=(Block("UNKNOWN_SCOPE", 9, "r"),)),
        (D.LEGACY, "1", None, "path-hold"),
    ),
    ("1-hold-902", dict(hold_on_head=True), (D.LEGACY, "1", None, "hold-902")),
    ("2-awaiting", dict(escalation=esc()), (D.HOLD, "2a", "bounce-cap", "awaiting-reviewer")),
    (
        "2-revoked",
        dict(escalation=esc(), escalation_act=act("DISMISSED")),
        (D.HOLD, "2b", "bounce-cap", "approval-revoked"),
    ),
    (
        "2-changes",
        dict(escalation=esc(), escalation_act=act("CHANGES_REQUESTED")),
        (D.HUMAN_SENDBACK, "2c", "bounce-cap", None),
    ),
    (
        "2-label",
        dict(escalation=esc(), escalation_act=act("NEEDS_AI_LABEL")),
        (D.HUMAN_SENDBACK, "2c", "bounce-cap", None),
    ),
    (
        "2-code-open",
        dict(escalation=esc(), escalation_act=APPROVED, findings=(code(),)),
        (D.HOLD, "2d", "bounce-cap", "code-findings-open"),
    ),
    (
        "2-collectors",
        dict(escalation=esc(), escalation_act=APPROVED, collectors_complete=False),
        (D.HOLD, "2e", "bounce-cap", "collectors-incomplete"),
    ),
    (
        "2-option-missing",
        dict(escalation=esc("decision", ("A", "B")), escalation_act=APPROVED),
        (D.HOLD, "2f", "decision", "decision-option-missing"),
    ),
    (
        "2-option-unknown",
        dict(escalation=esc("decision", ("A", "B")), escalation_act=act(option="Z")),
        (D.HOLD, "2f", "decision", "decision-option-missing"),
    ),
    (
        "2-pending-ruling",
        dict(escalation=esc(), escalation_act=APPROVED, pending_rulings=("F1",)),
        (D.RULING_REQUIRED, "2k", "bounce-cap", None),
    ),
    (
        "2-upheld",
        dict(escalation=esc(), escalation_act=APPROVED, upheld_unescalated=("F1",)),
        (D.ESCALATE, "2l", "upheld-dispute", None),
    ),
    (
        "2-veto-needs-start",
        dict(escalation=esc(), escalation_act=APPROVED, veto=VetoState.NEEDS_START),
        (D.HOLD_VETO, "2g", "bounce-cap", None),
    ),
    (
        "2-veto-open",
        dict(escalation=esc(), escalation_act=APPROVED, veto=VetoState.OPEN),
        (D.HOLD_VETO, "2h", "bounce-cap", None),
    ),
    (
        "2-pending-other",
        dict(escalation=esc(), escalation_act=APPROVED, blocks=(OTHER_PENDING,)),
        (D.HOLD, "2i", "bounce-cap", "path-pending-escalation"),
    ),
    (
        "2-proceed",
        dict(escalation=esc(), escalation_act=APPROVED),
        (D.PROCEED, "2j", "bounce-cap", None),
    ),
    (
        "2-proceed-decision",
        dict(escalation=esc("decision", ("A",)), escalation_act=act(option="A")),
        (D.PROCEED, "2j", "decision", None),
    ),
    ("3-ruling", dict(pending_rulings=("F1",)), (D.RULING_REQUIRED, "3", None, None)),
    ("4-veto-continues", dict(veto=VetoState.NEEDS_START), (D.HOLD_VETO, "8", None, None)),
    ("5-upheld", dict(upheld_unescalated=("F1",)), (D.ESCALATE, "5", "upheld-dispute", None)),
    (
        "6a-conflict-approved",
        dict(findings=(LLM1,), reviewer_act_on_head=APPROVED),
        (D.ESCALATE, "6a", "reviewer-conflict", None),
    ),
    (
        "6b-conflicts-with",
        dict(findings=(llm(conflicts_with=ma.Conflict("sec", "https://x")),)),
        (D.ESCALATE, "6b", "reviewer-conflict", None),
    ),
    (
        "6c-no-new-keys",
        dict(findings=(LLM1,), prior_on_head=(prior_of(LLM1),)),
        (D.NOOP, "6c", None, "no-new-keys"),
    ),
    (
        "6d-cap",
        dict(findings=(LLM1,), epoch_bounce_count=2),
        (D.ESCALATE, "6d", "bounce-cap", None),
    ),
    ("6e-bounce", dict(findings=(LLM1,)), (D.BOUNCE, "6e", None, None)),
    ("7-decision", dict(findings=(decision_finding(),)), (D.ESCALATE, "7", "decision", None)),
    ("8-veto-open", dict(veto=VetoState.OPEN), (D.HOLD_VETO, "8", None, None)),
    (
        "8-pending-other",
        dict(blocks=(OTHER_PENDING,)),
        (D.HOLD, "8", None, "path-pending-escalation"),
    ),
    ("8-collectors", dict(collectors_complete=False), (D.HOLD, "8", None, "collectors-incomplete")),
    ("8-proceed", dict(), (D.PROCEED, "8", None, None)),
    # AR1-C2: a PR's own pending escalation never blocks it; its own hold still does.
    (
        "C2-own-pending-clean",
        dict(blocks=(OWN_PENDING,), collectors_complete=False),
        (D.HOLD, "8", None, "collectors-incomplete"),
    ),
    (
        "C2-own-pending-approved",
        dict(escalation=esc(), escalation_act=APPROVED, blocks=(OWN_PENDING,)),
        (D.PROCEED, "2j", "bounce-cap", None),
    ),
    (
        "C2-own-hold-still-blocks",
        dict(blocks=(Block("PATH_HOLD", PR, "own"),)),
        (D.LEGACY, "1", None, "path-hold"),
    ),
]


@pytest.mark.parametrize(
    "kwargs,expected", [r[1:] for r in RULE_ROWS], ids=[r[0] for r in RULE_ROWS]
)
def test_t_rp_t_rule_table(kwargs, expected):
    assert verdict(route_pr(inputs(**kwargs))) == expected


def test_rule_2_proceed_overrules_llm_keys_only():
    r = route_pr(
        inputs(escalation=esc(), escalation_act=APPROVED, findings=(LLM1, decision_finding()))
    )
    assert r.disposition is D.PROCEED
    assert r.overruled_keys == (LLM1.key, decision_finding().key)


def test_rule_6c_appends_repair_finalize_and_actions_accumulate():
    same = dict(findings=(LLM1,), prior_on_head=(prior_of(LLM1),))
    assert route_pr(inputs(**same)).actions == ("repair-finalize",)
    started = route_pr(inputs(**same, veto=VetoState.NEEDS_START))
    assert started.actions == ("start-veto-window", "repair-finalize")
    assert route_pr(inputs(findings=(LLM1,))).actions == ()  # a bounce repairs nothing


def test_rule_2_pending_ruling_and_upheld_carry_the_veto_action():
    base = dict(escalation=esc(), escalation_act=APPROVED, veto=VetoState.NEEDS_START)
    assert route_pr(inputs(**base, pending_rulings=("F",))).actions == ("start-veto-window",)
    assert route_pr(inputs(**base, upheld_unescalated=("F",))).actions == ("start-veto-window",)


def test_rule_2_pending_ruling_waits_for_collectors_and_option_rows():
    held = route_pr(
        inputs(
            escalation=esc(),
            escalation_act=APPROVED,
            pending_rulings=("F",),
            collectors_complete=False,
        )
    )
    assert (held.disposition, held.rule) == (D.HOLD, "2e")


def test_rule_2_veto_actions():
    needs = route_pr(inputs(escalation=esc(), escalation_act=APPROVED, veto=VetoState.NEEDS_START))
    opened = route_pr(inputs(escalation=esc(), escalation_act=APPROVED, veto=VetoState.OPEN))
    assert needs.actions == ("start-veto-window",)
    assert opened.actions == ()
    assert route_pr(inputs(escalation=esc(), veto=VetoState.NEEDS_START)).actions == (
        "start-veto-window",
    )


@pytest.mark.parametrize(
    "cls", ["PROCEDURAL", "REQUIRED_CHECK", "CHECK", "MERITS", "SCOPE", "REVIEW_FINDING"]
)
def test_t_rp_c_each_class_bounces(cls):
    if cls in ("PROCEDURAL", "REQUIRED_CHECK"):
        f = code("x", cls)
    elif cls == "CHECK":
        f = Finding("CHECK", "check:lint:-:a.py", ("CHECK", "lint", "a.py"), "llm", "a.py", "s")
    else:
        f = llm(cls=cls)
    r = route_pr(inputs(findings=(f,)))
    assert r.disposition is D.BOUNCE and r.to_bounce == (f,)


def test_t_rp_2_security_finding_by_worker_still_bounces():
    r = route_pr(inputs(findings=(llm("security-hole", path="auth/login.py"),)))
    assert r.disposition is D.BOUNCE


def test_t_rp_p5_inputs_have_no_tier_or_surface_fields():
    import re

    names = [f.name for f in dataclasses.fields(RouteInputs)]
    assert not [n for n in names if re.search(r"tier|surface|security|protected|codeowner", n)]


def test_t_rp_6c_slug_reword_is_not_a_new_bounce():
    old = llm("first-slug")
    reworded = llm("reworded-slug")
    r = route_pr(inputs(findings=(reworded,), prior_on_head=(prior_of(old),)))
    assert r.disposition is D.NOOP


def test_t_rp_6c_new_check_run_on_same_path_bounces():
    def chk(run):
        return Finding("CHECK", f"check:{run}:-:a.py", ("CHECK", run, "a.py"), "llm", "a.py", "s")

    r = route_pr(
        inputs(findings=(chk("lint"), chk("tests")), prior_on_head=(prior_of(chk("lint")),))
    )
    assert r.disposition is D.BOUNCE and [f.key for f in r.to_bounce] == ["check:tests:-:a.py"]


def test_t_rp_7_decision_ordering():
    d = decision_finding()
    assert route_pr(inputs(findings=(d,))).disposition is D.ESCALATE
    assert route_pr(inputs(findings=(d, LLM1))).disposition is D.BOUNCE  # rejections first
    malformed = llm("bad", path=None)  # a dropped decision leaves a plain rejection
    assert route_pr(inputs(findings=(malformed,))).disposition is D.BOUNCE


# --------------------------------------------------------------------------- #
# T-RP-P: exhaustive property test (no hypothesis installed)
# --------------------------------------------------------------------------- #


def test_t_rp_p_properties():
    new_llm, old_llm = llm("new", path="n.py"), llm("old", path="o.py")
    llm_opts = {"none": (), "new": (new_llm,), "old": (old_llm,)}
    block_opts = {
        "none": (),
        "hold": (Block("PATH_HOLD", PR + 1, "r"),),
        "unknown": (Block("UNKNOWN_SCOPE", PR + 1, "r"),),
        "pend-own": (OWN_PENDING,),
        "pend-other": (OTHER_PENDING,),
    }
    esc_opts = {
        "none": (None, None),
        "unacted": (esc(), None),
        **{
            k: (esc(), act(k))
            for k in ("APPROVED", "DISMISSED", "CHANGES_REQUESTED", "NEEDS_AI_LABEL")
        },
    }
    cap = ma.BOUNCE_CAP
    n = 0
    for (
        wa,
        hold,
        b,
        veto,
        code_open,
        llm_k,
        dec,
        e,
        coll,
        pend,
        upheld,
        epoch,
        rv,
    ) in itertools.product(
        (True, False),
        (True, False),
        block_opts,
        list(VetoState),
        (0, 1),
        llm_opts,
        (0, 1),
        esc_opts,
        (True, False),
        (0, 1),
        (0, 1),
        (0, cap),
        (None, APPROVED),
    ):
        findings = (
            *((code(),) if code_open else ()),
            *llm_opts[llm_k],
            *((decision_finding(),) if dec else ()),
        )
        kw = dict(
            worker_authored=wa,
            hold_on_head=hold,
            blocks=block_opts[b],
            veto=veto,
            findings=findings,
            prior_on_head=(prior_of(old_llm),),
            escalation=esc_opts[e][0],
            escalation_act=esc_opts[e][1],
            collectors_complete=coll,
            pending_rulings=("F",) if pend else (),
            upheld_unescalated=("F",) if upheld else (),
            epoch_bounce_count=epoch,
            reviewer_act_on_head=rv,
        )
        r = route_pr(inputs(**kw))
        n += 1
        assert r == route_pr(inputs(**kw))  # P4: deterministic
        if r.disposition is D.PROCEED:  # P1
            assert wa and not hold and coll and veto not in (VetoState.OPEN, VetoState.NEEDS_START)
            assert not code_open
            assert not [x for x in block_opts[b] if x.kind in ("PATH_HOLD", "UNKNOWN_SCOPE")]
            assert not [
                x
                for x in block_opts[b]
                if x.kind == "PATH_PENDING_ESCALATION" and x.source_pr != PR
            ]
            assert not pend and not upheld  # unconditional (AR4-2)
        if not wa:  # P2
            assert r.disposition is D.LEGACY
        if r.disposition is D.BOUNCE:  # P3
            assert epoch < cap and r.to_bounce
            assert all(f.identity != old_llm.identity for f in r.to_bounce)
        if r.disposition is D.ESCALATE:  # P6
            assert r.trigger in ma.ESCALATION_TRIGGERS
        if veto is VetoState.NEEDS_START and r.disposition not in (
            D.LEGACY,
            D.RULING_REQUIRED,
            D.BOUNCE,
            D.ESCALATE,
        ):  # P7
            assert "start-veto-window" in r.actions
        if b == "none":  # P8
            assert r == route_pr(inputs(**{**kw, "blocks": (OWN_PENDING,)}))
    assert n > 100000


# --------------------------------------------------------------------------- #
# T-RA: latest_reviewer_act
# --------------------------------------------------------------------------- #


def rev(rid, state, at, login="carol", head=HEAD, body="", utype="User"):
    return {
        "id": rid,
        "user": {"login": login, "type": utype},
        "state": state,
        "commit_id": head,
        "submitted_at": at,
        "body": body,
    }


def label_ev(eid, at, login="carol", name="needs-ai", event="labeled"):
    return {
        "id": eid,
        "event": event,
        "label": {"name": name},
        "created_at": at,
        "actor": {"login": login, "type": "User"},
    }


def latest(reviews, labels=(), since=None, reviewer="carol"):
    return ma.latest_reviewer_act(reviews, labels, reviewer, HEAD, since, bot_accounts=BOT_ACCOUNTS)


ESC_AT = "2026-10-31T00:00:00Z"
T1, T2, T3 = "2026-10-31T01:00:00Z", "2026-10-31T02:00:00Z", "2026-10-31T03:00:00Z"


def test_t_ra_1_triggers_proceed_or_sendback():
    for trigger in ma.ESCALATION_TRIGGERS:
        e = esc(trigger, ("A",))
        approve = latest([rev(1, "APPROVED", T1, body="Option: A")], since=ESC_AT)
        assert route_pr(inputs(escalation=e, escalation_act=approve)).disposition is D.PROCEED
        changes = latest([rev(1, "CHANGES_REQUESTED", T1)], since=ESC_AT)
        assert (
            route_pr(inputs(escalation=e, escalation_act=changes)).disposition is D.HUMAN_SENDBACK
        )
        label = latest([], [label_ev(5, T1)], since=ESC_AT)
        assert route_pr(inputs(escalation=e, escalation_act=label)).disposition is D.HUMAN_SENDBACK


def test_t_ra_2_reapproval_after_escalation_is_the_latest_act():
    reviews = [rev(1, "APPROVED", "2026-10-30T23:00:00Z"), rev(2, "APPROVED", T1)]
    got = latest(reviews, since=ESC_AT)
    assert got.source_id == 2
    only_before = latest([rev(1, "APPROVED", "2026-10-30T23:00:00Z")], since=ESC_AT)
    assert only_before is None


def test_t_ra_3_wrong_actor_or_head_gives_none():
    assert (
        latest(
            [rev(1, "APPROVED", T1, login="hos-overseer-hos[bot]", utype="Bot")],
            reviewer="hos-overseer-hos[bot]",
        )
        is None
    )
    assert (
        latest(
            [rev(1, "APPROVED", T1, login="scottthurlow-claude[bot]", utype="Bot")],
            reviewer="scottthurlow-claude[bot]",
        )
        is None
    )
    assert latest([rev(1, "APPROVED", T1, login="mallory")]) is None
    assert latest([rev(1, "APPROVED", T1, head="e" * 40)]) is None
    r = route_pr(
        inputs(
            escalation=esc(),
            escalation_act=latest([rev(1, "APPROVED", T1, login="mallory")], since=ESC_AT),
        )
    )
    assert r.disposition is D.HOLD


def test_t_ra_skipped_candidates_do_not_hide_later_valid_acts():
    # a non-reviewer, a wrong-head review and a non-reviewer label event come
    # first; each must be skipped, not end the scan
    reviews = [
        rev(1, "APPROVED", T1, login="mallory"),
        rev(2, "APPROVED", T1, head="e" * 40),
        rev(3, "APPROVED", T2),
    ]
    assert latest(reviews, since=ESC_AT).source_id == 3
    labels = [label_ev(8, T1, login="mallory"), label_ev(9, T2)]
    assert latest([], labels, since=ESC_AT).source_id == 9


def test_t_ra_unparseable_label_time_is_skipped_not_fatal():
    bad = label_ev(4, "not-a-date")
    good = label_ev(5, T2)
    assert latest([], [bad, good], since=ESC_AT).source_id == 5


def test_t_ra_undated_review_sorts_before_any_dated_one():
    undated = rev(9, "APPROVED", None)
    dated = rev(1, "CHANGES_REQUESTED", T1)
    got = latest([undated, dated])
    assert got.source_id == 1


def test_t_ra_4_later_dismissal_revokes():
    got = latest(
        [rev(1, "APPROVED", T1), rev(2, "APPROVED", T2), rev(3, "DISMISSED", T3)], since=ESC_AT
    )
    assert got.kind == "DISMISSED"
    r = route_pr(inputs(escalation=esc(), escalation_act=got))
    assert (r.disposition, r.reasons) == (D.HOLD, ("approval-revoked",))


def test_t_ra_5_approved_with_open_required_check_holds():
    r = route_pr(
        inputs(
            escalation=esc(),
            escalation_act=APPROVED,
            findings=(code("check-failing:tests", "REQUIRED_CHECK"),),
        )
    )
    assert (r.disposition, r.reasons) == (D.HOLD, ("code-findings-open",))


def test_t_ra_6_decision_needs_a_known_option_line():
    e = esc("decision", ("A", "B"))
    none = latest([rev(1, "APPROVED", T1, body="LGTM")], since=ESC_AT)
    unknown = latest([rev(1, "APPROVED", T1, body="Option: Z")], since=ESC_AT)
    good = latest([rev(1, "APPROVED", T1, body="notes\nOption: B\nmore")], since=ESC_AT)
    assert route_pr(inputs(escalation=e, escalation_act=none)).disposition is D.HOLD
    assert route_pr(inputs(escalation=e, escalation_act=unknown)).disposition is D.HOLD
    assert route_pr(inputs(escalation=e, escalation_act=good)).disposition is D.PROCEED
    assert "notes" not in repr(good)


def test_t_ra_7_tie_commented_and_labels_without_since():
    tie = latest([rev(1, "APPROVED", T1), rev(2, "CHANGES_REQUESTED", T1)])
    assert tie.kind == "CHANGES_REQUESTED"
    assert latest([rev(1, "COMMENTED", T1)]) is None
    assert latest([], [label_ev(5, T1)], since=None) is None
    assert latest([], [label_ev(5, T1, name="other")], since=ESC_AT) is None
    assert latest([], [label_ev(5, T1, event="unlabeled")], since=ESC_AT) is None
    assert latest([rev(1, "APPROVED", "garbage")], since=ESC_AT) is None
    assert latest([rev(1, "APPROVED", "garbage")], since=None).kind == "APPROVED"


# --------------------------------------------------------------------------- #
# T-CO: CODEOWNERS parity, base-ref fetch
# --------------------------------------------------------------------------- #

CO_CASES = [
    ["/some/** @carol"],
    ["/team/** @org/team-a"],
    ["/x/** @hos-worker-hos[bot]"],
    ["/x/** dev@example.com"],
    ["/x/** @org/team-a @carol"],
    ["* @carol", "/a/** @dave"],
    ["/a/** @dave", "/a/** @erin"],
    ["/a/** @dave", "/a/b.py"],
    ["# comment", "", "/a/** @Dave  @erin"],
    ["/a/** @org/t", "/b/** @frank"],
    ["/x/** @hos-overseer-hos[bot] dev@example.com"],
    ["/a/** @dave # docs team"],
    ["/a/** @dave #@mallory", "/b/** @erin"],
    [],
]
CO_FILES = [
    ["some/f.py"],
    ["team/f.py"],
    ["x/f.py"],
    ["a/b.py"],
    ["a/b.py", "b/c.py"],
    ["unmatched.py"],
]


@pytest.mark.parametrize("lines", CO_CASES)
def test_t_co_1_humans_set_matches_requester_trust(lines, tmp_path):
    from scripts.framework import requester_trust

    text = "\n".join(lines) + "\n"
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text(text)
    assert ma._codeowners_humans_from_text(text) == requester_trust.codeowners_humans(str(tmp_path))
    assert ma._codeowners_humans_from_text(None) == set()


@pytest.mark.parametrize("lines", CO_CASES)
@pytest.mark.parametrize("files", CO_FILES)
def test_t_co_2_resolution_parity_with_step_6(lines, files, tmp_path):
    text = "\n".join(lines) + "\n"
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text(text)
    want = codeowners.resolve_human_reviewer(files, tmp_path, BOT_ACCOUNTS, "default-human")
    got = ma.resolve_reviewer_from_text(
        text, files, bot_accounts=BOT_ACCOUNTS, human_reviewer="default-human"
    )
    assert (got.login, got.source, got.note) == (want.login, want.source, want.note)
    assert list(got.team_owners) == want.codeowners_team_owners
    ma.check_resolution_consistent(got, text)  # no drift on any parity case


def test_t_co_2_no_codeowners_file():
    got = ma.resolve_reviewer_from_text(
        None, ["a.py"], bot_accounts=BOT_ACCOUNTS, human_reviewer="h"
    )
    assert (got.login, got.source, got.note) == ("h", "machine-accounts.env", "no CODEOWNERS file")


# #2202: inline '#' comments must not leak owners in either parser.
def test_t_co_3_oversight_parser_strips_inline_comment():
    assert codeowners.parse_codeowners("/a @u1 # docs team\n/b # @mallory\n") == [
        ("/a", ["@u1"]),
        ("/b", []),
    ]


def test_t_co_3_automation_find_owners_strips_inline_comment(tmp_path):
    from scripts.automation.lib.codeowners import find_owners

    path = tmp_path / "CODEOWNERS"
    path.write_text("docs/ @alice # docs team @mallory\n")
    assert find_owners("docs/a.md", path) == ["@alice"]


def test_drift_guard_raises_when_login_not_in_humans_set():
    res = ma.ReviewerResolution("ghost", "codeowners", (), None)
    with pytest.raises(ma.CodeownersDriftError):
        ma.check_resolution_consistent(res, "/a/** @carol\n")


def _payload(text):
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


def test_t_co_3_fetch_uses_the_ref_it_is_given():
    calls = []

    def fake(o, r, path, *, ref):
        calls.append((path, ref))
        return _payload("/a @carol\n") if path == ".github/CODEOWNERS" else None

    with patch.object(ma, "get_contents", side_effect=fake):
        assert ma.fetch_codeowners_text("o", "r", "BASESHA") == "/a @carol\n"
    assert calls == [(".github/CODEOWNERS", "BASESHA")]


def test_t_co_4_fetch_locations_and_failures():
    with patch.object(ma, "get_contents", return_value=None) as g:
        assert ma.fetch_codeowners_text("o", "r", "s") is None
    assert [c.args[2] for c in g.call_args_list] == [
        ".github/CODEOWNERS",
        "CODEOWNERS",
        "docs/CODEOWNERS",
    ]

    seq = {".github/CODEOWNERS": None, "CODEOWNERS": _payload("/b @dave\n")}
    with patch.object(ma, "get_contents", side_effect=lambda o, r, p, *, ref: seq.get(p)):
        assert ma.fetch_codeowners_text("o", "r", "s") == "/b @dave\n"

    with patch.object(ma, "get_contents", side_effect=GitHubError("boom", 502)):
        with pytest.raises(GitHubError):
            ma.fetch_codeowners_text("o", "r", "s")
    for bad in (
        {"encoding": "base64", "content": ""},
        {"encoding": "none", "content": "x"},
        {"content": "x"},
    ):
        with patch.object(ma, "get_contents", return_value=bad):
            with pytest.raises(ma.CodeownersUnreadableError):
                ma.fetch_codeowners_text("o", "r", "s")
    undecodable = {"encoding": "base64", "content": base64.b64encode(b"\xff\xfe").decode()}
    with patch.object(ma, "get_contents", return_value=undecodable):
        with pytest.raises(ma.CodeownersUnreadableError):
            ma.fetch_codeowners_text("o", "r", "s")


# --------------------------------------------------------------------------- #
# T-CID
# --------------------------------------------------------------------------- #


def worker_pr(**over):
    pr = {
        "number": 55,
        "user": {"login": "hos-worker-hos[bot]", "type": "Bot"},
        "head": {"ref": "worker-2171-fix-it-261029", "repo": {"full_name": "o/r"}},
        "base": {"repo": {"full_name": "O/R"}},
    }
    pr.update(over)
    return pr


def resolve(pr, lookup):
    return ma.bounce_cid(pr, worker_login="hos-worker-hos[bot]", issue_lookup=lookup)


@pytest.mark.parametrize("state", ["open", "closed"])
def test_t_cid_1_worker_pr_gets_issue_cid(state):
    got = resolve(worker_pr(), lambda n: {"number": n, "state": state})
    assert (got.cid, got.source, got.issue, got.warn) == ("issue-2171", "issue", 2171, None)
    again = resolve(worker_pr(number=99), lambda n: {"number": n, "state": state})
    assert again.cid == "issue-2171"  # a second PR on the same issue shares the budget


@pytest.mark.parametrize(
    "pr,lookup,warn",
    [
        (worker_pr(user={"login": "scott", "type": "User"}), lambda n: {}, "not-worker-author"),
        (
            worker_pr(user={"login": "hos-worker-hos[bot]", "type": "User"}),
            lambda n: {},
            "not-worker-author",
        ),
        (
            worker_pr(head={"ref": "feature/x", "repo": {"full_name": "o/r"}}),
            lambda n: {},
            "ref-not-worker-format",
        ),
        (
            worker_pr(head={"ref": "worker-0-x", "repo": {"full_name": "o/r"}}),
            lambda n: {},
            "ref-not-worker-format",
        ),
        (
            worker_pr(head={"ref": "worker-007-x", "repo": {"full_name": "o/r"}}),
            lambda n: {},
            "ref-not-worker-format",
        ),
        (
            worker_pr(head={"ref": "worker-9-x", "repo": {"full_name": "fork/r"}}),
            lambda n: {},
            "fork-head",
        ),
        (worker_pr(head={"ref": "worker-9-x", "repo": None}), lambda n: {}, "fork-head"),
        (worker_pr(), lambda n: None, "issue-not-found"),
        (worker_pr(), lambda n: {"number": n, "pull_request": {}}, "number-is-a-pr"),
    ],
)
def test_t_cid_2_fallbacks(pr, lookup, warn):
    got = resolve(pr, lookup)
    assert (got.cid, got.source, got.issue, got.warn) == ("pr-55", "pr-fallback", None, warn)


def test_t_cid_3_lookup_error_propagates_not_falls_back():
    def boom(n):
        raise GitHubError("503", 503)

    with pytest.raises(GitHubError):
        resolve(worker_pr(), boom)


# --------------------------------------------------------------------------- #
# T-EP: epoch
# --------------------------------------------------------------------------- #


def _bounce_event(root, n, when, cid="issue-1", pr=5, **extra):
    from scripts.oversight.lib import audit_log

    audit_log.write_event(
        {
            "event": "pr-bounced",
            "cid": cid,
            "pr": pr,
            "bounce_number": n,
            "timestamp": when,
            **extra,
        },
        root=str(root),
    )


def test_bounced_on_head_skips_junk_entries_and_keeps_later_ones(tmp_path):
    entry = {"id": "f1", "class": "CHECK", "key": "CHECK:k", "origin": "code"}
    _bounce_event(tmp_path, 1, "2026-10-30T01:00:00Z", head_sha="e" * 40, findings=[entry])
    _bounce_event(tmp_path, 2, "2026-10-30T02:00:00Z", head_sha=HEAD, findings=["junk", 7, entry])
    got = ma.bounced_on_head("issue-1", HEAD, repo_root=str(tmp_path))
    assert [(f.finding_id, f.cls, f.key) for f in got] == [("f1", "CHECK", "CHECK:k")]


def test_t_ep_1_escalation_resets_the_epoch(tmp_path):
    _bounce_event(tmp_path, 1, "2026-10-30T01:00:00Z")
    _bounce_event(tmp_path, 2, "2026-10-30T02:00:00Z")
    escalation = EscalationRecord(5, HEAD, "bounce-cap", "2026-10-30T03:00:00Z")
    start = ma.epoch_start(
        this_pr_created_at="2026-10-30T00:00:00Z",
        escalations=[escalation],
        sibling_closures=[],
        worker_login="hos-worker-hos[bot]",
    )
    assert start == "2026-10-30T03:00:00Z"
    assert ma.bounce_count("issue-1", repo_root=str(tmp_path), since=start) == 0
    with patch.object(ma, "EPOCH_RESETS_AT_ESCALATION", False):  # ARCH-ESC-1 (B)
        start_b = ma.epoch_start(
            this_pr_created_at="2026-10-30T00:00:00Z",
            escalations=[escalation],
            sibling_closures=[],
            worker_login="hos-worker-hos[bot]",
        )
        assert start_b is None
        assert ma.bounce_count("issue-1", repo_root=str(tmp_path), since=start_b) == 2


def test_t_ep_2_sibling_closures():
    def start(*closures):
        return ma.epoch_start(
            this_pr_created_at="2026-10-30T12:00:00Z",
            escalations=[],
            sibling_closures=list(closures),
            worker_login="hos-worker-hos[bot]",
        )

    overseer_merge = PrClosure(1, "merged", "2026-10-30T10:00:00Z", "hos-overseer-hos[bot]", "Bot")
    late_merge = PrClosure(2, "merged", "2026-10-30T13:00:00Z", "hos-overseer-hos[bot]", "Bot")
    worker_close = PrClosure(3, "closed", "2026-10-30T11:00:00Z", "HOS-Worker-HOS[bot]", "Bot")
    proxy_close = PrClosure(4, "closed", "2026-10-30T09:00:00Z", "scottthurlow-claude[bot]", "Bot")
    assert start(overseer_merge) == "2026-10-30T10:00:00Z"
    assert start(late_merge) is None
    assert start(worker_close) is None
    assert start(proxy_close) == "2026-10-30T09:00:00Z"
    assert start(proxy_close, overseer_merge, worker_close) == "2026-10-30T10:00:00Z"


def test_t_ep_3_unparseable_time_is_counted_and_none_is_all_time(tmp_path):
    _bounce_event(tmp_path, 1, "2026-10-30T01:00:00Z")
    _bounce_event(tmp_path, 2, "2026-10-30T01:30:00Z", comment_created_at="not-a-time")
    assert ma.bounce_count("issue-1", repo_root=str(tmp_path)) == 2
    assert ma.bounce_count("issue-1", repo_root=str(tmp_path), since=None) == 2
    assert (
        ma.bounce_count("issue-1", repo_root=str(tmp_path), since="2026-10-30T02:00:00Z") == 1
    )  # only the unparseable one
    assert (
        ma.bounce_count("issue-1", repo_root=str(tmp_path), since="2026-10-30T01:00:00Z") == 1
    )  # strict


def test_t_ep_3_comment_time_beats_audit_timestamp(tmp_path):
    _bounce_event(tmp_path, 1, "2026-10-30T01:00:00Z", comment_created_at="2026-10-30T05:00:00Z")
    assert ma.bounce_count("issue-1", repo_root=str(tmp_path), since="2026-10-30T03:00:00Z") == 1


def test_escalation_records_ignore_legacy_events(tmp_path):
    from scripts.oversight.lib import audit_log

    audit_log.write_event(
        {"event": "human-required", "pr": 5, "timestamp": "2026-10-30T00:00:00Z"},
        root=str(tmp_path),
    )
    audit_log.write_event(
        {
            "event": "human-required",
            "cid": "issue-1",
            "pr": 5,
            "head_sha": HEAD,
            "trigger": "bounce-cap",
            "escalation_created_at": "2026-10-30T01:00:00Z",
            "options": ["A"],
            "timestamp": "2026-10-30T01:00:01Z",
        },
        root=str(tmp_path),
    )
    got = ma.escalation_records("issue-1", repo_root=str(tmp_path))
    assert got == [EscalationRecord(5, HEAD, "bounce-cap", "2026-10-30T01:00:00Z", ("A",))]


# --------------------------------------------------------------------------- #
# T-FS: findings file
# --------------------------------------------------------------------------- #

CHANGED = ["bin/hos-cron", "docs/a.md", "café.py"]


def canon(entries, **over):
    kw = dict(
        changed_paths=CHANGED, head_check_runs=["shellcheck", "tests"], repo_slug="Owner/Repo"
    )
    kw.update(over)
    return ma.canonicalize_findings({"findings": entries}, **kw)


def merits(**over):
    entry = {"class": "MERITS", "summary": "s", "path": "docs/a.md", "slug": "good-slug"}
    entry.update(over)
    return entry


@pytest.mark.parametrize(
    "entry,fragment",
    [
        (merits(key="MERITS:x"), "unknown key"),
        (merits(origin="code"), "unknown key"),
        (merits(id="F1"), "unknown key"),
        (merits(**{"class": "PROCEDURAL"}), "reserved for code collectors"),
        (merits(**{"class": "REQUIRED_CHECK"}), "reserved for code collectors"),
        (merits(**{"class": "NOPE"}), "class"),
        (merits(path="docs/missing.md"), "not a file changed"),
        (merits(path="docs/a.md:123"), "no line numbers"),
        (merits(slug="Bad Slug"), "slug"),
        (merits(slug=None), "slug"),
        (merits(summary=""), "summary"),
        (merits(summary="x" * 201), "summary"),
        (merits(summary="two\nlines"), "summary"),
        (merits(summary="/hos dispute F1"), "summary"),
        (merits(detail="d" * 2001), "detail"),
        (merits(source_url="https://github.com/other/repo/pull/1"), "source_url"),
        (merits(source_url="https://evil.example/Owner/Repo/"), "source_url"),
        (merits(source_url="https://github.com/owner/repo/../../other/x"), "source_url"),
        (merits(source_url="https://github.com/owner/repo/%2e%2e/x"), "source_url"),
        (merits(source_url="https://github.com/owner/repo/..\\x"), "source_url"),
        (
            merits(conflicts_with={"reviewer": "sec", "ref": "https://github.com/owner/repo/a\\b"}),
            "conflicts_with.ref",
        ),
        (
            merits(conflicts_with={"reviewer": "sec", "ref": "https://github.com/owner/repo/../x"}),
            "conflicts_with.ref",
        ),
        ({"class": "CHECK", "summary": "s", "check_run": "not-a-run"}, "check_run"),
        ({"class": "CHECK", "summary": "s", "check_run": "shellcheck", "slug": "abc"}, "slug"),
        (
            {"class": "CHECK", "summary": "s", "check_run": "shellcheck", "rule": "bad rule!"},
            "rule",
        ),
        (merits(check_run="shellcheck"), "check_run"),
        (merits(decision="not an object"), "decision"),
        (merits(decision={"question": "q", "options": [{"label": "A"}]}), "decision.options[0]"),
        (
            merits(
                conflicts_with={"reviewer": "BAD NAME", "ref": "https://github.com/owner/repo/x"}
            ),
            "conflicts_with",
        ),
        (
            merits(conflicts_with={"reviewer": "sec", "ref": "https://github.com/x/y/z"}),
            "conflicts_with.ref",
        ),
    ],
)
def test_t_fs_1_refusals(entry, fragment):
    with pytest.raises(FindingsSchemaError) as err:
        canon([entry])
    assert fragment in str(err.value) and "findings[0]" in str(err.value)


def test_t_fs_1_top_level_and_size_limits():
    for bad in ([], {"findings": {}}, {"findings": [], "extra": 1}, "x"):
        with pytest.raises(FindingsSchemaError):
            ma.canonicalize_findings(
                bad, changed_paths=CHANGED, head_check_runs=[], repo_slug="o/r"
            )
    with pytest.raises(FindingsSchemaError):
        canon([merits(slug=f"slug-{i:03d}") for i in range(ma.FINDINGS_MAX + 1)])
    with pytest.raises(ma.FindingsFileError):
        ma.parse_findings_bytes(b"x" * (ma.FINDINGS_FILE_MAX_BYTES + 1))
    with pytest.raises(ma.FindingsFileError):
        ma.parse_findings_bytes(b"{not json")
    with pytest.raises(ma.FindingsFileError):
        ma.load_findings_file("/nonexistent/findings.json")


def test_t_fs_2_canonical_keys_and_identities():
    got = canon(
        [
            {
                "class": "CHECK",
                "summary": "s",
                "check_run": "shellcheck",
                "rule": "SC1090",
                "path": "./bin/hos-cron",
            },
            {"class": "CHECK", "summary": "s", "check_run": "tests"},
            merits(path="café.py".replace("é", "é")),  # NFD input matches the NFC changed path
            {"class": "SCOPE", "summary": "s", "slug": "too-big"},
            merits(),
            merits(summary="duplicate key"),
        ]
    )
    assert [f.key for f in got] == [
        "check:shellcheck:SC1090:bin/hos-cron",
        "check:tests:-:-",
        "MERITS:café.py:good-slug",
        "SCOPE:-:too-big",
        "MERITS:docs/a.md:good-slug",
    ]
    assert got[0].identity == ("CHECK", "shellcheck", "bin/hos-cron")
    assert got[2].identity == ("MERITS", "café.py")
    assert all(f.origin == "llm" for f in got)
    _, reasons = ma.canonicalize_findings_ex(
        {"findings": [merits(), merits()]},
        changed_paths=CHANGED,
        head_check_runs=[],
        repo_slug="o/r",
    )
    assert reasons == ("duplicate-key:1",)


def test_t_fs_2_path_case_is_kept():
    with pytest.raises(FindingsSchemaError):
        canon([merits(path="Docs/A.md")])


def test_t_fs_2_same_repo_url_rejects_whitespace_and_overlong_values():
    base = "https://github.com/owner/repo/pull/3"
    for bad in (base + "#a b", base + "#" + "x" * 600, "http://github.com/owner/repo/x", 5):
        with pytest.raises(ma.FindingsSchemaError):
            ma._same_repo_url(bad, "owner/repo", 0, "source_url")
    # whitespace alone (short) and length alone (no whitespace) each reject
    with pytest.raises(ma.FindingsSchemaError):
        ma._same_repo_url(base + "#\tz", "owner/repo", 0, "source_url")
    assert ma._same_repo_url(base, "owner/repo", 0, "source_url") == base


def test_derive_reason_category_single_and_mixed():
    assert ma.derive_reason_category(["CHECK", "CHECK"]) == "CHECK_FAILURE"
    assert ma.derive_reason_category(["MERITS"]) == "MERITS_FINDING"
    assert ma.derive_reason_category(["CHECK", "MERITS"]) == "MIXED"


def test_escalation_records_require_cid_match_and_known_trigger(tmp_path):
    from scripts.oversight.lib import audit_log

    def ev(**over):
        e = {
            "event": "human-required",
            "cid": "issue-1",
            "pr": 5,
            "head_sha": HEAD,
            "trigger": "bounce-cap",
            "escalation_created_at": "2026-10-30T01:00:00Z",
            "options": ["A"],
        }
        e.update(over)
        audit_log.write_event(e, root=str(tmp_path))

    ev(trigger="not-a-trigger")
    ev(cid="issue-2")
    ev(cid="")
    got = ma.escalation_records("issue-1", repo_root=str(tmp_path))
    assert got == []
    ev()
    assert len(ma.escalation_records("issue-1", repo_root=str(tmp_path))) == 1


def test_t_fs_2_same_repo_url_is_case_insensitive():
    got = canon([merits(source_url="https://github.com/OWNER/repo/pull/3#r1")])
    assert got[0].source_url.endswith("#r1")


def test_t_fs_1_malformed_decision_is_dropped_with_a_reason():
    good = {
        "question": "Which?",
        "options": [{"label": "A", "text": "x"}, {"label": "B", "text": "y"}],
    }
    cases = [
        {"question": "  ", "options": good["options"]},
        {"question": "q", "options": good["options"][:1]},
        {"question": "q", "options": [{"label": "A", "text": "x"}, {"label": "A", "text": "y"}]},
        {"question": "q", "options": [{"label": "A", "text": "x"}, {"label": "B", "text": "x"}]},
        {"question": "q", "options": [{"label": "A B", "text": "x"}, {"label": "B", "text": "y"}]},
    ]
    for bad in cases:
        findings, reasons = ma.canonicalize_findings_ex(
            {"findings": [merits(decision=bad)]},
            changed_paths=CHANGED,
            head_check_runs=[],
            repo_slug="o/r",
        )
        assert findings[0].decision is None and not findings[0].is_decision
        assert reasons == ("decision-malformed:0",)
    findings, reasons = ma.canonicalize_findings_ex(
        {"findings": [merits(decision=good)]},
        changed_paths=CHANGED,
        head_check_runs=[],
        repo_slug="o/r",
    )
    assert findings[0].is_decision and reasons == ()


# --------------------------------------------------------------------------- #
# T-HT: the #902 head time
# --------------------------------------------------------------------------- #


def suite(created, slug="github-actions", head=HEAD):
    return {"id": 1, "head_sha": head, "created_at": created, "app": {"slug": slug}}


def test_t_ht_1_future_committer_date_is_capped_by_the_server_side_suite():
    forged = "2099-01-01T00:00:00Z"
    got = ma.effective_head_time(forged, [suite("2026-10-31T00:00:05Z")], head_sha=HEAD)
    assert got == "2026-10-31T00:00:05Z"
    # earliest of several actions suites; a queued run does not matter (the suite exists)
    got = ma.effective_head_time(
        forged, [suite("2026-10-31T00:00:09Z"), suite("2026-10-31T00:00:05Z")], head_sha=HEAD
    )
    assert got == "2026-10-31T00:00:05Z"
    # an honest earlier committer date is kept
    assert (
        ma.effective_head_time(
            "2026-10-30T00:00:00Z", [suite("2026-10-31T00:00:05Z")], head_sha=HEAD
        )
        == "2026-10-30T00:00:00Z"
    )


def test_t_ht_1_queued_only_suite_still_bounds_a_forged_committer_date():
    """AR1-C7: a github-actions suite whose runs are all queued (no started_at)
    still exists server-side, so its created_at bounds the forged date."""
    queued = {
        "id": 7,
        "head_sha": HEAD,
        "status": "queued",
        "conclusion": None,
        "started_at": None,
        "created_at": "2026-10-31T00:00:05Z",
        "app": {"slug": "github-actions"},
    }
    forged = "2099-01-01T00:00:00Z"
    assert ma.effective_head_time(forged, [queued], head_sha=HEAD) == "2026-10-31T00:00:05Z"
    # not merely "some value": a result of None would clear no hold and a
    # forged value would clear every hold; the bound is the one right answer
    assert ma.effective_head_time(None, [queued], head_sha=HEAD) == "2026-10-31T00:00:05Z"
    # a queued suite from a non-Actions app is still ignored
    other = dict(queued, app={"slug": "some-app"})
    assert ma.effective_head_time(forged, [other], head_sha=HEAD) is None


def test_t_ht_1_no_actions_suite_gives_none_even_with_a_committer_date():
    assert ma.effective_head_time("2026-10-30T00:00:00Z", [], head_sha=HEAD) is None
    assert (
        ma.effective_head_time(
            "2026-10-30T00:00:00Z", [suite("2026-10-31T00:00:05Z", slug="some-app")], head_sha=HEAD
        )
        is None
    )
    assert (
        ma.effective_head_time(
            "2026-10-30T00:00:00Z", [suite("2026-10-31T00:00:05Z", head="e" * 40)], head_sha=HEAD
        )
        is None
    )


def test_t_ht_2_hold_after_push_survives_a_forged_future_commit_date():
    eff = ma.effective_head_time(
        "2099-01-01T00:00:00Z", [suite("2026-10-31T00:00:05Z")], head_sha=HEAD
    )
    comments = [
        {
            "user": {"login": "ScottThurlow"},
            "body": "do not merge this",
            "created_at": "2026-10-31T01:00:00Z",
            "html_url": "u",
        }
    ]
    hold = ma.detect_human_hold_directive(comments, "ScottThurlow", eff)
    assert hold is not None
    # the pre-fix behaviour: trusting the forged date would have cleared the hold
    assert ma.detect_human_hold_directive(comments, "ScottThurlow", "2099-01-01T00:00:00Z") is None
    r = route_pr(inputs(hold_on_head=hold is not None))
    assert (r.disposition, r.reasons) == (D.LEGACY, ("hold-902",))


# --------------------------------------------------------------------------- #
# T-GH-1: the three new github.py reads
# --------------------------------------------------------------------------- #


def test_t_gh_1_list_issue_events_paginates_in_order():
    pages = [[{"id": i} for i in range(100)], [{"id": 100}]]
    calls = []

    def fake(args, **k):
        calls.append(args[0])
        return pages[len(calls) - 1]

    with patch.object(gh, "_run_gh", side_effect=fake):
        got = gh.list_issue_events("o", "r", 5)
    assert [e["id"] for e in got] == list(range(101))
    assert calls[0].endswith("/issues/5/events?per_page=100&page=1")
    assert calls[1].endswith("page=2")


def test_t_gh_1_list_issue_events_never_truncates():
    with patch.object(gh, "_run_gh", return_value=[{"id": 1}] * 100):
        with pytest.raises(gh.ListTruncatedError):
            gh.list_issue_events("o", "r", 5, max_pages=3)
    with patch.object(gh, "_run_gh", return_value={"not": "a list"}):
        with pytest.raises(gh.ListTruncatedError):
            gh.list_issue_events("o", "r", 5)
    with patch.object(gh, "_run_gh", return_value=None):
        with pytest.raises(GitHubError) as err:  # a 404 is never an empty, complete list
            gh.list_issue_events("o", "r", 5)
    assert err.value.status_code == 404


def test_t_gh_1_list_check_suites_concatenates_and_validates():
    pages = [{"check_suites": [{"id": i} for i in range(100)]}, {"check_suites": [{"id": 100}]}]
    seen = []

    def fake(args, **k):
        seen.append(args[0])
        return pages[len(seen) - 1]

    with patch.object(gh, "_run_gh", side_effect=fake):
        assert len(gh.list_check_suites_for_ref("o", "r", "abc")) == 101
    assert "/commits/abc/check-suites?per_page=100&page=1" in seen[0]
    for bad in ([], {"check_suites": "x"}, None):
        with patch.object(gh, "_run_gh", return_value=bad):
            with pytest.raises(gh.ListTruncatedError):
                gh.list_check_suites_for_ref("o", "r", "abc")
    with patch.object(gh, "_run_gh", return_value={"check_suites": [{"id": 1}] * 100}):
        with pytest.raises(gh.ListTruncatedError):
            gh.list_check_suites_for_ref("o", "r", "abc", max_pages=2)


def test_t_gh_1_get_contents():
    with patch.object(gh, "_run_gh", return_value=None):
        assert gh.get_contents("o", "r", "a b/CODEOWNERS", ref="main") is None
    with patch.object(gh, "_run_gh", return_value=[{"name": "x"}]):
        with pytest.raises(GitHubError):
            gh.get_contents("o", "r", "dir", ref="main")
    with patch.object(gh, "_run_gh", return_value={"content": "x"}) as run:
        assert gh.get_contents("o", "r", "docs/a b.md", ref="feat/x") == {"content": "x"}
    url = run.call_args[0][0][0]
    assert url == "/repos/o/r/contents/docs/a%20b.md?ref=feat%2Fx"


# --------------------------------------------------------------------------- #
# T-REPLAY: PR #2207 at 02:27Z
# --------------------------------------------------------------------------- #

OVERSEER = "hos-overseer-hos[bot]"
WORKER = "hos-worker-hos[bot]"


def _write_config(root: Path) -> None:
    fw = root / "scripts" / "framework"
    fw.mkdir(parents=True, exist_ok=True)
    values = {
        "BOT_WORKER_USERNAME": WORKER,
        "BOT_OVERSEER_USERNAME": OVERSEER,
        "BOT_ACCOUNTS": f"{WORKER} {OVERSEER} scottthurlow-claude[bot]",
        "OVERSEER_CEILING": "HIGH",
        "TIER_CEILING_CHECK_NAME": "require-tier-ceiling",
        "HUMAN_REVIEWER": "ScottThurlow",
    }
    (fw / "machine-accounts.env").write_text("".join(f'{k}="{v}"\n' for k, v in values.items()))


@pytest.fixture
def replay(tmp_path, monkeypatch):
    return _build_replay(tmp_path, monkeypatch, None)


def _build_replay(tmp_path, monkeypatch, findings_override):
    fx = json.loads(FIXTURE.read_text())
    root = tmp_path / "repo"
    _write_config(root)
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(findings_override or fx["findings_file"]))
    monkeypatch.setenv("HOS_BOT_LOGIN", OVERSEER)

    posts, gh_calls = [], []

    def run_gh(args, *a, **k):
        gh_calls.append((args, k))
        if args[0].endswith("/pulls/2207"):
            return {"draft": True, "labels": [{"name": "needs-ai"}]}
        return {}

    pr = fx["pr"]
    monkeypatch.setattr(gh, "get_pull", lambda o, r, n: pr)
    monkeypatch.setattr(gh, "get_issue", lambda o, r, n: fx["issue_2171"])
    monkeypatch.setattr(gh, "list_pull_files", lambda o, r, n: fx["files"])
    monkeypatch.setattr(gh, "list_check_runs_for_ref", lambda o, r, ref: fx["check_runs"])
    monkeypatch.setattr(gh, "list_check_suites_for_ref", lambda o, r, ref, **k: fx["check_suites"])
    monkeypatch.setattr(gh, "list_pull_reviews", lambda o, r, n: fx["reviews"])
    monkeypatch.setattr(gh, "list_issue_events", lambda o, r, n, **k: [])
    monkeypatch.setattr(gh, "list_issue_comments", lambda o, r, n, **k: fx["comments"])
    monkeypatch.setattr(
        gh, "get_commit", lambda o, r, ref: {"commit": {"committer": {"date": pr["created_at"]}}}
    )
    monkeypatch.setattr(
        ma,
        "get_contents",
        lambda o, r, p, *, ref: (
            _payload(fx["codeowners_base_text"]) if p == ".github/CODEOWNERS" else None
        ),
    )
    monkeypatch.setattr(
        ma,
        "check_required_content_checks",
        lambda *a, **k: ma.RequiredChecksResult(**fx["required_checks_result"]),
    )
    monkeypatch.setattr(
        ma,
        "post_comment",
        lambda o, r, n, body, **k: posts.append(body)
        or {
            "id": len(posts),
            "html_url": "https://example/c",
            "created_at": "2026-10-29T02:28:00Z",
        },
    )
    monkeypatch.setattr(ma, "_run_gh", run_gh)
    monkeypatch.setattr(ma, "_convert_pr_to_draft", lambda o, r, n: None)

    def go(capsys):
        argv = [
            "route",
            "--app",
            "overseer",
            "--pr",
            "2207",
            "--step",
            "1",
            "--findings-file",
            str(findings_path),
            "--repo",
            "thurlow-research/HumanOversightSystem",
        ]
        rc = cli.main(argv, repo_root=str(root))
        record = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        return rc, record

    return go, posts, gh_calls, fx, root


def test_t_replay_pr_2207_bounces_and_never_goes_to_the_human(replay, capsys):
    go, posts, gh_calls, fx, _root = replay
    rc, record = go(capsys)
    assert rc == 0, record
    assert (record["disposition"], record["rule"], record["cid"]) == ("BOUNCE", "6e", "issue-2171")
    assert len(posts) == 1
    assert "[d33c93ba7000-F1] (CHECK)" in posts[0] and "SC1090" in posts[0]
    assert "REQUEST CHANGES" not in posts[0] and "needs-human" not in posts[0]
    urls = [c[0][0] for c in gh_calls]
    assert not [u for u in urls if "requested_reviewers" in u or u.endswith("/reviews")]
    labels = [c[1]["stdin_json"] for c in gh_calls if c[0][0].endswith("/labels")]
    assert labels == [{"labels": ["needs-ai"]}]
    assert ma.touches_protected_surface(["bin/hos-cron"], repo_root=str(REPO_ROOT)) is True

    # Same head, event now on disk: a repeat is a NOOP and posts nothing.
    rc2, record2 = go(capsys)
    assert rc2 == 0
    assert (record2["disposition"], record2["rule"]) == ("NOOP", "6c")
    assert len(posts) == 1


@pytest.mark.parametrize("ch", list("()[]<>@!`"))
def test_same_repo_url_rejects_markdown_breakout_characters(ch):
    base = "https://github.com/owner/repo/pull/3"
    for url in (f"{base}?x={ch}", f"{base}#a{ch}b"):
        with pytest.raises(ma.FindingsSchemaError):
            ma._same_repo_url(url, "owner/repo", 0, "source_url")


def test_neutralize_escapes_ampersand_so_entity_mentions_do_not_render():
    out = ma._neutralize("&#64;name &amp;")
    assert out == "&amp;#64;name &amp;amp;"


def test_withdrawing_one_finding_does_not_drop_a_same_class_same_path_sibling():
    f1 = llm("first")
    f2 = llm("second")  # same (cls, path) identity, different key (TD R-7)
    assert f1.identity == f2.identity and f1.key != f2.key
    r = route_pr(
        inputs(
            findings=(f1, f2),
            prior_on_head=(prior_of(f1, "F1"),),
            withdrawn_on_head=frozenset({"F1"}),
        )
    )
    assert r.open_findings == (f2,)


# --------------------------------------------------------------------------- #
# #2346: REVIEW_CHAIN (incomplete review chain) through route --findings-file
# --------------------------------------------------------------------------- #

_CHAIN_FINDINGS = {
    "findings": [
        {
            "class": "REVIEW_CHAIN",
            "slug": "second-review-agy",
            "summary": "No second review (agy) ran on this head.",
        },
        {
            "class": "REVIEW_CHAIN",
            "slug": "oversight-evaluator",
            "summary": "No oversight-evaluator run on this head.",
        },
    ]
}


def test_t_2346_review_chain_replay_bounces_as_register_gap(tmp_path, monkeypatch, capsys):
    go, posts, gh_calls, fx, root = _build_replay(tmp_path, monkeypatch, _CHAIN_FINDINGS)
    rc, record = go(capsys)
    assert rc == 0, record
    assert (record["disposition"], record["cid"]) == ("BOUNCE", "issue-2171")
    assert len(posts) == 1
    assert "(REVIEW_CHAIN)" in posts[0]
    assert "**Reason category:** REGISTER_GAP" in posts[0]
    assert "**Summary:** incomplete-review-chain: oversight-evaluator, second-review-agy" in posts[0]
    labels = [c[1]["stdin_json"] for c in gh_calls if c[0][0].endswith("/labels")]
    assert labels == [{"labels": ["needs-ai"]}]

    from scripts.oversight.lib import audit_log

    events = [json.loads(b) for b in audit_log.read_stream(str(root))]
    events = [e for e in events if e.get("event") == "pr-bounced"]
    assert len(events) == 1
    assert events[0]["reason_category"] == "REGISTER_GAP"
    assert events[0]["summary"].startswith("incomplete-review-chain: oversight-evaluator, second-review-agy")


def test_t_2346_review_chain_at_cap_escalates_like_other_classes(tmp_path, monkeypatch, capsys):
    go, posts, gh_calls, fx, root = _build_replay(tmp_path, monkeypatch, _CHAIN_FINDINGS)
    for n in (1, 2):
        _bounce_event(root, n, "2026-10-29T03:00:00Z", cid="issue-2171", pr=2207)
    rc, record = go(capsys)
    assert rc == 0, record
    assert (record["disposition"], record["rule"], record["trigger"]) == (
        "ESCALATE",
        "6d",
        "bounce-cap",
    )
    assert posts == []


@pytest.mark.parametrize(
    "entry, fragment",
    [
        ({"class": "REVIEW_CHAIN", "slug": "made-up-role", "summary": "s"}, "slug"),
        ({"class": "REVIEW_CHAIN", "slug": "oversight-evaluator", "summary": "s", "path": "docs/a.md"}, "path"),
        ({"class": "REVIEW_CHAIN", "summary": "s"}, "slug"),
    ],
)
def test_t_2346_review_chain_schema_refusals(entry, fragment):
    with pytest.raises(FindingsSchemaError) as err:
        canon([entry])
    assert fragment in str(err.value)


def test_t_2346_review_chain_keys_identity_and_summary():
    got = canon(
        [
            {"class": "REVIEW_CHAIN", "slug": "second-review-codex", "summary": "s"},
            {"class": "REVIEW_CHAIN", "slug": "security-reviewer", "summary": "s"},
            merits(),
        ]
    )
    assert [f.key for f in got] == [
        "REVIEW_CHAIN:-:second-review-codex",
        "REVIEW_CHAIN:-:security-reviewer",
        "MERITS:docs/a.md:good-slug",
    ]
    assert got[0].identity != got[1].identity
    assert ma.derive_reason_category(["REVIEW_CHAIN"]) == "REGISTER_GAP"
    assert ma.derive_reason_category(["REVIEW_CHAIN", "MERITS"]) == "MIXED"
    assert ma.bounce_summary_for(got, "a" * 40).startswith(
        "incomplete-review-chain: second-review-codex, security-reviewer"
    )
    assert ma.bounce_summary_for(got[2:], "a" * 40) == ma.bounce_summary(1, "a" * 40)
