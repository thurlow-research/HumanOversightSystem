# Technical Design — SPEC-328: Out-of-Scope Commits Protocol

**Spec:** `docs/specs/SPEC-328-out-of-scope-commits-protocol.md` (REVISED — GO)
**Issue:** #328
**Author:** technical-design
**Date:** 2026-06-17
**Architect bindings applied:** C1 (branch naming), C2 (cross-branch PR traceability), C3 (GitHub API verification), C4 (fail-closed on API failure)
**Status:** APPROVED — implementation contract

---

## 0. Scope and architect bindings

This design is the implementation contract for SPEC-328. It binds the following
artifacts only:

| Artifact | Requirements implemented |
|---|---|
| `.claude/agents/overseer.md` | R2.1, R2.2, R2.3, R2.4, R2.5, R4.1, R4.2, R4.3, C3, C4 |
| `.claude/agents/worker.md` | R2.5 (worker side), R3.2, R3.4 (needs-human), R3.5 |
| `contract/OVERSIGHT-CONTRACT.md` §3 | R1.1–R1.6 (`Out_of_scope_commits:` field schema) |
| `contract/OVERSIGHT-CONTRACT.md` §6a | R4.1, R4.2, R4.3 (detection + resolution event catalog) |

**Explicitly NOT modified:**
- Reviewer agent files (code-reviewer.md, security-reviewer.md, etc.) — the
  `Out_of_scope_commits:` field is a contract-layer addition to §3; reviewer
  agents implement the contract. Their agent files are not modified by this design;
  the contract is the authoritative source.
- `scripts/framework/` Python utilities — no new Python modules are introduced.
  The overseer's GitHub API calls use the existing `gh api` CLI pattern already
  established in the overseer for other operations.
- No new files are created in the repo. All changes are to existing agent files
  and the contract document.

**Classification:** `additive`. No existing required field is renamed or removed.
No existing behavior is changed or loosened. No contract version bump (additive-only
per contract §8).

---

## 1. Data contracts (authoritative)

### 1.1 `Out_of_scope_commits:` register field (R1.1, R1.2, R1.3, R1.4)

This is an optional structured field in any reviewer's sign-off register entry
(contract §3). Its presence forces `Status: ESCALATED`.

```markdown
Out_of_scope_commits:
  - sha: <short SHA or full SHA>
    files: [<list of affected file paths>]
    stated_issue: <issue number or "unknown">
    reason: <one sentence — why this commit does not belong in this PR>
```

**Absent / `none`:** clean state. The field is omitted or explicitly set to `none`
when no out-of-scope commits are found, or when the originating reviewer clears it
after verifying the out-of-scope commit has been removed from the diff (R1.6, R3.3).

**Present with one or more entries:** triggers the overseer's out-of-scope gate (R2.1).
The reviewer's `Status:` MUST be `ESCALATED` — a reviewer MUST NOT set `Status: APPROVED`
while this field is populated (R1.3).

**Clearing the field (R1.6, R3.3):** The originating reviewer (the reviewer whose
register entry carries the flag) is the ONLY actor that may clear it. The reviewer
re-reviews the updated diff, removes the field (or sets it to `none`), and updates
their `Status:` accordingly. No other agent, artifact, or process edits the
originating reviewer's entry.

### 1.2 Detection event schema (R4.2)

```json
{
  "event": "out-of-scope-commit",
  "phase": "detected",
  "pr": "<PR number or URL>",
  "step": "<step id>",
  "flagged_by": "<reviewer agent name>",
  "commits": [
    {
      "sha": "<commit SHA>",
      "files": ["<file path>", "..."],
      "stated_issue": "<issue number or unknown>"
    }
  ],
  "disposition": "bounced | escalated",
  "timestamp": "<ISO-8601>",
  "comment_posted": true
}
```

The detection event is appended ONLY after the bounce or escalation comment is
confirmed posted. `comment_posted` is always `true` in a committed detection event
— a value of `false` is not a valid log entry and MUST NOT be written. If the
comment post fails, the detection event is NOT written (R4.1).

### 1.3 Resolution event schema (R4.3, C2)

