# ADR-1657 AMENDMENT 1: non-merge dispositions summon the human and carry a head-bound interim sign-off

**Status:** ACCEPTED. It binds `technical-design`, `coder`, `code-reviewer` and `security-reviewer` for
#2174 (`docs/v0.7.0/TECHNICAL-DESIGN-2174-overseer-interim-signoff.md`).
This document **amends** `docs/v0.7.0/ADR-1657-overseer-review-objects.md`. It does not replace it.
Every decision in the base ADR stands **except** where a ruling below names it. Where the two
documents differ, **this document governs.**
**Author:** `architect`
**Date:** 2026-10-28
**Driver:** the human ruling on #1936 (ScottThurlow, 2026-10-25), restated as #2174's five required
behaviours.

**Product/policy boundary.** The trigger widening in AM-1 is what changes user-visible behaviour: a
reviewer request lands on nearly every PR the overseer does not merge. The human chose that
explicitly in the #1936 ruling ("no outcome ends with nobody named to act"), so it is cleared. AM-4
narrows *who* can satisfy the new path. That rule is stricter than the TD draft, and it is put to
the human for confirmation as TD ESC-2 before the implementation PR merges.

---

## AM-1: ADR-1657 AD-3 ("do not widen the trigger set") is SUPERSEDED for non-merge dispositions

AD-3 rested on the premise that the human had named widening as **the** failure mode (AD-3 point 4).
The #1936 ruling reverses that premise for one class: when the overseer reaches `HUMAN_REQUIRED` or
`PROPOSE_ONLY`, it must request the human. The ruling outranks AD-3.

- `request-reviewer --disposition {HUMAN_REQUIRED,PROPOSE_ONLY}` satisfies the trigger
  (`non_merge_disposition`). `AUTO_MERGE` is not an accepted value. With no `--disposition`, AD-3's
  three-term scoping and ARCH-3's observational `codeowners_human_owned` field are unchanged.
- AD-3's calibration evidence (`research/sessions/2026-08-04-controls-that-never-fire.md`) still
  applies to the *merge* path. The merge path must never summon a human, and argparse enforces that.
