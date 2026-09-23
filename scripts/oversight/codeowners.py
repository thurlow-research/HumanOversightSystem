#!/usr/bin/env python3
"""codeowners.py — CODEOWNERS-derived HUMAN_REQUIRED gate (SPEC-303b).

The overseer's protected-surface gate (``require_human_approval.py``) only covers
paths on the explicit protected-surface list. CODEOWNERS-owned paths that are NOT
on that list had no reviewer restriction — any collaborator (including a bot) could
approve them. This module closes that gap (#303 Finding 2): any changed file whose
CODEOWNERS owner is a human (or an ``@org/team`` entry) forces HUMAN_REQUIRED,
regardless of risk tier, additive to the existing protected-surface gate.

Architect bindings (SPEC-303b / #396):
  B1  ``@org/team`` entries → unconditional HUMAN_REQUIRED, no membership expansion.
  B2  Bot accounts come from BOT_ACCOUNTS — the same variable require_human_approval.py
      reads. No split definition.
  B3  CODEOWNERS is re-read on every ``check_pr_files`` call. No cross-invocation cache.
  B4  Pattern matching reuses the glob_to_regex translation semantics from
      require_human_approval.py (conservative; errs toward HUMAN_REQUIRED).
  B5  stdlib only.

Design: ``docs/v0.4.0/TECHNICAL-DESIGN-303b-codeowners-bypass.md``.

The module is pure: no git, no gh, no network. The caller (overseer) supplies the
list of changed files derived from the PR diff and the bot-account set.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# Standard GitHub CODEOWNERS locations, in priority order (§2.1).
CODEOWNERS_LOCATIONS = (
    ".github/CODEOWNERS",
    "CODEOWNERS",
    "docs/CODEOWNERS",
)

# Spec default when BOT_ACCOUNTS is unset (SPEC-303b R5 / §2.3).
# Updated for GitHub App auth (#547): old PAT machine accounts retired.
DEFAULT_BOT_ACCOUNTS = ("hos-worker-hos[bot]", "hos-overseer-hos[bot]", "copilot[bot]")


def load_codeowners(repo_root) -> str | None:
    """Return the text of the first existing CODEOWNERS file, else None.

    Checks ``.github/CODEOWNERS``, ``CODEOWNERS``, ``docs/CODEOWNERS`` in that
    priority order (§2.1 / R1). I/O only — no parsing here.
    """
    root = Path(repo_root)
    for rel in CODEOWNERS_LOCATIONS:
        candidate = root / rel
        if candidate.is_file():
            return candidate.read_text()
    return None


def parse_codeowners(text: str) -> list[tuple[str, list[str]]]:
    """Parse CODEOWNERS text into ordered ``(pattern, owners)`` tuples (§2.2).

    File order is preserved — it is load-bearing because GitHub resolves a path to
    the *last* matching entry. Blank lines and ``#`` comments are skipped. A pattern
    line with zero owners is retained (GitHub uses it to clear ownership); it matches
    paths but contributes no owners.
    """
    entries: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        pattern = tokens[0]
        owners = tokens[1:]
        entries.append((pattern, owners))
    return entries


def glob_to_regex(glob: str) -> re.Pattern:
    """Translate a CODEOWNERS path pattern to an anchored regex (B4 / §3.1).

    Reuses the translation semantics of require_human_approval.py:
      ``**`` → ``.*``     (cross-segment, matches '/')
      ``*``  → ``[^/]*``  (one path segment)
      other  → escaped literal

    Pattern normalization applied before translation (§3.1):
      - a single leading '/' is stripped (repo-root anchor; changed-file paths are
        repo-root-relative without a leading slash);
      - a trailing '/' becomes '/**' (a directory owns everything under it);
      - a pattern with no '/' (a bare token OR one containing a glob, e.g.
        "build", "*.py", "*") becomes '**/<pattern>' — GitHub matches no-slash
        patterns at ANY depth, not just repo root (errs toward matching, #975).
    """
    g = glob
    if g.startswith("/"):
        g = g[1:]
    if g.endswith("/"):
        g = g + "**"
    elif "/" not in g:
        # No-slash pattern (e.g. "build", "*.py", "*") — match at any depth, not
        # just repo root. Without this "*.py" gates only root-level files, so a
        # nested human-owned "*.py" path would fail-open (#975 / reopened #303).
        g = "**/" + g

    out = ["^"]
    i, n = 0, len(g)
    while i < n:
        c = g[i]
        if g.startswith("**", i):
            out.append(".*")  # cross-segment: any chars incl. '/'
            i += 2
            if i < n and g[i] == "/":
                i += 1  # `**/` already consumed the slash role
        elif c == "*":
            out.append("[^/]*")  # one segment
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def get_owners_for_path(
    codeowners_entries: list[tuple[str, list[str]]], file_path: str
) -> set[str]:
    """Return the owner set of the LAST CODEOWNERS entry matching ``file_path``.

    GitHub resolves ownership by last-match-wins (§3.1). Returns an empty set when
    no entry matches OR the last matching entry is an ownership-clearing line with
    zero owners.
    """
    f = file_path.strip().lstrip("/")
    matched: set[str] | None = None
    for pattern, owners in codeowners_entries:
        if glob_to_regex(pattern).match(f):
            matched = set(owners)  # last match wins — keep overwriting
    return matched if matched is not None else set()


def _is_team(owner: str) -> bool:
    """True for an ``@org/team`` entry (a slash after the leading '@')."""
    return owner.startswith("@") and "/" in owner[1:]


def _is_bot(owner: str, bot_accounts: set[str]) -> bool:
    """True if ``owner`` is a known bot account (leading '@' tolerated)."""
    login = owner[1:] if owner.startswith("@") else owner
    return login in bot_accounts


def requires_human_approval(
    file_path: str,
    codeowners_entries: list[tuple[str, list[str]]],
    bot_accounts: set[str],
) -> tuple[bool, str]:
    """Per-file gate decision: ``(required, reason)`` (§3.2).

    - any ``@org/team`` owner  → (True, "team-owned path: <owner>")        [B1]
    - any human owner          → (True, "human CODEOWNERS owner: <owner>")
    - all owners are bots       → (False, "bot-only CODEOWNERS entry")
    - no matching entry/owners  → (False, "no CODEOWNERS entry")
    """
    owners = get_owners_for_path(codeowners_entries, file_path)
    if not owners:
        return (False, "no CODEOWNERS entry")

    # Team check first so a mixed "@org/team @bot" entry still gates (§3.2 step 3).
    for owner in sorted(owners):
        if _is_team(owner):
            return (True, f"team-owned path: {owner}")

    for owner in sorted(owners):
        if not _is_bot(owner, bot_accounts):
            return (True, f"human CODEOWNERS owner: {owner}")

    return (False, "bot-only CODEOWNERS entry")


def _bot_accounts_from_env() -> set[str]:
    """Resolve BOT_ACCOUNTS from the environment, falling back to the spec default."""
    raw = os.environ.get("BOT_ACCOUNTS", "")
    accounts = {b for b in raw.split() if b}
    return accounts if accounts else set(DEFAULT_BOT_ACCOUNTS)


def check_pr_files(
    file_list: list[str],
    repo_root,
    bot_accounts: set[str] | None = None,
) -> tuple[bool, list[str], str]:
    """PR-level CODEOWNERS gate: ``(required, matched_paths, reason)`` (§3.3).

    Re-reads CODEOWNERS every call (B3). When ``bot_accounts`` is None it is resolved
    from the BOT_ACCOUNTS env var (spec default when unset). Pure: no git/gh/network.
    """
    if bot_accounts is None:
        bot_accounts = _bot_accounts_from_env()

    text = load_codeowners(repo_root)
    if text is None:
        return (False, [], "no CODEOWNERS file")

    entries = parse_codeowners(text)

    matched_paths: list[str] = []
    triggers: list[str] = []
    for f in file_list:
        if not f or not f.strip():
            continue
        required, reason = requires_human_approval(f, entries, bot_accounts)
        if required:
            matched_paths.append(f)
            triggers.append(f"{f} ({reason})")

    if matched_paths:
        reason = "CODEOWNERS-human-owned paths: " + "; ".join(triggers)
        return (True, matched_paths, reason)

    return (False, [], "no CODEOWNERS-human-owned path matched")


# ---------------------------------------------------------------------------
# resolve_human_reviewer (#1657 §4.5) — which login to request as reviewer.
#
# This is a distinct question from requires_human_approval/check_pr_files
# above: those decide WHETHER a human is required; this decides WHO to name
# as `requested_reviewers`. Kept separate rather than folded into
# check_pr_files so the gate's conservative "over-match -> HUMAN_REQUIRED"
# contract is never entangled with a resolution routine whose own fallback
# is "pick someone" rather than "escalate".
# ---------------------------------------------------------------------------


class Resolution:
    """Result of resolve_human_reviewer: which login to request, and why.

    A plain class, not @dataclass: this module is loaded by file path (it is
    not an importable package — see merge_authority_cli._load_codeowners_module
    and pr_review_cli._load_codeowners_module), and a dataclass's own
    field-processing resolves postponed annotations via
    sys.modules.get(cls.__module__) — which is None for a by-path load that
    never registers itself in sys.modules, raising at import time. Immutable
    by convention (attributes are set once in __init__ and never reassigned).
    """

    def __init__(
        self,
        login: str | None,
        source: str,  # "codeowners" | "machine-accounts.env" | "explicit-flag"
        codeowners_owners: list[str] | None = None,
        codeowners_team_owners: list[str] | None = None,
        note: str | None = None,
    ) -> None:
        self.login = login
        self.source = source
        self.codeowners_owners = codeowners_owners if codeowners_owners is not None else []
        self.codeowners_team_owners = (
            codeowners_team_owners if codeowners_team_owners is not None else []
        )
        self.note = note


def _owner_is_email(owner: str) -> bool:
    """True when `owner` (after stripping one leading '@', if present)
    still contains '@' — CODEOWNERS permits email-address owners; they
    cannot be passed to POST .../requested_reviewers."""
    login = owner[1:] if owner.startswith("@") else owner
    return "@" in login


def _owner_is_bot(owner: str, bot_accounts: set[str]) -> bool:
    """True when `owner`'s login (leading '@' stripped) is a known bot
    account (case-insensitive) or carries GitHub's own "[bot]" suffix.
    Deliberately broader than `_is_bot` above (case-insensitive, suffix
    check) — this is a resolution-time safety check, not the SPEC-303b gate
    decision, and the two must not be conflated."""
    login = (owner[1:] if owner.startswith("@") else owner).lower()
    if login.endswith("[bot]"):
        return True
    return any(login == b.lower() for b in bot_accounts)


def resolve_human_reviewer(
    changed_files: list[str],
    repo_root,
    bot_accounts: set[str],
    human_reviewer: str,
) -> Resolution:
    """Resolve the login to request as reviewer for `changed_files` (#1657
    §4.5). Pure: no network, no subprocess — `load_codeowners`'s file read
    is the only I/O.

    Steps 1-6: prefer the first human CODEOWNERS owner (in first-seen order
    over the sorted changed-file list); fall back to `human_reviewer` when
    no user candidate is found (no CODEOWNERS file, only team/bot/email
    owners matched, or no entry matched at all) — recording which case it
    was in `note` rather than silently collapsing them.

    Step 7's fail-closed terminal checks (empty login, bot login, login ==
    PR author) are NOT performed here: they need the PR author login, which
    this function does not have. The caller (pr_review_cli.py) applies them
    to whichever login this returns, and to an explicit `--reviewer`
    override, which skips steps 1-6 but not step 7.
    """
    text = load_codeowners(repo_root)
    if text is None:
        return Resolution(
            login=human_reviewer,
            source="machine-accounts.env",
            note="no CODEOWNERS file",
        )

    entries = parse_codeowners(text)

    accumulated: list[str] = []
    seen: set[str] = set()
    for f in sorted(changed_files):
        for owner in sorted(get_owners_for_path(entries, f)):
            if owner not in seen:
                seen.add(owner)
                accumulated.append(owner)

    team_owners: list[str] = []
    email_owners: list[str] = []
    bot_owners: list[str] = []
    user_owners: list[str] = []
    for owner in accumulated:
        if _is_team(owner):
            team_owners.append(owner)
        elif _owner_is_email(owner):
            email_owners.append(owner)
        elif _owner_is_bot(owner, bot_accounts):
            bot_owners.append(owner)
        else:
            user_owners.append(owner)

    # Never surface a raw e-mail-shaped owner token: this Resolution is
    # copied verbatim into pr_review_cli.py's printed JSON envelope, which
    # the overseer commits to a durable, git-committed audit record on every
    # disposition (audit/automation/<customer>/runs/). resolve_human_reviewer
    # has already decided not to use an e-mail owner as `login` — surfacing
    # it in `codeowners_owners` anyway would give a legitimate, common
    # CODEOWNERS pattern (e.g. "/docs/** dev@example.com") no purpose other
    # than leaking a personal e-mail address into that record, re-emitted on
    # every idempotent re-run with no erasure path. `note` remains the
    # record that an e-mail owner was present and skipped (MUST_FIX A,
    # #1657 PR-1 review round 2 / privacy-reviewer).
    safe_owners = [owner for owner in accumulated if not _owner_is_email(owner)]

    if user_owners:
        login = user_owners[0]
        login = login[1:] if login.startswith("@") else login
        return Resolution(
            login=login,
            source="codeowners",
            codeowners_owners=safe_owners,
            codeowners_team_owners=team_owners,
        )

    if team_owners:
        note = f"CODEOWNERS owner is a team ({team_owners[0]}); team review requests are not made"
    elif bot_owners and not email_owners:
        note = "bot-only CODEOWNERS entry"
    elif email_owners:
        note = "CODEOWNERS owners are e-mail addresses; not requestable"
    else:
        note = "no CODEOWNERS entry matched the changed files"

    return Resolution(
        login=human_reviewer,
        source="machine-accounts.env",
        codeowners_owners=safe_owners,
        codeowners_team_owners=team_owners,
        note=note,
    )
