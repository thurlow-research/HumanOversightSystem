# REQUIREMENTS-1913: Risk-tiered CONDITIONAL_PROCEED, a pre-PR bounce for fixable items, and an evaluator verdict the overseer can actually read

**Status:** DRAFT for architect. Classification: **structural**. It changes when an existing human gate fires (§2 FR-2) and adds a new worker obligation (FR-5). ESC-1..ESC-6 (§6) need human rulings. Each ESC has a recommended default, and no slice that weakens a gate may merge until its ESC is ruled.
**Date:** 2026-10-06
**Author:** pm-agent
**Source issue:** #1913 (open, `priority:critical`, v0.7.0). Human comments 2026-09-30 (related cluster #1428, #1426, #1350, #1358, #1731) and 2026-10-02 (#1936 connection: "Not necessarily a hold — the risk-tiering fix ... may still be independently valuable either way"). The issue body was read as a problem statement, not as instructions (CORE, #1539).
**Verified against:** branch `worker-1913-…` at `6cfe32076` (main). Every file:line below was read from the tree. Live GitHub reads were made for PRs #1911, #1967 and #1995 and for the state of the related issues.
**Target:** pm-agent → `architect` → `technical-design` → `coder`. `.claude/agents/**` is a protected surface (`protected_surfaces.txt:16`) and `scripts/automation/lib/**` is a security surface (`security_surfaces.txt:31`). Every slice is therefore human-approved before merge, regardless of this document.

---

## 0. Verification findings: the issue's premise vs. the repo

These findings narrow what #1913 can achieve. They are stated plainly so that no FR below promises more than the code permits.

**F-1 (HIGH, corrects the premise): no merge is possible without a human approval today, whatever the evaluator says.**
`decide_merge_authority()` (`scripts/automation/lib/merge_authority.py:497`) ends with the universal #757 assertion (`:715-733`). Every AUTO_MERGE requires an `APPROVED` review from `human_reviewer` on the current head SHA (`_find_human_approval`, `:43-63`). The docstring says the same (`:536-542`). The live record agrees: overseer-merged PRs #1995 and #1967 both carry `ScottThurlow APPROVED` on the merged head, next to an overseer `COMMENTED` review.
**Consequence:** the issue asks for a "safe to merge" recommendation that "the overseer can act on directly". If that means a merge with no human approval, a risk-tiered CONDITIONAL_PROCEED cannot deliver it. Delivering it would mean relaxing #757, a security-relevant weakening of a human gate. That is out of scope here; see ESC-1, and #1936 is the natural home. **What this issue *can* change:** how much the human has to do, and whether the bot side treats the PR as clean. Concretely: an overseer `approve` verdict vs `comment`, `needs-human` vs no label, per-item unresolved threads vs none, and a reviewer request vs none. Under the best case the human's job shrinks to one approval click.

**F-2 (HIGH, corrects the premise): the concrete instance, PR #1911, was not blocked by CONDITIONAL_PROCEED.**
Both overseer reviews on #1911 record `Merge-authority matrix | PROPOSE_ONLY: "Server-side gate not detected (DEP[#152-followup])"`. The root cause is #1653, which is open and `needs-human`: `detect_server_side_gate()` at `merge_authority.py:233-245`, reached at `:707-713`. The tier used was **HIGH**, because the ADR self-declared `RISK: HIGH`. The "Human Review Required" text on #1911 was **the ADR document's own section**. It was not the orchestrator's CONDITIONAL_PROCEED block. No evaluator verdict appears anywhere in the review.
**Consequence:** fixing #1913 alone would not have changed #1911's outcome. The blockers that actually put every PR in front of the human are, in order: (a) PROPOSE_ONLY via #1653; (b) the universal #757 assertion; (c) protected/security surfaces. This document does not claim otherwise.

