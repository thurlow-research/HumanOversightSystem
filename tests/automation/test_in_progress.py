"""Tests for scripts/automation/in_progress.py and its wiring (#2157)."""

import os
import re
import shutil
from pathlib import Path

import pytest

from scripts.automation import in_progress
from scripts.automation.lib import github
from tests.automation.test_branch_ownership import Repo

REPO_ROOT = Path(__file__).resolve().parents[2]


class FakeGitHub:
    """In-memory stand-in for the github.* label helpers."""

    def __init__(self, carriers=(), label_exists=True, create_error=None, titles=None):
        self.carriers = set(carriers)
        self.label_exists = label_exists
        self.create_error = create_error
        self.titles = titles or {}
        self.created = 0
        self.removed = []
        self.fail_all = False

    def install(self, monkeypatch):
        monkeypatch.setattr(in_progress, "resolve_repo_slug", lambda _p: "o/r")
        monkeypatch.setattr(github, "get_label", self.get_label)
        monkeypatch.setattr(github, "create_label", self.create_label)
        monkeypatch.setattr(github, "list_issues_with_label", self.list_issues)
        monkeypatch.setattr(github, "add_issue_label", self.add)
        monkeypatch.setattr(github, "remove_issue_label", self.remove)
        monkeypatch.setattr(github, "get_issue", self.get_issue)
        return self

    def _check(self):
        if self.fail_all:
            raise github.GitHubError("boom", status_code=500)

    def get_label(self, o, r, name):
        self._check()
        return {"name": name} if self.label_exists else None

    def create_label(self, o, r, name, color, desc):
        self.created += 1
        if self.create_error:
            raise self.create_error

    def list_issues(self, o, r, label):
        self._check()
        return [{"number": n} for n in sorted(self.carriers)]

    def add(self, o, r, n, label):
        self.carriers.add(n)

    def remove(self, o, r, n, label):
        self.removed.append(n)
        self.carriers.discard(n)

    def get_issue(self, o, r, n):
        return {"title": self.titles.get(n, "T")}


def test_mark_moves_label_and_logs(monkeypatch, tmp_path, capsys):
    fake = FakeGitHub(carriers=[5, 9], titles={7: "Fix it"}).install(monkeypatch)
    log = tmp_path / "cycle.log"
    log.write_text("start\n")
    monkeypatch.setenv("HOS_CYCLE_LOG", str(log))
    assert in_progress.main(["mark", "--issue", "7", "--branch", "worker-7-x"]) == 0
    assert fake.carriers == {7}
    assert sorted(fake.removed) == [5, 9]
    line = "WORKING ON #7 Fix it branch=worker-7-x"
    assert line in capsys.readouterr().err
    lines = log.read_text().splitlines()
    assert lines[0] == "start"
    assert re.fullmatch(r"\[\d{4}-\d\d-\d\dT[\d:]+Z\] " + re.escape(line), lines[1])


def test_mark_keeps_label_on_target_when_already_carried(monkeypatch):
    fake = FakeGitHub(carriers=[7]).install(monkeypatch)
    in_progress.main(["mark", "--issue", "7", "--branch", "b"])
    assert fake.removed == [] and fake.carriers == {7}


def test_mark_creates_missing_label(monkeypatch):
    fake = FakeGitHub(label_exists=False).install(monkeypatch)
    in_progress.main(["mark", "--issue", "7", "--branch", "b"])
    assert fake.created == 1 and fake.carriers == {7}


def test_mark_tolerates_422_on_create(monkeypatch):
    fake = FakeGitHub(
        label_exists=False, create_error=github.GitHubError("exists", status_code=422)
    ).install(monkeypatch)
    in_progress.main(["mark", "--issue", "7", "--branch", "b"])
    assert fake.carriers == {7}


def test_log_file_not_created_when_missing(monkeypatch, tmp_path):
    FakeGitHub().install(monkeypatch)
    log = tmp_path / "absent.log"
    monkeypatch.setenv("HOS_CYCLE_LOG", str(log))
    in_progress.main(["mark", "--issue", "7", "--branch", "b"])
    assert not log.exists()


def test_title_sanitized(monkeypatch, capsys):
    FakeGitHub(titles={7: "a\nb\x1b[0m" + "x" * 300}).install(monkeypatch)
    in_progress.main(["mark", "--issue", "7", "--branch", "b"])
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("WORKING ON #7 a b ")
    assert "\x1b" not in err[0]
    assert len(err[0]) < 160


def test_clear_removes_all_and_reports(monkeypatch, capsys):
    fake = FakeGitHub(carriers=[3, 4]).install(monkeypatch)
    assert in_progress.main(["clear"]) == 0
    assert capsys.readouterr().out.strip() == "in-progress: cleared #3,#4"
    assert fake.carriers == set()


def test_clear_none(monkeypatch, capsys):
    FakeGitHub().install(monkeypatch)
    in_progress.main(["clear"])
    assert capsys.readouterr().out.strip() == "in-progress: none"


def test_github_error_is_warning_exit_zero(monkeypatch, capsys):
    fake = FakeGitHub(carriers=[1]).install(monkeypatch)
    fake.fail_all = True
    assert in_progress.main(["clear"]) == 0
    assert in_progress.main(["mark", "--issue", "7", "--branch", "b"]) == 0
    assert "WARN" in capsys.readouterr().err


