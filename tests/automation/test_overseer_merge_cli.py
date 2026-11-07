"""Tests for the mutating merge CLI, its read-only twin, the new github.py
readers and the L3 wrapper (#2213 slice S1a, TD-2213 §7.4-§7.6).

The GitHub layer is faked at the `github.<fn>` seam; audit writes go to a tmp
repo root. Nothing here touches the network.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.automation.merge_authority_cli as twin
import scripts.automation.overseer_merge_cli as cli
from scripts.automation.lib import approval_merge as am
from scripts.automation.lib import github, merge_authority, merge_config
from scripts.oversight.lib import audit_log
from tests.automation.test_approval_merge import (
    HEAD,
    HUMAN,
    OTHER_HEAD,
    OVERSEER,
    WORKER,
    make_check_runs,
    make_events,
    make_gate,
    make_pull,
    make_reviews,
)
from tests.automation.test_merge_authority_cli import _ENVELOPE_KEYS, _write_config

REPO_ROOT = Path(__file__).resolve().parents[2]
ARGV = ["on-human-approval", "--app", "overseer", "--pr", "2211"]
WRITE_FNS = ("merge_pull", "post_comment", "add_issue_label", "remove_issue_label")


class World:
    """The faked GitHub state plus an ordered log of every call."""

    def __init__(self, root: Path):
        self.root = root
        self.calls: list[tuple] = []
        self.pulls = [make_pull()]
        self.files = [{"filename": f"f{i}.py"} for i in range(3)]
        self.reviews = make_reviews()
        self.comments: list[dict] = []
        self.events = make_events()
        self.threads = [{"id": f"t{i}", "isResolved": True} for i in range(8)]
        self.runs = make_check_runs()
        self.events_exc: Exception | None = None
        self.merge_exc: Exception | None = None
        self.merge_response: dict = {"merged": True, "sha": "c" * 40}
        self.fail_audit: set[str] = set()
        self.remove_label_exc: Exception | None = None

    # -- helpers -------------------------------------------------------------

    @property
    def writes(self) -> list[tuple]:
        return [c for c in self.calls if c[0] in WRITE_FNS or c[0] == "write_event"]

    def write_names(self) -> list[str]:
        return [c[1]["event"] if c[0] == "write_event" else c[0] for c in self.writes]

    def reads(self) -> list[str]:
        return [c[0] for c in self.calls if c[0] not in WRITE_FNS and c[0] != "write_event"]

    def event_dict(self, name: str) -> dict:
        return next(c[1] for c in self.calls if c[0] == "write_event" and c[1]["event"] == name)

    def audit_records(self) -> list[dict]:
        return [json.loads(b) for b in audit_log.read_stream(str(self.root))]

    # -- install -------------------------------------------------------------

    def install(self, monkeypatch) -> "World":
        w = self

        def rec(name):
            def deco(fn):
                def wrapper(*a, **k):
                    w.calls.append((name,) + a)
                    return fn(*a, **k)

                monkeypatch.setattr(github, name, wrapper)
                return fn

            return deco

        @rec("get_pull")
        def _get_pull(o, r, n):
            return w.pulls.pop(0) if len(w.pulls) > 1 else w.pulls[0]

        rec("get_repo")(lambda o, r: {"default_branch": "main"})
        rec("list_pull_files")(lambda o, r, n: w.files)
        rec("list_pull_reviews")(lambda o, r, n: w.reviews)
        rec("list_issue_comments")(lambda o, r, n, **k: w.comments)

        @rec("list_issue_events")
        def _events(o, r, n):
            if w.events_exc:
                raise w.events_exc
            return w.events

        rec("list_review_threads")(lambda o, r, n: w.threads)
        rec("get_commit")(
            lambda o, r, ref: {"commit": {"committer": {"date": "2026-10-29T16:48:44Z"}}}
        )
        rec("list_check_runs_for_ref")(lambda o, r, ref: w.runs)
        rec("get_file_text")(lambda o, r, path, ref: "* @ScottThurlow\n")

        @rec("merge_pull")
        def _merge(o, r, n, sha):
            if w.merge_exc:
                raise w.merge_exc
            return w.merge_response

        @rec("post_comment")
        def _post(o, r, n, body, **k):
            w.comments.append(
                {
                    "user": {"login": OVERSEER, "type": "Bot"},
                    "body": body,
                    "created_at": "2026-10-30T06:00:00Z",
                }
            )
            return {"id": 1, "html_url": "https://example.test/c/1"}

        rec("add_issue_label")(lambda o, r, n, label: None)

        @rec("remove_issue_label")
        def _remove(o, r, n, label):
            if w.remove_label_exc:
                raise w.remove_label_exc

        monkeypatch.setattr(merge_authority, "verify_merge_gate_live", lambda *a, **k: make_gate())
        monkeypatch.setattr(merge_config, "resolve_repo_slug", lambda root, explicit=None: "o/r")

        real_write = audit_log.write_event

        def write_event(event, *, root=".", ts=None):
            w.calls.append(("write_event", event))
            if event["event"] in w.fail_audit:
                raise RuntimeError("disk full")
            return real_write(event, root=root, ts=ts)

        monkeypatch.setattr(audit_log, "write_event", write_event)
        return self


@pytest.fixture
def world(tmp_path, monkeypatch) -> World:
    root = tmp_path / "repo"
    _write_config(root)
    monkeypatch.setenv("HOS_BOT_LOGIN", OVERSEER)
    monkeypatch.delenv("HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED", raising=False)
    monkeypatch.setenv("HOS_OVERSEER_MERGE_TOKEN_MINTED", "1")
    monkeypatch.delenv("HOS_CYCLE_ID", raising=False)
    return World(root).install(monkeypatch)


def run(world: World, capsys, argv=None, **kwargs) -> tuple[int, dict]:
    rc = cli.main(argv or ARGV, repo_root=world.root, sleep=lambda s: None, **kwargs)
    out = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(out) == 1, f"expected exactly one stdout line, got: {out!r}"
    return rc, json.loads(out[0])


# --------------------------------------------------------------------------- #
# identity (R1) and argv
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("app", ["worker", "human"])
def test_cli_id_1_2_other_apps_refused_before_any_call(world, capsys, app):
    rc, rec = run(world, capsys, ["on-human-approval", "--app", app, "--pr", "2211"])
    assert rc == 3
    assert rec["refused"] is True and rec["refusal_reason"] == "overseer_identity_required"
    assert world.calls == []


def test_cli_id_3_login_mismatch(world, capsys, monkeypatch):
    monkeypatch.setenv("HOS_BOT_LOGIN", WORKER)
    rc, rec = run(world, capsys)
    assert rc == 3 and rec["refusal_reason"] == "overseer_identity_mismatch"
    assert world.calls == []


def test_cli_id_4_login_unset_and_mint_failed(world, capsys, monkeypatch):
    monkeypatch.delenv("HOS_BOT_LOGIN")
    rc, rec = run(world, capsys)
    assert rc == 1 and "HOS_BOT_LOGIN" in rec["error"]
    monkeypatch.setenv("HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED", "1")
    rc, rec = run(world, capsys)
    assert rc == 1 and "mint" in rec["error"]
    assert world.calls == []


def test_cli_id_6_missing_minted_sentinel_refuses_before_any_call(world, capsys, monkeypatch):
    monkeypatch.delenv("HOS_OVERSEER_MERGE_TOKEN_MINTED")
    rc, rec = run(world, capsys)
    assert rc == 3 and rec["refusal_reason"] == "overseer_token_not_minted"
    assert world.calls == []


def test_cli_id_5_mint_failure_never_falls_back_to_ambient_login(world, capsys, monkeypatch):
    monkeypatch.setenv("HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED", "1")
    monkeypatch.setenv("HOS_BOT_LOGIN", OVERSEER)
    rc, rec = run(world, capsys)
    assert rc == 1 and "mint" in rec["error"]
    assert world.calls == []


@pytest.mark.parametrize(
    "argv",
    [
        ARGV + ["--repo", "o/r"],
        ARGV + ["--force"],
        ARGV + ["--head-sha", "x"],
        ARGV + ["--skip-gate"],
        ["on-human-approval", "--app", "overseer"],
        ["on-human-approval", "--app", "overseer", "--pr", "abc"],
        ["merge-now", "--app", "overseer", "--pr", "1"],
        ["on-human-approval", "--ap", "overseer", "--pr", "2211"],
        ["on-human-approval", "--a=overseer", "--pr", "2211"],
        ["on-human-approval", "--app", "overseer", "--p", "2211"],
    ],
)
def test_cli_argv_1_usage_errors(world, capsys, argv):
    rc, rec = run(world, capsys, argv)
    assert rc == 2 and rec["error"].startswith("usage:")
    assert world.calls == []


def test_envelope_keys(world, capsys):
    rc, rec = run(world, capsys)
    assert _ENVELOPE_KEYS.issubset(rec)
    assert rec["subcommand"] == "on-human-approval" and rec["repo"] == "o/r" and rec["pr"] == 2211


# --------------------------------------------------------------------------- #
# the merge path
# --------------------------------------------------------------------------- #


def test_cli_merge_1_ordered_writes(world, capsys, monkeypatch):
    monkeypatch.setenv("HOS_CYCLE_ID", "cycle-9")
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED", rec
    assert world.write_names() == [
        am.EVENT_AUTHORIZED,
        "merge_pull",
        "remove_issue_label",
        am.EVENT_MERGED,
    ]
    assert world.writes[1] == ("merge_pull", "o", "r", 2211, HEAD)
    assert world.writes[2] == ("remove_issue_label", "o", "r", 2211, "needs-human")
    authorized = world.event_dict(am.EVENT_AUTHORIZED)
    assert authorized["approver"] == HUMAN
    assert authorized["approving_review_id"] == 5708492480
    assert authorized["overseer_verdict_id"] == 5702138899
    assert authorized["verdict_kind"] == "marker:HUMAN_REQUIRED"
    assert authorized["head_sha"] == HEAD and authorized["actor"] == OVERSEER
    assert authorized["cycle_id"] == "cycle-9"
    assert authorized["label_provenance"]["labeled_event_id"] == 34614334737
    assert authorized["gate"]["ruleset_ids"] == [18044233]
    assert rec["merge_commit_sha"] == "c" * 40
    assert rec["label_removed"] is True and rec["authorized_record_reused"] is False
    assert all(rec["audit_records"][k] for k in ("authorized", "merged"))
    merged = world.event_dict(am.EVENT_MERGED)
    assert merged["authorized_record"] == rec["audit_records"]["authorized"]
    assert merged["recovered"] is False
    assert merged["overseer_verdict_id"] == 5702138899


def test_cli_merge_without_needs_human_skips_label_removal(world, capsys):
    world.pulls = [make_pull(labels=[])]
    world.events = []
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED" and rec["label_removed"] is False
    assert "remove_issue_label" not in world.write_names()


def test_cli_409_definite_failure_then_blocked_rerun(world, capsys):
    world.merge_exc = github.GitHubError("Head branch was modified", 409)
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_FAILED" and rec["http_status"] == 409
    assert world.write_names() == [
        am.EVENT_AUTHORIZED,
        "merge_pull",
        am.EVENT_FAILED,
        "post_comment",
    ]
    body = world.writes[3][4]
    assert am.render_failure_marker(HEAD) in body and "**OTHER**" in body
    assert ".sh" not in body and ".py" not in body
    assert rec["failure_comment_url"] == "https://example.test/c/1"
    assert rec["label_added"] is False

    world.calls.clear()
    world.merge_exc = None
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "NOT_ELIGIBLE"
    assert rec["decision"]["reason"] == "merge_failed_on_head"
    assert world.writes == []


def test_cli_409b_adds_label_when_absent(world, capsys):
    world.pulls = [make_pull(labels=[])]
    world.events = []
    world.merge_exc = github.GitHubError("conflict", 409)
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["label_added"] is True
    assert world.write_names().count("add_issue_label") == 1


def test_cli_409c_failed_audit_write_still_blocked_by_comment_marker(world, capsys):
    world.merge_exc = github.GitHubError("conflict", 409)
    world.fail_audit = {am.EVENT_FAILED}
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_FAILED"
    assert any("failed audit record not written" in n for n in rec["not_verified"])
    assert "post_comment" in world.write_names()
    # drop every audit record: only the GitHub-side marker remains
    for path in (world.root / "audit").rglob("*.json"):
        path.unlink()
    world.calls.clear()
    world.merge_exc = None
    rc, rec = run(world, capsys)
    assert rec["decision"]["reason"] == "merge_failed_on_head"
    assert "merge_pull" not in world.write_names()


def test_cli_403_is_definite(world, capsys):
    world.merge_exc = github.RateLimitError("rate limit", 403)
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_FAILED" and rec["http_status"] == 403
    assert am.EVENT_FAILED in world.write_names()


def test_cli_401_is_not_definite(world, capsys):
    world.merge_exc = github.GitHubError("auth", 401)
    world.pulls = [make_pull(), make_pull()]
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_UNCONFIRMED"
    assert world.write_names() == [am.EVENT_AUTHORIZED, "merge_pull"]
    world.calls.clear()
    world.merge_exc = None
    world.pulls = [make_pull()]
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED"


def test_cli_wa_1_write_ahead_failure_blocks_merge(world, capsys):
    world.fail_audit = {am.EVENT_AUTHORIZED}
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] is None and "write-ahead audit failed" in rec["error"]
    assert "merge_pull" not in world.write_names()


def _seed_authorized(world: World, **overrides) -> None:
    event = {
        "event": am.EVENT_AUTHORIZED,
        "repo": "o/r",
        "pr": 2211,
        "head_sha": HEAD,
        "timestamp": "2026-10-30T05:45:00Z",
        "approving_review_id": 5708492480,
        "overseer_verdict_id": 5702138899,
    }
    event.update(overrides)
    audit_log.write_event(event, root=str(world.root))
    world.calls.clear()


def test_cli_wa_2_existing_matching_record_is_reused(world, capsys):
    _seed_authorized(world)
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED"
    assert rec["authorized_record_reused"] is True and rec["audit_records"]["authorized"]
    assert am.EVENT_AUTHORIZED not in world.write_names()


def test_cli_wa_3_record_for_a_different_approval_is_not_reused(world, capsys):
    _seed_authorized(world, approving_review_id=1)
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["authorized_record_reused"] is False
    assert world.write_names()[0] == am.EVENT_AUTHORIZED


def test_cli_post_1_completion_record_failure_is_best_effort(world, capsys):
    world.fail_audit = {am.EVENT_MERGED}
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED"
    assert rec["audit_records"]["merged"] is None and rec["not_verified"]


def test_cli_post_2_label_removal_failure_is_best_effort(world, capsys):
    world.remove_label_exc = github.GitHubError("nope", 500)
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["label_removed"] is False and rec["not_verified"]
    assert am.EVENT_MERGED in world.write_names()


def test_cli_amb_1_ambiguous_but_merged_is_recovered(world, capsys):
    world.merge_exc = github.GitHubError("timed out", None)
    merged = make_pull(merged=True, state="closed", merge_commit_sha="d" * 40)
    world.pulls = [make_pull(), make_pull(), merged]
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED" and rec["recovered"] is True
    assert rec["merge_commit_sha"] == "d" * 40
    assert world.event_dict(am.EVENT_MERGED)["recovered"] is True


def test_cli_amb_2_ambiguous_and_unmerged_records_nothing(world, capsys):
    world.merge_exc = github.GitHubError("server error", 502)
    world.pulls = [make_pull(), make_pull()]
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_UNCONFIRMED"
    assert world.write_names() == [am.EVENT_AUTHORIZED, "merge_pull"]


def test_cli_amb_reread_for_other_head_is_not_recovery(world, capsys):
    world.merge_exc = github.GitHubError("timed out", None)
    moved = make_pull(merged=True, head={"sha": OTHER_HEAD}, merge_commit_sha="d" * 40)
    world.pulls = [make_pull(), make_pull(), moved]
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_UNCONFIRMED"


def test_cli_empty_2xx_body_is_ambiguous_not_a_failure(world, capsys):
    world.merge_exc = github.GitHubError("merge_pull: GitHub returned no response for PUT")
    world.pulls = [make_pull(), make_pull()]
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_UNCONFIRMED"
    assert rec["http_status"] is None and rec["label_added"] is False
    assert world.write_names() == [am.EVENT_AUTHORIZED, "merge_pull"]


@pytest.mark.parametrize(
    "changed",
    [
        {"base": {"ref": "release"}},
        {"head": {"sha": OTHER_HEAD}},
        {"state": "closed"},
        {"draft": True},
        {"labels": [{"name": "needs-human"}, {"name": "hos-halt"}]},
    ],
)
def test_cli_preflight_state_change_aborts_without_merge(world, capsys, changed):
    world.pulls = [make_pull(), make_pull(**changed)]
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_ABORTED_STATE_CHANGED"
    assert world.write_names() == [am.EVENT_AUTHORIZED]
    assert rec["label_added"] is False and rec["failure_comment_url"] is None
    assert any("aborted before the PUT" in n for n in rec["not_verified"])


def test_cli_preflight_missing_draft_key_aborts(world, capsys):
    no_draft = make_pull()
    del no_draft["draft"]
    world.pulls = [make_pull(), no_draft]
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_ABORTED_STATE_CHANGED"
    assert "merge_pull" not in world.write_names()


def _after_write_ahead(world, monkeypatch, name, fn):
    """Make github.<name> answer differently once the write-ahead record exists."""
    real = getattr(github, name)

    def wrapped(o, r, n):
        if world.write_names():
            return fn(real(o, r, n))
        return real(o, r, n)

    monkeypatch.setattr(github, name, wrapped)


def _assert_activity_abort(world, capsys):
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_ABORTED_STATE_CHANGED"
    assert world.write_names() == [am.EVENT_AUTHORIZED]
    assert rec["label_added"] is False and rec["failure_comment_url"] is None


def test_cli_preflight_new_comment_aborts(world, capsys, monkeypatch):
    new = {"id": 999, "user": {"login": "ScottThurlow", "type": "User"}, "body": "hold"}
    _after_write_ahead(world, monkeypatch, "list_issue_comments", lambda c: c + [new])
    _assert_activity_abort(world, capsys)


def test_cli_preflight_new_review_aborts(world, capsys, monkeypatch):
    new = {"id": 999, "user": {"login": "ScottThurlow"}, "state": "CHANGES_REQUESTED"}
    _after_write_ahead(world, monkeypatch, "list_pull_reviews", lambda r: r + [new])
    _assert_activity_abort(world, capsys)


def test_cli_preflight_review_dismissed_aborts(world, capsys, monkeypatch):
    def dismiss(reviews):
        return [dict(r, state="DISMISSED") if r["state"] == "APPROVED" else r for r in reviews]

    _after_write_ahead(world, monkeypatch, "list_pull_reviews", dismiss)
    _assert_activity_abort(world, capsys)


@pytest.mark.parametrize("name", ["list_pull_reviews", "list_issue_comments"])
def test_cli_preflight_activity_read_failure_aborts(world, capsys, monkeypatch, name):
    def boom(_):
        raise github.GitHubError("boom", 502)

    _after_write_ahead(world, monkeypatch, name, boom)
    _assert_activity_abort(world, capsys)


def test_cli_preflight_edited_comment_aborts(world, capsys, monkeypatch):
    world.comments = [_comment(updated_at="2026-10-30T05:00:00Z")]
    _after_write_ahead(
        world,
        monkeypatch,
        "list_issue_comments",
        lambda c: [dict(x, updated_at="2026-10-30T05:59:00Z", body="HOLD") for x in c],
    )
    _assert_activity_abort(world, capsys)


def test_cli_preflight_edited_review_body_aborts(world, capsys, monkeypatch):
    def edit(reviews):
        return [dict(r, body="HOLD") if r["state"] == "APPROVED" else r for r in reviews]

    _after_write_ahead(world, monkeypatch, "list_pull_reviews", edit)
    _assert_activity_abort(world, capsys)


def test_cli_preflight_comment_missing_updated_at_aborts(world, capsys, monkeypatch):
    world.comments = [_comment(updated_at="2026-10-30T05:00:00Z")]
    _after_write_ahead(
        world,
        monkeypatch,
        "list_issue_comments",
        lambda c: [{k: v for k, v in x.items() if k != "updated_at"} for x in c],
    )
    _assert_activity_abort(world, capsys)


def _comment(**over) -> dict:
    base = {"id": 77, "user": {"login": "someone", "type": "User"}, "body": "hi"}
    base.update(over)
    return base


def test_cli_preflight_no_new_activity_merges(world, capsys, monkeypatch):
    world.comments = [
        _comment(updated_at="2026-10-30T05:00:00Z", created_at="2026-10-30T05:00:00Z")
    ]
    _after_write_ahead(world, monkeypatch, "list_issue_comments", lambda c: list(c))
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED"


def test_cli_preflight_new_needs_human_aborts(world, capsys):
    world.pulls = [make_pull(labels=[]), make_pull(labels=[{"name": "needs-human"}])]
    world.events = []
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_ABORTED_STATE_CHANGED"
    assert "merge_pull" not in world.write_names()


def test_cli_preflight_read_failure_aborts(world, capsys, monkeypatch):
    real = github.get_pull

    def flaky(o, r, n):
        if world.write_names() == [am.EVENT_AUTHORIZED]:
            raise github.GitHubError("boom", 502)
        return real(o, r, n)

    monkeypatch.setattr(github, "get_pull", flaky)
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_ABORTED_STATE_CHANGED"
    assert "merge_pull" not in world.write_names()


def test_cli_post_merge_base_mismatch_is_recorded_and_escalated(world, capsys):
    world.pulls = [make_pull(), make_pull(), make_pull(base={"ref": "release"}, merged=True)]
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGED_BASE_MISMATCH"
    assert rec["label_added"] is True and rec["failure_comment_url"]
    assert am.EVENT_BASE_MISMATCH in world.write_names()
    mismatch = world.event_dict(am.EVENT_BASE_MISMATCH)
    assert mismatch["merged_base_ref"] == "release" and mismatch["expected_base_ref"] == "main"


def test_cli_post_merge_null_base_is_noted_not_fatal(world, capsys):
    world.pulls = [make_pull(), make_pull(), make_pull(base=None, merged=True)]
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED"
    assert any("base.ref unreadable" in n for n in rec["not_verified"])
    assert am.EVENT_BASE_MISMATCH not in world.write_names()


def test_cli_post_merge_base_check_read_failure_is_noted_not_fatal(world, capsys, monkeypatch):
    real = github.get_pull

    def flaky(o, r, n):
        if "merge_pull" in world.write_names():
            raise github.GitHubError("boom", 502)
        return real(o, r, n)

    monkeypatch.setattr(github, "get_pull", flaky)
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED"
    assert any("post-merge base check not run" in n for n in rec["not_verified"])


def test_cli_response_without_merged_true_is_a_failure(world, capsys):
    world.merge_response = {"merged": False, "message": "no"}
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["outcome"] == "MERGE_FAILED" and rec["http_status"] == 200


# --------------------------------------------------------------------------- #
# no-write outcomes, idempotency, polling, completeness, scrubbing
# --------------------------------------------------------------------------- #


def test_cli_nowrite_defer_not_eligible_undeterminable(world, capsys):
    recent = datetime.now(timezone.utc) - timedelta(minutes=10)
    world.reviews[2]["submitted_at"] = recent.strftime("%Y-%m-%dT%H:%M:%SZ")
    world.runs = make_check_runs(tests=("in_progress", None))
    rc, rec = run(world, capsys)
    assert (rc, rec["outcome"]) == (0, "DEFER") and world.writes == []

    world.runs = make_check_runs()
    world.reviews = [r for r in make_reviews() if r["state"] != "APPROVED"]
    rc, rec = run(world, capsys)
    assert (rc, rec["outcome"]) == (0, "NOT_ELIGIBLE") and world.writes == []

    world.reviews = make_reviews()
    world.events_exc = github.GitHubError("down", 500)
    rc, rec = run(world, capsys)
    assert (rc, rec["outcome"]) == (0, "UNDETERMINABLE")
    assert rec["decision"]["reason"] == "read:events" and world.writes == []


def test_cli_idem_1_closed_pr_costs_one_read(world, capsys):
    world.pulls = [make_pull(state="closed", merged=True)]
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["decision"]["reason"] == "not_open_pr"
    assert world.reads() == ["get_pull"] and world.writes == []


def test_cli_idem_2_unapproved_reruns_write_nothing(world, capsys):
    world.reviews = [r for r in make_reviews() if r["state"] != "APPROVED"]
    for _ in range(2):
        rc, rec = run(world, capsys)
        assert rc == 0 and rec["decision"]["reason"] == "no_eligible_approval"
    assert world.writes == []


def test_cli_poll_unknown_mergeability(world, capsys):
    world.pulls = [
        make_pull(mergeable_state="unknown"),
        make_pull(mergeable_state="unknown"),
        make_pull(mergeable_state="clean"),
    ]
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["outcome"] == "MERGED"
    assert world.reads().count("get_pull") == 5


def test_cli_poll_head_moved(world, capsys):
    world.pulls = [make_pull(mergeable_state="unknown"), make_pull(head={"sha": OTHER_HEAD})]
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["decision"]["reason"] == "read:head_moved" and world.writes == []


def test_cli_files_completeness(world, capsys):
    world.pulls = [make_pull(changed_files=5)]
    rc, rec = run(world, capsys)
    assert rc == 0 and rec["decision"]["reason"] == "read:files" and world.writes == []


def test_cli_scrub_redacts_tokens_in_envelope_and_failed_record(world, capsys):
    leaked = "ghs_" + "a" * 36  # pragma: allowlist secret
    world.merge_exc = github.GitHubError(f"bad credentials {leaked}", 409)
    rc, rec = run(world, capsys)
    assert leaked not in json.dumps(rec)
    assert leaked not in json.dumps(world.event_dict(am.EVENT_FAILED))
    assert leaked not in world.comments[-1]["body"]
    assert "[REDACTED]" in world.event_dict(am.EVENT_FAILED)["message"]


def test_cli_unhandled_exception_keeps_stdout_one_json_line(world, capsys, monkeypatch):
    monkeypatch.setattr(am, "decide_merge_on_human_approval", lambda *a: 1 / 0)
    rc, rec = run(world, capsys)
    assert rc == 1 and rec["error"].startswith("unhandled ZeroDivisionError")


# --------------------------------------------------------------------------- #
# 7.5 — read-only twin
# --------------------------------------------------------------------------- #

TWIN_APPROVAL = ["approval-merge", "--app", "human", "--pr", "2211", "--repo", "o/r"]
TWIN_PROVENANCE = ["merge-provenance", "--app", "human", "--pr", "2211", "--repo", "o/r"]


def twin_run(world: World, capsys, argv) -> tuple[int, dict]:
    rc = twin.main(argv, repo_root=str(world.root))
    out = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(out) == 1
    return rc, json.loads(out[0])


def test_twin_1_would_merge_and_writes_nothing(world, capsys, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the read-only twin attempted a write")

    for name in WRITE_FNS:
        monkeypatch.setattr(github, name, boom)
    monkeypatch.setattr(audit_log, "write_event", boom)
    rc, rec = twin_run(world, capsys, TWIN_APPROVAL)
    assert rc == 0 and rec["would_merge"] is True
    assert _ENVELOPE_KEYS.issubset(rec)
    assert rec["decision"]["reason"] == "approved_by_designated_human"
    assert rec["decision"]["approving_review_id"] == 5708492480
    assert rec["gate_evaluated_as"] == OVERSEER
    assert rec["gate"]["autonomous_capable"] is True
    assert rec["gate"]["ruleset_ids"] == [18044233]


def test_twin_2_read_error_is_exit_0_undeterminable(world, capsys):
    world.events_exc = github.GitHubError("down", 500)
    rc, rec = twin_run(world, capsys, TWIN_APPROVAL)
    assert rc == 0 and rec["would_merge"] is False
    assert rec["decision"]["outcome"] == "UNDETERMINABLE" and rec["gate"] is None


def test_twin_2_never_exits_3(world, capsys, monkeypatch):
    monkeypatch.delenv("HOS_BOT_LOGIN")
    for argv in (TWIN_APPROVAL, TWIN_PROVENANCE):
        rc, _ = twin_run(world, capsys, argv)
        assert rc != 3


def _provenance_pull(merged_by: str, merged: bool = True) -> dict:
    return make_pull(
        merged=merged,
        state="closed" if merged else "open",
        merged_by={"login": merged_by},
        merge_commit_sha="e" * 40,
    )


def test_twin_3_provenance(world, capsys):
    world.pulls = [_provenance_pull(OVERSEER)]
    rc, rec = twin_run(world, capsys, TWIN_PROVENANCE)
    assert rc == 0 and rec["classification"] == "unauthorized"
    assert rec["authorized_record_present"] is False

    _seed_authorized(world)
    rc, rec = twin_run(world, capsys, TWIN_PROVENANCE)
    assert rec["classification"] == "authorized_on_human_approval"
    assert rec["authorized_record_present"] is True and rec["completion_record_present"] is False
    assert rec["merged_by"] == OVERSEER and rec["head_sha"] == HEAD

    world.pulls = [_provenance_pull(WORKER)]
    rc, rec = twin_run(world, capsys, TWIN_PROVENANCE)
    assert rec["classification"] == "unauthorized"

    world.pulls = [_provenance_pull(OVERSEER, merged=False)]
    rc, rec = twin_run(world, capsys, TWIN_PROVENANCE)
    assert rc == 0 and rec["classification"] == "not_merged"


def test_twin_3_provenance_read_failures_exit_1(world, capsys, monkeypatch):
    monkeypatch.setattr(github, "get_pull", lambda o, r, n: None)
    rc, rec = twin_run(world, capsys, TWIN_PROVENANCE)
    assert rc == 1 and rec["error"]

    def raising(o, r, n):
        raise github.GitHubError("down", 500)

    monkeypatch.setattr(github, "get_pull", raising)
    rc, rec = twin_run(world, capsys, TWIN_PROVENANCE)
    assert rc == 1


# --------------------------------------------------------------------------- #
# new github.py readers
# --------------------------------------------------------------------------- #


class FakeRunGh:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple] = []

    def __call__(self, args, retries=3, backoff_base=2.0, stdin_json=None):
        self.calls.append((args, retries, stdin_json))
        value = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(value, Exception):
            raise value
        return value


def patch_gh(monkeypatch, *responses) -> FakeRunGh:
    fake = FakeRunGh(*responses)
    monkeypatch.setattr(github, "_run_gh", fake)
    return fake


def test_gh_events_1(monkeypatch):
    patch_gh(monkeypatch, [{"id": 1}] * 100)
    with pytest.raises(github.GitHubError, match="exceeded"):
        github.list_issue_events("o", "r", 1)
    patch_gh(monkeypatch, {"not": "a list"})
    with pytest.raises(github.GitHubError, match="unexpected"):
        github.list_issue_events("o", "r", 1)
    patch_gh(monkeypatch, None)
    with pytest.raises(github.GitHubError) as info:
        github.list_issue_events("o", "r", 1)
    assert info.value.status_code == 404
    patch_gh(monkeypatch, [{"id": 1}] * 100, [{"id": 2}] * 5)
    assert len(github.list_issue_events("o", "r", 1)) == 105


def _threads_page(nodes, has_next=False, cursor=None):
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                        "nodes": nodes,
                    }
                }
            }
        }
    }


def test_gh_threads_1(monkeypatch):
    fake = patch_gh(
        monkeypatch,
        _threads_page([{"id": "a", "isResolved": True}], True, "CUR1"),
        _threads_page([{"id": "b", "isResolved": False}]),
    )
    threads = github.list_review_threads("o", "r", 7)
    assert [t["id"] for t in threads] == ["a", "b"]
    first, second = fake.calls[0][0], fake.calls[1][0]
    assert first[0] == "graphql" and "cursor=CUR1" not in " ".join(first)
    assert "cursor=CUR1" in second and "number=7" in first

    patch_gh(monkeypatch, {"errors": [{"message": "x"}]})
    with pytest.raises(github.GitHubError):
        github.list_review_threads("o", "r", 7)
    patch_gh(monkeypatch, {"data": {"repository": {"pullRequest": None}}})
    with pytest.raises(github.GitHubError):
        github.list_review_threads("o", "r", 7)
    patch_gh(monkeypatch, _threads_page([], True, "CUR"))
    with pytest.raises(github.GitHubError, match="exceeded"):
        github.list_review_threads("o", "r", 7)


SHA = "a" * 40


def test_gh_merge_1(monkeypatch):
    fake = patch_gh(monkeypatch, {"merged": True, "sha": "b" * 40})
    assert github.merge_pull("o", "r", 5, SHA)["merged"] is True
    args, retries, body = fake.calls[0]
    assert args == ["/repos/o/r/pulls/5/merge", "--method", "PUT"]
    assert retries == 0 and body == {"merge_method": "squash", "sha": SHA}

    fake = patch_gh(monkeypatch, {"merged": True})
    with pytest.raises(ValueError):
        github.merge_pull("o", "r", 5, "short")
    assert fake.calls == []
    patch_gh(monkeypatch, None)
    with pytest.raises(github.GitHubError) as excinfo:
        github.merge_pull("o", "r", 5, SHA)
    assert excinfo.value.status_code is None


def test_gh_file_1(monkeypatch):
    payload = {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(b"* @a\n").decode(),
    }
    fake = patch_gh(monkeypatch, payload)
    assert github.get_file_text("o", "r", ".github/CODEOWNERS", "feat/x") == "* @a\n"
    assert "ref=feat%2Fx" in fake.calls[0][0][0]
    patch_gh(monkeypatch, None)
    assert github.get_file_text("o", "r", "p", "main") is None
    patch_gh(monkeypatch, {"type": "dir"})
    with pytest.raises(github.GitHubError):
        github.get_file_text("o", "r", "p", "main")
    patch_gh(monkeypatch, {"type": "file", "encoding": "base64", "content": "!!notbase64"})
    with pytest.raises(github.GitHubError):
        github.get_file_text("o", "r", "p", "main")


def test_gh_ruleset_1(monkeypatch):
    patch_gh(monkeypatch, {"id": 1, "enforcement": "active"})
    assert github.get_ruleset("o", "r", 1)["enforcement"] == "active"
    patch_gh(monkeypatch, ["nope"])
    with pytest.raises(github.GitHubError):
        github.get_ruleset("o", "r", 1)


def test_gh_rules_1(monkeypatch):
    patch_gh(monkeypatch, [{"type": "deletion"}] * 100)
    with pytest.raises(github.GitHubError, match="exceeded"):
        github.list_branch_rules("o", "r", "main")
    rules = [
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "a"}, {"context": "b"}]},
        },
        {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": "a"}, "junk"]},
        },
        "junk",
    ]
    patch_gh(monkeypatch, rules)
    assert github.list_branch_rules("o", "r", "main") == rules
    assert github.get_ruleset_required_checks("o", "r", "main") == ["a", "b"]


# --------------------------------------------------------------------------- #
# 7.6 — wrapper
# --------------------------------------------------------------------------- #

WRAPPER = REPO_ROOT / "bootstrap" / "overseer_merge.sh"


def test_wrap_1_static():
    text = WRAPPER.read_text(encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(WRAPPER)], check=False).returncode == 0
    assert 'overseer_merge_cli.py" "$@"' in text
    assert "revoke_app_token.sh" in text and "trap" in text
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    for line in code:
        assert not (("echo" in line or "printf" in line) and ">&2" not in line), line
        assert '{"' not in line, line
    case_lines = [ln.strip() for ln in code if ln.strip().endswith(")") and "|" not in ln]
    assert "on-human-approval)" in case_lines and "overseer) MINT_TOKEN=true ;;" in [
        ln.strip() for ln in code
    ]
    assert "MINT_TOKEN=true" in text and text.count("MINT_TOKEN=true") == 1
    assert os.access(WRAPPER, os.X_OK)


def test_wrap_2_non_overseer_exits_3_without_minting():
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    proc = subprocess.run(
        ["bash", str(WRAPPER), "on-human-approval", "--app", "worker", "--pr", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 3, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["refusal_reason"] == "overseer_identity_required"
    assert "failed to mint" not in proc.stderr


def test_wrap_3_sentinel_cleared_and_exported_only_after_mint():
    text = WRAPPER.read_text(encoding="utf-8")
    assert text.index("unset HOS_OVERSEER_MERGE_TOKEN_MINTED") < text.index("if $MINT_TOKEN; then")
    assert text.count("export HOS_OVERSEER_MERGE_TOKEN_MINTED=1") == 1
    assert text.index("_MINTED=1") < text.index("export HOS_OVERSEER_MERGE_TOKEN_MINTED=1")


def test_wrap_4_abbreviated_app_cannot_reach_merge_on_ambient_token():
    env = {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}
    env.update(GH_TOKEN="ambient", HOS_BOT_LOGIN="x", HOS_OVERSEER_MERGE_TOKEN_MINTED="1")
    proc = subprocess.run(
        ["bash", str(WRAPPER), "on-human-approval", "--ap", "overseer", "--pr", "1"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 2, proc.stderr
