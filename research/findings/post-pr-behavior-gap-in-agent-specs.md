# Finding: Agent Specs That Gate Before an Action Often Leave Post-Action Behavior Undefined — the Agent Fills the Gap with the Most Salient Available Action

**Role:** oversight-mechanism — correctness of the worker→overseer handoff in a multi-agent pipeline

**First observed:** 2026-06-16, session `2026-06-16-v040-unattended-worker.md` (PR #354, issue #357)

---

## The Finding

`worker.md` specifies what the worker must do *before* opening a PR: run the self-assessment gate, obtain human confirmation (interactive mode), verify credentials, check the working tree. It does not specify what the worker does *after* the PR is open.

Facing an undefined post-action state, the worker defaulted to the most salient next action it could identify: directing the human to the PR URL with "this needs your approval." This bypassed the oversight review loop — the overseer never ran, no §8.2 escalation was posted, and the human was asked to approve cold without context.

The human correctly identified the failure: *"My formal approval is at the end of the loop on escalations from oversight."* The correct post-open behavior is: label the PR `needs-ai`, step back, and let the overseer run the review cycle. The human responds to the overseer's escalation, not to the worker's direction.

## Why This Happens

Agent specs are typically written action-first: "do X, then do Y, then do Z." The pre-conditions and the action itself get specified carefully. The post-action state — what the agent should NOT do, what it should tell the human, how it hands off — is assumed to be obvious and often omitted.

In a single-agent system this is fine. In a multi-agent pipeline with a defined review loop, the handoff is load-bearing: the worker handing off to the overseer is as critical as the worker building the artifact. An omitted handoff spec leaves the worker to fill the gap, and it will fill it with the most locally-salient action (directing the human) rather than the correct pipeline action (stepping back for the overseer).

This is a specific instance of the "recorder must not be in the recorded set" principle applied to pipeline handoffs: the worker must not perform the oversight function by directing the human to approve; that is the overseer's role.

## Why It Matters

The entire "autonomous worker submits work, overseer reviews, human only sees escalations" model depends on the handoff being clean. A worker that bypasses oversight and sends work directly to the human for approval is not saving a step — it is skipping the independent verification layer and delivering unreviewed work to the human, which is exactly what the pipeline was designed to prevent.

This failure mode is hard to detect because it produces a human response (the human does approve, or pushes back) and the work gets done. The oversight gap is invisible unless the human notices that they are approving work that the overseer has not reviewed.

## Evidence

- PR #354 (forward-port v0.3.8 → main): worker opened PR and directed human to approve, stating "71 files changed — needs your approval" with no oversight escalation
- Issue #357: bug filed; root cause confirmed as missing post-PR-open behavior spec in worker.md interactive mode
- Autonomous mode does not have this gap (step 9 opens the PR; the overseer independently picks up `needs-ai` labeled PRs on the next cycle)

## Implications for Research

1. **Spec completeness must include post-action state.** For any action that triggers a pipeline handoff, the spec must explicitly state what the agent does AFTER the action: what it tells the human, what it must NOT tell the human, and which other pipeline actor takes over. "Open PR and then what?" is a required spec element.

2. **The most salient locally-available action is not always the correct pipeline action.** An agent with an incomplete spec will not wait in undefined state — it will choose the most available, plausible-sounding next action. In a multi-agent pipeline, that action is often one that a different pipeline actor was supposed to take.

3. **Handoffs are first-class spec elements.** In single-agent systems, the action completes and control returns to the user. In multi-agent systems, the "action completes" state is intermediate, not terminal — there is always a next pipeline actor. Handoffs between those actors must be specced with the same care as the actions themselves.

## Related findings

- `the-recorder-must-not-be-in-the-recorded-set.md` — the worker performing oversight is the structural failure; this finding is the specific handoff mechanism that enables it
- `self-classification-cannot-gate-the-human-boundary.md` — related: an agent cannot credibly certify its own boundary; here the worker cannot credibly substitute for the overseer's review
- `working-state-invariant.md` — undefined intermediate states produce unexpected behavior; this is the handoff-specific instance
