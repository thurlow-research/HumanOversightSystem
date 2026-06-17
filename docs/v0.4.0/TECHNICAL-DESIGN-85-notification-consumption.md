# Technical Design — SPEC-85: Notification-Consumption Protocol for Reviewer Agents

**Spec:** `docs/specs/SPEC-85-notification-consumption-protocol.md`
**Issue:** #85
**ADR / Architect ruling:** GO (bindings recorded below)
**Author:** technical-design
**Date:** 2026-06-17
**Status:** For architect review

---

## 0. Architect bindings (authoritative constraints)

These four bindings from the architect's ruling govern the design. Where the spec
and a binding could be read differently, the binding wins.

1. **§3 contract amendment ships ATOMICALLY with the evaluator check.** The
   `Notifications_acknowledged:` field addition to `OVERSIGHT-CONTRACT.md` §3 and
   the oversight-evaluator Phase 1 notification check must land in the **same
   commit**. The register schema and its consumer are never out of sync in
   committed history.
2. **The evaluator backstops acknowledgment-RECORDING, not discovery.** The
   evaluator verifies that a required reviewer recorded an acknowledgment in the
   register when a notification was filed to it. It does **not** attempt to detect
   an undiscovered notification directory or guarantee the reviewer actually read
   the file. Gap 1 (a reviewer never told where to look) remains a **behavioral**
   obligation carried in the reviewer CORE prompts — not a mechanical check.
3. **A `Blocking: yes` FAIL is scoped to required roles only.** The
   COMPLIANCE FAIL for an unacknowledged blocking notification fires only when the
   addressed role (`To:`) is in this step's effective `required_signoffs`. A
   notification with `Blocking: yes` addressed to a **non-required** role does
   **not** trigger FAIL (it is out of the step's review scope; at most an
   informational note).
4. **The evaluator does NOT parse the `Acknowledged:` field inside the
   notification file.** The evaluator's inputs are exactly three: (a) the existence
   and `To:` field of each file in `.claudetmp/notifications/step{N}/`, and (b) the
   `Blocking:` field of those files, and (c) the register entry's
   `Notifications_acknowledged:` field. It never reads or validates the inline
   `Acknowledged:` line the reviewer wrote into the notification file. The register
   field is the single source of truth for the compliance check.

---

## 1. Problem restated (contract terms)

`ux-designer` and `ops-designer` write notification artifacts to
`.claudetmp/notifications/step{N}/{from}-to-{to}-{ts}.md` (contract §1) when they
change a shared artifact (design pack, telemetry spec) that a reviewer must
re-review. The contract defines the file location and field list but no
**consumption** protocol: nothing requires `ui-reviewer`, `a11y-reviewer`, or
`ops-reviewer` to read the file, act on it, or record that it did so, and the
oversight-evaluator has no compliance signal to detect a sign-off that skipped a
notification.

This design adds three things, all additive (no existing field renamed or
removed):

- A uniform **consumption protocol** (discover → filter → read/assess →
  acknowledge → record) in the CORE region of the three receiving reviewers.
- A new sign-off register field `Notifications_acknowledged:` (required for
  `ui`/`a11y`/`ops`, optional elsewhere) in contract §3.
- A new oversight-evaluator Phase 1 compliance check (WARN by default,
  FAIL when a blocking notification to a required role is unacknowledged).

---

## 2. Data model — register field `Notifications_acknowledged:` (contract §3)

### 2.1 Field schema

| Field | Type | Required for | Constraint |
|---|---|---|---|
| `Notifications_acknowledged:` | `none` \| `{count} — {comma-separated basenames}` | `ui`, `a11y`, `ops` | When `{count}` form, count must equal the number of basenames listed; each basename must exist in `.claudetmp/notifications/step{N}/` |

**Value grammar:**

```
Notifications_acknowledged: none
Notifications_acknowledged: {N} — {basename}[, {basename}]...
```

- `none` — no notification directory existed for this step, OR the directory
  contained no file whose `To:` matched this reviewer. No action was required.
