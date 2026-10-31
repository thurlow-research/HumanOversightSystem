# TECHNICAL DESIGN — #2174: the overseer's interim sign-off on non-merge dispositions

**Status:** ARCHITECT-APPROVED WITH AMENDMENTS (round 1 of 5). The architect edited this document in
place. Every amended passage is tagged **[ARCH-R1]**, and the rulings are listed in §11. The binding
ADR is `docs/v0.7.0/ADR-1657-AMENDMENT-1-non-merge-reviewer-trigger.md` (AM-1 to AM-6). Coding may
start. ESC-2 (§8) must be answered before the implementation PR **merges**, not before it is coded.
**Author:** `technical-design`
**Date:** 2026-10-28
**Issue:** #2174 (milestone v0.7.0). It brings the #1428/#1426 interim forward under the human ruling
on #1936 (2026-10-25).
**Binding inputs:**
- the human ruling on #1936 and the five required behaviours restated in #2174;
- #621: a human approval alone never satisfies `require-overseer-approval`;
- #1426 and `docs/FABERIX-ROLES.md` §5: above `OVERSEER_CEILING` the overseer records a review but never `APPROVED`;
- #2170: escalation text names a GitHub action, never a file or a shell step;
- `docs/v0.7.0/ADR-1657-overseer-review-objects.md` and `TECHNICAL-DESIGN-1657-overseer-review-objects.md`.

**Out of scope:** the full #1936 epic (a single CODEOWNERS gate and a human-maintainers team). #1816
and #1668 stay parked. This design changes nothing in `merge_authority.py`'s matrix.

> This document specifies contracts, not code. A "must" is a requirement on the implementation.
> Choices the inputs left open are labelled **D<n>**, each with its reason.

---

## 0. Search-first findings and verified state

**Searched:** `scripts/framework/require_overseer_approval.py`, `require_tier_ceiling.py`,
`require_human_approval.py`, `rerun_gate_checks.py`, `setup_branch_protection.sh`;
`.github/workflows/require-overseer-approval.yml` and `rerun-gate-checks.yml`;
`scripts/automation/pr_review_cli.py`, `bootstrap/pr_review.sh`, `bootstrap/post_review_thread.sh`;
`scripts/automation/lib/merge_authority.py` and `github.py`; `scripts/oversight/lib/audit_log.{sh,py}`;
`.claude/agents/overseer.md` and `bootstrap/overseer-cron-prompt.md`; TD/ADR-1657, TD-2101; and the
stale branch `worker-1668-propose-only-actionable-260928080001-3321809`.

**Reused rather than rebuilt:**
- `require_human_approval.py::is_bot_reviewer` is the bot test (three layers);
- `pr_review_cli.py` is the only writer of review objects and reviewer requests;
- `scripts/oversight/lib/audit_log.py::write_event` writes the audit records;
- from the #1668 branch, the "latest verdict on head" rule, with empty-bodied thread containers excluded.

No new script, wrapper or GitHub helper is created. The #1668 branch's `add_issue_labels` is **not**
reintroduced, because this design writes no labels.

