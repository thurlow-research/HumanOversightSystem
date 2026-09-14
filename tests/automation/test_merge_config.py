"""
Tests for scripts/automation/lib/merge_config.py — AD-9 configuration
resolution and repo identity (#1357 slice 1, TD §10 AD-13 item 3).

T3.1-T3.7 per docs/v0.7.0/TECHNICAL-DESIGN-1357-merge-authority-primitives.md
§10.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.automation.lib.merge_authority import RiskTier
from scripts.automation.lib.merge_config import ConfigError, resolve_config, resolve_repo_slug

# Mirrors scripts/framework/machine-accounts.env's real style: quotes, inline
# comments, and ${VAR} expansion for BOT_ACCOUNTS.
_FIXTURE_ENV = """\
BOT_WORKER_USERNAME="hos-worker-hos[bot]"      # GitHub App
BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"  # GitHub App
BOT_HUMAN_USERNAME="scottthurlow-claude[bot]"
COPILOT_BOT_LOGIN="copilot[bot]"
BOT_ACCOUNTS="${BOT_WORKER_USERNAME} ${BOT_OVERSEER_USERNAME} ${BOT_HUMAN_USERNAME} ${COPILOT_BOT_LOGIN}"
OVERSEER_CEILING="HIGH"
TIER_CEILING_CHECK_NAME="require-tier-ceiling"
HUMAN_REVIEWER="ScottThurlow"
"""


def _write_fixture_repo(tmp_path: Path, env_text: str | None = _FIXTURE_ENV) -> Path:
    root = tmp_path / "repo"
    fw = root / "scripts" / "framework"
    fw.mkdir(parents=True)
    if env_text is not None:
        (fw / "machine-accounts.env").write_text(env_text, encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# T3.1 — all six keys resolve
# --------------------------------------------------------------------------- #


def test_all_six_keys_resolve(tmp_path):
    root = _write_fixture_repo(tmp_path)
    config = resolve_config(root)
    assert config.human_reviewer == "ScottThurlow"
    assert config.overseer_handle == "hos-overseer-hos[bot]"
    assert config.worker_handle == "hos-worker-hos[bot]"
    assert config.tier_ceiling_check_name == "require-tier-ceiling"
    assert config.bot_accounts == frozenset(
        {
            "hos-worker-hos[bot]",
            "hos-overseer-hos[bot]",
            "scottthurlow-claude[bot]",
            "copilot[bot]",
        }
    )
    assert config.config_source == str(
        (root / "scripts" / "framework" / "machine-accounts.env").resolve()
    )


# --------------------------------------------------------------------------- #
# T3.2 — ceiling resolves to HIGH, explicitly not the library default LOW
# --------------------------------------------------------------------------- #


def test_overseer_ceiling_resolves_to_high_not_library_default_low(tmp_path):
    root = _write_fixture_repo(tmp_path)
    config = resolve_config(root)
    assert config.overseer_ceiling == RiskTier.HIGH
    assert config.overseer_ceiling != RiskTier.LOW


# --------------------------------------------------------------------------- #
# T3.3 — absent machine-accounts.env raises ConfigError, never SystemExit
# --------------------------------------------------------------------------- #


def test_absent_config_file_raises_config_error_not_system_exit(tmp_path):
    root = _write_fixture_repo(tmp_path, env_text=None)
    with pytest.raises(ConfigError):
        resolve_config(root)


# --------------------------------------------------------------------------- #
# T3.4 — each required key, removed or emptied, fails loud naming the key
# --------------------------------------------------------------------------- #


_REQUIRED_KEYS = (
    "OVERSEER_CEILING",
    "HUMAN_REVIEWER",
    "BOT_OVERSEER_USERNAME",
    "BOT_WORKER_USERNAME",
    "BOT_ACCOUNTS",
    "TIER_CEILING_CHECK_NAME",
)


@pytest.mark.parametrize("key", _REQUIRED_KEYS)
def test_missing_required_key_raises_config_error_naming_key(tmp_path, key):
    lines = [line for line in _FIXTURE_ENV.splitlines() if not line.startswith(f"{key}=")]
    root = _write_fixture_repo(tmp_path, env_text="\n".join(lines) + "\n")
    with pytest.raises(ConfigError, match=key):
        resolve_config(root)


@pytest.mark.parametrize("key", _REQUIRED_KEYS)
def test_empty_required_key_raises_config_error_naming_key(tmp_path, key):
    lines = []
    for line in _FIXTURE_ENV.splitlines():
        if line.startswith(f"{key}="):
            lines.append(f'{key}=""')
        else:
            lines.append(line)
    root = _write_fixture_repo(tmp_path, env_text="\n".join(lines) + "\n")
    with pytest.raises(ConfigError, match=key):
        resolve_config(root)


def test_config_error_message_names_the_file_path(tmp_path):
    lines = [line for line in _FIXTURE_ENV.splitlines() if not line.startswith("HUMAN_REVIEWER=")]
    root = _write_fixture_repo(tmp_path, env_text="\n".join(lines) + "\n")
    expected_path = str((root / "scripts" / "framework" / "machine-accounts.env").resolve())
    with pytest.raises(ConfigError, match=r".*machine-accounts\.env.*"):
        resolve_config(root)
    # Confirm the path really is resolvable from the fixture (sanity, not a
    # duplicate of the regex above).
    assert Path(expected_path).is_file()


# --------------------------------------------------------------------------- #
# T3.5 — an unrecognised OVERSEER_CEILING value fails loud, never falls back
# --------------------------------------------------------------------------- #


def test_unrecognised_overseer_ceiling_raises_config_error(tmp_path):
    lines = []
    for line in _FIXTURE_ENV.splitlines():
        if line.startswith("OVERSEER_CEILING="):
            lines.append('OVERSEER_CEILING="NOT_A_TIER"')
        else:
            lines.append(line)
    root = _write_fixture_repo(tmp_path, env_text="\n".join(lines) + "\n")
    with pytest.raises(ConfigError, match="OVERSEER_CEILING"):
        resolve_config(root)


# --------------------------------------------------------------------------- #
# T3.6 — delegation to require_tier_ceiling.load_env: comments, quotes, ${VAR}
# --------------------------------------------------------------------------- #


def test_delegates_parsing_inline_comments_quotes_and_var_expansion(tmp_path):
    root = _write_fixture_repo(tmp_path)
    config = resolve_config(root)
    # BOT_ACCOUNTS expands ${VAR} references to the four real logins, and the
    # inline "# GitHub App" comments on the first two lines were stripped.
    assert config.bot_accounts == frozenset(
        {
            "hos-worker-hos[bot]",
            "hos-overseer-hos[bot]",
            "scottthurlow-claude[bot]",
            "copilot[bot]",
        }
    )
    assert config.worker_handle == "hos-worker-hos[bot]"


# --------------------------------------------------------------------------- #
# T3.7 — resolve_repo_slug normalisation and rejection
# --------------------------------------------------------------------------- #


def test_resolve_repo_slug_normalises_ssh_url(tmp_path):
    root = _write_fixture_repo(tmp_path)
    assert resolve_repo_slug(root, explicit="o/r") == "o/r"


def test_resolve_repo_slug_from_ssh_remote(tmp_path, monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        class Result:
            stdout = "git@github.com:test-owner/test-repo.git\n"

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    root = _write_fixture_repo(tmp_path)
    assert resolve_repo_slug(root) == "test-owner/test-repo"


def test_resolve_repo_slug_from_https_remote(tmp_path, monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        class Result:
            stdout = "https://github.com/test-owner/test-repo.git\n"

        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    root = _write_fixture_repo(tmp_path)
    assert resolve_repo_slug(root) == "test-owner/test-repo"


def test_resolve_repo_slug_rejects_malformed_explicit(tmp_path):
    root = _write_fixture_repo(tmp_path)
    with pytest.raises(ConfigError):
        resolve_repo_slug(root, explicit="not-a-slug")
