# ADR-1657 — The overseer's verdict artifact, and the scoped reviewer request

**Status:** ACCEPTED — **binding on `technical-design` and `coder`.**
`docs/v0.7.0/TECHNICAL-DESIGN-1657-overseer-review-objects.md` is **CLEARED FOR THE CODER subject to
the eleven binding conditions ARCH-1 … ARCH-11 in §3.** No further `technical-design` iteration is
required; the conditions are mechanical applications of rules the design already owns, and
`code-reviewer` must verify each before sign-off.
**Author:** `architect`
**Date:** 2026-09-23
**Iteration:** 1 of 5 (CORE cap) — resolved in round 1; no loop temp-state carried.
**Issue:** #1657 (`bug`, `process-gap`, `priority:critical`, milestone `v0.7.0`)
**Binding inputs:** the human ruling of 2026-09-14 recorded in #1657 (the spec — not re-litigated
anywhere below); the human ruling of 2026-09-11 on #1357 ESC-1; `docs/PR-SIZE-POLICY.md`;
`docs/v0.7.0/ADR-1357-merge-authority-execution.md`.
**Cross-ADR consequence:** `docs/v0.7.0/ADR-1357-AMENDMENT-1-pr-review-primitive.md` (the forward
constraint this ADR places on #1357 build slice 4, recorded where slice 4's implementer will read it).

---

## 0. What this ADR decides, and what it does not

The human's 2026-09-14 ruling settled the **product** question — may the overseer record an `APPROVE`
verdict on a protected-surface PR, and when is a human requested as reviewer. That question is closed
and this ADR does not re-open it, including its load-bearing scoping (a human reviewer is requested
only when tier exceeds `OVERSEER_CEILING`, on the existing CRITICAL path, or when the PR touches
`scripts/framework/protected_surfaces.txt`).

This ADR decides the **architecture** questions the ruling left open, which `technical-design`
correctly routed rather than absorbed: slice ownership, the event enum, the trigger-set boundary, the
canonical CODEOWNERS module, the scope seam around VP-10, and the PR shape. Every ruling below is
final and binding on the technical side. Where a ruling carried a product consequence, §4 records the
product-boundary checkpoint and its disposition.

---

## 1. Rulings

### AD-1 — A1: **#1657 PROCEEDS NOW.** It is not blocked, and the premise that blocked it is false.

**The design's premise is factually wrong, and the error is in the design's favour but must still be
corrected on the record.** TD-1657 §12 A1 states that ADR-1357 slice 4 is *"blocked on ESC-1, a human
escalation with no recorded answer."* ESC-1 **was answered by the human on 2026-09-11** (#1357 comment
`2026-09-11T06:47:52Z`), and a second comment two minutes later closes all three: *"All three
architect escalations are now resolved: ESC-1 … ESC-2 (moot) … ESC-3 (no retrospective audit). #1357
has no remaining open escalations blocking build."* `docs/v0.7.0/TECHNICAL-DESIGN-1357-merge-authority-primitives.md:48`
already records this (*"ACCEPTED; ESC-1/2/3 resolved by human ruling in #1357's comment thread"*).
ADR-1357 §4's slice-4 row still reads *"Blocked on ESC-1"* — **that row is stale text, not a live
block.** It is corrected in `ADR-1357-AMENDMENT-1`.

**What ESC-1 actually asked, and what it gates.** ESC-1 asked whether `merge_permitted` includes an
above-ceiling, human-approved **merge** path — options (a) a `HUMAN_APPROVED_ABOVE_CEILING`
authorization computed inside the decision layer, or (b) above-ceiling PRs are merged by the human.
Its subject is *who may execute a merge*. Its resolution: above ceiling, a verified CODEOWNER
`APPROVE` becomes a required **additional** gate layered on top of the overseer's own required review,
and once both are satisfied the merge is automatic. So ESC-1 gated **only the merge half of AD-7** —
never the review-posting half, and never a review primitive.

**What actually gates slice 4 today** is **ESC-4** (four of `decide_merge_authority`'s inputs —
`oversight_verdict`, the sign-off register, `bounce_count`, `risk_tier` — have no cross-clone
transport) and **ESC-5** (whether the SPEC-303b CODEOWNERS gate gets a clearing path). Both are open.
Neither touches #1657: both concern `decide_merge_authority`'s **fresh recompute** and the **merge**
row of the matrix. `bootstrap/pr_review.sh` performs no recompute, computes no disposition, consumes
none of the four un-transported inputs (it takes `--tier` as a caller-supplied input, mechanically
re-checked only against the ceiling), and merges nothing.

