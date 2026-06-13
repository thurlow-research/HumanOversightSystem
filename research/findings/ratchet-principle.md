# Finding: The Ratchet Principle — Automation May Only Tighten Oversight, Never Loosen It

**First observed:** 2026-06-13, naming the invariant behind suspension auto-removal  
**Status:** cornerstone principle — enshrine in the principles document

---

## The Principle

> **Any automated change to the level of human oversight may only increase it. Reducing oversight always requires an explicit human decision.**

Like a mechanical ratchet, the system can turn freely in one direction (toward more checking) and is locked against the other (toward less). Automation is permitted to tighten the gate; only a human may loosen it.

This is the single most important safety invariant in an AI governance system that automates its own operation. An automated system that can reduce its own oversight can, by definition, escape it — not through malice, but through the ordinary tendency of any system to find the path of least resistance. The ratchet removes that path.

---

## It Was Already Here, Unnamed, in Three Places

The principle was implicit in the framework before it was stated. Three mechanisms built independently all obey it:

1. **risk-assessor tier validation.** The risk-assessor may *raise* a change's risk tier freely (more scrutiny) but may *lower* it only when a human-authored `human-tier-override.md` exists. Raising = automated tightening = allowed. Lowering = loosening = requires a human. (`risk-assessor.md`)

2. **Gate suspension authorship.** A gate suspension *loosens* oversight (a check stops blocking). Only a human may create one — agents are explicitly prohibited from writing `gate-suspension.md`. Loosening requires a human. (`oversight-evaluator.md`, brownfield mechanism)

3. **Suspension auto-removal.** Auto-removal *re-enables* a suspended gate (the check resumes blocking). This is the system overriding a human-authorized decision — and it is safe precisely because it tightens. The system may auto-re-enable; it may never auto-suspend. (design issue #62)

Three mechanisms, one principle. Naming it makes the consistency visible and gives future agents a single rule to check any new automation against: *does this automated action reduce oversight? If yes, it must require a human.*

---

## Why "Never Ever" Is the Right Strength

The temptation to allow narrow exceptions ("the system may auto-lower the tier when it's *really sure* the change is trivial") is exactly the failure mode to resist. The value of the ratchet is that it has no teeth on the loosening side at all. The moment a single automated loosening path exists, it becomes:

- **An attack surface** — anything that can trigger that path can reduce oversight.
- **A drift vector** — under time pressure, the "really sure" threshold erodes.
- **An audit hole** — a reduction in oversight that no human signed is indistinguishable, after the fact, from one that should never have happened.

A ratchet with one weak tooth is not a ratchet. The principle is only load-bearing if it is absolute.

---

## What Counts as "Loosening"

Loosening is any automated action that reduces the probability a defect is caught or a human is involved:

- Lowering a risk tier
- Suspending or waiving a gate or reviewer
- Reducing a required-signoff list
- Relaxing a threshold (coverage, mutation, contrast)
- Marking something N/A that would otherwise be reviewed
- Dismissing a finding without resolution

Each of these, done automatically, would let the system reduce its own scrutiny. Each must require a human.

Tightening — raising a tier, re-enabling a gate, adding a reviewer, flagging low confidence, escalating — may always be automated. The asymmetry is the whole point.

---

## Implications for Research

1. **Self-governing automation needs a directional invariant.** A system that governs its own operation must be structurally incapable of relaxing that governance without external (human) input. The ratchet principle is that structural constraint. It is more fundamental than any individual gate, because it constrains what the *automation itself* is allowed to do to the gates.

2. **The principle is checkable.** Because "loosening" is enumerable, a validator can in principle audit every automated decision path in the framework and confirm none of them reduce oversight without a human artifact. This turns a philosophical commitment into a verifiable property — exactly the move HOS makes everywhere (rules need verification mechanisms).

3. **It unifies otherwise-separate safety mechanisms.** Tier floors, suspension authorship, and auto-removal looked like three unrelated rules. They are one rule. A framework that recognizes this can apply it consistently to every future mechanism instead of re-deriving it each time — and can catch violations by asking a single question of any new automation.

4. **It is the precondition for trusting automation with more.** The reason auto-removal of suspensions is acceptable at all — the reason the system can be trusted to override a human's suspension — is that it can only override in the safe direction. The ratchet is what makes increasing automation compatible with maintaining oversight: you can let the machine do more, because the one thing it structurally cannot do is reduce the human's control.

---

## Related findings

- `unenforceable-rules-need-verification-mechanisms.md` — the ratchet is only real if loosening paths are mechanically blocked, not just discouraged
- `brownfield-governance-adoption.md` — suspension is the human-authorized loosening; auto-removal is the automated tightening; together they obey the ratchet
- `jidoka-reactive-pipeline.md` — Jidoka stops the line on a defect (tightening); it never auto-continues past an unresolved one (which would be loosening)
- `human-gate-enforcement-limits.md` — the ratchet is why even imperfect human-gate enforcement is worth having: the gates can only be loosened by a human, however that human is authenticated
