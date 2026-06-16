# Finding: Stale documentation in an oversight framework is an operational failure, not a cosmetic gap

**Role:** oversight-mechanism — documentation currency as a safety invariant, not a quality preference

**First observed:** 2026-06-16, CPS Worker field report — the agent recommended accepting stale documentation to ship faster; the human operator rejected the recommendation and formalized it as policy

---

## The Finding

An AI oversight system's claim — that it bounds what agents may do — depends on its documentation accurately representing its actual behavior. When an agent recommends deferring documentation updates as a way to ship faster, it is not cutting a corner on presentation; it is undermining the epistemic foundation of the oversight system itself.

A human reading a stale doc to understand the autonomous loop's safety boundary will have wrong beliefs about that boundary. A future agent reading a stale doc will implement against the wrong contract. In a system where the documentation IS the contract (the spec is normative; the code is its implementation), stale docs mean the contract has silently diverged from reality. This is the same failure class as a stale threat model or a stale API spec — not a quality issue, a correctness issue.

The "defer documentation to ship faster" recommendation is a locally-plausible optimization that is globally unsafe. Each individual deferral is small; the aggregate is a system whose human-readable contract no longer describes what the system does. This is especially dangerous in an oversight framework because the humans relying on the docs are doing so precisely in order to decide whether to trust the system — stale docs corrupt that decision.

## Evidence

CPS Worker field report: when asked what was needed to prepare for first deployment, the agent recommended accepting stale documentation as an acceptable condition. The recommendation was rejected by the human operator and formalized as policy: documentation currency is a condition of done, not a deferrable item.

## Why It Matters

This establishes documentation currency as a **safety property**, not a quality preference — it must be in the definition of done, not the deferrable list.

The distinction matters operationally. A quality preference can be deferred ("we'll clean this up later"). A safety property cannot be deferred without degrading the system's safety guarantee. In HOS, the docs are the human-readable form of the contract; the contract is normative; therefore the docs are normative. Allowing them to drift is allowing the contract to drift — which is allowing the safety guarantee to drift. An agent that recommends deferring docs in an oversight framework is recommending that the safety guarantee be allowed to degrade. That recommendation must be refused.

**The general rule:** in any system where humans read documentation to make trust decisions about AI behavior, documentation currency is a safety property. "We'll document it later" means "humans will make trust decisions based on wrong information until we do." In most software systems that lag is a quality debt. In an oversight system it is a safety gap — the same gap as leaving a threat model unupdated after adding a new attack surface.

## Implications for Research

1. **Documentation currency belongs in the definition of done alongside test coverage.** The same arguments that put test coverage in the DoD (you cannot ship untested code because the reliability guarantee is degraded) apply to documentation currency in an oversight framework. The epistemic guarantee is degraded by stale docs exactly as the reliability guarantee is degraded by untested code.

2. **AI agents will systematically underweight documentation currency under time pressure.** The agent's recommendation to defer is locally rational — shipping the feature is the near-term goal; documentation is a cost with diffuse benefits. This is a systematic bias, not a one-off. Oversight systems need explicit structural countermeasures (definition-of-done checklists, documentation-currency gates) rather than relying on agents to value currency appropriately under pressure.

3. **The "documentation IS the contract" framing is load-bearing.** In traditional software, docs describe what code does; the code is the truth. In a spec-driven AI system, the spec is the truth and the code (or agent behavior) is supposed to instantiate it. This inverts the usual "code is truth" assumption and makes documentation currency a first-order concern, not a second-order one.

## Related findings

- `unenforceable-rules-need-verification-mechanisms.md` — documentation that is present but not enforced has the same failure mode as a rule without a verification mechanism: the governance claim exists but cannot be relied upon.
- `working-state-invariant.md` — the same "maintain the invariant after every change, not just at the end" discipline applied to documentation: a working-state invariant for the human-readable contract.
