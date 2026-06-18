# SPEC-220 — Step-Head Timing: Re-Write After Panel (step-head-final Event)

**Issue:** #220
**Status:** Draft — for architect review
**Family:** #204 commit-range machinery
**Date:** 2026-06-17
**Author:** pm-agent

---

## 1. Problem Statement

The `step-head` audit event is written by the evaluator at the end of Phase 1 (pre-PR,
approximately Phase 7 of the pipeline). It records `head_sha` — the commit that was
HEAD when evaluation ran. The next step uses this value as its `BASE_SHA`.

The panel phase (Phases 9–10) can produce additional commits. When the cross-vendor
panel (`run_panel.sh`) raises findings, the base team makes fix commits on the same
branch before the PR merges. These panel-fix commits land *after* the `step-head`
event was written, so they are not included in the recorded `head_sha`.

When the next step begins, the evaluator reads the most recent `step-head` for the
previous step and uses it as `BASE_SHA`. Because that SHA predates the panel-fix
commits, those commits fall outside the next step's computed `base_sha..head_sha`
window. The risk-assessor, prompt-artifact check, and all range-verification checks
will miss them. The panel-fix commits effectively belong to no step's audit trail.

The fix is to write a second, final `step-head` record — the `step-head-final` event —
after the PR is merged (Phase 10 complete), recording the actual post-panel HEAD. The
next step's evaluator uses the `step-head-final` SHA preferentially when one exists.

---

## 2. Scope

**In scope:**
- `oversight-orchestrator.md`: after the PR is merged (or after Phase 10 completes
  with no PR — e.g. a documentation-only step closed without a PR), write a
  `step-head-final` event to `audit/oversight-log.jsonl` recording the post-merge
  `head_sha`.
- `oversight-evaluator.md` Phase 1: when computing `BASE_SHA` for a step, prefer the
  most recent `step-head-final` event for the previous step over the plain `step-head`
  event. Fall back to `step-head` if no `step-head-final` exists for the previous step
  (backward compatibility).

**Out of scope:**
- Changing the existing `step-head` event format or when it is written. It continues
  to be written at Phase 7 by the evaluator. This spec adds a second, later event; it
  does not remove or replace the early one.
- Any change to how `run_panel.sh` operates, what it checks, or when it fires.
- Retroactively re-writing `step-head` events for already-closed steps.
- Steps with no panel activity (no panel-fix commits). The orchestrator writes the
  `step-head-final` event regardless — it is always the authoritative final SHA for
  the step, even when `step-head-final.head_sha == step-head.head_sha` (no panel-fix
  commits were made). Consistent writing avoids conditional logic in the evaluator's
  lookup.

---

## 3. Requirements

### R1 — `oversight-orchestrator.md`: write `step-head-final` after PR merge

After the PR for step N is merged (the orchestrator receives confirmation that the merge
completed, or detects the merged state via `gh pr view`), the orchestrator must append
a `step-head-final` event to `audit/oversight-log.jsonl`:

```json
{
  "event": "step-head-final",
  "step": N,
  "head_sha": "<40-char full SHA of HEAD after merge>",
  "panel_fix_commits": K,
  "timestamp": "<ISO-8601 UTC>"
}
```

Field definitions:
- `head_sha`: the result of `git rev-parse HEAD` after the merge commit lands on the
  branch (or after the PR is confirmed merged and the local branch is fast-forwarded).
  Full 40-character hex. Not abbreviated.
- `panel_fix_commits`: integer count of commits between the Phase 7 `step-head.head_sha`
  and this `head_sha` that were authored after the `step-head` event was written. This
  is an informational field for research data (it is the observable panel-fix commit
  count); it does not gate anything. If the orchestrator cannot cheaply compute it,
  the field may be omitted on a first implementation and added later — it is NOT
  required for correctness. `head_sha` is required; `panel_fix_commits` is advisory.
- `timestamp`: ISO-8601 UTC at the moment of writing.

**When Phase 10 closes without a PR** (e.g. a documentation-only step or a step that
was resolved without opening a PR — the orchestrator wrote a handoff with
`ESCALATE`/no-PR): write the `step-head-final` event using the current HEAD at the
time the orchestrator determines Phase 10 is complete for this step. The event still
provides a clean anchor for the next step's `BASE_SHA`.

### R2 — `oversight-evaluator.md` Phase 1: prefer `step-head-final` when computing BASE_SHA

The evaluator's Phase 1 `BASE_SHA` derivation (the block "First, establish the step's
commit range and write the register header") must be updated to look for
`step-head-final` before falling back to `step-head`:

