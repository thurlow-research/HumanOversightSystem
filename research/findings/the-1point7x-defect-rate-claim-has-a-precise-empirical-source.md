# Finding: The 1.7× agentic defect rate claim has a precise empirical source — cite it correctly or the premise weakens

**Role:** research provenance / citation hygiene — a meta-finding about evidence quality and claim-source integrity

**Source:** Loker 2025 (CodeRabbit, 2025-12-17); Ferdous et al. 2026 (MSR, DOI:10.1145/3793302.3793610) — SLR P8

---

## The finding

The claim that AI-assisted code has approximately 1.7× more issues than human-only code traces to a specific, citable primary source: CodeRabbit's *State of AI vs Human Code Generation Report* (Loker 2025, published 2025-12-17). The study covered 470 PRs: 320 AI-co-authored and 150 human-only. The specific breakdown reported is:

- **Overall:** AI-co-authored PRs have approximately **1.7×** more issues than human-only PRs (Poisson rate ratios at 95% CI).
- **Security:** **1.5–2× more** security issues.
- **Readability:** **>3× more** readability issues.

Ferdous et al. 2026 (MSR) is the peer-reviewed restatement of this finding — not a replication from a different dataset, but a secondary scholarly treatment that provides the citation chain from the CodeRabbit report to the peer-reviewed literature.

## Why precise provenance matters for the dissertation

This number is the empirical anchor for the oversight protocol's premise: if AI-assisted code has measurably higher defect rates, then structured human oversight of AI-generated code is not a conservative precaution — it is a correctness requirement. An unsourced "empirical studies show 1.7×" weakens the entire argument.

The specific errors to avoid:

1. **Citing only Ferdous et al. 2026** without acknowledging that the underlying data is from the CodeRabbit report. Ferdous et al. provides the peer-reviewed pathway, but it is the secondary treatment; the primary source and its methodology details are in Loker 2025.

2. **Stripping the context conditions.** The 1.7× figure applies to: 470 PRs, one company's tooling (CodeRabbit's review platform), one time period (data available as of late 2025), and one definition of "issue" (review comments flagged as requiring action). It is a solid estimate with a reported confidence interval. It is not a universal law, and a dissertation that presents it as one invites a methodological objection that distracts from the oversight contribution.

3. **Confusing "AI-co-authored" with "fully AI-generated."** The CodeRabbit dataset is AI-assisted (human + AI tool), not autonomous AI generation. The defect rate for fully autonomous agentic PRs is likely higher, but that claim would need a separate empirical source.

## The correct citation pattern

> Loker (2025) found that AI-co-authored PRs had approximately 1.7× more issues overall, 1.5–2× more security issues, and >3× more readability issues than human-only PRs, in a study of 470 PRs on the CodeRabbit platform (95% CI, Poisson rate ratios). Ferdous et al. (2026) provide the peer-reviewed restatement of this finding.

This pattern: names the primary source, gives the sample size and confidence framing, names the peer-reviewed follow-on, and does not overstate generalizability.

## What this is not

This is a citation hygiene finding, not an empirical result. It does not add new evidence. Its contribution is the source chain: Loker 2025 (primary, with methodology) → Ferdous et al. 2026 (peer-reviewed restatement). Knowing this chain matters because:

- Future replication studies will cite the CodeRabbit report as the baseline; citing only the secondary treatment misrepresents the evidence hierarchy.
- The methodology details (sample size, CI, definition of "issue") are in the primary source; they are needed to evaluate whether the finding generalizes to the dissertation's context.
- The 1.7× figure is the most-cited quantitative claim in the AI code-quality literature; getting its provenance right is a credibility signal for the entire research program.

## Provenance

Loker 2025 (CodeRabbit, *State of AI vs Human Code Generation Report*, 2025-12-17); Ferdous et al. 2026 (MSR, DOI:10.1145/3793302.3793610). Related: `maintenance-class-changes-carry-higher-agentic-risk-than-generation.md` (a separate empirical basis for elevated agentic risk in a different task class).
