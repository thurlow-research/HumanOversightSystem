# SPEC-378: Structured Rejection Rationale and Gate Suspension Schema

**Status:** Draft — for architect review
**Issue:** #378
**Author:** pm-agent
**Date:** 2026-06-17

---

## 1. Problem Statement

Watanabe et al. (2026) found that 64.1% of rejected agentic PRs were closed with no explanatory comment. This means the majority of bot-initiated PR rejections leave no machine-readable or human-readable record of *why* the PR was rejected. For an oversight system, this is an audit-trail gap: the decision to not merge is as consequential as the decision to merge, yet only the latter is systematically documented.

HOS already requires zero-reader-context legibility for escalations (the ESCALATE path in `oversight-orchestrator.md` prints structured, numbered items). Gate suspension already requires a human-authorized `contract/gate-suspension.md` file. Neither PR close/reject events nor gate suspensions currently require a structured, machine-readable rationale field. The result:

- A closed PR cannot be queried, categorized, or fed into risk-scoring without unstructured text parsing.
- A gate suspension's `Reason:` prose field cannot be aggregated across projects or flagged by category in automated tooling.
- `audit/oversight-log.jsonl` has no event type for PR rejection rationale, so the audit trail is asymmetric: merges are logged, rejections are not.

---

## 2. Scope

This spec covers:

1. **Overseer protocol** (`oversight-orchestrator.md`): when the overseer closes or rejects a PR (does not merge), it must write a structured rationale comment to the PR before closing.
2. **Contract amendment** (`contract/OVERSIGHT-CONTRACT.md`): the contract must document the PR-rejection comment format as a required protocol step, and the `pr-rejection` audit-log event type.
3. **Gate-suspension schema** (`contract/gate-suspension.template.md`): the suspension file must gain a `reason_category` field alongside the existing prose `Reason:` field.
4. **Audit log** (`audit/oversight-log.jsonl` event catalog): a new `pr-rejection` event type must be added to the catalog.

This spec does NOT cover:

- The inner-loop reviewer rejection flow (security-reviewer, code-reviewer, etc. issuing `Status: ESCALATED`). Those roles write to the sign-off register, not to GitHub PR comments.
- Human-initiated PR closes. The structured comment requirement applies only to bot-initiated closes (where the acting agent is `oversight-orchestrator` or a bot acting under the overseer protocol).
- Requiring AI to generate the rationale text. The rationale fields are templated; the agent fills in a category enum and a human-authored or templated one-sentence summary.
- Changes to the merge path. The handoff document, panel context, and merge-authority matrix are not affected.

---

## 3. Requirements

### R1 — Overseer writes structured rationale comment before closing a PR

When the overseer closes or rejects a PR (i.e., takes any action that closes a PR without merging it), it must:

**R1.1** Post a GitHub comment to the PR using `gh pr comment` with the following format before issuing the close command:

```markdown
## HOS Rejection Rationale
**Reason category:** <FINDINGS_NOT_RESOLVED | ESCALATION | HUMAN_REQUIRED | OTHER>
**Summary:** <one sentence — what the decisive blocker was>
**Items requiring action:** <bulleted list of unresolved items, or "none — closed definitively">
```

**R1.2** The `Reason category` field must use one of the four enumerated values exactly:
- `FINDINGS_NOT_RESOLVED` — one or more reviewer findings, compliance failures, or second-review findings remain unresolved after the maximum iteration budget.
- `ESCALATION` — the oversight-evaluator issued ESCALATE and the human did not resolve it within the step's authorized window.
- `HUMAN_REQUIRED` — a human gate was required (CRITICAL step, merge-authority matrix) and authorization was not provided.
- `OTHER` — any close reason not fitting the above; the `Summary` sentence must make the reason unambiguous.

**R1.3** The comment must be posted and confirmed (non-zero exit from `gh pr comment` treated as a hard stop) before the close command (`gh pr close`) executes. If posting the comment fails, the overseer must not close the PR silently — it must halt and print the failure to the console for human attention.

**R1.4** The structured comment is distinct from and additive to the existing ESCALATE console output. The console output is for the local session; the PR comment is the durable artifact.

**R1.5** This requirement applies only when the overseer is closing a PR it previously opened (identified by the `[AI: oversight-orchestrator]` title prefix). The overseer must not post a rejection comment to human-opened PRs.

### R2 — Gate-suspension schema gains `reason_category`

**R2.1** The `contract/gate-suspension.template.md` file must add a `reason_category` field immediately after the `Reason:` field. The value must be one of:

```
reason_category: EMERGENCY | PLANNED_MAINTENANCE | FALSE_POSITIVE | OTHER
```

**R2.2** Field semantics:
- `EMERGENCY` — a blocking production issue requires bypassing the gate to unblock a critical fix; the suspension is expected to be very short-lived.
- `PLANNED_MAINTENANCE` — a known, scheduled period where the gate would produce expected failures (e.g., a database migration window, a transient third-party outage).
- `FALSE_POSITIVE` — the gate is consistently triggering on a known non-issue in this project's codebase; a fix or gate rule update is planned.
- `OTHER` — any suspension reason not fitting the above; the prose `Reason:` sentence must make the reason unambiguous.

