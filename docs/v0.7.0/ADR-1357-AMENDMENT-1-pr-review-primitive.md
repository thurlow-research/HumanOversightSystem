# ADR-1357 AMENDMENT 1 — the PR-review write primitive lands early; slice 4 calls it

**Status:** ACCEPTED — binding on `technical-design` and `coder` for #1357 build slices 4 and 6.
This document **amends** `docs/v0.7.0/ADR-1357-merge-authority-execution.md`; it does not replace it.
Every decision in the base ADR (AD-1 … AD-14, ESC-1 … ESC-3) stands **except** where a ruling below
names it. Where the base ADR and this document differ, **this document governs.**
**Author:** `architect`
**Date:** 2026-09-23
**Driver:** #1657 (`priority:critical`) — see `docs/v0.7.0/ADR-1657-overseer-review-objects.md`,
which this amendment exists to make visible from the #1357 side.

---

## 1. Why this amendment exists

#1657 lands `bootstrap/pr_review.sh` + `scripts/automation/pr_review_cli.py`: a write primitive that
performs `POST /repos/{o}/{r}/pulls/{n}/reviews` and
`POST /repos/{o}/{r}/pulls/{n}/requested_reviewers`. ADR-1357 §4 nominally assigns *any* GitHub
mutation and the exit-3 refusal convention to **build slice 4**, and **AD-7** specifies
`overseer_merge.sh` performing the review POST as part of an atomic approve-and-merge unit.

Landing the primitive in #1657 is ruled an **authorised early landing**, not a slice violation
(ADR-1657 AD-1). This amendment records the consequence for slice 4, because a forward constraint
recorded only inside another issue's design document is one nobody reads at the moment it binds.

---

## 2. AM-1 — §4's slice-4 row is corrected: ESC-1 is RESOLVED. (Correction of stale text.)

ADR-1357 §4's slice-4 row reads *"**Blocked on ESC-1** (the affirmative test for the CRITICAL path is
undefined until it is answered)"*, and §3's ESC-1 heading and the §"Human Review Required" list read
the same way.

**ESC-1 was answered by the human on 2026-09-11** (#1357 comment `2026-09-11T06:47:52Z`), and the
follow-up comment two minutes later states: *"All three architect escalations are now resolved: ESC-1
(codeowner-approval-required-above-ceiling) … ESC-2 (moot — implementing ESC-1's rule correctly
answers it), ESC-3 (no retrospective audit). #1357 has no remaining open escalations blocking build."*
`docs/v0.7.0/TECHNICAL-DESIGN-1357-merge-authority-primitives.md:48` already records this.

**The resolution, restated so slice 4 does not have to reconstruct it from a comment thread:**

> Tier-agnostic. If `tier ≤ OVERSEER_CEILING`: standard path, unchanged. If `tier > OVERSEER_CEILING`:
> a verified CODEOWNER `APPROVE` review becomes a **required additional** gate, layered **on top of**
> — never instead of — the overseer's own required review. **The overseer is always a required
> approver, at every tier**; codeowner approval above ceiling is additive, not a substitute. Once both
> are satisfied (codeowner approved AND the overseer's own gates pass AND other gates satisfied), the
> merge is automatic — no separate "human clicks merge" step. Missing codeowner approval →
> `HUMAN_REQUIRED`. This replaces the CRITICAL-only carve-out at `overseer.md:449` with a general
> rule. Enforce in code per Q6: the merge wrapper checks for a real, verified codeowner approval — not
> narrated, not inferred from tier/label/title — as part of its fresh recompute.

**AM-1 (binding):** §4's slice-4 gate column is amended to read **"Blocked on ESC-4 and ESC-5"**, and
§3's ESC-1 section is annotated **RESOLVED 2026-09-11** with the text above. ESC-4 (four of
`decide_merge_authority`'s inputs have no cross-clone transport) and ESC-5 (whether the SPEC-303b
CODEOWNERS gate gets a clearing path) are the live gates, both open as of 2026-09-23.

**Process note, recorded because this nearly cost a `priority:critical` fix.** A stale "blocked"
marker in an ACCEPTED ADR is indistinguishable, to the next reader, from a live block —
`technical-design` correctly refused to proceed past it and routed the question, which is the system
working, but only after a full design cycle spent on a block that did not exist. **When a human
answers an escalation in an issue thread, the ADR's escalation section and build-order table are
updated in the same session.** The comment thread is the record of the answer; the ADR is the record
of the *state*, and the two must not be allowed to diverge.

---

## 3. AM-2 — Forward constraint: slice 4 calls the #1657 primitive; it does not re-implement it. (BINDING.)

> **FC-1.** `overseer_merge.sh` and `overseer_escalate.sh` **must not** issue
> `POST /repos/{o}/{r}/pulls/{n}/reviews` or `POST /repos/{o}/{r}/pulls/{n}/requested_reviewers`
> themselves. Their approve/comment and reviewer-request legs **must** be performed by calling
> `scripts/automation/pr_review_cli.py`'s functions in-process (preferred — it keeps one process, one
> token, one envelope) or by invoking `bootstrap/pr_review.sh`. One invocation site per authority
> (D41). A second implementation of either POST is a defect and `code-reviewer` must reject it.
>
> **FC-2.** Slice 4 **must not** re-derive any of: the reviewer login (`resolve_human_reviewer`), the
> reviewer trigger predicate (`evaluate_reviewer_trigger`), the above-ceiling approve refusal (G1), or
> the self-authored approve refusal (G2). Those belong to `pr_review_cli`. AD-5's fresh-recompute
> requirement governs the **merge authorization**, which is `decide_merge_authority`'s answer — it is
> not a licence to recompute the review primitive's own guards a second time, in a second place, with
> a second chance to diverge.

