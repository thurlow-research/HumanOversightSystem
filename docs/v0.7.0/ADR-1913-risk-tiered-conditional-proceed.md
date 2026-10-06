# ADR-1913: Risk-tiered CONDITIONAL_PROCEED. A deterministic disposition module, a pre-PR bounce, a committed head-bound verdict artifact the overseer can only be raised by, and a verdict gate that a human approval can actually satisfy

**Status:** ACCEPTED FOR DESIGN. AD-1 to AD-12 bind `technical-design`. Five human rulings are open (§6). Each slice in §5 names the ESC, if any, that gates its **merge**. No ESC blocks design or build of any slice.
**Date:** 2026-10-06
**Author:** architect
**Issue:** #1913 (`priority:critical`, v0.7.0).
**Input:** `docs/v0.7.0/REQUIREMENTS-1913-risk-tiered-conditional-proceed.md` (pm-agent, 2026-10-06). F-1 to F-8 there are confirmed unless §0 says otherwise.
**Verified against:** branch `worker-1913-…` at `18c563425` (main `6cfe32076` plus the requirements commit). Every file:line below was read from the tree in this pass.
**Consumers:** `technical-design` → `coder`, `security-reviewer`, `code-reviewer`, and the human approver of each slice.
**Out of scope:**
- relaxing #757 (any merge without a human approval);
- PROPOSE_ONLY / server-side gate detection (#1653);
- the native-CODEOWNERS / `human-maintainers` migration (#1936);
- the overseer's post-PR bounce paths 4a/4c and the negotiation epic (#1358/#1731).

---

## 0. Verification findings

### 0.1 Confirming pm-agent

- **F-1 confirmed.** `decide_merge_authority()` (`merge_authority.py:497`) ends in the #757 universal assertion (`:715-731`). No #1913 outcome can merge without `_find_human_approval(reviews, human_reviewer, head_sha)`.
- **F-3 confirmed.** The verdict path is named three different ways (`overseer.md:245`, `worker.md:380`, `oversight-evaluator.md:647`) and none of them is readable cross-clone. No production code passes `oversight_verdict` to `decide_merge_authority()`: the only caller is the overseer agent's prose (`overseer.md:310`), and `grep` finds no other call site that sets the argument.
- **F-5 confirmed, and it is stronger than stated.** `_check_evaluator_verdict` (`pr_readiness.py:650-670`) fails closed on **any** value outside `{PROCEED, CONDITIONAL_PROCEED}`. A `BOUNCE` value already blocks PR creation with no new code path.
- **F-6 confirmed.** `oversight-orchestrator.md:244` hardcodes `--add-reviewer ScottThurlow`.

### 0.2 My own findings (these change the design)

**AF-1 (HIGH): transporting the verdict without changing the gate would deadlock every CONDITIONAL_PROCEED PR at or below the ceiling.** F-3 currently hides this.
- `merge_authority.py:632-638` returns HUMAN_REQUIRED for any non-PROCEED verdict. It does this **before** any human-approval check (`:656-695`) and before #757 (`:715`). A human approval on the head therefore never clears a CONDITIONAL_PROCEED.
- Approve-eligibility condition 4 (`overseer.md` § Verdict events, :587) lets the overseer post `approve` only when "the oversight verdict is PROCEED". At or below the ceiling, the overseer would therefore post `comment` forever.
- `require-overseer-approval` (`require_overseer_approval.py:1-33`) requires an overseer APPROVED review. Its #1426 bypass applies **only above** the ceiling.
- **Net effect:** the moment the verdict reaches the overseer, a LOW–HIGH CONDITIONAL_PROCEED PR cannot merge except by admin override, even after the human approves. The `needs-ai` label (`:633`) meanwhile hands it to a worker that cannot clear it.
- The gate fix (AD-6) **must merge before** transport (AD-4/AD-5). This is a hard ordering constraint in §5.

**AF-2 (HIGH): pm-agent's ESC-3 default reverses a human-confirmed ruling.**
- `evaluate_reviewer_trigger` (`pr_review_cli.py:899-916`) cites "ADR-1657 AD-3 — CONFIRMED, do not widen". ADR-1657 AD-3 (`:130`) records the human confirmation.
- Adding a `conditional_judgment` trigger is a widening. Only the human can reverse that confirmation, so an architect default cannot recommend it as if it were neutral.
- The "lost notification" ESC-3 is meant to protect is also theoretical. F-4 found 0 `conditional_proceed` events ever recorded, so the orchestrator's hardcoded request has never fired in this repo.

**AF-3 (HIGH): FR-5's staleness rule ("`head_sha` must equal the PR head") cannot be satisfied by any channel.**
- Committing the artifact moves the head past the evaluated commit.
- `bootstrap/submit_pr.sh` merges the base into the branch before every push (#1162), so the head moves again after evaluation even if nothing is committed.
- A literal head-equality rule would mark every artifact stale. The replacement is AD-5's net-diff-equivalence rule.

**AF-4 (MEDIUM): the recommendation that REQ-W-13 gates on is LLM-authored text today.** `pr_readiness.py:662` regex-parses `**Recommendation:**` from the evaluator's markdown. Classification (FR-1) and disposition (FR-2) only become trustworthy if the rules are code. The model must not both classify an item and decide what the classes imply.

**AF-5 (MEDIUM): in the autonomous loop, nothing surfaces the conditional items at all.**
- FR-7/FR-8 change the orchestrator, but autonomous PRs never go through it (F-4).
- Without AD-7, every JUDGMENT item in a worker PR would be invisible to the human, just as it is today.
- The overseer's existing HUMAN_REQUIRED path already posts one resolvable escalation thread (`overseer.md:465` (4)). That thread is the surface to reuse.

**AF-6 (LOW, resolves FR-9's open question): `needs-ai` at `:633` is not deliberate.**
- It arrived in merge `823cea532` (#1582, a gates per-job split that has nothing to do with verdict routing).
- No ADR, TD or DECISIONS entry mentions it, and no test asserts it (`grep` over `tests/`).
- The only later mention is `fa6e2dcee` (#1703), which cites it as a PR-side occurrence without endorsing it. It is ruled an error (AD-6).

**AF-7 (MEDIUM): FR-2's tier input is unspecified.** If the evaluator passes its own idea of the "validated tier", it can understate the tier and shift rule 3/rule 4. The module takes the maximum of the declared tier and the deterministic validator output (AD-2).

---

## 1. Context after §0

#1913 cannot deliver a no-human merge (F-1, ESC-1). It can deliver four things:
1. Fixable defects go back to the worker before a PR exists (FR-3).
2. The human sees, on the PR, exactly which items need a human judgment, and nothing that does not (FR-1, FR-2, AD-7).
3. Clean PRs get an overseer `approve`, so the human's job is one click. Conditional PRs get `comment` plus the item list until the human approves, and then the overseer merges (AD-6).
4. The orchestrator stops hardcoding a login (FR-7).

The design rule throughout: **the evaluator (a model) proposes items; deterministic code disposes; the overseer treats every worker-authored artifact as an input that can only raise its decision.**

---

## 2. Decisions (BINDING on `technical-design`)

### AD-1: Scope is the F-1 narrowing. #757 is untouched.
- No change in any slice may add a path to `MergeDecision.AUTO_MERGE` that does not pass through `_find_human_approval(reviews, human_reviewer, head_sha)`.
- Every existing #757 test passes unchanged (AC-9).
- The human confirms this scope as part of ESC-1. Until then, design and build proceed on this basis.

### AD-2: Item classification and disposition live in one deterministic module, `scripts/framework/evaluation_verdict.py`. Agent prose only cites it. (FR-1, FR-2, AF-4, AF-7.)

**Placement.**
- `scripts/framework/**` is protected by construction (ADR-1935 §2 "Directory homes"). The module is P1: its output decides approve, escalate or bounce.
- It is importable as `scripts.framework.evaluation_verdict`, by the same namespace-package idiom `probe.py:39` uses for `scripts.framework.requester_trust`.
- It is stdlib only. It imports nothing from an unprotected module (ADR-1935 P2).
- CLI: `python -m scripts.framework.evaluation_verdict {dispose|publish|read}`.

**What the model supplies.** The evaluator emits one JSON item list per evaluation, at `.claudetmp/oversight/step{N}-evaluation-items-{ts}.json`. Each item has:
- `trigger`: a member of a closed enum;
- `declared_class`;
- `text`;
- `evidence`: a register role and field, a ledger check id, or a file:line;
- `reason`: required when `declared_class` is above the floor.

The evaluator also emits `escalate_conditions[]` (Phase 1 FAILs and the existing ESCALATE rules) and `declared_tier`.

**What the module decides.**
1. **Floors.** The FR-1 table is encoded as data. Class is `max(floor(trigger, tier), declared_class)`, ordered INFO < DEFECT < JUDGMENT.
   - A declared class below the floor is **raised, not rejected**. The module records `raised_from` (this refines AC-1). Erroring would lose the evaluation, and raising is the fail-safe direction.
   - `governance_bot_authorship` and `validated_tier_critical` are fixed at JUDGMENT.
   - Any trigger not in the enum becomes `other` → JUDGMENT.
2. **Tier.** `validated_tier = max(declared_tier, tier from the validator summary)`. The validator summary is the committed `signoffs/validators/step{N}/summary.json` if present, else `.claudetmp/oversight/validators/summary.json`, reading `tier` and `tier_floor`. If no summary is readable, the tier is HIGH (fail closed for rule 3/4).
3. **Rules.** FR-2's rules are applied in order. Rule 4 (INFO-only → PROCEED) is **compiled in but disabled** until ESC-2 (S1b flips it, AD-10). While it is disabled, INFO-only yields CONDITIONAL_PROCEED, which is today's behaviour.
4. **Budget** (AD-3).

**Trigger enum.** `technical-design` finalizes the names, one per FR-1 row: `register_status_conditional`, `critical_findings_resolved`, `reviewer_loop_escalated`, `architect_override`, `secpriv_iterations_ge3`, `confidence_gap_unaddressed`, `second_review_finding_unaddressed`, `second_review_finding_addressed`, `second_review_unparseable`, `notification_ack_missing`, `suspension_unacknowledged`, `condition12_future`, `governance_bot_authorship`, `thread_compliance_warn`, `validated_tier_critical`, `other`.

**Output.** `dispose` writes `.claudetmp/oversight/step{N}-disposition-{ts}.json` containing:
- `recommendation`: PROCEED | CONDITIONAL_PROCEED | ESCALATE | BOUNCE;
- `validated_tier`;
- `bounce_round`;
- `items[]` with the final class;
- `head_sha`, `base_sha`;
- `module_version`.

`dispose` also renders the recommendation line into the evaluation markdown for humans. The JSON is authoritative.

**REQ-W-13** (`pr_readiness.py:650-670`) reads the latest disposition JSON for the step instead of regex-parsing markdown. Its acceptable set stays `{PROCEED, CONDITIONAL_PROCEED}`, so BOUNCE and ESCALATE fail it. If no disposition is present, REQ-W-13 fails.

**Agent prose.** `oversight-evaluator.md` Phase 2, the taxonomy and the Output section cite the module and the enum. They never restate the floor table, which would let the two drift.

### AD-3: BOUNCE is a worker-loop state that never leaves the worker clone. (FR-3, §5 non-goal.)
- `BOUNCE` appears only in the `.claudetmp` disposition record. `publish` (AD-4) refuses to write any recommendation other than PROCEED or CONDITIONAL_PROCEED. The `read` side (AD-5) treats any other value as `invalid`. `decide_merge_authority()` therefore never receives it.
- **Budget.** `bounce_round` is computed by the module as the number of prior BOUNCE dispositions for this step and cid in `.claudetmp/oversight/`. While `bounce_round < 2`, DEFECT → BOUNCE.
  - At 2, every remaining DEFECT is raised to JUDGMENT with `raised_from: DEFECT` and reason `bounce_budget_exhausted`, and rules 3–5 apply.
  - If `.claudetmp` is lost, the count resets. That is an accepted residual (R-3), bounded by the cycle's existing wall-clock and failure breakers.
- **Remediation.** The worker re-dispatches the owning stage: the reviewer for a confidence gap or an unaddressed finding, the addressed role for a missing ACK. It commits after each stage (worker.md cycle discipline), then re-runs the evaluator and `dispose`.
- **A bounce never re-runs second review.** `second_review_finding_unaddressed` is remediated by the owning reviewer addressing the finding, after which it is `second_review_finding_addressed` (JUDGMENT). Re-running agy or codex inside a bounce is not authorized: it spends the reserved quota and, per #1718, reproduces truncation.
- This is the bounce the issue explicitly asked for (#1913 item 2), so the product request is already in the issue and it is not a new ESC. Its cost is bounded at 2 reviewer re-dispatch rounds per affected step.

### AD-4: Transport is a committed, per-branch artifact: `signoffs/evaluations/<namespace>/evaluation.json`. The PR body is rejected as a channel. (FR-4, F-3.)
- `<namespace>` is the per-branch slug from `signoff_namespace()` (`scripts/oversight/sign_off.sh:57-62`, #968). Two concurrent PRs never share a path, and a step number shared across PRs (#1170's checkpoint problem) cannot collide.
- `publish` copies the latest disposition into this path in the stable schema `hos.evaluation-verdict/1`. It contains:
  - `step`, `cid`, `namespace`;
  - `head_sha`: the evaluated commit;
  - `base_sha`;
  - `validated_tier`;
  - `recommendation`;
  - `bounce_rounds_used`;
  - `items[]` with `trigger`, `class`, `raised_from`, `text`, `evidence`;
  - `module_version`.
- The worker commits it as the **last commit before** `bootstrap/submit_pr.sh` (new `worker.md` step 8.6, between 8.5 and 8.7). REQ-W-13 additionally checks that the committed artifact exists and that its `head_sha` equals `HEAD^`. That check is the worker-side self-test of AD-5 rule (b).
- **No change to `bootstrap/submit_pr.sh`** and no PR-body block. The requirements' S2 file list is overruled here.
- Cost: one extra file per PR, which counts toward `docs/PR-SIZE-POLICY.md`. It also accumulates under `signoffs/evaluations/` on `main`, as the stamps already do. That is accepted: it is the durable, post-squash audit record that the research instrument needs.

### AD-5: The overseer reads the artifact through `evaluation_verdict read`. The result can only raise the overseer's decision. (FR-5, AF-3.)

`read --pr-head <sha> --base <ref> --namespace <ns>` (the namespace is derived from the PR head branch name) returns `{status, recommendation, judgment_items[], info_items[], detail}`. `status` is one of `valid`, `absent`, `stale`, `invalid`.

The artifact is **valid** only if all of the following hold:
- **(a) Present in the PR's own commits.** At least one commit in `merge-base(base, head)..head` touches the path. A copy inherited from base does not count.
- **(b) Head-bound.** `artifact.head_sha == artifact_commit^`, where `artifact_commit` is the last such commit (the overseer.md 3b precedent).
- **(c) Ancestry.** `artifact_commit` is an ancestor of the PR head.
- **(d) Net-diff equivalence (replaces FR-5's head-equality rule; AF-3).** The PR's net change as evaluated must equal its net change now:
  - patch-id of `git diff merge-base(base, artifact.head_sha) artifact.head_sha`, equal to
  - patch-id of `git diff merge-base(base, head) head`,
  - both computed with `git patch-id --stable` and excluding `signoffs/**` and `audit/**`.
  - A merge-from-base that changes nothing in the PR's own diff keeps the artifact valid.
  - A conflict resolution, a fix push, or any edit to a non-excluded path makes it `stale`. This is the #741 discipline, made robust to #1162's merge.
- **(e) Schema.** `schema` is `hos.evaluation-verdict/1`, and `recommendation` is in `{PROCEED, CONDITIONAL_PROCEED}`. Anything else is `invalid`.

**Ratchet (tamper control).**
- The **effective** recommendation is the most restrictive across **every version** of the artifact committed in `merge-base..head`, ordered PROCEED < CONDITIONAL_PROCEED.
- A worker that commits CONDITIONAL_PROCEED and later commits PROCEED does not clear the JUDGMENT items. Only a human approval clears them (AD-6).
- `judgment_items[]` comes from the latest version. When the ratchet fires, the module also returns the earlier version's items, labelled `withdrawn_by_later_evaluation`, so the human sees them.

**Mapping to `oversight_verdict`.**
- `valid` → the effective recommendation.
- `absent`, `stale`, `invalid` → `PROCEED`, with `detail` recorded under *Not verified this run* in the executive summary.
  - This equals today's de facto input (F-3), so absence lowers nothing.
  - Whether absence on a worker PR additionally **bounces** is ESC-5 (AD-9).

**Monotonicity argument (why a worker-authored artifact can never loosen the overseer).**
- Today the effective verdict input is PROCEED. Under AD-5 every outcome is either PROCEED or more restrictive.
- AD-6's only "clearance" for CONDITIONAL_PROCEED is the same human-approval predicate #757 already requires for every merge.
- The overseer's own recomputations (tier, surfaces, security, labels, holds, gate detection, #757) run unchanged and after the verdict gate.

**Residual R-1 (accepted).**
- A worker that force-pushes can erase earlier artifact versions, and so defeat the ratchet. The worker's protocol force-pushes only on the conflict-resolution path.
- The human still approves every merge (#757).
- Detecting `head_ref_force_pushed` timeline events is noted as a follow-up and is not required here.

**`overseer.md` step 3.** The `.claudetmp/signoffs/` clause is replaced by a call to `read`. `worker.md:380` and step 8.6 name the artifact path. `oversight-evaluator.md:647` names both the `.claudetmp` disposition and the published artifact (FR-10(b)).

### AD-6: The verdict gate treats CONDITIONAL_PROCEED exactly like a protected surface: a verified human approval on the head satisfies it. Otherwise it is HUMAN_REQUIRED with `needs-human`. (FR-9, AF-1, AF-6.)

In `decide_merge_authority()` (`merge_authority.py:631-638`):
- `oversight_verdict == "PROCEED"` → continue (unchanged).
- `oversight_verdict == "CONDITIONAL_PROCEED"`:
  - call `_find_human_approval(reviews, human_reviewer, head_sha)`;
  - if found, set `human_auth_reason` with the same string format as `:662`/`:683` and **continue** the matrix, so every later gate still applies;
  - if not found, return HUMAN_REQUIRED with `labels_to_add=["needs-human"]` and reason `Oversight verdict CONDITIONAL_PROCEED — human disposition of conditional items required`.
- **Any other value**, including `ESCALATE`, `BOUNCE`, unknown and empty → HUMAN_REQUIRED, `needs-human`. ESCALATE behaviour is unchanged. Unknown values fail closed. Today they hit the same branch with `needs-ai`.
- **Reuse only `_find_human_approval`.** No new approval predicate. #1936 can then replace the approval model in one function (AD-11).

**Approve-eligibility condition 4** (`overseer.md` § Verdict events) becomes: "The oversight verdict is PROCEED, **or** it is CONDITIONAL_PROCEED and a verified human approval exists on the current head SHA; and there are no unresolved findings, no bounce condition, no out-of-scope commits and no human hold directive."
- Before the human approves, the overseer posts `comment` that lists the JUDGMENT items (AD-7).
- After the approval, the next cycle posts `approve` and merges. `require-overseer-approval` is satisfied and AF-1's deadlock is gone.
- Unresolved threads still block server-side (`required_conversation_resolution: true`).

**Why this is not a loosening.** In effect, today every PR is PROCEED (F-3) and the overseer may `approve` before the human acts. Under AD-6, a CONDITIONAL PR gets `approve` only **after** a human has approved the same head, having seen the items. The code as written today (never auto-merge a CONDITIONAL) is unreachable, and if it were reached it would deadlock, so it is not a working control to preserve. This is still a user-visible change: the overseer, not the human, presses merge on a CONDITIONAL PR after approval. It therefore goes to the human under ESC-1(b).

**AC-8 amended:** `decide_merge_authority(..., oversight_verdict="CONDITIONAL_PROCEED", reviews=[])` → HUMAN_REQUIRED, `labels_to_add == ["needs-human"]`. With a human APPROVED review on `head_sha`, the result is whatever the remaining matrix yields. Add a test that a human approval on a **different** SHA does not satisfy it.

### AD-7: Worker-loop surfacing reuses the overseer's existing HUMAN_REQUIRED outputs. The worker loop gets no new per-item threads. (AF-5, FR-8, ESC-4.)
- For a `valid` CONDITIONAL_PROCEED artifact, the overseer's verdict body lists every JUDGMENT item (text, trigger, evidence) under a fixed heading, `Conditional items (human judgment required)`.
- The §8.2 escalation thread (`overseer.md:465` (4), already resolvable and merge-blocking) carries the same list.
- INFO items, which reach a PR only once S1b is enabled, go under `Notes for the reviewer`, never under a "Human Review Required" heading.
- `request-reviewer` is called exactly as it is today. It refuses at or below the ceiling unless the PR is on a protected surface, which is correct under ADR-1657 AD-3 (AF-2). The human's notification is the `needs-human` label, which AD-6 now applies (it was `needs-ai`).
- This adds no mechanism. It renders module output into two outputs the overseer already posts.

### AD-8: Orchestrator flows (FR-7, FR-8) are accepted, with item sourcing made deterministic.
- **Step 4:** `bash bootstrap/pr_review.sh request-reviewer --pr <n> --tier <TIER> --app <role>`. No literal login (AC-7). Exit 3 `no_qualifying_trigger` is logged and not worked around.
- **Step 5** posts threads for the disposition JSON's `class == JUDGMENT` items. It does **not** use the `grep -E '^[0-9]+\. '` regex over the handoff markdown (`oversight-orchestrator.md:256`), which cannot tell classes apart.
  - `ITEM_COUNT` is the JUDGMENT count from the JSON.
  - The handoff's "Human Review Required Before Merge" section is rendered from the same list.
- **Step 7 ledger:** `review_requested` records the wrapper outcome (`requested` | `skipped` | `refused:no_qualifying_trigger` | `error`), not a login.
- **R3.3** (`oversight-evaluator.md:536`) reads that outcome. `refused:no_qualifying_trigger` is a note, not a WARN, because it is the ruled behaviour.
- **FR-10(a):** delete the stale "No-op until SPEC-222 R1 ships" note (`:543`). The orchestrator does post threads (`:248-288`).

### AD-9: A missing, stale or invalid artifact on a worker PR. The default until ESC-5 is "note only". (FR-6.)
- **Before ESC-5 is ruled**, and for every PR not authored by the worker App: AD-5's mapping applies (`PROCEED` plus *Not verified*). No bounce.
- **If ESC-5 is accepted (S3b):** for PRs authored by the worker App whose `merge-base` with the default branch contains the S3 merge commit, the overseer calls `record_pr_bounce()` with `reason_category: REGISTER_GAP` and `summary: "evaluation verdict artifact <status>: <detail>"`, under the existing shared `< 2` budget (`overseer.md:288-290`), then escalates. This runs at step 4a, before the matrix.
  - PRs whose merge-base predates S3 are grandfathered. They are never bounced for a channel that did not exist when they were built.
  - Human and human-proxy PRs are exempt, as the requirements already state.

### AD-10: INFO → PROCEED (S1b) admits an INFO item only when the module can verify its evidence mechanically. (FR-2 rule 4, ESC-2.)
- When ESC-2 is accepted, rule 4 applies only to items whose trigger is `secpriv_iterations_ge3` with tier at or below MEDIUM, or `thread_compliance_warn`.
- **Each such item must also pass a deterministic evidence check:**
  - `secpriv_iterations_ge3`: the module parses the sign-off register (`.claudetmp/signoffs/step{N}-register.md`, the latest entry for the cited role, reusing `pr_readiness`'s register parser by import or extraction) and confirms the role is `security-review` or `privacy-review` and that `Iterations ≥ 3`.
  - `thread_compliance_warn`: the evidence is an R3.x check id from the module's closed set.
- An item that fails its check is raised to JUDGMENT (`raised_from: INFO`, reason `evidence_unverified`).
- This bounds the gaming surface: a model can no longer turn a judgment item into PROCEED by labelling it with an INFO trigger.

### AD-11: #1936 and #1428 compatibility. Isolate the actuators so #1936 can supersede them by deletion, not rework.
- The module and the artifact are **actuator-agnostic**. They emit classes, items and a recommendation. They never name a login, label, thread or reviewer.
- Every human-gate **actuator** lives in exactly one of three places:
  1. `_find_human_approval`: the approval predicate (AD-6, #757). If #1936 replaces bespoke approval checks with native "require review from Code Owners", this is the one function it changes.
  2. `bootstrap/pr_review.sh request-reviewer`: reviewer resolution. This is #1428's primitive. It already resolves the reviewer from `.github/CODEOWNERS`, so a `@org/human-maintainers` owner reaches it through the file without any change here. Supporting team reviewers (`team_reviewers`) in the wrapper is #1936's work.
  3. Per-item threads in `oversight-orchestrator.md` step 5 only, plus the overseer's existing single escalation thread. If #1936 retires threads, it deletes orchestrator step 5 and nothing in the module, the artifact or the overseer's read changes.
- Nothing in #1913 depends on #1936, and nothing here blocks it.

### AD-12: Documentation currency.
- FR-10(a) is covered by AD-8 and FR-10(b) by AD-5.
- **FR-10(c):** `overseer.md:450` "LOW / MEDIUM / HIGH tier + all checks green → AUTO_MERGE (… no human wait)" is replaced with text saying that AUTO_MERGE additionally requires a verified human approval on the head (#757; `merge_authority.py:715-731`). This corrects the text and changes no behaviour. It ships with AD-6 (S2), because both edit the same section.

---

## 3. Rulings on the requirements (deltas only; everything else is accepted as written)

| Req | Ruling |
|---|---|
| FR-1 | Accepted. The table is data in the module (AD-2). The evaluator supplies `trigger`; the module applies floors. |
| FR-2 | Accepted. Rule 4 ships disabled until ESC-2 (AD-2, AD-10). The tier is `max(declared, validator summary)` (AF-7). |
| FR-3 | Accepted. Second review is never re-run inside a bounce (AD-3). |
| FR-4 | **Channel ruled: committed artifact** (AD-4). The PR body is rejected (§4). |
| FR-5 | **Amended.** Head equality is replaced by AD-5's validity rules (b)–(d) and the ratchet (AF-3). |
| FR-6 | Mechanism accepted. The default before ESC-5 is "note only". Pre-S3 PRs are grandfathered (AD-9). |
| FR-7 | Accepted (AD-8). The trigger is **not** widened (AF-2, ESC-3). |
| FR-8 | Accepted, with items sourced from the disposition JSON (AD-8). |
| FR-9 | Accepted and extended. A human approval on the head clears CONDITIONAL_PROCEED (AD-6, AF-1). `needs-ai` is ruled an error (AF-6). |
| FR-10 | Accepted (AD-8, AD-5, AD-12). |
| AC-1 | Amended: "raised to the floor and recorded in `raised_from`", not "rejected". |
| AC-5 | Amended: staleness is per AD-5(d), not head equality. |
| AC-8 | Amended per AD-6. |
| S2 file list | `submit_pr.sh` is removed from scope (AD-4). |
| ESC-3 default | **Reversed** (AF-2). See §6 ESC-3. |
| ESC-5 (pm) | **Bound here, not escalated.** An `unparseable` second review stays JUDGMENT with no auto-retry. This is the status quo (`oversight-evaluator.md:490`), it spends no quota, and #1718 makes a retry likely to reproduce the problem. Retaining the status quo needs no product clearance. |

---

## 4. Alternatives rejected

- **PR-body "Oversight evaluation" block (FR-4 option).** Rejected:
  - The worker App can edit a PR body at any time without a commit, so the block is not bound to any commit.
  - A body edit does not trigger `dismiss_stale_reviews_on_push`.
  - It has no version history the overseer can ratchet over. Body edit history is GraphQL-only, and the ratchet is AD-5's tamper control.
  - It is lost from `main` on squash merge, so it leaves no durable research record.
  - It adds a markdown parsing surface on untrusted text, and every body `submit_pr.sh` composes carries the #1856 closing-keyword hazard.
- **Classification rules in agent prose** (`oversight-evaluator.md`). Rejected (AF-4). A model would then both label items and decide what the labels imply, and AC-1/AC-2 could only be tested by running the model.
- **Module under `scripts/automation/lib/`.** Rejected. It is unprotected today, and under ADR-1935 it would need a per-file list entry. `scripts/framework/` is protected by construction and is the ratified home for new control code (ADR-1935 §2, ADR-1540 AF-3).
- **A fourth recommendation value in `decide_merge_authority()`.** Rejected, per the requirements' non-goal. BOUNCE never leaves the worker clone (AD-3).
- **Shipping transport (S3) before the gate fix (S2).** Rejected: this is AF-1's deadlock.
- **Keeping "CONDITIONAL_PROCEED never auto-merges".** Rejected. Combined with `require-overseer-approval`, it makes LOW–HIGH CONDITIONAL PRs mergeable only by admin override (AF-1).
- **Overseer posts per-item threads on worker PRs.** Rejected for now. It is a new actuator that #1936 may delete. The single existing escalation thread plus the itemised verdict body gives the human the list (AD-7, ESC-4).
- **Treating an absent artifact as CONDITIONAL_PROCEED.** Rejected as the default. On human-authored PRs it changes behaviour for a channel those PRs cannot produce. On worker PRs, the honest enforcement is a bounce, which ESC-5 decides.

---

## 5. Slicing (BINDING order; every slice is HIGH tier and human-approved: protected or security surface)

| Slice | Delivers | Files (expected) | Depends on | Merge gated by |
|---|---|---|---|---|
| **S1: classify, dispose, pre-PR bounce** (minimal first value slice) | FR-1, FR-2 rules 1–3 and 5, FR-3, AD-2, AD-3, AF-7 | new `scripts/framework/evaluation_verdict.py` (`dispose`), tests; `oversight-evaluator.md` (items JSON output, Phase 2 cites the module, FR-10(a) is in S4); `worker.md` (bounce re-dispatch loop around 8.5); `pr_readiness.py` (REQ-W-13 reads the disposition JSON) | none | **none.** Under the ESC-1 default it delivers the bounce the issue asked for, and INFO-only stays CONDITIONAL. It weakens nothing. |
| **S2: verdict gate and docs** | FR-9, AD-6, AD-12 / FR-10(c) | `merge_authority.py` (`:631-638`), tests (AC-8 as amended, AC-9); `overseer.md` (approve-eligibility condition 4; `:450`) | none (can be built in parallel with S1) | **ESC-1** |
| **S3: transport and surfacing** | FR-4, FR-5, AD-4, AD-5, AD-7, FR-10(b), AD-9 default | `evaluation_verdict.py` (`publish`, `read`, ratchet, patch-id), tests incl. AC-4/AC-5; `worker.md` (step 8.6 commit, `:380`); `overseer.md` (step 3 `read`, verdict-body and escalation-thread rendering); `pr_readiness.py` (REQ-W-13 artifact self-check) | **S1 and S2 merged** (AF-1) | none beyond S2's |
| **S3b: missing-artifact bounce** | FR-6 enforcement (AD-9) | `overseer.md` step 4a | S3 | **ESC-5** |
| **S4: orchestrator** | FR-7, FR-8, AD-8, FR-10(a) | `oversight-orchestrator.md` (steps 4, 5, 7); `oversight-evaluator.md` (R3.3, `:543`) | S1 (disposition JSON) | none (ESC-4 default) |
| **S1b: INFO → PROCEED** | FR-2 rule 4, AD-10 | `evaluation_verdict.py` (enable rule 4 and the evidence checks); `oversight-evaluator.md` (Notes for the reviewer) | S1; S3 for the overseer rendering | **ESC-2** |
| *S4b (only if ESC-3 is reversed)* | `conditional_judgment` trigger | `pr_review_cli.py:899-916`, ADR-1657 amendment | S3 | **ESC-3 = (a)** |

**`technical-design` obligations:**
- AD-5's patch-id rule needs fixtures: a merge-from-base with no conflict (stays valid), a merge with a conflict resolution (becomes stale), a fix push (becomes stale), an artifact inherited from base (absent), a PROCEED-after-CONDITIONAL ratchet, and a schema with BOUNCE (invalid).
- The S1 worker loop must commit after each remediation stage. A cycle can die mid-bounce (MEMORY: orphaned agent output, the 600 s background kill).

---

## 6. Escalations for the human (final list; supersedes pm-agent's ESC-1..6)

### ESC-1 (human + pm-agent): Confirm the narrowed scope, and that a human head-approval disposes the conditional items. *Gates S2's merge.*
- **(a)** #757 stays. #1913 never produces a merge without a human approval on the head. Any relaxation belongs to #1936.
- **(b)** AD-6: once you approve a CONDITIONAL_PROCEED PR's current head, having been shown its JUDGMENT items, your approval disposes them, and the overseer may `approve` and merge on its next cycle. You no longer press merge yourself. Unresolved threads still block server-side.
  - The alternative to (b), "CONDITIONAL never auto-merges", is not viable: `require-overseer-approval` would then fail at or below the ceiling and the PR could merge only by admin override (AF-1).
- **Recommended: confirm (a) and (b).**

### ESC-2 (human): INFO-only items at LOW/MEDIUM yield PROCEED (no conditional gate; the items go under "Notes for the reviewer"). *Gates S1b.*
- The INFO set is closed: security/privacy iterations ≥ 3 at ≤ MEDIUM, and the SPEC-222 thread-compliance WARNs. Each must also pass a **mechanical evidence check**, failing which it becomes JUDGMENT (AD-10).
- #757 still requires your approval of the merge. The weakening is limited to the per-item gate for these two triggers.
- **Recommended: accept.**

### ESC-3 (human): Widen `pr_review.sh request-reviewer` with a `conditional_judgment` trigger? This **reverses** your confirmed ADR-1657 AD-3 ("do not widen"). *Gates S4b only.*
- **(a)** Widen. Every CONDITIONAL_PROCEED PR with a JUDGMENT item gets a review request.
- **(b)** Do not widen. A CONDITIONAL PR gets `needs-human` (AD-6, previously the misrouted `needs-ai`), an itemised overseer verdict, and a resolvable escalation thread. Revisit under #1936, where a team review request becomes the native mechanism.
- **Recommended: (b).** This differs from pm-agent's default. The request the orchestrator sends today has never fired (F-4: 0 events), so (b) loses nothing that exists, and AD-3's calibration rationale ("controls that never fire" / review fatigue) still holds.

### ESC-4 (human): Thread model until #1936.
- Keep per-item threads for JUDGMENT items **in orchestrator flows** (FR-8). Worker PRs get the itemised verdict plus the one existing escalation thread, with no new per-item threads (AD-7).
- Retire threads only when #1936 rules on the native gate model.
- **Recommended: confirm.** Not gating: S3 and S4 build to this default.

### ESC-5 (human; was pm-agent's ESC-6): A missing, stale or invalid evaluation artifact on a worker-authored PR bounces it back to the worker. *Gates S3b.*
- It uses the existing `record_pr_bounce()` path and its shared `< 2` budget, then escalates. PRs built before S3 merged are grandfathered (AD-9).
- This adds a worker obligation (re-evaluate and re-publish after any push that changes the PR's net diff), and a bounce condition on every new worker PR.
- **Recommended: accept.** Alternative (b) is note-only, which is what ships by default until you rule. It leaves FR-5 unenforced on worker PRs.

**Bound here, not escalated:** pm-agent's ESC-5 (unparseable second review stays JUDGMENT, §3). The pre-PR bounce's compute cost (AD-3) is not escalated either: the issue itself requests the bounce, and it is bounded at 2 rounds with no second-review re-runs.

---

## 7. Startup-gap and affected sign-offs

**Startup-gap: yes, for F-3 and AF-1.**
- `overseer.md:245` and the `merge_authority.py:631-638` verdict gate were approved on the assumption that the evaluator's verdict was transported. It never was. This is the #1594 cross-clone defect class, which an initial architecture review of the two-clone topology should have caught.
- **Action for the orchestrating session** (this ADR posts nothing): annotate #1913 with `startup-artifact-gap`.

**Affected sign-offs:**
- **Invalidated, re-reviewed in S2:** the `:633` `needs-ai` branch (AF-6), and approve-eligibility condition 4 as it applies to CONDITIONAL_PROCEED (AF-1). These were never exercised, so no merged PR was decided by them, and no past merge needs re-audit.
- **Stands:** SPEC-222 / #399 thread posting in the orchestrator. That path is correct for its flow and is narrowed, not reversed, by AD-8. #1657 / ADR-1657 AD-3 stands unchanged under the recommended ESC-3 (b). #757 stands (AD-1).
- **Stands:** the 3b validator-artifact check. AD-5 borrows its rules (b)–(c) but does not modify it.

---

## 8. Residuals (accepted, stated)

- **R-1:** a force-push can erase earlier artifact versions and defeat the ratchet (AD-5). #757 bounds the impact.
- **R-2:** the model can still **omit** an item entirely, or attach the wrong trigger to it. AD-2 removes the model's control over what a class implies, and AD-10 removes the INFO escape hatch. Omission is today's trust in the evaluator, unchanged.
- **R-3:** `.claudetmp` loss resets the bounce count (AD-3). Bounded by the cycle breakers.
- **R-4:** `signoffs/evaluations/` grows on `main` by one file per worker PR, as `signoffs/<namespace>/` stamps already do.

---

## Escalation flag (CORE self-flag)

RISK: HIGH. The design changes when the overseer approves and merges (AD-6) and adds a worker-authored input to the merge decision (AD-5).
CONFIDENCE: 85%.
- High on AF-1 to AF-3: each was read directly from code (`merge_authority.py:631-731`, `overseer.md` § Verdict events, `require_overseer_approval.py:1-33`, `pr_review_cli.py:899-916`, `submit_pr.sh` #1162).
- Lower on AD-5(d)'s patch-id comparison under exotic merge histories (octopus merges, rename detection). `technical-design` must fixture these. If patch-id proves unstable, it should fall back to the stricter rule ("any PR-own non-excluded path changed after `artifact_commit` → stale"). It must not fall back to anything looser.

## Human Review Required

- **ESC-1 to ESC-5 (§6)**, especially **ESC-1(b)** (the overseer merges a CONDITIONAL PR after your approval) and **ESC-3** (the recommended default differs from pm-agent's and preserves your ADR-1657 AD-3 ruling).
- **AF-1:** the transport must not ship before the gate fix. If anyone proposes reordering S2 and S3, reject it.
