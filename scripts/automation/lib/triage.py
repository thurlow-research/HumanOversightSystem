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

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


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


# ===========================================================================
# Framing-guard subsection (SPEC-381 / #391 — merged into §13 by architect ruling)
#
# Detects adversarial framing in PR descriptions before they reach reviewers.
# classify_framing(pr_description, context) -> FramingVerdict
# ===========================================================================
# ---------------------------------------------------------------------------
# FramingVerdict — return type for classify_framing()
# ---------------------------------------------------------------------------

@dataclass
class FramingVerdict:
    """Result of framing-guard analysis on a PR description.

    Fields
    ------
    is_adversarial:
        True when ``confidence`` exceeds the active threshold (default 0.7).
    confidence:
        Proportion of shipped pattern classes that had at least one match.
        Range 0.0–1.0.
    redacted_description:
        The PR description with matched framing spans replaced by
        ``[FRAMING REDACTED]``.  Set only when ``is_adversarial`` is True;
        None otherwise.
    reason:
        Human-readable explanation: matched classes, example snippets (up to
        3 per class), confidence score, and whether the threshold was crossed.
    """

    is_adversarial: bool
    confidence: float
    redacted_description: str | None
    reason: str


# ---------------------------------------------------------------------------
# Shipped v1 pattern list — authoritative baseline (SPEC-381 §3 C2 / §13)
#
# Each entry: (class_name, compiled_pattern).
# The class_name groups patterns for confidence scoring and reporting.
# Case-insensitive flag is set at compile time.
# ---------------------------------------------------------------------------

_SHIPPED_PATTERNS: list[tuple[str, str]] = [
    # Class 1 — risk-tier steering
    ("risk-tier steering", r"\bmark\s+(?:this|it)\s+as\s+(?:low|medium|safe|approv(?:ed|al)?)\b"),
    ("risk-tier steering", r"\bthis\s+is\s+(?:a\s+)?(?:safe|low[\s\-]risk)\b"),
    ("risk-tier steering", r"\blow[\s\-]risk\s+change\b"),
    ("risk-tier steering", r"\bthis\s+(?:change\s+)?is\s+(?:safe|approved?)\b"),
    # Class 2 — approval solicitation
    ("approval solicitation", r"\bauto[\s\-]?approve\b"),
    ("approval solicitation", r"\bsafe\s+to\s+(?:merge|approve|deploy)\b"),
    ("approval solicitation", r"\bapprove\s+this\b"),
    ("approval solicitation", r"\bplease\s+(?:auto[\s\-]?)?approve\b"),
    # Class 3 — review-bypass
    ("review-bypass", r"\bno\s+review\s+(?:needed|required)\b"),
    ("review-bypass", r"\bskip\s+(?:the\s+)?review\b"),
    ("review-bypass", r"\bno\s+security\s+review\b"),
    ("review-bypass", r"\breview\s+(?:is\s+)?(?:not\s+)?(?:necessary|needed|required)\b"),
    # Class 4 — confidence inflation
    ("confidence inflation", r"\bobviously\s+safe\b"),
    ("confidence inflation", r"\btrivially\s+correct\b"),
    ("confidence inflation", r"\bno\s+possible\s+(?:security\s+)?issue\b"),
    ("confidence inflation", r"\bclearly\s+(?:safe|harmless|benign)\b"),
]

# Deduplicated class names in insertion order — total shipped class count.
_SHIPPED_CLASS_NAMES: list[str] = list(dict.fromkeys(c for c, _ in _SHIPPED_PATTERNS))
_SHIPPED_CLASS_COUNT: int = len(_SHIPPED_CLASS_NAMES)  # 4

_DEFAULT_CONFIDENCE_THRESHOLD: float = 0.7


def _compile_patterns(
    raw_patterns: list[tuple[str, str]],
) -> list[tuple[str, re.Pattern[str]]]:
    """Compile (class_name, regex_str) pairs; skip and log any that fail."""
    compiled = []
    for class_name, pattern_str in raw_patterns:
        try:
            compiled.append((class_name, re.compile(pattern_str, re.IGNORECASE)))
        except re.error as exc:
            logger.error(
                "classify_framing: failed to compile pattern %r (%s) — skipping",
                pattern_str,
                exc,
            )
    return compiled


# Pre-compile shipped defaults once at import time.
_COMPILED_SHIPPED: list[tuple[str, re.Pattern[str]]] = _compile_patterns(_SHIPPED_PATTERNS)


