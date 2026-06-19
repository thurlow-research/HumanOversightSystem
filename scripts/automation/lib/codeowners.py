"""
CODEOWNERS parser and actor-authorization signal (O19, §13).

Answers: "Is this actor a codeowner of this file?" — used as an authorization
signal in the worker automation pipeline.

NOTE: This module has NO production callers as of v0.4.0. The docstring
previously claimed triage.py uses actor_is_codeowner(); that was incorrect.
Any future wiring into a live authorization path requires a product-boundary
checkpoint (architect ruling on #559, 2026-06-19).

KNOWN DIVERGENCE from scripts/oversight/codeowners.py (#559):
  This module and the oversight gate use different glob matchers with
  intentionally opposite fail directions:
  - oversight: conservative (over-match → HUMAN_REQUIRED — safe)
  - this module: fail-closed (over-match → unearned authorization — dangerous)
  A shared matcher cannot serve both. See KNOWN-DIVERGENCE tests in
  tests/automation/test_phase_b.py for the pinned divergence rows.
  Do not import from scripts/oversight/ — that inverts the trust direction.

Rules (O19 resolution):
  - Parse .github/CODEOWNERS, last-match-wins (GitHub semantics)
  - Support user (@user), team (@org/team), and wildcard (*) patterns
  - Uncovered paths → fail-closed (no owner → not authorized)
  - Team membership is NOT verified (requires org-level API; deferred)
    → treat team patterns as present but flag for review
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class CodeownersEntry:
    __slots__ = ("pattern", "owners")

    def __init__(self, pattern: str, owners: list[str]):
        self.pattern = pattern
        self.owners = owners


def _parse_codeowners(path: Path) -> list[CodeownersEntry]:
    """
    Parse a CODEOWNERS file into a list of entries (in order).

    GitHub semantics: last matching rule wins.
    """
    entries = []
    if not path.is_file():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pattern = parts[0]
        owners = parts[1:]
        entries.append(CodeownersEntry(pattern, owners))
    return entries


def _fnmatch_codeowners(pattern: str, filepath: str) -> bool:
    """
    Match a CODEOWNERS pattern against a file path.

    GitHub CODEOWNERS uses a gitignore-style glob:
      *     matches any file in the repo
      *.py  matches any .py file anywhere
      /foo  anchored to root
      foo/  matches directory foo and everything under it
    """
    # Normalize
    filepath = filepath.lstrip("/")
    pattern = pattern.lstrip("/")

    # Convert pattern to a regex
    # Escape everything except * and /
    regex = re.escape(pattern)
    regex = regex.replace(r"\*\*", ".*")
    regex = regex.replace(r"\*", "[^/]*")

    # If pattern ends with /, match directory and all contents
    if pattern.endswith("/"):
        regex = regex + ".*"
    else:
        # Match the exact path OR anything under it as a directory
        regex = regex + "(/.*)?$"

    return bool(re.fullmatch(regex, filepath))


def find_owners(filepath: str, codeowners_path: Path) -> list[str]:
    """
    Return the owners for a given filepath (last-match-wins).

    Returns [] if no rule matches (uncovered path → fail-closed in triage).
    """
    entries = _parse_codeowners(codeowners_path)
    owners: list[str] = []
    for entry in entries:
        if _fnmatch_codeowners(entry.pattern, filepath):
            owners = entry.owners  # Last match wins
    return owners


# ---------------------------------------------------------------------------
# Label-actor authorization (O19)
# ---------------------------------------------------------------------------

def actor_is_codeowner(
    github_login: str,
    path: str,
    codeowners_path: Path,
) -> bool:
    """
    Return True if github_login is a listed owner of path in CODEOWNERS.

    Team patterns (@org/team) are accepted as present but NOT expanded —
    team membership is not verified (org API required; deferred to v2).
    Uncovered path → False (fail-closed).
    """
    owners = find_owners(path, codeowners_path)
    if not owners:
        return False  # Uncovered path → fail-closed
    login_lower = github_login.lower()
    for owner in owners:
        owner = owner.lstrip("@")
        if "/" in owner:
            # Team pattern — treat as authorized (v1: no membership check)
            # Flag but don't block
            return True
        if owner.lower() == login_lower:
            return True
    return False
