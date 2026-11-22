"""A per-test stall guard for the pure-function modules of the new-code gate (ADR-2304 2j, C6-3 b).

A mutant that turns a `while` loop into one that never advances does not fail the first test that
reaches it: that test hangs, and mutmut gives up on it only after `(estimated seconds + 1) * 15`
CPU-seconds, an estimate summed over every test that reaches the function (225 s for
`unquote_git_path`). A test that has nothing to wait for fails the same mutant in `STALL_SECONDS`.
Importing `stalled_test_fails_fast` into a test module applies the guard to each test of it.
"""

import signal

import pytest

STALL_SECONDS = 5.0


def _stalled(signum, frame):
    raise AssertionError(f"test made no progress for {STALL_SECONDS} s (an endless loop?)")


@pytest.fixture
def stalled_test_fails_fast():
    """Fail the test, rather than wait for it, once it has run `STALL_SECONDS` without returning.

    An `ITIMER_REAL` that is already armed is not ours to cancel (the exit below would discard it),
    so the guard refuses to start rather than silently turn a protection into a no-op (C6-7 a).
    """
    outer_delay, outer_interval = signal.getitimer(signal.ITIMER_REAL)
    if outer_delay or outer_interval:
        raise RuntimeError(
            "stall guard: an ITIMER_REAL is already armed "
            f"(delay {outer_delay} s, interval {outer_interval} s); refusing to cancel it"
        )
    previous = signal.signal(signal.SIGALRM, _stalled)
    signal.setitimer(signal.ITIMER_REAL, STALL_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
