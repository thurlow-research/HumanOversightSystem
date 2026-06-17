# SPEC-85: Concrete Notification-Consumption Protocol for Reviewer Agents

**Status:** Draft — for architect review
**Issue:** #85
**Author:** pm-agent
**Date:** 2026-06-17

---

## 1. Problem Statement

`ux-designer` and `ops-designer` write inter-agent notification artifacts to
`.claudetmp/notifications/step{N}/` per the oversight contract §1 filesystem
protocol. The receiving reviewer agents (`ui-reviewer`, `a11y-reviewer`,
`ops-reviewer`) are expected to read and act on those artifacts, but the
framework specifies no concrete protocol for how they do so. Two gaps result:

**Gap 1 — Invocation ambiguity.** No mechanism ensures a reviewer is told
where to look. A reviewer invoked by the orchestration script or the human
receives no reliable signal that a notification file exists for its step unless
the invoking context mentions it by name. In a multi-session build, the
invoking context may not contain that information at all.

**Gap 2 — No acknowledgment requirement.** The notification artifact's
`Acknowledged:` field exists in the §1 schema but is described only as "left
blank; receiving agent fills in." No agent definition currently requires
reviewers to fill it in, verify its content, or record any acknowledgment in
their sign-off entry. A reviewer can sign off on a step without having read the
notification file that was written for it, and the oversight-evaluator has no
way to detect this.

The practical consequence: a `ux-designer` reactive gap-fill that adds a new
component class, writes a notification to `ui-reviewer`, and waits for
re-review — may receive a sign-off from a `ui-reviewer` that never opened the
file. The design-pack change is effectively invisible to the review chain.

---

## 2. Scope

This spec covers:

1. **Notification artifact schema** — formalizing the required fields that the
   sending agents (`ux-designer`, `ops-designer`) must write, with field-level
   semantics, so the receiving agent knows exactly what to read and act on.

2. **Reviewer consumption protocol** — a concrete, uniform set of steps each
   receiving reviewer must take at the start of its review when a notification
   directory exists for the current step: discover, read, verify, and
   acknowledge each relevant notification.

3. **Acknowledgment recording in the sign-off entry** — a new required
   sub-field in the sign-off register entry for the `ui`, `a11y`, and `ops`
   reviewer roles: `Notifications_acknowledged:`.

4. **Oversight-evaluator Phase 1 check** — when a notification file exists for
   a step and names a required reviewer role, the evaluator must verify that
   the register entry for that role includes a non-empty
   `Notifications_acknowledged:` field.

This spec does NOT cover:

- Changing who creates notification files. `ux-designer` and `ops-designer`
  already write them per contract §1; this spec only formalizes the schema and
  adds the consumption side.
- Notification files between agents other than the four named pairs
  (`ux-designer` → `ui-reviewer`, `ux-designer` → `a11y-reviewer`,
  `ops-designer` → `ops-reviewer`). The mechanism is generic but the
  compliance check is scoped to these three reviewer roles.
- Automated discovery or injection by the orchestration scripts. The protocol
  is prompt-level (agent CORE instructions), not shell-script-level. Tooling
  integration is out of scope for this spec.
- Notification routing between agents other than designer-to-reviewer pairs
  (e.g., `coder`-to-`security-reviewer` side-channels). This spec does not
  forbid such use but does not specify it or make it compliance-checked.
- Changes to the `ux-designer` or `ops-designer` sending behavior beyond
  formalizing the schema fields they already write.

---

## 3. Notification Artifact Schema (sending side)

The filesystem location is already defined in contract §1:

```
.claudetmp/notifications/step{N}/{from}-to-{to}-{ts}.md
```

This spec formalizes the required fields. All fields are required unless marked
optional.