```json
{
  "event": "out-of-scope-commit",
  "phase": "resolved",
  "pr": "<PR number or URL>",
  "step": "<step id>",
  "resolution": "cherry-pick-pr-opened | human-accepted",
  "authorized_by": "<human name or agent name>",
  "authorizing_issue": "<GitHub issue number — required when resolution is human-accepted; null when cherry-pick-pr-opened>",
  "cross_branch_pr": "<PR number of the cross-branch PR — required when cherry-pick-pr-opened; null when human-accepted>",
  "commits": ["<sha>", "..."],
  "timestamp": "<ISO-8601>"
}
```

Field rules:
- `resolution: "cherry-pick-pr-opened"` → `cross_branch_pr` required (the PR number
  from R3.2 step 3); `authorizing_issue` is null.
- `resolution: "human-accepted"` → `authorizing_issue` required (the GitHub issue
  number from R2.5); `cross_branch_pr` is null.
- Both values are mutually exclusive for a given SHA.

---

## 2. Component: `overseer.md` — out-of-scope commit gate

### 2.1 Gate position (R2.3)

The out-of-scope commit flag check is inserted into the existing §4 bounce-back gate
(overseer.md step 4a) **after** the register-completeness check and **before** the
merge-authority matrix. The complete gate ordering is:

1. Register-completeness check (all required sign-off fields present).
2. **Out-of-scope commit flag check** (this design — §2.2 through §2.5).
3. Merge-authority matrix evaluation.

A PR with an unresolved out-of-scope flag does not reach step 3.

### 2.2 Flag detection (R2.1)

The overseer inspects every entry in the sign-off register
(`.claudetmp/signoffs/step{N}-register.md`) for a non-empty `Out_of_scope_commits:`
field. "Non-empty" means: present AND not explicitly set to `none`. If one or more
such entries exist, the overseer MUST NOT proceed to the merge-authority matrix.

Inspection is over ALL register entries for the current step, not just the most
recent version of each role's entry.

### 2.3 Path A — bounce to worker (R2.1, R2.4)

Conditions: the flag is present AND the same SHA has NOT appeared in a prior bounce
on this `cid` AND `bounce_count(cid) < 2`.

The overseer calls `record_pr_bounce()` with:
- `reason_category: COMPLIANCE_FAILURE`
- `summary`: one sentence naming the flagged commit SHA(s) and affected file(s)

The bounce comment MUST include both resolution options in plain language:
- **(Option A)** Cherry-pick the out-of-scope commit to its correct branch via a new
  branch named `fix/<cid>-out-of-scope-<sha8>` (C1), open a PR with `[AI: overseer]`
  title prefix referencing the originating PR/cid and the out-of-scope SHA (C2),
  then revert the commit from the current PR branch using `git revert <sha>`.
- **(Option B)** Obtain human authorization via a `needs-human` GitHub issue (the
  4-step protocol from R2.5), then re-submit.

The detection event (§1.2) is appended in the same halt-on-failure unit as the
bounce comment: comment → confirm posted → append detection event (with
`disposition: "bounced"`) → finalize bounce. If the comment post fails or the
audit append fails, the overseer halts without finalizing (same halt-on-failure
protocol as the existing SPEC-378 ordering).

### 2.4 Path B — human escalation (R2.1)

Conditions (whichever occurs first):
1. **Same-SHA re-appearance:** any SHA in the current `Out_of_scope_commits:` field
   was already named in a prior bounce on this `cid` — regardless of the current
   `bounce_count(cid)`.
2. **Bounce-count cap:** `bounce_count(cid) >= 2`.

The overseer escalates via `HUMAN_REQUIRED` with:
- `reason_category: FINDINGS_NOT_RESOLVED`
- `summary`: one sentence identifying the re-appearing SHA(s) or bounce-count trigger

The detection event (§1.2) is appended after the escalation comment is confirmed
posted, with `disposition: "escalated"`. Same halt-on-failure ordering as §2.3.

Out-of-scope bounces use the existing `bounce_count(cid)` counter and the same per-cid
cap (`>= 2 → HUMAN_REQUIRED`). No separate counter is maintained (R2.2).

### 2.5 Human authorization verification (R2.5, C3, C4)

