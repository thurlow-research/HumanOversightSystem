# Technical Design — Overseer Merge Authority (v0.4.0)

**Status:** draft — requesting architect review (iteration 1)
**Source spec:** `docs/specs/SPEC-overseer-merge-authority.md`
**Issues:** #222, #302, #325
**Depends on:** `.claude/agents/overseer.md` CORE, `.claude/agents/oversight-orchestrator.md`, `OVERSIGHT-CONTRACT.md`, `scripts/framework/machine-accounts.env`
**Written by:** technical-design · 2026-06-16

---

## HOS self-flag (this document)

```
RISK: MEDIUM
CONFIDENCE: MEDIUM
BLAST RADIUS: overseer autonomous flow (overseer.md CORE), oversight-orchestrator.md,
  CONDITIONAL_PROCEED merge-blocking behavior on every PR, overseer poll scope.
```

Change classification: **structural** for §1 (changes the merge-gate enforcement
mechanism from prose to GitHub review threads — alters a human-approval gate's
mechanical contract) and **structural** for §2 S1 (broadens which PRs the overseer
acts on autonomously). §2 S2–S5 and §3 are **additive**.

### ## Human Review Required

This design changes the *mechanism* by which CONDITIONAL_PROCEED is enforced
(§1) and broadens the overseer's autonomous poll scope to all protected branches
(§2 S1). Both touch the safety-critical human-approval gate and the autonomous
merge surface. Per the authoring contract a structural change to a human gate is
escalated to a human before the contract is handed to the coder.

**The specific points needing human/architect decision are enumerated in
"Open questions for the architect" at the end.** The most load-bearing:
the task prompt and the SPEC describe two *different* substrates for the overseer
(an agent-prompt overseer using `.claudetmp/` vs. a Python automation layer
using `.ai-local/hos-automation/` with `probe.py`/`merge_authority.py`). That
discrepancy must be resolved before coding §2.

---

## 0. Substrate reconciliation (READ FIRST — blocks §2)

The three inputs disagree on what the overseer *is*:

| Input | Overseer substrate | State paths cited |
|---|---|---|
| `overseer.md` CORE (shipped) | An **agent prompt** invoked by `hos_orchestrator.sh --class overseer`; references `merge_authority.py`, `breakers.py`, `.claudetmp/signoffs/`, `audit/automation/<customer>/runs/` | `.claudetmp/`, `audit/automation/` |
| `SPEC-overseer-merge-authority.md` | Agent-driven; S1–S5 write to `.claudetmp/oversight-state.json`, `.claudetmp/oversight-schedule.json` | `.claudetmp/` |
| This task's §2 brief | A Python `probe.py` + per-PR state under `.ai-local/hos-automation/` | `.ai-local/hos-automation/` |

