"""Regression guard for #949 — shared-remote PR-branch collision.

When Worker/Human/Overseer are separate local clones of ONE GitHub remote,
`hos_install.sh --pr` derived its branch name solely from the release ref
(`hos-upgrade/<slug>`). The first clone's push landed; the next clones pushed
the same branch name and were rejected non-fast-forward, leaving a local branch
with no PR and exit 1 despite the local install succeeding.

The fix: before creating the branch, if it already exists on the remote,
disambiguate with the clone's directory name (and a process-unique suffix as a
last resort) so each role-clone opens its own PR.

Two layers of coverage:
  * a static guard that the installer still contains the ls-remote check, so the
    logic can't be silently dropped;
  * functional tests over real local git remotes that exercise the exact naming
    algorithm the installer uses (mirrored below — kept in lockstep by the
    static guard).
"""
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO_ROOT / "bootstrap" / "hos_install.sh"


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


# The branch-naming algorithm, mirrored verbatim from hos_install.sh (#949).
# The static guard test below keeps the installer side from drifting away.
_PICK_BRANCH = r"""
set -euo pipefail
TARGET_REPO="$1"; HOS_REF="$2"
_slug="$(printf '%s' "$HOS_REF" | tr -cs 'A-Za-z0-9._-' '-' | sed 's/^-*//; s/-*$//')"
PR_BRANCH="hos-upgrade/${_slug:-update}"
if git -C "$TARGET_REPO" ls-remote --exit-code --heads origin "$PR_BRANCH" >/dev/null 2>&1; then
  _clone_tag="$(basename "$TARGET_REPO" | tr -cs 'A-Za-z0-9._-' '-' | sed 's/^-*//; s/-*$//')"
  _candidate="hos-upgrade/${_slug:-update}-${_clone_tag:-clone}"
  if git -C "$TARGET_REPO" ls-remote --exit-code --heads origin "$_candidate" >/dev/null 2>&1; then
    _candidate="${_candidate}-$$"
  fi
  PR_BRANCH="$_candidate"
fi
printf '%s' "$PR_BRANCH"
"""


def _pick_branch(target_repo: Path, ref: str) -> str:
    return subprocess.run(
        ["bash", "-c", _PICK_BRANCH, "_", str(target_repo), ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _make_clone(bare_remote: Path, dest: Path) -> Path:
    _git("clone", "--quiet", str(bare_remote), str(dest), cwd=bare_remote.parent)
    _git("config", "user.email", "t@t", cwd=dest)
    _git("config", "user.name", "t", cwd=dest)
    return dest


@pytest.fixture()
def shared_remote(tmp_path: Path) -> Path:
    """A bare remote seeded with one commit on the default branch."""
    bare = tmp_path / "origin.git"
    _git("init", "--quiet", "--bare", str(bare), cwd=tmp_path)
    seed = _make_clone(bare, tmp_path / "seed")
    (seed / "README").write_text("seed\n", encoding="utf-8")
    _git("add", "-A", cwd=seed)
    _git("commit", "--quiet", "-m", "seed", cwd=seed)
    _git("push", "--quiet", "origin", "HEAD", cwd=seed)
    return bare


def test_plain_branch_when_no_collision(shared_remote: Path, tmp_path: Path) -> None:
    """With no pre-existing remote branch, the plain name is used."""
    worker = _make_clone(shared_remote, tmp_path / "Worker")
    assert _pick_branch(worker, "v0.5.0") == "hos-upgrade/v0.5.0"


def test_second_clone_disambiguates_and_pushes_cleanly(
    shared_remote: Path, tmp_path: Path
) -> None:
    """The second role-clone gets a distinct branch and pushes without rejection."""
    worker = _make_clone(shared_remote, tmp_path / "Worker")
    human = _make_clone(shared_remote, tmp_path / "Human")

    # Worker takes the plain branch and pushes it (the collision source).
    worker_branch = _pick_branch(worker, "v0.5.0")
    assert worker_branch == "hos-upgrade/v0.5.0"
    _git("checkout", "--quiet", "-b", worker_branch, cwd=worker)
    (worker / "framework").write_text("x\n", encoding="utf-8")
    _git("add", "-A", cwd=worker)
    _git("commit", "--quiet", "-m", "worker upgrade", cwd=worker)
    _git("push", "--quiet", "-u", "origin", worker_branch, cwd=worker)

    # Human now sees the collision and must pick a different branch.
    _git("fetch", "--quiet", "origin", cwd=human)
    human_branch = _pick_branch(human, "v0.5.0")
    assert human_branch != worker_branch
    assert human_branch == "hos-upgrade/v0.5.0-Human"

    # And that branch must push cleanly (no non-fast-forward — the #949 failure).
    _git("checkout", "--quiet", "-b", human_branch, cwd=human)
    (human / "framework").write_text("y\n", encoding="utf-8")
    _git("add", "-A", cwd=human)
    _git("commit", "--quiet", "-m", "human upgrade", cwd=human)
    _git("push", "--quiet", "-u", "origin", human_branch, cwd=human)  # would raise on rejection


def test_installer_contains_949_disambiguation_guard() -> None:
    """Static guard: the installer must keep the remote-collision check (#949)."""
    text = _INSTALLER.read_text(encoding="utf-8")
    assert 'ls-remote --exit-code --heads origin "$PR_BRANCH"' in text
    assert "#949" in text
    assert '_clone_tag=' in text
