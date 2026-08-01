"""
Tests for check_base_freshness() in scripts/automation/lib/stale_commit_detector.py.

The #1162 guard: building on a base the target has moved past produces a commit
that proposes REVERTING the intervening work, while the PR looks entirely normal.

These are unit tests over real throwaway repos rather than subprocess tests of a
shell script — which is the point of the function living in Python. The predicate
is directly callable, so the boundaries (exactly-equal, unresolvable target,
sample bounding) are cheap to cover instead of needing a repo-plus-script harness
per case.
"""

import subprocess
from pathlib import Path

import pytest

from scripts.automation.lib.stale_commit_detector import (
    BaseFreshnessResult,
    check_base_freshness,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _commit(repo: Path, name: str, msg: str) -> str:
    (repo / name).write_text(f"{name} content\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    _commit(r, "base.md", "base commit")
    # The module's _run_git shells out in the process CWD.
    monkeypatch.chdir(r)
    return r


def test_fresh_base_reports_zero_behind(repo):
    result = check_base_freshness(base="main", target="main")
    assert result.is_fresh
    assert result.behind_count == 0
    assert result.missing_commits == []
    assert result.target_resolved
    assert not result.could_not_check


def test_stale_base_counts_and_names_missing_commits(repo):
    """The core case: target has advanced past the base."""
    _git(repo, "branch", "old")
    _commit(repo, "theirs-1.md", "concurrent work one")
    _commit(repo, "theirs-2.md", "concurrent work two")

    result = check_base_freshness(base="old", target="main")

    assert not result.is_fresh
    assert result.behind_count == 2
    assert len(result.missing_commits) == 2
    # Newest first, and the summaries carry the subject so a caller can print
    # something actionable rather than bare SHAs.
    assert "concurrent work two" in result.missing_commits[0]
    assert "concurrent work one" in result.missing_commits[1]


def test_unresolvable_target_reports_could_not_check_not_fresh(repo):
    """Fail-open guard: a missing target must never read as 'fresh'.

    This is the boundary that a shell implementation got wrong — an unresolvable
    ref silently skipped the check entirely.
    """
    result = check_base_freshness(base="main", target="origin/does-not-exist")

    assert result.could_not_check
    assert not result.target_resolved
    # is_fresh is vacuously True (0 behind), so callers MUST branch on
    # could_not_check first — asserted here so the contract is pinned.
    assert result.behind_count == 0


def test_sample_bounds_returned_summaries_but_not_the_count(repo):
    _git(repo, "branch", "old")
    for i in range(7):
        _commit(repo, f"t{i}.md", f"commit {i}")

    result = check_base_freshness(base="old", target="main", sample=3)

    assert result.behind_count == 7, "the count must be exact, not sampled"
    assert len(result.missing_commits) == 3, "summaries are bounded by sample"


def test_base_ahead_of_target_is_still_fresh(repo):
    """Ahead is not behind — a branch with its own new work is not stale."""
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "mine.md", "my work")

    result = check_base_freshness(base="feature", target="main")

    assert result.is_fresh, "having extra commits is not staleness"
    assert result.behind_count == 0


def test_diverged_base_reports_only_what_it_is_missing(repo):
    """Both sides advanced: only the target-side commits count as missing."""
    _git(repo, "branch", "old")
    _commit(repo, "theirs.md", "their work")
    _git(repo, "checkout", "-q", "old")
    _commit(repo, "mine.md", "my work")

    result = check_base_freshness(base="old", target="main")

    assert result.behind_count == 1
    assert "their work" in result.missing_commits[0]
    assert not any("my work" in c for c in result.missing_commits)


def test_result_is_a_dataclass_with_the_documented_fields(repo):
    result = check_base_freshness(base="main", target="main")
    assert isinstance(result, BaseFreshnessResult)
    assert result.base == "main"
    assert result.target == "main"