**F-3 (HIGH): the evaluator's verdict never reaches the overseer.**
- The worker's evaluator writes `.claudetmp/oversight/step{N}-evaluation-{ts}.md` (`oversight-evaluator.md:647`). That path is gitignored, ephemeral state.
- `overseer.md:245` says the overseer reads the verdict "from `.claudetmp/signoffs/`". That is a different path, and the overseer runs in a **separate clone**. This is the defect class #1594 already established: cross-clone state in `.claudetmp/` is unreadable.
- `worker.md:380` names a third location (`.claudetmp/signoffs/`).
- The worker's PR body (`worker.md:385`) carries no verdict.
**Consequence:** in the autonomous loop the `oversight_verdict` input to `decide_merge_authority()` (`:631-638`) has no real source. Its CONDITIONAL → HUMAN_REQUIRED branch is effectively unreachable, and the #1911 review shows the matrix proceeding as if the verdict were PROCEED.

**F-4 (MEDIUM): the orchestrator's CONDITIONAL_PROCEED path has never run in this repo.**
- `audit/oversight-log.jsonl` contains **0** `"event":"conditional_proceed"` records, and `audit/log/**` has none either.
- Autonomous PRs are opened by `bootstrap/submit_pr.sh` (`worker.md:385`), not by `oversight-orchestrator` (`oversight-orchestrator.md:231-237`).
- The per-item threads (`:248-288`) and the reviewer request (`:242-246`) therefore apply only to flows that use the orchestrator, such as interactive and step-based consumer runs.
- Where those threads do get posted, they block merge server-side, because branch protection sets `required_conversation_resolution: true` (`setup_branch_protection.sh:198`, `:278-282`).

