r"""Regression guards for hos_install.sh hardening — #991, #992, #993, #998.

Four independent fail-open/corruption bugs in ``bootstrap/hos_install.sh``:

* **#991** — the ``--release`` fast path ``git archive``-exports whatever a
  *local* tag points at, never comparing its SHA against the published release.
  A re-cut tag (same name, new commit) or a same-named tag in a vendored target
  repo installs stale/foreign content stamped as the validated release.
* **#992** — the single-brace placeholder engine interpolated config values
  directly into a perl ``s|||`` replacement string, so ``@``/``$``/``\`` in a
  value corrupted the agent (or killed the whole perl run) — silently, because
  the error was swallowed by ``2>/dev/null || true``.
* **#993** — in the ``--pr`` flow ``fail()`` does not exit, so a rejected commit
  fell through to an unconditional ``git checkout "$PR_ORIG_BRANCH"`` that
  carried the still-staged upgrade onto the base branch while claiming it was
  untouched.
* **#998** — the version-skip adjacency gate recomputed the target tag with a
  *second* ``gh release view`` when ``--release`` was flagless, even though
  ``resolve_hos_source`` already resolved and published-gate-checked it into
  ``$HOS_REF``. A transient failure of that duplicate query emptied
  ``_install_tag`` and silently skipped the whole adjacency gate — installing
  skipped versions unsequenced. Fixed by reusing ``$HOS_REF``.

Each bug gets two layers of coverage (mirrors the #949 test convention):

  * a **static guard** asserting the installer still contains the fix, so the
    logic can't be silently dropped in a later edit;
  * a **functional** test over the exact corrected logic the installer runs
    (mirrored below — kept in lockstep by the static guard).
"""
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALLER = _REPO_ROOT / "bootstrap" / "hos_install.sh"
_SRC = _INSTALLER.read_text(encoding="utf-8")


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _seed_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "--quiet", str(path), cwd=path.parent)
    _git("config", "user.email", "t@t", cwd=path)
    _git("config", "user.name", "t", cwd=path)
    _git("config", "commit.gpgsign", "false", cwd=path)
    return path


# --------------------------------------------------------------------------- #
# #992 — placeholder substitution must pass values via %ENV, never interpolate
# --------------------------------------------------------------------------- #

# The exact perl invocation the installer's _substitute_into runs (#992).
_SUBST_SNIPPET = r"""
set -euo pipefail
f="$1"
HOS_SUBST_N="$2" HOS_SUBST_V="$3" perl -i -pe 's/\{\Q$ENV{HOS_SUBST_N}\E\}/$ENV{HOS_SUBST_V}/g' "$f"
"""

_NASTY_VALUE = r"R&D @ Acme $x \n |pipe|"


def _run_subst(target_file: Path, name: str, value: str) -> None:
    subprocess.run(
        ["bash", "-c", _SUBST_SNIPPET, "_", str(target_file), name, value],
        check=True,
        capture_output=True,
        text=True,
    )


def test_env_substitution_preserves_at_dollar_backslash(tmp_path):
    """A value with @/$/\\/| substitutes verbatim — no perl-metachar corruption."""
    tf = tmp_path / "agent.md"
    tf.write_text("Project {PROJECT_NAME}; again {PROJECT_NAME}.\n", encoding="utf-8")
    _run_subst(tf, "PROJECT_NAME", _NASTY_VALUE)
    out = tf.read_text(encoding="utf-8")
    assert out == f"Project {_NASTY_VALUE}; again {_NASTY_VALUE}.\n"
    # The old bug dropped everything from the first '@' or mangled '$'/'\'.
    assert "@ Acme" in out and "$x" in out


def test_installer_uses_env_substitution_and_surfaces_errors():
    """Static guard: installer uses the %ENV perl form and no longer swallows errors."""
    assert r"perl -i -pe 's/\{\Q$ENV{HOS_SUBST_N}\E\}/$ENV{HOS_SUBST_V}/g'" in _SRC, (
        "the %ENV-based substitution (#992) was dropped from hos_install.sh"
    )
    # The old vulnerable interpolation must be gone.
    assert r'-e "s|\{${_n}\}|${_val}|g;"' not in _SRC, (
        "the value-interpolating perl arg (#992 bug) is back in hos_install.sh"
    )
    # _substitute_into must surface a perl failure via fail(), not `|| true`.
    assert "Placeholder substitution failed" in _SRC


# --------------------------------------------------------------------------- #
# #993 — a rejected --pr commit must NOT carry staged changes onto the base branch
# --------------------------------------------------------------------------- #

