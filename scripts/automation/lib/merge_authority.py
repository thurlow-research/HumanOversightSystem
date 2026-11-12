"""
Merge-authority detection, matrix, queue, and guard rails (T10, §9, O3).

B4 delivered: detect_server_side_gate (the detection half).
B10 delivers: the full matrix, PROPOSE_ONLY default, pre-merge re-check (R9.1.1),
              authorship backstop, draft-PR/needs-human/needs-ai queue,
              no-release guard, embargo route, --class worker/overseer awareness.

Matrix (R9.1 — authoritative):
  Auto-merge iff ALL of:
    (tier ≤ MEDIUM) AND (not security-relevant) AND (not protected-surface)
    AND (full PROCEED from oversight-evaluator) AND (server-side gate detected, re-checked)
    AND (verified human approval on current head SHA — universal, #757)

  class=worker  → NEVER merges (opens PRs only)
  class=overseer → may merge iff matrix permits AND below OVERSEER_CEILING
"""

from __future__ import annotations

import base64
import contextlib
import errno
import fcntl
import fnmatch
import hashlib
import importlib.util
import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import (
    Any,
    Callable,
    Collection,
    Iterable,
    NamedTuple,
    NoReturn,
    Optional,
    Sequence,
    Union,
)

from scripts.automation.lib import github as _github
from scripts.automation.lib.github import (
    GitHubError,
    ListTruncatedError,
    RateLimitError,
    _required_contexts_from_rules,
    _run_gh,
    get_branch_protection,
    get_contents,
    get_ruleset,
    get_ruleset_required_checks,
    list_branch_rules,
    list_check_runs_for_ref,
    post_comment,
)

logger = logging.getLogger(__name__)


def _find_human_approval(
    reviews: list[dict],
    human_reviewer: str = "ScottThurlow",
    head_sha: Optional[str] = None,
) -> Optional[dict]:
    """
    Find the first APPROVED review from the authorized human reviewer.

    If head_sha is provided, only a review whose commit_id matches head_sha
    counts — a stale approval from before a later push is rejected (defends
    the push-after-approval race; see issue #741 safety condition 2).
    """
    for review in reviews:
        if (
            review.get("state") == "APPROVED"
            and review.get("user", {}).get("login", "").lower() == human_reviewer.lower()
        ):
            if head_sha is not None and review.get("commit_id") != head_sha:
                continue  # Stale approval — not for the current head
            return review
    return None


def has_human_approval(
    reviews: list[dict],
    human_reviewer: str = "ScottThurlow",
    head_sha: Optional[str] = None,
) -> bool:
    """
    Check if PR has an APPROVED review from the specified human.

    Args:
        reviews: List of PR review dicts from GitHub API (GET /pulls/{n}/reviews).
        human_reviewer: GitHub login of the authorized human reviewer.
        head_sha: If provided, only an approval on this exact commit counts.
            An approval from before a later push is rejected (issue #741).

    Returns:
        True if a qualifying APPROVED review exists from the human_reviewer.
    """
    return _find_human_approval(reviews, human_reviewer, head_sha) is not None


# Explicit human directives that mean "do not approve / send this PR back" rather
# than "merge it" — a bounce-back / hold / do-not-merge signal (#902). Matched
# case-insensitively against a comment body. The set is deliberately conservative
# but errs toward withholding: a false positive only ever blocks an auto-approval
# (the safe direction), never enables one.
_HOLD_DIRECTIVE_RE = re.compile(
    r"\b(?:"
    r"bounce(?:\s+it|\s+this)?\s+back"
    r"|back\s+to\s+(?:the\s+)?(?:worker|hos-worker)"
    r"|send(?:\s+it|\s+this)?\s+back"
    r"|do\s+not\s+merge|don['’]?t\s+merge|dont\s+merge"
    r"|do\s+not\s+approve|don['’]?t\s+approve|dont\s+approve"
    r"|on\s+hold|hold\s+off|hold\s+the\s+merge"
    r"|halt"
    r"|unapprove"
    r"|needs?\s+rework|rework\s+(?:this|it)"
    r"|revise"
    r")\b",
    re.IGNORECASE,
)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Parse a GitHub ISO-8601 timestamp (e.g. '2026-06-28T15:46:11Z') to an
    aware datetime, or None if absent/unparseable."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def detect_human_hold_directive(
    comments: list[dict],
    human_reviewer: str = "ScottThurlow",
    head_committed_at: Optional[str] = None,
) -> Optional[dict]:
    """
    Find an unaddressed human hold / bounce-back directive on the current head (#902).

    Scans issue/PR comments for one authored by ``human_reviewer`` whose body
    matches a bounce-back / hold / do-not-merge pattern (``_HOLD_DIRECTIVE_RE``).

    If ``head_committed_at`` (ISO-8601 timestamp of the current head commit) is
    provided, only directives posted AFTER the head was pushed count — a newer
    worker push supersedes an earlier bounce-back, mirroring how a push
    invalidates a stale approval (#741). When ``head_committed_at`` is None, any
    matching directive counts (fail-safe: withhold approval when the push time is
    unknown). A comment whose own timestamp cannot be parsed is also counted
    (fail-safe), so a missing ``created_at`` never silently clears the gate.

    Args:
        comments: Issue/PR comment dicts from ``GET /issues/{n}/comments`` (each
            with ``user.login``, ``body``, ``created_at``).
        human_reviewer: GitHub login of the authorized human reviewer.
        head_committed_at: ISO-8601 timestamp the current head was pushed/committed.

    Returns:
        The most recent matching comment dict, or None if no active directive.
    """
    head_dt = _parse_iso(head_committed_at)
    _epoch = datetime.min.replace(tzinfo=timezone.utc)
    matches: list[tuple[datetime, dict]] = []
    for comment in comments or []:
        login = (comment.get("user") or {}).get("login", "")
        if login.lower() != human_reviewer.lower():
            continue
        if not _HOLD_DIRECTIVE_RE.search(comment.get("body") or ""):
            continue
        created_dt = _parse_iso(comment.get("created_at"))
        if head_dt is not None and created_dt is not None and created_dt <= head_dt:
            continue  # Superseded by a later head push — directive is addressed.
        matches.append((created_dt or _epoch, comment))
    if not matches:
        return None
    matches.sort(key=lambda m: m[0])
    return matches[-1][1]


# ---------------------------------------------------------------------------
# Re-export from B4 detection half
# ---------------------------------------------------------------------------


@dataclass
class GateDetectionResult:
    autonomous_capable: bool
    reason: str

    def __bool__(self) -> bool:
        return self.autonomous_capable


_PROPOSE_ONLY_DEP = GateDetectionResult(
    autonomous_capable=False,
    reason=(
        "DEP[#152-followup]: risk-tier-vs-ceiling status check not yet shipped — "
        "above-ceiling enforcement unverifiable → PROPOSE_ONLY (fail-safe)"
    ),
)

DEFAULT_OVERSEER_HANDLE = "hos-overseer-hos[bot]"  # GitHub App; updated from PAT account (#547)


def _dep_ceiling_check_present(owner: str, repo: str) -> bool:
    """Stub — returns False until the #152 follow-up status check ships.

    Unchanged by #2213: the human-approval merge path uses
    ``verify_merge_gate_live``; switching this stub to it is ESC-1b and needs
    its own issue.
    """
    return False


def _verify_overseer_cannot_bypass(
    protection: dict,
    overseer_handle: str,
) -> GateDetectionResult:
    enforce_admins = protection.get("enforce_admins", {})
    if isinstance(enforce_admins, dict) and enforce_admins.get("enabled"):
        return GateDetectionResult(autonomous_capable=True, reason="enforce_admins enabled")
    bypass_actors = protection.get("bypass_pull_request_allowances", {})
    if isinstance(bypass_actors, dict):
        for user in bypass_actors.get("users", []):
            if isinstance(user, dict) and user.get("login", "").lower() == overseer_handle.lower():
                return GateDetectionResult(
                    autonomous_capable=False,
                    reason=f"Overseer '{overseer_handle}' is in bypass_pull_request_allowances.users",
                )
        for team in bypass_actors.get("teams", []):
            if isinstance(team, dict):
                return GateDetectionResult(
                    autonomous_capable=False,
                    reason=(
                        f"bypass_pull_request_allowances includes team "
                        f"'{team.get('slug')}' — overseer membership unverifiable"
                    ),
                )
    return GateDetectionResult(autonomous_capable=True, reason="No bypass actors found")


def _verify_overseer_review_accepted(
    protection: dict,
    overseer_handle: str,
) -> GateDetectionResult:
    return GateDetectionResult(
        autonomous_capable=True,
        reason="Overseer review accepted (CODEOWNER check deferred to pre-merge re-check)",
    )


def detect_server_side_gate(
    owner: str,
    repo: str,
    default_branch: str = "main",
    overseer_handle: str = DEFAULT_OVERSEER_HANDLE,
) -> GateDetectionResult:
    """
    Detect server-side gate (O3). Must be re-called immediately before each merge (R9.1.1).

    Returns PROPOSE_ONLY until DEP[#152-followup] lands.
    """
    if not _dep_ceiling_check_present(owner, repo):
        return _PROPOSE_ONLY_DEP

    try:
        protection = get_branch_protection(owner, repo, default_branch)
    except GitHubError as exc:
        return GateDetectionResult(
            autonomous_capable=False, reason=f"Protection API read failed: {exc}"
        )

    if protection is None:
        return GateDetectionResult(
            autonomous_capable=False, reason=f"Branch protection not enabled on {default_branch}"
        )

    rpr = protection.get("required_pull_request_reviews")
    if not rpr:
        return GateDetectionResult(
            autonomous_capable=False, reason="required_pull_request_reviews not configured"
        )
    if rpr.get("required_approving_review_count", 0) < 1:
        return GateDetectionResult(
            autonomous_capable=False, reason="required_approving_review_count < 1"
        )
    if not rpr.get("dismiss_stale_reviews"):
        return GateDetectionResult(
            autonomous_capable=False, reason="dismiss_stale_reviews not enabled"
        )

    bypass_result = _verify_overseer_cannot_bypass(protection, overseer_handle)
    if not bypass_result.autonomous_capable:
        return bypass_result

    review_result = _verify_overseer_review_accepted(protection, overseer_handle)
    if not review_result.autonomous_capable:
        return review_result

    return GateDetectionResult(
        autonomous_capable=True,
        reason="Server-side gate detected: protection active, overseer cannot bypass",
    )


# ---------------------------------------------------------------------------
# Risk tier enum
# ---------------------------------------------------------------------------


class RiskTier(Enum):
    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @classmethod
    def from_str(cls, s: str) -> "RiskTier":
        return cls[s.upper()]


# ---------------------------------------------------------------------------
# Merge decision
# ---------------------------------------------------------------------------


class MergeDecision(Enum):
    AUTO_MERGE = auto()  # overseer may approve + merge
    PROPOSE_ONLY = auto()  # open PR, no auto-merge (server gate absent)
    HUMAN_REQUIRED = auto()  # escalate to human


@dataclass
class MergeAuthorityResult:
    decision: MergeDecision
    reason: str
    pr_title: Optional[str] = None
    labels_to_add: Optional[list[str]] = None
    is_release: bool = False

    def __post_init__(self):
        if self.labels_to_add is None:
            self.labels_to_add = []


# ---------------------------------------------------------------------------
# No-release guard (NG3b)
# ---------------------------------------------------------------------------

