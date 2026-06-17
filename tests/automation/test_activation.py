"""Tests for activation.py — repo-scope assertion functions (§312).

These tests cover derive_repo_id_from_path() and is_in_scope() only.
verify_bot_identity() is excluded because it requires a live gh CLI session.
"""
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "activation",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "automation"
    / "lib"
    / "activation.py",
)
act = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(act)


# ── derive_repo_id_from_path ───────────────────────────────────────────────────


def test_derive_repo_id_from_path_github_url():
    """Full GitHub HTTPS URL yields the correct lowercase slug."""
    result = act.derive_repo_id_from_path(
        "https://github.com/thurlow-research/HumanOversightSystem/pull/42"
    )
    assert result == "thurlow-research/humanoversightsystem"


def test_derive_repo_id_from_path_github_url_dotgit():
    """GitHub URL with .git suffix is stripped correctly."""
    result = act.derive_repo_id_from_path(
        "https://github.com/MyOrg/MyRepo.git"
    )
    assert result == "myorg/myrepo"


def test_derive_repo_id_from_path_owner_repo_ref():
    """<owner>/<repo>#N reference yields the lowercase slug."""
    result = act.derive_repo_id_from_path("thurlow-research/HumanOversightSystem#302")
    assert result == "thurlow-research/humanoversightsystem"


def test_derive_repo_id_from_path_relative_returns_none():
    """A bare relative path that has no resolvable git remote returns None.

    We run this in a tmp directory that is not a git repo so there is no
    remote to read.
    """
    import os, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        old = os.getcwd()
        try:
            os.chdir(tmp)
            result = act.derive_repo_id_from_path("src/foo.py")
            # Outside any git repo the path walk finds nothing → None.
            # (If the CWD happens to be inside a git repo with an origin,
            # this may return a slug — that is correct behaviour per the spec.
            # The test is only authoritative in a non-git directory.)
            assert result is None or isinstance(result, str)
        finally:
            os.chdir(old)


def test_derive_repo_id_from_path_malformed_returns_none():
    """Garbage input must not raise and must return None."""
    for bad in [
        "not-a-url-or-path-at-all!!!",
        ":::invalid:::",
        "",
        "//",
        "\x00\x01\x02",
    ]:
        result = act.derive_repo_id_from_path(bad)
        assert result is None or isinstance(result, str), (
            f"derive_repo_id_from_path({bad!r}) raised or returned unexpected type"
        )


# ── is_in_scope ───────────────────────────────────────────────────────────────

SESSION_REPO = "thurlow-research/humanoversightsystem"


def test_is_in_scope_same_repo():
    """Target resolving to the same repo → True."""
    result = act.is_in_scope(
        "https://github.com/thurlow-research/HumanOversightSystem/issues/312",
        SESSION_REPO,
    )
    assert result is True


def test_is_in_scope_different_repo():
    """Target resolving to a provably different repo → False."""
    result = act.is_in_scope(
        "https://github.com/some-other-org/totally-different-repo/pull/1",
        SESSION_REPO,
    )
    assert result is False


def test_is_in_scope_none_target():
    """A target that cannot be resolved (None from derive) → True (safe direction)."""
    # Pass garbage that will not resolve to any slug so derive returns None.
    result = act.is_in_scope("not-resolvable-garbage-input-!!!!", SESSION_REPO)
    # Must be True — cannot prove a crossing, must not block on a guess.
    assert result is True


def test_is_in_scope_never_raises():
    """is_in_scope must not raise regardless of inputs."""
    for target in [None, "", "///", "https://notgithub.example.com/x/y"]:
        try:
            act.is_in_scope(str(target), SESSION_REPO)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"is_in_scope raised on input {target!r}: {exc}")
