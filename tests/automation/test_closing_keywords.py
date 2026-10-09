"""Tests for scripts/automation/closing_keywords.py (#1856)."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.automation import closing_keywords as ck

SLUG = "test-owner/test-repo"
KEYWORDS = ["close", "closes", "closed", "fix", "fixes", "fixed", "resolve", "resolves", "resolved"]
SCRIPT = Path(ck.__file__)


def keys(text: str) -> list[str]:
    return [m.key for m in ck.find_closing_refs(text, SLUG)]


@pytest.mark.parametrize("kw", KEYWORDS)
@pytest.mark.parametrize("variant", [str.lower, str.upper, str.title])
def test_every_keyword_every_case(kw, variant):
    assert keys(f"{variant(kw)} #5") == ["5"]


@pytest.mark.parametrize(
    "text",
    ["Closes: #5", "closes :#5", "closes#5", "closes\n#5", "closes  \n  : #5"],
)
def test_separator_forms(text):
    assert keys(text) == ["5"]


@pytest.mark.parametrize(
    "ref,expected",
    [
        ("#5", "5"),
        ("GH-5", "5"),
        ("o/r#5", "o/r#5"),
        ("O/R#5", "o/r#5"),
        ("https://github.com/o/r/issues/5", "o/r#5"),
        ("https://github.com/o/r/pull/5", "o/r#5"),
        ("test-owner/test-repo#5", "5"),
        ("Test-Owner/TEST-repo#05", "5"),
        ("https://github.com/Test-Owner/Test-Repo/issues/5", "5"),
    ],
)
def test_ref_forms_and_normalization(ref, expected):
    assert keys(f"closes {ref}") == [expected]


@pytest.mark.parametrize(
    "text",
    [
        "prefixes #12",
        "unfixed #3",
        "fix_closes #4",
        "closes the bug in #9",
        "#5 is closed",
        "bare #5",
        "fixtures/foo#12",
        "fixesGH-5",
    ],
)
def test_negatives(text):
    assert keys(text) == []


def test_hyphen_is_a_boundary():
    assert keys("re-fixes #3") == ["3"]


def test_ref_chains():
    assert keys("Closes #1, #2") == ["1", "2"]
    assert keys("fixes #1 and #2") == ["1", "2"]
    assert keys("closes #1 & o/r#3") == ["1", "o/r#3"]
    assert keys("closes #1, and #2") == ["1", "2"]
    assert keys("closes #1 and fixes #2") == ["1", "2"]
    assert keys("closes #1 see #2") == ["1"]


def test_chain_across_lines_reports_own_line():
    matches = ck.find_closing_refs("closes #1,\n#2", SLUG)
    assert [(m.key, m.line) for m in matches] == [("1", 1), ("2", 2)]


@pytest.mark.parametrize(
    "text",
    [
        "`closes #5`",
        "```\ncloses #5\n```",
        "> closes #5",
        "<!-- closes #5 -->",
    ],
)
def test_no_exemptions(text):
    assert keys(text) == ["5"]


def test_1725_fixture():
    body = "\n".join(f"line {i}" for i in range(1, 60))
    body += "\n> H6 — yes. S2 is the fix that closes #1539.\ntrailing"
    matches = ck.find_closing_refs(body, SLUG)
    assert len(matches) == 1
    assert matches[0].key == "1539"
    assert matches[0].line == 60
    assert "closes #1539" in matches[0].snippet


def test_snippet_truncated():
    (m,) = ck.find_closing_refs("closes #1 " + "x" * 500, SLUG)
    assert len(m.snippet) == 120


def test_parse_declared():
    assert ck.parse_declared(["1539,12"], SLUG) == {"1539", "12"}
    assert ck.parse_declared(["1", "2", "1"], SLUG) == {"1", "2"}
    assert ck.parse_declared(["o/r#7"], SLUG) == {"o/r#7"}
    assert ck.parse_declared(["test-owner/test-repo#5"], SLUG) == {"5"}
    assert ck.parse_declared([], SLUG) == set()


@pytest.mark.parametrize("bad", ["abc", "#5", "5,", "", "o/r", "1,,2"])
def test_parse_declared_invalid(bad):
    with pytest.raises(ValueError):
        ck.parse_declared([bad], SLUG)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "commit", "-q", "--allow-empty", "-m", "base")
    _git(r, "checkout", "-q", "-b", "feat")
    _git(r, "commit", "-q", "--allow-empty", "-m", "clean subject")
    _git(r, "commit", "-q", "--allow-empty", "-m", "subject\n\nsome text\nfixes #77\nmore")
    return r


def test_read_commits(repo):
    commits = ck.read_commits(str(repo), "main..feat")
    assert len(commits) == 2
    sha, message = commits[0]
    assert len(sha) == 40
    matches = ck.find_closing_refs(message, SLUG)
    assert [(m.key, m.line) for m in matches] == [("77", 4)]
    assert ck.find_closing_refs(commits[1][1], SLUG) == []


def test_read_commits_git_failure(repo):
    with pytest.raises(RuntimeError):
        ck.read_commits(str(repo), "nope..feat")


def run_cli(*args: str):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "check", "--repo-slug", SLUG, *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_clean_exit_0():
    r = run_cli("--title", "plain title")
    assert r.returncode == 0 and r.stdout == ""


def test_cli_undeclared_exit_1(tmp_path):
    body = tmp_path / "b.md"
    body.write_text("x\ny\nfixes #12 and closes #3\n")
    r = run_cli("--title", "closes #99", "--body-file", str(body))
    assert r.returncode == 1
    assert r.stdout == "12,3,99\n"
    assert "body line 3" in r.stderr
    assert "title" in r.stderr
    assert "#99" in r.stderr
    assert "force-push" not in r.stderr


def test_cli_declared_exit_0(tmp_path):
    body = tmp_path / "b.md"
    body.write_text("fixes #12\n")
    r = run_cli("--body-file", str(body), "--closes", "12", "--closes", "3")
    assert r.returncode == 0


def test_cli_warn_unused(tmp_path):
    body = tmp_path / "b.md"
    body.write_text("nothing\n")
    r = run_cli("--body-file", str(body), "--closes", "99", "--warn-unused")
    assert r.returncode == 0
    assert "--closes 99 declared but no closing keyword" in r.stderr


def test_cli_title_starting_with_dash():
    r = run_cli("--title=-closes #4")
    assert r.returncode == 1 and r.stdout == "4\n"


def test_cli_commit_source_and_update_mode_hint(repo):
    r = run_cli("--repo-dir", str(repo), "--range", "main..feat")
    assert r.returncode == 1
    assert r.stdout == "77\n"
    assert "commit " in r.stderr and "line 4" in r.stderr
    assert "force-push" in r.stderr
    ok = run_cli("--repo-dir", str(repo), "--range", "main..feat", "--closes", "77")
    assert ok.returncode == 0


def test_cli_usage_errors_exit_2(tmp_path):
    assert run_cli("--closes", "abc").returncode == 2
    assert run_cli("--repo-dir", str(tmp_path)).returncode == 2
    assert run_cli("--range", "a..b").returncode == 2
    assert run_cli("--body-file", str(tmp_path / "missing")).returncode == 2


def test_cli_git_failure_exit_2(repo):
    r = run_cli("--repo-dir", str(repo), "--range", "nope..feat")
    assert r.returncode == 2 and r.stdout == ""


def test_cli_rejects_option_like_range(repo):
    r = run_cli("--repo-dir", str(repo), "--range=--all")
    assert r.returncode == 2
