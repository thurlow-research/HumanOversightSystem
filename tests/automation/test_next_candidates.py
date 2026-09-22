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

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")


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
        lines = _run_filter(
            [
                _issue(894),  # unlabeled -> low
                _issue(901, "priority:high"),  # high, higher number
            ]
        )
        assert _numbers(lines) == [901, 894]

    def test_full_priority_ladder(self):
        lines = _run_filter(
            [
                _issue(700, "priority:low"),
                _issue(600, "priority:medium"),
                _issue(950, "priority:critical"),  # newest number, top priority
                _issue(880, "priority:high"),
            ]
        )
        assert _numbers(lines) == [950, 880, 600, 700]

    def test_tie_break_is_lowest_number_within_band(self):
        lines = _run_filter(
            [
                _issue(901, "priority:high"),
                _issue(880, "priority:high"),
                _issue(890, "priority:high"),
            ]
        )
        assert _numbers(lines) == [880, 890, 901]

    def test_no_priority_label_defaults_to_low(self):
        # An unlabeled issue must sort identically to an explicit priority:low one,
        # broken only by issue number — proving "no label => low".
        lines = _run_filter(
            [
                _issue(894),  # unlabeled (default low)
                _issue(700, "priority:low"),  # explicit low
                _issue(800, "priority:medium"),
            ]
        )
        assert _numbers(lines) == [800, 700, 894]

    def test_default_low_label_rendered_as_low(self):
        [line] = _run_filter([_issue(894)])
        assert line == "#894 [low] issue 894"


class TestEligibilityFilter:
    def test_needs_human_is_excluded(self):
        lines = _run_filter(
            [
                _issue(500, "priority:high", "needs-human"),  # blocked, even though high
                _issue(894),  # eligible
            ]
        )
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
        lines = _run_filter(
            [
                {"number": 10, "title": "no labels key"},
                {"number": 20, "title": "null labels", "labels": None},
                _issue(5, "priority:high"),
            ]
        )
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


def _run_paginated(pages: list[list[dict]]) -> list[str]:
    """Apply the canonical filter the way both selection paths now do (#1805).

    Mirrors the shipped shape exactly: `gh api --paginate` emits one JSON array
    per page (concatenated), which is slurped and `add`-ed into a single array
    before the filter runs ONCE over the combined set.
    """
    proc = subprocess.run(
        ["jq", "-s", "-r", f"add | {FILTER.read_text()}"],
        input="".join(json.dumps(p) for p in pages),
        capture_output=True,
        text=True,
        check=True,
    )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def _run_per_page(pages: list[list[dict]]) -> list[str]:
    """The TRAP: what `gh api --paginate --jq FILTER` does (#1805).

    Reproduced only so a test can assert the shipped code does NOT behave this
    way. The filter runs once per page, so sort_by() sorts within a page and the
    pages are then concatenated.
    """
    lines: list[str] = []
    for page in pages:
        lines.extend(_run_filter(page))
    return lines


