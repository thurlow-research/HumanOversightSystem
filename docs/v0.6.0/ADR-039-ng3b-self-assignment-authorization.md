# ADR-039 — NG3b release authorization: self-assignment replaces bot-assignment as the third signal

**Status:** ACCEPTED
**Date:** 2026-08-13
**Author:** architect (ruling captured verbatim below; transcribed by worker per this ADR's own §4)
**Issue:** #1347 (blocks #1338, the v0.6.0 release-cut request) · **Milestone:** v0.6.0 · **Risk tier: HIGH** (governs the release-cut gate itself)
**Consumers:** worker (`.claude/agents/worker.md` NG3b), overseer (`.claude/agents/overseer.md` bounce protocol), `scripts/automation/lib/merge_authority.py`, `bootstrap/edit_issue.sh`

---

## 0. Problem

GitHub does not permit assigning issues or pull requests to GitHub App/Bot identities on this repo. Confirmed 2026-08-13 via three independent checks against `hos-worker-hos[bot]`:

1. `gh api repos/{owner}/{repo}/assignees` (the assignable-users list) does not include it — only `ScottThurlow` appears.
2. `POST /repos/{owner}/{repo}/issues/{n}/assignees` with that login returns `403 Forbidden` (a genuine authorization rejection, not a 422 validation error).
3. GraphQL has no top-level `bot(login:)` query field, and `Repository.assignableUsers` is typed to return Users only, never Bots/Apps.

This is a hard GitHub platform constraint, not a missing permission or App configuration gap. The Release Authorization Protocol (NG3b, `.claude/agents/worker.md`) uses "assign this issue to `hos-worker-hos[bot]`" as one of three signals a human CODEOWNER must produce to authorize `cut_release.sh`, verified live via the GitHub Events API and never satisfiable by chat text. Since that action is categorically impossible, R1 condition 3 and R5's temporal/actor checks could never pass as written — this is why issue #1338 (v0.6.0's release-cut request) was stuck from 2026-08-12T20:46:30Z. `record_pr_bounce()` in `scripts/automation/lib/merge_authority.py` attempts the same impossible assignment on every PR bounce, failing silently (already wrapped in try/except, so non-blocking, but wasteful and produces a false `assigned_to` audit field).

---

## 1. Decision

**Self-assignment replaces bot-assignment as NG3b's third authorization signal**: the authorizing human CODEOWNER assigns the release-request issue to *themselves*, instead of to the bot. This preserves every anti-spoofing property the original design relied on — a real, timestamped, actor-attributed GitHub API event, not a chat message; tied to one identifiable human; verifiable live from the Events API; compatible with the existing "same actor for all three signals" invariant.

The naive port of this idea — literally swapping "assign the bot" for "assign yourself" everywhere the old text said "assign the bot" — is **not** what shipped. It is fail-open where the original was fail-safe (§2) and deadlocks the moment any validation-failure path runs (§2). Four additional, load-bearing changes make it safe. All four are binding, not optional refinements:

