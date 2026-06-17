"""
activation.py — Runtime activation helpers for the HOS autonomous worker.

verify_bot_identity() guards against a common operator mistake: running the
worker in a shell where a human admin's `gh` session is still active.  If the
active gh identity isn't the expected bot account, commits and PRs would be
attributed to the human, contaminating the audit trail and sending notifications
from their account.

derive_repo_id_from_path() and is_in_scope() implement the §312 repo-scope
assertion: the worker calls is_in_scope(target, session_repo_id) before acting
on any file/PR/issue it did not itself create this session. False only when the
target PROVABLY resolves to a different repo — bare relative paths and
indeterminate inputs are safe-direction True (cannot prove a crossing).
"""

import logging
import re
import subprocess
from typing import Optional


def verify_bot_identity(bot_username: str, repo_root=None) -> bool:
    """
    Verify that gh is currently authenticated as bot_username.

    Returns True if authenticated as the expected bot, False otherwise.
    Logs a warning if the active account is a human (non-bot) account.

    Args:
        bot_username: The expected GitHub login for the bot account
                      (e.g. "HOSWorkerTutelare").
        repo_root:    Unused; reserved for future per-repo gh-host lookup.
    """
    result = subprocess.run(
        ["gh", "api", "user", "--jq", ".login"],
        capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        logging.warning(
            "verify_bot_identity: 'gh api user' failed (exit %d). "
            "Is gh installed and authenticated?",
            result.returncode,
        )
        return False
    current = result.stdout.strip()
    if current.lower() != bot_username.lower():
        logging.warning(
            "Identity mismatch: gh is authenticated as '%s' but expected '%s'. "
            "PRs and commits will be attributed to the wrong account. "
            "Run: provision_agent_account.sh %s --pat <BOT_PAT>",
            current,
            bot_username,
            "worker" if "worker" in bot_username.lower() else "overseer",
        )
        return False
    return True


# ── Repo-scope assertion helpers (§312) ───────────────────────────────────────
# Normalization rule (PRD R6.1 / R13.4): lowercase owner and repo, strip .git,
# no trailing slash.  ONE canonical algorithm shared by both functions so there
# is never a second, divergent slug path in this module.

_GITHUB_URL_RE = re.compile(
    r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.#?\s]+)",
    re.IGNORECASE,
)
_OWNER_REPO_REF_RE = re.compile(
    r"^(?P<owner>[A-Za-z0-9_.\-]+)/(?P<repo>[A-Za-z0-9_.\-]+)(?:#\d+)?$"
)


def _normalize_slug(owner: str, repo: str) -> str:
    """Return the canonical lowercased owner/repo slug, strip trailing .git."""
    repo = repo.rstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{owner.lower()}/{repo.lower()}"


def derive_repo_id_from_path(path: str) -> Optional[str]:
    """
    Derive the canonical <owner>/<repo> repo-id slug from a file path OR a
    GitHub URL/reference, using the SAME normalization as the cid/slug
    derivation (R6.1, R13.4): lowercase owner/repo, no trailing slash.

    Resolution order:
      1. If `path` is a github.com URL or an `<owner>/<repo>#<n>` reference,
         extract owner/repo directly and normalize to lowercase.
      2. If `path` is a filesystem path, resolve to absolute, walk up to the
         nearest enclosing git work-tree, read `git -C <root> remote get-url
         origin`, and derive the slug from that remote.
      3. If neither yields a repo, return None.

    Returns the lowercased `<owner>/<repo>` slug, or None when the repo cannot
    be determined.  Never raises.
    """
    try:
        # (1) GitHub URL or owner/repo#N reference
        url_m = _GITHUB_URL_RE.search(path)
        if url_m:
            return _normalize_slug(url_m.group("owner"), url_m.group("repo"))

        ref_m = _OWNER_REPO_REF_RE.match(path.strip())
        if ref_m:
            return _normalize_slug(ref_m.group("owner"), ref_m.group("repo"))

        # (2) Filesystem path — walk up to the nearest git work-tree root, then
        # read the origin remote URL and parse it as a GitHub URL.
        import os
        candidate = os.path.abspath(path)
        # Walk up from the path itself (not just its parent) so a bare file path
        # like "src/foo.py" that doesn't exist still resolves via CWD.
        if not os.path.exists(candidate):
            candidate = os.getcwd()
        # Find the git root by walking upward.
        check = candidate if os.path.isdir(candidate) else os.path.dirname(candidate)
        git_root: Optional[str] = None
        while True:
            if os.path.isdir(os.path.join(check, ".git")):
                git_root = check
                break
            parent = os.path.dirname(check)
            if parent == check:
                break
            check = parent

        if git_root is None:
            # Fall back to asking git directly — handles worktrees / submodules.
            r = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=False
            )
            if r.returncode == 0:
                git_root = r.stdout.strip()

        if git_root:
            r = subprocess.run(
                ["git", "-C", git_root, "remote", "get-url", "origin"],
                capture_output=True, text=True, check=False
            )
            if r.returncode == 0:
                remote_url = r.stdout.strip()
                url_m2 = _GITHUB_URL_RE.search(remote_url)
                if url_m2:
                    return _normalize_slug(url_m2.group("owner"), url_m2.group("repo"))

        return None
    except Exception:
        # Must never raise — return None for any indeterminate input.
        return None


def is_in_scope(target: str, session_repo_id: str) -> bool:
    """
    Return False if `target` resolves to a DIFFERENT repo-id than
    `session_repo_id`; True otherwise.

    target: a file path, a github.com URL, or an `<owner>/<repo>#<n>` reference.
    session_repo_id: the session scope slug (lowercased <owner>/<repo>),
                     derived once at session start from
                     git remote get-url origin.

    Semantics (fail-toward-pushback only when scope is PROVABLY different):
      - derive_repo_id_from_path(target) == session_repo_id  -> True (in scope)
      - derive returns a DIFFERENT, non-None slug             -> False (cross-repo)
      - derive returns None (indeterminate)                    -> True
        (cannot prove a crossing; do not block on a guess — a bare relative path
        inside the current tree is the common case and must not trip the guard)
    """
    try:
        target_id = derive_repo_id_from_path(target)
        if target_id is None:
            # Cannot determine; safe direction is True (no provable crossing).
            return True
        return target_id == session_repo_id.lower()
    except Exception:
        return True