- **Disclosed volume.** Because the `_dep_ceiling_check_present` stub (#152-followup) is still in
  place, PROPOSE_ONLY is nearly universal, so a request lands on nearly every PR that is reviewed and
  not merged. Re-measure this when the stub is replaced (TD §9).

## AM-2: #1426's above-ceiling bypass is RETIRED in favour of the head-bound interim sign-off

**Confirmed (TD A-1 / D2).** The #1426 path in `require_overseer_approval.py` accepted an overseer
review in *any* state on *any* commit. A `COMMENTED` review is never dismissed on push, so the
overseer's side was not bound to the head. That is a live soundness defect, not merely redundant
code. Keeping it next to D1 would leave the weaker path as the one that decides.

The replacement rule is necessary-and-sufficient only as a conjunction. Its security model is
binding:

1. **Trusted rule.** The gate runs from `base.sha` under `pull_request_target`. A PR cannot change
   the rule that judges it. Do not add a `pull_request_review` trigger (#972/#1299).
2. **Authored by the overseer only.** A marker counts only inside a review whose `user.login`
   equals `BOT_OVERSEER_USERNAME` (case-insensitive) **and** whose `user.type == "Bot"`. A missing
   `type` does not count (fail closed). The PR body, conversation comments, and reviews by any other
   identity are never read for the marker.
3. **Bound to the evaluated head.** The marker's `head=` field, the review's `commit_id`, the PR's
   live head, and the head of the `pull_request_target` event that the check run is attached to must
   all be the same SHA. The event head is read from `$GITHUB_EVENT_PATH` (on a rerun this is the
   replayed original event). A mismatch fails the check. It never falls back to another commit's
   reviews. This closes a gap in the TD draft: when a PR head is force-pushed from X to Y and back,
   the X check run could otherwise go green on Y's reviews.
4. **Latest verdict decides, and a dismissed verdict revokes.** The candidates are the overseer's
   non-empty-bodied reviews on the head in the states `COMMENTED`, `APPROVED`, `CHANGES_REQUESTED`
   or **`DISMISSED`**. If the latest candidate is not a marked `COMMENTED` review, the result is a
   failure (M2). Including `DISMISSED` stops an older marked sign-off from being resurrected when a
   later approval on the same head is dismissed (#902 hold, admin action). `PENDING` is excluded.
5. **The human side is on the head and designated (AM-4).**
6. **#621 floor.** With no overseer verdict on the head, the result is a failure, whatever the human
   approvals say.
7. **Ceiling.** The marker is appended **only** to `--event comment` verdicts. The overseer still
   never posts `APPROVED` above `OVERSEER_CEILING` (wrapper guard G1, FABERIX-ROLES §5), and
   `require-tier-ceiling` still fails any overseer approval above the ceiling.

**Transition.** Open above-ceiling PRs that pass today on #1426 turn red until the overseer's next
cycle posts a marked verdict. The verdict review is not governed by the #1215 precheck, and G4 cannot
byte-match a body that now carries the marker, so the re-post happens on the first cycle. The PR body
must say this.

## AM-3: ARCH-5 is refined, not broken: guard G6 keys sign-off identity on (head SHA, expected action)

**Confirmed (TD A-3 / D5).** ARCH-5 has two parts. The first is a **single dedup authority for the
verdict**, which is the wrapper, never the #1215 precheck. G6 lives in the wrapper, so that part is
untouched. The second is a **rationale**: never suppress a verdict whose content changed. G6 does
suppress narrative-only changes. That is a deliberate narrowing, ruled here:

- For a **marked interim sign-off**, the content that matters to the human is the structured
  `(head, expected action)` pair, which D-5 verifies against the human-visible
  `Expected action: **…**` text. Re-posting a reworded narrative on every cycle of a stuck PR is
  noise that requirement 4 forbids. Under TD §3.6 it would also re-run all three gates on every
  cycle.
- **Disposition is deliberately not part of the key.** #761 flips PROPOSE_ONLY to HUMAN_REQUIRED
  because of the overseer's own reviewer request (TD F10). That flip is a derived marker, not new
  information. overseer.md's "derived markers are not reasons" rule is extended to the expected
  action, which keeps the key stable.
- Byte-identical G4 still governs unmarked verdicts and `approve` verdicts. New findings on an
  unchanged head still surface through `post_review_thread.sh` threads, which G6 never touches.

## AM-4: who can satisfy the human side of the interim path (NEW, stricter than the TD draft)

The ruling says the overseer requests **the human CODEOWNER** and the merge then "waits **only** on
the human's approval". The TD draft accepted any non-bot `OWNER`/`MEMBER`/`COLLABORATOR`. Under that
draft, any write collaborator in a consumer repo could override an overseer `DO NOT MERGE` on a
non-protected path, a step that today needs the repo admin. That reads the ruling too loosely.

**Ruled default:** on the interim path only, an eligible approval is a review with
`state == APPROVED`, `commit_id ==` the evaluated head, not a bot under
`require_human_approval.is_bot_reviewer`, and a login in the **designated human set**. That set is
`HUMAN_REVIEWER` from base `machine-accounts.env`, together with every individual (`@user`, never
`@org/team`, since team membership is unverifiable here) owner named in the base checkout's
`.github/CODEOWNERS`. The comparison is case-insensitive. If the set is empty, the gate exits 2
(misconfigured). `author_association` is dropped. The designated set subsumes it, and its live
behaviour was the TD's one unverified assumption.

In this repo the set is `{ScottThurlow}`, so behaviour here is identical to the draft. In consumer
repos it narrows who can override the overseer. That is the product-visible part, and it is TD
ESC-2.

## AM-5: worker bounce is not a non-merge disposition; DIRTY is

**Confirmed (TD A-4).** `record_pr_bounce` posts a conversation comment and converts the PR to
draft. It posts no verdict review, writes no marker, and names the worker as the next actor, so
requirement 3 is met without the human. A draft cannot be merged.

The **DIRTY** step-6 outcome is a different case. TD-1657 §3.3 classes it as merits-type
HUMAN_REQUIRED, and it posts a verdict review. It therefore passes `--disposition HUMAN_REQUIRED`
with `DO_NOT_MERGE` or `REQUEST_CHANGES`, carries the marker, and summons the human. A human who
wants to override the overseer must do two deliberate GitHub acts: resolve the overseer's blocking
review threads (`required_conversation_resolution: true`) and approve the head. The visible sentence
and the executive summary must say so (#2170).

## AM-6: TD-1657 §4.1 "no conditionally-valid flag" gets one identity-keyed exception

**Confirmed (TD A-2 / D4).** `--disposition` is required for `--app overseer` and refused for
`worker` and `human`. The condition is the caller's identity, which the preamble already validates
(D-1 cross-checks the resolved bot login). If the flag were optional, forgetting it would recreate
#1668 silently, with no human summoned and the gate red. This exception is the only one. Any further
conditionally-valid flag needs its own architect ruling.

---

## Affected sign-offs

- The #1426 code-review and security sign-offs on `require_overseer_approval.py` are **invalidated**
  (AM-2). The replacement is reviewed as new code by `security-reviewer`.
- The #1657 sign-offs on `submit-verdict` and `request-reviewer` **stand** for G0-G5 and I2. D-0 to
  D-5, G6 and the `non_merge_disposition` trigger term are new code and are reviewed as such.
- The ADR-1657 AD-3 text stays in place as history. Readers are pointed here.
