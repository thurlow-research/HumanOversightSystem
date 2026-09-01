# Finding: The Deployment Translation Is Author-the-Artifact, Not Execute-the-Action — and Its Missing Precondition Is Author/Executor Separation

**Role:** oversight-mechanism — extending the translation lens from development to deployment

**First observed:** 2026-08-18, analysis session on scoping the dissertation beyond development-time oversight. Derived, not incident-observed — see *Status* below.
**Theoretical basis:** the translation lens (`hos-ports-human-software-engineering-best-practices.md`); authorization/activation separation (`two-key-enable-for-autonomous-systems.md`)

---

## Status

This is a **derived finding, not an observed one.** It applies the translation lens to a surface HOS does not currently govern, and its predictions have not yet been tested against a HOS deployment incident. It is recorded now because the lens identifies the mechanism *and* the failure mode in advance, and because the public incident record already contains the failure this predicts. Treat the mechanism claim as specced, not validated.

---

## The Finding

HOS governs the **development** surface: agents author code, adversarial multi-agent panels review it, deterministic gates and risk-tiered human approval gate the merge. Deployment is a distinct surface, and the incident record shows it is where the most severe agentic failures land.

The translation lens asks, for each established human practice, what its AI-native form is. The relevant human practice for deployment is well settled: **do not run commands manually against production; run validated, version-controlled scripts.** Infrastructure-as-code, runbooks, and CI/CD pipelines are all instances. The practice is decades old and its rationale is not primarily fat-fingering.

The AI-native translation is therefore *not* "let the agent deploy carefully." It is:

> **Agents author and validate deployment artifacts. Execution of those artifacts is deterministic and separately anchored. The AI belongs in the authoring loop, never on the execution path.**

This has a useful consequence for scope: a deployment script is an artifact, so it is **already** in HOS's jurisdiction. It is code, and it is subject to the same adversarial review, deterministic gates, and risk tiering as any other code. Deployment does not require a new oversight mechanism. It requires that the executing boundary be deterministic and that the agent not straddle it.

---

## Why the Human Practice Works (the property to preserve)

The reason manual production commands are unsafe is not mainly typing errors. It is that a manual action:

1. **Leaves no reviewable artifact.** There is nothing to diff, approve, or reject before it happens.
2. **Leaves no reproducible trace.** What actually ran is recoverable only from the actor's account of it.
3. **Collapses authoring and execution into one act.** No one else stands between intent and effect.

Properties (1) and (2) are precisely the two failure modes the incident record shows for agentic deployment. In the Replit case (2025-07), the agent executed destructive commands during a declared code freeze and then misreported the recoverability of the result — an unreviewable action followed by an unreliable account of it. This is the same shape as `reviewer-agents-file-confident-non-reproducing-reports.md` and `self-classification-cannot-gate-the-human-boundary.md`, one surface over: **the actor's own account of what it did is not an oversight artifact.**

Scripting restores (1) and (2). It does not, by itself, restore (3).

---

## The Missing Precondition (what the lens predicts)

Per the corollary in `hos-ports-human-software-engineering-best-practices.md`, every translation must be audited for what the human version implicitly assumed.

"Use validated scripts rather than manual commands" implicitly assumed **the author and the executor are separated** — by time, by review, and usually by person. The script was written, reviewed, merged, and only then run, frequently by someone else or by an unattended pipeline.

An agent that authors a deployment script and then immediately executes it satisfies the letter of the practice and **loses the property entirely.** The artifact exists but nothing independent ever stood between authoring and effect. This is the same class of silent translation failure as the human gate's identity precondition (`human-gate-enforcement-limits.md`): the mechanism looks ported, but the assumption that made it work is absent.

The prediction, therefore: **scripted agentic deployment without an enforced author/executor separation will fail in the same way manual agentic deployment does**, and it will be harder to notice because the presence of a reviewed artifact reads as control.

---

## The Mechanism Already Exists

`two-key-enable-for-autonomous-systems.md` supplies the decomposition. Authorization and activation are distinct concerns, and the structural property that makes Key 2 work is that it **cannot travel with the repo** — a fresh clone is inert by construction.

Mapped onto deployment:

| Concern | Deployment form | Property |
|---|---|---|
| **Authorization** | The deployment artifact: committed, reviewed, risk-tiered, gated | Auditable, durable, diffable |
| **Activation** | Execution of that artifact: operator- or pipeline-anchored, outside agent reach | Structurally unavailable to the authoring agent |

The agent's inability to execute should be **structural, not behavioral** — no production credentials in the authoring environment — for exactly the reason `human-gate-enforcement-limits.md` documents: a behavioral prohibition is auditable but forgeable, and an instruction is not a control. This is the same conclusion the incident record reaches independently: Replit's remediation was dev/prod separation and a planning-only mode, both structural.

---

## What Scripting Does Not Fix

Three limits, recorded so the claim is not overstated:

1. **A validated-but-wrong artifact still destroys production.** The DataTalks.Club incident (2026-02) ran through Terraform — infrastructure-as-code did not prevent the teardown. Reviewability is necessary, not sufficient; destructive plans still need a human gate.
2. **Review of generated deployment artifacts is subject to the same attention deficit as any other review.** If the human rubber-stamps them, the complacency problem returns with added false confidence because it "went through review" (`gates-and-review-are-complementary.md`; the attention evidence in `attention-guarantees-not-fix-mandates.md`).
3. **Infrastructure changes are maintenance-class work.** Per `maintenance-class-changes-carry-higher-agentic-risk-than-generation.md`, refactor and chore invert the human risk pattern (6.72% and 9.35% breaking-change rates vs. 2.89% feat, 2.69% fix). Most infrastructure edits read as maintenance and would receive the lightest scrutiny under a content-type rubric. Deployment artifacts should carry a deterministic floor bump for the same reason.

---

## Implications for Research

1. **Deployment extends the dissertation's scope without a new theory.** The contribution remains translation plus scale. Deployment is the next un-ported practice named in the lens finding's own candidate list (runbooks/on-call, the two-person rule for sensitive ops).
2. **The boundary claim is falsifiable.** "An agent may author and validate deployment artifacts but must not hold the capability to execute them" is testable against the incident record and against a HOS-governed pilot deployment.
3. **The lens predicted the gap before the evidence did.** That the translation corollary identifies author/executor separation as the at-risk precondition, and that the public incidents show exactly that failure, is itself support for the lens as a bug predictor rather than a post-hoc description.

---

## Related findings

- `hos-ports-human-software-engineering-best-practices.md` — the lens this applies, and the source of the audit-the-precondition corollary.
- `two-key-enable-for-autonomous-systems.md` — the authorization/activation decomposition reused here.
- `human-gate-enforcement-limits.md` — why the execution barrier must be structural rather than behavioral.
- `maintenance-class-changes-carry-higher-agentic-risk-than-generation.md` — why deployment artifacts warrant a risk floor bump.
- `self-classification-cannot-gate-the-human-boundary.md` — the actor cannot certify its own boundary; here, its own deployment.
- `gates-and-review-are-complementary.md` — reviewed artifacts still need deterministic gates.
