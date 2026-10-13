# REQUIREMENTS-1660/1662 — One meaning for CHANGES_REQUESTED: hold merges, stop the false needs-fix

Issues: #1660 (fail-open: the merge-authority matrix cannot see a CHANGES_REQUESTED review) and
#1662 (fail-closed: worker routing counts every CHANGES_REQUESTED review ever posted and livelocks).
Both are bug, priority:high, milestone v0.7.0. Author: pm-agent. Date: 2026-10-13.
Change classification: **structural**. It changes existing routing behaviour, changes a
requirement already approved in REQUIREMENTS-1644-AMENDMENT-2 (REQ-C24 item 1, "today's rules,
unchanged"), and adds a new merge-authority hold signal. ESC-1..ESC-6 below are human decisions.
Design may proceed under the recommended defaults, but coding of each affected part waits for its
ruling.
Protected surfaces touched by any implementation: `bin/**` (worker routing), `bootstrap/**`
(`merge_authority.sh`, `worker-cron-prompt.md`), `.claude/agents/**` (`overseer.md`),
`scripts/framework/**` (if the T3.0b classifier carries the routing). All of these go through the
human CODEOWNERS gate.

## Problem (restated as product behavior)

One GitHub signal, a CHANGES_REQUESTED review, is read in two places and gets a different wrong
answer in each.

1. **Merge authority does not see it (#1660).** `detect_human_hold_directive()`
   (`scripts/automation/lib/merge_authority.py:120`) only scans issue comments from
   `GET /issues/{n}/comments`. `decide_merge_authority()` (`:498`) has no CHANGES_REQUESTED handling.
   `bootstrap/merge_authority.sh hold-directive` reports `hold_active: false` with
   `comments_scanned` counting comments only (PR #1658, cycle 2026-09-14T23:06Z). Today nothing merges
   unsafely. The #757 human-approval assertion and GitHub branch protection both still block. What is
   lost:
   - The disposition and audit reason cannot tell "no human has looked" apart from "a human looked
     and said no".
   - The #902 step in `overseer.md` that dismisses the overseer's own standing APPROVED never fires
     on a CHANGES_REQUESTED.
   - Overseer routing cannot use the signal.
2. **Worker routing over-counts it (#1662).** `bin/hos-cron:1225-1228` counts CHANGES_REQUESTED reviews
   across the PR's whole review history and returns `needs-fix` for as long as the count is above
   zero. The worker prompt tells the worker to "fix the listed gaps, push, then STOP". When nothing is
   left to fix, the worker pushes nothing, the routing inputs stay the same, and the same directive
   repeats every cycle. That blocks the whole `needs-ai` queue. There are two live shapes:
   - **#1658 (supersession).** The same human requested changes, then later APPROVED the new head.
     GitHub's effective state is APPROVED. Routing still says `needs-fix`.
   - **#1727 (addressed, human not back).** The human requested changes ("Correct lint failure").
     The worker pushed a fix (`7374beef`). The human has not reviewed again. GitHub's effective state
     is still CHANGES_REQUESTED, so the "latest review per reviewer" fix suggested in #1662 does
     **not** clear it. This is the ordinary lifecycle of a requested change, and it is likely the more
     common of the two shapes.

The #1727 comment on #1662 shows that the routing is answering two different questions with one
signal:
- "Does the worker have something to fix?"
- "Is this PR waiting on a human?"

Merge authority asks a third question: "Has the human withdrawn their objection?" These requirements
give each question its own answer, built from one shared definition of the review state.

## Definitions (binding for every requirement below)

- **Review list.** The PR's complete review history from `GET /pulls/{n}/reviews`, across every page.
  A read is **complete** only when every page was fetched and parsed. A failed fetch, an unparseable
  page, or a list that may be truncated (for example a full last page with no further page fetched)
  is **unknown**, never "no reviews".
- **State-bearing review.** A review whose `state` is `APPROVED`, `CHANGES_REQUESTED` or `DISMISSED`.
  A `COMMENTED` (or `PENDING`) review does **not** change a reviewer's effective state. This matches
  GitHub: a plain comment review does not withdraw a request for changes.
- **Effective state (per reviewer).** For each reviewer login, the state of that reviewer's most
  recent state-bearing review, ordered by `submitted_at`. Ties and unparseable timestamps are broken
  toward CHANGES_REQUESTED (the fail-safe direction). A dismissed CHANGES_REQUESTED shows up as
  `DISMISSED` and is not outstanding.
- **Outstanding CR.** A reviewer whose effective state is CHANGES_REQUESTED. Its **CR review** is that
  most recent CHANGES_REQUESTED review, including its `id`, `commit_id`, `submitted_at`, `html_url`
  and `body`.
- **Human reviewer.** A reviewer whose login does not end in `[bot]` and whose
  `author_association` ∈ {OWNER, MEMBER, COLLABORATOR}. This is the same trust test as T3.0b §2.5
  `approved_on_head`. `HUMAN_REVIEWER` (`scripts/framework/machine-accounts.env`) always qualifies.
  See ESC-5.
- **Head-current CR.** An outstanding CR whose CR review `commit_id` equals the PR's current head SHA.
- **Acted-on CR.** An outstanding CR that is not head-current and where the worker has acted since:
  at least one commit after the CR review's `commit_id` is something other than solely a merge of the
  base branch into the PR branch. A head that moved only because of a base merge does **not** count
  as acting on the review. Whether a marker-guarded "nothing to fix" notice also counts as acting is
  ESC-4.

## Requirements

### Shared definition

- **REQ-CR-01** "Outstanding CR", "head-current" and "acted-on" MUST each have exactly one
  definition. It is the one above, implemented once, and every consumer listed here uses it: worker
  PR routing (bash or the T3.0b classifier), `decide_merge_authority()`, and
  `merge_authority.sh hold-directive`. Each consumer MUST be tested against the same fixture set, and
  for every fixture they MUST agree on the outstanding-CR set. This is what stops #1660 and #1662
  from drifting apart again (prior art: #550 was fixed on one side only).
- **REQ-CR-02** Effective state MUST be computed from the **complete** review list. If the list is
  unknown, the result MUST be "CR state unknown". It MUST NOT be "no outstanding CR", and it MUST NOT
  be computed from a partial list. A partial list can both hide a later CHANGES_REQUESTED and hide a
  later APPROVED that supersedes one.

### Worker PR routing ("the worker PR routing")

These requirements are a **behavioral contract on the worker PR routing**, wherever it lives.
Today that is `bin/hos-cron:1171-1250`. After T3.0b it is `scripts/framework/classify_worker_prs.py`.
They apply unchanged in either location (see Sequencing).

- **REQ-CR-10** A PR MUST route `needs-fix` on CR grounds **only** when it has at least one
  **head-current** outstanding CR. Any reviewer counts here, human or bot, which is today's
  reviewer scope for routing. Other `needs-fix` triggers (dirty, human-applied `needs-ai` without
  `needs-human`) and `needs-fix-bounce`, together with their precedence, are unchanged.
- **REQ-CR-11** A CHANGES_REQUESTED review that is no longer outstanding MUST NOT cause `needs-fix`.
  That covers a review superseded by a later APPROVED or another state-bearing review from the same
  reviewer, and a review that has been dismissed. Fixes #1658.
- **REQ-CR-12** A PR whose only CR grounds are **acted-on** outstanding CRs MUST NOT route `needs-fix`.
  It MUST route to a "waiting on a human" outcome. The cycle context and the directive text MUST:
  - name the PR, the reviewer, and the CR review URL;
  - state that the worker has pushed since the review and the PR is awaiting that reviewer's
    re-review or dismissal;
  - prescribe no fix.

  It MUST NOT print "not yet reviewed" (the #1847 wording). Fixes #1727. Whether this outcome blocks
  new work, and how it counts under the ARCH-ESC-1 bound, is ESC-2.
- **REQ-CR-13** An outstanding CR that is neither head-current nor acted-on MUST route `needs-fix`.
  This is the case where the head moved only because of a base merge. Moving the head without
  addressing the review must not clear the review.
- **REQ-CR-14** Fail-closed. If the CR state is unknown (REQ-CR-02), the PR MUST resolve to a class
  that blocks new work. It MUST NOT resolve to `awaiting-merge`, `none`, human-pending, or any other
  outcome that allows new work. The cycle context MUST name the cause ("reviews unreadable"). It MUST
  NOT present the PR as unreviewed, and it MUST NOT invent a fix. The routing MUST NOT keep today's
  `|| echo "0"` behaviour, where a failed reviews read counts as zero CRs.
- **REQ-CR-15** Every routing decision made on CR grounds MUST be auditable. The `_audit` event, or
  the classifier's equivalent output, MUST record the PR, the outstanding-CR reviewers, each CR's
  review id and `commit_id`, the head SHA, and which branch was taken: head-current, acted-on,
  superseded, or unknown.

### "needs-fix" with nothing actionable (#1662 ask)

- **REQ-CR-20** If a worker cycle acts on a `needs-fix` routing for a PR and finds no actionable gap,
  it MUST post one visibility notice on that PR. The notice names the CR review(s) and the evidence
  checked, and says nothing was pushed. It MUST be marker-guarded so it posts at most once per
  (PR, CR review id, head SHA). The precedent is the `<!-- hos-worker-merge-block -->` notice in
  `bootstrap/worker-cron-prompt.md` Step 1. A new CR review or a new head re-arms the marker.
- **REQ-CR-21** After REQ-CR-20's notice, the routing MUST NOT keep prescribing the same no-op fix
  forever. Whether the notice counts as "acted-on", which moves the PR to the waiting-on-a-human
  outcome of REQ-CR-12, is ESC-4. Under any ruling, a `needs-fix` that cannot change state on its own
  MUST be visible to a human within one cycle (the notice) and MUST NOT be silent.

### Merge authority (#1660)

- **REQ-CR-30** `decide_merge_authority()` MUST receive the outstanding-CR determination for the PR
  and MUST return HUMAN_REQUIRED while any **human reviewer** has an outstanding CR. This guard is
  evaluated ahead of the worker/verdict guards, in the same position as the #902 hold. It MUST NOT be
  cleared by any of the following (conservative default, ESC-1 and ESC-3):
  - a later push, i.e. commit-staleness;
  - an overseer or worker judgement that the findings are fixed;
  - an APPROVED review from a *different* reviewer.

  It clears only when the human's effective state stops being CHANGES_REQUESTED: that human reviews
  again, or the review is dismissed.
- **REQ-CR-31** The existing #757 rule is unchanged: every merge needs a verified human APPROVED on
  the current head SHA (`_find_human_approval`, which rejects stale approvals). REQ-CR-30 adds a hold
  on top of #757. It never replaces #757 and never relaxes it.
- **REQ-CR-32** Fail-closed. If the CR state is unknown, `decide_merge_authority()` MUST NOT treat the
  PR as having no hold. The reason MUST say the review state was unreadable. A caller that passes no
  reviews, or `reviews=None`, which today defaults to `[]` at `:551`, MUST NOT be read as "reviews
  read, no CR". The architect decides how "not supplied" is told apart from "read and empty". The
  required outcome is that an unread review list can never produce AUTO_MERGE or an overseer APPROVE.
- **REQ-CR-33** The HUMAN_REQUIRED reason and the audit record MUST say that the cause is an outstanding
  CHANGES_REQUESTED, giving the reviewer, review URL, CR `commit_id`, and whether it is head-current.
  This keeps the case distinct from "awaiting human approval" (no human review yet).
- **REQ-CR-34** When REQ-CR-30 fires and the overseer App has a standing APPROVED review on the PR, the
  overseer MUST dismiss its own approval. This is the same #902 step 6(3) behaviour that a
  comment-based hold triggers today. The overseer MUST NOT dismiss, or ask anyone to dismiss, the
  human's CHANGES_REQUESTED review.
- **REQ-CR-35** The comment-based #902 hold (`detect_human_hold_directive` over issue comments,
  supersede-on-push) is unchanged by this issue. The CR signal is an additional input. It does not
  replace the comment scan.

### Primitive output

- **REQ-CR-40** `bootstrap/merge_authority.sh hold-directive` JSON MUST report, separately from the
  comment-scan fields that exist today:
  - whether a CR hold is active;
  - the outstanding-CR reviewer(s), review id/URL, `commit_id`, and head-current flag;
  - a count of the reviews scanned;
  - a review-read status (ok / unknown);
  - which signal or signals set `hold_active`.

  `hold_active` MUST be true if either signal fires, and MUST NOT be false when the review state is
  unknown. Existing field names keep their meaning. Additions only.

### Tests (acceptance)

- **REQ-CR-50** Shared fixtures, run through every consumer (REQ-CR-01), MUST cover:
  - **(a)** the #1658 shape, CR then APPROVED by the same reviewer on a later head. Routing: no
    `needs-fix`. Merge authority: no CR hold, and #757 applies normally.
  - **(b)** the #1727 shape, CR on an old commit, a non-merge worker commit since, no later review.
    Routing: waiting-on-human and not `needs-fix`. Merge authority: HUMAN_REQUIRED with the CR reason.
  - **(c)** CR on the current head. Routing: `needs-fix`. Merge authority: HUMAN_REQUIRED.
  - **(d)** CR, then the head moves only by a base merge. Routing: `needs-fix` (REQ-CR-13).
  - **(e)** CR, then a COMMENTED review from the same reviewer. The CR is still outstanding.
  - **(f)** CR, then dismissed. Not outstanding.
  - **(g)** CR from reviewer A and APPROVED from reviewer B. A's CR is still outstanding.
  - **(h)** a reviews read failure, an unparseable page, and a truncated or full-page list. Routing:
    blocking class. Merge authority: never AUTO_MERGE or APPROVE. Primitive: `hold_active` not false.
  - **(i)** a CR whose later superseding APPROVED is on page 2. It is resolved only with page 2 read.
  - **(j)** a bot-authored CR. Routing per REQ-CR-10. Merge authority per the ESC-5 ruling.
- **REQ-CR-51** Regression: `decide_merge_authority()` with an outstanding human CR and the overseer
  holding an APPROVED review results in the dismissal path being taken (REQ-CR-34).
- **REQ-CR-52** Regression: the REQ-CR-20 notice posts once across two consecutive cycles on an
  unchanged (PR, CR id, head), and again after a new CR review.
- **REQ-CR-53** The existing routing precedence tests (#867 dirty, #1350 bounce, #1522/#1526
  `needs-ai`) and the T3.0b fixtures C2–C4, C7 and C10–C11 still pass unchanged. C5, T-FC10 and any
  "any CR ⇒ needs-fix" fixture are revised to REQ-CR-10..14. The revision is listed explicitly in the
  PR. It is never a silent fixture edit.

## Sequencing and the T3.0b coordination requirement

- **REQ-CR-60** The PR routing has to have one owner. T3.0b
  (`TECHNICAL-DESIGN-1644-T3.0b-pr-classifier.md`, ADR-1644, REQUIREMENTS-1644-AMENDMENT-2) moves it
  into `scripts/framework/classify_worker_prs.py`. T3.0b deliberately keeps today's CR semantics:
  - §2.5 "R": CR is true iff any review is CHANGES_REQUESTED;
  - a full page containing a CR counts as a determination;
  - a read failure gives CR = false;
  - Amendment-2 REQ-C24 item 1 says "`CHANGES_REQUESTED` > 0 … unchanged".

  T3.0b coding is human-gated (ARCH-ESC-1R). Whichever change lands second MUST carry REQ-CR-10..15
  forward, so the system never runs two CR definitions at once:
  - **If this lands first, in bash:** before T3.0b codes, T3.0b's §2.5 R, the §2.6 C5/C6 rows, the
    "full page with a CR is a determination" rule (no longer valid, because a later page can supersede
    it), the `|| echo 0` fallback, fixtures C5 and T-FC10, and Amendment-2 REQ-C24 item 1 MUST be
    revised to this contract. The behaviour-preservation equivalence tests MUST preserve the new
    behaviour, not the old.
  - **If T3.0b lands first:** this contract is implemented in the classifier. It is not re-added to
    `bin/hos-cron`.
  - Either way, changing REQ-C24 item 1 changes an approved requirement. This document's structural
    classification covers that change, and the human's ruling on ESC-1/ESC-2 is the approval for it.
- **REQ-CR-61** If routing ships before the merge-authority half, or the other way round, the half
  that ships first MUST NOT create a new unsafe state:
  - Routing alone moves #1727-shape PRs to waiting-on-human. Merge is still held by #757 and branch
    protection, so this is safe.
  - Merge authority alone only adds holds, so it is safe too.

  Splitting into slices is the architect's call.

## Non-goals

- Changing #757, `_find_human_approval`, `OVERSEER_CEILING`, the protected-surface rules, or the
  #902 comment-scan regex and its supersede-on-push rule.
- The pipeline dismissing, or auto-requesting dismissal of, a human's review.
- Fixing #1847 ("not yet reviewed" on HUMAN_REQUIRED PRs) beyond REQ-CR-12's own wording.
- Changing GitHub branch protection settings.

## Escalations (human decisions required)

Each ESC lists the recommended default that design proceeds under.

- **ESC-1 — Does a later review from the same reviewer clear a CHANGES_REQUESTED?** (policy question
  (a) in both issues)
  **Recommended: yes, for every consumer.** The definition is the effective state: the latest
  state-bearing review from that reviewer, with COMMENTED not counted. In that case the human has
  spoken again. This is GitHub's own semantics, and `require-human-approval` was already green on
  #1658. The design builds on this default. The open choice is whether a later COMMENTED review from
  the same human should also supersede. The recommendation is no: it does not supersede on GitHub,
  and treating it as superseding would loosen the hold.
- **ESC-2 — Does commit-staleness clear a CHANGES_REQUESTED, and for which consumer?** (policy
  question (b))
  **Recommended:**
  - **Worker routing:** an acted-on CR is no longer "worker, go fix something". It becomes "waiting on
    a human" (REQ-CR-12). This is not a dismissal. It only stops the false fix instruction. Merging is
    still blocked by #757 and branch protection, so nothing merges as a result (the #1727 comment's
    asymmetry argument).
  - **Merge authority:** commit-staleness never clears the CR (REQ-CR-30).

  The sub-question is how a waiting-on-human-for-CR PR counts toward new-work blocking. The
  recommendation is to treat the positively read outstanding human CR as a **human-pending carrier**
  under ARCH-ESC-1, so it counts toward bound B = 3. It is a positive read, not unknown state, and it
  is exactly "reviewed and awaiting a human". This adds a carrier to the #1912 ruling, so it needs the
  human's approval. Under bash routing before T3.0b, the conservative alternative is today's
  `needs-attention` block with the corrected wording from REQ-CR-12. That still ends the livelock's
  false fix instruction, but it keeps the queue blocked.
  Also confirm the "acted-on" proxy: a non-merge commit after the CR's `commit_id`. That proxy cannot
  tell whether the commit actually addresses the review. The recommendation is to accept it. The
  human's re-review is the real check, and merging stays held.
- **ESC-3 — Does a CHANGES_REQUESTED whose findings are demonstrably fixed still hold merge?** (policy
  question (c), raised by #1660 on #1658)
  **Recommended: yes.** Dismissing or re-reviewing is the human's decision, not the pipeline's. The
  overseer may say in its verdict that the findings appear fixed, but it does not clear the hold
  (REQ-CR-30, REQ-CR-34). This matches GitHub, where a new push does not dismiss a
  CHANGES_REQUESTED. It also matches the overseer's own correct restraint on #1727 at
  2026-09-18T17:57Z.
- **ESC-4 — Does the "nothing to fix" notice count as the worker acting?** (policy question (d))
  **Recommended: yes.** After the marker-guarded notice (REQ-CR-20) on a head-current CR, the PR is
  routed as waiting-on-a-human (REQ-CR-12) until the human reviews again or a new CR or head arrives.
  If the answer is no, the notice is visibility only, and a head-current CR with nothing fixable keeps
  the worker on `needs-fix` until a human intervenes. That fixes the silence but leaves the livelock.
- **ESC-5 — Whose CHANGES_REQUESTED holds merge?**
  **Recommended:** any human reviewer, as defined above (trusted association, not a bot), and not
  only `HUMAN_REVIEWER`. That is broader than #902's comment scan, so it is stricter. A bot-authored
  CHANGES_REQUESTED still routes the worker to `needs-fix` (REQ-CR-10), but it adds no merge-authority
  hold beyond the existing verdict guards. The overseer never posts CHANGES_REQUESTED today
  (`post_review_thread.sh` always uses COMMENT, and `pr_review.sh submit-verdict` uses approve or
  comment).
- **ESC-6 — Amending the approved REQUIREMENTS-1644-AMENDMENT-2 REQ-C24 item 1 and T3.0b §2.5.**
  Approving ESC-1/ESC-2 implies changing a requirement that the #1912 ruling's amendment wrote down as
  "unchanged". The human is asked to approve that change explicitly, and to say whether it should
  land as a T3.0b revision (preferred: one implementation) or as a bash change ahead of T3.0b.

## Not determined here

- I did not check whether repository branch protection has "require review from code owners" or
  "dismiss stale reviews" settings that change GitHub's treatment of CHANGES_REQUESTED. The architect
  should confirm the claim "GitHub keeps a CHANGES_REQUESTED after a push" against
  `setup_branch_protection.sh` and the live settings.
- How to detect "solely a base merge" reliably (for example from commit parents, or from the commits
  list) is a design question.
- I did not check whether PRs #1658 and #1727 are still open, or what state they are in now. They are
  used here only as historical fixtures.
