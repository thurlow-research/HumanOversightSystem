"""Unit tests for tests/conftest.py `_report_retry_rescues` (TD-2304 §5.20.17, RR-1 to RR-5).

The helper is driven with a fake terminal reporter, a plain dict for the environment and a
recording `write_event`. `MUTANT_UNDER_TEST` is never set in the real `os.environ`: mutmut's
trampoline reads it there to choose which mutant runs.

The only production code reached is `retry_rescue_logic` (the helper's own lazy import, and the
event builder used to compute expected events).
"""

from types import SimpleNamespace

import pytest
import retry_rescue_logic

from tests.conftest import ROOT, _report_retry_rescues

SKIP_LINE = "  (audit write skipped: inside a mutation run)"
SECTION = "retry-rescues (#1244 ruling item 4)"
FIXED_TS = "2026-11-22T10:00:00Z"
NODE = "tests/test_x.py::test_flaky"


class FakeReporter:
    """Just enough of pytest's TerminalReporter: `stats`, `section` and `write_line`."""

    def __init__(self, stats):
        self.stats = stats
        self.sections = []
        self.lines = []

    def section(self, title):
        self.sections.append(title)

    def write_line(self, line):
        self.lines.append(line)


def _reports(*nodeids):
    return [SimpleNamespace(nodeid=n) for n in nodeids]


def _reporter(rerun=(), passed=()):
    return FakeReporter({"rerun": _reports(*rerun), "passed": _reports(*passed)})


class Recorder:
    """A `write_event` stand-in that records each call."""

    def __init__(self):
        self.calls = []

    def __call__(self, event, root):
        self.calls.append((event, root))


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    monkeypatch.setattr(retry_rescue_logic, "now_iso", lambda: FIXED_TS)


@pytest.mark.parametrize("marker", ["", "x.y__mutmut_1"], ids=["clean-run-empty", "mutant-name"])
def test_rescue_inside_mutation_run_prints_lines_and_never_writes(marker):
    """RR-1 and RR-2: MUTANT_UNDER_TEST present (even empty) suppresses the write only."""
    reporter = _reporter(rerun=[NODE], passed=[NODE])
    recorder = Recorder()

    _report_retry_rescues(reporter, {"MUTANT_UNDER_TEST": marker}, recorder)

    assert recorder.calls == []
    assert reporter.sections == [SECTION]
    assert reporter.lines == [
        f"RETRY-RESCUE: {NODE} failed once, passed on retry",
        SKIP_LINE,
    ]


def test_skip_line_is_printed_once_per_rescue_in_order():
    """RR-1 and RR-2: each rescue gets its own RETRY-RESCUE line followed by one skip line."""
    other = "tests/test_y.py::test_other"
    reporter = _reporter(rerun=[NODE, other], passed=[other, NODE])
    recorder = Recorder()

    _report_retry_rescues(reporter, {"MUTANT_UNDER_TEST": ""}, recorder)

    assert recorder.calls == []
    assert reporter.sections == [SECTION]
    assert reporter.lines == [
        f"RETRY-RESCUE: {NODE} failed once, passed on retry",
        SKIP_LINE,
        f"RETRY-RESCUE: {other} failed once, passed on retry",
        SKIP_LINE,
    ]


def test_rescue_outside_mutation_run_writes_event_with_repo_root():
    """RR-3: no MUTANT_UNDER_TEST means one write_event call with the built event and ROOT."""
    reporter = _reporter(rerun=[NODE], passed=[NODE])
    recorder = Recorder()

    _report_retry_rescues(reporter, {}, recorder)

    assert recorder.calls == [
        (retry_rescue_logic.build_retry_rescue_event(NODE, FIXED_TS, None), str(ROOT))
    ]
    assert recorder.calls[0][0] == {
        "event": "test-retry-rescue",
        "test": NODE,
        "timestamp": FIXED_TS,
    }
    assert reporter.sections == [SECTION]
    assert reporter.lines == [f"RETRY-RESCUE: {NODE} failed once, passed on retry"]


def test_write_event_called_once_per_rescue_with_pr_number_from_environ():
    """RR-3: one call per rescue; PR_NUMBER is read from the passed environ."""
    other = "tests/test_y.py::test_other"
    reporter = _reporter(rerun=[NODE, other], passed=[NODE, other])
    recorder = Recorder()

    _report_retry_rescues(reporter, {"PR_NUMBER": "2304"}, recorder)

    assert recorder.calls == [
        (retry_rescue_logic.build_retry_rescue_event(NODE, FIXED_TS, "2304"), str(ROOT)),
        (retry_rescue_logic.build_retry_rescue_event(other, FIXED_TS, "2304"), str(ROOT)),
    ]
    assert all(event["pr_number"] == "2304" for event, _ in recorder.calls)