def test_working_on_line_survives_label_failure(monkeypatch, tmp_path, capsys):
    fake = FakeGitHub().install(monkeypatch)

    def boom(*_a):
        raise github.GitHubError("nope", status_code=500)

    monkeypatch.setattr(github, "add_issue_label", boom)
    monkeypatch.setattr(github, "get_issue", boom)
    log = tmp_path / "cycle.log"
    log.write_text("")
    monkeypatch.setenv("HOS_CYCLE_LOG", str(log))
    assert in_progress.main(["mark", "--issue", "7", "--branch", "b"]) == 0
    err = capsys.readouterr().err
    assert "WARN" in err and "WORKING ON #7  branch=b" in err
    assert "WORKING ON #7  branch=b" in log.read_text()
    assert fake.carriers == set()


def test_working_on_line_survives_slug_failure(monkeypatch, tmp_path, capsys):
    def bad(_p):
        raise RuntimeError("no remote")

    monkeypatch.setattr(in_progress, "resolve_repo_slug", bad)
    log = tmp_path / "cycle.log"
    log.write_text("")
    monkeypatch.setenv("HOS_CYCLE_LOG", str(log))
    assert in_progress.main(["mark", "--issue", "7", "--branch", "b"]) == 0
    assert "WORKING ON #7  branch=b" in capsys.readouterr().err
    assert "WORKING ON #7  branch=b" in log.read_text()


def test_line_written_before_any_label_call(monkeypatch, tmp_path):
    fake = FakeGitHub(carriers=[5]).install(monkeypatch)
    log = tmp_path / "cycle.log"
    log.write_text("")
    monkeypatch.setenv("HOS_CYCLE_LOG", str(log))
    seen = []

    def rec(name, orig):
        def wrapper(*a):
            seen.append((name, "WORKING ON #7" in log.read_text()))
            return orig(*a)

        return wrapper

    for name in ("get_label", "list_issues_with_label", "add_issue_label", "remove_issue_label"):
        monkeypatch.setattr(github, name, rec(name, getattr(github, name)))
    in_progress.main(["mark", "--issue", "7", "--branch", "b"])
    assert seen and all(logged for _n, logged in seen)
    assert fake.carriers == {7}


def test_warn_appended_to_cycle_log(monkeypatch, tmp_path):
    fake = FakeGitHub().install(monkeypatch)
    fake.fail_all = True
    log = tmp_path / "cycle.log"
    log.write_text("")
    monkeypatch.setenv("HOS_CYCLE_LOG", str(log))
    in_progress.main(["clear"])
    assert "in-progress: WARN: clear failed" in log.read_text()


def test_usage_error_exits_2():
    with pytest.raises(SystemExit) as exc:
        in_progress.main(["mark"])
    assert exc.value.code == 2


def test_remove_issue_label_404_is_success(monkeypatch):
    monkeypatch.setattr(github, "_run_gh", lambda args, **kw: None)  # 404 -> None
    github.remove_issue_label("o", "r", 1, "hos-in-progress")


def test_selector_ignores_label():
    text = (REPO_ROOT / "scripts/framework/select_work_candidates.py").read_text()
    assert "hos-in-progress" not in text


def test_create_branch_stdout_is_only_branch_name(tmp_path):
    repo = Repo(tmp_path)
    # The throwaway repo has no scripts.automation package, so mark fails fast
    # (best-effort) and must not disturb the stdout contract.
    res = repo.create_branch("--issue", "7", "--slug", "thing")
    assert res.returncode == 0, res.stderr
    out = res.stdout.strip().splitlines()
    assert out == ["worker-7-thing-260101000000-999"]
    again = repo.create_branch("--issue", "7", "--slug", "thing")
    assert again.stdout.strip().splitlines() == out


def test_create_branch_stdout_clean_when_mark_prints(tmp_path):
    repo = Repo(tmp_path)
    pkg = repo.root / "scripts" / "automation"
    pkg.mkdir(parents=True)
    for d in (repo.root / "scripts", pkg):
        (d / "__init__.py").write_text("")
    (pkg / "in_progress.py").write_text("print('NOISE on stdout')\n")
    res = repo.create_branch("--issue", "7", "--slug", "thing")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().splitlines() == ["worker-7-thing-260101000000-999"]
    assert "NOISE on stdout" in res.stderr


def test_create_branch_silent_when_module_absent(tmp_path):
    repo = Repo(tmp_path)
    res = repo.create_branch("--issue", "7", "--slug", "thing")
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip().splitlines() == ["worker-7-thing-260101000000-999"]
    assert "hos-in-progress" not in res.stderr and "ModuleNotFound" not in res.stderr


def test_hos_cron_exit_trap_clears_for_worker():
    text = (REPO_ROOT / "bin" / "hos-cron").read_text()
    assert re.search(r"^trap '_hos_inprogress_clear; rm -rf", text, re.M)
    assert 'ROLE" == "worker"' in text.split("_hos_inprogress_clear() {", 1)[1][:200]
    assert "scripts.automation.in_progress clear" in text
