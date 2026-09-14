"""
merge_config.py — AD-9 configuration resolution and repo identity (#1357).

Resolves the six machine-account keys `decide_merge_authority` needs from
`<repo_root>/scripts/framework/machine-accounts.env` — never from the
library's own defaults (which disagree with this repo's configuration; see
ADR-1357 AF-4) and never from an environment variable (AD-2 rule 5).

Parsing is delegated to `scripts/framework/require_tier_ceiling.py`'s
`load_env`, loaded by file path because `scripts/framework` is not an
importable package (TD-VF-4). This module contains zero `=`-splitting,
quote-stripping, or `${VAR}`-expansion code of its own (AD-9's "do not coin a
third env parser").
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scripts.automation.lib.merge_authority import RiskTier

# The six AD-9 keys — all mandatory, no defaults, fail loud on any missing or
# empty value.
_REQUIRED_KEYS = (
    "OVERSEER_CEILING",
    "HUMAN_REVIEWER",
    "BOT_OVERSEER_USERNAME",
    "BOT_WORKER_USERNAME",
    "BOT_ACCOUNTS",
    "TIER_CEILING_CHECK_NAME",
)


class ConfigError(Exception):
    """Raised when AD-9 configuration cannot be resolved."""


@dataclass(frozen=True)
class MergeConfig:
    overseer_ceiling: RiskTier
    human_reviewer: str
    overseer_handle: str
    worker_handle: str
    bot_accounts: frozenset[str]
    tier_ceiling_check_name: str
    config_source: str


def _load_require_tier_ceiling():
    """Load require_tier_ceiling.py by file path (TD-VF-4 — scripts/framework
    is not a package). Mirrors merge_authority._load_audit_log's idiom for
    the same trust-direction reason."""
    path = Path(__file__).resolve().parents[2] / "framework" / "require_tier_ceiling.py"
    spec = importlib.util.spec_from_file_location("hos_require_tier_ceiling", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def resolve_config(repo_root: str | Path) -> MergeConfig:
    """Resolve AD-9 configuration from `<repo_root>/scripts/framework/machine-accounts.env`.

    Raises ConfigError (never SystemExit — `load_env` calls `sys.exit(2)` on a
    missing file, which is the wrong exit code for this surface) when the
    file is absent, a required key is missing/empty, or OVERSEER_CEILING is
    not a recognised RiskTier.
    """
    root = Path(repo_root)
    config_path = root / "scripts" / "framework" / "machine-accounts.env"

    if not config_path.is_file():
        raise ConfigError(f"machine-accounts.env not found at {config_path}")

    require_tier_ceiling = _load_require_tier_ceiling()
    try:
        env = require_tier_ceiling.load_env(config_path)
    except SystemExit as exc:
        raise ConfigError(
            f"require_tier_ceiling.load_env failed to parse {config_path}: {exc}"
        ) from exc

    missing = [key for key in _REQUIRED_KEYS if not env.get(key, "").strip()]
    if missing:
        raise ConfigError(
            f"machine-accounts.env at {config_path} is missing or has an empty "
            f"value for: {', '.join(missing)}"
        )

    try:
        overseer_ceiling = RiskTier.from_str(env["OVERSEER_CEILING"].strip())
    except KeyError as exc:
        raise ConfigError(
            f"OVERSEER_CEILING={env['OVERSEER_CEILING']!r} in {config_path} is not "
            f"a recognised risk tier"
        ) from exc

    bot_accounts = frozenset(env["BOT_ACCOUNTS"].split())

    return MergeConfig(
        overseer_ceiling=overseer_ceiling,
        human_reviewer=env["HUMAN_REVIEWER"].strip(),
        overseer_handle=env["BOT_OVERSEER_USERNAME"].strip(),
        worker_handle=env["BOT_WORKER_USERNAME"].strip(),
        bot_accounts=bot_accounts,
        tier_ceiling_check_name=env["TIER_CEILING_CHECK_NAME"].strip(),
        config_source=str(config_path.resolve()),
    )


_REPO_SLUG_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def resolve_repo_slug(repo_root: str | Path, explicit: str | None = None) -> str:
    """Resolve the `owner/repo` slug — from `explicit` (validated) if given,
    else from the `origin` remote of the checkout at `repo_root`.

    Raises ConfigError if `explicit` is malformed, or if the remote cannot be
    read or parsed.
    """
    if explicit is not None:
        if not _REPO_SLUG_RE.match(explicit):
            raise ConfigError(f"--repo value is not a valid owner/repo slug: {explicit!r}")
        return explicit

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError) as exc:
        raise ConfigError(f"could not read git remote 'origin' at {repo_root}: {exc}") from exc

    url = result.stdout.strip()
    slug = url
    if slug.startswith("git@github.com:"):
        slug = slug[len("git@github.com:") :]
    elif slug.startswith("https://github.com/"):
        slug = slug[len("https://github.com/") :]
    if slug.endswith(".git"):
        slug = slug[: -len(".git")]

    if not _REPO_SLUG_RE.match(slug):
        raise ConfigError(f"could not parse owner/repo from origin remote: {url!r}")
    return slug