class TestPaginationGlobalSort:
    """Work selection must see the whole backlog, globally sorted (#1805).

    The list-issues endpoint defaults to sort=created&direction=desc, so page 1
    is the NEWEST issues. next_candidates.jq tie-breaks on ASCENDING number, so
    an unpaginated (or per-page-sorted) fetch discards exactly the issues the
    ordering rule ranks first. Live v0.7.0 had 135 eligible issues; the 36 on
    page 2 -- 24 of them priority:high, including #1357 and #1601/#1602 -- were
    unselectable.
    """

    # Page 1 = newest (higher numbers), page 2 = oldest (lower numbers), which
    # is the real API's ordering. The page-2 issues are HIGH; the page-1 tail is
    # LOW, so a correct global sort must interleave them across the page seam.
    PAGE_1 = [
        _issue(1643, "priority:critical"),
        _issue(1604, "priority:high"),
        _issue(1744, "priority:low"),
    ]
    PAGE_2 = [
        _issue(1340, "priority:high"),
        _issue(1357, "priority:high"),
    ]

    def test_combined_set_is_globally_sorted(self):
        lines = _run_paginated([self.PAGE_1, self.PAGE_2])
        # Every high-priority issue outranks the low one regardless of page, and
        # within the high band the lower (older) numbers come first.
        assert _numbers(lines) == [1643, 1340, 1357, 1604, 1744]

    def test_page_two_issues_are_reachable_at_all(self):
        # The pre-fix bug: page 2 simply never entered the candidate set.
        lines = _run_paginated([self.PAGE_1, self.PAGE_2])
        assert 1357 in _numbers(lines)

    def test_per_page_filtering_is_not_globally_sorted(self):
        # Characterizes the trap so the assertion below has teeth: applying the
        # filter per page leaves a [low] ahead of two [high]s.
        trap = _numbers(_run_per_page([self.PAGE_1, self.PAGE_2]))
        assert trap == [1643, 1604, 1744, 1340, 1357]
        assert trap != _numbers(_run_paginated([self.PAGE_1, self.PAGE_2]))

    def test_trap_is_invisible_in_the_first_five_lines(self):
        # Why this bug survived: the cycle context prints head -5. With a real
        # page size of 100 the per-page output's first five entries are the same
        # as the broken single-page output's, so the naive fix looks identical.
        head = _numbers(_run_per_page([self.PAGE_1, self.PAGE_2]))[:2]
        assert head == _numbers(_run_filter(self.PAGE_1))[:2]


class TestBothPathsPaginate:
    """Both selection paths must paginate AND apply the filter once (#1805)."""

    def test_hos_cron_paginates(self):
        assert "--paginate" in HOS_CRON.read_text()

    def test_cron_prompt_paginates(self):
        assert "--paginate" in CRON_PROMPT.read_text()

    @pytest.mark.parametrize("path", [HOS_CRON, CRON_PROMPT], ids=["hos-cron", "cron-prompt"])
    def test_filter_applied_once_to_combined_set(self, path):
        # The load-bearing part: `jq -s ... add | <filter>` over the slurped
        # pages. Presence of --paginate alone does NOT mean the bug is fixed.
        text = path.read_text()
        assert "add | $(cat" in text, (
            f"{path.name} must pipe paginated output through "
            'jq -sr "add | $(cat .../next_candidates.jq)" so the sort is global'
        )

    @staticmethod
    def _logical_lines(text: str) -> list[str]:
        """Join shell line-continuations so one command is one string.

        The invocation spans a backslash continuation and a leading-pipe
        continuation; matching raw lines would make every assertion below pass
        vacuously (no single raw line holds both `--paginate` and the filter
        path).
        """
        joined = text.replace("\\\n", " ")
        out: list[str] = []
        for raw in joined.splitlines():
            if raw.lstrip().startswith("|") and out:
                out[-1] += " " + raw.strip()
            else:
                out.append(raw)
        return out

    @pytest.mark.parametrize("path", [HOS_CRON, CRON_PROMPT], ids=["hos-cron", "cron-prompt"])
    def test_guard_is_not_vacuous(self, path):
        # The continuation-joining must actually produce the command, else the
        # shape assertions below would silently test nothing.
        cmds = [
            ln
            for ln in self._logical_lines(path.read_text())
            if "--paginate" in ln and "next_candidates.jq" in ln
        ]
        assert cmds, (
            f"{path.name}: found no single logical command containing both "
            "--paginate and next_candidates.jq -- the selection call changed "
            "shape and these guards need updating"
        )

    @pytest.mark.parametrize("path", [HOS_CRON, CRON_PROMPT], ids=["hos-cron", "cron-prompt"])
    def test_does_not_use_gh_jq_with_paginate(self, path):
        # `gh api --paginate ... --jq <filter>` runs the filter per page. Guard
        # against a future edit collapsing the pipeline back into that form.
        for cmd in self._logical_lines(path.read_text()):
            if "--paginate" in cmd and "next_candidates.jq" in cmd:
                assert "--jq" not in cmd, (
                    f"{path.name}: `gh api --paginate --jq <filter>` sorts "
                    "per page, not globally -- pipe to `jq -sr 'add | ...'`"
                )
                assert "| jq -sr" in cmd or "| jq -s -r" in cmd, (
                    f"{path.name}: paginated output must be slurped and "
                    "combined before the filter runs"
                )
