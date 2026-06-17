"""triage.py — Work-item triage helpers for the HOS autonomous worker (§13).

Provides the framing-guard function ``classify_framing()`` (SPEC-381 / #391) and its
companion ``FramingVerdict`` return type.  All code is stdlib-only — no third-party
imports, per the §13 constraint.

Framing-guard background (P9, Mitropoulos et al. 2026)
-------------------------------------------------------
PR descriptions and issue bodies authored by external contributors can contain
adversarial framing — natural-language instructions that attempt to steer a downstream
AI reviewer toward a more permissive verdict.  ``classify_framing()`` detects and
redacts those spans before they reach reviewer prompts, complementing the prompt-layer
guard carried in every reviewer agent's CORE block.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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
