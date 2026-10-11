"""Regression tests for the four script defects in #1828.

1. run_redteam_sample.sh passed the non-existent `--merges=false` to git log and
   hid the failure behind `2>/dev/null`, so it always sampled zero commits.
2. reverify_self.sh aborted under `set -euo pipefail` on a grep for commits that
   do not exist; the diff base is now --base / Reviewed-Commit / hard error.
3. review_self.sh hard-required agy even with `--reviewer codex`.
4. check_agents_static.sh crashed on an agent file with no `name:` key.

Each behavioral test copies only the script's dependencies into an isolated
tmp_path layout (script locates REPO_ROOT relative to its own directory).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    return subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def _scaffold(repo: Path, *names: str) -> None:
    """Copy the named scripts plus the vendor_invoke library they source."""
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy(SCRIPTS / name, repo / "scripts" / name)
    shutil.copytree(
        SCRIPTS / "oversight" / "lib",
        repo / "scripts" / "oversight" / "lib",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(
        SCRIPTS / "oversight" / "run_with_retry.sh",
        repo / "scripts" / "oversight" / "run_with_retry.sh",
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "-q", "-b", "main")


def _env(tmp_path: Path, path: str | None = None) -> dict:
    tmpdir = tmp_path / "tmpdir"
    tmpdir.mkdir(exist_ok=True)
    env = {**os.environ, "TMPDIR": str(tmpdir)}
    if path is not None:
        env["PATH"] = path
    return env


def _commit(repo: Path, fname: str, message: str) -> str:
    (repo / fname).write_text(message)
    _git(repo, "add", fname)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


# ── 1. run_redteam_sample.sh ─────────────────────────────────────────────────


def test_redteam_sample_static_git_log_flags():
    text = (SCRIPTS / "run_redteam_sample.sh").read_text()
    assert "--merges=false" not in text
    log_lines = [ln for ln in text.splitlines() if "git log" in ln and "--since" in ln]
    assert log_lines, "git log --since invocation not found"
    for ln in log_lines:
        assert "--no-merges" in ln
        assert "--oneline" not in ln
        assert "2>/dev/null" not in ln


def test_redteam_sample_selects_recent_low_commits(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _scaffold(repo, "run_redteam_sample.sh")
    _commit(repo, "a.txt", "base\n")
    _commit(repo, "b.txt", "low one\n\nAI-Risk: LOW\n")
    _commit(repo, "c.txt", "medium one\n\nAI-Risk: MEDIUM\n")
    result = subprocess.run(
        ["bash", "scripts/run_redteam_sample.sh", "--dry-run"],
        cwd=repo,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Found 1 LOW-tier commits in pool" in result.stdout


def test_redteam_sample_empty_window_uses_no_data_path(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _scaffold(repo, "run_redteam_sample.sh")
    _commit(repo, "a.txt", "no trailer\n")
    result = subprocess.run(
        ["bash", "scripts/run_redteam_sample.sh", "--dry-run"],
        cwd=repo,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Found 0 LOW-tier commits in pool" in result.stdout


def test_redteam_sample_git_failure_is_surfaced(tmp_path):
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    _scaffold(not_a_repo, "run_redteam_sample.sh")
    env = _env(tmp_path)
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    result = subprocess.run(
        ["bash", "scripts/run_redteam_sample.sh", "--dry-run"],
        cwd=not_a_repo,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "git log failed" in result.stderr


# ── 2. reverify_self.sh ──────────────────────────────────────────────────────


def _reverify_repo(tmp_path: Path, review_text: str):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _scaffold(repo, "reverify_self.sh")
    first = _commit(repo, "a.txt", "one\n")
    _commit(repo, "b.txt", "two\n")
    review = repo / "review-test.md"
    review.write_text(review_text.replace("@FIRST@", first))
    return repo, review, first


def _reverify(repo: Path, tmp_path: Path, *args: str):
    return subprocess.run(
        ["bash", "scripts/reverify_self.sh", "--dry-run", *args],
        cwd=repo,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
    )


def test_reverify_no_base_and_no_reviewed_commit_fails(tmp_path):
    repo, review, _ = _reverify_repo(tmp_path, "# Self-Review\nTimestamp: x\n")
    result = _reverify(repo, tmp_path, "--review", str(review))
    assert result.returncode != 0
    assert "--base" in result.stderr


def test_reverify_bad_base_fails_with_actionable_message(tmp_path):
    repo, review, _ = _reverify_repo(tmp_path, "# Self-Review\n")
    result = _reverify(repo, tmp_path, "--review", str(review), "--base", "no-such-ref")
    assert result.returncode != 0
    assert "no-such-ref" in result.stderr
    assert "--base" in result.stderr


def test_reverify_option_like_base_is_rejected(tmp_path):
    repo, review, _ = _reverify_repo(tmp_path, "# Self-Review\n")
    result = _reverify(repo, tmp_path, "--review", str(review), "--base", "--all")
    assert result.returncode != 0
    assert "does not resolve" in result.stderr


def test_reverify_recorded_commit_resolves(tmp_path):
    repo, review, first = _reverify_repo(
        tmp_path, "# Self-Review\nReviewed-Commit: @FIRST@\n---\nbody\n"
    )
    result = _reverify(repo, tmp_path, "--review", str(review))
    assert result.returncode == 0, result.stdout + result.stderr
    assert first in result.stdout
    assert "DRY RUN" in result.stdout


def test_reverify_recorded_commit_gone_fails(tmp_path):
    repo, review, _ = _reverify_repo(
        tmp_path, "# Self-Review\nReviewed-Commit: " + "0" * 40 + "\n---\nbody\n"
    )
    result = _reverify(repo, tmp_path, "--review", str(review))
    assert result.returncode != 0
    assert "0" * 40 in result.stderr


def test_reverify_explicit_base_overrides_recorded(tmp_path):
    repo, review, first = _reverify_repo(
        tmp_path, "# Self-Review\nReviewed-Commit: " + "0" * 40 + "\n---\nbody\n"
    )
    result = _reverify(repo, tmp_path, "--review", str(review), "--base", first)
    assert result.returncode == 0, result.stdout + result.stderr


# ── 3. review_self.sh ────────────────────────────────────────────────────────


def test_review_self_codex_does_not_require_agy(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _scaffold(repo, "review_self.sh")
    head = _commit(repo, "a.txt", "one\n")

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    codex = fakebin / "codex"
    codex.write_text("#!/bin/sh\ncat >/dev/null\necho 'No findings.'\n")
    codex.chmod(0o755)
    path = f"{fakebin}:/usr/bin:/bin"
    if shutil.which("agy", path=path):
        pytest.skip("agy present in system PATH dirs; cannot build agy-less PATH")

    result = subprocess.run(
        ["bash", "scripts/review_self.sh", "--reviewer", "codex"],
        cwd=repo,
        env=_env(tmp_path, path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "agy not found" not in result.stdout + result.stderr
    reviews = list((repo / ".claudetmp" / "self-review").glob("review-*.md"))
    assert len(reviews) == 1
    text = reviews[0].read_text()
    assert f"Reviewed-Commit: {head}\n" in text
    assert text.index("Reviewed-Commit:") < text.index("\n---\n")


def test_review_self_dry_run_needs_no_reviewer_cli(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    _scaffold(repo, "review_self.sh")
    path = "/usr/bin:/bin"
    result = subprocess.run(
        ["bash", "scripts/review_self.sh", "--reviewer", "codex", "--dry-run"],
        cwd=repo,
        env=_env(tmp_path, path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ── 4. check_agents_static.sh ────────────────────────────────────────────────


def test_check_agents_static_missing_name_is_finding_not_crash(tmp_path):
    (tmp_path / "scripts" / "framework").mkdir(parents=True)
    shutil.copy(
        SCRIPTS / "framework" / "check_agents_static.sh",
        tmp_path / "scripts" / "framework" / "check_agents_static.sh",
    )
    (tmp_path / "scripts" / "oversight").mkdir(parents=True)
    shutil.copy(
        SCRIPTS / "oversight" / "agents_static_logic.py",
        tmp_path / "scripts" / "oversight" / "agents_static_logic.py",
    )
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "a-nameless.md").write_text("---\ndescription: no name key\n---\n\nbody\n")
    (agents / "b-good.md").write_text(
        "---\nname: b-good\ndescription: x\nmodel: sonnet\n---\n\nbody\n"
    )
    result = subprocess.run(
        ["bash", "scripts/framework/check_agents_static.sh"],
        cwd=tmp_path,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "No 'name:' frontmatter in .claude/agents/a-nameless.md" in result.stdout
    # the script kept going past section 1 to the end-of-run summary
    assert "finding(s) require attention" in result.stdout


def test_reverify_ignores_reviewed_commit_in_body(tmp_path):
    repo, review, _ = _reverify_repo(
        tmp_path, "# Self-Review\nTimestamp: x\n---\nReviewed-Commit: @FIRST@\n"
    )
    result = _reverify(repo, tmp_path, "--review", str(review))
    assert result.returncode != 0
    assert "--base" in result.stderr
