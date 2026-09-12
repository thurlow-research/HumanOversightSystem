# ADR-1604 — A stuck issue stops itself, not the project: deterministic isolation in `hos-cron`, attribution as a forced side effect of an already-mandatory wrapper, and judgment confined to the split assessment

**Status:** ACCEPTED FOR DESIGN — binds `technical-design`. **Three items are held for the human** (§4): ESC-1 (the project brake's new threshold is a cost-model change), ESC-2 (may worker-filed sub-issues be autonomously selected before ADR-1540's enumeration lands?), ESC-3 (a lost audit write found in §0 that needs its own issue). Everything else below is **BINDING**.
**Date:** 2026-09-12
**Author:** architect
**Inputs:** issue #1604's body and **all five** of its comments — the 2026-09-12 refinements (graceful non-split; per-issue isolation), the process ruling, the auto-close-the-tracking-parent requirement, the VF-3/Q1/Q3 resolutions, and the bound-parameters comment with its *"if you find yourself in a hole, stop digging"* principle; `docs/v0.7.0/REQUIREMENTS-1604-worker-self-split-isolation.md` (pm-agent, PR #1610, **not yet merged** — read from `origin/docs/1604-worker-self-split-requirements`); #1601 as amended 2026-09-12; my own re-verification against `origin/main` (§0).
**Consumers:** `technical-design` (next), then **three or more** `needs-ai` issues to the autonomous `worker` (§3 — one issue for this whole mechanism would reproduce #1354).
**Source issues:** #1604 (this), #1601 (attribution + counter — hard prerequisite, **rescoped by AD-3**), #1602/#1603 (soft, quality-improving), #1354 (parent, canonical positive split case), #1597 (the live breaker trip), #1353 (incident), #1356 (`bounce_count` write side — the pattern #1601 was told to copy; **overturned** by AD-4), #1540 (actor-trust; AD-9 constrains its enumeration), #1520 (label rename), #1446 (usage-limit breaker — untouched).
**Explicitly does NOT re-litigate:** whether the suspend should be role-scoped (**ruled: no**, #1604 comment 2026-09-12T23:12:23Z — VF-3 is closed, not deferred); the three bound parameters D-1/D-2/D-3 (**ruled**); whether attribution belongs in #1601 (**ruled: yes**, Q1); whether a human clear resets the count (**ruled: yes**, Q3). This ADR implements those rulings; it does not reopen them.

---

## 0. Verification findings — every load-bearing premise re-derived against `origin/main` = `58b4785a`

pm-agent's document is from earlier the same day and is largely correct; I re-derived it rather than inheriting it. Line numbers are `58b4785a`'s.

### Confirming pm-agent

- **VF-1 CONFIRMED.** `bin/hos-cron:1248-1300`. State is one file per role+project, `${HOS_STATE_DIR:-$HOME/.hos}/timeout-breaker/${ROLE}-${PROJECT}`, two lines (attempts, cap). Trips at `HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS` (default **2**, `:1249`), calls `hos-suspend --project` with no `--until` (`:1265`), files one `needs-human` issue with fail-closed dedup (`:1278-1297`). No issue identity anywhere on the path.
- **VF-2 CONFIRMED.** The counter is keyed on role+project only, so "timed out on #A then on #B" is indistinguishable from "#A twice". FR20's dead-code hazard is real: at a default of 2 the existing counter fires before any per-issue policy could act.
- **VF-3 CONFIRMED, and now moot by ruling.** `_SUSPEND_FILE="$_HOS_DIR/suspend/$PROJECT"` (`:199`) is checked at `:200`, before the overlap lock and before any role branch, and `exit 0`s whichever role is firing. So a worker timeout does halt the overseer. The human ruled on 2026-09-12 that this is correct behaviour once the suspend is reserved for the systemic case. Recorded, closed, not designed around.
- **VF-4 CONFIRMED.** `scripts/automation/lib/next_candidates.jq` has exactly one eligibility filter: `select((.labels // []) | map(.name) | index("needs-human") | not)`. Isolation needs no new queue mechanism — but see **AF-4**, which is why I nevertheless bind a change to this file.
- **VF-5 CONFIRMED (56, not 57, today).** `query_issues.sh --list --label needs-human --state open` returns **56** open issues. The exact number does not matter; the conclusion does — a stuck count derived from `needs-human` would sit permanently above any threshold.
- **VF-6 CONFIRMED.** The post-kill block (`:1237-1300`) never names an issue. Work selection happens inside the Claude session: `_GATE_CANDIDATES` (`:1199-1213`) supplies a *list*, and the agent "picks the first non-blocked candidate" — the choice is never written anywhere `hos-cron` can read. No per-issue timeout attribution exists today, and the "existing interim mitigation" #1601's body cites is not in the code.
- **VF-8 CONFIRMED.** 19 committed `cycle-claude-timeout` records exist, all `role=worker`, spanning 2026-08-02 to 2026-08-17. Representative record verbatim: `{"event":"cycle-claude-timeout","limit":1800,"role":"worker","timestamp":"2026-08-13T20:33:14Z"}`. No issue number.
- **VF-9 CONFIRMED and root-caused — see AF-1.**
- **VF-12 CONFIRMED.** #1600–#1603 each name the parent, scope to one requirement, and list siblings under *"Explicitly out of scope"*. This is the bar an automated split must clear.
- **VF-13 CONFIRMED.** #1520 is open (`needs-ai`, `process-gap`, `priority:medium`, v0.7.0); the rename has not happened.

### My own findings — these change the design

**AF-1 (CRITICAL — `bounce_count` is not "unproven", it is *structurally* dead, and the reason generalizes to everything this ADR builds).** #1356 reports zero `pr-bounced` events. The cause is not a flaky write. `grep -rn "record_pr_bounce" --include=*.py scripts/ tests/` returns the definition (`merge_authority.py:1059`) and **eight test call sites, and nothing else**. There is **no non-test caller anywhere in the repository.** The only thing that "calls" it is prose in `.claude/agents/overseer.md:279`. `bounce_count`'s read side is correct and carries 20 passing unit tests; it counts an event that no executing code ever writes.

This is the single most important finding for this ADR, and it is a sharper statement than "don't assume the pattern is live":

> **A counter whose write is an instruction to an agent is a counter that reads zero forever, and a zero-reading counter is indistinguishable from "this never happened".**

#1601 was told to model itself on `bounce_count`. That instruction is **overturned** by AD-4. Every state transition this mechanism depends on is placed in deterministic code in AD-1 for exactly this reason.

**AF-2 (HIGH — an independently-derived second instance, and it is a *lost write*, not a sync gap).** pm-agent hedged VF-10. I can close most of the hedge. `#1597`'s body is byte-for-byte the `printf` template at `bin/hos-cron:1288` with `attempts=2`, so the breaker demonstrably tripped. The trip emits `_audit cycle-timeout-breaker-tripped` at `:1270`, **31 lines after** the `_audit cycle-claude-timeout` at `:1239`, in the same cycle, through the same helper, synced by the same unconditional `_sync_audit_logs` at `:1431`. In `audit/log/2026/08/` there is exactly one record matching `2026-08-17T17`:

```
2026-08-17T170243Z-cycle-claude-timeout-2bfb19c2fc16.json
```

The sibling from the same cycle is present; the trip record is absent. A sync gap would have dropped both. `_audit` swallows every error (`2>/dev/null || true`, `:300`) and `cycle_log.py` has no event allowlist that could reject it, so the cause is not visible from the code — but the *class* is settled: **an emitted event is not a written event, and a written event is not a readable one.** Consequence: AD-4 forbids any policy decision in this mechanism from depending on an audit read. This finding also deserves its own issue — **ESC-3**.

**AF-3 (HIGH — pm-agent's VF-7 is over-credited; the ownership record does NOT carry the issue number, and this changes what #1601 must build).** `bootstrap/lib/branch_ownership.sh:38-44` fixes the record format at exactly five keys — `schema`, `branch`, `cycle_id`, `role`, `created_at` — with strict validity requiring "every required key appearing exactly once". **There is no `issue` key.** The issue number survives only inside the *branch name*, recoverable by parsing. The record is written **record-first, before the branch** (`create_branch.sh:121-129`), keyed by encoded branch name under `<git-common-dir>/hos/branch-ownership`, and `HOS_CYCLE_ID` is exported by `hos-cron` itself (`:296`) — so a post-kill block **can** scan the store for the record whose `cycle_id` matches this cycle. That makes `create_branch.sh` the natural attribution point (AD-3), but it requires a **schema bump**, not merely "read the existing record". Anyone planning #1601 from pm-agent's VF-7 alone would find a field that is not there.

**AF-4 (HIGH — idle cycles neither increment nor clear the existing counter, so "consecutive" spans arbitrary wall-clock time, and `needs-human` alone is not a safe exclusion basis).** Two parts:
1. A no-work cycle `exit 0`s at `:797`, **before** the post-cycle bookkeeping at `:1355` that clears `_tb_state`. The 2026-08-17 trail is full of `cycle-skip` records (roughly one every ten minutes through the small hours). So the two timeouts that produced #1597 — 07:23:01Z and 17:02:43Z, **nearly ten hours apart** — were "consecutive" only in the sense of *consecutive claude-invoking cycles*. The existing counter accumulates indefinitely across idle time. This is not a bug to fix here, but `technical-design` must not assume "consecutive" means "back to back in time", and the same trap must not be reproduced in the new per-issue counter.
2. Because `needs-human` is applied and removed by many hands for many reasons (56 open today), making queue-exclusion depend on it means a human removing `needs-human` for an unrelated reason silently re-queues a still-stuck issue. AD-5 therefore puts the *exclusion* on the narrow marker, not only the count.

**AF-5 (MEDIUM — the split's own intent record has a shape already proven in this repo).** `create_branch.sh` writes its ownership record **before** creating the branch, with an explicit rationale: *"a record with no branch is inert; a branch with no record is a confusing fail-closed refusal later"* (`:118-120`). FR9's partial-split problem is the same problem, and AD-8 copies that shape verbatim rather than inventing one.

### Verification gaps I could not close

- **Whether the two cycles behind #1597 reached branch creation.** #1353 records "zero commits either time", which does not tell me whether `create_branch.sh` ran. So the *coverage* of AD-3's attribution source on the exact historical incident is **unknown**. AD-3's fail-closed path (AD-6) exists precisely because I could not close this.
- **Local state directories.** `~/.hos/timeout-breaker/`, `~/.hos/suspend/` on the Worker and Overseer clones were not inspected; all claims about them are from the code.
- **Cron logs** under `.local/log/` are outside this session's read scope.
- **Root cause of AF-2's lost write.** Identified as real; not diagnosed. ESC-3.

---

## 1. Context — what this mechanism actually is, after §0

The requirements frame this as a policy change. After §0 it is better described as **a relocation of authority**.

Today, three facts the system needs — *which issue was being worked*, *how many times it has failed*, and *whether to stop* — live in three bad places: the first is inside a killed process's memory, the second nowhere at all, and the third in a counter that cannot tell one issue from another. #1604 asks for a fourth fact, *"can this be decomposed?"*, which genuinely requires judgment.

The failure mode this design must avoid is not "the policy is wrong". It is **AF-1**: writing the policy as instructions to an agent, producing a mechanism that is fully specified, fully tested at the unit level, and never executes. The repo already contains one such mechanism (`bounce_count`) and one lost write from a deterministic path (**AF-2**). A third would be worse than doing nothing, because a brake that reads zero looks exactly like a system that is fine.

So the architecture splits on a single line: **everything that counts, decides, excludes, or suspends is deterministic code that runs whether or not an agent cooperates. Exactly one thing — "does this issue decompose, and into what?" — is a judgment, and it is given no authority over any of the above.** That is the same division ADR-1540 bound for request intake (deterministic gate + authority-free assessor), and using it twice is deliberate.

The human's guiding principle applies directly to the shape of this document: the ladder terminates in a human, and each rung is dumber than the last. There is no rung that tries harder.

---

## 2. Decisions (BINDING on `technical-design`)

### AD-1 — The decision point is deterministic code in the cron cycle. The agent is handed a directive, never a question. (BINDING — FR5, FR6; AF-1.)

All of the following are computed by code that runs before `claude` is launched, in `bin/hos-cron`'s pre-work gate region (alongside the existing `_GATE_CANDIDATES` block at `:1199-1213`), delegating to a new, unit-testable Python module under `scripts/automation/lib/` rather than growing the shell:

- per-issue attributed-timeout counts and whether any issue is at the D-3 threshold;
- the live stuck-issue count and whether it is at D-2;
- the tracking-parent reconcile (AD-10).

The agent receives the result as a **directive line in the context block**, in the same register as the existing `NEW WORK: ALLOWED` / `STOP — do not proceed to Step 2` lines (`:1190-1197`) — e.g. *"ISSUE #N IS AT THE TIMEOUT THRESHOLD. Your only permitted action on it this cycle is a split assessment (AD-7). You may not work it."*

**The agent is never asked to check a counter, apply a threshold, decide whether to suspend, or remember to emit an event.** If the agent ignores the directive entirely, the isolation has already happened: the labels were applied by code before the session started, and the issue is already out of `_GATE_CANDIDATES`.

*Why this could still go wrong:* the directive is prose in a prompt, so an agent could in principle work the issue anyway by ignoring the candidate list. The containment is that the *state changes* do not depend on the agent — worst case is one wasted session, not a broken brake.

### AD-2 — The per-issue counter reuses the mechanism that is demonstrably proven live, and is **not** modelled on `bounce_count`. (BINDING — FR2; AF-1, AF-2. This overturns #1601's stated instruction.)

`_tb_state` (`:1248-1260`) is the one counter in this area with direct field evidence of working end to end: #1597 exists, and its body reports `attempts=2`, which is only reachable if the file was written, read back on a later cycle, and compared. The per-issue counter is the **same mechanism, re-keyed**: one small file per (role, project, issue) under `$_HOS_DIR/`, written by deterministic shell/Python in the post-kill block, carrying at minimum the attempted count and the cap it was counted at (so a cap change resets it, preserving the existing "raising `--max-seconds` is never a trap" property).

`bounce_count`'s *shape* — derive the count from the append-only audit stream — is explicitly **rejected** for this counter. Its read side is fine; its write side has no non-test caller (AF-1) and its sibling event class has a demonstrated lost write (AF-2).

*Accepted consequence, recorded so `technical-design` does not "fix" it:* the per-issue counter is local to the worker clone and is lost if the clone is rebuilt. That is acceptable and deliberate — the worker is the only writer and the only reader, the loss direction is "one extra attempt", and the project-level brake (AD-6) backstops it. Do **not** promote it to a cross-clone store; the one decision that genuinely needs cross-clone, human-visible state is the stuck count, and AD-5 gives it exactly that.

### AD-3 — Attribution is a forced side effect of `bootstrap/create_branch.sh --issue <N>`, not an instruction. (BINDING — FR1; AF-1, AF-3. **This rescopes #1601 a second time.**)

#1601's amended mechanism — mark the issue when work starts, clear on clean finish, treat a leftover marker as the attribution signal — is **correct and adopted**. What is bound here is *who performs the write*:

1. **Set:** `create_branch.sh` already takes `--issue <N>`, is already the mandatory path to a work branch, and already writes a durable record before doing anything else. It gains two forced side effects: an `issue=<N>` key in the ownership record (**schema bump — AF-3: the key does not exist today**), and application of the active-work marker to that issue. The agent cannot start work and forget, because starting work *is* this call.
2. **Read:** the post-kill block resolves the cycle's issue by scanning the ownership store for the record whose `cycle_id` equals the exported `HOS_CYCLE_ID` (`:296`), reading `issue=`. The branch name is a secondary, corroborating source, not the primary one (parsing a name is weaker than reading a field).
3. **Clear:** deterministic post-cycle code in the `_claude_exit -eq 0` bookkeeping block (`:1355`) removes the marker, resolving the issue the same way. Never the agent.

This is ADR-1357's AD-10 pattern (*"a forced side effect of the wrappers, not a step the agent is trusted to remember"*) applied to a different control, and it is the only formulation of #1601's mechanism that does not land in AF-1's failure class.

*Coverage limit, stated rather than hidden:* a cycle killed **before** branch creation has no attribution. Triage-only and PR-review cycles create no branch at all. Those timeouts are **unattributable by construction** and go to AD-6. This is the right answer, not a hole: a cycle that never opened a branch also produced nothing to attribute, and repeated such kills are a systemic signal, which is precisely where AD-6 sends them.

### AD-4 — Audit events are emitted for observability only. **No decision in this mechanism may read one.** (BINDING — FR22 as amended; AF-1, AF-2.)

Every transition emits an audit event (attributed timeout, decision outcome, each sub-issue filed, stuck marking, project suspend, parent auto-close). None of them is an input to any decision. FR22's verification requirement stands and is strengthened: the implementation MUST include a test that drives at least one event through the **real** write path and reads it back from a separate process, and that test must fail if the write is skipped — it may not pass by mocking the store.

This closes AF-2's failure class by construction: if the audit write is silently lost again, this mechanism degrades to "less observable", never to "the brake stopped working".

### AD-5 — The stuck state is one narrow marker that is authoritative for **both** the count and the queue exclusion. (BINDING — FR17, FR18, FR24, FR26; VF-4, VF-5, AF-4.)

- A single new narrow marker (spelling is `technical-design`'s; semantics are "this mechanism has concluded no further autonomous attempt should be made on this issue") is the **sole** basis for the FR19 live count and the **sole** basis for this mechanism's queue exclusion.
- That exclusion is expressed in `scripts/automation/lib/next_candidates.jq` **and** its inlined twin in `bootstrap/worker-cron-prompt.md`, in lock-step, covered by the existing `tests/automation/test_next_candidates.py` divergence test.
- The generic human-attention label is applied **alongside** for continuity with existing human triage, and is **advisory**: removing it does not re-queue a stuck issue, and it is never counted. (AF-4.2 — with 56 of them open and many hands touching them, deriving anything load-bearing from that label is how this mechanism would silently re-queue work it had just parked.)
- **Clearing is removing the narrow marker**, and nothing else. Per Q3, the deterministic reconcile resets that issue's attributed-timeout counter to zero when it observes the marker absent on an issue that carries a non-zero count. The human edits no state file and posts no magic string.
- Neither the marker nor any other label spelling appears in policy logic (FR25): one constants module, one place #1520's rename touches.

### AD-6 — Three brakes, three distinct triggers, one ladder. The token-burn brake is **strengthened in reach and relaxed in threshold**, never removed. (BINDING — FR3, FR19, FR20, FR21; D-1, D-2, D-3.)

FR20 requires the existing project-scoped trip to be superseded. Superseding it naively opens a hole the requirements do not name: if attributed timeouts only ever increment a per-issue counter, then *N distinct issues each timing out once* increments nothing to threshold, marks nothing stuck, and burns sessions forever. The ladder below closes it.

| Rung | Trigger | Threshold | Response |
|---|---|---|---|
| 1 | Attributed timeouts on **one** issue | **2** (D-3; floor 2, configurable) | Split-or-escalate decision (AD-7). Worker continues all other work. |
| 2 | Consecutive claude-invoking timeout cycles, **regardless of attribution** | **4** (default; **floor 3**; configurable — this is the existing `HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS`, re-defaulted) | Project-wide suspend, exactly as today. |
| 3 | Live count of currently-stuck issues | **3** (D-2; floor 2, configurable) | Project-wide suspend, exactly as today. |

Binding notes on the rungs:

- **Rung 2's floor of 3 is not cosmetic.** At 2 it fires before rung 1 can ever act and the entire mechanism is dead code (FR20, VF-2). The default of 4 leaves one cycle of headroom for the cheap decision cycle (AD-7), which exits 0 and therefore **clears rung 2's counter** — so in the working case rung 2 never approaches its threshold, and it only accumulates when nothing is working. That is the systemic case, which is what it is for.
- **Rung 2 also catches every unattributable timeout (FR3).** Attribution failure cannot disable the brake; it routes to rung 2 unchanged. No issue is ever marked stuck on a guess.
- **Rung 3 does not decay, by design.** pm-agent's D-1 recorded this and I affirm it: three issues the autonomous system could not finish, sitting unattended, *is* the systemic signal. Do not add a staleness or decay rule.
- **When rungs 2 or 3 fire, both roles suspend.** Ruled 2026-09-12; correct; not a defect (VF-3).
- All existing suspend properties are preserved: no `--until`, fail-closed dedup on the filed `needs-human` issue, auto-clear on a normally completing cycle.
- **The usage-limit breaker (`:1306-1352`, #1446) is untouched** — different signal, first-detection trip, deliberately project-wide.

*What could still go wrong:* rung 2's raised default increases worst-case burn before a project-wide stop by roughly two sessions. That is a cost-model change and is **ESC-1**.

### AD-7 — The split assessment is the only judgment in the mechanism, it holds no authority, and its default answer is "no split". (BINDING — FR6, FR7, FR8, FR13.)

- It runs **before** work selection in the cycle, completes its state changes (labels, comments, sub-issues) **before** any build work begins, and then the cycle proceeds to normal work selection. A later kill in the same cycle cannot undo a completed decision, and a decision cycle is not a wasted cycle.
- It may not invoke the design/review chain, open branches, or run builds. Reading the issue, its comments, and (when present) #1602's checkpoint and #1603's session record is the whole input set.
- Its output is one of exactly two values — `SPLIT(<plan>)` or `NO_SPLIT(<reason>)`. There is no third value and no "retry unchanged". If it errors, times out, returns anything unparseable, or is skipped, the deterministic code treats it as `NO_SPLIT` and marks the issue stuck. **The mechanism's behaviour when the judgment is absent is the safe behaviour** — this is what "authority-free" means here.
- `NO_SPLIT` is unconditional and carries no penalty; a reason is recorded on the issue (FR23). A plan of size 1, or one whose members restate the parent, is invalid and is treated as `NO_SPLIT`.
- Per FR13, if the sequencing enforcement of AD-10 is unavailable for any reason, a plan containing a dependency is likewise `NO_SPLIT`. Split-and-hope is not reachable.

### AD-8 — The split is record-first and resumable: the plan is written to the parent before any sub-issue is filed. (BINDING — FR9; AF-5.)

Order, non-negotiable: (1) write the complete plan as one machine-readable tracking block on the parent, each child carrying a stable slug; (2) file each child via `bootstrap/create_issue.sh`, recording its number back into the block as it is created; (3) mark the parent a tracking item (AD-5's marker plus the tracking block). A cycle interrupted anywhere resumes by reading the block and filing only the slugs with no number yet. No second overlapping set is reachable, and a plan with no children is inert.

This is `create_branch.sh`'s record-first rationale (AF-5) applied unchanged. `technical-design` should not invent a different ordering.

### AD-9 — Sub-issues inherit authorization from the parent explicitly; they never acquire it by authorship. (BINDING; constrains ADR-1540's AD-2 enumeration. Resolves pm-agent's **Q2** technically; **ESC-2** holds the sequencing.)

The worker files sub-issues under its own App identity via the existing `create_issue.sh` path — that part of pm-agent's recommendation is confirmed. But ADR-1540 makes issue **authorship** the trust signal, which would make these self-trusted by construction: a machine creating its own authorized work.

Binding containment:
1. Every sub-issue carries a machine-readable derivation link to its parent, and is authorized **because the parent was**, not because the worker wrote it.
2. Sub-issue filing is an **enumerated machine-filing path** under ADR-1540's AD-2, not an instance of a general trusted-author exemption. ADR-1540's implementer must enumerate it deliberately.
3. A sub-issue whose parent cannot be resolved, or whose parent was not itself authorized, is not autonomously selectable.

This mechanism may not ship ahead of that enumeration (or an equivalent enforced inheritance check) — **ESC-2** puts the sequencing choice with the human, because it is a policy call about machine self-authorization, not a technical one.

### AD-10 — One deterministic reconcile handles sequencing-unblock **and** tracking-parent auto-close. They are the same sweep. (BINDING — FR11, FR12, FR14, FR15, FR16, and the human's 2026-09-12T22:12:14Z requirement.)

Each cycle, before work selection, deterministic code walks every issue carrying a tracking block and:

- **unblocks** children whose declared blockers are all closed, by removing their exclusion marker (this is what makes FR11's both-sided sequencing load-bearing rather than decorative — a dependency recorded in prose while both children sit in the queue is the *"two cycles building conflicting work in parallel"* failure with a paper trail that makes it look handled);
- **auto-closes** a parent when every child listed in its block is closed, posting a comment naming them.

Binding constraints on the sweep:

- **Both sides of every dependency are recorded** (FR11), and a plan asserting independence must say so explicitly — absence of a dependency statement is not an assertion of independence, it is an incomplete plan, and an incomplete plan is `NO_SPLIT`.
- **Parenthood is recognized only from the tracking block.** Never inferred from prose, cross-references, or title conventions. Auto-closing an issue on a guess is the worst available false positive here. Any parse ambiguity → do nothing.
- **This generalizes as the human required:** any issue carrying the block is reconciled, including hand-made parents like #1354 and #1358. Those get the behaviour by a human adding the block once — one convention, not two.
- **Split-origin durability (FR15/FR16) is parent-side.** "Is this issue a sub-issue?" is answered by its appearance in some parent's tracking block, not by a label on the child. Relabelling, editing, or re-triaging a child therefore cannot make it split-eligible. The child's own derivation link (AD-9.1) is a fast path, never the authority.
- A sub-issue reaching the D-3 threshold is marked stuck. It is never split. No path creates a grandchild.

### AD-11 — Worst-case bound, stated as a number `technical-design` must be able to demonstrate. (BINDING.)

Per parent: 2 attempts → 1 cheap decision cycle → (if split) 2 attempts per child → human. Per project: at most 4 consecutive timeout cycles before a full stop (AD-6 rung 2), and at most 3 concurrently stuck issues before a full stop (rung 3). There is no reachable state in which the worker retries an unchanged issue a third time, and no reachable state in which it splits a sub-issue. A test must assert both.

### AD-12 — Scope boundaries.

Unchanged and owned elsewhere: the timeout itself (#1354 R1–R4), the detection primitives (#1601/#1602/#1603, as rescoped by AD-3), `HOS_CRON_MAX_SECONDS` (#1600), the usage-limit breaker (#1446), `hos-suspend`'s granularity (ruled: no change), PR splitting (`docs/PR-SIZE-POLICY.md`), #1356's root cause (ESC-3). **No learning, no heuristic tuned from history, no additional automatic recovery layer.** The human's *"stop digging"* principle is a binding constraint on future extension, not a mood: anything that makes the ladder try harder before reaching a human requires a new human ruling.

---

## 3. Build order — and the implementation of this issue must itself be split

**#1601, rescoped per AD-3, is a hard prerequisite and must land first.** Nothing in phases 1–4 can be built against an issue number the system cannot name. Design work (this ADR, then `technical-design`) proceeds now; implementation does not begin before Phase 0 lands.

There is an obvious trap here, and it is the one this issue exists to fix: **filing "implement ADR-1604" as one `needs-ai` issue would reproduce #1354 exactly.** The phases below are independently completable and are the intended issue boundaries. State the dependencies on both sides (FR11) when filing them.

- **Phase 0 — attribution (#1601, rescoped).** `issue=` in the ownership record (schema bump, AF-3); `create_branch.sh` applies the active-work marker; deterministic clear on clean exit; per-issue counter file (AD-2); resolution of the cycle's issue from `HOS_CYCLE_ID`. Ships with the FR2 end-to-end test. **Blocks everything below.**
- **Phase 1 — isolation only.** AD-5's narrow marker + `next_candidates.jq` lock-step exclusion; AD-6's three rungs, including re-defaulting the existing breaker to 4/floor 3; the stuck-set query; Q3's reset. **No split behaviour at all.** This phase alone delivers the whole of #1597's fix and is the highest-value, lowest-risk slice — if the rest slips, this should still ship.
- **Phase 2 — the reconcile sweep (AD-10), auto-close half only.** Tracking-block convention, parent auto-close, fail-closed parsing. Independently valuable: it closes #1354 and #1358 automatically today, with no split behaviour anywhere.
- **Phase 3 — the reconcile sweep, unblock half.** Dependency enforcement (FR12). Required before Phase 4 may permit dependent splits (FR13).
- **Phase 4 — the split assessment and filing (AD-7, AD-8, AD-9).** Gated on Phase 3 and on **ESC-2**. #1602 and #1603 improve this phase's input quality and should land before it if they are going to; neither blocks it.

---

## 4. Escalations

### Bound here, not escalated — with reasons

- **Which store holds the per-issue counter** (AD-2): bound to the proven `_tb_state` mechanism, against `bounce_count`'s audit-derived shape. This contradicts #1601's own body; AF-1 is why.
- **Who writes the attribution** (AD-3): bound to `create_branch.sh` as a forced side effect. The human's marker mechanism is adopted; only its writer is bound.
- **Rung 2's new default of 4 / floor 3** (AD-6): bound technically, because a floor below 3 makes the whole mechanism dead code. The *cost* of the raised default is ESC-1.
- **Q2's technical containment** (AD-9): bound. Only the sequencing is escalated.
- **The auto-close convention** (AD-10): bound to a single explicit tracking block, never inference.

### ESC-1 — Raising the project brake's threshold changes the cost model. (Product boundary — human.)

AD-6 rung 2 moves `HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS` from 2 to a default of 4. Worst case before a project-wide stop goes from ~2 killed sessions to ~4 (at the current 1800s cap, roughly one hour to roughly two). The floor of 3 is technically mandatory (below it the mechanism is dead code); the choice of **3 vs 4** is a cost/latency tradeoff the human owns. My recommendation is 4, because the cheap decision cycle clears the counter in every working case, so the fourth rung is only ever reached when nothing is working.

### ESC-2 — May worker-filed sub-issues be autonomously selectable before ADR-1540's enumeration lands? (Policy — human; `pm-agent` for product impact.)

AD-9 binds the containment. What it cannot decide is sequencing: ship Phase 4 with sub-issues autonomously selectable and rely on the derivation link, or hold Phase 4 until ADR-1540's AD-2 enumerates this filing path. This is the first mechanism in HOS by which the machine creates its own authorized work; whether that waits for the trust design is a policy call with no correct technical answer. Phases 0–3 are unaffected either way, which is why they are ordered first.

### ESC-3 — A deterministic audit write is being lost, and it has no issue. (New — mine; AF-2.)

`cycle-timeout-breaker-tripped` is absent from the committed trail for the 2026-08-17T17:02:43Z cycle while the same cycle's `cycle-claude-timeout` record is present. This is the same class as #1356 but a different instance — #1356 is a missing *caller*, this is a missing *record from a caller that demonstrably ran*. It needs its own issue (or an explicit annotation on #1356 distinguishing the two classes). I am design-only this session and have not filed it; the orchestrating session should. AD-4 means this ADR does not depend on the fix, but leaving it unrecorded would let a second lost-write class stay invisible.

---

## 5. Startup-gap analysis and affected sign-offs

**Should any of this have been settled before design and code were built against it?** Two items, both affecting work not yet built, so no prior sign-off is invalidated:

- **AD-3 rescopes #1601 a second time** (after the human's 2026-09-12 amendment). #1601 is open, `needs-ai`, unstarted — **no design or code exists against the superseded scope, so no sign-off is orphaned.** #1601's body must be annotated with two corrections before pickup: the ownership record has **no** `issue` key today (AF-3), and the `bounce_count` pattern its body instructs the implementer to copy has no non-test caller and is **overturned** (AF-1, AD-2). Without that annotation, #1601 would be built to copy a dead pattern and to read a field that does not exist — a startup gap this ADR catches in time.
- **AD-6 re-defaults an existing shipped control** (`HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS`, shipped in #1435/#1439, 2026-08-15). The code and its sign-off stand; only the default changes, and only in service of a rule (FR20) that did not exist when it was written. No re-review of #1435 is required, but its tests must be re-run against the new default and the #1435 rationale comment at `:1241-1247` updated so the two thresholds' relationship is legible in the file.

No other prior sign-off is affected: Phases 0–4 are all new build.

---

## Human Review Required

**RISK: HIGH.** This ADR relaxes a safety brake on purpose and relocates where several controls live. The failure mode of getting it wrong is an autonomous worker that burns sessions indefinitely without stopping — and per AF-1 and AF-2 this repo already contains one control that never fires and one deterministic write that vanished, so "we specified a brake" is not evidence of a brake. Four specific routes to that failure are closed positively rather than cautioned about: every count, threshold, exclusion and suspend is deterministic code with no agent in the path (AD-1, AD-3); the counter reuses the one mechanism with field evidence of working rather than the one reported dead (AD-2); no decision reads an audit event (AD-4); and the existing project brake is kept, re-keyed and raised to a floor that cannot fire before the new policy acts, while still catching every unattributable timeout (AD-6). The fifth route — the *N distinct issues, once each* hole that FR20's supersession opens and the requirements do not name — is closed by rung 2 surviving as an attribution-blind counter.

**CONFIDENCE: HIGH** on §0; every finding was re-derived from `origin/main` (`58b4785a`) this session, including the three that correct or extend pm-agent (**AF-1** root-causes VF-9 from a caller search; **AF-2** closes most of VF-10's hedge with a same-cycle sibling comparison; **AF-3** finds VF-7's proposed field absent from the record schema). **HIGH** on AD-1 through AD-6, which follow directly from those findings and from rulings the human has already made. **MEDIUM-HIGH** on AD-7/AD-8/AD-10 — the split and reconcile shapes are sound and copy proven patterns, but they are the parts with the least existing code to verify against. **LOWER** on anything downstream of the stated gaps: whether the #1597 cycles reached branch creation (which sets AD-3's real-world coverage), and the uninspected local state directories.

**BLAST RADIUS:** `bin/hos-cron`'s timeout, escalation and pre-work gate paths; `hos-suspend` entry conditions; `bootstrap/create_branch.sh` and the branch-ownership record schema; `next_candidates.jq` and its test-pinned twin — i.e. work selection for every autonomous cycle; the issue graph itself, since the worker gains authority to create and to close issues. Indirectly ADR-1540, which AD-9 constrains, and the overseer, which stops being halted by a single worker timeout.

**Change classification: STRUCTURAL.** New authority (the machine creates and closes its own work items), a changed safety-brake threshold, a new issue state, and a schema bump to a shipped durable record. Per the product-boundary checkpoint, ESC-1 (cost model) and ESC-2 (machine self-authorization policy) must be cleared by the human before the corresponding phases bind; Phases 0–3 are unaffected by either and may proceed on `technical-design`'s completion.
