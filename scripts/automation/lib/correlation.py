"""
Correlation-id derivation, artifact naming, idempotency precheck, and
cold-start recovery state machine for the HOS automation loop.

This is the M1 correctness owner (ADR-2, R6.1).  The cid is the ONLY
mechanism that prevents duplicate work — all lock/claim/activation layers
are contention reducers on top.  Any code that re-derives a branch name
outside this module is a bug.
"""

import hashlib
import re
from enum import Enum, auto
from typing import Optional
from urllib.parse import urlparse

from scripts.automation.lib.github import (
    get_branch,
    list_issue_comments,
    list_pulls,
)


class ResumeState(Enum):
    """
    Furthest-progressed state found during the idempotency precheck.
    A worker resumes from this state rather than starting over (R6.1 cold-start table).
    """
    NOT_STARTED = auto()       # No artifacts found — begin from scratch.
    CLAIM_PRESENT = auto()     # Claim envelope posted but no branch.
    BRANCH_EXISTS = auto()     # Branch created but no PR.
    PR_EXISTS = auto()         # PR open — re-run gates then re-decide.
    GATES_COMPLETE = auto()    # Gate results visible on the PR — re-decide merge.
    MERGED = auto()            # Already merged — nothing to do.


# ---------------------------------------------------------------------------
# cid derivation (ADR-2 · R6.1 — the M1 keystone)
# ---------------------------------------------------------------------------

def _normalize_issue_url(raw_url: str, issue_number: int) -> str:
    """
    Produce the canonical issue URL for hashing.

    Canonical form: https://github.com/{owner}/{repo}/issues/{n}
    - Scheme is always https
    - Host is lowercased
    - Trailing slashes stripped
    - issue_number appended if not already present in the path

    This normalization is the stability contract: changing it changes every
    cid ever derived — treat it as a wire format.
    """
    parsed = urlparse(raw_url.rstrip("/"))
    host = (parsed.netloc or "github.com").lower()
    path = parsed.path.rstrip("/")

    # Ensure the path ends with /issues/{n}.
    issues_suffix = f"/issues/{issue_number}"
    if not path.endswith(issues_suffix):
        # Strip any existing /issues/... tail then re-append.
        path = re.sub(r"/issues/\d+$", "", path)
        path = path + issues_suffix

    return f"https://{host}{path}"


def derive_cid(issue_url: str, issue_number: int) -> str:
    """
    Derive the correlation-id for a GitHub issue.

    cid = sha256("{normalized_url}#{issue_number}".encode()).hexdigest()[:12]

    The cid is deterministic across instances (given the same input) so two
    racing workers derive the same branch name, making duplicate-work
    structurally impossible (ADR-2).

    >>> derive_cid("https://github.com/thurlow-research/HumanOversightSystem/issues/254", 254)
    # deterministic 12-char hex string
    """
    canonical = _normalize_issue_url(issue_url, issue_number)
    payload = f"{canonical}#{issue_number}"
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Artifact names (single owner — no other module derives these)
# ---------------------------------------------------------------------------

def branch_name(cid: str) -> str:
    """Return the branch name for a given cid."""
    return f"hos/auto/{cid}"


def pr_title(cid: str, summary: str) -> str:
    """Return the canonical PR title carrying the cid."""
    return f"[AI: hos-worker] {summary} (auto/{cid})"


ENVELOPE_CID_MARKER = "correlation-id:"


def envelope_cid_line(cid: str) -> str:
    """Return the correlation-id line as it appears in an answer envelope."""
    return f"{ENVELOPE_CID_MARKER} {cid}"


# ---------------------------------------------------------------------------
# Idempotency precheck (R6.1 · read-your-writes — REST-by-id only)
# ---------------------------------------------------------------------------

def _check_merged(pulls: list[dict]) -> bool:
    return any(pr.get("merged_at") for pr in pulls)


def _check_gates_complete(pulls: list[dict]) -> bool:
    """
    Gates are considered complete when the PR has at least one completed
    check-run or review in a terminal state.  This is a heuristic; the
    per-task worker makes the authoritative re-decision from PR state.
    """
    for pr in pulls:
        if pr.get("mergeable_state") in ("clean", "blocked", "behind"):
            return True
    return False


def already_exists(
    owner: str,
    repo: str,
    cid: str,
    issue_number: int,
) -> ResumeState:
    """
    Check GitHub (REST-by-id) for any artifact from a prior run with this cid.

    Returns the furthest-progressed ResumeState.  The caller resumes
    the task from that state — not from scratch — enabling cold-start
    recovery (R6.1, M4).

    Read-your-writes invariant: uses REST-by-id only, never the Search API.
    """
    branch = branch_name(cid)
    head_filter = f"{owner}:{branch}"

    # 1. Does the branch exist?
    branch_ref = get_branch(owner, repo, branch)
    branch_found = branch_ref is not None

    # 2. Does a PR exist (any state)?
    pulls = list_pulls(owner, repo, head=head_filter, state="all")
    pr_found = bool(pulls)

    if pr_found:
        if _check_merged(pulls):
            return ResumeState.MERGED
        if _check_gates_complete(pulls):
            return ResumeState.GATES_COMPLETE
        return ResumeState.PR_EXISTS

    if branch_found:
        return ResumeState.BRANCH_EXISTS

    # 3. Is there a claim envelope on the issue?
    if _has_claim_envelope(owner, repo, issue_number, cid):
        return ResumeState.CLAIM_PRESENT

    return ResumeState.NOT_STARTED


def _has_claim_envelope(
    owner: str,
    repo: str,
    issue_number: int,
    cid: str,
) -> bool:
    """
    Scan the issue's comments for a posted claim envelope with this cid.

    Uses REST-by-id pagination — never Search.
    """
    marker = envelope_cid_line(cid)
    for comment in list_issue_comments(owner, repo, issue_number):
        if marker in comment.get("body", ""):
            return True
    return False


# ---------------------------------------------------------------------------
# Cold-start recovery table (R6.1 · M4 — informational; workers act on ResumeState)
# ---------------------------------------------------------------------------

COLD_START_TABLE: dict[ResumeState, str] = {
    ResumeState.NOT_STARTED: "Begin from scratch: triage → claim → branch → build → PR",
    ResumeState.CLAIM_PRESENT: "Claim envelope found — re-triage and continue from claim",
    ResumeState.BRANCH_EXISTS: "Branch exists — open PR (idempotent; branch already created)",
    ResumeState.PR_EXISTS: "PR exists — re-run gates then re-decide merge",
    ResumeState.GATES_COMPLETE: "Gate results visible — re-read PR state and re-decide merge",
    ResumeState.MERGED: "Already merged — no work remaining for this cid",
}
