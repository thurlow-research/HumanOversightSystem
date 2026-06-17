# SPEC-378: Structured Rejection Rationale and Gate Suspension Schema

**Status:** REVISED — ready for architect re-review
**Issue:** #378
**Author:** pm-agent
**Date:** 2026-06-17
**Revised:** 2026-06-17

---

## 1. Problem Statement

Watanabe et al. (2026) found that 64.1% of rejected agentic PRs were closed with no explanatory comment. This finding describes *human* reviewers who close PRs without explanation — HOS does not produce that pattern because the overseer never issues `gh pr close`. The overseer's dispositions are AUTO_MERGE, HUMAN_REQUIRED (escalate, leave PR open and labeled `needs-human`), and pr-bounced (return to worker, leave PR open). There is no bot-initiated PR close path in HOS.

The audit-trail gap the finding identifies is real, however, and it applies to HOS's non-merge dispositions: when the overseer posts a HUMAN_REQUIRED escalation comment or emits a pr-bounced event, those events currently carry no structured, machine-readable rationale field. The decision to not merge is as consequential as the decision to merge, yet only the merge path is systematically documented.

HOS already requires zero-reader-context legibility for escalations (the ESCALATE path in `oversight-orchestrator.md` prints structured, numbered items). Gate suspension already requires a human-authorized `contract/gate-suspension.md` file. Neither non-merge disposition comments nor gate suspensions currently require a structured rationale field. The result:

- A HUMAN_REQUIRED escalation or pr-bounced comment cannot be queried, categorized, or fed into risk-scoring without unstructured text parsing.
- A gate suspension's `Reason:` prose field cannot be aggregated across projects or flagged by category in automated tooling.
- `audit/oversight-log.jsonl` has no `reason_category` on non-merge events, so the audit trail is asymmetric: merges are logged with full context, non-merge dispositions are not.

---

## 2. Scope

This spec covers:

1. **Overseer protocol** (`oversight-orchestrator.md`): when the overseer emits a HUMAN_REQUIRED escalation comment or a pr-bounced event, it must include structured rationale fields (`reason_category` enum + `summary` sentence) in that comment or event payload.
2. **Contract amendment** (`contract/OVERSIGHT-CONTRACT.md`): the contract must document the structured rationale fields as a required element of HUMAN_REQUIRED and pr-bounced disposition comments, and the extended audit-log event schema.
3. **Gate-suspension schema** (`contract/gate-suspension.template.md`): the suspension file must gain a `reason_category` field alongside the existing prose `Reason:` field.
4. **Audit log** (`audit/oversight-log.jsonl` event catalog): the existing `pr-bounced` and any HUMAN_REQUIRED audit events must be extended to include `reason_category` and `summary` fields. No new event type is introduced.

This spec does NOT cover:

- The inner-loop reviewer rejection flow (security-reviewer, code-reviewer, etc. issuing `Status: ESCALATED`). Those roles write to the sign-off register, not to GitHub PR comments.
- Human-initiated PR closes. There is no bot-initiated PR close path in HOS; human-initiated closes are not in scope.
- Requiring AI to generate the rationale text. The rationale fields are templated; the overseer fills in a category enum and a one-sentence summary derived from the evaluator's output. No language model generation step is required.
- Changes to the merge path. The handoff document, panel context, and merge-authority matrix are not affected.

---

## 3. Requirements

### R1 — Overseer includes structured rationale in non-merge dispositions

The overseer has two non-merge dispositions: **HUMAN_REQUIRED** (escalation comment posted to the PR, PR left open and labeled `needs-human`) and **pr-bounced** (worker is notified to rework, PR left open). When either disposition fires, the overseer must include structured rationale fields in the disposition comment or event payload.

**R1.1** When posting a HUMAN_REQUIRED escalation comment to the PR, the overseer must include the following structured fields in that comment:

```markdown
## HOS Disposition: Human Review Required
**Reason category:** <FINDINGS_NOT_RESOLVED | ESCALATION | HUMAN_REQUIRED | OTHER>
**Summary:** <one sentence — what the decisive blocker was>
**Items requiring action:** <bulleted list of unresolved items>
```

**R1.2** When emitting a pr-bounced event (returning the PR to the worker), the overseer must include the same structured fields in the bounce comment posted to the PR:

```markdown
## HOS Disposition: Returned for Rework
**Reason category:** <FINDINGS_NOT_RESOLVED | ESCALATION | HUMAN_REQUIRED | OTHER>
**Summary:** <one sentence — what must change before this PR can proceed>
**Items requiring action:** <bulleted list of unresolved items>
```

**R1.3** The `Reason category` field must use one of the four enumerated values exactly:
- `FINDINGS_NOT_RESOLVED` — one or more reviewer findings, compliance failures, or second-review findings remain unresolved after the maximum iteration budget.
- `ESCALATION` — the oversight-evaluator issued ESCALATE and the condition requires human resolution.
- `HUMAN_REQUIRED` — a human gate is required (CRITICAL step, merge-authority matrix) and has not been satisfied.
- `OTHER` — any disposition reason not fitting the above; the `Summary` sentence must make the reason unambiguous.

**R1.4** The structured fields are additive to and must not replace the existing ESCALATE console output. The console output is for the local session; the PR comment is the durable artifact.

**R1.5** This requirement applies only when the overseer is acting on a PR it previously opened (identified by the `[AI: oversight-orchestrator]` title prefix). The overseer must not post structured rationale comments to human-opened PRs.

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

### R3 — oversight-log.jsonl extends existing non-merge events with rationale fields

No new event type is introduced. The existing `pr-bounced` event and any HUMAN_REQUIRED audit event in `audit/oversight-log.jsonl` must be extended to include `reason_category` and `summary` fields.

