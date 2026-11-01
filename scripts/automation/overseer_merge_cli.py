#!/usr/bin/env python3
"""
overseer_merge_cli.py — L2 mutating primitive: merge a PR on a designated
human's approval (#2213, slice S1a; ADR-2213 AD-6, TD-2213 §4.5).

    overseer_merge_cli.py on-human-approval --app overseer --pr <N>

Recomputes the approval-merge decision in this invocation (the read-only
twin's answer is never trusted), and only on MERGE: writes a write-ahead audit
record, makes the SHA-pinned squash merge, then removes `needs-human` and
writes the completion record, both best effort. A definite refusal by GitHub
records the failure, comments, and (if absent) labels `needs-human`. An
ambiguous result is re-read and never recorded as a failure.

There is deliberately no --repo, --force, --skip-*, --head-sha, --dry-run or
--repo-root: the repo always comes from the clone's origin remote.

Exit codes: 0 decided (MERGED, DEFER, NOT_ELIGIBLE, UNDETERMINABLE);
1 operational (config, identity unresolvable, write-ahead failure,
MERGE_FAILED, MERGE_UNCONFIRMED, unhandled exception); 2 usage; 3 identity
refusal. stdout is exactly one JSON object, always.

Invoked exclusively through `bootstrap/overseer_merge.sh` (L3). Importing this
module performs no I/O: the only module-level work is the sys.path bootstrap.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT_STR = str(_DEFAULT_REPO_ROOT)
if _REPO_ROOT_STR not in sys.path:
    sys.path.insert(0, _REPO_ROOT_STR)

from scripts.automation.lib import approval_merge as am  # noqa: E402
from scripts.automation.lib import github, merge_config  # noqa: E402
from scripts.automation.merge_authority_cli import (  # noqa: E402
    _envelope,
    _EnvelopeArgumentParser,
    _pr_type,
    _UsageExit,
)
from scripts.automation.pr_review_cli import _scrub_exc, _scrub_secrets  # noqa: E402

SUBCOMMAND = "on-human-approval"
_CYCLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_MESSAGE_LIMIT = 300
TOKEN_MINTED_ENV = "HOS_OVERSEER_MERGE_TOKEN_MINTED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_parser() -> _EnvelopeArgumentParser:
    parser = _EnvelopeArgumentParser(
        prog="overseer_merge_cli.py", add_help=False, allow_abbrev=False
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)
    mode_p = subparsers.add_parser(SUBCOMMAND, add_help=False, allow_abbrev=False)
    mode_p.add_argument("--app", required=True, choices=("worker", "overseer", "human"))
    mode_p.add_argument("--pr", type=_pr_type, required=True)
    return parser


@dataclass
class _Result:
    """One invocation's outcome: payload keys, exit code, envelope extras."""

    payload: dict
    exit_code: int
    error: str | None = None
    not_verified: list[str] = field(default_factory=list)
    repo: str | None = None
    config_source: str | None = None


def _gh_message(exc: Exception) -> str:
    """The error's own message, scrubbed (GitHubError.__str__ is its args tuple)."""
    if isinstance(exc, github.GitHubError) and exc.args:
        return _scrub_secrets(str(exc.args[0]))
    return _scrub_exc(exc)


def _blank_payload() -> dict:
    return {
        "outcome": None,
        "decision": None,
        "merge_commit_sha": None,
        "audit_records": {"authorized": None, "merged": None, "failed": None},
        "authorized_record_reused": False,
        "label_removed": False,
        "label_added": False,
        "failure_comment_url": None,
        "http_status": None,
        "recovered": False,
        "refused": False,
        "refusal_reason": None,
    }


def _refuse(reason: str, exit_code: int = 3) -> _Result:
    payload = _blank_payload()
    payload.update(refused=True, refusal_reason=reason)
    return _Result(payload, exit_code)


def _fail(error: str, payload: dict | None = None, exit_code: int = 1) -> _Result:
    return _Result(payload if payload is not None else _blank_payload(), exit_code, error=error)


def _failure_comment(head: str, status: object, message: str) -> str:
    return (
        "**Executive summary:** The overseer tried to merge this PR on your approval of commit "
        f"`{head[:12]}`, and GitHub refused the merge (HTTP {status}: {message}). Nothing was "
        "merged. Expected action: **OTHER**: merge the PR yourself on GitHub once the cause is "
        "fixed, or push a new commit. The overseer will not try to merge this commit again "
        "unless you remove the `needs-human` label. Not verified this run: nothing was skipped "
        "this run.\n\n"
        f"{am.render_failure_marker(head)}\n"
    )


