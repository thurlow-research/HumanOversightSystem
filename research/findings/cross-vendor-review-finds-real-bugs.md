# Finding: Cross-Vendor AI Review Produces Actionable Findings, Not Just Noise

**First observed:** 2026-06-11, session `2026-06-11-hos-bootstrap-pipeline-hardening.md`
**Confirmed:** 2026-06-12, session `2026-06-12-ux-designer-validation-suite.md`

---

## The Finding

Independent cross-vendor AI review (agy/Gemini and codex/OpenAI reviewing code authored by Claude/Opus) consistently produces genuine, actionable findings — not primarily false positives or trivial style comments. Across two sessions and multiple review passes, the majority of findings required code or documentation changes that improved correctness, and a non-trivial fraction caught bugs that would have produced incorrect behavior in production.

Specifically, on the first self-review run of the HOS framework (June 11):
- agy identified a **critical** bug: nested function double-counting in the Risk Number calculator
- agy identified a **high** bug: stale validator output reads
- agy identified a **high** contract gap: two agents both disclaiming responsibility for GitHub issue creation
- agy identified a **high** design flaw: an unenforceable governance rule with no verification mechanism

On the framework validation run (June 12):
- agy identified 13 structural/consistency findings in escalation paths, cross-file mismatches, and terminology drift — all genuine
- agy identified 3 governance compliance gaps including an incorrect model assignment (coder on Sonnet instead of Opus)
- Most findings were real; false positive rate was low (one confirmed false positive across both sessions)

---

## Why This Matters

**The core methodology claim.** The HOS framework is premised on the claim that independent AI review catches defects that the authoring AI and human reviewer miss. This finding provides direct evidence for that claim: specific bugs in specific files, caught by the reviewer and not by the author.

**Decorrelated failure modes.** The bugs caught by agy were not caught by the developer or by Claude during authoring. This is consistent with the "decorrelated error" hypothesis: different AI systems from different vendors, trained on different data with different architectures, have different blind spots. A bug invisible to the authoring model may be visible to the reviewing model.

**False positive rate is quantifiable and manageable.** Across three review runs, empirical false positive rates were:
- June 11 (agy, first self-review): ~1 false positive of ~8 findings (~12%)
- June 12 morning (agy, framework validation): low false positive rate on 13 structural findings
- June 12 afternoon (codex, after tooling fix): ~20 of 33 findings were design tensions, consumer-project concerns, or stubs acknowledged as stubs (~60%)

The codex adversarial rate (~60% non-actionable) is higher than agy's consistency review rate. This is expected: adversarial probing surfaces more edge-case concerns that turn out to be accepted trade-offs rather than bugs. Both rates are manageable — the triage process (categorize as real, design tension, or context-specific) takes less time than fixing everything codex flags.

**Real bugs at all severity levels.** The findings span critical (logic errors), high (contract violations), medium (design issues), and low (style/documentation) — consistent with what a human code reviewer would surface. The review is not narrowly focused on one class of error.

---

## The False Positive Problem

One finding in the June 11 session was a confirmed false positive: agy reported a signature mismatch in `token_tracker.py` that was actually correct code. The comment in `review_self.sh` that prompted the finding was wrong; the code was fine.

This suggests a pattern: **AI reviewers can be misled by incorrect comments or documentation, just as human reviewers can.** The false positive arose because the review relied on a comment that described expected behavior incorrectly. The code was right; the comment was wrong; the reviewer trusted the comment.

Implication: code comments and documentation that describe expected behavior are load-bearing inputs to AI review. Incorrect documentation is not just a documentation problem — it degrades review quality.

---

## Evidence

June 11, agy review output (`review-20260611T165546.md`):

> **[CRITICAL]** Nested function double-counting in the Risk Number calculator. [...] The RN calculator's count of "functions" used for complexity scoring includes both outer functions and their inner/nested functions, effectively counting nested functions twice.

> **[HIGH]** Contradiction regarding who is responsible for creating GitHub issues between oversight agents. [...] In reality, neither agent creates the issues.

June 12, Phase 2 validation output (`validation-20260612T115530.md`):

> **[Blocking]** coder.md states: "Do not mark any section complete until all three reviewers have approved" (specifying code-reviewer, security-reviewer, and privacy-reviewer). This completely omits ui-reviewer, a11y-reviewer, and infra-reviewer.

> **[Compliance gap REQ-004]** coder.md (the pipeline agent responsible for authoring code) is configured with `model: claude-sonnet-4-6` instead of `claude-opus-4-8`. [...] The coder IS the authoring agent. METHODOLOGY.md states "Opus is the author."

---

## Implications for Research

1. **Cross-vendor review is not primarily a trust exercise.** The value is not that agy is "more trustworthy" than Claude — it's that agy has different blind spots. A security reviewer who was on the team that built the system would find fewer bugs than one brought in from outside. Vendor diversity is the AI-native analog of external review.

2. **The false positive finding points to a complementary discipline.** Comments and documentation that describe expected behavior should be as carefully reviewed as the code itself. In practice, they often aren't — they're written quickly and rarely updated. AI reviewers that reason about consistency between code and its documentation amplify this problem.

3. **Finding rate suggests the methodology scales.** If the first review pass of a carefully-written framework finds critical and high severity bugs, the finding rate for less-carefully-written production code is likely higher. This supports the hypothesis that the methodology provides positive ROI even accounting for the time to review findings.

4. **Quantitative measurement is feasible.** Each review session produces a structured finding list with severity, file, and fix. This data supports empirical measurement of: finding rate by severity, false positive rate, time to fix, recurrence rate. These could form a quantitative baseline for the research paper.

---

## Related findings

- `self-governance-recursion.md` — the framework-applied-to-itself context in which these findings were made
- `unenforceable-rules-need-verification-mechanisms.md` — one specific high-severity finding expanded into its own finding
- `tooling-drift-in-validation-pipelines.md` — a prerequisite condition: the cross-vendor review data above is only meaningful when the tools are actually running correctly
