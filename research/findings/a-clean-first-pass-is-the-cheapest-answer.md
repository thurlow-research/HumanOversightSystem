# Finding: A Clean First Pass May Be the Cheapest Answer — A Reviewer Confirmed Defects It Had Passed Once Given Specific Claims to Check

**Role:** oversight-mechanism. In one review, a reviewer's answer to an open question ("any blockers?") was clean. A second run of the same reviewer was given another reviewer's specific claims, with pointers to where to look, and it confirmed every one. The hypothesis this raises is that a clean verdict to an open question can be the cheapest answer available, and that specific, falsifiable questions tied to a source draw out deeper checking. The incident cannot separate the question's shape from the new information the second prompt carried. Both are candidate oversight variables.

**Evidence strength:** a single observed incident (n = 1 per condition). All three claims given to the second run were true, so it says nothing about whether a reviewer asked to confirm or refute will also reject false claims rather than agree with them. The human parallel is the human's informal observation, not a measurement.

**First observed:** 2026-11-27, in the human-proxy's pre-review of thurlow-research/seriatim PR #119. The observation comes from the human (ScottThurlow): "many times the initial work by claude (or any LLM) is shallow. You push on it and it digs in, does more thinking/research, adding details and corrects. … people have the same characteristic." Issues: #1471 (evidence comment), #2481, #2482.

---

## What happened

1. **Independent pass.** Seriatim PR #119 (S2-5, head `a9ef61ed9`) went to codex and agy, each with the same request to review it against the spec and technical design for blockers or significant issues.
   - **codex:** "No blockers or significant issues." It gave no list of what it had checked.
   - **agy:** three test defects.
     - A slot-release race. Two requests that each take the one slot are sent back to back on new connections. TD-slice-1 §8.6 records this race as having already failed PR #92's CI.
     - float64 epoch subtraction that breaks the test's own 1 ms tolerance. The human-proxy measured it by subtracting 1000 exact 199 ms pairs at current epoch magnitudes: 504 fell outside the tolerance.
     - An import form (`import seriatim_node.app as app_module`) that `conftest.py:23-25` explicitly forbids.
2. **Verification.** The human-proxy checked each claim against the code and found all three real. Under the convergence rule then in force (send back only when both reviewers agree), the PR would have gone to the human as ready, because the reviewers disagreed. That is an inference from the rule, not an observed outcome.
3. **Confirm-or-refute round.** codex was given agy's three claims with their evidence pointers and asked to confirm or refute each one adversarially. It **confirmed all three**, with file:line evidence, and judged each one fix-in-this-PR. The PR went back to its author as one REQUEST_CHANGES review (2026-11-27).

