# SPEC-222: CONDITIONAL_PROCEED as Blocking PR Threads

**Status:** Draft — for architect review
**Issue:** #222
**Author:** pm-agent
**Date:** 2026-06-17
**Companion:** `SPEC-overseer-merge-authority.md` §1 (this spec elaborates the requirements
first written there; this document supersedes §1 as the canonical requirements source for #222)

---

## 1. Problem Statement

When the oversight-evaluator returns CONDITIONAL_PROCEED, the oversight-orchestrator
appends a "Human Review Required Before Merge" section to the PR body before opening the
PR. The section enumerates the items the human must verify. The existing agent instructions
(`oversight-orchestrator.md` CONDITIONAL_PROCEED path) specify that these items live in
`handoff.md`, which becomes the PR body, and include a `grep -q "Human Review Required Before Merge"`
assertion before opening the PR.

This mechanism has a mechanical gap: GitHub's merge gate enforces resolved review threads,
not PR body content. A PR body section is prose — it is visible to the human but invisible to
GitHub's branch protection rules. `gh pr merge` succeeds when all required status checks pass
and all required review threads are resolved, regardless of whether the PR body prose was
ever read or actioned. A CONDITIONAL_PROCEED PR can therefore be merged with the conditional
items never addressed.

The semantic requirement — "a human must verify these items before merge" — is stated in the
existing agent instructions but is not mechanically enforced. The mechanical enforcement is
missing. This is not a documentation gap or an agent instruction gap; it is a structural gap
in how the oversight pipeline converts a CONDITIONAL_PROCEED verdict into a merge block.

The fix is to convert each conditional item from PR body prose into a posted, unresolved PR
review thread. GitHub's branch protection rule "Require resolved conversations" then becomes
the mechanical enforcement: `gh pr merge` is blocked until each thread is explicitly resolved
by a human reviewer. The semantic requirement and the mechanical enforcement become the same
thing.

---

## 2. Scope

This spec covers:

1. **Oversight-orchestrator CONDITIONAL_PROCEED path** (`.claude/agents/oversight-orchestrator.md`):
   after opening the PR, the orchestrator must post one PR review thread per conditional item
   via `gh pr review --comment`, request a human review, and post a worker summary comment.
   The conditional items must continue to appear in the PR body (for context) but the threads
   are the enforcement mechanism.

2. **Oversight-evaluator Phase 1 compliance check** (`.claude/agents/oversight-evaluator.md`
   and `contract/OVERSIGHT-CONTRACT.md`): when the evaluator reviews a CONDITIONAL_PROCEED
   step, it must verify that the PR has unresolved conditional threads — not merely that the
   PR body includes the items. An evaluator running against a PR that has no conditional threads
   despite a CONDITIONAL_PROCEED verdict must treat this as a compliance gap and escalate.

3. **Branch protection requirement** (`contract/OVERSIGHT-CONTRACT.md` and
   `docs/MACHINE-ACCOUNTS-SETUP.md`): the contract must document that any branch targetted by
   CONDITIONAL_PROCEED PRs must have "Require a minimum number of approvals" set to 1 and
   "Require conversation resolution before merging" enabled. These settings are prerequisites
   for the thread-blocking mechanism to function as intended.

This spec does NOT cover:

- The PROCEED path. A PROCEED-verdict PR carries no conditional items and posts no conditional
  threads.
- The ESCALATE path. ESCALATE does not open a PR. No threads are posted.
- The panel review threads posted by `run_panel.sh`. Panel threads are a separate mechanism;
  this spec covers only the conditional items posted by the orchestrator.
- Requiring the human to write a specific reply format when resolving a thread. The resolution
  is a native GitHub conversation-resolve action; the content of any reply is not constrained.
- Retroactive enforcement. PRs opened under the prior prose mechanism (before this spec is
  implemented) are not subject to re-gating. `SPEC-370-conditional-proceed-audit.md` covers
  the audit of those prior PRs.

---

## 3. Requirements

### R1 — Each conditional item becomes a PR review thread

When the oversight-orchestrator acts on a CONDITIONAL_PROCEED evaluator verdict:

**R1.1** After opening the PR, the orchestrator must post one PR review thread per item in
the evaluator's conditional items list, using `gh pr review <PR_NUMBER> --comment --body "<thread body>"`.
Each thread must be posted as a separate comment — not combined into one multi-item comment.

**R1.2** Each thread body must contain, in order:
1. The conditional item description verbatim from the evaluator output.
2. A one-sentence explanation of why this item requires human confirmation before merge.
3. The resolution options available to the human reviewer, enumerated:
   - APPROVE — "I have read this item; it does not block merge."
   - REQUEST CHANGES — "This item reveals a problem; do not merge."
   - CLOSE WITHOUT MERGING — "Abandon this change."
4. The instruction: "Resolve this thread by replying with one of the options above.
   Do not dismiss without replying."

**R1.3** The conditional items must continue to appear in the "Human Review Required Before
Merge" section of the PR body, as currently specified. The threads are the enforcement
mechanism; the body section is the readable summary. Both must be present. The body section
must include a note stating: "Each item above has a corresponding unresolved review thread.
Merge is blocked until all threads are resolved."

**R1.4** The existing `grep -q "Human Review Required Before Merge"` assertion (before opening
the PR) is unchanged. It remains a pre-open check that the body section was written. A
companion post-open assertion must verify that the number of successfully posted threads
equals the number of conditional items. If fewer threads were posted than items (e.g., a
`gh pr review` call failed), the orchestrator must halt and print the discrepancy rather
than silently proceeding.

### R2 — Branch protection must enforce resolved conversations

**R2.1** Any repository branch that can receive a CONDITIONAL_PROCEED PR (any branch that
is a valid `--base` target when the orchestrator opens a PR) must have the following
GitHub branch protection rule enabled:

- "Require a minimum number of approvals" set to 1, with the approver being `HOSOversightTutelare`
  or the human reviewer (`HUMAN_REVIEWER` from `machine-accounts.env`).
- "Require conversation resolution before merging" enabled.

Without conversation resolution enforcement, posted threads do not block `gh pr merge` — R1
posts threads but R2 is what makes them block.

**R2.2** The contract (`contract/OVERSIGHT-CONTRACT.md`) must document "Require conversation
resolution before merging" as a prerequisite for the CONDITIONAL_PROCEED thread-blocking
mechanism to function. This is a project setup requirement, not a per-step runtime check.
The machine-accounts setup guide (`docs/MACHINE-ACCOUNTS-SETUP.md`) must include a step
confirming this branch protection setting.

**R2.3** The orchestrator is not responsible for verifying branch protection is enabled at
runtime — that is a project setup invariant. However, if the orchestrator detects that
`gh api repos/{owner}/{repo}/branches/{base}/protection` returns no conversation-resolution
requirement, it must emit a warning in its PR summary comment. The warning does not block PR
opening — the branch protection gap is a setup deficiency, not a per-PR runtime error.

### R3 — Oversight-evaluator Phase 1 check verifies threads exist

When the oversight-evaluator runs Phase 1 compliance check against a step that carries a
CONDITIONAL_PROCEED verdict:

**R3.1** The evaluator must query the PR's review threads (via `gh pr view <PR_NUMBER> --json reviews`
or equivalent) and verify that at least one unresolved thread posted by the orchestrator
account (`HOSOversightTutelare`) exists. If no such thread exists and the step has conditional
items → **COMPLIANCE WARN** (not FAIL — the threads may have been resolved by a human before
the evaluator runs; an evaluator running post-resolution is expected). The warning must state
how many conditional items the evaluator verdict listed and that no unresolved orchestrator
threads were found.

