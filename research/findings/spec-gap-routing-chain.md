# Finding: Spec-Gap Escalation Must Enter at the Lowest Capable Authority

**First observed:** 2026-06-12, feedback loop design session (issue #21)
**Documented in:** `docs/AGENTS.md` — spec-gap routing; `docs/OVERSIGHT-RUNBOOK.md` — Cross-Role Feedback Loops

---

## The Finding

When a build-phase agent (coder, security-reviewer, privacy-reviewer) discovers a gap in the spec — an underdetermined requirement, a missing threat model, an unspecified compliance boundary — there is a tempting short circuit: route it directly to pm-agent via a `spec-gap` issue and halt. pm-agent owns the spec; why go anywhere else?

The short circuit has a failure mode. Many apparent spec gaps are not actually requirements questions — they are implementation design questions or architectural questions that can be resolved without touching the spec at all. A coder hitting two valid interpretations of a booking rule may simply need technical-design to clarify the implementation contract. A security-reviewer finding a missing auth boundary may need technical-design to add it to the design, not pm-agent to rewrite the requirement.

If every apparent spec gap goes directly to pm-agent, pm-agent becomes a bottleneck for questions it shouldn't be answering, the spec accumulates clarifications that are really design details, and the design chain loses its ability to resolve things within its own authority.

**The correct routing chain:**

```
coder / security-reviewer / privacy-reviewer
  → technical-design    (can it be resolved at the implementation design level?)
      → architect        (does it require an architectural decision?)
          → spec-gap issue for pm-agent   (only if it requires a product decision)
```

**The principle:** enter at the lowest authority that can resolve it; escalate only if that level cannot.

---

## Why This Ordering

**technical-design as first receiver** makes sense because it owns the implementation contract — the translation layer between the spec and the code. Many apparent spec gaps are really gaps in the implementation contract: the spec is clear about *what* the product should do, but the implementation contract hasn't specified *how* precisely enough. technical-design can fill that gap without touching the spec.

**architect as second receiver** makes sense because some implementation design gaps have architectural implications — the resolution requires a decision about system structure that technical-design cannot make unilaterally. But the question is still technical, not product.

**pm-agent as final receiver** only when the gap genuinely requires a product decision — a choice about user behavior, business rules, or scope that cannot be answered by looking at the implementation. By the time a gap reaches pm-agent via this chain, it has already been confirmed as a product question, not a design or architecture question.

---

## The ux-designer parallel

The same principle applies to the design pack loop. When `ui-reviewer` finds a gap in the design pack, it escalates to `ux-designer` (the authority on the design pack), not to `pm-agent` (the authority on product requirements). Only if `ux-designer` determines the gap implies a product-scope question does it consult `pm-agent`. The routing enters at the lowest capable authority.

---

## What goes wrong without this routing

**Spec falsification risk.** If agents short-circuit to pm-agent for every apparent gap, pm-agent may update the spec to match what the code did, rather than what the product should do. This is spec falsification — the spec becomes a record of implementation choices rather than an authority over them.

**pm-agent bottleneck.** pm-agent becomes a clearing house for design questions it lacks the context to answer well. It sees "coder hit ambiguity at line 84" without the implementation context that technical-design has. The resolution quality degrades.

**Design chain authority erosion.** If every design question bypasses the design chain, the design chain loses its role as the authoritative layer between product intent and implementation. Over time, it atrophies. Agents stop treating technical-design and architect as authorities because they're never the ones that actually unblock things.

---

## Loop exits

The routing chain requires explicit loop exits at each level:
- technical-design ↔ architect: maximum 3 rounds, then escalate to human
- architect → pm-agent: creates `spec-gap` issue; does not continue iterating
- pm-agent: updates spec, notifies blocked agent and design chain

Without loop exits, a disagreement at any level loops indefinitely.

---

## Implications for Research

1. **Authority hierarchies in multi-agent systems need explicit routing rules.** Without defined escalation chains, agents default to the highest available authority (human or pm-agent), which creates bottlenecks and degrades the quality of decisions made at inappropriate levels.

2. **Apparent gaps are often misclassified.** A "spec gap" observed by a coder is frequently a "design gap" or "architecture gap." The routing chain is a classification mechanism: by passing through technical-design and architect first, gaps are correctly classified before reaching the authority that should answer them.

3. **Short-circuit escalation is a smell.** When an agent escalates past its natural first receiver to a higher authority, it is usually a signal that the first receiver's authority is not well-defined or not trusted. Robust multi-agent pipelines require that each level's authority is clear enough that agents naturally route to it first.

---

## Related findings

- `unenforceable-rules-need-verification-mechanisms.md` — the routing chain must be defined in agent files to be followed; prose in a runbook is insufficient
- `issue-vs-pr-thread-routing.md` — the decision about where findings land (issue vs. PR thread) follows the same "lowest appropriate authority" principle