```bash
# Prefer step-head-final (post-panel) over step-head (pre-panel) for previous step.
PREV_HEAD=$(grep -h '"event":"step-head-final"' audit/oversight-log.jsonl 2>/dev/null \
  | grep "\"step\":$((N-1))\b" | tail -1 \
  | sed -n 's/.*"head_sha":"\([0-9a-f]*\)".*/\1/p')

# Fall back to step-head if no step-head-final exists for the previous step.
if [ -z "$PREV_HEAD" ]; then
  PREV_HEAD=$(grep -h '"event":"step-head"' audit/oversight-log.jsonl 2>/dev/null \
    | grep "\"step\":$((N-1))\b" | tail -1 \
    | sed -n 's/.*"head_sha":"\([0-9a-f]*\)".*/\1/p')
fi

# For step 1 (no previous step), fall back to merge-base.
BASE_SHA="${PREV_HEAD:-$(git merge-base HEAD \
  "$(git remote show origin 2>/dev/null | sed -n 's/.*HEAD branch: //p' || echo main)")}"
HEAD_SHA=$(git rev-parse HEAD)
```

This lookup is backward-compatible: steps evaluated before this spec ships have no
`step-head-final` events, so the evaluator falls through to the existing `step-head`
lookup without behavioral change.

The step-scoped grep (`grep "\"step\":$((N-1))\b"`) is important. The existing
evaluator snippet used `tail -1` on all `step-head` events without filtering by step,
which would return the most recent `step-head` from *any* step, not necessarily the
previous step. R2 makes the step scope explicit for both the `step-head-final` and
`step-head` lookups. This is a correctness fix bundled with the new lookup; it applies
to the fallback path too.

### R3 — `audit/oversight-log.jsonl` event catalog: add `step-head-final`

The event catalog in `contract/OVERSIGHT-CONTRACT.md` §6a must be updated to document
the new event type:

| event | written by | when |
|---|---|---|
| `step-head-final` | oversight-orchestrator | After PR merge (or Phase 10 close without PR) — records the post-panel final HEAD SHA for the step |

This is a documentation requirement on the contract, not a behavioral requirement on
any script. The catalog entry must include all fields from R1's JSON schema.

---

## 4. Non-Requirements

- This spec does not require the orchestrator to re-run any review or re-evaluate any
  compliance check after writing `step-head-final`. It is a recording action only.
- This spec does not require the orchestrator to detect whether panel-fix commits
  introduced new risk. That is a separate concern for a future spec; panel-fix commits
  are currently outside the inner-loop review chain by design.
- This spec does not require the evaluator to re-derive its own `head_sha` after Phase
  10. The evaluator runs at Phase 7 and records its own `head_sha` in the register;
  that value is correct for Phase 7. The `step-head-final` event supplements it for
  the *next step's* `BASE_SHA` derivation.
- This spec does not require `step-head-final` to be written atomically or in the same
  commit as the merge. The orchestrator appends it after confirming the merge state.
- This spec does not require the `panel_fix_commits` field. It is advisory research
  data; omitting it is acceptable in a first implementation.

---

## 5. Acceptance Criteria

AC-1. After any step's PR merges, `audit/oversight-log.jsonl` contains a
      `step-head-final` event for that step with a non-empty, 40-character `head_sha`
      and a valid ISO-8601 `timestamp`.

AC-2. When a step has panel-fix commits (commits landed after the Phase 7 `step-head`
      event), `step-head-final.head_sha` differs from `step-head.head_sha` for that
      step.

AC-3. When a step has no panel-fix commits, `step-head-final.head_sha` equals
      `step-head.head_sha` for that step.

AC-4. The next step's evaluator uses `step-head-final.head_sha` as `BASE_SHA` when a
      `step-head-final` event exists for the previous step (verified by checking that
      the `base_sha` in the next step's register equals the `step-head-final.head_sha`
      of the previous step).

AC-5. When no `step-head-final` event exists for the previous step (e.g. an older step
      evaluated before this spec shipped), the evaluator falls back to `step-head`
      without error or compliance warning.

AC-6. The step-scoped grep in the evaluator's `BASE_SHA` derivation matches on step
      number, not just on event type — so a `step-head-final` for step 5 is not used
      as `BASE_SHA` for step 4.

AC-7. `contract/OVERSIGHT-CONTRACT.md` §6a contains an entry for `step-head-final`
      with `written by: oversight-orchestrator` and the correct `when` description.
