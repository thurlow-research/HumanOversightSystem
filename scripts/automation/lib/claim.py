"""
Claim-then-verify with UUIDv4 instance-id and heartbeat (T8, §7, ADR-2 backstop).

The claim mechanism is a CONTENTION REDUCER, not mutual exclusion.
M1 correctness (zero duplicate work) lives in correlation.py (cid keystone).
Two instances may both claim and verify — cid-keyed artifact naming ensures
that a double-dispatch produces one artifact (second push is a no-op).

Claim protocol:
  1. Post a claim envelope to the issue (correlation.py cid line in body)
  2. Jitter sleep, then re-read the issue's comments (REST-by-id)
  3. Lowest instance-id among valid claims wins
  4. Loser deletes any artifacts it created and releases the claim
  5. Winner heartbeats every ≤15m, rechecking activation + hos-halt at each beat
"""

from __future__ import annotations

import time
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from scripts.automation.lib.correlation import (
    ENVELOPE_CID_MARKER,
    envelope_cid_line,
)
from scripts.automation.lib.github import (
    GitHubError,
    list_issue_comments,
    _run_gh,
)

# Claim timeout: stale claim is re-claimable after this (R7.3)
CLAIM_TIMEOUT_MINUTES = 45

# Heartbeat interval (must be ≤ claim.heartbeat from config, default 15m)
HEARTBEAT_INTERVAL_SECONDS = 900  # 15 minutes

# First-beat window: new claim is valid for this long before heartbeat is required
FIRST_BEAT_WINDOW_SECONDS = 120  # 2 minutes

# Claim-then-verify jitter range
CLAIM_VERIFY_JITTER_MIN = 5
CLAIM_VERIFY_JITTER_MAX = 30


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ClaimResult:
    won: bool
    instance_id: str
    reason: str


@dataclass
class HeartbeatResult:
    should_continue: bool
    reason: str


# ---------------------------------------------------------------------------
# Claim envelope helpers
# ---------------------------------------------------------------------------

_CLAIM_MARKER = "hos-claim"
_INSTANCE_MARKER = "instance-id:"


def _build_claim_body(cid: str, instance_id: str, who: str) -> str:
    """Build the claim comment body."""
    return (
        f"---hos-envelope\n"
        f"type: claim\n"
        f"correlation-id: {cid}\n"
        f"from: {who}\n"
        f"instance-id: {instance_id}\n"
        f"claimed-at: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"protocol-version: \"1.0\"\n"
        f"---\n\n"
        f"{envelope_cid_line(cid)}\n"
        f"🤖 [{who}] Claimed for autonomous processing."
    )


def _build_heartbeat_body(cid: str, instance_id: str, who: str, status: str = "in-progress") -> str:
    return (
        f"---hos-envelope\n"
        f"type: heartbeat\n"
        f"correlation-id: {cid}\n"
        f"from: {who}\n"
        f"instance-id: {instance_id}\n"
        f"status: {status}\n"
        f"heartbeat-at: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"protocol-version: \"1.0\"\n"
        f"---"
    )


