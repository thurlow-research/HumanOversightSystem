# TECHNICAL DESIGN — SPEC-222 R1 (thread posting) + R2 (verification)

**Spec:** `docs/specs/SPEC-222-conditional-proceed-thread-blocking.md`
**Issues:** #222 (mechanism), #399 (human clearance on merge-gate default — RESOLVED, R2 cleared)
**Author:** technical-design
**Date:** 2026-06-18
**Scope of this document:** R1 (orchestrator thread posting) and the residual R2 work
(verification call in `setup_branch_protection.sh`). The R2 payload flip
(`required_conversation_resolution: true`) already shipped in commit `dc1a7d8` (#387,
OM-4 architect decision). R3 (evaluator checks R3.1/R3.3/R3.4) and the R4.3 ledger field
already shipped.

---

## 1. R1.5 — Empirical API verification (PREREQUISITE, completed before R1 implementation)

**Question (R1.5):** Does `gh pr review <PR> --comment --body "..."` create a thread that the
`required_conversation_resolution` branch-protection rule blocks merge on?

**Answer: NO.** `gh pr review --comment` issues `POST /repos/{o}/{r}/pulls/{n}/reviews` with
`event=COMMENT` and a top-level `body` and no `comments[]` array. That creates a *pull request
review* carrying a summary body. It does **not** create a `PullRequestReviewThread`. The
`required_conversation_resolution` gate blocks merge only on **unresolved review threads** —
the objects exposing `isResolved` in GraphQL and the "Resolve conversation" button in the UI.
A review summary body has no `isResolved` state and no resolve button, so it does not block merge.

For completeness, the three comment surfaces and their gate behavior:

| Surface | API | Creates a `PullRequestReviewThread`? | Blocks merge under `required_conversation_resolution`? |
|---|---|---|---|
| Issue comment | `gh pr comment` / `POST .../issues/{n}/comments` | No | No |
| Review summary body | `gh pr review --comment` / `POST .../pulls/{n}/reviews` (body, no `comments[]`) | No | No |
| Review thread | `POST .../pulls/{n}/comments` (path+line) or GraphQL `addPullRequestReviewThread` | **Yes** | **Yes** |

