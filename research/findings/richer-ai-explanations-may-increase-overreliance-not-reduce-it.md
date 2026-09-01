# Richer AI explanations may increase human overreliance, not reduce it

**Claim:** HOS's main lever for improving human oversight has been *better AI-authored explanation* — richer PR comments, fuller handoffs, structured recommendations. The empirical literature says that lever does not reduce overreliance and can increase it, because explanations are read as a general competence signal rather than evaluated on their content. The mechanisms that *do* work are interventions that force engagement with the evidence — and HOS has exactly one, built for unrelated reasons.

Source: Buçinca, Z., Malaya, M. B., & Gajos, K. Z. (2021). *To Trust or to Think: Cognitive Forcing Functions Can Reduce Overreliance on AI in AI-assisted Decision-making.* Proc. ACM Hum.-Comput. Interact. 5(CSCW1), Article 188. doi:10.1145/3449287. N=199, MTurk, simulated AI at 75% accuracy. Read 2026-08-15.

## The results that matter here

1. **Explanations do not fix overreliance.** People "rarely engage analytically with each individual AI recommendation and explanation, and instead develop general heuristics about whether and when to follow the AI." Explanations can *increase* trust and overreliance "just by their presence" (§1).
2. **Cognitive forcing functions (CFFs) work, partially.** Interventions applied *at decision time* to disrupt heuristic reasoning. Three tested: **on demand** (suggestion hidden until requested), **update** (human decides first, then sees the AI and may revise), **wait** (30s delay before the suggestion appears). CFFs significantly reduced overreliance vs. plain explainable AI — but did not eliminate it.
3. **On the cases where the AI was wrong, no-AI beat everything:** `{SXAI} < {CFF} < {no AI}` across all four objective measures (Table 1). Having AI present made people *worse* on precisely the instances where the AI erred, cognitive forcing included.
4. **Effectiveness and acceptability are inversely related** (H2 confirmed). People performed best in the conditions they trusted least, preferred least, and rated most mentally demanding. Trust correlated *positively* with overreliance.
5. **CFFs did not improve overall performance** (H1b unsupported) — only performance on incorrect AI predictions. It is a targeted fix for the error case, not a general uplift.
6. **Intervention-generated inequality:** CFFs disproportionately benefited high Need-for-Cognition participants. Low-NFC participants gained on the narrow sub-measure but not overall (§5, Tables 4–5).
7. **Proxy tasks inflate results.** Asking people to *judge* an algorithm's output is itself a strong CFF, so proxy-task evaluations are systematically more optimistic than real decision tasks (§6).

## What this says about HOS

**The explanation-richness path is probably not the oversight-improvement path.** #1099/#1268 (overseer comments leading with recommendation + expected action + what could not be checked), `handoff.md`'s "full picture", and the evaluator's structured recommendation are all *explanation*. Finding 1 says that raises perceived competence without raising scrutiny. This does not make those changes wrong — they improved legibility — but they should not be counted as overreliance mitigations.

**HOS's one real forcing function was built by accident.** `scripts/run_panel.sh:257,276` reads `panel-context.md` (structural signals only) and *explicitly refuses* `handoff.md` because "it contains internal findings that violate independence." That is the anchoring-avoidance intervention — withhold the prior AI's conclusion so the reviewer forms its own judgement first, i.e. the `update` family, the most effective one tested. HOS justified it as reviewer independence; this paper supplies the mechanism and the evidence.

**The same rule is not applied to the human.** The panel is protected from anchoring; the human is not. The overseer's recommendation leads the PR comment. By finding 3, on exactly the cases where the pipeline is wrong, a human reading the raw diff plus deterministic signals may outperform one reading a confident wrong recommendation.

**Correction to an earlier claim in this repo's discussion:** NG3b R4's three-action ritual (add label, remove label, self-assign, same CODEOWNER, assignment last) is **not** a cognitive forcing function in this paper's sense. It forces deliberateness and proves identity — anti-forgery, anti-accident. It requires no engagement with the *evidence*: nothing obliges the authorizer to have looked at a single suite result. It is a proof-of-identity gate, not a proof-of-attention gate.

**The friction is partly load-bearing.** Finding 4 predicts that HOS's high-friction surfaces are doing oversight work, that the operator will want to reduce them, and that reducing them will quietly degrade oversight quality. This makes #1107 ("optimization of workflow when human approval is required") double-edged rather than pure improvement.

**Finding 5 argues for tier-conditional forcing.** Because CFFs help only in the error case and cost usability, the paper's own future-work proposal is adaptive deployment — apply the strong intervention only where it is predicted to pay. HOS already scales *review depth* by risk tier; it does not scale *human-interaction design* by tier. Applying the strongest forcing function at CRITICAL and none at LOW is the direct analog.

## Threat to the scaling claim (dissertation-relevant)

Finding 6 is the sharpest challenge. HOS exists to *scale* human oversight — plausibly to reviewers with less expertise, less context, or less time than its author. If forcing functions pay off mainly for the already-expert reviewer, the scaling claim weakens exactly where it matters most. Worth preempting rather than being asked.

A claimable extension: Buçinca measured NFC as a stable **trait**. HOS's reviewer is volume-pressured and fatigued — a **state** depletion of cognitive motivation the study does not model. Oversight at 144 cycles/day is a state-depletion regime, which connects directly to the exposure gap in [[hos-scores-severity-and-controllability-but-never-exposure]].

**Methodological caution:** by finding 7, evaluating HOS by asking humans to assess whether HOS's findings were correct is a proxy task and will overestimate performance relative to measuring real merge decisions under normal conditions.

## This project has already produced instances of the failure

- `.claudetmp` handoff, 2026-08-13/14: an architect asserted `check_register_completeness()` returns `bounce_required=True` on every PR (a two-line read disproved it); a pm claimed a waiver mechanism that does not exist. Recorded as "verify sub-agent citations" — overreliance of an AI on an AI.
- 2026-08-15: the human-proxy session told the operator its own cleanup recommendation "wouldn't have helped" **after the operator had already run it and it had worked**. Corrected only by the operator stating "I ran the git commands you gave me." A confident AI contradiction of observed reality, inside a system built to catch exactly that.

## Related

- [[hos-scores-severity-and-controllability-but-never-exposure]] — the exposure axis; state-depletion connection.
- **#1107** — friction reduction where human approval is required; now known to be double-edged.
- **#1099 / #1268** — the explanation-richness work this reframes (legibility gain, not overreliance mitigation).
- `scripts/run_panel.sh:257,276` — the accidental anchoring-avoidance CFF.
- **#1357 / #1358 / #1362** — prose controls that never ran; the failure class overreliance makes invisible.