class _Merger:
    """The mutating half of one invocation, after the decision is MERGE."""

    def __init__(
        self,
        owner: str,
        repo: str,
        pr: int,
        snapshot: am.ApprovalMergeSnapshot,
        decision: am.ApprovalMergeDecision,
        repo_root: Path,
        payload: dict,
        not_verified: list[str],
    ):
        self.owner, self.repo, self.pr = owner, repo, pr
        self.snapshot, self.decision = snapshot, decision
        self.repo_root = repo_root
        self.payload, self.not_verified = payload, not_verified
        self.head = str(decision.head_sha)
        cycle = os.environ.get("HOS_CYCLE_ID", "")
        self.cycle_id = cycle if _CYCLE_ID_RE.match(cycle) else None
        self.actor = os.environ.get("HOS_BOT_LOGIN", "")

    # -- audit ---------------------------------------------------------------

    def _record(self, event: str, **fields: object) -> dict:
        return {
            "event": event,
            "repo": f"{self.owner}/{self.repo}",
            "pr": self.pr,
            "head_sha": self.head,
            "actor": self.actor,
            "cycle_id": self.cycle_id,
            "timestamp": _now_iso(),
            **fields,
        }

    def _write(self, record: dict) -> str:
        from scripts.oversight.lib import audit_log

        return os.path.join("audit", "log", audit_log.write_event(record, root=str(self.repo_root)))

    def _best_effort_write(self, slot: str, record: dict) -> None:
        try:
            self.payload["audit_records"][slot] = self._write(record)
        except Exception as exc:  # noqa: BLE001 - the GitHub write already landed
            self.not_verified.append(f"{slot} audit record not written: {_scrub_exc(exc)}")

    def write_ahead(self) -> str | None:
        """Write (or reuse) the authorization record; an error string on failure."""
        d, gate = self.decision, self.snapshot.gate
        for ev in self.snapshot.audit_events or ():
            if (
                ev.get("event") == am.EVENT_AUTHORIZED
                and ev.get("pr") == self.pr
                and ev.get("head_sha") == self.head
                and ev.get("approving_review_id") == d.approving_review_id
                and ev.get("overseer_verdict_id") == d.overseer_verdict_id
            ):
                self.payload["authorized_record_reused"] = True
                self.payload["audit_records"]["authorized"] = self._relpath_of(ev)
                return None
        record = self._record(
            am.EVENT_AUTHORIZED,
            approver=d.approver,
            approving_review_id=d.approving_review_id,
            approved_at=d.approved_at,
            overseer_verdict_id=d.overseer_verdict_id,
            verdict_kind=d.verdict_kind,
            label_provenance=d.label_provenance,
            gate={
                "reason": gate.reason if gate else None,
                "ruleset_ids": list(gate.ruleset_ids) if gate else [],
                "required_contexts": list(gate.required_contexts) if gate else [],
            },
        )
        try:
            self.payload["audit_records"]["authorized"] = self._write(record)
        except Exception as exc:  # noqa: BLE001
            return f"write-ahead audit failed: {_scrub_exc(exc)}"
        return None

    @staticmethod
    def _relpath_of(record: dict) -> str | None:
        try:
            from scripts.oversight.lib import audit_log

            ts = audit_log.normalize_ts(str(record["timestamp"]))
            return os.path.join("audit", "log", audit_log.record_relpath(record, ts))
        except Exception:  # noqa: BLE001 - the path is informational
            return None

    # -- outcomes ------------------------------------------------------------

    def _merged(self, merge_commit_sha: object, recovered: bool) -> _Result:
        p, d = self.payload, self.decision
        p["outcome"] = "MERGED"
        p["merge_commit_sha"] = merge_commit_sha
        p["recovered"] = recovered
        if am.NEEDS_HUMAN in am._label_names(self.snapshot.pull):
            try:
                github.remove_issue_label(self.owner, self.repo, self.pr, am.NEEDS_HUMAN)
                p["label_removed"] = True
            except Exception as exc:  # noqa: BLE001
                self.not_verified.append(f"needs-human label not removed: {_scrub_exc(exc)}")
        self._best_effort_write(
            "merged",
            self._record(
                am.EVENT_MERGED,
                merge_commit_sha=merge_commit_sha,
                approver=d.approver,
                approving_review_id=d.approving_review_id,
                overseer_verdict_id=d.overseer_verdict_id,
                verdict_kind=d.verdict_kind,
                label_removed=p["label_removed"],
                recovered=recovered,
                authorized_record=p["audit_records"]["authorized"],
            ),
        )
        return _Result(p, 0, not_verified=self.not_verified)

    def _definite_failure(self, status: object, message: str) -> _Result:
        p, d = self.payload, self.decision
        message = _scrub_secrets(message)[:_MESSAGE_LIMIT]
        p["outcome"] = "MERGE_FAILED"
        p["http_status"] = status
        self._best_effort_write(
            "failed",
            self._record(
                am.EVENT_FAILED,
                http_status=status,
                message=message,
                approver=d.approver,
                approving_review_id=d.approving_review_id,
            ),
        )
        try:
            comment = github.post_comment(
                self.owner, self.repo, self.pr, _failure_comment(self.head, status, message)
            )
            p["failure_comment_url"] = (comment or {}).get("html_url")
        except Exception as exc:  # noqa: BLE001
            self.not_verified.append(f"failure comment not posted: {_scrub_exc(exc)}")
        if am.NEEDS_HUMAN not in am._label_names(self.snapshot.pull):
            try:
                github.add_issue_label(self.owner, self.repo, self.pr, am.NEEDS_HUMAN)
                p["label_added"] = True
            except Exception as exc:  # noqa: BLE001
                self.not_verified.append(f"needs-human label not added: {_scrub_exc(exc)}")
        return _Result(
            p, 1, error=f"merge refused by GitHub (HTTP {status})", not_verified=self.not_verified
        )

    def _ambiguous(self, exc: Exception) -> _Result:
        """TD-D5 / AR-1 E1: re-read; a retry is safe because the decision is
        recomputed and the SHA pinned, so nothing is recorded as a failure."""
        p = self.payload
        try:
            fresh = github.get_pull(self.owner, self.repo, self.pr)
        except Exception:  # noqa: BLE001 - a failed re-read means "not merged"
            fresh = None
        if (
            isinstance(fresh, dict)
            and fresh.get("merged") is True
            and (fresh.get("head") or {}).get("sha") == self.head
            and fresh.get("merge_commit_sha")
        ):
            return self._verify_base_after_merge(
                self._merged(fresh["merge_commit_sha"], recovered=True)
            )
        p["outcome"] = "MERGE_UNCONFIRMED"
        p["http_status"] = getattr(exc, "status_code", None)
        return _Result(
            p,
            1,
            error=f"merge result unconfirmed: {_gh_message(exc)}"[:_MESSAGE_LIMIT],
            not_verified=self.not_verified,
        )

    def _state_change(self, fresh: object) -> str | None:
        """Why the PR no longer matches what was authorized (CWE-367), or None.
        Fails closed: an unreadable or malformed PR is itself a change."""
        if not isinstance(fresh, dict):
            return "the PR could not be re-read"
        base = (fresh.get("base") or {}).get("ref")
        snap_base = (self.snapshot.pull.get("base") or {}).get("ref")
        if base != snap_base or base != self.snapshot.default_branch:
            return f"base branch changed to {base!r}"
        if (fresh.get("head") or {}).get("sha") != self.head:
            return "head SHA moved"
        if fresh.get("state") != "open" or fresh.get("merged") is True:
            return "PR is no longer open"
        if fresh.get("draft") is not False:
            return "PR is a draft"
        labels = am._label_names(fresh)
        if am.HOS_HALT in labels:
            return "hos-halt label is set"
        if (am.NEEDS_HUMAN in labels) != (am.NEEDS_HUMAN in am._label_names(self.snapshot.pull)):
            return "needs-human label changed"
        return None

    @staticmethod
    def _review_key(review: dict) -> tuple:
        return (review.get("state"), review.get("body"), review.get("submitted_at"))

    @staticmethod
    def _parseable(value: object) -> bool:
        if not isinstance(value, str):
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True

    def _activity_change(self) -> str | None:
        """New or altered reviews and issue comments since the snapshot (R6,
        R9, R10). Not re-evaluated: any new activity defers to the next cycle."""
        try:
            reviews = github.list_pull_reviews(self.owner, self.repo, self.pr)
            comments = github.list_issue_comments(self.owner, self.repo, self.pr)
        except Exception:  # noqa: BLE001
            return "reviews and comments could not be re-read"
        if not isinstance(reviews, list) or not isinstance(comments, list):
            return "reviews and comments could not be re-read"
        snap_reviews = {r.get("id"): self._review_key(r) for r in self.snapshot.reviews or ()}
        for review in reviews:
            rid = review.get("id")
            if rid not in snap_reviews:
                return "a new review was posted"
            if self._review_key(review) != snap_reviews[rid]:
                return "a review changed"
        snap_comments = {
            c.get("id"): c.get("updated_at") for c in self.snapshot.issue_comments or ()
        }
        for comment in comments:
            cid, updated = comment.get("id"), comment.get("updated_at")
            if cid not in snap_comments:
                return "a new comment was posted"
            if not self._parseable(updated) or updated != snap_comments[cid]:
                return "a comment was edited or its updated_at is unreadable"
        return None

    def _preflight(self) -> _Result | None:
        """Re-read the PR immediately before the PUT: the merge pins only the
        head SHA, so a retargeted base or a newly applied halt must be caught
        here. Narrows the window; the post-merge check detects the remainder."""
        try:
            fresh = github.get_pull(self.owner, self.repo, self.pr)
        except Exception:  # noqa: BLE001
            fresh = None
        reason = self._state_change(fresh) or self._activity_change()
        if reason is None:
            return None
        p = self.payload
        p["outcome"] = "MERGE_ABORTED_STATE_CHANGED"
        self.not_verified.append(f"merge aborted before the PUT: {reason}")
        return _Result(
            p,
            1,
            error=f"merge aborted: PR state changed after the decision ({reason})"[:_MESSAGE_LIMIT],
            not_verified=self.not_verified,
        )

    def _verify_base_after_merge(self, result: _Result) -> _Result:
        """Residual-race detector: a merge into a non-default base is recorded
        loudly and handed to a human."""
        try:
            fresh = github.get_pull(self.owner, self.repo, self.pr)
        except Exception as exc:  # noqa: BLE001
            self.not_verified.append(f"post-merge base check not run: {_scrub_exc(exc)}")
            return result
        base = ((fresh or {}).get("base") or {}).get("ref") if isinstance(fresh, dict) else None
        if base is None or base == self.snapshot.default_branch:
            if base is None:
                self.not_verified.append("post-merge base check not run: base.ref unreadable")
            return result
        p = self.payload
        p["outcome"] = "MERGED_BASE_MISMATCH"
        self._best_effort_write(
            "failed",
            self._record(
                am.EVENT_BASE_MISMATCH,
                merged_base_ref=base,
                expected_base_ref=self.snapshot.default_branch,
                merge_commit_sha=p["merge_commit_sha"],
                approver=self.decision.approver,
            ),
        )
        body = (
            "**Executive summary:** The overseer merged this PR on your approval, but the PR's "
            f"base branch is now `{base}`, not the default branch "
            f"`{self.snapshot.default_branch}`; it was retargeted around the merge. Expected "
            "action: **OTHER**: inspect the merge commit "
            f"`{str(p['merge_commit_sha'])[:12]}` and revert or re-land it as needed. Not "
            "verified this run: nothing was skipped this run.\n"
        )
        try:
            comment = github.post_comment(self.owner, self.repo, self.pr, body)
            p["failure_comment_url"] = (comment or {}).get("html_url")
        except Exception as exc:  # noqa: BLE001
            self.not_verified.append(f"base-mismatch comment not posted: {_scrub_exc(exc)}")
        try:
            github.add_issue_label(self.owner, self.repo, self.pr, am.NEEDS_HUMAN)
            p["label_added"] = True
        except Exception as exc:  # noqa: BLE001
            self.not_verified.append(f"needs-human label not added: {_scrub_exc(exc)}")
        return _Result(
            p,
            1,
            error=f"PR merged into {base!r}, not the default branch"[:_MESSAGE_LIMIT],
            not_verified=self.not_verified,
        )

    def merge(self) -> _Result:
        aborted = self._preflight()
        if aborted is not None:
            return aborted
        try:
            response = github.merge_pull(self.owner, self.repo, self.pr, self.head)
        except github.GitHubError as exc:
            status = exc.status_code
            if isinstance(status, int) and 400 <= status <= 499 and status != 401:
                return self._definite_failure(status, _gh_message(exc))
            return self._ambiguous(exc)
        if isinstance(response, dict) and response.get("merged") is True:
            return self._verify_base_after_merge(self._merged(response.get("sha"), recovered=False))
        return self._definite_failure(200, "the response did not confirm the merge")