When the overseer encounters a register entry with `Out_of_scope_commits:` populated
and the worker has re-submitted claiming human authorization (i.e., the re-entry
references a `needs-human` issue), the overseer MUST perform GitHub API verification
before treating any flagged SHA as resolved-by-human.

**Verification procedure (C3):** For the referenced authorization issue, the overseer
MUST verify ALL of the following via the GitHub API:

1. **Issue exists:** `GET /repos/{o}/{r}/issues/{n}` returns HTTP 200.
2. **Carries `needs-human` label:** `issue.labels` contains a label with `name == "needs-human"`.
3. **Qualifying human comment exists:** `GET /repos/{o}/{r}/issues/{n}/comments` returns
   at least one comment where:
   - `comment.user.type != "Bot"` (the commenter is a human account, not a bot)
   - `comment.created_at` is AFTER the timestamp of the worker's initial request comment
     on that issue (the comment that filed the authorization request)

The overseer gates on the presence of a qualifying human comment (condition 3),
NOT on the issue's open or closed state. A closed issue with no qualifying human
comment does not constitute authorization.

**Fail-closed (C4):** If any of the following occur, the overseer MUST treat the
SHA as live and blocking and route to HUMAN_REQUIRED:
- The GitHub API call returns an error or non-200 response
- Network timeout or API unavailability
- No comments exist on the referenced issue
- No comment satisfies all three conditions of condition 3 above
- The issue does not exist or does not carry the `needs-human` label

The overseer MUST NOT treat unverifiable authorization as resolved. There is no
fallback or degraded-mode authorization path. This is the acknowledged operational
tradeoff documented in spec §3a: an API outage blocks auto-merge for authorized SHAs
until the API is reachable.

**Implementation detail:** The GitHub API calls use the existing `gh api` CLI pattern
already established in the overseer for other API operations. Read the canonical
label name from `scripts/framework/machine-accounts.env` (the existing labels
protocol in overseer.md). The `GET /repos/{o}/{r}/issues/{n}/comments` call returns
a paginated list; the overseer must follow pagination to examine all comments. If
the worker's initial request comment timestamp is not available from the issue itself,
the earliest comment with `user.login == HOSWorkerTutelare` (or equivalent bot login)
serves as the T_request anchor.

**Partial authorization (R2.5):** An authorization issue that covers only a subset
of flagged SHAs does not clear the unaddressed SHAs. The overseer must verify that
every flagged SHA in the register is covered by an authorization issue that passes
verification, or has been removed from the diff (originating reviewer cleared the entry).

**Resolution audit event:** When the overseer determines a SHA is resolved-by-human
after successful API verification, it appends the resolution event (§1.3) with
`resolution: "human-accepted"`, `authorizing_issue` set to the GitHub issue number,
and `cross_branch_pr: null`.

---

## 3. Component: `worker.md` — out-of-scope commit bounce response

### 3.1 Bounce response — out-of-scope path A (R3.2)

When the overseer bounces the PR with `reason_category: COMPLIANCE_FAILURE` for
an out-of-scope commit, the worker follows this sequence to execute Path A:

1. Identify the correct target branch for the out-of-scope commit from the
   `stated_issue` field in the `Out_of_scope_commits:` register entry.
   - If the target branch does not exist → escalate to human via `needs-human`
     issue; do NOT create a branch speculatively (R3.4).
   - If the target branch exists but is in an indeterminate state → escalate to
     human via `needs-human` issue (R3.4).

2. Revert the out-of-scope commit from the current PR branch:
   ```
   git revert <sha>
   ```
   This creates a new revert commit. Force-push and interactive rebase are not
   permitted (R3.5). Push the revert to the current PR branch.

3. Create the intermediate branch for the cherry-pick using the naming convention:
   ```
   fix/<cid>-out-of-scope-<sha8>
   ```
   where `<cid>` is the originating PR's correlation ID and `<sha8>` is the first
   8 characters of the out-of-scope commit SHA (C1). Branch from the target branch.

4. Cherry-pick the out-of-scope commit onto the intermediate branch:
   ```
   git cherry-pick <sha>
   ```

5. Open a PR against the target branch. The PR MUST (C2):
   - Have a title starting with `[AI: overseer]`
   - Reference in the body: (a) the originating PR number and its correlation ID,
     and (b) the out-of-scope commit SHA

