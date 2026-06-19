"""
Issue triage for the HOS automation loop (T6, §5).

Classifies inbound items into: bug | feature | communication | security-report |
spec-gap | duplicate | invalid | needs-human.

Design rules:
  - Low-confidence triage → escalate to human (never act on uncertain classification)
  - Security reports → immediate embargo path, never public auto-fix (§5.2)
  - Features → queued for human review, never auto-built (NG3)
  - Bugs and communications → handled autonomously (within gates)
  - Requester allowlist is enforced by envelope.py (GitHub-author check); triage
    does NOT re-check it — it trusts the caller has already verified the actor

Caller responsibility — repo-scope guard:
  triage() does not have access to the issue's origin repo.  Callers MUST verify
  that the issue belongs to the current session's repo before acting on
  ``autonomous=True``.  The worker scope guard in worker.md owns this check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TriageClass(Enum):
    BUG = "bug"
    FEATURE = "feature"
    COMMUNICATION = "communication"
    SECURITY_REPORT = "security-report"
    SPEC_GAP = "spec-gap"
    DUPLICATE = "duplicate"
    INVALID = "invalid"
    NEEDS_HUMAN = "needs-human"


# Autonomous classes (may proceed through the build chain)
AUTONOMOUS_CLASSES = frozenset({TriageClass.BUG, TriageClass.COMMUNICATION, TriageClass.SPEC_GAP})

# Human-only classes — always route to human regardless of confidence
HUMAN_ONLY_CLASSES = frozenset({
    TriageClass.FEATURE,
    TriageClass.SECURITY_REPORT,
    TriageClass.NEEDS_HUMAN,
})

# ---------------------------------------------------------------------------
# Security patterns — asymmetric: a single match triggers embargo path (§5.2).
#
# Fix 2 (#311): patterns require real security vocabulary.  Vague terms like
# "threshold", "confidence", "calibrate", "protocol", and "commits" must NOT
# trigger the security path on their own.  Each pattern either:
#   (a) directly names a well-known vulnerability class / CVE notation, OR
#   (b) pairs "security" with a concrete harm word (bug/flaw/hole/exploit).
# ---------------------------------------------------------------------------
_SECURITY_PATTERNS = [
    # Specific vulnerability classes and well-known attack names
    re.compile(
        r"\b(vuln(?:erability)?|exploit|CVE[-\s]\d{4}[-\s]\d+|RCE|XSS|SQLi|SQL\s+injection|"
        r"SSRF|CSRF|LFI|auth[\s\-]?bypass|secret[\s\-]leak|credential[\s\-]theft|"
        r"token[\s\-]exfil(?:tration)?|privilege[\s\-]escal(?:ation)?|"
        r"injection|backdoor|malware|ransomware)\b",
        re.IGNORECASE,
    ),
    # "security" paired with a concrete harm word — requires BOTH to be present
    re.compile(
        r"\bsecurity\b.{0,60}\b(bug|flaw|hole|exploit|vulnerability|breach|bypass|"
        r"misconfiguration|weakness)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"\bembargo\b", re.IGNORECASE),
]

# Feature request keywords
_FEATURE_PATTERNS = [
    re.compile(
        r"\b(feature[\s\-]request|enhancement|FR:|new[\s\-]feature|add[\s\-]support[\s\-]for|"
        r"would[\s\-]be[\s\-]nice|could[\s\-]we[\s\-]have|please[\s\-]add)\b",
        re.IGNORECASE,
    ),
]

# Bug patterns
_BUG_PATTERNS = [
    re.compile(
        r"\b(bug|error|exception|traceback|crash|broken|regression|"
        r"not[\s\-]working|fails|fails[\s\-]to|unexpected[\s\-]behavior|wrong[\s\-]output)\b",
        re.IGNORECASE,
    ),
]

# Communication patterns (questions, reports, coordination)
_COMM_PATTERNS = [
    re.compile(
        r"\b(question|question:|how[\s\-]do|can[\s\-]you|please[\s\-]explain|"
        r"status[\s\-]update|coordination|follow[\s\-]up|report|observation)\b",
        re.IGNORECASE,
    ),
]

# Spec-gap patterns — behavior gaps, missing specs, design deviations
_SPEC_GAP_PATTERNS = [
    re.compile(
        r"\b(spec[\s\-]gap|behavior[\s\-]gap|missing[\s\-]spec|design[\s\-]deviation|"
        r"undocumented|not[\s\-]specified|should[\s\-](?:be|do)|"
        r"expected[\s\-]behavior|actual[\s\-]behavior)\b",
        re.IGNORECASE,
    ),
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
    Severity.P0: re.compile(r"\b(P0|critical|outage|data[\s\-]loss|production[\s\-]down)\b", re.IGNORECASE),
    Severity.P1: re.compile(r"\b(P1|high[\s\-]priority|urgent|blocker)\b", re.IGNORECASE),
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

    Caller responsibility — repo-scope guard:
        triage() does not have access to the issue's origin repo.  Callers MUST
        verify that the issue belongs to the current session's repo before acting
        on ``autonomous=True``.  The worker scope guard in worker.md owns this
        check.  An ``autonomous=True`` result for an out-of-scope issue MUST be
        treated as ``autonomous=False`` by the caller.

    Args:
        title:            Issue title.
        body:             Issue body.
        labels:           List of label strings attached to the issue.
        existing_issues:  Count of potential duplicates (reserved for future use).
        confidence_floor: Minimum confidence for autonomous=True.
    """
    text = f"{title} {body}"

    # ── Fix 1 (#311): needs-human label is authoritative — check before everything ──
    # The label is set by a human reviewer explicitly requesting human attention.
    # Skip all pattern matching; return NEEDS_HUMAN immediately.
    label_set = {lbl.lower() for lbl in labels}
    if "needs-human" in label_set:
        return TriageResult(
            triage_class=TriageClass.NEEDS_HUMAN,
            confidence=1.0,
            reason="Explicit 'needs-human' label — human review required",
            autonomous=False,
        )

    # ── Fix 3 (#311): field-report label — classify as spec-gap or communication ──
    # field-report issues describe observed behaviors; they must not fall through
    # to the security path via keyword coincidence (e.g. "commits", "protocol").
    if "field-report" in label_set:
        # If the body describes a behavior gap → spec-gap; otherwise communication.
        if _score_patterns(text, _SPEC_GAP_PATTERNS) > 0:
            return TriageResult(
                triage_class=TriageClass.SPEC_GAP,
                confidence=0.85,
                reason="Explicit 'field-report' label with behavior-gap signals → spec-gap",
                autonomous=True,
            )
        return TriageResult(
            triage_class=TriageClass.COMMUNICATION,
            confidence=0.85,
            reason="Explicit 'field-report' label (no behavior-gap signals) → communication",
            autonomous=True,
        )

    # ── Security check — asymmetric (one match is enough) ────────────────────
    # Fix 2 (#311): patterns now require real security vocabulary.  See
    # _SECURITY_PATTERNS definition for the narrowing rationale.
    if any(p.search(text) for p in _SECURITY_PATTERNS):
        return TriageResult(
            triage_class=TriageClass.SECURITY_REPORT,
            confidence=0.9,
            reason="Security-pattern match → embargo path",
            autonomous=False,
            embargo=True,
        )

    # ── Label-based fast-path (remaining labels) ──────────────────────────────
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
    if "spec-gap" in label_set:
        return TriageResult(
            triage_class=TriageClass.SPEC_GAP,
            confidence=0.95,
            reason="Explicit 'spec-gap' label",
            autonomous=True,
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

    # ── Content scoring ───────────────────────────────────────────────────────
    scores = {
        TriageClass.FEATURE: _score_patterns(text, _FEATURE_PATTERNS),
        TriageClass.BUG: _score_patterns(text, _BUG_PATTERNS),
        TriageClass.COMMUNICATION: _score_patterns(text, _COMM_PATTERNS),
        TriageClass.SPEC_GAP: _score_patterns(text, _SPEC_GAP_PATTERNS),
    }

    best_class = max(scores, key=lambda c: scores[c])
    best_score = scores[best_class]

    # Margin between top-two scores lowers confidence when classes are ambiguous.
    sorted_scores = sorted(scores.values(), reverse=True)
    margin = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]
    confidence = min(0.95, best_score * (0.5 + 0.5 * margin))

    if best_score == 0.0:
        # Nothing matched — treat as communication with low confidence.
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
      - Class is FEATURE, SECURITY_REPORT, or NEEDS_HUMAN
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
