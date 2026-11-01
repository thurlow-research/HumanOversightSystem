"""
approval_merge.py — merge on a designated human's approval (#2213, slice S1a).

Names ADR-2213 AD-1/AD-3 and TD-2213. `decide_merge_on_human_approval` and
`classify_bot_merge` are pure; `fetch_snapshot` is this module's only I/O. The
decision is a first-failing-rule walk (R2-R15, TD §4.3) over one immutable
snapshot of GitHub state; tier, ceiling and surface matching are deliberately
not inputs (AD-3) because the human's approval is the authority and GitHub's
ruleset is the enforcement.

R1 (the caller is the overseer) is not here: it is the mutating CLI's
precondition, because the read-only twin evaluates the same rules for any
caller. Nothing in this module writes, labels, comments or merges.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from scripts.automation.lib import github, merge_authority, merge_config
from scripts.framework import require_overseer_approval as roa
from scripts.framework.requester_trust import codeowners_humans

NEEDS_HUMAN = "needs-human"
HOS_HALT = "hos-halt"
AGENT_STATIC_CHECK = "Agent static checks"
CHECK_STALL_SECONDS = 7200
MERGEABLE_UNKNOWN_POLLS = 3
MERGEABLE_POLL_SECONDS = 2.0

EVENT_AUTHORIZED = "merge-on-human-approval-authorized"
EVENT_MERGED = "merged-on-human-approval"
EVENT_FAILED = "merge-on-human-approval-failed"
EVENT_BASE_MISMATCH = "merge-on-human-approval-base-mismatch"
_AUDIT_EVENTS = frozenset({EVENT_AUTHORIZED, EVENT_MERGED, EVENT_FAILED})

# Trailing whitespace and CR are tolerated: this marker *blocks*, so a strict
# match would fail open (AR-1 E3).
FAILURE_MARKER_RE = re.compile(
    r"^<!-- hos:merge-on-human-approval-failed v=1 head=([0-9a-f]{40}) -->[ \t\r]*$",
    re.MULTILINE,
)

_MERGEABLE_BLOCKING = frozenset({"dirty", "behind", "blocked", "unstable", "has_hooks", "draft"})
_MESSAGE_LIMIT = 300


def render_failure_marker(head: str) -> str:
    """The one writer of the failure marker line (R12 evidence, TD-D4)."""
    if not isinstance(head, str) or not roa.SHA_RE.match(head):
        raise ValueError(f"invalid head sha: {head!r}")
    return f"<!-- hos:merge-on-human-approval-failed v=1 head={head} -->"


class ApprovalMergeOutcome(Enum):
    MERGE = "MERGE"
    DEFER = "DEFER"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    UNDETERMINABLE = "UNDETERMINABLE"


@dataclass(frozen=True)
class ApprovalMergeSnapshot:
    """Every input to the decision. A field is None when it was not fetched
    (the early stop on a closed, merged or draft PR, TD-D11)."""

    pr_number: int
    pull: dict
    now: datetime
    default_branch: Optional[str] = None
    changed_files: Optional[tuple[str, ...]] = None
    reviews: Optional[tuple[dict, ...]] = None
    issue_comments: Optional[tuple[dict, ...]] = None
    issue_events: Optional[tuple[dict, ...]] = None
    review_threads: Optional[tuple[dict, ...]] = None
    head_committed_at: Optional[str] = None
    check_runs: Optional[tuple[dict, ...]] = None
    codeowners_owners: Optional[frozenset[str]] = None
    audit_events: Optional[tuple[dict, ...]] = None
    gate: Optional[merge_authority.LiveGateResult] = None


@dataclass(frozen=True)
class ApprovalMergeDecision:
    outcome: ApprovalMergeOutcome
    rule: int
    reason: str
    detail: str = ""
    head_sha: Optional[str] = None
    approver: Optional[str] = None
    approving_review_id: Optional[int] = None
    approved_at: Optional[str] = None
    overseer_verdict_id: Optional[int] = None
    verdict_kind: Optional[str] = None
    label_provenance: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome.name,
            "rule": self.rule,
            "reason": self.reason,
            "detail": self.detail,
            "head_sha": self.head_sha,
            "approver": self.approver,
            "approving_review_id": self.approving_review_id,
            "approved_at": self.approved_at,
            "overseer_verdict_id": self.overseer_verdict_id,
            "verdict_kind": self.verdict_kind,
            "label_provenance": self.label_provenance,
        }


class SnapshotReadError(Exception):
    """A snapshot read failed. `what` names the read: pull, repo, files, reviews,
    comments, events, threads, head_commit, check_runs, codeowners, audit or
    head_moved."""

    def __init__(self, what: str, message: str):
        super().__init__(what, message)
        self.what = what
        self.message = message


def read_error_decision(
    exc: SnapshotReadError, scrub: Callable[[str], str] = lambda s: s
) -> ApprovalMergeDecision:
    """TD-D11: any snapshot read error is UNDETERMINABLE as a whole (rule 0)."""
    return ApprovalMergeDecision(
        outcome=ApprovalMergeOutcome.UNDETERMINABLE,
        rule=0,
        reason=f"read:{exc.what}",
        detail=scrub(exc.message)[:_MESSAGE_LIMIT],
    )


# ---------------------------------------------------------------------------
# fetch_snapshot — the only I/O in this module
# ---------------------------------------------------------------------------


def _read(what: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except SnapshotReadError:
        raise
    except Exception as exc:  # noqa: BLE001 - every failure is a fail-closed read error
        raise SnapshotReadError(what, f"{type(exc).__name__}: {exc}"[:_MESSAGE_LIMIT]) from exc


def _require_list(what: str, value: Any) -> tuple:
    if not isinstance(value, list):
        raise SnapshotReadError(what, f"expected a list, got {type(value).__name__}")
    return tuple(value)


def read_audit_events(repo_root: Path, pr_number: int) -> tuple[dict, ...]:
    """This PR's approval-merge audit records (raises on an unreadable log)."""
    from scripts.oversight.lib import audit_log

    kept: list[dict] = []
    for chunk in audit_log.read_stream(str(repo_root)):
        record = json.loads(chunk)
        if (
            isinstance(record, dict)
            and record.get("event") in _AUDIT_EVENTS
            and record.get("pr") == pr_number
        ):
            kept.append(record)
    return tuple(kept)