**Decision (R1.5 binding):** R1.1's prescribed `gh pr review --comment` does NOT satisfy the
mechanical-enforcement intent of the spec (§1: "the semantic requirement and the mechanical
enforcement become the same thing"). Per R1.5's explicit escape clause, the implementation
**MUST use the GraphQL `addPullRequestReviewThread` mutation**, which creates a resolvable,
merge-blocking `PullRequestReviewThread`.

This finding is recorded as an inline comment block in the orchestrator R1 section so the
coder/overseer running the path understands why GraphQL is used in place of the spec's literal
`gh pr review --comment`.

---

## 2. R1 — Thread posting contract (oversight-orchestrator CONDITIONAL_PROCEED path)

### 2.1 Inputs

- `PR_NUMBER` — created in step 3 of the existing CONDITIONAL_PROCEED path.
- `.claudetmp/oversight/step{N}-handoff.md` — contains the "⚠ Human Review Required Before
  Merge" section whose numbered items (`^[0-9]+\. `) are the conditional items, verbatim.
- `ITEM_COUNT` — count of numbered items (already computed in the existing step 5 via
  `grep -cE '^[0-9]+\. '`).

### 2.2 Thread anchor

`addPullRequestReviewThread` requires a file (or line) anchor — GitHub review threads must
attach to a path; there is no "whole-PR" thread. Conditional items are evaluator-level findings,
not file-line findings (spec Non-Requirement: "Does not require threads to target specific diff
lines"). To honor that while still producing a resolvable thread, every conditional thread is
anchored at **FILE level** (`subjectType: FILE`) on the **first file in the PR diff** —
deterministic, guaranteed in-diff, and semantically neutral. The item's own `{file:line}`
reference stays in the thread body.

- `ANCHOR_PATH = first entry of` `gh pr view "$PR_NUMBER" --json files --jq '.files[0].path'`.
- `PR_NODE_ID = ` `gh pr view "$PR_NUMBER" --json id --jq '.id'`.

### 2.3 Per-item thread body (R1.2 — four elements, in order)

For each numbered conditional item:

1. The conditional item description **verbatim** from the handoff section.
2. A one-sentence **why**: "This item was a resolved finding or confidence gap that automated
   review could not fully clear, so a human must confirm it before merge."
3. **Resolution options**, enumerated (R1.2.3):
   - APPROVE — "I have read this item; it does not block merge."
   - REQUEST CHANGES — "This item reveals a problem; do not merge."
   - CLOSE WITHOUT MERGING — "Abandon this change."
4. The instruction (R1.2.4): "Resolve this thread by replying with one of the options above.
   Do not dismiss without replying. The overseer will check before any auto-merge attempt."

### 2.4 Posting algorithm (R1.1, R1.4)

1. Resolve `PR_NODE_ID` and `ANCHOR_PATH`.
2. Initialize `POSTED=0`.
3. For each numbered item in the handoff section (one thread per item — never combined):
   - Build the body (2.3).
   - Call GraphQL `addPullRequestReviewThread(input: {pullRequestId, path, subjectType: FILE, body})`.
   - On success, `POSTED++`. On failure, do not increment; continue collecting so the final
     discrepancy is reported.
4. **Post-open assertion (R1.4):** if `POSTED != ITEM_COUNT`, the orchestrator must **halt** and
   print the discrepancy (`expected $ITEM_COUNT threads, posted $POSTED`) rather than silently
   proceeding. This is a hard stop — a partial post leaves an under-enforced PR.

### 2.5 Ledger (R1 / R4.3)

`conditional_threads_opened` in the `conditional_proceed` audit event becomes `$POSTED` (the
true posted-thread count), replacing the hardcoded `0`. The field already exists in the event
schema (shipped earlier); only its value source changes.

### 2.6 Body section note (R1.3)

The "⚠ Human Review Required Before Merge" section already appears in the PR body (existing
step 2). R1.3's required note ("Each item above has a corresponding unresolved review thread.
Merge is blocked until all threads are resolved.") is added to that appended block.

### 2.7 Boundaries (what the orchestrator must NOT do here)

- Must not combine items into one thread (R1.1).
- Must not proceed on a thread-count shortfall (R1.4) — halt instead.
- Must not resolve the threads it posts. Resolution is the human's action / branch-protection's
  gate (R3.3, Non-Requirement).
- Must not change the PROCEED or ESCALATE paths.

---

## 3. R2 — Verification call in setup_branch_protection.sh

**Payload flip:** already done (commit `dc1a7d8`, line 135: `"required_conversation_resolution": true`).
No further payload change required.

**Residual work (this design):** the `_check` verification block at the end of the script
(lines 209–214) verifies `dismiss_stale_reviews`, `require_code_owner_reviews`, and
`required_approving_review_count` but does NOT verify `required_conversation_resolution`. Add one
`_check` call matching the existing pattern:

```
_check "required_conversation_resolution" \
  "required_conversation_resolution" "true"
```

`required_conversation_resolution` is a top-level field of the protection response (not nested
under `required_pull_request_reviews`), so the query is the bare key. The existing `_check`
python walker handles a single top-level key and prints `true`/`false` lowercased for booleans —
matching the `"true"` expected value.

**Boundary:** this is a verification-only addition. It changes no payload and no merge behavior;
it surfaces drift if a later edit silently reverts the flip.

---

## 4. Affected artifacts (this design)

| Artifact | Change |
|---|---|
| `.claude/agents/oversight-orchestrator.md` | CONDITIONAL_PROCEED path: replace the "not yet implemented" stub with R1 thread-posting (GraphQL `addPullRequestReviewThread`), R1.3 body note, R1.4 post-open assertion, R4.3 ledger value `$POSTED`. Record the R1.5 finding inline. |
| `scripts/framework/setup_branch_protection.sh` | Add `_check "required_conversation_resolution"` verification call. |

---

## 5. Self-flag

RISK: MEDIUM — the design changes how a CONDITIONAL_PROCEED verdict becomes a mechanical merge
block; an error posts no threads or a wrong count, weakening the gate. Mitigated by the R1.4
hard-stop assertion and the R3 evaluator tamper-check that cross-references the ledger.
CONFIDENCE: HIGH on the API finding (R1.5) — the review-body-vs-review-thread distinction is a
well-established GitHub model; the GraphQL mutation is the documented path for creating
resolvable threads.
Classification: **additive** (no prior CONDITIONAL_PROCEED code was approved against a posting
contract — the path was an explicit "not yet implemented" stub; no existing sign-off is
invalidated). Not structural: the merge-gate default flip (R2 payload) was already cleared via
#399/OM-4 and shipped separately.

## Human Review Required Before Merge

- Confirm the FILE-level anchor on the first diff file is acceptable as the thread attachment
  point (the alternative — LINE-level on a specific item line — would couple threads to file
  positions the conditional items do not actually reference).
