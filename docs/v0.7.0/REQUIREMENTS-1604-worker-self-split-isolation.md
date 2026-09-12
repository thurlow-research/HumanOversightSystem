# REQUIREMENTS-1604 — A stuck issue must stop itself, not the project: per-issue timeout isolation, a bounded split-or-escalate decision, and a project-wide suspend reserved for the systemic case

**Status:** DRAFT for architect. The mechanism is **structural** — it changes an existing escalation
behaviour (`bin/hos-cron`'s timeout breaker), introduces a new decision point in the worker's cycle,
a new issue state, and a new authority for the worker to create its own work items — and therefore
requires explicit human sign-off before `architect` binds it. Three §0 findings materially change
what must be built relative to the issue text: **VF-2**, **VF-3**, and **VF-6**. Two parameters the
human explicitly delegated to this pass are **bound** in §3, with reasoning; a third threshold that
had to be settled to make the requirements testable is bound alongside them.
**Date:** 2026-09-12
**Author:** pm-agent
**Source issues:** #1604 (open, `enhancement`/`needs-human`/`priority:high`, v0.7.0 — Quality; the
body plus its two 2026-09-12 comments are the binding requirements input, and the comments govern
where they refine the body); #1601, #1602, #1603, #1600 (open, `needs-ai`/`priority:high` — the
#1354 split, the detection primitives this policy consumes); #1354 (open — the parent, and the first
real test case); #1597 (open, `needs-human` — the auto-filed breaker issue from the live incident);
#1353 (the original incident report); #1356 (open, `priority:high` — the `bounce_count` pattern this
design is told to reuse is reported non-functional); #1520 (open — the `needs-ai` label rename).
**Target:** the design chain the human ruled for this issue on 2026-09-12 — pm-agent (this document)
→ `architect` → `technical-design` — then a `needs-ai` implementation issue in v0.7.0.
**Consumers:** `architect` (next), then `technical-design`.
**Scope note:** This document says WHAT and WHY only. No code, file layout, state-store choice,
label spelling, or GitHub-API mechanics are specified here — those belong to `architect` and
`technical-design`. Where a concrete value is given it is a binding default with a stated floor and
an explicit configurability requirement, not an implementation instruction.

---

## 0. Verification findings — where the ruling meets the repo

Every load-bearing claim in the task brief and in #1604 was re-derived from this repo at
`origin/main` = `58b4785a` (fetched 2026-09-12). Line numbers are this commit's.

**Verification gaps, stated up front.** (a) The cron logs at
`/home/scott/Code/HumanOversightSystem/.local/log/` are outside this session's read scope, so every
claim about what the live worker did is derived from the committed audit trail and from GitHub, not
from the logs. (b) This clone sees only audit records that reached `main` via the `audit-log` branch
workflow; an absent record may be an un-synced record (**VF-10** is hedged accordingly). (c) The
Worker and Overseer clones' local state directories (`~/.hos/timeout-breaker/`, `~/.hos/suspend/`)
were not inspected. (d) Nothing was executed against the live cron.

**VF-1 — CONFIRMED, and narrower than the issue implies: the existing timeout breaker is
project-scoped and completely issue-blind.** `bin/hos-cron:1237-1300`. State lives in a single file
per role+project — `${HOS_STATE_DIR:-$HOME/.hos}/timeout-breaker/${ROLE}-${PROJECT}` (`:1248`) —
holding exactly two lines: an attempt count and the cap it was counted at (`:1260`). The counter
increments on any `exit 124` when the cap is unchanged (`:1255-1259`), trips at
`HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS` (default **2**, `:1249`), calls
`hos-suspend --project "$PROJECT"` with no `--until` (`:1265`), files one `needs-human` issue with
fail-closed dedup (`:1278-1297`), and is cleared by a cap change or by any normally-completing cycle
(`:1355-1376`, which also auto-closes the breaker issue). **No issue identity appears anywhere on
this path.**

**VF-2 — CONTRADICTS THE ISSUE'S FRAMING, and widens the defect: today's breaker trips on two
timeouts on two *different* issues.** Because the counter is keyed on role+project only (**VF-1**),
"timed out on #A, then timed out on #B" is indistinguishable from "timed out on #A twice" and
produces an identical project-wide suspension. #1604's premise — *"blind identical retry"* — is one
instance of a broader defect: the mechanism cannot tell same-issue repetition from unrelated-issue
repetition at all. **Design consequence:** "detect a prior timeout *on the same issue*" is not a
refinement of the existing counter; it requires attribution the existing counter does not have
(**VF-6**). A second consequence is decisive for sequencing: if the existing project-scoped counter
is left running in parallel with the new per-issue policy, **it trips first and the new isolation
never executes** (FR20).