def _read_codeowners(owner: str, repo: str, default_branch: str) -> frozenset[str]:
    text = github.get_file_text(owner, repo, ".github/CODEOWNERS", ref=default_branch)
    if text is None:
        return frozenset()
    # The working-tree CODEOWNERS is never read (AF-9): parse the default
    # branch's copy through the one shared parser.
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / ".github" / "CODEOWNERS"
        target.parent.mkdir(parents=True)
        target.write_text(text, encoding="utf-8")
        return frozenset(codeowners_humans(tmp))


def fetch_snapshot(
    owner: str,
    repo: str,
    pr_number: int,
    config: merge_config.MergeConfig,
    *,
    repo_root: Path,
    now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> ApprovalMergeSnapshot:
    """Read every input once, in the TD §4.2 order. Raises SnapshotReadError;
    nothing is swallowed and nothing is cached across calls."""
    pull = _read("pull", github.get_pull, owner, repo, pr_number)
    if not isinstance(pull, dict):
        raise SnapshotReadError("pull", "pull request not found or malformed")
    if pull.get("state") != "open" or pull.get("merged") is True or pull.get("draft") is not False:
        return ApprovalMergeSnapshot(pr_number=pr_number, pull=pull, now=now)

    head = (pull.get("head") or {}).get("sha")
    if not isinstance(head, str) or not head:
        raise SnapshotReadError("pull", "pull request has no head sha")

    repo_obj = _read("repo", github.get_repo, owner, repo)
    default_branch = repo_obj.get("default_branch") if isinstance(repo_obj, dict) else None
    if not isinstance(default_branch, str) or not default_branch:
        raise SnapshotReadError("repo", "default_branch unavailable")

    raw_files = _require_list(
        "files", _read("files", github.list_pull_files, owner, repo, pr_number)
    )
    declared = pull.get("changed_files")
    if not isinstance(declared, int) or isinstance(declared, bool) or len(raw_files) != declared:
        # GitHub's files endpoint stops silently at 3000 files; an under-reported
        # list would let R4's release check fail open (AR-1 E6).
        raise SnapshotReadError(
            "files", f"file list has {len(raw_files)} entries, PR declares {declared!r}"
        )
    changed_files = tuple(
        f["filename"]
        for f in raw_files
        if isinstance(f, dict) and isinstance(f.get("filename"), str)
    )
    if len(changed_files) != len(raw_files):
        raise SnapshotReadError("files", "file list contains a malformed entry")

    reviews = _require_list(
        "reviews", _read("reviews", github.list_pull_reviews, owner, repo, pr_number)
    )
    comments = _require_list(
        "comments", _read("comments", github.list_issue_comments, owner, repo, pr_number)
    )
    events = _require_list(
        "events", _read("events", github.list_issue_events, owner, repo, pr_number)
    )
    threads = _require_list(
        "threads", _read("threads", github.list_review_threads, owner, repo, pr_number)
    )

    commit = _read("head_commit", github.get_commit, owner, repo, head)
    committed_at = None
    if isinstance(commit, dict):
        committer = (commit.get("commit") or {}).get("committer") or {}
        committed_at = committer.get("date")
    if not isinstance(committed_at, str) or not committed_at:
        raise SnapshotReadError("head_commit", "head commit has no committer date")

    check_runs = _require_list(
        "check_runs", _read("check_runs", github.list_check_runs_for_ref, owner, repo, head)
    )
    owners = _read("codeowners", _read_codeowners, owner, repo, default_branch)
    audit_events = _read("audit", read_audit_events, Path(repo_root), pr_number)

    polls = 0
    while pull.get("mergeable_state") in (None, "unknown") and polls < MERGEABLE_UNKNOWN_POLLS:
        polls += 1
        sleep(MERGEABLE_POLL_SECONDS)
        fresh = _read("pull", github.get_pull, owner, repo, pr_number)
        if not isinstance(fresh, dict):
            raise SnapshotReadError("pull", "pull request not found or malformed")
        if (fresh.get("head") or {}).get("sha") != head:
            raise SnapshotReadError("head_moved", "head changed while polling mergeability")
        pull = fresh

    # Gate last (REQ-8, AD-5); verify_merge_gate_live never raises.
    gate = merge_authority.verify_merge_gate_live(
        owner,
        repo,
        (pull.get("base") or {}).get("ref", ""),
        tier_ceiling_check_name=config.tier_ceiling_check_name,
    )

    return ApprovalMergeSnapshot(
        pr_number=pr_number,
        pull=pull,
        now=now,
        default_branch=default_branch,
        changed_files=changed_files,
        reviews=reviews,
        issue_comments=comments,
        issue_events=events,
        review_threads=threads,
        head_committed_at=committed_at,
        check_runs=check_runs,
        codeowners_owners=owners,
        audit_events=audit_events,
        gate=gate,
    )


# ---------------------------------------------------------------------------
# decide_merge_on_human_approval — pure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Ctx:
    """What the early rules established, for the later ones."""

    head: str
    approver: str
    approving_review_id: Optional[int]
    approved_at: str
    t0: datetime
    verdict_id: Optional[int]
    verdict_kind: str
    label_provenance: dict


def _d(
    outcome: ApprovalMergeOutcome,
    rule: int,
    reason: str,
    head: Optional[str],
    detail: str = "",
    **extra: Any,
) -> ApprovalMergeDecision:
    return ApprovalMergeDecision(
        outcome=outcome, rule=rule, reason=reason, detail=detail, head_sha=head, **extra
    )


def _ne(rule: int, reason: str, head: Optional[str], detail: str = "") -> ApprovalMergeDecision:
    return _d(ApprovalMergeOutcome.NOT_ELIGIBLE, rule, reason, head, detail)


def _und(rule: int, reason: str, head: Optional[str], detail: str = "") -> ApprovalMergeDecision:
    return _d(ApprovalMergeOutcome.UNDETERMINABLE, rule, reason, head, detail)


def _login(item: dict, key: str = "user") -> str:
    return str((item.get(key) or {}).get("login", "")).lower()


def _label_names(pull: dict) -> set[str]:
    return {
        str(lbl.get("name", "")).lower()
        for lbl in (pull.get("labels") or [])
        if isinstance(lbl, dict)
    }


def decide_merge_on_human_approval(
    snapshot: ApprovalMergeSnapshot, config: merge_config.MergeConfig
) -> ApprovalMergeDecision:
    """First failing rule wins (TD §4.3). Performs no I/O."""
    pull = snapshot.pull
    head = (pull.get("head") or {}).get("sha")
    head_for_record = head if isinstance(head, str) else None

    # R2
    if pull.get("state") != "open" or pull.get("merged") is True:
        return _ne(2, "not_open_pr", head_for_record)
    if pull.get("draft") is not False:
        return _ne(2, "draft", head_for_record)
    if not isinstance(head, str) or not roa.SHA_RE.match(head):
        return _und(0, "head_sha_invalid", head_for_record)
    if snapshot.default_branch is None:
        return _und(2, "missing:default_branch", head)
    if (pull.get("base") or {}).get("ref") != snapshot.default_branch:
        return _ne(2, "base_not_default_branch", head)

    # R3
    labels = _label_names(pull)
    if HOS_HALT in labels:
        return _ne(3, "hos_halt", head)

    # R4
    if snapshot.changed_files is None:
        return _und(4, "missing:changed_files", head)
    if merge_authority._is_release_related(pull.get("title") or "", list(snapshot.changed_files)):
        return _ne(4, "release", head)

    # R5
    author = str((pull.get("user") or {}).get("login", ""))
    if not author:
        return _und(5, "pr_author_missing", head)
    if not merge_authority._verify_authorship_separation(
        author, config.overseer_handle, config.worker_handle
    ):
        return _ne(5, "self_authored", head)

    # R6
    if snapshot.reviews is None:
        return _und(6, "missing:reviews", head)
    if snapshot.codeowners_owners is None:
        return _und(6, "missing:codeowners_owners", head)
    reviews = list(snapshot.reviews)
    designated = roa.designated_humans(
        {"HUMAN_REVIEWER": config.human_reviewer}, set(snapshot.codeowners_owners)
    )
    if not designated:
        return _und(6, "no_designated_humans", head)
    eligible = roa.eligible_human_approvals_on_head(
        reviews, set(config.bot_accounts), designated, head
    )
    if not eligible:
        return _ne(6, "no_eligible_approval", head)
    eligible_lower = {e.lower() for e in eligible}
    candidates: list[tuple[datetime, int, dict]] = []
    for r in reviews:
        if (
            str(r.get("state", "")).upper() == "APPROVED"
            and r.get("commit_id") == head
            and _login(r) in eligible_lower
        ):
            when = merge_authority._parse_iso(r.get("submitted_at"))
            if when is None:
                return _und(6, "timestamp:approval", head)
            candidates.append((when, int(r.get("id") or 0), r))
    if not candidates:
        return _ne(6, "no_eligible_approval", head)
    t0, _, approval = max(candidates, key=lambda c: (c[0], c[1]))
    approver = str((approval.get("user") or {}).get("login", ""))
    approving_review_id = approval.get("id")
    approved_at = str(approval.get("submitted_at"))

    # R7
    verdict = roa.latest_overseer_verdict_on_head(reviews, config.overseer_handle, head)
    verdict_kind: Optional[str] = None
    if verdict is not None:
        if str(verdict.get("state", "")).upper() == "APPROVED":
            verdict_kind = "approved"
        else:
            marker = roa.valid_interim_signoff(verdict, head)
            if marker is not None and marker[1] == "APPROVE":
                verdict_kind = f"marker:{marker[0]}"
    if verdict is None or verdict_kind is None:
        return _ne(7, "no_approve_signoff", head)

    # R8
    if NEEDS_HUMAN in labels:
        if snapshot.issue_events is None:
            return _und(8, "missing:issue_events", head)
        labeled: list[tuple[datetime, int, dict]] = []
        for ev in snapshot.issue_events:
            if (
                ev.get("event") == "labeled"
                and str((ev.get("label") or {}).get("name", "")).lower() == NEEDS_HUMAN
            ):
                when = merge_authority._parse_iso(ev.get("created_at"))
                if when is None:
                    return _und(8, "timestamp:label_event", head)
                labeled.append((when, int(ev.get("id") or 0), ev))
        if not labeled:
            return _und(8, "label_event_missing", head)
        latest_ev = max(labeled, key=lambda c: (c[0], c[1]))[2]
        actor = str((latest_ev.get("actor") or {}).get("login", ""))
        if actor.lower() != config.overseer_handle.lower():
            return _ne(8, "foreign_needs_human", head, detail=f"applied by {actor or 'unknown'}")
        provenance: dict = {
            "labeled_event_id": latest_ev.get("id"),
            "actor": actor,
            "created_at": latest_ev.get("created_at"),
        }
    else:
        provenance = {"absent": True}

    # R9
    if snapshot.issue_comments is None:
        return _und(9, "missing:issue_comments", head)
    head_dt = merge_authority._parse_iso(snapshot.head_committed_at)
    if head_dt is None:
        return _und(9, "missing:head_committed_at", head)
    # The committer date is author-set. A head committed at or after the approval
    # is impossible for an honest push (the approved commit existed when it was
    # approved), so it supersedes nothing: with no cutoff every matching hold
    # counts, fail-safe (AR-1 E5; detect_human_hold_directive treats a None
    # cutoff that way). This also keeps the approval's own body in scope.
    cutoff_iso = (
        head_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if head_dt < t0 else None
    )
    items: list[dict] = list(snapshot.issue_comments)
    for r in reviews:
        if r.get("commit_id") == head and _login(r) in designated:
            items.append(
                {"user": r.get("user"), "body": r.get("body"), "created_at": r.get("submitted_at")}
            )
    for login in sorted(designated):
        if merge_authority.detect_human_hold_directive(items, login, cutoff_iso) is not None:
            return _ne(9, "hold_directive", head, detail=f"hold directive from {login}")

    # R10
    unparseable = False
    for c in snapshot.issue_comments:
        if _login(c) in designated:
            when = merge_authority._parse_iso(c.get("created_at"))
            if when is None:
                unparseable = True
            elif when > t0:
                return _ne(10, "human_comment_after_approval", head)
    for r in reviews:
        if _login(r) in designated and str(r.get("state", "")).upper() == "COMMENTED":
            if not r.get("submitted_at"):
                continue  # pending: ignored
            when = merge_authority._parse_iso(r.get("submitted_at"))
            if when is None:
                unparseable = True
            elif when > t0:
                return _ne(10, "human_comment_after_approval", head)
    if unparseable:
        return _und(10, "timestamp:human_activity", head)

    # R11
    if snapshot.review_threads is None:
        return _und(11, "missing:review_threads", head)
    unresolved = [t for t in snapshot.review_threads if t.get("isResolved") is not True]
    if unresolved:
        return _ne(11, "unresolved_thread", head, detail=f"{len(unresolved)} unresolved")

    # R12
    failure = _failure_evidence_decision(snapshot, config, designated, head)
    if failure is not None:
        return failure

    ctx = _Ctx(
        head=head,
        approver=approver,
        approving_review_id=approving_review_id if isinstance(approving_review_id, int) else None,
        approved_at=approved_at,
        t0=t0,
        verdict_id=verdict.get("id") if isinstance(verdict.get("id"), int) else None,
        verdict_kind=verdict_kind,
        label_provenance=provenance,
    )

    # R13-R15
    blocked = _pre_merge_live_checks(snapshot, ctx)
    if blocked is not None:
        return blocked

    return ApprovalMergeDecision(
        outcome=ApprovalMergeOutcome.MERGE,
        rule=15,
        reason="approved_by_designated_human",
        head_sha=head,
        approver=ctx.approver,
        approving_review_id=ctx.approving_review_id,
        approved_at=ctx.approved_at,
        overseer_verdict_id=ctx.verdict_id,
        verdict_kind=ctx.verdict_kind,
        label_provenance=ctx.label_provenance,
    )


def _failure_evidence_decision(
    snapshot: ApprovalMergeSnapshot,
    config: merge_config.MergeConfig,
    designated: frozenset[str],
    head: str,
) -> Optional[ApprovalMergeDecision]:
    """R12 (TD-D4, AR-1 E3/E4): a recorded failed merge on this head blocks until
    a designated non-bot human removes `needs-human` after it."""
    if snapshot.audit_events is None:
        return _und(12, "missing:audit_events", head)
    if snapshot.issue_comments is None:
        return _und(12, "missing:issue_comments", head)
    if snapshot.issue_events is None:
        return _und(12, "missing:issue_events", head)

    evidence: list[datetime] = []
    for ev in snapshot.audit_events:
        if (
            ev.get("event") == EVENT_FAILED
            and ev.get("pr") == snapshot.pr_number
            and ev.get("head_sha") == head
        ):
            when = merge_authority._parse_iso(ev.get("timestamp"))
            if when is None:
                return _und(12, "timestamp:failure_evidence", head)
            evidence.append(when)
    for c in snapshot.issue_comments:
        user = c.get("user") or {}
        if _login(c) != config.overseer_handle.lower() or user.get("type") != "Bot":
            continue
        if head in FAILURE_MARKER_RE.findall(str(c.get("body") or "")):
            when = merge_authority._parse_iso(c.get("created_at"))
            if when is None:
                return _und(12, "timestamp:failure_evidence", head)
            evidence.append(when)
    if not evidence:
        return None

    latest_evidence = max(evidence)
    for ev in snapshot.issue_events:
        if ev.get("event") != "unlabeled":
            continue
        if str((ev.get("label") or {}).get("name", "")).lower() != NEEDS_HUMAN:
            continue
        actor = ev.get("actor") or {}
        if str(actor.get("login", "")).lower() not in designated or actor.get("type") == "Bot":
            continue
        when = merge_authority._parse_iso(ev.get("created_at"))
        if when is None:
            return _und(12, "timestamp:failure_evidence", head)
        if when > latest_evidence:
            return None  # a designated human reset it: one fresh attempt
    return _ne(12, "merge_failed_on_head", head)


def _pre_merge_live_checks(
    snapshot: ApprovalMergeSnapshot, ctx: _Ctx
) -> Optional[ApprovalMergeDecision]:
    """R13, R14, R15 in order; the first failing decision, else None (AD-12 seam:
    #2209's merge-guard replaces this body)."""
    head = ctx.head
    gate = snapshot.gate
    if gate is None:
        return _und(13, "missing:gate", head)
    if snapshot.check_runs is None:
        return _und(13, "missing:check_runs", head)

    # R13
    if not gate.required_contexts:
        return _und(13, "required_contexts_unavailable", head)
    required = set(gate.required_contexts) | {AGENT_STATIC_CHECK}
    latest = merge_authority._latest_check_runs_by_name(list(snapshot.check_runs))
    pending: list[str] = []
    failed: list[str] = []
    for name in sorted(required):
        run = latest.get(name)
        if run is None or run.get("status") != "completed":
            pending.append(name)
        elif run.get("conclusion") != "success":
            failed.append(name)
    if failed:
        return _ne(13, "check_not_success", head, detail=", ".join(failed))
    if pending:
        if (snapshot.now - ctx.t0).total_seconds() > CHECK_STALL_SECONDS:
            return _ne(13, "checks_stalled", head, detail=", ".join(pending))
        return _d(ApprovalMergeOutcome.DEFER, 13, "checks_pending", head, detail=", ".join(pending))

    # R14
    state = snapshot.pull.get("mergeable_state")
    if state is None or state == "unknown":
        return _d(ApprovalMergeOutcome.DEFER, 14, "mergeable_unknown", head)
    if state != "clean":
        reason = f"mergeable_{state}" if state in _MERGEABLE_BLOCKING else "mergeable_other"
        return _ne(14, reason, head)

    # R15
    if gate.autonomous_capable is not True:
        return _ne(15, "gate_failed", head, detail=gate.reason)
    return None


# ---------------------------------------------------------------------------
# classify_bot_merge — pure (AD-9)
# ---------------------------------------------------------------------------


class BotMergeClass(Enum):
    AUTHORIZED_ON_HUMAN_APPROVAL = "authorized_on_human_approval"
    UNAUTHORIZED = "unauthorized"


@dataclass(frozen=True)
class BotMergeProvenance:
    classification: BotMergeClass
    authorized_record: Optional[dict]
    completion_record_present: bool


def classify_bot_merge(
    pr_number: int,
    merged_head_sha: str,
    merged_by: str,
    audit_events: Sequence[dict],
    overseer_login: str,
) -> BotMergeProvenance:
    """AUTHORIZED only when the overseer itself merged and a write-ahead record
    exists for exactly this (pr, head). The completion record is informational:
    the write-ahead record is the key (AD-9)."""

    def _match(event_name: str) -> Optional[dict]:
        for ev in audit_events:
            if (
                ev.get("event") == event_name
                and ev.get("pr") == pr_number
                and ev.get("head_sha") == merged_head_sha
            ):
                return ev
        return None

    authorized = _match(EVENT_AUTHORIZED)
    completion = _match(EVENT_MERGED)
    by_overseer = bool(merged_by) and merged_by.lower() == overseer_login.lower()
    classification = (
        BotMergeClass.AUTHORIZED_ON_HUMAN_APPROVAL
        if by_overseer and authorized is not None
        else BotMergeClass.UNAUTHORIZED
    )
    return BotMergeProvenance(
        classification=classification,
        authorized_record=(
            authorized if classification is BotMergeClass.AUTHORIZED_ON_HUMAN_APPROVAL else None
        ),
        completion_record_present=completion is not None,
    )
