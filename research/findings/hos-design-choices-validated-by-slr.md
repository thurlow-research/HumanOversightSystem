# Finding: HOS Design Choices Independently Validated by the Systematic Literature Review

**Role:** research provenance — cross-referencing HOS design decisions against empirical evidence from the SLR corpus

**First observed:** 2026-06-16, session `2026-06-16-v040-unattended-worker.md`

---

## The finding

When the SLR corpus was read against existing HOS design, five core decisions were found to have direct empirical support in peer-reviewed literature. These were not designed *from* the literature — they were designed on first principles and later confirmed. The convergence strengthens the dissertation claim that HOS instantiates generalizable governance patterns, not project-specific workarounds.

This matters for research provenance. A system designed to match the literature is at risk of circular validation: the literature confirms what you built to match it. The reverse is not circular: HOS was built first, the SLR corpus was read against it, and the convergence was discovered post-hoc. That ordering eliminates the circularity concern and makes the five confirmations below genuine independent corroboration.

---

## The five validated choices

### 1. Cross-vendor, no-self-review decorrelation (D4; author-exclusion rule)

**HOS design:** agy + codex + Copilot are selected for vendor diversity; the independence invariant withholds internal findings from second reviewers so each reviewer operates on the diff, not on a prior LLM verdict; no reviewer reviews its own output.

**Empirical support:** SWE-PRBench (Kumar 2026) found single models detect only 15–31% of human-flagged issues. Aggregate recall depends on reviewer diversity — the coverage gap is a function of shared blind spots between author and reviewer when they come from the same training distribution. AgenticSCR (Charoenwet et al. 2026) independently adopted decorrelated reviewing for the same reason, and found cross-vendor corroboration to be the strongest signal for distinguishing real findings from false positives.

The HOS rationale for multi-vendor review (different architectures, different training data, different blind spots) is exactly the mechanism the literature identifies. The literature found it independently; HOS built it from first principles.

**Cite:** Kumar 2026 (SWE-PRBench, arXiv:2603.26130); Charoenwet et al. 2026 (AgenticSCR, arXiv:2601.19138)

---

### 2. Deterministic gates as blockers, not LLM votes (D6/D7)

**HOS design:** `gates/*.sh` scripts are binary and structurally upstream of LLM review. A gate failure is not fed to a reviewer for synthesis or interpretation — it stops the pipeline. LLM reviewers cannot override or downgrade a deterministic gate finding.

**Empirical support:** AIRA (Parris 2026) documented a concrete failure mode: an LLM reviewer masked a deterministic scanner finding by synthesizing it away in its summary verdict. The human saw the LLM's reassuring summary, not the scanner's blocking signal. The HOS gate-before-review ordering prevents this failure mode structurally — not by asking LLM reviewers to be more honest about scanner findings, but by ensuring the LLM reviewer never sees a finding that should have already stopped the pipeline.

The AIRA failure mode is not hypothetical; it was observed in a deployed system. HOS's design choice to keep deterministic gates structurally upstream of LLM review is directly validated by that observation.

**Cite:** Parris 2026 (AIRA, arXiv:2604.17587); see also `llm-reviewer-can-mask-deterministic-scanner-failures.md`

---

### 3. Prompts-as-artifact discipline (D8; `prompts/` directory + git trailers)

**HOS design:** Prompt artifacts are captured at authoring time, committed to the `prompts/` directory, and referenced in git trailers (`Prompt-Artifact:`, `AI-Model:`, `AI-Risk:`). The prompt-fidelity subagent checks semantic alignment between the committed prompt and the produced code, surfacing unexplained additions and missing specs.

**Empirical support:** The practitioner stream (AI House panel; grey-lit corpus) surfaces "prompts as durable governance artifacts" as an emerging norm — the prompt is not ephemeral input but a governance record that enables post-hoc audit of what the model was asked to do versus what it did. The peer-reviewed literature has not yet formalized this construct; HOS's implementation is ahead of that formalization.

This is a case where HOS is ahead of the literature rather than confirmed by it. The practitioner-stream convergence is weaker evidence than peer-review, but it is evidence: practitioners building governed AI systems are independently arriving at the same discipline. The citation is honest about that distinction.

