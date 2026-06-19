# Technical Design — SPEC-378: Structured Rejection Rationale and Gate Suspension Schema

**Spec:** `docs/specs/SPEC-378-structured-rejection-rationale.md` (REVISED, pass 3)
**Issue:** #378
**Author:** technical-design
**Date:** 2026-06-17
**Architect ruling:** GO (pass 3)
**Status:** APPROVED — implementation contract

---

## 0. Scope and architect bindings

This design is the implementation contract for SPEC-378. It binds the following
artifacts only:

| Artifact | Requirements implemented |
|---|---|
| `.claude/agents/overseer.md` | R1.1, R1.2, R1.3, R1.4, R1.5, R3.3, R3.4 |
| `contract/OVERSIGHT-CONTRACT.md` §6a | R3.1 (extend `pr-bounced`), R3.2 (new `human-required` event) |
| `contract/OVERSIGHT-CONTRACT.md` §3 | R2.3 WARN-not-FAIL semantics (cross-reference only; evaluator logic lives in §7) |
| `contract/gate-suspension.template.md` | R2.1, R2.2 |

**Explicitly NOT modified** (architect binding 1): `oversight-orchestrator.md`.
The target of all overseer-protocol changes is `overseer.md` only. The
orchestrator's ESCALATE console output is unchanged (R1.4).