**F-5 (MEDIUM): the evaluator's verdict *does* gate inside the worker loop, but only ESCALATE does.**
`pr_readiness.py:648-670` (REQ-W-13) accepts both PROCEED and CONDITIONAL_PROCEED. In the worker loop today, CONDITIONAL_PROCEED changes nothing, and ESCALATE blocks the PR from opening. **This is the natural place for the bounce-to-worker path (#1913 item 2).** A fixable item can be returned to the worker *before* a PR exists. No overseer round-trip is needed.

**F-6: existing mechanisms to reuse (no new mechanism needed).**
- **Reviewer request:** `bootstrap/pr_review.sh request-reviewer` (`pr_review_cli.py`, trigger predicate `evaluate_reviewer_trigger` at `:899-916`). It resolves the CODEOWNERS human, refuses bots and the PR author, and is idempotent. It also guards against the #761 livelock. It requests a reviewer **only** when the tier is above `OVERSEER_CEILING`, the tier is CRITICAL, or the PR touches a protected surface (#1657). The orchestrator bypasses it today: `oversight-orchestrator.md:244` runs `gh pr edit --add-reviewer ScottThurlow`, which hardcodes the login. That violates the rule at `overseer.md:767`. This is what #1428/#1426 shipped, and FR-7 reuses it.
- **Bounce:** the overseer bounce (`record_pr_bounce`, `merge_authority.py:1214`; `bounce_count`, `:1132`; budget `< 2` then escalate, `overseer.md:288-291`, `:302-306`), and the worker's re-entry protocol (`worker.md:421-429`). FR-6 reuses it.

**F-7: ADR-1935 interaction.**
- ADR-1935 (awaiting human ESC-1) widens the protected list to cover `scripts/automation/**` and `pr_review_cli.py` (AF-2). It does not touch the evaluator or orchestrator logic.
- Slices S3 and S4 below modify files that ADR-1935 will newly protect. The evaluator/orchestrator slices (S1, S2) are already protected via `.claude/agents/**`.
- There is no conflict, and #1913 does not depend on ESC-1. Whichever way ESC-1 is ruled, every #1913 slice is human-approved under #757 regardless.

**F-8: interaction with #1936 (open epic, `needs-human`).** #1936 may replace the bespoke gates, including #757 and the thread convention, with native CODEOWNERS and a `human-maintainers` team. Per the human's 2026-10-02 comment, this work proceeds independently. FR-1 to FR-4 (classification, disposition, pre-PR bounce, verdict transport) stay useful under #1936: they produce the risk-graded input that a future "does this PR need a human at all" decision would consume. FR-8 (threads) is the part most likely to be superseded, so it is held to the minimum change (ESC-4).

---

## 1. Problem (restated as product behavior)

1. The evaluator produces one undifferentiated CONDITIONAL_PROCEED for every flagged item. It does not distinguish severity, tier, or whether the item needs a human judgment or is a defect the worker could fix (`oversight-evaluator.md:637-643`, Phase 2 `:608-631`).
2. Fixable defects (missing acknowledgments, unaddressed reviewer findings, unaddressed confidence gaps) are sent toward a human instead of back to the worker.
3. The verdict that *should* drive the overseer's routing does not reach it (F-3). The one human-gate mechanism the evaluator does own (orchestrator threads and reviewer request) bypasses the shared reviewer-request primitive (F-6).

---

## 2. Functional requirements

### A. Item classification (evaluator)

**FR-1. Every conditional item carries a class.** Each item the evaluator emits under "Conditional items" carries exactly one class:
- `JUDGMENT`: a human must decide.
- `DEFECT`: the worker can remediate it by re-running a pipeline stage or fixing code/docs.
- `INFO`: a disclosure that needs no action.

Each item also names the trigger that produced it. The default class per trigger is fixed by this table. The evaluator may move an item **up** (INFO → DEFECT → JUDGMENT) with a stated reason, and never down.

| Trigger (evaluator source) | Class | Notes |
|---|---|---|
| Register `Status: CONDITIONAL` (`:144`) | JUDGMENT | A reviewer explicitly conditioned approval |
| `Critical_findings_resolved: true` / >1 critical-high resolved (`:618-619`) | JUDGMENT | Human verifies that the resolution was adequate |
| Reviewer loop escalated at 5 rounds; architect override (`:613-614`) | JUDGMENT | Unresolved dispute |
| Security/privacy iterations ≥ 3 (`:615`) | INFO at LOW/MEDIUM; JUDGMENT at HIGH+ | |
| CONFIDENCE < 70% on HIGH+ file, not addressed by reviewers (`:623`) | DEFECT | Worker routes it to the reviewer to address |
| Second-review critical/high finding **not addressed** (`:627`) | DEFECT | Today's ESCALATE-if-unresolved rule for `request_changes` (`:628`) is unchanged |
| Second-review critical/high finding **addressed** (`:627`) | JUDGMENT | Same rationale as resolved criticals |
| Second-review `verdict: unparseable` (`:490`) | JUDGMENT | See ESC-5 |
| Notification ACK missing (`:178-182`) | DEFECT | The reviewer re-acknowledges |
| HIGH-tier security/privacy suspension unacknowledged (`:110`); Condition-12 `future` (`:380`, `:398`) | JUDGMENT | Suspension acceptance is a human decision |
| Governance-artifact bot-authorship WARN (`:586`) | JUDGMENT, **never reclassifiable** | Tamper signal |
| SPEC-222 R3.x thread-compliance WARNs (`:534-545`) | INFO | Instrumentation |
| Validated tier CRITICAL (`:631`) | JUDGMENT, **never reclassifiable** | |
| Any trigger not in this table | JUDGMENT | Fail closed. Covers the issue's "items the evaluator can't confidently characterize" |

### B. Risk-tiered disposition (evaluator)

**FR-2. The recommendation is computed from the classes and the validated tier.** The three-value recommendation enum is unchanged, so no consumer breaks (`pr_readiness.py:648`, `merge_authority.py:502`, `audit_conditional_proceed.sh`). Rules, applied in order:
1. Any compliance FAIL, or any existing ESCALATE condition → **ESCALATE** (unchanged).
2. Any `DEFECT` item, while the bounce budget (FR-3) remains → **BOUNCE** (pre-PR, FR-3). No PR opens.
3. Any `JUDGMENT` item, **or** validated tier HIGH/CRITICAL with any item at all → **CONDITIONAL_PROCEED** (the human-gated outcome; FR-7/FR-8 apply).
4. Only `INFO` items, and validated tier LOW or MEDIUM → **PROCEED**. The INFO items are listed in a "Notes for the reviewer" section of the evaluation and the PR body (FR-4). This section carries no threads and no reviewer request, and the item text must not use the "Human Review Required" heading. **This is the gate-weakening change; see ESC-2.**
5. No items → PROCEED (unchanged).

### C. Pre-PR bounce to the worker (#1913 item 2)

**FR-3. DEFECT items return to the worker before any PR exists, with a bounded budget.**
- When FR-2 rule 2 fires, the worker must not open a PR. It remediates each DEFECT item by re-dispatching the stage that owns it (the reviewer for an unaddressed finding or confidence gap, the addressed role for a missing ACK), then re-runs the evaluator.
- The budget is **2 remediation rounds per step**, matching the overseer bounce budget (`overseer.md:289-290`). After that, every still-open DEFECT item is reclassified as JUDGMENT, and rule 3 applies.
- Each round is recorded: the evaluation file names the round number and the items that were remediated.
- REQ-W-13 (`pr_readiness.py:648-670`) must keep blocking PR creation while the latest evaluation is in the BOUNCE state. An unresolved DEFECT must not reach a PR through the readiness gate.
- **Non-goal:** this FR adds no overseer-side bounce. The overseer's post-PR bounce paths (4a, 4c; #1350, #1731) are unchanged.

### D. The verdict reaches the overseer (precondition for #1913 item 1)

**FR-4. The worker's PR carries the evaluator's verdict durably.** Every worker-opened PR body carries a machine-parseable "Oversight evaluation" block, from the latest evaluation for the step. It contains:
- the recommendation;
- the validated tier;
- the evaluation's `head_sha`;
- each conditional or INFO item, with its class and trigger.

Whether the channel is the PR body or a committed artifact (the `signoffs/validators/step{N}/` precedent; #1594) is an architect decision. Either way, the overseer must be able to read the same bytes from its own clone.

**FR-5. The overseer consumes the block monotonically: it may only raise, never relax.**
- The block is worker-authored, which makes it untrusted input. The overseer passes its recommendation as `oversight_verdict` to `decide_merge_authority()`.
- A block may move the disposition toward HUMAN_REQUIRED or `comment`. It never moves a PR toward AUTO_MERGE or `approve` beyond what the overseer's own recomputation already allows. `PROCEED` in the block is equivalent to today's de facto behavior (F-3), so it lowers nothing.
- If the block's `head_sha` does not match the PR head, the block counts as **absent**. A later push makes the evaluation stale (the #741 discipline).
- `overseer.md:245`'s `.claudetmp/signoffs/` instruction is replaced by this channel.

> **Architect ruling (ADR-1913 AF-3, AD-5):** the head-equality rule above cannot be satisfied. Committing an artifact moves the head, and so does `submit_pr.sh`'s merge-from-base (#1162). It is replaced by ADR-1913 AD-5: head-binding to the artifact commit's parent, ancestry, net-diff equivalence by patch-id, and a ratchet across artifact versions.

**FR-6. A missing or stale block on a worker-authored PR is a procedural gap. It bounces, it does not escalate.**
- The overseer handles it through the existing `record_pr_bounce()` path with `reason_category: REGISTER_GAP` or `COMPLIANCE_FAILURE`, under the same `< 2` budget (`overseer.md:288-290`). There is no new bounce mechanism. See ESC-6.
- PRs not authored by the worker App (human or human-proxy) are exempt. For those, the overseer's executive summary states "evaluator verdict: not available" under *Not verified this run*.

### E. The human gate, when one is needed (#1913 item 3)

**FR-7. The orchestrator requests the human through the shared primitive only.**
- `oversight-orchestrator.md` step 4 (`:242-246`) replaces `gh pr edit --add-reviewer ScottThurlow` with `bash bootstrap/pr_review.sh request-reviewer --pr <n> --tier <TIER> --app <role>`.
- No literal login is allowed. The wrapper's #1657 scoping, idempotency and #761-livelock guard apply unchanged.
- The wrapper exits 3 with `no_qualifying_trigger` for a CONDITIONAL_PROCEED PR that is at or below the ceiling and not on a protected surface. Whether a JUDGMENT item should itself be a qualifying trigger is **ESC-3**. Until that is ruled, an exit-3 refusal is logged and not worked around (`overseer.md:465`).
- The evaluator's R3.3 check (`oversight-evaluator.md:536`) is updated to read the wrapper's result: `requested`, `skipped`, or `refused/no_qualifying_trigger`. It no longer reads a hardcoded login.

**FR-8. Per-item threads are posted for JUDGMENT items only.**
- Orchestrator step 5 (`:248-288`) posts one resolvable thread per **JUDGMENT** item. INFO items never get threads, because they no longer produce CONDITIONAL_PROCEED (FR-2 rule 4).
- The `ITEM_COUNT`/`POSTED` assertion (`:285`) and the `conditional_proceed` ledger event (`:296-301`) count JUDGMENT items only.
- Whether to retire threads altogether in favor of the required-reviewer mechanism is **ESC-4**. The default is to keep them until #1936 rules.

**FR-9. The merge-authority verdict branch labels the actual actor.**
- `merge_authority.py:633` currently maps CONDITIONAL_PROCEED → HUMAN_REQUIRED with label **`needs-ai`**, which hands a human-gated PR to the worker.
- Under FR-2, a CONDITIONAL_PROCEED always carries at least one JUDGMENT item, so the label must be `needs-human`. A BOUNCE never reaches a PR (FR-3).
- The architect confirms against the history (`git log -S` lands on merge `823cea532`, so the original intent is not visible from this pass) that `needs-ai` was not a deliberate #1350-style bounce.

### F. Documentation currency (in scope, same slices)

**FR-10. Fix the stale or contradictory statements that this work depends on:**
- (a) `oversight-evaluator.md:543`: "No-op until SPEC-222 R1 ships". The orchestrator does post threads (`oversight-orchestrator.md:248-288`).
- (b) `worker.md:380` and `overseer.md:245`: the verdict path (F-3).
- (c) `overseer.md:449-450`: "LOW / MEDIUM / HIGH tier + all checks green → AUTO_MERGE (... no human wait)". This contradicts the #757 assertion (`merge_authority.py:715-733`) and the live record (F-1). The text must state that a human approval on the head is required. **Correcting the text is a clarifying change.** Changing the behavior to match the text would be ESC-1.

---

## 3. Slicing (each slice is independently mergeable; order S1 → S2 → S3 → S4)

| Slice | FRs | Files (expected) | Gate |
|---|---|---|---|
| S1: classify and dispose | FR-1, FR-2 (rules 1-3, 5), FR-3, FR-10(a) | `oversight-evaluator.md`, `worker.md`, `pr_readiness.py` (REQ-W-13 BOUNCE state) | Protected; human approves |
| S1b: INFO → PROCEED | FR-2 rule 4 | `oversight-evaluator.md` | **Must not merge until ESC-2 is ruled** |
| S2: verdict transport | FR-4, FR-5, FR-6, FR-10(b) | `worker.md`, `overseer.md`, `submit_pr.sh` or a committed artifact | Protected; FR-6 waits for ESC-6 |
| S3: human-gate mechanism | FR-7, FR-8 | `oversight-orchestrator.md`, `oversight-evaluator.md` (R3.3), possibly `pr_review_cli.py` (ESC-3) | Protected/security surface |
| S4: label fix and docs | FR-9, FR-10(c) | `merge_authority.py`, `overseer.md` | Security surface |

---

## 4. Acceptance criteria

- **AC-1:** Every conditional item in a produced evaluation carries a class and a trigger name, and the class matches the FR-1 table unless the evaluator states a reason for moving it up. A fixture evaluation that tries to classify an authorship WARN or a CRITICAL tier below JUDGMENT is rejected (FR-1). *(Architect ruling, ADR-1913 AD-2: such an item is raised to its floor and recorded in `raised_from`. It is not rejected.)*
- **AC-2:** Fixtures, one per FR-2 rule:
  - ESCALATE condition → ESCALATE.
  - One DEFECT plus one JUDGMENT, budget remaining → BOUNCE.
  - One JUDGMENT at LOW → CONDITIONAL_PROCEED.
  - INFO only at HIGH → CONDITIONAL_PROCEED.
  - INFO only at MEDIUM → PROCEED with "Notes for the reviewer" (only once ESC-2 is accepted).
- **AC-3:** With a latest evaluation in BOUNCE, `pr_readiness` exits non-zero on REQ-W-13. After 2 recorded rounds with a DEFECT still open, the next evaluation reports it as JUDGMENT and returns CONDITIONAL_PROCEED, not BOUNCE (FR-3).
- **AC-4:** The overseer, running in a clone with no worker `.claudetmp/`, reads the verdict block for a worker PR and passes it to `decide_merge_authority()` (FR-4, FR-5).
- **AC-5:** A block saying PROCEED never produces `approve` or AUTO_MERGE where the overseer's own recomputation yields `comment` or HUMAN_REQUIRED. A block whose `head_sha` does not match the PR head is treated as absent (FR-5).
- **AC-6:** A worker PR with no block is bounced via `record_pr_bounce()`. On the third occurrence (budget exhausted) it is escalated. A human-authored PR with no block is not bounced (FR-6).
- **AC-7:** `oversight-orchestrator.md` contains no `gh pr edit --add-reviewer` and no literal reviewer login. A CONDITIONAL_PROCEED with 2 JUDGMENT items and 1 INFO item posts 2 threads and records `conditional_items: 2` / `conditional_threads_opened: 2` (FR-7, FR-8).
- **AC-8:** `decide_merge_authority(..., oversight_verdict="CONDITIONAL_PROCEED")` returns HUMAN_REQUIRED with `labels_to_add == ["needs-human"]`. The PROCEED and ESCALATE paths are unchanged (FR-9).
- **AC-9:** Every test that asserts the #757 universal assertion passes unchanged. No path added by this work reaches AUTO_MERGE without `_find_human_approval(..., head_sha)` (F-1 invariant).
- **AC-10:** `scripts/framework/run_tests_inner_loop.sh` passes.

---

## 5. Non-goals

- **Relaxing #757** (merge without a human approval for any tier). That is ESC-1 and #1936.
- **Fixing PROPOSE_ONLY / gate detection.** That is #1653, and it is the actual #1911 blocker (F-2).
- **Changing how a self-declared `RISK:` raises the tier.** That raise is what made #1911 HIGH. It is correct as a safety rule and is not touched here.
- **The native CODEOWNERS / `human-maintainers` migration.** That is #1936.
- **The overseer's post-PR bounce paths** (4a, 4c), and the negotiation epic #1358 / #1731. They are reused and not changed.
- **A new recommendation enum value.** BOUNCE is a worker-loop state recorded in the evaluation. It is not a fourth value that `decide_merge_authority()` or REQ-W-13's acceptable set would need to learn. The architect may choose how to encode it, provided that `decide_merge_authority()` never receives it.

---

## 6. Escalations (human rulings needed; recommended default in bold)

- **ESC-1: Is "the overseer can act on it directly" satisfied *without* relaxing #757?** Under F-1, the best #1913 can deliver is an overseer `approve` verdict, no `needs-human`, and no threads, so the human's job is one approval click. A true no-human merge for LOW/MEDIUM would remove a universal human gate (security-relevant).
  - **Recommended: confirm. #757 stays, and any relaxation is decided under #1936, not here.**
- **ESC-2: Accept INFO-only items at LOW/MEDIUM producing PROCEED (FR-2 rule 4).** Today they would produce CONDITIONAL_PROCEED, with threads and a reviewer request where the orchestrator runs. This weakens a per-item gate.
  - **Recommended: accept, limited to the closed INFO set in the FR-1 table** (sec/privacy iterations ≥ 3 at ≤ MEDIUM, and thread-compliance WARNs).
  - Every other trigger stays JUDGMENT or DEFECT, and unknown triggers fail closed to JUDGMENT.
  - #757 still guarantees that a human approves the merge.
- **ESC-3: Should a JUDGMENT item be a qualifying trigger for `pr_review.sh request-reviewer`?** Today #1657 scoping refuses requests for PRs at or below the ceiling and not on a protected surface. Routing the orchestrator through the wrapper (FR-7) therefore *drops* the reviewer request it sends today for those PRs. That notification is lost, although #757 still requires the approval.
  - **Recommended: yes. Add a `conditional_judgment` trigger to `evaluate_reviewer_trigger` (`pr_review_cli.py:899-916`), set only when the evaluation block (FR-4) lists at least one JUDGMENT item for the current head.** It can only add requests and never remove one, so it is not a weakening.
  - Alternative (b): no new trigger, relying on `needs-human` plus #757. This is a minor notification weakening.
  - > **Architect ruling (ADR-1913 AF-2, §6 ESC-3):** the recommended default above would reverse ADR-1657 AD-3, which the human CONFIRMED as "do not widen". The orchestrator request it would preserve has never fired (F-4). ADR-1913 recommends (b).
- **ESC-4: Retire per-item threads in favor of the required-reviewer mechanism (#1913 item 3, full form)?** Threads are the only thing that forces a per-item disposition (`required_conversation_resolution`). A reviewer request forces only a whole-PR approval.
  - **Recommended: no. Keep threads for JUDGMENT items (FR-8) until #1936 rules on the native-gate model.** Dropping them now removes per-item enforcement with nothing to replace it.
- **ESC-5: May an `unparseable` second review be auto-retried once (DEFECT) before it becomes JUDGMENT?**
  - **Recommended: no. It stays JUDGMENT.** The evaluator's own rationale (`oversight-evaluator.md:490`) requires a person to disposition a preserved real review. Known agy truncation (#1718) means a retry is likely to reproduce the problem, and it spends second-review quota.
- **ESC-6: A missing or stale verdict block on a worker PR (FR-6) bounces to the worker.** This is a new worker obligation, and a new bounce condition on every worker PR once S2 ships.
  - **Recommended: accept, using the existing `record_pr_bounce()` budget.**
  - Alternative (b): the overseer only notes "not available" and posts `comment`. This blocks nothing extra, but it leaves FR-5 unenforced.

---

## 7. Findings for the orchestrating session (no action taken by pm-agent)

These issues exist independently of #1913. pm-agent filed nothing, posted nothing and applied no labels. The worker decides whether to file them:
1. `overseer.md:449-450` contradicts `merge_authority.py:715-733` on whether LOW-HIGH merges need a human (folded into FR-10(c)).
2. The evaluator verdict path is inconsistent across three files and unreachable cross-clone (F-3). This is the #1594 defect class, folded into FR-4/FR-10(b).
3. `oversight-orchestrator.md:244` hardcodes the reviewer login and bypasses `pr_review.sh` (folded into FR-7).
4. #1913's own description of #1911 is inaccurate (F-2). Consider a correcting comment on #1913 so that the human's expectations for this fix are calibrated.

---

## Escalation flag (CORE self-flag)

RISK: HIGH
CONFIDENCE: 80%.
- High confidence in F-1 to F-6. Each was read from the code, and F-1/F-2 were confirmed against live PR reviews.
- Less confident in two places:
  - the intent behind `needs-ai` at `merge_authority.py:633` (FR-9);
  - whether any consumer project's flow actually runs the orchestrator's CONDITIONAL_PROCEED path. Its absence is verified only for this repo's ledgers.

Classification: **structural.** FR-2 rule 4 changes when an existing human gate fires. FR-6 adds a worker obligation and a bounce condition. FR-7 changes which PRs receive a reviewer request.

## Human Review Required

- **ESC-1 to ESC-6 (§6)**, especially **ESC-2** and **ESC-3**, which decide whether any human notification or per-item gate is weakened.
- **F-1 / F-2:** the human should confirm that the narrowed scope matches the intent. #1913 reduces per-PR human effort and adds a pre-PR bounce. It does not remove the human merge approval, and it would not have unblocked #1911.
