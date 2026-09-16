# Finding: a correctly-disclosed escalation still fails if it isn't salient — buried disclosure fails like no disclosure

**Role:** oversight-mechanism — human attention allocation as a component of the oversight loop, distinct from signal correctness

**Source:** HOS session, 2026-09-16 — PR #1710 (`thurlow-research/HumanOversightSystem`)

---

## The finding

On 2026-09-16, a HOS release-management PR (#1710) carried a real, converged human escalation: the underlying security-fix epic (#1539/#1540) was blocked on an explicit human yes/no across several named items, stated in the document as "`coder` is NOT cleared to build." The human operator merged the PR anyway, without seeing the escalation.

This was not a failure of the oversight mechanism in the sense this project usually means it (a check that was narrated but never executed, or a signal that was never generated). The escalation was disclosed **twice**, accurately and completely, by two independent authors:

1. The PR body itself stated the block explicitly — at line ~440 of a 461-line document.
2. The autonomous reviewing agent's own review comment disclosed it in full, under a section titled "Where the human input actually sits," and explicitly declined to soften it ("That escalation is real and I am not softening it"). But that same comment's **Executive Summary** — the first thing a reader sees — read "Expected action: NO ACTION."

Both disclosures were technically correct. "NO ACTION" was accurate in a narrow sense: the reviewing agent itself had nothing to do — it could not merge the PR regardless of the escalation's status. But it reads, to a human scanning the top of the comment, as "nothing needs your attention" — and that is exactly what happened. The escalation only became findable by the human after the fact, once the merge was already done.

## Why it matters for scalable oversight

This project's dominant failure model to date has been **narration without execution**: a control that reads source and describes what it would do, rather than a real, callable mechanism that actually runs (the "USE THE CODE, don't narrate" principle, #1357/#1358). This finding is a different failure class, occurring even when narration-without-execution is fully solved: **a signal can be technically generated, complete, and accurate, and still fail to reach the human, because of where and how it is presented.**

Two established human-factors literatures predict this outcome directly, independent of anything specific to AI-assisted development:

- **Automation bias / complacency** (Parasuraman & Manzey and the following literature): once a system presents a confident top-line summary, human reviewers tend to trust that summary as ground truth rather than independently verifying the content it summarizes. A summary line becomes the effective decision surface, not a pointer to one.
- **Dual-process reasoning** (Kahneman, *System 1 / System 2*): a long, technically dense document invites fast, heuristic scanning (check for the top-line verdict, check for green/red) rather than the slow, effortful reading needed to reach content stated near the end. The document's own structure determines which mode a reader defaults into, largely independent of the reader's diligence.
- **Alert fatigue** (originally documented in healthcare and aviation human-factors research): this session separately found that the underlying autonomous-merge gate had a stub defect (`_dep_ceiling_check_present()` returning `False` unconditionally) forcing *every* PR through manual human review, regardless of actual risk, for an extended period. High review volume with a low true-positive rate for "this one actually needs deep attention" is exactly the precondition alert-fatigue research predicts will erode vigilance for the rare real signal.
- **Signal placement / salience** (information-architecture and warning-label research; F-shaped reading patterns): a warning stated after several hundred lines of supporting detail has a dramatically lower read-probability than the same warning stated first, independent of its accuracy or completeness.

The implication for HOS's own research claims: **auditability and disclosure completeness are necessary but not sufficient for effective human oversight.** A system can satisfy "the information was there" while still failing "the human received it," and these are measurably different properties. A dissertation claim that HOS provides effective human oversight needs evidence on both axes, not just the first.

## The mechanism for HOS

Two concrete engineering fixes were filed from this same incident (`thurlow-research/HumanOversightSystem` #1714, #1715), because the finding has both a research dimension and a direct remediation:

- Any AI-authored document or PR body whose content concludes with a real, unresolved human escalation must carry a prominent banner at the **top** — not a conclusion reached only after full reading.
- An autonomous reviewer's own "expected action" framing must separate two distinct questions that were previously collapsed into one field: *does the reviewing agent itself need to act* (merge/bounce/hold) versus *does the human need to act on something*, which may not even be on the artifact being reviewed. "No action" on the first must never read as "no action" on the second.

Separately, and not a substitute for the above: the review-volume problem (the stub forcing 100% manual review) compounds the salience problem by inflating the base rate of "routine, nothing to see here" reviews a human must scan past, which is itself an alert-fatigue amplifier independent of any single document's formatting.

## The trap it avoids

"The information was in the disclosure" is not the same claim as "the human received the information," and treating them as equivalent is itself a form of automation bias applied to the oversight system's own reporting — trusting that generation of a correct artifact discharges the system's obligation, without verifying it against how humans actually read under realistic conditions (time pressure, high routine-approval volume, long documents). A governance framework that only measures signal correctness, and never signal salience, can report itself as fully auditable while still failing the human it exists to keep informed.

## Provenance

HOS session, 2026-09-16 (human-proxy session, PR #1710 review). Related engineering issues: `thurlow-research/HumanOversightSystem` #1714 (the autonomous-merge stub that inflated review volume) and #1715 (the buried-escalation-banner fix). Connects to `unexplained-pr-rejection-is-a-transparency-gap-in-agentic-systems.md` (silence is not a valid oversight record) as a companion finding: that finding is about the *absence* of a disclosure; this one is about a *present but inaccessible* disclosure — both fail the same downstream test (can the human or a future auditor actually recover the decision that mattered), by different mechanisms.