def classify_framing(
    pr_description: str,
    context: dict,
) -> FramingVerdict:
    """Classify a PR description for adversarial framing (SPEC-381 C4).

    Parameters
    ----------
    pr_description:
        The raw PR description string (untrusted).  Empty string or None is
        handled gracefully — returns a benign verdict.
    context:
        Optional per-call overrides:

        ``context["confidence_threshold"]`` (float, default 0.7):
            Threshold above which ``is_adversarial`` is set True.

        ``context["framing_patterns"]`` (list[str]):
            Caller-supplied additional regex strings.  The shipped default
            pattern list is always included and cannot be removed (narrow-only,
            SPEC-381 §3 C2 / R13.1).

    Returns
    -------
    FramingVerdict
        Populated verdict; never raises.
    """
    # --- Graceful empty / None handling ---
    if not pr_description:
        return FramingVerdict(
            is_adversarial=False,
            confidence=0.0,
            redacted_description=None,
            reason="no description",
        )

    # --- Configuration ---
    threshold: float
    try:
        threshold = float(context.get("confidence_threshold", _DEFAULT_CONFIDENCE_THRESHOLD))
    except (TypeError, ValueError):
        logger.warning(
            "classify_framing: invalid confidence_threshold in context; using default %.1f",
            _DEFAULT_CONFIDENCE_THRESHOLD,
        )
        threshold = _DEFAULT_CONFIDENCE_THRESHOLD

    # --- Build the full compiled pattern list ---
    # Shipped defaults always come first and cannot be removed.
    all_compiled = list(_COMPILED_SHIPPED)

    caller_raw: list[str] = context.get("framing_patterns", []) or []
    caller_class_names: list[str] = context.get("framing_pattern_classes", []) or []

    extra_patterns: list[tuple[str, str]] = []
    for i, pat_str in enumerate(caller_raw):
        # Assign the caller-supplied class name if provided; default to the
        # nearest shipped class or a synthetic "caller-supplied" class.
        class_name = (
            caller_class_names[i]
            if i < len(caller_class_names)
            else "caller-supplied"
        )
        extra_patterns.append((class_name, pat_str))

    all_compiled.extend(_compile_patterns(extra_patterns))

    # --- Collect all class names (shipped + caller) in order ---
    all_class_names: list[str] = list(
        dict.fromkeys(c for c, _ in all_compiled)
    )
    total_classes = len(all_class_names)

    # --- Pattern matching ---
    # For each class: record whether at least one match occurred, and collect
    # up to 3 example matched strings for the reason message.
    class_matched: dict[str, bool] = {name: False for name in all_class_names}
    class_examples: dict[str, list[str]] = {name: [] for name in all_class_names}
    # Span tracking for redaction: list of (start, end) pairs.
    matched_spans: list[tuple[int, int]] = []

    for class_name, compiled_pat in all_compiled:
        for m in compiled_pat.finditer(pr_description):
            class_matched[class_name] = True
            if len(class_examples[class_name]) < 3:
                class_examples[class_name].append(m.group(0))
            matched_spans.append((m.start(), m.end()))

    # --- Confidence scoring ---
    matched_class_count = sum(1 for v in class_matched.values() if v)
    confidence = matched_class_count / total_classes if total_classes > 0 else 0.0

    # --- Adversarial determination ---
    is_adversarial = confidence > threshold

    # --- Redaction (only when adversarial) ---
    redacted_description: str | None = None
    if is_adversarial and matched_spans:
        redacted_description = _apply_redaction(pr_description, matched_spans)
    elif is_adversarial:
        # Edge: adversarial flag set but no spans recorded (shouldn't happen,
        # but be defensive — return description unchanged rather than None).
        redacted_description = pr_description

    # --- Reason assembly ---
    reason = _build_reason(
        class_matched=class_matched,
        class_examples=class_examples,
        confidence=confidence,
        threshold=threshold,
        is_adversarial=is_adversarial,
    )

    return FramingVerdict(
        is_adversarial=is_adversarial,
        confidence=confidence,
        redacted_description=redacted_description,
        reason=reason,
    )


def _apply_redaction(text: str, spans: list[tuple[int, int]]) -> str:
    """Replace matched spans in ``text`` with ``[FRAMING REDACTED]``.

    Spans may overlap; they are merged before redaction so that a single
    overlapping match region becomes one ``[FRAMING REDACTED]`` token rather
    than a doubled replacement.
    """
    # Merge overlapping / adjacent spans.
    merged = _merge_spans(spans)

    parts: list[str] = []
    prev_end = 0
    for start, end in merged:
        parts.append(text[prev_end:start])
        parts.append("[FRAMING REDACTED]")
        prev_end = end
    parts.append(text[prev_end:])
    return "".join(parts)


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Return a sorted, non-overlapping list of (start, end) tuples."""
    if not spans:
        return []
    sorted_spans = sorted(spans)
    merged: list[tuple[int, int]] = [sorted_spans[0]]
    for start, end in sorted_spans[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _build_reason(
    *,
    class_matched: dict[str, bool],
    class_examples: dict[str, list[str]],
    confidence: float,
    threshold: float,
    is_adversarial: bool,
) -> str:
    """Assemble a human-readable reason string."""
    matched_classes = [name for name, matched in class_matched.items() if matched]

    if not matched_classes:
        return f"no framing patterns detected (confidence=0.0, threshold={threshold:.2f})"

    parts: list[str] = []
    for class_name in matched_classes:
        examples = class_examples[class_name]
        example_str = "; ".join(f'"{e}"' for e in examples)
        parts.append(f"{class_name}: [{example_str}]")

    verdict_str = "ADVERSARIAL" if is_adversarial else "PARTIAL (below threshold)"
    return (
        f"{verdict_str} — confidence={confidence:.2f} (threshold={threshold:.2f}); "
        f"matched classes: {'; '.join(parts)}"
    )
