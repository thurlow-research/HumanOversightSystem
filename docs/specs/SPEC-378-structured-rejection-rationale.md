# SPEC-378: Structured Rejection Rationale and Gate Suspension Schema

**Status:** REVISED — ready for architect re-review (pass 3)
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

1. **Overseer protocol** (`overseer.md`): when the overseer emits a HUMAN_REQUIRED escalation comment or a pr-bounced event, it must include structured rationale fields (`reason_category` enum + `summary` sentence) in that comment or event payload.
2. **Contract amendment** (`contract/OVERSIGHT-CONTRACT.md`): the contract must document the structured rationale fields as a required element of HUMAN_REQUIRED and pr-bounced disposition comments, and the extended audit-log event schema.
3. **Gate-suspension schema** (`contract/gate-suspension.template.md`): the suspension file must gain a `reason_category` field alongside the existing prose `Reason:` field.
4. **Audit log** (`audit/oversight-log.jsonl` event catalog): the existing `pr-bounced` event must be extended by adding `reason_category` and `summary` fields. A new `human-required` event type is added to the catalog for HUMAN_REQUIRED disposition audit entries — this is an additive catalog extension (a new event name for a disposition the overseer already performs but does not yet log structurally).

This spec does NOT cover:

- The inner-loop reviewer rejection flow (security-reviewer, code-reviewer, etc. issuing `Status: ESCALATED`). Those roles write to the sign-off register, not to GitHub PR comments.
- Human-initiated PR closes. There is no bot-initiated PR close path in HOS; human-initiated closes are not in scope.
- Requiring AI to generate the rationale text. The rationale fields are templated; the overseer fills in a category enum and a one-sentence summary derived from the evaluator's output. No language model generation step is required.
- Changes to the merge path. The handoff document, panel context, and merge-authority matrix are not affected.

---

## 3. Requirements

### R1 — Overseer includes structured rationale in non-merge dispositions

The overseer has two non-merge dispositions: **HUMAN_REQUIRED** (escalation comment posted to the PR, PR left open and labeled `needs-human`) and **pr-bounced** (worker is notified to rework, PR left open). When either disposition fires, the overseer must include structured rationale fields in the disposition comment or event payload.

**R1.1** When posting a HUMAN_REQUIRED escalation comment to the PR, the overseer must append `reason_category` and `summary` as additional structured sections to the existing §8.2 escalation comment format. The §8.2 format requires five elements in order: (1) problem + risk + background, (2) options with pros/cons, (3) recommendation + justification, (4) token estimate + blast-radius summary, (5) default-deny deadline if applicable. This requirement adds two fields after those five elements:

```markdown
**Reason category:** <FINDINGS_NOT_RESOLVED | ESCALATION | HUMAN_REQUIRED | OTHER>
**Summary:** <one sentence — what the decisive blocker was>
```

A HUMAN_REQUIRED comment missing the five §8.2 elements is already a malformed escalation per the overseer protocol. A HUMAN_REQUIRED comment missing the two new fields defined here is additionally non-compliant with this spec.

**R1.2** When emitting a pr-bounced event (returning the PR to the worker), the overseer calls `record_pr_bounce()`, which posts a comment, assigns the PR to HOSWorkerTutelare, applies the `needs-ai` label, converts the PR to draft, and appends the audit event. This requirement adds `reason_category` and `summary` fields to that existing `record_pr_bounce()` comment body and its audit event payload — not a separate additional comment. The bounce comment must include:

```markdown
**Reason category:** <REGISTER_GAP | COMPLIANCE_FAILURE | SPEC_AMBIGUITY | OTHER>
**Summary:** <one sentence — what must change before this PR can proceed>
```

These two fields are appended to whatever structured content `record_pr_bounce()` already includes in the comment body.

**R1.3** The `reason_category` field uses a different enum for each disposition type, because the two dispositions describe different procedural states.

For **HUMAN_REQUIRED** escalation comments (R1.1), the field must use one of:
- `FINDINGS_NOT_RESOLVED` — one or more reviewer findings, compliance failures, or second-review findings remain unresolved after the maximum iteration budget.
- `ESCALATION` — the oversight-evaluator issued ESCALATE and the condition requires human resolution.
- `HUMAN_REQUIRED` — a human gate is required (CRITICAL step, merge-authority matrix) and has not been satisfied.
- `OTHER` — any disposition reason not fitting the above; the `Summary` sentence must make the reason unambiguous.

For **pr-bounced** comments via `record_pr_bounce()` (R1.2), the field must use one of:
- `REGISTER_GAP` — one or more required sign-off register entries are absent or missing required fields; the worker must complete the register before the PR can re-enter the overseer queue.
- `COMPLIANCE_FAILURE` — the register or evaluator compliance check identified a concrete failure (e.g. missing human-authorization artifact, failing gate result, N/A invalidated); the specific check_id(s) appear in the `failures` field of the audit event.
- `SPEC_AMBIGUITY` — a procedural requirement could not be evaluated because the spec is ambiguous on the point; the worker should seek clarification before reworking.
- `OTHER` — any bounce reason not fitting the above; the `Summary` sentence must make the reason unambiguous.