**VF-3 — NOT STATED IN THE ISSUE, and enlarges the harm: the suspend marker is keyed on project
only, never on role, so a *worker* timeout also halts the *overseer*.** `bin/hos-cron:199` —
`_SUSPEND_FILE="$_HOS_DIR/suspend/$PROJECT"` — is checked at `:200` before the overlap lock and
before any role branch, and exits 0 for whichever role is firing. So the ~3.5-hour outage #1604
describes did not merely stop new work: it stopped **review and merge of already-approved PRs** for
the same window. The blast radius the issue objects to is understated in the issue itself.

**VF-4 — CONFIRMED, and it makes the isolation half cheap: `needs-human` already removes an issue
from the pick-up queue.** `scripts/automation/lib/next_candidates.jq` — the documented *single source
of truth* for work selection, used both by `bin/hos-cron:771-772` and (inlined, test-pinned) by the
worker's Step-2 fallback — has exactly one eligibility filter:
`select((.labels // []) | map(.name) | index("needs-human") | not)`. **Per-issue isolation therefore
needs no new queue-filtering mechanism**; it needs the label applied to the right issue, plus *not*
calling `hos-suspend`.

**VF-5 — DECISIVE FOR THE DELEGATED THRESHOLD: there are 57 open `needs-human` issues in this repo
right now.** A "count of currently-stuck issues" implemented as a count of `needs-human` issues would
exceed any sane threshold on the first cycle and would never fall back below it. The stuck state MUST
be a distinct, separately-queryable marker that is *narrower* than `needs-human`, even though it also
implies `needs-human` (FR17, FR18).

**VF-6 — CONTRADICTS #1601's PREMISE, and is the single most important finding for sequencing: no
per-issue timeout attribution exists anywhere today, and the "existing interim mitigation" #1601
cites is not in the code.** Three independent checks: (i) the only code that runs after the kill is
`bin/hos-cron`'s post-`124` block (`:1237-1300`), and it never names an issue — a repo search of that
path finds no per-issue comment or label, only the project-level breaker issue (`:1284-1290`);
(ii) work *selection* happens inside the Claude session (the `_GATE_CANDIDATES` block at `:1199-1213`
supplies a candidate **list**, and `bootstrap/worker-cron-prompt.md:95` instructs the agent to
*"pick the first non-blocked candidate"* — the choice is never written anywhere `hos-cron` can read);
(iii) `claude --print` flushes nothing when killed, which is the whole subject of #1603. #1601's body
states that #1353's *"comment + `needs-human` label on the triggering issue after a timeout"* is
*"the current minimum-viable form"* — **that mitigation is not present in `bin/hos-cron` at
`58b4785a`.** #1601 must therefore *build* attribution, not inherit it, and #1604 cannot assume it.

**VF-7 — One durable attribution source already exists, but it is partial.**
`bootstrap/create_branch.sh --issue <N>` creates a cycle-unique branch whose name embeds the issue
number (header example: `worker-967-branch-ownership-260802191500-111`) **and** writes a
branch-ownership record under `<git-common-dir>/hos/branch-ownership` carrying `cycle_id`, `role`,
and `branch` (`bootstrap/lib/branch_ownership.sh:42-50`, written record-first at
`create_branch.sh:121-129`). Both survive the kill and are readable by the next cycle. The limitation
is coverage, not durability: the record only exists once the cycle reached branch creation, and the
#1354 incident produced *"zero commits either time"*, so how far those cycles got is unknown. Usable
as one attribution source; not sufficient alone.

**VF-8 — The audit stream is a viable substrate here, unlike in the `bounce_count` case — but the
event carries no issue.** 19 committed `cycle-claude-timeout` records exist under `audit/log/**`. A
representative record is complete and verbatim:
`{"event":"cycle-claude-timeout","limit":1800,"role":"worker","timestamp":"2026-08-13T20:33:14Z"}`.
So the write→sync→commit path for cron timeout events demonstrably works (`_audit` at `:298-301`,
`_sync_audit_logs` unconditionally at `:1431`), and an audit-derived per-issue counter is feasible —
**after** the event gains issue attribution.

**VF-9 — CAUTION on the pattern #1601 is instructed to copy: `bounce_count` is reported
non-functional.** #1356 (open, `bug`/`process-gap`/`priority:high`) records **zero `pr-bounced`
events across 189 audit records**, and states the consequence plainly: *"`bounce_count(cid) >= 2`
… cannot work: a PR could be bounced indefinitely without ever escalating."* `bounce_count()` itself
(`scripts/automation/lib/merge_authority.py:977-994`) is a sound *shape* — derive the count from the
append-only audit stream rather than from separate state — but its **write** side is unproven on the
live path. Copying the read shape without demonstrating the write is the precise way this new
mechanism would fail silently, and silently is the worst available failure here: an escalation that
never fires looks exactly like an escalation that was never needed.