**Classification:** `additive`. No existing field is renamed or removed; no
existing contract behavior is loosened; no contract version bump (additive-only
per the contract's §8). The one rename below is internal to a *new/extended*
enum value, not to an existing shipped field.

---

## 1. `reason_category` enum rename (architect binding 8 — RESOLVED: apply)

The architect raised a non-blocking note: the HUMAN_REQUIRED reason_category
enum (R1.3) contains a member literally named `HUMAN_REQUIRED`, which collides
with the *disposition* name `HUMAN_REQUIRED`. A reader cannot tell from the bare
token whether it refers to the disposition or to one specific reason within that
disposition.

**Decision: apply the rename.** It does not create ambiguity — it removes it.

- **Old member:** `HUMAN_REQUIRED`
- **New member:** `GATE_UNSATISFIED`
- **Semantics (unchanged from R1.3):** a human gate is required (CRITICAL step,
  merge-authority matrix) and has not been satisfied.

`GATE_UNSATISFIED` names the condition precisely (a gate that is required and not
yet satisfied) and can never be confused with the disposition. The rename applies
in **two** places that both carry the HUMAN_REQUIRED reason_category:

1. R1.1 — the §8.2 escalation comment `**Reason category:**` field.
2. R3.2 — the `human-required` audit event `reason_category` field.

Both enums are therefore: `FINDINGS_NOT_RESOLVED | ESCALATION | GATE_UNSATISFIED | OTHER`.

This is the only deviation from the spec's literal enum text, and it is the
deviation the architect authorized. The pr-bounced enum is untouched.

---

## 2. Data contract — enums (authoritative)

Two distinct enums, one per disposition (spec R1.3). They are intentionally
different because the two dispositions describe different procedural states.

### 2.1 HUMAN_REQUIRED disposition enum (escalation comment + `human-required` event)

| Value | Meaning |
|---|---|
| `FINDINGS_NOT_RESOLVED` | One or more reviewer/compliance/second-review findings remain unresolved after the maximum iteration budget. |
| `ESCALATION` | The oversight-evaluator issued ESCALATE and the condition requires human resolution. |
| `GATE_UNSATISFIED` | A human gate is required (CRITICAL step, merge-authority matrix) and has not been satisfied. *(renamed from `HUMAN_REQUIRED` per binding 8.)* |
| `OTHER` | Any reason not fitting the above; the `Summary` sentence must make it unambiguous. |

### 2.2 pr-bounced disposition enum (`record_pr_bounce()` comment + `pr-bounced` event)

| Value | Meaning |
|---|---|
| `REGISTER_GAP` | Required sign-off register entries are absent or missing required fields; the worker must complete the register before re-entering the overseer queue. |
| `COMPLIANCE_FAILURE` | The register/evaluator compliance check found a concrete failure (missing human-authorization artifact, failing gate result, N/A invalidated); the specific `check_id`(s) appear in the `failures` field of the audit event. |
| `SPEC_AMBIGUITY` | A procedural requirement could not be evaluated because the spec is ambiguous; the worker should seek clarification before reworking. |
| `OTHER` | Any bounce reason not fitting the above; the `Summary` sentence must make it unambiguous. |

### 2.3 Gate-suspension enum (`contract/gate-suspension.md` `reason_category`)

| Value | Meaning |
|---|---|
| `EMERGENCY` | A blocking production issue requires bypassing the gate; the suspension is expected to be very short-lived. |
| `PLANNED_MAINTENANCE` | A known, scheduled period where the gate would produce expected failures (migration window, transient third-party outage). |
| `FALSE_POSITIVE` | The gate consistently triggers on a known non-issue in this codebase; a fix/gate-rule update is planned. |
| `OTHER` | Any suspension reason not fitting the above; the prose `Reason:` sentence must make it unambiguous. |

### 2.4 `summary` field — invariant

`summary` is a single sentence. It is **templated, not generated** (NR2): the
overseer fills it from the evaluator's ESCALATE output or from the specific
compliance-failure list. No language-model generation step. The `summary` value
written into the comment MUST be byte-identical to the `summary` value in the
corresponding audit event (R3.1, R3.2). Empty `summary` is non-compliant.

---

## 3. Component: `overseer.md` (R1.1, R1.2, R1.3, R1.4, R1.5, R3.3, R3.4)

The overseer is a protocol document, not executable code; `record_pr_bounce()`
is a named protocol step ("comment + assign + needs-ai + draft + audit event"),
not a Python function. The design therefore specifies the *protocol text*
contracts, not function signatures.

### 3.1 R1.2 — extend the `record_pr_bounce()` protocol step

**Where:** the bounce-back gate (overseer.md step 4a, the `record_pr_bounce(...)`
call) and a new dedicated "Bounce rationale" subsection in the bounce protocol.

**Contract additions — the bounce comment body MUST include, appended after
whatever structured content the bounce comment already carries:**

```markdown
**Reason category:** <REGISTER_GAP | COMPLIANCE_FAILURE | SPEC_AMBIGUITY | OTHER>
**Summary:** <one sentence — what must change before this PR can proceed>
```

**Contract additions — the `pr-bounced` audit event payload gains:**
`reason_category` (the same value written to the comment) and `summary` (the
same sentence). All seven existing payload fields (`pr`, `cid`, `bounce_number`,
`failures`, `assigned_to`, `repo`, `timestamp`) are unchanged.

**Boundaries:**
- This is NOT a separate, additional comment. The two fields are appended to the
  existing single bounce comment body (AC2, R1.2).
- `record_pr_bounce()` still performs all five existing actions (comment, assign
  to hos-worker-hos[bot], `needs-ai`, convert-to-draft, append audit). The change
  adds two fields to two of those five (the comment body and the audit payload).
- The `>= 2` bounce-count branch (overseer.md step 4a) escalates to human via
  the §8.2 path instead — that path is governed by R1.1, not R1.2.

### 3.2 R1.1 — extend the §8.2 HUMAN_REQUIRED escalation comment

**Where:** the "Escalation format (§8.2 …)" section of overseer.md.

The existing §8.2 format requires five ordered elements:
1. Problem + risk + background
2. Options with pros/cons
3. Recommendation + justification
4. Token estimate + blast-radius summary
5. Default-deny deadline if applicable

**Contract addition — append AFTER element 5, do NOT alter elements 1–5
(architect binding 5):**

```markdown
**Reason category:** <FINDINGS_NOT_RESOLVED | ESCALATION | GATE_UNSATISFIED | OTHER>
**Summary:** <one sentence — what the decisive blocker was>
```

**Boundaries:**
- The five existing elements keep their order and meaning. A comment missing any
  of them is already malformed; this design does not touch that rule.
- The two new fields are *additionally* required. A §8.2 comment missing them is
  compliant with the legacy format but non-compliant with SPEC-378.
- The console/ESCALATE output is NOT changed (R1.4). The PR comment is the
  durable artifact; the console output is session-local.

### 3.3 R1.5 — applicability boundary

Structured-rationale comments are posted ONLY when the overseer acts on a PR it
previously opened, identified by the `[AI: overseer]` title prefix. The overseer
MUST NOT post structured-rationale comments to human-opened PRs. This is a
guard condition on both R1.1 and R1.2.

### 3.4 R3.3 / R3.4 — halt-on-failure ordering (architect binding 7)

Both non-merge dispositions follow strict ordering. The audit event is appended
ONLY after the comment is confirmed posted, and the disposition is finalized
ONLY after the audit append succeeds.

**pr-bounced ordering:**
1. Post bounce comment (with the two new fields).
2. **Confirm** comment posted (the `gh` call returned success / a comment URL).
   - If the comment post fails → **do not finalize** the bounce (do not append
     the audit event, do not treat the bounce as recorded). Halt and print.
3. Append the `pr-bounced` audit event (with `reason_category` + `summary`).
   - If the audit append fails → **do not finalize**. Halt and print (R3.4).
4. Finalize the disposition (assign, `needs-ai`, convert-to-draft as the existing
   `record_pr_bounce()` already does).

**HUMAN_REQUIRED ordering:**
1. Post §8.2 escalation comment (with the two new fields).
2. **Confirm** comment posted.
   - If the comment post fails → **do not finalize** (do not append audit, do not
     treat as escalated). Halt and print.
3. Append the `human-required` audit event (with `reason_category` + `summary`).
   - If the audit append fails → **do not finalize**. Halt and print (R3.4).
4. Finalize the disposition (label `needs-human`, leave PR open).

**Boundary:** "do not finalize" means the disposition is incomplete and the
overseer halts loudly. A missing audit-log line is an audit-trail gap; the
overseer must never silently continue past a comment-post or audit-append
failure (R3.4). The audit log is append-only and committed.

---

## 4. Component: `contract/OVERSIGHT-CONTRACT.md` §6a (R3.1, R3.2)

### 4.1 R3.1 — extend the `pr-bounced` catalog row

The existing `pr-bounced` row's **Key fields** column gains `reason_category`
and `summary`. Existing key fields are unchanged. The canonical extended schema
(documented inline near the catalog) is:

```json
{
  "event": "pr-bounced",
  "pr": "<PR number or URL>",
  "cid": "<worker correlation id>",
  "bounce_number": "<integer>",
  "failures": ["<check_id>", "..."],
  "assigned_to": "hos-worker-hos[bot]",
  "repo": "<owner/repo>",
  "timestamp": "<ISO-8601>",
  "reason_category": "REGISTER_GAP | COMPLIANCE_FAILURE | SPEC_AMBIGUITY | OTHER",
  "summary": "<same one-sentence summary as the bounce comment>",
  "comment_posted": true
}
```

`reason_category` and `summary` MUST match the bounce comment values (R3.1).

### 4.2 R3.2 — add the new `human-required` catalog row

A NEW row is added to the §6a catalog table. The disposition already exists
(label `needs-human` + §8.2 comment); only the discrete audit event is new.

- **Event:** `human-required`
- **Meaning:** Overseer escalated a PR to a human (label `needs-human` + §8.2
  comment); PR left open. Logged so all non-merge dispositions are queryable.
- **Emitted by:** overseer
- **Key fields:** `pr`, `step`, `reason_category`
  (`FINDINGS_NOT_RESOLVED | ESCALATION | GATE_UNSATISFIED | OTHER`), `summary`,
  `agent` (= `overseer`), `comment_posted`

Canonical schema (documented inline near the catalog):

```json
{
  "event": "human-required",
  "pr": "<PR number or URL>",
  "step": "<step id>",
  "reason_category": "FINDINGS_NOT_RESOLVED | ESCALATION | GATE_UNSATISFIED | OTHER",
  "summary": "<same one-sentence summary as the §8.2 comment>",
  "agent": "overseer",
  "timestamp": "<ISO-8601>",
  "comment_posted": true
}
```

**Note on the enum rename:** the spec's R3.2 text lists `HUMAN_REQUIRED` as the
third enum member; per architect binding 8 this design ships it as
`GATE_UNSATISFIED`. The contract documents `GATE_UNSATISFIED`.

### 4.3 R2.4 — `gate-suspended` event gains `reason_category`

The existing `gate-suspended` catalog row's Key fields gain `reason_category`.
*(Spec R2.4. The architect bindings for this task enumerate R1/R3 edits and the
gate-suspension template; the §6a `gate-suspended` row update is in spec scope.
It is additive and consistent with binding 6. See §6 for the affected-sign-offs
note.)*

---

## 5. Component: `contract/gate-suspension.template.md` (R2.1, R2.2)

**Where:** immediately after the `Reason:` field (template line 25).

**Contract addition:**

```
reason_category: EMERGENCY | PLANNED_MAINTENANCE | FALSE_POSITIVE | OTHER
```

with an inline comment enumerating the four semantics (§2.3 of this design).

**Boundaries:**
- The field is required in any NEW gate-suspension file (R2.3).
- Existing files without it are grandfathered: the oversight-evaluator emits a
  COMPLIANCE **WARN** (not FAIL) for a suspension file missing `reason_category`
  (R2.3, AC3, architect binding 6). This WARN-not-FAIL semantics is documented in
  the contract (§3 cross-reference / §7 evaluator behavior); the template change
  itself only adds the field + comment.
- Agents must NOT create or modify `contract/gate-suspension.md` (R2.5, existing
  invariant). The human who creates the file sets `reason_category`. The template
  is the thing edited here, never the live suspension file.

---

## 6. Startup-gap analysis and affected sign-offs

**Should this have been settled in the initial technical design before any code
was written against it?** No. SPEC-378 is a net-new audit-completeness feature,
not a correction of a pre-existing contract that built code relied on. There is
no `startup-artifact-gap`.

**Affected-sign-offs analysis:** All changes are `additive`.
- No existing `pr-bounced` emission contract is broken — the two new fields are
  added; the seven existing fields are unchanged. Prior overseer sign-offs that
  approved the existing bounce behavior **stand** (the old behavior is a strict
  subset of the new behavior).
- The new `human-required` event logs a disposition that already occurred but was
  previously unlogged. No prior code was written against an absence-of-event
  contract that the new event contradicts. Prior sign-offs **stand**.
- The gate-suspension template change is additive and migration-friendly
  (WARN-not-FAIL). Existing suspension files remain valid. Prior evaluator
  sign-offs **stand**.

No orphaned approvals. No re-review required.

---

## 7. Acceptance-criteria traceability

| AC | Satisfied by design section |
|---|---|
| AC1 — HUMAN_REQUIRED includes structured rationale | §3.2 (R1.1), §3.3 (R1.5 guard), §2.1 enum |
| AC2 — pr-bounced includes structured rationale | §3.1 (R1.2), §2.2 enum, no extra comment |
| AC3 — suspension WARN-not-FAIL | §5 (R2.3), §4.3 |
| AC4 — non-merge dispositions logged with rationale | §4.1 (R3.1), §4.2 (R3.2), §3.4 ordering |

---

## 8. Human Review Required

**RISK:** LOW
**CONFIDENCE:** HIGH

This is an additive, migration-friendly change to documentation/contract
artifacts. It introduces no new bot-initiated action (NR1), no AI generation
step (NR2), and changes no merge-path behavior (NR5). The single deviation from
the spec's literal text — the `HUMAN_REQUIRED` → `GATE_UNSATISFIED` enum-member
rename — is explicitly authorized by architect binding 8 and removes a naming
collision rather than introducing one.

**Change classification:** `additive`. Not `structural` — no human pre-write gate
required beyond the architect GO already on record.

Human review item: confirm the enum-member rename `HUMAN_REQUIRED` →
`GATE_UNSATISFIED` is acceptable in the shipped contract (architect authorized
it as non-blocking; flagged here for visibility).
