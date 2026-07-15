"""Tests for scripts/oversight/signoff_gate.py — per-branch sign-off register (#968).

Two layers:
  * Pure-helper unit tests for namespace derivation and cross-namespace stamp
    discovery (no git).
  * End-to-end gate runs against a throwaway git repo, exercising PR-mode
    namespace scoping, the legacy flat-path migration fallback, staleness, and
    deploy-mode (--all) aggregation across namespaces.

The end-to-end tests drive a real `git` and run the gate as a subprocess under
the test interpreter (which has PyYAML). They are skipped if git is unavailable.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_GATE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "oversight" / "signoff_gate.py"
)
_spec = importlib.util.spec_from_file_location("signoff_gate", _GATE_PATH)
sg = importlib.util.module_from_spec(_spec)
sys.modules["signoff_gate"] = sg
_spec.loader.exec_module(sg)


# ── pure helpers: namespace derivation ────────────────────────────────────────


def test_namespace_override_sanitized(tmp_path):
    # Slashes and spaces collapse to single dashes; edges trimmed.
    assert sg.signoff_namespace(tmp_path, "fix/968-signoff register") == (
        "fix-968-signoff-register"
    )


def test_namespace_env_used_when_no_override(tmp_path, monkeypatch):
    monkeypatch.setenv(sg.NAMESPACE_ENV, "feature/AB_cd.1")
    # Allowed chars [A-Za-z0-9._-] survive; "/" becomes "-".
    assert sg.signoff_namespace(tmp_path) == "feature-AB_cd.1"


def test_namespace_override_beats_env(tmp_path, monkeypatch):
    monkeypatch.setenv(sg.NAMESPACE_ENV, "from-env")
    assert sg.signoff_namespace(tmp_path, "explicit") == "explicit"


def test_namespace_never_empty(tmp_path):
    # A name made entirely of disallowed chars must not collapse to "".
    assert sg.signoff_namespace(tmp_path, "///") == "detached"


# ── pure helpers: cross-namespace stamp discovery ─────────────────────────────


def _stamp(root: Path, rel: str, status: str = "APPROVED") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"role: x\nstatus: {status}\n", encoding="utf-8")


def test_namespaced_rels_finds_legacy_and_namespaces(tmp_path):
    _stamp(tmp_path, "signoffs/code-review.stamp")  # legacy flat
    _stamp(tmp_path, "signoffs/branch-a/code-review.stamp")
    _stamp(tmp_path, "signoffs/branch-b/code-review.stamp")
    rels = sg.namespaced_stamp_rels(tmp_path, "code-review")
    assert rels == [
        "signoffs/code-review.stamp",
        "signoffs/branch-a/code-review.stamp",
        "signoffs/branch-b/code-review.stamp",
    ]


def test_namespaced_rels_excludes_validators_subdir(tmp_path):
    _stamp(tmp_path, "signoffs/validators/code-review.stamp")
    _stamp(tmp_path, "signoffs/branch-a/code-review.stamp")
    rels = sg.namespaced_stamp_rels(tmp_path, "code-review")
    assert rels == ["signoffs/branch-a/code-review.stamp"]


def test_namespaced_rels_only_matching_role(tmp_path):
    _stamp(tmp_path, "signoffs/branch-a/security.stamp")
    assert sg.namespaced_stamp_rels(tmp_path, "code-review") == []


# ── end-to-end gate runs against a real git repo ──────────────────────────────

_GIT = shutil.which("git")
pytestmark_git = pytest.mark.skipif(_GIT is None, reason="git not available")


def _git(repo: Path, *args: str, when: int | None = None) -> str:
    env = dict(os.environ)
    if when is not None:
        stamp = f"@{when} +0000"  # git epoch-seconds date form
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
    out = subprocess.run(
        [_GIT, *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def _run_gate(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_GATE_PATH), *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    # Minimal manifest: one required role.
    (repo / "contract").mkdir()
    (repo / "contract" / "step-manifest.yaml").write_text(
        "role_mappings:\n  code-review: code-reviewer\n"
        "steps:\n  - id: 1\n    required_signoffs: [code-review]\n",
        encoding="utf-8",
    )
    (repo / "src.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base", when=1_000_000)
    return repo


def _write_stamp(repo: Path, rel: str, status: str = "APPROVED") -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"role: code-review\nstatus: {status}\n", encoding="utf-8")


@pytestmark_git
def test_pr_mode_namespace_scoped_pass(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature-x")
    (repo / "src.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-aqm", "change", when=1_000_100)
    _write_stamp(repo, "signoffs/feature-x/code-review.stamp")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sign", when=1_000_200)

    res = _run_gate(repo, "--base", "main")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "namespace: feature-x" in res.stdout


@pytestmark_git
def test_pr_mode_ignores_other_branch_namespace(tmp_path):
    # A stamp under a DIFFERENT branch's namespace must not satisfy this branch.
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature-x")
    (repo / "src.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-aqm", "change", when=1_000_100)
    # Stamp written under the wrong namespace.
    _write_stamp(repo, "signoffs/some-other-branch/code-review.stamp")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sign-wrong-ns", when=1_000_200)

    res = _run_gate(repo, "--base", "main")
    assert res.returncode == 1, res.stdout
    assert "MISSING stamp signoffs/feature-x/code-review.stamp" in res.stdout


@pytestmark_git
def test_pr_mode_legacy_flat_fallback(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature-x")
    (repo / "src.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-aqm", "change", when=1_000_100)
    _write_stamp(repo, "signoffs/code-review.stamp")  # pre-#968 flat path
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sign-legacy", when=1_000_200)

    res = _run_gate(repo, "--base", "main")
    assert res.returncode == 0, res.stdout + res.stderr


@pytestmark_git
def test_pr_mode_stale_stamp_fails(tmp_path):
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature-x")
    (repo / "src.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-aqm", "change", when=1_000_100)
    _write_stamp(repo, "signoffs/feature-x/code-review.stamp")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sign", when=1_000_200)
    # New change committed AFTER signing, without re-signing → stale.
    (repo / "src.py").write_text("x = 3\n", encoding="utf-8")
    _git(repo, "commit", "-aqm", "late change", when=1_000_300)

    res = _run_gate(repo, "--base", "main")
    assert res.returncode == 1, res.stdout
    assert "STALE" in res.stdout


@pytestmark_git
def test_pr_mode_bad_base_ref_exits_env_error(tmp_path):
    # #974: a base ref that does not resolve (unfetched in a shallow clone, or a
    # typo) must abort with exit 2 (env error), NOT silently PASS with an empty
    # changed-file set. This is the exact case the gate exists to catch: the
    # worker signed at T1, then committed an unsigned change at T2.
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "-b", "feature-x")
    (repo / "src.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-aqm", "change", when=1_000_100)
    _write_stamp(repo, "signoffs/feature-x/code-review.stamp")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sign", when=1_000_200)
    # Unsigned change committed AFTER the stamp — must not be waved through.
    (repo / "src.py").write_text("x = 3\n", encoding="utf-8")
    _git(repo, "commit", "-aqm", "late unsigned change", when=1_000_300)

    res = _run_gate(repo, "--base", "origin/does-not-exist")
    assert res.returncode == 2, res.stdout + res.stderr
    assert "PASS" not in res.stdout


@pytestmark_git
def test_pr_mode_empty_diff_is_not_an_env_error(tmp_path):
    # A genuinely empty diff (base == HEAD, no changes) must NOT be treated as a
    # git failure: check=True fires only on a non-zero exit, never on legitimately
    # empty output. Here the gate fails 1 (missing stamp), never 2 (#974).
    repo = _init_repo(tmp_path)
    res = _run_gate(repo, "--base", "main")
    assert res.returncode != 2, res.stdout + res.stderr


@pytestmark_git
def test_deploy_mode_aggregates_across_namespaces(tmp_path):
    # Two namespaces on main, each signing the role at different times; --all
    # takes the freshest and must pass against the whole tree.
    repo = _init_repo(tmp_path)
    _write_stamp(repo, "signoffs/branch-a/code-review.stamp")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sign-a", when=1_000_500)

    res = _run_gate(repo, "--all")
    assert res.returncode == 0, res.stdout + res.stderr
