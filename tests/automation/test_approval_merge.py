"""Tests for scripts/automation/lib/approval_merge.py and the live-gate verifier
(#2213 slice S1a, TD-2213 §7.1-§7.3).

The replay fixture is built from the state PR #2211 had on 2026-10-30 (real ids
and timestamps, bodies trimmed). Nothing here touches the network.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any

import pytest

from scripts.automation.lib import approval_merge as am
from scripts.automation.lib import github, merge_authority
from scripts.automation.lib.merge_config import MergeConfig
from scripts.framework import require_overseer_approval as roa

HEAD = "35a3b20382b1767b9789220bbe9b69a9735effd4"  # pragma: allowlist secret
OTHER_HEAD = "b" * 40
OVERSEER = "hos-overseer-hos[bot]"
WORKER = "hos-worker-hos[bot]"
PROXY = "scottthurlow-claude[bot]"
HUMAN = "ScottThurlow"
APPROVAL_AT = "2026-10-30T05:39:47Z"
NOW = datetime(2026, 10, 30, 5, 44, 0, tzinfo=timezone.utc)

REQUIRED_CONTEXTS = (
    "require-human-approval",
    "require-tier-ceiling",
    "require-overseer-approval",
    "tests",
    "oversight-gate-repo-scoped",
    "oversight-gate-lint",
    "oversight-gate-type-check",
    "oversight-validator-python",
    "oversight-validator-migration",
    "oversight-validator-shell",
    "oversight-validator-diff-size",
)


def make_config(**overrides) -> MergeConfig:
    values: dict[str, Any] = dict(
        overseer_ceiling=merge_authority.RiskTier.HIGH,
        human_reviewer=HUMAN,
        overseer_handle=OVERSEER,
        worker_handle=WORKER,
        bot_accounts=frozenset({WORKER, OVERSEER, PROXY, "copilot-pull-request-reviewer[bot]"}),
        tier_ceiling_check_name="require-tier-ceiling",
        config_source="test",
    )
    values.update(overrides)
    return MergeConfig(**values)


CONFIG = make_config()


def make_pull(**overrides) -> dict:
    pull = {
        "number": 2211,
        "state": "open",
        "merged": False,
        "draft": False,
        "title": "[AI: hos-worker-hos[bot]] fix: pre-agent gh consumers check exit status",
        "user": {"login": WORKER, "type": "Bot"},
        "base": {"ref": "main"},
        "head": {"sha": HEAD},
        "labels": [{"name": "needs-human"}],
        "mergeable_state": "clean",
        "changed_files": 3,
    }
    pull.update(overrides)
    return pull


def overseer_marker_body(action: str = "APPROVE", disposition: str = "HUMAN_REQUIRED") -> str:
    return "**Executive summary:** verdict.\n\n" + roa.render_interim_marker(
        disposition, action, HEAD
    )


def make_reviews() -> list[dict]:
    return [
        {
            "id": 5702138899,
            "user": {"login": OVERSEER, "type": "Bot"},
            "state": "COMMENTED",
            "body": overseer_marker_body(),
            "commit_id": HEAD,
            "submitted_at": "2026-10-29T17:27:54Z",
        },
        {
            "id": 5702142635,
            "user": {"login": OVERSEER, "type": "Bot"},
            "state": "COMMENTED",
            "body": "",
            "commit_id": HEAD,
            "submitted_at": "2026-10-29T17:28:10Z",
        },
        {
            "id": 5708492480,
            "user": {"login": HUMAN, "type": "User"},
            "state": "APPROVED",
            "body": "",
            "commit_id": HEAD,
            "submitted_at": APPROVAL_AT,
        },
    ]


def make_events() -> list[dict]:
    return [
        {
            "id": 34614334737,
            "event": "labeled",
            "label": {"name": "needs-human"},
            "actor": {"login": OVERSEER, "type": "Bot"},
            "created_at": "2026-10-29T17:28:25Z",
        }
    ]


def make_check_runs(**overrides) -> list[dict]:
    """28 completed/success runs including every required context; `overrides`
    maps a name to a (status, conclusion) pair."""
    names = list(REQUIRED_CONTEXTS) + [am.AGENT_STATIC_CHECK]
    names += [f"extra-{i}" for i in range(28 - len(names))]
    runs = []
    for i, name in enumerate(names):
        status, conclusion = overrides.get(name, ("completed", "success"))
        runs.append({"id": 1000 + i, "name": name, "status": status, "conclusion": conclusion})
    return runs


def make_gate(**overrides) -> merge_authority.LiveGateResult:
    values: dict[str, Any] = dict(
        autonomous_capable=True,
        reason="ruleset gate verified (#2213 AD-5)",
        required_contexts=REQUIRED_CONTEXTS,
        ruleset_ids=(18044233,),
    )
    values.update(overrides)
    return merge_authority.LiveGateResult(**values)


def snap(**overrides) -> am.ApprovalMergeSnapshot:
    """The REPLAY-1 snapshot; any field can be overridden."""
    values: dict[str, Any] = dict(
        pr_number=2211,
        pull=make_pull(),
        now=NOW,
        default_branch="main",
        changed_files=("scripts/automation/lib/github.py", "tests/a.py", "docs/x.md"),
        reviews=tuple(make_reviews()),
        issue_comments=(
            {
                "id": 6515873383,
                "user": {"login": PROXY, "type": "Bot"},
                "body": "Relaying the approval.",
                "created_at": "2026-10-30T05:40:07Z",
            },
        ),
        issue_events=tuple(make_events()),
        review_threads=tuple({"id": f"t{i}", "isResolved": True} for i in range(8)),
        head_committed_at="2026-10-29T16:48:44Z",
        check_runs=tuple(make_check_runs()),
        codeowners_owners=frozenset({"scottthurlow"}),
        audit_events=(),
        gate=make_gate(),
    )
    values.update(overrides)
    for key in ("reviews", "issue_comments", "issue_events", "check_runs", "audit_events"):
        if isinstance(values[key], list):
            values[key] = tuple(values[key])
    return am.ApprovalMergeSnapshot(**values)


def decide(**overrides) -> am.ApprovalMergeDecision:
    return am.decide_merge_on_human_approval(snap(**overrides), CONFIG)


def reviews_plus(*extra: dict) -> list[dict]:
    return make_reviews() + list(extra)


def review(
    login: str,
    state: str,
    at: str,
    *,
    rid: int = 9000000001,
    body: str = "",
    commit: str = HEAD,
    kind: str = "User",
) -> dict:
    return {
        "id": rid,
        "user": {"login": login, "type": kind},
        "state": state,
        "body": body,
        "commit_id": commit,
        "submitted_at": at,
    }


def comment(login: str, body: str, at: str, kind: str = "User") -> dict:
    return {"user": {"login": login, "type": kind}, "body": body, "created_at": at}


def assert_decision(d, outcome, reason):
    assert (d.outcome.name, d.reason) == (outcome, reason), d


# --------------------------------------------------------------------------- #
# 7.1 — the #2211 replay
# --------------------------------------------------------------------------- #


def test_replay_1_merges():
    d = decide()
    assert_decision(d, "MERGE", "approved_by_designated_human")
    assert d.approver == HUMAN
    assert d.approving_review_id == 5708492480
    assert d.head_sha == HEAD
    assert d.approved_at == APPROVAL_AT
    assert d.overseer_verdict_id == 5702138899
    assert d.verdict_kind == "marker:HUMAN_REQUIRED"
    assert d.label_provenance["labeled_event_id"] == 34614334737
    assert d.label_provenance["actor"] == OVERSEER
    assert d.to_dict()["outcome"] == "MERGE"


def test_replay_2_human_added_label():
    events = make_events()
    events[0]["actor"] = {"login": HUMAN, "type": "User"}
    assert_decision(decide(issue_events=events), "NOT_ELIGIBLE", "foreign_needs_human")


def test_replay_2b_human_proxy_added_label():
    events = make_events()
    events[0]["actor"] = {"login": PROXY, "type": "Bot"}
    assert_decision(decide(issue_events=events), "NOT_ELIGIBLE", "foreign_needs_human")


def test_replay_2c_relabel_by_human_after_unlabel():
    events = make_events() + [
        {
            "id": 34614334800,
            "event": "unlabeled",
            "label": {"name": "needs-human"},
            "actor": {"login": HUMAN, "type": "User"},
            "created_at": "2026-10-30T01:00:00Z",
        },
        {
            "id": 34614334900,
            "event": "labeled",
            "label": {"name": "needs-human"},
            "actor": {"login": HUMAN, "type": "User"},
            "created_at": "2026-10-30T02:00:00Z",
        },
    ]
    assert_decision(decide(issue_events=events), "NOT_ELIGIBLE", "foreign_needs_human")


def test_replay_3_hos_halt():
    pull = make_pull(labels=[{"name": "needs-human"}, {"name": "hos-halt"}])
    assert_decision(decide(pull=pull), "NOT_ELIGIBLE", "hos_halt")


def test_replay_4_stale_head_approval():
    pull = make_pull(head={"sha": OTHER_HEAD})
    assert_decision(decide(pull=pull), "NOT_ELIGIBLE", "no_eligible_approval")


def test_replay_5_af5_pin_other_action_blocks():
    later = review(
        OVERSEER,
        "COMMENTED",
        "2026-10-30T05:42:18Z",
        rid=5708508520,
        body=overseer_marker_body("OTHER"),
        kind="Bot",
    )
    assert_decision(decide(reviews=reviews_plus(later)), "NOT_ELIGIBLE", "no_approve_signoff")


def test_replay_6_later_approve_marker_merges():
    later = review(
        OVERSEER,
        "COMMENTED",
        "2026-10-30T05:42:18Z",
        rid=5708508520,
        body=overseer_marker_body("APPROVE"),
        kind="Bot",
    )
    d = decide(reviews=reviews_plus(later))
    assert_decision(d, "MERGE", "approved_by_designated_human")
    assert d.overseer_verdict_id == 5708508520


def test_replay_7_unmarked_overseer_approval():
    reviews = make_reviews()
    reviews[0]["state"] = "APPROVED"
    reviews[0]["body"] = "approved by the overseer"
    d = decide(reviews=reviews)
    assert_decision(d, "MERGE", "approved_by_designated_human")
    assert d.verdict_kind == "approved"


def test_replay_8_propose_only_without_label():
    reviews = make_reviews()
    reviews[0]["body"] = overseer_marker_body("APPROVE", "PROPOSE_ONLY")
    pull = make_pull(labels=[])
    d = decide(reviews=reviews, pull=pull, issue_events=())
    assert_decision(d, "MERGE", "approved_by_designated_human")
    assert d.verdict_kind == "marker:PROPOSE_ONLY"
    assert d.label_provenance == {"absent": True}


# --------------------------------------------------------------------------- #
# 7.2 — one negative per rule
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "pull_overrides, reason",
    [
        ({"state": "closed"}, "not_open_pr"),
        ({"merged": True}, "not_open_pr"),
        ({"draft": True}, "draft"),
        ({"base": {"ref": "release"}}, "base_not_default_branch"),
    ],
)
def test_r2_negatives(pull_overrides, reason):
    assert_decision(decide(pull=make_pull(**pull_overrides)), "NOT_ELIGIBLE", reason)


def test_r4_release_title_and_path():
    assert_decision(decide(pull=make_pull(title="Release v0.7.0")), "NOT_ELIGIBLE", "release")
    assert_decision(decide(changed_files=("docs/releases/x.md",)), "NOT_ELIGIBLE", "release")


def test_r5_self_authored_and_missing_author():
    assert_decision(
        decide(pull=make_pull(user={"login": OVERSEER})), "NOT_ELIGIBLE", "self_authored"
    )
    assert_decision(
        decide(pull=make_pull(user={"login": ""})), "UNDETERMINABLE", "pr_author_missing"
    )


def test_r6_individual_codeowner_is_designated():
    reviews = make_reviews()
    reviews[2] = review("alice", "APPROVED", APPROVAL_AT, rid=77)
    d = decide(reviews=reviews, codeowners_owners=frozenset({"alice"}))
    assert_decision(d, "MERGE", "approved_by_designated_human")
    assert d.approver == "alice"


def test_r6_approval_on_older_commit():
    reviews = make_reviews()
    reviews[2]["commit_id"] = OTHER_HEAD
    assert_decision(decide(reviews=reviews), "NOT_ELIGIBLE", "no_eligible_approval")


def test_r6_bot_and_proxy_approvals_do_not_count():
    reviews = make_reviews()[:2] + [
        review(WORKER, "APPROVED", APPROVAL_AT, rid=1, kind="Bot"),
        review(PROXY, "APPROVED", APPROVAL_AT, rid=2, kind="Bot"),
    ]
    assert_decision(decide(reviews=reviews), "NOT_ELIGIBLE", "no_eligible_approval")


def test_r6_non_designated_collaborator():
    reviews = make_reviews()[:2] + [review("bob", "APPROVED", APPROVAL_AT, rid=3)]
    assert_decision(decide(reviews=reviews), "NOT_ELIGIBLE", "no_eligible_approval")


@pytest.mark.parametrize("state", ["CHANGES_REQUESTED", "DISMISSED"])
def test_r6_approval_withdrawn(state):
    reviews = reviews_plus(review(HUMAN, state, "2026-10-30T05:41:00Z", rid=9))
    assert_decision(decide(reviews=reviews), "NOT_ELIGIBLE", "no_eligible_approval")


def test_r6_empty_designated_set():
    cfg = make_config(human_reviewer="")
    d = am.decide_merge_on_human_approval(snap(codeowners_owners=frozenset()), cfg)
    assert_decision(d, "UNDETERMINABLE", "no_designated_humans")


def test_r6_two_approvers_latest_chosen():
    reviews = reviews_plus(review("alice", "APPROVED", "2026-10-30T05:41:00Z", rid=88))
    d = decide(reviews=reviews, codeowners_owners=frozenset({"scottthurlow", "alice"}))
    assert_decision(d, "MERGE", "approved_by_designated_human")
    assert (d.approver, d.approving_review_id) == ("alice", 88)


def test_r6_unparseable_approval_timestamp():
    reviews = make_reviews()
    reviews[2]["submitted_at"] = "garbage"
    assert_decision(decide(reviews=reviews), "UNDETERMINABLE", "timestamp:approval")


def test_r7_negatives():
    only_approval = [make_reviews()[2]]
    assert_decision(decide(reviews=only_approval), "NOT_ELIGIBLE", "no_approve_signoff")

    unmarked = make_reviews()
    unmarked[0]["body"] = "a verdict without a marker"
    assert_decision(decide(reviews=unmarked), "NOT_ELIGIBLE", "no_approve_signoff")

    do_not_merge = make_reviews()
    do_not_merge[0]["body"] = overseer_marker_body("DO_NOT_MERGE")
    assert_decision(decide(reviews=do_not_merge), "NOT_ELIGIBLE", "no_approve_signoff")

    dismissed = reviews_plus(
        review(OVERSEER, "DISMISSED", "2026-10-30T05:41:00Z", rid=5, body="dismissed", kind="Bot")
    )
    assert_decision(decide(reviews=dismissed), "NOT_ELIGIBLE", "no_approve_signoff")


def test_r7_empty_container_after_verdict_still_passes():
    container = review(OVERSEER, "COMMENTED", "2026-10-30T05:30:00Z", rid=6, kind="Bot")
    assert_decision(
        decide(reviews=reviews_plus(container)), "MERGE", "approved_by_designated_human"
    )


def test_r8_label_without_event():
    assert_decision(decide(issue_events=()), "UNDETERMINABLE", "label_event_missing")


def test_r8_unparseable_label_event_timestamp():
    events = make_events()
    events[0]["created_at"] = "garbage"
    assert_decision(decide(issue_events=events), "UNDETERMINABLE", "timestamp:label_event")


def test_r9_hold_directive_cases():
    hold = comment(HUMAN, "please hold off on this", "2026-10-30T01:00:00Z")
    assert_decision(decide(issue_comments=[hold]), "NOT_ELIGIBLE", "hold_directive")

    before_push = comment(HUMAN, "please hold off on this", "2026-10-29T10:00:00Z")
    assert_decision(decide(issue_comments=[before_push]), "MERGE", "approved_by_designated_human")

    stranger = comment("bob", "please hold off on this", "2026-10-30T01:00:00Z")
    assert_decision(decide(issue_comments=[stranger]), "MERGE", "approved_by_designated_human")

    reviews = make_reviews()
    reviews[2]["body"] = "approved but do not merge yet"
    assert_decision(decide(reviews=reviews), "NOT_ELIGIBLE", "hold_directive")

    assert_decision(decide(head_committed_at=None), "UNDETERMINABLE", "missing:head_committed_at")


def test_r9_forward_dated_commit_does_not_supersede_a_hold():
    hold = comment(HUMAN, "please hold off on this", "2026-10-30T01:00:00Z")
    d = decide(issue_comments=[hold], head_committed_at="2030-01-01T00:00:00Z")
    assert_decision(d, "NOT_ELIGIBLE", "hold_directive")


def test_r9_head_committed_after_approval_applies_no_cutoff():
    # Head 10 minutes after the approval (05:39:47Z): impossible for an honest
    # push, so no cutoff applies and a hold that predates both still blocks.
    hold = comment(HUMAN, "please hold off on this", "2026-10-29T10:00:00Z")
    d = decide(issue_comments=[hold], head_committed_at="2026-10-30T05:49:47Z")
    assert_decision(d, "NOT_ELIGIBLE", "hold_directive")


def test_r9_head_committed_before_approval_supersedes_earlier_hold():
    hold = comment(HUMAN, "please hold off on this", "2026-10-29T10:00:00Z")
    d = decide(issue_comments=[hold], head_committed_at="2026-10-29T16:48:44Z")
    assert_decision(d, "MERGE", "approved_by_designated_human")


def test_r10_designated_activity_after_approval():
    thanks = comment(HUMAN, "thanks", "2026-10-30T05:41:00Z")
    assert_decision(decide(issue_comments=[thanks]), "NOT_ELIGIBLE", "human_comment_after_approval")

    inline_reply = review(HUMAN, "COMMENTED", "2026-10-30T05:41:00Z", rid=11)
    assert_decision(
        decide(reviews=reviews_plus(inline_reply)),
        "NOT_ELIGIBLE",
        "human_comment_after_approval",
    )

    garbled = comment(HUMAN, "thanks", "garbage")
    assert_decision(decide(issue_comments=[garbled]), "UNDETERMINABLE", "timestamp:human_activity")


def test_r10_pending_review_is_ignored():
    pending = review(HUMAN, "COMMENTED", "", rid=12)
    pending["submitted_at"] = None
    assert_decision(decide(reviews=reviews_plus(pending)), "MERGE", "approved_by_designated_human")


def test_r11_unresolved_threads():
    threads = [{"id": "a", "isResolved": True}, {"id": "b", "isResolved": False}]
    d = decide(review_threads=threads)
    assert_decision(d, "NOT_ELIGIBLE", "unresolved_thread")
    assert "1" in d.detail
    overseer_thread = [{"id": "o", "isResolved": False, "comments": {"nodes": []}}]
    assert_decision(decide(review_threads=overseer_thread), "NOT_ELIGIBLE", "unresolved_thread")


def _failure_audit(head=HEAD, at="2026-10-30T05:43:00Z") -> dict:
    return {"event": am.EVENT_FAILED, "pr": 2211, "head_sha": head, "timestamp": at}


def _failure_comment(body: str, login=OVERSEER, kind="Bot") -> dict:
    return comment(login, body, "2026-10-30T05:43:30Z", kind)


def _unlabel(actor: str, at: str, kind="User") -> dict:
    return {
        "id": 40000000000,
        "event": "unlabeled",
        "label": {"name": "needs-human"},
        "actor": {"login": actor, "type": kind},
        "created_at": at,
    }


def test_r12_failure_evidence_in_audit():
    assert_decision(decide(audit_events=[_failure_audit()]), "NOT_ELIGIBLE", "merge_failed_on_head")
    assert_decision(
        decide(audit_events=[_failure_audit(head=OTHER_HEAD)]),
        "MERGE",
        "approved_by_designated_human",
    )


def test_r12_failure_marker_comment():
    marker = am.render_failure_marker(HEAD)
    body = f"text\n\n{marker}\n"
    assert_decision(
        decide(issue_comments=[_failure_comment(body)]),
        "NOT_ELIGIBLE",
        "merge_failed_on_head",
    )
    human = _failure_comment(body, login="bob", kind="User")
    assert_decision(decide(issue_comments=[human]), "MERGE", "approved_by_designated_human")


def test_r12_marker_matching_is_permissive():
    marker = am.render_failure_marker(HEAD)
    crlf = _failure_comment(f"x\r\n{marker}\r\n")
    assert_decision(decide(issue_comments=[crlf]), "NOT_ELIGIBLE", "merge_failed_on_head")
    twice = _failure_comment(f"{marker}\nmore\n{marker}\n")
    assert_decision(decide(issue_comments=[twice]), "NOT_ELIGIBLE", "merge_failed_on_head")


def test_r12_reset_by_designated_human_unlabel():
    events = make_events() + [_unlabel(HUMAN, "2026-10-30T05:43:50Z")]
    assert_decision(
        decide(audit_events=[_failure_audit()], issue_events=events),
        "MERGE",
        "approved_by_designated_human",
    )
    by_overseer = make_events() + [_unlabel(OVERSEER, "2026-10-30T05:43:50Z", kind="Bot")]
    assert_decision(
        decide(audit_events=[_failure_audit()], issue_events=by_overseer),
        "NOT_ELIGIBLE",
        "merge_failed_on_head",
    )
    before = make_events() + [_unlabel(HUMAN, "2026-10-30T05:42:00Z")]
    assert_decision(
        decide(audit_events=[_failure_audit()], issue_events=before),
        "NOT_ELIGIBLE",
        "merge_failed_on_head",
    )


def test_r12_unparseable_reset_timestamp():
    events = make_events() + [_unlabel(HUMAN, "garbage")]
    assert_decision(
        decide(audit_events=[_failure_audit()], issue_events=events),
        "UNDETERMINABLE",
        "timestamp:failure_evidence",
    )


def _with_run(**overrides):
    return tuple(make_check_runs(**overrides))


def test_r13_pending_then_stalled():
    runs = _with_run(tests=("in_progress", None))
    soon = datetime(2026, 10, 30, 5, 49, 47, tzinfo=timezone.utc)
    d = decide(check_runs=runs, now=soon)
    assert_decision(d, "DEFER", "checks_pending")
    late = datetime(2026, 10, 30, 7, 40, 47, tzinfo=timezone.utc)
    assert_decision(decide(check_runs=runs, now=late), "NOT_ELIGIBLE", "checks_stalled")


def test_r13_failed_and_neutral():
    assert_decision(
        decide(check_runs=_with_run(tests=("completed", "failure"))),
        "NOT_ELIGIBLE",
        "check_not_success",
    )
    assert_decision(
        decide(check_runs=_with_run(tests=("completed", "neutral"))),
        "NOT_ELIGIBLE",
        "check_not_success",
    )


def test_r13_agent_static_check_absent_defers():
    runs = tuple(r for r in make_check_runs() if r["name"] != am.AGENT_STATIC_CHECK)
    assert_decision(decide(check_runs=runs), "DEFER", "checks_pending")


def test_r13_newer_success_supersedes_older_failure():
    older = {"id": 1, "name": "tests", "status": "completed", "conclusion": "failure"}
    runs = (older,) + tuple(make_check_runs())
    assert_decision(decide(check_runs=runs), "MERGE", "approved_by_designated_human")


def test_r13_failure_takes_precedence_over_pending():
    runs = _with_run(tests=("completed", "failure"), **{"oversight-gate-lint": ("queued", None)})
    assert_decision(decide(check_runs=runs), "NOT_ELIGIBLE", "check_not_success")


def test_r13_no_required_contexts_is_undeterminable():
    gate = make_gate(required_contexts=())
    assert_decision(decide(gate=gate), "UNDETERMINABLE", "required_contexts_unavailable")


@pytest.mark.parametrize("state", ["dirty", "behind", "blocked", "unstable"])
def test_r14_blocking_states(state):
    d = decide(pull=make_pull(mergeable_state=state))
    assert_decision(d, "NOT_ELIGIBLE", f"mergeable_{state}")


def test_r14_other_and_unknown():
    assert_decision(
        decide(pull=make_pull(mergeable_state="weird")), "NOT_ELIGIBLE", "mergeable_other"
    )
    for value in ("unknown", None):
        d = decide(pull=make_pull(mergeable_state=value))
        assert_decision(d, "DEFER", "mergeable_unknown")


def test_r15_gate_failed_carries_reason():
    gate = make_gate(autonomous_capable=False, reason="ruleset bypassable")
    d = decide(gate=gate)
    assert_decision(d, "NOT_ELIGIBLE", "gate_failed")
    assert d.detail == "ruleset bypassable"


def test_missing_field_is_undeterminable():
    assert_decision(decide(reviews=None), "UNDETERMINABLE", "missing:reviews")


def test_decide_is_pure(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("decide performed I/O")

    for name in ("get_pull", "get_repo", "list_pull_reviews", "list_issue_comments", "_run_gh"):
        monkeypatch.setattr(github, name, boom)
    monkeypatch.setattr(merge_authority, "verify_merge_gate_live", boom)
    assert_decision(decide(), "MERGE", "approved_by_designated_human")


def test_first_failing_rule_wins():
    pull = make_pull(labels=[{"name": "needs-human"}, {"name": "hos-halt"}])
    d = decide(pull=pull, review_threads=[{"id": "x", "isResolved": False}])
    assert_decision(d, "NOT_ELIGIBLE", "hos_halt")


def test_invalid_head_sha():
    assert_decision(
        decide(pull=make_pull(head={"sha": "xyz"})), "UNDETERMINABLE", "head_sha_invalid"
    )


def test_early_stop_snapshot_decides_not_open():
    stopped = am.ApprovalMergeSnapshot(
        pr_number=2211, pull=make_pull(state="closed", merged=True), now=NOW
    )
    assert_decision(
        am.decide_merge_on_human_approval(stopped, CONFIG), "NOT_ELIGIBLE", "not_open_pr"
    )


def test_failure_marker_writer_validates_sha():
    with pytest.raises(ValueError):
        am.render_failure_marker("short")
    assert am.FAILURE_MARKER_RE.search(am.render_failure_marker(HEAD)).group(1) == HEAD


def test_decision_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        decide().reason = "x"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# 7.3 — the live gate
# --------------------------------------------------------------------------- #

RULESET_ID = 18044233


def gate_rules(
    contexts=REQUIRED_CONTEXTS,
    count=1,
    dismiss=True,
    ruleset_id=RULESET_ID,
    with_pr_rule=True,
) -> list[dict]:
    rules = [
        {"type": "deletion", "ruleset_id": ruleset_id},
        {"type": "non_fast_forward", "ruleset_id": ruleset_id},
        {
            "type": "required_status_checks",
            "ruleset_id": ruleset_id,
            "parameters": {"required_status_checks": [{"context": c} for c in contexts]},
        },
    ]
    if with_pr_rule:
        rules.append(
            {
                "type": "pull_request",
                "ruleset_id": ruleset_id,
                "parameters": {
                    "required_approving_review_count": count,
                    "dismiss_stale_reviews_on_push": dismiss,
                    "required_review_thread_resolution": True,
                    "allowed_merge_methods": ["squash"],
                },
            }
        )
    return rules


def good_ruleset(**overrides) -> dict:
    value = {"id": RULESET_ID, "enforcement": "active", "current_user_can_bypass": "never"}
    value.update(overrides)
    return value


@pytest.fixture
def gate_env(monkeypatch):
    state = {"rules": gate_rules(), "rulesets": {RULESET_ID: good_ruleset()}}

    def list_rules(owner, repo, branch):
        if isinstance(state["rules"], Exception):
            raise state["rules"]
        return state["rules"]

    def get_ruleset(owner, repo, rid):
        value = state["rulesets"].get(rid)
        if isinstance(value, Exception):
            raise value
        return value

    def no_classic(*a, **k):
        raise AssertionError("classic branch protection must not be consulted")

    monkeypatch.setattr(merge_authority, "list_branch_rules", list_rules)
    monkeypatch.setattr(merge_authority, "get_ruleset", get_ruleset)
    monkeypatch.setattr(merge_authority, "get_branch_protection", no_classic)
    return state


def verify(name="require-tier-ceiling"):
    return merge_authority.verify_merge_gate_live("o", "r", "main", tier_ceiling_check_name=name)


def test_gate_1_passes_on_the_live_shape(gate_env):
    result = verify()
    assert result.autonomous_capable is True, result.reason
    assert result.required_contexts == REQUIRED_CONTEXTS
    assert result.ruleset_ids == (RULESET_ID,)
    assert result.evidence[RULESET_ID]["current_user_can_bypass"] == "never"
    assert isinstance(result, merge_authority.GateDetectionResult)


def _gate_fails(reason_part: str):
    result = verify()
    assert result.autonomous_capable is False
    assert reason_part in result.reason, result.reason


def test_gate_2_missing_meta_context(gate_env):
    gate_env["rules"] = gate_rules(
        contexts=[c for c in REQUIRED_CONTEXTS if c != "require-overseer-approval"]
    )
    _gate_fails("required context missing: require-overseer-approval")


def test_gate_2_custom_ceiling_name(gate_env):
    result = verify("custom-ceiling")
    assert result.autonomous_capable is False
    assert "required context missing: custom-ceiling" in result.reason


@pytest.mark.parametrize(
    "kwargs",
    [
        {"with_pr_rule": False},
        {"count": 0},
        {"count": True},
        {"dismiss": False},
    ],
)
def test_gate_2_pull_request_rule_defects(gate_env, kwargs):
    gate_env["rules"] = gate_rules(**kwargs)
    _gate_fails("no pull_request rule")


@pytest.mark.parametrize(
    "ruleset",
    [
        good_ruleset(current_user_can_bypass="always"),
        good_ruleset(current_user_can_bypass="pull_requests_only"),
        {"id": RULESET_ID, "enforcement": "active"},
        good_ruleset(enforcement="evaluate"),
        None,
    ],
)
def test_gate_2_bypassable_or_unverifiable_ruleset(gate_env, ruleset):
    gate_env["rulesets"] = {RULESET_ID: ruleset}
    _gate_fails("ruleset bypassable or unverifiable")


def test_gate_2_ruleset_read_error(gate_env):
    gate_env["rulesets"] = {RULESET_ID: github.GitHubError("boom", 403)}
    result = verify()
    assert result.autonomous_capable is False
    assert "ruleset bypassable or unverifiable" in result.reason
    assert "boom" in str(result.evidence[RULESET_ID])


def test_gate_2_rules_read_error(gate_env):
    gate_env["rules"] = github.GitHubError("down", 500)
    _gate_fails("rules read failed")


def test_gate_2_missing_ruleset_id(gate_env):
    gate_env["rules"] = gate_rules(ruleset_id=None)
    _gate_fails("ruleset bypassable or unverifiable")


def test_gate_3_unrelated_bypassable_ruleset_is_not_consulted(gate_env):
    extra = {
        "type": "required_status_checks",
        "ruleset_id": 2,
        "parameters": {"required_status_checks": [{"context": "lint"}]},
    }
    gate_env["rules"] = gate_rules() + [extra]
    gate_env["rulesets"][2] = good_ruleset(current_user_can_bypass="always")
    assert verify().autonomous_capable is True


def test_gate_3_only_supplier_bypassable_fails(gate_env):
    rules = gate_rules(contexts=[c for c in REQUIRED_CONTEXTS if c != "require-human-approval"])
    rules.append(
        {
            "type": "required_status_checks",
            "ruleset_id": 2,
            "parameters": {"required_status_checks": [{"context": "require-human-approval"}]},
        }
    )
    gate_env["rules"] = rules
    gate_env["rulesets"][2] = good_ruleset(current_user_can_bypass="always")
    _gate_fails("require-human-approval")


def test_gate_4_never_calls_classic_protection(gate_env):
    # gate_env patches get_branch_protection to raise; a pass proves it was not called.
    assert verify().autonomous_capable is True


def test_gate_5_general_gate_stub_is_unchanged():
    result = merge_authority.detect_server_side_gate("o", "r")
    assert result is merge_authority._PROPOSE_ONLY_DEP
    assert result.reason.startswith("DEP[#152-followup]: risk-tier-vs-ceiling status check")


# --------------------------------------------------------------------------- #
# 7.3 — provenance
# --------------------------------------------------------------------------- #


def _authorized(head=HEAD) -> dict:
    return {"event": am.EVENT_AUTHORIZED, "pr": 2211, "head_sha": head}


def test_prov_1_authorized_then_completed():
    first = am.classify_bot_merge(2211, HEAD, OVERSEER, [_authorized()], OVERSEER)
    assert first.classification is am.BotMergeClass.AUTHORIZED_ON_HUMAN_APPROVAL
    assert first.completion_record_present is False
    merged = {"event": am.EVENT_MERGED, "pr": 2211, "head_sha": HEAD}
    second = am.classify_bot_merge(2211, HEAD, OVERSEER, [_authorized(), merged], OVERSEER)
    assert second.completion_record_present is True
    assert second.authorized_record == _authorized()


def test_prov_2_unauthorized_bot_merges():
    for merged_by, events in ((WORKER, [_authorized()]), (OVERSEER, [])):
        result = am.classify_bot_merge(2211, HEAD, merged_by, events, OVERSEER)
        assert result.classification is am.BotMergeClass.UNAUTHORIZED


def test_prov_3_wrong_head_or_human_merger():
    other = am.classify_bot_merge(2211, HEAD, OVERSEER, [_authorized(OTHER_HEAD)], OVERSEER)
    assert other.classification is am.BotMergeClass.UNAUTHORIZED
    human = am.classify_bot_merge(2211, HEAD, HUMAN, [_authorized()], OVERSEER)
    assert human.classification is am.BotMergeClass.UNAUTHORIZED
