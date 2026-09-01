# Finding: An Enabled Control Can Still Not Cover Its Target

**Role:** oversight-mechanism — verifying a control is *on* is not verifying it acts on the artifacts the actor of interest produces

**First observed:** 2026-08-02, session `2026-08-02-triage-mechanism-sandbox-drift.md`

---

## The Finding

Enforcement mechanisms operate on specific artifact *types*. A control can be correctly configured, verifiably enabled, and reported as active while never touching the actor it was adopted to constrain — because that actor produces a different artifact type than the one the control governs.

The verification question is not "is this control enabled?" but **"which objects does this control act on, and does the actor of interest actually produce those objects?"** The first question has an easy, checkable, misleading answer.

### The instance

To close a documented-but-unenforced gate, `required_review_thread_resolution` was to be enabled on the repository's ruleset: no pull request may merge with unresolved review conversations.

That setting governs **review threads** — line-anchored conversations created through GitHub's pull request review machinery.

The HOS overseer posts its findings as **PR conversation comments**, via the issues API (`POST /repos/{o}/{r}/issues/{n}/comments`). The cron prompt instructs it, in those words, to *"post findings as a PR comment."*

Conversation comments are not review threads. They are not resolvable, and the setting does not see them.

So enabling the flag would have gated panel findings, Copilot findings, and human review comments — while leaving **the most prolific automated source of findings on every pull request** entirely unblocking. The setting would have read as active. Coverage would have been silently partial.

The overseer is not naive about the reviews API. It uses it deliberately elsewhere: `POST /pulls/{n}/reviews` with `{"event":"APPROVE"}`, annotated in its own definition as *"this satisfies the branch protection 1-approver requirement."* It knows the distinction where approval is concerned. Findings simply never went through it.

## Why this class is hard to detect

The failure is invisible from every natural vantage point:

- **From configuration:** the setting is on. A config audit passes.
- **From documentation:** the gate is described and now enforced. A doc review passes.
- **From the PR:** findings are visible in the conversation. A human sees them and assumes they are gating.
- **From the audit trail:** the overseer recorded that it posted findings. True.

Only a question that crosses the boundary — *what object type does the enforcement consume, and what object type does the producer emit?* — surfaces it. Nothing prompts that question, because both halves are individually correct.

Aggravating detail from the same session: the repository's protection is implemented as a **ruleset**, so `GET /repos/{o}/{r}/branches/main/protection` returns `404 Branch not protected`. A reasonable verification attempt returns a confidently wrong answer, in the opposite direction.

## Implication for research

Governance audits for agentic systems need an explicit **producer/consumer reconciliation** step: for each control, enumerate the artifact type it acts on, then enumerate the artifact types each governed actor emits, and check the intersection is non-empty for every actor the control names.

This is mechanisable and cheap relative to its yield. It is also the same shape as several other findings from this session — a control reporting success while not doing what it is believed to do — which suggests the reconciliation should be periodic rather than one-off.

Relates to [`unenforceable-rules-need-verification-mechanisms`](unenforceable-rules-need-verification-mechanisms.md): there, a rule had no verification mechanism. Here the mechanism exists, works, and is pointed at the wrong object. The second is worse, because the first at least looks unfinished.

## What changed

- **#1207** — overseer findings must be posted as review comments via `POST /pulls/{n}/reviews`, line-anchored where a location exists, so the mechanism has objects to act on.
- **#1206** — enabled anyway, with an explicit note that it is **not** complete coverage until #1207 lands, so the flag is not mistaken for the control.
- Both issues carry a verification requirement: confirm on a test PR that an unresolved *review thread* blocks merge and an unresolved *conversation comment* does not — rather than trusting the documentation that produced the original assumption.
