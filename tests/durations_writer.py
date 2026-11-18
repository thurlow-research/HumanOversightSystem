"""Per-test wall time for the new-code gate's shard planner (#2304, AD-14).

`scripts/framework/run_tests.sh` sets `HOS_TEST_DURATIONS_OUT` on its pytest command, and the
root `tests/conftest.py` registers this plugin only then. It adds up `report.duration` for the
setup, call and teardown of every test (a rerun adds its time too) under the same node ID the
coverage contexts use, and at the end of the session writes `{node_id: whole milliseconds}`.
The write goes to a temp file in the same directory and is renamed into place, so `meta` never
reads a half-written file. A failed write is reported and never fails the suite: `meta` then
records the durations as missing, and `plan` fails with that reason.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import pytest

DURATIONS_ENV = "HOS_TEST_DURATIONS_OUT"


def write_durations(path: Path, seconds: dict[str, float]) -> None:
    """Write `{node_id: ms}` to `path` atomically (temp file beside it, then `os.replace`)."""
    document = {node: round(value * 1000) for node, value in sorted(seconds.items())}
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def discard_stale(path: Path) -> None:
    """Remove a durations file an earlier run left, so a file at `path` always comes from this run.

    A run that dies before `pytest_sessionfinish` then leaves no file, and `meta` records the
    durations as missing (fail closed) instead of pairing the new coverage data with old timings.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"stale test durations not removed from {path}: {exc}", file=sys.stderr)


class DurationsWriter:
    def __init__(self, out: Path) -> None:
        self.out = out
        self.seconds: dict[str, float] = defaultdict(float)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.seconds[report.nodeid] += report.duration

    def pytest_sessionfinish(self, session: pytest.Session) -> None:
        try:
            write_durations(self.out, self.seconds)
        except OSError as exc:
            print(f"test durations not written to {self.out}: {exc}", file=sys.stderr)


def register_if_requested(config: pytest.Config) -> None:
    out = os.environ.get(DURATIONS_ENV)
    if out:
        path = Path(os.path.abspath(out))
        discard_stale(path)
        config.pluginmanager.register(DurationsWriter(path), "hos-test-durations")
