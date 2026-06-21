"""
Tests for bin/lib/git-credentials.sh — deterministic git credentials for cron (#738).

The launcher must make `git push` work regardless of the host's credential
helper (Git Credential Manager / osxkeychain), which is unreachable from the
cron thin-env. These tests source the bash function via subprocess and assert
the real git behavior it produces — including the end-to-end credential fill,
which is what an actual push relies on.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

BASH = shutil.which("bash") or "/bin/bash"

GIT_CREDS_SH = (
    Path(__file__).parent.parent.parent / "bin" / "lib" / "git-credentials.sh"
)

# A `gh` stub speaking the credential-helper protocol: on `auth git-credential
# get` it prints a sentinel token. Used to prove git invokes *this* helper and
# not the host's.
FAKE_GH = """#!/usr/bin/env bash
if [[ "$1 $2" == "auth git-credential" && "$3" == "get" ]]; then
  echo "protocol=https"
  echo "host=github.com"
  echo "username=x-access-token"
  echo "password=SENTINEL_GH_TOKEN"
fi
"""


def _bash(script: str, env: dict, timeout: int = 10) -> subprocess.CompletedProcess:
    full = f"source {GIT_CREDS_SH}\n{script}"
    return subprocess.run(
        [BASH, "-c", full],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


@pytest.fixture
def isolated_home(tmp_path):
    """A throwaway HOME with a *hostile* global git config: the host helper is
    credential-manager-core, exactly the helper that breaks under cron."""
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "HOME": str(home)}
    # Drop any inherited GIT_CONFIG_* so each test starts from a clean slate.
    for k in list(env):
        if k.startswith("GIT_CONFIG_"):
            del env[k]
    subprocess.run(
        ["git", "config", "--global", "credential.helper", "credential-manager-core"],
        env=env, check=True,
    )
    return env, home


@pytest.fixture
def fake_gh(tmp_path):
    gh = tmp_path / "bin" / "gh"
    gh.parent.mkdir(parents=True)
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return gh


def test_exports_reset_then_gh_helper(isolated_home, fake_gh):
    """The function exports the empty-reset + url-scoped gh helper sequence."""
    env, _ = isolated_home
    result = _bash(
        f'hos_configure_git_credentials "{fake_gh}"\n'
        'echo "COUNT=$GIT_CONFIG_COUNT"\n'
        'echo "K0=$GIT_CONFIG_KEY_0 V0=[$GIT_CONFIG_VALUE_0]"\n'
        'echo "K1=$GIT_CONFIG_KEY_1 V1=$GIT_CONFIG_VALUE_1"\n',
        env,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "COUNT=3" in out
    # First entry resets the inherited helper list (empty value).
    assert "K0=credential.helper V0=[]" in out
    # Second entry scopes the gh helper to github.com.
    assert "K1=credential.https://github.com.helper" in out
    assert f"V1=!{fake_gh} auth git-credential" in out


def test_credential_fill_uses_gh_over_host_helper(isolated_home, fake_gh):
    """End-to-end: `git credential fill` for github.com returns the gh sentinel,
    even though the host configured credential-manager-core. This is the exact
    path a `git push` authenticates through."""
    env, _ = isolated_home
    result = _bash(
        f'hos_configure_git_credentials "{fake_gh}"\n'
        "printf 'protocol=https\\nhost=github.com\\n\\n' | git credential fill\n",
        env,
    )
    assert result.returncode == 0, result.stderr
    assert "password=SENTINEL_GH_TOKEN" in result.stdout
    assert "credential-manager-core" not in result.stdout


def test_does_not_mutate_global_gitconfig(isolated_home, fake_gh):
    """Constraint: configure the session only — never write the developer's
    global ~/.gitconfig."""
    env, home = isolated_home
    before = (home / ".gitconfig").read_text()
    result = _bash(f'hos_configure_git_credentials "{fake_gh}"\n', env)
    assert result.returncode == 0, result.stderr
    after = (home / ".gitconfig").read_text()
    assert before == after
    # The host helper is still the only thing on disk; gh lives only in env.
    assert "credential-manager-core" in after
    assert "gh auth git-credential" not in after


def test_token_never_materialized_in_config(isolated_home, fake_gh):
    """#734: the helper invokes gh; no token value is embedded in any exported
    config value (gh supplies it over stdin at fill time)."""
    env, _ = isolated_home
    result = _bash(
        f'hos_configure_git_credentials "{fake_gh}"\n'
        "env | grep '^GIT_CONFIG_VALUE_'\n",
        env,
    )
    assert result.returncode == 0, result.stderr
    assert "SENTINEL_GH_TOKEN" not in result.stdout
    # GH_TOKEN-style material must not leak into config values.
    assert "ghp_" not in result.stdout
    assert "x-access-token" not in result.stdout


def test_fails_when_gh_absent(isolated_home):
    """No gh on PATH → non-zero return and no GIT_CONFIG_* exported, so the
    launcher can fail fast instead of silently mis-pushing."""
    env, _ = isolated_home
    env["PATH"] = "/nonexistent"
    result = _bash(
        'hos_configure_git_credentials ""\n'
        'echo "COUNT=[${GIT_CONFIG_COUNT:-unset}]"\n',
        env,
    )
    assert "COUNT=[unset]" in result.stdout
    assert "gh not found" in result.stderr


def test_appends_to_existing_git_config_entries(isolated_home, fake_gh):
    """If GIT_CONFIG_* entries already exist, the function appends rather than
    clobbering index 0."""
    env, _ = isolated_home
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "user.name"
    env["GIT_CONFIG_VALUE_0"] = "preexisting"
    result = _bash(
        f'hos_configure_git_credentials "{fake_gh}"\n'
        'echo "COUNT=$GIT_CONFIG_COUNT"\n'
        'echo "K0=$GIT_CONFIG_KEY_0"\n'
        'echo "K1=$GIT_CONFIG_KEY_1"\n',
        env,
    )
    assert result.returncode == 0, result.stderr
    assert "COUNT=4" in result.stdout
    # Pre-existing entry untouched; new entries appended after it.
    assert "K0=user.name" in result.stdout
    assert "K1=credential.helper" in result.stdout
