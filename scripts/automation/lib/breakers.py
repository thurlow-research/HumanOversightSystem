"""
Circuit breakers and safety nets for the HOS automation loop (T13, §11).

Prevents runaway automation:
  - Per-issue failure cap: stop retrying a poison-pill task
  - Blast-radius window enforcer: cap PRs/issues/files per rolling window
  - Rate-limit backoff: honor GitHub X-RateLimit-* headers
  - Max runtime: per-task worker hard ceiling (4h)
  - Dead-man's switch: page human if no healthy probe in 6h
  - Shadow mode: default for newly-onboarded customers (propose-only, no model)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from scripts.automation.lib.ledger import (
    _iter_run_records,
    sum_window_blast_radius,
)

# ---------------------------------------------------------------------------
# Failure cap (per-issue)
# ---------------------------------------------------------------------------

_SOFT_STATE_DIR = Path(".ai-local") / "hos-automation"
_FAILURE_CAP_FILE = "failure-caps.json"


def _load_failure_caps(repo_root: str = ".") -> dict:
    path = Path(repo_root) / _SOFT_STATE_DIR / _FAILURE_CAP_FILE
    if not path.is_file():
        return {}
    try:
        with path.open() as fh:
            return json.load(fh)
    except Exception:
        return {}


def _save_failure_caps(caps: dict, repo_root: str = ".") -> None:
    path = Path(repo_root) / _SOFT_STATE_DIR / _FAILURE_CAP_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        json.dump(caps, fh)


def record_task_failure(cid: str, repo_root: str = ".") -> int:
    """Increment failure count for a cid. Returns new count."""
    caps = _load_failure_caps(repo_root)
    caps[cid] = caps.get(cid, 0) + 1
    _save_failure_caps(caps, repo_root)
    return caps[cid]


def failure_count(cid: str, repo_root: str = ".") -> int:
    return _load_failure_caps(repo_root).get(cid, 0)


def is_poisoned(cid: str, max_failures: int = 3, repo_root: str = ".") -> bool:
    """Return True if this task has failed too many times and should be abandoned."""
    return failure_count(cid, repo_root) >= max_failures


# ---------------------------------------------------------------------------
# Blast-radius window enforcer (R11.2)
# ---------------------------------------------------------------------------

def blast_radius_ok(
    customer: str,
    caps: Optional[dict] = None,
    window_hours: float = 24.0,
    repo_root: str = ".",
) -> tuple[bool, str]:
    """
    Check whether the rolling blast-radius window is under cap.

    Returns (ok, reason). If not ok, the caller should not claim new work.
    """
    defaults = {"prs": 5, "issues": 10, "files": 25}
    caps = caps or defaults

    totals = sum_window_blast_radius(customer, window_hours, repo_root)

    for key, cap in caps.items():
        used = totals.get(key, 0)
        if used >= cap:
            return False, f"Blast-radius cap reached: {key}={used}/{cap} in last {window_hours}h"

    return True, "Within blast-radius caps"


# ---------------------------------------------------------------------------
# Rate-limit backoff
# ---------------------------------------------------------------------------

def backoff_for_rate_limit(
    remaining: int,
    reset_epoch: Optional[int] = None,
    low_water_mark: int = 100,
) -> None:
    """
    Sleep until GitHub rate limit resets if remaining is critically low.

    remaining: X-RateLimit-Remaining header value
    reset_epoch: X-RateLimit-Reset header value (Unix timestamp)
    """
    if remaining > low_water_mark:
        return

    if reset_epoch is not None:
        wait = max(0, reset_epoch - int(time.time()) + 5)  # +5s buffer
    else:
        wait = 60  # Default: wait 60s if we don't know the reset time

    if wait > 0:
        time.sleep(wait)


# ---------------------------------------------------------------------------
# Max-runtime enforcer
# ---------------------------------------------------------------------------

def runtime_exceeded(started_iso: str, max_runtime_hours: float = 4.0) -> bool:
    """Return True if the task has been running longer than max_runtime_hours."""
    try:
        started = datetime.fromisoformat(started_iso.replace("Z", "+00:00"))
        elapsed = datetime.now(timezone.utc) - started
        return elapsed > timedelta(hours=max_runtime_hours)
    except (ValueError, TypeError):
        return True  # Fail-closed: can't parse start time → assume exceeded


# ---------------------------------------------------------------------------
# Dead-man's switch (R11.5)
# ---------------------------------------------------------------------------

_DEADMAN_FILE = "deadman-last-probe.json"


def record_probe_completion(customer: str, repo_root: str = ".") -> None:
    """Called at the end of each healthy probe cycle (R11.5 probe-completion event)."""
    path = Path(repo_root) / _SOFT_STATE_DIR / _DEADMAN_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if path.is_file():
        try:
            with path.open() as fh:
                state = json.load(fh)
        except Exception:
            pass
    state[customer] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with path.open("w") as fh:
        json.dump(state, fh)


def dead_man_triggered(
    customer: str,
    threshold_hours: float = 6.0,
    repo_root: str = ".",
) -> bool:
    """
    Return True if no probe-completion event has been recorded in threshold_hours.

    The dead-man check MUST be run by an EXTERNAL process (not the loop itself —
    a dead loop cannot report its own death). This function provides the check;
    the caller is responsible for paging a human when it returns True.
    """
    path = Path(repo_root) / _SOFT_STATE_DIR / _DEADMAN_FILE
    if not path.is_file():
        return True  # Never probed → dead-man fires immediately

    try:
        with path.open() as fh:
            state = json.load(fh)
        last_str = state.get(customer)
        if not last_str:
            return True
        last = datetime.fromisoformat(last_str.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - last > timedelta(hours=threshold_hours)
    except Exception:
        return True  # Fail-closed


# ---------------------------------------------------------------------------
# Shadow mode (R11.7 — default for new customers)
# ---------------------------------------------------------------------------

def is_shadow_mode(mode: str) -> bool:
    """
    Shadow mode = propose-only (no auto-merge, no model-invoked mutations).

    New customers default to shadow mode; the operator must explicitly graduate
    them to autonomous. This is the safest default.
    """
    return mode != "autonomous"