# The corrected commit / return-to-base control flow, mirrored from hos_install.sh.
_PR_FLOW_SNIPPET = r"""
set -euo pipefail
TARGET_REPO="$1"; PR_ORIG_BRANCH="$2"; PR_BRANCH="$3"
git -C "$TARGET_REPO" add -A
_pr_commit_failed=false
if ! git -C "$TARGET_REPO" commit -q -m "chore(hos): upgrade" 2>/dev/null; then
  _pr_commit_failed=true
fi
if $_pr_commit_failed; then
  :  # #993: stay on PR_BRANCH — never checkout the base with changes still staged
elif git -C "$TARGET_REPO" checkout "$PR_ORIG_BRANCH" >/dev/null 2>&1; then
  :
fi
git -C "$TARGET_REPO" rev-parse --abbrev-ref HEAD
"""


def test_rejected_commit_keeps_upgrade_off_base_branch(tmp_path):
    """With a rejecting pre-commit hook, the staged upgrade stays on PR_BRANCH."""
    repo = _seed_repo(tmp_path / "target")
    (repo / "README").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "--quiet", "-m", "seed", cwd=repo)
    base = _git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).strip()

    # Fork the PR branch from base with no commits (the installer's setup).
    _git("checkout", "--quiet", "-b", "hos-upgrade/vX", cwd=repo)

    # A pre-commit hook that rejects the machine commit (the #993 trigger).
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    # Stage the "upgrade".
    (repo / "framework.md").write_text("upgrade\n", encoding="utf-8")

    head = subprocess.run(
        ["bash", "-c", _PR_FLOW_SNIPPET, "_", str(repo), base, "hos-upgrade/vX"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # We must NOT have returned to the base branch.
    assert head == "hos-upgrade/vX", f"expected to stay on PR branch, got {head!r}"
    # And the base branch's tree must not contain the staged upgrade.
    r = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-e", f"{base}:framework.md"],
        capture_output=True,
    )
    assert r.returncode != 0, "the upgrade file leaked onto the base branch (#993)"


def test_installer_guards_base_checkout_on_commit_failure():
    """Static guard: the return-to-base checkout is gated by the commit-failed flag."""
    assert "_pr_commit_failed=true" in _SRC
    assert "if $_pr_commit_failed; then" in _SRC, (
        "the #993 guard around `git checkout \"$PR_ORIG_BRANCH\"` was dropped"
    )


# --------------------------------------------------------------------------- #
# #991 — the fast path must compare the local tag SHA against the published one
# --------------------------------------------------------------------------- #

# Mirrors _local_tag_matches_published's ls-remote comparison (the network-free
# fallback path; the installer prefers `gh api` when available).
_MATCH_SNIPPET = r"""
set -euo pipefail
LOCAL_REPO="$1"; PUBLISHED_URL="$2"; ref="$3"
local_sha="$(git -C "$LOCAL_REPO" rev-parse -q --verify "refs/tags/${ref}^{commit}" 2>/dev/null || true)"
remote_sha="$(git ls-remote "$PUBLISHED_URL" "refs/tags/${ref}^{}" 2>/dev/null | awk 'NR==1{print $1}')"
[[ -n "$remote_sha" ]] || remote_sha="$(git ls-remote "$PUBLISHED_URL" "refs/tags/${ref}" 2>/dev/null | awk 'NR==1{print $1}')"
if [[ -n "$local_sha" && -n "$remote_sha" && "$local_sha" == "$remote_sha" ]]; then
  echo MATCH
else
  echo MISMATCH
fi
"""


def _matches(local_repo: Path, published: Path, ref: str) -> str:
    return subprocess.run(
        ["bash", "-c", _MATCH_SNIPPET, "_", str(local_repo), str(published), ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture()
def published_and_local(tmp_path):
    """A published bare repo tagged v1, and a local clone with the same tag."""
    work = _seed_repo(tmp_path / "pub-work")
    (work / "f").write_text("v1\n", encoding="utf-8")
    _git("add", "-A", cwd=work)
    _git("commit", "--quiet", "-m", "release 1", cwd=work)
    _git("tag", "-a", "v1", "-m", "v1", cwd=work)

    published = tmp_path / "published.git"
    _git("clone", "--quiet", "--bare", str(work), str(published), cwd=tmp_path)
    _git("push", "--quiet", str(published), "v1", cwd=work)

    local = tmp_path / "local"
    _git("clone", "--quiet", str(published), str(local), cwd=tmp_path)
    return published, local, work


def test_matching_local_tag_passes(published_and_local):
    """A local tag at the published commit verifies as a match (fast path allowed)."""
    published, local, _ = published_and_local
    assert _matches(local, published, "v1") == "MATCH"


def test_recut_tag_detected_as_mismatch(published_and_local):
    """A re-cut published tag (same name, new commit) is detected as a mismatch."""
    published, local, work = published_and_local
    # Re-cut v1 on a NEW commit and force-push the moved tag to the published repo.
    (work / "f").write_text("v1-recut\n", encoding="utf-8")
    _git("add", "-A", cwd=work)
    _git("commit", "--quiet", "-m", "release 1 (re-cut)", cwd=work)
    _git("tag", "-f", "-a", "v1", "-m", "v1 re-cut", cwd=work)
    _git("push", "--quiet", "--force", str(published), "v1", cwd=work)
    # The local clone still points v1 at the OLD commit → must NOT be trusted.
    assert _matches(local, published, "v1") == "MISMATCH"


def test_installer_gates_fast_path_on_published_match():
    """Static guard: the fast-path git archive is gated by _local_tag_matches_published."""
    assert 'if _local_tag_matches_published "$ref"; then' in _SRC, (
        "the #991 SHA-verification gate around the fast-path git archive was dropped"
    )
    assert "_published_release_commit" in _SRC
    # The authoritative remote is $HOS_REPO, and annotated tags are peeled to a commit.
    assert 'refs/tags/${ref}^{}' in _SRC


# --------------------------------------------------------------------------- #
# #998 — the adjacency gate must reuse the already-resolved $HOS_REF, never
#        re-query the target tag (a transient failure would skip the gate).
# --------------------------------------------------------------------------- #

# Two mirrors of the target-tag resolution + gate-entry decision: the corrected
# form (reuses $HOS_REF) and the old buggy form (re-queries, empties on failure).
# A "transient" re-query failure is simulated by _requery returning non-zero.
_ADJ_FIXED_SNIPPET = r"""
set -euo pipefail
INSTALLED_TAG="$1"; RELEASE_REF="$2"; HOS_REF="$3"
_requery() { return 1; }   # simulate a transient `gh release view` failure
# Corrected #998 logic: reuse the already resolved+gate-checked ref.
_install_tag="$HOS_REF"
if [[ -n "$_install_tag" && "$INSTALLED_TAG" != "$_install_tag" ]]; then
  echo "GATE_RUNS:$_install_tag"
else
  echo "GATE_SKIPPED"
fi
"""

_ADJ_BUGGY_SNIPPET = r"""
set -euo pipefail
INSTALLED_TAG="$1"; RELEASE_REF="$2"; HOS_REF="$3"
_requery() { return 1; }   # simulate a transient `gh release view` failure
# Old #998 bug: re-query when flagless; a transient failure empties _install_tag.
_install_tag="$RELEASE_REF"
if [[ -z "$_install_tag" ]]; then
  _install_tag="$(_requery 2>/dev/null || true)"
fi
if [[ -n "$_install_tag" && "$INSTALLED_TAG" != "$_install_tag" ]]; then
  echo "GATE_RUNS:$_install_tag"
else
  echo "GATE_SKIPPED"
fi
"""


def _adj(snippet: str, installed: str, release_ref: str, hos_ref: str) -> str:
    return subprocess.run(
        ["bash", "-c", snippet, "_", installed, release_ref, hos_ref],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_flagless_upgrade_runs_gate_via_hos_ref_despite_requery_failure():
    """Corrected: a flagless (empty RELEASE_REF) upgrade uses $HOS_REF, so the
    adjacency gate still runs even when a re-query would have failed."""
    out = _adj(_ADJ_FIXED_SNIPPET, installed="v0.3.0", release_ref="", hos_ref="v0.6.0")
    assert out == "GATE_RUNS:v0.6.0"


def test_old_requery_form_would_skip_gate_on_transient_failure():
    """Regression contrast: the old re-query form empties the target tag on a
    transient failure and silently skips the gate — the exact #998 fail-open."""
    out = _adj(_ADJ_BUGGY_SNIPPET, installed="v0.3.0", release_ref="", hos_ref="v0.6.0")
    assert out == "GATE_SKIPPED"


def test_installer_reuses_hos_ref_for_adjacency_target():
    """Static guard: the adjacency gate reuses $HOS_REF and no longer re-queries."""
    assert '_install_tag="$HOS_REF"' in _SRC, (
        "the #998 fix (reuse the resolved $HOS_REF) was dropped from hos_install.sh"
    )
    # The old duplicate `gh release view ... --json tagName` re-query command must
    # be gone from the version-skip block (prose comments may still name it).
    _skip_block = _SRC[_SRC.index("Version-skip detection") :]
    assert "gh release view --repo" not in _skip_block, (
        "the #998 duplicate `gh release view` re-query is back in the adjacency gate"
    )
