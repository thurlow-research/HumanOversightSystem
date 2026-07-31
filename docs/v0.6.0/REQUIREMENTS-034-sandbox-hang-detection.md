# REQUIREMENTS-034 — Sandbox worker + overseer: hang detection, durable recording, next-run behavior change

**Status:** DRAFT for architect. Six product decisions escalated to the human (§5); architect
may proceed on the settled requirements but MUST NOT bind the escalated points until the human
rules them.
**Date:** 2026-07-31
**Author:** pm-agent
**Source issue:** #1146 — "Sandbox worker + overseer, with hang detection, durable recording, and
next-run behavior change."
**Consumers:** `architect` (next), then `technical-design`.
**Scope note:** This document says WHAT and WHY only. Every intervals-and-thresholds *number*
below is a recommended default with a stated floor; the binding values are the human's (§5). No
file layout, schema, or mechanism is specified here — those belong to `architect`.

---

## 0. Verification findings — where the draft requirements meet the repo

I verified every load-bearing claim against the working tree and, where the working tree is behind
`origin/main`, against `origin/main`. Five findings change the draft rather than merely confirm it.

**VF-1 — This is not greenfield; the autonomous loop already has a breaker/ledger/recovery
substrate the requirements must extend, not duplicate.** `scripts/automation/lib/` already
contains: a per-issue poison-pill failure cap (`breakers.py:is_poisoned`, default `max_failures=3`),
a coarse per-task runtime ceiling (`breakers.py:runtime_exceeded`, default 4h, fail-closed), an
*external* dead-man's switch (`breakers.py:dead_man_triggered`, 6h, explicitly "MUST be run by an
EXTERNAL process — a dead loop cannot report its own death"), a committed append-only run ledger
(`ledger.py`, under `audit/automation/<customer>/runs/`), a committed per-entry cycle audit trail
(`cycle_log.py`, under `audit/log/<YYYY>/<MM>/`, with a `halt` / `escalate` / `heartbeat` event
vocabulary), correlation-id derivation + a `ResumeState` cold-start recovery table
(`correlation.py`), and claim heartbeating with stale-claim reclamation
(`claim.py`: heartbeat ≤15m, stale claim re-claimable after 45m). **No per-command watchdog or
hang-detection layer exists.** The requirements below are the missing layer; they must reuse the
existing durable audit locations, the cid, and the cold-start model, and must not reinvent them.

**VF-2 — "no output + no return" (draft R1) is not a sound discriminator, and elapsed-time-alone is
worse.** A permission prompt is not silence — it emits a prompt. And legitimate operations run
many minutes with little output: the cross-vendor review calls are internally capped at
`AI_REVIEW_TIMEOUT` (default **300s**, per `research/findings/the-gate-must-time-out-its-own-dependencies.md`),
and test suites run longer. A single elapsed-time bound low enough to catch a prompt-hang promptly
would false-kill a real review; a bound high enough to never false-kill a review would let the hang
hold locks for minutes each time. The discriminator that actually holds is structural, not
temporal: **a legitimately long operation is bounded internally and returns control; an
unanswerable-prompt hang is not bounded and never will.** FR3 and §5-Q1 are rewritten around this.

**VF-3 — The draft conflates two things that need opposite lifetimes (draft R2 vs R4).** The
*record that a hang happened* is audit history and must be permanent (you do not expire history).
The *active directive derived from a hang* — "do not reissue this command / rewrite it / this is
escalated" — is exactly the kind of open-ended override that
`research/findings/an-override-must-expire-or-it-becomes-the-policy.md` shows becomes silent policy.
FR6 and FR7 split these: permanent record, expiring directive.

**VF-4 — `.claudetmp/` is not the only ephemeral trap; `.ai-local/` is the same trap (draft R2).**
The existing failure-cap and dead-man state live under `.ai-local/hos-automation/` (`breakers.py:30`),
which `CLAUDE.md` lists alongside `.claudetmp/` as "do not commit." Both reset per clone.
`research/findings/convergence-ledger-must-persist.md` is explicit that state a gate's behavior
depends on cannot be per-machine. The hang ledger's *behavior-changing* content (FR8) therefore may
live in neither. FR6 requires a committed, version-controlled location — the `audit/` tree already
provides one.

