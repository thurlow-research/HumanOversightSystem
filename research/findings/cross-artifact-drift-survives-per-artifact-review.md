# Finding: Cross-artifact referential drift survives per-artifact review — every document can be internally coherent while the set is wrong

**Role:** oversight-mechanism — a defect class that is invisible to any review scoped to a single artifact, because the defect lives in the *relationship between* artifacts rather than inside any one of them

**First observed:** 2026-07-29, HOS design-chain consistency check over the Astro/JS epic (ADR-032 → epic spec → corrected decomposition → tickets #1060–#1074)

---

## The finding

A deep-reasoning consistency pass was run over a full design chain — ADR, epic spec, decomposition, and the filed tickets — with a deliberately different instruction from the usual review framings: it was handed the seven already-known defects and asked to find what that list *misses*.

It returned a **blocker** that three prior review passes had not caught. The decomposition's Task-4 action table had **#1072 and #1073 swapped**, consistently — in the intro, in the table, and in three section headers. Because the document instructed readers to *"treat the table, not the S-labels, as authoritative"*, applying it verbatim would have **closed the astro pack mega-ticket as a folded micro-ticket, and split the tiny framing ticket into three.**

The essential property: **every individual document was internally coherent.** The ADR was coherent. The epic spec was coherent. The decomposition was coherent *with itself* — the swap was consistent across all five of its references, so nothing inside it contradicted anything else inside it. The defect existed only in the correspondence between the decomposition's issue numbers and the actual tickets in the tracker. No amount of reviewing any single artifact could surface it.

Four MAJOR findings had the same shape — tickets specifying in-place edits to Python validators that a ratified decision had already superseded and merged code had already routed around; a dependency cycle where a slice needed a library installed by a ticket that depended on that slice; a ticket re-importing fail-open language that a ratified decision had removed; and an additive-composition rule breaking a pack's stated content. Each is a contradiction *between* a ticket and a decision or a merged artifact, not a flaw within either.

## Why it matters for scalable oversight

Review is almost always scoped to an artifact: review this PR, this spec section, this design doc. That scoping is what makes review tractable — and it is precisely what makes this defect class invisible. As a governed pipeline accumulates artifacts (spec → ADR → technical design → decomposition → tickets → code), the number of *pairs* that can drift grows faster than the number of artifacts, while review coverage stays per-artifact. The gap widens with maturity.

Worse, this class is **selectively invisible to the checks most likely to be automated**. A referential swap between two issue numbers passes every structural lint, every schema validation, and every "is this document well-formed" gate. It reads as correct to a reviewer who trusts the document's internal consistency — which is the rational default, since internal consistency is normally strong evidence of care.

Two consequences for oversight design:

1. **At least one review pass must take the artifact *set* as its unit**, not any single artifact. A panel composed entirely of per-artifact reviewers has a structural blind spot no amount of reviewer diversity within that scope will close.
2. **This is a distinct lens, not a stronger reviewer.** The pass that caught it was same-model-family as the authoring chain — it added no vendor independence. What it added was *scope* (the whole chain at once) and *framing* (asked what the known-defect list omits, rather than asked to find defects). The repo's own contemporaneous record warns against drawing the wrong lesson here: *"a single deep reviewer remains exposed to its own family's blind spots — which is why author-exclusion still binds and why [it] must not become a substitute for cross-vendor votes"* (#1082). The finding is about *coverage scope*, not about model strength.

## Provenance

Run 2026-07-29 as a manual design-chain consistency check, recorded verbatim at
`research/sessions/2026-07-29-fable-design-chain-consistency-check.md`. It self-describes as the first real exercise of the mechanism proposed in **#1078** (cross-vendor design-chain panel: review spec + ADR + technical design + decomposition together), run deliberately out of process. Comparative result and the confound analysis are recorded in **#1082**; the related observation that governing artifacts receive less review than code is **#1079**.

Directly motivated the completeness lens in **ADR-033** (dual-lens spec-review gate), which makes a whole-bundle coverage pass a required participant at the spec-phase hold point — see that ADR for how the lens is bounded, and in particular why a same-family lens can never by itself discharge a hold point.

**Evidentiary limitation, stated deliberately:** this is n=1 and confounded — the pass ran *last*, after three others had already removed the defects they were capable of finding, so its unique yield is partly an artifact of ordering. It is suggestive, not a controlled result.