**The affirmative argument, which is stronger than the absence of a block.** ESC-1's own resolution
says, verbatim: *"**The overseer is always a required approver, at every tier**; codeowner approval
above ceiling is additive, not a substitute."* That rule is **unimplementable today** — the overseer
records no review object, so "the overseer's own required review" cannot be satisfied or even
observed. #1657 is therefore a **prerequisite of the human's ESC-1 ruling**, not a competitor to slice
4. Landing it is what makes ESC-1's rule reachable.

**RULING: proceed.** Landing `bootstrap/pr_review.sh` + `scripts/automation/pr_review_cli.py` now is
an **authorised early landing of a slice-4-adjacent surface**, not a slice violation. The `priority:critical`
unsatisfiable gate is a supporting reason, not the reason — the reason is that ESC-1 is resolved, the
live gates (ESC-4/ESC-5) are disjoint from this surface, and ESC-1's own text depends on this primitive
existing.

**The forward constraint slice 4 inherits — exact text, binding:**

> **FC-1.** `overseer_merge.sh` and `overseer_escalate.sh` **must not** issue
> `POST /repos/{o}/{r}/pulls/{n}/reviews` or `POST /repos/{o}/{r}/pulls/{n}/requested_reviewers`
> themselves. Their approve/comment and reviewer-request legs **must** be performed by calling
> `scripts/automation/pr_review_cli.py`'s functions in-process (preferred) or by invoking
> `bootstrap/pr_review.sh`. One invocation site per authority (D41). AD-7's atomicity is preserved
> exactly: AD-7 requires that the *agent* issues one command, and an in-process call to the primitive
> is internal to that one command. A second implementation of either POST is a defect, not an
> optimisation, and `code-reviewer` must reject it.
>
> **FC-2.** Slice 4 **must not** re-derive the reviewer login, the trigger predicate, the
> above-ceiling refusal, or the self-authored refusal. Those are `pr_review_cli`'s, and AD-5's fresh
> recompute governs the *merge authorization*, not these.

**Where FC-1/FC-2 are recorded:** `docs/v0.7.0/ADR-1357-AMENDMENT-1-pr-review-primitive.md`, which
amends ADR-1357 and is the document slice 4's `technical-design` reads. Recording a forward constraint
only inside another issue's design doc guarantees it is never read; that is why it gets its own
amendment file rather than a paragraph here.

---

### AD-2 — A2: **CONFIRMED.** The event enum is `{APPROVE, COMMENT}`. `REQUEST_CHANGES` is excluded.

TD-1657 §3.1's reading is upheld, and I add the decisive ground the design did not state:

