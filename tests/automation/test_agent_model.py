"""Unit tests for bootstrap/lib/agent_model.py (#2359)."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent.parent / "bootstrap" / "lib" / "agent_model.py"


def _resolve(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "resolve", "--agent-file", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def _agent(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "agent.md"
    p.write_text(text)
    return p


def _ok(tmp_path: Path, frontmatter: str) -> str:
    r = _resolve(_agent(tmp_path, f"---\n{frontmatter}---\nbody\n"))
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _fails(r: subprocess.CompletedProcess, path: Path) -> None:
    assert r.returncode != 0
    assert r.stdout == ""
    assert str(path) in r.stderr
    assert len(r.stderr.strip().splitlines()) == 1


def test_happy_path(tmp_path):
    assert _ok(tmp_path, "name: x\nmodel: opus\ntools:\n  - Read\n") == "opus"


@pytest.mark.parametrize("raw", ['"opus"', "'opus'", "opus   ", "opus  # trailing comment"])
def test_quotes_whitespace_and_comment_are_stripped(tmp_path, raw):
    assert _ok(tmp_path, f"model: {raw}\n") == "opus"


def test_full_model_id_with_brackets_is_accepted(tmp_path):
    assert _ok(tmp_path, "model: claude-opus-4-8[1m]\n") == "claude-opus-4-8[1m]"


def test_missing_file(tmp_path):
    p = tmp_path / "nope.md"
    _fails(_resolve(p), p)


def test_no_frontmatter(tmp_path):
    p = _agent(tmp_path, "# just a heading\nmodel: opus\n")
    _fails(_resolve(p), p)


def test_unterminated_frontmatter(tmp_path):
    p = _agent(tmp_path, "---\nmodel: opus\n")
    _fails(_resolve(p), p)


def test_no_model_key(tmp_path):
    p = _agent(tmp_path, "---\nname: x\n---\nmodel: opus\n")
    _fails(_resolve(p), p)


@pytest.mark.parametrize("raw", ["", '""', "# only a comment"])
def test_empty_value(tmp_path, raw):
    p = _agent(tmp_path, f"---\nmodel: {raw}\n---\n")
    _fails(_resolve(p), p)


@pytest.mark.parametrize("raw", ["--evil", "-x", "opus;rm", "$(id)", "a b", "opus`x`"])
def test_unsafe_value(tmp_path, raw):
    p = _agent(tmp_path, f"---\nmodel: {raw}\n---\n")
    _fails(_resolve(p), p)


def test_nested_or_indented_model_is_not_read(tmp_path):
    p = _agent(tmp_path, "---\nname: x\nmeta:\n  model: opus\n---\n")
    _fails(_resolve(p), p)


@pytest.mark.parametrize("raw", ["inherit", "Inherit", "INHERIT", '"inherit"'])
def test_inherit_is_rejected(tmp_path, raw):
    p = _agent(tmp_path, f"---\nmodel: {raw}\n---\n")
    _fails(_resolve(p), p)
    assert "inherit" in _resolve(p).stderr


def test_duplicate_model_keys_fail_closed(tmp_path):
    p = _agent(tmp_path, "---\nmodel: opus\nname: x\nmodel: sonnet\n---\n")
    _fails(_resolve(p), p)
    assert "duplicate" in _resolve(p).stderr
