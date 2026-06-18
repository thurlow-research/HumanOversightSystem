# Structured Fault Explanation Drives Developer Action (vs. Bare Flags)

**Source:** Adejumo, E.K. & Johnson, B. (2025). *Explaining Code Risk in OSS: Towards LLM-Generated Fault Prediction Interpretations.* ASEW 2025. arXiv:2510.06104  
**Zotero key:** QLMUYYQ3  
**Session:** 2026-06-18 (v0.5.0 triage from issue #431)

## Core finding

68% of fault prediction tools provide raw metric values with no explanation. Developers consistently fail to act on bare flags. LLMs can generate three types of explanation that drive action:

| Type | Purpose | Example |
|------|---------|---------|
| **Descriptive** | What does this finding mean? | "C03: this `except` block absorbs all exceptions and returns success regardless of whether the operation succeeded." |
| **Contextual** | Why does it matter *here*? | "This is in `create_reservation()` — a swallowed failure means a double-booking with no error surfaced." |
| **Actionable** | What should the reviewer do? | "Either re-raise after logging, or return a typed error result. Do not return `{'status': 'ok'}` from inside `except`." |

## Calibrated thresholds finding

Identical metric values have different implications depending on codebase size, architecture, and conventions. Generic thresholds produce both false positives (flagging architectural norms) and false negatives (missing genuine outliers that look normal globally).

Risk thresholds should be computed relative to the project's own statistical distribution (mean + σ per metric) rather than fixed absolute values.

## Implications for HOS

1. **Agent PR comments must include all three explanation layers** — descriptive, contextual, actionable. A bare "C03 detected in reservations.py:47" is insufficient and will be ignored.
2. **Risk thresholds need project baseline calibration** — as CPS accumulates scan history, compute rolling baselines per module and route to human review when a PR exceeds 1.5σ above the project's own baseline for that check.

## Related HOS findings
- `aira-deterministic-scanner-for-ai-code-failures.md`
- `reviewer-output-contract.md`
