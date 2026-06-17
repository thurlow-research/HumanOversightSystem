"""
activation.py — Runtime activation helpers for the HOS autonomous worker.

verify_bot_identity() guards against a common operator mistake: running the
worker in a shell where a human admin's `gh` session is still active.  If the
active gh identity isn't the expected bot account, commits and PRs would be
attributed to the human, contaminating the audit trail and sending notifications
from their account.
"""

import logging
import subprocess


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