**R3.1** The `pr-bounced` event schema must be extended to include:

```json
{
  "event": "pr-bounced",
  "timestamp": "<ISO-8601>",
  "pr": "<PR number or URL>",
  "step": "<step id>",
  "reason_category": "FINDINGS_NOT_RESOLVED | ESCALATION | HUMAN_REQUIRED | OTHER",
  "summary": "<the same one-sentence summary posted to the PR comment>",
  "agent": "oversight-orchestrator",
  "comment_posted": true
}
```

**R3.2** When the overseer posts a HUMAN_REQUIRED escalation comment, it must also append an audit event that includes `reason_category` and `summary` fields alongside the existing `pr`, `step`, and `agent` fields. The event type for this audit entry is `human-required` (using the existing event name if one exists in the catalog, or adding it if absent — this is an additive catalog extension, not a new close-path event).

**R3.3** The overseer must append the audit event after the disposition comment is confirmed posted. For pr-bounced: (1) post bounce comment, (2) confirm comment posted, (3) append audit event. For HUMAN_REQUIRED: (1) post escalation comment, (2) confirm comment posted, (3) append audit event.

**R3.4** If the audit-log append fails, the overseer must halt and print the failure. The audit log is append-only and committed; a missing log entry is an audit-trail gap. The overseer must not silently continue after a log failure.

---

## 4. Acceptance Criteria

**AC1 — HUMAN_REQUIRED disposition includes structured rationale.**
Given the oversight-orchestrator has opened a PR and the overseer determines HUMAN_REQUIRED, when the escalation comment is posted to the PR, then the comment contains a `## HOS Disposition: Human Review Required` block with a valid `reason_category` enum value, a non-empty `Summary:` sentence, and an `Items requiring action:` field. The PR is left open and labeled `needs-human`.

**AC2 — pr-bounced disposition includes structured rationale.**
Given the oversight-orchestrator has opened a PR and the overseer emits a pr-bounced event, when the bounce comment is posted to the PR, then the comment contains a `## HOS Disposition: Returned for Rework` block with a valid `reason_category` enum value, a non-empty `Summary:` sentence, and an `Items requiring action:` field. The PR is left open.

**AC3 — Gate suspension file with `reason_category` is accepted; file without it emits a warning not a failure.**
Given a new `contract/gate-suspension.md` that includes `reason_category: EMERGENCY` (or any valid enum value), when the oversight-evaluator Phase 1 runs, then the gate-suspension compliance check passes without warning. Given an existing `contract/gate-suspension.md` that lacks `reason_category`, when the oversight-evaluator runs, then it emits exactly one COMPLIANCE WARN (not a COMPLIANCE FAIL) and continues evaluation.

**AC4 — Non-merge dispositions are logged in the audit trail with rationale fields.**
Given the overseer posts a HUMAN_REQUIRED or pr-bounced comment, when `audit/oversight-log.jsonl` is read, then the corresponding audit event contains matching `reason_category` and `summary` fields alongside `pr`, `step`, and `agent`, and `"comment_posted": true`. The event timestamp follows the PR comment timestamp.

---

## 5. Non-Requirements

The following are explicitly out of scope for this spec:

**NR1 — Bot-initiated PR close is not introduced.** HOS does not have a bot-initiated `gh pr close` path. This spec does not add one. The overseer's non-merge dispositions leave PRs open: HUMAN_REQUIRED labels the PR `needs-human` and waits for human action; pr-bounced returns the PR to the worker for rework. Human-initiated closes (via GitHub UI or CLI) remain outside this spec's scope.

**NR2 — AI-generated rationale text is not required.** The `Summary:` field is a templated one-sentence description. The overseer fills it from the evaluator's ESCALATE output or from the specific compliance failure list. No language model generation step is required — the information already exists in the evaluation artifact.

**NR3 — Inner-loop reviewer rejections are not covered.** `security-reviewer`, `code-reviewer`, and other base-team agents write `Status: ESCALATED` to the sign-off register. That is their existing rejection artifact. This spec does not add a PR comment requirement to those agents.

**NR4 — Retroactive logging of prior dispositions is not required.** The extended event fields apply to events written going forward. Prior `pr-bounced` events in `audit/oversight-log.jsonl` that predate this implementation are not backfilled.

**NR5 — The merge path is not changed.** PROCEED and CONDITIONAL_PROCEED flows in the orchestrator are not affected. The structured rationale requirement fires only on HUMAN_REQUIRED and pr-bounced dispositions.

**NR6 — Gate re-enable log is not changed.** The re-enable log table in `contract/gate-suspension.md` is not modified by this spec. Re-enable events continue to be documented as prose table rows by the human.

---

## 6. Affected Artifacts

| Artifact | Change type | Summary |
|---|---|---|
| `contract/OVERSIGHT-CONTRACT.md` §3 | Additive | Document that gate-suspension `reason_category` is required in new files; WARN behavior for legacy files |
| `contract/OVERSIGHT-CONTRACT.md` §6a | Additive | Extend `pr-bounced` event schema and any HUMAN_REQUIRED audit event to include `reason_category` and `summary` fields; no new event type |
| `contract/gate-suspension.template.md` | Additive | Add `reason_category` field with enum options and comment |
| `.claude/agents/oversight-orchestrator.md` | Additive | Add structured rationale fields to HUMAN_REQUIRED and pr-bounced disposition comments; append extended audit events after comment is confirmed |

No new files are created by the implementation. No existing required fields are renamed or removed. No `gh pr close` call is introduced. Contract version is not bumped (additive-only change per §8).