**VF-10 — A live instance of that same class, observed here.** No `cycle-timeout-breaker-tripped`
record exists anywhere in the committed audit trail, although the breaker demonstrably tripped:
#1597's body is verbatim the printf template at `bin/hos-cron:1288`, and the **same cycle's**
`cycle-claude-timeout` record (`2026-08-17T170243Z`) *did* land. `_audit` swallows every error
(`2>/dev/null || true`, `:300`) and the sync is unconditional (`:1431`), so the cause is not visible
from the code. Hedged per verification gap (b): this could be a sync gap rather than a lost write.
Either way, **a new escalation policy must not be built on an audit write that has not been
demonstrated end to end** (FR22).

**VF-11 — The cost figure in #1604 is a floor, not a bound.** The last `cycle-start` of any kind in
the committed trail is `2026-08-17T163242Z` and the last timeout `2026-08-17T170243Z`; there are
**no September cron cycle events at all** (September contains only `subagent-model-resolved`
records). This does not contradict the issue's *"~3.5 hours"* — that figure plausibly describes one
specific window, and the marker may have been cleared and later re-tripped — but the trail is
consistent with a far longer autonomous outage, and (per **VF-3**) one that took the overseer with
it. Do not treat 3.5 hours as the worst case this design must beat.

**VF-12 — The human's own split of #1354 is the worked example the split requirements should be
measured against, and it is *almost* complete.** #1600/#1601/#1602/#1603 each name the parent, scope
themselves to exactly one requirement ("this is R1 only"), and list the siblings' scope under
*"Explicitly out of scope"*. The one genuine dependency is recorded — but only on the **dependent**
side, in #1604's own *"should be sequenced after both land"*. The four siblings do not state any
ordering among themselves (they are genuinely independent, so none was needed). An automated split
must reach at least this bar, and must state ordering **on both sides** of a dependency, since a
blocker that does not know it is blocking cannot be checked from the blocker's own page (FR11).