**R3.2** The evaluator must NOT treat all-resolved threads as a COMPLIANCE FAIL. A PR where
a human resolved all conditional threads before the evaluator re-runs is in the correct state —
the threads did their job. The evaluator notes this as "conditional items resolved" and allows
the step to proceed.

**R3.3** The evaluator must NOT treat unresolved threads as blocking evaluation. The purpose
of the Phase 1 check is to verify the threads were posted. Whether they are resolved is the
human's action and the branch protection's gate — not the evaluator's gate. The evaluator
records thread state in its output but does not fail on unresolved threads.

**R3.4** If the evaluator is running in a context where no PR number is available (e.g., a
local pre-PR evaluation run), R3.1 is not applicable. The evaluator skips the thread-existence
check and notes this in its output.

### R4 — Human reviewer receives a review request

**R4.1** After posting the conditional threads, the orchestrator must request a review from
the human reviewer account (read from `machine-accounts.env:HUMAN_REVIEWER`) using
`gh pr edit <PR_NUMBER> --add-reviewer <HUMAN_REVIEWER>`. The review request is what triggers
GitHub to notify the human.

**R4.2** After posting the threads and requesting the review, the orchestrator must post a
single summary comment on the PR (distinct from the conditional threads) addressed to the
worker account. The comment must state:
- Count of conditional threads opened.
- Instruction: "This PR has N unresolved conditional threads. The HOSWorkerTutelare
  account must not close or re-push this branch until a human resolves all threads."