def test_empty_pr_number_is_omitted_from_event():
    """An empty PR_NUMBER is treated as absent (`or None`)."""
    reporter = _reporter(rerun=[NODE], passed=[NODE])
    recorder = Recorder()

    _report_retry_rescues(reporter, {"PR_NUMBER": ""}, recorder)

    assert "pr_number" not in recorder.calls[0][0]


def test_no_rerun_prints_nothing_and_writes_nothing():
    """RR-4: no rerun reports means no section, no lines, no write."""
    reporter = _reporter(rerun=[], passed=[NODE])
    recorder = Recorder()

    _report_retry_rescues(reporter, {}, recorder)

    assert reporter.sections == []
    assert reporter.lines == []
    assert recorder.calls == []


def test_missing_rerun_bucket_prints_nothing_and_writes_nothing():
    """RR-4: pytest omits the 'rerun' key entirely when nothing reran."""
    reporter = FakeReporter({"passed": _reports(NODE)})
    recorder = Recorder()

    _report_retry_rescues(reporter, {}, recorder)

    assert reporter.sections == []
    assert reporter.lines == []
    assert recorder.calls == []


@pytest.mark.parametrize("environ", [{}, {"MUTANT_UNDER_TEST": ""}], ids=["plain", "mutation"])
def test_rerun_without_rescue_prints_nothing_and_writes_nothing(environ):
    """RR-4: a rerun whose test never passed is a real failure, not a rescue."""
    reporter = _reporter(rerun=[NODE], passed=["tests/test_y.py::test_other"])
    recorder = Recorder()

    _report_retry_rescues(reporter, environ, recorder)

    assert reporter.sections == []
    assert reporter.lines == []
    assert recorder.calls == []


def test_failing_write_event_is_swallowed_and_reported():
    """RR-5: a raising write_event yields the skipped line and nothing propagates."""
    reporter = _reporter(rerun=[NODE], passed=[NODE])

    def boom(event, root):
        raise OSError("disk on fire")

    _report_retry_rescues(reporter, {}, boom)

    assert reporter.lines == [
        f"RETRY-RESCUE: {NODE} failed once, passed on retry",
        "  (audit write skipped: disk on fire)",
    ]


def test_import_error_from_lazy_wrapper_is_swallowed_and_reported():
    """RR-5: the real hook's lazy import failing lands in the best-effort except."""
    reporter = _reporter(rerun=[NODE], passed=[NODE])

    def lazy_wrapper(event, root):
        raise ImportError("No module named 'scripts.oversight.lib.audit_log'")

    _report_retry_rescues(reporter, {}, lazy_wrapper)

    assert reporter.lines[-1] == (
        "  (audit write skipped: No module named 'scripts.oversight.lib.audit_log')"
    )


def test_one_failed_write_does_not_stop_later_rescues():
    """RR-5: the except is per rescue; the next rescue is still attempted and written."""
    other = "tests/test_y.py::test_other"
    reporter = _reporter(rerun=[NODE, other], passed=[NODE, other])
    calls = []

    def flaky_write(event, root):
        calls.append(event["test"])
        if event["test"] == NODE:
            raise RuntimeError("first fails")

    _report_retry_rescues(reporter, {}, flaky_write)

    assert calls == [NODE, other]
    assert reporter.lines == [
        f"RETRY-RESCUE: {NODE} failed once, passed on retry",
        "  (audit write skipped: first fails)",
        f"RETRY-RESCUE: {other} failed once, passed on retry",
    ]


def test_failing_write_event_inside_mutation_run_is_never_reached():
    """RR-1 with RR-5: a raising writer is not even called in a mutation run, so no error line."""
    reporter = _reporter(rerun=[NODE], passed=[NODE])

    def boom(event, root):
        raise AssertionError("must not be called")

    _report_retry_rescues(reporter, {"MUTANT_UNDER_TEST": "a.b__mutmut_2"}, boom)

    assert reporter.lines == [
        f"RETRY-RESCUE: {NODE} failed once, passed on retry",
        SKIP_LINE,
    ]