| # | Verified fact | Where |
|---|---|---|
| F1 | The gate passes on any `APPROVED` overseer review. That path does not check the head SHA, so it relies on `dismiss_stale_reviews` (`setup_branch_protection.sh:171`) to turn older approvals into `DISMISSED`. | `require_overseer_approval.py:119-132`, `:175-177` |
| F2 | The #1426 bypass passes when three things hold: the overseer posted **any** review, on **any** commit and in any state; the tier computed live is above the ceiling; and **any** non-bot account has an `APPROVED` review. **The overseer side is not bound to the head.** A `COMMENTED` review is never dismissed on push, so a comment on an old head plus a human approval on the new head passes, even though the overseer never looked at the new head. The human side is bound to the head only indirectly, through `dismiss_stale_reviews`. | `:135-148`, `:179-201` |
| F3 | The bypass fires only when the tier is above the ceiling. Three cases are left red: a HUMAN_REQUIRED at or below the ceiling (protected surface where the overseer had a merits reason to `comment`, evaluator ESCALATE/CONDITIONAL, unresolved findings, a #902 hold, release-related), PROPOSE_ONLY, and the #757 case. In all three the overseer must post `comment` (TD-1657 §3.3), so admin bypass is the only way to merge. This was observed on PR #2146. | TD-1657 §3.3 |
| F4 | `require-tier-ceiling` fails only when the overseer `APPROVED` above the ceiling. With a `comment` verdict it passes trivially. | `require_tier_ceiling.py:1-19` |
| F5 | `require-human-approval` applies only when a protected surface is touched, and then needs any non-bot `APPROVED` review. It does not bind to the head beyond `dismiss_stale_reviews`. | `require_human_approval.py:161-172`, `:196-247` |
| F6 | `request-reviewer` refuses with exit 3 `no_qualifying_trigger` unless the PR is above the ceiling, CRITICAL, or touches a protected surface. This is why PROPOSE_ONLY and the merits-type HUMAN_REQUIRED cases at or below the ceiling summon nobody (#1668). | `pr_review_cli.py:899-922`, `:968-1013` |
| F7 | `request-reviewer` is already idempotent. It skips with `already_requested` (`:1088-1108`) and with `already_reviewed_head`, meaning any review by the resolved human on the current head (`:1111-1128`). The second skip is also the I2 livelock guard. | `pr_review_cli.py` |
| F8 | `submit-verdict` deduplicates in two ways. G3 skips when an approval already exists on this head. G4 skips a `COMMENTED` verdict on this head only when its body is byte-identical. An LLM-written narrative rarely repeats byte for byte, so on a stuck HUMAN_REQUIRED PR G4 posts a new review every cycle. Requirement 4 forbids that. | `:661-686`, `:713-739` |
| F9 | PROPOSE_ONLY is effectively universal. `_dep_ceiling_check_present` is a stub that returns `False`, and `detect_server_side_gate` returns `_PROPOSE_ONLY_DEP` before it reads anything. Every clean PR at or below the ceiling that is not protected and not security-relevant therefore ends PROPOSE_ONLY. AUTO_MERGE is unreachable today. | `merge_authority.py:181-193`, `:234-246`, `:684-689` |
| F10 | The #761 requested-reviewer gate returns HUMAN_REQUIRED whenever `HUMAN_REVIEWER` is in `requested_reviewers`. So once the overseer has requested the human, the next cycle's disposition on the same head becomes HUMAN_REQUIRED even if it was PROPOSE_ONLY. | `merge_authority.py:583-596` |
| F11 | `rerun-gate-checks` does not dispatch on a plain `COMMENTED` review. If the human approves **before** the overseer posts a `comment` sign-off, nothing re-runs `require-overseer-approval` and it stays red. | `rerun_gate_checks.py:119-124`; `rerun-gate-checks.yml:70-83` |
| F12 | A `post_review_thread.sh` container is a `COMMENTED` review by the overseer with an **empty body** (ADR-1657 AD-5). It is not a verdict. | `post_review_thread.sh:24` |
| F13 | `require-overseer-approval` runs under `pull_request_target`, from `base.sha`, and is not re-triggered by reviews (#972/#1299). Reviews are read live at run time. | `require-overseer-approval.yml:32-84` |
| F14 | Overseer step 6 forbids the overseer from widening the trigger (`overseer.md:512`). Its PROPOSE_ONLY bullet posts Expected action `NO ACTION` and summons nobody (`:513`). The disposition-to-action mapping is at `:689-694`. | `overseer.md` |
| F15 | `test_overseer_verdict_artifact.py` pins `require_overseer_approval.py`'s docstring to quote FABERIX-ROLES §5 ("Above OVERSEER_CEILING → record a review, but never APPROVED"). The quote must survive this change. | `tests/framework/test_overseer_verdict_artifact.py:275-290` |

---

## 1. Problem in one paragraph

When the overseer reaches HUMAN_REQUIRED or PROPOSE_ONLY it posts a `comment` verdict, which is
correct: it must not assert approval it does not have. Three things then go wrong. Nothing in
`require-overseer-approval` treats that comment as the overseer's side being done, unless the tier is
above the ceiling (F2, F3). For most of these dispositions no human is summoned (F6). And re-runs on an
unchanged head re-post (F8). The result is that a PR a human approves still needs an admin bypass, and
a PROPOSE_ONLY PR waits for nobody.

---

## 2. Decisions

### D1. What "the overseer signs off its own side" means: a marked `COMMENT` review bound to the head

**Chosen.** On HUMAN_REQUIRED and PROPOSE_ONLY the overseer posts its normal verdict review through
`submit-verdict`. **[ARCH-R1] When, and only when, the event is `comment`**, the CLI (not the agent)
appends two things to that review. A HUMAN_REQUIRED `approve` (protected surface, sound on the merits,
≤ C) gets neither: it already passes through the F1 path, and a sentence saying "this review does not
approve the PR" inside an `APPROVED` review would be false.

1. A visible sentence that depends on the action **[ARCH-R1]**. The CLI picks it from the
   `--expected-action` value, so the agent never writes it:
   - `APPROVE`: *"Overseer interim sign-off (#2174): this review does not approve the PR. The merge
     now waits only on a designated human's approval of commit `<sha12>`."*
   - `REQUEST_CHANGES`, `DO_NOT_MERGE`, `DECIDE` and `OTHER`: *"Overseer interim sign-off (#2174):
     this review does not approve the PR, and the overseer recommends against merging it as it
     stands (see above). The overseer's required check no longer blocks. A designated human who
     approves commit `<sha12>`, after resolving the overseer's open review threads, overrides this
     recommendation and makes the PR mergeable."*
2. A machine-readable marker line, bound to the head (grammar in §3.1).

The review's own `commit_id` already binds it to the head. `require_overseer_approval.py` then passes
when the overseer's **latest verdict on the current head** carries a valid marker **and** an eligible
human has `APPROVED` the **current head** (algorithm in §3.2).

**Why the marker cannot be forged, or misused to lower the bar:**
- The gate runs from the trusted base (F13), so the PR cannot change the rule.
- The marker counts only inside a review whose GitHub-attributed author is `BOT_OVERSEER_USERNAME` and
  whose `user.type` is `Bot`. **[ARCH-R1]** If `type` is missing, the review does not count. GitHub attributes a review to the identity that owns the posting token,
  so only the overseer App installation can author one. The same marker written by a human, the worker
  App, Copilot, the PR body or a conversation comment is never read.
- The marker is necessary but **not sufficient**. Even a marker posted wrongly, for example by a buggy
  overseer, can only make the PR mergeable together with an eligible human approval on the same
  commit. The worst case is therefore "a human approved this exact commit and the overseer looked at
  this exact commit". That is the #621 floor itself.
- The marker must name the current head, and the review's `commit_id` must equal it. A sign-off left
  on an older head never carries over after a push.

**Rejected alternatives:**
- **(a) The overseer posts `approve` at or below the ceiling for every non-merge disposition.** This
  fails the merits constraint. An overseer `APPROVED` review satisfies `require-overseer-approval` on
  its own and also counts as the "1 approving review" (`setup_branch_protection.sh:124`). On a PR that
  is not protected, and so not subject to `require-human-approval`, the PR would become mergeable with
  no human. It is also unusable above the ceiling, where `require-tier-ceiling` fails it (F4), and an
  approval asserts "sound on the merits", which is false for a merits-type HUMAN_REQUIRED.
- **(b) The overseer posts a commit status or check run as its sign-off.** This needs a new required
  context and a change to branch protection. A commit status can also be set by any token with
  `statuses:write`, so it is weaker identity than an attributed review. It also duplicates what review
  objects already provide (ADR-1657).
- **(c) Pass `require-overseer-approval` on any human approval.** This violates #621 outright.
- **(d) Generalise the #1426 bypass without the marker** (any overseer review plus any human approval,
  at any tier). Two flaws: an overseer review on an old head would count (F2), and a thread container
  or a bounce comment would count as a sign-off. Requiring the marker on the latest verdict makes the
  sign-off a deliberate act that is bound to the head and can be revoked (§3.2 step 4).

### D2. #1426's above-ceiling bypass is retired and replaced by D1

D1 strictly covers #1426: every above-ceiling disposition is HUMAN_REQUIRED, so it will carry the
marker. D1 is also stricter, because both sides are bound to the head and the PR no longer depends on
live tier recomputation. Keeping both would leave two pass paths with different head-binding, and the
weaker path (F2) would win. Removing #1426 also drops `require_overseer_approval.py`'s only network-heavy
step (`compute_tier_for_pr`), which can fail closed.

**Transition.** The gate runs from base, so it applies to every open PR as soon as this merges. An
above-ceiling PR that already has an unmarked overseer comment and a human approval turns red until the
overseer's next cycle. That cycle re-posts the verdict, because G4 cannot match: the effective body now
includes the marker. This is a one-cycle delay, not an admin bypass. It must be stated in the PR body.

### D3. Summoning the human: `--disposition` widens the reviewer trigger only for non-merge outcomes

`request-reviewer` gets `--disposition {HUMAN_REQUIRED,PROPOSE_ONLY}`. If the flag is present, the
trigger is satisfied (new term `non_merge_disposition`). `AUTO_MERGE` is **not** an accepted value, so
argparse rejects it with exit 2, and the merge path can never summon a human. That keeps #1657's
concern about requesting a human on every PR intact for the only outcome where it was never wanted. The
#1657 rule (above ceiling, CRITICAL, or protected surface) still applies unchanged when the flag is
absent. That case is reachable only for `--app worker|human`, because D4 makes the flag mandatory for
the overseer.

**Disclosure, not an ESC.** Because of F9, PROPOSE_ONLY covers nearly every routine PR. In practice
this design therefore requests the human on almost every PR the overseer reviews and does not merge.
That is the consequence the #1936 ruling chose, and #757 already makes a human approval a precondition
of every merge, so this adds no new human gate, only the notification for one that exists. It
supersedes ADR-1657 AD-3's "do not widen" for non-merge dispositions. The architect must record that
supersession (§5, file 14).

### D4. `--disposition` is mandatory on every overseer call to the wrapper

If the flag were optional, forgetting it would recreate #1668 silently: nobody summoned and the gate
red. So `--app overseer` without `--disposition` is a usage error (exit 2) on both subcommands. This is
a deliberate exception to TD-1657 §4.1's "no conditionally-valid flag" rule. The condition is the
caller's identity, which is already validated, and the alternative is a silent failure. Worker and
human callers keep today's argv: for them `--disposition` is refused (exit 3,
`disposition_requires_overseer_identity`), because a marker from them would be ignored by the gate and
would mislead readers.

### D5. Idempotency per head: guard G6 inside the wrapper, keyed on (head SHA, expected action)

To satisfy requirement 4 without suppressing new information, `submit-verdict` adds **G6**. When the
disposition is HUMAN_REQUIRED or PROPOSE_ONLY and the event is `comment`, the post is skipped
(`skip_reason: "interim_signoff_on_head"`) if the overseer's latest verdict on the current head (§3.2
steps 2-3) is `COMMENTED` and carries a valid marker with the **same** `action=`.

- **Why the key is the expected action, not the disposition.** F10 turns PROPOSE_ONLY into
  HUMAN_REQUIRED on the second cycle, purely because of the overseer's own request. Using the
  disposition as the key would therefore re-post every PR once. The expected action (`APPROVE`,
  `DO NOT MERGE`, …) is what is being asked of the human. If it changes, a re-post is new information
  and is posted. If it does not, the human's job is unchanged.
