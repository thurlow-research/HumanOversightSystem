#!/usr/bin/env python3
"""
retry_rescue_logic.py — pure logic for pytest retry-rescue observability.

Ruling on #1244 (2026-09-10), final-policy item 4: "Don't let retry-rescues
go silent." pytest-rerunfailures gives each test 2 total attempts
(--reruns 1); a test that fails once then passes on the same commit is
flaky by definition and doesn't block the run — but a silent pass-on-retry
is exactly the kind of drift this repo's testability work (#314, #1167,
#1241) exists to catch mechanically rather than rely on someone noticing.

This module is the pure, testable half of that requirement: given pytest's
own per-outcome report data, decide which tests were rescued by a retry,
build the audit event for one, and evaluate the rolling-window threshold
that promotes "acceptable flakiness" into "file a bug ticket" (more than 3
rescues for the same test within the window). The pytest-facing wiring
(reading `terminalreporter.stats`, writing the event) lives in
tests/conftest.py, which cannot usefully unit-test itself — the decision
logic lives here instead, in keeping with the shell/logic-container
principle (METHODOLOGY.md, "Testability as a code-quality principle").

CI runs on an ephemeral, read-only checkout (`permissions: contents: read`
in tests.yml) and cannot push the resulting audit event back to the repo —
a genuine limitation, not an oversight. The terminal-summary line this
module's output feeds keeps CI visible even where persistence isn't
possible; the audit-log write only durably lands for runs where the working
tree is later committed (worker/overseer local pre-PR test runs). Making
CI-originated events durable, and turning a threshold breach into a filed
bug ticket, needs its own design (state channel, de-dup) and is tracked as
a follow-up rather than folded in here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

EVENT_NAME = "test-retry-rescue"
DEFAULT_THRESHOLD = 3
DEFAULT_WINDOW_DAYS = 14

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


def rescued_nodeids(rerun_nodeids: Iterable[str], passed_nodeids: Iterable[str]) -> list[str]:
    """Return the nodeids that failed at least once (reran) and ultimately passed.

    A nodeid that reran but never appears in `passed_nodeids` exhausted both
    attempts — a real failure, already reflected in pytest's own exit code,
    not a rescue. Order follows first appearance in `rerun_nodeids`;
    duplicates (pytest-rerunfailures can log more than one rerun report for
    the same nodeid under some plugin combinations) are collapsed.
    """
    passed = set(passed_nodeids)
    seen: set[str] = set()
    result: list[str] = []
    for nodeid in rerun_nodeids:
        if nodeid in passed and nodeid not in seen:
            seen.add(nodeid)
            result.append(nodeid)
    return result


def build_retry_rescue_event(
    nodeid: str, timestamp: str, pr_number: str | None = None
) -> dict:
    """Build the audit event dict for one retry-rescue (SPEC-888 event shape)."""
    event: dict = {
        "event": EVENT_NAME,
        "test": nodeid,
        "timestamp": timestamp,
    }
    if pr_number:
        event["pr_number"] = pr_number
    return event


def now_iso(now: datetime | None = None) -> str:
    """Current UTC instant in the audit-log's ISO grammar."""
    return (now or datetime.now(timezone.utc)).strftime(_TS_FMT)


def window_start_iso(days: int = DEFAULT_WINDOW_DAYS, now: datetime | None = None) -> str:
    """Start of a rolling `days`-day window ending now, in the audit-log's ISO grammar."""
    reference = now or datetime.now(timezone.utc)
    return (reference - timedelta(days=days)).strftime(_TS_FMT)


def count_rescues_in_window(events: Iterable[dict], nodeid: str, window_start: str) -> int:
    """Count `test-retry-rescue` events for `nodeid` with timestamp >= window_start.

    Timestamps are compared lexically. That's valid only for a fixed-width,
    zero-padded ISO-8601 form ("YYYY-MM-DDTHHMMSSZ" or "YYYY-MM-DDTHH:MM:SSZ")
    — callers must pass a consistent form for both `events` and `window_start`.
    """
    count = 0
    for event in events:
        if event.get("event") != EVENT_NAME:
            continue
        if event.get("test") != nodeid:
            continue
        if event.get("timestamp", "") >= window_start:
            count += 1
    return count


def exceeds_threshold(count: int, threshold: int = DEFAULT_THRESHOLD) -> bool:
    """True once a test's rescue count in the window exceeds the threshold.

    Per the #1244 ruling: "more than 3 retries across a rolling window" —
    a count of exactly `threshold` is still acceptable flakiness.
    """
    return count > threshold