- **M1 — identity-triple check.** The authorizing `assigned` event must carry non-null `assignee.login` AND non-null `assigner.login`, with `assigner.login == assignee.login`, and any present `actor.login` must agree. Never substitute `actor.login` for a missing `assigner`. This makes the check correct regardless of which of GitHub's documented-vs-observed field semantics is true (§2), and makes a bot-performed assignment structurally unrepresentable as an authorization.
- **M2 — assignee-write ban on release-request issues.** The worker's only permitted write to the assignee field on such an issue is the M3 reset. No failure, escalation, or error path may assign any account there. Without this, the protocol deadlocks the first time a validation suite fails (the old failure paths reassigned `ScottThurlow`, which — combined with M1's absence — is exactly the forgery path M1 closes; keeping the failure-path reassignment while adding M1 would just make M1's protection load-bearing on every validator run instead of only at authorization time, for no benefit).
- **M3 — deterministic anchor reset.** R4 clears all assignees on the issue *before* posting the results comment, so "the issue is unassigned" is true when the human reads the instructions, and so a genuine self-assignment necessarily produces a fresh `assigned` event postdating the comment. Without this, a human already self-assigned from a prior failed attempt produces no new event (GitHub does not emit `assigned` for a redundant assignment) and the wait is silent and permanent — reproducing the exact failure class this ADR exists to fix.
- **M4 — AWAITING vs VIOLATION split.** "No qualifying signal yet" (human hasn't finished acting) and "a disqualified signal exists" (spoofing attempt or misconfiguration) are different outcomes. Under bot-assignment, "assigned to a human" was itself disqualifying, so a blanket "any failure fires `ng3b-violation-attempt`" rule was harmless. Under self-assignment, "assigned to a human, no event yet" is the *routine, expected, in-progress* state, and firing a violation event on every such read would make the audit log noise, not signal. AWAITING conditions fire no event; only a disqualified signal fires one. A one-time diagnostic comment (`<!-- hos-ng3b-awaiting -->`) is posted the first time a request is found AWAITING, naming which of the three signals is outstanding — because a silently-unsatisfiable NG3b condition already cost this project a release cycle (#1338), and a stalled gate must say what it is waiting for.

---

## 2. Why the naive port is unsafe — the reasoning, not just the rule

**(a) The worker itself can produce the "authorized" assignee state.** Under the old design, five NG3b failure paths (R3, R4 dirty-tree, R6 ×3) ran `edit_issue.sh --assignee ScottThurlow` — a state no agent could otherwise create, since only the bot could be a *worker-assigned* value and bots can't be assigned at all. "Assigned to the bot" was therefore a state exactly one path (the human's authorizing action) could ever produce. Under self-assignment, "assigned to a human CODEOWNER" is a state the worker creates *routinely*, as a side effect of ordinary error handling. Combined with this repo's own prior finding that GitHub's Issue Events API can carry `actor.login` as the *assignee* rather than the performer of an `assigned` event (`research/findings/api-field-shape-verification.md`, #348, 2026-06-16 — a live-response contradiction of GitHub's documented field semantics, not a hypothetical), an implementation reading only `actor.login` would read a worker-performed assignment as `ScottThurlow` and the three-signal check would pass. The old design failed **closed** under that same field-name ambiguity (assignee was the bot → in `BOT_ACCOUNTS` → reject regardless of which field meant what). The naive port fails **open** — a genuine new privilege-escalation path, closed by M1 (which is semantics-agnostic: it requires whichever fields are present to agree, so it is correct under either reading of GitHub's API) combined with M2 (which removes the worker's ability to write the field on these issues at all, so there is nothing for M1 to be tricked by).

**(b) The common path silently deadlocks without M3.** GitHub emits no `assigned` event for a redundant assignment. Any failure path that assigns a human (pre-M2 design) or any prior self-assignment attempt (post-M2 design, if the anchor isn't reset) leaves the issue already assigned by the time R4 posts — so "assign yourself" is a no-op, produces no event, the freshness condition never holds, and the worker waits forever while the human believes they already acted. This is the identical failure class as #1347 itself, re-created one layer down. M3 (reset-before-post) and M2 (no other path may write the field) together are what make the freshness condition satisfiable on every request, not just the first.

**Residual risk, accepted.** Self-assigning is a lower-ceremony, more common gesture ("I'll take this") than assigning a bot was, so it is a slightly weaker "I am authorizing this" signal in isolation. This residual is bounded and accepted because: (i) the semantic intent is carried by `release-authorized`, not the assignment — the assignment is the freshness/accountability anchor, not the approval itself; (ii) the three-signal same-actor requirement still applies in full; (iii) the freshness condition (event must postdate the results comment) rules out a stale pre-emptive self-assign; (iv) M3 guarantees the anchor reads as empty at the moment the human reads the instructions. Enforcing a strict signal *order* (self-assign must be the temporally last of the three) was considered and rejected — it would close the last sliver of this residual but reintroduce a silent-deadlock class (self-assign-first produces no event to re-trigger on), which is the bug this ADR exists to fix.

**Side effect, not a design goal but worth recording:** the accountable human is now the visible assignee of record on the release issue in every GitHub listing. The bot never was accountable for the release in that sense; the old assignee semantics were arguably wrong on their own terms even before the platform-constraint bug surfaced.

---

## 3. Process-gap ruling: who edits `.claude/agents/*.md` in this repo

A coder subagent attempting a draft of this fix reported it is blocked by its own CORE instruction (`.claude/agents/coder.md` line 83): *"Do not write to your own agent definition file or any other agent's definition file (`.claude/agents/*.md`). These are HOS-managed; edits go through the installer."*

**Ruling: the top-level worker/human-proxy session edits `.claude/agents/*.md` directly in this repo. `coder` is never dispatched for those files, and `coder.md`'s CORE prohibition is not weakened or carved out.**

Reasoning:

1. This is the established, repeated pattern, not an exception: `git log --oneline -- .claude/agents/worker.md .claude/agents/overseer.md` shows direct `hos-worker-hos[bot]` authorship across many commits (e.g. 87337f31, 4450db47, d5a494f6, and others).
2. The actual anti-tampering control is the protected-surface gate, not which agent typed the edit. `.claude/agents/**` is the first entry in `scripts/framework/protected_surfaces.txt`; any PR touching it requires human approval and can never be bot-merged, and `.github/CODEOWNERS` is generated from that same list. This property holds regardless of whether `worker` or `coder` authored the diff.
3. `coder.md`'s prohibition is defence-in-depth for *consumer* projects, where the installed copies of these files carry no such protected-surface gate. Adding a conditional carve-out ("...unless this is the HOS source repo") to a CORE rule that ships to every consumer would be a self-assessed exemption a consumer's coder could reason itself into applying — the same failure class as #556. CORE stays verbatim.
4. The clarification instead lives in this repo's own `CLAUDE.md` (§"Working in this repo"), which is HOS-source-specific, never ships to consumers, and is itself a protected surface.

Practical split applied to this fix: the worker session authored all `.claude/agents/*.md`, `CLAUDE.md`, `contract/OVERSIGHT-CONTRACT.md`, and `docs/MACHINE-ACCOUNTS-SETUP.md` changes directly; `coder` was dispatched only for `scripts/automation/lib/merge_authority.py`, `bootstrap/edit_issue.sh`, and their tests — ordinary application/tooling code, ordinary rules.

---

## 4. Implementation record

Implemented in the same PR as this ADR (issue #1347):

| File | Change |
|---|---|
| `.claude/agents/worker.md` | R1 condition 3 → issue state `open` (assignee removed as a trigger condition); new R0 assignee-write ban (M2); R4 idempotency keyed on `Release candidate SHA`, new step 0 anchor reset (M3), steps 6–7 and the "How to authorize this release" block reworded for self-assignment; R5 replaced in full (current-state conditions, M1 identity-triple check on the authorizing event, three-signal actor check, M4 AWAITING/VIOLATION split with one-time diagnostic comment); R3/R4/R6 failure paths no longer write the assignee field; `ng3b-violation-attempt` `failed_check` enum and example updated; "Re-entry after a bounce" section and the generic `needs-human` "How to authorize" footer no longer reference bot-assignment; script-inventory table documents the new `edit_issue.sh --set-assignee` flag; **Amendment 1** — Step 0.5 in the loop-start precheck, new R1.9 (idempotency-before-R2 precedence + directive-aware R2 deferral), R4 step 0b applies `needs-human`, R5 absent-event→AWAITING split, diagnostic next-actor line |
| `.claude/agents/overseer.md` | Bounce-protocol descriptions (`record_pr_bounce()` mentions, the finalize-step list, the canonical-labels table, the `edit_issue.sh` inventory row) no longer describe an assign-to-bot step |
| `CLAUDE.md` | New clause in "Working in this repo" recording §3 |
| `contract/OVERSIGHT-CONTRACT.md` | `pr-bounced` description and `assigned_to` example updated to reflect the field is always `null` (retained for schema stability) |
| `docs/MACHINE-ACCOUNTS-SETUP.md` | `release-authorized` label description and surrounding prose updated to self-assignment language |
| `scripts/automation/lib/merge_authority.py` | `record_pr_bounce()` — removed the doomed `/assignees` POST call, its `try/except`, and the `assignee` parameter; `assigned_to` is now always `None` in the emitted event |
| `bootstrap/edit_issue.sh` | New `--set-assignee <user\|none>` mode (`PATCH` with a replacing `assignees` array) alongside the existing add-only `--assignee`; required by R4 step 0 |
| `tests/automation/test_bounce_gate.py`, `tests/automation/test_edit_issue.py` | Updated/added to match |
| `bin/hos-cron` | **Amendment 1** — `_build_context()` gains a worker-only `### Open release requests (NG3b)` section, emitted before the "New work directive" section; one `issues?state=open&labels=release-request` call; fail-open |
| `bootstrap/worker-cron-prompt.md` | **Amendment 1** — new LOOP "Step 0.5 — Open release requests" between Step 0 (triage) and Step 1 (check PRs), with context-absent fallback and the R2-deferral rule |
| `docs/OVERSIGHT-RUNBOOK.md` | **Amendment 1** — "Intervening" §1 gains the release-request carve-out: `needs-human` is worker-applied and its removal is an authorization signal |

**Verification obligation — blocking on declaring #1338 unblocked, not on merging this PR.** Before relying on this protocol for an actual release cut, the implementation must capture a live `assigned` event payload from a real human self-assignment on this repo and confirm `actor`/`assignee`/`assigner` resolve as R5 conditions 4–6 expect, and append the finding to `research/findings/api-field-shape-verification.md`. A mocked test cannot catch a wrong field name — it will faithfully mock the wrong field. That is exactly how this repo reached #1347's bug in the first place. This will happen naturally the first time a human authorizes a release under the new protocol (e.g. re-authorizing #1338); no separate drill is required, but the finding must be recorded when it does.

**Affected sign-offs.** Stand unchanged: NG3b's R0 identity guard, R1.5 creator check, R2 tier matrix, R4 HEAD-SHA binding, R6 command-precision check — none of these are touched by this ADR. Also stand: prior approvals of the bounce mechanism's finalize *behavior* (posting the comment, applying `needs-ai`, converting to draft) — the assign call never succeeded, so no reviewed behavior actually changes there, only a dead call and a false audit field are removed. Orphaned by this ADR, requiring re-review against it if revisited: the original R1/R4/R5 assignment-signal design.

**On #1338 specifically:** at the time this ADR was written, #1338 carried `release-request`, `release-authorized`, and `needs-human`, with no assignees. Under the revised R5 it reads AWAITING on two counts (`needs-human` still present; no self-assignment event). Once this fix lands, the next worker cycle re-runs R2–R4 for the current HEAD and posts a fresh authorization request; #1338 does not need to be reset or recreated.

---

## 5. Amendment 1 — protocol wiring and happy-path gaps (2026-08-13)

These were gaps in this ADR's original scope: §1–4 specified the protocol's
*semantics* correctly but did not specify how a release request reaches the
worker on a cron cycle, nor did they trace the happy path end-to-end through
R5's three-signal check. Both are corrected here rather than in a new ADR,
since neither reverses a §1 decision — they complete it. Raised in PR #1348
review (human CODEOWNER, CHANGES_REQUESTED: "This needs a pass through pm,
architect, and tech design agents... docs need updating").

| # | Gap | Ruling |
|---|---|---|
| A1.1 | No trigger — nothing caused the worker to evaluate an open release request on a cycle. A release-request issue never carries `needs-ai`, so it was invisible to the worker's per-cycle work-selection logic (`bootstrap/worker-cron-prompt.md` Step 2 / `next_candidates.jq`), and §4's "the next worker cycle re-runs R2–R4" claim about #1338 was not actually wired to anything. | `bin/hos-cron` `_build_context()` emits a worker-only `### Open release requests (NG3b)` section before the "New work directive"; both `worker-cron-prompt.md` and `worker.md` gain a Step 0.5 that runs NG3b from R1 for each listed issue, **regardless of the New work directive** — NG3b is a standing gate, not new work. Fail-open on the context fetch: omission delays a release but can never authorize one (R5 reads all state live), so failing open costs latency, not safety. |
| A1.2 | R2 ran unconditionally every cycle, re-running the full release validation suite while waiting on a human. | New R1.9 check 1: R4's existing SHA-keyed idempotency condition is evaluated **before** R2; if satisfied, skip straight to R5 (read-only). R1.9 must change no issue state — re-applying `needs-human` there would erase authorization signal 2. |
| A1.3 | A cycle owing a PR fix (`needs-fix`) could instead be consumed by a release validation run. | New R1.9 check 2: `NEW WORK: BLOCKED` / reason `needs-fix` defers R2 for that cycle (stdout log only, no comment, no label). `awaiting-merge` / `needs-attention` do not defer. R5 and R6 are never deferred — an already-authorized release is always verified and executed. |
| A1.4 | **Bug.** On the happy path (validation passes first try) `needs-human` was never applied to the release-request issue, so no `unlabeled` event existed for R5's third signal; with the fail-closed "actor unresolvable → FAIL" rule this misfired `R5.6.3-label` — a false `ng3b-violation-attempt` — on a *legitimate* release. | Two-part, both required: (a) R4's all-pass path applies `needs-human` (new step 0b) after the step-0 anchor reset and before the results comment, fail-closed identically; (b) independently, "no `unlabeled` event exists at all" is AWAITING, not VIOLATION — `R5.6.3-label` fires only on a present-but-disqualified actor. The third signal is **not** made optional: (a) makes it unconditionally present in normal operation, (b) covers only the residual where (a)'s own write failed. `needs-human` does **not** become an R1 trigger condition — R1 stays label-authorization-agnostic. |
| A1.5 | The `<!-- hos-ng3b-awaiting -->` diagnostic said what was missing but not whose move it was — the same "silently unsatisfiable, no signal to the human" failure class as #1347/#1338 itself, one layer down. | Its first line now names the next actor: `Waiting on you (@<CODEOWNER>)` when conditions 1–3 or 9 are outstanding; `Waiting on the worker` when the state is worker-side (HEAD advanced, R2 deferred, or the A1.4(b) residual). |

**Affected sign-offs.** Stand unchanged: R0 identity guard, R1.5 creator check,
R2 tier matrix, R4 HEAD-SHA binding, M1 identity-triple check, M2
assignee-write ban, M3 anchor reset, R6 command-precision check — Amendment 1
touches none of them, and A1.4 strengthens (never relaxes) the three-signal
requirement. Re-review required: none — no code has yet been approved against
the pre-Amendment R4/R5 happy path (the protocol has not executed a release
since this ADR landed; #1338 is still unauthorized). The §4 verification
obligation is unchanged and still blocking on declaring #1338 unblocked.

**On #1338 specifically:** unchanged from §4, with one addition — the next
cycle's R4 re-post now also (re-)applies `needs-human`, so the human's removal
of it becomes a readable third signal. #1338 still needs no reset or
recreation.

**Deferred, not resolved here:** `R5.6.4` (HEAD-advanced) remains classified
VIOLATION rather than AWAITING, even though it is a routine worker-side state
(the worker merges its own PRs) — reclassifying it changes the violation
taxonomy and is out of this amendment's scope; flagged for a future ruling.
The reviewer's `needs-worker`/`needs-overseer` label-taxonomy question is a
separate, larger initiative and is tracked in #1349 rather than folded into
NG3b.

---

## 6. Amendment 2 — R2 failure-path idempotency (2026-08-17)

Gap: R1.9 check 1's idempotency covers only the *success* path — once R2
all-passes and R4 posts an authorization request, an unchanged HEAD skips
straight to R5. There was no equivalent guard on the *failure* path: every
cycle re-ran the full R2 suite from scratch, including any suite already
known to fail deterministically against the current HEAD. On #1338, R2 suite
5 (`scripts/run_second_review.sh`) failed identically across three
consecutive cron cycles against the same HEAD, because the `v0.5.0..HEAD`
release-scale diff (334 files / ~100 PRs / ~1.8M combined input tokens)
exceeds what a single second-review call can process — a deterministic,
diff-shaped failure, not a transient one. Each of the three re-runs re-paid
the full cost: ~4.0M agy tokens (≈201% of its monthly plan allotment) and
~3.2M codex tokens (≈644% of its monthly reserve) in a single day, for zero
additional signal after the first failure established the pattern. Raised in
#1355.

Ruling: extend R1.9 with a third, per-suite check. For each required suite,
find its **anchor comment** — the most recent results comment whose line for
that suite is a fresh (non-restated) result. Skip re-running the suite in R2
only when the anchor's recorded result is a FAIL against the *same* HEAD, *no
human has commented since* the anchor, and *fewer than 6 hours have elapsed*
since the anchor. Any of the three failing forces a fresh run: HEAD advancing
means the diff that caused the failure changed; a human comment may carry new
direction (a waiver, a narrower diff, a process fix); the backoff bounds the
case where the failure is actually transient (e.g. a CLI outage) and would
otherwise never be retried.

The anchor must be a *fresh* result specifically, not simply "the most recent
comment carrying the suite's line" — the first design of this amendment used
the latter and had a self-defeating bug: R3 restates a carried-forward
suite's line verbatim in every cycle's new comment, so "most recent comment"
would keep resolving to the *previous cycle's restatement* rather than the
original failure, and the restatement's `created_at` is the posting time, not
the failure time. That let the 6-hour window reset itself every cycle the
suite stayed skipped, turning the intended backoff into indefinite
suppression — exactly what this amendment exists to prevent. Marking a
restated line (identifiable by its `(skipped — ...)` suffix) permanently
ineligible as an anchor fixes this: the elapsed-time and human-comment checks
always measure from the original fresh failure, however many cycles have
carried it forward since.

This is deliberately per-suite, not R2-wide: cheap, fast, deterministic
suites (`run_tests_release.sh`, `check_agents_static.sh`,
`run_validators.sh`) still run every cycle for fresh-regression signal; only
a suite with a matching anchor FAIL is skipped. R3's results-comment format
gains a `Release candidate SHA:` line (mirroring R4's existing one) so a
later cycle's anchor walk has something to match against, and each suite
entry becomes a fixed, parseable `<suite>: PASS|FAIL (exit <code>) at
<timestamp>` line with a fenced first-line excerpt on FAIL — needed so a
carried-forward skip can restate the anchor's result verbatim rather than
re-deriving it.

**Affected sign-offs.** Stand unchanged: R0 identity guard, R1 trigger
conditions, R1.9 checks 1–2, R4, R5, R6 — this amendment touches none of
them. R2's tier table and PATCH promotion rule are unchanged; only whether a
required suite executes this cycle changes. R3's escalation behavior
(`needs-human`) is unchanged — only its comment format gains the SHA line and
a fixed per-suite line shape.

**On #1338 specifically:** moot — #1338 shipped as v0.6.0 and is closed. This
amendment is prospective, for the next release request that hits a
deterministic R2 failure.
