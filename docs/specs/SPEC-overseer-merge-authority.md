# SPEC — Overseer Merge Authority (v0.4.0)

**Status:** draft — for technical-design
**Issues:** #222, #302, #325
**Companion:** `SPEC-317-worker-pre-pr-gate.md` (worker pre-PR gate — cross-referenced, not duplicated here)
**Depends on:** `overseer.md` CORE, `OVERSIGHT-CONTRACT.md`, `machine-accounts.env`
**Written by:** pm-agent · 2026-06-16

---

## Purpose

This spec covers three operational gaps in the overseer's autonomous-mode behavior:

1. CONDITIONAL_PROCEED items must block merge as unresolved PR review threads, not prose (#222)
2. Oversight loop correctness — S1–S5 operational requirements from live monitoring (#302)
3. Overseer-side empty-PR guard — required companion to the worker pre-open check (#325)

S6 (pipeline-completeness check) is not covered here. S6 requirements depend on
evaluator artifact definitions from `SPEC-evaluator-re-derivation.md` §2/§3. Write
S6 requirements after that spec is finalized.

Sections are independent. Technical-design may sequence them across build steps
as it sees fit.

---

## §1 — CONDITIONAL_PROCEED as blocking threads (#222)

### Background

When the oversight-evaluator returns CONDITIONAL_PROCEED, the overseer currently
places "human must read before merge" items as prose in the PR body. Branch
protection gates only on resolved review threads — prose items are invisible to
GitHub's merge gate. A CONDITIONAL_PROCEED PR can therefore be merged while the
conditional items are never actioned.

The fix: each conditional item must be a posted, unresolved PR review thread so
that branch protection's "require resolved conversations" gate blocks merge until
a human explicitly resolves each one.

### Requirements

**R1.1 — Thread per conditional item.**
When the overseer opens or acts on a PR whose evaluator verdict is CONDITIONAL_PROCEED,
it must open one unresolved PR review thread per item listed in the evaluator's
conditional items list. These threads are opened via the GitHub pull-request review
comments API. They are NOT placed in the PR body.

**R1.2 — Thread body contents.**
Each thread body must contain, in order:

1. The conditional item description verbatim from the evaluator output.
2. A one-sentence explanation of why this item requires human confirmation before
   merge (e.g., "Second-review verdict was unparseable — a human must read the
   raw report and confirm it contains no blocking findings.").
3. The resolution options available to the human reviewer, enumerated:
   - APPROVE — "I have read the item, it does not block merge."
   - REQUEST CHANGES — "This item reveals a problem; do not merge."
   - CLOSE WITHOUT MERGING — "Abandon this change."
4. The instruction: "Resolve this thread by replying with one of the options
   above. Do not dismiss without replying."

**R1.3 — Reviewer assignment.**
The overseer must request a review from `ScottThurlow` (read from
`machine-accounts.env:HUMAN_REVIEWER`) at the same time it posts the threads.
The reviewer request is what causes GitHub to notify the human.

**R1.4 — Worker notification.**
After posting the threads and requesting the review, the overseer must post a
single summary comment on the PR (distinct from the review threads) with:
- Count of conditional threads opened.
- Instruction to HOSWorkerTutelare: "This PR has N unresolved conditional
  threads. The worker must not close or re-push this branch until a human
  resolves all threads."

**R1.5 — CONDITIONAL_PROCEED does not trigger AUTO_MERGE.**
The merge-authority matrix (overseer.md CORE step 5) already requires
HUMAN_REQUIRED for CONDITIONAL/ESCALATE verdicts. R1.1–R1.4 are the specific
mechanism that enforces this. The matrix row is unchanged; this spec specifies
the mechanical implementation that makes CONDITIONAL_PROCEED merge-blocking.

**R1.6 — Thread count in ledger entry.**
The ledger record for the overseer's action on a CONDITIONAL_PROCEED PR must
include a `conditional_threads_opened` field with the integer count.

### Acceptance Criteria

- AC-1.1: A PR with CONDITIONAL_PROCEED evaluator verdict cannot be merged
  while any overseer-posted conditional thread remains unresolved.
- AC-1.2: Each conditional item from the evaluator output has exactly one
  corresponding unresolved PR review thread.
- AC-1.3: Each thread body contains the four required elements in R1.2.
- AC-1.4: `ScottThurlow` receives a review-requested notification on every
  CONDITIONAL_PROCEED PR.
- AC-1.5: The worker summary comment is posted; it references the thread count.
- AC-1.6: Ledger entry includes `conditional_threads_opened`.
- AC-1.7: A PR with PROCEED verdict and no conditional items opens no conditional
  threads.

---

## §2 — Oversight loop operational requirements (S1–S5 from #302)

### Background

A 36-hour live monitoring run of the overseer's `/loop` mode revealed five
operational gaps. Suggestions S1–S5 from #302 are v0.4.0 requirements. S6 is
deferred (see Purpose section above). S7 (heartbeat file) is deferred to a later
pass.

### S1 — Base-branch scope

**R2.1 — Poll protected branches, not only main.**
The overseer's PR-discovery query must include all protected base branches, not
only `main`. The protected branch list is: `main`, all branches matching
`release/v*`, and any branches listed in the step manifest as protected.

**R2.2 — Discovery implementation.**
The overseer must issue one `gh pr list --base <branch> --state open` query per
protected branch, or equivalently one `gh pr list --state open` query filtered
client-side. Either approach is acceptable; the result must be the union of open
PRs targeting any protected branch.

**R2.3 — Step manifest is the authority.**
If the step manifest defines a `protected_branches` key, its value is the
authoritative list and supersedes the defaults in R2.1.

### Acceptance Criteria

- AC-2.1: An open PR targeting `release/v0.3.x` is discovered and processed by
  the overseer in the same tick that would discover a PR targeting `main`.
- AC-2.2: A PR targeting an unprotected feature branch is NOT picked up by the
  overseer discovery loop.

---

### S2 — Immediate notification on new PR discovery

**R2.4 — State file on empty tick.**
After each tick that finds zero qualifying open PRs, the overseer must write
`.claudetmp/oversight-state.json` with the current timestamp and the empty-queue
state. If the file already exists, it must be updated in place.

**R2.5 — New-PR notification path.**
On any tick that finds one or more PRs not present in the previous state file
(i.e., newly discovered PRs), the overseer must immediately post a notification
to the human rather than waiting for the next scheduled read. The notification
must include: PR number, title, base branch, risk tier if readable from
`panel-context.md`, and the time elapsed since the PR was opened.

**R2.6 — HIGH and CRITICAL escalate immediately.**
For a newly discovered PR whose risk tier is HIGH or CRITICAL, the notification
must be labelled `[URGENT]` and posted before the overseer begins its review
cycle on that PR. The review cycle must not proceed silently.

### Acceptance Criteria

- AC-2.3: `.claudetmp/oversight-state.json` is written after every empty tick.
- AC-2.4: A PR that opens between tick T and tick T+1 is surfaced to the human
  as a notification at tick T+1 without waiting for another cycle.
- AC-2.5: A HIGH-tier PR triggers an `[URGENT]` notification before the review
  cycle begins.

---

### S3 — Durable stop-time

**R2.7 — Stop instruction persists across session restarts.**
When the human instructs the overseer to stop at a specific time (e.g., "stop at
9am"), the overseer must record the stop time in a durable settings file at
`.claudetmp/oversight-schedule.json` before creating any cron job. Format:

```json
{
  "stop_at": "<ISO-8601 datetime>",
  "created_at": "<ISO-8601 datetime>",
  "loop_job_tag": "<cron-job-id>"
}
```

**R2.8 — Session-start recovery.**
On each session start in autonomous mode, before creating a new cron job, the
overseer must read `.claudetmp/oversight-schedule.json` if it exists. If a
`stop_at` value is present and is in the future, the overseer must recreate the
stop job targeting that time without prompting the human again.

**R2.9 — Stop skill.**
The overseer must expose a `/stop-oversight-loop` skill that: reads all active
cron job IDs from `.claudetmp/oversight-schedule.json`, deletes each job by ID,
clears the schedule file, and confirms to the human that the loop is stopped. This
skill is usable from both interactive and autonomous modes.

### Acceptance Criteria

- AC-2.6: After a session restart, the oversight loop stops at the originally
  instructed time without re-prompting the human.
- AC-2.7: `/stop-oversight-loop` deletes all active loop jobs and clears the
  schedule file.
- AC-2.8: If `.claudetmp/oversight-schedule.json` does not exist on session
  start, no recovery is attempted and no error is surfaced.

---

### S4 — Per-tick state file for stale-PR detection

**R2.10 — State file contents.**
`.claudetmp/oversight-state.json` must include, for each known open PR:
- `pr_number`
- `first_seen` (ISO-8601 timestamp of the tick when the PR was first observed)
- `last_checked` (ISO-8601 timestamp of the most recent tick)
- `sign_off_status` (value read from the sign-off register on last check, or
  `"unknown"` if not yet read)
- `second_review_status` (value from the second-review output file on last
  check, or `"unknown"`)

**R2.11 — Stale-PR escalation.**
If a PR has been in `oversight-state.json` with no sign-off movement for more
than 48 hours, the overseer must escalate to the human with label `needs-human`
and a comment explaining the stale state. "No sign-off movement" means the
`sign_off_status` field has not changed across two consecutive ticks separated
by at least 48 hours.

**R2.12 — PR removal on close.**
When the overseer observes a PR transition to closed or merged state, it must
remove that PR's entry from the state file within the same tick.

### Acceptance Criteria

- AC-2.9: State file contains entries for all open PRs observed in the current
  tick, with all five required fields.
- AC-2.10: A PR that has been open for 48+ hours with no sign-off change
  receives a `needs-human` escalation comment.
- AC-2.11: Closed or merged PRs are removed from the state file in the tick
  they are observed as closed.

---

### S5 — Duplicate loop job guard

**R2.13 — Pre-creation deduplication.**
Before creating a new cron job for the oversight loop, the overseer must call
`CronList` and inspect the results for an existing job whose prompt matches the
loop prompt (match on the identifying prefix: "HOS oversight loop"). If a
matching job exists, the overseer must reuse it and not create a new job. The
existing job ID must be written to `.claudetmp/oversight-schedule.json`.

**R2.14 — Human notification on skip.**
If creation is skipped because an existing job was found, the overseer must
inform the human: "Oversight loop already running (job ID: `<id>`). Reusing
existing job — no new job created."

**R2.15 — Stale job cleanup.**
If `CronList` returns multiple jobs matching the loop prompt (indicating a
prior failure to deduplicate), the overseer must: delete all but the most
recently created matching job, log the deleted job IDs, and notify the human
that duplicate jobs were found and cleaned up.

### Acceptance Criteria

- AC-2.12: Invoking `/loop` twice in the same session creates exactly one cron
  job, not two.
- AC-2.13: Invoking `/loop` in a fresh session when an existing loop job is
  active produces no new job and notifies the human of the reuse.
- AC-2.14: If two duplicate loop jobs exist at session start, one is deleted
  and the human is informed.

---

## §3 — Empty-PR guard: overseer side (#325)

### Background

Worker-side requirements for the empty-PR guard are in `SPEC-worker-operational.md` §7
(R7.1, R7.3). This section specifies the overseer's companion obligation. The
worker is supposed to prevent empty-branch PRs from being opened; the overseer
guard is defense-in-depth for cases where the worker pre-open check fails or is
bypassed.

### Requirements

**R3.1 — Pre-review empty check.**
Before running any part of its review cycle on a PR (before reading the
sign-off register, before dispatching any reviewer agent, before applying
the merge-authority matrix), the overseer must verify that the PR branch has
at least one commit ahead of the target base using:

```bash
gh pr diff <PR-number> --name-only
```

If the output is empty, the PR has zero commits ahead of base. The overseer
must treat this as the empty-PR condition and follow R3.2–R3.5 exclusively.

**R3.2 — Structured comment.**
The overseer must post a structured comment on the PR:

```
[OVERSEER] Empty-PR guard triggered.

This PR has zero commits ahead of base. There is nothing to review.

Possible causes:
- The branch was rebased and all commits were already upstream.
- The branch was reset to match the base.

Action required: close this PR and investigate the branch state.

The oversight review cycle has NOT been run. No sign-off was recorded.
```

**R3.3 — Label: needs-human.**
The overseer must apply the `needs-human` label to the PR. It must NOT apply
`needs-ai`. The worker created the condition by failing the pre-open check;
resolution requires human judgment about whether the fix is truly upstream.

**R3.4 — No sign-off register entry.**
The overseer must NOT write any entry to the sign-off register for an empty-PR.
Writing a sign-off entry would misrepresent that oversight occurred when no
reviewable content was present.

**R3.5 — No reviewer agents dispatched.**
The overseer must NOT dispatch any reviewer agents (oversight-evaluator,
risk-assessor, or any panel reviewer) for an empty-PR. Dispatching reviewers
on an empty diff produces meaningless output and wastes resources.

**R3.6 — Branch intact.**
The overseer must NOT close the branch, delete it, or request its deletion.
Branch state is the worker's domain. The overseer's action is limited to the
comment and label.

**R3.7 — Ledger event.**
The overseer must append an `empty-pr-guard` event to the audit ledger:

```json
{
  "event": "empty-pr-guard",
  "pr": <PR-number>,
  "base": "<base-branch>",
  "head": "<head-branch>",
  "action": "needs-human-labeled, no review run",
  "timestamp": "<ISO-8601>"
}
```

### Acceptance Criteria

- AC-3.1: A PR with zero commits ahead of base receives the structured comment
  in R3.2 verbatim (or with only `<base>` substituted).
- AC-3.2: The `needs-human` label is applied; `needs-ai` is not.
- AC-3.3: No sign-off register entry exists for the PR after overseer processing.
- AC-3.4: No oversight-evaluator, risk-assessor, or panel reviewer invocation
  is recorded for the PR.
- AC-3.5: The head branch still exists after the overseer's action.
- AC-3.6: An `empty-pr-guard` event appears in the audit ledger for the PR.
- AC-3.7: A non-empty PR (one commit ahead of base) is not affected by this
  guard and proceeds to normal review.

---

## Cross-references

| Section | Cross-reference |
|---|---|
| §1 (CONDITIONAL threads) | `overseer.md` CORE step 6 (act on decision — HUMAN_REQUIRED path); `OVERSIGHT-CONTRACT.md` §3 (sign-off schema) |
| §2 S1–S5 (loop) | `overseer.md` CORE step 7 (heartbeat); `scripts/framework/hos_orchestrator.sh` |
| §3 (empty-PR guard) | `SPEC-worker-operational.md` §7 R7.1 (worker pre-open check); `SPEC-317-worker-pre-pr-gate.md` §4 (bounce-back rule) |
| S6 (pipeline completeness) | Deferred to `SPEC-evaluator-re-derivation.md` §2/§3 — write S6 requirements after that spec is finalized |
