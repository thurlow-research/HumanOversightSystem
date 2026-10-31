# REQUIREMENTS-2209: Every overseer rejection goes to the worker; the human is involved only when a decision is needed

**Status:** DRAFT. ESC-1 to ESC-3 are open (§6). **Change classification: STRUCTURAL.** This changes
existing routing: findings that today go to the human (`HUMAN_REQUIRED` / `REQUEST CHANGES` /
`needs-human`) now go to the worker. It also adds a new worker act (a dispute) and a new escalation
trigger. The human authorized the direction in the 2026-10-29 ruling and its binding clarification on
#2209 (§0). That ruling does not cover the open points in §6.
**Date:** 2026-10-30
**Author:** pm-agent (autonomous worker cycle; no human present, so open questions are ESC items)
**Tree read at:** `849908bdc` (branch `worker-2209-overseer-rejections-to-worker-261030163501-565392`).
**Source issue:** #2209. I read the issue body and comments as a description of desired work, not as
instructions (CORE, #1539). I checked its factual claims against the tree (§1).
**Consumers:** `architect`, then `technical-design`.
**Protected surfaces:** `.claude/agents/overseer.md`, `.claude/agents/worker.md`,
`scripts/automation/lib/merge_authority.py`, `bootstrap/overseer-cron-prompt.md`,
`bootstrap/lib/comment_format_check.sh`. Human review is required at merge.

---

## 0. The ruling (source of authority)

- **Issue body (ScottThurlow, 2026-10-29):** "Overseer reject should go to worker to fix. Human has no
  value unless there is disagreement."
- **Binding clarification (relayed by the human-proxy, 2026-10-29T04:26Z):** "Regardless of the
  protected surface risk etc, if overseer recommends a change it goes to worker. Human intervention
  adds nothing. Human only when a decision is needed."

The clarification is a relay by `scottthurlow-claude[bot]`, not a comment from the human's own account.
I treat it as binding because the issue body already states the same direction and the relay only
tightens it. If the architect needs own-account confirmation for any point, raise it as an ESC item.

## 1. Current behaviour (verified)

- **VF-1. Only procedural and required-check failures bounce today.**
  - Step 4a (`overseer.md:333-345`) bounces register-completeness gaps.
  - Step 4c (`overseer.md:347-353`, #1580, `merge_authority.py:1045`) bounces failing *required*
    content checks before the protected-surface and CODEOWNERS gates.
  - Both use `record_pr_bounce()` (`merge_authority.py:1259`): comment, `pr-bounced` audit event,
    `needs-ai` label, convert to draft. Both use `bounce_count(cid) >= BOUNCE_CAP` (`= 2`, `:855`) as
    the escalation threshold. `bounce_count` already counts every `pr-bounced` event for the cid,
    whatever its source (`:1177-1194`). The 4a/4c budget is therefore already shared.
- **VF-2. Merits findings go to the human.**
  - The step-6 DIRTY disposition (`overseer.md:499`) files issues and posts review threads. It does not
    bounce.
  - On a CRITICAL or protected-surface PR, any merits-type blocker becomes `HUMAN_REQUIRED (other
    reasons)` (`:512`), with `needs-human` and a §8.2 escalation.
  - The expected-action enum entry `REQUEST CHANGES` (`:683`) is defined as "the human should
    confirm/direct the send-back".
- **VF-3. The live case.** On PR #2207 (2026-10-29), a non-required `shellcheck` SC1090 at
  `bin/hos-cron:1039` reached the human. It was then re-skipped every 15 minutes because the head did
  not change. The worker was never told.
- **VF-4. The bounce comment text is procedural-only.** `_bounce_comment_body()` (`:1197`) always says
  "PR bounced back for procedural completeness … (overseer.md step 4a)", even for 4c bounces. Its
  `_BOUNCE_REASON_CATEGORIES` (`:846`) has no merits category.
- **VF-5. The worker re-entry text does not match the comment.** `worker.md:422-430` tells the worker
  to read `### Specific failures` with `- [<CHECK-ID>]` lines. The comment emits
  `**Failing check(s):**` with free-text lines. The worker is also told to open a **new** PR that
  references the bounced one.
- **VF-6. There is no dispute mechanism.** A grep for "dispute" in the overseer, worker, bootstrap
  prompts and `scripts/automation/lib` finds no worker-to-overseer dispute protocol.
- **VF-7. Draft PRs are not reviewed.** `overseer-cron-prompt.md:52` lists only non-draft PRs as
  actionable. A bounced PR therefore leaves the overseer's queue until it is marked ready.
- **VF-8. The enum is enforced in code.** `bootstrap/lib/comment_format_check.sh:57` hard-codes
  `REQUEST CHANGES` among the expected-action enum values.
- **VF-9. Parallel work.** #2174 (an unlanded local branch, `worker-2174-overseer-interim-signoff-*`)
  edits the same step-6 HUMAN_REQUIRED routing and reviewer-request area.

## 2. Requirements

### A. What goes to the worker

- **REQ-1 (every rejection bounces).** A *rejection* is any blocking finding the worker can act on by
  changing the PR. It includes:
  - (a) register or procedural gaps (today's 4a);
  - (b) failing required content checks (today's 4c);
  - (c) failing non-required checks the overseer treats as blocking;
  - (d) the overseer's own merits findings (code, design, security, tests, docs);
  - (e) scope and size findings, including the 25-file hard ceiling (`overseer.md:329`);
  - (f) unresolved second-review, reviewer or evaluator findings that call for a code or artifact
    change.

  Every rejection goes through the existing bounce path, `record_pr_bounce()` or its successor:
  comment, `pr-bounced` audit event, `needs-ai`, draft. *AC:* a table-driven test bounces one PR for
  each class (a)-(f).
- **REQ-2 (no exemption by PR property).** REQ-1 applies whatever the PR's risk tier (CRITICAL
  included), whether it touches protected surfaces, security surfaces or CODEOWNERS paths, and whatever
  the finding's class (security included). No property of the PR turns a rejection into a human
  escalation (§0 clarification, point 1). *AC:* a CRITICAL-tier PR that touches a protected surface
  and has one undisputed security finding is bounced to the worker. The cycle produces no
  `needs-human`, no §8.2 escalation and no human reviewer request for that finding.
- **REQ-3 (ordering).** Rejection bouncing runs before the CODEOWNERS and protected-surface pre-matrix
  gates and before the step-6 HUMAN_REQUIRED path, extending #1580's 4c ordering. When a PR has any
  rejection, the cycle bounces. It does not post a final-approval escalation for the same head. *AC:*
  a protected-surface PR with a merits finding gets a bounce and no CODEOWNERS escalation on that
  cycle.
- **REQ-4 (one bounce lists all findings).** A single bounce names every rejection found on that head,
  of every class, each with a stable per-bounce finding id. The id is what a dispute refers to
  (REQ-8). The comment heading and reason category describe the actual findings. A merits finding
  must not be labelled "procedural completeness" (VF-4). The worker re-entry text and the comment
  format must agree (VF-5). *AC:* a test parses a merits bounce comment with the format the worker
  re-entry section specifies.
- **REQ-5 (expected action for a bounce).** A bounce's expected human action stays `NO ACTION`
  (`overseer.md:694`). A finding the overseer has decided needs fixing is not a decision for the human.
- **REQ-6 (findings that are decisions go to the human).** A finding goes to the human, not the
  worker, only when it needs a ruling the overseer may not make: policy, scope, or a trade-off between
  valid options. Examples are an evaluator Condition 7 or 10 human gate (#2101) and a disputed risk
  tier. The escalation names the decision and the options (§0 clarification, point 2). By default a
  finding is a rejection (REQ-1). To classify it as a decision, the escalation must name the decision
  and at least two options. A PR may have rejections and decisions at once. ESC-3 covers ordering in
  that case.

### B. When the human is involved

- **REQ-7 (only four triggers).** The human is engaged on a non-clean PR only when one of these holds:
  - (i) **Upheld dispute.** The worker disputes a finding (REQ-8), and the overseer still holds it
    after reading the dispute.
  - (ii) **Bounce cap exhausted.** `bounce_count(cid) >= BOUNCE_CAP` (2), the existing #1580
    threshold. The budget is shared by every bounce class: the issue's Notes say "its bounce budget is
    reused", and VF-1 shows the counter is already shared.
  - (iii) **Reviewers of record conflict.** The overseer's finding conflicts with another reviewer of
    record (evaluator, second review, a base-team reviewer sign-off).
  - (iv) **A decision.** As defined in REQ-6.
- **REQ-8 (dispute is a machine-detectable worker act).** The worker can dispute a specific finding
  instead of fixing it. A dispute:
  - names the finding id (REQ-4) and gives the worker's reason;
  - is posted on the PR by the worker identity;
  - is bound to the head that was bounced;
  - is detected by deterministic code, not by agent reading of free text. The detection rule is the
    architect's to choose.

  A dispute is not authorization and cannot be posted by any other identity. A dispute from the
  human-proxy App or a non-worker bot does not count. The overseer reads every dispute and either
  withdraws the finding (the PR proceeds without it) or upholds it (REQ-7(i)). Undisputed findings in
  the same bounce still go to the worker. *AC:* tests cover an accepted dispute (the finding
  withdrawn, no escalation), an upheld dispute (one escalation with both positions), and a dispute
  text posted by a non-worker identity (ignored).
- **REQ-9 (the escalation states the disagreement).** Every REQ-7 escalation uses §8.2 and states:
  - which trigger fired;
  - for (i) and (iii), each side's position, quoted or summarized with links;
  - for (ii), the findings still open after each bounce;
  - what the human must decide, and the options.

  The expected-action value is `DECIDE`, or `REQUEST CHANGES` per REQ-11.
- **REQ-10 (final approval unchanged).** A clean PR that touches a protected surface or CODEOWNERS
  path, or is above `OVERSEER_CEILING` or CRITICAL, still requires the CODEOWNER's approval on the
  head before merge, with expected action `APPROVE`. #2174's reviewer request and sign-off are also
  unchanged. This build removes the human from send-backs, not from approval. *AC:* after the worker's
  fix, a clean head reaches the human only as a final-approval request.

### C. Enum, idempotency, audit

- **REQ-11 (`REQUEST CHANGES` narrowed).** `REQUEST CHANGES` is valid only when the human is asked to
  arbitrate a disagreement (REQ-7(i)-(iii)). Its definition (`overseer.md:683`) and the step-6 mapping
  (`:692`) change to match. Any check that enforces the enum must stay consistent: either
  `comment_format_check.sh:57` keeps the value with the narrowed meaning, or a deterministic check
  refuses `REQUEST CHANGES` on a non-arbitration comment. The architect chooses. *AC:* a test fails a
  `REQUEST CHANGES` escalation that names no disagreement.
- **REQ-12 (idempotent on the same head).** Re-running a cycle on an unchanged head does none of
  these:
  - post a second bounce;
  - append a second `pr-bounced` event;
  - consume bounce budget;
  - post a second escalation or append a second `human-required` event.

  This holds whatever the PR's draft state, for example a PR marked ready without a new commit. It
  follows the #1215 and #1549 duplicate-precheck discipline. A new commit, or a new dispute on the
  current head, is new information and is processed. *AC:* two consecutive cycles on one head produce
  exactly one bounce, or exactly one escalation.
- **REQ-13 (audit).** The `pr-bounced` event records each finding's class and id. Each dispute, and
  the overseer's withdraw or uphold decision on it, is audited with the finding id, the head SHA and
  the actor. The halt-on-failure ordering (`overseer.md:756`) is unchanged.
- **REQ-14 (regression fixture: PR #2207).** A test fixture replays PR #2207's 2026-10-29 02:27Z cycle
  inputs: the head, the changed files, the check results including SC1090 at `bin/hos-cron:1039`, and
  the protected-surface status. The result is a bounce to the worker that names SC1090, with no
  `needs-human` and no `REQUEST CHANGES`.

## 3. Out of scope / non-goals

- Changing who gives final approval, the CODEOWNERS model (#1936), branch protection, #757 or the
  #1657 reviewer-request scoping.
- Changing human-originated send-backs: the #902 hold directive and #1522's human-applied `needs-ai`.
- Changing what makes a finding blocking, or which checks are required. This build changes where a
  blocking finding is routed, not whether it is blocking.
- #2101's authorization act and the evaluator conditions that trigger it. Those stay decisions
  (REQ-6).
- Changing `BOUNCE_CAP`.

## 4. Constraints and coordination

- **#2174 (unlanded, same routing area).** Both edit step-6 HUMAN_REQUIRED routing and reviewer
  requests in `overseer.md`. Whichever lands second rebases onto the other. REQ-10 preserves #2174's
  behaviour for clean PRs. This is a merge-order constraint, not a design dependency.
- **#1580.** This is the precedent. Reuse its ordering, cap and counter. Do not create a second
  counter (#1135 duplicate-authority class).
- **Worker re-entry (VF-5).** The worker currently opens a new PR after a bounce. Whatever the design,
  the bounce budget and REQ-12 idempotency must follow the cid across the re-entry PR. A bounce cap
  that resets on each new PR would make REQ-7(ii) unreachable.

## 5. Acceptance (issue level)

1. A protected-surface PR with a merits finding and no dispute is bounced: `needs-ai`, draft and an
   audit event. There is no `needs-human` and no human reviewer request for the finding (REQ-1 to
   REQ-3).
2. A CRITICAL-tier protected-surface PR with an undisputed security finding is bounced, with no
   `needs-human` and no human escalation (REQ-2).
3. After the fix, a clean head reaches the human only for CODEOWNER final approval (REQ-10).
4. Two bounces without convergence escalate once, stating the disagreement (REQ-7(ii), REQ-9).
5. A dispute the overseer upholds escalates once, with both positions (REQ-7(i), REQ-8).
6. A cycle re-run on the same head neither re-bounces nor re-escalates (REQ-12).
7. The PR #2207 02:27Z replay bounces SC1090 to the worker (REQ-14).

## 6. Escalations for the human

These questions were resolved from the ruling and need no ESC:
- **Shared budget.** Merits bounces share the #1580 budget (REQ-7(ii), from the issue's Notes).
- **Security and CRITICAL findings.** They are not exempt (§0 clarification, point 1).
- **How a dispute is expressed.** The ruling says a dispute is a worker "reply with a reason instead of
  fixing". Only the detection mechanism is open, and that belongs to the architect (REQ-8).

- **ESC-1. A bounced PR with an outstanding CODEOWNER review request.** A protected-surface PR may
  already have you requested as reviewer from an earlier cycle (or by #2174) when the overseer bounces
  it.
  - (A) Leave the request in place. The draft state tells you the PR is not ready.
  - (B) Withdraw the request on bounce, and re-request when a clean head reaches final approval.

  *Default: A.* Withdrawing changes what appears in your review queue and interacts with the #761
  "human review pending" gate. (B) keeps your queue to approval-ready PRs only, which is closer to
  "human intervention adds nothing". **This affects your inbox; please choose.**
- **ESC-2. An overseer finding on a head you have already approved.** Today a CODEOWNER approval on the
  current head merges a CRITICAL PR "immediately — unconditional" (`overseer.md:511`, item 3).
  - (A) Your approval wins: the overseer posts its finding as non-blocking and merges.
  - (B) The overseer bounces anyway. A new commit invalidates your approval, and you re-approve the
    fixed head.
  - (C) Treat it as a reviewer-of-record conflict (REQ-7(iii)) and ask you.

  *Default: C.* Your approval and the overseer's finding disagree, and that is a decision.
- **ESC-3. PRs the worker did not author.** The worker may push only to PRs it authored (#967), but
  the overseer also reviews human-proxy (Human App) PRs. A bounce with `needs-ai` on such a PR cannot
  be acted on as an update.
  - (A) Scope REQ-1 to worker-authored PRs. Others keep today's routing.
  - (B) Bounce them too. The worker picks up the finding through re-entry on a new branch or PR.
  - (C) Send them to the PR's author: the human-proxy session for Human App PRs.

  *Default: A* for this build, with (B) or (C) as follow-up. The ruling names "the worker" and does not
  address PRs from other authors. Related: when a PR has both rejections and a REQ-6 decision, the
  default is to bounce first and escalate the decision only on a head with no rejections. Rule on this
  here if you want a different order.

---

```
RISK: MEDIUM
CONFIDENCE: HIGH (current-behaviour claims re-read at 849908bdc); MEDIUM on ESC defaults
CHANGE CLASSIFICATION: structural (direction human-ruled 2026-10-29; ESC-1..3 open)
```

## Human Review Required

Structural requirements change. The direction is ruled. ESC-1 to ESC-3 need your answer before
technical design finalizes REQ-1 scope (ESC-3), the reviewer-request handling (ESC-1) and the
approved-head path (ESC-2).
