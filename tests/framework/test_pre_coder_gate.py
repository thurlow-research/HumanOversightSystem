"""Tests for the #385 mechanical pre-coder gate (check_pre_coder_gate.sh).

Each test builds an isolated temporary git repo (REQ-385-28 — no dependence on the
real working tree) and shells out to the script via subprocess, asserting on exit
code and on the [GATE PASS]/[GATE FAIL] lines.

Committed vs staged-only is the load-bearing distinction (OQ-385-D): a `git add`
without a `git commit` must read as NOT committed and fail the gate.
"""
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "framework" / "check_pre_coder_gate.sh"

SLUG = "pre-coder-gate-script"


# ── helpers ──────────────────────────────────────────────────────────────────
def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t.test", "-c", "user.name=Test", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q")


def _write(repo: Path, rel: str, content: str = "x\n") -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def _commit_all(repo: Path, msg: str = "c") -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


def _run(repo: Path, *args: str, cwd: Path | None = None):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd or repo),
        capture_output=True,
        text=True,
    )


def _spec_path(slug: str = SLUG) -> str:
    return f"docs/specs/SPEC-{slug}.md"


def _td_path(slug: str = SLUG) -> str:
    return f"docs/v0.4.0/TECHNICAL-DESIGN-{slug}.md"


def _architect_path(slug: str = SLUG, stamp: str = "20260616") -> str:
    return f".claudetmp/design/architect-{slug}-{stamp}.md"