```markdown
Step: {N}
From: {sender agent-name}
To: {receiver agent-name}
Type: design-pack-change | telemetry-spec-change | other
Changed: {YAML-style list of file paths or spec section references}
Reason: {one paragraph — what changed and why the receiving agent must act}
Blocking: yes | no
Required action: {imperative: what the receiving agent must do — e.g.
                  "Re-review the component class list against the updated
                   design pack before signing off on step 4."}
Acknowledged: {left blank by sender; receiving agent writes ISO-8601 timestamp
               and a one-sentence acknowledgment here}
```

**Field semantics:**

- `Step`: the build step number this notification concerns. Must match the
  step directory it is filed under.
- `From` / `To`: must use the canonical agent names from `step-manifest.yaml`
  role mappings (`ux-designer`, `ops-designer`, `ui-reviewer`, `a11y-reviewer`,
  `ops-reviewer`).
- `Type`: one of the three values above. `design-pack-change` is for
  `ux-designer` notifications; `telemetry-spec-change` is for `ops-designer`
  notifications; `other` is reserved for future use.
- `Changed`: a YAML-style bullet list. Each entry is a file path relative to
  the project root, or a spec section reference (e.g.
  `docs/design/DESIGN-PACK.md#color-tokens`). Must contain at least one entry.
  This is what the receiving agent is expected to inspect.
- `Reason`: why the change is relevant to the receiving agent's review domain.
  Must not be empty.
- `Blocking`: `yes` means the receiving agent must not sign off until it has
  acknowledged and acted on this notification. `no` means the notification is
  informational but acknowledgment is still required.
- `Required action`: a concrete, imperative statement. Must not be "see above"
  or a restatement of `Reason`.
- `Acknowledged`: the sender leaves this field blank (the colon and value are
  written, with the value empty). The receiving agent fills in an ISO-8601
  timestamp and a one-sentence acknowledgment on the same line or on the next
  line under the header, e.g.:
  `Acknowledged: 2026-06-17T14:32:00Z — Reviewed updated color tokens; no new
  a11y violations found. Proceeding.`

**File naming:** The `{ts}` component is an ISO-8601 basic datetime
(`YYYYMMDDTHHMMSSZ` or a similarly unambiguous compact form), not a Unix epoch.
Multiple notifications from the same sender to the same receiver within one
step are permitted; each gets its own file with a distinct timestamp.

---

## 4. Reviewer Consumption Protocol (receiving side)

Each of `ui-reviewer`, `a11y-reviewer`, and `ops-reviewer` must follow this
protocol at the **start of every review**, before examining code or templates:

**Step 1 — Discover.** Check whether `.claudetmp/notifications/step{N}/`
exists, where `N` is the build step being reviewed. If the directory does not
exist or is empty, record "no notifications for step N" and proceed to the
normal review.

**Step 2 — Filter.** Read every `.md` file in the directory. For each file,
read the `To:` field. Retain only files where `To:` matches this reviewer's
canonical agent name. Discard files addressed to other agents.

**Step 3 — Read and assess.** For each retained notification file:
- Read `Changed:`, `Reason:`, `Blocking:`, and `Required action:` in full.
- Locate and read each artifact listed in `Changed:` that falls within this
  reviewer's domain.
- Determine whether the change affects the sign-off decision for this step.

