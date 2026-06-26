"""Tests for the canonical work-selection ordering filter (#901).

`scripts/automation/lib/next_candidates.jq` is the single source of truth for the
order in which the autonomous worker picks up `needs-ai` issues. Both selection
paths consume it:

  (a) bin/hos-cron `_build_context` — the pre-computed "Next work candidates" block
  (b) bootstrap/worker-cron-prompt.md Step-2 fallback

These tests run the real jq filter against fixtures (so they validate the actual
ordering logic, not a Python re-implementation) and assert that both selection
paths reference the canonical filter rather than re-inlining divergent jq.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FILTER = REPO_ROOT / "scripts" / "automation" / "lib" / "next_candidates.jq"
HOS_CRON = REPO_ROOT / "bin" / "hos-cron"
CRON_PROMPT = REPO_ROOT / "bootstrap" / "worker-cron-prompt.md"

pytestmark = pytest.mark.skipif(
    shutil.which("jq") is None, reason="jq not installed"
)


def _issue(number: int, *labels: str, title: str = "") -> dict:
    """A minimal GitHub list-issues API record. needs-ai is implied by query."""
    names = ["needs-ai", *labels]
    return {
        "number": number,
        "title": title or f"issue {number}",
        "labels": [{"name": n} for n in names],
    }


def _run_filter(issues: list[dict]) -> list[str]:
    """Pipe an issues array through the canonical jq filter, return output lines."""
    proc = subprocess.run(
        ["jq", "-r", "-f", str(FILTER)],
        input=json.dumps(issues),
        capture_output=True,
        text=True,
        check=True,
    )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _numbers(lines: list[str]) -> list[int]:
    """Extract the issue numbers, in order, from '#N [prio] title' lines."""
    return [int(ln.split()[0].lstrip("#")) for ln in lines]


class TestPriorityOrdering:
    def test_high_beats_low_across_number_inversion(self):
        # The high-priority issue has the HIGHER number; it must still come first.
        lines = _run_filter([
            _issue(894),                       # unlabeled -> low
            _issue(901, "priority:high"),      # high, higher number
        ])
        assert _numbers(lines) == [901, 894]

    def test_full_priority_ladder(self):
        lines = _run_filter([
            _issue(700, "priority:low"),
            _issue(600, "priority:medium"),
            _issue(950, "priority:critical"),  # newest number, top priority
            _issue(880, "priority:high"),
        ])
        assert _numbers(lines) == [950, 880, 600, 700]

    def test_tie_break_is_lowest_number_within_band(self):
        lines = _run_filter([
            _issue(901, "priority:high"),
            _issue(880, "priority:high"),
            _issue(890, "priority:high"),
        ])
        assert _numbers(lines) == [880, 890, 901]

    def test_no_priority_label_defaults_to_low(self):
        # An unlabeled issue must sort identically to an explicit priority:low one,
        # broken only by issue number — proving "no label => low".
        lines = _run_filter([
            _issue(894),                   # unlabeled (default low)
            _issue(700, "priority:low"),   # explicit low
            _issue(800, "priority:medium"),
        ])
        assert _numbers(lines) == [800, 700, 894]

    def test_default_low_label_rendered_as_low(self):
        [line] = _run_filter([_issue(894)])
        assert line == "#894 [low] issue 894"


class TestEligibilityFilter:
    def test_needs_human_is_excluded(self):
        lines = _run_filter([
            _issue(500, "priority:high", "needs-human"),  # blocked, even though high
            _issue(894),                                  # eligible
        ])
        assert _numbers(lines) == [894]

    def test_empty_input_yields_no_lines(self):
        assert _run_filter([]) == []

    def test_all_blocked_yields_no_lines(self):
        assert _run_filter([_issue(1, "needs-human")]) == []

    def test_missing_or_null_labels_does_not_crash(self):
        # The canonical filter is unit-tested in isolation and declared the single
        # source of truth, so it must survive a degenerate record (no/null labels)
        # rather than aborting the whole selection. Such a record has no priority
        # label -> defaults to low, and is not needs-human -> eligible.
        lines = _run_filter([
            {"number": 10, "title": "no labels key"},
            {"number": 20, "title": "null labels", "labels": None},
            _issue(5, "priority:high"),
        ])
        assert _numbers(lines) == [5, 10, 20]


class TestBothSelectionPathsAgree:
    """The two selection paths must not re-inline divergent jq (#901)."""

    def test_filter_file_exists(self):
        assert FILTER.is_file()

    def test_hos_cron_uses_canonical_filter(self):
        text = HOS_CRON.read_text()
        assert "scripts/automation/lib/next_candidates.jq" in text

    def test_cron_prompt_fallback_uses_canonical_filter(self):
        text = CRON_PROMPT.read_text()
        assert "scripts/automation/lib/next_candidates.jq" in text

    def test_both_paths_share_query_params(self):
        # Ordering is shared via the filter file, but the query inputs are written
        # in both files; if they drift (e.g. per_page or label filter) the paths
        # select from different candidate sets. Assert the load-bearing params match.
        cron = HOS_CRON.read_text()
        prompt = CRON_PROMPT.read_text()
        for param in ("state=open", "labels=needs-ai", "per_page=100"):
            assert param in cron, f"{param} missing from bin/hos-cron"
            assert param in prompt, f"{param} missing from worker-cron-prompt.md"