- `{N} — {basenames}` — the reviewer read and acknowledged `N` files, named by
  basename. `N` must equal the count of listed basenames.

**Required for:** `ui`, `a11y`, `ops` roles. **Optional** (may be omitted or
recorded as `N/A`) for `code-review`, `security`, `privacy`, `reliability`,
`infra`, and every other role that does not receive designer notifications
(spec NR6).

**Empty / absent semantics (drives the evaluator check):** an absent field, an
empty value, or a whitespace-only value are all treated identically by the
evaluator — "acknowledgment not recorded." `none` is a *recorded* value (the
reviewer affirmatively checked and found nothing for it) and is **not** empty.

### 2.2 Notification artifact schema (sending side — unchanged behavior, formalized)

The notification file at `.claudetmp/notifications/step{N}/{from}-to-{to}-{ts}.md`
already exists in contract §1. This design does not change the §1 field list
(`Step`, `From`, `To`, `Changed`, `Reason`, `Blocking`, `Required action`,
`Acknowledged`). The evaluator consumes only `To:` and `Blocking:` from it
(binding 4). The reviewer consumes the full file. No §1 edit is required by this
design — the §1 schema is already sufficient; the spec's §3 (sending-side field
semantics) is documentation of existing fields, not a new contract requirement
for this implementation.

> **Scope note.** The task scopes the implementation to four edited files plus the
> evaluator (five total): the three reviewer CORE regions, contract §3, and the
> evaluator. Contract §1 is **not** edited in this commit — its field list already
> covers the sending side. The spec's "Affected Artifacts" row for §1 is satisfied
> by the existing §1 schema; no further §1 change is load-bearing for the
> consumption protocol or the compliance check.

---

## 3. Reviewer consumption protocol (CORE region — ui / a11y / ops)

Each of the three reviewers gains a **"Notification consumption (before you
review)"** subsection in its CORE Inputs/Before-you-review area. The protocol is
identical across the three; only the reviewer's canonical agent name differs
(`ui-reviewer` / `a11y-reviewer` / `ops-reviewer`).

**Contract the prompt text must express (5 steps):**

1. **Discover.** At the start of the review, before examining code/templates,
   check whether `.claudetmp/notifications/step{N}/` exists for the step `N` being
   reviewed (`N` is supplied by the invoking context / register path). If it does
   not exist or is empty → record `Notifications_acknowledged: none` in the
   sign-off entry and proceed to the normal review. (Binding 2: discovery is a
   behavioral obligation here — no script injects it.)
2. **Filter.** Read every `.md` file in the directory; read each file's `To:`
   field; retain only files whose `To:` equals this reviewer's canonical agent
   name. Discard files addressed to other agents. If none remain → record
   `Notifications_acknowledged: none` and proceed.
3. **Read & assess.** For each retained file: read `Changed:`, `Reason:`,
   `Blocking:`, `Required action:` in full; locate and read each artifact in
   `Changed:` that falls in this reviewer's domain; determine whether the change
   affects the sign-off decision for this step.
4. **Acknowledge (inline in the notification file).** After assessing a file,
   fill its `Acknowledged:` field with an ISO-8601 timestamp and a one-sentence
   determination, written **before** the sign-off register entry. (Reviewers have
   Write/Edit only via… — see boundary note below.)
5. **Record (in the register).** Include `Notifications_acknowledged: {count} —
   {basenames}` (or `none`) in the sign-off register entry per §2.1.

**Blocking-notification rule (behavioral, in the prompt):** if any retained
notification has `Blocking: yes`, the reviewer must address its `Required action`
before approving. A `Blocking: yes` notification not acknowledged-and-acted-on
must cause the reviewer to withhold `APPROVED` — write `Status: CONDITIONAL` (with
the unresolved notification as the conditional item) or `Status: ESCALATED`
instead.

### 3.1 Boundary note — reviewer write capability on notification files

