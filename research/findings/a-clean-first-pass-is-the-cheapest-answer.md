# Finding: A Clean First Pass Is the Cheapest Answer — Targeted, Source-Tied Verification Is What Makes a Reviewer Dig

**Role:** oversight-mechanism. A reviewer's first answer to an open question ("any issues?") is often shallow, and a clean verdict is the cheapest answer it can give. The same reviewer, asked a specific, falsifiable question tied to a source ("is this claim right? show me the file and line"), does much deeper work. Asking better questions is an oversight control in its own right: confirm-or-refute rounds between reviewers, clean verdicts that must show what they covered, and artifacts traced to their sources. People show the same pattern.

**First observed:** 2026-11-27, in the human-proxy's review of Seriatim PR #119. The principle comes from the human (ScottThurlow): "many times the initial work by claude (or any LLM) is shallow. You push on it and it digs in, does more thinking/research, adding details and corrects. … people have the same characteristic." Issues: #1471 (evidence comment), #2481, #2482.

---

## What happened

1. **Independent pass.** Seriatim PR #119 (S2-5, head `a9ef61ed9`) went to codex and agy with the same question: "any blockers or significant issues against the spec and TD?"
   - **codex:** "No blockers or significant issues." It gave no list of what it had checked.
   - **agy:** three test defects.
     - A slot-release race. Two requests that each take the one slot are sent back to back on new connections. This is the race TD-slice-1 §8.6 records as having already failed PR #92's CI.
     - float64 epoch subtraction that breaks the test's own 1 ms tolerance. The human-proxy measured it: 504 of 1000 exact 199 ms pairs fail.
     - An import form that `conftest.py` explicitly forbids.
2. **Verification.** The human-proxy checked each claim against the code and found all three real. Under the convergence rule then in force (send back only when both reviewers agree), the PR would have gone to the human as ready, because the reviewers disagreed.
3. **Confirm-or-refute round.** codex was given agy's three claims with their evidence pointers and asked to CONFIRM or REFUTE each one adversarially. It **confirmed all three**, with file:line evidence, and judged each one fix-in-this-PR. The PR went back to its author with one REQUEST_CHANGES review.

The model and the code were the same in both codex runs. Only the question changed.

## Why it happens

- **An open question invites a satisficing answer.** "Any issues?" can be answered cheaply: a reviewer that finds nothing quickly can stop. A specific claim can't be answered without opening the file and checking.
- **A clean verdict carries no evidence of effort.** An empty findings list from a careful reviewer looks exactly like one from a reviewer who barely looked. The pipeline counts both as discharged.
- **Self-review without new evidence doesn't fix this.** Asking the same reviewer "are you sure?" mostly rephrases the first answer. The second pass worked here because it carried outside evidence: another reviewer's specific claims.

## External evidence

Checked against OpenAlex and Semantic Scholar on 2026-11-27. The Zotero status is given for each source.

| Practice | Evidence | Bearing | In Zotero |
|---|---|---|---|
| **Re-ask with outside evidence, not bare self-review** | Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet", ICLR 2024 (arXiv:2310.01798): without external feedback, self-correction doesn't reliably help and can hurt | qualifies self-critique; supports the confirm-or-refute round | yes (`CXQFKT3S`) |
| | Madaan et al., "Self-Refine", NeurIPS 2023 (arXiv:2303.17651): iterative self-feedback improves output | supports, with feedback | yes (`XBRTG9KD`) |
| **Targeted verification questions** | Dhuliawala et al., "Chain-of-Verification Reduces Hallucination in LLMs", ACL Findings 2024 (arXiv:2309.11495): answering planned verification questions independently cuts errors | supports | no |
| | Du et al., "Improving Factuality and Reasoning in Language Models through Multiagent Debate", ICML 2024 (arXiv:2305.14325) | supports | yes (`GGKFBJKH`) |
| **Explaining your own work surfaces errors** | Chi et al., "Eliciting Self-Explanations Improves Understanding", Cognitive Science 1994 (doi:10.1207/s15516709cog1803_3) | supports, in people | no |
| **Tracing artifacts to their source** | Rempel & Mäder, "Preventing Defects: The Impact of Requirements Traceability Completeness on Software Quality", IEEE TSE 2017 (doi:10.1109/TSE.2016.2622264). Across 24 projects, "more complete traceability decreases the expected defect rate", the first empirical evidence of this | supports | no |
| | Gotel & Finkelstein, "An analysis of the requirements traceability problem", 1994; Ramesh & Jarke, "Toward reference models of requirements traceability", 2001 | background | yes (`FUIU35NM`, `32FJP5WQ`) |
| **Design rationale** | Tang et al., "A Survey of the Use and Documentation of Architecture Design Rationale", WICSA 2005/06 (doi:10.1109/wicsa.2005.7): practitioners value rationale but rarely record it; Burge, SEURAT (dissertation, WPI 2005): rationale pays only when tools check it for completeness and consistency | qualifies, on adoption cost; supports checked tables over prose | no |
| **Author explanations can mislead** | Turpin et al., "Language Models Don't Always Say What They Think", NeurIPS 2023 (arXiv:2305.04388): explanations can be unfaithful to the actual reasoning | supports treating claims as inputs to verify | no |
| | Buçinca et al., "To Trust or to Think: Cognitive Forcing Functions Can Reduce Overreliance on AI", CSCW 2021 (doi:10.1145/3449287): explanations alone don't reduce overreliance; making people engage before seeing the AI's answer does | supports "independent pass first" | yes (`UTTJ5N93`) |
| | Vasconcelos et al., "Explanations Can Reduce Overreliance on AI Systems During Decision-Making", PACM HCI 2023 (doi:10.1145/3579605): explanations reduce overreliance when they **lower the cost of verifying** the AI | supports source-tied, checkable claims | no |
| **Anchoring in code review** | Spadini et al., "Primers or Reminders? The Effects of Existing Review Comments on Code Review", ICSE 2020 (doi:10.1145/3377811.3380385): visible review comments acted as positive reminders for bug types reviewers don't usually consider, not as negative primers | qualifies; it concerns reviewer comments, not author rationale | no |
| | Several 2024–26 papers on anchoring in LLMs and AI assistance (e.g. "Stuck on suggestions", "Anchoring bias in large language models") | background | yes (`D62FTR38`, `TMSMG2G9`, others) |
| **Failure framing** | Klein, "Performing a Project Premortem" (HBR 2007; IEEE EMR reprint 2008, doi:10.1109/EMR.2008.4534313) | supports | no |

