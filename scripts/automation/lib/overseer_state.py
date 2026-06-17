"""
overseer_state.py — Deterministic state helpers for the HOS oversight loop.

The overseer agent (overseer.md) owns all GitHub and cron tool calls.
This module owns only JSON state mutation and the pure predicates — keeping
safety-relevant predicates (stale detection, new-PR detection, dedup) under
unit test rather than in prompt prose alone.

State files live under .claudetmp/ per the SPEC decision (§0 substrate choice):
  .claudetmp/oversight-state.json   — per-tick PR queue state
  .claudetmp/oversight-schedule.json — stop-time + cron job tag

Stop records land under .ai-local/hos-automation/ (S1-S5 gap-tracking):
  .ai-local/hos-automation/overseer-stop-{ts}.json

PR-state cache (per-PR progress tracking, per-PR in-progress guard):
  .ai-local/hos-automation/pr-state-{pr_number}.json

Stdlib only — no third-party imports.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


# ── Time helpers ──────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 UTC Z timestamp; return None on failure."""
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ── Atomic write ──────────────────────────────────────────────────────────────

def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON to `path` atomically (tmp + rename) so a crash mid-write
    leaves the prior state intact rather than a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-overseer-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ── Oversight-state.json (per-tick PR queue) ─────────────────────────────────

_STATE_FILE = ".claudetmp/oversight-state.json"


def read_state(path: str = _STATE_FILE) -> dict:
    """Read the oversight state file; return {} if absent or unreadable."""
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_state(path: str = _STATE_FILE, state: dict = None) -> None:
    """Write the oversight state file atomically."""
    if state is None:
        state = {}
    _atomic_write(Path(path), state)


def upsert_pr(
    state: dict,
    pr_number: int,
    *,
    sign_off_status: str,
    second_review_status: str,
    now_iso: Optional[str] = None,
) -> dict:
    """
    Upsert a PR entry in the state dict.

    Sets first_seen on first sight; updates last_checked on every call;
    tracks status_changed_at so stale_prs() can detect 48h without movement.
    Returns the mutated state dict (mutated in place AND returned for chaining).
    """
    if now_iso is None:
        now_iso = _now_iso()
    prs = state.setdefault("prs", {})
    key = str(pr_number)
    entry = prs.get(key, {})

    if not entry:
        entry["first_seen"] = now_iso

    # Track status-change timestamp for stale detection.
    prior_sign_off = entry.get("sign_off_status")
    if prior_sign_off != sign_off_status:
        entry["status_changed_at"] = now_iso

    entry["pr_number"] = pr_number
    entry["last_checked"] = now_iso
    entry["sign_off_status"] = sign_off_status
    entry["second_review_status"] = second_review_status
    prs[key] = entry
    state["last_tick"] = now_iso
    state["queue"] = "non-empty"
    return state


def reconcile(state: dict, open_pr_numbers: list[int]) -> dict:
    """
    Remove entries from state["prs"] whose PR number is not in open_pr_numbers.
    Called once per tick after discovering the current open-PR set.
    Returns the mutated state dict.
    """
    open_keys = {str(n) for n in open_pr_numbers}
    prs = state.get("prs", {})
    closed = [k for k in prs if k not in open_keys]
    for k in closed:
        del prs[k]
    if not prs:
        state["queue"] = "empty"
    return state


def stale_prs(
    state: dict,
    now_iso: Optional[str] = None,
    threshold_hours: int = 48,
) -> list[int]:
    """
    Return PR numbers whose sign_off_status has not changed in threshold_hours.

    A PR is stale when `now - status_changed_at >= threshold_hours` AND the
    `escalated` flag is not True (avoid re-escalating on every tick).
    """
    if now_iso is None:
        now_iso = _now_iso()
    now_dt = _parse_iso(now_iso)
    if now_dt is None:
        return []
    threshold = timedelta(hours=threshold_hours)
    stale: list[int] = []
    for entry in state.get("prs", {}).values():
        if entry.get("escalated"):
            continue
        changed_at = _parse_iso(entry.get("status_changed_at", ""))
        if changed_at is None:
            # No movement ever recorded for this PR — treat first_seen as the
            # change epoch so a brand-new PR is never immediately flagged stale.
            changed_at = _parse_iso(entry.get("first_seen", now_iso))
        if changed_at is not None and (now_dt - changed_at) >= threshold:
            stale.append(entry["pr_number"])
    return stale


