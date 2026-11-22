"""Self-test of the per-test stall guard (ADR-2304 2j, C6-7 b).

The guard owns `SIGALRM` and `ITIMER_REAL`, so this module must not itself be guarded. Each test
drives the fixture's generator directly, with `STALL_SECONDS` patched down to 0.05 s.
"""

import re
import signal
import time

import pytest

from tests.framework import _stall_guard

GUARD = _stall_guard.stalled_test_fails_fast._get_wrapped_function()


@pytest.fixture(autouse=True)
def drop_tmp_path_link_at_teardown(request, tmp_path):
    """Remove this test's `<name>current` link from the session's base temp once the test passed.

    pytest deletes a passing test's tmp_path itself (retention policy "failed") but leaves the
    link to it, and every such link is allocated space in the session's temp budget. A failed test
    keeps both the directory and its link, for diagnosis.
    """
    failed_before = request.session.testsfailed
    yield
    if request.session.testsfailed == failed_before:
        link = tmp_path.parent / (re.sub(r"\d+$", "", tmp_path.name) + "current")
        if link.is_symlink() and link.resolve() == tmp_path.resolve():
            link.unlink()


@pytest.fixture(autouse=True)
def short_stall_and_clean_signal_state(monkeypatch):
    """Patch the limit down, and put the signal state back whatever a test did to it."""
    monkeypatch.setattr(_stall_guard, "STALL_SECONDS", 0.05)
    handler = signal.getsignal(signal.SIGALRM)
    signal.setitimer(signal.ITIMER_REAL, 0)
    yield
    signal.setitimer(signal.ITIMER_REAL, 0)
    signal.signal(signal.SIGALRM, handler)


def _outer_handler(signum, frame):
    raise AssertionError("outer handler must not run")


def test_stalled_test_is_failed_by_the_guard_with_its_message():
    guard = GUARD()
    next(guard)
    with pytest.raises(AssertionError, match=r"made no progress for 0\.05 s"):
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            pass
    guard.close()


def test_fast_test_passes_under_the_guard():
    guard = GUARD()
    next(guard)
    result = sum(range(100))
    with pytest.raises(StopIteration):
        next(guard)
    assert result == 4950


def test_handler_and_timer_are_restored_after_the_guard_exits():
    signal.signal(signal.SIGALRM, _outer_handler)
    guard = GUARD()
    next(guard)
    assert signal.getsignal(signal.SIGALRM) is _stall_guard._stalled
    assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
    with pytest.raises(StopIteration):
        next(guard)
    assert signal.getsignal(signal.SIGALRM) is _outer_handler
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_guard_restores_state_when_the_test_body_raised():
    signal.signal(signal.SIGALRM, _outer_handler)
    guard = GUARD()
    next(guard)
    with pytest.raises(ValueError, match="boom"):
        guard.throw(ValueError("boom"))
    assert signal.getsignal(signal.SIGALRM) is _outer_handler
    assert signal.getitimer(signal.ITIMER_REAL) == (0.0, 0.0)


def test_already_armed_outer_timer_makes_the_guard_fail_loudly_and_stays_armed():
    signal.signal(signal.SIGALRM, _outer_handler)
    signal.setitimer(signal.ITIMER_REAL, 30.0)
    guard = GUARD()
    with pytest.raises(RuntimeError, match="already armed"):
        next(guard)
    assert signal.getsignal(signal.SIGALRM) is _outer_handler
    remaining, _ = signal.getitimer(signal.ITIMER_REAL)
    assert 0 < remaining <= 30.0