1. **On the above-ceiling path the overseer can never clear its own change request.** Guard G1
   refuses `--event approve` when tier exceeds `OVERSEER_CEILING` (mechanising `overseer.md:54`, one
   of the four NEVER entries #1657 leaves untouched). A `CHANGES_REQUESTED` posted there is clearable
   only by a human dismissal — there is **no autonomous clearing actor**. That is a permanent,
   human-only-clearable block created by a bot, on exactly the PR class that is already the most
   human-expensive. This is not a hypothetical: the operator record already carries *"Stale
   CHANGES_REQUESTED blocks cycles."*
2. **It would add a blocking authority the ruling says is unchanged.** The ruling states *"Merge
   authority is unchanged — it stays with the human gate, the CODEOWNERS gate, and the tier matrix."*
   A bot `CHANGES_REQUESTED` is a fourth, new, bot-held block on merge. Adding it inside a change
   whose spec says merge authority is unchanged is out of bounds regardless of its merits.
3. **The blocking job is already done, by a control with a working clearing path.**
   `post_review_thread.sh` + `required_conversation_resolution` (#1207) blocks and clears on
   resolution. Two blockers for one job, with different clearing protocols, is a deadlock class for
   zero additional gate coverage.
4. `dismiss_stale_reviews_on_push` dismisses **approvals**, not change requests, so a push does not
   release it either.

**Binding:** the enum is **closed**. `--event request_changes` is rejected at argument-parsing time
(exit 2) with a message naming `bootstrap/post_review_thread.sh`. Adding any third value requires a
new architect ruling **and** a specified dismissal protocol with a named non-human clearing actor.
Pinned by test **W5**.

---

### AD-3 — A3: **CONFIRMED — do not widen the trigger set.** With one additive disclosure requirement.

TD-1657's reading is upheld, on grounds stronger than the ones it gave:

1. **In this repo the third trigger is the empty set.** `.github/CODEOWNERS` is *generated from*
   `scripts/framework/protected_surfaces.txt` by `gen_codeowners.sh` (VP-4). So
   {CODEOWNERS-human-owned} ≡ {protected surface}, exactly. The class "CODEOWNERS-owned but not on
   `protected_surfaces.txt`" **has no members here**. Adding the term would be a literal no-op that
   nonetheless widens a predicate the ruling pins — the worst of both.
2. **In a consumer install the class is non-empty, and it is covered by a better control.** GitHub's
   `require_code_owner_review` auto-requests the code owner on open and on synchronize — server-side,
   synchronously, with no cron cycle in the path. An agent-loop request is strictly weaker.
3. **If that server-side control is absent, the gate still holds; only the nudge is missing.**
   `scripts/oversight/codeowners.py`'s SPEC-303b check still forces `HUMAN_REQUIRED` in the decision
   matrix and still applies `needs-human`. The reviewer request is a *queueing/notification*
   mechanism, not the gate. Losing a nudge is not losing a gate, and the ruling's anti-widening
   constraint outranks a nudge.
4. The ruling names widening as **the** failure mode and cites the calibration evidence
   (`research/sessions/2026-08-04-controls-that-never-fire.md`). The bar is high and this does not
   clear it.

**ARCH-3 (binding, additive — this is not a widening).** When `request-reviewer` refuses with
`no_qualifying_trigger`, the exit-3 payload must additionally carry
`codeowners_human_owned: true|false`, computed by calling `scripts/oversight/codeowners.py`'s
`check_pr_files` over the changed files. No write, no behaviour change, no new trigger — it records in
the artifact the one case the ruling did not name, so a future recalibration is a **measurement**
rather than a guess, and so "we deliberately did not request here" is visible rather than silent. If
that call raises or CODEOWNERS is absent, record `null` and add a `not_verified[]` entry; never
escalate it to a trigger and never fail the refusal on it.

---

### AD-4 — Canonical CODEOWNERS module: **`scripts/oversight/codeowners.py`. My earlier suggestion is overruled — the design is right.**

I record this as an overruled architect suggestion rather than quietly adopting it, because a design
that correctly refuses an architect's suggestion should be seen to have done so.

Verified grounds:

1. **Trust direction.** `scripts/automation/lib/codeowners.py`'s own docstring: over-match →
   *"unearned authorization — dangerous"*. `scripts/oversight/codeowners.py`: over-match →
   *"HUMAN_REQUIRED — safe"*. "Who must be asked to look at this" is a conservative-direction
   question. Using the dangerous-direction matcher would fail in the direction of *not* asking.
2. **It carries a standing product-boundary checkpoint.** Its docstring: *"Any future wiring into a
   live authorization path requires a product-boundary checkpoint (architect ruling on #559)."*
   Wiring it here would trip that checkpoint for zero benefit.
3. **The divergence is deliberate and test-pinned.** Its docstring forbids cross-import (*"that
   inverts the trust direction"*) and names KNOWN-DIVERGENCE rows in
   `tests/automation/test_phase_b.py`. Unifying them as a side effect of #1657 would break pinned
   tests that exist to record the divergence.
4. **The oversight module is already the live one on this side of the boundary** — verified at
   `scripts/automation/merge_authority_cli.py:659-665` (`_load_codeowners_module` loads
   `scripts/oversight/codeowners.py` by file path) and at `_cmd_codeowners:696` (`check_pr_files`).
   One more consumer of the live module is **consolidation, not proliferation**.
5. **Decisive.** The human's ESC-1 ruling explicitly flagged the two-module divergence as a dependency
   that must resolve *"to one authoritative source before or alongside this build."* #1657 picks the
   source that is already authoritative on the overseer/merge side. Picking the other one would push
   against the direction that human ruling points.

**On "two parsers in one repo is a smell": yes, and it is a filed, owned smell, not an unowned one.**
It is already named by #559, by #1542 VF-3/Q7, and by the human in ESC-1. **ARCH-4 (binding):** the
worker files **one** follow-up issue — *"two CODEOWNERS parsers with opposite fail directions: name
one authoritative for authorization decisions"* — `priority:medium`, milestone `v0.7.0`, linking #559,
#1357 (ESC-1), #1542, #1657, #1816, and stating the constraint that any consolidation must preserve
the conservative fail direction for gate/reviewer decisions and must clear #559's product-boundary
checkpoint before the automation-side module is wired to any authorization path. **It is not a blocker
for #1657** and must not be bundled into it. `scripts/automation/lib/codeowners.py` stays untouched by
#1657 (TD-1657 §9 item 7 — confirmed binding).

---

### AD-5 — VP-10: **SPLIT, on a precise seam. The design's in-scope repair is half right, and the other half is a behaviour change the ruling forbids.**

VP-10 is verified and worse than stated. `overseer.md:331-340` (#761 `prior_overseer_decision`) and
`:376-390` (#1215 precheck) both scan `GET /issues/{n}/comments` for `**Decision: HUMAN_REQUIRED**`.
`overseer.md:408` routes the §8.2 escalation — the artifact §8.2 requires to carry that header on
*every* HUMAN_REQUIRED — to `post_review_thread.sh`, which posts it into a **review thread comment**
(`addPullRequestReviewThread` → the body lands on `/pulls/{n}/comments`; the containing review's own
`body` is empty). So the marker is on a **third** surface, and both scans match nothing today. The
design's proposed union (`/issues/{n}/comments` ∪ `/pulls/{n}/reviews`) does not cover the thread
surface either.

**AD-5a — the #1215 duplicate-verdict precheck: IN SCOPE, with a hard boundary.** This design
deliberately relocates the canonical marker into the verdict review body. Leaving a consumer reading a
surface the producer no longer writes, *in the same PR that moves the producer*, is committing the
#1207/#1657 defect a third time knowingly. That is not deferrable. Repair it as §6.4 describes.

> **ARCH-5 (binding).** The #1215 precheck **must not govern the verdict review.** Deduplication of
> the verdict review is owned solely by wrapper guard **G4** (byte-identical body, same head SHA).
> Two dedup authorities with different predicates — "latest marker is mine" vs. "body is byte-identical"
> — will suppress a verdict whose content **changed**, which is suppression of new information. Strike
> the clause *"Posting the verdict body … is subject to the §1215 duplicate-verdict precheck"* from
> the `:407` and `:408` replacements. The precheck governs the escalation thread and the narrative
> comment only. One artifact, one dedup authority.

> **ARCH-6 (binding).** The canonical `**Decision: HUMAN_REQUIRED**` header must appear in the verdict
> review body on **every** HUMAN_REQUIRED disposition, unconditionally. §3.4's *"(where applicable)"*
> is struck: the #761/#1215 consumers key on that exact string, and a conditional producer is how this
> class of defect is built. Pinned by a test in the wrapper suite.

**AD-5b — reviving the #761 `prior_overseer_decision` guard: OUT OF SCOPE. Split to its own issue.**

This is the finding TD-1657 missed, and it is the reason the split seam is where it is.
`merge_authority.py:569-580` reads: if `prior_overseer_decision == "HUMAN_REQUIRED"` and there is no
verified human approval **on the current head SHA**, return `HUMAN_REQUIRED` and label `needs-human`.
The guard is **dead today** (its scan matches nothing). Wiring the scan to a surface the marker
actually occupies **revives it**, and revival is a behaviour change:

> A LOW-tier, non-protected PR that recorded `HUMAN_REQUIRED` on any earlier cycle — e.g. because the
> oversight verdict was `CONDITIONAL`/`ESCALATE` — would, after the worker fixes it and pushes,
> require a **human approval on the new head SHA** to merge. There is no other clearing path: a worker
> push creates a new head, and no human approval exists on it. Today that PR auto-merges.

That is (i) a new human gate on the LOW/MEDIUM non-protected path, which #1657's third acceptance
criterion pins as *"byte-for-byte unchanged"*; (ii) a widening of human-attention demand, the exact
calibration failure the ruling forbids; and (iii) a throughput/human-obligation change of precisely
ESC-5's class, which means it carries a **product-boundary checkpoint** that #1657's 2026-09-14 ruling
does not cover.

> **ARCH-7 (binding).** Leave the `prior_overseer_decision` derivation at `:331-340` reading
> `/issues/{n}/comments` only — i.e. dead, exactly as today. **Status quo is not a regression.** The
> new *"§ Where your own prior decision is recorded"* subsection must state, in the file, that the
> #761 derivation is **knowingly not wired to it**, name the follow-up issue, and say why (reviving it
> changes merge dispositions on the LOW/MEDIUM non-protected path and needs a product-boundary
> checkpoint). A documented inconsistency is auditable; an undocumented one is the next VP-10.
>
> **ARCH-8 (binding).** File the follow-up: *"the #761 prior-decision guard is dead, and reviving it
> needs a clearing path"* — `priority:high`, `needs-human`, milestone `v0.7.0`, linking #761, #1207,
> #1657, #1357 (ESC-5), #1816. It must state the two questions the human has to answer: (1) should the
> guard be revived at all, given it adds a human gate to the LOW/MEDIUM non-protected path; (2) if
> yes, what clears it — a marker scoped to the head SHA it was written against, a clean recompute
> after a worker push, or human approval only. Note the direct parallel to ESC-5's clearing-path
> question and recommend that whoever settles ESC-5 and #1816 settles this the same way.

TD-1657 §9 claim 1 and §11's VP-10 row must both be corrected to match AD-5a/AD-5b: as written, §9
claim 1 ("byte-for-byte unchanged") would have been **false** for the design as submitted. That
correction is the single most important edit this ruling requires.

**On "a half-repaired scan could be worse than an unrepaired one":** the concern is right in general
and does not apply here, because the two scans have different contracts and each is correct for its
own after the split — the #1215 precheck reads the surface its producer now writes; the #761
derivation reads the surface it always read and stays as dead as it is today. Nothing becomes
*partially* true. ARCH-7's in-file note is what keeps it that way.

---

### AD-6 — Finding 1 (the merge livelock): **VERIFIED REAL. Guard I2 is the right fix and is sufficient, with three refinements.**

Verified against the code, not the design's account:

- `merge_authority.py:585-593` — `if requested_reviewers: if any(r.lower() == human_reviewer.lower() …): return HUMAN_REQUIRED` with `labels_to_add=["needs-human"]`. **Unconditional.** It does not consult `reviews` at all.
- The first `_find_human_approval` call on the merge path is at **:658** (security-relevant branch), with further calls at `:679` and `:717`. All are **after** :585. The gate at :569-580 also calls it, but only inside the `prior_overseer_decision` branch, which is dead (AD-5b).
- `POST /pulls/{n}/requested_reviewers` for a user who has already submitted a review is GitHub's *re-request review* operation: it re-adds that login to `requested_reviewers`.

So the livelock is real and its shape is exactly as described: human approves (GitHub removes them from
`requested_reviewers`) → next cycle the overseer re-requests → `requested_reviewers` contains
`human_reviewer` again → `decide_merge_authority` returns `HUMAN_REQUIRED` at :585 without ever
looking at the approval sitting on the PR → repeat forever. Note that **I1 alone cannot catch it**:
after the human reviews, they are *not* in `requested_reviewers`, so I1 does not fire. I2 is load-bearing,
not an optimisation. The existing prose at `overseer.md:407` (*"idempotent … so run it every cycle"*)
is true only for the pending case and false for the reviewed case — the design's reading is correct.

I2 is also **sufficient**, and I checked the state machine rather than assuming: after the human
reviews head *X*, I2 skips, `requested_reviewers` stays empty, :585 passes, and the approval is found
downstream. On a worker push head becomes *Y*, the human's review `commit_id` is *X*, I2 does not fire,
the request is made — which is correct, because the new head genuinely needs fresh human review. A
human `COMMENTED`-but-not-approved review on head also suppresses the request; that costs a
notification, never a gate, and the human demonstrably already has that head in view.

> **ARCH-9 (binding).** The I2 predicate is *"the resolved login has **any** review (any state) whose
> `commit_id` equals `head.sha`"*. Test **W12** as drafted exercises only `APPROVED`; it must cover
> `APPROVED` **and** `COMMENTED` so the table and the test state the same predicate.
>
> **ARCH-10 (binding).** `head.sha` for I2 must be the value read once in the §4.2 shared preamble —
> the same value `submit-verdict` pins into `commit_id`. Never re-fetched, never derived twice.
>
> **ARCH-11 (binding).** I2's code comment and W12's docstring must state the *reason* behaviourally —
> *"`decide_merge_authority` returns HUMAN_REQUIRED on an outstanding request from `human_reviewer`
> before it checks for any human approval, so a re-request after approval flips an approved PR back to
> HUMAN_REQUIRED every cycle"* — and must **not** cite `merge_authority.py:585-596` by line number.
> Line numbers rot; the behaviour does not.

**Recorded, not fixed here:** the root fragility is that :585 has no *"unless a verified human
approval exists on the current head"* escape. I2 makes the overseer stop tripping it; it does not make
the gate robust against any other actor re-requesting. Fixing :585 means editing
`decide_merge_authority`, which TD-1657 §9 item 3 correctly holds untouched and which belongs to
#1357. Routed to `ADR-1357-AMENDMENT-1` §3 as an observation for slice 4 / ESC-5, not to #1657.

---

### AD-7 — A4 (the ARCH-3a deviation): **CONFIRMED.**

`bootstrap/pr_review.sh` may refuse in `HOS_COMMENT_FORMAT_MODE=enforce` via
`bootstrap/lib/comment_format_check.sh`. Forking the #1270 format contract into Python to satisfy
ARCH-3a would defeat that validator's entire purpose — that the write paths **cannot** drift apart —
and would create a second format authority, which is the #1135 class. One bash implementation with a
third caller is correct. **Binding:** the invocation must be byte-identical in shape to
`post_comment.sh:79-86` and `post_review_thread.sh:103-112`. No new mode, no new default, no
`pr_review.sh`-specific branch inside the shared check. Recorded as a named deviation in
`ADR-1357-AMENDMENT-1` §4 so ARCH-3a's exemption list stays in one place.

### AD-8 — A3b (CODEOWNERS teams): **CONFIRMED.** Teams are not requested; the fact is surfaced in
`codeowners_team_owners[]` and `not_verified[]`, and resolution falls back to `HUMAN_REVIEWER`. The
grounds in TD-1657 §4.5 step 5 hold: a team request needs the separate `team_reviewers` field, 422s on
a non-org repo, and could never satisfy `decide_merge_authority`'s single-login comparison at :586.
The path is unreachable in this repo (VP-4) and reachable in a consumer install, so it is a real
follow-up: fold `team_reviewers` support into the **same** issue ARCH-4 files, as a named second
section — not a third issue for one adjacent fact.

### AD-9 — A5 (consumer ship-set): **CONFIRMED — deferred to TD-1357 slice 6.** Shipping one wrapper
into an install that lacks its two siblings produces a consumer `overseer.md` naming three wrappers of
which one exists; that is worse than the present, uniform gap. **Binding:** the PR description must
state, in one sentence, that `pr_review.sh` joins `post_comment.sh` and `post_review_thread.sh` as
HOS-repo-only, that this is a **pre-existing** gap (AF-5) owned by TD-1357 slice 6, and that #1657
neither creates nor closes it. A gap inherited silently becomes a gap introduced.

---

## 2. PR shape — binding

TD-1657's change set is **16 files** (2 new source, 4 modified source/prose, 4 protected-surface
prose/config, 4 test, `SCRIPTS-INDEX.md`, the design doc, plus this ADR). `docs/PR-SIZE-POLICY.md`:
*"Worker (both modes): does not open a PR that would exceed 15 files or 10 commits without first
splitting."* 16 > 15. The policy decides this; I am applying it, not adding a constraint.

> **ARCH-2 (binding) — two sequential PRs, wrappers before prose.**
>
> **PR 1 — "Part 1 of 2: the verdict primitive"** (~10 files, **nothing invokes it**):
> `bootstrap/pr_review.sh`, `scripts/automation/pr_review_cli.py`, `scripts/automation/lib/github.py`,
> `scripts/oversight/codeowners.py`, `tests/automation/test_pr_review_wrapper.py`,
> `tests/automation/test_pr_review_resolution.py`, `tests/automation/test_github.py`,
> `docs/v0.7.0/TECHNICAL-DESIGN-1657-…md`, this ADR, `ADR-1357-AMENDMENT-1`.
>
> **PR 2 — "Part 2 of 2: the overseer posts verdicts"** (~7 files): `.claude/agents/overseer.md`,
> `docs/FABERIX-ROLES.md`, `CLAUDE.md`, `bootstrap/overseer-cron-prompt.md`,
> `scripts/framework/require_overseer_approval.py` (prose only), `SCRIPTS-INDEX.md`,
> `tests/framework/test_overseer_verdict_artifact.py`.
>
> **PR 2 must not open until PR 1 has merged.** Each title states its position per the policy.

Three reasons this seam and not another:

1. **This repo's own binding precedent.** ADR-1357 §4's build order is *"wrappers before prose (the
   human's instruction)"*, with slice 6 = "Prose + ship-set" as its own PR. ADR-1340 AD-9 does the
   same and describes its PR 1 as having *"a deliberately null blast radius: nothing invokes it."*
   PR 1 here is exactly that shape.
2. **The two halves are different review disciplines.** PR 1 is a write primitive with mechanical
   guards; PR 2 rewrites an entry in the overseer's NEVER list. The NEVER-list edit is the
   highest-consequence line in the whole change and must not be the twelfth file of sixteen, where
   this repo's own size policy says findings measurably tail off.
3. **It makes the final admin override maximally auditable.** #1657 anticipates one last override; a
   7-file, prose-only PR 2 is the cleanest possible thing for that override to be spent on.

Splitting does **not** cost a human-approval round in practice: `bootstrap/**` and
`scripts/framework/**` are both protected, so a single 16-file PR would need the same human anyway.
Neither half leaves the tree broken — PR 1 is tested, unused code; PR 2 rewires onto a primitive
already on `main`. If the coder concludes the split is genuinely impossible, the policy's own path
applies: file a `needs-human` issue explaining why and await explicit authorization — **do not** open
a 16-file PR on your own judgement.

---

## 3. Binding conditions — the checklist `code-reviewer` verifies

| # | Condition | Source |
|---|---|---|
| **ARCH-1** | TD-1657 §12 A1's premise is corrected: ESC-1 is **resolved** (2026-09-11); slice 4's live gates are ESC-4/ESC-5, both disjoint from this surface. FC-1/FC-2 recorded in `ADR-1357-AMENDMENT-1`. | AD-1 |
| **ARCH-2** | Two sequential PRs on the §2 seam; PR 2 does not open before PR 1 merges; each title states its position. | §2 |
| **ARCH-3** | `request-reviewer`'s `no_qualifying_trigger` refusal payload carries `codeowners_human_owned`; `null` + `not_verified[]` if unevaluable; never a trigger. | AD-3 |
| **ARCH-4** | One follow-up issue filed for CODEOWNERS-parser consolidation **and** `team_reviewers` support (AD-8), with the stated links and constraints. Not a blocker; not bundled. **Filed as #1838.** | AD-4, AD-8 |
| **ARCH-5** | The #1215 precheck does **not** govern the verdict review; G4 is its sole dedup authority. The clause is struck from the `:407` and `:408` replacements. | AD-5a |
| **ARCH-6** | `**Decision: HUMAN_REQUIRED**` appears in the verdict review body on **every** HUMAN_REQUIRED disposition, unconditionally; `"(where applicable)"` struck from §3.4; pinned by a test. | AD-5a |
| **ARCH-7** | `prior_overseer_decision` (`:331-340`) is left reading `/issues/{n}/comments` only; the new subsection states in-file that it is knowingly not wired, names the follow-up issue (**#1839**), and says why. | AD-5b |
| **ARCH-8** | Follow-up filed for the #761 revival with its two bounded human questions and the ESC-5/#1816 cross-reference. **Filed as #1839** (`needs-human`, `priority:high`, v0.7.0). | AD-5b |
| **ARCH-9** | I2's predicate is "any review state, `commit_id == head.sha`"; **W12** covers `APPROVED` and `COMMENTED`. | AD-6 |
| **ARCH-10** | I2 and `submit-verdict`'s `commit_id` use the one `head.sha` read in the §4.2 preamble. | AD-6 |
| **ARCH-11** | I2's comment and W12's docstring state the reason behaviourally, with no `merge_authority.py` line-number citation. | AD-6 |

**Corrections `technical-design` must make to TD-1657 before the coder starts** (mechanical, no new
iteration): §12 A1's ESC-1 premise (ARCH-1); §9 claim 1 and §11's VP-10 row, which are **false** as
written once AD-5b is applied (ARCH-7); §3.4's `"(where applicable)"` (ARCH-6); the `:407`/`:408`
precheck clause (ARCH-5); §4.4 I2 and W12 (ARCH-9); §2's PR shape (ARCH-2).

**One factual correction with no ruling attached:** TD-1657 §1 and #1657 state the #1426 bypass "can
never fire". `overseer_posted_any_review` (`require_overseer_approval.py:196-210`) matches a review in
**any** state, and `post_review_thread.sh` submits its implicit review as `COMMENT` — so on any PR
where the overseer posted a blocking review thread, the bypass's first condition is already satisfied
today. The defect is real and unchanged (it is not satisfied on the PRs #1657 cites, which have zero
reviews), but the claim should be stated as *"is not satisfied on any path the overseer routinely
takes"* rather than *"can never fire"*. Overstating a defect in a governance artifact is the same
class of error as understating one.

---

## 4. Product-boundary checkpoint — disposition

Per CORE, each ruling was tested for a product/policy consequence before binding:

| Ruling | Consequence | Disposition |
|---|---|---|
| AD-1 (proceed) | The overseer begins recording `APPROVE` verdicts on protected-surface PRs — user-visible, and a change to what a gate observes. | **Already cleared.** This is the human's 2026-09-14 ruling verbatim. No new checkpoint. |
| AD-2 (no `REQUEST_CHANGES`) | Declines to add a bot-held merge block. | Status quo preserved; no checkpoint required. |
| AD-3 (no widening) | Preserves the ruling's scoping exactly. | Status quo preserved; no checkpoint. ARCH-3 is observability only. |
| AD-5b (#761 not revived) | **Deliberately routed.** Revival would add a human gate to the LOW/MEDIUM non-protected path — human-attention obligation and throughput. | **Routed, not decided.** ARCH-8 files it as `needs-human` with two bounded questions. I do not bind it. |
| AD-6 (I2) | Prevents a livelock; changes no disposition that is reachable today. | No checkpoint. |
| ARCH-2 (PR split) | Process only. | No checkpoint. |
| §3.4 narrative relocation | The findings narrative moves from a conversation comment into the verdict review body. | **Accepted, noted.** Review bodies render in the same PR timeline; this is a rendering change, not an availability change. Required by change 1 of the issue. |

---

## 5. Startup-gap analysis and affected sign-offs

Per CORE, every reactive architecture decision is tested against *"should this have been settled in
the initial architecture review, before design and code were built against it?"*

| Item | Should it have been settled up front? | Disposition |
|---|---|---|
| The overseer's verdict artifact type vs. the gate's consumed artifact type | **Yes** — `research/findings/an-enabled-control-can-still-not-cover-its-target.md` (2026-08-02) prescribed the reconciliation and nobody re-ran it against the approval gate. | #1657 is already `process-gap`; **no new `startup-artifact-gap` issue.** This ADR is that reconciliation for the approval gate. |
| ADR-1357 §4's slice-4 row saying "Blocked on ESC-1" nine days after ESC-1 was answered | **Yes.** A stale block in an ACCEPTED ADR came within one ruling of stalling a `priority:critical` fix on an escalation that does not exist. | Corrected in `ADR-1357-AMENDMENT-1` §2. The **general** lesson — an ADR's escalation table must be updated in the ADR when the human answers in the issue thread, not left to the comment thread — is recorded there as a process note. |
| The #761 guard being dead | **Yes**, and it is a third instance of the same producer/consumer class. | Left dead (AD-5b); revival routed to the human via ARCH-8 because revival is a product decision, not a repair. |

**Affected sign-offs.** No prior sign-off is orphaned by these rulings:

- **`require_overseer_approval.py` (#1426)** — its `overseer_posted_any_review` precondition is
  unchanged; it simply begins to find records. Sign-off **stands**.
- **`post_review_thread.sh` (#1248)** — the "never assert a verdict" constraint is reinforced, not
  relaxed. Sign-off **stands**.
- **`merge_authority.py`, `require_tier_ceiling.py`, `require_human_approval.py`** — untouched.
  Sign-offs **stand**.
- **TD-1357 slice 1 (#1641, merged) and slice 2 (in review)** — approved against ADR-1357 as it stood.
  FC-1/FC-2 bind **slice 4 only**, a path not yet built, so per the CORE rule *"a decision for a path
  never built → prior sign-offs stand."* Slices 1–3 are read-only and contain no review-POST or
  reviewer-request code, so there is nothing for FC-1 to invalidate. Sign-offs **stand**; **no
  re-review is required**.
- **`scripts/automation/lib/codeowners.py`'s #559 checkpoint** — untouched and not tripped. **Stands.**
- **`overseer.md`'s own most recent approval** is re-reviewed by construction in PR 2 (protected
  surface → human approval).

---

## 6. Self-flag

**RISK: HIGH** — these rulings govern what review verdicts the overseer may record on the
highest-risk change class in the repository, and one of them (AD-5b) is a ruling *not* to fix a dead
control.
**CONFIDENCE: HIGH** on AD-1 (ESC-1's resolution is quoted, dated, and independently corroborated by
TD-1357:48), AD-4 (verified in code at `merge_authority_cli.py:659-665`), AD-5b and AD-6 (both read
out of `merge_authority.py` directly, at :569-593 and :585-593/:658). **MEDIUM-HIGH** on AD-3, whose
consumer-install half rests on `require_code_owner_review` being configured in a repo I cannot read;
ARCH-3's disclosure requirement exists precisely so that assumption becomes measurable rather than
permanent.
**BLAST RADIUS:** #1657's build; ADR-1357 slice 4's implementation contract; two new follow-up issues.
