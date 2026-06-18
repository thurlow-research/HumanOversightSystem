# Technical Design — #398: SPEC-328 Out-of-Scope Commits Protocol (binding-decisions implementation)

**Spec:** `docs/specs/SPEC-328-out-of-scope-commits-protocol.md` (REVISED — GO)
**Issues:** #398 (binding decisions C1–C4 + items 1–2), #328 (originating spec)
**Author:** technical-design
**Date:** 2026-06-18
**Status:** APPROVED — implementation contract
**Supersedes:** none. Companion to `TECHNICAL-DESIGN-328-out-of-scope-commits.md`;
this document is the authoritative contract for the work tracked under #398 and
reconciles the one ambiguity that the 328 design left open (resolution-event writer).

---

## 0. Scope and binding decisions

This design is the implementation contract for SPEC-328 as resolved by the binding
decisions in issue #398. It binds these artifacts only:

| Artifact | Requirements implemented |
|---|---|
| `.claude/agents/overseer.md` (step 4b) | R2.1–R2.5, R4.1–R4.5, C3, C4 |
| `.claude/agents/worker.md` (bounce-response) | R2.5 (worker side), R3.2, R3.4, R3.5, R3.7 |
| `contract/OVERSIGHT-CONTRACT.md` §3 | R1.1–R1.6 (`Out_of_scope_commits:` field) |
| `contract/OVERSIGHT-CONTRACT.md` §6a | R4.1–R4.5 (detection + resolution events) |

