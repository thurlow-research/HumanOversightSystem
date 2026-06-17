"""
triage.py — Issue-triage helpers for the HOS autonomous worker.

triage() classifies an incoming GitHub issue (title + body) into a risk tier
and recommended action.  Because issue text originates from external requesters,
the body is treated as **untrusted framing** by default — it is used as a
classification signal, but any language that tries to steer the triage outcome
(e.g. "mark this as LOW risk", "this is safe", "auto-approve") is detected and
surfaced to the caller so a human can decide.

Trust boundary (P9, Mitropoulos et al. 2026):
  issue_body_trusted=False (the default) means the body is untrusted framing.
  The classification still uses the body text for signal extraction (keywords
  that indicate risk level, affected components, etc.), but:
    - TriageResult.reason always notes "body treated as untrusted framing".
    - If the body contains framing-steering patterns, TriageResult.reason
      includes a FRAMING_DETECTED marker so the caller can gate on it.

  Pass issue_body_trusted=True only when the body comes from a verified internal
  author (e.g. a human team member filing a known-safe doc-only fix).

Stdlib only — no third-party imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ── Framing-steering detection ────────────────────────────────────────────────
# Patterns that attempt to steer the triage outcome rather than describe the
# issue.  These are matched case-insensitively against the issue body.

_FRAMING_STEERING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bmark\s+(?:this|it)\s+as\s+(?:low|medium|safe|approved?)\b", re.IGNORECASE),
    re.compile(r"\bthis\s+is\s+safe\b", re.IGNORECASE),
    re.compile(r"\bauto.?approve\b", re.IGNORECASE),
    re.compile(r"\bno\s+review\s+(?:needed|required)\b", re.IGNORECASE),
    re.compile(r"\bskip\s+review\b", re.IGNORECASE),
    re.compile(r"\blow\s+risk\b.*\bapprove\b", re.IGNORECASE),
    re.compile(r"\bapprove\b.*\blow\s+risk\b", re.IGNORECASE),
    re.compile(r"\bsafe\s+to\s+(?:merge|approve|deploy)\b", re.IGNORECASE),
]

# ── Risk-classification keyword sets ─────────────────────────────────────────
# Scored heuristically: HIGH keywords raise the tier, LOW keywords lower it.
# The caller (the agent) owns final classification; this is a signal, not a
# decision.

_HIGH_RISK_KEYWORDS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:auth(?:entication|orization)?|login|logout|session|token|credential|password|secret|key|permission|privilege|escalat)\b", re.IGNORECASE),
    re.compile(r"\b(?:inject|xss|csrf|sqli|sql\s+injection|exploit|vulnerability|cve-\d+|rce|lfi|ssrf)\b", re.IGNORECASE),
    re.compile(r"\b(?:pii|personal\s+data|gdpr|erasure|encryption|decrypt|private)\b", re.IGNORECASE),
    re.compile(r"\b(?:migration|schema|database|db|data\s+loss|destructive)\b", re.IGNORECASE),
    re.compile(r"\b(?:payment|billing|stripe|financial|money|invoice)\b", re.IGNORECASE),
]

_LOW_RISK_KEYWORDS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:typo|spelling|doc(?:ument(?:ation)?)?|readme|comment|whitespace)\b", re.IGNORECASE),
    re.compile(r"\b(?:css|style|colour|color|font|layout|margin|padding|icon|logo)\b", re.IGNORECASE),
]


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class TriageResult:
    """
    Result of a triage() call.

    Attributes:
        risk_tier:        Suggested risk tier: "LOW", "MEDIUM", "HIGH", or "CRITICAL".
        action:           Recommended action: "AUTO_PROCESS", "HUMAN_REVIEW", or "ESCALATE".
        reason:           Human-readable explanation of the classification, always including
                          the body-trust note when issue_body_trusted=False.
        framing_detected: True when the issue body contained framing-steering language that
                          attempts to influence the triage outcome.  The caller MUST NOT
                          auto-approve when this is True.
        high_risk_signals: List of matched high-risk keyword patterns (for traceability).
    """
    risk_tier: str
    action: str
    reason: str
    framing_detected: bool = False
    high_risk_signals: list[str] = field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────

def triage(
    title: str,
    body: str,
    *,
    issue_body_trusted: bool = False,
) -> TriageResult:
    """
    Classify an incoming GitHub issue and return a TriageResult.

    Args:
        title:              The issue title (treated as trusted — short, structured text
                            filed under the contributor's GitHub identity).
        body:               The issue body.  When issue_body_trusted=False (the default),
                            the body is used only as a classification signal; its framing
                            claims are not taken at face value and are checked for
                            steering patterns.
        issue_body_trusted: Pass True only when the body comes from a verified internal
                            author filing a known-safe change (e.g. a team member's
                            doc-only fix).  False is the safe default for all
                            autonomously-triaged issues from external requesters.

    Returns:
        TriageResult with the suggested risk tier, recommended action, and a
        reason string that always records the body-trust posture.

    Trust boundary note (P9):
        When issue_body_trusted=False the returned reason always contains
        "body treated as untrusted framing".  If framing-steering language is
        detected the reason also contains "FRAMING_DETECTED" and
        TriageResult.framing_detected is True.  The caller must gate on
        framing_detected before taking any automated action.
    """
    combined_text = f"{title}\n{body}"
    body_text = body or ""

    # ── Step 1: Framing-steering detection (body only) ────────────────────────
    framing_detected = False
    framing_notes: list[str] = []
    if not issue_body_trusted:
        for pat in _FRAMING_STEERING_PATTERNS:
            m = pat.search(body_text)
            if m:
                framing_detected = True
                framing_notes.append(m.group(0))

    # ── Step 2: Risk-keyword scoring ─────────────────────────────────────────
    high_signals: list[str] = []
    for pat in _HIGH_RISK_KEYWORDS:
        m = pat.search(combined_text)
        if m:
            high_signals.append(m.group(0))

    low_signals: list[str] = []
    for pat in _LOW_RISK_KEYWORDS:
        m = pat.search(combined_text)
        if m:
            low_signals.append(m.group(0))

    # ── Step 3: Tier assignment ───────────────────────────────────────────────
    # Heuristic: high-risk signals dominate; low-risk signals only apply when
    # there are no high-risk signals.
    if framing_detected:
        # Framing-steering is itself a risk signal — floor at MEDIUM so it
        # always reaches a human.
        risk_tier = "MEDIUM"
        action = "HUMAN_REVIEW"
    elif high_signals:
        # Two or more distinct high-risk keyword matches → HIGH.
        risk_tier = "HIGH" if len(high_signals) >= 2 else "MEDIUM"
        action = "HUMAN_REVIEW"
    elif low_signals and not high_signals:
        risk_tier = "LOW"
        action = "AUTO_PROCESS"
    else:
        # No clear signal → MEDIUM (conservative default).
        risk_tier = "MEDIUM"
        action = "HUMAN_REVIEW"

    # ── Step 4: Reason assembly ───────────────────────────────────────────────
    reason_parts: list[str] = []

    if not issue_body_trusted:
        reason_parts.append("body treated as untrusted framing")

    if framing_detected:
        snippet = "; ".join(repr(f) for f in framing_notes[:3])
        reason_parts.append(f"FRAMING_DETECTED: body contains steering language ({snippet})")

    if high_signals:
        reason_parts.append(f"high-risk signals: {', '.join(high_signals[:5])}")

    if low_signals and not high_signals and not framing_detected:
        reason_parts.append(f"low-risk signals only: {', '.join(low_signals[:3])}")

    if not reason_parts:
        reason_parts.append("no strong risk signal; defaulting to MEDIUM")

    reason = "; ".join(reason_parts) + f" → {risk_tier}/{action}"

    return TriageResult(
        risk_tier=risk_tier,
        action=action,
        reason=reason,
        framing_detected=framing_detected,
        high_risk_signals=high_signals,
    )
