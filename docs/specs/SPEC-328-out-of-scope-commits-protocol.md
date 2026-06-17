# SPEC-328: Out-of-Scope Commits Protocol

**Status:** REVISED — pending human clearance on two open items (issue #398)
**Issue:** #328
**Author:** pm-agent
**Date:** 2026-06-17

> **PENDING HUMAN SIGN-OFF on two items (issue #398):**
> 1. Worker authority to push to a second branch beyond its assigned PR branch (required for the cherry-pick step in R3).
> 2. Whether the human-acceptance artifact should be committed to a tracked path (not `.claudetmp/`) for audit durability.
> Technical-design is blocked until issue #398 is resolved.
>
> **NOTE — human-acceptance artifact path:** `.claudetmp/oversight/step{N}-out-of-scope-accepted.md` is ephemeral and gitignored. The architect recommends a committed path instead for audit durability. The human decides (issue #398 item 2).

---

## 1. Problem Statement

During review of a consumer project PR, the security reviewer identified a commit that updated `docs/architecture/ADR-001-pilot.md` with content from issue #125 committed to the wrong branch. The commit had no traceable connection to the PR's stated issue. The reviewer correctly flagged it as a T1-3 finding but had no defined protocol for what should follow: should the PR be blocked? Should the out-of-scope commit be reverted? Should it be accepted with acknowledgment?

The absence of a protocol meant the reviewer could detect the anomaly but could not direct a resolution, the overseer had no defined response path, and the audit trail captured no event for the disposition. The result is an undefined state: a flagged anomaly that neither proceeds nor resolves.

The core principle this spec enforces: every commit in every PR must be traceable to the PR's stated issue. A commit not traceable to that issue requires explicit acknowledgment — either it is moved to the correct branch and reverted from this PR, or a human confirms it is intentional and accepts responsibility for the cross-issue contamination.

---

## 2. Scope

This spec covers:

1. **Reviewer detection and structured flagging** — when any base-team reviewer identifies a commit that does not belong in the PR (wrong issue content, different feature, stale content, or content not traceable to the PR's stated issue), the reviewer must flag it in a defined, structured format in the sign-off register.

2. **Overseer response protocol** — when the overseer encounters an out-of-scope commit flag in the sign-off register, it has a defined response: route the PR back to the worker with one of two required resolutions, or seek human confirmation when the worker cannot resolve it autonomously.

3. **Worker cherry-pick and revert workflow** — when routed by the overseer, the worker has a defined path for moving the out-of-scope commit to its correct branch and reverting it from the current PR.

4. **Audit log event** — a new `out-of-scope-commit` event type is added to the `audit/oversight-log.jsonl` catalog to record the detection, the disposition, and the acknowledging actor.

This spec does NOT cover:

- Automated commit-by-commit parsing or traceability enforcement before review (no pre-commit hook, no automated diff scanner). Detection is reviewer-driven.
- Commits that are in-scope for the PR but have minor formatting or content issues. This protocol applies only to commits a reviewer judges as not belonging to the PR's stated issue.
- Changes to the merge-authority matrix or step manifest schema. The out-of-scope commit flag integrates into the existing sign-off register and overseer bounce path.
- Enforcing commit message conventions beyond what is already required by `contract/OVERSIGHT-CONTRACT.md` §2 (git trailers).

---

## 3. Requirements

### R1 — Reviewer detection and structured flagging

**R1.1** Any base-team reviewer (code-reviewer, security-reviewer, privacy-reviewer, or any other role conducting a diff review) that identifies a commit not traceable to the PR's stated issue must flag it in its sign-off register entry using the structured field `Out_of_scope_commits:`.

**R1.2** The `Out_of_scope_commits:` field must contain one entry per flagged commit in the following format:

```
Out_of_scope_commits:
  - sha: <short SHA or full SHA>
    files: [<list of affected file paths>]
    stated_issue: <issue number or "unknown">
    reason: <one sentence — why this commit does not belong in this PR>
```

**R1.3** When `Out_of_scope_commits:` is populated, the reviewer's register entry `Status:` must be `ESCALATED`. An `out-of-scope-commit` flag is a blocking finding: the reviewer must not set `Status: APPROVED` while out-of-scope commits are unresolved.

**R1.4** The `Out_of_scope_commits:` field is optional and absent (or explicitly `none`) when the reviewer finds no out-of-scope commits. Absence is the clean state. A present field with one or more entries triggers R2.

**R1.5** Any reviewer role may flag out-of-scope commits, not only the security reviewer. The flag is a structural anomaly, not a security finding; the reviewer that first notices it logs it, regardless of role.

**R1.6** The `Out_of_scope_commits:` flag is cleared ONLY when the originating reviewer (the reviewer whose register entry carries the flag) re-reviews the updated diff and explicitly removes the field (or sets it to `none`) and updates their `Status:` accordingly. No other agent, artifact, or automated process edits the reviewer's register entry to clear this flag.

**R1.7** A human-acceptance artifact (R2.5) is a separate surface from the sign-off register. Its existence does NOT cause the `Out_of_scope_commits:` field to be edited or removed from the reviewer's entry. The overseer evaluates both surfaces independently:

- SHAs covered by a valid human-acceptance artifact are treated as **resolved-by-human** for merge-gate purposes.
- SHAs not covered by any artifact remain **live** and block merge.

The flag in the register entry persists as written by the reviewer. The overseer treats it as live whenever it is present, regardless of any acceptance artifact. There is no silent clearing.

---

### R2 — Overseer response protocol

**R2.1** Before applying the merge-authority matrix, the overseer must inspect the sign-off register for any entry with a non-empty `Out_of_scope_commits:` field. If one or more such entries exist, the overseer must not proceed to merge. It must select one of two response paths:

- **Path A (worker-resolvable):** Route the PR back to the worker via `record_pr_bounce()` with `reason_category: COMPLIANCE_FAILURE` and a `summary` sentence naming the flagged commit SHA(s). The worker is directed to either (a) cherry-pick the out-of-scope commit to its correct branch and revert it from the current PR (see R3), or (b) obtain a human confirmation artifact that the cross-issue inclusion is intentional (see R2.3).

- **Path B (human escalation):** Escalate to a human via `HUMAN_REQUIRED` with `reason_category: FINDINGS_NOT_RESOLVED` when any of the following conditions are met (whichever occurs first):
  1. **Same-SHA re-appearance:** Any SHA named in the current `Out_of_scope_commits:` flag was also named in a prior bounce on this `cid` (correlation ID for this PR), regardless of the current `bounce_count(cid)`. The overseer must not bounce the same SHA a second time autonomously.
  2. **Bounce-count cap:** `bounce_count(cid) >= 2` under the existing bounce-count governance (§4 bounce-back gate).

**R2.2** Out-of-scope bounces use the existing `record_pr_bounce()` function and the existing `bounce_count(cid)` counter. No parallel or separate counter is maintained for out-of-scope bounces. The bounce counts toward the same cap (`bounce_count(cid) >= 2 → HUMAN_REQUIRED`) that governs all other bounce categories.

**R2.3** The out-of-scope flag check is performed inside the existing §4 bounce-back gate, after the register-completeness check and before the merge-authority matrix. The ordering within the §4 gate is:
  1. Register-completeness check (all required sign-off fields present).
  2. Out-of-scope commit flag check (this spec — R2.1 through R2.5).
  3. Merge-authority matrix evaluation.

A PR with an unresolved out-of-scope flag does not reach step 3.

**R2.4** The overseer's bounce comment (Path A) must name the specific commit SHA(s) and the flagged file(s), and must present both options (cherry-pick-and-revert, or human confirmation artifact) as required resolutions. The worker must choose one and complete it before resubmitting.

**R2.5** Human confirmation path: a human may accept an out-of-scope commit as intentional by creating `.claudetmp/oversight/step{N}-out-of-scope-accepted.md` with a `Date:`, `Authorized_by:`, `Commit_sha:`, and `Reason:` field. When this artifact exists and covers the flagged SHA(s), the overseer treats those SHAs as **resolved-by-human** for merge-gate purposes (see R1.7). The overseer must verify that every flagged SHA is either covered by the artifact or has been resolved by the originating reviewer before proceeding. A partial artifact does not clear unaddressed SHAs.

---

### R3 — Worker cherry-pick and revert workflow

**R3.1** When the overseer routes the PR to the worker under Path A (R2.1), the worker must follow this workflow to resolve the out-of-scope commit:

1. Identify the correct target branch for the out-of-scope commit (the branch associated with the stated issue in the `Out_of_scope_commits:` flag). See R3.3 for constraints: the worker may not create branches and may not push to a branch that has an open PR.
2. Cherry-pick the out-of-scope commit to the correct branch: `git cherry-pick <sha>` on the target branch.
3. Revert the out-of-scope commit from the current PR's branch: `git revert <sha>` (a new revert commit, not a destructive history edit).
4. Push the cherry-pick to the target branch and the revert to the current PR's branch.
5. Update the sign-off register: clear the `Out_of_scope_commits:` field (or set it to `none`) and update `Status:` on the reviewer's entry. The reviewer who originally flagged the commit must re-review the updated diff and confirm the out-of-scope commit is gone before the register entry is updated to `APPROVED`.

**R3.2** The worker must use `git revert` (a new commit) to remove the out-of-scope commit from the current PR branch. Force-push and interactive rebase are not permitted on a PR branch — they rewrite history visible to reviewers and destroy the audit trail of the original flag.

**R3.3** The worker may cherry-pick ONLY to an existing target branch that has NO open PR of its own at the time of the cherry-pick. The worker must check both conditions before proceeding:
  - If the target branch does not exist: escalate to the human. The worker must not create a branch speculatively.
  - If the target branch exists but has an open PR of its own: escalate to the human. The worker must not push commits to a branch that is already under active PR review.

**R3.4** After the cherry-pick and revert are complete, the worker must re-submit the PR for overseer evaluation. The register must reflect the resolved state before re-submission.

---

### R4 — Audit log event

**R4.1** A new `out-of-scope-commit` event type is added to the `audit/oversight-log.jsonl` catalog. A detection event and a resolution event are defined.

The detection event is NOT emitted as a standalone event at the moment the flag is found. It is appended as part of the confirmed-comment-posted sequence: the detection event is written to the audit log in the same halt-on-failure unit as the bounce or escalation comment post, sharing the `comment_posted` gate. If the comment post fails, neither the comment nor the detection event is recorded — the overseer halts. This prevents a detection event from existing in the log without a corresponding PR comment, and prevents double-logging when the disposition is a bounce or escalation.

The resolution event remains a separate, standalone event emitted when the out-of-scope commit is resolved (either via cherry-pick-and-revert or via human acceptance artifact).

Technical-design specifies the exact append ordering within the confirmed-comment-posted sequence.

**R4.2** Detection event schema:

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

**R4.3** Resolution event schema:

```json
{
  "event": "out-of-scope-commit",
  "phase": "resolved",
  "pr": "<PR number or URL>",
  "step": "<step id>",
  "resolution": "cherry-pick-reverted | human-accepted",
  "authorized_by": "<human name or agent name>",
  "commits": ["<sha>", "..."],
  "timestamp": "<ISO-8601>"
}
```

**R4.4** The `human-accepted` resolution value is used when the resolution was a human confirmation artifact (R2.3). The `cherry-pick-reverted` value is used when the worker completed the cherry-pick and revert workflow (R3.1). Both values are mutually exclusive for a given SHA.

**R4.5** The `comment_posted: true` field in the detection event confirms the comment was successfully posted before the event was written. This field is always `true` in a committed detection event — a detection event with `comment_posted: false` is not a valid log entry and must never be written. The halt-on-failure behavior is defined in R4.1; this field is the log-level confirmation that the gate was satisfied.

---

## 4. Acceptance Criteria

**AC1 — Reviewer detection produces a structured flag.**
Given a reviewer identifies a commit that does not belong in the PR (e.g., `docs/architecture/ADR-001-pilot.md` content from issue #125 committed to the wrong branch), when the reviewer writes its sign-off register entry, then the entry contains a correctly structured `Out_of_scope_commits:` field with `sha`, `files`, `stated_issue`, and `reason` sub-fields, and `Status: ESCALATED`.

**AC2 — Overseer blocks merge on unresolved flag.**
Given a sign-off register contains a non-empty `Out_of_scope_commits:` field, when the overseer runs its pre-merge gate, then the overseer does not evaluate the merge-authority matrix and instead routes the PR via Path A (bounce to worker) or Path B (human escalation per R2.1).

**AC3 — Worker cherry-pick and revert resolves the flag (originating reviewer must re-review).**
Given the overseer bounced the PR to the worker with Path A, when the worker completes the cherry-pick to the correct branch and the revert on the PR branch, then the ORIGINATING reviewer (the one whose entry carries the `Out_of_scope_commits:` field) must re-review the updated diff, remove the `Out_of_scope_commits:` field (or set it to `none`), and update their `Status:` to `APPROVED`. No other agent or artifact edits the reviewer's register entry. Only after the originating reviewer's entry is updated does the overseer proceed to the merge-authority matrix on re-submission.

**AC4 — Human confirmation artifact marks SHAs as resolved-by-human (register entry unchanged).**
Given a human creates `.claudetmp/oversight/step{N}-out-of-scope-accepted.md` with the required fields covering all flagged SHAs, when the overseer runs its pre-merge gate on re-submission, then the overseer treats each covered SHA as resolved-by-human and proceeds to the merge-authority matrix — WITHOUT editing or clearing the reviewer's `Out_of_scope_commits:` field. The field persists in the register as written by the reviewer.

**AC5 — Same-SHA re-appearance triggers immediate human escalation; bounce-count cap also applies.**
Given the overseer encounters an `Out_of_scope_commits:` flag naming a SHA that was already named in a prior bounce on the same `cid`, when the overseer runs its pre-merge gate, then the overseer immediately issues `HUMAN_REQUIRED` with `reason_category: FINDINGS_NOT_RESOLVED` regardless of the current `bounce_count(cid)`. Separately, if `bounce_count(cid) >= 2` for any reason, the overseer also escalates rather than bouncing again.

**AC6 — Detection event is appended in the same unit as the confirmed comment post; resolution event is separate.**
Given an out-of-scope commit flag is detected and then resolved, when `audit/oversight-log.jsonl` is read, then: (a) the detection event (with `phase: detected`, the flagged SHAs, and `comment_posted: true`) appears in the log only if the bounce or escalation comment was successfully posted — no detection event exists without a corresponding PR comment; and (b) a separate resolution event (with `phase: resolved` and the correct `resolution` value) is appended when the commit is resolved. There is no standalone detection event emitted prior to the comment-post confirmation.

---

## 5. Non-Requirements

**NR1 — No automated pre-commit or pre-review scanning.** This protocol is triggered by a reviewer's judgment, not by automated diff parsing. The system does not attempt to automatically detect commits whose content does not match the PR's issue at the point of commit or push. Detection is exclusively reviewer-driven.

**NR2 — Not all commits are blocked automatically.** Only commits that a reviewer has specifically flagged as out-of-scope require explicit acknowledgment. A reviewer who does not flag a commit has implicitly accepted it as in-scope for the PR. No blanket traceability gate is introduced for every commit in every PR.

**NR3 — No new commit-message convention is required.** This protocol does not add a commit-message field for issue traceability. The existing `Prompt-Artifact:` git trailer (contract §2) is not extended. Traceability is asserted through reviewer review, not through commit metadata.

**NR4 — Worker may not create branches or push to contested branches.** The worker cherry-picks only to an existing target branch that has no open PR of its own. Branch creation is a human judgment call, not an autonomous worker action (R3.3).

**NR5 — Force-push and interactive rebase are not introduced.** The revert workflow uses `git revert` exclusively. Destructive history editing on PR branches is explicitly excluded (R3.2).

**NR6 — This protocol does not apply to human-opened PRs.** Consistent with the overseer's existing scope, the out-of-scope commit pre-merge gate applies only to PRs opened by the overseer (identified by an `[AI: overseer]` title prefix). Human-opened PRs are outside this protocol's scope.

---

## 6. Affected Artifacts

| Artifact | Change type | Summary |
|---|---|---|
| `contract/OVERSIGHT-CONTRACT.md` §3 | Additive | Document `Out_of_scope_commits:` as an optional structured field in the sign-off register schema; document that its presence forces `Status: ESCALATED` |
| `contract/OVERSIGHT-CONTRACT.md` §6a | Additive | Add new `out-of-scope-commit` event type to the audit-log catalog with detection and resolution schemas |
| `.claudetmp/oversight/step{N}-out-of-scope-accepted.md` | Additive | Document the human confirmation artifact path and required fields in the contract filesystem protocol (§1) |
| `.claude/agents/overseer.md` | Additive | Add out-of-scope commit pre-merge gate check (before merge-authority matrix); implement Path A bounce and Path B human escalation logic; emit audit events; verify human confirmation artifact covers all flagged SHAs |
| Reviewer agents (code-reviewer, security-reviewer, and all base-team reviewers) | Additive | Document the `Out_of_scope_commits:` field, its format, and the obligation to set `Status: ESCALATED` when populated |

No new files are created by the implementation other than the per-step human confirmation artifact when a human elects to accept an out-of-scope commit. No existing required fields are renamed or removed. Contract version is not bumped (additive-only change per §8).
