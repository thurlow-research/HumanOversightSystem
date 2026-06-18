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


# ---------------------------------------------------------------------------
# Framing-guard (AC-381 / #391 / #466)
#
# Detects adversarial PR-description framing — language that attempts to steer
# reviewer or AI risk assessment by misrepresenting the change's risk tier,
# soliciting approval, bypassing review, or inflating confidence.
#
# Algorithm (SPEC-381 §3):
#   confidence = len(matched_shipped_classes) / total_classes
#   is_adversarial = confidence > threshold   (default 0.7)
#   total_classes = 4 shipped + unique caller-supplied class names
#
# Patterns are pre-compiled at import time. Caller may EXTEND the pattern list
# via context["framing_patterns"] / context["framing_pattern_classes"] but
# may NOT remove or replace shipped patterns.
# ---------------------------------------------------------------------------

# v1 shipped pattern list — 4 classes, pre-compiled at import time.
# Each entry: (class_name, compiled_pattern)
_FRAMING_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Class 1: risk-tier steering — characterises the change's risk as low
    ("risk-tier steering", re.compile(
        r"\b(low[- ]risk|this\s+is\s+safe|this\s+change\s+is\s+safe|change\s+is\s+safe"
        r"|safe\s+change|it\s+is\s+safe|mark\s+.{0,20}(?:low[- ]risk|safe)"
        r"|trivial\s+change|harmless\s+change)\b",
        re.IGNORECASE,
    )),
    # Class 2: approval solicitation — explicitly requests or asserts approval
    ("approval solicitation", re.compile(
        r"\b(auto[- ]?approve|please\s+approve|approve\s+this|mark\s+.{0,30}approved"
        r"|it\s+is\s+approved|this\s+is\s+approved|change\s+is\s+approved"
        r"|safe\s+to\s+(?:merge|deploy|land|ship)|lgtm\b|ship\s+it)\b",
        re.IGNORECASE,
    )),
    # Class 3: review-bypass — attempts to skip review steps
    ("review-bypass", re.compile(
        r"\b(no\s+review\s+(?:needed|required|necessary)|skip\s+(?:the\s+)?review"
        r"|bypass\s+review|review\s+not\s+needed|no\s+(?:security\s+)?review\s+(?:needed|required"
        r"|necessary)|no\s+need\s+to\s+review|does\s+not\s+need\s+(?:a\s+)?review)\b",
        re.IGNORECASE,
    )),
    # Class 4: confidence inflation — inflates reviewer/AI confidence in the change
    ("confidence inflation", re.compile(
        r"\b(obviously\s+(?:safe|correct|fine|harmless)|trivially\s+correct"
        r"|clearly\s+(?:safe|correct|fine|harmless|obvious)"
        r"|no\s+possible\s+(?:issue|security\s+issue|risk|problem)"
        r"|cannot\s+(?:possibly\s+)?(?:break|fail|cause)\b"
        r"|100\s*%\s+safe|guaranteed\s+safe)\b",
        re.IGNORECASE,
    )),
]

# Names of the four shipped classes (used to compute the denominator)
_SHIPPED_CLASS_NAMES: tuple[str, ...] = tuple(cls for cls, _ in _FRAMING_PATTERNS)

# Default confidence threshold — above this, the description is adversarial
_FRAMING_DEFAULT_THRESHOLD: float = 0.7


@dataclass
class FramingVerdict:
    """Result of classify_framing()."""
    is_adversarial: bool
    confidence: float
    redacted_description: Optional[str]
    reason: str


def classify_framing(
    pr_description: Optional[str],
    context: dict,
) -> FramingVerdict:
    """
    Classify a PR description for adversarial framing.

    Args:
        pr_description: The PR description text to analyse (str or None).
        context: Optional overrides:
            "confidence_threshold" (float, default 0.7): above this → adversarial.
            "framing_patterns" (list[str]): additional regex strings (compiled
                at call time, skipped if malformed — shipped defaults always run).
            "framing_pattern_classes" (list[str]): class names for each additional
                pattern (parallel list; defaults to "caller-supplied" if shorter).

    Returns:
        FramingVerdict with all four fields populated. Never raises.
    """
    # Resolve threshold — fall back to default on any non-numeric value
    raw_threshold = context.get("confidence_threshold", _FRAMING_DEFAULT_THRESHOLD)
    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError):
        threshold = _FRAMING_DEFAULT_THRESHOLD

    # Guard empty / None input
    if not pr_description:
        return FramingVerdict(
            is_adversarial=False,
            confidence=0.0,
            redacted_description=None,
            reason="no description",
        )

    text: str = pr_description

    # --- Build the active pattern set ---
    # Start with shipped defaults (immutable; caller cannot remove them)
    active_patterns: list[tuple[str, re.Pattern[str]]] = list(_FRAMING_PATTERNS)

    caller_patterns: list[str] = context.get("framing_patterns", []) or []
    caller_classes: list[str] = context.get("framing_pattern_classes", []) or []

    for idx, raw_pat in enumerate(caller_patterns):
        try:
            compiled = re.compile(raw_pat, re.IGNORECASE)
        except re.error:
            # Malformed caller regex — skip it; shipped defaults are unaffected
            continue
        cls_name = (
            caller_classes[idx]
            if idx < len(caller_classes)
            else "caller-supplied"
        )
        active_patterns.append((cls_name, compiled))

    # --- Score: count distinct classes that have at least one match ---
    matched_classes: set[str] = set()
    matched_spans: list[tuple[int, int]] = []  # for redaction

    for cls_name, pattern in active_patterns:
        for m in pattern.finditer(text):
            matched_classes.add(cls_name)
            matched_spans.append((m.start(), m.end()))

    # Confidence = matched shipped classes / total unique class count
    # (caller-supplied classes expand the denominator)
    all_class_names: set[str] = {cls for cls, _ in active_patterns}
    total_classes = max(len(all_class_names), 1)
    matched_shipped = matched_classes & set(_SHIPPED_CLASS_NAMES)
    # Count caller classes separately so that the shipped fraction is exact
    # but caller classes that match also contribute to confidence
    matched_count = len(matched_shipped) + len(matched_classes - set(_SHIPPED_CLASS_NAMES))
    confidence = matched_count / total_classes

    is_adversarial = confidence > threshold

    # --- Reason ---
    if not matched_classes:
        reason = (
            f"No framing patterns matched. confidence={confidence:.3f}"
        )
    else:
        sorted_classes = sorted(matched_classes)
        reason = (
            f"Matched classes: {', '.join(sorted_classes)}. "
            f"confidence={confidence:.3f}"
        )

    # --- Redaction (only when adversarial) ---
    redacted_description: Optional[str] = None
    if is_adversarial and matched_spans:
        # Merge overlapping/adjacent spans, then replace right-to-left to
        # preserve character offsets
        merged: list[tuple[int, int]] = []
        for start, end in sorted(matched_spans):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        result = list(text)
        for start, end in reversed(merged):
            result[start:end] = list("[FRAMING REDACTED]")
        redacted_description = "".join(result)

    return FramingVerdict(
        is_adversarial=is_adversarial,
        confidence=confidence,
        redacted_description=redacted_description,
        reason=reason,
    )