6. After the revert is pushed and the cross-branch PR is opened, update the
   sign-off register to reflect the pending state so the originating reviewer
   can re-review the updated diff.

7. When filing the resolution audit event, the worker records `cherry-pick-pr-opened`
   with `cross_branch_pr` set to the PR number from step 5.

### 3.2 Bounce response — out-of-scope path B / needs-human issue (R2.5)

When the worker chooses the human-authorization path (or is directed there by the
overseer after path A completes but a human decision is still needed), the worker
files a `needs-human` issue using the standard 4-step protocol with the standard
"How to authorize" footer block. The issue must identify the flagged SHA(s) and
affected file(s), state the reason the commit is out-of-scope, and request explicit
human authorization to accept it as intentional.

The worker waits for the human's explicit authorization comment before re-submitting
the PR. The issue number is recorded in the resolution audit event
(`authorizing_issue` field).

---

## 4. Component: `contract/OVERSIGHT-CONTRACT.md` §3

### 4.1 `Out_of_scope_commits:` field (R1.1–R1.6)

A new optional structured field `Out_of_scope_commits:` is documented in §3 under
"Sign-off entries." Its canonical format is given in §1.1 of this design.

**Contract text addition to §3:**

Add after the `Critical_findings_resolved` field documentation:

> **`Out_of_scope_commits:`** (optional structured field — any reviewer role)
> When a reviewer identifies a commit that does not belong in the PR (content not
> traceable to the PR's stated issue), the reviewer populates this field with one
> entry per flagged commit. Its presence forces `Status: ESCALATED`. The field is
> absent or explicitly `none` in the clean state. Format:
> ```
> Out_of_scope_commits:
>   - sha: <short SHA or full SHA>
>     files: [<list of affected file paths>]
>     stated_issue: <issue number or "unknown">
>     reason: <one sentence — why this commit does not belong in this PR>
> ```
> Only the originating reviewer (whose entry carries the field) may clear it, by
> re-reviewing the updated diff and removing the field (or setting it to `none`).
> No other agent or artifact edits the originating reviewer's register entry to
> clear this flag.

---

## 5. Component: `contract/OVERSIGHT-CONTRACT.md` §6a

### 5.1 New event catalog rows (R4.1, R4.2, R4.3)

Two new rows are added to the §6a event catalog table:

**Detection row:**

| Event | Meaning | Emitted by | Key fields |
|---|---|---|---|
| `out-of-scope-commit` (phase: detected) | A reviewer flagged one or more commits as not belonging in the PR; the overseer bounced or escalated and confirmed the comment was posted before appending this event | overseer | `pr`, `step`, `flagged_by`, `commits` (array of `{sha, files, stated_issue}`), `disposition` (`bounced\|escalated`), `comment_posted` (always `true`) |

**Resolution row:**

| Event | Meaning | Emitted by | Key fields |
|---|---|---|---|
| `out-of-scope-commit` (phase: resolved) | The out-of-scope commit was resolved either by cross-branch PR with revert, or by human authorization via GitHub issue | overseer or worker | `pr`, `step`, `resolution` (`cherry-pick-pr-opened\|human-accepted`), `authorized_by`, `authorizing_issue` (required when `human-accepted`; null when `cherry-pick-pr-opened`), `cross_branch_pr` (required when `cherry-pick-pr-opened`; null when `human-accepted`), `commits` |

The canonical schemas are in §1.2 and §1.3 of this design.

**Append-ordering note (R4.1):** The detection event is NOT a standalone event
emitted independently at the moment the flag is found. It is appended in the same
halt-on-failure unit as the bounce or escalation comment post. The resolution event
is a separate, standalone event emitted when the out-of-scope commit is resolved.
Technical-design specifies these as separate events because their timing differs:
detection is tied to the comment-post gate; resolution is tied to the workflow
completion (revert pushed + cross-branch PR opened, or human comment verified).

---

## 6. Halt-on-failure ordering summary

Both detection dispositions (bounce and escalate) follow the same ordering:

**Detection (bounce path):**
1. Post the bounce comment (with out-of-scope SHAs, files, and both resolution
   options named).
2. Confirm the comment was posted (HTTP success / comment URL returned).
3. Append the `out-of-scope-commit / detected` audit event with
   `disposition: "bounced"` and `comment_posted: true`.
4. Finalize the bounce (assign, `needs-ai`, convert-to-draft, increment bounce
   counter).

**Detection (escalate path):**
1. Post the §8.2 HUMAN_REQUIRED escalation comment with
   `reason_category: FINDINGS_NOT_RESOLVED`.
2. Confirm the comment was posted.
3. Append the `out-of-scope-commit / detected` audit event with
   `disposition: "escalated"` and `comment_posted: true`.
4. Finalize (label `needs-human`, leave PR open).

**At each step:** if the action fails, the overseer halts without proceeding to
the next step. A detection event with `comment_posted: false` is not a valid log
entry and MUST NOT be written. A missing audit event is an audit-trail gap; the
overseer must never silently continue.

**Resolution (cherry-pick path):**
After the worker has pushed the revert and opened the cross-branch PR:
1. Append the `out-of-scope-commit / resolved` audit event with
   `resolution: "cherry-pick-pr-opened"` and `cross_branch_pr` set to the
   new PR number.

**Resolution (human-accepted path):**
After the overseer has verified the GitHub API authorization (C3/C4) and
confirms it passes:
1. Append the `out-of-scope-commit / resolved` audit event with
   `resolution: "human-accepted"`, `authorizing_issue` set to the issue number,
   and `cross_branch_pr: null`.

---

## 7. Startup-gap and affected sign-offs analysis

**Is there a startup-artifact-gap?** No. SPEC-328 is a net-new protocol, not a
correction of a pre-existing contract behavior that built code relied on. No prior
code was written against a gap this spec fills.

**Affected-sign-offs analysis:** All changes are `additive`.
- The `Out_of_scope_commits:` field is new and optional. No existing reviewer
  sign-offs referenced this field or relied on its absence. Prior reviewer
  sign-offs stand.
- The new audit events extend the catalog. No prior code was written against an
  absence-of-event contract that the new events contradict. Prior evaluator
  sign-offs stand.
- The overseer gate check is additive to the existing bounce-back gate. The gate
  ordering already had a register-completeness check followed by the merge-authority
  matrix; this inserts a new check between them. The existing register-completeness
  check behavior is unchanged. Prior overseer sign-offs stand.
- The worker's bounce-response instructions extend the existing re-entry-after-bounce
  section. Prior worker sign-offs stand.

No orphaned approvals. No re-review required.

---

## 8. Acceptance-criteria traceability

| AC | Satisfied by design section |
|---|---|
| AC1 — Reviewer detection produces a structured flag | §4.1 (`Out_of_scope_commits:` field, §1.1 schema) |
| AC2 — Overseer blocks merge on unresolved flag | §2.2, §2.3 (Path A), §2.4 (Path B) |
| AC3 — Worker cross-branch PR with correct naming (C1) and PR metadata (C2) | §3.1 steps 3–5 |
| AC4 — Human authorization verified via GitHub API (C3/C4) | §2.5 |
| AC5 — Same-SHA re-appearance → immediate HUMAN_REQUIRED | §2.4 |
| AC6 — Detection event tied to comment-post; resolution event separate | §1.2 `comment_posted` invariant, §6 halt ordering |

---

## 9. Human Review Required

**RISK:** LOW
**CONFIDENCE:** HIGH — all constraints are additive; the most sensitive element is
the GitHub API verification logic (C3/C4), which is fail-closed and therefore errs
toward blocking rather than unauthorized acceptance.

This is an additive change to documentation/contract artifacts and protocol text
in agent files. No new Python modules are introduced. No existing behavior is
changed or loosened.

**Change classification:** `additive`. The spec identifies this as REVISED — GO
for technical-design. No structural changes.

Human review items:
1. Confirm the `fix/<cid>-out-of-scope-<sha8>` branch naming convention (C1) is
   consistent with the project's existing branch-naming conventions.
2. Confirm the GitHub API verification procedure (C3) — specifically the
   `user.type != "Bot"` check — is sufficient for the human-vs-bot distinction
   in this repo's GitHub configuration.
3. Confirm the fail-closed-on-API-outage operational tradeoff (C4, spec §3a) is
   acceptable for production deployment scenarios.