def _run(args: argparse.Namespace, repo_root: Path, sleep: Callable[[float], None]) -> _Result:
    try:
        config = merge_config.resolve_config(repo_root)
    except merge_config.ConfigError as exc:
        return _fail(_scrub_exc(exc))
    result = _run_with_config(args, repo_root, sleep, config)
    result.config_source = config.config_source
    return result


def _run_with_config(
    args: argparse.Namespace,
    repo_root: Path,
    sleep: Callable[[float], None],
    config: merge_config.MergeConfig,
) -> _Result:
    # R1 identity (REQ-11), before any network call.
    if args.app != "overseer":
        return _refuse("overseer_identity_required")
    bot_login = os.environ.get("HOS_BOT_LOGIN", "")
    if os.environ.get("HOS_OVERSEER_MERGE_TOKEN_MINT_FAILED") == "1":
        # Never fall back to an ambient token on an irreversible path (AR-1 E2).
        return _fail("overseer token mint failed; refusing to merge with an unverified credential")
    if os.environ.get(TOKEN_MINTED_ENV) != "1":
        # Positive proof the wrapper minted this credential (AR-1 E2): an
        # ambient GH_TOKEN plus a self-asserted login is not enough.
        return _refuse("overseer_token_not_minted")
    if not bot_login:
        return _fail("HOS_BOT_LOGIN is unset: the overseer identity cannot be resolved")
    if bot_login.lower() != config.overseer_handle.lower():
        return _refuse("overseer_identity_mismatch")

    try:
        slug = merge_config.resolve_repo_slug(repo_root)
    except merge_config.ConfigError as exc:
        return _fail(_scrub_exc(exc))
    owner, repo = slug.split("/", 1)

    now = datetime.now(timezone.utc)
    try:
        snapshot = am.fetch_snapshot(
            owner, repo, args.pr, config, repo_root=repo_root, now=now, sleep=sleep
        )
        decision = am.decide_merge_on_human_approval(snapshot, config)
    except am.SnapshotReadError as exc:
        decision = am.read_error_decision(exc, scrub=_scrub_secrets)
        snapshot = None

    payload = _blank_payload()
    payload["decision"] = decision.to_dict()
    payload["outcome"] = decision.outcome.name
    if decision.outcome is not am.ApprovalMergeOutcome.MERGE or snapshot is None:
        return _Result(payload, 0, repo=slug)

    merger = _Merger(owner, repo, args.pr, snapshot, decision, repo_root, payload, [])
    problem = merger.write_ahead()
    if problem is not None:
        payload["outcome"] = None
        return _Result(payload, 1, error=problem, repo=slug)
    result = merger.merge()
    result.repo = slug
    return result


def main(
    argv: list[str] | None = None,
    *,
    repo_root: str | Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Parse argv, run, print exactly one JSON record, return the exit code.
    `repo_root` and `sleep` are test-only injections argv cannot reach."""
    resolved_root = Path(repo_root).resolve() if repo_root is not None else _DEFAULT_REPO_ROOT
    try:
        args = _build_parser().parse_args(argv)
    except _UsageExit as exc:
        return exc.code

    try:
        result = _run(args, resolved_root, sleep)
    except Exception as exc:  # noqa: BLE001 - stdout must stay one JSON object
        result = _fail(f"unhandled {type(exc).__name__}: {_scrub_exc(exc)}")

    record = _envelope(
        subcommand=SUBCOMMAND,
        repo=result.repo,
        repo_root=str(resolved_root),
        pr=args.pr,
        config_source=result.config_source,
        app_role=args.app,
        error=result.error,
    )
    record["not_verified"] = result.not_verified
    record.update(result.payload)
    print(json.dumps(record))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
