"""Tests for retry_rescue_logic.py — #1244 ruling item 4 (retry-rescue observability).

Focus: which reruns count as "rescued" (failed once, passed eventually) vs. a
real exhausted failure, the audit-event shape, and the rolling-window
threshold arithmetic that decides "acceptable flakiness" vs. "file a ticket."
"""
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "retry_rescue_logic",
    Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "retry_rescue_logic.py",
)
rr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rr)


# --------------------------------------------------------------------------- #
# rescued_nodeids
# --------------------------------------------------------------------------- #

def test_rescued_nodeids_includes_test_that_reran_then_passed():
    assert rr.rescued_nodeids(["tests/a.py::t1"], ["tests/a.py::t1"]) == ["tests/a.py::t1"]


def test_rescued_nodeids_excludes_test_that_reran_and_never_passed():
    # exhausted both attempts — a real failure, not a rescue
    assert rr.rescued_nodeids(["tests/a.py::t1"], []) == []


def test_rescued_nodeids_excludes_test_that_passed_without_rerunning():
    # passed on the first attempt — no rerun report at all, nothing to rescue
    assert rr.rescued_nodeids([], ["tests/a.py::t1"]) == []


def test_rescued_nodeids_preserves_first_seen_order_and_dedupes():
    reruns = ["tests/a.py::t2", "tests/a.py::t1", "tests/a.py::t2"]
    passed = ["tests/a.py::t1", "tests/a.py::t2"]
    assert rr.rescued_nodeids(reruns, passed) == ["tests/a.py::t2", "tests/a.py::t1"]


def test_rescued_nodeids_handles_mixed_batch():
    reruns = ["tests/a.py::rescued", "tests/a.py::still_failing"]
    passed = ["tests/a.py::rescued", "tests/a.py::unrelated_first_try_pass"]
    assert rr.rescued_nodeids(reruns, passed) == ["tests/a.py::rescued"]


# --------------------------------------------------------------------------- #
# build_retry_rescue_event
# --------------------------------------------------------------------------- #

def test_build_retry_rescue_event_shape_without_pr():
    event = rr.build_retry_rescue_event("tests/a.py::t1", "2026-09-10T20:00:00Z")
    assert event == {
        "event": "test-retry-rescue",
        "test": "tests/a.py::t1",
        "timestamp": "2026-09-10T20:00:00Z",
    }


def test_build_retry_rescue_event_includes_pr_number_when_given():
    event = rr.build_retry_rescue_event("tests/a.py::t1", "2026-09-10T20:00:00Z", pr_number="1244")
    assert event["pr_number"] == "1244"


def test_build_retry_rescue_event_omits_pr_number_when_empty_string():
    event = rr.build_retry_rescue_event("tests/a.py::t1", "2026-09-10T20:00:00Z", pr_number="")
    assert "pr_number" not in event


# --------------------------------------------------------------------------- #
# now_iso / window_start_iso
# --------------------------------------------------------------------------- #

def test_now_iso_uses_fixed_width_grammar():
    fixed = datetime(2026, 9, 10, 20, 33, 58, tzinfo=timezone.utc)
    assert rr.now_iso(fixed) == "2026-09-10T20:33:58Z"


def test_window_start_iso_subtracts_days():
    fixed = datetime(2026, 9, 10, 20, 33, 58, tzinfo=timezone.utc)
    assert rr.window_start_iso(days=14, now=fixed) == "2026-08-27T20:33:58Z"


def test_window_start_iso_default_matches_default_window_days():
    fixed = datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc)
    assert rr.window_start_iso(now=fixed) == rr.window_start_iso(
        days=rr.DEFAULT_WINDOW_DAYS, now=fixed
    )


# --------------------------------------------------------------------------- #
# count_rescues_in_window
# --------------------------------------------------------------------------- #

def _event(test, ts):
    return {"event": "test-retry-rescue", "test": test, "timestamp": ts}


def test_count_rescues_in_window_counts_matching_test_in_window():
    events = [
        _event("tests/a.py::t1", "2026-09-01T00:00:00Z"),
        _event("tests/a.py::t1", "2026-09-05T00:00:00Z"),
    ]
    assert rr.count_rescues_in_window(events, "tests/a.py::t1", "2026-08-27T00:00:00Z") == 2


def test_count_rescues_in_window_excludes_events_before_window_start():
    events = [
        _event("tests/a.py::t1", "2026-08-01T00:00:00Z"),  # before window
        _event("tests/a.py::t1", "2026-09-05T00:00:00Z"),  # in window
    ]
    assert rr.count_rescues_in_window(events, "tests/a.py::t1", "2026-08-27T00:00:00Z") == 1


def test_count_rescues_in_window_excludes_other_tests():
    events = [_event("tests/a.py::other", "2026-09-05T00:00:00Z")]
    assert rr.count_rescues_in_window(events, "tests/a.py::t1", "2026-08-27T00:00:00Z") == 0


def test_count_rescues_in_window_ignores_non_rescue_events():
    events = [{"event": "validator-failure", "test": "tests/a.py::t1", "timestamp": "2026-09-05T00:00:00Z"}]
    assert rr.count_rescues_in_window(events, "tests/a.py::t1", "2026-08-27T00:00:00Z") == 0


def test_count_rescues_in_window_boundary_is_inclusive():
    events = [_event("tests/a.py::t1", "2026-08-27T00:00:00Z")]
    assert rr.count_rescues_in_window(events, "tests/a.py::t1", "2026-08-27T00:00:00Z") == 1


# --------------------------------------------------------------------------- #
# exceeds_threshold
# --------------------------------------------------------------------------- #

def test_exceeds_threshold_false_at_exactly_threshold():
    # ruling text: "more than 3" — exactly 3 is still acceptable flakiness
    assert rr.exceeds_threshold(3, threshold=3) is False


def test_exceeds_threshold_true_above_threshold():
    assert rr.exceeds_threshold(4, threshold=3) is True


def test_exceeds_threshold_false_below_threshold():
    assert rr.exceeds_threshold(1, threshold=3) is False


def test_exceeds_threshold_uses_default_threshold():
    assert rr.exceeds_threshold(rr.DEFAULT_THRESHOLD) is False
    assert rr.exceeds_threshold(rr.DEFAULT_THRESHOLD + 1) is True
