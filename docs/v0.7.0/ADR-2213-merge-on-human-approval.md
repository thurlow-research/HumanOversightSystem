# ADR-2213: Merge on human approval. One pure function decides it, a live ruleset re-check guards it, and one isolated wrapper executes it. The general gate stub is left alone

**Status:** PROPOSED. AD-1 to AD-12 become binding on `technical-design` once reviewed. The REQ's
ESC-1 is split. ESC-1a, the re-check mechanism on this path, is resolved here (AD-5). ESC-1b, turning
on the general gate, goes to the human. ESC-2, ESC-3 and ESC-4 stay with the human. ARCH-ESC-5 is
new. Every ESC has a recommended default, and the design may proceed on the defaults. Per the REQ,
the implementation PR must not merge until each ESC is answered or its default is accepted.
**Date:** 2026-10-31
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #2213 · **Milestone:** v0.7.0 · **Expected risk tier:** HIGH or above (the
`risk-assessor` decides). This adds a new path by which the overseer merges. Every slice touches a
protected surface. `security-reviewer` is mandatory on S1a, and the cross-vendor second review
applies.
**Inputs:** `docs/v0.7.0/REQUIREMENTS-2213-merge-on-human-approval.md` (the REQ);
`merge_authority.py:44-64,181-285,495-743,1026-1032`; `require_overseer_approval.py:151-292`;
`pr_review_cli.py:482-503`; `merge_config.py`; `github.py:331-496,717-728`;
`overseer.md` step 0, steps 4-6, § Verdict events and the expected-action enum;
`overseer-cron-prompt.md`; `setup_branch_protection.sh:120-170`;
`.github/workflows/require-{human-approval,tier-ceiling}.yml`; TD-2174 D1/D6/D7 and §4;
ADR-1657-AM1; ADR-1357 AD-1/AD-5/AD-7/AD-8 and ESC-1/ESC-2; ADR-1357-AM1 AM-1/AM-4; ADR-2209 AD-5.
Live reads (worker App token, 2026-10-31): PR #2211's reviews, events and merge metadata; the merger
of the last 58 merged PRs; `rules/branches/main`; `rulesets/18044233`; classic
`branches/main/protection`.
**Consumers:** `technical-design` → `coder` → review chain. Edits to `.claude/agents/**` are made by
the top-level session, never by `coder` (#1347).

---

## 0. Verification findings

Each claim was checked against the tree at `96d7ae66f` and against live GitHub. Most of these change
the design.

- **VF-1, VF-2, VF-4, VF-6, VF-7, VF-9, VF-11 confirmed** at the cited lines.
- **VF-3 confirmed live.** On #2211 the worker requested ScottThurlow at 10-29 17:03Z. After the
  approval at 10-30 05:39:47Z, the overseer's 05:42Z verdict records `request-reviewer` skipped with
  `already_reviewed_head` and no outstanding request. GitHub cleared the request when the review
  was submitted.
- **VF-8 confirmed live.** The human-proxy resolved all eight #2211 threads at 05:40:07Z, on the
  human's instruction. One of them was the overseer's own escalation thread. Resolving them was a
  second human act.
- **VF-5 is true, and option A as the REQ wrote it cannot work (AF-1).**
- **AF-1. The checks "below the stub" read an endpoint the overseer cannot read.**
  `detect_server_side_gate()` calls classic `GET /branches/main/protection`, which returns
  **403 "Resource not accessible by integration"** to the App (re-verified live, and see #1731,
  #1588). Flip the stub and that function returns "Protection API read failed" on every call. Its
  fail-closed design guarantees it. The live protection for this repo is a **repository ruleset**,
  `main-protection` (id 18044233, `enforcement: active`):
  - `required_status_checks` includes `require-human-approval`, `require-tier-ceiling` and
    `require-overseer-approval`, plus `tests`, `oversight-gate-*` and `oversight-validator-*`;
  - the `pull_request` rule has `required_approving_review_count: 1`,
    `dismiss_stale_reviews_on_push: true`, `require_code_owner_review: true`,
    `require_last_push_approval: true` and `required_review_thread_resolution: true`;
  - `GET /rulesets/{id}` returns `current_user_can_bypass: "never"` to the calling App.

  The `bypass_actors` list itself is hidden from non-admins. `current_user_can_bypass` is the
  readable, authoritative answer to "can **this** caller bypass?". ADR-1357 AD-8 specified reading
  the classic object. That spec is stale for this repo for the same reason.
- **AF-2. Activating the general gate would newly allow merges with no human approval.**
  - **Who merges today:** all 58 of the most recently merged PRs were merged by `ScottThurlow`. In
    practice there are no autonomous merges today.
  - **How the overseer reaches a merge:** never through `decide_merge_authority()`. It has no
    caller. `bootstrap/merge_authority.sh` exposes only read-only primitives (`gate`, `register`,
    `human-approval`, and so on), and ADR-1357's `overseer_decide.sh` and `overseer_merge.sh` never
    landed. The overseer merges by narrating step 6. Its AUTO_MERGE row is "≤ ceiling, not
    security, not protected, PROCEED, gate detected". It has no #757 human-approval check (that
    check exists only inside the function) and ends in a raw `PUT …/merge`.
  - **What GitHub would allow if `gate` reported detected:** on a non-protected PR,
    `require-human-approval` passes without a human ("gate N/A"). `require-tier-ceiling` passes at
    or below the ceiling. The overseer's own `APPROVED` review satisfies `require-overseer-approval`
    and the one required approving review. `require_last_push_approval` is satisfied because the
    overseer did not push.

  **Result:** flipping `_dep_ceiling_check_present()` globally (and fixing AF-1 so it can read the
  ruleset) would make every clean PR at or below the ceiling that is not protected merge with no
  human. That is a change to autonomous-merge behaviour well beyond #2213. See ESC-1b.
- **AF-3. Clearing the label and calling the existing function cannot deliver #2211.** #2211's
  oversight verdict was **CONDITIONAL_PROCEED** (its 10-29 17:27Z verdict). At `:633`,
  `decide_merge_authority()` returns HUMAN_REQUIRED for any verdict other than PROCEED. That happens
  after the label guard and before the protected-surface approval check. So even with the label
  removed and the stub flipped, #2211 returns HUMAN_REQUIRED. The overseer's 05:42Z verdict told the
  human "remove `needs-human` and this overseer will merge it next cycle". That claim was false
  against the code. It was a narration error of exactly the #1357 kind. Under ADR-1913 the CP
  conditions are carried as resolvable threads. Once those are resolved and the human has approved,
  the verdict gate is a derived marker, not a live reason.
- **AF-4. The REQ's REQ-2(2) would exclude the most common protected case.** TD-2174 D1/§4: on a
  protected-surface PR at or below the ceiling that is sound on the merits, the overseer posts
  `--event approve` **with no marker**, and `valid_interim_signoff()` requires `COMMENTED`. If the
  overseer's own `APPROVED` verdict on the head did not count, those PRs would never qualify.
- **AF-5. Verdict churn after approval.** After the approval, #2211's next overseer verdict changed
  its expected action from `APPROVE` to `OTHER` ("merge it yourself, or remove the label"). After
  #2174, that verdict carries a marker with `action=OTHER`. It would become the latest verdict on the
  head and turn REQ-6's "latest action is APPROVE" condition false, so this path would block itself.
- **AF-6. The human has already ruled on this direction (#1357 ESC-1, 2026-09-11; ADR-1357-AM1
  AM-1).** The ruling says that once a codeowner has approved and the overseer's gates pass, "the
  merge is automatic — no separate 'human clicks merge' step", at every tier. The slices that would
  have implemented it (ADR-1357 slices 2-6) never landed, and #1357 was closed on 10-04 after
  slice 1. The 10-30 ruling quoted in #2213 restates the same direction. TD-2174 D7 ("everywhere
  else the human presses Merge") was a holding position, not a policy.
- **AF-7. ADR-2209 overlaps.** ADR-2209 is PROPOSED and unbuilt. It declares "`PROCEED` plus
  `merge-guard` is the only way to a merge" (REQ-10) and adds a second latest-decision predicate,
  `latest_reviewer_act`. See AD-12.
- **AF-8. Missing helpers.** `github.py` has no reader for issue events, no review-thread reader and
  no merge call. Searches covered `scripts/`, `bootstrap/`, `bin/` and `scripts/automation/lib/*.py`;
  the only `reviewThreads`/`isResolved` use is a write mutation in `post_review_thread.sh`.
  `remove_issue_label`, `add_issue_label`, `list_pull_reviews`, `list_issue_comments`,
  `list_check_runs_for_ref`, `get_ruleset_required_checks`, `get_commit`, `post_comment`,
  `merge_config.resolve_config`, `_is_release_related`, `_verify_authorship_separation`,
  `detect_human_hold_directive`, `_META_GATE_CHECKS` and the `require_overseer_approval.py` helpers
  already exist and are reused (AGENTS.md "Use the Code").
- **AF-9. A CODEOWNERS read can be steered by the PR author.**
  `require_overseer_approval.codeowners_individual_owners(repo_root)` reads the file under
  `repo_root`. In CI that is the trusted base checkout. In the overseer's clone it may be the PR
  branch, which the PR author controls (the ADR-2209 AF-7 class). An author could add themselves as
  an owner and become "designated".

---

## 1. Organizing principle

**The human's approval of this exact head is the authorization. Code decides whether it applies, and
GitHub's own rules are re-read live before the irreversible act.** This path never trusts a marker
the overseer wrote as a *reason to block*. Those markers are the `needs-human` label, a pending
reviewer request and a non-PROCEED evaluator label. It trusts only signals that encode the human's
decision or a real unmet condition: the approval, holds, unresolved threads, checks, `mergeable_state`
and the ruleset.

---

## 2. Decisions

### AD-1. A dedicated pure decision for this path. `decide_merge_authority()` is not modified

- **New module `scripts/automation/lib/approval_merge.py`.** It holds
  `decide_merge_on_human_approval(snapshot, config) -> ApprovalMergeDecision`. The function is pure:
  no I/O, and every input arrives in `snapshot`.
- **It is the only authority for "merge because a designated human approved this head".** The
  narrated CRITICAL-tier rule in step 6 ("merge immediately — unconditional") is **deleted** and
  replaced by this path, not kept beside it (REQ D-A, #1135).
- **`decide_merge_authority()` keeps its signature and behaviour, and its existing tests stay
  untouched.** Reasons:
  1. AF-3: its guard order is built for the autonomous path. Re-ordering it for this path would
     change autonomous outcomes.
  2. Its approval predicate (`_find_human_approval`, first match, single login) is the one VF-4 says
     is wrong. Fixing it inside the matrix is ADR-2209's N-1, not this issue.
  3. One function per path keeps each path's precedence testable on its own.
- **Why this is not the #1135 duplicate-authority class:** the two functions answer different
  questions. The matrix asks "may the overseer merge on its own authority?". This function asks "has
  a human authorized this head, and does nothing stand against it?". Neither function ever answers
  the other's question.

### AD-2. Inputs: one fresh snapshot per invocation, and reads must be complete

The L2 CLI (AD-6) builds the snapshot fresh on every invocation (R9.1.1, ADR-1357 AD-5). Nothing
comes from cache, from the agent, or from an earlier cycle.

| Input | Source |
|---|---|
| PR: `state`, `draft`, `head.sha`, `user.login`, `title`, `labels`, `mergeable_state`, `base.ref` | `get_pull` |
| Changed files | `list_pull_files` |
| Reviews (all pages) | `list_pull_reviews` |
| Issue comments (all pages) | `list_issue_comments` |
| Issue events (all pages), used for the `labeled`/`unlabeled` provenance of `needs-human` | **new** `list_issue_events` |
| Review threads: `isResolved` and the first comment's author | **new** `list_review_threads` (GraphQL, paginated) |
| Check runs on the head | `list_check_runs_for_ref` |
| Head commit date (#902 supersession) | `get_commit` |
| Ruleset gate | AD-5 |
| Config: designated set, overseer login, bot accounts, ceiling | `merge_config.resolve_config` plus AD-4 |
| Audit history for this PR: earlier `merge-on-human-approval-failed` / `-authorized` | `audit_log.read_stream` |

- **Completeness.** Every paginated read either returns all pages or raises.
  `get_ruleset_required_checks` already does this. The new readers and the existing list helpers
  this path uses must refuse a truncated list. A list helper that silently stops on an empty page is
  acceptable; one that stops at a page cap without raising is not.
- **Any read error, unparseable timestamp, missing field or truncation gives
  `UNDETERMINABLE(<what>)`.** It never gives `MERGE`. Fail-closed means a stuck PR, never a wrong
  merge.

### AD-3. The decision: an ordered predicate with four outcomes

**Outcomes:**
- `MERGE(approver, review_id, head_sha)`;
- `DEFER(reason)`: transient, retry next cycle and post nothing;
- `NOT_ELIGIBLE(reason)`: this path does not apply, so the normal review runs;
- `UNDETERMINABLE(reason)`.

The first matching rule wins. Every rule's failure alone must block the merge (one test per rule).

1. **Identity.** The caller is the overseer: `--app overseer` and `HOS_BOT_LOGIN ==
   BOT_OVERSEER_USERNAME`. Otherwise the CLI refuses with exit 3 before it builds the snapshot
   (REQ-11).
2. **Target.** An open, non-draft **pull request**. Otherwise `NOT_ELIGIBLE(not_open_pr)`. Issues,
   and so `release-request` issues, are unreachable by construction (VF-10).
3. **Kill switch.** `hos-halt` is present → `NOT_ELIGIBLE(hos_halt)`, whoever applied it.
4. **Release.** `_is_release_related(title, files)` → `NOT_ELIGIBLE(release)` (ESC-4 default A).
5. **Authorship.** The PR author is not the overseer (`_verify_authorship_separation`, R9.1.4).
6. **Eligible approval.** `eligible_human_approvals_on_head(reviews, bot_accounts, designated,
   head)` is non-empty (REQ-1, TD-2174 D6). Choose the approver deterministically: the eligible
   login with the latest approving review. Record that review's id.
7. **The overseer signed off on this head, and only for approval.** Let `v =
   latest_overseer_verdict_on_head(...)`. It qualifies only if one of these holds:
   - `v.state == APPROVED` (AF-4: the overseer approved on the merits; the only thing missing was the
     human);
   - `valid_interim_signoff(v, head)` is not None with `action == APPROVE`, under either disposition
     (ESC-2 default A).

   No verdict on the head, a marker with any other action, an unmarked `COMMENTED`, or `DISMISSED` →
   `NOT_ELIGIBLE(no_approve_signoff)`. Without this rule, a human approval alone could merge a PR
   the overseer never reviewed on this head. That would break #621.
8. **The label is the overseer's own, if present.** If `needs-human` is on the PR, the latest
   `labeled` event for it must have `actor.login == overseer`. Otherwise
   `NOT_ELIGIBLE(foreign_needs_human)`. If the label is absent, this rule passes (AD-11). Labels are
   not merge gates on GitHub, so this is the only thing the label means on this path.
9. **No human hold.** Run `detect_human_hold_directive()` **once per designated login**: reuse it,
   do not widen its regex. Its input is the issue comments together with the designated humans'
   review bodies on this head (`submitted_at` is mapped to `created_at`), and `head_committed_at`
   applies. Any hit → `NOT_ELIGIBLE(hold_directive)`. This is strictly wider than #902 today, which
   reads only one login's issue comments. That is the safe direction.
10. **The approval is the human's last word (ARCH-ESC-5 default).** No designated-human issue
    comment or `COMMENTED` review is timestamped after the chosen approving review. Otherwise
    `NOT_ELIGIBLE(human_comment_after_approval)`, and the normal review reads the comment. The
    human can re-establish the order by approving again.
11. **No open question.** Every review thread is resolved (REQ-6). Otherwise
    `NOT_ELIGIBLE(unresolved_thread)`. With ESC-3 at its default (status quo), that includes the
    overseer's own escalation thread.
12. **No earlier failure on this head.** No `merge-on-human-approval-failed` record exists for
    `(pr, head)` → otherwise `NOT_ELIGIBLE(merge_failed_on_head)` (REQ-9). A new head resets this.
    So does a designated human removing `needs-human` after the failure record (a real human act).
13. **Checks.** Every ruleset-required context (AD-5's read) **and** `Agent static checks` has a
    latest check run on the head with `status: completed` and `conclusion: success`.
    - Absent, queued or in progress → `DEFER(checks_pending)`.
    - If that has lasted more than 2 h since the approval (the same stall guard as step 2a) →
      `NOT_ELIGIBLE(checks_stalled)`.
    - Any other conclusion → `NOT_ELIGIBLE(check_not_success)`.
14. **Mergeability.** `mergeable_state == "clean"`. `unknown` is re-polled a bounded number of times
    (ADR-1357 AD-6), then `DEFER(mergeable_unknown)`. Any other value →
    `NOT_ELIGIBLE(mergeable_<state>)`.
15. **Live gate** (AD-5) passes → `MERGE`. Otherwise `NOT_ELIGIBLE(gate:<reason>)`.

**Not inputs, deliberately:**
- tier, the ceiling, protected/security/CODEOWNERS paths, and the evaluator verdict label. A
  designated approval of the head is what those gates require (REQ-4, AF-3, AF-6). GitHub still
  enforces `require_code_owner_review` through rule 14;
- `requested_reviewers` and `prior_overseer_decision` (AD-10).

### AD-4. Reuse the approval and sign-off predicates. The CODEOWNERS read is pinned to the default branch

- **Loading.** `approval_merge.py` loads `require_overseer_approval.py` by file path. The precedent
  is `pr_review_cli._load_require_overseer_approval`. Move that loader into one shared place (for
  example `merge_config`) rather than writing a third copy.
- **Used as they are, with no forks:** `designated_humans`, `eligible_human_approvals_on_head`,
  `latest_overseer_verdict_on_head`, `valid_interim_signoff` and `parse_interim_marker`.
- **`_find_human_approval` and `has_human_approval` are not used and not changed.**
- **AF-9: the designated set is built from the default branch's `.github/CODEOWNERS`, never the
  working tree.** Read it with `git show origin/<default>:.github/CODEOWNERS` into a temporary root,
  or with the contents API at `ref=<default>`, and pass the parsed owners to `designated_humans()`.
  - An unreadable file → `UNDETERMINABLE(codeowners)`.
  - An empty designated set → `UNDETERMINABLE(no_designated_humans)` (TD-2174 D6).

### AD-5. The R9.1.1 re-check on this path is a real, ruleset-based live read. The general stub is not touched (ESC-1a resolved)

- **New function in `merge_authority.py`:** `verify_merge_gate_live(owner, repo, branch, config) ->
  GateDetectionResult`, built on `github.py` readers. It passes only if **all** of these hold.
  1. `get_ruleset_required_checks()` succeeds and its contexts include every member of
     `_META_GATE_CHECKS`. Use that set with `config.tier_ceiling_check_name` substituted for the
     ceiling entry. No new literal.
  2. `rules/branches/<branch>` returns a `pull_request` rule with
     `required_approving_review_count >= 1` and `dismiss_stale_reviews_on_push == true`.
  3. For every ruleset id that the rules response attributes those rules to, `GET /rulesets/{id}`
     returns `current_user_can_bypass == "never"`.

  Any read failure, missing rule or other value fails with a named reason.
- **Classic protection is not consulted.** The App cannot read it (AF-1). It is also not needed:
  ruleset rules apply in addition to classic protection, and a classic bypass allowance does not
  bypass a ruleset. Ruleset enforcement plus "this caller can never bypass" is therefore sufficient
  proof that GitHub will independently enforce the three approval gates against this merge.
- **Re-read timing.** This read runs inside the same invocation, immediately before the merge
  `PUT` (REQ-8). It is never cached.
- **Confinement.** `_dep_ceiling_check_present()`, `detect_server_side_gate()`, the `gate`
  subcommand and the step-6 AUTO_MERGE prose are **unchanged** in #2213. The narrated AUTO_MERGE
  path therefore stays exactly as reachable as today: unreachable while `gate` reports
  PROPOSE_ONLY. The new function may later replace the stub's body. That is ESC-1b's decision and
  needs its own issue. Only the stub's docstring may be updated to point at ESC-1b. Its behaviour
  and reason string stay as they are.

### AD-6. Execution surface and write order

- **L3 `bootstrap/overseer_merge.sh on-human-approval --app overseer --pr <N> [--repo <o/r>]`.**
  This is the isolated irreversible wrapper ADR-1357 AD-1 reserved. The positional mode is a closed
  enum, so a later autonomous mode can be added without a new script.
- **L2 `scripts/automation/overseer_merge_cli.py`.** It fetches, calls AD-3, executes and prints one
  JSON object.
- **A read-only twin, `bootstrap/merge_authority.sh approval-merge --pr <N>`.** It returns the same
  decision record without writing. The human and the proxy use it to ask "would it merge?", and the
  fixture tests use it.
- **ADR-1357 AD-2 applies.** No `--force`, no `--skip-*`, and no flag or environment variable widens
  the decision.
- **Exit codes:**
  - 0: decided. That covers `MERGED`, `DEFER`, `NOT_ELIGIBLE` and `UNDETERMINABLE`, with the outcome
    in the JSON;
  - 1: operational failure, including a merge that failed after authorization;
  - 2: usage error;
  - 3: identity refusal.
- **Write order on `MERGE`.** Each step halts on failure (SPEC-378):
  1. Recompute the full AD-3 decision inside this invocation. The read-only twin's earlier answer is
     never trusted.
  2. **Write-ahead audit** `merge-on-human-approval-authorized` {pr, head_sha, approver,
     approving_review_id, overseer_verdict_id, verdict_kind (`approved` | `marker:<disposition>`),
     label_provenance (labeled-event id and actor, or `absent`), gate evidence, cycle id}. If this
     write fails → exit 1. Nothing has changed on GitHub.
  3. `PUT /pulls/{n}/merge` with `{"merge_method":"squash","sha":<head_sha>}`, through a **new**
     `github.merge_pull()`. The pinned `sha` makes a racing push fail the merge rather than merge an
     unapproved head (REQ-9).
  4. On success (`merged: true`):
     - remove `needs-human` if present, best effort: the PR is closed, so the label is cosmetic now;
     - write `merged-on-human-approval` {pr, head_sha, merge_commit_sha, approver,
       approving_review_id, verdict_kind, label_removed, cycle id};
     - a failure in either of these is reported in the JSON, and the exit code is still 0.
  5. On merge failure:
     - write `merge-on-human-approval-failed` {pr, head_sha, http_status, message};
     - post one failure comment (`post_comment`);
     - add `needs-human` if it is absent;
     - exit 1.
- **Why the label comes off *after* the merge, not before (a deviation from REQ-3's order):** a
  label is not a GitHub merge gate. AD-3 rule 8 has already shown the label is the overseer's own.
  Removing it first would need a compensating re-add whenever the audit write or the merge fails,
  and would leave a window where it is absent without a merge. With this order, every failure
  leaves either nothing changed or the label in place.
- **REQ-3 is still met in substance.** Removal happens only after a `MERGE` decision. It is audited
  by the completion record's `label_removed` field. It never touches `hos-halt` or any other label.
  It never happens on an issue.

### AD-7. Idempotency

- **After a merge:** the PR is closed. The next invocation returns `NOT_ELIGIBLE(not_open_pr)` and
  writes nothing.
- **On an unchanged head that is still unapproved:** `NOT_ELIGIBLE(no_eligible_approval)` and no
  writes. The normal review's #1215 precheck and the wrapper's G3/G4/G6 guards govern the rest.
- **After a crash between steps 2 and 3:** a second `-authorized` record for the same `(pr, head)` is
  not written; the existing one is reused. The decision is recomputed in full either way.
- **After a failed merge:** AD-3 rule 12 stops a retry on that head, so the run returns
  `NOT_ELIGIBLE(merge_failed_on_head)`.
- **DEFER posts nothing and writes nothing.**

### AD-8. Overseer cycle wiring

- **Step 1, per PR in `HOS_ACTIONABLE_PRS`:** run `bash bootstrap/overseer_merge.sh on-human-approval
  --app overseer --pr <n>` **first**. It is a literal command, in the #1524 `check_pr_reviewed.sh`
  shape, and its stderr is never suppressed. Then act on the outcome:
  - `MERGED`: done with this PR.
  - `DEFER`: **skip the PR this cycle**. Post nothing and run no review. This removes the AF-5
    churn: an approved, unchanged head never gets a new verdict while it waits for checks.
  - `NOT_ELIGIBLE` or `UNDETERMINABLE`: run the normal chain unchanged. That chain cannot merge on
    approval, because the CRITICAL rule (3) is deleted, and AUTO_MERGE is as unreachable as today.
  - Exit 1: report it and skip the PR this cycle.
- **Step 6 text (S1b):**
  - delete HUMAN_REQUIRED (CRITICAL tier) item (3);
  - on HUMAN_REQUIRED and PROPOSE_ONLY with `--expected-action APPROVE`, the expected action **stays
    `APPROVE` after a human approval on the head**. Never switch to `OTHER` to ask the human to
    remove the label (the AF-5 "derived markers are not reasons" rule);
  - the `APPROVE` enum text and #2174's visible sentence say "the overseer merges it on its next
    cycle after your approval, once checks are green and every review thread is resolved", and name
    any other act still needed (REQ-13, #2170: no script names).
- **The cron prompt's Step 1 gains the same literal line.**

### AD-9. Step 0 recognizes an authorized overseer merge

- **New pure function `classify_bot_merge(pr_number, merged_head_sha, merged_by, audit_events)` in
  `approval_merge.py`.** It returns `authorized_on_human_approval` only if all of these hold:
  - `merged_by` is the overseer login (not any bot);
  - a `merge-on-human-approval-authorized` record exists for that pr and head.

  Otherwise it returns `unauthorized`.
- **Exposed read-only as `merge_authority.sh merge-provenance --pr <n>`.**
- **Step 0's bot branch calls it.**
  - `authorized_on_human_approval`: log only. File no `process-gap` and append no
    `pr-merged-without-review`. A missing `merged-on-human-approval` completion record is logged as a
    warning, not as a violation.
  - `unauthorized`: today's behaviour, unchanged (REQ-10).
- **The write-ahead record is the key, not the completion record,** so a failed audit write after
  the merge cannot turn a legitimate merge into a false process-gap.

### AD-10. #756, #761 and #1839: what stays and what is bypassed

- **#756 label guard, #761 `prior_overseer_decision` and the requested-reviewer guard:** all stay in
  `decide_merge_authority()`, unchanged. This path does not call that function.
- **The #761 scan stays dormant (#1839 stands).** Nothing here revives it.
- **The requested-reviewer guard is not an input.** A pending request for one designated human does
  not block a merge that another designated human approved. TD-2174 D6 already makes any designated
  approval sufficient for `require-overseer-approval`. This settles ADR-1357-AM1 AM-4's routed
  question **for this path only**. For the matrix it is still open.

### AD-11. What `needs-human` means on a PR

- **Once the overseer applies it, `needs-human` on a PR means "the overseer is waiting for you". It
  is no longer a way for the human to hold the PR.** The human holds a PR with `hos-halt`, a #902
  comment, `CHANGES_REQUESTED`, or simply by not approving.
- **A `needs-human` that a human or another actor applied is respected** (AD-3 rule 8).
- **`docs/LABELS.md` states this (S1b).**
- **No consumer reads an overseer-actor `unlabeled` event as a resume.** The worker's R5 check reads
  only the human's own event, on issues only. No change is needed; one test pins it.

### AD-12. Coordination with ADR-2209 (PROPOSED, unbuilt)

- **One seam for the pre-merge checks.** AD-6 step 1 runs the live re-checks (rules 9 and 11-15)
  through one internal function, `_pre_merge_live_checks()`.
- **When #2209 S1 lands `merge-guard`, that seam calls it.** It does not keep a parallel copy.
  `merge-guard`'s legacy and worker modes both already require the approval and the live #902 and
  required-check re-checks.
- **ADR-2209's REQ-10 ("the only way to a merge") is read as "the only way to an autonomous
  merge".** This path is the second route, and it goes through `merge-guard` once that exists.
- **ADR-2209's `latest_reviewer_act` should reuse `eligible_human_approvals_on_head` rather than
  build a third latest-decision predicate.** Raise this in #2209's design review.
- **Whichever of the two lands second does the rebase onto the other (REQ §5).**

---

## 3. Failure modes

| Attempt or fault | Outcome |
|---|---|
| A push lands between the decision and the merge | The pinned `sha` gives 409. A failure record is written, and the next cycle reviews the new head |
| A human approves, then posts "wait" (comment or review body) | Rule 9 or rule 10. No merge |
| A human approves, then CHANGES_REQUESTED or a dismissal | The latest decision is not APPROVED (rule 6). No merge |
| The approval is on an older head | Rule 6. The next normal review runs on the new head (REQ-7) |
| A human-added `needs-human` on an approved, all-green PR | Rule 8. No merge |
| The PR author edits CODEOWNERS on the head to designate themselves | The designated set comes from the default branch (AD-4) |
| A bot or human-proxy App approval | `is_bot_reviewer` excludes it (rule 6) |
| The worker or human-proxy invokes the wrapper | Exit 3 (rule 1) |
| An issue-events, reviews or threads read fails or is truncated | UNDETERMINABLE. Normal review, no merge |
| The ruleset is relaxed (a context dropped, bypass granted) | Rule 15 fails, so no merge |
| The merge succeeds but the completion audit fails | Exit 0 with the failure in the JSON. Step 0 keys on the write-ahead record (AD-9) |
| Checks never finish | DEFER, then NOT_ELIGIBLE after 2 h, and the normal review names the stall |
| Residual: the human holds by adding `needs-human` on top of the overseer's label (a no-op, so no event) | Not detected. Disclosed in AD-11. Use `hos-halt` or a comment |
| Residual (accepted, #2228): the base branch is retargeted between the pre-PUT re-read and the merge PUT | The PUT pins the head, not the base. Narrowed by `_preflight` and caught after the fact by `_verify_base_after_merge` (`MERGED_BASE_MISMATCH`, escalated). See the note below |

**Accepted residual: base retarget before the PUT (ruling A on #2228, 2026-10-31).** GitHub's merge
API can pin the head SHA but cannot bind the base branch. S1a re-reads the PR (base, head, state,
draft, labels, reviews, comments including edits) immediately before the PUT (`_preflight` in
`overseer_merge_cli.py`) and checks the merged base afterwards (`_verify_base_after_merge`, which
escalates `MERGED_BASE_MISMATCH`). A retarget inside the window between that re-read and the PUT is
not prevented. The human accepted this residual because only an actor who already has write access
can retarget a PR. The codex second review's CWE-367 finding on `overseer_merge_cli.py` is
dispositioned against #2228. Option B, a protection ruleset covering every branch, is deferred
hardening that may be filed later. It is not part of S1a.

---

## 4. Slices

| Slice | Content | Files (≈) | Gate |
|---|---|---|---|
| **S1a: code, inert until wired** | `approval_merge.py` (`decide_merge_on_human_approval`, `classify_bot_merge`); `merge_authority.py` (`verify_merge_gate_live`, plus the stub docstring only); `github.py` (`list_issue_events`, `list_review_threads`, `merge_pull`, ruleset-detail read); `overseer_merge_cli.py` and `bootstrap/overseer_merge.sh`; `merge_authority_cli.py` plus `merge_authority.sh` (`approval-merge`, `merge-provenance`); the shared loader move. Tests: one negative per AD-3 rule; the **#2211 replay fixture**, with its real 10-29/10-30 reviews and events, the overseer's 17:27Z verdict rewritten as the post-#2174 marked `HUMAN_REQUIRED action=APPROVE` sign-off, resolved threads, green checks and a clean state → `MERGE` with the pinned SHA and both audit records; the same fixture with a human-added label → NOT_ELIGIBLE; with `hos-halt` → NOT_ELIGIBLE; a 409 → failure record and no retry; `classify_bot_merge` over the replay → authorized, and over a synthetic bot merge → unauthorized; identity refusal; the gate's fail-closed cases | ~13 | ESC-1b is not needed. The ESC-2/4 and ARCH-ESC-5 defaults are encoded |
| **S1b: wiring and text** | `overseer.md` (step 0 branch, step 1 call, delete CRITICAL (3), the expected action stays APPROVE, the enum text); `overseer-cron-prompt.md`; contract §6a (three events); `docs/LABELS.md`; `DECISIONS.md`; text-pin test | 6 | S1a merged. Edits under `.claude/agents/**` are made by the top-level session |
| **S2: thread handling** | Only if the human picks ESC-3 B or A | ≤6 | ESC-3 |

- **The smallest slice that delivers the replay-#2211 acceptance (REQ-14, and the decision and
  step-0 halves of acceptance 1) is S1a.**
- **Live delivery needs S1b.** It must merge in the same release as S1a, and wrappers land before
  the prose (ADR-1357 AD-11).
- **Both slices merge under the old flow:** the human merges them.

---

## 5. Positions on the escalations

| ESC | Status | Recommendation, and the default the design proceeds on |
|---|---|---|
| **ESC-1a** (which live re-check guards this path) | **Resolved, AD-5.** The REQ's option A is not implementable (AF-1). Replaced by a ruleset-based live check confined to this path | — |
| **ESC-1b** (new, for the human) Turn on the general gate: make `detect_server_side_gate` use AD-5's check | **Human.** AF-2: this would newly let PRs at or below the ceiling that are not protected merge **with no human approval**, through the narrated AUTO_MERGE row. That is a merge-authority and safety change, and it touches the #757 / v0.4.0 / #1839 tension | **Not in #2213.** Open a separate issue that also decides whether #757's universal human approval stands. Default: stub unchanged |
| **ESC-2** (which sign-off actions an approval satisfies) | **Human** (it decides whether an approval overrides the overseer's own DO NOT MERGE) | **A: `APPROVE` only, plus the overseer's own APPROVED verdict (AF-4).** A already covers #2211, whose CONDITIONAL_PROCEED expected action was `APPROVE` |
| **ESC-3** (the overseer's approval-request thread) | **Human** (it changes what the human must do) | **Recommend B:** post no resolvable §8.2 thread when the expected action is `APPROVE`. The ask is already carried by the reviewer request and the verdict (#2174). B removes a mechanism, where A adds a thread-resolving write and a heuristic to identify the thread. **Design default for S1: C (status quo),** which needs no new mechanism. #2211's threads were resolved by hand (VF-8), so the replay still holds |
| **ESC-4** (release-related PRs) | **Human** | **A: exclude them** (AD-3 rule 4). NG3b is a standing rule |
| **ARCH-ESC-5** (new) A designated human's comment after the approval blocks the merge until they approve again (AD-3 rule 10) | **Human** (user-visible: "thanks, ship it" delays the merge by a cycle) | **Strict, block.** Free-text questions are not caught by #902's regex. Approving again is a cheap, unambiguous reset |

---

## 6. Product boundary, startup gap and affected sign-offs

- **Product boundary.**
  - **Cleared by human rulings:** the direction (#2213, 2026-10-30) and automatic merge after a
    designated approval at any tier (#1357 ESC-1, 2026-09-11). Both rulings cover the user-visible
    change: the human no longer presses Merge on approved PRs. Because of F9 that covers almost
    every PR they approve.
  - **Not cleared, so escalated:** ESC-1b, ESC-2, ESC-3, ESC-4 and ARCH-ESC-5.
  - **No new service, no new trust boundary, no retention change.** Three new audit event types are
    written to the existing trail.
- **Startup gap: yes.** #1357 ESC-1's ruling (09-11) made this behaviour required, but ADR-1357 AM-1
  left slice 4 blocked and #1357 was closed with slices 2-6 unbuilt. TD-2174 D7 then re-stated "the
  human presses Merge". The worker should annotate #2213, or open an issue labelled
  `startup-artifact-gap`, referencing #1357. This session is not permitted to file it.
- **Affected sign-offs:**
  - **TD-2174 D7, and the `APPROVE` enum and visible-sentence text, are superseded for the
    `APPROVE` case.** The code built and approved under #2174 stays valid: the gates, the marker and
    the G6 guard are all unchanged. Its D7 *text* is re-reviewed in S1b. Nothing else that #2174
    approved is orphaned.
  - **ADR-1657-AM1 stands.**
  - **ADR-1357 AD-8 is corrected by AF-1:** the classic-protection read is stale. Only the unbuilt
    slice 5 was designed against it, so no sign-off is orphaned.
  - **ADR-2209 is PROPOSED and unbuilt.** No sign-off is orphaned. AD-12 is a design-review input
    for #2209 S1.

---

## Escalation flag (CORE self-flag)

```
RISK: HIGH
CONFIDENCE: HIGH on AF-1..AF-6 (live reads 2026-10-31); MEDIUM on AD-5's sufficiency argument
  (ruleset-over-classic layering and current_user_can_bypass semantics are GitHub-documented
  behaviour, not replayed by a deliberate bypass test)
CHANGE CLASSIFICATION: structural (new overseer merge path; direction human-ruled twice)
BLAST RADIUS: every PR a designated human approves; overseer step 0/1/6; merge_authority.py
  (additive); ESC-1b deliberately excluded
```

## Human Review Required

This adds a path by which the overseer merges. Before the S1a/S1b PRs merge, the human answers or
accepts the defaults for:
- **ESC-1b**: keep the general gate stub, and file a separate issue;
- **ESC-2**: A;
- **ESC-3**: B recommended; S1 ships C;
- **ESC-4**: A;
- **ARCH-ESC-5**: strict.