The model and the code were the same in both codex runs. The second prompt differed in two ways at once: it asked targeted, falsifiable questions instead of an open one, and it supplied new information (another reviewer's claims and where to look). It was also a separate run. This incident cannot say which of these produced the deeper check.

## Candidate explanations

These are hypotheses for #1471 and #2481 to test, not established mechanisms.

- **An open question may invite a satisficing answer.** "Any issues?" can be answered cheaply: a reviewer that finds nothing quickly can stop. A specific claim is harder to dismiss without opening the file, though a reviewer can still assert an answer without checking.
- **A clean verdict carries no evidence of effort.** An empty findings list from a careful reviewer looks exactly like one from a reviewer who barely looked. The pipeline counts both as discharged. This one is a property of the record, not a guess about the reviewer.
- **New evidence, not the re-ask, may be what helped.** The second pass carried another reviewer's specific claims. The literature on self-correction (below) suggests that asking the same model "are you sure?" without new evidence is unreliable on reasoning tasks.

The incident did not reveal which happened inside codex's first run: whether it looked at the test files and missed the defects, or did not look at them.

## External evidence

Bibliographic details, and abstracts where available, were checked against OpenAlex and Semantic Scholar on 2026-11-27. This is a targeted lookup, not a systematic search. Each row states what the source studied; its bearing on HOS is an analogy or hypothesis unless it says otherwise.

| Practice | Evidence | Bearing | In Zotero |
|---|---|---|---|
| **New evidence, not bare self-review** | Huang et al., "Large Language Models Cannot Self-Correct Reasoning Yet", ICLR 2024 (arXiv:2310.01798). On reasoning benchmarks, intrinsic self-correction, without external feedback, did not reliably improve answers and sometimes made them worse. | qualifies the "are you sure?" re-ask; consistent with giving the second pass outside claims | yes (`CXQFKT3S`) |
| | Madaan et al., "Self-Refine: Iterative Refinement with Self-Feedback", NeurIPS 2023 (arXiv:2303.17651). The same model generates, critiques and refines its own output; this improved results on the seven tasks tested, which included dialogue, code optimization and a math-reasoning task. | counterpoint: same-model feedback helped there. Huang et al. found intrinsic self-correction unreliable on their reasoning benchmarks; the two differ in tasks, prompts and evaluation conditions | yes (`XBRTG9KD`) |
| **Targeted verification questions** | Dhuliawala et al., "Chain-of-Verification Reduces Hallucination in Large Language Models", arXiv:2309.11495, 2023 (ACL Findings 2024 version unverified). The model plans its own verification questions, answers them independently of its draft, and revises; this reduced hallucination. | analogous: the questions are model-generated, not supplied by a second reviewer | yes (`4MQFRA5D`) |
| **Reviewers exchanging claims** | Du et al., "Improving Factuality and Reasoning in Language Models through Multiagent Debate", ICML 2024 (arXiv:2305.14325). Several model instances exchange answers over rounds; this improved factuality and reasoning on the tasks tested. Huang et al. report that ungrounded debate does not reliably beat self-consistency at equal cost. | analogous to the confirm-or-refute round, which is grounded in file:line checks | yes (`GGKFBJKH`) |
| **Self-explanation** | Chi et al., "Eliciting Self-Explanations Improves Understanding", Cognitive Science 1994 (doi:10.1207/s15516709cog1803_3). Eighth-grade students prompted to explain a biology text to themselves as they read it understood it better. | analogous mechanism in human learning (reading, not authoring or defect-finding) | yes (`AZ9AGHB6`) |
| **Tracing artifacts to their source** | Rempel & Mäder, "Preventing Defects: The Impact of Requirements Traceability Completeness on Software Quality", IEEE TSE 43(8), 2017 (online 2016; doi:10.1109/TSE.2016.2622264). An observational study of 24 open-source projects: more complete traceability was associated with a lower expected defect rate. | associational support for traceability in general; does not test HOS's requirement-to-PR-claim chain | yes (`Z9U7JQJS`) |
| | Gotel & Finkelstein, "An analysis of the requirements traceability problem", ICRE 1994; Ramesh & Jarke, "Toward reference models for requirements traceability", IEEE TSE 2001 | background | yes (`FUIU35NM`, `32FJP5WQ`) |
| **Design rationale** | Tang et al., "A Survey of the Use and Documentation of Architecture Design Rationale", WICSA 2005 (doi:10.1109/wicsa.2005.7) (a separate 2006 *Journal of Systems and Software* article reports the same survey). Practitioners valued design rationale but often did not document it. | qualifies, on adoption cost | yes (`DX93G6AH`) |
| | Burge, "Software Engineering Using Design Rationale" (PhD dissertation, WPI 2005). Built SEURAT, which checks captured rationale for completeness and consistency, to make capture worth its cost; short-task evaluation showed overhead. | design inference only: favours checked tables over free prose | yes (`6BHII5DA`) |
| **Author explanations can be unfaithful** | Turpin et al., "Language Models Don't Always Say What They Think: Unfaithful Explanations in Chain-of-Thought Prompting", NeurIPS 2023 (arXiv:2305.04388). Chain-of-thought explanations can misrepresent what actually drove the model's answer. | supports treating author claims as inputs to verify, not as evidence | yes (`GKKQH9C4`) |
| **Independent judgment before seeing the AI's** | Buçinca et al., "To Trust or to Think: Cognitive Forcing Functions Can Reduce Overreliance on AI in AI-assisted Decision-making", PACM HCI 5(CSCW1), 2021 (doi:10.1145/3449287). Three cognitive forcing designs (on-demand, update, wait) reduced, but did not eliminate, overreliance compared with simple explainable-AI designs. | analogous support for "independent pass first" | yes (`UTTJ5N93`) |
| | Vasconcelos et al., "Explanations Can Reduce Overreliance on AI Systems During Decision-Making", PACM HCI 7(CSCW1), 2023 (doi:10.1145/3579605). Five studies of a maze task: people engaged with explanations, and overreliance fell, under conditions where the task was hard and the explanation made verifying the AI cheaper. | hypothesis: source-tied, checkable claims may lower verification cost | yes (`JZ76J43W`) |
| **Author framing biases LLM reviewers** | Mitropoulos et al., "Measuring and Exploiting Contextual Bias in LLM-Assisted Security Code Review", arXiv:2603.18740v2, 2026 (cited at v2; the title and results differ in other versions). Across 17 CVEs in 10 real projects, template-based biasing of PR metadata was ineffective, but an iteratively refined attack on titles, descriptions and commit messages led LLM reviewers to accept every vulnerability-reintroducing change. In v2, metadata redaction combined with an explicit debiasing instruction restored detection in all affected cases. | direct evidence that author-supplied text can anchor an LLM reviewer (adversarial case); see `adversarial-framing-attack-on-reviewer-agents.md` | yes (`X7EN6DXZ`) |
| **Existing comments in code review** | Spadini et al., "Primers or Reminders? The Effects of Existing Review Comments on Code Review", ICSE 2020 (doi:10.1145/3377811.3380385). Visible, valid comments from other reviewers acted as reminders for bug types reviewers don't usually consider. Misleading comments were not tested. | qualifies; concerns other reviewers' comments, not the author's rationale | yes (`RQSG5VFX`) |
| **Anchoring, outside code review** | Rosbach et al., "Stuck on suggestions: Automation bias, the anchoring effect, and the factors that shape them in computational pathology", Machine Learning for Biomedical Imaging (MELBA), 2026 (doi:10.59275/j.melba.2026-87b1): human experts working with AI assistance. Lou & Sun, "Anchoring bias in large language models: an experimental study", Journal of Computational Social Science, 2025 (doi:10.1007/s42001-025-00435-2): LLMs as the anchored party. | background; separates the human and LLM anchoring cases | yes (`D62FTR38`, `TMSMG2G9`) |
| **Failure framing** | Klein, "Performing a Project Premortem", Harvard Business Review 2007 (IEEE EMR reprint 2008, doi:10.1109/EMR.2008.4534313). A practitioner essay; the method rests on prospective-hindsight research (Mitchell, Russo & Pennington 1989). | practitioner precedent in human planning; untested in LLM review | yes (`FEDCSX6V`) |

**A narrower gap.** Mitropoulos et al. show that *adversarial* author framing anchors LLM reviewers, and that redacting it, with an explicit debiasing instruction, restored detection in their setting. Among the sources checked so far, no study was found of anchoring on an *author's own* justification in code review in the *benign* case: structured justification (for example, a table of claims each citing its source) anchoring a human or LLM reviewer. A bounded gap-check search is planned (forward and backward from Spadini et al.; forward from Vasconcelos et al. and Buçinca et al.). The benign case is the one #2482 creates. Its mitigation, reading the author's claims only after an independent pass, shields the first pass from the PR-level claims, though not from inline why-comments in the diff itself. Whether the claims still anchor the verification round after it is unmeasured. The two research tracks stay separate: the dissertation survey measures how common these practices are (rationale exposure order, independent-first review, coverage disclosure), while #2481 and #2482 test whether they work.

## The response

Status as of 2026-11-28. Item 1 is in use only in the human-proxy's own pre-reviews, and item 5 is practised there informally; the pipeline versions of both, and items 2 to 4, are proposed or planned.

1. **Confirm-or-refute round on disagreement** (#1471's Phase 2). When reviewers disagree, each is given the other's specific claims and must confirm or refute them with evidence. This incident is its first field use.
2. **A clean verdict must carry its coverage map** (#2481, proposed). It would list the files, the requirements and the failure classes checked, and a clean verdict without one would be recorded as `unverified`, not as a pass.
3. **Every artifact traces to its source** (#2482, proposed). The chain would run requirement → design → code → test → PR claims. The claims would be falsifiable and cite their source, with why-comments only where a choice isn't obvious. Reviewers would read the claims only **after** an independent pass, so the first pass is not anchored by them. Adoption cost: in Buçinca et al., the forcing designs that reduced overreliance most were the ones participants rated least favorably.
4. **Failure framing in review prompts.** Ask "assume this breaks; where?", not "is this OK?". Untested here.
5. **Review on a different model family from the author** (#2372, planned for v0.7.2; the human-proxy's pre-reviews already do this informally). This addresses a related but separate cause: shared blind spots, rather than shallow passes.

## Implications for research

1. **The prompt is a candidate oversight variable.** In this case the same reviewer returned nothing to an open question and three confirmed defects to a targeted, evidence-carrying one. Reporting the prompt shape, and what information the prompt carried, alongside reviewer outcomes would let later work separate the two.
2. **A clean verdict is a weak signal.** In this run it was the least informative output. A clean verdict without evidence of coverage is better treated as missing data than as a pass.
3. **Checkable justification, read late, is a hypothesis.** Traceability completeness is associated with fewer defects (Rempel & Mäder). Explanations reduced overreliance where they lowered the cost of verifying (Vasconcelos et al.). Explanations alone do not reduce overreliance (Buçinca et al.), and model explanations can be unfaithful to the reasoning behind them (Turpin et al.). Author framing can anchor LLM reviewers (Mitropoulos et al.). Together these suggest, without establishing, that short, source-tied claims verified after an independent pass are the safer form.
4. **Measure it.** Once #2481 and #1471 land, compare findings from open versus targeted prompts, with and without supplied claims, and include false claims so that agreement with a wrong claim can be detected. Compare clean verdicts with and without coverage maps. Anchoring on benign author justification is a candidate study.
5. **People too, as an analogy.** Self-explanation, pre-mortems and cognitive forcing are human practices aimed at the same problem. This is `hos-ports-human-software-engineering-best-practices.md` applied to the depth of a single review; the incident does not show that people and models share the mechanism.

## Related findings

- `adversarial-framing-attack-on-reviewer-agents.md`: author framing anchors LLM reviewers (Mitropoulos et al.)
- `richer-ai-explanations-may-increase-overreliance-not-reduce-it.md`: explanations can raise overreliance
- `wrong-rationale-outlives-wrong-conclusions.md`: a recorded rationale is inherited without re-checking
- `corroboration-ranked-review-reduces-noise-without-losing-coverage.md`: detector-then-validator
- `reviewer-agents-file-confident-non-reproducing-reports.md`: confident reports still need verification
- `explicit-na-audit-entries.md`: "found nothing" must be distinguishable from "didn't look"
- `cross-vendor-review-finds-real-bugs.md`: decorrelation, the complementary control
- `omission-class-documentation-bugs.md`: checking against the authoritative source
- `hos-ports-human-software-engineering-best-practices.md`: the human-practice lens