**A research gap.** No study was found of anchoring on an *author's own* justification in code review. That is exactly the risk of asking authors for justification artifacts. Spadini et al. study comments from other reviewers, not the author. HOS's design (#2482: reviewers read the author's claims only after their own independent pass) is an untested mitigation for an unmeasured effect.

## The response

1. **Confirm-or-refute round on disagreement** (#1471's Phase 2, now with field evidence). When reviewers disagree, each is given the other's specific claims and must confirm or refute them with evidence. The human-proxy applies this now in its own pre-reviews. #1471 carries the design.
2. **A clean verdict must carry its coverage map** (#2481). It lists the files, the requirements and the failure classes checked. A clean verdict without one is recorded as `unverified`, never as a pass.
3. **Every artifact traces to its source** (#2482). The chain runs requirement → design → code → test → PR claims. The claims are falsifiable and cite their source, and why-comments appear only where a choice isn't obvious. Reviewers verify the claims **after** an independent pass, so the author's justification cannot anchor them.
4. **Failure framing in review prompts.** Ask "assume this breaks; where?", not "is this OK?".
5. **Review uses a different model family from the author** (#2372, v0.7.2). This addresses a related but separate cause: shared blind spots, rather than shallow passes.

## Implications for research

1. **The question is an oversight variable.** The same reviewer gives different coverage under an open question and under targeted ones. Report the prompt shape alongside reviewer outcomes; a "reviewer found nothing" result means little without it.
2. **A clean verdict is a weak signal.** In this case it was the weakest signal of the run. Treat a clean verdict without evidence of coverage as missing data, not as a pass.
3. **Justification helps when it is checkable and read late.** Traceability is empirically linked to fewer defects (Rempel & Mäder). Explanations reduce overreliance when they make verification cheaper (Vasconcelos et al.). Fluent, unverified explanations can raise overreliance (Buçinca et al.; Turpin et al. on unfaithfulness). Read together, these favour short, source-tied claims, verified after an independent pass.
4. **Measure it.** Compare the findings from open versus targeted questions, and from clean verdicts with and without coverage maps, once #2481 and #1471 land. The open gap (anchoring on author rationale) is a candidate study.
5. **People too.** Every mechanism here has a human counterpart: self-explanation, checklists, pre-mortems, cognitive forcing. This is `hos-ports-human-software-engineering-best-practices.md` applied to the depth of a single review.

## Related findings

- `richer-ai-explanations-may-increase-overreliance-not-reduce-it.md`: explanations can raise overreliance
- `wrong-rationale-outlives-wrong-conclusions.md`: a recorded rationale is inherited without re-checking
- `corroboration-ranked-review-reduces-noise-without-losing-coverage.md`: detector-then-validator
- `reviewer-agents-file-confident-non-reproducing-reports.md`: confident reports still need verification
- `explicit-na-audit-entries.md`: "found nothing" must be distinguishable from "didn't look"
- `cross-vendor-review-finds-real-bugs.md`: decorrelation, the complementary control
- `omission-class-documentation-bugs.md`: checking against the authoritative source
- `hos-ports-human-software-engineering-best-practices.md`: the human-practice lens