The pr-bounced enum is distinct from the HUMAN_REQUIRED enum because a bounce is a procedural return to the worker (the `failures` field carries the specific check_id list); it is not a gate-block or an escalation to a human.

**R1.4** The structured fields are additive to and must not replace the existing ESCALATE console output. The console output is for the local session; the PR comment is the durable artifact.

**R1.5** This requirement applies only when the overseer is acting on a PR it previously opened (identified by the `[AI: overseer]` title prefix). The overseer must not post structured rationale comments to human-opened PRs.

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

### R3 — oversight-log.jsonl records rationale fields on all non-merge dispositions

The existing `pr-bounced` event is extended by adding `reason_category` and `summary` fields. A new `human-required` event type is added to the catalog for HUMAN_REQUIRED dispositions (see §2.4 and R3.2 for rationale). Both events carry the same two new fields so that all non-merge dispositions are queryable and categorizable in the audit trail.

**R3.1** The existing `pr-bounced` event in `audit/oversight-log.jsonl` (emitted by `overseer` via `record_pr_bounce()`) must be extended by adding two fields: `reason_category` and `summary`. The existing fields — `pr`, `cid`, `bounce_number`, `failures` (check_id list), `assigned_to`, `repo`, `timestamp` — are not changed. The extended schema is:

```json
{
  "event": "pr-bounced",
  "pr": "<PR number or URL>",
  "cid": "<worker correlation id>",
  "bounce_number": "<integer>",
  "failures": ["<check_id>", "..."],
  "assigned_to": "<HOSWorkerTutelare account>",
  "repo": "<owner/repo>",
  "timestamp": "<ISO-8601>",
  "reason_category": "REGISTER_GAP | COMPLIANCE_FAILURE | SPEC_AMBIGUITY | OTHER",
  "summary": "<the same one-sentence summary included in the bounce comment>",
  "comment_posted": true
}
```

The `reason_category` value must match the value written into the bounce comment (R1.2). The `summary` value must match the summary sentence in the bounce comment.

**R3.2** When the overseer posts a HUMAN_REQUIRED escalation comment, it must also append an audit event to `audit/oversight-log.jsonl`. The `human-required` event type does not currently exist in the OVERSIGHT-CONTRACT.md §6a catalog; this spec adds it as an additive catalog extension. The event captures the structured rationale for a disposition that the overseer already performs (label `needs-human` + escalation comment) but does not yet log as a discrete audit event. The schema for this new event is:

```json
{
  "event": "human-required",
  "pr": "<PR number or URL>",
  "step": "<step id>",
  "reason_category": "FINDINGS_NOT_RESOLVED | ESCALATION | HUMAN_REQUIRED | OTHER",
  "summary": "<the same one-sentence summary appended to the §8.2 comment>",
  "agent": "overseer",
  "timestamp": "<ISO-8601>",
  "comment_posted": true
}
```

The `reason_category` and `summary` values must match what was appended to the §8.2 escalation comment (R1.1). The contract's §6a audit-log event catalog must be updated to include this event type.

**R3.3** The overseer must append the audit event after the disposition comment is confirmed posted. For pr-bounced: (1) post bounce comment, (2) confirm comment posted, (3) append audit event. For HUMAN_REQUIRED: (1) post escalation comment, (2) confirm comment posted, (3) append audit event.

**R3.4** If the audit-log append fails, the overseer must halt and print the failure. The audit log is append-only and committed; a missing log entry is an audit-trail gap. The overseer must not silently continue after a log failure.

---

## 4. Acceptance Criteria

**AC1 — HUMAN_REQUIRED disposition includes structured rationale.**
Given the overseer has opened a PR (identified by an `[AI: overseer]` title prefix) and determines HUMAN_REQUIRED, when the §8.2 escalation comment is posted to the PR, then the comment includes a `reason_category` field with a valid HUMAN_REQUIRED enum value and a non-empty `summary` sentence appended after the five §8.2 required elements. The PR is left open and labeled `needs-human`.

**AC2 — pr-bounced disposition includes structured rationale.**
Given the overseer has opened a PR and calls `record_pr_bounce()`, when the bounce comment is posted to the PR, then the comment includes a `reason_category` field with a valid pr-bounced enum value (`REGISTER_GAP | COMPLIANCE_FAILURE | SPEC_AMBIGUITY | OTHER`) and a non-empty `summary` sentence. The PR is left open, assigned to HOSWorkerTutelare, labeled `needs-ai`, and converted to draft — the existing `record_pr_bounce()` behavior. No additional separate comment is posted.

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
| `contract/OVERSIGHT-CONTRACT.md` §6a | Additive | Extend `pr-bounced` event schema with `reason_category` and `summary` fields; add new `human-required` event type to the catalog |
| `contract/gate-suspension.template.md` | Additive | Add `reason_category` field with enum options and comment |
| `.claude/agents/overseer.md` | Additive | Add `reason_category` and `summary` fields to `record_pr_bounce()` comment body and to the §8.2 HUMAN_REQUIRED escalation comment; append extended audit events after comment is confirmed |

No new files are created by the implementation. No existing required fields are renamed or removed. No `gh pr close` call is introduced. The `human-required` event type is a new catalog entry (additive — the disposition already exists, the audit event does not). Contract version is not bumped (additive-only change per §8).