- **This keeps ARCH-5's single-authority rule.** ARCH-5 (TD-1657) forbids two *different* dedup
  authorities, the overseer's #1215 precheck and the wrapper, deciding about the verdict. G6 lives in
  the wrapper, which remains the verdict's only dedup authority; it gains one more predicate. New
  findings on an unchanged head still reach the human through the escalation and blocking review
  threads (`post_review_thread.sh`), which the #1215 precheck governs and G6 never touches.
- **On request-reviewer.** F7's existing guards already give exactly one request per head, so nothing
  is added.

### D6. Which human approval counts **[ARCH-R1: replaced; ADR-1657-AM1 AM-4]**

An eligible human approval is a review that meets all of these:
- `state == "APPROVED"`;
- `commit_id ==` the evaluated head (§3.2 step 2);
- not a bot under `require_human_approval.is_bot_reviewer(login, user.type, BOT_ACCOUNTS)`;
- `user.login` (case-insensitive) is in the **designated human set**. The set is `HUMAN_REVIEWER`
  from the base `machine-accounts.env`, together with every individual `@user` owner named anywhere
  in the base checkout's `.github/CODEOWNERS`. `@org/team` owners are excluded because team
  membership is unverifiable here. Comment lines and email owners are ignored. This is a pure
  function, `designated_humans(env, codeowners_text) -> frozenset[str]`, in
  `require_overseer_approval.py`. It does no path matching, because the question is "is this one of
  the project's oversight humans", not "does this person own these paths". The path-owner question
  is `require-human-approval` and `require_code_owner_reviews`. If `.github/CODEOWNERS` is absent,
  the set is just `HUMAN_REVIEWER`. If the set is empty, the gate exits 2 (misconfigured).

**Why not any collaborator (the draft's rule).** The ruling says the overseer requests "the human
CODEOWNER" and the merge then waits "only on the human's approval". Under an any-collaborator rule,
any write collaborator in a consumer repo could override an overseer `DO NOT MERGE` on a
non-protected path, a step that today needs the repo admin. `author_association` is dropped. The
designated set subsumes it, and its live behaviour was one of the two unverified assumptions in the
self-flag. In this repo the set is `{ScottThurlow}`, so nothing changes here. For consumer repos it is
a product-visible narrowing, put to the human as ESC-2. The filter applies only on the D1 path, and
`require_human_approval.py` is unchanged (§9).

### D7. After the human approves, who merges

No change to merge authority.
- **The overseer merges on its next cycle** wherever `overseer.md` already authorizes a merge once
  there is a human approval on the head. Today that is the HUMAN_REQUIRED (CRITICAL tier) rule (3).
- **Everywhere else the human merges with GitHub's Merge button.** That covers PROPOSE_ONLY (F9, the
  stub), above-ceiling cases, and merits-type HUMAN_REQUIRED. All required checks are green, so no
  bypass is needed.
- **[ARCH-R1]** Branch protection also sets `required_conversation_resolution: true`
  (`setup_branch_protection.sh`). Any open overseer escalation or blocking review thread must be
  resolved before GitHub allows the merge. That is a GitHub act, and it is deliberate. On a
  `DO_NOT_MERGE` or `REQUEST_CHANGES` sign-off, the human overrides the overseer with two acts:
  resolving the thread and approving. Both the executive summary and the visible sentence (D1) must
  say so.

The executive summary states which case applies (§4.3), so requirement 2 holds on either path.

### D8. Audit

The CLI writes the records. The agent does not, so the records are deterministic. The CLI writes one
record per actual GitHub write, and none on a skip or refusal, so a re-run adds no audit noise. The
record schemas are in §3.5.

---

## 3. Contracts

### 3.1 Marker grammar (one shared constant, defined once)

```
<!-- hos:overseer-interim-signoff v=1 disposition=<HUMAN_REQUIRED|PROPOSE_ONLY> action=<ACTION> head=<sha> -->
```
- `<ACTION>` is one of `APPROVE`, `REQUEST_CHANGES`, `DECIDE`, `DO_NOT_MERGE` or `OTHER`. These are
  the overseer.md enum values with spaces replaced by `_`. `NO_ACTION` is not valid, because a
  sign-off always waits on a human.
- `<sha>` is exactly 40 lowercase hex characters.
- The marker must be on its own line. The matching regex is anchored with `re.MULTILINE`:
  `^<!-- hos:overseer-interim-signoff v=1 disposition=(HUMAN_REQUIRED|PROPOSE_ONLY) action=(APPROVE|REQUEST_CHANGES|DECIDE|DO_NOT_MERGE|OTHER) head=([0-9a-f]{40}) -->$`
- **Single source of truth.** The prefix, the regex and the render function live in
  `require_overseer_approval.py` as `INTERIM_MARKER_RE`, `render_interim_marker(disposition, action, head)`
  and `parse_interim_marker(body) -> (disposition, action, head) | None`. `pr_review_cli.py` loads them
  through its existing sibling-loader idiom (`_load_require_tier_ceiling` at `:462` is the model), so
  the writer and the reader cannot drift.
- `parse_interim_marker` returns `None` when there are zero matches **or more than one**. Multiple
  markers fail closed.

### 3.2 `require_overseer_approval.py` — gate algorithm (replaces `:179-201`)

1. **Existing path, unchanged.** If `overseer_has_approved(reviews, overseer_login)`, the gate passes
   (exit 0). The message is unchanged.
2. **Resolve the head, bound to the check run's commit [ARCH-R1].** Call
   `gh api repos/{repo}/pulls/{pr} --jq .head.sha` to get the live head. If the result is empty or
   does not match `^[0-9a-f]{40}$`, exit 2 (fail closed).
   - If `GITHUB_EVENT_PATH` is set, read `pull_request.head.sha` from that JSON file. This is the
     commit the check run is attached to; on a rerun it is the replayed original event. A missing or
     malformed value exits 2. If it differs from the live head, fail with exit 1 and the message
     *"This check belongs to commit `<event12>`, but the PR head is now `<live12>`. The check on the
     new head decides; no action is needed."*
   - If `GITHUB_EVENT_PATH` is unset (a local run), use the live head. A local run cannot affect
     branch protection.
   - Why: without this binding, a PR head force-pushed from X to Y and back to X could leave X's
     check run green after it was evaluated against Y's reviews. `require-overseer-approval.yml` is
     still unchanged, because the runner writes `GITHUB_EVENT_PATH` itself.
3. **Find the overseer's latest verdict on the head**, `latest_overseer_verdict_on_head(reviews, overseer_login, head_sha)`,
   which is pure:
   - keep reviews whose `user.login` equals `overseer_login` case-insensitively;
   - and whose `user.type` is exactly `Bot` **[ARCH-R1: a missing field does not count]**;
   - and whose `commit_id == head_sha`;
   - and whose `state` is `COMMENTED`, `APPROVED`, `CHANGES_REQUESTED` or **`DISMISSED`**
     **[ARCH-R1]**, which excludes only `PENDING`;
   - and whose `body.strip()` is non-empty, which excludes F12 thread containers;
   - and which have `submitted_at` set.

   The verdict is the maximum by `(submitted_at, id)`. If there is none, the gate fails with the
   "not reviewed" message (§3.3 M1).
