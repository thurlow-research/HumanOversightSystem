# ADR-2209: Every overseer rejection is routed by one pure function. The LLM supplies findings, code decides who gets them. The bounce budget is keyed to the issue, not the PR. A dispute is a worker-only, head-bound `/hos dispute <finding-id>` comment

**Status:** PROPOSED. AD-1 to AD-7 (including AD-5a) are proposed as binding on `technical-design` once the reviews clear. AD-5's ordering of rejections against decisions is PROVISIONAL on ESC-3. ARCH-ESC-1 (the budget window) and ARCH-ESC-2 (a security-class withdraw rule) are open. The human's ruling (no exemption by tier, surface or finding class) is not re-opened here.
**Date:** 2026-10-30 (revision 11)
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #2209 · **Milestone:** v0.7.0 · **Risk tier: HIGH.** Every slice touches protected surface (`.claude/agents/**`, `scripts/automation/lib/merge_authority.py`, `bootstrap/**`, `contract/**`), so the CODEOWNER gate applies.
**Inputs:** the requirements doc; `overseer.md:318-353,499-512,534,683-694,754-758`; `merge_authority.py:44-64,435,846-855,1045,1177-1340`; `merge_authority_cli.py`; `correlation.py`; `comment_format_check.sh:57`; `submit_pr.sh:169-187`; `bin/hos-cron:1289-1295,2237`; `worker.md:422-430`; `contract:440-458`; the #2174 branch diff; ADR-2101 AD-3.