def _extract_claims(
    comments: list[dict],
    cid: str,
) -> list[tuple[str, str]]:
    """
    Extract (instance_id, claimed_at) from claim envelopes for the given cid.

    Returns only valid, non-stale claims.
    Stale = last heartbeat / claimed-at older than CLAIM_TIMEOUT_MINUTES.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CLAIM_TIMEOUT_MINUTES)
    claims = []

    for comment in comments:
        body = comment.get("body", "")
        if envelope_cid_line(cid) not in body and f"correlation-id: {cid}" not in body:
            continue
        if "type: claim" not in body and "type: heartbeat" not in body:
            continue

        # Extract instance-id
        instance_id = None
        for line in body.splitlines():
            if line.strip().startswith("instance-id:"):
                instance_id = line.split(":", 1)[1].strip()
                break
        if not instance_id:
            continue

        # Check freshness: use the comment's updated_at
        updated_at_str = comment.get("updated_at", "")
        try:
            updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        if updated_at < cutoff:
            continue  # Stale claim

        claims.append((instance_id, updated_at_str))

    return claims


# ---------------------------------------------------------------------------
# Claim-then-verify
# ---------------------------------------------------------------------------

def claim(
    owner: str,
    repo: str,
    issue_number: int,
    cid: str,
    who: str,
    repo_root: str = ".",
) -> ClaimResult:
    """
    Attempt to claim a work item via claim-then-verify.

    Returns ClaimResult(won=True) if this instance wins the claim.
    Does NOT delete losing artifacts — caller (correlation.py) handles cleanup.

    Read-your-writes: claim re-verify uses REST-by-id (list_issue_comments),
    never the Search API.
    """
    instance_id = str(uuid.uuid4())

    # Step 1: post claim envelope
    claim_body = _build_claim_body(cid, instance_id, who)
    try:
        _run_gh([
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            "--method", "POST",
            "--field", f"body={claim_body}",
        ])
    except GitHubError as exc:
        return ClaimResult(won=False, instance_id=instance_id, reason=f"Failed to post claim: {exc}")

    # Step 2: jitter then re-read
    jitter = random.uniform(CLAIM_VERIFY_JITTER_MIN, CLAIM_VERIFY_JITTER_MAX)
    time.sleep(jitter)

    # Step 3: re-read claims (REST-by-id)
    try:
        comments = list_issue_comments(owner, repo, issue_number)
    except GitHubError as exc:
        return ClaimResult(won=False, instance_id=instance_id, reason=f"Failed to re-read claims: {exc}")

    active_claims = _extract_claims(comments, cid)

    if not active_claims:
        return ClaimResult(won=False, instance_id=instance_id, reason="No active claims found after posting")

    # Step 4: lowest instance-id wins (deterministic tiebreak)
    all_ids = sorted([iid for iid, _ in active_claims])
    winner = all_ids[0]

    if winner == instance_id:
        return ClaimResult(won=True, instance_id=instance_id, reason="Won claim (lowest instance-id)")

    return ClaimResult(won=False, instance_id=instance_id, reason=f"Lost claim to {winner}")


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

def heartbeat(
    owner: str,
    repo: str,
    issue_number: int,
    cid: str,
    instance_id: str,
    who: str,
    check_activation_fn=None,
    check_halt_fn=None,
    status: str = "in-progress",
) -> HeartbeatResult:
    """
    Post a heartbeat envelope and recheck activation + hos-halt.

    Called every ≤15m by the per-task worker. Returns HeartbeatResult indicating
    whether the worker should continue. Self-terminates if activation or halt
    conditions fail.

    check_activation_fn: callable() -> bool  (activation.check_activation)
    check_halt_fn: callable() -> bool         (returns True if halt file present)
    """
    # Recheck activation file
    if check_activation_fn is not None:
        if not check_activation_fn():
            return HeartbeatResult(should_continue=False, reason="Activation file absent or mismatched — self-terminating")

    # Recheck hos-halt
    if check_halt_fn is not None:
        if check_halt_fn():
            return HeartbeatResult(should_continue=False, reason="hos-halt file detected — self-terminating")

    # Post heartbeat envelope
    beat_body = _build_heartbeat_body(cid, instance_id, who, status)
    try:
        _run_gh([
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            "--method", "POST",
            "--field", f"body={beat_body}",
        ])
    except GitHubError as exc:
        # Non-fatal — heartbeat failure doesn't stop the worker
        pass

    return HeartbeatResult(should_continue=True, reason="Heartbeat posted")


# ---------------------------------------------------------------------------
# Terminal release
# ---------------------------------------------------------------------------

def release_claim(
    owner: str,
    repo: str,
    issue_number: int,
    cid: str,
    instance_id: str,
    who: str,
    reason: str = "completed",
) -> None:
    """
    Post a terminal claim-release envelope. Removes the hos-claimed label.

    Best-effort — failure does not raise (claim will age out naturally).
    """
    release_body = _build_heartbeat_body(cid, instance_id, who, status=f"terminal:{reason}")

    try:
        _run_gh([
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            "--method", "POST",
            "--field", f"body={release_body}",
        ])
        # Remove hos-claimed label
        _run_gh([
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels/hos-claimed",
            "--method", "DELETE",
        ])
    except GitHubError:
        pass  # Best-effort
