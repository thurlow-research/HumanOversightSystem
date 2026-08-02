# Finding: The Countermeasure for AI-Authored Code Is an Attention Guarantee, Not a Fix Mandate

**Role:** oversight-mechanism — forcing acknowledgement and forcing action are different instruments, and the documented failure mode calls for the first

**First observed:** 2026-08-02, session `2026-08-02-triage-mechanism-sandbox-drift.md`

---

## The Finding

Controls that gate merges on review findings come in two kinds, and they are routinely conflated:

- **Attention controls** guarantee that every finding was *looked at* before merge.
- **Outcome controls** guarantee that every finding was *acted on* before merge.

For AI-authored changes, the documented failure mode is not authors refusing to fix things. It is **nobody looking**. The matched countermeasure is therefore an attention guarantee. A fix mandate does not address the failure and imposes a real cost: it removes the legitimate "considered and declined" disposition, converting judgement into compliance and adding rework pressure.

### How the distinction surfaced

GitHub's `required_review_thread_resolution` blocks merge until every review conversation is resolved. This was initially recorded as *stricter than human practice*, on the reasoning that it removes the reviewer's ability to approve over comments they judge non-blocking.

That was wrong, and the correction is the finding. The setting does not constrain the outcome at all:

- The **author** may resolve a thread without changing a line — the "I disagree" disposition — and the PR still merges.
- The **reviewer** may still approve or withhold on whatever basis they choose.

What it removes is the possibility of a finding reaching merge **unread**. The human framing that made this clear:

> Human A MUST at least LOOK at the comment before it can be merged. The parallel approval means that if Human A decides not to make a change now, that's ok.

The two mechanisms are orthogonal, and that is the design:

| Mechanism | Guarantees |
|---|---|
| Thread resolution | The author **looked at** every finding |
| Approval | The reviewer **accepts the disposition**, including "won't fix" |

Neither substitutes for the other. Approval without resolution means signing off on things the author may never have read. Resolution without approval means findings were seen but the reviewer is unsatisfied.

## Why the attention framing matches the evidence

The SLR record describes an attention deficit, not a compliance deficit:

- AI pull requests draw **less** reviewer criticism than human ones despite carrying ~1.87× the semantic redundancy (Huang et al., 2026, `4T5QFWZE`).
- 22.7% of AI-introduced issues survive to repository HEAD (Liu et al., 2026, `9H6FWJME`).
- Low-effort AI pull requests function as a denial-of-service on maintainer attention (Baltes et al., 2026, `B644HQFS`).
- Copilot adoption shifted maintenance onto a shrinking pool of experienced contributors (Xu et al., 2025, `F2C2DWSI`).

Every one of these is a failure of findings being *engaged with*, not of findings being *disputed*. An attention guarantee is cheap, does not constrain engineering judgement, and targets the measured failure directly.

## The limit of the guarantee, and why it was not closed

An attention control guarantees a look, not a fix — and for a bot author, clicking resolve is the cheapest way to clear the board. A silent resolve satisfies the mechanism while conveying nothing to the reviewer.

Human practice tolerates this because social accountability substitutes: the reviewer knows the author and can simply ask. A worker/overseer pair has no such substitute.

The tempting move is to build detection for silent resolves and withhold approval on them. It was proposed, scoped, and **rejected** (#1208, closed not-planned). Two reasons, both worth recording:

1. **The native workflow already covers it.** The reviewer re-reads the diff regardless and can withhold approval if a disposition is unexplained. That is what a human reviewer does. No detection machinery is needed because approval — not resolution — is the gate.
2. **The implementation cost was a signal.** Thread resolution state is not exposed via REST at all (`isResolved` is GraphQL-only), so detection would have required carving an exception out of the overseer's standing REST-only constraint. A control that cannot be built without weakening an existing rule deserves scrutiny before it is built.

The residual observation — that resolutions accompanied by a code change carry more information than those without — was retained as an **observability signal** for the operator dashboard (#1195) rather than converted into a gate. This follows the SLR guidance that adoption must be measured from action data (did the code change) rather than from a resolve action or a model's self-assessment (Sun et al., 2025, `V4IRKSFI`; Karakaya et al., 2026, `5NZ2EDEK`, where LLM judges of comment usefulness scored MCC ≈ 0).

## Implication for research

When specifying a merge gate over review findings, state explicitly which of the two guarantees is intended. The attention guarantee is the more defensible default for agent-authored code: it is matched to the measured failure, it preserves the "considered and declined" outcome that engineering judgement requires, and it is enforceable with existing platform features rather than bespoke machinery.

**Make the disposition visible; do not mandate the outcome.**

## What changed

- **#1206** — `required_review_thread_resolution` enabled, with the rationale recorded as *forced acknowledgement, not forced fix*, and declining-to-fix noted as a legitimate outcome.
- **#1208** — closed not-planned. The bespoke enforcement was declined in favour of the native reviewer-approval path.
- **#1195** — resolutions without a corresponding code change retained as a rate to watch, not a condition to block.
