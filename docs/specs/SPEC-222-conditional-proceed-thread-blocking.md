# SPEC-222: CONDITIONAL_PROCEED as Blocking PR Threads

**Status:** REVISED — pending human clearance on branch-protection flip (see issue #399)
**Issue:** #222
**Author:** pm-agent
**Date:** 2026-06-17
**Revised:** 2026-06-17 — architect REQUEST_CHANGES applied: R1.5 (API verification), R2 product
boundary checkpoint + startup-artifact-gap, R3 WARN/FAIL distinction (tamper signal), AC-10
update, setup_branch_protection.sh added to §6 Affected Artifacts. Classification: R1.5 and
AC-10 are structural (new requirement / behavior change); R2 notes are structural (new decision
gate); setup_branch_protection.sh entry is structural (pending #399); startup-artifact-gap note
is clarifying.
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

**R1.5** The orchestrator implementation MUST empirically verify that the chosen GitHub API
call creates a thread resolvable by the `required_conversation_resolution` branch protection
rule. If `gh pr review --comment` does NOT produce such threads (i.e., GitHub does not treat
general review comments as "conversations" for the purposes of the branch protection gate),
the implementation must use the GraphQL `addPullRequestReviewThread` API instead.
Technical-design must confirm which API creates resolvable threads before implementing R1.
This verification must be completed before any R1 implementation is submitted for review.

### R2 — Branch protection must enforce resolved conversations

**R2.1** Any repository branch that can receive a CONDITIONAL_PROCEED PR (any branch that
is a valid `--base` target when the orchestrator opens a PR) must have the following
GitHub branch protection rule enabled:

- "Require a minimum number of approvals" set to 1, with the approver being `hos-overseer-hos[bot]`
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

**Product boundary checkpoint (R2):** The branch-protection flip required by R2 changes the
merge gate default for ALL PRs on any branch that receives CONDITIONAL_PROCEED PRs — not only
CONDITIONAL_PROCEED PRs. This affects all existing installs from the moment `setup_branch_protection.sh`
is re-run. Technical-design may build R1 (thread posting) and R4 (ledger field) without this
checkpoint. The branch-protection flip (R2) and the evaluator tamper-check (R3.2) bind only
after pm-agent + human explicitly confirm that changing the merge gate default is acceptable
for all existing installs. Issue #399 tracks this clearance. Do not implement R2 or R3.2 until
#399 is resolved.

**Startup-artifact-gap:** `scripts/framework/setup_branch_protection.sh` currently sets
`"required_conversation_resolution": false` at line 140 of that file. This spec adds
`setup_branch_protection.sh` as an Affected Artifact (see §6). Until this spec ships and
`setup_branch_protection.sh` is updated, new installs default to `required_conversation_resolution:
false`, meaning the thread-blocking mechanism is installed but not mechanically enforced on
those installs. This is a known startup-artifact-gap — tracked in issue #399.

### R3 — Oversight-evaluator Phase 1 check verifies threads exist

When the oversight-evaluator runs Phase 1 compliance check against a step that carries a
CONDITIONAL_PROCEED verdict:

**R3.1** The evaluator must query the PR's review threads (via `gh pr view <PR_NUMBER> --json reviews`
or equivalent) and cross-reference the ledger's `conditional_threads_opened` field. The
compliance outcome is determined as follows:

- **COMPLIANCE WARN:** No unresolved orchestrator threads are found AND the ledger shows
  `conditional_threads_opened = 0`. This is an ambiguous state — threads may have been resolved
  by a human before the evaluator runs, or may never have been posted. The warning must state
  how many conditional items the evaluator verdict listed, that no unresolved orchestrator
  threads were found, and that the ledger records zero threads opened.

- **COMPLIANCE FAIL (tampering signal):** The ledger shows `conditional_threads_opened > 0`
  (the orchestrator recorded that it posted threads) BUT the evaluator finds zero unresolved
  threads AND zero resolved-thread evidence on the PR (no thread resolution events from any
  account). This combination means threads were reportedly posted but have vanished with no
  resolution record — a tampering signal. The evaluator must escalate with COMPLIANCE FAIL,
  state the discrepancy (ledger count vs. observed thread state), and halt evaluation.

The warning must state how many conditional items the evaluator verdict listed and the ledger
`conditional_threads_opened` count for context.

**R3.2** The evaluator must NOT treat all-resolved threads as a COMPLIANCE FAIL. A PR where
a human resolved all conditional threads before the evaluator re-runs is in the correct state —
the threads did their job. The evaluator notes this as "conditional items resolved" and allows
the step to proceed. (Note: R3.2 binds only after human clearance on issue #399 — see the
product boundary checkpoint under R2.)

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
- Instruction: "This PR has N unresolved conditional threads. The hos-worker-hos[bot]
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
| AC-6 | The worker summary comment is posted; it states the thread count and the no-close/no-push instruction to hos-worker-hos[bot] |
| AC-7 | The ledger entry includes `conditional_threads_opened` with the correct integer count |
| AC-8 | A PROCEED-verdict PR opens no conditional threads |
| AC-9 | Posting N conditional items results in exactly N threads posted; if any `gh pr review` call fails, the orchestrator halts and reports the discrepancy |
| AC-10 | The oversight-evaluator emits COMPLIANCE WARN (not FAIL) when no unresolved orchestrator threads are found AND the ledger shows `conditional_threads_opened = 0` (ambiguous state); it emits COMPLIANCE FAIL when the ledger shows `conditional_threads_opened > 0` but zero threads and zero resolved-thread evidence are found on the PR (tampering signal) |
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
| `scripts/framework/setup_branch_protection.sh` | Structural (pending #399) | Flip `"required_conversation_resolution": false` to `true` at line 140; add a `_check "required_conversation_resolution"` verification call matching the `_check()` pattern at lines 214–219. This change MUST NOT be implemented until issue #399 (human clearance on merge-gate default change) is resolved. |

No new files are created. The existing PR body format is not restructured. The `CONDITIONAL_PROCEED`
audit event is not changed. Contract version is not bumped (additive-only change per contract §8).
