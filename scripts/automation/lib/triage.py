"""
Issue triage for the HOS automation loop (T6, §5).

Classifies inbound items into: bug | feature | communication | security-report |
spec-gap | duplicate | invalid.

Design rules:
  - Low-confidence triage → escalate to human (never act on uncertain classification)
  - Security reports → immediate embargo path, never public auto-fix (§5.2)
  - Features → queued for human review, never auto-built (NG3)
  - Bugs and communications → handled autonomously (within gates)
  - Requester allowlist is enforced by envelope.py (GitHub-author check); triage
    does NOT re-check it — it trusts the caller has already verified the actor
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class TriageClass(Enum):
    BUG = "bug"
    FEATURE = "feature"
    COMMUNICATION = "communication"
    SECURITY_REPORT = "security-report"
    SPEC_GAP = "spec-gap"
    DUPLICATE = "duplicate"
    INVALID = "invalid"


# Autonomous classes (may proceed through the build chain)
AUTONOMOUS_CLASSES = frozenset({TriageClass.BUG, TriageClass.COMMUNICATION, TriageClass.SPEC_GAP})

# Human-only classes — always route to human regardless of confidence
HUMAN_ONLY_CLASSES = frozenset({TriageClass.FEATURE, TriageClass.SECURITY_REPORT})

# Security keywords that trigger the embargo path (asymmetric: err toward security)
_SECURITY_PATTERNS = [
    re.compile(r"\b(vuln|exploit|CVE[-\s]\d{4}|RCE|XSS|SQLi|SSRF|CSRF|auth.bypass|"
               r"secret.leak|credential|token.exfil|privilege.escal|security.fix)\b",
               re.IGNORECASE),
    re.compile(r"\bsecurity\b.*\b(bug|issue|flaw|hole|problem|risk|concern)\b", re.IGNORECASE),
    re.compile(r"\bembargo\b", re.IGNORECASE),
]

# Feature request keywords
_FEATURE_PATTERNS = [
    re.compile(r"\b(feature.request|enhancement|FR:|new.feature|add.support.for|"
               r"would.be.nice|could.we.have|please.add)\b", re.IGNORECASE),
]

# Bug patterns
_BUG_PATTERNS = [
    re.compile(r"\b(bug|error|exception|traceback|crash|broken|regression|"
               r"not.working|fails|fails.to|unexpected.behavior|wrong.output)\b",
               re.IGNORECASE),
]

# Communication patterns (questions, reports, coordination)
_COMM_PATTERNS = [
    re.compile(r"\b(question|question:|how.do|can.you|please.explain|"
               r"status.update|coordination|follow.up|report|observation)\b",
               re.IGNORECASE),
]

# Default confidence floor — below this, escalate to human (R13 triage-confidence-floor)
DEFAULT_CONFIDENCE_FLOOR = 0.75


@dataclass
class TriageResult:
    triage_class: TriageClass
    confidence: float
    reason: str
    autonomous: bool
    embargo: bool = False  # True → immediate embargo path

    @property
    def should_escalate(self) -> bool:
        return not self.autonomous or self.triage_class in HUMAN_ONLY_CLASSES


# ---------------------------------------------------------------------------
# Severity mapping (§5.3)
# ---------------------------------------------------------------------------

class Severity(Enum):
    P0 = 0  # Critical — immediate, above all other work
    P1 = 1  # High
    P2 = 2  # Medium
    P3 = 3  # Low (default)


_SEVERITY_KEYWORDS = {
    Severity.P0: re.compile(r"\b(P0|critical|outage|data.loss|production.down)\b", re.IGNORECASE),
    Severity.P1: re.compile(r"\b(P1|high.priority|urgent|blocker)\b", re.IGNORECASE),
    Severity.P2: re.compile(r"\b(P2|medium|moderate)\b", re.IGNORECASE),
}


def infer_severity(title: str, body: str) -> Severity:
    text = f"{title} {body}"
    for sev in (Severity.P0, Severity.P1, Severity.P2):
        if _SEVERITY_KEYWORDS[sev].search(text):
            return sev
    return Severity.P3


# ---------------------------------------------------------------------------
# Triage engine
# ---------------------------------------------------------------------------

def _score_patterns(text: str, patterns: list[re.Pattern]) -> float:
    """Score a text against a pattern list. Returns 0.0–1.0."""
    matches = sum(1 for p in patterns if p.search(text))
    return min(1.0, matches / max(len(patterns), 1))


def triage(
    title: str,
    body: str,
    labels: list[str] = (),
    existing_issues: int = 0,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
) -> TriageResult:
    """
    Classify an issue/item into a triage class.

    Security is asymmetric: a single security-pattern match triggers
    the embargo path regardless of other signals (§5.2).

    Low confidence (<= confidence_floor) → escalate to human.
    """
    text = f"{title} {body}"

    # Security check — asymmetric (one match is enough)
    if any(p.search(text) for p in _SECURITY_PATTERNS):
        return TriageResult(
            triage_class=TriageClass.SECURITY_REPORT,
            confidence=0.9,
            reason="Security-pattern match → embargo path",
            autonomous=False,
            embargo=True,
        )

    # Label-based fast-path
    label_set = {lbl.lower() for lbl in labels}
    if "bug" in label_set:
        return TriageResult(
            triage_class=TriageClass.BUG,
            confidence=0.95,
            reason="Explicit 'bug' label",
            autonomous=True,
        )
    if "enhancement" in label_set or "feature" in label_set:
        return TriageResult(
            triage_class=TriageClass.FEATURE,
            confidence=0.95,
            reason="Explicit 'enhancement'/'feature' label",
            autonomous=False,
        )
    if "duplicate" in label_set:
        return TriageResult(
            triage_class=TriageClass.DUPLICATE,
            confidence=0.95,
            reason="Explicit 'duplicate' label",
            autonomous=False,
        )
    if "invalid" in label_set or "wontfix" in label_set:
        return TriageResult(
            triage_class=TriageClass.INVALID,
            confidence=0.95,
            reason="Explicit 'invalid'/'wontfix' label",
            autonomous=False,
        )

    # Score each class from content
    scores = {
        TriageClass.FEATURE: _score_patterns(text, _FEATURE_PATTERNS),
        TriageClass.BUG: _score_patterns(text, _BUG_PATTERNS),
        TriageClass.COMMUNICATION: _score_patterns(text, _COMM_PATTERNS),
    }

    best_class = max(scores, key=lambda c: scores[c])
    best_score = scores[best_class]

    # If top two classes are close, confidence is lower
    sorted_scores = sorted(scores.values(), reverse=True)
    margin = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]
    confidence = min(0.95, best_score * (0.5 + 0.5 * margin))

    if best_score == 0.0:
        # Nothing matched — treat as communication with low confidence
        best_class = TriageClass.COMMUNICATION
        confidence = 0.4

    autonomous = (
        best_class in AUTONOMOUS_CLASSES
        and confidence >= confidence_floor
    )

    reason = (
        f"Content signals: {best_class.value} (score={best_score:.2f}, "
        f"confidence={confidence:.2f})"
    )

    if confidence < confidence_floor:
        reason += f" — below floor {confidence_floor:.2f}, escalating to human"

    return TriageResult(
        triage_class=best_class,
        confidence=confidence,
        reason=reason,
        autonomous=autonomous,
    )


# ---------------------------------------------------------------------------
# Benefit ≫ risk gate (§5.3)
# ---------------------------------------------------------------------------

def benefit_exceeds_risk(
    triage_result: TriageResult,
    security_sensitive: bool = False,
    tier_estimate: str = "LOW",
) -> bool:
    """
    Quick gate: is the expected benefit clearly > the risk for autonomous action?

    Returns False (escalate) when:
      - Class is FEATURE or SECURITY_REPORT
      - Triage confidence is below floor
      - Change touches a security-sensitive path and tier is not LOW
    """
    if triage_result.triage_class in HUMAN_ONLY_CLASSES:
        return False
    if not triage_result.autonomous:
        return False
    if security_sensitive and tier_estimate not in ("LOW", "SAFE"):
        return False
    return True
