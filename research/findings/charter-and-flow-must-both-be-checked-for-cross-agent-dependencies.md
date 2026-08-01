# Finding: A new mechanism that depends on an existing agent must be checked against that agent's charter *and* its actual flow — these fail separately, and three passes missed both

**Role:** oversight-mechanism — cross-agent dependency verification in a multi-agent pipeline

**First observed:** 2026-08-01, three occurrences within a single design lineage (ADR-035 → ADR-036)

---

## The Finding

When a design says "then the overseer approves it" or "the worker opens the PR," it is asserting a **capability claim about another agent** — and that claim has two independent failure modes that must be checked separately:

1. **Charter** — is the agent *permitted* to do this? Its `.claude/agents/*.md` definition is a behavioral contract; an agent following its own charter will refuse an action outside it.
2. **Flow** — will the agent's *actual decision procedure* produce the required outcome? An agent may be permitted to act and still route every instance of the case to a human, because the case trips a fail-closed branch nobody considered.

These are orthogonal. Passing one says nothing about the other. In a single design lineage over one session, both failed, at different times, in different directions:

- **Charter failure (ADR-035, AD-16).** The design required the overseer to author the audit PR. `overseer.md:7` — *"Never opens branches or PRs"* — forbids exactly that. An overseer following its own charter would have refused the action the mechanism depended on.
- **Flow failure (ADR-036, TD-VF-036-1).** After the pivot, the design required the overseer to *approve* the audit PR. Nothing forbade it, and all three server-side CI gates were verified to pass natively. But the overseer's own review procedure (`overseer.md:190-245`) fail-closes on a missing validator artifact at step 3b and a register-completeness bounce at 4a — so every audit PR would route to `HUMAN_REQUIRED` and the mechanism would never run unattended, defeating its purpose.

A third instance in the same lineage (ADR-035, AD-15) is the degenerate case: the design specified every *consumer* of an audit PR — approver, gate exception, pre-PR exemption, trigger — while removing the only existing producer, and never noticed nothing created the PR at all.

## Evidence

- All three were missed by the authoring `architect` pass's own verification section, which *did* read the three server-side CI gates in full. Reading the gates is not the same as reading the agent, and the gap is exactly there.
- The charter failure and producer gap were caught by a completeness-lens review; the flow failure was caught by `technical-design` during implementation contracting. **None was caught by adversarial review**, which found six real defects in the same bundle — all of them *inside* the artifact (parsing bugs, truncation bypass, an unrestricted glob), none of them about another agent's behavior.
- The flow failure is the subtlest: the design's central claim ("the overseer approves, so the gate passes natively") was *verified true at the CI layer* and still wrong in effect, because a different layer — the agent's own procedure — blocked it first. Verifying the mechanism you named does not verify the mechanism that actually decides.

## Why It Matters

Multi-agent pipelines make capability claims about other agents constantly, in prose, without any mechanical check. `.claude/agents/*.md` files are treated as documentation, but they are **executable behavioral contracts** — an agent reads its own charter at runtime and acts on it. A design that contradicts one is not merely inaccurate; it specifies a mechanism that cannot run.

The flow half is worse than the charter half, because charter violations are at least greppable — the constraint is a sentence in a file. Flow failures live in a decision procedure's fail-closed branches, are conditional on the specific case, and produce a *plausible* outcome (`HUMAN_REQUIRED` is a legitimate result, not an error) — so they surface as "the mechanism mysteriously never runs unattended" rather than as a failure.

This is the same family as the repo's recurring "gate documented as executing with nothing executing it" defect (`ADR-033` VF-1/VF-2/VF-3; issues #1128, #1131) — a documented mechanism whose real-world precondition was never verified — but one level up: the unverified precondition is *another agent's behavior* rather than a script's existence.

**The general rule:** any design step of the form "then agent X does Y" needs two checks before it is load-bearing — *is X permitted to do Y* (charter) and *will X's decision procedure actually produce Y for this case* (flow). Both, separately. Neither implies the other.

## Implications for Research

This is a mechanizable check, and worth building rather than remembering: for every agent named in a design document, extract the claimed action, then verify it against that agent's charter constraints and its decision-procedure branches. It is the agent-level analogue of the documentation-reality drift detector already proposed in #1123, and the recurrence rate — three times in one lineage, by capable agents that had already read the relevant files — argues that discipline alone does not close it.

A related observation worth testing: the failures clustered at *handoff points* between agents, not inside any agent's own scope. That is where each agent's verification stops — each checked its own artifacts thoroughly and assumed the neighbour's behavior.

## Related findings

- `agent-availability-is-a-setup-property-not-a-runtime-property.md` — the same class at the infrastructure layer (an agent that isn't dispatchable), where this is an agent that is dispatchable but won't act
- `enforcement-gate-scope-gap.md`
- `unenforceable-rules-need-verification-mechanisms.md`
- `documentation-currency-as-safety-property.md` — a charter that no longer describes actual behavior is this failure in latent form