def _good_repo(tmp_path: Path) -> Path:
    """A repo where all three conditions pass: spec + TD committed, no architect file."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _write(repo, _spec_path())
    _write(repo, _td_path())
    _commit_all(repo)
    return repo


# ── all pass ─────────────────────────────────────────────────────────────────
def test_all_three_pass(tmp_path):
    repo = _good_repo(tmp_path)
    r = _run(repo, SLUG)
    assert r.returncode == 0, r.stderr
    assert "[GATE PASS]" in r.stdout
    assert SLUG in r.stdout


# ── condition 1: spec ────────────────────────────────────────────────────────
def test_c1_spec_absent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _write(repo, _td_path())
    _commit_all(repo)
    r = _run(repo, SLUG)
    assert r.returncode == 1
    assert "[GATE FAIL] SPEC" in r.stderr


def test_c1_spec_staged_only(tmp_path):
    # spec git-added but never committed → not committed (OQ-385-D)
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _write(repo, _td_path())
    _commit_all(repo)
    _write(repo, _spec_path())
    _git(repo, "add", _spec_path())  # staged, not committed
    r = _run(repo, SLUG)
    assert r.returncode == 1
    assert "[GATE FAIL] SPEC" in r.stderr


# ── condition 2: technical design ────────────────────────────────────────────
def test_c2_no_glob_match(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _write(repo, _spec_path())
    _commit_all(repo)
    r = _run(repo, SLUG)
    assert r.returncode == 1
    assert "[GATE FAIL] TECH-DESIGN" in r.stderr
    assert "absent" in r.stderr


def test_c2_staged_only(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _write(repo, _spec_path())
    _commit_all(repo)
    _write(repo, _td_path())
    _git(repo, "add", _td_path())  # staged, not committed
    r = _run(repo, SLUG)
    assert r.returncode == 1
    assert "[GATE FAIL] TECH-DESIGN" in r.stderr
    assert "not committed" in r.stderr


def test_c2_accepts_any_docs_v_prefix(tmp_path):
    # AC-385-06: any docs/v*/ directory prefix is accepted.
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _write(repo, _spec_path())
    _write(repo, f"docs/v1.2.3/TECHNICAL-DESIGN-{SLUG}.md")
    _commit_all(repo)
    r = _run(repo, SLUG)
    assert r.returncode == 0, r.stderr


# ── condition 3: architect verdict ───────────────────────────────────────────
def test_c3_request_changes_last(tmp_path):
    repo = _good_repo(tmp_path)
    _write(repo, _architect_path(), "status: REQUEST_CHANGES\n")
    _commit_all(repo)
    r = _run(repo, SLUG)
    assert r.returncode == 1
    assert "[GATE FAIL] ARCHITECT" in r.stderr
    assert _architect_path() in r.stderr


def test_c3_approved_after_request_changes_passes(tmp_path):
    # AC-385-07: last status: line wins, not first.
    repo = _good_repo(tmp_path)
    _write(
        repo,
        _architect_path(),
        "status: REQUEST_CHANGES\nsome notes\nstatus: APPROVED\n",
    )
    _commit_all(repo)
    r = _run(repo, SLUG)
    assert r.returncode == 0, r.stderr
    assert "[GATE PASS]" in r.stdout


def test_c3_request_changes_case_insensitive(tmp_path):
    # REQ-385-16: key and value matched case-insensitively.
    repo = _good_repo(tmp_path)
    _write(repo, _architect_path(), "Status: request_changes\n")
    _commit_all(repo)
    r = _run(repo, SLUG)
    assert r.returncode == 1
    assert "[GATE FAIL] ARCHITECT" in r.stderr


def test_c3_no_architect_file_passes(tmp_path):
    # REQ-385-18 / AC-385-08
    repo = _good_repo(tmp_path)
    r = _run(repo, SLUG)
    assert r.returncode == 0, r.stderr


# ── usage errors ─────────────────────────────────────────────────────────────
def test_no_args(tmp_path):
    repo = _good_repo(tmp_path)
    r = _run(repo)
    assert r.returncode == 2
    assert "[USAGE]" in r.stderr


def test_two_positional_args(tmp_path):
    repo = _good_repo(tmp_path)
    r = _run(repo, SLUG, "extra")
    assert r.returncode == 2


def test_unknown_flag(tmp_path):
    repo = _good_repo(tmp_path)
    r = _run(repo, "--nope")
    assert r.returncode == 2


@pytest.mark.parametrize("bad", ["Foo Bar", "a/b", "--", "UPPER", "trailing-", "-leading", "a--b"])
def test_invalid_slug(tmp_path, bad):
    # OQ-385-A: validate slug, exit 2, do not normalize.
    repo = _good_repo(tmp_path)
    r = _run(repo, bad)
    assert r.returncode == 2, f"{bad!r} should be rejected"
    assert "[USAGE]" in r.stderr


def test_not_a_git_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    r = _run(plain, SLUG)
    assert r.returncode == 2
    assert "[USAGE]" in r.stderr


def test_help_exits_zero(tmp_path):
    repo = _good_repo(tmp_path)
    r = _run(repo, "--help")
    assert r.returncode == 0
    assert "Usage" in r.stdout


# ── git-root resolution & no short-circuit ───────────────────────────────────
def test_subdir_invocation_resolves_git_root(tmp_path):
    # AC-385-09 / REQ-385-22: invoked from a subdir, gate still passes.
    repo = _good_repo(tmp_path)
    sub = repo / "scripts" / "deep"
    sub.mkdir(parents=True)
    r = _run(repo, SLUG, cwd=sub)
    assert r.returncode == 0, r.stderr
    assert "[GATE PASS]" in r.stdout


def test_all_three_fail_reports_all(tmp_path):
    # REQ-385-06: all conditions evaluated before exit, no short-circuit.
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    # commit something so HEAD exists but none of the gate files do
    _write(repo, "README.md")
    _write(repo, _architect_path(), "status: REQUEST_CHANGES\n")
    _commit_all(repo)
    r = _run(repo, SLUG)
    assert r.returncode == 1
    assert "[GATE FAIL] SPEC" in r.stderr
    assert "[GATE FAIL] TECH-DESIGN" in r.stderr
    assert "[GATE FAIL] ARCHITECT" in r.stderr
