# SPEC-328: Out-of-Scope Commits Protocol

**Status:** Draft — for architect review
**Issue:** #328
**Author:** pm-agent
**Date:** 2026-06-17

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

---

### R2 — Overseer response protocol

**R2.1** Before applying the merge-authority matrix, the overseer must inspect the sign-off register for any entry with a non-empty `Out_of_scope_commits:` field. If one or more such entries exist, the overseer must not proceed to merge. It must select one of two response paths:

- **Path A (worker-resolvable):** Route the PR back to the worker via `record_pr_bounce()` with `reason_category: COMPLIANCE_FAILURE` and a `summary` sentence naming the flagged commit SHA(s). The worker is directed to either (a) cherry-pick the out-of-scope commit to its correct branch and revert it from the current PR (see R3), or (b) obtain a human confirmation artifact that the cross-issue inclusion is intentional (see R2.3).

- **Path B (human escalation):** If the PR has already been bounced once for the same out-of-scope commit flag and the flag is still unresolved on re-submission, the overseer must escalate to a human via `HUMAN_REQUIRED` with `reason_category: FINDINGS_NOT_RESOLVED`. The overseer must not bounce the same out-of-scope commit flag a second time autonomously.

**R2.2** The overseer's bounce comment (Path A) must name the specific commit SHA(s) and the flagged file(s), and must present both options (cherry-pick-and-revert, or human confirmation artifact) as required resolutions. The worker must choose one and complete it before resubmitting.

**R2.3** Human confirmation path: a human may accept an out-of-scope commit as intentional by creating `.claudetmp/oversight/step{N}-out-of-scope-accepted.md` with a `Date:`, `Authorized_by:`, `Commit_sha:`, and `Reason:` field. When this artifact exists and covers the flagged SHA(s), the overseer treats the flag as resolved and proceeds. The overseer must verify that every flagged SHA has a matching entry in the artifact before treating the flag as resolved; a partial authorization does not clear unaddressed commits.

**R2.4** The out-of-scope flag check is performed in the overseer's pre-merge gate, before the merge-authority matrix is evaluated. A PR with an unresolved out-of-scope flag does not reach the merge-authority matrix.

---

### R3 — Worker cherry-pick and revert workflow

**R3.1** When the overseer routes the PR to the worker under Path A (R2.1), the worker must follow this workflow to resolve the out-of-scope commit:

1. Identify or create the correct target branch for the out-of-scope commit (the branch associated with the stated issue in the `Out_of_scope_commits:` flag).
2. Cherry-pick the out-of-scope commit to the correct branch: `git cherry-pick <sha>` on the target branch.
3. Revert the out-of-scope commit from the current PR's branch: `git revert <sha>` (a new revert commit, not a destructive history edit).
4. Push the cherry-pick to the target branch and the revert to the current PR's branch.
5. Update the sign-off register: clear the `Out_of_scope_commits:` field (or set it to `none`) and update `Status:` on the reviewer's entry. The reviewer who originally flagged the commit must re-review the updated diff and confirm the out-of-scope commit is gone before the register entry is updated to `APPROVED`.

**R3.2** The worker must use `git revert` (a new commit) to remove the out-of-scope commit from the current PR branch. Force-push and interactive rebase are not permitted on a PR branch — they rewrite history visible to reviewers and destroy the audit trail of the original flag.

**R3.3** If the target branch for the out-of-scope commit does not exist and the worker cannot determine the correct branch, the worker must escalate to the human rather than create a branch speculatively.

**R3.4** After the cherry-pick and revert are complete, the worker must re-submit the PR for overseer evaluation. The register must reflect the resolved state before re-submission.

---

### R4 — Audit log event

**R4.1** A new `out-of-scope-commit` event type is added to the `audit/oversight-log.jsonl` catalog. The event is emitted by the overseer at the point of detection (when the flag is found in the register during the pre-merge gate). A second event is emitted at resolution.

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

**R4.5** The `comment_posted: true` field in the detection event must follow the same convention as other disposition events: the audit event is appended only after the bounce or escalation comment is confirmed posted. If the comment post fails, the overseer halts rather than logging a detection event with no corresponding PR comment.

---

## 4. Acceptance Criteria

**AC1 — Reviewer detection produces a structured flag.**
Given a reviewer identifies a commit that does not belong in the PR (e.g., `docs/architecture/ADR-001-pilot.md` content from issue #125 committed to the wrong branch), when the reviewer writes its sign-off register entry, then the entry contains a correctly structured `Out_of_scope_commits:` field with `sha`, `files`, `stated_issue`, and `reason` sub-fields, and `Status: ESCALATED`.

**AC2 — Overseer blocks merge on unresolved flag.**
Given a sign-off register contains a non-empty `Out_of_scope_commits:` field, when the overseer runs its pre-merge gate, then the overseer does not evaluate the merge-authority matrix and instead routes the PR via Path A (bounce to worker) or Path B (human escalation per R2.1).

**AC3 — Worker cherry-pick and revert resolves the flag.**
Given the overseer bounced the PR to the worker with Path A, when the worker completes the cherry-pick to the correct branch and the revert on the PR branch and the original reviewer re-confirms the diff, then the reviewer's register entry is updated to remove the `Out_of_scope_commits:` field and set `Status: APPROVED`, and the overseer proceeds to the merge-authority matrix on re-submission.

**AC4 — Human confirmation artifact resolves the flag.**
Given a human creates `.claudetmp/oversight/step{N}-out-of-scope-accepted.md` with the required fields covering all flagged SHAs, when the overseer runs its pre-merge gate on re-submission, then the overseer treats the flag as resolved and proceeds to the merge-authority matrix.

**AC5 — Second bounce for the same flag triggers human escalation.**
Given the overseer has already bounced a PR once for a specific out-of-scope commit SHA and the flag is still unresolved on re-submission, when the overseer runs its pre-merge gate, then the overseer issues `HUMAN_REQUIRED` with `reason_category: FINDINGS_NOT_RESOLVED` rather than a second bounce.

**AC6 — Audit log records detection and resolution events.**
Given an out-of-scope commit flag is detected and then resolved, when `audit/oversight-log.jsonl` is read, then it contains both an `out-of-scope-commit` detection event (with `phase: detected`, the flagged SHAs, and `comment_posted: true`) and a resolution event (with `phase: resolved` and the correct `resolution` value matching the path taken).

---

## 5. Non-Requirements

**NR1 — No automated pre-commit or pre-review scanning.** This protocol is triggered by a reviewer's judgment, not by automated diff parsing. The system does not attempt to automatically detect commits whose content does not match the PR's issue at the point of commit or push. Detection is exclusively reviewer-driven.

**NR2 — Not all commits are blocked automatically.** Only commits that a reviewer has specifically flagged as out-of-scope require explicit acknowledgment. A reviewer who does not flag a commit has implicitly accepted it as in-scope for the PR. No blanket traceability gate is introduced for every commit in every PR.

**NR3 — No new commit-message convention is required.** This protocol does not add a commit-message field for issue traceability. The existing `Prompt-Artifact:` git trailer (contract §2) is not extended. Traceability is asserted through reviewer review, not through commit metadata.

**NR4 — Worker is not required to create the target branch.** If the correct target branch for the out-of-scope commit does not exist, the worker escalates to a human (R3.3). Branch creation decisions are a human judgment call, not an autonomous worker action.

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
