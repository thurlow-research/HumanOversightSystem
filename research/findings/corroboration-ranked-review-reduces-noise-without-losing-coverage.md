# Finding: Corroboration-ranked review raises precision and cuts volume without suppressing findings

**Role:** oversight-mechanism — signal-to-noise ratio in the review layer; reviewer fatigue as an oversight failure mode

**Source:** Charoenwet et al. 2026 (AgenticSCR, FSE 2026, arXiv:2601.19138) — SLR P4

---

## The finding

AgenticSCR's detector-then-validator architecture raised review precision while cutting comment volume by 81%, by filtering findings with low grounding. The mechanism is not suppression — all findings are retained in the record — but the human reviewer sees the corroborated findings first. The key signal driving that ordering is cross-vendor agreement: findings that multiple independent reviewers flag are far more likely to be real.

Charoenwet et al. establish two complementary results that must be read together:

1. **Volume is as important as correctness.** Unfiltered AI review comments erode reviewer trust and cause fatigue even when the precision is reasonable. A reviewer who sees 40 comments per PR and finds 10 of them actionable will stop reading. The volume problem is an oversight failure because it causes human reviewers to disengage from the findings they most need to see.

2. **Cross-vendor corroboration is the strongest filter.** A finding that two reviewers from different vendors independently surface has a much higher prior of being real than a finding surfaced by only one reviewer. This is the same decorrelation argument that motivates the cross-vendor panel (`cross-vendor-review-finds-real-bugs.md`), applied to the ranking problem rather than the coverage problem.

## Why it matters for scalable oversight

`reviewer-agents-file-confident-non-reproducing-reports.md` establishes that AI reviewers produce confident false reports at a non-trivial rate. The natural response — "read everything carefully" — fails at scale. As the volume of AI-generated code and AI-generated review grows, a human reviewer who must carefully evaluate every comment is spending their limited attention in exactly the wrong way: roughly uniform across real and phantom findings.

The oversight capacity problem is real: if human reviewers must treat every AI-review comment as equally credible, the review pipeline's throughput is bounded by the slowest, most skeptical human. Corroboration ranking addresses this by giving the human a prior: start with the findings that multiple independent sources agree on, and treat single-source uncorroborated findings as secondary until a reproduction confirms them.

This is not a concession to reviewer fatigue — it is the scientifically correct response to a known base rate. If the base rate of a single-reviewer AI finding being real is ~50% and the base rate of a corroborated cross-vendor finding is ~90%, the human's time is best spent on the corroborated ones first.

## The mechanism for HOS

The arbiter (oversight-evaluator / oversight-orchestrator) should rank escalated findings by corroboration strength before presenting them to the human:

1. **Tier 1 — deterministic anchor:** findings confirmed by a deterministic gate (static analysis, linter, type checker). These are the highest-signal tier; they appear first and verbatim (per `llm-reviewer-can-mask-deterministic-scanner-failures.md`).
2. **Tier 2 — cross-vendor corroboration:** findings independently surfaced by two or more reviewers from different vendors (agy + codex, or either + Claude). These appear next with the corroborating sources named.
3. **Tier 3 — single-source:** findings surfaced by exactly one reviewer, uncorroborated by a deterministic gate. These are retained in the audit trail but labeled as secondary; the human may defer them to a follow-up pass.

This is not suppression. Every finding appears in the sign-off register. The ranking is purely about the human's reading order, and the ranking labels must be visible so the human knows they are receiving a ranked view.

## What this is not

Corroboration ranking must not become a mechanism for an LLM to suppress findings it dislikes. The ranking must be computed from a deterministic rule (count of independent sources), not from the LLM arbiter's assessment of plausibility. An LLM that ranks its own findings higher because it finds them more persuasive has re-introduced the exact bias the mechanism is designed to remove.

## Provenance

Charoenwet et al. 2026 (AgenticSCR, FSE 2026, arXiv:2601.19138, Zotero: VR9AM6VV). Related: `cross-vendor-review-finds-real-bugs.md` (corroboration as the decorrelation argument for coverage), `reviewer-agents-file-confident-non-reproducing-reports.md` (the false-positive base rate that makes ranking necessary), `llm-reviewer-can-mask-deterministic-scanner-failures.md` (deterministic anchor as Tier 1 in the ranking scheme).