**Step 4 — Acknowledge.** After completing Step 3 for a file, fill in the
`Acknowledged:` field with the ISO-8601 timestamp and a one-sentence summary
of the determination (the action taken or the finding, e.g. "No additional
findings from the design-pack update"). Write the edit to the notification file
before writing the sign-off register entry.

**Step 5 — Record.** Include a `Notifications_acknowledged:` line in the
sign-off register entry (see §5 below).

**Blocking notifications:** If any retained notification has `Blocking: yes`,
the reviewer must address the `Required action` before approving. A `Blocking:
yes` notification that has not been acknowledged and acted on must cause the
reviewer to withhold approval (`Status: ESCALATED` with an explanation, or
`Status: CONDITIONAL` with the unresolved notification as the conditional item)
rather than approving.

**No notification directory:** If the directory does not exist, the reviewer
records `Notifications_acknowledged: none` and proceeds normally. This is the
expected state for steps where no designer gap-fill occurred.

---

## 5. Sign-Off Register Entry Field

The sign-off register entry schema (contract §3) is extended for the `ui`,
`a11y`, and `ops` reviewer roles with one new field:

```markdown
Notifications_acknowledged: none | {count} — {comma-separated file basenames}
```

Examples:

```markdown
Notifications_acknowledged: none
Notifications_acknowledged: 1 — ux-designer-to-ui-reviewer-20260617T143200Z.md
Notifications_acknowledged: 2 — ux-designer-to-a11y-reviewer-20260617T143200Z.md, ux-designer-to-a11y-reviewer-20260617T153000Z.md
```

**Semantics:**

- `none`: no notification directory existed for this step, or the directory
  contained no files addressed to this reviewer. No action was required.
- `{count} — {filenames}`: the reviewer read and acknowledged this many
  notification files, identified by their basenames. The count must equal the
  number of files listed. The basenames must match files that exist in
  `.claudetmp/notifications/step{N}/`.

**Required for:** `ui`, `a11y`, `ops` sign-off roles. Optional (may be omitted
or recorded as `N/A`) for all other roles that do not receive designer
notifications.

---

## 6. Oversight-Evaluator Phase 1 Check

The oversight-evaluator must add one new compliance check to Phase 1, run after
the existing sign-off role checks:

**Condition: notification acknowledgment present when files exist.**

1. List all files in `.claudetmp/notifications/step{N}/`. If none exist, skip
   this check entirely.
2. For each file in the directory, read the `To:` field.
3. For each distinct value of `To:` that names a role in `required_signoffs`
   for this step (`ui`, `a11y`, `ops`), verify that the corresponding
   register entry contains a non-empty `Notifications_acknowledged:` field
   (any value other than absent or empty).
4. If a required reviewer role has at least one notification file addressed to
   it AND its register entry is missing the `Notifications_acknowledged:` field
   (or it is present but empty) → **COMPLIANCE WARN** (not FAIL).
   Message: "Notification file {filename} addressed to {role} for step {N}:
   register entry for {role} does not record acknowledgment
   (`Notifications_acknowledged:` absent or empty). Reviewer may not have read
   the notification."

**Severity: COMPLIANCE WARN, not FAIL.** The notification mechanism is a
communication protocol between agents, not a gate-enforcement artifact. A
missing acknowledgment is a process gap (the reviewer may have read the file
and simply not recorded it, or the notification may have been sent after sign-
off completed). It is surfaced as a conditional item rather than a hard
escalation. However, when the notification has `Blocking: yes`, the warn is
upgraded to a **COMPLIANCE FAIL**: a blocking notification that was not
acknowledged represents a concrete gap in the review chain — the reviewer's
sign-off may not reflect the design-pack or telemetry-spec change the
notification described.

**Emit a conditional item when Blocking: yes notifications are unacknowledged:**
"Blocking notification {filename} ({from} → {role}) for step {N} was not
acknowledged in the sign-off register. The sign-off may predate the
{from} change. Re-review required."

---

## 7. Acceptance Criteria

**AC1 — No notification directory: no new compliance check fires.**
Given `.claudetmp/notifications/step{N}/` does not exist, when the evaluator
runs Phase 1, the notification check is skipped and no compliance item is added.

**AC2 — Non-blocking notification, acknowledged: passes cleanly.**
Given a notification file at `.claudetmp/notifications/step{N}/ux-designer-to-
ui-reviewer-{ts}.md` with `Blocking: no`, and the `ui` sign-off entry has
`Notifications_acknowledged: 1 — ux-designer-to-ui-reviewer-{ts}.md`, when
the evaluator runs Phase 1, no notification-related compliance item is emitted.

**AC3 — Non-blocking notification, no acknowledgment: COMPLIANCE WARN.**
Given the notification file exists with `Blocking: no`, and the `ui` sign-off
entry either lacks `Notifications_acknowledged:` or has it empty, when the
evaluator runs Phase 1, it emits exactly one COMPLIANCE WARN naming the file
and the role, and triggers CONDITIONAL_PROCEED (not ESCALATE).

**AC4 — Blocking notification, no acknowledgment: COMPLIANCE FAIL.**
Given the notification file exists with `Blocking: yes`, and the `ui` sign-off
entry lacks a non-empty `Notifications_acknowledged:` field, when the evaluator
runs Phase 1, it emits COMPLIANCE FAIL and the recommendation is ESCALATE.

**AC5 — Notification addressed to a different reviewer: not checked.**
Given a notification file with `To: ops-reviewer`, and the step's
`required_signoffs` include `ui` but not `ops`, when the evaluator runs Phase
1, no compliance item is emitted for the `ui` reviewer's acknowledgment. The
`ops-reviewer` acknowledgment check is skipped because `ops` is not a required
sign-off for this step.

**AC6 — Multiple notifications, all acknowledged: passes cleanly.**
Given two notification files addressed to `a11y-reviewer` for the same step,
and the `a11y` sign-off entry records
`Notifications_acknowledged: 2 — {file1}, {file2}`, when the evaluator runs
Phase 1, no notification-related compliance item is emitted.

**AC7 — Reviewer records `none` when no files are addressed to it.**
Given `.claudetmp/notifications/step{N}/` exists with only a file addressed
to `ops-reviewer`, and the `ui` reviewer records
`Notifications_acknowledged: none`, when the evaluator runs Phase 1, no
compliance item is emitted for the `ui` role.

---

## 8. Non-Requirements

**NR1 — No orchestration script changes required.** The consumption protocol is
carried entirely in agent CORE instructions. No shell script needs to pass a
`--notifications-dir` flag. This spec does not preclude adding such a flag in
future but does not require it.

**NR2 — No automated notification injection.** The evaluator does not inject
notification summaries into reviewer invocations. Reviewers are responsible for
discovering the directory at the start of their review.

**NR3 — No schema versioning.** The notification artifact schema is not
versioned separately. It is part of the oversight contract §1. Schema changes
follow the normal spec-change classification rules.

**NR4 — No retroactive requirement for completed steps.** Steps that completed
before this spec ships are not retroactively checked. The evaluator applies the
new condition only to steps evaluated after the spec is implemented.

**NR5 — No cross-step notifications.** A notification in `step{N}/` concerns
only step N. Notifications are not persisted or re-checked across step
boundaries.

**NR6 — `Notifications_acknowledged:` is not required for roles that never
receive designer notifications.** `code-reviewer`, `security-reviewer`,
`privacy-reviewer`, `reliability-reviewer`, `infra-reviewer` are not required
to include this field in their sign-off entries.

---

## 9. Affected Artifacts

| Artifact | Change type | Summary |
|---|---|---|
| `contract/OVERSIGHT-CONTRACT.md` §1 | Additive | Formalize notification artifact field schema with field semantics (Type, Changed, Reason, Blocking, Required action, Acknowledged semantics) |
| `.claude/agents/ui-reviewer.md` CORE | Additive | Add consumption protocol (Steps 1–5) and `Notifications_acknowledged:` sign-off field requirement |
| `.claude/agents/a11y-reviewer.md` CORE | Additive | Same as ui-reviewer |
| `.claude/agents/ops-reviewer.md` CORE | Additive | Same as ui-reviewer |
| `.claude/agents/oversight-evaluator.md` Phase 1 | Additive | Add notification acknowledgment compliance check (§6) after existing sign-off role checks |
| `contract/OVERSIGHT-CONTRACT.md` §3 | Additive | Add `Notifications_acknowledged:` to the sign-off register entry schema for ui/a11y/ops roles |

No existing required fields are renamed or removed. The `Acknowledged:` field
already exists in §1; this spec assigns it formal semantics and makes filling
it in a reviewer obligation rather than an optional gesture.

---

*Status: Draft — for architect review*
*Author: pm-agent | 2026-06-17*