**R4.3** The ledger record for the overseer's action on a CONDITIONAL_PROCEED PR must include
a `conditional_threads_opened` field with the integer count of threads successfully posted.

---

## 4. Non-Requirements

- **Does not apply to the PROCEED path.** A PROCEED-verdict PR has no conditional items and
  posts no threads. The PROCEED PR opening flow is unchanged.

- **Does not require the human to close the threads.** The human resolves threads by actioning
  them (replying and using GitHub's "resolve conversation" UI). Alternatively, the overseer may
  resolve a thread when it has been explicitly authorized to do so (per the merge-authority matrix
  in `overseer.md`). This spec does not restrict who may resolve a thread — it only requires
  that threads exist and that branch protection blocks merge while they remain open.

- **Does not require threads to target specific diff lines.** R1.1 uses `gh pr review --comment`
  (a general PR comment with review semantics), not a line-level comment. Conditional items
  are evaluator-level findings, not file-line findings. Line-level targeting is not required.

- **Does not change the evaluator verdict logic.** What triggers CONDITIONAL_PROCEED versus
  PROCEED or ESCALATE is defined in `oversight-evaluator.md`. This spec does not change those
  conditions.

- **Does not change the PR body format.** The "Human Review Required Before Merge" section
  continues to be appended to the handoff document before PR opening, as currently specified
  in `oversight-orchestrator.md`. R1.3 adds a note to that section pointing to the threads;
  it does not reformat or move the section.

- **Does not introduce a new audit event.** The `CONDITIONAL_PROCEED` audit event already
  records that a step carried conditional items. The ledger `conditional_threads_opened` field
  (R4.3) is sufficient to record that threads were posted. No new `audit/oversight-log.jsonl`
  event type is required by this spec.

---

## 5. Acceptance Criteria

| ID | Criterion |
|---|---|
| AC-1 | A CONDITIONAL_PROCEED PR cannot be merged while any orchestrator-posted conditional thread remains unresolved, given branch protection "Require conversation resolution before merging" is enabled |
| AC-2 | Each conditional item from the evaluator output has exactly one corresponding PR review thread posted by the orchestrator |
| AC-3 | Each thread body contains the four required elements from R1.2, in order |
| AC-4 | The PR body "Human Review Required Before Merge" section is present AND includes the note directing the reviewer to the threads |
| AC-5 | The human reviewer account (`HUMAN_REVIEWER`) receives a review request on every CONDITIONAL_PROCEED PR |
| AC-6 | The worker summary comment is posted; it states the thread count and the no-close/no-push instruction to HOSWorkerTutelare |
| AC-7 | The ledger entry includes `conditional_threads_opened` with the correct integer count |
| AC-8 | A PROCEED-verdict PR opens no conditional threads |
| AC-9 | Posting N conditional items results in exactly N threads posted; if any `gh pr review` call fails, the orchestrator halts and reports the discrepancy |
| AC-10 | The oversight-evaluator, running after a CONDITIONAL_PROCEED PR was opened, emits a COMPLIANCE WARN (not FAIL) if no unresolved orchestrator threads are found |
| AC-11 | The oversight-evaluator, running after all threads have been resolved by a human, records "conditional items resolved" and does not block the step |
| AC-12 | The contract documents "Require conversation resolution before merging" as a prerequisite for CONDITIONAL_PROCEED enforcement |

---

## 6. Affected Artifacts

| Artifact | Change type | Summary |
|---|---|---|
| `.claude/agents/oversight-orchestrator.md` | Additive | CONDITIONAL_PROCEED path: add thread-posting steps after PR open; add R4.2 summary comment; add R4.3 ledger field; add post-open thread-count assertion |
| `contract/OVERSIGHT-CONTRACT.md` §1 | Additive | Document "Require conversation resolution before merging" branch protection as a prerequisite for CONDITIONAL_PROCEED enforcement |
| `contract/OVERSIGHT-CONTRACT.md` §7 | Additive | Add evaluator Phase 1 thread-existence COMPLIANCE WARN (R3.1) for CONDITIONAL_PROCEED steps |
| `.claude/agents/oversight-evaluator.md` | Additive | Phase 1: add thread-existence check for CONDITIONAL_PROCEED steps (R3.1–R3.4) |
| `docs/MACHINE-ACCOUNTS-SETUP.md` | Additive | Add branch protection setup step confirming "Require conversation resolution before merging" is enabled |

No new files are created. The existing PR body format is not restructured. The `CONDITIONAL_PROCEED`
audit event is not changed. Contract version is not bumped (additive-only change per contract §8).