4. **Validate the sign-off.** The verdict's `state` must be `COMMENTED`. It must have a parsed marker,
   the marker's `head` must equal `head_sha`, and its disposition must be one of `HUMAN_REQUIRED` or
   `PROPOSE_ONLY`. If any of these fails, the gate fails with M2. Because only the latest verdict
   counts, the overseer can revoke a sign-off by posting a later verdict without a marker on the same
   head. **[ARCH-R1]** A latest verdict in the `DISMISSED` state also fails with M2. Otherwise,
   dismissing a later approval on the same head (a #902 hold, or an admin acting) would bring back an
   older marked sign-off.
5. **Check configuration.** If `BOT_ACCOUNTS` is empty, exit 2 with a "misconfigured" message (same
   reasoning as the #994 precedent). **[ARCH-R1]** If the designated human set (D6) is empty, exit 2
   in the same way. Both are checked only here, so a misconfiguration surfaces only when it matters.
6. **Find eligible human approvals**, `eligible_human_approvals_on_head(reviews, bot_accounts, designated, head_sha)`,
   which is pure and applies D6. If the list is non-empty, the gate passes (exit 0) with the message
   `✔ require-overseer-approval: <overseer> signed off commit <sha12> (interim, disposition=<D>) and <humans> approved it — gate satisfied.`
   Otherwise it fails with M3.
7. **Remove** `overseer_posted_any_review` and the #1426 branch (D2). `require_tier_ceiling.compute_tier_for_pr`
   stays, because it has its own tests. Its comment "reused by require_overseer_approval's bypass" is
   updated to say it is no longer reused there.
8. **Docstring.** Rewrite the module docstring's bypass paragraph to describe D1. Keep the citation of
   `docs/FABERIX-ROLES.md` and the literal quote `Above OVERSEER_CEILING → record a review, but never APPROVED`
   (F15). Keep the first docstring line unchanged so `SCRIPTS-INDEX.md` does not need regenerating.

### 3.3 Gate failure messages (stderr; every message names a GitHub act or says that none is needed, #2170)

- **M1 (no verdict on the head):** *"The overseer has not reviewed commit `<sha12>` yet. No action is
  needed; the overseer reviews it on its next cycle. A human approval on its own cannot satisfy this
  check (#621)."*
- **M2 (the latest verdict is not a sign-off):** *"The overseer's latest review of commit `<sha12>` is
  not a sign-off. Open that review on the PR's Conversation tab for the action it asks of you."*
- **M3 (signed off, no eligible human approval on the head):** *"The overseer has signed off its side
  of commit `<sha12>`, and this merge now waits only on a human. Approve the PR on GitHub (Files changed
  → Review changes → Approve). This check re-runs automatically when you approve."* **[ARCH-R1]**
  The message must also name the logins in the designated set (D6) and say that approvals from
  anyone else do not count for this check.

The current text about admin bypass (`:232-239`) is removed, because the point of this change is that
no bypass is needed.

### 3.4 `pr_review_cli.py`

**argv** (additions to `_build_parser`, `:244-267`):
- `submit-verdict` and `request-reviewer` gain `--disposition`. The choices for `submit-verdict` are
  `AUTO_MERGE`, `HUMAN_REQUIRED` and `PROPOSE_ONLY`. For `request-reviewer` they are `HUMAN_REQUIRED`
  and `PROPOSE_ONLY`.
- `submit-verdict` gains `--expected-action`, with choices
  `APPROVE|REQUEST_CHANGES|DECIDE|DO_NOT_MERGE|NO_ACTION|OTHER`.

**New guards on `submit-verdict`.** They run in this order, after the preamble and before G0, unless
noted otherwise:

| Guard | Condition | Result |
|---|---|---|
| D-0 | `--app overseer` and no `--disposition` | exit 2, `--disposition is required for --app overseer` |
| D-1 | `--disposition` given and `ctx.app_role != "overseer"`, or `pre.bot_login` ≠ `overseer_handle` | exit 3, `disposition_requires_overseer_identity` |
| D-2 | `AUTO_MERGE` with event ≠ `approve`, or `PROPOSE_ONLY` with event ≠ `comment` | exit 3, `disposition_event_mismatch` (this is a disposition bug, so halt) |
| D-3 | disposition is HUMAN_REQUIRED or PROPOSE_ONLY and `--expected-action` is absent or `NO_ACTION`; or PROPOSE_ONLY with an action other than `APPROVE`; or AUTO_MERGE with `--expected-action` other than absent or `NO_ACTION` | exit 2 |
| D-4 *(after G5 reads the body)* | **[ARCH-R1]** any line of the body, after leading whitespace is stripped, starts with `<!-- hos:overseer-interim-signoff`. This applies on **every** disposition, including AUTO_MERGE. | exit 2, `body_contains_marker`. This is defence in depth: an injected marker plus the appended one already fails closed (§3.1, more than one marker). Narrowing the check from a bare substring to the comment-opener prefix stops a refusal when the narrative merely *mentions* the marker name, for example while reviewing this PR. |
| D-5 *(after G5)* | disposition is HUMAN_REQUIRED or PROPOSE_ONLY and the body does not contain the literal `Expected action: **<ACTION with _ replaced by a space>**` | exit 2, `expected_action_not_in_body`. This keeps G6's key honest: the human-visible text and the key agree |

**Effective body.** For HUMAN_REQUIRED and PROPOSE_ONLY **with `--event comment`** **[ARCH-R1]**,
the effective body is
`body.rstrip("\n") + "\n\n" + <visible sentence for the action, D1> + "\n\n" + render_interim_marker(...) + "\n"`.
The effective body is what G4, G6, the POST and `_find_matching_review` all compare and send. Bodies
for AUTO_MERGE and for HUMAN_REQUIRED `approve` are unchanged.

**G6** runs after G4 and before the POST, under the conditions in D5. When it skips, the payload has
`skipped: true`, `skip_reason: "interim_signoff_on_head"` and the existing review's
`id`/`state`/`url`. The skip exits 0 and writes no audit record.

**G1 (never approve above the ceiling) and G2 (never approve one's own PR) are unchanged.** A
HUMAN_REQUIRED `approve` above the ceiling is still refused, which is correct.

**`request-reviewer`:**
- D-0 and D-1 apply as above, with no event.
- `TriggerResult` gains `non_merge_disposition: bool`. `evaluate_reviewer_trigger` gains a keyword
  argument `disposition: str | None = None`, and `triggered = <existing OR> or disposition in {"HUMAN_REQUIRED","PROPOSE_ONLY"}`.
  The function stays pure. Its docstring is updated: "ADR-1657 AD-3 is superseded for non-merge
  dispositions by the #1936 ruling and #2174; with no disposition the scoping is unchanged."
- The payload's `trigger` object gains `non_merge_disposition`, and the payload gains a top-level
  `disposition`.
- If the disposition is set and the resolved reviewer equals the PR author, the command returns exit 0
  with `skipped` and `skip_reason: "reviewer_is_pr_author"`, instead of today's exit 1 (`:1074-1086`).
  On a PR the human authored, the human is already the named actor. Without this change the overseer
  would halt every cycle. Without a disposition the behaviour is unchanged.
- `already_requested` and `already_reviewed_head` are unchanged (F7). They are both the
  one-request-per-head guarantee and the I2 livelock guard.

**Envelope.** Every outcome where `requested` or `posted` is true gains `audit_record` (a relative path,
or `null`).

### 3.5 Audit records (written by the CLI with `audit_log.write_event(event, root=str(ctx.repo_root))`)

The audit module is imported **inside** the write helper, so that importing `pr_review_cli` still
performs no I/O (header contract, `:24-26`).

| `event` | Written when | Fields |
|---|---|---|
| `overseer-reviewer-requested` | `request-reviewer` returned `requested: true` | `pr`, `repo`, `head_sha`, `disposition` (`null` without the flag), `reviewer`, `resolution_source`, `trigger` (the object), `actor` (`pre.bot_login`), `timestamp` (`_now_iso()`) |
| `overseer-interim-signoff` | `submit-verdict` posted (including via ambiguous-POST recovery) with disposition HUMAN_REQUIRED or PROPOSE_ONLY, **on either event** **[ARCH-R1]**. On a HUMAN_REQUIRED `approve` the sign-off is the approval itself, and requirement 5 still needs it recorded. | `pr`, `repo`, `head_sha`, `disposition`, `expected_action`, `event_requested`, `review_id`, `review_state`, `marker_appended` (bool, **[ARCH-R1]**), `actor`, `timestamp` |

If the audit write fails, the GitHub write has already landed. The command returns exit 0 with
`audit_record: null`, and `not_verified` gains `audit write failed: <scrubbed>`. It is not exit 1:
exit 1 would halt the overseer, and on the next cycle the idempotency guards would skip the write, so
the record would be lost permanently. The overseer surfaces `not_verified` in its executive summary's
"could not verify" clause.

### 3.6 `rerun_gate_checks.py` and `rerun-gate-checks.yml` (closes F11)

- The workflow adds the env var `REVIEWER_LOGIN: ${{ github.event.review.user.login }}` and passes
  `--reviewer-login "$REVIEWER_LOGIN"`. The value is passed through an env var, never interpolated
  into the script, which is the same pattern as the existing variables.
- `should_dispatch(event_action, review_state, reviewer_login="", overseer_login="")` returns `True`
  for a submitted `COMMENTED` review when `reviewer_login` equals `overseer_login`
  (case-insensitively). Every other case is unchanged. `overseer_login` comes from
  `BOT_OVERSEER_USERNAME` in `machine-accounts.env`, read with `require_overseer_approval.load_env`
  through the sibling loader.
- **When the overseer login cannot be resolved, a COMMENTED review from a non-empty reviewer
  dispatches.** This covers three causes: `machine-accounts.env` is missing, the sibling load raises
  `ImportError`/`OSError`, or `BOT_OVERSEER_USERNAME` is empty. In each case
  `overseer_login_from_env()` emits a `::warning::` naming the cause and returns `""`. Then
  `should_dispatch` returns `True` for a submitted `COMMENTED` review whose `reviewer_login` is
  non-empty.
  - *Amended in round 2 (§11).* The iteration-1 text said this case "fails toward today's behaviour"
    (no dispatch). That was rejected because a missed dispatch can leave a human approval stuck behind
    a red `require-overseer-approval`.
  - Dispatching is safe: the job is not a required check and reruns are idempotent.
  - A `COMMENTED` review with an **empty** `reviewer_login` still does not dispatch. That is today's
    behaviour, and it keeps the existing `("submitted","COMMENTED")` test case `False`.
- Thread-container comments by the overseer also dispatch. That is harmless: reruns are idempotent and
  the job is not required.

### 3.7 `.claude/agents/overseer.md` (text changes; the coder takes exact wording from this list)

1. **Step 6, `:511` HUMAN_REQUIRED (CRITICAL tier).** Add `--disposition HUMAN_REQUIRED` to both calls
   and `--expected-action APPROVE` to `submit-verdict`. Replace "the #1426 above-ceiling bypass can
   fire" with "the wrapper appends the interim sign-off (#2174); `require-overseer-approval` passes once
   the human approves this head".
2. **`:512` HUMAN_REQUIRED (other reasons).** Every call passes `--disposition HUMAN_REQUIRED`.
   **Delete** the "refusal is the expected, correct outcome … calibration failure" sentences. Replace
   them with: *"Per the #1936 ruling (2026-10-25) every non-merge disposition requests the human; with
   `--disposition` the wrapper cannot refuse on scoping, so an exit 3 here is a disposition bug, so
   halt."* `submit-verdict` passes `--expected-action` matching the executive summary.
3. **`:513` PROPOSE_ONLY.** Run `request-reviewer --disposition PROPOSE_ONLY` and then
   `submit-verdict --event comment --disposition PROPOSE_ONLY --expected-action APPROVE`. The expected
   action becomes `APPROVE`, no longer `NO ACTION`. **Still apply no label** (#1557, unchanged), since
   the pending reviewer request is what names the human.
4. **AUTO_MERGE (`:510`).** Pass `--disposition AUTO_MERGE`. "Do NOT request a human reviewer on this
   path" stays, and argparse now enforces it.
5. **§ Verdict events, ordering (`:652-660`).** `request-reviewer` exit 1 or 3 on a HUMAN_REQUIRED or
   PROPOSE_ONLY path halts before `submit-verdict`, so a sign-off never exists without a request. The
   `no_qualifying_trigger` carve-out is reworded so that it applies only to calls without
   `--disposition`, which the overseer never makes. Add: *"Run both commands every cycle; the wrapper
   is the only dedup authority (already_requested / already_reviewed_head / G3 / G4 / G6). A re-run on
   an unchanged head posts and requests nothing."*
6. **Expected-action mapping (`:689-694`).** PROPOSE_ONLY maps to `APPROVE`. The `APPROVE` definition
   (`:682`) becomes: *"the human's GitHub approval is the remaining gate. Say which GitHub act follows:
   either 'the overseer merges it on its next cycle' (CRITICAL-tier rule (3)) or 'then press Merge on
   the PR once checks are green' (every other case, D7)."* `NO ACTION` loses its PROPOSE_ONLY example.
7. **New sentence under § Escalation format (#2170).** *"Every expected action names a GitHub act the
   human performs on the PR (approve, request changes, comment a decision, press Merge). It never names
   a file, a script, or a shell step. For `DO NOT MERGE`, state that approving the PR overrides the
   overseer's hold and makes it mergeable."*
8. **Tooling table (`:791`) and § Request reviewer (`:814`).** Add `--disposition` (and
   `--expected-action`) and drop "scoped to above-ceiling/CRITICAL/protected-surface only". Keep the
   I2 livelock explanation as it is.
9. **"Derived markers are not reasons" (`:637-643`).** Extend it to the expected action. A HUMAN_REQUIRED
   that exists only because of the overseer's own pending request (#761, F10), or its own `needs-human`
   label, keeps the expected action of the underlying recomputed condition. This is what makes G6 stable.
10. **[ARCH-R1] DIRTY (`:499`) is explicit.** A DIRTY outcome reached in step 6 posts its verdict with
    `--event comment --disposition HUMAN_REQUIRED --expected-action <DO_NOT_MERGE|REQUEST_CHANGES>`,
    and runs `request-reviewer --disposition HUMAN_REQUIRED` first. TD-1657 §3.3 already classes
    DIRTY as merits-type HUMAN_REQUIRED, and ADR-1657-AM1 AM-5 rules on it. A **worker bounce**
    (`record_pr_bounce`, steps 4a and 4c) posts no verdict review and gets no `--disposition`. It is
    not a non-merge disposition (AM-5).
11. **[ARCH-R1] Every example, not only step 6.** Every `submit-verdict` and `request-reviewer`
    invocation in `overseer.md` carries `--disposition`. That includes the re-approve-after-dismissal
    line (`:517`, which is `--disposition HUMAN_REQUIRED --event approve --expected-action APPROVE`
    when re-approving a protected-surface PR, or `AUTO_MERGE` on the AUTO_MERGE path), the tooling
    table (`:791`), § Request reviewer and § Post a verdict (`:814-815`), and the code block at
    `:839`. Without the flag, D-0 makes each of them exit 2.
12. **[ARCH-R1] Conversation resolution (D7).** The `DO NOT MERGE` sentence in item 7 adds: *"…and
    resolving the overseer's open review threads on the PR is part of that override."*

### 3.8 `bootstrap/overseer-cron-prompt.md` (`:62`)

Replace "Auto-merge if within ceiling; escalate to human if above." with "Auto-merge when the matrix
says AUTO_MERGE; on HUMAN_REQUIRED or PROPOSE_ONLY request the human and post the interim sign-off
(`overseer.md` step 6, #2174)."

### 3.9 `bootstrap/pr_review.sh`

Only the header usage comment changes (`:11-18`), to add `--disposition` and `--expected-action`. The
script passes argv through and must not parse them (ARCH-3a, `:63-66`).

---

## 4. Behaviour walk-through: the three gates together

`C` = OVERSEER_CEILING. "H" = an eligible human approval on the current head (D6).

| Case | Overseer posts | require-overseer-approval | require-tier-ceiling | require-human-approval | Mergeable when |
|---|---|---|---|---|---|
| AUTO_MERGE (≤C) | `approve` | ✔ (F1 path) | ✔ (≤C) | N/A (not protected) | overseer merges (unchanged) |
| HR, protected, merits OK (≤C) | `approve`, **no marker** [ARCH-R1] | ✔ (F1 path) | ✔ | ✘ until H | H, then human or overseer per D7 |
| DIRTY (merits-type HR) [ARCH-R1] | `comment` + marker (`DO_NOT_MERGE`/`REQUEST_CHANGES`) | ✘ until H | ✔ | per paths | the human resolves the overseer's threads **and** H (a deliberate override) |
| Worker bounce [ARCH-R1] | conversation comment, then draft; no verdict, no marker | unchanged (an earlier marker on the head stays) | ✔ | — | never while draft; the worker's fix normally moves the head and voids any marker |
| HR, protected, merits blocker (≤C) | `comment` + marker | ✘ until H (M3) | ✔ (no overseer approval) | ✘ until H | H |
| HR, merits-type, not protected (≤C) | `comment` + marker | ✘ until H | ✔ | N/A | H, never the overseer alone |
| HR, above C / CRITICAL | `comment` + marker | ✘ until H | ✔ | depends on paths | H |
| PROPOSE_ONLY | `comment` + marker | ✘ until H | ✔ | N/A | H, then the human presses Merge |
| Push after sign-off | (old marker, old head) | ✘ (M1 until the next cycle) | ✔ | — | the next cycle re-signs, then H on the new head |
| Human approves, no overseer verdict on the head | — | ✘ (M1) — #621 preserved | ✔ | — | never on the human alone |

All three gates are green together only once a human has approved the current head and the overseer
has either approved it or signed off on it.

---

## 5. Files (14, one PR)

| # | File | Change |
|---|---|---|
| 1 | `scripts/framework/require_overseer_approval.py` | §3.1 constants and functions, §3.2, §3.3; retire #1426 (D2) |
| 2 | `scripts/framework/require_tier_ceiling.py` | Comment only (§3.2 step 7) |
| 3 | `scripts/automation/pr_review_cli.py` | §3.4, §3.5 |
| 4 | `bootstrap/pr_review.sh` | Header usage comment only (§3.9) |
| 5 | `scripts/framework/rerun_gate_checks.py` | §3.6 |
| 6 | `.github/workflows/rerun-gate-checks.yml` | §3.6 (one env var, one flag) |
| 7 | `.claude/agents/overseer.md` | §3.7 |
| 8 | `bootstrap/overseer-cron-prompt.md` | §3.8 |
| 9 | `tests/framework/test_require_overseer_approval.py` | Rewrite the #1426 bypass tests as D1 tests (§6) |
| 10 | `tests/automation/test_pr_review_wrapper.py` | §6; also add `--disposition` to existing overseer calls |
| 11 | `tests/automation/test_pr_review_resolution.py` | `evaluate_reviewer_trigger` with a disposition |
| 12 | `tests/framework/test_rerun_gate_checks.py` | `should_dispatch` cases |
| 13 | `tests/framework/test_overseer_verdict_artifact.py` | Document pins (§6) |
| 14 | `docs/v0.7.0/ADR-1657-AMENDMENT-1-non-merge-reviewer-trigger.md` | **Architect-authored.** Records that AD-3 is superseded for non-merge dispositions (D3) and that #1426 is retired (D2) |

`merge_authority.py`, `github.py`, `require_human_approval.py` and `require-overseer-approval.yml` are
**unchanged**.

---

## 6. Test plan, mapped to the acceptance criteria

All tests are deterministic and make no network calls. `gh` and `github.*` are faked through the
existing seams. Audit writes go to `tmp_path`.

**AC-1: HUMAN_REQUIRED gives exactly one reviewer request on the human and a passing overseer sign-off.**
- W-HR-1 (`test_pr_review_wrapper.py`): `request-reviewer --disposition HUMAN_REQUIRED --tier LOW`,
  on a PR that is not protected and is at or below the ceiling (today this is `no_qualifying_trigger`),
  makes exactly one `request_reviewers` call. It returns `requested: true` and
  `trigger.non_merge_disposition: true`, and writes one `overseer-reviewer-requested` record carrying
  the PR, the head and `disposition`.
- W-HR-2: `submit-verdict --event comment --disposition HUMAN_REQUIRED --expected-action DO_NOT_MERGE`.
  The POST body ends with the visible sentence and exactly one marker line, whose `head` equals
  `pre.head_sha`. One `overseer-interim-signoff` record is written.
- G-HR-1 (`test_require_overseer_approval.py`): an overseer `COMMENTED` review with a marker on head
  H, plus an `APPROVED` on H from a login in the designated set **[ARCH-R1]**, exits 0. Without the human approval it
  exits 1 and stderr contains M3's "Approve the PR on GitHub".

**AC-2: same for PROPOSE_ONLY.**
- W-PO-1 and W-PO-2: as W-HR-1 and W-HR-2 with `PROPOSE_ONLY`. With `--expected-action NO_ACTION` the
  command exits 2. With `--event approve` it exits 3 `disposition_event_mismatch`.
- G-PO-1: as G-HR-1 with `disposition=PROPOSE_ONLY`.

**AC-3: a second cycle on the same head requests and posts nothing new.**
- W-IDEM-1: request-reviewer when the human is already in `requested_reviewers` gives
  `already_requested`, no POST and no audit. When the human already reviewed H it gives
  `already_reviewed_head`. These are the existing guards, now exercised with a disposition.
- W-IDEM-2 (G6): the latest overseer verdict on H is `COMMENTED` with marker `action=APPROVE`. A new
  `submit-verdict` with a **different narrative** and `--expected-action APPROVE`, and the disposition
  flipped from PROPOSE_ONLY to HUMAN_REQUIRED (F10), skips with `interim_signoff_on_head`. There is no
  POST and no audit.
- W-IDEM-3: the same setup but `--expected-action DO_NOT_MERGE` posts. New information is never
  suppressed.
- W-IDEM-4: the latest verdict on H is an empty-body thread container that comes *after* the marked
  verdict. G6 still skips, because containers are not verdicts (F12).

**AC-4: mergeable once the human approves, with no bypass.**
- G-MERGE-1: all three gates are green together on the "HR, merits-type, not protected" row of §4.
  `require_tier_ceiling` is fed the same reviews and passes, because there is no overseer approval.
- R-1 (`test_rerun_gate_checks.py`):
  `should_dispatch("submitted","commented","hos-overseer-hos[bot]","hos-overseer-hos[bot]") is True`.
  The existing `("submitted","COMMENTED")` case with no logins stays `False`, and a human `COMMENTED`
  review stays `False`.

**Constraints:**
- #621. G-621-1: a human approval on H with no overseer review exits 1 (M1). G-621-2: a human approval
  on H with an overseer marked review on an **older** commit exits 1. G-621-3: the old #1426 shape
  (an overseer `COMMENTED` review with no marker, above the ceiling, with a human approval) now
  **exits 1**. This pins D2.
- Forgery. G-FORGE-1: a valid marker inside a review by a human, by `hos-worker-hos[bot]`, or by a
  login equal to the overseer's but with `user.type: "User"` is ignored and exits 1. G-FORGE-2: two
  marker lines in one review fail closed. G-FORGE-3: a marker whose `head` differs from `commit_id`
  exits 1. W-FORGE-1: a body containing `hos:overseer-interim-signoff` exits 2 `body_contains_marker`.
  W-FORGE-2: `--app worker --disposition HUMAN_REQUIRED` exits 3 `disposition_requires_overseer_identity`.
- Revocation. G-REVOKE-1: a marked `COMMENTED` review followed by a later non-empty unmarked
  `COMMENTED` review on H, plus a human approval, exits 1 (M2).
- Ceiling. W-CEIL-1: `--event approve --disposition HUMAN_REQUIRED --tier CRITICAL` still exits 3
  `above_ceiling_approve` (G1 unchanged).
- AUTO_MERGE never summons. W-AM-1: `request-reviewer --disposition AUTO_MERGE` exits 2 through
  argparse. W-AM-2: `--app overseer` without `--disposition` exits 2 on both subcommands.
- **[ARCH-R1] Designated set (replaces G-ASSOC-1).** G-DESIG-1: a non-bot `APPROVED` on H from a
  collaborator who is neither `HUMAN_REVIEWER` nor an `@user` CODEOWNERS owner does not count, and
  the result is M3. G-DESIG-2: `designated_humans` drops `@org/team`, email owners and comment
  lines, and compares logins case-insensitively. G-DESIG-3: with no CODEOWNERS file the set is just
  `{HUMAN_REVIEWER}`. With `HUMAN_REVIEWER` empty as well, the gate exits 2.
- **[ARCH-R1] Event-head binding.** G-HEAD-1: `GITHUB_EVENT_PATH` names commit X, the live head is
  Y, and both carry a valid marker and an approval. The gate exits 1 with the "check belongs to
  commit" message. G-HEAD-2: a malformed event file exits 2. G-HEAD-3: with `GITHUB_EVENT_PATH`
  unset, the live head is used.
- **[ARCH-R1] Dismissal does not resurrect.** G-DISMISS-1: on H, a marked `COMMENTED` review, then a
  later overseer `APPROVED` that is now `DISMISSED`, plus a designated approval, exits 1 (M2).
- **[ARCH-R1] Strict bot type.** G-FORGE-4: an overseer-login review with no `user.type` field is
  not a verdict.
- **[ARCH-R1] Marker only on `comment`.** W-APPROVE-1:
  `submit-verdict --event approve --disposition HUMAN_REQUIRED --expected-action APPROVE --tier LOW`
  posts the body unchanged (no sentence, no marker). It still writes one `overseer-interim-signoff`
  record with `marker_appended: false`.
- **[ARCH-R1] Narrow D-4.** W-FORGE-3: a narrative that contains the words
  `hos:overseer-interim-signoff` mid-line posts normally. A line beginning
  `<!-- hos:overseer-interim-signoff` exits 2, including under AUTO_MERGE.
- **[ARCH-R1] Action-aware sentence.** W-HR-3: `--expected-action DO_NOT_MERGE` appends the
  override sentence, not the "waits only on" sentence.
- Misconfiguration. G-CFG-1: a valid marker with `BOT_ACCOUNTS` empty exits 2. G-CFG-2: an
  unresolvable head SHA exits 2.
- Author. W-AUTH-1: with a disposition, a resolved reviewer that equals the PR author gives
  `reviewer_is_pr_author` and exit 0. Without a disposition it still exits 1.
- Audit failure. W-AUDIT-1: when `write_event` raises after a successful POST, the command exits 0
  with `audit_record: null` and a `not_verified` entry.
- Pure functions. Unit tests cover `parse_interim_marker`, `render_interim_marker` (round trip),
  `latest_overseer_verdict_on_head` (exclusion by `DISMISSED`, `PENDING`, empty body or another
  commit, and `(submitted_at, id)` ordering) and `eligible_human_approvals_on_head`.

**Document pins (`test_overseer_verdict_artifact.py`):**
- every `request-reviewer` and `submit-verdict` example **anywhere** in overseer.md carries
  `--disposition` **[ARCH-R1]**;
- the DIRTY bullet names `--disposition HUMAN_REQUIRED`, and no bounce text names a `--disposition`
  **[ARCH-R1]**;
- the PROPOSE_ONLY bullet's expected action is `APPROVE`;
- the "calibration failure … do not add trigger conditions" sentence is gone;
- the #2170 sentence is present;
- the existing #1557 no-label pin still passes;
- the FABERIX §5 quote pin (F15) still passes.

---

## 7. Risk tier and the merge path of this PR

**Self-assessed tier: HIGH.** The PR changes the logic of a required server-side gate and the overseer's
governance text. It touches protected surfaces: `.claude/agents/**`, `bootstrap/**`,
`scripts/framework/**` and `.github/workflows/**`. A human approval is required at merge
(`require-human-approval`, CODEOWNERS).

**How this PR itself merges.** The gate runs from base, so this PR is judged by today's rule, not
D1.
- If the overseer's verdict is `approve` (protected surface, sound on the merits, HIGH ≤ C), the
  existing F1 path is green, and the human's approval satisfies `require-human-approval`. No bypass.
- If the risk-assessor scores it CRITICAL, today's #1426 bypass covers it after the human approves.
  No bypass.
- **Only if** the overseer posts `comment` at or below the ceiling for a merits reason does this PR hit
  the very gap it fixes. It would then need one final admin bypass, which must be recorded on the PR.

**Blast radius.** Every open PR is judged by the new rule as soon as this merges (D2 transition). A
defect in the new gate could block all merges, and the fallback is admin bypass. Mitigations are the
fail-closed exit-2 paths and the test matrix in §6.

---

## 8. Escalations

**ESC-1 (human; non-blocking unless the human objects).** #1549's open Q2 asks: *"may the posting
wrappers emit a disposition marker?"* This design has `pr_review_cli.py` emit one. It is narrowly a
gate sign-off marker, and the #2174 ruling requires a sign-off that the gate can detect, which this
design reads as answering Q2 **for this purpose**.
- Recommendation: proceed. When #1549 is built, it must reuse the §3.1 marker rather than add a second
  disposition marker.
- Requested act: reply on #2174 with "ESC-1: proceed" or with an objection.

**ESC-2 (human; [ARCH-R1]; must be answered before the implementation PR merges, not before coding).**
Who can satisfy the human side of the interim path? The architect's default, which the coder builds,
is the **designated set** (D6: `HUMAN_REVIEWER` plus the individual CODEOWNERS owners). The
alternative is any non-bot write collaborator, the TD draft's rule. In this repo the two are
identical (`{ScottThurlow}`). In a consumer repo with several collaborators, the default means
(a) only the designated humans can override an overseer `DO NOT MERGE`, and (b) above-ceiling PRs
that a non-designated collaborator approved, which pass today through #1426, will no longer pass.
- Recommendation: designated set. It is the literal reading of "the human CODEOWNER" in the ruling.
- Requested act: reply on #2174 with "ESC-2: designated" or "ESC-2: any collaborator". Changing to
  the alternative is a one-predicate swap in `eligible_human_approvals_on_head` plus the G-DESIG
  tests.

**Architect items: RULED [ARCH-R1]** (see §11 and ADR-1657-AM1):
- A-1. D2 is **confirmed**: #1426 is retired (AM-2), and file 14 is authored.
- A-2. D4 is **confirmed** as the one identity-keyed exception (AM-6).
- A-3. The G6 key is **confirmed**. ARCH-5's single-authority rule holds, and its "never suppress
  changed content" rationale is narrowed for marked sign-offs (AM-3).
- A-4. **Confirmed**: a worker bounce is not a non-merge disposition. **DIRTY is**, and it is now
  explicit (§3.7 item 10, AM-5). There is no `pm-agent` routing, because requirement 3 is met by the
  bounce naming the worker.

**Disclosed, not escalated:**
- D3's effective volume: a request on almost every reviewed PR, because of F9.
- After the human leaves a non-approving review on the head, the request is consumed and not
  re-issued (F7, I2). The human's own review is then the record of who acts next.
- Human-authored PRs. The author cannot approve their own PR, so D1's path needs a second human. This
  is unchanged from today's `require-human-approval`.

---

## 9. Follow-ups (recommended; nothing is filed by this design)

- Align `require_human_approval.py` with D6: bind it to the head SHA and filter by `author_association`.
- Once DEP[#152-followup] replaces the F9 stub, PROPOSE_ONLY becomes rare. Re-measure the request
  volume under D3 at that point.

---

## 10. Startup-gap check and affected sign-offs

*Should this have been settled before code was written against it?* **Partly.** TD-1657 §3.3 shipped
the `comment` verdict for PROPOSE_ONLY and for merits-type HUMAN_REQUIRED at or below the ceiling,
without a gate path to clear them. That is a startup-artifact gap in TD-1657, and the parent
orchestrator should annotate #2174 with `startup-artifact-gap`; this agent did not change labels, as
instructed.

**Affected sign-offs:**
- The #1657 code-review and security sign-offs for `submit-verdict` and `request-reviewer` **stand**.
  The changes here are additive guards and a new flag, and the existing guards G0-G5 and the I2 guard
  are unchanged.
- The #1426 sign-offs on `require_overseer_approval.py`'s bypass are **invalidated**, because that
  path is removed (D2). The security reviewer must re-review the replacement rule (§3.2) as new code.
- The `rerun_gate_checks.py` sign-offs stand for their existing predicate. The new branch is re-reviewed.

---

## Escalation flag (CORE self-flag)

RISK: HIGH. This changes a required server-side merge gate and widens the overseer's reviewer trigger
for non-merge dispositions. It touches protected surfaces.
CONFIDENCE: MEDIUM-HIGH. Every fact in §0 was re-read in the tree on 2026-10-28. One thing remains
unverified. **[ARCH-R1]** The `author_association` dependency was removed by the D6 rewrite. What is
still unverified is whether `github.event.review.user.login` is
populated for App-authored reviews in `pull_request_review` payloads; the documentation says it is, but
it has not been probed.
BLAST RADIUS: every open PR's `require-overseer-approval` result from the moment this merges (D2 transition).
CHANGE CLASSIFICATION: **additive** (a new sign-off path, a new flag and new guards) with one
tightening (#1426 retired in favour of a head-bound equivalent). It is not structural: no component is
added and the merge-authority matrix is untouched.

## Human Review Required

- §3.2 and §4: confirm that "the overseer's latest verdict on the current head carries the marker, plus
  an eligible human approval on the current head" is the rule you want for `require-overseer-approval`.
- D2: retiring the #1426 bypass makes affected open PRs red for one overseer cycle after merge.
- ESC-1 (#1549 Q2 overlap).
- ESC-2 (who counts as "the human" on the interim path) **[ARCH-R1]**.

---

## 11. Architect review, round 1 (2026-10-28): rulings applied in place

The binding record is `docs/v0.7.0/ADR-1657-AMENDMENT-1-non-merge-reviewer-trigger.md`. The
architect made each change below in this document directly; each is tagged **[ARCH-R1]** where it
lands.

**What the draft got right.** Retiring #1426 (F2) is a real soundness fix: an unbound `COMMENTED`
review on an old head plus a new-head approval passes today. Defining the marker once, in the gate
module, and loading it into the writer stops writer/reader drift. Requiring a marker *and* a
head-bound human approval keeps #621's floor. Resolving the head live and failing closed on bad
input is correct. The F11 dispatcher fix is needed: without it, the human-approves-first ordering
leaves the gate red until some unrelated event happens. The scope is 14 files, inside the cap, and
this round adds none: the event head comes from `GITHUB_EVENT_PATH`, and CODEOWNERS is read from the
base checkout that is already present.

**What was unsound and is now fixed:**
1. **The marker landed on `approve` verdicts** (draft §3.4 and §4 row 2). An `APPROVED` review saying
   "this review does not approve the PR" contradicts itself. The marker and sentence are now
   appended on `comment` only, and the audit record carries `marker_appended`.
2. **The human side accepted any collaborator.** That is looser than "the human CODEOWNER" in the
   ruling, and it hands consumer-repo collaborators an override of `DO NOT MERGE`. It is now the
   designated set (D6, AM-4), and the default is confirmed through ESC-2.
3. **The check run was not bound to its own commit.** The head was resolved live only, so a check
   on X could be evaluated against Y. The gate now binds the event head from `GITHUB_EVENT_PATH`
   (§3.2 step 2).
4. **A dismissed later verdict resurrected an earlier sign-off.** `DISMISSED` reviews are now
   candidates, and a dismissed latest verdict fails (§3.2 steps 3-4).
5. **`user.type` was optional.** It is now required to be `Bot`.
6. **D-0 left DIRTY verdicts with no specified disposition**, and some overseer.md examples outside
   step 6 had no `--disposition` (`:517`, `:839`). Without one they exit 2 and the overseer halts.
   §3.7 items 10 and 11 fix both.
7. **D-4's bare-substring test** would refuse any narrative that mentions the marker name. It now
   matches the marker's comment-opener prefix at the start of a line.
8. **The visible sentence said "waits only on a human approval" on a `DO NOT MERGE` sign-off**, which
   invites a rubber stamp. The sentence now depends on the action, and the override (resolving the
   threads, then approving) is spelled out (D1, D7).

**The three gates together (re-checked).** `require-tier-ceiling` is unaffected: there is no new
overseer approval path, and G1 is unchanged. `require-human-approval` is unchanged. On protected
paths, `require_code_owner_reviews` still needs the CODEOWNER. Branch protection's "1 approving
review" is met by the designated human's approval on the D1 path. `required_conversation_resolution`
stays as an independent backstop that the overseer's threads feed. No combination lets a PR merge
without a designated human approving the current head, except the unchanged F1 AUTO_MERGE path. No
combination lets a human approval alone satisfy `require-overseer-approval`.

**rerun_gate_checks change: confirmed.** Its inputs are values GitHub computes, passed through `env`.
It is a dispatcher, not a gate, and it fails toward today's behaviour. The extra dispatches on
overseer thread containers are acceptable.

**Residual risk accepted.** A worker bounce does not revoke an earlier marker on the same head. Draft
status blocks the merge, and a designated approval of that exact commit is still required. So the
worst case is the #621 floor itself.

**Loop state.** Approved in round 1, so no `.claudetmp/design/architect-2174-*` file is kept.

---

## 12. Review round 2 (implementation 6c153857c)

These changes were accepted in reliability review and code-review round 2. Each one is either stricter
than the design or a justified deviation. None of them invalidates a sign-off beyond what §10 already
says. Only the rerun dispatcher's predicate changed, and it is not a required check.

| Item | Change | Where |
|---|---|---|
| Reliability SHOULD_FIX-3 (accepted by code-review round 2 as a justified deviation) | When the overseer login cannot be resolved, a COMMENTED review from a non-empty reviewer now dispatches, with a `::warning::` naming the cause. §3.6 is amended accordingly. This supersedes the "fails toward today's behaviour" wording, both in iteration 1 of §3.6 and in §11's "rerun_gate_checks change: confirmed" paragraph. An empty reviewer login still does not dispatch. | `rerun_gate_checks.py::should_dispatch`, `overseer_login_from_env` |
| `gh` timeouts | Every `gh` subprocess call is bounded by a 30 s timeout (`GH_SUBPROCESS_TIMEOUT_SECONDS`). The workflows set no `timeout-minutes`, so a stalled `gh` would otherwise hold a required check pending indefinitely. | `require_overseer_approval.py`, `rerun_gate_checks.py` |
| Gate timeout handling | In the gate, `subprocess.TimeoutExpired` exits 2 (fail closed, tooling failure). In the dispatcher it becomes a `::warning::`, because the dispatcher has no failure exit (its header contract). | `require_overseer_approval.py::_gh` |
| CODEOWNERS read error | If CODEOWNERS cannot be read while the gate resolves the designated human set (D6), the gate exits 2 (fail closed). It is never treated as an empty set of owners. | `require_overseer_approval.py::codeowners_individual_owners` |
| Audit-write failure | In addition to the `not_verified` entry and `audit_record: null` (§3.5), the CLI prints one stderr line, `pr_review_cli: audit write failed: <scrubbed>`. Exit 0 is unchanged. | `pr_review_cli.py` |
| Reliability SHOULD_FIX-1 | Deferred to #2202. Not addressed in this PR. | — |