**AD-7's atomicity is preserved exactly, not weakened.** AD-7's requirement is that the *agent* issues
**one** command rather than being told to remember a second one. An in-process call from
`overseer_act.py` into `pr_review_cli` is internal to that one command: the agent still issues one
invocation, and partial-failure handling is unchanged — approval succeeded + merge failed still emits
`{"approved": true, "merged": false, "error": …}`, applies `needs-human`, and exits **1**, never 0.

**Exit-code compatibility.** `pr_review_cli` adopts AD-2's envelope and AD-5's exit-3 refusal
semantics verbatim, so slice 4 inherits a primitive that already speaks its contract. A refusal
returned by the primitive is a refusal of the *primitive's* authority (above-ceiling approve,
self-authored approve, no qualifying reviewer trigger); slice 4 must map it into its own envelope and
must **not** collapse it into a generic exit 1 — the distinction between "not allowed" and "failed" is
the whole point of AD-5's exit 3.

---

## 4. AM-3 — Named ARCH-3a deviation, recorded here so the exemption list stays in one place. (BINDING.)

`bootstrap/pr_review.sh` sources `bootstrap/lib/comment_format_check.sh` and can therefore **refuse
from bash** when `HOS_COMMENT_FORMAT_MODE=enforce`. This deviates from ARCH-3a (*"no decision
reachable only through bash"*).

**Ruled acceptable** (ADR-1657 AD-7). Re-implementing the #1270 format contract in Python would fork a
validator whose entire purpose is that the write paths **cannot** drift apart, and would create a
second format authority — the #1135 class. One bash implementation with a third caller is the lesser
evil. The invocation must be byte-identical in shape to `post_comment.sh:79-86` and
`post_review_thread.sh:103-112`: no new mode, no new default, no `pr_review.sh`-specific branch inside
the shared check. `bootstrap/merge_authority.sh` and the slice-4 wrappers remain **fully** bound by
ARCH-3a; this exemption covers the comment-format check only, and only in wrappers that post a body.

---

## 5. AM-4 — Observation routed to slice 4 / ESC-5, not fixed by #1657.

`decide_merge_authority`'s requested-reviewer gate (`scripts/automation/lib/merge_authority.py:585-593`)
returns `HUMAN_REQUIRED` whenever `requested_reviewers` contains `human_reviewer` — **unconditionally,
and before** any human-approval check (the first `_find_human_approval` on that path is at `:658`).
Because `POST /pulls/{n}/requested_reviewers` for an already-reviewed user is GitHub's *re-request*
operation, any actor that re-requests a reviewer after that reviewer approved flips the PR back to
`HUMAN_REQUIRED`, with the approval sitting on the PR unread.

#1657 stops the **overseer** from being that actor (guard I2: skip the request when the resolved login
has any review whose `commit_id` equals the current head SHA). It does **not** make the gate robust
against any other actor, because doing so means editing `decide_merge_authority`, which #1657 holds
untouched.

**Routed, not decided:** whether `:585` should gain an *"unless a verified human approval exists on the
current head SHA"* escape belongs to slice 4's fresh-recompute work and is adjacent to **ESC-5**'s
clearing-path question. It is recorded here so slice 4 encounters it as a known property rather than
rediscovering it as a livelock in production. **I do not bind it** — it changes which PRs merge
autonomously, which is ESC-5's class of decision.

---

## 6. What this amendment does not change

- **ESC-4 and ESC-5 remain open and still gate slice 4.** Nothing here answers either. #1657's
  primitive is disjoint from both: it performs no recompute, consumes none of the four
  un-transported inputs, computes no disposition, and merges nothing.
- **AD-1 … AD-14 stand**, including AD-5 (fresh recompute), AD-7 (atomic approve-and-merge), AD-9 (no
  third env parser), and AD-14 (ship-set). AD-14's obligation is unchanged and unsatisfied:
  `bootstrap/pr_review.sh` and `scripts/automation/pr_review_cli.py` join `post_comment.sh` and
  `post_review_thread.sh` as **HOS-repo-only** for now, and slice 6 owns closing that for the whole
  family at once (ADR-1657 AD-9).
- **ESC-3's resolution stands** — no retrospective audit.
- **The base ADR's §6 affected-sign-offs analysis stands.** FC-1/FC-2 bind slice 4, a path not yet
  built; slices 1–3 are read-only and contain no review-POST or reviewer-request code, so no prior
  sign-off is orphaned and no re-review is triggered by this amendment.