**Cite:** Practitioner-stream construct (AI House panel; SLR grey-lit corpus) — peer-reviewed confirmation pending

---

### 4. Human routed to high-risk decisions, not removed (risk stratification)

**HOS design:** The merge-authority matrix routes LOW/MEDIUM to the overseer bot for autonomous merge; HIGH/CRITICAL and protected surfaces (security-relevant, migrations, config) require human approval. The human is a scarce resource applied to the decisions where they add the most value, not a bottleneck on every decision.

**Empirical support:** Charoenwet et al. 2026 explicitly frames AI-assisted review as a human-capacity problem: unfiltered AI review at scale exhausts human attention, and the only scalable path is routing human time to the decisions that matter. Watanabe et al. 2026 shows that 39.9% of agentic PRs are multi-purpose, increasing per-PR review burden over what human-authored PRs impose; tiered routing is the capacity answer to that burden growth.

HOS's merge-authority matrix is the operational instantiation of the capacity argument the literature makes in the abstract. Both sources find the same thing: you cannot scale human oversight by keeping humans in every loop — you scale it by keeping humans in the *right* loops.

**Cite:** Charoenwet et al. 2026 (AgenticSCR, arXiv:2601.19138); Watanabe et al. 2026 (TOSEM, DOI:10.1145/3798166)

---

### 5. Diff-centric context for reviewers (independence invariant)

**HOS design:** The independence invariant withholds internal findings from second reviewers. Each reviewer receives the diff, not a synthesized prior verdict. The rationale: a reviewer anchored to a prior LLM verdict is not an independent reviewer — it is a confirmer.

**Empirical support:** SWE-PRBench (Kumar 2026) found that adding more context (including prior review summaries) makes LLM review *worse*, not better. The additional context anchors the reviewer to prior verdicts and suppresses independent signal. AgenticSCR adopted diff-centric perception for the same reason, finding that reviewers given only the diff produce more independent and higher-recall findings than reviewers given the full conversation history.

HOS's withholding-of-prior-verdicts is a diff-centric practice by another name. The literature validated the mechanism by studying its absence: when reviewers are given too much context, they produce less independent signal. HOS's design prevents that failure mode by construction.

**Cite:** Kumar 2026 (SWE-PRBench, arXiv:2603.26130); Charoenwet et al. 2026 (AgenticSCR, arXiv:2601.19138)

---

## Why this matters for research

The five convergences above are not a post-hoc rationalization. The HOS design decisions predate the SLR corpus read. The finding is that the literature, assembled independently, arrives at the same conclusions — which makes HOS a citable empirical instantiation of those conclusions rather than a system that happened to implement them.

This strengthens two dissertation claims:

1. **Generalizability.** If the SLR corpus independently validates HOS's design choices, those choices are not artifacts of HOS's particular domain or implementation context. They are governance patterns that apply across agentic systems broadly. This makes HOS a stronger example artifact.

2. **Non-circularity.** The evidence that HOS is well-designed does not come from HOS's own performance data alone. It comes from independent researchers studying different systems and finding the same mechanisms. The dissertation's empirical claims about HOS rest on a foundation that is partially external to HOS itself.

One caveat applies to item 3 (prompts-as-artifact): the peer-reviewed literature has not yet caught up to the practitioner norm. That item is flagged accordingly and should be cited as a practitioner-stream construct pending peer-reviewed confirmation, not as a replicated empirical finding.

---

## Related findings

- `cross-vendor-review-finds-real-bugs.md` — direct HOS evidence for the decorrelation claim (validated choice #1)
- `the-recorder-must-not-be-in-the-recorded-set.md` — related independence-invariant reasoning
- `corroboration-ranked-review-reduces-noise-without-losing-coverage.md` — Charoenwet et al. 2026 in depth (choices #1, #4, #5)
- `llm-reviewer-can-mask-deterministic-scanner-failures.md` — Parris 2026 / AIRA in depth (choice #2)
- `agentic-prs-are-larger-and-more-multipurpose-than-human-prs.md` — Watanabe et al. 2026 in depth (choice #4)
- All SLR-derived findings (P1–P9)