The three reviewers' tool lists are `Read, Grep, Glob, Bash` — they have **no
Write/Edit tool**, and their CORE Constraints explicitly forbid modifying
application code/templates and agent definition files. Filling the
`Acknowledged:` field (Step 4) is a write to a `.claudetmp/notifications/` file,
which is **neither application code, a template, nor an agent definition** — it is
ephemeral inter-agent working state. The protocol instructs the reviewer to record
the acknowledgment; the mechanically load-bearing artifact for compliance is the
**register field** (§2.1), which the reviewer already writes via its normal
sign-off path. Per binding 4 the evaluator never reads the inline `Acknowledged:`
field, so the inline write is a courtesy-to-the-sender, not a compliance gate. The
prompt must not imply the reviewer gains new tools; where a reviewer cannot write
the inline field with its available tools (`Bash` can append/edit a temp file), it
must still record the register field, which is the source of truth.

> **Design note (no architectural dependency).** This keeps the reviewers' "you
> have no Write/Edit tools; you review and sign off" constraint intact for the
> artifacts that matter (code, templates, agent defs). Editing an ephemeral
> notification file via `Bash` is within the existing tool set and does not
> require a tools-list change. If the architect prefers the inline acknowledgment
> be dropped entirely (register field only), that is a one-line simplification —
> flagged for the architect, not assumed.

---

## 4. Oversight-evaluator Phase 1 notification check

### 4.1 Placement

A new check, **"Notification acknowledgment compliance,"** is added to Phase 1
**after** the existing per-role sign-off field checks and **before** the
second-review compliance check. It is not assigned a numbered "Condition N"
(those are reserved for the anti-gaming re-derivation conditions 9–14); it is a
straight compliance check in the same class as the test-declaration checks.

### 4.2 Algorithm (exact computation)

Inputs: the step's effective `required_signoffs` (the manifest ∪ dynamic union
the evaluator already computed), the register entries, and the directory
`.claudetmp/notifications/step{N}/`.

```
1. If .claudetmp/notifications/step{N}/ does not exist OR is empty:
     skip this check entirely (no compliance item).        # spec AC1
2. For each *.md file F in the directory:
     read To(F)  and  Blocking(F)   # the only two fields read (binding 4)
3. Build the set ADDRESSED = { To(F) for each F }, and for each role r in
   ADDRESSED, the list FILES(r) = [ basename(F) : To(F) == r ],
   and BLOCKING(r) = any F with To(F)==r has Blocking(F)=="yes".
4. For each role r in ADDRESSED:
     a. If r is NOT in required_signoffs for this step:
          skip r — emit no compliance item.                # binding 3 + AC5
     b. Else read the register entry for r and its
        Notifications_acknowledged: field, ACK(r).
        - ACK(r) is "recorded" iff present AND non-empty AND not whitespace-only
          ("none" counts as recorded).
     c. If ACK(r) is recorded:
          pass — no compliance item.                        # AC2, AC6, AC7
     d. If ACK(r) is NOT recorded:
          - If BLOCKING(r) is true:
              COMPLIANCE FAIL  + conditional/escalation item # AC4
          - Else:
              COMPLIANCE WARN  + CONDITIONAL_PROCEED         # AC3
```

**Severity rules (spec §6):**

- **WARN** (non-blocking notification, no acknowledgment) → add a conditional
  item, trigger `CONDITIONAL_PROCEED`, do **not** fail compliance.
  Message: *"Notification file {filename} addressed to {role} for step {N}:
  register entry for {role} does not record acknowledgment
  (`Notifications_acknowledged:` absent or empty). Reviewer may not have read the
  notification."*
- **FAIL** (blocking notification to a required role, no acknowledgment) →
  COMPLIANCE FAIL → recommendation `ESCALATE`.
  Message: *"Blocking notification {filename} ({from} → {role}) for step {N} was
  not acknowledged in the sign-off register. The sign-off may predate the {from}
  change. Re-review required."*

### 4.3 Binding-driven edge cases (acceptance-criteria mapping)

