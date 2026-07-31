"""
Tests for scripts/dev/commit_onto_base.sh — commit files onto a base ref without
a checkout.

The script exists because protected surfaces are mounted read-only in the
sandboxed Human clone, so `git checkout` fails partway through and desyncs the
index. These tests build a real throwaway repo and drive the real script as a
subprocess, asserting the resulting git objects — the working tree must be left
untouched, which is the whole point of the plumbing approach.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"

SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "dev" / "commit_onto_base.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway repo with one commit on `main` and two tracked files."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    (r / "tracked.md").write_text("original tracked\n")
    (r / "nested").mkdir()
    (r / "nested" / "deep.md").write_text("original deep\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base commit")
    return r


@pytest.fixture
def msg_file(tmp_path: Path) -> Path:
    p = tmp_path / "msg.txt"
    p.write_text("test: a commit message\n\nWith a body line.\n")
    return p


def test_commits_edited_file_without_touching_working_tree(repo, tmp_path, msg_file):
    """The core guarantee: the commit lands, the working tree is not modified."""
    edited = tmp_path / "edited.md"
    edited.write_text("EDITED CONTENT\n")

    res = _run(
        repo,
        "--base", "main",
        "--branch", "feature/x",
        "--message-file", str(msg_file),
        "--file", f"tracked.md={edited}",
    )
    assert res.returncode == 0, res.stderr

    # The branch points at a commit whose tree carries the edit...
    assert _git(repo, "show", "feature/x:tracked.md") == "EDITED CONTENT"
    # ...parented on main...
    assert _git(repo, "rev-parse", "feature/x^") == _git(repo, "rev-parse", "main")
    # ...and the working tree is untouched.
    assert (repo / "tracked.md").read_text() == "original tracked\n"
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_commit_message_is_taken_verbatim_from_file(repo, tmp_path, msg_file):
    edited = tmp_path / "e.md"
    edited.write_text("x\n")
    _run(
        repo,
        "--base", "main", "--branch", "b",
        "--message-file", str(msg_file),
        "--file", f"tracked.md={edited}",
    )
    body = _git(repo, "log", "-1", "--format=%B", "b")
    assert "test: a commit message" in body
    assert "With a body line." in body


def test_untouched_paths_are_preserved_from_base(repo, tmp_path, msg_file):
    """Only the named path changes; everything else comes from the base tree."""
    edited = tmp_path / "e.md"
    edited.write_text("changed\n")
    _run(
        repo,
        "--base", "main", "--branch", "b",
        "--message-file", str(msg_file),
        "--file", f"tracked.md={edited}",
    )
    assert _git(repo, "show", "b:nested/deep.md") == "original deep"
    names = _git(repo, "diff", "--name-only", "main", "b")
    assert names == "tracked.md"


def test_multiple_files_including_a_new_nested_path(repo, tmp_path, msg_file):
    a = tmp_path / "a.md"
    a.write_text("A\n")
    b = tmp_path / "b.md"
    b.write_text("B\n")
    res = _run(
        repo,
        "--base", "main", "--branch", "multi",
        "--message-file", str(msg_file),
        "--file", f"tracked.md={a}",
        "--file", f"newdir/created.md={b}",
    )
    assert res.returncode == 0, res.stderr
    assert _git(repo, "show", "multi:tracked.md") == "A"
    assert _git(repo, "show", "multi:newdir/created.md") == "B"


def test_dry_run_builds_tree_but_creates_no_commit(repo, tmp_path, msg_file):
    edited = tmp_path / "e.md"
    edited.write_text("dry\n")
    res = _run(
        repo,
        "--base", "main", "--branch", "nope",
        "--message-file", str(msg_file),
        "--file", f"tracked.md={edited}",
        "--dry-run",
    )
    assert res.returncode == 0, res.stderr
    branches = _git(repo, "branch", "--list", "nope")
    assert branches == ""


def test_identical_content_fails_rather_than_making_an_empty_commit(repo, tmp_path, msg_file):
    """A no-op tree is far more likely a mistake than an intent."""
    same = tmp_path / "same.md"
    same.write_text("original tracked\n")
    res = _run(
        repo,
        "--base", "main", "--branch", "b",
        "--message-file", str(msg_file),
        "--file", f"tracked.md={same}",
    )
    assert res.returncode != 0
    assert "identical" in res.stderr


def test_refuses_to_move_an_unrelated_existing_branch(repo, tmp_path, msg_file):
    """Fail closed: silently moving a branch would discard work."""
    _git(repo, "branch", "existing")
    (repo / "tracked.md").write_text("divergent\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "divergent work")
    _git(repo, "branch", "-f", "existing", "HEAD")
    _git(repo, "reset", "-q", "--hard", "HEAD~1")

    edited = tmp_path / "e.md"
    edited.write_text("new\n")
    res = _run(
        repo,
        "--base", "main", "--branch", "existing",
        "--message-file", str(msg_file),
        "--file", f"tracked.md={edited}",
    )
    assert res.returncode != 0
    assert "refusing to move" in res.stderr


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("/abs/path.md=SRC", "must be relative"),
        ("../escape.md=SRC", "must not contain"),
        ("noequalssign", "repo-path=source-path"),
    ],
)
def test_rejects_malformed_or_unsafe_repo_paths(repo, tmp_path, msg_file, spec, expected):
    src = tmp_path / "s.md"
    src.write_text("x\n")
    res = _run(
        repo,
        "--base", "main", "--branch", "b",
        "--message-file", str(msg_file),
        "--file", spec.replace("SRC", str(src)),
    )
    assert res.returncode != 0
    assert expected in res.stderr


def test_missing_source_file_fails_closed(repo, tmp_path, msg_file):
    res = _run(
        repo,
        "--base", "main", "--branch", "b",
        "--message-file", str(msg_file),
        "--file", f"tracked.md={tmp_path}/does-not-exist.md",
    )
    assert res.returncode != 0
    assert "source file not found" in res.stderr


def test_empty_message_file_fails_closed(repo, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("")
    edited = tmp_path / "e.md"
    edited.write_text("x\n")
    res = _run(
        repo,
        "--base", "main", "--branch", "b",
        "--message-file", str(empty),
        "--file", f"tracked.md={edited}",
    )
    assert res.returncode != 0
    assert "empty" in res.stderr


def test_unresolvable_base_ref_fails_closed(repo, tmp_path, msg_file):
    edited = tmp_path / "e.md"
    edited.write_text("x\n")
    res = _run(
        repo,
        "--base", "no/such/ref", "--branch", "b",
        "--message-file", str(msg_file),
        "--file", f"tracked.md={edited}",
    )
    assert res.returncode != 0
    assert "base ref does not resolve" in res.stderr
