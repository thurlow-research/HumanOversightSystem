"""
Token-free "is there work?" probe across customer repos (T4, §10, R10.1b).

Probe is cheap: a few GitHub REST/GraphQL calls per repo, NO model invocation.
Cadence governs API quota spend; the budget gate governs token spend — two
independent knobs. The model only wakes when the probe finds work.

Key constraints:
  - NEVER calls the Search API on the hot path (R10.1b)
  - Probe runs ONLY after activation + hos-halt pass (gate ordering, §11)
  - Per-customer API-call quota: default 300 calls / rolling 1h (O15)
  - Round-robin + staggered start times across repos (R12.2, O15)
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from scripts.automation.lib.github import (
    GitHubError,
    list_issue_comments,
    _run_gh,
)
from scripts.automation.lib.ledger import sum_window_blast_radius

# ---------------------------------------------------------------------------
# Cadence state (soft state, layer 2b, .ai-local/hos-automation/)
# ---------------------------------------------------------------------------

_SOFT_STATE_DIR = Path(".ai-local") / "hos-automation"
_CADENCE_FILE = "cadence-state.json"
_API_BUDGET_FILE = "api-budget.json"

# Blast-radius window caps (R11.2)
BLAST_CAPS = {"prs": 5, "issues": 10, "files": 25}

# Default per-customer API budget (O15 resolution)
DEFAULT_API_BUDGET_PER_HOUR = 300
API_WINDOW_HOURS = 1.0

# Priority-pin max duration before escalating to needs-human (R10.4)
PIN_MAX_HOURS = 72


@dataclass
class CadenceState:
    backoff_level: int = 0
    last_poll: Optional[str] = None
    next_due: Optional[str] = None
    pinned: bool = False
    pin_reason: Optional[str] = None
    pin_since: Optional[str] = None


@dataclass
class WorkCandidate:
    """A single probe-discovered work item."""
    owner: str
    repo: str
    issue_number: int
    issue_url: str
    labels: list[str] = field(default_factory=list)
    actor: Optional[str] = None  # the actor who applied hos-coordination label


# ---------------------------------------------------------------------------
# API quota tracking (soft state)
# ---------------------------------------------------------------------------

def _load_api_budget(repo_id: str, repo_root: str = ".") -> dict:
    path = Path(repo_root) / _SOFT_STATE_DIR / _API_BUDGET_FILE
    if not path.is_file():
        return {}
    try:
        with path.open() as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_api_budget(state: dict, repo_id: str, repo_root: str = ".") -> None:
    path = Path(repo_root) / _SOFT_STATE_DIR / _API_BUDGET_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        json.dump(state, fh)


def _api_calls_used(repo_id: str, repo_root: str = ".") -> int:
    state = _load_api_budget(repo_id, repo_root)
    entry = state.get(repo_id, {})
    window_start_str = entry.get("window_start")
    if not window_start_str:
        return 0
    try:
        window_start = datetime.fromisoformat(window_start_str.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if datetime.now(timezone.utc) - window_start > timedelta(hours=API_WINDOW_HOURS):
        return 0  # Window expired
    return int(entry.get("calls_used", 0))


def _record_api_call(repo_id: str, count: int = 1, repo_root: str = ".") -> None:
    state = _load_api_budget(repo_id, repo_root)
    entry = state.get(repo_id, {})
    now = datetime.now(timezone.utc)
    window_start_str = entry.get("window_start")
    if window_start_str:
        try:
            window_start = datetime.fromisoformat(window_start_str.replace("Z", "+00:00"))
            if now - window_start > timedelta(hours=API_WINDOW_HOURS):
                entry = {}  # Reset window
        except ValueError:
            entry = {}
    if not entry:
        entry = {"window_start": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "calls_used": 0}
    entry["calls_used"] = int(entry.get("calls_used", 0)) + count
    state[repo_id] = entry
    _save_api_budget(state, repo_id, repo_root)


# ---------------------------------------------------------------------------
# Cadence helpers
# ---------------------------------------------------------------------------

def _load_cadence(repo_id: str, repo_root: str = ".") -> CadenceState:
    path = Path(repo_root) / _SOFT_STATE_DIR / _CADENCE_FILE
    if not path.is_file():
        return CadenceState()
    try:
        with path.open() as fh:
            data = json.load(fh)
        entry = data.get(repo_id, {})
        return CadenceState(
            backoff_level=int(entry.get("backoff_level", 0)),
            last_poll=entry.get("last_poll"),
            next_due=entry.get("next_due"),
            pinned=bool(entry.get("pinned", False)),
            pin_reason=entry.get("pin_reason"),
            pin_since=entry.get("pin_since"),
        )
    except Exception:
        return CadenceState()


def _save_cadence(repo_id: str, state: CadenceState, repo_root: str = ".") -> None:
    path = Path(repo_root) / _SOFT_STATE_DIR / _CADENCE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open() as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    data[repo_id] = {
        "backoff_level": state.backoff_level,
        "last_poll": state.last_poll,
        "next_due": state.next_due,
        "pinned": state.pinned,
        "pin_reason": state.pin_reason,
        "pin_since": state.pin_since,
    }
    with path.open("w") as fh:
        json.dump(data, fh)


def _is_due(state: CadenceState) -> bool:
    """Is it time to probe this repo?"""
    if state.pinned:
        return True  # Priority-pinned repos always probe
    if not state.next_due:
        return True  # First probe
    try:
        next_due = datetime.fromisoformat(state.next_due.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) >= next_due
    except ValueError:
        return True


def _compute_next_due(backoff_level: int, floor_minutes: int, ceiling_hours: int) -> str:
    interval_minutes = min(
        floor_minutes * (2 ** backoff_level),
        ceiling_hours * 60,
    )
    next_due = datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)
    return next_due.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Coordination-label actor verification (R4.1.4)
# ---------------------------------------------------------------------------

def _verify_label_actor(
    owner: str,
    repo: str,
    issue_number: int,
    label_name: str,
    requester_allowlist: list[str],
) -> Optional[str]:
    """
    Verify the actor who applied `label_name` is in the requester allowlist.

    Uses REST-by-id (issue events). Returns the actor login on success, None if
    the actor is not in the allowlist or the event cannot be verified.
    """
    try:
        events = _run_gh([
            f"/repos/{owner}/{repo}/issues/{issue_number}/events"
            f"?per_page=100"
        ])
    except GitHubError:
        return None
    if not isinstance(events, list):
        return None

    # Find the most recent 'labeled' event for this label
    for event in reversed(events):
        if event.get("event") != "labeled":
            continue
        if event.get("label", {}).get("name") != label_name:
            continue
        actor = event.get("actor", {}).get("login", "")
        if actor and actor.lower() in {a.lower() for a in requester_allowlist}:
            return actor
        return None  # Found the event but actor not allowed

    return None  # Label event not found


# ---------------------------------------------------------------------------
# Main probe function
# ---------------------------------------------------------------------------

def probe_repo(
    owner: str,
    repo: str,
    repo_id: str,
    requester_allowlist: list[str],
    floor_minutes: int = 15,
    ceiling_hours: int = 24,
    api_budget: int = DEFAULT_API_BUDGET_PER_HOUR,
    customer: str = "",
    repo_root: str = ".",
) -> list[WorkCandidate]:
    """
    Probe a single repo for work candidates. Returns a list of WorkCandidate items.

    Never calls Search API. Respects per-customer API quota.
    Blast-radius pre-check runs before any API call (cheap local read).
    """
    # Blast-radius pre-check (R11.2) — read the rolling-24h ledger
    if customer:
        blast = sum_window_blast_radius(customer, window_hours=24.0, repo_root=repo_root)
        if (blast["prs"] >= BLAST_CAPS["prs"]
                or blast["issues"] >= BLAST_CAPS["issues"]
                or blast["files"] >= BLAST_CAPS["files"]):
            return []  # Window cap reached; no new claims this cycle

    # API quota gate (R12.1, O15)
    if _api_calls_used(repo_id, repo_root) >= api_budget:
        return []  # Quota exhausted for this window

    # Cadence check
    state = _load_cadence(repo_id, repo_root)
    if not _is_due(state):
        return []

    # Priority-pin expiry check (R10.4)
    if state.pinned and state.pin_since:
        try:
            pin_since = datetime.fromisoformat(state.pin_since.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) - pin_since > timedelta(hours=PIN_MAX_HOURS):
                # Pin expired — escalate and release
                state.pinned = False
                state.pin_reason = None
                state.pin_since = None
        except ValueError:
            pass

    candidates: list[WorkCandidate] = []

    # REST probe: open issues labeled hos-coordination updated recently
    since = state.last_poll or ""
    query = f"/repos/{owner}/{repo}/issues?state=open&labels=hos-coordination&per_page=50"
    if since:
        query += f"&since={since}"

    try:
        issues = _run_gh([query]) or []
        _record_api_call(repo_id, count=1, repo_root=repo_root)
    except GitHubError:
        return candidates

    activity_found = bool(issues)

    for issue in issues:
        issue_number = issue.get("number")
        if not issue_number:
            continue

        # Verify the hos-coordination label was applied by an allowed actor (R4.1.4)
        actor = _verify_label_actor(
            owner, repo, issue_number,
            "hos-coordination", requester_allowlist,
        )
        _record_api_call(repo_id, count=1, repo_root=repo_root)

        if actor is None:
            continue  # Label applied by non-allowlisted actor — skip

        labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]
        candidates.append(WorkCandidate(
            owner=owner,
            repo=repo,
            issue_number=issue_number,
            issue_url=f"https://github.com/{owner}/{repo}/issues/{issue_number}",
            labels=labels,
            actor=actor,
        ))

    # Update cadence state
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if activity_found:
        state.backoff_level = 0
        if state.pinned is False:
            pass  # Reset already handled
    else:
        state.backoff_level = min(state.backoff_level + 1, 10)

    state.last_poll = now_iso
    state.next_due = _compute_next_due(state.backoff_level, floor_minutes, ceiling_hours)
    _save_cadence(repo_id, state, repo_root)

    return candidates