| AC | Scenario | Outcome |
|---|---|---|
| AC1 | No notification directory | check skipped, no item |
| AC2 | Non-blocking, acknowledged | clean |
| AC3 | Non-blocking, unacknowledged (required role) | WARN → CONDITIONAL_PROCEED |
| AC4 | Blocking, unacknowledged (required role) | FAIL → ESCALATE |
| AC5 | Addressed to a non-required role (`ops` not required) | skipped for that role (binding 3) — no item, even if Blocking:yes |
| AC6 | Multiple notifications, all acknowledged | clean |
| AC7 | Reviewer records `none` when nothing addressed to it | clean (`none` is recorded) |

### 4.4 What the check does NOT do (boundaries)

- **Does not read the inline `Acknowledged:` field** of the notification file
  (binding 4). The register field is the sole compliance source.
- **Does not discover** that a directory *should* have existed (binding 2 — Gap 1
  stays behavioral). If no directory exists, the check skips; it never infers a
  missing notification.
- **Does not verify basename correspondence** between the register's listed
  basenames and the directory contents as a *compliance gate* — that is a §2.1
  reviewer obligation, surfaced at most as a Phase 2 note, not a Phase 1 FAIL.
  (Keeps the check's FAIL surface minimal and deterministic.)
- **Does not fire for non-required roles** even on `Blocking: yes` (binding 3).
- **Retroactivity (spec NR4):** applies only to steps evaluated after this ships;
  the evaluator does not re-check completed steps.

---

## 5. Sign-off register entry examples (the three reviewers)

```markdown
## ui | templates/booking/confirm.html | 2026-06-17T14:40:00Z
Status: APPROVED
Agent: ui-reviewer
Artifact: templates/booking/confirm.html
Iterations: 1
Critical_findings_resolved: N/A
Notifications_acknowledged: 1 — ux-designer-to-ui-reviewer-20260617T143200Z.md
Notes: none
```

```markdown
## a11y | templates/booking/confirm.html | 2026-06-17T14:41:00Z
Status: APPROVED
Agent: a11y-reviewer
Artifact: templates/booking/confirm.html
Iterations: 1
Critical_findings_resolved: N/A
Notifications_acknowledged: none
Notes: none
```

`ops` follows the same shape with role key `ops` and agent `ops-reviewer`.

---

## 6. Affected artifacts (this commit)

| Artifact | Change | Atomic? |
|---|---|---|
| `.claude/agents/ui-reviewer.md` CORE | Add §3 consumption protocol + register-field requirement | same commit |
| `.claude/agents/a11y-reviewer.md` CORE | Same | same commit |
| `.claude/agents/ops-reviewer.md` CORE | Same | same commit |
| `contract/OVERSIGHT-CONTRACT.md` §3 | Add `Notifications_acknowledged:` field (required ui/a11y/ops, optional else) | **same commit (binding 1)** |
| `.claude/agents/oversight-evaluator.md` Phase 1 | Add §4 notification acknowledgment check | **same commit (binding 1)** |

No existing required field is renamed or removed. The change is additive and
classified **additive** (a new optional/role-scoped field + a new WARN-default
compliance check; no governance loosening, no human-gate change). It is **not
structural** — no new dependency, auth state, route, surface, or user-facing state
signature (§2a). No human escalation required before writing.

---

## 7. Self-flag (design authoring)

RISK: LOW
CONFIDENCE: 90% — confident the contract/evaluator/register additions are
internally consistent and additive; the only open judgment is whether the inline
`Acknowledged:` write (§3.1) should remain given reviewers have no Write/Edit tool
— flagged for the architect, but it is non-load-bearing for compliance (the
register field is the source of truth), so it does not gate the design.

## Human Review Required

**§3.1 (reviewer inline acknowledgment write)** — reviewers have no Write/Edit
tool; the design routes the inline `Acknowledged:` write through `Bash` and makes
the register field the compliance source of truth so the protocol holds either
way. Confirm the architect is content to keep the inline write as a sender
courtesy (vs. register-field-only).

---

*Status: For architect review — bindings 1–4 incorporated.*
*Author: technical-design | 2026-06-17*
