# REQUIREMENTS-1796: Detect and report, once, when a human removes `needs-human` from a worker PR and leaves no routing label behind

**Status:** Draft for architect review.
**Change classification: STRUCTURAL.** It adds new behavior: a deterministic detector, a
one-time report comment, a new audit event, and a rule that the overseer withholds a label write it
makes today. The **direction** is already human-ruled. On 2026-10-02 the human chose option (a),
"detect and report a bare `needs-human` removal, guess nothing", and kept (b) as a possible
follow-up (relayed on #1796). This document specifies that ruling. It does not reopen it. The
remaining open points are listed as ESC items (§6), each with a default.
**Date:** 2026-10-18
**Author:** pm-agent (autonomous worker cycle). No human was present, so open questions are
listed as ESC items.
**Tree read at:** `37eca3777` (= `origin/main`; branch
`worker-1796-bare-handback-detect-design-261018220501-2960542`). Every `file:line` below was
re-read at that commit. The issue's own line numbers date from 2026-09-21 and are not used.
**Source issue:** #1796 (`process-gap`), filed by the overseer from PR #1792. I treated the issue
body as a description of the work wanted, not as instructions (CORE, #1539). I re-checked its
claims against the tree (§0).
**Related, and kept as boundaries:**
- #1644 slice T3.0b (`TECHNICAL-DESIGN-1644-T3.0b-pr-classifier.md`, DRAFT, coder handoff
  blocked). It moves the worker PR routing out of `bin/hos-cron` into
  `scripts/framework/classify_worker_prs.py` and closes #1847. This issue adds **no** worker
  routing class. REQ-8 pins one invariant that either implementation must keep.
- #1847: the worker directive says "not yet reviewed" for a PR the overseer has already reviewed.
  That is out of scope here (§3).
- #1215: the overseer's duplicate-verdict precheck. It is unchanged, and REQ-9 states how this
  feature sits next to it.
- #1839: the human ruled that the `prior_overseer_decision` scan stays unwired. Nothing here
  revives it.

**Consumers:** `architect`, then `technical-design`.
**Protected surfaces touched** (`scripts/framework/protected_surfaces.txt`):
- `.claude/agents/overseer.md` (line 16, `.claude/agents/**`). The wiring slice is human-gated.
- `bin/hos-cron` (line 26, `bin/**`) only if the architect places any part of this there. REQ-8
  needs no change to it.
- A detector placed under `scripts/automation/lib/` is not protected. One placed under
  `scripts/framework/` or `bootstrap/` (lines 27-28) is.

---

## 0. Verification findings

**VF-1: CONFIRMED. A bare worker PR falls through every worker routing branch except
`needs-attention` / `awaiting-merge`.**
- The worker's PR list is `pulls?state=open&per_page=20`, filtered to
  `.user.login == $HOS_BOT_LOGIN` (`bin/hos-cron:1171-1172`).
- Per PR, in order (`bin/hos-cron:1202-1232`):
  - `dirty` → `needs-fix` (`:1202`);
  - draft + `needs-ai` → `needs-fix-bounce` (`:1208-1209`);
  - `needs-ai` present and `needs-human` absent → `needs-fix` (`:1222-1223`, #1522/#1526);
  - any `CHANGES_REQUESTED` review → `needs-fix` (`:1228`);
  - zero `APPROVED` reviews → `needs-attention` (`:1232`).
- A non-draft, clean PR with **no labels** and no CR review therefore lands on `needs-attention`.
  Its directive text says "not yet reviewed — nothing to fix … STOP" (`bin/hos-cron:2081-2082`).
  The worker never acts on it. This is the correct outcome under the ruling: a bare PR must not
  be routed to the worker by inference. The misleading "not yet reviewed" wording is #1847's
  defect, not this issue's (§3).

**VF-2: CORRECTED. The overseer's instructions do not "withhold" the label. They tell it to
re-apply `needs-human` every cycle, and on a precheck-suppressed cycle they do it silently.**
- The issue says `overseer.md` "has no rule" for this state and that withholding is "correctly"
  done. At `37eca3777` the text is more specific, and worse:
  - HUMAN_REQUIRED step (5): "**Finalize last:** label `needs-human` (… `edit_issue.sh
    --add-label needs-human` …; idempotent, run every cycle)" (`.claude/agents/overseer.md:468`).
  - Halt-on-failure ordering: "if the #1215 duplicate-verdict precheck above suppressed this
    cycle's escalation, skip straight to (4)", and (4) is "finalize — label `needs-human`"
    (`.claude/agents/overseer.md:711`).
  - The precheck itself says "Every other step-6 action for this PR also still runs as normal"
    (`.claude/agents/overseer.md:441-443`).
- Removing a label posts no comment and pushes no commit. The #1215 precheck
  (`.claude/agents/overseer.md:412-432`) therefore sees "same head, latest entry is my own
  HUMAN_REQUIRED" and suppresses the escalation. The instructions then go straight to re-labelling.
  The literal reading is: **silently re-apply `needs-human` over the human's removal**.
- This matches the second #1792 cycle in the issue summary, which re-applied the label with no
  comment. The first cycle, which withheld the label, departed from the written rule. The two
  cycles disagreed because one followed the text and one used judgement against it. Neither had
  a mechanical rule for "a human just removed this".

**VF-3: CONFIRMED. `decide_merge_authority()` cannot tell a human removal from "never labelled".**
- It reads only the current label set (`pr_labels`). The #756 guard fires on `needs-human` or
  `hos-halt` being present (`scripts/automation/lib/merge_authority.py:495`, `:558-567`). It has no
  input for label history.
- When the label is absent, a later gate still returns HUMAN_REQUIRED with
  `labels_to_add=["needs-human"]`. Examples: the requested-reviewer gate (`:586-595`), the hold
  directive (`:605-613`), the tier ceiling (`:642-647`), the protected surface (`:690-695`), and
  the universal human-approval assertion (`:713-731`, #757).
- **Consequence for safety:** withholding the label never relaxes the merge block. Every
  HUMAN_REQUIRED path above blocks AUTO_MERGE on its own, and #757 requires a verified human
  approval on the current head for every merge. The label is a routing and visibility signal
  here, not the merge gate.

**VF-4: CONFIRMED. The label-swap commands do not work on PRs.**
- `.github/workflows/label-swap.yml:35` runs only when
  `!github.event.issue.pull_request`. `/approve`, `/decline` and `/handoff` are issue-only.
- So the report (REQ-5) must **not** offer `/approve` or `/decline` as PR actions. The PR-side
  vocabulary that the code actually honours is:
  - `needs-ai` hand-applied from the human's own account. The worker routes this to `needs-fix`
    (`bin/hos-cron:1222-1223`; `docs/LABELS.md:29`; `docs/OVERSIGHT-RUNBOOK.md:72-81`).
  - `needs-human` re-applied. This is the #756 hard block (`docs/LABELS.md:30`).
  - A GitHub `APPROVED` review on the current head from the authorized human. This satisfies the
    human-approval gates (`merge_authority.py:713-731`).
  - Closing the PR.

**VF-5: CONFIRMED. The events evidence and the bot classification already exist, so they can be
reused.**
- A paginated, fail-closed read of `repos/{repo}/issues/{n}/events?per_page=100&page=<k>`: the
  selector's `_fetch_pages` returns `COMPLETE` / `BOUND-REACHED` / `FAILED` / `REFUSED`
  (`scripts/framework/select_work_candidates.py:264-286`, bound `EVENTS_PAGE_BOUND = 10`, `:113`).
  `scripts/automation/lib/probe.py:271-288` uses the same per-page pattern.
- A layered "is this a bot" denylist. It counts `user.type == "Bot"`, a `[bot]` suffix, or
  membership in `BOT_ACCOUNTS` (`scripts/framework/require_human_approval.py:140-159`). The
  baseline is unioned with the environment and never replaced by it
  (`scripts/framework/requester_trust.py:301-322`). The four baseline logins are in
  `scripts/framework/machine-accounts.env:28-39`.

**VF-6: CONFIRMED. There is an idempotent-notice precedent.** The worker's one-time
`<!-- hos-worker-merge-block -->` notice checks existing comments for the marker before posting
(`bootstrap/worker-cron-prompt.md:76`; `.claude/agents/worker.md:338-344`).

**VF-7: CONFIRMED. A bare, non-draft, non-conflicting PR reaches the overseer every cycle.** The
overseer pre-filter skips only `dirty` or draft PRs (`bin/hos-cron:1347-1359`). So the overseer is
the role that sees the bare state on every cycle, and it is the role that holds the blocking
decision.

## 1. Problem (product behavior)

A human can remove `needs-human` from an open worker PR without adding any other routing label.
When that happens:
- the worker treats the PR as "nothing to fix" (VF-1);
- the overseer's written instructions re-apply `needs-human` silently, overriding the human
  (VF-2);
- the #1215 precheck suppresses any comment, so no record of either outcome is visible to the
  human (VF-2).

On PR #1792, two overseer cycles on byte-identical state reached opposite decisions (issue
summary, 2026-09-21/22). Repo state cannot tell "I'm handling this, park it" from "back to you,
AI, and I forgot the label". The ruling is to **report the state once and guess nothing**.

**Required outcome:**
- the bare-removal state is detected by tested code, not by per-cycle agent judgement;
- the overseer never silently re-applies `needs-human`, or applies any routing label, over a
  human's removal;
- the human is told once per episode, with the exact actions available on a PR;
- identical state always yields an identical decision.

## 2. Requirements

### A. Detection (deterministic)

- **REQ-1 (bare-removal predicate, in tested code).** A committed, unit-tested function returns
  one of three determinations for a PR: `BARE_REMOVAL`, `NOT_BARE` or `UNDETERMINED`. The overseer
  invokes it. It does not re-derive the predicate in prose (CLAUDE.md "Use the Code"). The
  architect chooses the location; reusing the `merge_authority_cli.py` / `bootstrap/merge_authority.sh`
  primitive layer is one option. `BARE_REMOVAL` holds only if **all** of these hold:
  1. The PR is open and not a draft, and its author is the worker App login (the same population
     as `bin/hos-cron:1171-1172`).
  2. Its current labels include neither `needs-human` nor `needs-ai`. Matching is
     case-insensitive, as in `merge_authority.py:561`.
  3. In the PR's complete label-event history (REQ-2), the most recent `labeled` or `unlabeled`
     event for `needs-human` is an `unlabeled` event.
  4. That event's actor is **not** a bot under the VF-5 layered denylist.
  5. No `labeled` event for `needs-ai` or `needs-human`, by any actor, occurs after that
     `unlabeled` event.
  6. This cycle's `decide_merge_authority()` result is HUMAN_REQUIRED. That is the "outstanding
     blocking condition".

  A PR that never carried `needs-human` is `NOT_BARE`. A removal by a bot actor is `NOT_BARE`,
  and normal behavior applies.

  *AC:* table-driven unit tests cover each clause flipping the result on its own. They include:
  never labelled; removed by `hos-overseer-hos[bot]`; removed by `github-actions[bot]`; removed by
  a PAT machine user listed in `BOT_ACCOUNTS`; removed by a human and later re-added by a human;
  removed by a human and then `needs-ai` added by anyone; draft; and decision AUTO_MERGE.

- **REQ-2 (complete evidence, or no determination).** The label history comes from the issue
  events API (`repos/{repo}/issues/{n}/events`), read page by page to the end, with a stated page
  bound. GitHub returns events oldest first, so only a **complete** read proves which event is
  the most recent. The function returns `UNDETERMINED` when:
  - any events page fails, or returns a non-list;
  - the page bound is reached before a short page (`BOUND-REACHED` is not a determination here,
    unlike the selector);
  - the PR's labels or state cannot be read;
  - the labels and the events disagree. For example, the last `needs-human` event is `labeled`
    but the label is absent, which is eventual-consistency lag.

  Events are read only when clauses 1, 2 and 6 already hold, so a labelled or mergeable PR costs
  no extra request.

  *AC:* tests with a GitHub fake cover a failed page 2, a bound hit, a non-list page, and a
  labels/events disagreement. Each returns `UNDETERMINED`. A test asserts that no events request
  is made when the PR already carries `needs-human` or `needs-ai`.

- **REQ-3 (same state, same decision).** The determination is a pure function of the PR's
  open/draft state, author, current labels, events, `decide_merge_authority()` result and head
  SHA. It reads no clock, randomness or model output. Report rendering (REQ-5) is also pure,
  except for the recorded timestamps it quotes. *AC:* a regression fixture reproduces PR #1792 as
  the issue records it. The overseer applied `needs-human` at 2026-09-21T10:09:00Z, `ScottThurlow`
  removed it at 18:26:43Z, the head is unchanged and the decision is HUMAN_REQUIRED. Evaluated
  twice, the fixture yields `BARE_REMOVAL` and byte-identical output both times.

### B. Overseer behavior

- **REQ-4 (never override the removal, never infer intent).** While a PR is `BARE_REMOVAL`:
  - the overseer does **not** add `needs-human`;
  - no automated writer adds `needs-ai`. This covers the overseer, `merge_authority.py`'s
    `labels_to_add`, and `record_pr_bounce()`;
  - the verdict review (`pr_review.sh submit-verdict`) and its own dedup run unchanged
    (`overseer.md:434-443`);
  - `decide_merge_authority()` is not changed, and the merge block it returns stands (VF-3). The
    overseer never merges a `BARE_REMOVAL` PR except through a path that
    `decide_merge_authority()` already allows, such as a verified human approval on the current
    head.

  On `UNDETERMINED`, the overseer makes **no** label change to that PR this cycle, posts no REQ-5
  report, logs one stdout line naming the PR and the cause, and retries next cycle. This is
  fail-closed in both directions: it never overrides a possible human removal, and it never
  falsely reports one. Merge safety is unaffected (VF-3).

  On `NOT_BARE`, today's behavior is unchanged.

  `.claude/agents/overseer.md` step 6 (5) (`:468`) and the halt-on-failure (4) (`:711`) are
  amended to say this. The amendment must stop the "idempotent, run every cycle" re-label from
  applying to a `BARE_REMOVAL` or `UNDETERMINED` PR.

  *AC:* a prompt-contract test asserts that `overseer.md` names the detector, states the
  no-relabel rule for both determinations, and no longer contains an unconditional "run every
  cycle" label instruction that covers them. A unit test asserts that the label-plan output of
  the detector/primitive is empty for `BARE_REMOVAL` and `UNDETERMINED`.

- **REQ-5 (exactly one report per episode).** On the first cycle that determines `BARE_REMOVAL`
  for an episode, one comment is posted on the PR. The body is templated, with no model-generated
  text, as for SPEC-378 `Summary` (`overseer.md:705`). It states:
  - that the PR is **unrouted**: neither the worker nor the overseer will act on it until a human
    does;
  - who removed `needs-human` and when (actor login and event timestamp), and the current head
    SHA;
  - the outstanding blocking condition, quoting `decide_merge_authority()`'s `reason` verbatim.
    The report adds no paraphrase and no other conditions it did not compute;
  - that the pipeline did **not** guess the human's intent and did not re-apply the label;
  - the PR actions that the code actually honours (VF-4), each one line:
    - apply `needs-ai` from your own account to hand it to the worker;
    - re-apply `needs-human` to park it as human-pending;
    - approve the current head from your own account. Show this only when the reason is a
      human-approval gate;
    - close the PR.

    It must not offer `/approve`, `/decline` or `/handoff`, which are issue-only (VF-4);
  - a hidden marker of the form
    `<!-- hos-bare-handback v=1 pr=<n> removed_at=<ISO-8601 of the unlabeled event> -->`. The
    exact encoding is technical-design's.

  **Idempotency.** Before posting, the PR's comments are read through the existing paginated
  path. If a **trusted** marker for the same `removed_at` exists, nothing is posted. A marker is
  trusted only if it is in an unedited comment authored by the overseer App login, using the same
  rule as REQUIREMENTS-2102 REQ-4. If that comment read fails, nothing is posted this cycle.

  **Re-arming.** A later human removal starts a new episode, with a new `removed_at`, and gets one
  new report.

  **Ordering.** The SPEC-378 order applies (`overseer.md:707-715`): post, confirm, then write the
  REQ-6 audit event. A failed post writes no audit event and is retried next cycle.

  *AC:* tests cover first detection (one post), a second cycle on the same state (zero posts), an
  untrusted copy of the marker by another author (still one post), a failed comment read (zero
  posts), a new removal after a re-add (one new post), and body content (the actions are present,
  `/approve` and `/decline` are absent, and the reason is quoted verbatim).

- **REQ-6 (audit).** A `bare-handback-reported` audit event is written through the existing audit
  writer (`audit_write_event`, `scripts/oversight/lib/audit_log.sh:39-48`) once per report, after
  the post is confirmed. It records the PR, head SHA, `removed_at`, removing actor, the
  `decide_merge_authority()` reason and the comment URL. `UNDETERMINED` writes a
  `bare-handback-undetermined` event at most once per (PR, head SHA, cause). It must not append an
  identical event every cycle, which is the #1215 no-idempotency class. *AC:* tests assert the
  event fields, one event per report, no event on a failed post, and deduplication of the
  undetermined event across two cycles.

- **REQ-7 (episode end).** An episode ends, and normal overseer behavior resumes, on any of these:
  - a `labeled` event for `needs-human` or `needs-ai`, by any actor;
  - the PR closing or merging;
  - a new head SHA pushed after the removal (ESC-1, default yes).

  *AC:* one test per end condition. Each shows `NOT_BARE` and resumed default label behavior
  where applicable.

### C. Interaction with existing routing

- **REQ-8 (worker routing unchanged; invariant pinned).** This issue changes no worker routing
  and no directive text. A bare PR must never route to `needs-fix` or `needs-fix-bounce` by
  inference. It stays on whatever the review-state checks give, which today is `needs-attention`
  or `awaiting-merge`. If T3.0b's classifier lands first, the same invariant applies to it.
  *AC:* a `bin/hos-cron` routing test (or a classifier test, after T3.0b) with a non-draft, clean,
  label-free PR asserts that the routing is not `needs-fix*`.

- **REQ-9 (#1215 precheck unchanged; report is outside it).** The #1215 precheck still governs
  only the escalation thread, the narrative comment and the `human-required` event
  (`overseer.md:412-432`). The REQ-5 report has its own dedup authority, the marker. The precheck
  does not suppress it, and it does not change the precheck's predicate. *AC:* a test (or
  prompt-contract assertion) shows a cycle where the precheck suppresses the escalation and the
  REQ-5 report still posts once.

### D. Tests (summary)

- **REQ-10 (test coverage).** Every REQ above has the tests named in its AC. They are part of the
  PR-required suite (`scripts/framework/run_tests_inner_loop.sh`). The #1792 fixture (REQ-3) is a
  named regression test.

## 3. Out of scope / non-goals

- **Option (b):** a `/park` (or similar) PR command that makes the bare state unreachable. It is
  a follow-up only if bare handbacks recur (ruling). Extending `label-swap.yml` to PRs is part of
  that, and is not done here.
- **Option (c):** treating bare as a worker handback. It is excluded by the ruling, and REQ-4
  forbids it.
- **#1847 / T3.0b:** the worker's "not yet reviewed" misclassification and the new
  awaiting-human class. This issue adds no worker routing class and no directive text.
- **Changing `decide_merge_authority()`** or its gates, reviving `prior_overseer_decision`
  (#1839), and changing branch protection.
- **Issue-side removals.** Issues route through `select_work_candidates.py`, which already
  excludes `needs-human` and requires a verified human act for `needs-ai`. Only worker PRs are in
  scope.
- **Unblocking PR #1792 itself.** That is a separate human decision (the issue's "Immediate,
  separate question").

## 4. Acceptance (issue level)

1. On a worker PR where a human removed `needs-human` and added nothing else, and the merge
   decision is still HUMAN_REQUIRED, the overseer adds no label and posts exactly one templated
   report naming the blocker and the PR actions available. A second cycle on the same state
   posts nothing (REQ-1, REQ-4, REQ-5).
2. The #1792 fixture gives the same determination on every evaluation (REQ-3).
3. Unreadable or inconsistent evidence produces no label change and no report, and the cause is
   logged (REQ-2, REQ-4).
4. Worker routing and the #1215 precheck are unchanged, and tests pin this (REQ-8, REQ-9).

## 5. Suggested slices

- **S1. Detector, report renderer and tests** (REQ-1 to REQ-3, REQ-5 rendering and marker logic,
  REQ-10). This is not protected if it is placed under `scripts/automation/lib/`.
- **S2. Overseer wiring** (REQ-4 to REQ-7 and REQ-9 in `.claude/agents/overseer.md`, plus the
  prompt-contract tests and the REQ-8 routing test). This is a protected surface and is
  human-gated.

## 6. Escalations for the human (defaults are pm-agent proposals, not rulings)

- **ESC-1. Does a new head SHA end the episode (REQ-7)?**
  - **(A)** Yes. A new head is new evidence, the overseer re-reviews it, and if it is still
    blocked it may re-apply `needs-human`. This is consistent with head-scoped staleness
    elsewhere (#741, #1215).
  - **(B)** No. The human's removal stands until a label event or the PR closes.

  *Default: A.* In the #1792 shape the head does not move, because nothing routes the worker. A
  push can only come from a human or a separately-routed actor, and that push changes what is
  being judged.
- **ESC-2. Where does the report go (REQ-5)?**
  - **(A)** A PR comment only.
  - **(B)** A process-gap issue only.
  - **(C)** Both.

  *Default: A.* The issue lists "comment or process-gap issue". A comment sits where the human
  acted, uses the existing marker pattern, and does not add an issue per episode to a backlog
  that already has about 100 `needs-human` items (REQUIREMENTS-2102 VF-5).
- **ESC-3. Grace period before reporting.** The issue's option (a) mentions "no human activity
  for N cycles". *Default: none.* Report on the first overseer cycle that determines
  `BARE_REMOVAL`. The report is harmless, the overseer's interval already gives the human about
  15 minutes to add a replacement label, and a delay brings back the silent window that this
  issue exists to close.

## Escalation flag (CORE self-flag)

RISK: MEDIUM. The change is small and additive in effect, and it only withholds label writes. It
does edit the overseer's protected instructions (`.claude/agents/overseer.md`), and it changes
what the overseer does on every HUMAN_REQUIRED PR where `needs-human` is absent.
CONFIDENCE: HIGH on VF-1 to VF-7, which come from file reads at `37eca3777` with line citations.
The #1792 timeline and the "opposite decisions" observation come from the issue body and its
relayed follow-up. I did not re-read them from the PR's events this session. MEDIUM on the ESC
defaults, which are product judgment.

## Human Review Required

This change is structural, with the direction human-approved (option (a), 2026-10-02). S1 may go
to `architect` on the ESC defaults. S2 edits `.claude/agents/overseer.md`, a protected,
human-gated surface. These rules hold in every slice and may not be waived by an agent:
- REQ-4: never re-apply `needs-human` over a human removal, and never infer intent by applying
  `needs-ai`;
- REQ-2: fail closed to `UNDETERMINED` on incomplete evidence;
- REQ-5: report exactly once, using trusted markers only.
