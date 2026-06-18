"""
Operator-local activation gate for the HOS automation loop (R13.4).

The activation file (~/.hos/<repo-id>/ACTIVE) is the FIRST check on every
cron wake.  If absent, unreadable, empty, or token-mismatched → OFF.
ZERO other activity — no probe, no GitHub API call, no model invocation.

The two-key enable (activation AND repo authorization in governance config)
means the loop cannot self-enable: changing the committed governance config
requires a human-approved PR (CODEOWNERS-gated), and the local activation
file is outside the repo and never committed.
"""

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# repo-id slug derivation (MF-4 — single source of truth)
# ---------------------------------------------------------------------------

def _normalize_remote_url(url: str) -> tuple[str, str]:
    """
    Extract (owner, repo) from an HTTPS or SSH GitHub remote URL.

    Handles:
      https://github.com/owner/repo.git
      git@github.com:owner/repo.git
      https://github.com/owner/repo
    Returns (owner, repo) both lowercased, repo without .git suffix.
    """
    url = url.strip()

    # SSH form: git@github.com:owner/repo.git
    ssh_match = re.match(r"git@github\.com:([^/]+)/(.+?)(?:\.git)?$", url, re.IGNORECASE)
    if ssh_match:
        return ssh_match.group(1).lower(), ssh_match.group(2).lower()

    # HTTPS form: https://github.com/owner/repo[.git]
    https_match = re.match(
        r"https?://github\.com/([^/]+)/(.+?)(?:\.git)?/?$", url, re.IGNORECASE
    )
    if https_match:
        return https_match.group(1).lower(), https_match.group(2).lower()

    raise ValueError(f"Cannot derive owner/repo from remote URL: {url!r}")


def derive_repo_id(repo_root: Optional[str | Path] = None) -> str:
    """
    Derive the <repo-id> slug for the given repo root (or cwd).

    Algorithm (MF-4):
    1. git remote get-url origin
    2. Normalize to (owner, repo) — strip scheme/host, strip .git
    3. Lowercase; join with '-'

    Example:
      https://github.com/thurlow-research/HumanOversightSystem.git
      → "thurlow-research-humanoversightsystem"
    """
    cwd = str(repo_root) if repo_root else None
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True, check=False,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read git remote origin: {result.stderr.strip()}"
        )
    remote_url = result.stdout.strip()
    owner, repo = _normalize_remote_url(remote_url)
    return f"{owner}-{repo}"


# ---------------------------------------------------------------------------
# Machine-token resolution (fail-closed at every branch)
# ---------------------------------------------------------------------------

def _hos_dir(repo_id: str) -> Path:
    return Path.home() / ".hos" / repo_id


def _resolve_machine_token(repo_id: str) -> Optional[str]:
    """
    Resolve the ONE canonical machine token per the R13.4 contract.

    1. If MACHINE-TOKEN exists and is readable and non-empty → return UUID from it.
    2. If MACHINE-TOKEN exists but empty or unreadable → return None (OFF).
    3. If MACHINE-TOKEN absent → return hostname -f.

    Returns None to signal OFF.  Never returns an empty string.
    """
    machine_token_path = _hos_dir(repo_id) / "MACHINE-TOKEN"

    if machine_token_path.exists():
        # MACHINE-TOKEN present — must be readable and non-empty.
        try:
            content = machine_token_path.read_text(encoding="utf-8").strip()
        except (OSError, PermissionError):
            return None  # Unreadable → OFF.
        if not content:
            return None  # Empty → OFF (interrupted hos activate --uuid).
        return content

    # MACHINE-TOKEN absent → use hostname -f.
    result = subprocess.run(
        ["hostname", "-f"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None  # Cannot resolve hostname → OFF.
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Activation check (R13.4 · R13.2)
# ---------------------------------------------------------------------------

def check_activation(repo_root: Optional[str | Path] = None) -> bool:
    """
    The very first gate on every cron wake.

    Returns True (ACTIVE) only if BOTH conditions hold:
      1. ~/.hos/<repo-id>/ACTIVE is a readable, non-empty file.
      2. Its trimmed content byte-equals the canonical machine token.

    Any other outcome — absent, unreadable, empty, mismatch — → False (OFF).
    NEVER raises; all failure paths return False.
    """
    try:
        repo_id = derive_repo_id(repo_root)
    except (RuntimeError, ValueError, OSError):
        return False

    active_path = _hos_dir(repo_id) / "ACTIVE"

    # Condition 1: file must exist, be readable, and non-empty.
    if not active_path.is_file():
        return False
    try:
        file_token = active_path.read_text(encoding="utf-8").strip()
    except (OSError, PermissionError):
        return False
    if not file_token:
        return False

    # Condition 2: single equality against the canonical machine token.
    canonical = _resolve_machine_token(repo_id)
    if canonical is None:
        return False

    return file_token == canonical


# ---------------------------------------------------------------------------
# hos activate / hos deactivate helpers (R13.4 — operator CLI)
# ---------------------------------------------------------------------------

def activate(
    repo_root: Optional[str | Path] = None,
    use_uuid: bool = False,
    verify_orchestrator: bool = True,
) -> str:
    """
    Write ~/.hos/<repo-id>/ACTIVE with the canonical machine token.

    With use_uuid=False (default): writes hostname -f and creates no sidecar.
    With use_uuid=True: generates a UUID, writes it to both MACHINE-TOKEN
    and ACTIVE (for operators with unstable hostnames).
    With verify_orchestrator=True (default): raises RuntimeError if
    scripts/automation/hos_orchestrator.sh is absent or not executable —
    prevents activating a setup where the cron target doesn't exist yet.
    Pass verify_orchestrator=False to skip this check (e.g. during build).

    Returns the repo-id slug for confirmation.
    Raises RuntimeError on any failure (e.g. cannot resolve git remote).
    """
    if verify_orchestrator:
        root = Path(repo_root).resolve() if repo_root else Path.cwd()
        orchestrator = root / "scripts" / "automation" / "hos_orchestrator.sh"
        if not orchestrator.is_file() or not os.access(str(orchestrator), os.X_OK):
            raise RuntimeError(
                f"hos_orchestrator.sh not found or not executable at {orchestrator} — "
                "build Phase C first, or pass verify_orchestrator=False to skip"
            )

    repo_id = derive_repo_id(repo_root)
    hos_dir = _hos_dir(repo_id)
    hos_dir.mkdir(parents=True, exist_ok=True)

    if use_uuid:
        token = str(uuid.uuid4())
        machine_token_path = hos_dir / "MACHINE-TOKEN"
        machine_token_path.write_text(token + "\n", encoding="utf-8")
    else:
        result = subprocess.run(
            ["hostname", "-f"], capture_output=True, text=True, check=False
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError("Cannot resolve hostname -f for activation token")
        token = result.stdout.strip()

    active_path = hos_dir / "ACTIVE"
    active_path.write_text(token + "\n", encoding="utf-8")
    return repo_id


def deactivate(repo_root: Optional[str | Path] = None) -> str:
    """
    Remove ~/.hos/<repo-id>/ACTIVE.

    Returns the repo-id slug for confirmation.
    Idempotent — does not raise if the file is already absent.
    """
    repo_id = derive_repo_id(repo_root)
    active_path = _hos_dir(repo_id) / "ACTIVE"
    active_path.unlink(missing_ok=True)
    return repo_id