**VF-5 — The draft's remediation ordering is backwards for this repo (draft R3).** Draft R3 makes
"rewrite into allowlistable form" primary and "promote to a committed script" a tertiary fallback
for recurrence. But `CLAUDE.md` "Shell usage under the sandbox" already prescribes the opposite as
the standing rule: *"Use an existing script in `scripts/`… If none fits, write one, commit it, then
invoke it… Never inline logic."* An unallowlistable ad-hoc command is, by that rule, already a
process violation whose *correct* remediation is a committed script — not a cleverer one-liner.
FR8 reorders accordingly and constrains ad-hoc rewriting, because a silently-rewritten command that
now does something subtly different is a new fail-open (`research/findings/a-guard-that-doesnt-halt-is-not-a-guard.md`
— do not limp forward in an inconsistent state).

---

## 1. Context

Under an OS-enforced sandbox, a command whose full text is not known before it runs cannot be
matched by any permission rule, so the harness prompts for approval. In an interactive session that
costs one keystroke. In an autonomous `worker`/`overseer` cron cycle there is nobody to answer, so
the process **blocks indefinitely**, holding whatever claim, lock, branch, or PR-evaluation state it
held, until an external actor kills it. Shell-usage discipline (PR #1145) lowers the *frequency* but
cannot make it *impossible*: one unallowlistable command anywhere in a cycle is enough, and the
agent authoring the command cannot reliably predict how the matcher will parse it.

The system therefore needs three capabilities, in order: **detect** the hang while it is happening,
**record** it where the record survives and can change behavior, and **change the next run** so the
same command does not silently hang again — all without becoming a permanent self-inflicted block
and without ever failing silently.

---

## 2. Functional requirements

Each FR is testable; the *Verify* line states the acceptance check. "The cycle" means one autonomous
`worker` or `overseer` cron iteration keyed to a correlation-id (cid).

### Scope and detection

**FR1 — Coverage.** Hang detection MUST be armed for every autonomous `worker` and `overseer` cron
cycle running under the sandbox. The Human interactive clone is out of scope for the *kill*
behavior (a human is present to answer the prompt); see §5-Q5 for the open question on whether
detection runs there as a no-op.
*Verify:* an autonomous cycle that issues an unallowlistable command has detection active; an
interactive session's behavior is as decided in §5-Q5.

**FR2 — Bounded detection with independent liveness.** While an agent-issued command is running, the
system MUST detect that the command has become blocked on an approval that will not arrive, within a
bounded interval, and the detector's ability to act MUST NOT depend on the blocked command
returning. (Recursive application of the dead-man's-switch principle in `breakers.py` — "a dead loop
cannot report its own death.") A detector that can only fire *after* the very command it is watching
unblocks is non-compliant.
*Verify:* inject a command that blocks forever on a prompt; detection fires and acts within the
bound with no external intervention.

**FR3 — No false-kill of sanctioned long-running work.** Detection MUST NOT terminate a legitimately
long-running, allowlisted operation (cross-vendor review calls, test suites, builds) that is making
progress within its own internal time bound. The distinguishing property is that sanctioned long
operations are internally bounded and return control; the hang is not. Any purely-temporal backstop
(FR-adjacent, §5-Q1) MUST have a floor strictly greater than the longest sanctioned operation's own
timeout, so a well-behaved review can never trip it.
*Verify:* a review call that runs to its 300s `AI_REVIEW_TIMEOUT` and returns is never killed by
hang detection; a genuinely unbounded command is.

**FR4 — Clean termination of the hung command tree.** On detection, the system MUST terminate the
blocked command and any subprocesses it spawned, so no orphaned child continues holding the prompt
or a resource.
*Verify:* after a detected hang, no descendant of the killed command remains running.

**FR5 — Termination leaves resumable, uncorrupted state.** Termination MUST leave durable state
(claim/lock/branch/PR-evaluation, cid artifacts) in a condition the existing idempotency and
cold-start recovery model (`correlation.py` `ResumeState`, `claim.py` stale-claim reclamation) can
resume from on a later cycle. Termination MUST NOT leave a half-written durable artifact that a
resuming cycle would read as complete.
*Verify:* a later cycle for the same cid resumes at the correct `ResumeState` and completes the task
without duplicate work.

### Durable recording

**FR6 — Durable, committed hang ledger.** Each detected hang MUST be recorded to a durable,
version-controlled location that is identical across clones, machines, and releases. The record MUST
NOT live under `.claudetmp/` or `.ai-local/` (both are per-clone ephemeral; VF-4). Each record MUST
contain at minimum: the offending command text, the cid, the role (`worker`/`overseer`), a UTC
timestamp, and the disposition taken (killed / aborted / escalated). The record SHOULD contain the
matched unallowlistable pattern *when the matcher makes it determinable*; because the whole premise
is that the parse is not always predictable, an indeterminate-match marker is an acceptable value and
its absence MUST NOT block recording.
*Verify:* a detected hang appends a record with the mandatory fields to a committed path; the record
survives a fresh clone.

**FR7 — Permanent record, expiring directive.** The system MUST distinguish (a) the permanent audit
record that a hang occurred (never expires) from (b) any active *directive derived from* a hang —
"do not reissue this command / this command is escalated / this rewrite is in force." Every directive
of type (b) MUST carry an expiry or a revalidation trigger, after which the command is treated as
novel again and re-evaluated on its merits. A directive with no expiry is non-compliant. (Direct
application of `an-override-must-expire-or-it-becomes-the-policy.md`: the deferral is legitimate, the
amnesia is not — and here, "we permanently suppress this command" would silently become policy as
the sandbox allowlist evolves underneath it.)
*Verify:* an active suppression/rewrite directive has an expiry; past its expiry the same command is
re-evaluated rather than auto-suppressed; the historical record of the original hang remains.

### Next-run behavior change

**FR8 — Startup consultation and sanctioned remediation.** At the start of an autonomous cycle the
system MUST consult the ledger's active directives and MUST NOT blindly reissue a command recorded
as hanging under a still-active directive. The sanctioned remediation, in order, is: (1) use an
already-allowlisted equivalent — per `CLAUDE.md` shell-usage discipline this is normally an existing
committed script; (2) if none exists, the correct fix is to *author a committed script* (which flows
through the normal build/review pipeline) — see §5-Q2 for the open gate question; (3) escalate to a
human if it cannot be remediated. Free-form ad-hoc rewriting of the command into a different
one-liner is NOT a sanctioned first resort: a rewrite that changes behavior is a new fail-open, and
any rewrite the system does apply MUST be recorded so a human can see what was substituted.
*Verify:* a command under an active hang directive is not reissued verbatim; the remediation path
taken is one of the three sanctioned options and is recorded.

**FR9 — Normalized command identity and conservative matching.** "The same command" MUST be matched
on a stable, normalized identity (insensitive to volatile substrings such as timestamps, cids, and
run-specific paths), not on exact bytes. Matching MUST be conservative in the safe direction: when
identity is uncertain the command is treated as *novel* (and re-protected by FR2), never as
*known-good* — because a false "known-good" is the fail-open, whereas a false "novel" merely lets
FR2 re-catch it.
*Verify:* two runs of the same logical command with differing timestamps/cids match one identity;
an ambiguous case is treated as novel.

**FR10 — Recurrence escalation.** Repeated hangs of the *same* normalized command identity MUST
escalate to a human rather than auto-recover indefinitely. The recommended threshold is escalate on
the **second** occurrence of the same identity (auto-remediate once; on the first *recurrence*,
escalate), which is stricter than the generic `breakers.py` poison-pill cap of 3 and is justified by
the override-expiry finding's "the fourth identical override is a policy nobody decided." Separately,
a hang that cannot be remediated into allowlistable form at all MUST escalate on its **first**
occurrence. The exact recurrence count is a §5-Q6 human decision.
*Verify:* the same command hanging twice produces a human escalation, not a third silent retry.

**FR11 — Breaker and failure-count integration.** A hang MUST count toward stopping runaway retry,
but as a *distinct category* from a logic-error failure (the remediation differs). A recurring hang
on a given cid MUST contribute to that cid's failure cap so a hanging task cannot be retried forever;
a single isolated hang MUST NOT trip a global halt of all automation. Pervasive hangs — a threshold
number of *distinct* command identities hanging across cycles in a rolling window, indicating the
sandbox configuration itself is broken — MUST escalate to a human immediately (the distinct-command
count and window are §5-Q6 numbers).
*Verify:* one hang does not halt the loop; repeated same-cid hangs hit the cid cap; many distinct
hangs in the window escalate.

### Cycle disposition, accounting, visibility

**FR12 — Abort the current cycle cleanly (default).** On a detected hang the default disposition MUST
be to abort the current task cycle cleanly — kill, record, release/leave-resumable state, exit — not
to skip the offending step and continue the same cycle. Rationale: after a kill the agent's in-flight
assumption about that command's effect is unverifiable, and continuing in an inconsistent state is
the failure `a-guard-that-doesnt-halt-is-not-a-guard.md` warns against; the cold-start machinery
(FR5) already makes resume-next-cycle safe and cheap. For `overseer`, "abort the cycle" is scoped to
the current cid/PR evaluation, not a halt of all PR review. Whether skip-and-continue is ever
permitted for a *provably* side-effect-free command is §5-Q4.
*Verify:* a hang aborts the current cid's cycle and the next cycle resumes it; other work is
unaffected.

**FR13 — Accounting.** A hang MUST NOT be charged against *token* budget (`budget.py`) — a blocked
prompt spends no tokens. A hang-aborted cycle MUST NOT be counted as productive blast-radius (no PR /
issue / file was produced). The cycle MUST still be recorded as a spent/aborted cycle so the null
outcome is visible and not mistaken for "no work found."
*Verify:* a hang cycle adds zero to token and blast-radius totals but appears as an aborted cycle in
the audit trail.

**FR14 — Human visibility, tiered.** Every detected hang MUST be visible in the existing cycle audit
trail (`cycle_log.py` event vocabulary) in addition to the ledger — not buried in a ledger nobody
reads. A first, auto-recoverable hang needs no human page. A hang that recurs past FR10's threshold,
or that cannot be remediated, MUST produce a durable, tracked, human-addressable artifact through the
repo's standard escalation channel (a filed `needs-human` issue), and — when the hang is tied to a
specific PR/cid (`overseer`) — additionally on that PR. The exact channel mix is §5-Q5.
*Verify:* first hang → audit event + ledger only; escalated hang → a filed tracked issue exists.

### Fail-closed integrity

**FR15 — Fail closed and loud.** The system MUST distinguish an *absent or empty* ledger (safe: no
known hangs — proceed exactly as prior behavior, per the fail-closed-identical baseline in
`convergence-ledger-must-persist.md`) from an *unreadable, corrupt, or unwritable* ledger (unsafe:
escalate to a human, do not proceed as if empty — per `tooling-drift-in-validation-pipelines.md`,
oversight tooling fails open by default and must be made to fail loud). Furthermore, if hang
detection itself cannot be armed for a cycle, that cycle MUST NOT proceed unprotected — an
autonomous cycle with no hang protection is the exact denial-of-oversight condition this work item
exists to remove.
*Verify:* empty ledger → normal run; corrupt/unwritable ledger → escalation, no silent proceed;
detection-arm failure → cycle does not run unprotected.

**FR16 — The remediation path must itself be bounded.** The detect → kill → record → escalate path
MUST NOT itself issue an unallowlistable command or block indefinitely; its own actions (ledger
write, issue filing, kill) MUST be bounded and allowlistable, so the hang-handler cannot become the
next thing that hangs. (Recursive application of `the-gate-must-time-out-its-own-dependencies.md`:
the guard that reviews for unbounded dependency calls must not make one itself.)
*Verify:* every action on the hang-handling path completes within a bound and none can itself trigger
an approval prompt.

---

## 3. Disposition of the draft requirements R1–R5

| Draft | Disposition | Change |
|---|---|---|
| **R1** Detect during the run | **Kept, corrected** | "No output + no return" replaced by the internally-bounded-vs-unbounded discriminator (FR2/FR3, VF-2); "continue or exit cleanly" resolved to *abort by default* (FR12, §5-Q4); added independent-liveness (FR2) and clean-tree termination (FR4/FR5). |
| **R2** Record it durably | **Kept, strengthened** | Extended the exclusion from `.claudetmp/` to `.ai-local/` too (VF-4); made the matched-pattern field best-effort not mandatory (the parse is not always knowable); split permanent-record vs expiring-directive (FR6/FR7, VF-3). |
| **R3** Change next run | **Kept, reordered** | Committed-script remediation promoted from tertiary to primary per `CLAUDE.md` shell discipline (VF-5); ad-hoc rewriting constrained and made recordable; added normalized-identity + conservative matching (FR9). |
| **R4** Don't become a permanent block | **Kept, sharpened** | Expiry applies to the *directive*, not the *record* (FR7). |
| **R5** Fail closed and loudly | **Kept, sharpened** | Distinguished absent/empty (safe) from corrupt/unwritable (escalate), and added "detection-arm failure ⇒ don't run unprotected" (FR15). |

No draft requirement was dropped. The one I most strongly flag is **R3**: automatic command
*rewriting* is a fail-open risk and is deliberately demoted below the committed-script path.

---

## 4. Explicit non-goals

- Removing the sandbox, widening the allowlist, or auto-approving prompts — the sandbox is the
  control; this work makes hangs under it survivable, it does not relax it.
- Guaranteeing zero hangs — impossible per §1; the goal is detect / record / not-repeat, not
  prevent.
- Replacing the existing breakers, dead-man's switch, claim reclamation, or cold-start recovery —
  this layer integrates with them (VF-1).

---

## 5. Product decisions escalated to the human

These are genuine product/policy choices, not things I can settle from the spec. Architect MUST NOT
bind them until ruled. I give a recommended default for each so the human can confirm or override.

**Q1 — What interval constitutes a hang?**
*Recommendation:* Do not rely on a single elapsed-time bound. Primary signal = the prompt-wait state
itself (kill promptly when the harness is detectably blocked on an approval). Backstop = a hard
per-command wall-clock ceiling whose value is **operator-tunable but floored strictly above the
longest sanctioned operation's own timeout** (today `AI_REVIEW_TIMEOUT`=300s and the test-suite
ceiling), so a real review can never trip it. *Human owns:* the concrete backstop value and its
floor.

**Q2 — Does a hang consume cycle budget?**
*Recommendation:* No token charge (nothing was spent). It consumes a cron slot and MUST be recorded
as an aborted cycle, but it is not counted as productive blast-radius (FR13). *Human owns:* confirm
that a hang cycle is "free" against token budget and does not count toward blast-radius caps.

**Q3 — Does it trip a breaker / count toward failure thresholds?**
*Recommendation:* Yes, as a distinct hang category: a recurring same-cid hang contributes to that
cid's poison-pill cap; a single hang does not trip a global halt; pervasive distinct-command hangs
escalate as a suspected sandbox misconfiguration (FR11). *Human owns:* whether hang counts share the
existing failure cap or use a separate, lower one.

**Q4 — Abort the whole cycle, or skip the step and continue?**
*Recommendation:* Abort the current task cycle cleanly by default; do not skip-and-continue, because
the command's effect is unverifiable after a kill and cold-start resume is safe and cheap (FR12).
*Human owns:* whether a *provably* side-effect-free command may ever be skipped-and-continued instead
of aborting.

**Q5 — What does the human see?**
*Recommendation:* Tiered — ledger + audit event always; a filed `needs-human` issue (the repo's
tracked, non-losable channel) on recurrence or unremediable hangs; a PR comment additionally when a
specific PR/cid is implicated (`overseer`). A page on every single hang would train the operator to
ignore pages. *Human owns:* the exact channel mix, and whether detection runs (as a no-op) in
interactive mode at all.

**Q6 — How many recorded hangs before escalating rather than auto-recovering?**
*Recommendation:* Escalate on the **second** occurrence of the same normalized command identity
(auto-recover once), and on the **first** occurrence of any hang that cannot be remediated into
allowlistable form. Separately, escalate immediately when a small number of *distinct* command
identities (recommend 3) hang within a rolling window, signaling systemic breakage. *Human owns:*
the same-identity recurrence count, the distinct-command count, and the window length.

**Additional decision surfaced, not in the original six — Q2′ (gate on self-authored remediation
scripts).** FR8's sanctioned remediation is "author a committed script." An autonomous worker
already opens PRs, but a script written specifically to change the agent's own guardrail behavior is
a self-modification of its operating constraints. *Recommendation:* such a remediation PR is
**human-gated** (not overseer auto-merge), because it changes what the agent is allowed to run.
*Human owns:* whether self-remediation scripts may auto-merge under the normal overseer ceiling or
must be human-reviewed.

---

## Human Review Required

This document authors new requirements (a MEDIUM-or-above spec change), so per my role I self-flag.

**RISK: MEDIUM** — The requirements introduce new autonomous behavior (killing agent-issued
commands, changing next-run command selection, self-authored remediation). The behaviors are
guardrails, but a wrong threshold (Q1) could false-kill a real review (a denial of oversight) and a
too-permissive self-remediation gate (Q2′) could let the agent widen its own effective permissions.
**CONFIDENCE: HIGH** on the requirement set and the finding-grounded corrections to R1–R5;
**LOWER** on the six threshold/channel values, which are correctly the human's to set.
**BLAST RADIUS:** the autonomous worker and overseer loops on every consumer deployment.

**Change classification: STRUCTURAL.** This introduces new required behaviors, new decision points,
and a new agent obligation (consult-ledger-before-issuing-commands) that did not exist before — it
is not clarifying or additive to an existing spec. Per my role, the six escalated policy decisions
(§5, including Q2′) require explicit human sign-off before `architect` binds them. Architect may
begin design against FR1–FR16's settled shape, but the numeric thresholds, the escalation channel,
the interactive-mode question, the skip-vs-abort exception, and the self-remediation gate are held
for the human.
