"""Tests for the "already started" signal and started-first ordering in
scripts/framework/select_work_candidates.py (#2155: WIP discipline).

The git-backed tests build a REAL throwaway repository under pytest's tmp_path
(a local `origin/main` ref stands in for the remote) so the `git cherry` and
`git ls-tree` logic is exercised for real. The fixtures are duplicated from
test_select_work_candidates.py: tests/framework is not a package.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from scripts.framework import requester_trust as rt
from scripts.framework import select_work_candidates as swc

PREFIX = "select_work_candidates: "
ROOT = Path(__file__).resolve().parents[2]

_ZERO_DEPS = {"blocked_by": 0, "blocking": 0, "total_blocked_by": 0, "total_blocking": 0}
_ZERO_SUBS = {"total": 0, "completed": 0, "percent_completed": 0}

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _issue(number: int, *labels: str, title: str = "") -> dict:
    return {
        "number": number,
        "title": title or f"issue {number}",
        "labels": [{"name": n} for n in ["needs-ai", *labels]],
        "user": {"login": "ScottThurlow", "type": "User"},
        "pull_request": None,
        "issue_dependencies_summary": _ZERO_DEPS,
        "sub_issues_summary": _ZERO_SUBS,
    }


class _Repo:
    """A real git repo whose `origin/main` is a local ref."""

    def __init__(self, root: Path):
        self.root = root
        self.git("init", "-q", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        self.write("README.md", "base\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.publish()

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, **_GIT_ENV},
        )
        return result.stdout.strip()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def publish(self) -> None:
        """Point origin/main at the local main tip."""
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", "main"))

    def doc_on_main(self, rel: str) -> None:
        self.git("checkout", "-q", "main")
        self.write(rel, "doc\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"add {rel}")
        self.publish()

    def branch_with_commit(self, name: str, fname: str = "work.txt") -> str:
        self.git("checkout", "-q", "main")
        self.git("checkout", "-q", "-b", name)
        self.write(fname, f"{name}\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", f"work on {name}")
        sha = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "main")
        return sha

    def land_on_main(self, sha: str) -> None:
        """Re-apply a branch commit onto main (new SHA, same patch)."""
        self.git("checkout", "-q", "main")
        self.git("cherry-pick", sha)
        self.publish()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path
    (root / ".github").mkdir()
    (root / ".github" / "CODEOWNERS").write_text("* @ScottThurlow\n")
    fw = root / "scripts" / "framework"
    fw.mkdir(parents=True)
    (fw / "machine-accounts.env").write_text(
        'BOT_WORKER_USERNAME="hos-worker-hos[bot]"\n'
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n'
        'BOT_HUMAN_USERNAME="scottthurlow-claude[bot]"\n'
        'COPILOT_BOT_LOGIN="copilot[bot]"\n'
    )
    r = _Repo(root)
    monkeypatch.setattr(swc, "_REPO_ROOT", root)
    return r


class _Gh:
    def __init__(self):
        self.issues: list = []

    def __call__(self, endpoint: str):
        if re.search(r"/issues\?.*page=1\b", endpoint):
            return self.issues
        if re.search(r"/issues\?.*page=\d+", endpoint):
            return []
        raise AssertionError(f"unexpected endpoint {endpoint!r}")


@pytest.fixture
def gh(monkeypatch):
    stub = _Gh()
    monkeypatch.setattr(swc, "_run_gh", stub)
    monkeypatch.setattr(rt, "_run_gh_get", stub)
    return stub


def _run(capsys, *args: str):
    rc = swc.main(["--repo", "owner/repo", "--milestone", "5", *args])
    cap = capsys.readouterr()
    return (
        rc,
        [ln for ln in cap.out.splitlines() if ln.strip()],
        [ln for ln in cap.err.splitlines() if ln.strip()],
    )


def _nums(lines: list) -> list:
    return [int(ln.split()[0].lstrip("#")) for ln in lines]


class TestStageClassification:
    def test_branch_beats_design_beats_none_and_beats_priority(self, repo, gh, capsys):
        repo.branch_with_commit("worker-30-built-1")
        repo.doc_on_main("docs/TECHNICAL-DESIGN-20-thing.md")
        gh.issues = [
            _issue(10, "priority:critical"),
            _issue(20, "priority:low"),
            _issue(30, "priority:low"),
        ]
        rc, out, err = _run(capsys)
        assert rc == 0
        assert _nums(out) == [30, 20, 10]
        assert out[0] == "#30 [low] [started:branch] issue 30"
        assert out[1] == "#20 [low] [started:design] issue 20"
        assert out[2] == "#10 [critical] issue 10"
        assert PREFIX + "STARTED branch=1 design=1" in err

    def test_priority_then_number_within_a_level(self, repo, gh, capsys):
        repo.branch_with_commit("worker-31-a")
        repo.branch_with_commit("worker-32-b")
        repo.branch_with_commit("worker-33-c")
        gh.issues = [
            _issue(33, "priority:high"),
            _issue(32, "priority:low"),
            _issue(31, "priority:low"),
        ]
        _, out, _ = _run(capsys)
        assert _nums(out) == [33, 31, 32]

    def test_branch_wins_when_both_signals_present(self, repo, gh, capsys):
        repo.doc_on_main("docs/ADR-40-x.md")
        repo.branch_with_commit("worker-40-y")
        gh.issues = [_issue(40)]
        _, out, err = _run(capsys)
        assert out == ["#40 [low] [started:branch] issue 40"]
        assert PREFIX + "STARTED branch=1 design=0" in err

    def test_walk_admits_started_issue_past_the_candidate_clamp(self, repo, gh, capsys):
        repo.branch_with_commit("worker-99-low")
        gh.issues = [_issue(n, "priority:critical") for n in range(1, 8)] + [
            _issue(99, "priority:low")
        ]
        rc, out, _ = _run(capsys)
        assert rc == 0
        assert len(out) == 5
        assert _nums(out)[0] == 99

    def test_branch_already_landed_is_not_started(self, repo, gh, capsys):
        sha = repo.branch_with_commit("worker-50-landed")
        repo.land_on_main(sha)
        gh.issues = [_issue(50)]
        _, out, err = _run(capsys)
        assert out == ["#50 [low] issue 50"]
        assert PREFIX + "STARTED branch=0 design=0" in err

    def test_branch_with_no_commits_beyond_main_is_not_started(self, repo, gh, capsys):
        repo.git("branch", "worker-51-empty", "main")
        gh.issues = [_issue(51)]
        _, out, _ = _run(capsys)
        assert out == ["#51 [low] issue 51"]

    def test_branch_for_other_issue_or_other_prefix_is_ignored(self, repo, gh, capsys):
        repo.branch_with_commit("worker-60-x")
        repo.branch_with_commit("feature-61-x")
        gh.issues = [_issue(61)]
        _, out, _ = _run(capsys)
        assert out == ["#61 [low] issue 61"]

    def test_design_doc_number_boundaries(self, repo, gh, capsys):
        repo.doc_on_main("docs/ADR-1552-other.md")
        repo.doc_on_main("docs/v0.7.0/ADR-1660-1662-combined.md")
        repo.doc_on_main("docs/TECHNICAL-DESIGN-70.md")
        gh.issues = [_issue(155), _issue(1660), _issue(1662), _issue(70), _issue(7)]
        _, out, _ = _run(capsys)
        started = {int(ln.split()[0][1:]) for ln in out if "[started:design]" in ln}
        assert started == {1660, 1662, 70}
        assert _nums(out)[:3] == [70, 1660, 1662]

    def test_unstarted_lines_are_byte_identical_to_the_old_format(self, repo, gh, capsys):
        gh.issues = [_issue(8, "priority:high", title="Some  title")]
        _, out, err = _run(capsys)
        assert out == ["#8 [high] Some  title"]
        assert PREFIX + "STARTED branch=0 design=0" in err


class TestFailSafe:
    def _unstarted_baseline(self, repo, gh, capsys):
        gh.issues = [_issue(1, "priority:low"), _issue(2, "priority:critical")]
        return _run(capsys)

    def test_missing_origin_main_degrades_to_none_with_one_warn(self, repo, gh, capsys):
        repo.branch_with_commit("worker-1-x")
        repo.git("update-ref", "-d", "refs/remotes/origin/main")
        rc, out, err = self._unstarted_baseline(repo, gh, capsys)
        assert rc == 0
        assert _nums(out) == [2, 1]
        assert all("[started:" not in ln for ln in out)
        assert err.count(PREFIX + "WARN started-signal-unavailable") == 1

    def test_git_failure_changes_neither_exit_code_nor_candidate_set(
        self, repo, gh, capsys, monkeypatch
    ):
        repo.branch_with_commit("worker-1-x")
        rc_ok, out_ok, _ = self._unstarted_baseline(repo, gh, capsys)

        def boom(*_a, **_k):
            raise subprocess.TimeoutExpired("git", 1)

        monkeypatch.setattr(swc.subprocess, "run", boom)
        # gh is stubbed, so only the git call sites see the failing runner.
        rc, out, err = self._unstarted_baseline(repo, gh, capsys)
        assert rc == rc_ok == 0
        assert sorted(_nums(out)) == sorted(_nums(out_ok))
        assert all("[started:" not in ln for ln in out)
        assert err.count(PREFIX + "WARN started-signal-unavailable") == 1

    def test_not_a_git_repo_degrades(self, tmp_path, gh, capsys, monkeypatch):
        (tmp_path / ".github").mkdir()
        (tmp_path / ".github" / "CODEOWNERS").write_text("* @ScottThurlow\n")
        fw = tmp_path / "scripts" / "framework"
        fw.mkdir(parents=True)
        (fw / "machine-accounts.env").write_text(
            'BOT_WORKER_USERNAME="hos-worker-hos[bot]"\n'
            'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n'
            'BOT_HUMAN_USERNAME="scottthurlow-claude[bot]"\n'
            'COPILOT_BOT_LOGIN="copilot[bot]"\n'
        )
        monkeypatch.setattr(swc, "_REPO_ROOT", tmp_path)
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
        gh.issues = [_issue(3)]
        rc, out, err = _run(capsys)
        assert rc == 0
        assert out == ["#3 [low] issue 3"]
        assert err.count(PREFIX + "WARN started-signal-unavailable") == 1


class TestDesignNumbers:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("docs/ADR-1552-x.md", {1552}),
            ("docs/ADR-1660-1662-x.md", {1660, 1662}),
            ("docs/a/TECHNICAL-DESIGN-1540-S1-S2-x.md", {1540}),
            ("docs/TECHNICAL-DESIGN-12.md", {12}),
            ("docs/ADR-12_x.md", {12}),
            ("docs/ADR-12abc.md", set()),
            ("docs/MY-ADR-12-x.md", set()),
            ("docs/REQUIREMENTS-12-x.md", set()),
        ],
    )
    def test_design_numbers(self, path, expected):
        assert swc._design_numbers([path]) == expected


class TestWorkerPromptStatesTheOrdering:
    def test_step_2_and_3_carry_the_wip_rules(self):
        text = (ROOT / "bootstrap" / "worker-cron-prompt.md").read_text()
        assert "[started:branch]" in text
        assert "[started:design]" in text
        assert "does not skip a level" in text
        assert "a merged spec is not done" in text.lower()


def test_module_docstring_documents_the_stage_key():
    assert "stage" in (swc.__doc__ or "") and "#2155" in swc.__doc__
