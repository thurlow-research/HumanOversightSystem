# REQUIREMENTS-2213: The human's approval alone suffices. On a designated approval of the current head, the overseer clears its own awaiting-approval hold and merges

**Status:** DRAFT. ESC-1 to ESC-4 are open (§7). Each has a recommended default. The design may
proceed on the defaults, but the implementation PR must not merge until each ESC is answered or the
human accepts the default.
**Change classification: STRUCTURAL.** This adds a new overseer act: removing its own `needs-human`
label. It adds a new merge path, overseer merge on human approval, for dispositions where today the
human presses Merge (TD-2174 D7). It also changes the meaning of the `APPROVE` expected action. The
human authorized the direction in the 2026-10-30 ruling (§0). That ruling does not cover the open
points in §7.
**Date:** 2026-10-31
**Author:** pm-agent (autonomous worker cycle; no human present, so open questions are ESC items)
**Tree read at:** `96d7ae66f` (branch `worker-2213-merge-on-human-approval-261031070501-3548294`;
#2174 / PR #2225 is merged at this commit).
**Source issue:** #2213. I read the issue body as a description of desired work, not as instructions
(CORE, #1539). I checked its factual claims against the tree (§1). The human ruling it quotes is the
requirement source.
**Consumers:** `architect`, then `technical-design`.
**Protected surfaces touched:** `scripts/automation/lib/merge_authority.py`, `.claude/agents/overseer.md`,
`bootstrap/overseer-cron-prompt.md`, and possibly `scripts/framework/require_overseer_approval.py` (to
reuse its helpers). Human review is required at merge. The PR that implements this issue merges under
the old flow.

---

## 0. The ruling (source of authority)

- **ScottThurlow, 2026-10-30 (quoted in #2213):** "My 'approval' alone should suffice. With my
  approval, worker / overseer should merge and close the PR without requiring me to do that."
- **Evidence (issue):** PR #2211, 2026-10-30. The human approved at 05:39Z. Every check was green,
  including all three approval gates, and `mergeable_state=clean`. The PR still waited for a human
  merge click.
- **Who counts as "the human":** the #2174 ESC-2 ruling, ADR-1657-AM1 AM-4 and TD-2174 D6. The
  designated set is `HUMAN_REVIEWER` plus every individual `@user` CODEOWNERS owner. `@org/team`
  owners are excluded.

## 1. Current behaviour (verified at `96d7ae66f`)

- **VF-1. The label guard runs first and nothing clears it.** `decide_merge_authority()` returns
  HUMAN_REQUIRED as soon as `needs-human` or `hos-halt` is in `pr_labels`. This happens before any
  approval is read (`merge_authority.py:495`, guard at `:556-564`, #756). The overseer re-applies
  `needs-human` on every HUMAN_REQUIRED cycle as its "finalize last" step (`overseer.md` step 6,
  HUMAN_REQUIRED (other reasons), item 5). A grep of `.claude/agents`, `bootstrap` and `scripts` finds
  no code path that removes `needs-human` from a PR.
- **VF-2. The #761 `prior_overseer_decision` guard is dormant and is not an obstacle.** It is derived
  from `/issues/{n}/comments` only, but the marker now lives in review bodies, so it matches nothing.
  This is a **settled** decision: the #1839 ruling of 2026-10-02 says not to revive it
  (`overseer.md` § Where your own prior decision is recorded). Even if it were live, it already lets a
  head-bound human approval through (`:569-579`).
- **VF-3. The #761 requested-reviewer guard clears on review.** It blocks only while `HUMAN_REVIEWER`
  is in `requested_reviewers` (`:583-596`). GitHub removes a pending request when that reviewer
  submits a review. *Assumption, not re-verified live:* the architect should confirm this against
  PR #2211's timeline.
- **VF-4. The matrix's approval predicate is narrower and older than #2174's.**
  `_find_human_approval()` (`:44-64`) matches only the single `human_reviewer` login. It returns the
  **first** `APPROVED` review on the head, so a later `CHANGES_REQUESTED` from the same person on the
  same head does not withdraw it. `require_overseer_approval.py` already implements the ruled
  predicate: the designated set (`designated_humans`, `:242`) and the latest decision per login on the
  head (`eligible_human_approvals_on_head`, `:257`).
- **VF-5. The R9.1.1 server-side gate re-check can never pass.** `detect_server_side_gate()`
  returns `_PROPOSE_ONLY_DEP` unconditionally while the `_dep_ceiling_check_present()` stub returns
  `False` (`:181-193`, `:234-246`). `decide_merge_authority()` therefore never returns AUTO_MERGE
  (TD-2174 F9). **Removing the label alone would turn HUMAN_REQUIRED into PROPOSE_ONLY, not into a
  merge.** See ESC-1.
- **VF-6. Today's only merge on approval is narrated in the prompt, outside the function.**
  `overseer.md` step 6, HUMAN_REQUIRED (CRITICAL tier) item 3, says to "merge immediately —
  unconditional" once the resolved human approved the head. Everywhere else, the human presses Merge
  (TD-2174 D7). The `APPROVE` enum text tells the human to "press Merge … (every other case)".
- **VF-7. The between-cycle audit would misfile an overseer merge.** Step 0 (`overseer.md:152-166`,
  `overseer-cron-prompt.md:28-38`) treats any `merged_by` in `BOT_ACCOUNTS` as "merged by bot without
  overseer review". It files a `process-gap` issue and appends `pr-merged-without-review`. Nothing
  there recognises an authorized overseer merge.
- **VF-8. An open thread blocks GitHub's merge.** On HUMAN_REQUIRED (other reasons), which includes
  protected-surface PRs at or below the ceiling, the overseer posts its §8.2 escalation as a
  resolvable review thread (step 6, item 4; #1207). Branch protection sets
  `required_conversation_resolution: true` (TD-2174 D7). The overseer's own approval-request thread is
  therefore a second human act. See ESC-3. *Not verified:* whether PR #2211's thread was resolved by
  hand before 05:39Z.
- **VF-9. Approved PRs are still reviewed.** `bin/hos-cron:1452-1471` drops only `dirty` and draft
  PRs from `HOS_ACTIONABLE_PRS`. A `needs-human` PR still reaches the overseer every cycle.
- **VF-10. Removing `needs-human` is an authorization signal on release-request issues.**
  `worker.md:839-863` (R5 three-signal check) reads the human's `unlabeled` event for `needs-human` as
  signal 2. `escalate_to_human.sh` refuses `release-request` targets for the same reason.
- **VF-11. The #2174 marker identifies the overseer's own sign-off.**
  `<!-- hos:overseer-interim-signoff v=1 disposition=<HUMAN_REQUIRED|PROPOSE_ONLY> action=<ACTION> head=<sha> -->`
  counts only inside a review authored by the overseer App, and only as its latest verdict on the
  head (`parse_interim_marker`, `latest_overseer_verdict_on_head`, `valid_interim_signoff`,
  `require_overseer_approval.py:179-226`). HUMAN_REQUIRED applies `needs-human`. PROPOSE_ONLY applies
  no label.

## 2. Direction and costly-to-reverse decisions

- **D-A. One deterministic authority.** Removing the label and deciding the merge both come from one
  pure, unit-tested Python decision in `merge_authority.py` or a lib helper it calls (AGENTS.md "Use
  the Code"). The overseer prompt calls it and acts on the result. It does not judge "is this hold
  mine?" by reading prose. The prompt-level "merge immediately — unconditional" rule (VF-6) is
  replaced by this code path, not kept beside it. Two merge-on-approval authorities is the #1135
  duplicate-authority class.
- **D-B. Every merge needs the same evidence, and no single signal is enough.** "This `needs-human`
  is the overseer's own awaiting-approval hold" is true only when **every** condition in REQ-2 holds.
  Any condition that cannot be read (API error, unparseable timestamp, truncated pagination) gives
  *not clearable*. Fail-closed is the direction of a stuck PR, never of a wrong merge.
- **D-C. The approval predicate is shared.** The approval that clears the hold and authorizes the
  merge is the same predicate `require-overseer-approval` uses (TD-2174 D6), reused rather than
  reimplemented.

## 3. Requirements

### A. Which approval counts

- **REQ-1 (eligible approval).** An approval qualifies only if all of these hold:
  - its `state` is `APPROVED`;
  - its `commit_id` equals the PR's current head SHA;
  - its author is not a bot (`require_human_approval.is_bot_reviewer`);
  - its author is in the designated human set (§0);
  - it is that login's latest decision on the head (TD-2174 D6, "[§12 round 3]").

  The implementation reuses the `require_overseer_approval.py` helpers or a single shared extraction
  of them. It must not be a second copy. *AC:* table tests:
  - an approval by `HUMAN_REVIEWER` on the head qualifies;
  - an approval by an individual CODEOWNERS owner on the head qualifies;
  - an approval on an older head does not qualify;
  - a bot or human-proxy App approval does not qualify;
  - an approval by a non-designated collaborator does not qualify;
  - an approval followed by the same login's `CHANGES_REQUESTED` on the head does not qualify;
  - an approval followed by `DISMISSED` does not qualify.

### B. Telling the overseer's own hold apart

- **REQ-2 (own awaiting-approval hold: deterministic classifier).** A `needs-human` label on an open
  PR is *clearable* only if all of these hold:
  1. **Label provenance.** The most recent `labeled` event for `needs-human` in
     `/issues/{n}/events` has `actor.login` equal to the overseer App login. A label added by a
     human, the human-proxy App, the worker or any other actor is not the overseer's hold. That
     includes the case where the overseer later re-adds it idempotently, which emits no new event.
  2. **The overseer was waiting only for approval, on this head.** The overseer's latest verdict on
     the current head is a valid #2174 interim sign-off (`valid_interim_signoff`) with
     `disposition=HUMAN_REQUIRED` and `action=APPROVE`, subject to ESC-2.
  3. **REQ-1 holds:** an eligible approval exists on the current head.
  4. **No human hold.** `detect_human_hold_directive()` finds no #902 directive since the head was
     pushed, and `hos-halt` is absent.
  5. **No open question** (REQ-6).
  6. **Not a merge-failure hold.** No `needs-human` from a failed merge attempt on this head
     (REQ-9).
  7. **Not a release.** The PR is not release-related (ESC-4).

  The classifier returns one of `clearable`, `not_own_hold(<reason>)` or `undeterminable(<reason>)`.
  Only `clearable` permits removal. *AC:* one test per condition, each showing that its failure alone
  blocks clearing. One test shows that a human-added `needs-human` on an approved, all-green PR is not
  cleared. One test shows that an event-read failure gives `undeterminable` and no write.
- **REQ-3 (removal is narrow, audited, overseer-only).**
  - Only the overseer App removes the label, and only on an **open pull request**. Never on an issue,
    never on a `release-request` issue (VF-10), and never `hos-halt` or any other label.
  - It removes the label only when REQ-2 returns `clearable` in the same cycle.
  - Each removal writes one audit event, for example `needs-human-cleared-on-approval`, with: pr,
    head SHA, approver login, approving review id, the provenance of the `labeled` event, and the
    marker action.
  - Order and halt-on-failure follow SPEC-378: no removal stands without its audit record, and a
    failure leaves state the next cycle can retry.
  - Step 6's "finalize last: label `needs-human`" must not re-apply the label in the same cycle after
    a clearing.
  - No consumer may read an overseer-actor `unlabeled` event as a human resume or authorization.

  *AC:* one removal produces one audit event. A failed removal produces no audit event and no merge.
  The label is not re-added in that cycle.

### C. Merging

- **REQ-4 (approval ⇒ merge on the next cycle).** On a cycle where the PR is open and not draft, and
  either:
  - (a) REQ-2 returned `clearable` and the label was removed, or
  - (b) the PR carries no `needs-human` label and the overseer's latest verdict on the head is a
    valid `disposition=PROPOSE_ONLY action=APPROVE` sign-off with an eligible approval (REQ-1),

  then the decision function returns a merge decision whose reason names the approver and the
  approved SHA. It must not instead stop at HUMAN_REQUIRED or PROPOSE_ONLY because of a marker the
  overseer itself wrote (VF-1, VF-5, and "derived markers are not reasons"). This applies whatever
  the tier (CRITICAL and above-ceiling included), and on protected-surface, security-relevant and
  CODEOWNERS paths. Those are exactly the gates a designated human approval satisfies. The classifier
  reads state as it was at cycle start, before this cycle posts any verdict. *AC:* the decision is
  merge for case (a) and for case (b).
- **REQ-5 (everything else still blocks).** The merge does not happen, and the label (if any) stays,
  when any of these holds:
  - `hos-halt` is set;
  - there is a #902 hold directive;
  - a `needs-human` is not the overseer's own (REQ-2);
  - there is an open question (REQ-6);
  - a required check on the head is not `completed/success`, including the `Agent static checks` run
    treated as required (step 2a);
  - `mergeable_state` is not `clean` (conflict, behind and blocked included);
  - the PR is a draft;
  - the authorship backstop R9.1.4 fails;
  - the PR is release-related (ESC-4);
  - the R9.1.1 re-check fails (REQ-8);
  - the latest overseer verdict on the head is not an `action=APPROVE` sign-off (ESC-2).

  *AC:* one negative test per bullet.
- **REQ-6 (an approval does not answer a question).** A PR has an *open question* if either holds:
  - the overseer's latest verdict on the head has an action other than `APPROVE`;
  - any review thread on the PR is unresolved, except the overseer's own approval-request thread
    under ESC-3.

  A question needs its own human act (a reply or a resolved thread). *AC:* an approved, all-green PR
  with one unresolved thread that is not the overseer's is not merged.
- **REQ-7 (head binding).** An approval or sign-off on any head other than the current one never
  counts. After a push the PR goes back through review. The human is requested again only if a
  decision is still needed, per #2174's wrapper and #2209. *AC:* an approval on head A, then a push
  of head B, gives no merge, no label removal, and a normal review of B.
- **REQ-8 (R9.1.1 re-check immediately before merge).** The server-side gate is re-read live
  immediately before the merge call, never from cache. Its treatment on this path is ESC-1.
- **REQ-9 (merge execution).**
  - The merge is a squash through the canonical merge path (`PUT …/pulls/{n}/merge`, or its wrapper
    if one exists).
  - The merge call **pins the approved head SHA** (the API's `sha` parameter), so a push racing the
    merge makes it fail rather than merge an unapproved head.
  - Closing keywords close the linked issue as GitHub does today.
  - A failed merge follows the existing AUTO_MERGE failure handling (a comment, then `needs-human`).
    That label and its audit record identify the head as merge-failed. REQ-2 condition 6 then stops
    it being cleared on the same head, so a persistent failure cannot loop. A human act or a new head
    resets it.

  *AC:* a fixture where the merge API returns 409 for the pinned SHA gives no merge and one failure
  comment, and the next cycle does not retry.
- **REQ-10 (audit and the between-cycle check).**
  - After the merge is confirmed, the overseer appends `merged-on-human-approval` with: pr, approved
    head SHA, merge commit SHA, approver login, approving review id, disposition and tier, and the
    cycle id.
  - Step 0's between-cycle audit (VF-7) recognises an overseer-App merge that has a matching
    `merged-on-human-approval` record as authorized. It files no `process-gap` issue and appends no
    `pr-merged-without-review`.
  - A bot merge with no such record is still a violation.

  *AC:* replaying step 0 over the #2211 merge files nothing. A synthetic bot merge with no record
  still files.
- **REQ-11 (the worker never merges or clears).** `agent_class="worker"` still gives PROPOSE_ONLY.
  The classifier and the removal run only under the overseer identity. A worker or human-proxy
  identity calling them gets a refusal. *AC:* a test checks the refusal.
- **REQ-12 (idempotent).** Each of these does nothing, writes nothing and audits nothing:
  - a cycle after the merge (the PR is no longer open; step 0 deduplicates by PR number);
  - a re-run on an unchanged, still-unapproved head (no removal, no duplicate verdict, per the
    #1215 precheck and the wrapper's G3/G4/G6 guards);
  - a re-run after a removal whose merge was deferred by a non-clean check (no second removal event).
- **REQ-13 (human-facing text matches behaviour).** The `APPROVE` expected-action definition and the
  #2174 visible sign-off sentence state the behaviour that applies:
  - in REQ-4 cases, "the overseer merges it on its next cycle after your approval";
  - in every other case, which act is needed, for example resolving a thread or replying to a
    question.

  `overseer.md`'s "press Merge (every other case)" text (VF-6) is updated to match. Per #2170, the
  text never names a script or a shell step.
- **REQ-14 (regression fixture: PR #2211).** A fixture replays PR #2211 at 2026-10-30 05:39Z:
  - the head;
  - the labels (`needs-human` added by the overseer);
  - the reviews (the overseer's marked `HUMAN_REQUIRED action=APPROVE` sign-off, then the human's
    approval);
  - the check runs (all green) and `mergeable_state=clean`.

  The next cycle's result is: label cleared and audited, merge with the pinned SHA, one
  `merged-on-human-approval`, and no human merge. The same fixture with a human-added `needs-human`
  does not merge. The same fixture with `hos-halt` does not merge.

## 4. Out of scope / non-goals

- Who is designated (ruled under #2174 ESC-2), the CODEOWNERS model (#1936), and branch-protection
  settings. `require_code_owner_reviews`, `require-human-approval` and `require-overseer-approval`
  stay as they are and still enforce at GitHub merge time.
- Reviving the #761 `prior_overseer_decision` scan (VF-2). The #1839 ruling stands.
- #2209's routing of rejections to the worker, and #902's detection patterns.
- `needs-human` on issues, and every `release-request` flow.
- Changing `OVERSEER_CEILING` or the tier matrix for PRs **without** a designated approval.

## 5. Constraints and coordination

- **#2174 is merged** (PR #2225). Reuse its marker, helpers and designated set. Do not fork them.
- **#2209** edits the same step-6 area. Whichever lands second rebases onto the other. Its ESC-2 (an
  overseer finding on a head the human already approved) is consistent with REQ-5's last bullet: a
  merits finding means the latest verdict is not `action=APPROVE`, so there is no merge on approval
  alone.
- **Batch merges** follow step 6b: one at a time, with approvals re-read before each merge. This
  matters because `dismiss_stale_reviews` dismisses sibling approvals when the base advances.
- **Self-application:** this PR merges under the old flow (the human merges it).

## 6. Acceptance (issue level)

1. Replaying #2211, the overseer's next cycle merges it and audits `merged-on-human-approval` with
   the approver and SHA. There is no human merge and no bypass (REQ-4, REQ-10, REQ-14).
2. An approval on an older head does not merge, and the PR re-enters review (REQ-7).
3. A PR whose `needs-human` comes from a human, a #902 hold, or an open question is not merged by an
   approval alone (REQ-2, REQ-5, REQ-6).
4. `hos-halt` still blocks (REQ-5).
5. A second cycle after the merge does nothing (REQ-12).

## 7. Escalations for the human

These design questions were resolved from repo evidence and need no ESC:
- **How the overseer identifies its own hold.** By label-event provenance, plus its own head-bound
  #2174 marker with `action=APPROVE`, plus a recomputed absence of every other hold (REQ-2). No
  single signal is enough, and ambiguity fails closed.
- **Who owns the removal.** Deterministic Python called by the prompt (D-A).
- **#761.** The `prior_overseer_decision` scan is dormant by ruling (VF-2). The requested-reviewer
  guard clears when the human reviews (VF-3). Neither needs changing. Only the #756 label guard
  (VF-1) and the R9.1.1 stub (VF-5) stand in the way.

- **ESC-1. The R9.1.1 re-check is a stub that always fails (VF-5).** Until the #152 follow-up flips
  `_dep_ceiling_check_present()`, no merge decision can pass it. The issue requires the re-check to
  stay.
  - (A) On the human-approval path only, run the live branch-protection checks that already exist
    below the stub:
    - protection is enabled;
    - at least one approving review is required;
    - `dismiss_stale_reviews` is on;
    - the overseer is not a bypass actor.

    Skip only the stub's ceiling question, because the designated human's approval answers it. The
    AUTO_MERGE path without a human approval is unchanged.
  - (B) Keep the stub. Nothing merges on approval until #152's follow-up lands, so this issue is not
    delivered.
  - (C) Drop the re-check on this path and rely on GitHub's merge-time enforcement.

  *Default: A.* It keeps a real live re-check and changes nothing for unapproved PRs. **This touches
  merge-authority safety; please choose.**
- **ESC-2. Which sign-off actions an approval satisfies.** The issue clears only a hold "applied only
  to wait for approval". TD-2174 D7, however, describes approving plus resolving the thread as the
  human's override of an overseer `DO NOT MERGE` or `REQUEST CHANGES`. It also covers
  CONDITIONAL_PROCEED PRs whose CP threads the human resolves.
  - (A) Only `action=APPROVE` sign-offs. In every other case the human still presses Merge.
  - (B) Every action except `DECIDE`, provided every review thread is resolved. The human's approval
    plus resolved threads is the override, and the overseer then merges.
  - (C) Every action.

  *Default: A.* It follows the issue text literally and fails closed. (B) is closer to "approval alone
  should suffice" for overrides.
- **ESC-3. The overseer's own approval-request thread (VF-8).** On protected-surface PRs the §8.2
  escalation is a resolvable thread. Branch protection then needs a second human act, resolving it,
  before merge.
  - (A) On an eligible approval, the overseer resolves its own approval-request thread, audited. The
    thread must be overseer-authored, marker-identified, on the approved head, with `action=APPROVE`
    and no replies from anyone else.
  - (B) For `action=APPROVE` escalations, post no resolvable thread. The verdict's executive summary
    carries the ask.
  - (C) The human resolves the thread (status quo).

  *Default: A.* It keeps #1207's thread and removes only the mechanical act. Whether #2211's thread
  was hand-resolved is unverified.
- **ESC-4. Release-related PRs (NG3b).** "Autonomous releases are prohibited."
  - (A) Exclude them. The human still merges release PRs.
  - (B) Include them. The human's approval is the release authorization.

  *Default: A.* NG3b is a standing safety rule, and this issue does not mention releases.

---

```
RISK: HIGH
CONFIDENCE: HIGH on VF-1..VF-11 (re-read at 96d7ae66f); MEDIUM on VF-3 (GitHub request-clearing
  behaviour assumed, not replayed) and VF-8 (#2211 thread state unverified)
CHANGE CLASSIFICATION: structural (direction human-ruled 2026-10-30; ESC-1..4 open)
BLAST RADIUS: every overseer merge decision on human-gated PRs; merge_authority.py, overseer.md step 0
  and step 6, overseer-cron-prompt.md
```

## Human Review Required

This is a structural requirements change on merge authority. The direction is ruled: approval alone
suffices. Before the implementation PR merges, the human must answer or accept defaults for:
- ESC-1, the R9.1.1 stub, without which nothing can merge;
- ESC-2, which sign-off actions an approval satisfies;
- ESC-3, the overseer's own escalation thread;
- ESC-4, releases.
