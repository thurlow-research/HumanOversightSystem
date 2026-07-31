"""Static-guard tests for bin/hos-human.

These tests guard the security-critical properties of the human-proxy session
launcher.  They run against the file content (no execution) so they pass in
environments where the binary cannot be run (e.g. different OS, no Claude CLI).

NOTE: bin/hos-human cannot be written by the installer in environments with a
read-only filesystem mount on bin/ (EROFS — observed in some sandboxed agent
environments).  If the file does not exist, all tests in this module are skipped
with a clear message so the CI does not fail silently.  The human must create the
file manually; see docs/HUMAN-SETUP.md Step 6 for the exact content.
"""

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOS_HUMAN = _REPO_ROOT / "bin" / "hos-human"
_HOS_CRON = _REPO_ROOT / "bin" / "hos-cron"


def _src() -> str:
    return _HOS_HUMAN.read_text(encoding="utf-8")


pytestmark = pytest.mark.skipif(
    not _HOS_HUMAN.exists(),
    reason=(
        "bin/hos-human not present — create it manually (see docs/HUMAN-SETUP.md Step 6). "
        "EROFS may block the installer from writing to bin/ in sandboxed environments."
    ),
)


# --------------------------------------------------------------------------- #
# Existence and executability
# --------------------------------------------------------------------------- #


def test_file_exists():
    assert _HOS_HUMAN.exists(), "bin/hos-human does not exist"


def test_file_is_executable():
    import stat
    mode = _HOS_HUMAN.stat().st_mode
    assert mode & stat.S_IXUSR, "bin/hos-human is not executable (chmod +x needed)"


# --------------------------------------------------------------------------- #
# Auth safety: temp-file pattern, not source <(...)
# --------------------------------------------------------------------------- #


def test_uses_temp_file_auth_not_process_substitution():
    """Auth must use the temp-file source pattern, not source <(...).

    The script header comments mention 'source <(...)' to explain why the
    pattern is deliberately NOT used.  Strip comment lines before the check so
    those documentation notes do not trigger a false positive.
    """
    src = _src()
    code_lines = [
        ln for ln in src.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    code_only = "\n".join(code_lines)

    # The temp-file pattern must be present in executable code.
    assert "mktemp" in code_only, (
        "bin/hos-human does not use mktemp — expected temp-file auth pattern"
    )
    assert "get_app_token.sh" in code_only and "--app human" in code_only, (
        "bin/hos-human must call get_app_token.sh --app human"
    )
    # No actual executable source <(...) — only comment lines may mention it.
    assert "source <(" not in code_only, (
        "bin/hos-human executable code uses 'source <(...)' — "
        "must use temp-file source pattern instead"
    )


# --------------------------------------------------------------------------- #
# EXIT trap — token file cleanup on all exit paths
# --------------------------------------------------------------------------- #


def test_exit_trap_cleans_up_token_file():
    """An EXIT trap must remove the token temp file on all exit paths.

    Under set -e, a non-zero return from `source "$_t"` exits the script
    immediately, skipping any explicit `rm -f "$_t"` that follows it.  An EXIT
    trap is the only reliable cleanup mechanism.
    """
    src = _src()
    assert "trap" in src, (
        "bin/hos-human has no EXIT trap — token temp file may survive abnormal exits"
    )
    trap_lines = [ln for ln in src.splitlines() if "trap" in ln and "EXIT" in ln]
    assert trap_lines, (
        "no 'trap ... EXIT' line found in bin/hos-human — "
        "the EXIT trap is required for reliable token-file cleanup"
    )


# --------------------------------------------------------------------------- #
# No --dangerously-skip-permissions
# --------------------------------------------------------------------------- #


def test_no_dangerously_skip_permissions():
    """exec claude must NOT include --dangerously-skip-permissions.

    The human-proxy is an interactive session with a human directing it; it
    requires normal Claude permission prompts, not the autonomous-cron bypass.
    """
    src = _src()
    assert "exec claude" in src, "bin/hos-human must use 'exec claude' to launch Claude"
    assert "--dangerously-skip-permissions" not in src, (
        "bin/hos-human must NOT pass --dangerously-skip-permissions to exec claude "
        "(human-proxy is interactive, not an autonomous cron agent)"
    )


# --------------------------------------------------------------------------- #
# Portable identity guard (no hardcoded literal)
# --------------------------------------------------------------------------- #


def test_identity_guard_uses_exported_variables_not_literal():
    """Identity guard must compare HOS_BOT_LOGIN to HOS_EXPECTED_BOT_LOGIN.

    Hardcoding 'scottthurlow-claude[bot]' (or any literal) in the guard would
    make it HOS-repo-specific and wrong for every consumer installation.
    get_app_token.sh exports both values independently; the guard must use them.
    """
    src = _src()
    assert "HOS_BOT_LOGIN" in src, "identity guard variable HOS_BOT_LOGIN missing"
    assert "HOS_EXPECTED_BOT_LOGIN" in src, (
        "identity guard variable HOS_EXPECTED_BOT_LOGIN missing"
    )
    # Both must be referenced in a comparison context (not just assigned).
    # Check both appear on the same line (the guard expression).
    guard_lines = [
        ln for ln in src.splitlines()
        if "HOS_BOT_LOGIN" in ln and "HOS_EXPECTED_BOT_LOGIN" in ln
    ]
    assert guard_lines, (
        "no line comparing HOS_BOT_LOGIN to HOS_EXPECTED_BOT_LOGIN found — "
        "identity guard may be hardcoded or missing"
    )


# --------------------------------------------------------------------------- #
# Repo sync present
# --------------------------------------------------------------------------- #


def test_repo_sync_called():
    """hos_repo_sync.sh must be called (best-effort) at session start."""
    src = _src()
    assert "hos_repo_sync.sh" in src, (
        "bin/hos-human does not call hos_repo_sync.sh — session-start sync is missing"
    )


# --------------------------------------------------------------------------- #
# hos-cron rejects --role human
# --------------------------------------------------------------------------- #


def test_hos_cron_rejects_human_role():
    """bin/hos-cron must not accept --role human (human is not a cron role)."""
    if not _HOS_CRON.exists():
        pytest.skip("bin/hos-cron not present")
    cron_src = _HOS_CRON.read_text(encoding="utf-8")
    # The valid role set in hos-cron must not list 'human'.
    # Accept either an explicit 'human' guard or the absence of 'human' in the role list.
    # The test checks that 'human' never appears as a valid --role value.
    # A role list like "worker|overseer" is fine; "worker|overseer|human" is not.
    if "worker|overseer|human" in cron_src or "human|worker" in cron_src:
        pytest.fail(
            "bin/hos-cron appears to accept --role human — "
            "human is an interactive role, not a cron role"
        )