**On disk today:** there is no `probe.py`, no `merge_authority.py`, no
`breakers.py`. The only automation code present is
`scripts/automation/lib/activation.py`. `merge_authority.py` etc. are referenced
by `overseer.md` CORE but not yet implemented — they are part of the
unattended-worker work in flight (MEMORY: #254/#152).

**Design decision taken in this document (subject to architect override —
OQ-1):** Follow the **SPEC** as the authoritative artifact (the SPEC is the
pm-approved contract for this work; the task brief is a paraphrase). Therefore:

- State files live under **`.claudetmp/`** (matching the SPEC and `overseer.md`
  CORE), **not** `.ai-local/hos-automation/`. Rationale: `overseer.md` CORE
  already reads `.claudetmp/signoffs/`; `.claudetmp/` is the established
  oversight-runtime location. `.ai-local/` is the worker's per-project runtime
  (SQC salt), a different owner. Mixing them would split overseer state across
  two trees.
- The per-PR state required by the task's S4 is folded into the SPEC's
  **single** `.claudetmp/oversight-state.json` (one object keyed by PR number),
  not one file per PR. Rationale: the SPEC mandates one state file with
  per-PR entries (R2.10); a single file is atomically rewriteable and avoids
  orphaned per-PR files when a PR closes (R2.12). **OQ-2** records the per-file
  alternative for the architect.
- The overseer remains **agent-prompt-driven** (edits land in `overseer.md`
  CORE), with the deterministic primitives (state read/write, stale detection,
  dedup) factored into a small helper module so they are unit-testable rather
  than living only in prompt prose. New helper: `scripts/automation/lib/overseer_state.py`
  (sibling of `activation.py`). **OQ-3** asks the architect to confirm the
  agent-prompt-plus-helper split vs. a fully scripted `probe.py`.

Everything below §1 is written against this decision. If the architect chooses
the `probe.py` / `.ai-local/` model instead, §2's paths and the helper-module
boundary change, but the field schemas and algorithms are unchanged.

---

## §1 — CONDITIONAL_PROCEED as blocking review threads (#222)

### Component map

| Component | File | Change |
|---|---|---|
| Orchestrator agent | `.claude/agents/oversight-orchestrator.md` | Rewrite the `CONDITIONAL_PROCEED` section: post one `REQUEST_CHANGES` review per conditional item; request human reviewer; post worker-summary comment; record thread count |
| Overseer agent | `.claude/agents/overseer.md` CORE step 6 (HUMAN_REQUIRED path) | Add cross-reference: when acting on a PR whose verdict is CONDITIONAL_PROCEED and the threads were not already posted at open time, post them now (idempotency guard) |
| Conditional-items source | evaluator artifact `.claudetmp/oversight/step{N}-evaluation-{ts}.md` | No change — consumed read-only |
| Ledger | `audit/oversight-log.jsonl` (and `audit/automation/<customer>/runs/` for the overseer) | New field `conditional_threads_opened` |

### Contract

**The conditional-items list.** The evaluator output is the source of truth.
The orchestrator already reads `.claudetmp/oversight/step{N}-evaluation-{ts}.md`
(its validated Inputs §). The conditional items are the numbered entries the
orchestrator currently renders into the `## ⚠ Human Review Required Before Merge`
section of `handoff.md`. **That section stays** (per spec #255 cross-reference,
AC retains the PR-body prose) — but it is no longer the enforcement mechanism;
it is the human-readable index. Enforcement moves to review threads.

**Each item must be parseable to a single thread body.** Define a conditional
item as one numbered list entry under the evaluator's conditional-items heading.
The orchestrator iterates these in order; item *i* produces thread *i*.

**API call — one review per item (R1.1, R1.2).**

For each conditional item, POST a pull-request review with event
`REQUEST_CHANGES`:

```
POST /repos/{owner}/{repo}/pulls/{pr_number}/reviews
Body:
{
  "event": "REQUEST_CHANGES",
  "body": "<thread-body>",
  "comments": []
}
```

Invoked via `gh api`:

```bash
gh api --method POST \
  "repos/${OWNER}/${REPO}/pulls/${PR}/reviews" \
  -f event=REQUEST_CHANGES \
  -f body="${THREAD_BODY}" \
  -f 'comments=[]' --input -   # see note
```

> Implementation note for the coder: `gh api -f` sends form fields as strings;
> `comments` must be a JSON array, so build the JSON payload as a file/heredoc
> and pipe via `--input -` rather than `-f comments=[]`. Exact JSON:
> `{"event":"REQUEST_CHANGES","body":"<escaped body>","comments":[]}`.
> The body must be JSON-escaped (newlines → `\n`). Prefer `jq -n --arg body "$THREAD_BODY" '{event:"REQUEST_CHANGES",body:$body,comments:[]}'`
> piped to `gh api ... --input -`.

**Thread body contents (R1.2 — required order, all four elements).**

```
<conditional item description, verbatim from the evaluator output>

Why this blocks merge: <one sentence — why this item needs human confirmation
before merge, e.g. "Second-review verdict was unparseable — a human must read
the raw report and confirm it contains no blocking findings.">

Resolve this thread by replying with one of:
- APPROVE — "I have read the item; it does not block merge."
- REQUEST CHANGES — "This item reveals a problem; do not merge."
- CLOSE WITHOUT MERGING — "Abandon this change."

Resolve this thread by replying with one of the options above. Do not dismiss
without replying.
```

Boundary: the "why this blocks merge" sentence is sourced from the evaluator
item's own rationale when present; if the evaluator item carries no rationale,
the orchestrator emits the generic fallback sentence above. The orchestrator
**must not** invent a domain-specific rationale it cannot cite.

**Reviewer request (R1.3).**

After posting all threads, request the human reviewer:

```bash
gh api --method POST \
  "repos/${OWNER}/${REPO}/pulls/${PR}/requested_reviewers" \
  -f 'reviewers[]'="${HUMAN_REVIEWER}"
```

`HUMAN_REVIEWER` is read from `scripts/framework/machine-accounts.env:HUMAN_REVIEWER`
(do not hardcode `ScottThurlow`). If the key is absent, the orchestrator
**fails closed**: it must not silently skip the reviewer request (the request is
what notifies the human). Emit an error and HALT (do not open/leave the PR in a
state where conditional items are unwatched).

**Worker-summary comment (R1.4).** One issue comment (not a review), distinct
from the threads:

```
[HOS Overseer] CONDITIONAL_PROCEED — {N} unresolved conditional thread(s) opened.

@HOSWorkerTutelare: this PR has {N} unresolved conditional thread(s). Do NOT
close or re-push this branch until a human resolves all threads.
```

The worker account name comes from `machine-accounts.env` (the `@`-mention
target — read it, do not hardcode `HOSWorkerTutelare`).

**Ledger field (R1.6).** The orchestrator's ledger record for this action gains:

```json
"conditional_threads_opened": <integer count>
```

Appended to `audit/oversight-log.jsonl` as part of the existing orchestrator
action record (and to `audit/automation/<customer>/runs/` when the overseer is
the actor per `overseer.md` CORE step 8).

**Idempotency (overseer side, overseer.md step 6).** The overseer may act on a
CONDITIONAL_PROCEED PR on a later tick. It must not re-post duplicate threads.
Guard: before posting, list existing reviews
(`GET /repos/{o}/{r}/pulls/{n}/reviews`) and count those authored by the
overseer/orchestrator account with state `CHANGES_REQUESTED`. If that count
equals the conditional-item count, the threads already exist → skip posting,
do not re-request the reviewer, do not re-post the summary comment. Record
`conditional_threads_opened` = existing count.

### Boundaries

- The orchestrator/overseer **must not** post `event: APPROVE` for a
  CONDITIONAL_PROCEED PR under any circumstance (matrix row unchanged — R1.5).
- The PR-body `## ⚠ Human Review Required Before Merge` section is retained but
  is **not** load-bearing for the merge gate; do not remove the existing
  `grep -q "Human Review Required Before Merge"` assertion in
  `oversight-orchestrator.md` CONDITIONAL_PROCEED step 3.
- Threads must be `REQUEST_CHANGES` (not `COMMENT`) — only `CHANGES_REQUESTED`
  reviews are dismissable-but-blocking under branch protection's "require
  conversation resolution" + "require review" rules. **OQ-4** flags the exact
  branch-protection setting this depends on.

### Acceptance-criteria trace

AC-1.1 → REQUEST_CHANGES review blocks merge under branch protection (OQ-4).
AC-1.2 → one review per numbered item; idempotency guard prevents duplicates.
AC-1.3 → four-element body contract above.
AC-1.4 → requested_reviewers POST with HUMAN_REVIEWER, fail-closed if absent.
AC-1.5 → worker-summary comment template references {N}.
AC-1.6 → `conditional_threads_opened` ledger field.
AC-1.7 → PROCEED path posts zero threads (orchestrator PROCEED section unchanged).

---

## §2 — Oversight loop operational requirements S1–S5 (#302)

> All paths below assume the §0 decision (`.claudetmp/`, single state file,
> agent + `overseer_state.py` helper). Architect override → see OQ-1/OQ-2/OQ-3.

### Component map

| Component | File | Change |
|---|---|---|
| State helper (new) | `scripts/automation/lib/overseer_state.py` | New module: read/write `oversight-state.json`, stale detection, PR-entry upsert/remove |
| Schedule helper (new) | folded into `overseer_state.py` or sibling | read/write `oversight-schedule.json`, recovery |
| Overseer agent | `.claude/agents/overseer.md` CORE | New autonomous-flow steps: poll-scope (S1), empty-tick + new-PR notify (S2), durable stop (S3), per-tick state (S4), dedup guard (S5) |
| Orchestrator runner | `scripts/framework/hos_orchestrator.sh` (referenced; confirm exists — see OQ-5) | Pass protected-branch list and invoke overseer per tick |

### S1 — Base-branch scope (R2.1–R2.3)

**Algorithm.** Compute the protected-branch list, then discover the union of
open PRs targeting any of them.

```
protected_branches:
  if step-manifest defines `protected_branches:` → use it verbatim (R2.3, authority)
  else → ["main"] ∪ { open branches matching glob "release/v*" }
```

The `release/v*` set is resolved at discovery time, not hardcoded:

```bash
gh api "repos/${OWNER}/${REPO}/branches" --paginate --jq '.[].name' \
  | grep -E '^(main|release/v.*)$'
```

**Discovery (R2.2).** Either per-branch queries or one filtered query is
acceptable; the design mandates the single-query form for fewer API calls:

```bash
gh pr list --state open --json number,title,baseRefName,createdAt,labels --limit 200
# client-side filter: keep PRs whose baseRefName ∈ protected_branches
```

Boundary: a PR targeting an **unprotected** feature branch must be dropped
(AC-2.2). The filter is an allow-list against `protected_branches`, never a
deny-list.

**Step-manifest key.** `contract/step-manifest.yaml` (consumer copy) may define:

```yaml
protected_branches:
  - main
  - release/v0.4.x
```

If present, this value is authoritative and the `release/v*` glob is **not**
consulted (R2.3).

### S2 — Immediate notification on new-PR discovery (R2.4–R2.6)

**Empty-tick state write (R2.4).** After a tick that finds zero qualifying PRs,
write/update `.claudetmp/oversight-state.json`:

```json
{
  "last_tick": "<ISO-8601>",
  "queue": "empty",
  "prs": {}
}
```

If the file exists, update in place (preserve `prs` from prior non-empty ticks
only if those PRs are still open — see S4 removal rule R2.12; an empty
*qualifying* set means no open protected-branch PRs, so `prs` becomes `{}`).

**New-PR detection (R2.5).** A PR is "new" if its number is **not** a key in the
prior state file's `prs` object. For each new PR, post an immediate human
notification (do not wait for the next scheduled read). Notification channel:
**OQ-6** — the SPEC says "post a notification to the human" but does not name the
channel. Default chosen here: a PR issue-comment plus a console line, because the
overseer's only durable human-facing surface is the PR thread. Architect to
confirm whether a separate notification sink (e.g. a `needs-human`-labeled
tracking issue, or stdout consumed by the cron wrapper) is required.

Notification content (R2.5):

```
[HOS Overseer] New PR discovered.
PR #{number}: {title}
Base: {baseRefName}
Risk tier: {tier from panel-context.md, or "unread"}
Open for: {elapsed since createdAt}
```

Risk tier is read from `.claudetmp/oversight/step{N}-panel-context.md`
(`Validated tier:` line) when resolvable; else `"unread"`.

**HIGH/CRITICAL urgent escalation (R2.6).** If the read tier is HIGH or CRITICAL,
prefix the notification subject with `[URGENT]` and post it **before** beginning
the review cycle for that PR. The review cycle for that PR must not begin until
the `[URGENT]` notification is posted (ordering constraint, not just labeling).

### S3 — Durable stop-time (R2.7–R2.9)

**Schedule file (R2.7).** Before creating any cron job, write
`.claudetmp/oversight-schedule.json`:

```json
{
  "stop_at": "<ISO-8601 datetime>",
  "created_at": "<ISO-8601 datetime>",
  "loop_job_tag": "<cron-job-id>"
}
```

`loop_job_tag` is filled after the job is created (it requires the returned job
ID); write `stop_at`/`created_at` first, then update `loop_job_tag` once the
`CronCreate` returns. **Invariant:** `stop_at` is persisted *before* the cron
job exists, so a crash between the two leaves a recoverable stop intent.

**Session-start recovery (R2.8).** On each autonomous session start, before
creating a new cron job:
1. If `.claudetmp/oversight-schedule.json` is absent → no recovery, no error
   (AC-2.8).
2. If present and `stop_at` is in the future → recreate the stop job targeting
   `stop_at` without re-prompting the human (AC-2.6).
3. If present and `stop_at` is in the past → the stop already lapsed; do not
   recreate; clear the file.

**Stop skill (R2.9).** Expose `/stop-oversight-loop`:
1. Read `loop_job_tag` (and any additional job IDs) from the schedule file.
2. `CronDelete` each job by ID.
3. Clear (delete or truncate to `{}`) `.claudetmp/oversight-schedule.json`.
4. Confirm to the human that the loop is stopped.
Usable in both interactive and autonomous modes.

> Boundary: the cron primitives are the runtime's `CronList`/`CronCreate`/
> `CronDelete` tools (referenced by the SPEC S5). `overseer_state.py` owns the
> JSON file; the agent owns the cron tool calls. The helper must not shell out
> to cron.

### S4 — Per-tick state for stale-PR detection (R2.10–R2.12)

**State schema (R2.10).** `.claudetmp/oversight-state.json`:

```json
{
  "last_tick": "<ISO-8601>",
  "queue": "non-empty",
  "prs": {
    "<pr_number>": {
      "pr_number": <int>,
      "first_seen": "<ISO-8601>",
      "last_checked": "<ISO-8601>",
      "sign_off_status": "<value from sign-off register | 'unknown'>",
      "second_review_status": "<value from second-review output | 'unknown'>"
    }
  }
}
```

`sign_off_status` is read from the sign-off register
(`.claudetmp/signoffs/` per `OVERSIGHT-CONTRACT.md` §3) for the PR's step.
`second_review_status` is read from the second-review output file produced by
`run_second_review.sh`. **OQ-7:** the exact register field to snapshot for
`sign_off_status` (the whole register? a per-step rollup? the latest entry's
`Status`?) must be pinned by the architect — the SPEC says "value read from the
sign-off register" without naming the field. Design assumes the latest
register entry's `Status` for the PR's step, as a single comparable scalar.

**Stale escalation (R2.11).** "No sign-off movement for >48h" =
`sign_off_status` unchanged across two ticks whose timestamps differ by ≥48h.
Implementation: `overseer_state.py` records, per PR, the `(sign_off_status,
last_checked)` at the time the status last *changed* (call it
`status_changed_at`). On each tick, if `now − status_changed_at ≥ 48h` →
escalate: apply `needs-human` label + post a §8.2-style comment explaining the
stale state (problem + how long + what the human must decide). Escalate **once**
per stale episode (track an `escalated: true` flag in the PR entry to avoid
re-escalating every tick).

**PR removal on close/merge (R2.12).** When a tick observes a PR no longer in
the open-PR discovery set (closed or merged), remove its key from `prs` in the
same tick. `overseer_state.py.reconcile(open_prs)` deletes entries whose key is
not in `open_prs`.

### S5 — Duplicate loop-job guard (R2.13–R2.15)

**Loop-prompt identifying prefix.** The dedup key is the cron job's prompt
prefix: **`HOS oversight loop`** (exact string, R2.13). Every loop job the
overseer creates must begin its prompt with this prefix.

**Pre-creation dedup (R2.13).**
1. Call `CronList`.
2. Filter jobs whose prompt starts with `HOS oversight loop`.
3. If exactly one match → reuse it; do not create. Write its ID to
   `oversight-schedule.json:loop_job_tag`. Notify per R2.14.
4. If zero matches → create the job, then write its ID.

**Skip notification (R2.14).**
```
Oversight loop already running (job ID: {id}). Reusing existing job — no new
job created.
```

**Stale-job cleanup (R2.15).** If `CronList` returns **multiple** matching jobs:
1. Sort by creation time; keep the most recent.
2. `CronDelete` all the others; collect deleted IDs.
3. Write the surviving job's ID to `oversight-schedule.json`.
4. Notify the human: duplicates found and cleaned up, listing deleted IDs.

> **Cross-tie to S5 in the task brief (20-minute duplicate-job guard):** the task
> brief frames S5 as a per-PR "another instance is working it" lock
> (`status == "reviewing"` within 20 min). The SPEC frames S5 as a *cron-job*
> dedup. These are two different dedup concerns. **OQ-8:** Design treats the SPEC
> as authoritative for S5 (cron-job dedup) and folds the task brief's per-PR
> in-progress guard into S4's state as an optional `status` field
> (`reviewing|waiting|bounced|merged`) with a `last_checked` recency check
> (skip a PR whose `status=="reviewing"` and `last_checked` within 20 min). Both
> are specified; architect to confirm whether the per-PR 20-min guard is in
> scope for v0.4.0 or deferred.

### `overseer_state.py` public surface (deterministic, unit-testable)

```
read_state(path) -> dict                       # {} if absent
write_state(path, state) -> None               # atomic write (tmp+rename)
upsert_pr(state, pr_number, *, sign_off_status, second_review_status,
          now_iso) -> dict                     # sets first_seen on first sight,
                                               # updates last_checked, tracks
                                               # status_changed_at
reconcile(state, open_pr_numbers) -> dict      # drop entries not in open set
stale_prs(state, now_iso, threshold_hours=48) -> list[int]
read_schedule(path) -> dict                    # {} if absent
write_schedule(path, *, stop_at, created_at, loop_job_tag) -> None
clear_schedule(path) -> None
is_new_pr(prior_state, pr_number) -> bool
```

The agent (`overseer.md`) owns all GitHub and cron tool calls; the helper owns
only JSON state mutation and the pure predicates. This keeps the safety-relevant
predicates (stale detection, new-PR detection) under unit test rather than in
prompt prose.

### Acceptance-criteria trace (§2)

AC-2.1 → discovery union over protected branches. AC-2.2 → allow-list filter.
AC-2.3 → empty-tick write. AC-2.4 → new-PR notify at next tick. AC-2.5 →
`[URGENT]` before cycle. AC-2.6/2.7/2.8 → schedule file recovery + stop skill.
AC-2.9 → five-field state entries. AC-2.10 → 48h stale escalation. AC-2.11 →
removal on close. AC-2.12/2.13/2.14 → cron dedup + cleanup.

---

## §3 — Empty-PR guard: overseer side (#325)

### Component map

| Component | File | Change |
|---|---|---|
| Overseer agent | `.claude/agents/overseer.md` CORE autonomous flow | New step **before** current step 4a (register-completeness): empty-PR pre-check |
| Ledger | `audit/oversight-log.jsonl` | New `empty-pr-guard` event |

### Placement (R3.1)

The empty check runs **before any part of the review cycle** — before
`overseer.md` CORE step 3 reads PR state in earnest, and specifically before
step 4a (register-completeness / bounce-back gate). The exact insertion point:
a new **step 2c** in the autonomous flow (after step 2b's notification in §2 S2,
before step 3). The guard short-circuits steps 3–8 entirely for an empty PR.

### Empty-check (R3.1)

```bash
CHANGED=$(gh pr diff "${PR}" --name-only 2>/dev/null | sed '/^$/d' | wc -l | tr -d ' ')
if [ "${CHANGED}" -eq 0 ]; then
  # empty-PR condition — follow R3.2–R3.7 exclusively, then STOP this PR
fi
```

The SPEC mandates `gh pr diff <PR> --name-only` as the authoritative check (R3.1).
The task brief's alternative (`gh api repos/{o}/{r}/pulls/{n}` → `commits` field)
is recorded as a fallback for environments where `gh pr diff` is unavailable, but
the **primary** check is `gh pr diff --name-only` (matches AC-3.7's "one commit
ahead" framing via changed-file count). Boundary: `gh pr diff` returns empty for
zero commits ahead of base; a non-empty diff means proceed to normal review.

### Structured comment (R3.2) — post verbatim

```
[OVERSEER] Empty-PR guard triggered.

This PR has zero commits ahead of base. There is nothing to review.

Possible causes:
- The branch was rebased and all commits were already upstream.
- The branch was reset to match the base.

Action required: close this PR and investigate the branch state.

The oversight review cycle has NOT been run. No sign-off was recorded.
```

Post via `gh pr comment "${PR}" --body "..."` (issue comment, not a review).
Only `<base>` may be substituted into the body if a base-naming variant is used
(AC-3.1); otherwise post verbatim.

> Note: the task brief's alternate comment text ("It was likely emptied by a
> rebase. Closing without review.") **conflicts** with SPEC R3.6 (the overseer
> must NOT close anything). The SPEC text above is authoritative — it does not
> claim to close the PR. **OQ-9** records this conflict for the architect; the
> design follows the SPEC (no close).

### Label (R3.3)

Apply `needs-human`; do **not** apply `needs-ai`. Read the actual repo label
spelling first (`GET /repos/{o}/{r}/labels`) per `overseer.md` CORE label
protocol (the repo may use `needs_human`). Do not assume the hyphenated default.

### No sign-off entry / no reviewers / branch intact (R3.4–R3.6)

- R3.4: write **no** sign-off register entry for an empty PR.
- R3.5: dispatch **no** reviewer agents (no oversight-evaluator, no
  risk-assessor, no panel). The short-circuit in R3.1 guarantees this by
  exiting before step 3.
- R3.6: do **not** close, delete, or request deletion of the branch. The
  overseer's actions are limited to the comment + label + ledger event.

### Ledger event (R3.7)

Append to `audit/oversight-log.jsonl`:

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

`base`/`head` resolved via `gh pr view {PR} --json baseRefName,headRefName`.

### Acceptance-criteria trace (§3)

AC-3.1 → verbatim comment. AC-3.2 → `needs-human`, not `needs-ai`. AC-3.3 → no
register entry (short-circuit before step 4a). AC-3.4 → no reviewer dispatch.
AC-3.5 → branch untouched. AC-3.6 → ledger event. AC-3.7 → non-empty PR
proceeds (the `-eq 0` guard is false).

---

## Startup-gap analysis

Per the technical-design startup-gap protocol, for each reactive contract change:
*should this have been settled in the initial design?*

- §1 (threads not prose): **yes** — CONDITIONAL_PROCEED enforcement was specified
  as PR-body prose in the *original* `oversight-orchestrator.md`. This is a
  `startup-artifact-gap`: the original merge-gate contract was incomplete (prose
  is invisible to branch protection). **Affected sign-offs:** any prior approval
  of a CONDITIONAL_PROCEED PR that was merged on the prose contract is an
  **orphaned approval** — it was approved against a gate that did not actually
  block. Flag for re-review: confirm no CONDITIONAL_PROCEED PR was merged without
  human action under the old prose mechanism. Code already approved that only
  *renders* the prose section stands (the section is retained); code that
  *relied on prose being the gate* must be re-checked.
- §2/§3: net-new behavior (loop operational gaps surfaced by live monitoring;
  empty-PR guard is defense-in-depth). Not orphaning prior approvals — these are
  additive. A missing edge case never previously exercised → prior sign-offs
  stand.

---

## Open questions for the architect

| # | Question | Blocks | Design's provisional choice |
|---|---|---|---|
| OQ-1 | Overseer substrate: agent-prompt (`.claudetmp/`, per SPEC) vs. Python `probe.py` (`.ai-local/hos-automation/`, per task brief)? | All of §2 | SPEC: agent-prompt + helper, `.claudetmp/` |
| OQ-2 | Single `oversight-state.json` (per-PR entries) vs. one file per PR (`pr-state-{n}.json`, per task brief)? | §2 S4 | Single file |
| OQ-3 | Factor deterministic logic into `scripts/automation/lib/overseer_state.py`, or keep in prompt? | §2 testability | Helper module |
| OQ-4 | Which branch-protection settings make a `REQUEST_CHANGES` review block merge (require review approval + require conversation resolution)? Names the exact setting `setup_branch_protection.sh` must register. | §1 AC-1.1 | Assumes both settings on; needs confirmation |
| OQ-5 | Does `scripts/framework/hos_orchestrator.sh` exist? `overseer.md` CORE references it but it was not found on disk. | §2 invocation | Treat as the runner to be wired; confirm |
| OQ-6 | New-PR notification channel (PR comment? tracking issue? cron-wrapper stdout?) | §2 S2 | PR comment + console |
| OQ-7 | Exact sign-off-register field to snapshot for `sign_off_status` | §2 S4 stale detection | Latest entry's `Status` for the PR's step |
| OQ-8 | Is the task brief's per-PR 20-min "another instance is working it" guard in scope, or deferred? (SPEC's S5 is cron-job dedup only.) | §2 S5 | Both specified; per-PR guard folded into S4 as optional `status` |
| OQ-9 | Empty-PR comment conflict: task brief says "Closing without review"; SPEC R3.6 forbids closing. | §3 | Follow SPEC (no close) |

**Routing:** OQ-1/OQ-2/OQ-3/OQ-5 are architecture decisions → `architect`.
OQ-4 is architecture (branch-protection contract) → `architect`. OQ-6/OQ-7/OQ-8/
OQ-9 are spec-ambiguity → if the architect deems any a *product* question
(what the overseer should *do*), route to `pm-agent` per the SPEC's own
escalation targets.

**Status:** Requesting architect review. Do not hand to coder until §0 substrate
(OQ-1) and OQ-4 are resolved — §2 cannot be coded against an undecided substrate,
and §1's merge-blocking guarantee is unverifiable without the branch-protection
setting.
