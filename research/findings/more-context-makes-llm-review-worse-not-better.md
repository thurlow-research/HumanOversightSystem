# Finding: More context makes LLM code review worse, not better — the large-context assumption is empirically disconfirmed

**Role:** oversight-mechanism — reviewer context assembly design; decorrelation justification

**Source:** Kumar 2026 (SWE-PRBench, arXiv:2603.26130, Zotero: 8CQRCPW2) + Charoenwet et al. 2026 (AgenticSCR, arXiv:2601.19138) — SLR P7

---

## The finding

SWE-PRBench found that single LLMs detect only 15–31% of human-flagged issues in code review, and that giving the model more context **made detection worse, not better**. Charoenwet et al. 2026 independently adopted a diff-centric perception strategy — providing reviewers the diff plus curated relevant sections, not the full codebase — for the same empirical reason.

The "large context window improves review" assumption is not only unconfirmed. It is **empirically disconfirmed for review tasks specifically**. Two independent 2026 empirical studies, approaching the problem from different directions, converge on the same result: additional context beyond the diff and relevant spec sections degrades review quality.

This is counterintuitive because it contradicts the intuition from generation tasks (more context → the model knows more about what it should build). The review task is different: the reviewer must hold a specific question ("does this diff introduce a defect?") and reason against a bounded artifact. A large context window floods the reviewer's attention with information that is true but irrelevant to the specific review question, causing the model to attend to the wrong things.

## Why it matters for scalable oversight

**The decorrelation argument is strengthened, not weakened, by this finding.** If large context degrades review, then the standard practice of giving a reviewer "the whole codebase for context" is actively counterproductive. Reviewers should receive the diff plus curated relevant spec sections — not the whole repository. This applies to review-time context assembly only; the following must not be conflated:

- **Review-time context** (what the reviewer sees during review): less is more. Diff + curated relevant spec sections. Whole-repository context degrades detection rates.
- **Generation-time context** (what the coder sees during authoring): more is better-supported. Architecture constraints, standards, prior decisions — all improve generation quality. This finding says nothing about generation-time context.

The independence-invariant withholding already present in HOS — not sharing internal reviewer findings between reviewers before they file — is an instance of this principle. It prevents a reviewer from being anchored to another reviewer's conclusions rather than reading the diff directly.

## The implication for HOS context assembly

The risk-assessor and the review-dispatch machinery should construct each reviewer's context bundle as:

1. The diff (mandatory, verbatim).
2. The relevant spec sections for the changed components (curated, not the full spec).
3. The open tracked issues for this component (per `feed-the-reviewer-its-own-issue-tracker.md`).

What it should **not** include: the full codebase, the full architecture document, prior reviewer findings from the same step, or unrelated historical context. The reviewer's job is to review *this diff*, not to understand the entire system.

This is a constraint on what gets assembled into the review prompt, not a constraint on what the reviewer may ask for. A reviewer may invoke a tool to look up a specific related file — that is targeted, reviewer-initiated context acquisition, which is different from flooding the initial prompt.

## The precision result adds urgency

The 15–31% detection rate (Kumar 2026) means that even with well-constructed context, a single LLM reviewer misses 69–85% of the issues a human reviewer would flag. This number makes the corroboration-ranking finding (`corroboration-ranked-review-reduces-noise-without-losing-coverage.md`) more urgent: if a single reviewer catches only 15–31% of real issues, the coverage argument for multi-reviewer cross-vendor panels is not a belt-and-suspenders luxury — it is a minimum viable detection strategy.

## Provenance

Kumar 2026 (SWE-PRBench, arXiv:2603.26130, Zotero: 8CQRCPW2); Charoenwet et al. 2026 (AgenticSCR, FSE 2026, arXiv:2601.19138, Zotero: VR9AM6VV). Related: `cross-vendor-review-finds-real-bugs.md` (why multi-reviewer panels are necessary given the single-reviewer detection rate), `corroboration-ranked-review-reduces-noise-without-losing-coverage.md` (how to rank the findings from multiple reviewers), `reviewer-agents-file-confident-non-reproducing-reports.md` (confident but false reports are a second, orthogonal failure mode from low detection rate), `feed-the-reviewer-its-own-issue-tracker.md` (an example of curated targeted context that improves convergence without flooding the window).