**R2.3** The `reason_category` field is required in any new gate-suspension file. Existing files without it (created before this spec is implemented) are grandfathered; the oversight-evaluator emits a COMPLIANCE WARN (not FAIL) for a suspension file missing `reason_category`, to allow projects to migrate without breaking existing brownfield remediations.

**R2.4** The `gate-suspended` audit-log event (already in the catalog) must include `reason_category` as a key field alongside the existing `gate`, `step`, `authorized_by`, and `suspension_file` fields.

**R2.5** Agents must not create or modify `contract/gate-suspension.md`. This is an existing invariant. R2 does not change it — the `reason_category` field is set by the human who creates the file.

### R3 — oversight-log.jsonl records the rationale event

**R3.1** A new event type `pr-rejection` must be added to the audit-log event catalog in `contract/OVERSIGHT-CONTRACT.md` §6a.

**R3.2** The `pr-rejection` event schema:

```json
{
  "event": "pr-rejection",
  "timestamp": "<ISO-8601>",
  "pr": "<PR number or URL>",
  "step": "<step id>",
  "reason_category": "FINDINGS_NOT_RESOLVED | ESCALATION | HUMAN_REQUIRED | OTHER",
  "summary": "<the same one-sentence summary posted to the PR comment>",
  "agent": "oversight-orchestrator",
  "comment_posted": true
}
```

**R3.3** The overseer must append the `pr-rejection` event to `audit/oversight-log.jsonl` after the PR comment is confirmed posted and before the close command executes. The sequence is: (1) post comment, (2) confirm comment posted, (3) append audit event, (4) close PR.

**R3.4** If the audit-log append fails, the overseer must not proceed to close the PR. It must halt and print the failure. The audit log is append-only and committed; a missing log entry is an audit-trail gap.

---

## 4. Acceptance Criteria

**AC1 — PR close generates a structured comment.**
Given the oversight-orchestrator has opened a PR and subsequently determines it must close the PR without merging, when the close action executes, then a `## HOS Rejection Rationale` comment exists on the PR with a valid `reason_category` enum value, a non-empty `Summary:` sentence, and an `Items requiring action:` field before the `gh pr close` command is issued.

**AC2 — Gate suspension file with `reason_category` is accepted; file without it emits a warning not a failure.**
Given a new `contract/gate-suspension.md` that includes `reason_category: EMERGENCY` (or any valid enum value), when the oversight-evaluator Phase 1 runs, then the gate-suspension compliance check passes without warning. Given an existing `contract/gate-suspension.md` that lacks `reason_category`, when the oversight-evaluator runs, then it emits exactly one COMPLIANCE WARN (not a COMPLIANCE FAIL) and continues evaluation.

**AC3 — PR rejection is logged in the audit trail.**
Given the overseer posts a rejection comment and closes a PR, when `audit/oversight-log.jsonl` is read, then it contains a `pr-rejection` event with matching `pr`, `step`, `reason_category`, and `summary` fields, and `"comment_posted": true`. The event timestamp falls between the PR comment timestamp and the PR close timestamp.

---

## 5. Non-Requirements

The following are explicitly out of scope for this spec:

**NR1 — Human-initiated PR closes are not covered.** If a human closes a PR manually (via GitHub UI or `gh pr close` run by a human), no structured comment is required. The requirement applies only when the acting agent is `oversight-orchestrator` operating under the bot-initiated close path.

**NR2 — AI-generated rationale text is not required.** The `Summary:` field is a templated one-sentence description. The overseer fills it from the evaluator's ESCALATE output or from the specific compliance failure list. No language model generation step is required — the information already exists in the evaluation artifact.

**NR3 — Inner-loop reviewer rejections are not covered.** `security-reviewer`, `code-reviewer`, and other base-team agents write `Status: ESCALATED` to the sign-off register. That is their existing rejection artifact. This spec does not add a PR comment requirement to those agents.

**NR4 — Retroactive logging of closed PRs is not required.** The `pr-rejection` audit event is written at close time going forward. Closed PRs predating this implementation are not backfilled.

**NR5 — The merge path is not changed.** PROCEED and CONDITIONAL_PROCEED flows in the orchestrator are not affected. The structured comment requirement fires only on the close path.

**NR6 — Gate re-enable log is not changed.** The re-enable log table in `contract/gate-suspension.md` is not modified by this spec. Re-enable events continue to be documented as prose table rows by the human.

---

## 6. Affected Artifacts

| Artifact | Change type | Summary |
|---|---|---|
| `contract/OVERSIGHT-CONTRACT.md` §3 | Additive | Document that gate-suspension `reason_category` is required in new files; WARN behavior for legacy files |
| `contract/OVERSIGHT-CONTRACT.md` §6a | Additive | Add `pr-rejection` event to the audit-log event catalog |
| `contract/gate-suspension.template.md` | Additive | Add `reason_category` field with enum options and comment |
| `.claude/agents/oversight-orchestrator.md` | Additive | Add close path: post structured comment, append audit event, then close |

No new files are created by the implementation. No existing required fields are renamed or removed. Contract version is not bumped (additive-only change per §8).