**Consumers:** `technical-design` → `coder` → review chain. `security-reviewer` is mandatory on S1. Edits to `.claude/agents/**` are made by the top-level session, never by `coder` (#1347).

---

## 0. Verification findings (baseline `849908bdc`)

- **VF-1, VF-2, VF-4, VF-5, VF-7, VF-8 CONFIRMED** at the cited lines.
- **AF-1: the bounce cap has never been reachable.** Each bounce lands on a fresh PR key, so #1580's cap of 2 never fires. AD-3 fixes this.
  - **Verified in the tree:** no production code calls `derive_cid` (the grep finds only tests), nothing defines the overseer's cid for a PR, and the worker re-enters through a **new** PR (`worker.md:428`, `bin/hos-cron:2237`).
  - **Corroborating, outside the tree:** while drafting, I read the Overseer clone's audit log (`../Overseer/audit/log`). It held 8 `pr-bounced` events, all with `cid: "pr-<n>"` and `bounce_number: 1`. Reviewers working in the Worker clone cannot reproduce this.
- **AF-2: the `record_pr_bounce` helper has no same-head guard and records no `head_sha`.** Events the overseer writes by hand sometimes carry one (`pr-1760`). Today, idempotency depends on the draft PR dropping out of the overseer's queue.
- **AF-3: there is no CLI for bouncing.** The overseer's bounce calls are improvised Python. Every new step in this ADR goes through a fixed CLI subcommand (D41).
- **AF-4: `human-required` events carry no `cid` or `head_sha`** (`contract:441`).
- **AF-5: the validator-artifact fail-close (`overseer.md:318-324`) routes to HUMAN_REQUIRED**, but the worker can fix it, so under REQ-1(a) it is a rejection.
- **AF-6: `_find_human_approval` (`merge_authority.py:44`) returns the first matching `APPROVED` review**, not the reviewer's latest act.
- **AF-7: `codeowners.py` reads the CODEOWNERS file from the working tree.** On the PR head, the PR author controls that file.
- **#2174 overlap.** The #2174 branch edits `overseer.md` (`:495-520`, `:641-735`, `:788-851`), `overseer-cron-prompt.md:59`, `pr_review.sh` and `pr_review_cli.py`. It does not touch any S1 or S3 file.

**Reuse:** I reuse `bounce_count`'s audit scan, `record_pr_bounce`'s halt ordering, the `escalate_to_human.sh:226` unedited-comment rule, the `--update-pr` authorship check, `BOT_WORKER_USERNAME`, `create_branch.sh`'s ref format, `touches_security_surface`, and ADR-2101 AD-3's default-branch CODEOWNERS read. I found no existing dispute parser, router or PR-to-issue helper.

---

## 1. Organizing principle

**The LLM judges whether something is wrong. Code decides where that judgment goes and when it may take effect.** One pure function, `route_pr()`, turns the findings, the PR facts and the audit history into exactly one disposition. Its inputs are fetched by the CLI, never passed in by the LLM. Merging requires a code-written `route-proceed` record plus `merge-guard`'s live re-checks. Text written by the worker is data, never instructions.

---

## 2. Decisions

### AD-1: Findings use a closed schema. `route_pr()` alone maps them to a disposition. A finding is a rejection unless it carries a well-formed decision. (REQ-1, REQ-2, REQ-6.)

- **Schema** (the CLI validates it and refuses unknown keys): `{class, key, summary, detail, source_url?, decision?: {question, options[≥2]}, conflicts_with?: {reviewer, ref}}`.
  - **`class`** ∈ `PROCEDURAL` (a), `REQUIRED_CHECK` (b), `CHECK` (c), `MERITS` (d), `SCOPE` (e), `REVIEW_FINDING` (f).
  - **`source_url`**, when present, must be `https://github.com/<owner>/<repo>/…` for this repo. Anything else fails the schema.
- **`key`, canonicalized by the CLI:**
  - code-collected findings: `<class>:<check_id>`;
  - `CHECK`: `check:<check-run>:<rule|->:<path>`;
  - `MERITS`, `REVIEW_FINDING` and merits `SCOPE`: `<class>:<path|->:<slug>`, where the path is one of the PR's changed files and the slug matches `^[a-z0-9-]{3,40}$`;
  - the path keeps its case, a leading `./` is stripped, and no line numbers are included.
- **Who produces each class.** Code produces (a), (b), the size counts for (e), and the validator artifact (AF-5); the CLI collects these itself. The LLM produces (c), (d), (f) and the merits part of (e). What counts as blocking is unchanged (§3 non-goal).
- **Decision vs rejection, decided by code.** A finding is a decision only if it has a non-empty `question` and at least two distinct options. `route_pr()` has no tier, surface or security input. For worker PRs, REQ-2 therefore holds by construction, **subject to ESC-3**: under ESC-3(A), non-worker PRs stay on today's path, which is an exemption by author.
- **Residual R-1.** The LLM could dress a rejection up as a decision, or claim a reviewer conflict, to reach the human. Each such escalation is audited with its `trigger`. It costs the human attention, never a merge.
- **Residual R-6 (the same class as R-1).** The worker could dispute findings frivolously to force `upheld-dispute` escalations, either by the overseer's real uphold or by the ruling-missing default (AD-2). The cost is again the human's attention, never a merge. Every dispute and ruling is audited, so the rate is measurable per cid.

### AD-2: A dispute is a worker-only, unedited issue comment. Its reason is untrusted data. A ruling binds only the head it was made on. (REQ-8, REQ-13.)

- **Finding id** = `<head12>-F<k>`. Numbering of `k` continues across every bounce on a head (AD-5 rule 6(e)), so each id is unique and binds its finding to that head.
- **The only source is `GET /repos/{o}/{r}/issues/{n}/comments`.** Review bodies and inline review comments are never read for disputes.
- **A comment counts as a dispute only if all of the following hold** (`parse_dispute`, `scan_disputes(cid)`):
  1. its first non-blank line matches `^/hos dispute (?P<id>[0-9a-f]{12}-F\d+)\s*$`;
  2. a non-empty reason follows;
  3. `user.login == BOT_WORKER_USERNAME` and `user.type == "Bot"`, both read from the payload;
  4. `updated_at == created_at`;
  5. the id names a finding in a `pr-bounced` event for this cid.
- **Which PRs are scanned:** those named by the cid's audit events, open or closed.
- **Refusals are audited, with a cap.** Each refused comment gets one `dispute-refused` event, at most **5 per cid per cycle**. Anything beyond that is folded into one `dispute-refused-suppressed {cid, count}` event. Any commenter can trigger a refusal, so the cap stops them flooding the audit log.
- **The reason is untrusted data** (security MUST_FIX-1, CWE-77/345).
  - The CLI passes the reason to the overseer **fenced** (in a code block labelled `untrusted-worker-text`) and capped at 2,000 characters; anything longer is truncated and marked.
  - `overseer.md` (S2) requires that every `withdraw` cites evidence in the diff or the code (a `path:line` or a check output). The reason alone never justifies a withdraw.
  - A reason that contains instructions (for example "ignore", "approve", "you must", or a role or system framing) is in itself **grounds to uphold**.
  - `dispute-ruling` refuses a `withdraw` unless its `--evidence` is bound to the finding:
    - **`<path>:<line>` evidence.** If the finding's key has a path, `<path>` must be that path; otherwise it may be any changed file. In both cases `<line>` must exist in that file at the head (checked with `GET /contents?ref=<head>`).
    - **`check:<name>` evidence.** It is allowed only for `CHECK` and `REQUIRED_CHECK` keys, and `<name>` must equal the key's check-run name on the head. `merge-guard` still re-checks required checks live (AD-5).
- **Ruling:** `merge_authority.sh dispute-ruling --finding <id> --ruling withdraw|uphold --evidence <path:line|check:name> --reason-file <p>`. It writes `bounce-dispute-ruled`. Code never decides the merits. It refuses a ruling where no valid dispute exists, and a second ruling on the same dispute.
  - **Uphold** → ESCALATE `upheld-dispute` (AD-5).
  - **Withdraw** drops the finding **only on the head the dispute was bound to (H)**. Nothing carries forward automatically.
- **Later heads: a fresh ruling is required, not automatic carry** (codex HIGH, CWE-863). A security finding can depend on callers, configuration or routes outside the named file. On a later head H2 (this PR or a re-entry PR for the same cid), if the overseer raises the same key again:
  1. `route` exits **3 (`ruling-required`)**, listing each such finding with the note "withdrawn on `<head12>`, ruling `<id>`". It writes no bounce and spends no budget.
  2. The overseer rules on it fresh against H2's diff: `dispute-ruling --carry <prior id> --ruling withdraw|reinstate --evidence …`. No new worker dispute is needed.
  3. `--carry` refuses unless the prior ruling was `withdraw` (not uphold, not a human override), and the prior finding has the same key, is LLM-classed and belongs to the same cid. Every call is audited (`bounce-carry-ruled`).
  4. After `withdraw`, the finding is dropped on H2. After `reinstate`, it is an ordinary rejection again, and the worker may dispute it again.
  
  Under option (b) (concede some findings on H, fix the rest on H2), the run converges with no new bounce for the conceded keys. If the overseer does not raise the key again on H2, nothing is suppressed, because there is nothing to suppress.
- **Missing rulings are bounded (liveness; round-5 MUST_FIX-1(a)).** `route` also exits 3 when a valid worker dispute on this cid has no ruling. On the first exit 3 for a given `(head, finding)`, it writes `ruling-pending`. On the **next** cycle for the same head (the second consecutive cycle), if the ruling is still missing, `route` applies a default, writes `ruling-defaulted {cid, head_sha, finding_id, kind, default}`, and continues routing. At most one cycle is skipped.
  - **A missing `--carry` ruling defaults to *reinstate*.** The finding becomes an ordinary rejection, so it is bounced to the worker (or, if it stands alone, it counts toward the cap). The worker stays in control and can dispute it again. No human is involved, because nobody has disagreed yet.
  - **A missing ruling on a worker dispute defaults to *uphold*,** giving `ESCALATE upheld-dispute` with the note "overseer did not rule; finding stands by default". The worker has disputed a finding that still stands, which is a real disagreement (REQ-7(i)). Defaulting to withdraw would let a dispute nobody read drop a finding. Defaulting to reinstate would bounce the dispute straight back to the worker, a loop that only the cap would end.
  
  Both defaults fail toward a defined, audited outcome, never toward a silent skip (the PR #2207 failure).
- **Code-collected keys** are recomputed on every head and are never carried.
- **Veto window, enforced in code and with no class exemption** (security MUST_FIX-1(b)).
  - **When it starts:** the window opens on any head that has a `withdraw` or `--carry withdraw`, **or on any head of a cid with withdrawals earlier in this PR's epoch (AD-3) whose keys the overseer did not raise again on this head**. The `route` CLI posts one visibility comment for that head, then records `withdraw-visible-since {cid, pr, head_sha, merge_base_sha, paths[], comment_id, created_at}`, written by the overseer, where `created_at` is the GitHub timestamp. If the post fails, the CLI exits 1. The comment lists:
    - each withdrawal on this head, with links to the dispute, the ruling and the evidence;
    - **every key withdrawn earlier in this cid's current epoch (AD-3) that is absent from this head's findings**, marked "not re-raised on `<head12>`". This makes a non-re-raise visible, so a trivial push cannot skip the window.
  - **While it runs:** the window blocks only `PROCEED` (AD-5 rule 8). In its place `route` returns `HOLD_VETO`, which posts nothing further and allows no merge. Bounces and escalations go through undelayed, because neither merges. The window lasts until a later cycle runs **and** at least `WITHDRAW_VETO_MIN = 30 min` has passed since `created_at`.
  - **Path-keyed blocks: a hold, or a pending escalation, follows the changed files, not the cid** (security round 2 MUST_FIX-1; codex HIGH, round 8).
    - **Why not the cid:** `detect_human_hold_directive` (`merge_authority.py:120-160`) treats a newer head as superseding a hold (#902), and the cid comes from a branch name the worker writes. A trivial push, or resubmitting the same change under another issue's branch, would escape a hold keyed to either.
    - **`path_hold` (a sticky hold).** A #902 hold by the resolved reviewer, posted on a worker PR P while P had a `withdraw-visible-since` record, becomes sticky.
      - **Paths are recorded when each event is written, never fetched later** (codex HIGH, rounds 9 and 10). Every per-head event the overseer writes for a worker PR stores that head's complete changed-path set `paths[]`. Those events are `pr-bounced`, `withdraw-visible-since`, `path-block-noted` and `human-required`. In addition, `route` writes `head-observed {pr, head_sha, paths[]}` the **first time it sees any head** of a worker PR (codex round 11).
        - **Source of `paths[]`:** it is read once, at write time, from `GET /compare/<merge_base_sha>...<head_sha>`, never from the mutable `pulls/{n}/files`.
        - **What it includes:** every changed, added and **removed** file, plus each rename's `previous_filename`.
        - **Normalization:** paths are normalized (Unicode NFC, a leading `./` stripped, compared case-insensitively) before they are stored or intersected.
        - **Failures:** a failed **or truncated** comparison (a file cap or an incomplete page set) is a read failure. The CLI exits 1 and writes no event.
      - **The hold's scope** is the **union** of `paths[]` across all of P's recorded events from before the hold's `created_at`. It is valid **only if the held head itself is recorded**.
        - **The held head** is P's head at the hold's `created_at`, taken server-side from P's timeline: `committed` and `head_ref_force_pushed` events.
        - **If the held head can't be identified, or has no recorded `paths[]`,** the hold is **unknown-scope**.
        
        A push between the last record and the hold therefore cannot leave the held head's paths out of the scope.
      - **Unknown scope fails closed:** an unknown-scope hold, or an unreadable audit stream, blocks worker merges **across all cids** until the resolved reviewer releases it on P.
      - **Recording and reach:** `route` records `path-hold {hold_comment_id, pr, head_sha, paths[]}`. Any worker PR, on **any branch or issue**, whose changed paths intersect `paths[]` (minus the exclusions below) inherits the hold.
    - **`path_pending_escalation`.** This means an AD-5 `ESCALATE` record only: a `human-required` event that carries a `trigger`. Step-6 final-approval `HUMAN_REQUIRED` (protected surface, CRITICAL, evaluator ESCALATE, merge failure) is **not** included, so two overlapping protected PRs awaiting CODEOWNER approval never block each other (REQ-10).
      - **Effect:** while unresolved, such an escalation on worker PR P gives `HOLD` instead of `PROCEED` (rule 8) on every other worker PR whose paths intersect the `paths[]` recorded in the escalation event. If that set is missing, the block applies across all cids, as for a hold.
      - **Clearing:** a `human-ruled` event, or P merged or closed by a **non-worker** actor. A worker closing P does not clear it.
    - **Excluded paths (`PATH_BLOCK_EXCLUDE`):** shared generated, index or append-only files are never intersected. These are `SCRIPTS-INDEX.md`, `DECISIONS.md`, `audit/**` and `signoffs/validators/**`. Authorization-policy files such as `.github/CODEOWNERS` and `contract/**` are **never** excluded.
    - **No silent stall** (#2207). A path block, whether `route` or `merge-guard` hits it, posts one note per `(PR, head)` naming the blocker (kind, PR, link) and how it clears. It also records `path-block-noted {pr, head_sha, paths[]}`.
    - **Residual R-10 (evasion by moving code):** exact-path blocks can be evaded by renaming, copying or splitting held code into new paths. The fallback is that the moved code is a new diff, which the overseer reviews afresh with no carried withdrawal. That is still stronger than today's #902 hold, which lapses on any push.
    - **Residual R-8 (over-blocking):** unrelated worker work on the same non-excluded files is also blocked, as is every worker PR under the unknown-scope rule. That is the safe direction: the reviewer releases it, or the escalation is ruled on.
    - **Release** of a `path_hold` happens **only on the originally held PR P** (security round 4 SHOULD_FIX-4), and it releases the hold everywhere. The resolved reviewer, after the hold, does one of these on P's current head. Approving a resubmission elsewhere does **not** release the hold.
      - an `APPROVED` review, as `latest_reviewer_act` reads it; or
      - a comment whose first line is `/hos release-hold`. That comment must come from **that reviewer's login**, with `user.type == "User"`, `is_bot_reviewer` false, and `updated_at == created_at`. Nobody else can release the hold.
    - **Enforcement:** AD-5 rule 1 and `merge-guard` both check `path_blocks`. `path_blocks(pr)` returns each block with its kind (`path_hold` or `path_pending_escalation`). An unreadable audit stream, or a failed compare or files read, counts as **blocked**, never released.
  - **It is not a required human step.** When the window lapses with no veto, routing proceeds.
- **Worker obligations (S3).** After a bounce, the worker does one of two things:
  - **(a)** Dispute **every** finding, then mark the bounced PR ready with `submit_pr.sh --ready-pr <n> --app worker`.
    - That command reuses `--update-pr`'s authorship check.
    - It refuses unless every finding has a valid dispute.
    - After marking the PR ready it **removes `needs-ai`** (#1557), and it exits non-zero if the removal fails.
  - **(b)** Fix the findings it accepts, dispute the rest, and open the re-entry PR.

### AD-3: The bounce budget is keyed to the issue, deduplicated by head, and counted in a window that restarts at each escalation. (REQ-7(ii), REQ-12. The window is ARCH-ESC-1.)

- **`bounce_cid(pr)`** returns `issue-<N>` if all of the following hold, checked server-side (**a hard S1 requirement**). Otherwise it returns `pr-<n>` with a WARN.
  1. The PR is authored by `BOT_WORKER_USERNAME` with `type == "Bot"`.
  2. The head ref matches `^worker-(\d+)-`.
  3. Issue N exists, **open or closed**.
- **The earlier lineage clause is dropped** (security round 3, cid detachment). It sent a worker PR without the re-entry line to `pr-<n>`, giving it a **fresh** budget, an escape from the cap. With no automatic carry (AD-2), the budget is all a cid carries. A worker PR that names issue N always shares N's budget, so a worker can only spend its own issue's budget, never reset it. The same PR on later cycles, and any re-entry PR, keep `issue-<N>` without parsing PR text. Dispute scanning reads PR numbers from the audit events.
- **Same-head idempotency:**
  - `pr-bounced` gains `head_sha` and `findings[]`;
  - `human-required` gains `cid`, `head_sha`, `trigger`, `merge_base_sha` and `escalation_created_at` (the GitHub timestamp);
  - on a head that already has a bounce, `NOOP` applies only when no key is new by class and path and no ruling is pending (AD-5 rules 3 and 6(c)). New keys get a further bounce under rule 6(e);
  - `record_pr_bounce` skips a bounce whose keys were all already bounced on that `(cid, head)`.
- **Epoch** (code review round 8 MUST_FIX-1; codex HIGH, round 9). The epoch resets **only** two things: the bounce budget, and the earlier-withdrawn key set used by rule 4's "not raised again" trigger. For a PR, `epoch_start(cid, pr)` is the later of the cid's latest AD-5 `ESCALATE` record (a `human-required` with a `trigger`), and the latest merge or close by a **non-worker** actor (`merged_by`, or the issue events API's `closed` actor) of **another** PR of the cid **before this PR was opened**. Sequential slices therefore start fresh. A concurrent sibling merging does not reset a PR that was already open. A worker closing its own PR resets nothing. `BOUNCE_CAP` stays 2, and all classes share it.
  - **Never cleared by an epoch reset:** live obligations stay bound to their own `(PR, head)`. These are an active veto window, a `path_hold`, a `path_pending_escalation`, and an unresolved ruling or `--carry` obligation. They clear only by their own rules.
- **Residuals:**
  - **R-2:** legacy `pr-<n>` events do not count toward `issue-<N>`, so a PR in flight at cutover can get one extra bounce.
  - **R-3:** the audit log lives in the clone (#1803). If it is unreadable, `route` returns exit 1 or `HOLD`, never `PROCEED`.
  - **R-9:** a sibling PR opened while PR A is still open shares A's epoch, and so its budget, until a non-worker merge or close. At worst that brings an earlier escalation, never a merge.
  - **R-4 (restated accurately):** the worker chooses its own branch name. Filing work under another issue can **gain** bounces, because an unused issue has a fresh budget, which only means more worker iterations. It cannot escape a hold or a pending escalation (both path-keyed), it carries no withdrawal (AD-2), and the overseer reviews the work afresh. The cost is extra cycles before the cap fires; it never produces a merge without a fresh review and, where one applies, the reviewer's act.

### AD-4: One bounce comment lists every finding, with ids, under `### Specific failures`. (REQ-4, REQ-5.)

- **Format:**
  ```
  ## PR bounced to the worker: <n> finding(s) on <head12>
  ### Specific failures
  - [<finding-id>] (<CLASS>) <summary>. <detail or source_url>
  ### How to respond
  Fix each finding, or dispute one: post a comment whose first line is `/hos dispute <finding-id>`, followed by your reason.
  **Reason category:** <category>
  **Summary:** <templated sentence>
  _Bounce #<k> for <cid> (cap: 2 before human escalation)._
  ```
- **Legacy rendering for `failures=` callers:** the same heading and section, with lines `- [<check-id|item-k>] <text>`. It has **no** "How to respond" section and no dispute text.
- **New `reason_category` values**, derived by code: `CHECK_FAILURE`, `MERITS_FINDING`, `SCOPE_SIZE`, `REVIEW_FINDING` and `MIXED`.
- **Expected action** stays `NO ACTION`.

### AD-5: Collect, then route, then gates. (REQ-3, REQ-10. The rejection-vs-decision order is PROVISIONAL on ESC-3.)

- **Step 4R** replaces the bounce logic in steps 3, 3b, 4a and 4c, which become collectors. In order:
  1. collect the code findings;
  2. review the merits and write the findings;
  3. rule on any disputes and carries (AD-2);
  4. call `merge_authority.sh route --pr <n> --findings-file <p>`.
- **`route` exit contract** (security SHOULD_FIX-5):
  - **0:** a disposition was decided. The JSON carries `disposition`.
  - **1:** operational error. Defer, with no post and no merge.
  - **2:** usage error.
  - **3:** `ruling-required` (AD-2). This is bounded: at most one consecutive cycle per head before a default applies.
  
  **Any non-zero exit, and any disposition other than `PROCEED`, means no step 6 and no merge.**
  - On `PROCEED`, `route` writes `route-proceed {cid, head_sha, ts}` before it exits.
  - Immediately before the merge `PUT`, step 6 runs `merge_authority.sh merge-guard --pr <n> --head <sha>`. That command exits 0 only if all of these hold:
    - a `route-proceed` record exists for `(cid, head)`;
    - **live re-checks pass:** the code-collected findings (register, required checks through `check_required_content_checks`, size, validator artifact), `detect_human_hold_directive`, `path_blocks(pr)` and the veto window;
    - where step 6's gate set requires an approval, `latest_reviewer_act` on the head is `APPROVED`. The gate set is: CRITICAL tier, a tier above `OVERSEER_CEILING`, a protected-surface or CODEOWNERS-human-owned path, a security-relevant change (#1253), or an AD-5a escalation on this head.
    
    LLM findings are not re-run by `merge-guard`. They are re-derived by the `route` call in the same cycle, which always runs before step 6.
  - **`merge-guard` has two modes.**
    - **Worker PRs** (author is `BOT_WORKER_USERNAME`) always use the full check above. A `LEGACY` disposition writes no `route-proceed`, so a worker PR sent to `LEGACY` by a sticky or #902 hold can never pass the guard while the hold stands.
    - **Non-worker PRs** (ESC-3(A) `LEGACY`) use legacy mode: no `route-proceed` record is required, but the live #902 hold, the required-check and the approval gate-set checks still apply. A non-worker PR is never blocked just for lacking a `route-proceed` record.
  - **Residual R-5:** `merge-guard` is invoked from the overseer's prose. Making it a required CI check (`require-overseer-approval`) is a follow-up after #2174, which owns that file.
- **`route_pr()` precedence: one flat list, where the first match wins.**
  1. **Legacy.** A `path_hold` applies, a #902 hold exists on this head, or the PR is not worker-authored (ESC-3(A)) → `LEGACY`: today's path.
     - **`path_hold`:** the CLI posts, once per `(PR, head)`, a comment naming the hold and the **originally held PR** as the place to release it: comment `/hos release-hold` there, or approve its current head. An unreadable audit stream counts as **held**; it never releases a hold.
  2. **Escalated head.** An escalation exists for `(cid, head)` → AD-5a: `PROCEED`, `HUMAN_SENDBACK` or `HOLD`. No later rule applies.
  3. **Ruling missing.** A valid worker dispute on this head's findings, or a re-raised key that was withdrawn earlier, has no ruling (or `--carry` ruling) → exit 3. On the second consecutive cycle the AD-2 default is applied, and routing continues.
  4. **Veto window.** This applies when this head has a `withdraw` or `--carry withdraw`, **or** the cid has earlier-withdrawn keys that are absent from this head's findings (AD-2).
     If no window has started yet, post the visibility comment and start the window. Then **continue** in every case. The window affects only rule 8.
  5. **Upheld dispute.** A dispute upheld and not yet escalated, including one upheld by `ruling-defaulted` → `ESCALATE upheld-dispute`. A head with both withdrawn and upheld findings starts its window at rule 4, then escalates here without delay.
  6. **Rejections remain** after dropping the keys withdrawn on **this head**:
     - (a) the resolved `reviewer`'s latest act on this head is `APPROVED` → `ESCALATE reviewer-conflict` (ESC-2(C));
     - (b) a finding carries `conflicts_with` → `ESCALATE reviewer-conflict`;
     - (c) **no new keys** → `NOOP`. A key is *new* unless an earlier bounce on this head already has a key of the same class and path that is still open. The worker owes a fix, or a dispute that will be ruled on (rule 3).
     - (d) `bounce_count >= 2` → `ESCALATE bounce-cap`;
     - (e) otherwise → `BOUNCE` the new keys only, continuing the `F<k>` numbering. Each such bounce counts against the budget.
  7. **Decisions only** → `ESCALATE decision`.
  8. **Clean.**
     - An open veto window → `HOLD_VETO`.
     - A `path_pending_escalation` → `HOLD`, with the one-time note.
     - Otherwise → `PROCEED`. The CODEOWNERS gate, the protected-surface gate, the matrix and step 6 then run unchanged.
  
  There is no shortcut for a head that has already proceeded. Every cycle re-derives the result from live inputs. `route-proceed` is a record, written at most once per `(cid, head)`.
- **Slug stability** (risk-assessor addendum). The LLM could reword a key's slug on unchanged input to manufacture a "new" key. Rule 6(c) therefore compares keys on an already-bounced head by class and path, not by slug, so a reworded slug yields `NOOP`, not a bounce.
  - **Residual R-7:** a genuinely distinct second finding with the same class and path, raised in a later cycle on the same head, waits until that head's earlier key is resolved (fixed on a new head, or withdrawn). The direction is delay, not merge.
- **REQ-10:** `PROCEED` plus `merge-guard` is the only way to a merge. Step 6's CODEOWNER approval and #2174's behaviour are untouched.
- **ESCALATE** posts the trigger, both positions, the findings still open in the window, the options, and the two acts that resolve it. It follows the §8.2 thread, then `record-escalation` (which stores the thread comment's GitHub `created_at`), then `needs-human`. The SPEC-378 halt ordering is unchanged.

### AD-5a: An escalation is resolved only by the resolved reviewer's latest act on the escalated head, made after the escalation's GitHub timestamp. (REQ-9, REQ-10.)

- **Where the inputs come from.** The `route` CLI fetches the PR, every review and the label events itself. It reads `escalation_created_at` from the audit event; that value is GitHub's `created_at`, not the local clock. The overseer passes only `--pr` and `--findings-file`. If any fetch fails, or the audit log is unreadable, an escalated head gets `HOLD`. That never yields `PROCEED`.
- **Reviewer.** This is the login step 6 resolves: the CODEOWNERS owner of the PR's paths, falling back to `HUMAN_REVIEWER`.
  - CODEOWNERS is read **from the PR's base ref** (`GET /contents/.github/CODEOWNERS?ref=<base sha>`), never from the PR head (AF-7).
  - The text-taking parser lives in `merge_authority.py` as `_codeowners_humans_from_text`. It uses the same rules as `requester_trust.codeowners_humans`: teams are skipped and logins compared case-insensitively. It moves to ADR-2101's `parse_codeowners_humans` once that lands. S1 adds no file for it.
- **The act** comes from a new `latest_reviewer_act(reviews, label_events, reviewer, head_sha, since)` helper, not from `_find_human_approval` (AF-6). **First it finds the latest act, then it evaluates it** (codex HIGH, revocation bypass):
  - it scans **all** reviews and label events;
  - **Collect:** the reviewer's reviews, where `is_bot_reviewer` is false, on `commit_id == head_sha`, submitted after `since`, in state `APPROVED`, `CHANGES_REQUESTED` **or `DISMISSED`**; plus `needs-ai` label events by the reviewer after `since`.
  - **Choose:** the latest by `submitted_at` or `created_at`, with ties broken by id.
  - **Evaluate:** a governing review in `DISMISSED` state is a **revocation**, which gives `HOLD` until a fresh qualifying act arrives. A dismissed latest approval never lets an earlier approval govern again.
  - The same helper also backs `merge-guard`'s approval re-check, so a revocation blocks the merge as well.
  
  `_find_human_approval` is left unchanged for the matrix (N-1).

| Latest act | `route_pr()` result |
|---|---|
| `APPROVED` | `PROCEED`. LLM-classed findings are overridden **for this head only**, and the overridden keys are recorded as `human-overruled`. Step 6 merges on that same approval. A human override never carries to a later head |
| `CHANGES_REQUESTED`, or `needs-ai` applied by the reviewer (#1522, `pr-1760`) | `HUMAN_SENDBACK`. No `pr-bounced` event and no budget spent |
| #902 hold directive | `LEGACY` |
| None | `HOLD` (post nothing) |

- **Per trigger:**
  - For `upheld-dispute`, `bounce-cap` and `reviewer-conflict`, approving overrides and sending back upholds the overseer.
  - For `decision`, the review body must contain `Option: <label>` naming one of the escalation's labelled options. Without it, the result is `HOLD`.
- **Code-collected findings** (`PROCEDURAL`, `REQUIRED_CHECK`, size `SCOPE`) cannot be overridden. If any are still open, the result is `HOLD`, with a one-time note per head. It is never a second bounce on that head.
- **The record and crash safety.** `route` writes `human-ruled` (at most once per `(cid, head, escalation)`), then `route-proceed`, and only then exits 0.
  - These are records, not authority. Every run, and `merge-guard`, re-validates the act live.
  - A re-run after a crash returns the same result. If the approval was dismissed in the meantime, it returns `HOLD`.
  - The merge `PUT` passes `sha=<routed head>`.
- **Merge failure is classified by code (`classify_merge_failure`).**
  - **Deterministic** (a 422, a branch-protection refusal, or a 403 that is not a rate limit): recorded once per head as `merge-failed`, followed by the merge-failure path. That head then gets `NOOP`.
  - **Transient** (5xx, a timeout, a network error, a 429, a 403 with `X-RateLimit-Remaining: 0` or a secondary-rate-limit body, or a 405 while mergeability is still being computed): recorded as `merge-attempt-transient` and retried on the next cycle. After 3 such failures on one head, it is treated as deterministic.
  - **409** (the head moved): no record. The next cycle routes the new head.

### AD-6: `REQUEST CHANGES` keeps its enum slot, narrowed by a deterministic `**Trigger:**` line. (REQ-9, REQ-11.)

- **Every ESCALATE body carries `**Trigger:** <upheld-dispute|bounce-cap|reviewer-conflict|decision>`.** The first three map to `REQUEST CHANGES`, and `decision` maps to `DECIDE`. `reason_category` gains `DISAGREEMENT` and `DECISION`; `bounce-cap` uses `FINDINGS_NOT_RESOLVED`.
- **`comment_format_check.sh`** gains `hos_cfc_check_request_changes`: a `REQUEST CHANGES` body must name one of the three arbitration triggers. The check follows the file's existing mode.

### AD-7: Audit. (REQ-13.)

- **Extended:**
  - `pr-bounced`: `head_sha`, `findings[]`, wider categories;
  - `human-required`: `cid`, `head_sha`, `trigger`, `merge_base_sha`, `escalation_created_at`.
- **New events:**
  - `bounce-dispute-ruled`, `bounce-carry-ruled` (with `prior_finding_id` and `evidence`);
  - `dispute-refused` (capped) and `dispute-refused-suppressed`;
  - `withdraw-visible-since`, `path-hold`, `path-block-noted`, `head-observed` (each carries `paths[]`, as do `pr-bounced` and `human-required`);
  - `ruling-pending` and `ruling-defaulted`;
  - `human-ruled`;
  - `route-proceed`;
  - `merge-failed` and `merge-attempt-transient`.
- **What is logged:** ids, URLs, logins, SHAs and GitHub timestamps only. Comment bodies and dispute reasons are never logged. All writes go through `audit_log`, and the halt ordering at `overseer.md:756` is unchanged.

---

## 3. Failure modes

| Failure | Behaviour | Direction |
|---|---|---|
| Findings JSON is invalid, or a `source_url` points off-repo | `route` exit 1, defer | Closed |
| A collector fails, a fetch fails, or the audit log is unreadable | exit 1, or `HOLD` if already escalated. Never `PROCEED` | Closed |
| A dispute from a non-worker, an edited dispute, or a dispute in a review body | refused or ignored, with a capped audit | Closed |
| The dispute reason carries instructions | fenced as data. Instructions are grounds to uphold. A withdraw needs diff evidence | Closed |
| A withdraw lets a PR through in the same cycle | `HOLD_VETO` until the next cycle and at least 30 min. A #902 hold is honoured | Delayed, vetoable |
| The human holds during the window, then the worker pushes a trivial new head, or resubmits under another issue | the hold is path-keyed, so `LEGACY`, and `merge-guard` refuses. The new head's comment lists the keys not raised again | Closed |
| An escalated change is re-filed under a fresh issue | a pending escalation on intersecting paths gives `HOLD` until it is ruled on or closed by a non-worker | Closed |
| A new finding, a red re-run or a hold appears after `route-proceed` | re-derived on the next `route`; `merge-guard` re-checks code-collected findings, checks and holds live | Closed |
| The overseer never issues a ruling or a carry | one skipped cycle, then a default (reinstate, or uphold and escalate), audited | Bounded |
| The latest approval is dismissed, with an earlier approval on the same head | revocation, so `HOLD`, and `merge-guard` refuses | Closed |
| A later head where only a caller or config changed, and the named file is unchanged | the re-raised key needs a fresh `--carry` ruling (exit 3). No automatic suppression | Closed |
| A bot, the human-proxy, or a non-CODEOWNER approves | not the reviewer's act, so `HOLD` | Closed |
| The PR branch edits CODEOWNERS | ignored, because CODEOWNERS is read from the base ref | Closed |
| An approval before the escalation, then a re-approval after it | the latest act wins, so `PROCEED` | Correct |
| The overseer skips `merge-guard` | R-5. Prose-enforced until the CI follow-up | Residual |
| A merge failure is transient | retried, with a cap of 3 | Bounded |

---

## 4. Slices (each ≤15 files including tests)

| # | Slice | Files | Lands after |
|---|---|---|---|
| **S1** | **Code.** Schema and key canonicalization, `bounce_cid` (author, ref, issue exists), `path_blocks` (path-keyed holds and pending escalations), `epoch_start(cid, pr)`, epoch-windowed `bounce_count`, same-head dedup, pure `route_pr`, `latest_reviewer_act`, base-ref CODEOWNERS read (parser in `merge_authority.py`), ruling-missing defaults, dispute parse and scan (fenced reason, refusal cap), ruling and `--carry` with refusals, the veto window, `route-proceed` and `merge-guard`, `classify_merge_failure`, the new bounce comment. CLI subcommands `route`, `bounce`, `disputes`, `dispute-ruling`, `record-escalation` and `merge-guard`. Contract §6a. | `scripts/automation/lib/merge_authority.py`, `scripts/automation/merge_authority_cli.py`, `bootstrap/merge_authority.sh`, `tests/automation/test_bounce_gate.py`, `…/test_route_pr.py` (new), `…/test_bounce_disputes.py` (new), `…/test_bounce_idempotency.py` (new), `…/test_route_resolution.py` (new), `…/test_route_carry_veto.py` (new), `…/fixtures/pr2207_0227Z.json` (new), `…/test_pr2207_replay.py` (new), `…/test_merge_authority_cli.py`, `contract/OVERSIGHT-CONTRACT.md`, `SCRIPTS-INDEX.md`: **14** | none. Disjoint from #2174 |
| **S2** | **Overseer wiring.** Step 4R, the exit contract and `merge-guard` in step 6, the narrowed step-6 "other reasons", the enum text, the `**Trigger:**` line, the rules for untrusted reasons and evidence-backed rulings, the cron prompt, and the format check. | `.claude/agents/overseer.md`, `bootstrap/overseer-cron-prompt.md`, `bootstrap/lib/comment_format_check.sh`, `tests/framework/test_comment_format_check.py`, `tests/framework/test_overseer_rejection_routing_text.py` (new), `DECISIONS.md`: 6 | S1 and #2174; ESC-1/2/3 |
| **S3** | **Worker side.** Re-entry text with finding ids, the dispute act and options (a) and (b); `--ready-pr`; the hos-cron directive text. | `.claude/agents/worker.md`, `bootstrap/worker-cron-prompt.md`, `bootstrap/submit_pr.sh`, `bin/hos-cron` (`:2237` text), `tests/automation/test_submit_pr_ready.py` (new), `tests/automation/test_hos_cron.py`, `tests/automation/test_worker_reentry_format.py` (new): 7 | S2 |

**S1's live effects** (S1 is not inert). For today's 4a/4c callers, as soon as S1 lands:
- the bounce comment switches to the legacy rendering (AD-4);
- `record_pr_bounce` writes `head_sha` and skips a repeated bounce on the same head;
- `bounce_count` uses the window, which makes no practical difference with today's `pr-<n>` keys.

Everything else stays unused until S2 calls `route`. The order is S1 → (#2174) → S2 → S3. ARCH-ESC-2 adds at most one `dispute-ruling` condition, so S1 can be built on (A) now.

**S1 tests, beyond the REQ ACs:**
- **AD-5a resolution:**
  - each trigger with a later approval gives `PROCEED`, and with a send-back gives `HUMAN_SENDBACK`;
  - a pre-escalation approval followed by a later re-approval gives `PROCEED`, because the latest act wins;
  - an act by a bot, the human-proxy or a non-CODEOWNER, a dismissed review, or a review on another head gives `HOLD`;
  - **the revocation regression:** two approvals after the escalation on the same head, the later one dismissed → both `route` and `merge-guard` refuse;
  - the CODEOWNERS text parser gives the same result as `requester_trust.codeowners_humans` on its fixtures;
  - a CODEOWNERS file edited on the PR head is ignored;
  - an approval cannot clear an open `REQUIRED_CHECK`, and the result is `HOLD` with no second bounce;
  - a decision approval with no `Option:` line gives `HOLD`;
  - a crash re-run returns the same result, and gives `HOLD` if the approval was dismissed meanwhile;
  - an unreadable audit log never gives `PROCEED`.
- **cid and budget:**
  - a second cycle on the same PR keeps `issue-<N>`;
  - a re-entry PR keeps `issue-<N>`, even without a re-entry line (no fresh budget), and a closed issue N still gives `issue-<N>`;
  - a borrowed cid inherits no suppression;
  - **held work moved to another issue** (codex): held changes resubmitted on `worker-<other existing issue>-…` → `route` gives `LEGACY` and `merge-guard` refuses. The same holds for a re-filed escalated change (`HOLD`);
  - **sequential slices:** PR A bounces twice, then merges via the overseer. PR B for the same issue gets a fresh budget, and A's withdrawals open no window on B;
  - a PR **closed by the worker** does not reset the epoch, while one closed by a human does;
  - **diff swap** (codex rounds 9 and 10): hold posted, then the worker force-pushes an unrelated diff (or makes the old commit unreachable), then resubmits the original under another issue → the hold's scope is the union of recorded `paths[]`, so the resubmission stays held. With no recorded paths, worker merges are blocked across all cids;
  - a hold on a head newer than the last window record still covers that head's paths, through the union over `pr-bounced` and `path-block-noted`;
  - a held `.github/CODEOWNERS` change resubmitted under another cid stays blocked;
  - **push-to-event gap** (codex round 11): head A recorded, then the worker pushes head B (changing new paths) and the reviewer holds B → B was recorded by `head-observed`, so a resubmission of B's paths under another issue is blocked. If B was never recorded, or the timeline can't identify the held head, the hold is unknown-scope and blocks globally;
  - **path set completeness:** removed files and a rename's `previous_filename` are included; a truncated comparison exits 1; `./a/B.py` and the NFC or case variants of `a/b.py` intersect;
  - `merge-guard` refusing because of a path block posts the same one-time note;
  - **sibling during a window** (codex round 9): B merges or is human-closed while A's veto window, hold or ruling obligation is live → A is unaffected, and A's budget does not reset;
  - **REQ-10:** two overlapping protected PRs, both awaiting CODEOWNER approval in step 6 → neither blocks the other;
  - an `audit/**`-only or `SCRIPTS-INDEX.md`-only overlap does not block; a path block posts exactly one note per head, naming its kind and how it clears.
- **Carry and veto window:**
  - **the codex regression:** only a caller or config file changes and the subject file stays byte-identical, so the re-raised key gives exit 3, and nothing is suppressed without a fresh ruling;
  - **liveness** (with budget remaining and no hold): a missing `--carry` ruling gives exit 3 on cycle 1 and a default reinstate plus `BOUNCE` on cycle 2; an unruled worker dispute gives exit 3 on cycle 1 and `ESCALATE upheld-dispute` on cycle 2; each default writes exactly one `ruling-defaulted`;
  - **option (a) on the same head:** all findings disputed, the PR marked ready and every finding withdrawn → not `NOOP`; it goes to `HOLD_VETO` (rule 4 posts the comment, rule 8 returns `HOLD_VETO`), then `PROCEED` on a later cycle, and never a second bounce;
  - evidence `check:<name>` for a check that is not on the head is refused;
  - `--carry` refuses an upheld, human-overruled, different-key, code-collected or other-cid prior ruling;
  - **option (b) round trip:** F1 withdrawn on H, re-entry PR H2, `--carry withdraw` gives no bounce, then `HOLD_VETO`, then `PROCEED` on a later cycle;
  - a #902 hold posted during the veto window gives `LEGACY` (rule 1).
  - **Checked against the final rule list:** codex regression → rule 3; liveness defaults → rule 3, then 6(e) or 5; option (a) → rule 4 (window started), then 8 (`HOLD_VETO`, later `PROCEED`); a mixed withdrawn and upheld head → rule 4, then 5 with no delay; option (b) → rule 3 (ruled), then 4, then 8; non-re-raise push → rule 4.
- **Disputes and input safety:**
  - a reason containing instructions is fenced and truncated;
  - `withdraw` without evidence is refused;
  - the refusal cap writes 5 events plus one suppressed-count event;
  - an off-repo `source_url` is rejected.
- **Merge path:**
  - `merge-guard` without a `route-proceed` record exits non-zero, and so does `merge-guard` when, after `route-proceed`, a required check turns red on the same SHA or a hold is posted;
  - **sticky hold:** hold on H during the window, then a worker push to H2 (or another PR touching the same paths) → `LEGACY`, and `merge-guard` refuses. `/hos release-hold` from a bot, the human-proxy, another human or an edited comment does not release it, nor does an approval on the old head. The reviewer's release or approval on H2 of the held PR does; an approval of a different PR that inherited the hold does not. The release instructions are posted once per head, and an unreadable audit stream counts as held;
  - **`merge-guard` modes:** a worker PR in `LEGACY` refuses; a non-worker `LEGACY` PR with green checks, no hold and any required approval passes without `route-proceed`;
  - H2 does not raise again a key withdrawn on H → the comment lists it as "not re-raised", and the window opens on H2;
  - **evidence binding:** these are refused: a path other than the key's path, a line past the end of the file, a `check:` name other than the key's check, and `check:` evidence on a `MERITS` key;
  - **rule 6(e):** a key with a new class or path on an already-bounced head gives a further bounce numbered `F<k+1>…` and spends budget; a re-run gives `NOOP` (rule 6(c)); a reworded slug with the same class and path gives `NOOP` (slug stability);
  - the merge-failure table, including a 403 rate limit compared with a 403 refusal, and a 405 that retries up to 3 times.

---

## 5. Positions on pm-agent's escalations

| ESC | Architect | Gates |
|---|---|---|
| ESC-1 | **Concur (A)** for this build. (B) would need a new `pr_review.sh` operation in a file #2174 is rewriting. **It affects your review queue, so it is your call.** | S2 |
| ESC-2 | **Concur (C).** AD-5 rule 6(a); your re-approval resolves it (AD-5a). | S2 |
| ESC-3 | **Concur (A)**, which AD-3's cid rule depends on. Rejections go to the worker before any decision is escalated. | S1, S2 |

**ARCH-ESC-1 (the budget window). Recommended: (A),** where the epoch also restarts after each escalation. Under (B) it restarts only when a PR of the issue is merged or closed by a non-worker (AD-3), so every later rejection on that slice comes straight to you. **This sets how often you are engaged, so it is your call.** It gates S1's `bounce_count`, and switching between the two is a one-line change.

**ARCH-ESC-2 (an extra withdraw rule for security findings). No recommendation; it is your call.** Should withdrawing a finding on a security surface (`touches_security_surface`) need more than the veto window, for example your approval, or a ban on withdraw? **(A) No:** the veto window, the sticky hold and the visibility comment apply to every class equally, which matches your "no exemption by class" ruling. **(B) Yes:** that is a class-based exemption, which only you can authorize. Under (B), S1's `dispute-ruling` gains one extra refusal condition.

**WITHDRAW_VETO_MIN (30 min)** sets how long you have to veto a withdrawn finding before it takes effect. It delays merges but adds no human step. It is noted here for your awareness; I do not need a ruling unless you want a different value.

---

## 6. Product boundary, startup gap, affected sign-offs

- **Product consequences, routed to you:** ESC-1 to ESC-3, ARCH-ESC-1 and ARCH-ESC-2; path-keyed holds and pending-escalation blocks (with R-8 over-blocking) and `/hos release-hold`; the `/hos dispute` act and `--ready-pr`; the `**Trigger:**` line; the veto-window delay on merges after a withdraw; and the ruling-missing defaults (AD-2).
- **Operational:** no new service or credential. About 11 new audit event types, holding only public ids and timestamps. One comment read per bounced PR in the cid, per cycle.
- **Startup gap: yes (AF-1).** #1580's cap assumed a stable cid that nothing ever produced. **Recommendation:** annotate a `startup-artifact-gap` issue (not filed here).
- **Sign-offs needing re-review:** #1580's 4c sign-offs (their cap claim was never true) and SPEC-378's schema sign-offs (AD-7 adds fields and events). **#2174's sign-offs stand.**
- **N-1 → pm-agent.** `_find_human_approval`'s first-match behaviour (AF-6) also affects the matrix's #589 and #757 checks, including the revocation case. `merge-guard` covers it for routed PRs; fixing the matrix itself is out of scope, so I am naming it rather than fixing it.

---

```yaml
adr: ADR-2209
status: PROPOSED
issue: 2209
codable_now: [S1]
design_now_merge_after: {S2: [S1, "#2174", ESC-1, ESC-2, ESC-3], S3: [S2]}
hard_constraints_not_waivable: ["REQ-2 (no tier/surface/class exemption; subject to ESC-3 author scoping)", "AD-2 actor rule + untrusted-reason handling", "AD-2 no automatic carry", "AD-2 veto window", "AD-5 exit contract + merge-guard", "AD-5a latest-act, base-ref CODEOWNERS, GitHub timestamps"]
s1_security_review_items: ["R-5 merge-guard as a required CI check (post-#2174)"]
escalations:
  - {id: ESC-1, recommended: A, gates: [S2], note: inbox}
  - {id: ESC-2, recommended: C, gates: [S2]}
  - {id: ESC-3, recommended: "A; rejections before decisions", gates: [S1, S2]}
  - {id: ARCH-ESC-1, options: {A: window-resets-at-escalation, B: never-resets}, recommended: A, gates: [S1]}
  - {id: ARCH-ESC-2, options: {A: no-class-rule, B: extra-security-withdraw-rule}, recommended: none, gates: [S1], note: class exemption is human-only}
```

## Escalation flag (CORE self-flag)

RISK: HIGH. `route_pr()`, `--carry` and `merge-guard` decide whether a finding reaches the human or blocks a merge, on protected surfaces.
CONFIDENCE: HIGH on AF-2 to AF-7 and the #2174 overlap, all verified in the tree. MEDIUM on AF-1's production evidence, which comes from the Overseer clone and cannot be reproduced from the Worker clone; the in-tree half (no `derive_cid` caller, re-entry by a new PR) is verified. MEDIUM on residual R-1's rate and on R-5 until the CI follow-up lands.
BLAST RADIUS: the overseer's handling of every worker PR, worker re-entry, the audit schemas, one format check and one new `submit_pr.sh` mode. Approval, branch protection and CODEOWNERS are unchanged.
Change classification: STRUCTURAL.

## Human Review Required

ESC-1, ESC-2, ESC-3, ARCH-ESC-1 and ARCH-ESC-2 need your answer from your own account before S2 merges. ARCH-ESC-1 and ARCH-ESC-2 also need it before S1 is final. S1 may be designed and built now. Your approval of each protected-surface PR is the final gate.