**VF-13 — Do not hard-code the label spelling.** The state-label taxonomy that renames `needs-ai` to
`needs-worker`/`needs-overseer` is designed (#1349, **closed**) but unimplemented (#1520, **open**,
v0.7.0). Requirements below name label *semantics* ("the marker that removes an issue from
autonomous selection"), and FR25 requires the mechanism to survive the rename.

---

## 1. Context

The failure this responds to is not "a task was too big". It is that **the system's response to one
task being too big was to stop the whole system**, and that it could not have responded any other
way, because it never knew which task was involved (**VF-1**, **VF-2**, **VF-6**).

`bin/hos-cron`'s breaker is a good token-burn brake and a bad work-scheduling policy. As a brake it
is correct and should survive: two consecutive full-session burns producing nothing is worth
stopping. As a policy it conflates three different situations that deserve three different responses:

| Situation | Correct response | Today's response |
|---|---|---|
| One issue is too large to finish in a cycle | Split it, or park **it** | Suspend the project |
| One issue is genuinely intractable for an agent | Park **it**, keep working | Suspend the project |
| Everything is timing out (broken env, broken dep, pipeline bug) | Suspend the project | Suspend the project |

Only the third row is right today, and it is right by accident — the mechanism cannot tell the rows
apart. #1604 asks for the first two rows to be handled by isolating the *issue*, and for the third
row to remain the project-wide response, entered on evidence of a *pattern* rather than on evidence
of *one hard task*.

Two things make this more than a threshold change. First, the worker gains a genuinely new
authority — **creating its own work items** — which is why the linkage and sequencing requirements
(FR10–FR13) are the strictest in this document: an unlinked or dependency-hiding split does not merely
fail to help, it manufactures conflicting parallel work, which is worse than the stall it replaced
(the human's own words: *"a bad split is worse than no split"*). Second, the project-wide suspend
stops being the first response and becomes the last one, so the conditions for reaching it must be
stated positively and must remain reachable (FR19–FR21) — otherwise this change trades a
too-eager brake for no brake.

---

## 2. Functional requirements

Each FR is testable; the *Verify* line states the acceptance check.

**Terminology.** A **timeout** is a cycle that ended in the condition `bin/hos-cron:1237` treats as a
wall-clock kill. **Attribution** is the association of a timeout with the specific issue the killed
cycle was working on. An issue is **stuck** when this mechanism has concluded no further autonomous
attempt should be made on it and has handed it to a human. The **pick-up queue** is the candidate set
produced by `next_candidates.jq` and its inlined twin. A **sub-issue** is an issue this mechanism
created by splitting a **parent**.

### Trigger and attribution

**FR1 — A timeout MUST be attributable to a specific issue, using state that is written before the
kill and survives it.** The killed session cannot record anything (**VF-6**), so attribution MUST NOT
depend on any action taken by the agent at or after the kill. It MUST come from state written earlier
in the cycle and readable by a later, independent process.
*Verify:* kill a cycle at an arbitrary point after work selection and confirm an independent process
can name the selected issue; repeat with the kill placed before branch creation and confirm the
answer is still correct or is an explicit "unknown" (FR3), never a wrong issue number.

**FR2 — Attribution MUST be recorded durably and MUST NOT rely on an unverified write path.** The
record MUST survive across cycles and MUST be demonstrated end to end — written, synced, and read
back — before any policy depends on it. A counter derived from records that are never written is
indistinguishable from "this has never happened" (**VF-9**, **VF-10**).
*Verify:* an automated test drives two attributed timeouts on the same issue through the real write
path and asserts the counter reads 2 on a subsequent, separate process; the test fails if the write
is skipped, and does not pass by mocking the store.

**FR3 — Unattributable timeouts MUST fail closed to a project-level response, never be silently
dropped.** If a timeout cannot be attributed to an issue, the mechanism MUST NOT guess, and MUST NOT
treat the cycle as harmless. Consecutive unattributable timeouts MUST still be able to reach the
project-wide suspend (FR21), because the token-burn brake must not be removable by an attribution
failure.
*Verify:* with attribution disabled or failing, repeated timeouts still trip a project-wide suspend
within the configured attempt count; no issue is labelled on the basis of a guess.

**FR4 — Attribution MUST distinguish a wall-clock kill from other causes of the same exit condition,
or MUST be tolerant of failing to.** #1353 records that `exit 124` is not exclusive to `timeout`, and
that the current audit event reports the *configured* cap rather than observed elapsed time — so a
non-timeout `124` is relabelled as a 30-minute wall-clock kill that never happened. The decision
threshold (D-3) is set at 2 partly to absorb this; if the ambiguity is resolved (e.g. by recording
observed elapsed time), the mechanism MUST NOT thereby become more eager than D-3 without a human
ruling.
*Verify:* a simulated non-wall-clock `124` does not, on its own, mark any issue stuck.

### The decision point

**FR5 — On reaching the decision threshold (D-3) for an issue, the worker MUST NOT attempt that issue
again unchanged.** Exactly one of two outcomes MUST occur: the issue is split (FR7) or the issue is
marked stuck (FR14). There is no third outcome, and "retry once more" is not available.
*Verify:* an issue at threshold is never selected again in its original form; a test asserts the two
outcomes are exhaustive.

**FR6 — The decision MUST happen before build work in the cycle, and MUST be cheap enough that it is
not itself at risk of the failure it responds to.** Assessing and splitting is a bounded reading and
issue-filing task, not a build. It MUST NOT run the design/review chain.
*Verify:* a cycle whose only action is a split completes well inside the configured cap, with no
build agents invoked.

**FR7 — A split is permitted only when the issue decomposes into sub-deliverables that are each
independently completable, and the worker can say what each one is.** The assessment MUST be made
against the issue's own content and, when available, the record of what the prior attempt achieved
(#1602's checkpoint, #1603's record). It MUST NOT be made from the issue's size or title alone.
*Verify:* a fixture set of issues — one cleanly decomposable (#1354 is the canonical positive case,
and the human's manual split into #1600–#1603 is the reference answer), one atomic (e.g. a single
bug fix in one function), one ambiguous — produces split / no-split / no-split respectively.

**FR8 — When decomposition is not clearly warranted, the outcome MUST be "no split", unconditionally
and without penalty.** This is the primary fallback, not a last resort. A partial split, a
"best-effort" split, or a split into pieces that do not correspond to independent deliverables is
non-compliant. The human's ruling is binding and is stated here as a requirement rather than as
guidance: *a bad split is worse than no split; when in doubt, escalate rather than decompose.*
*Verify:* the ambiguous fixture in FR7 produces a stuck issue and zero new issues; no code path
exists that emits a sub-issue set of size 1, or a set whose members restate the parent.

**FR9 — A split that cannot be completed MUST leave no partial split behind.** If the cycle
performing a split is interrupted (including by a timeout), the next cycle MUST be able to detect the
incomplete split and MUST NOT produce a second, overlapping set of sub-issues. Either the split
completes and is recorded as complete, or it is cleanly reversible/resumable.
*Verify:* interrupt a split after the first sub-issue is filed; the next cycle produces no duplicate
sub-issues, and the end state is either a completed split or a clean retry of the same split.

### Sub-issue quality: linkage and sequencing

**FR10 — Every sub-issue MUST identify its parent, and the parent MUST identify every sub-issue.**
The linkage MUST be bidirectional and machine-readable, not merely narrative.
*Verify:* from any sub-issue, the parent is resolvable; from the parent, the complete sub-issue set
is resolvable; a sub-issue set with a missing back-link fails the check.

**FR11 — Sequencing between sub-issues MUST be recorded explicitly, on both sides of every
dependency.** Where sub-issue B cannot begin until A completes, this MUST be stated on B (what it
waits for) **and** on A (what waits on it). A dependency recorded only on the dependent side is
non-compliant: a blocker that does not know it is blocking cannot be checked from the blocker's own
page (**VF-12**). Where no dependency exists, the split MUST say so explicitly — "these are
independent" is an assertion the split makes, not an absence of information.
*Verify:* a split with a dependency yields both directions of the statement; a split asserting
independence says so in a form a later reader can find; a hidden dependency (present in neither
direction) fails.

**FR12 — A sub-issue that depends on an incomplete sub-issue MUST NOT be selectable for autonomous
work while its blocker is open.** This is what makes FR11 load-bearing. Recording a dependency in
prose while leaving both sub-issues in the pick-up queue reproduces exactly the failure the human
identified — *"two cycles building conflicting work in parallel without realizing it"* — with the
added harm that the record makes it look handled.
*Verify:* with A open, B is absent from every work-selection path; when A closes, B becomes
selectable without human action.

**FR13 — If FR12's exclusion cannot be enforced, dependent splits MUST be refused.** The fail-closed
fallback to FR12 is to allow only fully independent decompositions: if the assessment finds a
dependency and the mechanism cannot hold the dependent out of the queue, the outcome MUST be "no
split" (FR8), not "split and hope".
*Verify:* with dependency enforcement disabled, an issue whose decomposition contains a dependency
produces a stuck issue and zero sub-issues.

**FR14 — Sub-issues MUST be actionable in the same terms as hand-filed work.** Each MUST carry the
context needed to be worked without re-reading the parent's full history, and MUST inherit the
parent's milestone and priority unless the assessment states a reason otherwise. The parent MUST be
converted to a tracking item and removed from the pick-up queue, so that the split does not leave the
original selectable.
*Verify:* each sub-issue is selectable and workable on its own; the parent is never selected again;
milestone and priority match the parent's.

### Bounding the recursion

**FR15 — A sub-issue MUST NOT be split.** An issue created by this mechanism reaching the decision
threshold MUST be marked stuck (FR16), never decomposed further. The worst case is therefore bounded
at: attempts on the parent up to the threshold, one split, attempts on each sub-issue up to the
threshold, then a human — with no possibility of an ever-widening tree.
*Verify:* a sub-issue driven to threshold produces a stuck issue and zero new issues; a test asserts
no reachable path creates a grandchild.

**FR16 — The split-origin marker MUST be durable and MUST NOT be erasable as a side effect of normal
work.** FR15 depends on knowing an issue is a sub-issue. If that fact can be lost — by an edit, a
relabel, or a re-triage — the recursion bound is lost with it.
*Verify:* relabelling and editing a sub-issue does not make it split-eligible.

### Isolation, and the reserved project-wide response

**FR17 — A stuck issue MUST be removed from the pick-up queue and handed to a human, and the worker
MUST continue with all other work in the same cycle and every later cycle.** This is the central
behaviour change. No project-wide pause, no effect on any other issue, no effect on the overseer.
*Verify:* with one stuck issue present, the next cycle selects the next eligible candidate and
completes normally; the overseer's cycle is unaffected; `hos-suspend` was not called.

**FR18 — The stuck state MUST be a distinct, queryable marker, narrower than the generic
human-attention label.** It MUST also result in the issue's exclusion from the queue (which the
existing `needs-human` semantics already provide — **VF-4**), but the count in FR19 MUST be derived
from the narrow marker only. Deriving it from the generic label is non-compliant and would trip a
project-wide suspend immediately and permanently: there are **57** open `needs-human` issues today
(**VF-5**).
*Verify:* the count query returns 0 against the current repository state with no timeout-stuck issues
present; adding one stuck issue makes it 1.

**FR19 — The project-wide suspend MUST be conditioned on the number of issues *currently* stuck by
this mechanism, not on a rate, and not on any single issue's history.** The binding form and value
are in §3 (**D-1**, **D-2**): a live count of currently-open, currently-stuck issues, threshold
**3**, configurable, floor 2.
*Verify:* two simultaneously stuck issues do not suspend the project; a third does; resolving one
below the threshold restores normal operation on the next cycle without a manual counter reset.

**FR20 — The existing project-scoped consecutive-timeout trip MUST be superseded, not run in
parallel with, the per-issue policy.** At its default of 2 (**VF-1**) the existing counter trips on
the second timeout regardless of which issues were involved (**VF-2**) — so if it is left in place
unchanged, it fires before the per-issue policy can ever act, and this entire mechanism is dead code.
*Verify:* two timeouts attributed to two different issues do not suspend the project; two timeouts
attributed to the same issue reach the decision point (FR5) rather than a suspension.

**FR21 — The project-wide suspend MUST remain reachable, and the token-burn brake MUST NOT be
weakened.** It MUST still be entered for: the FR19 multi-issue condition; consecutive unattributable
timeouts (FR3); and any condition that today suspends for reasons other than repeated timeouts (the
usage-limit breaker is out of scope and unchanged — §4). Its existing properties MUST be preserved:
no `--until`, a `needs-human` issue filed with fail-closed dedup, and auto-clear on a normally
completing cycle (**VF-1**).
*Verify:* each listed condition still produces a suspension; the suspension still requires an
explicit clear; a normal cycle still auto-closes the standing breaker issue.

**FR22 — Every state transition this mechanism makes MUST be visible in the audit trail, and the
write MUST be verified rather than assumed.** At minimum: an attributed timeout, a decision-point
outcome (split / stuck), each sub-issue created, and any project-wide suspend. Given **VF-10** —
where the breaker's own trip event is absent from the trail while the same cycle's timeout event is
present — "we emit an event" is not evidence that the event exists.
*Verify:* a test drives one full sequence and asserts each event is present in the committed trail,
read back by a separate process; the test fails if any event is emitted but not readable.

**FR23 — A human MUST be able to see, at a glance, which issues are stuck and why.** For each stuck
issue: how many attributed timeouts it accumulated, whether a split was attempted and what the
assessment concluded, and whether it is a sub-issue of a prior split.
*Verify:* one query returns the stuck set; each member carries the three facts; the reason for "no
split" is recorded rather than implied by the absence of sub-issues.

### Compatibility

**FR24 — Clearing a stuck state MUST be a human act with an obvious mechanism, and MUST return the
issue to normal selection.** A human who splits, rescopes, or simply re-authorizes a stuck issue must
be able to put it back in the queue without editing state files. Whether the accumulated timeout
count resets on that act is **Q3** (§6).
*Verify:* removing the stuck marker returns the issue to the candidate set on the next cycle.

**FR25 — The mechanism MUST NOT hard-code label spellings that #1520 will change.** `needs-ai` is
scheduled to become `needs-worker`/`needs-overseer` (**VF-13**). The requirement is on the semantics:
"excluded from autonomous selection", "awaiting a human".
*Verify:* the rename can be applied without touching this mechanism's decision logic; a search finds
the label names in one place, not scattered through the policy.

**FR26 — Work-selection eligibility MUST stay defined in one place.** `next_candidates.jq` is the
documented single source of truth, with its twin inlined in the worker prompt and pinned by
`tests/automation/test_next_candidates.py` (**VF-4**). Any new exclusion (stuck issues, FR17;
blocked sub-issues, FR12) MUST be expressed there and in the twin, in lock-step.
*Verify:* the existing lock-step test covers the new exclusions and fails if the two diverge.

---

## 3. Delegated parameters — bound here, with reasoning

#1604's 2026-09-12 comment left two parameters open and the human's brief for this pass directed
that they be settled now rather than deferred. Both are bound below. A third threshold had to be
settled to make FR5 testable, so it is bound alongside them. All three are **defaults with a stated
floor and a configurability requirement** — the human retains the values.

**D-1 — The systemic signal is a live count of currently-stuck issues, not a rate over a window.**
**Bound: live count.** I concur with the human's recommendation, and the reasons are stronger than
"a rate is awkward":
1. **It is self-clearing by construction.** The suspend condition is a predicate over *current*
   state, so resolving a stuck issue decrements it immediately. A rate has to decide when to forget,
   and every answer is wrong somewhere — the two failure modes the human named (false trip during a
   rough patch, never resetting cleanly) are not implementation defects but consequences of
   history-dependence.
2. **It needs no new persistent counter and no clock.** It is a query over live GitHub state
   (FR18). Given **VF-9** and **VF-10** — two independent instances of an audit-derived counter in
   this repo that is not demonstrably incrementing — a design that avoids depending on a new durable
   counter for its *most consequential* decision is materially safer.
3. **It is idempotent across cycles, roles, and clones.** The existing breaker's state file is
   per-clone and per-role (**VF-1**), so the worker and overseer clones cannot agree about it. A
   label query gives the same answer to anyone who asks, including the human.
4. **It is directly observable.** A human can run the same query and see exactly what the machine
   sees — which is the property that matters most in an oversight system.

*Accepted consequence, recorded so the architect does not "fix" it:* a live count does not decay. If
three issues become stuck over three months and nobody triages them, the project suspends. **This is
correct, not a defect.** An accumulating backlog of work the autonomous system cannot finish *is* a
systemic signal about the project, the remedy is cheap and visible (a human triages three issues),
and the suspension is cleared the same way every other suspension is. Adding a decay rule to avoid it
would reintroduce exactly the history-dependence D-1 rejects. The single acknowledged alternative — a
staleness rule that stops counting issues stuck for longer than some age — is recorded here as
considered and rejected, not as an open question. If the human prefers it, it is a one-line change to
this ruling.

**D-2 — The multi-issue threshold is 3 distinct currently-stuck issues. Floor: 2. MUST be
operator-configurable**, in the same family as the existing `HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS`.
Reasoning, which turns entirely on the asymmetry of the two errors:
- **Too low costs the thing this issue exists to prevent.** Two genuinely hard issues in a backlog is
  ordinary composition, not a broken environment. At a threshold of 2, a project with a couple of
  research-grade issues in it suspends on normal backlog variance — a smaller version of #1597.
- **Too high costs very little, because isolation already contains the damage.** Each stuck issue is
  already out of the queue (FR17), so the marginal cost of waiting for a third is not wasted cycles
  on stuck work — it is only the delay in noticing a systemic cause. The worker keeps making
  progress the whole time.
- **3 is the smallest number that distinguishes "a pattern" from "a coincidence"** while staying
  well inside human attention: three unrelated issues failing the same way is a signal that survives
  a reasonable person's scepticism, which is precisely the bar the human set ("several unrelated
  issues failing the same way at once is a different kind of problem").
- **The floor of 2 exists because 1 is not "multiple"** — a threshold of 1 reproduces today's
  behaviour exactly and would silently undo the issue.

**D-3 — The per-issue decision threshold is 2 attributed timeouts on the same issue.** Not delegated
explicitly, but required for FR5 to be testable, and #1604's point 3 already uses this number for
sub-issues (*"times out twice in a row"*). Applied uniformly to parents and sub-issues:
- **It matches the incident.** #1354 timed out exactly twice; under this design the third cycle
  splits it — which is precisely what the human then did by hand into #1600–#1603.
- **It absorbs the exit-124 ambiguity (FR4, #1353).** A single `124` is not reliable evidence of a
  wall-clock kill; requiring two makes a spurious split or a spurious park much less likely. Since
  *"a bad split is worse than no split"*, a hair trigger is the wrong direction here.
- **It is consistent with both existing `>= 2` precedents in this codebase** —
  `HOS_TIMEOUT_BREAKER_MAX_ATTEMPTS` (**VF-1**) and `bounce_count(cid) >= 2` — so the escalation
  shape stays recognisable rather than introducing a third convention.
- **It keeps the worst case small and countable:** 2 parent attempts + 1 split cycle + 2 attempts per
  sub-issue, then a human. MUST be configurable; floor 2 (a threshold of 1 splits on a single
  possibly-spurious signal).

---

## 4. Sequencing against #1601 / #1602 / #1603 — the dependency is real, and larger than #1604 states

#1604 says it *"should be sequenced after both land"* (#1601, #1602). Verification changes that
picture in one important way.

**Hard prerequisite: #1601, with its scope corrected.** #1604's trigger is "this issue timed out
before", which requires per-issue attribution and a per-issue counter. #1601 owns that. But #1601's
body assumes it is *generalising* an existing mitigation — *"#1353's interim mitigation (a comment +
`needs-human` label on the triggering issue after a timeout) is the current minimum-viable form"* —
and **that mitigation is not in the code** (**VF-6**). #1601 therefore has to build the harder half
first: determining *which issue* a killed cycle was working on, from state that survives the kill
(FR1). That is a real design problem, not a counter-shaped one, and it is currently invisible in
#1601's scope. **Recommendation: comment on #1601 before it is picked up**, naming attribution as
in-scope and pointing at the two candidate sources verified here — the branch-ownership record and
branch name (**VF-7**, durable but only present once a branch exists) and an in-flight selection
marker written at selection time (nothing like it exists today). Without that, #1601 may land a
counter with nothing to count, and #1604 would then be blocked on a dependency everyone believed had
shipped.

**Soft prerequisite: #1602.** Its checkpoint improves the split assessment's *quality* (FR7 —
"what got done last time" is the best evidence for where the natural seams are). It is not required
for the trigger. #1604 can be built and correct without it; the splits will be less well-informed.

**Soft prerequisite, and under-credited: #1603.** The streamed/checkpointed session record is the
second-best evidence for FR7 (which agents ran, how far the chain got) **and** an independent
attribution source for FR1 (which issue was selected). #1604 does not list it as related; on the
evidence it is more useful to this design than #1602 is. Worth adding to #1604's Related list.

**Current state (2026-09-12):** #1601, #1602, #1603, #1600 are all **open**, `needs-ai`,
`priority:high`, v0.7.0, none built. So: **this design may proceed through `architect` and
`technical-design` now** — nothing in the design work depends on those landing — **but
implementation MUST NOT begin before #1601 lands with attribution included.** If the architect
concludes attribution belongs *here* rather than in #1601, that is a defensible split of the work and
should be stated explicitly so #1601 can be rescoped rather than duplicated.

---

## 5. Explicit non-goals

- **Fixing the timeout itself.** #1354's R1–R4 own durability, streaming, and budget measurement.
  This is the response policy only.
- **Building the detection primitives.** #1601/#1602 own them (§4), subject to the attribution
  correction above.
- **The usage-limit breaker** (`bin/hos-cron:1306-1352`, #1446). It trips on first detection, is
  deliberately project-wide, and is a different signal entirely — a limit from the vendor's side,
  not a hard task. Untouched.
- **Changing `HOS_CRON_MAX_SECONDS`.** #1600 owns the budget question.
- **Making the split smarter over time.** No learning, no heuristics tuned from history. The
  assessment reads the issue and the prior attempt's record, and that is all.
- **Splitting PRs.** `docs/PR-SIZE-POLICY.md` and `.claude/agents/worker.md:191` already govern PR
  size; this is about issues.
- **Fixing #1356 / #1289.** The audit write/read seam defects are cited as a hazard this design must
  not inherit (FR2, FR22), not as work this issue takes on.
- **Role-scoped suspension.** **VF-3** shows a worker timeout also halts the overseer. That is a real
  defect and arguably should be fixed — but it is a change to `hos-suspend`'s granularity, affecting
  every suspend reason, and folding it in here would widen this issue substantially. **Q4**.

---

## 6. Escalated to the human

The delegated parameters are bound (§3) and are not re-opened here. These four are genuine product
decisions this pass could not settle.

**Q1 — Amending #1601's scope (§4, VF-6).** *Recommendation:* comment on #1601 stating that
per-issue attribution is in scope for it, and that the "existing interim mitigation" its body cites
is not present in the code. *Human owns:* whether attribution lands in #1601 or becomes this issue's
own first requirement. Either is workable; what is not workable is both issues assuming the other
has it.

**Q2 — Who performs the split assessment, and under whose identity the sub-issues are filed.**
*Recommendation:* the worker, in its own cycle, under the worker App identity — it has the context
and the existing `bootstrap/create_issue.sh` path. *Human owns:* confirming this, with one
interaction worth noting: #1540's design makes issue **authorship** the trust signal, so
worker-authored sub-issues would be trusted by construction. That is defensible (their content
derives from an already-approved parent), but it means this mechanism is a path by which the worker
creates its own authorized work, and #1540's implementer should know it exists rather than discover
it. If that is unwelcome, the alternative is sub-issues that inherit the parent's approval explicitly
rather than by authorship.

**Q3 — Does a human's clearing of a stuck issue reset its timeout count (FR24)?**
*Recommendation:* **yes, reset.** A human who looks at a stuck issue and returns it to the queue has
made a judgement, and carrying the old count forward would send it straight back to the decision
point on its next timeout, making the human's act nearly meaningless. *Human owns:* the opposite
choice is defensible for an issue a human waved through without changing anything.

**Q4 — Role-scoped suspension (VF-3, §5).** *Recommendation:* file separately; do not widen this
issue. *Human owns:* whether the overseer being halted by a worker timeout is urgent enough to fold
in here. Note it partially self-resolves — under FR17 most single-issue timeouts will no longer
suspend anything at all.

---

## Human Review Required

**RISK: MEDIUM–HIGH.** This document changes an existing safety brake. The brake is currently too
eager (**VF-1**, **VF-2**, **VF-3**) and the change makes it less eager on purpose; the failure mode
of getting it wrong is an autonomous worker that burns tokens on an unfinishable task without ever
stopping. Four specific ways that could happen are closed positively rather than cautioned about:
attribution failure must still reach the project-wide brake (FR3); the counter must be demonstrated
to increment through the real write path, because this repo has two live instances of one that does
not (FR2, FR22, **VF-9**, **VF-10**); the existing project-scoped trip must be *superseded* rather
than left running in parallel, or the new policy is dead code (FR20, **VF-2**); and the stuck-issue
count must use a narrow marker, since counting `needs-human` would trip permanently against today's
57 open such issues (FR18, **VF-5**). The second-largest risk is the split itself: a dependency-hiding
split manufactures conflicting parallel work, which is why FR11–FR13 require both-sided sequencing
with enforcement, and refusal to split when enforcement is unavailable.

**CONFIDENCE: HIGH** on §0 — every finding was re-derived from `origin/main` (`58b4785a`) this
session, including the three that correct or extend the issue text (**VF-2**, **VF-3**, **VF-6**).
**HIGH** on the FR set's shape, which follows #1604's two ruling comments rather than re-deriving
them. **MEDIUM-HIGH** on the three bound parameters (§3): the reasoning is stated in full precisely
so the human can overturn any of them cheaply. **LOWER** on anything downstream of the stated
verification gaps — the unreadable cron logs, the possibility that **VF-10**'s missing event is a
sync gap rather than a lost write, and the uninspected local state directories.

**BLAST RADIUS:** `bin/hos-cron`'s timeout and escalation path; `hos-suspend` entry conditions;
`next_candidates.jq` and its test-pinned twin (work selection for every autonomous cycle); the issue
graph itself, since the worker gains authority to create issues. Indirectly, the overseer — today via
**VF-3**, and after this change by no longer being halted for a single worker timeout.

**Change classification: STRUCTURAL.** It changes existing escalation behaviour, adds a new decision
point to the worker's cycle, adds a new issue state, and grants the worker a new authority. Per my
role this requires explicit human sign-off before `architect` binds it, and the four §6 escalations
must be ruled before `technical-design` depends on them.
