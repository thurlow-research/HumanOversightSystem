# Finding: Agentic PRs are larger and more multi-purpose than human PRs — both are leading indicators of review failure

**Role:** oversight-mechanism — risk tier calibration; diff-size and task-mixing as deterministic governance signals

**Source:** Watanabe et al. 2026 (TOSEM, DOI:10.1145/3798166, arXiv:2509.14745) — SLR P5

---

## The finding

Watanabe et al. 2026 measured agentic and human PRs across a large open-source corpus and found:

- Agentic PRs have a **median of 48 added lines** vs 24 for human PRs — roughly 2×.
- **39.9% of agentic PRs are multi-purpose** (mix of distinct task types, e.g., feature + refactor, or fix + docs update) vs 12.2% for human PRs — more than 3×.
- Human reviewers **explicitly reject oversized agentic PRs** as impractical to review, with comments like "closing in favor of smaller, more focused PRs."

The rejection feedback from human reviewers is load-bearing: it is not a stylistic preference. A reviewer who must understand a feature change and a refactor and a documentation update simultaneously has their cognitive budget split across three distinct mental models. The probability of catching a defect in any one of them falls.

## Why it matters for scalable oversight

Size and multi-purpose scope are **leading indicators** of review failure, not lagging indicators. By the time a reviewer rejects a PR as impractical to review, the oversight failure has already occurred: the PR was submitted, review capacity was consumed, and the rejection itself costs the team time. The correct point of intervention is before the PR is opened.

This is a governance decision, not a coding decision. An agent that produces a 200-line refactor-plus-feature PR has made a structural choice about the unit of human review — a choice that is structurally harder to review, structurally harder to revert, and structurally harder to audit than two focused PRs of 100 lines each. The agent made this choice implicitly, by not splitting; the oversight framework should make it explicit.

The finding maps directly to HOS's oversight scaling problem (OSA-VOLUME): as agents produce more code, the volume of changes requiring human review grows. An agent that consistently produces oversized multi-purpose PRs multiplies the review load faster than it produces working code.

## The deterministic signal and its use

Both indicators are measurable without an LLM:

- **Diff size:** line count of additions + deletions (or added files × estimated line weight). The threshold is not a magic number; the principle is that a threshold must exist and must be calibrated to the reviewer's cognitive budget.
- **Multi-purpose detection:** task-type label detection on the commit messages or PR title + body. Heuristics ("fix" + "refactor" in the same PR; "feat" + "docs") are sufficient as a first-pass detector.

These belong in the risk-tier floor — deterministic signals that the agent (and the risk-assessor) must check before opening a PR, not in the reviewer's subjective assessment after opening. The risk-assessor should:

1. Flag any PR exceeding the configured line threshold as requiring explicit split justification or decomposition.
2. Flag any PR with mixed task labels as multi-purpose and require the agent to confirm the mixing is intentional and justified.
3. Escalate to the human if the agent cannot provide that justification — because at that point the governance decision (how to split the work) belongs to the human, not the agent.

## What this is not

This finding is not an argument for arbitrary small PRs. A single focused change that requires 300 lines to implement correctly is better as one PR than as three artificial splits that break the working state between them (`working-state-invariant.md`). The constraint is on *mixing unrelated concerns*, not on raw size for a single cohesive change.

## Provenance

Watanabe et al. 2026 (TOSEM, DOI:10.1145/3798166, arXiv:2509.14745, Zotero: P868GNU7). Related: `working-state-invariant.md` (the working-state argument for why artificial splits can be worse), `three-tier-review-cost-model.md` (the reviewer cognitive-budget model that makes size a risk signal).