def is_new_pr(prior_state: dict, pr_number: int) -> bool:
    """Return True if pr_number is NOT a key in prior_state["prs"]."""
    return str(pr_number) not in prior_state.get("prs", {})


# ── Oversight-schedule.json (stop-time + cron job tag) ───────────────────────

_SCHEDULE_FILE = ".claudetmp/oversight-schedule.json"


def read_schedule(path: str = _SCHEDULE_FILE) -> dict:
    """Read the schedule file; return {} if absent or unreadable."""
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def write_schedule(
    path: str = _SCHEDULE_FILE,
    *,
    stop_at: str,
    created_at: str,
    loop_job_tag: str,
) -> None:
    """Write the schedule file atomically.

    Per the design invariant, stop_at is persisted BEFORE the cron job exists
    (the caller writes with loop_job_tag="" first, then calls again with the
    real ID once CronCreate returns).
    """
    _atomic_write(
        Path(path),
        {"stop_at": stop_at, "created_at": created_at, "loop_job_tag": loop_job_tag},
    )


def clear_schedule(path: str = _SCHEDULE_FILE) -> None:
    """Clear the schedule file (stop intent lapsed or loop stopped)."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


# ── Stop record (.ai-local/hos-automation/) ──────────────────────────────────

def record_stop(reason: str, repo_root: str = ".") -> None:
    """
    Write a durable stop record under .ai-local/hos-automation/.

    Called by the overseer when it executes /stop-oversight-loop so the stop
    decision is auditable even after the schedule file is cleared.
    """
    ts = _now_iso()
    safe_ts = ts.replace(":", "-")
    dest = Path(repo_root) / ".ai-local" / "hos-automation" / f"overseer-stop-{safe_ts}.json"
    _atomic_write(dest, {"reason": reason, "stopped_at": ts})


# ── Per-PR state cache (.ai-local/hos-automation/) ───────────────────────────
# Used by the per-PR in-progress guard (task brief S5 / OQ-8 optional status
# field) and by the 20-minute duplicate-job guard.

_VALID_PR_STATUSES = frozenset({"reviewing", "waiting", "bounced", "merged"})


def update_pr_state(
    pr_number: int,
    cid: str,
    status: str,
    repo_root: str = ".",
) -> None:
    """
    Write or update the per-PR state cache entry.

    pr_number: the GitHub PR number
    cid: the correlation ID (e.g. the overseer's run ID) for tracing
    status: one of reviewing | waiting | bounced | merged
    repo_root: path to the repo root (default CWD)
    """
    if status not in _VALID_PR_STATUSES:
        raise ValueError(
            f"invalid status {status!r} — must be one of {sorted(_VALID_PR_STATUSES)}"
        )
    dest = (
        Path(repo_root) / ".ai-local" / "hos-automation" / f"pr-state-{pr_number}.json"
    )
    _atomic_write(dest, {
        "pr": pr_number,
        "cid": cid,
        "last_checked": _now_iso(),
        "status": status,
    })


def is_duplicate_in_progress(
    pr_number: int,
    repo_root: str = ".",
    timeout_minutes: int = 20,
) -> bool:
    """
    Return True if a concurrent overseer instance is already processing this PR.

    Reads pr-state-{pr_number}.json; returns True only if status == "reviewing"
    AND last_checked is within timeout_minutes of now.  Returns False when the
    file is absent, unreadable, or the status is stale (the prior instance is
    presumed dead or done).
    """
    path = (
        Path(repo_root) / ".ai-local" / "hos-automation" / f"pr-state-{pr_number}.json"
    )
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False

    if data.get("status") != "reviewing":
        return False

    last_checked = _parse_iso(data.get("last_checked", ""))
    if last_checked is None:
        return False
    age = datetime.now(timezone.utc) - last_checked
    return age.total_seconds() < timeout_minutes * 60
