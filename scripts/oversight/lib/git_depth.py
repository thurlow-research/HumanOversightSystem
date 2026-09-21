#!/usr/bin/env python3
"""git_depth.py — shared shallow-clone detector (#1759, Ruling I / TD-D15).

One detector, not two. `secret_scan_logic.py`'s `GitShaVerifier._is_shallow`
(landed in `033c1382`) already implemented exactly this tri-state — this
module is that logic extracted unchanged, so both callers ask git the same
question the same way rather than risking two implementations drifting apart
(see docs/v0.7.0/TECHNICAL-DESIGN-1759-run-gates-diff-parsing.md §3 TD-D15).

`GitShaVerifier._is_shallow` becomes a thin, cached delegation to
`is_shallow_repository()`; `changeset_logic.py`'s missing-path classifier
(tier 4) imports it directly.
"""

from __future__ import annotations

import subprocess


def is_shallow_repository(timeout: int = 15) -> bool | None:
    """Is the current working tree a shallow git clone?

    Returns:
        True   — `git rev-parse --is-shallow-repository` answered "true".
        False  — it answered "false" (a complete clone).
        None   — git could not be asked at all (not a repo, git missing,
                 the call timed out, or it answered something else).
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    answer = completed.stdout.decode("utf-8", "replace").strip()
    if answer in ("true", "false"):
        return answer == "true"
    return None