# Release detection is split into TITLE patterns and PATH globs (#1032).  The
# original implementation concatenated the title with every changed path into a
# single string and substring-matched a flat keyword list, so any path holding
# "v0." (every file under docs/v0.6.0/**) or "tag" ("staging", "metadata",
# "packs/") read as a release.  Titles are now matched with word boundaries and
# paths are matched as globs against release artifacts only.
#
# The guard still fails safe: it may only ever route a PR to HUMAN_REQUIRED, so
# narrowing it removes false positives without opening any autonomous-release
# path.  Genuine release PRs are additionally backstopped by the server-side
# protected-surface gate (docs/releases/**, .hos-release — #761).
_RELEASE_TITLE_RE = re.compile(
    r"""
      \b releases? \b
    | \b releasing \b
    | \b publish (?: es | ed | ing )? \b
    | \b ship (?: s | ped | ping )? \b
    | \b semver \b
    | \b tags? \b
    | \b tagging \b
    | \b v \d+ \. \d+ (?: \. \d+ )? \b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Release artifacts only — deliberately NOT the whole of
# scripts/framework/protected_surfaces.txt.  That list covers every control
# surface (bin/**, .claude/agents/**, …); reusing it here would label unrelated
# control-surface PRs as releases and widen NG3b with a misleading reason.  Those
# surfaces are already gated by touches_protected_surface().  Keep the entries
# below in sync with the "Release artifacts (#761)" block of that file.
_RELEASE_PATH_GLOBS = [
    "docs/releases/**",
    ".hos-release",
    "CHANGELOG*",
    "release/v*",
]


def _matches_release_path(path: str) -> bool:
    """True when a changed path is a release artifact (glob, not substring)."""
    normalized = path.strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lower()
    for pattern in _RELEASE_PATH_GLOBS:
        pattern = pattern.lower()
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(normalized, f"**/{pattern}"):
            return True
    return False


def _is_release_related(pr_title: str, changed_files: list[str]) -> bool:
    """
    True when the PR performs a release action — NG3b: never autonomous.

    Title and paths are evaluated independently (#1032): a release verb/version
    in the title, or a changed file that is a release artifact.
    """
    if _RELEASE_TITLE_RE.search(pr_title or ""):
        return True
    return any(_matches_release_path(f) for f in (changed_files or []))


# ---------------------------------------------------------------------------
# Protected-surface check (re-uses require_human_approval.py)
# ---------------------------------------------------------------------------


def touches_protected_surface(changed_files: list[str], repo_root: str = ".") -> bool:
    """Check if any changed file is on the protected surface.

    Public (#1325): overseer.md's pre-matrix protected-surface gate calls this
    directly, before any other computation, so the check runs deterministically
    every cycle rather than being reachable only via decide_merge_authority()'s
    internal call — a prior cycle's narrative conclusion ("Auto-merging") is
    never a substitute for calling this fresh.
    """
    surfaces_path = Path(repo_root) / "scripts" / "framework" / "protected_surfaces.txt"
    if not surfaces_path.is_file():
        return False
    try:
        globs = []
        for line in surfaces_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                globs.append(line)
        for f in changed_files:
            for pattern in globs:
                if fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(f, f"**/{pattern}"):
                    return True
        return False
    except Exception:
        return True  # Fail-closed: if we can't read, assume protected


# ---------------------------------------------------------------------------
# Security-relevant surface check (#1253 — deterministic source, mirrors the
# protected-surface check above)
# ---------------------------------------------------------------------------


def touches_security_surface(changed_files: list[str], repo_root: str = ".") -> bool:
    """
    Check if any changed file is on the security-relevant surface (#1253).

    Before this existed, `security_relevant` was a caller-supplied bool with no
    real caller — the matrix row forcing HUMAN_REQUIRED and the "never approve a
    security-relevant change without human sign-off" hard limit were both
    silently unenforced. This derives the signal from
    scripts/framework/security_surfaces.txt so it no longer depends on a caller
    remembering to pass it. Same fail-closed contract as
    touches_protected_surface: an unreadable surfaces file assumes relevant; a
    surfaces file that simply does not exist is not itself treated as relevant,
    because security_surfaces.txt lives under scripts/framework/**, which
    protected_surfaces.txt already protects — deleting or tampering with it is
    independently caught by the protected-surface check.

    Public (#1357): documented as a matrix input in overseer.md:538-542, and
    `bootstrap/merge_authority.sh security-surface` reports it as evidence.
    Behaviour is unchanged by the promotion.
    """
    surfaces_path = Path(repo_root) / "scripts" / "framework" / "security_surfaces.txt"
    if not surfaces_path.is_file():
        return False
    try:
        globs = []
        for line in surfaces_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                globs.append(line)
        for f in changed_files:
            for pattern in globs:
                if fnmatch.fnmatch(f, pattern) or fnmatch.fnmatch(f, f"**/{pattern}"):
                    return True
        return False
    except Exception:
        return True  # Fail-closed: if we can't read, assume security-relevant


# ---------------------------------------------------------------------------
# Authorship backstop (R9.1.4)
# ---------------------------------------------------------------------------


def _verify_authorship_separation(
    pr_author: str,
    overseer_handle: str,
    worker_handle: str,
) -> bool:
    """
    The PR author (worker) must not be the overseer (the approver/merger).
    GitHub's "no self-approval" rule enforces this at the server level, but
    we verify it here as a local backstop.
    """
    return pr_author.lower() != overseer_handle.lower()


# ---------------------------------------------------------------------------
# Main decision function
# ---------------------------------------------------------------------------

_HUMAN_GATE_LABELS = frozenset({"needs-human", "hos-halt"})


def decide_merge_authority(
    owner: str,
    repo: str,
    pr_number: int,
    risk_tier: RiskTier,
    oversight_verdict: str,  # "PROCEED" | "CONDITIONAL_PROCEED" | "ESCALATE"
    changed_files: list[str],
    pr_title: str = "",
    pr_author: str = "",
    security_relevant: bool = False,  # explicit override; OR'd with the derived
    # scripts/framework/security_surfaces.txt check (#1253)
    agent_class: str = "worker",  # "worker" | "overseer"
    overseer_handle: str = DEFAULT_OVERSEER_HANDLE,
    worker_handle: str = "hos-worker-hos[bot]",  # GitHub App; updated from PAT account (#547)
    overseer_ceiling: RiskTier = RiskTier.LOW,
    default_branch: str = "main",
    repo_root: str = ".",
    reviews: Optional[
        list[dict]
    ] = None,  # PR reviews from GitHub API; enables human-approval override
    human_reviewer: str = "ScottThurlow",  # Human who can approve protected-surface PRs
    head_sha: Optional[str] = None,  # Current PR head SHA; stale approvals (wrong SHA) are rejected
    pr_labels: Optional[
        list[str]
    ] = None,  # Labels on the PR; needs-human/hos-halt block AUTO_MERGE (#756)
    prior_overseer_decision: Optional[
        str
    ] = None,  # "HUMAN_REQUIRED" if a prior cycle decided so (#761)
    requested_reviewers: Optional[
        list[str]
    ] = None,  # Pending human review requests on the PR (#761)
    human_hold_directive: bool = False,  # Unaddressed human bounce-back/hold on current head (#902)
) -> MergeAuthorityResult:
    """
    Decide what the automation may do with this PR.

    R9.1.1: calls detect_server_side_gate immediately before merge decision —
    never trusts a cached result.

    Issues #589 / #741 / #757: Every merge requires a verified human approval
    on the current head SHA — no bot-only merge is allowed.  For PRs that are
    security-relevant or touch a protected surface, the human approval is
    checked early (and the PR routes to HUMAN_REQUIRED if absent).  For all
    other PRs the universal assertion (#757) fires last, after the server-side
    gate re-check (R9.1.1).  The audit reason always records the authorizing
    maintainer and the approved SHA.

    Issue #902: an unaddressed human hold/bounce-back directive on the current
    head (``human_hold_directive=True``, computed by the caller via
    detect_human_hold_directive) forces HUMAN_REQUIRED before the worker/verdict
    guards, so the overseer withholds approval rather than approving against an
    explicit human decision to send the PR back.
    """
    if reviews is None:
        reviews = []

    # Tracks the human-authorization string for the audit trail when a human
    # approval satisfies the protected-surface or security-relevant gate.
    human_auth_reason: Optional[str] = None

    # Hard pre-merge label guard (#756): needs-human and hos-halt are blocking
    # regardless of risk tier, protected-surface status, or any other signal.
    if pr_labels:
        blocking = _HUMAN_GATE_LABELS & {lbl.lower() for lbl in pr_labels}
        if blocking:
            label_str = ", ".join(sorted(blocking))
            return MergeAuthorityResult(
                decision=MergeDecision.HUMAN_REQUIRED,
                reason=f"PR carries blocking label(s) [{label_str}] — human authorization required (#756)",
            )

    # Idempotency guard (#761): a prior overseer cycle decided HUMAN_REQUIRED.
    # Only a verified human approval on the current head SHA may clear this —
    # the overseer must not silently downgrade a prior decision in a later cycle.
    if prior_overseer_decision == "HUMAN_REQUIRED":
        if not _find_human_approval(reviews, human_reviewer, head_sha):
            return MergeAuthorityResult(
                decision=MergeDecision.HUMAN_REQUIRED,
                reason=(
                    "Prior overseer decision was HUMAN_REQUIRED; no qualifying human approval "
                    f"found on head SHA — escalating to {human_reviewer} (#761)"
                ),
                labels_to_add=["needs-human"],
            )

    # Requested-reviewer gate (#761): an outstanding review request from the
    # authorized human reviewer is an implicit HUMAN_REQUIRED signal — the PR
    # author or a prior overseer cycle explicitly routed the PR for human review.
    if requested_reviewers:
        if any(r.lower() == human_reviewer.lower() for r in requested_reviewers):
            return MergeAuthorityResult(
                decision=MergeDecision.HUMAN_REQUIRED,
                reason=(
                    f"PR has an outstanding review request from {human_reviewer} — "
                    "human review is pending (#761)"
                ),
                labels_to_add=["needs-human"],
            )

    # Human hold-directive gate (#902): an explicit, unaddressed human directive
    # to bounce back / hold / not merge on the current head SHA is a
    # HUMAN_REQUIRED-equivalent block. It fires alongside the #756 label and #761
    # reviewer guards — before the worker-class, verdict, and ceiling guards — so a
    # held PR escalates to the human and the overseer withholds any approval review,
    # rather than silently downgrading to PROPOSE_ONLY. The caller computes this via
    # detect_human_hold_directive() over comments posted since the head was pushed;
    # a newer worker push (or explicit human re-approval) supersedes the directive.
    if human_hold_directive:
        return MergeAuthorityResult(
            decision=MergeDecision.HUMAN_REQUIRED,
            reason=(
                f"Unaddressed human hold/bounce-back directive from {human_reviewer} "
                "on the current head — withholding approval; human authorization required (#902)"
            ),
            labels_to_add=["needs-human"],
        )

    # No-release guard (NG3b)
    if _is_release_related(pr_title, changed_files):
        return MergeAuthorityResult(
            decision=MergeDecision.HUMAN_REQUIRED,
            reason="Release-related PR — autonomous releases are prohibited (NG3b)",
            labels_to_add=["needs-human"],
            is_release=True,
        )

    # Worker class never merges — opens PRs only
    if agent_class == "worker":
        return MergeAuthorityResult(
            decision=MergeDecision.PROPOSE_ONLY,
            reason="agent_class=worker — worker opens PRs only, never merges",
            labels_to_add=[],
        )

    # Oversight verdict gate
    if oversight_verdict != "PROCEED":
        label = "needs-human" if oversight_verdict == "ESCALATE" else "needs-ai"
        return MergeAuthorityResult(
            decision=MergeDecision.HUMAN_REQUIRED,
            reason=f"Oversight verdict is {oversight_verdict} — escalating",
            labels_to_add=[label],
        )

    # Tier above overseer ceiling
    if risk_tier.value > overseer_ceiling.value:
        return MergeAuthorityResult(
            decision=MergeDecision.HUMAN_REQUIRED,
            reason=f"Tier {risk_tier.name} exceeds overseer ceiling {overseer_ceiling.name}",
            labels_to_add=["needs-human"],
        )

    # Security-relevant: requires human approval.  If a verified human has
    # already approved the current head SHA, authorization is satisfied and
    # the overseer may execute the merge (#741).
    #
    # #1253: security_relevant is no longer trusted from the caller alone — it
    # is OR'd with the deterministic surface-file derivation, so the gate fires
    # even when a caller forgets to compute and pass it (which is how it went
    # unenforced: no real caller ever did).
    security_relevant = security_relevant or touches_security_surface(changed_files, repo_root)
    if security_relevant:
        approval = _find_human_approval(reviews, human_reviewer, head_sha)
        if approval:
            approver = approval.get("user", {}).get("login", human_reviewer)
            approved_sha = approval.get("commit_id", "unknown")
            human_auth_reason = f"human authorization (approval by {approver} on {approved_sha})"
            logger.info(
                "Security-relevant PR has human approval from %s on %s; overseer may execute merge",
                approver,
                approved_sha,
            )
        else:
            return MergeAuthorityResult(
                decision=MergeDecision.HUMAN_REQUIRED,
                reason="Security-relevant change — human approval required",
                labels_to_add=["needs-human"],
            )

    # Protected surface: requires human approval.  Same treatment as
    # security-relevant — a verified maintainer approval on the current head
    # satisfies the authorization condition (#589, #741).
    if touches_protected_surface(changed_files, repo_root):
        approval = _find_human_approval(reviews, human_reviewer, head_sha)
        if approval:
            approver = approval.get("user", {}).get("login", human_reviewer)
            approved_sha = approval.get("commit_id", "unknown")
            human_auth_reason = f"human authorization (approval by {approver} on {approved_sha})"
            logger.info(
                "Protected-surface PR has human approval from %s on %s; overseer may execute merge",
                approver,
                approved_sha,
            )
        else:
            return MergeAuthorityResult(
                decision=MergeDecision.HUMAN_REQUIRED,
                reason="PR touches a protected surface — human approval required",
                labels_to_add=["needs-human"],
            )

    # Authorship backstop (R9.1.4)
    if pr_author and not _verify_authorship_separation(pr_author, overseer_handle, worker_handle):
        return MergeAuthorityResult(
            decision=MergeDecision.HUMAN_REQUIRED,
            reason=f"PR author ({pr_author}) == overseer — self-approval blocked",
            labels_to_add=["needs-human"],
        )

    # R9.1.1: re-detect server-side gate immediately before merge decision
    gate = detect_server_side_gate(owner, repo, default_branch, overseer_handle)
    if not gate:
        return MergeAuthorityResult(
            decision=MergeDecision.PROPOSE_ONLY,
            reason=f"Server-side gate not detected ({gate.reason})",
        )

    # Universal human-authorization assertion (#757): every merge — regardless
    # of tier, surface, or security flag — requires a verified human approval
    # on the current head SHA.  Security-relevant and protected-surface paths
    # already set human_auth_reason above; the general path needs this check.
    if not human_auth_reason:
        approval = _find_human_approval(reviews, human_reviewer, head_sha)
        if approval:
            approver = approval.get("user", {}).get("login", human_reviewer)
            approved_sha = approval.get("commit_id", "unknown")
            human_auth_reason = f"human authorization (approval by {approver} on {approved_sha})"
        else:
            return MergeAuthorityResult(
                decision=MergeDecision.HUMAN_REQUIRED,
                reason=(
                    "Merge requires verified human approval on current head SHA — "
                    "none found (#757)"
                ),
                labels_to_add=["needs-human"],
            )

    merge_reason = (
        f"Auto-merge approved: tier={risk_tier.name}, "
        f"ceiling={overseer_ceiling.name}, verdict=PROCEED, "
        f"gate=detected"
    )
    merge_reason += f"; merged by overseer under {human_auth_reason}"

    return MergeAuthorityResult(
        decision=MergeDecision.AUTO_MERGE,
        reason=merge_reason,
    )


# ---------------------------------------------------------------------------
# PR queue management (draft-PR / needs-human / needs-ai)
# ---------------------------------------------------------------------------


def open_draft_pr(
    owner: str,
    repo: str,
    branch: str,
    title: str,
    body: str,
    labels: Sequence[str] = (),
) -> Optional[int]:
    """Open a draft PR and apply labels. Returns PR number or None on failure."""
    try:
        result = _run_gh(
            [
                f"/repos/{owner}/{repo}/pulls",
                "--method",
                "POST",
                "--field",
                f"title={title}",
                "--field",
                f"body={body}",
                "--field",
                f"head={branch}",
                "--field",
                "base=main",
                "--field",
                "draft=true",
            ]
        )
        pr_number = result.get("number") if result else None
        if pr_number and labels:
            _run_gh(
                [
                    f"/repos/{owner}/{repo}/issues/{pr_number}/labels",
                    "--method",
                    "POST",
                    "--field",
                    f"labels={list(labels)}",
                ]
            )
        return pr_number
    except GitHubError as exc:
        logger.error("Failed to open draft PR: %s", exc)
        return None


def route_embargo(
    owner: str,
    repo: str,
    issue_number: int,
) -> None:
    """
    Embargo path for security reports (§5.2, R9.1.5).

    Acknowledges the report, applies hos-embargo label, routes to human.
    Never posts a public fix or opens a public PR.
    """
    ack_body = (
        "---hos-envelope\n"
        "type: ack\n"
        'protocol-version: "1.0"\n'
        "---\n\n"
        "🔒 This report has been classified as a potential security issue and routed "
        "to the responsible human for private review. No public fix will be posted "
        "until coordinated disclosure is complete. Thank you for the report."
    )
    try:
        post_comment(owner, repo, issue_number, ack_body)
        _run_gh(
            [
                f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
                "--method",
                "POST",
                "--field",
                'labels=["hos-embargo", "needs-human"]',
            ]
        )
    except GitHubError as exc:
        logger.error("Failed to route embargo: %s", exc)


# ---------------------------------------------------------------------------
# Register-completeness bounce gate (overseer.md step 4a, SPEC-378 R1.2, #1125)
# ---------------------------------------------------------------------------
#
# Re-checks contract §7 compliance conditions 1-3 (register presence, required
# §3 fields, unresolved ESCALATED entries) against the worker's PR before the
# merge-authority matrix runs. This mirrors the register grammar and required-
# signoffs parsing pr_readiness.py's REQ-W-05/W-06 checks already use (the
# worker's own pre-PR gate) — duplicated here rather than imported to avoid a
# circular import (pr_readiness already imports RiskTier from this module) and
# to keep this module's only cross-package dependency limited to github.py.
# Condition 7b (risk-assessment scope + blocking findings) is out of scope for
# this issue; #1125 names only the register-completeness gate.

_BOUNCE_REGISTER_REQUIRED_FIELDS = ("Status", "Agent", "Artifact", "Iterations")
_BOUNCE_ENTRY_HEADER_RE = re.compile(r"^##\s+(?P<role>[^|#]+?)\s*(?:\|.*)?$")
_BOUNCE_REASON_CATEGORIES = frozenset(
    {
        "REGISTER_GAP",
        "COMPLIANCE_FAILURE",
        "SPEC_AMBIGUITY",
        "OTHER",
        "CHECK_FAILURE",
        "MERITS_FINDING",
        "SCOPE_SIZE",
        "REVIEW_FINDING",
        "MIXED",
    }
)

# The bounce cap before human escalation (overseer.md step 4a). Named here so
# `bootstrap/merge_authority.sh bounce-count` (#1357) can report it without
# coining a second, unnamed "2" (the #1135 duplicate-authority class) — the
# only other place this value appeared was as prose inside
# _bounce_comment_body's f-string.
BOUNCE_CAP = 2

# record_pr_bounce's `cap` default: resolved to the current BOUNCE_CAP at call time
# (not definition time), so a caller that omits it is still capped.
_CAP_DEFAULT: Any = object()


def _bounce_register_path(step: Union[str, int]) -> str:
    return f".claudetmp/signoffs/step{step}-register.md"


def _parse_bounce_register(text: str) -> list[dict]:
    """Parse `.claudetmp/signoffs/step{N}-register.md` into ordered entries.

    Grammar mirrors pr_readiness._parse_register: `## <role>` headers followed
    by `key: value` lines. A role may appear more than once (one entry per
    iteration); callers wanting current state take the last match.
    """
    entries: list[dict] = []
    current: Optional[dict] = None
    for line in text.splitlines():
        m = _BOUNCE_ENTRY_HEADER_RE.match(line)
        if m:
            if current is not None:
                entries.append(current)
            current = {"role": m.group("role").strip(), "fields": {}}
            continue
        if current is None:
            continue
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        current["fields"][key.strip()] = value.strip()
    if current is not None:
        entries.append(current)
    return entries


def _latest_bounce_register_entries(entries: list[dict]) -> dict[str, dict]:
    """Reduce `entries` to the latest occurrence per role (lowercased key)."""
    latest: dict[str, dict] = {}
    for entry in entries:
        latest[entry["role"].lower()] = entry
    return latest


def _required_signoffs_for_step(manifest_path: Path, step: Union[str, int]) -> list[str]:
    """Extract `required_signoffs: [a, b, c]` for `step` from step-manifest.yaml.

    Hand-rolled line scan (stdlib only), mirroring pr_readiness's approach for
    the same file so a missing/malformed manifest degrades to "no required
    roles" rather than raising.
    """
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError:
        return []
    step_str = str(step)
    in_steps = False
    in_target_step = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("steps:"):
            in_steps = True
            continue
        if not in_steps:
            continue
        if line and not line[0].isspace() and ":" in line and not stripped.startswith("-"):
            in_steps = False
            in_target_step = False
            continue
        if stripped.startswith("- id:"):
            id_val = stripped[len("- id:") :].strip().strip("\"'")
            in_target_step = id_val == step_str
            continue
        if in_target_step and stripped.startswith("id:"):
            id_val = stripped[len("id:") :].strip().strip("\"'")
            in_target_step = id_val == step_str
            continue
        if in_target_step and stripped.startswith("required_signoffs:"):
            raw = stripped[len("required_signoffs:") :].strip()
            raw = raw.strip("[]")
            if not raw:
                return []
            return [r.strip() for r in raw.split(",") if r.strip()]
    return []


@dataclass
class RegisterCompletenessResult:
    bounce_required: bool
    failures: list[str] = field(default_factory=list)
    reason_category: Optional[str] = None
    summary: Optional[str] = None


def check_register_completeness(
    step: Union[str, int],
    *,
    repo_root: str = ".",
    manifest_path: Optional[str] = None,
) -> RegisterCompletenessResult:
    """Re-check contract §7 conditions 1-3 against the PR's sign-off register.

    Reads `.claudetmp/signoffs/step{N}-register.md` and the required-signoffs
    list for `step` from step-manifest.yaml, both from the PR branch's working
    tree (repo_root — the overseer's checkout already has the PR branch
    present when step 4a runs, the same precondition step 3b relies on for
    `signoffs/validators/step{N}/summary.json`).
    """
    root = Path(repo_root)
    manifest = Path(manifest_path) if manifest_path else root / "contract" / "step-manifest.yaml"
    required_roles = _required_signoffs_for_step(manifest, step)

    if not required_roles:
        # Nothing is required for this step, so there is nothing to be
        # incomplete about — even a wholly absent register is not a gap.
        return RegisterCompletenessResult(bounce_required=False)

    register_file = root / _bounce_register_path(step)
    try:
        text = register_file.read_text(encoding="utf-8")
    except OSError:
        text = None

    if text is None:
        return RegisterCompletenessResult(
            bounce_required=True,
            failures=["register-missing"],
            reason_category="REGISTER_GAP",
            summary=f"Sign-off register {_bounce_register_path(step)} is missing.",
        )

    latest = _latest_bounce_register_entries(_parse_bounce_register(text))

    failures: list[str] = []
    for role in required_roles:
        entry = latest.get(role.lower())
        if entry is None:
            failures.append(f"register-missing-role:{role}")
            continue
        missing_fields = [f for f in _BOUNCE_REGISTER_REQUIRED_FIELDS if not entry["fields"].get(f)]
        if missing_fields:
            failures.append(f"register-missing-fields:{role}:{','.join(missing_fields)}")
            continue
        status = entry["fields"].get("Status", "").strip().upper()
        if status == "ESCALATED" and not entry["fields"].get("Human_resolution", "").strip():
            failures.append(f"register-unresolved-escalation:{role}")

    if not failures:
        return RegisterCompletenessResult(bounce_required=False)

    summary = f"{len(failures)} sign-off register gap(s) on step {step}: " + "; ".join(failures)
    return RegisterCompletenessResult(
        bounce_required=True,
        failures=failures,
        reason_category="REGISTER_GAP",
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Required-content-checks bounce gate (#1580, overseer.md step 4c)
# ---------------------------------------------------------------------------

# These three checks encode WHO must approve (human / overseer / tier
# ceiling), not the PR's content — see their own workflow headers
# (.github/workflows/require-*.yml). A worker push cannot turn one green by
# itself (e.g. require-human-approval only passes once a human approves), so
# treating them as a worker-fixable bounce condition would create a bounce
# loop indistinguishable from progress. Every other required context
# (oversight-gate-*, oversight-validator-*, tests, ...) is ordinary CI that a
# worker fix genuinely can turn green, so a failure there is a real bounce
# condition.
_META_GATE_CHECKS = frozenset(
    {
        "require-human-approval",
        "require-overseer-approval",
        "require-tier-ceiling",
    }
)

_FAILING_CONCLUSIONS = frozenset({"failure", "timed_out", "cancelled", "action_required"})


@dataclass
class RequiredChecksResult:
    bounce_required: bool
    failures: list[str] = field(default_factory=list)
    reason_category: Optional[str] = None
    summary: Optional[str] = None


def _latest_check_runs_by_name(runs: Sequence[dict]) -> dict[str, dict]:
    """Latest check run per name: the highest integer ``id`` wins (list order
    is not guaranteed). Non-dict runs and runs without a name are skipped; a
    run with a missing or non-int id (a bool is not an int) loses to any run
    that has one."""
    latest_by_name: dict[str, dict] = {}

    def _run_id(r: dict) -> int:
        rid = r.get("id")
        return rid if isinstance(rid, int) and not isinstance(rid, bool) else -1

    for run in runs:
        if not isinstance(run, dict):
            continue
        name = run.get("name")
        if not isinstance(name, str) or not name:
            continue
        current = latest_by_name.get(name)
        if current is None or _run_id(run) > _run_id(current):
            latest_by_name[name] = run
    return latest_by_name


@dataclass
class LiveGateResult(GateDetectionResult):
    """GateDetectionResult plus the evidence the human-approval merge path
    needs (#2213 TD-D7): the required contexts and the qualifying ruleset ids."""

    required_contexts: tuple[str, ...] = ()
    ruleset_ids: tuple[int, ...] = ()
    evidence: dict = field(default_factory=dict)


def verify_merge_gate_live(
    owner: str,
    repo: str,
    branch: str,
    *,
    tier_ceiling_check_name: str,
) -> LiveGateResult:
    """
    Verify, from the live repository ruleset, that a server-side gate the
    caller cannot bypass protects ``branch`` (#2213 AD-5, TD-D7/TD-D8).

    Never raises. Each failure returns ``autonomous_capable=False`` with a
    named reason. Every required property (each meta context, the approving
    review count, stale-review dismissal) must be supplied by at least one
    rule whose ruleset is ``active`` and reports ``current_user_can_bypass ==
    "never"`` for the calling token. Classic branch protection is never
    consulted (AF-1).
    """

    def _fail(reason: str, evidence: Optional[dict] = None) -> LiveGateResult:
        return LiveGateResult(
            autonomous_capable=False, reason=reason, evidence=dict(evidence or {})
        )

    try:
        rules = list_branch_rules(owner, repo, branch)
    except GitHubError as exc:
        return _fail(f"rules read failed: {exc}")

    contexts = _required_contexts_from_rules(rules)
    meta = (_META_GATE_CHECKS - {"require-tier-ceiling"}) | {tier_ceiling_check_name}
    for name in sorted(meta):
        if name not in contexts:
            return _fail(f"required context missing: {name}")

    def _ruleset_id(rule: dict) -> Optional[int]:
        rid = rule.get("ruleset_id")
        return rid if isinstance(rid, int) and not isinstance(rid, bool) else None

    def _supplies(rule: object, context: str) -> bool:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            return False
        return context in _required_contexts_from_rules([rule])

    def _qualifying_pr_rule(rule: object) -> bool:
        if not isinstance(rule, dict) or rule.get("type") != "pull_request":
            return False
        params = rule.get("parameters")
        if not isinstance(params, dict):
            return False
        count = params.get("required_approving_review_count")
        return (
            isinstance(count, int)
            and not isinstance(count, bool)
            and count >= 1
            and params.get("dismiss_stale_reviews_on_push") is True
        )

    pr_rules = [r for r in rules if _qualifying_pr_rule(r)]
    if not pr_rules:
        return _fail("no pull_request rule with >=1 approval and stale-review dismissal")

    evidence: dict = {}
    qualified: dict[int, bool] = {}

    def _ruleset_qualifies(rule: dict) -> bool:
        rid = _ruleset_id(rule)
        if rid is None:
            return False
        if rid not in qualified:
            try:
                rs = get_ruleset(owner, repo, rid)
            except GitHubError as exc:
                evidence[rid] = {"error": str(exc)}
                qualified[rid] = False
            else:
                if isinstance(rs, dict):
                    evidence[rid] = {
                        "enforcement": rs.get("enforcement"),
                        "current_user_can_bypass": rs.get("current_user_can_bypass"),
                    }
                    qualified[rid] = (
                        rs.get("enforcement") == "active"
                        and rs.get("current_user_can_bypass") == "never"
                    )
                else:
                    evidence[rid] = {"error": "ruleset not readable"}
                    qualified[rid] = False
        return qualified[rid]

    properties: list[tuple[str, list[dict]]] = [
        (name, [r for r in rules if _supplies(r, name)]) for name in sorted(meta)
    ]
    properties.append(("pull_request", pr_rules))
    for prop, suppliers in properties:
        if not any(_ruleset_qualifies(r) for r in suppliers):
            return _fail(f"ruleset bypassable or unverifiable for: {prop}", evidence)

    ids = sorted(rid for rid, ok in qualified.items() if ok)
    return LiveGateResult(
        autonomous_capable=True,
        reason="ruleset gate verified (#2213 AD-5)",
        required_contexts=tuple(contexts),
        ruleset_ids=tuple(ids),
        evidence=evidence,
    )


def check_required_content_checks(
    owner: str,
    repo: str,
    head_sha: str,
    *,
    default_branch: str = "main",
) -> RequiredChecksResult:
    """
    Detect required, worker-fixable status checks currently failing on
    ``head_sha`` (#1580).

    This is a content signal, not an approval signal: it exists so that
    ordinary "changes needed" findings (a required CI gate is red) bounce
    back to the worker like any other procedural gap (mirrors
    check_register_completeness / overseer.md step 4a), instead of falling
    through to the protected-surface/CODEOWNERS pre-matrix gate and
    escalating straight to human. That gate still fires once these checks are
    green (or once the bounce budget is exhausted) — this function only ever
    adds a bounce opportunity, it never removes the human-approval
    requirement for the final merge.

    Reads the union of repository-ruleset required checks and classic
    branch-protection required_status_checks.contexts (not a hardcoded list)
    so it stays in sync with whatever is actually promoted to required at call
    time. Rulesets matter because this repo's required checks live there, and
    the overseer App gets 403 on the classic endpoint (#1731, #1588). Each
    read degrades independently, and a single failure is logged at warning.
    The gate fails open (no bounce, warning logged, diagnostic summary) when
    both reads fail, or when the ruleset read fails and classic yields no
    contexts: rulesets are the primary source, so an empty classic set says
    nothing about what is required. The protected-surface/CODEOWNERS gates
    that run next still fail closed to HUMAN_REQUIRED, so merge safety is
    unaffected. Malformed payload elements are ignored, never raised.
    """
    required_contexts: list[str] = []
    errors: list[str] = []
    ruleset_failed = False

    try:
        protection = get_branch_protection(owner, repo, default_branch, retries=0)
        rsc = protection.get("required_status_checks") if isinstance(protection, dict) else None
        classic = rsc.get("contexts") if isinstance(rsc, dict) else None
        if isinstance(classic, list):
            required_contexts.extend(c for c in classic if isinstance(c, str))
    except GitHubError as exc:
        errors.append(f"classic protection read failed: {exc}")
        logger.warning("required-checks gate: classic protection read failed: %s", exc)

    classic_count = len(required_contexts)

    try:
        required_contexts.extend(get_ruleset_required_checks(owner, repo, default_branch))
    except GitHubError as exc:
        ruleset_failed = True
        errors.append(f"ruleset read failed: {exc}")
        logger.warning("required-checks gate: ruleset read failed: %s", exc)

    if len(errors) == 2 or (ruleset_failed and classic_count == 0):
        summary = "required-checks gate skipped, no usable required-check source: " + "; ".join(
            errors
        )
        logger.warning(summary)
        return RequiredChecksResult(bounce_required=False, summary=summary)

    content_contexts = [c for c in dict.fromkeys(required_contexts) if c not in _META_GATE_CHECKS]
    if not content_contexts:
        return RequiredChecksResult(bounce_required=False)

    runs = list_check_runs_for_ref(owner, repo, head_sha)
    latest_by_name = _latest_check_runs_by_name(runs)

    failing = []
    for name in content_contexts:
        matched_run = latest_by_name.get(name)
        if matched_run is None:
            continue  # not yet reported (queued / not started) — not a bounce condition
        if matched_run.get("conclusion") in _FAILING_CONCLUSIONS:
            failing.append(name)

    if not failing:
        return RequiredChecksResult(bounce_required=False)

    summary = f"{len(failing)} required check(s) failing on head {head_sha[:8]}: " + ", ".join(
        failing
    )
    return RequiredChecksResult(
        bounce_required=True,
        failures=[f"check-failing:{name}" for name in failing],
        reason_category="COMPLIANCE_FAILURE",
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Audit trail — bounce counter + pr-bounced event (contract §6a)
# ---------------------------------------------------------------------------


def _load_audit_log():
    """Load scripts/oversight/lib/audit_log.py by path (mirrors cycle_log.py).

    Loaded by file path rather than `from scripts.oversight...` so this
    module's cross-package dependency stays limited to the CLI it already
    calls via gh, not a live import of the oversight package (same trust-
    direction rationale as codeowners.py's KNOWN DIVERGENCE note).
    """
    path = Path(__file__).resolve().parents[2] / "oversight" / "lib" / "audit_log.py"
    spec = importlib.util.spec_from_file_location("hos_audit_log", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_AUDIT_LOG = _load_audit_log()


def bounce_events(cid: str, *, repo_root: str = ".") -> list[dict]:
    """Every `pr-bounced` audit event for `cid`, in chronological order.

    A malformed record raises ValueError (from `read_stream`); an absent
    audit/log/ yields an empty list (#2209 §3.5).
    """
    events: list[dict] = []
    for raw in _AUDIT_LOG.read_stream(repo_root):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(event, dict)
            and event.get("event") == "pr-bounced"
            and event.get("cid") == cid
        ):
            events.append(event)
    return events


def _bounce_event_time(event: dict) -> Optional[datetime]:
    """GitHub's comment time when recorded, else the audit timestamp."""
    return _parse_iso(event.get("comment_created_at") or event.get("timestamp"))


def bounce_count(cid: str, *, repo_root: str = ".", since: Optional[str] = None) -> int:
    """Count prior `pr-bounced` audit events for this correlation id.

    The audit trail (audit/log/) is append-only and already the source of
    truth for every other per-cid counter in this codebase (contract §6a);
    this derives the count from it rather than maintaining separate state.
    Shared by step 4a (register-completeness) and step 4c (required
    content checks) — "the existing bounce_count(cid) counter" both cite.

    With `since` (#2209 epoch), only events whose time is strictly later are
    counted. An event whose time cannot be parsed is counted: an unparseable
    time pushes toward the cap and an earlier escalation, never toward a merge.
    """
    since_dt = _parse_iso(since) if since is not None else None
    count = 0
    for event in bounce_events(cid, repo_root=repo_root):
        if since_dt is not None:
            when = _bounce_event_time(event)
            if when is not None and when <= since_dt:
                continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Rejection routing (#2209 S1a)
# ---------------------------------------------------------------------------

# ARCH-ESC-1 (A): the bounce epoch also restarts at each escalation. Setting
# this to False is the whole of ARCH-ESC-1 option (B).
EPOCH_RESETS_AT_ESCALATION = True

FINDING_CLASSES = (
    "PROCEDURAL",
    "REQUIRED_CHECK",
    "CHECK",
    "MERITS",
    "SCOPE",
    "REVIEW_FINDING",
    "REVIEW_CHAIN",
)
LLM_FINDING_CLASSES = frozenset({"CHECK", "MERITS", "SCOPE", "REVIEW_FINDING", "REVIEW_CHAIN"})
# #2346: the closed set of roles a REVIEW_CHAIN finding may name as missing
# from the review chain. The slug is a role name from the tier table, never
# PR-body text, so the bounce summary stays code-templated.
REVIEW_CHAIN_ROLES = (
    "second-review-agy",
    "second-review-codex",
    "second-review",
    "oversight-evaluator",
    "security-reviewer",
    "reliability-reviewer",
)
REVIEW_CHAIN_SUMMARY_PREFIX = "incomplete-review-chain:"
ESCALATION_TRIGGERS = ("upheld-dispute", "bounce-cap", "reviewer-conflict", "decision")

# Mirror .claude/agents/overseer.md:328-329 (15 files / 10 commits soft limits,
# 25-file hard ceiling).
SIZE_SOFT_FILES = 15
SIZE_SOFT_COMMITS = 10
SIZE_HARD_FILES = 25

FINDINGS_FILE_MAX_BYTES = 262144
FINDINGS_MAX = 50
_EPOCH_MAX_SIBLING_PRS = 50
_ISSUE_EVENTS_MAX_PAGES = 10

# Legacy `failures=` tokens as check_register_completeness and
# check_required_content_checks emit them (AR1-C3).
_LEGACY_PROCEDURAL_PREFIXES = (
    "register-missing",
    "register-missing-role:",
    "register-missing-fields:",
    "register-unresolved-escalation:",
)
_LEGACY_REQUIRED_CHECK_PREFIX = "check-failing:"

_SLUG_RE = re.compile(r"^[a-z0-9-]{3,40}$")
_RULE_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
_REVIEWER_RE = re.compile(r"^[a-z0-9-]{2,40}$")
_DECISION_LABEL_RE = re.compile(r"^[A-Za-z0-9-]{1,20}$")
_LINE_NO_RE = re.compile(r":\d+$")
_WORKER_REF_RE = re.compile(r"^worker-(\d+)-")
_FINDING_ID_RE = re.compile(r"^[0-9a-f]{12}-F(\d+)$")
_OPTION_LINE_RE = re.compile(r"^Option:\s*(?P<l>[A-Za-z0-9-]{1,20})\s*$", re.MULTILINE)
_LEGACY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
_ENTRY_KEYS = frozenset(
    {
        "class",
        "summary",
        "detail",
        "path",
        "slug",
        "check_run",
        "rule",
        "source_url",
        "decision",
        "conflicts_with",
    }
)


class Option(NamedTuple):
    label: str
    text: str


@dataclass(frozen=True)
class Decision:
    question: str
    options: tuple[Option, ...]


@dataclass(frozen=True)
class Conflict:
    reviewer: str
    ref: str


@dataclass(frozen=True)
class Finding:
    cls: str
    key: str
    identity: tuple
    origin: str  # "code" | "llm"
    path: Optional[str]
    summary: str
    detail: str = ""
    source_url: Optional[str] = None
    decision: Optional[Decision] = None
    conflicts_with: Optional[Conflict] = None

    @property
    def is_decision(self) -> bool:
        return self.decision is not None


@dataclass(frozen=True)
class PriorFinding:
    finding_id: str
    cls: str
    key: str
    identity: tuple
    origin: str


@dataclass(frozen=True)
class ReviewerAct:
    kind: str  # APPROVED | CHANGES_REQUESTED | DISMISSED | NEEDS_AI_LABEL
    source_id: int
    at: str
    option_label: Optional[str] = None


@dataclass(frozen=True)
class EscalationRecord:
    pr: int
    head_sha: str
    trigger: str
    created_at: str
    option_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class PrClosure:
    pr: int
    kind: str  # "merged" | "closed"
    at: str
    actor_login: str
    actor_type: str


@dataclass(frozen=True)
class Block:
    kind: str  # PATH_HOLD | UNKNOWN_SCOPE | PATH_PENDING_ESCALATION
    source_pr: int
    ref: str


class VetoState(Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NEEDS_START = "NEEDS_START"
    OPEN = "OPEN"
    LAPSED = "LAPSED"


class Disposition(Enum):
    LEGACY = "LEGACY"
    PROCEED = "PROCEED"
    BOUNCE = "BOUNCE"
    NOOP = "NOOP"
    ESCALATE = "ESCALATE"
    HOLD = "HOLD"
    HOLD_VETO = "HOLD_VETO"
    HUMAN_SENDBACK = "HUMAN_SENDBACK"
    RULING_REQUIRED = "RULING_REQUIRED"


@dataclass(frozen=True)
class CidResolution:
    cid: str
    source: str  # "issue" | "pr-fallback"
    issue: Optional[int]
    warn: Optional[str]


@dataclass(frozen=True)
class ReviewerResolution:
    login: str
    source: str  # "codeowners" | "machine-accounts.env"
    team_owners: tuple[str, ...]
    note: Optional[str]


class FindingsSchemaError(ValueError):
    """The findings file (or one entry of it) is refused."""


class FindingsFileError(FindingsSchemaError):
    """The findings file is missing, oversize or not JSON (CLI: findings_file_invalid)."""


class CodeownersUnreadableError(GitHubError):
    """A CODEOWNERS payload at the base ref exists but cannot be used."""


class BounceAuditWriteError(Exception):
    """The audit event could not be written AFTER the bounce comment was posted."""


class CodeownersDriftError(Exception):
    """step 6's resolver and the humans-set parser disagree."""


def classify_github_error(exc: GitHubError) -> str:
    """'transient' (worth a retry next cycle) or 'deterministic' (needs a fix)."""
    if isinstance(exc, RateLimitError):
        return "transient"
    if isinstance(exc, ListTruncatedError):
        return "deterministic"
    status = getattr(exc, "status_code", None)
    if status is None or status >= 500:
        return "transient"
    return "deterministic"


# --- finding identity, keys and the findings file ---------------------------


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def finding_identity(
    cls: str, key: str, origin: str, path: Optional[str], check_run: Optional[str] = None
) -> tuple:
    """TD-D2: the same-head identity tuple, by origin and class."""
    if origin == "code" or cls == "REVIEW_CHAIN":
        return (cls, key)  # REVIEW_CHAIN has no path: the role slug is its identity
    if cls == "CHECK":
        return ("CHECK", check_run, path or "-")
    return (cls, path or "-")


def load_findings_file(path: Union[str, Path]) -> object:
    """Read and JSON-parse the findings file. FindingsFileError on any failure."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise FindingsFileError(f"cannot read findings file: {exc.__class__.__name__}") from exc
    return parse_findings_bytes(data)


def parse_findings_bytes(data: bytes) -> object:
    if len(data) > FINDINGS_FILE_MAX_BYTES:
        raise FindingsFileError(f"findings file exceeds {FINDINGS_FILE_MAX_BYTES} bytes")
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FindingsFileError(
            f"findings file is not UTF-8 JSON: {exc.__class__.__name__}"
        ) from exc


def _schema_fail(index: int, field_name: str, message: str) -> NoReturn:
    raise FindingsSchemaError(f"findings[{index}].{field_name}: {message}")


def _parse_decision(raw: object, index: int) -> Optional[Decision]:
    """A structurally valid decision object -> Decision, or None when the
    decision is malformed (AD-1: dropped by code, the finding stays a rejection).
    A decision that is not even the right JSON shape is a schema error."""
    if not isinstance(raw, dict) or set(raw) - {"question", "options"}:
        _schema_fail(index, "decision", "must be an object with only question and options")
    question, options = raw.get("question"), raw.get("options")
    if not isinstance(question, str) or not isinstance(options, list):
        _schema_fail(index, "decision", "question must be a string and options a list")
    parsed: list[Option] = []
    for j, opt in enumerate(options):
        if (
            not isinstance(opt, dict)
            or set(opt) != {"label", "text"}
            or not isinstance(opt["label"], str)
            or not isinstance(opt["text"], str)
        ):
            _schema_fail(
                index, f"decision.options[{j}]", "must be an object {label, text} of strings"
            )
        parsed.append(Option(opt["label"].strip(), opt["text"].strip()))
    labels = [o.label for o in parsed]
    texts = [o.text for o in parsed]
    valid = (
        bool(question.strip())
        and len(parsed) >= 2
        and len(set(labels)) == len(labels)
        and len(set(texts)) == len(texts)
        and all(_DECISION_LABEL_RE.match(label) for label in labels)
        and all(texts)
    )
    return Decision(question.strip(), tuple(parsed)) if valid else None


# Characters that could break out of a markdown link or inject markup/mentions
# when the URL is interpolated into a bounce comment (CWE-116).
_URL_UNSAFE_CHARS = frozenset("()[]<>@!`")


def _same_repo_url(value: object, repo_slug: str, index: int, field_name: str) -> str:
    prefix = f"https://github.com/{repo_slug.lower()}/"
    if (
        not isinstance(value, str)
        or len(value) > 500
        or re.search(r"\s", value)
        or not value.lower().startswith(prefix)
        or ".." in value.split("#", 1)[0].split("?", 1)[0].split("/")
        or "%2e" in value.lower()
        or "\\" in value
        or any(c in value for c in _URL_UNSAFE_CHARS)
    ):
        _schema_fail(
            index, field_name, f"must be a same-repo URL under {prefix} with no '..' segments"
        )
    return value


def canonicalize_findings_ex(
    raw: object,
    *,
    changed_paths: Sequence[str],
    head_check_runs: Sequence[str],
    repo_slug: str,
) -> tuple[tuple[Finding, ...], tuple[str, ...]]:
    """canonicalize_findings plus the closed reason tokens it recorded."""
    if (
        not isinstance(raw, dict)
        or set(raw) != {"findings"}
        or not isinstance(raw["findings"], list)
    ):
        raise FindingsSchemaError('top level must be exactly {"findings": [...]}')
    entries = raw["findings"]
    if len(entries) > FINDINGS_MAX:
        raise FindingsSchemaError(f"more than {FINDINGS_MAX} findings")

    changed = {_nfc(p) for p in changed_paths}
    check_runs = set(head_check_runs)
    reasons: list[str] = []
    out: list[Finding] = []
    seen: set[str] = set()

    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            _schema_fail(i, "entry", "must be an object")
        unknown = sorted(set(entry) - _ENTRY_KEYS)
        if unknown:
            _schema_fail(i, unknown[0], "unknown key (key, origin and id are computed by the CLI)")

        cls = entry.get("class")
        if cls in ("PROCEDURAL", "REQUIRED_CHECK"):
            _schema_fail(i, "class", "class reserved for code collectors")
        if cls not in LLM_FINDING_CLASSES:
            _schema_fail(i, "class", f"must be one of {sorted(LLM_FINDING_CLASSES)}")

        summary = entry.get("summary")
        if (
            not isinstance(summary, str)
            or not 1 <= len(summary) <= 200
            or "\n" in summary
            or "\r" in summary
            or summary.lstrip().startswith("/hos")
        ):
            _schema_fail(i, "summary", "must be 1-200 characters, one line, not starting with /hos")
        detail = entry.get("detail", "")
        if not isinstance(detail, str) or len(detail) > 2000:
            _schema_fail(i, "detail", "must be a string of at most 2000 characters")

        path = entry.get("path")
        if path is not None:
            if not isinstance(path, str):
                _schema_fail(i, "path", "must be a string or null")
            path = _nfc(path)
            if path.startswith("./"):
                path = path[2:]
            if _LINE_NO_RE.search(path):
                _schema_fail(i, "path", "no line numbers in a path")
            if path not in changed:
                _schema_fail(i, "path", "is not a file changed by this PR")

        slug = entry.get("slug")
        check_run = entry.get("check_run")
        rule = entry.get("rule")
        if cls == "CHECK":
            if slug is not None:
                _schema_fail(i, "slug", "not allowed on a CHECK finding")
            if not isinstance(check_run, str) or check_run not in check_runs:
                _schema_fail(i, "check_run", "must equal a check-run name on the head")
            if rule is None:
                rule = "-"
            elif not isinstance(rule, str) or not _RULE_RE.match(rule):
                _schema_fail(i, "rule", f"must match {_RULE_RE.pattern}")
            key = f"check:{check_run}:{rule}:{path or '-'}"
        else:
            if check_run is not None or rule is not None:
                _schema_fail(
                    i, "check_run" if check_run is not None else "rule", "CHECK findings only"
                )
            if not isinstance(slug, str) or not _SLUG_RE.match(slug):
                _schema_fail(i, "slug", f"required, must match {_SLUG_RE.pattern}")
            if cls == "REVIEW_CHAIN":
                if path is not None:
                    _schema_fail(i, "path", "not allowed on a REVIEW_CHAIN finding")
                if slug not in REVIEW_CHAIN_ROLES:
                    _schema_fail(i, "slug", f"must be one of {list(REVIEW_CHAIN_ROLES)}")
            key = f"{cls}:{path or '-'}:{slug}"

        source_url = entry.get("source_url")
        if source_url is not None:
            source_url = _same_repo_url(source_url, repo_slug, i, "source_url")

        decision = None
        if entry.get("decision") is not None:
            decision = _parse_decision(entry["decision"], i)
            if decision is None:
                reasons.append(f"decision-malformed:{i}")

        conflict = None
        raw_conflict = entry.get("conflicts_with")
        if raw_conflict is not None:
            if (
                not isinstance(raw_conflict, dict)
                or set(raw_conflict) != {"reviewer", "ref"}
                or not isinstance(raw_conflict["reviewer"], str)
                or not _REVIEWER_RE.match(raw_conflict["reviewer"])
            ):
                _schema_fail(
                    i, "conflicts_with", "must be {reviewer, ref} with a valid reviewer name"
                )
            conflict = Conflict(
                raw_conflict["reviewer"],
                _same_repo_url(raw_conflict["ref"], repo_slug, i, "conflicts_with.ref"),
            )

        if key in seen:
            reasons.append(f"duplicate-key:{i}")
            continue
        seen.add(key)
        out.append(
            Finding(
                cls=cls,
                key=key,
                identity=finding_identity(cls, key, "llm", path, check_run),
                origin="llm",
                path=path,
                summary=summary,
                detail=detail,
                source_url=source_url,
                decision=decision,
                conflicts_with=conflict,
            )
        )
    return tuple(out), tuple(reasons)


def canonicalize_findings(
    raw: object,
    *,
    changed_paths: Sequence[str],
    head_check_runs: Sequence[str],
    repo_slug: str,
) -> tuple[Finding, ...]:
    """Validate the parsed findings file and build canonical Findings (TD §3.3).

    Raises FindingsSchemaError naming the offending index and field. The CLI
    alone builds `key`; a `key`, `origin` or `id` in the file is refused.
    """
    findings, _ = canonicalize_findings_ex(
        raw, changed_paths=changed_paths, head_check_runs=head_check_runs, repo_slug=repo_slug
    )
    return findings


# --- the correlation id -----------------------------------------------------


def bounce_cid(
    pr: dict,
    *,
    worker_login: str,
    issue_lookup: Callable[[int], Optional[dict]],
) -> CidResolution:
    """`issue-<N>` when the PR is a worker PR for a real issue, else `pr-<n>`.

    A GitHubError from `issue_lookup` propagates: falling back to `pr-<n>` on
    a transient failure would hand out a fresh bounce budget (AF-1). Only a
    None result (404 or empty body) counts as "not found". No PR text is parsed.
    """
    number = pr.get("number")
    fallback = f"pr-{number}"
    user = pr.get("user") or {}
    head = pr.get("head") or {}
    base = pr.get("base") or {}

    def _fallback(warn: str) -> CidResolution:
        return CidResolution(cid=fallback, source="pr-fallback", issue=None, warn=warn)

    if (
        str(user.get("login", "")).lower() != worker_login.lower()
        or str(user.get("type", "")) != "Bot"
    ):
        return _fallback("not-worker-author")
    match = _WORKER_REF_RE.match(str(head.get("ref") or ""))
    if not match or str(int(match.group(1))) != match.group(1) or int(match.group(1)) == 0:
        return _fallback("ref-not-worker-format")
    head_repo = str((head.get("repo") or {}).get("full_name") or "").lower()
    base_repo = str((base.get("repo") or {}).get("full_name") or "").lower()
    if not head_repo or head_repo != base_repo:
        return _fallback("fork-head")
    issue_number = int(match.group(1))
    issue = issue_lookup(issue_number)
    if not isinstance(issue, dict):
        return _fallback("issue-not-found")
    if "pull_request" in issue:
        return _fallback("number-is-a-pr")
    return CidResolution(cid=f"issue-{issue_number}", source="issue", issue=issue_number, warn=None)


# --- the epoch --------------------------------------------------------------


def escalation_records(cid: str, *, repo_root: str = ".") -> list[EscalationRecord]:
    """`human-required` events carrying this cid and a known trigger.

    Legacy events (no cid or trigger, AF-4) are ignored. Nothing writes the
    new form in S1a: `record-escalation` is S1b.
    """
    records: list[EscalationRecord] = []
    for raw in _AUDIT_LOG.read_stream(repo_root):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if (
            not isinstance(event, dict)
            or event.get("event") != "human-required"
            or not event.get("cid")
            or event.get("cid") != cid
            or event.get("trigger") not in ESCALATION_TRIGGERS
        ):
            continue
        labels = event.get("options")
        pr_number = event.get("pr")
        records.append(
            EscalationRecord(
                pr=pr_number if isinstance(pr_number, int) else 0,
                head_sha=str(event.get("head_sha") or ""),
                trigger=event["trigger"],
                created_at=str(event.get("escalation_created_at") or event.get("timestamp") or ""),
                option_labels=tuple(str(x) for x in labels) if isinstance(labels, list) else (),
            )
        )
    return records


def epoch_start(
    *,
    this_pr_created_at: str,
    escalations: Sequence[EscalationRecord],
    sibling_closures: Sequence[PrClosure],
    worker_login: str,
) -> Optional[str]:
    """The latest epoch boundary, or None for the whole history (TD §3.5).

    A boundary is an escalation (when EPOCH_RESETS_AT_ESCALATION) or a sibling
    PR closed or merged by a non-worker before this PR opened.
    """
    candidates: list[tuple[datetime, str]] = []
    if EPOCH_RESETS_AT_ESCALATION:
        for esc in escalations:
            when = _parse_iso(esc.created_at)
            if when is not None:
                candidates.append((when, esc.created_at))
    opened = _parse_iso(this_pr_created_at)
    if opened is not None:
        for closure in sibling_closures:
            when = _parse_iso(closure.at)
            if (
                when is not None
                and when < opened
                and closure.actor_login.lower() != worker_login.lower()
            ):
                candidates.append((when, closure.at))
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1]


# --- same-head dedup --------------------------------------------------------


def legacy_token_finding(token: str) -> tuple[str, str, tuple]:
    """Map a legacy `failures=` token to (cls, key, identity) (AR1-C3).

    Register and required-check tokens map to exactly the key and identity the
    code collectors produce for them, so a legacy bounce followed by a
    findings-path bounce on the same head is a repeat, not a second bounce.
    """
    if token == _LEGACY_PROCEDURAL_PREFIXES[0] or token.startswith(_LEGACY_PROCEDURAL_PREFIXES[1:]):
        key = f"PROCEDURAL:{token}"
        return "PROCEDURAL", key, ("PROCEDURAL", key)
    if token.startswith(_LEGACY_REQUIRED_CHECK_PREFIX):
        key = f"REQUIRED_CHECK:{token}"
        return "REQUIRED_CHECK", key, ("REQUIRED_CHECK", key)
    return "LEGACY", token, ("LEGACY", token)


def _prior_identity(entry: dict) -> tuple:
    cls, key, origin = entry.get("class"), str(entry.get("key")), entry.get("origin")
    path = entry.get("path")
    check_run = None
    if cls == "CHECK" and origin == "llm" and key.startswith("check:"):
        # key = check:<run>:<rule>:<path|->; rule has no ':' so the split is exact.
        body = key[len("check:") :]
        suffix = f":{path or '-'}"
        if body.endswith(suffix):
            head_part = body[: -len(suffix)]
            check_run = head_part.rsplit(":", 1)[0] if ":" in head_part else None
        if check_run is None:
            return ("CHECK", key)
    return finding_identity(str(cls), key, str(origin), path, check_run)


def bounced_on_head(cid: str, head_sha: str, *, repo_root: str = ".") -> tuple[PriorFinding, ...]:
    """Every finding already bounced on (cid, head_sha), legacy events included."""
    prior: list[PriorFinding] = []
    for event in bounce_events(cid, repo_root=repo_root):
        if event.get("head_sha") != head_sha:
            continue
        findings = event.get("findings")
        if isinstance(findings, list):
            for entry in findings:
                if not isinstance(entry, dict):
                    continue
                prior.append(
                    PriorFinding(
                        finding_id=str(entry.get("id") or ""),
                        cls=str(entry.get("class")),
                        key=str(entry.get("key")),
                        identity=_prior_identity(entry),
                        origin=str(entry.get("origin")),
                    )
                )
            continue
        for token in event.get("failures") or []:
            cls, key, identity = legacy_token_finding(str(token))
            prior.append(
                PriorFinding(
                    finding_id="",
                    cls=cls,
                    key=key,
                    identity=identity,
                    origin="legacy" if cls == "LEGACY" else "code",
                )
            )
    return tuple(prior)


def next_finding_index(prior: Sequence[PriorFinding]) -> int:
    """1 + the highest k over ids shaped `<head12>-F<k>`, else 1."""
    highest = 0
    for p in prior:
        match = _FINDING_ID_RE.match(p.finding_id)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


# --- the bounce comment -----------------------------------------------------

_CLASS_REASON_CATEGORY = {
    "PROCEDURAL": "REGISTER_GAP",
    "REQUIRED_CHECK": "COMPLIANCE_FAILURE",
    "CHECK": "CHECK_FAILURE",
    "MERITS": "MERITS_FINDING",
    "SCOPE": "SCOPE_SIZE",
    "REVIEW_FINDING": "REVIEW_FINDING",
    "REVIEW_CHAIN": "REGISTER_GAP",
}


def derive_reason_category(classes: Iterable[str]) -> str:
    unique = set(classes)
    if len(unique) == 1:
        return _CLASS_REASON_CATEGORY[next(iter(unique))]
    return "MIXED"


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _legacy_gloss(token: str) -> str:
    if token == "register-missing":
        return "Sign-off register is missing"
    if token.startswith("register-missing-role:"):
        return f"Required sign-off missing: {token.partition(':')[2]}"
    if token.startswith("register-missing-fields:"):
        role, _, fields = token.partition(":")[2].partition(":")
        return f"Sign-off {role} is missing field(s) {fields}"
    if token.startswith("register-unresolved-escalation:"):
        return f"Sign-off {token.partition(':')[2]} is ESCALATED with no Human_resolution"
    if token.startswith(_LEGACY_REQUIRED_CHECK_PREFIX):
        return f"Required check {token[len(_LEGACY_REQUIRED_CHECK_PREFIX):]} is failing"
    return token


_BOUNCE_MARKER_PREFIX = "<!-- hos-bounce v=1 id="
_BOUNCE_COMMENTS_MAX_PAGES = 10


def _bounce_marker(cid: str, head_sha: str, new_keys: Sequence[str], bounce_number: int) -> str:
    """The hidden, deterministic line that identifies one bounce comment (#2263).

    One digest over (cid, head, bounce number, sorted keys) keeps caller-supplied text out of
    the comment, so no cid or key can close the HTML comment early.
    """
    material = "\0".join([cid, head_sha, str(bounce_number), *sorted(new_keys)])
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"{_BOUNCE_MARKER_PREFIX}{digest} -->"


def _find_posted_bounce(
    owner: str, repo: str, pr_number: int, marker: str, recorded_ids: Collection[str]
) -> Optional[dict[str, Any]]:
    """An orphan comment by the current bot carrying exactly `marker` (oldest first), else None.

    A comment whose id a recorded `pr-bounced` event already references is never
    an orphan: only a comment posted but not recorded may be adopted.

    Reads every comment page, bounded; a failed or truncated read raises
    GitHubError so the caller halts before posting on an unknown state. Without
    HOS_BOT_LOGIN nothing is read or adopted: any commenter can type the marker,
    and adopting theirs would suppress a real bounce.
    """
    login = os.environ.get("HOS_BOT_LOGIN")
    if not login:
        logger.warning(
            "record_pr_bounce: HOS_BOT_LOGIN unset; not looking for an already-posted "
            "bounce comment on PR #%s (a retry after an audit-write failure may re-post)",
            pr_number,
        )
        return None
    comments = _github.list_issue_comments(
        owner, repo, pr_number, max_pages=_BOUNCE_COMMENTS_MAX_PAGES
    )
    for comment in comments:
        if (
            isinstance(comment, dict)
            and str(comment.get("id")) not in recorded_ids
            and (comment.get("user") or {}).get("login") == login
            and marker in str(comment.get("body") or "").splitlines()
        ):
            return comment
    return None


def _bounce_comment_body(
    failures: list[str],
    reason_category: str,
    summary: str,
    bounce_number: int,
    *,
    head_sha: Optional[str] = None,
    marker: Optional[str] = None,
) -> str:
    """The legacy rendering (AD-4): the findings heading and section, no
    dispute text, for callers that still pass `failures=`."""
    head12 = (head_sha or "unknown")[:12]
    lines = [
        f"## PR bounced to the worker: {len(failures)} finding(s) on {head12}",
        "",
        "### Specific failures",
    ]
    for k, failure in enumerate(failures, 1):
        failure = _one_line(str(failure))
        if _LEGACY_ID_RE.match(failure):
            lines.append(f"- [{failure}] {_legacy_gloss(failure)}")
        else:
            lines.append(f"- [item-{k}] {failure}")
    lines += [
        "",
        f"**Reason category:** {reason_category}",
        f"**Summary:** {summary}",
        "",
        f"_Bounce #{bounce_number} for this correlation id "
        f"(cap: {BOUNCE_CAP} before human escalation)._",
    ]
    if marker:
        lines.append(marker)
    return "\n".join(lines) + "\n"


# GitHub rejects comments over 65,536 characters (422), which would stall a PR
# on a deterministic bounce_comment_failed every cycle. Stay well below it.
BOUNCE_BODY_MAX_CHARS = 60000
_TRUNCATED_DETAIL_CHARS = 200


def _neutralize(text: str) -> str:
    """Defang mentions and image/link markdown in LLM-supplied text (CWE-74/116)."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace("@", "@\u200b")
        .replace("![", "!\\[")
        .replace("](", "]\\(")
    )


def _bounce_comment_body_findings(
    findings_with_ids: Sequence[tuple[str, Finding]],
    reason_category: str,
    summary: str,
    bounce_number: int,
    *,
    cid: str,
    head_sha: str,
    marker: Optional[str] = None,
) -> str:
    """The findings rendering (AD-4): one `[id] (CLASS)` line per finding and
    the dispute instruction the worker re-entry text parses.

    The body is capped at BOUNCE_BODY_MAX_CHARS: per-finding detail is truncated
    first, then findings are listed by id and summary only, with an explicit
    truncation line. The audit event always keeps every finding.
    """
    total = len(findings_with_ids)

    def render(rows: list[str], note: Optional[str]) -> str:
        lines = [
            f"## PR bounced to the worker: {total} finding(s) on {head_sha[:12]}",
            "",
            "### Specific failures",
            *rows,
        ]
        if note:
            lines.append(note)
        lines += [
            "",
            "### How to respond",
            "Fix each finding, or dispute one: post a comment whose first line is "
            "`/hos dispute <finding-id>`, followed by your reason.",
            "",
            f"**Reason category:** {reason_category}",
            f"**Summary:** {summary}",
            "",
            f"_Bounce #{bounce_number} for {cid} (cap: {BOUNCE_CAP} before human escalation)._",
        ]
        if marker:
            lines.append(marker)
        return "\n".join(lines) + "\n"

    def row(finding_id: str, f: Finding, detail_chars: Optional[int]) -> str:
        text = f"- [{finding_id}] ({f.cls}) {_neutralize(_one_line(f.summary))}"
        if detail_chars != 0:
            detail = _neutralize(_one_line(f.detail))
            if detail_chars is not None and len(detail) > detail_chars:
                detail = detail[:detail_chars] + "..."
            if detail:
                text += f". {detail}"
            if f.source_url:
                text += f" ({f.source_url})"
        return text

    body = render([row(fid, f, None) for fid, f in findings_with_ids], None)
    if len(body) <= BOUNCE_BODY_MAX_CHARS:
        return body
    body = render([row(fid, f, _TRUNCATED_DETAIL_CHARS) for fid, f in findings_with_ids], None)
    if len(body) <= BOUNCE_BODY_MAX_CHARS:
        return body
    rows = [row(fid, f, 0) for fid, f in findings_with_ids]
    for kept in range(len(rows), -1, -1):
        dropped = len(rows) - kept
        note = f"- {dropped} findings truncated; see audit event" if dropped else None
        body = render(rows[:kept], note)
        if len(body) <= BOUNCE_BODY_MAX_CHARS:
            return body
    return body


def bounce_summary(count: int, head_sha: str) -> str:
    """Templated summary — never LLM text."""
    return f"{count} finding(s) on {head_sha[:12]} must be fixed or disputed before this PR can proceed."


def bounce_summary_for(findings: Sequence[Finding], head_sha: str) -> str:
    """Templated summary; REVIEW_CHAIN findings lead with the missing roles (#2346).

    The role names come from the closed REVIEW_CHAIN_ROLES slug set, so this is
    still never LLM text.
    """
    roles = sorted({f.key.split(":", 2)[2] for f in findings if f.cls == "REVIEW_CHAIN"})
    if not roles:
        return bounce_summary(len(findings), head_sha)
    return (
        f"{REVIEW_CHAIN_SUMMARY_PREFIX} {', '.join(roles)} "
        f"missing on {head_sha[:12]}; run the missing review(s) before this PR can proceed."
    )


def _convert_pr_to_draft(owner: str, repo: str, pr_number: int) -> None:
    """Convert an open PR to draft.

    No REST endpoint supports this (draft can only be set at PR creation via
    REST); the GraphQL `convertPullRequestToDraft` mutation is the only path,
    same as bootstrap/post_review_thread.sh's use of `gh api graphql` for the
    review-thread mutation it needs.
    """
    pr = _run_gh([f"/repos/{owner}/{repo}/pulls/{pr_number}"])
    node_id = pr.get("node_id") if pr else None
    if not node_id:
        raise GitHubError(f"could not resolve node_id for PR #{pr_number}")
    mutation = (
        "mutation($id:ID!){convertPullRequestToDraft(input:{pullRequestId:$id})"
        "{pullRequest{isDraft}}}"
    )
    result = _run_gh(["graphql", "-f", f"query={mutation}", "-f", f"id={node_id}"])
    is_draft = (
        (result or {})
        .get("data", {})
        .get("convertPullRequestToDraft", {})
        .get("pullRequest", {})
        .get("isDraft")
    )
    if is_draft is not True:
        raise GitHubError(
            f"convertPullRequestToDraft did not report isDraft=true for PR #{pr_number}"
        )


@dataclass
class BounceResult:
    comment_url: Optional[str]
    audit_relpath: str
    bounce_number: int
    finalize_errors: list[str] = field(default_factory=list)
    skipped: bool = False
    finding_ids: list[str] = field(default_factory=list)
    finalize_repaired: list[str] = field(default_factory=list)
    at_cap: bool = False
    finding_keys: list[str] = field(default_factory=list)
    adopted: bool = False


def _add_label(owner: str, repo: str, pr_number: int, label: str) -> None:
    _run_gh(
        [f"/repos/{owner}/{repo}/issues/{pr_number}/labels", "--method", "POST"],
        stdin_json={"labels": [label]},
    )


# Deliberate trade-off: a holder's worst-case GitHub retry budget (post_comment plus its
# read-back, 30 s per gh call with 3 retries) can exceed this. A waiter that times out
# fails transiently with nothing written and retries next cycle; dedup inside the lock
# then makes that retry safe. Waiting longer would only stall the cycle behind a slow holder.
BOUNCE_LOCK_TIMEOUT_SECONDS = 60.0
_BOUNCE_LOCK_POLL_SECONDS = 0.1


class BounceLockTimeout(RuntimeError):
    """The per-(repo, cid) bounce lock was not acquired in time. Raised before any write."""


# errnos that clear on their own (interrupts, contention, resource exhaustion). Any other
# errno, or none, is persistent: it fails closed toward escalation rather than retrying
# every cycle in silence (#2263).
_TRANSIENT_LOCK_ERRNOS = frozenset(
    getattr(errno, name)
    for name in ("EINTR", "EAGAIN", "EWOULDBLOCK", "ENOLCK", "EMFILE", "ENFILE", "ENOSPC", "EDQUOT")
    if hasattr(errno, name)
)


class BounceLockUnavailable(RuntimeError):
    """The bounce lock file could not be created or locked (OSError is `__cause__`).
    Raised before any write."""

    @property
    def errno(self) -> Optional[int]:
        cause = self.__cause__
        return cause.errno if isinstance(cause, OSError) else None

    @property
    def classification(self) -> str:
        """ "transient" only for a known self-clearing errno; otherwise "deterministic"."""
        return "transient" if self.errno in _TRANSIENT_LOCK_ERRNOS else "deterministic"


@contextlib.contextmanager
def _bounce_lock(
    owner: str,
    repo: str,
    cid: str,
    *,
    repo_root: str = ".",
    timeout: float = BOUNCE_LOCK_TIMEOUT_SECONDS,
):
    """Serialize the bounce critical section for one (repo, cid) under `repo_root` (#2227).

    A kernel flock, not a PID file: the kernel drops it when the holder dies, so
    a crash cannot leave a stale lock, and no PID liveness check is needed
    (those fail across sandbox PID namespaces, #1616). The file is never
    deleted: unlinking a flock file races with a waiter holding the old inode.
    """
    digest = hashlib.sha256(f"{owner}/{repo}\0{cid}".encode("utf-8")).hexdigest()[:24]
    lock_dir = Path(repo_root) / ".claudetmp" / "locks"
    lock_path = lock_dir / f"bounce-{digest}.lock"
    try:
        lock_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        raise BounceLockUnavailable(
            f"bounce lock {lock_path} unavailable (errno {exc.errno}): {exc.strerror}"
        ) from exc
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise BounceLockTimeout(
                        f"bounce lock for {cid} not acquired within {timeout:g}s"
                    ) from None
                time.sleep(_BOUNCE_LOCK_POLL_SECONDS)
            except OSError as exc:
                raise BounceLockUnavailable(
                    f"bounce lock {lock_path} unavailable (errno {exc.errno}): {exc.strerror}"
                ) from exc
        yield
    finally:
        os.close(fd)  # closing the fd releases the flock


class RepairReadError(GitHubError):
    """A server-side read made by repair_bounce_finalize failed or was truncated.
    The original error is `__cause__`. Raised before any write (TD-D9)."""


def _latest_bounce_time(cid: str, head_sha: str, repo_root: str) -> Optional[datetime]:
    """T (TD-D9): comment_created_at of the latest pr-bounced event for
    (cid, head_sha); a legacy event without it falls back to its timestamp."""
    times = [
        t
        for t in (
            _bounce_event_time(e)
            for e in bounce_events(cid, repo_root=repo_root)
            if e.get("head_sha") == head_sha
        )
        if t is not None
    ]
    return max(times) if times else None


def _deliberate_after(
    events: Sequence[dict], since: Optional[datetime], label: str
) -> tuple[bool, bool]:
    """(ready_for_review after `since`, `label` removed after `since`), by any actor.

    An event whose time cannot be parsed counts as after: it cannot be shown to
    precede the bounce, and undoing a human's act is worse than leaving a gap.
    """
    ready = unlabeled = False
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = event.get("event")
        is_ready = kind == "ready_for_review"
        is_unlabeled = kind == "unlabeled" and (event.get("label") or {}).get("name") == label
        if not (is_ready or is_unlabeled):
            continue
        when = _parse_iso(event.get("created_at"))
        if since is None or when is None or when > since:
            ready = ready or is_ready
            unlabeled = unlabeled or is_unlabeled
    return ready, unlabeled


def repair_bounce_finalize(
    owner: str,
    repo: str,
    pr_number: int,
    *,
    cid: str,
    head_sha: str,
    repo_root: str = ".",
    label: str = "needs-ai",
    errors: Optional[list[str]] = None,
) -> list[str]:
    """TD-D9: finish a label or draft step that failed after a bounce.

    Returns the repairs made ("label", "draft"). A failed or truncated PR or
    issue-events READ raises RepairReadError before any write. A label or draft
    WRITE failure is best-effort: it is appended to `errors` (when given).
    Runs under the bounce lock (#2227); BounceLockTimeout is raised before any write.
    """
    with _bounce_lock(owner, repo, cid, repo_root=repo_root):
        return _repair_bounce_finalize_unlocked(
            owner,
            repo,
            pr_number,
            cid=cid,
            head_sha=head_sha,
            repo_root=repo_root,
            label=label,
            errors=errors,
        )


def _repair_bounce_finalize_unlocked(
    owner: str,
    repo: str,
    pr_number: int,
    *,
    cid: str,
    head_sha: str,
    repo_root: str,
    label: str,
    errors: Optional[list[str]],
) -> list[str]:
    """repair_bounce_finalize's body; the caller must hold the bounce lock."""
    try:
        pr = _run_gh([f"/repos/{owner}/{repo}/pulls/{pr_number}"])
    except GitHubError as exc:
        raise RepairReadError(
            f"repair read of PR #{pr_number} failed: {exc}", exc.status_code
        ) from exc
    if not isinstance(pr, dict):
        raise RepairReadError(f"repair read of PR #{pr_number} found nothing", 404)
    is_draft = bool(pr.get("draft"))
    has_label = any(
        isinstance(item, dict) and item.get("name") == label for item in pr.get("labels") or []
    )
    if is_draft and has_label:
        return []

    # Any repair needs server-side evidence that the state is not deliberate.
    try:
        events = _github.list_issue_events(
            owner, repo, pr_number, max_pages=_ISSUE_EVENTS_MAX_PAGES
        )
    except GitHubError as exc:
        raise RepairReadError(
            f"repair read of events for PR #{pr_number} failed: {exc}", exc.status_code
        ) from exc
    ready, unlabeled = _deliberate_after(
        events, _latest_bounce_time(cid, head_sha, repo_root), label
    )
    if not is_draft and not has_label:
        # Both missing: either deliberate act suppresses both repairs.
        want_label = want_draft = not (ready or unlabeled)
    else:
        want_label = not has_label and not unlabeled
        want_draft = not is_draft and not ready

    repaired: list[str] = []
    sink = errors if errors is not None else []
    if want_label:
        try:
            _add_label(owner, repo, pr_number, label)
            repaired.append("label")
        except GitHubError as exc:
            sink.append(f"label failed: {exc}")
    if want_draft:
        try:
            _convert_pr_to_draft(owner, repo, pr_number)
            repaired.append("draft")
        except GitHubError as exc:
            sink.append(f"convert-to-draft failed: {exc}")
    return repaired


def record_pr_bounce(
    owner: str,
    repo: str,
    pr_number: int,
    *,
    cid: str,
    reason_category: str,
    summary: str,
    failures: Sequence[str] = (),
    label: str = "needs-ai",
    repo_root: str = ".",
    head_sha: Optional[str] = None,
    findings: Optional[Sequence[Finding]] = None,
    epoch_since: Optional[str] = None,
    cap: Optional[int] = _CAP_DEFAULT,
) -> BounceResult:
    """Bounce a PR back to the worker (SPEC-378 R3.3 halt-on-failure ordering).

    (1) validate, (2) resolve the head (TD-D5) before posting anything,
    (3) skip a repeat of keys already bounced on this head (TD-D9 repairs an
    unfinished finalize), (4) post the bounce comment, unless this bot's comment
    with the same hidden marker is already on the PR (an earlier attempt whose
    audit write failed, #2263): that one is adopted, and a failed or truncated
    comment read raises before posting, (5) confirmed via
    post_comment's read-back, (6) append the `pr-bounced` audit event,
    (7) finalize — label, convert to draft. Steps 2-6 raise on failure
    (GitHubError / audit-write error) and halt before any finalize action
    runs, per overseer.md's "Halt-on-failure ordering for non-merge
    dispositions" — a bounce must never be finalized without a confirmed
    comment and a committed audit entry. Finalize sub-steps (7) are
    independent and best-effort: a failure there is recorded in
    `finalize_errors` rather than rolled back, since the audit event (the
    durable record) has already been written.

    Steps 3-6 (read prior events, dedup, cap check, post, append) run under a
    per-(repo, cid) flock (#2227), so concurrent callers cannot double-post or
    burn two bounces for one rejection. The cap is enforced by default: omitting
    `cap` uses BOUNCE_CAP (read at call time), and a lock-time count at or above
    it posts and writes nothing and returns skipped=True, at_cap=True. Passing
    `cap=None` is the explicit, documented opt-out (no cap check). A non-int,
    bool or negative `cap` raises ValueError before any GitHub call or lock.
    BounceLockTimeout is raised before any write. The label/draft finalize steps
    run after the lock is released and are idempotent via repair.
    """
    if cap is _CAP_DEFAULT:
        cap = BOUNCE_CAP
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 0):
        raise ValueError(f"cap must be a non-negative int or None, got {cap!r}")
    if reason_category not in _BOUNCE_REASON_CATEGORIES:
        raise ValueError(
            f"reason_category must be one of {sorted(_BOUNCE_REASON_CATEGORIES)}, "
            f"got {reason_category!r}"
        )
    if findings is not None:
        if failures:
            raise ValueError("findings and failures are mutually exclusive")
        if head_sha is None:
            raise ValueError("findings requires head_sha")

    if head_sha is None:
        pr_obj = _run_gh([f"/repos/{owner}/{repo}/pulls/{pr_number}"])
        head_sha = (
            ((pr_obj or {}).get("head") or {}).get("sha") if isinstance(pr_obj, dict) else None
        )
        if not head_sha:
            raise GitHubError(f"could not resolve head.sha for PR #{pr_number}")

    with _bounce_lock(owner, repo, cid, repo_root=repo_root):
        prior = bounced_on_head(cid, head_sha, repo_root=repo_root)
        if findings is not None:
            prior_identities = {p.identity for p in prior}
            fresh = [f for f in findings if f.identity not in prior_identities]
            nothing_new = bool(findings) and not fresh
            new_keys = [f.key for f in fresh]
        else:
            fresh = []
            new_keys = [legacy_token_finding(str(t))[1] for t in failures]
            nothing_new = bool(new_keys) and set(new_keys) <= {p.key for p in prior}
        if nothing_new:
            repair_errors: list[str] = []
            repaired = _repair_bounce_finalize_unlocked(
                owner,
                repo,
                pr_number,
                cid=cid,
                head_sha=head_sha,
                repo_root=repo_root,
                label=label,
                errors=repair_errors,
            )
            return BounceResult(
                comment_url=None,
                audit_relpath="",
                bounce_number=bounce_count(cid, repo_root=repo_root, since=epoch_since),
                finalize_errors=repair_errors,
                skipped=True,
                finalize_repaired=repaired,
            )

        prior_count = bounce_count(cid, repo_root=repo_root, since=epoch_since)
        if cap is not None and prior_count >= cap:
            return BounceResult(
                comment_url=None,
                audit_relpath="",
                bounce_number=prior_count,
                skipped=True,
                at_cap=True,
            )
        bounce_number = prior_count + 1
        marker = _bounce_marker(cid, head_sha, new_keys, bounce_number)
        finding_ids: list[str] = []
        if findings is not None:
            start = next_finding_index(prior)
            finding_ids = [f"{head_sha[:12]}-F{start + k}" for k in range(len(fresh))]
            body = _bounce_comment_body_findings(
                list(zip(finding_ids, fresh)),
                reason_category,
                summary,
                bounce_number,
                cid=cid,
                head_sha=head_sha,
                marker=marker,
            )
        else:
            body = _bounce_comment_body(
                [str(t) for t in failures],
                reason_category,
                summary,
                bounce_number,
                head_sha=head_sha,
                marker=marker,
            )

        # A prior attempt may have posted and then failed its audit write. No event
        # exists, so prior_count is unchanged and that comment's bounce number equals
        # this one's: adopt it rather than post (and count) a second time.
        recorded_ids = {
            str(e.get("comment_id"))
            for e in bounce_events(cid, repo_root=repo_root)
            if e.get("comment_id") is not None
        }
        orphan = _find_posted_bounce(owner, repo, pr_number, marker, recorded_ids)
        adopted = orphan is not None
        if orphan is not None:
            comment = orphan
            logger.info(
                "record_pr_bounce: adopted already-posted bounce comment %s on PR #%s "
                "(an earlier attempt's audit write failed)",
                comment.get("id"),
                pr_number,
            )
        else:
            comment = post_comment(owner, repo, pr_number, body)  # raises GitHubError on failure

        event = {
            "event": "pr-bounced",
            "pr": pr_number,
            "cid": cid,
            "bounce_number": bounce_number,
            "failures": new_keys if findings is not None else list(failures),
            "assigned_to": None,
            "repo": f"{owner}/{repo}",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "reason_category": reason_category,
            "summary": summary,
            "comment_posted": True,
            "head_sha": head_sha,
            "comment_id": comment.get("id"),
            "comment_created_at": comment.get("created_at"),
            "actor": os.environ.get("HOS_BOT_LOGIN") or None,
        }
        if adopted:
            event["adopted"] = True
        if findings is not None:
            event["findings"] = [
                {"id": fid, "class": f.cls, "key": f.key, "origin": f.origin, "path": f.path}
                for fid, f in zip(finding_ids, fresh)
            ]
            event["epoch_start"] = epoch_since
        try:
            audit_relpath = _AUDIT_LOG.write_event(event, root=repo_root)
        except Exception as exc:  # the comment is already posted: say so explicitly
            raise BounceAuditWriteError(f"audit write failed after posting: {exc}") from exc

    finalize_errors: list[str] = []
    try:
        _add_label(owner, repo, pr_number, label)
    except GitHubError as exc:
        finalize_errors.append(f"label failed: {exc}")

    try:
        _convert_pr_to_draft(owner, repo, pr_number)
    except GitHubError as exc:
        finalize_errors.append(f"convert-to-draft failed: {exc}")

    if finalize_errors:
        logger.error(
            "record_pr_bounce: finalize step(s) failed for PR #%s: %s",
            pr_number,
            "; ".join(finalize_errors),
        )

    return BounceResult(
        comment_url=comment.get("html_url"),
        audit_relpath=audit_relpath,
        bounce_number=bounce_number,
        finalize_errors=finalize_errors,
        finding_ids=finding_ids,
        finding_keys=[f.key for f in fresh],
        adopted=adopted,
    )


# --- the routing decision ---------------------------------------------------


@dataclass(frozen=True)
class RouteInputs:
    """Everything route_pr decides from. There is deliberately no tier,
    surface, security or CODEOWNERS-ownership field (REQ-2, by construction)."""

    pr: int
    worker_authored: bool
    head_sha: str
    findings: tuple[Finding, ...]
    collectors_complete: bool
    hold_on_head: bool
    prior_on_head: tuple[PriorFinding, ...]
    epoch_bounce_count: int
    reviewer_act_on_head: Optional[ReviewerAct] = None
    escalation: Optional[EscalationRecord] = None
    escalation_act: Optional[ReviewerAct] = None
    blocks: tuple[Block, ...] = ()
    pending_rulings: tuple[str, ...] = ()
    upheld_unescalated: tuple[str, ...] = ()
    withdrawn_on_head: frozenset[str] = frozenset()
    veto: VetoState = VetoState.NOT_APPLICABLE


@dataclass(frozen=True)
class RouteResult:
    disposition: Disposition
    rule: str
    trigger: Optional[str] = None
    to_bounce: tuple[Finding, ...] = ()
    open_findings: tuple[Finding, ...] = ()
    overruled_keys: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


_START_VETO = "start-veto-window"
_REPAIR_FINALIZE = "repair-finalize"


def route_pr(inputs: RouteInputs) -> RouteResult:
    """Pure precedence list (TD §3.8): first match wins. No I/O, no clock."""
    i = inputs
    withdrawn_keys = {p.key for p in i.prior_on_head if p.finding_id in i.withdrawn_on_head}
    code_open = tuple(f for f in i.findings if f.origin == "code")
    rejections = tuple(f for f in i.findings if not f.is_decision and f.key not in withdrawn_keys)
    decisions = tuple(f for f in i.findings if f.is_decision)
    # A PR's own pending escalation is handled by rule 2; blocking on it would
    # deadlock the approval that resolves it (AR1-C2). PATH_HOLD and
    # UNKNOWN_SCOPE are never filtered by source.
    pending_blocks = tuple(
        b for b in i.blocks if b.kind == "PATH_PENDING_ESCALATION" and b.source_pr != i.pr
    )
    veto_action = (_START_VETO,) if i.veto is VetoState.NEEDS_START else ()

    def result(
        disposition: Disposition,
        rule: str,
        reason: Optional[str] = None,
        *,
        trigger: Optional[str] = None,
        to_bounce: tuple[Finding, ...] = (),
        overruled: tuple[str, ...] = (),
        actions: tuple[str, ...] = (),
    ) -> RouteResult:
        return RouteResult(
            disposition=disposition,
            rule=rule,
            trigger=trigger,
            to_bounce=to_bounce,
            open_findings=rejections,
            overruled_keys=overruled,
            actions=actions,
            reasons=(reason,) if reason else (),
        )

    # Rule 1 — ESC-3 (A): non-worker PRs stay on the legacy path.
    if not i.worker_authored:
        return result(Disposition.LEGACY, "1", "non-worker-pr")
    if any(b.kind in ("PATH_HOLD", "UNKNOWN_SCOPE") for b in i.blocks):
        return result(Disposition.LEGACY, "1", "path-hold")
    if i.hold_on_head:
        return result(Disposition.LEGACY, "1", "hold-902")

    # Rule 2 — an escalated head waits on the resolved reviewer's act.
    esc = i.escalation
    if esc is not None:
        act = i.escalation_act
        trig = esc.trigger
        if act is None:
            return result(
                Disposition.HOLD, "2a", "awaiting-reviewer", trigger=trig, actions=veto_action
            )
        if act.kind == "DISMISSED":
            return result(
                Disposition.HOLD, "2b", "approval-revoked", trigger=trig, actions=veto_action
            )
        if act.kind in ("CHANGES_REQUESTED", "NEEDS_AI_LABEL"):
            return result(Disposition.HUMAN_SENDBACK, "2c", trigger=trig, actions=veto_action)
        if code_open:
            return result(
                Disposition.HOLD, "2d", "code-findings-open", trigger=trig, actions=veto_action
            )
        if not i.collectors_complete:
            return result(
                Disposition.HOLD, "2e", "collectors-incomplete", trigger=trig, actions=veto_action
            )
        if trig == "decision" and act.option_label not in esc.option_labels:
            return result(
                Disposition.HOLD, "2f", "decision-option-missing", trigger=trig, actions=veto_action
            )
        if i.pending_rulings:
            return result(Disposition.RULING_REQUIRED, "2k", trigger=trig, actions=veto_action)
        if i.upheld_unescalated:
            return result(Disposition.ESCALATE, "2l", trigger="upheld-dispute", actions=veto_action)
        if i.veto is VetoState.NEEDS_START:
            return result(Disposition.HOLD_VETO, "2g", trigger=trig, actions=veto_action)
        if i.veto is VetoState.OPEN:
            return result(Disposition.HOLD_VETO, "2h", trigger=trig)
        if pending_blocks:
            return result(Disposition.HOLD, "2i", "path-pending-escalation", trigger=trig)
        return result(
            Disposition.PROCEED,
            "2j",
            trigger=trig,
            overruled=tuple(f.key for f in i.findings if f.origin == "llm"),
        )

    # Rule 3
    if i.pending_rulings:
        return result(Disposition.RULING_REQUIRED, "3")

    # Rule 4 — an unstarted veto window is started, then treated as open.
    actions: tuple[str, ...] = ()
    veto = i.veto
    if veto is VetoState.NEEDS_START:
        actions = (_START_VETO,)
        veto = VetoState.OPEN

    # Rule 5
    if i.upheld_unescalated:
        return result(Disposition.ESCALATE, "5", trigger="upheld-dispute", actions=actions)

    # Rule 6
    if rejections:
        if i.reviewer_act_on_head is not None and i.reviewer_act_on_head.kind == "APPROVED":
            # ESC-2 (C): an approval on this head plus a rejection is a conflict.
            return result(Disposition.ESCALATE, "6a", trigger="reviewer-conflict", actions=actions)
        if any(f.conflicts_with is not None for f in rejections):
            return result(Disposition.ESCALATE, "6b", trigger="reviewer-conflict", actions=actions)
        prior_identities = {p.identity for p in i.prior_on_head}
        if all(f.identity in prior_identities for f in rejections):
            return result(
                Disposition.NOOP, "6c", "no-new-keys", actions=(*actions, _REPAIR_FINALIZE)
            )
        if i.epoch_bounce_count >= BOUNCE_CAP:
            return result(Disposition.ESCALATE, "6d", trigger="bounce-cap", actions=actions)
        return result(
            Disposition.BOUNCE,
            "6e",
            to_bounce=tuple(f for f in rejections if f.identity not in prior_identities),
            actions=actions,
        )

    # Rule 7
    if decisions:
        return result(Disposition.ESCALATE, "7", trigger="decision", actions=actions)

    # Rule 8
    if veto is VetoState.OPEN:
        return result(Disposition.HOLD_VETO, "8", actions=actions)
    if pending_blocks:
        return result(Disposition.HOLD, "8", "path-pending-escalation", actions=actions)
    if not i.collectors_complete:
        return result(Disposition.HOLD, "8", "collectors-incomplete", actions=actions)
    return result(Disposition.PROCEED, "8", actions=actions)


# --- the reviewer's act -----------------------------------------------------


def _is_bot_reviewer(login: str, user_type: str, bot_accounts: Collection[str]) -> bool:
    path = Path(__file__).resolve().parents[2] / "framework" / "require_human_approval.py"
    spec = importlib.util.spec_from_file_location("hos_require_human_approval", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.is_bot_reviewer(login, user_type, set(bot_accounts))


_REVIEW_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "DISMISSED"})


def latest_reviewer_act(
    reviews: Sequence[dict],
    label_events: Sequence[dict],
    reviewer: str,
    head_sha: str,
    since: Optional[str],
    *,
    bot_accounts: Collection[str],
) -> Optional[ReviewerAct]:
    """The resolved reviewer's latest act on `head_sha`, after `since` (AD-5a)."""
    since_dt = _parse_iso(since) if since is not None else None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    reviewer_l = reviewer.lower()
    candidates: list[tuple[datetime, int, ReviewerAct]] = []

    for review in reviews:
        user = review.get("user") or {}
        login = str(user.get("login", ""))
        if login.lower() != reviewer_l or _is_bot_reviewer(
            login, str(user.get("type", "")), bot_accounts
        ):
            continue
        state = str(review.get("state", "")).upper()
        if review.get("commit_id") != head_sha or state not in _REVIEW_STATES:
            continue
        when = _parse_iso(review.get("submitted_at"))
        if since is not None and (when is None or since_dt is None or when <= since_dt):
            continue
        option = None
        if state == "APPROVED":
            match = _OPTION_LINE_RE.search(review.get("body") or "")
            option = match.group("l") if match else None
        rid = review.get("id")
        rid = rid if isinstance(rid, int) else 0
        candidates.append(
            (
                when or epoch,
                rid,
                ReviewerAct(state, rid, str(review.get("submitted_at") or ""), option),
            )
        )

    if since is not None:
        for event in label_events:
            if (
                event.get("event") != "labeled"
                or (event.get("label") or {}).get("name") != "needs-ai"
            ):
                continue
            actor = event.get("actor") or {}
            login = str(actor.get("login", ""))
            if login.lower() != reviewer_l or _is_bot_reviewer(
                login, str(actor.get("type", "")), bot_accounts
            ):
                continue
            when = _parse_iso(event.get("created_at"))
            if when is None or since_dt is None or when <= since_dt:
                continue
            eid = event.get("id")
            eid = eid if isinstance(eid, int) else 0
            candidates.append(
                (when, eid, ReviewerAct("NEEDS_AI_LABEL", eid, str(event.get("created_at")), None))
            )

    if not candidates:
        return None
    return max(candidates, key=lambda c: (c[0], c[1]))[2]


# --- CODEOWNERS at the base ref, and the #902 head time ---------------------

_codeowners_module = None


def _codeowners():
    """scripts/oversight/codeowners.py, loaded by path and cached (it is not an
    importable package — same idiom as merge_authority_cli._load_codeowners_module)."""
    global _codeowners_module
    if _codeowners_module is None:
        path = Path(__file__).resolve().parents[2] / "oversight" / "codeowners.py"
        spec = importlib.util.spec_from_file_location("hos_oversight_codeowners", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _codeowners_module = mod
    return _codeowners_module


def fetch_codeowners_text(owner: str, repo: str, ref: str) -> Optional[str]:
    """CODEOWNERS text at `ref` (the PR's BASE sha), or None when absent.

    Tries the same three locations, in the same order, as
    codeowners.load_codeowners. A payload that exists but cannot be decoded
    raises CodeownersUnreadableError; a GitHubError propagates.
    """
    for relpath in _codeowners().CODEOWNERS_LOCATIONS:
        payload = get_contents(owner, repo, relpath, ref=ref)
        if payload is None:
            continue
        content = payload.get("content") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("encoding") != "base64" or not content:
            raise CodeownersUnreadableError(
                f"CODEOWNERS at {relpath}@{ref[:12]} has no usable content"
            )
        try:
            return base64.b64decode(content).decode("utf-8")
        except ValueError as exc:  # UnicodeDecodeError is a ValueError
            raise CodeownersUnreadableError(
                f"CODEOWNERS at {relpath}@{ref[:12]} could not be decoded"
            ) from exc
    return None


def _codeowners_humans_from_text(text: Optional[str]) -> set[str]:
    """Byte-equivalent to requester_trust.codeowners_humans over `text`."""
    humans: set[str] = set()
    if text is None:
        return humans
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        for owner in line.split()[1:]:
            owner = owner.lstrip("@")
            if "/" in owner:
                continue
            humans.add(owner.lower())
    return humans


def resolve_reviewer_from_text(
    text: Optional[str],
    changed_files: Sequence[str],
    *,
    bot_accounts: Collection[str],
    human_reviewer: str,
) -> ReviewerResolution:
    """codeowners.resolve_human_reviewer's algorithm, on already-fetched text."""
    if text is None:
        return ReviewerResolution(human_reviewer, "machine-accounts.env", (), "no CODEOWNERS file")
    co = _codeowners()
    entries = co.parse_codeowners(text)
    accumulated: list[str] = []
    seen: set[str] = set()
    for f in sorted(changed_files):
        for owner in sorted(co.get_owners_for_path(entries, f)):
            if owner not in seen:
                seen.add(owner)
                accumulated.append(owner)
    bots = set(bot_accounts)
    teams: list[str] = []
    emails: list[str] = []
    bot_owners: list[str] = []
    users: list[str] = []
    for owner in accumulated:
        if co._is_team(owner):
            teams.append(owner)
        elif co._owner_is_email(owner):
            emails.append(owner)
        elif co._owner_is_bot(owner, bots):
            bot_owners.append(owner)
        else:
            users.append(owner)
    if users:
        login = users[0]
        return ReviewerResolution(
            login[1:] if login.startswith("@") else login, "codeowners", tuple(teams), None
        )
    if teams:
        note = f"CODEOWNERS owner is a team ({teams[0]}); team review requests are not made"
    elif bot_owners and not emails:
        note = "bot-only CODEOWNERS entry"
    elif emails:
        note = "CODEOWNERS owners are e-mail addresses; not requestable"
    else:
        note = "no CODEOWNERS entry matched the changed files"
    return ReviewerResolution(human_reviewer, "machine-accounts.env", tuple(teams), note)


def check_resolution_consistent(resolution: ReviewerResolution, text: Optional[str]) -> None:
    """Drift guard (TD-D3): a codeowners-sourced login must be in the humans set."""
    if (
        resolution.source == "codeowners"
        and resolution.login.lower() not in _codeowners_humans_from_text(text)
    ):
        raise CodeownersDriftError(
            f"resolved reviewer {resolution.login!r} is not in the CODEOWNERS humans set"
        )


def effective_head_time(
    committer_date: Optional[str], check_suites: Sequence[dict], *, head_sha: str
) -> Optional[str]:
    """The head's time, bounded by a server-set fact (TD-D6, F8).

    The committer date is pusher-controlled, so it is capped at the earliest
    `created_at` of a `github-actions` check suite on this head. A committer
    date is never trusted alone: with no such suite the result is None, so
    every matching hold directive counts (the library's fail-safe).
    """
    bounds: list[tuple[datetime, str]] = []
    for suite in check_suites:
        if (
            isinstance(suite, dict)
            and (suite.get("app") or {}).get("slug") == "github-actions"
            and suite.get("head_sha") == head_sha
        ):
            when = _parse_iso(suite.get("created_at"))
            if when is not None:
                bounds.append((when, suite["created_at"]))
    if not bounds:
        return None
    bound = min(bounds, key=lambda b: b[0])
    committed = _parse_iso(committer_date)
    if committed is not None and committed < bound[0]:
        return committer_date
    return bound[1]


# --- the code collectors ----------------------------------------------------


def _code_finding(cls: str, check_id: str, summary: str) -> Finding:
    key = f"{cls}:{check_id}"
    return Finding(
        cls=cls, key=key, identity=(cls, key), origin="code", path=None, summary=summary, detail=""
    )


def collect_code_findings(
    owner: str,
    repo: str,
    *,
    step: Union[str, int],
    head_sha: str,
    pr: dict,
    changed_paths: Sequence[str],
    repo_root: str,
    default_branch: str,
) -> tuple[tuple[Finding, ...], dict]:
    """Deterministic findings the CLI collects itself (AD-5): register,
    required checks and size. The validator artifact collector is S1b."""
    findings: list[Finding] = []

    register = check_register_completeness(step, repo_root=repo_root)
    for failure in register.failures:
        findings.append(_code_finding("PROCEDURAL", failure, f"{_legacy_gloss(failure)}."))

    required = check_required_content_checks(owner, repo, head_sha, default_branch=default_branch)
    for failure in required.failures:
        findings.append(_code_finding("REQUIRED_CHECK", failure, f"{_legacy_gloss(failure)}."))
    degraded = not required.bounce_required and (required.summary or "").startswith(
        "required-checks gate skipped"
    )

    file_count = len(changed_paths)
    commits = pr.get("commits")
    if file_count > SIZE_HARD_FILES:
        findings.append(
            _code_finding(
                "SCOPE",
                "size-hard-ceiling",
                f"Changed files {file_count} exceed the {SIZE_HARD_FILES}-file hard ceiling; split the PR.",
            )
        )
    elif file_count > SIZE_SOFT_FILES:
        findings.append(
            _code_finding(
                "SCOPE",
                "size-soft-files",
                f"Changed files {file_count} exceed the {SIZE_SOFT_FILES}-file limit; split the PR.",
            )
        )
    if isinstance(commits, int) and commits > SIZE_SOFT_COMMITS:
        findings.append(
            _code_finding(
                "SCOPE",
                "size-soft-commits",
                f"Commits {commits} exceed the {SIZE_SOFT_COMMITS}-commit limit; split the PR.",
            )
        )

    evidence = {
        "register": {
            "bounce_required": register.bounce_required,
            "failures": list(register.failures),
        },
        "required_checks": {
            "bounce_required": required.bounce_required,
            "failures": list(required.failures),
            "degraded": degraded,
        },
        "size": {"changed_files": file_count, "commits": commits},
        "required_checks_degraded": degraded,
    }
    return tuple(findings), evidence
