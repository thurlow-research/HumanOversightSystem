# Finding: Defining an extension point is itself a discovery mechanism — it forces hidden coupling into the open

**Role:** oversight-mechanism — interface design as an audit of existing architecture

**First observed:** 2026-08-01, while converting HOS's audit-recording from a hard-wired git/PR mechanism into a swappable extension point (ADR-036)

---

## The Finding

HOS's audit log had been running for months as a single, obvious thing: overseer appends records, they end up in `audit/`. Three separate design passes had specified mechanisms *around* it — a bypass-actor design, an approval-bot design, a predicate that validated its contents — and none of them noticed that the audit log was silently doing **two unrelated jobs**.

It only surfaced when someone asked a different question: *what would a different backend have to implement?*

The moment the requirement became "a WORM store or a SIEM must be able to satisfy this contract," the overload became unavoidable. `oversight-evaluator`, `step_range.sh`, and `audit_conditional_proceed.sh` all **read records back** to resolve per-step base/head SHAs from `step-head`/`step-head-final` markers. That is operational control-flow state, not audit-of-record. A write-only backend — the entire point of the abstraction — would have silently broken step resolution in the build pipeline.

The coupling had always been there. What changed was the question. "Is this correct?" doesn't surface it, because the coupling *is* correct as long as there's exactly one implementation. "Could something else implement this?" surfaces it immediately, because the two jobs have incompatible requirements: one needs query-back, the other needs only append.

## Evidence

- The overload survived: the original hard-wired design, `ADR-035` (approval-bot), `TECHNICAL-DESIGN-035`, and a two-lens adversarial + completeness panel review of that bundle. None asked what a non-git backend would need, so none found it.
- It was found by `pm-agent` in the first pass of `REQUIREMENTS-036`, specifically while answering the contract question *"does anything read the audit log back?"* — a question that only exists because the interface was being defined.
- The resolution (`ADR-036` AD-2) is a tier boundary with an explicit test: *does HOS read this record back for control flow?* Yes → HOS-owned local tier, never delegated. No → write-only swappable backend. The deciding conformance proof is that a **write-only stub** must be able to implement the contract; if it can't, a storage assumption has leaked in.

## Why It Matters

The usual argument for extension points is future flexibility — you might want a different backend someday. This finding is that the **immediate** payoff can be larger than the deferred one: defining the interface audits the existing implementation, whether or not a second implementation is ever built.

That reframes when it's worth doing. "We only have one backend, so an abstraction is premature" assumes the abstraction's value is optionality. But the act of specifying what a *second* implementation would need is a structured way of asking "what does the current one actually depend on?" — and that question finds coupling that correctness review structurally cannot, because coupling isn't incorrect until something else has to satisfy the same contract.

**The general rule:** when a subsystem has exactly one implementation, its accidental couplings are invisible, because nothing distinguishes essential behavior from incidental behavior. Writing the interface — even for a backend nobody plans to build — separates them. The write-only stub is the sharpest version of this: an implementation deliberately too weak to accommodate any leak, which fails loudly the moment one exists.

## Implications for Research

This is a cheap, repeatable audit technique with a concrete artifact (the stub) and a binary outcome, distinct from review-based methods. It's worth testing whether it generalizes to other single-implementation subsystems in an AI-oversight pipeline — the risk-scoring path, the review-dispatch path — where the same "only one implementation, so coupling is invisible" condition holds.

It also sharpens a limitation of adversarial review specifically. A red-team asks *"how could this be wrong or gamed?"* Accidental coupling is neither: it's correct, unexploitable, and fatal only to a change that hasn't been proposed yet. That may be a third defect class alongside the adversarial/completeness split in `ADR-033` — not a contradiction within the artifact, and not an absence relative to what it should cover, but a *dependency that only becomes visible under a hypothetical*.

## Related findings

- `refactor-to-reusable-is-a-quality-audit.md` — the same mechanism in the code-structure domain; this finding extends it from refactoring to interface definition
- `omission-class-documentation-bugs.md` — a related class of defect invisible to contradiction-checking
- `oversight-blindspot-documentation-discoverability.md`