**Binding decisions carried (from #398 / spec header):**
- **Item 1** — Cross-branch work is ALWAYS via PR; never a direct push. Target-branch
  owner has approval authority.
- **Item 2** — Authorization is a GitHub issue, NOT a `.claudetmp/` artifact. The
  `.claudetmp/oversight/step{N}-out-of-scope-accepted.md` path is not used by this protocol.
- **C1** — Intermediate branch naming: `fix/<cid>-out-of-scope-<sha8>`.
- **C2** — Cross-branch PR title carries `[AI: overseer]` prefix; body references the
  originating PR/cid and the out-of-scope SHA; resolution schema requires `cross_branch_pr`.
- **C3** — Overseer verifies authorization via the GitHub API: issue exists +
  `needs-human` label + a human comment (`user.type != "Bot"`) post-dating the worker's
  request. Gate on the human comment, not on issue open/closed state.
- **C4** — Fail-closed on API failure or no qualifying human comment → HUMAN_REQUIRED.

**Explicitly NOT modified:**
- Reviewer agent files (code-reviewer.md, security-reviewer.md, etc.) — the
  `Out_of_scope_commits:` field is a contract-layer field in §3. Reviewers implement the
  contract; their agent files are not edited. The contract §3 is the authoritative source
  for the field's format and the `Status: ESCALATED` obligation.
- `scripts/framework/` Python — no new modules. The overseer's GitHub calls use the
  existing `gh api` CLI pattern already established in overseer.md.
- No new repo files. The authorization record is a GitHub issue, not a committed file.

**Classification:** `additive`. No required field is renamed or removed; no existing
behavior is loosened; no contract version bump (additive-only per contract §8).

---

## 1. Reconciled decision — single writer for the resolution event (the #398 delta)

The 328 design left two readings open: contract §6a lists the resolution event as
"Emitted by: overseer or worker", and 328-design §3.1 step 7 said the worker records
`cherry-pick-pr-opened`. This design SETTLES it:

> **The overseer is the sole writer of BOTH the detection event and the resolution
> event.** The worker opens the cross-branch PR (it is the only actor that may push to
> branches) but never writes to `audit/oversight-log.jsonl` for this protocol. The
> overseer emits `out-of-scope-commit / resolved` at the pre-merge gate, at the moment
> it confirms the flag is cleared — for BOTH `cherry-pick-pr-opened` and `human-accepted`.

Rationale:
- **Single audit writer at the confirmation point.** The resolution is only *true* once
  the overseer confirms it at the gate (originating reviewer cleared the entry, or the
  GitHub API authorization verified). Logging at any earlier point — e.g. when the worker
  opens the cross-branch PR — would record a resolution the gate has not yet confirmed.
- **No worker write path to the committed audit log** for out-of-scope, which keeps the
  worker's filesystem authority unchanged and avoids a second concurrent writer.
- Contract §6a's "overseer or worker" remains permissive and is not contradicted; the
  agent files narrow it to overseer-emits, which is the stricter (single-writer) reading.

`worker.md` Option A step 8 is updated to state this explicitly and to require the worker
to surface the cross-branch PR number in the re-entry note so the overseer can populate
`cross_branch_pr`.

---

## 2. Data contracts (authoritative)

### 2.1 `Out_of_scope_commits:` register field (R1.1–R1.6)

Optional structured field in any reviewer's sign-off register entry (contract §3).
Presence forces `Status: ESCALATED`.

```
Out_of_scope_commits:
  - sha: <short SHA or full SHA>
    files: [<list of affected file paths>]
    stated_issue: <issue number or "unknown">
    reason: <one sentence — why this commit does not belong in this PR>
```

- **Absent / `none`** — clean state. Also the cleared state after the originating reviewer
  re-reviews and removes the field.
- **Present (≥1 entry)** — triggers the overseer gate (§3). `Status:` MUST be `ESCALATED`.
- **Clearing (R1.6, R3.3)** — ONLY the originating reviewer (whose entry carries the field)
  may clear it, by re-reviewing the updated diff and removing the field / setting `none`.
  No other agent, artifact, or process edits that entry. A human authorization issue does
  NOT cause the field to be edited (R1.7) — the overseer evaluates the field and the
  authorization surface independently.

### 2.2 Detection event (R4.2, R4.5)

```json
{
  "event": "out-of-scope-commit",
  "phase": "detected",
  "pr": "<PR number or URL>",
  "step": "<step id>",
  "flagged_by": "<reviewer agent name>",
  "commits": [{ "sha": "<sha>", "files": ["<path>"], "stated_issue": "<issue or unknown>" }],
  "disposition": "bounced | escalated",
  "timestamp": "<ISO-8601>",
  "comment_posted": true
}
```

`comment_posted` is always `true` in a committed entry. The event is appended ONLY after
the bounce/escalation comment is confirmed posted (R4.1, §4). A `comment_posted: false`
entry is invalid and MUST NOT be written.

### 2.3 Resolution event (R4.3, R4.4, C2)

```json
{
  "event": "out-of-scope-commit",
  "phase": "resolved",
  "pr": "<PR number or URL>",
  "step": "<step id>",
  "resolution": "cherry-pick-pr-opened | human-accepted",
  "authorized_by": "<human name or agent name>",
  "authorizing_issue": "<issue number — required when human-accepted; null when cherry-pick-pr-opened>",
  "cross_branch_pr": "<PR number — required when cherry-pick-pr-opened; null when human-accepted>",
  "commits": ["<sha>", "..."],
  "timestamp": "<ISO-8601>"
}
```

- `cherry-pick-pr-opened` → `cross_branch_pr` required, `authorizing_issue` null.
- `human-accepted` → `authorizing_issue` required, `cross_branch_pr` null.
- Mutually exclusive per resolution. Written by the **overseer only** (§1).

---

## 3. Component: `overseer.md` step 4b — out-of-scope gate

### 3.1 Gate position (R2.3)

Inside the existing §4 bounce-back gate, after register-completeness and before the
merge-authority matrix:

1. Register-completeness check.
2. **Out-of-scope commit flag check** (this design).
3. Merge-authority matrix.

A PR with an unresolved out-of-scope flag never reaches step 3.

### 3.2 Flag detection (R2.1)

Inspect EVERY entry in `.claudetmp/signoffs/step{N}-register.md` for a non-empty
`Out_of_scope_commits:` field (present AND not `none`). Any such entry blocks the matrix.

For each flagged SHA, it is *resolved* iff ONE of:
- the originating reviewer cleared the entry (field removed/`none` + `Status: APPROVED`); or
- a referenced `needs-human` issue passes the C3 GitHub API verification (§3.5).

### 3.3 Path A — bounce to worker (R2.1, R2.4)

Conditions: ≥1 flagged SHA unresolved AND no flagged SHA appeared in a prior bounce on
this `cid` AND `bounce_count(cid) < 2`.

`record_pr_bounce()` with `reason_category: COMPLIANCE_FAILURE` and a `summary` naming the
flagged SHA(s) and file(s). The bounce comment MUST present both options:
- **Option A** — `git revert <sha>` on the current PR branch; create
  `fix/<cid>-out-of-scope-<sha8>` from the target branch (C1); cherry-pick; open a PR with
  `[AI: overseer]` title prefix, body referencing originating PR/cid + out-of-scope SHA
  (C2); notify the originating reviewer to re-review.
- **Option B** — file a `needs-human` issue (4-step protocol, R2.5), await the human
  authorization comment, re-submit.

Detection-event append shares the bounce comment's halt-on-failure unit (§4).

### 3.4 Path B — human escalation (R2.1)

Conditions (first to occur):
1. Same-SHA re-appearance: any current flagged SHA was already named in a prior bounce on
   this `cid` — regardless of `bounce_count(cid)`.
2. `bounce_count(cid) >= 2`.
3. Any flagged SHA whose authorization cannot be verified by the GitHub API (C4).

`HUMAN_REQUIRED` with `reason_category: FINDINGS_NOT_RESOLVED` and a `summary` naming the
blocking condition. Detection event with `disposition: "escalated"`, same halt-on-failure
ordering (§4). Uses the existing `bounce_count(cid)` counter and per-cid cap (R2.2).

### 3.5 Human authorization verification (R2.5, C3, C4)

Before treating any flagged SHA as resolved-by-human, verify via `gh api` ALL of:
1. Issue exists — `GET /repos/{o}/{r}/issues/{n}` returns HTTP 200.
2. Carries `needs-human` — `issue.labels` contains `name == "needs-human"`.
3. Qualifying human comment — `GET /repos/{o}/{r}/issues/{n}/comments` has ≥1 comment with
   `user.type != "Bot"` AND `created_at` after the worker's initial request comment
   (earliest comment by `HOSWorkerTutelare` / the bot login). Follow pagination.

Gate on condition 3, NOT on open/closed state. A closed issue with no qualifying human
comment is NOT authorization.

**Fail-closed (C4):** any API error, non-200, timeout, rate-limit, missing issue, missing
label, or no qualifying comment → treat the SHA as live and route to HUMAN_REQUIRED. No
degraded-mode path. Operational tradeoff per spec §3a (API outage blocks auto-merge for
authorized SHAs until recovery).

**Partial coverage (R2.5):** an issue covering only some flagged SHAs does not clear the
rest. Every flagged SHA must be either reviewer-cleared or covered by a verified issue.

### 3.6 Resolution-event emission (§1)

When the overseer confirms a SHA resolved at the gate, it appends `out-of-scope-commit /
resolved`:
- reviewer cleared via cross-branch PR → `resolution: cherry-pick-pr-opened`,
  `cross_branch_pr` = the cross-branch PR number (from the re-entry note), `authorizing_issue: null`.
- human-accepted via verified issue → `resolution: human-accepted`, `authorizing_issue` =
  issue number, `cross_branch_pr: null`.

The worker never writes this event.

---

## 4. Halt-on-failure ordering (R4.1)

Detection (both dispositions) shares the comment-post gate (same shape as SPEC-378 §8.2):
1. Post the bounce/escalation comment (SHAs, files, both options named).
2. Confirm posted (HTTP success / comment URL).
3. Append `out-of-scope-commit / detected` (`disposition` set, `comment_posted: true`).
4. Finalize (bounce: assign + `needs-ai` + convert-to-draft; escalate: `needs-human`).

If step 1 or 3 fails → HALT without finalizing. No detection event without a posted
comment; no silent continuation past an audit-append failure.

Resolution is a separate standalone event, appended by the overseer at gate confirmation
(§3.6) — not tied to the comment-post gate.

---

## 5. Component: `worker.md` — bounce response

### 5.1 Option A — cross-branch PR with revert (R3.2, R3.4, R3.5)
1. Identify target branch from `stated_issue`. Branch missing / indeterminate → file a
   `needs-human` issue; never create a branch speculatively (R3.4).
2. `git revert <sha>` on the current PR branch; push. No force-push / interactive rebase (R3.5).
3. Create `fix/<cid>-out-of-scope-<sha8>` from the target branch (C1).
4. `git cherry-pick <sha>`.
5. Open a PR against the target branch — title `[AI: overseer]…`; body references
   originating PR/cid + out-of-scope SHA (C2).
6. Update the register so the originating reviewer can re-review.
7. Only the originating reviewer clears the flag; the worker does not edit that entry (R3.3).
8. After the flag clears, re-run the pre-PR gate and re-submit. The worker does NOT write
   the resolution event — the overseer emits it at the gate (§1). Surface the cross-branch
   PR number in the re-entry note so the overseer can populate `cross_branch_pr`.

Credential guard: before any push / `gh pr create`, confirm `gh api user --jq .login` is
`HOSWorkerTutelare` (identity guard, #363).

### 5.2 Option B — human authorization issue (R2.5)
File a `needs-human` issue with the 4-step protocol + standard "How to authorize" footer:
(1) flagged SHA(s)+file(s); (2) why out-of-scope; (3) request authorization; (4) await the
human's explicit comment. Do not re-submit until the human comments. Re-submit references
the issue number so the overseer can verify (§3.5) and reference it in the resolution event.

---

## 6. Contract edits

- **§3** — `Out_of_scope_commits:` field documented (format + `Status: ESCALATED` +
  originating-reviewer-only clearing). Authoritative for reviewer behavior.
- **§6a** — detection + resolution event rows and both JSON schemas. Resolution
  "Emitted by" stays "overseer or worker" at the catalog level; the agent files narrow it
  to overseer-emits (§1) — the stricter reading, permitted by the catalog.

---

## 7. Startup-gap and affected-sign-offs analysis

**Startup-artifact-gap?** No. SPEC-328 is a net-new protocol, not a correction of a
pre-existing contract that built code relied on.

**Affected sign-offs (all `additive`):**
- New optional field — no prior reviewer sign-off relied on its absence → prior sign-offs stand.
- New audit events extend the catalog — no prior code contradicted → prior evaluator sign-offs stand.
- Overseer gate is inserted between two existing checks; existing checks unchanged → prior overseer sign-offs stand.
- Worker bounce-response extends existing re-entry section → prior worker sign-offs stand.

No orphaned approvals; no re-review required.

---

## 8. Acceptance-criteria traceability

| AC | Satisfied by |
|---|---|
| AC1 — structured flag | §2.1 (contract §3) |
| AC2 — overseer blocks merge | §3.2, §3.3, §3.4 |
| AC3 — cross-branch PR (C1/C2) + originating-reviewer re-review | §5.1, §3.6 |
| AC4 — GitHub API verification (C3/C4), register entry unchanged | §3.5, §2.1 |
| AC5 — same-SHA → HUMAN_REQUIRED; bounce cap | §3.4 |
| AC6 — detection tied to comment-post; resolution separate | §4, §2.2, §2.3 |

---

## 9. Human Review Required

**RISK:** LOW
**CONFIDENCE:** HIGH — all changes additive; the most sensitive element (the C3/C4 GitHub
API verification) is fail-closed and errs toward blocking, never toward unauthorized accept.

**Change classification:** `additive`. No structural change.

Review items:
1. Confirm `fix/<cid>-out-of-scope-<sha8>` (C1) matches the project's branch conventions.
2. Confirm the single-writer reconciliation (§1) — overseer emits BOTH events, worker emits
   none — is the intended division of audit-write authority.
3. Confirm the fail-closed-on-API-outage tradeoff (C4 / spec §3a) is acceptable for production.
