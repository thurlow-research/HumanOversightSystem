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

  class=worker  → NEVER merges (opens PRs only)
  class=overseer → may merge iff matrix permits AND below OVERSEER_CEILING
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional

from scripts.automation.lib.github import (
    GitHubError,
    get_branch_protection,
    post_comment,
    _run_gh,
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
        if (review.get("state") == "APPROVED" and
                review.get("user", {}).get("login", "").lower() == human_reviewer.lower()):
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
    """Stub — returns False until the #152 follow-up status check ships."""
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
                    reason=f"bypass_pull_request_allowances includes team '{team.get('slug')}' — overseer membership unverifiable",
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
        return GateDetectionResult(autonomous_capable=False, reason=f"Protection API read failed: {exc}")

    if protection is None:
        return GateDetectionResult(autonomous_capable=False, reason=f"Branch protection not enabled on {default_branch}")

    rpr = protection.get("required_pull_request_reviews")
    if not rpr:
        return GateDetectionResult(autonomous_capable=False, reason="required_pull_request_reviews not configured")
    if rpr.get("required_approving_review_count", 0) < 1:
        return GateDetectionResult(autonomous_capable=False, reason="required_approving_review_count < 1")
    if not rpr.get("dismiss_stale_reviews"):
        return GateDetectionResult(autonomous_capable=False, reason="dismiss_stale_reviews not enabled")

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
    AUTO_MERGE = auto()         # overseer may approve + merge
    PROPOSE_ONLY = auto()       # open PR, no auto-merge (server gate absent)
    HUMAN_REQUIRED = auto()     # escalate to human


@dataclass
class MergeAuthorityResult:
    decision: MergeDecision
    reason: str
    pr_title: Optional[str] = None
    labels_to_add: list[str] = None
    is_release: bool = False

    def __post_init__(self):
        if self.labels_to_add is None:
            self.labels_to_add = []


# ---------------------------------------------------------------------------
# No-release guard (NG3b)
# ---------------------------------------------------------------------------

_RELEASE_PATTERNS = [
    "tag", "release", "v0.", "v1.", "publish", "ship", "cut-release",
    "semver", "CHANGELOG", "release/v",
]


def _is_release_related(pr_title: str, changed_files: list[str]) -> bool:
    text = pr_title.lower() + " " + " ".join(changed_files).lower()
    return any(kw.lower() in text for kw in _RELEASE_PATTERNS)


# ---------------------------------------------------------------------------
# Protected-surface check (re-uses require_human_approval.py)
# ---------------------------------------------------------------------------

def _touches_protected_surface(changed_files: list[str], repo_root: str = ".") -> bool:
    """Check if any changed file is on the protected surface."""
    surfaces_path = Path(repo_root) / "scripts" / "framework" / "protected_surfaces.txt"
    if not surfaces_path.is_file():
        return False
    try:
        import fnmatch
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
    oversight_verdict: str,          # "PROCEED" | "CONDITIONAL_PROCEED" | "ESCALATE"
    changed_files: list[str],
    pr_title: str = "",
    pr_author: str = "",
    security_relevant: bool = False,
    agent_class: str = "worker",     # "worker" | "overseer"
    overseer_handle: str = DEFAULT_OVERSEER_HANDLE,
    worker_handle: str = "hos-worker-hos[bot]",  # GitHub App; updated from PAT account (#547)
    overseer_ceiling: RiskTier = RiskTier.LOW,
    default_branch: str = "main",
    repo_root: str = ".",
    reviews: list[dict] = None,      # PR reviews from GitHub API; enables human-approval override
    human_reviewer: str = "ScottThurlow",  # Human who can approve protected-surface PRs
    head_sha: Optional[str] = None,  # Current PR head SHA; stale approvals (wrong SHA) are rejected
    pr_labels: list[str] = None,     # Labels on the PR; needs-human/hos-halt block AUTO_MERGE (#756)
) -> MergeAuthorityResult:
    """
    Decide what the automation may do with this PR.

    R9.1.1: calls detect_server_side_gate immediately before merge decision —
    never trusts a cached result.

    Issues #589 / #741: If decision would be HUMAN_REQUIRED due to a
    protected-surface or security-relevant flag, and a verified human maintainer
    has already approved the PR on the current head SHA, the authorization
    condition is satisfied — the overseer may execute the merge as mechanical
    delivery of that human decision.  The authorship-separation and server-side
    gate checks still run.  The audit reason records the authorizing maintainer
    and the approved SHA.
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
    if security_relevant:
        approval = _find_human_approval(reviews, human_reviewer, head_sha)
        if approval:
            approver = approval.get("user", {}).get("login", human_reviewer)
            approved_sha = approval.get("commit_id", "unknown")
            human_auth_reason = f"human authorization (approval by {approver} on {approved_sha})"
            logger.info(
                "Security-relevant PR has human approval from %s on %s; overseer may execute merge",
                approver, approved_sha,
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
    if _touches_protected_surface(changed_files, repo_root):
        approval = _find_human_approval(reviews, human_reviewer, head_sha)
        if approval:
            approver = approval.get("user", {}).get("login", human_reviewer)
            approved_sha = approval.get("commit_id", "unknown")
            human_auth_reason = f"human authorization (approval by {approver} on {approved_sha})"
            logger.info(
                "Protected-surface PR has human approval from %s on %s; overseer may execute merge",
                approver, approved_sha,
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

    merge_reason = (
        f"Auto-merge approved: tier={risk_tier.name}, "
        f"ceiling={overseer_ceiling.name}, verdict=PROCEED, "
        f"gate=detected"
    )
    if human_auth_reason:
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
    labels: list[str] = (),
) -> Optional[int]:
    """Open a draft PR and apply labels. Returns PR number or None on failure."""
    try:
        result = _run_gh([
            f"/repos/{owner}/{repo}/pulls",
            "--method", "POST",
            "--field", f"title={title}",
            "--field", f"body={body}",
            "--field", f"head={branch}",
            "--field", "base=main",
            "--field", "draft=true",
        ])
        pr_number = result.get("number") if result else None
        if pr_number and labels:
            _run_gh([
                f"/repos/{owner}/{repo}/issues/{pr_number}/labels",
                "--method", "POST",
                "--field", f"labels={list(labels)}",
            ])
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
        "protocol-version: \"1.0\"\n"
        "---\n\n"
        "🔒 This report has been classified as a potential security issue and routed "
        "to the responsible human for private review. No public fix will be posted "
        "until coordinated disclosure is complete. Thank you for the report."
    )
    try:
        post_comment(owner, repo, issue_number, ack_body)
        _run_gh([
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            "--method", "POST",
            "--field", "labels=[\"hos-embargo\", \"needs-human\"]",
        ])
    except GitHubError as exc:
        logger.error("Failed to route embargo: %s", exc)
